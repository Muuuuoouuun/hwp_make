"""Source-owned labeled answer rules, independent of QA manifests.

Discovery uses current producer items. Mutation permission must come from the
complete current PDF numbered band and actual visible source paint. This file
returns a read-only plan; it never changes HWPX bytes.
"""
from collections import Counter
import math
import re

import fitz

from . import pdf_source_choice_headers as headers


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _horizontal_ink(page, left, y, right):
    if not all(math.isfinite(value) for value in (left, y, right)) or right-left < 2:
        return False
    pix = page.get_pixmap(matrix=fitz.Matrix(4, 4),
                         clip=fitz.Rect(left+.5, y-.65, right-.5, y+.65),
                         colorspace=fitz.csGRAY, alpha=False)
    return bool(pix.width >= 4 and pix.height >= 2 and all(
        min(pix.samples[row*pix.stride+col] for row in range(pix.height)) < 192
        for col in range(pix.width)))


def _vertical_ink(page, x, top, bottom):
    pix = page.get_pixmap(matrix=fitz.Matrix(4, 4),
                         clip=fitz.Rect(x-.65, top+.5, x+.65, bottom-.5),
                         colorspace=fitz.csGRAY, alpha=False)
    return bool(pix.height >= 4 and pix.width >= 2 and all(
        min(pix.samples[row*pix.stride+col] for col in range(pix.width)) < 192
        for row in range(pix.height)))


def _frame_paint_permission(page, frame, intervals):
    """Reject unproved current paint even if an older black path survives.

    Grayscale alone cannot distinguish a hidden original stroke followed by a
    colored redraw. Accept only black solid strokes contained in the proved
    rule intervals or frame edges, including repeated edges and short tails.
    A later white cover, partial label erasure, extra vector or shading has no
    permission. This is a bounded structural check, not a general PDF painter.
    """
    protected = frame + (-.5, -.5, .5, .5)
    proved_sequences = set()
    for drawing in page.get_drawings():
        width = float(drawing.get('width') or 0)
        extent = fitz.Rect(drawing['rect']) + (-max(.5, width/2), -max(.5, width/2),
                                               max(.5, width/2), max(.5, width/2))
        if not extent.intersects(protected):
            continue
        _require(drawing.get('type') == 's' and drawing.get('stroke_opacity') == 1
                 and drawing.get('color') == (0., 0., 0.)
                 and drawing.get('dashes', '').strip() == '[] 0'
                 and .1 <= width <= 1, 'unproved source summary fill/color/opacity')
        for item in drawing['items']:
            _require(item[0] == 'l', 'unproved source summary vector')
            a, b = item[1:3]
            supported = False
            if abs(a.y-b.y) < .002:
                left, right, y = min(a.x, b.x), max(a.x, b.x), (a.y+b.y)/2
                supported = any(abs(y-rule['rule'][1]) < .002
                                and abs(width-rule['stroke_width']) < .002
                                and rule['rule'][0]-.002 <= left <= right <= rule['rule'][2]+.002
                                for rule in intervals)
                supported = supported or (min(abs(y-frame.y0), abs(y-frame.y1)) < .002
                                           and frame.x0-width/2-.002 <= left <= right <= frame.x1+width/2+.002)
            elif abs(a.x-b.x) < .002:
                top, bottom, x = min(a.y, b.y), max(a.y, b.y), (a.x+b.x)/2
                supported = (min(abs(x-frame.x0), abs(x-frame.x1)) < .002
                             and frame.y0-width/2-.002 <= top <= bottom <= frame.y1+width/2+.002)
            _require(supported, 'unproved source summary stroke position')
        proved_sequences.add(drawing.get('seqno'))
    for sequence, event in enumerate(page.get_bboxlog()):
        kind, box = event[:2]
        extent = fitz.Rect(box) + (-.5, -.5, .5, .5)
        if not extent.intersects(protected):
            continue
        _require(kind == 'fill-text' or (kind == 'stroke-path' and sequence in proved_sequences),
                 'unproved source summary paint operation')


