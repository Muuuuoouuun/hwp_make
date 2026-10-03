# -*- coding: utf-8 -*-
"""PDF 결과 문서의 제목과 영역(과목) 판별 회귀 핀 (2026-10-03).

고친 결함
1. 업로드 저장 파일명(날짜_시각_해시_원래이름)이 그대로 제목이 되고, 밑줄 때문에
   제목이 수식 객체로 조립되던 문제 -> 원래 파일명(확장자 제외)의 일반 텍스트.
2. '대학수학능력시험'에 '수학'이 들어 있다는 이유로 국어·영어 PDF 에 '수학 영역'
   머리말과 수학 양식이 붙던 문제 -> 1쪽에 인쇄된 '○○ 영역' 줄, 없으면 교시 번호
   (1 국어, 2 수학, 3 영어)로 판별하고, 판별이 안 되면 영역명을 비운다.

합성 PDF 만 사용하므로 실물 샘플 없이 항상 실행된다.
"""
from __future__ import annotations

import io
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

_TMP = tempfile.TemporaryDirectory(prefix="pdf_title_subject_")
os.environ.setdefault("HWP_MAKE_DATA_DIR", _TMP.name)

import fitz  # noqa: E402

from app import pdf_layout_writer as w  # noqa: E402
from app.math_text import split_math_text  # noqa: E402

FAILURES: list[str] = []


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
    font = _font()
    kwargs = {"fontfile": font, "fontname": "F0"} if font else {"fontname": "helv"}
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


BODY = [
    "1. 다음 중 옳은 것은? [2점]",
    "① 하나  ② 둘  ③ 셋  ④ 넷  ⑤ 다섯",
    "2. 다음 중 옳지 않은 것은? [3점]",
    "① 하나  ② 둘  ③ 셋  ④ 넷  ⑤ 다섯",
]


def check_subject_detection(tmp: Path) -> None:
    cases = [
        ("area_line", ["2026학년도 대학수학능력시험 문제지", "영어 영역", "제3 교시"], "영어 영역", "kice_english"),
        ("area_compact", ["2026학년도 6월 전국연합학력평가 문제지", "국어영역", "제1 교시"], "국어영역", "kice_korean"),
        ("period_only_1", ["2026학년도 대학수학능력시험 문제지", "제1 교시", "홀수형"], "국어 영역", "kice_korean"),
        ("period_only_2", ["2026학년도 대학수학능력시험 문제지", "제2 교시", "홀수형"], "수학 영역", "kice_math"),
        ("period_only_3", ["2026학년도 대학수학능력시험 문제지", "제3 교시", "홀수형"], "영어 영역", "kice_english"),
        ("science", ["2026학년도 대학수학능력시험 문제지", "과학탐구영역(물리학I)", "제4 교시"], "과학탐구영역(물리학I)", "kice_science"),
        ("period_4_unknown", ["2026학년도 대학수학능력시험 문제지", "제4 교시"], "", ""),
        ("nothing", ["합성 장문 시험지  - 1 -"], "", ""),
    ]
    for key, head, area, template in cases:
        pdf = tmp / f"{key}.pdf"
        _make_pdf(pdf, head, BODY)
        detected = w.detect_source_subject(pdf)
        _check(f"영역 판별 {key}: area", detected["area"] == area, f"{detected!r} != {area!r}")
        _check(f"영역 판별 {key}: template", detected["template_key"] == template, f"{detected!r}")

    # 파일명·제목의 '수학' 은 1쪽 판별보다 뒤다. 제목 '대학수학능력시험' 만으로는 수학이 아니다.
    _check(
        "제목 '대학수학능력시험' 만으로 수학 양식이 되지 않는다",
        w._structured_pdf_template_key("eng_25.pdf", "2026학년도 대학수학능력시험 문제지") != "kice_math",
    )
    _check(
        "1쪽 판별이 파일명보다 우선한다",
        w._structured_pdf_template_key("math_final.pdf", "", "kice_english") == "kice_english",
    )
    _check(
        "판별 없이 파일명 '수학' 은 그대로 수학 양식",
        w._structured_pdf_template_key("3월 수학 문제지.pdf", "") == "kice_math",
    )


