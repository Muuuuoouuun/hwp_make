"""Restore source-confirmed English answer rules using native text underline.

The PDF's words remain ordinary paragraph text. A printed empty rule has no
character inventory, and therefore must never be represented by underscores.
"""
from __future__ import annotations

from copy import deepcopy
import math
import re
import struct
from statistics import median

import fitz
from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
_TEXT_GEOMETRY_KEY = object()
_WHITE_COVER_KEY = object()
_GLYF_BUDGET_KEY = object()


def _compact(value):
    return re.sub(r"\s+", "", value)


def _visible_ink(color, opacity):
    try:
        values = tuple(float(value) for value in color)
        alpha = float(opacity)
    except (TypeError, ValueError):
        return False
    return (bool(values) and all(math.isfinite(value) and 0 <= value <= 1 for value in values)
            and math.isfinite(alpha) and alpha == 1 and max(values) < .5)


def _painted_rule(page, left, right, y, thickness):
    # Later white paint can hide a perfectly valid path. Confirm continuous
    # visible ink in its interior before restoring it as editable whitespace.
    half = thickness / 2
    region = fitz.Rect(left + .5, y - half - .5, right - .5, y + half + .5)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=region,
                             colorspace=fitz.csGRAY, alpha=False)
    if not pixmap.width or not pixmap.height:
        return False
    samples = pixmap.samples
    return all(min(samples[column::pixmap.stride]) < 192
               for column in range(pixmap.width))


def _validated_glyf_points(tables, fmt, glyphs, gid, cache, active=None, cost=None):
    """Bound actual simple/compound outline points before trusting glyph bounds.

    A declared glyf header is only metadata. Every decoded contour/control point
    must fit its own declared box, including recursively transformed components.
    Their convex hull bounds every quadratic outline segment. Ambiguous compound
    offset conventions, cyclic graphs and unsupported/malformed records abstain.
    No checksum or advance box can substitute for this local outline proof.
    """
    if gid in cache:
        return cache[gid]
    if active is None:
        active=set()
    if cost is None:
        cost=cache.setdefault(_GLYF_BUDGET_KEY,[0,0])
    if type(gid) is not int or not 0 <= gid < glyphs or gid in active or len(active)>=16:
        raise ValueError('invalid/cyclic later compound GID')
    cost[0]+=1
    if cost[0]>128:
        raise ValueError('later glyph graph budget')
    loca=tables[b'loca'];glyf=tables[b'glyf']
    step=2 if fmt==0 else 4
    if len(loca)<step*(glyphs+1):
        raise ValueError('short later loca table')
    if fmt==0:
        start,end=(struct.unpack_from('>H',loca,2*i)[0]*2 for i in (gid,gid+1))
    else:
        start,end=(struct.unpack_from('>I',loca,4*i)[0] for i in (gid,gid+1))
    if not 0<=start<=end<=len(glyf) or (start!=end and end-start<10):
        raise ValueError('malformed later glyph outline')
    if start==end:
        cache[gid]=();return ()
    data=glyf[start:end]
    contours,x0,y0,x1,y1=struct.unpack_from('>hhhhh',data)
    if x0>x1 or y0>y1:
        raise ValueError('inverted later glyph bounds')
    pos=10;points=[];active.add(gid)
    def take(pattern):
        nonlocal pos
        size=struct.calcsize(pattern)
        if pos+size>len(data):
            raise ValueError('short later outline record')
        values=struct.unpack_from(pattern,data,pos);pos+=size
        return values
    try:
        if contours>=0:
            if contours>32767:
                raise ValueError('later contour budget')
            ends=list(take('>'+str(contours)+'H')) if contours else []
            if ends and any(a>=b for a,b in zip(ends,ends[1:])):
                raise ValueError('nonmonotone contour endpoints')
            count=ends[-1]+1 if ends else 0
            cost[1]+=count
            if cost[1]>65536:
                raise ValueError('later point budget')
            instructions,=take('>H')
            if pos+instructions>len(data):
                raise ValueError('short later glyph instructions')
            pos+=instructions;flags=[]
            while len(flags)<count:
                flag,=take('>B')
                if flag&0x80:
                    raise ValueError('reserved later point flag')
                repeat=take('>B')[0]+1 if flag&8 else 1
                if len(flags)+repeat>count:
                    raise ValueError('later point repeat overflow')
                flags.extend([flag]*repeat)
            axes=[]
            for short,same in ((2,16),(4,32)):
                values=[];current=0
                for flag in flags:
                    if flag&short:
                        delta,=take('>B')
                        if not flag&same:delta=-delta
                    else:
                        delta=0 if flag&same else take('>h')[0]
                    current+=delta;values.append(current)
                axes.append(values)
            points=list(zip(*axes))
        elif contours==-1:
            components=0
            while True:
                flags,component=take('>HH');components+=1
                if flags&~0x1FEF or components>64:
                    raise ValueError('unsupported later compound flags')
                if sum(bool(flags&mask) for mask in (8,64,128))>1 or flags&0x1800==0x1800:
                    raise ValueError('ambiguous later compound transform')
                xy=bool(flags&2)
                arg1,arg2=take('>hh' if xy and flags&1 else '>bb' if xy else '>HH' if flags&1 else '>BB')
                a=d=1.;b=c=0.
                if flags&8:a=d=take('>h')[0]/16384
                elif flags&64:a,d=(v/16384 for v in take('>hh'))
                elif flags&128:a,b,c,d=(v/16384 for v in take('>hhhh'))
                child=_validated_glyf_points(tables,fmt,glyphs,component,cache,active,cost)
                transformed=[(a*x+c*y,b*x+d*y) for x,y in child]
                if xy:
                    dx,dy=arg1,arg2
                    if flags&0x800:
                        dx,dy=a*arg1+c*arg2,b*arg1+d*arg2
                    elif not flags&0x1000 and (a,b,c,d)!=(1.,0.,0.,1.) and (arg1 or arg2):
                        raise ValueError('unspecified compound offset convention')
                    if flags&4 and (dx!=int(dx) or dy!=int(dy)):
                        raise ValueError('unsupported compound grid offset')
                else:
                    if flags&0x1800 or not 0<=arg1<len(points) or not 0<=arg2<len(transformed):
                        raise ValueError('invalid compound point attachment')
                    dx,dy=points[arg1][0]-transformed[arg2][0],points[arg1][1]-transformed[arg2][1]
                if len(points)+len(transformed)>65536:
                    raise ValueError('compound output point budget')
                cost[1]+=len(transformed)
                if cost[1]>65536:
                    raise ValueError('later cached point budget')
                points.extend((x+dx,y+dy) for x,y in transformed)
                if not flags&32:
                    break
            if flags&256:
                instructions,=take('>H')
                if pos+instructions>len(data):
                    raise ValueError('short compound instructions')
                pos+=instructions
        else:
            raise ValueError('reserved later contour kind')
        if any(not (math.isfinite(x) and math.isfinite(y) and x0<=x<=x1 and y0<=y<=y1) for x,y in points):
            raise ValueError('declared glyf bounds do not contain actual outline')
        cache[gid]=tuple(points)
        return cache[gid]
    finally:
        active.remove(gid)


