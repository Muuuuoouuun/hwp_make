"""Source-proved whole prose frames with one paragraph-owned side picture."""
from copy import deepcopy
import math
import re
from statistics import median

import fitz
from lxml import etree

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HH = '{http://www.hancom.co.kr/hwpml/2011/head}'
HC = '{http://www.hancom.co.kr/hwpml/2011/core}'
WRAPPED_CELL = 'source-prose-frame:wrapped:v1'


def _rect(value):
    if len(value) != 4 or not all(math.isfinite(float(v)) for v in value):
        raise ValueError('invalid source rectangle')
    box = fitz.Rect(value)
    if box.is_empty or box.is_infinite:
        raise ValueError('empty source rectangle')
    return box


def _compact(value):
    from .pdf_layout_writer import _pdf_output_text
    return re.sub(r'\s+', '', _pdf_output_text(value))


def wrapped_frame_topology(frame, records, images):
    """Identify a real line crossing a side image without crossing its ink."""
    try:
        frame = _rect(list(frame))
        if len(images) != 1 or len(records) < 4:
            return None
        image = _rect(images[0]['bbox_pt'])
        size = median(float(r['font_size_pt']) for r in records)
        if not math.isfinite(size) or size <= 0 or not frame.contains(image) or image.height < size*2:
            return None
        boxes = [_rect(r['bbox_pt']) for r in records]
        beside = [b for b in boxes if min(b.y1, image.y1) > max(b.y0, image.y0)]
        crossing = [i for i, b in enumerate(boxes) if b.y0 < image.y0 < b.y1]
        if (len(crossing) != 1 or crossing[0] < 2 or not beside
            or any(b.x1 > image.x0+.1 for b in beside)
            or min(image.x0-frame.x0, frame.x1-image.x0) < size*3
            or any(not frame.contains(b) for b in boxes)):
            return None
        return {'mode':'paragraph_wrap', 'side':'right', 'crossing_line':crossing[0],
                'primary_image_index':0, 'wrapped_image_index':None,
                'split_x_pt':image.x0, 'row_y_pt':[frame.y0,frame.y1]}
    except (ValueError, TypeError, KeyError, IndexError):
        return None


def source_wrapped_groups(lines):
    """Use actual notice bullets/fields, keeping printed continuations intact."""
    from .pdf_native_content import _semantic_line_groups
    from .pdf_layout_writer import _line_text, _item_bbox
    texts = [_line_text(line).strip() for line in lines]
    labels = [i for i, text in enumerate(texts) if re.match(r'^[A-Za-z][A-Za-z &]{1,35}:\s*\S', text)]
    rail = min(_item_bbox(line).x0 for line in lines)
    if (len(labels) < 2 or any(abs(_item_bbox(lines[i]).x0-rail) > .1 for i in labels)):
        return _semantic_line_groups(lines, framed_callout=True)
    cuts = {0, len(lines), *labels}
    for i, text in enumerate(texts):
        if re.match(r'^[∙•●]\s', text): cuts.add(i)
        if (i and re.fullmatch(r'[A-Z][A-Za-z &]{2,32}', text)
            and abs(_item_bbox(lines[i]).x0-rail) < .1): cuts.add(i)
    groups = []
    for start, end in zip(sorted(cuts), sorted(cuts)[1:]):
        segment = lines[start:end]
        if start in labels and len(segment) > 1:
            first = lines[start]
            chars = [c for s in first.get('spans', []) for c in s.get('chars', [])]
            raw = ''.join(c.get('c','') for c in chars)
            colon = raw.find(':')
            value = next((c for c in chars[colon+1:] if not c.get('c','').isspace()), None)
            continuation = _item_bbox(segment[1])
            font_size=median(float(s.get('size') or 0) for s in first.get('spans',[]))
            if (value is not None and abs(value['origin'][0]-continuation.x0) < font_size*.25
                and all(abs(_item_bbox(line).x0-continuation.x0) < .2 for line in segment[1:])):
                groups.append(segment)
                continue
        groups.extend(_semantic_line_groups(segment, framed_callout=True))
    return groups


