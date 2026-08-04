# -*- coding: utf-8 -*-
"""Regression pins for PDF glyph-geometry math structure restoration.

Real exam PDFs draw a fraction bar, a vector accent, a radical vinculum, and an
empty answer box with the *same* private-use glyph, so every repair that
flattens raw characters can silently trade an already-restored formula for a
bare square placeholder.  The fixtures below are synthetic recreations of the
three failure shapes found in the local KICE samples; they never embed real
exam text.

Each pin states the evidence rule it protects:

1. ``_repair_inline_scripts`` rebuilds a line from raw glyphs to recover
   super/subscripts.  A bar with aligned glyphs above and below it must come
   back as ``\\frac``, and a rebuild may never add a placeholder the line did
   not already have.
2. ``_repair_multi_fraction_rows`` merges a baseline holding several fractions.
   A bar that the row window missed must still be resolved against every glyph
   of the problem, and a row that would still hide a bare bar is not applied.
3. ``_repair_placeholder_only_fraction_lines`` rebuilds a bar that owns a whole
   text line (piecewise braces, absolute-value rules), but only when its
   numerator and denominator lines are consumed completely.
4. ``reading_order_line_geometries`` re-linearizes the fragments of one visual
   row that the PDF content stream handed over out of order.  It applies only
   when the re-sort strictly lowers the placeholder count of the normalized
   text.
5. ``_repair_nested_bar_structures`` resolves a bar that geometrically contains
   other bars, innermost first, and tells a vinculum from a fraction bar by the
   ``√`` that abuts the bar's left edge.

Placeholders without that evidence stay untouched: they are classified
residuals, not noise to delete.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import pdf_math_geometry as geometry  # noqa: E402

PLACEHOLDER = "□"
FAILURES: list[str] = []


def _chars(
    text: str,
    *,
    left: float,
    center_y: float,
    size: float,
    width: float | None = None,
    height: float | None = None,
) -> list[dict[str, Any]]:
    """Lay a glyph run out left-to-right around a vertical centre."""
    width = size * 0.62 if width is None else width
    height = size * 1.2 if height is None else height
    top = center_y - height / 2.0
    bottom = center_y + height / 2.0
    out: list[dict[str, Any]] = []
    cursor = left
    for char in text:
        out.append(
            {
                "c": char,
                "bbox": [cursor, top, cursor + width, bottom],
                "size": size,
                "font": "HyhwpEQ",
            }
        )
        cursor += width
    return out


def _line(text: str, *runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Build one PDF line whose ``text`` may already carry a repaired formula."""
    chars = [char for run in runs for char in run]
    boxes = [char["bbox"] for char in chars] or [[0.0, 0.0, 0.0, 0.0]]
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[2] for box in boxes)
    bottom = max(box[3] for box in boxes)
    return {
        "text": text,
        "bbox_px": [left, top, right - left, bottom - top],
        "pdf_line_chars": chars,
        "pdf_line_spans": [],
    }


def _repair(lines: list[dict[str, Any]], choices: list[str] | None = None) -> str:
    stem = "\n".join(str(line["text"]) for line in lines)
    repaired, _choices, _counts = geometry.repair_problem_math_layout(
        stem, list(choices or []), lines
    )
    return repaired


def _check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [PASS] {name}")
        return
    FAILURES.append(f"{name}: {detail}")
    print(f"  [FAIL] {name}: {detail}")


