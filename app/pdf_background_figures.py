"""Avoid painting an original bitmap both as a frame and a flow figure."""
import hashlib
import re

import fitz


def remove_covered_bitmap_figures(page, items, provenance):
    """Remove only figures already wholly owned by a retained table background.

    A PDF crop can include vector strokes or text absent from the raw bitmap.
    Those figures must survive, even if their bounds lie inside a background.
    Check the actual retained asset, its source image inventory and all other
    source painting operations before considering a figure redundant.
    """
    from . import storage

    def region(record):
        x, y, width, height = record['bbox_px']
        return fitz.Rect(x, y, x + width, y + height)

    records = [p for p in provenance if p.get('page') == page.number + 1]
    backgrounds = []
    for item in items:
        layout = item.get('layout') or {}
        geometries = layout.get('native_tables') or []
        lines = (layout.get('source_typography') or {}).get('lines') or []
        if len(geometries) != 1 or not lines:
            continue
        from .pdf_layout_writer import _pdf_output_text, is_hancom_eq_font
        compact = lambda value: re.sub(r'\s+', '', _pdf_output_text(value))
        for table in geometries:
            box = table.get('bbox_pt')
            if (not box or table.get('cell_bounds') != [[box]]
                or not table.get('background_source_text')
                or compact(table['background_source_text']) != compact(''.join(line['text'] for line in lines))
                or any(not fitz.Rect(box).contains(fitz.Rect(line['bbox_pt'])) for line in lines)
                or any(is_hancom_eq_font(span.get('font', '')) for line in lines for span in line.get('spans', []))):
                continue
            path = storage.resolve_data_image_path(table.get('background_path')) if table.get('background_path') else None
            if path is None:
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            backgrounds.extend(p for p in records
                               if p.get('role') == 'source_background_frame'
                               and p.get('sha256') == digest
                               and list(region(p)) == table.get('bbox_pt'))
    if not backgrounds:
        return items, provenance
    blocks = page.get_text('dict').get('blocks', [])
    text = [fitz.Rect(line['bbox']) for b in blocks if b.get('type') == 0
            for line in b.get('lines', [])]
    # Include the stroke width: a zero-height PDF rule is still visible ink.
    vectors = [fitz.Rect(d['rect']) + (-max(.1, d.get('width') or 0) / 2,
                                      -max(.1, d.get('width') or 0) / 2,
                                      max(.1, d.get('width') or 0) / 2,
                                      max(.1, d.get('width') or 0) / 2)
               for d in page.get_drawings()]
    annotations = [fitz.Rect(a.rect) for a in page.annots() or ()]
    kept, removed = [], set()
    for item in items:
        layout = item.get('layout') or {}
        paths = item.get('image_paths') or []
        bounds = layout.get('source_bbox_pt')
        if item.get('stem') or item.get('tables') or len(paths) != 1 or not bounds:
            kept.append(item)
            continue
        box = fitz.Rect(bounds)
        owners = [p for p in backgrounds if region(p).contains(box)]
        numbers = {b['number'] for b in blocks if b.get('type') == 1
                   and fitz.Rect(b['bbox']).intersects(box)}
        if (not numbers or not any(numbers <= set(p.get('source_image_numbers', [])) for p in owners)
            or any(box.intersects(other) for other in text + vectors + annotations)):
            kept.append(item)
            continue
        path = storage.resolve_data_image_path(paths[0])
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path else None
        matches = [p for p in records if p.get('role') == 'source_figure'
                   and p.get('sha256') == digest and region(p) == box]
        if not matches:
            kept.append(item)
            continue
        removed.update(id(p) for p in matches)
    return kept, [p for p in provenance if id(p) not in removed]
