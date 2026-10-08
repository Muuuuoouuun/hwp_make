"""Separate a source-proven exam instruction from its indented prose body."""
from copy import deepcopy
from math import isfinite
import re
from statistics import median
import unicodedata

import fitz

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"


def _numbers(value, length):
    if not isinstance(value, (list, tuple, fitz.Rect)) or len(value) != length:
        raise ValueError("unsupported source geometry")
    values = tuple(float(number) for number in value)
    if not all(isfinite(number) for number in values):
        raise ValueError("nonfinite source geometry")
    return values


def _line_proof(line):
    from .pdf_layout_writer import is_hancom_eq_font

    spans, glyphs, signatures = line.get("spans") or [], [], []
    if not spans:
        raise ValueError("missing source spans")
    for span in spans:
        font, size = span.get("font"), float(span.get("size", 0))
        flags = float(span.get("flags", 0))
        chars = span.get("chars") or []
        bounds = _numbers(span.get("bbox"), 4)
        origin = _numbers(span.get("origin"), 2)
        if (not font or is_hancom_eq_font(font) or not isfinite(size) or size <= 0
                or not isfinite(flags) or flags != int(flags) or flags < 0
                or not chars or "".join(c.get("c", "") for c in chars) != span.get("text")):
            raise ValueError("unsupported source text")
        raw = []
        for char in chars:
            text = char.get("c")
            if not isinstance(text, str) or len(text) != 1:
                raise ValueError("unsupported source character")
            box, position = _numbers(char.get("bbox"), 4), _numbers(char.get("origin"), 2)
            if box[2] < box[0] or box[3] <= box[1]:
                raise ValueError("invalid source character box")
            raw.append((text, box, position))
            glyphs.append((text, box, position, font, size))
        union = (min(c[1][0] for c in raw), min(c[1][1] for c in raw),
                 max(c[1][2] for c in raw), max(c[1][3] for c in raw))
        if any(abs(a - b) > .1 for a, b in zip(bounds, union)):
            raise ValueError("source span does not cover its characters")
        signatures.append((font, size, int(flags), bounds, origin, tuple(raw)))
    bounds = _numbers(line.get("bbox"), 4)
    union = (min(s[3][0] for s in signatures), min(s[3][1] for s in signatures),
             max(s[3][2] for s in signatures), max(s[3][3] for s in signatures))
    if any(abs(a - b) > .1 for a, b in zip(bounds, union)):
        raise ValueError("source line does not cover its spans")
    return tuple(signatures), glyphs


def source_question_body_complete(page, instruction, body, *, source_lines=None):
    """Prove the complete actual column band and its vocabulary/choice end.

    This complements the splitter's raw/style/rail proof. A raw source subset
    is not permission to omit terminal body rows, even if native text and its
    cache were shortened together. A star alone does not identify a note.
    """
    try:
        from .pdf_layout_writer import _iter_text_lines, _pdf_output_text

        if page is None or not instruction or len(body) < 3:
            return False
        actual = _iter_text_lines(page)
        signatures = [_line_proof(row)[0] for row in actual]
        if (source_lines is not None and
                [_line_proof(row)[0] for row in source_lines] != signatures):
            return False
        supplied = [*instruction, *body]
        if any(_line_proof(row)[0] not in signatures for row in supplied):
            return False
        chars = lambda row: [c for c in _line_proof(row)[1] if c[0].strip()]
        size = median(c[4] for row in body for c in chars(row))
        left = min(c[2][0] for row in instruction for c in chars(row))
        right = median(max(c[1][2] for c in chars(row)) for row in body[:-1])
        def in_column(row):
            return left - .1 <= row["bbox"][0] <= right + size * .1
        order = lambda row: (row["bbox"][1], row["bbox"][0])
        band = sorted((row for row in actual if in_column(row)
                       and row["bbox"][1] >= instruction[0]["bbox"][1] - .1
                       and row["bbox"][3] <= body[-1]["bbox"][3] + .1), key=order)
        if [_line_proof(row)[0] for row in band] != [_line_proof(row)[0] for row in supplied]:
            return False
        following = sorted((row for row in actual if in_column(row)
                            and row["bbox"][1] >= body[-1]["bbox"][3] - .1), key=order)
        previous_baseline = median(c[2][1] for c in chars(body[-1]))
        for row in following[:4]:
            value = _pdf_output_text("".join(s["text"] for s in row["spans"])).strip()
            if value.startswith("*"):
                glyphs = chars(row)
                baseline = median(c[2][1] for c in glyphs)
                if (not re.fullmatch(r"\*\s*[A-Za-z][A-Za-z'’ -]*:\s*(?=[^\r\n]*[가-힣])[^①-⑳\r\n:]+", value)
                        or not size * .65 <= min(c[4] for c in glyphs)
                        <= max(c[4] for c in glyphs) < size * .98
                        or not size * .5 < baseline - previous_baseline < size * 2.5
                        or not 0 <= row["bbox"][1] - body[-1]["bbox"][3] <= size * 3):
                    return False
                previous_baseline = baseline
                continue
            return value.startswith("①") and 0 <= row["bbox"][1] - body[-1]["bbox"][3] <= size * 4
        return False
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, AttributeError):
        return False


