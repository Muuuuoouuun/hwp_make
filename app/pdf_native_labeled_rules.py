"""Source-proved labeled answer rules in editable native text.

Discovery uses producer items. The frozen source planner proves the complete
numbered PDF band, embedded label program and visible rule/frame paint. Current
native geometry/cache permission is independently replayed from actual PDF
rows; old owner files and saved TAB widths never supply new coordinates.

The bytes API stages a clone with exact input fallback. The file wrapper
validates and atomically replaces the package. Source Y and native underline
thickness remain separate.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import io
from pathlib import Path
import re
import struct
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile

import fitz
from lxml import etree

from app import pdf_source_choice_headers as headers
from app import pdf_source_choice_geometry as guards
from app.pdf_native_text import body_text
from .pdf_source_labeled_rules import source_labeled_rule_plan

HP, HH, HC = headers.HP, headers.HH, headers.HC
LANGS = headers.LANGS
require = headers._require
compact = headers.compact


def _unique_child(parent, tag):
    values = parent.findall(tag)
    require(len(values) == 1, 'missing/duplicate native '+etree.QName(tag).localname)
    return values[0]


def _plain_paragraph(p, style, meta, header):
    require(len({c.tag for c in style}) == len(style), 'duplicate native paragraph style child')
    require(all(c.tag in {HH+'align', HH+'heading', HH+'breakSetting', HH+'autoSpacing', HP+'switch', HH+'border'} for c in style),
            'foreign/unsupported native paragraph style child')
    guards._paragraph_plain(p, style, meta, header)


def _native_paint(data, native):
    from app.pdf_question_rendering import (_visible_svg_text, _transform, _multiply,
        IDENTITY, _expose_painted_dot_leaders, SVG)
    document = native.Document.from_bytes(data)
    result = []
    for pi in range(document.page_count):
        svg = document.render_svg(pi)
        root = etree.fromstring(svg.encode('utf-8'))
        _expose_painted_dot_leaders(root)
        page = []
        for node in root.iter(SVG+'text'):
            if any(etree.QName(a).localname in {'defs','pattern','clipPath','mask','symbol'} for a in node.iterancestors()):
                continue
            value = compact(''.join(node.itertext()))
            if not value:
                continue
            require(len(value) == 1, 'unsupported native glyph paint')
            matrix = IDENTITY
            for a in [*reversed(list(node.iterancestors())), node]:
                matrix = _multiply(matrix, _transform(a.get('transform', '')))
            x, y = float(node.get('x', 0)), float(node.get('y', 0))
            page.append((pi, value, (matrix[0]*x+matrix[2]*y+matrix[4], matrix[1]*x+matrix[3]*y+matrix[5])))
        visible, _, _ = _visible_svg_text(svg)
        require(''.join(c[1] for c in page) == compact(visible), 'incomplete native visible paint')
        result.extend(page)
    return document, result


def _column_plan(section, draw, question, page, source, path, digest):
    width = guards._native_integer(_unique_child(section.find('.//'+HP+'secPr'), HP+'pagePr').get('width'))
    actual = [r for r in guards._actual_column_rails(str(path), digest)
              if r[:2] == (question.page-1, source['source_column'])]
    require(len(actual) == 1, 'actual source column ownership')
    _, _, left, right, pw, ph = actual[0]
    layout = {'source_pdf_path': str(path), 'source_page_index': question.page-1,
              'source_column': source['source_column'], 'column_left_pt': left,
              'column_right_pt': right, 'source_page_width_pt': pw, 'source_page_height_pt': ph}
    wrapper = draw.getparent()
    guards._source_native_column_proof(layout, section, wrapper, width)
    pagepr = section.find('.//'+HP+'pagePr')
    margin = _unique_child(pagepr, HP+'margin')
    columns = list(section.iter(HP+'colPr'))
    column_width = (width-guards._native_integer(margin.get('left'))-guards._native_integer(margin.get('right'))
                    -guards._native_integer(columns[0].get('sameGap')))/2
    actual_width = guards._native_integer(_unique_child(wrapper, HP+'sz').get('width'))
    require(actual_width == column_width and guards._native_integer(draw.get('lastWidth')) == actual_width
            and guards._native_integer(_unique_child(draw, HP+'subList').get('textWidth')) == actual_width,
            'native canonical wrapper width disagreement')
    origin = guards._native_integer(margin.get('left'))+(source['source_column']-1)*(column_width+guards._native_integer(columns[0].get('sameGap')))
    return {**layout, 'page_width': width, 'width': actual_width, 'column_origin_hwp': origin,
            'scale': width/page.rect.width}


def _canonical_source_frame(document, page, question, source, items, columns):
    from app.pdf_layout_writer import _iter_text_lines, _merge_same_row_flow_lines, _line_text
    from app.pdf_native_content import _source_typography, _source_prose_frame
    frame = _source_prose_frame(fitz.Rect(source['summary_frame_bbox_pt']), page.get_drawings())
    require(frame is not None, 'actual source frame bounds unavailable')
    # The producer discards standalone whitespace-only PDF rows. Require all
    # actual ink rows; retained spaces inside those rows remain fully proved.
    actual_rows = [dict(row, type='line') for row in _iter_text_lines(page)
                   if frame.contains(fitz.Rect(row['bbox'])) and compact(_line_text(row))]
    actual_rows = _merge_same_row_flow_lines(page, actual_rows)
    actual_rows.sort(key=lambda row: (row['bbox'][1], row['bbox'][0]))
    require(compact(''.join(_line_text(row) for row in actual_rows)) == source['summary_complete_cell_text'],
            'actual source frame has missing/foreign row')
    meta = _source_typography(actual_rows, {**columns, 'rect': frame})
    geometry = {'index': 0, 'source_prose_frame': True,
                'source_frame_text': ''.join(_line_text(row) for row in actual_rows),
                'bbox_pt': list(frame), 'cell_bounds': [[list(frame)]], 'images': []}
    matches = []
    for item in items:
        layout = item.get('layout') or {}
        if layout.get('question_number') != question.number:
            continue
        if compact(''.join(r.get('text', '') for r in layout.get('source_typography', {}).get('lines', []))) == source['summary_complete_cell_text']:
            matches.append(item)
    require(len(matches) == 1, 'ambiguous producer summary frame owner')
    item = matches[0]; layout = item['layout']
    require(not item.get('image_paths') and layout.get('source_literal_text') is True,
            'unsupported source frame objects/literal text')
    require(guards._json(layout.get('native_tables')) == guards._json([geometry]), 'noncanonical actual source frame geometry')
    require(guards._json(layout.get('source_typography')) == guards._json(meta), 'noncanonical actual source frame typography')
    for name in ('source_page_index', 'source_column', 'source_page_width_pt', 'source_page_height_pt', 'column_left_pt', 'column_right_pt'):
        require(layout.get(name) == columns[name], 'source frame column/page disagreement')
    require(Path(layout['source_pdf_path']).resolve() == Path(columns['source_pdf_path']), 'source frame PDF disagreement')
    # Rebind the complete actual frame program, including ordinary prose.
    traces = {}
    for trace in page.get_texttrace():
        for glyph in trace['chars']:
            traces.setdefault((glyph[0], tuple(glyph[2])), []).append((trace, glyph))
    glyphs = []; spans = []
    for row in actual_rows:
        for span in row['spans']:
            require(span['font'] == 'TimesNewRoman' and span['flags'] == 4 and span.get('color') == 0
                    and span.get('alpha') == 255 and abs(span['size']-source['source_rule_style_size_pt']) < .02,
                    'actual source frame font/style disagreement')
            spans.append(span)
            for char in span['chars']:
                require(char.get('synthetic') is False, 'synthetic source frame character')
                found = traces.get((ord(char['c']), tuple(char['origin'])), [])
                require(len(found) == 1, 'ambiguous actual source frame trace')
                trace, glyph = found[0]
                require(trace['font'] == span['font'] and trace['flags'] == 4 and trace['type'] == 0
                        and trace['opacity'] == 1 and trace['wmode'] == 0 and tuple(trace['dir']) == (1.,0.)
                        and abs(trace['size']-span['size']) < .02, 'actual source frame trace style/axis')
                glyphs.append((char, glyph[1]))
    program = headers.font_program_proof(document, page, {'spans': spans, 'glyphs': glyphs})
    return deepcopy(layout), actual_rows, program


def _geometry(table, cell):
    def attrs(parent, tags):
        return {tag: dict(_unique_child(parent, HP+tag).attrib) for tag in tags}
    return {'table': attrs(table, ('sz','pos','inMargin','outMargin')),
            'cell': attrs(cell, ('cellSz','cellMargin','subList'))}


def _frame_border(header, table):
    """The current editable frame must retain the producer's plain black ink."""
    matches=[b for b in header.iter(HH+'borderFill') if b.get('id')==table.get('borderFillIDRef')]
    require(len(matches)==1,'ambiguous current native frame border')
    border=matches[0]
    require({k:v for k,v in border.attrib.items() if k!='id'} ==
            {'threeD':'0','shadow':'0','centerLine':'NONE','breakCellSeparateLine':'0'}, 'native frame border effect')
    expected={'slash':{'type':'NONE','Crooked':'0','isCounter':'0'},
              'backSlash':{'type':'NONE','Crooked':'0','isCounter':'0'},
              **{name:{'type':'SOLID','width':'0.12 mm','color':'#000000'}
                 for name in ('leftBorder','rightBorder','topBorder','bottomBorder')},
              'diagonal':{'type':'SOLID','width':'0.1 mm','color':'#000000'}}
    require(len(border)==len(expected) and {c.tag for c in border}=={HH+name for name in expected},
            'native frame border structure')
    require(all(dict(_unique_child(border,HH+name).attrib)==attrs and not len(border.find(HH+name))
                for name,attrs in expected.items()), 'native frame border paint disagreement')


