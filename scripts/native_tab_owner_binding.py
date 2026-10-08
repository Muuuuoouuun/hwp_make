"""Native XML column replay plus complete current painted question ownership."""
from types import SimpleNamespace
from lxml import etree
from app import pdf_source_choice_headers as H
from app.pdf_question_rendering import IDENTITY,_transform,_multiply,_expose_painted_dot_leaders,SVG
HP=H.HP
def bind(document,paragraph,pages):
    section=paragraph.section;root=section.element
    draw=next(a for a in paragraph.element.iterancestors() if a.tag==HP+'drawText')
    host=draw.getparent().getparent().getparent()
    tops=root.findall(HP+'p');slot=0;slots={}
    for p in tops:
        if p.get('pageBreak')=='1':slot+=2-slot%2
        elif p.get('columnBreak')=='1':slot+=1
        slots[p]=slot
    first_host=next(p for p in tops if any(H.re.fullmatch(r'question:v\d+:q\d+',d.get('name','')) for d in p.iter(HP+'drawText')))
    if slots[first_host]!=0:raise ValueError('unsupported section first-owner slot')
    first_draw=next(d for d in first_host.iter(HP+'drawText') if H.re.fullmatch(r'question:v\d+:q\d+',d.get('name','')))
    chars=[]
    for pi,svg in enumerate(pages):
        tree=etree.fromstring(svg.encode('utf8'));_expose_painted_dot_leaders(tree)
        for t in tree.iter(SVG+'text'):
            if any(etree.QName(a).localname in {'defs','pattern','clipPath','mask','symbol'} for a in t.iterancestors()):continue
            text=H.comparable(''.join(t.itertext()))
            if not text:continue
            if len(text)!=1:raise ValueError('unsupported native text granularity')
            m=IDENTITY
            for a in [*reversed(list(t.iterancestors())),t]:m=_multiply(m,_transform(a.get('transform','')))
            x,y=float(t.get('x',0)),float(t.get('y',0));chars.append((pi,text,(m[0]*x+m[2]*y+m[4],m[1]*x+m[3]*y+m[5])))
    full=''.join(c[1] for c in chars);prefix=H.native_segments(first_draw)[0]
    if full.count(prefix)!=1:raise ValueError('ambiguous first section native owner')
    section_page=chars[full.index(prefix)][0]
    pagepr=root.find('.//'+HP+'pagePr');margin=pagepr.find(HP+'margin')
    cols=[c for c in root.iter(HP+'colPr') if c.get('colCount')=='2']
    if len(cols)!=1:raise ValueError('ambiguous native columns')
    width=(int(pagepr.get('width'))-int(margin.get('left'))-int(margin.get('right'))-int(cols[0].get('sameGap')))/2
    expected=int(margin.get('left'))+(slots[host]%2)*(width+int(cols[0].get('sameGap')))
    if int(draw.getparent().find(HP+'sz').get('width'))!=width:raise ValueError('wrapper/column width mismatch')
    from app.pdf_native_text import body_text
    from hwpx.tools.paragraph_spacing import paragraph_indentation,line_left_margin
    header=document.headers[0].element;paras={n.get('id'):n for n in header.iter(H.HH+'paraPr')}
    if paragraph_indentation(host,paras)!=(0,0,0):raise ValueError('unsupported host indentation')
    pos=draw.getparent().find(HP+'pos')
    if pos.get('horzOffset')!='0' or pos.get('vertOffset')!='0':raise ValueError('unsupported wrapper offset')
    segments=H.native_segments(draw)
    if ''.join(segments)!=H.comparable(body_text(draw)) or full.count(segments[0])!=1:raise ValueError('incomplete owner segments')
    first=chars[full.index(segments[0])]
    p=draw.find(HP+'subList/'+HP+'p');cache=p.find(HP+'linesegarray/'+HP+'lineseg')
    insets=draw.find(HP+'textMargin');left,right,indent=paragraph_indentation(p,paras)
    first_x=(expected+int(insets.get('left'))+line_left_margin(left,indent,0)+int(cache.get('horzpos')))/75
    if first[0]!=section_page+slots[host]//2 or abs(first[2][0]-first_x)>=.02:raise ValueError('independent XML column/indent paint disagreement')
    top=first[2][1]-(int(cache.get('vertpos'))+int(cache.get('baseline'))+int(insets.get('top')))/75
    height=int(draw.getparent().find(HP+'sz').get('height'))/75
    rect=[expected/75,top,(expected+width)/75,top+height]
    owned=[c for c in chars if c[0]==first[0] and rect[0]-.02<=c[2][0]<=rect[2]+.02 and rect[1]-.02<=c[2][1]<=rect[3]+.02]
    text=''.join(c[1]for c in owned);covered=set()
    for segment in segments:
        if text.count(segment)!=1:raise ValueError('missing/ambiguous owner segment')
        start=text.index(segment);indices=set(range(start,start+len(segment)))
        if covered.intersection(indices):raise ValueError('overlapping owner segments')
        covered.update(indices)
    if len(covered)!=len(owned) or len(owned)!=len(H.comparable(body_text(draw))):raise ValueError('foreign or missing native owner paint')
    proof={'native_owner_rect_px':rect,'actual_native_question_glyphs':len(owned),'actual_native_segments':len(segments),
           'first_prompt_xml_x_px':first_x,'first_prompt_painted_x_px':first[2][0]}
    return {**proof,'slot':slots[host],'expected_page':section_page+slots[host]//2,
            'column_origin_hwp':expected,'column_pitch_px':(width+int(cols[0].get('sameGap')))/75}
