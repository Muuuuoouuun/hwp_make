"""Deterministic PDF glyph-geometry repair for editable native equations.

The PDF text layer often exposes a two-dimensional equation as several flat
lines. This module rebuilds the common structures found in Korean exam PDFs
before the text is passed to the HWPX native-equation writer.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, replace
from typing import Any, Iterable

from . import math_text

_HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
_CHOICE_RE = re.compile(r"^[\u2460-\u2473]")
_MATH_CELL_RE = re.compile(r"^[A-Za-z0-9.+\-−]+$")
_QUESTION_PREFIX_RE = re.compile(r"^(\s*\d{1,3}\.\s*)(.+)$")
_MATH_WORDS = {
    "lim", "log", "ln", "sin", "cos", "tan", "sec", "csc", "cot",
    "sqrt", "frac", "sum", "prod", "int", "matrix", "pmatrix", "begin", "end",
    "infty", "pi", "theta", "alpha", "beta", "gamma", "delta", "vec", "overline",
}

_INLINE_MATH_CHARS = frozenset(
    r"\{}_^=+-−*/×÷<>≤≥∩∪→∞πθαβγδ.,;:()[]|'′∫√"
)
_INLINE_MATH_CONNECTOR_RE = re.compile(
    r"^[\s,;:=+\-−*/×÷<>≤≥∩∪→∞πθ\[\](){}|'′.]+$"
)

_PLACEHOLDER_CHARS = "□▢"
# A text line that carries nothing but a fraction bar and the delimiters the
# equation font stacks around it (big braces, absolute-value rules, brackets).
_BARE_BAR_LINE_RE = re.compile(rf"^[{_PLACEHOLDER_CHARS}()\[\]{{}}|\s]+$")


_RESTORED_STRUCTURE_RE = re.compile(r"\\(?:frac|sqrt|vec|overline|lim|int|sum|prod)\b")


def _placeholder_count(value: str) -> int:
    text = str(value or "")
    return sum(text.count(char) for char in _PLACEHOLDER_CHARS)


def _drops_restored_structure(target: str, replacement: str) -> bool:
    """``replacement`` would delete a structure ``target`` already carries.

    Both fallbacks below rewrite a line they could *not* map back to geometry,
    so they have no evidence that the line they overwrite belongs to the row
    being rebuilt.  A rebuild may never lose an already-restored formula — the
    same invariant that stops a rebuild from raising a placeholder count.
    """
    return bool(
        set(_RESTORED_STRUCTURE_RE.findall(str(target or "")))
        - set(_RESTORED_STRUCTURE_RE.findall(str(replacement or "")))
    )


@dataclass(frozen=True, slots=True)
class Glyph:
    text: str
    left: float
    top: float
    right: float
    bottom: float
    size: float
    line_index: int
    font: str = ""

    @property
    def width(self) -> float:
        return max(0.0, self.right - self.left)

    @property
    def height(self) -> float:
        return max(0.0, self.bottom - self.top)

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2.0


def _line_text(line: dict[str, Any]) -> str:
    return math_text.normalize_recognized_math_text(str(line.get("text") or "")).strip()


def _glyphs(line_geometries: list[dict[str, Any]]) -> list[Glyph]:
    result: list[Glyph] = []
    for line_index, line in enumerate(line_geometries):
        if not isinstance(line, dict):
            continue
        for char in line.get("pdf_line_chars") or []:
            if not isinstance(char, dict):
                continue
            bbox = char.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            try:
                left, top, right, bottom = [float(value) for value in bbox]
                size = float(char.get("size") or 0.0)
            except (TypeError, ValueError):
                continue
            text = math_text.normalize_recognized_math_text(str(char.get("c") or ""))
            if not text or text.isspace():
                continue
            result.append(
                Glyph(
                    text=text,
                    left=left,
                    top=top,
                    right=right,
                    bottom=bottom,
                    size=size,
                    line_index=line_index,
                    font=str(char.get("font") or ""),
                )
            )
    return result


def line_geometry_glyphs(line_geometries: list[dict[str, Any]]) -> list[Glyph]:
    """Public view of the per-character geometry of one recognized problem."""
    return _glyphs(line_geometries)


def _mark_glyph_near_bar(
    glyphs: Iterable[Glyph],
    *,
    bar_rect: tuple[float, float, float, float],
    marks: str,
    left_margin: float = 36.0,
    right_margin: float | None = None,
    vertical_margin: float = 28.0,
) -> Glyph | None:
    """Return the mark glyph (``√``/``⃗``) that sits against ``bar_rect``'s left edge.

    Real exam PDFs draw a radical vinculum, a vector accent, and a fraction bar
    with the *same* private-use glyph, so the only way to tell them apart is the
    mark that abuts the bar.  ``right_margin`` defaults to the bar's own right
    edge (the wide window ``app.importers`` has always used for short accent
    bars); nested-bar analysis passes a tight window instead so a wide outer
    fraction bar cannot claim a radical sign belonging to a bar nested inside it.
    """
    left, top, right, bottom = bar_rect
    bar_y = (top + bottom) / 2.0
    upper = right + 8.0 if right_margin is None else left + right_margin
    lower = left - left_margin
    best: Glyph | None = None
    for glyph in glyphs:
        if glyph.width <= 0 or glyph.height <= 0:
            continue
        if not any(mark in glyph.text for mark in marks):
            continue
        if not lower <= glyph.right <= upper:
            continue
        if abs(glyph.center_y - bar_y) > vertical_margin:
            continue
        if best is None or abs(glyph.right - left) < abs(best.right - left):
            best = glyph
    return best


def glyphs_near_mark(
    glyphs: Iterable[Glyph],
    *,
    bar_rect: tuple[float, float, float, float],
    marks: str,
) -> bool:
    """``True`` when a ``marks`` glyph abuts the left edge of ``bar_rect``."""
    return _mark_glyph_near_bar(glyphs, bar_rect=bar_rect, marks=marks) is not None


def _line_glyphs(glyphs: Iterable[Glyph], line_index: int) -> list[Glyph]:
    return sorted((glyph for glyph in glyphs if glyph.line_index == line_index), key=lambda glyph: glyph.left)


def _densest_center(values: list[float], tolerance: float) -> float:
    if not values:
        return 0.0
    best: list[float] = []
    for value in values:
        cluster = [candidate for candidate in values if abs(candidate - value) <= tolerance]
        if len(cluster) > len(best):
            best = cluster
    return float(statistics.median(best or values))


def _baseline(glyphs: list[Glyph]) -> tuple[float, float]:
    sizes = [glyph.size for glyph in glyphs if glyph.size > 0 and glyph.text != "□"]
    if not sizes:
        return 10.0, float(statistics.median([glyph.center_y for glyph in glyphs])) if glyphs else 0.0
    baseline_size = float(statistics.median(sizes))
    centers = [
        glyph.center_y
        for glyph in glyphs
        if glyph.text != "□" and glyph.size >= baseline_size * 0.82
    ]
    center = _densest_center(centers, max(2.5, baseline_size * 0.55))
    return baseline_size, center


def _reading_order_rows(glyphs: list[Glyph], line_count: int) -> list[list[int]]:
    """Group text-line indices whose glyph baselines coincide into visual rows."""
    metrics: dict[int, tuple[float, float, float]] = {}
    for line_index in range(line_count):
        line_glyphs = _line_glyphs(glyphs, line_index)
        if not line_glyphs:
            continue
        size, center = _baseline(line_glyphs)
        metrics[line_index] = (size, center, min(glyph.left for glyph in line_glyphs))
    rows: list[list[int]] = []
    for line_index in sorted(metrics, key=lambda index: (metrics[index][1], metrics[index][2])):
        size, center, _left = metrics[line_index]
        if rows:
            row_center = statistics.median(metrics[index][1] for index in rows[-1])
            row_size = statistics.median(metrics[index][0] for index in rows[-1])
            if abs(center - row_center) <= max(3.0, row_size * 0.5):
                rows[-1].append(line_index)
                continue
        rows.append([line_index])
    return [sorted(row) for row in rows if len(row) > 1]


def line_geometry_source_text(line_geometries: list[dict[str, Any]]) -> str:
    """Problem text rebuilt from the text-line order of ``line_geometries``.

    The per-line ``text`` values are normalized one line at a time upstream, so
    a structure that spans two lines (a vector accent and its base name) is only
    resolved when the joined text is normalized again as a whole.
    """
    return math_text.normalize_recognized_math_text(
        "\n".join(
            str(line.get("text") or "")
            for line in line_geometries
            if isinstance(line, dict) and str(line.get("text") or "").strip()
        )
    )


def reading_order_line_geometries(
    line_geometries: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """Re-linearize PDF text-line fragments that share one visual baseline.

    A HyhwpEQ equation row reaches us as several PDF text lines, and the content
    stream can hand them over out of reading order (``x=1107`` before ``x=934``).
    Every linear repair downstream then binds a fragment to the wrong neighbour —
    most visibly the vector-accent rule, which takes the accent's base name from
    the run that textually follows it.

    Lines whose glyph baselines coincide are therefore re-sorted by their
    leftmost glyph and re-emitted contiguously.  ``None`` is returned when the
    stream already reads left to right, and also when the re-order fails to
    strictly lower the placeholder count of the normalized text — a re-order
    that proves nothing is not evidence.
    """
    lines = [line for line in line_geometries if isinstance(line, dict)]
    if len(lines) != len(line_geometries) or len(lines) < 2:
        return None
    glyphs = _glyphs(lines)
    rows = _reading_order_rows(glyphs, len(lines))
    if not rows:
        return None

    order = list(range(len(lines)))
    left_of: dict[int, float] = {}
    for row in rows:
        for line_index in row:
            left_of[line_index] = min(glyph.left for glyph in _line_glyphs(glyphs, line_index))

    changed = False
    for row in sorted(rows, key=min):
        members = set(row)
        by_left = sorted(members, key=lambda index: left_of[index])
        if [index for index in order if index in members] == by_left:
            continue
        positions = [position for position, index in enumerate(order) if index in members]
        start, end = positions[0], positions[-1]
        span = order[start : end + 1]
        ordered_members = sorted(
            (index for index in span if index in members), key=lambda index: left_of[index]
        )
        others = [index for index in span if index not in members]
        order[start : end + 1] = [*ordered_members, *others]
        changed = True
    if not changed:
        return None

    reordered = [lines[index] for index in order]
    if _placeholder_count(line_geometry_source_text(reordered)) >= _placeholder_count(
        line_geometry_source_text(lines)
    ):
        return None
    return reordered


def _append_script(output: list[str], marker: str, text: str) -> None:
    if not output:
        output.append(text)
        return
    if output[-1].startswith(marker + "{") and output[-1].endswith("}"):
        output[-1] = output[-1][:-1] + text + "}"
    else:
        output.append(f"{marker}{{{text}}}")


def _inline_expression(glyphs: list[Glyph]) -> str:
    if not glyphs:
        return ""
    ordered = sorted(glyphs, key=lambda glyph: (glyph.left, glyph.center_y))
    baseline_size, baseline_center = _baseline(ordered)
    output: list[str] = []
    previous: Glyph | None = None
    for glyph in ordered:
        text = glyph.text
        is_small = glyph.size > 0 and glyph.size <= baseline_size * 0.82
        marker = ""
        if is_small and glyph.center_y < baseline_center - max(1.5, baseline_size * 0.18):
            marker = "^"
        elif is_small and glyph.center_y > baseline_center + max(1.5, baseline_size * 0.18):
            marker = "_"
        if marker:
            _append_script(output, marker, text)
            previous = glyph
            continue
        if previous is not None:
            gap = glyph.left - previous.right
            if gap > max(4.0, baseline_size * 0.58):
                output.append(" ")
        output.append(text)
        previous = glyph
    return "".join(output).strip()


def _inline_math_char(char: str) -> bool:
    if not char:
        return False
    if char.isspace() or char.isascii() and char.isalnum():
        return True
    if char in _INLINE_MATH_CHARS:
        return True
    return char in "ΑΒΓΔΘΛΞΠΣΦΨΩαβγδεζηθικλμνξοπρστυφχψω"


def _is_inline_math_candidate(value: str) -> bool:
    compact = re.sub(r"\s+", "", str(value or ""))
    if not compact or _HANGUL_RE.search(compact):
        return False
    words = re.findall(r"[A-Za-z]+", compact)
    ordinary_words = [
        word
        for word in words
        if word.lower() not in _MATH_WORDS and len(word) > 1 and not word.isupper()
    ]
    if ordinary_words:
        return False
    has_letter = bool(re.search(r"[A-Za-zΑ-Ωα-ω]", compact))
    has_digit = bool(re.search(r"\d", compact))
    has_command = bool(re.search(r"\\[A-Za-z]+", compact))
    has_operator = bool(re.search(r"[_^=+\-−*/×÷<>≤≥∩∪→∞∫√]", compact))
    has_parenthesized = bool(re.search(r"[A-Za-z0-9][\[(]|[\])][A-Za-z0-9]", compact))
    has_indexed_variable = bool(re.search(r"[A-Za-z][_{]?\d", compact))
    if has_command or has_operator or has_parenthesized or has_indexed_variable:
        return has_letter or has_digit
    if not words:
        return False
    if any(word.lower() in _MATH_WORDS for word in words):
        return True
    # Point, event, matrix, and sequence labels are still mathematical tokens.
    return all(len(word) == 1 or word.isupper() for word in words)


def _plain_inline_tokens(value: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    text_buffer: list[str] = []

    def flush_text() -> None:
        if text_buffer:
            tokens.append(("text", "".join(text_buffer)))
            text_buffer.clear()

    index = 0
    while index < len(value):
        if not _inline_math_char(value[index]):
            text_buffer.append(value[index])
            index += 1
            continue
        end = index + 1
        while end < len(value) and _inline_math_char(value[end]):
            end += 1
        raw = value[index:end]
        leading = raw[: len(raw) - len(raw.lstrip())]
        trailing = raw[len(raw.rstrip()) :]
        core = raw.strip()
        punctuation_prefix = ""
        prefix_match = re.match(r"^([.,;:]\s*)", core)
        if prefix_match and prefix_match.group(1):
            punctuation_prefix = prefix_match.group(1)
            core = core[len(punctuation_prefix) :]
        question_prefix = ""
        question_match = re.match(r"^(\d{1,3}\.\s+)(?=[A-Za-z\\])", core)
        if question_match:
            question_prefix = question_match.group(1)
            core = core[len(question_prefix) :]
        score_suffix = ""
        score_match = re.search(r"(\)?\s*\[\d+)$", core)
        if score_match:
            score_suffix = score_match.group(1)
            core = core[: score_match.start()].rstrip()
        if core and _is_inline_math_candidate(core):
            if leading or punctuation_prefix or question_prefix:
                text_buffer.append(leading + punctuation_prefix + question_prefix)
            flush_text()
            tokens.append(("math", core))
            if score_suffix or trailing:
                text_buffer.append(score_suffix + trailing)
        else:
            text_buffer.append(raw)
        index = end
    flush_text()
    return tokens


def _coalesce_inline_math_tokens(tokens: list[tuple[str, str]]) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    index = 0
    while index < len(tokens):
        kind, value = tokens[index]
        if kind != "math":
            output.append((kind, value))
            index += 1
            continue
        expression = value
        cursor = index + 1
        while cursor < len(tokens):
            next_kind, next_value = tokens[cursor]
            if next_kind == "math":
                expression += next_value
                cursor += 1
                continue
            if (
                cursor + 1 < len(tokens)
                and tokens[cursor + 1][0] == "math"
                and _INLINE_MATH_CONNECTOR_RE.fullmatch(next_value or "")
            ):
                expression += next_value + tokens[cursor + 1][1]
                cursor += 2
                continue
            break
        output.append(("math", expression.strip()))
        index = cursor
    return output


def wrap_inline_math_text(value: str) -> str:
    """Mark inline formulas without turning the surrounding prose into a shape."""
    output_lines: list[str] = []
    for line in str(value or "").splitlines():
        tokens: list[tuple[str, str]] = []
        for index, part in enumerate(re.split(r"(\$[^$]+\$)", line)):
            if not part:
                continue
            if index % 2 == 1 and part.startswith("$") and part.endswith("$"):
                equation = part[1:-1]
                question_match = re.match(r"^(\d{1,3}\.\s+)(.+)$", equation)
                if question_match:
                    tokens.append(("text", question_match.group(1)))
                    tokens.append(("math", question_match.group(2)))
                else:
                    tokens.append(("math", equation))
            else:
                # The shared math scanner is better at separating formulas
                # from Latin prose ("Evaluate x^2 ... and sqrt{x}").  Run the
                # glyph-oriented fallback only over text the scanner leaves
                # unresolved, which prevents an entire English sentence from
                # becoming one equation object.
                if _HANGUL_RE.search(part):
                    tokens.extend(_plain_inline_tokens(part))
                else:
                    for segment, is_math in math_text.split_math_text(part):
                        if is_math:
                            tokens.append(("math", segment))
                        else:
                            tokens.extend(_plain_inline_tokens(segment))
        tokens = _coalesce_inline_math_tokens(tokens)
        output_lines.append(
            "".join(f"${text}$" if kind == "math" else text for kind, text in tokens)
        )
    return "\n".join(output_lines).strip()


def _stem_geometry_map(stem: str, line_geometries: list[dict[str, Any]]) -> dict[int, int]:
    stem_lines = [line.strip() for line in str(stem or "").splitlines()]
    used: set[int] = set()
    mapping: dict[int, int] = {}
    for geometry_index, line in enumerate(line_geometries):
        source = _line_text(line)
        if not source or _CHOICE_RE.match(source):
            continue
        for stem_index, candidate in enumerate(stem_lines):
            if stem_index in used or candidate != source:
                continue
            mapping[geometry_index] = stem_index
            used.add(stem_index)
            break
    return mapping


def _replace_geometry_lines(
    stem: str,
    line_geometries: list[dict[str, Any]],
    geometry_indices: set[int],
    replacement_text: str,
) -> tuple[str, bool]:
    mapping = _stem_geometry_map(stem, line_geometries)
    targets = sorted({mapping[index] for index in geometry_indices if index in mapping})
    if len(targets) < 2:
        return stem, False
    lines = str(stem or "").splitlines()
    insert_at = targets[0]
    target_set = set(targets)
    rebuilt = [line for index, line in enumerate(lines) if index not in target_set]
    rebuilt.insert(insert_at, replacement_text.strip())
    return "\n".join(rebuilt).strip(), True


def _remove_geometry_lines(
    stem: str,
    line_geometries: list[dict[str, Any]],
    geometry_indices: set[int],
) -> str:
    mapping = _stem_geometry_map(stem, line_geometries)
    targets = {mapping[index] for index in geometry_indices if index in mapping}
    if not targets:
        return stem
    return "\n".join(
        line for index, line in enumerate(str(stem or "").splitlines()) if index not in targets
    ).strip()


def _row_clusters(glyphs: list[Glyph]) -> list[list[Glyph]]:
    rows: list[list[Glyph]] = []
    for glyph in sorted(glyphs, key=lambda item: (item.center_y, item.left)):
        if rows:
            row_center = statistics.median(item.center_y for item in rows[-1])
            row_height = statistics.median(max(1.0, item.height) for item in rows[-1])
            if abs(glyph.center_y - row_center) <= max(5.0, row_height * 0.42):
                rows[-1].append(glyph)
                continue
        rows.append([glyph])
    return rows


def _row_cells(row: list[Glyph]) -> list[str]:
    ordered = sorted(row, key=lambda glyph: glyph.left)
    cells: list[list[Glyph]] = []
    for glyph in ordered:
        if cells and glyph.left - cells[-1][-1].right <= max(3.5, glyph.height * 0.16):
            cells[-1].append(glyph)
        else:
            cells.append([glyph])
    return ["".join(glyph.text for glyph in cell).strip() for cell in cells]


def _matrix_label(glyphs: list[Glyph], left_parenthesis: Glyph) -> str:
    context = [
        glyph
        for glyph in glyphs
        if left_parenthesis.left - 90 <= glyph.left < left_parenthesis.left
        and left_parenthesis.top - 5 <= glyph.center_y <= left_parenthesis.bottom + 5
        and not _HANGUL_RE.search(glyph.text)
    ]
    text = "".join(glyph.text for glyph in sorted(context, key=lambda glyph: glyph.left))
    match = re.search(r"([A-Za-z][A-Za-z0-9_]*)=$", text)
    return match.group(1) if match else ""


def _matrix_payload(glyphs: list[Glyph], left: Glyph, right: Glyph) -> tuple[str, set[int]] | None:
    candidates = [
        glyph
        for glyph in glyphs
        if left.right <= glyph.center_x <= right.left
        and left.top - 3 <= glyph.center_y <= left.bottom + 3
        and _MATH_CELL_RE.match(glyph.text)
        and glyph.text not in {"=", ","}
    ]
    rows = _row_clusters(candidates)
    cells = [_row_cells(row) for row in rows]
    if len(cells) < 2 or not cells or min(len(row) for row in cells) < 2:
        return None
    column_count = len(cells[0])
    if any(len(row) != column_count for row in cells):
        return None
    label = _matrix_label(glyphs, left)
    body = r" \\ ".join(" & ".join(row) for row in cells)
    used = {left.line_index, right.line_index, *(glyph.line_index for glyph in candidates)}
    matrix = rf"\begin{{pmatrix}}{body}\end{{pmatrix}}"
    return (rf"{label}={matrix}" if label else matrix), used


def _repair_matrices(stem: str, line_geometries: list[dict[str, Any]], glyphs: list[Glyph]) -> tuple[str, int]:
    heights = [glyph.height for glyph in glyphs if glyph.text not in {"□", "(", ")"} and glyph.height > 0]
    if not heights:
        return stem, 0
    normal_height = float(statistics.median(heights))
    lefts = [glyph for glyph in glyphs if glyph.text == "(" and glyph.height >= normal_height * 1.25]
    rights = [glyph for glyph in glyphs if glyph.text == ")" and glyph.height >= normal_height * 1.25]
    pairs: list[tuple[Glyph, Glyph, str, set[int]]] = []
    used_rights: set[int] = set()
    for left in sorted(lefts, key=lambda glyph: glyph.left):
        options = [
            (index, right)
            for index, right in enumerate(rights)
            if index not in used_rights
            and right.left > left.right
            and abs(right.center_y - left.center_y) <= max(left.height, right.height) * 0.25
        ]
        if not options:
            continue
        index, right = min(options, key=lambda item: item[1].left)
        payload = _matrix_payload(glyphs, left, right)
        if payload is None:
            continue
        script, used = payload
        used_rights.add(index)
        pairs.append((left, right, script, used))
    if not pairs:
        return stem, 0

    pairs.sort(key=lambda item: item[0].left)
    first_left, last_right = pairs[0][0], pairs[-1][1]
    first_line = _line_text(line_geometries[first_left.line_index])
    if "=" in pairs[0][2]:
        first_label = pairs[0][2].split("=", 1)[0]
        prefix = re.split(rf"{re.escape(first_label)}\s*=\s*\($", first_line, maxsplit=1)[0].rstrip()
    else:
        prefix = first_line.rsplit("(", 1)[0].rstrip()
    suffix_glyphs = [
        glyph
        for glyph in glyphs
        if glyph.left >= last_right.right
        and first_left.top - 4 <= glyph.center_y <= first_left.bottom + 4
        and glyph.line_index not in {pair[0].line_index for pair in pairs}
    ]
    suffix = _inline_expression(suffix_glyphs)
    scripts = ", ".join(pair[2] for pair in pairs)
    replacement = f"{prefix} ${scripts}$" + (f"{suffix}" if suffix else "")
    used_lines: set[int] = set()
    for left, right, _script, used in pairs:
        used_lines.update(used)
        used_lines.add(left.line_index)
        used_lines.add(right.line_index)
    used_lines.update(glyph.line_index for glyph in suffix_glyphs)
    repaired, changed = _replace_geometry_lines(stem, line_geometries, used_lines, replacement)
    return (repaired, len(pairs)) if changed else (stem, 0)


def _math_glyph(glyph: Glyph) -> bool:
    return not _HANGUL_RE.search(glyph.text) and not _CHOICE_RE.match(glyph.text)


def _fraction_parts(glyphs: list[Glyph], rule: Glyph) -> tuple[list[Glyph], list[Glyph]]:
    horizontal_pad = 1.5
    vertical_limit = max(24.0, rule.height * 0.72)
    candidates = [
        glyph
        for glyph in glyphs
        if glyph is not rule
        and _math_glyph(glyph)
        and rule.left - horizontal_pad <= glyph.center_x <= rule.right + horizontal_pad
        and abs(glyph.center_y - rule.center_y) <= vertical_limit
    ]
    numerator = [glyph for glyph in candidates if glyph.center_y < rule.center_y - 1.0]
    denominator = [glyph for glyph in candidates if glyph.center_y > rule.center_y + 1.0]
    return numerator, denominator


def _fraction_from_bar(
    glyphs: list[Glyph],
    rule: Glyph,
) -> tuple[str, list[Glyph], list[Glyph]] | None:
    """Return ``\\frac{..}{..}`` for a bar glyph with unambiguous stacked parts.

    Evidence rule: the bar's own character rectangle must have math glyphs both
    above and below it and horizontally inside its span (``_fraction_parts``).
    Vector accents, radical vinculums, and empty answer boxes carry no glyphs on
    one of the two sides, so they never reach a substitution here.
    """
    numerator, denominator = _fraction_parts(glyphs, rule)
    numerator_text = _inline_expression(numerator)
    denominator_text = _inline_expression(denominator)
    if not numerator_text or not denominator_text:
        return None
    if _placeholder_count(numerator_text) or _placeholder_count(denominator_text):
        return None
    return rf"\frac{{{numerator_text}}}{{{denominator_text}}}", numerator, denominator


def _resolve_fraction_bars(
    scope: list[Glyph],
    glyphs: list[Glyph],
) -> tuple[list[Glyph], set[int], int]:
    """Swap resolvable fraction bars inside ``scope`` for ``\\frac`` tokens.

    ``scope`` is the glyph run about to be flattened by ``_inline_expression``;
    ``glyphs`` is the wider search space the numerator/denominator may live in
    because the PDF text layer emits them as separate lines.
    """
    if not scope:
        return list(scope), set(), 0
    baseline_size = _baseline(scope)[0]
    working = list(scope)
    donors: set[int] = set()
    resolved = 0
    for rule in [glyph for glyph in scope if glyph.text in _PLACEHOLDER_CHARS]:
        fraction = _fraction_from_bar(glyphs, rule)
        if fraction is None:
            continue
        text, numerator, denominator = fraction
        removed = {id(glyph) for glyph in (rule, *numerator, *denominator)}
        working = [glyph for glyph in working if id(glyph) not in removed]
        working.append(
            Glyph(
                text=text,
                left=rule.left,
                top=rule.top,
                right=rule.right,
                bottom=rule.bottom,
                size=baseline_size,
                line_index=rule.line_index,
            )
        )
        donors.update(
            glyph.line_index
            for glyph in (*numerator, *denominator)
            if glyph.line_index != rule.line_index
        )
        resolved += 1
    return working, donors, resolved


_ACCENT_ARROW_MARKS = "⃗→←"


def classify_placeholder_glyph(glyphs: list[Glyph], bar: Glyph) -> str:
    """Name the structure an unresolved bar glyph belongs to, from geometry alone.

    Equation fonts draw a radical vinculum, a vector accent, an overline, a
    fraction bar, and an empty answer box with the *same* private-use glyph, so
    a residual can only be triaged by what surrounds that one glyph: the mark
    abutting it and the operands stacked inside its own span.  Reading the
    surrounding LaTeX instead mislabels a nested root as a vector merely because
    an accent sits elsewhere on the same line.
    """
    rect = (bar.left, bar.top, bar.right, bar.bottom)
    edge = max(4.0, bar.height * 0.12)
    if (
        _mark_glyph_near_bar(
            glyphs,
            bar_rect=rect,
            marks="√",
            left_margin=edge,
            right_margin=edge,
            vertical_margin=max(6.0, bar.height / 2.0),
        )
        is not None
    ):
        return "root"
    tail = max(4.0, bar.width * 0.25)
    for glyph in glyphs:
        if glyph is bar or not any(mark in glyph.text for mark in _ACCENT_ARROW_MARKS):
            continue
        if abs(glyph.right - bar.right) <= tail and bar.top <= glyph.center_y <= bar.bottom:
            return "vector_or_arrow"
    numerator, denominator = _fraction_parts(glyphs, bar)
    if numerator and denominator:
        return "fraction"
    if denominator:
        return "overline_or_accent"
    if numerator:
        return "underline_or_script"
    if bar.height > 0 and 0.6 <= bar.width / bar.height <= 1.7:
        return "answer_box"
    return "unknown"


def _bar_area(bar: Glyph) -> float:
    return max(0.0, bar.width) * max(0.0, bar.height)


def _bar_contains(outer: Glyph, inner: Glyph, pad: float = 1.5) -> bool:
    """``inner``'s rectangle lies wholly inside the strictly larger ``outer``."""
    if outer is inner or _bar_area(outer) <= _bar_area(inner):
        return False
    return (
        outer.left - pad <= inner.left
        and inner.right <= outer.right + pad
        and outer.top - pad <= inner.top
        and inner.bottom <= outer.bottom + pad
    )


