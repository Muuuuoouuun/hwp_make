"""Recover native document content from all PDF body lines, including boxes.

Question recognition is an inventory, not the content source: recognition may
exclude text in a figure frame (notably science <보기> and experiment boxes).
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from bisect import bisect_left, bisect_right
from copy import deepcopy
from collections import Counter
from pathlib import Path
from statistics import median

import fitz
import numpy as np
from PIL import Image

from .pdf_question_markers import QUESTION_START, shared_question_range, document_note_heading


def _figure_inside_table(figure: fitz.Rect, table: fitz.Rect) -> bool:
    area = figure.get_area()
    return area > 0 and (figure & table).get_area() >= area * 0.90


def source_margin_label_indices(page, lines: list[dict]) -> set[int]:
    """Recognize a duplicate header printed vertically in the outer page margin.

    A single narrow line is never enough: at least three stacked Hangul glyphs
    must reproduce text actually present above the body on this same PDF page.
    """
    from . import pdf_layout_writer as w

    def compact(value):
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))

    body_top = w._page_body_top(page)
    header = compact(
        " ".join(
            w._pdf_output_text(w._line_text(line))
            for line in w._iter_text_lines(page)
            if w._item_bbox(line).y1 < body_top
        )
    )
    candidates = []
    for index, line in enumerate(lines):
        text = compact(w._pdf_output_text(w._line_text(line)))
        rect = w._item_bbox(line)
        if (
            re.fullmatch(r"[가-힣]|I{1,3}|IV|V", text)
            and (rect.x1 < page.rect.width * 0.1 or rect.x0 > page.rect.width * 0.9)
            and rect.width < page.rect.width * 0.035
        ):
            candidates.append((index, text, rect))
    groups = []
    for candidate in sorted(
        candidates, key=lambda c: (c[2].x0 < page.rect.width / 2, c[2].y0)
    ):
        _, _, rect = candidate
        if groups:
            previous = groups[-1][-1][2]
            if (
                abs((rect.x0 + rect.x1 - previous.x0 - previous.x1) / 2) < 3
                and 0 < rect.y0 - previous.y0 <= max(rect.height, previous.height) * 2.2
            ):
                groups[-1].append(candidate)
                continue
        groups.append([candidate])
    excluded = set()
    for group in groups:
        label = "".join(record[1] for record in group)
        if len(group) >= 3 and len(re.findall(r"[가-힣]", label)) >= 2 and label in header:
            excluded.update(record[0] for record in group)
    return excluded


def _remove_margin_label_spans(page, lines):
    """Remove a repeated vertical margin label even when PDF joins it to prose."""
    from . import pdf_layout_writer as w
    spans = [span for line in lines for span in line.get("spans", [])]
    isolated = [{"bbox": span["bbox"], "spans": [span]} for span in spans]
    removed = {id(spans[index]) for index in source_margin_label_indices(page, isolated)}
    if not removed:
        return lines
    clean = []
    for line in lines:
        retained = [span for span in line.get("spans", []) if id(span) not in removed]
        if retained:
            clean.append({**line, "spans": retained,
                          "bbox": w._union_rect([fitz.Rect(span["bbox"]) for span in retained])})
    return clean


_PARAGRAPH_START = re.compile(
    r"^(?:\d{1,2}[.)]\s|[①-⑤]|[ㄱ-ㅎ][.)]|\([가-힣A-Za-z0-9]\)|"
    r"[<〈＜]\s*보\s*기\s*[>〉＞]\s*$|보\s*기\s*$|[※○●•])"
)


def _semantic_line_groups(lines: list[dict], figures=()) -> list[list[dict]]:
    """Join printed line wraps; retain labels and actual paragraph boundaries."""
    from . import pdf_layout_writer as w

    def prose_bounds(line):
        spans = [span for span in line.get("spans", [])
                 if not re.fullmatch(r"\s*\[[A-Z]\]\s*", str(span.get("text", "")))]
        return w._union_rect([fitz.Rect(s["bbox"]) for s in spans]) if spans else w._item_bbox(line)

    groups: list[list[dict]] = []
    right_edge = max((prose_bounds(line).x1 for line in lines), default=0)
    for index, line in enumerate(lines):
        text = w._pdf_output_text(w._line_text(line)).strip()
        if not text:
            continue
        if groups and re.fullmatch(r"\[[A-Z]\]", text):
            # A marginal passage label sits between two baselines. Preserve
            # it once, without using its short width/height as prose geometry.
            groups[-1].append(line)
            continue
        if groups:
            prose_lines = [part for part in groups[-1]
                           if not re.fullmatch(r"\[[A-Z]\]", w._pdf_output_text(w._line_text(part)).strip())]
            previous = (prose_lines or groups[-1])[-1]
            previous_text = w._pdf_output_text(w._line_text(previous)).strip()
            old, new = prose_bounds(previous), prose_bounds(line)
            size = w._line_median_font_size(line)
            gap = new.y0 - old.y0
            maximum_gap = max(20.0, size * 1.95)
            if "$" in previous_text or old.height > size * 1.6:
                # A stacked fraction raises the preceding bounding box above
                # its baseline. Measure the remaining whitespace below that
                # tall line so a short sentence tail remains in its paragraph.
                maximum_gap = max(maximum_gap, old.height + size * 1.4)
            fraction_bottoms = [
                span["source_fraction_bbox"][3]
                for span in previous.get("spans", [])
                if span.get("source_fraction_bbox")
            ]
            if fraction_bottoms:
                maximum_gap = max(
                    maximum_gap, max(fraction_bottoms) - old.y0 + size * 1.4
                )
            # A sentence ending at the physical right margin is still part of
            # the same paragraph. Short final lines and a fresh indentation
            # carry paragraph evidence; punctuation by itself does not.
            sentence_end = re.search(r"[.!?。][\]\)）]?\s*$", previous_text)
            short_last_line = old.x1 < right_edge - size * 2.5
            continuation_left = min(prose_bounds(part).x0 for part in prose_lines[1:]) if len(prose_lines) > 1 else old.x0
            new_indent = new.x0 - continuation_left > size * 0.7
            # A one-line salutation can precede the indented first line of a
            # new paragraph. A hanging paragraph, however, keeps every later
            # line indented. Require the next line's actual return to the
            # original rail before splitting such a short opening line.
            following = next((prose_bounds(part) for part in lines[index + 1:]
                              if w._pdf_output_text(w._line_text(part)).strip()), None)
            new_first_indent = bool(short_last_line and following is not None
                                    and abs(following.x0 - old.x0) < size * .3
                                    and 0 < following.y0 - new.y0 <= maximum_gap)
            if len(groups[-1]) == 1 and (QUESTION_START.match(previous_text) or _PARAGRAPH_START.match(previous_text)):
                new_indent = False  # hanging question/choice label
            returns_below_figure = any(
                old.x0 >= picture.x1 - .1 and new.x0 < old.x0
                and min(old.y1, picture.y1) > max(old.y0, picture.y0)
                and new.y0 >= picture.y1 - .1 and new.x0 <= picture.x0 + size
                and new.x1 > picture.x1 + size
                for picture in figures
            )
            continuation = (
                not _PARAGRAPH_START.match(text)
                and not QUESTION_START.match(text)
                and not (sentence_end and (short_last_line or new_indent))
                and not (new_indent and (new_first_indent or len(groups[-1]) > 1))
                and not re.fullmatch(r"[<〈＜]?\s*보\s*기\s*[>〉＞]?", previous_text)
                and 0 < gap <= maximum_gap
                and (abs(new.x0 - old.x0) <= max(32.0, size * 3) or returns_below_figure)
                and len(re.sub(r"\s", "", previous_text)) >= 8
            )
            if continuation:
                groups[-1].append(line)
                continue
        groups.append([line])
    return groups


def _semantic_flow_blocks(blocks: list[dict]) -> list[dict]:
    """Keep prose in ordinary paragraphs, including question-number first lines."""
    from . import pdf_layout_writer as w

    result, pending = [], []
    source = None
    figures = [w._item_bbox(block["image"]) for block in blocks if block["type"] == "image"]

    def flush():
        if pending:
            for group in _semantic_line_groups(pending, figures):
                result.append({**source, "type": "paragraph", "lines": group})
            pending.clear()

    for block in blocks:
        if block["type"] in {"line", "paragraph"}:
            if not pending:
                source = block
            pending.extend(block.get("lines") or [block["line"]])
        else:
            if block["type"] == "image" and pending:
                picture = w._item_bbox(block["image"])
                split = len(pending)
                while split:
                    text = w._item_bbox(pending[split - 1])
                    if (min(text.y1, picture.y1) <= max(text.y0, picture.y0)
                        or not (text.x1 <= picture.x0 + .1
                                or text.x0 >= picture.x1 - .1)):
                        break
                    split -= 1
                if split < len(pending):
                    # The top of a side illustration can lie between the first
                    # baseline and the second. Keep the paragraph pending
                    # across that image instead of splitting its first line.
                    beside = pending[split:]
                    del pending[split:]
                    flush()
                    result.append(block)
                    pending.extend(beside)
                    continue
            flush()
            result.append(block)
    flush()
    return result


def _source_typography(lines: list[dict], block: dict) -> dict:
    """Record measured PDF metrics, without turning coordinates into text boxes."""
    from . import pdf_layout_writer as w

    spans = [span for line in lines for span in line.get("spans", [])]
    prose = [s for s in spans if not w.is_hancom_eq_font(str(s.get("font", "")))]
    prose = prose or spans
    if not prose:
        return {}
    fonts, sizes = Counter(), Counter()
    tracking, ratios = [], []
    for span in prose:
        count = len(str(span.get("text", "")).strip())
        fonts[str(span.get("font", ""))] += count
        size = float(span.get("size", 10))
        sizes[round(size, 3)] += count
        for left, right in zip(span.get("chars", []), span.get("chars", [])[1:]):
            if not (
                re.fullmatch(r"[가-힣]", left.get("c", ""))
                and re.fullmatch(r"[가-힣]", right.get("c", ""))
            ):
                continue
            advance = right["origin"][0] - left["origin"][0]
            width = left["bbox"][2] - left["bbox"][0]
            if 0.5 * size < advance < 1.5 * size:
                tracking.append((advance - width) / size * 100)
                ratios.append(width / size * 100)
    font = fonts.most_common(1)[0][0]
    size = sizes.most_common(1)[0][0]
    records = []
    for line in lines:
        measured = [s for s in line.get("spans", [])
                    if "origin" in s and str(s.get("text", "")).strip()]
        # An equation's parentheses, superscripts and Latin variables can use
        # different source baselines. They must not move the ordinary prose
        # line merely by contributing more spans than the body font does.
        baseline_spans = ([s for s in measured if s.get("font") == font]
                          or [s for s in measured if not w.is_hancom_eq_font(str(s.get("font", "")))]
                          or measured)
        baselines = [float(s["origin"][1]) for s in baseline_spans]
        records.append(
            {
                "text": w._pdf_output_text(w._line_text(line)).strip(),
                "bbox_pt": list(w._item_bbox(line)),
                "baseline_pt": median(baselines)
                if baselines
                else w._item_bbox(line).y1,
                "font_size_pt": w._line_median_font_size(line),
                "spans": deepcopy(line.get("spans", [])),
            }
        )
    gaps = [
        b["baseline_pt"] - a["baseline_pt"]
        for a, b in zip(records, records[1:])
        if size * 0.9 < b["baseline_pt"] - a["baseline_pt"] < size * 2.1
    ]
    left = float(block.get("column_left_pt") or min(r["bbox_pt"][0] for r in records))
    right = float(block.get("column_right_pt") or max(r["bbox_pt"][2] for r in records))
    region = block.get("rect")
    if region is not None:
        left, right = region.x0, region.x1
    alignment = "LEFT"
    if len(records) > 1:
        body_rights = [r["bbox_pt"][2] for r in records[:-1]]
        if body_rights and max(body_rights) - min(body_rights) < size * 0.7:
            alignment = "JUSTIFY"
    elif records:
        x0, _, x1, _ = records[0]["bbox_pt"]
        if x0 - left > size and abs((x0 + x1 - left - right) / 2) < size * 0.5:
            alignment = "CENTER"
        elif x0 - left > size * 3 and abs(right - x1) < size * 0.5:
            alignment = "RIGHT"
    return {
        "font_name": font,
        "font_name_recovered": w._recover_pdf_font_name(font),
        "font_size_pt": size,
        "line_spacing_pt": round(median(gaps), 3) if gaps else None,
        "alignment": alignment,
        "source_column_width_pt": round(right - left, 3),
        "source_bbox_pt": list(w._union_rect([w._item_bbox(line) for line in lines])),
        "letter_spacing_percent": round(median(tracking), 2) if tracking else None,
        "font_width_percent": round(median(ratios), 2) if ratios else None,
        "letter_spacing_sample_count": len(tracking),
        "lines": records,
    }


def _group_native_image_rows(items: list[dict]) -> list[dict]:
    """Retain adjacent source figures on one flowing paragraph, without crops."""
    grouped: list[dict] = []
    for item in items:
        layout = item.get("layout") or {}
        bounds = layout.get("source_bbox_pt")
        pure_image = (
            bool(item.get("image_paths"))
            and not item.get("stem")
            and not item.get("tables")
        )
        if pure_image and bounds:
            layout["source_image_bounds"] = [list(bounds)]
        if grouped and pure_image and bounds:
            previous = grouped[-1]
            old_layout = previous.get("layout") or {}
            old_bounds = old_layout.get("source_image_bounds") or []
            column_left = float(layout.get("column_left_pt") or 0)
            column_right = float(layout.get("column_right_pt") or 0)
            width = column_right - column_left
            regions = [fitz.Rect(bound) for bound in old_bounds] + [fitz.Rect(bounds)]
            regions.sort(key=lambda region: region.x0)
            common_top = max(region.y0 for region in regions)
            common_bottom = min(region.y1 for region in regions)
            aligned = (
                len(regions) >= 2
                and common_bottom - common_top
                >= min(region.height for region in regions) * 0.8
                and all(
                    left.x1 <= right.x0 + 0.1
                    for left, right in zip(regions, regions[1:])
                )
                and regions[-1].x1 - regions[0].x0 <= width + 0.1
            )
            if (
                old_bounds
                and not previous.get("stem")
                and not previous.get("tables")
                and item.get("source_page") == previous.get("source_page")
                and layout.get("source_column") == old_layout.get("source_column")
                and width > 0
                and aligned
            ):
                pairs = list(zip(old_bounds, previous["image_paths"])) + [
                    (bounds, item["image_paths"][0])
                ]
                pairs.sort(key=lambda pair: pair[0][0])
                previous["image_paths"] = [pair[1] for pair in pairs]
                old_layout["source_image_bounds"] = [list(pair[0]) for pair in pairs]
                old_layout["image_width_ratios"] = [
                    region.width / width for region in regions
                ]
                old_layout["image_horizontal_gaps"] = [
                    max(0.0, right.x0 - left.x1) / width
                    for left, right in zip(regions, regions[1:])
                ]
                old_layout["image_leading_ratio"] = (
                    max(0.0, regions[0].x0 - column_left) / width
                )
                union = fitz.Rect(regions[0])
                for region in regions[1:]:
                    union.include_rect(region)
                old_layout["source_bbox_pt"] = list(union)
                old_layout["image_width_ratio"] = union.width / width
                continue
        grouped.append(item)
    return grouped


def _anchor_question_figures(items: list[dict]) -> list[dict]:
    """Read a question before its side figure/table when their top edges differ.

    The PDF's drawing top can precede the adjacent first text baseline by a
    point. Only overlapping, horizontally separate content is reordered; a
    figure genuinely above a following question retains its original position.
    """
    result = []
    index = 0
    while index < len(items):
        item = items[index]
        layout = item.get("layout") or {}
        bounds = layout.get("source_bbox_pt") or (
            layout.get("source_typography") or {}
        ).get("source_bbox_pt")
        is_illustration = not item.get("stem") and (
            bool(item.get("image_paths")) != bool(item.get("tables"))
        )
        if is_illustration and bounds and index + 1 < len(items):
            following = items[index + 1]
            if QUESTION_START.match(following.get("stem", "")):
                picture = fitz.Rect(bounds)
                end = index + 1
                while end < len(items):
                    text = items[end]
                    text_layout = text.get("layout") or {}
                    text_bounds = (text_layout.get("source_typography") or {}).get(
                        "source_bbox_pt"
                    )
                    if (
                        not text.get("stem")
                        or text.get("image_paths")
                        or text.get("tables")
                        or text.get("source_page") != item.get("source_page")
                        or text_layout.get("source_column")
                        != layout.get("source_column")
                        or not text_bounds
                        or (
                            end > index + 1
                            and QUESTION_START.match(text["stem"])
                        )
                    ):
                        break
                    line_bounds = [
                        line["bbox_pt"]
                        for line in (text_layout.get("source_typography") or {}).get(
                            "lines", []
                        )
                    ]
                    paragraphs = [
                        fitz.Rect(bound) for bound in (line_bounds or [text_bounds])
                    ]
                    overlapping = [
                        paragraph
                        for paragraph in paragraphs
                        if min(picture.y1, paragraph.y1) > max(picture.y0, paragraph.y0)
                    ]
                    if not overlapping or not all(
                        picture.x1 <= paragraph.x0 + 0.1
                        or paragraph.x1 <= picture.x0 + 0.1
                        for paragraph in overlapping
                    ):
                        break
                    end += 1
                if end > index + 1:
                    result.extend(items[index + 1 : end])
                    result.append(item)
                    index = end
                    continue
        result.append(item)
        index += 1
    return result


def annotate_question_groups(items: list[dict], recognized_problems=None) -> dict:
    """Attach semantic question boundaries without flattening their native items.

    A group survives column and page changes. Shared passages and closing
    document notes have explicit outside groups instead of being absorbed by
    the preceding question. Repeated numbering creates a new exam variant.
    """
    expected = None
    if recognized_problems is not None:
        expected = Counter(
            (int(problem.page_number), int(problem.number))
            for problem in recognized_problems
        )
    observed = Counter()
    variant = 1
    previous_number = None
    active_group = None
    active_number = None
    active_kind = "document_note"
    outside_count = 0
    question_groups = []
    unmatched_numbered = []
    for item in items:
        layout = item.setdefault("layout", {})
        stem = str(item.get("stem") or "").strip()
        page = int(item.get("source_page") or 0)
        marker = QUESTION_START.match(stem)
        number = int(marker.group(1)) if marker else None
        key = (page, number)
        accepted = marker is not None and (
            expected is None or observed[key] < expected[key]
        )
        if marker and not accepted:
            unmatched_numbered.append(
                {"page": page, "number": number, "text": stem[:100]}
            )
        text = "\n".join(
            [stem]
            + [
                str(cell)
                for table in item.get("tables", [])
                for row in table
                for cell in row
            ]
        )
        first_line = next(
            (line.strip() for line in text.splitlines() if line.strip()), ""
        )
        shared = shared_question_range(first_line) is not None
        note = document_note_heading(first_line)
        start = False
        if accepted:
            if previous_number is not None and number <= previous_number:
                variant += 1
            active_group = f"v{variant}:q{number:02d}"
            active_number = number
            active_kind = "question"
            previous_number = number
            observed[key] += 1
            question_groups.append(
                {"id": active_group, "number": number, "variant": variant, "page": page}
            )
            start = True
        elif shared or note or active_group is None:
            outside_count += 1
            active_group = f"out:v{variant}:{outside_count}"
            active_number = None
            active_kind = "shared_passage" if shared else "document_note"
            start = True
        layout.update(
            {
                "question_group": active_group,
                "question_number": active_number,
                "question_variant": variant,
                "question_group_kind": active_kind,
                "question_group_start": start,
            }
        )
    missing = expected - observed if expected is not None else Counter()
    return {
        "question_count": len(question_groups),
        "variant_count": variant if question_groups else 0,
        "outside_group_count": outside_count,
        "inventory_checked": expected is not None,
        "inventory_matches": not missing if expected is not None else None,
        "expected_question_count": sum(expected.values())
        if expected is not None
        else None,
        "matched_question_count": sum((observed & expected).values())
        if expected is not None
        else None,
        "missing_question_markers": [
            {"page": page, "number": number, "count": count}
            for (page, number), count in sorted(missing.items())
        ],
        "unmatched_numbered_paragraphs": unmatched_numbered,
        "groups": question_groups,
    }


def _native_images_and_frames(page, lines, cell_regions=(), backgrounds=None):
    """Separate tiled decorative backgrounds from the figures placed inside them.

    Only adjoining tiles may merge. Containment is not evidence that a figure
    and the surrounding worksheet frame are one picture. A frame is replaced
    by a native box only when the original raster has flat pixels behind prose.
    """
    from . import pdf_layout_writer as w

    groups = []
    source_images = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 1 or not block.get("image"):
            continue
        rect = fitz.Rect(block["bbox"])
        if rect.width < 12 or rect.height < 8:
            continue
        data = block["image"]
        transform = fitz.Matrix(block["transform"])
        # bbox can be clipped while image bytes still contain the full bitmap.
        # Apply that crop before testing the pixels beneath native PDF text.
        if (
            abs(transform.b) < 0.001
            and abs(transform.c) < 0.001
            and transform.a > 0
            and transform.d > 0
        ):
            visible = rect * ~transform
            with Image.open(io.BytesIO(data)) as original:
                crop = original.crop(
                    tuple(
                        round(v * (original.width if n % 2 == 0 else original.height))
                        for n, v in enumerate(visible)
                    )
                )
                crop = crop.resize(
                    (max(1, round(rect.width * 2)), max(1, round(rect.height * 2)))
                )
                buffer = io.BytesIO()
                crop.save(buffer, format="PNG")
                data = buffer.getvalue()
        source_images.append(
            {"type": "image", "bbox": rect, "image": data, "ext": "png", "source_image_number": block["number"]}
        )
    for item in source_images:
        rect = w._item_bbox(item)
        def cell_owner(bounds):
            return tuple(index for index, cell in enumerate(cell_regions)
                         if (bounds & cell).get_area() >= bounds.get_area() * 0.90)
        touching = [
            group
            for group in groups
            if any(
                w._image_rects_related(rect, w._item_bbox(other))
                and cell_owner(rect) == cell_owner(w._item_bbox(other))
                and (rect & w._item_bbox(other)).get_area()
                <= min(rect.get_area(), w._item_bbox(other).get_area()) * 0.01
                for other in group
            )
        ]
        combined = [item]
        for group in touching:
            combined.extend(group)
            groups.remove(group)
        groups.append(combined)
    pictures, frames = [], []
    for group in groups:
        for item in w._merge_flow_images(group):
            region = w._item_bbox(item)
            prose = [
                line
                for line in lines
                if (
                    len(re.findall(r"[가-힣]", w._line_text(line))) >= 12
                    or len(re.findall(r"[a-zA-Z]", w._line_text(line))) >= 24
                )
                and region.contains(w._item_bbox(line))
            ]
            flat = False
            if prose:
                with Image.open(io.BytesIO(item["image"])) as source:
                    pixels = np.asarray(source.convert("L"), dtype=np.int16)
                sy, sx = pixels.shape[0] / region.height, pixels.shape[1] / region.width
                edge_counts = []
                for line in prose:
                    bounds = w._item_bbox(line)
                    x0, x1 = [
                        round((x - region.x0) * sx) for x in (bounds.x0, bounds.x1)
                    ]
                    y0, y1 = [
                        round((y - region.y0) * sy) for y in (bounds.y0, bounds.y1)
                    ]
                    crop = pixels[max(0, y0) : y1, max(0, x0) : x1]
                    if min(crop.shape, default=0) > 1:
                        edge_counts.append(
                            max(
                                float(np.mean(np.abs(np.diff(crop, axis=0)) > 24)),
                                float(np.mean(np.abs(np.diff(crop, axis=1)) > 24)),
                            )
                        )
                flat = bool(edge_counts) and max(edge_counts) < 0.015
            if flat:
                frames.append(region)
                if backgrounds is not None:
                    backgrounds.append({"region": region, "numbers": [source["source_image_number"] for source in group]})
                # Some frames also contain an actual illustration (e.g. a
                # teacher below a speech bubble). Retain detailed areas outside
                # the prose instead of dropping the complete bitmap.
                native_lines = [line for line in lines if region.contains(w._item_bbox(line))]
                text_bounds = w._union_rect([w._item_bbox(line) for line in native_lines or prose])
                for remainder in (
                    fitz.Rect(region.x0, region.y0, region.x1, text_bounds.y0 - 2),
                    fitz.Rect(region.x0, text_bounds.y1 + 2, region.x1, region.y1),
                ):
                    if remainder.height < 12:
                        continue
                    start = max(0, round((remainder.y0 - region.y0 + 3) * sy))
                    end = min(
                        pixels.shape[0], round((remainder.y1 - region.y0 - 3) * sy)
                    )
                    interior = pixels[
                        start:end, max(1, round(3 * sx)) : -max(1, round(3 * sx))
                    ]
                    if (
                        min(interior.shape, default=0) > 1
                        and max(
                            np.mean(np.abs(np.diff(interior, axis=0)) > 24),
                            np.mean(np.abs(np.diff(interior, axis=1)) > 24),
                        )
                        > 0.015
                    ):
                        pictures.append({**item, "bbox": remainder})
            else:
                pictures.append(item)
    # A retained illustration clip is rendered from the PDF and therefore
    # already includes any embedded figure completely inside that clip.
    pictures = [
        picture
        for picture in pictures
        if not any(
            other is not picture
            and w._item_bbox(other).get_area() > w._item_bbox(picture).get_area()
            and w._item_bbox(other).contains(w._item_bbox(picture))
            for other in pictures
        )
    ]
    return pictures, frames


def recover_stacked_fractions(
    lines: list[dict], drawings: list[dict], table_regions: list[fitz.Rect],
    *, source_page=None,
) -> tuple[list[dict], list[str]]:
    """Recover bounded fraction rules from glyph geometry, including word ratios."""
    from . import pdf_layout_writer as w

    chars = []
    bars = []
    for li, line in enumerate(lines):
        for si, span in enumerate(line.get("spans", [])):
            for ci, char in enumerate(span.get("chars", [])):
                rect = fitz.Rect(char["bbox"])
                record = {
                    "key": (li, si, ci),
                    "text": w._pdf_output_text(char.get("c", "")),
                    "rect": rect,
                    "size": float(span.get("size", 10)),
                    "cx": (rect.x0 + rect.x1) / 2,
                    "cy": (rect.y0 + rect.y1) / 2,
                }
                chars.append(record)
                if char.get("c") == w._HANCOM_FRACTION_RULE_CHAR:
                    rule_y = rect.y0 + rect.height * 0.4
                    if source_page is not None and rect.width >= 4:
                        # A stretched equation-font rule has a tall glyph box;
                        # its box midpoint is not the position of the visible
                        # fraction line. Measure only a continuous horizontal
                        # ink run spanning nearly the whole original glyph.
                        pix = source_page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect, alpha=False)
                        pixels = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                        ink = pixels[:, :, :3].mean(axis=2) < 200
                        candidates = []
                        for row_index, row in enumerate(ink):
                            edges = np.diff(np.r_[False, row, False].astype(np.int8))
                            lengths = np.flatnonzero(edges == -1)-np.flatnonzero(edges == 1)
                            if len(lengths) and lengths.max() >= pix.width*0.85:
                                candidates.append(row_index)
                        if candidates and candidates[-1]-candidates[0] <= max(3, rect.height*0.16):
                            rule_y = (pix.y + float(median(candidates)) + 0.5)/2
                    bars.append(
                        (rect.x0, rect.x1, rule_y, record["key"])
                    )
    for drawing in drawings:
        for part in drawing.get("items", []):
            if part[0] == "l" and abs(part[1].y - part[2].y) < 0.5:
                x0, x1 = sorted((part[1].x, part[2].x))
                if 3 < x1 - x0 < 300:
                    bars.append((x0, x1, part[1].y, None))
    consumed = set()
    replacements: dict[int, list[dict]] = {}
    equations = []
    visible_chars = sorted(
        (c for c in chars if c["text"].strip()), key=lambda c: c["cy"]
    )
    centers_y = [c["cy"] for c in visible_chars]
    reach = max((c["size"] for c in visible_chars), default=0) * 1.05
    operand_size = median([c["size"] for c in visible_chars]) if visible_chars else 0
    roots = [c for c in chars if c["text"] == "√"]
    for x0, x1, y, bar_key in bars:
        if bar_key is not None and any(
            c["text"] == "√"
            and abs(c["rect"].x1 - x0) < 2
            and abs((c["rect"].y0 + c["rect"].y1) / 2 - y) < c["size"]
            for c in roots
        ):
            continue  # The equation font also uses this glyph as a root vinculum.
        if any(
            region.contains(fitz.Point((x0 + x1) / 2, y)) for region in table_regions
        ):
            continue
        nearby = [
            c
            for c in visible_chars[
                bisect_left(centers_y, y - reach) : bisect_right(centers_y, y + reach)
            ]
            if c["key"] not in consumed
            and x0 - 0.8 <= c["cx"] <= x1 + 0.8
            and 1.5 < abs(c["cy"] - y) < max(c["size"], operand_size) * 1.05
        ]
        above = [
            c
            for c in nearby
            if 0 < y - (c["rect"].y0 + c["rect"].y1) / 2 < max(c["size"], operand_size) * 0.9
        ]
        below = [c for c in nearby if (c["rect"].y0 + c["rect"].y1) / 2 > y]
        if not above or not below:
            continue

        def include_operand_scripts(group):
            # A numerator's superscript (or denominator's subscript) can lie
            # beyond the fraction's normal baseline band. Include it only if
            # the original glyph baseline, size and horizontal attachment
            # establish a script on a base already selected for this operand.
            chosen = {c["key"] for c in group}
            additions = []
            for li, si in {(c["key"][0], c["key"][1]) for c in group}:
                base = lines[li]["spans"][si]
                base_size = float(base.get("size", 0))
                base_origin = base.get("origin")
                base_text = w._pdf_output_text(base.get("text", "")).rstrip()
                glyphs = base.get("chars", [])
                if (not base_size or not base_origin or not glyphs
                        or (li, si, len(glyphs)-1) not in chosen
                        or not base_text or not (base_text[-1].isalnum() or base_text[-1] == ")")
                        or not w.is_hancom_eq_font(str(base.get("font", "")))):
                    continue
                base_bounds = fitz.Rect(base["bbox"])
                for sli, source_line in enumerate(lines):
                    for ssi, script in enumerate(source_line.get("spans", [])):
                        value = w._pdf_output_text(script.get("text", "")).strip()
                        origin = script.get("origin")
                        script_size = float(script.get("size", 0))
                        if (not origin or not 0 < script_size <= base_size*0.82
                                or not re.fullmatch(r"[+−-]|[+−-]?[A-Za-z0-9]{1,4}(?:[+−-][A-Za-z0-9]{1,4})?[+−-]?", value)
                                or not w.is_hancom_eq_font(str(script.get("font", "")))):
                            continue
                        bounds = fitz.Rect(script["bbox"])
                        dx = bounds.x0-base_bounds.x1
                        dy = float(base_origin[1])-float(origin[1])
                        if not (-base_size*0.45 <= dx <= base_size*0.55
                                and base_size*0.19 <= abs(dy) <= base_size*0.8):
                            continue
                        if (bounds.y0+bounds.y1-2*y)*(base_bounds.y0+base_bounds.y1-2*y) <= 0:
                            continue
                        additions.extend(c for c in chars
                                         if c["key"][:2] == (sli, ssi)
                                         and c["key"] not in consumed
                                         and c["key"] not in chosen
                                         and x0-0.8 <= c["cx"] <= x1+0.8)
            return group + [c for index, c in enumerate(additions)
                            if c["key"] not in {earlier["key"] for earlier in additions[:index]}]

        above, below = include_operand_scripts(above), include_operand_scripts(below)
        outside = [
            c
            for c in visible_chars[
                bisect_left(centers_y, y - 3.5) : bisect_right(centers_y, y + 3.5)
            ]
            if c["key"] not in consumed
            and c["text"].strip()
            and (0 <= x0 - c["rect"].x1 < 24 or 0 <= c["rect"].x0 - x1 < 24)
            and abs((c["rect"].y0 + c["rect"].y1) / 2 - y) < 3.5
        ]
        if bar_key is None and not outside:
            continue  # A grid edge or underline is not a fraction.

        def value(group):
            ordered = sorted(group, key=lambda c: c["rect"].x0)
            text = "".join(c["text"] for c in ordered)
            selected = {}
            for character in ordered:
                li, si, ci = character["key"]
                selected.setdefault((li, si), []).append(ci)
            operand_spans = []
            for (li, si), indices in selected.items():
                original = lines[li]["spans"][si]
                glyphs = [original["chars"][index] for index in sorted(indices)]
                operand_spans.append({**original, "chars": glyphs,
                                      "text": "".join(glyph["c"] for glyph in glyphs),
                                      "bbox": tuple(w._union_rect([fitz.Rect(glyph["bbox"]) for glyph in glyphs]))})
            recovered = recover_native_scripts([{"spans": sorted(operand_spans, key=lambda s: s["bbox"][0])}])
            if any(span.get("source_script_spans") for line in recovered for span in line["spans"]):
                return "".join(w._pdf_output_text(span["text"]).strip("$")
                               for line in recovered for span in line["spans"])
            if re.fullmatch(r"[A-Za-z]{1,4}", text):
                bounds = w._union_rect([c["rect"] for c in ordered])
                for rule in chars:
                    if rule["key"] == bar_key or rule["text"]:
                        continue
                    rect = rule["rect"]
                    if (
                        rect.x0 - 1 <= bounds.x0
                        and bounds.x1 <= rect.x1 + 1
                        and 0
                        < (bounds.y0 + bounds.y1 - rect.y0 - rect.y1) / 2
                        < ordered[0]["size"] * 0.65
                    ):
                        return r"\overline{" + text + "}"
            return text

        numerator, denominator = value(above), value(below)
        if any(
            marker in numerator + denominator
            for marker in ("ㄱ.", "ㄴ.", "ㄷ.", "①", "②", "③")
        ):
            continue
        if bar_key is not None:
            host = bar_key[0]
        else:
            host = min(outside, key=lambda c: abs(c["rect"].x1 - x0))["key"][0]
        expression = r"\frac{" + numerator + "}{" + denominator + "}"
        equations.append(expression)
        consumed.update(c["key"] for c in above + below)
        if bar_key is not None:
            consumed.add(bar_key)
        size = above[0]["size"]
        replacements.setdefault(host, []).append(
            {
                "text": "$" + expression + "$",
                "font": "HyhwpEQ",
                "size": size,
                "flags": 0,
                "bbox": (x0, y - size / 2, x1, y + size / 2),
                "source_fraction_bbox": tuple(
                    w._union_rect([c["rect"] for c in above + below])
                ),
            }
        )
    result = []
    for li, line in enumerate(lines):
        spans = []
        for si, span in enumerate(line.get("spans", [])):
            retained = [
                c
                for ci, c in enumerate(span.get("chars", []))
                if (li, si, ci) not in consumed
            ]
            if retained:
                copy = deepcopy(span)
                copy["chars"] = retained
                copy["text"] = "".join(c["c"] for c in retained)
                if retained[0].get("origin"):
                    copy["origin"] = retained[0]["origin"]
                copy["bbox"] = tuple(
                    w._union_rect([fitz.Rect(c["bbox"]) for c in retained])
                )
                spans.append(copy)
            elif not span.get("chars"):
                spans.append(deepcopy(span))
        spans.extend(replacements.get(li, []))
        if spans:
            spans.sort(key=lambda s: s["bbox"][0])
            result.append(
                {
                    **line,
                    "spans": spans,
                    "bbox": w._union_rect([fitz.Rect(s["bbox"]) for s in spans]),
                }
            )
    return result, equations


def recover_native_scripts(lines: list[dict]) -> list[dict]:
    """Attach small mathematical script spans using their actual PDF baselines.

    Keep the base and script geometry together before semantic line grouping;
    otherwise table extraction can move an exponent onto its own physical line.
    This deliberately leaves fraction operands and equal-sized digits alone.
    """
    from . import pdf_layout_writer as w

    result = deepcopy(lines)
    spans = [
        (li, span) for li, line in enumerate(result) for span in line.get("spans", [])
    ]
    consumed = set()
    for _, script in spans:
        value = w._pdf_output_text(script.get("text", "")).strip()
        if not re.fullmatch(r"[+−-]|[+−-]?[A-Za-z0-9]{1,4}(?:[+−-][A-Za-z0-9]{1,4})?[+−-]?", value):
            continue
        if not w.is_hancom_eq_font(str(script.get("font", ""))):
            continue
        size = float(script.get("size") or 0)
        origin = script.get("origin")
        if not size or not origin:
            continue
        script_box = fitz.Rect(script["bbox"])
        options = []
        for base_line, base in spans:
            if base is script or id(base) in consumed:
                continue
            base_size = float(base.get("size") or 0)
            if not base_size or size > base_size * 0.82:
                continue
            if not w.is_hancom_eq_font(str(base.get("font", ""))):
                continue
            base_origin = base.get("origin")
            text = w._pdf_output_text(base.get("text", "")).strip().strip("$")
            anchor_text = re.sub(r"[_^]\{[^{}]*\}", "", text).replace("{}", "")
            if (
                not base_origin
                or not text
                or not anchor_text
                or not (anchor_text[-1].isalnum() or anchor_text[-1] == ")")
            ):
                continue
            bbox = fitz.Rect(base.get("source_script_base_bbox") or base["bbox"])
            dx = script_box.x0 - bbox.x1
            dy = float(base_origin[1]) - float(origin[1])
            if not (base_size * 0.19 <= abs(dy) <= base_size * 0.8):
                continue
            if -base_size * 0.45 <= dx <= base_size * 0.55:
                options.append((abs(dx), abs(dy), base_line, base, text, "right"))
            left_gap = bbox.x0 - script_box.x1
            if (re.fullmatch(r"[A-Z][a-z]?", anchor_text)
                    and -base_size * 0.1 <= left_gap <= base_size * 0.55):
                options.append((abs(left_gap), abs(dy), base_line, base, text, "left"))
        if not options:
            continue
        # A chemical index between adjacent elements (H₂O) belongs to its
        # preceding base when that attachment is geometrically valid. A
        # prescript is considered only when no preceding base can own it.
        _, _, _, base, text, side = min(options, key=lambda entry: (entry[5] == "left", *entry[:2]))
        sign = "^" if float(base["origin"][1]) > float(origin[1]) else "_"
        attachment = sign + "{" + value.replace("−", "-") + "}"
        if side == "left":
            text = "{}" + attachment + (text[2:] if text.startswith("{}") else text)
        else:
            text += attachment
        base["text"] = "$" + text + "$"
        base.setdefault("source_script_base_bbox", tuple(base["bbox"]))
        base.setdefault("source_script_spans", []).append(deepcopy(script))
        # Use the baseline band's y range for line grouping, with the actual
        # combined horizontal extent. Source glyph coordinates stay untouched.
        bounds = fitz.Rect(base["bbox"])
        if side == "left":
            bounds.x0 = min(bounds.x0, script_box.x0)
        bounds.x1 = max(bounds.x1, script_box.x1)
        base["bbox"] = tuple(bounds)
        consumed.add(id(script))
    for line in result:
        line["spans"] = [
            span for span in line.get("spans", []) if id(span) not in consumed
        ]
        # Keep an entire adjacent formula in one native equation, including
        # operators, units and further scripted variables on the same baseline.
        groups = []
        for span in line["spans"]:
            prior = groups[-1][-1] if groups else None
            compatible = (
                prior is not None
                and w.is_hancom_eq_font(str(prior.get("font", "")))
                and w.is_hancom_eq_font(str(span.get("font", "")))
                and not prior.get("source_fraction_bbox")
                and not span.get("source_fraction_bbox")
                and not any(
                    re.search(r"[Α-Ωα-ω]", w._pdf_output_text(piece.get("text", "")))
                    and not piece.get("source_script_spans")
                    for piece in (prior, span)
                )
                and prior.get("origin")
                and span.get("origin")
                and abs(prior["origin"][1] - span["origin"][1])
                <= max(float(prior.get("size", 0)), float(span.get("size", 0))) * 0.15
                and -1
                <= span["bbox"][0] - prior["bbox"][2]
                <= max(float(prior.get("size", 0)), float(span.get("size", 0))) * 1.2
            )
            if compatible:
                groups[-1].append(span)
            else:
                groups.append([span])
        merged = []
        for group in groups:
            if len(group) > 1 and any(
                span.get("source_script_spans") for span in group
            ):
                base = deepcopy(group[0])
                base["text"] = (
                    "$"
                    + "".join(
                        w._pdf_output_text(span.get("text", "")).strip("$")
                        for span in group
                    )
                    + "$"
                )
                # HWP's named Greek tokens need a separator before a Latin
                # variable: DELTA t is delta-times-t; DELTAt is a word.
                base["text"] = re.sub(r"([Α-Ωα-ω])(?=[A-Za-z])", r"\1 ", base["text"])
                base["bbox"] = tuple(
                    w._union_rect([fitz.Rect(span["bbox"]) for span in group])
                )
                base["chars"] = [
                    char for span in group for char in span.get("chars", [])
                ]
                base["source_sum_parts"] = [
                    part for span in group for part in span.get("source_sum_parts", [])
                ]
                merged.append(base)
            else:
                merged.extend(group)
        line["spans"] = merged
    return [line for line in result if line.get("spans")]


def recover_native_sum_limits(lines: list[dict]) -> list[dict]:
    """Attach explicit small limits centered above/below a PDF sum glyph.

    Run before body/header filtering: an upper limit may cross the nominal
    first-line boundary even though its summation belongs to the body. This
    does not infer values, consume the summand, or convert unrelated numbers.
    """
    from . import pdf_layout_writer as w

    result = deepcopy(lines)
    spans = [s for line in result for s in line.get("spans", [])]
    consumed = set()
    for operator in spans:
        if w._pdf_output_text(operator.get("text", "")).strip() != "∑":
            continue
        if not w.is_hancom_eq_font(str(operator.get("font", ""))):
            continue
        bounds = fitz.Rect(operator["bbox"])
        center = (bounds.tl + bounds.br) / 2
        groups = [[], []]
        for span in spans:
            if span is operator or id(span) in consumed:
                continue
            value = w._pdf_output_text(span.get("text", "")).strip()
            if not re.fullmatch(r"[A-Za-z0-9=+−\-∞]+", value):
                continue
            if not w.is_hancom_eq_font(str(span.get("font", ""))):
                continue
            size = float(span.get("size", 0))
            if not 0 < size <= float(operator.get("size", 0)) * .65:
                continue
            rect = fitz.Rect(span["bbox"])
            point = (rect.tl + rect.br) / 2
            if (abs(point.x - center.x) > bounds.width * .7
                    or not bounds.height * .32 <= abs(point.y - center.y) <= bounds.height * .95):
                continue
            groups[int(point.y > center.y)].append(span)
        # Both explicitly printed limits provide an unambiguous finite sum.
        # A missing/ambiguous side is left intact for independent validation.
        if not all(groups):
            continue
        values = []
        for group in groups:
            origins = [float(s.get("origin", (0, s["bbox"][3]))[1]) for s in group]
            if max(origins) - min(origins) > max(float(s["size"]) for s in group) * .25:
                break
            ordered = sorted(group, key=lambda s: s["bbox"][0])
            if any(right["bbox"][0] - left["bbox"][2] > max(float(left["size"]), float(right["size"])) * .7
                   for left, right in zip(ordered, ordered[1:])):
                break
            values.append("".join(w._pdf_output_text(s["text"]).strip() for s in ordered))
        if len(values) != 2 or not re.fullmatch(r"[A-Za-z]=[A-Za-z0-9+−\-]+", values[1]):
            continue
        operator["source_sum_limits"] = {"upper": deepcopy(groups[0]), "lower": deepcopy(groups[1])}
        operator["source_sum_glyphs"] = deepcopy(operator.get("chars", []))
        operator["chars"] = []
        operator["text"] = "$\\sum_{" + values[1].replace("−", "-") + "}^{" + values[0].replace("−", "-") + "}$"
        # A display sum glyph is taller than its equation's nominal font. Use
        # the adjacent baseline operand's font, retaining original glyph data.
        nearby = [s for s in spans if s is not operator and id(s) not in consumed
                  and bounds.x1 - 1 <= s["bbox"][0] <= bounds.x1 + bounds.width
                  and abs((s["bbox"][1] + s["bbox"][3]) / 2 - center.y) < bounds.height * .25
                  and float(operator.get("size", 0)) * .4 <= float(s.get("size", 0)) <= float(operator.get("size", 0)) * .8]
        if nearby:
            neighbor = min(nearby, key=lambda s: s["bbox"][0])
            operator["size"] = neighbor["size"]
            if neighbor.get("origin"):
                operator["origin"] = (bounds.x0, neighbor["origin"][1])
        operator["source_sum_parts"] = [{
            "text": operator["text"], "size": operator["size"],
            "bbox": tuple(w._union_rect([bounds] + [fitz.Rect(s["bbox"]) for group in groups for s in group])),
        }]
        consumed.update(id(s) for group in groups for s in group)
    for line in result:
        line["spans"] = [s for s in line.get("spans", []) if id(s) not in consumed]
        if line["spans"]:
            line["bbox"] = w._union_rect([fitz.Rect(s["bbox"]) for s in line["spans"]])
    return [line for line in result if line.get("spans")]


def extract_native_content(
    pdf_path: Path, *, max_pages: int | None = None
) -> tuple[list[dict], list[dict]]:
    from . import importers, pdf_layout_writer as w
    from .pdf_math_geometry import recover_native_radicals
    from .pdf_word_wrap import boundary_space_fonts, join_source_paragraph

    output: list[dict] = []
    provenance: list[dict] = []
    source_masthead_area = ""
    source_masthead_typography = {}
    source_running_headings = []
    with fitz.open(pdf_path) as document:
        for page_index in range(min(len(document), max_pages or len(document))):
            page = document[page_index]
            page_start = len(output)
            body_top = w._page_body_top(page)
            if page_index == 0:
                from .pdf_masthead_typography import measure_source_masthead
                source_masthead_typography = measure_source_masthead(page, body_top)
                areas = [w._pdf_output_text(w._line_text(line)).strip()
                         for line in w._iter_text_lines(page)
                         if w._item_bbox(line).y1 < body_top
                         and re.fullmatch(r".{1,16}영역(?:\s*\([^\n]+\))?",
                                          w._pdf_output_text(w._line_text(line)).strip())]
                source_masthead_area = max(areas, key=len, default="")
            if page_index > 0:
                from .pdf_running_headings import measure_running_heading
                running = measure_running_heading(page, body_top, source_masthead_area)
                if running:
                    source_running_headings.append(running)
            lines = [
                line
                for line in recover_native_sum_limits(
                    recover_native_radicals(w._iter_text_lines(page), source_page=page)
                )
                if w._line_text(line)
                and w._item_bbox(line).y1 >= body_top - 1
                and not w._is_flow_footer_line(page, line)
            ]
            marginal_indices = source_margin_label_indices(page, lines)
            margin_labels = [
                w._pdf_output_text(w._line_text(line))
                for index, line in enumerate(lines)
                if index in marginal_indices
            ]
            lines = [
                line
                for index, line in enumerate(lines)
                if index not in marginal_indices
            ]
            lines = _remove_margin_label_spans(page, lines)
            space_fonts = boundary_space_fonts(lines)
            drawings = page.get_drawings()
            from .pdf_inline_labels import source_inline_labels
            from .pdf_inline_label_writer import associate_inline_labels
            page_inline_labels = source_inline_labels(page, drawings)
            dark = w._page_dark_pixels(page)
            tables = w._flow_native_table_items(page, lines, drawings)
            # A page-wide rule can hide a small grid from the legacy connected-
            # drawing detector. Accept bounded multi-row/multi-column grids.
            for found in page.find_tables().tables:
                region = fitz.Rect(found.bbox)
                if (
                    found.row_count < 2
                    or found.col_count < 2
                    or region.y0 < body_top
                    or region.width > page.rect.width * 0.48
                    or region.height > page.rect.height * 0.4
                ):
                    continue
                cells = []
                for row in found.rows:
                    cell_row = []
                    for cell in row.cells:
                        bounds = fitz.Rect(cell) if cell else fitz.Rect()
                        from .pdf_source_characters import source_spans_in_cell
                        cell_row.append(source_spans_in_cell(
                            [span for line in lines for span in line.get("spans", [])], bounds))
                    cells.append(cell_row)
                tables = [t for t in tables if not region.intersects(w._item_bbox(t))]
                tables.append({"type": "native_table", "bbox": region, "cells": cells,
                               "cell_bounds": [[list(cell) if cell else None for cell in row.cells]
                                               for row in found.rows]})
            for table in w._raster_native_table_items(page, lines, dark):
                region = w._item_bbox(table)
                if not any(
                    (region & w._item_bbox(t)).get_area() >= region.get_area() * 0.8
                    for t in tables
                ):
                    tables.append(table)
            from .pdf_table_gutters import attach_table_gutters, retained_figure_label
            # A table is a container, not evidence that its images are redundant.
            # Retain each embedded figure in the source cell, with native text
            # and borders around it; never rasterize the enclosing table.
            for table in tables:
                if not table.get("cell_bounds"):
                    xs, ys = table.get("x_boundaries", []), table.get("y_boundaries", [])
                    table["cell_bounds"] = [
                        [[xs[c], ys[r], xs[c + 1], ys[r + 1]] for c in range(len(xs) - 1)]
                        for r in range(len(ys) - 1)
                    ]
            attach_table_gutters(tables, lines)
            table_regions = [w._item_bbox(t) for t in tables]
            lines, _fractions = recover_stacked_fractions(
                lines, drawings, table_regions, source_page=page
            )
            lines = recover_native_scripts(lines)
            cell_regions = [fitz.Rect(bounds) for table in tables
                            for row in table["cell_bounds"] for bounds in row if bounds]
            raster_backgrounds = []
            native_images, raster_frames = _native_images_and_frames(page, lines, cell_regions, raster_backgrounds)
            from .pdf_figure_labels import include_diagram_labels
            diagram_labels = include_diagram_labels(page, native_images, lines, table_regions)
            # PDF producers can encode one decorative frame as overlapping
            # bitmap strips. Unite their frame geometry before assigning prose.
            united = []
            for background in raster_backgrounds:
                related = [other for other in united
                           if abs(other["region"].x0-background["region"].x0) < 1
                           and abs(other["region"].x1-background["region"].x1) < 1
                           and other["region"].y0 <= background["region"].y1+0.1
                           and other["region"].y1 >= background["region"].y0-0.1]
                for other in related:
                    background = {"region": background["region"] | other["region"],
                                  "numbers": sorted(set(background["numbers"] + other["numbers"]))}
                    united.remove(other)
                united.append(background)
            raster_backgrounds = united
            raster_frames = [entry["region"] for entry in united]
            assigned_images = set()
            for table in tables:
                table["cell_images"] = []
                for picture in native_images:
                    region = w._item_bbox(picture)
                    # A figure crossing the lower edge can have its centre in
                    # the table while most of it lies outside. Only claim an
                    # image when its area belongs to this container; otherwise
                    # preserve the complete source figure as a sibling item.
                    if not _figure_inside_table(region, w._item_bbox(table)):
                        continue
                    matches = [(r, c) for r, row in enumerate(table["cell_bounds"])
                               for c, bounds in enumerate(row)
                               if bounds and (region & fitz.Rect(bounds)).get_area()
                               >= region.get_area() * 0.90]
                    if len(matches) != 1:
                        raise ValueError(f"source table figure has no unambiguous native cell: page={page_index+1}, figure={list(region)}, table={list(w._item_bbox(table))}, cells={table['cell_bounds']}")
                    r, c = matches[0]
                    table["cell_images"].append({"row": r, "column": c, "region": region})
                    assigned_images.add(id(picture))
            images = [
                i
                for i in native_images
                if w._item_bbox(i).y0 >= body_top - 1
                and id(i) not in assigned_images
            ]
            body_sizes = [float(span.get("size", 0))
                          for line in lines
                          if not any(w._item_bbox(picture).contains(w._item_bbox(line))
                                     for picture in native_images)
                          for span in line.get("spans", [])
                          if len(span.get("text", "").strip()) >= 12
                          and float(span.get("size", 0)) > 0]
            body_font_size = median(body_sizes) if body_sizes else 0
            retained_labels = diagram_labels | {id(line) for line in lines
                               if retained_figure_label(line, native_images,
                                                        body_font_size=body_font_size)}
            line_items = [
                {"type": "line", **line}
                for line in lines
                if not w._inside_any_region(w._item_bbox(line), table_regions)
                and id(line) not in retained_labels
            ]
            items = w._merge_same_row_flow_lines(page, line_items + images + tables)
            boxes = w._flow_box_rects(page, lines, drawings, dark)
            # The rectangular edge of an illustration is not a prose box.
            # Remove only image-contained candidates with no remaining native
            # text; a genuine surrounding box or a text-bearing box survives.
            boxes = [box for box in boxes if not (
                any((box & w._item_bbox(picture)).get_area() >= box.get_area() * .98
                    for picture in images)
                and not any(id(line) not in retained_labels
                            and box.contains(w._item_bbox(line)) for line in lines)
            )]
            for region in raster_frames:
                boxes = [box for box in boxes if not region.contains(box)]
                if not any((region & box).get_area() >= region.get_area() * 0.98 for box in boxes):
                    boxes.append(region)
            blocks_by_column = w._flow_column_blocks(page, items, boxes)

            def table_rows(table: dict) -> list[list[str]]:
                def cell_spans(spans):
                    # A table border is not a fraction, but a fraction inside a
                    # cell still needs the same native operand reconstruction
                    # as prose. Restrict glyphs to this cell before examining
                    # rules so neighbouring cells cannot supply operands.
                    cell_lines, _ = recover_stacked_fractions(
                        [{"spans": spans}], drawings, [], source_page=page
                    )
                    return [span for line in recover_native_scripts(cell_lines)
                            for span in line["spans"]]

                return [
                    [
                        "\n".join(
                            join_source_paragraph(group, space_fonts)
                            for group in _semantic_line_groups(
                                w._flow_lines_from_spans(
                                    cell_spans(spans)
                                )
                            )
                        )
                        for spans in row
                    ]
                    for row in table.get("cells", [])
                ]

            def save_figure(region):
                from .pdf_source_image_validation import render_source_crop
                data = render_source_crop(pdf_path, page_index, region)
                path = importers._save_image_bytes(f"native_p{page_index + 1}_{len(provenance)}.png", data)
                if not path:
                    raise ValueError("source figure could not be saved")
                provenance.append({"sha256": hashlib.sha256(data).hexdigest(), "role": "source_figure",
                                   "page": page_index + 1,
                                   "bbox_px": [region.x0, region.y0, region.width, region.height],
                                   "page_width_px": page.rect.width, "page_height_px": page.rect.height})
                return path

            def save_background(region):
                from .pdf_source_backgrounds import compose_source_background
                matches = [background for background in raster_backgrounds
                           if (background["region"] & region).get_area()
                           >= min(region.get_area(), background["region"].get_area()) * .95]
                if not matches:
                    return None
                blocks = [b for b in page.get_text("dict").get("blocks", []) if b.get("type") == 1]
                numbers = sorted({number for bg in matches for number in bg["numbers"]
                                  if any(b["number"] == number and (fitz.Rect(b["bbox"]) & region).get_area() > 0 for b in blocks)})
                data = compose_source_background(page, region, numbers)
                with Image.open(io.BytesIO(data)) as decoration:
                    if np.all(np.asarray(decoration.convert("RGB")) == 255):
                        return None
                path = importers._save_image_bytes(f"native_background_p{page_index + 1}_{len(provenance)}.png", data)
                provenance.append({"sha256": hashlib.sha256(data).hexdigest(), "role": "source_background_frame",
                                   "page": page_index + 1, "bbox_px": [region.x0, region.y0, region.width, region.height],
                                   "page_width_px": page.rect.width, "page_height_px": page.rect.height,
                                   "source_image_numbers": numbers})
                return path

            def append_table(item, table):
                index = len(item["tables"])
                item["tables"].append(table_rows(table))
                region = fitz.Rect(w._item_bbox(table))
                bounds = table.get("cell_bounds") or []
                # A single original decoration can span many editable cells.
                # Preserve that bitmap once as the native table's background.
                # Include its side rim rather than squeezing a different crop
                # into each cell or losing pixels outside the detected grid.
                for background in raster_backgrounds:
                    frame = background["region"]
                    if frame.contains(region):
                        region.x0, region.x1 = frame.x0, frame.x1
                        # Preserve a frame's empty lower rim with this table.
                        # Text below the grid belongs to its own flow item.
                        if not any(frame.contains(w._item_bbox(line))
                                   and w._item_bbox(line).y0 >= region.y1
                                   for line in lines):
                            region.y1 = frame.y1
                        break
                background = save_background(region)
                item["layout"].setdefault("native_tables", []).append({
                    "index": index, "bbox_pt": list(region), "cell_bounds": bounds,
                    "borderless_columns": table.get("borderless_columns", []),
                    "background_path": background,
                    "images": [{"row": image["row"], "column": image["column"],
                                "path": save_figure(image["region"]),
                                "bbox_pt": list(image["region"])}
                               for image in table.get("cell_images", [])],
                })

            for column, blocks in enumerate(blocks_by_column, 1):
                ordered_blocks = []
                for original in blocks:
                    if original.get("type") != "box" or not any(line.get("type") == "native_table" for line in original.get("lines", [])):
                        ordered_blocks.append(original)
                        continue
                    region = fitz.Rect(original["rect"])
                    top = region.y0
                    pending = []
                    for line in original["lines"]:
                        if line.get("type") != "native_table":
                            pending.append(line)
                            continue
                        table_region = w._item_bbox(line)
                        if pending:
                            ordered_blocks.append({**original, "lines": pending,
                                                   "rect": fitz.Rect(region.x0, top, region.x1, table_region.y0)})
                        ordered_blocks.append({"type": "native_table", "native_table": line,
                                               "column_left_pt": original.get("column_left_pt"),
                                               "column_right_pt": original.get("column_right_pt")})
                        pending = []
                        top = table_region.y1
                    if pending:
                        ordered_blocks.append({**original, "lines": pending,
                                               "rect": fitz.Rect(region.x0, top, region.x1, region.y1)})
                for block in _semantic_flow_blocks(ordered_blocks):
                    kind = block["type"]
                    if kind == "gap":
                        continue
                    item = {
                        "number": "",
                        "stem": "",
                        "choices": [],
                        "tables": [],
                        "image_paths": [],
                        "source_page": page_index + 1,
                        "layout": {
                            "source_content": True,
                            "column_count": 2,
                            "source_column": column,
                            "source_page_width_pt": page.rect.width,
                            "source_page_height_pt": page.rect.height,
                            "source_margin_labels": margin_labels,
                            "column_left_pt": block.get("column_left_pt"),
                            "column_right_pt": block.get("column_right_pt"),
                        },
                    }
                    typography_lines = []
                    if kind == "image":
                        picture = block["image"]
                        region = w._item_bbox(picture)
                        # Render only the actual embedded figure bounds. PDF
                        # soft masks must be composited or charts lose strokes.
                        path = save_figure(region)
                        item["image_paths"] = [path]
                        column_width = float(
                            block.get("column_right_pt") or page.rect.width * 0.45
                        ) - float(block.get("column_left_pt") or page.rect.width * 0.05)
                        item["layout"]["image_width_ratio"] = min(
                            1.0, region.width / max(1.0, column_width)
                        )
                        item["layout"]["source_bbox_pt"] = list(region)
                        if picture.get("diagram_labels"):
                            item["layout"]["source_diagram_labels"] = picture["diagram_labels"]
                    elif kind == "native_table":
                        append_table(item, block["native_table"])
                        typography_lines = [
                            line
                            for row in block["native_table"].get("cells", [])
                            for spans in row
                            for line in w._flow_lines_from_spans(spans)
                        ]
                    elif kind == "box":
                        typography_lines = [
                            line
                            for line in block.get("lines", [])
                            if line.get("type") == "line"
                        ]
                        text_lines = [
                            join_source_paragraph(group, space_fonts)
                            for group in _semantic_line_groups(typography_lines)
                        ]
                        if text_lines:
                            item["tables"].append([["\n".join(text_lines)]])
                            text_region = w._union_rect([w._item_bbox(line) for line in typography_lines])
                            frames = [entry["region"] for entry in raster_backgrounds
                                      if entry["region"].contains(text_region)]
                            region = fitz.Rect(frames[0]) if frames else (fitz.Rect(block["rect"]) if block.get("rect") else None)
                            if region is not None:
                                for source_table in tables:
                                    grid = w._item_bbox(source_table)
                                    if not region.intersects(grid):
                                        continue
                                    if grid.y1 <= text_region.y0:
                                        region.y0 = max(region.y0, grid.y1)
                                    elif grid.y0 >= text_region.y1:
                                        region.y1 = min(region.y1, grid.y0)
                            background = save_background(region) if region else None
                            if background:
                                item["layout"].setdefault("native_tables", []).append({"index": 0,
                                    "background_path": background,
                                    "background_preserve_border": not bool(frames),
                                    "background_source_text": "".join(
                                        w._pdf_output_text(w._line_text(line)) for line in lines
                                        if region.contains(w._item_bbox(line))),
                                    "bbox_pt": list(region), "cell_bounds": [[list(region)]]})
                        for nested in block.get("lines", []):
                            if nested.get("type") == "native_table":
                                append_table(item, nested)
                                typography_lines.extend(
                                    line
                                    for row in nested.get("cells", [])
                                    for spans in row
                                    for line in w._flow_lines_from_spans(spans)
                                )
                    else:
                        text_lines = (
                            block.get("lines")
                            if kind == "paragraph"
                            else [block["line"]]
                        )
                        typography_lines = text_lines
                        item["stem"] = join_source_paragraph(text_lines, space_fonts)
                    if typography_lines:
                        item["layout"]["source_typography"] = _source_typography(
                            typography_lines, block
                        )
                        labels = associate_inline_labels(
                            item["layout"]["source_typography"]["lines"], page_inline_labels)
                        if labels:
                            item["layout"]["source_inline_labels"] = labels
                    if item["stem"] or item["tables"] or item["image_paths"]:
                        output.append(item)
            from .pdf_background_figures import remove_covered_bitmap_figures
            output[page_start:], provenance = remove_covered_bitmap_figures(
                page, output[page_start:], provenance)
    output = _anchor_question_figures(_group_native_image_rows(output))
    if output and source_masthead_area:
        output[0]["layout"]["source_masthead_area"] = source_masthead_area
    if output and source_masthead_typography:
        output[0]["layout"]["source_masthead_typography"] = source_masthead_typography
    if output and source_running_headings:
        output[0]["layout"]["source_running_headings"] = source_running_headings
    annotate_question_groups(output)
    return output, provenance


def write_native_content(
    pdf_path: Path,
    output: Path,
    *,
    title: str,
    template: str,
    recognized,
    page_limit: int,
    native_math: bool,
    variant_policy: str,
    variant_page_limit: int | None,
    variant_overlap_ratio: float,
) -> dict:
    from . import hwpx_writer_v2, math_text, pdf_layout_writer as w

    items, provenance = extract_native_content(pdf_path, max_pages=page_limit)
    if not items:
        raise ValueError("no native PDF body content")
    problems = [p for p in recognized.problems if 0 < p.page_number <= page_limit]
    grouping = annotate_question_groups(items, problems)
    if not grouping["inventory_matches"]:
        raise ValueError(
            f"native question grouping does not match source inventory: {grouping['missing_question_markers']}"
        )
    hwpx_writer_v2.write_hwpx(
        output,
        title,
        items,
        template,
        native_math=native_math,
        preserve_source_layout=True,
    )
    from .pdf_running_headings import apply_running_heading
    heading = apply_running_heading(output, items[0]["layout"].get("source_running_headings", []), page_limit)
    from .pdf_choice_measurement import refresh_choice_tab_widths
    choice_tabs = refresh_choice_tab_widths(output)
    from .pdf_frame_rows import split_background_frame_rows
    provenance, frame_rows = split_background_frame_rows(pdf_path, output, provenance)
    structure = w._structured_hwpx_counts(output)
    fragments = w._structured_editable_text_fragments(items)
    plain = w._structured_hwpx_plain_text(output)
    total = sum(map(len, fragments))
    matched = sum(len(fragment) for fragment in fragments if fragment in plain)
    coverage = matched / total if total else 0.0
    values = [str(item["stem"]) for item in items]
    values.extend(
        str(cell)
        for item in items
        for table in item["tables"]
        for row in table
        for cell in row
    )
    segments = sum(
        is_math for value in values for _, is_math in math_text.split_math_text(value)
    )
    unresolved = sum(
        value.count(marker) for value in values for marker in ("□", "▢", "�")
    )
    return {
        **structure,
        "layout_mode": "structured",
        "structure": "native_paragraphs_tables_equations",
        "running_heading": heading,
        "choice_tab_measurement": choice_tabs,
        "background_frame_rows": frame_rows,
        "question_grouping": grouping,
        "column_layout_mode": "native_columns",
        "pages": page_limit,
        "source_pages": page_limit,
        "original_source_pages": recognized.page_count,
        "output_source_page_numbers": list(range(1, page_limit + 1)),
        "source_problem_count": len(problems),
        "recognized_problem_count": len(problems),
        "output_problem_count": len(problems),
        "duplicate_problem_count": 0,
        "unreliable_text_problems": sum(not p.text_reliable for p in problems),
        "editable_text_coverage_ratio": round(coverage, 4),
        "source_text_preservation_ratio": round(coverage, 4),
        "source_text_char_count": total,
        "matched_text_char_count": matched,
        "source_layout_coverage_ratio": 0.0,
        "source_layout_items": 0,
        "output_page_count_target": page_limit,
        "expected_page_breaks": page_limit - 1,
        "expected_column_breaks": page_limit,
        "template_key": template,
        "native_math_enabled": native_math,
        "source_math_segments": segments,
        "native_math_coverage_ratio": min(1.0, structure["native_equations"] / segments)
        if segments
        else 1.0,
        "unresolved_math_placeholders": unresolved,
        "images": len(provenance),
        "image_provenance": provenance,
        "full_page_images": 0,
        "full_page_raster_fallback": False,
        "text_visual_overlays": 0,
        "math_visual_overlays": 0,
        "text_visual_overlay_enabled": False,
        "math_visual_overlay_enabled": False,
        "variant_policy": variant_policy,
        "variant_page_limit": variant_page_limit,
        "variant_overlap_ratio": variant_overlap_ratio,
    }
