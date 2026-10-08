"""Keep one real prose frame around its editable text and source illustrations."""
from copy import deepcopy
import math
import re
from statistics import median

import fitz
from lxml import etree

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'


def _compact(value):
    from .pdf_layout_writer import _pdf_output_text
    return re.sub(r'\s+', '', _pdf_output_text(value))


def illustrated_frame_topology(frame, records, images):
    """Measure a real side illustration, never divide prose by printed rows."""
    from .pdf_wrapped_prose_frames import wrapped_frame_topology
    wrapped = wrapped_frame_topology(frame, records, images)
    if wrapped is not None:
        return wrapped
    boxes = [fitz.Rect(image['bbox_pt']) for image in images]
    if not boxes or len(boxes) > 2:
        return None
    primary = max(range(len(boxes)), key=lambda index: boxes[index].height)
    picture = boxes[primary]
    size = median(float(record.get('font_size_pt') or 11) for record in records)
    beside = [fitz.Rect(record['bbox_pt']) for record in records
              if min(record['bbox_pt'][3], picture.y1) > max(record['bbox_pt'][1], picture.y0)]
    if not beside or picture.height < size*2 or not frame.contains(picture):
        return None
    side = ('right' if all(box.x1 <= picture.x0+.1 for box in beside) else
            'left' if all(box.x0 >= picture.x1-.1 for box in beside) else None)
    if side != 'right':
        return None
    split = picture.x0 if side == 'right' else picture.x1
    if min(split-frame.x0, frame.x1-split) < size*3:
        return None
    other = next((index for index in range(len(boxes)) if index != primary), None)
    cuts = [frame.y0, picture.y0]
    if other is not None:
        small = boxes[other]
        if (not frame.contains(small) or small.height > size*1.8 or small.y0 <= picture.y0
            or (side == 'right' and small.x1 > split) or (side == 'left' and small.x0 < split)):
            return None
        cuts.append(small.y0)
    cuts.append(frame.y1)
    rows = [[] for _ in cuts[1:]]
    for record in records:
        box = fitz.Rect(record['bbox_pt'])
        row = next((i for i,(top,bottom) in enumerate(zip(cuts,cuts[1:]))
                    if box.y0 >= top-.1 and box.y1 <= bottom+.1), None)
        if row is None or (row and ((side == 'right' and box.x1 > split+.1)
                                    or (side == 'left' and box.x0 < split-.1))):
            return None
        rows[row].append(record)
    if not all(rows):
        return None
    if other is not None and (len(rows[-1]) != 1
        or (side == 'right' and rows[-1][0]['bbox_pt'][2] > boxes[other].x0+.1)
        or (side == 'left' and rows[-1][0]['bbox_pt'][0] < boxes[other].x1-.1)):
        return None
    return {'side':side, 'split_x_pt':split, 'row_y_pt':cuts,
            'primary_image_index':primary, 'wrapped_image_index':other}


def coalesce_illustrated_prose_frames(blocks, page, source_lines):
    """Join only a complete vector frame interrupted by contained pictures.

    Every original source line in the four-rule rectangle must be present once,
    with the same text and bounds. Native grids, overlapping prose/pictures,
    partial illustrations and competing inner frames keep their existing path.
    """
    from .pdf_layout_writer import _item_bbox, _line_text
    from .pdf_native_content import _source_prose_frame

    result = list(blocks)
    drawings = page.get_drawings()
    candidates = []
    for block in blocks:
        box = block.get('rect')
        if block.get('type') == 'box' and box is not None:
            frame = _source_prose_frame(fitz.Rect(box), drawings)
            if frame is not None and not any(max(abs(a-b) for a,b in zip(frame, old)) < .1 for old in candidates):
                candidates.append(frame)
    for frame in candidates:
        pieces, pictures, indices = [], [], []
        invalid = False
        for index, block in enumerate(result):
            kind = block.get('type')
            if kind == 'box' and block.get('rect') is not None:
                box = fitz.Rect(block['rect'])
                if max(abs(a-b) for a,b in zip(box, frame)) < .1:
                    if any(line.get('type') != 'line' for line in block.get('lines', [])):
                        invalid = True
                        break
                    pieces.append(block)
                    indices.append(index)
                elif frame.intersects(box):
                    invalid = True
                    break
            elif kind == 'image':
                picture = block['image']
                bounds = _item_bbox(picture)
                if frame.intersects(bounds):
                    if not frame.contains(bounds) or picture.get('native_graph') or picture.get('diagram_labels'):
                        invalid = True
                        break
                    pictures.append(picture)
                    indices.append(index)
            elif kind == 'native_table' and frame.intersects(_item_bbox(block['native_table'])):
                invalid = True
                break
        if invalid or len(pieces) < 2 or not pictures:
            continue
        lines = [line for piece in pieces for line in piece['lines']]
        ordered = sorted(lines, key=lambda line: (_item_bbox(line).y0, _item_bbox(line).x0))
        expected = sorted((line for line in source_lines if frame.contains(_item_bbox(line))),
                          key=lambda line: (_item_bbox(line).y0, _item_bbox(line).x0))
        if not expected or len(expected) != len(ordered):
            continue
        if any(_compact(_line_text(a)) != _compact(_line_text(b))
               or max(abs(x-y) for x,y in zip(_item_bbox(a), _item_bbox(b))) > .1
               for a,b in zip(ordered, expected)):
            continue
        if any(not frame.contains(_item_bbox(line)) for line in ordered):
            continue
        if any((_item_bbox(picture) & _item_bbox(line)).get_area() > .1
               for picture in pictures for line in ordered):
            continue
        images = sorted(pictures, key=lambda image: (_item_bbox(image).y0, _item_bbox(image).x0))
        topology = illustrated_frame_topology(frame,
            [{'bbox_pt':list(_item_bbox(line)), 'font_size_pt':median(float(span.get('size') or 11)
              for span in line.get('spans', []))} for line in ordered],
            [{'bbox_pt':list(_item_bbox(picture))} for picture in images])
        if topology is None:
            continue
        start, end = min(indices), max(indices)
        if any(result[index].get('type') != 'gap' and index not in indices for index in range(start, end+1)):
            continue
        merged = {**pieces[0], 'lines': ordered, 'rect': frame,
                  'source_frame_images':images, 'source_frame_topology':topology}
        result[start:end+1] = [merged]
    return result


