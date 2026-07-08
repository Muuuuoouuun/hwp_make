"""회귀/인수 테스트: 시험명 파서(app/exam_header.py) — 병목 #6 마스트헤드 동적화.

실제 평가원/교육청 헤더 문구·파일명 → 기대 마스트헤드 매핑을 고정한다. 개인 샘플
무의존(문자열 케이스만)이라 어디서나 자립 실행. scripts/run_all_verify.py 자동 편입.

종료코드 0=통과, 1=실패.
"""
from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.exam_header import masthead_from_text  # noqa: E402
from app import hwpx_writer_v2  # noqa: E402

# (입력 헤더/파일명, 기대 마스트헤드). ""=파싱 불충분→템플릿 폴백 기대.
CASES = [
    (
        "2025학년도 대학수학능력시험 6월 모의평가 문제지 국어 영역",
        "2025학년도 대학수학능력시험 6월 모의평가 문제지",
    ),
    (
        "2025학년도 대학수학능력시험 문제지 수학 영역",
        "2025학년도 대학수학능력시험 문제지",
    ),
    (
        "2024학년도 3월 고3 전국연합학력평가 국어 영역",
        "2024학년도 3월 고3 전국연합학력평가 문제지",
    ),
    (
        "2024년 5월 교육청 모의고사 수학",
        "2024학년도 5월 모의고사 문제지",
    ),
    # 연도 없음 → 파싱 불충분 → 빈 문자열(템플릿 폴백)
    ("01.3월_고3_국어_언어와매체", ""),
    # 순수 시험지 아님 → 빈 문자열
    ("아무 텍스트나 여기 있음", ""),
]


def main() -> int:
    failures = 0
    for source, expected in CASES:
        got = masthead_from_text(source)
        ok = got == expected
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {source!r}\n         → {got!r} (기대 {expected!r})")
        if not ok:
            failures += 1

    dynamic_title = "2024학년도 3월 고3 전국연합학력평가 문제지"
    with tempfile.TemporaryDirectory(prefix="hwp_make_masthead_") as tmp:
        out = Path(tmp) / "masthead.hwpx"
        hwpx_writer_v2.write_hwpx(
            out,
            dynamic_title,
            [{"number": "1", "stem": "1. 제목 배선 확인", "choices": []}],
            template_key="kice_math",
            native_math=True,
        )
        with zipfile.ZipFile(out) as archive:
            section = archive.read("Contents/section0.xml").decode("utf-8", errors="replace")
        writer_ok = dynamic_title in section and "2025학년도 대학수학능력시험 문제지" not in section
        status = "PASS" if writer_ok else "FAIL"
        print(f"  [{status}] writer 동적 마스트헤드 우선 적용")
        if not writer_ok:
            failures += 1
    if failures:
        print(f"EXAM_MASTHEAD_FAIL ({failures}건)")
        return 1
    print("EXAM_MASTHEAD_OK — 시험명 파싱 동적 마스트헤드 유지")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
