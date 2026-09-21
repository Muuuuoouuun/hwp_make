"""Measured, editable running-header fields and source vector decorations.

Fields share one native table row. Page numbers are automatic PAGE controls;
the source page number is never copied as a repeating literal. Decorations
contain only source line segments, with no text pictures or glyph outlines.
"""
from copy import deepcopy
import re
from statistics import median
from xml.etree import ElementTree

from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"


def _record(span, chars):
    chars = [c for c in chars if (c.get('c') or '').strip()]
    if not chars or not span.get('origin') or not span.get('size'):
        return None
    return {'text': ''.join(c['c'] for c in chars),
            'bbox_pt': [min(c['bbox'][0] for c in chars), min(c['bbox'][1] for c in chars),
                        max(c['bbox'][2] for c in chars), max(c['bbox'][3] for c in chars)],
            'baseline_pt': span['origin'][1], 'font': span['font'],
            'size_pt': span['size'], 'bold': bool(span.get('flags', 0) & 16)}


def measure_running_furniture(page, body_top, subject):
    """Recognize all three fields independently on this source page, or abstain."""
    if not hasattr(page, 'get_drawings'):
        return None
    fields = {'subject': [], 'grade': [], 'page': []}
    rules = []
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines', []):
            if line['bbox'][3] >= body_top:
                continue
            content = ''.join(c.get('c', '') for s in line['spans'] for c in s.get('chars', [])).strip()
            if content and set(content) <= set('━─— '):
                rules.append(line['bbox'])
            for span in line['spans']:
                chars = span.get('chars', [])
                text = ''.join(c.get('c', '') for c in chars).strip()
                kind = ('subject' if re.sub(r'\s+', '', text) == re.sub(r'\s+', '', subject)
                        else 'grade' if re.fullmatch(r'(?:초|중|고)\s*[1-6]', text)
                        else 'page' if text == str(page.number + 1) else None)
                if kind and (record := _record(span, chars)):
                    if kind != 'page' or record['bbox_pt'][0] < page.rect.width*.2 or record['bbox_pt'][0] > page.rect.width*.8:
                        fields[kind].append(record)
    if any(len(records) != 1 for records in fields.values()):
        return None
    fields = {kind: records[0] for kind, records in fields.items()}
    # An alternating number at the outer edge is proof of the page-side role.
    fields['page']['align'] = 'LEFT' if fields['page']['bbox_pt'][0] < page.rect.width/2 else 'RIGHT'
    grade = fields['grade']['bbox_pt']
    outlines = []
    for drawing in page.get_drawings():
        box = drawing['rect']
        if (drawing['type'] not in ('s', 'fs') or not drawing.get('width')
            or drawing.get('color') != (0., 0., 0.) or drawing.get('stroke_opacity', 1) != 1
            or box.y1 >= body_top or box.width > page.rect.width*.2
            or not (box.x0 <= grade[0] and box.x1 >= grade[2]
                    and box.y0 <= grade[1]+3 and box.y1 >= grade[3]-3)
            or not all(item[0] == 'l' for item in drawing['items'])):
            continue
        segments = [[list(item[1]), list(item[2])] for item in drawing['items']]
        if not segments or any(a[1] != b[0] for a, b in zip(segments, segments[1:])):
            continue
        if max(abs(a-b) for a, b in zip(segments[0][0], segments[-1][1])) > .5:
            continue
        outlines.append({'bbox_pt': list(box), 'width_pt': drawing['width'],
                         'points_pt': [segments[0][0], *[s[1] for s in segments]]})
    rule = None
    if len(rules) == 1 and rules[0][2]-rules[0][0] > page.rect.width*.65:
        # The rule is a row of box-drawing glyphs in some PDFs. Measure its
        # painted ink; export a native line, never the measurement bitmap.
        import fitz
        import numpy as np
        pix = page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=fitz.Rect(rules[0]),
                             colorspace=fitz.csGRAY, alpha=False)
        dark = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width) < 160
        rows = np.flatnonzero(dark.sum(axis=1) > pix.width*.9)
        if len(rows) and rows[-1]-rows[0]+1 == len(rows):
            columns = np.flatnonzero(dark[rows].sum(axis=0) >= max(1, len(rows)//2))
            if len(columns):
                rule = {'left_pt': (pix.x+columns[0])/4, 'right_pt': (pix.x+columns[-1]+1)/4,
                        'y_pt': (pix.y+(rows[0]+rows[-1]+1)/2)/4, 'width_pt': len(rows)/4}
                rule = {key: float(value) for key, value in rule.items()}
    return {'fields': fields, 'grade_outline': outlines[0] if len(outlines) == 1 else None,
            'horizontal_rule': rule,
            'page_width_pt': page.rect.width, 'body_top_pt': body_top}


def _coherent(records):
    if not records or any(not r.get('furniture') for r in records):
        return False
    if len({round(r['page_width_pt'], 2) for r in records}) != 1:
        return False
    for kind in ('subject', 'grade', 'page'):
        fields = [r['furniture']['fields'][kind] for r in records]
        if kind != 'page' and len({f['text'] for f in fields}) != 1:
            return False
        if len({(f['font'], round(f['size_pt'], 1), f['bold'], f.get('align')) for f in fields}) != 1:
            return False
        # Printed page-number widths vary. Its outer anchor must stay fixed.
        anchors = [f['bbox_pt'][2 if f.get('align') == 'RIGHT' else 0] for f in fields]
        if max(anchors)-min(anchors) > 2 or max(f['baseline_pt'] for f in fields)-min(f['baseline_pt'] for f in fields) > 2:
            return False
    for key in ('grade_outline', 'horizontal_rule'):
        decorations = [r['furniture'].get(key) for r in records]
        if len({bool(d) for d in decorations}) != 1:
            return False
        if not decorations[0]:
            continue
        coordinates = ('width_pt', 'left_pt', 'right_pt', 'y_pt') if key == 'horizontal_rule' else ('width_pt',)
        if any(max(d[k] for d in decorations)-min(d[k] for d in decorations) > 2 for k in coordinates):
            return False
        if key == 'grade_outline':
            if len({len(d['points_pt']) for d in decorations}) != 1:
                return False
            if any(max(d['bbox_pt'][i] for d in decorations)-min(d['bbox_pt'][i] for d in decorations) > 2 for i in range(4)):
                return False
    return True


def _paragraph_style(document, align):
    header = document.headers[0].element
    properties = header.find('.//' + HH+'paraProperties')
    style = deepcopy(properties[0])
    identifier = str(max(int(p.get('id')) for p in properties)+1)
    style.set('id', identifier)
    style.find(HH+'align').set('horizontal', align)
    for margin in style.findall('.//' + HH+'margin'):
        for child in margin:
            child.set('value', '0')
            child.set('unit', 'HWPUNIT')
    for spacing in style.findall('.//' + HH+'lineSpacing'):
        spacing.set('type', 'PERCENT'); spacing.set('value', '100'); spacing.set('unit', 'PERCENT')
    properties.append(style)
    properties.set('itemCnt', str(len(properties)))
    document.headers[0].mark_dirty()
    return identifier


def _cache(paragraph, height, width):
    array = etree.SubElement(paragraph, HP+'linesegarray')
    etree.SubElement(array, HP+'lineseg', textpos='0', vertpos='0', vertsize=str(round(height)),
                     textheight=str(round(height)), baseline=str(round(height*.85)), spacing='0',
                     horzpos='0', horzsize=str(round(width)), flags='393216')


def apply_running_furniture(document, records, body_top):
    """Return evidence only if each parity has a complete, consistent source."""
    from hwpx.oxml._document_impl import HwpxOxmlTable, _create_rectangle_element, _create_line_element
    from .pdf_native_typography import _font_name

    groups = {kind: [r for r in records if r['page'] % 2 == parity]
              for kind, parity in (('EVEN', 0), ('ODD', 1))}
    groups = {kind: group for kind, group in groups.items() if group}
    if not all(_coherent(group) for group in groups.values()):
        return None
    section = document.sections[1]
    props = section.properties
    width = props.page_size.width
    left = props.page_margins.left
    available = width-left-props.page_margins.right
    scale = width / records[0]['page_width_pt']
    sources = {}
    for kind, group in groups.items():
        source = deepcopy(group[0]['furniture'])
        for role, field in source['fields'].items():
            peers = [r['furniture']['fields'][role] for r in group]
            field['baseline_pt'] = median(f['baseline_pt'] for f in peers)
        sources[kind] = source
    top = round(min([f['baseline_pt']-f['size_pt']*.85 for s in sources.values() for f in s['fields'].values()]
                    + [s['grade_outline']['bbox_pt'][1] for s in sources.values() if s.get('grade_outline')])*scale)
    ends = {kind: round(max(f['baseline_pt']+f['size_pt']*.15 for f in s['fields'].values())*scale)
            for kind, s in sources.items()}
    if not 0 < top < min(ends.values()) <= max(ends.values()) < body_top:
        return None
    if any(f['bbox_pt'][0]*scale < left-2 or f['bbox_pt'][2]*scale > left+available+2
           for s in sources.values() for f in s['fields'].values()):
        return None
    header = document.headers[0].element
    none = next((b for b in header.iter(HH+'borderFill') if all(
        (edge := b.find(HH+kind+'Border')) is not None and edge.get('type') == 'NONE'
        for kind in ('left', 'right', 'top', 'bottom'))), None)
    if none is None:
        return None
    styles = {align: _paragraph_style(document, align) for align in ('LEFT', 'RIGHT')}
    identifier = max(int(n.get('id')) for n in section.element.iter() if n.get('id', '').isdigit())+1

    def pid():
        nonlocal identifier
        identifier += 1
        return str(identifier)

    def paragraph(align='LEFT'):
        return etree.Element(HP+'p', id=pid(), paraPrIDRef=styles[align], styleIDRef='0',
                             pageBreak='0', columnBreak='0', merged='0')

    document.set_page_margins(section_index=1, top=top, header=body_top-top)
    # Remove only the converter's previous BOTH header before adding both sides.
    props.remove_header('BOTH')
    for kind, source in sources.items():
        height = ends[kind]-top
        entries = sorted(source['fields'].items(), key=lambda item: item[1]['bbox_pt'][0])
        # Right-aligned page numbers occupy a stable outer cell, sized for the
        # widest source page number in this parity (e.g. page 9 -> page 11).
        for role, field in entries:
            if field.get('align') == 'RIGHT':
                peers = [r['furniture']['fields'][role] for r in groups[kind]]
                field['bbox_pt'][0] = min(f['bbox_pt'][0] for f in peers)
                field['bbox_pt'][2] = median(f['bbox_pt'][2] for f in peers)
        cells = [(max(0, round(f['bbox_pt'][0]*scale-left)), role, f) for role, f in entries]
        if cells[0][0] > 0:
            cells.insert(0, (0, None, None))
        table = etree.fromstring(ElementTree.tostring(HwpxOxmlTable.create(
            1, len(cells), width=available, height=height, border_fill_id_ref=none.get('id'))))
        table.set('id', pid())
        table.find(HP+'pos').set('affectLSpacing', '1')
        for tag in ('inMargin', 'outMargin'):
            for edge in table.find(HP+tag).attrib:
                table.find(HP+tag).set(edge, '0')
        for i, (cell, (start, role, field)) in enumerate(zip(table.findall(HP+'tr/'+HP+'tc'), cells)):
            end = cells[i+1][0] if i+1 < len(cells) else available
            cell.set('name', 'source-running:'+str(role or 'spacer'))
            cell.set('hasMargin', '1'); cell.set('editable', '1')
            cell.find(HP+'cellSz').set('width', str(end-start))
            margins = cell.find(HP+'cellMargin')
            for edge in margins.attrib:
                margins.set(edge, '0')
            sub = cell.find(HP+'subList')
            sub.set('vertAlign', 'TOP'); sub.set('textWidth', str(end-start)); sub.set('textHeight', str(height))
            for child in list(sub):
                sub.remove(child)
            p = paragraph(field.get('align', 'LEFT') if field else 'LEFT')
            size = field['size_pt']*scale if field else 1
            char = document.ensure_run_style(font=_font_name(field['font']), size=size/100,
                                             bold=field['bold']) if field else '0'
            run = etree.SubElement(p, HP+'run', charPrIDRef=char)
            if role == 'page':
                ctrl = etree.SubElement(run, HP+'ctrl')
                number = etree.SubElement(ctrl, HP+'autoNum', num='1', numType='PAGE')
                etree.SubElement(number, HP+'autoNumFormat', type='DIGIT', userChar='', prefixChar='', suffixChar='', superscript='0')
            else:
                etree.SubElement(run, HP+'t').text = field['text'] if field else ''
            _cache(p, size, end-start)
            sub.append(p)
            if field:
                margins.set('top', str(max(0, round(field['baseline_pt']*scale-top-size*.85))))
                if field.get('align') == 'RIGHT':
                    margins.set('right', str(max(0, round(left+end-field['bbox_pt'][2]*scale))))
        wrapper = props.set_header_content([], page_type=kind)
        sub = wrapper._ensure_sublist()
        sub.set('textWidth', str(available)); sub.set('textHeight', str(body_top-top))
        host = paragraph()
        etree.SubElement(host, HP+'run', charPrIDRef='0').append(table)
        _cache(host, height, available)
        sub.append(host)
        decoration = paragraph()
        outline = source.get('grade_outline')
        if outline:
            bounds = outline['bbox_pt']
            shape = etree.fromstring(ElementTree.tostring(_create_rectangle_element(
                round((bounds[2]-bounds[0])*scale), round((bounds[3]-bounds[1])*scale),
                line_width=str(round(outline['width_pt']*scale)), treat_as_char=False)))
            shape.tag = HP+'polygon'
            shape.attrib.pop('ratio', None)
            shape.set('id', pid()); shape.set('instid', pid())
            for child in list(shape):
                if etree.QName(child).localname.startswith('pt'):
                    shape.remove(child)
            for x, y in outline['points_pt']:
                etree.SubElement(shape, HC+'pt', x=str(round((x-bounds[0])*scale)), y=str(round((y-bounds[1])*scale)))
            pos = shape.find(HP+'pos')
            pos.set('vertRelTo', 'PARA'); pos.set('horzRelTo', 'COLUMN')
            pos.set('vertOffset', str(round(bounds[1]*scale-top)))
            pos.set('horzOffset', str(round(bounds[0]*scale-left)))
            shape.set('textWrap', 'IN_FRONT_OF_TEXT')
            for margins in shape.findall(HP+'outMargin'):
                for edge in margins.attrib:
                    margins.set(edge, '0')
            etree.SubElement(decoration, HP+'run', charPrIDRef='0').append(shape)
        rule = source.get('horizontal_rule')
        if rule:
            line = etree.fromstring(ElementTree.tostring(_create_line_element(
                0, 0, round((rule['right_pt']-rule['left_pt'])*scale), 0,
                line_width=str(max(1, round(rule['width_pt']*scale))), treat_as_char=False)))
            line.set('id', pid()); line.set('instid', pid()); line.set('textWrap', 'IN_FRONT_OF_TEXT')
            pos = line.find(HP+'pos')
            pos.set('vertRelTo', 'PARA'); pos.set('horzRelTo', 'COLUMN')
            pos.set('vertOffset', str(round(rule['y_pt']*scale-top)))
            pos.set('horzOffset', str(round(rule['left_pt']*scale-left)))
            for margins in line.findall(HP+'outMargin'):
                for edge in margins.attrib:
                    margins.set(edge, '0')
            etree.SubElement(decoration, HP+'run', charPrIDRef='0').append(line)
        if len(decoration):
            _cache(decoration, 1, available)
            sub.insert(0, decoration)
        props._sync_header_footer_control('header', wrapper.element)
    section.mark_dirty()
    return {'applied': True, 'source_pages': len(records), 'text': records[0]['text'],
            'body_top_hwp': body_top, 'header_top_hwp': top,
            'page_numbers_restored': True, 'native_page_number_fields': len(groups),
            'grade_restored': True, 'parity_headers': list(groups),
            'grade_outlines': sum(bool(s.get('grade_outline')) for s in sources.values()),
            'horizontal_rule_restored': all(bool(s.get('horizontal_rule')) for s in sources.values()),
            'footer_restored': False}
