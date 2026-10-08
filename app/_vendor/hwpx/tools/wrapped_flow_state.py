"""Portable break bookkeeping for independently validated wrapped-cell edits.

The native cell name is an editing hint, never provenance or eligibility.
Every caller first proves the complete native wrapped-cell structure.
"""
import base64
import hashlib
import json
import math

from lxml import etree

from .paragraph_floats import HP, WRAPPED_CELL, wrapped_cell_layout

PREFIX = WRAPPED_CELL + ':flow:'
HH='{http://www.hancom.co.kr/hwpml/2011/head}'
LINE_KEYS=('textpos','vertpos','vertsize','textheight','baseline','spacing','horzpos','horzsize','flags')


def encode(state):
    raw=json.dumps(state,separators=(',',':'),ensure_ascii=True).encode('ascii')
    if len(raw)>32768: raise ValueError('oversized native wrap state')
    return PREFIX+hashlib.sha256(raw).hexdigest()+':'+base64.urlsafe_b64encode(raw).decode('ascii')


def paragraph_fingerprint(paragraph,para_styles,char_styles):
    def xml(node):
        if node is None: raise ValueError('unresolved source cache style')
        from copy import deepcopy
        copy=deepcopy(node);copy.attrib.pop('id',None)
        return etree.tostring(copy,method='c14n',exclusive=True).decode('utf8')
    runs=[]
    for run in paragraph.findall(HP+'run'):
        text=''.join(t.text or '' for t in run.findall(HP+'t'))
        if text: runs.append([text,xml(char_styles.get(run.get('charPrIDRef')))])
    header=next(iter(char_styles.values())).getroottree().getroot()
    fonts=header.find('.//'+HH+'fontfaces')
    payload=[paragraph.get('id'),xml(para_styles.get(paragraph.get('paraPrIDRef'))),runs,
             etree.tostring(fonts,method='c14n',exclusive=True).decode('utf8') if fonts is not None else '']
    return hashlib.sha256(json.dumps(payload,ensure_ascii=True,separators=(',',':')).encode()).hexdigest()


def cell_geometry(cell):
    picture=cell.find('.//'+HP+'pic')
    if picture is None: raise ValueError('missing owned picture')
    return [cell.find(HP+'cellSz').get('width'),dict(cell.find(HP+'cellMargin').attrib),
            # Staging a table can discard unused ancestor namespace bindings.
            # They do not change the picture; canonicalize its used names only.
            etree.tostring(picture,method='c14n',exclusive=True).decode('utf8')]


def cache_integrity(cache):
    """Detect damaged snapshot storage; this hash never proves PDF provenance."""
    payload={k:v for k,v in cache.items() if k!='integrity'}
    return hashlib.sha256(json.dumps(payload,ensure_ascii=True,separators=(',',':')).encode()).hexdigest()


def seed(root,cell,para_styles,char_styles):
    """Called only after the importer's actual PDF/native proof succeeds."""
    if cell.get('name')!=WRAPPED_CELL or wrapped_cell_layout(cell,para_styles,char_styles=char_styles) is None: return False
    paragraphs=root.findall(HP+'p');ids=[p.get('id') for p in paragraphs]
    if not ids or len(ids)>512 or len(set(ids))!=len(ids) or any(not i or len(i)>32 for i in ids): return False
    ps=cell.findall(HP+'subList/'+HP+'p')
    if not 2<=len(ps)<=128 or len({p.get('id') for p in ps})!=len(ps): return False
    from .wrapped_cache_metrics import cached_slices_fit
    if any(not cached_slices_fit(p,para_styles,char_styles) for p in ps): return False
    snapshot=[]
    for p in ps:
        lines=p.findall(HP+'linesegarray/'+HP+'lineseg')
        if not 1<=len(lines)<=128: return False
        snapshot.append([p.get('id'),paragraph_fingerprint(p,para_styles,char_styles),
                         [[int(line.get(k)) for k in LINE_KEYS] for line in lines]])
    current=flags(paragraphs)
    value={'v':2,'ids':ids,'base':current,'last':current,
           'cache':{'geometry':cell_geometry(cell),'paragraphs':snapshot}}
    value['cache']['integrity']=cache_integrity(value['cache'])
    cell.set('name',encode(value))
    return True


