"""Store measured paragraph indentation as an editable native paragraph style."""
from copy import deepcopy
from lxml import etree

from .pdf_source_line_cache import apply_source_line_cache, HP

HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"


def restore_paragraph_indentation(paragraphs, header, page_width, width):
    properties = header.find(".//" + HH + "paraProperties")
    styles = {p.get("id"): p for p in properties}
    next_id = max(map(int, styles)) + 1
    cache = {}
    changed = 0
    for paragraph, layout in paragraphs:
        meta = layout.get("source_typography") or {}
        records = meta.get("lines") or []
        if (not records or not layout.get("source_page_width_pt")
            or any(a.tag == HP + "tc" for a in paragraph.iterancestors())
            or str(meta.get("alignment") or "LEFT").upper() not in {"LEFT", "JUSTIFY"}):
            continue
        scale = page_width / float(layout["source_page_width_pt"])
        rail = layout.get("column_left_pt")
        if rail is None:
            continue
        starts = [(r["bbox_pt"][0] - rail) * scale for r in records]
        size = float(meta.get("font_size_pt") or 0) * scale
        if size <= 0 or min(starts) < -2:
            continue
        left = max(0, round(min(starts)))
        indent = round(starts[0] - starts[1]) if len(starts) > 1 else 0
        # Large changes in the starting rail beside a picture are wrapping,
        # not a hundred-point first-line indent.
        if abs(indent) > size * 3:
            indent = 0
        if left < 2 and abs(indent) < 2:
            continue
        candidate = {**layout, "native_page_width": page_width, "native_indentation": (left, 0, indent)}
        probe = deepcopy(paragraph)
        if not apply_source_line_cache(probe, candidate, width):
            continue
        base = paragraph.get("paraPrIDRef")
        key = (base, left, indent)
        if key not in cache:
            style = deepcopy(styles[base])
            identifier = str(next_id)
            next_id += 1
            style.set("id", identifier)
            for margin in style.findall(".//" + HH + "margin"):
                for tag, value in (("left", left), ("right", 0), ("intent", indent)):
                    node = margin.find(HC + tag)
                    if node is None:
                        node = etree.SubElement(margin, HC + tag)
                    node.set("value", str(value))
                    node.set("unit", "HWPUNIT")
            properties.append(style)
            cache[key] = identifier
        paragraph.set("paraPrIDRef", cache[key])
        old = paragraph.find(HP + "linesegarray")
        if old is not None:
            paragraph.remove(old)
        paragraph.append(probe.find(HP + "linesegarray"))
        changed += 1
    properties.set("itemCnt", str(len(properties)))
    return changed