def _times_body_style(lines):
    """Permit source regular/italic Times and one baseline-aligned dash fallback."""
    from .pdf_native_typography import _font_name

    rows = [[c for c in _line_proof(line)[1] if c[0].strip()] for line in lines]
    primary = [c for row in rows for c in row if _font_name(c[3]) == "Times New Roman"]
    fallback = [c for row in rows for c in row if _font_name(c[3]) != "Times New Roman"]
    if not primary:
        return None
    sizes = [c[4] for c in primary]
    size = median(sizes)
    if max(sizes) - min(sizes) > .1:
        return None
    for line in lines:
        for span in line["spans"]:
            flags = float(span.get("flags", 0))
            if flags not in (4, 6):
                return None
            if (_font_name(span["font"]) == "Times New Roman"
                    and bool(int(flags) & 2) != ("italic" in span["font"].lower())):
                return None
    if fallback:
        if (len(fallback) != 1 or unicodedata.category(fallback[0][0]) != "Pd"
                or not size * .8 <= fallback[0][4] <= size):
            return None
        row = next(row for row in rows if fallback[0] in row)
        baselines = [c[2][1] for c in row if _font_name(c[3]) == "Times New Roman"]
        if not baselines or abs(fallback[0][2][1] - median(baselines)) > size * .03:
            return None
    return primary[0][3], size


def split_source_question_body(lines, *, page=None, area_hint="", answer_blanks=(),
                               existing_boundary=False):
    """Return the original group unless raw source proves two semantic parts.

    A Korean numbered instruction followed by uniformly styled Latin prose
    has a different continuation rail and an indented first body line. These
    are paragraph boundaries, rather than per-line cache positions that a
    native editor cannot retain after reflow. No text or run style is changed.
    """
    original = [lines]
    if page is None or re.sub(r"\s+", "", area_hint) != "영어영역" or len(lines) < 4:
        return original
    try:
        from .pdf_layout_writer import _iter_text_lines

        proofs = [_line_proof(line) for line in lines]
        texts = ["".join(c[0] for c in proof[1]).strip() for proof in proofs]
        if not re.match(r"^\d{1,3}[.)]\s*", texts[0]):
            return original
        start = next((index for index, text in enumerate(texts[1:], 1)
                      if len(re.findall(r"[A-Za-z]", text)) >= 20
                      and not re.search(r"[가-힣]", text)), None)
        if (start is None or start > 3 or len(lines) - start < 3
                or any(not re.search(r"[가-힣]", text) for text in texts[:start])
                or any(re.search(r"[가-힣①-⑳]|^\s*\d+[.)]|[_＿]{2,}", text)
                       for text in texts[start:])):
            return original
        source_lines = _iter_text_lines(page)
        source = {_line_proof(line)[0] for line in source_lines}
        if any(signature not in source for signature, _ in proofs):
            return original
        from .pdf_answer_blanks import measure_answer_blanks
        actual_blanks = measure_answer_blanks(page, source_lines, area_hint=area_hint)
        if any(max(abs(a - b) for a, b in zip(blank["line_bbox_pt"], line["bbox"])) < .1
               for blank in [*answer_blanks, *actual_blanks] for line in lines):
            return original
        body = [[char for char in glyphs if char[0].strip()] for _, glyphs in proofs[start:]]
        if any(not row for row in body):
            return original
        fonts = {char[3] for row in body for char in row}
        sizes = [char[4] for row in body for char in row]
        size = median(sizes)
        if len(fonts) == 1 and max(sizes) - min(sizes) <= .1:
            font = next(iter(fonts))
        else:
            style = _times_body_style(lines[start:])
            if style is None:
                return original
            font, size = style
        shared_font = any(char[3] == font for _, chars in proofs[:start]
                          for char in chars if re.search(r"[가-힣]", char[0]))
        if shared_font and existing_boundary is not True:
            return original
        rails = [row[0][2][0] for row in body]
        continuation = median(rails[1:])
        instruction = next(char[2][0] for char in proofs[0][1] if char[0].strip())
        baselines = [median(char[2][1] for char in row) for row in body]
        steps = [b - a for a, b in zip(baselines, baselines[1:])]
        step = median(steps)
        previous = median(char[2][1] for char in proofs[start - 1][1] if char[0].strip())
        if (max(abs(rail - continuation) for rail in rails[1:]) > size * .03
                or not size * .4 < rails[0] - continuation < size * 2
                or not size * .4 < continuation - instruction < size * 2
                or not size < step < size * 1.8
                or max(abs(value - step) for value in steps) > size * .03
                or not step * 1.15 < baselines[0] - previous < size * 2.5):
            return original
        region = fitz.Rect(min(c[1][0] for row in body for c in row),
                           min(c[1][1] for row in body for c in row),
                           max(c[1][2] for row in body for c in row),
                           max(c[1][3] for row in body for c in row))
        if any(region.intersects(fitz.Rect(image["bbox"])) for image in page.get_image_info()):
            return original
        if not source_question_body_complete(page, lines[:start], lines[start:],
                                             source_lines=source_lines):
            return original
        if shared_font:
            from .pdf_source_body_metrics import source_body_span_ratios

            ratios = source_body_span_ratios(page, lines[start:])
            if len(ratios) != sum(len(line["spans"]) for line in lines[start:]):
                return original
        return [lines[:start], lines[start:]]
    except (ValueError, TypeError, KeyError, IndexError, StopIteration, OverflowError):
        return original


