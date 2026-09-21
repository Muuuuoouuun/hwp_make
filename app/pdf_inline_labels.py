"""Audit small PDF answer frames independently of writer metadata."""
import re
import math

import fitz

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
LABEL = re.compile(r'\([가-힣]\)')


def _number(element, key, default=0):
    try:
        value = float(element.get(key, default))
        return value if math.isfinite(value) else default
    except (TypeError, ValueError, AttributeError):
        return default


def source_inline_labels(page, drawings=None):
    """Read closed, opaque vector rectangles and their actual enclosed glyphs."""
    from .pdf_layout_writer import _pdf_output_text

    glyphs = []
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines', []):
            for span in line['spans']:
                for char in span['chars']:
                    glyphs.append({**char, 'font': span['font'], 'size': span['size']})
    results = []
    for drawing in drawings if drawings is not None else page.get_drawings():
        items = drawing.get('items') or []
        if (drawing.get('type') not in ('s', 'fs') or len(items) != 1
            or items[0][0] not in ('re', 'qu') or drawing.get('stroke_opacity', 0) < .99
            or max(drawing.get('color') or (1,)) > .2
            or not 0 < drawing.get('width', 0) <= 1
            or drawing.get('dashes', '[] 0').strip() != '[] 0'):
            continue
        rect = fitz.Rect(drawing['rect'])
        if not 8 <= rect.height <= 25 or not 2 <= rect.width / rect.height <= 5:
            continue
        if items[0][0] == 'qu':
            quad = items[0][1]
            # Producers may start at any corner and wind in either direction.
            if any(min(abs(point.x-x)+abs(point.y-y) for point in quad) > .01
                   for x in (rect.x0, rect.x1) for y in (rect.y0, rect.y1)):
                continue
        inside = [g for g in glyphs if rect.contains(fitz.Rect(g['bbox']))]
        inside.sort(key=lambda g: g['origin'][0])
        text = ''.join(_pdf_output_text(g['c']) for g in inside).strip()
        if not LABEL.fullmatch(text):
            continue
        ink = fitz.Rect(inside[0]['bbox'])
        for glyph in inside[1:]:
            ink |= fitz.Rect(glyph['bbox'])
        if ink.height > rect.height or ink.width > rect.width * .75:
            continue
        # Multiple PDF paint commands may describe the same rule once.
        if any(max(abs(a-b) for a, b in zip(rect, old['bbox_pt'])) < .05 for old in results):
            continue
        hangul = next(g for g in inside if re.fullmatch('[가-힣]', _pdf_output_text(g['c'])))
        results.append({'text': text, 'bbox_pt': list(rect), 'ink_bbox_pt': list(ink),
                        'font': hangul['font'], 'font_size_pt': hangul['size'],
                        'line_width_pt': drawing['width']})
    return sorted(results, key=lambda entry: (entry['bbox_pt'][1], entry['bbox_pt'][0]))


def inline_label_text(shape):
    """Read the text of a visible, editable inline frame, not its name tag."""
    if shape.tag != HP+'rect':
        return None
    draw, pos, size = shape.find(HP+'drawText'), shape.find(HP+'pos'), shape.find(HP+'sz')
    line = shape.find(HP+'lineShape')
    if (draw is None or pos is None or size is None or line is None
        or draw.get('editable') != '1' or pos.get('treatAsChar') != '1'
        or shape.get('textWrap') not in ('SQUARE', 'TOP_AND_BOTTOM')
        or line.get('style') != 'SOLID' or line.get('color', '').upper() != '#000000'
        or _number(line, 'width') <= 0 or _number(line, 'alpha', 255) != 0
        or any(_number(pos, k, float('inf')) for k in ('vertOffset', 'horzOffset'))):
        return None
    sub = draw.find(HP+'subList')
    paragraphs = sub.findall(HP+'p') if sub is not None else []
    if len(paragraphs) != 1:
        return None
    children = [c for r in paragraphs[0].findall(HP+'run') for c in r]
    if not children or any(c.tag != HP+'t' or len(c) for c in children):
        return None
    text = ''.join(c.text or '' for c in children)
    from .pdf_question_geometry import inspect_question_geometry
    if not LABEL.fullmatch(text) or not inspect_question_geometry(draw)['ok']:
        return None
    return text


def native_inline_labels(roots):
    """Inventory native labels only inside visible, inline rectangular frames."""
    results = []
    for root in roots:
        page = root.find('.//' + HP + 'pagePr')
        if page is None:
            continue
        page_width = _number(page, 'width')
        if page_width <= 0:
            continue
        for shape in root.iter(HP+'rect'):
            text = inline_label_text(shape)
            if text is None:
                continue
            size = shape.find(HP+'sz')
            results.append({'text': text, 'width_ratio': _number(size, 'width')/page_width,
                            'height_ratio': _number(size, 'height')/page_width,
                            'native_page_width': page_width})
    return results


def inspect_inline_label_preservation(source, roots, *, page_limit=None):
    """No credit for an unframed label or a frame with wrong native dimensions.

    Actual paint visibility is a separate mandatory renderer check; this check
    cannot prove that a reader supports a deeply nested native rectangle.
    """
    actual = native_inline_labels(roots)
    remaining = list(actual)
    missing, count = [], 0
    with fitz.open(source) as doc:
        for index in range(min(len(doc), page_limit or len(doc))):
            page = doc[index]
            for entry in source_inline_labels(page):
                count += 1
                box = fitz.Rect(entry['bbox_pt'])
                match = next((n for n in remaining if n['text'] == entry['text']
                    and abs(n['width_ratio']-box.width/page.rect.width)*n['native_page_width'] <= 1
                    and abs(n['height_ratio']-box.height/page.rect.width)*n['native_page_width'] <= 1), None)
                if match is None:
                    missing.append({'page': index+1, **entry})
                else:
                    remaining.remove(match)
    return {'ok': not missing and not remaining, 'source_label_frames': count,
            'native_label_frames': len(actual), 'matched_label_frames': count-len(missing),
            'missing_label_frames': missing, 'unexpected_label_frames': remaining}
