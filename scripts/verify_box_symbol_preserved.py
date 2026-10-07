# -*- coding: utf-8 -*-
"""원본 PDF 의 정당한 '□'(U+25A1, 빈칸 기호) 보존 회귀 핀 (2026-10-03 R2).

고친 결함
- pdf_layout_writer._pdf_output_text 가 미복원 수식 자리표시자('□')를 지우면서 원본 글리프의
  '□'(국어·정치와 법·제2외국어 발문/선지의 빈칸)까지 모두 지웠다(1차 전 과목 매트릭스 45개 소실).
- 자리표시자 '□' 는 정규화 단계에서 PUA(한컴 분수선 E06D, 미지 PUA)로부터만 만들어지므로,
  입력에 이미 있는 U+25A1 은 원본 글리프로 보고 보존하고, 정규화가 만든 '□' 만 지운다.
- 보존된 원본 '□' 는 unresolved_math_placeholders 통계에서 제외한다(원본 텍스트층 '□' 수만큼 차감).

합성 PDF(fitz) 가 주 핀이라 항상 실행된다. 한글 글꼴이 없으면 exit 2(SKIP).
실물 일본어Ⅰ 책자(data/external_exam_qa/2026_csat/...)가 있으면 추가로 확인한다.
"""
from __future__ import annotations

import os
import re
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

_TMP = tempfile.TemporaryDirectory(prefix="box_symbol_preserved_")
os.environ.setdefault("HWP_MAKE_DATA_DIR", _TMP.name)

import fitz  # noqa: E402

from app import pdf_layout_writer as w  # noqa: E402

BOX = "\u25a1"
FAILURES: list[str] = []
REAL_SAMPLE = ROOT / "data/external_exam_qa/2026_csat/문제지/제2외국어한문/05 일본어Ⅰ_문제.pdf"


def _check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS: {name}")
    else:
        FAILURES.append(f"{name} {detail}".strip())
        print(f"FAIL: {name} {detail}".strip())


