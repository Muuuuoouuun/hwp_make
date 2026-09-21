"""Keep measured masthead fields in an editable native section header."""
from copy import deepcopy
from xml.etree import ElementTree

from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"


def restore_masthead_flow(section, header, meta, title, area, char_style, items):
    from hwpx.oxml._document_impl import HwpxOxmlTable
    from .pdf_source_spacing import source_anchor

    page = section.find(".//" + HP + "pagePr")
    if page is None:
        return False
    margin = page.find(HP + "margin")
    if margin is None:
        return False
    roots = section.findall(HP + "p")
    if not roots:
        return False
    host = roots[0]
    if host not in (title, area) and any((t.text or "").strip() for t in host.iter(HP + "t")):
        return False
    anchor = source_anchor([dict(item.get('layout') or {}, source_page=int(item.get('source_page') or 1))
                            for item in items]) if items else None
    if anchor is None:
        return False
    prologue = []
    for p in roots:
        if p.get('nativeSourceItem') is not None:
            break
        prologue.append(p)
    if (len([c for p in prologue for c in p.findall(HP + 'run/' + HP + 'ctrl/' + HP + 'colPr')
             if c.get('colCount') == '2']) != 1
        or section.find('.//' + HP + 'header') is not None):
        return False
    if any(p not in (host, title, area) and
           (any((t.text or '').strip() for t in p.iter(HP + 't'))
            or any(p.find('.//' + HP + tag) is not None for tag in ('pic', 'tbl', 'rect', 'equation')))
           for p in prologue):
        return False
    scale = float(page.get("width")) / meta["source_page_width_pt"]
    left = float(margin.get("left"))
    width = float(page.get("width")) - left - float(margin.get("right"))
    rows = [[meta["title"]], [meta["area"]]]
    if meta.get("page_number"):
        rows[0].append(meta["page_number"])
    if meta.get("period_geometry"):
        rows[1].append(meta["period_geometry"])
    elif meta.get("period"):
        return False
    for row in rows:
        row.sort(key=lambda r: r["bbox_pt"][0])
        if any(r.get("baseline_pt") is None or not r.get("spans") for r in row):
            return False
        if any(a["bbox_pt"][2] > b["bbox_pt"][0] + 1 for a, b in zip(row, row[1:])):
            return False
    if any(r["bbox_pt"][0] * scale < left - 2 or r["bbox_pt"][2] * scale > left + width + 2
           for row in rows for r in row):
        return False
    starts = [min(r["baseline_pt"] * scale - max(s["font_size_pt"] for s in r["spans"]) * scale * .85
                  for r in row) for row in rows]
    bottom = max(r["baseline_pt"] * scale + max(s["font_size_pt"] for s in r["spans"]) * scale * .15
                 for r in rows[1])
    rule = meta.get("bottom_rule")
    if rule and rule["y_pt"] * scale >= bottom:
        bottom = rule["y_pt"] * scale
    if not 0 < starts[0] < starts[1] < bottom:
        return False
    if anchor[2] * float(page.get('width')) / anchor[3] < bottom:
        return False
    heights = [round(starts[1] - starts[0]), round(bottom - starts[1])]
    borders = header.find(".//" + HH + "borderFills")
    if borders is None:
        return False
    none = next((b for b in borders if all(
        (e := b.find(HH + edge + "Border")) is not None and e.get("type") == "NONE"
        for edge in ("left", "right", "top", "bottom"))), None)
    if none is None:
        return False
    bottom_border = none.get("id")
    if rule and rule["width_pt"] > 0:
        border = deepcopy(none)
        bottom_border = str(max(int(b.get("id")) for b in borders) + 1)
        border.set("id", bottom_border)
        edge = border.find(HH + "bottomBorder")
        edge.set("type", "SOLID")
        edge.set("color", "#000000")
        edge.set("width", f'{rule["width_pt"] * scale / 100 * 25.4 / 72:.3f} mm')
        borders.append(border)
        borders.set("itemCnt", str(len(borders)))

    properties = header.find(".//" + HH + "paraProperties")
    style = deepcopy(next(p for p in properties if p.get("id") == title.get("paraPrIDRef")))
    style_id = str(max(int(p.get("id")) for p in properties) + 1)
    style.set("id", style_id)
    style.find(HH + "align").set("horizontal", "LEFT")
    for m in style.findall(".//" + HH + "margin"):
        for edge in m:
            edge.set("value", "0")
            edge.set("unit", "HWPUNIT")
    for spacing in style.findall(".//" + HH + "lineSpacing"):
        spacing.set("type", "PERCENT")
        spacing.set("value", "100")
        spacing.set("unit", "PERCENT")
    properties.append(style)
    properties.set("itemCnt", str(len(properties)))
    next_id = max((int(n.get("id")) for n in section.iter() if n.get("id", "").isdigit()), default=0) + 1
    base = title.find(HP + "run").get("charPrIDRef", "0")

    def paragraph(record, available, identifier):
        p = etree.Element(HP + "p", id=str(identifier), paraPrIDRef=style_id,
                          styleIDRef="0", pageBreak="0", columnBreak="0", merged="0")
        height = max((s["font_size_pt"] * scale for s in record["spans"]), default=1)
        for span in record["spans"]:
            char = char_style(base, span["font_size_pt"] * scale, span["font_name"],
                              round(span.get("letter_spacing_percent", 0)),
                              round(span.get("font_width_percent", 100)), bool(span["bold"]))
            run = etree.SubElement(p, HP + "run", charPrIDRef=char)
            etree.SubElement(run, HP + "t").text = span["text"]
        cache = etree.SubElement(p, HP + "linesegarray")
        etree.SubElement(cache, HP + "lineseg", textpos="0", vertpos="0", vertsize=str(round(height)),
                         textheight=str(round(height)), baseline=str(round(height * .85)), spacing="0",
                         horzpos="0", horzsize=str(round(available)), flags="393216")
        return p, height

    # One shared column grid, with spans for the different title/subject rows.
    rails = sorted({0, round(width), *(max(0, round(r["bbox_pt"][0] * scale - left))
                                     for row in rows for r in row)})
    table = etree.fromstring(ElementTree.tostring(HwpxOxmlTable.create(
        2, len(rails) - 1, width=round(width), height=sum(heights), border_fill_id_ref=none.get("id"))))
    table.set("id", str(next_id)); next_id += 1
    table.find(HP + "pos").set("affectLSpacing", "1")
    for tag in ("inMargin", "outMargin"):
        for edge in table.find(HP + tag).attrib:
            table.find(HP + tag).set(edge, "0")
    for row_index, (row, tr) in enumerate(zip(rows, table.findall(HP + "tr"))):
        cell_template = deepcopy(tr[0])
        for cell in list(tr):
            tr.remove(cell)
        entries = [(max(0, round(r["bbox_pt"][0] * scale - left)), r) for r in row]
        if entries[0][0] > 0:
            entries.insert(0, (0, None))
        for index, (start, record) in enumerate(entries):
            end = entries[index + 1][0] if index + 1 < len(entries) else round(width)
            cell = deepcopy(cell_template)
            cell.set("name", f"source-masthead:{row_index}:{index}")
            cell.set("hasMargin", "1")
            cell.set("editable", "1")
            cell.set("borderFillIDRef", bottom_border if row_index == 1 else none.get("id"))
            cell.find(HP + "cellAddr").set("colAddr", str(rails.index(start)))
            cell.find(HP + "cellAddr").set("rowAddr", str(row_index))
            cell.find(HP + "cellSpan").set("colSpan", str(rails.index(end) - rails.index(start)))
            cell.find(HP + "cellSz").set("width", str(end - start))
            cell.find(HP + "cellSz").set("height", str(heights[row_index]))
            sub = cell.find(HP + "subList")
            sub.set("vertAlign", "TOP")
            sub.set("textWidth", str(end - start))
            sub.set("textHeight", str(heights[row_index]))
            for child in list(sub):
                sub.remove(child)
            if record is None:
                record = {"spans": [{"text": "", "font_size_pt": 1 / scale, "font_name": "Gulim",
                                      "bold": False}], "baseline_pt": starts[row_index] / scale}
            p, height = paragraph(record, end - start, next_id); next_id += 1
            sub.append(p)
            inset = cell.find(HP + "cellMargin")
            for edge in inset.attrib:
                inset.set(edge, "0")
            inset.set("top", str(max(0, round(record["baseline_pt"] * scale - starts[row_index] - height * .85))))
            tr.append(cell)

    preserved = [deepcopy(c) for run in host.findall(HP + "run") for c in run
                 if c.tag in {HP + "secPr", HP + "ctrl"}]
    # Only replace the known template prologue; keep the later two-column
    # switch, which is relocated to the first body paragraph by the flow pass.
    for p in list(section.findall(HP + "p")):
        if p.get("nativeSourceItem") is not None:
            break
        if p is host:
            continue
        if p in (title, area) or (not any((t.text or "").strip() for t in p.iter(HP + "t"))
                                  and p.find('.//' + HP + 'ctrl') is None):
            section.remove(p)
    for child in list(host):
        host.remove(child)
    host.set("paraPrIDRef", style_id)
    run = etree.SubElement(host, HP + "run", charPrIDRef=base)
    for c in preserved:
        run.append(c)
    run.append(table)
    height = sum(heights) + 400
    cache = etree.SubElement(host, HP + "linesegarray")
    etree.SubElement(cache, HP + "lineseg", textpos="0", vertpos="0", vertsize=str(height),
                     textheight=str(height), baseline=str(round(height * .85)), spacing="0",
                     horzpos="0", horzsize=str(round(width)), flags="393216")
    # The original section properties were moved into the replacement host.
    host.find('.//' + HP + 'pagePr/' + HP + 'margin').set("top", str(round(starts[0])))
    return True


