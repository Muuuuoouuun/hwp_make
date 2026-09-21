"""Real mixed-math table paragraphs: measured wraps, whole-paragraph editing."""
from copy import copy, deepcopy
import json
from pathlib import Path
import re
import sys
import tempfile
import zipfile

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pdf_layout_writer import write_pdf_structured_hwpx
from app.pdf_native_content import extract_native_content
from app.pdf_table_paragraphs import restore_table_paragraphs
from app.pdf_source_line_cache import source_line_values
from app.pdf_inline_labels import inline_label_text, native_inline_labels
from app.pdf_inline_label_rendering import painted_label_frames, missing_label_frames
from app.pdf_native_typography import HP, HH
from app.pdf_question_geometry import inspect_question_geometry
from scripts.verify_native_shared_table_paragraphs import tokens, locate
from hwpx import HwpxDocument
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools.paragraph_spacing import paragraph_indentation, paragraph_spacing
import rhwp

ADDITION = (' 수식과 조건을 그대로 둔 채 이 문단 뒤에 검증 문장을 추가합니다.'
            ' 문장이 길어지면 풀이 표와 문항 글상자가 함께 늘어나야 합니다.'
            ' 인쇄된 줄마다 문단이 생기거나 다음 문장과 겹쳐서는 안 됩니다.'
            ' 편집한 내용은 저장하고 다시 열어도 남아 있어야 합니다. MIXED_CELL_EDIT_END')


def state(path):
    with zipfile.ZipFile(path) as z:
        header = etree.fromstring(z.read('Contents/header.xml'))
        roots = [etree.fromstring(z.read(n)) for n in z.namelist()
                 if re.fullmatch(r'Contents/section\d+\.xml', n)]
    draw = next(d for root in roots for d in root.iter(HP+'drawText')
                if d.get('name') == 'question:v1:q14')
    table = draw.find('.//'+HP+'tbl')
    paragraphs = table.findall(HP+'tr/'+HP+'tc/'+HP+'subList/'+HP+'p')
    scripts = [s.text for root in roots for s in root.iter(HP+'script')]
    styles = {p.get('id'): p for p in header.iter(HH+'paraPr')}
    return roots, header, draw, table, paragraphs, scripts, styles