def check_inline_script_keeps_restored_fraction() -> None:
    """A glyph rebuild must recover the bar, not flatten it back to a square.

    The line text already reads ``\\frac{1}{4}`` because an earlier linear pass
    resolved it, while the raw characters still hold only the bar and the
    denominator.  The numerator lives on its own text line above the bar.
    """
    lines = [
        _line(
            r"y=a2-\frac{1}{4}",
            _chars("y=a", left=100.0, center_y=364.0, size=14.0),
            _chars("2", left=126.0, center_y=355.0, size=9.0),
            _chars("-", left=132.0, center_y=364.0, size=14.0),
            _chars(PLACEHOLDER, left=141.0, center_y=364.5, size=13.9, width=18.0, height=29.0),
            _chars("4", left=145.0, center_y=384.0, size=14.0),
        ),
        _line("1", _chars("1", left=145.0, center_y=345.0, size=14.0)),
    ]
    repaired = _repair(lines)
    _check(
        "분수 막대가 위첨자 재구성에서 사각형으로 되돌아가지 않는다",
        r"\frac{1}{4}" in repaired and PLACEHOLDER not in repaired,
        repr(repaired),
    )
    _check(
        "같은 재구성이 위첨자 복원도 함께 유지한다",
        "a^{2}" in repaired,
        repr(repaired),
    )


def check_inline_script_rejects_placeholder_regression() -> None:
    """Without stacked evidence the rebuild is dropped, keeping the formula.

    A vinculum/accent bar has no numerator, so it can never become a fraction.
    Re-flattening the characters would replace ``\\frac{1}{4}`` with ``□4``;
    the guard has to keep the restored text instead.
    """
    lines = [
        _line(
            r"y2=\frac{1}{4}",
            _chars("y", left=100.0, center_y=364.0, size=14.0),
            _chars("2", left=110.0, center_y=355.0, size=9.0),
            _chars("=", left=117.0, center_y=364.0, size=14.0),
            _chars(PLACEHOLDER, left=127.0, center_y=364.5, size=13.9, width=18.0, height=29.0),
            _chars("4", left=131.0, center_y=384.0, size=14.0),
        ),
    ]
    repaired = _repair(lines)
    _check(
        "근거 없는 재구성은 기각되고 복원된 분수가 살아남는다",
        r"\frac{1}{4}" in repaired and PLACEHOLDER not in repaired,
        repr(repaired),
    )


def check_multi_fraction_row_resolves_out_of_window_bar() -> None:
    """A bar the row window skipped is retried against every glyph.

    Three bars share one baseline band, but only two of them are close enough
    in ``center_y`` to be grouped.  The third used to be flattened into the
    merged equation as a bare square.
    """
    lines = [
        _line("1", _chars("1", left=104.0, center_y=80.0, size=14.0)),
        _line("3", _chars("3", left=204.0, center_y=80.0, size=14.0)),
        _line("5", _chars("5", left=154.0, center_y=105.0, size=14.0)),
        _line(
            "=" + PLACEHOLDER + PLACEHOLDER + PLACEHOLDER,
            _chars("=", left=80.0, center_y=100.0, size=14.0),
            _chars(PLACEHOLDER, left=100.0, center_y=100.0, size=13.9, width=18.0, height=29.0),
            _chars(PLACEHOLDER, left=150.0, center_y=125.0, size=13.9, width=18.0, height=29.0),
            _chars(PLACEHOLDER, left=200.0, center_y=100.0, size=13.9, width=18.0, height=29.0),
        ),
        _line("2", _chars("2", left=104.0, center_y=120.0, size=14.0)),
        _line("4", _chars("4", left=204.0, center_y=120.0, size=14.0)),
        _line("6", _chars("6", left=154.0, center_y=145.0, size=14.0)),
    ]
    repaired = _repair(lines)
    _check(
        "행 병합이 사각형을 남기지 않는다",
        PLACEHOLDER not in repaired,
        repr(repaired),
    )
    for fraction in (r"\frac{1}{2}", r"\frac{3}{4}", r"\frac{5}{6}"):
        _check(
            f"행 병합이 {fraction}을 복원한다",
            fraction in repaired,
            repr(repaired),
        )


