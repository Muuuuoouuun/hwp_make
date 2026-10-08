"""Actual-source paragraph justification, forged geometry and ordinary text."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'tmp/september-exam-matrix/source-justification'
NATIVE=Path(sys.argv[2]) if len(sys.argv)>2 else None
OUT.mkdir(parents=True,exist_ok=True)
os.environ['HWP_MAKE_DATA_DIR']=str((OUT/'data').resolve())
sys.path.insert(0,str(ROOT))

import fitz
from PIL import Image
from app.pdf_layout_writer import _iter_text_lines,_item_bbox,_line_text
from app.pdf_native_content import _source_typography
from app.pdf_source_image_validation import render_source_crop
from app.pdf_source_justification import source_justification
from verify_native_wrapped_prose_frame import source_oracle


def fixture(source,page,frame,image,name):
    with fitz.open(source) as pdf:
        source_width=pdf[page].rect.width
        lines=sorted((line for line in _iter_text_lines(pdf[page]) if frame.contains(_item_bbox(line))),
                     key=lambda line:(_item_bbox(line).y0,_item_bbox(line).x0))
        typography=_source_typography(lines,{'rect':frame})
    crop=OUT/'data/uploads'/f'{name}.png';crop.parent.mkdir(parents=True,exist_ok=True)
    crop.write_bytes(render_source_crop(source,page,image))
    return {'source_literal_text':True,'source_page_width_pt':source_width,
        'column_left_pt':frame.x0,'column_right_pt':frame.x1,'source_typography':typography,
        'native_tables':[{'source_prose_frame':True,'bbox_pt':list(frame),
            'source_pdf_path':str(source.resolve()),'source_page_index':page,
            'source_frame_text':''.join(record['text'] for record in typography['lines']),
            'images':[{'bbox_pt':list(image),'path':f'uploads/{name}.png'}]}]}


def invoke(layout,rows,**changes):
    records=layout['source_typography']['lines']
    rail=min(record['bbox_pt'][0] for record in records)
    scale=59528/layout['source_page_width_pt']
    frame=fitz.Rect(layout['native_tables'][0]['bbox_pt'])
    args={'available_width_hwp':round((frame.x1-rail)*scale),
          'source_left_pt':rail,'page_width_hwp':59528}
    args.update(changes)
    return source_justification(layout,rows,**args)


def actual():
    source=ROOT/'data/external_exam_qa/2026_september_high2/english.pdf'
    truth=source_oracle(source,3,27)
    layout=fixture(source,3,fitz.Rect(truth['frame']),fitz.Rect(truth['image_bbox']),'actual-tree')
    records=layout['source_typography']['lines']
    index=next(i for i,record in enumerate(records) if record['text'].startswith('Registration:'))
    rows=records[index:index+2]
    # Standalone source proof uses the entire available frame interval. The
    # optional native integration below independently reads actual cell margins.
    rail=min(record['bbox_pt'][0] for record in records)
    width=round((fitz.Rect(truth['frame']).x1-rail)*59528/truth['page_width'])
    before=repr(layout),repr(rows),source.read_bytes()
    result=invoke(layout,rows,available_width_hwp=width)
    last=max(char['bbox'][2] for span in rows[0]['spans'] for char in span['chars'] if not char['c'].isspace())
    expected=round(width-(last-min(record['bbox_pt'][0] for record in records))*59528/truth['page_width'])
    assert result=={'alignment':'JUSTIFY','right_hwp':expected},(result,expected)
    assert before==(repr(layout),repr(rows),source.read_bytes())
    return layout,index,width,result


def negatives(layout,index,width):
    names=('nonliteral','missing_pdf','missing_picture','answer_blank','partial_frame','single_row',
           'rows_reversed','rows_nonconsecutive','source_text','span_text','missing_raw','raw_text',
           'origin_forged','origin_nan','space_origin_forged','bbox_forged','bbox_nan','span_bbox_nan',
           'record_bbox_nan','span_font','span_size','span_flags','equation_font','wrong_source_width',
           'width_nan','width_negative','width_outside_frame','source_left_forged','page_width_nan')
    for name in names:
        changed=deepcopy(layout);records=changed['source_typography']['lines'];rows=records[index:index+2]
        geometry=changed['native_tables'][0];span=rows[0]['spans'][-1];char=span['chars'][1]
        args={'available_width_hwp':width}
        if name=='nonliteral':changed['source_literal_text']=False
        elif name=='missing_pdf':geometry['source_pdf_path']=str(OUT/'missing.pdf')
        elif name=='missing_picture':geometry['images'][0]['path']='uploads/missing.png'
        elif name=='answer_blank':changed['source_answer_blanks']=[{'text':'blank'}]
        elif name=='partial_frame':geometry['bbox_pt'][3]-=10
        elif name=='single_row':rows=rows[:1]
        elif name=='rows_reversed':rows=rows[::-1]
        elif name=='rows_nonconsecutive':rows=[records[index-1],records[index+1]]
        elif name=='source_text':rows[0]['text']+=' changed'
        elif name=='span_text':span['text']+=' changed'
        elif name=='missing_raw':span['chars']=[]
        elif name=='raw_text':char['c']='X'
        elif name in ('origin_forged','origin_nan','space_origin_forged'):
            if name=='space_origin_forged':char=next(c for c in span['chars'] if c['c']==' ')
            origin=list(char['origin']);origin[0]=float('nan') if name=='origin_nan' else origin[0]+5
            char['origin']=origin
        elif name in ('bbox_forged','bbox_nan'):
            bounds=list(char['bbox']);bounds[2]=float('nan') if name=='bbox_nan' else bounds[2]+5;char['bbox']=bounds
        elif name=='span_bbox_nan':span['bbox']=[float('nan'),0,1,1]
        elif name=='record_bbox_nan':rows[0]['bbox_pt']=[float('nan'),0,1,1]
        elif name=='span_font':span['font']='Different face'
        elif name=='span_size':span['size']+=1
        elif name=='span_flags':span['flags']^=16
        elif name=='equation_font':span['font']='HancomEQN'
        elif name=='wrong_source_width':changed['source_page_width_pt']+=1
        elif name=='width_nan':args['available_width_hwp']=float('nan')
        elif name=='width_negative':args['available_width_hwp']=-1
        elif name=='width_outside_frame':args['available_width_hwp']=width*2
        elif name=='source_left_forged':args['source_left_pt']=rows[0]['bbox_pt'][0]+1
        elif name=='page_width_nan':args['page_width_hwp']=float('nan')
        before=repr(changed),repr(rows)
        assert invoke(changed,rows,**args) is None,name
        assert before==(repr(changed),repr(rows)),name
    return names


def synthetic(mode):
    """Real PDF text operators; no field label or question-specific wording."""
    source=OUT/f'synthetic-{mode}.pdf'
    frame=fitz.Rect(40,40,460,300);picture=fitz.Rect(350,110,440,170)
    with fitz.open() as pdf:
        page=pdf.new_page(width=500,height=842)
        if mode!='missing_rules':page.draw_rect(frame,color=(0,0,0),width=.5)
        for x,y,text in ((150,60,'Community activity'),(60,90,'A short introductory sentence.'),
                         (60,120,'A line beside the picture.'),(60,190,'More information')):
            page.insert_text((x,y),text,fontsize=12)
        image=Image.new('RGB',(60,40),(40,130,180));image.putpixel((20,20),(240,210,60))
        buffer=io.BytesIO();image.save(buffer,format='PNG')
        page.insert_image(picture,stream=buffer.getvalue())
        first='Alpha beta gamma delta epsilon zeta'
        page.insert_text((60,220),first,fontsize=12)
        xref=page.get_contents()[-1];stream=pdf.xref_stream(xref)
        if mode not in ('ordinary','one_label_gap'):
            stream=stream.replace(b'BT',b'BT\n4 Tw',1)
        if mode in ('one_label_gap','inconsistent_gaps'):
            # Extra advance at one original ASCII space, using an actual
            # PDF TJ adjustment rather than forged metadata coordinates.
            encoded=first.encode().hex().encode()
            cut=(first.index(' ')+1)*2
            adjustment=b'-300' if mode=='one_label_gap' else b'-100'
            stream=stream.replace(b'<'+encoded+b'>',b'<'+encoded[:cut]+b'> '+adjustment+b' <'+encoded[cut:]+b'>')
        pdf.update_stream(xref,stream)
        page.insert_text((60,240),'One two three four five',fontsize=11 if mode=='different_size' else 12,
                         fontname='cour' if mode=='different_font' else 'helv')
        pdf.save(source)
    layout=fixture(source,0,frame,picture,f'synthetic-{mode}')
    records=layout['source_typography']['lines']
    rows=[record for record in records if record['baseline_pt']>=220]
    before=repr(layout),repr(rows),source.read_bytes()
    result=invoke(layout,rows)
    assert before==(repr(layout),repr(rows),source.read_bytes()),mode
    if mode=='expanded':
        assert result and result['alignment']=='JUSTIFY',result
        right=max(c['bbox'][2] for s in rows[0]['spans'] for c in s['chars'] if not c['c'].isspace())
        rail=min(r['bbox_pt'][0] for r in records);scale=59528/500
        assert result['right_hwp']==round(round((frame.x1-rail)*scale)-(right-rail)*scale)
    else:
        assert result is None,(mode,result)
    return {'mode':mode,'result':result,'source':str(source),'unchanged':True}


def integration(layout,index):
    if NATIVE is None:return {'checked':False,'reason':'no native artifact argument'}
    import zipfile
    from hashlib import sha256
    from lxml import etree
    import verify_native_illustrated_prose_frame_flow as shared
    from verify_native_wrapped_prose_frame import unique_in_frame
    HP=shared.HP;HH='{http://www.hancom.co.kr/hwpml/2011/head}'
    HC='{http://www.hancom.co.kr/hwpml/2011/core}'
    records=layout['source_typography']['lines'];rows=records[index:index+2]
    native_digest=sha256(NATIVE.read_bytes()).hexdigest()
    with zipfile.ZipFile(NATIVE) as archive:
        head=etree.fromstring(archive.read('Contents/header.xml'))
        roots=[etree.fromstring(archive.read(name)) for name in archive.namelist()
               if name.startswith('Contents/section') and name.endswith('.xml')]
    truth=source_oracle(ROOT/'data/external_exam_qa/2026_september_high2/english.pdf',3,27)
    cell=next(c for root in roots for c in root.iter(HP+'tc') if truth['title']['text'].strip() in ''.join(c.itertext()))
    ps=cell.findall(HP+'subList/'+HP+'p')
    # Compare the original independent semantic grouping, not source row count.
    from app.pdf_wrapped_prose_frames import source_wrapped_groups
    source=ROOT/'data/external_exam_qa/2026_september_high2/english.pdf'
    with fitz.open(source) as pdf:
        frame=fitz.Rect(truth['frame'])
        lines=sorted((line for line in _iter_text_lines(pdf[3]) if frame.contains(_item_bbox(line))),
                     key=lambda line:(_item_bbox(line).y0,_item_bbox(line).x0))
    groups=source_wrapped_groups(lines)
    def compact(value):return ''.join(value.split())
    assert len(ps)==len(groups)==14,(len(ps),len(groups))
    for paragraph,group in zip(ps,groups):
        assert ''.join(t.text or '' for t in paragraph.iter(HP+'t'))==' '.join(_line_text(line).strip() for line in group)
    assert not list(cell.iter(HP+'equation'))
    assert compact(''.join(t.text or '' for p in ps for t in p.iter(HP+'t')))==compact(truth['text'])
    paragraph=next(p for p in ps if compact(''.join(t.text or '' for t in p.iter(HP+'t')))==compact(''.join(r['text'] for r in rows)))
    styles={style.get('id'):style for style in head.iter(HH+'paraPr')}
    style=styles[paragraph.get('paraPrIDRef')]
    margin=cell.find(HP+'cellMargin')
    width=float(cell.find(HP+'cellSz').get('width'))-float(margin.get('left'))-float(margin.get('right'))
    evidence=invoke(layout,rows,available_width_hwp=width)
    assert evidence=={'alignment':'JUSTIFY','right_hwp':254},evidence
    assert style.find(HH+'align').get('horizontal')=='JUSTIFY'
    assert all(float(m.find(HC+'right').get('value'))==evidence['right_hwp'] for m in style.findall('.//'+HH+'margin'))
    parsed,painted,_,_=shared.painted(NATIVE)
    assert parsed.page_count==8,parsed.page_count
    scale=float(roots[0].find('.//'+HP+'pagePr').get('width'))/75/truth['page_width']
    residuals=[]
    for row in truth['rows']:
        if row['text'].strip() not in [r['text'].strip() for r in rows]:continue
        native=unique_in_frame(painted,row['text'],truth['text'])
        expected=[c for c in row['chars'] if not c['c'].isspace()]
        assert len(native)==len(expected)
        dx=[n[2]-s['origin'][0]*scale for n,s in zip(native,expected)]
        residuals.append({'text':row['text'],'first_dx_px':dx[0],'last_dx_px':dx[-1],
                          'max_abs_dx_px':max(map(abs,dx))})
    assert len(residuals)==2
    assert abs(residuals[0]['last_dx_px'])<2,residuals
    assert sha256(NATIVE.read_bytes()).hexdigest()==native_digest
    return {'checked':True,'native':str(NATIVE.resolve()),'pages':8,'semantic_paragraphs':len(ps),
            'sha256':native_digest,'actual_cell_evidence':evidence,'rows':residuals,
            'whole_text_preserved':True,'exact_semantic_paragraph_text':True,'equations':0}


def main():
    layout,index,width,result=actual()
    rejected=negatives(layout,index,width)
    synthetic_results=[synthetic(mode) for mode in ('expanded','ordinary','one_label_gap',
                       'inconsistent_gaps','different_font','different_size','missing_rules')]
    native_result=integration(layout,index)
    report={'ok':True,'actual_result':result,'metadata_negatives':list(rejected),
            'synthetic_actual_pdf':synthetic_results,
            'native_integration':native_result,
            'source_and_inputs_unchanged':True,'quality_pass_claimed':False}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('SOURCE_JUSTIFICATION_OK '+json.dumps(report,ensure_ascii=True))


if __name__=='__main__':main()