def verify(folder, source=None, native=None):
    source = source or ROOT/'data/external_exam_qa/2026_june_high1/math.pdf'
    folder.mkdir(parents=True, exist_ok=True)
    if native is None:
        native = folder/'math.hwpx'
        write_pdf_structured_hwpx(source, native, native_math=True)
    roots, header, draw, table, paragraphs, scripts, styles = state(native)
    from scripts.verify_pdf_layout_hwpx import _verify_no_draw_text_equations
    assert not _verify_no_draw_text_equations(native), 'valid inline answer frames rejected as nested line boxes'
    with zipfile.ZipFile(native) as package:
        part = next(n for n in package.namelist() if re.fullmatch(r'Contents/section\d+\.xml', n)
                    and b'question:v1:q14' in package.read(n))
        for kind in ('renamed', 'prose_line', 'locked', 'missing_border', 'equation'):
            root = etree.fromstring(package.read(part))
            question = next(d for d in root.iter(HP+'drawText') if d.get('name') == 'question:v1:q14')
            label = question.find('.//'+HP+'drawText')
            shape = label.getparent()
            if kind == 'renamed':
                label.attrib.pop('name', None)
            elif kind == 'prose_line':
                label.find('.//'+HP+'t').text = 'This is a positioned prose line.'
            elif kind == 'locked':
                shape.set('lock', '1')
            elif kind == 'missing_border':
                shape.find(HP+'lineShape').set('style', 'NONE')
            else:
                label.find('.//'+HP+'run').append(deepcopy(question.find('.//'+HP+'equation')))
            target = folder/('nested_'+kind+'.hwpx')
            with zipfile.ZipFile(target, 'w') as writer:
                for info in package.infolist():
                    writer.writestr(copy(info), etree.tostring(root) if info.filename == part else package.read(info.filename))
            failures = _verify_no_draw_text_equations(target)
            assert bool(failures) == (kind != 'renamed'), ('nested structure gate', kind, failures)
    chars = {c.get('id'): c for c in header.iter(HH+'charPr')}
    next_font_height = float(chars[paragraphs[9].find(HP+'run').get('charPrIDRef')].get('height')) / 75
    items, _ = extract_native_content(source)
    layout = next(i['layout'] for i in items if i['layout'].get('question_number') == 14 and i.get('tables'))
    records = layout['source_typography']['lines']
    assert len(paragraphs) == 13, 'semantic paragraphs changed into printed-line paragraphs'
    assert len(records) == 20 and sum(len(p.findall(HP+'linesegarray/'+HP+'lineseg')) for p in paragraphs) == 20
    assert not table.findall('.//'+HP+'lineBreak'), 'ordinary prose must wrap without forced line breaks'
    assert ''.join(source_line_values(records, mixed=True)) == re.sub(r'\s+', '', ''.join(
        c.findtext(HP+'script', '') if c.tag == HP+'equation'
        else inline_label_text(c) if c.tag == HP+'rect' else c.text or ''
        for p in paragraphs for r in p.findall(HP+'run') for c in r)), 'text/equation sequence differs'
    outer = table.getparent().getparent()
    page_width = float(roots[0].find('.//'+HP+'pagePr').get('width'))
    for kind in ('operator', 'missing_line', 'overflow', 'split_formula'):
        bad = deepcopy(layout)
        lines = bad['source_typography']['lines']
        if kind == 'operator':
            span = next(s for l in lines for s in l['spans'] if 'x^{2}' in s['text'])
            span['text'] = span['text'].replace('x^{2}', 'x^{3}', 1)
        elif kind == 'missing_line':
            lines.pop()
        elif kind == 'overflow':
            lines[1]['bbox_pt'][2] += 500
        else:
            lines[1]['spans'], lines[2]['spans'] = lines[1]['spans'][:1], lines[1]['spans'][1:]+lines[2]['spans']
        before = etree.tostring(outer), etree.tostring(header)
        def rejected_style(*args):
            raise AssertionError('invalid source allocated a style before full reconciliation')
        assert restore_table_paragraphs(outer, bad, header, page_width, rejected_style) == 0, kind
        assert before == (etree.tostring(outer), etree.tostring(header)), kind

    # Add a real paragraph run, retaining the native equations at their anchors.
    chosen = paragraphs[7]
    old_style = paragraph_indentation(chosen, styles), paragraph_spacing(chosen, styles)
    old_height = int(table.find(HP+'sz').get('height'))
    doc = HwpxDocument.open(native)
    section, element = next((s, p) for s in doc.sections for p in s.element.iter(HP+'p')
                            if p.get('id') == chosen.get('id'))
    public = HwpxOxmlParagraph(element, section)
    public.add_run(ADDITION)
    edited = folder/'mixed_cell_edited.hwpx'
    doc.save(edited)
    _, _, ed, et, ep, es, estyles = state(edited)
    assert es == scripts and len(ep) == len(paragraphs)
    assert not et.findall('.//'+HP+'lineBreak')
    assert int(et.find(HP+'sz').get('height')) > old_height
    assert (paragraph_indentation(ep[7], estyles), paragraph_spacing(ep[7], estyles)) == old_style
    assert inspect_question_geometry(ed)['ok']
    assert rhwp.parse(str(edited)).page_count == rhwp.parse(str(native)).page_count == 12
    # New content must actually be painted; XML membership alone is insufficient.
    locate(tokens(edited), ADDITION)
    second = folder/'mixed_cell_resaved.hwpx'
    HwpxDocument.open(edited).save(second)
    _, _, _, table2, ps2, scripts2, _ = state(second)
    assert scripts2 == scripts and etree.tostring(ps2[7]) == etree.tostring(ep[7])
    assert table2.find(HP+'sz').get('height') == et.find(HP+'sz').get('height')
    locate(tokens(second), ADDITION)
    # Real PDF labels must survive reflow and a second save as visible native
    # frames, including the line that consists only of equations and a frame.
    for path in (native, edited, second):
        required = native_inline_labels(state(path)[0])
        assert len(required) == 8, 'an inline answer frame was lost'
        rendered = rhwp.parse(str(path))
        painted = [frame for i in range(rendered.page_count)
                   for frame in painted_label_frames(rendered.render_svg(i), {'(가)', '(나)', '(다)'})]
        assert len(painted) == 8 and not missing_label_frames(required, painted), 'a frame was omitted or duplicated'
        next_line = locate(tokens(path), '(ⅱ) 방정식')
        earlier = next(frame for frame in painted if frame['text'] == '(나)')
        # A tall inline textbox must leave room above the following prose.
        assert earlier['bbox_px'][3] <= next_line[0][2] - next_font_height, 'the following paragraph overlaps the inline frame'
    result = {'ok': True, 'question': 14, 'source_printed_lines': 20, 'native_paragraphs': 13,
              'added_characters': len(ADDITION), 'unchanged_equations': len(scripts),
              'old_table_height': old_height, 'edited_table_height': int(et.find(HP+'sz').get('height')),
              'pages': 12, 'negative_source_cases': 4, 'painted_and_resaved': True,
              'inline_frames_painted_before_after_resave': [8, 8, 8],
              'package_nested_frame_cases': 5}
    (folder/'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('NATIVE_MIXED_TABLE_PARAGRAPHS_OK', result)
    return result


if __name__ == '__main__':
    if not (ROOT/'data/external_exam_qa/2026_june_high1/math.pdf').exists():
        print('SKIP: external math PDF is unavailable')
        raise SystemExit(2)
    with tempfile.TemporaryDirectory(prefix='mixed_table_paragraph_') as temp:
        verify(Path(temp))
