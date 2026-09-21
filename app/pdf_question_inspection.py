"""Verify one native, complete question per actual editable text box."""

from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
import re
import zipfile

import fitz
from lxml import etree

from .pdf_question_markers import QUESTION_START as START, shared_question_range, document_note_heading

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"
OPF = "{http://www.idpf.org/2007/opf/}"
NAME = re.compile(r"question:(v\d+:q\d+)$")


def _direct_text(paragraph):
    return "".join(t.text or "" for t in paragraph.findall(f"{HP}run/{HP}t"))


def _question_starts(sub):
    """Include a stem flowing beside a figure, but not numbered data rows.

    A native layout table may contain the first prose paragraph. Later table
    rows are data rather than additional question starts; source ownership and
    the independent question inventory verify their contents separately.
    """
    direct = sub.findall(f"{HP}p")
    first = next((p for p in sub.iter(f"{HP}p") if _direct_text(p).strip()), None)
    candidates = list(direct)
    if first is not None and first not in direct:
        candidates.insert(0, first)
    return (
        [int(m[1]) for p in candidates if (m := START.match(_direct_text(p)))],
        _direct_text(first).strip() if first is not None else "",
    )


def _separate_following_passage(region, lines, question_number):
    """Separate a following source passage at its printed range heading.

    Recognition rectangles can extend from a question to the next question
    marker, enclosing a shared passage that belongs between the two questions.
    The actual printed heading, not any writer label, is the boundary evidence.
    """
    from . import pdf_layout_writer as w

    candidates = []
    for line in lines:
        bounds = w._item_bbox(line)
        marker = shared_question_range(w._line_text(line))
        if (
            marker
            and marker[0] > question_number
            and region.contains(bounds.tl)
            and bounds.y0 > region.y0
        ):
            candidates.append(bounds.y0)
    if not candidates:
        return region, None
    boundary = min(candidates)
    return (
        fitz.Rect(region.x0, region.y0, region.x1, boundary),
        fitz.Rect(region.x0, boundary, region.x1, region.y1),
    )