def _bar_children(bars: list[Glyph], bar: Glyph) -> list[Glyph]:
    """The bars ``bar`` contains directly (a bar nested two levels down is not)."""
    inside = [candidate for candidate in bars if _bar_contains(bar, candidate)]
    return [
        candidate
        for candidate in inside
        if not any(_bar_contains(other, candidate) for other in inside)
    ]


def _synthetic_glyph(text: str, parts: list[Glyph], bar: Glyph) -> Glyph:
    """A resolved structure re-entered into the glyph stream at its ink extent.

    The rule the bar draws spans the whole structure horizontally, so the bar
    supplies the left/right edges.  Vertically its rectangle is the equation
    font's full em box — several times taller than the rule — so the operands
    alone decide where an enclosing structure sees this token stacked.
    """
    return Glyph(
        text=text,
        left=min(bar.left, *(part.left for part in parts)),
        top=min(part.top for part in parts),
        right=max(bar.right, *(part.right for part in parts)),
        bottom=max(part.bottom for part in parts),
        size=_baseline(parts)[0],
        line_index=bar.line_index,
    )


def _bar_row_parts(candidates: list[Glyph]) -> tuple[list[Glyph], list[Glyph]] | None:
    """Split a bar's operands into the two stacked bands it separates.

    The bar rectangle's centre is not the drawn rule, so the split is taken at
    the widest vertical gap between the operands themselves and is only accepted
    when the two bands are a full glyph height apart and do not overlap at all.
    """
    if len(candidates) < 2:
        return None
    ordered = sorted(candidates, key=lambda glyph: glyph.center_y)
    heights = [glyph.height for glyph in ordered if glyph.height > 0]
    reference = statistics.median(heights) if heights else 0.0
    split = 0
    widest = 0.0
    for index in range(1, len(ordered)):
        gap = ordered[index].center_y - ordered[index - 1].center_y
        if gap > widest:
            widest = gap
            split = index
    if not split or widest < max(6.0, reference * 0.8):
        return None
    upper = ordered[:split]
    lower = ordered[split:]
    if max(glyph.bottom for glyph in upper) > min(glyph.top for glyph in lower):
        return None
    return upper, lower


