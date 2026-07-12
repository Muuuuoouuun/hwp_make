"""Render-based PDF to HWPX layout fidelity checks."""

from __future__ import annotations

from collections import Counter
import io
from pathlib import Path
import re
from typing import Any
import unicodedata

import fitz
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

try:
    import rhwp
except Exception:  # pragma: no cover - optional runtime dependency
    rhwp = None

STRICT_ALIGNMENT_REVIEW_THRESHOLD = 0.75
FOREGROUND_OVERLAP_REVIEW_THRESHOLD = 0.10
ASPECT_RATIO_TOLERANCE = 0.02
LAYOUT_VIEW_BLUR_RADIUS = 1.0
DETAILED_FOREGROUND_REFERENCE = 0.88
DETAILED_LINE_TOLERANCE_PX = 6

PDF_PDF_DEFAULT_RENDER_DPI = 96
PDF_PDF_DUPLICATE_SIMILARITY_THRESHOLD = 0.985
PDF_PDF_MINIMUM_ASSESSMENT_COVERAGE = 0.75
PDF_PDF_SEMANTIC_WEIGHTS = {
    "page_count": 20.0,
    "text_preservation": 35.0,
    "problem_number_preservation": 25.0,
    "duplicate_pages": 10.0,
    "central_divider": 10.0,
}
_FALLBACK_PROBLEM_MARKER_RE = re.compile(
    r"^\s*(?:문제\s*)?[\[(]?([1-9][0-9]{0,2})[\]).．.](?:\s|$)"
)
_FALLBACK_KOREAN_PROBLEM_MARKER_RE = re.compile(
    r"^\s*문제\s*([1-9][0-9]{0,2})(?:\s|$)"
)


def _render_hwpx_page(document: Any, page_index: int) -> Image.Image:
    png = bytes(document.render_png(page_index))
    if not png:
        raise RuntimeError(f"rhwp returned an empty PNG for page {page_index + 1}")
    return Image.open(io.BytesIO(png)).convert("RGB")


def _render_pdf_page(page: fitz.Page, target_size: tuple[int, int]) -> Image.Image:
    width, height = target_size
    scale_x = width / float(page.rect.width)
    scale_y = height / float(page.rect.height)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale_x, scale_y), alpha=False)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    if image.size != target_size:
        image = image.resize(target_size, Image.Resampling.BICUBIC)
    return image


def _foreground_mask(image: Image.Image, threshold: int = 245) -> Image.Image:
    gray = image.convert("L")
    return gray.point(lambda pixel: 255 if pixel < threshold else 0, mode="L")


def _foreground_count(mask: Image.Image) -> int:
    histogram = mask.histogram()
    return int(histogram[255]) if len(histogram) > 255 else 0


def _intersection_count(left: Image.Image, right: Image.Image) -> int:
    return _foreground_count(ImageChops.multiply(left, right))


def _expanded_bbox(mask: Image.Image, margin: int = 24) -> tuple[int, int, int, int]:
    bbox = mask.getbbox()
    if bbox is None:
        return (0, 0, mask.width, mask.height)
    left, top, right, bottom = bbox
    return (
        max(0, left - margin),
        max(0, top - margin),
        min(mask.width, right + margin),
        min(mask.height, bottom + margin),
    )


def _safe_aspect_ratio(width: float, height: float) -> float:
    if height <= 0:
        return 0.0
    return float(width) / float(height)


def _mask_array(mask: Image.Image) -> np.ndarray:
    return np.asarray(mask, dtype=np.float32) / 255.0


def _without_long_vertical_rules(mask: np.ndarray) -> np.ndarray:
    clean = mask.copy()
    if clean.size == 0:
        return clean
    long_rule_columns = clean.sum(axis=0) >= clean.shape[0] * 0.62
    clean[:, long_rule_columns] = 0.0
    return clean


def _smooth_profile(values: np.ndarray, radius: int = 3) -> np.ndarray:
    if values.size == 0 or radius <= 0:
        return values.astype(np.float32, copy=False)
    kernel = np.ones(radius * 2 + 1, dtype=np.float32)
    kernel /= kernel.sum()
    return np.convolve(values.astype(np.float32), kernel, mode="same")


def _profile_similarity(left: np.ndarray, right: np.ndarray) -> float:
    if left.size == 0 or right.size == 0:
        return 1.0 if left.size == right.size else 0.0
    size = min(left.size, right.size)
    left = _smooth_profile(left[:size])
    right = _smooth_profile(right[:size])
    left_sum = float(left.sum())
    right_sum = float(right.sum())
    if left_sum <= 1e-6 and right_sum <= 1e-6:
        return 1.0
    if left_sum <= 1e-6 or right_sum <= 1e-6:
        return 0.0

    left_dist = left / left_sum
    right_dist = right / right_sum
    distribution = max(0.0, 1.0 - float(np.abs(left_dist - right_dist).sum()) * 0.5)
    left_peak = float(left.max()) or 1.0
    right_peak = float(right.max()) or 1.0
    left_shape = left / left_peak
    right_shape = right / right_peak
    union = float(np.maximum(left_shape, right_shape).sum())
    soft_iou = (
        float(np.minimum(left_shape, right_shape).sum()) / union
        if union > 1e-6
        else 1.0
    )
    return max(0.0, min(1.0, distribution * 0.65 + soft_iou * 0.35))


def _row_profile_score(source: np.ndarray, output: np.ndarray) -> float:
    height, width = source.shape
    regions = (
        (0.07, 0.93, 0.055, 0.22),
        (0.07, 0.49, 0.17, 0.93),
        (0.51, 0.93, 0.17, 0.93),
    )
    scores: list[float] = []
    for left, right, top, bottom in regions:
        x0, x1 = int(width * left), int(width * right)
        y0, y1 = int(height * top), int(height * bottom)
        src = _without_long_vertical_rules(source[y0:y1, x0:x1])
        out = _without_long_vertical_rules(output[y0:y1, x0:x1])
        scores.append(_profile_similarity(src.sum(axis=1), out.sum(axis=1)))
    return sum(scores) / len(scores)


def _column_profile_score(source: np.ndarray, output: np.ndarray) -> float:
    height, width = source.shape
    y0, y1 = int(height * 0.055), int(height * 0.93)
    x0, x1 = int(width * 0.055), int(width * 0.945)
    src = _without_long_vertical_rules(source[y0:y1, x0:x1])
    out = _without_long_vertical_rules(output[y0:y1, x0:x1])
    return _profile_similarity(src.sum(axis=0), out.sum(axis=0))


def _line_band_centers(mask: np.ndarray) -> list[float]:
    if mask.size == 0:
        return []
    clean = _without_long_vertical_rules(mask)
    profile = clean.sum(axis=1)
    active = profile >= max(2.0, clean.shape[1] * 0.006)
    centers: list[float] = []
    start: int | None = None
    for index, value in enumerate(active):
        if value and start is None:
            start = index
        if start is not None and (not value or index == len(active) - 1):
            end = index if not value else index + 1
            height = end - start
            if 2 <= height <= 24:
                weights = profile[start:end]
                total = float(weights.sum())
                if total > 0:
                    positions = np.arange(start, end, dtype=np.float32)
                    centers.append(float((positions * weights).sum() / total))
            start = None
    return centers


def _line_band_match_score(source: np.ndarray, output: np.ndarray) -> float:
    height, width = source.shape
    scores: list[float] = []
    for left, right in ((0.07, 0.49), (0.51, 0.93)):
        x0, x1 = int(width * left), int(width * right)
        y0, y1 = int(height * 0.17), int(height * 0.93)
        src_centers = _line_band_centers(source[y0:y1, x0:x1])
        out_centers = _line_band_centers(output[y0:y1, x0:x1])
        if not src_centers and not out_centers:
            scores.append(1.0)
            continue
        matched = 0
        out_index = 0
        for center in src_centers:
            while (
                out_index < len(out_centers)
                and out_centers[out_index] < center - DETAILED_LINE_TOLERANCE_PX
            ):
                out_index += 1
            candidates = []
            for candidate_index in (out_index, out_index + 1):
                if candidate_index < len(out_centers):
                    distance = abs(out_centers[candidate_index] - center)
                    if distance <= DETAILED_LINE_TOLERANCE_PX:
                        candidates.append((distance, candidate_index))
            if candidates:
                _distance, chosen = min(candidates)
                matched += 1
                out_index = chosen + 1
        denominator = len(src_centers) + len(out_centers)
        scores.append((2.0 * matched / denominator) if denominator else 1.0)
    return sum(scores) / len(scores)


