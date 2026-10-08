"""Independent portable-break state checks using a real native wrapped cell.

This tests bookkeeping and fail-closed scope. Actual public edit/save/render
is a separate gate; serializing XML here is not reported as that gate.
"""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app.hwpx_writer_v2  # expose bundled tools
from hwpx.tools.paragraph_floats import HP, HH, WRAPPED_CELL, wrapped_cell_layout
from hwpx.tools.wrapped_flow_state import PREFIX, begin, decode, finish, flags


def encode(value):
    raw = json.dumps(value, separators=(',', ':')).encode('utf8')
    return PREFIX + hashlib.sha256(raw).hexdigest() + ':' + base64.urlsafe_b64encode(raw).decode()


def independent_slots(paragraphs, pairs):
    slot = 0
    result = {}
    for paragraph, (page, column) in zip(paragraphs, pairs):
        if page == '1':
            slot = (slot // 2 + 1) * 2
        elif column == '1':
            slot += 1
        result[paragraph] = slot
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hwpx', type=Path)
    parser.add_argument('--report', type=Path, default=ROOT/'tmp/renderer-square/break-state-review.json')
    args = parser.parse_args()
    if args.hwpx is None or not args.hwpx.is_file():
        print('SKIP: pass --hwpx with an actual wrapped-cell native fixture')
        return 2
    reviewed_files = [ROOT/'app/_vendor/hwpx/tools'/name for name in
                      ('wrapped_flow_state.py', 'paragraph_floats.py', 'question_reflow.py', 'wrapped_cache_metrics.py')]
    code_before = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in reviewed_files}
    with zipfile.ZipFile(args.hwpx) as package:
        header = etree.fromstring(package.read('Contents/header.xml'))
        sections = [etree.fromstring(package.read(name)) for name in package.namelist()
                    if name.startswith('Contents/section') and name.endswith('.xml')]
    root = next(root for root in sections if any(cell.get('name', '').startswith(WRAPPED_CELL)
                                               for cell in root.iter(HP+'tc')))
    styles = {node.get('id'): node for node in header.iter(HH+'paraPr')}
    chars = {node.get('id'): node for node in header.iter(HH+'charPr')}
    checks = []

    def cell_of(root):
        return next(cell for cell in root.iter(HP+'tc')
                    if cell.get('name', '').startswith(WRAPPED_CELL))

    def dirty(root):
        paragraph = cell_of(root).find(HP+'subList/'+HP+'p')
        cache = paragraph.find(HP+'linesegarray')
        if cache is not None:
            paragraph.remove(cache)
        return paragraph, cache

    def reject(root, label):
        before = etree.tostring(root)
        assert begin(root, styles, chars) is None, label
        assert etree.tostring(root) == before, (label, 'mutated XML while rejecting')
        checks.append(label)

    assert wrapped_cell_layout(cell_of(root), styles, char_styles=chars) is not None
    reject(deepcopy(root), 'unchanged_document_no_override')
    initial = deepcopy(root)
    paragraph, cache = dirty(initial)
    before = etree.tostring(initial)
    context = begin(initial, styles, chars)
    assert context is not None and etree.tostring(initial) == before
    paragraphs = initial.findall(HP+'p')
    baseline = flags(paragraphs)
    assert context['state']['base'] == baseline
    assert context['slots'] == independent_slots(paragraphs, baseline)
    checks.append('initial_exact_break_slots_without_mutation')
    paragraph.append(cache)
    owner = next(node for node in cell_of(initial).iterancestors() if node.getparent() is initial)
    target_index = paragraphs.index(owner) + 1
    assert target_index < len(paragraphs), 'fixture needs a following question'
    target = paragraphs[target_index]
    target.set('pageBreak', '1'); target.set('columnBreak', '0')
    finish(initial, context, styles, chars)
    stored = decode(cell_of(initial).get('name'))
    assert stored['base'] == baseline and stored['last'] == flags(paragraphs)
    checks.append('generated_breaks_recorded_separately_from_baseline')

    # Reopening must recover the same base even though the generated output
    # now contains an additional page break.
    reopened = etree.fromstring(etree.tostring(initial))
    p, original_cache = dirty(reopened)
    resumed = begin(reopened, styles, chars)
    assert resumed is not None and resumed['state']['base'] == baseline
    assert resumed['slots'] == independent_slots(reopened.findall(HP+'p'), baseline)
    checks.append('serialized_generated_break_not_promoted_to_baseline')

    for pair, label in [(['0', '1'], 'manual_column_change_preserved'),
                        (['0', '0'], 'manual_generated_page_break_removal_preserved')]:
        manual = deepcopy(reopened)
        target = manual.findall(HP+'p')[target_index]
        target.set('pageBreak', pair[0]); target.set('columnBreak', pair[1])
        result = begin(manual, styles, chars)
        expected = deepcopy(baseline); expected[target_index] = pair
        assert result is not None and result['state']['base'] == expected, label
        assert result['slots'] == independent_slots(manual.findall(HP+'p'), expected)
        checks.append(label)

    manual = deepcopy(reopened)
    owner_index = target_index - 1
    manual_owner = manual.findall(HP+'p')[owner_index]
    manual_owner.set('pageBreak', '1'); manual_owner.set('columnBreak', '0')
    result = begin(manual, styles, chars)
    expected = deepcopy(baseline); expected[owner_index] = ['1', '0']
    assert result is not None and result['state']['base'] == expected
    assert result['slots'] == independent_slots(manual.findall(HP+'p'), expected)
    checks.append('manual_page_break_added_to_owner_preserved')

    # A second generated save and a deletion/save must retain the initial
    # ordered baseline, rather than making the first automatic break permanent.
    p.append(original_cache)
    finish(reopened, resumed, styles, chars)
    deleted = etree.fromstring(etree.tostring(reopened))
    p, original_cache = dirty(deleted)
    deletion = begin(deleted, styles, chars)
    assert deletion is not None and deletion['state']['base'] == baseline
    p.append(original_cache)
    for node, pair in zip(deleted.findall(HP+'p'), baseline):
        node.set('pageBreak', pair[0]); node.set('columnBreak', pair[1])
    finish(deleted, deletion, styles, chars)
    final = decode(cell_of(deleted).get('name'))
    assert final['base'] == baseline and final['last'] == baseline
    checks.append('two_generated_saves_and_deletion_keep_original_baseline')

    negative_base = deepcopy(initial)
    dirty(negative_base)
    for label in ('generic_dirty', 'ordinary_table_dirty', 'math_control_dirty',
                  'invalid_manual_break', 'reordered_ids', 'removed_paragraph',
                  'new_paragraph', 'duplicate_id', 'missing_id', 'picture_page_anchor',
                  'overlapping_cached_band'):
        changed = deepcopy(negative_base)
        cell = cell_of(changed)
        if label == 'generic_dirty':
            generic = changed.findall(HP+'p')[-1]
            cache = generic.find(HP+'linesegarray')
            if cache is not None: generic.remove(cache)
        elif label == 'ordinary_table_dirty': cell.set('name', '')
        elif label == 'math_control_dirty': etree.SubElement(cell.find(HP+'subList/'+HP+'p/'+HP+'run'), HP+'equation')
        elif label == 'invalid_manual_break':
            changed.findall(HP+'p')[target_index].set('columnBreak', '1')
        elif label == 'reordered_ids': changed.insert(0, changed.findall(HP+'p')[-1])
        elif label == 'removed_paragraph': changed.remove(changed.findall(HP+'p')[-1])
        elif label == 'new_paragraph':
            new = deepcopy(changed.findall(HP+'p')[-1]); new.set('id', 'independent-added'); changed.append(new)
        elif label == 'duplicate_id': changed.findall(HP+'p')[-1].set('id', changed.findall(HP+'p')[0].get('id'))
        elif label == 'missing_id': changed.findall(HP+'p')[-1].attrib.pop('id', None)
        elif label == 'picture_page_anchor': cell.find('.//'+HP+'pic/'+HP+'pos').set('vertRelTo', 'PAGE')
        elif label == 'overlapping_cached_band':
            owner = cell.find('.//'+HP+'pic').getparent().getparent()
            owner.findall(HP+'linesegarray/'+HP+'lineseg')[-1].set('horzsize', '22430')
        reject(changed, label)

    state = decode(cell_of(initial).get('name'))
    for label in ('bad_digest', 'bad_base64', 'bad_schema', 'wrong_version', 'unknown_key',
                  'wrong_ids_type', 'too_many_ids', 'invalid_base_flag', 'double_last_break',
                  'base_count_mismatch'):
        changed = deepcopy(negative_base)
        value = deepcopy(state)
        if label == 'bad_digest': name = cell_of(changed).get('name').replace(':flow:', ':flow:0', 1)
        elif label == 'bad_base64': name = PREFIX + '0'*64 + ':!bad!'
        elif label == 'bad_schema': name = encode([])
        else:
            if label == 'wrong_version': value['v'] = 99
            elif label == 'unknown_key': value['unexpected'] = 'flag'
            elif label == 'wrong_ids_type': value['ids'] = [{'unhashable': True}]
            elif label == 'too_many_ids': value['ids'] = [str(i) for i in range(513)]
            elif label == 'invalid_base_flag': value['base'][0] = ['false', '0']
            elif label == 'double_last_break': value['last'][0] = ['1', '1']
            elif label == 'base_count_mismatch': value['base'].pop()
            name = encode(value)
        cell_of(changed).set('name', name)
        reject(changed, label)

    code_after = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in reviewed_files}
    assert code_before == code_after, 'reviewed product code changed during the check'
    result = {'ok': True, 'checks': checks, 'count': len(checks),
              'input_sha256': hashlib.sha256(args.hwpx.read_bytes()).hexdigest(),
              'stable_reviewed_code': code_before,
              'public_save_render_tested_here': False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print('WRAPPED_BREAK_STATE_OK', json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
