"""Source number glyphs distinguish figure lists from question markers."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.recognition.pdf_segment import _filter_figure_embedded_markers
from app.recognition.schema import Box
from app.recognition.pipeline import recognize_pdf


def marker(number, x, y, glyph_height, line_height=None):
    return {'number':number, 'punct':'.', 'text':f'{number}. Source text*',
            'box':Box(x,y,100,line_height or glyph_height),
            'line':{'pdf_line_spans':[{'text':f'{number}.','bbox':[x,y,x+12,y+glyph_height]}]}}


def main():
    first = marker(1,40,100,13)
    actual = marker(2,40,300,13,20)  # Raised mathematical glyph in real prose.
    embedded = marker(1,60,180,11,20)  # Smaller number plus raised footnote.
    region = Box(50,160,160,100)
    kept, count = _filter_figure_embedded_markers([first,embedded,actual],[region],width_px=595,height_px=842)
    assert kept == [first,actual] and count == 1
    # Equal-sized real question numbers enclosed by a frame remain questions.
    equal = marker(3,60,180,13,20)
    kept, count = _filter_figure_embedded_markers([first,equal,actual],[region],width_px=595,height_px=842)
    assert kept == [first,equal,actual] and count == 0
    # A small number with no containing source figure cannot be suppressed.
    kept, count = _filter_figure_embedded_markers([first,embedded,actual],[],width_px=595,height_px=842)
    assert kept == [first,embedded,actual] and count == 0
    # No outside reference is insufficient proof, even inside a frame.
    kept, count = _filter_figure_embedded_markers([embedded],[region],width_px=595,height_px=842)
    assert kept == [embedded] and count == 0
    missing_geometry = dict(embedded, line={})
    kept, count = _filter_figure_embedded_markers([first,missing_geometry,actual],[region],width_px=595,height_px=842)
    assert kept == [first,missing_geometry,actual] and count == 0
    inventory = json.loads((ROOT/'tmp/september-exam-matrix/stable-all-51-20261007-final/source_inventory.json').read_text(encoding='utf8'))
    case = next(c for c in inventory['cases'] if c['id'] == '2027_kice_september_high3__J_sangup')
    source = Path(case['source'])
    payload = source.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == case['sha256']
    expected = Counter((page['physical_page'],m['number'])
                       for page in case['pages'] for m in page['question_markers'])
    result = recognize_pdf(payload,filename='neutral.pdf')
    assert Counter((p.page_number,p.number) for p in result.problems) == expected
    assert len(result.problems) == 20 and result.page_count == 4
    # Inspect the actual input: the raised footnote enlarges the line bbox,
    # whereas its numbered-list glyph is smaller than each real question.
    with fitz.open(stream=payload,filetype='pdf') as pdf:
        candidate = next(line for block in pdf[0].get_text('dict')['blocks'] for line in block.get('lines',[])
                         if ''.join(s['text'] for s in line['spans']).startswith('2. 적용금리'))
        real = next(line for block in pdf[0].get_text('dict')['blocks'] for line in block.get('lines',[])
                    if ''.join(s['text'] for s in line['spans']).startswith('4. 다음 상품'))
        assert candidate['bbox'][3]-candidate['bbox'][1] > real['bbox'][3]-real['bbox'][1]
        assert candidate['spans'][0]['bbox'][3]-candidate['spans'][0]['bbox'][1] < .92*(
            real['spans'][0]['bbox'][3]-real['spans'][0]['bbox'][1])
    print('RECOGNITION_MARKER_GLYPHS_OK: actual source20/20, raised footnote list, framed real numbers and missing-proof negatives')


if __name__ == '__main__':
    main()