def detach_source_frame_illustrations(root, layout):
    """Validate the complete frame before moving its temporary picture rows."""
    geometries = layout.get('native_tables') or []
    if len(geometries) != 1 or not geometries[0].get('images'):
        return 0
    geometry = geometries[0]
    source_width = float(layout.get('source_page_width_pt') or 0)
    box = geometry.get('bbox_pt') or []
    records = (layout.get('source_typography') or {}).get('lines') or []
    tables = root.findall(HP+'run/'+HP+'tbl')
    if (not layout.get('source_literal_text') or not geometry.get('source_prose_frame')
        or len(box) != 4 or source_width <= 0 or len(tables) != 1 or not records
        or geometry.get('cell_bounds') != [[box]]):
        return -1
    frame = fitz.Rect(box)
    table = tables[0]
    cells = table.findall(HP+'tr/'+HP+'tc')
    if (len(cells) != 1 or any(table.find('.//'+HP+tag) is not None for tag in ('tbl','rect','equation'))
        or _compact(''.join(t.text or '' for t in cells[0].iter(HP+'t')))
           != _compact(geometry.get('source_frame_text') or '')
        or _compact(''.join(record.get('text','') for record in records))
           != _compact(geometry.get('source_frame_text') or '')):
        return -1
    images = geometry['images']
    pictures = table.findall('.//'+HP+'pic')
    if len(images) != len(pictures) or not pictures:
        return -1
    plans = []
    for picture, image in zip(pictures, images):
        bounds = image.get('bbox_pt') or []
        if len(bounds) != 4 or image.get('row') != 0 or image.get('column') != 0:
            return -1
        bounds = fitz.Rect(bounds)
        if (not all(math.isfinite(v) for v in bounds) or bounds.is_empty or not frame.contains(bounds)
            or any((bounds & fitz.Rect(record['bbox_pt'])).get_area() > .1 for record in records)):
            return -1
        holder, owner = picture.getparent(), picture.getparent().getparent()
        if (holder.tag != HP+'run' or owner.tag != HP+'p'
            or any((t.text or '').strip() for t in owner.iter(HP+'t'))
            or any(child.tag != HP+'pic' for child in holder)):
            return -1
        position = picture.find(HP+'pos')
        size = picture.find(HP+'sz')
        if position is None or size is None:
            return -1
        plans.append((picture, holder, owner, bounds))
    for picture, holder, owner, bounds in plans:
        holder.remove(picture)
        if not any((t.text or '').strip() for t in owner.iter(HP+'t')) and not any(owner.iter(HP+'pic')):
            owner.getparent().remove(owner)
    return [picture for picture, _, _, _ in plans]


def _border_fill(header, base_id, *, left, right, top, bottom):
    HH = '{http://www.hancom.co.kr/hwpml/2011/head}'
    fills = header.find('.//'+HH+'borderFills')
    wanted = dict(zip(('left','right','top','bottom'), (left,right,top,bottom)))
    base = next(fill for fill in fills if fill.get('id') == base_id)
    copied = deepcopy(base)
    for edge, visible in wanted.items():
        copied.find(HH+edge+'Border').set('type', 'SOLID' if visible else 'NONE')
    for fill in fills:
        probe = deepcopy(copied)
        probe.set('id',fill.get('id'))
        if etree.tostring(probe) == etree.tostring(fill):
            return fill.get('id')
    identifier = str(max(int(fill.get('id')) for fill in fills)+1)
    copied.set('id',identifier)
    fills.append(copied)
    fills.set('itemCnt',str(len(fills)))
    return identifier