def promote_masthead_to_header(section, paragraphs, layouts):
    """Give the masthead its own header area before positioning body paragraphs.

    A full-width masthead is independent of body columns. Moving its native
    table into the section header eliminates an artificial one-column body
    band and keeps header edits out of the question's paragraph contents.
    """
    from .pdf_source_spacing import source_anchor

    if not paragraphs:
        return False
    first = paragraphs[0]
    prologue = list(section)[:section.index(first)]
    tables = [t for p in prologue for t in p.findall(HP + "run/" + HP + "tbl")
              if any(c.get("name", "").startswith("source-masthead:")
                     for c in t.findall(HP + "tr/" + HP + "tc"))]
    if len(tables) != 1:
        return False
    table = tables[0]
    host = table.getparent().getparent()
    secpr = host.find('.//' + HP + 'secPr')
    if secpr is None or section.find('.//' + HP + 'header') is not None:
        return False
    anchor = source_anchor([entry for group in layouts for entry in group])
    if anchor is None:
        return False
    page = secpr.find(HP + 'pagePr')
    margin = page.find(HP + 'margin')
    top = int(margin.get('top'))
    body_top = round(anchor[2] * float(page.get('width')) / anchor[3])
    table_height = int(table.find(HP + 'sz').get('height'))
    if body_top < top + table_height:
        return False
    # Reject unfamiliar content instead of dropping it with the template.
    for p in prologue:
        if p is not host and (any((t.text or '').strip() for t in p.iter(HP + 't'))
                             or any(p.find('.//' + HP + tag) is not None
                                    for tag in ('pic', 'tbl', 'rect', 'equation'))):
            return False
    columns = [c for p in prologue for c in p.findall(HP + 'run/' + HP + 'ctrl')
               if c.find(HP + 'colPr') is not None
               and c.find(HP + 'colPr').get('colCount') == '2']
    if len(columns) != 1:
        return False
    header_ctrl = etree.Element(HP + 'ctrl')
    identifier = max((int(n.get('id')) for n in section.iter() if n.get('id', '').isdigit()), default=0) + 1
    running = etree.SubElement(header_ctrl, HP + 'header', id=str(identifier), applyPageType='BOTH')
    sub = etree.SubElement(running, HP + 'subList', id='', textDirection='HORIZONTAL',
                          lineWrap='BREAK', vertAlign='TOP', linkListIDRef='0', linkListNextIDRef='0',
                          textWidth=table.find(HP + 'sz').get('width'),
                          textHeight=str(body_top - top), hasTextRef='0', hasNumRef='0')
    # Reuse the ordinary editable table paragraph, without section controls.
    heading = etree.Element(HP + 'p', **dict(host.attrib))
    run = etree.SubElement(heading, HP + 'run', charPrIDRef=host.find(HP + 'run').get('charPrIDRef'))
    run.append(table)
    cache = deepcopy(host.find(HP + 'linesegarray'))
    heading.append(cache)
    sub.append(heading)
    first_run = first.find(HP + 'run')
    first_run.insert(0, header_ctrl)
    first_run.insert(0, columns[0])
    first_run.insert(0, secpr)
    # Page numbering, visibility, and other template controls are independent
    # of the obsolete one-column band and must not disappear with that band.
    for p in prologue:
        for control in p.findall(HP + 'run/' + HP + 'ctrl'):
            for column in list(control.findall(HP + 'colPr')):
                control.remove(column)
            if len(control):
                first_run.insert(2, control)
    margin.set('header', str(body_top - top))
    for p in prologue:
        section.remove(p)
    return True
