"""Use measured source wraps as caches of ONE editable native paragraph."""
from __future__ import annotations

import re
from statistics import median
from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def source_line_values(records, *, mixed=False):
    """Canonical complete source lines, retaining mathematical grouping."""
    from .pdf_layout_writer import _pdf_output_text, is_hancom_eq_font
    from .hwpx_writer import _hancom_eqn_script

    if not mixed:
        return [re.sub(r"\s+", "", _pdf_output_text(r.get("text", ""))) for r in records]
    from .pdf_native_content import recover_native_scripts

    def source_value(record):
        spans = record.get("spans") or []
        if not spans:
            return ""
        values, pending = [], []

        def flush_math():
            if not pending:
                return True
            expression = "".join(pending)
            pending.clear()
            script = _hancom_eqn_script(expression)
            if not script:
                return False
            values.append(re.sub(r"\s+", "", script))
            return True

        for span in spans:
            value = _pdf_output_text(span.get("text", ""))
            if is_hancom_eq_font(str(span.get("font", ""))):
                value = value.strip().strip("$")
                if value:
                    pending.append(value)
            else:
                if not flush_math():
                    return ""
                values.append(re.sub(r"\s+", "", value))
        if not flush_math():
            return ""
        return "".join(values)

    recovered = recover_native_scripts(records)
    if len(recovered) != len(records):
        return []
    return [source_value(r) for r in recovered]


def apply_source_line_cache(paragraph, layout, width):
    """Fail closed when source lines do not reproduce the complete paragraph.

    No line breaks or positioned text nodes are inserted. Editing invalidates
    this ordinary HWPX line cache and the paragraph can be typeset again.
    """
    meta = layout.get("source_typography") or {}
    records = meta.get("lines") or []
    page_width = float(layout.get("source_page_width_pt") or 0)
    if not records or not page_width:
        return False
    controls = 0
    text = ""
    positions = []
    boundaries = []
    mixed = False
    offset = 0
    hard_breaks = []

    def append_text(value):
        nonlocal text, offset
        for char in value:
            text += char
            if not char.isspace():
                positions.append(offset)
                boundaries.append(True)
            offset += len(char.encode('utf-16-le')) // 2

    for run in paragraph.findall(HP + "run"):
        for child in run:
            if child.tag == HP + "t":
                if any(c.tag != HP + 'lineBreak' or len(c) or c.text for c in child):
                    return False
                append_text(child.text or '')
                for control in child:
                    hard_breaks.append(len(positions))
                    append_text('\n')
                    append_text(control.tail or '')
            elif child.tag == HP + 'lineBreak':
                hard_breaks.append(len(positions))
                append_text('\n')
            elif (child.tag == HP + "pic" and not text
                  and (pos := child.find(HP + "pos")) is not None
                  and pos.get("treatAsChar") == "0"
                  and child.get("textWrap") == "SQUARE"):
                controls += 1
                offset += 8
            elif child.tag == HP + "equation":
                # Keep grouping braces: x^{a+b} and x^a+b must not be treated
                # as the same expression when borrowing source geometry.
                value = re.sub(r"\s+", "", child.findtext(HP + "script", ""))
                if not value:
                    return False
                text += value
                positions.extend([offset] * len(value))
                boundaries.extend([True] + [False] * (len(value) - 1))
                offset += 8
                mixed = True
            elif child.tag == HP + "rect":
                from .pdf_inline_labels import inline_label_text
                value = inline_label_text(child)
                if value is None:
                    return False
                text += value
                positions.extend([offset] * len(value))
                boundaries.extend([True] + [False] * (len(value) - 1))
                offset += 8
                mixed = True
            else:
                return False
    values = source_line_values(records, mixed=mixed)
    if len(values) != len(records) or not all(values) or "".join(values) != re.sub(r"\s+", "", text):
        return False
    source_boundaries = {sum(map(len, values[:i])) for i in range(1, len(values))}
    if len(hard_breaks) != len(set(hard_breaks)) or any(b not in source_boundaries for b in hard_breaks):
        # Preserve intentional native breaks only at measured source line
        # boundaries. A forged break in a word cannot borrow this cache.
        return False
    scale = float(layout.get("native_page_width") or 59528) / page_width
    left = float(layout.get("column_left_pt") or min(r["bbox_pt"][0] for r in records))
    size = float(meta.get("font_size_pt") or 0) * scale
    if size <= 0:
        return False
    gaps = [(b["baseline_pt"] - a["baseline_pt"]) * scale
            for a, b in zip(records, records[1:])]
    if any(gap < size * .8 or gap > size * 3 for gap in gaps):
        return False
    step = median(gaps) if gaps else max(size, float(meta.get("line_spacing_pt") or size / scale * 1.5) * scale)
    offsets = [(record["bbox_pt"][0] - left) * scale for record in records]
    if any(x < -2 or x >= width - size for x in offsets):
        return False
    cache = etree.Element(HP + "linesegarray")
    from hwpx.tools.paragraph_spacing import line_left_margin
    margin_left, margin_right, indent = layout.get("native_indentation", (0, 0, 0))
    start = top = 0
    for index, (record, value, x) in enumerate(zip(records, values, offsets)):
        if not boundaries[start]:
            # A source wrap cannot split an indivisible native equation.
            return False
        native_left = line_left_margin(margin_left, indent, index)
        relative_x = x - native_left
        if relative_x < -2:
            return False
        # A line beside an attached figure can use a smaller interval. Full
        # source lines and the final short line keep the normal column width.
        available = width - max(0, x) - margin_right
        if controls:
            from hwpx.tools.paragraph_floats import available_interval
            interval_start, interval_width = available_interval(paragraph, width, top, size)
            if x < interval_start - 2:
                return False
            available = min(interval_start + interval_width, width) - max(0, x) - margin_right
            if available < size:
                return False
        if (record["bbox_pt"][2] - record["bbox_pt"][0]) * scale > available + size * .2:
            return False
        line_step = gaps[index] if index < len(gaps) else step
        height, baseline = size, size * .85
        if mixed:
            box = record["bbox_pt"]
            height = max(size, (box[3] - box[1]) * scale)
            baseline = (record["baseline_pt"] - box[1]) * scale
            if index < len(gaps):
                # Equation ascenders vary. Measured baseline gaps are not
                # interchangeable with gaps between the tops of line boxes.
                line_step = (records[index + 1]["bbox_pt"][1] - box[1]) * scale
            if not 0 < baseline <= height or (index < len(gaps) and height > line_step):
                return False
        etree.SubElement(cache, HP + "lineseg", textpos=str(0 if index == 0 else positions[start]),
                         vertpos=str(round(top)), vertsize=str(round(height)), textheight=str(round(height)),
                         baseline=str(round(baseline)), spacing=str(max(0, round(line_step - height))),
                         horzpos=str(max(0, round(relative_x))),
                         horzsize=str(max(1, round(available + native_left + margin_right))), flags="393216")
        start += len(value)
        top += line_step
    old = paragraph.find(HP + "linesegarray")
    if old is not None:
        paragraph.remove(old)
    paragraph.append(cache)
    return True
