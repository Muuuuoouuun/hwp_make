"""인수 테스트: 혼합문서 페이지단위 폴백 — 병목 #4.

마커 있는 born-digital 페이지 + 마커 없는(스캔형) 페이지가 섞인 PDF에서, 마커 없는
페이지의 콘텐츠가 소실되지 않고 result에 병합되는지 확인한다.

SKIP-until-wired: 현재는 미배선(빈 페이지가 empty_page_numbers에 판정만 됨)이라 SKIP(2)로
빠지고, 코덱스가 pipeline._page_fallback_problem을 배선하면 자동으로 PASS로 전환된다.
recognition 무기능 케이스(문항0 순수 스캔)는 여전히 레거시 소유여야 하므로 별도 확인.

종료코드 0=PASS(배선됨) / 2=SKIP(미배선) / 1=FAIL(회귀/예상외).
"""
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

try:
    import fitz  # PyMuPDF
except Exception:
    print("SKIP: PyMuPDF(fitz) 미설치")
    raise SystemExit(2)

from app.recognition.pipeline import recognize_pdf  # noqa: E402


def make_mixed_pdf() -> bytes:
    doc = fitz.open()
    # 페이지1: 문항번호 마커 있는 born-digital
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 100), "1. First problem statement on page one.", fontsize=12)
    p1.insert_text((90, 122), "A) alpha", fontsize=11)
    p1.insert_text((90, 140), "B) beta", fontsize=11)
    # 페이지2: 마커 없음(스캔형 대체) — 번호로 시작하지 않는 본문
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 100), "This page has no leading problem-number marker at all.", fontsize=12)
    p2.insert_text((72, 130), "It represents a scanned or non-standard page whose content must survive.", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def main() -> int:
    res = recognize_pdf(make_mixed_pdf(), filename="mixed_test.pdf")

    p1 = [p for p in res.problems if p.page_number == 1]
    p2 = [p for p in res.problems if p.page_number == 2]

    # 기준선: 페이지1은 반드시 인식돼야(회귀 감지)
    if not res.found or not p1:
        print(f"  [FAIL] 페이지1 인식 실패 — found={res.found}, page1문항={len(p1)}")
        print("MIXED_PAGE_FALLBACK_FAIL (인식 회귀)")
        return 1

    if p2:
        print(f"  [PASS] 페이지2 콘텐츠 병합됨(문항 {len(p2)}개) — 페이지폴백 배선 확인")
        print("MIXED_PAGE_FALLBACK_OK")
        return 0

    if 2 in (res.empty_page_numbers or []):
        print("  [SKIP] 페이지2가 empty_page_numbers에만 기록됨 — 페이지폴백 미배선(코덱스 적용 대기)")
        print("       배선 후(pipeline._page_fallback_problem) 이 테스트는 자동 PASS로 전환됩니다.")
        return 2

    print(f"  [FAIL] 페이지2가 사라졌고 empty_page_numbers에도 없음: {res.empty_page_numbers}")
    print("MIXED_PAGE_FALLBACK_FAIL (콘텐츠 소실)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