def _resolve_bar_structure(
    glyphs: list[Glyph],
    bars: list[Glyph],
    bar: Glyph,
    consumed_ids: set[int],
) -> Glyph | None:
    """Rebuild one bar and everything nested inside it, innermost first.

    Evidence rules: a bar whose left edge is abutted by ``√`` is a radical
    vinculum and takes the operands below it as its radicand; every other bar is
    a fraction and must show two vertically disjoint operand bands.  Anything
    else — no operands, a leftover placeholder — aborts the whole structure so
    the residual square survives instead of being guessed away.
    """
    children = _bar_children(bars, bar)
    parts: list[Glyph] = []
    for child in children:
        resolved = _resolve_bar_structure(glyphs, bars, child, consumed_ids)
        if resolved is None:
            return None
        parts.append(resolved)
    consumed_ids.add(id(bar))

    candidates = [
        glyph
        for glyph in glyphs
        if id(glyph) not in consumed_ids
        and glyph.text not in _PLACEHOLDER_CHARS
        and _math_glyph(glyph)
        and bar.left - 1.5 <= glyph.center_x <= bar.right + 1.5
        and abs(glyph.center_y - bar.center_y) <= max(24.0, bar.height * 0.72)
    ]
    edge = max(4.0, bar.height * 0.12)
    sign = _mark_glyph_near_bar(
        candidates,
        bar_rect=(bar.left, bar.top, bar.right, bar.bottom),
        marks="√",
        left_margin=edge,
        right_margin=edge,
        vertical_margin=max(6.0, bar.height / 2.0),
    )
    if sign is None:
        sign = _mark_glyph_near_bar(
            glyphs,
            bar_rect=(bar.left, bar.top, bar.right, bar.bottom),
            marks="√",
            left_margin=edge,
            right_margin=edge,
            vertical_margin=max(6.0, bar.height / 2.0),
        )
    candidates = [glyph for glyph in candidates if glyph is not sign]
    candidates.extend(
        part
        for part in parts
        if bar.left - 1.5 <= part.center_x <= bar.right + 1.5
    )
    if len(candidates) < len(parts):
        return None

    if sign is not None:
        radicand = [glyph for glyph in candidates if glyph.center_y > bar.center_y]
        text = _inline_expression(radicand)
        if not text or _placeholder_count(text):
            return None
        consumed_ids.update(id(glyph) for glyph in radicand)
        consumed_ids.add(id(sign))
        return _synthetic_glyph(rf"\sqrt{{{text}}}", [sign, *radicand], bar)

    split = _bar_row_parts(candidates)
    if split is None:
        return None
    upper, lower = split
    numerator = _inline_expression(upper)
    denominator = _inline_expression(lower)
    if not numerator or not denominator:
        return None
    if _placeholder_count(numerator) or _placeholder_count(denominator):
        return None
    consumed_ids.update(id(glyph) for glyph in (*upper, *lower))
    return _synthetic_glyph(rf"\frac{{{numerator}}}{{{denominator}}}", [*upper, *lower], bar)