def _source_regions_from_markers(document, raw_lines, expected):
    """Use printed marker boundaries instead of a recognizer's text-only bottom.

    The independent recognition inventory supplies question identity and column;
    raw PDF markers supply their physical starts. A table or picture extending
    below the recognizer's tight text rectangle still belongs to that question.
    """
    from . import pdf_layout_writer as w

    result = {}
    two_column_pages = set()
    for page_number, lines in raw_lines.items():
        page = document[page_number - 1]
        midpoint = page.rect.width / 2
        substantial = [
            w._item_bbox(line)
            for line in lines
            if w._item_bbox(line).width >= page.rect.width * 0.18
            and w._item_bbox(line).y0 >= page.rect.height * 0.12
            and not w._is_flow_footer_line(page, line)
        ]
        left = sum(bounds.x1 <= midpoint for bounds in substantial)
        right = sum(bounds.x0 >= midpoint for bounds in substantial)
        crossing = len(substantial) - left - right
        headings = [
            w._item_bbox(line)
            for line in lines
            if START.match(w._line_text(line))
            or shared_question_range(w._line_text(line))
        ]
        parallel_headings = any(
            a.x1 <= midpoint <= b.x0 and abs(a.y0 - b.y0) <= max(a.height, b.height)
            for a in headings
            for b in headings
        )
        if parallel_headings or (
            left >= 4 and right >= 4 and crossing <= len(substantial) * 0.1
        ):
            two_column_pages.add(page_number)
    for key, problem in expected:
        if problem.box is None:
            continue
        page = document[problem.page_number - 1]
        sx = page.rect.width / problem.page_width_px
        sy = page.rect.height / problem.page_height_px
        box = problem.box
        region = fitz.Rect(
            box.left * sx,
            box.top * sy,
            (box.left + box.width) * sx,
            (box.top + box.height) * sy,
        )
        anchors = []
        for line in raw_lines[problem.page_number]:
            bounds = w._item_bbox(line)
            marker = START.match(w._line_text(line))
            if (
                marker
                and int(marker[1]) == problem.number
                and region.x0 <= bounds.x0 < region.x1
            ):
                anchors.append(bounds)
        if anchors:
            anchor = min(anchors, key=lambda bounds: abs(bounds.y0 - region.y0))
            region.y0 = anchor.y0
            if (
                problem.page_number in two_column_pages
                and region.width > page.rect.width * 0.75
            ):
                midpoint = page.rect.width / 2
                region.x0, region.x1 = (
                    (0, midpoint)
                    if anchor.x0 < midpoint
                    else (midpoint, page.rect.width)
                )
            # Stacked fractions / roots can rise above their question number.
            # Use actual equation ink intersecting that first line, not an
            # arbitrary padding which could absorb the previous question.
            equation_tops = [
                bounds.y0
                for line in raw_lines[problem.page_number]
                for span in line.get("spans", [])
                if w.is_hancom_eq_font(str(span.get("font", "")))
                and (bounds := fitz.Rect(span["bbox"]))
                and region.x0 <= bounds.x0 < bounds.x1 <= region.x1
                and min(bounds.y1, anchor.y1) > max(bounds.y0, anchor.y0)
                and bounds.height <= anchor.height * 4
            ]
            region.y0 = min([region.y0, *equation_tops])
        result[key] = (problem.page_number, region, bool(anchors))
    for key, (page_number, region, anchored) in result.items():
        if not anchored:
            continue  # Do not invent a larger area without a printed start.
        next_starts = [
            other.y0
            for other_key, (other_page, other, found) in result.items()
            if other_key != key
            and found
            and other_page == page_number
            and region.x0 <= other.x0 < region.x1
            and other.y0 > region.y0 + 1
        ]
        region.y1 = min(next_starts, default=document[page_number - 1].rect.height)
    return {
        key: (page_number, region) for key, (page_number, region, _) in result.items()
    }


