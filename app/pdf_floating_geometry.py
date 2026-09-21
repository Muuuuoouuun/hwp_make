"""Independently inspect paragraph-anchored pictures and text wrap rectangles."""
from math import isfinite

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def inspect_floating_picture(picture, header=None):
    if picture.get("textWrap") == "TOP_AND_BOTTOM":
        return inspect_standalone_picture(picture, header)
    issues = []
    try:
        def number(node, key, default=0):
            value = float(node.get(key, default)) if node is not None else float(default)
            if not isfinite(value):
                raise ValueError("non-finite geometry")
            return value

        pos, size, margin = (picture.find(HP + tag) for tag in ("pos", "sz", "outMargin"))
        paragraph = picture.getparent().getparent()
        if (paragraph.tag != HP + "p" or pos is None or size is None
            or picture.get("textWrap") != "SQUARE" or picture.get("textFlow") != "BOTH_SIDES"
            or pos.get("treatAsChar") != "0" or pos.get("flowWithText") != "1"
            or pos.get("allowOverlap") != "0" or pos.get("vertRelTo") != "PARA"
            or pos.get("horzRelTo") != "COLUMN" or pos.get("horzAlign") != "LEFT"
            or pos.get("vertAlign") != "TOP"):
            return {"ok": False, "issues": ["unsupported_floating_picture_anchor"]}
        lines = paragraph.findall(HP + "linesegarray/" + HP + "lineseg")
        if not lines or not any((t.text or "").strip() for t in paragraph.findall(HP + "run/" + HP + "t")):
            return {"ok": False, "issues": ["floating_picture_without_editable_paragraph"]}
        root = paragraph.getroottree().getroot()
        page = root.find(".//" + HP + "pagePr")
        page_margin = page.find(HP + "margin") if page is not None else None
        columns = next((c for c in root.iter(HP + "colPr") if c.get("colCount") == "2"), None)
        width = (number(page, "width") - number(page_margin, "left")
                 - number(page_margin, "right") - number(columns, "sameGap")) / 2
        draw = next((a for a in paragraph.iterancestors() if a.tag == HP + "drawText"), None)
        if draw is not None:
            width = number(draw, "lastWidth")
        # COLUMN anchoring inside table cells has different ownership; this
        # export feature only emits direct body or question paragraphs.
        if any(a.tag == HP + "tc" for a in paragraph.iterancestors()):
            issues.append("unsupported_floating_picture_cell")
        x, y = number(pos, "horzOffset"), number(pos, "vertOffset")
        w, h = number(size, "width"), number(size, "height")
        if min(w, h, width) <= 0 or x < -2 or x + w > width + 2:
            issues.append("floating_picture_outside_column")
        left, right = x - number(margin, "left"), x + w + number(margin, "right")
        top, bottom = y - number(margin, "top"), y + h + number(margin, "bottom")
        origin = min(number(line, "vertpos") for line in lines)
        text_left = text_right = indent = 0
        if header is not None:
            hh = "{http://www.hancom.co.kr/hwpml/2011/head}"
            hc = "{http://www.hancom.co.kr/hwpml/2011/core}"
            styles = {p.get("id"): p for p in header.iter(hh + "paraPr")}
            style = styles.get(paragraph.get("paraPrIDRef"))
            if style is None:
                issues.append("unresolved_floating_paragraph_style")
            else:
                text_margin = style.find(".//" + hh + "margin")
                if text_margin is not None:
                    text_left, text_right, indent = (number(text_margin.find(hc + tag), "value")
                                                    for tag in ("left", "right", "intent"))
        beside = 0
        for index, line in enumerate(lines):
            a, c = number(line, "horzpos"), number(line, "horzsize")
            native_left = text_left + (max(0, indent) if index == 0 else max(0, -indent))
            a += native_left
            c -= native_left + text_right
            b = number(line, "vertpos") - origin
            d = max(number(line, "vertsize"), number(line, "textheight"))
            if c <= 0 or d <= 0 or a < -2 or a + c > width + 2:
                issues.append("floating_paragraph_line_outside_column")
            if min(b + d, bottom) > max(b, top):
                beside += 1
                if min(a + c, right) - max(a, left) > 2:
                    issues.append("floating_picture_overlaps_text_wrap")
        if not beside:
            issues.append("floating_picture_detached_from_paragraph")
    except (TypeError, ValueError, AttributeError):
        issues.append("invalid_floating_picture_geometry")
    return {"ok": not issues, "issues": sorted(set(issues))}