def _source_proof(layout):
    """Reopen the actual PDF; producer flags cannot establish a complete frame."""
    from .pdf_native_content import _source_prose_frame
    try:
        geometry, = layout.get('native_tables') or []
        if (not layout.get('source_literal_text') or not geometry.get('source_prose_frame')
            or layout.get('source_answer_blanks')): return None
        frame = _rect(geometry['bbox_pt'])
        records = layout['source_typography']['lines']
        topology = wrapped_frame_topology(frame, records, geometry.get('images') or [])
        if topology is None: return None
        with fitz.open(geometry['source_pdf_path']) as pdf:
            page = pdf[int(geometry['source_page_index'])]
            actual = _source_prose_frame(frame, page.get_drawings())
            if actual is None or max(abs(a-b) for a,b in zip(actual, frame)) > .1: return None
            rows = sorted([line for block in page.get_text('rawdict')['blocks'] for line in block.get('lines', [])
                           if frame.contains(_rect(line['bbox']))], key=lambda r:(r['bbox'][1],r['bbox'][0]))
            if len(rows) != len(records): return None
            picture = _rect(geometry['images'][0]['bbox_pt'])
            for raw, record in zip(rows, records):
                chars = [c for s in raw['spans'] for c in s['chars']]
                baseline,size=float(record['baseline_pt']),float(record['font_size_pt'])
                if (_compact(''.join(c['c'] for c in chars)) != _compact(record['text'])
                    or max(abs(a-b) for a,b in zip(raw['bbox'], record['bbox_pt'])) > .1
                    or not all(math.isfinite(v) for v in (baseline,size))
                    or abs(baseline-raw['spans'][0]['origin'][1])>.001
                    or abs(size-median(s['size'] for s in raw['spans']))>.001
                    or any((_rect(c['bbox']) & picture).get_area() > .1 for c in chars if not c['c'].isspace())
                    or any('hancomeq' in s.get('font','').lower() for s in raw['spans'])): return None
            images = [b for b in page.get_text('dict')['blocks'] if b.get('type') == 1 and frame.contains(_rect(b['bbox']))]
            if len(images) != 1 or max(abs(a-b) for a,b in zip(images[0]['bbox'], picture)) > .1: return None
            from . import storage
            from .pdf_source_image_validation import render_source_crop,compare_source_crop
            if not compare_source_crop(render_source_crop(geometry['source_pdf_path'],int(geometry['source_page_index']),picture),
                                       storage.resolve_data_image_path(geometry['images'][0]['path']).read_bytes())['ok']: return None
            left, right = float(layout['column_left_pt']), float(layout['column_right_pt'])
            if not all(math.isfinite(v) for v in (left,right)) or not left <= frame.x0 < frame.x1 <= right: return None
            # Other-column ink cannot be concealed by a larger question owner.
            for block in page.get_text('rawdict')['blocks']:
                for row in block.get('lines', []):
                    box = _rect(row['bbox'])
                    if min(box.y1,frame.y1) > max(box.y0,frame.y0) and box.x0 < left and box.x1 > frame.x0: return None
            return geometry, frame, records, picture, page.rect.width
    except (ValueError, TypeError, AttributeError, KeyError, IndexError, StopIteration, OSError, OverflowError,
            fitz.FileNotFoundError, fitz.FileDataError, fitz.EmptyFileError):
        return None


def measured_wrapped_frame_width(root, layout, page_width, column_width):
    """Measure a complete source frame's own end, without widening a column."""
    try:
        return _measured_wrapped_frame_width(root, layout, page_width, column_width)
    except (AttributeError, ValueError, TypeError, KeyError, IndexError, StopIteration, OverflowError):
        return None


def _measured_wrapped_frame_width(root, layout, page_width, column_width):
    proof = _source_proof(layout)
    if proof is None: return None
    geometry, frame, records, picture, source_width = proof
    if _compact(''.join(t.text or '' for t in root.iter(HP+'t'))) != _compact(geometry['source_frame_text']): return None
    if not all(math.isfinite(v) and v > 0 for v in (page_width,column_width,source_width)): return None
    document = root.getroottree().getroot()
    page = document.find('.//'+HP+'pagePr')
    margins = page.find(HP+'margin')
    columns = next(c for c in document.iter(HP+'colPr') if c.get('colCount') == '2')
    gap, left = float(columns.get('sameGap')), float(margins.get('left'))
    if not all(math.isfinite(v) and v >= 0 for v in (gap,left)): return None
    if layout.get('source_column') not in (1,2): return None
    origin = left+(column_width+gap)*(int(layout['source_column'])-1)
    scale = page_width/source_width
    offset = round(frame.x0*scale-origin)
    required = offset+round(frame.width*scale)
    if offset < 0 or origin+required > page_width or frame.x1 >= source_width: return None
    return max(column_width, required)


