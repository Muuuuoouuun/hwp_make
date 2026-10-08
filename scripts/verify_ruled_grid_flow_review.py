"""Independent plain-grid cache guards and public grow/delete review.

Reads a real September source PDF and an existing HWPX; never converts the
source or writes product/storage files. Digest-valid mutants are deliberate.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import fitz
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.hwpx_writer_v2 import HwpxDocument
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools import ruled_grid_flow as grid

HP, HH, HC = grid.HP, grid.HH, grid.HC


def text(node):
    return ''.join(t.text or '' for t in node.iter(HP+'t'))


def target(root):
    return next(t for t in root.iter(HP+'tbl')
                if t.get('name', '').startswith(grid.PREFIX) and 'Winners' in text(t))


def cell_paragraph(table):
    return next(p for p in table.iter(HP+'p') if text(p) == '1st prize')


def maps(header):
    return ({s.get('id'): s for s in header.iter(HH+'paraPr')},
            {s.get('id'): s for s in header.iter(HH+'charPr')})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hwpx', type=Path, default=ROOT/'tmp/september-exam-matrix/high3-native3-readonly/grid-current-fresh-seeded.hwpx')
    parser.add_argument('--source', type=Path, default=ROOT/'data/external_exam_qa/2027_kice_september_high3/english.pdf')
    parser.add_argument('--report', type=Path, default=ROOT/'tmp/september-audit/grid-flow-independent/report.json')
    parser.add_argument('--edits', action='store_true')
    args = parser.parse_args()
    if not args.hwpx.is_file() or not args.source.is_file():
        print('SKIP: existing actual source PDF and native HWPX required')
        return 2
    code = [ROOT/name for name in ('app/pdf_source_grid_layout.py', 'app/_vendor/hwpx/tools/ruled_grid_flow.py',
                                  'app/_vendor/hwpx/tools/question_reflow.py', 'app/pdf_native_typography.py')]
    hashes = lambda: {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code}
    before_code = hashes()
    with zipfile.ZipFile(args.hwpx) as package:
        header = etree.fromstring(package.read('Contents/header.xml'))
        roots = [etree.fromstring(package.read(n)) for n in package.namelist()
                 if n.startswith('Contents/section') and n.endswith('.xml')]
    root = next(r for r in roots if any('Winners' in text(t) for t in r.iter(HP+'tbl')))
    table = target(root)
    original_height = int(table.find(HP+'sz').get('height'))
    # Source oracle reads actual PDF table cells, independent of the imported
    # metadata/state. Blank native decoration gutters are excluded by borders.
    with fitz.open(args.source) as document:
        found = [t.extract() for p in document for t in p.find_tables().tables
                 if t.row_count >= 2 and t.col_count >= 2
                 and any('Winners' in (v or '') for row in t.extract() for v in row)]
        assert len(found) == 1, 'one independently detected Winners source grid'
        source_cells = [[(v or '').strip() for v in row] for row in found[0]]
    ps, cs = maps(header)
    native_shape, _, native_cells = grid.geometry(table, header)
    native_source = [[text(native_cells[r*native_shape[1]+c]) for c in range(native_shape[1])
                      if native_shape[5][r*native_shape[1]+c][1] == 'SOLID']
                     for r in range(native_shape[0])]
    native_source = [row for row in native_source if row]
    assert native_source == source_cells, (native_source, source_cells)

    checks, failures = [], []

    def record(name, passed, **evidence):
        checks.append({'name': name, 'passed': bool(passed), **evidence})
        print(('PASS: ' if passed else 'FAIL: ')+name, flush=True)
        if not passed:
            failures.append(name)

    def fixture():
        r, h = deepcopy(root), deepcopy(header)
        t = target(r); p = cell_paragraph(t)
        p.remove(p.find(HP+'linesegarray'))
        return r, h, t, p, *maps(h)

    for name in ('exact_dirty', 'small_fit', 'large_wrap', 'space_boundary_wrap', 'staged_table_copy'):
        r, h, t, p, ps, cs = fixture()
        if name == 'small_fit':
            p.find(HP+'run/'+HP+'t').text = '1st Prize'
        elif name == 'large_wrap':
            p.find(HP+'run/'+HP+'t').text += ' measured editable grid growth'*3
        elif name == 'space_boundary_wrap':
            # Actual native core text_measurement.rs forces ASCII space to
            # half-em. Eight i glyphs plus seven spaces exceed this cell even
            # though the original TNR quarter-em hmtx estimate would fit.
            p.find(HP+'run/'+HP+'t').text = 'i i i i i i i i'
        elif name == 'staged_table_copy':
            t = deepcopy(t)
        before = etree.tostring(r), etree.tostring(h)
        try:
            staged, _ = grid.prepare(t, h, ps, cs)
            newheight = int(staged.find(HP+'sz').get('height'))
            passed = (newheight > original_height if name in ('large_wrap','space_boundary_wrap') else newheight == original_height)
            passed = passed and text(t) == text(staged) and before == (etree.tostring(r), etree.tostring(h))
            record(name, passed, native_height=newheight)
        except Exception as error:
            record(name, False, error=repr(error))

    cases = ('forged_baseline', 'forged_top_reserve', 'forged_spacing_reserve', 'forged_canonical_height_reserve',
             'forged_first_offset', 'forged_width', 'forged_negative_baseline', 'forged_oversized_height',
             'missing_state', 'bad_digest', 'unicode_surrogate_pair', 'unicode_combining', 'tab',
             'native_picture', 'native_equation', 'changed_char_height', 'changed_char_ratio',
             'changed_char_spacing', 'changed_para_indent', 'changed_font_family', 'generic_dirty')
    for name in cases:
        r, h, t, p, ps, cs = fixture()
        state = grid.decode(t.get('name'))
        entry = next(v for v in state['cells'] if v[0] == p.get('id'))
        char = cs[p.find(HP+'run').get('charPrIDRef')]
        if name == 'forged_baseline': entry[2][0][4] = 1
        elif name == 'forged_top_reserve': entry[2][0][1] += 300; entry[3] -= 300
        elif name == 'forged_spacing_reserve': entry[2][0][5] += 300; entry[3] -= 300
        elif name == 'forged_canonical_height_reserve':
            delta = 1000-entry[2][0][2]
            entry[2][0][2] = entry[2][0][3] = 1000
            entry[2][0][4] = 850
            entry[3] -= delta
        elif name == 'forged_first_offset': entry[2][0][0] = 1
        elif name == 'forged_width': entry[2][0][7] += 100
        elif name == 'forged_negative_baseline': entry[2][0][4] = -1
        elif name == 'forged_oversized_height': entry[2][0][2] = 100000
        elif name == 'missing_state': t.set('name', 'ordinary-table')
        elif name == 'bad_digest': t.set('name', t.get('name').replace(':cache:', ':cache:0', 1))
        elif name in ('unicode_surrogate_pair', 'unicode_combining', 'tab'):
            p.find(HP+'run/'+HP+'t').text += {'unicode_surrogate_pair': '\U0001f600', 'unicode_combining': '\u0301', 'tab': '\t'}[name]
        elif name in ('native_picture', 'native_equation'):
            etree.SubElement(p.find(HP+'run'), HP+('pic' if name == 'native_picture' else 'equation'))
        elif name == 'changed_char_height': char.set('height', str(int(char.get('height'))+1))
        elif name == 'changed_char_ratio': char.find(HH+'ratio').set('latin', '200')
        elif name == 'changed_char_spacing': char.find(HH+'spacing').set('latin', '20')
        elif name == 'changed_para_indent': ps[p.get('paraPrIDRef')].find('.//'+HC+'intent').set('value', '10')
        elif name == 'changed_font_family':
            ref = char.find(HH+'fontRef').get('latin')
            next(f for face in h.iter(HH+'fontface') if face.get('lang') == 'LATIN'
                 for f in face if f.get('id') == ref).set('face', 'Arial')
        elif name == 'generic_dirty':
            extra = etree.SubElement(r, HP+'p', id='independent-nongrid')
            etree.SubElement(etree.SubElement(extra, HP+'run'), HP+'t').text = 'ordinary editable text'
        if name.startswith('forged_'):
            t.set('name', grid.encode(state))  # Recompute checksum; never rely on bad digest rejection.
        before = etree.tostring(r), etree.tostring(h)
        context = grid.begin(r, ps, cs)
        evidence = {'accepted': context is not None, 'transactional': before == (etree.tostring(r), etree.tostring(h))}
        if context is not None and name.startswith('forged_'):
            pp = next(q for q in context['plans'][t].iter(HP+'p') if q.get('id') == p.get('id'))
            evidence['accepted_cache'] = grid.lines(pp)
        record(name, context is None and evidence['transactional'], **evidence)

    edit_report = None
    if args.edits:
        import rhwp
        folder = args.report.parent/'public-edits'
        folder.mkdir(parents=True, exist_ok=True)
        initial_pages = rhwp.parse(str(args.hwpx)).page_count
        results = []
        previous = args.hwpx
        for name in ('small', 'large', 'deleted'):
            doc = HwpxDocument.open(args.hwpx if name != 'deleted' else previous)
            section = next(s for s in doc.sections if any('Winners' in text(t) for t in s.element.iter(HP+'tbl')))
            t = target(section.element)
            p = next(p for p in t.iter(HP+'p') if text(p).startswith('1st prize' if name != 'deleted' else '1st prize measured'))
            editable = HwpxOxmlParagraph(p, section)
            editable.text = '1st Prize' if name == 'small' else '1st prize'+' measured editable grid growth'*3 if name == 'large' else '1st prize'
            path = folder/(name+'.hwpx');doc.save_to_path(path)
            reopened = HwpxDocument.open(path)
            rt = next(target(s.element) for s in reopened.sections if any('Winners' in text(t) for t in s.element.iter(HP+'tbl')))
            row = {'mode': name, 'path': str(path), 'pages': rhwp.parse(str(path)).page_count,
                   'height': int(rt.find(HP+'sz').get('height')), 'text': text(rt)}
            results.append(row);previous = path
        record('public_small_preserves_page_height', results[0]['pages'] == initial_pages and results[0]['height'] == original_height)
        record('public_large_grows', results[1]['pages'] > initial_pages and results[1]['height'] > original_height)
        record('public_delete_exact_page_height_text', results[2]['pages'] == initial_pages and results[2]['height'] == original_height and results[2]['text'] == text(table))
        edit_report = {'initial_pages': initial_pages, 'initial_height': original_height, 'stages': results}
    after_code = hashes()
    stable = before_code == after_code
    record('reviewed_code_snapshot_stable', stable)
    report = {'ok': not failures, 'source': str(args.source), 'source_sha256': hashlib.sha256(args.source.read_bytes()).hexdigest(),
              'input': str(args.hwpx), 'input_sha256': hashlib.sha256(args.hwpx.read_bytes()).hexdigest(),
              'before_code': before_code, 'after_code': after_code, 'source_grid_cells': source_cells,
              'checks': checks, 'failures': failures, 'public_edits': edit_report,
              'scope': 'ASCII native cell cache/flow guard review; no target98 or source-font/PNG-paint claim'}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': report['ok'], 'checks': len(checks), 'failures': failures, 'report': str(args.report)}, ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