def _canonical_native_cell(header, section, draw, question, source, layout, columns):
    from app.pdf_table_paragraphs import restore_background_frame
    from hwpx.tools.question_reflow import update_positions
    styles = guards._stylemap(header); fonts = guards._fontmap(header)
    paras = guards._unique(header.iter(HH+'paraPr'), guards._native_id, 'native paraPr IDs')
    guards._unique(header.iter(HH+'tabPr'), guards._native_id, 'native tabPr IDs')
    cells = [c for c in draw.iter(HP+'tc') if compact(body_text(c)) == source['summary_complete_cell_text']]
    require(len(cells) == 1, 'ambiguous current complete summary cell')
    cell = cells[0]; row = cell.getparent(); table = row.getparent(); run = table.getparent(); root = run.getparent()
    require(root.getparent() is draw.find(HP+'subList') and run.tag == HP+'run' and len(run) == 1
            and table.tag == HP+'tbl' and table.findall(HP+'tr') == [row] and row.findall(HP+'tc') == [cell],
            'nested/ambiguous native summary table ownership')
    expected_table = {'zOrder':'0','numberingType':'TABLE','textWrap':'TOP_AND_BOTTOM','textFlow':'BOTH_SIDES',
                      'lock':'0','dropcapstyle':'None','pageBreak':'CELL','repeatHeader':'0','rowCnt':'1',
                      'colCnt':'1','cellSpacing':'0','noAdjust':'0'}
    require(all(table.get(k) == v for k,v in expected_table.items()) and set(table.attrib) == set(expected_table)|{'id','borderFillIDRef'},
            'unsupported native table attributes')
    require(set(c.tag for c in table) == {HP+t for t in ('sz','pos','inMargin','outMargin','tr')} and len(table) == 5,
            'duplicate/unsupported native table geometry')
    require(set(c.tag for c in cell) == {HP+t for t in ('subList','cellAddr','cellSpan','cellSz','cellMargin')} and len(cell) == 5,
            'duplicate/unsupported native cell geometry')
    require(cell.get('hasMargin') == '1' and cell.get('protect') == '0' and cell.get('borderFillIDRef') == table.get('borderFillIDRef'),
            'unsupported native cell flags/border')
    require({k:v for k,v in cell.attrib.items() if k!='borderFillIDRef'} ==
            {'name':'','header':'0','hasMargin':'1','protect':'0','editable':'0','dirty':'1'}, 'native cell flags')
    _frame_border(header,table)
    require(dict(_unique_child(cell,HP+'cellAddr').attrib) == {'colAddr':'0','rowAddr':'0'}
            and dict(_unique_child(cell,HP+'cellSpan').attrib) == {'colSpan':'1','rowSpan':'1'}, 'native cell address/span')
    sub = _unique_child(cell, HP+'subList'); ps = sub.findall(HP+'p')
    require(ps and len(ps) == len(sub) and all(c.tag == HP+'p' for c in sub), 'unsupported summary cell flow')
    height = round(source['source_rule_style_size_pt']*columns['scale'])
    for p in ps:
        require(len(p.findall(HP+'linesegarray')) == 1 and all(c.tag in {HP+'run',HP+'linesegarray'} for c in p),
                'native summary controls/cache')
        runs = p.findall(HP+'run')
        require(runs and all(len(r) == 1 and r[0].tag == HP+'t' and not len(r[0]) for r in runs), 'native summary text controls')
        for r in runs:
            style = styles[r.get('charPrIDRef')]; guards._plain(style, header)
            require(guards._native_integer(style.get('height')) == height and style.find(HH+'bold') is None
                    and style.find(HH+'italic') is None, 'native summary source height/flags')
            require(all(guards._native_integer(style.find(HH+tag).get(lang)) == value
                        for tag,value in (('ratio',100),('spacing',0)) for lang in LANGS), 'native summary ratio/tracking')
            refs = style.find(HH+'fontRef')
            require(refs is not None and set(refs.attrib) == set(LANGS)
                    and all(fonts[lang].get(refs.get(lang)) == 'Times New Roman' for lang in LANGS),
                    'native summary seven-language source font')
    # Reconstruct every actual field and paragraph margin/spacing from raw rows.
    clone = deepcopy(root); cloned_header = deepcopy(header)
    properties = cloned_header.find('.//'+HH+'paraProperties')
    replay_styles = {s.get('id'):s for s in cloned_header.iter(HH+'paraPr')}
    def para_style(base, alignment, step, font_height, left=0, indent=0, right=0):
        style = deepcopy(replay_styles[base]); identifier = str(max(map(int,replay_styles))+1); style.set('id',identifier)
        style.find(HH+'align').set('horizontal',alignment)
        percent = max(100,min(250,round(step*100/font_height)))
        for n in style.iter(HH+'lineSpacing'): n.attrib.update({'type':'PERCENT','value':str(percent),'unit':'PERCENT'})
        for margin in style.iter(HH+'margin'):
            for name in ('left','right','prev','next','intent'):
                margin.find(HC+name).set('value',str(round({'left':left,'right':right,'intent':indent}.get(name,0))))
        properties.append(style); replay_styles[identifier] = style
        return identifier
    require(restore_background_frame(clone,layout,cloned_header,columns['page_width'],columns['width'],para_style) == len(ps),
            'canonical current summary frame reconstruction failed')
    cloned_cell = next(clone.iter(HP+'tc')); cloned_table = cloned_cell.getparent().getparent()
    update_positions(cloned_cell.find(HP+'subList'), replay_styles)
    require(_geometry(table,cell) == _geometry(cloned_table,cloned_cell), 'noncanonical native summary frame geometry')
    cloned_ps = cloned_cell.findall(HP+'subList/'+HP+'p')
    def style_value(style):
        value = deepcopy(style); value.attrib.pop('id',None)
        return etree.tostring(value,method='c14n')
    for p, expected in zip([root,*ps],[clone,*cloned_ps]):
        style = paras[p.get('paraPrIDRef')]; canonical = replay_styles[expected.get('paraPrIDRef')]
        percent = int(next(canonical.iter(HH+'lineSpacing')).get('value'))
        _plain_paragraph(p,style,{'alignment':'LEFT','font_size_pt':height,'line_spacing_pt':height*percent/100},header)
        require(style_value(style) == style_value(canonical), 'noncanonical native summary paragraph geometry')
        require([dict(c.attrib) for c in p.findall(HP+'linesegarray/'+HP+'lineseg')] ==
                [dict(c.attrib) for c in expected.findall(HP+'linesegarray/'+HP+'lineseg')],
                'noncanonical native summary cache fields')
    geometry = _geometry(table,cell)
    for tag in ('sz','pos','inMargin','outMargin'):
        for name,value in geometry['table'][tag].items():
            if name in {'width','height','horzOffset','vertOffset','left','right','top','bottom'}: guards._native_integer(value)
    for tag in ('cellSz','cellMargin'):
        for value in geometry['cell'][tag].values(): guards._native_integer(value)
    pos = table.find(HP+'pos'); margin = cell.find(HP+'cellMargin')
    origin = columns['column_origin_hwp']+int(pos.get('horzOffset'))+int(margin.get('left'))
    width = int(cell.find(HP+'cellSz').get('width'))-int(margin.get('left'))-int(margin.get('right'))
    target = [p for p in ps if compact(body_text(p)).startswith(source['rule_row_nonspace_text'])]
    require(len(target) == 1 and ps[-1] is target[0], 'ambiguous/followed native rule paragraph')
    p = target[0]; runs = p.findall(HP+'run')
    require(len(runs) == 1, 'mixed current summary rule style IDs')
    text = body_text(p); a,b = [i['label'] for i in source['labeled_intervals']]
    require(text.startswith(a) and text.count(a) == text.count(b) == 1, 'native summary label segmentation')
    middle = text[len(a):text.index(b)]; tail = text[text.index(b)+len(b):]
    require(compact(middle) == compact(source['rule_row_prose']) and tail.startswith(' ')
            and compact(tail), 'native summary prose/tail boundary')
    caches = [dict(c.attrib) for c in p.findall(HP+'linesegarray/'+HP+'lineseg')]
    require(len(caches) == 2 and int(caches[0]['textpos']) == 0
            and int(caches[1]['textpos']) == len(a+middle+b)+1, 'native/source complete two-row summary boundary')
    require(abs(origin-source['labeled_intervals'][0]['rule'][0]*columns['scale']) <= 1,
            'source opening rule not at proved current cell content origin')
    return {'paragraph':p,'cell':cell,'table':table,'style':paras[p.get('paraPrIDRef')],
            'char_style':styles[runs[0].get('charPrIDRef')], 'charid':runs[0].get('charPrIDRef'),
            'origin_hwp':origin,'width':width,'cache_fields':caches,'labels':[a,b],
            'middle':middle,'tail':tail,'height':height,'canonical_geometry':geometry,
            'canonical_rows':sum(len(p.findall(HP+'linesegarray/'+HP+'lineseg')) for p in ps)}


