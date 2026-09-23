"""Verify native graph labels against PDF text geometry and actual package assets."""
from collections import Counter
import hashlib
import math
import re

import fitz

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HC = '{http://www.hancom.co.kr/hwpml/2011/core}'


def _number(node, key):
    value = float(node.get(key))
    if not math.isfinite(value):
        raise ValueError('non-finite graph geometry')
    return value


def _text(value):
    return re.sub(r'\s|\$', '', value)


def graph_annotation_text(shape):
    """Package-only shape check; source identity requires the audit below."""
    from .pdf_native_text import body_text
    from .pdf_graph_writer import NAME
    try:
        group = shape.getparent()
        draw = shape.find(HP+'drawText')
        sub = draw.find(HP+'subList') if draw is not None else None
        if (shape.tag != HP+'rect' or group.tag != HP+'container'
            or len(group.findall(HP+'pic')) != 1 or len(group.findall(HP+'rect')) < 6
            or shape.get('groupLevel') != '1' or shape.get('lock') != '0'
            or draw is None or draw.get('name') != NAME or draw.get('editable') != '1'
            or sub is None or len(sub.findall(HP+'p')) != 1
            or any(sub.find('.//'+HP+tag) is not None for tag in ('tbl','rect','container','pic'))):
            return None
        value = _text(body_text(sub))
        if not re.fullmatch(r'[A-Za-z]|[xy]=[A-Za-z](?:\([xy]\))?',value):
            return None
        size = shape.find(HP+'sz')
        width,height = _number(size,'width'),_number(size,'height')
        if min(width,height) <= 0 or max(width,height) > 5000:
            return None
        if (abs(_number(draw,'lastWidth')-width)>1 or abs(_number(sub,'textWidth')-width)>1
            or abs(_number(sub,'textHeight')-height)>1):
            return None
        pos = shape.find(HP+'offset')
        x,y = _number(pos,'x'),_number(pos,'y')
        if min(x,y)<0 or x+width>_number(group.find(HP+'sz'),'width')+2 or y+height>_number(group.find(HP+'sz'),'height')+2:
            return None
        return value
    except (AttributeError,TypeError,ValueError):
        return None


