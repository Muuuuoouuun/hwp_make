"""Real-paper header parity, automatic numbering, source vectors, and edits."""
# ruff: noqa: E402
from copy import deepcopy
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = tempfile.TemporaryDirectory(prefix='native_running_furniture_')
if __name__ == '__main__':
    os.environ['HWP_MAKE_DATA_DIR'] = runtime.name
import fitz
from lxml import etree
import numpy as np
from PIL import Image
import rhwp
from app.hwpx_writer_v2 import HwpxDocument
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools.package_validator import validate_editor_open_safety
from app.pdf_layout_writer import write_pdf_structured_hwpx, _page_body_top
from app.pdf_running_headings import measure_running_heading, apply_running_heading
from app.pdf_running_heading_audit import inspect_running_header_fields
from app.pdf_editability import inspect_pdf_editability
from app.pdf_question_rendering import _visible_svg_text

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HH = '{http://www.hancom.co.kr/hwpml/2011/head}'
SVG = '{http://www.w3.org/2000/svg}'


def mutate(source, destination, change):
    with zipfile.ZipFile(source) as archive:
        payloads = {n: archive.read(n) for n in archive.namelist()}
    section = etree.fromstring(payloads['Contents/section1.xml'])
    header = etree.fromstring(payloads['Contents/header.xml'])
    change(section, header)
    payloads['Contents/section1.xml'] = etree.tostring(section)
    payloads['Contents/header.xml'] = etree.tostring(header)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in payloads.items():
            archive.writestr(name, data)


def body_contents(path):
    with zipfile.ZipFile(path) as archive:
        roots = [etree.fromstring(archive.read(n)) for n in sorted(archive.namelist())
                 if re.fullmatch(r'Contents/section\d+\.xml', n)]
        boxes = [etree.tostring(d, method='c14n') for root in roots for d in root.iter(HP+'drawText')]
        images = {n: archive.read(n) for n in archive.namelist() if n.startswith('BinData/')}
        equations = [e.findtext(HP+'script') for root in roots for e in root.iter(HP+'equation')]
    return boxes, images, equations