def _apply_native_rule(header, source, plan, columns, native):
    from hwpx.tools import native_line_metrics
    from hwpx.tools import native_line_cache
    p = plan['paragraph']; oldtext = body_text(p)
    chars = _unique_child(header.find('.//'+HH+'refList'),HH+'charProperties')
    paras = header.find('.//'+HH+'paraProperties'); tabs = header.find('.//'+HH+'tabProperties')
    require(paras is not None and tabs is not None, 'missing current native style stores')
    char = deepcopy(plan['char_style']); charid = str(max(int(c.get('id')) for c in chars)+1); char.set('id',charid)
    underline = _unique_child(char, HH+'underline'); underline.attrib.clear(); underline.attrib.update({'type':'BOTTOM','shape':'SOLID','color':'#000000'})
    chars.append(char); chars.set('itemCnt',str(len(chars)))
    style = deepcopy(plan['style']); style.set('id',str(max(int(c.get('id')) for c in paras)+1))
    tabid = str(max(int(c.get('id')) for c in tabs)+1); style.set('tabPrIDRef',tabid)
    for margin in style.iter(HH+'margin'): margin.find(HC+'intent').set('value','0')
    a,b = source['labeled_intervals']
    x = [a['label_bbox'][0],a['rule'][2],source['rule_row_prose_origin_pt'][0],b['rule'][0],b['label_bbox'][0],b['rule'][2]]
    stops = [round(value*columns['scale']-plan['origin_hwp']) for value in x]
    require(all(0<v<=plan['width'] for v in stops) and all(a<b for a,b in zip(stops,stops[1:])), 'source rule TAB destinations outside current native content')
    tab = etree.SubElement(tabs,HH+'tabPr',id=tabid,autoTabLeft='0',autoTabRight='0')
    switch = etree.SubElement(tab,HP+'switch'); case = etree.SubElement(switch,HP+'case',attrib={'required-namespace':'http://www.hancom.co.kr/hwpml/2016/HwpUnitChar'}); default = etree.SubElement(switch,HP+'default')
    for stop in stops:
        etree.SubElement(case,HH+'tabItem',pos=str(stop),type='LEFT',leader='NONE')
        etree.SubElement(default,HH+'tabItem',pos=str(stop*2),type='LEFT',leader='NONE')
    paras.append(style); paras.set('itemCnt',str(len(paras))); tabs.set('itemCnt',str(len(tabs))); p.set('paraPrIDRef',style.get('id'))
    old = p.findall(HP+'run'); attrs = dict(old[0].attrib)
    for run in old: p.remove(run)
    def run(sid):
        r = etree.Element(HP+'run',attrib={**attrs,'charPrIDRef':sid}); p.insert(len(p)-1,r); return r
    def tabchild(r): etree.SubElement(r,HP+'tab',width='1',leader='0',type='1')
    first = run(charid); tabchild(first); etree.SubElement(first,HP+'t').text=plan['labels'][0]; tabchild(first)
    middle = run(plan['charid']); tabchild(middle); etree.SubElement(middle,HP+'t').text=plan['middle']; tabchild(middle)
    last = run(charid); tabchild(last); etree.SubElement(last,HP+'t').text=plan['labels'][1]; tabchild(last)
    final = run(plan['charid']); etree.SubElement(final,HP+'t').text=plan['tail']
    require(body_text(p).replace('\t','') == oldtext, 'original native literal text changed')
    # Current native metrics alone assign all six advances. Source/canonical
    # caches authorize preserved Y only after the complete original replay.
    context = native_line_metrics.optional_native_context(header,native=native,budget=native_line_metrics.ProbeBudget())
    provider = context.for_paragraph(p) if context is not None else None
    styles = {c.get('id'):c for c in header.iter(HH+'charPr')}; para_styles = {c.get('id'):c for c in header.iter(HH+'paraPr')}
    require(provider is not None and native_line_cache.cache_lines_native(p,plan['width'],styles,para_styles,native_advance=provider),
            'current native six-TAB underline font metric plan failed')
    lines = p.findall(HP+'linesegarray/'+HP+'lineseg')
    require(len(lines) == len(plan['cache_fields']) == 2 and int(lines[0].get('textpos')) == 0,
            'fresh native cache changed source row count')
    # The plain separator belongs to the source-backed first row. A carried
    # separator would shift the next row, so fail instead of restoring its Y
    # over an incompatible current native boundary.
    boundary = int(lines[1].get('textpos'))
    expected = int(plan['cache_fields'][1]['textpos'])+48
    require(boundary == expected, 'fresh native cache crossed a source row boundary')
    units = provider.units; before=[]; after=[]; position=0
    for unit in units:
        (before if position < boundary else after).append(unit)
        position += unit[2]
    require(sum(u[2] for u in before) == boundary and sum(u[1]=='\t' for u in before) == 6
            and not any(u[1]=='\t' for u in after)
            and compact(''.join(u[1] for u in before)) == source['rule_row_nonspace_text']
            and compact(''.join(u[1] for u in after)) == compact(plan['tail']),
            'fresh native cache lost/moved source row ink or TAB coverage')
    for i,(line,fields) in enumerate(zip(lines,plan['cache_fields'])):
        position = line.get('textpos'); line.attrib.clear(); line.attrib.update(fields); line.set('textpos',position)
    return {'native_tab_stops_hwp':stops,'native_tab_widths_hwp':[int(t.get('width')) for t in p.findall(HP+'run/'+HP+'tab')],
            'native_metric_probes':provider.probes,'native_capability':context.capability_evidence,
            'fresh_native_second_row_textpos':boundary,'canonical_second_row_with_tabs':expected,
            'preserved_canonical_y_fields':True,'canonical_source_rows':plan['canonical_rows'],
            'native_cache':[dict(c.attrib) for c in lines]}


