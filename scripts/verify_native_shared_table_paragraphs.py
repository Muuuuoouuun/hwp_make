"""Source frame geometry and public cell-paragraph edit/save regression."""
# ruff: noqa: E402
from copy import deepcopy
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix='shared_table_paragraphs_')
os.environ['HWP_MAKE_DATA_DIR'] = RUNTIME.name
import fitz
from lxml import etree
import rhwp
from app.hwpx_writer_v2 import HwpxDocument
from app.pdf_layout_writer import write_pdf_structured_hwpx
from app.pdf_native_content import extract_native_content
from app.pdf_native_typography import HP, HH, _flow_height
from app.pdf_question_rendering import IDENTITY, _multiply, _transform
from app.pdf_table_paragraphs import restore_table_paragraphs
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools.paragraph_spacing import paragraph_spacing, paragraph_indentation

SVG = '{http://www.w3.org/2000/svg}'
LINES = ['Measured paragraphs preserve their words',
         'when a printed sentence wraps onto',
         'another line inside this editable frame.']
FOLLOWING = ['A separate paragraph follows the gap.',
             'Its text remains a separate paragraph.']
ADDITION = (' Editing this cell must grow its native table and push the following paragraph down.'
            ' It must remain one paragraph after saving. SHARED_CELL_EDIT_END')


def state(path):
    with zipfile.ZipFile(path) as archive:
        root = etree.fromstring(archive.read('Contents/section0.xml'))
        header = etree.fromstring(archive.read('Contents/header.xml'))
    styles = {p.get('id'): p for p in header.iter(HH + 'paraPr')}
    assert len(styles) == len(list(header.iter(HH + 'paraPr'))), 'duplicate paragraph style IDs'
    p = next(p for p in root.iter(HP + 'p') if LINES[0] in ''.join(t.text or '' for t in p.findall(HP + 'run/' + HP + 't')))
    table = next(a for a in p.iterancestors() if a.tag == HP + 'tbl')
    following = next(q for q in table.iter(HP + 'p') if FOLLOWING[0] in ''.join(t.text or '' for t in q.findall(HP + 'run/' + HP + 't')))
    return root, header, styles, p, following, table


def tokens(path):
    doc = rhwp.parse(str(path))
    result = []
    for page in range(doc.page_count):
        svg = etree.fromstring(doc.render_svg(page).encode())
        for node in svg.iter(SVG + 'text'):
            if any(a.tag == SVG + 'defs' for a in node.iterancestors()):
                continue
            matrix = IDENTITY
            for a in [*reversed(list(node.iterancestors())), node]:
                matrix = _multiply(matrix, _transform(a.get('transform', '')))
            x, y = float(node.get('x', 0)), float(node.get('y', 0))
            tx, ty = matrix[0]*x + matrix[2]*y + matrix[4], matrix[1]*x + matrix[3]*y + matrix[5]
            result.extend((c, tx, ty, page) for c in ''.join(node.itertext()) if not c.isspace())
    return result


def locate(rendered, text):
    value = re.sub(r'\s+', '', text)
    joined = ''.join(t[0] for t in rendered)
    assert joined.count(value) == 1, 'expected native text missing or duplicated in actual SVG'
    start = joined.index(value)
    return rendered[start:start + len(value)]


