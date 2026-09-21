"""Flatten boxed-view word fractions into one native table nesting level."""

from __future__ import annotations

from copy import deepcopy
import re
from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def flatten_question_fraction_tables(paragraphs, header, *, width=None):
    """Keep stacked editable fractions visible inside a question drawText.

    Some readers omit a table inside a table inside drawText. Replace only
    one-cell view boxes containing word fractions with an equivalent flat grid.
    Ordinary text spans the grid; fraction operands occupy adjacent rows.
    """
    from .pdf_native_typography import _line_cache
    from .hwpx_writer_v2 import _set_paragraph_element_lineseg, _visual_units

    fills = header.find(f".//{HH}borderFills")
    styles = header.find(f".//{HH}charProperties")
    para_styles = header.find(f".//{HH}paraProperties")
    if fills is None or styles is None or para_styles is None:
        raise ValueError("native fraction layout requires document styles")
    fill_by_id = {x.get("id"): x for x in fills}
    char_by_id = {x.get("id"): x for x in styles}
    para_by_id = {x.get("id"): x for x in para_styles}
    fill_cache = {}
    root = paragraphs[0].getroottree().getroot() if paragraphs else None
    paragraph_ids = (
        {p.get("id") for p in root.iter(f"{HP}p")} if root is not None else set()
    )
    next_paragraph_id = 1

    def paragraph_id():
        nonlocal next_paragraph_id
        while str(next_paragraph_id) in paragraph_ids:
            next_paragraph_id += 1
        value = str(next_paragraph_id)
        paragraph_ids.add(value)
        next_paragraph_id += 1
        return value

    def edge_style(fill_id, edge):
        node = fill_by_id.get(str(fill_id))
        child = node.find(f"{HH}{edge}Border") if node is not None else None
        return child.get("type", "NONE") if child is not None else "NONE"

    def fraction(table):
        pos = table.find(f"{HP}pos")
        cells = table.findall(f"{HP}tr/{HP}tc")
        return (
            table.get("rowCnt") == "2"
            and table.get("colCnt") == "1"
            and pos is not None
            and pos.get("treatAsChar") == "1"
            and len(cells) == 2
            and edge_style(cells[0].get("borderFillIDRef"), "bottom") == "SOLID"
            and all(
                edge_style(cells[0].get("borderFillIDRef"), e) == "NONE"
                for e in ("left", "right", "top")
            )
            and re.search(
                r"[가-힣]", "".join(x.text or "" for x in table.findall(f".//{HP}t"))
            )
        )

    def borders(source, edges):
        key = (source, tuple(sorted(edges)))
        if key not in fill_cache:
            node = deepcopy(fill_by_id[source])
            identifier = str(max(map(int, fill_by_id)) + 1)
            node.set("id", identifier)
            for edge in ("left", "right", "top", "bottom"):
                rule = node.find(f"{HH}{edge}Border")
                if rule is not None:
                    rule.set("type", "SOLID" if edge in edges else "NONE")
            fills.append(node)
            fill_by_id[identifier] = node
            fill_cache[key] = identifier
        return fill_cache[key]

    def part(paragraph, runs):
        result = etree.Element(paragraph.tag, dict(paragraph.attrib))
        for run in runs:
            result.append(deepcopy(run))
        if not runs:
            etree.SubElement(
                etree.SubElement(result, f"{HP}run", charPrIDRef="0"), f"{HP}t"
            ).text = ""
        result.set("pageBreak", "0")
        result.set("columnBreak", "0")
        return result

    def text_width(paragraph):
        total = 0
        for run in paragraph.findall(f"{HP}run"):
            style = char_by_id.get(run.get("charPrIDRef"))
            size = int(style.get("height", "790")) if style is not None else 790
            for child in run:
                if child.tag == f"{HP}t":
                    total += _visual_units(child.text or "") * size * 0.5
                elif child.tag == f"{HP}equation":
                    total += int(child.find(f"{HP}sz").get("width", "0")) + 112
        return round(total)

    def first_sentence(paragraph):
        """Keep the fraction's connective beside it; resume prose at full width."""
        before, after = [], []
        found = False
        for run in paragraph.findall(f"{HP}run"):
            for child in run:
                clone = etree.Element(run.tag, dict(run.attrib))
                if not found and child.tag == f"{HP}t":
                    match = re.search(r"[.!?](?=\s)", child.text or "")
                    if match:
                        first = deepcopy(child)
                        first.text = (child.text or "")[: match.end()]
                        clone.append(first)
                        before.append(clone)
                        rest = deepcopy(child)
                        rest.text = (child.text or "")[match.end() :].lstrip()
                        if rest.text:
                            tail = etree.Element(run.tag, dict(run.attrib))
                            tail.append(rest)
                            after.append(tail)
                        found = True
                        continue
                clone.append(deepcopy(child))
                (after if found else before).append(clone)
        return (part(paragraph, before), part(paragraph, after)) if after else None

    def cache(paragraph, width):
        run = next(
            (r for r in paragraph.findall(f"{HP}run") if r.find(f"{HP}t") is not None),
            None,
        )
        char = char_by_id.get(run.get("charPrIDRef")) if run is not None else None
        size = int(char.get("height", "790")) if char is not None else 790
        para = para_by_id.get(paragraph.get("paraPrIDRef"))
        spacing = para.find(f".//{HH}lineSpacing") if para is not None else None
        percent = int(spacing.get("value", "150")) if spacing is not None else 150
        height = _line_cache(
            paragraph, max(100, width - 200), size, size * percent / 100, {}
        )
        if not height:
            _set_paragraph_element_lineseg(
                paragraph, 1, width=max(100, width - 200), spacing_ratio=0
            )
        return height

    changed = 0
    for parent in paragraphs:
        from .pdf_source_cell_fractions import flatten_source_cell_fractions
        for grid in list(parent.findall(f"./{HP}run/{HP}tbl")):
            if (grid.get("rowCnt"),grid.get("colCnt")) != ("1","1") and not fraction(grid):
                if flatten_source_cell_fractions(grid, header, fraction, flatten_question_fraction_tables, paragraph_id):
                    changed += 1
        direct_fractions = [
            table for table in parent.findall(f"./{HP}run/{HP}tbl") if fraction(table)
        ]
        if direct_fractions:
            # Direct inline fractions also lose their x position in drawText.
            # Reuse the flat operand grid without adding a visible body frame.
            original = deepcopy(parent)
            outer = deepcopy(direct_fractions[0])
            outer.set("nativeFractionBody", "1")
            outer.set("rowCnt", "1")
            outer.set("colCnt", "1")
            root_ids = [
                int(x.get("id")) for x in root.iter() if str(x.get("id", "")).isdigit()
            ]
            outer.set("id", str(max(root_ids, default=1000000000) + 1))
            whole_width = int(width or 22961)
            outer.find(f"{HP}sz").set("width", str(whole_width))
            position = outer.find(f"{HP}pos")
            position.set("treatAsChar", "0")
            position.set("vertRelTo", "PARA")
            position.set("horzRelTo", "COLUMN")
            position.set("vertOffset", "0")
            position.set("horzOffset", "0")
            no_border = borders(
                direct_fractions[0].find(f"{HP}tr/{HP}tc").get("borderFillIDRef"), set()
            )
            outer.set("borderFillIDRef", no_border)
            cell = outer.find(f"{HP}tr/{HP}tc")
            cell.set("borderFillIDRef", no_border)
            cell.find(f"{HP}cellSz").set("width", str(whole_width))
            target = cell.find(f"{HP}subList")
            for child in list(target):
                target.remove(child)
            target.append(original)
            for row in list(outer.findall(f"{HP}tr"))[1:]:
                outer.remove(row)
            for child in list(parent):
                parent.remove(child)
            etree.SubElement(parent, f"{HP}run", charPrIDRef="0").append(outer)
            _set_paragraph_element_lineseg(parent, 1000, width=whole_width)
        for table in list(parent.findall(f".//{HP}tbl")):
            if table.get("rowCnt") != "1" or table.get("colCnt") != "1":
                continue
            base = table.find(f"{HP}tr/{HP}tc")
            sub = base.find(f"{HP}subList") if base is not None else None
            if sub is None or not any(fraction(t) for t in sub.findall(f".//{HP}tbl")):
                continue
            draw_outer_border = table.attrib.pop("nativeFractionBody", None) != "1"
            original_paragraphs = sub.findall(f"{HP}p")
            records = []
            maximum = 0
            for paragraph in original_paragraphs:
                fragments = []
                fractions = []
                buffer = []
                for run in paragraph.findall(f"{HP}run"):
                    for child in run:
                        if child.tag == f"{HP}tbl" and fraction(child):
                            fragments.append(part(paragraph, buffer))
                            buffer = []
                            fractions.append(child)
                        else:
                            clone = etree.Element(run.tag, dict(run.attrib))
                            clone.append(deepcopy(child))
                            buffer.append(clone)
                if not fractions:
                    records.append(("plain", deepcopy(paragraph)))
                    continue
                fragments.append(part(paragraph, buffer))
                # Preserve a long lead-in as its own full-width native line;
                # forcing it into a narrow fraction-side cell would add height.
                if text_width(fragments[0]) > 5000:
                    records.append(("plain", fragments[0]))
                    fragments[0] = part(paragraph, [])
                maximum = max(maximum, len(fractions))
                following = None
                if not draw_outer_border and text_width(fragments[-1]) > 5000:
                    sentences = first_sentence(fragments[-1])
                    if sentences:
                        fragments[-1], following = sentences
                records.append(("fraction", fragments, fractions))
                if following is not None:
                    records.append(("plain", following))
            if not maximum:
                raise ValueError(
                    "a word fraction is nested inside an unsupported source table structure"
                )
            col_count = maximum * 2 + 1
            width = int(table.find(f"{HP}sz").get("width"))
            widths = [200] * col_count
            for record in records:
                if record[0] != "fraction":
                    continue
                _, fragments, fractions = record
                for i, frac in enumerate(fractions):
                    widths[i * 2 + 1] = max(
                        widths[i * 2 + 1], max(
                            (sum(text_width(p) for p in cell.findall(f"{HP}subList/{HP}p"))
                             for cell in frac.findall(f"{HP}tr/{HP}tc")), default=0
                        ) + 200
                    )
                for i, fragment in enumerate(fragments):
                    widths[i * 2] = max(
                        widths[i * 2], min(5000, text_width(fragment) + 200)
                    )
            used = sum(widths[:-1])
            if sum(widths) > width:
                raise ValueError(
                    f"native word fractions do not fit their source view width: {sum(widths)} > {width} ({widths})"
                )
            widths[-1] = width - used
            rows = []
            source_fill = base.get("borderFillIDRef")
            template = deepcopy(base)

            def make_cell(pars, col, span=1, row_span=1, name=""):
                cell = deepcopy(template)
                cell.set("name", name)
                cell.set("hasMargin", "1")
                cell.find(f"{HP}cellAddr").set("colAddr", str(col))
                cs = cell.find(f"{HP}cellSpan")
                cs.set("colSpan", str(span))
                cs.set("rowSpan", str(row_span))
                size = cell.find(f"{HP}cellSz")
                cell_width = sum(widths[col : col + span])
                size.set("width", str(cell_width))
                margin = cell.find(f"{HP}cellMargin")
                for edge, value in (
                    ("left", 100),
                    ("right", 100),
                    ("top", 50),
                    ("bottom", 50),
                ):
                    margin.set(edge, str(value))
                target = cell.find(f"{HP}subList")
                for child in list(target):
                    target.remove(child)
                target.set("vertAlign", "CENTER" if row_span == 2 or name else "TOP")
                for par in pars:
                    par.set("id", paragraph_id())
                    target.append(par)
                height = sum(cache(par, cell_width) for par in pars) + 100
                return cell, max(200, round(height))

            def append_plain(paragraph, closing=False):
                cell, height = make_cell([paragraph], 0, col_count)
                if closing:
                    height = 200
                rows.append(([(cell, 0, col_count, False)], height))

            if draw_outer_border and records and records[0][0] == "fraction":
                append_plain(part(original_paragraphs[0], []), closing=True)
            for record in records:
                if record[0] == "plain":
                    append_plain(record[1])
                    continue
                _, fragments, fractions = record
                top = []
                bottom = []
                row_height = 200
                for i, frag in enumerate(fractions):
                    prefix, prefix_height = make_cell([fragments[i]], i * 2, row_span=2)
                    top.append((prefix, i * 2, 1, False))
                    row_height = max(row_height, (prefix_height + 1) // 2)
                    operands = frag.findall(f"{HP}tr/{HP}tc")
                    label = f"fraction:{frag.get('id')}"
                    for j, role in enumerate(("numerator", "denominator")):
                        pars = [
                            deepcopy(p)
                            for p in operands[j].findall(f"{HP}subList/{HP}p")
                        ]
                        cell, operand_height = make_cell(
                            pars, i * 2 + 1, name=f"{label}:{role}"
                        )
                        (top if j == 0 else bottom).append(
                            (
                                cell,
                                i * 2 + 1,
                                1,
                                operands[0].get("borderFillIDRef") if j == 0 else False,
                            )
                        )
                        row_height = max(row_height, operand_height)
                after_col = len(fractions) * 2
                suffix, suffix_height = make_cell(
                    [fragments[-1]], after_col, col_count - after_col, row_span=2
                )
                top.append((suffix, after_col, col_count - after_col, False))
                row_height = max(row_height, (suffix_height + 1) // 2)
                rows.extend([(top, row_height), (bottom, row_height)])
            # A short closing frame row keeps the denominator's fraction border
            # independent from the visible outer box border.
            if draw_outer_border:
                append_plain(part(original_paragraphs[-1], []), closing=True)
            for child in list(table.findall(f"{HP}tr")):
                table.remove(child)
            for row_index, (cells, row_height) in enumerate(rows):
                row = etree.SubElement(table, f"{HP}tr")
                for cell, col, span, numerator in cells:
                    cell.find(f"{HP}cellAddr").set("rowAddr", str(row_index))
                    row_span = int(cell.find(f"{HP}cellSpan").get("rowSpan"))
                    cell.find(f"{HP}cellSz").set("height", str(row_height * row_span))
                    edges = set()
                    if draw_outer_border:
                        if col == 0:
                            edges.add("left")
                        if col + span == col_count:
                            edges.add("right")
                        if row_index == 0:
                            edges.add("top")
                        if row_index + row_span == len(rows):
                            edges.add("bottom")
                    if numerator:
                        edges.add("bottom")
                    cell.set(
                        "borderFillIDRef",
                        borders(str(numerator) if numerator else source_fill, edges),
                    )
                    row.append(cell)
            table.set("rowCnt", str(len(rows)))
            table.set("colCnt", str(col_count))
            table.find(f"{HP}sz").set("height", str(sum(height for _, height in rows)))
            changed += 1
    fills.set("itemCnt", str(len(fills)))
    return changed