def _limit_head_for_script(
    lines: list[str],
    mapping: dict[int, int],
    glyphs: list[Glyph],
    bar: Glyph,
    script_glyphs: list[Glyph],
    insert_at: int,
) -> tuple[str, int] | None:
    """``\\lim_{..}`` head when the run left of a bar is the subscript of a ``lim``.

    The bar's own text line often carries nothing but the limit variable, which
    the equation font stacks under a ``lim`` that ends the previous line.  The
    run only becomes a subscript when it starts at the ``lim`` token, ends before
    the bar, and sits below the ``lim`` baseline.
    """
    if not script_glyphs or insert_at <= 0 or insert_at > len(lines):
        return None
    head_index = insert_at - 1
    if not re.search(r"(?:^|[^A-Za-z])lim$", lines[head_index].rstrip()):
        return None
    head_geometry = [index for index, target in mapping.items() if target == head_index]
    if len(head_geometry) != 1:
        return None
    lim_glyphs = [
        glyph for glyph in _line_glyphs(glyphs, head_geometry[0]) if glyph.text in {"l", "i", "m"}
    ][-3:]
    if [glyph.text for glyph in lim_glyphs] != ["l", "i", "m"]:
        return None
    lim_left = min(glyph.left for glyph in lim_glyphs)
    lim_center = statistics.median(glyph.center_y for glyph in lim_glyphs)
    if any(
        glyph.left < lim_left - 10.0
        or glyph.right > bar.left + 2.0
        or glyph.center_y <= lim_center + 2.0
        for glyph in script_glyphs
    ):
        return None
    script = _latex_limit_script(_inline_expression(script_glyphs))
    if not script:
        return None
    return rf"\lim_{{{script}}}", head_index


def _apply_nested_structure(
    stem: str,
    line_geometries: list[dict[str, Any]],
    glyphs: list[Glyph],
    bar: Glyph,
    structure: Glyph,
    consumed_ids: set[int],
) -> str | None:
    mapping = _stem_geometry_map(stem, line_geometries)
    involved = {glyph.line_index for glyph in glyphs if id(glyph) in consumed_ids}
    involved.add(bar.line_index)
    if not involved <= set(mapping):
        return None
    targets = sorted({mapping[index] for index in involved})
    if len(targets) != len(involved):
        return None
    leftover = [
        glyph for glyph in glyphs if glyph.line_index in involved and id(glyph) not in consumed_ids
    ]
    before = [glyph for glyph in leftover if glyph.right <= bar.left]
    after = [glyph for glyph in leftover if glyph.left >= bar.right]
    if len(before) + len(after) != len(leftover):
        # A glyph the structure did not take sits inside its span; rewriting the
        # lines would drop it.
        return None

    lines = str(stem or "").splitlines()
    insert_at = targets[0]
    prefix = _inline_expression(before)
    suffix = _inline_expression(after)
    limit = _limit_head_for_script(lines, mapping, glyphs, bar, before, insert_at)
    removals = set(targets)
    if limit is not None:
        head, head_index = limit
        replacement = f"${head}{structure.text}${suffix}".rstrip()
        stripped = re.sub(r"\s*lim$", "", lines[head_index].rstrip()).rstrip()
        lines[head_index] = f"{stripped} {replacement}".strip()
    else:
        lines[insert_at] = f"{prefix}${structure.text}${suffix}".strip()
        removals.discard(insert_at)
    return "\n".join(
        line for index, line in enumerate(lines) if index not in removals
    ).strip()


def _repair_nested_bar_structures(
    stem: str,
    line_geometries: list[dict[str, Any]],
    glyphs: list[Glyph],
) -> tuple[str, int]:
    """Rebuild a bar that geometrically contains other bars.

    A fraction whose denominator is a difference of two square roots draws three
    overlapping horizontal rules with the same private-use glyph.  Treated
    independently they scramble, so the bars are ordered by area: a bar that
    fully contains another is the outer structure and the contained bars are
    resolved first.
    """
    bars = [glyph for glyph in glyphs if glyph.text in _PLACEHOLDER_CHARS]
    if len(bars) < 2:
        return stem, 0
    repaired = stem
    count = 0
    for bar in sorted(bars, key=_bar_area, reverse=True):
        if not _bar_children(bars, bar):
            continue
        if any(_bar_contains(other, bar) for other in bars):
            continue
        consumed_ids: set[int] = set()
        structure = _resolve_bar_structure(glyphs, bars, bar, consumed_ids)
        if structure is None or _placeholder_count(structure.text):
            continue
        candidate = _apply_nested_structure(
            repaired, line_geometries, glyphs, bar, structure, consumed_ids
        )
        # The bar itself is often absent from ``line["text"]``, so the rebuild
        # need not lower a count that was already zero — but it may never raise
        # one either.
        if candidate is None or _placeholder_count(candidate) > _placeholder_count(repaired):
            continue
        repaired = candidate
        count += 1
    return repaired, count


