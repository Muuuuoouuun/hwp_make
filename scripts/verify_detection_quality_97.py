#!/usr/bin/env python3
"""Independently verify detection quality for a packaged four-subject conversion.

This verifier deliberately does not read generation_report.json.  Its source-side
inventory is rebuilt from the packaged PDFs with PyMuPDF, then compared with the
HWPX XML and the PDF exported by Hancom.  The graphic/table/box portion is scoped
to signals that can be measured without inventing semantic ground truth.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

try:
    import fitz  # PyMuPDF
except ImportError as exc:  # pragma: no cover - environment failure path
    raise SystemExit("PyMuPDF is required: python -m pip install pymupdf") from exc


SUBJECTS = ("korean", "english", "math_a", "math_b")
LANGUAGE_SUBJECTS = ("korean", "english")
MATH_SUBJECTS = ("math_a", "math_b")

ODD_VARIANT = "\ud640\uc218\ud615"
EVEN_VARIANT = "\uc9dd\uc218\ud615"
PROBLEM_TOKEN_RE = re.compile(r"(?:[1-9]|[1-4][0-9]|50)")
PROBLEM_LINE_RE = re.compile(
    r"^\s*((?:[1-9]|[1-4][0-9]|50))\s*[.]\s*(?=\S|$)"
)
PROBLEM_WORD_RE = re.compile(r"((?:[1-9]|[1-4][0-9]|50))[.]")
MATH_FONT_HINTS = ("hyhwpeq", "hancomeqn")
PUA_MIN = 0xE000
PUA_MAX = 0xF8FF
FRACTION_RULE_PUA = "\ue06d"
NUMERIC_PUA = {chr(value) for value in range(0xE034, 0xE03E)} | {"\ue053"}
SCRIPT_PLACEHOLDERS = ("\ufffd", "\u25a1", "\u2610", "\u25a0")

RUBRIC_WEIGHTS = {
    "page_and_variant": 20.0,
    "problem_inventory": 40.0,
    "native_math": 25.0,
    "source_feature_contract": 15.0,
}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _natural_key(value: str) -> list[object]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _ratio(numerator: float, denominator: float, *, empty: float = 1.0) -> float:
    if denominator == 0:
        return empty
    return numerator / denominator


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _round(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def _ordered_unique(values: list[int]) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _normalize_similarity_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").lower()
    normalized = normalized.replace(ODD_VARIANT, "").replace(EVEN_VARIANT, "")
    return re.sub(r"[^0-9a-z\uac00-\ud7a3]+", "", normalized)


def _ngram_f1(left: str, right: str, size: int = 3) -> float:
    left = _normalize_similarity_text(left)
    right = _normalize_similarity_text(right)
    left_grams = {
        left[index : index + size]
        for index in range(max(0, len(left) - size + 1))
    }
    right_grams = {
        right[index : index + size]
        for index in range(max(0, len(right) - size + 1))
    }
    if not left_grams and not right_grams:
        return 1.0
    if not left_grams or not right_grams:
        return 0.0
    return 2.0 * len(left_grams & right_grams) / (len(left_grams) + len(right_grams))


def _set_f1(expected: set[int], actual: set[int]) -> float:
    if not expected and not actual:
        return 1.0
    if not expected or not actual:
        return 0.0
    return 2.0 * len(expected & actual) / (len(expected) + len(actual))


def _labels_from_lines(page: fitz.Page) -> list[int]:
    labels: list[int] = []
    for line in page.get_text("text").splitlines():
        match = PROBLEM_LINE_RE.match(line)
        if match:
            labels.append(int(match.group(1)))
    return _ordered_unique(labels)


def _labels_from_words(page: fitz.Page) -> list[int]:
    labels: list[int] = []
    for word in page.get_text("words", sort=True):
        token = str(word[4]).strip()
        match = PROBLEM_WORD_RE.fullmatch(token)
        if match:
            labels.append(int(match.group(1)))
    return _ordered_unique(labels)


def _pdf_label_inventory(doc: fitz.Document, page_indices: list[int]) -> dict[str, object]:
    pages: list[dict[str, object]] = []
    agreement_scores: list[float] = []
    selected_labels: list[list[int]] = []
    for output_index, source_index in enumerate(page_indices):
        page = doc[source_index]
        line_labels = _labels_from_lines(page)
        word_labels = _labels_from_words(page)
        line_set = set(line_labels)
        word_set = set(word_labels)
        agreement = _set_f1(line_set, word_set)
        agreement_scores.append(agreement)
        consensus = line_labels if line_set == word_set else sorted(line_set & word_set)
        selected_labels.append(consensus)
        pages.append(
            {
                "output_page": output_index + 1,
                "physical_source_page": source_index + 1,
                "line_labels": line_labels,
                "word_labels": word_labels,
                "agreement_f1": _round(agreement),
                "consensus_labels": consensus,
            }
        )
    return {
        "pages": pages,
        "labels_by_page": selected_labels,
        "extractor_agreement": _round(_mean(agreement_scores)),
        "all_pages_exact_agreement": all(score == 1.0 for score in agreement_scores),
    }


def _label_order_coherence(labels_by_page: list[list[int]]) -> dict[str, object]:
    if not labels_by_page:
        return {
            "score": 0.0,
            "nonempty_page_ratio": 0.0,
            "sorted_unique_page_ratio": 0.0,
            "contiguous_run_ratio": 0.0,
            "runs": [],
        }

    nonempty_ratio = _mean([1.0 if labels else 0.0 for labels in labels_by_page])
    page_order_scores = [
        1.0 if labels == sorted(set(labels)) else 0.0 for labels in labels_by_page
    ]
    flattened = [label for page_labels in labels_by_page for label in page_labels]
    runs: list[list[int]] = []
    for label in flattened:
        if not runs or (runs[-1] and label <= runs[-1][-1]):
            runs.append([label])
        else:
            runs[-1].append(label)
    adjacency_checks: list[float] = []
    for run in runs:
        adjacency_checks.extend(
            1.0 if right == left + 1 else 0.0
            for left, right in zip(run, run[1:])
        )
    contiguous_ratio = _mean(adjacency_checks) if adjacency_checks else 1.0
    page_order_ratio = _mean(page_order_scores)
    score = _mean([nonempty_ratio, page_order_ratio, contiguous_ratio])
    return {
        "score": _round(score),
        "nonempty_page_ratio": _round(nonempty_ratio),
        "sorted_unique_page_ratio": _round(page_order_ratio),
        "contiguous_run_ratio": _round(contiguous_ratio),
        "runs": runs,
        "run_count": len(runs),
    }


def _new_hwpx_page() -> dict[str, object]:
    return {
        "text_parts": [],
        "problem_labels": [],
        "equations": [],
        "pictures": 0,
        "tables": 0,
        "rectangles": 0,
        "draw_text": 0,
    }


def _read_hwpx(path: Path) -> dict[str, object]:
    pages: list[dict[str, object]] = []
    media_names: list[str] = []
    xml_entries: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        media_names = [name for name in names if name.lower().startswith("bindata/")]
        section_names = sorted(
            [
                name
                for name in names
                if name.lower().startswith("contents/section")
                and name.lower().endswith(".xml")
            ],
            key=_natural_key,
        )
        if not section_names:
            raise ValueError(f"HWPX has no section XML: {path}")
        for section_name in section_names:
            payload = archive.read(section_name)
            xml_entries.append(payload.decode("utf-8", errors="replace"))
            root = ET.fromstring(payload)
            current = _new_hwpx_page()
            started = False
            for paragraph in list(root):
                if _local_name(paragraph.tag) != "p":
                    continue
                if paragraph.get("pageBreak") == "1" and started:
                    pages.append(current)
                    current = _new_hwpx_page()
                started = True
                for element in paragraph.iter():
                    local = _local_name(element.tag)
                    if local == "t" and element.text:
                        current["text_parts"].append(element.text)
                        match = PROBLEM_WORD_RE.fullmatch(element.text.strip())
                        if match:
                            current["problem_labels"].append(int(match.group(1)))
                    elif local == "pic":
                        current["pictures"] += 1
                    elif local == "tbl":
                        current["tables"] += 1
                    elif local == "rect":
                        current["rectangles"] += 1
                    elif local.lower() == "drawtext":
                        current["draw_text"] += 1
                for equation in (
                    element
                    for element in paragraph.iter()
                    if _local_name(element.tag) == "equation"
                ):
                    scripts = [
                        child.text or ""
                        for child in equation.iter()
                        if _local_name(child.tag) == "script"
                    ]
                    current["equations"].append(
                        {
                            "id": equation.get("id"),
                            "version": equation.get("version"),
                            "font": equation.get("font"),
                            "base_unit": equation.get("baseUnit"),
                            "numbering_type": equation.get("numberingType"),
                            "scripts": scripts,
                        }
                    )
            if started:
                pages.append(current)

    normalized_pages: list[dict[str, object]] = []
    for index, page in enumerate(pages):
        normalized_pages.append(
            {
                "page": index + 1,
                "text": " ".join(page.pop("text_parts")),
                "problem_labels": _ordered_unique(page["problem_labels"]),
                "equations": page["equations"],
                "pictures": page["pictures"],
                "tables": page["tables"],
                "rectangles": page["rectangles"],
                "draw_text": page["draw_text"],
            }
        )
    return {
        "pages": normalized_pages,
        "page_count": len(normalized_pages),
        "media_count": len(media_names),
        "media_names": media_names,
        "forbidden_draw_text_xml_count": sum(
            entry.lower().count("drawtext") for entry in xml_entries
        ),
    }


def _page_problem_comparison(
    expected_by_page: list[list[int]], actual_by_page: list[list[int]]
) -> dict[str, object]:
    page_count = max(len(expected_by_page), len(actual_by_page))
    pages: list[dict[str, object]] = []
    scores: list[float] = []
    for index in range(page_count):
        expected = set(expected_by_page[index]) if index < len(expected_by_page) else set()
        actual = set(actual_by_page[index]) if index < len(actual_by_page) else set()
        score = _set_f1(expected, actual)
        scores.append(score)
        pages.append(
            {
                "page": index + 1,
                "expected": sorted(expected),
                "actual": sorted(actual),
                "missing": sorted(expected - actual),
                "extra": sorted(actual - expected),
                "f1": _round(score),
            }
        )
    return {
        "page_macro_f1": _round(_mean(scores)),
        "minimum_page_f1": _round(min(scores) if scores else 0.0),
        "exact_page_count": sum(score == 1.0 for score in scores),
        "page_count": page_count,
        "pages": pages,
    }


def _variant_marker_counts(texts: list[str]) -> dict[str, int]:
    return {
        "odd": sum(ODD_VARIANT in text for text in texts),
        "even": sum(EVEN_VARIANT in text for text in texts),
    }


def _marker_variant_index(marker_counts: dict[str, int]) -> int | None:
    odd = marker_counts["odd"]
    even = marker_counts["even"]
    if odd > even:
        return 0
    if even > odd:
        return 1
    return None


def _variant_evidence(
    source_texts: list[str],
    output_texts: list[str],
    hwpx_texts: list[str],
    source_labels: list[list[int]],
) -> dict[str, object]:
    output_pages = len(output_texts)
    first = source_texts[:output_pages]
    second = source_texts[output_pages : 2 * output_pages]
    paired_similarity = [_ngram_f1(a, b) for a, b in zip(first, second)]
    output_similarity = [
        _mean([_ngram_f1(output_texts[i], half[i]) for i in range(output_pages)])
        for half in (first, second)
    ]
    hwpx_similarity = [
        _mean([_ngram_f1(hwpx_texts[i], half[i]) for i in range(output_pages)])
        for half in (first, second)
    ]
    output_best = max(range(2), key=output_similarity.__getitem__)
    hwpx_best = max(range(2), key=hwpx_similarity.__getitem__)

    source_marker_counts = [
        _variant_marker_counts(first),
        _variant_marker_counts(second),
    ]
    hwpx_marker_counts = _variant_marker_counts(hwpx_texts)
    hwpx_marker = _marker_variant_index(hwpx_marker_counts)
    marker_to_half: dict[int, int] = {}
    for half_index, counts in enumerate(source_marker_counts):
        marker_index = _marker_variant_index(counts)
        if marker_index is not None:
            marker_to_half[marker_index] = half_index
    marker_selected_half = marker_to_half.get(hwpx_marker) if hwpx_marker is not None else None

    first_labels = source_labels[:output_pages]
    second_labels = source_labels[output_pages : 2 * output_pages]
    paired_label_f1 = [
        _set_f1(set(left), set(right)) for left, right in zip(first_labels, second_labels)
    ]
    selected_half = output_best
    selection_consistent = (
        output_best == hwpx_best
        and (marker_selected_half is None or marker_selected_half == output_best)
    )
    return {
        "physical_halves": 2,
        "paired_trigram_f1_by_page": [_round(value) for value in paired_similarity],
        "paired_trigram_f1_mean": _round(_mean(paired_similarity)),
        "paired_trigram_f1_min": _round(min(paired_similarity) if paired_similarity else 0.0),
        "paired_problem_label_f1_mean": _round(_mean(paired_label_f1)),
        "output_similarity_by_half": [_round(value) for value in output_similarity],
        "hwpx_similarity_by_half": [_round(value) for value in hwpx_similarity],
        "source_marker_counts_by_half": source_marker_counts,
        "hwpx_marker_counts": hwpx_marker_counts,
        "output_similarity_selected_half": output_best,
        "hwpx_similarity_selected_half": hwpx_best,
        "marker_selected_half": marker_selected_half,
        "selected_half": selected_half,
        "selection_consistent": selection_consistent,
    }


def _is_math_span(span: dict[str, object]) -> bool:
    font = str(span.get("font") or "").lower()
    text = str(span.get("text") or "")
    return any(hint in font for hint in MATH_FONT_HINTS) or any(
        PUA_MIN <= ord(char) <= PUA_MAX for char in text
    )


def _math_spans(page: fitz.Page) -> list[dict[str, object]]:
    spans: list[dict[str, object]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = str(span.get("text") or "")
                if not text.strip() or not span.get("bbox") or not _is_math_span(span):
                    continue
                spans.append(
                    {
                        "bbox": fitz.Rect(span["bbox"]),
                        "text": text,
                        "font": str(span.get("font") or ""),
                        "size": float(span.get("size") or 0.0),
                    }
                )
    return spans


def _math_components(
    spans: list[dict[str, object]], *, horizontal_gap: float, vertical_gap: float = 5.0
) -> list[dict[str, object]]:
    parents = list(range(len(spans)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left_index, left_span in enumerate(spans):
        left_rect = left_span["bbox"]
        for right_index in range(left_index):
            right_rect = spans[right_index]["bbox"]
            x_gap = max(
                0.0,
                left_rect.x0 - right_rect.x1,
                right_rect.x0 - left_rect.x1,
            )
            y_gap = max(
                0.0,
                left_rect.y0 - right_rect.y1,
                right_rect.y0 - left_rect.y1,
            )
            x_overlap = min(left_rect.x1, right_rect.x1) - max(
                left_rect.x0, right_rect.x0
            )
            y_overlap = min(left_rect.y1, right_rect.y1) - max(
                left_rect.y0, right_rect.y0
            )
            if (y_overlap > 0 and x_gap <= horizontal_gap) or (
                x_overlap > 0 and y_gap <= vertical_gap
            ):
                union(left_index, right_index)

    grouped: dict[int, list[dict[str, object]]] = {}
    for index, span in enumerate(spans):
        grouped.setdefault(find(index), []).append(span)

    components: list[dict[str, object]] = []
    for group in grouped.values():
        pua_chars = [
            char
            for span in group
            for char in str(span["text"])
            if PUA_MIN <= ord(char) <= PUA_MAX
        ]
        if not pua_chars or not any(char not in NUMERIC_PUA for char in pua_chars):
            continue
        rect = fitz.Rect(group[0]["bbox"])
        for span in group[1:]:
            rect.include_rect(span["bbox"])
        components.append(
            {
                "bbox": [_round(value, 3) for value in tuple(rect)],
                "span_count": len(group),
                "pua_char_count": len(pua_chars),
                "non_numeric_pua_count": sum(char not in NUMERIC_PUA for char in pua_chars),
            }
        )
    return components


def _source_math_inventory(page: fitz.Page) -> dict[str, object]:
    spans = _math_spans(page)
    strict = _math_components(spans, horizontal_gap=16.0)
    sensitive = _math_components(spans, horizontal_gap=4.0)
    fonts = Counter(str(span["font"]) for span in spans)
    text = "".join(str(span["text"]) for span in spans)
    return {
        "math_span_count": len(spans),
        "math_char_count": len(text),
        "pua_char_count": sum(PUA_MIN <= ord(char) <= PUA_MAX for char in text),
        "fraction_rule_pua_count": text.count(FRACTION_RULE_PUA),
        "fonts": dict(fonts.most_common()),
        "strict_candidate_count": len(strict),
        "sensitive_candidate_count": len(sensitive),
        "strict_candidates": strict,
        "sensitive_candidates": sensitive,
    }


def _equation_integrity(hwpx: dict[str, object]) -> dict[str, object]:
    equations = [
        equation
        for page in hwpx["pages"]
        for equation in page["equations"]
    ]
    scripts = [script for equation in equations for script in equation["scripts"]]
    equation_count = len(equations)
    script_count = len(scripts)
    nonempty = sum(bool(script.strip()) for script in scripts)
    placeholder_clean = sum(
        not any(marker in script for marker in SCRIPT_PLACEHOLDERS) for script in scripts
    )
    native_attributes = sum(
        str(equation.get("version") or "").lower().startswith("equation")
        and str(equation.get("font") or "").lower() == "hancomeqn"
        and str(equation.get("numbering_type") or "").upper() == "EQUATION"
        and str(equation.get("base_unit") or "").isdigit()
        and int(str(equation.get("base_unit"))) > 0
        for equation in equations
    )
    parity = 1.0 if equation_count == script_count and equation_count > 0 else 0.0
    no_draw_text = 1.0 if hwpx["forbidden_draw_text_xml_count"] == 0 else 0.0
    metrics = {
        "nonempty_script_ratio": _ratio(nonempty, script_count, empty=0.0),
        "placeholder_clean_ratio": _ratio(placeholder_clean, script_count, empty=0.0),
        "native_attribute_ratio": _ratio(native_attributes, equation_count, empty=0.0),
        "equation_script_parity": parity,
        "no_draw_text": no_draw_text,
    }
    return {
        "equation_count": equation_count,
        "script_count": script_count,
        "nonempty_script_count": nonempty,
        "placeholder_clean_count": placeholder_clean,
        "native_attribute_count": native_attributes,
        "metrics": {key: _round(value) for key, value in metrics.items()},
        "score": _round(_mean(list(metrics.values()))),
    }


def _envelope_score(value: int, lower: int, upper: int) -> float:
    if lower <= value <= upper:
        return 1.0
    if value < lower:
        return _clamp(_ratio(value, lower, empty=0.0))
    return _clamp(_ratio(upper, value, empty=0.0))


def _page_ink_ratio(page: fitz.Page) -> float:
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(0.18, 0.18),
        colorspace=fitz.csGRAY,
        alpha=False,
    )
    samples = pixmap.samples
    if not samples:
        return 0.0
    return sum(value < 245 for value in samples) / len(samples)


def _drawing_inventory(page: fitz.Page) -> dict[str, object]:
    operations: Counter[str] = Counter()
    axis_aligned_segments = 0
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            operation = str(item[0])
            operations[operation] += 1
            if operation == "l":
                start, end = item[1], item[2]
                if abs(start.x - end.x) <= 0.6 or abs(start.y - end.y) <= 0.6:
                    axis_aligned_segments += 1
    return {
        "drawing_count": len(page.get_drawings()),
        "path_operations": dict(operations),
        "axis_aligned_segment_count": axis_aligned_segments,
        "image_object_count": len(page.get_image_info(xrefs=True)),
    }


def _center_divider_count(page: fitz.Page) -> int:
    count = 0
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if item[0] == "l":
                start, end = item[1], item[2]
                length = abs(start.y - end.y)
                x = (start.x + end.x) / 2.0
                if (
                    abs(start.x - end.x) <= 1.0
                    and length >= page.rect.height * 0.45
                    and abs(x - page.rect.width / 2.0) <= page.rect.width * 0.08
                ):
                    count += 1
            elif item[0] == "re":
                rect = fitz.Rect(item[1])
                if (
                    rect.width <= 2.0
                    and rect.height >= page.rect.height * 0.45
                    and abs(rect.x0 + rect.x1 - page.rect.width) / 2.0
                    <= page.rect.width * 0.08
                ):
                    count += 1
    return count


def _group_rectangles(rectangles: list[fitz.Rect], gap: float = 10.0) -> list[list[fitz.Rect]]:
    parents = list(range(len(rectangles)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left_index, left in enumerate(rectangles):
        for right_index in range(left_index):
            right = rectangles[right_index]
            x_gap = max(0.0, left.x0 - right.x1, right.x0 - left.x1)
            y_gap = max(0.0, left.y0 - right.y1, right.y0 - left.y1)
            x_overlap = min(left.x1, right.x1) - max(left.x0, right.x0)
            y_overlap = min(left.y1, right.y1) - max(left.y0, right.y0)
            if (
                left.intersects(right)
                or (x_overlap > 0 and y_gap <= gap)
                or (y_overlap > 0 and x_gap <= gap)
            ):
                union(left_index, right_index)
    grouped: dict[int, list[fitz.Rect]] = {}
    for index, rect in enumerate(rectangles):
        grouped.setdefault(find(index), []).append(rect)
    return list(grouped.values())


def _source_raster_zones(
    page: fitz.Page,
    digest_frequency: Counter[bytes],
    repeated_threshold: int,
) -> dict[str, object]:
    words = page.get_text("words")
    accepted: list[fitz.Rect] = []
    excluded = Counter()
    raw_images = page.get_image_info(xrefs=True)
    for image in raw_images:
        rect = fitz.Rect(image["bbox"])
        digest = image.get("digest")
        aspect = max(
            _ratio(rect.width, rect.height, empty=0.0),
            _ratio(rect.height, rect.width, empty=0.0),
        )
        if digest_frequency[digest] >= repeated_threshold:
            excluded["repeated_asset"] += 1
            continue
        if rect.width * rect.height < 900.0:
            excluded["tiny_asset"] += 1
            continue
        if rect.y1 < 220.0 and aspect > 3.0:
            excluded["header_strip"] += 1
            continue
        overlapping_text_chars = sum(
            len(str(word[4]))
            for word in words
            if fitz.Rect(word[:4]).intersects(rect)
        )
        if overlapping_text_chars >= 20:
            excluded["text_overlay"] += 1
            continue
        accepted.append(rect)

    groups = _group_rectangles(accepted)
    zones: list[dict[str, object]] = []
    for group in groups:
        union = fitz.Rect(group[0])
        for rect in group[1:]:
            union.include_rect(rect)
        zones.append(
            {
                "bbox": [_round(value, 3) for value in tuple(union)],
                "source_image_objects": len(group),
            }
        )
    return {
        "raw_image_object_count": len(raw_images),
        "accepted_image_object_count": len(accepted),
        "zone_count": len(zones),
        "zones": zones,
        "excluded": dict(excluded),
    }


def _required_paths(package_dir: Path) -> dict[str, dict[str, Path]]:
    return {
        subject: {
            "source_pdf": package_dir / "source_pdf" / f"{subject}.pdf",
            "hancom_pdf": package_dir / "hancom_pdf" / f"{subject}.pdf",
            "hwpx": package_dir / "hwpx" / f"{subject}.hwpx",
        }
        for subject in SUBJECTS
    }


def verify(package_dir: Path, min_score: float) -> dict[str, object]:
    package_dir = package_dir.resolve()
    paths = _required_paths(package_dir)
    missing = [
        str(path)
        for subject_paths in paths.values()
        for path in subject_paths.values()
        if not path.is_file()
    ]
    if missing:
        raise FileNotFoundError(f"Missing required artifacts: {missing}")

    subject_reports: dict[str, dict[str, object]] = {}
    physical_mapping_checks: list[float] = []
    duplicate_similarities: list[float] = []
    duplicate_label_parity: list[float] = []
    selection_checks: list[float] = []
    source_agreements: list[float] = []
    source_coherences: list[float] = []
    hwpx_problem_scores: list[float] = []
    actual_problem_scores: list[float] = []
    math_inventory_page_checks: list[float] = []
    math_envelope_scores: list[float] = []
    math_page_coverage_scores: list[float] = []
    math_integrity_scores: list[float] = []
    math_render_checks: list[float] = []
    raster_total = 0
    raster_covered = 0
    raster_misses: list[dict[str, object]] = []
    divider_checks: list[float] = []
    vector_channel_checks: list[float] = []
    hard_gates: dict[str, bool] = {}

    for subject in SUBJECTS:
        hwpx = _read_hwpx(paths[subject]["hwpx"])
        source_doc = fitz.open(paths[subject]["source_pdf"])
        output_doc = fitz.open(paths[subject]["hancom_pdf"])
        try:
            source_count = len(source_doc)
            output_count = len(output_doc)
            hwpx_count = int(hwpx["page_count"])
            if subject in LANGUAGE_SUBJECTS:
                physical_ok = source_count == 2 * output_count and hwpx_count == output_count
            else:
                physical_ok = source_count == output_count == hwpx_count
            physical_mapping_checks.append(1.0 if physical_ok else 0.0)

            all_source_texts = [page.get_text("text") for page in source_doc]
            output_texts = [page.get_text("text") for page in output_doc]
            hwpx_texts = [str(page["text"]) for page in hwpx["pages"]]
            all_source_labels = [_labels_from_lines(page) for page in source_doc]

            variant: dict[str, object] | None = None
            if subject in LANGUAGE_SUBJECTS and source_count >= 2 * output_count:
                variant = _variant_evidence(
                    all_source_texts,
                    output_texts,
                    hwpx_texts,
                    all_source_labels,
                )
                selected_half = int(variant["selected_half"])
                selected_indices = [selected_half * output_count + i for i in range(output_count)]
                duplicate_similarities.append(float(variant["paired_trigram_f1_mean"]))
                duplicate_label_parity.append(float(variant["paired_problem_label_f1_mean"]))
                selection_checks.append(1.0 if variant["selection_consistent"] else 0.0)
                hard_gates[f"{subject}.duplicate_variant"] = (
                    float(variant["paired_trigram_f1_mean"]) >= 0.97
                    and float(variant["paired_trigram_f1_min"]) >= 0.95
                    and bool(variant["selection_consistent"])
                )
            else:
                selected_indices = list(range(min(source_count, output_count)))

            source_inventory = _pdf_label_inventory(source_doc, selected_indices)
            actual_inventory = _pdf_label_inventory(output_doc, list(range(output_count)))
            source_labels_by_page = source_inventory["labels_by_page"]
            actual_labels_by_page = actual_inventory["labels_by_page"]
            hwpx_labels_by_page = [page["problem_labels"] for page in hwpx["pages"]]
            coherence = _label_order_coherence(source_labels_by_page)
            source_agreements.append(float(source_inventory["extractor_agreement"]))
            source_coherences.append(float(coherence["score"]))

            hwpx_comparison = _page_problem_comparison(
                source_labels_by_page, hwpx_labels_by_page
            )
            actual_comparison = _page_problem_comparison(
                source_labels_by_page, actual_labels_by_page
            )
            hwpx_problem_scores.append(float(hwpx_comparison["page_macro_f1"]))
            actual_problem_scores.append(float(actual_comparison["page_macro_f1"]))

            hard_gates[f"{subject}.physical_pages"] = physical_ok
            hard_gates[f"{subject}.source_problem_consensus"] = (
                bool(source_inventory["all_pages_exact_agreement"])
                and float(coherence["score"]) >= 0.99
            )
            hard_gates[f"{subject}.problem_preservation"] = (
                float(hwpx_comparison["minimum_page_f1"]) >= 0.995
                and float(actual_comparison["minimum_page_f1"]) >= 0.995
                and float(actual_inventory["extractor_agreement"]) >= 0.98
            )

            math_report: dict[str, object] | None = None
            if subject in MATH_SUBJECTS:
                inventories = [
                    _source_math_inventory(source_doc[source_index])
                    for source_index in selected_indices
                ]
                native_counts = [len(page["equations"]) for page in hwpx["pages"]]
                strict_counts = [int(page["strict_candidate_count"]) for page in inventories]
                sensitive_counts = [
                    int(page["sensitive_candidate_count"]) for page in inventories
                ]
                lower = sum(strict_counts)
                upper = sum(sensitive_counts)
                native_total = sum(native_counts)
                envelope = _envelope_score(native_total, lower, upper)
                math_envelope_scores.append(envelope)
                page_coverages = [
                    _clamp(_ratio(native, strict, empty=1.0))
                    for native, strict in zip(native_counts, strict_counts)
                ]
                math_page_coverage_scores.extend(page_coverages)
                math_inventory_page_checks.extend(
                    1.0
                    if int(page["math_span_count"]) > 0
                    and int(page["sensitive_candidate_count"]) > 0
                    else 0.0
                    for page in inventories
                )
                integrity = _equation_integrity(hwpx)
                math_integrity_scores.append(float(integrity["score"]))
                render_pages: list[dict[str, object]] = []
                for page_index, page in enumerate(output_doc):
                    drawing_count = len(page.get_drawings())
                    ink_ratio = _page_ink_ratio(page)
                    render_ok = drawing_count > 0 and ink_ratio >= 0.005
                    math_render_checks.append(1.0 if render_ok else 0.0)
                    render_pages.append(
                        {
                            "page": page_index + 1,
                            "drawing_count": drawing_count,
                            "ink_ratio": _round(ink_ratio),
                            "render_ok": render_ok,
                        }
                    )
                math_report = {
                    "source_inventory_method": {
                        "path": "PyMuPDF span font/PUA plus 2D connected components",
                        "strict_horizontal_gap_pt": 16.0,
                        "sensitive_horizontal_gap_pt": 4.0,
                        "vertical_gap_pt": 5.0,
                        "numeric_only_components_excluded": True,
                        "generation_statistics_used": False,
                    },
                    "pages": [
                        {
                            "page": index + 1,
                            **inventory,
                            "native_equation_count": native_counts[index],
                            "strict_candidate_coverage": _round(page_coverages[index]),
                        }
                        for index, inventory in enumerate(inventories)
                    ],
                    "strict_candidate_total": lower,
                    "sensitive_candidate_total": upper,
                    "native_equation_total": native_total,
                    "native_count_inside_independent_envelope": lower
                    <= native_total
                    <= upper,
                    "envelope_score": _round(envelope),
                    "hard_gate_minimum_envelope_score": 0.97,
                    "page_coverage_mean": _round(_mean(page_coverages)),
                    "native_structure_integrity": integrity,
                    "actual_pdf_render_pages": render_pages,
                }
                hard_gates[f"{subject}.math_inventory"] = (
                    all(int(page["math_span_count"]) > 0 for page in inventories)
                    and all(int(page["sensitive_candidate_count"]) > 0 for page in inventories)
                    and envelope >= 0.97
                )
                hard_gates[f"{subject}.native_equation_integrity"] = (
                    float(integrity["score"]) >= 0.99
                    and all(page["render_ok"] for page in render_pages)
                )

            digest_frequency: Counter[bytes] = Counter()
            for source_index in selected_indices:
                digest_frequency.update(
                    image.get("digest")
                    for image in source_doc[source_index].get_image_info(xrefs=True)
                )
            repeated_threshold = max(3, math.ceil(len(selected_indices) * 0.4))
            feature_pages: list[dict[str, object]] = []
            for output_index, source_index in enumerate(selected_indices):
                source_page = source_doc[source_index]
                output_page = output_doc[output_index]
                raster = _source_raster_zones(
                    source_page, digest_frequency, repeated_threshold
                )
                hwpx_page = hwpx["pages"][output_index]
                source_zones = int(raster["zone_count"])
                output_pictures = int(hwpx_page["pictures"])
                covered = min(source_zones, output_pictures)
                missing_zones = max(0, source_zones - output_pictures)
                raster_total += source_zones
                raster_covered += covered
                if missing_zones:
                    raster_misses.append(
                        {
                            "subject": subject,
                            "page": output_index + 1,
                            "missing_zone_count": missing_zones,
                            "source_zones": raster["zones"],
                            "hwpx_picture_count": output_pictures,
                        }
                    )

                source_drawing = _drawing_inventory(source_page)
                output_drawing = _drawing_inventory(output_page)
                source_dividers = _center_divider_count(source_page)
                output_dividers = _center_divider_count(output_page)
                divider_required = source_dividers > 0
                divider_ok = not divider_required or output_dividers > 0
                if divider_required:
                    divider_checks.append(1.0 if divider_ok else 0.0)

                source_has_vector = (
                    int(source_drawing["drawing_count"]) > 0
                    or int(source_drawing["image_object_count"]) > 0
                )
                output_has_render_channel = (
                    int(output_drawing["drawing_count"]) > 0
                    or int(output_drawing["image_object_count"]) > 0
                )
                hwpx_has_structure_channel = (
                    int(hwpx_page["tables"])
                    + int(hwpx_page["pictures"])
                    + len(hwpx_page["equations"])
                    > 0
                )
                vector_channel_ok = (
                    not source_has_vector
                    or (output_has_render_channel and hwpx_has_structure_channel)
                )
                if source_has_vector:
                    vector_channel_checks.append(1.0 if vector_channel_ok else 0.0)

                feature_pages.append(
                    {
                        "page": output_index + 1,
                        "physical_source_page": source_index + 1,
                        "source_raster": raster,
                        "hwpx_picture_count": output_pictures,
                        "raster_zone_covered_count": covered,
                        "raster_zone_missing_count": missing_zones,
                        "source_drawing_inventory": source_drawing,
                        "actual_pdf_drawing_inventory": output_drawing,
                        "source_center_divider_count": source_dividers,
                        "actual_center_divider_count": output_dividers,
                        "center_divider_ok": divider_ok,
                        "hwpx_structure_channels": {
                            "pictures": hwpx_page["pictures"],
                            "tables": hwpx_page["tables"],
                            "native_equations": len(hwpx_page["equations"]),
                            "rectangles": hwpx_page["rectangles"],
                        },
                        "vector_render_channel_ok": vector_channel_ok,
                    }
                )

            subject_reports[subject] = {
                "artifacts": {
                    key: str(value.resolve()) for key, value in paths[subject].items()
                },
                "physical_pages": {
                    "source_pdf": source_count,
                    "hancom_pdf": output_count,
                    "hwpx": hwpx_count,
                    "mapping_ok": physical_ok,
                },
                "variant_detection": variant,
                "selected_source_page_indices_zero_based": selected_indices,
                "source_problem_inventory": source_inventory,
                "source_problem_order_coherence": coherence,
                "hwpx_problem_preservation": hwpx_comparison,
                "actual_pdf_problem_inventory": actual_inventory,
                "actual_pdf_problem_preservation": actual_comparison,
                "math_detection": math_report,
                "source_feature_contract": {
                    "repeated_image_threshold_pages": repeated_threshold,
                    "pages": feature_pages,
                },
            }
        finally:
            source_doc.close()
            output_doc.close()

    physical_score = 8.0 * _mean(physical_mapping_checks)
    duplicate_similarity_score = 6.0 * _mean(duplicate_similarities)
    duplicate_label_score = 2.0 * _mean(duplicate_label_parity)
    selection_score = 4.0 * _mean(selection_checks)
    page_component = (
        physical_score
        + duplicate_similarity_score
        + duplicate_label_score
        + selection_score
    )

    source_agreement_score = 8.0 * _mean(source_agreements)
    source_coherence_score = 4.0 * _mean(source_coherences)
    hwpx_problem_score = 14.0 * _mean(hwpx_problem_scores)
    actual_problem_score = 14.0 * _mean(actual_problem_scores)
    problem_component = (
        source_agreement_score
        + source_coherence_score
        + hwpx_problem_score
        + actual_problem_score
    )

    math_inventory_score = 4.0 * _mean(math_inventory_page_checks)
    math_envelope_score = 8.0 * _mean(math_envelope_scores)
    math_page_score = 4.0 * _mean(math_page_coverage_scores)
    math_integrity_score = 6.0 * _mean(math_integrity_scores)
    math_render_score = 3.0 * _mean(math_render_checks)
    math_component = (
        math_inventory_score
        + math_envelope_score
        + math_page_score
        + math_integrity_score
        + math_render_score
    )

    raster_recall = _ratio(raster_covered, raster_total, empty=1.0)
    divider_coverage = _mean(divider_checks) if divider_checks else 1.0
    vector_channel_coverage = (
        _mean(vector_channel_checks) if vector_channel_checks else 1.0
    )
    raster_score = 10.0 * raster_recall
    divider_score = 2.0 * divider_coverage
    vector_channel_score = 3.0 * vector_channel_coverage
    feature_component = raster_score + divider_score + vector_channel_score

    components = {
        "page_and_variant": {
            "weight": RUBRIC_WEIGHTS["page_and_variant"],
            "score": _round(page_component),
            "raw": {
                "physical_page_mapping": {
                    "weight": 8.0,
                    "normalized": _round(_mean(physical_mapping_checks)),
                    "points": _round(physical_score),
                },
                "duplicate_pair_trigram_f1": {
                    "weight": 6.0,
                    "normalized": _round(_mean(duplicate_similarities)),
                    "points": _round(duplicate_similarity_score),
                },
                "duplicate_pair_problem_label_parity": {
                    "weight": 2.0,
                    "normalized": _round(_mean(duplicate_label_parity)),
                    "points": _round(duplicate_label_score),
                },
                "selected_variant_cross_check": {
                    "weight": 4.0,
                    "normalized": _round(_mean(selection_checks)),
                    "points": _round(selection_score),
                },
            },
        },
        "problem_inventory": {
            "weight": RUBRIC_WEIGHTS["problem_inventory"],
            "score": _round(problem_component),
            "raw": {
                "source_line_word_extractor_agreement": {
                    "weight": 8.0,
                    "normalized": _round(_mean(source_agreements)),
                    "points": _round(source_agreement_score),
                },
                "source_number_run_coherence": {
                    "weight": 4.0,
                    "normalized": _round(_mean(source_coherences)),
                    "points": _round(source_coherence_score),
                },
                "hwpx_page_problem_set_f1": {
                    "weight": 14.0,
                    "normalized": _round(_mean(hwpx_problem_scores)),
                    "points": _round(hwpx_problem_score),
                },
                "actual_pdf_page_problem_set_f1": {
                    "weight": 14.0,
                    "normalized": _round(_mean(actual_problem_scores)),
                    "points": _round(actual_problem_score),
                },
            },
        },
        "native_math": {
            "weight": RUBRIC_WEIGHTS["native_math"],
            "score": _round(math_component),
            "raw": {
                "source_math_signal_page_coverage": {
                    "weight": 4.0,
                    "normalized": _round(_mean(math_inventory_page_checks)),
                    "points": _round(math_inventory_score),
                },
                "native_count_inside_geometry_envelope": {
                    "weight": 8.0,
                    "normalized": _round(_mean(math_envelope_scores)),
                    "points": _round(math_envelope_score),
                },
                "strict_candidate_page_coverage": {
                    "weight": 4.0,
                    "normalized": _round(_mean(math_page_coverage_scores)),
                    "points": _round(math_page_score),
                },
                "native_equation_xml_integrity": {
                    "weight": 6.0,
                    "normalized": _round(_mean(math_integrity_scores)),
                    "points": _round(math_integrity_score),
                },
                "actual_pdf_vector_render_evidence": {
                    "weight": 3.0,
                    "normalized": _round(_mean(math_render_checks)),
                    "points": _round(math_render_score),
                },
            },
        },
        "source_feature_contract": {
            "weight": RUBRIC_WEIGHTS["source_feature_contract"],
            "score": _round(feature_component),
            "raw": {
                "non_text_raster_zone_recall": {
                    "weight": 10.0,
                    "normalized": _round(raster_recall),
                    "points": _round(raster_score),
                    "source_zone_count": raster_total,
                    "covered_zone_count": raster_covered,
                    "misses": raster_misses,
                },
                "center_divider_page_coverage": {
                    "weight": 2.0,
                    "normalized": _round(divider_coverage),
                    "points": _round(divider_score),
                },
                "vector_structure_channel_coverage": {
                    "weight": 3.0,
                    "normalized": _round(vector_channel_coverage),
                    "points": _round(vector_channel_score),
                },
            },
        },
    }

    score = sum(float(component["score"]) for component in components.values())
    hard_gate_failures = [name for name, passed in hard_gates.items() if not passed]
    hard_gates_passed = not hard_gate_failures
    passed = score >= min_score and hard_gates_passed
    warnings: list[str] = []
    if raster_misses:
        warnings.append(
            f"{sum(int(item['missing_zone_count']) for item in raster_misses)} independent "
            "source raster zones have no corresponding HWPX picture on the same page."
        )

    return {
        "schema_version": 1,
        "verifier": "scripts/verify_detection_quality_97.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package_dir": str(package_dir),
        "independence_policy": {
            "generation_report_read": False,
            "generation_statistics_as_ground_truth": False,
            "source_path": "packaged source_pdf read directly with PyMuPDF",
            "output_paths": ["HWPX ZIP/XML", "actual Hancom-exported PDF via PyMuPDF"],
        },
        "rubric": {
            "total_weight": sum(RUBRIC_WEIGHTS.values()),
            "components": components,
        },
        "result": {
            "score": _round(score),
            "min_score": min_score,
            "score_gate_passed": score >= min_score,
            "hard_gates_passed": hard_gates_passed,
            "hard_gate_failures": hard_gate_failures,
            "passed": passed,
            "warnings": warnings,
        },
        "hard_gates": hard_gates,
        "subjects": subject_reports,
        "limitations": [
            "Problem labels are independently observable text tokens; this is not a manual bounding-box ground truth for full problem extents.",
            "Problem preservation uses the line/word extractor consensus set and requires at least 98% extractor agreement, so decimal table rows such as 1.0 are not misclassified as problem 1.",
            "The native-math count is checked against a conservative/sensitive geometry envelope, not against generation_report counts or a hand-authored semantic formula transcript.",
            "Raster zones exclude repeated assets, tiny assets, wide header strips, and image regions overlapping at least 20 extracted text characters.",
            "Tables, boxes, curves, and vector drawings have no semantic object ground truth in this package. Their score is limited to raw source inventories, normalized center-divider coverage, and page-level output representation channels; it does not claim object-level table/box precision or IoU.",
            "An HWPX picture count is page-level preservation evidence. The report lists every unmatched source raster zone instead of silently awarding semantic credit.",
        ],
    }


def _write_report(report: dict[str, object], path: Path | None) -> None:
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if path is None:
        print(payload)
        return
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload + "\n", encoding="utf-8")
    print(f"Report: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--min-score", type=float, default=97.0)
    args = parser.parse_args(argv)

    try:
        report = verify(args.package_dir, args.min_score)
    except Exception as exc:  # Keep CI failure machine-readable.
        report = {
            "schema_version": 1,
            "verifier": "scripts/verify_detection_quality_97.py",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "package_dir": str(args.package_dir.resolve()),
            "result": {
                "score": 0.0,
                "min_score": args.min_score,
                "score_gate_passed": False,
                "hard_gates_passed": False,
                "hard_gate_failures": ["verifier_error"],
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
            },
        }
        _write_report(report, args.report)
        print(f"DETECTION_QUALITY_FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    _write_report(report, args.report)
    result = report["result"]
    status = "PASS" if result["passed"] else "FAIL"
    print(
        f"DETECTION_QUALITY_{status}: score={result['score']:.4f} "
        f"min={result['min_score']:.4f} hard_gates={result['hard_gates_passed']}"
    )
    if result["warnings"]:
        for warning in result["warnings"]:
            print(f"WARNING: {warning}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
