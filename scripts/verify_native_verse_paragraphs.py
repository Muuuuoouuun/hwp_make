"""Intentional verse lines survive real paragraph/run edits in stanza paragraphs."""
# ruff: noqa: E402
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix='native_verse_')
os.environ['HWP_MAKE_DATA_DIR'] = RUNTIME.name
import fitz
from lxml import etree
from app.hwpx_writer_v2 import HwpxDocument, _paragraph_text_units
from app.pdf_layout_writer import write_pdf_structured_hwpx
from app.pdf_source_line_cache import apply_source_line_cache, HP
from app.pdf_verse import source_verse_stanzas
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools.package_validator import validate_package
from hwpx.tools.question_reflow import cache_lines
from scripts.verify_native_shared_table_paragraphs import tokens, locate

LINES = ['A quiet river turns.', 'The cold stones listen.', 'Small lights cross the water.',
         'A distant bell replies.', 'The empty road grows still.', 'Another morning waits.']


def state(path):
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read('Contents/section0.xml'))
    table = next(t for t in root.findall(HP + 'p/' + HP + 'run/' + HP + 'tbl') if LINES[0] in ''.join(t.itertext()))
    paragraphs = table.findall('.//' + HP + 'p')
    assert len(paragraphs) == 4, 'one label, two stanza paragraphs and one credit are required'
    assert not table.findall('.//' + HP + 'drawText'), 'verse lines must not become drawing boxes'
    return root, table, paragraphs


def verify_control_units(section):
    # Mixed text tails are real HWPX text, and a line break occupies one UTF-16
    # unit. The supplementary-plane character before it occupies two units.
    p = etree.Element(HP + 'p', paraPrIDRef='0')
    run = etree.SubElement(p, HP + 'run', charPrIDRef='0')
    text = etree.SubElement(run, HP + 't')
    text.text = '가😀'
    control = etree.SubElement(text, HP + 'lineBreak')
    control.tail = '나 다'
    records = [{'text': '가😀', 'bbox_pt': [40, 90, 60, 102], 'baseline_pt': 100},
               {'text': '나 다', 'bbox_pt': [40, 105, 65, 117], 'baseline_pt': 115}]
    layout = {'source_page_width_pt': 595.28, 'column_left_pt': 40,
              'source_typography': {'font_size_pt': 10, 'lines': records}}
    assert apply_source_line_cache(p, layout, 20000)
    assert [l.get('textpos') for l in p.findall(HP + 'linesegarray/' + HP + 'lineseg')] == ['0', '4']
    assert _paragraph_text_units(p) == 7
    original = etree.tostring(p)
    bad = deepcopy(p)
    t = bad.find(HP + 'run/' + HP + 't')
    t.text = '가'
    t[0].tail = '😀나 다'
    before = etree.tostring(bad)
    assert not apply_source_line_cache(bad, layout, 20000)
    assert etree.tostring(bad) == before
    assert etree.tostring(p) == original

    # External HWPX files can put text in a control's tail. Both public
    # getters and setters must include it without duplicating native breaks.
    public = HwpxOxmlParagraph(deepcopy(p), section)
    assert public.text == public.runs[0].text == '가😀\n나 다'
    expected = public.text + '\n다음 줄\t끝'
    public.runs[0].text = expected
    assert public.text == expected
    public.text = public.text
    assert public.text == public.runs[0].text == expected
    assert len(public.element.findall('.//' + HP + 'lineBreak')) == 2
    assert len(public.element.findall('.//' + HP + 'tab')) == 1
    assert _paragraph_text_units(public.element) == 21
    cache_lines(public.element, 20000, {}, {})
    assert [line.get('textpos') for line in public.element.findall(
        HP + 'linesegarray/' + HP + 'lineseg')] == ['0', '4', '8']


