"""Refresh edited, named question boxes before serialization.

Paragraph setters invalidate cached lines. Hancom can recalculate them, but
static readers need explicit caches; a fixed drawing box also needs its height
updated. Only our explicitly named question containers opt into this behavior.
"""

from __future__ import annotations

import re
from lxml import etree
from hangul_units import hangul_clusters
from .paragraph_spacing import paragraph_spacing, paragraph_indentation, line_left_margin, paragraph_tab_stops
from .paragraph_floats import available_interval, is_wrapped_picture
from hwpx_text_content import iter_text_parts

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"
QUESTION = re.compile(r"question:v\d+:q\d{2}$")
OBJECTS = {HP + x for x in ("equation", "tbl", "pic", "rect", "container")}


def number(node, name, default=0):
    return float(node.get(name, default)) if node is not None else float(default)


def flow_height(paragraph):
    lines = paragraph.findall(HP + "linesegarray/" + HP + "lineseg")
    height = sum(number(line, "vertsize", 1000) + number(line, "spacing") for line in lines)
    objects = [
        number(o.find(HP + "sz"), "height")
        + (number(o.find(HP + "pos"), "vertOffset") if is_wrapped_picture(o) else 0)
        + (0 if o.tag == HP + "rect" and o.find(HP + "drawText") is not None else 400)
        for r in paragraph.findall(HP + "run")
        for o in r
        if o.tag in OBJECTS
    ]
    return max([height, 1] + objects)


