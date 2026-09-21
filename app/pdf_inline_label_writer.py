"""Restore source-drawn answer labels as inline, editable native textboxes."""
from copy import deepcopy
import re
from xml.etree import ElementTree

import fitz
from lxml import etree

from .pdf_inline_labels import HP, LABEL

NAME = 'source-inline-label'


def _can_split_equation(text, start, end):
    """A framed label can replace a top-level term, never a math argument."""
    before, after = text[:start], text[end:]
    if any(mark in text for mark in ('"', "'", '\\')):
        return False
    for value in (before, after):
        stack = []
        for char in value:
            if char in '({[':
                stack.append(char)
            elif char in ')}]':
                if not stack or '({['[')}]'.index(char)] != stack.pop():
                    return False
        if stack:
            return False
    operator = r'(?:[=+\-*/<>]|\b(?:LEQ|GEQ|NEQ|TIMES|DIV)\b)'
    return (not before.strip() or re.search(operator+r'\s*$', before) is not None) and (
        not after.strip() or re.match(r'\s*'+operator, after) is not None)


def associate_inline_labels(records, labels):
    """Map measured labels to exact offsets in the complete source text."""
    if not labels:
        return []
    from .pdf_layout_writer import _pdf_output_text
    from .pdf_source_line_cache import source_line_values

    values = source_line_values(records, mixed=True)
    if len(values) != len(records) or not all(values):
        return []
    result, offset = [], 0
    for index, (record, value) in enumerate(zip(records, values)):
        glyphs = [g for span in record.get('spans', []) for g in span.get('chars', [])]
        glyphs.sort(key=lambda g: g['origin'][0])
        raw = ''.join(_pdf_output_text(g['c']) for g in glyphs)
        raw_matches, matches = list(LABEL.finditer(raw)), list(LABEL.finditer(value))
        if len(raw) == len(glyphs) and [m.group() for m in raw_matches] == [m.group() for m in matches]:
            for raw_match, match in zip(raw_matches, matches):
                ink = fitz.Rect(glyphs[raw_match.start()]['bbox'])
                for glyph in glyphs[raw_match.start()+1:raw_match.end()]:
                    ink |= fitz.Rect(glyph['bbox'])
                owners = [label for label in labels
                          if label['text'] == match.group()
                          and fitz.Rect(label['bbox_pt']).contains(ink)]
                if len(owners) == 1:
                    entry = {**owners[0], 'offset': offset + match.start(), 'line': index}
                    result.append(entry)
                    record.setdefault('inline_labels', []).append(entry)
                    record['bbox_pt'] = list(fitz.Rect(record['bbox_pt']) | fitz.Rect(entry['bbox_pt']))
        offset += len(value)
    return result


