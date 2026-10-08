"""One editable frame for a source-proved alternating-avatar conversation.

The PDF rectangle, every source line and the three real avatar bitmaps must
agree. Rows represent a notice, conversation turns and a semantic answer list;
they never represent individual printed lines. No filename or subject flag
authorizes this reconstruction.
"""
from copy import deepcopy
import hashlib
import io
import math
from pathlib import Path
import re
from statistics import median

import fitz
from lxml import etree
from PIL import Image

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HH = '{http://www.hancom.co.kr/hwpml/2011/head}'
HC = '{http://www.hancom.co.kr/hwpml/2011/core}'
_LABEL = re.compile(r'^\(([가-힣A-Za-z0-9])\)\s*\S')


def _compact(value):
    from .pdf_layout_writer import _pdf_output_text
    return re.sub(r'\s+', '', _pdf_output_text(value))


def _rect(value):
    if len(value) != 4 or not all(math.isfinite(float(v)) for v in value):
        raise ValueError('invalid dialogue bounds')
    box = fitz.Rect(value)
    if box.is_empty or box.is_infinite:
        raise ValueError('empty dialogue bounds')
    return box


def _same(a, b, tolerance=.1):
    return max(abs(x-y) for x, y in zip(_rect(a), _rect(b))) <= tolerance


def dialogue_topology(frame, records, images):
    """Prove three alternating avatars and a genuinely separated answer list."""
    from .pdf_layout_writer import is_hancom_eq_font
    try:
        frame = _rect(frame)
        if len(images) != 3 or len(records) < 8:
            return None
        boxes = [_rect(image['bbox_pt']) for image in images]
        measured = []
        for record in records:
            box = _rect(record['bbox_pt'])
            size, baseline = float(record['font_size_pt']), float(record['baseline_pt'])
            spans = record.get('spans') or []
            if (not frame.contains(box) or not math.isfinite(size+baseline) or size <= 0
                or not box.y0 < baseline <= box.y1 or not spans
                or any(is_hancom_eq_font(str(s.get('font', ''))) for s in spans)
                or _compact(''.join(s.get('text', '') for s in spans)) != _compact(record['text'])):
                return None
            combined = fitz.Rect()
            for span in spans:
                sb = _rect(span['bbox'])
                span_size, flags = float(span['size']), float(span.get('flags') or 0)
                if not span.get('font') or not math.isfinite(span_size+flags) or span_size <= 0 or flags != round(flags):
                    return None
                raw = span.get('chars') or []
                if not raw or ''.join(c.get('c', '') for c in raw) != span.get('text'):
                    return None
                union = fitz.Rect()
                for char in raw:
                    cb, origin = _rect(char['bbox']), char['origin']
                    if len(origin) != 2 or not all(math.isfinite(float(v)) for v in origin):
                        return None
                    union |= cb
                if not _same(sb, union):
                    return None
                combined |= sb
            if not _same(box,combined):return None
            measured.append(box)
        size = median(float(r['font_size_pt']) for r in records)
        if (any(not frame.contains(b) or not size <= min(b.width, b.height)
                or max(b.width, b.height) > size*4 for b in boxes)
            or any(abs(b.width-boxes[0].width) > .1 or abs(b.height-boxes[0].height) > .1 for b in boxes)
            or not boxes[0].y1 < boxes[1].y0 < boxes[1].y1 < boxes[2].y0
            or abs(boxes[0].x0-boxes[2].x0) > size*.15
            or not boxes[0].x1 < frame.x0+frame.width*.3
            or not boxes[1].x0 > frame.x0+frame.width*.7
            or any((b & line).get_area() > .1 for b in boxes for line in measured)
            or any(b.y0 <= a.y0 for a, b in zip(measured, measured[1:]))):
            return None
        label_start = next((i for i, r in enumerate(records) if _LABEL.match(r['text'].strip())), None)
        if label_start is None or measured[label_start].y0 <= boxes[-1].y1:
            return None
        cuts = [frame.y0, boxes[0].y0, boxes[1].y0, boxes[2].y0,
                measured[label_start].y0-size*.15, frame.y1]
        bands = [[] for _ in range(5)]
        for index, box in enumerate(measured):
            band = next((i for i, (a, b) in enumerate(zip(cuts, cuts[1:]))
                         if box.y0 >= a-.1 and box.y1 <= b+.1), None)
            if band is None:
                return None
            bands[band].append(index)
        if not all(bands) or bands[4][0] != label_start:
            return None
        # The notice is centered on the real rectangle, while text turns sit
        # strictly beside their corresponding avatar, without overlap.
        if (any(abs((measured[i].x0+measured[i].x1-frame.x0-frame.x1)/2) > size*.5 for i in bands[0])
            or any(measured[i].x0 < max(boxes[0].x1, boxes[2].x1) for b in (1, 3) for i in bands[b])
            or any(measured[i].x1 > boxes[1].x0 for i in bands[2])):
            return None
        groups = [[band] for band in bands[:4]]
        listing, labels = [], []
        for index in bands[4]:
            match = _LABEL.match(records[index]['text'].strip())
            if match:
                labels.append(match.group(1))
                listing.append([index])
            elif listing:
                if measured[index].x0 <= measured[listing[-1][0]].x0+size*.5:
                    return None
                listing[-1].append(index)
            else:
                return None
        if len(listing) < 2 or len(labels) != len(set(labels)):
            return None
        rails = [measured[group[0]].x0 for group in listing]
        if max(rails)-min(rails) > .1:
            return None
        groups.append(listing)
        return {'row_y_pt': cuts, 'column_x_pt': [frame.x0, max(boxes[0].x1, boxes[2].x1), boxes[1].x0, frame.x1],
                'groups': groups, 'text_cells': [(0, 1, 1), (1, 1, 2), (2, 0, 2), (3, 1, 2), (4, 0, 3)],
                'image_cells': [(1, 0), (2, 2), (3, 0)], 'empty_cells':[(0,0),(0,2)]}
    except (ValueError, TypeError, KeyError, IndexError):
        return None


