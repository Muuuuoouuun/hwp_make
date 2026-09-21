"""Edit a textbox inside a table inside a question, without losing its paint."""
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
from xml.etree import ElementTree
import zipfile

from lxml import etree as E
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_native_inline_label_audit import native_fixture
from app.hwpx_writer_v2 import _set_paragraph_element_lineseg
from app.hwpx_writer_v2 import write_hwpx
from app.pdf_inline_labels import HP, native_inline_labels
from app.pdf_inline_label_rendering import painted_label_frames, missing_label_frames
from app.pdf_question_geometry import inspect_question_geometry
from hwpx import HwpxDocument
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.oxml._document_impl import _create_rectangle_element
from hwpx.tools.question_reflow import cache_lines
from hwpx.tools.package_validator import validate_package
import rhwp

HH = '{http://www.hancom.co.kr/hwpml/2011/head}'


def verify_invisible_object_marker(folder):
    marked, clean = folder/'marker.hwpx', folder/'marker_removed.hwpx'
    write_hwpx(marked, 'Renderer marker check', [
        {'number': '1', 'stem': 'Visible native paragraph \ufffc'}], native_math=True)
    with zipfile.ZipFile(marked) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    assert any('\ufffc'.encode() in b for n, b in parts.items() if n.startswith('Contents/section'))
    with zipfile.ZipFile(clean, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, payload in parts.items():
            z.writestr(name, payload.replace('\ufffc'.encode(), b'')
                       if name.startswith('Contents/section') else payload)
    a, b = rhwp.parse(str(marked)), rhwp.parse(str(clean))
    assert a.page_count == b.page_count
    for page in range(a.page_count):
        images = [Image.open(io.BytesIO(bytes(d.render_png(page)))).convert('RGB') for d in (a, b)]
        assert ImageChops.difference(*images).getbbox() is None, 'internal object marker was painted as a glyph'


def nested_fixture(path):
    native_fixture(path)
    doc = HwpxDocument.open(path)
    section, p = next((s, p) for s in doc.sections for p in s.element.findall(HP+'p')
                      if 'Paragraph before' in ''.join(p.itertext()))
    source_runs = list(p.findall(HP+'run'))
    public = HwpxOxmlParagraph(p, section)
    table = public.add_table(1, 1, width=22000, height=10000).element
    cell_p = table.find(HP+'tr/'+HP+'tc/'+HP+'subList/'+HP+'p')
    for node in list(cell_p):
        cell_p.remove(node)
    for run in source_runs:
        cell_p.append(run)
    E.SubElement(cell_p.findall(HP+'run')[-1], HP+'t').text = ' The sentence continues after the blank.'
    header = doc.headers[0].element
    chars = {p.get('id'): p for p in header.iter(HH+'charPr')}
    paras = {p.get('id'): p for p in header.iter(HH+'paraPr')}
    label = next(p for p in cell_p.iter(HP+'p') if p.get('id') == '987655')
    centered = deepcopy(paras[label.get('paraPrIDRef')])
    centered.set('id', str(max(map(int, paras)) + 1))
    centered.find(HH+'align').set('horizontal', 'CENTER')
    definitions = header.find('.//'+HH+'paraProperties')
    definitions.append(centered)
    definitions.set('itemCnt', str(len(definitions)))
    paras[centered.get('id')] = centered
    label.set('paraPrIDRef', centered.get('id'))
    doc.headers[0].mark_dirty()
    cache_lines(cell_p, 21000, chars, paras)
    _set_paragraph_element_lineseg(p, 10000, width=22000, spacing_ratio=0)
    shape = E.fromstring(ElementTree.tostring(_create_rectangle_element(
        22961, 14000, line_width='1', fill_color=None)))
    shape.set('id', '987660')
    shape.set('instid', '987660')
    shape.set('textWrap', 'TOP_AND_BOTTOM')
    shape.find(HP+'lineShape').set('style', 'NONE')
    draw = E.Element(HP+'drawText', lastWidth='22961', name='question:v1:q01', editable='1')
    E.SubElement(draw, HP+'textMargin', left='0', right='0', top='0', bottom='0')
    sub = E.SubElement(draw, HP+'subList', id='', textDirection='HORIZONTAL', lineWrap='BREAK',
        vertAlign='TOP', linkListIDRef='0', linkListNextIDRef='0', textWidth='22961',
        textHeight='14000', hasTextRef='0', hasNumRef='0')
    anchor = E.Element(HP+'p', dict(p.attrib))
    anchor.set('id', '987661')
    section.element.replace(p, anchor)
    sub.append(p)
    shape.insert(shape.index(shape.find(HP+'shadow')), draw)
    E.SubElement(anchor, HP+'run', charPrIDRef='0').append(shape)
    _set_paragraph_element_lineseg(anchor, 14000, width=22961, spacing_ratio=0)
    doc.save_to_path(path)


def state(path):
    with zipfile.ZipFile(path) as z:
        return [E.fromstring(z.read(n)) for n in z.namelist()
                if n.startswith('Contents/section') and n.endswith('.xml')]


def painted(path, labels):
    validation = validate_package(path)
    assert validation.ok, validation
    doc = rhwp.parse(str(path))
    required = native_inline_labels(state(path))
    assert len(required) == 1, 'the single native inline frame was lost'
    frames = [frame for i in range(doc.page_count)
              for frame in painted_label_frames(doc.render_svg(i), labels)]
    assert len(frames) == 1, 'the native frame was omitted or painted twice'
    assert not missing_label_frames(required, frames), 'nested frame/glyphs were not painted'
    return doc.page_count


def verify(folder):
    folder.mkdir(parents=True, exist_ok=True)
    verify_invisible_object_marker(folder)
    source = folder/'nested.hwpx'
    nested_fixture(source)
    before = state(source)
    baseline_count = sum(len(list(r.iter(HP+'p'))) for r in before)
    doc = HwpxDocument.open(source)
    section, label = next((s, p) for s in doc.sections for p in s.element.iter(HP+'p')
                          if p.get('id') == '987655')
    shape = label.getparent().getparent().getparent()
    old_geometry = [dict(shape.find(HP+k).attrib) for k in ('sz', 'pos')]
    HwpxOxmlParagraph(label, section).runs[0].text = '(나)'
    edited = folder/'label_edited.hwpx'
    doc.save_to_path(edited)
    after = state(edited)
    label2 = next(p for r in after for p in r.iter(HP+'p') if p.get('id') == '987655')
    assert ''.join(t.text or '' for t in label2.findall(HP+'run/'+HP+'t')) == '(나)'
    shape2 = label2.getparent().getparent().getparent()
    assert [dict(shape2.find(HP+k).attrib) for k in ('sz', 'pos')] == old_geometry
    assert label2.find(HP+'linesegarray/'+HP+'lineseg').get('horzsize') == '5382', 'label borrowed the outer cell width'
    assert sum(len(list(r.iter(HP+'p'))) for r in after) == baseline_count
    assert all(inspect_question_geometry(d)['ok'] for r in after for d in r.iter(HP+'drawText'))
    resaved = folder/'label_resaved.hwpx'
    HwpxDocument.open(edited).save_to_path(resaved)
    final_label = next(p for r in state(resaved) for p in r.iter(HP+'p') if p.get('id') == '987655')
    assert E.tostring(final_label) == E.tostring(label2)
    counts = [painted(p, {'(가)', '(나)'}) for p in (source, edited, resaved)]
    assert len(set(counts)) == 1
    result = {'ok': True, 'native_paragraphs': baseline_count, 'saved_label_width': 5382,
              'label_replaced': True, 'resaved': True, 'all_three_painted': True, 'pages': counts[0],
              'object_marker_raster_invisible': True}
    (folder/'report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('NATIVE_NESTED_TEXTBOX_EDITING_OK', result)
    return result


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='nested_textbox_editing_') as temp:
        verify(Path(temp))
