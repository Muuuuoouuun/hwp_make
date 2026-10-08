"""Oversized native answer areas retain height, text and edit/save behavior."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fitz
from lxml import etree
import rhwp
from app.hwpx_writer_v2 import HwpxDocument
from app.pdf_layout_writer import write_pdf_structured_hwpx
from app.pdf_question_geometry import inspect_question_geometry
from app.recognition.pipeline import recognize_pdf
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools.question_spacing import (HP, HH, MAX_MARGIN, ParagraphSpacingStyles,
                                        arrange_question_gaps, paragraph_spacing)
from scripts.verify_native_shared_table_paragraphs import tokens


def read_package(path):
    with zipfile.ZipFile(path) as archive:
        payload = {n: archive.read(n) for n in archive.namelist()}
    header = etree.fromstring(payload['Contents/header.xml'])
    sections = {n: etree.fromstring(data) for n, data in payload.items()
                if re.fullmatch(r'Contents/section\d+\.xml', n)}
    return payload, header, sections


def native_content(sections):
    """The semantic nodes must survive whitespace conversion byte-for-byte."""
    return [etree.tostring(node) for section in sections.values() for node in section.iter()
            if node.tag in {HP+'t', HP+'equation', HP+'pic', HP+'tbl'}]


def verify_package(path, count):
    payload, header, sections = read_package(path)
    boxes = [d for s in sections.values() for d in s.iter(HP+'drawText')
             if d.get('name', '').startswith('question:')]
    assert len(boxes) == count
    styles = ParagraphSpacingStyles(header).styles
    for draw in boxes:
        assert inspect_question_geometry(draw)['ok'], draw.get('name')
        assert all(0 <= float(draw.find(HP+'textMargin').get(e)) <= MAX_MARGIN
                   for e in ('top', 'bottom'))
        assert all(p.get('paraPrIDRef') in styles for p in draw.iter(HP+'p'))
    return payload, header, sections, boxes


def synthetic(folder):
    source = folder/'ordinary-source.pdf'
    native = folder/'ordinary-native.hwpx'
    with fitz.open() as pdf:
        page = pdf.new_page(width=841, height=1190)
        page.insert_text((90, 100), 'Native whitespace regression')
        page.insert_text((88, 200), '1. Ordinary native editable question.')
        page.insert_text((436, 200), '2. A second native editable question.')
        pdf.save(source)
    write_pdf_structured_hwpx(source, native)
    payload, header, sections, boxes = verify_package(native, 2)
    section = next(s for s in sections.values() if boxes[1] in list(s.iter(HP+'drawText')))
    draw = boxes[1]
    shape = draw.getparent()
    host = shape.getparent().getparent()
    last = draw.findall(HP+'subList/'+HP+'p')[-1]
    spacing = ParagraphSpacingStyles(header)
    before, after = paragraph_spacing(host, spacing.styles)
    gap = MAX_MARGIN + 2035  # The actual high2 mathematics terminal answer area.
    spacing.set(host, before, after + gap)
    old_height = int(shape.find(HP+'sz').get('height'))
    old_text_height = int(draw.find(HP+'subList').get('textHeight'))
    old_bottom = int(draw.find(HP+'textMargin').get('bottom'))
    old_inner = paragraph_spacing(last, spacing.styles)
    semantic = native_content(sections)
    cached = [etree.tostring(p.find(HP+'linesegarray')) for p in draw.findall(HP+'subList/'+HP+'p')]
    expected_inner = old_inner[1] + max(0, old_bottom + gap - MAX_MARGIN)
    assert arrange_question_gaps(section, header) > 0
    styles = ParagraphSpacingStyles(header).styles
    assert int(shape.find(HP+'sz').get('height')) == old_height + gap
    assert int(draw.find(HP+'textMargin').get('bottom')) == MAX_MARGIN
    assert int(draw.find(HP+'subList').get('textHeight')) == old_text_height + expected_inner-old_inner[1]
    assert paragraph_spacing(last, styles) == (old_inner[0], expected_inner)
    assert paragraph_spacing(host, styles) == (0, 0)
    assert native_content(sections) == semantic
    assert cached == [etree.tostring(p.find(HP+'linesegarray')) for p in draw.findall(HP+'subList/'+HP+'p')]
    state = etree.tostring(section), etree.tostring(header)
    assert arrange_question_gaps(section, header) == 0
    assert state == (etree.tostring(section), etree.tostring(header))
    # Ordinary paragraphs are outside the question-padding transformation.
    plain = etree.Element(HP+'p', paraPrIDRef=last.get('paraPrIDRef'))
    normal = etree.Element(section.tag, nsmap=section.nsmap)
    normal.append(plain)
    original = etree.tostring(normal), etree.tostring(header)
    assert arrange_question_gaps(normal, header) == 0
    assert original == (etree.tostring(normal), etree.tostring(header))
    # Unsupported leading overflow is still rejected, rather than clamped.
    bad_section, bad_header = deepcopy(section), deepcopy(header)
    bad_host = next(d for d in bad_section.iter(HP+'drawText')
                    if d.get('name') == draw.get('name')).getparent().getparent().getparent()
    ParagraphSpacingStyles(bad_header).set(bad_host, MAX_MARGIN+1, 0)
    try:
        arrange_question_gaps(bad_section, bad_header)
    except ValueError as exc:
        assert 'native text-margin range' in str(exc)
    else:
        raise AssertionError('Unsupported oversized leading padding was silently accepted')
    for name, s in sections.items():
        payload[name] = etree.tostring(s, encoding='utf8', xml_declaration=True)
    payload['Contents/header.xml'] = etree.tostring(header, encoding='utf8', xml_declaration=True)
    preserved = folder/'ordinary-trailing-space.hwpx'
    with zipfile.ZipFile(preserved, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in payload.items():
            archive.writestr(name, data)
    verify_package(preserved, 2)
    assert rhwp.parse(str(preserved)).page_count == 1
    assert tokens(native) == tokens(preserved), 'Whitespace changed the content origin'
    prior = preserved
    for label, text in [('grow', '2. A second native editable question.' + ' Additional detail remains editable.'*8),
                        ('shrink', '2. Short editable question.')]:
        document = HwpxDocument.open(prior)
        doc_section, edited = next((s,d) for s in document.sections for d in s.element.iter(HP+'drawText')
                                  if d.get('name') == 'question:v1:q02')
        p = edited.find(HP+'subList/'+HP+'p')
        original_after = paragraph_spacing(p, ParagraphSpacingStyles(document.headers[0].element).styles)
        HwpxOxmlParagraph(p, doc_section).text = text
        target = folder/f'ordinary-{label}.hwpx'
        document.save_to_path(target)
        _, h, _, edited_boxes = verify_package(target, 2)
        current = next(d for d in edited_boxes if d.get('name') == 'question:v1:q02')
        assert paragraph_spacing(current.find(HP+'subList/'+HP+'p'), ParagraphSpacingStyles(h).styles) == original_after
        assert rhwp.parse(str(target)).page_count == 1
        assert re.sub(r'\s+', '', text) in ''.join(t[0] for t in tokens(target))
        reopened = folder/f'ordinary-{label}-reopened.hwpx'
        HwpxDocument.open(target).save_to_path(reopened)
        assert tokens(target) == tokens(reopened)
        assert read_package(target)[2].keys() == read_package(reopened)[2].keys()
        prior = reopened
    return {'synthetic': 'PASS', 'retained_trailing_space_hwp': expected_inner}


def actual(folder):
    inventory = json.loads((ROOT/'tmp/september-exam-matrix/stable-all-51-20261007-final/source_inventory.json').read_text(encoding='utf8'))
    result = []
    for case in inventory['cases']:
        if case['area'] != '수학':
            continue
        path = Path(case['source'])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == case['sha256']
        expected = Counter((p['physical_page'], m['number']) for p in case['pages'] for m in p['question_markers'])
        recognized = recognize_pdf(path.read_bytes(), filename='neutral.pdf')
        assert Counter((p.page_number,p.number) for p in recognized.problems) == expected
        target = folder/f"{case['id']}.hwpx"
        stats = write_pdf_structured_hwpx(path, target, native_math=True)
        assert stats['source_pages'] == case['physical_pages']
        assert stats['source_problem_count'] == stats['output_problem_count'] == sum(expected.values())
        assert stats['question_grouping']['inventory_matches']
        assert stats['full_page_images'] == stats['text_visual_overlays'] == stats['math_visual_overlays'] == 0
        _, header, sections, boxes = verify_package(target, sum(expected.values()))
        initial_count = rhwp.parse(str(target)).page_count
        reopened = target.with_name(target.stem+'-reopened.hwpx')
        HwpxDocument.open(target).save_to_path(reopened)
        _, _, saved_sections, _ = verify_package(reopened, sum(expected.values()))
        assert native_content(sections) == native_content(saved_sections), 'Save altered native mathematical content'
        assert tokens(target) == tokens(reopened), 'Save changed actual painted glyph baselines'
        assert rhwp.parse(str(reopened)).page_count == initial_count
        if case['id'] == '2026_september_high2__math':
            original_scripts = [n.text for s in sections.values() for n in s.iter(HP+'script')]
            document = HwpxDocument.open(target)
            edited_draw = next(d for s in document.sections for d in s.element.iter(HP+'drawText')
                               if d.get('name') == 'question:v1:q30')
            edited_body = edited_draw.findall(HP+'subList/'+HP+'p')
            tail = paragraph_spacing(edited_body[-1], ParagraphSpacingStyles(header).styles)[1]
            assert tail > 0, 'Actual source must exercise the oversized trailing answer area'
            paragraph = next(p for p in reversed(edited_body) if any((t.text or '').strip() for t in p.findall(HP+'run/'+HP+'t')))
            text_node = paragraph.findall(HP+'run/'+HP+'t')[-1]
            text_node.text = (text_node.text or '') + ' Additional condition.'
            cache = paragraph.find(HP+'linesegarray')
            if cache is not None:
                paragraph.remove(cache)
            edited_target = target.with_name(target.stem+'-edited.hwpx')
            document.save_to_path(edited_target)
            _, edited_header, edited_sections, edited_boxes = verify_package(edited_target, sum(expected.values()))
            assert [n.text for s in edited_sections.values() for n in s.iter(HP+'script')] == original_scripts
            current = next(d for d in edited_boxes if d.get('name') == 'question:v1:q30')
            assert paragraph_spacing(current.findall(HP+'subList/'+HP+'p')[-1], ParagraphSpacingStyles(edited_header).styles)[1] == tail
            assert rhwp.parse(str(edited_target)).page_count == initial_count
            edited_reopen = target.with_name(target.stem+'-edited-reopened.hwpx')
            HwpxDocument.open(edited_target).save_to_path(edited_reopen)
            assert tokens(edited_target) == tokens(edited_reopen)
            assert native_content(edited_sections) == native_content(read_package(edited_reopen)[2])
        result.append({'id':case['id'],'recognized':sum(expected.values()), 'source_pages':case['physical_pages'],
                       'native_pages':initial_count, 'native_equations':stats['native_equations'],
                       'source_text_preservation_ratio':stats['source_text_preservation_ratio'],
                       'quality_pass':False,'output':str(target)})
        print('ACTUAL_WRITE_AND_REOPEN_OK',case['id'],initial_count,flush=True)
    assert len(result) == 5
    return result


def main():
    folder = Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'tmp/native-question-trailing-whitespace'
    folder.mkdir(parents=True, exist_ok=True)
    report = synthetic(folder)
    report['actual'] = actual(folder)
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('NATIVE_QUESTION_TRAILING_WHITESPACE_OK: source inventory, native math, occupied height, growth/deletion and stable saves')


if __name__ == '__main__':
    main()