def inspect_graph_annotations(source, roots, hrefs, archive, provenance):
    """A name or writer count never authorizes additional drawing textboxes.

    The bitmap-only asset must belong to exactly one inline group. Every PDF
    text line touching its source area must have exactly one editable label at
    its measured relative position. Original bitmap pixels are independently
    checked by inspect_source_images; text is still checked as native content.
    """
    from . import pdf_layout_writer as w
    from .pdf_native_text import body_text
    from .pdf_graph_writer import NAME

    records = [r for r in provenance or [] if r.get('source_kind') == 'bitmap_objects']
    issues, details, allowed = [], [], set()
    groups = [g for root in roots for g in root.iter(HP+'container')]
    claimed = set()
    if not records and not groups:
        return {'ok':True,'issues':[],'graphs':[],'annotation_count':0}, allowed
    with fitz.open(source) as document:
        for record in records:
            failures = []
            try:
                page = document[int(record['page'])-1]
                x,y,width,height = map(float, record['bbox_px'])
                sx,sy = page.rect.width/record['page_width_px'], page.rect.height/record['page_height_px']
                region = fitz.Rect(x*sx,y*sy,(x+width)*sx,(y+height)*sy)
                if region.is_empty or not page.rect.contains(region):
                    raise ValueError('invalid graph source area')
                matches = []
                for group in groups:
                    pictures = group.findall(HP+'pic')
                    if len(pictures) != 1:
                        continue
                    image = pictures[0].find(HC+'img')
                    href = hrefs.get(image.get('binaryItemIDRef')) if image is not None else None
                    if href and href in archive.namelist() and hashlib.sha256(archive.read(href)).hexdigest() == record['sha256']:
                        matches.append((group,pictures[0]))
                if len(matches) != 1 or matches[0][0] in claimed:
                    raise ValueError('graph asset has no unique native group')
                group,picture = matches[0]
                claimed.add(group)
                question = next((a for a in group.iterancestors()
                    if a.tag == HP+'drawText' and re.fullmatch(r'question:v\d+:q\d+',a.get('name',''))), None)
                if question is None or group.find(HP+'pos').get('treatAsChar') != '1':
                    raise ValueError('graph must flow inside its question')
                if group.get('lock') != '0' or group.find(HP+'pos').get('flowWithText') != '1':
                    raise ValueError('graph is locked or detached from its paragraph')
                for matrix_name in ('transMatrix','scaMatrix','rotMatrix'):
                    matrix = group.find(HP+'renderingInfo/'+HC+matrix_name)
                    if any(abs(_number(matrix,k)-v) > 1e-8 for k,v in (('e1',1),('e2',0),('e3',0),('e4',0),('e5',1),('e6',0))):
                        raise ValueError('unexpected graph group transform')
                group_size = group.find(HP+'sz')
                for name in ('orgSz','curSz'):
                    if any(abs(_number(group.find(HP+name),k)-_number(group_size,k)) > 1 for k in ('width','height')):
                        raise ValueError('inconsistent native graph dimensions')
                scale = _number(group.getroottree().getroot().find('.//'+HP+'pagePr'),'width')/page.rect.width
                source_lines = [line for line in w._iter_text_lines(page)
                                if region.intersects(w._item_bbox(line)) and w._line_text(line).strip()]
                expected = {_text(w._pdf_output_text(w._line_text(line))):w._item_bbox(line) for line in source_lines}
                if (len(expected) != len(source_lines) or len(expected) < 6
                    or not {'x','y'} <= expected.keys()
                    or not all(re.fullmatch(r'[A-Za-z]|[xy]=[A-Za-z](?:\([xy]\))?',value) for value in expected)):
                    raise ValueError('source area is not a sparse graph-label constellation')
                shapes = group.findall(HP+'rect')
                draws = [s.find(HP+'drawText') for s in shapes]
                if any(d is None or d.get('name') != NAME or d.get('editable') != '1' for d in draws):
                    raise ValueError('non-editable or unknown graph annotation')
                actual = Counter(_text(body_text(d)) for d in draws)
                if actual != Counter(expected.keys()):
                    failures.append('graph_annotation_text_inventory_mismatch')
                size = picture.find(HP+'sz')
                if max(abs(_number(size,'width')-region.width*scale),
                       abs(_number(size,'height')-region.height*scale)) > 2:
                    failures.append('graph_bitmap_size_mismatch')
                pt = picture.find(HP+'renderingInfo/'+HC+'transMatrix')
                px,py = _number(pt,'e3'),_number(pt,'e6')
                max_error = 0.0
                for shape,draw in zip(shapes,draws):
                    bounds = expected.get(_text(body_text(draw)))
                    if bounds is None:
                        continue
                    transform = shape.find(HP+'renderingInfo/'+HC+'transMatrix')
                    offset, size = shape.find(HP+'offset'), shape.find(HP+'sz')
                    values = (_number(transform,'e3'), _number(transform,'e6'),
                              _number(size,'width'), _number(size,'height'))
                    targets = (px+(bounds.x0-region.x0)*scale,py+(bounds.y0-region.y0)*scale,
                               bounds.width*scale,bounds.height*scale)
                    max_error = max(max_error,*(abs(a-b) for a,b in zip(values,targets)))
                    if (abs(_number(offset,'x')-values[0]) > 1 or abs(_number(offset,'y')-values[1]) > 1
                        or any(abs(_number(transform,k)-v) > 1e-8 for k,v in (('e1',1),('e2',0),('e4',0),('e5',1)))
                        or shape.get('groupLevel') != '1' or shape.get('lock') != '0'):
                        failures.append('graph_annotation_transform_mismatch')
                    for matrix_name in ('scaMatrix','rotMatrix'):
                        matrix = shape.find(HP+'renderingInfo/'+HC+matrix_name)
                        if any(abs(_number(matrix,k)-v) > 1e-8 for k,v in (('e1',1),('e2',0),('e3',0),('e4',0),('e5',1),('e6',0))):
                            failures.append('graph_annotation_transform_mismatch')
                    sub = draw.find(HP+'subList')
                    if (len(sub.findall(HP+'p')) != 1
                        or abs(_number(draw,'lastWidth')-values[2]) > 1
                        or abs(_number(sub,'textWidth')-values[2]) > 1
                        or abs(_number(sub,'textHeight')-values[3]) > 1):
                        failures.append('graph_annotation_container_mismatch')
                    if (min(values[0], values[1]) < 0
                        or values[0]+values[2] > _number(group.find(HP+'sz'),'width')+2
                        or values[1]+values[3] > _number(group.find(HP+'sz'),'height')+2):
                        failures.append('graph_annotation_outside_group')
                if max_error > 2:
                    failures.append('graph_annotation_position_mismatch')
                # A graph label printed again as a stand-alone paragraph is a
                # duplicate unless this source question actually contains it.
                column = region.x0 >= page.rect.width/2
                markers = [(w._item_bbox(line).y0,w._line_text(line)) for line in w._iter_text_lines(page)
                           if bool(w._item_bbox(line).x0 >= page.rect.width/2) == column
                           and re.match(r'^\s*\d{1,2}[.]\s',w._pdf_output_text(w._line_text(line)))]
                top = max((y for y,_ in markers if y < region.y0),default=0)
                bottom = min((y for y,_ in markers if y > region.y1),default=page.rect.height)
                outside_source = Counter(_text(w._pdf_output_text(w._line_text(line))) for line in w._iter_text_lines(page)
                    if top <= w._item_bbox(line).y0 < bottom and bool(w._item_bbox(line).x0 >= page.rect.width/2) == column
                    and not region.intersects(w._item_bbox(line)))
                outside_native = Counter(_text(body_text(p)) for p in question.iter(HP+'p')
                    if group not in p.iterancestors() and p.find('.//'+HP+'container') is None)
                if any(outside_native[value] > outside_source[value] for value in expected):
                    failures.append('graph_annotation_duplicated_outside_group')
                if not failures:
                    allowed.update(draws)
                details.append({'page':int(record['page']),'annotations':len(draws),
                    'maximum_relative_geometry_error_hwpunit':round(max_error,6),'issues':sorted(set(failures))})
            except (AttributeError,KeyError,IndexError,TypeError,ValueError,ZeroDivisionError) as error:
                failures.append('invalid_native_graph')
                details.append({'page':record.get('page'),'issues':failures,'reason':str(error)})
            issues.extend(failures)
    if any(g not in claimed and g.find('.//'+HP+'drawText') is not None for g in groups):
        issues.append('unproven_native_graph')
    return {'ok':not issues,'issues':sorted(set(issues)),'graphs':details,
            'annotation_count':len(allowed)}, allowed
