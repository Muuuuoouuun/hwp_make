"""Real letter frame: source bounds, paragraph editing and actual paint."""
from collections import Counter
from copy import copy, deepcopy
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fitz
from lxml import etree
from PIL import Image
import rhwp
from app.pdf_layout_writer import write_pdf_structured_hwpx
from app.pdf_native_content import extract_native_content
from app.pdf_editability import inspect_pdf_editability
from app.pdf_question_rendering import (
    IDENTITY, _multiply, _transform, _bounds, _bitmap_identity,
    _visible_svg_images, inspect_question_rendering,
)
from app.hwpx_writer_v2 import HwpxDocument
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools.package_validator import validate_package
from scripts.verify_native_shared_table_paragraphs import tokens, locate

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
SVG = '{http://www.w3.org/2000/svg}'
ADDITION = (' Please bring books that younger readers can enjoy during the summer.'
            ' Every donated book will support a new reading group at the center.'
            ' LETTER_FRAME_EDIT_END')


def body_cell(table):
    cells = table.findall(HP+'tr/'+HP+'tc')
    bodies = [c for c in cells if any((t.text or '').strip() for t in c.iter(HP+'t'))]
    assert len(bodies) == 1, 'the frame must have one native text-bearing cell'
    return bodies[0]


def state(path):
    with zipfile.ZipFile(path) as package:
        roots = [etree.fromstring(package.read(n)) for n in package.namelist()
                 if re.fullmatch(r'Contents/section\d+\.xml', n)]
        media = Counter(hashlib.sha256(package.read(n)).hexdigest()
                        for n in package.namelist() if n.startswith('BinData/'))
    draw = next(d for r in roots for d in r.iter(HP+'drawText')
                if d.get('name') == 'question:v1:q18')
    table = draw.find('.//'+HP+'tbl')
    paragraphs = body_cell(table).findall(HP+'subList/'+HP+'p')
    assert len(paragraphs) == 3, 'letter body was split into printed-line paragraphs'
    assert not table.findall('.//'+HP+'lineBreak'), 'ordinary prose has forced line breaks'
    assert not draw.findall('.//'+HP+'pic'), 'a frame rim was duplicated as a flow figure'
    return roots, draw, table, paragraphs, media


def painted_frame(path, payload):
    from app.pdf_source_backgrounds import native_background_assets
    from app.pdf_source_image_validation import compare_source_crop
    _, _, table, _, _ = state(path)
    with zipfile.ZipFile(path) as package:
        header = etree.fromstring(package.read('Contents/header.xml'))
        manifest = etree.fromstring(package.read('Contents/content.hpf'))
        hrefs = {n.get('id'): n.get('href') for n in manifest.iter('{http://www.idpf.org/2007/opf/}item')}
        assets = native_background_assets(table, header, hrefs, package)
    assert len(assets) in (1, 3), 'the frame lost a native background part'
    bitmaps = [Image.open(io.BytesIO(data)).convert('RGB') for _, data in assets]
    assert len({image.width for image in bitmaps}) == 1
    combined = Image.new('RGB', (bitmaps[0].width, sum(image.height for image in bitmaps)))
    y = 0
    for image in bitmaps:
        combined.paste(image, (0, y)); y += image.height
    combined_data = io.BytesIO(); combined.save(combined_data, format='PNG')
    assert compare_source_crop(payload, combined_data.getvalue())['ok'], 'native background parts do not reconstruct the original decoration'
    required = Counter(_bitmap_identity(data) for _, data in assets)
    doc = rhwp.parse(str(path))
    painted = Counter()
    rectangles = []
    for page in range(doc.page_count):
        svg = doc.render_svg(page)
        visible = _visible_svg_images(svg)
        painted.update({key: visible[key] for key in required})
        root = etree.fromstring(svg.encode())
        for node in root.iter(SVG+'image'):
            if any(a.tag == SVG+'defs' for a in node.iterancestors()):
                continue
            href = node.get('{http://www.w3.org/1999/xlink}href') or node.get('href', '')
            if not href.startswith('data:') or _bitmap_identity(base64.b64decode(href.split(',', 1)[1])) not in required:
                continue
            matrix = IDENTITY
            for a in [*reversed(list(node.iterancestors())), node]:
                matrix = _multiply(matrix, _transform(a.get('transform', '')))
            rectangles.append((page, _bounds(matrix, *[float(node.get(k, 0)) for k in ('x', 'y', 'width', 'height')])))
    assert painted == required and len(rectangles) == len(assets), 'original decoration must paint exactly once'
    rectangles.sort(key=lambda r: (r[0], r[1][1]))
    assert len({p for p, _ in rectangles}) == 1
    for (_, a), (_, b) in zip(rectangles, rectangles[1:]):
        assert max(abs(a[0]-b[0]), abs(a[2]-b[2]), abs(a[3]-b[1])) < .03, 'native background parts have a gap or overlap'
    return rectangles[0][0], (rectangles[0][1][0], rectangles[0][1][1], rectangles[-1][1][2], rectangles[-1][1][3])


