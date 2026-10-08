"""Source-frame native rows and atomic public-entrypoint guard regression.

Consumes a completed writer capture and its package without starting another
writer. The real raw PDF and original decoration assets are reopened for every
source proof. Only temporary XML clones are mutated by the negative cases.
"""
from copy import deepcopy
from pathlib import Path
import argparse,json,os,sys,zipfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--capture',type=Path,default=ROOT/'tmp/september-audit/grid-quality-ab/producer-capture.json')
parser.add_argument('--native',type=Path,default=ROOT/'tmp/september-audit/grid-quality-ab/fresh-baseline.hwpx')
parser.add_argument('--assets',type=Path,default=ROOT/'tmp/september-audit/grid-quality-ab/data')
parser.add_argument('--report',type=Path,default=ROOT/'tmp/september-audit/grid-y-producer-ab/entrypoint-negatives.json')
args=parser.parse_args()
if not args.capture.is_file() or not args.native.is_file() or not args.assets.is_dir():
    raise SystemExit('Completed writer capture, matching native package and source asset directory are required.')
os.environ['HWP_MAKE_DATA_DIR']=str(args.assets.resolve())
from lxml import etree
from app import storage
from app import pdf_source_frame_native_rows as module,pdf_table_paragraphs as frames
HP,HH=module.HP,module.HH
items=json.loads(args.capture.read_text(encoding='utf8'))
items=[a for a in items if a['layout'].get('source_frame_has_grid')]
with zipfile.ZipFile(args.native) as z:
    header=etree.fromstring(z.read('Contents/header.xml'))
    roots=[etree.fromstring(z.read(n)) for n in z.namelist() if n.startswith('Contents/section') and n.endswith('.xml')]
fixtures=[]
for a in items:
    p=next(p for r in roots for p in r.iter(HP+'p') if p.get('id')==a['paragraph_id'])
    plan=module.source_frame_native_rows(p,a['layout'],header,59528)
    assert plan,(a['question'],a['paragraph_id'])
    fixtures.append((p,a['layout']))
    staged,head=deepcopy(p),deepcopy(header)
    forbidden=lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError('original callback mutated staged attempt'))
    assert frames.restore_background_frame(staged,a['layout'],head,59528,22961,forbidden,forbidden)>0
    from app.pdf_native_typography import _fit_table_heights
    _fit_table_heights(staged,lambda table:False,head)
    assert int(staged.find(HP+'run/'+HP+'tbl/'+HP+'sz').get('height'))==plan['height']
    print('FRAME_POSITIVE',a['question'],plan['glyphs'],plan['top'],plan['required'],plan['height'],flush=True)
target,layout=fixtures[0]
cases=('source_text','source_omit_last','source_flags_fractional','source_flags_nan','source_size','source_face','source_origin','source_bbox',
       'source_baseline','source_page','source_crop','native_text','native_size','native_bold','native_face','native_ratio','native_tracking',
       'unknown_control','styled_empty','cache_height','cache_textpos','cache_spacing','cache_baseline','cache_width','cache_nan','native_effect',
       'meta_ratio_compensated','meta_tracking_compensated','meta_sample_count','bool_page','relsz','offset','use_kerning','use_fontspace','symmark','superscript_alias')
for reason in cases:
    p=deepcopy(target);given=deepcopy(layout);head=deepcopy(header)
    paragraph=p.find(HP+'run/'+HP+'tbl/'+HP+'tr/'+HP+'tc/'+HP+'subList/'+HP+'p')
    run=paragraph.find(HP+'run');cp=next(s for s in head.iter(HH+'charPr') if s.get('id')==run.get('charPrIDRef'))
    row=paragraph.find(HP+'linesegarray/'+HP+'lineseg');record=given['source_typography']['lines'][0];span=record['spans'][0]
    if reason=='source_text':record['text']='wrong'
    elif reason=='source_omit_last':given['source_typography']['lines'].pop()
    elif reason=='source_flags_fractional':span['flags']=.5
    elif reason=='source_flags_nan':span['flags']=float('nan')
    elif reason=='source_size':span['size']+=.1
    elif reason=='source_face':span['font']='TimesNewRoman'
    elif reason=='source_origin':span['chars'][0]['origin'][0]+=.1
    elif reason=='source_bbox':span['chars'][0]['bbox'][0]+=.1
    elif reason=='source_baseline':record['baseline_pt']+=.1
    elif reason=='source_page':given['source_page_index']=2
    elif reason=='source_crop':given['native_tables'][0]['bbox_pt'][1]+=.1
    elif reason=='native_text':run.find(HP+'t').text='wrong'
    elif reason=='native_size':cp.set('height','600')
    elif reason=='native_bold':etree.SubElement(cp,HH+'bold')
    elif reason=='native_face':
        for key in cp.find(HH+'fontRef').attrib:cp.find(HH+'fontRef').set(key,'0')
    elif reason=='native_ratio':
        for key in cp.find(HH+'ratio').attrib:cp.find(HH+'ratio').set(key,'90')
    elif reason=='native_tracking':
        for key in cp.find(HH+'spacing').attrib:cp.find(HH+'spacing').set(key,'-10')
    elif reason=='unknown_control':etree.SubElement(run,HP+'equation')
    elif reason=='styled_empty':
        empty=etree.SubElement(paragraph,HP+'run',charPrIDRef=run.get('charPrIDRef'));etree.SubElement(empty,HP+'t')
    elif reason=='cache_height':row.set('vertsize','600');row.set('textheight','600');row.set('baseline','510')
    elif reason=='cache_textpos':row.set('textpos','1')
    elif reason=='cache_spacing':row.set('spacing','-1')
    elif reason=='cache_baseline':row.set('baseline','9000')
    elif reason=='cache_width':row.set('horzsize','0')
    elif reason=='cache_nan':row.set('vertpos','nan')
    elif reason=='native_effect':etree.SubElement(cp,HH+'emboss')
    elif reason=='meta_ratio_compensated':
        given['source_typography']['font_width_percent']=90
        for style in head.iter(HH+'charPr'):
            for key in style.find(HH+'ratio').attrib:style.find(HH+'ratio').set(key,'90')
    elif reason=='meta_tracking_compensated':
        given['source_typography']['letter_spacing_percent']=-10
        for style in head.iter(HH+'charPr'):
            if style.get('id') in ('90','91','72'):
                for key in style.find(HH+'spacing').attrib:style.find(HH+'spacing').set(key,'-10')
    elif reason=='meta_sample_count':given['source_typography']['letter_spacing_sample_count']=4
    elif reason=='bool_page':given['source_page_index']=True
    elif reason in ('relsz','offset'):
        node=cp.find(HH+('relSz' if reason=='relsz' else 'offset'));node.set('latin','90' if reason=='relsz' else '1')
    elif reason in ('use_kerning','use_fontspace','symmark'):cp.set({'use_kerning':'useKerning','use_fontspace':'useFontSpace','symmark':'symMark'}[reason],'1')
    elif reason=='superscript_alias':etree.SubElement(cp,HH+'superscript')
    assert module.source_frame_native_rows(p,given,head,59528) is None,reason
    original_p,original_h=etree.tostring(p),etree.tostring(head)
    assert frames.restore_background_frame(p,given,head,59528,22961,forbidden,forbidden)==0,reason
    assert (etree.tostring(p),etree.tostring(head))==(original_p,original_h),reason+' mutated original root/header'
