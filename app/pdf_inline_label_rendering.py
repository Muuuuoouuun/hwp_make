"""Demand visible text inside a fully painted border for each native label."""
from collections import Counter
import re
from lxml import etree


def painted_label_frames(svg, labels):
    from .pdf_question_rendering import (
        SVG, IDENTITY, _bounds, _contrast_on_white, _intersect,
        _multiply, _style, _transform, _visible_svg_text,
    )
    root = etree.fromstring(svg.encode())
    view = [float(n) for n in root.get('viewBox', '').split()]
    viewport = (view[0], view[1], view[0]+view[2], view[1]+view[3]) if len(view) == 4 else (
        0, 0, float(root.get('width')), float(root.get('height')))
    page_width = viewport[2]-viewport[0]
    clips = {n.get('id'): n for n in root.iter(SVG+'clipPath')}
    result = []
    for rect in root.iter(SVG+'rect'):
        if any(etree.QName(a).localname in ('defs', 'clipPath', 'mask', 'pattern', 'symbol')
               for a in rect.iterancestors()):
            continue
        matrix, opacity, limits = IDENTITY, 1., [viewport]
        inherited = {'stroke': 'none', 'stroke-width': '0', 'stroke-opacity': '1', 'visibility': 'visible'}
        try:
            for node in [*reversed(list(rect.iterancestors())), rect]:
                style = _style(node)
                if style.get('display') == 'none':
                    raise ValueError('hidden frame')
                opacity *= float(style.get('opacity', 1))
                matrix = _multiply(matrix, _transform(style.get('transform', '')))
                inherited.update({k: style[k] for k in inherited if k in style})
                if style.get('mask', 'none') != 'none' or style.get('filter', 'none') != 'none':
                    raise ValueError('unassessed paint effect')
                clip = style.get('clip-path', 'none')
                if clip != 'none':
                    match = re.fullmatch(r'url\(#([^)]*)\)', clip)
                    definition = clips.get(match[1]) if match else None
                    regions = definition.findall(SVG+'rect') if definition is not None else []
                    if (len(regions) != 1 or definition.get('clipPathUnits', 'userSpaceOnUse') != 'userSpaceOnUse'):
                        raise ValueError('unassessed clip')
                    c = regions[0]
                    limits.append(_bounds(_multiply(matrix, _transform(c.get('transform', ''))),
                        float(c.get('x', 0)), float(c.get('y', 0)), float(c.get('width', 0)), float(c.get('height', 0))))
            opacity *= float(inherited['stroke-opacity'])
            if (inherited['visibility'] in ('hidden', 'collapse') or opacity <= 0
                or float(inherited['stroke-width']) <= 0 or abs(matrix[1])+abs(matrix[2]) > 1e-8
                or _contrast_on_white(inherited['stroke'], opacity) < 3):
                continue
            x, y = float(rect.get('x', 0)), float(rect.get('y', 0))
            width, height = float(rect.get('width', 0)), float(rect.get('height', 0))
            box = _bounds(matrix, x, y, width, height)
            if width <= 0 or height <= 0:
                continue
            if any(max(abs(a-b) for a, b in zip(_intersect(box, limit), box)) > .01 for limit in limits):
                continue
            # A viewport-limited inspection reuses the same visibility and
            # clipping rules as the full page. It does not alter the render.
            probe = etree.fromstring(svg.encode())
            # Approximate glyph widths in the visibility checker can overlap
            # the preceding punctuation by a fraction of a pixel. It is not
            # box content unless its own text anchor lies inside this frame.
            for text_node in list(probe.iter(SVG+'text')):
                transform = IDENTITY
                for ancestor in [*reversed(list(text_node.iterancestors())), text_node]:
                    transform = _multiply(transform, _transform(_style(ancestor).get('transform', '')))
                tx, ty = float(text_node.get('x', 0)), float(text_node.get('y', 0))
                px = transform[0]*tx + transform[2]*ty + transform[4]
                py = transform[1]*tx + transform[3]*ty + transform[5]
                if not (box[0]-.01 <= px <= box[2]+.01 and box[1]-.01 <= py <= box[3]+.01):
                    text_node.getparent().remove(text_node)
            probe.set('viewBox', f'{box[0]} {box[1]} {box[2]-box[0]} {box[3]-box[1]}')
            text, _, unknown = _visible_svg_text(etree.tostring(probe, encoding='unicode'))
            text = re.sub(r'\s+', '', text)
            if not unknown and text in labels:
                result.append({'text': text, 'width_ratio': (box[2]-box[0])/page_width,
                               'height_ratio': (box[3]-box[1])/page_width, 'page_width': page_width,
                               'bbox_px': list(box)})
        except (ValueError, TypeError, OverflowError):
            continue
    return result


def missing_label_frames(required, painted):
    available = list(painted)
    missing = Counter()
    for label in required:
        match = next((frame for frame in available if frame['text'] == label['text']
            and abs(frame['width_ratio']-label['width_ratio'])*frame['page_width'] <= .1
            and abs(frame['height_ratio']-label['height_ratio'])*frame['page_width'] <= .1), None)
        if match is None:
            missing[label['text']] += 1
        else:
            available.remove(match)
    return dict(missing)