def restore_wrapped_frame(root, layout, header, page_width, column_width, pictures, *, char_style=None):
    """Keep all prose and one side picture in a single normal flowing cell."""
    try:
        if (not all(math.isfinite(v) and v > 0 for v in (page_width,column_width))
            or measured_wrapped_frame_width(root,layout,page_width,column_width) is None): return False
        section=root.getroottree().getroot()
        index=list(section.iter()).index(root)
        staged_section=deepcopy(section)
        staged_root=list(staged_section.iter())[index]
        staged_header=deepcopy(header)
        properties=header.find('.//'+HH+'paraProperties')
        staged_properties=staged_header.find('.//'+HH+'paraProperties')
        original=[etree.tostring(p) for p in properties]
        before_text=''.join(t.text or '' for t in root.iter(HP+'t'))
        if not _restore_wrapped_frame(staged_root,layout,staged_header,page_width,column_width,deepcopy(pictures)): return False
        if ([etree.tostring(p) for p in list(staged_properties)[:len(original)]] != original
            or ''.join(t.text or '' for t in staged_root.iter(HP+'t')) != before_text): return False
        from hwpx.tools.paragraph_floats import wrapped_cell_layout
        cell=staged_root.find(HP+'run/'+HP+'tbl/'+HP+'tr/'+HP+'tc')
        styles={p.get('id'):p for p in staged_header.iter(HH+'paraPr')}
        if wrapped_cell_layout(cell,styles) is None: return False
        # Append only; callers retain references to the existing style nodes.
        properties.extend(list(staged_properties)[len(original):])
        properties.set('itemCnt',str(len(properties)))
        root.attrib.clear();root.attrib.update(staged_root.attrib)
        for child in list(root): root.remove(child)
        root.extend(staged_root)
        if char_style is not None:
            # The style allocator belongs to the real header. Call it only
            # after the complete native/source proof has committed, with the
            # source-owned picture temporarily detached from its same run.
            picture=root.find('.//'+HP+'pic')
            owner=picture.getparent();position=owner.index(picture)
            owner.remove(picture)
            try:
                from .pdf_source_run_styles import restore_source_run_styles
                heights={s.get('id'):float(s.get('height')) for s in header.iter(HH+'charPr')}
                def metrics_style(base_id,_source_height,*args,**kwargs):
                    # This complete-frame repair restores horizontal metrics.
                    # Keep each existing semantic paragraph's measured cache
                    # height; mixed source sizes otherwise change cell flow.
                    return char_style(base_id,heights[base_id],*args,**kwargs)
                restore_source_run_styles(root,layout,page_width,metrics_style)
            finally:
                owner.insert(position,picture)
        return True
    except (AttributeError, ValueError, TypeError, KeyError, IndexError, StopIteration, OverflowError, ZeroDivisionError):
        return False


