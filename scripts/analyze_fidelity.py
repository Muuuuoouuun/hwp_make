"""전 과목 충실도 감사 — 실물 평가원 PDF를 recognize_pdf로 돌려 제품 B 핵심지표를 정량화.

지표(과목별): 문항수, 편집가능(text_reliable) 비율, 이미지폴백 수, 페이지수,
마커없는 페이지수, E0xx 커버리지. 편집성 비율이 제품 B("편집 가능")의 헤드라인 KPI.

분석 도구(테스트 아님, run_all_verify 미편입). 사용:
  python scripts/analyze_fidelity.py            # data/uploads 전체
  python scripts/analyze_fidelity.py a.pdf b.pdf
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.recognition.pipeline import recognize_pdf  # noqa: E402

# 실제 수능/모의평가 문항수(대략) — 과분할 감지용 참고치.
EXPECTED = {
    "국어": 45, "화작": 45, "언매": 45,
    "수학": 30, "영어": 45,
    "물리": 20, "화학": 20, "생명": 20, "지구과학": 20, "한국사": 20,
}


def expected_for(name: str) -> int | None:
    for key, val in EXPECTED.items():
        if key in name:
            return val
    return None


def discover() -> list[Path]:
    if len(sys.argv) > 1:
        return [Path(a).resolve() for a in sys.argv[1:]]
    up = ROOT / "data" / "uploads"
    return sorted(up.glob("*.pdf")) if up.is_dir() else []


def main() -> int:
    pdfs = discover()
    if not pdfs:
        print("PDF 없음.")
        return 2

    print(f"{'과목/파일':<34} {'문항':>4} {'예상':>4} {'편집':>4} {'편집%':>6} {'이미지':>5} {'쪽':>3} {'마커0쪽':>6}")
    print("-" * 78)
    agg = {"total": 0, "editable": 0, "image": 0}
    for pdf in pdfs:
        try:
            res = recognize_pdf(pdf.read_bytes(), filename=pdf.name)
        except Exception as exc:
            print(f"{pdf.name[:33]:<34} ERROR {type(exc).__name__}: {exc}")
            continue
        total = len(res.problems)
        editable = sum(1 for p in res.problems if getattr(p, "text_reliable", False))
        image = total - editable
        pages = getattr(res, "page_count", 0)
        empty = len(getattr(res, "empty_page_numbers", []) or [])
        exp = expected_for(pdf.name)
        pct = f"{100*editable/total:.0f}%" if total else "-"
        flag = ""
        if exp and total > exp * 1.3:
            flag = " ⚠과분할"
        print(f"{pdf.name[:33]:<34} {total:>4} {str(exp or '-'):>4} {editable:>4} {pct:>6} {image:>5} {pages:>3} {empty:>6}{flag}")
        agg["total"] += total
        agg["editable"] += editable
        agg["image"] += image

    print("-" * 78)
    t = agg["total"]
    if t:
        print(f"{'합계':<34} {t:>4} {'':>4} {agg['editable']:>4} {100*agg['editable']/t:>5.0f}% {agg['image']:>5}")
        print(f"\n제품 B 편집성 KPI: 전체 문항 {t}개 중 {agg['editable']}개({100*agg['editable']/t:.0f}%) 편집 가능 텍스트, {agg['image']}개 이미지 폴백.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