def check_bar_only_line_rebuilds_grouped_fraction() -> None:
    """A bar that owns a whole text line inside a piecewise group is rebuilt.

    The tall brace pushes the bar onto its own line; the numerator and the
    denominator each occupy a separate line that the bar consumes completely.
    """
    lines = [
        _line(
            "|" + PLACEHOLDER,
            _chars("|", left=396.0, center_y=430.5, size=30.0, width=16.0, height=100.0),
            _chars(
                PLACEHOLDER, left=414.0, center_y=430.5, size=30.2, width=87.0, height=63.0
            ),
        ),
        _line("|2x-1|", _chars("|2x-1|", left=416.0, center_y=396.0, size=14.0)),
        _line("12", _chars("12", left=440.0, center_y=464.0, size=14.0)),
        _line("의 값은? [3점]", _chars("의 값은? [3점]", left=100.0, center_y=520.0, size=14.0)),
    ]
    repaired = _repair(lines)
    _check(
        "묶음 안 단독 막대 줄이 분수로 복원된다",
        r"\frac{|2x-1|}{12}" in repaired and PLACEHOLDER not in repaired,
        repr(repaired),
    )
    _check(
        "분자/분모로 소비된 줄이 중복으로 남지 않는다",
        "\n|2x-1|" not in repaired and not repaired.endswith("|2x-1|"),
        repr(repaired),
    )


def check_accent_bar_only_line_is_preserved() -> None:
    """A bar with no numerator is an accent, not a fraction: leave it alone.

    The repo rule is that a residual square is a classified residual, never
    something to delete on a guess.
    """
    lines = [
        _line(
            PLACEHOLDER,
            _chars(
                PLACEHOLDER, left=414.0, center_y=430.5, size=30.2, width=87.0, height=63.0
            ),
        ),
        _line("AB", _chars("AB", left=420.0, center_y=464.0, size=14.0)),
        _line("의 길이는? [3점]", _chars("의 길이는? [3점]", left=100.0, center_y=520.0, size=14.0)),
    ]
    repaired = _repair(lines)
    _check(
        "분자 없는 악센트 막대는 삭제되지 않고 남는다",
        PLACEHOLDER in repaired or r"\overline{AB}" in repaired,
        repr(repaired),
    )
    _check(
        "악센트 막대의 밑줄 텍스트가 사라지지 않는다",
        "AB" in repaired,
        repr(repaired),
    )


def check_fraction_bar_evidence_rule() -> None:
    """Unit pin for the shared evidence rule used by every repair above."""
    lines = [
        _line("1", _chars("1", left=104.0, center_y=345.0, size=14.0)),
        _line(
            PLACEHOLDER + "5",
            _chars(PLACEHOLDER, left=100.0, center_y=364.5, size=13.9, width=18.0, height=29.0),
            _chars("5", left=104.0, center_y=384.0, size=14.0),
        ),
        _line(
            PLACEHOLDER + "AB",
            _chars(PLACEHOLDER, left=300.0, center_y=364.5, size=13.9, width=18.0, height=29.0),
            _chars("AB", left=302.0, center_y=384.0, size=14.0),
        ),
    ]
    glyphs = geometry._glyphs(lines)
    bars = [glyph for glyph in glyphs if glyph.text == PLACEHOLDER]
    _check("픽스처가 막대 2개를 만든다", len(bars) == 2, str(len(bars)))
    if len(bars) != 2:
        return
    stacked = geometry._fraction_from_bar(glyphs, bars[0])
    accent = geometry._fraction_from_bar(glyphs, bars[1])
    _check(
        "위/아래 정렬 글리프가 있으면 분수로 인정한다",
        stacked is not None and stacked[0] == r"\frac{1}{5}",
        repr(stacked),
    )
    _check(
        "아래쪽만 있는 막대는 분수로 인정하지 않는다",
        accent is None,
        repr(accent),
    )
    working, donors, resolved = geometry._resolve_fraction_bars(
        geometry._line_glyphs(glyphs, 1), glyphs
    )
    _check("_resolve_fraction_bars가 1건만 해결한다", resolved == 1, str(resolved))
    _check(
        "_resolve_fraction_bars가 분자 줄을 기증자로 보고한다",
        donors == {0},
        repr(donors),
    )
    _check(
        "해결된 막대가 \\frac 토큰으로 대체된다",
        any(glyph.text == r"\frac{1}{5}" for glyph in working)
        and all(glyph.text != PLACEHOLDER for glyph in working),
        repr([glyph.text for glyph in working]),
    )


