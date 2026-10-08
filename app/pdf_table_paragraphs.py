"""Restore measured wraps and paragraph gaps inside a native single-cell frame.

The complete cell text must match the ordered source lines. This does not turn
printed lines into paragraphs or insert line breaks into ordinary prose.
"""
from copy import deepcopy
import re
from statistics import median
from lxml import etree

from .pdf_source_line_cache import HP, apply_source_line_cache, source_line_values


def _set_terminal_letter_spacing(paragraph, records, header):
    """Keep a proved one-row letter ending's zero leading editable."""
    from .pdf_layout_writer import _pdf_output_text
    HH = '{http://www.hancom.co.kr/hwpml/2011/head}'
    texts = [_pdf_output_text(str(row.get('text') or '')).strip() for row in records]
    if (not texts or not re.fullmatch(r"Dear [A-Za-z][A-Za-z .'-]{0,60},|To whom it may concern,", texts[0])
        or not any(re.fullmatch(r'(?:Best|Kind|Warm) regards,|Sincerely,', value)
                   for value in texts[max(0, len(texts) - 3):-1])):
        return False
    children = [child for run in paragraph.findall(HP + 'run') for child in run]
    if (not children or any(child.tag != HP + 't' or len(child) for child in children)
        or _pdf_output_text(''.join(child.text or '' for child in children)).strip() != texts[-1]):
        return False
    arrays = paragraph.findall(HP + 'linesegarray')
    lines = arrays[0].findall(HP + 'lineseg') if len(arrays) == 1 else []
    if len(lines) != 1 or lines[0].get('spacing') != '0':
        return False
    styles = list(header.iter(HH + 'paraPr'))
    ids = [style.get('id') for style in styles]
    if (not ids or any(not re.fullmatch(r'0|[1-9][0-9]{0,9}', value or '') for value in ids)
        or len(ids) != len(set(ids)) or any(int(value) > 2147483647 for value in ids)):
        return False
    selected = [style for style in styles if style.get('id') == paragraph.get('paraPrIDRef')]
    if len(selected) != 1:
        return False
    style = selected[0]
    switches = style.findall(HP + 'switch')
    if len(switches) != 1 or len(switches[0]) != 2:
        return False
    cases, defaults = switches[0].findall(HP + 'case'), switches[0].findall(HP + 'default')
    if len(cases) != 1 or len(defaults) != 1:
        return False
    spacings = [node.findall(HH + 'lineSpacing') for node in (cases[0], defaults[0])]
    if any(len(nodes) != 1 for nodes in spacings):
        return False
    spacings = [nodes[0] for nodes in spacings]
    if (len(list(style.iter(HH + 'lineSpacing'))) != 2
        or any(node.get('type') != 'PERCENT' or node.get('unit') != 'PERCENT'
               or not re.fullmatch(r'[1-9][0-9]{0,2}', node.get('value', '')) for node in spacings)
        or not 100 <= int(spacings[0].get('value')) <= 300
        or spacings[0].get('value') != spacings[1].get('value')):
        return False
    parent = style.getparent()
    if (parent is None or any(node.getparent() is not parent for node in styles)
        or parent.get('itemCnt') != str(len(styles))):
        return False
    if spacings[0].get('value') == '100':
        return True
    next_id = max(map(int, ids)) + 1
    if next_id > 2147483647:
        return False
    # Independent spacing styles have already been allocated. Use the actual
    # header's current IDs rather than the caller's not-yet-refreshed cache.
    clone = deepcopy(style)
    clone.set('id', str(next_id))
    for node in clone.iter(HH + 'lineSpacing'):
        node.set('value', '100')
    parent.append(clone)
    parent.set('itemCnt', str(len(styles) + 1))
    paragraph.set('paraPrIDRef', str(next_id))
    return True


def restore_background_frame(root, layout, header, page_width, column_width, para_style, char_style=None):
    from .pdf_source_frame_native_rows import source_grid_frame_fragment, restore_source_grid_frame_fragment
    if source_grid_frame_fragment(layout):
        return restore_source_grid_frame_fragment(root, layout, header, page_width, column_width,
                                                 _restore_background_frame)
    return _restore_background_frame(root, layout, header, page_width, column_width, para_style, char_style)