def source_labeled_rule_plan(document, page, question, native_draw):
    """Require a whole summary cell, two centered labels, visible rules/frame.

    The four-label/five-choice structure is independently re-proved by the
    header planner, including the complete numbered same-column source band.
    A metadata or native substring cannot supply that permission.
    """
    from app.pdf_native_text import body_text

    header = headers.source_header_plan(page, question)
    if header is None:
        return None
    raw = headers.ordered_source(question)
    _require(headers.comparable(''.join(c['c'] for c in raw)) ==
             headers.comparable(body_text(native_draw)),
             'incomplete current source/native question text')
    wanted = Counter((c['c'], tuple(c['bbox']), c['baseline']) for c in raw)
    rows = []
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines', []):
            chars = [c for span in line['spans'] for c in span['chars']]
            ink = [c for c in chars if not c['c'].isspace()]
            if ink and all((c['c'], tuple(c['bbox']), c['origin'][1]) in wanted for c in ink):
                rows.append((line, chars, ink))
    labels = [(line, chars, ink) for line, chars, ink in rows
              if re.fullmatch(r'\([A-Z]\)', ''.join(c['c'] for c in ink))]
    horizontal, vertical = [], []
    for drawing in page.get_drawings():
        if not (drawing.get('type') in {'s', 'fs'} and drawing.get('stroke_opacity') == 1
                and drawing.get('color') == (0., 0., 0.)
                and drawing.get('dashes', '').strip() == '[] 0'
                and .1 <= float(drawing.get('width', 0)) <= 1):
            continue
        for item in drawing['items']:
            if item[0] != 'l':
                continue
            a, b = item[1:3]
            if abs(a.y-b.y) < .02:
                horizontal.append((min(a.x, b.x), a.y, max(a.x, b.x), float(drawing['width'])))
            elif abs(a.x-b.x) < .02:
                vertical.append((a.x, min(a.y, b.y), max(a.y, b.y), float(drawing['width'])))
    intervals = []
    for line, chars, ink in labels:
        box = fitz.Rect(ink[0]['bbox'])
        for c in ink[1:]:
            box |= fitz.Rect(c['bbox'])
        baseline = sum(c['origin'][1] for c in ink)/len(ink)
        size = line['spans'][0]['size']
        matches = {tuple(round(v, 4) for v in rule): rule for rule in horizontal
                   if 25 <= rule[2]-rule[0] <= 100 and rule[0] <= box.x0 and box.x1 <= rule[2]
                   and abs((rule[0]+rule[2]-box.x0-box.x1)/2) < .05
                   and .15*size < rule[1]-baseline < .4*size}
        if len(matches) == 1:
            rule = next(iter(matches.values()))
            _require(_horizontal_ink(page, *rule[:3]), 'source answer rule has interrupted/hidden ink')
            intervals.append({'label': ''.join(c['c'] for c in ink),
                              'rule': [rule[0], rule[1], rule[2], rule[1]],
                              'stroke_width': rule[3], 'label_bbox': list(box),
                              'label_baseline': baseline, 'source_line': line})
    if not intervals:
        return None
    _require(len(intervals) == 2, 'ambiguous source labeled rule pair')
    intervals.sort(key=lambda item: item['rule'][0])
    _require(intervals[0]['label'] != intervals[1]['label'] and
             abs(intervals[0]['rule'][1]-intervals[1]['rule'][1]) <= .02,
             'source labels/rule baselines disagree')
    left, y, right = intervals[0]['rule'][0], intervals[0]['rule'][1], intervals[1]['rule'][2]
    frames = set()
    for a in vertical:
        if not (a[0] < left and a[1] < y < a[2]):
            continue
        for b in vertical:
            if not (b[0] > right and abs(a[1]-b[1]) < .05 and abs(a[2]-b[2]) < .05):
                continue
            if all(any(abs(h[1]-edge) < .05 and abs(h[0]-a[0]) < .5 and abs(h[2]-b[0]) < .5
                       for h in horizontal) for edge in a[1:3]):
                frames.add(tuple(round(v, 4) for v in (a[0], a[1], b[0], a[2])))
    _require(len(frames) == 1, 'missing/ambiguous closed source summary frame')
    frame = fitz.Rect(next(iter(frames)))
    _require(all(_horizontal_ink(page, frame.x0, edge, frame.x1) for edge in (frame.y0, frame.y1))
             and all(_vertical_ink(page, edge, frame.y0, frame.y1) for edge in (frame.x0, frame.x1)),
             'source summary frame has hidden/interrupted edges')
    _require(not any(frame.intersects(fitz.Rect(info['bbox'])) for info in page.get_image_info()),
             'source summary frame overlaps raster paint')
    _frame_paint_permission(page, frame, intervals)
    frame_rows = [(line, chars, ink) for line, chars, ink in rows
                  if all(frame.contains(fitz.Rect(c['bbox'])) for c in ink)]
    _require(frame_rows, 'empty actual source summary frame')
    sizes = []
    traces = {}
    for trace in page.get_texttrace():
        for c in trace['chars']:
            traces.setdefault((chr(c[0]), tuple(c[2])), []).append((trace, c))
    for line, chars, ink in frame_rows:
        _require(line.get('wmode') == 0 and tuple(line.get('dir', ())) == (1., 0.),
                 'unsupported source summary direction')
        for span in line['spans']:
            _require(span['font'] == 'TimesNewRoman' and span['flags'] == 4
                     and span.get('color') == 0 and span.get('alpha') == 255
                     and 6 <= span['size'] <= 24, 'unsupported source summary style')
            sizes.append(span['size'])
        for c in ink:
            matches = traces.get((c['c'], tuple(c['origin'])), [])
            _require(c.get('synthetic') is False and len(matches) == 1, 'ambiguous summary glyph trace')
            trace, glyph = matches[0]
            source_spans = [span for span in line['spans'] if c in span['chars']]
            _require(len(source_spans) == 1, 'ambiguous summary glyph font span')
            _require(trace['type'] == 0 and trace['opacity'] == 1 and trace['flags'] == 4
                     and trace['font'] == 'TimesNewRoman' and trace['wmode'] == 0
                     and tuple(trace['dir']) == (1., 0.)
                     and abs(trace['size']-source_spans[0]['size']) <= .02,
                     'unsupported actual summary glyph paint')
            pix = page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=fitz.Rect(c['bbox']),
                                 colorspace=fitz.csGRAY, alpha=False)
            _require(pix.width and pix.height and min(pix.samples) < 192,
                     'actual source summary glyph has no visible ink')
    _require(max(sizes)-min(sizes) <= .02, 'mixed source summary sizes')
    physical = []
    for c in sorted((c for _, _, ink in frame_rows for c in ink), key=lambda c: (c['origin'][1], c['origin'][0])):
        if physical and abs(c['origin'][1]-physical[-1][0]['origin'][1]) <= 3:
            physical[-1].append(c)
        else:
            physical.append([c])
    frame_text = ''.join(c['c'] for row in physical for c in sorted(row, key=lambda c: c['origin'][0]))
    cells = [cell for cell in native_draw.iter(headers.HP+'tc')
             if headers.compact(body_text(cell)) == frame_text]
    _require(len(cells) == 1, 'incomplete/ambiguous current native summary cell')
    _require([span['label'] for span in intervals]*2 == header['labels'],
             'summary labels disagree with complete choice-column headers')
    label_baseline = intervals[0]['label_baseline']
    label_rows = [row for row in frame_rows if ''.join(c['c'] for c in row[2]) in
                  [interval['label'] for interval in intervals]]
    _require(len(label_rows) == 2, 'ambiguous source summary label rows')
    prose_rows = [row for row in frame_rows if row not in label_rows and
                  abs(row[2][0]['origin'][1]-label_baseline) < 3]
    _require(len(prose_rows) == 1, 'ambiguous source prose between labels')
    prose = prose_rows[0][1]
    _require(intervals[0]['rule'][2] < prose[0]['bbox'][0] and prose[-1]['bbox'][2] < intervals[1]['rule'][0],
             'source prose crosses labeled answer interval')
    actual_row = [c for _, _, ink in frame_rows for c in ink if abs(c['origin'][1]-label_baseline) < 3]
    actual_row.sort(key=lambda c: c['origin'][0])
    row_text = ''.join(c['c'] for c in actual_row)
    prose_text = ''.join(c['c'] for c in prose)
    _require(row_text == intervals[0]['label']+headers.compact(prose_text)+intervals[1]['label'],
             'incomplete source labeled-rule physical row')
    # Reuse the exact Unicode/CID/GID/embedded-font proof for the two labels.
    label_spans = [interval['source_line']['spans'][0] for interval in intervals]
    label_glyphs = [(c, traces[(c['c'], tuple(c['origin']))][0][1][1])
                    for row in label_rows for c in row[2]]
    font_plan = {'spans': label_spans, 'glyphs': label_glyphs}
    program = headers.font_program_proof(document, page, font_plan)
    clean_intervals = [{k: v for k, v in item.items() if k != 'source_line'} for item in intervals]
    return {'question': question.number, 'source_page': question.page,
            'complete_actual_question_glyphs': len(raw), 'summary_frame_bbox_pt': list(frame),
            'summary_complete_cell_text': frame_text, 'labeled_intervals': clean_intervals,
            'rule_row_nonspace_text': row_text, 'rule_row_prose': prose_text,
            'rule_row_prose_origin_pt': list(prose[0]['origin']),
            'source_rule_style_size_pt': sizes[0], 'source_font_program': program,
            'source_column': header['column'], 'mutation_permission': False,
            'source_oracle_dependency': False,
            'remaining': ['current native style/canonical cell geometry proof',
                          'fresh native advance and editable underlined TAB reconstruction',
                          'actual all-glyph/pixel and public-edit qualification']}
