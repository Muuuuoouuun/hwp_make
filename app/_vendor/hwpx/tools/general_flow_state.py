"""Bounded local edit history for general named-question break generation.

This is portable edit bookkeeping, not source provenance or authentication.
The digest detects damaged state; simultaneous deliberate forgery of a document
and its metadata is outside this feature's contract. No old cache is stored.
"""
from copy import deepcopy
import hashlib
import json
import re

from lxml import etree

HP='{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HH='{http://www.hancom.co.kr/hwpml/2011/head}'
PART='META-INF/hwp-make-general-flow.json'
MAX_BYTES=262144
QUESTION=re.compile(r'question:v\d+:q\d{2}$')

def _require(ok):
    if not ok:raise ValueError('unsupported general flow history')

def _json(value):
    return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':')).encode('ascii')

def _sha(value):
    return hashlib.sha256(value).hexdigest()

def _xml(node):
    _require(node is not None)
    return etree.tostring(node,method='c14n',exclusive=True)

def _flags(paragraphs):
    result=[[p.get('pageBreak','0'),p.get('columnBreak','0')] for p in paragraphs]
    _require(all(pair in (['0','0'],['1','0'],['0','1']) for pair in result))
    return result

def _ids(paragraphs):
    result=[p.get('id') for p in paragraphs]
    _require(1<=len(result)<=4096 and len(set(result))==len(result)
             and all(isinstance(i,str) and 1<=len(i)<=64 and not any(ord(c)<32 for c in i) for i in result))
    return result

def _fingerprint(p):
    copy=deepcopy(p)
    copy.attrib.pop('pageBreak',None);copy.attrib.pop('columnBreak',None)
    for array in list(copy.findall(HP+'linesegarray')):copy.remove(array)
    # Parents bind their own geometry/control structure. Nested paragraph
    # content is separately bound by its ordered ID and individual fingerprint.
    for nested in list(copy.iter(HP+'p')):
        if nested is copy:continue
        if nested.getparent() is None:continue
        marker=etree.Element(HP+'p',id=nested.get('id',''))
        marker.tail=nested.tail
        nested.getparent().replace(nested,marker)
    return _sha(_xml(copy))

def _column_config(root):
    configs=[]
    for node in root.iter():
        if node.tag in (HP+'pagePr',HP+'colPr'):
            configs.append(_xml(node).decode('utf8'))
    _require(1<=len(configs)<=64)
    return configs

def _document_binding(document):
    sections=[];all_ids=[]
    _require(1<=len(document.sections)<=64)
    for section in document.sections:
        ids=_ids(list(section.element.iter(HP+'p')))
        all_ids.extend(ids)
        sections.append([section.part_name,ids,_column_config(section.element)])
    _require(len(all_ids)<=8192 and len({section[0] for section in sections})==len(sections))
    # HWPX paragraph IDs are scoped by section. This actual document reuses
    # five IDs across sections; (part_name, ID) remains unambiguous.
    parts=[];total=0
    names=document.package.part_names()
    _require(len(names)<=512)
    for name in names:
        if (name==PART or name=='META-INF/hwp-make-native-gaps.json' or name=='version.xml' or name.startswith('Preview/')
            or re.fullmatch(r'Contents/(?:section\d+|header)\.xml',name)):
            continue
        value=document.package.read(name);total+=len(value)
        _require(len(value)<=16777216 and total<=67108864)
        parts.append([name,_sha(value)])
    return _sha(_json([sections,parts]))

