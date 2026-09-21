"""Preserve measured source whitespace using editable paragraph margins."""
from copy import deepcopy
from statistics import median
from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"


def apply_source_column_rails(section, items):
    """Map source column starts to native page margins and column spacing."""
    page = section.find(".//" + HP + "pagePr")
    if page is None:
        return False
    margin = page.find(HP + "margin")
    columns = [c for c in section.iter(HP + "colPr") if c.get("colCount") == "2"]
    if margin is None or not columns:
        return False
    rails = {1: {}, 2: {}}
    for item in items:
        layout = item.get("layout") or {}
        column = int(layout.get("source_column") or 0)
        left = layout.get("column_left_pt")
        width = layout.get("source_page_width_pt")
        if column in rails and left is not None and width:
            rails[column][int(item.get("source_page") or 1)] = float(left) / float(width)
    if not all(rails.values()):
        return False
    page_width = float(page.get("width"))
    left, second = [median(rails[c].values()) * page_width for c in (1, 2)]
    old_gap = float(columns[0].get("sameGap", "2268"))
    column_width = (page_width - float(margin.get("left")) - float(margin.get("right")) - old_gap) / 2
    gap = second - left - column_width
    right = page_width - second - column_width
    if min(left, right, gap) < 0 or gap > page_width * .15:
        return False
    margin.set("left", str(round(left)))
    margin.set("right", str(round(right)))
    for column in columns:
        column.set("sameGap", str(round(gap)))
    return True


def source_anchor(layouts):
    first = layouts[0]
    page, column = int(first.get("source_page") or 1), int(first.get("source_column") or 1)
    bounds = []
    for layout in layouts:
        if (int(layout.get("source_page") or 1), int(layout.get("source_column") or 1)) != (page, column):
            continue
        box = layout.get("source_bbox_pt") or (layout.get("source_typography") or {}).get("source_bbox_pt")
        if box and len(box) == 4:
            bounds.append(box)
        else:
            bounds.extend(t["bbox_pt"] for t in layout.get("native_tables", []) if t.get("bbox_pt"))
    if not bounds:
        return None
    return (page, column, min(float(b[1]) for b in bounds), float(first.get("source_page_width_pt") or 842))


def set_space_before(paragraph, header, amount):
    _set_paragraph_space(paragraph, header, "prev", amount)


def set_space_after(paragraph, header, amount):
    _set_paragraph_space(paragraph, header, "next", amount)


def _set_paragraph_space(paragraph, header, edge_name, amount):
    properties = header.find(".//" + HH + "paraProperties")
    styles = {p.get("id"): p for p in properties}
    base = styles[paragraph.get("paraPrIDRef")]
    copied = deepcopy(base)
    identifier = str(max(map(int, styles)) + 1)
    copied.set("id", identifier)
    for margin in copied.findall(".//" + HH + "margin"):
        before = margin.find(HC + edge_name)
        if before is None:
            before = etree.SubElement(margin, HC + edge_name)
        before.set("value", str(round(max(0, amount))))
        before.set("unit", "HWPUNIT")
    properties.append(copied)
    properties.set("itemCnt", str(len(properties)))
    paragraph.set("paraPrIDRef", identifier)


def source_paragraph_top(paragraph, layout, page_width):
    """Align native text to source baselines, objects to their actual bounds."""
    anchor = source_anchor([layout])
    if anchor is None:
        return None
    scale = page_width / anchor[3]
    records = (layout.get("source_typography") or {}).get("lines") or []
    cache = paragraph.find(HP + "linesegarray/" + HP + "lineseg")
    if records and cache is not None and any(
        (t.text or "").strip() for t in paragraph.findall(HP + "run/" + HP + "t")
    ) and not any(paragraph.find(HP + "run/" + HP + tag) is not None
                  for tag in ("tbl", "rect", "pic")):
        return float(records[0]["baseline_pt"]) * scale - float(cache.get("baseline", "0"))
    return anchor[2] * scale


