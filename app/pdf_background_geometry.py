"""Independently validate a source-backed frame's horizontal flow inset."""
import math
import re

import fitz
from lxml import etree

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'


def source_flow_background_table(table, root, header, hrefs, package, source, provenance):
    """Accept ordinary native flow, never arbitrary positioned line tables.

    A complete source frame may start inside the column. Its native body cell
    must contain ALL source text in order. Optional empty cap rows must match
    contiguous original bitmap regions and real native row dimensions.
    """
    from .pdf_source_backgrounds import native_background_assets
    from .pdf_layout_writer import _iter_text_lines, _line_text, _pdf_output_text

    pos, size = table.find(HP+'pos'), table.find(HP+'sz')
    cells = table.findall(HP+'tr/'+HP+'tc')
    if (pos is None or size is None or len(cells) not in (1, 3) or table.get('lock') == '1'
        or table.get('textWrap') != 'TOP_AND_BOTTOM'
        or any(pos.get(k) != value for k, value in (
            ('treatAsChar', '0'), ('vertRelTo', 'PARA'), ('horzRelTo', 'COLUMN'),
            ('vertOffset', '0'), ('flowWithText', '1'), ('allowOverlap', '0'),
            ('horzAlign', 'LEFT'), ('vertAlign', 'TOP')))
        or any(table.find('.//'+HP+tag) is not None for tag in ('tbl', 'pic', 'rect', 'equation'))):
        return False
    cell = cells[len(cells) // 2]
    if any(c.get('hasMargin') != '1' or c.get('protect') == '1' for c in cells):
        return False
    owner = etree.Element(table.tag, attrib=dict(table.attrib))
    def number(node, name):
        value = float(node.get(name))
        if not math.isfinite(value):
            raise ValueError('non-finite geometry')
        return value
    try:
        records = []
        owners = [owner] if len(cells) == 1 else [etree.Element(c.tag, attrib=dict(c.attrib)) for c in cells]
        if len(cells) == 3:
            if table.get('rowCnt') != '3' or table.get('colCnt') != '1' or native_background_assets(owner, header, hrefs, package):
                return False
            if any((t.text or '').strip() for c in (cells[0], cells[2]) for t in c.iter(HP + 't')):
                return False
        for index, o in enumerate(owners):
            assets = native_background_assets(o, header, hrefs, package)
            if len(assets) != 1:
                return False
            candidates = [p for p in provenance if p.get('role') == 'source_background_frame'
                          and p.get('sha256') == assets[0][0]]
            if len(candidates) != 1:
                return False
            records.append(candidates[0])
            if len(cells) == 3:
                c = cells[index]
                if (number(c.find(HP + 'cellAddr'), 'rowAddr') != index
                    or number(c.find(HP + 'cellAddr'), 'colAddr') != 0
                    or number(c.find(HP + 'cellSpan'), 'rowSpan') != 1
                    or number(c.find(HP + 'cellSpan'), 'colSpan') != 1):
                    return False
        record = records[0]
        page_properties = root.find('.//'+HP+'pagePr')
        page_margin = page_properties.find(HP+'margin')
        columns = next(c for c in root.iter(HP+'colPr') if c.get('colCount') == '2')
        page_width = number(page_properties, 'width')
        gap = number(columns, 'sameGap')
        left = number(page_margin, 'left')
        column_width = (page_width - left - number(page_margin, 'right') - gap) / 2
        x, y, width, height = map(float, record['bbox_px'])
        if len(records) == 3:
            bottom = y + height
            for r in records[1:]:
                a, b, w, h = map(float, r['bbox_px'])
                if (r['page'] != record['page'] or abs(a-x) > 1e-5
                    or abs(w-width) > 1e-5 or abs(b-bottom) > 1e-5 or h <= 0):
                    return False
                bottom = b + h
            height = bottom-y
        if min(width, height) <= 0 or not all(math.isfinite(v) for v in (x, y, width, height)):
            return False
        bounds = fitz.Rect(x, y, x+width, y+height)
        with fitz.open(source) as pdf:
            page = pdf[int(record['page'])-1]
            if not page.rect.contains(bounds):
                return False
            scale = page_width / page.rect.width
            if bounds.x0 >= page.rect.width / 2:
                left += column_width + gap
            expected = x * scale - left
            offset = number(pos, 'horzOffset')
            actual_width = number(size, 'width')
            if (offset < 0 or offset + actual_width > column_width + 2
                or abs(offset - expected) > 2 or abs(actual_width - width * scale) > 2
                or any(abs(number(c.find(HP+'cellSz'), 'width') - actual_width) > 2 for c in cells)):
                return False
            if len(cells) == 3:
                if (abs(number(size, 'height') - height * scale) > 2
                    or any(abs(number(c.find(HP+'cellSz'), 'height') - float(r['bbox_px'][3]) * scale) > 2
                           for c, r in zip(cells, records))):
                    return False
            compact = lambda value: re.sub(r'\s+', '', _pdf_output_text(value))
            original = ''.join(compact(_line_text(line)) for line in _iter_text_lines(page)
                               if bounds.contains(fitz.Rect(line['bbox'])))
            native = ''.join(compact(t.text or '') for t in cell.iter(HP+'t'))
            return bool(original) and original == native
    except (ValueError, TypeError, AttributeError, IndexError, KeyError, StopIteration):
        return False
