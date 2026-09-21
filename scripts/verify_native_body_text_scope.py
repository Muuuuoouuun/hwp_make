"""PDF body evidence cannot be supplied or interrupted by running controls."""
# ruff: noqa: E402
from copy import deepcopy
import base64
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = tempfile.TemporaryDirectory(prefix='native_body_scope_')
if __name__ == '__main__':
    os.environ['HWP_MAKE_DATA_DIR'] = runtime.name

import fitz
from lxml import etree
from app.pdf_editability import _compact_text, _package_text, inspect_pdf_editability
from app.pdf_layout_writer import write_pdf_structured_hwpx, _structured_hwpx_plain_text
from app.pdf_native_text import body_elements, body_text

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
SENTENCE = ('Observation records must stay in the document body. '
            'Moving them into a repeating page header cannot preserve the question.')


def running_control(kind, text, paragraph):
    run = etree.Element(HP + 'run', charPrIDRef=paragraph.find(HP + 'run').get('charPrIDRef'))
    ctrl = etree.SubElement(run, HP + 'ctrl')
    heading = etree.SubElement(ctrl, HP + kind, id='1987654321', applyPageType='BOTH')
    sub = etree.SubElement(heading, HP + 'subList', id='', textDirection='HORIZONTAL',
                          lineWrap='BREAK', vertAlign='TOP', linkListIDRef='0',
                          linkListNextIDRef='0', textWidth='20000', textHeight='5000',
                          hasTextRef='0', hasNumRef='0')
    copy = deepcopy(paragraph)
    copy.set('id', '1987654322')
    for child in list(copy):
        copy.remove(child)
    etree.SubElement(etree.SubElement(copy, HP + 'run', charPrIDRef=run.get('charPrIDRef')), HP + 't').text = text
    sub.append(copy)
    return run


def rewrite(source, output, change):
    with zipfile.ZipFile(source) as archive:
        payloads = [(deepcopy(info), archive.read(info.filename)) for info in archive.infolist()]
    changed = False
    with zipfile.ZipFile(output, 'w') as archive:
        for info, data in payloads:
            if re.fullmatch(r'Contents/section\d+\.xml', info.filename):
                root = etree.fromstring(data)
                changed |= change(root)
                data = etree.tostring(root, encoding='utf-8', xml_declaration=True)
            archive.writestr(info, data)
    assert changed


def target(root):
    return next((p for p in body_elements(root) if p.tag == HP + 'p'
                 and 'Observation records' in ''.join(t.text or '' for t in p.findall(HP + 'run/' + HP + 't'))), None)