def _source_avatar_proof(page, pictures):
    from .pdf_layout_writer import _item_bbox
    source = page.get_image_info(xrefs=True)
    images = []
    for picture in pictures:
        box = _item_bbox(picture)
        matches = [image for image in source if _same(image['bbox'], box, .01) and image.get('xref', 0) > 0]
        if len(matches) != 1:
            return None
        match = matches[0]
        pix = fitz.Pixmap(page.parent, match['xref'])
        if pix.width < 2 or pix.height < 2 or not pix.samples:
            return None
        images.append({'bbox_pt': list(box), 'pixel_sha256': hashlib.sha256(pix.samples).hexdigest(),
                       'pixel_size': [pix.width, pix.height], 'source_xref': match['xref']})
    if (len(images) != 3 or images[0]['pixel_sha256'] != images[2]['pixel_sha256']
        or images[0]['pixel_sha256'] == images[1]['pixel_sha256']):
        return None
    return images


def _compose_dialogue_background(page,frame,bitmaps):
    """Compose original image objects, respecting a higher-resolution SMask.

    PDF soft masks can have a different sample grid from their base image.
    Both map to the same original image rectangle. Keep the finer mask grid
    before mapping to the native fill, rather than resizing its geometry or
    rendering any PDF text into the decoration.
    """
    canvas = Image.new('RGBA',(round(frame.width*2),round(frame.height*2)),'white')
    for block in bitmaps:
        matrix = fitz.Matrix(block['transform'])
        bounds = _rect(block['bbox'])
        if (not frame.contains(bounds) or abs(matrix.b)>.001 or abs(matrix.c)>.001
            or matrix.a<=0 or matrix.d<=0):
            raise ValueError('unsupported dialogue bitmap transform')
        with Image.open(io.BytesIO(block['image'])) as original:
            image = original.convert('RGBA')
        if block.get('mask'):
            with Image.open(io.BytesIO(block['mask'])) as original_mask:
                mask = original_mask.convert('L')
            if image.size != mask.size:
                if (mask.width%image.width or mask.height%image.height
                    or mask.width//image.width != mask.height//image.height):
                    raise ValueError('unproved dialogue soft-mask grid')
                image = image.resize(mask.size,Image.Resampling.BILINEAR)
            image.putalpha(mask)
        target = [round((bounds.x0-frame.x0)*2),round((bounds.y0-frame.y0)*2),
                  round((bounds.x1-frame.x0)*2),round((bounds.y1-frame.y0)*2)]
        if min(target[2]-target[0],target[3]-target[1])<=0:
            raise ValueError('empty dialogue decoration')
        image = image.resize((target[2]-target[0],target[3]-target[1]),Image.Resampling.BICUBIC)
        canvas.alpha_composite(image,target[:2])
    output = io.BytesIO();canvas.convert('RGB').save(output,format='PNG')
    return output.getvalue()


def compose_proved_dialogue_background(page, region, numbers):
    """Decode decoration objects only after independently proving a dialogue.

    A provenance role or digest is insufficient. The original four rules,
    raw source prose, alternating avatar pixels and three connected bubble
    strips must reproduce the same rectangle and exact image inventory.
    Other backgrounds retain their existing composition/validation path.
    """
    from .pdf_layout_writer import _iter_text_lines, _item_bbox, _line_text
    from .pdf_native_content import _source_prose_frame, _source_typography
    from .pdf_source_page_memo import source_text_dict
    try:
        region = _rect(region)
        frame = _source_prose_frame(region,page.get_drawings())
        if frame is None or not _same(frame,region,.01):
            return None
        if (not numbers or any(type(n) is not int for n in numbers)
            or len(numbers) != len(set(numbers))):
            return None
        lines = sorted((line for line in _iter_text_lines(page)
            if frame.contains(_item_bbox(line)) and _compact(_line_text(line))),
            key=lambda line:(_item_bbox(line).y0,_item_bbox(line).x0))
        if not lines:
            return None
        records = _source_typography(lines,{'rect':frame})['lines']
        size = median(r['font_size_pt'] for r in records)
        pictures = sorted(({'bbox':_rect(image['bbox'])} for image in page.get_image_info(xrefs=True)
            if frame.contains(_rect(image['bbox']))
            and size <= min(_rect(image['bbox']).width,_rect(image['bbox']).height)
            and max(_rect(image['bbox']).width,_rect(image['bbox']).height) <= size*4),
            key=lambda image:(image['bbox'].y0,image['bbox'].x0))
        images = _source_avatar_proof(page,pictures)
        topology = dialogue_topology(frame,records,images) if images is not None else None
        if topology is None:
            return None
        bitmaps = [block for block in source_text_dict(page)['blocks'] if block.get('type') == 1
            and frame.contains(_rect(block['bbox']))
            and not any(_same(block['bbox'],image['bbox_pt'],.01) for image in images)]
        if (sorted(block['number'] for block in bitmaps) != sorted(numbers)
            or any(_rect(block['bbox']).height > size or _rect(block['bbox']).width < size*8
                   for block in bitmaps)):
            return None
        bands = []
        for bitmap in sorted(bitmaps,key=lambda block:(block['bbox'][1],block['bbox'][0])):
            box = _rect(bitmap['bbox'])
            connected = next((old for old in bands if abs(old.x0-box.x0)<.5 and abs(old.x1-box.x1)<.5
                              and abs(old.y1-box.y0)<.01),None)
            if connected is not None:bands[bands.index(connected)] = connected | box
            else:bands.append(box)
        if len(bands) != 3 or any(not bubble.contains(_item_bbox(lines[index]))
            for bubble,groups in zip(bands,topology['groups'][1:4]) for group in groups for index in group):
            return None
        return _compose_dialogue_background(page,frame,bitmaps)
    except (ValueError,TypeError,AttributeError,KeyError,IndexError,OSError):
        return None


def coalesce_dialogue_frames(blocks, page, source_lines):
    """Join a complete real dialogue frame, retaining each line and picture once."""
    from .pdf_layout_writer import _item_bbox, _line_text
    from .pdf_native_content import _source_prose_frame, _source_typography
    result = list(blocks)
    candidates = []
    for block in blocks:
        if block.get('type') != 'box' or block.get('rect') is None:
            continue
        frame = _source_prose_frame(fitz.Rect(block['rect']), page.get_drawings())
        if frame is not None and not any(_same(frame, old) for old in candidates):
            candidates.append(frame)
    for frame in candidates:
        indices, pieces, pictures = [], [], []
        invalid = False
        for index, block in enumerate(result):
            kind = block.get('type')
            if kind == 'gap':
                continue
            if kind == 'box' and block.get('rect') is not None and _same(block['rect'], frame):
                if any(line.get('type') != 'line' for line in block.get('lines', [])):
                    invalid = True; break
                indices.append(index); pieces.append(block)
            elif kind == 'image' and frame.intersects(_item_bbox(block['image'])):
                picture = block['image']
                if not frame.contains(_item_bbox(picture)) or picture.get('native_graph') or picture.get('diagram_labels'):
                    invalid = True; break
                indices.append(index); pictures.append(picture)
            else:
                value = block.get('rect') or block.get('line') or block.get('native_table')
                if value is not None:
                    box = fitz.Rect(value) if isinstance(value, fitz.Rect) else _item_bbox(value)
                    if frame.intersects(box):
                        invalid = True; break
        if invalid or len(pieces) < 2 or len(pictures) != 3:
            continue
        ordered = sorted((line for piece in pieces for line in piece['lines']), key=lambda l: (_item_bbox(l).y0, _item_bbox(l).x0))
        expected = sorted((line for line in source_lines if frame.contains(_item_bbox(line))), key=lambda l: (_item_bbox(l).y0, _item_bbox(l).x0))
        if (not expected or len(expected) != len(ordered)
            or any(_compact(_line_text(a)) != _compact(_line_text(b)) or not _same(_item_bbox(a), _item_bbox(b))
                   for a, b in zip(ordered, expected))):
            continue
        pictures.sort(key=lambda p: (_item_bbox(p).y0, _item_bbox(p).x0))
        images = _source_avatar_proof(page, pictures)
        records = _source_typography(ordered, pieces[0])['lines']
        if images is None or dialogue_topology(frame, records, images) is None:
            continue
        start, end = min(indices), max(indices)
        if any(i not in indices and result[i].get('type') != 'gap' for i in range(start, end+1)):
            continue
        merged = {**pieces[0], 'rect': frame, 'lines': ordered, 'source_frame_images': pictures,
                  'source_dialogue_frame': {'bbox_pt': list(frame), 'images': images}}
        from .pdf_source_page_memo import source_text_dict
        bitmaps = [b for b in source_text_dict(page)['blocks'] if b.get('type') == 1
                   and frame.contains(fitz.Rect(b['bbox']))
                   and not any(_same(b['bbox'],i['bbox_pt'],.01) for i in images)]
        # Only original small decoration strips overlapping the real prose
        # turns can become the fill. Never rasterize PDF text into this asset.
        if bitmaps:
            size = median(r['font_size_pt'] for r in records)
            if any(fitz.Rect(b['bbox']).height > size or fitz.Rect(b['bbox']).width < size*8 for b in bitmaps):
                continue
            bands = []
            for bitmap in sorted(bitmaps,key=lambda b:(b['bbox'][1],b['bbox'][0])):
                box = fitz.Rect(bitmap['bbox'])
                connected = next((old for old in bands if abs(old.x0-box.x0)<.5 and abs(old.x1-box.x1)<.5
                                  and abs(old.y1-box.y0)<.01),None)
                if connected is not None:bands[bands.index(connected)] = connected | box
                else:bands.append(box)
            topology = dialogue_topology(frame,records,images)
            if len(bands) != 3 or any(not bubble.contains(_item_bbox(ordered[index]))
                for bubble,groups in zip(bands,topology['groups'][1:4]) for group in groups for index in group):
                continue
            numbers = sorted(b['number'] for b in bitmaps)
            payload = _compose_dialogue_background(page,frame,bitmaps)
            merged['_dialogue_background_png'] = payload
            merged['source_dialogue_frame']['background'] = {'sha256':hashlib.sha256(payload).hexdigest(),
                'source_image_numbers':numbers,'page':page.number+1,
                'page_width_px':page.rect.width,'page_height_px':page.rect.height}
        result[start:end+1] = [merged]
    return result


def attach_dialogue_frame(item, block, save_figure, provenance=None):
    """Keep actual avatar assets even when the frame has bitmap decorations."""
    proof = block.get('source_dialogue_frame')
    if not proof:
        return False
    layout = item.get('layout') or {}
    tables = layout.get('native_tables') or []
    records = (layout.get('source_typography') or {}).get('lines') or []
    if (len(tables) != 1 or len(item.get('tables') or []) != 1
        or not _same(tables[0].get('bbox_pt') or [], proof['bbox_pt'])
        or dialogue_topology(proof['bbox_pt'], records, proof['images']) is None
        or _compact(''.join(r['text'] for r in records)) != _compact(''.join(str(c) for row in item['tables'][0] for c in row))):
        raise ValueError('incomplete source dialogue frame')
    geometry = tables[0]
    images = geometry.get('images') or []
    if images and (len(images) != 3 or any(not _same(a['bbox_pt'], b['bbox_pt']) for a, b in zip(images, proof['images']))):
        raise ValueError('competing source dialogue pictures')
    if not images:
        images = [{'row': 0, 'column': 0, 'path': save_figure(fitz.Rect(image['bbox_pt'])), **image}
                  for image in proof['images']]
    geometry.update({'source_prose_frame': True, 'source_frame_text': ''.join(r['text'] for r in records), 'images': images})
    if block.get('_dialogue_background_png'):
        from .importers import _save_image_bytes
        payload, background = block['_dialogue_background_png'],proof['background']
        if hashlib.sha256(payload).hexdigest() != background['sha256'] or provenance is None:
            raise ValueError('unproved source dialogue decoration')
        geometry['background_path'] = _save_image_bytes(f"dialogue_background_p{background['page']}.png",payload)
        geometry['background_preserve_border'] = True
        provenance.append({**background,'role':'source_background_frame',
            'bbox_px':[proof['bbox_pt'][0],proof['bbox_pt'][1],
                       proof['bbox_pt'][2]-proof['bbox_pt'][0],proof['bbox_pt'][3]-proof['bbox_pt'][1]]})
    layout['source_dialogue_frame'] = deepcopy(proof)
    return True


def _split_text_paragraphs(paragraphs, groups):
    """Split only semantic groups, retaining every existing space/run attribute."""
    atoms = []
    for paragraph in paragraphs:
        for run in paragraph.findall(HP+'run'):
            if not len(run) or any(child.tag != HP+'t' or len(child) for child in run):
                return None
            for child in run:
                atoms.extend((char, run, child) for char in child.text or '')
    expected = [_compact(''.join(r['text'] for r in group)) for group in groups]
    if ''.join(_compact(char) for char, _, _ in atoms) != ''.join(expected):
        return None
    output, cursor, consumed = [], 0, 0
    for index, value in enumerate(expected):
        end = cursor
        while end < len(atoms) and consumed < sum(map(len, expected[:index+1])):
            consumed += len(_compact(atoms[end][0])); end += 1
        while end < len(atoms) and atoms[end][0].isspace():
            end += 1
        p = etree.Element(HP+'p', attrib=dict(paragraphs[0].attrib))
        last_run, last_child = None, None
        for char, run, child in atoms[cursor:end]:
            if last_run is not run or last_child is not child:
                copied = etree.SubElement(p, HP+'run', attrib=dict(run.attrib))
                text = etree.SubElement(copied, HP+'t', attrib=dict(child.attrib)); text.text = ''
                last_run, last_child = run, child
            text.text += char
        output.append(p); cursor = end
    return output if cursor == len(atoms) else None


def restore_dialogue_frame(root, layout, header, page_width, column_width, para_style, char_style=None):
    """Reconstruct a flowing native grid only after complete text/cache proof."""
    if not layout.get('source_dialogue_frame'):
        return 0
    try:
        return _restore_dialogue_frame(root, layout, header, page_width, column_width, para_style, char_style)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, StopIteration):
        return 0


