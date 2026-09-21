"""Compare question mathematics and addressed table cells with actual PDF glyphs.

The evidence comes from the input PDF, never from writer metadata. Literal prose
coverage alone cannot detect a changed physical constant or exchanged columns.
"""

from __future__ import annotations

from collections import Counter
import re

import fitz

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
_GREEK = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "theta": "θ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "phi": "φ",
    "psi": "ψ",
    "omega": "ω",
    "DELTA": "Δ",
}


def _symbols(value):
    value = str(value or "").replace("−", "-").replace("–", "-")
    value = re.sub(r"\\(?:mathrm|text|operatorname)\s*\{([^{}]*)\}", r"\1", value)
    value = re.sub(r"\b(?:rm|it|bold)\s*", "", value)
    value = re.sub(r"\\?times|×|⋅|\\?cdot", "*", value)
    value = re.sub(r"(?<![A-Za-z])(?:\\?infty|inf)(?![A-Za-z])", "∞", value)
    for name, symbol in {"LEQ": "≤", "GEQ": "≥", "NEQ": "≠"}.items():
        value = re.sub(r"(?<![A-Za-z])\\?" + name + r"(?![A-Za-z])", symbol, value)
    for name, symbol in _GREEK.items():
        value = re.sub(r"(?<![A-Za-z])\\?" + name + r"(?![A-Za-z])", symbol, value)
    return value


def _tokens(value):
    return tuple(
        re.findall(
            r"\d+(?:\.\d+)?|over|[A-Za-zΑ-Ωα-ω]|[가-힣]+|[_^+*/=<>≤≥≠∞\-()\[\]]",
            _symbols(value),
        )
    )


def _cell_value(value):
    return re.sub(r"[\s{}$_^]+", "", _symbols(value))


def _native_text(paragraph):
    return "".join(
        (child.text or "")
        if child.tag == HP + "t"
        else child.findtext(HP + "script", "")
        for run in paragraph.findall(HP + "run")
        for child in run
        if child.tag in {HP + "t", HP + "equation"}
    )


def _source_script_lines(lines):
    """Bind detached source scripts to the adjacent baseline glyph.

    Read PDF coordinates directly: a left isotope number belongs to its element,
    while an ion charge belongs to the preceding element. Neither association
    follows the producer's span serialization or a merged cell's y-sort.
    """
    from .pdf_layout_writer import _pdf_output_text, is_hancom_eq_font

    result = []
    for line in lines:
        spans = [dict(s) for s in line.get("spans", [])]
        used = set()
        attached = {}
        for i, small in enumerate(spans):
            value = _pdf_output_text(small.get("text", "")).strip()
            if not is_hancom_eq_font(str(small.get("font", ""))) or not re.fullmatch(
                r"[A-Za-zΑ-Ωα-ω0-9+−-]+", value
            ):
                continue
            choices = []
            for j, base in enumerate(spans):
                size = float(base.get("size", 0))
                if i == j or not 0 < float(small.get("size", 0)) <= size * 0.82:
                    continue
                text = _pdf_output_text(base.get("text", "")).strip()
                if not is_hancom_eq_font(str(base.get("font", ""))):
                    continue
                sb, bb = fitz.Rect(small["bbox"]), fitz.Rect(base["bbox"])
                left = sb.x1 <= bb.x0 + 0.7
                if left:
                    if not re.fullmatch(r"[A-Z][a-z]?", text) or not re.search(
                        r"[0-9]", value
                    ):
                        continue
                    gap = bb.x0 - sb.x1
                    glyph = next(iter(base.get("chars", [])), {})
                else:
                    if not re.search(r"[A-Za-zΑ-Ωα-ω0-9)\]]$", text):
                        continue
                    gap = sb.x0 - bb.x1
                    glyph = (base.get("chars") or [{}])[-1]
                a = glyph.get("origin", base.get("origin"))
                b = (small.get("chars") or [{}])[0].get("origin", small.get("origin"))
                if not a or not b or not -size * 0.3 <= gap <= size * 0.65:
                    continue
                delta = a[1] - b[1]
                if not size * 0.19 <= abs(delta) <= size * 0.85:
                    continue
                choices.append((abs(gap), j, left, "^" if delta > 0 else "_"))
            if choices:
                _, j, left, op = min(choices)
                attached.setdefault(j, []).append((i, left, op, value))
                used.add(i)
        for j, scripts in attached.items():
            base = spans[j]
            text = _pdf_output_text(base.get("text", ""))
            before, after = [], []
            for i, left, op, value in sorted(scripts):
                (before if left else after).append(op + "{" + value + "}")
            base["text"] = (
                ("{}" + "".join(before) if before else "") + text + "".join(after)
            )
            base["chars"] = []
        result.append(
            {**line, "spans": [s for i, s in enumerate(spans) if i not in used]}
        )
    return result