def _occupancy_grid_score(source_mask: Image.Image, output_mask: Image.Image) -> float:
    target_size = (80, 113)
    source_soft = source_mask.filter(ImageFilter.MaxFilter(5)).resize(
        target_size, Image.Resampling.BOX
    )
    output_soft = output_mask.filter(ImageFilter.MaxFilter(5)).resize(
        target_size, Image.Resampling.BOX
    )
    source = np.asarray(source_soft, dtype=np.float32) / 255.0
    output = np.asarray(output_soft, dtype=np.float32) / 255.0
    union = float(np.maximum(source, output).sum())
    return float(np.minimum(source, output).sum()) / union if union > 1e-6 else 1.0


def _bbox_similarity(
    source_bbox: tuple[int, int, int, int] | None,
    output_bbox: tuple[int, int, int, int] | None,
    size: tuple[int, int],
) -> float:
    if source_bbox is None and output_bbox is None:
        return 1.0
    if source_bbox is None or output_bbox is None:
        return 0.0
    width, height = size
    scales = (width, height, width, height)
    normalized_delta = sum(
        abs(float(left) - float(right)) / max(1.0, float(scale))
        for left, right, scale in zip(source_bbox, output_bbox, scales)
    ) / 4.0
    return max(0.0, 1.0 - normalized_delta * 5.0)


def _detailed_geometry_metrics(
    source_mask: Image.Image,
    output_mask: Image.Image,
    *,
    foreground_overlap: float,
) -> dict[str, float]:
    source = _mask_array(source_mask)
    output = _mask_array(output_mask)
    row_score = _row_profile_score(source, output)
    column_score = _column_profile_score(source, output)
    line_score = _line_band_match_score(source, output)
    occupancy_score = _occupancy_grid_score(source_mask, output_mask)
    source_count = float(source.sum())
    output_count = float(output.sum())
    density_score = (
        min(source_count, output_count) / max(source_count, output_count)
        if source_count > 0 or output_count > 0
        else 1.0
    )
    bbox_score = _bbox_similarity(source_mask.getbbox(), output_mask.getbbox(), source_mask.size)
    foreground_score = min(1.0, foreground_overlap / DETAILED_FOREGROUND_REFERENCE)
    total = (
        row_score * 0.25
        + line_score * 0.20
        + occupancy_score * 0.20
        + foreground_score * 0.15
        + column_score * 0.10
        + bbox_score * 0.05
        + density_score * 0.05
    )
    return {
        "detailed_layout_score": round(total * 100.0, 2),
        "row_alignment_score": round(row_score * 100.0, 2),
        "line_band_match_score": round(line_score * 100.0, 2),
        "occupancy_grid_score": round(occupancy_score * 100.0, 2),
        "foreground_geometry_score": round(foreground_score * 100.0, 2),
        "column_alignment_score": round(column_score * 100.0, 2),
        "content_bbox_score": round(bbox_score * 100.0, 2),
        "ink_density_score": round(density_score * 100.0, 2),
    }


def _page_metrics(source: Image.Image, output: Image.Image) -> dict[str, Any]:
    source_gray = source.convert("L")
    output_gray = output.convert("L")

    whole_diff = ImageChops.difference(source_gray, output_gray)
    whole_mean_abs_diff = float(ImageStat.Stat(whole_diff).mean[0])
    whole_visual_similarity = max(0.0, 1.0 - whole_mean_abs_diff / 255.0)

    layout_source = source_gray.filter(ImageFilter.GaussianBlur(LAYOUT_VIEW_BLUR_RADIUS))
    layout_output = output_gray.filter(ImageFilter.GaussianBlur(LAYOUT_VIEW_BLUR_RADIUS))
    layout_diff = ImageChops.difference(layout_source, layout_output)
    layout_mean_abs_diff = float(ImageStat.Stat(layout_diff).mean[0])
    layout_view_similarity = max(0.0, 1.0 - layout_mean_abs_diff / 255.0)

    source_mask = _foreground_mask(source_gray)
    output_mask = _foreground_mask(output_gray)
    union_mask = ImageChops.lighter(source_mask, output_mask)
    bbox = _expanded_bbox(union_mask)

    source_crop = source_gray.crop(bbox)
    output_crop = output_gray.crop(bbox)
    diff = ImageChops.difference(source_crop, output_crop)
    mean_abs_diff = float(ImageStat.Stat(diff).mean[0])
    visual_similarity = max(0.0, 1.0 - mean_abs_diff / 255.0)

    source_mask_crop = source_mask.crop(bbox)
    output_mask_crop = output_mask.crop(bbox)
    source_fg = _foreground_count(source_mask_crop)
    output_fg = _foreground_count(output_mask_crop)
    if source_fg == 0 and output_fg == 0:
        foreground_overlap = 1.0
    elif source_fg == 0 or output_fg == 0:
        foreground_overlap = 0.0
    else:
        source_dilated = source_mask_crop.filter(ImageFilter.MaxFilter(7))
        output_dilated = output_mask_crop.filter(ImageFilter.MaxFilter(7))
        source_covered = _intersection_count(source_mask_crop, output_dilated) / source_fg
        output_covered = _intersection_count(output_mask_crop, source_dilated) / output_fg
        foreground_overlap = (source_covered + output_covered) / 2.0

    strict_alignment = (visual_similarity * 0.75) + (foreground_overlap * 0.25)
    detailed = _detailed_geometry_metrics(
        source_mask,
        output_mask,
        foreground_overlap=foreground_overlap,
    )
    # Hancom's PDF renderer expands high-contrast glyph edges by one to four
    # pixels depending on local rule density. Compare a bounded set of equal
    # source/output normalizations, then cap the result with the unnormalized
    # strict-alignment and foreground-overlap measurements below.
    normalized_candidates: list[tuple[float, int]] = []
    for kernel_size in (3, 7, 9, 15, 17, 21):
        normalized_detailed = _detailed_geometry_metrics(
            source_mask.filter(ImageFilter.MaxFilter(kernel_size)),
            output_mask.filter(ImageFilter.MaxFilter(kernel_size)),
            foreground_overlap=foreground_overlap,
        )
        normalized_candidates.append(
            (float(normalized_detailed["detailed_layout_score"]), kernel_size)
        )
    normalized_score, normalization_kernel = max(normalized_candidates)
    harsh_layout_score = min(
        normalized_score,
        strict_alignment * 100.0,
        foreground_overlap * 100.0,
    )
    return {
        "visual_sync_ratio": round(visual_similarity, 4),
        "visual_similarity_ratio": round(visual_similarity, 4),
        "content_visual_sync_ratio": round(visual_similarity, 4),
        "whole_page_visual_sync_ratio": round(whole_visual_similarity, 4),
        "layout_view_sync_ratio": round(layout_view_similarity, 4),
        "foreground_overlap_ratio": round(foreground_overlap, 4),
        "strict_alignment_ratio": round(strict_alignment, 4),
        "antialias_normalized_detailed_layout_score": round(normalized_score, 2),
        "antialias_normalization_kernel": normalization_kernel,
        "harsh_layout_score": round(harsh_layout_score, 2),
        "mean_abs_luma_diff": round(mean_abs_diff, 3),
        "whole_page_mean_abs_luma_diff": round(whole_mean_abs_diff, 3),
        "layout_view_mean_abs_luma_diff": round(layout_mean_abs_diff, 3),
        "content_bbox_px": list(bbox),
        "source_foreground_pixels": source_fg,
        "output_foreground_pixels": output_fg,
        **detailed,
    }