def _style_binding(document,root):
    """Bind unambiguous current definitions, including referenced dependencies.

    Header catalogs are resolved by different consumers with different duplicate
    policies. Reject ambiguous IDs before any dictionary lookup can hide one.
    This is current native edit compatibility, not source typography permission.
    """
    _require(len(document.headers)==1)
    header=document.headers[0].element
    refs=header.findall(HH+'refList');_require(len(refs)==1)
    refs=refs[0]
    catalogs={}
    for kind,container in (('charPr','charProperties'),('paraPr','paraProperties'),
                           ('style','styles'),('tabPr','tabProperties'),
                           ('borderFill','borderFills')):
        parents=refs.findall(HH+container);_require(len(parents)==1)
        nodes=list(parents[0]);_require(1<=len(nodes)<=4096)
        _require(all(n.tag==HH+kind for n in nodes)
                 and len(list(header.iter(HH+kind)))==len(nodes))
        ids=[n.get('id') for n in nodes]
        _require(all(type(i) is str and re.fullmatch(r'0|[1-9][0-9]{0,9}',i)
                     and int(i)<=4294967295 for i in ids)
                 and len(set(ids))==len(ids))
        catalogs[kind]=dict(zip(ids,nodes))
    faces=refs.findall(HH+'fontfaces');_require(len(faces)==1)
    faces=faces[0];languages={'HANGUL','LATIN','HANJA','JAPANESE','OTHER','SYMBOL','USER'}
    face_nodes=list(faces);langs=[n.get('lang','').upper() for n in face_nodes]
    _require(len(face_nodes)==7 and set(langs)==languages
             and len(set(langs))==len(langs)
             and all(n.tag==HH+'fontface' for n in face_nodes)
             and len(list(header.iter(HH+'fontface')))==7)
    fonts={}
    for lang,face in zip(langs,face_nodes):
        nodes=list(face);ids=[n.get('id') for n in nodes]
        _require(1<=len(nodes)<=4096 and all(n.tag==HH+'font' for n in nodes)
                 and all(type(i) is str and re.fullmatch(r'0|[1-9][0-9]{0,9}',i)
                         and int(i)<=4294967295 for i in ids)
                 and len(set(ids))==len(ids))
        fonts[lang]=dict(zip(ids,nodes))
    _require(len(list(header.iter(HH+'font')))==sum(len(v) for v in fonts.values()))
    ref_kinds={'charPrIDRef':'charPr','paraPrIDRef':'paraPr','styleIDRef':'style',
               'nextStyleIDRef':'style','tabPrIDRef':'tabPr','borderFillIDRef':'borderFill'}
    pending=[];used=set()
    def enqueue(node):
        for n in node.iter():
            for attr,kind in ref_kinds.items():
                if attr in n.attrib:pending.append((kind,n.get(attr)))
    enqueue(root)
    for paragraph in root.iter(HP+'p'):
        _require(paragraph.get('paraPrIDRef') is not None)
        pending.append(('style',paragraph.get('styleIDRef','0')))
    _require(all(n.get('charPrIDRef') is not None for n in root.iter(HP+'run')))
    while pending:
        kind,identifier=pending.pop()
        key=(kind,identifier)
        if key in used:continue
        _require(identifier in catalogs[kind])
        used.add(key);_require(len(used)<=8192)
        node=catalogs[kind][identifier];enqueue(node)
        if kind=='charPr':
            font_refs=node.findall(HH+'fontRef');_require(len(font_refs)==1)
            font_refs=font_refs[0]
            _require(set(font_refs.attrib)=={v.lower() for v in languages})
            _require(all(font_refs.get(lang.lower()) in fonts[lang] for lang in languages))
    values=[_xml(faces).decode('utf8')]
    values.extend([kind,identifier,_xml(catalogs[kind][identifier]).decode('utf8')]
                  for kind,identifier in sorted(used))
    return _sha(_json(values))


def _object(pairs):
    value={}
    for key,item in pairs:
        _require(key not in value)
        value[key]=item
    return value

def _load(document):
    if not document.package.has_part(PART):return None
    raw=document.package.read(PART);_require(1<=len(raw)<=MAX_BYTES)
    value=json.loads(raw,object_pairs_hook=_object)
    _require(type(value) is dict and set(value)=={'v','binding','sections','digest'} and type(value['v']) is int and value['v']==1)
    payload={k:v for k,v in value.items() if k!='digest'}
    _require(type(value['digest']) is str and value['digest']==_sha(_json(payload)))
    _require(type(value['binding']) is str and re.fullmatch('[a-f0-9]{64}',value['binding']) is not None)
    _require(type(value['sections']) is dict and 1<=len(value['sections'])<=64)
    for name,s in value['sections'].items():
        _require(type(name) is str and re.fullmatch(r'Contents/section\d+\.xml',name) is not None)
        _require(type(s) is dict and set(s)=={'top_ids','ids','config','base','last','all_flags','fingerprints','styles'})
        _require(type(s['top_ids']) is list and type(s['ids']) is list
                 and 1<=len(s['top_ids'])<=512 and 1<=len(s['ids'])<=4096)
        for key in ('top_ids','ids'):
            ids=s[key]
            _require(len(set(ids))==len(ids) and all(type(i) is str and 1<=len(i)<=64 for i in ids))
        _require(set(s['top_ids'])<=set(s['ids']))
        for key,count in (('base',len(s['top_ids'])),('last',len(s['top_ids'])),('all_flags',len(s['ids']))):
            rows=s[key]
            _require(type(rows) is list and len(rows)==count
                     and all(type(pair) is list and pair in (['0','0'],['1','0'],['0','1']) for pair in rows))
        _require(type(s['config']) is list and 1<=len(s['config'])<=64
                 and all(type(x) is str and len(x)<=8192 for x in s['config']))
        _require(type(s['fingerprints']) is list and len(s['fingerprints'])==len(s['ids'])
                 and all(type(x) is str and re.fullmatch('[a-f0-9]{64}',x) is not None for x in s['fingerprints']))
        _require(type(s['styles']) is str and re.fullmatch('[a-f0-9]{64}',s['styles']) is not None)
    return value

