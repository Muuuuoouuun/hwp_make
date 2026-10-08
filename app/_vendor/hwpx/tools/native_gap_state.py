"""Native ordinary-gap edit basis; local bookkeeping, never PDF permission.

Only scalar leading and a measured ordinary wrapper residual survive editing.
Old coordinates, line counts, and occupied heights are never replayed. History
detects damaged or mismatched state; it does not authenticate deliberate forgery.
"""
from copy import deepcopy
import hashlib,json,math,re
from lxml import etree
from . import general_flow_state as G
from .paragraph_spacing import paragraph_spacing
from hwpx_text_content import iter_text_parts

HP=G.HP;HH=G.HH
PART='META-INF/hwp-make-native-gaps.json'
MAX_BYTES=262144
ERRORS=(ValueError,TypeError,AttributeError,KeyError,UnicodeError,OSError,RecursionError,OverflowError)

def need(ok):
    if not ok:raise ValueError('unsupported native ordinary gap basis')

def integer(value,low=0,high=10000000):
    need(type(value) is int and low<=value<=high);return value

def number(node,name,low=0,high=10000000):
    raw=node.get(name)
    need(type(raw) is str and re.fullmatch(r'0|[1-9][0-9]{0,9}',raw) is not None)
    return integer(int(raw),low,high)

def cache_digest(p):return G._sha(G._xml(p.find(HP+'linesegarray')))

def attrs(p):
    return {k:v for k,v in p.attrib.items() if k not in ('pageBreak','columnBreak')}