def analyze_pdf_hwpx_fidelity(
    pdf_path: str | Path,
    hwpx_path: str | Path,
    output_dir: str | Path,
    *,
    max_pages: int = 3,
    target_sync_ratio: float = 0.9,
    allow_truncated_by_max_pages: bool = False,
    artifact_mode: str = "all",
) -> dict[str, Any]:
    """Render PDF/HWPX pages and compute visual sync ratios.

    The score is an automated QA signal, not a substitute for Hancom visual
    review. It compares rendered luminance over the document content area and
    adds a tolerant foreground-overlap check so text shifts are visible in the
    report instead of being hidden by white page background.
    """

    if rhwp is None:
        return {
            "available": False,
            "skipped": True,
            "reason": "rhwp unavailable",
            "target_sync_ratio": target_sync_ratio,
            "meets_target": None,
        }

    pdf_path = Path(pdf_path)
    hwpx_path = Path(hwpx_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    save_all_artifacts = artifact_mode == "all"
    save_failure_artifacts = artifact_mode == "failures"

    pages: list[dict[str, Any]] = []
    try:
        hwpx_doc = rhwp.parse(str(hwpx_path))
        hwp_page_count = int(hwpx_doc.page_count)
        with fitz.open(pdf_path) as pdf_doc:
            pdf_page_count = len(pdf_doc)
            page_count = max(0, min(pdf_page_count, hwp_page_count, max_pages))
            for page_index in range(page_count):
                pdf_page = pdf_doc[page_index]
                output_image = _render_hwpx_page(hwpx_doc, page_index)
                source_image = _render_pdf_page(pdf_page, output_image.size)
                metrics = _page_metrics(source_image, output_image)
                should_save_artifacts = save_all_artifacts or (
                    save_failure_artifacts
                    and float(metrics.get("layout_view_sync_ratio") or 0.0) < target_sync_ratio
                )

                source_name = f"source_page_{page_index + 1:03d}.png"
                output_name = f"output_page_{page_index + 1:03d}.png"
                diff_name = f"diff_page_{page_index + 1:03d}.png"
                if should_save_artifacts:
                    diff_image = ImageChops.difference(
                        source_image.convert("RGB"), output_image.convert("RGB")
                    )
                    source_image.save(output_dir / source_name)
                    output_image.save(output_dir / output_name)
                    diff_image.save(output_dir / diff_name)

                pdf_aspect = _safe_aspect_ratio(pdf_page.rect.width, pdf_page.rect.height)
                output_aspect = _safe_aspect_ratio(output_image.width, output_image.height)
                aspect_delta = abs(pdf_aspect - output_aspect)
                pages.append(
                    {
                        "page": page_index + 1,
                        "source_png": source_name,
                        "output_png": output_name,
                        "diff_png": diff_name,
                        "pdf_page_size_pt": [
                            round(float(pdf_page.rect.width), 3),
                            round(float(pdf_page.rect.height), 3),
                        ],
                        "source_size_px": list(source_image.size),
                        "output_size_px": list(output_image.size),
                        "pdf_page_aspect_ratio": round(pdf_aspect, 4),
                        "output_aspect_ratio": round(output_aspect, 4),
                        "aspect_ratio_delta": round(aspect_delta, 4),
                        "aspect_ratio_mismatch": aspect_delta > ASPECT_RATIO_TOLERANCE,
                        **metrics,
                    }
                )
    except Exception as exc:
        return {
            "available": True,
            "skipped": False,
            "error": f"{type(exc).__name__}: {exc}",
            "target_sync_ratio": target_sync_ratio,
        }

    if pages:
        sync_values = [float(page["visual_sync_ratio"]) for page in pages]
        strict_values = [float(page["strict_alignment_ratio"]) for page in pages]
        visual_values = [float(page["visual_similarity_ratio"]) for page in pages]
        whole_page_values = [
            float(page.get("whole_page_visual_sync_ratio", page["visual_sync_ratio"]))
            for page in pages
        ]
        layout_view_values = [
            float(page.get("layout_view_sync_ratio", page["visual_sync_ratio"]))
            for page in pages
        ]
        overlap_values = [float(page["foreground_overlap_ratio"]) for page in pages]
        overall_sync = min(sync_values)
        mean_sync = sum(sync_values) / len(sync_values)
        overall_whole_page_sync = min(whole_page_values)
        mean_whole_page_sync = sum(whole_page_values) / len(whole_page_values)
        overall_layout_view_sync = min(layout_view_values)
        mean_layout_view_sync = sum(layout_view_values) / len(layout_view_values)
        min_strict = min(strict_values)
        min_visual = min(visual_values)
        min_overlap = min(overlap_values)
        max_aspect_delta = max(float(page["aspect_ratio_delta"]) for page in pages)
        detailed_values = [float(page["detailed_layout_score"]) for page in pages]
        overall_detailed_layout_score = sum(detailed_values) / len(detailed_values)
        minimum_detailed_layout_score = min(detailed_values)
        harsh_values = [float(page["harsh_layout_score"]) for page in pages]
        overall_harsh_layout_score = sum(harsh_values) / len(harsh_values)
        minimum_harsh_layout_score = min(harsh_values)
    else:
        overall_sync = 0.0
        mean_sync = 0.0
        overall_whole_page_sync = 0.0
        mean_whole_page_sync = 0.0
        overall_layout_view_sync = 0.0
        mean_layout_view_sync = 0.0
        min_strict = 0.0
        min_visual = 0.0
        min_overlap = 0.0
        max_aspect_delta = 0.0
        overall_detailed_layout_score = 0.0
        minimum_detailed_layout_score = 0.0
        overall_harsh_layout_score = 0.0
        minimum_harsh_layout_score = 0.0

    compared_possible_pages = min(pdf_page_count, hwp_page_count)
    raw_page_count_mismatch = pdf_page_count != hwp_page_count
    limited_by_max_pages = (
        allow_truncated_by_max_pages
        and max_pages > 0
        and pdf_page_count > max_pages
        and hwp_page_count == max_pages
        and len(pages) == max_pages
    )
    page_count_mismatch = raw_page_count_mismatch and not limited_by_max_pages
    truncated_by_max_pages = page_count < compared_possible_pages
    truncated = page_count < max(pdf_page_count, hwp_page_count)
    missing_foreground_pages = [
        int(page["page"])
        for page in pages
        if int(page["source_foreground_pixels"]) > 0 and int(page["output_foreground_pixels"]) == 0
    ]
    unexpected_foreground_pages = [
        int(page["page"])
        for page in pages
        if int(page["source_foreground_pixels"]) == 0 and int(page["output_foreground_pixels"]) > 0
    ]
    aspect_mismatch_pages = [
        int(page["page"]) for page in pages if bool(page.get("aspect_ratio_mismatch"))
    ]
    meets_visual_similarity_target = bool(pages) and overall_sync >= target_sync_ratio
    meets_whole_page_sync_target = bool(pages) and overall_whole_page_sync >= target_sync_ratio
    meets_layout_view_sync_target = bool(pages) and overall_layout_view_sync >= target_sync_ratio
    meets_strict_alignment_review = bool(pages) and min_strict >= STRICT_ALIGNMENT_REVIEW_THRESHOLD
    meets_foreground_overlap_review = (
        bool(pages) and min_overlap >= FOREGROUND_OVERLAP_REVIEW_THRESHOLD
    )
    review_flags: list[str] = []
    if page_count_mismatch:
        review_flags.append("page_count_mismatch")
    if truncated_by_max_pages:
        review_flags.append("truncated_by_max_pages")
    if aspect_mismatch_pages:
        review_flags.append("aspect_ratio_mismatch")
    if missing_foreground_pages:
        review_flags.append("missing_output_foreground")
    if unexpected_foreground_pages:
        review_flags.append("unexpected_output_foreground")
    if pages and not meets_strict_alignment_review:
        review_flags.append("strict_alignment_below_review_threshold")
    if pages and not meets_foreground_overlap_review:
        review_flags.append("foreground_overlap_below_review_threshold")

    return {
        "available": True,
        "skipped": False,
        "target_sync_ratio": target_sync_ratio,
        "artifact_mode": artifact_mode,
        "strict_alignment_review_threshold": STRICT_ALIGNMENT_REVIEW_THRESHOLD,
        "foreground_overlap_review_threshold": FOREGROUND_OVERLAP_REVIEW_THRESHOLD,
        "layout_view_blur_radius": LAYOUT_VIEW_BLUR_RADIUS,
        "aspect_ratio_tolerance": ASPECT_RATIO_TOLERANCE,
        "pdf_page_count": pdf_page_count,
        "hwpx_page_count": hwp_page_count,
        "max_pages": max_pages,
        "truncated": truncated,
        "truncated_by_max_pages": truncated_by_max_pages,
        "limited_by_max_pages": limited_by_max_pages,
        "raw_page_count_mismatch": raw_page_count_mismatch,
        "page_count_mismatch": page_count_mismatch,
        "pages_compared": len(pages),
        "overall_sync_ratio": round(overall_sync, 4),
        "mean_sync_ratio": round(mean_sync, 4),
        "overall_whole_page_sync_ratio": round(overall_whole_page_sync, 4),
        "mean_whole_page_sync_ratio": round(mean_whole_page_sync, 4),
        "overall_layout_view_sync_ratio": round(overall_layout_view_sync, 4),
        "mean_layout_view_sync_ratio": round(mean_layout_view_sync, 4),
        "min_strict_alignment_ratio": round(min_strict, 4),
        "min_visual_similarity_ratio": round(min_visual, 4),
        "min_foreground_overlap_ratio": round(min_overlap, 4),
        "max_aspect_ratio_delta": round(max_aspect_delta, 4),
        "overall_detailed_layout_score": round(overall_detailed_layout_score, 2),
        "minimum_detailed_layout_score": round(minimum_detailed_layout_score, 2),
        "overall_harsh_layout_score": round(overall_harsh_layout_score, 2),
        "minimum_harsh_layout_score": round(minimum_harsh_layout_score, 2),
        "missing_foreground_pages": missing_foreground_pages,
        "unexpected_foreground_pages": unexpected_foreground_pages,
        "aspect_ratio_mismatch_pages": aspect_mismatch_pages,
        "meets_visual_similarity_target": meets_visual_similarity_target,
        "meets_whole_page_sync_target": meets_whole_page_sync_target,
        "meets_layout_view_sync_target": meets_layout_view_sync_target,
        "meets_strict_alignment_review": meets_strict_alignment_review,
        "meets_foreground_overlap_review": meets_foreground_overlap_review,
        "review_flags": review_flags,
        "needs_human_review": bool(review_flags),
        "meets_target": (
            meets_layout_view_sync_target
            and meets_strict_alignment_review
            and meets_foreground_overlap_review
            and not page_count_mismatch
            and not truncated_by_max_pages
            and not aspect_mismatch_pages
            and not missing_foreground_pages
        ),
        "pages": pages,
    }


def _pdf_page_target_size(page: fitz.Page, dpi: int) -> tuple[int, int]:
    scale = float(dpi) / 72.0
    return (
        max(1, int(round(float(page.rect.width) * scale))),
        max(1, int(round(float(page.rect.height) * scale))),
    )


def _extract_pdf_text(page: fitz.Page) -> str:
    try:
        return str(page.get_text("text", sort=True) or "")
    except TypeError:  # pragma: no cover - compatibility with older PyMuPDF
        return str(page.get_text("text") or "")


def _normalize_semantic_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return "".join(
        char
        for char in normalized
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )


def _text_ngram_counter(texts: list[str], ngram_size: int = 3) -> Counter[str]:
    grams: Counter[str] = Counter()
    for text in texts:
        normalized = _normalize_semantic_text(text)
        if not normalized:
            continue
        size = min(max(1, int(ngram_size)), len(normalized))
        grams.update(
            normalized[index : index + size]
            for index in range(len(normalized) - size + 1)
        )
    return grams


def _counter_overlap_metrics(
    source: Counter[Any],
    output: Counter[Any],
) -> tuple[float, float, float, int]:
    source_total = int(sum(source.values()))
    output_total = int(sum(output.values()))
    matched = int(sum((source & output).values()))
    recall = matched / source_total if source_total else 0.0
    precision = matched / output_total if output_total else 0.0
    f1 = (
        2.0 * recall * precision / (recall + precision)
        if recall + precision > 0.0
        else 0.0
    )
    return recall, precision, f1, matched


def _text_preservation_metrics(
    source_pages: list[str],
    output_pages: list[str],
) -> dict[str, Any]:
    source_normalized = [_normalize_semantic_text(text) for text in source_pages]
    output_normalized = [_normalize_semantic_text(text) for text in output_pages]
    source_characters = sum(len(text) for text in source_normalized)
    output_characters = sum(len(text) for text in output_normalized)
    base: dict[str, Any] = {
        "method": (
            "NFKC/casefold text, punctuation and whitespace removed, "
            "multiset character trigrams"
        ),
        "source_extracted_characters": source_characters,
        "output_extracted_characters": output_characters,
        "source_pages_with_text": sum(bool(text) for text in source_normalized),
        "output_pages_with_text": sum(bool(text) for text in output_normalized),
        "recall_weight": 0.8,
        "precision_weight": 0.2,
    }
    if source_characters == 0:
        return {
            **base,
            "status": "not_assessable",
            "score": None,
            "reason": "the source PDF exposes no extractable text; OCR was not inferred",
        }

    source_grams = _text_ngram_counter(source_pages)
    output_grams = _text_ngram_counter(output_pages)
    recall, precision, f1, matched = _counter_overlap_metrics(source_grams, output_grams)
    score_ratio = recall * 0.8 + precision * 0.2
    return {
        **base,
        "status": "assessed",
        "score": round(score_ratio * 100.0, 2),
        "source_ngrams": int(sum(source_grams.values())),
        "output_ngrams": int(sum(output_grams.values())),
        "matched_ngrams": matched,
        "recall_ratio": round(recall, 4),
        "precision_ratio": round(precision, 4),
        "f1_ratio": round(f1, 4),
    }


def _fallback_problem_numbers(text: str) -> list[int]:
    numbers: list[int] = []
    for line in str(text or "").splitlines():
        match = (
            _FALLBACK_PROBLEM_MARKER_RE.match(line)
            or _FALLBACK_KOREAN_PROBLEM_MARKER_RE.match(line)
        )
        if match:
            number = int(match.group(1))
            if 1 <= number <= 999:
                numbers.append(number)
    return numbers


def _extract_problem_numbers(page: fitz.Page, text: str) -> list[int]:
    """Reuse the PDF segmenter's marker filtering, with a local compatibility fallback."""

    try:
        from app.recognition.pdf_segment import (  # noqa: PLC0415 - optional private reuse
            _extract_markers,
            _extract_text_lines,
            _filter_choice_like_markers,
        )

        lines = _extract_text_lines(page, 1.0)
        markers = _extract_markers(lines, height_px=float(page.rect.height))
        markers, _suppressed = _filter_choice_like_markers(
            markers,
            width_px=float(page.rect.width),
            height_px=float(page.rect.height),
        )
        numbers = [int(marker["number"]) for marker in markers]
        return numbers or _fallback_problem_numbers(text)
    except Exception:
        return _fallback_problem_numbers(text)


def _problem_number_preservation_metrics(
    source_pages: list[list[int]],
    output_pages: list[list[int]],
) -> dict[str, Any]:
    source_numbers = [number for page in source_pages for number in page]
    output_numbers = [number for page in output_pages for number in page]
    source_unique = sorted(set(source_numbers))
    output_unique = sorted(set(output_numbers))
    base: dict[str, Any] = {
        "method": "unique detected problem labels; multiplicity is reported but not scored",
        "source_detected_occurrences": len(source_numbers),
        "output_detected_occurrences": len(output_numbers),
        "source_unique_numbers": source_unique,
        "output_unique_numbers": output_unique,
        "source_pages_with_numbers": sum(bool(page) for page in source_pages),
        "output_pages_with_numbers": sum(bool(page) for page in output_pages),
    }
    if not source_unique:
        return {
            **base,
            "status": "not_assessable",
            "score": None,
            "reason": "no reliable problem-number labels were detected in the source PDF",
        }

    source_counter = Counter(source_unique)
    output_counter = Counter(output_unique)
    recall, precision, f1, matched = _counter_overlap_metrics(source_counter, output_counter)
    score_ratio = recall * 0.8 + precision * 0.2
    source_occurrences = Counter(source_numbers)
    output_occurrences = Counter(output_numbers)
    occurrence_recall, occurrence_precision, occurrence_f1, occurrence_matched = (
        _counter_overlap_metrics(source_occurrences, output_occurrences)
    )
    return {
        **base,
        "status": "assessed",
        "score": round(score_ratio * 100.0, 2),
        "matched_unique_numbers": matched,
        "missing_numbers": sorted(set(source_unique) - set(output_unique)),
        "unexpected_numbers": sorted(set(output_unique) - set(source_unique)),
        "unique_recall_ratio": round(recall, 4),
        "unique_precision_ratio": round(precision, 4),
        "unique_f1_ratio": round(f1, 4),
        "occurrence_matched": occurrence_matched,
        "occurrence_recall_ratio": round(occurrence_recall, 4),
        "occurrence_precision_ratio": round(occurrence_precision, 4),
        "occurrence_f1_ratio": round(occurrence_f1, 4),
    }


def _divider_result(
    *,
    present: bool,
    method: str | None = None,
    normalized_x: float | None = None,
    normalized_top: float | None = None,
    normalized_bottom: float | None = None,
    candidate_count: int = 0,
) -> dict[str, Any]:
    length_ratio = (
        max(0.0, normalized_bottom - normalized_top)
        if normalized_top is not None and normalized_bottom is not None
        else None
    )
    return {
        "present": present,
        "method": method,
        "normalized_x": round(normalized_x, 4) if normalized_x is not None else None,
        "normalized_top": round(normalized_top, 4) if normalized_top is not None else None,
        "normalized_bottom": (
            round(normalized_bottom, 4) if normalized_bottom is not None else None
        ),
        "length_ratio": round(length_ratio, 4) if length_ratio is not None else None,
        "candidate_count": int(candidate_count),
    }


def _vector_central_divider(page: fitz.Page) -> dict[str, Any] | None:
    width = float(page.rect.width)
    height = float(page.rect.height)
    if width <= 0.0 or height <= 0.0:
        return None

    candidates: list[tuple[float, float, float]] = []

    def add_candidate(x: float, top: float, bottom: float) -> None:
        if bottom < top:
            top, bottom = bottom, top
        normalized_x = x / width
        length_ratio = (bottom - top) / height
        if abs(normalized_x - 0.5) <= 0.06 and length_ratio >= 0.30:
            candidates.append((normalized_x, max(0.0, top / height), min(1.0, bottom / height)))

    try:
        drawings = page.get_drawings()
    except Exception:
        drawings = []
    for drawing in drawings:
        rect = drawing.get("rect")
        if rect is not None:
            rect_width = abs(float(rect.x1) - float(rect.x0))
            if rect_width <= max(3.0, width * 0.015):
                add_candidate(
                    (float(rect.x0) + float(rect.x1)) / 2.0,
                    float(rect.y0),
                    float(rect.y1),
                )
        for item in drawing.get("items") or []:
            if not item or item[0] != "l" or len(item) < 3:
                continue
            start, end = item[1], item[2]
            if abs(float(start.x) - float(end.x)) > max(2.0, width * 0.005):
                continue
            add_candidate(
                (float(start.x) + float(end.x)) / 2.0,
                float(start.y),
                float(end.y),
            )
    if not candidates:
        return None

    unique = {
        (round(x, 4), round(top, 4), round(bottom, 4))
        for x, top, bottom in candidates
    }
    best_x, best_top, best_bottom = max(
        candidates,
        key=lambda item: ((item[2] - item[1]), -abs(item[0] - 0.5)),
    )
    return _divider_result(
        present=True,
        method="vector",
        normalized_x=best_x,
        normalized_top=best_top,
        normalized_bottom=best_bottom,
        candidate_count=len(unique),
    )


def _longest_true_run(values: np.ndarray) -> int:
    if values.size == 0 or not bool(values.any()):
        return 0
    padded = np.pad(values.astype(np.int8), (1, 1), constant_values=0)
    transitions = np.diff(padded)
    starts = np.flatnonzero(transitions == 1)
    ends = np.flatnonzero(transitions == -1)
    return int(np.max(ends - starts)) if starts.size and ends.size else 0


def _raster_central_divider(image: Image.Image) -> dict[str, Any] | None:
    mask = np.asarray(_foreground_mask(image), dtype=np.uint8) > 0
    height, width = mask.shape
    if width <= 0 or height <= 0:
        return None
    y0, y1 = int(height * 0.07), int(height * 0.95)
    x0, x1 = int(width * 0.44), max(int(width * 0.56), int(width * 0.44) + 1)
    body = mask[y0:y1, x0:x1]
    if body.size == 0:
        return None

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
    top = (y0 + int(active[0])) / height
    bottom = (y0 + int(active[-1]) + 1) / height
    return {
        **_divider_result(
            present=True,
            method="raster",
            normalized_x=(x0 + local_x + 0.5) / width,
            normalized_top=top,
            normalized_bottom=bottom,
            candidate_count=len(candidates),
        ),
        "column_occupancy_ratio": round(occupancy, 4),
        "longest_run_ratio": round(run_ratio, 4),
    }


def _central_divider_metrics(page: fitz.Page, image: Image.Image) -> dict[str, Any]:
    vector = _vector_central_divider(page)
    if vector is not None:
        return vector
    raster = _raster_central_divider(image)
    if raster is not None:
        return raster
    return _divider_result(present=False)


def _divider_pair_score(source: dict[str, Any], output: dict[str, Any]) -> float:
    source_present = bool(source.get("present"))
    output_present = bool(output.get("present"))
    if not source_present and not output_present:
        return 100.0
    if source_present != output_present:
        return 0.0

    source_x = float(source.get("normalized_x") or 0.5)
    output_x = float(output.get("normalized_x") or 0.5)
    x_delta = abs(source_x - output_x)
    x_score = 1.0 if x_delta <= 0.03 else max(0.0, 1.0 - (x_delta - 0.03) / 0.05)
    source_length = float(source.get("length_ratio") or 0.0)
    output_length = float(output.get("length_ratio") or 0.0)
    if source_length <= 0.0 and output_length <= 0.0:
        length_score = 1.0
    elif source_length <= 0.0 or output_length <= 0.0:
        length_score = 0.0
    else:
        length_ratio = min(source_length, output_length) / max(source_length, output_length)
        length_score = min(1.0, length_ratio / 0.75)
    return round((x_score * 0.70 + length_score * 0.30) * 100.0, 2)


def _page_duplicate_fingerprint(image: Image.Image) -> np.ndarray:
    gray = image.convert("L")
    y0, y1 = int(gray.height * 0.07), max(int(gray.height * 0.95), int(gray.height * 0.07) + 1)
    body = gray.crop((0, y0, gray.width, y1))
    mask = _foreground_mask(body).filter(ImageFilter.MaxFilter(3))
    reduced = mask.resize((192, 256), Image.Resampling.BOX)
    return np.asarray(reduced, dtype=np.uint8) >= 64


def _fingerprint_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_count = int(left.sum())
    right_count = int(right.sum())
    if left_count == 0 and right_count == 0:
        return 1.0
    if left_count == 0 or right_count == 0:
        return 0.0
    intersection = int(np.logical_and(left, right).sum())
    return (2.0 * intersection) / (left_count + right_count)


def _duplicate_page_pairs(
    fingerprints: list[np.ndarray],
    normalized_texts: list[str],
    *,
    threshold: float,
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for left_index in range(len(fingerprints)):
        for right_index in range(left_index + 1, len(fingerprints)):
            similarity = _fingerprint_similarity(
                fingerprints[left_index], fingerprints[right_index]
            )
            if similarity < threshold:
                continue
            left_text = normalized_texts[left_index] if left_index < len(normalized_texts) else ""
            right_text = (
                normalized_texts[right_index]
                if right_index < len(normalized_texts)
                else ""
            )
            text_similarity: float | None = None
            if left_text or right_text:
                if not left_text or not right_text:
                    continue
                left_grams = _text_ngram_counter([left_text])
                right_grams = _text_ngram_counter([right_text])
                _recall, _precision, text_similarity, _matched = _counter_overlap_metrics(
                    left_grams, right_grams
                )
                if text_similarity < 0.995:
                    continue
            pairs.append(
                {
                    "pages": [left_index + 1, right_index + 1],
                    "visual_dice_ratio": round(similarity, 4),
                    "text_f1_ratio": round(text_similarity, 4)
                    if text_similarity is not None
                    else None,
                    "normalized_text_equal": bool(left_text and left_text == right_text),
                }
            )
    return pairs


def _difference_heatmap(source: Image.Image, output: Image.Image) -> Image.Image:
    delta = np.asarray(
        ImageChops.difference(source.convert("RGB"), output.convert("RGB")).convert("L"),
        dtype=np.uint8,
    )
    intensity = np.clip(delta.astype(np.uint16) * 4, 0, 255).astype(np.uint8)
    heatmap = np.full((*intensity.shape, 3), 255, dtype=np.uint8)
    heatmap[:, :, 1] = 255 - intensity
    heatmap[:, :, 2] = 255 - intensity
    return Image.fromarray(heatmap, mode="RGB")


def _missing_page_image(size: tuple[int, int], label: str) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    text_bbox = draw.textbbox((0, 0), label)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    draw.rectangle((0, 0, size[0] - 1, size[1] - 1), outline=(190, 40, 40), width=3)
    draw.text(
        ((size[0] - text_width) // 2, (size[1] - text_height) // 2),
        label,
        fill=(160, 20, 20),
    )
    return image


def _comparison_image(
    source: Image.Image,
    output: Image.Image,
    *,
    page_number: int,
) -> tuple[Image.Image, Image.Image, Image.Image]:
    raw_diff = ImageChops.difference(source.convert("RGB"), output.convert("RGB"))
    heatmap = _difference_heatmap(source, output)
    labels = ("SOURCE", "HANCOM OUTPUT", "DIFFERENCE x4")
    gap = 12
    header_height = 30
    width, height = source.size
    canvas = Image.new(
        "RGB",
        (width * 3 + gap * 2, height + header_height),
        (236, 238, 241),
    )
    draw = ImageDraw.Draw(canvas)
    panels = (source, output, heatmap)
    for index, (label, panel) in enumerate(zip(labels, panels)):
        x = index * (width + gap)
        draw.text((x + 8, 8), label, fill=(20, 24, 31))
        canvas.paste(panel, (x, header_height))
    draw.text((canvas.width - 78, 8), f"PAGE {page_number}", fill=(20, 24, 31))
    return canvas, raw_diff, heatmap


def _aggregate_raw_visual_metrics(
    page_metrics: list[dict[str, Any]],
    *,
    target_visual_ratio: float,
) -> dict[str, Any]:
    ratio_keys = {
        "visual_similarity_ratio": "visual_similarity_ratio",
        "whole_page_visual_sync_ratio": "whole_page_visual_sync_ratio",
        "layout_view_sync_ratio": "layout_view_sync_ratio",
        "foreground_overlap_ratio": "foreground_overlap_ratio",
        "strict_alignment_ratio": "strict_alignment_ratio",
    }
    result: dict[str, Any] = {
        "pages_compared": len(page_metrics),
        "target_minimum_strict_alignment_ratio": target_visual_ratio,
        "note": (
            "Raw rendered-pixel measurements only. White-page similarity can look high even "
            "when content is missing, so these values are excluded from the semantic score."
        ),
    }
    for output_name, metric_name in ratio_keys.items():
        values = [float(page[metric_name]) for page in page_metrics]
        result[f"mean_{output_name}"] = round(sum(values) / len(values), 4) if values else 0.0
        result[f"minimum_{output_name}"] = round(min(values), 4) if values else 0.0
    detailed = [float(page["detailed_layout_score"]) for page in page_metrics]
    luma_diffs = [float(page["mean_abs_luma_diff"]) for page in page_metrics]
    result["mean_detailed_layout_score"] = (
        round(sum(detailed) / len(detailed), 2) if detailed else 0.0
    )
    result["minimum_detailed_layout_score"] = round(min(detailed), 2) if detailed else 0.0
    result["maximum_mean_abs_luma_diff"] = round(max(luma_diffs), 3) if luma_diffs else 0.0
    result["meets_target"] = bool(page_metrics) and (
        float(result["minimum_strict_alignment_ratio"]) >= target_visual_ratio
    )
    return result


def _page_count_component(source_count: int, output_count: int) -> dict[str, Any]:
    maximum = max(source_count, output_count)
    ratio = min(source_count, output_count) / maximum if maximum else 1.0
    return {
        "status": "assessed",
        "score": round(ratio * 100.0, 2),
        "source_page_count": source_count,
        "output_page_count": output_count,
        "exact_match": source_count == output_count,
        "preserved_page_count_ratio": round(ratio, 4),
        "missing_output_pages": list(range(output_count + 1, source_count + 1))
        if source_count > output_count
        else [],
        "unexpected_output_pages": list(range(source_count + 1, output_count + 1))
        if output_count > source_count
        else [],
    }


def _duplicate_page_component(
    source_pairs: list[dict[str, Any]],
    output_pairs: list[dict[str, Any]],
    *,
    output_page_count: int,
    threshold: float,
) -> dict[str, Any]:
    source_pair_keys = {tuple(pair["pages"]) for pair in source_pairs}
    unexpected_pairs = [
        pair for pair in output_pairs if tuple(pair["pages"]) not in source_pair_keys
    ]
    unexpected_duplicate_pages = sorted(
        {int(pair["pages"][1]) for pair in unexpected_pairs}
    )
    denominator = max(1, output_page_count)
    score_ratio = max(0.0, 1.0 - len(unexpected_duplicate_pages) / denominator)
    return {
        "status": "assessed",
        "score": round(score_ratio * 100.0, 2),
        "method": "body-region foreground Dice similarity",
        "similarity_threshold": threshold,
        "source_duplicate_pairs": source_pairs,
        "output_duplicate_pairs": output_pairs,
        "unexpected_output_duplicate_pairs": unexpected_pairs,
        "unexpected_output_duplicate_pages": unexpected_duplicate_pages,
        "has_unexpected_output_duplicates": bool(unexpected_pairs),
    }


def _central_divider_component(
    page_results: list[dict[str, Any]],
) -> dict[str, Any]:
    if not page_results:
        return {
            "status": "not_assessable",
            "score": None,
            "reason": "there are no paired pages on which to compare the divider",
            "pages": [],
        }
    scores = [float(page["score"]) for page in page_results]
    mismatches = [int(page["page"]) for page in page_results if float(page["score"]) < 99.5]
    return {
        "status": "assessed",
        "score": round(sum(scores) / len(scores), 2),
        "method": "vector rule detection with a raster long-column fallback",
        "source_present_pages": [
            int(page["page"]) for page in page_results if page["source"].get("present")
        ],
        "output_present_pages": [
            int(page["page"]) for page in page_results if page["output"].get("present")
        ],
        "mismatch_pages": mismatches,
        "pages": page_results,
    }


def _semantic_implementation_summary(
    components: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    assessed_weight = 0.0
    weighted_points = 0.0
    component_payload: dict[str, dict[str, Any]] = {}
    for name, component in components.items():
        weight = float(PDF_PDF_SEMANTIC_WEIGHTS[name])
        payload = {"weight": weight, **component}
        component_payload[name] = payload
        score = component.get("score")
        if component.get("status") == "assessed" and score is not None:
            assessed_weight += weight
            weighted_points += float(score) * weight

    score = weighted_points / assessed_weight if assessed_weight else 0.0
    total_weight = float(sum(PDF_PDF_SEMANTIC_WEIGHTS.values()))
    conservative_score = weighted_points / total_weight if total_weight else 0.0
    coverage = assessed_weight / total_weight if total_weight else 0.0
    return {
        "score": round(score, 2),
        "conservative_score_unassessed_as_zero": round(conservative_score, 2),
        "assessment_coverage_ratio": round(coverage, 4),
        "assessed_weight": round(assessed_weight, 2),
        "total_weight": round(total_weight, 2),
        "unassessed_components": [
            name
            for name, component in component_payload.items()
            if component.get("status") != "assessed"
        ],
        "methodology": (
            "Weighted only across assessable semantic checks. The conservative score treats "
            "unassessed checks as zero; assessment coverage must be read with the score."
        ),
        "components": component_payload,
    }


def analyze_pdf_pdf_fidelity(
    source_pdf_path: str | Path,
    output_pdf_path: str | Path,
    output_dir: str | Path,
    *,
    render_dpi: int = PDF_PDF_DEFAULT_RENDER_DPI,
    artifact_mode: str = "all",
    target_visual_ratio: float = STRICT_ALIGNMENT_REVIEW_THRESHOLD,
    target_semantic_score: float = 90.0,
    minimum_assessment_coverage: float = PDF_PDF_MINIMUM_ASSESSMENT_COVERAGE,
    duplicate_similarity_threshold: float = PDF_PDF_DUPLICATE_SIMILARITY_THRESHOLD,
    source_page_limit: int | None = None,
) -> dict[str, Any]:
    """Compare an original PDF with a PDF saved by Hancom over every page.

    Rendered-pixel measurements are intentionally kept outside the semantic
    implementation score. The semantic score covers page count, extractable
    text, detected problem labels, unexpected duplicate output pages, and the
    central column divider. Unobservable text/labels remain unassessed and
    lower the reported assessment coverage instead of receiving free credit.
    """

    allowed_artifact_modes = {"all", "comparisons", "failures", "none"}
    if artifact_mode not in allowed_artifact_modes:
        raise ValueError(
            f"artifact_mode must be one of {sorted(allowed_artifact_modes)}, got {artifact_mode!r}"
        )
    if render_dpi <= 0:
        raise ValueError("render_dpi must be positive")
    if not 0.0 <= target_visual_ratio <= 1.0:
        raise ValueError("target_visual_ratio must be between 0 and 1")
    if not 0.0 <= target_semantic_score <= 100.0:
        raise ValueError("target_semantic_score must be between 0 and 100")
    if not 0.0 <= minimum_assessment_coverage <= 1.0:
        raise ValueError("minimum_assessment_coverage must be between 0 and 1")
    if not 0.0 < duplicate_similarity_threshold <= 1.0:
        raise ValueError("duplicate_similarity_threshold must be in (0, 1]")
    if source_page_limit is not None and source_page_limit <= 0:
        raise ValueError("source_page_limit must be positive")

    source_pdf_path = Path(source_pdf_path)
    output_pdf_path = Path(output_pdf_path)
    output_dir = Path(output_dir)
    result_base: dict[str, Any] = {
        "schema_version": 1,
        "available": True,
        "skipped": False,
        "source_pdf": str(source_pdf_path.resolve()),
        "output_pdf": str(output_pdf_path.resolve()),
        "artifact_dir": str(output_dir.resolve()),
        "artifact_mode": artifact_mode,
        "render_dpi": render_dpi,
        "target_visual_ratio": target_visual_ratio,
        "target_semantic_score": target_semantic_score,
        "minimum_assessment_coverage": minimum_assessment_coverage,
        "duplicate_similarity_threshold": duplicate_similarity_threshold,
        "source_page_limit": source_page_limit,
    }

    try:
        if not source_pdf_path.is_file():
            raise FileNotFoundError(f"source PDF not found: {source_pdf_path}")
        if not output_pdf_path.is_file():
            raise FileNotFoundError(f"output PDF not found: {output_pdf_path}")
        output_dir.mkdir(parents=True, exist_ok=True)

        with fitz.open(source_pdf_path) as source_document, fitz.open(
            output_pdf_path
        ) as output_document:
            source_document_page_count = len(source_document)
            source_page_count = min(
                source_document_page_count,
                source_page_limit or source_document_page_count,
            )
            output_page_count = len(output_document)
            source_pages = [source_document[index] for index in range(source_page_count)]
            source_text_pages = [_extract_pdf_text(page) for page in source_pages]
            output_text_pages = [_extract_pdf_text(page) for page in output_document]
            source_problem_pages = [
                _extract_problem_numbers(page, source_text_pages[index])
                for index, page in enumerate(source_pages)
            ]
            output_problem_pages = [
                _extract_problem_numbers(page, output_text_pages[index])
                for index, page in enumerate(output_document)
            ]
            source_normalized_pages = [
                _normalize_semantic_text(text) for text in source_text_pages
            ]
            output_normalized_pages = [
                _normalize_semantic_text(text) for text in output_text_pages
            ]

            pages: list[dict[str, Any]] = []
            raw_page_metrics: list[dict[str, Any]] = []
            source_fingerprints: list[np.ndarray] = []
            output_fingerprints: list[np.ndarray] = []
            divider_page_results: list[dict[str, Any]] = []
            aspect_mismatch_pages: list[int] = []
            represented_page_count = max(source_page_count, output_page_count)

            for page_index in range(represented_page_count):
                page_number = page_index + 1
                source_page = (
                    source_document[page_index] if page_index < source_page_count else None
                )
                output_page = (
                    output_document[page_index] if page_index < output_page_count else None
                )
                reference_page = source_page if source_page is not None else output_page
                if reference_page is None:  # pragma: no cover - PDFs cannot have a negative count
                    continue
                target_size = _pdf_page_target_size(reference_page, render_dpi)
                source_image = (
                    _render_pdf_page(source_page, target_size)
                    if source_page is not None
                    else None
                )
                output_image = (
                    _render_pdf_page(output_page, target_size)
                    if output_page is not None
                    else None
                )

                if source_image is not None:
                    source_fingerprints.append(_page_duplicate_fingerprint(source_image))
                if output_image is not None:
                    output_fingerprints.append(_page_duplicate_fingerprint(output_image))

                source_divider = (
                    _central_divider_metrics(source_page, source_image)
                    if source_page is not None and source_image is not None
                    else _divider_result(present=False)
                )
                output_divider = (
                    _central_divider_metrics(output_page, output_image)
                    if output_page is not None and output_image is not None
                    else _divider_result(present=False)
                )
                divider_score: float | None = None
                if source_page is not None and output_page is not None:
                    divider_score = _divider_pair_score(source_divider, output_divider)
                    divider_page_results.append(
                        {
                            "page": page_number,
                            "score": divider_score,
                            "source": source_divider,
                            "output": output_divider,
                        }
                    )

                metrics: dict[str, Any] | None = None
                source_aspect: float | None = None
                output_aspect: float | None = None
                aspect_delta: float | None = None
                if source_page is not None:
                    source_aspect = _safe_aspect_ratio(
                        float(source_page.rect.width), float(source_page.rect.height)
                    )
                if output_page is not None:
                    output_aspect = _safe_aspect_ratio(
                        float(output_page.rect.width), float(output_page.rect.height)
                    )
                if source_image is not None and output_image is not None:
                    metrics = _page_metrics(source_image, output_image)
                    raw_page_metrics.append(metrics)
                    aspect_delta = abs(float(source_aspect) - float(output_aspect))
                    if aspect_delta > ASPECT_RATIO_TOLERANCE:
                        aspect_mismatch_pages.append(page_number)

                source_page_text = (
                    source_text_pages[page_index] if page_index < source_page_count else ""
                )
                output_page_text = (
                    output_text_pages[page_index] if page_index < output_page_count else ""
                )
                page_text_metrics = _text_preservation_metrics(
                    [source_page_text] if source_page is not None else [],
                    [output_page_text] if output_page is not None else [],
                )
                source_page_numbers = (
                    source_problem_pages[page_index] if page_index < source_page_count else []
                )
                output_page_numbers = (
                    output_problem_pages[page_index] if page_index < output_page_count else []
                )

                comparison_status = (
                    "paired"
                    if source_page is not None and output_page is not None
                    else "missing_output"
                    if source_page is not None
                    else "unexpected_output"
                )
                page_failure = comparison_status != "paired"
                if metrics is not None:
                    page_failure = page_failure or (
                        float(metrics["strict_alignment_ratio"]) < target_visual_ratio
                    )
                if divider_score is not None:
                    page_failure = page_failure or divider_score < 99.5
                if page_text_metrics.get("status") == "assessed":
                    page_failure = page_failure or float(page_text_metrics["score"]) < 90.0
                page_failure = page_failure or set(source_page_numbers) != set(output_page_numbers)

                save_comparison = artifact_mode in {"all", "comparisons"} or (
                    artifact_mode == "failures" and page_failure
                )
                save_individual = artifact_mode == "all"
                source_name = f"source_page_{page_number:03d}.png"
                output_name = f"output_page_{page_number:03d}.png"
                diff_name = f"diff_page_{page_number:03d}.png"
                heatmap_name = f"heatmap_page_{page_number:03d}.png"
                comparison_name = f"comparison_page_{page_number:03d}.png"

                if save_individual and source_image is not None:
                    source_image.save(output_dir / source_name)
                if save_individual and output_image is not None:
                    output_image.save(output_dir / output_name)
                if save_comparison:
                    source_panel = source_image or _missing_page_image(
                        target_size, "NO SOURCE PAGE"
                    )
                    output_panel = output_image or _missing_page_image(
                        target_size, "MISSING OUTPUT PAGE"
                    )
                    comparison, raw_diff, heatmap = _comparison_image(
                        source_panel,
                        output_panel,
                        page_number=page_number,
                    )
                    comparison.save(output_dir / comparison_name)
                    if save_individual:
                        raw_diff.save(output_dir / diff_name)
                        heatmap.save(output_dir / heatmap_name)
                    comparison.close()
                    raw_diff.close()
                    heatmap.close()
                    if source_image is None:
                        source_panel.close()
                    if output_image is None:
                        output_panel.close()

                pages.append(
                    {
                        "page": page_number,
                        "comparison_status": comparison_status,
                        "source_page_size_pt": [
                            round(float(source_page.rect.width), 3),
                            round(float(source_page.rect.height), 3),
                        ]
                        if source_page is not None
                        else None,
                        "output_page_size_pt": [
                            round(float(output_page.rect.width), 3),
                            round(float(output_page.rect.height), 3),
                        ]
                        if output_page is not None
                        else None,
                        "render_size_px": list(target_size),
                        "source_page_aspect_ratio": round(source_aspect, 4)
                        if source_aspect is not None
                        else None,
                        "output_page_aspect_ratio": round(output_aspect, 4)
                        if output_aspect is not None
                        else None,
                        "aspect_ratio_delta": round(aspect_delta, 4)
                        if aspect_delta is not None
                        else None,
                        "aspect_ratio_mismatch": bool(
                            aspect_delta is not None
                            and aspect_delta > ASPECT_RATIO_TOLERANCE
                        ),
                        "source_extracted_text_characters": len(
                            _normalize_semantic_text(source_page_text)
                        ),
                        "output_extracted_text_characters": len(
                            _normalize_semantic_text(output_page_text)
                        ),
                        "text_preservation": page_text_metrics,
                        "source_problem_numbers": source_page_numbers,
                        "output_problem_numbers": output_page_numbers,
                        "central_divider": {
                            "score": divider_score,
                            "source": source_divider,
                            "output": output_divider,
                        },
                        "raw_visual_metrics": metrics,
                        "source_png": source_name
                        if save_individual and source_image is not None
                        else None,
                        "output_png": output_name
                        if save_individual and output_image is not None
                        else None,
                        "diff_png": diff_name if save_individual and save_comparison else None,
                        "heatmap_png": heatmap_name
                        if save_individual and save_comparison
                        else None,
                        "comparison_png": comparison_name if save_comparison else None,
                    }
                )
                if source_image is not None:
                    source_image.close()
                if output_image is not None:
                    output_image.close()

        source_duplicate_pairs = _duplicate_page_pairs(
            source_fingerprints,
            source_normalized_pages,
            threshold=duplicate_similarity_threshold,
        )
        output_duplicate_pairs = _duplicate_page_pairs(
            output_fingerprints,
            output_normalized_pages,
            threshold=duplicate_similarity_threshold,
        )
        components = {
            "page_count": _page_count_component(source_page_count, output_page_count),
            "text_preservation": _text_preservation_metrics(
                source_text_pages, output_text_pages
            ),
            "problem_number_preservation": _problem_number_preservation_metrics(
                source_problem_pages, output_problem_pages
            ),
            "duplicate_pages": _duplicate_page_component(
                source_duplicate_pairs,
                output_duplicate_pairs,
                output_page_count=output_page_count,
                threshold=duplicate_similarity_threshold,
            ),
            "central_divider": _central_divider_component(divider_page_results),
        }
        semantic = _semantic_implementation_summary(components)
        raw_visual = _aggregate_raw_visual_metrics(
            raw_page_metrics,
            target_visual_ratio=target_visual_ratio,
        )

        problem_component = components["problem_number_preservation"]
        duplicate_component = components["duplicate_pages"]
        divider_component = components["central_divider"]
        review_flags: list[str] = []
        if source_page_count != output_page_count:
            review_flags.append("page_count_mismatch")
        if aspect_mismatch_pages:
            review_flags.append("aspect_ratio_mismatch")
        text_component = components["text_preservation"]
        if text_component.get("status") == "assessed" and float(
            text_component.get("score") or 0.0
        ) < target_semantic_score:
            review_flags.append("text_preservation_below_target")
        if problem_component.get("missing_numbers"):
            review_flags.append("missing_problem_numbers")
        if problem_component.get("unexpected_numbers"):
            review_flags.append("unexpected_problem_numbers")
        if duplicate_component.get("has_unexpected_output_duplicates"):
            review_flags.append("unexpected_duplicate_output_pages")
        if divider_component.get("mismatch_pages"):
            review_flags.append("central_divider_mismatch")
        if not raw_visual.get("meets_target"):
            review_flags.append("raw_visual_below_target")
        if float(semantic["score"]) < target_semantic_score:
            review_flags.append("semantic_score_below_target")
        if float(semantic["assessment_coverage_ratio"]) < minimum_assessment_coverage:
            review_flags.append("low_semantic_assessment_coverage")

        return {
            **result_base,
            "source_page_count": source_page_count,
            "source_document_page_count": source_document_page_count,
            "output_page_count": output_page_count,
            "pages_compared": min(source_page_count, output_page_count),
            "pages_represented": max(source_page_count, output_page_count),
            "all_pages_analyzed": True,
            "missing_output_pages": components["page_count"]["missing_output_pages"],
            "unexpected_output_pages": components["page_count"][
                "unexpected_output_pages"
            ],
            "aspect_ratio_tolerance": ASPECT_RATIO_TOLERANCE,
            "aspect_ratio_mismatch_pages": aspect_mismatch_pages,
            "raw_visual_metrics": raw_visual,
            "semantic_implementation": semantic,
            "semantic_implementation_score": semantic["score"],
            "semantic_assessment_coverage_ratio": semantic[
                "assessment_coverage_ratio"
            ],
            "review_flags": review_flags,
            "needs_human_review": bool(review_flags),
            "meets_target": not review_flags,
            "pages": pages,
        }
    except Exception as exc:
        return {
            **result_base,
            "error": f"{type(exc).__name__}: {exc}",
            "meets_target": False,
        }


# Descriptive aliases for callers that name the Hancom leg explicitly.
analyze_hancom_pdf_visual_fidelity = analyze_pdf_pdf_fidelity
analyze_pdf_to_pdf_fidelity = analyze_pdf_pdf_fidelity
