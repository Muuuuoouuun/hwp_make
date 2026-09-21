"""Associate isolated vertex labels with their genuine embedded diagram."""
import re
from statistics import median

import fitz


def include_diagram_labels(page, figures, lines, table_regions=()):
    """Expand a bitmap only for a bounded constellation of vertex labels.

    Labels may sit just outside the bitmap and use the body font size. Require
    several distinct one-letter labels on different edges, a unique nearby
    bitmap, and no prose, formula, table or other picture in the added region.
    The resulting source crop is one illustration, with its labels as pixels;
    it is never a substitute for an editable text paragraph.
    """
    from . import pdf_layout_writer as w

    original = {id(figure): fitz.Rect(w._item_bbox(figure)) for figure in figures}
    assigned = {id(figure): [] for figure in figures}
    for line in lines:
        text = w._pdf_output_text(w._line_text(line)).strip()
        spans = [s for s in line.get("spans", []) if str(s.get("text", "")).strip()]
        sizes = [float(s.get("size", 0)) for s in spans]
        if not re.fullmatch(r"[A-Z](?:['′″])?", text) or not sizes or min(sizes) <= 0:
            continue
        size, bounds = median(sizes), w._item_bbox(line)
        if bounds.width > size * 1.8 or bounds.height > size * 1.8:
            continue
        owners = []
        for key, region in original.items():
            near = fitz.Rect(region.x0 - size * 1.4, region.y0 - size * 1.4,
                             region.x1 + size * 1.4, region.y1 + size * 1.4)
            if (region.width >= size * 4 and region.height >= size * 3
                and near.contains(bounds)):
                owners.append(key)
        if len(owners) == 1:
            assigned[owners[0]].append((line, text, bounds, size))

    retained = set()
    for figure in figures:
        key = id(figure)
        region, labels = original[key], assigned[key]
        if not 3 <= len(labels) <= 14 or len({text for _, text, _, _ in labels}) != len(labels):
            continue
        expanded, edges = fitz.Rect(region), set()
        for _, _, bounds, _ in labels:
            expanded.include_rect(bounds)
            for name, outside in (("left", bounds.x0 < region.x0), ("right", bounds.x1 > region.x1),
                                  ("top", bounds.y0 < region.y0), ("bottom", bounds.y1 > region.y1)):
                if outside:
                    edges.add(name)
        if (len(edges) < 2 or expanded.get_area() > region.get_area() * 1.65
            or not page.rect.contains(expanded)
            or any(expanded.intersects(fitz.Rect(table)) for table in table_regions)
            or any(other != key and expanded.intersects(bounds) for other, bounds in original.items())):
            continue
        label_ids = {id(line) for line, _, _, _ in labels}
        if any(id(line) not in label_ids and w._line_text(line).strip()
               and expanded.intersects(w._item_bbox(line)) for line in lines):
            continue
        figure["bbox"] = expanded
        figure["diagram_labels"] = [
            {"text": text, "bbox_pt": list(bounds)} for _, text, bounds, _ in labels
        ]
        retained.update(label_ids)
    return retained
