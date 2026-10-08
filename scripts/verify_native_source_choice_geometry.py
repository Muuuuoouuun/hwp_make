"""Production atomic source/current-native guards for full single-choice geometry plans."""
from pathlib import Path
from copy import deepcopy
import sys,json,runpy,hashlib,math
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lxml import etree
from scripts.verify_native_source_question_body import package,question,HP,HH
M=runpy.run_path(str(ROOT/'app/pdf_source_choice_geometry.py'));plan=M['source_choice_group_plan']
D=json.loads((ROOT/'tmp/september-exam-matrix/choice-marker-gap-diagnostic/report.json').read_text(encoding='utf8'))
INPUT=Path(D['native_hwpx']);H,S=package(INPUT)
# Qualify live producer metadata as well as the serialized JSON fixture.
from app.pdf_native_content import _source_typography
import fitz
for q in D['questions'][:4]:
 for item in q['items']:
  layout=item['layout']
  with fitz.open(layout['source_pdf_path']) as doc:page,rows=M['actual_source_records'](layout,doc)
  layout['source_typography']=_source_typography(rows,{'column_left_pt':layout['column_left_pt'],'column_right_pt':layout['column_right_pt']})
OUT=ROOT/'tmp/september-exam-matrix/source-choice-geometry-production-native5';OUT.mkdir(exist_ok=True)
fingerprint=lambda:{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'app').rglob('*.py')}
before=fingerprint();candidate_before=hashlib.sha256((ROOT/'app/pdf_source_choice_geometry.py').read_bytes()).hexdigest();results=[]
def source(i):return i[1]['layout']
def row(i):return source(i)['source_typography']['lines'][0]
def span(i):return row(i)['spans'][1]
def choice(d):return next(p for p in d.iter(HP+'p') if ''.join(p.itertext()).startswith('①'))
def style(h,d):
 p=choice(d);run=p.findall(HP+'run')[1];return next(s for s in h.iter(HH+'charPr') if s.get('id')==run.get('charPrIDRef'))
def pstyle(h,d):
 p=choice(d);return next(s for s in h.iter(HH+'paraPr') if s.get('id')==p.get('paraPrIDRef'))
def firstcache(d):return choice(d).find(HP+'linesegarray')[0]
def mutate_space(h,d,tag,attr,value):
 p=choice(d)
 for run in p.findall(HP+'run'):
  value0=run.findtext(HP+'t','')
  if ' ' not in value0:continue
  split=value0.index(' ');index=p.index(run);base=next(s for s in h.iter(HH+'charPr') if s.get('id')==run.get('charPrIDRef'));s=deepcopy(base);sid=str(max(int(n.get('id')) for n in h.iter(HH+'charPr'))+1);s.set('id',sid)
  if tag is None:s.set(attr,value)
  elif value is None:etree.SubElement(s,HH+tag)
  else:s.find(HH+tag).set(attr,value)
  base.getparent().append(s)
  for j,text in enumerate((value0[:split],' ',value0[split+1:])):
   if not text:continue
   replacement=deepcopy(run);replacement[0].text=text
   if text==' ':replacement.set('charPrIDRef',sid)
   p.insert(index+j,replacement)
  p.remove(run);return
 raise AssertionError('no actual native choice space')
def mutate_native_space(d,value):
 for run in choice(d).findall(HP+'run'):
  node=run.find(HP+'t')
  if ' ' in (node.text or ''):node.text=node.text.replace(' ',value,1);return
 raise AssertionError('missing actual native space')
def prefix(i):return i[0]['layout']
cases=[]
for field,value in [('source_page_index',.5),('source_page_index',True),('source_page_width_pt',math.nan),('source_page_height_pt',1),('source_column',2),('column_left_pt',0),('question_number',99),('question_group','forged'),('question_variant',99),('source_literal_text',False),('native_tables',[{}]),('source_answer_blanks',[{}]),('source_inline_labels',[{}]),('source_native_graph',True),('source_illustrated_prose_frame',True)]:
 cases.append(('source_'+field,lambda h,d,i,f=field,v=value:source(i).__setitem__(f,v)))
