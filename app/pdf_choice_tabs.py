"""Restore measured option spacing with editable native paragraph tabs."""
from copy import deepcopy
import re

from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"
MARKERS = "①②③④⑤"


def restore_choice_tabs(paragraphs, header, page_width, width):
    """Only accept a complete, single source row of consecutive choices.

    The paragraph and its equations stay intact. Tab definitions determine
    editing behavior; inline widths cache the gaps actually printed in the PDF.
    """
    properties = header.find(".//" + HH + "paraProperties")
    tab_properties = header.find(".//" + HH + "tabProperties")
    if properties is None or tab_properties is None:
        return 0
    styles = {p.get("id"): p for p in properties}
    next_style = max(map(int, styles), default=-1) + 1
    next_tab = max((int(p.get("id")) for p in tab_properties), default=-1) + 1
    changed = 0
    for paragraph, layout in paragraphs:
        records = (layout.get("source_typography") or {}).get("lines") or []
        cache = paragraph.find(HP + "linesegarray")
        if (len(records) != 1 or cache is None or len(cache) != 1
            or any(a.tag == HP + "tc" for a in paragraph.iterancestors())
            or layout.get("column_left_pt") is None or not layout.get("source_page_width_pt")):
            continue
        children = [child for run in paragraph.findall(HP + "run") for child in run]
        if any(child.tag not in {HP + "t", HP + "equation"}
               or (child.tag == HP + "t" and len(child)) for child in children):
            continue
        texts = [child for child in children if child.tag == HP + "t"]
        text = "".join(t.text or "" for t in texts)
        labels = re.findall("[①-⑤]", text)
        if not 2 <= len(labels) <= 5 or not text.lstrip().startswith(labels[0]):
            continue
        if "".join(labels) not in MARKERS:
            continue
        chars = [c for span in records[0].get("spans", []) for c in span.get("chars", [])
                 if (c.get("c") or "").strip() and len(c.get("bbox", [])) == 4]
        markers = [c for c in chars if c["c"] in MARKERS]
        if [c["c"] for c in markers] != labels:
            continue
        scale = page_width / float(layout["source_page_width_pt"])
        rail = float(layout["column_left_pt"])
        starts = [(c["bbox"][0] - rail) * scale for c in markers]
        if starts[0] < -2 or starts[-1] >= width or any(b <= a for a, b in zip(starts, starts[1:])):
            continue
        gaps = []
        for previous, following in zip(markers, markers[1:]):
            ink = [c["bbox"][2] for c in chars if previous["bbox"][0] <= c["bbox"][0] < following["bbox"][0]]
            gap = (following["bbox"][0] - max(ink)) * scale
            if gap <= 0 or gap > 65535:
                break
            gaps.append(round(gap))
        if len(gaps) != len(labels) - 1:
            continue

        tab = etree.SubElement(tab_properties, HH + "tabPr", id=str(next_tab), autoTabLeft="0", autoTabRight="0")
        switch = etree.SubElement(tab, HP + "switch")
        case = etree.SubElement(switch, HP + "case", attrib={"required-namespace": "http://www.hancom.co.kr/hwpml/2016/HwpUnitChar"})
        default = etree.SubElement(switch, HP + "default")
        for stop in starts[1:]:
            etree.SubElement(case, HH + "tabItem", pos=str(round(stop)), type="LEFT", leader="NONE")
            etree.SubElement(default, HH + "tabItem", pos=str(round(stop * 2)), type="LEFT", leader="NONE")
        style = deepcopy(styles[paragraph.get("paraPrIDRef")])
        style.set("id", str(next_style))
        style.set("tabPrIDRef", str(next_tab))
        style.find(HH + "align").set("horizontal", "LEFT")
        for margin in style.findall(".//" + HH + "margin"):
            for name, value in (("left", max(0, round(starts[0]))), ("right", 0), ("intent", 0)):
                edge = margin.find(HC + name)
                if edge is None:
                    edge = etree.SubElement(margin, HC + name)
                edge.set("value", str(value))
                edge.set("unit", "HWPUNIT")
        properties.append(style)
        paragraph.set("paraPrIDRef", str(next_style))
        next_style += 1
        next_tab += 1
        label_index = 0
        for node in texts:
            value = node.text or ""
            matches = list(re.finditer("[①-⑤]", value))
            if not matches:
                continue
            run = node.getparent()
            position = run.index(node)
            start = 0
            replacements = []
            for match in matches:
                if label_index:
                    prefix = value[start:match.start()].rstrip()
                    if prefix:
                        part = etree.Element(HP + "t")
                        part.text = prefix
                        replacements.append(part)
                    replacements.append(etree.Element(HP + "tab", width=str(gaps[label_index - 1]), leader="0", type="1"))
                    start = match.start()
                label_index += 1
            part = etree.Element(HP + "t")
            part.text = value[start:]
            replacements.append(part)
            run.remove(node)
            for offset, replacement in enumerate(replacements):
                run.insert(position + offset, replacement)
        cache[0].set("horzpos", "0")
        cache[0].set("horzsize", str(round(width)))
        changed += 1
    properties.set("itemCnt", str(len(properties)))
    tab_properties.set("itemCnt", str(len(tab_properties)))
    return changed