ACCENT = "⃗"


def _accent_row_lines() -> list[dict[str, Any]]:
    """One equation row whose fragments arrive out of reading order.

    Three fragments share a baseline at ``center_y=100``.  Each accent bar is
    drawn over the letters of the fragment to its right, so the base name the
    accent needs is the fragment that follows it *visually*, not in the stream.
    The stream hands them over as ``left=110 -> left=150 -> left=100``.
    """
    fragment_a = _line(
        "(" + PLACEHOLDER + ACCENT,
        _chars("(", left=100.0, center_y=100.0, size=14.0, width=6.0),
        _chars(PLACEHOLDER, left=110.0, center_y=100.0, size=24.0, width=24.0, height=34.0),
        _chars(ACCENT, left=128.0, center_y=94.0, size=9.0, width=8.0),
    )
    fragment_b = _line(
        "AB)+" + PLACEHOLDER + ACCENT,
        _chars("AB)", left=110.0, center_y=100.0, size=14.0, width=9.0),
        _chars("+", left=137.0, center_y=100.0, size=14.0, width=9.0),
        _chars(PLACEHOLDER, left=150.0, center_y=100.0, size=24.0, width=24.0, height=34.0),
        _chars(ACCENT, left=168.0, center_y=94.0, size=9.0, width=8.0),
    )
    fragment_c = _line("CD)", _chars("CD)", left=150.0, center_y=100.0, size=14.0, width=9.0))
    tail = _line("의 값은? [3점]", _chars("의 값은? [3점]", left=100.0, center_y=160.0, size=14.0))
    return [fragment_b, fragment_c, fragment_a, tail]


def check_reading_order_relinearizes_one_row() -> None:
    """Same-baseline fragments are re-sorted by x so accents find their base."""
    lines = _accent_row_lines()
    stream_text = geometry.line_geometry_source_text(lines)
    _check(
        "픽스처가 스트림 순서에서 악센트를 해결하지 못한다",
        PLACEHOLDER in stream_text,
        repr(stream_text),
    )
    reordered = geometry.reading_order_line_geometries(lines)
    _check("읽기 순서 재정렬이 적용된다", reordered is not None, repr(reordered))
    if reordered is None:
        return
    _check(
        "재정렬 결과가 x 좌표 순서를 따른다",
        [str(line["text"]) for line in reordered]
        == [
            "(" + PLACEHOLDER + ACCENT,
            "AB)+" + PLACEHOLDER + ACCENT,
            "CD)",
            "의 값은? [3점]",
        ],
        repr([str(line["text"]) for line in reordered]),
    )
    reordered_text = geometry.line_geometry_source_text(reordered)
    _check(
        "재정렬 후 두 벡터 악센트가 모두 복원된다",
        r"\vec{AB}" in reordered_text
        and r"\vec{CD}" in reordered_text
        and PLACEHOLDER not in reordered_text,
        repr(reordered_text),
    )
    _check(
        "이미 읽기 순서인 입력은 다시 정렬하지 않는다",
        geometry.reading_order_line_geometries(reordered) is None,
        "재정렬이 반복 적용됨",
    )


def check_reading_order_needs_placeholder_evidence() -> None:
    """A re-sort that resolves nothing is not evidence and is not applied."""
    lines = [
        _line("CD)", _chars("CD)", left=150.0, center_y=100.0, size=14.0, width=9.0)),
        _line("(AB)+", _chars("(AB)+", left=100.0, center_y=100.0, size=14.0, width=9.0)),
        _line("의 값은? [3점]", _chars("의 값은? [3점]", left=100.0, center_y=160.0, size=14.0)),
    ]
    _check(
        "사각형을 줄이지 못하는 재정렬은 기각된다",
        geometry.reading_order_line_geometries(lines) is None,
        "근거 없는 재정렬이 적용됨",
    )