def _trace_glyph_ink(page, trace, char, fonts, *, transform=None):
    """Read the actual traced TTF GID bounds; font boxes are not ink boxes.

    Missing/ambiguous programs or unsupported direction cannot grant permission.
    Current-paint permission supplies the actual affine SVG glyph transform
    after complete display/text inventory and origin binding. Empty glyf
    records have no ink. Only horizontal source writing is handled here.
    """
    if trace.get('wmode') != 0 or tuple(trace.get('dir', ())) != (1., 0.):
        raise ValueError('unsupported later text direction')
    face = trace.get('font')
    if face not in fonts:
        programs = set()
        for entry in page.get_fonts(full=True):
            name = re.sub(r'^[A-Z]{6}\+', '', entry[3])
            if name == face:
                _, extension, _, program = page.parent.extract_font(entry[0])
                if extension != 'ttf' or not program:
                    raise ValueError('unsupported later text font program')
                programs.add(program)
        if len(programs) != 1:
            raise ValueError('ambiguous later text font program')
        program = next(iter(programs))
        if program[:4] not in {b'\x00\x01\x00\x00', b'true'}:
            raise ValueError('unsupported later font outline')
        count = struct.unpack_from('>H', program, 4)[0]
        tables = {}
        for i in range(count):
            tag, _, start, length = struct.unpack_from('>4sIII', program, 12+16*i)
            if tag in tables or start+length > len(program):
                raise ValueError('malformed later font table')
            tables[tag] = program[start:start+length]
        units = struct.unpack_from('>H', tables[b'head'], 18)[0]
        fmt = struct.unpack_from('>h', tables[b'head'], 50)[0]
        glyphs = struct.unpack_from('>H', tables[b'maxp'], 4)[0]
        metrics = struct.unpack_from('>H', tables[b'hhea'], 34)[0]
        if not units or fmt not in (0, 1) or not 0 < metrics <= glyphs:
            raise ValueError('unsupported later font metrics')
        fonts[face] = (tables, units, fmt, glyphs, metrics, {})
    tables, units, fmt, glyphs, metrics, bounds = fonts[face]
    gid = char[1]
    if type(gid) is not int or not 0 <= gid < glyphs:
        raise ValueError('invalid later traced GID')
    points = _validated_glyf_points(tables, fmt, glyphs, gid, bounds)
    if not points:
        return fitz.Rect()
    advance = struct.unpack_from('>H', tables[b'hmtx'], 4*min(gid,metrics-1))[0]
    size = trace['size']
    if not advance or not math.isfinite(size) or size <= 0:
        raise ValueError('unsupported later glyph advance')
    scale = size/units
    x0=min(p[0] for p in points);y0=min(p[1] for p in points)
    x1=max(p[0] for p in points);y1=max(p[1] for p in points)
    x,y = char[2]
    if transform is None:
        raise ValueError('missing proved actual SVG glyph transform')
    if len(transform) != 4 or not all(math.isfinite(v) for v in transform):
        raise ValueError('invalid actual glyph transform')
    a,b,c,d = (v/units for v in transform)
    points = [(x+a*gx+c*gy, y+b*gx+d*gy)
              for gx,gy in ((x0,y0),(x1,y0),(x0,y1),(x1,y1))]
    box = fitz.Rect(min(p[0] for p in points), min(p[1] for p in points),
                    max(p[0] for p in points), max(p[1] for p in points))
    if trace.get('type') == 1:
        width = trace.get('linewidth')
        if not isinstance(width, (int,float)) or not math.isfinite(width) or width < 0:
            raise ValueError('unsupported later text stroke')
        box += (-width/2,-width/2,width/2,width/2)
    return box


