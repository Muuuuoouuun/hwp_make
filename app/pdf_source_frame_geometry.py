"""Retain a complete source vector frame's inset in ordinary paragraph flow."""
import math
import re

import fitz

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'

# Source column rails are measured from text and the border can extend just
# outside that rail. Match the existing frame-padding allowance (<1px), while
# keeping every emitted horizontal offset nonnegative.
_ZERO_RAIL_TOLERANCE = 50


def _compact(value):
    from .pdf_layout_writer import _pdf_output_text
    return re.sub(r'\s+', '', _pdf_output_text(value))


def restore_source_prose_frame_position(table, layout, page_width, column_width):
    """Use a source-confirmed horizontal inset without a page/y anchor.

    Inline tables inside drawText ignore the owning paragraph's left margin in
    the renderer. A paragraph-following table supports the same native inset;
    its height still grows with its editable cell and advances the next flow.
    """
    geometries = layout.get('native_tables') or []
    records = (layout.get('source_typography') or {}).get('lines') or []
    if len(geometries) != 1 or not geometries[0].get('source_prose_frame') or not records:
        return False
    geometry = geometries[0]
    box = geometry.get('bbox_pt') or []
    source_width = float(layout.get('source_page_width_pt') or 0)
    rail = layout.get('column_left_pt')
    cells = table.findall(HP + 'tr/' + HP + 'tc')
    position, size = table.find(HP + 'pos'), table.find(HP + 'sz')
    if (len(box) != 4 or not source_width or rail is None or len(cells) != 1
        or geometry.get('cell_bounds') != [[box]] or position is None or size is None
        or geometry.get('background_path')
        or any(table.find('.//' + HP + tag) is not None for tag in ('tbl', 'pic', 'rect', 'equation'))):
        return False
    expected = _compact(geometry.get('source_frame_text') or '')
    if (not expected or expected != _compact(''.join(r.get('text', '') for r in records))
        or expected != _compact(''.join(t.text or '' for t in cells[0].iter(HP + 't')))
        or any(not fitz.Rect(box).contains(fitz.Rect(r['bbox_pt'])) for r in records)):
        return False
    scale = float(page_width) / source_width
    origin = float(rail) * scale
    document = table.getroottree().getroot()
    page_pr = document.find('.//' + HP + 'pagePr')
    columns = next((c for c in document.iter(HP + 'colPr') if c.get('colCount') == '2'), None)
    if page_pr is not None and columns is not None:
        margin = page_pr.find(HP + 'margin')
        if margin is not None:
            origin = float(margin.get('left', '0'))
            if int(layout.get('source_column') or 1) == 2:
                origin += float(column_width) + float(columns.get('sameGap', '0'))
    offset = round(float(box[0]) * scale - origin)
    width = (float(box[2]) - float(box[0])) * scale
    if (not all(math.isfinite(value) for value in (offset, width, column_width))
        or offset < -_ZERO_RAIL_TOLERANCE or max(0, offset) + width > float(column_width) + 2
        or abs(float(size.get('width', '0')) - width) > 2):
        return False
    offset = max(0, offset)
    position.attrib.update({'treatAsChar': '0', 'vertRelTo': 'PARA', 'horzRelTo': 'COLUMN',
                           'vertAlign': 'TOP', 'horzAlign': 'LEFT', 'vertOffset': '0',
                           'horzOffset': str(offset), 'flowWithText': '1', 'allowOverlap': '0'})
    return True


def source_flow_prose_frame_table(table, root, source):
    """Independently prove this inset against four real PDF rules and all text.

    This grants no exception from a name/flag in the output package. A matching
    complete source vector rectangle, width, height, column inset and cell text
    are required, as are paragraph-relative vertical flow and no overlapping or
    nested body objects.
    """
    from .pdf_layout_writer import _iter_text_lines, _line_text
    from .pdf_native_content import _source_prose_frame

    position, size = table.find(HP + 'pos'), table.find(HP + 'sz')
    cells = table.findall(HP + 'tr/' + HP + 'tc')
    if (position is None or size is None or len(cells) != 1
        or table.get('rowCnt') != '1' or table.get('colCnt') != '1'
        or table.get('lock') == '1' or table.get('textWrap') != 'TOP_AND_BOTTOM'
        or any(position.get(k) != value for k, value in (
            ('treatAsChar', '0'), ('vertRelTo', 'PARA'), ('horzRelTo', 'COLUMN'),
            ('vertOffset', '0'), ('flowWithText', '1'), ('allowOverlap', '0'),
            ('horzAlign', 'LEFT'), ('vertAlign', 'TOP')))
        or cells[0].get('hasMargin') != '1' or cells[0].get('protect') == '1'
        or any(table.find('.//' + HP + tag) is not None for tag in ('tbl', 'pic', 'rect', 'equation'))):
        return False
    try:
        native = _compact(''.join(t.text or '' for t in cells[0].iter(HP + 't')))
        page_pr = root.find('.//' + HP + 'pagePr')
        margin = page_pr.find(HP + 'margin')
        columns = next(c for c in root.iter(HP + 'colPr') if c.get('colCount') == '2')
        paper_width = float(page_pr.get('width'))
        left = float(margin.get('left'))
        gap = float(columns.get('sameGap'))
        column_width = (paper_width - left - float(margin.get('right')) - gap) / 2
        offset, width, height = (float(position.get('horzOffset')), float(size.get('width')),
                                 float(size.get('height')))
        if (not native or not all(math.isfinite(v) for v in (offset, width, height))
            or offset < 0 or min(width, height) <= 0 or offset + width > column_width + 2
            or abs(float(cells[0].find(HP + 'cellSz').get('width')) - width) > 2
            or abs(float(cells[0].find(HP + 'cellSz').get('height')) - height) > 2):
            return False
        with fitz.open(source) as pdf:
            for page in pdf:
                scale = paper_width / page.rect.width
                drawings = page.get_drawings()
                horizontals = []
                for drawing in drawings:
                    for part in drawing.get('items', []):
                        if part and part[0] == 'l':
                            a, b = part[1:3]
                            if abs(a.y - b.y) < .5:
                                horizontals.append((min(a.x, b.x), a.y, max(a.x, b.x)))
                        elif part and part[0] == 're':
                            bounds = fitz.Rect(part[1])
                            horizontals.extend([(bounds.x0, bounds.y0, bounds.x1),
                                                (bounds.x0, bounds.y1, bounds.x1)])
                for origin in (left, left + column_width + gap):
                    x = (origin + offset) / scale
                    for x0, top, x1 in horizontals:
                        # A zero inset can retain the same subpixel border
                        # overhang as the producer. Positive insets still
                        # require the original exact source coordinate proof.
                        rail_tolerance = _ZERO_RAIL_TOLERANCE if offset == 0 else 2
                        if abs(x0 - x) * scale > rail_tolerance or abs((x1 - x0) * scale - width) > 2:
                            continue
                        bounds = fitz.Rect(x0, top, x1, top + height / scale)
                        frame = _source_prose_frame(bounds, drawings)
                        if frame is None or abs(frame.height * scale - height) > 2:
                            continue
                        original = ''.join(_compact(_line_text(line)) for line in _iter_text_lines(page)
                                           if frame.contains(fitz.Rect(line['bbox'])))
                        if original == native:
                            return True
    except (ValueError, TypeError, AttributeError, KeyError, StopIteration):
        pass
    return False
