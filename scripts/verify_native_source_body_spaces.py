"""Actual-source body word spacing, metadata rejection and editable native text."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lxml import etree
from app.pdf_native_content import extract_native_content
from app.pdf_source_body_spaces import source_body_space_styles
from app.pdf_source_run_styles import HP, restore_source_run_styles


def main():
    source = ROOT/'data/external_exam_qa/2027_kice_september_high3/english.pdf'
    if not source.is_file():
        print('SKIP: actual source PDF missing'); return 2
    items, _ = extract_native_content(source, max_pages=3, area_hint='\uc601\uc5b4 \uc601\uc5ed')
    fixtures = [i for i in items if i['layout'].get('question_number') in (19,20,22)
                and len(i['layout'].get('source_typography',{}).get('lines',[])) >= 3]
    assert len(fixtures) == 3
    styles, ids = {}, {}
    def style(base, height, font, tracking, ratio, bold, *, italic):
        key = (height,font,tracking,ratio,bold,italic)
        if key not in ids:
            ident = str(len(styles)+1); ids[key] = ident; styles[ident] = key
        return ids[key]
    def paragraph(value):
        p = etree.Element(HP+'p')
        etree.SubElement(etree.SubElement(p,HP+'run',charPrIDRef='0'),HP+'t').text = value
        return p
    proved = []
    for item in fixtures:
        spaces = source_body_space_styles(item['layout'])
        assert len(spaces) >= 100 and set(spaces.values()) == {(80,-15)}
        text = item['stem']; p = paragraph(text)
        assert restore_source_run_styles(p,item['layout'],59528,style) > 0
        assert ''.join(p.itertext()) == text
        ordinary = [r for r in p.findall(HP+'run') if r.findtext(HP+'t') == ' ']
        assert len(ordinary) == text.count(' ')
        assert all(styles[r.get('charPrIDRef')][1:4] == ('Times New Roman',-15,80) for r in ordinary)
        before = etree.tostring(p)
        restore_source_run_styles(p,item['layout'],59528,style)
        assert etree.tostring(p) == before # memoizing allocator; not raw producer IDs
        proved.append({'question':item['layout']['question_number'], 'proved_space_positions':len(spaces),
                       'native_ascii_spaces':len(ordinary)})
    original = fixtures[0]['layout']; negatives=[]
    for reason in ('nonliteral','table','answerblank','inline_label','left','missing_pdf',
                   'wrong_page','negative_page','fractional_page','bool_page','nan_page',
                   'wrong_width','nan_width','partial_rows','reversed_rows','duplicate_row',
                   'changed_text','wrong_bbox','nan_bbox','missing_span','wrong_font',
                   'wrong_size','nan_size','bold','fractional_flags','missing_char',
                   'changed_char','wrong_origin','nan_origin','wrong_char_bbox'):
        q=deepcopy(original); records=q['source_typography']['lines']; row=records[0]; span=row['spans'][0]
        if reason=='nonliteral':q['source_literal_text']=False
        elif reason=='table':q['native_tables']=[{}]
        elif reason=='answerblank':q['source_answer_blanks']=[{}]
        elif reason=='inline_label':q['source_inline_labels']=[{}]
        elif reason=='left':q['source_typography']['alignment']='LEFT'
        elif reason=='missing_pdf':q['source_pdf_path']=str(source.parent/'missing.pdf')
        elif reason=='wrong_page':q['source_page_index']=0
        elif reason=='negative_page':q['source_page_index']=-1
        elif reason=='fractional_page':q['source_page_index']=1.5
        elif reason=='bool_page':q['source_page_index']=True
        elif reason=='nan_page':q['source_page_index']=float('nan')
        elif reason=='wrong_width':q['source_page_width_pt']+=1
        elif reason=='nan_width':q['source_page_width_pt']=float('nan')
        elif reason=='partial_rows':records.pop(0)
        elif reason=='reversed_rows':records.reverse()
        elif reason=='duplicate_row':records.insert(1,deepcopy(row))
        elif reason=='changed_text':row['text']='different words'
        elif reason in ('wrong_bbox','nan_bbox'):
            row['bbox_pt'][0]=float('nan') if reason=='nan_bbox' else row['bbox_pt'][0]+1
        elif reason=='missing_span':row['spans'].pop()
        elif reason=='wrong_font':span['font']='Arial'
        elif reason=='wrong_size':span['size']+=1
        elif reason=='nan_size':span['size']=float('nan')
        elif reason=='bold':span['flags']^=16
        elif reason=='fractional_flags':span['flags']+=.1
        elif reason=='missing_char':span['chars'].pop()
        elif reason=='changed_char':span['chars'][0]['c']='X'
        elif reason in ('wrong_origin','nan_origin'):
            v=list(span['chars'][0]['origin']);v[0]=float('nan') if reason=='nan_origin' else v[0]+1
            span['chars'][0]['origin']=v
        elif reason=='wrong_char_bbox':
            v=list(span['chars'][0]['bbox']);v[0]+=1;span['chars'][0]['bbox']=v
        assert source_body_space_styles(q)=={},reason
        negatives.append(reason)
    text=fixtures[0]['stem']
    for reason in ('changed_native_words','native_equation','native_tabs'):
        p=paragraph(text.replace('Katie','Sarah',1) if reason=='changed_native_words'
                    else text.replace(' ','\t') if reason=='native_tabs' else text)
        if reason=='native_equation':etree.SubElement(p[0],HP+'equation')
        before=etree.tostring(p);count=len(styles)
        result=restore_source_run_styles(p,original,59528,style)
        if reason=='native_tabs':
            assert ''.join(p.itertext())==text.replace(' ','\t')
            assert not any(styles[r.get('charPrIDRef')][2:4]==(-15,80) for r in p.findall(HP+'run'))
        else:
            assert result==0 and before==etree.tostring(p) and len(styles)==count,reason
        negatives.append(reason)
    report={'ok':True,'actual_source_bodies':proved,'negative_cases':negatives,
            'source_space_style':[80,-15],'native_text_preserved':True,
            'idempotence_scope':'memoizing test allocator only; no raw producer-ID claim'}
    out=ROOT/'tmp/september-exam-matrix/source-body-spaces';out.mkdir(parents=True,exist_ok=True)
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('SOURCE_BODY_SPACES_OK',json.dumps(report,ensure_ascii=False));return 0


if __name__=='__main__':
    raise SystemExit(main())
