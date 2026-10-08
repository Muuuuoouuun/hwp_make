"""Measure source transforms for complete prose sharing its instruction font."""
from __future__ import annotations

from collections import Counter
import math
import re

import fitz


def source_body_span_ratios(page, body_rows):
    """Return only complete actual row/visible-glyph transform measurements.

    This pure source helper is also the semantic splitter's permission for
    prose that shares a font with its Korean instruction. It does not infer a
    transform from paragraph metadata or a producer flag.
    """
    from .pdf_layout_writer import _iter_text_lines
    from .pdf_source_question_body import _line_proof

    try:
        if not 3 <= len(body_rows) <= 128:
            return {}
        proofs = [_line_proof(row)[0] for row in body_rows]
        actual = Counter(_line_proof(row)[0] for row in _iter_text_lines(page))
        if len(set(proofs)) != len(proofs) or any(actual[proof] != 1 for proof in proofs):
            return {}
        raw_rows = [row for block in page.get_text('rawdict')['blocks'] for row in block.get('lines', [])]
        spans = [span for row in body_rows for span in row['spans']]
        if (not spans or len({span['font'] for span in spans}) != 1
                or any(int(span.get('flags', 0)) & (1 | 2 | 16) for span in spans)):
            return {}
        for row in body_rows:
            matches = [raw for raw in raw_rows if tuple(raw['bbox']) == tuple(row['bbox'])]
            if (len(matches) != 1 or matches[0].get('wmode') != 0
                    or tuple(matches[0].get('dir', ())) != (1., 0.)):
                return {}
        candidates = {}
        for trace in page.get_texttrace():
            if (trace.get('type') != 0 or trace.get('opacity', 1) < .999
                    or trace.get('wmode') != 0 or tuple(trace.get('dir', ())) != (1., 0.)):
                continue
            size = float(trace['size'])
            if not math.isfinite(size) or size <= 0:
                continue
            for char in trace['chars']:
                candidates.setdefault((trace['font'], chr(char[0])), []).append((char[2], size, trace['flags']))
        result = {}
        for row_index, row in enumerate(body_rows):
            for span_index, span in enumerate(row['spans']):
                pairs = sum(bool(re.fullmatch(r'[A-Za-z]', a['c']) and re.fullmatch(r'[A-Za-z]', b['c']))
                            for a, b in zip(span['chars'], span['chars'][1:]))
                if pairs < 3:
                    return {}
                samples = []
                for char in span['chars']:
                    if char['c'].isspace():
                        continue
                    hits = [(size, flags) for origin, size, flags in candidates.get((span['font'], char['c']), ())
                            if len(origin) == 2 and all(math.isfinite(float(v)) for v in origin)
                            and max(abs(a-b) for a, b in zip(origin, char['origin'])) < .0001]
                    if len(hits) != 1 or hits[0][1] != span['flags']:
                        return {}
                    samples.append(hits[0][0] / span['size'] * 100)
                if (not samples or not all(math.isfinite(n) and 80 <= n <= 110 for n in samples)
                        or max(samples) - min(samples) > .01):
                    return {}
                result[row_index, span_index] = round(sum(samples) / len(samples))
        return result
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError,
            OSError, fitz.FileNotFoundError, fitz.FileDataError, fitz.EmptyFileError):
        return {}


def body_source_span_ratios(layout):
    """Re-prove a complete same-font instruction/body before restoring runs."""
    from .pdf_source_question_body import _line_proof, split_source_question_body
    from .pdf_native_content import _source_typography

    try:
        if (layout.get('source_literal_text') is not True or layout.get('native_tables')
                or layout.get('source_answer_blanks') or layout.get('source_inline_labels')):
            return {}
        proof = layout.get('source_question_body') or {}
        meta = layout.get('source_typography') or {}
        records = meta.get('lines') or []
        index, width = layout['source_page_index'], float(layout['source_page_width_pt'])
        if (not proof.get('lines') or proof.get('boundary_mode') != 'existing'
                or not 3 <= len(records) <= 128
                or isinstance(index, bool) or not isinstance(index, int) or index < 0
                or not math.isfinite(width) or width <= 0):
            return {}
        with fitz.open(layout['source_pdf_path']) as source:
            if index >= len(source) or source[index].rect.width != width:
                return {}
            page = source[index]
            groups = split_source_question_body(proof['lines'], page=page, area_hint='영어 영역', existing_boundary=True)
            if len(groups) != 2 or len(groups[1]) != len(records):
                return {}
            body = groups[1]
            canonical = _source_typography(body, {'column_left_pt': layout.get('column_left_pt'),
                                                 'column_right_pt': layout.get('column_right_pt')})
            if (any(meta.get(key) != canonical.get(key) for key in
                    ('font_name', 'font_size_pt', 'alignment', 'line_spacing_pt',
                     'letter_spacing_percent', 'font_width_percent', 'letter_spacing_sample_count'))
                    or any(_line_proof({'bbox': record['bbox_pt'], 'spans': record['spans']})[0]
                           != _line_proof(row)[0] for record, row in zip(records, body))
                    or any(any(record.get(key) != actual.get(key) for key in
                               ('text', 'baseline_pt', 'font_size_pt'))
                           for record, actual in zip(records, canonical['lines']))):
                return {}
            body_font = body[0]['spans'][0]['font']
            if not any(span['font'] == body_font and re.search(r'[가-힣]', span['text'])
                       for row in groups[0] for span in row['spans']):
                return {}
            return source_body_span_ratios(page, body)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError,
            OSError, fitz.FileNotFoundError, fitz.FileDataError, fitz.EmptyFileError):
        return {}
