"""회귀핀: 후행 HWP 출처 마커와 dingbat 원문자 선택지 분리."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import importers  # noqa: E402
from app import importers_hwp_ir as hwp_ir  # noqa: E402


STREAM = [
    ("text", "$x+1$의 값은? [2점]"),
    ("text", "➀ 1\t➁ 2\t➂ 3\t➃ 4\t➄ 5"),
    ("text", "[26년 06월 고1 전국 1번]"),
    ("text", "[출제의도] 첫 번째 의도"),
    ("text", "$x+2$의 값은? [3점]"),
    ("image", "uploads/q2.png"),
    ("table", [["조건", "$x>0$"]]),
    ("text", "❶ 6\t❷ 7\t❸ 8\t❹ 9\t❺ 10"),
    ("text", "[26년 06월 고1 전국 2번]"),
    ("text", "[출제의도] 두 번째 의도"),
    ("text", "$x+3$의 값을 구하시오. [4점]"),
    ("text", "[26년 06월 고1 전국 3번]"),
    ("text", "[출제의도] 세 번째 의도"),
    ("text", "정답 및 해설"),
    ("text", "이 줄은 문항에 들어가면 안 된다."),
]


def main() -> int:
    original = hwp_ir._ordered_stream
    hwp_ir._ordered_stream = lambda payload, filename, save_image: list(STREAM)
    try:
        problems = hwp_ir.hwp_to_problems(
            b"fixture",
            "fixture.hwp",
            lambda name, payload: name,
            importers._split_inline_circled_choices,
            chunk_paragraphs=importers._paragraphs_to_chunks,
            split_stem_choices=importers._split_stem_and_choices,
        )
    finally:
        hwp_ir._ordered_stream = original

    failures: list[str] = []
    mixed_label = hwp_ir._wrap_eqn("a = box{~~(가)~~}")
    math_segments = mixed_label.split("$")[1::2]
    if "(가)" not in mixed_label or any("가" in segment for segment in math_segments):
        failures.append(f"Hangul label was not separated from equation script: {mixed_label}")
    if not problems or len(problems) != 3:
        failures.append(f"expected 3 problems, got {0 if not problems else len(problems)}")
    else:
        if [p.get("number") for p in problems] != ["1", "2", "3"]:
            failures.append(f"number sequence mismatch: {[p.get('number') for p in problems]}")
        if [len(p.get("choices") or []) for p in problems] != [5, 5, 0]:
            failures.append(f"choice split mismatch: {[len(p.get('choices') or []) for p in problems]}")
        if [p.get("score") for p in problems] != ["2", "3", "4"]:
            failures.append(f"score mismatch: {[p.get('score') for p in problems]}")
        if [p.get("intent") for p in problems] != ["첫 번째 의도", "두 번째 의도", "세 번째 의도"]:
            failures.append("intent metadata mismatch")
        if "[2점]" in str(problems[0].get("stem") or ""):
            failures.append("inline score leaked into stem")
        if problems[1].get("image_paths") != ["uploads/q2.png"]:
            failures.append(f"image attachment mismatch: {problems[1].get('image_paths')}")
        if len(problems[1].get("tables") or []) != 1:
            failures.append("table attachment mismatch")
        if "정답" in str(problems[-1].get("stem") or ""):
            failures.append("answer section leaked into last problem")
        if hwp_ir._marker_parts(str(problems[0].get("unit") or "")) != (
            "26년 06월 고1 전국",
            1,
            1,
        ):
            failures.append(f"optional 번 marker parse mismatch: {problems[0].get('unit')}")

    if failures:
        for failure in failures:
            print(f"  [FAIL] {failure}")
        print("HWP_TRAILING_MARKER_FAIL")
        return 1
    print("  [PASS] 후행 출처 3개, 출제의도 3개, 5지선다 2개, 단답형 1개")
    print("HWP_TRAILING_MARKER_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