def flags(paragraphs):
    result=[]
    for p in paragraphs:
        pair=[p.get('pageBreak','0'),p.get('columnBreak','0')]
        if any(v not in ('0','1') for v in pair) or pair==['1','1']:
            raise ValueError('invalid native break flags')
        result.append(pair)
    return result


def decode(name):
    if not name.startswith(PREFIX) or len(name)>65536: raise ValueError('invalid wrap state')
    digest,payload=name[len(PREFIX):].split(':',1)
    raw=base64.b64decode(payload.encode('ascii'),altchars=b'-_',validate=True)
    if len(raw)>32768 or hashlib.sha256(raw).hexdigest()!=digest: raise ValueError('invalid wrap state digest')
    value=json.loads(raw)
    if (not isinstance(value,dict) or value.get('v') not in (1,2)
        or set(value)!= ({'v','ids','base','last','cache'} if value['v']==2 else {'v','ids','base','last'})):
        raise ValueError('invalid wrap state keys')
    ids=value['ids']
    if (not isinstance(ids,list) or not 1<=len(ids)<=512 or len(set(ids))!=len(ids)
        or any(not isinstance(i,str) or not i or len(i)>32 for i in ids)): raise ValueError('invalid wrap state IDs')
    for key in ('base','last'):
        rows=value[key]
        if (not isinstance(rows,list) or len(rows)!=len(ids)
            or any(not isinstance(row,list) or len(row)!=2 or any(v not in ('0','1') for v in row)
                   or row==['1','1'] for row in rows)): raise ValueError('invalid wrap state flags')
    if value['v']==2:
        cache=value['cache']
        if (not isinstance(cache,dict) or set(cache)!= {'geometry','paragraphs','integrity'}
            or cache.get('integrity')!=cache_integrity(cache)): raise ValueError('invalid source cache')
        ps=cache['paragraphs']
        if not isinstance(ps,list) or not 2<=len(ps)<=128: raise ValueError('invalid source cache count')
        pids=[]
        for item in ps:
            if (not isinstance(item,list) or len(item)!=3 or not isinstance(item[0],str)
                or not isinstance(item[1],str) or len(item[1])!=64 or not isinstance(item[2],list)
                or not 1<=len(item[2])<=128): raise ValueError('invalid source cache paragraph')
            pids.append(item[0]);previous=-1
            for line in item[2]:
                if (not isinstance(line,list) or len(line)!=len(LINE_KEYS)
                    or any(type(v) is not int or not 0<=v<=2147483647 for v in line)
                    or (previous<0 and line[0]!=0) or not previous<line[0]
                    or not 0<line[4]<line[3]<=line[2] or line[7]<=0):
                    raise ValueError('invalid source cache band')
                previous=line[0]
        if len(set(pids))!=len(pids): raise ValueError('duplicate source cache paragraph')
    return value


def restore_cached_cell(cell,para_styles,char_styles):
    """Reuse a proved cache only after complete content/style/geometry reversion."""
    try:
        state=decode(cell.get('name',''))
        if state['v']!=2: return False
        snapshot=state['cache'];paragraphs=cell.findall(HP+'subList/'+HP+'p')
        if (cell_geometry(cell)!=snapshot['geometry']
            or [p.get('id') for p in paragraphs]!=[p[0] for p in snapshot['paragraphs']]
            or any(paragraph_fingerprint(p,para_styles,char_styles)!=item[1]
                   for p,item in zip(paragraphs,snapshot['paragraphs']))): return False
        from copy import deepcopy
        staged=deepcopy(cell)
        for p,item in zip(staged.findall(HP+'subList/'+HP+'p'),snapshot['paragraphs']):
            old=p.find(HP+'linesegarray')
            if old is not None: p.remove(old)
            array=etree.SubElement(p,HP+'linesegarray')
            for line in item[2]: etree.SubElement(array,HP+'lineseg',**{k:str(v) for k,v in zip(LINE_KEYS,line)})
        # Keep the table parent while proving all text offsets, descenders,
        # masks and occupied bands against the actual current native geometry.
        table=deepcopy(cell.getparent().getparent())
        original=table.find(HP+'tr/'+HP+'tc');original.getparent().replace(original,staged)
        if wrapped_cell_layout(staged,para_styles,char_styles=char_styles) is None: return False
        from .wrapped_cache_metrics import cached_slices_fit
        if any(not cached_slices_fit(p,para_styles,char_styles)
               for p in staged.findall(HP+'subList/'+HP+'p')): return False
        for p,s in zip(paragraphs,staged.findall(HP+'subList/'+HP+'p')):
            old=p.find(HP+'linesegarray')
            if old is not None: p.remove(old)
            p.append(s.find(HP+'linesegarray'))
        return True
    except (AttributeError,ValueError,TypeError,KeyError,UnicodeError,IndexError):
        return False