def restore_source_instruction_cache(paragraph, layout, header, page_width, width):
    """Use each proved instruction row's tallest native/source run height.

    A tall numbered marker belongs to the same printed instruction line as
    smaller Korean text. Borrowing the dominant font's height makes the reader
    add line-height correction before the following body paragraph. The
    source/native per-character size match is required; run styles stay intact.
    """
    proof = layout.get("source_question_instruction") or {}
    if (not layout.get("source_literal_text") or not proof.get("lines")
            or not layout.get("source_pdf_path") or layout.get("source_answer_blanks")):
        return False
    try:
        from .pdf_source_line_cache import apply_source_line_cache
        from .pdf_native_content import _source_typography
        from .pdf_layout_writer import _pdf_output_text

        page_width, width = float(page_width), float(width)
        source_width = float(layout.get("source_page_width_pt", 0))
        page_index = layout.get("source_page_index")
        if (not all(isfinite(n) and n > 0 for n in (page_width, width, source_width))
                or isinstance(page_index, bool) or not isinstance(page_index, int) or page_index < 0):
            return False
        if (len(paragraph.findall(HP + "linesegarray")) != 1
                or any(node.tag not in (HP + "run", HP + "linesegarray") for node in paragraph)):
            return False
        with fitz.open(layout["source_pdf_path"]) as document:
            if page_index >= len(document) or abs(document[page_index].rect.width - source_width) > .01:
                return False
            groups = split_source_question_body(proof["lines"], page=document[page_index],
                                                area_hint="영어 영역", existing_boundary=True)
        if len(groups) != 2:
            return False
        expected = [char for line in groups[0] for char in _line_proof(line)[1]
                    if char[0].strip()]
        records = (layout.get("source_typography") or {}).get("lines") or []
        actual_meta = _source_typography(groups[0], {
            "column_left_pt": layout.get("column_left_pt"),
            "column_right_pt": layout.get("column_right_pt")})
        meta = layout.get("source_typography") or {}
        if (len(records) != len(groups[0]) or any(_line_proof({"bbox": record["bbox_pt"],
                "spans": record["spans"]})[0] != _line_proof(line)[0]
                for record, line in zip(records, groups[0]))
                or any(meta.get(key) != actual_meta.get(key) for key in
                       ("font_name", "font_size_pt", "line_spacing_pt", "alignment"))
                or any(any(record.get(key) != actual.get(key) for key in
                           ("text", "baseline_pt", "font_size_pt"))
                       for record, actual in zip(records, actual_meta["lines"]))):
            return False
        properties = {node.get("id"): node for node in header.iter(HH + "charPr")}
        native, positions, offset = [], [], 0
        for run in paragraph.findall(HP + "run"):
            style = properties.get(run.get("charPrIDRef"))
            if style is None or len(run) != 1 or run[0].tag != HP + "t" or len(run[0]):
                return False
            height = float(style.get("height", 0))
            if not isfinite(height) or height <= 0 or int(height) != height:
                return False
            for char in run[0].text or "":
                positions.append((char, height, offset))
                offset += len(char.encode("utf-16-le")) // 2
                if char.strip():
                    native.append((char, height))
        scale = page_width / source_width
        if (len(native) != len(expected) or any(char != _pdf_output_text(source[0])
                or abs(height - round(source[4] * scale)) > 1
                for (char, height), source in zip(native, expected))):
            return False
        source_size = max(char[4] for char in expected)
        if round(source_size * scale) < max(height for _, height in native):
            return False
        para_styles = {node.get("id"): node for node in header.iter(HH + "paraPr")}
        margin = para_styles[paragraph.get("paraPrIDRef")].find(".//" + HH + "margin")
        indentation = tuple(_integer(margin.find(HC + key).get("value"),
                                     minimum=-1000000 if key == "intent" else 0)
                            for key in ("left", "right", "intent"))
        candidate = {**layout, "native_page_width": page_width,
                     "native_indentation": indentation, "source_typography": {
            **layout["source_typography"], "font_size_pt": source_size}}
        probe = deepcopy(paragraph)
        if not apply_source_line_cache(probe, candidate, width):
            return False
        old, cache = paragraph.find(HP + "linesegarray"), probe.find(HP + "linesegarray")
        if len(records) > 1:
            starts = [_integer(row.get("textpos")) for row in cache]
            boundaries = {position for _, _, position in positions}
            if (len(starts) != len(records) or starts[0] != 0
                    or starts != sorted(set(starts)) or starts[-1] >= offset
                    or any(start not in boundaries for start in starts)):
                return False
            starts.append(offset)
            heights, baselines = [], []
            for index, line in enumerate(groups[0]):
                row_native = [(char, height) for char, height, position in positions
                              if starts[index] <= position < starts[index + 1] and char.strip()]
                row_source = [char for char in _line_proof(line)[1] if char[0].strip()]
                if (len(row_native) != len(row_source) or any(char != _pdf_output_text(source[0])
                        or abs(height - round(source[4] * scale)) > 1
                        for (char, height), source in zip(row_native, row_source))):
                    return False
                size = max(char[4] for char in row_source) * scale
                if round(size) < max(height for _, height in row_native):
                    return False
                heights.append(round(size))
                baselines.append(round(size * .85))
            # Top-to-top advances account for the rows' different baselines,
            # so their original source baseline gaps remain exact.
            tops = [round((record["baseline_pt"] - records[0]["baseline_pt"]) * scale
                          + baselines[0] - baseline)
                    for record, baseline in zip(records, baselines)]
            last_step = round((records[-1]["baseline_pt"] - records[-2]["baseline_pt"]) * scale)
            steps = [b - a for a, b in zip(tops, tops[1:])] + [last_step]
            if tops[0] != 0 or any(step < height for step, height in zip(steps, heights)):
                return False
            for row, top, height, baseline, step in zip(cache, tops, heights, baselines, steps):
                for key, value in (("vertpos", top), ("vertsize", height), ("textheight", height),
                                   ("baseline", baseline), ("spacing", step - height)):
                    row.set(key, str(value))
        if old is not None:
            paragraph.remove(old)
        paragraph.append(cache)
        return True
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError, OSError,
            fitz.FileNotFoundError, fitz.FileDataError, fitz.EmptyFileError):
        return False