def inspect_question_units(
    source: Path,
    output: Path,
    *,
    page_limit=None,
    required=True,
    provenance=None,
    source_grid_cache=None,
) -> dict:
    from . import pdf_layout_writer as w
    from .pdf_editability import _compact_text, _package_text
    from .pdf_native_text import body_elements, body_text
    from .recognition.pipeline import recognize_pdf
    from .pdf_script_attachments import (
        source_script_attachments,
        inspect_script_attachments,
    )
    from .pdf_source_semantics import (
        source_grid_cells,
        inspect_source_question_semantics,
    )

    boxes = []
    issues = []
    wrong_geometry = []
    outside_by_preceding = {}
    inline_label_count = 0
    with zipfile.ZipFile(output) as archive:
        header = etree.fromstring(archive.read("Contents/header.xml"))
        manifest = etree.fromstring(archive.read("Contents/content.hpf"))
        hrefs = {
            item.get("id"): item.get("href") for item in manifest.iter(f"{OPF}item")
        }
        roots = [etree.fromstring(archive.read(name)) for name in archive.namelist()
                 if re.fullmatch(r"Contents/section\d+\.xml", name)]
        from .pdf_inline_labels import inspect_inline_label_preservation, inline_label_text
        inline_labels = inspect_inline_label_preservation(source, roots, page_limit=page_limit)
        if inline_labels['missing_label_frames']:
            issues.append('native_source_inline_label_frame_missing')
        if inline_labels['unexpected_label_frames']:
            issues.append('unproven_native_inline_label_frame')
        for root in roots:
            seen_question = False
            outside_kind = None
            preceding_question = None
            for paragraph in root.findall(f"{HP}p"):
                question_names = [
                    m[1]
                    for d in body_elements(paragraph)
                    if d.tag == HP + 'drawText' and (m := NAME.fullmatch(d.get("name", "")))
                ]
                if question_names:
                    seen_question = True
                    outside_kind = None
                    preceding_question = question_names[-1]
                    continue
                outside_by_preceding[preceding_question] = outside_by_preceding.get(
                    preceding_question, ""
                ) + _compact_text(_package_text(paragraph))
                text = body_text(paragraph, include_equations=False).strip()
                if not seen_question or not text:
                    continue
                first_text = next((_direct_text(p).strip() for p in paragraph.iter(f"{HP}p")
                                   if _direct_text(p).strip()), text)
                if document_note_heading(first_text):
                    outside_kind = "document_note"
                elif shared_question_range(text):
                    outside_kind = "shared_passage"
                elif outside_kind is None:
                    issues.append("question_body_outside_container")
            for draw in (n for n in body_elements(root) if n.tag == HP + 'drawText'):
                match = NAME.fullmatch(draw.get("name", ""))
                if match is None:
                    # A source-confirmed answer frame is an inline object of
                    # an existing question paragraph, not another question or
                    # a separately positioned body-text line. Its name alone
                    # grants no exception, and the paint gate still applies.
                    if (inline_labels['ok'] and inline_label_text(draw.getparent()) is not None
                        and any(a.tag == HP+'drawText' and NAME.fullmatch(a.get('name', ''))
                                for a in draw.iterancestors())):
                        inline_label_count += 1
                        continue
                    issues.append("unidentified_text_box")
                    continue
                rect = draw.getparent()
                pos = rect.find(f"{HP}pos")
                sub = draw.find(f"{HP}subList")
                if (
                    rect.tag != f"{HP}rect"
                    or pos is None
                    or pos.get("treatAsChar") != "1"
                    or draw.get("editable") != "1"
                    or sub is None
                ):
                    issues.append("unsafe_question_box")
                    continue
                from .pdf_question_geometry import inspect_question_geometry

                geometry = inspect_question_geometry(draw)
                if not geometry["ok"]:
                    wrong_geometry.append(geometry)
                    issues.append("question_container_smaller_than_native_content")
                paragraphs = sub.findall(f".//{HP}p")
                # Numbered survey/data rows in a nested table are not exam
                # starts. Inventory and source ownership are checked below.
                starts, first = _question_starts(sub)
                if len(starts) != 1 or not START.match(first):
                    issues.append("question_box_must_have_one_question")
                text = _package_text(sub)
                pictures = Counter()
                from .pdf_source_backgrounds import native_background_assets

                pictures.update(
                    digest for digest, _data in
                    native_background_assets(sub, header, hrefs, archive)
                )
                for picture in sub.iter(f"{HP}pic"):
                    image = picture.find(f".//{HC}img")
                    href = (
                        hrefs.get(image.get("binaryItemIDRef"))
                        if image is not None
                        else None
                    )
                    if not href or href not in archive.namelist():
                        issues.append("unresolved_question_picture")
                        continue
                    pictures[hashlib.sha256(archive.read(href)).hexdigest()] += 1
                boxes.append(
                    {
                        "id": match[1],
                        "number": starts[0] if len(starts) == 1 else None,
                        "text": _compact_text(text),
                        "paragraphs": len(paragraphs),
                        "pictures": pictures,
                        "scripts": [
                            node.text or ""
                            for node in body_elements(sub)
                            if node.tag == HP + 'script' and node.getparent().tag == HP + 'equation'
                        ],
                        "element": sub,
                    }
                )
    if not boxes and not required:
        return {
            "ok": not issues,
            "issues": issues,
            "question_count": 0,
            "source_inline_label_count": inline_label_count,
            "inline_label_frames": inline_labels,
            "required": False,
        }
    recognition = recognize_pdf(Path(source).read_bytes(), filename=Path(source).name)
    problems = [
        p for p in recognition.problems if not page_limit or p.page_number <= page_limit
    ]
    expected = []
    variant = 1
    previous_number = None
    for problem in problems:
        if previous_number is not None and problem.number <= previous_number:
            variant += 1
        expected.append((f"v{variant}:q{problem.number:02d}", problem))
        previous_number = problem.number
    if Counter(box["id"] for box in boxes) != Counter(key for key, _ in expected):
        issues.append("question_container_inventory_mismatch")
    if [box["id"] for box in boxes] != [key for key, _ in expected]:
        issues.append("question_container_order_mismatch")
    by_id = {box["id"]: box for box in boxes}
    missing = []
    wrong_pictures = []
    wrong_attachments = []
    wrong_semantics = []
    wrong_shared_passages = []
    shared_regions_checked = 0
    semantic_math_fragments = semantic_grids = 0
    semantic_regions_checked = []
    with fitz.open(source) as document:
        raw_lines = {i + 1: w._iter_text_lines(page) for i, page in enumerate(document)}
        figures = {}
        figure_records = []
        for record in provenance or []:
            page_number = int(record["page"])
            page = document[page_number - 1]
            x, y, width, height = record["bbox_px"]
            sx, sy = (
                page.rect.width / record["page_width_px"],
                page.rect.height / record["page_height_px"],
            )
            region = fitz.Rect(x * sx, y * sy, (x + width) * sx, (y + height) * sy)
            figures.setdefault(page_number, []).append(region)
            figure_records.append((page_number, region, record.get("sha256")))
        source_regions = _source_regions_from_markers(document, raw_lines, expected)
        grids_by_page = {}
        for key, problem in expected:
            if problem.box is None:
                issues.append("unverifiable_source_question")
                continue
            page = document[problem.page_number - 1]
            region = source_regions[key][1]
            lines = raw_lines[problem.page_number]
            for line in lines:
                linebox = w._item_bbox(line)
                if region.contains(linebox.tl) and document_note_heading(w._line_text(line)):
                    region.y1 = min(region.y1, linebox.y0)
            region, following_passage = _separate_following_passage(
                region, lines, problem.number
            )
            if following_passage is not None:
                shared_regions_checked += 1
                shared_items = []
                for line in lines:
                    if w._is_flow_footer_line(page, line):
                        continue
                    for span in line.get("spans", []):
                        spanbox = fitz.Rect(span["bbox"])
                        center = (spanbox.tl + spanbox.br) / 2
                        if following_passage.contains(center) and not any(
                            f.contains(center)
                            for f in figures.get(problem.page_number, [])
                        ):
                            shared_items.append(
                                {"stem": w._pdf_output_text(span.get("text", ""))}
                            )
                required_shared = Counter(
                    _compact_text(value)
                    for value in w._structured_editable_text_fragments(shared_items)
                )
                outside = outside_by_preceding.get(key, "")
                absent = [
                    {"text": value, "expected": count, "actual": outside.count(value)}
                    for value, count in required_shared.items()
                    if value and outside.count(value) < count
                ]
                if absent:
                    wrong_shared_passages.append(
                        {
                            "after_question": key,
                            "source_page": problem.page_number,
                            "source_bbox": list(following_passage),
                            "missing": absent,
                        }
                    )
            source_regions[key] = (problem.page_number, region)
            box = by_id.get(key)
            if box is None:
                continue
            if box["number"] != problem.number:
                issues.append("question_number_mismatch")
            source_items = []
            math_lines = []
            for line in lines:
                if w._is_flow_footer_line(page, line):
                    continue
                selected_spans = []
                for span in line.get("spans", []):
                    spanbox = fitz.Rect(span["bbox"])
                    center = (spanbox.tl + spanbox.br) / 2
                    if region.contains(center) and not any(
                        f.contains(center) for f in figures.get(problem.page_number, [])
                    ):
                        # Equation-font spans are verified from raw geometry
                        # below. A flattened numerator/suffix span is not prose.
                        if not w.is_hancom_eq_font(str(span.get("font", ""))):
                            source_items.append(
                                {"stem": w._pdf_output_text(span.get("text", ""))}
                            )
                        selected_spans.append(span)
                if selected_spans:
                    math_lines.append({"spans": selected_spans})
            attachments = inspect_script_attachments(
                source_script_attachments(math_lines), box["scripts"]
            )
            if not attachments["ok"]:
                wrong_attachments.append({"id": key, **attachments})
            if problem.page_number not in grids_by_page:
                grids_by_page[problem.page_number] = source_grid_cells(
                    page,
                    lines,
                    figures.get(problem.page_number, []),
                    raw_grid_collector=source_grid_cache,
                )
            semantics = inspect_source_question_semantics(
                math_lines, box["element"], region, grids_by_page[problem.page_number],
                header=header, source_page=page,
            )
            semantic_regions_checked.append(
                {"id": key, "page": problem.page_number, "bbox": list(region)}
            )
            semantic_math_fragments += semantics["source_math_fragments"]
            semantic_grids += semantics["source_grids"]
            if not semantics["ok"]:
                wrong_semantics.append({"id": key, **semantics})
            box_text = box["text"]
            if attachments["ok"]:
                box_text = _compact_text(_package_text(box["element"], omit_script_markers=True))
            fragments = [
                _compact_text(f)
                for f in w._structured_editable_text_fragments(source_items)
            ]
            total = sum(map(len, fragments))
            matched = sum(len(f) for f in fragments if f in box_text)
            coverage = matched / total if total else 1.0
            if coverage < 0.98:
                missing.append(
                    {
                        "id": key,
                        "coverage": round(coverage, 4),
                        "fragments": [f for f in fragments if f not in box_text][:8],
                    }
                )
        if provenance is not None:
            expected_pictures = {key: Counter() for key, _ in expected}
            for page_number, figure, digest in figure_records:
                if figure.get_area() <= 0:
                    continue
                owners = [
                    (((region & figure).get_area() / figure.get_area()), key)
                    for key, (source_page, region) in source_regions.items()
                    if source_page == page_number
                    and (region & figure).get_area() / figure.get_area() >= 0.90
                ]
                if not owners:
                    continue  # Shared passages and document notes may own figures.
                owners.sort(reverse=True)
                if len(owners) > 1 and abs(owners[0][0] - owners[1][0]) < 1e-6:
                    issues.append("ambiguous_source_question_picture")
                    continue
                expected_pictures[owners[0][1]][digest] += 1
            for key, expected_counts in expected_pictures.items():
                actual_counts = by_id.get(key, {}).get("pictures", Counter())
                if actual_counts != expected_counts:
                    wrong_pictures.append(
                        {
                            "id": key,
                            "expected_count": sum(expected_counts.values()),
                            "actual_count": sum(actual_counts.values()),
                            "missing": dict(expected_counts - actual_counts),
                            "unexpected": dict(actual_counts - expected_counts),
                        }
                    )
    if missing:
        issues.append("source_question_content_outside_its_box")
    if wrong_pictures:
        issues.append("source_question_picture_outside_its_box")
    if wrong_attachments:
        issues.append("source_question_script_attachment_missing")
    if wrong_semantics:
        issues.append("source_question_semantics_mismatch")
    if wrong_shared_passages:
        issues.append("source_shared_passage_not_preserved_outside_questions")
    return {
        "ok": not issues,
        "issues": sorted(set(issues)),
        "question_count": len(boxes),
        "source_inline_label_count": inline_label_count,
        "inline_label_frames": inline_labels,
        "source_question_count": len(expected),
        "container_type": "native_text_box",
        "question_ids": [box["id"] for box in boxes],
        "missing_question_content": missing,
        "question_picture_ownership_checked": provenance is not None,
        "wrong_question_pictures": wrong_pictures,
        "wrong_question_script_attachments": wrong_attachments,
        "source_math_fragments_checked": semantic_math_fragments,
        "source_semantic_regions": semantic_regions_checked,
        "source_grid_tables_checked": semantic_grids,
        "wrong_question_semantics": wrong_semantics,
        "wrong_question_geometry": wrong_geometry,
        "source_shared_regions_checked": shared_regions_checked,
        "wrong_shared_passages": wrong_shared_passages,
        "required": required,
    }
