"""Actual PDF ruled-grid geometry, consumer proof and public edit/reopen."""
from copy import deepcopy
import argparse,base64,hashlib,io,json,os,re,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
parser=argparse.ArgumentParser();parser.add_argument('folder',nargs='?',default=str(ROOT/'tmp/native-source-grid'))
args=parser.parse_args();OUT=Path(args.folder).resolve();OUT.mkdir(parents=True,exist_ok=True)
os.environ['HWP_MAKE_DATA_DIR']=str(OUT/'data')
import fitz,numpy as np,rhwp
from PIL import Image
from lxml import etree
from app.hwpx_writer_v2 import HwpxDocument
from app.pdf_layout_writer import write_pdf_structured_hwpx
from app import pdf_source_grid_layout as grid
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools import ruled_grid_flow as flow
from hwpx.tools.package_validator import validate_package
HP,HH,HC=grid.HP,grid.HH,grid.HC
SVG='{http://www.w3.org/2000/svg}'
SOURCE=ROOT/'data/external_exam_qa/2027_kice_september_high3/english.pdf'
CAPTURE=[]


def package(path):
    with zipfile.ZipFile(path) as z:parts={n:z.read(n) for n in z.namelist()}
    header=etree.fromstring(parts['Contents/header.xml'])
    roots=[etree.fromstring(v) for n,v in parts.items() if re.fullmatch(r'Contents/section\d+\.xml',n)]
    manifest=etree.fromstring(parts['Contents/content.hpf']);hrefs={n.get('id'):n.get('href') for n in manifest.iter('{http://www.idpf.org/2007/opf/}item')}
    tables=[(r,t) for r in roots for t in r.iter(HP+'tbl') if t.get('name','').startswith(flow.PREFIX)]
    return parts,header,roots,hrefs,tables


def run_write():
    original=grid.restore_source_grid_layout
    def captured(root,layout,header,width,column_width,**kwargs):
        before=deepcopy(root),deepcopy(header)
        result=original(root,layout,header,width,column_width,**kwargs)
        if result:CAPTURE.append((before[0],deepcopy(layout),before[1],width,column_width,dict(kwargs['hrefs']),dict(kwargs['payloads'])))
        return result
    grid.restore_source_grid_layout=captured
    try:stats=write_pdf_structured_hwpx(SOURCE,OUT/'native.hwpx',native_math=True)
    finally:grid.restore_source_grid_layout=original
    assert len(CAPTURE)==2,len(CAPTURE)
    assert stats['source_pages']==8 and stats['source_problem_count']==stats['output_problem_count']==45
    assert stats['source_text_preservation_ratio']==1 and stats['native_equations']==0
    assert stats['full_page_images']==stats['text_visual_overlays']==stats['math_visual_overlays']==0
    (OUT/'write.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf8')
    return stats