def _restore_dialogue_frame(root, layout, header, page_width, column_width, para_style, char_style):
    from .pdf_source_line_cache import apply_source_line_cache
    from .pdf_native_typography import _flow_height
    from .pdf_source_spacing import set_space_after
    from .pdf_picture_geometry import set_picture_display_size
    from .hwpx_writer_v2 import _set_paragraph_element_lineseg
    from .pdf_illustrated_prose_frames import _border_fill
    from .pdf_source_run_styles import restore_source_run_styles
    geometries = layout.get('native_tables') or []
    records = (layout.get('source_typography') or {}).get('lines') or []
    source_width = float(layout.get('source_page_width_pt') or 0)
    if len(geometries) != 1 or not source_width or layout.get('source_answer_blanks'):
        return 0
    geometry = geometries[0]
    frame = _rect(geometry['bbox_pt'])
    images = geometry.get('images') or []
    proof = layout.get('source_dialogue_frame')
    if (not isinstance(proof,dict) or not _same(proof.get('bbox_pt') or [],frame)
        or len(proof.get('images') or []) != 3 or len(images) != 3
        or any(not _same(a['bbox_pt'],b['bbox_pt']) for a,b in zip(images,proof['images']))
        or any(not re.fullmatch(r'[0-9a-f]{64}',image.get('pixel_sha256',''))
               or len(image.get('pixel_size') or []) != 2 or min(image['pixel_size']) < 2
               for image in proof['images'])
        or proof['images'][0]['pixel_sha256'] != proof['images'][2]['pixel_sha256']
        or proof['images'][0]['pixel_sha256'] == proof['images'][1]['pixel_sha256']):
        return 0
    topology = dialogue_topology(frame, records, images)
    tables = root.findall(HP+'run/'+HP+'tbl')
    if (topology is None or len(tables) != 1 or not geometry.get('source_prose_frame')
        or geometry.get('cell_bounds') != [[list(frame)]] or char_style is None):
        return 0
    original_table = tables[0]
    original_cells = original_table.findall(HP+'tr/'+HP+'tc')
    if len(original_cells) != 1 or any(original_table.find('.//'+HP+t) is not None for t in ('tbl','rect','equation')):
        return 0
    if any(child is not original_table and (child.tag != HP+'t' or len(child) or child.text)
           for run in root.findall(HP+'run') for child in run):
        return 0
    for node, keys in ((original_table.find(HP+'sz'),('width','height')),
                       (original_cells[0].find(HP+'cellSz'),('width','height')),
                       (original_cells[0].find(HP+'cellMargin'),('left','right','top','bottom'))):
        values = [float(node.get(key)) for key in keys]
        if any(not math.isfinite(value) or value < 0 for value in values):return 0
    if (_compact(''.join(t.text or '' for t in original_table.iter(HP+'t')))
        != _compact(geometry.get('source_frame_text') or '')
        or _compact(geometry.get('source_frame_text') or '') != _compact(''.join(r['text'] for r in records))):
        return 0
    staged = deepcopy(root)
    table = staged.find(HP+'run/'+HP+'tbl')
    original = table.find(HP+'tr/'+HP+'tc')
    source_paragraphs = original.findall(HP+'subList/'+HP+'p')
    pictures = table.findall('.//'+HP+'pic')
    if len(pictures) != 3:
        return 0
    for picture in pictures:
        owner = picture.getparent().getparent()
        if (owner.tag != HP+'p'
            or any(child is not picture and (child.tag != HP+'t' or len(child) or child.text)
                   for run in owner.findall(HP+'run') for child in run)
            or picture.find(HP+'sz') is None
            or picture.find(HP+'pos') is None or picture.find(HP+'outMargin') is None):
            return 0
        owner.getparent().remove(owner)
        source_paragraphs.remove(owner)
    groups = [[records[index] for index in group] for band in topology['groups'] for group in band]
    paragraphs = _split_text_paragraphs(source_paragraphs, groups)
    if paragraphs is None:
        return 0
    scale = float(page_width)/source_width
    if not math.isfinite(scale) or scale <= 0 or not math.isfinite(float(column_width)):
        return 0
    doc = root.getroottree().getroot()
    page = doc.find('.//'+HP+'pagePr'); margins = page.find(HP+'margin')
    columns = next(c for c in doc.iter(HP+'colPr') if c.get('colCount') == '2')
    origin = float(margins.get('left'))+(column_width+float(columns.get('sameGap')))*(int(layout.get('source_column') or 1)-1)
    offset = round(frame.x0*scale-origin)
    if offset < 0 or offset+frame.width*scale > column_width+2:
        return 0
    cuts, xcuts = topology['row_y_pt'], topology['column_x_pt']
    # Quantize shared boundaries once; independently rounded row heights can
    # otherwise accumulate a unit at the bottom of a multi-row frame.
    ys = [round((y-frame.y0)*scale) for y in cuts]
    xs = [round((x-frame.x0)*scale) for x in xcuts]
    rows, planned, cursor = [etree.Element(HP+'tr') for _ in range(5)], [], 0
    identifier = max((int(n.get('id')) for n in doc.iter() if n.get('id', '').isdigit()), default=0)
    def cell(row, col, span):
        result = deepcopy(original)
        result.set('hasMargin', '1'); result.set('protect', '0')
        result.find(HP+'cellAddr').attrib.update({'rowAddr': str(row), 'colAddr': str(col)})
        result.find(HP+'cellSpan').attrib.update({'rowSpan': '1', 'colSpan': str(span)})
        result.find(HP+'cellSz').attrib.update({'width': str(xs[col+span]-xs[col]), 'height': str(ys[row+1]-ys[row])})
        result.find(HP+'cellMargin').attrib.update({edge: '0' for edge in ('left','right','top','bottom')})
        sub = result.find(HP+'subList'); sub.set('vertAlign','TOP')
        for child in list(sub): sub.remove(child)
        rows[row].append(result)
        return result
    for band, (row, col, span) in enumerate(topology['text_cells']):
        target = cell(row, col, span)
        sub, margin = target.find(HP+'subList'), target.find(HP+'cellMargin')
        source_groups = [[records[i] for i in g] for g in topology['groups'][band]]
        rail = min(r['bbox_pt'][0] for g in source_groups for r in g)
        left = round((rail-xcuts[col])*scale)
        # The original right-side blank remains available to an edited native
        # paragraph. Its left rail/cache pins every original glyph; the real
        # cell edge (or adjacent avatar column) is the reflow boundary.
        right = 0
        usable = xs[col+span]-xs[col]-left-right
        if min(left, right) < 0 or usable <= 0:
            return 0
        margin.set('left', str(left)); margin.set('right', str(right))
        local = []
        for source in source_groups:
            p = paragraphs[cursor]; cursor += 1; identifier += 1; p.set('id',str(identifier))
            size = median(float(r['font_size_pt']) for r in source)*scale
            indent = round((source[0]['bbox_pt'][0]-source[1]['bbox_pt'][0])*scale) if len(source) > 1 else 0
            # Centered notice lines have their own real centers, rather than
            # being a hanging continuation. Cache offsets retain both wraps.
            if band == 0: indent = 0
            candidate = {**layout, 'native_page_width': page_width, 'column_left_pt': rail,
                         'native_indentation': (0, 0, indent),
                         'source_typography': {**layout['source_typography'], 'lines': source, 'font_size_pt': size/scale}}
            if not 500 <= size <= 1600 or not apply_source_line_cache(p, candidate, usable):
                return 0
            lines = p.findall(HP+'linesegarray/'+HP+'lineseg'); lines[-1].set('spacing','0')
            local.append((p, source, size, indent))
            sub.append(p)
        baseline = float(local[0][0].find(HP+'linesegarray/'+HP+'lineseg').get('baseline'))
        top = round((source_groups[0][0]['baseline_pt']-cuts[row])*scale-baseline)
        gaps = []
        for index, (p, source, _, _) in enumerate(local):
            gap = 0
            if index+1 < len(local):
                next_p, next_source, _, _ = local[index+1]
                next_base = float(next_p.find(HP+'linesegarray/'+HP+'lineseg').get('baseline'))
                this_base = float(p.find(HP+'linesegarray/'+HP+'lineseg').get('baseline'))
                gap = round((next_source[0]['baseline_pt']-source[0]['baseline_pt'])*scale+this_base-next_base-_flow_height(p))
            if gap < 0: return 0
            gaps.append(gap)
        bottom = ys[row+1]-ys[row]-top-sum(_flow_height(p)+gap for (p,*_), gap in zip(local,gaps))-200
        if min(top,bottom) < 0: return 0
        steps=[]
        for index,(p,source,size,indent) in enumerate(local):
            step=(median((b['baseline_pt']-a['baseline_pt'])*scale for a,b in zip(source,source[1:]))
                  if len(source)>1 else float(layout['source_typography'].get('line_spacing_pt') or size/scale)*scale)
            percent=max(100,min(250,round(step*100/size)))
            leading=round(size*(percent-100)/100)
            available=gaps[index] if index+1<len(local) else bottom
            if leading>available:
                if len(source)>1:return 0
                # The final single printed line has no following baseline.
                # Keep its positive native descender without inventing a
                # trailing interline reservation outside the real frame.
                step=size;leading=0
            p.findall(HP+'linesegarray/'+HP+'lineseg')[-1].set('spacing',str(leading))
            if index+1<len(local):gaps[index]-=leading
            else:bottom-=leading
            steps.append(step)
        margin.set('top',str(top)); margin.set('bottom',str(bottom))
        planned.extend((p, source, size, indent, gap, step) for (p,source,size,indent),gap,step in zip(local,gaps,steps))
    flow_template = source_paragraphs[0]
    for row,col in topology['empty_cells']:
        target = cell(row,col,1)
        identifier += 1
        p=etree.Element(HP+'p',attrib=dict(flow_template.attrib));p.set('id',str(identifier))
        run=etree.SubElement(p,HP+'run',attrib=dict(flow_template.find(HP+'run').attrib))
        etree.SubElement(run,HP+'t').text=''
        _set_paragraph_element_lineseg(p,600,width=xs[col+1]-xs[col],spacing_ratio=0)
        target.find(HP+'subList').append(p)
        target.find(HP+'cellMargin').set('bottom',str(ys[row+1]-ys[row]-600-200))
    for picture, image, (row,col) in zip(pictures, images, topology['image_cells']):
        target = cell(row, col, 1)
        box = _rect(image['bbox_pt'])
        width, height = round(box.width*scale), round(box.height*scale)
        left, top = round((box.x0-xcuts[col])*scale), round((box.y0-cuts[row])*scale)
        bottom = ys[row+1]-ys[row]-top-height-400-200
        right = xs[col+1]-xs[col]-left-width
        if min(left,top,right,bottom) < 0: return 0
        target.find(HP+'cellMargin').attrib.update(dict(zip(('left','top','right','bottom'),map(str,(left,top,right,bottom)))))
        identifier += 1
        p = etree.Element(HP+'p', attrib=dict(flow_template.attrib)); p.set('id',str(identifier))
        run = etree.SubElement(p,HP+'run',attrib=dict(flow_template.find(HP+'run').attrib)); run.append(picture)
        set_picture_display_size(picture,width,height)
        picture.find(HP+'pos').attrib.update({'treatAsChar':'1','horzOffset':'0','vertOffset':'0','affectLSpacing':'0'})
        picture.find(HP+'outMargin').attrib.update({edge:'0' for edge in ('left','right','top','bottom')})
        _set_paragraph_element_lineseg(p,height,width=width,spacing_ratio=0)
        target.find(HP+'subList').append(p)
    # No source or native validation below this point can reject the staged
    # structure. Allocate callback styles before independent spacing styles.
    flow_style = para_style(root.get('paraPrIDRef','0'),'LEFT',700,700)
    from .pdf_native_typography import _font_name
    for p, source, size, indent, gap, step in planned:
        p.set('paraPrIDRef',para_style(p.get('paraPrIDRef','0'),'LEFT',step,size,0,indent,0))
        dominant = max((s for r in source for s in r['spans']),key=lambda s:len(_compact(s['text'])))
        meta = layout['source_typography']
        for run in p.findall(HP+'run'):
            run.set('charPrIDRef',char_style(run.get('charPrIDRef','0'),size,_font_name(dominant['font']),
                round(float(meta.get('letter_spacing_percent') or 0)),round(float(meta.get('font_width_percent') or 100)),
                bool(int(dominant.get('flags') or 0)&16),italic=bool(int(dominant.get('flags') or 0)&2)))
        restore_source_run_styles(p,{**layout,'source_typography':{**meta,'lines':source}},page_width,char_style)
    for row in rows:
        row[:] = sorted(row, key=lambda c: int(c.find(HP+'cellAddr').get('colAddr')))
    for p, source, size, indent, gap, step in planned:
        set_space_after(p,header,gap)
    for row in rows:
        for target in row:
            addr, span = target.find(HP+'cellAddr'), target.find(HP+'cellSpan')
            r,c,s = int(addr.get('rowAddr')),int(addr.get('colAddr')),int(span.get('colSpan'))
            target.set('borderFillIDRef',_border_fill(header,original.get('borderFillIDRef'),left=c==0,right=c+s==3,top=r==0,bottom=r==4))
            for p in target.findall(HP+'subList/'+HP+'p'):
                if p.find(HP+'run/'+HP+'pic') is not None or not any((t.text or '').strip() for t in p.iter(HP+'t')):
                    p.set('paraPrIDRef',flow_style)
    for old in table.findall(HP+'tr'):table.remove(old)
    table.extend(rows); table.set('rowCnt','5'); table.set('colCnt','3')
    table.find(HP+'sz').attrib.update({'width':str(xs[-1]),'height':str(ys[-1])})
    table.find(HP+'pos').attrib.update({'treatAsChar':'0','affectLSpacing':'0','flowWithText':'1','allowOverlap':'0',
        'vertRelTo':'PARA','horzRelTo':'COLUMN','vertAlign':'TOP','horzAlign':'LEFT','vertOffset':'0','horzOffset':str(offset)})
    staged.set('paraPrIDRef',flow_style)
    _set_paragraph_element_lineseg(staged,ys[-1],width=round(column_width),spacing_ratio=0)
    root.attrib.clear(); root.attrib.update(staged.attrib)
    for child in list(root): root.remove(child)
    root.extend(staged)
    return len(planned)