def _restore_wrapped_frame(root, layout, header, page_width, column_width, pictures):
    from .pdf_picture_geometry import set_picture_display_size
    from .pdf_source_spacing import set_space_before, set_space_after
    from .hwpx_writer_v2 import _set_paragraph_element_lineseg
    from hwpx.tools.paragraph_spacing import paragraph_spacing, paragraph_indentation, line_left_margin
    proof = _source_proof(layout)
    if proof is None or len(pictures) != 1: return False
    geometry, frame, records, picture_box, source_width = proof
    scale = page_width/source_width
    table = root.find(HP+'run/'+HP+'tbl')
    cell = table.find(HP+'tr/'+HP+'tc')
    groups, cursor = [], 0
    for p in cell.findall(HP+'subList/'+HP+'p'):
        value = _compact(''.join(t.text or '' for t in p.iter(HP+'t')))
        start, text = cursor, ''
        while cursor < len(records) and len(text) < len(value):
            text += _compact(records[cursor]['text']); cursor += 1
        rows = records[start:cursor]
        cache = p.findall(HP+'linesegarray/'+HP+'lineseg')
        if not value or text != value or len(cache) != len(rows): return False
        groups.append((p, rows))
    if cursor != len(records): return False
    owners = [(p,rows) for p,rows in groups if rows[0]['bbox_pt'][1] < picture_box.y0 < rows[-1]['bbox_pt'][3]]
    if len(owners) != 1 or len(owners[0][1]) < 2: return False
    margin = cell.find(HP+'cellMargin')
    rail = min(r['bbox_pt'][0] for r in records)
    text_left = round((rail-frame.x0)*scale)
    width, height = round(frame.width*scale), round(frame.height*scale)
    usable = width-text_left-float(margin.get('right'))
    styles = {s.get('id'):s for s in header.iter(HH+'paraPr')}
    properties = header.find('.//'+HH+'paraProperties')
    # Reapply first-ink evidence after callbacks have allocated every style.
    for i,(p,rows) in enumerate(groups):
        cache = p.findall(HP+'linesegarray/'+HP+'lineseg')
        initial = float(cache[0].get('vertpos'))
        for line in cache: line.set('vertpos',str(round(float(line.get('vertpos'))-initial)))
        cache[-1].set('spacing','0')
        source_left = min(r['bbox_pt'][0] for r in rows)
        left = round((source_left-rail)*scale)
        indent = round((rows[0]['bbox_pt'][0]-rows[1]['bbox_pt'][0])*scale) if len(rows)>1 else 0
        # Negative intent follows the native hanging-indent convention.
        if indent < 0: left = round((rows[0]['bbox_pt'][0]-rail)*scale)
        centered = (len(rows)==1 and source_left-rail > rows[0]['font_size_pt']
                    and abs((rows[0]['bbox_pt'][0]+rows[0]['bbox_pt'][2]-frame.x0-frame.x1)/2) < rows[0]['font_size_pt']*.5)
        style = deepcopy(styles[p.get('paraPrIDRef')])
        style.set('id',str(max(int(s.get('id')) for s in properties)+1))
        if centered: style.find(HH+'align').set('horizontal','CENTER'); left=indent=0
        from .pdf_source_justification import source_justification
        justification=source_justification(layout,rows,available_width_hwp=usable,
                                            source_left_pt=rail,page_width_hwp=page_width)
        if justification is not None:
            style.find(HH+'align').set('horizontal',justification['alignment'])
        for m in style.findall('.//'+HH+'margin'):
            m.find(HC+'left').set('value',str(left)); m.find(HC+'intent').set('value',str(indent))
            if justification is not None:
                m.find(HC+'right').set('value',str(justification['right_hwp']))
            if centered:
                # Center in the actual source frame despite asymmetric cell margins.
                m.find(HC+'right').set('value',str(round(text_left-float(margin.get('right'))
                    -(rows[0]['bbox_pt'][0]+rows[0]['bbox_pt'][2]-frame.x0-frame.x1)*scale)))
        properties.append(style); p.set('paraPrIDRef',style.get('id'))
        styles[style.get('id')] = style
        margin_left,margin_right,native_indent=paragraph_indentation(p,styles)
        for line_index,(line,row) in enumerate(zip(cache,rows)):
            available=usable
            if min(row['bbox_pt'][3],picture_box.y1) > max(row['bbox_pt'][1],picture_box.y0):
                available=(picture_box.x0-frame.x0)*scale-text_left
            effective=available-line_left_margin(margin_left,native_indent,line_index)-margin_right
            if effective<=0: return False
            line.set('horzpos','0'); line.set('horzsize',str(round(effective)))
        occupied=sum(float(l.get('vertsize'))+float(l.get('spacing')) for l in cache)
        top=rows[0]['baseline_pt']*scale-float(cache[0].get('baseline'))
        gap=0
        if i+1<len(groups):
            np,nr=groups[i+1]; nc=np.find(HP+'linesegarray/'+HP+'lineseg')
            gap=nr[0]['baseline_pt']*scale-float(nc.get('baseline'))-top-occupied
        if gap < -2: return False
        set_space_before(p,header,0); set_space_after(p,header,max(0,gap))
        styles.update({s.get('id'):s for s in properties})
    owner,own_rows = owners[0]
    picture=pictures[0]
    set_picture_display_size(picture,picture_box.width*scale,picture_box.height*scale)
    owner_top=own_rows[0]['baseline_pt']*scale-float(owner.find(HP+'linesegarray/'+HP+'lineseg').get('baseline'))
    picture.set('textWrap','SQUARE'); picture.set('textFlow','BOTH_SIDES')
    picture.find(HP+'pos').attrib.update({'treatAsChar':'0','flowWithText':'1','allowOverlap':'0','affectLSpacing':'0',
        'vertRelTo':'PARA','horzRelTo':'COLUMN','vertAlign':'TOP','horzAlign':'LEFT',
        'horzOffset':str(round((picture_box.x0-frame.x0)*scale-text_left)),
        'vertOffset':str(round(picture_box.y0*scale-owner_top))})
    for edge in ('left','right','top','bottom'): picture.find(HP+'outMargin').set(edge,'0')
    run=etree.Element(HP+'run',charPrIDRef=owner.find(HP+'run').get('charPrIDRef')); run.append(picture); owner.insert(0,run)
    for line in owner.findall(HP+'linesegarray/'+HP+'lineseg')[1:]: line.set('textpos',str(int(line.get('textpos'))+8))
    table.find(HP+'sz').attrib.update({'width':str(width),'height':str(height)})
    cell.find(HP+'cellSz').attrib.update({'width':str(width),'height':str(height)})
    cell.set('name',WRAPPED_CELL)
    margin.set('left',str(text_left))
    content=sum(sum(float(l.get('vertsize'))+float(l.get('spacing')) for l in p.findall(HP+'linesegarray/'+HP+'lineseg'))
                +sum(paragraph_spacing(p,styles)) for p,_ in groups)
    margin.set('bottom',str(round(height-float(margin.get('top'))-content)))
    document=root.getroottree().getroot(); page=document.find('.//'+HP+'pagePr'); pm=page.find(HP+'margin')
    col=next(c for c in document.iter(HP+'colPr') if c.get('colCount')=='2')
    origin=float(pm.get('left'))+(column_width+float(col.get('sameGap')))*(int(layout['source_column'])-1)
    table.find(HP+'pos').attrib.update({'treatAsChar':'0','flowWithText':'1','allowOverlap':'0','affectLSpacing':'0',
        'vertRelTo':'PARA','horzRelTo':'COLUMN','vertAlign':'TOP','horzAlign':'LEFT','vertOffset':'0',
        'horzOffset':str(round(frame.x0*scale-origin))})
    _set_paragraph_element_lineseg(root,height,width=round(column_width),spacing_ratio=0)
    properties.set('itemCnt',str(len(properties)))
    return True


