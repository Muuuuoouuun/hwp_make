"""Actual PDF horizontal scale and tracking, with forged-source negatives."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tmp/september-exam-matrix/source-span-metrics'
OUT.mkdir(parents=True, exist_ok=True)
os.environ['HWP_MAKE_DATA_DIR'] = str(OUT / 'data')
sys.path.insert(0, str(ROOT))

import fitz
from lxml import etree
from app.pdf_layout_writer import _iter_text_lines, _item_bbox
from app.pdf_native_content import _source_typography
from app.pdf_source_image_validation import render_source_crop
from app.pdf_source_run_styles import HP, restore_source_run_styles
from app.pdf_source_span_metrics import wrapped_source_span_ratios, wrapped_source_synthetic_spaces
from verify_native_wrapped_prose_frame import source_oracle


def main():
    source = ROOT / 'data/external_exam_qa/2026_september_high2/english.pdf'
    if not source.is_file():
        print('SKIP: actual source PDF missing'); return 2
    truth = source_oracle(source, 3, 27)
    frame = fitz.Rect(truth['frame'])
    image = fitz.Rect(truth['image_bbox'])
    with fitz.open(source) as pdf:
        lines = sorted([line for line in _iter_text_lines(pdf[3]) if frame.contains(_item_bbox(line))],
                       key=lambda line: (_item_bbox(line).y0, _item_bbox(line).x0))
        typography = _source_typography(lines, {'rect': frame})
    crop = OUT / 'data/uploads/tree.png'
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(render_source_crop(source, 3, image))
    layout = {'source_literal_text': True, 'source_page_width_pt': truth['page_width'],
              'column_left_pt': frame.x0, 'column_right_pt': frame.x1,
              'source_typography': typography, 'native_tables': [{
                  'source_prose_frame': True, 'bbox_pt': list(frame),
                  'source_pdf_path': str(source), 'source_page_index': 3,
                  'source_frame_text': truth['text'],
                  'images': [{'bbox_pt': list(image), 'path': 'uploads/tree.png'}]}]}
    ratios = wrapped_source_span_ratios(layout)
    assert ratios[0, 0] == 97 and ratios[1, 0] == 98, ratios
    spaces = wrapped_source_synthetic_spaces(layout)
    assert len(spaces) == 6 and set(spaces.values()) == {(80, -19)}, spaces
    styles, keys = {}, {}
    def style(base, height, font, spacing, ratio, bold, *, italic):
        key = (height, font, spacing, ratio, bold, italic)
        if key not in keys:
            identifier = str(len(styles)+1); keys[key] = identifier; styles[identifier] = key
        return keys[key]
    text = ''.join(span['text'] for record in typography['lines'] for span in record['spans'])
    p = etree.Element(HP+'p')
    etree.SubElement(etree.SubElement(p, HP+'run', charPrIDRef='0'), HP+'t').text = text
    assert restore_source_run_styles(p, layout, 59528, style) > 0
    assert ''.join(p.itertext()) == text
    runs = [(run.findtext(HP+'t'), styles[run.get('charPrIDRef')]) for run in p.findall(HP+'run')]
    assert runs[0][0].strip() == truth['title']['text'].strip()
    assert runs[0][1][2:4] == (-1, 97), runs[0]
    assert next(value for text, value in runs if 'Join us' in text)[2:4] == (-2, 98)
    assert next(value for text, value in runs if 'Online registration' in text)[2:4] == (-5, 98)
    assert next(value for text, value in runs if 'Bring a hat' in text)[2:4] == (-3, 98)
    assert next(value for text, value in runs if text == '-')[2:4] == (0, 97)
    assert next(value for text, value in runs if '11 a.m.' in text)[2:4] == (-2, 98)
    assert next(value for text, value in runs if text.strip() == 'Free')[2:4] == (-2, 98)
    assert len([1 for text, value in runs if text == ' ' and value[2:4] == (-19, 80)]) == 6
    snapshot = etree.tostring(p)
    restore_source_run_styles(p, layout, 59528, style)
    assert etree.tostring(p) == snapshot
    negative = []
    for reason in ('nonliteral', 'missing_pdf', 'missing_image', 'wrong_page', 'partial_frame',
                   'missing_line', 'extra_image', 'answer_blank', 'fake_font', 'fake_flags',
                   'fake_span_size', 'nan_span_size', 'fake_char_origin', 'nan_char_origin',
                   'fake_char_bbox', 'nan_char_bbox', 'missing_chars', 'fake_span_text',
                   'fake_page_width', 'nan_page_width'):
        changed = deepcopy(layout)
        geometry = changed['native_tables'][0]
        span = changed['source_typography']['lines'][0]['spans'][0]
        if reason == 'nonliteral': changed['source_literal_text'] = False
        elif reason == 'missing_pdf': geometry['source_pdf_path'] = str(OUT/'missing.pdf')
        elif reason == 'missing_image': geometry['images'][0]['path'] = 'uploads/missing.png'
        elif reason == 'wrong_page': geometry['source_page_index'] = 2
        elif reason == 'partial_frame': geometry['bbox_pt'][3] -= 20
        elif reason == 'missing_line': changed['source_typography']['lines'].pop()
        elif reason == 'extra_image': geometry['images'].append(deepcopy(geometry['images'][0]))
        elif reason == 'answer_blank': changed['source_answer_blanks'] = [{'text': 'fake'}]
        elif reason == 'fake_font': span['font'] = 'UnknownSourceFont'
        elif reason == 'fake_flags': span['flags'] ^= 16
        elif reason == 'fake_span_size': span['size'] += .5
        elif reason == 'nan_span_size': span['size'] = float('nan')
        elif reason in ('fake_char_origin', 'nan_char_origin'):
            origin = list(span['chars'][0]['origin']); origin[0] = float('nan') if reason.startswith('nan') else origin[0]+.5
            span['chars'][0]['origin'] = origin
        elif reason in ('fake_char_bbox', 'nan_char_bbox'):
            box = list(span['chars'][0]['bbox']); box[0] = float('nan') if reason.startswith('nan') else box[0]+.5
            span['chars'][0]['bbox'] = box
        elif reason == 'missing_chars': span['chars'].pop()
        elif reason == 'fake_span_text': span['text'] = 'forged text'
        elif reason == 'fake_page_width': changed['source_page_width_pt'] += 1
        elif reason == 'nan_page_width': changed['source_page_width_pt'] = float('nan')
        assert wrapped_source_span_ratios(changed) == {}, reason
        assert wrapped_source_synthetic_spaces(changed) == {}, reason
        negative.append(reason)
    mismatch = deepcopy(p); mismatch.find('.//'+HP+'t').text = 'changed original prose'
    before = etree.tostring(mismatch); count = len(styles)
    assert restore_source_run_styles(mismatch, layout, 59528, style) == 0
    assert etree.tostring(mismatch) == before and len(styles) == count
    result = {'ok': True, 'source_rows': len(typography['lines']),
              'proved_spans': len(ratios), 'title_ratio': ratios[0, 0],
              'title_tracking': runs[0][1][2], 'negative_cases': negative,
              'actual_synthetic_spaces': len(spaces),
              'synthetic_space_ratio_tracking': [80, -19],
              'short_punctuation_transform': [97, 0],
              'short_numeric_tracking': -2,
              'whole_native_text_preserved': True, 'repeated_application_stable': True,
              'idempotence_scope': 'memoizing test allocator only; no raw producer-ID claim'}
    (OUT/'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print('SOURCE_SPAN_METRICS_OK', json.dumps(result, ensure_ascii=False)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
