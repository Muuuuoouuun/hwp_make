"""Associate isolated vertex labels with their genuine embedded diagram."""
import re
from statistics import median

import fitz


def statistical_chart_regions(page):
    """Return proven source chart bounds in PDF points for import/export users."""
    from . import pdf_layout_writer as w
    from .pdf_native_content import _native_images_and_frames
    from .pdf_source_page_memo import page_memo

    def measure():
        lines = w._iter_text_lines(page)
        figures, _ = _native_images_and_frames(page, lines)
        include_statistical_chart_labels(page, figures, lines)
        return [tuple(w._item_bbox(figure)) for figure in figures
                if figure.get("source_chart")]

    return page_memo(page, "statistical_chart_regions", measure,
                     copy=lambda bounds: [fitz.Rect(box) for box in bounds])


def include_statistical_chart_labels(page, figures, lines, table_regions=()):
    """Keep a bounded source chart, including its axes and legend, together.

    PDF charts often store the bars as one bitmap and the labels as separate
    text/vector objects. A real rectangular chart frame, repeated numeric
    data, an ordered outside axis and several aligned category labels prove
    ownership. Only that original graphic is cropped; neighbouring prose and
    tables never become part of the figure.
    """
    from . import pdf_layout_writer as w

    frames = [fitz.Rect(item[1]) for drawing in page.get_drawings()
              for item in drawing.get("items", []) if item and item[0] == "re"]
    selected, covered = set(), set()
    for figure in figures:
        if id(figure) in covered or figure.get("native_graph"):
            continue
        core = w._item_bbox(figure)
        if core.width < page.rect.width * .16 or core.height < 40:
            continue
        candidates = sorted((frame for frame in frames if frame.contains(core)
                             and frame.width <= page.rect.width * .48
                             and frame.height <= page.rect.height * .35
                             and frame.get_area() <= core.get_area() * 3),
                            key=lambda frame: frame.get_area())
        for frame in candidates:
            owned = [line for line in lines if frame.contains(w._item_bbox(line))]
            if not 16 <= len(owned) <= 90 or any(frame.intersects(fitz.Rect(t)) for t in table_regions):
                continue
            records = [(line, w._pdf_output_text(w._line_text(line)).strip(),
                        w._item_bbox(line)) for line in owned]
            if any(re.match(r"^(?:\d{1,3}[.)]\s|[①-⑳]|[∙•●※])", text)
                   for _, text, _ in records):
                continue
            numeric = [(line, text, box) for line, text, box in records
                       if re.fullmatch(r"\d{1,3}(?:\.\d+)?%?", text)]
            inside = [r for r in numeric if core.contains(r[2])]
            # A horizontal axis sits below the plot. Repeated table values
            # alone cannot authorize turning an editable data table into art.
            ticks = sorted((r for r in numeric
                            if core.y1 - 1 <= r[2].y0 <= core.y1 + 24),
                           key=lambda r: r[2].x0)
            values = [float(text.rstrip("%")) for _, text, _ in ticks]
            categories = [(line, text, box) for line, text, box in records
                          if re.search(r"[A-Za-z가-힣]", text)
                          and len(text) <= 18 and len(text.split()) <= 3
                          and core.y0 <= box.y0 and box.y1 <= core.y1
                          and frame.x0 <= box.x0 < core.x0
                          and box.x1 <= core.x0 + core.width * .04]
            if (len(inside) < 8 or len(ticks) < 4 or len(categories) < 3
                or any(a >= b for a, b in zip(values, values[1:]))
                or ticks[-1][2].x1 - ticks[0][2].x0 < core.width * .65
                or max(r[2].y0 for r in ticks) - min(r[2].y0 for r in ticks) > 3
                or len({round(r[2].y0 / 4) for r in categories}) < 3):
                continue
            # Titles, legends and a short source note may surround the plot;
            # ordinary prose through the data area disqualifies the frame.
            if any(len(text) > 90 or (core.intersects(box) and len(text) > 18)
                   for _, text, box in records):
                continue
            related = [other for other in figures if other is not figure
                       and frame.intersects(w._item_bbox(other))]
            if any(not frame.contains(w._item_bbox(other))
                   or w._item_bbox(other).get_area() > core.get_area() * .08
                   for other in related):
                continue
            figure["bbox"] = fitz.Rect(frame)
            figure["diagram_labels"] = [{"text": text, "bbox_pt": list(box)}
                                         for _, text, box in records]
            figure["source_chart"] = True
            selected.update(id(line) for line in owned)
            covered.update(id(other) for other in related)
            break
    figures[:] = [figure for figure in figures if id(figure) not in covered]
    return selected


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
