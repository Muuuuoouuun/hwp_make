"""Restore measured wraps and paragraph gaps inside a native single-cell frame.

The complete cell text must match the ordered source lines. This does not turn
printed lines into paragraphs or insert line breaks into ordinary prose.
"""
from copy import deepcopy
import re
from statistics import median
from lxml import etree

from .pdf_source_line_cache import HP, apply_source_line_cache, source_line_values


def restore_background_frame(root, layout, header, page_width, column_width, para_style):
    """Restore a complete prose frame's source bounds and editable padding.

    This is deliberately limited to one source-confirmed cell. Partial frames,
    grids and mixed controls keep their existing reconstruction paths.
    """
    from .pdf_native_typography import _flow_height
    from hwpx.tools.paragraph_spacing import paragraph_spacing

    tables = root.findall(HP + 'run/' + HP + 'tbl')
    geometries = layout.get('native_tables') or []
    records = (layout.get('source_typography') or {}).get('lines') or []
    source_width = float(layout.get('source_page_width_pt') or 0)
    if len(tables) != 1 or len(geometries) != 1 or not records or not source_width:
        return 0
    table, geometry = tables[0], geometries[0]
    box = geometry.get('bbox_pt')
    cells = table.findall(HP + 'tr/' + HP + 'tc')
    if (not geometry.get('background_path') or not box or len(cells) != 1
        or geometry.get('cell_bounds') != [[box]]
        or any(table.find('.//' + HP + tag) is not None for tag in ('tbl', 'pic', 'rect', 'equation'))):
        return 0
    from .pdf_layout_writer import _pdf_output_text
    compact = lambda value: re.sub(r'\s+', '', _pdf_output_text(value))
    if (not geometry.get('background_source_text')
        or compact(geometry['background_source_text']) != compact(''.join(r['text'] for r in records))):
        # A decorative bitmap can span several source blocks. Fitting every
        # fragment to the whole bitmap repeats its height and hides siblings.
        return 0
    if any(r['bbox_pt'][0] < box[0] or r['bbox_pt'][1] < box[1]
           or r['bbox_pt'][2] > box[2] or r['bbox_pt'][3] > box[3] for r in records):
        return 0
    scale = page_width / source_width
    width, height = round((box[2] - box[0]) * scale), round((box[3] - box[1]) * scale)
    offset = round((box[0] - float(layout.get('column_left_pt') or box[0])) * scale)
    size = float(layout['source_typography'].get('font_size_pt') or 0) * scale
    left = round((min(r['bbox_pt'][0] for r in records) - box[0]) * scale)
    right = round((box[2] - max(r['bbox_pt'][2] for r in records)) * scale)
    top = round((records[0]['baseline_pt'] - box[1]) * scale - size * .85)
    steps = [(b['baseline_pt'] - a['baseline_pt']) * scale for a, b in zip(records, records[1:])]
    last_step = float(layout['source_typography'].get('line_spacing_pt') or 0) * scale
    # Reserve enough room before allocating styles or modifying paragraphs.
    required = top + (records[-1]['baseline_pt'] - records[0]['baseline_pt']) * scale + max([size, last_step, *steps]) + 200
    if (not 500 <= size <= 1600 or min(offset, left, right, top) < 0
        or offset + width > column_width + 2 or width - left - right <= size
        or required > height or any(step < size * .8 for step in steps)):
        return 0
    cell = cells[0]
    cell_size, margins = cell.find(HP + 'cellSz'), cell.find(HP + 'cellMargin')
    table_size, position = table.find(HP + 'sz'), table.find(HP + 'pos')
    if any(n is None for n in (cell_size, margins, table_size, position)):
        return 0
    saved = [(n, dict(n.attrib)) for n in (cell, cell_size, margins, table_size, position)]
    cell.set('hasMargin', '1')
    cell_size.set('width', str(width))
    table_size.set('width', str(width))
    position.set('horzOffset', str(offset))
    for side, value in (('left', left), ('right', right), ('top', top)):
        margins.set(side, str(value))
    restored = restore_table_paragraphs(root, {**layout, 'column_left_pt': box[0]}, header, page_width, para_style)
    if not restored:
        for node, attributes in saved:
            node.attrib.clear()
            node.attrib.update(attributes)
        return 0
    styles = {p.get('id'): p for p in header.iter('{http://www.hancom.co.kr/hwpml/2011/head}paraPr')}
    paragraphs = cell.findall(HP + 'subList/' + HP + 'p')
    content_height = sum(_flow_height(p) + sum(paragraph_spacing(p, styles)) for p in paragraphs)
    # The native row fitter reserves 200 units after its paragraph flow. Keep
    # the measured frame height without a fixed height or non-flowing text.
    margins.set('bottom', str(max(0, round(height - top - content_height - 200))))
    table_size.set('height', str(height))
    cell_size.set('height', str(height))
    return restored


