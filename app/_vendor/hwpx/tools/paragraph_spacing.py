"""Read native before/after paragraph spacing for cached flow layout."""
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"


def paragraph_spacing(paragraph, styles):
    style = styles.get(paragraph.get("paraPrIDRef")) if styles else None
    margin = style.find(".//" + HH + "margin") if style is not None else None
    result = []
    for name in ("prev", "next"):
        edge = margin.find(HC + name) if margin is not None else None
        result.append(max(0, float(edge.get("value", "0")))
                      if edge is not None and edge.get("unit", "HWPUNIT") == "HWPUNIT" else 0)
    return tuple(result)


def paragraph_indentation(paragraph, styles):
    """Return native left/right margins and first-line (or hanging) indent."""
    style = styles.get(paragraph.get("paraPrIDRef")) if styles else None
    margin = style.find(".//" + HH + "margin") if style is not None else None
    result = []
    for name in ("left", "right", "intent"):
        edge = margin.find(HC + name) if margin is not None else None
        value = (float(edge.get("value", "0")) if edge is not None
                 and edge.get("unit", "HWPUNIT") == "HWPUNIT" else 0)
        result.append(value if name == "intent" else max(0, value))
    return tuple(result)


def line_left_margin(left, indent, index):
    return left + (max(0, indent) if index == 0 else max(0, -indent))


def paragraph_tab_stops(paragraph, styles):
    """Read explicit left tab stops in native HWPUNIT coordinates."""
    style = styles.get(paragraph.get("paraPrIDRef")) if styles else None
    if style is None:
        return []
    root = style.getroottree().getroot()
    tab = next((t for t in root.iter(HH + "tabPr") if t.get("id") == style.get("tabPrIDRef")), None)
    if tab is None:
        return []
    hp = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
    case = next((c for c in tab.iter(hp + "case") if "HwpUnitChar" in c.get("required-namespace", "")), None)
    if case is not None:
        nodes, scale = list(case.iter(HH + "tabItem")), 1
    else:
        nodes, scale = list(tab.iter(HH + "tabItem")), .5
    return sorted({float(n.get("pos", "0")) * scale for n in nodes if n.get("type") == "LEFT"})