def reconstruct_from_items(data, source_path, items, *, native=None):
    """Stage complete source/native proof or return exactly the input bytes."""
    report = {'scope':'source-complete editable labeled answer rules; source Y/thickness separate',
              'questions_examined':0,'changed_groups':0,'plans':[],'source_oracle_dependency':False,
              'product_applied':False}
    try:
        source_path = Path(source_path).resolve(); digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        questions = headers.source_owners_from_items(source_path,items)
        with ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist(); require(len({guards._zip_name(i) for i in infos}) == len(infos), 'duplicate ZIP entries')
            parts = {i.filename:archive.read(i.filename) for i in infos}
        header = etree.fromstring(parts['Contents/header.xml'])
        sections = {n:etree.fromstring(v) for n,v in parts.items() if re.fullmatch(r'Contents/section\d+\.xml',n)}
        draws = {}
        for name,section in sections.items():
            for draw in section.iter(HP+'drawText'):
                match = re.fullmatch(r'question:v\d+:q(\d+)',draw.get('name',''))
                if match:
                    number = int(match[1]); require(number not in draws, 'duplicate native question owner')
                    draws[number] = (name,section,draw)
        require(set(draws) == set(questions), 'incomplete native/source named question ownership')
        report['questions_examined'] = len(draws)
        for number,(_,_,draw) in draws.items():
            require(Counter(headers.comparable(''.join(c['c'] for c in headers.ordered_source(questions[number])))) == Counter(headers.comparable(body_text(draw))),
                    'complete native/source question inventory disagreement '+str(number))
        if native is None:
            import rhwp as native
        painted, native_chars = _native_paint(data,native)
        with fitz.open(source_path) as document:
            for number,(name,section,draw) in sorted(draws.items()):
                question = questions[number]; page = document[question.page-1]
                source = source_labeled_rule_plan(document,page,question,draw)
                if source is None: continue
                columns = _column_plan(section,draw,question,page,source,source_path,digest)
                ownership = headers.bind_native_owner(draw,question,columns,native_chars)
                layout, rows, program = _canonical_source_frame(document,page,question,source,items,columns)
                plan = _canonical_native_cell(header,section,draw,question,source,layout,columns)
                result = _apply_native_rule(header,source,plan,columns,native)
                report['plans'].append({'question':number,'source_page':question.page,'source_plan':source,
                    'source_full_frame_program':program,'current_canonical_geometry':plan['canonical_geometry'],
                    'native_paragraph_id':plan['paragraph'].get('id'),'native_cell_content_origin_hwp':plan['origin_hwp'],
                    'native_content_width_hwp':plan['width'],**ownership,**result})
        require(hashlib.sha256(source_path.read_bytes()).hexdigest() == digest, 'source changed during proof')
        if not report['plans']: return data,report
        parts['Contents/header.xml'] = etree.tostring(header,xml_declaration=True,encoding='utf-8',standalone=True)
        for name,section in sections.items(): parts[name] = etree.tostring(section,xml_declaration=True,encoding='utf-8',standalone=True)
        output = io.BytesIO()
        with ZipFile(output,'w',compression=ZIP_DEFLATED) as archive:
            for info in infos: archive.writestr(info,parts[info.filename])
        report['changed_groups'] = len(report['plans']); report['staged_atomic_clone'] = True
        return output.getvalue(),report
    except (OSError,ValueError,TypeError,KeyError,IndexError,AttributeError,RuntimeError,UnicodeError,
            StopIteration,struct.error,BadZipFile,etree.XMLSyntaxError) as error:
        report['abstention'] = str(error); report['changed_groups'] = 0
        return data,report


def apply_source_labeled_rules(path, items):
    """Apply proved answer intervals in the basic English source-layout path."""
    import os
    import tempfile
    from hwpx.tools.package_validator import validate_editor_open_safety
    fallback = {'changed_groups': 0, 'abstained': True, 'atomic_rejection': True}
    try:
        paths = {Path(layout['source_pdf_path']).resolve() for item in items
                 for layout in [item.get('layout') or {}] if layout.get('source_pdf_path')}
        if len(paths) != 1:
            return fallback
        target = Path(path)
        original = target.read_bytes()
        updated, report = reconstruct_from_items(original, paths.pop(), items)
        if updated == original:
            return report
        descriptor, name = tempfile.mkstemp(dir=str(target.parent), suffix='.hwpx.tmp')
        os.close(descriptor)
        staged = Path(name)
        try:
            staged.write_bytes(updated)
            if not validate_editor_open_safety(staged).ok:
                return fallback
            if target.read_bytes() != original:
                return fallback
            os.replace(staged, target)
            report['product_applied'] = True
            return report
        finally:
            staged.unlink(missing_ok=True)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError,
            BadZipFile, etree.XMLSyntaxError):
        return fallback