def producer_negatives():
    cases=('not_source','not_literal','no_pdf','wrong_page','nan_page','nan_frame','partial_grid','wrong_cell',
           'wrong_text','missing_rawchars','fake_origin','nan_origin','fake_font','fake_size','fake_flags','fractional_flags','nan_flags',
           'equation','unknown_control','caption','fractional_address','fractional_span','merged','padding',
           'nan_cache','wrong_native_text','overlap','image_alpha','font_mismatch','native_height','native_height_cache',
           'native_bold','native_ratio','native_tracking')
    for reason in cases:
        root,layout,header,width,column,hrefs,parts=deepcopy(CAPTURE[0]);g=layout['native_tables'][0];table=root.find(HP+'run/'+HP+'tbl');cell=table.find(HP+'tr/'+HP+'tc');p=cell.find(HP+'subList/'+HP+'p');r=layout['source_typography']['lines'][0]
        if reason=='not_source':layout['source_content']=False
        elif reason=='not_literal':layout['source_literal_text']=False
        elif reason=='no_pdf':g['source_pdf_path']=str(OUT/'absent.pdf')
        elif reason=='wrong_page':g['source_page_index']=0
        elif reason=='nan_page':g['source_page_index']=float('nan')
        elif reason=='nan_frame':g['bbox_pt'][0]=float('nan')
        elif reason=='partial_grid':g['source_grid_bbox_pt'][2]-=1
        elif reason=='wrong_cell':g['cell_bounds'][0][0]=list(g['cell_bounds'][0][0]);g['cell_bounds'][0][0][2]-=1
        elif reason=='wrong_text':r['text']+=' forgery'
        elif reason=='missing_rawchars':r['spans'][0]['chars']=[]
        elif reason=='fake_origin':r['spans'][0]['chars'][0]['origin']=list(r['spans'][0]['chars'][0]['origin']);r['spans'][0]['chars'][0]['origin'][0]+=1
        elif reason=='nan_origin':r['spans'][0]['origin']=[float('nan'),0]
        elif reason=='fake_font':r['spans'][0]['font']='Symbol'
        elif reason=='fake_size':r['spans'][0]['size']+=1
        elif reason=='fake_flags':r['spans'][0]['flags']^=16
        elif reason=='fractional_flags':r['spans'][0]['flags']+=.5
        elif reason=='nan_flags':r['spans'][0]['flags']=float('nan')
        elif reason in ('equation','unknown_control'):etree.SubElement(p.find(HP+'run'),HP+('equation' if reason=='equation' else 'bookmark'))
        elif reason=='caption':etree.SubElement(table,HP+'caption')
        elif reason=='fractional_address':cell.find(HP+'cellAddr').set('rowAddr','0.5')
        elif reason=='fractional_span':cell.find(HP+'cellSpan').set('colSpan','1.5')
        elif reason=='merged':cell.find(HP+'cellSpan').set('rowSpan','2')
        elif reason=='padding':cell.find(HP+'cellMargin').set('left','1')
        elif reason=='nan_cache':p.find(HP+'linesegarray/'+HP+'lineseg').set('textheight','nan')
        elif reason=='wrong_native_text':p.find(HP+'run/'+HP+'t').text='forged'
        elif reason=='overlap':table.find(HP+'pos').set('allowOverlap','1')
        elif reason=='image_alpha':next(f for f in header.iter(HH+'borderFill') if f.get('id')==table.get('borderFillIDRef')).find('.//'+HC+'img').set('alpha','100')
        elif reason=='font_mismatch':
            cp=next(c for c in header.iter(HH+'charPr') if c.get('id')==p.find(HP+'run').get('charPrIDRef'));cp.set('height','100')
        elif reason.startswith('native_'):
            p=next(v for v in table.iter(HP+'p') if grid._text(v));run=p.find(HP+'run')
            cp=deepcopy(next(c for c in header.iter(HH+'charPr') if c.get('id')==run.get('charPrIDRef')))
            cp.set('id',str(max(int(c.get('id')) for c in header.iter(HH+'charPr'))+1));header.find('.//'+HH+'charProperties').append(cp)
            for run in p.findall(HP+'run'):run.set('charPrIDRef',cp.get('id'))
            if reason in ('native_height','native_height_cache'):
                cp.set('height','600')
                if reason=='native_height_cache':
                    line=p.find(HP+'linesegarray/'+HP+'lineseg');line.set('vertsize','600');line.set('textheight','600');line.set('baseline','510')
            elif reason=='native_bold':etree.SubElement(cp,HH+'bold')
            else:
                metric=cp.find(HH+('ratio' if reason=='native_ratio' else 'spacing'))
                for language in metric.attrib:metric.set(language,'90' if reason=='native_ratio' else '-10')
        before=etree.tostring(root),etree.tostring(header)
        assert grid.restore_source_grid_layout(root,layout,header,width,column,hrefs=hrefs,payloads=parts)==0,reason
        assert before==(etree.tostring(root),etree.tostring(header)),reason
    return len(cases)


