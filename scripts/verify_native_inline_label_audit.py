"""No false passes for short labels whose frames or painted glyphs disappear."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from xml.etree import ElementTree
import zipfile

import fitz
from lxml import etree as E

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.hwpx_writer_v2 import write_hwpx
from app.pdf_inline_labels import source_inline_labels, native_inline_labels, inspect_inline_label_preservation, HP
from app.pdf_inline_label_rendering import painted_label_frames, missing_label_frames
from app.pdf_question_rendering import inspect_question_rendering
from hwpx.oxml._document_impl import _create_rectangle_element
import rhwp

SVG = '{http://www.w3.org/2000/svg}'


def native_fixture(path):
    write_hwpx(path, 'Inline label audit', [{'number': '1', 'stem': 'Paragraph before the blank and after it.'}], native_math=True)
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    root = E.fromstring(parts['Contents/section0.xml'])
    p = next(p for p in root.iter(HP+'p') if 'Paragraph before' in ''.join(p.itertext()))
    run = p.find(HP+'run')
    shape = E.fromstring(ElementTree.tostring(_create_rectangle_element(5382, 1667, line_width='12', fill_color=None)))
    shape.set('id', '987654')
    shape.set('instid', '987654')
    shape.set('lock', '0')
    draw = E.Element(HP+'drawText', lastWidth='5382', name='audit-label', editable='1')
    E.SubElement(draw, HP+'textMargin', left='0', right='0', top='0', bottom='0')
    sub = E.SubElement(draw, HP+'subList', id='', textDirection='HORIZONTAL', lineWrap='BREAK',
        vertAlign='CENTER', linkListIDRef='0', linkListNextIDRef='0', textWidth='5382', textHeight='1667',
        hasTextRef='0', hasNumRef='0')
    label = E.SubElement(sub, HP+'p', id='987655', paraPrIDRef=p.get('paraPrIDRef'), styleIDRef='0',
                         pageBreak='0', columnBreak='0', merged='0')
    lr = E.SubElement(label, HP+'run', charPrIDRef=run.get('charPrIDRef'))
    E.SubElement(lr, HP+'t').text = '(가)'
    cache = E.SubElement(label, HP+'linesegarray')
    E.SubElement(cache, HP+'lineseg', textpos='0', vertpos='0', vertsize='1000', textheight='1000',
                 baseline='850', spacing='0', horzpos='1000', horzsize='5382', flags='393216')
    shadow = shape.find(HP+'shadow')
    shape.insert(shape.index(shadow) if shadow is not None else len(shape), draw)
    run.append(shape)
    parts['Contents/section0.xml'] = E.tostring(root)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, payload in parts.items():
            z.writestr(n, payload)
    return root


def verify(folder):
    folder.mkdir(parents=True, exist_ok=True)
    pdf, native = folder/'source.pdf', folder/'visible.hwpx'
    with fitz.open() as doc:
        page = doc.new_page(width=595.28, height=841.88)
        for i, kind in enumerate(('valid', 'unframed', 'white', 'transparent', 'open', 'large')):
            y = 90+i*50
            rect = fitz.Rect(50, y, 103.82, y+16.67)
            page.insert_text((67, y+12), '(가)', fontname='korea', fontsize=10)
            if kind == 'open':
                page.draw_line(rect.tl, rect.tr, width=.12)
            elif kind == 'large':
                page.draw_rect(fitz.Rect(40, y-8, 180, y+25), width=.12)
            elif kind != 'unframed':
                page.draw_rect(rect, color=(1, 1, 1) if kind == 'white' else (0, 0, 0),
                               width=.12, stroke_opacity=0 if kind == 'transparent' else 1)
        doc.save(pdf)
        labels = source_inline_labels(page)
        assert len(labels) == 1 and labels[0]['text'] == '(가)', labels
    root = native_fixture(native)
    audit = inspect_inline_label_preservation(pdf, [root])
    assert audit['ok'] and audit['matched_label_frames'] == 1, audit
    required = native_inline_labels([root])
    renderer = rhwp.parse(str(native))
    svg = renderer.render_svg(0)
    assert not missing_label_frames(required, painted_label_frames(svg, {'(가)'}))
    assert inspect_question_rendering(native, rhwp)['ok']
    for kind in ('text', 'border', 'width', 'anchor', 'height', 'duplicate'):
        bad = deepcopy(root)
        rect = next(r for r in bad.iter(HP+'rect') if r.get('id') == '987654')
        if kind == 'text':
            rect.find('.//'+HP+'t').text = '(나)'
        elif kind == 'border':
            rect.find(HP+'lineShape').set('alpha', '255')
        elif kind == 'width':
            rect.find(HP+'sz').set('width', '1000')
        elif kind == 'anchor':
            rect.find(HP+'pos').set('treatAsChar', '0')
        elif kind == 'height':
            rect.find(HP+'sz').set('height', '1')
        else:
            rect.getparent().append(deepcopy(rect))
        assert not inspect_inline_label_preservation(pdf, [bad])['ok'], kind
    # Native membership cannot substitute for paint. The same literal outside
    # the frame must not compensate for a missing label inside it.
    for kind in ('text', 'border', 'hidden', 'width', 'clipped', 'elsewhere', 'definition'):
        bad = E.fromstring(svg.encode())
        rect = next(n for n in bad.iter(SVG+'rect') if n.get('stroke') == '#000000')
        if kind in ('text', 'elsewhere'):
            for n in bad.iter(SVG+'text'):
                if n.text:
                    n.text = n.text.replace('가', '나')
            if kind == 'elsewhere':
                E.SubElement(bad, SVG+'text', x='20', y='20', fill='#000000', **{'font-size': '12'}).text = '(가)'
        elif kind == 'border':
            rect.set('stroke', '#ffffff')
        elif kind == 'hidden':
            rect.set('opacity', '0')
        elif kind == 'width':
            rect.set('width', str(float(rect.get('width'))+2))
        elif kind == 'clipped':
            rect.set('x', '-5')
        else:
            defs = E.SubElement(bad, SVG+'defs')
            defs.append(rect)
        painted = painted_label_frames(E.tostring(bad, encoding='unicode'), {'(가)'})
        assert missing_label_frames(required, painted), kind
    result = {'ok': True, 'source_positive': 1, 'source_negatives': 5, 'native_negatives': 6,
              'paint_negatives': 7, 'visible_native_label': True, 'unframed_alias_rejected': True}
    (folder/'report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('NATIVE_INLINE_LABEL_AUDIT_OK', result)
    return result


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='inline_label_audit_') as temp:
        verify(Path(temp))