for field,value in [('font_width_percent',101),('font_size_pt',13),('letter_spacing_percent',-2),('alignment','RIGHT'),('source_column_width_pt',999),('source_bbox_pt',[0,0,1,1])]:cases.append(('typography_'+field,lambda h,d,i,f=field,v=value:source(i)['source_typography'].__setitem__(f,v)))
for field,value in [('font','Arial'),('size',13),('flags',4.5),('color',1),('alpha',254),('text','forged')]:cases.append(('span_'+field,lambda h,d,i,f=field,v=value:span(i).__setitem__(f,v)))
for field,value in [('c','X'),('synthetic',True),('origin',[0,0]),('bbox',[0,0,1,1])]:cases.append(('char_'+field,lambda h,d,i,f=field,v=value:span(i)['chars'][0].__setitem__(f,v)))
cases += [('omit_prompt',lambda h,d,i:i.pop(0)),('choices_only',lambda h,d,i:i.__setitem__(slice(None),[x for x in i if x['text'].startswith(tuple('①②③④⑤'))])),('omit_final_choice',lambda h,d,i:i.pop()),('reverse_items',lambda h,d,i:i.reverse()),('item_image',lambda h,d,i:i[1].__setitem__('image_paths',['unsupported.png'])),('item_table',lambda h,d,i:i[1].__setitem__('tables',[{}])),('native_owner',lambda h,d,i:d.set('name','question:forged')),('wrapper_width',lambda h,d,i:d.getparent().find(HP+'sz').set('width','20000')),('draw_width',lambda h,d,i:d.set('lastWidth','20000')),('sublist_width',lambda h,d,i:choice(d).getparent().set('textWidth','20000')),('native_duplicate_cache',lambda h,d,i:choice(d).append(deepcopy(choice(d).find(HP+'linesegarray')))),('native_control',lambda h,d,i:choice(d).find(HP+'run').append(etree.Element(HP+'ctrl'))),('native_tab',lambda h,d,i:choice(d).find(HP+'run/'+HP+'t').append(etree.Element(HP+'tab'))),('native_nbsp',lambda h,d,i:mutate_native_space(d,'\u00a0')),('native_double_space',lambda h,d,i:mutate_native_space(d,'  ')),('native_choice_text',lambda h,d,i:choice(d).findall(HP+'run')[1][0].__setattr__('text','X'+choice(d).findall(HP+'run')[1][0].text)),('paragraph_align',lambda h,d,i:pstyle(h,d).find(HH+'align').set('horizontal','RIGHT')),('paragraph_auto_spacing',lambda h,d,i:pstyle(h,d).find(HH+'autoSpacing').set('eAsianEng','1')),('paragraph_line_spacing',lambda h,d,i:pstyle(h,d).find('.//'+HH+'lineSpacing').set('value','170')),('paragraph_tab_definition',lambda h,d,i:pstyle(h,d).set('tabPrIDRef','1')),('paragraph_break',lambda h,d,i:choice(d).set('pageBreak','1'))]
for f in ('vertpos','vertsize','textheight','baseline','spacing','textpos','horzpos','horzsize','flags'):
 cases.append(('native_cache_'+f,lambda h,d,i,k=f:firstcache(d).set(k,str(int(firstcache(d).get(k,'0'))+1))))
for f,v in [('height','871'),('textColor','#123456'),('shadeColor','#FF0000'),('useKerning','1'),('useFontSpace','1'),('symMark','DOT')]:cases.append(('native_style_'+f,lambda h,d,i,k=f,v=v:style(h,d).set(k,v)))
for tag in ('bold','italic','emboss','engrave'):cases.append(('native_effect_'+tag,lambda h,d,i,t=tag:etree.SubElement(style(h,d),HH+t)))
for tag,key,value in [('outline','type','SOLID'),('shadow','type','DROP'),('underline','type','BOTTOM')]:cases.append(('native_effect_'+tag,lambda h,d,i,t=tag,k=key,v=value:style(h,d).find(HH+t).set(k,v)))
for lang in M['LANGS']:
 cases.append(('native_font_'+lang,lambda h,d,i,l=lang:style(h,d).find(HH+'fontRef').set(l,'0')))
 cases.append(('space_font_'+lang,lambda h,d,i,l=lang:mutate_space(h,d,'fontRef',l,'0')))