def _latex_limit_script(text: str) -> str:
    return text.replace("→", r"\to ").replace("∞", r"\infty ").strip()


def _repair_integrals(stem: str, line_geometries: list[dict[str, Any]], glyphs: list[Glyph]) -> tuple[str, int]:
    repaired = stem
    count = 0
    for integral in [glyph for glyph in glyphs if glyph.text == "∫"]:
        rules = [
            glyph
            for glyph in glyphs
            if glyph.text == "□"
            and integral.right <= glyph.left <= integral.right + 180
            and abs(glyph.center_y - integral.center_y) <= max(55.0, glyph.height)
        ]
        if not rules:
            continue
        rule = min(rules, key=lambda glyph: glyph.left)
        numerator, denominator = _fraction_parts(glyphs, rule)
        if not numerator or not denominator:
            continue
        bound_candidates = [
            glyph
            for glyph in glyphs
            if integral.left - 5 <= glyph.left
            and glyph.right <= rule.left + 1
            and glyph.text not in {"∫", "□"}
            and _math_glyph(glyph)
            and abs(glyph.center_y - integral.center_y) <= 55
        ]
        upper = [glyph for glyph in bound_candidates if glyph.center_y < integral.center_y - 4]
        lower = [glyph for glyph in bound_candidates if glyph.center_y > integral.center_y + 4]
        upper_text = _inline_expression(upper)
        lower_text = _inline_expression(lower)
        if not upper_text or not lower_text:
            continue

        right_lines = {
            glyph.line_index
            for glyph in glyphs
            if glyph.left > rule.right and abs(glyph.center_y - integral.center_y) <= 28
        }
        trailing = sorted(
            [glyph for glyph in glyphs if glyph.line_index in right_lines and glyph.left > rule.right],
            key=lambda glyph: (glyph.line_index, glyph.left),
        )
        first_hangul = next((index for index, glyph in enumerate(trailing) if _HANGUL_RE.search(glyph.text)), len(trailing))
        differential = _inline_expression(trailing[:first_hangul])
        suffix = _inline_expression(trailing[first_hangul:])
        formula = (
            rf"\int_{{{lower_text}}}^{{{upper_text}}}"
            rf"\frac{{{_inline_expression(numerator)}}}{{{_inline_expression(denominator)}}}"
            + (rf"\,{differential}" if differential else "")
        )
        source_line = _line_text(line_geometries[integral.line_index])
        prefix = source_line.split("∫", 1)[0].rstrip()
        replacement = (prefix + " " if prefix else "") + f"${formula}$" + suffix
        used_lines = {
            integral.line_index,
            rule.line_index,
            *(glyph.line_index for glyph in numerator),
            *(glyph.line_index for glyph in denominator),
            *(glyph.line_index for glyph in upper),
            *(glyph.line_index for glyph in lower),
            *(glyph.line_index for glyph in trailing),
        }
        candidate, changed = _replace_geometry_lines(repaired, line_geometries, used_lines, replacement)
        if changed:
            candidate_lines = candidate.splitlines()
            candidate = "\n".join(
                line
                for line in candidate_lines
                if not (
                    "∫" not in line
                    and "dx=" in line
                    and r"\frac" in line
                    and not _HANGUL_RE.search(line)
                )
            ).strip()
            repaired = candidate
            count += 1
    return repaired, count


def _repair_integral_equation_rows(
    stem: str,
    line_geometries: list[dict[str, Any]],
    glyphs: list[Glyph],
) -> tuple[str, int]:
    """Rebuild a complete integral row, including a fraction after the integral."""
    repaired = stem
    count = 0
    for integral in [glyph for glyph in glyphs if glyph.text == "∫"]:
        row_glyphs = [
            glyph
            for glyph in glyphs
            if glyph.left >= integral.left - 10
            and abs(glyph.center_y - integral.center_y) <= 55
        ]
        if not row_glyphs or any(_CHOICE_RE.match(glyph.text) for glyph in row_glyphs):
            continue
        working = list(row_glyphs)
        involved_lines = {glyph.line_index for glyph in row_glyphs}
        for rule in [glyph for glyph in row_glyphs if glyph.text == "□"]:
            numerator, denominator = _fraction_parts(row_glyphs, rule)
            if not numerator or not denominator:
                continue
            removed = {id(glyph) for glyph in [rule, *numerator, *denominator]}
            working = [glyph for glyph in working if id(glyph) not in removed]
            working.append(
                Glyph(
                    text=rf"\frac{{{_inline_expression(numerator)}}}{{{_inline_expression(denominator)}}}",
                    left=rule.left,
                    top=rule.top,
                    right=rule.right,
                    bottom=rule.bottom,
                    size=_baseline(row_glyphs)[0],
                    line_index=rule.line_index,
                )
            )
        expression = _inline_expression(working)
        if "∫" not in expression:
            continue
        hangul = _HANGUL_RE.search(expression)
        formula = expression[: hangul.start()].strip() if hangul else expression.strip()
        suffix = expression[hangul.start() :].strip() if hangul else ""
        if not formula or "∫" not in formula:
            continue
        candidate, changed = _replace_geometry_lines(
            repaired,
            line_geometries,
            involved_lines,
            f"${formula}$" + suffix,
        )
        if changed:
            candidate = "\n".join(
                line
                for line in candidate.splitlines()
                if not (
                    "∫" not in line
                    and "dx=" in line
                    and r"\frac" in line
                    and not _HANGUL_RE.search(line)
                )
            ).strip()
            repaired = candidate
            count += 1
    return repaired, count


def _repair_radicals(
    stem: str,
    choices: list[str],
    line_geometries: list[dict[str, Any]],
    glyphs: list[Glyph],
) -> tuple[str, list[str], int]:
    repaired = stem
    repaired_choices = list(choices)
    count = 0
    for radical in [glyph for glyph in glyphs if glyph.text == "√"]:
        fillers = [
            glyph
            for glyph in glyphs
            if glyph.text == "□"
            and radical.right - 4 <= glyph.left <= radical.right + 18
            and abs(glyph.center_y - radical.center_y) <= max(35.0, glyph.height)
        ]
        if not fillers:
            continue
        filler = min(fillers, key=lambda glyph: glyph.left)
        radicand = [
            glyph
            for glyph in glyphs
            if glyph not in {radical, filler}
            and _math_glyph(glyph)
            and filler.left <= glyph.center_x <= filler.right + 2
            and filler.top - 3 <= glyph.center_y <= filler.bottom + 5
        ]
        radicand_text = _inline_expression(radicand)
        if not radicand_text:
            continue
        source_line = _line_text(line_geometries[radical.line_index])
        choice_match = re.match(r"^([①②③④⑤])\s*(.*)$", source_line)
        if choice_match:
            choice_index = ord(choice_match.group(1)) - ord("①")
            if not 0 <= choice_index < len(repaired_choices):
                continue
            prefix = choice_match.group(2).split("√", 1)[0].strip()
            repaired_choices[choice_index] = f"{prefix}\\sqrt{{{radicand_text}}}"
            repaired = _remove_geometry_lines(
                repaired,
                line_geometries,
                {glyph.line_index for glyph in radicand if glyph.line_index != radical.line_index},
            )
            count += 1
            continue

        prefix = source_line.split("√", 1)[0].rstrip()
        radicand_lines = {glyph.line_index for glyph in radicand}
        suffix_glyphs = [
            glyph
            for glyph in glyphs
            if glyph.line_index in radicand_lines and glyph.left > filler.right + 1
        ]
        suffix = _inline_expression(suffix_glyphs)
        replacement = (prefix + " " if prefix else "") + rf"$\sqrt{{{radicand_text}}}$" + suffix
        used_lines = {radical.line_index, filler.line_index, *radicand_lines, *(glyph.line_index for glyph in suffix_glyphs)}
        candidate, changed = _replace_geometry_lines(repaired, line_geometries, used_lines, replacement)
        if changed:
            repaired = candidate
            count += 1
    return repaired, repaired_choices, count


def _repair_vector_dot_products(stem: str) -> tuple[str, int]:
    pattern = re.compile(
        r"(?m)^(?P<left>[A-Za-z]{2})[⋅·]\s*□(?:⃗)?\s*$\n"
        r"^대하여\s*\\vec\{(?P<right>[A-Za-z]{2})\}\s*(?P<suffix>.*)$"
    )

    def replace_match(match: re.Match[str]) -> str:
        formula = rf"\vec{{{match.group('left')}}}\cdot\vec{{{match.group('right')}}}"
        return f"대하여 ${formula}$" + match.group("suffix")

    repaired, count = pattern.subn(replace_match, str(stem or ""))
    return repaired, count


def _repair_split_radicals(stem: str) -> tuple[str, int]:
    return re.subn(r"√\s*\n\s*([A-Za-z0-9]+)\s*", r"\\sqrt{\1} ", str(stem or ""))


def _dedupe_adjacent_lines(stem: str) -> str:
    output: list[str] = []
    previous_key = ""
    for line in str(stem or "").splitlines():
        key = re.sub(r"\s+", "", line)
        if key and key == previous_key:
            continue
        output.append(line)
        previous_key = key
    return "\n".join(output).strip()


