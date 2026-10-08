"""Independent actual-source cache reversion and digest-valid forgery guards."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app.hwpx_writer_v2
from app.hwpx_writer_v2 import HwpxDocument
from app.pdf_wrapped_prose_frames import source_flow_wrapped_prose_frame_table
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools.paragraph_floats import HP, HH, WRAPPED_CELL
from hwpx.tools.wrapped_flow_state import (LINE_KEYS, begin, cache_integrity, decode, encode,
                                          finish, restore_cached_cell, seed)

HC = '{http://www.hancom.co.kr/hwpml/2011/core}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hwpx', type=Path)
    parser.add_argument('--source', type=Path, default=ROOT/'data/external_exam_qa/2026_september_high2/english.pdf')
    parser.add_argument('--report', type=Path, default=ROOT/'tmp/renderer-square/cache-snapshot-independent/independent-report.json')
    args = parser.parse_args()
    if args.hwpx is None or not args.hwpx.is_file() or not args.source.is_file():
        print('SKIP: actual source PDF and native --hwpx fixture required')
        return 2
    code_paths = [ROOT/'app/_vendor/hwpx/tools'/name for name in
                  ('wrapped_flow_state.py', 'paragraph_floats.py', 'question_reflow.py', 'wrapped_cache_metrics.py')]
    before_code = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths}
    with zipfile.ZipFile(args.hwpx) as package:
        header = etree.fromstring(package.read('Contents/header.xml'))
        manifest = etree.fromstring(package.read('Contents/content.hpf'))
        hrefs = {node.get('id'): node.get('href') for node in manifest.iter() if node.get('href')}
        sections = [etree.fromstring(package.read(name)) for name in package.namelist()
                    if name.startswith('Contents/section') and name.endswith('.xml')]
        root = next(root for root in sections if any(c.get('name', '').startswith(WRAPPED_CELL)
                                                    for c in root.iter(HP+'tc')))

        def cell_of(root):
            return next(cell for cell in root.iter(HP+'tc')
                        if cell.get('name', '').startswith(WRAPPED_CELL))

        cell = cell_of(root)
        assert source_flow_wrapped_prose_frame_table(cell.getparent().getparent(), root,
                                                     header, hrefs, package, args.source), 'independent initial PDF/native proof'
    styles = {p.get('id'): p for p in header.iter(HH+'paraPr')}
    chars = {p.get('id'): p for p in header.iter(HH+'charPr')}
    # Regenerate the snapshot only after the independent actual source proof.
    cell.set('name', WRAPPED_CELL)
    assert seed(root, cell, styles, chars)
    assert decode(cell.get('name'))['v'] == 2

    def context():
        copied_root, copied_header = deepcopy(root), deepcopy(header)
        cell = cell_of(copied_root)
        paragraphs = cell.findall(HP+'subList/'+HP+'p')
        paragraphs[0].remove(paragraphs[0].find(HP+'linesegarray'))
        para_styles = {p.get('id'): p for p in copied_header.iter(HH+'paraPr')}
        char_styles = {p.get('id'): p for p in copied_header.iter(HH+'charPr')}
        return copied_root, copied_header, cell, paragraphs, para_styles, char_styles

    positives, negatives, failures = [], [], []
    cache_vectors = lambda paragraphs: [[dict(line.attrib) for line in p.findall(HP+'linesegarray/'+HP+'lineseg')]
                                         for p in paragraphs]
    original_caches = cache_vectors(cell.findall(HP+'subList/'+HP+'p'))
    for label in ('exact_reverted_content', 'empty_added_run', 'manual_root_page_break', 'staged_table_copy_restore'):
        r, h, c, paragraphs, ps, cs = context()
        if label == 'empty_added_run':
            etree.SubElement(etree.SubElement(paragraphs[1], HP+'run', charPrIDRef=paragraphs[1].find(HP+'run').get('charPrIDRef')), HP+'t').text = ''
        elif label == 'manual_root_page_break':
            r.findall(HP+'p')[-1].set('pageBreak', '1'); r.findall(HP+'p')[-1].set('columnBreak', '0')
            history = begin(r, ps, cs)
            assert history is not None and history['state']['base'][-1] == ['1', '0']
        elif label == 'staged_table_copy_restore':
            # The real save path stages this table, not the whole section.
            # Its unused inherited namespaces may disappear in deepcopy.
            staged = deepcopy(c.getparent().getparent())
            c = staged.find(HP+'tr/'+HP+'tc')
            paragraphs = c.findall(HP+'subList/'+HP+'p')
        flags_before = [(p.get('pageBreak'), p.get('columnBreak')) for p in r.findall(HP+'p')]
        accepted = restore_cached_cell(c, ps, cs)
        if not accepted:
            failures.append('positive_'+label)
            continue
        assert cache_vectors(paragraphs) == original_caches, label
        assert [(p.get('pageBreak'), p.get('columnBreak')) for p in r.findall(HP+'p')] == flags_before, label
        positives.append(label)

    # Use the actual persisted snapshot through the public document parser.
    # Re-seeding raw etree below/above cannot detect header normalization that
    # changes resolved style/fontface fingerprints during the real save path.
    public_open_stage = {}
    with HwpxDocument.open(args.hwpx) as document:
        public_header = document.headers[0].element
        section = next(s for s in document.sections
                       if any(c.get('name', '').startswith(WRAPPED_CELL)
                              for c in s.element.iter(HP+'tc')))
        public_cell = cell_of(section.element)
        persisted_name = public_cell.get('name')
        persisted_state = decode(persisted_name)
        public_ps = {p.get('id'): p for p in public_header.iter(HH+'paraPr')}
        public_cs = {p.get('id'): p for p in public_header.iter(HH+'charPr')}
        public_paragraphs = public_cell.findall(HP+'subList/'+HP+'p')
        public_original_caches = cache_vectors(public_paragraphs)
        public_flags = [(p.get('pageBreak'), p.get('columnBreak'))
                        for p in section.element.findall(HP+'p')]
        target = public_paragraphs[0]
        HwpxOxmlParagraph(target, section).add_run(
            '', char_pr_id_ref=target.find(HP+'run').get('charPrIDRef'))
        invalidated = target.find(HP+'linesegarray') is None
        staged = deepcopy(public_cell.getparent().getparent())
        staged_cell = staged.find(HP+'tr/'+HP+'tc')
        accepted = restore_cached_cell(staged_cell, public_ps, public_cs)
        exact_caches = (cache_vectors(staged_cell.findall(HP+'subList/'+HP+'p'))
                        == public_original_caches == original_caches)
        public_open_stage = {
            'stored_snapshot_used_without_reseed': staged_cell.get('name') == persisted_name,
            'snapshot_version': persisted_state['v'],
            'public_empty_run_invalidated_cache': invalidated,
            'staged_restore_accepted': accepted,
            'cache_vectors_equal_actual_input': exact_caches,
            'root_breaks_unchanged': public_flags == [
                (p.get('pageBreak'), p.get('columnBreak'))
                for p in section.element.findall(HP+'p')],
        }
        if (persisted_state['v'] == 2 and invalidated and accepted and exact_caches
            and public_open_stage['stored_snapshot_used_without_reseed']
            and public_open_stage['root_breaks_unchanged']):
            positives.append('public_document_open_staged_table_restore')
        else:
            failures.append('positive_public_document_open_staged_table_restore')

    # Synthetic native isolation check; only the first cell's actual source
    # provenance is claimed. A second cell's snapshot must not be overwritten.
    multi_root, multi_header = deepcopy(root), deepcopy(header)
    ps = {p.get('id'): p for p in multi_header.iter(HH+'paraPr')}
    cs = {p.get('id'): p for p in multi_header.iter(HH+'charPr')}
    first = cell_of(multi_root)
    owner = next(p for p in first.iterancestors() if p.getparent() is multi_root)
    other_owner = deepcopy(owner); other_owner.set('id', '900001'); multi_root.append(other_owner)
    for index, p in enumerate(other_owner.iter(HP+'p')): p.set('id', str(910000+index))
    second = next(c for c in other_owner.iter(HP+'tc') if c.get('name', '').startswith(WRAPPED_CELL))
    second.find('.//'+HP+'pic').set('id', '990001')
    for c in (first, second):
        c.set('name', WRAPPED_CELL)
        assert seed(multi_root, c, ps, cs)
    second_snapshot = decode(second.get('name'))['cache']
    p = first.find(HP+'subList/'+HP+'p'); cache = p.find(HP+'linesegarray'); p.remove(cache)
    history = begin(multi_root, ps, cs); assert history is not None
    p.append(cache); finish(multi_root, history, ps, cs)
    same_snapshot = decode(second.get('name'))['cache'] == second_snapshot
    p = second.find(HP+'subList/'+HP+'p'); p.remove(p.find(HP+'linesegarray'))
    if same_snapshot and restore_cached_cell(second, ps, cs):
        positives.append('untouched_second_cell_own_snapshot_preserved')
    else:
        failures.append('positive_untouched_second_cell_own_snapshot_preserved')

    cases = ('changed_text', 'changed_utf16_content', 'char_height', 'char_ratio', 'char_spacing',
             'char_bold', 'para_indent', 'para_line_spacing', 'fontface_change', 'fontface_addition',
             'cell_width', 'cell_padding', 'picture_offset', 'picture_width', 'picture_reference',
             'nested_id_change', 'nested_id_order', 'generic_cell', 'math_control',
             'forged_line_removal', 'forged_first_offset', 'forged_mid_offset',
             'forged_negative_descender', 'forged_zero_descender', 'forged_shared_mask',
             'forged_oversized_band', 'forged_offset_beyond_text')
    for label in cases:
        r, h, c, paragraphs, ps, cs = context()
        first = paragraphs[0]
        char = cs[first.find(HP+'run').get('charPrIDRef')]
        para = ps[first.get('paraPrIDRef')]
        picture = c.find('.//'+HP+'pic')
        if label == 'changed_text': first.find(HP+'run/'+HP+'t').text += ' changed'
        elif label == 'changed_utf16_content': first.find(HP+'run/'+HP+'t').text += '\U0001f331'
        elif label == 'char_height': char.set('height', str(int(char.get('height'))+1))
        elif label in ('char_ratio', 'char_spacing'):
            value = char.find(HH+('ratio' if label=='char_ratio' else 'spacing'))
            key = 'latin'; value.set(key, str(int(value.get(key))+1))
        elif label == 'char_bold':
            bold = char.find(HH+'bold')
            if bold is None: etree.SubElement(char, HH+'bold')
            else: char.remove(bold)
        elif label == 'para_indent':
            value = para.find('.//'+HC+'intent'); value.set('value', str(int(value.get('value'))+1))
        elif label == 'para_line_spacing':
            value = para.find('.//'+HH+'lineSpacing'); value.set('value', str(int(value.get('value'))+1))
        elif label == 'fontface_change': next(h.iter(HH+'font')).set('face', 'Independent changed face')
        elif label == 'fontface_addition':
            face = next(h.iter(HH+'fontface')); font = deepcopy(face.find(HH+'font')); font.set('id', '9999'); font.set('face', 'Independent added face'); face.append(font)
        elif label == 'cell_width': c.find(HP+'cellSz').set('width', str(int(c.find(HP+'cellSz').get('width'))+1))
        elif label == 'cell_padding': c.find(HP+'cellMargin').set('left', str(int(c.find(HP+'cellMargin').get('left'))+1))
        elif label == 'picture_offset': picture.find(HP+'pos').set('vertOffset', str(int(picture.find(HP+'pos').get('vertOffset'))+1))
        elif label == 'picture_width': picture.find(HP+'sz').set('width', str(int(picture.find(HP+'sz').get('width'))+1))
        elif label == 'picture_reference': picture.find(HC+'img').set('binaryItemIDRef', 'independent-other-image')
        elif label == 'nested_id_change': first.set('id', 'independent-other-id')
        elif label == 'nested_id_order': first.getparent().insert(0, paragraphs[-1])
        elif label == 'generic_cell': c.set('name', '')
        elif label == 'math_control': etree.SubElement(first.find(HP+'run'), HP+'equation')
        else:
            state = decode(c.get('name'))
            cache = state['cache']['paragraphs']
            if label == 'forged_line_removal': cache[1][2].pop(1)
            elif label == 'forged_first_offset': cache[0][2][0][0] = 1
            elif label == 'forged_mid_offset': cache[1][2][1][0] += 1
            elif label == 'forged_negative_descender': cache[0][2][0][4] = cache[0][2][0][3]
            elif label == 'forged_zero_descender': cache[0][2][0][4] = 0
            elif label == 'forged_shared_mask': cache[1][2][-1][7] = 22430
            elif label == 'forged_oversized_band': cache[0][2][0][2] = cache[0][2][0][3] = 200000
            elif label == 'forged_offset_beyond_text': cache[0][2][0][0] = 100000
            state['cache']['integrity'] = cache_integrity(state['cache'])
            c.set('name', encode(state))  # both valid hashes; neither proves provenance
        before = (etree.tostring(r), etree.tostring(h))
        accepted = restore_cached_cell(c, ps, cs)
        unchanged = before == (etree.tostring(r), etree.tostring(h))
        outcome = {'case': label, 'restore_accepted': accepted, 'rejection_unchanged': unchanged}
        negatives.append(outcome)
        if accepted or not unchanged: failures.append(label)
    after_code = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths}
    if before_code != after_code: failures.append('product_changed_during_check')
    result = {'ok': not failures, 'failures': failures, 'positives': positives, 'negatives': negatives,
              'actual_initial_source_proof': True, 'stable_code': before_code == after_code,
              'public_document_open_staged_restore': public_open_stage,
              'code_hashes': after_code, 'input_sha256': hashlib.sha256(args.hwpx.read_bytes()).hexdigest(),
              'public_save_render_tested_here': False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print('WRAPPED_SOURCE_CACHE_STATE', json.dumps(result, ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