def finalize_wrapped_frame(root, layout, header, page_width):
    """Remove duplicated fitter padding only when every actual cache fits."""
    proof=_source_proof(layout)
    if proof is None: return False
    table=root.find(HP+'run/'+HP+'tbl')
    if table is None: return False
    cell=table.find(HP+'tr/'+HP+'tc')
    if cell is None or cell.get('name') != WRAPPED_CELL: return False
    from hwpx.tools.paragraph_floats import wrapped_cell_layout
    styles={s.get('id'):s for s in header.iter(HH+'paraPr')}
    measured=wrapped_cell_layout(cell,styles)
    height=round(proof[1].height*page_width/proof[-1])
    if measured is None or measured['height'] > height+2: return False
    table.find(HP+'sz').set('height',str(height)); cell.find(HP+'cellSz').set('height',str(height))
    from .hwpx_writer_v2 import _set_paragraph_element_lineseg
    _set_paragraph_element_lineseg(root,height,width=int(root.find(HP+'linesegarray/'+HP+'lineseg').get('horzsize')),spacing_ratio=0)
    return True


def question_wrapped_width(entries, page_width, width):
    """Use a proved complete frame's end only for its own question group."""
    required=width
    for paragraph,layout in entries:
        table=paragraph.find(HP+'run/'+HP+'tbl')
        if table is None: continue
        cell=table.find(HP+'tr/'+HP+'tc')
        if cell is None or cell.get('name') != WRAPPED_CELL: continue
        measured=measured_wrapped_frame_width(paragraph,layout,page_width,width)
        if measured is not None: required=max(required,measured)
    return int(round(required))