def source_flow_dialogue_frame_table(table, root, header, hrefs, package, source):
    """Re-prove rules, all prose, native geometry and actual avatar pixels.

    Output names and producer flags are deliberately ignored. A consumer must
    find the original source rectangle and reproduce its semantic turn/list
    boundaries, measured cache origins and all three embedded picture crops.
    """
    from .pdf_layout_writer import _iter_text_lines, _item_bbox, _line_text
    from .pdf_native_content import _source_prose_frame, _source_typography
    from .pdf_illustrated_prose_frames import _illustrated_cell_cache_fits
    from .pdf_source_image_validation import render_source_crop, compare_source_crop
    from .pdf_picture_geometry import has_complete_picture_crop
    from .pdf_source_backgrounds import native_background_assets
    from hwpx.tools.paragraph_spacing import paragraph_indentation, paragraph_spacing, line_left_margin
    from .pdf_native_typography import _flow_height
    pos, size = table.find(HP+'pos'), table.find(HP+'sz')
    cells = table.findall(HP+'tr/'+HP+'tc')
    pictures = table.findall('.//'+HP+'pic')
    if (pos is None or size is None or len(cells) != 10 or len(pictures) != 3
        or table.get('rowCnt') != '5' or table.get('colCnt') != '3'
        or table.get('lock') == '1' or table.get('textWrap') != 'TOP_AND_BOTTOM'
        or any(table.find('.//'+HP+tag) is not None for tag in ('tbl','rect','equation'))
        or any(pos.get(k) != v for k,v in (('treatAsChar','0'),('vertRelTo','PARA'),
            ('horzRelTo','COLUMN'),('vertOffset','0'),('flowWithText','1'),('allowOverlap','0'),
            ('horzAlign','LEFT'),('vertAlign','TOP')))):
        return False
    def number(node,key):
        value = float(node.get(key))
        if not math.isfinite(value):raise ValueError('non-finite native dialogue')
        return value
    try:
        native = _compact(''.join(t.text or '' for t in table.iter(HP+'t')))
        page_pr = root.find('.//'+HP+'pagePr'); margin = page_pr.find(HP+'margin')
        columns = next(c for c in root.iter(HP+'colPr') if c.get('colCount') == '2')
        page_width = number(page_pr,'width')
        left, gap = number(margin,'left'), number(columns,'sameGap')
        column_width = (page_width-left-number(margin,'right')-gap)/2
        offset, width, height = number(pos,'horzOffset'),number(size,'width'),number(size,'height')
        if not native or min(width,height) <= 0 or offset < 0 or offset+width > column_width+2:
            return False
        styles = {p.get('id'):p for p in header.iter(HH+'paraPr')}
        fills = {f.get('id'):f for f in header.iter(HH+'borderFill')}
        with fitz.open(source) as document:
            for page in document:
                scale = page_width/page.rect.width
                drawings = page.get_drawings()
                horizontals = []
                for drawing in drawings:
                    for part in drawing.get('items',[]):
                        if part[0] == 'l' and abs(part[1].y-part[2].y) < .5:
                            horizontals.append((min(part[1].x,part[2].x),part[1].y,max(part[1].x,part[2].x)))
                        elif part[0] == 're':
                            box=fitz.Rect(part[1]); horizontals.extend(((box.x0,box.y0,box.x1),(box.x0,box.y1,box.x1)))
                for origin in (left,left+column_width+gap):
                    for x0,y0,x1 in horizontals:
                        if abs(x0*scale-origin-offset)>2 or abs((x1-x0)*scale-width)>2:
                            continue
                        frame = _source_prose_frame(fitz.Rect(x0,y0,x1,y0+height/scale),drawings)
                        if frame is None or abs(frame.height*scale-height)>2:
                            continue
                        lines = sorted((line for line in _iter_text_lines(page) if frame.contains(_item_bbox(line)) and _compact(_line_text(line))),
                                       key=lambda l:(_item_bbox(l).y0,_item_bbox(l).x0))
                        if ''.join(_compact(_line_text(line)) for line in lines) != native:
                            continue
                        records = _source_typography(lines,{'rect':frame})['lines']
                        font_size = median(r['font_size_pt'] for r in records)
                        source_pictures = sorted(({'bbox':fitz.Rect(i['bbox'])} for i in page.get_image_info(xrefs=True)
                            if frame.contains(fitz.Rect(i['bbox'])) and font_size <= min(fitz.Rect(i['bbox']).width,fitz.Rect(i['bbox']).height)
                            and max(fitz.Rect(i['bbox']).width,fitz.Rect(i['bbox']).height) <= font_size*4),
                            key=lambda i:(i['bbox'].y0,i['bbox'].x0))
                        images = _source_avatar_proof(page,source_pictures)
                        topology = dialogue_topology(frame,records,images) if images is not None else None
                        if topology is None:
                            continue
                        if not _prove_native_dialogue(table,frame,records,images,topology,scale,styles,fills,
                            hrefs,package,source,page.number,number,paragraph_indentation,paragraph_spacing,
                            line_left_margin,_flow_height,_illustrated_cell_cache_fits,has_complete_picture_crop,
                            render_source_crop,compare_source_crop):
                            continue
                        # Optional decorative fills may contain original image
                        # objects only, never source PDF prose or a page raster.
                        assets = native_background_assets(table,header,hrefs,package)
                        from .pdf_source_page_memo import source_text_dict
                        bitmaps = [b for b in source_text_dict(page)['blocks'] if b.get('type') == 1
                            and frame.contains(fitz.Rect(b['bbox']))
                            and not any(_same(b['bbox'],i['bbox_pt'],.01) for i in images)]
                        if bitmaps or assets:
                            if len(assets) != 1 or not bitmaps:
                                continue
                            expected = _compose_dialogue_background(page,frame,bitmaps)
                            if not compare_source_crop(expected,assets[0][1])['ok']:
                                continue
                        return True
    except (ValueError,TypeError,AttributeError,KeyError,IndexError,StopIteration,OSError):
        return False
    return False