def cache_lines(paragraph, width, styles, para_styles):
    units = []
    tabs = {}
    for run in paragraph.findall(HP + "run"):
        style = styles.get(run.get("charPrIDRef"))
        size = number(style, "height", 1000)
        ratio = style.find(HH + "ratio") if style is not None else None
        spacing = style.find(HH + "spacing") if style is not None else None
        content = []
        for child in run:
            if child.tag == HP + 't':
                content.extend((control if control is not None and control.tag in {HP + 'lineBreak', HP + 'tab'} else None, value)
                               for value, control in iter_text_parts(child))
            else:
                content.append((child, None))
        for child, value in content:
            if child is None:
                text_value = value
            elif child.tag == HP + 't':
                text_value = child.text or ''
            else:
                text_value = None
            if text_value is not None:
                for char in hangul_clusters(text_value):
                    language = "hangul" if ord(char[0]) > 255 else "latin"
                    # Conservative advances are deliberate for edited text:
                    # retain words where possible without overflowing a box.
                    factor = 1 if ord(char[0]) > 255 else (0.9 if char in "MW@%" else 0.6)
                    if char.isspace():
                        factor = 0.35
                    advance = (
                        size
                        * (
                            factor * number(ratio, language, 100)
                            + number(spacing, language)
                        )
                        / 100
                    )
                    units.append(
                        (
                            char,
                            max(1, advance),
                            len(char.encode("utf-16-le")) // 2,
                            size,
                        )
                    )
            elif child.tag in OBJECTS:
                if is_wrapped_picture(child):
                    # The anchor occupies eight UTF-16 control units, but its
                    # square-wrapped picture is outside the text line itself.
                    units.append(("\ufffc", 0, 8, 0))
                    continue
                bounds = child.find(HP + "sz")
                units.append(
                    (
                        "\ufffc",
                        number(bounds, "width", size),
                        8,
                        max(
                            size,
                            number(bounds, "height"),
                            number(child, "baseUnit") * 1.5,
                        ),
                    )
                )
            elif child.tag in {HP + "tab", HP + "lineBreak"}:
                if child.tag == HP + "tab":
                    tabs[len(units)] = child
                units.append(
                    ("\n" if child.tag == HP + "lineBreak" else "\t", 0 if child.tag == HP + "lineBreak" else size * 2,
                     1 if child.tag == HP + "lineBreak" else 8, size)
                )
    if not units:
        units = [("", 0, 0, 1000)]
    style = para_styles.get(paragraph.get("paraPrIDRef"))
    spacing = style.find(".//" + HH + "lineSpacing") if style is not None else None
    percent = (
        number(spacing, "value", 150)
        if spacing is None or spacing.get("type") == "PERCENT"
        else 150
    )
    wrapped = any(is_wrapped_picture(o) for r in paragraph.findall(HP + "run") for o in r)
    margin_left, margin_right, indent = paragraph_indentation(paragraph, para_styles)
    tab_stops = paragraph_tab_stops(paragraph, para_styles)
    lines = []
    start = 0
    top = 0
    while start < len(units):
        height = max(1, units[start][3])
        if wrapped:
            height = max((u[3] for u in units[start:] if u[3]), default=1000)
        left, available = available_interval(paragraph, width, top, height) if wrapped else (0, width)
        usable = available - line_left_margin(margin_left, indent, len(lines)) - margin_right
        if usable <= 0:
            raise ValueError("Paragraph indentation leaves no room for editable text")
        end = start
        advance = 0
        space = None
        def unit_width(index, used):
            if index in tabs and tab_stops:
                current = line_left_margin(margin_left, indent, len(lines)) + used
                stop = next((stop for stop in tab_stops if stop > current + 1),
                            (int(current // 3600) + 1) * 3600)
                return max(1, stop - current)
            return units[index][1]

        while end < len(units):
            amount = unit_width(end, advance)
            if end > start and advance + amount > usable * .97:
                break
            char = units[end][0]
            advance += amount
            end += 1
            if char == "\n":
                break
            if char.isspace():
                space = end
        if end < len(units) and units[end - 1][0] != "\n" and space and space > start:
            end = space
        advance = 0
        for index in range(start, end):
            amount = unit_width(index, advance)
            if index in tabs:
                tabs[index].set("width", str(min(65535, round(amount))))
            advance += amount
        line = units[start:end]
        height = max(1, max(u[3] for u in line))
        step = max(height, height * percent / 100)
        lines.append((line, left, available, height, step))
        top += step
        start = end
    old = paragraph.find(HP + "linesegarray")
    if old is not None:
        paragraph.remove(old)
    cache = etree.SubElement(paragraph, HP + "linesegarray")
    offset = top = 0
    for line, left, available, height, step in lines:
        etree.SubElement(
            cache,
            HP + "lineseg",
            textpos=str(offset),
            vertpos=str(round(top)),
            vertsize=str(round(height)),
            textheight=str(round(height)),
            baseline=str(round(height * 0.85)),
            spacing=str(round(step - height)),
            horzpos=str(round(left)),
            horzsize=str(round(available)),
            flags="393216",
        )
        offset += sum(u[2] for u in line)
        top += step


def update_positions(container, para_styles=None):
    cursor = 0
    for p in container.findall(HP + "p"):
        if (
            p.get("pageBreak") == "1"
            or p.get("columnBreak") == "1"
            or p.find(".//" + HP + "colPr") is not None
        ):
            cursor = 0
        before, after = paragraph_spacing(p, para_styles)
        cursor += before
        start = cursor
        for line in p.findall(HP + "linesegarray/" + HP + "lineseg"):
            line.set("vertpos", str(round(cursor)))
            cursor += number(line, "vertsize", 1000) + number(line, "spacing")
        cursor = max(cursor, start + flow_height(p))
        cursor += after
    return cursor


def paragraph_container_width(paragraph, fallback):
    """Use the nearest text container when rebuilding an edited paragraph.

    A textbox inside a table cell owns its own text width. Using the outer
    cell width shifts centered labels and lets longer replacements overflow
    their editable shape even though the XML text survives the edit.
    """
    for ancestor in paragraph.iterancestors():
        if ancestor.tag == HP + "drawText":
            margins = ancestor.find(HP + "textMargin")
            return (number(ancestor, "lastWidth", fallback)
                    - number(margins, "left") - number(margins, "right"))
        if ancestor.tag == HP + "tc":
            margins = ancestor.find(HP + "cellMargin")
            return (number(ancestor.find(HP + "cellSz"), "width", fallback)
                    - number(margins, "left") - number(margins, "right") - 200)
    return fallback


def refresh_question_layout(document):
    """Mutate only question flows with invalidated paragraph caches."""
    if not document.headers:
        return 0
    header = document.headers[0].element
    styles = {p.get("id"): p for p in header.iter(HH + "charPr")}
    paras = {p.get("id"): p for p in header.iter(HH + "paraPr")}
    refreshed = 0
    for section in document.sections:
        root = section.element
        changed = False
        original_slots = {}
        slot = 0
        if not any(
            QUESTION.fullmatch(d.get("name", "")) for d in root.iter(HP + "drawText")
        ):
            continue
        # Keep measured caches that were not invalidated by a text setter.
        section._preserve_question_layout_caches = True
        for p in root.findall(HP + "p"):
            if p.get("pageBreak") == "1":
                slot += 2 - slot % 2
            elif p.get("columnBreak") == "1":
                slot += 1
            original_slots[p] = slot
        page = root.find(".//" + HP + "pagePr")
        margins = page.find(HP + "margin") if page is not None else None
        columns = next((c for c in root.iter(HP + "colPr") if c.get("colCount") == "2"), None)
        column_width = (number(page, "width", 59528) - number(margins, "left", 5669)
                        - number(margins, "right", 5669) - number(columns, "sameGap")) / 2
        current_width = column_width
        for p in root.findall(HP + "p"):
            # Shared passages are ordinary section paragraphs. They need the
            # same edit/reflow contract as paragraphs inside a question box;
            # otherwise readers can lay them out across both columns.
            column_change = p.find(HP + "run/" + HP + "ctrl/" + HP + "colPr")
            if column_change is not None:
                count = max(1, number(column_change, "colCount", 1))
                current_width = (number(page, "width", 59528)
                                 - number(margins, "left", 5669)
                                 - number(margins, "right", 5669)
                                 - (count - 1) * number(column_change, "sameGap")) / count
            if (p.find(HP + "linesegarray") is None
                and (any((t.text or "").strip() for t in p.findall(HP + "run/" + HP + "t"))
                     or any(o.tag in OBJECTS for r in p.findall(HP + "run") for o in r))):
                cache_lines(p, current_width, styles, paras)
                changed = True
                refreshed += 1
        # Shared passage frames are ordinary section tables, outside the
        # named question rectangles. Editing their cell paragraphs must also
        # invalidate/rebuild the cell cache and grow the table in document
        # flow, while retaining native paragraph margins and indentation.
        for table in root.findall(HP + 'p/' + HP + 'run/' + HP + 'tbl'):
            missing = [p for p in table.iter(HP + 'p')
                       if p.find(HP + 'linesegarray') is None
                       and (any((t.text or '').strip() for t in p.findall(HP + 'run/' + HP + 't'))
                            or any(o.tag in OBJECTS for r in p.findall(HP + 'run') for o in r))]
            if not missing:
                continue
            for p in missing:
                width = paragraph_container_width(p, column_width)
                cache_lines(p, max(500, width), styles, paras)
            from .table_reflow import fit_table_rows
            for nested in reversed([table, *table.findall('.//' + HP + 'tbl')]):
                if any(nested in p.iterancestors() for p in missing):
                    fit_table_rows(nested, lambda p: flow_height(p) + sum(paragraph_spacing(p, paras)), grow_only=True)
            for sub in reversed(table.findall('.//' + HP + 'subList')):
                update_positions(sub, paras)
            changed = True
            refreshed += len(missing)
        for draw in root.iter(HP + "drawText"):
            if not QUESTION.fullmatch(draw.get("name", "")):
                continue
            missing = [
                p
                for p in draw.iter(HP + "p")
                if p.find(HP + "linesegarray") is None
                and (
                    any(
                        (t.text or "").strip()
                        for t in p.findall(HP + "run/" + HP + "t")
                    )
                    or any(o.tag in OBJECTS for r in p.findall(HP + "run") for o in r)
                )
            ]
            if not missing:
                continue
            width = number(draw, "lastWidth", 20000)
            for p in missing:
                available = paragraph_container_width(p, width)
                cache_lines(p, max(500, available), styles, paras)
            # Grow affected rows without changing cell ownership or spans.
            for table in reversed(draw.findall(".//" + HP + "tbl")):
                if not any(table in p.iterancestors() for p in missing):
                    continue
                from .table_reflow import fit_table_rows
                fit_table_rows(table, lambda p: flow_height(p) + sum(paragraph_spacing(p, paras)), grow_only=True)
            for sub in reversed(draw.findall(".//" + HP + "subList")):
                update_positions(sub, paras)
            sub = draw.find(HP + "subList")
            text_height = round(sum(flow_height(p) + sum(paragraph_spacing(p, paras))
                                    for p in sub.findall(HP + "p")) + 400)
            text_margin = draw.find(HP + 'textMargin')
            height = round(text_height + number(text_margin, 'top') + number(text_margin, 'bottom'))
            from .question_spacing import resize_question_box
            resize_question_box(draw.getparent(), height)
            changed = True
            refreshed += len(missing)
        if not changed:
            continue
        from .question_spacing import arrange_question_gaps, ParagraphSpacingStyles
        if arrange_question_gaps(root, header, before_pagination=True):
            document.headers[0].mark_dirty()
        spacing_styles = ParagraphSpacingStyles(header)
        paras = spacing_styles.styles
        capacity = (
            number(page, "height", 84188)
            - number(margins, "top", 5669)
            - number(margins, "bottom", 5102)
            - number(margins, "header")
            - number(margins, "footer")
            - 1400
        )
        all_p = root.findall(HP + "p")
        first = next(
            i
            for i, p in enumerate(all_p)
            if p.find(".//" + HP + "drawText") is not None
            or any(c.get("colCount") == "2" for c in p.iter(HP + "colPr"))
        )
        masthead = sum(flow_height(p) + sum(paragraph_spacing(p, paras)) for p in all_p[:first])
        slot = 0
        cursor = 0
        for p in all_p[first:]:
            prior = slot
            slot = max(slot, original_slots[p])
            cursor = 0 if slot != prior else cursor
            before, after = paragraph_spacing(p, paras)
            height = flow_height(p) + before + after
            limit = capacity - (masthead if slot < 2 else 0)
            if before and cursor + height > limit:
                # Match initial source pagination: when edited content no
                # longer fits with its measured blank area, consume that area
                # before moving a complete question to the next column.
                spacing_styles.set(p, 0, after)
                document.headers[0].mark_dirty()
                height -= before
            if height > capacity:
                raise ValueError(
                    "Edited question cannot fit on one page without splitting its container"
                )
            if height > limit and slot < 2:
                slot = 2
                cursor = 0
            elif cursor and cursor + height > limit:
                slot += 1
                cursor = 0
            p.set("pageBreak", "1" if slot // 2 > prior // 2 else "0")
            p.set(
                "columnBreak", "1" if slot > prior and slot // 2 == prior // 2 else "0"
            )
            cursor += height
        if arrange_question_gaps(root, header):
            document.headers[0].mark_dirty()
        paras = {p.get("id"): p for p in header.iter(HH + "paraPr")}
        update_positions(root, paras)
        section.mark_dirty()
    return refreshed
