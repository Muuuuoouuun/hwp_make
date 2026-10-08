"""Public-save pagination boundaries for source-proved wrapped-cell edits.

The native Q27 frame is checked against the actual PDF first. Three existing
question boxes then form a deliberately small synthetic pagination fixture;
its page size is artificial and no source-layout fidelity is claimed for it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.hwpx_writer_v2 import HwpxDocument
from app.pdf_wrapped_prose_frames import source_flow_wrapped_prose_frame_table
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools.paragraph_floats import HH, HP, WRAPPED_CELL
from hwpx.tools.paragraph_spacing import paragraph_spacing
from hwpx.tools.question_reflow import flow_height
from hwpx.tools.question_spacing import ParagraphSpacingStyles, arrange_question_gaps
from hwpx.tools.wrapped_flow_state import decode, encode, seed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hwpx', type=Path)
    parser.add_argument('--source', type=Path, default=ROOT/'data/external_exam_qa/2026_september_high2/english.pdf')
    parser.add_argument('--output', type=Path, default=ROOT/'tmp/renderer-square/gap-pagination-independent')
    args = parser.parse_args()
    if args.hwpx is None or not args.hwpx.is_file() or not args.source.is_file():
        print('SKIP: actual source PDF and native --hwpx fixture required')
        return 2
    args.output.mkdir(parents=True, exist_ok=True)
    paths = [ROOT/'app/_vendor/hwpx/tools'/name for name in
             ('wrapped_flow_state.py', 'paragraph_floats.py', 'question_reflow.py',
              'wrapped_cache_metrics.py', 'question_spacing.py')]
    code_before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    with zipfile.ZipFile(args.hwpx) as package:
        header = etree.fromstring(package.read('Contents/header.xml'))
        manifest = etree.fromstring(package.read('Contents/content.hpf'))
        hrefs = {n.get('id'): n.get('href') for n in manifest.iter() if n.get('href')}
        roots = [etree.fromstring(package.read(n)) for n in package.namelist()
                 if n.startswith('Contents/section') and n.endswith('.xml')]
        root = next(r for r in roots if any(c.get('name', '').startswith(WRAPPED_CELL) for c in r.iter(HP+'tc')))
        cell = next(c for c in root.iter(HP+'tc') if c.get('name', '').startswith(WRAPPED_CELL))
        assert source_flow_wrapped_prose_frame_table(cell.getparent().getparent(), root,
                                                     header, hrefs, package, args.source)

    cases = (
        ('v2_exact_capacity_retains_before', 'v2', 1466, 0, None, True),
        ('v2_one_unit_oversized_consumes_before', 'v2', 1466, -1, None, False),
        ('v1_uses_ordinary_consume', 'v1', 1466, 0, None, False),
        ('bare_marker_uses_ordinary_consume', 'bare', 1466, 0, None, False),
        ('bad_digest_uses_ordinary_consume', 'invalid', 1466, 0, None, False),
        ('generic_dirty_uses_ordinary_consume', 'generic', 1466, 0, None, False),
        ('math_dirty_uses_ordinary_consume', 'math', 1466, 0, None, False),
        ('manual_positive_before_retained', 'v2', 2048, 0, None, True),
        # The preceding Q27 is slightly taller than Q28 without its gap.
        ('manual_zero_before_stays_zero', 'v2', 0, 512, None, True),
        ('manual_page_break_retained', 'v2', 1466, 0, ('1', '0'), True),
        ('manual_column_break_retained', 'v2', 1466, 0, ('0', '1'), True),
    )
    outcomes, failures = [], []
    for label, mode, gap, capacity_delta, manual_break, retain in cases:
        try:
            with HwpxDocument.open(args.hwpx) as document:
                section = next(s for s in document.sections
                               if any(c.get('name', '').startswith(WRAPPED_CELL) for c in s.element.iter(HP+'tc')))
                root, header = section.element, document.headers[0].element
                arrange_question_gaps(root, header, before_pagination=True)
                owners = {next(d.get('name') for d in p.iter(HP+'drawText')): p
                          for p in root.findall(HP+'p') if any(True for _ in p.iter(HP+'drawText'))}
                kept = [owners[name] for name in ('question:v1:q13', 'question:v1:q27', 'question:v1:q28')]
                for p in list(root):
                    if p not in kept: root.remove(p)
                for p in kept: p.set('pageBreak', '0'); p.set('columnBreak', '0')
                kept[1].set('columnBreak', '1')
                spacing = ParagraphSpacingStyles(header)
                spacing.set(kept[2], gap, 0)
                ps = spacing.styles
                cs = {n.get('id'): n for n in header.iter(HH+'charPr')}
                question_height = flow_height(kept[2])
                capacity = question_height + gap + capacity_delta
                page = root.find('.//'+HP+'pagePr'); margins = page.find(HP+'margin')
                overhead = sum(float(margins.get(k, '0')) for k in ('top', 'bottom', 'header', 'footer'))+1400
                page.set('height', str(round(capacity+overhead)))
                cell = next(c for c in kept[1].iter(HP+'tc') if c.get('name', '').startswith(WRAPPED_CELL))
                cell.set('name', WRAPPED_CELL)
                assert seed(root, cell, ps, cs), 'synthetic native cache seed'
                state = decode(cell.get('name'))
                if mode == 'v1': cell.set('name', encode({k: v for k, v in state.items() if k != 'cache'} | {'v': 1}))
                elif mode == 'bare': cell.set('name', WRAPPED_CELL)
                elif mode == 'invalid': cell.set('name', cell.get('name').replace(':flow:', ':flow:0', 1))
                if manual_break is not None:
                    kept[2].set('pageBreak', manual_break[0]); kept[2].set('columnBreak', manual_break[1])
                target = cell.find(HP+'subList/'+HP+'p')
                HwpxOxmlParagraph(target, section).add_run('', char_pr_id_ref=target.find(HP+'run').get('charPrIDRef'))
                if mode in ('generic', 'math'):
                    generic = next(kept[0].iter(HP+'drawText')).find(HP+'subList/'+HP+'p')
                    public = HwpxOxmlParagraph(generic, section)
                    run = public.add_run(' additional plain text', char_pr_id_ref=generic.find(HP+'run').get('charPrIDRef'))
                    if mode == 'math': etree.SubElement(run.element, HP+'equation')
                path = args.output/(label+'.hwpx')
                document.save_to_path(path)
            with HwpxDocument.open(path) as saved:
                draw = next(d for s in saved.sections for d in s.element.iter(HP+'drawText')
                            if d.get('name') == 'question:v1:q28')
                owner = draw.getparent().getparent().getparent()
                margin = draw.find(HP+'textMargin')
                top = float(margin.get('top'))
                expected = gap if retain else 0
                assert top == expected, (label, top, expected)
                if manual_break is not None:
                    saved_cell = next(c for s in saved.sections for c in s.element.iter(HP+'tc')
                                      if c.get('name', '').startswith(WRAPPED_CELL))
                    saved_state = decode(saved_cell.get('name'))
                    # A manual next-column break from the right column is
                    # canonically emitted as a next-page flag; its baseline
                    # intent must remain the explicit user pair.
                    assert saved_state['base'][saved_state['ids'].index(owner.get('id'))] == list(manual_break)
                output = {'case': label, 'ok': True, 'capacity': capacity,
                          'question_plus_before': question_height+gap,
                          'native_top_margin': top, 'expected_top_margin': expected,
                          'breaks': [owner.get('pageBreak'), owner.get('columnBreak')]}
                reopened = args.output/(label+'-reopened.hwpx')
                saved.save_to_path(reopened)
            with zipfile.ZipFile(path) as a, zipfile.ZipFile(reopened) as b:
                names = [n for n in a.namelist() if n.startswith('Contents/section') and n.endswith('.xml')]
                assert all(a.read(n) == b.read(n) for n in names), 'reopened stable save changed section'
            outcomes.append(output)
        except Exception as error:
            failures.append(label)
            outcomes.append({'case': label, 'ok': False, 'error': str(error)})
    code_after = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if code_before != code_after: failures.append('product_changed_during_check')
    result = {'ok': not failures, 'failures': failures, 'cases': outcomes,
              'actual_initial_source_proof': True, 'synthetic_pagination_fixture': True,
              'stable_code': code_before == code_after, 'code_hashes': code_after,
              'input_sha256': hashlib.sha256(args.hwpx.read_bytes()).hexdigest(),
              'actual_source_render_tested_here': False}
    (args.output/'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print('WRAPPED_PAGINATION_GAPS', json.dumps(result, ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