def _source_math(lines, source_page=None):
    from .pdf_layout_writer import _pdf_output_text, is_hancom_eq_font

    expressions = []
    for line in _source_script_lines(
        _source_fraction_lines(lines, source_page=source_page)
    ):
        groups = []
        group = []
        previous = None
        for span in line.get("spans", []):
            value = _pdf_output_text(span.get("text", ""))
            if not is_hancom_eq_font(str(span.get("font", ""))) or not value.strip():
                if group:
                    groups.append("".join(group))
                group, previous = [], None
                continue
            if previous is not None:
                size = float(previous.get("size", 0))
                small = float(span.get("size", 0))
                a, b = previous.get("origin"), span.get("origin")
                gap = float(span["bbox"][0]) - float(previous["bbox"][2])
                delta = float(a[1]) - float(b[1]) if a and b else 0
                script = (
                    size > 0
                    and re.search(
                        r"[A-Za-zΑ-Ωα-ω0-9)\]]$",
                        _pdf_output_text(previous.get("text", "")).strip(),
                    )
                    and 0 < small <= size * 0.85
                    and re.fullmatch(r"[+−-]?[A-Za-z0-9]+", value.strip())
                    and -size * 0.7 <= gap <= size * 0.8
                    and size * 0.20 <= abs(delta) <= size * 0.85
                )
                if script:
                    group.append(
                        ("^" if delta > 0 else "_") + "{" + value.strip() + "}"
                    )
                    # The following baseline span continues the same equation.
                    continue
                if abs(delta) > max(size, small) * 0.25 or gap > max(size, small) * 1.2:
                    if group:
                        groups.append("".join(group))
                    group = []
            group.append(value)
            previous = span
        if group:
            groups.append("".join(group))
        for expression in groups:
            tokens = _tokens(expression)
            if tokens and any(
                re.fullmatch(r"\d+(?:\.\d+)?", token) for token in tokens
            ):
                expressions.append(tokens)
    return expressions


