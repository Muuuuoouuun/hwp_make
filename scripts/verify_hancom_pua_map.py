"""회귀/검증: HyhwpEQ E0xx→유니코드 매핑표(app/hancom_pua_map.py) — 병목 #2.

핵심 매핑(문자/숫자/연산자/그리스)을 고정하고, data/uploads에 실물 평가원 PDF가 있으면
E0xx 글리프 커버리지(%)를 측정해 '이제 수식 텍스트가 복원 가능한가'를 실증한다.
매핑 assert는 PDF 무의존(항상 실행), 커버리지는 informational(PDF 없으면 생략).

종료코드 0=통과, 1=실패.
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

from app.hancom_pua_map import (  # noqa: E402
    HANCOM_PUA_MAP,
    is_hancom_eq_font,
    recover_pua_char,
)

_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}{('  · ' + detail) if detail else ''}")
    if not cond:
        _failures.append(name)


def main() -> int:
    m = HANCOM_PUA_MAP
    # 숫자
    check("숫자 E034→1, E03C→9, E03D→0", m.get(chr(0xE034)) == "1" and m.get(chr(0xE03C)) == "9" and m.get(chr(0xE03D)) == "0")
    # 대/소문자 경계
    check("대문자 A/Z", m.get(chr(0xE000)) == "A" and m.get(chr(0xE019)) == "Z")
    check("소문자 a/x/z", m.get(chr(0xE0E5)) == "a" and m.get(chr(0xE0FC)) == "x" and m.get(chr(0xE0FE)) == "z")
    # 연산자·기호
    check("연산자 =,+,-,(,)", all(m.get(chr(c)) == s for c, s in [(0xE047, "="), (0xE048, "+"), (0xE046, "-"), (0xE044, "("), (0xE045, ")")]))
    check("수식기호 √,∑,∫", m.get(chr(0xE05C)) == "√" and m.get(chr(0xE067)) == "∑" and m.get(chr(0xE05B)) == "∫")
    check("벡터 악센트 E06E", m.get(chr(0xE06E)) == "⃗")
    # 그리스
    check("그리스 α,π,θ,Δ", all(m.get(chr(c)) == s for c, s in [(0xE09D, "α"), (0xE0AC, "π"), (0xE0A4, "θ"), (0xE088, "Δ")]))
    # 폰트 스코프
    check("폰트 스코프 HyhwpEQ=참, Arial=거짓", is_hancom_eq_font("ABCDEE+HyhwpEQ") and not is_hancom_eq_font("Arial"))
    check("recover_pua_char 미매핑→None", recover_pua_char("") is None and recover_pua_char("A") is None)
    check("케이스 하단 구조조각 E07A 제거", recover_pua_char(chr(0xE07A)) == "")
    check("표 크기(문자52+숫자10+기타)", len(m) >= 71, f"len={len(m)}")

    # 커버리지(실물 PDF 있을 때만, informational)
    _coverage_report()

    if _failures:
        print(f"HANCOM_PUA_MAP_FAIL ({len(_failures)}건): {', '.join(_failures)}")
        return 1
    print("HANCOM_PUA_MAP_OK — E0xx 매핑표 유지")
    return 0


def _coverage_report() -> None:
    try:
        import fitz  # noqa
    except Exception:
        return
    uploads = ROOT / "data" / "uploads"
    pdfs = sorted(uploads.glob("*.pdf")) if uploads.is_dir() else []
    if not pdfs:
        print("  (커버리지: data/uploads에 PDF 없음 — 생략)")
        return
    import fitz
    total = mapped = 0
    for pdf in pdfs:
        try:
            doc = fitz.open(str(pdf))
        except Exception:
            continue
        try:
            for pi in range(doc.page_count):
                for block in doc.load_page(pi).get_text("rawdict").get("blocks", []):
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            if not is_hancom_eq_font(span.get("font")):
                                continue
                            for ch in span.get("chars", []):
                                c = ch.get("c") or ""
                                if c and 0xE000 <= ord(c) <= 0xF8FF:
                                    total += 1
                                    if c in HANCOM_PUA_MAP:
                                        mapped += 1
        finally:
            doc.close()
    if total:
        pct = 100.0 * mapped / total
        print(f"  [커버리지] 실물 PDF {len(pdfs)}부: E0xx 글리프 {mapped}/{total} 복원 = {pct:.1f}%")
        print(f"            → 이 비율이 (1-0.12)=88% 이상이면 수학 문항 다수가 text_reliable=True로 승격(편집텍스트).")


if __name__ == "__main__":
    raise SystemExit(main())
