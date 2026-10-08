"""Source-proved horizontal choice-header reconstruction in editable native text.

Producer source items discover numbered owners; actual PDF numbered bands,
fonts, paint and current native ownership grant horizontal permission. There
is no question-number, paper-hash or prose selector. Summary rules and source Y
are outside this helper's horizontal-only mutation permission.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import io
import math
from pathlib import Path
import re
import struct
from types import SimpleNamespace
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile

import fitz
from lxml import etree

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HH = '{http://www.hancom.co.kr/hwpml/2011/head}'
HC = '{http://www.hancom.co.kr/hwpml/2011/core}'
LANGS = ('hangul','latin','hanja','japanese','other','symbol','user')
LABEL = re.compile(r'\([A-Z]\)')


def compact(value):
    return ''.join(c for c in value if not c.isspace())


def comparable(value):
    return compact(value).replace('\U000f003b','↓').replace('－','-').replace('～','~')


def native_segments(draw):
    """Preserve separate native paint layers instead of assuming ZIP text order."""
    from app.pdf_native_text import body_text
    result=[]
    def visit(node):
        if node.tag in {HP+'header',HP+'footer'}:return
        if node.tag!=HP+'p':
            for child in node:visit(child)
            return
        pending=[]
        def flush():
            value=comparable(''.join(pending))
            if value:result.append(value)
            pending.clear()
        for run in node.findall(HP+'run'):
            for child in run:
                if child.tag==HP+'t':pending.append(body_text(child))
                elif child.tag==HP+'tab':pending.append(' ')
                elif child.tag in {HP+'rect',HP+'tbl',HP+'container',HP+'equation'}:
                    flush();visit(child)
        flush()
    visit(draw)
    return result


def bind_native_owner(draw,question,plan,native_chars):
    """Bind every native text segment within its actual current wrapper band."""
    from app.pdf_native_text import body_text
    segments=native_segments(draw)
    _require(segments and ''.join(segments)==comparable(body_text(draw)),'incomplete native segment traversal')
    alltext=''.join(c[1] for c in native_chars)
    _require(alltext.count(segments[0])==1,'actual numbered native prefix ambiguous')
    first=native_chars[alltext.index(segments[0])]
    _require(first[0]==question.page-1 and abs(first[2][0]*75-plan['column_origin_hwp'])<1.5,'native question painted in another page/column')
    firstp=draw.find(HP+'subList/'+HP+'p');cache=firstp.find(HP+'linesegarray/'+HP+'lineseg')
    _require(cache is not None,'missing first native question cache')
    top=first[2][1]-(int(cache.get('vertpos'))+int(cache.get('baseline')))/75
    height=int(draw.getparent().find(HP+'sz').get('height'))/75
    left=plan['column_origin_hwp']/75;right=left+plan['width']/75
    owned=[c for c in native_chars if c[0]==first[0] and left-.02<=c[2][0]<=right+.02 and top-.02<=c[2][1]<=top+height+.02]
    text=''.join(c[1] for c in owned);covered=set()
    for segment in segments:
        _require(text.count(segment)==1,'actual native question segment ambiguous in wrapper')
        start=text.index(segment);indices=set(range(start,start+len(segment)))
        _require(not covered.intersection(indices),'overlapping native paint ownership')
        covered.update(indices)
    _require(len(covered)==len(owned)==len(comparable(body_text(draw))),'native wrapper has missing/foreign text paint')
    return {'actual_native_question_glyphs':len(owned),'actual_native_segments':len(segments),
            'native_owner_rect_px':[left,top,right,top+height]}


def _require(value, message):
    if not value:
        raise ValueError(message)


def ordered_source(question):
    rows=[]
    for char in sorted((c for row in question.rows for c in row['glyphs']), key=lambda c:(c['baseline'],c['bbox'][0])):
        if rows and abs(char['baseline']-rows[-1][0]['baseline'])<=3:
            rows[-1].append(char)
        else:
            rows.append([char])
    return [c for row in rows for c in sorted(row,key=lambda c:c['bbox'][0]) if not c['c'].isspace()]


def source_owners_from_items(source_path,items):
    """Use producer metadata only for discovery, then reprove candidate bands.

    No frozen test manifest or independent test-oracle module supplies an owner.
    The raw PDF numbered band remains the mutation permission in source_header_plan.
    """
    source_path=Path(source_path).resolve();groups={};group_ids={};starts=Counter()
    for item in items:
        layout=item.get('layout',{});group=layout.get('question_group','')
        match=re.fullmatch(r'v\d+:q(\d+)',group)
        if match is None:continue
        number=int(match[1]);_require(number>0,'invalid source question number')
        _require(layout.get('question_number')==number and layout.get('question_group_kind')=='question','source group number/kind disagreement')
        _require(number not in group_ids or group_ids[number]==group,'duplicate source group number')
        group_ids[number]=group
        _require(type(layout.get('question_group_start')) is bool,'source group start is not canonical')
        starts[number]+=int(layout['question_group_start'])
        page_number=item.get('source_page');_require(type(page_number) is int and page_number>0,'source item page disagreement')
        owner=groups.setdefault(number,SimpleNamespace(number=number,page=page_number,rows=[]))
        lines=layout.get('source_typography',{}).get('lines',[])
        if not lines:continue  # Nontext items discover owners; never prove header geometry.
        _require(Path(layout['source_pdf_path']).resolve()==source_path,'source item PDF path disagreement')
        pi=layout.get('source_page_index');column=layout.get('source_column')
        _require(type(pi) is int and pi>=0 and page_number==pi+1 and type(column) is int and column in (1,2),'source item page/column lexical disagreement')
        for line in lines:
            chars=[{'c':c['c'],'bbox':tuple(c['bbox']),'baseline':c['origin'][1],'font_size':s['size']}
                   for s in line['spans'] for c in s['chars']]
            _require(chars,'empty source typography row')
            owner.rows.append({'page':pi+1,'column':column-1,'glyphs':chars,'bbox':line['bbox_pt']})
    _require(groups and all(starts[n]==1 and q.rows for n,q in groups.items()),'source group starts/rows incomplete')
    return groups


def reconstruct_from_items(data,source_path,items,*,native=None):
    """Producer-facing bytes API with exact fallback and no test-oracle dependency."""
    try:
        questions=source_owners_from_items(source_path,items)
    except (ValueError,KeyError,TypeError,IndexError,AttributeError,OSError) as error:
        return data,{'changed_groups':0,'abstention':str(error),'source_owner_discovery':'producer source items'}
    result,report=reconstruct_headers(data,source_path,questions,native=native)
    report['source_owner_discovery']='producer source items; actual PDF numbered-band permission'
    report['test_oracle_dependency']=False
    return result,report


def source_header_plan(page, question):
    """Prove one actual four-label row above five two-column choices."""
    from app.pdf_native_text import body_text
    wanted=Counter((c['c'],tuple(c['bbox']),c['baseline']) for c in ordered_source(question))
    actual=Counter((c['c'],tuple(c['bbox']),c['origin'][1])
                   for b in page.get_text('rawdict')['blocks'] for line in b.get('lines',[])
                   for s in line['spans'] for c in s['chars'] if not c['c'].isspace())
    _require(wanted and all(actual[k]==v for k,v in wanted.items()),'question raw ownership is not current/unique')
    _require(all(r['page']==question.page for r in question.rows) and len({r['column'] for r in question.rows})==1,'unsupported continued question ownership')
    rows=[]
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines',[]):
            chars=[c for s in line['spans'] for c in s['chars'] if not c['c'].isspace()]
            if chars and all((c['c'],tuple(c['bbox']),c['origin'][1]) in wanted for c in chars):
                rows.append((line,chars))
    labels=[(line,chars) for line,chars in rows if LABEL.fullmatch(''.join(c['c'] for c in chars))]
    groups=[]
    for line,chars in sorted(labels,key=lambda r:(r[1][0]['origin'][1],r[1][0]['origin'][0])):
        if groups and abs(chars[0]['origin'][1]-groups[-1][0][1][0]['origin'][1])<.1:
            groups[-1].append((line,chars))
        else:
            groups.append([(line,chars)])
    candidates=[]
    source_chars=ordered_source(question)
    for group in groups:
        if len(group)!=4:
            continue
        group.sort(key=lambda r:r[1][0]['origin'][0])
        names=[''.join(c['c'] for c in chars) for line,chars in group]
        if names[:2]!=names[2:] or names[0]==names[1]:
            continue
        baseline=group[0][1][0]['origin'][1]
        physical=[c for line,chars in rows for c in chars if abs(c['origin'][1]-baseline)<.1]
        if len(physical)!=12:
            continue
        choices=[c for c in source_chars if c['c'] in '①②③④⑤' and c['baseline']>baseline]
        if ''.join(c['c'] for c in choices)!='①②③④⑤':
            continue
        rails=[round(c['bbox'][0],2) for c in choices]
        if not (rails[0]==rails[2]==rails[4]<rails[1]==rails[3]):
            continue
        size=group[0][0]['spans'][0]['size']
        if not 0<choices[0]['baseline']-baseline<3*size:
            continue
        candidates.append((group,choices,rails,size))
    if not candidates:
        return None
    _require(len(candidates)==1,'ambiguous actual choice header')
    group,choices,rails,size=candidates[0]
    # Reprove the complete actual numbered band through the final option row.
    # A synchronized shortened oracle/native body is not a complete owner just
    # because each retained glyph is present in the PDF. The physical final row
    # includes every same-column fragment, including the leader/purpose word.
    column=question.rows[0]['column']
    column_rows=[]
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines',[]):
            if int(line['bbox'][0]>=page.rect.width/2)!=column:continue
            chars=[c for s in line['spans'] for c in s['chars'] if not c['c'].isspace()]
            if chars:column_rows.append((line,chars))
    anchors=[(line,chars) for line,chars in column_rows
             if re.match(r'^\s*'+str(question.number)+r'\s*\.', ''.join(c['c'] for c in chars))]
    _require(len(anchors)==1,'actual numbered source owner ambiguous')
    start=anchors[0][0]['bbox'][1]
    terminal_box=choices[-1]['bbox']
    terminal_rows=[chars for line,chars in column_rows
                   if line['bbox'][1]<terminal_box[3] and line['bbox'][3]>terminal_box[1]]
    _require(terminal_rows,'actual final choice physical row missing')
    end=max(c['origin'][1] for chars in terminal_rows for c in chars)
    complete=Counter((c['c'],tuple(c['bbox']),c['origin'][1])
                     for line,chars in column_rows if line['bbox'][1]>=start-.001
                     for c in chars if c['origin'][1]<=end)
    _require(complete==wanted,'incomplete actual numbered source band through final choice')
    traces=[(t,c) for t in page.get_texttrace() for c in t['chars']]
    allchars=[];spans=[]
    for line,chars in group:
        _require(line.get('wmode')==0 and tuple(line.get('dir',()))==(1.,0.),'header source direction')
        _require(len(line['spans'])==1,'ambiguous header source spans')
        span=deepcopy(line['spans'][0])
        span['text']=''.join(c['c'] for c in span['chars'])
        _require(span['font']=='TimesNewRoman' and span['flags']==4 and span.get('color')==0 and span.get('alpha')==255 and abs(span['size']-size)<.0001,'header source font/paint')
        for char in chars:
            _require(char.get('synthetic') is False,'synthetic source label')
            matches=[(t,c) for t,c in traces if c[0]==ord(char['c']) and tuple(c[2])==tuple(char['origin']) and t['font']==span['font']]
            _require(len(matches)==1,'ambiguous source label trace')
            trace,glyph=matches[0]
            _require(trace['type']==0 and trace['opacity']==1 and trace['flags']==4 and trace['wmode']==0 and tuple(trace['dir'])==(1.,0.) and abs(trace['size']-size)<.0001,'unsupported actual source label paint')
            pix=page.get_pixmap(matrix=fitz.Matrix(4,4),clip=fitz.Rect(char['bbox']),colorspace=fitz.csGRAY,alpha=False)
            _require(pix.width and pix.height and min(pix.samples)<192,'source label has no visible ink')
            allchars.append((char,glyph[1]))
        spans.append(span)
    bbox=fitz.Rect(group[0][0]['bbox'])
    for line,chars in group[1:]:
        bbox |= fitz.Rect(line['bbox'])
    _require(not any(bbox.intersects(fitz.Rect(i['bbox'])) for i in page.get_image_info()),'source header raster overlap')
    # Source rule/frame paints are independent; a header crossing a vector
    # object is conservatively unsupported by this horizontal-only scope.
    _require(not any(bbox.intersects(d['rect']) for d in page.get_drawings()),'source header vector overlap')
    return {'text':''.join(s['text'] for s in spans),'labels':[s['text'] for s in spans],
            'origins_pt':[list(s['chars'][0]['origin']) for s in spans],
            'bbox_pt':list(bbox),'baseline_pt':spans[0]['chars'][0]['origin'][1],
            'size_pt':size,'spans':spans,'glyphs':allchars,'choice_rails_pt':rails,
            'column':question.rows[0]['column']+1,'source_question_characters':len(source_chars)}


def font_program_proof(document,page,plan):
    """Bind each header Unicode/CID/GID to the actual embedded Times program."""
    from app.pdf_source_font_spaces import face,xref,ttf_space_width,cmap_space_cid
    resources=[f for f in page.get_fonts(full=True) if face(f[3])=='TimesNewRoman']
    _require(len(resources)==1,'ambiguous source font resource')
    font=resources[0];owner=font[0]
    _require(font[1:3]==('ttf','Type0') and document.xref_get_key(owner,'Encoding')==('name','/Identity-H'),'unsupported source font resource')
    kind,refs=document.xref_get_key(owner,'DescendantFonts');match=re.fullmatch(r'\[\s*([1-9]\d*) 0 R\s*\]',refs)
    _require(kind=='array' and match,'source descendant')
    descendant=int(match[1]);_require(document.xref_get_key(descendant,'CIDToGIDMap')==('name','/Identity'),'source glyph map')
    cmap=document.xref_stream(xref(document,owner,'ToUnicode'));space=cmap_space_cid(cmap)
    mapping={}
    def add(cid,value):
        _require(cid not in mapping and 0<=cid<=65535 and 0<=value<=65535,'ambiguous source CMap')
        mapping[cid]=value
    text=cmap.decode('ascii')
    for count,body in re.findall(r'(\d+)\s+beginbfchar(.*?)endbfchar',text,re.S):
        pairs=re.findall(r'<([\da-fA-F]{4})>\s*<([\da-fA-F]{4})>',body)
        _require(len(pairs)==int(count),'unsupported source CMap bfchar')
        for cid,value in pairs:add(int(cid,16),int(value,16))
    for count,body in re.findall(r'(\d+)\s+beginbfrange(.*?)endbfrange',text,re.S):
        triples=re.findall(r'<([\da-fA-F]{4})>\s*<([\da-fA-F]{4})>\s*<([\da-fA-F]{4})>',body)
        _require(len(triples)==int(count),'unsupported source CMap bfrange')
        for first,last,start in triples:
            a,b,c=int(first,16),int(last,16),int(start,16)
            _require(a<=b and b-a<4096,'source CMap range')
            for offset,gid in enumerate(range(a,b+1)):add(gid,c+offset)
    name,ext,kind,program=document.extract_font(owner)
    _require(ext=='ttf' and face(name)=='TimesNewRoman' and program==document.xref_stream(xref(document,xref(document,descendant,'FontDescriptor'),'FontFile2')),'source font program identity')
    metrics=ttf_space_width(program,space)
    # The same bounded hmtx directory validated by the quarter-space proof
    # supplies explicit nonzero header-glyph advances.
    count=struct.unpack_from('>H',program,4)[0]
    hmtx=next(struct.unpack_from('>4sIII',program,12+16*i)[2] for i in range(count) if program[12+16*i:16+16*i]==b'hmtx')
    advance={}
    for char,gid in plan['glyphs']:
        _require(mapping.get(gid)==ord(char['c']),'source Unicode/CID/GID disagreement')
        _require(0<=gid<metrics['glyph_count'],'source glyph program bounds')
        width=struct.unpack_from('>H',program,hmtx+4*min(gid,metrics['metric_count']-1))[0]
        _require(width>0,'source label missing glyph advance')
        advance[char['c']]={'gid':gid,'advance_width':width}
    return {'resource_xref':owner,'program_sha256':metrics['program_sha256'],
            'units_per_em':metrics['units_per_em'],'glyphs':advance}


def native_header_plan(header,section,draw,question,page,source,source_path,source_digest):
    """Reprove current native styles, canonical cache and actual columns."""
    from app import pdf_source_choice_geometry as guards, hwpx_writer_v2 as writer
    from app.pdf_native_text import body_text
    from app.pdf_native_content import _source_typography
    from app.pdf_source_line_cache import apply_source_line_cache
    from hwpx.tools.question_reflow import update_positions
    styles=guards._stylemap(header);fonts=guards._fontmap(header)
    paras=guards._unique(header.iter(HH+'paraPr'),guards._native_id,'paraPr IDs')
    _require(comparable(''.join(c['c'] for c in ordered_source(question)))==comparable(body_text(draw)),'incomplete source/native question text')
    matches=[p for p in draw.iter(HP+'p') if compact(body_text(p))==source['text']]
    _require(len(matches)==1,'ambiguous native header ownership')
    p=matches[0];_require(p.getparent() is draw.find(HP+'subList'),'nested header paragraph unsupported')
    _require(all(c.tag in {HP+'run',HP+'linesegarray'} for c in p) and len(p.findall(HP+'linesegarray'))==1,'native header controls/cache')
    runs=p.findall(HP+'run');_require(runs and all(c.tag==HP+'t' and not len(c) for r in runs for c in r),'native header text controls')
    _require(''.join(c.text or '' for r in runs for c in r)==source['text'],'native literal header text')
    width=guards._native_integer(section.find('.//'+HP+'pagePr').get('width'))
    scale=width/page.rect.width;height=round(source['size_pt']*scale)
    for run in runs:
        style=styles[run.get('charPrIDRef')];guards._plain(style,header)
        _require(guards._native_integer(style.get('height'))==height and style.find(HH+'bold') is None and style.find(HH+'italic') is None,'native source label height/flags')
        for tag,value in (('ratio',100),('spacing',0)):
            _require(all(guards._native_integer(style.find(HH+tag).get(l))==value for l in LANGS),'native label ratio/tracking')
        refs=style.find(HH+'fontRef');_require(all(fonts[l].get(refs.get(l))=='Times New Roman' for l in LANGS),'native seven-language source face')
    rail_records=guards._actual_column_rails(str(source_path),source_digest)
    actual=[r for r in rail_records if r[:2]==(question.page-1,source['column'])]
    _require(len(actual)==1,'actual source column ownership')
    _,_,left,right,pw,ph=actual[0]
    layout={'source_pdf_path':str(source_path),'source_page_index':question.page-1,'source_column':source['column'],
            'column_left_pt':left,'column_right_pt':right,'source_page_width_pt':pw,'source_page_height_pt':ph}
    wrapper=draw.getparent();guards._source_native_column_proof(layout,section,wrapper,width)
    actual_width=guards._native_integer(wrapper.find(HP+'sz').get('width'))
    pagepr=section.find('.//'+HP+'pagePr');margin=pagepr.find(HP+'margin');columns=list(section.iter(HP+'colPr'))
    column_width=(width-guards._native_integer(margin.get('left'))-guards._native_integer(margin.get('right'))-guards._native_integer(columns[0].get('sameGap')))/2
    _require(actual_width==column_width and guards._native_integer(draw.get('lastWidth'))==actual_width
             and guards._native_integer(draw.find(HP+'subList').get('textWidth'))==actual_width,'native canonical wrapper width disagreement')
    merged={'bbox':source['bbox_pt'],'spans':source['spans']}
    meta=_source_typography([merged],{'column_left_pt':left,'column_right_pt':right})
    style=paras[p.get('paraPrIDRef')];guards._paragraph_plain(p,style,meta,header)
    from hwpx.tools.paragraph_spacing import paragraph_indentation
    _require(paragraph_indentation(p,paras)==(0,0,0),'native original header indentation')
    default_width=(width-writer._mm_to_hwp(writer._KICE_SOURCE_MARGIN_LEFT_MM)-writer._mm_to_hwp(writer._KICE_SOURCE_MARGIN_RIGHT_MM)-writer._mm_to_hwp(writer._KICE_SOURCE_COLUMN_GAP_MM))/2
    # Typography caps this paragraph's source cache to the actual measured
    # source-column ink width, before later wrapper/column layout passes.
    legacy_width=min(default_width,float(meta['source_column_width_pt'])*scale)
    cloned_draw=deepcopy(draw)
    cloned=next(c for c in cloned_draw.iter(HP+'p') if c.get('id')==p.get('id'))
    _require(apply_source_line_cache(cloned,{**layout,'source_typography':meta,'native_page_width':width,'native_indentation':(0,0,0)},legacy_width),'canonical native header cache reconstruction')
    update_positions(cloned.getparent(),paras)
    expected_cache=[dict(x.attrib) for x in cloned.findall(HP+'linesegarray/'+HP+'lineseg')]
    actual_cache=[dict(x.attrib) for x in p.findall(HP+'linesegarray/'+HP+'lineseg')]
    _require(expected_cache==actual_cache,'noncanonical current header cache fields: '+repr({'actual':actual_cache,'expected':expected_cache}))
    # Page columns are independently replayed above. Bind the native question
    # to the actual source column, rather than deriving placement from a
    # mutable target header or an old painted-owner file.
    pagepr=section.find('.//'+HP+'pagePr');margin=pagepr.find(HP+'margin');columns=list(section.iter(HP+'colPr'))
    colwidth=(width-int(margin.get('left'))-int(margin.get('right'))-int(columns[0].get('sameGap')))/2
    origin=int(margin.get('left'))+(source['column']-1)*(colwidth+int(columns[0].get('sameGap')))
    return {'paragraph':p,'style':style,'width':actual_width,'page_width':width,'height':height,
            'column_origin_hwp':origin,'source_origins_hwp':[c[0]*scale for c in source['origins_pt']],
            'cache_fields':dict(p.find(HP+'linesegarray/'+HP+'lineseg').attrib)}


def apply_header_plan(header,plan,labels):
    """Stage one horizontal change using actual installed native font metrics."""
    from hwpx.tools import native_line_metrics, native_line_cache
    p=plan['paragraph'];properties=header.find('.//'+HH+'paraProperties');tabs=header.find('.//'+HH+'tabProperties')
    _require(properties is not None and tabs is not None,'missing native style stores')
    style=deepcopy(plan['style']);style.set('id',str(max(int(x.get('id')) for x in properties)+1))
    tabid=str(max(int(x.get('id')) for x in tabs)+1);style.set('tabPrIDRef',tabid)
    style.find(HH+'align').set('horizontal','LEFT')
    relative=[x-plan['column_origin_hwp'] for x in plan['source_origins_hwp']]
    left=round(relative[0]);_require(0<left<plan['width'] and all(a<b for a,b in zip(relative,relative[1:])),'source header rails outside native column')
    for margin in style.iter(HH+'margin'):
        for name,value in (('left',left),('right',0),('intent',0)):
            margin.find(HC+name).set('value',str(value))
    tab=etree.SubElement(tabs,HH+'tabPr',id=tabid,autoTabLeft='0',autoTabRight='0')
    switch=etree.SubElement(tab,HP+'switch');case=etree.SubElement(switch,HP+'case',attrib={'required-namespace':'http://www.hancom.co.kr/hwpml/2016/HwpUnitChar'});default=etree.SubElement(switch,HP+'default')
    for x in relative[1:]:
        etree.SubElement(case,HH+'tabItem',pos=str(round(x)),type='LEFT',leader='NONE')
        etree.SubElement(default,HH+'tabItem',pos=str(round(x)*2),type='LEFT',leader='NONE')
    properties.append(style);properties.set('itemCnt',str(len(properties)));tabs.set('itemCnt',str(len(tabs)));p.set('paraPrIDRef',style.get('id'))
    oldruns=p.findall(HP+'run');charid=oldruns[0].get('charPrIDRef')
    _require(all(r.get('charPrIDRef')==charid for r in oldruns),'mixed native header style IDs')
    for run in oldruns:p.remove(run)
    run=etree.Element(HP+'run',**dict(oldruns[0].attrib));p.insert(0,run)
    for i,label in enumerate(labels):
        if i:etree.SubElement(run,HP+'tab',width='1',leader='0',type='1')
        etree.SubElement(run,HP+'t').text=label
    # Use the installed production default's deterministic paragraph/probe/
    # prefix budgets and cumulative native-time bound, including exact fallback.
    context=native_line_metrics.optional_native_context(header,budget=native_line_metrics.ProbeBudget())
    provider=context.for_paragraph(p) if context is not None else None
    styles={c.get('id'):c for c in header.iter(HH+'charPr')};paras={c.get('id'):c for c in header.iter(HH+'paraPr')}
    _require(provider is not None and native_line_cache.cache_lines_native(p,plan['width'],styles,paras,native_advance=provider),'actual native header font metric plan failed')
    lines=p.findall(HP+'linesegarray/'+HP+'lineseg');_require(len(lines)==1,'header metric plan wraps')
    # Horizontal permission preserves every original vertical/cache field.
    lines[0].attrib.clear();lines[0].attrib.update(plan['cache_fields']);lines[0].set('horzpos','0');lines[0].set('horzsize',str(plan['width']))
    return {'left_hwp':left,'stops_hwp':[round(x) for x in relative[1:]],
            'widths_hwp':[int(t.get('width')) for t in p.findall(HP+'run/'+HP+'tab')],
            'native_probe_pages':provider.probes,'native_capability':context.capability_evidence}


def reconstruct_headers(data,source_path,questions,*,native=None):
    """Return exact input on any failed plan; discover candidates over all owners.

    This low-level API consumes source owner objects. ``reconstruct_from_items``
    is the producer entry point; it needs no manifest/test oracle. Every candidate
    replays complete actual numbered-band membership before any native change.
    """
    from app.pdf_native_text import body_text
    from app import pdf_source_choice_geometry as guards
    report={'scope':'source-proved horizontal choice-column headers; rules/source Y separate',
            'questions_examined':0,'plans':[],'changed_groups':0}
    try:
        source_path=Path(source_path).resolve();digest=hashlib.sha256(source_path.read_bytes()).hexdigest()
        report['source_sha256']=digest
        with ZipFile(io.BytesIO(data)) as archive:
            infos=archive.infolist();_require(len({guards._zip_name(i) for i in infos})==len(infos),'duplicate ZIP entries')
            parts={i.filename:archive.read(i.filename) for i in infos}
        header=etree.fromstring(parts['Contents/header.xml']);sections={n:etree.fromstring(v) for n,v in parts.items() if re.fullmatch(r'Contents/section\d+\.xml',n)}
        draws={}
        for name,root in sections.items():
            for draw in root.iter(HP+'drawText'):
                match=re.fullmatch(r'question:v\d+:q(\d+)',draw.get('name',''))
                if match:
                    number=int(match[1]);_require(number not in draws,'duplicate named question')
                    draws[number]=(name,root,draw)
        _require(set(draws)==set(questions),'complete native/source question ownership mismatch')
        report['questions_examined']=len(draws)
        # Actual current native paint supplies only ownership confirmation,
        # never the new source rail positions or font advances.
        if native is None:
            import rhwp as native
        painted=native.Document.from_bytes(data)
        from app.pdf_question_rendering import _visible_svg_text,_transform,_multiply,IDENTITY,_expose_painted_dot_leaders
        native_chars=[]
        for pi in range(painted.page_count):
            svg=painted.render_svg(pi);root=etree.fromstring(svg.encode('utf-8'));page_chars=[]
            _expose_painted_dot_leaders(root)
            for node in root.iter('{http://www.w3.org/2000/svg}text'):
                if any(etree.QName(a).localname in {'defs','pattern','clipPath','mask','symbol'} for a in node.iterancestors()):continue
                value=compact(''.join(node.itertext()))
                if not value:continue
                _require(len(value)==1,'unsupported current native multi-character paint')
                matrix=IDENTITY
                for ancestor in [*reversed(list(node.iterancestors())),node]:matrix=_multiply(matrix,_transform(ancestor.get('transform','')))
                x,y=float(node.get('x',0)),float(node.get('y',0))
                page_chars.append((pi,value,(matrix[0]*x+matrix[2]*y+matrix[4],matrix[1]*x+matrix[3]*y+matrix[5])))
            visible,hidden,unknown=_visible_svg_text(svg)
            _require(''.join(c[1] for c in page_chars)==compact(visible),'current native visible glyph ownership is incomplete')
            native_chars.extend(page_chars)
        full=''.join(c[1] for c in native_chars)
        with fitz.open(source_path) as document:
            for number,(name,section,draw) in sorted(draws.items()):
                q=questions[number];page=document[q.page-1]
                source=source_header_plan(page,q)
                if source is None:continue
                program=font_program_proof(document,page,source)
                plan=native_header_plan(header,section,draw,q,page,source,source_path,digest)
                ownership=bind_native_owner(draw,q,plan,native_chars)
                event=apply_header_plan(header,plan,source['labels'])
                report['plans'].append({'question':number,'source_page':q.page,'header_text':source['text'],
                                        'source_origins_pt':source['origins_pt'],'source_complete_question_characters':source['source_question_characters'],
                                        'source_font_program':program,'native_header_paragraph_id':plan['paragraph'].get('id'),**ownership,**event})
        _require(hashlib.sha256(source_path.read_bytes()).hexdigest()==digest,'source changed during proof')
        if not report['plans']:return data,report
        parts['Contents/header.xml']=etree.tostring(header,xml_declaration=True,encoding='utf-8',standalone=True)
        for name,root in sections.items():parts[name]=etree.tostring(root,xml_declaration=True,encoding='utf-8',standalone=True)
        buffer=io.BytesIO()
        with ZipFile(buffer,'w',compression=ZIP_DEFLATED) as archive:
            for info in infos:archive.writestr(info,parts[info.filename])
        report['changed_groups']=len(report['plans']);report['staged_atomic_clone']=True
        return buffer.getvalue(),report
    except (ValueError,KeyError,TypeError,IndexError,AttributeError,RuntimeError,OSError,UnicodeError,struct.error,StopIteration,BadZipFile,etree.XMLSyntaxError) as error:
        report['abstention']=str(error);report['changed_groups']=0
        return data,report


def apply_source_choice_headers(path,items):
    """Atomically apply proved horizontal headers after source-layout writing.

    Failed permission, source I/O, native probes, or editor-open validation
    preserve the original package. Only the shared basic English producer opts in.
    """
    import os,tempfile
    from hwpx.tools.package_validator import validate_editor_open_safety
    fallback={'changed_groups':0,'abstained':True,'atomic_rejection':True}
    try:
        paths={Path(layout['source_pdf_path']).resolve() for item in items
               for layout in [item.get('layout') or {}] if layout.get('source_pdf_path')}
        if len(paths)!=1:return fallback
        target=Path(path);original=target.read_bytes()
        updated,report=reconstruct_from_items(original,paths.pop(),items)
        if updated==original:return report
        descriptor,name=tempfile.mkstemp(dir=str(target.parent),suffix='.hwpx.tmp')
        os.close(descriptor);staged=Path(name)
        try:
            staged.write_bytes(updated)
            if not validate_editor_open_safety(staged).ok:return fallback
            # A concurrent editor must not lose changes made during proof.
            if target.read_bytes()!=original:return fallback
            os.replace(staged,target)
            return report
        finally:
            staged.unlink(missing_ok=True)
    except (OSError,ValueError,TypeError,KeyError,AttributeError,RuntimeError,BadZipFile,etree.XMLSyntaxError):
        return fallback
