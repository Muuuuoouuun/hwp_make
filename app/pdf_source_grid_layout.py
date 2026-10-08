"""Restore simple ruled grids from actual source cells and native content."""
from __future__ import annotations

from copy import deepcopy
import io
import math
from statistics import median

import fitz
from lxml import etree
from PIL import Image

HP='{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HH='{http://www.hancom.co.kr/hwpml/2011/head}'
HC='{http://www.hancom.co.kr/hwpml/2011/core}'
GRID_FRAME='source-ruled-grid-frame:v1'


def _vector(value,count):
    result=tuple(float(v) for v in value)
    if len(result)!=count or not all(math.isfinite(v) for v in result):raise ValueError('invalid grid geometry')
    return result


def _box(value):
    result=fitz.Rect(_vector(value,4))
    if result.is_empty or result.is_infinite:raise ValueError('empty grid geometry')
    return result


def _integer(value):
    result=float(value)
    if not math.isfinite(result) or result!=round(result):raise ValueError('nonintegral grid address')
    return int(result)


def _number(node,name):
    result=float(node.get(name))
    if not math.isfinite(result):raise ValueError('nonfinite native grid geometry')
    return result


def _text(element):return ''.join(t.text or '' for t in element.iter(HP+'t'))


def _same_pixels(a,b):
    with Image.open(io.BytesIO(a)) as first,Image.open(io.BytesIO(b)) as second:
        return first.size==second.size and first.convert('RGBA').tobytes()==second.convert('RGBA').tobytes()


def _source_native_fonts(paragraph,record,header,scale):
    """Compare complete native character styles with independently read PDF glyphs."""
    styles={p.get('id'):p for p in header.iter(HH+'charPr')}
    fonts={(face.get('lang'),font.get('id')):font.get('face')
           for face in header.iter(HH+'fontface') for font in face.findall(HH+'font')}
    native=[]
    for run in paragraph.findall(HP+'run'):
        style=styles[run.get('charPrIDRef')]
        refs=style.find(HH+'fontRef');ratios=style.find(HH+'ratio');tracking=style.find(HH+'spacing')
        langs={'hangul','latin','hanja','japanese','other','symbol','user'}
        if any(n is None or set(n.attrib)!=langs for n in (refs,ratios,tracking)):return False
        family={fonts.get((lang.upper(),ref)) for lang,ref in refs.attrib.items()}
        if len(family)!=1:return False
        actual=(family.pop(),_integer(style.get('height')),style.find(HH+'bold') is not None,
                style.find(HH+'italic') is not None,style.find(HH+'supscript') is not None,
                {_integer(v) for v in ratios.attrib.values()},{_integer(v) for v in tracking.attrib.values()})
        if any(child.tag!=HP+'t' or len(child) for child in run):return False
        native.extend((c,actual) for child in run for c in child.text or '')
    source=[]
    for span in record['spans'] if record else ():
        proved=span['_grid_font_proof']
        expected=(proved[0],round(span['size']*scale),proved[1],proved[2],proved[3],{proved[4]},{proved[5]})
        source.extend((char['c'],expected) for char in span['chars'])
    while source and source[0][0].isspace():source.pop(0)
    while source and source[-1][0].isspace():source.pop()
    return native==source


def _source_proof(layout,background=None):
    from .pdf_layout_writer import _pdf_output_text,is_hancom_eq_font
    from .pdf_source_backgrounds import compose_source_background,prove_background_source_text
    from . import storage
    if (not layout.get('source_content') or not layout.get('source_literal_text')
        or layout.get('source_answer_blanks')):return None
    geometry,=layout['native_tables']
    grid=_box(geometry['source_grid_bbox_pt']);frame=_box(geometry['bbox_pt'])
    if not frame.contains(grid) or geometry.get('images') or geometry.get('borderless_columns'):return None
    bounds=geometry['cell_bounds'];nr=len(bounds);nc=len(bounds[0])
    if nr<2 or nc<2 or any(len(row)!=nc for row in bounds):return None
    cells=[[_box(cell) for cell in row] for row in bounds]
    xs=[cells[0][0].x0]+[cell.x1 for cell in cells[0]]
    ys=[row[0].y0 for row in cells]+[cells[-1][0].y1]
    if any(b<=a for a,b in zip(xs,xs[1:])) or any(b<=a for a,b in zip(ys,ys[1:])):return None
    if _vector(grid,4)!=tuple((xs[0],ys[0],xs[-1],ys[-1])):return None
    if any(_vector(cell,4)!=(xs[c],ys[r],xs[c+1],ys[r+1])
           for r,row in enumerate(cells) for c,cell in enumerate(row)):return None
    records=layout['source_typography']['lines']
    with fitz.open(geometry['source_pdf_path']) as document:
        index=_integer(geometry['source_page_index'])
        if not 0<=index<len(document):return None
        page=document[index]
        if (float(layout['source_page_width_pt'])!=page.rect.width
            or not page.rect.contains(frame)):return None
        from .pdf_source_grid_geometry import source_grid_cell_bounds
        detected=[table for table in page.find_tables().tables
                  if tuple(table.bbox)==tuple(grid) and table.row_count==nr and table.col_count==nc]
        if len(detected)!=1 or source_grid_cell_bounds(page,detected[0])!=[[tuple(cell) for cell in row] for row in bounds]:return None
        segments=[]
        for drawing in page.get_drawings():
            if ('s' not in drawing.get('type','') or not drawing.get('width')
                or drawing.get('stroke_opacity',0)<=0 or drawing.get('color') is None
                or min(drawing['color'])>=.8 or drawing.get('dashes') not in (None,'','[] 0')):continue
            for item in drawing['items']:
                if item[0]=='l':segments.append((*item[1],*item[2]))
                elif item[0]=='re':
                    a,b,c,d=item[1];segments.extend(((a,b,c,b),(a,d,c,d),(a,b,a,d),(c,b,c,d)))
        # The detector snaps nearby page-wide rails (by three source points).
        # Verify its supplied result exactly, then recover the actual unique
        # complete grid from original dark PDF rules, never the snapped axes.
        def unique(values):
            result=[]
            for value in sorted(values):
                if not result or abs(value-result[-1])>.001:result.append(value)
            return result
        actual_x=unique(a for a,b,c,d in segments if abs(a-c)<=.001
                        and grid.x0-3<=a<=grid.x1+3 and min(b,d)<=grid.y0+3 and max(b,d)>=grid.y1-3)
        if len(actual_x)!=nc+1:return None
        actual_y=unique(b for a,b,c,d in segments if abs(b-d)<=.001
                        and grid.y0-3<=b<=grid.y1+3 and min(a,c)<=actual_x[0] and max(a,c)>=actual_x[-1])
        if len(actual_y)!=nr+1:return None
        xs,ys=actual_x,actual_y
        grid=_box((xs[0],ys[0],xs[-1],ys[-1]))
        if not fitz.Rect(frame.x0-.001,frame.y0-.001,frame.x1+.001,frame.y1+.001).contains(grid):return None
        cells=[[_box((xs[c],ys[r],xs[c+1],ys[r+1])) for c in range(nc)] for r in range(nr)]
        def ruled(start,end,vertical):
            intervals=[]
            for a,b,c,d in segments:
                if vertical and abs(a-start[0])<=.1 and abs(c-start[0])<=.1:intervals.append(sorted((b,d)))
                if not vertical and abs(b-start[1])<=.1 and abs(d-start[1])<=.1:intervals.append(sorted((a,c)))
            cursor=start[1] if vertical else start[0];stop=end[1] if vertical else end[0]
            for a,b in sorted(intervals):
                if a>cursor+.1:continue
                if b>=cursor:cursor=max(cursor,b)
            return cursor>=stop-.1
        if (not all(ruled((x,ys[0]),(x,ys[-1]),True) for x in xs)
            or not all(ruled((xs[0],y),(xs[-1],y),False) for y in ys)):return None
        raw=sorted((line for block in page.get_text('rawdict')['blocks'] for line in block.get('lines',[])
                    if grid.contains(_box(line['bbox']))),key=lambda line:(line['bbox'][1],line['bbox'][0]))
        if len(raw)!=len(records):return None
        from .pdf_native_typography import _font_name
        from .pdf_source_run_styles import _source_latin_tracking
        traces={}
        for trace in page.get_texttrace():
            if trace.get('wmode')!=0 or tuple(trace.get('dir',()))!=(1.0,0.0):continue
            size=float(trace['size'])
            if not math.isfinite(size) or size<=0:continue
            for char in trace['chars']:
                traces.setdefault((trace['font'],chr(char[0])),[]).append((char[2],size))
        for actual,given in zip(raw,records):
            value=''.join(c['c'] for s in actual['spans'] for c in s['chars'])
            if (_vector(given['bbox_pt'],4)!=_vector(actual['bbox'],4)
                or given['text']!=_pdf_output_text(value).strip()
                or len(actual['spans'])!=len(given['spans'])):return None
            for a,g in zip(actual['spans'],given['spans']):
                if (is_hancom_eq_font(a['font']) or any(a[k]!=g[k] for k in ('font','size','flags'))
                    or _integer(g['flags'])!=a['flags']
                    or _vector(a['origin'],2)!=_vector(g['origin'],2)
                    or _vector(a['bbox'],4)!=_vector(g['bbox'],4)
                    or g['text']!=''.join(c['c'] for c in a['chars']) or len(a['chars'])!=len(g['chars'])):return None
                for ac,gc in zip(a['chars'],g['chars']):
                    if (ac['c']!=gc['c'] or _vector(ac['origin'],2)!=_vector(gc['origin'],2)
                        or _vector(ac['bbox'],4)!=_vector(gc['bbox'],4)):return None
                family=_font_name(a['font']);flags=_integer(a['flags']);ratios=[]
                if family!='Times New Roman' or flags&~20:return None
                for char in a['chars']:
                    if char['c'].isspace():continue
                    sizes={size for origin,size in traces.get((a['font'],char['c']),[])
                           if max(abs(x-y) for x,y in zip(origin,char['origin']))<.0001}
                    if len(sizes)!=1:return None
                    ratios.append(round(sizes.pop()/a['size']*100))
                tracking=_source_latin_tracking(a,family,None)
                if not ratios or len(set(ratios))!=1:return None
                a['_grid_font_proof']=(family,bool(flags&16 or 'bold' in a['font'].lower()),
                                      bool(flags&2 or 'italic' in a['font'].lower()),bool(flags&1),ratios[0],tracking)
        # Short labels do not contain enough adjacent letters to distinguish
        # regular font kerning from run tracking. Their default may come only
        # from the actual grid's independently measured longer runs with the
        # exact same PDF face/size/flags/transform, never supplied metadata.
        defaults={}
        for row in raw:
            for span in row['spans']:
                proof=span['_grid_font_proof'];key=(span['font'],span['size'],span['flags'],proof[4])
                if proof[5] is not None:defaults.setdefault(key,set()).add(proof[5])
        for row in raw:
            for span in row['spans']:
                proof=span['_grid_font_proof']
                if proof[5] is None:
                    values=defaults.get((span['font'],span['size'],span['flags'],proof[4]),set())
                    if len(values)!=1:return None
                    span['_grid_font_proof']=(*proof[:5],next(iter(values)))
        by_cell=[]
        for row in cells:
            line=[]
            for cell in row:
                matching=[record for record in raw if cell.contains(_box(record['bbox']))]
                if len(matching)>1:return None
                line.append(matching[0] if matching else None)
            by_cell.append(line)
        if sum(record is not None for row in by_cell for record in row)!=len(raw):return None
        # Original non-text bitmap bands supply the outer decoration; a frame
        # can be sliced into adjacent/overlapping source image objects.
        images=[b for b in page.get_text('dict')['blocks'] if b.get('type')==1 and _box(b['bbox']).intersects(frame)]
        if not images:return None
        cursor=frame.y0
        for bounds_image in sorted((_box(b['bbox']) for b in images),key=lambda box:box.y0):
            if bounds_image.x0>frame.x0+.001 or bounds_image.x1<frame.x1-.001 or bounds_image.y0>cursor+.001:return None
            cursor=max(cursor,bounds_image.y1)
        if cursor<frame.y1-.001:return None
        expected=compose_source_background(page,frame,[image['number'] for image in images])
        if background is None:
            asset=storage.resolve_data_image_path(geometry['background_path'])
            if asset is None:return None
            background=asset.read_bytes()
        if not _same_pixels(expected,background):return None
        value=''.join(record['text'] for record in records)
        if not prove_background_source_text(page,frame,expected,value)['ok']:return None
        left,right=map(float,(layout['column_left_pt'],layout['column_right_pt']))
        if not all(math.isfinite(v) for v in (left,right)) or not left<=frame.x0<frame.x1<=right:return None
        return geometry,frame,grid,cells,by_cell,page.rect.width,expected


def restore_source_grid_layout(root,layout,header,page_width,column_width,*,hrefs,payloads):
    """Transactionally restore one fully proved, plain, unmerged native grid."""
    try:
        if not all(math.isfinite(float(v)) and float(v)>0 for v in (page_width,column_width)):return 0
        proof=_source_proof(layout)
        if proof is None:return 0
        geometry,frame,grid,bounds,raw,source_width,expected=proof
        tables=root.findall(HP+'run/'+HP+'tbl')
        if len(tables)!=1:return 0
        if any(child.tag not in (HP+'tbl',HP+'t') or (child.tag==HP+'t' and (len(child) or (child.text or '').strip()))
               for run in root.findall(HP+'run') for child in run):return 0
        table=tables[0];nr,nc=len(bounds),len(bounds[0])
        if (_integer(table.get('rowCnt'))!=nr or _integer(table.get('colCnt'))!=nc
            or table.get('name')==GRID_FRAME or list(table.iter(HP+'equation'))):return 0
        if any(etree.QName(child).localname not in ('sz','pos','outMargin','inMargin','tr','shapeComment') for child in table):return 0
        position=table.find(HP+'pos')
        if (table.get('textWrap')!='TOP_AND_BOTTOM' or table.get('lock')!='0'
            or any(position.get(k)!=v for k,v in (('treatAsChar','0'),('flowWithText','1'),
                ('allowOverlap','0'),('vertRelTo','PARA'),('horzRelTo','COLUMN'),
                ('horzAlign','LEFT'),('vertAlign','TOP'),('vertOffset','0'),('horzOffset','0')))
            or any(_number(table.find(HP+tag),k)!=0 for tag in ('outMargin','inMargin') for k in ('left','right','top','bottom'))):return 0
        fills=header.find('.//'+HH+'borderFills');styles={p.get('id'):p for p in header.iter(HH+'paraPr')}
        fill=next(f for f in fills if f.get('id')==table.get('borderFillIDRef'))
        image=fill.find('.//'+HC+'img')
        if image is None or hrefs.get(image.get('binaryItemIDRef')) not in payloads:return 0
        if (set(image.attrib)-{'binaryItemIDRef','bright','contrast','effect','alpha'}
            or any(image.get(k)!=v for k,v in (('bright','0'),('contrast','0'),('effect','REAL_PIC'),('alpha','0')))
            or fill.find('.//'+HC+'imgBrush').get('mode')!='TOTAL'):return 0
        if not _same_pixels(expected,payloads[hrefs[image.get('binaryItemIDRef')]]):return 0
        cells=table.findall(HP+'tr/'+HP+'tc')
        from hwpx.tools.ruled_grid_flow import lines as native_lines,native_font_height
        native_chars={p.get('id'):p for p in header.iter(HH+'charPr')}
        if len(cells)!=nr*nc:return 0
        for i,cell in enumerate(cells):
            r,c=divmod(i,nc);address=cell.find(HP+'cellAddr');span=cell.find(HP+'cellSpan')
            if (_integer(address.get('rowAddr'))!=r or _integer(address.get('colAddr'))!=c
                or _integer(span.get('rowSpan'))!=1 or _integer(span.get('colSpan'))!=1):return 0
            if (cell.get('protect')!='0'
                or any(_number(cell.find(HP+'cellMargin'),k)!=0 for k in ('left','right','top','bottom'))
                or cell.find(HP+'subList').get('textDirection')!='HORIZONTAL'
                or any(etree.QName(n).localname not in ('subList','cellAddr','cellSpan','cellSz','cellMargin') for n in cell)):return 0
            paragraphs=cell.findall(HP+'subList/'+HP+'p')
            if len(paragraphs)!=1:return 0
            paragraph=paragraphs[0]
            if any(child.tag not in (HP+'run',HP+'linesegarray') for child in paragraph):return 0
            if any(child.tag!=HP+'t' or len(child) for run in paragraph.findall(HP+'run') for child in run):return 0
            actual=raw[r][c]
            source=''.join(ch['c'] for s in actual['spans'] for ch in s['chars']).strip() if actual else ''
            if _text(paragraph)!=source:return 0
            native_lines(paragraph)
            line,=paragraph.findall(HP+'linesegarray/'+HP+'lineseg')
            if (_integer(line.get('textpos'))!=0 or _number(line,'vertsize')<=0
                or not 0<_number(line,'baseline')<_number(line,'vertsize')):return 0
            if actual and abs(_number(line,'textheight')-median(s['size'] for s in actual['spans'])*page_width/source_width)>1:return 0
            if (not _source_native_fonts(paragraph,actual,header,page_width/source_width)
                or actual and (native_font_height(paragraph,native_chars)!=_integer(line.get('textheight'))
                               or _integer(line.get('vertsize'))!=_integer(line.get('textheight')))):return 0
        staged=deepcopy(table);staged_header=deepcopy(header)
        if not _restore(staged,root,layout,staged_header,proof,page_width,column_width):return 0
        from hwpx.tools.ruled_grid_flow import geometry as native_grid_geometry, metrics, lines, fit, canonical_source_line
        _,_,native_cells=native_grid_geometry(staged,staged_header)
        para_styles={p.get('id'):p for p in staged_header.iter(HH+'paraPr')}
        char_styles={p.get('id'):p for p in staged_header.iter(HH+'charPr')}
        for cell in native_cells:
            paragraph=cell.find(HP+'subList/'+HP+'p')
            chars,_=metrics(paragraph,para_styles,char_styles)
            cache=lines(paragraph)
            width=_integer(cell.find(HP+'cellSz').get('width'))
            if not canonical_source_line(paragraph,char_styles,cache,width) or not fit(chars,cache,width):return 0
        # Existing XML/style objects remain intact; append only new styles.
        for tag in ('paraProperties','borderFills'):
            original=header.find('.//'+HH+tag);changed=staged_header.find('.//'+HH+tag)
            count=len(original)
            if [etree.tostring(v) for v in original]!=[etree.tostring(v) for v in list(changed)[:count]]:return 0
        if _text(table)!=_text(staged):return 0
        for tag in ('paraProperties','borderFills'):
            original=header.find('.//'+HH+tag);changed=staged_header.find('.//'+HH+tag)
            original.extend(list(changed)[len(original):]);original.set('itemCnt',str(len(original)))
        table.getparent().replace(table,staged)
        return 1
    except (ValueError,TypeError,AttributeError,KeyError,IndexError,StopIteration,OverflowError,OSError,
            fitz.FileNotFoundError,fitz.FileDataError,fitz.EmptyFileError):return 0


def _restore(table,root,layout,header,proof,page_width,column_width):
    from hwpx.tools.ruled_grid_flow import native_font_height
    geometry,frame,grid,bounds,raw,source_width,expected=proof
    scale=page_width/source_width;nr,nc=len(bounds),len(bounds[0])
    styles={p.get('id'):p for p in header.iter(HH+'paraPr')};paras=header.find('.//'+HH+'paraProperties')
    char_styles={p.get('id'):p for p in header.iter(HH+'charPr')}
    fills=header.find('.//'+HH+'borderFills')
    base=next(f for f in fills if f.get('id')==table.get('borderFillIDRef'))
    next_fill=max(int(f.get('id')) for f in fills)+1
    inner_fill=deepcopy(base);inner_fill.set('id',str(next_fill))
    for brush in inner_fill.findall(HC+'fillBrush'):inner_fill.remove(brush)
    fills.append(inner_fill);table.set('borderFillIDRef',inner_fill.get('id'))
    outer_fill=deepcopy(base);outer_fill.set('id',str(next_fill+1))
    blank_fill=deepcopy(inner_fill);blank_fill.set('id',str(next_fill+2))
    for f in (outer_fill,blank_fill):
        for edge in f:
            if etree.QName(edge).localname.endswith('Border'):edge.set('type','NONE')
        fills.append(f)
    widths=[round((row.x1-grid.x0)*scale)-round((row.x0-grid.x0)*scale) for row in bounds[0]]
    heights=[round((row[0].y1-grid.y0)*scale)-round((row[0].y0-grid.y0)*scale) for row in bounds]
    for i,cell in enumerate(table.findall(HP+'tr/'+HP+'tc')):
        r,c=divmod(i,nc);size=cell.find(HP+'cellSz');size.set('width',str(widths[c]));size.set('height',str(heights[r]))
        margin=cell.find(HP+'cellMargin')
        for edge in ('left','right','top','bottom'):margin.set(edge,'0')
        paragraph=cell.find(HP+'subList/'+HP+'p');record=raw[r][c]
        cell.find(HP+'subList').set('vertAlign','TOP')
        style=deepcopy(styles[paragraph.get('paraPrIDRef')]);style.set('id',str(max(int(p.get('id')) for p in paras)+1))
        style.find(HH+'align').set('horizontal','CENTER' if record else 'LEFT')
        for m in style.findall('.//'+HH+'margin'):
            for tag in ('left','right','intent','prev','next'):m.find(HC+tag).set('value','0')
        paras.append(style);paragraph.set('paraPrIDRef',style.get('id'))
        line=paragraph.find(HP+'linesegarray/'+HP+'lineseg');line.set('spacing','0');line.set('horzpos','0');line.set('horzsize',str(widths[c]))
        height=native_font_height(paragraph,char_styles)
        line.set('vertsize',str(height));line.set('textheight',str(height));line.set('baseline',str(round(height*.85)))
        if record:
            chars=[ch for s in record['spans'] for ch in s['chars'] if not ch['c'].isspace()]
            ink=_box((min(ch['bbox'][0] for ch in chars),min(ch['bbox'][1] for ch in chars),
                      max(ch['bbox'][2] for ch in chars),max(ch['bbox'][3] for ch in chars)))
            spaces=[ch['bbox'][2]-ch['bbox'][0] for s in record['spans'] for ch in s['chars'] if ch['c']==' ']
            precision=max(spaces,default=median(s['size'] for s in record['spans'])/4)
            if abs((ink.x0+ink.x1-bounds[r][c].x0-bounds[r][c].x1)/2)>precision:return False
            offset=round((record['spans'][0]['origin'][1]-bounds[r][c].y0)*scale-_number(line,'baseline'))
            if offset<0 or offset+_number(line,'vertsize')>heights[r]:return False
            margin.set('top',str(offset));cell.set('hasMargin','1')
            line.set('vertpos','0')
        else:
            line.set('vertpos','0')
            if _number(line,'vertsize')>heights[r]:return False
    table.find(HP+'sz').set('width',str(sum(widths)));table.find(HP+'sz').set('height',str(sum(heights)))
    position=table.find(HP+'pos');position.set('treatAsChar','1');position.set('horzRelTo','PARA');position.set('horzOffset','0');position.set('vertOffset','0')
    # Keep one real native table. Embedded table cells do not paint another
    # table in the current renderer. Empty, borderless source-derived gutters
    # represent the decoration's extent without stretching the actual grid.
    original_cells=table.findall(HP+'tr/'+HP+'tc')
    x_edges=[frame.x0]+[cell.x0 for cell in bounds[0]]+[grid.x1,frame.x1]
    y_edges=[frame.y0]+[row[0].y0 for row in bounds]+[grid.y1,frame.y1]
    x_edges=sorted(set(round((v-frame.x0)*scale) for v in x_edges))
    y_edges=sorted(set(round((v-frame.y0)*scale) for v in y_edges))
    widths=[b-a for a,b in zip(x_edges,x_edges[1:])]
    heights=[b-a for a,b in zip(y_edges,y_edges[1:])]
    c0=x_edges.index(round((grid.x0-frame.x0)*scale))
    r0=y_edges.index(round((grid.y0-frame.y0)*scale))
    if any(v<=0 for v in widths+heights):return False
    native_cells={(r+r0,c+c0):original_cells[r*nc+c] for r in range(nr) for c in range(nc)}
    template=deepcopy(original_cells[0])
    next_id=max((_integer(p.get('id')) for p in root.getroottree().getroot().iter(HP+'p')),default=0)+1
    empty_style=deepcopy(styles[root.get('paraPrIDRef')])
    empty_style.set('id',str(max(int(p.get('id')) for p in paras)+1))
    for margin in empty_style.findall('.//'+HH+'margin'):
        for tag in ('left','right','intent','prev','next'):margin.find(HC+tag).set('value','0')
    paras.append(empty_style)
    for row in list(table.findall(HP+'tr')):table.remove(row)
    for r,height in enumerate(heights):
        row=etree.SubElement(table,HP+'tr')
        for c,width in enumerate(widths):
            cell=native_cells.get((r,c))
            if cell is None:
                cell=deepcopy(template);cell.set('borderFillIDRef',blank_fill.get('id'))
                for edge in ('left','right','top','bottom'):cell.find(HP+'cellMargin').set(edge,'0')
                sub=cell.find(HP+'subList')
                for child in list(sub):sub.remove(child)
                paragraph=etree.SubElement(sub,HP+'p',paraPrIDRef=empty_style.get('id'),styleIDRef='0',pageBreak='0',columnBreak='0',merged='0',id=str(next_id))
                next_id+=1
                cache=etree.SubElement(paragraph,HP+'linesegarray')
                etree.SubElement(cache,HP+'lineseg',textpos='0',vertpos='0',vertsize='1',textheight='1',baseline='1',spacing='0',horzpos='0',horzsize=str(width),flags='393216')
            cell.find(HP+'cellAddr').set('rowAddr',str(r));cell.find(HP+'cellAddr').set('colAddr',str(c))
            cell.find(HP+'cellSz').set('width',str(width));cell.find(HP+'cellSz').set('height',str(height))
            for line in cell.findall(HP+'subList/'+HP+'p/'+HP+'linesegarray/'+HP+'lineseg'):
                line.set('horzsize',str(width))
            row.append(cell)
    table.set('rowCnt',str(len(heights)));table.set('colCnt',str(len(widths)))
    table.set('name',GRID_FRAME);table.set('borderFillIDRef',outer_fill.get('id'))
    table.find(HP+'sz').set('width',str(sum(widths)));table.find(HP+'sz').set('height',str(sum(heights)))
    position=table.find(HP+'pos');position.set('treatAsChar','0');position.set('horzRelTo','COLUMN')
    position.set('horzOffset',str(round((frame.x0-float(layout['column_left_pt']))*scale)))
    return True


def source_flow_grid_frame_table(table,root,header,hrefs,package,source,provenance):
    """Reconstruct expected native cells from actual source rules and pixels.

    Package names/cache snapshots never grant the source exception. Provenance
    chooses a candidate crop; its actual PDF pixels, every raw source span,
    all native cell text, widths, borders and baselines must match separately.
    """
    import hashlib
    from .pdf_layout_writer import _iter_text_lines,_item_bbox
    from .pdf_native_content import _source_typography
    from .pdf_source_grid_geometry import source_grid_cell_bounds
    from hwpx.tools.ruled_grid_flow import geometry as native_geometry,metrics,lines,fit,canonical_source_line
    try:
        native,heights,cells=native_geometry(table,header)
        nr,nc=native[:2]
        real=[divmod(i,nc) for i,v in enumerate(native[5]) if v[1]=='SOLID']
        r0,c0=min(r for r,c in real),min(c for r,c in real)
        r1,c1=max(r for r,c in real)+1,max(c for r,c in real)+1
        image=next(f for f in header.iter(HH+'borderFill') if f.get('id')==table.get('borderFillIDRef')).find('.//'+HC+'img')
        payload=package.read(hrefs[image.get('binaryItemIDRef')]) if hasattr(package,'read') else package[hrefs[image.get('binaryItemIDRef')]]
        checksum=hashlib.sha256(payload).hexdigest()
        candidates=[v for v in provenance if v.get('role')=='source_background_frame' and v.get('sha256')==checksum]
        page_pr=root.find('.//'+HP+'pagePr');page_width=_number(page_pr,'width');margin=page_pr.find(HP+'margin')
        col=next(c for c in root.iter(HP+'colPr') if c.get('colCount')=='2')
        left,gap=_number(margin,'left'),_number(col,'sameGap')
        col_width=(page_width-left-_number(margin,'right')-gap)/2
        width,height=_number(table.find(HP+'sz'),'width'),_number(table.find(HP+'sz'),'height')
        offset=_number(table.find(HP+'pos'),'horzOffset')
        ps={p.get('id'):p for p in header.iter(HH+'paraPr')};cs={p.get('id'):p for p in header.iter(HH+'charPr')}
        for cell in cells:
            paragraph=cell.find(HP+'subList/'+HP+'p');chars,_=metrics(paragraph,ps,cs);cache=lines(paragraph)
            cell_width=_integer(cell.find(HP+'cellSz').get('width'))
            if not canonical_source_line(paragraph,cs,cache,cell_width) or not fit(chars,cache,cell_width):return False
        with fitz.open(source) as document:
            for candidate in candidates:
                index=_integer(candidate['page'])-1
                if not 0<=index<len(document):continue
                page=document[index];scale=page_width/page.rect.width
                x,y,w,h=_vector(candidate['bbox_px'],4);frame=_box((x,y,x+w,y+h))
                if abs(width-frame.width*scale)>1 or abs(height-frame.height*scale)>1:continue
                origins=[origin for origin in (left,left+col_width+gap) if abs(frame.x0*scale-origin-offset)<=2]
                if len(origins)!=1:continue
                origin=origins[0]
                detected=[t for t in page.find_tables().tables if frame.contains(_box(t.bbox)) and t.row_count==r1-r0 and t.col_count==c1-c0]
                if len(detected)!=1:continue
                detected=detected[0]
                records=sorted([line for line in _iter_text_lines(page) if _box(detected.bbox).contains(_item_bbox(line))],key=lambda line:(_item_bbox(line).y0,_item_bbox(line).x0))
                layout={'source_content':True,'source_literal_text':True,'source_page_width_pt':page.rect.width,
                    'column_left_pt':origin/scale,'column_right_pt':(origin+col_width)/scale,
                    'source_typography':_source_typography(records,{'rect':fitz.Rect(detected.bbox)}),
                    'native_tables':[{'source_pdf_path':str(source),'source_page_index':index,'source_grid_bbox_pt':list(detected.bbox),
                        'bbox_pt':list(frame),'cell_bounds':source_grid_cell_bounds(page,detected)}]}
                proof=_source_proof(layout,payload)
                if proof is None:continue
                raw=proof[4]
                if any(not _source_native_fonts(cells[(r+r0)*nc+c+c0].find(HP+'subList/'+HP+'p'),raw[r][c],header,scale)
                       for r in range(r1-r0) for c in range(c1-c0)):continue
                if any(_text(cells[(r+r0)*nc+c+c0].find(HP+'subList/'+HP+'p'))!=
                       (''.join(ch['c'] for span in raw[r][c]['spans'] for ch in span['chars']).strip() if raw[r][c] else '')
                       for r in range(r1-r0) for c in range(c1-c0)):continue
                original=deepcopy(table);original.set('rowCnt',str(r1-r0));original.set('colCnt',str(c1-c0));original.set('name','')
                for row in list(original.findall(HP+'tr')):original.remove(row)
                for r in range(r0,r1):
                    row=etree.SubElement(original,HP+'tr')
                    for c in range(c0,c1):
                        cell=deepcopy(cells[r*nc+c]);cell.find(HP+'cellAddr').set('rowAddr',str(r-r0));cell.find(HP+'cellAddr').set('colAddr',str(c-c0));row.append(cell)
                expected_header=deepcopy(header)
                if not _restore(original,table.getparent().getparent(),layout,expected_header,proof,page_width,col_width):continue
                expected=original.findall(HP+'tr/'+HP+'tc')
                if original.get('rowCnt')!=table.get('rowCnt') or original.get('colCnt')!=table.get('colCnt') or len(expected)!=len(cells):continue
                valid=True
                for actual,wanted in zip(cells,expected):
                    if any(dict(actual.find(HP+tag).attrib)!=dict(wanted.find(HP+tag).attrib) for tag in ('cellAddr','cellSpan','cellSz','cellMargin')):
                        valid=False;break
                    ap=actual.find(HP+'subList/'+HP+'p');wp=wanted.find(HP+'subList/'+HP+'p')
                    wanted_style=next(s for s in expected_header.iter(HH+'paraPr') if s.get('id')==wp.get('paraPrIDRef'))
                    if (_text(ap)!=_text(wp) or lines(ap)!=lines(wp)
                        or ps[ap.get('paraPrIDRef')].find(HH+'align').get('horizontal')!=wanted_style.find(HH+'align').get('horizontal')):valid=False;break
                if valid:return True
        return False
    except (ValueError,TypeError,AttributeError,KeyError,IndexError,StopIteration,OverflowError,OSError,
            fitz.FileNotFoundError,fitz.FileDataError,fitz.EmptyFileError):return False