def check_display_stem() -> None:
    stored = Path("20261003_013809_9d4c3ba5_long_42p.pdf")
    _check("저장 접두사 제거", w.source_display_stem(stored) == "long_42p", w.source_display_stem(stored))
    _check(
        "원래 파일명이 있으면 그 이름",
        w.source_display_stem(stored, "2학기 기말 수학_2반.pdf") == "2학기 기말 수학_2반",
    )
    _check("접두사 없는 이름은 그대로", w.source_display_stem(Path("synthetic_math_20.pdf")) == "synthetic_math_20")


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


def check_native_output(tmp: Path) -> None:
    # 영어 PDF: 머리말이 '영어 영역' 이어야 하고 '수학 영역' 이 있으면 안 된다.
    english = tmp / "20261003_120000_0123abcd_eng_sample_a.pdf"
    _make_pdf(english, ["2026학년도 대학수학능력시험 문제지", "제3 교시", "홀수형"], BODY)
    out = tmp / "eng.hwpx"
    try:
        stats = w.write_pdf_structured_hwpx(english, out, native_math=True, source_name="eng_sample_a.pdf")
    except ValueError as exc:
        # 예전엔 'SKIP-ish' 출력 뒤 return 해 영어 머리말·제목 핀이 조용히 빠지고 exit 0 이었다.
        if not _font():
            print(f"SKIP: 한글 글꼴이 없어 합성 영어 PDF 를 변환할 수 없음 ({exc})")
            raise SystemExit(2)
        _check("합성 영어 PDF 변환", False, f"ValueError: {exc}")
        return
    texts, scripts = _hwpx_texts(out)
    joined = "\n".join(texts)
    _check("영어 PDF 양식", stats.get("template_key") == "kice_english", str(stats.get("template_key")))
    _check("영어 PDF 머리말에 '영어 영역'", "영어 영역" in joined)
    _check("영어 PDF 머리말에 '수학 영역' 없음", "수학 영역" not in joined)
    _check("영어 PDF 통계에 subject_area", stats.get("subject_area") == "영어 영역", str(stats.get("subject_area")))

    # 머리말 제목이 없는 PDF: 원래 파일명이 일반 텍스트 제목이 되고 수식으로 조립되지 않는다.
    plain = tmp / "20261003_120000_0123abcd_my_exam_v2.pdf"
    _make_pdf(plain, ["합성 시험지  - 1 -"], BODY)
    out2 = tmp / "plain.hwpx"
    try:
        stats2 = w.write_pdf_structured_hwpx(plain, out2, native_math=True, source_name="my_exam_v2.pdf")
    except ValueError as exc:
        # 예전엔 'SKIP-ish' 출력 뒤 return 해 제목·영역 핀 4개가 조용히 빠지고 exit 0 이었다.
        if not _font():
            print(f"SKIP: 한글 글꼴이 없어 합성 무제 PDF 를 변환할 수 없음 ({exc})")
            raise SystemExit(2)
        _check("합성 무제 PDF 변환", False, f"ValueError: {exc}")
        return
    texts2, scripts2 = _hwpx_texts(out2)
    _check("제목이 원래 파일명", texts2 and texts2[0] == "my_exam_v2", repr(texts2[:2]))
    _check("제목이 수식으로 조립되지 않음", not any("my" in s or "exam" in s for s in scripts2), repr(scripts2[:3]))
    _check("판별 불가 PDF 에 '수학 영역' 없음", "수학 영역" not in "\n".join(texts2))
    _check("판별 불가 PDF 의 subject_area 비어 있음", not stats2.get("subject_area"), str(stats2.get("subject_area")))
    _check("밑줄 파일명은 split_math_text 에서도 수식이 아니다",
           all(not is_math for _, is_math in split_math_text("20261003_013809_9d4c3ba5_long_42p")))


def main() -> int:
    print("PDF 제목·영역 판별 회귀 핀")
    with tempfile.TemporaryDirectory(prefix="title_subject_") as raw:
        tmp = Path(raw)
        check_display_stem()
        check_subject_detection(tmp)
        check_native_output(tmp)
    if FAILURES:
        print(f"\nPDF_TITLE_SUBJECT_FAIL — {len(FAILURES)}건")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("\nPDF_TITLE_SUBJECT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