def main():
    folder = Path(RUNTIME.name)
    source, native = folder / 'source.pdf', folder / 'native.hwpx'
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.insert_text((150, 40), 'Verse test')
        page.insert_text((40, 95), '[1~2] Read the shared passage.', fontsize=10)
        page.draw_rect(fitz.Rect(40, 116, 287, 282), width=.5)
        page.insert_text((50, 132), '(A)', fontsize=10)
        baselines = [150, 165, 180, 212, 227, 242]
        for line, y in zip(LINES, baselines):
            page.insert_text((60, y), line, fontsize=10)
        page.insert_text((180, 265), '- Poet, "River" -', fontsize=10)
        page.insert_text((40, 320), '1. Choose the correct description.', fontsize=10)
        page.insert_text((310, 95), '2. Choose another description.', fontsize=10)
        doc.save(source)
    write_pdf_structured_hwpx(source, native, native_math=True)
    root, table, paragraphs = state(native)
    assert len(table.findall('.//' + HP + 'lineBreak')) == 4
    assert [len(p.findall(HP + 'linesegarray/' + HP + 'lineseg')) for p in paragraphs] == [1, 3, 3, 1]
    assert validate_package(native).ok
    rendered = tokens(native)
    starts = [locate(rendered, line)[0] for line in LINES]
    scale = float(root.find('.//' + HP + 'pagePr').get('width')) / 595 / 75
    for a, b, sa, sb in zip(starts, starts[1:], baselines, baselines[1:]):
        assert abs(b[2] - a[2] - (sb-sa)*scale) < .1
    identifier = paragraphs[1].get('id')
    doc = HwpxDocument.open(native)
    section = doc.sections[0]
    verify_control_units(section)
    node = next(p for p in section.element.iter(HP + 'p') if p.get('id') == identifier)
    public = HwpxOxmlParagraph(node, section)
    assert public.text == '\n'.join(LINES[:3])
    assert public.runs[0].text == public.text
    public.text = public.text
    credit_node = next(p for p in section.element.iter(HP + 'p') if p.get('id') == paragraphs[-1].get('id'))
    credit = HwpxOxmlParagraph(credit_node, section)
    credit.text = credit.text
    saved = folder / 'noop.hwpx'
    doc.save_to_path(saved)
    _, _, same = state(saved)
    assert len(same[1].findall('.//' + HP + 'lineBreak')) == 2
    assert len(same[1].findall(HP + 'linesegarray/' + HP + 'lineseg')) == 3
    assert len(same[-1].findall(HP + 'linesegarray/' + HP + 'lineseg')) == 1, 'right-aligned credit wrapped on a no-op edit'
    painted = tokens(saved)
    y = [locate(painted, line)[0][2] for line in LINES[:3]]
    assert y[0] < y[1] < y[2], 'no-op setter collapsed intentional verse lines'

    doc = HwpxDocument.open(saved)
    section = doc.sections[0]
    public = HwpxOxmlParagraph(next(p for p in section.element.iter(HP + 'p') if p.get('id') == identifier), section)
    # A run edit must replace old controls, including mixed-content tails.
    addition = ' Its waters carry the long story of a winter journey through the valley.'
    expected = public.text.replace(LINES[0], LINES[0] + addition)
    public.runs[0].text = expected
    assert public.text == expected
    edited = folder / 'edited.hwpx'
    doc.save_to_path(edited)
    _, enlarged, changed = state(edited)
    assert len(changed[1].findall('.//' + HP + 'lineBreak')) == 2
    assert len(changed[1].findall(HP + 'linesegarray/' + HP + 'lineseg')) > 3
    assert int(enlarged.find(HP + 'sz').get('height')) > int(table.find(HP + 'sz').get('height'))
    painted = tokens(edited)
    first = locate(painted, LINES[0] + addition)
    second, third = locate(painted, LINES[1]), locate(painted, LINES[2])
    next_stanza = locate(painted, LINES[3])
    assert max(t[2] for t in first) < second[0][2] < third[0][2] < next_stanza[0][2]
    second_save = folder / 'edited_twice.hwpx'
    HwpxDocument.open(edited).save_to_path(second_save)
    _, _, stable = state(second_save)
    assert etree.tostring(changed[1]) == etree.tostring(stable[1])
    assert validate_package(second_save).ok
    locate(tokens(second_save), expected)

    # Credited, margin-filled prose and uncredited short lists are not verse.
    records = [{'text': line, 'bbox_pt': [50, y-10, 270, y+2], 'baseline_pt': y, 'font_size_pt': 10}
               for line,y in zip(LINES, baselines)]
    credit = {'text': '- Sample Author, "A Report" -', 'bbox_pt': [150,255,280,267],
              'baseline_pt': 265, 'font_size_pt': 10}
    assert source_verse_stanzas(records + [credit], 237) is None
    for r in records:
        r['bbox_pt'][2] = 150
    assert source_verse_stanzas(records, 237) is None
    records[2]['text'] = '1. A numbered instruction'
    assert source_verse_stanzas(records + [credit], 237) is None
    print('NATIVE_VERSE_PARAGRAPHS_OK: source-backed stanza paragraphs, native verse breaks, UTF-16 tails, no-op/run edits, growth, visible line order and stable re-save')


if __name__ == '__main__':
    main()
