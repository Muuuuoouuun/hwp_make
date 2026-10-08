"""Native square-wrapped pictures anchored to an editable paragraph."""
import math
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
WRAPPED_CELL = 'source-prose-frame:wrapped:v1'


def is_wrapped_picture(node):
    pos = node.find(HP + "pos")
    return (node.tag == HP + "pic" and node.get("textWrap") == "SQUARE"
            and pos is not None and pos.get("treatAsChar") == "0"
            and pos.get("flowWithText") == "1" and pos.get("vertRelTo") == "PARA"
            and pos.get("horzRelTo") in {"PARA", "COLUMN"})


def available_interval(paragraph, width, top, height, *, exclusions=None):
    intervals = [(0.0, float(width))]
    rectangles = list(exclusions) if exclusions is not None else []
    if exclusions is None:
      for run in paragraph.findall(HP + "run"):
        for picture in run:
            if not is_wrapped_picture(picture):
                continue
            pos, size, margin = (picture.find(HP + tag) for tag in ("pos", "sz", "outMargin"))
            def number(node, key):
                return float(node.get(key, 0)) if node is not None else 0
            x, y = number(pos, "horzOffset"), number(pos, "vertOffset")
            end = x + number(size, "width") + number(margin, "right")
            x -= number(margin, "left")
            bottom = y + number(size, "height") + number(margin, "bottom")
            y -= number(margin, "top")
            rectangles.append((x,y,end,bottom))
    for x,y,end,bottom in rectangles:
        if min(top + height, bottom) <= max(top, y):
            continue
        remaining = []
        for left, right in intervals:
            if end <= left or x >= right:
                remaining.append((left, right))
            else:
                if x > left:
                    remaining.append((left, min(x, right)))
                if end < right:
                    remaining.append((max(end, left), right))
        intervals = remaining
    if not intervals:
        raise ValueError("Floating picture leaves no horizontal interval for editable text")
    left, right = max(intervals, key=lambda interval: interval[1] - interval[0])
    return left, right - left


