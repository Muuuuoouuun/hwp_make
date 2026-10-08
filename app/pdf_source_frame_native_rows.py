"""Source-proved native font rows in a complete one-cell grid-frame fragment.

This path retains the ordinary cell and object reserves. It
does not confer source provenance on a persisted cache or editing signature.
"""
from __future__ import annotations

import io
import math
from copy import deepcopy

import fitz
from PIL import Image

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HH = '{http://www.hancom.co.kr/hwpml/2011/head}'
LANGS = {'hangul', 'latin', 'hanja', 'japanese', 'other', 'symbol', 'user'}


def _integer(value):
    if isinstance(value, bool):
        raise ValueError('boolean source-frame metric')
    number = float(value)
    if not math.isfinite(number) or number != round(number):
        raise ValueError('nonintegral source-frame metric')
    return int(number)


def _vector(value, length):
    result = tuple(float(n) for n in value)
    if len(result) != length or not all(math.isfinite(n) for n in result):
        raise ValueError('nonfinite source-frame geometry')
    return result


def _raw_signature(line):
    spans = []
    for span in line['spans']:
        size = float(span['size'])
        if not math.isfinite(size) or size <= 0:
            raise ValueError('invalid source font height')
        flags = _integer(span['flags'])
        chars = tuple((char['c'], _vector(char['origin'], 2), _vector(char['bbox'], 4))
                      for char in span['chars'])
        spans.append((span['font'], size, flags, _vector(span['origin'], 2),
                      _vector(span['bbox'], 4), chars))
    return tuple(spans)


def _native_style(run, styles, fonts):
    style = styles[run.get('charPrIDRef')]
    refs, ratios, tracking = (style.find(HH + tag) for tag in ('fontRef', 'ratio', 'spacing'))
    if any(node is None or set(node.attrib) != LANGS for node in (refs, ratios, tracking)):
        raise ValueError('incomplete source-frame style')
    family = {fonts[(lang.upper(), value)] for lang, value in refs.attrib.items()}
    ratio = {_integer(value) for value in ratios.attrib.values()}
    spacing = {_integer(value) for value in tracking.attrib.values()}
    if len(family) != 1 or len(ratio) != 1 or len(spacing) != 1:
        raise ValueError('mixed source-frame language styles')
    for tag, default in (('relSz', 100), ('offset', 0)):
        node = style.find(HH + tag)
        if (node is None or set(node.attrib) != LANGS
            or {_integer(value) for value in node.attrib.values()} != {default}):
            raise ValueError('nondefault source-frame font transform')
    if any(style.get(key) != value for key, value in
           (('useKerning', '0'), ('useFontSpace', '0'), ('symMark', 'NONE'))):
        raise ValueError('unsupported source-frame font mode')
    height = _integer(style.get('height'))
    if not 500 <= height <= 1600:
        raise ValueError('unsupported source-frame native height')
    for tag, attribute in (('outline', 'type'), ('shadow', 'type'), ('underline', 'type')):
        node = style.find(HH + tag)
        if node is not None and node.get(attribute) != 'NONE':
            raise ValueError('decorated source-frame font')
    if any(style.find(HH + tag) is not None for tag in
           ('strikeout', 'emboss', 'engrave', 'supscript', 'superscript', 'subscript')):
        raise ValueError('unsupported source-frame font effect')
    return (height, family.pop(), style.find(HH + 'bold') is not None,
            style.find(HH + 'italic') is not None, ratio.pop(), spacing.pop())


def _cache_bounds(paragraph, units, total):
    cache = paragraph.findall(HP + 'linesegarray/' + HP + 'lineseg')
    if not cache:
        raise ValueError('missing source-frame cache')
    boundaries = {position for position, char, height in units} | {total}
    bounds = [_integer(line.get('textpos')) for line in cache] + [total]
    if (bounds[0] != 0 or any(position not in boundaries for position in bounds)
        or any(a >= b for a, b in zip(bounds, bounds[1:]))):
        raise ValueError('invalid source-frame UTF-16 boundary')
    for index, line in enumerate(cache):
        height, textheight, baseline, spacing = (_integer(line.get(key)) for key in
                                                 ('vertsize', 'textheight', 'baseline', 'spacing'))
        represented = [height for position, char, height in units if bounds[index] <= position < bounds[index + 1]]
        if (not represented or not 0 < baseline < textheight <= height or spacing < 0
            or _integer(line.get('vertpos')) < 0 or _integer(line.get('horzpos')) < 0
            or _integer(line.get('horzsize')) <= 0 or textheight < max(represented)):
            raise ValueError('invalid source-frame current cache')
    return cache, bounds


