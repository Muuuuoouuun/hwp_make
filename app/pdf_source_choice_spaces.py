"""Keep the measured word gaps of complete, single-row English choices."""
from __future__ import annotations

import math

import fitz


def _vector(value, length):
    result = tuple(float(v) for v in value)
    if len(result) != length or not all(math.isfinite(v) for v in result):
        raise ValueError('invalid source choice coordinate')
    return result


def source_choice_space_styles(layout):
    """Return whitespace styles only after independently matching the PDF.

    A normal native HWP space advances half an em. A source Times word space
    may be a quarter em; copying only letters leaves cumulative horizontal
    errors. This narrow path handles a complete single-line, ordinary choice.
    Tables, equations, underlined answer blanks and multi-line justification
    retain their existing layout paths.
    """
    from .pdf_layout_writer import _pdf_output_text, is_hancom_eq_font
    from .pdf_native_typography import _font_name

    try:
        if (not layout.get('source_literal_text') or layout.get('native_tables')
            or layout.get('source_answer_blanks') or layout.get('source_inline_labels')):
            return {}
        meta = layout.get('source_typography') or {}
        records = meta.get('lines') or []
        if len(records) != 1 or str(meta.get('alignment', 'LEFT')).upper() != 'LEFT':
            return {}
        record = records[0]
        if not str(record.get('text', '')).startswith(tuple('①②③④⑤')):
            return {}
        page_index = float(layout['source_page_index'])
        width = float(layout['source_page_width_pt'])
        if not math.isfinite(page_index+width) or page_index != int(page_index) or page_index < 0:
            return {}
        with fitz.open(layout['source_pdf_path']) as document:
            page = document[int(page_index)]
            if width <= 0 or width != page.rect.width:
                return {}
            bbox = _vector(record['bbox_pt'], 4)
            matches = [row for block in page.get_text('rawdict')['blocks']
                       for row in block.get('lines', []) if _vector(row['bbox'], 4) == bbox]
            if len(matches) != 1:
                return {}
            actual = matches[0]
            if actual.get('wmode') != 0 or _vector(actual['dir'], 2) != (1.0, 0.0):
                return {}
            text = ''.join(c['c'] for span in actual['spans'] for c in span['chars'])
            if record['text'] != _pdf_output_text(text).strip():
                return {}
            spans = record.get('spans') or []
            if len(spans) != len(actual['spans']):
                return {}
            for original, supplied in zip(actual['spans'], spans):
                size, flags = float(supplied['size']), float(supplied['flags'])
                if (not math.isfinite(size+flags) or size <= 0 or flags != int(flags)
                    or size != original['size'] or flags != original['flags']
                    or supplied['font'] != original['font']
                    or is_hancom_eq_font(original['font'])
                    or _vector(supplied['origin'], 2) != _vector(original['origin'], 2)
                    or _vector(supplied['bbox'], 4) != _vector(original['bbox'], 4)
                    or supplied['text'] != ''.join(c['c'] for c in original['chars'])
                    or len(supplied.get('chars') or []) != len(original['chars'])):
                    return {}
                for a, b in zip(original['chars'], supplied['chars']):
                    if (a['c'] != b['c'] or _vector(a['origin'], 2) != _vector(b['origin'], 2)
                        or _vector(a['bbox'], 4) != _vector(b['bbox'], 4)):
                        return {}
            cursor, spaces = 0, []
            for span in actual['spans']:
                chars = span['chars']
                supported = (_font_name(span['font']) == 'Times New Roman'
                             and not span['flags'] & (2 | 16))
                for index, char in enumerate(chars):
                    value = _pdf_output_text(char['c'])
                    if (supported and value == ' ' and not char.get('synthetic')
                        and 0 < index < len(chars)-1
                        and not chars[index-1]['c'].isspace()
                        and not chars[index+1]['c'].isspace()
                        and abs(chars[index+1]['origin'][1]-char['origin'][1]) <= .0001):
                        advance = (chars[index+1]['origin'][0]-char['origin'][0])/span['size']
                        if math.isfinite(advance) and .2 <= advance <= .35:
                            spaces.append((cursor, advance))
                    cursor += sum(not c.isspace() for c in value)
            # Several actual, consistent spaces distinguish font word spacing
            # from a one-off tab, label gap or source line justification.
            if len(spaces) < 3 or max(v for _, v in spaces)-min(v for _, v in spaces) > .002:
                return {}
            result = {}
            for position, advance in spaces:
                ratio = max(80, min(110, round(advance*200)))
                tracking = round(advance*100-ratio/2)
                predicted = max(ratio/200+tracking/100, ratio/400)
                if not -50 <= tracking <= 50 or abs(predicted-advance) > .005:
                    return {}
                result[position] = (ratio, tracking)
            return result
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError,
            OSError, fitz.FileNotFoundError, fitz.FileDataError, fitz.EmptyFileError):
        return {}