def _source_field_groups(records, following=None):
    """Prove repeated label fields and their real leading-space continuation.

    A PDF line box includes its leading spaces. Only complete raw characters
    can distinguish a field's ink rail from that box. This proof is deliberately
    separate from ordinary prose grouping and answer-blank whitespace.
    """
    from .pdf_layout_writer import is_hancom_eq_font

    label = re.compile(r'^([A-Z][A-Za-z ]{1,20}):\s*\S')
    measured = []
    for record in records:
        spans = record.get('spans') or []
        if not spans or any(not s.get('font') or is_hancom_eq_font(str(s.get('font', ''))) for s in spans):
            return []
        chars = []
        for span in spans:
            raw = span.get('chars') or []
            if (not raw or ''.join(str(c.get('c', '')) for c in raw) != span.get('text')
                or len(span.get('bbox') or []) != 4
                or not all(math.isfinite(float(v)) for v in span['bbox'])
                or any(not isinstance(c.get('c'), str) or len(c['c']) != 1
                       or len(c.get('bbox') or []) != 4 or len(c.get('origin') or []) != 2 for c in raw)):
                return []
            try:
                boxes = [fitz.Rect(c['bbox']) for c in raw]
                if any(b.is_empty or not all(math.isfinite(v) for v in (*b, *c['origin']))
                       for b, c in zip(boxes, raw)):
                    return []
                union = fitz.Rect(boxes[0])
                for box in boxes[1:]: union |= box
                if max(abs(a-b) for a, b in zip(union, span['bbox'])) > .1:
                    return []
            except (KeyError, TypeError, ValueError):
                return []
            chars.extend(raw)
        raw_text = ''.join(c['c'] for c in chars)
        ink = [c for c in chars if c['c'].strip()]
        if not ink or _compact(raw_text) != _compact(record.get('text', '')):
            return []
        union = fitz.Rect(chars[0]['bbox'])
        for char in chars[1:]: union |= fitz.Rect(char['bbox'])
        try:
            if (len(record.get('bbox_pt') or []) != 4
                or not all(math.isfinite(float(v)) for v in record['bbox_pt'])
                or max(abs(a-b) for a, b in zip(union, record['bbox_pt'])) > .1):
                return []
            size = float(record['font_size_pt'])
            first, left = float(ink[0]['origin'][0]), float(chars[0]['origin'][0])
            if (not math.isfinite(size) or size <= 0
                or abs(left-record['bbox_pt'][0]) > .1
                or any(abs(c['origin'][1]-ink[0]['origin'][1]) > .1 for c in chars)):
                return []
        except (KeyError, TypeError, ValueError):
            return []
        prefix = raw_text[:len(raw_text)-len(raw_text.lstrip(' '))]
        # Only an actual ASCII-space prefix proves this layout advance.
        if (raw_text[:1].isspace() and not prefix or '\t' in raw_text
            or re.search(r' {3,}', raw_text[len(prefix):].rstrip(' '))
            or len(raw_text)-len(raw_text.rstrip(' ')) > 1):
            return []
        measured.append((raw_text.strip(), first, first-left, len(prefix), size))
    labels = [(i, label.match(text)) for i, (text, *_rest) in enumerate(measured) if label.match(text)]
    if len(labels) < 2 or labels[0][0] != 0 or len({m.group(1) for _, m in labels}) < 2:
        return []
    rail = measured[0][1]
    if any(abs(measured[i][1]-rail) > .1 or measured[i][3] for i, _ in labels):
        return []
    starts = [i for i, _ in labels]
    # A short section heading has independent evidence: a following source
    # bullet and a return to the same rail, rather than an arbitrary row cut.
    last = len(measured)-1
    if last not in starts and abs(measured[last][1]-rail) < .1 and not measured[last][3]:
        if (not re.fullmatch(r'[A-Z][A-Za-z ]{2,32}', measured[last][0])
            or not following or not re.match(r'^[∙•●]\s', following.get('text', '').strip())):
            return []
        starts.append(last)
    groups = [records[a:b] for a, b in zip(starts, starts[1:]+[len(records)])]
    continued = False
    for start, end in zip(starts, starts[1:]+[len(records)]):
        tail = measured[start+1:end]
        if not tail: continue
        continued = True
        if (any(prefix < 2 or advance < size*.7 or first <= rail for _text, first, advance, prefix, size in tail)
            or max(first for _text, first, *_rest in tail)-min(first for _text, first, *_rest in tail) > .1):
            return []
    return groups if continued else []


def restore_source_field_paragraphs(table, layout, header, page_width):
    """Leave unsupported source or native metadata unchanged."""
    try:
        return _restore_source_field_paragraphs(table, layout, header, page_width)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        return 0