def consumer_negatives(stats):
    parts,header,roots,hrefs,tables=package(OUT/'native.hwpx');assert len(tables)==2
    for root,table in tables:
        assert grid.source_flow_grid_frame_table(table,root,header,hrefs,parts,SOURCE,stats['image_provenance'])
    root,table=tables[0];path=root.getroottree().getpath(table)
    cases=('text','baseline','vertpos','spacing','height','width','alignment','rule','margin','control','nonintegral','name_only','altered_png',
           'native_height_compensated','native_bold','native_ratio','native_tracking')
    for reason in cases:
        changed=deepcopy(root);head=deepcopy(header);t=changed.xpath(path,namespaces=changed.nsmap)[0];media=dict(parts)
        cell=next(c for c in t.findall(HP+'tr/'+HP+'tc') if any((n.text or '').strip() for n in c.iter(HP+'t')));p=cell.find(HP+'subList/'+HP+'p');line=p.find(HP+'linesegarray/'+HP+'lineseg')
        if reason=='text':p.find(HP+'run/'+HP+'t').text='wrong text'
        elif reason in ('baseline','vertpos','spacing'):line.set(reason,str(int(line.get(reason))+10))
        elif reason=='height':cell.find(HP+'cellSz').set('height','1000')
        elif reason=='width':cell.find(HP+'cellSz').set('width','1000')
        elif reason=='alignment':next(s for s in head.iter(HH+'paraPr') if s.get('id')==p.get('paraPrIDRef')).find(HH+'align').set('horizontal','LEFT')
        elif reason=='rule':cell.set('borderFillIDRef',t.get('borderFillIDRef'))
        elif reason=='margin':cell.find(HP+'cellMargin').set('top','1000')
        elif reason=='control':etree.SubElement(p.find(HP+'run'),HP+'equation')
        elif reason=='nonintegral':cell.find(HP+'cellAddr').set('rowAddr','1.5')
        elif reason=='name_only':t.set('name',grid.GRID_FRAME);t.find(HP+'pos').set('horzOffset','999')
        elif reason=='altered_png':
            image=next(f for f in head.iter(HH+'borderFill') if f.get('id')==t.get('borderFillIDRef')).find('.//'+HC+'img');key=hrefs[image.get('binaryItemIDRef')]
            im=Image.open(io.BytesIO(media[key])).convert('RGB');im.putpixel((0,0),(255,0,0));b=io.BytesIO();im.save(b,format='PNG');media[key]=b.getvalue()
        elif reason.startswith('native_'):
            cp=deepcopy(next(c for c in head.iter(HH+'charPr') if c.get('id')==p.find(HP+'run').get('charPrIDRef')))
            cp.set('id',str(max(int(c.get('id')) for c in head.iter(HH+'charPr'))+1));head.find('.//'+HH+'charProperties').append(cp)
            for run in p.findall(HP+'run'):run.set('charPrIDRef',cp.get('id'))
            if reason=='native_height_compensated':
                top=cell.find(HP+'cellMargin');top.set('top',str(int(top.get('top'))+int(line.get('baseline'))-510))
                cp.set('height','600');line.set('vertsize','600');line.set('textheight','600');line.set('baseline','510')
            elif reason=='native_bold':etree.SubElement(cp,HH+'bold')
            else:
                metric=cp.find(HH+('ratio' if reason=='native_ratio' else 'spacing'))
                for language in metric.attrib:metric.set(language,'90' if reason=='native_ratio' else '-10')
            state=flow.decode(t.get('name'));state['geometry']=flow.geometry(t,head)[0]
            ps={s.get('id'):s for s in head.iter(HH+'paraPr')};cs={s.get('id'):s for s in head.iter(HH+'charPr')}
            for entry in state['cells']:
                q=next(q for q in t.iter(HP+'p') if q.get('id')==entry[0]);entry[1]=flow.metrics(q,ps,cs)[1]
                if q is p:entry[2]=flow.lines(q);entry[3]=int(cell.find(HP+'cellSz').get('height'))-int(cell.find(HP+'cellMargin').get('top'))-entry[2][-1][2]
            t.set('name',flow.encode(state))
        assert not grid.source_flow_grid_frame_table(t,changed,head,hrefs,media,SOURCE,stats['image_provenance']),reason
    return len(cases)