def _prove_native_dialogue(table,frame,records,images,topology,scale,styles,fills,hrefs,package,source,page,
    number,indentation,spacing,line_left,flow_height,cache_fits,complete_crop,source_crop,compare_crop):
    cuts, xcuts = topology['row_y_pt'],topology['column_x_pt']
    expected = {(row,col):span for row,col,span in topology['text_cells']}
    expected.update({pair:1 for pair in topology['image_cells']})
    expected.update({pair:1 for pair in topology['empty_cells']})
    cells = {}
    for cell in table.findall(HP+'tr/'+HP+'tc'):
        addr, span = cell.find(HP+'cellAddr'),cell.find(HP+'cellSpan')
        values = [number(addr,'rowAddr'),number(addr,'colAddr'),number(span,'colSpan'),number(span,'rowSpan')]
        if any(value != round(value) for value in values):return False
        row,col,cs,rs = map(int,values)
        if (row,col) in cells or expected.get((row,col)) != cs or rs != 1:
            return False
        cells[row,col] = cell
        if (cell.get('hasMargin') != '1' or cell.get('protect') == '1'
            or abs(number(cell.find(HP+'cellSz'),'width')-(xcuts[col+cs]-xcuts[col])*scale)>2
            or abs(number(cell.find(HP+'cellSz'),'height')-(cuts[row+1]-cuts[row])*scale)>2
            or not cache_fits(cell,styles)):
            return False
        fill = fills.get(cell.get('borderFillIDRef'))
        if fill is None or fill.find('.//'+HC+'imgBrush') is not None:
            return False
        for edge,visible in zip(('left','right','top','bottom'),(col==0,col+cs==3,row==0,row==4)):
            if fill.find(HH+edge+'Border').get('type') != ('SOLID' if visible else 'NONE'):
                return False
    if cells.keys() != expected.keys():return False
    for pair in topology['empty_cells']:
        cell=cells[pair];paragraphs=cell.findall(HP+'subList/'+HP+'p')
        if len(paragraphs)!=1:return False
        paragraph=paragraphs[0]
        children=[child for run in paragraph.findall(HP+'run') for child in run]
        lines=paragraph.findall(HP+'linesegarray/'+HP+'lineseg')
        if (len(children)!=1 or children[0].tag!=HP+'t' or len(children[0]) or children[0].text
            or len(lines)!=1 or any(number(lines[0],key) for key in ('textpos','vertpos','horzpos','spacing'))
            or any(indentation(paragraph,styles)) or any(spacing(paragraph,styles))):return False
    for band,(row,col,_) in enumerate(topology['text_cells']):
        cell = cells[row,col]; margin = cell.find(HP+'cellMargin')
        paragraphs = cell.findall(HP+'subList/'+HP+'p')
        groups = [[records[i] for i in g] for g in topology['groups'][band]]
        if len(paragraphs) != len(groups) or cell.find('.//'+HP+'pic') is not None:
            return False
        accumulated = number(margin,'top')
        for p,group in zip(paragraphs,groups):
            children = [child for run in p.findall(HP+'run') for child in run]
            if not children or any(child.tag != HP+'t' or len(child) for child in children):
                return False
            text = ''.join(t.text or '' for t in children)
            if _compact(text) != ''.join(_compact(r['text']) for r in group):return False
            lines = p.findall(HP+'linesegarray/'+HP+'lineseg')
            if len(lines) != len(group):return False
            initial = number(lines[0],'vertpos')
            # Native save normalizes a cell's paragraph caches to a shared
            # cell origin. A fresh paragraph cache starts at zero instead.
            # Both must describe the same measured paragraph flow.
            if min(abs(initial),abs(initial-accumulated+number(margin,'top'))) > 2:return False
            left,right,intent = indentation(p,styles)
            if any(not math.isfinite(v) for v in (left,right,intent)) or left or right:return False
            positions=[]; units=0
            for char in text:
                if not char.isspace():positions.append(units)
                units+=len(char.encode('utf-16-le'))//2
            cursor=0
            for index,(line,record) in enumerate(zip(lines,group)):
                if number(line,'textpos') != (0 if not index else positions[cursor]):return False
                actual_x=(xcuts[col]-frame.x0)*scale+number(margin,'left')+line_left(left,intent,index)+number(line,'horzpos')
                actual_y=(cuts[row]-frame.y0)*scale+accumulated+number(line,'vertpos')-initial+number(line,'baseline')
                if (abs(actual_x-(record['bbox_pt'][0]-frame.x0)*scale)>3
                    or abs(actual_y-(record['baseline_pt']-frame.y0)*scale)>3):return False
                cursor+=len(_compact(record['text']))
            accumulated+=flow_height(p)+sum(spacing(p,styles))
    for image,(row,col) in zip(images,topology['image_cells']):
        cell=cells[row,col];pictures=cell.findall('.//'+HP+'pic')
        if len(pictures)!=1 or any((t.text or '').strip() for t in cell.iter(HP+'t')):return False
        picture=pictures[0];box=fitz.Rect(image['bbox_pt']);pos=picture.find(HP+'pos');size=picture.find(HP+'sz')
        paragraphs=cell.findall(HP+'subList/'+HP+'p')
        if len(paragraphs)!=1 or picture.getparent().getparent() is not paragraphs[0]:return False
        owner=paragraphs[0]
        children=[child for run in owner.findall(HP+'run') for child in run]
        cache=owner.findall(HP+'linesegarray/'+HP+'lineseg')
        if (children != [picture] or len(cache)!=1 or number(cache[0],'textpos')
            or number(cache[0],'vertpos') or number(cache[0],'horzpos')
            or abs(number(cache[0],'vertsize')-box.height*scale)>2
            or abs(number(cache[0],'textheight')-box.height*scale)>2
            or number(cache[0],'spacing')):return False
        margin=cell.find(HP+'cellMargin')
        if (pos.get('treatAsChar')!='1' or number(pos,'horzOffset') or number(pos,'vertOffset')
            or any(number(picture.find(HP+'outMargin'),edge) for edge in ('left','right','top','bottom'))
            or abs(number(size,'width')-box.width*scale)>2 or abs(number(size,'height')-box.height*scale)>2
            or abs((xcuts[col]-frame.x0)*scale+number(margin,'left')-(box.x0-frame.x0)*scale)>2
            or abs((cuts[row]-frame.y0)*scale+number(margin,'top')-(box.y0-frame.y0)*scale)>2):return False
        if any(abs(v)>2 for v in indentation(owner,styles)) or any(spacing(owner,styles)):return False
        ref=picture.find(HC+'img');href=hrefs.get(ref.get('binaryItemIDRef'))
        if href not in package.namelist():return False
        payload=package.read(href)
        if not complete_crop(picture,payload) or not compare_crop(source_crop(source,page,box),payload)['ok']:return False
    return True