def source_flow_wrapped_prose_frame_table(table, root, header, hrefs, package, source):
    """Independently prove full native text, source rules, image and masks."""
    from .pdf_native_content import _source_prose_frame
    from .pdf_picture_geometry import has_complete_picture_crop
    from .pdf_source_image_validation import render_source_crop,compare_source_crop
    from hwpx.tools.paragraph_floats import wrapped_cell_layout,is_wrapped_picture,available_interval
    from hwpx.tools.paragraph_spacing import paragraph_indentation,line_left_margin
    from hwpx.tools.wrapped_cache_metrics import cached_line_texts
    try:
        cells=table.findall(HP+'tr/'+HP+'tc')
        if len(cells)!=1: return False
        cell=cells[0]
        # The source oracle below establishes provenance; cell.name is merely
        # a portable editing opt-in, never the source proof itself.
        styles={s.get('id'):s for s in header.iter(HH+'paraPr')}
        measured=wrapped_cell_layout(cell,styles)
        if measured is None: return False
        picture,=table.findall('.//'+HP+'pic')
        if not is_wrapped_picture(picture): return False
        text=_compact(''.join(t.text or '' for t in cell.iter(HP+'t')))
        page_pr=root.find('.//'+HP+'pagePr'); margin=page_pr.find(HP+'margin')
        columns=next(c for c in root.iter(HP+'colPr') if c.get('colCount')=='2')
        def number(node,key):
            value=float(node.get(key))
            if not math.isfinite(value): raise ValueError('nonfinite wrapped native geometry')
            return value
        page_width=number(page_pr,'width');left=number(margin,'left');gap=number(columns,'sameGap')
        column_width=(page_width-left-number(margin,'right')-gap)/2
        pos=table.find(HP+'pos');size=table.find(HP+'sz')
        width,height,offset=number(size,'width'),number(size,'height'),number(pos,'horzOffset')
        if min(width,height)<=0 or offset<0: return False
        draw=next((a for a in table.iterancestors() if a.tag==HP+'drawText'),None)
        if draw is None or number(draw,'lastWidth')+2<offset+width: return False
        ref=picture.find(HC+'img');href=hrefs.get(ref.get('binaryItemIDRef'))
        if href not in package.namelist(): return False
        payload=package.read(href)
        if not has_complete_picture_crop(picture,payload): return False
        owner=picture.getparent().getparent()
        owner_index=measured['paragraphs'].index(owner)
        image_rect=measured['floats'][0]
        ml=number(cell.find(HP+'cellMargin'),'left')
        mt=number(cell.find(HP+'cellMargin'),'top')
        with fitz.open(source) as pdf:
            for page_index,page in enumerate(pdf):
                scale=page_width/page.rect.width
                for origin in (left,left+column_width+gap):
                    frame=fitz.Rect((origin+offset)/scale,0,(origin+offset+width)/scale,height/scale)
                    for drawing in page.get_drawings():
                        for part in drawing.get('items',[]):
                            if part[0]=='l' and abs(part[1].y-part[2].y)<.1:
                                x0,x1=sorted((part[1].x,part[2].x)); y=part[1].y
                            elif part[0]=='re': x0,y,x1,_=part[1]
                            else: continue
                            if abs(x0-frame.x0)*scale>2 or abs(x1-frame.x1)*scale>2: continue
                            actual=_source_prose_frame(fitz.Rect(x0,y,x1,y+height/scale),page.get_drawings())
                            if actual is None or abs(actual.height*scale-height)>2: continue
                            rows=sorted([line for block in page.get_text('rawdict')['blocks'] for line in block.get('lines',[])
                                         if actual.contains(_rect(line['bbox']))],key=lambda r:(r['bbox'][1],r['bbox'][0]))
                            records=[{'text':''.join(c['c'] for s in r['spans'] for c in s['chars']),
                                      'bbox_pt':r['bbox'],'font_size_pt':median(s['size'] for s in r['spans']),
                                      'baseline_pt':r['spans'][0]['origin'][1]} for r in rows]
                            if ''.join(_compact(r['text']) for r in records)!=text: continue
                            images=[b for b in page.get_text('dict')['blocks'] if b.get('type')==1 and actual.contains(_rect(b['bbox']))]
                            if len(images)!=1 or wrapped_frame_topology(actual,records,[{'bbox_pt':images[0]['bbox']}]) is None: continue
                            image=_rect(images[0]['bbox'])
                            if not compare_source_crop(render_source_crop(source,page_index,image),payload)['ok']: continue
                            first_line=measured['paragraphs'][0].find(HP+'linesegarray/'+HP+'lineseg')
                            # Native font ascenders differ from PDF ink boxes.
                            # Compare the actual printed baseline relationship,
                            # using the first source/native line as the anchor.
                            source_top=records[0]['baseline_pt']*scale-mt-number(first_line,'baseline')
                            expected=[(image.x0-actual.x0)*scale-ml,image.y0*scale-source_top-mt,
                                      (image.x1-actual.x0)*scale-ml,image.y1*scale-source_top-mt]
                            if max(abs(a-b) for a,b in zip(image_rect,expected))>2: continue
                            cursor=0;valid=True
                            for p,start in zip(measured['paragraphs'],measured['starts']):
                                value=_compact(''.join(t.text or '' for t in p.findall(HP+'run/'+HP+'t')))
                                begin=cursor;matched=''
                                while cursor<len(records) and len(matched)<len(value):
                                    matched+=_compact(records[cursor]['text']);cursor+=1
                                lines=p.findall(HP+'linesegarray/'+HP+'lineseg')
                                slices=cached_line_texts(p)
                                if (value!=matched or len(lines)!=cursor-begin or slices is None
                                    or any(native.strip(' ')!=row['text'].strip(' ')
                                           for native,row in zip(slices,records[begin:cursor]))): valid=False;break
                                margin_left,margin_right,indent=paragraph_indentation(p,styles)
                                local=0
                                for line_index,(line,row) in enumerate(zip(lines,records[begin:cursor])):
                                    target=row['baseline_pt']*scale-source_top
                                    native=mt+start+local+number(line,'baseline')
                                    # Font height and line spacing round to
                                    # integer HWP units independently. Bound
                                    # that quantization by the proved group's
                                    # number of source lines, not a pixel fudge.
                                    if (abs(native-target)>1+len(lines)
                                        or abs(number(line,'vertpos')-start-local)>1): valid=False;break
                                    interval=available_interval(p,measured['width'],start+local,number(line,'vertsize'),exclusions=measured['floats'])
                                    effective=interval[1]-line_left_margin(margin_left,indent,line_index)-margin_right
                                    if abs(number(line,'horzpos')-interval[0])>2 or abs(number(line,'horzsize')-effective)>2: valid=False;break
                                    local+=number(line,'vertsize')+number(line,'spacing')
                                if not valid: break
                            if valid and cursor==len(records) and owner_index>0:
                                return True
    except (ValueError,TypeError,AttributeError,KeyError,IndexError,StopIteration,OSError,
            fitz.FileNotFoundError,fitz.FileDataError,fitz.EmptyFileError):
        pass
    return False