def inspect_standalone_picture(picture, header):
    """Accept only a full-height, single-figure paragraph in native text flow."""
    issues = []
    try:
        def number(node, key):
            value = float(node.get(key, "0")) if node is not None else 0.0
            if not isfinite(value):
                raise ValueError("non-finite geometry")
            return value

        pos, size, margin = (picture.find(HP + tag) for tag in ("pos", "sz", "outMargin"))
        paragraph = picture.getparent().getparent()
        if (paragraph.tag != HP + "p" or pos is None or size is None
            or picture.get("textWrap") != "TOP_AND_BOTTOM"
            or pos.get("treatAsChar") != "0" or pos.get("flowWithText") != "1"
            or pos.get("affectLSpacing") != "1" or pos.get("allowOverlap") != "0"
            or pos.get("vertRelTo") != "PARA" or pos.get("horzRelTo") != "COLUMN"
            or pos.get("vertAlign") != "TOP" or pos.get("horzAlign") != "LEFT"
            or number(pos, "vertOffset") != 0
            or any(number(margin, edge) for edge in ("left", "right", "top", "bottom"))):
            return {"ok": False, "issues": ["unsupported_standalone_picture_anchor"]}
        children = [child for run in paragraph.findall(HP + "run") for child in run]
        if (sum(child.tag == HP + "pic" for child in children) != 1
            or any(child is not picture and (child.tag != HP + "t" or len(child) or (child.text or "").strip())
                   for child in children)
            or any(a.tag == HP + "tc" for a in paragraph.iterancestors())):
            issues.append("standalone_picture_shares_text_paragraph")
        root = paragraph.getroottree().getroot()
        page = root.find(".//" + HP + "pagePr")
        margins = page.find(HP + "margin") if page is not None else None
        columns = next((c for c in root.iter(HP + "colPr") if c.get("colCount") == "2"), None)
        width = (number(page, "width") - number(margins, "left") - number(margins, "right")
                 - number(columns, "sameGap")) / (2 if columns is not None else 1)
        draw = next((a for a in paragraph.iterancestors() if a.tag == HP + "drawText"), None)
        if draw is not None:
            width = number(draw, "lastWidth")
        x, w, h = number(pos, "horzOffset"), number(size, "width"), number(size, "height")
        if min(w, h, width) <= 0 or x < 0 or x + w > width + 1:
            issues.append("standalone_picture_outside_column")
        lines = paragraph.findall(HP + "linesegarray/" + HP + "lineseg")
        if (len(lines) != 1 or number(lines[0], "horzpos") != 0
            or min(number(lines[0], "vertsize"), number(lines[0], "textheight")) < h
            or number(lines[0], "horzsize") + 1 < x + w):
            issues.append("standalone_picture_without_reserved_flow_height")
        hh, hc = "{http://www.hancom.co.kr/hwpml/2011/head}", "{http://www.hancom.co.kr/hwpml/2011/core}"
        style = next((p for p in header.iter(hh + "paraPr") if p.get("id") == paragraph.get("paraPrIDRef")), None) if header is not None else None
        if (style is None or style.find(hh + "align").get("horizontal") != "LEFT"
            or any(number(edge, "value") for name in ("left", "right", "intent") for edge in style.findall(".//" + hc + name))):
            issues.append("standalone_picture_has_ambiguous_paragraph_position")
    except (AttributeError, TypeError, ValueError):
        issues.append("invalid_standalone_picture_geometry")
    return {"ok": not issues, "issues": sorted(set(issues))}
