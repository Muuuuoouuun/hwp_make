"""Apply measured PDF typography to flowing, editable HWPX paragraphs.

Only styles, native object dimensions and paragraph line caches change here.
Text remains in the existing semantic paragraphs; no drawing layer is added.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from pathlib import Path
import re
from statistics import median
import zipfile

from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"
LANGUAGES = ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")


def _font_name(value):
    from .pdf_layout_writer import _recover_pdf_font_name

    name = re.sub(r"^[A-Z]{6}\+", "", _recover_pdf_font_name(str(value or ""))).lstrip(
        "*"
    )
    # PDF/PostScript names are not necessarily installed font-family names.
    # An unresolved TimesNewRoman fell back to fixed half-em Latin advances in
    # the renderer, overrunning columns despite measured source line caches.
    name = {"TimesNewRoman": "Times New Roman",
            "TimesNewRomanPSMT": "Times New Roman",
            "ArialMT": "Arial"}.get(name, name)
    if "eq" in name.lower():
        return "HY신명조"
    if "신명" in name and "고딕" not in name:
        return "한양신명조" if "한양" in name else "신명 중명조"
    if "중고딕" in name:
        return "신명 중고딕"
    return name or "HY신명조"


def _number(element, attribute, default=0):
    return (
        float(element.get(attribute, default))
        if element is not None
        else float(default)
    )


def _paragraph_units(paragraph, font_height, widths):
    """Text offsets count UTF-16 characters; inline controls occupy eight units."""
    from ._vendor.hangul_units import hangul_clusters
    from ._vendor.hwpx_text_content import iter_text_parts

    result = []
    for run in paragraph.findall(f"{HP}run"):
        for child in run:
            if child.tag == f"{HP}t":
                for value, control in iter_text_parts(child):
                    if control is not None and control.tag == HP + 'lineBreak':
                        result.append(('\n', 0, 1, 0))
                    else:
                        for char in hangul_clusters(value):
                            width = max(widths.get(part, font_height * (0.95 if ord(part) > 255 else 0.48))
                                        for part in char)
                            result.append((char, width, 8 if control is not None and control.tag == HP + 'tab' else len(char.encode("utf-16-le")) // 2, 0))
            elif child.tag == HP + 'lineBreak':
                result.append(('\n', 0, 1, 0))
            elif child.tag in {f"{HP}equation", f"{HP}tbl", f"{HP}pic", f"{HP}rect"}:
                size = child.find(f"{HP}sz")
                height = _number(size, "height")
                if child.tag == f"{HP}equation":
                    from .hwpx_writer import _equation_size

                    height = max(
                        height,
                        _equation_size(child.findtext(f"{HP}script", ""))[1]
                        * _number(child, "baseUnit", 1000)
                        / 1000,
                    )
                result.append(
                    ("\ufffc", _number(size, "width", font_height), 8, height)
                )
    return result


def _line_cache(paragraph, width, font_height, line_step, widths):
    units = _paragraph_units(paragraph, font_height, widths)
    if not units:
        return 0
    # Keep Latin words together when possible, while allowing long Korean words
    # and native objects to flow at the available column/cell width.
    lines = []
    start = 0
    while start < len(units):
        used = 0.0
        end = start
        last_space = None
        while end < len(units) and (end == start or used + units[end][1] <= width):
            used += units[end][1]
            if units[end][0].isspace():
                last_space = end + 1
            end += 1
            if units[end - 1][0] == '\n':
                break
        if end < len(units) and last_space is not None and last_space > start:
            end = last_space
        lines.append(units[start:end])
        start = end
    old = paragraph.find(f"{HP}linesegarray")
    if old is not None:
        paragraph.remove(old)
    cache = etree.SubElement(paragraph, f"{HP}linesegarray")
    offset = top = 0
    heights = [
        max(
            font_height,
            (object_height := max((unit[3] for unit in line), default=0))
            + (200 if object_height else 0),
        )
        for line in lines
    ]
    for index, (line, height) in enumerate(zip(lines, heights)):
        # A tall native equation raises this line's baseline. Without carrying
        # that difference into its trailing spacing, the following prose line
        # moves closer than the measured PDF baseline interval.
        following_baseline = (
            heights[index + 1] * 0.85 if index + 1 < len(heights) else height * 0.85
        )
        spacing = max(
            0,
            line_step - height,
            height * 0.85 + line_step - following_baseline - height,
        )
        etree.SubElement(
            cache,
            f"{HP}lineseg",
            textpos=str(offset),
            vertpos=str(round(top)),
            vertsize=str(round(height)),
            textheight=str(round(height)),
            baseline=str(round(height * 0.85)),
            spacing=str(round(spacing)),
            horzpos="0",
            horzsize=str(round(width)),
            flags="393216",
        )
        top += height + spacing
        offset += sum(unit[2] for unit in line)
    return top


def _flow_height(paragraph):
    lines = paragraph.findall(f"{HP}linesegarray/{HP}lineseg")
    height = sum(
        _number(line, "vertsize", 1000) + _number(line, "spacing") for line in lines
    )
    objects = [
        child
        for run in paragraph.findall(f"{HP}run")
        for child in run
        if child.tag in {f"{HP}tbl", f"{HP}pic", f"{HP}rect"}
    ]
    return max(height, *(
        _number(obj.find(f"{HP}sz"), "height")
        + (0 if obj.tag == HP + "rect" and obj.find(HP + "drawText") is not None else 400)
        for obj in objects), 1)


def _fit_table_heights(root, is_fraction, header=None):
    from hwpx.tools.paragraph_spacing import paragraph_spacing
    styles = {p.get('id'): p for p in header.iter(HH + 'paraPr')} if header is not None else {}
    def measure(paragraph):
        return _flow_height(paragraph) + sum(paragraph_spacing(paragraph, styles))
    # Work from inner tables outward so each cell includes its actual objects.
    for table in reversed(root.findall(f".//{HP}tbl")):
        if is_fraction(table):
            continue
        rows = table.findall(f"{HP}tr")
        if any(
            int(span.get("rowSpan", "1")) > 1
            for span in table.findall(f"{HP}tr/{HP}tc/{HP}cellSpan")
        ):
            from hwpx.tools.table_reflow import fit_table_rows
            fit_table_rows(table, measure)
            continue
        total = 0
        for row in rows:
            cells = row.findall(f"{HP}tc")
            row_height = 800
            for cell in cells:
                sublist = cell.find(f"{HP}subList")
                if sublist is None:
                    continue
                height = sum(measure(p) for p in sublist.findall(f"{HP}p"))
                margin = cell.find(f"{HP}cellMargin")
                height += _number(margin, "top") + _number(margin, "bottom") + 200
                row_height = max(row_height, height)
                if table.get("colCnt") == "1":
                    sublist.set("vertAlign", "TOP")
            for cell in cells:
                size = cell.find(f"{HP}cellSz")
                if size is not None:
                    size.set("height", str(round(row_height)))
            total += row_height
        size = table.find(f"{HP}sz")
        if size is not None and total:
            size.set("height", str(round(total)))


def _paginate(section, paragraphs, source_groups, header=None):
    if not paragraphs:
        return
    page = section.find(f".//{HP}pagePr")
    margin = page.find(f"{HP}margin") if page is not None else None
    available = (
        _number(page, "height", 84188)
        - _number(margin, "top", 5669)
        - _number(margin, "header")
        - _number(margin, "bottom", 5102)
    )
    prologue = []
    for paragraph in section.findall(f"{HP}p"):
        if paragraph is paragraphs[0]:
            break
        prologue.append(paragraph)
    from hwpx.tools.paragraph_spacing import paragraph_spacing
    styles = {p.get("id"): p for p in header.iter(HH + "paraPr")} if header is not None else {}
    header_height = sum(_flow_height(p) + sum(paragraph_spacing(p, styles)) for p in prologue)
    # Source boundaries are minimum positions. Once a complete question has
    # spilled beyond an original boundary, advancing again would leave an
    # unnecessary empty column or page. Content order remains unchanged.
    first_source_page = int(source_groups[0][0])
    page_index = column = 0
    cursor = 0.0
    for paragraph, group in zip(paragraphs, source_groups):
        paragraph.set("pageBreak", "0")
        paragraph.set("columnBreak", "0")
        desired_slot = max(0, int(group[0]) - first_source_page) * 2 + max(
            0, min(1, int(group[1]) - 1)
        )
        physical_slot = page_index * 2 + column
        if physical_slot < desired_slot:
            if desired_slot // 2 > page_index:
                paragraph.set("pageBreak", "1")
                page_index += 1
                column = 0
            else:
                paragraph.set("columnBreak", "1")
                column += 1
            cursor = 0.0
        limit = available - (header_height if page_index == 0 else 0) - 1400
        before, after = paragraph_spacing(paragraph, styles)
        height = _flow_height(paragraph) + before + after
        if before and cursor + height > limit and header is not None:
            # Content takes priority when a measured blank area no longer
            # fits. Collapse that space rather than pushing an otherwise
            # fitting complete question to a new source column.
            from .pdf_source_spacing import set_space_before
            set_space_before(paragraph, header, 0)
            height -= before
        if page_index == 0 and height > limit:
            # A fixed question box that fits a full page may not fit below the
            # first-page masthead. Reserve a full page rather than clipping it.
            paragraph.set("pageBreak", "1")
            paragraph.set("columnBreak", "0")
            page_index += 1
            column = 0
            cursor = 0.0
        elif cursor and cursor + height > limit:
            paragraph.set("columnBreak", "1")
            column += 1
            if column == 2:
                column = 0
                page_index += 1
            cursor = 0.0
        cursor += height


def apply_native_typography(path: Path, items: list[dict]) -> dict:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        payloads = {info.filename: archive.read(info.filename) for info in infos}
    header = etree.fromstring(payloads["Contents/header.xml"])
    chars = header.find(f".//{HH}charProperties")
    paras = header.find(f".//{HH}paraProperties")
    if chars is None or paras is None:
        return {"applied": False, "reason": "missing_native_styles"}
    char_by_id = {node.get("id"): node for node in chars}
    para_by_id = {node.get("id"): node for node in paras}
    char_cache = {}
    para_cache = {}
    equation_matches = equation_fallbacks = 0
    equation_width_matches = 0
    sideflow_groups = 0
    choice_rows = 0
    changed_paragraphs = 0
    shared_table_paragraphs = 0
    source_fonts = set()
    fraction_borders = {
        node.get("id")
        for node in header.findall(f".//{HH}borderFill")
        if (bottom := node.find(f"{HH}bottomBorder")) is not None
        and bottom.get("type") == "SOLID"
        and all(
            (edge := node.find(f"{HH}{name}Border")) is not None
            and edge.get("type") == "NONE"
            for name in ("top", "left", "right")
        )
    }

    def fraction_table(table):
        cells = table.findall(f"{HP}tr/{HP}tc")
        return (
            table.get("rowCnt") == "2"
            and table.get("colCnt") == "1"
            and len(cells) == 2
            and cells[0].get("borderFillIDRef") in fraction_borders
            and cells[1].get("borderFillIDRef") not in fraction_borders
        )

    def font_ids(name):
        ids = {}
        for face in header.findall(f".//{HH}fontface"):
            language = face.get("lang", "").lower()
            font = next((f for f in face if f.get("face") == name), None)
            if font is None:
                font = etree.SubElement(
                    face,
                    f"{HH}font",
                    id=str(max((int(f.get("id", "0")) for f in face), default=-1) + 1),
                    face=name,
                    type="TTF",
                    isEmbedded="0",
                )
                face.set("fontCnt", str(len(face)))
            ids[language] = font.get("id")
        return ids

    def char_style(base, height, font, spacing, ratio, bold=None):
        key = (base, round(height), font, spacing, ratio, bold)
        if key not in char_cache:
            node = deepcopy(char_by_id.get(base, next(iter(char_by_id.values()))))
            identifier = str(max(map(int, char_by_id)) + 1)
            node.set("id", identifier)
            node.set("height", str(round(height)))
            if bold is not None:
                weight = node.find(HH + "bold")
                if bold and weight is None:
                    etree.SubElement(node, HH + "bold")
                elif not bold and weight is not None:
                    node.remove(weight)
            refs = node.find(f"{HH}fontRef")
            ids = font_ids(font)
            for language in LANGUAGES:
                if refs is not None and language in ids:
                    refs.set(language, ids[language])
            for kind, value in (("ratio", ratio), ("spacing", spacing)):
                metric = node.find(f"{HH}{kind}")
                if metric is not None:
                    for language in LANGUAGES:
                        metric.set(language, str(value))
            chars.append(node)
            char_by_id[identifier] = node
            char_cache[key] = identifier
        return char_cache[key]

    def para_style(base, alignment, step, font_height, left=0, indent=0, right=0):
        percent = max(100, min(250, round(step * 100 / font_height)))
        key = (base, alignment, percent, round(left), round(indent), round(right))
        if key not in para_cache:
            node = deepcopy(para_by_id.get(base, next(iter(para_by_id.values()))))
            identifier = str(max(map(int, para_by_id)) + 1)
            node.set("id", identifier)
            align = node.find(f"{HH}align")
            if align is not None:
                align.set("horizontal", alignment)
            for spacing in node.findall(f".//{HH}lineSpacing"):
                spacing.set("type", "PERCENT")
                spacing.set("value", str(percent))
                spacing.set("unit", "PERCENT")
            for margin in node.findall(f".//{HH}margin"):
                for name in ("left", "right", "prev", "next", "intent"):
                    edge = margin.find(f"{HC}{name}")
                    if edge is not None:
                        value = {"left": left, "right": right, "intent": indent}.get(name, 0)
                        edge.set("value", str(round(value)))
            paras.append(node)
            para_by_id[identifier] = node
            para_cache[key] = identifier
        return para_cache[key]

    for filename, payload in list(payloads.items()):
        if not re.fullmatch(r"Contents/section\d+\.xml", filename):
            continue
        section = etree.fromstring(payload)
        from .pdf_picture_geometry import restore_picture_coordinates
        manifest = etree.fromstring(payloads["Contents/content.hpf"])
        hrefs = {n.get("id"): n.get("href") for n in manifest.iter("{http://www.idpf.org/2007/opf/}item")}
        restore_picture_coordinates(section, payloads, hrefs)
        from .pdf_source_spacing import apply_source_column_rails
        apply_source_column_rails(section, items)
        page = section.find(f".//{HP}pagePr")
        page_width = _number(page, "width", 59528)
        margin = page.find(f"{HP}margin") if page is not None else None
        original_width = (
            page_width - _number(margin, "left", 5669) - _number(margin, "right", 5669)
        )
        native_columns = next((c for c in section.iter(HP + "colPr") if c.get("colCount") == "2"), None)
        default_width = (original_width - _number(native_columns, "sameGap", 2268)) / 2
        from .pdf_masthead_typography import apply_source_masthead
        apply_source_masthead(section, header, items, char_style)
        # The measured masthead may add a paragraph style of its own.
        # Subsequent body styles must allocate IDs from the updated registry.
        para_by_id.update({p.get("id"): p for p in paras})
        flow_paragraphs = []
        source_groups = []
        item_layouts = []
        for root_paragraph in section.findall(f"{HP}p"):
            index = root_paragraph.attrib.pop("nativeSourceItem", None)
            if index is None:
                continue
            flow_paragraphs.append(root_paragraph)
            item = items[int(index) - 1]
            layout = item.get("layout") or {}
            item_layouts.append(
                dict(layout, source_page=int(item.get("source_page") or 1))
            )
            source_groups.append(
                (
                    int(item.get("source_page") or 1),
                    int(layout.get("source_column") or 1),
                )
            )
            meta = layout.get("source_typography") or {}
            if not meta:
                continue
            scale = page_width / float(layout.get("source_page_width_pt") or 842)
            size = float(meta.get("font_size_pt") or 11.21)
            font_height = max(500, min(1600, size * scale))
            step = max(
                font_height, float(meta.get("line_spacing_pt") or size * 1.5) * scale
            )
            width = min(
                default_width,
                float(meta.get("source_column_width_pt") or default_width / scale)
                * scale,
            )
            font = _font_name(meta.get("font_name_recovered") or meta.get("font_name"))
            source_fonts.add(font)
            spacing = max(
                -15, min(15, round(float(meta.get("letter_spacing_percent") or 0)))
            )
            ratio = max(
                80, min(110, round(float(meta.get("font_width_percent") or 100)))
            )
            from .pdf_inline_label_writer import restore_inline_labels
            inline_label_count = restore_inline_labels(root_paragraph, layout, page_width, char_style, para_style)
            samples = defaultdict(list)
            for line in meta.get("lines") or []:
                for span in line.get("spans") or []:
                    for char in span.get("chars") or []:
                        bbox = char.get("bbox") or []
                        if len(bbox) == 4 and bbox[2] > bbox[0]:
                            samples[char.get("c", "")].append(
                                max(
                                    1,
                                    (bbox[2] - bbox[0]) * scale
                                    + font_height * spacing / 100,
                                )
                            )
            widths = {char: median(values) for char, values in samples.items()}
            widths.setdefault(" ", font_height * 0.3)
            # Equation glyphs have an independent baseUnit; inheriting the body
            # char style alone leaves their original fixed 10pt size unchanged.
            from .hwpx_writer import _hancom_eqn_script
            from .pdf_layout_writer import _pdf_output_text, is_hancom_eq_font
            from .pdf_native_content import recover_native_scripts

            measured_equations = defaultdict(list)
            math_sizes = []
            for source_line in recover_native_scripts(meta.get("lines") or []):
                for span in source_line.get("spans", []):
                    # A native standalone sigma can be split from a larger
                    # merged source formula. Its limits' actual ink bounds
                    # remain independent evidence for its displayed width.
                    for part in span.get("source_sum_parts", []):
                        expression = str(part.get("text", "")).strip().strip("$")
                        canonical_sum = re.sub(r"\s+", "", _hancom_eqn_script(expression) or "")
                        bounds_sum = part.get("bbox") or ()
                        if canonical_sum and len(bounds_sum) == 4:
                            measured_equations[canonical_sum].append((
                                float(part.get("size", 0)),
                                float(bounds_sum[2]) - float(bounds_sum[0]),
                            ))
                    if not is_hancom_eq_font(str(span.get("font", ""))):
                        continue
                    source_size = float(span.get("size") or 0)
                    expression = (
                        _pdf_output_text(span.get("text", "")).strip().strip("$")
                    )
                    if not source_size or not expression:
                        continue
                    script = _hancom_eqn_script(expression)
                    if not script:
                        continue
                    canonical = re.sub(r"\s+", "", script)
                    # The restored span includes the fraction rule's width;
                    # source_fraction_bbox records operand ink for line-height
                    # grouping and can be narrower than the full expression.
                    bbox = span.get("bbox") or ()
                    source_width = (
                        float(bbox[2]) - float(bbox[0]) if len(bbox) == 4 else 0.0
                    )
                    measured_equations[canonical].append((source_size, source_width))
                    math_sizes.append(source_size)
            from .pdf_equation_measurements import joined_equation_metrics
            targets = {re.sub(r"\s+", "", e.findtext(HP + "script", ""))
                       for e in root_paragraph.iter(HP + "equation")}
            for canonical, measurements in joined_equation_metrics(
                recover_native_scripts(meta.get("lines") or []), targets
            ).items():
                measured_equations[canonical].extend(measurements)
            for equation in root_paragraph.iter(f"{HP}equation"):
                canonical = re.sub(r"\s+", "", equation.findtext(f"{HP}script", ""))
                measured = measured_equations.get(canonical)
                source_width = None
                if measured:
                    source_size = median(value[0] for value in measured)
                    measured_widths = [value[1] for value in measured if value[1] > 0]
                    if measured_widths:
                        source_width = median(measured_widths)
                        equation_width_matches += 1
                    equation_matches += 1
                elif math_sizes:
                    # A mixed-font expression can span several PDF spans. Its
                    # baseline font still comes from this exact source item.
                    largest = max(math_sizes)
                    source_size = median(
                        [value for value in math_sizes if value > largest * 0.82]
                    )
                    equation_fallbacks += 1
                else:
                    continue
                old_base = _number(equation, "baseUnit", 1000)
                new_base = max(1, round(source_size * scale))
                equation.set("baseUnit", str(new_base))
                bounds = equation.find(f"{HP}sz")
                if bounds is not None:
                    bounds.set(
                        "width",
                        str(
                            max(
                                1,
                                round(
                                    source_width * scale
                                    if source_width
                                    else _number(bounds, "width") * new_base / old_base
                                ),
                            )
                        ),
                    )
                    if _number(bounds, "height"):
                        bounds.set(
                            "height",
                            str(
                                max(
                                    1,
                                    round(
                                        _number(bounds, "height") * new_base / old_base
                                    ),
                                )
                            ),
                        )
            for paragraph in root_paragraph.iter(f"{HP}p"):
                if any(a.tag == HP+'drawText' and a.get('name') == 'source-inline-label'
                       for a in paragraph.iterancestors()):
                    continue
                # Fraction cells already have their own compact centered style.
                ancestor = paragraph.getparent()
                is_fraction_cell = False
                while ancestor is not None and ancestor is not root_paragraph:
                    if ancestor.tag == f"{HP}tbl" and fraction_table(ancestor):
                        is_fraction_cell = True
                        break
                    ancestor = ancestor.getparent()
                for run in paragraph.findall(f"{HP}run"):
                    if run.find(f"{HP}t") is not None:
                        run.set(
                            "charPrIDRef",
                            char_style(
                                run.get("charPrIDRef", "0"),
                                font_height,
                                font,
                                spacing,
                                ratio,
                            ),
                        )
                available = width
                parent = paragraph.getparent()
                if parent is not None and parent.tag == f"{HP}subList":
                    cell = parent.getparent()
                    cellsize = cell.find(f"{HP}cellSz")
                    available = min(width, _number(cellsize, "width", width) - 600)
                if is_fraction_cell:
                    # Editable Hangul operands use the measured source table
                    # font too. Keep their centered fraction paragraph style.
                    _line_cache(paragraph, max(1500, available), font_height,
                                font_height * 1.2, widths)
                    continue
                if any(
                    (position := table.find(f"{HP}pos")) is None
                    or position.get("treatAsChar") != "1"
                    for table in paragraph.findall(f"./{HP}run/{HP}tbl")
                ):
                    continue
                paragraph.set(
                    "paraPrIDRef",
                    para_style(
                        paragraph.get("paraPrIDRef", "0"),
                        str(meta.get("alignment") or "LEFT").upper(),
                        step,
                        font_height,
                    ),
                )
                if _line_cache(
                    paragraph, max(1500, available), font_height, step, widths
                ):
                    changed_paragraphs += 1
                if paragraph is root_paragraph:
                    from .pdf_source_line_cache import apply_source_line_cache
                    apply_source_line_cache(paragraph, {**layout, "native_page_width": page_width}, max(1500, available))
            if inline_label_count and root_paragraph.find(HP + 'run/' + HP + 'tbl') is None:
                from .pdf_source_line_cache import apply_source_line_cache
                apply_source_line_cache(root_paragraph, {**layout, 'native_page_width': page_width}, width)
            from .pdf_table_paragraphs import restore_background_frame
            background_paragraphs = restore_background_frame(
                root_paragraph, layout, header, page_width, default_width, para_style)
            if background_paragraphs:
                shared_table_paragraphs += background_paragraphs
                item_layouts[-1]['source_bbox_pt'] = layout['native_tables'][0]['bbox_pt']
                para_by_id.update({p.get("id"): p for p in paras})
            elif (layout.get('question_group_kind') == 'shared_passage' or inline_label_count
                or root_paragraph.find('.//' + HP + 'tbl//' + HP + 'equation') is not None):
                # A shared passage or a complete mixed-math cell can recover
                # measured paragraphs. Ordinary question callouts may contain
                # partial frames and need their spacing reconciled as a group.
                from .pdf_table_paragraphs import restore_table_paragraphs
                shared_table_paragraphs += restore_table_paragraphs(root_paragraph, layout, header, page_width, para_style)
                para_by_id.update({p.get("id"): p for p in paras})
        if flow_paragraphs:
            for body_paragraph in flow_paragraphs:
                _fit_table_heights(body_paragraph, fraction_table, header)
            from .pdf_floating_figures import restore_floating_figures
            flow_paragraphs, item_layouts, restored_floats = restore_floating_figures(
                section, flow_paragraphs, item_layouts, default_width)
            sideflow_groups += restored_floats
            from .pdf_question_sideflow import restore_question_sideflow

            flow_paragraphs, item_layouts, restored = restore_question_sideflow(
                section, flow_paragraphs, item_layouts, header, default_width
            )
            sideflow_groups += restored
            # Decide standalone anchoring only after figures have been
            # assigned to their real prose wrap or native sideflow cell.
            from .pdf_picture_geometry import restore_single_picture_paragraph
            for paragraph, layout in zip(flow_paragraphs, item_layouts):
                restore_single_picture_paragraph(paragraph, layout, page_width, default_width, para_style)
            from .pdf_question_units import wrap_question_units

            paragraph_sources = list(zip(flow_paragraphs, item_layouts))
            flow_paragraphs, source_groups = wrap_question_units(
                section, flow_paragraphs, item_layouts, header, default_width
            )
            from .pdf_paragraph_indentation import restore_paragraph_indentation
            restore_paragraph_indentation(paragraph_sources, header, page_width, default_width)
            from .pdf_choice_tabs import restore_choice_tabs
            choice_rows += restore_choice_tabs(paragraph_sources, header, page_width, default_width)
            para_by_id.update({p.get("id"): p for p in paras})
            if filename == "Contents/section0.xml" and "Contents/section1.xml" not in payloads:
                from .pdf_source_spacing import split_masthead_section
                following = split_masthead_section(section, flow_paragraphs, source_groups, paragraph_sources, header)
                if following is not None:
                    payloads["Contents/section1.xml"] = etree.tostring(
                        following, encoding="utf-8", xml_declaration=True, standalone=True)
                    manifest = etree.fromstring(payloads["Contents/content.hpf"])
                    opf = "{" + etree.QName(manifest).namespace + "}"
                    etree.SubElement(manifest.find(opf + "manifest"), opf + "item", id="section1",
                                     href="Contents/section1.xml", attrib={"media-type": "application/xml"})
                    etree.SubElement(manifest.find(opf + "spine"), opf + "itemref", idref="section1", linear="yes")
                    payloads["Contents/content.hpf"] = etree.tostring(manifest, encoding="utf-8", xml_declaration=True)
                    header.set("secCnt", "2")
            # Paginate each section using its own printable height. Running
            # the first-page margin over all later pages prematurely removed
            # valid whitespace before the section split could restore it.
            local = [(p, group) for p, group in zip(flow_paragraphs, source_groups)
                     if p.getparent() is section]
            _paginate(section, [p for p, _ in local], [group for _, group in local], header)
        payloads[filename] = etree.tostring(
            section, encoding="utf-8", xml_declaration=True, standalone=True
        )
    from hwpx.tools.question_spacing import arrange_question_gaps
    native_question_gaps = 0
    for filename in list(payloads):
        if re.fullmatch(r"Contents/section\d+\.xml", filename):
            section = etree.fromstring(payloads[filename])
            native_question_gaps += arrange_question_gaps(section, header)
            payloads[filename] = etree.tostring(section, encoding="utf-8", xml_declaration=True, standalone=True)
    chars.set("itemCnt", str(len(chars)))
    paras.set("itemCnt", str(len(paras)))
    payloads["Contents/header.xml"] = etree.tostring(
        header, encoding="utf-8", xml_declaration=True, standalone=True
    )
    with zipfile.ZipFile(path, "w") as archive:
        for info in infos:
            archive.writestr(info, payloads[info.filename])
        existing = {info.filename for info in infos}
        for name in payloads.keys() - existing:
            archive.writestr(name, payloads[name], compress_type=zipfile.ZIP_DEFLATED)
    from .hwpx_writer_v2 import _merge_native_paragraphs

    _merge_native_paragraphs(path)
    return {
        "applied": bool(changed_paragraphs),
        "paragraphs": changed_paragraphs,
        "font_faces": sorted(source_fonts),
        "source_metrics": True,
        "equations_source_font_matched": equation_matches,
        "equations_source_item_font": equation_fallbacks,
        "equations_source_width_matched": equation_width_matches,
        "source_sideflow_groups": sideflow_groups,
        "source_choice_rows": choice_rows,
        "source_shared_table_paragraphs": shared_table_paragraphs,
        "native_question_gaps": native_question_gaps,
    }
