"""Independent actual-source body spaces and native right-margin guards.

Reads the existing PDF and HWPX only. Mutants retain the real source text and
native structure unless the named case deliberately changes that condition.
This is a proof/transaction review, not a full-page paint quality verdict.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pdf_native_content import extract_native_content
from app.pdf_source_body_spaces import source_body_space_styles
from app.pdf_source_question_body import HP, HH, HC, restore_source_question_body_right
from app.pdf_source_run_styles import restore_source_run_styles


def text(paragraph):
    return ''.join(t.text or '' for t in paragraph.findall(HP+'run/'+HP+'t'))


def body(root, number):
    draw = next(d for d in root.iter(HP+'drawText') if d.get('name') == f'question:v1:q{number}')
    return list(draw.iter(HP+'p'))[1]


def style_maps(header):
    return ({p.get('id'):p for p in header.iter(HH+'paraPr')},
            {p.get('id'):p for p in header.iter(HH+'charPr')})


def right(header, paragraph):
    return style_maps(header)[0][paragraph.get('paraPrIDRef')].find('.//'+HH+'margin/'+HC+'right')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hwpx', type=Path, default=ROOT/'tmp/september-exam-matrix/high3-p2-readonly/producer3.hwpx')
    parser.add_argument('--source', type=Path, default=ROOT/'data/external_exam_qa/2027_kice_september_high3/english.pdf')
    parser.add_argument('--report', type=Path, default=ROOT/'tmp/september-audit/body-right-independent/report.json')
    parser.add_argument('--late-guards-only',action='store_true',help='Run actual right-margin positives plus the final flags/emboss/engrave guards.')
    args = parser.parse_args()
    if not args.hwpx.is_file() or not args.source.is_file():
        print('SKIP: existing actual source PDF and native HWPX required')
        return 2
    code = [ROOT/name for name in ('app/pdf_source_body_spaces.py', 'app/pdf_source_question_body.py',
                                  'app/pdf_source_run_styles.py')]
    hashes = lambda: {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in code}
    before_code = hashes()
    with ZipFile(args.hwpx) as package:
        header = etree.fromstring(package.read('Contents/header.xml'))
        roots = [etree.fromstring(package.read(n)) for n in package.namelist()
                 if n.startswith('Contents/section') and n.endswith('.xml')]
    items,_ = extract_native_content(args.source,max_pages=3,area_hint='영어 영역')
    fixtures = {i['layout']['question_number']:i for i in items if i['layout'].get('source_question_body')}
    page_width = float(roots[0].find('.//'+HP+'pagePr').get('width'))
    checks,failures = [],[]
    def record(name, passed, **evidence):
        checks.append({'name':name,'passed':bool(passed),**evidence})
        print(('PASS: ' if passed else 'FAIL: ')+name,flush=True)
        if not passed:
            failures.append(name)
    def fixture(number=19):
        root = deepcopy(next(r for r in roots if any(d.get('name') == f'question:v1:q{number}'
                         for d in r.iter(HP+'drawText'))))
        h,l = deepcopy(header),deepcopy(fixtures[number]['layout'])
        p = body(root,number)
        right(h,p).set('value','0')
        return root,h,l,p,float(p.getparent().get('textWidth'))

    for number in (19,20,21,22,23,24):
        root,h,l,p,width = fixture(number)
        old_runs = [etree.tostring(r) for r in p.findall(HP+'run')]
        old_cache = etree.tostring(p.find(HP+'linesegarray'))
        old_styles = [etree.tostring(s) for s in h.find('.//'+HH+'paraProperties')]
        count = restore_source_question_body_right([(p,l)],h,page_width,width)
        measured = int(right(h,p).get('value'))
        passed = count == 1 and 0 < measured < 2000
        passed &= old_runs == [etree.tostring(r) for r in p.findall(HP+'run')]
        passed &= old_cache == etree.tostring(p.find(HP+'linesegarray'))
        passed &= old_styles == [etree.tostring(s) for s in h.find('.//'+HH+'paraProperties')][:-1]
        record(f'actual_q{number}_right_clone_only',passed,native_right=measured)
        before = etree.tostring(root),etree.tostring(h)
        count = restore_source_question_body_right([(p,l)],h,page_width,width)
        record(f'actual_q{number}_margin_reapply_stable',count == 0 and before == (etree.tostring(root),etree.tostring(h)))

    allocated,ids = {},{}
    def char_style(base,height,font,tracking,ratio,bold,*,italic):
        signature = height,font,tracking,ratio,bold,italic
        if signature not in ids:
            ident = str(len(ids)+1);ids[signature] = ident;allocated[ident] = signature
        return ids[signature]
    for number in (() if args.late_guards_only else (19,20,22)):
        item = fixtures[number]
        layout,raw = item['layout'],item['stem']
        cursor,positions = 0,set()
        for offset,char in enumerate(raw):
            if char == ' ' and offset and offset+1 < len(raw) and not raw[offset-1].isspace() and not raw[offset+1].isspace():
                positions.add(cursor)
            if not char.isspace():
                cursor += 1
        actual = source_body_space_styles(layout)
        record(f'actual_q{number}_independent_native_space_positions',set(actual) == positions and set(actual.values()) == {(80,-15)},spaces=len(positions))
        for shape in ('one_run','per_character_empty_runs','double_space','nbsp','tab'):
            value = raw.replace(' ','  ' if shape == 'double_space' else '\u00a0' if shape == 'nbsp' else '\t' if shape == 'tab' else ' ')
            p = etree.Element(HP+'p')
            for part in list(value) if shape == 'per_character_empty_runs' else [value]:
                if shape == 'per_character_empty_runs':
                    etree.SubElement(etree.SubElement(p,HP+'run',charPrIDRef='0'),HP+'t').text = ''
                etree.SubElement(etree.SubElement(p,HP+'run',charPrIDRef='0'),HP+'t').text = part
            restore_source_run_styles(p,layout,page_width,char_style)
            marked = [r for r in p.findall(HP+'run') if allocated.get(r.get('charPrIDRef'),())[2:4] == (-15,80)]
            passed = text(p) == value
            passed &= len(marked) == len(positions) if shape in ('one_run','per_character_empty_runs') else not marked
            record(f'actual_q{number}_{shape}_space_style_scope',passed)

    cases = (
        'nonliteral','missing_source','wrong_page','wrong_source_width','wrong_column_rail',
        'source_font','source_size','source_char_origin','source_span_bbox','source_missing_row',
        'source_reversed_rows','source_row_text','source_blank','source_inline_label','source_table',
        'source_proof_fractional_flags','source_typography_fractional_flags_q23','source_both_fractional_flags_q23',
        'native_text_change','native_nbsp','native_tab','native_surrogate','native_combining',
        'native_equation','native_picture','native_nested_text','native_run_control','native_unknown_paragraph_child',
        'native_font','native_height','native_bold','native_italic','native_underline','native_superscript',
        'native_ratio','native_spacing','native_relsz','native_offset','native_missing_metric_langs',
        'native_outline','native_shadow','native_strikeout','native_emboss','native_engrave','native_kerning','native_fontspace','native_symbol_mark',
        'native_align','native_left','native_indent','native_right','native_container_width','native_draw_width',
        'native_rectangle_width','native_table_container','cache_missing','cache_duplicate_container','cache_missing_row','cache_start_nonzero',
        'cache_wrap_offset','cache_duplicate_offset','cache_negative_offset','cache_baseline_one',
        'cache_vertpos_forged','cache_spacing_forged','cache_height_forged','cache_width_forged',
    )
    if args.late_guards_only:
        cases = tuple(name for name in cases if name in ('source_proof_fractional_flags',
            'source_typography_fractional_flags_q23','source_both_fractional_flags_q23','native_emboss','native_engrave'))
    for name in cases:
        root,h,l,p,width = fixture(23 if name.endswith('_q23') else 19)
        ps,cs = style_maps(h)
        c = cs[p.find(HP+'run').get('charPrIDRef')]
        para = ps[p.get('paraPrIDRef')]
        margin = para.find('.//'+HH+'margin')
        seg = p.find(HP+'linesegarray')
        row = l['source_typography']['lines'][0]
        span = row['spans'][0]
        if name == 'nonliteral': l['source_literal_text'] = False
        elif name == 'missing_source': l['source_pdf_path'] = str(args.report.parent/'missing.pdf')
        elif name == 'wrong_page': l['source_page_index'] = 0
        elif name == 'wrong_source_width': l['source_page_width_pt'] += 1
        elif name == 'wrong_column_rail': l['column_left_pt'] += 1
        elif name == 'source_font': span['font'] = 'Arial'
        elif name == 'source_size': span['size'] += 1
        elif name == 'source_char_origin':
            v = list(span['chars'][0]['origin']);v[0] += 1;span['chars'][0]['origin'] = v
        elif name == 'source_span_bbox':
            v = list(span['bbox']);v[2] += 1;span['bbox'] = v
        elif name == 'source_missing_row': l['source_typography']['lines'].pop(0)
        elif name == 'source_reversed_rows': l['source_typography']['lines'].reverse()
        elif name == 'source_row_text': row['text'] += ' changed'
        elif name == 'source_blank': l['source_answer_blanks'] = [{}]
        elif name == 'source_inline_label': l['source_inline_labels'] = [{}]
        elif name == 'source_table': l['native_tables'] = [{}]
        elif name in ('source_proof_fractional_flags','source_typography_fractional_flags_q23','source_both_fractional_flags_q23'):
            if name != 'source_typography_fractional_flags_q23':
                for line in l['source_question_body']['lines'][1:]:
                    for changed_span in line['spans']:changed_span['flags'] += .25
            if name != 'source_proof_fractional_flags':
                for line in l['source_typography']['lines']:
                    for changed_span in line['spans']:changed_span['flags'] += .25
        elif name in ('native_text_change','native_nbsp','native_tab','native_surrogate','native_combining'):
            t = p.find(HP+'run/'+HP+'t')
            t.text = ('X'+t.text[1:] if name == 'native_text_change' else t.text+'\U0001f600' if name == 'native_surrogate'
                      else t.text+'\u0301' if name == 'native_combining' else t.text+'\u00a0' if name == 'native_nbsp' else t.text+'\t')
        elif name in ('native_equation','native_picture','native_run_control'):
            etree.SubElement(p.find(HP+'run'),HP+{'native_equation':'equation','native_picture':'pic','native_run_control':'ctrl'}[name])
        elif name == 'native_nested_text': etree.SubElement(p.find(HP+'run/'+HP+'t'),HP+'lineBreak')
        elif name == 'native_unknown_paragraph_child': etree.SubElement(p,HP+'ctrl')
        elif name == 'native_font':
            ref = c.find(HH+'fontRef').get('latin')
            next(f for face in h.iter(HH+'fontface') if face.get('lang') == 'LATIN' for f in face if f.get('id') == ref).set('face','Arial')
        elif name == 'native_height': c.set('height',str(int(c.get('height'))+10))
        elif name in ('native_bold','native_italic','native_superscript','native_strikeout','native_emboss','native_engrave'):
            etree.SubElement(c,HH+name.removeprefix('native_'),**({'shape':'SOLID'} if name == 'native_strikeout' else {}))
        elif name == 'native_underline': c.find(HH+'underline').set('type','BOTTOM')
        elif name in ('native_ratio','native_spacing','native_relsz','native_offset'):
            node = c.find(HH+('relSz' if name == 'native_relsz' else name.removeprefix('native_')))
            for key,value in node.attrib.items():node.set(key,str(int(value)+1))
        elif name == 'native_missing_metric_langs':
            for tag in ('ratio','spacing','relSz','offset'):
                node = c.find(HH+tag)
                for key in list(node.attrib):
                    if key != 'latin':del node.attrib[key]
        elif name == 'native_outline': c.find(HH+'outline').set('type','SOLID')
        elif name == 'native_shadow': c.find(HH+'shadow').set('type','DISCRETE')
        elif name in ('native_kerning','native_fontspace'): c.set('useKerning' if name == 'native_kerning' else 'useFontSpace','1')
        elif name == 'native_symbol_mark': c.set('symMark','DOT_ABOVE')
        elif name == 'native_align': para.find(HH+'align').set('horizontal','LEFT')
        elif name in ('native_left','native_indent','native_right'):
            node = margin.find(HC+{'native_left':'left','native_indent':'intent','native_right':'right'}[name]);node.set('value',str(int(node.get('value'))+20))
        elif name == 'native_container_width': p.getparent().set('textWidth',str(width+20))
        elif name == 'native_draw_width': p.getparent().getparent().set('lastWidth',str(width+20))
        elif name == 'native_rectangle_width': p.getparent().getparent().getparent().find(HP+'sz').set('width',str(width+20))
        elif name == 'native_table_container':
            tc = etree.SubElement(root,HP+'tc');tc.append(p.getparent().getparent().getparent())
        elif name == 'cache_missing': p.remove(seg)
        elif name == 'cache_duplicate_container': p.append(deepcopy(seg))
        elif name == 'cache_missing_row': seg.remove(seg[-1])
        elif name == 'cache_start_nonzero': seg[0].set('textpos','1')
        elif name == 'cache_wrap_offset': seg[1].set('textpos',str(int(seg[1].get('textpos'))+1))
        elif name == 'cache_duplicate_offset': seg[1].set('textpos',seg[0].get('textpos'))
        elif name == 'cache_negative_offset': seg[0].set('textpos','-1')
        elif name == 'cache_baseline_one': seg[0].set('baseline','1')
        elif name == 'cache_vertpos_forged': seg[0].set('vertpos','9999')
        elif name == 'cache_spacing_forged': seg[0].set('spacing','9999')
        elif name == 'cache_height_forged':
            seg[0].set('vertsize','9999');seg[0].set('textheight','9999');seg[0].set('baseline','8888')
        elif name == 'cache_width_forged': seg[0].set('horzsize',str(int(seg[0].get('horzsize'))+20))
        before = etree.tostring(root),etree.tostring(h)
        count = restore_source_question_body_right([(p,l)],h,page_width,width)
        atomic = before == (etree.tostring(root),etree.tostring(h))
        record(name,count == 0 and atomic,accepted=count != 0,transactional=atomic)

    after_code = hashes()
    record('reviewed_code_snapshot_stable',before_code == after_code)
    report = {'ok':not failures,'source':str(args.source),'input':str(args.hwpx),
              'source_sha256':hashlib.sha256(args.source.read_bytes()).hexdigest(),
              'input_sha256':hashlib.sha256(args.hwpx.read_bytes()).hexdigest(),
              'before_code':before_code,'after_code':after_code,'checks':checks,'failures':failures,
              'scope':'actual source spaces/native right-margin guard and transactional mutation review; no full-page paint verdict',
              'allocator_scope':'memoizing test allocator only; no raw producer style-ID idempotence claim'}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'ok':report['ok'],'checks':len(checks),'failures':failures,'report':str(args.report)},ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
