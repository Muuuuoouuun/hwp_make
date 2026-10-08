"""Refresh edited, named question boxes before serialization.

Paragraph setters invalidate cached lines. Hancom can recalculate them, but
static readers need explicit caches; a fixed drawing box also needs its height
updated. Only our explicitly named question containers opt into this behavior.
"""

from __future__ import annotations

import re
import math
from lxml import etree
from hangul_units import hangul_clusters
from .paragraph_spacing import paragraph_spacing, paragraph_indentation, line_left_margin, paragraph_tab_stops
from .paragraph_floats import available_interval, is_wrapped_picture, wrapped_cell_layout
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


def cache_lines(paragraph, width, styles, para_styles, *, wrap_context=None, native_advance=None, leading=None):
    if native_advance is not None and wrap_context is None:
        from .native_line_cache import cache_lines_native
        if cache_lines_native(paragraph, width, styles, para_styles,
                              native_advance=native_advance, leading=leading):
            return
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
                underline = style.find(HH + "underline") if style is not None else None
                if text_value and text_value.isspace() and underline is not None and underline.get("type") == "BOTTOM":
                    # A measured answer blank is one flowing text unit. Keep
                    # the underline intact when its paragraph is edited.
                    advance = size * (.5 * number(ratio, "latin", 100)
                                      + number(spacing, "latin")) / 100 * len(text_value)
                    units.append((text_value, max(1, advance),
                                  len(text_value.encode("utf-16-le")) // 2, size))
                    continue
                for char in hangul_clusters(text_value):
                    language = "hangul" if ord(char[0]) > 255 else "latin"
                    # Conservative advances are deliberate for edited text:
                    # retain words where possible without overflowing a box.
                    factor = 1 if ord(char[0]) > 255 else (0.9 if char in "MW@%" else 0.6)
                    if char.isspace():
                        # The proved shared-wrap path must reserve a full
                        # half-em space when rebuilding edited text. Using
                        # the generic .35 estimate lets long Latin word rows
                        # cross the adjacent picture's actual ink edge.
                        factor = .5 if wrap_context is not None else .35
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
    wrapped = wrap_context is not None or any(is_wrapped_picture(o) for r in paragraph.findall(HP + "run") for o in r)
    margin_left, margin_right, indent = paragraph_indentation(paragraph, para_styles)
    tab_stops = paragraph_tab_stops(paragraph, para_styles)
    lines = []
    start = 0
    top = 0
    while start < len(units):
        height = max(1, units[start][3])
        if wrapped:
            height = max((u[3] for u in units[start:] if u[3]), default=1000)
        if wrap_context is not None:
            exclusions, paragraph_top = wrap_context
            left,available=available_interval(paragraph,width,paragraph_top+top,height,exclusions=exclusions)
        else:
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
    from .native_gap_state import step as native_gap_step
    for index,(line, left, available, height, step) in enumerate(lines):
        step = native_gap_step(height,step,index,len(lines),leading)
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
            horzsize=str(round(available-line_left_margin(margin_left,indent,index)-margin_right
                               if wrap_context is not None else available)),
            flags="393216",
        )
        offset += sum(u[2] for u in line)
        top += step


def update_positions(container, para_styles=None):
    from .ruled_grid_flow import preserve_positions
    grid_height = preserve_positions(container, para_styles)
    if grid_height is not None:
        return grid_height
    cell=container.getparent()
    measured=wrapped_cell_layout(cell,para_styles) if cell is not None and cell.tag==HP+'tc' else None
    if measured is not None:
        for paragraph,start in zip(measured['paragraphs'],measured['starts']):
            for line in paragraph.findall(HP+'linesegarray/'+HP+'lineseg'):
                line.set('vertpos',str(round(start)))
                start+=number(line,'vertsize')+number(line,'spacing')
        return measured['height']-measured['top']-measured['bottom']
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


def reflow_wrapped_table(table, missing, styles, para_styles):
    """Reflow one proved native wrap cell; other tables retain grow-only flow."""
    cells=table.findall(HP+'tr/'+HP+'tc')
    if len(cells)!=1: return False
    cell=cells[0]
    measured=wrapped_cell_layout(cell,para_styles,allow_missing=True,char_styles=styles)
    if measured is None or not any(p in measured['paragraphs'] for p in missing): return False
    # Stage all geometry so malformed or impossible masks cannot partially
    # mutate a package. The picture remains inside its original semantic p.
    from copy import deepcopy
    staged=deepcopy(table)
    target=staged.find(HP+'tr/'+HP+'tc')
    from .wrapped_flow_state import restore_cached_cell
    source_cache_restored=restore_cached_cell(target,para_styles,styles)
    original=measured['paragraphs']; paragraphs=target.findall(HP+'subList/'+HP+'p')
    dirty=set() if source_cache_restored else {i for i,p in enumerate(original) if p in missing}
    width=measured['width']; cursor=0; floats=[]
    for index,p in enumerate(paragraphs):
        before,after=paragraph_spacing(p,para_styles); cursor+=before; start=cursor
        for run in p.findall(HP+'run'):
            for pic in run:
                if not is_wrapped_picture(pic): continue
                pos,size,margin=(pic.find(HP+k) for k in ('pos','sz','outMargin'))
                x,y=number(pos,'horzOffset'),number(pos,'vertOffset')
                floats.append((x-number(margin,'left'),start+y-number(margin,'top'),
                               x+number(size,'width')+number(margin,'right'),
                               start+y+number(size,'height')+number(margin,'bottom')))
        lines=p.findall(HP+'linesegarray/'+HP+'lineseg')
        margin_left,margin_right,indent=paragraph_indentation(p,para_styles)
        refresh=index in dirty
        local=0
        for line_index,line in enumerate(lines):
            left,available=available_interval(p,width,start+local,number(line,'vertsize'),exclusions=floats)
            effective=available-line_left_margin(margin_left,indent,line_index)-margin_right
            if left!=number(line,'horzpos') or effective<number(line,'horzsize')-2: refresh=True
            local+=number(line,'vertsize')+number(line,'spacing')
        if refresh:
            cache_lines(p,width,styles,para_styles,wrap_context=(floats,start))
            lines=p.findall(HP+'linesegarray/'+HP+'lineseg')
            lines[-1].set('spacing','0')
        for line_index,line in enumerate(lines):
            left,available=available_interval(p,width,cursor,number(line,'vertsize'),exclusions=floats)
            effective=available-line_left_margin(margin_left,indent,line_index)-margin_right
            if effective<=0: return False
            line.set('horzpos',str(round(left)));line.set('horzsize',str(round(effective)))
            line.set('vertpos',str(round(cursor)))
            cursor+=number(line,'vertsize')+number(line,'spacing')
        cursor+=after
    height=round(measured['top']+max([cursor]+[r[3] for r in floats])+measured['bottom'])
    target.find(HP+'cellSz').set('height',str(height));staged.find(HP+'sz').set('height',str(height))
    if wrapped_cell_layout(target,para_styles,char_styles=styles) is None: return False
    table.attrib.clear();table.attrib.update(staged.attrib)
    for child in list(table): table.remove(child)
    table.extend(staged)
    owner=table.getparent().getparent()
    # Keep the ordinary table-object reserve. The Square picture itself has
    # already occupied the cell's maximum extent exactly once.
    if owner.tag==HP+'p' and not any((t.text or '').strip() for t in owner.findall(HP+'run/'+HP+'t')):
        old=owner.find(HP+'linesegarray')
        if old is not None: owner.remove(old)
        cache=etree.SubElement(owner,HP+'linesegarray')
        etree.SubElement(cache,HP+'lineseg',textpos='0',vertpos='0',vertsize=str(height+400),
            textheight=str(height+400),baseline=str(round((height+400)*.85)),spacing='0',horzpos='0',
            horzsize=table.find(HP+'sz').get('width'),flags='393216')
    return True


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


def existing_question_reserve(draw, missing, para_styles):
    """Retain a measured wrapper reserve when only its table cells changed.

    Direct paragraph caches and native object sizes still describe the old
    question at this point. A missing direct cache cannot establish its old
    occupied height, so that path keeps the normal 400-unit reserve.
    """
    sub = draw.find(HP + "subList")
    if sub is None or not missing:
        return 400
    for paragraph in missing:
        nested_table = False
        for ancestor in paragraph.iterancestors():
            if ancestor is draw:
                break
            nested_table |= ancestor.tag == HP + "tbl"
        if not nested_table:
            return 400
    paragraphs = sub.findall(HP + "p")
    if not paragraphs or any(p.find(HP + "linesegarray/" + HP + "lineseg") is None for p in paragraphs):
        return 400
    try:
        margins = draw.find(HP + "textMargin")
        insets = [number(margins, edge) for edge in ("left", "right", "top", "bottom")]
        wrapper_height = number(draw.getparent().find(HP + "sz"), "height")
        text_height = number(sub, "textHeight")
        if (not all(math.isfinite(v) and v >= 0 for v in insets)
            or not math.isfinite(wrapper_height) or not math.isfinite(text_height)
            or min(wrapper_height, text_height) <= 0
            or abs(wrapper_height - insets[2] - insets[3] - text_height) > 1):
            return 400
        for paragraph in paragraphs:
            for line in paragraph.findall(HP + "linesegarray/" + HP + "lineseg"):
                values = [number(line, key) for key in ("vertsize", "textheight", "baseline", "spacing")]
                height, textheight, baseline, spacing = values
                if (not all(math.isfinite(v) for v in values)
                    or not 0 <= baseline < textheight <= height or spacing < 0):
                    return 400
        reserved = text_height - sum(flow_height(p) + sum(paragraph_spacing(p, para_styles)) for p in paragraphs)
        return reserved if math.isfinite(reserved) and 0 <= reserved <= 400 else 400
    except (TypeError, ValueError, AttributeError):
        return 400


def refresh_question_layout(document):
    """Mutate only question flows with invalidated paragraph caches."""
    if not document.headers:
        return 0
    header = document.headers[0].element
    styles = {p.get("id"): p for p in header.iter(HH + "charPr")}
    paras = {p.get("id"): p for p in header.iter(HH + "paraPr")}
    refreshed = 0
    native_backend = None
    native_budget = None
    native_context = None
    native_context_attempted = False
    general_contexts = []
    gap_contexts = []
    from . import native_gap_state as native_gaps

    def current_native_advance(paragraph):
        nonlocal native_backend, native_budget, native_context, native_context_attempted
        if (paragraph.find(HP + "linesegarray") is not None
            or paragraph.find(HP + "run/" + HP + "tab") is None):
            return None
        try:
            if native_backend is None:
                from . import native_line_metrics as native_backend
            # Do not create a header/native context for wrapped or unsupported
            # paragraphs; the backend's exact plain LEFT-TAB proof owns this.
            if native_backend.plain_units(paragraph, header) is None:
                return None
            if native_budget is None:
                native_budget = native_backend.ProbeBudget()
            if not native_context_attempted:
                native_context_attempted = True
                native_context = native_backend.optional_native_context(
                    header, budget=native_budget)
            return (native_context.for_paragraph(paragraph)
                    if native_context is not None else None)
        except Exception:
            return None

    for section in document.sections:
        root = section.element
        changed = False
        original_slots = {}
        slot = 0
        if not any(
            QUESTION.fullmatch(d.get("name", "")) for d in root.iter(HP + "drawText")
        ):
            continue
        # Spacing may add/change header styles after each section. Renew the
        # lazy current-header context, retaining one budget for this refresh.
        native_context = None
        native_context_attempted = False
        # Keep measured caches that were not invalidated by a text setter.
        section._preserve_question_layout_caches = True
        from .wrapped_flow_state import begin as begin_wrapped_flow, finish as finish_wrapped_flow
        wrapped_flow=begin_wrapped_flow(root,paras,styles)
        from .ruled_grid_flow import begin as begin_grid_flow, apply as apply_grid_flow, finish as finish_grid_flow
        grid_flow = begin_grid_flow(root, paras, styles)
        from .general_flow_state import begin as begin_general_flow
        general_flow = begin_general_flow(document, section, wrapped_flow, grid_flow)
        gap_flow = native_gaps.begin(document,section,general_flow)
        for p in root.findall(HP + "p"):
            if p.get("pageBreak") == "1":
                slot += 2 - slot % 2
            elif p.get("columnBreak") == "1":
                slot += 1
            original_slots[p] = slot
        if wrapped_flow is not None:
            original_slots=wrapped_flow['slots']
        if grid_flow is not None:
            original_slots=grid_flow['slots']
        if general_flow is not None:
            original_slots=general_flow['slots']
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
                cache_lines(p, current_width, styles, paras,
                            native_advance=current_native_advance(p), leading=native_gaps.policy(gap_flow,p))
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
                cache_lines(p, max(500, width), styles, paras,
                            native_advance=current_native_advance(p), leading=native_gaps.policy(gap_flow,p))
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
                    or (grid_flow is not None and p in grid_flow['dirty'])
                )
            ]
            if not missing:
                continue
            reserve = (gap_flow['reserves'][draw] if gap_flow is not None and draw in gap_flow['reserves']
                       else existing_question_reserve(draw, missing, paras))
            width = number(draw, "lastWidth", 20000)
            for p in missing:
                if grid_flow is not None and p in grid_flow['dirty']:
                    continue
                cell=next((a for a in p.iterancestors() if a.tag==HP+'tc'),None)
                if cell is not None and wrapped_cell_layout(cell,paras,allow_missing=True,char_styles=styles) is not None:
                    continue
                available = paragraph_container_width(p, width)
                cache_lines(p, max(500, available), styles, paras,
                            native_advance=current_native_advance(p), leading=native_gaps.policy(gap_flow,p))
            # Grow affected rows without changing cell ownership or spans.
            for table in reversed(draw.findall(".//" + HP + "tbl")):
                if not any(table in p.iterancestors() for p in missing):
                    continue
                if apply_grid_flow(table, grid_flow):
                    continue
                if reflow_wrapped_table(table,missing,styles,paras):
                    continue
                from .table_reflow import fit_table_rows
                fit_table_rows(table, lambda p: flow_height(p) + sum(paragraph_spacing(p, paras)), grow_only=True)
            for sub in reversed(draw.findall(".//" + HP + "subList")):
                update_positions(sub, paras)
            sub = draw.find(HP + "subList")
            text_height = round(sum(flow_height(p) + sum(paragraph_spacing(p, paras))
                                    for p in sub.findall(HP + "p")) + reserve)
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
            if (before and cursor + height > limit
                and not (gap_flow is not None and height <= capacity)
                and (grid_flow is None and (wrapped_flow is None or wrapped_flow['state'].get('v')!=2)
                     or height > capacity)):
                # Match initial source pagination: when edited content no
                # longer fits with its measured blank area, consume that area
                # before moving a complete question to the next column.
                spacing_styles.set(p, 0, after)
                document.headers[0].mark_dirty()
                height -= before
            # A fully proved wrapped-cell edit keeps the existing native gap
            # when the following question and gap fit an empty column. This
            # lets deletion repaginate back to the original spacing. General
            # edits and gaps too large for an empty column keep the ordinary
            # consume-before policy above; no source gap is reconstructed.
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
            if general_flow is not None:
                from .general_flow_state import preserve_manual_flags
                preserve_manual_flags(p, prior, slot, general_flow)
            cursor += height
        if arrange_question_gaps(root, header):
            document.headers[0].mark_dirty()
        paras = {p.get("id"): p for p in header.iter(HH + "paraPr")}
        update_positions(root, paras)
        finish_wrapped_flow(root,wrapped_flow,paras,styles)
        finish_grid_flow(root, grid_flow)
        section.mark_dirty()
        if general_flow is not None:
            general_contexts.append(general_flow)
        if gap_flow is not None:
            gap_contexts.append(gap_flow)
    from .general_flow_state import commit as commit_general_flow
    general_committed = commit_general_flow(document, general_contexts)
    native_gaps.commit(document,gap_contexts,general_committed)
    return refreshed