def _nested_radical_fraction_lines() -> list[dict[str, Any]]:
    """``\\frac{n}{\\sqrt{x+1}-\\sqrt{y+2}}``: two vinculums inside a fraction bar.

    The outer bar (220x100) fully contains both radical vinculums (70x75 and
    60x71); every rule is the same private-use glyph.
    """
    return [
        _line(
            "f=" + PLACEHOLDER,
            _chars("f=", left=60.0, center_y=50.0, size=14.0),
            _chars(PLACEHOLDER, left=100.0, center_y=50.0, size=48.0, width=220.0, height=100.0),
        ),
        _line("n", _chars("n", left=200.0, center_y=30.0, size=14.0)),
        _line(
            "√",
            _chars("√", left=122.0, center_y=80.0, size=14.0, width=18.0),
            _chars(PLACEHOLDER, left=140.0, center_y=57.5, size=36.0, width=70.0, height=75.0),
        ),
        _line(
            "x+1-√",
            _chars("x+1", left=142.0, center_y=80.0, size=14.0, width=20.0),
            _chars("-", left=212.0, center_y=80.0, size=14.0, width=16.0),
            _chars("√", left=232.0, center_y=80.0, size=14.0, width=18.0),
            _chars(PLACEHOLDER, left=250.0, center_y=59.5, size=34.0, width=60.0, height=71.0),
        ),
        _line("y+2", _chars("y+2", left=252.0, center_y=80.0, size=14.0, width=18.0)),
        _line("의 값은? [3점]", _chars("의 값은? [3점]", left=60.0, center_y=150.0, size=14.0)),
    ]


def check_nested_bars_rebuild_radicals_inside_fraction() -> None:
    """Bars are resolved innermost first, so the nesting cannot scramble."""
    lines = _nested_radical_fraction_lines()
    repaired = _repair(lines)
    _check(
        "중첩 막대가 분수 안 두 근호로 복원된다",
        r"\frac{n}{\sqrt{x+1}-\sqrt{y+2}}" in repaired,
        repr(repaired),
    )
    _check(
        "중첩 막대 복원이 사각형을 남기지 않는다",
        PLACEHOLDER not in repaired,
        repr(repaired),
    )
    _check(
        "분수 바깥 접두 텍스트가 사라지지 않는다",
        "f=" in repaired and "의 값은? [3점]" in repaired,
        repr(repaired),
    )


def check_nested_bar_without_radical_evidence_is_preserved() -> None:
    """An inner bar with one operand band is not a fraction and not a radical.

    Nothing about the outer bar may be rewritten on that guess: the square is a
    classified residual.
    """
    lines = [
        _line(
            "f=" + PLACEHOLDER,
            _chars("f=", left=60.0, center_y=50.0, size=14.0),
            _chars(PLACEHOLDER, left=100.0, center_y=50.0, size=48.0, width=220.0, height=100.0),
        ),
        _line("n", _chars("n", left=280.0, center_y=30.0, size=14.0)),
        _line(
            PLACEHOLDER,
            _chars(PLACEHOLDER, left=140.0, center_y=57.5, size=36.0, width=70.0, height=75.0),
        ),
        _line("AB", _chars("AB", left=145.0, center_y=80.0, size=14.0)),
        _line("의 값은? [3점]", _chars("의 값은? [3점]", left=60.0, center_y=150.0, size=14.0)),
    ]
    repaired = _repair(lines)
    _check(
        "근거 없는 중첩 막대는 근호를 지어내지 않는다",
        "\\sqrt" not in repaired,
        repr(repaired),
    )
    _check(
        "해결 불가한 중첩 막대의 사각형이 보존된다",
        PLACEHOLDER in repaired,
        repr(repaired),
    )
    _check(
        "중첩 막대 아래 텍스트가 사라지지 않는다",
        "AB" in repaired and "n" in repaired,
        repr(repaired),
    )