def main():
    folder = Path(RUNTIME.name)
    source, native = folder / 'source.pdf', folder / 'native.hwpx'
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.insert_text((150, 40), 'Paragraph source test')
        page.insert_text((40, 95), '[1~2] Read the shared passage.', fontsize=10)
        page.draw_rect(fitz.Rect(40, 120, 287, 270), width=.5)
        for i, line in enumerate(LINES):
            page.insert_text((60 if i == 0 else 50, 140 + i*15), line, fontsize=10)
        for i, line in enumerate(FOLLOWING):
            page.insert_text((50, 230 + i*15), line, fontsize=10)
        page.insert_text((40, 320), '1. Choose the correct description.', fontsize=10)
        page.insert_text((310, 95), '2. Choose another description.', fontsize=10)
        doc.save(source)
    write_pdf_structured_hwpx(source, native, native_math=True)
    root, header, styles, p, following, table = state(native)
    text = ''.join(t.text or '' for t in p.findall(HP + 'run/' + HP + 't'))
    assert all(line in text for line in LINES), 'source prose was split into printed-line paragraphs'
    assert not p.findall('.//' + HP + 'lineBreak')
    assert len(p.findall(HP + 'linesegarray/' + HP + 'lineseg')) == 3
    assert paragraph_spacing(p, styles)[1] > 0, 'source inter-paragraph gap was lost'
    assert paragraph_indentation(p, styles)[2] > 0, 'native first-line indentation was lost'
    scale = float(root.find('.//' + HP + 'pagePr').get('width')) / 595 / 75
    rendered = tokens(native)
    starts = [locate(rendered, line)[0] for line in LINES + FOLLOWING]
    assert len({t[3] for t in starts}) == 1
    for a, b, gap in zip(starts, starts[1:], [15, 15, 60, 15]):
        assert abs(b[2] - a[2] - gap*scale) < .1, (a, b, gap, scale)
    assert abs(starts[0][1] - starts[1][1] - 10*scale) < .1

    # A partial/mismatched source must not alter any cell text, cache or style.
    items, _ = extract_native_content(source)
    layout = next(item['layout'] for item in items if any(LINES[0] in str(t) for t in item.get('tables', [])))
    outer = table.getparent().getparent()
    for kind in ('mismatch', 'omitted', 'overflow'):
        bad = deepcopy(layout)
        records = bad['source_typography']['lines']
        if kind == 'mismatch':
            records[1]['text'] += 'forged'
        elif kind == 'omitted':
            records.pop()
        else:
            records[1]['bbox_pt'][2] += 500
        before, head_before = etree.tostring(outer), etree.tostring(header)
        def no_mutation(*args):
            raise AssertionError('rejected source allocated a paragraph style')
        assert restore_table_paragraphs(outer, bad, header, scale*595*75, no_mutation) == 0
        assert (etree.tostring(outer), etree.tostring(header)) == (before, head_before)

    old_height = int(table.find(HP + 'sz').get('height'))
    old_style = (paragraph_spacing(p, styles), paragraph_indentation(p, styles))
    old_count = len(table.findall('.//' + HP + 'p'))
    doc = HwpxDocument.open(native)
    candidate = next(q for q in doc.sections[0].element.iter(HP + 'p') if q.get('id') == p.get('id'))
    public = HwpxOxmlParagraph(candidate, doc.sections[0])
    public.text += ADDITION
    edited = folder / 'edited.hwpx'
    doc.save(edited)
    _, _, edited_styles, ep, ef, et = state(edited)
    assert ''.join(t.text or '' for t in ep.findall(HP + 'run/' + HP + 't')) == text + ADDITION
    assert len(et.findall('.//' + HP + 'p')) == old_count
    assert int(et.find(HP + 'sz').get('height')) > old_height
    assert (paragraph_spacing(ep, edited_styles), paragraph_indentation(ep, edited_styles)) == old_style
    first_cache = int(ef.find(HP + 'linesegarray/' + HP + 'lineseg').get('vertpos'))
    edited_start = int(ep.find(HP + 'linesegarray/' + HP + 'lineseg').get('vertpos'))
    assert first_cache >= edited_start + _flow_height(ep) + old_style[0][1]
    painted = tokens(edited)
    body, tail = locate(painted, text + ADDITION), locate(painted, ' '.join(FOLLOWING))
    assert {x[3] for x in body + tail} == {body[0][3]}
    assert tail[0][2] > max(x[2] for x in body) + old_style[0][1] / 75
    second = folder / 'edited_twice.hwpx'
    HwpxDocument.open(edited).save(second)
    _, _, _, p2, _, table2 = state(second)
    assert etree.tostring(p2) == etree.tostring(ep), 'second save changed the editable paragraph'
    assert table2.find(HP + 'sz').get('height') == et.find(HP + 'sz').get('height')
    locate(tokens(second), text + ADDITION)
    print('NATIVE_SHARED_TABLE_PARAGRAPHS_OK: measured wraps/gaps/indent, source mismatch rejection, public paragraph edit, table growth and re-save')


if __name__ == '__main__':
    main()