def _paint_overlaps(rect, bounds):
    # MuPDF's special infinite shading rectangle reports intersects=False.
    # Unknown/unbounded later paint cannot grant local non-overlap permission.
    if (len(bounds) != 4 or not all(math.isfinite(v) for v in bounds)
            or bounds[0] > bounds[2] or bounds[1] > bounds[3]):
        return True
    return (bounds[0] < rect.x1 and rect.x0 < bounds[2]
            and bounds[1] < rect.y1 and rect.y0 < bounds[3])


def _svg_shade_boxes(page, paint_log, traces, *, text_geometry=None, white_covers=None):
    """Bind finite MuPDF SVG image bounds only through complete paint order.

    SVG may split a PDF text call into font fragments. Consume their complete
    Unicode inventory against that exact display-list text sequence. Paths,
    images and shaded raster images each occupy one ordered paint entry. A
    missing/extra leaf or unknown representation grants no shading permission.
    Image bounds are an upper bound even when SVG clips further restrict paint.
    """
    svg_ns = 'http://www.w3.org/2000/svg'
    link = '{http://www.w3.org/1999/xlink}href'
    identity = (1.,0.,0.,1.,0.,0.)
    def values(value, count):
        result = tuple(float(v) for v in re.split(r'[\s,]+', value.strip()))
        if len(result) != count or not all(math.isfinite(v) for v in result):
            raise ValueError('invalid SVG geometry')
        return result
    def multiply(a,b):
        return (a[0]*b[0]+a[2]*b[1], a[1]*b[0]+a[3]*b[1],
                a[0]*b[2]+a[2]*b[3], a[1]*b[2]+a[3]*b[3],
                a[0]*b[4]+a[2]*b[5]+a[4], a[1]*b[4]+a[3]*b[5]+a[5])
    def matrix(node):
        value = node.get('transform')
        if value is None:return identity
        match = re.fullmatch(r'matrix\(([^()]*)\)', value)
        if match is None:raise ValueError('unsupported SVG transform')
        return values(match[1],6)
    def tag(node):
        q = etree.QName(node)
        if q.namespace != svg_ns:raise ValueError('foreign SVG namespace')
        return q.localname
    def image_box(node, transform):
        source=node.get(link) or node.get('href') or ''
        if not source.startswith('data:image/png;base64,'):
            raise ValueError('unsupported SVG raster source')
        transform = multiply(transform,matrix(node))
        x,y,width,height = (float(node.get(k, default)) for k,default in
                            (('x','0'),('y','0'),('width','nan'),('height','nan')))
        if not all(math.isfinite(v) for v in (x,y,width,height)) or min(width,height)<=0:
            raise ValueError('invalid SVG image extent')
        points=[(transform[0]*a+transform[2]*b+transform[4],
                 transform[1]*a+transform[3]*b+transform[5])
                for a,b in ((x,y),(x+width,y),(x,y+height),(x+width,y+height))]
        result=(min(p[0] for p in points),min(p[1] for p in points),
                max(p[0] for p in points),max(p[1] for p in points))
        if not all(math.isfinite(v) and abs(v)<1e7 for v in result):
            raise ValueError('unbounded SVG image')
        return result
    try:
        parser=etree.XMLParser(resolve_entities=False,no_network=True)
        root=etree.fromstring(page.get_svg_image(text_as_path=False).encode('utf8'),parser)
        if tag(root)!='svg' or root.get('transform') is not None:
            raise ValueError('unsupported SVG root')
        expected=(0.,0.,page.rect.width,page.rect.height)
        if any(abs(a-b)>.001 for a,b in zip(values(root.get('viewBox',''),4),expected)):
            raise ValueError('SVG page geometry mismatch')
        ids={}
        for node in root.iter():
            identifier=node.get('id')
            if identifier:
                if identifier in ids:raise ValueError('duplicate SVG ID')
                ids[identifier]=node
        leaves=[]
        def glyph_geometry(node, transform):
            # Unknown text geometry does not invalidate unrelated paint. A
            # locally intersecting visible glyph still cannot be permitted
            # without its own complete affine/origin match below.
            try:
                current=multiply(transform,matrix(node))
                size=float(node.get('font-size','nan'))
                if not math.isfinite(size) or size<=0:raise ValueError('invalid SVG font size')
                result=[]
                for span in node:
                    if (len(span) or any(span.get(key) is not None for key in
                            ('transform','font-size','dx','dy','rotate','textLength','lengthAdjust'))):
                        raise ValueError('unsupported SVG text geometry')
                    text=span.text or ''
                    xs=values(span.get('x',''),len(text))
                    ys=tuple(float(v) for v in re.split(r'[\s,]+',span.get('y','').strip()))
                    if len(ys) not in (1,len(text)) or not all(math.isfinite(v) for v in ys):
                        raise ValueError('invalid SVG text origins')
                    for i,(char,x) in enumerate(zip(text,xs)):
                        y=ys[0] if len(ys)==1 else ys[i]
                        result.append((char,(current[0]*x+current[2]*y+current[4],
                                             current[1]*x+current[3]*y+current[5]),
                                       (current[0]*size,current[1]*size,
                                        -current[2]*size,-current[3]*size)))
                return result
            except (ValueError,TypeError,IndexError):
                return None
        def visit(node, transform, clipped=False, opaque=True):
            kind=tag(node)
            if any(node.get(k) is not None for k in ('filter','mask','style')):
                raise ValueError('unsupported SVG effect')
            if kind=='defs':return
            clip=node.get('clip-path')
            if clip:
                match=re.fullmatch(r'url\(#([^()]+)\)',clip)
                if match is None or match[1] not in ids or tag(ids[match[1]])!='clipPath':
                    raise ValueError('unknown SVG clip')
                clipped=True
            alpha=float(node.get('opacity','1'))
            if not math.isfinite(alpha) or not 0<=alpha<=1:
                raise ValueError('invalid SVG opacity')
            opaque=opaque and alpha==1
            if kind in {'svg','g'}:
                current=multiply(transform,matrix(node))
                for child in node:visit(child,current,clipped,opaque)
            elif kind=='text':
                if any(tag(child)!='tspan' for child in node):
                    raise ValueError('unsupported SVG text fragment')
                alpha=float(node.get('fill-opacity','1'))
                if not math.isfinite(alpha) or not 0<=alpha<=1:
                    raise ValueError('unsupported SVG text opacity')
                leaves.append(('text',''.join(node.itertext()),alpha,
                               glyph_geometry(node,transform) if text_geometry is not None else None))
            elif kind=='path':
                leaves.append(('path',None,None,not clipped and opaque
                               and node.get('fill')=='#ffffff'
                               and float(node.get('fill-opacity','1'))==1))
            elif kind=='image':leaves.append(('image',None,image_box(node,transform)))
            elif kind=='use':
                ref=node.get(link) or node.get('href')
                if not ref or not ref.startswith('#') or ref[1:] not in ids or tag(ids[ref[1:]])!='image':
                    raise ValueError('unsupported SVG use')
                reference=ids[ref[1:]]
                for key in ('x','y'):
                    if float(node.get(key,'0'))!=0:
                        raise ValueError('unsupported SVG use translation')
                for key in ('width','height'):
                    if node.get(key) is not None and float(node.get(key))!=float(reference.get(key,'nan')):
                        raise ValueError('unsupported SVG use scaling')
                leaves.append(('image',None,image_box(ids[ref[1:]],multiply(transform,matrix(node)))))
            else:raise ValueError('unsupported SVG paint leaf')
        visit(root,identity)
        text={}
        for trace in traces:
            text.setdefault(trace['seqno'],[]).extend(trace['chars'])
        cursor=0;result={};geometries={};covers=set()
        for seq,event in enumerate(paint_log):
            if cursor>=len(leaves):raise ValueError('missing SVG paint')
            kind=event[0];leaf=leaves[cursor]
            if kind in {'fill-text','stroke-text','ignore-text'}:
                expected=''.join(chr(c[0]) for c in text.get(seq,[]))
                if not expected:raise ValueError('missing display text inventory')
                observed='';geometry=[]
                while len(observed)<len(expected):
                    if cursor>=len(leaves) or leaves[cursor][0]!='text':
                        raise ValueError('SVG text ordering mismatch')
                    if kind=='ignore-text' and leaves[cursor][2]!=0:
                        raise ValueError('ignored text has actual SVG paint')
                    observed+=leaves[cursor][1]
                    geometry.extend(leaves[cursor][3] or [None]*len(leaves[cursor][1]));cursor+=1
                if observed!=expected:raise ValueError('SVG/display text inventory mismatch')
                if text_geometry is not None:
                    if len(geometry)!=len(text[seq]):raise ValueError('SVG glyph count mismatch')
                    for char,given in zip(text[seq],geometry):
                        key=(seq,char[0],char[1],tuple(char[2]))
                        if key in geometries:raise ValueError('ambiguous SVG glyph identity')
                        if (given is not None and given[0]==chr(char[0])
                            and max(abs(a-b) for a,b in zip(given[1],char[2]))<=.002):
                            geometries[key]=given[2]
                        else:geometries[key]=None
                continue
            family='path' if kind in {'fill-path','stroke-path'} else 'image' if kind in {'fill-image','fill-shade'} else None
            if family is None or leaf[0]!=family:raise ValueError('SVG/display paint kind mismatch')
            if kind=='fill-image':
                if any(not math.isfinite(v) or abs(v)>1e7 for v in event[1]) or any(abs(a-b)>.002 for a,b in zip(leaf[2],event[1])):
                    raise ValueError('SVG/display image geometry mismatch')
            if kind=='fill-shade':result[seq]=leaf[2]
            if kind=='fill-path' and white_covers is not None and leaf[3]:covers.add(seq)
            cursor+=1
        if cursor!=len(leaves):raise ValueError('extra SVG paint')
        if text_geometry is not None:text_geometry.update(geometries)
        if white_covers is not None:white_covers.update(covers)
        return result
    except (ValueError,KeyError,TypeError,IndexError,AttributeError,etree.XMLSyntaxError,RuntimeError):
        return {}


