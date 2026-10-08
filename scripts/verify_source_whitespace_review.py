"""Independent raw-source cursor and real allocator checks for word spacing."""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import re
import sys
import zipfile

import fitz
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pdf_layout_writer import _iter_text_lines, _line_text, _pdf_output_text
from app.pdf_native_content import _source_typography
from app.pdf_native_typography import HH, HP, LANGUAGES, apply_native_typography
from app.pdf_source_choice_spaces import source_choice_space_styles
from app.pdf_source_run_styles import restore_source_run_styles
from hwpx.tools.wrapped_flow_state import paragraph_fingerprint


def main():
    source = ROOT/'data/external_exam_qa/2027_kice_september_high3/english.pdf'
    package = ROOT/'tmp/september-exam-matrix/high3-choice-spaces-ab/choice.hwpx'
    out = ROOT/'tmp/renderer-square/source-whitespace-review'
    out.mkdir(parents=True, exist_ok=True)
    if not source.is_file() or not package.is_file():
        print('SKIP: actual PDF and native choice A/B package required'); return 2
    files = [ROOT/'app'/name for name in ('pdf_source_span_metrics.py', 'pdf_source_run_styles.py',
                                        'pdf_source_choice_spaces.py', 'pdf_source_justification.py')]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    with fitz.open(source) as pdf:
        page = pdf[1]
        line = next(l for l in _iter_text_lines(page) if _line_text(l).startswith('①Absolutely!'))
        layout = {'source_literal_text': True, 'source_pdf_path': str(source),
                  'source_page_index': 1, 'source_page_width_pt': page.rect.width,
                  'source_typography': _source_typography([line], {})}
    text = _pdf_output_text(_line_text(line)).strip()
    # Read expected whitespace positions from the complete actual raw text,
    # independently of the helper's cursor map. This example has eight gaps.
    raw_cursor, expected_positions = 0, []
    for char in text:
        if char == ' ': expected_positions.append(raw_cursor)
        else: raw_cursor += int(not char.isspace())
    assert len(expected_positions) == 8
    source_spaces = source_choice_space_styles(layout)
    assert sorted(source_spaces) == expected_positions
    assert set(source_spaces.values()) == {(80, -15)}

    def carrier(value, split=False):
        p = etree.Element(HP+'p', id='independent-choice', paraPrIDRef='0')
        for piece in list(value) if split else [value]:
            r = etree.SubElement(p, HP+'run', charPrIDRef='0')
            etree.SubElement(r, HP+'t').text = piece
            if split: etree.SubElement(etree.SubElement(p, HP+'run', charPrIDRef='0'), HP+'t').text = ''
        return p

    checks, failures = [], []
    for label, value, split, eligible in (
        ('one_run_raw_source_cursor', text, False, True),
        ('per_character_runs_and_empty_runs', text, True, True),
        ('leading_trailing_whitespace', '  '+text+'  ', True, True),
        ('double_spaces_not_matched_as_single', text.replace(' ', '  '), True, False),
        ('nbsp_not_restyled_as_ascii_space', text.replace(' ', '\u00a0'), True, False),
        ('tabs_not_restyled_as_ascii_space', text.replace(' ', '\t'), True, False),
    ):
        p = carrier(value, split)
        styles, keys = {}, {}
        def style(base, height, font, tracking, ratio, bold, *, italic):
            key = (height, font, tracking, ratio, bold, italic)
            if key not in keys:
                identifier = str(len(styles)+1); keys[key] = identifier; styles[identifier] = key
            return keys[key]
        restore_source_run_styles(p, layout, 59528, style)
        assert ''.join(p.itertext()) == value, label
        cursor, got = 0, []
        for r in p.findall(HP+'run'):
            for char in r.findtext(HP+'t') or '':
                if styles[r.get('charPrIDRef')][2:4] == (-15, 80):
                    assert char == ' ', (label, 'nonwhitespace style invasion', char)
                    got.append(cursor)
                if not char.isspace(): cursor += 1
        assert got == (expected_positions if eligible else []), (label, got)
        checks.append(label)

    # Supplied synthetic flags cannot select geometry; actual raw PDF flags
    # decide which ordinary real spaces qualify.
    forged = deepcopy(layout)
    for s in forged['source_typography']['lines'][0]['spans']:
        for c in s['chars']: c['synthetic'] = True
    assert source_choice_space_styles(forged) == source_spaces
    checks.append('supplied_synthetic_flag_cannot_replace_actual_pdf_evidence')
    for label in ('span_origin', 'span_bbox', 'row_text', 'no_records', 'no_native_text'):
        q = deepcopy(layout)
        record = q['source_typography']['lines'][0]
        if label == 'span_origin':
            v = list(record['spans'][-1]['origin']); v[0] += 1; record['spans'][-1]['origin'] = v
        elif label == 'span_bbox':
            v = list(record['spans'][-1]['bbox']); v[0] += 1; record['spans'][-1]['bbox'] = v
        elif label == 'row_text': record['text'] = '① forged original row'
        elif label == 'no_records': q['source_typography']['lines'] = []
        if label == 'no_native_text':
            p = carrier(''); called = []
            assert restore_source_run_styles(p, q, 59528, lambda *a, **k: called.append(a)) == 0
            assert not called and not ''.join(p.itertext())
        else: assert source_choice_space_styles(q) == {}, label
        checks.append(label)

    # Execute the actual nested production allocator source against a copied
    # real header. The public import path applies typography once; this probe
    # distinguishes resolved-style stability from raw style-ID idempotence.
    with zipfile.ZipFile(package) as z:
        header = etree.fromstring(z.read('Contents/header.xml'))
    chars = header.find('.//'+HH+'charProperties')
    registry = {p.get('id'): p for p in chars}
    node = ast.parse(inspect.getsource(apply_native_typography)).body[0]
    functions = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name in ('font_ids', 'char_style')]
    namespace = {'header': header, 'chars': chars, 'char_by_id': registry, 'char_cache': {},
                 'deepcopy': deepcopy, 'etree': etree, 'HH': HH, 'LANGUAGES': LANGUAGES}
    exec(compile(ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[])),
                 '<actual native typography allocator>', 'exec'), namespace)
    p = carrier(text)
    p.set('paraPrIDRef', next(header.iter(HH+'paraPr')).get('id'))
    para_styles = {n.get('id'): n for n in header.iter(HH+'paraPr')}
    restore_source_run_styles(p, layout, 59528, namespace['char_style'])
    first_xml, first_styles = etree.tostring(p), len(chars)
    first_fingerprint = paragraph_fingerprint(p, para_styles, registry)
    restore_source_run_styles(p, layout, 59528, namespace['char_style'])
    second_fingerprint = paragraph_fingerprint(p, para_styles, registry)
    assert ''.join(p.itertext()) == text
    assert first_fingerprint == second_fingerprint
    checks.append('real_allocator_resolved_fingerprint_stable')
    allocator = {'first_style_count': first_styles, 'second_style_count': len(chars),
                 'raw_run_xml_idempotent': first_xml == etree.tostring(p),
                 'resolved_snapshot_fingerprint_stable': True,
                 'public_import_path_reapplies_helper_on_save': False}
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    if before != after: failures.append('reviewed_code_changed_during_check')
    result = {'ok': not failures, 'checks': checks, 'count': len(checks), 'failures': failures,
              'actual_source_space_positions': expected_positions, 'style_ratio_tracking': [80, -15],
              'actual_allocator_reapplication': allocator, 'stable_reviewed_code': before == after,
              'code_hashes': after, 'product_modified_here': False}
    (out/'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print('SOURCE_WHITESPACE_REVIEW', json.dumps(result, ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
