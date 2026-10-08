"""Restore source fonts within a fully matched editable text item."""
from copy import deepcopy
import math
import re
from statistics import median

from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _source_latin_tracking(span, font, default, *, source_proved=False):
    """Measure Times tracking, or another face with independently proved spans."""
    if font not in {"Times New Roman", "Times-Roman"} and not source_proved:
        return default
    size = float(span.get("size") or 0)
    if not math.isfinite(size) or size <= 0:
        return default
    samples = []
    chars = span.get("chars") or []
    for left, right in zip(chars, chars[1:]):
        if not (re.fullmatch(r"[A-Za-z]", str(left.get("c") or ""))
                and re.fullmatch(r"[A-Za-z]", str(right.get("c") or ""))):
            continue
        a, b, box = left.get("origin"), right.get("origin"), left.get("bbox")
        if (not a or not b or not box or not all(math.isfinite(float(v)) for v in (*a, *b, *box))
            or abs(a[1] - b[1]) > .1):
            continue
        advance, width = b[0] - a[0], box[2] - box[0]
        if min(advance, width) <= 0:
            continue
        sample = (advance - width) / size * 100
        if -15 <= sample <= 15:
            samples.append(sample)
    # A single kerning pair cannot prove a span's uniform tracking. The median
    # of several adjacent letters distinguishes actual PDF character spacing.
    if len(samples) >= (3 if source_proved else 4):
        return round(median(samples))
    if source_proved:
        # Short numeric/punctuation runs can still contain several actual
        # advances. Use these only after every glyph and transform has been
        # independently matched to the original PDF.
        samples = []
        for left, right in zip(chars, chars[1:]):
            if not (re.fullmatch(r"[A-Za-z0-9.,:;!?-]", left['c'])
                    and re.fullmatch(r"[A-Za-z0-9.,:;!?-]", right['c'])):
                continue
            advance = right['origin'][0]-left['origin'][0]
            width = left['bbox'][2]-left['bbox'][0]
            sample = (advance-width)/size*100
            if (abs(left['origin'][1]-right['origin'][1]) <= .1
                and min(advance, width) > 0 and -15 <= sample <= 15):
                samples.append(sample)
        if len(samples) >= 4:
            return round(median(samples))
    return default


def restore_source_run_styles(root, layout, page_width, char_style, *, protected_styles=()):
    """Keep semantic paragraphs intact; split runs only at proven font changes.

    The complete source and native text must match before any style changes.
    Equations, inline labels and unfamiliar text controls keep their existing
    typography path. Underlined answer whitespace retains its measured style.
    """
    from .pdf_layout_writer import _pdf_output_text, is_hancom_eq_font
    from .pdf_native_typography import _font_name

    meta = layout.get("source_typography") or {}
    records = meta.get("lines") or []
    source_width = float(layout.get("source_page_width_pt") or 0)
    if not records or not source_width:
        return 0
    paragraphs = list(root.iter(HP + "p"))
    texts = []
    for paragraph in paragraphs:
        for run in paragraph.findall(HP + "run"):
            # A table is a container, rather than prose in its owning run.
            if all(child.tag == HP + "tbl" for child in run):
                continue
            if any(child.tag != HP + "t" or len(child) for child in run):
                return 0
            texts.extend(child.text or "" for child in run)
    compact = lambda value: re.sub(r"\s+", "", value)
    spacing = max(-15, min(15, round(float(meta.get("letter_spacing_percent") or 0))))
    ratio = max(80, min(110, round(float(meta.get("font_width_percent") or 100))))
    from .pdf_source_span_metrics import wrapped_source_span_ratios, wrapped_source_synthetic_spaces
    span_ratios = wrapped_source_span_ratios(layout) if layout.get("source_literal_text") else {}
    if layout.get("source_literal_text") and not span_ratios:
        from .pdf_source_body_metrics import body_source_span_ratios
        span_ratios = body_source_span_ratios(layout)
    source_spaces = wrapped_source_synthetic_spaces(layout) if span_ratios else {}
    if layout.get('source_literal_text') and not source_spaces:
        from .pdf_source_choice_spaces import source_choice_space_styles
        source_spaces = source_choice_space_styles(layout)
    if layout.get('source_literal_text') and not source_spaces:
        from .pdf_source_body_spaces import source_body_space_styles
        source_spaces = source_body_space_styles(layout)
    source, styles = [], []
    for row_index, record in enumerate(records):
        for span_index, span in enumerate(record.get("spans") or []):
            font = str(span.get("font") or "")
            if is_hancom_eq_font(font):
                return 0
            value = compact(_pdf_output_text(span.get("text", "")))
            size = float(span.get("size") or 0)
            if value and (not font or size <= 0):
                return 0
            flags = int(span.get("flags") or 0)
            name = _font_name(font)
            measured_ratio = span_ratios.get((row_index, span_index))
            tracking = (_source_latin_tracking(span, name, spacing, source_proved=measured_ratio is not None)
                        if layout.get("source_literal_text") else spacing)
            style = (name, size, bool(flags & 16 or "bold" in font.lower()),
                     bool(flags & 2 or "italic" in font.lower()), tracking,
                     measured_ratio if measured_ratio is not None else ratio)
            source.extend(value)
            styles.extend([style] * len(value))
    if not source or "".join(source) != compact("".join(texts)):
        return 0
    # Keep the existing source-font path for a uniform family/style. Number
    # glyphs and drop capitals can have different source sizes within that
    # path; restore mixed faces/styles and separately proved horizontal scale
    # or tracking, whose loss otherwise changes the actual source advances.
    if (len({(font, bold, italic) for font, _size, bold, italic, _tracking, _ratio in styles}) == 1
            and not source_spaces and not any(tracking != spacing or span_ratio != ratio
                        for _font, _size, _bold, _italic, tracking, span_ratio in styles)):
        return 0
    scale = page_width / source_width
    cursor, changed = 0, 0
    native_text = ''.join(texts)
    native_offset = 0
    for paragraph in paragraphs:
        for run in list(paragraph.findall(HP + "run")):
            if all(child.tag == HP + "tbl" for child in run):
                continue
            if run.get("charPrIDRef") in protected_styles:
                continue
            groups = []
            for child in run:
                for char in child.text or "":
                    style = styles[min(cursor, len(styles) - 1)]
                    if (char == ' ' and cursor in source_spaces
                        and 0 < native_offset < len(native_text)-1
                        and not native_text[native_offset-1].isspace()
                        and not native_text[native_offset+1].isspace()):
                        space_ratio, space_tracking = source_spaces[cursor]
                        font, size, bold, italic, _, _ = style
                        style = (font, size, bold, italic, space_tracking, space_ratio)
                    if not char.isspace():
                        cursor += 1
                    native_offset += 1
                    if groups and groups[-1][0] == style:
                        groups[-1][1] += char
                    else:
                        groups.append([style, char])
            index = paragraph.index(run)
            for offset, ((font, size, bold, italic, tracking, span_ratio), value) in enumerate(groups):
                replacement = deepcopy(run)
                for child in list(replacement):
                    replacement.remove(child)
                replacement.set("charPrIDRef", char_style(
                    run.get("charPrIDRef", "0"), max(500, min(1600, size * scale)),
                    font, tracking, span_ratio, bold, italic=italic))
                etree.SubElement(replacement, HP + "t").text = value
                paragraph.insert(index + offset, replacement)
                changed += 1
            paragraph.remove(run)
    return changed