def _restore_background_frame(root, layout, header, page_width, column_width, para_style, char_style=None,
                              *, native_rows=None):
    """Restore a complete prose frame's source bounds and editable padding.

    This is deliberately limited to one source-confirmed cell. Partial frames,
    grids and mixed controls keep their existing reconstruction paths.
    """
    from .pdf_native_typography import _flow_height
    from hwpx.tools.paragraph_spacing import paragraph_spacing
    if layout.get('source_dialogue_frame'):
        from .pdf_dialogue_frames import restore_dialogue_frame
        return restore_dialogue_frame(root,layout,header,page_width,column_width,para_style,char_style)

    tables = root.findall(HP + 'run/' + HP + 'tbl')
    geometries = layout.get('native_tables') or []
    records = (layout.get('source_typography') or {}).get('lines') or []
    source_width = float(layout.get('source_page_width_pt') or 0)
    if len(tables) != 1 or len(geometries) != 1 or not records or not source_width:
        return 0
    table, geometry = tables[0], geometries[0]
    box = geometry.get('bbox_pt')
    cells = table.findall(HP + 'tr/' + HP + 'tc')
    if (not (geometry.get('background_path') or geometry.get('source_prose_frame')) or not box or len(cells) != 1
        or geometry.get('cell_bounds') != [[box]]
        or any(table.find('.//' + HP + tag) is not None
               for tag in (('tbl', 'rect', 'equation') if geometry.get('images') else ('tbl', 'pic', 'rect', 'equation')))):
        return 0
    from .pdf_layout_writer import _pdf_output_text
    compact = lambda value: re.sub(r'\s+', '', _pdf_output_text(value))
    source_text = geometry.get('background_source_text') or geometry.get('source_frame_text')
    if (not source_text
        or compact(source_text) != compact(''.join(r['text'] for r in records))):
        # A decorative bitmap can span several source blocks. Fitting every
        # fragment to the whole bitmap repeats its height and hides siblings.
        return 0
    if any(r['bbox_pt'][0] < box[0] or r['bbox_pt'][1] < box[1]
           or r['bbox_pt'][2] > box[2] or r['bbox_pt'][3] > box[3] for r in records):
        return 0
    scale = page_width / source_width
    width, height = round((box[2] - box[0]) * scale), round((box[3] - box[1]) * scale)
    offset = round((box[0] - float(layout.get('column_left_pt') or box[0])) * scale)
    if geometry.get('source_prose_frame') and -50 <= offset < 0:
        offset = 0  # a source border stroke can extend slightly outside the text rail
    size = float(layout['source_typography'].get('font_size_pt') or 0) * scale
    left = round((min(r['bbox_pt'][0] for r in records) - box[0]) * scale)
    right = round((box[2] - max(r['bbox_pt'][2] for r in records)) * scale)
    top = round((records[0]['baseline_pt'] - box[1]) * scale - size * .85)
    if native_rows is not None:
        top = native_rows['top']
    steps = [(b['baseline_pt'] - a['baseline_pt']) * scale for a, b in zip(records, records[1:])]
    # Reserve enough room before allocating styles or modifying paragraphs.
    # Interline leading belongs between baselines, not after a complete
    # source frame's final line. Its remaining space is native cell padding.
    trailing_step = size
    reserve = 0 if geometry.get('images') else 200
    required = top + (records[-1]['baseline_pt'] - records[0]['baseline_pt']) * scale + max(size, trailing_step) + reserve
    if native_rows is not None:
        required = native_rows['required']
    from .pdf_wrapped_prose_frames import measured_wrapped_frame_width
    source_frame_width = measured_wrapped_frame_width(root,layout,page_width,column_width)
    frame_limit = source_frame_width if source_frame_width is not None else column_width
    if (not 500 <= size <= 1600 or min(offset, left, right, top) < 0
        or offset + width > frame_limit + 2 or width - left - right <= size
        or required > height or any(step < size * .8 for step in steps)):
        return 0
    cell = cells[0]
    cell_size, margins = cell.find(HP + 'cellSz'), cell.find(HP + 'cellMargin')
    table_size, position = table.find(HP + 'sz'), table.find(HP + 'pos')
    if any(n is None for n in (cell_size, margins, table_size, position)):
        return 0
    illustrated_original = deepcopy(root) if geometry.get('images') else None
    illustrated_pictures = None
    if illustrated_original is not None:
        from .pdf_illustrated_prose_frames import detach_source_frame_illustrations
        illustrated_pictures = detach_source_frame_illustrations(root, layout)
        if not isinstance(illustrated_pictures, list) or not illustrated_pictures:
            return 0
    saved = [(n, dict(n.attrib)) for n in (cell, cell_size, margins, table_size, position)]
    cell.set('hasMargin', '1')
    cell_size.set('width', str(width))
    table_size.set('width', str(width))
    position.set('horzOffset', str(offset))
    for side, value in (('left', left), ('right', right), ('top', top)):
        margins.set(side, str(value))
    # Allocate callback styles before restore_table_paragraphs adds independent
    # spacing styles. The callback's ID cache is refreshed by the caller only
    # after this function returns, so a later callback could reuse those IDs.
    root_style = (para_style(root.get('paraPrIDRef', '0'), 'LEFT', size, size, offset)
                  if geometry.get('source_prose_frame') else None)
    flow_root_style = (para_style(root.get('paraPrIDRef', '0'), 'LEFT', size, size)
                       if geometry.get('source_prose_frame') and offset >= 0 else None)
    restored = restore_table_paragraphs(root, {**layout, 'column_left_pt': box[0]}, header, page_width,
                                        para_style, char_style=char_style)
    if not restored:
        if illustrated_original is not None:
            root.attrib.clear()
            root.attrib.update(illustrated_original.attrib)
            for child in list(root):
                root.remove(child)
            root.extend(illustrated_original)
            return 0
        for node, attributes in saved:
            node.attrib.clear()
            node.attrib.update(attributes)
        return 0
    if illustrated_original is not None:
        from .pdf_illustrated_prose_frames import restore_illustrated_frame_cells
        if restore_illustrated_frame_cells(root, layout, header, page_width, column_width, illustrated_pictures, flow_root_style, char_style=char_style):
            root.set('paraPrIDRef',flow_root_style)
            return restored
        root.attrib.clear()
        root.attrib.update(illustrated_original.attrib)
        for child in list(root):
            root.remove(child)
        root.extend(illustrated_original)
        return 0
    if geometry.get('source_prose_frame'):
        from .pdf_source_frame_geometry import restore_source_prose_frame_position
        if restore_source_prose_frame_position(table, layout, page_width, column_width):
            root.set('paraPrIDRef', flow_root_style)
        else:
            position.set('treatAsChar', '1')
            position.set('horzOffset', '0')
            root.set('paraPrIDRef', root_style)
    if native_rows is not None:
        from .pdf_source_frame_native_rows import source_frame_native_rows, apply_source_frame_native_rows
        proved = source_frame_native_rows(root, layout, header, page_width, require_cache=True)
        if proved is None or not apply_source_frame_native_rows(proved, header):
            return 0
    paragraphs = cell.findall(HP + 'subList/' + HP + 'p')
    if paragraphs:
        # The final line's interline leading belongs between lines, not below
        # this source-measured frame's last line. Native text and table padding
        # provide the remaining bottom space and still reflow after editing.
        final_lines = paragraphs[-1].findall(HP + 'linesegarray/' + HP + 'lineseg')
        if final_lines:
            final_lines[-1].set('spacing', '0')
            if len(final_lines) == 1:
                _set_terminal_letter_spacing(paragraphs[-1], records, header)
    # The terminal style clone must participate in its preserved margins.
    styles = {p.get('id'): p for p in header.iter('{http://www.hancom.co.kr/hwpml/2011/head}paraPr')}
    content_height = sum(_flow_height(p) + sum(paragraph_spacing(p, styles)) for p in paragraphs)
    # The native row fitter reserves 200 units after its paragraph flow. Keep
    # the measured frame height without a fixed height or non-flowing text.
    margins.set('bottom', str(max(0, round(height - top - content_height - 200))))
    table_size.set('height', str(height))
    cell_size.set('height', str(height))
    return restored