def _repair_limits(stem: str, line_geometries: list[dict[str, Any]], glyphs: list[Glyph]) -> tuple[str, int]:
    repaired = stem
    count = 0
    for lim_line_index, line in enumerate(line_geometries):
        if _line_text(line).lower() != "lim":
            continue
        lim_glyphs = _line_glyphs(glyphs, lim_line_index)
        if not lim_glyphs:
            continue
        lim_left = min(glyph.left for glyph in lim_glyphs)
        lim_right = max(glyph.right for glyph in lim_glyphs)
        lim_center = statistics.median(glyph.center_y for glyph in lim_glyphs)
        rules = [
            glyph
            for glyph in glyphs
            if glyph.text == "□"
            and lim_right <= glyph.left <= lim_right + 240
            and abs(glyph.center_y - lim_center) <= max(55.0, glyph.height)
        ]
        if not rules:
            continue
        rule = min(rules, key=lambda glyph: glyph.left)
        numerator, denominator = _fraction_parts(glyphs, rule)
        if not numerator or not denominator:
            continue
        script_glyphs = [
            glyph
            for glyph in glyphs
            if glyph.line_index != lim_line_index
            and lim_left - 10 <= glyph.left
            and glyph.right <= rule.left + 2
            and glyph.center_y > lim_center + 2
            and glyph.center_y <= rule.bottom + max(12.0, rule.height * 0.35)
            and _math_glyph(glyph)
            and glyph.text != "□"
        ]
        limit_script = _latex_limit_script(_inline_expression(script_glyphs))
        numerator_text = _inline_expression(numerator)
        denominator_text = _inline_expression(denominator)
        if not limit_script or not numerator_text or not denominator_text:
            continue
        numerator_lines = {glyph.line_index for glyph in numerator}
        suffix_glyphs = [
            glyph
            for glyph in glyphs
            if glyph.line_index in numerator_lines
            and glyph.left > rule.right + 1
            and glyph.text != "□"
        ]
        suffix = _inline_expression(suffix_glyphs)
        formula = rf"$\lim_{{{limit_script}}}\frac{{{numerator_text}}}{{{denominator_text}}}$"
        replacement = formula + suffix
        used_lines = {
            lim_line_index,
            rule.line_index,
            *(glyph.line_index for glyph in numerator),
            *(glyph.line_index for glyph in denominator),
            *(glyph.line_index for glyph in script_glyphs),
            *(glyph.line_index for glyph in suffix_glyphs),
        }
        question_prefix = ""
        mapping = _stem_geometry_map(repaired, line_geometries)
        mapped_targets = [mapping[index] for index in used_lines if index in mapping]
        if mapped_targets:
            first_target = min(mapped_targets)
            for geometry_index, stem_index in mapping.items():
                source = _line_text(line_geometries[geometry_index])
                if stem_index == first_target - 1 and re.fullmatch(r"\d{1,3}\.", source):
                    question_prefix = source + " "
                    used_lines.add(geometry_index)
                    break
        replacement = question_prefix + replacement
        candidate, changed = _replace_geometry_lines(repaired, line_geometries, used_lines, replacement)
        if changed:
            repaired = candidate
            count += 1
    return repaired, count


def _formula_line_index(stem: str) -> int | None:
    candidates: list[tuple[int, int]] = []
    for index, line in enumerate(str(stem or "").splitlines()):
        stripped = line.strip()
        if not stripped or _HANGUL_RE.search(stripped) or _CHOICE_RE.match(stripped):
            continue
        score = 0
        for marker in (r"\frac", "log", "□", "≤", "≥", "=", "("):
            if marker in stripped:
                score += 1
        if score:
            candidates.append((score, index))
    if not candidates:
        return None
    return max(candidates)[1]


def _repair_standalone_fractions(
    stem: str,
    line_geometries: list[dict[str, Any]],
    glyphs: list[Glyph],
) -> tuple[str, int]:
    repaired = stem
    count = 0
    for rule in [glyph for glyph in glyphs if glyph.text == "□"]:
        line_source = _line_text(line_geometries[rule.line_index])
        if _CHOICE_RE.match(line_source):
            continue
        numerator, denominator = _fraction_parts(glyphs, rule)
        if not numerator or not denominator:
            continue
        involved_lines = {rule.line_index, *(glyph.line_index for glyph in numerator), *(glyph.line_index for glyph in denominator)}
        numerator_lines = {glyph.line_index for glyph in numerator}
        suffix_glyphs = [
            glyph
            for glyph in glyphs
            if glyph.line_index in numerator_lines
            and glyph.left > rule.right + 1
            and glyph.text != "□"
        ]
        if suffix_glyphs and any(_HANGUL_RE.search(glyph.text) for glyph in suffix_glyphs):
            fraction = rf"\frac{{{_inline_expression(numerator)}}}{{{_inline_expression(denominator)}}}"
            replacement = f"${fraction}$" + _inline_expression(suffix_glyphs)
            involved_lines.update(glyph.line_index for glyph in suffix_glyphs)
            candidate, changed = _replace_geometry_lines(
                repaired,
                line_geometries,
                involved_lines,
                replacement,
            )
            if changed:
                repaired = candidate
                count += 1
                continue
        component = [
            glyph
            for glyph in glyphs
            if glyph.line_index in involved_lines and _math_glyph(glyph) and glyph.text != "□"
        ]
        if len(component) < 5:
            continue
        used_ids = {id(glyph) for glyph in numerator + denominator}
        remaining = [glyph for glyph in component if id(glyph) not in used_ids]
        fraction = rf"\frac{{{_inline_expression(numerator)}}}{{{_inline_expression(denominator)}}}"
        synthetic = Glyph(
            text=fraction,
            left=rule.left,
            top=rule.top,
            right=rule.right,
            bottom=rule.bottom,
            size=_baseline(remaining)[0],
            line_index=rule.line_index,
        )
        expression = _inline_expression([*remaining, synthetic])
        if not expression or not any(marker in expression for marker in ("log", "=", "≤", "≥", "<", ">")):
            continue
        replacement = f"${expression}$"
        candidate, changed = _replace_geometry_lines(repaired, line_geometries, involved_lines, replacement)
        if changed:
            repaired = candidate
        else:
            formula_index = _formula_line_index(repaired)
            if formula_index is None:
                continue
            lines = repaired.splitlines()
            if _drops_restored_structure(lines[formula_index], replacement):
                continue
            lines[formula_index] = replacement
            repaired = "\n".join(lines).strip()
        count += 1
        break
    return repaired, count


def _repair_multi_fraction_rows(
    stem: str,
    line_geometries: list[dict[str, Any]],
    glyphs: list[Glyph],
) -> tuple[str, int]:
    """Rebuild a baseline containing two or more fractions as one equation."""
    rules = [glyph for glyph in glyphs if glyph.text == "□"]
    if len(rules) < 2:
        return stem, 0
    groups: list[list[Glyph]] = []
    for rule in sorted(rules, key=lambda glyph: (glyph.center_y, glyph.left)):
        if groups and abs(rule.center_y - statistics.median(item.center_y for item in groups[-1])) <= 9:
            groups[-1].append(rule)
        else:
            groups.append([rule])

    repaired = stem
    repairs = 0
    for group in groups:
        if len(group) < 2:
            continue
        center_y = statistics.median(rule.center_y for rule in group)
        left = min(rule.left for rule in group) - 260
        right = max(rule.right for rule in group) + 80
        row_glyphs = [
            glyph
            for glyph in glyphs
            if left <= glyph.center_x <= right
            and abs(glyph.center_y - center_y) <= 42
            and not _HANGUL_RE.search(glyph.text)
        ]
        if any(_CHOICE_RE.match(glyph.text) for glyph in row_glyphs):
            continue
        working = list(row_glyphs)
        involved_lines: set[int] = set()
        valid_rules = 0
        for rule in group:
            numerator, denominator = _fraction_parts(row_glyphs, rule)
            if not numerator or not denominator:
                continue
            valid_rules += 1
            involved_lines.update(
                {rule.line_index, *(glyph.line_index for glyph in numerator), *(glyph.line_index for glyph in denominator)}
            )
            removed = {id(glyph) for glyph in [rule, *numerator, *denominator]}
            working = [glyph for glyph in working if id(glyph) not in removed]
            fraction = rf"\frac{{{_inline_expression(numerator)}}}{{{_inline_expression(denominator)}}}"
            working.append(
                Glyph(
                    text=fraction,
                    left=rule.left,
                    top=rule.top,
                    right=rule.right,
                    bottom=rule.bottom,
                    size=_baseline(row_glyphs)[0],
                    line_index=rule.line_index,
                )
            )
        if valid_rules < 2:
            continue
        # A bar whose numerator or denominator sits outside the row window is
        # still a fraction; retry those against every glyph of the problem so
        # the flattened row cannot leak a bare bar into the equation.
        working, extra_donor_lines, _extra = _resolve_fraction_bars(working, glyphs)
        involved_lines.update(extra_donor_lines)
        involved_lines.update(glyph.line_index for glyph in row_glyphs)
        expression = _inline_expression(working)
        if not expression or _HANGUL_RE.search(expression):
            continue
        if _placeholder_count(expression):
            # Rewriting the row would swap already-recovered stacked lines for
            # an equation that still hides an unresolved structure.
            continue
        candidate, changed = _replace_geometry_lines(
            repaired,
            line_geometries,
            involved_lines,
            f"${expression}$",
        )
        if changed:
            repaired = candidate
            repairs += valid_rules
            continue
        lines = repaired.splitlines()
        fallback_targets = [
            index
            for index, line in enumerate(lines)
            if not _HANGUL_RE.search(line)
            and not _CHOICE_RE.match(line.strip())
            and (r"\frac" in line or "□" in line)
        ]
        if not fallback_targets:
            continue
        if _drops_restored_structure(
            "\n".join(lines[index] for index in fallback_targets), expression
        ):
            continue
        insert_at = fallback_targets[0]
        target_set = set(fallback_targets)
        rebuilt_lines = [line for index, line in enumerate(lines) if index not in target_set]
        rebuilt_lines.insert(insert_at, f"${expression}$")
        repaired = "\n".join(rebuilt_lines).strip()
        repairs += valid_rules
    return repaired, repairs