def _font() -> str:
    for candidate in (
        r"C:\Windows\Fonts\malgun.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    ):
        if Path(candidate).is_file():
            return candidate
    return ""


def _make_pdf(path: Path, head_lines: list[str], body_lines: list[str]) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    kwargs = {"fontfile": _font(), "fontname": "F0"}
    y = 40.0
    for text in head_lines:
        page.insert_text((60, y), text, fontsize=12, **kwargs)
        y += 18
    y = 140.0
    for text in body_lines:
        page.insert_text((60, y), text, fontsize=11, **kwargs)
        y += 18
    doc.save(str(path))
    doc.close()


def _source_boxes(path: Path) -> int:
    with fitz.open(path) as doc:
        return sum(page.get_text().count(BOX) for page in doc)


def _hwpx_texts(path: Path) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    scripts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if not re.fullmatch(r"Contents/section\d+\.xml", name):
                continue
            xml = archive.read(name).decode("utf-8", "replace")
            texts += [m.group(1) for m in re.finditer(r"<hp:t(?:\s[^>]*)?>([^<]*)</hp:t>", xml)]
            scripts += [m.group(1) for m in re.finditer(r"<hp:script>(.*?)</hp:script>", xml, re.S)]
    return texts, scripts


CHOICES = "① 하나  ② 둘  ③ 셋  ④ 넷  ⑤ 다섯"
BOX_BODY = [
    "1. 낱말 카드의 □에 공통으로 들어갈 글자는? [1점]",
    "ペッ□   カ□ト",
    CHOICES,
    "2. □에 들어갈 글자를 모두 조합하여 만들 수 있는 낱말은? [1점]",
    "print□mps   é□é   autom□e",
    CHOICES,
    "3. 갑은 자기 소유 □□ 건물 외벽 수리 공사를 을에게 맡겼다. 옳은 것은?",
    CHOICES,
]
PLAIN_BODY = [
    "1. 다음 중 옳은 것은? [2점]",
    CHOICES,
    "2. 다음 중 옳지 않은 것은? [3점]",
    CHOICES,
]


def check_output_text_funnel() -> None:
    # 원본 글리프 '□' 는 그대로, PUA 에서 만들어진 자리표시자만 지운다.
    keep = [
        "é□é",
        "1. 낱말 카드의 □에 공통으로 들어갈 글자는? [1점]",
        "갑은 자기 소유 □□ 건물",
        "print□mps",
    ]
    for text in keep:
        _check(f"원본 '□' 보존: {text}", w._pdf_output_text(text) == text, repr(w._pdf_output_text(text)))
    _check("한컴 분수선 PUA(E06D) 자리표시자는 제거", w._pdf_output_text("a\ue06db") == "ab", repr(w._pdf_output_text("a\ue06db")))
    _check("미지 PUA 자리표시자는 제거", w._pdf_output_text("x\ue999y") == "xy", repr(w._pdf_output_text("x\ue999y")))
    _check("근호 뒤 PUA 채움 글리프는 종전처럼 제거", w._pdf_output_text("√\ue06dx") == "√x", repr(w._pdf_output_text("√\ue06dx")))
    _check("'▢'·U+FFFD 자리표시자는 종전처럼 제거", w._pdf_output_text("a▢b�c") == "abc", repr(w._pdf_output_text("a▢b�c")))
    mixed = "□\ue06d□"
    _check("원본 '□' 와 PUA 자리표시자가 섞여도 원본만 남는다", w._pdf_output_text(mixed) == "□□", repr(w._pdf_output_text(mixed)))
    _check("두 번 적용해도 같다(멱등)", all(w._pdf_output_text(w._pdf_output_text(t)) == w._pdf_output_text(t) for t in keep))
    _check("내부 보호 문자(U+FDD0)가 결과에 남지 않는다", "\ufdd0" not in w._pdf_output_text("□\ufdd0□"))


def check_synthetic(tmp: Path) -> None:
    pdf = tmp / "box_sample.pdf"
    _make_pdf(pdf, ["합성 시험지  - 1 -"], BOX_BODY)
    source = _source_boxes(pdf)
    if source < 5:
        print(f"SKIP: 글꼴이 '□' 글리프를 심지 못함(source={source})")
        raise SystemExit(2)
    out = tmp / "box_sample.hwpx"
    stats = w.write_pdf_structured_hwpx(pdf, out, native_math=True, source_name="box_sample.pdf")
    texts, scripts = _hwpx_texts(out)
    joined = "".join(texts)
    body = joined.count(BOX)
    in_scripts = "".join(scripts).count(BOX)
    _check(f"합성 PDF: 본문 '□' 수 == 원본 '□' 수({source})", body == source, f"body={body} scripts={in_scripts}")
    _check("합성 PDF: 수식 스크립트에 '□' 없음", in_scripts == 0, str(in_scripts))
    for needle in ("낱말 카드의 □에", "print□mps", "é□é", "□□ 건물", "ペッ□"):
        _check(f"합성 PDF: '{needle}' 가 본문에 그대로", needle in joined)
    _check(
        "합성 PDF: 원본 '□' 는 unresolved_math_placeholders 로 세지 않는다",
        int(stats.get("unresolved_math_placeholders") or 0) == 0,
        str(stats.get("unresolved_math_placeholders")),
    )

    # 대조군: '□' 없는 PDF 는 종전처럼 '□' 0.
    plain = tmp / "plain_sample.pdf"
    _make_pdf(plain, ["합성 시험지  - 1 -"], PLAIN_BODY)
    out2 = tmp / "plain_sample.hwpx"
    stats2 = w.write_pdf_structured_hwpx(plain, out2, native_math=True, source_name="plain_sample.pdf")
    texts2, scripts2 = _hwpx_texts(out2)
    _check("대조군 PDF: 출력에 '□' 0", "".join(texts2 + scripts2).count(BOX) == 0)
    _check("대조군 PDF: unresolved_math_placeholders 0", int(stats2.get("unresolved_math_placeholders") or 0) == 0)


def check_real_sample(tmp: Path) -> None:
    if not REAL_SAMPLE.is_file():
        print(f"SKIP: 실물 샘플 없음 ({REAL_SAMPLE.relative_to(ROOT)})")
        return
    source = _source_boxes(REAL_SAMPLE)
    out = tmp / "japanese.hwpx"
    stats = w.write_pdf_structured_hwpx(REAL_SAMPLE, out, native_math=True, source_name=REAL_SAMPLE.name)
    texts, scripts = _hwpx_texts(out)
    joined = "".join(texts)
    body = joined.count(BOX)
    _check(f"일본어Ⅰ: 본문 '□' 수 == 원본({source})", body == source, f"body={body}")
    _check("일본어Ⅰ: 1번 발문의 '□' 유지", "낱말 카드의 □에" in joined)
    _check("일본어Ⅰ: 수식 스크립트에 '□' 없음", "".join(scripts).count(BOX) == 0)
    _check("일본어Ⅰ: unresolved_math_placeholders 0", int(stats.get("unresolved_math_placeholders") or 0) == 0,
           str(stats.get("unresolved_math_placeholders")))


def main() -> int:
    if not _font():
        print("SKIP: 한글 글꼴이 없어 합성 PDF 를 만들 수 없음")
        return 2
    tmp = Path(_TMP.name)
    check_output_text_funnel()
    check_synthetic(tmp)
    check_real_sample(tmp)
    if FAILURES:
        print(f"RESULT: FAIL ({len(FAILURES)})")
        for item in FAILURES:
            print(" -", item)
        return 1
    print("RESULT: ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
