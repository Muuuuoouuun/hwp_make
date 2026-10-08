"""Production whole-package ambiguity/resource/object rejection, with original-byte preservation."""
from pathlib import Path
from copy import deepcopy
import sys,runpy,json,hashlib,io,zipfile,warnings,struct,re
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tmp/renderer-tabs-fractional-20261008/candidate-site'))
import fitz
from lxml import etree
from scripts.verify_native_source_question_body import package,question,HP,HH
M=runpy.run_path(str(ROOT/'app/pdf_source_choice_geometry.py'));api=M['source_choice_geometry_bytes'];D=json.loads((ROOT/'tmp/september-exam-matrix/choice-marker-gap-diagnostic/report.json').read_text(encoding='utf8'));INPUT=Path(D['native_hwpx']);data=INPUT.read_bytes();H,S=package(INPUT);OUT=ROOT/'tmp/september-exam-matrix/source-choice-geometry-production-native5/atomic-fixtures';OUT.mkdir(parents=True,exist_ok=True)
candidate_before=hashlib.sha256((ROOT/'app/pdf_source_choice_geometry.py').read_bytes()).hexdigest();app=lambda:{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'app').rglob('*.py')};before=app();results=[]
def encode(header,sections):
 with zipfile.ZipFile(io.BytesIO(data)) as z:infos=z.infolist();values={i.filename:z.read(i.filename) for i in infos}
 values['Contents/header.xml']=etree.tostring(header)
 for i,s in enumerate(sections):values[f'Contents/section{i}.xml']=etree.tostring(s)
 b=io.BytesIO()
 with zipfile.ZipFile(b,'w') as z:
  for i in infos:z.writestr(i,values[i.filename])
 return b.getvalue()
def check(name,blob,groups):
 output,report=api(blob,groups);passed=output==blob and report['changed_groups']==0;results.append({'case':name,'pass':passed,'original_bytes_exact':output==blob,'changed_groups':report['changed_groups']});assert passed,(name,report)
groups=[q['items'] for q in D['questions'][:4]]
check('duplicate_source_group_IDs',data,groups+[deepcopy(groups[0])])
h=deepcopy(H);s=[deepcopy(v) for v in S];draw=question(s,D['questions'][0]['question']);draw.getparent().append(deepcopy(draw));check('duplicate_native_question_draw_name',encode(h,s),groups)
for tag,parent in [('charPr','charProperties'),('paraPr','paraProperties'),('fontface','fontfaces')]:
 h=deepcopy(H);s=[deepcopy(v) for v in S];node=next(h.iter(HH+tag));node.getparent().append(deepcopy(node));check('duplicate_native_'+tag+'_IDs',encode(h,s),groups)
h=deepcopy(H);s=[deepcopy(v) for v in S];node=next(h.iter(HH+'font'));node.getparent().append(deepcopy(node));check('duplicate_native_font_ID',encode(h,s),groups)
with zipfile.ZipFile(io.BytesIO(data)) as z:infos=z.infolist();values={i.filename:z.read(i.filename) for i in infos}
b=io.BytesIO()
with warnings.catch_warnings():
 warnings.simplefilter('ignore')
 with zipfile.ZipFile(b,'w') as z:
  for i in infos:z.writestr(i,values[i.filename])
  z.writestr('Contents/header.xml',values['Contents/header.xml'])
check('duplicate_ZIP_entry',b.getvalue(),groups)
h=deepcopy(H);s=[deepcopy(v) for v in S];node=next(h.iter(HH+'font'));alias=deepcopy(node);alias.set('id','0'+node.get('id'));node.getparent().append(alias);check('numeric_native_font_ID_alias',encode(h,s),groups)
b=io.BytesIO()
with zipfile.ZipFile(b,'w') as z:
 for i in infos:z.writestr(i,values[i.filename])
 z.writestr('Contents/./header.xml',values['Contents/header.xml'])
check('noncanonical_ZIP_alias',b.getvalue(),groups)
q=D['questions'][0];first=q['items'][0]['layout'];source=Path(first['source_pdf_path']);pageindex=first['source_page_index'];rows=[r for i in q['items'] for r in i['layout']['source_typography']['lines']];band=fitz.Rect(first['column_left_pt'],rows[0]['bbox_pt'][1],first['column_right_pt'],rows[-1]['bbox_pt'][3]);point=fitz.Point(band.x1-8,band.y0+8)
for kind in ('image','frame','new_prefix_answer_line','font_space_program'):
 doc=fitz.open(source);page=doc[pageindex]
 if kind=='image':
  pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,2,2),False);pix.clear_with(120);page.insert_image(fitz.Rect(point.x,point.y,point.x+4,point.y+4),pixmap=pix)
 elif kind=='frame':page.draw_rect(fitz.Rect(point.x-3,point.y,point.x+3,point.y+6),color=(0,0,0),width=.4)
 elif kind=='new_prefix_answer_line':
  path=next(d for d in page.get_drawings() if d['type']=='s' and d['rect'].y0>band.y0 and d['rect'].y0<band.y1 and len(d['items'])==1 and d['items'][0][0]=='l');_,a,c=path['items'][0];page.draw_line(a,c,color=(0,0,0),width=path['width'])
 else:
  from app.pdf_source_font_spaces import xref,face
  choice=next(i for i in q['items'] if i['text'].startswith('①'));span=choice['layout']['source_typography']['lines'][0]['spans'][1];font=next(f for f in page.get_fonts(full=True) if face(f[3])==face(span['font']));desc=int(re.search(r'([1-9]\d*) 0 R',doc.xref_get_key(font[0],'DescendantFonts')[1]).group(1));fd=xref(doc,desc,'FontDescriptor');programxref=xref(doc,fd,'FontFile2');program=bytearray(doc.xref_stream(programxref));ntables=struct.unpack_from('>H',program,4)[0];entry=next(12+16*n for n in range(ntables) if program[12+16*n:16+16*n]==b'hmtx');offset=struct.unpack_from('>I',program,entry+8)[0];assert struct.unpack_from('>H',program,offset+3*4)[0]==512;struct.pack_into('>H',program,offset+3*4,513);doc.update_stream(programxref,bytes(program))
 path=OUT/(kind+'.pdf');doc.save(path);doc.close();items=deepcopy(q['items'])
 for item in items:item['layout']['source_pdf_path']=str(path.resolve())
 check('actual_source_'+kind,data,[items])
 if kind=='font_space_program':
  layout=next(i['layout'] for i in items if i['text'].startswith('①'))
  actual_ok=True
  try:
   with fitz.open(path) as doc:M['actual_source_records'](layout,doc)
  except (ValueError,TypeError,KeyError,IndexError,RuntimeError):actual_ok=False
  results[-1]['raw_source_geometry_still_canonical']=actual_ok;results[-1]['actual_source_font_resource_plan_rejected']=M['source_choice_row_plan'](layout) is None
assert candidate_before==hashlib.sha256((ROOT/'app/pdf_source_choice_geometry.py').read_bytes()).hexdigest() and before==app()
report={'checks':len(results),'passed':sum(r['pass'] for r in results),'results':results,'candidate_sha256':candidate_before,'app_stable':True};(OUT.parent/'atomic-package-guards.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print('ATOMIC_PACKAGE_GUARDS',report,flush=True)