def _integer(value, *, minimum=0):
    number = float(value)
    if not isfinite(number) or number != int(number) or number < minimum:
        raise ValueError("invalid native paragraph metric")
    return int(number)


def _body_right(paragraph, layout, header, page_width, width):
    """Reprove actual source and native text before measuring a right margin."""
    from .pdf_native_typography import _font_name
    from .pdf_word_wrap import join_source_paragraph
    from .pdf_layout_writer import _pdf_output_text
    from .pdf_source_run_styles import _source_latin_tracking
    from .pdf_source_body_spaces import source_body_space_styles
    from .pdf_native_content import _source_typography
    from .pdf_source_line_cache import apply_source_line_cache

    proof = layout.get("source_question_body") or {}
    if (not proof.get("lines") or not layout.get("source_literal_text")
            or not layout.get("source_pdf_path") or layout.get("source_answer_blanks")
            or layout.get("native_tables") or layout.get("source_inline_labels")):
        return None
    page_width, width = float(page_width), float(width)
    source_width = float(layout.get("source_page_width_pt", 0))
    if not all(isfinite(v) and v > 0 for v in (page_width, width, source_width)):
        return None
    index = layout.get("source_page_index")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        return None
    with fitz.open(layout["source_pdf_path"]) as document:
        if index >= len(document) or abs(document[index].rect.width-source_width) > .01:
            return None
        groups = split_source_question_body(proof["lines"], page=document[index],
                                            area_hint="영어 영역", existing_boundary=True)
    if len(groups) != 2 or len(groups[1]) < 4:
        return None
    body = groups[1]
    meta = layout.get("source_typography") or {}
    actual_meta = _source_typography(body, {"column_left_pt": layout.get("column_left_pt"),
                                          "column_right_pt": layout.get("column_right_pt")})
    records = meta.get("lines") or []
    if (str(meta.get("alignment", "")).upper() != "JUSTIFY" or len(records) != len(body)
            or any(_line_proof({"bbox": r["bbox_pt"], "spans": r["spans"]})[0]
                   != _line_proof(line)[0] for r, line in zip(records, body))
            or any(meta.get(key) != actual_meta.get(key) for key in
                   ("font_name", "font_size_pt", "line_spacing_pt", "alignment"))
            or any(any(record.get(key) != actual.get(key) for key in
                       ("text", "baseline_pt", "font_size_pt"))
                   for record,actual in zip(records,actual_meta["lines"]))):
        return None
    rail = float(layout.get("column_left_pt", float("nan")))
    instruction = next(char for line in groups[0] for char in _line_proof(line)[1] if char[0].strip())
    if not isfinite(rail) or abs(rail-instruction[2][0]) > .05:
        return None
    # Only the actual, plain question textbox width is used. Line-segment sw
    # is not an available-width override in this renderer's ordinary path.
    if any(a.tag == HP+"tc" for a in paragraph.iterancestors()):
        return None
    sub = paragraph.getparent()
    draw = sub.getparent() if sub is not None else None
    rect = draw.getparent() if draw is not None else None
    if (sub is None or sub.tag != HP+"subList" or draw is None or draw.tag != HP+"drawText"
            or draw.get("editable") != "1" or rect is None or rect.tag != HP+"rect"):
        return None
    widths = [width, float(sub.get("textWidth", 0)), float(draw.get("lastWidth", 0)),
              float(rect.find(HP+"sz").get("width", 0))]
    if not all(isfinite(v) and v > 0 and abs(v-width) <= 1 for v in widths):
        return None
    expected_text = join_source_paragraph(body)
    native_text, native_chars = "", []
    properties = {p.get("id"): p for p in header.iter(HH+"charPr")}
    fonts = {font.get("id"): font.get("face") for face in header.iter(HH+"fontface")
             if str(face.get("lang")).upper() == "LATIN" for font in face.findall(HH+"font")}
    all_fonts = {str(face.get("lang")).lower(): {font.get("id"): font.get("face")
                 for font in face.findall(HH+"font")} for face in header.iter(HH+"fontface")}
    for node in paragraph:
        if node.tag == HP+"linesegarray":
            continue
        if node.tag != HP+"run" or len(node) != 1 or node[0].tag != HP+"t" or len(node[0]):
            return None
        style = properties.get(node.get("charPrIDRef"))
        if style is None:
            return None
        height = _integer(style.get("height"), minimum=1)
        font_ref = style.find(HH+"fontRef")
        underline = style.find(HH+"underline")
        if font_ref is None or (underline is not None and underline.get("type") != "NONE"):
            return None
        if (any(style.get(key) != value for key,value in
                (("useFontSpace","0"),("useKerning","0"),("symMark","NONE")))
                or any(node.get("type") != "NONE" for tag in ("outline","shadow")
                       for node in style.findall(HH+tag))
                or any(style.find(HH+tag) is not None for tag in ("strikeout","emboss","engrave"))):
            return None
        text = node[0].text or ""
        if (set(font_ref.attrib) != set(all_fonts)
                or any(all_fonts[lang].get(identifier) != fonts.get(font_ref.get("latin"))
                       for lang, identifier in font_ref.attrib.items())):
            return None
        native_text += text
        native_chars.extend((char, height, fonts.get(font_ref.get("latin")),
                             style.find(HH+"bold") is not None, style.find(HH+"italic") is not None)
                            for char in text if not char.isspace())
    if native_text != expected_text:
        return None
    source_chars = [char for line in body for char in _line_proof(line)[1] if char[0].strip()]
    if (any(_font_name(char[3]) != "Times New Roman" for char in source_chars)
            and _times_body_style(body) is None):
        return None
    scale = page_width/source_width
    if len(native_chars) != len(source_chars):
        return None
    source_flags = [int(span.get("flags", 0)) for line in body for span in line["spans"]
                    for char in span["chars"] if char["c"].strip()]
    for (char,height,font,bold,italic),source,flags in zip(native_chars,source_chars,source_flags):
        if (char != _pdf_output_text(source[0]) or abs(height-round(source[4]*scale)) > 1
                or font != _font_name(source[3]) or bold != bool(flags & 16)
                or italic != bool(flags & 2)):
            return None
    letter_spacing = [_source_latin_tracking(span, _font_name(span["font"]), 0)
                      for line in body for span in line["spans"]
                      for char in span["chars"] if char["c"].strip()]
    spaces = source_body_space_styles(layout, paragraph=paragraph, header=header, page_width=page_width)
    if spaces is None:
        return None
    cursor = 0
    for run in paragraph.findall(HP+"run"):
        style = properties[run.get("charPrIDRef")]
        if any(style.find(HH+tag) is not None for tag in ("supscript","superscript","subscript")):
            return None
        metrics = {}
        for tag,default in (("ratio",100),("spacing",0),("relSz",100),("offset",0)):
            metric = style.find(HH+tag)
            if metric is None:
                return None
            if set(metric.attrib) != {"hangul","latin","hanja","japanese","other","symbol","user"}:
                return None
            values = [_integer(value, minimum=-1000) for value in metric.attrib.values()]
            if not values or len(set(values)) != 1:
                return None
            metrics[tag] = values[0]
            if tag in ("relSz","offset") and metrics[tag] != default:
                return None
        for char in run[0].text or "":
            tracking = letter_spacing[min(cursor,len(letter_spacing)-1)]
            expected = (100, tracking)
            actual = metrics["ratio"],metrics["spacing"]
            if char.isspace():
                if char != " " or actual not in (expected, spaces.get(cursor)):
                    return None
                # Run restoration assigns whitespace the adjacent next
                # proved source character's face/size/style, then changes
                # only a proved space's ratio and tracking.
                source_index = min(cursor, len(source_chars) - 1)
                source, flags = source_chars[source_index], source_flags[source_index]
                font_ref = style.find(HH+"fontRef")
                if (font_ref is None or set(font_ref.attrib) != set(all_fonts)
                        or any(all_fonts[lang].get(identifier) != _font_name(source[3])
                               for lang, identifier in font_ref.attrib.items())
                        or abs(_integer(style.get("height"), minimum=1) - round(source[4]*scale)) > 1
                        or (style.find(HH+"bold") is not None) != bool(flags & 16)
                        or (style.find(HH+"italic") is not None) != bool(flags & 2)):
                    return None
            else:
                if actual != expected:
                    return None
                cursor += 1
    # Native caches must still cover exactly the original source wraps. An
    # edited body, omitted first character or forged line cannot borrow them.
    caches = paragraph.findall(HP+"linesegarray")
    cache = caches[0] if len(caches) == 1 else None
    if cache is None or len(cache) != len(body):
        return None
    boundaries, position = {0:0}, 0
    for offset,char in enumerate(native_text,1):
        position += len(char.encode("utf-16-le"))//2
        boundaries[position] = offset
    offsets = [_integer(line.get("textpos")) for line in cache]
    if (not offsets or offsets[0] != 0 or any(a >= b for a,b in zip(offsets,offsets[1:]))
            or any(offset not in boundaries for offset in offsets)):
        return None
    for row,line,start,end in zip(body,cache,offsets,[*offsets[1:],position]):
        if native_text[boundaries[start]:boundaries[end]].strip() != join_source_paragraph([row]):
            return None
        metrics = {key:_integer(line.get(key), minimum=1 if key in
                   ("vertsize","textheight","baseline","horzsize") else 0)
                   for key in ("vertpos","vertsize","textheight","baseline","spacing","horzpos","horzsize")}
        if (metrics["baseline"] > metrics["textheight"] or metrics["textheight"] > metrics["vertsize"]
                or metrics["textheight"] < max(c[1] for c in native_chars)
                or abs(metrics["horzsize"]+metrics["horzpos"]-width) > 2):
            return None
    para_properties = header.find(".//"+HH+"paraProperties")
    styles = {p.get("id"):p for p in para_properties}
    base = styles.get(paragraph.get("paraPrIDRef"))
    if base is None or base.find(HH+"align").get("horizontal") != "JUSTIFY":
        return None
    margin = base.find(".//"+HH+"margin")
    left = _integer(margin.find(HC+"left").get("value"))
    intent = _integer(margin.find(HC+"intent").get("value"))
    old_right = _integer(margin.find(HC+"right").get("value"))
    rows = [[c for c in _line_proof(line)[1] if c[0].strip()] for line in body]
    wanted_left = round((rows[1][0][2][0]-rail)*scale)
    wanted_intent = round((rows[0][0][2][0]-rows[1][0][2][0])*scale)
    if abs(left-wanted_left) > 1 or abs(intent-wanted_intent) > 1:
        return None
    # Rebuild every cache metric from the actual source rather than accepting
    # plausible heights or relative offsets supplied by the caller. During
    # conversion this paragraph has a zero-local cache; saving the question
    # subsequently moves it to its independently recomputed container start.
    probe = deepcopy(paragraph)
    candidate = {**layout,"source_typography":actual_meta,"native_page_width":page_width,
                 "native_indentation":(left,0,intent)}
    if not apply_source_line_cache(probe,candidate,width):
        return None
    expected_cache = probe.find(HP+"linesegarray")
    from hwpx.tools.question_reflow import update_positions
    container = deepcopy(sub)
    body_index = list(sub).index(paragraph)
    container.replace(list(container)[body_index],deepcopy(probe))
    update_positions(container,styles)
    saved_cache = list(container)[body_index].find(HP+"linesegarray")
    def same_cache(candidate):
        return len(cache) == len(candidate) and all(
            actual.tag == expected.tag and set(actual.attrib) == set(expected.attrib)
            and all(_integer(actual.get(key)) == _integer(value)
                    for key,value in expected.attrib.items())
            for actual,expected in zip(cache,candidate))
    if not (same_cache(expected_cache) or same_cache(saved_cache)):
        return None
    rights = [max(c[1][2] for c in row) for row in rows[:-1]]
    size = median(c[4] for row in rows for c in row)
    target = median(rights)
    if max(abs(right-target) for right in rights) > size*.03:
        return None
    right = round(width-(target-rail)*scale)
    if not 0 < right < size*scale*2 or old_right not in (0,right):
        return None
    return base, right


def restore_source_question_body_right(paragraphs, header, page_width, width):
    """Clone only a proved body's right margin; preserve text, styles and cache."""
    count = 0
    for paragraph,layout in paragraphs:
        try:
            result = _body_right(paragraph,layout,header,page_width,width)
            if result is None:
                continue
            base,right = result
            if _integer(base.find(".//"+HH+"margin/"+HC+"right").get("value")) == right:
                continue
            properties = header.find(".//"+HH+"paraProperties")
            identifiers = [_integer(p.get("id")) for p in properties]
            if len(identifiers) != len(set(identifiers)):
                continue
            clone = deepcopy(base)
            clone.set("id", str(max(identifiers)+1))
            for margin in clone.findall(".//"+HH+"margin"):
                margin.find(HC+"right").set("value", str(right))
            properties.append(clone)
            properties.set("itemCnt", str(len(properties)))
            paragraph.set("paraPrIDRef", clone.get("id"))
            count += 1
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError, OSError,
                fitz.FileNotFoundError, fitz.FileDataError, fitz.EmptyFileError):
            continue
    return count