def vendor_negatives():
    _,header,roots,_,tables=package(OUT/'native.hwpx');root,table=tables[0]
    ps={p.get('id'):p for p in header.iter(HH+'paraPr')};cs={p.get('id'):p for p in header.iter(HH+'charPr')}
    assert flow.prepare(table,header,ps,cs)
    cases=('baseline','vertpos','spacing_reserve','height_reserve','empty_height_reserve','gutter_height_reserve',
           'empty_clear_style','gutter_run','synced_strikeout','synced_outline','synced_shadow','synced_emboss','synced_engrave',
           'reserve','nan','wrong_cache_width','font','para_style','unicode',
           'equation','address','span','gutter_height','padding','fake_state','native_cache')
    for reason in cases:
        t=deepcopy(table);h=deepcopy(header);state=flow.decode(t.get('name'));cell=next(c for c in t.findall(HP+'tr/'+HP+'tc') if ''.join(c.itertext())=='1st prize');p=cell.find(HP+'subList/'+HP+'p');record=next(r for r in state['cells'] if r[0]==p.get('id'))
        if reason.startswith('empty_') or reason in ('gutter_height_reserve','gutter_run'):
            styled=reason.startswith('empty_')
            cell=next(c for c in t.findall(HP+'tr/'+HP+'tc') if not any((n.text or '') for n in c.iter(HP+'t'))
                      and (c.find(HP+'subList/'+HP+'p/'+HP+'run') is not None)==styled)
            p=cell.find(HP+'subList/'+HP+'p');record=next(r for r in state['cells'] if r[0]==p.get('id'))
        p.remove(p.find(HP+'linesegarray'))
        if reason=='baseline':record[2][0][4]=1
        elif reason=='vertpos':record[2][0][1]+=100;record[3]-=100
        elif reason=='spacing_reserve':record[2][0][5]+=100;record[3]-=100
        elif reason in ('height_reserve','empty_height_reserve','gutter_height_reserve'):
            height=10 if reason=='gutter_height_reserve' else 1000
            delta=height-record[2][0][3];record[2][0][2]=record[2][0][3]=height;record[2][0][4]=round(height*.85);record[3]-=delta
        elif reason=='empty_clear_style':
            p.remove(p.find(HP+'run'))
            record[1]=flow.metrics(p,ps,cs)[1]
        elif reason=='gutter_run':
            etree.SubElement(etree.SubElement(p,HP+'run',charPrIDRef='41'),HP+'t')
            record[1]=flow.metrics(p,ps,cs)[1]
        elif reason.startswith('synced_'):
            cp=next(s for s in h.iter(HH+'charPr') if s.get('id')==p.find(HP+'run').get('charPrIDRef'));old_signature=flow.digest(flow.xml(cp))
            tag=reason[7:];decoration=cp.find(HH+tag)
            if decoration is None:decoration=etree.SubElement(cp,HH+tag)
            if tag=='strikeout':decoration.attrib.update({'shape':'SOLID','color':'#000000'})
            elif tag in ('outline','shadow'):decoration.set('type','CONTINUOUS' if tag=='shadow' else 'SOLID')
            new_signature=flow.digest(flow.xml(cp))
            for entry in state['cells']:entry[1][1]=[new_signature if v==old_signature else v for v in entry[1][1]]
        elif reason=='reserve':record[3]+=1
        elif reason=='nan':record[2][0][2]=float('nan')
        elif reason=='wrong_cache_width':record[2][0][7]-=1
        elif reason=='font':next(s for s in h.iter(HH+'charPr') if s.get('id')==p.find(HP+'run').get('charPrIDRef')).set('height','999')
        elif reason=='para_style':next(s for s in h.iter(HH+'paraPr') if s.get('id')==p.get('paraPrIDRef')).find(HH+'align').set('horizontal','RIGHT')
        elif reason=='unicode':p.find(HP+'run/'+HP+'t').text='1st prize 😀'
        elif reason=='equation':etree.SubElement(p.find(HP+'run'),HP+'equation')
        elif reason=='address':cell.find(HP+'cellAddr').set('rowAddr','1.5')
        elif reason=='span':cell.find(HP+'cellSpan').set('colSpan','2')
        elif reason=='gutter_height':t.find(HP+'tr/'+HP+'tc/'+HP+'cellSz').set('height','100')
        elif reason=='padding':cell.find(HP+'cellMargin').set('top','999')
        elif reason=='native_cache':
            other=next(c.find(HP+'subList/'+HP+'p') for c in t.findall(HP+'tr/'+HP+'tc') if ''.join(c.itertext())=='2nd prize');other.find(HP+'linesegarray/'+HP+'lineseg').set('baseline','1')
        t.set('name',flow.encode(state) if reason!='fake_state' else flow.PREFIX+'forged')
        before=etree.tostring(t),etree.tostring(h)
        try:flow.prepare(t,h,{s.get('id'):s for s in h.iter(HH+'paraPr')},{s.get('id'):s for s in h.iter(HH+'charPr')})
        except (ValueError,TypeError,KeyError,IndexError,AttributeError):pass
        else:raise AssertionError(reason)
        assert before==(etree.tostring(t),etree.tostring(h)),reason
    return len(cases)


