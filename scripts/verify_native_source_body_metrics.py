"""Actual-source body transform guards and optional public native editing."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import re
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fitz
import rhwp
from app.pdf_native_content import extract_native_content
from app.pdf_source_body_metrics import body_source_span_ratios, source_body_span_ratios
from app.hwpx_writer_v2 import HwpxDocument
from hwpx.oxml import HwpxOxmlParagraph
from scripts.verify_native_source_question_body import (
    HP, HH, package, question, direct_text, styled_chars, margins,
)


class TracePage:
    def __init__(self, page, traces):
        self.page, self.traces = page, traces

    def get_texttrace(self):
        return deepcopy(self.traces)

    def __getattr__(self, key):
        return getattr(self.page, key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'data/external_exam_qa/2026_september_high2/english.pdf')
    parser.add_argument('--hwpx', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT/'tmp/september-exam-matrix/source-body-metrics-regression')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    owned = [ROOT/'app/pdf_source_body_metrics.py', ROOT/'app/pdf_source_run_styles.py',
             ROOT/'app/pdf_source_question_body.py', ROOT/'app/pdf_native_content.py', Path(__file__)]
    fingerprints = lambda: {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in owned}
    before = fingerprints()
    report = {'checks': [], 'negative_count': 0, 'native_verified': False, 'code_before': before}
    def check(ok, name):
        report['checks'].append({'name': name, 'ok': bool(ok)})
        assert ok, name
    try:
        items, _ = extract_native_content(args.source, area_hint='영어 영역')
        fixtures = [item for item in items if (item.get('layout') or {}).get('source_question_body', {}).get('boundary_mode') == 'existing'
                    and body_source_span_ratios(item['layout'])]
        check(bool(fixtures), 'actual producer supplies existing semantic body fixtures with proved transforms')
        report['fixtures'] = []
        with fitz.open(args.source) as document:
            for item in fixtures:
                layout = item['layout']; page = document[layout['source_page_index']]
                rows = [{'bbox': r['bbox_pt'], 'spans': r['spans']} for r in layout['source_typography']['lines']]
                measured = body_source_span_ratios(layout)
                check(len(measured) == sum(len(row['spans']) for row in rows), 'every actual body span has a transform')
                report['fixtures'].append({'question': layout['question_number'], 'rows': len(rows), 'span_ratios': list(measured.values())})
                mutations = {
                    'nonliteral': lambda d: d.update(source_literal_text=False),
                    'newly_split_boundary': lambda d: d['source_question_body'].update(boundary_mode='split'),
                    'missing_boundary_mode': lambda d: d['source_question_body'].pop('boundary_mode'),
                    'table': lambda d: d.update(native_tables=[{}]),
                    'blank': lambda d: d.update(source_answer_blanks=[{}]),
                    'label': lambda d: d.update(source_inline_labels=[{}]),
                    'wrongpage': lambda d: d.update(source_page_index=9999),
                    'booleanpage': lambda d: d.update(source_page_index=True),
                    'wrongwidth': lambda d: d.update(source_page_width_pt=d['source_page_width_pt']+1),
                    'nanwidth': lambda d: d.update(source_page_width_pt=float('nan')),
                    'missingpdf': lambda d: d.update(source_pdf_path=str(args.output/'missing.pdf')),
                }
                for field in ('font_name', 'font_size_pt', 'alignment', 'line_spacing_pt',
                              'letter_spacing_percent', 'font_width_percent', 'letter_spacing_sample_count'):
                    mutations['canonical_'+field] = lambda d, f=field: d['source_typography'].update({f: 'forged'})
                for field in ('text', 'baseline_pt', 'font_size_pt'):
                    mutations['record_'+field] = lambda d, f=field: d['source_typography']['lines'][0].update({f: 'forged'})
                for count in (1, 2):
                    def truncate(d, count=count):
                        d['source_typography']['lines'] = d['source_typography']['lines'][:-count]
                        d['source_question_body']['lines'] = d['source_question_body']['lines'][:-count]
                    mutations[f'synchronized_terminal_{count}'] = truncate
                for name, mutate in mutations.items():
                    changed = deepcopy(layout); mutate(changed)
                    frozen = json.dumps(changed, sort_keys=True)
                    check(not body_source_span_ratios(changed), 'reject '+name)
                    check(json.dumps(changed, sort_keys=True) == frozen, 'rejection preserves input '+name)
                    report['negative_count'] += 1
                first = next(c for s in rows[0]['spans'] for c in s['chars'] if not c['c'].isspace())
                traces = page.get_texttrace()
                target = next(i for i, trace in enumerate(traces) if any(chr(c[0]) == first['c'] and max(abs(a-b) for a,b in zip(c[2],first['origin'])) < .0001 for c in trace['chars']))
                for name in ('duplicate', 'hidden', 'vertical', 'rotated', 'flags', 'nan_size', 'varying_ratio'):
                    changed = deepcopy(traces)
                    if name == 'duplicate': changed.append(deepcopy(changed[target]))
                    elif name == 'hidden': changed[target]['opacity'] = 0
                    elif name == 'vertical': changed[target]['wmode'] = 1
                    elif name == 'rotated': changed[target]['dir'] = (0., 1.)
                    elif name == 'flags': changed[target]['flags'] ^= 16
                    elif name == 'nan_size': changed[target]['size'] = float('nan')
                    else:
                        trace = deepcopy(changed[target]); trace['chars'] = (trace['chars'][0],)
                        changed[target]['chars'] = changed[target]['chars'][1:]
                        trace['size'] *= 1.05; changed.append(trace)
                    check(not source_body_span_ratios(TracePage(page, changed), rows), 'reject actual trace '+name)
                    report['negative_count'] += 1
        if args.hwpx:
            header, sections = package(args.hwpx)
            props = {node.get('id'): node for node in header.iter(HH+'charPr')}
            for item in fixtures:
                body = next(p for p in question(sections,item['layout']['question_number']).iter(HP+'p') if direct_text(p) == item['stem'])
                ratios = {props[r.get('charPrIDRef')].find(HH+'ratio').get('latin') for r in body.findall(HP+'run')}
                check(ratios == {str(v) for v in body_source_span_ratios(item['layout']).values()}, 'saved native body retains actual source ratios')
                tracking = set()
                for record in item['layout']['source_typography']['lines']:
                    for span in record['spans']:
                        samples = [(b['origin'][0]-a['origin'][0]-(a['bbox'][2]-a['bbox'][0]))/span['size']*100
                                   for a,b in zip(span['chars'],span['chars'][1:])
                                   if re.fullmatch(r'[A-Za-z]',a['c']) and re.fullmatch(r'[A-Za-z]',b['c'])]
                        tracking.add(str(round(median(samples))))
                check({props[r.get('charPrIDRef')].find(HH+'spacing').get('latin') for r in body.findall(HP+'run')} == tracking,
                      'saved native body retains independently measured actual Latin tracking')
            item = fixtures[0]
            number, text = item['layout']['question_number'], item['stem']
            initial = next(p for p in question(sections,number).iter(HP+'p') if direct_text(p) == text)
            original_styles, original_margins = styled_chars(header,initial), margins(header,initial)
            document = HwpxDocument.open(args.hwpx)
            section, draw = next((s,d) for s in document.sections for d in s.element.iter(HP+'drawText') if d.get('name') == f'question:v1:q{number}')
            body = next(p for p in draw.iter(HP+'p') if direct_text(p) == text)
            public = HwpxOxmlParagraph(body,section)
            last = next(r for r in reversed(public.runs) if r.text)
            addition = ' Actual source typography remains editable after this additional sentence.'
            public.add_run(addition,char_pr_id_ref=last.element.get('charPrIDRef'))
            check(body.find(HP+'linesegarray') is None, 'public append invalidates source line cache')
            grown, reopened = args.output/'grown.hwpx', args.output/'reopened.hwpx'
            document.save_to_path(grown); HwpxDocument.open(grown).save_to_path(reopened)
            for path in (grown,reopened):
                h, ss = package(path); p = next(p for p in question(ss,number).iter(HP+'p') if direct_text(p) == text+addition)
                check(styled_chars(h,p)[:len(original_styles)] == original_styles and margins(h,p) == original_margins, 'public save/reopen preserves original styles and rails')
            first, second = rhwp.parse(str(grown)), rhwp.parse(str(reopened))
            check(first.page_count == second.page_count and all(first.render_svg(i) == second.render_svg(i) for i in range(first.page_count)), 'fresh reopen preserves every edited native page painting')
            report['native_verified'] = True
        report['code_after'] = fingerprints()
        check(report['code_after'] == before, 'source/native helper code remains stable during verification')
        report['ok'] = True
        print('NATIVE_SOURCE_BODY_METRICS_OK', len(report['checks']), 'checks', report['negative_count'], 'negatives', 'native', report['native_verified'])
        return 0
    except Exception as error:
        report.update(ok=False,error=repr(error)); raise
    finally:
        (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')


if __name__ == '__main__':
    raise SystemExit(main())