def restore_table_paragraphs(root, layout, header, page_width, para_style):
    from .pdf_layout_writer import _pdf_output_text
    from .pdf_native_typography import _flow_height, _number
    from .pdf_source_spacing import set_space_after
    from .pdf_inline_labels import inline_label_text

    tables = root.findall(HP + "run/" + HP + "tbl")
    meta = layout.get("source_typography") or {}
    records = meta.get("lines") or []
    source_width = float(layout.get("source_page_width_pt") or 0)
    if len(tables) != 1 or not records or not source_width:
        return 0
    table = tables[0]
    cells = table.findall(HP + "tr/" + HP + "tc")
    if len(cells) != 1 or cells[0].find('.//' + HP + 'tbl') is not None:
        return 0
    cell = cells[0]
    paragraphs = cell.findall(HP + "subList/" + HP + "p")
    compact = lambda text: re.sub(r"\s+", "", text)
    mixed = any(p.find('.//' + HP + 'equation') is not None
                or p.find('.//' + HP + 'rect') is not None for p in paragraphs)
    source_values = source_line_values(records, mixed=mixed)
    if len(source_values) != len(records) or not all(source_values):
        return 0
    # Match whole native paragraphs, not substrings with repeated words. Any
    # unsupported control or missing/extra source line rejects this cell intact.
    groups, cursor = [], 0
    for p in paragraphs:
        children = [child for run in p.findall(HP + "run") for child in run]
        if not children or any(c.tag not in (HP + 't', HP + 'equation', HP + 'rect')
                               or c.tag == HP + 't' and len(c)
                               or c.tag == HP + 'rect' and inline_label_text(c) is None
                               for c in children):
            return 0
        value = compact(''.join(c.findtext(HP + 'script', '') if c.tag == HP + 'equation'
                                else inline_label_text(c) if c.tag == HP + 'rect'
                                else c.text or '' for c in children))
        start, matched = cursor, ''
        while cursor < len(records) and len(matched) < len(value):
            matched += source_values[cursor]
            cursor += 1
        if not value or matched != value:
            return 0
        groups.append((p, records[start:cursor]))
    if cursor != len(records):
        return 0

    scale = page_width / source_width
    margins = cell.find(HP + 'cellMargin')
    left_margin = _number(margins, 'left')
    width = _number(cell.find(HP + 'cellSz'), 'width') - left_margin - _number(margins, 'right')
    rail = float(layout.get('column_left_pt') or min(r['bbox_pt'][0] for r in records)) + left_margin / scale
    size = float(meta.get('font_size_pt') or 0) * scale
    if size <= 0 or width <= size:
        return 0
    from .pdf_verse import CREDIT, source_verse_stanzas
    stanzas = source_verse_stanzas(records, width / scale)
    char_styles = {r.get('charPrIDRef', '0') for p in paragraphs for r in p.findall(HP + 'run')}
    rewritten = bool(not mixed and stanzas and len(char_styles) == 1)
    if rewritten:
        # Only a fully matched, uniformly styled, source-confirmed verse frame
        # is regrouped. Each stanza stays one editable native paragraph;
        # intentional verse endings are native controls within that paragraph.
        groups = []
        next_id = max((int(n.get('id')) for n in root.getroottree().getroot().iter()
                       if n.get('id', '').isdigit()), default=0) + 1
        for index, lines in enumerate(stanzas):
            p = deepcopy(paragraphs[min(index, len(paragraphs) - 1)])
            if index >= len(paragraphs):
                p.set('id', str(next_id))
                next_id += 1
            for child in list(p):
                p.remove(child)
            run = etree.SubElement(p, HP + 'run', charPrIDRef=next(iter(char_styles)))
            for i, line in enumerate(lines):
                text = etree.SubElement(run, HP + 't')
                text.text = _pdf_output_text(line['text'])
                if i + 1 < len(lines):
                    etree.SubElement(text, HP + 'lineBreak')
            groups.append((p, lines))
    probes = []
    for p, lines in groups:
        left = round((min(r['bbox_pt'][0] for r in lines) - rail) * scale)
        if left < -2:
            return 0
        left = max(0, left)
        indent = round((lines[0]['bbox_pt'][0] - lines[1]['bbox_pt'][0]) * scale) if len(lines) > 1 else 0
        if abs(indent) > size * 3:
            indent = 0
        probe = deepcopy(p)
        candidate = {**layout, 'native_page_width': page_width,
                     'column_left_pt': rail, 'native_indentation': (left, 0, indent),
                     'source_typography': {**meta, 'lines': lines}}
        if not apply_source_line_cache(probe, candidate, width):
            return 0
        gaps = [(b['baseline_pt'] - a['baseline_pt']) * scale for a, b in zip(lines, lines[1:])]
        step = median(gaps) if gaps else float(meta.get('line_spacing_pt') or size / scale * 1.5) * scale
        alignment = 'JUSTIFY' if not rewritten and len(lines) > 1 and meta.get('alignment') == 'JUSTIFY' else 'LEFT'
        right = 0
        if (rewritten and len(lines) == 1 and CREDIT.fullmatch(lines[0]['text'].strip())
            and left > width * .4):
            # A credit printed at the right edge is a right-aligned paragraph.
            # Encoding its starting x as a huge left margin leaves only the
            # original text's width for editing and can wrap unchanged text.
            right = max(0, round(width - (lines[0]['bbox_pt'][2] - rail) * scale))
            left = indent = 0
            alignment = 'RIGHT'
            probe.find(HP + 'linesegarray/' + HP + 'lineseg').set('horzpos', '0')
        probes.append((p, probe, lines, left, step, indent, right, alignment))

    if rewritten:
        sub = cell.find(HP + 'subList')
        for p in paragraphs:
            sub.remove(p)
        for p, _ in groups:
            sub.append(p)
    for p, probe, lines, left, step, indent, right, alignment in probes:
        # Indentation and line spacing remain ordinary native properties after
        # a user edits the text and invalidates these measured caches.
        p.set('paraPrIDRef', para_style(p.get('paraPrIDRef', '0'), alignment, step, size, left, indent, right))
        cache = p.find(HP + 'linesegarray')
        if cache is not None:
            p.remove(cache)
        p.append(probe.find(HP + 'linesegarray'))
    # Add cloned spacing styles after all para_style callbacks have allocated
    # their own IDs, so the caller's style cache cannot reuse an added ID.
    for index, (p, probe, lines, left, step, indent, right, alignment) in enumerate(probes):
        if index + 1 < len(probes):
            next_lines = probes[index + 1][2]
            gap = (next_lines[0]['baseline_pt'] - lines[0]['baseline_pt']) * scale - _flow_height(p)
            if gap >= 1:
                set_space_after(p, header, gap)
    return len(probes)