def source_frame_native_rows(root, layout, header, page_width, *, require_cache=False):
    """Return an independently proved row plan, or abstain without mutation."""
    try:
        from app.pdf_native_typography import _font_name
        from app.pdf_layout_writer import _pdf_output_text, is_hancom_eq_font
        from app.pdf_source_run_styles import _source_latin_tracking
        from app.pdf_source_backgrounds import compose_source_background, prove_background_source_text
        from app.pdf_native_content import _source_typography
        from app import storage

        geometries = layout.get('native_tables') or []
        records = (layout.get('source_typography') or {}).get('lines') or []
        if (layout.get('source_content') is not True or layout.get('source_literal_text') is not True
            or layout.get('source_frame_has_grid') is not True or len(geometries) != 1 or not records
            or layout.get('source_answer_blanks')):
            return None
        geometry = geometries[0]
        box = fitz.Rect(_vector(geometry['bbox_pt'], 4))
        tables = root.findall(HP + 'run/' + HP + 'tbl')
        if (box.is_empty or box.is_infinite or geometry.get('source_grid_bbox_pt')
            or not geometry.get('background_path') or geometry.get('images')
            or geometry.get('cell_bounds') != [[geometry['bbox_pt']]] or len(tables) != 1):
            return None
        table = tables[0]
        cells = table.findall(HP + 'tr/' + HP + 'tc')
        if len(cells) != 1 or any(table.find('.//' + HP + tag) is not None
                                  for tag in ('tbl', 'pic', 'rect', 'equation')):
            return None
        scale = float(page_width) / float(layout['source_page_width_pt'])
        if not math.isfinite(scale) or scale <= 0:
            return None
        index = _integer(layout['source_page_index'])
        with fitz.open(layout['source_pdf_path']) as document:
            if not 0 <= index < len(document):
                return None
            page = document[index]
            if page.rect.width != float(layout['source_page_width_pt']) or not page.rect.contains(box):
                return None
            raw = sorted((line for block in page.get_text('rawdict')['blocks'] for line in block.get('lines', [])
                          if box.contains(fitz.Rect(line['bbox']))), key=lambda line: (line['bbox'][1], line['bbox'][0]))
            if len(raw) != len(records):
                return None
            for actual, supplied in zip(raw, records):
                if (tuple(actual['dir']) != (1.0, 0.0) or actual.get('wmode', 0) != 0
                    or _raw_signature(actual) != _raw_signature(supplied)
                    or _vector(actual['bbox'], 4) != _vector(supplied['bbox_pt'], 4)
                    or _pdf_output_text(''.join(c['c'] for s in actual['spans'] for c in s['chars'])).strip() != supplied['text']
                    or abs(actual['spans'][0]['origin'][1] - float(supplied['baseline_pt'])) > .001):
                    return None
            converted = [{**line, 'spans': [{**span, 'text': ''.join(char['c'] for char in span['chars'])}
                                           for span in line['spans']]} for line in raw]
            canonical_meta = _source_typography(converted, {'rect': box})
            meta = layout['source_typography']
            if (any(meta.get(key) != canonical_meta.get(key) for key in
                    ('font_name', 'font_size_pt', 'line_spacing_pt', 'alignment',
                     'font_width_percent', 'letter_spacing_percent', 'letter_spacing_sample_count'))
                or _integer(meta.get('letter_spacing_sample_count')) != canonical_meta['letter_spacing_sample_count']):
                return None
            images = [block for block in page.get_text('dict')['blocks']
                      if block.get('type') == 1 and fitz.Rect(block['bbox']).intersects(box)]
            if not images:
                return None
            expected = compose_source_background(page, box, [image['number'] for image in images])
            asset = storage.resolve_data_image_path(geometry['background_path'])
            if asset is None:
                return None
            with Image.open(io.BytesIO(expected)) as a, Image.open(asset) as b:
                if a.size != b.size or a.convert('RGB').tobytes() != b.convert('RGB').tobytes():
                    return None
            if not prove_background_source_text(page, box, expected, ''.join(r['text'] for r in records))['ok']:
                return None

        meta = layout['source_typography']
        default_spacing = max(-15, min(15, round(float(meta.get('letter_spacing_percent') or 0))))
        ratio = max(80, min(110, round(float(meta.get('font_width_percent') or 100))))
        source = []
        for row_index, record in enumerate(records):
            for span in record['spans']:
                if is_hancom_eq_font(span['font']):
                    return None
                flags = _integer(span['flags'])
                family = _font_name(span['font'])
                props = (round(float(span['size']) * scale), family,
                         bool(flags & 16 or 'bold' in span['font'].lower()),
                         bool(flags & 2 or 'italic' in span['font'].lower()), ratio,
                         _source_latin_tracking(span, family, default_spacing))
                for char in span['chars']:
                    value = _pdf_output_text(char['c'])
                    if not value.isspace():
                        if len(value) != 1:
                            return None
                        source.append((value, row_index, props))
        if not source:
            return None
        styles = {n.get('id'): n for n in header.iter(HH + 'charPr')}
        fonts = {(face.get('lang'), font.get('id')): font.get('face')
                 for face in header.iter(HH + 'fontface') for font in face.findall(HH + 'font')}
        paragraphs = cells[0].findall(HP + 'subList/' + HP + 'p')
        cursor = 0
        groups = []
        for paragraph in paragraphs:
            if any(child.tag not in (HP + 'run', HP + 'linesegarray') for child in paragraph):
                return None
            units, nonspace = [], []
            offset = 0
            for run in paragraph.findall(HP + 'run'):
                if any(child.tag != HP + 't' or len(child) for child in run):
                    return None
                text = ''.join(child.text or '' for child in run)
                if not text:
                    return None
                props = _native_style(run, styles, fonts)
                for char in text:
                    if cursor >= len(source):
                        return None
                    # Writer-normalized inter-row spaces inherit the following
                    # proved source glyph's style, as restore_source_run_styles does.
                    if props != source[cursor][2]:
                        return None
                    units.append((offset, char, props[0]))
                    offset += len(char.encode('utf-16-le')) // 2
                    if not char.isspace():
                        if char != source[cursor][0]:
                            return None
                        nonspace.append((source[cursor][1], offset - len(char.encode('utf-16-le')) // 2))
                        cursor += 1
            if not nonspace:
                return None
            indices = sorted({row for row, position in nonspace})
            if indices != list(range(indices[0], indices[-1] + 1)):
                return None
            if any(sum(row == ri for row, position in nonspace) != sum(row == ri for char, row, props in source)
                   for ri in indices):
                return None
            cache, current_bounds = _cache_bounds(paragraph, units, offset)
            starts = [0] + [next(position for row, position in nonspace if row == ri) for ri in indices[1:]]
            if require_cache and (len(cache) != len(indices) or current_bounds[:-1] != starts):
                return None
            rows = []
            for i, ri in enumerate(indices):
                stop = starts[i + 1] if i + 1 < len(starts) else offset
                height = max(height for position, char, height in units if starts[i] <= position < stop)
                baseline = round(height * .85)
                rows.append((ri, height, baseline))
            groups.append((paragraph, rows))
        if cursor != len(source) or sum(len(rows) for p, rows in groups) != len(records):
            return None
        first = groups[0][1][0]
        last = groups[-1][1][-1]
        top = round((float(records[0]['baseline_pt']) - box.y0) * scale) - first[2]
        required = round((float(records[-1]['baseline_pt']) - box.y0) * scale) + last[1] - last[2] + 200
        height = round(box.height * scale)
        gaps = [(float(b['baseline_pt']) - float(a['baseline_pt'])) * scale for a, b in zip(records, records[1:])]
        if top < 0 or required > height or any(not math.isfinite(gap) or gap <= 0 for gap in gaps):
            return None
        plan = {'top': top, 'required': required, 'height': height, 'scale': scale,
                'records': records, 'groups': groups, 'glyphs': len(source)}
        return plan if _row_layout(plan) is not None else None
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, OSError, fitz.FileDataError):
        return None


def _row_layout(plan):
    records, scale = plan['records'], plan['scale']
    staged = []
    for paragraph, rows in plan['groups']:
        first_top = float(records[rows[0][0]]['baseline_pt']) * scale - rows[0][2]
        tops = [round(float(records[ri]['baseline_pt']) * scale - baseline - first_top)
                for ri, height, baseline in rows]
        spacings = [tops[i + 1] - tops[i] - height if i + 1 < len(rows) else 0
                    for i, (ri, height, baseline) in enumerate(rows)]
        if min(tops + spacings) < 0:
            return None
        staged.append((paragraph, rows, tops, spacings, first_top,
                       sum(height + spacing for (ri, height, baseline), spacing in zip(rows, spacings))))
    gaps = [round(staged[i + 1][4] - item[4]) - item[5] if i + 1 < len(staged) else 0
            for i, item in enumerate(staged)]
    if min(gaps) < 0:
        return None
    if plan['top'] + sum(item[5] + gap for item, gap in zip(staged, gaps)) + 200 > plan['height']:
        return None
    return staged, gaps


def apply_source_frame_native_rows(plan, header):
    """Preserve actual source baselines with each row's current native height."""
    from app.pdf_source_spacing import set_space_before, set_space_after

    layout = _row_layout(plan)
    if layout is None:
        return False
    staged, gaps = layout
    if any(len(paragraph.findall(HP + 'linesegarray/' + HP + 'lineseg')) != len(rows)
           for paragraph, rows, tops, spacings, first_top, occupied in staged):
        return False
    for (paragraph, rows, tops, spacings, first_top, occupied), gap in zip(staged, gaps):
        cache = paragraph.findall(HP + 'linesegarray/' + HP + 'lineseg')
        for line, (ri, height, baseline), top, spacing in zip(cache, rows, tops, spacings):
            for key, value in (('vertpos', top), ('vertsize', height), ('textheight', height),
                               ('baseline', baseline), ('spacing', spacing)):
                line.set(key, str(value))
        set_space_before(paragraph, header, 0)
        set_space_after(paragraph, header, gap)
    return True


def source_grid_frame_fragment(layout):
    geometries = layout.get('native_tables') or []
    return bool(layout.get('source_frame_has_grid') is True and len(geometries) == 1
                and geometries[0].get('background_path') and not geometries[0].get('source_grid_bbox_pt'))


def restore_source_grid_frame_fragment(root, layout, header, page_width, column_width, restore):
    """Commit the fully proved frame and new styles only after staged success."""
    from lxml import etree
    if source_frame_native_rows(root, layout, header, page_width) is None:
        return 0
    staged, head = deepcopy(root), deepcopy(header)
    plan = source_frame_native_rows(staged, layout, head, page_width)
    if plan is None:
        return 0
    properties = head.find('.//' + HH + 'paraProperties')
    original_properties = header.find('.//' + HH + 'paraProperties')
    if properties is None or original_properties is None:
        return 0
    original_styles = list(original_properties)
    styles = {p.get('id'): p for p in properties}
    identifiers = [p.get('id') for p in properties]
    if (not identifiers or len(set(identifiers)) != len(identifiers)
        or any(not isinstance(value, str) or not value.isdigit() for value in identifiers)
        or any(p.get('paraPrIDRef') not in styles for p in staged.iter(HP + 'p'))):
        return 0
    cache = {}
    hc = '{http://www.hancom.co.kr/hwpml/2011/core}'

    def paragraph_style(base, alignment, step, height, left=0, indent=0, right=0):
        percent = max(100, min(250, round(step * 100 / height)))
        key = (base, alignment, percent, round(left), round(indent), round(right))
        if key not in cache:
            copied = deepcopy(styles[base])
            identifier = str(max(map(int, styles)) + 1)
            copied.set('id', identifier)
            align = copied.find(HH + 'align')
            if align is not None:
                align.set('horizontal', alignment)
            for line in copied.findall('.//' + HH + 'lineSpacing'):
                line.attrib.update({'type': 'PERCENT', 'value': str(percent), 'unit': 'PERCENT'})
            for margin in copied.findall('.//' + HH + 'margin'):
                for name in ('left', 'right', 'prev', 'next', 'intent'):
                    edge = margin.find(hc + name)
                    if edge is not None:
                        value = {'left': left, 'right': right, 'intent': indent}.get(name, 0)
                        edge.set('value', str(round(value)))
            properties.append(copied)
            styles[identifier] = copied
            cache[key] = identifier
        return cache[key]

    try:
        result = restore(staged, layout, head, page_width, column_width, paragraph_style,
                         native_rows=plan)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, ZeroDivisionError):
        return 0
    if not result or len(properties) < len(original_styles) or any(etree.tostring(a, method='c14n', exclusive=True) != etree.tostring(b, method='c14n', exclusive=True)
                         for a, b in zip(original_styles, list(properties)[:len(original_styles)])):
        return 0
    for style in list(properties)[len(original_styles):]:
        original_properties.append(deepcopy(style))
    original_properties.set('itemCnt', str(len(original_properties)))
    root.attrib.clear()
    root.attrib.update(staged.attrib)
    for child in list(root):
        root.remove(child)
    root.extend(staged)
    return result
