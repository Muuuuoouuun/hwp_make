"""회귀핀: PDF 문항 마커 vs 번호형 선지('1) 2) 3)') 과분할 방지.

최근 app/recognition/pdf_segment.py 의 `_filter_choice_like_markers` 로 고친 버그를
고정한다 — 문항번호 정규식 `^([1-9][0-9]?)[.)]` 이 `)` 를 허용해 '1) 2) 3) 4) 5)' 형
번호 선지를 새 문항 시작으로 오인, 한 문항을 여러 pseudo-문항으로 쪼개던 과분할.

설계:
- pdf_segment 를 **수정 없이 import 만** 하므로 코덱스 핫존과 병합충돌 0.
- 공개 API `segment_pdf` 의 관측 가능한 출력(ProblemUnit 개수/번호)만 검증 —
  내부 리팩터에 강건(behavioral pin).
- fitz(PyMuPDF)로 합성 PDF 생성 — 개인경로/샘플 무의존, 어디서나 자립 실행.

종료코드: 모든 케이스 통과 0, 하나라도 실패 1, fitz 미설치 0(SKIP).
"""
from __future__ import annotations

import sys
from pathlib import Path

# 콘솔 코드페이지(cp949 등)와 무관하게 UTF-8로 출력 — CI/다양한 환경에서 UnicodeEncodeError 방지.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    print("SKIP: PyMuPDF(fitz) 미설치 — 마커 회귀핀 건너뜀 (종료 0)")
    raise SystemExit(0)

from app.recognition.pdf_segment import segment_pdf


def make_pdf(lines: list[tuple[float, float, str]]) -> bytes:
    """(x_pt, y_pt, text) 라인들로 A4 1페이지 born-digital PDF 를 만든다."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def problem_numbers(pdf_bytes: bytes) -> list[int]:
    numbers: list[int] = []
    for page in segment_pdf(pdf_bytes):
        for unit in page.problems:
            meta = unit.metadata or {}
            numbers.append(int(meta.get("problem_number") or meta.get("pdf_problem_number") or 0))
    return numbers


# --- 케이스 정의 -------------------------------------------------------------
# 각 케이스: (이름, 라인들, 기대 문항번호 리스트)

CASES: list[tuple[str, list[tuple[float, float, str]], list[int]]] = [
    (
        "번호형 선지가 문항을 쪼개면 안 된다(핵심 회귀)",
        [
            (72, 100, "1. First problem statement here."),
            (90, 122, "1) alpha"),
            (90, 140, "2) beta"),
            (90, 158, "3) gamma"),
            (72, 220, "2. Second problem statement here."),
            (90, 242, "1) yes"),
            (90, 260, "2) no"),
            (90, 278, "3) maybe"),
        ],
        [1, 2],
    ),
    (
        "선지 없는 순수 문항번호는 정상 분리",
        [
            (72, 100, "1. Alpha problem body."),
            (72, 170, "2. Beta problem body."),
            (72, 240, "3. Gamma problem body."),
        ],
        [1, 2, 3],
    ),
    (
        "한 문항 아래 1)~5) 다섯 선지 → 문항 1개",
        [
            (72, 100, "1. Only one problem with five numeric choices."),
            (90, 122, "1) a"),
            (90, 140, "2) b"),
            (90, 158, "3) c"),
            (90, 176, "4) d"),
            (90, 194, "5) e"),
        ],
        [1],
    ),
]


def main() -> int:
    failures = 0
    for name, lines, expected in CASES:
        got = problem_numbers(make_pdf(lines))
        ok = got == expected
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}: expected={expected} got={got}")
        if not ok:
            failures += 1
    if failures:
        print(f"MARKER_REGRESSION_FAIL ({failures} case(s)) — 마커 과분할 회귀 감지")
        return 1
    print("MARKER_REGRESSION_OK — 번호형 선지 과분할 방지 유지")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