def verify_bitmap_ownership(folder):
    from app import importers
    from app.pdf_background_figures import remove_covered_bitmap_figures
    from app.pdf_source_backgrounds import compose_source_background
    from app.pdf_source_image_validation import render_source_crop
    from PIL import ImageDraw
    bitmap = Image.new('RGB', (260, 260), 'white')
    paint = ImageDraw.Draw(bitmap)
    paint.rectangle((0, 0, 259, 259), outline='black', width=2)
    paint.rectangle((0, 0, 259, 18), fill='gray')
    stream = io.BytesIO()
    bitmap.save(stream, format='PNG')
    for case in ('covered', 'vector', 'text', 'extra_bitmap', 'partial'):
        source = folder/(case+'.pdf')
        with fitz.open() as pdf:
            page = pdf.new_page(width=400, height=400)
            frame, clip = fitz.Rect(40, 40, 300, 300), fitz.Rect(40, 40, 300, 58)
            page.insert_image(frame, stream=stream.getvalue())
            page.insert_text((55, 100), 'Native content for the complete frame.', fontsize=8)
            if case == 'vector':
                page.draw_line((100, 45), (160, 53))
            elif case == 'text':
                page.insert_text((100, 53), 'Keep editable text', fontsize=8)
            elif case == 'extra_bitmap':
                page.insert_image(fitz.Rect(100, 45, 110, 53), stream=stream.getvalue())
            pdf.save(source)
        with fitz.open(source) as pdf:
            page = pdf[0]
            number = next(b['number'] for b in page.get_text('dict')['blocks'] if b.get('type') == 1)
            if case == 'partial':
                frame.y0 += 10
            background = compose_source_background(page, frame, [number])
            picture = render_source_crop(source, 0, clip)
            records, paths = [], []
            for data, bounds, role in ((background, frame, 'source_background_frame'), (picture, clip, 'source_figure')):
                paths.append(importers._save_image_bytes(case+'_'+role+'.png', data))
                records.append({'sha256': hashlib.sha256(data).hexdigest(), 'role': role,
                                'page': 1, 'bbox_px': [bounds.x0, bounds.y0, bounds.width, bounds.height],
                                'source_image_numbers': [number]})
            lines = [{'text': ''.join(s['text'] for s in line['spans']), 'bbox_pt': list(line['bbox'])}
                     for block in page.get_text('dict')['blocks'] for line in block.get('lines', [])
                     if frame.contains(fitz.Rect(line['bbox']))]
            text = ''.join(line['text'] for line in lines)
            items = [{'tables': [[[text]]], 'layout': {'source_typography': {'lines': lines}, 'native_tables': [
                {'background_path': paths[0], 'bbox_pt': list(frame), 'cell_bounds': [[list(frame)]],
                 'background_source_text': text}]}},
                     {'image_paths': [paths[1]], 'layout': {'source_bbox_pt': list(clip)}}]
            kept, retained = remove_covered_bitmap_figures(page, items, records)
            expected = 1 if case == 'covered' else 2
            assert len(kept) == len(retained) == expected, ('incorrect bitmap ownership', case)


