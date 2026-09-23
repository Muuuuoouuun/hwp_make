"""Real mixed grid notice: native paragraph ownership, edits, and layout."""
from collections import Counter
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import zipfile

from lxml import etree
import numpy as np
from PIL import Image
import rhwp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.hwpx_writer_v2 import HwpxDocument
from app.pdf_editability import inspect_pdf_editability
from app.pdf_layout_writer import write_pdf_structured_hwpx
from app.pdf_native_content import extract_native_content
from app.pdf_question_rendering import inspect_question_rendering
from app.pdf_table_paragraphs import restore_table_paragraphs
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools.package_validator import validate_package

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'


def _package(path):
    with zipfile.ZipFile(path) as archive:
        header = etree.fromstring(archive.read('Contents/header.xml'))
        sections = [etree.fromstring(archive.read(name)) for name in archive.namelist()
                    if re.fullmatch(r'Contents/section\d+\.xml', name)]
        bitmaps = Counter(hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()
                          if name.startswith('BinData/'))
    question = next(draw for root in sections for draw in root.iter(HP+'drawText')
                    if draw.get('name') == 'question:v1:q27')
    tables = question.findall('.//'+HP+'tbl')
    assert len(tables) == 3 and [(t.get('rowCnt'),t.get('colCnt')) for t in tables] == [
        ('1','1'),('3','2'),('1','1')]
    paragraphs = [[p for p in table.iter(HP+'p')
                   if ''.join(t.text or '' for t in p.iter(HP+'t'))] for table in tables]
    return header, question, tables, paragraphs, bitmaps


def verify(folder, source=None, native=None, provenance=None):
    source = source or ROOT/'data/external_exam_qa/2026_june_high1/english.pdf'
    if not source.is_file():
        print('SKIP: real English exam PDF is unavailable')
        return False
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if native is None:
        native = folder/'english.hwpx'
        stats = write_pdf_structured_hwpx(source,native,native_math=True)
        provenance = stats['image_provenance']
    if provenance is None:
        _,provenance = extract_native_content(source)
    items,_ = extract_native_content(source,max_pages=4)
    fragments = [item for item in items if item.get('source_page') == 4
                 and item['layout'].get('source_frame_has_grid')]
    assert len(fragments) == 2 and all(item['layout'].get('question_number') == 27 for item in fragments)
    assert not any(item['layout'].get('source_frame_has_grid')
                   for item in items if item['layout'].get('question_number') == 28)

    audit = inspect_pdf_editability(source,native,provenance,require_question_boxes=True)
    assert audit['ok'],audit['issues']
    assert inspect_question_rendering(native,rhwp)['ok']
    header,question,tables,groups,bitmaps = _package(native)
    assert [len(group) for group in groups] == [7,6,5]
    assert [len(p.findall(HP+'linesegarray/'+HP+'lineseg')) for p in groups[0]] == [1,2,1,1,1,1,1]
    assert not any(t.findall('.//'+HP+'lineBreak') for t in tables)
    values = [''.join(t.text or '' for t in p.iter(HP+'t')) for group in groups for p in group]
    assert values.count('∙ Limited to 50 students') == 1
    assert sum(value.startswith('∙ ') for value in values) == 5

    # A false PDF line must leave this real fragment and its style header intact.
    bad = deepcopy(fragments[0]['layout'])
    bad['source_typography']['lines'][0]['text'] += ' wrong'
    probe, header_copy = deepcopy(tables[0].getparent().getparent()), deepcopy(header)
    before = etree.tostring(probe),etree.tostring(header_copy)
    def forbidden_style(*_args):
        raise AssertionError('invalid source allocated a paragraph style')
    page_width = float(next(root for root in question.iterancestors()
                            if root.find('.//'+HP+'pagePr') is not None).find('.//'+HP+'pagePr').get('width'))
    assert restore_table_paragraphs(probe,bad,header_copy,page_width,forbidden_style) == 0
    assert before == (etree.tostring(probe),etree.tostring(header_copy))

    document = HwpxDocument.open(native)
    changed = False
    for section in document.sections:
        for draw in section.element.iter(HP+'drawText'):
            if draw.get('name') != 'question:v1:q27':
                continue
            for p in draw.iter(HP+'p'):
                editable = HwpxOxmlParagraph(p,section)
                if editable.text == '∙ Limited to 50 students':
                    editable.text = '∙ Limited to 60 students'
                    changed = True
                    break
    assert changed
    edited = folder/'english_bullet_edited.hwpx'
    document.save(edited)
    assert validate_package(edited).ok
    _,_,_,edited_groups,edited_bitmaps = _package(edited)
    assert bitmaps == edited_bitmaps
    edited_values = [''.join(t.text or '' for t in p.iter(HP+'t'))
                     for group in edited_groups for p in group]
    assert [len(group) for group in edited_groups] == [7,6,5]
    assert edited_values.count('∙ Limited to 60 students') == 1
    assert sum(value.startswith('∙ ') for value in edited_values) == 5
    assert inspect_question_rendering(edited,rhwp)['ok']
    original_render, edited_render = rhwp.parse(str(native)),rhwp.parse(str(edited))
    assert original_render.page_count == edited_render.page_count == 8
    before_pixels = np.asarray(Image.open(io.BytesIO(bytes(original_render.render_png(3)))).convert('RGB'))
    after_pixels = np.asarray(Image.open(io.BytesIO(bytes(edited_render.render_png(3)))).convert('RGB'))
    changed_pixels = int(np.count_nonzero(np.any(before_pixels != after_pixels, axis=-1)))
    assert 0 < changed_pixels < 500, changed_pixels
    report = {'ok':True,'question':27,'source_grid_fragments':2,
              'native_tables':3,'paragraphs_per_table':[7,6,5],
              'wrapped_prose_lines_in_one_paragraph':2,
              'editable_bullets':5,'changed_bullet':'50 -> 60 students',
              'source_mismatch_rejected':True,'edit_resave_stable':True,
              'bitmaps_unchanged':True,'pages':8,'edited_page_changed_pixels':changed_pixels}
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('NATIVE_GRID_FRAME_FRAGMENTS_OK: '+json.dumps(report,ensure_ascii=False))
    return True


if __name__=='__main__':
    if len(sys.argv) == 2:
        success = verify(Path(sys.argv[1]))
    else:
        with tempfile.TemporaryDirectory(prefix='native_grid_frame_') as directory:
            success = verify(Path(directory))
    if not success:
        sys.exit(2)