def pixels(doc,page):return np.asarray(Image.open(io.BytesIO(doc.render_png(page))).convert('RGB'))


def glyph_bounds(rendered,table,target_id):
    """Actual PDF-painted glyph bboxes against independently painted grid rules."""
    cell=next(c for c in table.findall(HP+'tr/'+HP+'tc') if c.find(HP+'subList/'+HP+'p').get('id')==target_id)
    wanted=re.sub(r'\s+','',''.join(cell.itertext()))
    if not wanted:return {'glyphs':0,'empty_native_cell':True}
    native,_,_=flow.geometry(table,package(OUT/'native.hwpx')[1])
    real=[divmod(i,native[1]) for i,s in enumerate(native[5]) if s[1]=='SOLID']
    r0,c0=min(r for r,c in real),min(c for r,c in real)
    rows,cols=max(r for r,c in real)-r0+1,max(c for r,c in real)-c0+1
    address=cell.find(HP+'cellAddr');row=int(address.get('rowAddr'))-r0;col=int(address.get('colAddr'))-c0
    tokens=[]
    with fitz.open(stream=bytes(rendered.render_pdf()),filetype='pdf') as pdf:
        for page in pdf:
            tokens.extend((chr(ch[0]),page.number,tuple(v/.75 for v in ch[3]))
                          for trace in page.get_texttrace() for ch in trace['chars'] if not chr(ch[0]).isspace())
    value=''.join(t[0] for t in tokens);assert value.count(wanted)==1,(wanted,value.count(wanted))
    start=value.index(wanted);used=tokens[start:start+len(wanted)];pages={p for _,p,_ in used};assert len(pages)==1
    svg=etree.fromstring(rendered.render_svg(next(iter(pages))).encode())
    rules=[tuple(float(n.get(k)) for k in ('x1','y1','x2','y2')) for n in svg.iter(SVG+'line') if n.get('stroke-width')=='0.4']
    groups={}
    for x,y,a,b in rules:
        if x==a:groups.setdefault((y,b),[]).append(x)
    candidates=[]
    for (top,bottom),xs in groups.items():
        xs=sorted(set(xs))
        if len(xs)!=cols+1:continue
        ys=sorted(set(y for x,y,a,b in rules if y==b and abs(x-xs[0])<1e-6 and abs(a-xs[-1])<1e-6 and top<=y<=bottom))
        if len(ys)!=rows+1:continue
        box=(xs[col],ys[row],xs[col+1],ys[row+1]);epsilon=1/75
        if all(box[0]-epsilon<=b[0]<b[2]<=box[2]+epsilon and box[1]-epsilon<=b[1]<b[3]<=box[3]+epsilon for _,_,b in used):candidates.append(box)
    assert len(candidates)==1,('painted edited glyphs crossed their actual ruled native cell',wanted,candidates)
    return {'glyphs':len(used),'page':next(iter(pages))+1,'cell_bbox_px':candidates[0],
            'glyph_bbox_px':[min(t[2][0] for t in used),min(t[2][1] for t in used),max(t[2][2] for t in used),max(t[2][3] for t in used)]}


