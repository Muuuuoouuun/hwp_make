r"""회귀 핀: 같은 줄로 합쳐진 근호 수식 조각을 한 수식으로 유지한다(2026-10-03 R1).

근호 복원은 '√(n⁴+4n)-√(n⁴+n)' 를 두 원본 줄 조각으로 남기고, 같은 행 병합 뒤에도
'$\sqrt{..}$', '−', '$\sqrt{..}$' 세 조각이라 수식 두 개와 본문 '-' 로 갈라졌다.
- 합성 조각: 붙어 있는 복원 수식 두 개, 근호 사이 '+'·'−' 한 글자는 한 수식으로 합친다.
- 복원 표시가 없는 '$a$' 조각이나 떨어진 조각, 다른 기준선 조각은 합치지 않는다.
- 실물(data/ 의 수학 2교시 PDF, 읽기 전용): 25번 분모가 수식 하나 'sqrt {n^{4}+4n}-sqrt {n^{4}+n}'.
  실물이 없으면 그 부분만 건너뛰고(종료코드 2), 합성 검사가 실패하면 1.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory(prefix="hwpmake_radical_join_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = _TMP.name

from app import pdf_layout_writer as w  # noqa: E402

SAMPLE = ROOT / "data" / "pdf_math_real_probe" / "uploads" / "20260708_204535_eb1137e2_수학 2교시.pdf"
failures: list[str] = []


def check(condition: bool, message: str) -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {message}")
    if not condition:
        failures.append(message)


def span(text: str, x0: float, x1: float, *, radical: bool = False, y: float = 188.0, font: str = "HyhwpEQ") -> dict:
    item = {"text": text, "font": font, "size": 11.0, "bbox": (x0, y - 11, x1, y + 2), "origin": (x0, y), "chars": []}
    if radical:
        item["source_radical_chars"] = [{"c": "√"}]
    return item


def synthetic_checks() -> None:
    B = chr(92)
    joined = w._join_adjacent_recovered_math_spans([
        span(f"${B}sqrt{{n^{{4}}+4n}}$", 250.5, 295.5, radical=True),
        span("", 300.9, 309.3),
        span(f"${B}sqrt{{n^{{4}}+n}}$", 310.7, 350.5, radical=True),
    ])
    check([s["text"] for s in joined] == [f"${B}sqrt{{n^{{4}}+4n}}-{B}sqrt{{n^{{4}}+n}}$"],
          f"근호-연산자-근호는 한 수식 {[s['text'] for s in joined]}")
    joined = w._join_adjacent_recovered_math_spans([
        span(f"${B}sqrt{{2}}$", 10, 30, radical=True), span("$x^{2}$", 31, 45)])
    check(len(joined) == 1, f"붙어 있는 복원 수식 두 개는 한 수식 {[s['text'] for s in joined]}")
    plain = w._join_adjacent_recovered_math_spans([span("$a$", 10, 20), span("$b$", 21, 30)])
    check(len(plain) == 2, "복원 표시가 없는 수식 조각은 그대로")
    far = w._join_adjacent_recovered_math_spans([span(f"${B}sqrt{{2}}$", 10, 30, radical=True), span("$b$", 80, 90)])
    check(len(far) == 2, "떨어진 조각은 합치지 않음")
    lifted = w._join_adjacent_recovered_math_spans([span(f"${B}sqrt{{2}}$", 10, 30, radical=True), span("$b$", 31, 40, y=170.0)])
    check(len(lifted) == 2, "기준선이 다른 조각은 합치지 않음")
    prose = w._join_adjacent_recovered_math_spans([
        span(f"${B}sqrt{{2}}$", 10, 30, radical=True), span("와", 31, 40, font="Batang"), span(f"${B}sqrt{{3}}$", 41, 60, radical=True)])
    check(len(prose) == 3, "근호 사이 본문 글자는 합치지 않음")


def real_sample_check() -> bool:
    if not SAMPLE.is_file():
        print(f"  [SKIP] 실물 샘플 없음: data/pdf_math_real_probe/uploads/{SAMPLE.name}")
        return False
    work = Path(_TMP.name) / "real"
    work.mkdir()
    pdf = work / "math_2kyosi.pdf"
    shutil.copyfile(SAMPLE, pdf)
    out = work / "math_2kyosi.hwpx"
    w.write_pdf_structured_hwpx(pdf, out, native_math=True, source_name="수학 2교시.pdf")
    with zipfile.ZipFile(out) as archive:
        xml = "".join(archive.read(name).decode("utf-8") for name in archive.namelist()
                      if re.fullmatch(r"Contents/section\d+\.xml", name))
    scripts = re.findall(r"<hp:script>(.*?)</hp:script>", xml, re.S)
    check("sqrt {n^{4}+4n}-sqrt {n^{4}+n}" in scripts, "실물 25번 분모 '√(n⁴+4n)−√(n⁴+n)' 는 수식 하나")
    check("sqrt {n^{4}+4n}" not in scripts, "근호 앞 조각만 따로 나온 수식 없음")
    return True


def main() -> int:
    print("근호 수식 조각 합치기 회귀 핀")
    synthetic_checks()
    real_ran = real_sample_check()
    if failures:
        print(f"RADICAL_JOIN_FAIL ({len(failures)}건)")
        return 1
    if not real_ran:
        print("RADICAL_JOIN_SKIP (합성 통과, 실물 없음)")
        return 2
    print("RADICAL_JOIN_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        _TMP.cleanup()