def begin(document,section,wrapped_context,grid_context):
    """Release only previously recorded generated floors in one exact context."""
    try:
        _require(wrapped_context is None and grid_context is None)
        root=section.element;top=root.findall(HP+'p');paragraphs=list(root.iter(HP+'p'))
        ids=_ids(paragraphs);top_ids=_ids(top);_require(len(top_ids)<=512)
        dirty=[p for p in paragraphs if p.find(HP+'linesegarray') is None
               and (any((t.text or '').strip() for t in p.findall(HP+'run/'+HP+'t'))
                    or any(c.tag!=HP+'t' for r in p.findall(HP+'run') for c in r))]
        _require(1<=len(dirty)<=64)
        # Mixed table/wrapped/grid edits anywhere in the document retain
        # their existing flow ownership. Do not publish general history for
        # a simultaneous specialised transaction in another section.
        for other in document.sections:
            for q in other.element.iter(HP+'p'):
                if q.find(HP+'linesegarray') is not None:continue
                if not (any((t.text or '').strip() for t in q.findall(HP+'run/'+HP+'t'))
                        or any(c.tag!=HP+'t' for r in q.findall(HP+'run') for c in r)):continue
                _require(not any(a.tag==HP+'tbl' for a in q.iterancestors()))
        for p in dirty:
            ancestors=list(p.iterancestors())
            _require(not any(a.tag==HP+'tbl' for a in ancestors))
            draws=[a for a in ancestors if a.tag==HP+'drawText']
            _require((not draws and p in top) or (len(draws)==1 and QUESTION.fullmatch(draws[0].get('name','')) is not None))
            for run in p.findall(HP+'run'):
                _require(all(n.tag in (HP+'t',HP+'tab',HP+'lineBreak') for n in run))
                for text in run.findall(HP+'t'):
                    _require(all(n.tag in (HP+'tab',HP+'lineBreak') for n in text.iter() if n is not text))
        binding=_document_binding(document);styles=_style_binding(document,root);loaded=_load(document)
        current=_flags(top);all_flags=_flags(paragraphs);config=_column_config(root)
        if loaded is None:
            base=current
        else:
            _require(loaded['binding']==binding)
            state=loaded['sections'].get(section.part_name)
            # Existing history from another section is not permission to seed
            # an unmatched section after an external structural change.
            if state is None:
                base=current
            else:
                _require(state['top_ids']==top_ids and state['ids']==ids and state['config']==config
                         and state['last']==current and state['all_flags']==all_flags
                         and state['styles']==styles)
                dirty_set=set(dirty)
                _require(all(p in dirty_set or _fingerprint(p)==old for p,old in zip(paragraphs,state['fingerprints'])))
                base=state['base']
        slots={};slot=0
        for p,(page,column) in zip(top,base):
            if page=='1':slot+=2-slot%2
            elif column=='1':slot+=1
            slots[p]=slot
        return {'section':section,'binding':binding,'ids':ids,'top_ids':top_ids,'config':config,'base':base,'slots':slots}
    except (ValueError,TypeError,AttributeError,KeyError,UnicodeError,OSError,RecursionError):
        return None

def commit(document,contexts):
    """Stage all history, then add one non-rendering package part after success."""
    try:
        if not contexts:return False
        loaded=_load(document)
        binding=_document_binding(document)
        value=deepcopy(loaded) if loaded is not None else {'v':1,'binding':binding,'sections':{}}
        _require(value['binding']==binding)
        for ctx in contexts:
            section=ctx['section'];root=section.element;top=root.findall(HP+'p');paragraphs=list(root.iter(HP+'p'))
            _require(ctx['binding']==binding and ctx['top_ids']==_ids(top) and ctx['ids']==_ids(paragraphs)
                     and ctx['config']==_column_config(root))
            value['sections'][section.part_name]={'top_ids':ctx['top_ids'],'ids':ctx['ids'],'config':ctx['config'],
                'base':ctx['base'],'last':_flags(top),'all_flags':_flags(paragraphs),
                'fingerprints':[_fingerprint(p) for p in paragraphs],'styles':_style_binding(document,root)}
        value.pop('digest',None);value['digest']=_sha(_json(value));raw=_json(value)
        _require(len(raw)<=MAX_BYTES)
        document.package.write(PART,raw)
        return True
    except (ValueError,TypeError,AttributeError,KeyError,UnicodeError,OSError,RecursionError):
        return False


def preserve_manual_flags(paragraph,prior,slot,context):
    """Retain an original pair only when it describes the exact same move.

    For two columns, a COLUMN break from the right column advances to the
    next page. Canonicalizing it to PAGE loses the user's original pair even
    though both moves are identical. Never use a pair that changes the actual
    recomputed destination; baseline minimum slots remain separately enforced.
    """
    pairs=dict(zip(context['top_ids'],context['base']))
    pair=pairs[paragraph.get('id')]
    if ((pair==['1','0'] and slot==prior+2-prior%2)
        or (pair==['0','1'] and slot==prior+1)):
        paragraph.set('pageBreak',pair[0])
        paragraph.set('columnBreak',pair[1])