def _source_fraction_lines(lines, *, source_page=None):
    """Read font fraction rules from individual PDF glyphs, not span text order.

    PDF producers can put the elevated numerator and baseline suffix in one
    span (``3p``), while writing the denominator in a different line. Their
    character rectangles, together with the actual fraction-rule glyph, retain
    the association. This intentionally does not call the converter's repair.
    """
    from .pdf_layout_writer import _pdf_output_text, is_hancom_eq_font

    glyphs = []
    for li, line in enumerate(lines):
        for si, span in enumerate(line.get("spans", [])):
            if not is_hancom_eq_font(str(span.get("font", ""))):
                continue
            for ci, char in enumerate(span.get("chars", [])):
                glyphs.append(
                    {
                        "key": (li, si, ci),
                        "raw": char.get("c", ""),
                        "text": _pdf_output_text(char.get("c", "")),
                        "box": fitz.Rect(char["bbox"]),
                        "span": span,
                        "origin": char.get("origin", span.get("origin")),
                    }
                )
    consumed, replacements = set(), {}
    for rule in glyphs:
        if rule["raw"] != "\ue06d":
            continue
        box = rule["box"]
        axis = box.y0 + box.height * 0.4
        if any(
            g["text"] == "√"
            and abs(g["box"].x1 - box.x0) < 2
            and abs(g["box"].y1 - box.y1) < 5
            for g in glyphs
        ):
            continue  # A radical vinculum is not a fraction bar.
        if source_page is not None and box.width >= 4:
            # Measure the actual rule, independently of the converter. Tall
            # equation-font glyph rectangles do not locate the painted line.
            import numpy as np

            pix = source_page.get_pixmap(
                matrix=fitz.Matrix(2, 2), clip=box, alpha=False
            )
            pixels = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            dark = pixels[:, :, :3].max(axis=2) < 180
            rows = []
            for index, row in enumerate(dark):
                longest = current = 0
                for ink in row:
                    current = current + 1 if ink else 0
                    longest = max(longest, current)
                if longest >= pix.width * 0.85:
                    rows.append(index)
            if rows and rows[-1] - rows[0] <= max(3, box.height * 0.16):
                axis = (pix.y + sum(rows) / len(rows) + 0.5) / 2
        operands = [[], []]
        for glyph in glyphs:
            rect = glyph["box"]
            center = (rect.tl + rect.br) / 2
            size = float(glyph["span"].get("size", 0))
            if (
                glyph["key"] not in consumed
                and glyph["text"].strip()
                and box.x0 - 0.6 <= center.x <= box.x1 + 0.6
                and glyph["raw"] != "\ue06d"
                and 1.5 < abs(center.y - axis) < size * 0.95
            ):
                operands[int(center.y > axis)].append(glyph)
        # Only extend an identified operand by its own small raised/lowered
        # glyphs. A loose vertical band would invent a fraction out of an
        # overlined segment and text from the preceding physical line.
        for side in operands:
            for glyph in glyphs:
                if (
                    glyph in side
                    or glyph["key"] in consumed
                    or not glyph["text"].strip()
                ):
                    continue
                center = (glyph["box"].tl + glyph["box"].br) / 2
                if not box.x0 - 0.6 <= center.x <= box.x1 + 0.6:
                    continue
                if not any(
                    float(glyph["span"].get("size", 0))
                    <= float(base["span"].get("size", 0)) * 0.85
                    and glyph["origin"]
                    and base["origin"]
                    and abs(glyph["origin"][1] - base["origin"][1])
                    <= float(base["span"].get("size", 0)) * 0.85
                    and -2
                    <= glyph["box"].x0 - base["box"].x1
                    <= float(base["span"].get("size", 0)) * 0.7
                    and (center.y > axis)
                    == ((base["box"].y0 + base["box"].y1) / 2 > axis)
                    for base in list(side)
                ):
                    continue
                side.append(glyph)

        def operand(side):
            if not side:
                return ""
            large = max(float(g["span"].get("size", 0)) for g in side)
            bases = [g for g in side if float(g["span"].get("size", 0)) >= large * 0.85]
            baselines = sorted(float(g["origin"][1]) for g in bases if g["origin"])
            baseline = baselines[len(baselines) // 2] if baselines else 0
            chunks = []
            for g in sorted(side, key=lambda g: (g["box"].x0, g["box"].y0)):
                delta = baseline - float(g["origin"][1]) if g["origin"] else 0
                op = "^" if delta > 0 else "_"
                scripted = (
                    float(g["span"].get("size", 0)) <= large * 0.85
                    and large * 0.2 <= abs(delta) <= large * 0.85
                )
                if scripted and chunks:
                    if chunks[-1][0] == op:
                        chunks[-1][1] += g["text"]
                    else:
                        chunks.append([op, g["text"]])
                else:
                    chunks.append(["", g["text"]])
            return "".join(
                op + "{" + value + "}" if op else value for op, value in chunks
            )

        values = [operand(side) for side in operands]
        if not all(values) or any("□" in value for value in values):
            continue
        values = [value.replace("√", "sqrt ") for value in values]
        selected = operands[0] + operands[1]
        consumed.update(g["key"] for g in selected)
        consumed.add(rule["key"])
        host = operands[0][0]
        li = host["key"][0]
        size = float(host["span"].get("size", 10))
        replacements.setdefault(li, []).append(
            {
                **host["span"],
                "text": "{" + values[0] + "} over {" + values[1] + "}",
                "chars": [],
                "bbox": (box.x0, axis - size * 0.8, box.x1, axis + size * 0.2),
                "origin": (box.x0, axis + size * 0.2),
                "size": size,
            }
        )
    if not consumed:
        return lines
    result = []
    for li, line in enumerate(lines):
        spans = []
        for si, span in enumerate(line.get("spans", [])):
            chars = span.get("chars", [])
            if not any((li, si, ci) in consumed for ci in range(len(chars))):
                spans.append(span)
                continue
            remaining = [
                c for ci, c in enumerate(chars) if (li, si, ci) not in consumed
            ]
            if remaining:
                bounds = fitz.Rect(remaining[0]["bbox"])
                for char in remaining[1:]:
                    bounds |= fitz.Rect(char["bbox"])
                spans.append(
                    {
                        **span,
                        "chars": remaining,
                        "text": "".join(c["c"] for c in remaining),
                        "bbox": tuple(bounds),
                        "origin": remaining[0].get("origin", span.get("origin")),
                    }
                )
        spans.extend(replacements.get(li, []))
        result.append({**line, "spans": sorted(spans, key=lambda s: s["bbox"][0])})
    return result


def source_grid_cells(page, raw_lines, figure_regions=(), *, raw_grid_collector=None):
    """Read ordered cell values directly from PDF grid geometry and raw spans."""
    from .pdf_layout_writer import _pdf_output_text

    result = []
    grids = page.find_tables().tables
    if raw_grid_collector is not None:
        raw_grid_collector[page.number + 1] = [
            {
                "bbox": tuple(grid.bbox),
                "row_count": grid.row_count,
                "col_count": grid.col_count,
            }
            for grid in grids
        ]
    for grid in grids:
        bounds = fitz.Rect(grid.bbox)
        if grid.row_count < 2 or grid.col_count < 2:
            continue
        if (
            bounds.width > page.rect.width * 0.48
            or bounds.height > page.rect.height * 0.4
        ):
            continue
        if any(figure.contains(bounds) for figure in figure_regions):
            continue
        matrix = []
        for row in grid.rows:
            values = []
            for cell in row.cells:
                if cell is None:
                    values.append(None)
                    continue
                region = fitz.Rect(cell)
                selected = []
                for line in raw_lines:
                    for span in line.get("spans", []):
                        # Independently address each source glyph; a PDF span
                        # can cross a true grid line (e.g. "Standard $40").
                        glyphs = span.get("chars", [])
                        if glyphs:
                            inside = [glyph for glyph in glyphs
                                      if region.x0 <= (glyph["bbox"][0] + glyph["bbox"][2]) / 2 < region.x1
                                      and region.y0 <= (glyph["bbox"][1] + glyph["bbox"][3]) / 2 < region.y1]
                            if inside:
                                box = fitz.Rect(inside[0]["bbox"])
                                for glyph in inside[1:]:
                                    box |= fitz.Rect(glyph["bbox"])
                                selected.append({**span, "chars": inside,
                                                 "text": "".join(glyph["c"] for glyph in inside), "bbox": tuple(box)})
                        else:
                            box = fitz.Rect(span["bbox"])
                            if region.contains((box.tl + box.br) / 2):
                                selected.append(span)
                selected = _source_script_lines(
                    _source_fraction_lines([{"spans": selected}], source_page=page)
                )[0]["spans"]
                bands = []
                for span in sorted(
                    selected,
                    key=lambda s: (s.get("origin", (0, s["bbox"][3]))[1], s["bbox"][0]),
                ):
                    baseline = span.get("origin", (0, span["bbox"][3]))[1]
                    if (
                        bands
                        and abs(baseline - bands[-1][0])
                        <= max(float(span.get("size", 0)), bands[-1][1]) * 0.65
                    ):
                        bands[-1][2].append(span)
                        bands[-1][1] = max(bands[-1][1], float(span.get("size", 0)))
                    else:
                        bands.append([baseline, float(span.get("size", 0)), [span]])
                text = "".join(
                    _pdf_output_text(span.get("text", ""))
                    for _, _, band in bands
                    for span in sorted(band, key=lambda s: s["bbox"][0])
                )
                values.append(_cell_value(text))
            matrix.append(values)
        from .pdf_source_table_semantics import source_grid_gutter
        for side in ("left", "right"):
            gutter = source_grid_gutter(grid.rows, raw_lines, bounds, side=side)
            if gutter is not None:
                labels, edge = gutter
                if side == "left":
                    bounds.x0 = edge
                    matrix = [[None if label is None else _cell_value(label)] + row
                              for label, row in zip(labels, matrix)]
                else:
                    bounds.x1 = edge
                    matrix = [row + [None if label is None else _cell_value(label)]
                              for label, row in zip(labels, matrix)]
        result.append({"bbox": tuple(bounds), "cells": matrix})
    return result


def _native_grids(draw, header=None):
    result = []
    for table in draw.iter(HP + "tbl"):
        if header is not None:
            from .pdf_source_table_semantics import logical_native_grid

            logical = logical_native_grid(table, header, _native_text, _cell_value)
            if logical is not None:
                result.append(logical)
                continue
        rows, cols = int(table.get("rowCnt", "0")), int(table.get("colCnt", "0"))
        if rows < 2 or cols < 2:
            continue
        matrix = [[None] * cols for _ in range(rows)]
        covered = set()
        cells = table.findall(HP + "tr/" + HP + "tc")
        for cell in cells:
            addr, span, size = (
                cell.find(HP + name) for name in ("cellAddr", "cellSpan", "cellSz")
            )
            if addr is None or span is None or size is None:
                continue
            row, col = int(addr.get("rowAddr", "-1")), int(addr.get("colAddr", "-1"))
            height, width = int(span.get("rowSpan", "1")), int(span.get("colSpan", "1"))
            if (
                0 <= row < row + height <= rows
                and 0 <= col < col + width <= cols
                and int(size.get("width", "0")) > 0
                and int(size.get("height", "0")) > 0
            ):
                covered.update(
                    (r, c)
                    for r in range(row, row + height)
                    for c in range(col, col + width)
                    if (r, c) != (row, col)
                )
        for cell in cells:
            addr = cell.find(HP + "cellAddr")
            if addr is None:
                continue
            row, col = int(addr.get("rowAddr", "-1")), int(addr.get("colAddr", "-1"))
            if 0 <= row < rows and 0 <= col < cols:
                value = _cell_value(
                    "".join(
                        _native_text(p)
                        for p in cell.findall(HP + "subList/" + HP + "p")
                    )
                )
                size = cell.find(HP + "cellSz")
                if (
                    (row, col) in covered
                    and not value
                    and size is not None
                    and int(size.get("width", "-1")) >= 0
                    and int(size.get("height", "-1")) >= 0
                    and int(size.get("width", "-1")) * int(size.get("height", "-1"))
                    == 0
                    and not any(
                        child.tag in {HP + "pic", HP + "tbl"} for child in cell.iter()
                    )
                ):
                    continue  # Zero-size schema placeholder under an actual merged cell.
                matrix[row][col] = value
        result.append({"id": table.get("id"), "cells": matrix})
    return result


def _source_radicals(lines):
    """Read each radical's operand from its own source vinculum extent."""
    from .pdf_layout_writer import _pdf_output_text, is_hancom_eq_font

    records = []
    for line in lines:
        for span in line.get("spans", []):
            if not is_hancom_eq_font(str(span.get("font", ""))):
                continue
            for char in span.get("chars", []):
                records.append(
                    (
                        char,
                        span,
                        fitz.Rect(char["bbox"]),
                        _pdf_output_text(char.get("c", "")),
                    )
                )
    result = []
    for char, span, box, text in records:
        if text != "√":
            continue
        rules = [
            (c, b)
            for c, _, b, _ in records
            if c.get("c") == "\ue06d"
            and abs(b.x0 - box.x1) < 2
            and abs(b.y1 - box.y1) < 5
        ]
        if len(rules) != 1:
            continue
        rule, bounds = rules[0]
        selected = {}
        for glyph, owner, rect, decoded in records:
            center = (rect.tl + rect.br) / 2
            if glyph is char or glyph is rule or not decoded.strip():
                continue
            if (
                bounds.x0 - 0.5 <= center.x <= bounds.x1 + 0.5
                and box.y0 - 2 <= center.y <= box.y1 + 4
            ):
                selected.setdefault(id(owner), (owner, []))[1].append(glyph)
        operand = []
        for owner, chars in selected.values():
            union = fitz.Rect(chars[0]["bbox"])
            for glyph in chars[1:]:
                union |= fitz.Rect(glyph["bbox"])
            operand.append(
                {
                    **owner,
                    "chars": chars,
                    "text": "".join(c["c"] for c in chars),
                    "bbox": tuple(union),
                    "origin": chars[0].get("origin", owner.get("origin")),
                }
            )
        recovered = _source_script_lines(
            [{"spans": sorted(operand, key=lambda s: s["bbox"][0])}]
        )[0]
        tokens = _tokens(
            "".join(_pdf_output_text(s["text"]) for s in recovered["spans"])
        )
        if tokens:
            result.append(tokens)
    return result


def _native_radicals(draw):
    result = []
    for equation in draw.iter(HP + "equation"):
        text = equation.findtext(HP + "script", "")
        for match in re.finditer(r"\bsqrt\s*\{", text):
            start, depth, end = match.end(), 1, match.end()
            while end < len(text) and depth:
                depth += (text[end] == "{") - (text[end] == "}")
                end += 1
            if depth == 0:
                result.append(_tokens(text[start : end - 1]))
    return result


def _source_sum_limits(lines):
    """Independently require the small glyph bands belonging to each sigma."""
    from .pdf_layout_writer import _pdf_output_text, is_hancom_eq_font

    spans = [s for line in lines for s in line.get("spans", [])]
    result = []
    for sigma in spans:
        if _pdf_output_text(sigma.get("text", "")).strip() != "∑":
            continue
        box = fitz.Rect(sigma["bbox"])
        cx, cy = (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
        bands = {"upper": [], "lower": []}
        for span in spans:
            if not is_hancom_eq_font(str(span.get("font", ""))):
                continue
            if not 0 < float(span.get("size", 0)) < float(sigma.get("size", 0)) * 0.65:
                continue
            bounds = fitz.Rect(span["bbox"])
            x, y = (bounds.x0 + bounds.x1) / 2, (bounds.y0 + bounds.y1) / 2
            if (
                abs(x - cx) > box.width * 0.7
                or not box.height * 0.32 <= abs(y - cy) <= box.height * 0.95
            ):
                continue
            text = _pdf_output_text(span.get("text", "")).strip()
            if re.fullmatch(r"[A-Za-z0-9=+−\-∞]+", text):
                bands["upper" if y < cy else "lower"].append((bounds.x0, text))
        upper, lower = (
            "".join(text for _, text in sorted(bands[side]))
            for side in ("upper", "lower")
        )
        if upper and re.fullmatch(r"[A-Za-z]=[A-Za-z0-9+−\-]+", lower):
            result.append((_tokens(lower), _tokens(upper)))
    return result


def _native_sum_limits(draw):
    result = []
    for equation in draw.iter(HP + "equation"):
        text = equation.findtext(HP + "script", "")
        for match in re.finditer(r"\bsum\s*((?:[_^]\s*\{[^{}]*\}\s*){1,2})", text):
            scripts = dict(re.findall(r"([_^])\s*\{([^{}]*)\}", match[1]))
            if "_" in scripts and "^" in scripts:
                result.append((_tokens(scripts["_"]), _tokens(scripts["^"])))
    return result


def inspect_source_question_semantics(
    source_lines, draw, region, source_grids, *, header=None, source_page=None
):
    """Check complete numeric math fragments and source row/column associations."""
    required = Counter(_source_math(source_lines, source_page=source_page))
    native_streams = [_tokens(_native_text(p)) for p in draw.iter(HP + "p")]
    missing_math = []
    for fragment, count in required.items():
        actual = sum(
            stream[index : index + len(fragment)] == fragment
            for stream in native_streams
            for index in range(max(0, len(stream) - len(fragment) + 1))
        )
        if actual < count:
            missing_math.append(
                {"tokens": list(fragment), "expected": count, "actual": actual}
            )
    radicals, native_radicals = (
        Counter(_source_radicals(source_lines)),
        Counter(_native_radicals(draw)),
    )
    for operand, count in radicals.items():
        if native_radicals[operand] < count:
            missing_math.append(
                {
                    "structure": "radical_operand",
                    "tokens": list(operand),
                    "expected": count,
                    "actual": native_radicals[operand],
                }
            )
    sums, native_sums = (
        Counter(_source_sum_limits(source_lines)),
        Counter(_native_sum_limits(draw)),
    )
    for (lower, upper), count in sums.items():
        if native_sums[(lower, upper)] < count:
            missing_math.append(
                {
                    "structure": "sum_limits",
                    "lower": list(lower),
                    "upper": list(upper),
                    "expected": count,
                    "actual": native_sums[(lower, upper)],
                }
            )
    native_grids = _native_grids(draw, header)
    available = set(range(len(native_grids)))
    wrong_cells = []
    checked = 0
    for source in source_grids:
        bounds = fitz.Rect(source["bbox"])
        if (
            bounds.get_area() <= 0
            or (bounds & region).get_area() / bounds.get_area() < 0.9
        ):
            continue
        expected = source["cells"]
        options = []
        for index in available:
            actual = native_grids[index]["cells"]
            if len(actual) == len(expected) and all(
                len(a) == len(b) for a, b in zip(actual, expected)
            ):
                differences = [
                    {
                        "row": row,
                        "column": col,
                        "source": value,
                        "output": actual[row][col],
                    }
                    for row, values in enumerate(expected)
                    for col, value in enumerate(values)
                    if value != actual[row][col]
                ]
                options.append((len(differences), index, differences))
        checked += 1
        if not options:
            wrong_cells.append(
                {
                    "source_bbox": list(bounds),
                    "reason": "source_grid_missing",
                    "rows": len(expected),
                    "columns": len(expected[0]),
                }
            )
            continue
        _, index, differences = min(options, key=lambda item: (item[0], item[1]))
        available.remove(index)
        if differences:
            wrong_cells.append(
                {
                    "source_bbox": list(bounds),
                    "table_id": native_grids[index]["id"],
                    "cells": differences,
                }
            )
    return {
        "ok": not missing_math and not wrong_cells,
        "source_math_fragments": sum(required.values()),
        "missing_math_fragments": missing_math,
        "source_grids": checked,
        "wrong_source_cells": wrong_cells,
    }
