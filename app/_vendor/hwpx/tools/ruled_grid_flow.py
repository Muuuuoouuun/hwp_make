"""Reflow proved native plain grids using bounded original row reserves.

Cache snapshots are editing data, never source provenance. The importer seeds
only after actual PDF/rule/text/pixel proof; each save independently validates
native cells, styles, padding, complete UTF-16 slices and supported font widths.
"""
from copy import deepcopy
import base64
import hashlib
import json
import math
from lxml import etree
from .paragraph_spacing import paragraph_spacing,paragraph_indentation

HP='{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HH='{http://www.hancom.co.kr/hwpml/2011/head}'
HC='{http://www.hancom.co.kr/hwpml/2011/core}'
PREFIX='source-ruled-grid-frame:v1:cache:'
LINE_KEYS=('textpos','vertpos','vertsize','textheight','baseline','spacing','horzpos','horzsize','flags')
# rhwp-core ce45231c FONT_20/FONT_22_LATIN_0, 2048 units/em.
NORMAL=(512, 682, 836, 1024, 1024, 1706, 1593, 369, 682, 682, 1024, 1155, 512, 682, 512, 569, 1024, 1024, 1024, 1024, 1024, 1024, 1024, 1024, 1024, 1024, 569, 569, 1155, 1155, 1155, 909, 1886, 1479, 1366, 1366, 1479, 1251, 1139, 1479, 1479, 682, 797, 1479, 1251, 1821, 1479, 1479, 1139, 1479, 1366, 1139, 1251, 1479, 1479, 1933, 1479, 1479, 1251, 682, 569, 682, 961, 1024, 682, 909, 1024, 909, 1024, 909, 682, 1024, 1024, 569, 569, 1024, 569, 1593, 1024, 1024, 1024, 1024, 682, 797, 569, 1024, 1024, 1479, 1024, 1024, 909, 983, 410, 983, 1108)
BOLD=(512, 682, 1137, 1024, 1024, 2048, 1706, 569, 682, 682, 1024, 1167, 512, 682, 512, 569, 1024, 1024, 1024, 1024, 1024, 1024, 1024, 1024, 1024, 1024, 682, 682, 1167, 1167, 1167, 1024, 1905, 1479, 1366, 1479, 1479, 1366, 1251, 1593, 1593, 797, 1024, 1593, 1366, 1933, 1479, 1593, 1251, 1593, 1479, 1139, 1366, 1479, 1479, 2048, 1479, 1479, 1366, 682, 569, 682, 1190, 1024, 682, 1024, 1139, 909, 1139, 909, 682, 1024, 1139, 569, 682, 1139, 569, 1706, 1139, 1024, 1139, 1139, 909, 797, 682, 1139, 1024, 1479, 1024, 1024, 909, 807, 451, 807, 1065)


def integer(value):
    n=float(value)
    if not math.isfinite(n) or n!=round(n):raise ValueError('nonintegral grid metric')
    return int(n)


def digest(value):return hashlib.sha256(json.dumps(value,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()


def xml(element):
    if element is None:raise ValueError('missing native grid style')
    node=deepcopy(element);node.attrib.pop('id',None)
    return etree.tostring(node,method='c14n',exclusive=True).decode()


def encode(state):
    raw=json.dumps(state,separators=(',',':'),ensure_ascii=True).encode()
    if len(raw)>65536:raise ValueError('oversized grid state')
    return PREFIX+hashlib.sha256(raw).hexdigest()+':'+base64.urlsafe_b64encode(raw).decode()


def decode(name):
    if not name.startswith(PREFIX) or len(name)>90000:raise ValueError('invalid grid state')
    checksum,payload=name[len(PREFIX):].split(':',1)
    raw=base64.b64decode(payload,altchars=b'-_',validate=True)
    if len(raw)>65536 or hashlib.sha256(raw).hexdigest()!=checksum:raise ValueError('damaged grid state')
    state=json.loads(raw)
    if not isinstance(state,dict) or set(state)!={'v','geometry','cells','ids','base','last'} or state['v']!=1:raise ValueError('invalid grid schema')
    if (not isinstance(state['ids'],list) or not 1<=len(state['ids'])<=512
        or len(set(state['ids']))!=len(state['ids']) or any(not isinstance(i,str) or not i for i in state['ids'])):raise ValueError('invalid grid paragraph IDs')
    for k in ('base','last'):
        if len(state[k])!=len(state['ids']) or any(not isinstance(pair,list) or len(pair)!=2 or pair not in (["0","0"],["1","0"],["0","1"]) for pair in state[k]):raise ValueError('invalid grid break flags')
    return state


def flags(root):return [[p.get('pageBreak','0'),p.get('columnBreak','0')] for p in root.findall(HP+'p')]


def metrics(paragraph,para_styles,char_styles):
    style=para_styles.get(paragraph.get('paraPrIDRef'))
    if (style is None or any(paragraph_spacing(paragraph,para_styles)) or any(paragraph_indentation(paragraph,para_styles))
        or style.find(HH+'align').get('horizontal') not in ('LEFT','CENTER')):raise ValueError('unsupported grid paragraph')
    if any(c.tag not in (HP+'run',HP+'linesegarray') for c in paragraph):raise ValueError('unknown grid paragraph control')
    header=style.getroottree().getroot();fonts={(f.get('lang'),n.get('id')):n.get('face') for f in header.iter(HH+'fontface') for n in f.findall(HH+'font')}
    chars=[];signature=[]
    for run in paragraph.findall(HP+'run'):
        if any(c.tag!=HP+'t' or len(c) for c in run):raise ValueError('unknown grid text control')
        text=''.join(t.text or '' for t in run.findall(HP+'t'))
        char=char_styles.get(run.get('charPrIDRef'))
        if char is None:raise ValueError('missing grid font')
        refs=char.find(HH+'fontRef');ratio=char.find(HH+'ratio');spacing=char.find(HH+'spacing')
        langs={'hangul','latin','hanja','japanese','other','symbol','user'}
        if (refs is None or set(refs.attrib)!=langs or any(fonts.get((lang.upper(),ref))!='Times New Roman' for lang,ref in refs.attrib.items())
            or ratio is None or spacing is None or set(ratio.attrib)!=langs or set(spacing.attrib)!=langs
            or len(set(ratio.attrib.values()))!=1 or len(set(spacing.attrib.values()))!=1
            or any(char.find(HH+tag) is not None for tag in ('italic','supscript','subscript','strikeout','emboss','engrave'))
            or any(n.get('type','NONE')!='NONE' for tag in ('underline','outline','shadow') for n in char.findall(HH+tag))):raise ValueError('unsupported grid font metrics')
        size=integer(char.get('height'));rat=integer(ratio.get('latin'));tracking=integer(spacing.get('latin'))
        if not 0<size<=10000 or not 0<rat<=200 or not -100<tracking<100:raise ValueError('invalid grid font metrics')
        widths=BOLD if char.find(HH+'bold') is not None else NORMAL
        signature.append(digest(xml(char)))
        for c in text:
            if not 32<=ord(c)<=126:raise ValueError('unsupported grid glyph')
            natural=(math.floor(size/2) if c==' ' else math.floor(widths[ord(c)-32]*size/2048))*rat/100
            advance=max(natural+tracking*size/100,natural*.5)
            chars.append((c,advance,size))
    return chars,[digest(xml(style)),signature]


def native_font_height(paragraph,char_styles):
    # The current native resolver uses charPr.height (base_size), including
    # a styled empty run after public deletion. Runless decoration gutters
    # are deliberately one-unit empty caches, with no implicit font.
    return max((integer(char_styles[run.get('charPrIDRef')].get('height'))
                for run in paragraph.findall(HP+'run')),default=1)


def canonical_source_line(paragraph,char_styles,cache,width):
    height=native_font_height(paragraph,char_styles)
    return (len(cache)==1 and cache[0][:8]==[0,0,height,height,round(height*.85),0,0,width])


def lines(paragraph):
    values=[[integer(n.get(k)) for k in LINE_KEYS] for n in paragraph.findall(HP+'linesegarray/'+HP+'lineseg')]
    if not values or values[0][0]!=0:raise ValueError('incomplete grid cache')
    previous=-1
    for v in values:
        if (len(v)!=9 or any(n<0 or n>2147483647 for n in v) or v[0]<=previous
            or not 0<v[4]<=v[3]<=v[2] or v[7]<=0):raise ValueError('invalid grid cache')
        previous=v[0]
    return values


def fit(chars,cache,width):
    # Supported glyphs are ASCII: code-point and UTF-16 boundaries coincide.
    if not chars:return len(cache)==1 and cache[0][0]==0
    starts=[line[0] for line in cache]
    if starts[0]!=0 or any(a>=len(chars) for a in starts):return False
    for i,(start,stop) in enumerate(zip(starts,starts[1:]+[len(chars)])):
        part=chars[start:stop]
        advance=sum(c[1] for c in part)
        painted_width=math.floor(advance/75+.5)*75  # 96dpi, 7200 HWP units/inch
        if (not part or max(advance,painted_width)>width or max(c[2] for c in part)>cache[i][3]
            or cache[i][6]!=0 or cache[i][7]!=width):return False
    return True


def geometry(table,header):
    nr,nc=integer(table.get('rowCnt')),integer(table.get('colCnt'))
    if not 2<=nr<=32 or not 2<=nc<=16 or table.get('textWrap')!='TOP_AND_BOTTOM' or table.get('lock')!='0':raise ValueError('unsupported native grid')
    if any(etree.QName(c).localname not in ('sz','pos','outMargin','inMargin','tr','shapeComment') for c in table):raise ValueError('unknown grid control')
    pos=table.find(HP+'pos')
    if any(pos.get(k)!=v for k,v in (('treatAsChar','0'),('flowWithText','1'),('allowOverlap','0'),('vertRelTo','PARA'),('horzRelTo','COLUMN'),('vertOffset','0'),('horzAlign','LEFT'),('vertAlign','TOP'))):raise ValueError('invalid grid flow')
    if integer(pos.get('horzOffset'))<0:raise ValueError('negative grid offset')
    fills={f.get('id'):f for f in header.iter(HH+'borderFill')};fill=fills[table.get('borderFillIDRef')]
    brush=fill.find(HC+'fillBrush/'+HC+'imgBrush')
    if brush is None or brush.get('mode')!='TOTAL':raise ValueError('missing grid background')
    image=brush.find(HC+'img')
    if (image is None or any(image.get(k)!=v for k,v in (('bright','0'),('contrast','0'),('effect','REAL_PIC'),('alpha','0')))
        or any(fill.find(HH+edge+'Border').get('type')!='NONE' for edge in ('left','right','top','bottom'))):raise ValueError('unsupported grid background')
    cells=table.findall(HP+'tr/'+HP+'tc')
    if len(cells)!=nr*nc:raise ValueError('incomplete native grid')
    widths=[];heights=[];base_heights=[];shape=[]
    for i,cell in enumerate(cells):
        r,c=divmod(i,nc);addr=cell.find(HP+'cellAddr');span=cell.find(HP+'cellSpan');sz=cell.find(HP+'cellSz');sub=cell.find(HP+'subList')
        if (integer(addr.get('rowAddr'))!=r or integer(addr.get('colAddr'))!=c or integer(span.get('rowSpan'))!=1 or integer(span.get('colSpan'))!=1
            or cell.get('protect')!='0' or sub.get('textDirection')!='HORIZONTAL' or sub.get('vertAlign')!='TOP'
            or len(sub)!=1 or sub[0].tag!=HP+'p'
            or any(integer(cell.find(HP+'cellMargin').get(k))!=0 for k in ('left','right','bottom'))
            or integer(cell.find(HP+'cellMargin').get('top'))<0):raise ValueError('invalid native grid cell')
        width,height=integer(sz.get('width')),integer(sz.get('height'))
        if min(width,height)<=0:raise ValueError('invalid native grid size')
        if r==0:widths.append(width)
        elif widths[c]!=width:raise ValueError('inconsistent native grid widths')
        if c==0:heights.append(height);base_heights.append(height)
        else:heights[r]=max(heights[r],height)
        border=fills[cell.get('borderFillIDRef')]
        if border.find(HC+'fillBrush') is not None:raise ValueError('unexpected grid cell fill')
        edges=[border.find(HH+e+'Border').get('type') for e in ('left','right','top','bottom')]
        if len(set(edges))!=1 or edges[0] not in ('NONE','SOLID'):raise ValueError('partial grid borders')
        if edges[0]=='SOLID' and any(border.find(HH+e+'Border').get('color')!='#000000' for e in ('left','right','top','bottom')):raise ValueError('unsupported grid rule')
        shape.append([sub[0].get('id'),edges[0],width,dict(cell.find(HP+'cellMargin').attrib)])
    real=[divmod(i,nc) for i,s in enumerate(shape) if s[1]=='SOLID']
    if not real:raise ValueError('missing source grid cells')
    r0,c0=min(r for r,c in real),min(c for r,c in real);r1,c1=max(r for r,c in real)+1,max(c for r,c in real)+1
    if r1-r0<2 or c1-c0<2 or set(real)!={(r,c) for r in range(r0,r1) for c in range(c0,c1)}:raise ValueError('nonrectangular source grid')
    if c0==0 or c1==nc or any(shape[r*nc][1]!='NONE' or shape[r*nc+nc-1][1]!='NONE' for r in range(nr)):raise ValueError('missing native side gutters')
    if any(cell.find(HP+'subList/'+HP+'p').find(HP+'run') is not None
           for cell,entry in zip(cells,shape) if entry[1]=='NONE'):raise ValueError('nonempty native grid gutter')
    if any(integer(cells[r*nc+nc-1].find(HP+'cellSz').get('height'))!=base_heights[r] for r in range(nr)):raise ValueError('inconsistent native side gutters')
    if integer(table.find(HP+'sz').get('width'))!=sum(widths) or integer(table.find(HP+'sz').get('height'))!=sum(heights):raise ValueError('inconsistent native table size')
    if any(integer(table.find(HP+tag).get(k))!=0 for tag in ('outMargin','inMargin') for k in ('left','right','top','bottom')):raise ValueError('unknown grid margin')
    return [nr,nc,widths,dict(pos.attrib),xml(fill),shape,base_heights],heights,cells


def seed(table,root,header):
    try:
        para={p.get('id'):p for p in header.iter(HH+'paraPr')};char={p.get('id'):p for p in header.iter(HH+'charPr')}
        native,heights,cells=geometry(table,header);records=[]
        for cell in cells:
            p=cell.find(HP+'subList/'+HP+'p');units,signature=metrics(p,para,char);cache=lines(p)
            width=integer(cell.find(HP+'cellSz').get('width'))
            if not canonical_source_line(p,char,cache,width) or not fit(units,cache,width):return False
            end=integer(cell.find(HP+'cellMargin').get('top'))+cache[-1][1]+cache[-1][2]+cache[-1][5]
            reserve=integer(cell.find(HP+'cellSz').get('height'))-end
            if not 0<=reserve<=10000:return False
            records.append([p.get('id'),signature,cache,reserve])
        state={'v':1,'geometry':native,'cells':records,'ids':[p.get('id') for p in root.findall(HP+'p')],'base':flags(root),'last':flags(root)}
        table.set('name',encode(state));return True
    except (AttributeError,ValueError,TypeError,KeyError,IndexError):return False


def prepare(table,header,para,char):
    state=decode(table.get('name',''));native,heights,cells=geometry(table,header)
    baseline_geometry=state['geometry']
    if (not isinstance(baseline_geometry,list) or len(baseline_geometry)!=7
        or native[:6]!=baseline_geometry[:6] or len(state['cells'])!=len(cells)
        or len(baseline_geometry[6])!=native[0]
        or any(type(v)!=int or v<=0 for v in baseline_geometry[6])
        or any(a<b for a,b in zip(heights,baseline_geometry[6]))):raise ValueError('mutated grid geometry')
    staged=deepcopy(table);newcells=staged.findall(HP+'tr/'+HP+'tc');newheights=[0]*native[0]
    for i,(cell,record) in enumerate(zip(newcells,state['cells'])):
        p=cell.find(HP+'subList/'+HP+'p');units,signature=metrics(p,para,char)
        if not isinstance(record,list) or len(record)!=4 or p.get('id')!=record[0] or signature!=record[1]:raise ValueError('mutated grid styles')
        baseline=record[2]
        if (not isinstance(baseline,list) or not baseline or any(not isinstance(v,list) or len(v)!=9 or any(type(n)!=int for n in v) for v in baseline)
            or type(record[3])!=int or not 0<=record[3]<=10000):raise ValueError('invalid grid cache state')
        probe=deepcopy(p);old=probe.find(HP+'linesegarray')
        if old is not None:probe.remove(old)
        array=etree.SubElement(probe,HP+'linesegarray')
        for values in baseline:etree.SubElement(array,HP+'lineseg',**{k:str(v) for k,v in zip(LINE_KEYS,values)})
        lines(probe)
        width=integer(cell.find(HP+'cellSz').get('width'))
        # Original source plain grids have exactly one line per cell. Changed
        # text may reuse its baseline only when every actual supported glyph
        # still fits that real cell, with unchanged native styles/padding.
        if len(baseline)!=1:raise ValueError('unsupported grid source cache')
        native_top=integer(cell.find(HP+'cellMargin').get('top'))
        if not canonical_source_line(p,char,baseline,width):
            raise ValueError('noncanonical source grid line')
        if native_top+baseline[0][2]+record[3]!=baseline_geometry[6][i//native[1]]:
            raise ValueError('inconsistent original grid row reserve')
        if fit(units,baseline,width):newcache=baseline
        else:
            if not units:raise ValueError('empty invalid grid cache')
            height=max(u[2] for u in units);top=baseline[0][1];base=baseline[0][4]
            if height!=baseline[0][3]:raise ValueError('mutated grid font height')
            line_style=para[p.get('paraPrIDRef')].find('.//'+HH+'lineSpacing')
            if line_style is None or line_style.get('type')!='PERCENT':raise ValueError('unknown grid line spacing')
            step=max(height,round(height*integer(line_style.get('value'))/100));newcache=[];start=0
            while start<len(units):
                end=start;amount=0;space=None
                while end<len(units) and amount+units[end][1]<=width-38:
                    amount+=units[end][1]
                    if units[end][0]==' ':space=end+1
                    end+=1
                if end==start:raise ValueError('unbreakable grid glyph')
                if end<len(units) and space is not None and space>start:end=space
                newcache.append([start,top,height,height,base,step-height,0,width,baseline[0][8]])
                start=end;top+=step
            newcache[-1][5]=0
            if not fit(units,newcache,width):raise ValueError('grid edit does not fit')
        old=p.find(HP+'linesegarray')
        if old is not None and lines(p)!=newcache:raise ValueError('mutated current grid cache')
        if old is not None:p.remove(old)
        array=etree.SubElement(p,HP+'linesegarray')
        for values in newcache:etree.SubElement(array,HP+'lineseg',**{k:str(v) for k,v in zip(LINE_KEYS,values)})
        required=native_top+newcache[-1][1]+newcache[-1][2]+newcache[-1][5]+record[3]
        newheights[i//native[1]]=max(newheights[i//native[1]],required)
    for i,cell in enumerate(newcells):
        height=(baseline_geometry[6][i//native[1]] if native[5][i][1]=='NONE' else newheights[i//native[1]])
        cell.find(HP+'cellSz').set('height',str(height))
    staged.find(HP+'sz').set('height',str(sum(newheights)))
    return staged,state


def begin(root,para,char):
    try:
        header=next(iter(para.values())).getroottree().getroot()
        dirty=[p for p in root.iter(HP+'p') if p.find(HP+'linesegarray') is None and
               (any((t.text or '').strip() for t in p.iter(HP+'t')) or any(c.tag!=HP+'t' for r in p.findall(HP+'run') for c in r)
                or any(a.tag==HP+'tbl' and a.get('name','').startswith(PREFIX) for a in p.iterancestors()))]
        if not dirty:return None
        tables=[];plans={};states=[]
        for p in dirty:
            table=next((a for a in p.iterancestors() if a.tag==HP+'tbl'),None)
            if table is None:return None
            if table not in tables:
                staged,state=prepare(table,header,para,char);tables.append(table);plans[table]=staged;states.append(state)
        ids=[p.get('id') for p in root.findall(HP+'p')]
        if any(s['ids']!=ids or s['base']!=states[0]['base'] or s['last']!=states[0]['last'] for s in states):return None
        current=flags(root);base=[now if now!=old else original for now,old,original in zip(current,states[0]['last'],states[0]['base'])]
        slots={};slot=0
        for p,(page,col) in zip(root.findall(HP+'p'),base):
            if page=='1':slot+=2-slot%2
            elif col=='1':slot+=1
            slots[p]=slot
        return {'plans':plans,'dirty':set(dirty),'slots':slots,'base':base,'ids':ids}
    except (AttributeError,ValueError,TypeError,KeyError,IndexError,UnicodeError,StopIteration):return None


def apply(table,context):
    if context is None or table not in context['plans']:return False
    staged=context['plans'][table]
    table.attrib.clear();table.attrib.update(staged.attrib)
    for child in list(table):table.remove(child)
    table.extend(staged)
    owner=table.getparent().getparent();height=integer(table.find(HP+'sz').get('height'))+400
    cache=owner.find(HP+'linesegarray')
    if cache is None:cache=etree.SubElement(owner,HP+'linesegarray')
    for child in list(cache):cache.remove(child)
    etree.SubElement(cache,HP+'lineseg',textpos='0',vertpos='0',vertsize=str(height),textheight=str(height),baseline=str(round(height*.85)),spacing='0',horzpos='0',horzsize=table.find(HP+'sz').get('width'),flags='393216')
    return True


def preserve_positions(container,para):
    try:
        cell=container.getparent();table=cell.getparent().getparent()
        state=decode(table.get('name',''));header=next(iter(para.values())).getroottree().getroot();char={s.get('id'):s for s in header.iter(HH+'charPr')}
        prepared,_=prepare(table,header,para,char)
        target=next(c for c in prepared.findall(HP+'tr/'+HP+'tc') if c.find(HP+'subList/'+HP+'p').get('id')==container[0].get('id'))
        if etree.tostring(target.find(HP+'subList'),method='c14n',exclusive=True)!=etree.tostring(container,method='c14n',exclusive=True):return None
        return integer(cell.find(HP+'cellSz').get('height'))
    except (AttributeError,ValueError,TypeError,KeyError,IndexError,UnicodeError,StopIteration):return None


def finish(root,context):
    if context is None:return
    for table in root.iter(HP+'tbl'):
        try:
            state=decode(table.get('name',''))
            if state['ids']!=context['ids']:continue
            state['base']=context['base'];state['last']=flags(root);table.set('name',encode(state))
        except (ValueError,TypeError,KeyError,IndexError):continue