def begin(root,para_styles,char_styles):
    """Return baseline slots only when every dirty paragraph is proved wrapped."""
    try:
        paragraphs=root.findall(HP+'p')
        ids=[p.get('id') for p in paragraphs]
        if (not paragraphs or len(set(ids))!=len(ids)
            or any(not i or len(i)>32 for i in ids)): return None
        dirty=[p for p in root.iter(HP+'p') if p.find(HP+'linesegarray') is None
               and (any((t.text or '').strip() for t in p.findall(HP+'run/'+HP+'t'))
                    or any(c.tag!=HP+'t' for r in p.findall(HP+'run') for c in r))]
        if not dirty: return None
        cells=[]
        for p in dirty:
            cell=next((a for a in p.iterancestors() if a.tag==HP+'tc'),None)
            if cell is None or wrapped_cell_layout(cell,para_styles,allow_missing=True,char_styles=char_styles) is None: return None
            if cell not in cells: cells.append(cell)
        names={c.get('name','') for c in cells}
        if len(names)!=1: return None
        name=names.pop();current=flags(paragraphs)
        if name==WRAPPED_CELL:
            state={'v':1,'ids':ids,'base':current,'last':current}
        else:
            state=decode(name)
            if state['ids']!=ids: return None
            # A user's explicit change since our last pagination becomes the
            # new baseline, including explicit removal of a generated break.
            state['base']=[now if now!=old else base
                           for now,old,base in zip(current,state['last'],state['base'])]
        slots={};slot=0
        for p,(page,column) in zip(paragraphs,state['base']):
            if page=='1': slot+=2-slot%2
            elif column=='1': slot+=1
            slots[p]=slot
        return {'state':state,'slots':slots,'cells':cells}
    except (AttributeError,ValueError,TypeError,KeyError,UnicodeError):
        return None


def finish(root,context,para_styles,char_styles):
    """Save the generated flags after successful geometry/reflow validation."""
    if context is None: return
    paragraphs=root.findall(HP+'p')
    if [p.get('id') for p in paragraphs]!=context['state']['ids']: return
    # Tables may have been staged and replaced. Locate their native cells
    # again rather than retaining the detached pre-edit element references.
    cells=[c for c in root.iter(HP+'tc') if (c.get('name','')==WRAPPED_CELL or c.get('name','').startswith(PREFIX))
           and wrapped_cell_layout(c,para_styles,char_styles=char_styles) is not None]
    if not cells: return
    current=flags(paragraphs)
    for cell in cells:
        try:
            # Break bookkeeping belongs to the section, but original cache
            # snapshots belong to their own cell. Never copy another cell's
            # geometry/content/cache into an untouched neighbour.
            own=(decode(cell.get('name')) if cell.get('name','').startswith(PREFIX)
                 else {'v':1,'ids':context['state']['ids']})
            if own['ids']!=context['state']['ids']: continue
            state={**own,'base':context['state']['base'],'last':current}
            cell.set('name',encode(state))
        except (AttributeError,ValueError,TypeError,KeyError,UnicodeError):
            continue
