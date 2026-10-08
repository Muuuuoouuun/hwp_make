"""Complete actual mixed bodies: terminal font proof, strict native guards, public edits."""
from copy import deepcopy
from pathlib import Path
import argparse,hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lxml import etree
from app.pdf_native_content import extract_native_content
from app.pdf_source_body_spaces import source_body_space_styles
from app.pdf_source_question_body import restore_source_question_body_right
from scripts import verify_native_source_question_body as common
HP,HH,HC=common.HP,common.HH,common.HC

def producer_checks(fixtures,check):
    from app import pdf_source_body_spaces as product
    from app.pdf_source_run_styles import restore_source_run_styles
    allocated={};ids={}
    def allocate(base,height,font,tracking,ratio,bold,*,italic):
        key=height,font,tracking,ratio,bold,italic
        if key not in ids:
            identifier=str(len(ids)+1);ids[key]=identifier;allocated[identifier]=key
        return ids[key]
    def make(text,shape):
        p=etree.Element(HP+'p')
        for piece in (list(text) if shape=='per_character_empty' else [text]):
            if shape=='per_character_empty':etree.SubElement(etree.SubElement(p,HP+'run',charPrIDRef='0'),HP+'t').text=''
            etree.SubElement(etree.SubElement(p,HP+'run',charPrIDRef='0'),HP+'t').text=piece
        if shape=='equation':etree.SubElement(p[0],HP+'equation')
        return p
    def resolved(p):return [(c,allocated.get(run.get('charPrIDRef'))) for run in p.findall(HP+'run') for c in run.findtext(HP+'t','')]
    original=product.source_body_space_styles
    for number,count in ((21,5),(24,1)):
        item=fixtures[number];text=item['stem']
        for shape in ('one_run','per_character_empty','double_space','nbsp','tab','empty','changed','equation'):
            value=text.replace(' ','  ' if shape=='double_space' else '\u00a0' if shape=='nbsp' else '\t' if shape=='tab' else ' ')
            if shape=='empty':value=''
            elif shape=='changed':value='X'+value[1:]
            baseline=make(value,shape);candidate=make(value,shape);prior=etree.tostring(candidate);old_count=len(allocated)
            product.source_body_space_styles=lambda layout,**kwargs:{}
            try:restore_source_run_styles(baseline,item['layout'],59528,allocate)
            finally:product.source_body_space_styles=original
            changed=restore_source_run_styles(candidate,item['layout'],59528,allocate)
            before,after=resolved(baseline),resolved(candidate)
            marked=[(char,style) for char,style in after if style is not None and style[2:4]==(-15,80)]
            check(common.direct_text(candidate)==value and [x for x in before if not x[0].isspace()]==[x for x in after if not x[0].isspace()],f'q{number}_{shape}_producer_preserves_text_and_nonspace_styles')
            check(len(marked)==(count if shape in ('one_run','per_character_empty') else 0) and all(char==' ' for char,style in marked),f'q{number}_{shape}_only_proved_ascii_spaces_translated')
            if shape in ('empty','changed','equation'):
                check(changed==0 and etree.tostring(candidate)==prior and len(allocated)==old_count,f'q{number}_{shape}_producer_rejects_atomically')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hwpx',type=Path,required=True)
    parser.add_argument('--source',type=Path,default=ROOT/'data/external_exam_qa/2027_kice_september_high3/english.pdf')
    parser.add_argument('--output',type=Path,default=ROOT/'tmp/september-exam-matrix/mixed-terminal-source-body-regression')
    parser.add_argument('--public',action='store_true')
    parser.add_argument('--producer-only',action='store_true')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    fingerprint=lambda:{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'app').rglob('*.py'))}
    before=fingerprint();report={'checks':[],'input_sha256':common.sha(args.hwpx),'product_helper':True}
    def check(value,label,**evidence):
        report['checks'].append({'name':label,'passed':bool(value),**evidence});print(('PASS ' if value else 'FAIL ')+label,flush=True)
        assert value,label
    try:
        items,_=extract_native_content(args.source,max_pages=3,area_hint='영어 영역')
        fixtures={item['layout']['question_number']:item for item in items if item['layout'].get('source_question_body')}
        for number,count in ((19,107),(20,139),(22,164),(23,1),(21,5),(24,1)):
            result=source_body_space_styles(fixtures[number]['layout'])
            check(len(result)==count and set(result.values())=={(80,-15)},f'q{number}_actual_source_map',positions=len(result))
        producer_checks(fixtures,check)
        if args.producer_only:
            check(before==fingerprint(),'app_fingerprint_stable');report['ok']=True;return 0
        header,sections=common.package(args.hwpx);page_width=float(sections[0].find('.//'+HP+'pagePr').get('width'))
        source_labels=('bool_page','fractional_page','wrong_page','nan_width','missing_pdf','missing_body',
                       'omit_terminal_records','omit_terminal_both','omit_middle_both','reverse_rows','meta_ratio','meta_tracking','meta_samplecount',
                       'flags_fractional','flags_nan','fake_font','fake_size','synthetic_space','synthetic_records_only','synthetic_proof_only','space_origin','space_bbox','record_text')
        for number in (21,24):
            item=fixtures[number];layout=item['layout'];body=common.attached_body(sections,item)
            check(source_body_space_styles(layout,paragraph=body,header=header,page_width=page_width)==source_body_space_styles(layout),f'q{number}_strict_native_context_accepts')
            for label in source_labels:
                changed=deepcopy(layout);records=changed['source_typography']['lines'];proofrows=changed['source_question_body']['lines']
                if label=='bool_page':changed['source_page_index']=True
                elif label=='fractional_page':changed['source_page_index']=2.5
                elif label=='wrong_page':changed['source_page_index']=0
                elif label=='nan_width':changed['source_page_width_pt']=float('nan')
                elif label=='missing_pdf':changed['source_pdf_path']=str(args.output/'absent.pdf')
                elif label=='missing_body':changed.pop('source_question_body')
                elif label=='omit_terminal_records':records.pop()
                elif label=='omit_terminal_both':records.pop();proofrows.pop()
                elif label=='omit_middle_both':records.pop(-2);proofrows.pop(-2)
                elif label=='reverse_rows':records.reverse()
                elif label.startswith('meta_'):
                    key={'meta_ratio':'font_width_percent','meta_tracking':'letter_spacing_percent','meta_samplecount':'letter_spacing_sample_count'}[label]
                    changed['source_typography'][key]=90 if label=='meta_ratio' else -10 if label=='meta_tracking' else 999
                elif label=='record_text':records[-1]['text']+=' forged'
                elif label in ('synthetic_records_only','synthetic_proof_only'):
                    row=records[-1] if label=='synthetic_records_only' else proofrows[-1]
                    next(c for s in row['spans'] for c in s['chars'] if c['c']==' ')['synthetic']=True
                else:
                    for row in (records[-1],proofrows[-1]):
                        span=row['spans'][0]
                        if label=='flags_fractional':span['flags']=4.5
                        elif label=='flags_nan':span['flags']=float('nan')
                        elif label=='fake_font':span['font']='Arial'
                        elif label=='fake_size':span['size']+=1
                        else:
                            char=next(c for s in row['spans'] for c in s['chars'] if c['c']==' ')
                            if label=='synthetic_space':char['synthetic']=True
                            elif label=='space_origin':char['origin']=(0.,0.)
                            elif label=='space_bbox':char['bbox']=(0.,0.,0.,0.)
                check(not source_body_space_styles(changed),f'q{number}_source_rejects_{label}')
            wrapper=body.getparent().getparent().getparent();body_index=list(wrapper.iter(HP+'p')).index(body)
            labels=[f'font_{lang}' for lang in ('hangul','latin','hanja','japanese','other','symbol','user')]
            labels+=['height','bold','italic','ratio','tracking','relsize','offset','kerning','fontspace','symbolmark',
                     'outline','shadow','underline','strikeout','emboss','engrave','superscript','subscript',
                     'control','empty_badheight','metric_missing_language','font_missing_language','duplicate_style','joined_double_space']
            for label in labels:
                rect,h,l=deepcopy(wrapper),deepcopy(header),deepcopy(layout);p=list(rect.iter(HP+'p'))[body_index]
                styles={s.get('id'):s for s in h.iter(HH+'charPr')};run=next(r for r in p.findall(HP+'run') if (r.findtext(HP+'t') or '').strip())
                style=styles[run.get('charPrIDRef')]
                if label.startswith('font_') and label!='font_missing_language':
                    lang=label.removeprefix('font_');fontface=next(f for f in h.iter(HH+'fontface') if f.get('lang')==lang.upper())
                    old=next(f.get('face') for f in fontface if f.get('id')==style.find(HH+'fontRef').get(lang));alt=next(f for f in fontface if f.get('face')!=old)
                    style.find(HH+'fontRef').set(lang,alt.get('id'))
                elif label=='height':style.set('height',str(int(style.get('height'))+1))
                elif label in ('bold','italic','strikeout','emboss','engrave','superscript','subscript'):etree.SubElement(style,HH+label)
                elif label in ('ratio','tracking','relsize','offset'):
                    node=style.find(HH+{'tracking':'spacing','relsize':'relSz'}.get(label,label))
                    for key,value in list(node.attrib.items()):node.set(key,str(int(value)+1))
                elif label in ('kerning','fontspace','symbolmark'):style.set({'kerning':'useKerning','fontspace':'useFontSpace','symbolmark':'symMark'}[label],'1' if label!='symbolmark' else 'DOT_ABOVE')
                elif label in ('outline','shadow','underline'):style.find(HH+label).set('type','SOLID')
                elif label=='control':etree.SubElement(run,HP+'bookmark')
                elif label=='empty_badheight':
                    clone=deepcopy(style);clone.set('id',str(max(map(int,styles))+1));clone.set('height','nan');h.find('.//'+HH+'charProperties').append(clone)
                    p.insert(0,etree.Element(HP+'run',charPrIDRef=clone.get('id')));etree.SubElement(p[0],HP+'t').text=''
                elif label=='metric_missing_language':del style.find(HH+'ratio').attrib['other']
                elif label=='font_missing_language':del style.find(HH+'fontRef').attrib['other']
                elif label=='duplicate_style':h.find('.//'+HH+'charProperties').append(deepcopy(style))
                elif label=='joined_double_space':run[0].text=run[0].text.replace(' ','  ',1)
                prior=etree.tostring(rect),etree.tostring(h)
                check(source_body_space_styles(l,paragraph=p,header=h,page_width=page_width) is None,f'q{number}_native_context_rejects_{label}')
                common.para_style(h,p).find('.//'+HH+'margin/'+HC+'right').set('value','0')
                prior=etree.tostring(rect),etree.tostring(h)
                width=float(rect.find(HP+'sz').get('width'))
                check(restore_source_question_body_right([(p,l)],h,page_width,width)==0 and prior==(etree.tostring(rect),etree.tostring(h)),f'q{number}_consumer_rejects_{label}_atomically')
        result,count=common.right_guards(header,sections,[fixtures[21],fixtures[24]],page_width,check)
        report['existing_full_right_guard_negatives']=count
        if args.public:
            import fitz,rhwp
            from app.hwpx_writer_v2 import HwpxDocument
            from hwpx.oxml import HwpxOxmlParagraph
            old_native=rhwp.parse(str(args.hwpx));old_bytes=bytes(old_native.render_pdf());old_pdf=fitz.open(stream=old_bytes,filetype='pdf')
            glyphs=lambda pdf:[(index,c) for index,page in enumerate(pdf) for trace in page.get_texttrace() if trace.get('type')==0 and trace.get('opacity',1)>.99 for c in trace['chars'] if not chr(c[0]).isspace()]
            old_glyphs=glyphs(old_pdf);report['public']=[]
            for number in (21,24):
                doc=HwpxDocument.open(args.hwpx);section,draw=next((s,d) for s in doc.sections for d in s.element.iter(HP+'drawText') if d.get('name')==f'question:v1:q{number}')
                p=next(p for p in draw.iter(HP+'p') if common.direct_text(p)==fixtures[number]['stem'])
                old_text=common.direct_text(p);old_styles=common.styled_chars(header,p);old_margins=common.margins(header,p)
                following=common.direct_text(list(common.question(sections,number).iter(HP+'p'))[2])
                public=HwpxOxmlParagraph(p,section);last=next(r for r in reversed(public.runs) if r.text)
                addition=' Careful reading helps people understand complex ideas and consider a different perspective.'
                public.add_run(addition,char_pr_id_ref=last.element.get('charPrIDRef'));check(p.find(HP+'linesegarray') is None,f'q{number}_add_run_invalidates_cache')
                grown=args.output/f'q{number}-grown.hwpx';doc.save_to_path(grown);h,s=common.package(grown);p=list(common.question(s,number).iter(HP+'p'))[1]
                check(common.direct_text(p)==old_text+addition and common.margins(h,p)==old_margins and common.styled_chars(h,p)[:len(old_styles)]==old_styles,f'q{number}_public_preserves_complete_text_styles_margins')
                parsed=rhwp.parse(str(grown));payload=bytes(parsed.render_pdf());(args.output/f'q{number}-grown.pdf').write_bytes(payload);pdf=fitz.open(stream=payload,filetype='pdf');new_glyphs=glyphs(pdf)
                a,b=common.locate(old_glyphs,old_text)[0],common.locate(old_glyphs,following)[0];c,d=common.locate(new_glyphs,old_text+addition)[0],common.locate(new_glyphs,following)[0]
                advance=lambda target,origin,pdf:((target[0]-origin[0])*pdf[0].rect.height+target[1][2][1]-origin[1][2][1])*4/3
                movement=advance(d,c,pdf)-advance(b,a,old_pdf);check(movement>1,f'q{number}_following_choices_advance',pixels=movement)
                reopened=args.output/f'q{number}-reopened.hwpx';HwpxDocument.open(grown).save_to_path(reopened);h2,s2=common.package(reopened);p2=list(common.question(s2,number).iter(HP+'p'))[1];again=rhwp.parse(str(reopened))
                check(common.direct_text(p2)==old_text+addition and common.margins(h2,p2)==old_margins and common.styled_chars(h2,p2)==common.styled_chars(h,p),f'q{number}_reopen_preserves_text_styles_margins')
                check(again.page_count==parsed.page_count and all(again.render_svg(i)==parsed.render_svg(i) for i in range(parsed.page_count)),f'q{number}_reopen_all_pages_svg_exact')
                report['public'].append({'question':number,'pages':parsed.page_count,'choices_advance_px':movement})
        check(before==fingerprint(),'app_fingerprint_stable');report['ok']=True
    except Exception as exc:
        report['ok']=False;report['error']=repr(exc);raise
    finally:(args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    return 0
if __name__=='__main__':raise SystemExit(main())