def verify(folder):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    source = ROOT/'data/external_exam_qa/2026_june_high1/math.pdf'
    if not source.is_file():
        print('SKIP: public math fixture unavailable'); raise SystemExit(2)
    before, output = folder/'subject_only.hwpx', folder/'math.hwpx'
    with patch('app.pdf_running_furniture.apply_running_furniture', return_value=None):
        stats = write_pdf_structured_hwpx(source, before, native_math=True)
    negative_baseline = inspect_running_header_fields(source, before)
    assert not negative_baseline['ok'], 'subject-only legacy header incorrectly passed'
    with fitz.open(source) as pdf:
        records = [measure_running_heading(p, _page_body_top(p), '수학영역') for p in list(pdf)[1:]]
        page_count = len(pdf)
    shutil.copyfile(before, output)
    restored = apply_running_heading(output, records, page_count)
    assert restored['page_numbers_restored'] and restored['grade_outlines'] == 2
    assert restored['horizontal_rule_restored']
    assert body_contents(before) == body_contents(output), 'header altered question text, pictures, or equations'
    actual = inspect_running_header_fields(source, output)
    assert actual['ok'], actual
    assert actual['painted_header_fields_checked'] == (page_count-1)*3
    assert inspect_pdf_editability(source, output, stats['image_provenance'], require_question_boxes=True)['ok']
    assert validate_editor_open_safety(output).ok
    old, new = rhwp.parse(str(before)), rhwp.parse(str(output))
    assert old.page_count == new.page_count == page_count
    cut = math.ceil(restored['body_top_hwp']/75)
    maximum_outline_error = 0
    maximum_rule_error = 0
    for index, record in enumerate(records, 1):
        a = np.asarray(Image.open(io.BytesIO(old.render_png(index))))[cut:]
        b = np.asarray(Image.open(io.BytesIO(new.render_png(index))))[cut:]
        assert np.array_equal(a, b), f'body pixels moved on page {index+1}'
        root = etree.fromstring(new.render_svg(index).encode())
        scale = float(root.get('width'))/record['page_width_pt']
        outline = record['furniture']['grade_outline']
        expected = np.array(outline['points_pt'])*scale
        matches = []
        for path in root.iter(SVG+'path'):
            data = path.get('d', '')
            if re.search('[^MLZ0-9., eE+-]', data):
                continue
            numbers = [float(x) for x in re.findall(r'[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?', data)]
            if len(numbers) != expected.size or path.get('stroke') != '#000000':
                continue
            points = np.array(numbers).reshape(-1, 2)
            matches.append(float(np.abs(points-expected).max()))
        assert matches and min(matches) < .5, f'source grade outline displaced on page {index+1}: {matches}'
        maximum_outline_error = max(maximum_outline_error, min(matches))
        rule = record['furniture']['horizontal_rule']
        lines = [n for n in root.iter(SVG+'line') if n.get('stroke') == '#000000'
                 and abs(float(n.get('x2'))-float(n.get('x1'))) > float(root.get('width'))*.6
                 and float(n.get('y1')) < cut]
        assert len(lines) == 1
        line = lines[0]
        error = max(abs(float(line.get(key))-rule[source_key]*scale)
                    for key, source_key in [('x1', 'left_pt'), ('x2', 'right_pt'), ('y1', 'y_pt'), ('y2', 'y_pt')])
        assert error < .5, error
        maximum_rule_error = max(maximum_rule_error, error)

    def headers(root):
        return root.findall(HP+'p/'+HP+'run/'+HP+'ctrl/'+HP+'header')

    def fixed_number(root, _):
        for heading in headers(root):
            if heading.get('applyPageType') != 'EVEN':
                continue
            number = heading.find('.//'+HP+'autoNum')
            ctrl = number.getparent(); run = ctrl.getparent(); run.remove(ctrl)
            etree.SubElement(run, HP+'t').text = '2'

    def hide_grade(root, head):
        chars = head.find('.//'+HH+'charProperties')
        for heading in headers(root):
            for p in heading.iter(HP+'p'):
                if ''.join(p.itertext()) != '고1':
                    continue
                for run in p.findall(HP+'run'):
                    original = next(c for c in chars if c.get('id') == run.get('charPrIDRef'))
                    style = deepcopy(original); style.set('id', str(max(int(c.get('id')) for c in chars)+1))
                    style.set('textColor', '#FFFFFF'); chars.append(style); run.set('charPrIDRef', style.get('id'))
        chars.set('itemCnt', str(len(chars)))

    def remove_odd(root, _):
        heading = next(h for h in headers(root) if h.get('applyPageType') == 'ODD')
        ctrl = heading.getparent(); ctrl.getparent().remove(ctrl)

    mutations = {}
    for name, change in [('literal_page_number', fixed_number), ('invisible_grade', hide_grade), ('missing_odd_header', remove_odd)]:
        path = folder/f'{name}.hwpx'; mutate(output, path, change)
        audit = inspect_running_header_fields(source, path)
        assert not audit['ok'], f'{name} incorrectly passed'
        mutations[name] = audit
    doc = HwpxDocument.open(output)
    section = doc.sections[1]
    even = next(h for h in headers(section.element) if h.get('applyPageType') == 'EVEN')
    paragraph = next(p for p in even.iter(HP+'p') if ''.join(p.itertext()) == '수학영역')
    count = len(list(paragraph.getparent()))
    HwpxOxmlParagraph(paragraph, section).text = '수학실험영역'
    assert len(list(paragraph.getparent())) == count and not paragraph.findall('.//'+HP+'lineBreak')
    edited, resaved = folder/'edited.hwpx', folder/'resaved.hwpx'
    doc.save_to_path(edited); HwpxDocument.open(edited).save_to_path(resaved)
    assert body_contents(output) == body_contents(edited) == body_contents(resaved)
    for path in (edited, resaved):
        assert validate_editor_open_safety(path).ok
        native = rhwp.parse(str(path)); assert native.page_count == page_count
        for index in (1, 2, 9, 10):
            visible, _, _ = _visible_svg_text(native.render_svg(index))
            assert ('수학실험영역' in visible) == ((index+1)%2 == 0)
        Image.open(io.BytesIO(native.render_png(1))).save(folder/(path.stem+'_page2.png'))
    report = {'source_header_audit': actual, 'legacy_header_rejected': negative_baseline,
              'body_pixel_identical_pages': page_count-1, 'native_equations': len(body_contents(output)[2]),
              'maximum_grade_outline_error_px': maximum_outline_error,
              'maximum_rule_error_px': maximum_rule_error, 'negative_mutations': mutations,
              'paragraph_edit_resave_ok': True, 'hancom_gui_verified': False}
    (folder/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print('NATIVE_RUNNING_FURNITURE_OK: automatic page fields, parity, native vectors, identical body pixels, mutation rejection, paragraph edit/re-save')
    return report


if __name__ == '__main__':
    verify(Path(runtime.name))
