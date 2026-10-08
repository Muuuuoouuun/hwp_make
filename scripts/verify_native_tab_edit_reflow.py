"""Verify actual native TAB rails through the public edit/save API.

Uses a real English output and the installed renderer. Successful cases use
the production save path unchanged; only the conservative comparison disables
the optional metric factory. Text, visible glyph bounds, retained public run
objects and reopen/resave paint are checked separately from source world Y.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sys
import time

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.native_tab_owner_binding import bind as bind_actual_native_owner
from app.hwpx_writer_v2 import HwpxDocument
from app.pdf_question_rendering import IDENTITY, _multiply, _transform
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools import native_line_metrics, native_line_cache, question_reflow
from hwpx.tools.paragraph_spacing import paragraph_indentation, line_left_margin
import fitz
import rhwp

HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HH = '{http://www.hancom.co.kr/hwpml/2011/head}'
SVG = '{http://www.w3.org/2000/svg}'


def target(document):
    matches = [(section, p) for section in document.sections
               for draw in section.element.iter(HP + 'drawText')
               if draw.get('name') == 'question:v1:q17'
               for p in draw.iter(HP + 'p')
               if len(p.findall(HP + 'run/' + HP + 'tab')) == 2]
    if len(matches) != 1:
        raise ValueError('Expected one actual Q17 three-column choice paragraph')
    section, p = matches[0]
    return HwpxOxmlParagraph(p, section)


def fingerprint():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / 'app').rglob('*.py'))}


def painted(path, text):
    native = rhwp.parse(str(path))
    pages = [native.render_svg(index) for index in range(native.page_count)]
    glyphs = []
    for index, payload in enumerate(pages):
        for node in etree.fromstring(payload.encode('utf-8')).iter(SVG + 'text'):
            value = ''.join(node.itertext())
            if not value.strip():
                continue
            if len(value) != 1:
                raise ValueError('Actual glyph painter no longer uses one-character nodes')
            matrix = IDENTITY
            for ancestor in [*reversed(list(node.iterancestors())), node]:
                matrix = _multiply(matrix, _transform(ancestor.get('transform', '')))
            x, y = float(node.get('x', 0)), float(node.get('y', 0))
            glyphs.append((index, value, matrix[0]*x + matrix[2]*y + matrix[4],
                           matrix[1]*x + matrix[3]*y + matrix[5]))
    needle = ''.join(c for c in text if not c.isspace())
    full = ''.join(g[1] for g in glyphs)
    if full.count(needle) != 1:
        raise ValueError('Edited target is missing or ambiguously painted')
    start = full.index(needle)
    selected = glyphs[start:start + len(needle)]
    markers = [g for g in selected if g[1] in '①②③']
    if len(markers) != 3:
        raise ValueError('Choice markers incomplete')
    return native, pages, markers


def actual_bounds(native, paragraph):
    """Bind every visible target PDF glyph to its cached UTF16 line range."""
    pdf = fitz.open(stream=bytes(native.render_pdf()), filetype='pdf')
    glyphs = [(page_index, char) for page_index, page in enumerate(pdf)
              for trace in page.get_texttrace()
              if trace.get('type') == 0 and trace.get('opacity', 1) > .99
              for char in trace['chars'] if not chr(char[0]).isspace()]
    needle = ''.join(c for c in paragraph.text if not c.isspace())
    full = ''.join(chr(g[1][0]) for g in glyphs)
    if full.count(needle) != 1:
        raise ValueError('Edited target PDF glyph ownership is ambiguous')
    start = full.index(needle)
    selected = glyphs[start:start + len(needle)]
    source = []
    offset = 0
    for run in paragraph.element.findall(HP + 'run'):
        for child in run:
            if child.tag == HP + 'tab':
                offset += 8
            else:
                if child.tag != HP + 't' or len(child):
                    raise ValueError('Unsupported target control')
                for char in child.text or '':
                    if not char.isspace():
                        source.append((offset, char))
                    offset += len(char.encode('utf-16-le')) // 2
    if [c for _, c in source] != [chr(g[1][0]) for g in selected]:
        raise ValueError('Native UTF16 text and actual PDF glyphs differ')
    header = paragraph.section.document.headers[0].element
    paras = {p.get('id'): p for p in header.iter(HH + 'paraPr')}
    left, right, indent = paragraph_indentation(paragraph.element, paras)
    lines = paragraph.element.findall(HP + 'linesegarray/' + HP + 'lineseg')
    base = (selected[0][1][2][0]*4/3
            - line_left_margin(left, indent, 0)/75
            - float(lines[0].get('horzpos'))/75)
    overflow = []
    for index, line in enumerate(lines):
        begin = int(line.get('textpos'))
        end = int(lines[index + 1].get('textpos')) if index + 1 < len(lines) else offset
        actual = [g[1] for (position, _), g in zip(source, selected)
                  if begin <= position < end]
        if not actual:
            raise ValueError('Native cache line has no target glyphs')
        bound_left = base + float(line.get('horzpos'))/75 + line_left_margin(left, indent, index)/75
        bound_right = base + (float(line.get('horzpos')) + float(line.get('horzsize')) - right)/75
        overflow.append(max(0, bound_left - min(g[3][0]*4/3 for g in actual),
                            max(g[3][2]*4/3 for g in actual) - bound_right))
    pdf.close()
    if max(overflow) >= .02:
        raise ValueError(f'Actual edited glyphs exceed current line bounds: {max(overflow)}px')
    return {'glyphs': len(selected), 'cache_rows': len(lines),
            'maximum_overflow_px': max(overflow)}


@contextmanager
def conservative_only():
    factory = native_line_metrics.optional_native_context
    native_line_metrics.optional_native_context = lambda *args, **kwargs: None
    try:
        yield
    finally:
        native_line_metrics.optional_native_context = factory


def edited(path, variant):
    document = HwpxDocument.open(path)
    p = target(document)
    if variant == 'last':
        retained = p.add_run(' additional native words'*6,
                             char_pr_id_ref=p.runs[-1].char_pr_id_ref)
    else:
        retained = next(r for r in p.runs if ('schools' if variant == 'middle' else 'sports') in r.text)
        retained.text += ' additional native words'*(5 if variant == 'middle' else 15)
    return document, p, retained


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    original_sha = hashlib.sha256(args.input.read_bytes()).hexdigest()
    before = fingerprint()
    loaded_modules = {module.__name__: {'path': str(Path(module.__file__).resolve()),
                       'sha256': hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
                      for module in (native_line_metrics, native_line_cache, question_reflow)}
    report = {'scope': 'Actual public TAB edit/save using recorded loaded modules; no positive width callback override',
              'input': str(args.input.resolve()), 'input_sha256': original_sha,
              'loaded_modules': loaded_modules, 'variants': [], 'source_world_y_preserved_claim': False,
              'regression_revision':'Compare horizontal choice rails against independently replayed native XML owner/column origin; original absolute-X failure retained',
              'original_script_sha256':'968e9b48c51a79b197b68d1a2b41c6b2f300071e7d8303d0e9d101255d679289'}
    baseline_doc = HwpxDocument.open(args.input)
    _, baseline_pages, baseline_markers = painted(args.input, target(baseline_doc).text)
    baseline_owner = bind_actual_native_owner(baseline_doc,target(baseline_doc),baseline_pages)
    for variant in ('last', 'middle', 'prefix'):
        document, p, retained = edited(args.input, variant)
        text = p.text
        original_nodes = list(p.element.findall(HP + 'run'))
        path = args.out / (variant + '.hwpx')
        begin = time.perf_counter()
        document.save_to_path(path)
        elapsed = time.perf_counter() - begin
        current_nodes = p.element.findall(HP + 'run')
        if len(original_nodes) != len(current_nodes) or not all(a is b for a, b in zip(original_nodes, current_nodes)):
            raise ValueError('Public save detached original run nodes')
        reopened = HwpxDocument.open(path)
        rp = target(reopened)
        if rp.text != text:
            raise ValueError('Public edited text did not persist')
        native, pages, markers = painted(path, text)
        bounds = actual_bounds(native, rp)
        owner = bind_actual_native_owner(reopened,rp,pages)
        baseline_origin = baseline_owner['column_origin_hwp']/75
        current_origin = owner['column_origin_hwp']/75
        if variant == 'last' and any(abs((a[2]-baseline_origin) - (b[2]-current_origin)) >= .02 for a, b in zip(baseline_markers, markers)):
            raise ValueError('Last-choice edit moved an earlier choice rail')
        if variant == 'middle' and not (abs((baseline_markers[1][2]-baseline_origin) - (markers[1][2]-current_origin)) < .02 and markers[2][3] > markers[1][3]):
            raise ValueError('Middle edit lost preceding rail or normal later wrap')
        resaved = args.out / (variant + '-resaved.hwpx')
        reopened.save_to_path(resaved)
        again, again_pages, _ = painted(resaved, text)
        if pages != again_pages:
            raise ValueError('Reopen/resave changed actual page paint')
        if variant == 'prefix':
            control, cp, _ = edited(args.input, variant)
            control_path = args.out / 'prefix-conservative.hwpx'
            with conservative_only():
                control.save_to_path(control_path)
            control_native, control_pages, _ = painted(control_path, cp.text)
            control_p = target(HwpxDocument.open(control_path))
            if etree.tostring(rp.element) != etree.tostring(control_p.element) or pages != control_pages:
                raise ValueError('Bounded fallback differs from complete conservative output')
        else:
            retained.text += ' RETAINED_PUBLIC_RUN'
            next_text = p.text
            if 'RETAINED_PUBLIC_RUN' not in next_text:
                raise ValueError('Retained public run handle is detached after save')
            retained_path = args.out / (variant + '-retained.hwpx')
            document.save_to_path(retained_path)
            if target(HwpxDocument.open(retained_path)).text != next_text:
                raise ValueError('Repeated edit/save lost retained-run text')
            painted(retained_path, next_text)
        report['variants'].append({'variant': variant, 'save_seconds': elapsed,
                                   'pages': native.page_count, 'markers': markers,
                                   'world_first_y_delta_px': markers[0][3] - baseline_markers[0][3],
                                   'native_owner':owner,'baseline_native_owner':baseline_owner,
                                   'world_translation_x_px':current_origin-baseline_origin,
                                   'owner_local_first_rail_delta_px':(markers[0][2]-current_origin)-(baseline_markers[0][2]-baseline_origin),
                                   'original_run_nodes_retained': True,
                                   'retained_public_run_second_edit_persisted': variant != 'prefix',
                                   'exact_conservative_fallback_verified': variant == 'prefix',
                                   **bounds})
    report['app_stable'] = before == fingerprint()
    report['source_unchanged'] = original_sha == hashlib.sha256(args.input.read_bytes()).hexdigest()
    report['ok'] = report['app_stable'] and report['source_unchanged']
    (args.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if not report['ok']:
        raise ValueError('Production sources changed during proof')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