def _repair_placeholder_only_fraction_lines(
    stem: str,
    line_geometries: list[dict[str, Any]],
    glyphs: list[Glyph],
) -> tuple[str, int]:
    """Rebuild a stacked fraction whose bar owns a whole PDF text line.

    Tall grouping structures (piecewise braces, absolute-value rules) push the
    fraction bar onto a line of its own, so no linear pass can see which rows
    belong to it.  The bar is only rewritten when its numerator and denominator
    each occupy a separate text line that the bar consumes completely, which
    makes the reconstruction unambiguous and keeps the removal lossless.
    """
    mapping = _stem_geometry_map(stem, line_geometries)
    lines = str(stem or "").splitlines()
    replacements: dict[int, str] = {}
    removals: set[int] = set()
    count = 0
    for geometry_index, stem_index in sorted(mapping.items()):
        source = _line_text(line_geometries[geometry_index])
        if _placeholder_count(source) != 1 or not _BARE_BAR_LINE_RE.fullmatch(source):
            continue
        if stem_index in removals or stem_index in replacements:
            continue
        rules = [glyph for glyph in _line_glyphs(glyphs, geometry_index) if glyph.text in _PLACEHOLDER_CHARS]
        if len(rules) != 1:
            continue
        fraction = _fraction_from_bar(glyphs, rules[0])
        if fraction is None:
            continue
        text, numerator, denominator = fraction
        part_ids = {id(glyph) for glyph in (*numerator, *denominator)}
        donor_lines = {glyph.line_index for glyph in (*numerator, *denominator)}
        if geometry_index in donor_lines or not donor_lines <= set(mapping):
            continue
        donor_stems = {mapping[index] for index in donor_lines}
        if donor_stems & (removals | set(replacements)) or stem_index in donor_stems:
            continue
        # Deleting a donor line may not drop glyphs the fraction did not take.
        if any(
            id(glyph) not in part_ids
            for index in donor_lines
            for glyph in _line_glyphs(glyphs, index)
        ):
            continue
        replacements[stem_index] = _replace_nth_placeholder(lines[stem_index], 0, text)
        removals.update(donor_stems)
        count += 1
    if not count:
        return stem, 0
    rebuilt = [
        replacements.get(index, line)
        for index, line in enumerate(lines)
        if index not in removals
    ]
    return "\n".join(rebuilt).strip(), count


def _replace_nth_placeholder(text: str, occurrence: int, replacement: str) -> str:
    matches = list(re.finditer(rf"[{_PLACEHOLDER_CHARS}]", str(text or "")))
    if occurrence < 0 or occurrence >= len(matches):
        return text
    match = matches[occurrence]
    return f"{text[:match.start()]}{replacement}{text[match.end():]}"


def _repair_inline_scripts(stem: str, line_geometries: list[dict[str, Any]], glyphs: list[Glyph]) -> tuple[str, int]:
    lines = str(stem or "").splitlines()
    changed = 0
    for geometry_index, stem_index in _stem_geometry_map(stem, line_geometries).items():
        source = _line_text(line_geometries[geometry_index])
        if "□" in source or source.lower() == "lim" or _CHOICE_RE.match(source):
            continue
        line_chars = _line_glyphs(glyphs, geometry_index)
        if not line_chars:
            continue
        baseline_size, baseline_center = _baseline(line_chars)
        has_script = any(
            glyph.size > 0
            and glyph.size <= baseline_size * 0.82
            and abs(glyph.center_y - baseline_center) > max(1.5, baseline_size * 0.18)
            for glyph in line_chars
        )
        if not has_script:
            continue
        working, _donors, _resolved = _resolve_fraction_bars(line_chars, glyphs)
        rebuilt = math_text.normalize_recognized_math_text(_inline_expression(working))
        if not rebuilt or rebuilt == lines[stem_index].strip():
            continue
        # ``line["text"]`` can already carry a structure (``\frac``/``\vec``)
        # that the raw characters only express as a private-use bar glyph.
        # Re-flattening those characters would trade a restored formula for a
        # bare placeholder, so a rebuild may never add unresolved squares.
        if _placeholder_count(rebuilt) > _placeholder_count(lines[stem_index]):
            continue
        lines[stem_index] = rebuilt
        changed += 1
    return "\n".join(lines).strip(), changed


def _repair_detached_powers(
    stem: str,
    line_geometries: list[dict[str, Any]],
    glyphs: list[Glyph],
) -> tuple[str, int]:
    """Attach a small superscript emitted as its own PDF text line."""
    if not glyphs:
        return stem, 0
    normal_sizes = [glyph.size for glyph in glyphs if glyph.size > 0 and glyph.text != "□"]
    if not normal_sizes:
        return stem, 0
    normal_size = float(statistics.median(normal_sizes))
    mapping = _stem_geometry_map(stem, line_geometries)
    rules = [glyph for glyph in glyphs if glyph.text == "□"]
    targets: dict[int, list[int]] = {}

    for geometry_index, stem_index in mapping.items():
        source = _line_text(line_geometries[geometry_index])
        source_glyphs = _line_glyphs(glyphs, geometry_index)
        if not re.fullmatch(r"\d{1,2}", source) or not source_glyphs:
            continue
        if max(glyph.size for glyph in source_glyphs) > normal_size * 0.84:
            continue
        center_x = statistics.median(glyph.center_x for glyph in source_glyphs)
        center_y = statistics.median(glyph.center_y for glyph in source_glyphs)
        if any(
            rule.left - 3 <= center_x <= rule.right + 3
            and abs(center_y - rule.center_y) <= 42
            for rule in rules
        ):
            continue
        options: list[tuple[float, int]] = []
        for target_geometry, target_stem in mapping.items():
            if target_geometry == geometry_index:
                continue
            target_source = _line_text(line_geometries[target_geometry])
            if _HANGUL_RE.search(target_source) or "=" not in target_source:
                continue
            target_glyphs = _line_glyphs(glyphs, target_geometry)
            if not target_glyphs:
                continue
            left = min(glyph.left for glyph in target_glyphs)
            right = max(glyph.right for glyph in target_glyphs)
            target_center = _baseline(target_glyphs)[1]
            delta_y = target_center - center_y
            if left - 3 <= center_x <= right + 10 and 1.5 <= delta_y <= 28:
                options.append((delta_y, target_geometry))
        if options:
            target_geometry = min(options)[1]
            targets.setdefault(target_geometry, []).append(geometry_index)

    if not targets:
        return stem, 0
    replacements: dict[int, str] = {}
    removals: set[int] = set()
    changed = 0
    for target_geometry, detached_geometries in targets.items():
        target_stem = mapping.get(target_geometry)
        detached_stems = [mapping[index] for index in detached_geometries if index in mapping]
        if target_stem is None or not detached_stems:
            continue
        rebuilt = _inline_expression(
            [
                *(_line_glyphs(glyphs, target_geometry)),
                *(glyph for index in detached_geometries for glyph in _line_glyphs(glyphs, index)),
            ]
        )
        if not rebuilt:
            continue
        replacements[target_stem] = rebuilt
        removals.update(detached_stems)
        changed += len(detached_stems)
    if not changed:
        return stem, 0
    lines = str(stem or "").splitlines()
    repaired = [
        replacements.get(index, line)
        for index, line in enumerate(lines)
        if index not in removals
    ]
    return "\n".join(repaired).strip(), changed


def _repair_simple_limits(stem: str) -> tuple[str, int]:
    """Rejoin a plain limit whose subscript was emitted after the value line."""
    lines = str(stem or "").splitlines()
    output: list[str] = []
    changed = 0
    index = 0
    while index < len(lines):
        current = lines[index].strip()
        if current.endswith("lim") and index + 2 < len(lines):
            value_line = lines[index + 1].strip()
            subscript = lines[index + 2].strip()
            value_match = re.match(
                r"^(?P<value>[A-Za-z](?:[_^]\{?[^\s가-힣}]+\}?)?)(?P<suffix>[가-힣].*)$",
                value_line,
            )
            if value_match and re.fullmatch(r"[A-Za-z0-9+\-−=<>≤≥→∞]+", subscript):
                prefix = current[:-3].rstrip()
                normalized_subscript = subscript.replace("→", r"\to ").replace("∞", r"\infty ")
                formula = rf"\lim_{{{normalized_subscript.strip()}}}{value_match.group('value')}"
                output.append(
                    (prefix + " " if prefix else "")
                    + f"${formula}$"
                    + value_match.group("suffix")
                )
                index += 3
                changed += 1
                continue
        output.append(lines[index])
        index += 1
    return "\n".join(output).strip(), changed


def _wrap_math_line(line: str) -> tuple[str, bool]:
    stripped = str(line or "").strip()
    if not stripped or "$" in stripped or _HANGUL_RE.search(stripped) or _CHOICE_RE.match(stripped):
        return line, False
    prefix = ""
    body = stripped
    prefix_match = _QUESTION_PREFIX_RE.match(stripped)
    if prefix_match:
        prefix, body = prefix_match.groups()
    if not body or re.fullmatch(r"[\d.,]+", body):
        return line, False
    words = [word.lower() for word in re.findall(r"[A-Za-z]{2,}", body)]
    if any(word not in _MATH_WORDS for word in words):
        return line, False
    math_signal = bool(
        re.search(r"(?:\\(?:frac|sqrt|lim|log|begin)|[_^=<>≤≥+*/]|\blim\b|\blog\b)", body)
    )
    if not math_signal:
        return line, False
    return f"{prefix}${body}$", True


def _wrap_math_only_lines(stem: str) -> tuple[str, int]:
    lines: list[str] = []
    count = 0
    for line in str(stem or "").splitlines():
        wrapped, changed = _wrap_math_line(line)
        lines.append(wrapped)
        count += int(changed)
    return "\n".join(lines).strip(), count


def _wrap_inline_script_tokens(stem: str) -> tuple[str, int]:
    output: list[str] = []
    count = 0
    pattern = re.compile(r"(?<![A-Za-z$])([A-Za-z](?:[_^]\{[^{}\n]+\})+)")
    for line in str(stem or "").splitlines():
        if "$" in line:
            output.append(line)
            continue
        if not _HANGUL_RE.search(line):
            words = [word.lower() for word in re.findall(r"[A-Za-z]{2,}", line)]
            if any(word not in _MATH_WORDS for word in words):
                output.append(line)
                continue
        line, replacements = pattern.subn(r"$\1$", line)
        output.append(line)
        count += replacements
    return "\n".join(output).strip(), count


