"""Inspect the output package and source regions, independent of writer scores.

Small crops are not intrinsically safe: their union can still rasterize prose.
Only source figures with traceable bytes/geometry may occur in native exports.
"""

from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
import re
import zipfile

import fitz
from lxml import etree

from .pdf_native_text import body_elements, body_text

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HC = "http://www.hancom.co.kr/hwpml/2011/core"
OPF = "http://www.idpf.org/2007/opf/"


def _compact_text(value: str) -> str:
    value = re.sub(r"(?m)^([1-5])\)(?=\s+\S)", lambda m: chr(0x2460 + int(m[1]) - 1), value)
    from .hwpx_writer import _UNICODE_GREEK_EQN
    symbols = {}
    for glyph, name in _UNICODE_GREEK_EQN.items():
        symbols.setdefault(name, glyph)
        value = value.replace(glyph, symbols[name])
    symbols.update({"triangle": "△", "angle": "∠", "LEQ": "≤", "GEQ": "≥", "NEQ": "≠"})
    for name, glyph in symbols.items():
        value = re.sub(r"(?<![A-Za-z])" + re.escape(name) + r"(?![A-Za-z])", lambda _: glyph, value)
    # A PDF's zero-width line-break opportunity carries no glyph. Keep every
    # historical Hangul jamo intact; only this format character is ignored.
    return re.sub(r"[\s{}\u200b]+", "", value)


def _package_text(root, *, omit_script_markers=False):
    return body_text(root, omit_script_markers=omit_script_markers)


def _native_text_fraction_scripts(root, header) -> list[str]:
    """Read real stacked text fractions, including cells flattened into a 보기 table.

    Cell names select a candidate pair only. The visible fraction rule, actual
    adjacent row addresses, column span and equal cell widths must agree.
    """
    hh = "http://www.hancom.co.kr/hwpml/2011/head"
    borders = {
        border.get("id"): {
            edge: (
                node.get("type")
                if (node := border.find(f"{{{hh}}}{edge}Border")) is not None
                else None
            )
            for edge in ("top", "bottom", "left", "right")
        }
        for border in header.findall(f".//{{{hh}}}borderFill")
    }
    visible_rules = set()
    for border in header.findall(f".//{{{hh}}}borderFill"):
        bottom = border.find(f"{{{hh}}}bottomBorder")
        if bottom is None:
            continue
        width = re.fullmatch(
            r"\s*(\d+(?:\.\d+)?)\s*(?:mm|cm|pt)?\s*", bottom.get("width", "")
        )
        color = bottom.get("color", "").upper()
        if (
            bottom.get("type") == "SOLID"
            and width
            and float(width[1]) > 0
            and re.fullmatch(r"#[0-9A-F]{6}", color)
            and color != "#FFFFFF"
        ):
            visible_rules.add(border.get("id"))
    scripts = []

    def fraction(table, numerator, denominator):
        num_border = borders.get(numerator.get("borderFillIDRef"), {})
        den_border = borders.get(denominator.get("borderFillIDRef"), {})
        if (
            num_border.get("bottom") != "SOLID"
            or numerator.get("borderFillIDRef") not in visible_rules
            or any(num_border.get(edge) != "NONE" for edge in ("top", "left", "right"))
            or any(
                den_border.get(edge) != "NONE"
                for edge in ("top", "bottom", "left", "right")
            )
        ):
            return None
        addresses, widths, column_spans = [], [], []
        for cell in (numerator, denominator):
            address = cell.find(f"{{{HP}}}cellAddr")
            span = cell.find(f"{{{HP}}}cellSpan")
            size = cell.find(f"{{{HP}}}cellSz")
            if (
                address is None
                or span is None
                or size is None
                or span.get("rowSpan") != "1"
                or cell.find(f".//{{{HP}}}tbl") is not None
            ):
                return None
            try:
                row, column = int(address.get("rowAddr")), int(address.get("colAddr"))
                width = int(size.get("width"))
                column_span = int(span.get("colSpan"))
                if not (
                    0 <= row < int(table.get("rowCnt"))
                    and 0 <= column < column + column_span <= int(table.get("colCnt"))
                ):
                    return None
            except (TypeError, ValueError):
                return None
            addresses.append((row, column))
            widths.append(width)
            column_spans.append(column_span)
        if (
            addresses[1] != (addresses[0][0] + 1, addresses[0][1])
            or widths[0] <= 0
            or widths[0] != widths[1]
            or column_spans[0] != column_spans[1]
        ):
            return None
        values = [
            "".join(node.text or "" for node in cell.iter() if node.tag in {f"{{{HP}}}t", f"{{{HP}}}script"})
            for cell in (numerator, denominator)
        ]
        if not all(value.strip() for value in values):
            return None
        return "{" + values[0] + "} over {" + values[1] + "}"

    for table in root.findall(f".//{{{HP}}}tbl"):
        cells = table.findall(f"{{{HP}}}tr/{{{HP}}}tc")
        if (
            table.get("rowCnt") == "2"
            and table.get("colCnt") == "1"
            and len(cells) == 2
        ):
            script = fraction(table, cells[0], cells[1])
            if script:
                scripts.append(script)
                continue
        candidates = {}
        for cell in cells:
            match = re.fullmatch(
                r"fraction:(.+):(numerator|denominator)", cell.get("name", "")
            )
            if match:
                candidates.setdefault(match[1], {}).setdefault(match[2], []).append(
                    cell
                )
        for roles in candidates.values():
            if (
                len(roles.get("numerator", []))
                == len(roles.get("denominator", []))
                == 1
            ):
                script = fraction(table, roles["numerator"][0], roles["denominator"][0])
                if script:
                    scripts.append(script)
    return scripts