def check_shared_mark_predicate() -> None:
    """The ``√``-abuts-the-bar predicate shared with ``app.importers``.

    ``app.importers`` uses the wide default window to tell a short accent bar
    from a vinculum; the nested-bar analysis narrows it so a 220px-wide outer
    fraction bar cannot claim a radical sign 26px away from its left edge.
    """
    lines = _nested_radical_fraction_lines()
    glyphs = geometry.line_geometry_glyphs(lines)
    bars = sorted(
        (glyph for glyph in glyphs if glyph.text == PLACEHOLDER),
        key=lambda glyph: glyph.width * glyph.height,
        reverse=True,
    )
    _check("픽스처가 중첩 막대 3개를 만든다", len(bars) == 3, str(len(bars)))
    if len(bars) != 3:
        return
    outer, inner = bars[0], bars[1]
    _check(
        "바깥 막대가 안쪽 막대를 포함한다",
        geometry._bar_contains(outer, inner) and not geometry._bar_contains(inner, outer),
        repr((outer.left, outer.right, inner.left, inner.right)),
    )
    _check(
        "근호가 안쪽 막대 왼쪽 모서리에 붙어 있다",
        geometry._mark_glyph_near_bar(
            glyphs,
            bar_rect=(inner.left, inner.top, inner.right, inner.bottom),
            marks="√",
            left_margin=9.0,
            right_margin=9.0,
            vertical_margin=inner.height / 2.0,
        )
        is not None,
        "안쪽 막대의 근호를 찾지 못함",
    )
    _check(
        "넓은 바깥 막대는 안쪽 근호를 자기 것으로 삼지 않는다",
        geometry._mark_glyph_near_bar(
            glyphs,
            bar_rect=(outer.left, outer.top, outer.right, outer.bottom),
            marks="√",
            left_margin=12.0,
            right_margin=12.0,
            vertical_margin=outer.height / 2.0,
        )
        is None,
        "바깥 막대가 근호를 잘못 가져감",
    )


def check_fallback_never_drops_restored_structure() -> None:
    """An unmapped rebuild may not overwrite a line holding a restored formula.

    When the stem no longer matches the PDF lines one for one, the standalone
    fraction repair falls back to "the most formula-like line".  That line is
    picked by keyword score, not by geometry, so it can be a completely
    different equation — here a vector row that would lose both accents.
    """
    lines = [
        _line("q", _chars("q", left=300.0, center_y=112.0, size=14.0)),
        _line(
            "AB=" + PLACEHOLDER + "p",
            _chars("AB=", left=250.0, center_y=130.0, size=14.0, width=15.0),
            _chars(PLACEHOLDER, left=300.0, center_y=130.0, size=14.0, width=20.0, height=30.0),
            _chars("p", left=302.0, center_y=148.0, size=14.0),
        ),
        _line("의 값은? [3점]", _chars("의 값은? [3점]", left=100.0, center_y=200.0, size=14.0)),
    ]
    stem = "\n".join(
        [
            r"(\vec{AB})=2|\vec{CD}+" + PLACEHOLDER + ACCENT,
            r"AB=\frac{p}{q}",
            "의 값은? [3점]",
        ]
    )
    repaired, _choices, _counts = geometry.repair_problem_math_layout(stem, [], lines)
    _check(
        "매핑 없는 대체가 복원된 벡터 줄을 덮어쓰지 않는다",
        r"\vec{AB}" in repaired and r"\vec{CD}" in repaired,
        repr(repaired),
    )
    _check(
        "덮어쓰기 차단이 원래 분수 줄도 보존한다",
        r"\frac{p}{q}" in repaired,
        repr(repaired),
    )
    _check(
        "복원 구조 손실 판정이 방향을 구분한다",
        geometry._drops_restored_structure(r"(\vec{AB})=2", r"$AB=\frac{q}{p}$")
        and not geometry._drops_restored_structure(r"x=" + PLACEHOLDER + "5", r"$x=\frac{1}{5}$")
        and not geometry._drops_restored_structure(r"\frac{1}{2}+\vec{a}", r"\frac{1}{2}+\vec{a}=3"),
        "구조 손실 판정 오류",
    )


