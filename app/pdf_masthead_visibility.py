"""Exclude masthead glyphs fully covered by later opaque PDF rectangles."""
from collections import defaultdict

import fitz

from .pdf_source_page_memo import page_memo, source_text_dict


def _covered_characters(page):
    # A filled rectangle is sufficient proof; arbitrary paths, translucent
    # paint, images and a mere intersecting bounding box are not.
    if not hasattr(page, "get_drawings") or not hasattr(page, "get_texttrace"):
        return frozenset()
    covers = []
    for drawing in page.get_drawings():
        items = drawing.get("items", [])
        if (drawing.get("fill") is not None
                and drawing.get("fill_opacity") == 1
                and len(items) == 1 and items[0][0] == "re"
                and drawing.get("seqno") is not None):
            covers.append((int(drawing["seqno"]), fitz.Rect(items[0][1])))
    if not covers:
        return frozenset()
    states = defaultdict(list)
    for trace in page.get_texttrace():
        if trace.get("type") not in (0, 1) or not trace.get("opacity", 1):
            continue
        for code, _, origin, bounds in trace["chars"]:
            key = (chr(code), round(origin[0], 2), round(origin[1], 2))
            box = fitz.Rect(bounds)
            states[key].append(any(seq > trace["seqno"] and rect.contains(box)
                                   for seq, rect in covers))
    # Fill/stroke duplicates must both be covered. If a later visible copy has
    # the same character/origin, retaining it is the conservative choice.
    return frozenset(key for key, covered in states.items() if all(covered))


def visible_masthead_lines(page, body_top):
    lines = [line for block in source_text_dict(page)["blocks"]
             for line in block.get("lines", []) if line["bbox"][3] < body_top]
    covered = page_memo(page, "masthead_covered_characters", lambda: _covered_characters(page))
    if not covered:
        return lines
    raw = {tuple(span["bbox"]): span for block in source_text_dict(page, "rawdict")["blocks"]
           for line in block.get("lines", []) for span in line["spans"]}
    result = []
    for line in lines:
        spans = []
        for span in line["spans"]:
            chars = raw.get(tuple(span["bbox"]), {}).get("chars", [])
            keys = [(char["c"], round(char["origin"][0], 2), round(char["origin"][1], 2))
                    for char in chars if char["c"].strip()]
            if not keys or not all(key in covered for key in keys):
                spans.append(span)
        if spans:
            result.append({**line, "spans": spans})
    return result