def seed_source_wrapped_flow(path,items):
    """Persist original caches only after an independent actual-PDF proof."""
    import zipfile
    from hwpx.tools.wrapped_flow_state import seed
    sources={str(g['source_pdf_path']) for item in items
             for g in (item.get('layout') or {}).get('native_tables',[])
             if g.get('source_pdf_path')}
    if not sources: return 0
    with zipfile.ZipFile(path) as package:
        infos=package.infolist();payloads={i.filename:package.read(i.filename) for i in infos}
        header=etree.fromstring(payloads['Contents/header.xml'])
        manifest=etree.fromstring(payloads['Contents/content.hpf'])
        hrefs={n.get('id'):n.get('href') for n in manifest.iter() if n.get('href')}
        paras={p.get('id'):p for p in header.iter(HH+'paraPr')}
        chars={p.get('id'):p for p in header.iter(HH+'charPr')}
        count=0
        for name,raw in list(payloads.items()):
            if not re.fullmatch(r'Contents/section\d+\.xml',name): continue
            root=etree.fromstring(raw);changed=False
            for cell in root.iter(HP+'tc'):
                if cell.get('name')!=WRAPPED_CELL: continue
                table=cell.getparent().getparent()
                if not any(source_flow_wrapped_prose_frame_table(table,root,header,hrefs,package,source) for source in sources): continue
                if seed(root,cell,paras,chars): count+=1;changed=True
            if changed: payloads[name]=etree.tostring(root,xml_declaration=True,encoding='utf-8',standalone=True)
    if count:
        with zipfile.ZipFile(path,'w') as output:
            for info in infos: output.writestr(info,payloads[info.filename])
    return count
