"""Restore natural Times word spaces in independently proved indented prose."""
from __future__ import annotations

import math
import struct

import fitz


def _regular_body_space_styles(layout):
    """Measure ordinary word spaces without copying justified source gaps.

    A complete source instruction/body boundary must be independently proved.
    All body glyphs must belong to one regular Times face and size, and the
    final, short source row must independently demonstrate the natural word
    spacing. Native justification continues to lay out nonfinal rows.
    """
    from .pdf_layout_writer import _iter_text_lines, _pdf_output_text
    from .pdf_native_typography import _font_name
    from .pdf_source_question_body import _line_proof, split_source_question_body

    try:
        if (layout.get('source_literal_text') is not True or layout.get('native_tables')
                or layout.get('source_answer_blanks') or layout.get('source_inline_labels')):
            return {}
        meta = layout.get('source_typography') or {}
        records = meta.get('lines') or []
        if not 3 <= len(records) <= 128 or meta.get('alignment') != 'JUSTIFY':
            return {}
        page_index, width = layout['source_page_index'], float(layout['source_page_width_pt'])
        if (isinstance(page_index, bool) or not isinstance(page_index, int) or page_index < 0
                or not math.isfinite(width) or width <= 0):
            return {}
        with fitz.open(layout['source_pdf_path']) as document:
            if page_index >= len(document):
                return {}
            page = document[page_index]
            if width != page.rect.width:
                return {}
            actual_lines = _iter_text_lines(page)
            raw_rows = [row for block in page.get_text('rawdict')['blocks']
                        for row in block.get('lines', [])]
            actual_rows = []
            for record in records:
                bbox = tuple(float(v) for v in record['bbox_pt'])
                if len(bbox) != 4 or not all(math.isfinite(v) for v in bbox):
                    return {}
                matches = [row for row in actual_lines if tuple(row['bbox']) == bbox]
                if len(matches) != 1:
                    return {}
                row = matches[0]
                raw_matches = [raw for raw in raw_rows if tuple(raw['bbox']) == bbox]
                if (len(raw_matches) != 1 or raw_matches[0].get('wmode') != 0
                        or tuple(raw_matches[0].get('dir', ())) != (1.0, 0.0)):
                    return {}
                supplied = {'bbox': record['bbox_pt'], 'spans': record['spans']}
                if _line_proof(supplied)[0] != _line_proof(row)[0]:
                    return {}
                raw = ''.join(c['c'] for span in row['spans'] for c in span['chars'])
                if record['text'] != _pdf_output_text(raw).strip():
                    return {}
                for span in record['spans']:
                    flags = float(span.get('flags', 0))
                    if not math.isfinite(flags) or flags != int(flags):
                        return {}
                actual_rows.append(row)
            # Reconstruct and re-prove the actual semantic boundary. Supplied
            # body markers, question numbers and geometry are not permission.
            boundary = False
            for candidate in actual_lines:
                groups = split_source_question_body([candidate, *actual_rows], page=page,
                                                    area_hint='\uc601\uc5b4 \uc601\uc5ed')
                if len(groups) == 2 and groups[1] == actual_rows:
                    boundary = True
                    break
            if not boundary:
                return {}
            spans = [span for row in actual_rows for span in row['spans']]
            sizes = [float(span['size']) for span in spans]
            if (len({span['font'] for span in spans}) != 1 or max(sizes)-min(sizes) > .0001
                    or any(_font_name(span['font']) != 'Times New Roman'
                           or span['flags'] & (2 | 16) for span in spans)):
                return {}
            cursor, positions, natural, final_advances = 0, [], [], []
            for row_index, row in enumerate(actual_rows):
                row_chars = [c for span in row['spans'] for c in span['chars']]
                for span in row['spans']:
                    chars = span['chars']
                    for index, char in enumerate(chars):
                        value = _pdf_output_text(char['c'])
                        if value == ' ':
                            if (char.get('synthetic') or index == 0
                                    or chars[index-1]['c'].isspace()
                                    or index < len(chars)-1 and chars[index+1]['c'].isspace()):
                                return {}
                            em = (char['bbox'][2]-char['bbox'][0])/span['size']
                            if not math.isfinite(em) or abs(em-.25) > .0001:
                                return {}
                            natural.append(em)
                            positions.append(cursor)
                            if index < len(chars)-1:
                                following = chars[index+1]
                                advance = (following['origin'][0]-char['origin'][0])/span['size']
                                if (not math.isfinite(advance)
                                        or abs(following['origin'][1]-char['origin'][1]) > .0001):
                                    return {}
                                if row_index == len(actual_rows)-1:
                                    final_advances.append(advance)
                        cursor += sum(not c.isspace() for c in value)
                # A source line break can become an ordinary space when the
                # complete paragraph is joined. It uses the same proved face.
                if row_index < len(actual_rows)-1 and row_chars[-1]['c'].isalnum():
                    positions.append(cursor)
            if (len(natural) < 6 or len(final_advances) < 1
                    or max(abs(v-.25) for v in final_advances) > .01):
                return {}
            if len(final_advances) < 3:
                from .pdf_source_font_spaces import source_terminal_space_positions
                terminal = source_terminal_space_positions(document, page, actual_rows, actual_lines)
                if not terminal:
                    return {}
                positions = [position for position in positions if position in terminal]
                if set(positions) != terminal:
                    return {}
            # HWP's half-em space plus 80% ratio / -15% tracking is a quarter
            # em, and stays above the reader's half-width minimum clamp.
            return dict.fromkeys(positions, (80, -15))
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError,
            OSError, fitz.FileNotFoundError, fitz.FileDataError, fitz.EmptyFileError):
        return {}