for tag,key,value in [('ratio','latin','99'),('spacing','hangul','1'),('relSz','latin','101'),('offset','other','1')]:cases.append(('native_metric_'+tag,lambda h,d,i,t=tag,k=key,v=value:style(h,d).find(HH+t).set(k,v)))
for tag,key,value in [(None,'height','871'),('bold',None,None),('italic',None,None)]:cases.append(('space_'+str(tag or key),lambda h,d,i,t=tag,k=key,v=value:mutate_space(h,d,t,k,v)))
cases += [
 ('numeric_charPr_alias',lambda h,d,i:next(h.iter(HH+'charProperties')).append((lambda n:(n.set('id','0'+n.get('id')),n)[1])(deepcopy(style(h,d))))),
 ('numeric_paraPr_alias',lambda h,d,i:next(h.iter(HH+'paraProperties')).append((lambda n:(n.set('id','0'+n.get('id')),n)[1])(deepcopy(pstyle(h,d))))),
 ('duplicate_charPr_id',lambda h,d,i:next(h.iter(HH+'charProperties')).append(deepcopy(style(h,d)))),
 ('duplicate_paraPr_id',lambda h,d,i:next(h.iter(HH+'paraProperties')).append(deepcopy(pstyle(h,d)))),
 ('duplicate_fontface',lambda h,d,i:next(h.iter(HH+'fontface')).getparent().append(deepcopy(next(h.iter(HH+'fontface'))))),
 ('duplicate_font_id',lambda h,d,i:next(h.iter(HH+'fontface')).append(deepcopy(next(h.iter(HH+'font'))))),
 ('duplicate_underline',lambda h,d,i:etree.SubElement(style(h,d),HH+'underline',type='BOTTOM',shape='SOLID',color='#000000')),
 ('duplicate_fontRef',lambda h,d,i:style(h,d).append(deepcopy(style(h,d).find(HH+'fontRef')))),
 ('foreign_underline',lambda h,d,i:etree.SubElement(style(h,d),'{urn:forged}underline',type='BOTTOM')),
 ('foreign_run',lambda h,d,i:choice(d).append(etree.Element('{urn:forged}run'))),
 ('native_margin_fork',lambda h,d,i:list(pstyle(h,d).iter(HH+'margin'))[-1][0].set('value','123')),
 ('native_duplicate_paragraph',lambda h,d,i:choice(d).getparent().append(deepcopy(choice(d)))),
 ]
for q in D['questions'][:4]:
 accepted=plan(H,question(S,q['question']),q['items']);assert accepted and accepted['leading_permitted']==(q['question']!=14)
 results.append({'question':q['question'],'case':'actual_positive','pass':True,'leading':accepted['leading_permitted']})
 for label,mutate in cases:
  h=deepcopy(H);secs=[deepcopy(s) for s in S];d=question(secs,q['question']);items=deepcopy(q['items']);mutate(h,d,items)
  serialized=(etree.tostring(h),[etree.tostring(s) for s in secs],json.dumps(items,ensure_ascii=False,sort_keys=True))
  returned=plan(h,d,items)
  atomic=serialized==(etree.tostring(h),[etree.tostring(s) for s in secs],json.dumps(items,ensure_ascii=False,sort_keys=True))
  results.append({'question':q['question'],'case':label,'pass':returned is None and atomic,'rejected':returned is None,'atomic':atomic})
  if returned is not None:print('ACCEPTED MUTANT',q['question'],label,flush=True)
 print('GROUP_GUARDS',q['question'],len(cases),flush=True)
assert before==fingerprint();assert candidate_before==hashlib.sha256((ROOT/'app/pdf_source_choice_geometry.py').read_bytes()).hexdigest();report={'checks':len(results),'passed':sum(r['pass'] for r in results),'failures':[r for r in results if not r['pass']],'results':results,'app_stable':True,'candidate_sha256':hashlib.sha256((ROOT/'app/pdf_source_choice_geometry.py').read_bytes()).hexdigest()}
(OUT/'guards.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print('ATOMIC_GUARDS',report['checks'],report['passed'],'failures',len(report['failures']),flush=True)
assert not report['failures']