def restore_table_paragraphs(root, layout, header, page_width, para_style, char_style=None):
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
        exact_frame = any(g.get('source_prose_frame') for g in layout.get('native_tables') or [])
        complete_frame = exact_frame or any(g.get('background_path') and g.get('background_source_text')
                                             for g in layout.get('native_tables') or [])
        group_size = (median(float(line.get('font_size_pt') or size / scale) for line in lines) * scale
                      if exact_frame else size)
        left = round((min(r['bbox_pt'][0] for r in lines) - rail) * scale)
        if left < -2:
            return 0
        left = max(0, left)
        indent = round((lines[0]['bbox_pt'][0] - lines[1]['bbox_pt'][0]) * scale) if len(lines) > 1 else 0
        if abs(indent) > size * 3:
            indent = 0
        alignment = 'JUSTIFY' if not rewritten and len(lines) > 1 and meta.get('alignment') == 'JUSTIFY' else 'LEFT'
        right = 0
        cache_lines = lines
        if complete_frame and not rewritten and len(lines) >= 3:
            # A prose paragraph and its smaller glossary share one frame,
            # but have independent printed right rails. Including the prose's
            # short final line in the whole-frame alignment vote incorrectly
            # makes a fully justified source paragraph left aligned.
            right_edges = [line['bbox_pt'][2] for line in lines[:-1]]
            if not mixed and not layout.get('source_answer_blanks'):
                # Some PDF producers append one justified space after each
                # printed row. Its bbox is not the prose's visible right rail.
                # Use the original non-space glyph bounds for both indentation
                # and the cache proof; retaining that invisible advance widens
                # the row enough to push native punctuation past its padding.
                ink_rights = [max((char['bbox'][2] for span in line.get('spans', [])
                                   for char in span.get('chars', [])
                                   if str(char.get('c') or '').strip()),
                                  default=line['bbox_pt'][2]) for line in lines]
                if any(line['bbox_pt'][2] - ink > .2 for line, ink in zip(lines, ink_rights)):
                    right_edges = ink_rights[:-1]
                    cache_lines = [{**line, 'bbox_pt': [*line['bbox_pt'][:2], ink, line['bbox_pt'][3]]}
                                   for line, ink in zip(lines, ink_rights)]
            if max(right_edges) - min(right_edges) < group_size / scale * .7:
                alignment = 'JUSTIFY'
                right = max(0, round(width - (max(right_edges) - rail) * scale))
        probe = deepcopy(p)
        candidate = {**layout, 'native_page_width': page_width,
                     'column_left_pt': rail, 'native_indentation': (left, right, indent),
                     'source_typography': {**meta, 'lines': cache_lines, 'font_size_pt': group_size / scale}}
        if cache_lines is not lines:
            # The ink refinement cannot excuse forged or overflowing source
            # line geometry. First prove the unmodified source boxes against
            # the native cell, before narrowing the paragraph's visible rail.
            original = {**candidate, 'native_indentation': (left, 0, indent),
                        'source_typography': {**meta, 'lines': lines, 'font_size_pt': group_size / scale}}
            if not apply_source_line_cache(deepcopy(p), original, width):
                return 0
        if not apply_source_line_cache(probe, candidate, width):
            return 0
        gaps = [(b['baseline_pt'] - a['baseline_pt']) * scale for a, b in zip(lines, lines[1:])]
        step = median(gaps) if gaps else float(meta.get('line_spacing_pt') or size / scale * 1.5) * scale
        if (rewritten and len(lines) == 1 and CREDIT.fullmatch(lines[0]['text'].strip())
            and left > width * .4):
            # A credit printed at the right edge is a right-aligned paragraph.
            # Encoding its starting x as a huge left margin leaves only the
            # original text's width for editing and can wrap unchanged text.
            right = max(0, round(width - (lines[0]['bbox_pt'][2] - rail) * scale))
            left = indent = 0
            alignment = 'RIGHT'
            probe.find(HP + 'linesegarray/' + HP + 'lineseg').set('horzpos', '0')
        probes.append((p, probe, lines, left, step, indent, right, alignment, group_size))

    if rewritten:
        sub = cell.find(HP + 'subList')
        for p in paragraphs:
            sub.remove(p)
        for p, _ in groups:
            sub.append(p)
    for p, probe, lines, left, step, indent, right, alignment, group_size in probes:
        # Indentation and line spacing remain ordinary native properties after
        # a user edits the text and invalidates these measured caches.
        p.set('paraPrIDRef', para_style(p.get('paraPrIDRef', '0'), alignment, step, group_size, left, indent, right))
        if (char_style is not None and abs(group_size - size) > .5
            and not layout.get('source_run_styles_applied')):
            # Small source glossaries/credits in the same frame must retain
            # their own measured size. Enlarging them to the prose's dominant
            # size clips native glyphs at the source frame's right edge.
            from .pdf_native_typography import _font_name
            font = _font_name((lines[0].get('spans') or [{}])[0].get('font')
                              or meta.get('font_name_recovered') or meta.get('font_name'))
            spacing = max(-15, min(15, round(float(meta.get('letter_spacing_percent') or 0))))
            ratio = max(80, min(110, round(float(meta.get('font_width_percent') or 100))))
            for run in p.findall(HP + 'run'):
                run.set('charPrIDRef', char_style(run.get('charPrIDRef', '0'), group_size, font, spacing, ratio))
        cache = p.find(HP + 'linesegarray')
        if cache is not None:
            p.remove(cache)
        p.append(probe.find(HP + 'linesegarray'))
    # Add cloned spacing styles after all para_style callbacks have allocated
    # their own IDs, so the caller's style cache cannot reuse an added ID.
    for index, (p, probe, lines, left, step, indent, right, alignment, group_size) in enumerate(probes):
        if index + 1 < len(probes):
            next_lines = probes[index + 1][2]
            gap = (next_lines[0]['baseline_pt'] - lines[0]['baseline_pt']) * scale - _flow_height(p)
            if gap >= 1:
                set_space_after(p, header, gap)
    return len(probes)
