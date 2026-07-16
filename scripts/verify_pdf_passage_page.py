"""회귀핀: 번호 마커 없는 공유 지문 페이지를 다음 실제 문항에 연결."""
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
    import fitz
except Exception:
    print("SKIP: PyMuPDF(fitz) 미설치")
    raise SystemExit(2)

from app.recognition.pipeline import recognize_pdf  # noqa: E402


def make_pdf() -> bytes:
    doc = fitz.open()
    passage = doc.new_page(width=595, height=842)
    passage.insert_text((72, 70), "Korean Area 1", fontsize=10)
    passage.insert_text((72, 130), "[39~42] Read the following passage and answer.", fontsize=12)
    passage.insert_text((72, 165), "This editable passage continues for several lines.", fontsize=11)
    passage.insert_text((72, 190), "Its text must be linked without creating question zero.", fontsize=11)

    questions = doc.new_page(width=595, height=842)
    questions.insert_text((72, 100), "39. First question for the shared passage.", fontsize=12)
    questions.insert_text((72, 220), "40. Second question for the shared passage.", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def main() -> int:
    result = recognize_pdf(make_pdf(), filename="passage_fixture.pdf")
    failures: list[str] = []
    numbers = [problem.number for problem in result.problems]
    if numbers != [39, 40]:
        failures.append(f"expected [39, 40], got {numbers}")
    first = result.problems[0] if result.problems else None
    if first is None or first.shared_passage_range != (39, 42):
        failures.append(f"passage range mismatch: {getattr(first, 'shared_passage_range', None)}")
    if first is None or "editable passage" not in first.shared_passage_text:
        failures.append("passage text was not attached to question 39")
    if result.empty_page_numbers:
        failures.append(f"passage page misrouted as empty: {result.empty_page_numbers}")
    if result.passage_page_numbers != [1]:
        failures.append(f"passage page inventory mismatch: {result.passage_page_numbers}")

    if failures:
        for failure in failures:
            print(f"  [FAIL] {failure}")
        print("PDF_PASSAGE_PAGE_FAIL")
        return 1
    print("  [PASS] 공유 지문 1쪽을 39번에 연결, 실제 문항 inventory 2개 유지")
    print("PDF_PASSAGE_PAGE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
