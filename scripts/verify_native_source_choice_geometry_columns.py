"""Independent synchronized source/native column permission regressions."""
from pathlib import Path
from copy import deepcopy
from itertools import groupby
import sys,json,runpy,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lxml import etree
from scripts.verify_native_source_question_body import package,question,HP,HH
from app.pdf_native_content import _source_typography
from app.pdf_source_line_cache import apply_source_line_cache
from hwpx.tools.question_reflow import update_positions
import fitz
MODULE=ROOT/'app/pdf_source_choice_geometry.py'
M=runpy.run_path(str(MODULE));plan=M['source_choice_group_plan']
OUT=ROOT/'tmp/september-exam-matrix/source-choice-geometry-production-native5'
D=json.loads((ROOT/'tmp/september-exam-matrix/choice-marker-gap-diagnostic/report.json').read_text(encoding='utf8'))
H,S=package(Path(D['native_hwpx']))
metadata=json.loads((ROOT/'tmp/september-exam-matrix/source-choice-geometry-native5/fresh-producer/metadata.json').read_text(encoding='utf8'))
groups=[list(v) for k,v in groupby(metadata,key=lambda i:(i.get('layout') or {}).get('question_group') if (i.get('layout') or {}).get('question_group_kind')=='question' else None) if k]
draws={d.get('name'):d for s in S for d in s.iter(HP+'drawText')}
selected=[g for g in groups if 'question:'+g[0]['layout']['question_group'] in draws and plan(H,draws['question:'+g[0]['layout']['question_group']],g)]
assert len(selected)==6,len(selected)

def synchronized(h,d,items,field,delta):
 width=59528;wrapper=float(d.getparent().find(HP+'sz').get('width'))
 paras={n.get('id'):n for n in h.iter(HH+'paraPr')}
 for p,item in zip(d.iter(HP+'p'),items):
  layout=item['layout']
  with fitz.open(layout['source_pdf_path']) as doc:_,rows=M['actual_source_records'](layout,doc)
  layout[field]+=delta
  layout['source_typography']=_source_typography(rows,{'column_left_pt':layout['column_left_pt'],'column_right_pt':layout['column_right_pt']})
  meta=layout['source_typography'];starts=[(r['bbox_pt'][0]-layout['column_left_pt'])*width/layout['source_page_width_pt'] for r in meta['lines']]
  left=max(0,round(min(starts)));indent=round(starts[0]-starts[1]) if len(starts)>1 else 0
  if abs(indent)>meta['font_size_pt']*width/layout['source_page_width_pt']*3:indent=0
  for margin in paras[p.get('paraPrIDRef')].iter(HH+'margin'):
   for edge in margin:
    if etree.QName(edge).localname in ('left','intent'):edge.set('value',str(left if etree.QName(edge).localname=='left' else indent))
  assert apply_source_line_cache(p,{**layout,'native_page_width':width,'native_indentation':(left,0,indent)},wrapper)
 update_positions(next(d.iter(HP+'p')).getparent(),paras)

results=[]
for group in selected:
 number=group[0]['layout']['question_number'];results.append({'question':number,'case':'actual_positive','pass':True})
 for field in ('column_left_pt','column_right_pt'):
  h=deepcopy(H);s=[deepcopy(x) for x in S];d=question(s,number);items=deepcopy(group)
  synchronized(h,d,items,field,-1)
  before=(etree.tostring(h),etree.tostring(d),json.dumps(items,ensure_ascii=False,sort_keys=True))
  accepted=plan(h,d,items)
  atomic=before==(etree.tostring(h),etree.tostring(d),json.dumps(items,ensure_ascii=False,sort_keys=True))
  results.append({'question':number,'case':'synchronized_'+field,'pass':accepted is None and atomic})
 for label,mutation in (
  ('native_margins',lambda d:(d.getroottree().getroot().find('.//'+HP+'pagePr/'+HP+'margin').set('left','6215'))),
  ('native_column_gap',lambda d:d.getroottree().getroot().find('.//'+HP+'colPr').set('sameGap','1690')),
  ('native_wrapper_offset',lambda d:d.getparent().find(HP+'pos').set('horzOffset','1')),
  ('native_wrapper_origin',lambda d:d.getparent().find(HP+'offset').set('x','1')),
  ('native_decimal_col_count',lambda d:d.getroottree().getroot().find('.//'+HP+'colPr').set('colCount','2.0')),
  ('native_exponent_col_count',lambda d:d.getroottree().getroot().find('.//'+HP+'colPr').set('colCount','2e0')),
  ('native_decimal_page_width',lambda d:d.getroottree().getroot().find('.//'+HP+'pagePr').set('width','59528.0')),
  ('native_decimal_wrapper_width',lambda d:d.getparent().find(HP+'sz').set('width','22961.0')),
  ('native_decimal_draw_width',lambda d:d.set('lastWidth','22961.0')),
  ('native_decimal_sublist_width',lambda d:d.find(HP+'subList').set('textWidth','22961.0'))):
  h=deepcopy(H);s=[deepcopy(x) for x in S];d=question(s,number);items=deepcopy(group);mutation(d)
  before=(etree.tostring(h),etree.tostring(d),json.dumps(items,ensure_ascii=False,sort_keys=True))
  accepted=plan(h,d,items);atomic=before==(etree.tostring(h),etree.tostring(d),json.dumps(items,ensure_ascii=False,sort_keys=True))
  results.append({'question':number,'case':label,'pass':accepted is None and atomic})
 h=deepcopy(H);s=[deepcopy(x) for x in S];d=question(s,number);items=deepcopy(group)
 run=next(p for p in d.iter(HP+'p') if ''.join(p.itertext()).startswith('①')).findall(HP+'run')[1]
 style=next(n for n in h.iter(HH+'charPr') if n.get('id')==run.get('charPrIDRef'))
 style.set('height',style.get('height')+'.0')
 before=(etree.tostring(h),etree.tostring(d));accepted=plan(h,d,items)
 results.append({'question':number,'case':'native_decimal_char_height','pass':accepted is None and before==(etree.tostring(h),etree.tostring(d))})
report={'checks':len(results),'passed':sum(r['pass'] for r in results),'failures':[r for r in results if not r['pass']],'results':results,'module_sha256':hashlib.sha256(MODULE.read_bytes()).hexdigest()}
(OUT/'column-negative.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print('COLUMN_GUARDS',report['checks'],report['passed'],report['failures'],flush=True)
assert not report['failures']
