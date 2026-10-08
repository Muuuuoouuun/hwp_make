"""Measure horizontal font scaling from a complete, independently proved frame."""
import math

import fitz


def wrapped_source_span_ratios(layout):
    """Return only ratios proved by actual PDF glyph origins and font traces.

    A raw PDF span size combines both axes. A horizontal text trace exposes
    the actual horizontal size. Requiring matching original spans and every
    non-space glyph prevents metadata or a producer flag from setting ratios.
    """
    from .pdf_wrapped_prose_frames import _source_proof

    try:
        proof = _source_proof(layout)
        if proof is None:
            return {}
        geometry, frame, records, _, _ = proof
        with fitz.open(geometry['source_pdf_path']) as pdf:
            page = pdf[int(geometry['source_page_index'])]
            source_width = float(layout.get('source_page_width_pt', 0))
            if not math.isfinite(source_width) or abs(source_width-page.rect.width) > .0001:
                return {}
            rows = sorted([row for block in page.get_text('rawdict')['blocks']
                           for row in block.get('lines', []) if frame.contains(fitz.Rect(row['bbox']))],
                          key=lambda row: (row['bbox'][1], row['bbox'][0]))
            traces = page.get_texttrace()
            candidates = {}
            for trace in traces:
                if (trace.get('wmode') != 0 or len(trace.get('dir', ())) != 2
                    or abs(trace['dir'][0]-1) > .0001 or abs(trace['dir'][1]) > .0001):
                    continue
                size = float(trace['size'])
                if not math.isfinite(size) or size <= 0:
                    continue
                for char in trace['chars']:
                    key = (trace['font'], chr(char[0]))
                    candidates.setdefault(key, []).append((char[2], size))
            result = {}
            if len(rows) != len(records):
                return {}
            for row_index, (row, record) in enumerate(zip(rows, records)):
                spans = record.get('spans') or []
                if len(spans) != len(row['spans']):
                    return {}
                for span_index, (raw, span) in enumerate(zip(row['spans'], spans)):
                    original, given = raw['chars'], span.get('chars') or []
                    size = float(raw['size'])
                    supplied_size = float(span.get('size', 0))
                    if (raw['font'] != span.get('font') or raw['flags'] != span.get('flags')
                        or not math.isfinite(size) or not math.isfinite(supplied_size) or size <= 0
                        or abs(size-supplied_size) > .0001
                        or len(original) != len(given)
                        or ''.join(c['c'] for c in original) != span.get('text')):
                        return {}
                    samples = []
                    for actual, supplied in zip(original, given):
                        if (actual['c'] != supplied.get('c')
                            or any(not math.isfinite(float(v)) for v in (*supplied['origin'], *supplied['bbox']))
                            or len(supplied['origin']) != 2 or len(supplied['bbox']) != 4
                            or max(abs(a-b) for a,b in zip(actual['origin'], supplied['origin'])) > .0001
                            or max(abs(a-b) for a,b in zip(actual['bbox'], supplied['bbox'])) > .0001):
                            return {}
                        if actual['c'].isspace():
                            continue
                        values = {trace_size for origin, trace_size in candidates.get((raw['font'], actual['c']), [])
                                  if max(abs(a-b) for a,b in zip(origin, actual['origin'])) < .0001}
                        if len(values) != 1:
                            samples = []
                            break
                        samples.append(values.pop()/size*100)
                    # Text traces expose the transform independently of the
                    # glyph's width. One fully matched glyph therefore also
                    # proves the horizontal scale of a short punctuation run.
                    if (samples and all(80 <= value <= 110 for value in samples)
                        and max(samples)-min(samples) < .01):
                        result[row_index, span_index] = round(sum(samples)/len(samples))
            return result
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OSError,
            fitz.FileNotFoundError, fitz.FileDataError, fitz.EmptyFileError):
        return {}


def wrapped_source_synthetic_spaces(layout):
    """Measure genuine PDF gaps that MuPDF represents as synthetic spaces.

    These are ordinary editable spaces in HWPX. Only their whitespace style
    changes: native space advances are half an em, whereas an explicit PDF
    word position can leave a smaller gap. Actual PDF rows and every supplied
    span/glyph must agree before the geometry is used.
    """
    from .pdf_layout_writer import _pdf_output_text
    from .pdf_native_typography import _font_name
    from .pdf_source_justification import _actual_rows

    try:
        evidence = _actual_rows(layout)
        if evidence is None:
            return {}
        _, _, rows, _ = evidence
        cursor, result = 0, {}
        for row in rows:
            for span in row['spans']:
                chars = span['chars']
                for index, char in enumerate(chars):
                    value = _pdf_output_text(char['c'])
                    if (value == ' ' and char.get('synthetic') is True
                        and 0 < index < len(chars)-1
                        and not chars[index-1]['c'].isspace()
                        and not chars[index+1]['c'].isspace()
                        and _font_name(span['font']) == 'Haansoft Batang'
                        and row.get('wmode') == 0
                        and tuple(row.get('dir', ())) == (1.0, 0.0)):
                        previous, following = chars[index-1], chars[index+1]
                        # Require the actual empty interval between two glyphs,
                        # not a source font's ordinary space or a shifted line.
                        if (max(abs(char['origin'][1]-other['origin'][1])
                                for other in (previous, following)) <= .0001
                            and abs(char['bbox'][0]-previous['bbox'][2]) <= .0001
                            and abs(char['bbox'][2]-following['origin'][0]) <= .0001):
                            advance = (following['origin'][0]-char['origin'][0])/span['size']
                            if math.isfinite(advance) and 0 < advance < .5:
                                ratio = max(80, min(110, round(advance*200)))
                                tracking = round(advance*100-ratio/2)
                                # Mirror native negative-spacing clamping.
                                # If this style cannot express the actual gap,
                                # retain the original whitespace style.
                                predicted = max(ratio/200+tracking/100, ratio/400)
                                if -50 <= tracking <= 50 and abs(predicted-advance) <= .005:
                                    result[cursor] = (ratio, tracking)
                    cursor += sum(not c.isspace() for c in value)
        return result
    except (ValueError, TypeError, KeyError, IndexError, AttributeError,
            OverflowError, OSError, fitz.FileNotFoundError, fitz.FileDataError,
            fitz.EmptyFileError):
        return {}
