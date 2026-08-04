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


def main() -> int:
    print("PDF 수식 구조 복원 회귀 핀")
    check_fraction_bar_evidence_rule()
    check_inline_script_keeps_restored_fraction()
    check_inline_script_rejects_placeholder_regression()
    check_multi_fraction_row_resolves_out_of_window_bar()
    check_bar_only_line_rebuilds_grouped_fraction()
    check_accent_bar_only_line_is_preserved()
    if FAILURES:
        print(f"\nMATH_STRUCTURE_REPAIRS_FAIL — {len(FAILURES)}건")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("\nMATH_STRUCTURE_REPAIRS_OK — 기하 근거 기반 수식 구조 복원 유지")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