def _current_rule_paint(page, segment, sequence, drawings, paint_log, traces, fonts, shade_boxes):
    """TMP: prove later paint locally before old source fragments are merged.

    A dark pixel near an old path may belong to a colored redraw. The old
    segment has no permission after intersecting unproved paint. Supported
    later opaque dark solid lines may repeat or extend the same centerline.
    Text log bounds can cover several lines, so only actual nonspace glyph
    bounds participate in text overlap rather than the broad text log box.
    """
    if type(sequence) is not int or not 0 <= sequence < len(paint_log):
        return False
    x0, y0, x1, y1, thickness = segment
    if not all(math.isfinite(v) for v in segment) or thickness <= 0:
        return False
    half = thickness/2
    protected = fitz.Rect(min(x0,x1)-half, min(y0,y1)-half,
                          max(x0,x1)+half, max(y0,y1)+half)
    by_sequence = {}
    for drawing in drawings:
        seq = drawing.get('seqno')
        if type(seq) is int:
            by_sequence.setdefault(seq, []).append(drawing)
    own = by_sequence.get(sequence, [])
    if (paint_log[sequence][0] != 'stroke-path' or len(own) != 1
            or own[0].get('type') != 's' or own[0].get('dashes', '').strip() != '[] 0'):
        return False
    text_by_sequence = {}
    for trace in traces:
        seq = trace.get('seqno')
        if type(seq) is int:
            text_by_sequence.setdefault(seq, []).append(trace)
    for seq, event in enumerate(paint_log):
        if seq <= sequence:
            continue
        kind, bounds = event[:2]
        if kind=='fill-shade' and seq in shade_boxes:
            bounds=shade_boxes[seq]
        if not _paint_overlaps(protected, bounds):
            continue
        if kind in {'fill-text', 'stroke-text', 'ignore-text'}:
            current = text_by_sequence.get(seq)
            if not current:
                return False
            for trace in current:
                for char in trace['chars']:
                    # Neither the advance box nor the font box bounds actual
                    # ink: italic negative bearings can cross a rule from an
                    # otherwise outside advance. Ignored/zero-alpha text is
                    # explicitly nonpainting and needs no font permission.
                    alpha=trace.get('opacity')
                    if not isinstance(alpha,(int,float)) or not math.isfinite(alpha) or not 0<=alpha<=1:
                        return False
                    if kind=='ignore-text':
                        if trace.get('type')!=3:return False
                        continue
                    if alpha==0 or not chr(char[0]).strip():
                        continue
                    if trace.get('type')!=0 or kind!='fill-text':return False
                    if _TEXT_GEOMETRY_KEY not in fonts:
                        geometry={};covers=set()
                        _svg_shade_boxes(page,paint_log,traces,text_geometry=geometry,white_covers=covers)
                        fonts[_TEXT_GEOMETRY_KEY]=geometry
                        fonts[_WHITE_COVER_KEY]=covers
                    transform=fonts[_TEXT_GEOMETRY_KEY].get((seq,char[0],char[1],tuple(char[2])))
                    if transform is None:return False
                    if abs(math.hypot(transform[0],transform[1])-trace['size'])>.002:
                        return False
                    try:
                        ink = _trace_glyph_ink(page, trace, char, fonts, transform=transform)
                    except (ValueError, KeyError, TypeError, IndexError, struct.error):
                        return False
                    if protected.intersects(ink):
                        return False
            continue
        matches = by_sequence.get(seq, [])
        if kind != 'stroke-path' or len(matches) != 1:
            return False
        drawing = matches[0]
        width = drawing.get('width')
        if (drawing.get('type') != 's'
                or not _visible_ink(drawing.get('color'), drawing.get('stroke_opacity'))
                or drawing.get('dashes', '').strip() != '[] 0'
                or not isinstance(width, (int, float)) or not math.isfinite(width) or width <= 0):
            return False
        for item in drawing.get('items', []):
            if item[0] != 'l':
                return False
            a, b = item[1:3]
            extent = fitz.Rect(min(a.x,b.x)-width/2, min(a.y,b.y)-width/2,
                               max(a.x,b.x)+width/2, max(a.y,b.y)+width/2)
            if not protected.intersects(extent):
                continue
            if abs(a.y-b.y) > .002 or max(abs(a.y-y0), abs(b.y-y1)) > .002:
                return False
    return True