def apply_question_internal_spacing(entries, header, page_width):
    """Restore source gaps between semantic paragraphs inside one question.

    Use ordinary after-paragraph spacing. It participates in editing/reflow;
    no empty lines, separate line boxes, or fixed paragraph offsets are added.
    """
    from .pdf_native_typography import _flow_height
    from hwpx.tools.paragraph_spacing import paragraph_spacing

    styles = {p.get("id"): p for p in header.iter(HH + "paraPr")}
    first_anchor = source_anchor([entries[0][1]])
    if first_anchor is None:
        return

    def target_top(paragraph, layout):
        anchor = source_anchor([layout])
        if anchor is None or anchor[:2] != first_anchor[:2]:
            return None
        return source_paragraph_top(paragraph, layout, page_width)

    origin = target_top(*entries[0])
    if origin is None:
        return
    cursor = 0
    previous = None
    for paragraph, layout in entries:
        before, after = paragraph_spacing(paragraph, styles)
        target = target_top(paragraph, layout)
        extra = max(0, target - origin - cursor - before) if target is not None else 0
        if previous is not None and extra >= 1:
            _, old_after = paragraph_spacing(previous, styles)
            set_space_after(previous, header, old_after + extra)
            cursor += extra
        cursor += before + _flow_height(paragraph) + after
        previous = paragraph


def apply_source_flow_spacing(section, paragraphs, layouts, header):
    from .pdf_native_typography import _flow_height, _number
    from hwpx.tools.paragraph_spacing import paragraph_spacing

    if not paragraphs:
        return
    # The column switch is a control, not a blank body line. Keeping it in a
    # separate empty paragraph displaced only the first (left) column.
    first = paragraphs[0]
    for previous in list(section)[:section.index(first)]:
        controls = previous.findall(f"{HP}run/{HP}ctrl")
        if (not controls or previous.find(".//" + HP + "secPr") is not None
            or not any(c.find(HP + "colPr") is not None and c.find(HP + "colPr").get("colCount") == "2" for c in controls)
            or any((t.text or "").strip() for t in previous.iter(HP + "t"))
            or any(previous.find(".//" + HP + tag) is not None for tag in ("pic", "tbl", "rect", "equation"))):
            continue
        run = first.find(HP + "run")
        for control in reversed(controls):
            run.insert(0, control)
        section.remove(previous)
    page = section.find(".//" + HP + "pagePr")
    if page is None:
        return
    margin = page.find(HP + "margin")
    styles = {p.get("id"): p for p in header.iter(HH + "paraPr")}
    prologue = []
    for p in section.findall(HP + "p"):
        if p is paragraphs[0]:
            break
        prologue.append(p)
    header_height = sum(_flow_height(p) + sum(paragraph_spacing(p, styles)) for p in prologue)
    first_page = int(layouts[0][0].get("source_page") or 1)
    cursors = {}
    for paragraph, entries in zip(paragraphs, layouts):
        first = entries[0]
        group = (int(first.get("source_page") or 1), int(first.get("source_column") or 1))
        # Following pages receive a separate section margin below. Do not
        # clamp their leading gaps against the taller first-page masthead.
        initial = _number(margin, "top")
        if group[0] == first_page:
            initial += _number(margin, "header") + header_height
        cursor = cursors.get(group, initial)
        anchor = source_anchor(entries)
        before, after = paragraph_spacing(paragraph, styles)
        if anchor is not None:
            target = anchor[2] * _number(page, "width") / anchor[3]
            # A whole-question box begins with its first native paragraph.
            # Font bounding-box ascenders differ from HWP's cache baseline;
            # anchoring the box to the PDF ink top shifts every object in it.
            body = paragraph.find(HP + 'run/' + HP + 'rect/' + HP + 'drawText/' + HP + 'subList/' + HP + 'p')
            if body is None:
                body = paragraph
            if source_anchor([first]) == anchor:
                measured = source_paragraph_top(body, first, _number(page, 'width'))
                if measured is not None:
                    target = measured
            before = max(0, target - cursor)
            set_space_before(paragraph, header, before)
        cursors[group] = cursor + before + _flow_height(paragraph) + after


