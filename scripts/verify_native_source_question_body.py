"""Actual-source instruction/body boundaries, native rails and public editing.

This is a semantic-layout regression. Every glyph's horizontal residual is
reported separately: the remaining Times word-space discrepancy is not made
into a successful full-page fidelity result by this check.
"""
from copy import deepcopy
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from lxml import etree
import rhwp
from app.pdf_native_content import extract_native_content
from app.pdf_source_question_body import (
    HP, HH, split_source_question_body, restore_source_instruction_cache,
    restore_source_question_body_right,
)
from app.hwpx_writer_v2 import HwpxDocument
from hwpx.oxml import HwpxOxmlParagraph

HC = '{http://www.hancom.co.kr/hwpml/2011/core}'


def compact(text):
    return re.sub(r'\s+', '', text)


def direct_text(paragraph):
    return ''.join(node.text or '' for node in paragraph.findall(HP+'run/'+HP+'t'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(path):
    with ZipFile(path) as archive:
        header = etree.fromstring(archive.read('Contents/header.xml'))
        sections = [etree.fromstring(archive.read(name)) for name in archive.namelist()
                    if re.fullmatch(r'Contents/section\d+\.xml', name)]
    return header, sections


def question(sections, number):
    draws = [draw for section in sections for draw in section.iter(HP+'drawText')
             if draw.get('name') == f'question:v1:q{number}']
    assert len(draws) == 1, ('unique question', number, len(draws))
    return draws[0]


def margins(header, paragraph):
    style = next(p for p in header.iter(HH+'paraPr') if p.get('id') == paragraph.get('paraPrIDRef'))
    margin = style.find('.//'+HH+'margin')
    return {key: int(margin.find(HC+key).get('value')) for key in ('left','intent','right')}


def para_style(header, paragraph):
    return next(p for p in header.iter(HH+'paraPr') if p.get('id') == paragraph.get('paraPrIDRef'))


def native_right(header, paragraph):
    return int(para_style(header,paragraph).find('.//'+HH+'margin/'+HC+'right').get('value'))


def attached_body(sections, item):
    candidates = [p for p in question(sections,item['layout']['question_number']).iter(HP+'p')
                  if direct_text(p) == item['stem']]
    assert len(candidates) == 1, ('unique source body',item['layout']['question_number'],len(candidates))
    return candidates[0]


def right_guards(header, sections, fixtures, page_width, check):
    """Exercise the actual wrapper and source without inventing fixture proof."""
    results, negative_count = [], 0
    labels = ('missingproof','nonliteral','missingpdf','wrongpage','boolpage','partialsource',
              'partialrecords','wrongrecord','recordtext','recordbaseline','recordsize','metasize',
              'syncomitlast','syncomitlast2',
              'prooffractionalflags','recordfractionalflags',
              'leftsource','wrongrail','nanwidth','nanpage',
              'table','answerblank','inlinelabel','detached','cell','noneditable','textwidth',
              'lastwidth','rectwidth','nativechange','nativecontrol','nativefont','nativeheight',
              'nativebold','nativeitalic','underline','outline','shadow','strikeout','emboss','engrave','kerning',
              'spaceheight','spacefont','spacebold','spaceitalic','spacefontlanguage',
              'fontspace','symbolmark','ratio','tracking','relsize','offset','metriclanguage',
              'superscript','missingcache','duplicatecache','shortcache','cachetextpos','cachewidth','cacheheight',
              'cachebaseline','cachetop','cachespacing','cacheflags','cachelargeheight',
              'nativeleft','nativeintent','nativeright','nativealign','duplicateid')
    for item in fixtures:
        original = attached_body(sections,item)
        # Keep the real ancestry, width and all resolved native character props.
        wrapper = original.getparent().getparent().getparent()
        index = list(wrapper.iter(HP+'p')).index(original)
        width = float(wrapper.find(HP+'sz').get('width'))
        def setup():
            rect, styles, meta = deepcopy(wrapper), deepcopy(header), deepcopy(item['layout'])
            body = list(rect.iter(HP+'p'))[index]
            base = para_style(styles,body)
            for margin in base.findall('.//'+HH+'margin'):
                margin.find(HC+'right').set('value','0')
            return rect,body,styles,meta
        rect,body,styles,meta = setup()
        old_native,old_styles = etree.tostring(body),etree.tostring(styles)
        old_resolved = styled_chars(styles,body)
        check(restore_source_question_body_right([(body,meta)],styles,page_width,width) == 1,
              f"Q{meta['question_number']} actual source/native body accepts measured right margin")
        rows = [[c for span in line['spans'] for c in span['chars'] if c['c'].strip()]
                for line in meta['source_typography']['lines']]
        rights = sorted(max(c['bbox'][2] for c in row) for row in rows[:-1])
        middle = len(rights)//2
        target = rights[middle] if len(rights)%2 else (rights[middle-1]+rights[middle])/2
        expected = round(width-(target-meta['column_left_pt'])*page_width/meta['source_page_width_pt'])
        check(native_right(styles,body) == expected and native_right(header,original) == expected,
              f"Q{meta['question_number']} fresh writer right margin equals source nonfinal ink rail")
        unchanged = deepcopy(body); unchanged.set('paraPrIDRef',original.get('paraPrIDRef'))
        canonical = lambda node: etree.tostring(node,method='c14n',exclusive=True)
        check(canonical(unchanged) == canonical(etree.fromstring(old_native))
              and styled_chars(styles,body) == old_resolved,
              'right restoration preserves every run, resolved character style and cache')
        old_nodes = list(etree.fromstring(old_styles).find('.//'+HH+'paraProperties'))
        new_nodes = list(styles.find('.//'+HH+'paraProperties'))
        check(all(canonical(a) == canonical(b) for a,b in zip(old_nodes,new_nodes))
              and len(new_nodes) == len(old_nodes)+1,
              'right restoration only appends a paragraph style and preserves shared styles')
        before_p,before_h = etree.tostring(body),etree.tostring(styles)
        check(restore_source_question_body_right([(body,meta)],styles,page_width,width) == 0
              and etree.tostring(body) == before_p and etree.tostring(styles) == before_h,
              'measured right-margin restoration is idempotent')
        results.append({'question':meta['question_number'],'source_rows':len(rows),'right':expected})
        for label in labels:
            rect,body,styles,meta = setup(); w,pw = width,page_width
            native_style = next(p for p in styles.iter(HH+'charPr')
                                if p.get('id') == body[0].get('charPrIDRef'))
            cache = body.find(HP+'linesegarray')
            margin = para_style(styles,body).find('.//'+HH+'margin')
            if label == 'missingproof': meta.pop('source_question_body')
            elif label == 'nonliteral': meta['source_literal_text'] = False
            elif label == 'missingpdf': meta['source_pdf_path'] += '.missing'
            elif label == 'wrongpage': meta['source_page_index'] = 0
            elif label == 'boolpage': meta['source_page_index'] = True
            elif label == 'partialsource': meta['source_question_body']['lines'].pop()
            elif label == 'partialrecords': meta['source_typography']['lines'].pop()
            elif label in ('syncomitlast','syncomitlast2'):
                from app.pdf_native_content import _source_typography
                from app.pdf_word_wrap import join_source_paragraph
                count = 1 if label == 'syncomitlast' else 2
                records = meta['source_typography']['lines'][:-count]
                lines = [{'bbox':r['bbox_pt'],'spans':r['spans']} for r in records]
                meta['source_typography'] = _source_typography(lines,{
                    'column_left_pt':meta['column_left_pt'],'column_right_pt':meta['column_right_pt']})
                meta['source_question_body']['lines'] = meta['source_question_body']['lines'][:-count]
                remaining = len(join_source_paragraph(lines))
                for run in list(body.findall(HP+'run')):
                    value = direct_text_run(run)
                    if remaining == 0: body.remove(run)
                    elif len(value) > remaining:
                        run[0].text = value[:remaining]; remaining = 0
                    else: remaining -= len(value)
                for row in list(cache)[-count:]: cache.remove(row)
            elif label == 'wrongrecord': meta['source_typography']['lines'][0]['bbox_pt'][0] += 1
            elif label == 'recordtext': meta['source_typography']['lines'][0]['text'] += 'x'
            elif label == 'recordbaseline': meta['source_typography']['lines'][0]['baseline_pt'] += 1
            elif label == 'recordsize': meta['source_typography']['lines'][0]['font_size_pt'] += 1
            elif label == 'metasize': meta['source_typography']['font_size_pt'] += 1
            elif label == 'prooffractionalflags': meta['source_question_body']['lines'][1]['spans'][0]['flags'] += .5
            elif label == 'recordfractionalflags': meta['source_typography']['lines'][0]['spans'][0]['flags'] += .5
            elif label == 'leftsource': meta['source_typography']['alignment'] = 'LEFT'
            elif label == 'wrongrail': meta['column_left_pt'] += 1
            elif label == 'nanwidth': w = float('nan')
            elif label == 'nanpage': pw = float('nan')
            elif label == 'table': meta['native_tables'] = [{}]
            elif label == 'answerblank': meta['source_answer_blanks'] = [{}]
            elif label == 'inlinelabel': meta['source_inline_labels'] = [{}]
            elif label == 'detached': body.getparent().remove(body)
            elif label == 'cell': etree.SubElement(etree.Element(HP+'tc'),HP+'subList').append(rect)
            elif label == 'noneditable': body.getparent().getparent().set('editable','0')
            elif label == 'textwidth': body.getparent().set('textWidth',str(width+10))
            elif label == 'lastwidth': body.getparent().getparent().set('lastWidth',str(width+10))
            elif label == 'rectwidth': rect.find(HP+'sz').set('width',str(width+10))
            elif label == 'nativechange': body[0][0].text += 'x'
            elif label == 'nativecontrol': etree.SubElement(body[0],HP+'equation')
            elif label == 'nativefont': native_style.find(HH+'fontRef').set('latin','999999')
            elif label == 'nativeheight': native_style.set('height',str(int(native_style.get('height'))+10))
            elif label == 'nativebold': etree.SubElement(native_style,HH+'bold')
            elif label == 'nativeitalic': etree.SubElement(native_style,HH+'italic')
            elif label.startswith('space') and label not in ('spacing',):
                run = next(r for r in body.findall(HP+'run') if ' ' in direct_text_run(r))
                value = direct_text_run(run); offset = value.index(' ')
                source_style = next(p for p in styles.iter(HH+'charPr') if p.get('id') == run.get('charPrIDRef'))
                space_style = deepcopy(source_style)
                identifier = str(max(int(p.get('id')) for p in styles.iter(HH+'charPr'))+1)
                space_style.set('id',identifier)
                styles.find('.//'+HH+'charProperties').append(space_style)
                index = body.index(run); body.remove(run)
                for value,style_id in ((value[:offset],run.get('charPrIDRef')),(' ',identifier),(value[offset+1:],run.get('charPrIDRef'))):
                    if not value: continue
                    clone = deepcopy(run); clone[0].text = value; clone.set('charPrIDRef',style_id)
                    body.insert(index,clone); index += 1
                if label == 'spaceheight': space_style.set('height',str(int(space_style.get('height'))+10))
                elif label == 'spacefont':
                    font = space_style.find(HH+'fontRef')
                    candidates = [f for face in styles.iter(HH+'fontface') if face.get('lang') == 'LATIN' for f in face]
                    current = next(f.get('face') for f in candidates if f.get('id') == font.get('latin'))
                    font.set('latin',next(f.get('id') for f in candidates if f.get('face') != current))
                elif label == 'spacefontlanguage': space_style.find(HH+'fontRef').attrib.pop('hangul')
                else:
                    tag = HH+label.removeprefix('space'); node = space_style.find(tag)
                    if node is None: etree.SubElement(space_style,tag)
                    else: space_style.remove(node)
            elif label == 'underline': native_style.find(HH+'underline').set('type','BOTTOM')
            elif label == 'outline': native_style.find(HH+'outline').set('type','SOLID')
            elif label == 'shadow': native_style.find(HH+'shadow').set('type','DROP')
            elif label == 'strikeout': etree.SubElement(native_style,HH+'strikeout',shape='SOLID')
            elif label in ('emboss','engrave'): etree.SubElement(native_style,HH+label)
            elif label == 'kerning': native_style.set('useKerning','1')
            elif label == 'fontspace': native_style.set('useFontSpace','1')
            elif label == 'symbolmark': native_style.set('symMark','DOT_ABOVE')
            elif label in ('ratio','tracking','relsize','offset'):
                tag = {'tracking':'spacing','relsize':'relSz'}.get(label,label)
                metric = native_style.find(HH+tag)
                for key in metric.attrib: metric.set(key,str(int(metric.get(key))+1))
            elif label == 'metriclanguage':
                metric = native_style.find(HH+'ratio')
                for key in list(metric.attrib):
                    if key != 'latin': metric.attrib.pop(key)
            elif label == 'superscript': etree.SubElement(native_style,HH+'supscript')
            elif label == 'missingcache': body.remove(cache)
            elif label == 'duplicatecache': body.append(deepcopy(cache))
            elif label == 'shortcache': cache.remove(cache[-1])
            elif label == 'cachetextpos': cache[0].set('textpos','1')
            elif label == 'cachewidth': cache[0].set('horzsize',str(width+10))
            elif label == 'cacheheight': cache[0].set('textheight','1')
            elif label == 'cachebaseline': cache[0].set('baseline',str(int(cache[0].get('textheight'))+1))
            elif label == 'cachetop': cache[0].set('vertpos','9999')
            elif label == 'cachespacing': cache[0].set('spacing','9999')
            elif label == 'cacheflags': cache[0].set('flags','0')
            elif label == 'cachelargeheight':
                for key,value in (('vertsize','9999'),('textheight','9999'),('baseline','8888')):
                    cache[0].set(key,value)
            elif label in ('nativeleft','nativeintent','nativeright'):
                tag = label.removeprefix('native'); node = margin.find(HC+tag)
                node.set('value',str(int(node.get('value'))+10))
            elif label == 'nativealign': para_style(styles,body).find(HH+'align').set('horizontal','LEFT')
            elif label == 'duplicateid':
                properties = styles.find('.//'+HH+'paraProperties'); properties.append(deepcopy(properties[0]))
            before_rect,before_p,before_h = etree.tostring(rect),etree.tostring(body),etree.tostring(styles)
            check(restore_source_question_body_right([(body,meta)],styles,pw,w) == 0,
                  f'{label} body right-margin request abstains')
            check(etree.tostring(rect) == before_rect and etree.tostring(body) == before_p
                  and etree.tostring(styles) == before_h,f'{label} body right-margin rejection is atomic')
            negative_count += 1
    return results,negative_count


def styled_chars(header, paragraph):
    styles = {p.get('id'): p for p in header.iter(HH+'charPr')}
    values = []
    for run in paragraph.findall(HP+'run'):
        clone = deepcopy(styles[run.get('charPrIDRef')]); clone.attrib.pop('id', None)
        key = etree.tostring(clone, method='c14n', exclusive=True)
        values.extend((char, key) for char in direct_text_run(run))
    return values


def direct_text_run(run):
    return ''.join(t.text or '' for t in run.findall(HP+'t'))


def painted(path, folder, label):
    parsed = rhwp.parse(str(path))
    svg = parsed.render_svg(1)
    (folder/f'{label}-p2.svg').write_text(svg, encoding='utf8')
    (folder/f'{label}-p2.png').write_bytes(bytes(parsed.render_png(1)))
    pdf_path = folder/f'{label}.pdf'
    pdf_path.write_bytes(bytes(parsed.render_pdf()))
    document = fitz.open(pdf_path)
    glyphs = [(index, char) for index, page in enumerate(document)
              for trace in page.get_texttrace() if trace.get('type') == 0 and trace.get('opacity',1) > .99
              for char in trace['chars'] if not chr(char[0]).isspace()]
    return parsed.page_count, document, glyphs


def locate(glyphs, value):
    text = ''.join(chr(char[0]) for _,char in glyphs); needle = compact(value)
    assert text.count(needle) == 1, ('unique painted text', needle[:60], text.count(needle))
    start = text.index(needle)
    return glyphs[start:start+len(needle)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'data/external_exam_qa/2027_kice_september_high3/english.pdf')
    parser.add_argument('--hwpx', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'tmp/september-exam-matrix/source-question-body-regression')
    parser.add_argument('--guards-only', action='store_true', help='run source/native atomic guards without painting or public editing')
    args = parser.parse_args()
    missing = [str(p) for p in (args.source,args.hwpx) if not p.is_file()]
    if missing:
        print('SKIP: actual source/native fixture missing:', missing)
        return 2
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('HWP_MAKE_DATA_DIR', str(args.output/'data'))
    owned = [ROOT/'app/pdf_source_question_body.py', ROOT/'app/pdf_native_content.py', ROOT/'app/pdf_native_typography.py']
    before = {str(p.relative_to(ROOT)):sha(p) for p in owned}
    report = {'source_sha256':sha(args.source),'input_sha256':sha(args.hwpx),
              'code_before':before,'scope':'source-proven semantic boundaries and first-ink rails',
              'full_fidelity_claim':False,'checks':[]}
    def check(value, message):
        assert value, message
        report['checks'].append(message)
        print('PASS:',message,flush=True)
    try:
        items,_ = extract_native_content(args.source,max_pages=3,area_hint='영어 영역')
        fixtures = [item for item in items if item.get('layout',{}).get('source_question_instruction')]
        check([i['layout']['question_number'] for i in fixtures] == [19,20,21,22,23,24],
              'actual source proves all six instruction/body boundaries')
        body_fixtures = [item for item in items if item.get('layout',{}).get('source_question_body')]
        check([i['layout']['question_number'] for i in body_fixtures] == [19,20,21,22,23,24],
              'actual source independently proves all six instruction/body relationships')
        header,sections = package(args.hwpx)
        source = fitz.open(args.source)
        page_width = float(sections[0].find('.//'+HP+'pagePr').get('width'))
        source_page = source[1]
        cache_positive = 0
        negative_count = 0
        for item in fixtures:
            layout = item['layout']; lines = layout['source_question_instruction']['lines']
            source_page = source[layout['source_page_index']]
            groups = split_source_question_body(lines,page=source_page,area_hint='영어 영역',existing_boundary=True)
            instruction_rows = len(layout['source_typography']['lines'])
            check([len(g) for g in groups] == [instruction_rows,len(lines)-instruction_rows], f"Q{layout['question_number']} keeps two semantic paragraphs")
            check([line for group in groups for line in group] == lines, 'split preserves every raw span, character and source origin')
            paragraph_list = list(question(sections,layout['question_number']).iter(HP+'p'))
            prompt,body = paragraph_list[:2]
            body_source = ''.join(c['c'] for line in groups[1] for span in line['spans'] for c in span['chars'])
            check(compact(direct_text(prompt)) == compact(item['stem']) and compact(direct_text(body)) == compact(body_source), 'native text and body order match the complete source')
            check(not any(n.tag in (HP+'lineBreak',HP+'equation',HP+'tbl',HP+'pic') for n in body.iter()), 'body is one ordinary editable prose paragraph')
            raw = [[c for span in line['spans'] for c in span['chars'] if c['c'].strip()] for line in groups[1]]
            scale = page_width/source_page.rect.width
            expected = {'left':round((raw[1][0]['origin'][0]-layout['column_left_pt'])*scale),
                        'intent':round((raw[0][0]['origin'][0]-raw[1][0]['origin'][0])*scale)}
            check(all(abs(margins(header,body)[key]-value) <= 1 for key,value in expected.items()), 'native left and first-line indent derive from actual first ink')
            probe = deepcopy(prompt); old_runs = [etree.tostring(r) for r in probe.findall(HP+'run')]
            old_header = etree.tostring(header)
            width = float(prompt.find(HP+'linesegarray')[0].get('horzsize'))
            check(restore_source_instruction_cache(probe,layout,header,page_width,width), 'actual source/native size proof accepts prompt cache height')
            check([etree.tostring(r) for r in probe.findall(HP+'run')] == old_runs and etree.tostring(header) == old_header, 'cache height restoration leaves every run and shared style unchanged')
            max_height = max(int(next(p for p in header.iter(HH+'charPr') if p.get('id') == r.get('charPrIDRef')).get('height')) for r in prompt.findall(HP+'run'))
            check(int(probe.find(HP+'linesegarray')[0].get('textheight')) >= max_height, 'prompt cache contains the tallest actual native source run')
            prompt_cache = probe.find(HP+'linesegarray')
            check([int(row.get('textheight')) for row in prompt_cache] ==
                  [round(max(span['size'] for span in line['spans'])*scale) for line in groups[0]],
                  'each instruction cache row contains its own actual tallest source/native run')
            if instruction_rows > 1:
                baseline_positions = [int(row.get('vertpos'))+int(row.get('baseline')) for row in prompt_cache]
                source_positions = [record['baseline_pt']*scale for record in layout['source_typography']['lines']]
                check(all(abs((b-a)-(y-x)) <= 1 for a,b,x,y in zip(baseline_positions,baseline_positions[1:],source_positions,source_positions[1:])),
                      'different row heights preserve exact source instruction baseline gaps')
            cache_positive += 1
            # These are unsupported source data, not exceptions or weakened matches.
            for label in ('nonenglish','missingpage','ordinarybody','missingraw','nanbbox','shortbbox','nanspan','shortorigin','eqfont','partialtext','answerblank','omitlast','omitlast2','omitmiddle','duplicaterow','reverserows'):
                changed = deepcopy(lines); page = source_page; hint = '영어 영역'; blanks = ()
                if label == 'nonenglish': hint = '수학 영역'
                elif label == 'missingpage': page = None
                elif label == 'ordinarybody': changed = changed[1:]
                elif label == 'missingraw': changed[1]['spans'][0]['chars'] = []
                elif label == 'nanbbox': changed[1]['bbox'][0] = float('nan')
                elif label == 'shortbbox': changed[1]['bbox'] = changed[1]['bbox'][:3]
                elif label == 'nanspan':
                    changed[1]['spans'][0]['bbox'] = [float('nan'),*changed[1]['spans'][0]['bbox'][1:]]
                elif label == 'shortorigin': changed[1]['spans'][0]['chars'][0]['origin'] = [1]
                elif label == 'eqfont': changed[1]['spans'][0]['font'] = 'HancomEqn'
                elif label == 'partialtext': changed[1]['spans'][0]['text'] += ' changed'
                elif label == 'answerblank': blanks = ({'line_bbox_pt':list(changed[1]['bbox'])},)
                elif label == 'omitlast': changed.pop()
                elif label == 'omitlast2': changed = changed[:-2]
                elif label == 'omitmiddle': changed.pop(instruction_rows+1)
                elif label == 'duplicaterow': changed.insert(instruction_rows+1,deepcopy(changed[instruction_rows]))
                elif label == 'reverserows': changed = changed[:instruction_rows]+list(reversed(changed[instruction_rows:]))
                untouched = deepcopy(changed)
                result = split_source_question_body(changed,page=page,area_hint=hint,answer_blanks=blanks)
                # NaN equality is deliberately not used as an immutability check.
                check(len(result) == 1 and result[0] is changed, f'{label} source data abstains')
                check(repr(changed) == repr(untouched), f'{label} source data stays unchanged')
                negative_count += 1
            for label in ('nonliteral','missingpdf','wrongpage','nanwidth','nanpage','partialsource','nativeequation','wrongheight','recordtext','recordbaseline','recordsize','recordflags','shortrecords','duplicaterecords','missingcache','duplicatecache','sourceomitlast','sourceomitlast2'):
                native,meta,styles = deepcopy(prompt),deepcopy(layout),deepcopy(header)
                w,pw = width,page_width
                if label == 'nonliteral': meta['source_literal_text'] = False
                elif label == 'missingpdf': meta['source_pdf_path'] = str(args.output/'missing.pdf')
                elif label == 'wrongpage': meta['source_page_index'] = 0
                elif label == 'nanwidth': w = float('nan')
                elif label == 'nanpage': pw = float('nan')
                elif label == 'partialsource': meta['source_question_instruction']['lines'][1]['spans'][0]['text'] += 'x'
                elif label == 'nativeequation': etree.SubElement(native[0],HP+'equation')
                elif label == 'wrongheight': next(p for p in styles.iter(HH+'charPr') if p.get('id') == native[0].get('charPrIDRef')).set('height','2000')
                elif label == 'recordtext': meta['source_typography']['lines'][0]['text'] += 'x'
                elif label == 'recordbaseline': meta['source_typography']['lines'][0]['baseline_pt'] += 1
                elif label == 'recordsize': meta['source_typography']['lines'][0]['font_size_pt'] += 1
                elif label == 'recordflags': meta['source_typography']['lines'][0]['spans'][0]['flags'] += .5
                elif label == 'shortrecords': meta['source_typography']['lines'].pop()
                elif label == 'duplicaterecords': meta['source_typography']['lines'].append(deepcopy(meta['source_typography']['lines'][-1]))
                elif label == 'missingcache': native.remove(native.find(HP+'linesegarray'))
                elif label == 'duplicatecache': native.append(deepcopy(native.find(HP+'linesegarray')))
                elif label == 'sourceomitlast': meta['source_question_instruction']['lines'].pop()
                elif label == 'sourceomitlast2': meta['source_question_instruction']['lines'] = meta['source_question_instruction']['lines'][:-2]
                old_native,old_styles = etree.tostring(native),etree.tostring(styles)
                check(not restore_source_instruction_cache(native,meta,styles,pw,w), f'{label} native cache request abstains')
                check(etree.tostring(native) == old_native and etree.tostring(styles) == old_styles, f'{label} native cache rejection is atomic')
                negative_count += 1
        right_results,right_negatives = right_guards(header,sections,body_fixtures,page_width,check)
        report['measured_right_margins'] = right_results
        negative_count += right_negatives
        if args.guards_only:
            report.update(cache_positive=cache_positive,negative_count=negative_count,
                          semantic_layout_ok=True,guards_only=True)
            report['code_after'] = {str(p.relative_to(ROOT)):sha(p) for p in owned}
            check(report['code_after'] == before, 'owned producer/helper code is unchanged during guard verification')
            report['ok'] = True
            print('NATIVE_SOURCE_QUESTION_BODY_GUARDS_OK:',len(report['checks']),'checks;',negative_count,'negatives')
            return 0
        pages,pdf,glyphs = painted(args.hwpx,args.output,'initial')
        check(pages == 8, 'actual initial document retains eight physical pages')
        all_rows = []
        for item in fixtures:
            row_reports = []
            lines = item['layout']['source_question_instruction']['lines']
            source_page = source[item['layout']['source_page_index']]
            for index,line in enumerate(lines):
                chars = [c for span in line['spans'] for c in span['chars'] if c['c'].strip()]
                actual = locate(glyphs,''.join(c['c'] for c in chars))
                scale = pdf[actual[0][0]].rect.width/source_page.rect.width*4/3
                dx = [native[2][0]*4/3-src['origin'][0]*scale for (_,native),src in zip(actual,chars)]
                dy = actual[0][1][2][1]*4/3-chars[0]['origin'][1]*scale
                row_reports.append({'text':''.join(c['c'] for c in chars),'glyphs':len(chars),'first_dx':dx[0],
                                    'first_dy':dy,'last_dx':dx[-1],'max_abs_dx':max(map(abs,dx))})
                if index >= len(item['layout']['source_typography']['lines']):
                    check(abs(dx[0]) <= .6 and abs(dy) <= .6, 'actual PDF body first-ink x/y agrees with source within existing 0.6px rail')
            all_rows.append({'question':item['layout']['question_number'],'rows':row_reports})
        report['every_glyph_horizontal_diagnostic'] = all_rows
        report['remaining_wordspace_fidelity'] = {
            'ok':False,'last_body_line_max_abs_dx_px': [q['rows'][-1]['max_abs_dx'] for q in all_rows],
            'meaning':'All glyphs were measured; first-ink success does not claim word-space fidelity.'}
        all_body_rows = []
        for item in body_fixtures:
            meta = item['layout']; row_reports = []
            source_page = source[meta['source_page_index']]
            for record in meta['source_typography']['lines']:
                chars = [c for span in record['spans'] for c in span['chars'] if c['c'].strip()]
                actual = locate(glyphs,''.join(c['c'] for c in chars))
                scale = pdf[actual[0][0]].rect.width/source_page.rect.width*4/3
                dx = [native[2][0]*4/3-src['origin'][0]*scale for (_,native),src in zip(actual,chars)]
                dy = [native[2][1]*4/3-src['origin'][1]*scale for (_,native),src in zip(actual,chars)]
                row_reports.append({'glyphs':len(chars),'first_dx':dx[0],'first_dy':dy[0],
                                    'last_dx':dx[-1],'max_abs_dx':max(map(abs,dx)),
                                    'max_abs_dy':max(map(abs,dy))})
            all_body_rows.append({'question':meta['question_number'],'rows':row_reports,
                                 'max_abs_dx':max(r['max_abs_dx'] for r in row_reports),
                                 'max_abs_dy':max(r['max_abs_dy'] for r in row_reports)})
        report['every_proved_body_glyph_diagnostic'] = all_body_rows
        # Exercise regular, mixed italic and source fallback bodies through public editing.
        report['public_editing'] = []
        for number in (19,21,24):
            document = HwpxDocument.open(args.hwpx)
            section,draw = next((s,d) for s in document.sections for d in s.element.iter(HP+'drawText') if d.get('name') == f'question:v1:q{number}')
            body = list(draw.iter(HP+'p'))[1]
            old_text,old_margins = direct_text(body),margins(header,body)
            # Resolve styles from a saved package rather than relying on private API.
            old_styles = styled_chars(header,body)
            public = HwpxOxmlParagraph(body,section)
            last_run = next(run for run in reversed(public.runs) if run.text)
            addition = ' Careful communication helps friends understand each other and resolve difficult disagreements.'
            public.add_run(addition,char_pr_id_ref=last_run.element.get('charPrIDRef'))
            check(body.find(HP+'linesegarray') is None, 'public body append invalidates the measured line cache')
            grown = args.output/('grown.hwpx' if number == 19 else f'grown-q{number}.hwpx'); document.save_to_path(grown)
            new_header,new_sections = package(grown)
            grown_draw = question(new_sections,number); grown_body = list(grown_draw.iter(HP+'p'))[1]
            check(direct_text(grown_body) == old_text+addition and margins(new_header,grown_body) == old_margins, 'public save keeps semantic body text and both native indents')
            check(styled_chars(new_header,grown_body)[:len(old_styles)] == old_styles, 'public append preserves every original resolved character style')
            _,grown_pdf,grown_glyphs = painted(grown,args.output,'grown' if number == 19 else f'grown-q{number}')
            locate(grown_glyphs,old_text+addition)
            following = direct_text(list(question(sections,number).iter(HP+'p'))[2])
            initial_body,initial_next = locate(glyphs,old_text)[0],locate(glyphs,following)[0]
            edited_body,edited_next = locate(grown_glyphs,old_text+addition)[0],locate(grown_glyphs,following)[0]
            def advance(record,origin,doc):
                return (record[0]-origin[0])*doc[0].rect.height+record[1][2][1]-origin[1][2][1]
            check(advance(edited_next,edited_body,grown_pdf) > advance(initial_next,initial_body,pdf)+1, 'following choices move below the growing semantic body')
            reopened = args.output/('grown-reopened.hwpx' if number == 19 else f'grown-q{number}-reopened.hwpx'); HwpxDocument.open(grown).save_to_path(reopened)
            reopened_header,reopened_sections = package(reopened)
            reopened_body = list(question(reopened_sections,number).iter(HP+'p'))[1]
            check(direct_text(reopened_body) == old_text+addition and margins(reopened_header,reopened_body) == old_margins, 'fresh reopen/resave preserves body ownership and indentation')
            reopened_native, grown_native = rhwp.parse(str(reopened)), rhwp.parse(str(grown))
            check(reopened_native.page_count == grown_native.page_count and all(reopened_native.render_svg(page) == grown_native.render_svg(page) for page in range(grown_native.page_count)), 'fresh reopen/resave keeps every edited page painting stable')
            report['public_editing'].append({'question':number,'native_margins':old_margins,'pages':grown_native.page_count,'all_original_character_styles_preserved':True,'all_pages_reopen_svg_equal':True})
        report.update(cache_positive=cache_positive,negative_count=negative_count,initial_pages=pages,semantic_layout_ok=True)
        report['code_after'] = {str(p.relative_to(ROOT)):sha(p) for p in owned}
        check(report['code_after'] == before, 'owned producer/helper code is unchanged during verification')
        report['ok'] = True
        print('NATIVE_SOURCE_QUESTION_BODY_OK:',len(report['checks']),'checks;',negative_count,'negatives; remaining word-space fidelity explicitly false')
        return 0
    except Exception as error:
        report['ok'] = False; report['error'] = repr(error)
        print('FAIL:',repr(error),flush=True)
        raise
    finally:
        (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')


if __name__ == '__main__':
    raise SystemExit(main())