def _discarded_extent_hidden(segment, sequence, drawings, white_covers):
    """Permit a shorter new rule only when the complete old one was erased.

    Otherwise exposed old ends can remain connected to a new middle stroke,
    and returning only that middle would silently shorten the current rule.
    The supported eraser is an actual later opaque white rectangle with an
    unclipped SVG paint occurrence bound to the same display-list sequence.
    """
    x0,y0,x1,y1,width=segment
    physical=fitz.Rect(min(x0,x1)-width/2,min(y0,y1)-width/2,
                       max(x0,x1)+width/2,max(y0,y1)+width/2)
    for drawing in drawings:
        seq=drawing.get('seqno')
        if (type(seq) is not int or seq<=sequence or seq not in white_covers
            or drawing.get('type')!='f' or drawing.get('fill_opacity')!=1):
            continue
        fill=drawing.get('fill');items=drawing.get('items')
        if (not fill or not all(value==1 for value in fill) or len(items or ())!=1
            or items[0][0]!='re'):
            continue
        if fitz.Rect(items[0][1]).contains(physical):return True
    return False


def measure_answer_blanks(page, lines, *, area_hint=""):
    """Measure empty source rules and associate them with unchanged source lines.

Offsets count nonspace source characters within the owning line. The native
content extractor later associates that exact line bbox with its paragraph.
Only independently verified English inputs opt in.
"""
    if _compact(str(area_hint)) not in {"영어영역", "영어", "English", "ENGLISH"}:
        return []
    from .pdf_layout_writer import _pdf_output_text
    segments = [];discarded=[]
    drawings = page.get_drawings()
    paint_log = page.get_bboxlog()
    traces = page.get_texttrace()
    fonts = {}
    shade_boxes = (_svg_shade_boxes(page,paint_log,traces)
                   if any(event[0]=='fill-shade' for event in paint_log) else {})
    for drawing in drawings:
        stroke = (drawing.get("type") in {"s", "fs"}
                  and _visible_ink(drawing.get("color"), drawing.get("stroke_opacity", 1)))
        fill = (drawing.get("type") in {"f", "fs"}
                and _visible_ink(drawing.get("fill"), drawing.get("fill_opacity", 1)))
        for item in drawing.get("items", []):
            if item[0] == "l" and stroke:
                segment = (item[1].x, item[1].y, item[2].x, item[2].y,
                           float(drawing.get("width") or .5))
                if (abs(segment[1]-segment[3]) > .5 or
                        _current_rule_paint(page, segment, drawing.get('seqno'), drawings, paint_log, traces, fonts, shade_boxes)):
                    segments.append(segment)
                else:discarded.append((segment,drawing.get('seqno')))
            elif item[0] == "re" and (stroke or fill):
                rect = fitz.Rect(item[1])
                segments.extend([(rect.x0, rect.y0, rect.x0, rect.y1, .5),
                                 (rect.x1, rect.y0, rect.x1, rect.y1, .5)])
    images = [fitz.Rect(info["bbox"]) for info in page.get_image_info()]
    # Some PDFs emit one empty rule in adjacent font-run pieces. Join only
    # almost touching collinear strokes; widely separated summary A/B rules
    # remain independent source objects.
    unique = {}
    for segment in segments:
        if abs(segment[1]-segment[3]) <= .5:
            signature = tuple(segment[:4])
            previous=unique.get(signature)
            if previous is None or segment[4]>previous[4]:
                unique[signature]=segment
    horizontal = sorted(unique.values(),
                        key=lambda s: (round(s[1], 1), min(s[0], s[2])))
    merged = [];members=[]
    for x0,y0,x1,y1,thickness in horizontal:
        left,right = sorted((x0,x1))
        if (merged and abs(merged[-1][1]-y0) <= .2
                and left <= merged[-1][2]+3):
            previous = merged[-1]
            merged[-1] = (previous[0], y0, max(previous[2],right), y0, max(previous[4],thickness))
            members[-1].append((left,right,thickness,y0,y1))
        else:
            merged.append((left,y0,right,y1,thickness))
            members.append([(left,right,thickness,y0,y1)])
    uniform=[]
    for segment,parts in zip(merged,members):
        width=segment[4]
        widest=sorted((left,right) for left,right,w,_,_ in parts if w==width)
        cover=[]
        for left,right in widest:
            if cover and left<=cover[-1][1]:cover[-1]=(cover[-1][0],max(cover[-1][1],right))
            else:cover.append((left,right))
        # A single returned width must describe the entire visible component.
        # A shorter thick redraw over a longer thin line has no such scalar;
        # abstain locally instead of spreading its width or shrinking extent.
        same_centerline=all(y0==parts[0][3] and y1==parts[0][4]
                            for _,_,_,y0,y1 in parts)
        outside=[(old,seq) for old,seq in discarded
                 if old[1]==segment[1] and old[3]==segment[3]
                 and min(old[0],old[2])<=segment[2] and max(old[0],old[2])>=segment[0]
                 and (min(old[0],old[2])<segment[0] or max(old[0],old[2])>segment[2])]
        if outside and _WHITE_COVER_KEY not in fonts:
            covers=set()
            _svg_shade_boxes(page,paint_log,traces,white_covers=covers)
            fonts[_WHITE_COVER_KEY]=covers
        complete_extent=all(_discarded_extent_hidden(old,seq,drawings,fonts[_WHITE_COVER_KEY])
                            for old,seq in outside)
        if (same_centerline and complete_extent
            and all(any(a<=left and right<=b for a,b in cover)
                    for left,right,_,_,_ in parts)):
            uniform.append(segment)
    merged=uniform
    result, seen = [], set()
    for x0, y0, x1, y1, thickness in merged:
        left, right = sorted((x0, x1))
        if abs(y1-y0) > .5 or not 25 <= right-left <= page.rect.width*.45:
            continue
        signature = (round(left, 1), round(y0, 1), round(right, 1))
        if signature in seen:
            continue
        seen.add(signature)
        if any(rect.contains(fitz.Point((left+right)/2, y0)) for rect in images):
            continue
        if any(abs(a-c) < 1 and min(b,d)-1 <= y0 <= max(b,d)+1
               and abs(d-b) > 3 and min(abs(a-left), abs(a-right)) < 2
               for a,b,c,d,_ in segments):
            continue
        candidates = []
        for line in lines:
            box = fitz.Rect(line["bbox"])
            chars = [char for span in line.get("spans", []) for char in span.get("chars", [])]
            if not chars or abs(box.y1-y0) > max(2, box.height*.18):
                continue
            raw = "".join(str(char.get("c") or "") for char in chars)
            if (not re.search(r" {8,}", raw) and len(raw.split()) < 2
                    and not re.search(r"[.,;:!?]", raw)):
                continue
            if right < box.x0-3 or left > box.x1+3:
                continue
            ink = [char for char in chars if str(char.get("c") or "").strip()]
            covered = sum(max(0, min(right, char["bbox"][2])-max(left, char["bbox"][0]))
                          for char in ink)
            if covered > (right-left)*.07:
                continue
            candidates.append((abs(box.y1-y0), line, chars, raw))
        if not candidates:
            continue
        if not _painted_rule(page, left, right, y0, thickness):
            continue
        _, line, chars, raw = min(candidates, key=lambda entry: entry[0])
        insertion = next((i for i,char in enumerate(chars)
                          if str(char.get("c") or "").strip() and char["bbox"][0] >= right-1), len(chars))
        before = [char for char in chars[:insertion] if str(char.get("c") or "").strip()]
        after = [char for char in chars[insertion:] if str(char.get("c") or "").strip()]
        baselines = [span["origin"][1] for span in line.get("spans", [])
                     if span.get("origin") and str(span.get("text") or "").strip()]
        result.append({
            "line_bbox_pt": list(fitz.Rect(line["bbox"])),
            "line_text": _compact(_pdf_output_text(raw)),
            "offset_nonspace": len(_compact(_pdf_output_text(
                "".join(str(c.get("c") or "") for c in chars[:insertion])))),
            "bbox_pt": [left, y0, right, y0],
            "line_width_pt": thickness,
            "baseline_pt": median(baselines) if baselines else y0,
            "left_gap_pt": max(0, left-(before[-1]["bbox"][2] if before else fitz.Rect(line["bbox"]).x0)),
            "right_gap_pt": max(0, (after[0]["bbox"][0] if after else right)-right),
        })
    return result