def edits():
    native=OUT/'native.hwpx';original=rhwp.parse(str(native));assert original.page_count==8
    original_parts,_,_,_,tables=package(native);original_media={n:v for n,v in original_parts.items() if n.startswith('BinData/')}
    heights=[float(t.find(HP+'sz').get('height')) for _,t in tables]
    results={}
    target_id=next(p.get('id') for _,t in tables for p in t.iter(HP+'p') if ''.join(p.itertext())=='1st prize')
    for mode in ('small','large','revert','empty','empty-revert','space-boundary'):
        doc=HwpxDocument.open(OUT/'large.hwpx' if mode=='revert' else OUT/'empty.hwpx' if mode=='empty-revert' else native)
        for section in doc.sections:
            for table in section.element.iter(HP+'tbl'):
                if not table.get('name','').startswith(flow.PREFIX):continue
                targets=[p for p in table.iter(HP+'p') if p.get('id')==target_id]
                if not targets:continue
                p=targets[0];HwpxOxmlParagraph(p,section).text='1st Prize' if mode=='small' else '1st prize'+' measured editable grid growth'*3 if mode=='large' else '' if mode=='empty' else 'i i i i i i i i' if mode=='space-boundary' else '1st prize'
        target=OUT/(mode+'.hwpx');doc.save_to_path(target);assert validate_package(target).ok
        parts,h,roots,_,current=package(target);assert {n:v for n,v in parts.items() if n.startswith('BinData/')}==original_media
        now=[float(t.find(HP+'sz').get('height')) for _,t in current]
        rendered=rhwp.parse(str(target))
        if mode not in ('large','space-boundary'):assert now==heights and rendered.page_count==8,(mode,now,heights,rendered.page_count)
        else:assert now[0]>heights[0] and rendered.page_count>=8
        for _,t in current:
            ps={p.get('id'):p for p in h.iter(HH+'paraPr')};cs={p.get('id'):p for p in h.iter(HH+'charPr')}
            prepared,_=flow.prepare(t,h,ps,cs)
            assert t.find(HP+'sz').attrib==prepared.find(HP+'sz').attrib
        reopened=OUT/(mode+'-reopened.hwpx');HwpxDocument.open(target).save_to_path(reopened)
        assert [etree.tostring(t) for _,t in package(reopened)[4]]==[etree.tostring(t) for _,t in current]
        assert rhwp.parse(str(reopened)).page_count==rendered.page_count
        results[mode]={'pages':rendered.page_count,'grid_heights':now}
        results[mode]['painted_glyph_bounds']=glyph_bounds(rendered,current[0][1],target_id)
        if mode=='small':results[mode]['changed_pixels_p4']=int(np.count_nonzero(np.any(pixels(original,3)!=pixels(rendered,3),axis=-1)))
        if mode in ('revert','empty-revert'):assert np.array_equal(pixels(original,3),pixels(rendered,3))
    (OUT/'native-p4.png').write_bytes(original.render_png(3));(OUT/'native-p4.svg').write_text(original.render_svg(3),encoding='utf8')
    return results


def main():
    stats=run_write();result={'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'source_pages':8,'questions':45,'source_text_ratio':stats['source_text_preservation_ratio'],
      'producer_negatives':producer_negatives(),'consumer_negatives':consumer_negatives(stats),'vendor_negatives':vendor_negatives(),'edits':edits(),'quality_pass_claimed':False}
    (OUT/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print('SOURCE_GRID_OK '+json.dumps(result))


if __name__=='__main__':main()
