"""Preserve proved PDF choice spacing in editable native paragraphs.

Wordspace/marker-gap permission and leading permission are separate. These
plans use actual raw PDF glyphs, actual source fonts and canonical native caches.
The font probe/commit phase is deliberately separate so a rejected plan has
no partial XML edits. Native source-font ink fidelity is not inferred from origins.
"""
from pathlib import Path
from copy import deepcopy
import hashlib,json,math,re
import fitz
from lxml import etree
from functools import lru_cache
HP='{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HH='{http://www.hancom.co.kr/hwpml/2011/head}'
LANGS=('hangul','latin','hanja','japanese','other','symbol','user')


@lru_cache(maxsize=4)
def _actual_column_rails(path, digest):
 """Immutable source rails, independently segmented from the actual PDF."""
 from app.pdf_native_content import extract_native_content
 from app import storage
 from tempfile import TemporaryDirectory
 source=Path(path)
 if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:_fail('source changed before column proof')
 # The general extractor materializes images. Its independent rail proof
 # must not leave another set of uploads or alter the caller's upload scope.
 data_root=storage.DATA_DIR.resolve();data_root.mkdir(parents=True,exist_ok=True)
 temporary=TemporaryDirectory(prefix='.source-choice-rails-',dir=str(data_root))
 temporary_root=Path(temporary.name).resolve()
 if temporary_root==data_root or temporary_root.parent!=data_root or not temporary_root.is_relative_to(data_root):_fail('unsafe source rail temporary directory')
 # Start automatic recursive cleanup only after the absolute target has
 # been verified as a fresh direct child of the explicitly intended root.
 with temporary:
  with storage.scoped_upload_directory(temporary_root):
   items,_=extract_native_content(source)
 rails={}
 for item in items:
  layout=item.get('layout') or {}
  if layout.get('column_left_pt') is None:continue
  index=_integer(item['source_page'])-1;column=_integer(layout['source_column'])
  if layout.get('source_page_index',index)!=index:_fail('actual source page ownership')
  record=(_finite(layout['column_left_pt']),_finite(layout['column_right_pt']),
          _finite(layout['source_page_width_pt']),_finite(layout['source_page_height_pt']))
  if column not in (1,2) or _integer(layout['column_count'])!=2:_fail('unsupported actual source columns')
  key=(index,column)
  if key in rails and rails[key]!=record:_fail('ambiguous actual source column rail')
  rails[key]=record
 if not rails or hashlib.sha256(source.read_bytes()).hexdigest()!=digest:_fail('source changed during column proof')
 return tuple((index,column,*record) for (index,column),record in sorted(rails.items()))


def _source_native_column_proof(layout, section, wrapper, width):
 """Bind supplied rails and current native placement to independent source rails."""
 from app import hwpx_writer_v2 as writer
 from app.pdf_source_spacing import apply_source_column_rails
 path=Path(layout['source_pdf_path']).resolve()
 rails=_actual_column_rails(str(path),hashlib.sha256(path.read_bytes()).hexdigest())
 index=_integer(layout['source_page_index']);column=_integer(layout['source_column'])
 actual=[r for r in rails if r[:2]==(index,column)]
 expected=(_finite(layout['column_left_pt']),_finite(layout['column_right_pt']),
           _finite(layout['source_page_width_pt']),_finite(layout['source_page_height_pt']))
 if len(actual)!=1 or actual[0][2:]!=expected:_fail('nonactual source column rails')
 if width!=writer._A4_WIDTH_HWP:_fail('unsupported native source page width')
 pages=section.findall('.//'+HP+'pagePr')
 if len(pages)!=1 or len(pages[0].findall(HP+'margin'))!=1:_fail('ambiguous native page geometry')
 margin=pages[0].find(HP+'margin');columns=list(section.iter(HP+'colPr'))
 if not columns or any(_native_integer(c.get('colCount'))!=2 or c.get('sameSz') not in ('true','1')
                       or c.get('type')!='NEWSPAPER' or c.get('layout')!='LEFT' for c in columns):_fail('unsupported native column structure')
 # Replay the producer's horizontal source-column pass from its original
 # source-layout width contract, using only the freshly segmented PDF rails.
 replay=etree.Element('section');page=etree.SubElement(replay,HP+'pagePr',width=str(width))
 replay_margin=etree.SubElement(page,HP+'margin',
    left=str(writer._mm_to_hwp(writer._KICE_SOURCE_MARGIN_LEFT_MM)),
    right=str(writer._mm_to_hwp(writer._KICE_SOURCE_MARGIN_RIGHT_MM)))
 replay_col=etree.SubElement(replay,HP+'colPr',colCount='2',
    sameGap=str(writer._mm_to_hwp(writer._KICE_SOURCE_COLUMN_GAP_MM)))
 source_items=[{'source_page':r[0]+1,'layout':{'source_column':r[1],
                  'column_left_pt':r[2],'source_page_width_pt':r[4]}} for r in rails]
 if not apply_source_column_rails(replay,source_items):_fail('unproved native column replay')
 if any(margin.get(k)!=replay_margin.get(k) for k in ('left','right')) or margin.get('gutter')!='0':_fail('noncanonical native source column margins')
 if any(c.get('sameGap')!=replay_col.get('sameGap') for c in columns):_fail('noncanonical native source column gap')
 positions=wrapper.findall(HP+'pos');offsets=wrapper.findall(HP+'offset')
 if len(positions)!=1 or len(offsets)!=1:_fail('ambiguous native wrapper placement')
 pos=positions[0]
 if any(pos.get(k)!=v for k,v in {'treatAsChar':'1','flowWithText':'1','horzRelTo':'COLUMN',
                                'horzAlign':'LEFT','horzOffset':'0'}.items()) or offsets[0].get('x')!='0':_fail('native wrapper horizontal placement')
 return True


def _fail(message):raise ValueError(message)
def _finite(v):
 if isinstance(v,bool):_fail('boolean coordinate')
 v=float(v)
 if not math.isfinite(v):_fail('nonfinite coordinate')
 return v
def _integer(v):
 n=_finite(v)
 if n!=int(n):_fail('fractional integer')
 return int(n)
def _native_integer(v):
 # Rust integer parsers do not accept decimal/exponent XML lexemes even
 # when their numerical Python value is integral.
 if not isinstance(v,str) or re.fullmatch(r'0|-?[1-9]\d*',v) is None:_fail('noncanonical native integer')
 return int(v)
def _text(p):return ''.join(r.findtext(HP+'t','') for r in p.findall(HP+'run'))
def _json(v):return json.loads(json.dumps(v,ensure_ascii=False))
def _unique(items,key,label):
 result={}
 for item in items:
  identifier=key(item)
  if identifier is None or identifier in result:_fail('ambiguous '+label)
  result[identifier]=item
 return result

def _native_id(node):
 value=node.get('id')
 if not isinstance(value,str) or re.fullmatch(r'0|[1-9]\d*',value) is None or int(value)>4294967295:_fail('noncanonical native numeric ID')
 return value

def _zip_name(info):
 from pathlib import PurePosixPath
 value=info.filename
 normalized=PurePosixPath(value.replace('\\','/')).as_posix()+('/' if info.is_dir() else '')
 if value!=normalized or value.startswith('/') or '..' in PurePosixPath(normalized).parts:_fail('noncanonical ZIP entry')
 return value

def _header_namespaces(header):
 names={'charPr','charProperties','fontface','fontfaces','font','paraPr','paraProperties','ratio','spacing','fontRef','relSz','offset','underline','strikeout','outline','shadow','bold','italic','emboss','engrave'}
 for node in header.iter():
  name=etree.QName(node)
  if name.localname in names and node.tag!=HH+name.localname:_fail('foreign native header namespace')

def _stylemap(header):
 _header_namespaces(header)
 return _unique(header.iter(HH+'charPr'),_native_id,'native charPr IDs')

def _fontmap(header):
 faces=_unique(header.iter(HH+'fontface'),lambda f:str(f.get('lang')).lower(),'native fontface languages')
 if set(faces)!=set(LANGS):_fail('native fontface language coverage')
 result={}
 for lang,fontface in faces.items():
  fonts=_unique(fontface.findall(HH+'font'),_native_id,'native font IDs')
  result[lang]={identifier:font.get('face') for identifier,font in fonts.items()}
 return result


def actual_source_records(layout,document):
 from app.pdf_layout_writer import _iter_text_lines
 from app.pdf_native_content import _source_typography
 from app.pdf_source_question_body import _line_proof
 if (layout.get('source_literal_text') is not True or layout.get('native_tables')
     or layout.get('source_answer_blanks') or layout.get('source_inline_labels')
     or layout.get('source_native_graph') or layout.get('source_illustrated_prose_frame')):_fail('unsupported source controls')
 index=_integer(layout['source_page_index'])
 if not 0<=index<len(document):_fail('source page index')
 page=document[index]
 if (_finite(layout['source_page_width_pt'])!=page.rect.width
     or _finite(layout['source_page_height_pt'])!=page.rect.height):_fail('source page geometry')
 meta=layout['source_typography'];records=meta['lines']
 if not records:_fail('empty source paragraph')
 actual=_iter_text_lines(page);signatures=[_line_proof(r)[0] for r in actual];rows=[]
 raw=[r for b in page.get_text('rawdict',flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks'] for r in b.get('lines',[])]
 for record in records:
  signature=_line_proof({'bbox':record['bbox_pt'],'spans':record['spans']})[0]
  if signatures.count(signature)!=1:_fail('source row is not unique and actual')
  row=actual[signatures.index(signature)];rows.append(row)
  originals=[r for r in raw if tuple(r['bbox'])==tuple(record['bbox_pt'])]
  if len(originals)!=1 or originals[0]['wmode']!=0 or tuple(originals[0]['dir'])!=(1.,0.):_fail('unsupported source row direction')
 canonical=_source_typography(rows,{'column_left_pt':layout['column_left_pt'],'column_right_pt':layout['column_right_pt']})
 if _json(canonical)!=_json(meta):_fail('noncanonical source typography')
 traces=[(t,c) for t in page.get_texttrace() for c in t['chars']]
 for row in rows:
  for span in row['spans']:
   if span.get('color')!=0 or span.get('alpha')!=255 or _integer(span['flags']) not in (4,6):_fail('unsupported source paint/style')
   axis=[]
   for ch in span['chars']:
    if ch.get('synthetic') is not False:
     if ch['c'].isspace():continue
     _fail('synthetic visible source character')
    matches=[(t,c) for t,c in traces if c[0]==ord(ch['c']) and t['font']==span['font'] and max(abs(a-b) for a,b in zip(c[2],ch['origin']))<.0001]
    if len(matches)!=1:_fail('source glyph paint is not unique')
    t,c=matches[0]
    if (t['type']!=0 or t['opacity']!=1 or t['wmode']!=0 or tuple(t['dir'])!=(1.,0.) or t['flags']!=span['flags']):_fail('unsupported source glyph trace')
    axis.append(t['size']/span['size']*100)
   if not axis:
    if all(c['c'].isspace() and c.get('synthetic') is True for c in span['chars']):continue
    _fail('missing actual source glyph trace')
   if not all(math.isfinite(n) and 80<=n<=110 for n in axis) or max(axis)-min(axis)>.01:_fail('inconsistent actual source axis')
 return page,rows


def source_choice_row_plan(layout,*,native_page_width=59528):
 """Pure actual source plan: gap target, actual wordspace cursors and evidence."""
 from app.pdf_native_typography import _font_name
 from app.pdf_layout_writer import _pdf_output_text
 from app.pdf_source_font_spaces import face,xref,cmap_space_cid,pdf_cid_width,ttf_space_width
 try:
  native_page_width=_integer(native_page_width)
  if native_page_width<=0:_fail('native page width')
  with fitz.open(layout['source_pdf_path']) as doc:
   page,rows=actual_source_records(layout,doc)
   if len(rows)!=1:_fail('not one complete choice row')
   spans=rows[0]['spans'];chars=[(s,c) for s in spans for c in s['chars']]
   value=_pdf_output_text(''.join(c['c'] for s,c in chars))
   if not value or value[0] not in '①②③④⑤' or value!=value.strip() or len(re.findall('[①-⑤]',value))!=1:_fail('unsupported choice marker')
   if len(spans)<2 or spans[0]['text']!=value[0] or chars[1][1]['c'].isspace():_fail('source marker/letter boundary')
   if any(_font_name(s['font'])!='Times New Roman' or s['flags']!=4 for s in spans[1:]):_fail('choice is not regular Times')
   if any(re.search('[가-힣]',s['text']) for s in spans[1:]):_fail('not ordinary English choice')
   scale=native_page_width/page.rect.width;target=(chars[1][1]['origin'][0]-chars[0][1]['origin'][0])*scale/75
   size=spans[1]['size']*scale/75
   if not math.isfinite(target) or not .5*size<target<2*size:_fail('source marker gap is not ordinary')
   cursor=0;positions={};font_evidence=[]
   for span in spans:
    if _font_name(span['font'])!='Times New Roman':cursor+=sum(not c['c'].isspace() for c in span['chars']);continue
    resources=[f for f in page.get_fonts(full=True) if face(f[3])==face(span['font'])]
    if len(resources)!=1:_fail('ambiguous actual Times resource')
    resource=resources[0];font_xref,extension,kind,basefont=resource[:4]
    if extension!='ttf' or kind!='Type0' or doc.xref_get_key(font_xref,'Encoding')!=('name','/Identity-H'):_fail('unsupported actual font')
    k,v=doc.xref_get_key(font_xref,'DescendantFonts');m=re.fullmatch(r'\[\s*([1-9]\d*) 0 R\s*\]',v)
    if k!='array' or not m:_fail('actual descendant font')
    descendant=int(m[1])
    if doc.xref_get_key(descendant,'CIDToGIDMap')!=('name','/Identity'):_fail('nonidentity glyph map')
    cid=cmap_space_cid(doc.xref_stream(xref(doc,font_xref,'ToUnicode')));k,widths=doc.xref_get_key(descendant,'W')
    if k!='array':_fail('font widths')
    pdf_cid_width(widths,cid);name,ext,kind,program=doc.extract_font(font_xref)
    if ext!='ttf' or face(name)!=face(span['font']) or program!=doc.xref_stream(xref(doc,xref(doc,descendant,'FontDescriptor'),'FontFile2')):_fail('actual font program identity')
    metrics=ttf_space_width(program,cid);font_evidence.append({'source_face':span['font'],'xref':font_xref,'space_cid_gid':cid,**metrics})
    traces=[(t,c) for t in page.get_texttrace() if t['type']==0 and t['opacity']==1 and t['font']==span['font'] and t['flags']==span['flags'] and t['wmode']==0 and tuple(t['dir'])==(1.,0.) for c in t['chars']]
    for ix,ch in enumerate(span['chars']):
     if ch['c']==' ':
      if ch.get('synthetic') is not False:_fail('synthetic source wordspace')
      if not 0<ix<len(span['chars'])-1 or span['chars'][ix-1]['c'].isspace() or span['chars'][ix+1]['c'].isspace():_fail('wordspace neighbors')
      matches=[(t,c) for t,c in traces if c[0]==32 and c[1]==cid and max(abs(a-b) for a,b in zip(c[2],ch['origin']))<.0001]
      if len(matches)!=1 or abs(matches[0][0]['size']-span['size'])>.0001 or abs((ch['bbox'][2]-ch['bbox'][0])/span['size']-.25)>.0001:_fail('actual quarter-em space trace')
      following=span['chars'][ix+1];advance=(following['origin'][0]-ch['origin'][0])/span['size']
      if abs(following['origin'][1]-ch['origin'][1])>.0001 or not math.isfinite(advance) or not 70/400<=advance<=.35:_fail('actual wordspace advance')
      height=round(span['size']*scale)
      # Native embedded space starts at floor(height/2), then width ratio,
      # integer-percentage tracking and the per-character minimum clamp apply.
      candidates=[]
      for ratio in range(70,111):
       for tracking in range(-50,51):
        base=(height//2)*ratio/100;predicted=max(base+height*tracking/100,base*.5)/height
        candidates.append((abs(predicted-advance),abs(ratio-80),abs(tracking+15),ratio,tracking,predicted))
      error,_,_,ratio,tracking,predicted=min(candidates)
      if error>.005 or cursor in positions:_fail('unrepresentable or duplicate actual wordspace')
      positions[cursor]={'ratio':ratio,'tracking':tracking,'actual_advance_em':advance,'native_predicted_em':predicted,'height':height}
     elif ch['c'].isspace():_fail('foreign source whitespace')
     if not ch['c'].isspace():cursor+=1
   return {'marker':value[0],'text':value,'target_marker_advance_px':target,'spaces':positions,'font_evidence':font_evidence,'source_nonspace_characters':cursor}
 except (ValueError,TypeError,KeyError,IndexError,AttributeError,OverflowError,RuntimeError,OSError,UnicodeError):return None


def _plain(style,header):
 children=[etree.QName(c).localname for c in style]
 if len(children)!=len(set(children)) or any(c.tag!=HH+etree.QName(c).localname for c in style):_fail('ambiguous native character style nodes')
 borderid=style.get('borderFillIDRef','0')
 if borderid!='0':
  borders=[b for b in header.iter(HH+'borderFill') if b.get('id')==borderid]
  if len(borders)!=1:_fail('native border reference')
  border=borders[0]
  if any(border.get(k,default)!=default for k,default in (('threeD','0'),('shadow','0'),('centerLine','NONE'),('breakCellSeparateLine','0'))):_fail('native border effects')
  allowed_border={'slash','backSlash','leftBorder','rightBorder','topBorder','bottomBorder','diagonal','fillBrush'}
  if any(etree.QName(c).localname not in allowed_border for c in border):_fail('native border structure')
  for name in ('slash','backSlash','leftBorder','rightBorder','topBorder','bottomBorder'):
   nodes=[c for c in border if etree.QName(c).localname==name]
   if len(nodes)!=1 or nodes[0].get('type')!='NONE':_fail('native visible border')
  fills=[c for c in border if etree.QName(c).localname=='fillBrush']
  if len(fills)>1:_fail('duplicate native fill')
  if fills:
   fill=fills[0]
   if len(fill)!=1 or etree.QName(fill[0]).localname!='winBrush' or len(fill[0]) or fill[0].get('faceColor')!='none' or fill[0].get('hatchStyle') is not None:_fail('native visible fill')

 if (style.get('textColor')!='#000000' or style.get('shadeColor','none').lower()!='none'
     or style.get('useFontSpace','0') not in ('0','false') or style.get('useKerning','0') not in ('0','false')
     or style.get('symMark','NONE')!='NONE'):_fail('native paint effects')
 allowed={'fontRef','ratio','spacing','relSz','offset','underline','strikeout','outline','shadow','bold','italic'}
 if any(etree.QName(c).localname not in allowed for c in style):_fail('unsupported native style node')
 for tag,key,value in (('underline','type','NONE'),('strikeout','shape','NONE'),('outline','type','NONE'),('shadow','type','NONE')):
  n=style.find(HH+tag)
  if n is not None and n.get(key)!=value:_fail('native ink effect')
 for tag,expected in (('relSz',100),('offset',0)):
  n=style.find(HH+tag)
  if n is None or set(n.attrib)!=set(LANGS) or any(_native_integer(n.get(l))!=expected for l in LANGS):_fail('native size/baseline metrics')
 for tag,low,high in (('ratio',70,110),('spacing',-50,50)):
  n=style.find(HH+tag)
  if n is None or set(n.attrib)!=set(LANGS) or any(not low<=_native_integer(n.get(l))<=high for l in LANGS):_fail('native language metrics')


def _paragraph_plain(p,style,meta,header):
 if any(p.get(k,'0')!='0' for k in ('pageBreak','columnBreak','merged')) or p.get('styleIDRef')!='0':_fail('native paragraph break/style')
 expected={'tabPrIDRef':'0','condense':'0','fontLineHeight':'0','snapToGrid':'1','suppressLineNumbers':'0','checked':'0','textDir':'LTR'}
 if any(style.get(k)!=v for k,v in expected.items()) or set(style.attrib)!=set(expected)|{'id'}:_fail('unsupported native paragraph metrics')
 align=style.find(HH+'align')
 if align is None or dict(align.attrib)!={'horizontal':meta['alignment'],'vertical':'BASELINE'}:_fail('native source alignment')
 for tag,attrs in (('heading',{'type':'NONE','idRef':'0','level':'0'}),('autoSpacing',{'eAsianEng':'0','eAsianNum':'0'}),('breakSetting',{'breakLatinWord':'KEEP_WORD','breakNonLatinWord':'BREAK_WORD','widowOrphan':'0','keepWithNext':'0','keepLines':'0','pageBreakBefore':'0','lineWrap':'BREAK'})):
  nodes=style.findall(HH+tag)
  if len(nodes)!=1 or dict(nodes[0].attrib)!=attrs or len(nodes[0]):_fail('native paragraph effect')
 if len(style.findall(HH+'align'))!=1 or any(etree.QName(c).localname not in {'align','heading','breakSetting','autoSpacing','switch','border'} for c in style):_fail('native paragraph structure')
 percent=max(100,min(250,round((meta.get('line_spacing_pt') or meta['font_size_pt']*1.5)*100/meta['font_size_pt'])))
 margins=list(style.iter(HH+'margin'))
 if len(margins)!=2:_fail('native margin alternatives')
 profiles=[]
 for margin in margins:
  if len(margin)!=5 or {etree.QName(c).localname for c in margin}!={'intent','left','right','prev','next'}:_fail('native margin structure')
  if any(set(c.attrib)!={'value','unit'} or c.get('unit')!='HWPUNIT' for c in margin):_fail('native margin unit')
  profiles.append({etree.QName(c).localname:_native_integer(c.get('value')) for c in margin})
 if profiles[0]!=profiles[1]:_fail('native margin alternative mismatch')
 spacings=list(style.iter(HH+'lineSpacing'))
 if len(spacings)!=2 or any(dict(n.attrib)!={'type':'PERCENT','value':str(percent),'unit':'PERCENT'} for n in spacings):_fail('native source line spacing')
 border=style.find(HH+'border')
 if border is None or any(border.get(k)!='0' for k in ('offsetLeft','offsetRight','offsetTop','offsetBottom','connect','ignoreMargin')):_fail('native paragraph border offsets')
 # Reuse the resolved no-paint border proof without weakening actual charPr checks.
 surrogate=etree.Element(HH+'charPr',textColor='#000000',borderFillIDRef=border.get('borderFillIDRef','0'))
 for tag,value in (('relSz','100'),('offset','0'),('ratio','100'),('spacing','0')):etree.SubElement(surrogate,HH+tag,**{l:value for l in LANGS})
 _plain(surrogate,header)


def source_choice_group_plan(header,draw,items,*,native_page_width=59528):
 """Atomically prove full source/native ownership, styles and original caches.

 Return None for unsupported source/control/cache/style inputs. A successful
 row plan permits gap/wordspaces. leading_permitted additionally requires
 every prefix native glyph height to equal its actual source height.
 """
 from app.pdf_native_typography import _font_name
 from app.pdf_source_run_styles import _source_latin_tracking
 from app.pdf_source_choice_spaces import source_choice_space_styles
 from app.pdf_layout_writer import _iter_text_lines,_pdf_output_text,_line_text
 from app.pdf_source_question_body import _line_proof
 from app.pdf_source_line_cache import apply_source_line_cache
 from app.pdf_question_markers import question_number,shared_question_range
 from hwpx.tools.paragraph_spacing import paragraph_indentation
 from hwpx.tools.question_reflow import update_positions
 try:
  width=_integer(native_page_width);ps=list(draw.iter(HP+'p'));styles=_stylemap(header);fonts=_fontmap(header);paras=_unique(header.iter(HH+'paraPr'),_native_id,'native paraPr IDs')
  if set(c.tag for c in draw)!={HP+'textMargin',HP+'subList'} or len(draw)!=2 or len(draw.findall(HP+'subList'))!=1 or any(c.tag!=HP+'p' for c in draw.find(HP+'subList')):_fail('native question structure')
  if not items or len(ps)!=len(items) or any(p.getparent() is not ps[0].getparent() for p in ps):_fail('native question ownership')
  text=lambda i:str(i.get('text',i.get('stem','')))
  labels=[text(i)[0] for i in items if text(i).startswith(tuple('①②③④⑤'))]
  if labels!=list('①②③④⑤'):_fail('not five single ordinary choices')
  first=items[0]['layout'];number=_integer(first['question_number'])
  if draw.get('name')!=f"question:{first['question_group']}" or question_number(text(items[0]))!=number:_fail('numbered instruction ownership')
  section=draw.getroottree().getroot();pagepr=section.find('.//'+HP+'pagePr');col=section.find('.//'+HP+'colPr');margin=pagepr.find(HP+'margin')
  if _native_integer(pagepr.get('width'))!=width or _native_integer(col.get('colCount'))!=_integer(first['column_count']) or col.get('sameSz') not in ('true','1'):_fail('native source column geometry')
  count=_native_integer(col.get('colCount'));column_width=(width-_native_integer(margin.get('left'))-_native_integer(margin.get('right'))-(count-1)*_native_integer(col.get('sameGap')))/count
  wrapper=draw.getparent();actual_width=_native_integer(wrapper.find(HP+'sz').get('width'))
  if actual_width!=column_width or _native_integer(draw.get('lastWidth'))!=actual_width or _native_integer(ps[0].getparent().get('textWidth'))!=actual_width:_fail('native wrapper width')
  _source_native_column_proof(first,section,wrapper,width)
  plans=[];allrows=[];leading=True;canonical_draw=deepcopy(draw);canonical_ps=list(canonical_draw.iter(HP+'p'))
  with fitz.open(first['source_pdf_path']) as doc:
   for p,clone,item in zip(ps,canonical_ps,items):
    layout=item['layout']
    if (item.get('image_paths') or item.get('tables') or any(layout.get(k)!=first.get(k) for k in ('source_pdf_path','source_page_index','source_page_width_pt','source_page_height_pt','source_column','column_left_pt','column_right_pt','question_group','question_number','question_variant','question_group_kind'))):_fail('source owner/image/control mismatch')
    page,rows=actual_source_records(layout,doc);allrows.extend(rows)
    if (any(c.tag not in {HP+'run',HP+'linesegarray'} for c in p) or len(rows)>3 or _text(p)!=text(item) or len(p.findall(HP+'linesegarray'))!=1 or any(len(r)!=1 or r[0].tag!=HP+'t' or len(r[0]) for r in p.findall(HP+'run'))):_fail('native control/text/cache mismatch')
    meta=layout['source_typography'];_paragraph_plain(p,paras[p.get('paraPrIDRef')],meta,header);scale=width/page.rect.width;starts=[(r['bbox_pt'][0]-layout['column_left_pt'])*scale for r in meta['lines']];left=max(0,round(min(starts)));indent=round(starts[0]-starts[1]) if len(starts)>1 else 0
    if abs(indent)>meta['font_size_pt']*scale*3:indent=0
    if paragraph_indentation(p,paras)!=(left,0,indent):_fail('native source indentation')
    if not apply_source_line_cache(clone,{**layout,'native_page_width':width,'native_indentation':(left,0,indent)},actual_width):_fail('source canonical cache')
    choice=text(item).startswith(tuple('①②③④⑤'));rowplan=source_choice_row_plan(layout,native_page_width=width) if choice else None
    if choice and rowplan is None:_fail('source choice row permission')
    sourcechars=[(s,c) for row in rows for s in row['spans'] for c in s['chars'] if not c['c'].isspace()];nativechars=[(c,styles[r.get('charPrIDRef')]) for r in p.findall(HP+'run') for c in r[0].text or ''];cursor=0;actual_spaces={}
    for row in rows:
     for s in row['spans']:
      for c in s['chars']:
       if c['c']==' ':actual_spaces.setdefault(cursor,[]).append((s,c))
       elif c['c'].isspace():_fail('foreign actual source whitespace')
       else:cursor+=1
    if choice and len(nativechars)!=sum(len(s['chars']) for row in rows for s in row['spans']):_fail('native source wordspace count')
    oldspace=source_choice_space_styles(layout) if choice else {};ratio=max(80,min(110,round(meta.get('font_width_percent') or 100)));tracking=max(-15,min(15,round(meta.get('letter_spacing_percent') or 0)));families={(_font_name(s['font']),bool(s['flags']&16 or 'bold' in s['font'].lower()),bool(s['flags']&2 or 'italic' in s['font'].lower())) for row in rows for s in row['spans']};uniform=(len(families)==1 and not oldspace and all(_source_latin_tracking(s,_font_name(s['font']),tracking)==tracking for row in rows for s in row['spans']))
    cursor=0;space_seen={}
    for ch,style in nativechars:
     _plain(style,header);span,raw=sourcechars[min(cursor,len(sourcechars)-1)];native_height=_native_integer(style.get('height'));actual_height=round(span['size']*scale);font=_font_name(span['font']);ref=style.find(HH+'fontRef')
     if ref is None or set(ref.attrib)!=set(LANGS) or any(fonts[l].get(ref.get(l))!=font for l in LANGS):_fail('native source language font')
     if (style.find(HH+'bold') is not None)!=bool(span['flags']&16 or 'bold' in span['font'].lower()) or (style.find(HH+'italic') is not None)!=bool(span['flags']&2 or 'italic' in span['font'].lower()):_fail('native source flags')
     allowed_height=round(meta['font_size_pt']*scale) if uniform and not choice else actual_height
     if native_height!=allowed_height:_fail('native producer/source height mismatch')
     leading &= native_height==actual_height
     expected_ratio,expected_tracking=oldspace.get(cursor,(ratio,_source_latin_tracking(span,font,tracking))) if ch==' ' else (ratio,_source_latin_tracking(span,font,tracking))
     if any(_native_integer(style.find(HH+'ratio').get(l))!=expected_ratio or _native_integer(style.find(HH+'spacing').get(l))!=expected_tracking for l in LANGS):_fail('native producer/source tracking or ratio')
     if ch.isspace():
      if ch!=' ':_fail('foreign native whitespace')
      space_seen[cursor]=space_seen.get(cursor,0)+1
     else:
      if ch!=_pdf_output_text(raw['c']):_fail('native/source character')
      cursor+=1
    if cursor!=len(sourcechars):_fail('native/source character coverage')
    if choice and (set(space_seen)!=set(actual_spaces) or any(v!=1 for v in space_seen.values()) or any(len(v)!=1 for v in actual_spaces.values())):_fail('native actual wordspace bijection')
    plans.append({'paragraph_index':len(plans),'choice':choice,'source_row_plan':rowplan,'records':meta['lines'],'actual_heights':[[round(s['size']*scale) for s in row['spans'] for c in s['chars'] if not c['c'].isspace()] for row in rows]})
   actual=_iter_text_lines(page);left=min(r['bbox'][0] for r in allrows);right=max(r['bbox'][2] for r in allrows);order=lambda r:(r['bbox'][1],r['bbox'][0]);band=sorted((r for r in actual if left-.1<=r['bbox'][0]<=right and r['bbox'][1]>=allrows[0]['bbox'][1]-.1 and r['bbox'][3]<=allrows[-1]['bbox'][3]+.1),key=order)
   if [_line_proof(r)[0] for r in band]!=[_line_proof(r)[0] for r in allrows]:_fail('incomplete actual question source band')
   following=sorted((r for r in actual if left-.1<=r['bbox'][0]<=right and r['bbox'][1]>=allrows[-1]['bbox'][3]-.1),key=order)
   if not following:_fail('unproved choice terminal boundary')
   nexttext=_pdf_output_text(_line_text(following[0])).strip();nextnumber=question_number(nexttext);shared=shared_question_range(nexttext)
   if not ((nextnumber is not None and nextnumber>number) or (shared is not None and shared[0]>number)):_fail('actual choice terminal continuation')
   object_band=fitz.Rect(_finite(first['column_left_pt']),allrows[0]['bbox'][1],_finite(first['column_right_pt']),following[0]['bbox'][1])
   if any(fitz.Rect(image['bbox']).intersects(object_band) for image in page.get_image_info()):_fail('actual source question image')
   prefix_rows=[r for part in plans if not part['choice'] for r in part['records']];answer_lines=[]
   for path in page.get_drawings():
    stroke=_finite(path.get('width') or 0);expanded=fitz.Rect(path['rect'])+(-max(stroke/2,.0001),-max(stroke/2,.0001),max(stroke/2,.0001),max(stroke/2,.0001))
    if not expanded.intersects(object_band):continue
    # Existing source speaker answer-lines are explicitly classified. They
    # are outside the choice rows; this helper does not claim their native
    # paint fidelity or add/remove them. Other vectors/frames abstain.
    if (path.get('type')!='s' or path.get('fill') is not None or path.get('color')!=(0.,0.,0.) or path.get('stroke_opacity')!=1 or path.get('dashes')!='[] 0' or path.get('closePath') or len(path.get('items',[]))!=1 or path['items'][0][0]!='l'):_fail('actual source question vector/frame')
    _,a,b=path['items'][0];x0,x1=sorted((_finite(a.x),_finite(b.x)));y=_finite(a.y)
    if abs(y-_finite(b.y))>.0001:_fail('nonhorizontal source question vector')
    matches=[]
    for record in prefix_rows:
     size=max(_finite(s['size']) for s in record['spans']);baseline=_finite(record['baseline_pt']);box=record['bbox_pt']
     if (re.fullmatch(r'[A-Za-z]+:',record['text'].strip()) and .2*size<=x0-box[2]<=size and .05*size<=y-baseline<=.3*size and 0<stroke<=.1*size and x1-x0>=4*size and x1<=_finite(first['column_right_pt']) and x0>=_finite(first['column_left_pt'])):matches.append(record)
    if len(matches)!=1 or any(r['prefix_row']==matches[0]['text'] for r in answer_lines):_fail('unproved source prefix answer-line')
    answer_lines.append({'prefix_row':matches[0]['text'],'bbox_pt':list(path['rect']),'width_pt':stroke,'native_paint_fidelity':'unchanged; not claimed'})
  # Reproduce source paragraph gaps from zero ordinary before/after margins.
  from app.pdf_native_typography import _flow_height
  from hwpx.tools.paragraph_spacing import paragraph_spacing
  origin=None;cursor=0;expected_afters=[0]*len(items)
  for ix,(clone,item) in enumerate(zip(canonical_ps,items)):
   top=_finite(item['layout']['source_typography']['lines'][0]['baseline_pt'])*width/_finite(item['layout']['source_page_width_pt'])-_finite(clone.find(HP+'linesegarray')[0].get('baseline'))
   if origin is None:origin=top
   extra=max(0,top-origin-cursor)
   if ix and extra>=1:expected_afters[ix-1]=round(extra);cursor+=extra
   cursor+=_flow_height(clone)
  if any(paragraph_spacing(p,paras)!=(0,after) for p,after in zip(ps,expected_afters)):_fail('noncanonical source paragraph gaps')
  update_positions(canonical_ps[0].getparent(),paras)
  if any([dict(c.attrib) for c in p.find(HP+'linesegarray')]!=[dict(c.attrib) for c in clone.find(HP+'linesegarray')] for p,clone in zip(ps,canonical_ps)):_fail('noncanonical current native cache')
  return {'question_group':first['question_group'],'native_width':width,'native_wrapper_width':actual_width,'gap_wordspaces_permitted':True,'leading_permitted':bool(leading),'paragraphs':plans,'actual_full_band':True,'actual_nontext_objects_classified':True,'source_prefix_answer_lines':answer_lines,'canonical_current_caches':True,'complete_native_paragraph_ownership':True}
 except (ValueError,TypeError,KeyError,IndexError,AttributeError,OverflowError,RuntimeError,OSError,UnicodeError):return None


def _new_char_style(header,base,ratio,tracking):
 props=next(header.iter(HH+'charProperties'));node=deepcopy(base);identifier=str(max(_integer(n.get('id')) for n in props)+1);node.set('id',identifier)
 for tag,value in (('ratio',ratio),('spacing',tracking)):
  for lang in LANGS:node.find(HH+tag).set(lang,str(value))
 props.append(node);props.set('itemCnt',str(len(props)));return identifier


def _native_gap_styles(header,sections,eligible,payloads):
 """Fit editable U+0020 with an isolated real-native-font/style SVG probe.

 The target is an actual raw source marker-to-first-letter advance. No
 full-page PDF output participates in selecting a native ratio/tracking.
 """
 import io,zipfile
 import rhwp
 from app.pdf_question_rendering import _transform,_multiply,IDENTITY
 probe_header=deepcopy(header);props=next(probe_header.iter(HH+'charProperties'));styles=_stylemap(header);candidates=[]
 for item in eligible:
  p=item['paragraph'];native=[(ch,styles[r.get('charPrIDRef')],r) for r in p.findall(HP+'run') for ch in r[0].text or '' if not ch.isspace()]
  if len(native)<2 or native[0][0]!=item['plan']['marker']:_fail('native gap boundary')
  marker,body=native[:2];target=item['plan']['target_marker_advance_px'];item['probe_indices']=[]
  for tracking in range(-15,16):
   clone=deepcopy(p)
   for run in list(clone.findall(HP+'run')):clone.remove(run)
   gap_style=_new_char_style(probe_header,body[1],80,tracking)
   for index,(text,sid) in enumerate(((marker[0],marker[1].get('id')),(' ',gap_style),(body[0],body[1].get('id')))):
    run=etree.Element(HP+'run',charPrIDRef=sid);etree.SubElement(run,HP+'t').text=text;clone.insert(index,run)
   item['probe_indices'].append(len(candidates));candidates.append({'paragraph':clone,'tracking':tracking,'marker':marker[0],'letter':body[0],'target':target})
 if not candidates:return []
 first=sections[0];probe=etree.Element(first.tag,nsmap=first.nsmap);secpr=deepcopy(first.find('.//'+HP+'secPr'))
 for child in list(secpr):
  if etree.QName(child).localname in {'header','footer','headerApply','footerApply','masterPage'}:secpr.remove(child)
 margin=secpr.find(HP+'pagePr/'+HP+'margin')
 for key in ('top','bottom','left','right'):margin.set(key,'1000')
 for key in ('header','footer','gutter'):margin.set(key,'0')
 for index,candidate in enumerate(candidates):
  p=candidate['paragraph'];p.set('pageBreak','1' if index else '0');p.set('columnBreak','0');cache=p.find(HP+'linesegarray')
  if len(cache)!=1:_fail('native probe row count')
  cache[0].set('vertpos','0');cache[0].set('textpos','0')
  if not index:
   run=p.find(HP+'run');run.insert(0,secpr);ctrl=etree.Element(HP+'ctrl');etree.SubElement(ctrl,HP+'colPr',id='0',type='NEWSPAPER',layout='LEFT',colCount='1',sameSz='1',sameGap='0');run.insert(1,ctrl)
  probe.append(p)
 probe_header.set('secCnt','1');probe_payloads=dict(payloads);probe_payloads['Contents/header.xml']=etree.tostring(probe_header);probe_payloads['Contents/section0.xml']=etree.tostring(probe)
 manifest=etree.fromstring(payloads['Contents/content.hpf']);opf='{'+etree.QName(manifest).namespace+'}';removed=set()
 for node in list(manifest.find(opf+'manifest')):
  if re.fullmatch(r'(?:Contents/)?section[1-9]\d*\.xml',node.get('href','')):removed.add(node.get('id'));node.getparent().remove(node)
 for node in list(manifest.find(opf+'spine')):
  if node.get('idref') in removed:node.getparent().remove(node)
 probe_payloads['Contents/content.hpf']=etree.tostring(manifest);buffer=io.BytesIO()
 with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
  for name,data in probe_payloads.items():
   if re.fullmatch(r'Contents/section[1-9]\d*\.xml',name):continue
   z.writestr(name,data)
 doc=rhwp.Document.from_bytes(buffer.getvalue())
 if doc.page_count!=len(candidates):_fail('native font probe pagination')
 SVG='{http://www.w3.org/2000/svg}'
 for index,candidate in enumerate(candidates):
  root=etree.fromstring(doc.render_svg(index).encode());glyphs=[]
  for node in root.iter(SVG+'text'):
   value=''.join(node.itertext())
   if not value.strip():continue
   matrix=IDENTITY
   for parent in [*reversed(list(node.iterancestors())),node]:matrix=_multiply(matrix,_transform(parent.get('transform','')))
   x,y=_finite(node.get('x',0)),_finite(node.get('y',0));glyphs.append((value,matrix[0]*x+matrix[2]*y+matrix[4],matrix[1]*x+matrix[3]*y+matrix[5]))
  if len(glyphs)!=2 or glyphs[0][0]!=candidate['marker'] or glyphs[1][0]!=candidate['letter'] or abs(glyphs[0][2]-glyphs[1][2])>.1:_fail('native font probe ownership')
  candidate['measured']=glyphs[1][1]-glyphs[0][1];candidate['error']=candidate['measured']-candidate['target']
 results=[]
 for item in eligible:
  selected=min((candidates[ix] for ix in item['probe_indices']),key=lambda c:(abs(c['error']),abs(c['tracking'])))
  if abs(selected['error'])>.8:_fail('unrepresentable actual source marker advance')
  results.append({'ratio':80,'tracking':selected['tracking'],'target_px':selected['target'],'measured_native_px':selected['measured'],'error_px':selected['error']})
 return results


def source_choice_geometry_bytes(data,source_groups):
 """Return an atomic clone and report; leave original bytes on any failure.

 source_groups contains complete source items for each semantic question.
 Unsupported groups abstain individually before any XML changes. Once
 selected, every source/native plan and all metric probes must succeed
 before the cloned header/sections are serialized.
 """
 import io,zipfile
 from hwpx.tools.paragraph_spacing import paragraph_spacing
 try:
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   infos=z.infolist();_unique(infos,_zip_name,'ZIP entries');payloads={i.filename:z.read(i.filename) for i in infos}
  header=etree.fromstring(payloads['Contents/header.xml']);names=sorted((n for n in payloads if re.fullmatch(r'Contents/section\d+\.xml',n)),key=lambda n:int(re.search(r'\d+',n).group()));sections=[etree.fromstring(payloads[n]) for n in names]
  draws=_unique((d for section in sections for d in section.iter(HP+'drawText') if d.get('name','').startswith('question:')),lambda d:d.get('name'),'native question draw names');selected=[];eligible=[]
  _unique(source_groups,lambda items:items[0].get('layout',{}).get('question_group') if items else None,'source group IDs')
  for items in source_groups:
   if not items:continue
   group=items[0].get('layout',{}).get('question_group');draw=draws.get('question:'+str(group))
   if draw is None:continue
   plan=source_choice_group_plan(header,draw,items)
   if plan is None:continue
   ps=list(draw.iter(HP+'p'));selected.append((draw,items,plan))
   for part in plan['paragraphs']:
    if part['choice']:eligible.append({'paragraph':ps[part['paragraph_index']],'plan':part['source_row_plan']})
  if not selected:return data,{'changed_groups':0,'abstained':True}
  gap_styles=_native_gap_styles(header,sections,eligible,payloads)
  if len(gap_styles)!=len(eligible):_fail('native font probe coverage')
  styles=_stylemap(header);para_styles={p.get('id'):p for p in header.iter(HH+'paraPr')};events=[];gap_cursor=0
  for draw,items,plan in selected:
   ps=list(draw.iter(HP+'p'));event={'question_group':plan['question_group'],'leading_permitted':plan['leading_permitted'],'choices':[]}
   if plan['leading_permitted']:
    sequence=[]
    for p,item,part in zip(ps,items,plan['paragraphs']):
     for cache,record,heights in zip(p.find(HP+'linesegarray'),part['records'],part['actual_heights']):
      height=max(heights);baseline=round(max(_finite(cache.get('baseline')),height*.8));sequence.append({'p':p,'cache':cache,'record':record,'height':height,'baseline':baseline})
    scale=plan['native_width']/_finite(items[0]['layout']['source_page_width_pt']);origin=sequence[0]['record']['baseline_pt'];firstbaseline=sequence[0]['baseline']
    for row in sequence:row['global_top']=round((row['record']['baseline_pt']-origin)*scale+firstbaseline-row['baseline'])
    para_tops={id(row['p']):row['global_top'] for row in reversed(sequence)}
    for index,row in enumerate(sequence):
     cache=row['cache'];before,after=paragraph_spacing(row['p'],para_styles)
     if index+1<len(sequence):
      nxt=sequence[index+1];step=nxt['global_top']-row['global_top']
      if nxt['p'] is not row['p']:step-=after+paragraph_spacing(nxt['p'],para_styles)[0]
      spacing=round(step-row['height'])
      if spacing<0:_fail('source leading requires negative cache gap')
     else:spacing=_integer(cache.get('spacing'))
     for key,value in (('vertpos',row['global_top']-para_tops[id(row['p'])]),('vertsize',row['height']),('textheight',row['height']),('baseline',row['baseline']),('spacing',spacing)):cache.set(key,str(value))
   for p,part in zip(ps,plan['paragraphs']):
    if not part['choice']:continue
    rowplan=part['source_row_plan'];cursor=0;changed=0
    for run in list(p.findall(HP+'run')):
     base=styles[run.get('charPrIDRef')];groups=[]
     for ch in run[0].text or '':
      sid=run.get('charPrIDRef')
      if ch==' ':
       value=rowplan['spaces'].get(cursor)
       if value is None:_fail('unplanned native space')
       sid=_new_char_style(header,base,value['ratio'],value['tracking']);changed+=1
      if groups and groups[-1][0]==sid:groups[-1][1]+=ch
      else:groups.append([sid,ch])
      if not ch.isspace():cursor+=1
     index=p.index(run)
     for offset,(sid,value) in enumerate(groups):
      replacement=deepcopy(run);replacement.set('charPrIDRef',sid);replacement[0].text=value;p.insert(index+offset,replacement)
     p.remove(run)
    if changed!=len(rowplan['spaces']):_fail('native wordspace commit coverage')
    runs=p.findall(HP+'run');native=[(ch,styles.get(r.get('charPrIDRef')),r) for r in runs for ch in r[0].text or '' if not ch.isspace()]
    if runs[0].findtext(HP+'t')!=rowplan['marker'] or native[1][1] is None:_fail('native marker insertion boundary')
    gap=gap_styles[gap_cursor];gap_cursor+=1;sid=_new_char_style(header,native[1][1],gap['ratio'],gap['tracking']);run=etree.Element(HP+'run',charPrIDRef=sid);etree.SubElement(run,HP+'t').text=' ';p.insert(p.index(runs[0])+1,run)
    event['choices'].append({'marker':rowplan['marker'],'actual_wordspaces':changed,'gap':gap})
   events.append(event)
  if gap_cursor!=len(gap_styles):_fail('native gap commit coverage')
  payloads['Contents/header.xml']=etree.tostring(header,encoding='UTF-8',xml_declaration=True,standalone=True)
  for name,section in zip(names,sections):payloads[name]=etree.tostring(section,encoding='UTF-8',xml_declaration=True,standalone=True)
  buffer=io.BytesIO()
  with zipfile.ZipFile(buffer,'w') as z:
   for info in infos:z.writestr(info,payloads[info.filename])
  return buffer.getvalue(),{'changed_groups':len(selected),'events':events,'isolated_real_native_font_probe':True,'source_full_group_proof':True,'staged_atomic_clone':True}
 except (ValueError,TypeError,KeyError,IndexError,AttributeError,OverflowError,RuntimeError,OSError,UnicodeError):return data,{'changed_groups':0,'abstained':True,'atomic_rejection':True}


def apply_source_choice_geometry(path, items):
 """Apply only complete, source-proved question groups after native writing.

 Stage the entire package, retain editor-open validation, and replace the
 original only after every selected plan and isolated font probe succeeds.
 This producer pass runs before heading and multi-column TAB refresh.
 """
 from itertools import groupby
 import os,tempfile
 from hwpx.tools.package_validator import validate_editor_open_safety
 groups=[]
 for key,group in groupby(items,key=lambda item:(item.get('layout') or {}).get('question_group')
                          if (item.get('layout') or {}).get('question_group_kind')=='question' else None):
  if key is not None:groups.append(list(group))
 target=Path(path);original=target.read_bytes()
 updated,report=source_choice_geometry_bytes(original,groups)
 if updated==original:return report
 descriptor,name=tempfile.mkstemp(dir=str(target.parent),suffix='.hwpx.tmp')
 os.close(descriptor);staged=Path(name)
 try:
  staged.write_bytes(updated)
  if not validate_editor_open_safety(staged).ok:
   return {'changed_groups':0,'abstained':True,'atomic_rejection':True}
  os.replace(staged,target)
  return report
 finally:
  staged.unlink(missing_ok=True)