def inspect_pdf_editability(
    source: Path,
    output: Path,
    provenance: list[dict],
    *,
    page_limit: int | None = None,
    require_question_boxes: bool = False,
) -> dict:
    issues: list[str] = []
    text_boxes = positioned_tables = images = body_paragraphs = 0
    declared = Counter(item.get("sha256") for item in provenance)
    used: Counter = Counter()
    native_text: list[str] = []
    native_scripts: list[str] = []
    native_fraction_tables = 0
    picture_assets: dict[str, bytes] = {}
    source_image_roots = []
    background_texts = {}
    with zipfile.ZipFile(output) as package:
        header = etree.fromstring(package.read("Contents/header.xml"))
        manifest = etree.fromstring(package.read("Contents/content.hpf"))
        hrefs = {
            item.get("id"): item.get("href", "")
            for item in manifest.iter(f"{{{OPF}}}item")
        }
        for name in package.namelist():
            if not re.fullmatch(r"Contents/section\d+\.xml", name):
                continue
            root = etree.fromstring(package.read(name))
            source_image_roots.append(root)
            native_text.append(_package_text(root))
            native_scripts.extend(
                t.text or ""
                for t in body_elements(root)
                if t.tag == f"{{{HP}}}script" and t.getparent().tag == f"{{{HP}}}equation"
            )
            text_fractions = _native_text_fraction_scripts(root, header)
            native_scripts.extend(text_fractions)
            native_fraction_tables += len(text_fractions)
            text_boxes += len(root.findall(f".//{{{HP}}}drawText"))
            for paragraph in root.findall(f"{{{HP}}}p"):
                if any(t.text for t in paragraph.findall(f"./{{{HP}}}run/{{{HP}}}t")):
                    body_paragraphs += 1
            for paragraph in root.findall(
                f".//{{{HP}}}drawText/{{{HP}}}subList/{{{HP}}}p"
            ):
                if any(t.text for t in paragraph.findall(f"./{{{HP}}}run/{{{HP}}}t")):
                    body_paragraphs += 1
            for table in root.findall(f".//{{{HP}}}tbl"):
                pos = table.find(f"{{{HP}}}pos")
                cells = table.findall(f"{{{HP}}}tr/{{{HP}}}tc")
                cap_frame = False
                if len(cells) == 3 and table.get('colCnt') == '1' and not any(
                    (t.text or '').strip() for c in (cells[0], cells[2]) for t in c.iter(f'{{{HP}}}t')
                ):
                    from .pdf_source_backgrounds import native_background_assets
                    cap_frame = all(native_background_assets(
                        etree.Element(c.tag, attrib=dict(c.attrib)), header, hrefs, package) for c in cells)
                if cap_frame or pos is None or (
                    pos.get("treatAsChar") != "1"
                    and not (
                        pos.get("vertRelTo") == "PARA"
                        and pos.get("horzRelTo") == "COLUMN"
                        and pos.get("vertOffset", "0") == "0"
                        and pos.get("horzOffset", "0") == "0"
                    )
                ):
                    from .pdf_background_geometry import source_flow_background_table
                    if not source_flow_background_table(
                        table, root, header, hrefs, package, source, provenance):
                        positioned_tables += 1
            for pic in root.findall(f".//{{{HP}}}pic"):
                images += 1
                pos = pic.find(f"{{{HP}}}pos")
                if pos is None or pos.get("treatAsChar") != "1":
                    from .pdf_floating_geometry import inspect_floating_picture
                    floating = inspect_floating_picture(pic, header)
                    if not floating["ok"]:
                        issues.append("non_inline_picture")
                        issues.extend(floating["issues"])
                if pic.get("textWrap") == "IN_FRONT_OF_TEXT":
                    issues.append("front_of_text_picture")
                image = pic.find(f".//{{{HC}}}img")
                href = (
                    hrefs.get(image.get("binaryItemIDRef"))
                    if image is not None
                    else None
                )
                if not href or href not in package.namelist():
                    issues.append("unresolved_picture_asset")
                    continue
                picture_data = package.read(href)
                from .pdf_picture_geometry import has_complete_picture_crop
                if not has_complete_picture_crop(pic, picture_data):
                    issues.append("source_picture_cropped_in_output")
                digest = hashlib.sha256(picture_data).hexdigest()
                picture_assets[digest] = picture_data
                used[digest] += 1
                if used[digest] > declared[digest]:
                    issues.append("unproven_or_duplicate_picture")
        from .pdf_source_backgrounds import native_background_assets, native_background_texts
        for root in source_image_roots:
            for digest, data in native_background_assets(root, header, hrefs, package):
                picture_assets[digest] = data
                used[digest] += 1
                if used[digest] > declared[digest]:
                    issues.append("unproven_or_duplicate_picture")
            background_texts.update(native_background_texts(root, header, hrefs, package))
    if declared - used:
        issues.append("source_figure_missing_from_output")
    from .pdf_question_inspection import inspect_question_units

    source_grid_cache = {}
    question_units = inspect_question_units(
        source,
        output,
        page_limit=page_limit,
        required=require_question_boxes,
        provenance=provenance,
        source_grid_cache=source_grid_cache,
    )
    issues.extend(question_units["issues"])
    from .pdf_paragraph_flow import inspect_paragraph_flow
    paragraph_flow = inspect_paragraph_flow(source, output, page_limit=page_limit)
    issues.extend(paragraph_flow["issues"])
    if text_boxes and (
        not question_units["ok"]
        or question_units["question_count"] + question_units.get("source_inline_label_count", 0)
           + question_units.get('source_graph_annotation_count', 0) != text_boxes
    ):
        issues.append("text_in_drawing_boxes")
    if positioned_tables:
        issues.append("positioned_text_tables")
    if not body_paragraphs:
        issues.append("no_reflowing_body_paragraphs")

    regions: dict[int, list[fitz.Rect]] = {}
    rasterized_prose: list[dict] = []
    source_fragments: list[str] = []
    source_fractions: list[str] = []
    source_attachments: list[dict] = []
    literal_identifiers: list[str] = []
    with fitz.open(source) as document:
        from .pdf_source_image_validation import inspect_source_images, native_bordered_table_texts

        source_images = inspect_source_images(
            document, picture_assets, provenance, page_limit=page_limit,
            background_texts=background_texts,
            native_table_texts=native_bordered_table_texts(source_image_roots, header),
        )
        issues.extend(source_images["issues"])
        for item in provenance:
            if item.get("sha256") not in used:
                continue
            try:
                page_number = int(item["page"])
                if (
                    not 1 <= page_number <= len(document)
                    or item.get("role") not in {"source_figure", "source_background_frame"}
                ):
                    raise ValueError("invalid source figure")
                page = document[page_number - 1]
                x, y, width, height = map(float, item["bbox_px"])
                sx = page.rect.width / float(item["page_width_px"])
                sy = page.rect.height / float(item["page_height_px"])
                region = fitz.Rect(x * sx, y * sy, (x + width) * sx, (y + height) * sy)
                if (
                    region.is_empty
                    or region.is_infinite
                    or not page.rect.contains(region)
                ):
                    raise ValueError("invalid source bounds")
                if region.get_area() >= page.rect.get_area() * 0.5:
                    issues.append("large_source_raster")
                if item.get("role") == "source_figure" and item.get('source_kind') != 'bitmap_objects':
                    regions.setdefault(page_number, []).append(region)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                issues.append("invalid_picture_provenance")

        from . import pdf_layout_writer as w
        from .pdf_native_content import recover_stacked_fractions
        from .pdf_script_attachments import source_script_attachments
        from .pdf_literal_identifiers import source_identifiers

        for page_index in range(min(len(document), page_limit or len(document))):
            page = document[page_index]
            body_top = w._page_body_top(page)
            body_lines = [
                line
                for line in w._iter_text_lines(page)
                if w._item_bbox(line).y1 >= body_top - 1
                and not w._is_flow_footer_line(page, line)
                and not w._inside_any_region(
                    w._item_bbox(line), regions.get(page_index + 1, [])
                )
            ]
            source_attachments.extend(source_script_attachments(body_lines))
            literal_identifiers.extend(source_identifiers(body_lines))
            # PDF fractions reorder characters across lines. Compare original
            # text spans and verify fraction scripts separately, not a flattened
            # line string that incorrectly treats 1/2 as the characters "21".
            source_items = [
                {"stem": w._pdf_output_text(span.get("text", ""))}
                for line in body_lines
                for span in line.get("spans", [])
                if not (
                    w.is_hancom_eq_font(str(span.get("font", "")))
                    and any(
                        int(verified["page"]) == page_index + 1
                        and fitz.Rect(verified["bbox"]).contains(
                            (fitz.Rect(span["bbox"]).tl + fitz.Rect(span["bbox"]).br) / 2
                        )
                        for verified in question_units.get("source_semantic_regions", [])
                    )
                )
            ]
            source_fragments.extend(w._structured_editable_text_fragments(source_items))
            raw_grids = source_grid_cache.get(page_index + 1)
            if raw_grids is None:
                raw_grids = [
                    {"bbox": tuple(table.bbox), "row_count": table.row_count, "col_count": table.col_count}
                    for table in page.find_tables().tables
                ]
            grid_regions = [
                fitz.Rect(table["bbox"])
                for table in raw_grids
                if table["row_count"] >= 2
                and table["col_count"] >= 2
                and table["bbox"][1] >= body_top
                and table["bbox"][2] - table["bbox"][0] <= page.rect.width * 0.48
                and table["bbox"][3] - table["bbox"][1] <= page.rect.height * 0.4
            ]
            _, fractions = recover_stacked_fractions(
                body_lines, page.get_drawings(), grid_regions, source_page=page
            )
            source_fractions.extend(
                w._hancom_eqn_script(fraction) or fraction for fraction in fractions
            )

        for page_number, page_regions in regions.items():
            page = document[page_number - 1]
            for block in page.get_text(
                "rawdict", flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES
            ).get("blocks", []):
                for line in block.get("lines", []):
                    chars = [
                        c
                        for span in line.get("spans", [])
                        for c in span.get("chars", [])
                        if c.get("c", "").strip()
                    ]
                    text = "".join(c["c"] for c in chars)
                    # Short graph labels are allowed; question/choice markers and
                    # continuous prose are not allowed to become image content.
                    prose = (
                        len(re.findall(r"[가-힣]", text)) >= 12
                        or len(re.findall(r"[a-zA-Z]", text)) >= 24
                        or re.match(r"^(?:\d{1,2}[.]|[①②③④⑤])\s*\S", text)
                    )
                    if not prose:
                        continue
                    covered = 0
                    for char in chars:
                        box = fitz.Rect(char["bbox"])
                        center = fitz.Point(
                            (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
                        )
                        covered += any(
                            region.contains(center) for region in page_regions
                        )
                    if covered and covered / max(1, len(chars)) >= 0.2:
                        rasterized_prose.append(
                            {
                                "page": page_number,
                                "text": text,
                                "covered_chars": covered,
                                "chars": len(chars),
                            }
                        )
    if rasterized_prose:
        issues.append("source_prose_in_picture_union")
    inline_labels = question_units["inline_label_frames"]
    if inline_labels['missing_label_frames']:
        issues.append('native_source_inline_label_frame_missing')
    if inline_labels['unexpected_label_frames']:
        issues.append('unproven_native_inline_label_frame')
    from .pdf_literal_identifiers import inspect_literal_identifiers

    literal_audit = inspect_literal_identifiers(literal_identifiers, source_image_roots)
    if not literal_audit["ok"]:
        issues.append("native_source_literal_identifier_missing")
    from .pdf_script_attachments import inspect_script_attachments

    attachment_audit = inspect_script_attachments(source_attachments, native_scripts)
    if not attachment_audit["ok"]:
        issues.append("native_source_script_attachment_missing")
    plain = _compact_text("".join(native_text))
    if attachment_audit["ok"]:
        # Once attachment semantics are independently checked, their syntax can
        # be omitted for this separate literal-character conservation check.
        plain = _compact_text("".join(
            _package_text(root, omit_script_markers=True) for root in source_image_roots
        ))
    source_fragments = [_compact_text(fragment) for fragment in source_fragments]
    source_chars = sum(map(len, source_fragments))
    matched_chars = sum(
        len(fragment) for fragment in source_fragments if fragment in plain
    )
    coverage = matched_chars / source_chars if source_chars else 0.0
    if coverage < 0.98:
        issues.append("native_source_text_missing")
    expected = Counter(re.sub(r"\s+", "", script) for script in source_fractions)
    normalized_scripts = [re.sub(r"\s+", "", script) for script in native_scripts]
    # A fraction can be a subtree of a larger equation such as f(x)=1/2.
    actual = Counter(
        {
            fraction: sum(script.count(fraction) for script in normalized_scripts)
            for fraction in expected
        }
    )
    missing_fractions = list((expected - actual).elements())
    if missing_fractions:
        issues.append("native_source_fraction_missing")
    from .pdf_running_heading_audit import inspect_running_header_fields
    running_headers = inspect_running_header_fields(source, output, page_limit)
    if not running_headers['ok']:
        issues.append('native_source_running_header_missing')
    return {
        "ok": not issues,
        "issues": sorted(set(issues)),
        "running_headers": running_headers,
        "draw_text_boxes": text_boxes,
        "question_units": question_units,
        "paragraph_flow": paragraph_flow,
        "positioned_tables": positioned_tables,
        "body_paragraphs": body_paragraphs,
        "images": images,
        "source_images": source_images,
        "rasterized_prose": rasterized_prose,
        "source_text_chars": source_chars,
        "matched_native_text_chars": matched_chars,
        "native_source_text_coverage": round(coverage, 4),
        "missing_source_fragments": [
            fragment for fragment in source_fragments if fragment not in plain
        ],
        "source_fractions": len(source_fractions),
        "missing_native_fractions": missing_fractions,
        "native_fraction_tables": native_fraction_tables,
        "script_attachments": attachment_audit,
        "literal_identifiers": literal_audit,
        "inline_label_frames": inline_labels,
    }