def verify(folder, *, check_api=False):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    source, native = folder / 'source.pdf', folder / 'body.hwpx'
    with fitz.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        page.insert_text((45, 145), '1. Read the observation.', fontsize=9)
        for y, line in zip((173, 186, 199), (
            'Observation records must stay in the document body.',
            'Moving them into a repeating page header cannot',
            'preserve the question.',
        )):
            page.insert_text((45, y), line, fontsize=9)
        pdf.save(source)
    stats = write_pdf_structured_hwpx(source, native, native_math=True)
    original = inspect_pdf_editability(source, native, stats['image_provenance'])
    assert original['ok'] and original['native_source_text_coverage'] == 1, original
    plain = _structured_hwpx_plain_text(native)
    assert _compact_text(SENTENCE) in plain
    results = {}
    for kind in ('header', 'footer'):
        interleaved = folder / f'interleaved_{kind}.hwpx'

        def insert(root):
            paragraph = target(root)
            if paragraph is None: return False
            run = paragraph.find(HP + 'run')
            text = run.find(HP + 't')
            assert text is not None and len(text.text or '') > 30
            remainder = deepcopy(run)
            remainder.find(HP + 't').text = text.text[21:]
            text.text = text.text[:21]
            index = paragraph.index(run)
            paragraph.insert(index + 1, running_control(kind, 'Repeated page furniture only', paragraph))
            paragraph.insert(index + 2, remainder)
            return True

        rewrite(native, interleaved, insert)
        positive = inspect_pdf_editability(source, interleaved, stats['image_provenance'])
        assert positive['native_source_text_coverage'] == 1, positive
        assert not positive['question_units']['missing_question_content'], positive
        assert _structured_hwpx_plain_text(interleaved) == plain

        relocated = folder / f'body_moved_to_{kind}.hwpx'

        def relocate(root):
            paragraph = target(root)
            if paragraph is None: return False
            text = ''.join(t.text or '' for t in paragraph.findall(HP + 'run/' + HP + 't'))
            control = running_control(kind, text, paragraph)
            for run in paragraph.findall(HP + 'run'):
                paragraph.remove(run)
            paragraph.insert(0, control)
            # The original body text remains somewhere in the package, so a
            # package-wide text concatenation would accept this broken file.
            assert _compact_text(text) in _compact_text(''.join(root.itertext()))
            return True

        rewrite(native, relocated, relocate)
        negative = inspect_pdf_editability(source, relocated, stats['image_provenance'])
        assert not negative['ok'] and 'native_source_text_missing' in negative['issues'], negative
        assert negative['question_units']['missing_question_content'], negative
        assert _compact_text(SENTENCE) not in _structured_hwpx_plain_text(relocated)
        results[kind] = {
            'interleaved_body_coverage': positive['native_source_text_coverage'],
            'relocated_body_rejected': True,
            'relocated_issues': negative['issues'],
        }

    # Mixed text tails and real equation scripts remain body evidence. A header
    # equation must not provide a missing body script even with equal text.
    root = etree.fromstring(f'''<p xmlns="{HP[1:-1]}"><run><t>First<tab/>part<lineBreak/>tail</t>
        <ctrl><header><subList><p><run><t>OUTSIDE</t><equation><script>x^9</script></equation></run></p></subList></header></ctrl>
        <equation><script>y_2</script></equation><t>last</t></run></p>''')
    assert body_text(root) == 'First\tpart\ntaily_2last'
    assert body_text(root, include_equations=False) == 'First\tpart\ntaillast'
    assert _package_text(root, omit_script_markers=True) == 'First\tpart\ntaily2last'
    assert not _package_text(root.find('.//' + HP + 'header'))
    report = {'ok': True, 'running_controls': results, 'mixed_content_and_equation_scope': True}
    if check_api:
        from fastapi.testclient import TestClient
        from app import main, pdf_layout_writer as writer

        body = {'filename': source.name, 'data_base64': base64.b64encode(source.read_bytes()).decode(),
                'math_ai_recognition': False}
        api_results = []
        with TestClient(main.app) as client:
            for kind in ('header', 'footer'):
                def forged_writer(_source, destination, **_kwargs):
                    Path(destination).write_bytes((folder / f'body_moved_to_{kind}.hwpx').read_bytes())
                    return {**stats, 'editable_text_coverage_ratio': 1.0, 'source_text_preservation_ratio': 1.0}

                with patch.object(writer, 'write_pdf_structured_hwpx', forged_writer):
                    for mode in ('structured', 'coordinate'):
                        response = client.post('/api/pdf-layout-export', json={**body, 'layout_mode': mode})
                        result = response.json()
                        assert response.status_code == 422, result
                        assert 'native_source_text_missing' in result['detail']['editability']['issues'], result
                        assert result['detail']['editability']['question_units']['missing_question_content']
                        assert 'export' not in result and 'download_url' not in result
                        api_results.append({'control': kind, 'mode': mode, 'status': response.status_code,
                                            'issues': result['detail']['editability']['issues']})
        assert not list((Path(runtime.name) / 'exports').rglob('*.hwpx'))
        report['api_rejections_despite_perfect_stats'] = api_results
    (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('NATIVE_BODY_TEXT_SCOPE_OK: header/footer interleaving preserves body text; relocated body rejected by both source gates')
    return report


if __name__ == '__main__':
    verify(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(runtime.name), check_api=True)