def _mixed_terminal_spaces(layout):
    """Prove only terminal regular-Times spaces in a complete mixed body."""
    from .pdf_layout_writer import _iter_text_lines, _pdf_output_text
    from .pdf_native_content import _source_typography
    from .pdf_source_question_body import _line_proof, split_source_question_body
    from .pdf_source_font_spaces import (face, xref, cmap_space_cid,
                                         pdf_cid_width, ttf_space_width)
    import re

    if (layout.get('source_literal_text') is not True or layout.get('native_tables')
            or layout.get('source_answer_blanks') or layout.get('source_inline_labels')):
        return None
    proof = layout.get('source_question_body') or {}
    meta = layout.get('source_typography') or {}
    records = meta.get('lines') or []
    index, width = layout.get('source_page_index'), float(layout.get('source_page_width_pt', 0))
    if (not proof.get('lines') or not 3 <= len(records) <= 128
            or meta.get('alignment') != 'JUSTIFY'
            or isinstance(index, bool) or not isinstance(index, int) or index < 0
            or not math.isfinite(width) or width <= 0):
        return None
    with fitz.open(layout['source_pdf_path']) as document:
        if index >= len(document) or document[index].rect.width != width:
            return None
        page = document[index]
        groups = split_source_question_body(proof['lines'], page=page, area_hint='영어 영역')
        if len(groups) != 2 or len(groups[1]) != len(records):
            return None
        rows = groups[1]
        spans = [span for row in rows for span in row['spans']]
        # A rejected uniform-body proof must not borrow this mixed-body path.
        if len({(s['font'], s['flags']) for s in spans}) < 2:
            return None
        canonical = _source_typography(rows, {'column_left_pt': layout.get('column_left_pt'),
                                               'column_right_pt': layout.get('column_right_pt')})
        if (any(meta.get(key) != canonical.get(key) for key in
                ('font_name', 'font_size_pt', 'line_spacing_pt', 'alignment',
                 'font_width_percent', 'letter_spacing_percent', 'letter_spacing_sample_count'))
                or any(_line_proof({'bbox': record['bbox_pt'], 'spans': record['spans']})[0]
                       != _line_proof(row)[0] for record, row in zip(records, rows))
                or any(any(record.get(key) != actual.get(key) for key in
                           ('text', 'baseline_pt', 'font_size_pt'))
                       for record, actual in zip(records, canonical['lines']))):
            return None
        raw = [row for block in page.get_text('rawdict')['blocks'] for row in block.get('lines', [])]
        actual_lines, actual_rows = _iter_text_lines(page), []
        for record, row in zip(records, rows):
            matches = [value for value in actual_lines if _line_proof(value)[0] == _line_proof(row)[0]]
            if len(matches) != 1:
                return None
            actual = matches[0]
            for supplied in (record, row):
                if any(bool(char.get('synthetic')) != bool(original.get('synthetic'))
                       for span, original_span in zip(supplied['spans'], actual['spans'])
                       for char, original in zip(span['chars'], original_span['chars'])):
                    return None
            actual_rows.append(actual)
            matches = [value for value in raw if tuple(value['bbox']) == tuple(row['bbox'])]
            if (len(matches) != 1 or matches[0].get('wmode') != 0
                    or tuple(matches[0].get('dir', ())) != (1., 0.)):
                return None
        rows = actual_rows
        terminal = rows[-1]['spans']
        if (len({span['font'] for span in terminal}) != 1
                or any(span['flags'] != 4 for span in terminal)):
            return None
        raw_face = terminal[0]['font']
        if face(raw_face) != 'TimesNewRoman':
            return None
        resources = [font for font in page.get_fonts(full=True) if face(font[3]) == face(raw_face)]
        if len(resources) != 1:
            return None
        font_xref, extension, font_type, *_ = resources[0]
        if extension != 'ttf' or font_type != 'Type0':
            return None
        if document.xref_get_key(font_xref, 'Encoding') != ('name', '/Identity-H'):
            return None
        kind, value = document.xref_get_key(font_xref, 'DescendantFonts')
        descendant = re.fullmatch(r'\[\s*([1-9]\d*) 0 R\s*\]', value or '')
        if kind != 'array' or not descendant:
            return None
        descendant = int(descendant[1])
        if document.xref_get_key(descendant, 'CIDToGIDMap') != ('name', '/Identity'):
            return None
        cid = cmap_space_cid(document.xref_stream(xref(document, font_xref, 'ToUnicode')))
        kind, widths = document.xref_get_key(descendant, 'W')
        if kind != 'array':
            return None
        pdf_cid_width(widths, cid)
        descriptor = xref(document, descendant, 'FontDescriptor')
        program_xref = xref(document, descriptor, 'FontFile2')
        name, extension, _, program = document.extract_font(font_xref)
        if (extension != 'ttf' or face(name) != face(raw_face)
                or program != document.xref_stream(program_xref)):
            return None
        metrics = ttf_space_width(program, cid)
        traces = [trace for trace in page.get_texttrace() if face(trace.get('font', '')) == face(raw_face)
                  and trace.get('type') == 0 and trace.get('opacity') == 1.
                  and trace.get('wmode') == 0 and tuple(trace.get('dir', ())) == (1., 0.)]
        cursor = sum(sum(not c.isspace() for c in _pdf_output_text(char['c']))
                     for row in rows[:-1] for span in row['spans'] for char in span['chars'])
        positions = set()
        for span in terminal:
            chars = span['chars']
            for offset, char in enumerate(chars):
                if char['c'] == ' ':
                    if (char.get('synthetic') or not 0 < offset < len(chars)-1
                            or chars[offset-1]['c'].isspace() or chars[offset+1]['c'].isspace()
                            or abs((char['bbox'][2]-char['bbox'][0])/span['size']-.25) > .0001):
                        return None
                    matches = [(trace, value) for trace in traces for value in trace['chars']
                               if value[0] == 32 and max(abs(a-b) for a, b in
                                   zip(value[2], char['origin'])) < .0001]
                    if (len(matches) != 1 or matches[0][1][1] != cid
                            or abs(matches[0][0]['size']-span['size']) > .0001
                            or matches[0][0]['flags'] != span['flags']):
                        return None
                    following = chars[offset+1]
                    advance = (following['origin'][0]-char['origin'][0])/span['size']
                    if (not math.isfinite(advance)
                            or abs(advance-metrics['advance_width']/metrics['units_per_em']) > .01
                            or abs(following['origin'][1]-char['origin'][1]) > .0001):
                        return None
                    positions.add(cursor)
                cursor += sum(not c.isspace() for c in _pdf_output_text(char['c']))
        if not 1 <= len(positions) <= 64:
            return None
        return rows, dict.fromkeys(positions, (80, -15))