def restore_inline_labels(root, layout, page_width, char_style, para_style):
    """Substitute labels in place; preserve their surrounding native paragraph."""
    from .pdf_source_line_cache import source_line_values
    from .pdf_native_typography import _font_name
    from hwpx.oxml._document_impl import _create_rectangle_element

    labels = layout.get('source_inline_labels') or []
    meta = layout.get('source_typography') or {}
    if not labels:
        return 0
    tables = root.findall(HP+'run/'+HP+'tbl')
    if tables:
        cells = tables[0].findall(HP+'tr/'+HP+'tc')
        if len(tables) != 1 or len(cells) != 1 or cells[0].find('.//'+HP+'tbl') is not None:
            return 0
        paragraphs = cells[0].findall(HP+'subList/'+HP+'p')
    else:
        paragraphs = [root]
    children, cursor, value = [], 0, ''
    for paragraph in paragraphs:
        for run in paragraph.findall(HP+'run'):
            for child in run:
                if child.tag == HP+'t' and not len(child):
                    text = child.text or ''
                elif child.tag == HP+'equation':
                    text = child.findtext(HP+'script', '')
                else:
                    return 0
                compact = re.sub(r'\s+', '', text)
                children.append((child, paragraph, cursor, cursor+len(compact), text))
                value += compact
                cursor += len(compact)
    if value != ''.join(source_line_values(meta.get('lines', []), mixed=True)):
        return 0
    plans, intervals = {}, []
    for label in labels:
        start, end = label['offset'], label['offset'] + len(label['text'])
        if (start < 0 or end > len(value) or not LABEL.fullmatch(label['text'])
            or value[start:end] != label['text']
            or any(start < b and a < end for a, b in intervals)):
            return 0
        intervals.append((start, end))
        owner = next((entry for entry in children if entry[2] <= start and end <= entry[3]), None)
        if owner is None:
            return 0
        child, paragraph, a, _, text = owner
        positions = [i for i, char in enumerate(text) if not char.isspace()]
        first, last = positions[start-a], positions[end-a-1]+1
        if child.tag == HP+'equation' and not _can_split_equation(text, first, last):
            return 0
        plans.setdefault(child, []).append((first, last, label))
    scale = page_width / float(layout['source_page_width_pt'])
    section = root.getroottree().getroot()
    next_id = max((int(n.get('id')) for n in section.iter() if n.get('id', '').isdigit()), default=0)+1

    def identifier():
        nonlocal next_id
        value = str(next_id)
        next_id += 1
        return value

    for child, replacements in plans.items():
        run = child.getparent()
        source = child.text if child.tag == HP+'t' else child.findtext(HP+'script', '')
        index, cursor = run.index(child), 0
        fragments = []
        for start, end, label in sorted(replacements):
            if source[cursor:start]:
                fragments.append(source[cursor:start])
            width = round((label['bbox_pt'][2]-label['bbox_pt'][0])*scale)
            height = round((label['bbox_pt'][3]-label['bbox_pt'][1])*scale)
            size = label['font_size_pt']*scale
            shape = etree.fromstring(ElementTree.tostring(_create_rectangle_element(
                width, height, line_width=str(max(1, round(label['line_width_pt']*scale))),
                fill_color=None, treat_as_char=True)))
            shape_id = identifier()
            shape.set('id', shape_id)
            shape.set('instid', shape_id)
            shape.set('lock', '0')
            for margins in shape.findall(HP+'outMargin'):
                for side in ('left', 'right', 'top', 'bottom'):
                    margins.set(side, '0')
            draw = etree.Element(HP+'drawText', lastWidth=str(width), name=NAME, editable='1')
            etree.SubElement(draw, HP+'textMargin', left='0', right='0', top='0', bottom='0')
            sub = etree.SubElement(draw, HP+'subList', id='', textDirection='HORIZONTAL',
                lineWrap='BREAK', vertAlign='CENTER', linkListIDRef='0', linkListNextIDRef='0',
                textWidth=str(width), textHeight=str(height), hasTextRef='0', hasNumRef='0')
            p = etree.SubElement(sub, HP+'p', id=identifier(),
                paraPrIDRef=para_style('0', 'CENTER', size, size), styleIDRef='0',
                pageBreak='0', columnBreak='0', merged='0')
            r = etree.SubElement(p, HP+'run', charPrIDRef=char_style(
                run.get('charPrIDRef', '0'), size, _font_name(label['font']), 0, 100))
            etree.SubElement(r, HP+'t').text = label['text']
            cache = etree.SubElement(p, HP+'linesegarray')
            x = round((label['ink_bbox_pt'][0]-label['bbox_pt'][0])*scale)
            etree.SubElement(cache, HP+'lineseg', textpos='0', vertpos='0', vertsize=str(round(size)),
                textheight=str(round(size)), baseline=str(round(size*.85)), spacing='0',
                horzpos=str(x), horzsize=str(width), flags='393216')
            shadow = shape.find(HP+'shadow')
            shape.insert(shape.index(shadow) if shadow is not None else len(shape), draw)
            fragments.append(shape)
            cursor = end
        if source[cursor:]:
            fragments.append(source[cursor:])
        run.remove(child)
        for fragment in fragments:
            if isinstance(fragment, str):
                node = deepcopy(child)
                if node.tag == HP+'t':
                    node.text = fragment
                else:
                    node.set('id', identifier())
                    node.find(HP+'script').text = fragment
                fragment = node
            run.insert(index, fragment)
            index += 1
    return len(labels)