paragraph=etree.Element(HP+'p');cache=etree.SubElement(paragraph,HP+'linesegarray')
for start in (0,2):etree.SubElement(cache,HP+'lineseg',textpos=str(start),vertpos='0',vertsize='861',textheight='861',baseline='732',spacing='0',horzpos='0',horzsize='1000')
module._cache_bounds(paragraph,[(0,'😀',861),(2,'a',861)],3)
cache[1].set('textpos','1')
try:module._cache_bounds(paragraph,[(0,'😀',861),(2,'a',861)],3)
except ValueError:pass
else:raise AssertionError('UTF16 surrogate split accepted before normalization')
for failure in ('apply_after_styles','partial_restore'):
    p,head=deepcopy(target),deepcopy(header);before=etree.tostring(p),etree.tostring(head)
    original_apply=module.apply_source_frame_native_rows;original_restore=frames.restore_table_paragraphs
    try:
        if failure=='apply_after_styles':module.apply_source_frame_native_rows=lambda *args:False
        else:
            def partial(root,layout,header,*args,**kwargs):
                root.attrib['forged']='1';header.find('.//'+HH+'paraProperties').append(etree.Element(HH+'paraPr',id='999999'))
                return 0
            frames.restore_table_paragraphs=partial
        assert frames.restore_background_frame(p,layout,head,59528,22961,forbidden,forbidden)==0
        assert (etree.tostring(p),etree.tostring(head))==before
    finally:module.apply_source_frame_native_rows=original_apply;frames.restore_table_paragraphs=original_restore
header_cases=('missing_properties','empty_properties','duplicate_para_id','invalid_para_id','bad_para_base','removed_style','replaced_style')
for failure in header_cases:
    p,head=deepcopy(target),deepcopy(header);props=head.find('.//'+HH+'paraProperties')
    if failure=='missing_properties':props.getparent().remove(props)
    elif failure=='empty_properties':
        for child in list(props):props.remove(child)
    elif failure=='duplicate_para_id':props.append(deepcopy(props[0]))
    elif failure=='invalid_para_id':props[0].set('id','bad')
    elif failure=='bad_para_base':p.find('.//'+HP+'tc/'+HP+'subList/'+HP+'p').set('paraPrIDRef','999999')
    before=etree.tostring(p),etree.tostring(head);original=frames._restore_background_frame
    try:
        if failure in ('removed_style','replaced_style'):
            def invalid_staged(root,layout,header,*args,**kwargs):
                styles=header.find('.//'+HH+'paraProperties')
                if failure=='removed_style':styles.remove(styles[0])
                else:styles[0].set('condense','99')
                return 1
            frames._restore_background_frame=invalid_staged
        assert frames.restore_background_frame(p,layout,head,59528,22961,forbidden,forbidden)==0,failure
        assert (etree.tostring(p),etree.tostring(head))==before,failure
    finally:frames._restore_background_frame=original
report={'source_frames':len(fixtures),'negatives':list(cases)+['UTF16_surrogate_split','atomic_apply_after_styles','atomic_partial_restore']+list(header_cases),
        'negative_count':len(cases)+3+len(header_cases),'entrypoint_atomic':True,'candidate_only':False}
args.report.parent.mkdir(parents=True,exist_ok=True)
args.report.write_text(json.dumps(report,indent=2),encoding='utf8')
print('FRAME_ENTRYPOINT_NEGATIVES_PASS',report['negative_count'],flush=True)
