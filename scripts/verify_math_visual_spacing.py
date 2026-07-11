"""Measure math-exam spacing differences between source and Hancom PDFs.

The report intentionally has no aggregate quality score. Every gate keeps its
measurements, configured thresholds, and pass/fail result in separate fields.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
from typing import Any, Sequence

import fitz
import numpy as np
from PIL import Image


SCHEMA_VERSION = 1
TOOL_VERSION = "1.0"
COLUMN_RANGES = {
    "left": (0.055, 0.485),
    "right": (0.515, 0.945),
}
CONTENT_TOP = 0.11
CONTENT_BOTTOM = 0.90
PROBLEM_TOKEN_RE = re.compile(r"^([1-9]|[12][0-9]|30)[.)]$")
CIRCLED_CHOICES = {
    "\u2460": 1,
    "\u2461": 2,
    "\u2462": 3,
    "\u2463": 4,
    "\u2464": 5,
}


class ValidationError(RuntimeError):
    """Raised for an input or analysis condition that prevents a report."""


@dataclass(frozen=True)
class Thresholds:
    max_page_aspect_ratio_delta: float = 0.005
    max_profile_earth_mover_distance: float = 0.035
    min_profile_correlation: float = 0.45
    max_profile_ink_relative_error: float = 0.35
    min_profile_band_f1: float = 0.55
    max_profile_band_anchor_delta: float = 0.018
    max_problem_anchor_delta: float = 0.018
    max_divider_x_delta: float = 0.020
    max_divider_edge_delta: float = 0.030
    max_box_edge_delta: float = 0.030
    max_box_gap_delta: float = 0.030
    max_choice_row_anchor_delta: float = 0.018
    max_choice_row_gap_delta: float = 0.018


def _rounded(value: float | int | None, digits: int = 6) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return round(float(value), digits)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pdf_input(path: Path, document: fitz.Document) -> dict[str, Any]:
    first_size = None
    if document.page_count:
        rect = document[0].rect
        first_size = [round(float(rect.width), 3), round(float(rect.height), 3)]
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "page_count": document.page_count,
        "first_page_size_points": first_size,
    }


def _render_gray(page: fitz.Page, width: int, height: int) -> np.ndarray:
    matrix = fitz.Matrix(width / float(page.rect.width), height / float(page.rect.height))
    pixmap = page.get_pixmap(
        matrix=matrix,
        colorspace=fitz.csGRAY,
        alpha=False,
        annots=False,
    )
    array = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )[:, :, 0]
    if array.shape != (height, width):
        image = Image.fromarray(array, mode="L")
        array = np.asarray(
            image.resize((width, height), Image.Resampling.LANCZOS),
            dtype=np.uint8,
        )
    return array.copy()


def _remove_long_rules(mask: np.ndarray) -> np.ndarray:
    clean = mask.copy()
    if clean.size == 0:
        return clean
    long_columns = clean.sum(axis=0) >= clean.shape[0] * 0.30
    long_rows = clean.sum(axis=1) >= clean.shape[1] * 0.30
    clean[:, long_columns] = False
    clean[long_rows, :] = False
    return clean


def _text_ink_mask(
    page: fitz.Page,
    gray: np.ndarray,
    ink_threshold: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    height, width = gray.shape
    geometry = np.zeros((height, width), dtype=bool)
    span_count = 0
    character_count = 0
    try:
        raw = page.get_text("rawdict")
    except Exception:
        raw = {"blocks": []}

    scale_x = width / float(page.rect.width)
    scale_y = height / float(page.rect.height)
    pad_x = max(1, int(round(scale_x * 0.8)))
    pad_y = max(1, int(round(scale_y * 0.8)))
    for block in raw.get("blocks") or []:
        if int(block.get("type", -1)) != 0:
            continue
        for line in block.get("lines") or []:
            for span in line.get("spans") or []:
                bbox = span.get("bbox")
                if not bbox or len(bbox) != 4:
                    continue
                x0 = max(0, int(np.floor(float(bbox[0]) * scale_x)) - pad_x)
                y0 = max(0, int(np.floor(float(bbox[1]) * scale_y)) - pad_y)
                x1 = min(width, int(np.ceil(float(bbox[2]) * scale_x)) + pad_x)
                y1 = min(height, int(np.ceil(float(bbox[3]) * scale_y)) + pad_y)
                if x1 <= x0 or y1 <= y0:
                    continue
                geometry[y0:y1, x0:x1] = True
                span_count += 1
                characters = span.get("chars") or []
                character_count += len(characters)

    raw_ink = gray < ink_threshold
    if span_count:
        mask = raw_ink & geometry
        mode = "rendered_ink_intersected_with_pdf_text_spans"
    else:
        mask = _remove_long_rules(raw_ink)
        mode = "rendered_ink_with_long_rules_removed_fallback"
    return mask, {
        "mode": mode,
        "pdf_text_span_count": span_count,
        "pdf_text_character_count": character_count,
        "raw_ink_pixels": int(raw_ink.sum()),
        "profile_ink_pixels": int(mask.sum()),
    }


def _bridge_short_gaps(active: np.ndarray, max_gap: int = 2) -> np.ndarray:
    result = active.copy()
    index = 0
    while index < result.size:
        if result[index]:
            index += 1
            continue
        start = index
        while index < result.size and not result[index]:
            index += 1
        if start > 0 and index < result.size and index - start <= max_gap:
            result[start:index] = True
    return result


def _sample_profile(row_counts: np.ndarray, width: int, bins: int) -> list[float]:
    edges = np.linspace(0, row_counts.size, bins + 1)
    sampled: list[float] = []
    for index in range(bins):
        start = int(np.floor(edges[index]))
        end = int(np.floor(edges[index + 1]))
        if end <= start:
            end = min(row_counts.size, start + 1)
        area = max(1, (end - start) * width)
        sampled.append(round(float(row_counts[start:end].sum()) / area, 7))
    return sampled


def _active_bands(
    row_counts: np.ndarray,
    column_width: int,
    y_offset: int,
    page_height: int,
) -> list[dict[str, Any]]:
    minimum_ink = max(2, int(round(column_width * 0.0015)))
    active = _bridge_short_gaps(row_counts >= minimum_ink)
    bands: list[dict[str, Any]] = []
    index = 0
    while index < active.size:
        if not active[index]:
            index += 1
            continue
        start = index
        while index < active.size and active[index]:
            index += 1
        end = index
        weights = row_counts[start:end].astype(np.float64)
        total = float(weights.sum())
        if total < column_width * 0.004:
            continue
        positions = np.arange(start, end, dtype=np.float64)
        center = float((positions * weights).sum() / total) if total else (start + end) / 2.0
        bands.append(
            {
                "top_ratio": round((y_offset + start) / page_height, 6),
                "bottom_ratio": round((y_offset + end) / page_height, 6),
                "center_ratio": round((y_offset + center) / page_height, 6),
                "ink_pixels": int(total),
            }
        )
    return bands


def _profile_payload(
    mask: np.ndarray,
    column: str,
    bins: int,
) -> dict[str, Any]:
    height, width = mask.shape
    left, right = COLUMN_RANGES[column]
    x0, x1 = int(round(width * left)), int(round(width * right))
    y0, y1 = int(round(height * CONTENT_TOP)), int(round(height * CONTENT_BOTTOM))
    roi = mask[y0:y1, x0:x1]
    row_counts = roi.sum(axis=1).astype(np.int64)
    ink_pixels = int(row_counts.sum())
    return {
        "roi_normalized": {
            "left": left,
            "top": CONTENT_TOP,
            "right": right,
            "bottom": CONTENT_BOTTOM,
        },
        "roi_pixels": [x0, y0, x1, y1],
        "ink_pixels": ink_pixels,
        "ink_fraction": round(ink_pixels / max(1, roi.size), 7),
        "sampled_row_ink_fraction": _sample_profile(row_counts, roi.shape[1], bins),
        "active_bands": _active_bands(row_counts, roi.shape[1], y0, height),
        "_row_counts": row_counts,
    }


def _profile_correlation(source: np.ndarray, output: np.ndarray) -> float:
    source = np.asarray(source, dtype=np.float64)
    output = np.asarray(output, dtype=np.float64)
    kernel = np.ones(5, dtype=np.float64) / 5.0
    source = np.convolve(source, kernel, mode="same")
    output = np.convolve(output, kernel, mode="same")
    source_std = float(source.std())
    output_std = float(output.std())
    if source_std <= 1e-12 and output_std <= 1e-12:
        return 1.0 if np.allclose(source, output) else 0.0
    if source_std <= 1e-12 or output_std <= 1e-12:
        return 0.0
    return float(np.corrcoef(source, output)[0, 1])


def _max_shifted_profile_correlation(
    source: np.ndarray,
    output: np.ndarray,
    max_shift_rows: int,
) -> tuple[float, int]:
    best_correlation = _profile_correlation(source, output)
    best_shift = 0
    for shift in range(-max_shift_rows, max_shift_rows + 1):
        if shift == 0:
            continue
        if shift < 0:
            source_slice = source[-shift:]
            output_slice = output[: output.size + shift]
        else:
            source_slice = source[: source.size - shift]
            output_slice = output[shift:]
        if source_slice.size < 8 or output_slice.size < 8:
            continue
        correlation = _profile_correlation(source_slice, output_slice)
        if correlation > best_correlation:
            best_correlation = correlation
            best_shift = shift
    return best_correlation, best_shift


def _match_band_centers(
    source: list[dict[str, Any]],
    output: list[dict[str, Any]],
    tolerance: float,
) -> dict[str, Any]:
    candidates: list[tuple[float, int, int]] = []
    for source_index, source_band in enumerate(source):
        for output_index, output_band in enumerate(output):
            delta = abs(
                float(source_band["center_ratio"]) - float(output_band["center_ratio"])
            )
            if delta <= tolerance:
                candidates.append((delta, source_index, output_index))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    used_source: set[int] = set()
    used_output: set[int] = set()
    pairs: list[dict[str, Any]] = []
    for delta, source_index, output_index in candidates:
        if source_index in used_source or output_index in used_output:
            continue
        used_source.add(source_index)
        used_output.add(output_index)
        pairs.append(
            {
                "source_index": source_index,
                "output_index": output_index,
                "source_center_ratio": source[source_index]["center_ratio"],
                "output_center_ratio": output[output_index]["center_ratio"],
                "absolute_delta_ratio": round(delta, 6),
            }
        )
    pairs.sort(key=lambda item: int(item["source_index"]))
    matched = len(pairs)
    denominator = len(source) + len(output)
    f1 = (2.0 * matched / denominator) if denominator else 1.0
    return {
        "pairs": pairs,
        "source_unmatched_indices": sorted(set(range(len(source))) - used_source),
        "output_unmatched_indices": sorted(set(range(len(output))) - used_output),
        "f1": round(f1, 6),
        "max_matched_anchor_delta_ratio": (
            max((float(pair["absolute_delta_ratio"]) for pair in pairs), default=None)
        ),
    }


def _compare_profiles(
    source_payload: dict[str, Any],
    output_payload: dict[str, Any],
    thresholds: Thresholds,
) -> dict[str, Any]:
    source_rows = source_payload.pop("_row_counts")
    output_rows = output_payload.pop("_row_counts")
    source_total = int(source_rows.sum())
    output_total = int(output_rows.sum())
    if source_total:
        source_distribution = source_rows.astype(np.float64) / source_total
        output_distribution = (
            output_rows.astype(np.float64) / output_total
            if output_total
            else np.zeros_like(source_distribution)
        )
        ink_ratio = output_total / source_total
        ink_error = abs(output_total - source_total) / source_total
    elif output_total:
        source_distribution = np.zeros_like(source_rows, dtype=np.float64)
        output_distribution = output_rows.astype(np.float64) / output_total
        ink_ratio = None
        ink_error = 1.0
    else:
        source_distribution = np.zeros_like(source_rows, dtype=np.float64)
        output_distribution = np.zeros_like(output_rows, dtype=np.float64)
        ink_ratio = 1.0
        ink_error = 0.0

    total_variation = 0.5 * float(np.abs(source_distribution - output_distribution).sum())
    earth_mover = float(
        np.abs(np.cumsum(source_distribution) - np.cumsum(output_distribution)).mean()
    )
    zero_lag_correlation = _profile_correlation(source_rows, output_rows)
    max_shift_rows = max(
        1,
        int(
            round(
                source_rows.size
                * thresholds.max_profile_band_anchor_delta
                / (CONTENT_BOTTOM - CONTENT_TOP)
            )
        ),
    )
    shifted_correlation, best_shift_rows = _max_shifted_profile_correlation(
        source_rows, output_rows, max_shift_rows
    )
    band_match = _match_band_centers(
        source_payload["active_bands"],
        output_payload["active_bands"],
        thresholds.max_profile_band_anchor_delta,
    )
    max_band_delta = band_match["max_matched_anchor_delta_ratio"]
    measurements = {
        "source": source_payload,
        "output": output_payload,
        "comparison": {
            "earth_mover_distance_ratio": round(earth_mover, 6),
            "total_variation_distance": round(total_variation, 6),
            "zero_lag_pearson_correlation": round(zero_lag_correlation, 6),
            "max_shifted_pearson_correlation": round(shifted_correlation, 6),
            "best_output_shift_rows": best_shift_rows,
            "best_output_shift_page_ratio": round(
                best_shift_rows
                / max(1, source_rows.size)
                * (CONTENT_BOTTOM - CONTENT_TOP),
                6,
            ),
            "output_to_source_ink_ratio": _rounded(ink_ratio),
            "ink_relative_error": round(ink_error, 6),
            "active_band_matching": band_match,
        },
    }
    gates = {
        "earth_mover_distance": earth_mover
        <= thresholds.max_profile_earth_mover_distance,
        "shifted_correlation": shifted_correlation >= thresholds.min_profile_correlation,
        "ink_amount": ink_error <= thresholds.max_profile_ink_relative_error,
        "active_band_f1": band_match["f1"] >= thresholds.min_profile_band_f1,
        "active_band_anchor": max_band_delta is None
        or float(max_band_delta) <= thresholds.max_profile_band_anchor_delta,
    }
    return {
        "measurements": measurements,
        "thresholds": {
            "max_earth_mover_distance_ratio": thresholds.max_profile_earth_mover_distance,
            "min_max_shifted_pearson_correlation": thresholds.min_profile_correlation,
            "max_ink_relative_error": thresholds.max_profile_ink_relative_error,
            "min_active_band_f1": thresholds.min_profile_band_f1,
            "max_active_band_anchor_delta_ratio": thresholds.max_profile_band_anchor_delta,
        },
        "gates": gates,
        "pass": all(gates.values()),
    }


def _column_for_x(normalized_x: float) -> str:
    return "left" if normalized_x < 0.5 else "right"


def _anchor_payload(
    number: int,
    column: str,
    bbox: tuple[float, float, float, float],
    page: fitz.Page,
) -> dict[str, Any]:
    x0, y0, x1, y1 = bbox
    return {
        "number": number,
        "column": column,
        "bbox_points": [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)],
        "bbox_normalized": [
            round(x0 / page.rect.width, 6),
            round(y0 / page.rect.height, 6),
            round(x1 / page.rect.width, 6),
            round(y1 / page.rect.height, 6),
        ],
        "top_ratio": round(y0 / page.rect.height, 6),
        "left_ratio": round(x0 / page.rect.width, 6),
    }


def _extract_problem_anchors(page: fitz.Page) -> tuple[list[dict[str, Any]], list[int]]:
    anchors: list[dict[str, Any]] = []
    duplicates: list[int] = []
    seen: set[int] = set()
    for word in page.get_text("words", sort=True):
        token = str(word[4]).strip().replace(" ", "")
        match = PROBLEM_TOKEN_RE.fullmatch(token)
        if not match:
            continue
        x0, y0, x1, y1 = (float(value) for value in word[:4])
        normalized_x = x0 / page.rect.width
        normalized_y = y0 / page.rect.height
        in_left_lead = 0.04 <= normalized_x <= 0.18
        in_right_lead = 0.47 <= normalized_x <= 0.62
        if not (in_left_lead or in_right_lead):
            continue
        if not (CONTENT_TOP <= normalized_y <= 0.88):
            continue
        number = int(match.group(1))
        if number in seen:
            duplicates.append(number)
            continue
        seen.add(number)
        column = "left" if in_left_lead else "right"
        anchors.append(_anchor_payload(number, column, (x0, y0, x1, y1), page))
    anchors.sort(key=lambda item: (int(item["number"]), str(item["column"])))
    return anchors, sorted(duplicates)


def _compare_problem_anchors(
    source: list[dict[str, Any]],
    output: list[dict[str, Any]],
    source_duplicates: list[int],
    output_duplicates: list[int],
    output_page: fitz.Page,
    threshold: float,
) -> dict[str, Any]:
    source_by_number = {int(item["number"]): item for item in source}
    output_by_number = {int(item["number"]): item for item in output}
    common = sorted(set(source_by_number) & set(output_by_number))
    pairs: list[dict[str, Any]] = []
    for number in common:
        source_item = source_by_number[number]
        output_item = output_by_number[number]
        top_delta = abs(float(source_item["top_ratio"]) - float(output_item["top_ratio"]))
        left_delta = abs(float(source_item["left_ratio"]) - float(output_item["left_ratio"]))
        delta_points = top_delta * float(output_page.rect.height)
        pairs.append(
            {
                "number": number,
                "source": source_item,
                "output": output_item,
                "same_column": source_item["column"] == output_item["column"],
                "top_absolute_delta_ratio": round(top_delta, 6),
                "top_absolute_delta_output_points": round(delta_points, 3),
                "top_absolute_delta_mm": round(delta_points * 25.4 / 72.0, 3),
                "left_absolute_delta_ratio": round(left_delta, 6),
            }
        )
    missing = sorted(set(source_by_number) - set(output_by_number))
    unexpected = sorted(set(output_by_number) - set(source_by_number))
    max_delta = max(
        (float(item["top_absolute_delta_ratio"]) for item in pairs), default=None
    )
    pass_value = (
        not missing
        and not unexpected
        and not source_duplicates
        and not output_duplicates
        and all(bool(item["same_column"]) for item in pairs)
        and (max_delta is None or max_delta <= threshold)
    )
    status = "assessed" if source else ("not_present" if not output else "source_not_detected")
    return {
        "measurements": {
            "status": status,
            "source_anchors": source,
            "output_anchors": output,
            "pairs": pairs,
            "missing_output_numbers": missing,
            "unexpected_output_numbers": unexpected,
            "source_duplicate_numbers": source_duplicates,
            "output_duplicate_numbers": output_duplicates,
            "max_top_absolute_delta_ratio": _rounded(max_delta),
        },
        "thresholds": {
            "max_top_absolute_delta_ratio": threshold,
            "require_same_column": True,
            "require_exact_number_set": True,
            "allow_duplicate_number_anchors": False,
        },
        "pass": pass_value,
    }


def _dark_color(value: Any, limit: float = 0.95) -> bool:
    if value is None:
        return False
    try:
        components = [float(component) for component in value]
    except (TypeError, ValueError):
        return False
    return bool(components) and max(components) < limit


def _divider_payload(
    method: str,
    x: float,
    top: float,
    bottom: float,
    candidate_count: int,
    page: fitz.Page,
    **extra: Any,
) -> dict[str, Any]:
    if bottom < top:
        top, bottom = bottom, top
    result = {
        "present": True,
        "method": method,
        "x_points": round(x, 3),
        "top_points": round(top, 3),
        "bottom_points": round(bottom, 3),
        "x_ratio": round(x / page.rect.width, 6),
        "top_ratio": round(top / page.rect.height, 6),
        "bottom_ratio": round(bottom / page.rect.height, 6),
        "length_ratio": round((bottom - top) / page.rect.height, 6),
        "candidate_count": candidate_count,
    }
    result.update(extra)
    return result


def _vector_divider(page: fitz.Page) -> dict[str, Any] | None:
    candidates: list[tuple[float, float, float]] = []

    def add(x: float, top: float, bottom: float) -> None:
        if bottom < top:
            top, bottom = bottom, top
        x_ratio = x / page.rect.width
        length_ratio = (bottom - top) / page.rect.height
        if abs(x_ratio - 0.5) <= 0.06 and length_ratio >= 0.30:
            candidates.append((x, top, bottom))

    for drawing in page.get_drawings():
        stroke_visible = _dark_color(drawing.get("color"))
        fill_visible = _dark_color(drawing.get("fill"))
        rect = drawing.get("rect")
        if rect is not None and (stroke_visible or fill_visible):
            if abs(float(rect.width)) <= max(3.0, page.rect.width * 0.015):
                add((float(rect.x0) + float(rect.x1)) / 2.0, float(rect.y0), float(rect.y1))
        if not stroke_visible:
            continue
        for item in drawing.get("items") or []:
            if not item or item[0] != "l" or len(item) < 3:
                continue
            start, end = item[1], item[2]
            if abs(float(start.x) - float(end.x)) <= max(2.0, page.rect.width * 0.005):
                add((float(start.x) + float(end.x)) / 2.0, float(start.y), float(end.y))
    if not candidates:
        return None
    unique = sorted(
        {
            (round(x, 3), round(top, 3), round(bottom, 3))
            for x, top, bottom in candidates
        }
    )
    best = max(
        unique,
        key=lambda item: (item[2] - item[1], -abs(item[0] / page.rect.width - 0.5)),
    )
    return _divider_payload("vector", *best, len(unique), page)


def _longest_true_run(values: np.ndarray) -> int:
    if values.size == 0 or not bool(values.any()):
        return 0
    padded = np.pad(values.astype(np.int8), (1, 1), constant_values=0)
    changes = np.diff(padded)
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    return int(np.max(ends - starts)) if starts.size and ends.size else 0


def _raster_divider(
    page: fitz.Page,
    gray: np.ndarray,
    ink_threshold: int,
) -> dict[str, Any] | None:
    mask = gray < ink_threshold
    height, width = mask.shape
    x0, x1 = int(width * 0.44), int(width * 0.56)
    y0, y1 = int(height * 0.07), int(height * 0.95)
    body = mask[y0:y1, x0:x1]
    candidates: list[tuple[float, float, int, np.ndarray]] = []
    for local_x in range(body.shape[1]):
        column = body[:, local_x]
        occupancy = float(column.mean())
        run_ratio = _longest_true_run(column) / max(1, body.shape[0])
        if occupancy >= 0.30 and run_ratio >= 0.25:
            candidates.append((run_ratio, occupancy, local_x, column))
    if not candidates:
        return None
    run_ratio, occupancy, local_x, column = max(
        candidates,
        key=lambda item: (item[0], item[1], -abs((x0 + item[2]) / width - 0.5)),
    )
    active = np.flatnonzero(column)
    x_points = (x0 + local_x + 0.5) / width * page.rect.width
    top_points = (y0 + int(active[0])) / height * page.rect.height
    bottom_points = (y0 + int(active[-1]) + 1) / height * page.rect.height
    return _divider_payload(
        "raster_fallback",
        x_points,
        top_points,
        bottom_points,
        len(candidates),
        page,
        column_occupancy_ratio=round(occupancy, 6),
        longest_run_ratio=round(run_ratio, 6),
    )


def _detect_divider(
    page: fitz.Page,
    gray: np.ndarray,
    ink_threshold: int,
) -> dict[str, Any]:
    return _vector_divider(page) or _raster_divider(page, gray, ink_threshold) or {
        "present": False,
        "method": None,
        "candidate_count": 0,
    }


def _compare_dividers(
    source: dict[str, Any],
    output: dict[str, Any],
    thresholds: Thresholds,
) -> dict[str, Any]:
    both_present = bool(source.get("present")) and bool(output.get("present"))
    same_presence = bool(source.get("present")) == bool(output.get("present"))
    if both_present:
        x_delta = abs(float(source["x_ratio"]) - float(output["x_ratio"]))
        top_delta = abs(float(source["top_ratio"]) - float(output["top_ratio"]))
        bottom_delta = abs(float(source["bottom_ratio"]) - float(output["bottom_ratio"]))
        length_delta = abs(float(source["length_ratio"]) - float(output["length_ratio"]))
    else:
        x_delta = top_delta = bottom_delta = length_delta = None
    pass_value = same_presence and (
        not both_present
        or (
            x_delta is not None
            and x_delta <= thresholds.max_divider_x_delta
            and top_delta is not None
            and top_delta <= thresholds.max_divider_edge_delta
            and bottom_delta is not None
            and bottom_delta <= thresholds.max_divider_edge_delta
        )
    )
    return {
        "measurements": {
            "source": source,
            "output": output,
            "same_presence": same_presence,
            "x_absolute_delta_ratio": _rounded(x_delta),
            "top_absolute_delta_ratio": _rounded(top_delta),
            "bottom_absolute_delta_ratio": _rounded(bottom_delta),
            "length_absolute_delta_ratio": _rounded(length_delta),
        },
        "thresholds": {
            "max_x_absolute_delta_ratio": thresholds.max_divider_x_delta,
            "max_top_or_bottom_absolute_delta_ratio": thresholds.max_divider_edge_delta,
            "require_same_presence": True,
        },
        "pass": pass_value,
    }


def _box_candidate(rect: tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = rect
    width = x1 - x0
    height = y1 - y0
    if not (0.10 <= width <= 0.46 and 0.012 <= height <= 0.30):
        return False
    if not (0.11 <= y0 and y1 <= 0.88):
        return False
    center = (x0 + x1) / 2.0
    return (center < 0.5 and x1 <= 0.495) or (center >= 0.5 and x0 >= 0.49)


def _interval_coverage(
    segments: list[tuple[float, float, float]],
    target_y: float,
    left: float,
    right: float,
    tolerance: float,
) -> float:
    intervals: list[tuple[float, float]] = []
    for y, x0, x1 in segments:
        if abs(y - target_y) > tolerance:
            continue
        start, end = max(left, x0), min(right, x1)
        if end > start:
            intervals.append((start, end))
    if not intervals:
        return 0.0
    intervals.sort()
    merged: list[list[float]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1] + tolerance:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    covered = sum(end - start for start, end in merged)
    return covered / max(1e-9, right - left)


def _deduplicate_rects(
    rects: list[tuple[float, float, float, float]],
    tolerance: float = 0.004,
) -> list[tuple[float, float, float, float]]:
    result: list[tuple[float, float, float, float]] = []
    for rect in sorted(rects, key=lambda item: (item[1], item[0], item[3], item[2])):
        if any(max(abs(a - b) for a, b in zip(rect, previous)) <= tolerance for previous in result):
            continue
        result.append(rect)
    return result


def _detect_boxes(page: fitz.Page) -> list[tuple[float, float, float, float]]:
    horizontal: list[tuple[float, float, float]] = []
    vertical: list[tuple[float, float, float]] = []
    direct: list[tuple[float, float, float, float]] = []
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)

    def add_segment(x0: float, y0: float, x1: float, y1: float) -> None:
        nx0, nx1 = x0 / page_width, x1 / page_width
        ny0, ny1 = y0 / page_height, y1 / page_height
        if abs(ny1 - ny0) <= 0.0015 and abs(nx1 - nx0) >= 0.03:
            horizontal.append(((ny0 + ny1) / 2.0, min(nx0, nx1), max(nx0, nx1)))
        elif abs(nx1 - nx0) <= 0.0015 and abs(ny1 - ny0) >= 0.012:
            vertical.append(((nx0 + nx1) / 2.0, min(ny0, ny1), max(ny0, ny1)))

    for drawing in page.get_drawings():
        stroke_visible = _dark_color(drawing.get("color"))
        fill_visible = _dark_color(drawing.get("fill"))
        for item in drawing.get("items") or []:
            if not item:
                continue
            if item[0] == "l" and stroke_visible and len(item) >= 3:
                add_segment(float(item[1].x), float(item[1].y), float(item[2].x), float(item[2].y))
            elif item[0] == "re" and len(item) >= 2:
                rect = item[1]
                normalized = (
                    float(rect.x0) / page_width,
                    float(rect.y0) / page_height,
                    float(rect.x1) / page_width,
                    float(rect.y1) / page_height,
                )
                if (stroke_visible or fill_visible) and _box_candidate(normalized):
                    direct.append(normalized)
                if stroke_visible:
                    add_segment(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y0))
                    add_segment(float(rect.x0), float(rect.y1), float(rect.x1), float(rect.y1))
                    add_segment(float(rect.x0), float(rect.y0), float(rect.x0), float(rect.y1))
                    add_segment(float(rect.x1), float(rect.y0), float(rect.x1), float(rect.y1))

    horizontal = sorted(set(tuple(round(value, 6) for value in item) for item in horizontal))
    vertical = sorted(set(tuple(round(value, 6) for value in item) for item in vertical))
    assembled: list[tuple[float, float, float, float]] = []
    tolerance = 0.003
    for left_index, left_line in enumerate(vertical):
        left_x, left_top, left_bottom = left_line
        for right_line in vertical[left_index + 1 :]:
            right_x, right_top, right_bottom = right_line
            if abs(left_top - right_top) > tolerance or abs(left_bottom - right_bottom) > tolerance:
                continue
            top = (left_top + right_top) / 2.0
            bottom = (left_bottom + right_bottom) / 2.0
            rect = (left_x, top, right_x, bottom)
            if not _box_candidate(rect):
                continue
            has_interior_vertical = any(
                left_x + tolerance < candidate_x < right_x - tolerance
                and abs(candidate_top - top) <= tolerance
                and abs(candidate_bottom - bottom) <= tolerance
                for candidate_x, candidate_top, candidate_bottom in vertical
            )
            if has_interior_vertical:
                continue
            top_coverage = _interval_coverage(horizontal, top, left_x, right_x, tolerance * 1.5)
            bottom_coverage = _interval_coverage(
                horizontal, bottom, left_x, right_x, tolerance * 1.5
            )
            if top_coverage >= 0.65 and bottom_coverage >= 0.65:
                assembled.append(rect)
    return _deduplicate_rects(direct + assembled)


def _rect_payload(
    rect: tuple[float, float, float, float],
    page: fitz.Page,
    identifier: str,
) -> dict[str, Any]:
    x0, y0, x1, y1 = rect
    return {
        "id": identifier,
        "column": _column_for_x((x0 + x1) / 2.0),
        "edges_normalized": {
            "left": round(x0, 6),
            "top": round(y0, 6),
            "right": round(x1, 6),
            "bottom": round(y1, 6),
        },
        "edges_points": {
            "left": round(x0 * page.rect.width, 3),
            "top": round(y0 * page.rect.height, 3),
            "right": round(x1 * page.rect.width, 3),
            "bottom": round(y1 * page.rect.height, 3),
        },
        "width_ratio": round(x1 - x0, 6),
        "height_ratio": round(y1 - y0, 6),
    }


def _compare_boxes(
    source_rects: list[tuple[float, float, float, float]],
    output_rects: list[tuple[float, float, float, float]],
    source_page: fitz.Page,
    output_page: fitz.Page,
    thresholds: Thresholds,
) -> dict[str, Any]:
    source = [
        _rect_payload(rect, source_page, f"source-box-{index + 1}")
        for index, rect in enumerate(source_rects)
    ]
    output = [
        _rect_payload(rect, output_page, f"output-box-{index + 1}")
        for index, rect in enumerate(output_rects)
    ]
    candidates: list[tuple[float, int, int]] = []
    for source_index, source_rect in enumerate(source_rects):
        for output_index, output_rect in enumerate(output_rects):
            if _column_for_x((source_rect[0] + source_rect[2]) / 2.0) != _column_for_x(
                (output_rect[0] + output_rect[2]) / 2.0
            ):
                continue
            cost = sum(abs(a - b) for a, b in zip(source_rect, output_rect))
            candidates.append((cost, source_index, output_index))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    used_source: set[int] = set()
    used_output: set[int] = set()
    raw_pairs: list[tuple[int, int]] = []
    for _cost, source_index, output_index in candidates:
        if source_index in used_source or output_index in used_output:
            continue
        used_source.add(source_index)
        used_output.add(output_index)
        raw_pairs.append((source_index, output_index))
    raw_pairs.sort()

    pairs: list[dict[str, Any]] = []
    for source_index, output_index in raw_pairs:
        source_rect = source_rects[source_index]
        output_rect = output_rects[output_index]
        deltas = [abs(a - b) for a, b in zip(source_rect, output_rect)]
        max_delta = max(deltas)
        pairs.append(
            {
                "source_index": source_index,
                "output_index": output_index,
                "source_id": source[source_index]["id"],
                "output_id": output[output_index]["id"],
                "edge_absolute_deltas_ratio": {
                    key: round(value, 6)
                    for key, value in zip(("left", "top", "right", "bottom"), deltas)
                },
                "max_edge_absolute_delta_ratio": round(max_delta, 6),
                "pass": max_delta <= thresholds.max_box_edge_delta,
            }
        )

    spacing_pairs: list[dict[str, Any]] = []
    source_rank: dict[int, int] = {}
    output_rank: dict[int, int] = {}
    for column in COLUMN_RANGES:
        source_indices = sorted(
            [index for index, item in enumerate(source) if item["column"] == column],
            key=lambda index: source_rects[index][1],
        )
        output_indices = sorted(
            [index for index, item in enumerate(output) if item["column"] == column],
            key=lambda index: output_rects[index][1],
        )
        source_rank.update({index: rank for rank, index in enumerate(source_indices)})
        output_rank.update({index: rank for rank, index in enumerate(output_indices)})
    for first, second in zip(raw_pairs, raw_pairs[1:]):
        first_source, first_output = first
        second_source, second_output = second
        if source[first_source]["column"] != source[second_source]["column"]:
            continue
        if source_rank.get(second_source) != source_rank.get(first_source, -2) + 1:
            continue
        if output_rank.get(second_output) != output_rank.get(first_output, -2) + 1:
            continue
        source_gap = source_rects[second_source][1] - source_rects[first_source][3]
        output_gap = output_rects[second_output][1] - output_rects[first_output][3]
        gap_delta = abs(source_gap - output_gap)
        spacing_pairs.append(
            {
                "column": source[first_source]["column"],
                "source_box_ids": [source[first_source]["id"], source[second_source]["id"]],
                "output_box_ids": [output[first_output]["id"], output[second_output]["id"]],
                "source_vertical_gap_ratio": round(source_gap, 6),
                "output_vertical_gap_ratio": round(output_gap, 6),
                "absolute_gap_delta_ratio": round(gap_delta, 6),
                "pass": gap_delta <= thresholds.max_box_gap_delta,
            }
        )
    unmatched_source = sorted(set(range(len(source))) - used_source)
    unmatched_output = sorted(set(range(len(output))) - used_output)
    pass_value = (
        not unmatched_source
        and not unmatched_output
        and all(bool(pair["pass"]) for pair in pairs)
        and all(bool(pair["pass"]) for pair in spacing_pairs)
    )
    return {
        "measurements": {
            "source_boxes": source,
            "output_boxes": output,
            "matched_pairs": pairs,
            "vertical_spacing_pairs": spacing_pairs,
            "unmatched_source_box_indices": unmatched_source,
            "unmatched_output_box_indices": unmatched_output,
            "source_box_count": len(source),
            "output_box_count": len(output),
        },
        "thresholds": {
            "max_edge_absolute_delta_ratio": thresholds.max_box_edge_delta,
            "max_vertical_gap_absolute_delta_ratio": thresholds.max_box_gap_delta,
            "require_equal_box_count": True,
            "require_same_column": True,
        },
        "pass": pass_value,
    }


def _choice_markers(page: fitz.Page) -> dict[str, list[dict[str, Any]]]:
    markers: dict[str, list[dict[str, Any]]] = {"left": [], "right": []}
    for word in page.get_text("words", sort=True):
        text = str(word[4])
        values = [CIRCLED_CHOICES[character] for character in text if character in CIRCLED_CHOICES]
        if not values:
            continue
        x0, y0, x1, y1 = (float(value) for value in word[:4])
        center_x = (x0 + x1) / 2.0 / page.rect.width
        center_y = (y0 + y1) / 2.0 / page.rect.height
        if not (CONTENT_TOP <= center_y <= 0.88):
            continue
        column = _column_for_x(center_x)
        for value in values:
            markers[column].append(
                {
                    "value": value,
                    "x_ratio": round(center_x, 6),
                    "y_ratio": round(center_y, 6),
                    "bbox_points": [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)],
                }
            )
    return markers


def _cluster_choice_rows(
    markers: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {"left": [], "right": []}
    tolerance = 0.006
    for column, column_markers in markers.items():
        rows: list[list[dict[str, Any]]] = []
        for marker in sorted(column_markers, key=lambda item: (item["y_ratio"], item["x_ratio"])):
            if rows:
                anchor = sum(float(item["y_ratio"]) for item in rows[-1]) / len(rows[-1])
                if abs(float(marker["y_ratio"]) - anchor) <= tolerance:
                    rows[-1].append(marker)
                    continue
            rows.append([marker])
        payloads: list[dict[str, Any]] = []
        previous_anchor: float | None = None
        for index, row in enumerate(rows):
            row.sort(key=lambda item: (item["x_ratio"], item["value"]))
            anchor = sum(float(item["y_ratio"]) for item in row) / len(row)
            spread = max(float(item["y_ratio"]) for item in row) - min(
                float(item["y_ratio"]) for item in row
            )
            signature = [int(item["value"]) for item in row]
            payloads.append(
                {
                    "index": index,
                    "signature": signature,
                    "anchor_y_ratio": round(anchor, 6),
                    "baseline_spread_ratio": round(spread, 6),
                    "gap_from_previous_row_ratio": (
                        round(anchor - previous_anchor, 6) if previous_anchor is not None else None
                    ),
                    "markers": row,
                }
            )
            previous_anchor = anchor
        result[column] = payloads
    return result


def _lcs_row_pairs(
    source: list[dict[str, Any]],
    output: list[dict[str, Any]],
) -> list[tuple[int, int]]:
    rows = len(source)
    columns = len(output)
    table = [[0] * (columns + 1) for _ in range(rows + 1)]
    for source_index in range(rows - 1, -1, -1):
        for output_index in range(columns - 1, -1, -1):
            if source[source_index]["signature"] == output[output_index]["signature"]:
                table[source_index][output_index] = 1 + table[source_index + 1][output_index + 1]
            else:
                table[source_index][output_index] = max(
                    table[source_index + 1][output_index],
                    table[source_index][output_index + 1],
                )
    pairs: list[tuple[int, int]] = []
    source_index = output_index = 0
    while source_index < rows and output_index < columns:
        if source[source_index]["signature"] == output[output_index]["signature"]:
            pairs.append((source_index, output_index))
            source_index += 1
            output_index += 1
        elif table[source_index + 1][output_index] >= table[source_index][output_index + 1]:
            source_index += 1
        else:
            output_index += 1
    return pairs


def _compare_choice_rows(
    source_rows: dict[str, list[dict[str, Any]]],
    output_rows: dict[str, list[dict[str, Any]]],
    thresholds: Thresholds,
) -> dict[str, Any]:
    columns: dict[str, Any] = {}
    all_pass = True
    for column in COLUMN_RANGES:
        source = source_rows[column]
        output = output_rows[column]
        raw_pairs = _lcs_row_pairs(source, output)
        used_source = {item[0] for item in raw_pairs}
        used_output = {item[1] for item in raw_pairs}
        pairs: list[dict[str, Any]] = []
        for source_index, output_index in raw_pairs:
            anchor_delta = abs(
                float(source[source_index]["anchor_y_ratio"])
                - float(output[output_index]["anchor_y_ratio"])
            )
            spread_delta = abs(
                float(source[source_index]["baseline_spread_ratio"])
                - float(output[output_index]["baseline_spread_ratio"])
            )
            pairs.append(
                {
                    "source_index": source_index,
                    "output_index": output_index,
                    "signature": source[source_index]["signature"],
                    "source_anchor_y_ratio": source[source_index]["anchor_y_ratio"],
                    "output_anchor_y_ratio": output[output_index]["anchor_y_ratio"],
                    "anchor_absolute_delta_ratio": round(anchor_delta, 6),
                    "baseline_spread_absolute_delta_ratio": round(spread_delta, 6),
                    "pass": anchor_delta <= thresholds.max_choice_row_anchor_delta,
                }
            )
        spacing_pairs: list[dict[str, Any]] = []
        for first, second in zip(raw_pairs, raw_pairs[1:]):
            first_source, first_output = first
            second_source, second_output = second
            if second_source != first_source + 1 or second_output != first_output + 1:
                continue
            source_gap = float(source[second_source]["anchor_y_ratio"]) - float(
                source[first_source]["anchor_y_ratio"]
            )
            output_gap = float(output[second_output]["anchor_y_ratio"]) - float(
                output[first_output]["anchor_y_ratio"]
            )
            delta = abs(source_gap - output_gap)
            spacing_pairs.append(
                {
                    "source_row_indices": [first_source, second_source],
                    "output_row_indices": [first_output, second_output],
                    "source_gap_ratio": round(source_gap, 6),
                    "output_gap_ratio": round(output_gap, 6),
                    "absolute_gap_delta_ratio": round(delta, 6),
                    "pass": delta <= thresholds.max_choice_row_gap_delta,
                }
            )
        unmatched_source = sorted(set(range(len(source))) - used_source)
        unmatched_output = sorted(set(range(len(output))) - used_output)
        column_pass = (
            not unmatched_source
            and not unmatched_output
            and all(bool(item["pass"]) for item in pairs)
            and all(bool(item["pass"]) for item in spacing_pairs)
        )
        all_pass = all_pass and column_pass
        columns[column] = {
            "source_rows": source,
            "output_rows": output,
            "matched_rows": pairs,
            "consecutive_row_spacing": spacing_pairs,
            "unmatched_source_row_indices": unmatched_source,
            "unmatched_output_row_indices": unmatched_output,
            "pass": column_pass,
        }
    return {
        "measurements": {"columns": columns},
        "thresholds": {
            "max_row_anchor_absolute_delta_ratio": thresholds.max_choice_row_anchor_delta,
            "max_consecutive_row_gap_absolute_delta_ratio": thresholds.max_choice_row_gap_delta,
            "require_exact_row_signature_sequence": True,
        },
        "pass": all_pass,
    }


def _geometry_check(
    source_page: fitz.Page,
    output_page: fitz.Page,
    threshold: float,
) -> dict[str, Any]:
    source_aspect = float(source_page.rect.width) / float(source_page.rect.height)
    output_aspect = float(output_page.rect.width) / float(output_page.rect.height)
    delta = abs(source_aspect - output_aspect)
    return {
        "measurements": {
            "source_size_points": [
                round(float(source_page.rect.width), 3),
                round(float(source_page.rect.height), 3),
            ],
            "output_size_points": [
                round(float(output_page.rect.width), 3),
                round(float(output_page.rect.height), 3),
            ],
            "source_aspect_ratio": round(source_aspect, 7),
            "output_aspect_ratio": round(output_aspect, 7),
            "absolute_aspect_ratio_delta": round(delta, 7),
        },
        "thresholds": {"max_absolute_aspect_ratio_delta": threshold},
        "pass": delta <= threshold,
    }


def _page_report(
    page_number: int,
    source_page: fitz.Page,
    output_page: fitz.Page,
    render_width: int,
    profile_bins: int,
    ink_threshold: int,
    thresholds: Thresholds,
) -> dict[str, Any]:
    source_aspect = float(source_page.rect.height) / float(source_page.rect.width)
    render_height = max(1, int(round(render_width * source_aspect)))
    source_gray = _render_gray(source_page, render_width, render_height)
    output_gray = _render_gray(output_page, render_width, render_height)
    source_mask, source_mask_info = _text_ink_mask(source_page, source_gray, ink_threshold)
    output_mask, output_mask_info = _text_ink_mask(output_page, output_gray, ink_threshold)

    columns: dict[str, Any] = {}
    for column in COLUMN_RANGES:
        columns[column] = _compare_profiles(
            _profile_payload(source_mask, column, profile_bins),
            _profile_payload(output_mask, column, profile_bins),
            thresholds,
        )

    source_anchors, source_anchor_duplicates = _extract_problem_anchors(source_page)
    output_anchors, output_anchor_duplicates = _extract_problem_anchors(output_page)
    problem_anchors = _compare_problem_anchors(
        source_anchors,
        output_anchors,
        source_anchor_duplicates,
        output_anchor_duplicates,
        output_page,
        thresholds.max_problem_anchor_delta,
    )
    dividers = _compare_dividers(
        _detect_divider(source_page, source_gray, ink_threshold),
        _detect_divider(output_page, output_gray, ink_threshold),
        thresholds,
    )
    boxes = _compare_boxes(
        _detect_boxes(source_page),
        _detect_boxes(output_page),
        source_page,
        output_page,
        thresholds,
    )
    choice_rows = _compare_choice_rows(
        _cluster_choice_rows(_choice_markers(source_page)),
        _cluster_choice_rows(_choice_markers(output_page)),
        thresholds,
    )
    geometry = _geometry_check(
        source_page, output_page, thresholds.max_page_aspect_ratio_delta
    )
    checks = {
        "page_geometry": bool(geometry["pass"]),
        "left_column_row_profile": bool(columns["left"]["pass"]),
        "right_column_row_profile": bool(columns["right"]["pass"]),
        "problem_number_top_anchors": bool(problem_anchors["pass"]),
        "central_separator": bool(dividers["pass"]),
        "boxes": bool(boxes["pass"]),
        "choice_row_spacing": bool(choice_rows["pass"]),
    }
    return {
        "page": page_number,
        "normalized_render": {
            "width_pixels": render_width,
            "height_pixels": render_height,
            "source_profile_mask": source_mask_info,
            "output_profile_mask": output_mask_info,
        },
        "page_geometry": geometry,
        "column_text_math_ink_row_profiles": columns,
        "problem_number_top_anchors": problem_anchors,
        "central_separator": dividers,
        "boxes": boxes,
        "choice_row_spacing": choice_rows,
        "checks": checks,
        "pass": all(checks.values()),
    }


def _worst_item(
    items: list[tuple[int, str | None, float]],
    mode: str,
) -> dict[str, Any] | None:
    if not items:
        return None
    chosen = max(items, key=lambda item: item[2]) if mode == "max" else min(
        items, key=lambda item: item[2]
    )
    result: dict[str, Any] = {"page": chosen[0], "value": round(chosen[2], 6)}
    if chosen[1] is not None:
        result["column"] = chosen[1]
    return result


def _build_summary(
    pages: list[dict[str, Any]],
    source_page_count: int,
    output_page_count: int,
    thresholds: Thresholds,
) -> dict[str, Any]:
    exact_page_count = source_page_count == output_page_count
    failed_checks: list[dict[str, Any]] = []
    profile_emd: list[tuple[int, str | None, float]] = []
    profile_correlation: list[tuple[int, str | None, float]] = []
    problem_delta: list[tuple[int, str | None, float]] = []
    divider_x_delta: list[tuple[int, str | None, float]] = []
    box_delta: list[tuple[int, str | None, float]] = []
    choice_anchor_delta: list[tuple[int, str | None, float]] = []

    for page in pages:
        page_number = int(page["page"])
        for check, passed in page["checks"].items():
            if not passed:
                failed_checks.append({"page": page_number, "check": check})
        for column, section in page["column_text_math_ink_row_profiles"].items():
            comparison = section["measurements"]["comparison"]
            profile_emd.append(
                (page_number, column, float(comparison["earth_mover_distance_ratio"]))
            )
            profile_correlation.append(
                (
                    page_number,
                    column,
                    float(comparison["max_shifted_pearson_correlation"]),
                )
            )
        problem_value = page["problem_number_top_anchors"]["measurements"].get(
            "max_top_absolute_delta_ratio"
        )
        if problem_value is not None:
            problem_delta.append((page_number, None, float(problem_value)))
        divider_value = page["central_separator"]["measurements"].get(
            "x_absolute_delta_ratio"
        )
        if divider_value is not None:
            divider_x_delta.append((page_number, None, float(divider_value)))
        for pair in page["boxes"]["measurements"]["matched_pairs"]:
            box_delta.append(
                (page_number, None, float(pair["max_edge_absolute_delta_ratio"]))
            )
        for column_data in page["choice_row_spacing"]["measurements"]["columns"].values():
            for pair in column_data["matched_rows"]:
                choice_anchor_delta.append(
                    (page_number, None, float(pair["anchor_absolute_delta_ratio"]))
                )

    checks = {
        "page_count": {
            "measurements": {
                "source_page_count": source_page_count,
                "output_page_count": output_page_count,
                "pages_compared": len(pages),
                "missing_output_page_numbers": list(
                    range(output_page_count + 1, source_page_count + 1)
                )
                if source_page_count > output_page_count
                else [],
                "unexpected_output_page_numbers": list(
                    range(source_page_count + 1, output_page_count + 1)
                )
                if output_page_count > source_page_count
                else [],
            },
            "thresholds": {"require_exact_page_count": True},
            "pass": exact_page_count,
        },
        "column_text_math_ink_row_profiles": {
            "measurements": {
                "columns_assessed": len(pages) * 2,
                "columns_passed": sum(
                    int(section["pass"])
                    for page in pages
                    for section in page["column_text_math_ink_row_profiles"].values()
                ),
                "worst_earth_mover_distance_ratio": _worst_item(profile_emd, "max"),
                "lowest_max_shifted_pearson_correlation": _worst_item(
                    profile_correlation, "min"
                ),
            },
            "thresholds": {
                "max_earth_mover_distance_ratio": thresholds.max_profile_earth_mover_distance,
                "min_max_shifted_pearson_correlation": thresholds.min_profile_correlation,
                "max_ink_relative_error": thresholds.max_profile_ink_relative_error,
                "min_active_band_f1": thresholds.min_profile_band_f1,
                "max_active_band_anchor_delta_ratio": thresholds.max_profile_band_anchor_delta,
            },
            "pass": all(
                section["pass"]
                for page in pages
                for section in page["column_text_math_ink_row_profiles"].values()
            ),
        },
        "problem_number_top_anchors": {
            "measurements": {
                "pages_passed": sum(
                    int(page["problem_number_top_anchors"]["pass"]) for page in pages
                ),
                "pages_assessed": len(pages),
                "worst_top_absolute_delta_ratio": _worst_item(problem_delta, "max"),
            },
            "thresholds": {
                "max_top_absolute_delta_ratio": thresholds.max_problem_anchor_delta
            },
            "pass": all(page["problem_number_top_anchors"]["pass"] for page in pages),
        },
        "central_separator": {
            "measurements": {
                "pages_passed": sum(int(page["central_separator"]["pass"]) for page in pages),
                "pages_assessed": len(pages),
                "worst_x_absolute_delta_ratio": _worst_item(divider_x_delta, "max"),
            },
            "thresholds": {
                "max_x_absolute_delta_ratio": thresholds.max_divider_x_delta,
                "max_edge_absolute_delta_ratio": thresholds.max_divider_edge_delta,
            },
            "pass": all(page["central_separator"]["pass"] for page in pages),
        },
        "boxes": {
            "measurements": {
                "pages_passed": sum(int(page["boxes"]["pass"]) for page in pages),
                "pages_assessed": len(pages),
                "worst_edge_absolute_delta_ratio": _worst_item(box_delta, "max"),
            },
            "thresholds": {
                "max_edge_absolute_delta_ratio": thresholds.max_box_edge_delta,
                "max_vertical_gap_absolute_delta_ratio": thresholds.max_box_gap_delta,
            },
            "pass": all(page["boxes"]["pass"] for page in pages),
        },
        "choice_row_spacing": {
            "measurements": {
                "pages_passed": sum(int(page["choice_row_spacing"]["pass"]) for page in pages),
                "pages_assessed": len(pages),
                "worst_row_anchor_absolute_delta_ratio": _worst_item(
                    choice_anchor_delta, "max"
                ),
            },
            "thresholds": {
                "max_row_anchor_absolute_delta_ratio": thresholds.max_choice_row_anchor_delta,
                "max_consecutive_row_gap_absolute_delta_ratio": thresholds.max_choice_row_gap_delta,
            },
            "pass": all(page["choice_row_spacing"]["pass"] for page in pages),
        },
    }
    overall_pass = exact_page_count and all(page["pass"] for page in pages)
    return {
        "aggregate_quality_score": None,
        "aggregate_quality_score_policy": (
            "Not computed. Raw white-page pixel similarity and unrelated measurements are "
            "not collapsed into a percent score."
        ),
        "checks": checks,
        "failed_pages": [int(page["page"]) for page in pages if not page["pass"]],
        "failed_checks": failed_checks,
        "overall_pass": overall_pass,
    }


def analyze(
    source_path: Path,
    output_path: Path,
    *,
    render_width: int,
    profile_bins: int,
    ink_threshold: int,
    thresholds: Thresholds,
) -> dict[str, Any]:
    for label, path in (("source", source_path), ("Hancom output", output_path)):
        if not path.is_file():
            raise ValidationError(f"{label} PDF was not found: {path}")
        if path.stat().st_size <= 0:
            raise ValidationError(f"{label} PDF is empty: {path}")
    try:
        source_document = fitz.open(source_path)
    except Exception as exc:
        raise ValidationError(f"cannot open source PDF: {source_path}: {exc}") from exc
    try:
        output_document = fitz.open(output_path)
    except Exception as exc:
        source_document.close()
        raise ValidationError(f"cannot open Hancom output PDF: {output_path}: {exc}") from exc

    try:
        if source_document.needs_pass or output_document.needs_pass:
            raise ValidationError("password-protected PDFs are not supported")
        if not source_document.page_count or not output_document.page_count:
            raise ValidationError("both PDFs must contain at least one page")
        page_count = min(source_document.page_count, output_document.page_count)
        pages = [
            _page_report(
                index + 1,
                source_document[index],
                output_document[index],
                render_width,
                profile_bins,
                ink_threshold,
                thresholds,
            )
            for index in range(page_count)
        ]
        summary = _build_summary(
            pages,
            source_document.page_count,
            output_document.page_count,
            thresholds,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "tool": {
                "name": "verify_math_visual_spacing",
                "version": TOOL_VERSION,
                "python": platform.python_version(),
                "pymupdf": str(getattr(fitz, "VersionBind", "unknown")),
                "numpy": np.__version__,
            },
            "inputs": {
                "source_pdf": _pdf_input(source_path, source_document),
                "hancom_output_pdf": _pdf_input(output_path, output_document),
            },
            "configuration": {
                "normalized_render_width_pixels": render_width,
                "profile_bins": profile_bins,
                "grayscale_ink_threshold_exclusive": ink_threshold,
                "content_vertical_range_normalized": [CONTENT_TOP, CONTENT_BOTTOM],
                "column_ranges_normalized": {
                    key: list(value) for key, value in COLUMN_RANGES.items()
                },
            },
            "thresholds": asdict(thresholds),
            "methodology": {
                "row_profiles": (
                    "Pages are rendered to a fixed normalized width. Dark rendered pixels are "
                    "intersected with PDF text-span geometry so text and math ink drive the row "
                    "profiles; a rule-suppressed raster fallback is recorded when text geometry "
                    "is unavailable."
                ),
                "anchors_and_choices": (
                    "Problem labels and circled-choice rows are measured from extractable PDF "
                    "word coordinates and compared within normalized page coordinates."
                ),
                "separator_and_boxes": (
                    "The center separator and rectangular boxes are measured from visible vector "
                    "paths, with a recorded raster fallback only for the separator."
                ),
                "raw_pixel_similarity": (
                    "Not reported as a quality score because white page area can dominate a raw "
                    "pixel similarity percentage."
                ),
            },
            "summary": summary,
            "pages": pages,
        }
    finally:
        source_document.close()
        output_document.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare page/column math spacing in an original PDF and a PDF actually saved by "
            "Hancom. JSON contains raw measurements, thresholds, and pass/fail gates separately."
        )
    )
    parser.add_argument("source_pdf", type=Path, help="original math PDF")
    parser.add_argument("hancom_output_pdf", type=Path, help="actual Hancom-saved PDF")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("-"),
        help="JSON path, or - for stdout (default: -)",
    )
    parser.add_argument("--render-width", type=int, default=1200)
    parser.add_argument("--profile-bins", type=int, default=256)
    parser.add_argument("--ink-threshold", type=int, default=225)
    parser.add_argument("--compact", action="store_true", help="emit compact JSON")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="return exit code 0 after a valid report even when one or more gates fail",
    )
    parser.add_argument("--max-page-aspect-ratio-delta", type=float, default=0.005)
    parser.add_argument("--max-profile-earth-mover-distance", type=float, default=0.035)
    parser.add_argument("--min-profile-correlation", type=float, default=0.45)
    parser.add_argument("--max-profile-ink-relative-error", type=float, default=0.35)
    parser.add_argument("--min-profile-band-f1", type=float, default=0.55)
    parser.add_argument("--max-profile-band-anchor-delta", type=float, default=0.018)
    parser.add_argument("--max-problem-anchor-delta", type=float, default=0.018)
    parser.add_argument("--max-divider-x-delta", type=float, default=0.020)
    parser.add_argument("--max-divider-edge-delta", type=float, default=0.030)
    parser.add_argument("--max-box-edge-delta", type=float, default=0.030)
    parser.add_argument("--max-box-gap-delta", type=float, default=0.030)
    parser.add_argument("--max-choice-row-anchor-delta", type=float, default=0.018)
    parser.add_argument("--max-choice-row-gap-delta", type=float, default=0.018)
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not 400 <= args.render_width <= 4000:
        parser.error("--render-width must be between 400 and 4000")
    if not 32 <= args.profile_bins <= 1024:
        parser.error("--profile-bins must be between 32 and 1024")
    if not 1 <= args.ink_threshold <= 254:
        parser.error("--ink-threshold must be between 1 and 254")
    for name, value in vars(args).items():
        if name.startswith("max_") and isinstance(value, float) and not 0.0 <= value <= 2.0:
            parser.error(f"--{name.replace('_', '-')} must be between 0 and 2")
    if not -1.0 <= args.min_profile_correlation <= 1.0:
        parser.error("--min-profile-correlation must be between -1 and 1")
    if not 0.0 <= args.min_profile_band_f1 <= 1.0:
        parser.error("--min-profile-band-f1 must be between 0 and 1")
    if str(args.output) != "-":
        report_path = args.output.expanduser().resolve()
        input_paths = {
            args.source_pdf.expanduser().resolve(),
            args.hancom_output_pdf.expanduser().resolve(),
        }
        if report_path in input_paths:
            parser.error("--output must not overwrite either input PDF")


def _write_json(report: dict[str, Any], output: Path, compact: bool) -> None:
    payload = json.dumps(
        report,
        ensure_ascii=False,
        indent=None if compact else 2,
        separators=(",", ":") if compact else None,
    )
    if str(output) == "-":
        print(payload)
        return
    output = output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
        ) as stream:
            stream.write(payload)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            temporary_name = stream.name
        os.replace(temporary_name, output)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass
    print(str(output.resolve()), file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    thresholds = Thresholds(
        max_page_aspect_ratio_delta=args.max_page_aspect_ratio_delta,
        max_profile_earth_mover_distance=args.max_profile_earth_mover_distance,
        min_profile_correlation=args.min_profile_correlation,
        max_profile_ink_relative_error=args.max_profile_ink_relative_error,
        min_profile_band_f1=args.min_profile_band_f1,
        max_profile_band_anchor_delta=args.max_profile_band_anchor_delta,
        max_problem_anchor_delta=args.max_problem_anchor_delta,
        max_divider_x_delta=args.max_divider_x_delta,
        max_divider_edge_delta=args.max_divider_edge_delta,
        max_box_edge_delta=args.max_box_edge_delta,
        max_box_gap_delta=args.max_box_gap_delta,
        max_choice_row_anchor_delta=args.max_choice_row_anchor_delta,
        max_choice_row_gap_delta=args.max_choice_row_gap_delta,
    )
    try:
        report = analyze(
            args.source_pdf,
            args.hancom_output_pdf,
            render_width=args.render_width,
            profile_bins=args.profile_bins,
            ink_threshold=args.ink_threshold,
            thresholds=thresholds,
        )
    except Exception as exc:
        error_report = {
            "schema_version": SCHEMA_VERSION,
            "tool": {"name": "verify_math_visual_spacing", "version": TOOL_VERSION},
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        _write_json(error_report, args.output, args.compact)
        return 2
    _write_json(report, args.output, args.compact)
    if args.report_only:
        return 0
    return 0 if report["summary"]["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