def restore_answer_blanks(root, layout, page_width, char_style=None, blank_style=None):
    """Restore measured rules using native underlined whitespace runs.

Whitespace carries no new words and follows ordinary native paragraph edits.
An independent style callback creates BOTTOM/SOLID underline character styles.
"""
    from .pdf_source_line_cache import source_line_values

    blanks = layout.get("source_answer_blanks") or []
    records = (layout.get("source_typography") or {}).get("lines") or []
    if not blanks or not records or not layout.get("source_page_width_pt") or blank_style is None:
        return 0
    tables = root.findall(HP+"run/"+HP+"tbl")
    if tables:
        cells = tables[0].findall(HP+"tr/"+HP+"tc")
        if len(tables) != 1 or len(cells) != 1 or cells[0].find(".//"+HP+"tbl") is not None:
            return 0
        paragraphs = cells[0].findall(HP+"subList/"+HP+"p")
    else:
        paragraphs = [root]
    children, cursor, value = [], 0, ""
    for paragraph in paragraphs:
        for run in paragraph.findall(HP+"run"):
            for child in run:
                if child.tag == HP+"t" and not len(child):
                    text = child.text or ""
                    compact = _compact(text)
                    children.append((child, cursor, cursor+len(compact), text))
                elif child.tag == HP+"rect":
                    from .pdf_inline_labels import inline_label_text
                    text = inline_label_text(child)
                    if text is None:
                        return 0
                    compact = _compact(text)
                else:
                    return 0
                value += compact
                cursor += len(compact)
    values = source_line_values(records)
    if not all(values) or value != "".join(values):
        return 0
    plans, offsets = {}, set()
    for blank in blanks:
        owners = [i for i,record in enumerate(records)
                  if max(abs(a-b) for a,b in zip(blank["line_bbox_pt"], record["bbox_pt"])) < .05
                  and values[i] == blank["line_text"]]
        if len(owners) != 1:
            return 0
        line = owners[0]
        local = int(blank["offset_nonspace"])
        if not 0 <= local <= len(values[line]):
            return 0
        offset = sum(map(len, values[:line]))+local
        if offset in offsets:
            return 0
        offsets.add(offset)
        # Prefer the preceding text node at a boundary, so a trailing answer
        # rule remains in its own printed source line.
        owner = next((entry for entry in children if entry[1] < offset <= entry[2]), None)
        owner = owner or next((entry for entry in children if entry[1] == offset), None)
        if owner is None:
            return 0
        child, start, _, text = owner
        positions = [i for i,char in enumerate(text) if not char.isspace()]
        index = local_index = offset-start
        index = positions[local_index] if local_index < len(positions) else len(text)
        gap_start = positions[local_index-1]+1 if local_index else 0
        if text[gap_start:index].strip():
            return 0
        plans.setdefault(child, []).append((gap_start, index, {**blank, "source_line": line}))
    scale = float(page_width)/float(layout["source_page_width_pt"])
    source_height = float((layout.get("source_typography") or {}).get("font_size_pt") or 11)*scale

    def whitespace(width, underline, base):
        # The native base style uses a half-em space. Rounding its font height
        # to a native unit retains the measured length without overflowing and
        # triggering a reader's paragraph-wide compression.
        count = max(1, round(width/(source_height*.5)))
        height = max(1, round(width/count/.5))
        run = etree.Element(HP+"run", charPrIDRef=blank_style(base, height, underline=underline))
        etree.SubElement(run, HP+"t").text = " "*count
        return run

    changed_runs = set()
    for child, replacements in plans.items():
        run, source = child.getparent(), child.text or ""
        changed_runs.add(run)
        index, cursor, fragments = run.index(child), 0, []
        for start, end, blank in sorted(replacements):
            if source[cursor:start]:
                node = deepcopy(child)
                node.text = source[cursor:start]
                fragments.append(node)
            left, _, right, _ = blank["bbox_pt"]
            width = max(1, round((right-left)*scale))
            for gap, underline in ((blank["left_gap_pt"]*scale, False),
                                   (width, True), (blank["right_gap_pt"]*scale, False)):
                if gap > 0:
                    fragments.append(whitespace(gap, underline, run.get("charPrIDRef", "0")))
            cursor = end
        if source[cursor:]:
            node = deepcopy(child)
            node.text = source[cursor:]
            fragments.append(node)
        run.remove(child)
        for fragment in fragments:
            run.insert(index, fragment)
            index += 1
    # Keep each measured whitespace interval in its own native character style.
    for run in changed_runs:
        paragraph, index = run.getparent(), run.getparent().index(run)
        children = list(run)
        paragraph.remove(run)
        for child in children:
            if child.tag == HP+"run":
                fragment_run = child
            else:
                fragment_run = etree.Element(run.tag, dict(run.attrib), nsmap=run.nsmap)
                fragment_run.append(child)
            paragraph.insert(index, fragment_run)
            index += 1
    return len(blanks)
