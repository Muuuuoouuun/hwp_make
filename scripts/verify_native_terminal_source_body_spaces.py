"""Verify the actual font-backed terminal space and public native editing."""
from copy import deepcopy
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from lxml import etree
import rhwp
from app import pdf_source_body_spaces
from app.pdf_native_content import extract_native_content
from app.pdf_source_run_styles import HP,restore_source_run_styles
from app.pdf_source_question_body import HH,HC,restore_source_question_body_right
from app.hwpx_writer_v2 import HwpxDocument
from hwpx.oxml import HwpxOxmlParagraph
import verify_native_source_question_body as common


def snapshot():
    paths=sorted((ROOT/'app').rglob('*.py'))
    module=Path(rhwp.__file__).resolve()
    runtime=[module,*sorted(module.parent.rglob('*.pyd'))]
    return {'app':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
            'runtime':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in runtime},
            'rhwp_python_version':importlib.metadata.version('rhwp-python')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hwpx',type=Path,required=True)
    parser.add_argument('--source',type=Path,default=ROOT/'data/external_exam_qa/2027_kice_september_high3/english.pdf')
    parser.add_argument('--output',type=Path,default=ROOT/'tmp/september-exam-matrix/terminal-source-body-regression')
    parser.add_argument('--guards-only',action='store_true')
    parser.add_argument('--collect-guard-failures',action='store_true',help='Collect independent consumer failures in one report.')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('HWP_MAKE_DATA_DIR',str(args.output/'data'))
    original=pdf_source_body_spaces.source_body_space_styles
    before=snapshot();report={'checks':[],'before':before,'implementation':'direct product helper',
                              'source_sha256':common.sha(args.source),'input_sha256':common.sha(args.hwpx)}
    def check(value,label,**evidence):
        report['checks'].append({'name':label,'passed':bool(value),**evidence})
        print(('PASS: ' if value else 'FAIL: ')+label,flush=True)
        if not (args.collect_guard_failures and label.startswith('consumer_rejects_')):
            assert value,label
    try:
        items,_=extract_native_content(args.source,max_pages=3,area_hint='영어 영역')
        fixtures={item['layout']['question_number']:item for item in items if item['layout'].get('source_question_body')}
        for number,count in ((19,107),(20,139),(22,164)):
            values=pdf_source_body_spaces.source_body_space_styles(fixtures[number]['layout'])
            check(len(values)==count and set(values.values())=={(80,-15)},f'existing_q{number}_space_map_preserved')
        layout=fixtures[23]['layout'];rows=layout['source_typography']['lines']
        cursor=sum(len(common.compact(row['text'])) for row in rows[:-1]);expected=set()
        for span in rows[-1]['spans']:
            for char in span['chars']:
                if char['c']==' ':expected.add(cursor)
                cursor+=len(common.compact(char['c']))
        values=pdf_source_body_spaces.source_body_space_styles(layout)
        check(len(expected)==1 and values==dict.fromkeys(expected,(80,-15)),'actual_q23_terminal_cursor_only',positions=sorted(values))
        allocated={};ids={}
        def allocate(base,height,font,tracking,ratio,bold,*,italic):
            key=height,font,tracking,ratio,bold,italic
            if key not in ids:
                ident=str(len(ids)+1);ids[key]=ident;allocated[ident]=key
            return ids[key]
        text=fixtures[23]['stem']
        for shape in ('one_run','per_character_empty','double_space','nbsp','tab','empty','changed','equation'):
            value=text.replace(' ','  ' if shape=='double_space' else '\u00a0' if shape=='nbsp' else '\t' if shape=='tab' else ' ')
            if shape=='empty':value=''
            elif shape=='changed':value='X'+value[1:]
            p=etree.Element(HP+'p')
            for part in (list(value) if shape=='per_character_empty' else [value]):
                if shape=='per_character_empty':etree.SubElement(etree.SubElement(p,HP+'run',charPrIDRef='0'),HP+'t').text=''
                etree.SubElement(etree.SubElement(p,HP+'run',charPrIDRef='0'),HP+'t').text=part
            if shape=='equation':etree.SubElement(p[0],HP+'equation')
            prior=etree.tostring(p);allocation_count=len(allocated)
            changed=restore_source_run_styles(p,layout,59528,allocate)
            marked=[run for run in p.findall(HP+'run') if allocated.get(run.get('charPrIDRef'),())[2:4]==(-15,80)]
            passed=common.direct_text(p)==value and len(marked)==(1 if shape in ('one_run','per_character_empty') else 0)
            if shape in ('empty','changed','equation'):
                passed &= changed==0 and prior==etree.tostring(p) and len(allocated)==allocation_count
            check(passed,'native_'+shape+'_permission_scope')
        header,sections=common.package(args.hwpx)
        body=common.attached_body(sections,fixtures[23]);wrapper=body.getparent().getparent().getparent()
        body_index=list(wrapper.iter(HP+'p')).index(body)
        page_width=float(sections[0].find('.//'+HP+'pagePr').get('width'))
        width=float(wrapper.find(HP+'sz').get('width'))
        def setup():
            rect,h,l=deepcopy(wrapper),deepcopy(header),deepcopy(layout)
            p=list(rect.iter(HP+'p'))[body_index]
            common.para_style(h,p).find('.//'+HH+'margin/'+HC+'right').set('value','0')
            return rect,h,l,p
        rect,h,l,p=setup()
        check(restore_source_question_body_right([(p,l)],h,page_width,width)==1,'actual_q23_native_consumer_accepts')
        for name in ('absent_body','changed_body','missing_source_proof','native_equation','ratio','tracking','height','font',
                     'font_hangul','font_hanja','font_japanese','font_other','font_symbol','font_user',
                     'bold','italic','underline','outline','shadow','strikeout','emboss','engrave','relative_size','offset','missing_metric_language'):
            rect,h,l,p=setup()
            styles={style.get('id'):style for style in h.iter(HH+'charPr')}
            marked=next(run for run in p.findall(HP+'run') if run[0].text==' '
                        and styles[run.get('charPrIDRef')].find(HH+'ratio').get('latin')=='80')
            style=styles[marked.get('charPrIDRef')]
            if name in ('absent_body','changed_body'):
                p.find(HP+'run/'+HP+'t').text='' if name=='absent_body' else 'X'+p.find(HP+'run/'+HP+'t').text
                if name=='absent_body':
                    for run in p.findall(HP+'run')[1:]:p.remove(run)
            elif name=='missing_source_proof':l.pop('source_question_body')
            elif name=='native_equation':etree.SubElement(marked,HP+'equation')
            elif name in ('ratio','tracking','relative_size','offset'):
                node=style.find(HH+{'tracking':'spacing','relative_size':'relSz'}.get(name,name))
                for key,value in node.attrib.items():node.set(key,str(int(value)+1))
            elif name=='height':style.set('height',str(int(style.get('height'))+10))
            elif name=='font' or name.startswith('font_'):
                language='latin' if name=='font' else name.removeprefix('font_')
                fonts=[f for face in h.iter(HH+'fontface') if face.get('lang')==language.upper() for f in face]
                alternative=next(f for f in fonts if f.get('face')!='Times New Roman')
                style.find(HH+'fontRef').set(language,alternative.get('id'))
            elif name in ('bold','italic','strikeout','emboss','engrave'):etree.SubElement(style,HH+name)
            elif name=='underline':style.find(HH+'underline').set('type','BOTTOM')
            elif name in ('outline','shadow'):style.find(HH+name).set('type','SOLID')
            elif name=='missing_metric_language':del style.find(HH+'ratio').attrib['other']
            prior=etree.tostring(rect),etree.tostring(h)
            count=restore_source_question_body_right([(p,l)],h,page_width,width)
            check(count==0 and prior==(etree.tostring(rect),etree.tostring(h)),'consumer_rejects_'+name+'_atomically')
        if not args.guards_only:
            document=HwpxDocument.open(args.hwpx)
            section,draw=next((s,d) for s in document.sections for d in s.element.iter(HP+'drawText') if d.get('name')=='question:v1:q23')
            p=next(p for p in draw.iter(HP+'p') if common.direct_text(p)==text)
            old_margins,old_styles=common.margins(header,body),common.styled_chars(header,body)
            public=HwpxOxmlParagraph(p,section)
            last=next(run for run in reversed(public.runs) if run.text)
            addition=' Clear observations help people compare possibilities and make thoughtful decisions.'*3
            public.add_run(addition,char_pr_id_ref=last.element.get('charPrIDRef'))
            check(p.find(HP+'linesegarray') is None,'public_add_run_invalidates_cache')
            grown=args.output/'grown.hwpx';document.save_to_path(grown)
            grown_header,grown_sections=common.package(grown)
            grown_body=next(p for p in common.question(grown_sections,23).iter(HP+'p') if common.direct_text(p)==text+addition)
            check(common.margins(grown_header,grown_body)==old_margins,'public_save_preserves_native_indents')
            check(common.styled_chars(grown_header,grown_body)[:len(old_styles)]==old_styles,'public_save_preserves_all_original_resolved_styles')
            cache=grown_body.findall(HP+'linesegarray/'+HP+'lineseg')
            check(bool(cache) and len(cache)>len(rows),'public_save_reflows_growing_semantic_body')
            parsed=rhwp.parse(str(grown));payload=bytes(parsed.render_pdf());(args.output/'grown.pdf').write_bytes(payload)
            pdf=common.fitz.open(stream=payload,filetype='pdf')
            glyphs=[(index,char) for index,page in enumerate(pdf) for trace in page.get_texttrace() if trace.get('type')==0 and trace.get('opacity',1)>.99 for char in trace['chars'] if not chr(char[0]).isspace()]
            common.locate(glyphs,text+addition)
            check(True,'public_added_body_complete_native_painted_glyph_sequence')
            reopened=args.output/'reopened.hwpx';HwpxDocument.open(grown).save_to_path(reopened)
            h2,s2=common.package(reopened)
            p2=next(p for p in common.question(s2,23).iter(HP+'p') if common.direct_text(p)==text+addition)
            check(common.margins(h2,p2)==old_margins and common.styled_chars(h2,p2)==common.styled_chars(grown_header,grown_body),'reopen_resave_preserves_text_and_resolved_styles')
            check(rhwp.parse(str(reopened)).render_svg(2)==parsed.render_svg(2),'reopen_resave_native_p3_paint_exact')
        report['after']=snapshot();check(report['after']==before,'app_and_runtime_fingerprints_stable')
        report['ok']=all(row['passed'] for row in report['checks'])
    except Exception as error:
        report['ok']=False;report['error']=repr(error)
        raise
    finally:
        pdf_source_body_spaces.source_body_space_styles=original
        (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    return 0 if report['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