def wrapped_cell_layout(cell, para_styles, *, allow_missing=False, char_styles=None):
    """Validate an opted-in single cell's native Square flow, never a flag alone.

    Initial source text/rules/pixels are independently proved by the importer
    and editability audit. This portable save check needs no external PDF.
    It proves the remaining native ownership, controls and occupied bands.
    """
    from .paragraph_spacing import paragraph_spacing, paragraph_indentation, line_left_margin
    try:
        name=cell.get('name','')
        if (not (name == WRAPPED_CELL or name.startswith(WRAPPED_CELL+':flow:'))
            or len(name)>65536 or cell.get('hasMargin') != '1' or cell.get('protect') == '1'): return None
        table=cell.getparent().getparent()
        if (table.tag != HP+'tbl' or table.get('rowCnt') != '1' or table.get('colCnt') != '1'
            or table.get('textWrap') != 'TOP_AND_BOTTOM' or len(table.findall(HP+'tr/'+HP+'tc')) != 1): return None
        pos=table.find(HP+'pos')
        if any(pos.get(k) != v for k,v in (('treatAsChar','0'),('flowWithText','1'),('allowOverlap','0'),
            ('vertRelTo','PARA'),('horzRelTo','COLUMN'),('vertOffset','0'))): return None
        def number(node,key):
            value=float(node.get(key))
            if not math.isfinite(value): raise ValueError('nonfinite wrapped cell')
            return value
        address,span=cell.find(HP+'cellAddr'),cell.find(HP+'cellSpan')
        if (any(number(address,key)!=0 for key in ('rowAddr','colAddr'))
            or any(number(span,key)!=1 for key in ('rowSpan','colSpan'))): return None
        size,margin=cell.find(HP+'cellSz'),cell.find(HP+'cellMargin')
        width,height=number(size,'width'),number(size,'height')
        ml,mr,mt,mb=(number(margin,k) for k in ('left','right','top','bottom'))
        if min(width,height)<=0 or min(ml,mr,mt,mb)<0 or ml+mr>=width: return None
        if abs(number(table.find(HP+'sz'),'width')-width)>2: return None
        header=next(iter(para_styles.values())).getroottree().getroot()
        fill=next((f for f in header.iter(HH+'borderFill') if f.get('id')==cell.get('borderFillIDRef')),None)
        if fill is None or any(fill.find(HH+edge+'Border').get('type') == 'NONE' for edge in ('left','right','top','bottom')): return None
        if char_styles is None: char_styles={c.get('id'):c for c in header.iter(HH+'charPr')}
        paragraphs=cell.findall(HP+'subList/'+HP+'p')
        if len(paragraphs)<2: return None
        floats=[]; cursor=0; starts=[]; count=0
        for paragraph in paragraphs:
            lines=paragraph.findall(HP+'linesegarray/'+HP+'lineseg')
            style=para_styles.get(paragraph.get('paraPrIDRef'))
            if style is None: return None
            for values in style.findall('.//'+HH+'margin'):
                for value in values:
                    if not math.isfinite(float(value.get('value'))): return None
            before,after=paragraph_spacing(paragraph,para_styles)
            margin_left,margin_right,indent=paragraph_indentation(paragraph,para_styles)
            if not all(math.isfinite(v) and v>=0 for v in (before,after)): return None
            cursor+=before; starts.append(cursor)
            text=''; controls=0
            for run in paragraph.findall(HP+'run'):
                style=char_styles.get(run.get('charPrIDRef'))
                underline=style.find(HH+'underline') if style is not None else None
                for child in run:
                    if child.tag==HP+'t' and not len(child):
                        value=child.text or ''
                        if value and value.isspace() and underline is not None and underline.get('type')=='BOTTOM': return None
                        text+=value
                    elif is_wrapped_picture(child):
                        p,s,m=(child.find(HP+k) for k in ('pos','sz','outMargin'))
                        if (p.get('allowOverlap')!='0' or p.get('vertAlign')!='TOP' or p.get('horzAlign')!='LEFT'
                            or child.find(HP+'drawText') is not None): return None
                        x,y,w,h=(number(p,'horzOffset'),number(p,'vertOffset'),number(s,'width'),number(s,'height'))
                        gaps=[number(m,k) for k in ('left','right','top','bottom')]
                        if (min(x,y,w,h)<0 or min(w,h)<=0 or min(gaps)<0
                            or x-gaps[0]<0 or y-gaps[2]<0
                            or x+w+gaps[1]>width-ml-mr+2): return None
                        anchor=number(lines[0],'vertpos') if allow_missing and lines else cursor
                        floats.append((x-gaps[0],anchor+y-gaps[2],x+w+gaps[1],anchor+y+h+gaps[3]))
                        controls+=8; count+=1
                    else: return None
            if not text.strip(): return None
            if not lines:
                if not allow_missing: return None
                continue
            previous=-1
            local=0
            for index,line in enumerate(lines):
                values=[number(line,k) for k in ('textpos','vertpos','vertsize','textheight','baseline','spacing','horzpos','horzsize')]
                offset,y,h,th,baseline,spacing,x,w=values
                if (offset!=round(offset) or (previous<0 and offset!=0)
                    or not previous<offset<=len(text.encode('utf-16-le'))/2+controls
                    or min(offset,y,spacing,x)<0 or not 0<baseline<th<=h or w<=0 or x+w>width-ml-mr+2): return None
                if mt+y+h>height+2 or mt+cursor+h>height+2: return None
                left,available=available_interval(paragraph,width-ml-mr,y if allow_missing else cursor,h,exclusions=floats)
                effective=available-line_left_margin(margin_left,indent,index)-margin_right
                if effective<=0 or x<left-2 or x+w>left+effective+2: return None
                previous=offset; cursor+=h+spacing
            cursor+=after
        if count!=1 or not floats: return None
        occupied=max([cursor]+[r[3] for r in floats])
        if not allow_missing and mt+occupied+mb>height+2: return None
        return {'paragraphs':paragraphs,'floats':floats,'starts':starts,'width':width-ml-mr,
                'top':mt,'bottom':mb,'height':mt+occupied+mb}
    except (AttributeError, ValueError, TypeError, KeyError, IndexError, StopIteration):
        return None