def _classify(lines: list[dict[str, Any]], index: int = 0) -> str:
    glyphs = geometry.line_geometry_glyphs(lines)
    bars = [glyph for glyph in glyphs if glyph.text == PLACEHOLDER]
    bars.sort(key=lambda glyph: glyph.width * glyph.height, reverse=True)
    if not bars:
        return ""
    return geometry.classify_placeholder_glyph(glyphs, bars[index])


def check_placeholder_classification_uses_own_geometry() -> None:
    """A residual square is named by its own glyph, never by nearby LaTeX.

    Scanning the surrounding text calls a nested root a vector because an accent
    happens to sit on the same line, and calls an accent ``cases_or_grouping``
    because a brace is nearby.  Each shape below is separated only by what
    touches the bar itself.
    """
    nested = _nested_radical_fraction_lines()
    _check(
        "넓은 바깥 막대는 분수로 분류된다(근호 아님)",
        _classify(nested, 0) == "fraction",
        _classify(nested, 0),
    )
    _check(
        "근호가 붙은 안쪽 막대는 root로 분류된다",
        _classify(nested, 1) == "root",
        _classify(nested, 1),
    )

    stacked = [
        _line("1", _chars("1", left=104.0, center_y=345.0, size=14.0)),
        _line(
            PLACEHOLDER + "5",
            _chars(PLACEHOLDER, left=100.0, center_y=364.5, size=13.9, width=18.0, height=29.0),
            _chars("5", left=104.0, center_y=384.0, size=14.0),
        ),
    ]
    _check("위아래 피연산자가 있는 막대는 fraction", _classify(stacked) == "fraction", _classify(stacked))

    overline = [
        _line(
            PLACEHOLDER,
            _chars(PLACEHOLDER, left=414.0, center_y=430.5, size=30.2, width=87.0, height=63.0),
        ),
        _line("AB", _chars("AB", left=420.0, center_y=464.0, size=14.0)),
    ]
    _check(
        "아래쪽만 있는 막대는 overline_or_accent",
        _classify(overline) == "overline_or_accent",
        _classify(overline),
    )

    vector = [
        _line(
            PLACEHOLDER + ACCENT,
            _chars(PLACEHOLDER, left=414.0, center_y=430.5, size=30.2, width=87.0, height=63.0),
            _chars(ACCENT, left=493.0, center_y=430.0, size=9.0, width=10.0),
        ),
        _line("AB", _chars("AB", left=420.0, center_y=464.0, size=14.0)),
    ]
    _check(
        "오른쪽 끝 화살표가 붙은 막대는 vector_or_arrow",
        _classify(vector) == "vector_or_arrow",
        _classify(vector),
    )

    empty_box = [
        _line(
            PLACEHOLDER,
            _chars(PLACEHOLDER, left=414.0, center_y=430.5, size=24.0, width=26.0, height=26.0),
        ),
        _line("의 값은? [3점]", _chars("의 값은? [3점]", left=100.0, center_y=560.0, size=14.0)),
    ]
    _check(
        "피연산자 없는 정사각형 상자는 answer_box",
        _classify(empty_box) == "answer_box",
        _classify(empty_box),
    )


def main() -> int:
    print("PDF 수식 구조 복원 회귀 핀")
    check_fraction_bar_evidence_rule()
    check_inline_script_keeps_restored_fraction()
    check_inline_script_rejects_placeholder_regression()
    check_multi_fraction_row_resolves_out_of_window_bar()
    check_bar_only_line_rebuilds_grouped_fraction()
    check_accent_bar_only_line_is_preserved()
    check_reading_order_relinearizes_one_row()
    check_reading_order_needs_placeholder_evidence()
    check_shared_mark_predicate()
    check_nested_bars_rebuild_radicals_inside_fraction()
    check_nested_bar_without_radical_evidence_is_preserved()
    check_fallback_never_drops_restored_structure()
    check_placeholder_classification_uses_own_geometry()
    if FAILURES:
        print(f"\nMATH_STRUCTURE_REPAIRS_FAIL — {len(FAILURES)}건")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("\nMATH_STRUCTURE_REPAIRS_OK — 기하 근거 기반 수식 구조 복원 유지")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
