"""Actual PDF choice spaces, source-forgery guards and editable run styles."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from lxml import etree
from app.pdf_layout_writer import _iter_text_lines, _line_text, _pdf_output_text
from app.pdf_native_content import _source_typography
from app.pdf_source_choice_spaces import source_choice_space_styles
from app.pdf_source_run_styles import HP, restore_source_run_styles


def main():
    source = ROOT/'data/external_exam_qa/2027_kice_september_high3/english.pdf'
    if not source.is_file():
        print('SKIP: actual source PDF missing'); return 2
    with fitz.open(source) as pdf:
        page = pdf[1]
        line = next(line for line in _iter_text_lines(page)
                    if _line_text(line).startswith('①Absolutely!'))
        typography = _source_typography([line], {'column_left_pt': 87.9, 'column_right_pt': 409.8})
        width = page.rect.width
    layout = {'source_literal_text': True, 'source_pdf_path': str(source),
              'source_page_index': 1, 'source_page_width_pt': width,
              'source_typography': typography}
    spaces = source_choice_space_styles(layout)
    assert len(spaces) == 8 and set(spaces.values()) == {(80, -15)}, spaces
    text = _pdf_output_text(_line_text(line)).strip()
    styles, ids = {}, {}
    def style(base, height, font, tracking, ratio, bold, *, italic):
        key = (height, font, tracking, ratio, bold, italic)
        if key not in ids:
            ident = str(len(styles)+1); ids[key] = ident; styles[ident] = key
        return ids[key]
    def paragraph(value):
        p = etree.Element(HP+'p')
        etree.SubElement(etree.SubElement(p, HP+'run', charPrIDRef='0'), HP+'t').text = value
        return p
    p = paragraph(text)
    assert restore_source_run_styles(p, layout, 59528, style) > 0
    assert ''.join(p.itertext()) == text
    space_runs = [r for r in p.findall(HP+'run') if r.findtext(HP+'t') == ' ']
    assert len(space_runs) == 8
    assert all(styles[r.get('charPrIDRef')][1:4] == ('Times New Roman', -15, 80) for r in space_runs)
    before = etree.tostring(p)
    restore_source_run_styles(p, layout, 59528, style)
    assert etree.tostring(p) == before
    negatives = []
    for reason in ('nonliteral', 'table', 'answer_blank', 'inline_label', 'multirow', 'center',
                   'missing_pdf', 'wrong_page', 'fractional_page', 'negative_page', 'nan_page',
                   'wrong_width', 'nan_width', 'wrong_row_bbox', 'nan_row_bbox', 'wrong_font',
                   'wrong_flags', 'wrong_size', 'nan_size', 'wrong_span_text', 'missing_char',
                   'wrong_char', 'wrong_origin', 'nan_origin', 'wrong_char_bbox', 'nan_char_bbox',
                   'extra_span'):
        q = deepcopy(layout); rec = q['source_typography']['lines'][0]; sp = rec['spans'][-1]
        if reason == 'nonliteral': q['source_literal_text'] = False
        elif reason == 'table': q['native_tables'] = [{}]
        elif reason == 'answer_blank': q['source_answer_blanks'] = [{}]
        elif reason == 'inline_label': q['source_inline_labels'] = [{}]
        elif reason == 'multirow': q['source_typography']['lines'].append(deepcopy(rec))
        elif reason == 'center': q['source_typography']['alignment'] = 'CENTER'
        elif reason == 'missing_pdf': q['source_pdf_path'] = str(source.parent/'missing.pdf')
        elif reason == 'wrong_page': q['source_page_index'] = 0
        elif reason == 'fractional_page': q['source_page_index'] = 1.5
        elif reason == 'negative_page': q['source_page_index'] = -1
        elif reason == 'nan_page': q['source_page_index'] = float('nan')
        elif reason == 'wrong_width': q['source_page_width_pt'] += 1
        elif reason == 'nan_width': q['source_page_width_pt'] = float('nan')
        elif reason in ('wrong_row_bbox', 'nan_row_bbox'):
            rec['bbox_pt'][0] = float('nan') if reason.startswith('nan') else rec['bbox_pt'][0]+1
        elif reason == 'wrong_font': sp['font'] = 'Arial'
        elif reason == 'wrong_flags': sp['flags'] ^= 16
        elif reason == 'wrong_size': sp['size'] += 1
        elif reason == 'nan_size': sp['size'] = float('nan')
        elif reason == 'wrong_span_text': sp['text'] = 'forged original words'
        elif reason == 'missing_char': sp['chars'].pop()
        elif reason == 'wrong_char': sp['chars'][0]['c'] = 'X'
        elif reason in ('wrong_origin', 'nan_origin'):
            v = list(sp['chars'][0]['origin']); v[0] = float('nan') if reason.startswith('nan') else v[0]+1
            sp['chars'][0]['origin'] = v
        elif reason in ('wrong_char_bbox', 'nan_char_bbox'):
            v = list(sp['chars'][0]['bbox']); v[0] = float('nan') if reason.startswith('nan') else v[0]+1
            sp['chars'][0]['bbox'] = v
        elif reason == 'extra_span': rec['spans'].append(deepcopy(sp))
        assert source_choice_space_styles(q) == {}, reason
        negatives.append(reason)
    for reason in ('changed_native_words', 'native_equation', 'native_tabs'):
        changed = paragraph(text.replace('tickets', 'books') if reason == 'changed_native_words'
                            else text.replace(' ', '\t') if reason == 'native_tabs' else text)
        if reason == 'native_equation': etree.SubElement(changed[0], HP+'equation')
        before = etree.tostring(changed); count = len(styles)
        result = restore_source_run_styles(changed, layout, 59528, style)
        if reason == 'native_tabs':
            assert ''.join(changed.itertext()) == text.replace(' ', '\t')
            assert not any(styles[r.get('charPrIDRef')][2:4] == (-15, 80) for r in changed.findall(HP+'run'))
        else:
            assert result == 0 and before == etree.tostring(changed) and len(styles) == count, reason
        negatives.append(reason)
    report = {'ok': True, 'actual_source_spaces': len(spaces), 'space_ratio_tracking': [80, -15],
              'text_preserved': True, 'idempotent': True,
              'idempotence_scope': 'memoizing test allocator only; no raw producer-ID claim',
              'negative_cases': negatives}
    out = ROOT/'tmp/september-exam-matrix/source-choice-spaces'; out.mkdir(parents=True, exist_ok=True)
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print('SOURCE_CHOICE_SPACES_OK', json.dumps(report, ensure_ascii=False)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
