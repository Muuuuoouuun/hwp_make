"""E0xx 수식폰트 PUA 매핑표 추출 프로브 — 병목 #2 준비 도구(테스트 아님).

실물 평가원/학평 born-digital PDF에서 (font, PUA코드)→빈도를 덤프한다. 두 개 이상의
PDF에서 같은 (font, code)가 나오면 코드페이지가 문서 독립임을 시사(정적 매핑표 가능).
get_texttrace로 (unicode, glyph_id, bbox)도 뽑아 사람이 코드↔기호를 대조할 수 있게 한다.

이 저장소엔 현재 실물 PDF가 없어 합성 PDF(PUA 없음)만 존재 → "PUA 0개"로 보고된다.
실물 PDF를 인자로 주면 즉시 매핑 후보를 출력한다.

사용:
  python scripts/probe_kice_pua.py path/to/kice_math.pdf [more.pdf ...]
  python scripts/probe_kice_pua.py            # data/uploads의 PDF 자동탐색
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import fitz  # PyMuPDF
except Exception:
    print("PyMuPDF(fitz) 미설치 — 프로브 불가")
    raise SystemExit(2)


def is_pua(code: int) -> bool:
    # PUA(U+E000–F8FF). 특히 E0xx=한컴 임베디드 수식 서브셋, F0xx=Adobe Symbol.
    return 0xE000 <= code <= 0xF8FF


def probe(pdf_path: Path) -> collections.Counter:
    counter: collections.Counter = collections.Counter()
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        print(f"  열기 실패 {pdf_path.name}: {exc}")
        return counter
    try:
        for page in doc:
            try:
                data = page.get_text("dict")
            except Exception:
                continue
            for block in data.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        font = span.get("font", "?")
                        for ch in span.get("text", ""):
                            if is_pua(ord(ch)):
                                counter[(font, ord(ch))] += 1
    finally:
        doc.close()
    return counter


def discover() -> list[Path]:
    if len(sys.argv) > 1:
        return [Path(a).resolve() for a in sys.argv[1:]]
    uploads = ROOT / "data" / "uploads"
    return sorted(uploads.glob("*.pdf")) if uploads.is_dir() else []


def main() -> int:
    pdfs = discover()
    if not pdfs:
        print("PDF 없음: 인자로 실물 평가원 PDF 경로를 주거나 data/uploads에 두세요.")
        return 2
    total: collections.Counter = collections.Counter()
    for pdf in pdfs:
        c = probe(pdf)
        total.update(c)
        print(f"[{pdf.name}] PUA 글리프 {sum(c.values())}개, 고유 (font,code) {len(c)}종")
        for (font, code), n in c.most_common(20):
            print(f"    {font:24} U+{code:04X}  ×{n}")
    if not total:
        print("\nPUA 0개 — 합성/표준폰트 PDF로 보입니다. 실물 평가원 PDF가 필요합니다(병목 #2).")
        return 0
    print(f"\n총 고유 (font,code) {len(total)}종. 두 개 이상 PDF에서 반복되면 정적 매핑표 후보.")
    print("→ 다음: 각 코드의 crop 이미지를 눈으로 확인해 기호를 확정하고 math_text.HANCOM_PUA_MAP에 추가.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