def verify(folder, source=None, native=None, provenance=None):
    source = source or ROOT/'data/external_exam_qa/2026_june_high1/english.pdf'
    folder.mkdir(parents=True, exist_ok=True)
    verify_bitmap_ownership(folder)
    if native is None:
        native = folder/'english.hwpx'
        stats = write_pdf_structured_hwpx(source, native, native_math=True)
        provenance = stats['image_provenance']
    items, original_provenance = extract_native_content(source)
    if provenance is None:
        provenance = original_provenance
    item = next(i for i in items if i.get('tables') and 'Dear Residents,' in str(i['tables']))
    layout = item['layout']
    records = layout['source_typography']['lines']
    geometry = layout['native_tables'][0]
    from app import storage
    payload = storage.resolve_data_image_path(geometry['background_path']).read_bytes()
    roots, draw, table, paragraphs, media = state(native)
    assert table.get('rowCnt') == '3', 'decorative caps must be ordinary fixed native rows'
    original_caps = [int(c.find(HP+'cellSz').get('height')) for c in table.findall(HP+'tr/'+HP+'tc')][::2]
    audit = inspect_pdf_editability(source, native, provenance, require_question_boxes=True)
    assert audit['ok'], audit['issues']
    # Partial frame metadata must leave the native paragraph and its geometry
    # untouched. This reproduces a frame shared by several Korean callouts.
    from app.pdf_table_paragraphs import restore_background_frame
    fragment = deepcopy(layout)
    fragment['source_typography']['lines'].pop()
    outer = deepcopy(table.getparent().getparent())
    partial_table = outer.find('.//'+HP+'tbl')
    partial_body = deepcopy(body_cell(partial_table))
    partial_body.find(HP+'cellAddr').set('rowAddr', '0')
    for row in partial_table.findall(HP+'tr'):
        partial_table.remove(row)
    etree.SubElement(partial_table, HP+'tr').append(partial_body)
    partial_table.set('rowCnt', '1')
    unchanged = etree.tostring(outer)
    def forbidden_style(*args):
        raise AssertionError('partial source frame allocated a paragraph style')
    assert restore_background_frame(outer, fragment, etree.Element('header'), 59528, 22961, forbidden_style) == 0
    assert etree.tostring(outer) == unchanged
    assert [len(p.findall(HP+'linesegarray/'+HP+'lineseg')) for p in paragraphs] == [1, 10, 2]
    scale = float(roots[0].find('.//'+HP+'pagePr').get('width')) / layout['source_page_width_pt'] / 75
    expected = [x*scale for x in geometry['bbox_pt']]
    page, actual = painted_frame(native, payload)
    errors = [abs(a-b) for a, b in zip(actual, expected)]
    assert page == 1 and max(errors) < .1, ('source frame bounds differ', actual, expected)
    rendered = tokens(native)
    inside = [t for t in rendered if t[3] == page and actual[0] < t[1] < actual[2] and actual[1] < t[2] < actual[3]]
    passage = locate(inside, ''.join(r['text'] for r in records))
    lengths = [len(re.sub(r'\s+', '', r['text'])) for r in records]
    positions = [passage[sum(lengths[:i])] for i in range(len(records))]
    line_errors = [max(abs(p[1]-r['bbox_pt'][0]*scale), abs(p[2]-r['baseline_pt']*scale))
                   for p, r in zip(positions, records)]
    assert max(line_errors) < .1, ('source paragraph baseline or indentation differs', line_errors)
    old_height = int(table.find(HP+'sz').get('height'))
    old_choice = locate(rendered, '① 커뮤니티 센터 운영 시간을 공지하려고')[0]
    # Break the native position and duplicate the background. Actual-paint
    # geometry must reject both, even though all words/assets are still there.
    with zipfile.ZipFile(native) as package:
        for kind in ('zero_offset', 'duplicate_frame', 'line_paragraphs', 'wrong_offset', 'fixed_page', 'no_flow',
                     'resized_cap', 'reordered_caps', 'missing_cap'):
            part = next(n for n in package.namelist() if re.fullmatch(r'Contents/section\d+\.xml', n)
                        and b'Dear Residents' in package.read(n))
            root = etree.fromstring(package.read(part))
            d = next(d for d in root.iter(HP+'drawText') if d.get('name') == 'question:v1:q18')
            t = d.find('.//'+HP+'tbl')
            if kind == 'zero_offset':
                t.find(HP+'pos').set('horzOffset', '0')
            elif kind == 'wrong_offset':
                t.find(HP+'pos').set('horzOffset', '1000')
            elif kind == 'fixed_page':
                t.find(HP+'pos').set('vertRelTo', 'PAGE')
            elif kind == 'no_flow':
                t.find(HP+'pos').set('flowWithText', '0')
            elif kind == 'duplicate_frame':
                t.getparent().append(deepcopy(t))
            elif kind == 'resized_cap':
                sz = t.find(HP+'tr/'+HP+'tc/'+HP+'cellSz')
                sz.set('height', str(int(sz.get('height'))+300))
            elif kind == 'reordered_caps':
                cells = t.findall(HP+'tr/'+HP+'tc')
                a, b = cells[0].get('borderFillIDRef'), cells[2].get('borderFillIDRef')
                cells[0].set('borderFillIDRef', b); cells[2].set('borderFillIDRef', a)
            elif kind == 'missing_cap':
                t.find(HP+'tr/'+HP+'tc').set('borderFillIDRef', t.get('borderFillIDRef'))
            else:
                sub = body_cell(t).find(HP+'subList')
                sub.append(deepcopy(sub.findall(HP+'p')[1]))
            bad = folder/(kind+'.hwpx')
            with zipfile.ZipFile(bad, 'w') as target:
                for entry in package.infolist():
                    target.writestr(copy(entry), etree.tostring(root) if entry.filename == part else package.read(entry.filename))
            rejected = False
            if kind in ('wrong_offset', 'fixed_page', 'no_flow', 'resized_cap', 'reordered_caps', 'missing_cap'):
                audit = inspect_pdf_editability(source, bad, provenance, require_question_boxes=True)
                assert not audit['ok'] and 'positioned_text_tables' in audit['issues'], (kind, audit['issues'])
                continue
            try:
                state(bad)
                _, bounds = painted_frame(bad, payload)
                assert max(abs(a-b) for a, b in zip(bounds, expected)) < .1
            except AssertionError:
                rejected = True
            assert rejected, ('invalid native frame passed', kind)

    doc = HwpxDocument.open(native)
    section, element = next((s, p) for s in doc.sections for p in s.element.iter(HP+'p')
                            if p.get('id') == paragraphs[1].get('id'))
    paragraph = HwpxOxmlParagraph(element, section)
    original = paragraph.text
    paragraph.text = original + ADDITION
    edited = folder/'letter_edited.hwpx'
    doc.save(edited)
    second = folder/'letter_resaved.hwpx'
    HwpxDocument.open(edited).save(second)
    for path in (edited, second):
        _, ed, et, ep, images = state(path)
        assert images == media, 'original assets changed under a text edit'
        assert int(et.find(HP+'sz').get('height')) > old_height
        assert len(ep[1].findall(HP+'linesegarray/'+HP+'lineseg')) > 10
        page, box = painted_frame(path, payload)
        visible = tokens(path)
        actual_text = locate(visible, original + ADDITION)
        inside = [t for t in visible if t[3] == page and box[0] < t[1] < box[2] and box[1] < t[2] < box[3]]
        closing = locate(inside, 'Sincerely, Trixie Mitchell')
        choice = locate(visible, '① 커뮤니티 센터 운영 시간을 공지하려고')[0]
        assert all(p[3] == page and box[0] < p[1] < box[2] and box[1] < p[2] < box[3]
                   for p in actual_text + closing), 'editable prose escapes its frame'
        font = layout['source_typography']['font_size_pt'] * scale
        assert min(p[2] for p in closing) - max(p[2] for p in actual_text) > font
        assert choice[2] - box[3] > font and choice[2] > old_choice[2], 'following text did not move below the frame'
        assert inspect_question_rendering(path, rhwp)['ok']
        assert validate_package(path).ok
        raster = Image.open(io.BytesIO(bytes(rhwp.parse(str(path)).render_png(page))))
        raster.save(folder/(path.stem+'.png'))
    assert etree.tostring(state(edited)[3][1]) == etree.tostring(state(second)[3][1])
    long_edits = []
    for repeats in (2, 3, 5):
        doc = HwpxDocument.open(native)
        section, element = next((s, p) for s in doc.sections for p in s.element.iter(HP+'p')
                                if p.get('id') == paragraphs[1].get('id'))
        HwpxOxmlParagraph(element, section).text += ADDITION * repeats
        path = folder/f'letter_added_{len(ADDITION)*repeats}.hwpx'
        doc.save(path)
        resaved = folder/f'letter_added_{len(ADDITION)*repeats}_resaved.hwpx'
        HwpxDocument.open(path).save(resaved)
        for candidate in (path, resaved):
            _, _, t, pp, images = state(candidate)
            assert images == media
            cells = t.findall(HP+'tr/'+HP+'tc')
            caps = [int(c.find(HP+'cellSz').get('height')) for c in cells][::2]
            assert caps == original_caps, 'decorative caps stretched with the body'
            page, bounds = painted_frame(candidate, payload)
            visible = tokens(candidate)
            complete = locate(visible, original + ADDITION*repeats)
            greeting = locate(visible, 'Dear Residents,')
            closing = locate(visible, 'Sincerely, Trixie Mitchell')
            cap_bottom = bounds[1]+caps[0]/75
            assert min(g[2] for g in greeting) - font > cap_bottom, 'greeting overlaps the title cap'
            assert min(g[2] for g in closing) - max(g[2] for g in complete) > font
            assert all(p[3] == page and bounds[0] < p[1] < bounds[2] and cap_bottom < p[2] < bounds[3]-caps[1]/75
                       for p in complete+greeting+closing), 'prose overlaps a decorative cap or leaves the body cell'
            choice = locate(visible, '① 커뮤니티 센터 운영 시간을 공지하려고')[0]
            assert choice[3] > page or choice[3] == page and choice[2] > bounds[3]+font
            assert inspect_question_rendering(candidate, rhwp)['ok'] and validate_package(candidate).ok
        raster = Image.open(io.BytesIO(bytes(rhwp.parse(str(path)).render_png(page))))
        raster.save(folder/f'letter_added_{len(ADDITION)*repeats}.png')
        long_edits.append({'added_characters': len(ADDITION)*repeats, 'fixed_cap_heights_hwp': caps,
                           'body_paragraphs': len(pp), 'edit_resave_and_no_overlap': True})
    result = {'ok': True, 'source_printed_lines': len(records), 'native_paragraphs': 3,
              'body_printed_lines_in_one_paragraph': 10,
              'maximum_frame_position_error_px': max(errors),
              'maximum_line_start_error_px': max(line_errors), 'position_threshold_px': .1,
              'logical_background_frames': 1, 'background_instances': 3, 'duplicate_rim_pictures': 0,
              'added_characters': len(ADDITION), 'old_height': old_height,
              'edited_height': int(state(edited)[2].find(HP+'sz').get('height')),
              'negative_cases_rejected': 9, 'bitmap_ownership_cases': 5,
              'partial_frame_rejected_without_mutation': True, 'edit_and_resave': True,
              'long_edits': long_edits}
    (folder/'report.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print('NATIVE_BACKGROUND_FRAME_FLOW_OK', result)
    return result


if __name__ == '__main__':
    if not (ROOT/'data/external_exam_qa/2026_june_high1/english.pdf').exists():
        print('SKIP: external English PDF is unavailable')
        raise SystemExit(2)
    with tempfile.TemporaryDirectory(prefix='background_frame_flow_') as tmp:
        verify(Path(tmp))
