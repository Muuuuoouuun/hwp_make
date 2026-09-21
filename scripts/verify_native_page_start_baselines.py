"""Compare every later-page math column start to actual PDF/SVG baselines."""
# ruff: noqa: E402
from pathlib import Path
import json
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz
from lxml import etree
import rhwp
from app.pdf_layout_writer import write_pdf_structured_hwpx
from app.pdf_question_rendering import IDENTITY, _multiply, _transform, _bounds

SVG = '{http://www.w3.org/2000/svg}'


def measure(source, native):
    rendered = rhwp.parse(str(native))
    rows = []
    with fitz.open(source) as pdf:
        assert rendered.page_count == len(pdf)
        for index in range(1, len(pdf)):
            page = pdf[index]
            svg = etree.fromstring(rendered.render_svg(index).encode())
            scale = float(svg.get('width')) / page.rect.width
            text_nodes = []
            for node in svg.iter(SVG + 'text'):
                matrix = IDENTITY
                for ancestor in [*reversed(list(node.iterancestors())), node]:
                    matrix = _multiply(matrix, _transform(ancestor.get('transform', '')))
                x, y, *_ = _bounds(matrix, float(node.get('x', '0')), float(node.get('y', '0')), 0, 0)
                text_nodes.append((''.join(node.itertext()), x, y))
            for column in (1, 2):
                starts = []
                for block in page.get_text('dict')['blocks']:
                    for line in block.get('lines', []):
                        text = ''.join(span['text'] for span in line['spans'])
                        match = re.match(r'^(\d+)\.', text)
                        if match and (1 if line['bbox'][0] < page.rect.width / 2 else 2) == column:
                            starts.append((line, match[1]))
                assert starts, (index + 1, column)
                line, number = min(starts, key=lambda pair: pair[0]['bbox'][1])
                expected = [value * scale for value in line['spans'][0]['origin']]
                candidates = []
                for i, (value, x, y) in enumerate(text_nodes):
                    if not value.startswith(number[0]) or abs(x - expected[0]) > 12 or abs(y - expected[1]) > 30:
                        continue
                    label = ''
                    for part, _, baseline in text_nodes[i:i + len(number) + 1]:
                        if abs(baseline - y) > .01:
                            break
                        label += part
                    if label.startswith(number + '.'):
                        candidates.append((x, y))
                # Identify the actual printed question marker, including its
                # period. Nearby equation digits are not equivalent evidence.
                assert len(candidates) == 1, (index + 1, column, number, candidates)
                x, y = candidates[0]
                rows.append({'page': index + 1, 'column': column, 'question': int(number),
                             'source_marker_origin_px': expected, 'actual_marker_origin_px': [x, y],
                             'baseline_error_px': y - expected[1], 'horizontal_error_px': x - expected[0]})
    return rows


def verify(folder, *, source=None, native=None):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    source = source or ROOT / 'data/external_exam_qa/2026_june_high1/math.pdf'
    if not source.is_file():
        print('SKIP: public math source fixture unavailable')
        raise SystemExit(2)
    if native is None:
        native = folder / 'math.hwpx'
        write_pdf_structured_hwpx(source, native, native_math=True)
    measurements = measure(source, native)
    maximum = max(abs(row['baseline_error_px']) for row in measurements)
    report = {'ok': maximum <= .1, 'scope': 'Vertical baselines of printed first question markers in both columns, pages 2–12; horizontal errors reported separately.',
              'threshold_px': .1, 'columns_checked': len(measurements), 'maximum_baseline_error_px': maximum,
              'measurements': measurements}
    (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    assert len(measurements) == 22 and report['ok'], report
    print(f'NATIVE_PAGE_START_BASELINES_OK: {len(measurements)} source markers, maximum vertical error {maximum:.6f}px <= 0.1px')
    return report


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='native_page_baselines_') as temporary:
        verify(Path(temporary))