def _native_mixed_body_matches(paragraph, header, page_width, source_width, rows, spaces):
    """Validate every current native character before granting source spaces."""
    from .pdf_layout_writer import _pdf_output_text
    from .pdf_native_typography import _font_name
    from .pdf_source_run_styles import _source_latin_tracking
    from .pdf_word_wrap import join_source_paragraph
    from .pdf_source_question_body import HP, HH

    languages = {'hangul', 'latin', 'hanja', 'japanese', 'other', 'symbol', 'user'}
    scale = float(page_width)/source_width
    if not math.isfinite(scale) or scale <= 0:
        return False
    char_properties = list(header.iter(HH+'charPr'))
    styles = {style.get('id'): style for style in char_properties}
    if len(styles) != len(char_properties) or None in styles:
        return False
    faces = {}
    for node in header.iter(HH+'fontface'):
        language = str(node.get('lang')).lower()
        if language in faces:
            return False
        fonts = node.findall(HH+'font')
        faces[language] = {font.get('id'): font.get('face') for font in fonts}
        if len(faces[language]) != len(fonts):
            return False
    if set(faces) != languages:
        return False
    source = []
    for row in rows:
        for span in row['spans']:
            name, flags = _font_name(span['font']), int(span['flags'])
            height = round(span['size']*scale)
            tracking = _source_latin_tracking(span, name, 0)
            if not 500 <= height <= 1600:
                return False
            source.extend((char, height, name, bool(flags & 16), bool(flags & 2), tracking)
                          for item in span['chars'] for char in _pdf_output_text(item['c'])
                          if not char.isspace())
    def integer(value):
        if isinstance(value, bool):
            raise ValueError('boolean native metric')
        number = float(value)
        if not math.isfinite(number) or number != int(number):
            raise ValueError('nonintegral native metric')
        return int(number)
    cursor, native = 0, ''
    allowed = {HH+tag for tag in ('fontRef', 'ratio', 'spacing', 'relSz', 'offset',
                                 'outline', 'shadow', 'underline', 'bold', 'italic')}
    for run in paragraph:
        if run.tag == HP+'linesegarray':
            continue
        if run.tag != HP+'run' or len(run) != 1 or run[0].tag != HP+'t' or len(run[0]):
            return False
        style = styles.get(run.get('charPrIDRef'))
        if (style is None or any(child.tag not in allowed for child in style)
                or len({child.tag for child in style}) != len(style)
                or any(style.get(key) != value for key, value in
                       (('useFontSpace', '0'), ('useKerning', '0'), ('symMark', 'NONE')))):
            return False
        refs = style.find(HH+'fontRef')
        if refs is None or set(refs.attrib) != languages:
            return False
        for tag in ('outline', 'shadow', 'underline'):
            node = style.find(HH+tag)
            if node is None or node.get('type') != 'NONE':
                return False
        metrics = {}
        for tag in ('ratio', 'spacing', 'relSz', 'offset'):
            node = style.find(HH+tag)
            if node is None or set(node.attrib) != languages:
                return False
            values = {integer(value) for value in node.attrib.values()}
            if len(values) != 1:
                return False
            metrics[tag] = values.pop()
        if metrics['relSz'] != 100 or metrics['offset'] != 0:
            return False
        value = run[0].text or ''
        if not value:
            return False
        native_height = integer(style.get('height'))
        native += value
        for char in value:
            if not source or cursor >= len(source) and not char.isspace():
                return False
            expected = source[min(cursor, len(source)-1)]
            letter, height, name, bold, italic, tracking = expected
            if (native_height != height
                    or any(faces[lang].get(identifier) != name for lang, identifier in refs.attrib.items())
                    or (style.find(HH+'bold') is not None) != bold
                    or (style.find(HH+'italic') is not None) != italic):
                return False
            actual = metrics['ratio'], metrics['spacing']
            if char.isspace():
                if char != ' ' or actual not in ((100, tracking), spaces.get(cursor)):
                    return False
            elif char != letter or actual != (100, tracking):
                return False
            else:
                cursor += 1
    return cursor == len(source) and native == join_source_paragraph(rows)


def source_body_space_styles(layout, *, paragraph=None, header=None, page_width=None):
    """Return source-proved spaces, with a strict optional native consumer gate.

    The original regular-body path is unchanged. Mixed prose receives only
    actual regular-Times terminal spaces, never italic or nonterminal ones.
    A context-bearing consumer gets None when its current native proof fails.
    """
    ordinary = _regular_body_space_styles(layout)
    if ordinary:
        return ordinary
    try:
        result = _mixed_terminal_spaces(layout)
        if result is None:
            return {}
        rows, spaces = result
        if any(value is not None for value in (paragraph, header, page_width)):
            if (paragraph is None or header is None or page_width is None
                    or not _native_mixed_body_matches(paragraph, header, page_width,
                            float(layout['source_page_width_pt']), rows, spaces)):
                return None
        return spaces
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError,
            RuntimeError, UnicodeError, struct.error, OSError,
            fitz.FileNotFoundError, fitz.FileDataError, fitz.EmptyFileError):
        return None if any(value is not None for value in (paragraph, header, page_width)) else {}