def _restore_source_field_paragraphs(table, layout, header, page_width):
    """Restore proved field semantics without changing text, styles or height.

    This runs only after a complete illustrated source frame has been built.
    All allocation and paragraph changes are staged on copies, so unsupported
    text/geometry leaves both the native table and its style inventory intact.
    """
    HH = '{http://www.hancom.co.kr/hwpml/2011/head}'
    HC = '{http://www.hancom.co.kr/hwpml/2011/core}'
    from hwpx.tools.paragraph_spacing import paragraph_spacing

    geometries = layout.get('native_tables') or []
    records = (layout.get('source_typography') or {}).get('lines') or []
    try:
        source_width = float(layout.get('source_page_width_pt') or 0)
        if not all(math.isfinite(v) and v > 0 for v in (source_width,page_width)): return 0
    except (TypeError, ValueError): return 0
    if (not layout.get('source_literal_text') or layout.get('source_answer_blanks')
        or len(geometries) != 1 or not geometries[0].get('source_prose_frame')
        or not geometries[0].get('images') or not records or source_width <= 0
        or table.find('.//'+HP+'equation') is not None
        or _compact(''.join(t.text or '' for t in table.iter(HP+'t'))) != _compact(geometries[0].get('source_frame_text', ''))
        or _compact(''.join(r.get('text', '') for r in records)) != _compact(geometries[0].get('source_frame_text', ''))):
        return 0
    try:
        frame = fitz.Rect(geometries[0]['bbox_pt'])
        size = table.find(HP+'sz')
        scale = page_width/source_width
        if (frame.is_empty or not all(math.isfinite(v) for v in frame)
            or size is None or any(not math.isfinite(float(size.get(key))) for key in ('width','height'))
            or any(not frame.contains(fitz.Rect(r['bbox_pt'])) for r in records)
            or abs(float(size.get('width'))-frame.width*scale)>2
            or abs(float(size.get('height'))-frame.height*scale)>2
            or table.find('.//'+HP+'tbl') is not None
            or len(table.findall('.//'+HP+'pic')) != len(geometries[0]['images'])
            or any(pic.find(HP+'pos').get('treatAsChar')!='1' for pic in table.findall('.//'+HP+'pic'))):
            return 0
    except (AttributeError, KeyError, TypeError, ValueError): return 0
    staged, staged_header = deepcopy(table), deepcopy(header)
    styles = {p.get('id'):p for p in staged_header.iter(HH+'paraPr')}
    char_styles = {c.get('id'):c for c in header.iter(HH+'charPr')}
    for run in table.iter(HP+'run'):
        value = ''.join(t.text or '' for t in run.findall(HP+'t'))
        char_style = char_styles.get(run.get('charPrIDRef'))
        underline = char_style.find(HH+'underline') if char_style is not None else None
        if (value and value.isspace() and underline is not None
            and underline.get('type') not in (None,'NONE')):
            return 0
    properties = staged_header.find('.//'+HH+'paraProperties')
    if properties is None: return 0
    original_style_count = len(properties)
    next_style = max(int(v) for v in styles)+1
    next_id = max((int(n.get('id')) for n in table.getroottree().getroot().iter()
                   if n.get('id', '').isdigit()), default=0)+1
    scale, cursor, restored = page_width/source_width, 0, 0
    original_text = ''.join(t.text or '' for t in table.iter(HP+'t'))
    for cell in staged.findall(HP+'tr/'+HP+'tc'):
        sub = cell.find(HP+'subList')
        for paragraph in list(sub.findall(HP+'p')):
            runs = paragraph.findall(HP+'run')
            text = ''.join(t.text or '' for run in runs for t in run.findall(HP+'t'))
            if not _compact(text): continue
            start, value = cursor, ''
            while cursor < len(records) and len(value) < len(_compact(text)):
                value += _compact(records[cursor].get('text', '')); cursor += 1
            if value != _compact(text): return 0
            own = records[start:cursor]
            groups = _source_field_groups(own, records[cursor] if cursor < len(records) else None)
            if not groups: continue
            if any(child.tag != HP+'t' or len(child) for run in runs for child in run): return 0
            cache = paragraph.findall(HP+'linesegarray/'+HP+'lineseg')
            style = styles.get(paragraph.get('paraPrIDRef'))
            if len(cache) != len(own) or style is None: return 0
            try:
                if any(not math.isfinite(float(line.get(key)))
                       for line in cache for key in ('textpos','vertpos','vertsize','textheight','baseline','spacing','horzpos','horzsize')):
                    return 0
                text_offsets = [int(line.get('textpos')) for line in cache]
                if any(a >= b for a,b in zip(text_offsets,text_offsets[1:])): return 0
                if (float(style.find('.//'+HC+'intent').get('value')) != 0
                    or float(style.find('.//'+HC+'left').get('value')) != 0
                    or any(float(l.get('horzpos')) != 0 for l in cache)
                    or any(abs(float(b.get('vertpos'))-float(a.get('vertpos'))
                               -float(a.get('vertsize'))-float(a.get('spacing'))) > 1 for a,b in zip(cache,cache[1:]))):
                    return 0
                before, after = paragraph_spacing(paragraph, styles)
                old_flow = sum(float(l.get('vertsize'))+float(l.get('spacing')) for l in cache)+before+after
                if not math.isfinite(old_flow) or old_flow <= 0: return 0
            except (AttributeError, TypeError, ValueError): return 0
            positions = [i for i,c in enumerate(text) if not c.isspace()]
            source_offset = 0
            for i,record in enumerate(own):
                expected_offset = (len(text[:positions[source_offset]].encode('utf-16-le'))//2 if i else 0)
                if int(cache[i].get('textpos')) != expected_offset: return 0
                source_offset += len(_compact(record['text']))
            count, boundaries = 0, [0]
            for group in groups[:-1]:
                count += sum(len(_compact(r['text'])) for r in group)
                boundaries.append(positions[count])
            boundaries.append(len(text))
            replacements, row_index = [], 0
            for gi, (group, a, b) in enumerate(zip(groups,boundaries,boundaries[1:])):
                new, copied_style = deepcopy(paragraph), deepcopy(style)
                new.set('id',str(next_id)); next_id += 1
                for child in list(new): new.remove(child)
                offset = 0
                for run in runs:
                    part = ''.join(t.text or '' for t in run)
                    x,y = max(0,a-offset),min(len(part),b-offset)
                    if x < y:
                        copied_run = deepcopy(run)
                        for child in list(copied_run): copied_run.remove(child)
                        etree.SubElement(copied_run,HP+'t').text = part[x:y]
                        new.append(copied_run)
                    offset += len(part)
                copied_style.set('id',str(next_style)); next_style += 1
                new.set('paraPrIDRef',copied_style.get('id'))
                continuation = group[1:] if len(group)>1 else []
                indent = (round((next(c for s in continuation[0]['spans'] for c in s['chars'] if c['c'].strip())['origin'][0]
                                 -next(c for s in group[0]['spans'] for c in s['chars'] if c['c'].strip())['origin'][0])*scale)
                          if continuation else 0)
                new_cache = etree.SubElement(new,HP+'linesegarray')
                start_utf16 = len(text[:a].encode('utf-16-le'))//2
                initial = float(cache[row_index].get('vertpos'))
                for i in range(len(group)):
                    line = deepcopy(cache[row_index+i])
                    line.set('textpos',str(0 if i==0 else int(line.get('textpos'))-start_utf16))
                    line.set('vertpos',str(round(float(line.get('vertpos'))-initial)))
                    line.set('horzpos','0')
                    line.set('horzsize',str(round(float(line.get('horzsize'))-(indent if i else 0))))
                    if i+1==len(group): line.set('spacing','0')
                    new_cache.append(line)
                row_index += len(group)
                gap = (float(cache[row_index-1].get('spacing')) if row_index<len(cache)
                       else float(cache[-1].get('spacing'))+after)
                for margin in copied_style.findall('.//'+HH+'margin'):
                    for key,v in {'intent':-indent,'prev':before if gi==0 else 0,'next':gap}.items():
                        margin.find(HC+key).set('value',str(round(v)))
                if len(group)>1:
                    step = float(new_cache[1].get('vertpos'))-float(new_cache[0].get('vertpos'))
                    percent = round(step/float(new_cache[0].get('vertsize'))*100)
                    for spacing in copied_style.findall('.//'+HH+'lineSpacing'): spacing.set('value',str(percent))
                properties.append(copied_style);styles[copied_style.get('id')]=copied_style
                replacements.append(new)
            new_flow = sum(sum(float(l.get('vertsize'))+float(l.get('spacing')) for l in p.findall(HP+'linesegarray/'+HP+'lineseg'))
                           +sum(paragraph_spacing(p,styles)) for p in replacements)
            if abs(new_flow-old_flow)>1 or ''.join(''.join(t.text or '' for t in p.iter(HP+'t')) for p in replacements)!=text:
                return 0
            index = sub.index(paragraph)
            for i,p in enumerate(replacements): sub.insert(index+i,p)
            sub.remove(paragraph); restored += 1
        if not _illustrated_cell_cache_fits(cell,styles): return 0
    if cursor != len(records) or not restored or ''.join(t.text or '' for t in staged.iter(HP+'t'))!=original_text:
        return 0
    target_properties = header.find('.//'+HH+'paraProperties')
    target_properties.extend(list(properties)[original_style_count:])
    target_properties.set('itemCnt',str(len(target_properties)))
    for child in list(table): table.remove(child)
    table.extend(list(staged))
    return restored


def restore_illustrated_frame_cells(root, layout, header, page_width, column_width, pictures, flow_style, *, char_style=None):
    """Partition a complete frame only at real prose/illustration relationships."""
    from .pdf_picture_geometry import set_picture_display_size
    from .pdf_source_spacing import set_space_after, set_space_before
    from .hwpx_writer_v2 import _set_paragraph_element_lineseg
    geometry = layout['native_tables'][0]
    frame = fitz.Rect(geometry['bbox_pt'])
    records = layout['source_typography']['lines']
    topology = illustrated_frame_topology(frame, records, geometry['images'])
    if topology is None or len(pictures) != len(geometry['images']):
        return False
    if topology.get('mode') == 'paragraph_wrap':
        from .pdf_wrapped_prose_frames import restore_wrapped_frame
        return restore_wrapped_frame(root, layout, header, page_width, column_width, pictures, char_style=char_style)
    table = root.find(HP+'run/'+HP+'tbl')
    original = table.find(HP+'tr/'+HP+'tc')
    paragraphs = original.findall(HP+'subList/'+HP+'p')
    scale = page_width / layout['source_page_width_pt']
    cuts, split, side = topology['row_y_pt'], topology['split_x_pt'], topology['side']
    row_groups, cursor = [[] for _ in cuts[1:]], 0
    for paragraph in paragraphs:
        value = _compact(''.join(t.text or '' for t in paragraph.findall(HP+'run/'+HP+'t')))
        start, text = cursor, ''
        while cursor < len(records) and len(text) < len(value):
            text += _compact(records[cursor]['text'])
            cursor += 1
        if not value or value != text:
            return False
        group = records[start:cursor]
        row = next((i for i,(top,bottom) in enumerate(zip(cuts,cuts[1:]))
                    if all(record['bbox_pt'][1] >= top-.1 and record['bbox_pt'][3] <= bottom+.1 for record in group)), None)
        if row is None:
            return False
        row_groups[row].append((paragraph,group))
    if cursor != len(records) or not all(row_groups):
        return False
    styles = {style.get('id'):style for style in header.iter('{http://www.hancom.co.kr/hwpml/2011/head}paraPr')}
    margins = original.find(HP+'cellMargin')
    text_left = float(margins.get('left'))
    wrapped = topology['wrapped_image_index']
    xcuts = [frame.x0]
    if wrapped is not None:xcuts.append(float(geometry['images'][wrapped]['bbox_pt'][0]))
    xcuts.extend((split,frame.x1))
    columns=len(xcuts)-1
    def make_cell(row, col, row_span=1, col_span=1):
        cell = deepcopy(original)
        cell.set('name',f'source-prose-frame:r{row}:c{col}')
        cell.find(HP+'cellAddr').attrib.update({'rowAddr':str(row),'colAddr':str(col)})
        cell.find(HP+'cellSpan').attrib.update({'rowSpan':str(row_span),'colSpan':str(col_span)})
        cell.find(HP+'cellSz').attrib.update({'width':str(round((xcuts[col+col_span]-xcuts[col])*scale)),
            'height':str(round((cuts[row+row_span]-cuts[row])*scale))})
        sub = cell.find(HP+'subList')
        for child in list(sub):sub.remove(child)
        sub.set('vertAlign','TOP')
        cell.find(HP+'cellMargin').attrib.update({edge:'0' for edge in ('left','right','top','bottom')})
        cell.set('borderFillIDRef',_border_fill(header,original.get('borderFillIDRef'),
            left=col==0,right=col+col_span==columns,top=row==0,bottom=row+row_span==len(row_groups)))
        return cell
    rows = [etree.Element(HP+'tr') for _ in row_groups]
    text_cells = []
    for row, groups in enumerate(row_groups):
        cell = make_cell(row,0,col_span=columns if row==0 else columns-1 if row==1 else 1)
        sub = cell.find(HP+'subList')
        for paragraph, _ in groups:sub.append(paragraph)
        first, first_records = groups[0]
        baseline = float(first.find(HP+'linesegarray/'+HP+'lineseg').get('baseline'))
        top = round((first_records[0]['baseline_pt']-cuts[row])*scale-baseline)
        if top < 0:
            return False
        margin = cell.find(HP+'cellMargin')
        margin.set('left',str(round(text_left)))
        margin.set('top',str(top))
        usable=float(cell.find(HP+'cellSz').get('width'))-text_left
        for paragraph,_ in groups:
            for line in paragraph.findall(HP+'linesegarray/'+HP+'lineseg'):
                line.set('horzsize',str(round(min(float(line.get('horzsize')),
                    usable-float(line.get('horzpos'))))))
        text_cells.append(cell)
    main = text_cells[0]
    rows[0].append(main)
    image_cell = make_cell(1,columns-1,row_span=len(row_groups)-1)
    primary = topology['primary_image_index']
    big = pictures[primary]
    bounds = fitz.Rect(geometry['images'][primary]['bbox_pt'])
    set_picture_display_size(big,bounds.width*scale,bounds.height*scale)
    big.find(HP+'pos').attrib.update({'treatAsChar':'1','vertOffset':'0','horzOffset':'0','affectLSpacing':'0'})
    for edge in ('left','right','top','bottom'):big.find(HP+'outMargin').set(edge,'0')
    identifier=max((int(node.get('id')) for node in root.getroottree().getroot().iter()
                    if node.get('id','').isdigit()),default=0)
    def image_paragraph(picture,bounds):
        nonlocal identifier
        identifier+=1
        paragraph=etree.Element(HP+'p',attrib=dict(paragraphs[0].attrib))
        paragraph.set('id',str(identifier));paragraph.set('paraPrIDRef',flow_style)
        run=etree.SubElement(paragraph,HP+'run',charPrIDRef=paragraphs[0].find(HP+'run').get('charPrIDRef','0'))
        run.append(picture)
        set_picture_display_size(picture,bounds.width*scale,bounds.height*scale)
        picture.find(HP+'pos').attrib.update({'treatAsChar':'1','vertOffset':'0','horzOffset':'0','affectLSpacing':'0'})
        for edge in ('left','right','top','bottom'):picture.find(HP+'outMargin').set(edge,'0')
        _set_paragraph_element_lineseg(paragraph,round(bounds.height*scale),width=round(bounds.width*scale),spacing_ratio=0)
        return paragraph
    image_cell.find(HP+'subList').append(image_paragraph(big,bounds))
    for row in range(1,len(rows)):
        rows[row].append(text_cells[row])
        if row==1:rows[row].append(image_cell)
    if wrapped is not None:
        picture = pictures[wrapped]
        bounds = fitz.Rect(geometry['images'][wrapped]['bbox_pt'])
        small_cell=make_cell(len(rows)-1,1)
        small_cell.find(HP+'subList').append(image_paragraph(picture,bounds))
        rows[-1].append(small_cell)
    # A semantic paragraph's last baseline has no following interline step.
    # Derive the next paragraph's ordinary after-gap from its actual source
    # baseline instead of retaining a whole-frame median step for short bullets.
    for groups in row_groups:
        for index,(paragraph,source) in enumerate(groups):
            cache=paragraph.findall(HP+'linesegarray/'+HP+'lineseg')
            if not cache or len(cache)!=len(source):return False
            initial=float(cache[0].get('vertpos'))
            for line in cache:line.set('vertpos',str(round(float(line.get('vertpos'))-initial)))
            cache[-1].set('spacing','0')
            occupied=sum(float(line.get('vertsize'))+float(line.get('spacing')) for line in cache)
            top=source[0]['baseline_pt']*scale-float(cache[0].get('baseline'))
            following=(groups[index+1] if index+1<len(groups) else None)
            gap=0
            if following is not None:
                next_p,next_source=following
                next_cache=next_p.find(HP+'linesegarray/'+HP+'lineseg')
                gap=next_source[0]['baseline_pt']*scale-float(next_cache.get('baseline'))-top-occupied
                if gap < -2:return False
            set_space_before(paragraph,header,0)
            set_space_after(paragraph,header,max(0,gap))
    for old in table.findall(HP+'tr'):table.remove(old)
    table.set('rowCnt',str(len(rows)))
    table.set('colCnt',str(columns))
    for row in rows:table.append(row)
    table.find(HP+'sz').attrib.update({'width':str(round(frame.width*scale)),'height':str(round(frame.height*scale))})
    document=root.getroottree().getroot()
    page=document.find('.//'+HP+'pagePr')
    margin=page.find(HP+'margin')
    columns=next(column for column in document.iter(HP+'colPr') if column.get('colCount')=='2')
    origin=float(margin.get('left'))+(column_width+float(columns.get('sameGap'))) * (int(layout.get('source_column') or 1)-1)
    offset=round(frame.x0*scale-origin)
    table.find(HP+'pos').attrib.update({'treatAsChar':'0','affectLSpacing':'0','flowWithText':'1','allowOverlap':'0',
        'vertRelTo':'PARA','horzRelTo':'COLUMN','vertAlign':'TOP','horzAlign':'LEFT','vertOffset':'0','horzOffset':str(offset)})
    _set_paragraph_element_lineseg(root,round(frame.height*scale),width=round(column_width),spacing_ratio=0)
    restore_source_field_paragraphs(table,layout,header,page_width)
    return True


def finalize_illustrated_frame_height(root, layout, header, page_width):
    """Discard generic row padding only after complete source and ink proof."""
    geometries=layout.get('native_tables') or []
    if (not layout.get('source_literal_text') or len(geometries)!=1
        or not geometries[0].get('source_prose_frame') or not geometries[0].get('images')):
        return False
    geometry=geometries[0]
    frame=fitz.Rect(geometry['bbox_pt'])
    records=(layout.get('source_typography') or {}).get('lines') or []
    topology=illustrated_frame_topology(frame,records,geometry['images']) if records else None
    if topology is not None and topology.get('mode') == 'paragraph_wrap':
        from .pdf_wrapped_prose_frames import finalize_wrapped_frame
        return finalize_wrapped_frame(root,layout,header,page_width)
    table=root.find(HP+'run/'+HP+'tbl')
    if topology is None or table is None or table.get('colCnt') not in ('2','3'):return False
    if _compact(''.join(t.text or '' for t in table.iter(HP+'t')))!=_compact(geometry.get('source_frame_text') or ''):return False
    scale=page_width/layout['source_page_width_pt']
    pictures=table.findall('.//'+HP+'pic')
    if len(pictures)!=len(geometry['images']):return False
    for picture,image in zip(pictures,geometry['images']):
        bounds=fitz.Rect(image['bbox_pt'])
        size=picture.find(HP+'sz')
        if (size is None or abs(float(size.get('width'))-bounds.width*scale)>2
            or abs(float(size.get('height'))-bounds.height*scale)>2):return False
    cuts=topology['row_y_pt']
    styles={style.get('id'):style for style in header.iter('{http://www.hancom.co.kr/hwpml/2011/head}paraPr')}
    for cell in table.findall(HP+'tr/'+HP+'tc'):
        addr,span=cell.find(HP+'cellAddr'),cell.find(HP+'cellSpan')
        row=int(addr.get('rowAddr'));row_span=int(span.get('rowSpan'))
        height=round((cuts[row+row_span]-cuts[row])*scale)
        if not _illustrated_cell_cache_fits(cell,styles,height):return False
    for cell in table.findall(HP+'tr/'+HP+'tc'):
        addr,span=cell.find(HP+'cellAddr'),cell.find(HP+'cellSpan')
        row=int(addr.get('rowAddr'));row_span=int(span.get('rowSpan'))
        cell.find(HP+'cellSz').set('height',str(round((cuts[row+row_span]-cuts[row])*scale)))
    table.find(HP+'sz').set('height',str(round(frame.height*scale)))
    from .hwpx_writer_v2 import _set_paragraph_element_lineseg
    _set_paragraph_element_lineseg(root,round(frame.height*scale),width=int(root.find(HP+'linesegarray/'+HP+'lineseg').get('horzsize')),spacing_ratio=0)
    return True


def _illustrated_cell_cache_fits(cell, styles, height=None):
    """Fail closed on clipped cache bands, including positive descenders."""
    from hwpx.tools.paragraph_spacing import paragraph_spacing
    try:
        margin=cell.find(HP+'cellMargin');size=cell.find(HP+'cellSz')
        width=float(size.get('width'))-sum(float(margin.get(edge)) for edge in ('left','right'))
        height=float(size.get('height')) if height is None else float(height)
        top,bottom=(float(margin.get(edge)) for edge in ('top','bottom'))
        occupied=band=0
        if min(width,height)<=0 or min(top,bottom)<0:return False
        paragraphs=cell.findall(HP+'subList/'+HP+'p')
        if not paragraphs:return False
        for paragraph in paragraphs:
            cache=paragraph.findall(HP+'linesegarray/'+HP+'lineseg')
            if not cache:return False
            for line in cache:
                y,size_y,text_y,baseline,spacing,x,size_x=(float(line.get(key)) for key in
                    ('vertpos','vertsize','textheight','baseline','spacing','horzpos','horzsize'))
                if (not all(math.isfinite(v) for v in (y,size_y,text_y,baseline,spacing,x,size_x))
                    or not 0<baseline<text_y<=size_y or min(y,spacing,x)<0 or size_x<=0
                    or x+size_x>width+2):return False
                band=max(band,y+size_y+spacing)
                occupied+=size_y+spacing
            gaps=paragraph_spacing(paragraph,styles)
            if any(not math.isfinite(v) or v<0 for v in gaps):return False
            occupied+=sum(gaps)
        return all(math.isfinite(v) for v in (width,height,top,bottom,occupied,band)) and top+bottom+max(occupied,band)<=height+2
    except (AttributeError,TypeError,ValueError):
        return False


def source_flow_illustrated_frame_table(table, root, header, hrefs, package, source):
    """Prove the whole editable frame from PDF rules, prose and picture pixels.

    Cell names and producer metadata are deliberately ignored. The only split
    rows accepted are the actual side illustration and its smaller companion;
    the source prose remains in semantic native paragraphs.
    """
    from .pdf_layout_writer import _iter_text_lines, _line_text
    from .pdf_native_content import _source_prose_frame
    from .pdf_picture_geometry import has_complete_picture_crop
    from .pdf_source_image_validation import render_source_crop, compare_source_crop
    from hwpx.tools.paragraph_spacing import paragraph_indentation
    HH='{http://www.hancom.co.kr/hwpml/2011/head}'
    HC='{http://www.hancom.co.kr/hwpml/2011/core}'
    pos,size=table.find(HP+'pos'),table.find(HP+'sz')
    cells=table.findall(HP+'tr/'+HP+'tc')
    pictures=table.findall('.//'+HP+'pic')
    if (pos is None or size is None or len(cells) not in (3,5) or len(pictures) not in (1,2)
        or table.get('colCnt') not in ('2','3') or table.get('rowCnt') not in ('2','3')
        or table.get('lock')=='1' or table.get('textWrap')!='TOP_AND_BOTTOM'
        or any(table.find('.//'+HP+tag) is not None for tag in ('tbl','rect','equation'))
        or any(pos.get(k)!=v for k,v in (('treatAsChar','0'),('vertRelTo','PARA'),
            ('horzRelTo','COLUMN'),('vertOffset','0'),('flowWithText','1'),
            ('allowOverlap','0'),('horzAlign','LEFT'),('vertAlign','TOP')))):
        return False
    def number(node,key):
        value=float(node.get(key))
        if not math.isfinite(value):raise ValueError('non-finite source frame')
        return value
    try:
        native=_compact(''.join(t.text or '' for t in table.iter(HP+'t')))
        page_pr=root.find('.//'+HP+'pagePr')
        margins=page_pr.find(HP+'margin')
        columns=next(c for c in root.iter(HP+'colPr') if c.get('colCount')=='2')
        page_width=number(page_pr,'width')
        left,gap=number(margins,'left'),number(columns,'sameGap')
        column_width=(page_width-left-number(margins,'right')-gap)/2
        offset,width,height=number(pos,'horzOffset'),number(size,'width'),number(size,'height')
        if not native or min(width,height)<=0 or offset<0 or offset+width>column_width+2:return False
        styles={s.get('id'):s for s in header.iter(HH+'paraPr')}
        fills={f.get('id'):f for f in header.iter(HH+'borderFill')}
        with fitz.open(source) as document:
            for page_index,page in enumerate(document):
                scale=page_width/page.rect.width
                drawings=page.get_drawings()
                horizontals=[]
                for drawing in drawings:
                    for part in drawing.get('items',[]):
                        if part[0]=='l' and abs(part[1].y-part[2].y)<.5:
                            horizontals.append((min(part[1].x,part[2].x),part[1].y,max(part[1].x,part[2].x)))
                        elif part[0]=='re':
                            box=fitz.Rect(part[1]);horizontals.extend(((box.x0,box.y0,box.x1),(box.x0,box.y1,box.x1)))
                for origin in (left,left+column_width+gap):
                    for x0,y0,x1 in horizontals:
                        if (abs(x0*scale-origin-offset)>2 or abs((x1-x0)*scale-width)>2):continue
                        frame=_source_prose_frame(fitz.Rect(x0,y0,x1,y0+height/scale),drawings)
                        if frame is None or abs(frame.height*scale-height)>2:continue
                        lines=[line for line in _iter_text_lines(page) if frame.contains(fitz.Rect(line['bbox']))]
                        lines.sort(key=lambda line:(line['bbox'][1],line['bbox'][0]))
                        if ''.join(_compact(_line_text(line)) for line in lines)!=native:continue
                        records=[{'text':_line_text(line),'bbox_pt':list(line['bbox']),
                            'font_size_pt':median(float(span.get('size') or 11) for span in line['spans'])}
                            for line in lines]
                        source_images=[{'bbox_pt':list(fitz.Rect(image['bbox']))} for image in page.get_text('dict')['blocks']
                            if image.get('type')==1 and frame.contains(fitz.Rect(image['bbox'])) and not fitz.Rect(image['bbox']).is_empty]
                        source_images.sort(key=lambda image:(image['bbox_pt'][1],image['bbox_pt'][0]))
                        topology=illustrated_frame_topology(frame,records,source_images)
                        if topology is None or len(source_images)!=len(pictures):continue
                        if _prove_illustrated_cells(table,cells,pictures,frame,records,source_images,topology,
                            scale,styles,fills,hrefs,package,source,page_index,number,paragraph_indentation,
                            has_complete_picture_crop,render_source_crop,compare_source_crop):
                            return True
    except (ValueError,TypeError,AttributeError,KeyError,IndexError,StopIteration,OSError):
        pass
    return False


def _prove_illustrated_cells(table,cells,pictures,frame,records,images,topology,scale,styles,fills,
    hrefs,package,source,page_index,number,indentation,complete_crop,source_crop,compare_crop):
    HH='{http://www.hancom.co.kr/hwpml/2011/head}'
    HC='{http://www.hancom.co.kr/hwpml/2011/core}'
    cuts=topology['row_y_pt'];split=topology['split_x_pt']
    columns=3 if topology['wrapped_image_index'] is not None else 2
    expected={(0,0):(1,columns),(1,0):(1,columns-1),(1,columns-1):(len(cuts)-2,1)}
    if len(cuts)==4:expected.update({(2,0):(1,1),(2,1):(1,1)})
    indexed={}
    for cell in cells:
        addr,span=cell.find(HP+'cellAddr'),cell.find(HP+'cellSpan')
        row,col=int(number(addr,'rowAddr')),int(number(addr,'colAddr'))
        spans=(int(number(span,'rowSpan')),int(number(span,'colSpan')))
        if (row,col) in indexed or expected.get((row,col))!=spans:return False
        indexed[row,col]=cell
        if cell.get('hasMargin')!='1' or cell.get('protect')=='1':return False
        xcuts=[frame.x0]+([images[topology['wrapped_image_index']]['bbox_pt'][0]] if columns==3 else [])+[split,frame.x1]
        if (abs(number(cell.find(HP+'cellSz'),'width')-(xcuts[col+spans[1]]-xcuts[col])*scale)>2
            or abs(number(cell.find(HP+'cellSz'),'height')-(cuts[row+spans[0]]-cuts[row])*scale)>2):return False
        if not _illustrated_cell_cache_fits(cell,styles):return False
        fill=fills.get(cell.get('borderFillIDRef'))
        if fill is None:return False
        for edge,visible in zip(('left','right','top','bottom'),
            (col==0,col+spans[1]==columns,row==0,row+spans[0]==len(cuts)-1)):
            if fill.find(HH+edge+'Border').get('type')!=('SOLID' if visible else 'NONE'):return False
        original=''.join(_compact(record['text']) for record in records
            if record['bbox_pt'][1]>=cuts[row]-.1 and record['bbox_pt'][3]<=cuts[row+1]+.1) if col==0 else ''
        if _compact(''.join(t.text or '' for t in cell.iter(HP+'t')))!=original:return False
    if set(indexed)!=set(expected):return False
    for index,(picture,image) in enumerate(zip(pictures,images)):
        box=fitz.Rect(image['bbox_pt'])
        size=picture.find(HP+'sz');pos=picture.find(HP+'pos')
        if (abs(number(size,'width')-box.width*scale)>2 or abs(number(size,'height')-box.height*scale)>2
            or any(number(picture.find(HP+'outMargin'),edge) for edge in ('left','right','top','bottom'))):return False
        image_ref=picture.find(HC+'img')
        href=hrefs.get(image_ref.get('binaryItemIDRef'))
        if href not in package.namelist():return False
        payload=package.read(href)
        if not complete_crop(picture,payload) or not compare_crop(source_crop(source,page_index,box),payload)['ok']:return False
        owner=picture.getparent().getparent()
        cell=next(a for a in owner.iterancestors() if a.tag==HP+'tc')
        expected_cell=indexed[1,columns-1] if index==topology['primary_image_index'] else indexed[len(cuts)-2,1]
        if (cell is not expected_cell or pos.get('treatAsChar')!='1'
                or number(pos,'horzOffset') or number(pos,'vertOffset')
                or any((t.text or '').strip() for t in owner.iter(HP+'t'))):return False
        if any(abs(v)>2 for v in indentation(owner,styles)):return False
    return True