def plain(p,styles):
    units=[];heights=set()
    need(list(p) and all(n.tag in (HP+'run',HP+'linesegarray') for n in p))
    for run in p.findall(HP+'run'):
        need(set(run.attrib)=={'charPrIDRef'})
        style=styles[run.get('charPrIDRef')];height=number(style,'height',1,100000)
        heights.add(height)
        for child in run:
            need(child.tag in (HP+'t',HP+'tab',HP+'lineBreak'))
            need(not child.tail)
            if child.tag==HP+'t':
                need(all(c.tag in (HP+'tab',HP+'lineBreak') for c in child.iter() if c is not child))
                parts=iter_text_parts(child)
            else:parts=[('\t' if child.tag==HP+'tab' else '\n',child)]
            for text,control in parts:
                if control is not None:
                    if control.tag==HP+'tab':
                        need(control.get('type')=='1' and control.get('leader')=='0')
                        units.append(8)
                    elif control.tag==HP+'lineBreak':units.append(1)
                    else:need(False)
                else:units.extend(len(c.encode('utf-16-le'))//2 for c in text)
    need(1<=len(units)<=100000 and heights)
    return units,max(heights)

def scalar(p,styles,paras):
    units,height=plain(p,styles)
    arrays=p.findall(HP+'linesegarray');need(len(arrays)==1)
    lines=list(arrays[0]);need(1<=len(lines)<=4096 and all(n.tag==HP+'lineseg' for n in lines))
    ends={0};total=0
    for amount in units:total+=amount;ends.add(total)
    positions=[number(n,'textpos') for n in lines]
    need(positions[0]==0 and positions==sorted(set(positions)) and positions[-1]<total
         and all(v in ends for v in positions))
    gaps=[];previous=None
    for line in lines:
        h=number(line,'vertsize',1,100000);th=number(line,'textheight',1,100000)
        baseline=number(line,'baseline');top=number(line,'vertpos');gap=number(line,'spacing',0,100000)
        need(h==th==height and 0<baseline<h and number(line,'horzsize',1)>0)
        if previous is not None:need(abs(top-previous)<=1)
        previous=top+h+gap;gaps.append(gap)
    spacing=paras[p.get('paraPrIDRef')].findall('.//'+HH+'lineSpacing')
    need(spacing and all(s.get('type')=='PERCENT' for s in spacing))
    percents=[number(s,'value',100,300) for s in spacing];need(len(set(percents))==1)
    nominal=round(height*(percents[0]-100)/100)
    nonterminal=gaps[:-1]
    need(not nonterminal or len(set(nonterminal))==1)
    leading=nonterminal[0] if nonterminal else (gaps[-1] if gaps[-1] else nominal)
    need(abs(leading-nominal)<=1 and (gaps[-1]==0 or abs(gaps[-1]-leading)<=1))
    return {'height':height,'leading':leading,'terminal':gaps[-1],'attrs':attrs(p)}

def owner_basis(top,styles,paras):
    from .question_spacing import question_host
    from .question_reflow import flow_height
    found=question_host(top);need(found is not None)
    shape,draw,line=found
    need(G.QUESTION.fullmatch(draw.get('name','')) is not None)
    # Existing unchanged table paragraphs remain bound by complete native snapshots.
    # A dirty nested table is excluded independently by general flow begin.
    need(not any(n.tag in (HP+'pic',HP+'equation',HP+'container',HP+'rect') for n in draw.iter() if n is not draw))
    subs=draw.findall(HP+'subList');need(len(subs)==1)
    sub=subs[0];paragraphs=sub.findall(HP+'p');ids=G._ids(paragraphs)
    need(list(sub)==paragraphs)
    margin=draw.find(HP+'textMargin');need(margin is not None)
    insets=[number(margin,k,0,32767) for k in ('left','right','top','bottom')]
    width=number(draw,'lastWidth',1);height=number(shape.find(HP+'sz'),'height',1)
    textheight=number(sub,'textHeight',1)
    need(abs(height-textheight-insets[2]-insets[3])<=1
         and number(line,'vertsize')==height and number(line,'textheight')==height)
    for tag in ('curSz','orgSz'):
        n=shape.find(HP+tag)
        if n is not None:need(number(n,'height',1)==height)
    scalars={}
    for p in paragraphs:
        try:scalars[p.get('id')]=scalar(p,styles,paras)
        except ERRORS:pass
    need(scalars)
    reserve=textheight-sum(flow_height(p)+sum(paragraph_spacing(p,paras)) for p in paragraphs)
    need(math.isfinite(reserve) and reserve==int(reserve) and 0<=reserve<=400)
    return {'name':draw.get('name'),'ids':ids,'reserve':int(reserve),'width':width,
            'horizontal_insets':insets[:2],'paragraphs':scalars}

def current(document):
    result={}
    for section in document.sections:
        root=section.element;paragraphs=list(root.iter(HP+'p'));top=root.findall(HP+'p')
        ids=G._ids(paragraphs);G._ids(top)
        result[section.part_name]={'ids':ids,'top_ids':[p.get('id') for p in top],
            'config':G._column_config(root),'styles':G._style_binding(document,root),
            'flags':G._flags(paragraphs),'fingerprints':[G._fingerprint(p) for p in paragraphs],
            'caches':[cache_digest(p) for p in paragraphs]}
    return result

def load(document):
    raw=document.package.read(PART);need(1<=len(raw)<=MAX_BYTES)
    value=json.loads(raw,object_pairs_hook=G._object)
    need(type(value) is dict and set(value)=={'v','binding','last','basis','digest'}
         and type(value['v']) is int and value['v']==1)
    payload={k:v for k,v in value.items() if k!='digest'}
    need(value['digest']==G._sha(G._json(payload)))
    need(type(value['basis']) is dict and type(value['last']) is dict)
    need(set(value['basis'])<=set(value['last']) and 1<=len(value['last'])<=64)
    for name,groups in value['basis'].items():
        need(type(groups) is dict and len(groups)<=512)
        for host,b in groups.items():
            need(type(host) is str and type(b) is dict and set(b)=={'name','ids','reserve','width','horizontal_insets','paragraphs'})
            need(type(b['name']) is str and G.QUESTION.fullmatch(b['name']) is not None)
            integer(b['reserve'],0,400);integer(b['width'],1)
            need(type(b['horizontal_insets']) is list and len(b['horizontal_insets'])==2)
            for x in b['horizontal_insets']:integer(x,0,32767)
            need(type(b['ids']) is list and len(b['ids'])==len(set(b['ids'])) and 1<=len(b['ids'])<=4096
                 and type(b['paragraphs']) is dict and 1<=len(b['paragraphs'])<=len(b['ids'])
                 and set(b['paragraphs'])<=set(b['ids']))
            for identifier,s in b['paragraphs'].items():
                need(type(identifier) is str and type(s) is dict and set(s)=={'height','leading','terminal','attrs'})
                integer(s['height'],1,100000);integer(s['leading'],0,100000);integer(s['terminal'],0,100000)
                need(type(s['attrs']) is dict and all(type(k) is str and type(v) is str for k,v in s['attrs'].items()))
    return value

def capture_open(document):
    """Read-only, before a setter can erase the native cache and gap evidence."""
    document._native_gap_basis=None
    try:
        now=current(document);binding=G._document_binding(document)
        if document.package.has_part(PART):
            value=load(document)
            need(value['binding']==binding and value['last']==now)
        else:
            # Legacy break history may already have consumed gaps. Never guess.
            need(not document.package.has_part(G.PART))
            header=document.headers[0].element
            styles={p.get('id'):p for p in header.iter(HH+'charPr')}
            paras={p.get('id'):p for p in header.iter(HH+'paraPr')}
            basis={}
            for section in document.sections:
                groups={}
                for top in section.element.findall(HP+'p'):
                    try:groups[top.get('id')]=owner_basis(top,styles,paras)
                    except ERRORS:pass
                if groups:basis[section.part_name]=groups
            need(basis)
            value={'v':1,'binding':binding,'last':now,'basis':basis}
        document._native_gap_basis=deepcopy(value)
    except ERRORS:pass

def begin(document,section,general_context):
    try:
        need(general_context is not None)
        value=document._native_gap_basis;need(type(value) is dict)
        if document.package.has_part(PART):need(load(document)==value)
        else:need('digest' not in value)
        need(value['binding']==G._document_binding(document))
        old=value['last'][section.part_name];root=section.element;paragraphs=list(root.iter(HP+'p'))
        need(old['ids']==G._ids(paragraphs) and old['top_ids']==G._ids(root.findall(HP+'p'))
             and old['config']==G._column_config(root) and old['styles']==G._style_binding(document,root)
             and old['flags']==G._flags(paragraphs))
        dirty=[p for p in paragraphs if p.find(HP+'linesegarray') is None]
        need(1<=len(dirty)<=64)
        for p,fp,cache in zip(paragraphs,old['fingerprints'],old['caches']):
            if p not in dirty:need(G._fingerprint(p)==fp and cache_digest(p)==cache)
        header=document.headers[0].element;styles={p.get('id'):p for p in header.iter(HH+'charPr')}
        paras={p.get('id'):p for p in header.iter(HH+'paraPr')}
        groups=value['basis'][section.part_name];policies={};reserves={}
        for p in dirty:
            owners=[a for a in p.iterancestors() if a.tag==HP+'drawText']
            need(len(owners)==1);draw=owners[0];host=draw.getparent().getparent().getparent()
            need(host.tag==HP+'p' and host.getparent() is root)
            b=groups[host.get('id')]
            need(draw.get('name')==b['name'] and number(draw,'lastWidth',1)==b['width']
                 and G._ids(draw.find(HP+'subList').findall(HP+'p'))==b['ids'])
            s=b['paragraphs'][p.get('id')]
            need(attrs(p)==s['attrs'] and plain(p,styles)[1]==s['height'])
            spacings=paras[p.get('paraPrIDRef')].findall('.//'+HH+'lineSpacing')
            need(spacings and all(n.get('type')=='PERCENT' for n in spacings))
            percents=[number(n,'value',100,300) for n in spacings]
            need(len(set(percents))==1 and abs(s['leading']-round(s['height']*(percents[0]-100)/100))<=1
                 and (s['terminal']==0 or abs(s['terminal']-s['leading'])<=1))
            policies[p]=s;reserves[draw]=b['reserve']
        return {'section':section,'policies':policies,'reserves':reserves,'basis':value}
    except ERRORS:return None

def policy(context,p):return context['policies'].get(p) if context is not None else None

def step(height,default_step,index,count,leading):
    if leading is None:return default_step
    if height!=leading['height']:return default_step
    gap=leading['terminal'] if index==count-1 else leading['leading']
    return height+gap

def commit(document,contexts,general_committed):
    try:
        need(general_committed and contexts)
        value=deepcopy(document._native_gap_basis);need(type(value) is dict)
        need(all(c['basis'] is document._native_gap_basis for c in contexts))
        value.pop('digest',None);value['last']=current(document);value['binding']=G._document_binding(document)
        value['digest']=G._sha(G._json(value));raw=G._json(value);need(len(raw)<=MAX_BYTES)
        document.package.write(PART,raw);document._native_gap_basis=value
        return True
    except ERRORS:return False