def split_masthead_section(section, paragraphs, source_groups, paragraph_sources, header):
    """Give following pages their real top margin, independent of page-one title.

    Leading paragraph spacing is normally suppressed at a page/column break.
    A native section margin is therefore required for the running body offset.
    Content remains ordinary flowing question paragraphs in both sections.
    """
    from hwpx.tools.paragraph_spacing import paragraph_spacing
    from .pdf_native_typography import _number, _paginate

    if not paragraphs:
        return None
    first_page = int(source_groups[0][0])
    boundary = next((i for i, group in enumerate(source_groups) if group[0] > first_page), None)
    if boundary is None:
        return None
    page = section.find(".//" + HP + "pagePr")
    page_width = _number(page, "width")
    first_anchors = {}
    for paragraph, layout in paragraph_sources:
        anchor = source_anchor([layout])
        if anchor and anchor[0] > first_page:
            group = anchor[:2]
            top = source_paragraph_top(paragraph, layout, page_width)
            first_anchors[group] = min(first_anchors.get(group, float("inf")), top / page_width)
    if not first_anchors:
        return None
    margin = page.find(HP + "margin")
    # A taller equation on the first line needs an earlier paragraph top even
    # when its baseline matches a neighbouring plain-text column. The median
    # clips these earlier starts because ordinary before-spacing cannot be
    # negative. Reserve the earliest measured start; each column retains its
    # remaining positive source gap in normal paragraph spacing.
    body_top = min(first_anchors.values()) * _number(page, "width")
    if not 0 < body_top < _number(page, "height") * .3:
        return None
    control = next((c for c in section.iter(HP + "ctrl")
                    if c.find(HP + "colPr") is not None and c.find(HP + "colPr").get("colCount") == "2"), None)
    secpr = section.find(".//" + HP + "secPr")
    if control is None or secpr is None:
        return None
    second = etree.Element(section.tag, nsmap=section.nsmap)
    first = paragraphs[boundary]
    for p in list(section)[section.index(first):]:
        second.append(p)
    section_properties = deepcopy(secpr)
    section_properties.set("id", "1")
    following_margin = section_properties.find(".//" + HP + "pagePr/" + HP + "margin")
    following_margin.set("top", str(round(body_top)))
    following_margin.set("header", "0")
    run = first.find(HP + "run")
    run.insert(0, section_properties)
    run.insert(1, deepcopy(control))
    masthead = section.find('.//' + HP + 'header')
    if masthead is not None:
        # A section without a header inherits the preceding one in Hancom.
        # Explicitly end the first-page masthead; measured running headings
        # can replace this empty native header in the later writing pass.
        blank = deepcopy(masthead)
        identifier = max((int(n.get('id')) for root in (section, second) for n in root.iter()
                          if n.get('id', '').isdigit()), default=0) + 1
        blank.set('id', str(identifier))
        sub = blank.find(HP + 'subList')
        original = sub.find(HP + 'p')
        p = etree.Element(HP + 'p', **dict(original.attrib))
        p.set('id', str(identifier + 1))
        r = etree.SubElement(p, HP + 'run', charPrIDRef=original.find(HP + 'run').get('charPrIDRef', '0'))
        etree.SubElement(r, HP + 't')
        for child in list(sub):
            sub.remove(child)
        sub.set('textHeight', '0')
        sub.append(p)
        ctrl = etree.Element(HP + 'ctrl')
        ctrl.append(blank)
        run.insert(2, ctrl)
    delta = body_top - _number(margin, "top")
    styles = {p.get("id"): p for p in header.iter(HH + "paraPr")}
    previous = None
    for p, group in zip(paragraphs[boundary:], source_groups[boundary:]):
        if group != previous:
            before, _ = paragraph_spacing(p, styles)
            set_space_before(p, header, max(0, before - delta))
        previous = group
    _paginate(second, paragraphs[boundary:], source_groups[boundary:], header)
    return second