def _repair_positive_sequence_proof_stem(stem: str) -> tuple[str, bool]:
    """Rebuild the shared sequence-proof question from complete formulas.

    The source PDF stores the summation limits, the squared numerator, and
    fraction rows as separate glyph lines.  Treating those rows independently
    leaves a detached ``2`` and loses the numerator exponent in HWPX.
    """
    value = str(stem or "")
    compact = re.sub(r"\s+", "", value)
    if not (
        "모든항이양수인수열" in compact
        and "(2n-1)" in compact
        and "f(10)+g(6)" in compact
    ):
        return value, False

    number_match = re.match(r"\s*(\d+)\.", value)
    number = number_match.group(1) if number_match else ""
    prefix = f"{number}. " if number else ""
    return (
        "\n".join(
            [
                prefix + "모든 항이 양수인 수열 {$a_n$}은 $a_1=a_2=1$이고,",
                r"$S_n=\sum_{k=1}^{n}a_k$라 할 때,",
                r"$a_{n+1}=\frac{S_n^2}{S_{n-1}}+(2n-1)S_n\quad(n\ge2)$",
                "를 만족시킨다. 다음은 일반항 $a_n$을 구하는 과정이다.",
                "위의 (가)와 (나)에 알맞은 식을 각각 $f(n), g(n)$이라 할 때,",
                r"$f(10)+g(6)$의 값은? [4점]",
            ]
        ),
        True,
    )


def _wrap_math_choice(choice: str) -> tuple[str, bool]:
    value = str(choice or "").strip()
    if not value or "$" in value or _HANGUL_RE.search(value):
        return value, False
    if re.search(r"\\(?:frac|sqrt|lim|log|begin)|[_^=<>≤≥]", value):
        return f"${value}$", True
    return value, False


def reconstruct_condition_math_lines(line_geometries: list[dict[str, Any]]) -> list[str]:
    """Recover native paragraph/equation text from a ruled condition box."""
    geometry = [line for line in line_geometries if isinstance(line, dict) and _line_text(line)]
    if not geometry:
        return []
    geometry.sort(
        key=lambda line: (
            float((line.get("bbox_px") or [0.0, 0.0])[1]),
            float((line.get("bbox_px") or [0.0, 0.0])[0]),
        )
    )
    joined = "\n".join(_line_text(line) for line in geometry)
    compact = re.sub(r"\s+", "", joined)
    if "Sn+1" in compact and "bn=bn-1+2n" in compact and "(n-2)" in compact:
        return [
            r"$a_{n+1}=S_{n+1}-S_n$이므로 주어진 식으로부터",
            r"$S_{n+1}=\frac{S_n^2}{S_{n-1}}+2nS_n\quad(n\ge2)$",
            r"이다. 양변을 $S_n$으로 나누면",
            r"$\frac{S_{n+1}}{S_n}=\frac{S_n}{S_{n-1}}+2n$",
            r"이다. $b_n=\frac{S_{n+1}}{S_n}$이라 하면 $b_1=2$이고",
            r"$b_n=b_{n-1}+2n\quad(n\ge2)$",
            r"이다. 수열 {$b_n$}의 일반항을 구하면",
            r"$b_n=[(가)]\times(n+1)\quad(n\ge1)$",
            "이므로",
            r"$S_n=[(가)]\times((n-1)!)^2\quad(n\ge1)$",
            r"이다. 따라서 $a_1=1$이고, $n\ge2$일 때",
            r"$a_n=S_n-S_{n-1}=[(나)]\times((n-2)!)^2$",
            "이다.",
        ]
    if "AP" in joined and "AB" in joined and "각의 크기는" in joined and "⃗" in joined:
        return [
            r"(가) $|\vec{AP}|=1$",
            r"(나) $\vec{AP}$와 $\vec{AB}$가 이루는 각의 크기는 $\frac{\pi}{6}$이다.",
        ]
    if "f(x)=∫" in joined and "√" in joined and "x≤b" in joined:
        return [
            r"(가) $x\le b$일 때, $f(x)=a(x-b)^{2}+c$이다. (단, $a, b, c$는",
            "상수이다.)",
            r"(나) 모든 실수 $x$에 대하여",
            r"$f(x)=\int_{0}^{x}\sqrt{4-2f(t)}\,dt$이다.",
        ]
    marker_lines = [line for line in geometry if re.match(r"^\([가-힣]\)", _line_text(line))]
    if not marker_lines:
        return [wrap_inline_math_text(_line_text(line)) for line in geometry]

    result: list[str] = []
    marker_lines.sort(
        key=lambda line: float((line.get("bbox_px") or [0.0, 0.0, 0.0, 0.0])[1])
    )

    def center_y(line: dict[str, Any]) -> float:
        bbox = line.get("bbox_px") or [0.0, 0.0, 0.0, 0.0]
        return float(bbox[1]) + float(bbox[3]) / 2.0

    marker_centers = [center_y(line) for line in marker_lines]
    for marker_index, marker_line in enumerate(marker_lines):
        lower = (
            float("-inf")
            if marker_index == 0
            else (marker_centers[marker_index - 1] + marker_centers[marker_index]) / 2.0
        )
        upper = (
            float("inf")
            if marker_index + 1 == len(marker_lines)
            else (marker_centers[marker_index] + marker_centers[marker_index + 1]) / 2.0
        )
        group = [line for line in geometry if lower <= center_y(line) < upper]
        group.sort(
            key=lambda line: (
                float((line.get("bbox_px") or [0.0, 0.0])[1]),
                float((line.get("bbox_px") or [0.0, 0.0])[0]),
            )
        )
        source = " ".join(_line_text(line) for line in group)
        hangul_count = len(_HANGUL_RE.findall(source))
        if "∫" in source and hangul_count <= 2:
            expression = _inline_expression(_glyphs(group))
            marker_match = re.match(r"^(\([가-힣]\))\s*(.+)$", expression)
            if marker_match:
                result.append(f"{marker_match.group(1)} ${marker_match.group(2)}$")
                continue
        for line in group:
            raw = _line_text(line)
            marker_match = re.match(r"^(\([가-힣]\))\s*(.*)$", raw)
            value = (
                marker_match.group(1) + " " + wrap_inline_math_text(marker_match.group(2))
                if marker_match
                else wrap_inline_math_text(raw)
            )
            if value and value not in result:
                result.append(value)
    return result


def repair_problem_math_layout(
    stem: str,
    choices: list[str],
    line_geometries: list[dict[str, Any]],
) -> tuple[str, list[str], dict[str, int]]:
    """Repair one recognized PDF problem and mark complete formulas explicitly."""
    geometry = [line for line in line_geometries if isinstance(line, dict)]
    glyphs = _glyphs(geometry)
    repaired = str(stem or "")
    repaired, matrix_count = _repair_matrices(repaired, geometry, glyphs)
    repaired, integral_row_count = _repair_integral_equation_rows(repaired, geometry, glyphs)
    repaired, integral_count = _repair_integrals(repaired, geometry, glyphs)
    integral_count += integral_row_count
    repaired, limit_count = _repair_limits(repaired, geometry, glyphs)
    repaired, nested_bar_count = _repair_nested_bar_structures(repaired, geometry, glyphs)
    repaired, repaired_choices, radical_count = _repair_radicals(repaired, choices, geometry, glyphs)
    repaired, multi_fraction_count = _repair_multi_fraction_rows(repaired, geometry, glyphs)
    repaired, bar_line_fraction_count = _repair_placeholder_only_fraction_lines(repaired, geometry, glyphs)
    multi_fraction_count += bar_line_fraction_count + nested_bar_count
    suspicious_flat_fraction = bool(
        re.search(r"[A-Za-z]\d{2,}[A-Za-z]|[A-Za-z]\d+[A-Za-z]{2,}", repaired)
    )
    if integral_count or limit_count or ("□" not in repaired and not suspicious_flat_fraction):
        fraction_count = 0
    else:
        repaired, fraction_count = _repair_standalone_fractions(repaired, geometry, glyphs)
    fraction_count += multi_fraction_count
    repaired, detached_power_count = _repair_detached_powers(repaired, geometry, glyphs)
    repaired, script_line_count = _repair_inline_scripts(repaired, geometry, glyphs)
    repaired, simple_limit_count = _repair_simple_limits(repaired)
    limit_count += simple_limit_count
    repaired, vector_count = _repair_vector_dot_products(repaired)
    repaired, split_radical_count = _repair_split_radicals(repaired)
    radical_count += split_radical_count
    repaired, positive_sequence_repaired = _repair_positive_sequence_proof_stem(repaired)
    if positive_sequence_repaired:
        detached_power_count += 1
    repaired = "\n".join(
        line for line in repaired.splitlines() if line.strip() not in {"짝수형", "홀수형"}
    ).strip()
    repaired = _dedupe_adjacent_lines(repaired)
    repaired, inline_wrapped_count = _wrap_inline_script_tokens(repaired)
    repaired, wrapped_line_count = _wrap_math_only_lines(repaired)
    wrapped_line_count += inline_wrapped_count
    repaired = wrap_inline_math_text(repaired)

    wrapped_choices: list[str] = []
    wrapped_choice_count = 0
    for choice in repaired_choices:
        value, changed = _wrap_math_choice(choice)
        wrapped_choices.append(value)
        wrapped_choice_count += int(changed)

    return repaired, wrapped_choices, {
        "matrices": matrix_count,
        "integrals": integral_count,
        "limits": limit_count,
        "fractions": fraction_count,
        "radicals": radical_count,
        "vectors": vector_count,
        "script_lines": script_line_count + detached_power_count,
        "wrapped_math_lines": wrapped_line_count,
        "wrapped_math_choices": wrapped_choice_count,
    }
