"""Keep a source bitmap graph and its text-layer annotations as distinct objects."""
from statistics import median
import re

import fitz


def associate_graph_annotations(page, figures, lines, table_regions=()):
    """Recognize a sparse axis/point/function constellation, never body prose.

    Geometry, several independent label types, unique ownership and a complete
    embedded-image inventory are required. Unsupported diagrams stay on the
    existing path instead of granting a blanket text-in-picture exemption.
    """
    from . import pdf_layout_writer as w

    bitmaps = [b for b in page.get_text('dict')['blocks'] if b.get('type') == 1]
    selected = set()
    for index, figure in enumerate(figures):
        region = w._item_bbox(figure)
        candidates = []
        for line in lines:
            text = re.sub(r'\s|\$', '', w._pdf_output_text(w._line_text(line)))
            sizes = [float(s.get('size', 0)) for s in line.get('spans', [])
                     if str(s.get('text', '')).strip()]
            if not sizes or min(sizes) <= 0:
                continue
            size, bounds = median(sizes), w._item_bbox(line)
            syntax = (re.fullmatch(r'[A-Za-z]', text) or
                      re.fullmatch(r'[xy]=[A-Za-z](?:\([xy]\))?', text))
            near = fitz.Rect(region.x0-size, region.y0-size, region.x1+size, region.y1+size)
            if (syntax and near.contains(bounds) and region.intersects(bounds)
                and bounds.height <= size*1.8 and bounds.width <= region.width*.4
                and region.width >= size*6 and region.height >= size*5):
                candidates.append((line, text, bounds))
        values = [text for _, text, _ in candidates]
        if (not 6 <= len(candidates) <= 20 or len(values) != len(set(values))
            or not {'x', 'y'} <= set(values)
            or sum(bool(re.fullmatch('[A-Z]', t)) for t in values) < 3
            or sum('=' in t for t in values) < 2):
            continue
        expanded = fitz.Rect(region)
        for _, _, bounds in candidates:
            expanded |= bounds
        ids = {id(line) for line, _, _ in candidates}
        if (not page.rect.contains(expanded) or expanded.get_area() > region.get_area()*1.3
            or any(expanded.intersects(fitz.Rect(t)) for t in table_regions)
            or any(other is not figure and expanded.intersects(w._item_bbox(other)) for other in figures)
            or any(id(line) not in ids and w._line_text(line).strip()
                   and expanded.intersects(w._item_bbox(line)) for line in lines)):
            continue
        originals = [b for b in bitmaps if expanded.contains(fitz.Rect(b['bbox']))]
        if not originals:
            continue
        transforms = [fitz.Matrix(b['transform']) for b in originals]
        if any(abs(m.b) > .001 or abs(m.c) > .001 or m.a <= 0 or m.d <= 0 for m in transforms):
            continue
        candidates.sort(key=lambda record: (record[2].y0, record[2].x0))
        figure['bbox'] = expanded
        figure['native_graph'] = {
            'key': f'{page.number+1}:{index}', 'bbox_pt': list(expanded),
            'source_image_numbers': [b['number'] for b in originals],
            'lines': [line for line, _, _ in candidates],
        }
        selected.update(ids)
    return selected
