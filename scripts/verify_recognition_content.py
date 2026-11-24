"""회귀핀: 문항 인식이 본문을 잃지 않는다(2026-11-25 총동원 수정).

번호 일치율이 100%여도 인식 단계에서 본문의 약 40%가 버려지던 결함과, 그 인식 결과를
적용하는 변환 경로의 결함을 고정한다.

인식:
- 테두리만 있는 상자(<보기>·제시문)의 글은 문항 본문에 남는다.
- 안쪽에 칸 구분선이 있는 표는 그림으로 잘라 보존한다(글과 그림 중 하나에는 항상 남는다).
- 같은 쪽의 ``[N~M]`` 공통 지문을 영어 밖 과목에서도 범위 문항 전부에 연결한다.
- 한쪽 단에만 문항이 있는 2단 쪽에서 반대편 지문이 문항 본문에 섞이지 않는다.
- 쪽을 넘어 이어진 지문의 뒷부분을 앞 쪽의 지문에 이어 붙인다.
- 번호 줄이 120자를 넘어도 뒷부분이 잘리지 않는다.
- 본문의 "11. AM 9 … PM 3 … 12" 같은 줄을 인쇄일 머리글로 보고 버리지 않는다.

적용·속도:
- 번호 없는 쪽(표지)이 섞여도 편집형 변환이 실패하지 않는다.
- render=False 인식은 번호·본문이 같고 래스터를 만들지 않는다.
- 변환 한 번에 인식은 한 번만 돈다.
- quality_check="fast" 는 원본 대조만 생략하고 같은 본문을 낸다.

합성 PDF(fitz)만 쓴다. 종료코드: 통과 0, 실패 1, fitz 없음 2(SKIP).
"""
from __future__ import annotations

import base64
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

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
    print("SKIP: PyMuPDF(fitz) 미설치")
    raise SystemExit(2)

_tmp = tempfile.TemporaryDirectory(prefix="hwp_make_recognition_content_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = _tmp.name

from app.recognition import pipeline  # noqa: E402
from app.recognition.pdf_segment import segment_pdf  # noqa: E402
from app.recognition.pipeline import recognize_pdf  # noqa: E402
from app.recognition.schema import Subject  # noqa: E402

_failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}{(' - ' + detail) if detail and not condition else ''}")
    if not condition:
        _failures.append(name)


def new_page(doc):
    return doc.new_page(width=595, height=842)


def put(page, x: float, y: float, text: str, size: float = 11) -> None:
    page.insert_text((x, y), text, fontsize=size)


def by_number(result) -> dict[int, object]:
    return {problem.number: problem for problem in result.problems}


def boxed_text_pdf() -> bytes:
    doc = fitz.open()
    page = new_page(doc)
    put(page, 60, 120, "1. Which statement follows from the box?")
    page.draw_rect(fitz.Rect(60, 135, 290, 235), width=0.8)
    put(page, 70, 160, "BOXLINE-A the committee approved the plan")
    put(page, 70, 180, "BOXLINE-B after a long public debate")
    put(page, 60, 300, "2. Second question after the box.")
    return doc.tobytes()


def table_pdf() -> bytes:
    doc = fitz.open()
    page = new_page(doc)
    put(page, 60, 120, "1. Read the table and answer.")
    page.draw_rect(fitz.Rect(60, 135, 290, 235), width=0.8)
    page.draw_line((175, 135), (175, 235), width=0.8)
    page.draw_line((60, 185), (290, 185), width=0.8)
    put(page, 68, 165, "TBL-A1 height km")
    put(page, 183, 165, "TBL-B1 temp deg")
    put(page, 68, 215, "TBL-A2 3.0 2.0")
    put(page, 183, 215, "TBL-B2 -4 26")
    put(page, 60, 300, "2. Second question after the table.")
    return doc.tobytes()


def same_page_passage_pdf() -> bytes:
    doc = fitz.open()
    page = new_page(doc)
    put(page, 60, 120, "[1~2] Read the passage and answer.")
    put(page, 60, 145, "PASSAGE-ONE about reading models.")
    put(page, 60, 165, "PASSAGE-TWO continues the idea.")
    put(page, 60, 220, "1. First question about the passage?")
    put(page, 60, 300, "2. Second question about the passage?")
    put(page, 60, 380, "3. Unrelated third question?")
    return doc.tobytes()


def divider(page) -> None:
    page.draw_line((297.5, 100), (297.5, 780), width=0.6)


def cross_page_passage_pdf() -> bytes:
    """1쪽 오른쪽 단에서 시작한 지문이 2쪽 왼쪽 단으로 이어지고, 문항은 2쪽 오른쪽 단에만 있다."""
    doc = fitz.open()
    first = new_page(doc)
    divider(first)
    put(first, 60, 150, "1. Opening question on the left?")
    put(first, 320, 150, "[2~3] Read the passage and answer.")
    put(first, 320, 175, "P1-PASSAGE-A opening sentence.")
    put(first, 320, 195, "P1-PASSAGE-B second sentence.")
    second = new_page(doc)
    divider(second)
    for index in range(8):
        put(second, 60, 150 + 20 * index, f"P2-CONT-{index} continued passage line.")
    put(second, 320, 150, "2. Question two on the right?")
    put(second, 320, 230, "3. Question three on the right?")
    return doc.tobytes()


def long_marker_line_pdf() -> bytes:
    doc = fitz.open()
    page = new_page(doc)
    put(page, 40, 120, "1. " + "word " * 30 + "TAIL_SENTINEL", size=6)
    put(page, 40, 200, "2. Short second question.")
    return doc.tobytes()


def unlinked_passage_pdf() -> bytes:
    """발췌본: 8번 아래 [9~10] 지문은 있는데 9번이 없다."""
    doc = fitz.open()
    page = new_page(doc)
    put(page, 60, 120, "8. Question eight of an excerpt?")
    put(page, 60, 145, "choice text for question eight")
    put(page, 60, 220, "[9~10] Read the next passage and answer.")
    put(page, 60, 245, "ORPHAN_SENTINEL passage body without its questions.")
    return doc.tobytes()


def restarted_form_pdf() -> bytes:
    """첫 유형은 12·13번까지만 있고 둘째 유형이 12번부터 다시 시작한다."""
    doc = fitz.open()
    first = new_page(doc)
    put(first, 60, 120, "[12~15] Read the passage and answer.")
    put(first, 60, 145, "FORM-ONE passage body.")
    put(first, 60, 220, "12. First form question twelve?")
    put(first, 60, 300, "13. First form question thirteen?")
    second = new_page(doc)
    for index, number in enumerate((12, 13, 14, 15)):
        put(second, 60, 120 + 80 * index, f"{number}. Second form question {number}?")
    return doc.tobytes()


def single_path_table_pdf() -> bytes:
    """테두리와 칸 구분선을 한 벡터 경로로 그린 표."""
    doc = fitz.open()
    page = new_page(doc)
    put(page, 60, 120, "1. Read the table and answer.")
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(60, 135, 290, 235))
    shape.draw_line((175, 135), (175, 235))
    shape.draw_line((60, 185), (290, 185))
    shape.finish(width=0.8)
    shape.commit()
    put(page, 68, 165, "TBL-A1 height km")
    put(page, 183, 165, "TBL-B1 temp deg")
    put(page, 68, 215, "TBL-A2 3.0 2.0")
    put(page, 183, 215, "TBL-B2 -4 26")
    put(page, 60, 300, "2. Second question after the table.")
    return doc.tobytes()


def central_rule_single_column_pdf() -> bytes:
    """1단 시험지인데 쪽 가운데에 긴 세로선이 있다(답안 작성란 등)."""
    doc = fitz.open()
    page = new_page(doc)
    page.draw_line((297.5, 150), (297.5, 760), width=0.6)
    put(page, 60, 120, "1. This full width question line clearly runs across the middle of the page to the right side.")
    put(page, 60, 145, "FULLWIDTH-SENTINEL body line that also runs across the middle of the page to the right.")
    put(page, 60, 300, "2. The second full width question line also runs across the middle of the page layout.")
    return doc.tobytes()


def band_marker_pdf() -> bytes:
    """다음 쪽의 첫 문항 번호 줄이 머리글 밴드(위 13%) 안에서 시작한다."""
    doc = fitz.open()
    first = new_page(doc)
    put(first, 60, 150, "1. Opening question?")
    put(first, 60, 300, "[2~3] Read the passage and answer.")
    put(first, 60, 325, "BAND-PASSAGE body line.")
    second = new_page(doc)
    put(second, 60, 105, "2. Question two starts inside the header band?")
    put(second, 60, 140, "QUESTION-ONLY body line of question two.")
    put(second, 60, 280, "3. Question three?")
    return doc.tobytes()


def fullwidth_heading_pdf() -> bytes:
    doc = fitz.open()
    page = new_page(doc)
    page.insert_text((60, 120), "［1～2］ Read the passage and answer.", fontsize=11, fontname="korea")
    put(page, 60, 145, "FULLWIDTH-PASSAGE body line.")
    put(page, 60, 220, "1. First question about the passage?")
    put(page, 60, 300, "2. Second question about the passage?")
    return doc.tobytes()


def date_like_question_pdf() -> bytes:
    doc = fitz.open()
    page = new_page(doc)
    put(page, 60, 30, "24. 11. 7. PM 3:21", size=8)  # 인쇄일 머리글(쪽 여백)
    put(page, 60, 90, "24. 11. 7. PM 3:21", size=8)  # 여백 밴드(8%) 밖에 찍힌 인쇄일
    put(page, 60, 200, "10. 3. 1. Movement was a turning point because?")  # 날짜로 시작하는 문항 줄
    put(page, 60, 300, "11. AM 9 and PM 3 readings were 12 degrees.")
    return doc.tobytes()


def cover_page_pdf() -> bytes:
    doc = fitz.open()
    cover = new_page(doc)
    put(cover, 180, 300, "Midterm Examination", size=20)
    put(cover, 200, 340, "Name:            Class:")
    page = new_page(doc)
    put(page, 60, 120, "1. First question after the cover?")
    put(page, 60, 150, "choice text for the first question")
    put(page, 60, 260, "2. Second question after the cover?")
    put(page, 60, 290, "choice text for the second question")
    return doc.tobytes()


def check_recognition() -> None:
    boxed = by_number(recognize_pdf(boxed_text_pdf(), subject=Subject.KOREAN))
    text = getattr(boxed.get(1), "text", "")
    check("테두리 상자 안 글이 본문에 남는다", "BOXLINE-A" in text and "BOXLINE-B" in text, text[:120])
    check("본문 상자는 그림으로 자르지 않는다", not getattr(boxed.get(1), "figure_pngs", [1]))

    table = by_number(recognize_pdf(table_pdf(), subject=Subject.KOREAN))
    text = getattr(table.get(1), "text", "")
    check("칸 구분선이 있는 표는 그림으로 보존한다", len(getattr(table.get(1), "figure_pngs", [])) == 1)
    check("표 안 글은 그림에만 남는다(중복 없음)", "TBL-A1" not in text and "TBL-B2" not in text, text[:120])

    passage = by_number(recognize_pdf(same_page_passage_pdf(), subject=Subject.KOREAN))
    check("같은 쪽 공통 지문을 범위 문항 전부에 연결(영어 밖 과목)",
          all("PASSAGE-ONE" in getattr(passage.get(n), "shared_passage_text", "") for n in (1, 2))
          and all("PASSAGE-TWO" in getattr(passage.get(n), "shared_passage_text", "") for n in (1, 2)))
    check("범위 밖 문항에는 지문을 붙이지 않는다", not getattr(passage.get(3), "shared_passage_text", "x"))

    data = cross_page_passage_pdf()
    pages = segment_pdf(data, subject=Subject.KOREAN)
    check("한쪽 단에만 문항이 있어도 2단으로 본다",
          [int(page.metadata.get("column_count") or 0) for page in pages] == [2, 2])
    crossed = by_number(recognize_pdf(data, subject=Subject.KOREAN))
    shared = [getattr(crossed.get(n), "shared_passage_text", "") for n in (2, 3)]
    check("쪽을 넘은 지문 뒷부분까지 연결", all("P1-PASSAGE-A" in s and "P2-CONT-7" in s for s in shared),
          shared[0][-80:] if shared else "")
    check("반대편 단의 지문이 문항 본문에 섞이지 않는다",
          not any("P2-CONT" in getattr(crossed.get(n), "text", "P2-CONT") for n in (2, 3)))
    check("지문이 앞 문항에는 붙지 않는다", not getattr(crossed.get(1), "shared_passage_text", "x"))

    long_line = by_number(recognize_pdf(long_marker_line_pdf(), subject=Subject.KOREAN))
    check("120자를 넘는 번호 줄의 뒷부분 보존", "TAIL_SENTINEL" in getattr(long_line.get(1), "text", ""))

    dated = recognize_pdf(date_like_question_pdf(), subject=Subject.KOREAN)
    numbers = [problem.number for problem in dated.problems]
    check("본문의 날짜형 문항 줄은 문항이고 인쇄일은 어디에 찍혀도 아니다", numbers == [10, 11], repr(numbers))

    unlinked = recognize_pdf(unlinked_passage_pdf(), subject=Subject.KOREAN)
    check("받을 문항이 없는 지문의 글은 앞 문항에 남는다(소실·0번 없음)",
          [p.number for p in unlinked.problems] == [8] and "ORPHAN_SENTINEL" in unlinked.problems[0].text,
          repr([(p.number, p.text[-60:]) for p in unlinked.problems]))

    restarted = recognize_pdf(restarted_form_pdf(), subject=Subject.KOREAN)
    owners = [(p.page_number, p.number) for p in restarted.problems if "FORM-ONE" in p.shared_passage_text]
    check("번호가 다시 시작한 다음 유형에는 앞 유형의 지문을 붙이지 않는다", owners == [(1, 12), (1, 13)], repr(owners))

    single_path = by_number(recognize_pdf(single_path_table_pdf(), subject=Subject.KOREAN))
    check("한 경로로 그린 표도 그림으로 보존한다", len(getattr(single_path.get(1), "figure_pngs", [])) == 1
          and "TBL-A1" not in getattr(single_path.get(1), "text", "TBL-A1"))

    data = central_rule_single_column_pdf()
    check("본문이 가운데를 가로지르면 세로선이 있어도 1단이다",
          [int(page.metadata.get("column_count") or 0) for page in segment_pdf(data, subject=Subject.KOREAN)] == [1])
    check("1단 시험지의 전폭 줄을 잃지 않는다",
          "FULLWIDTH-SENTINEL" in getattr(by_number(recognize_pdf(data, subject=Subject.KOREAN)).get(1), "text", ""))

    band = by_number(recognize_pdf(band_marker_pdf(), subject=Subject.KOREAN))
    shared = [getattr(band.get(n), "shared_passage_text", "") for n in (2, 3)]
    check("머리글 밴드 안에서 시작한 문항의 본문이 지문에 섞이지 않는다",
          all("BAND-PASSAGE" in s and "QUESTION-ONLY" not in s for s in shared)
          and "QUESTION-ONLY" in getattr(band.get(2), "text", ""), repr(shared))

    try:
        fullwidth = by_number(recognize_pdf(fullwidth_heading_pdf(), subject=Subject.KOREAN))
    except Exception as exc:  # 내장 CJK 글꼴이 없는 PyMuPDF 빌드
        print(f"  [SKIP] 전각 대괄호 지문 머리 - {type(exc).__name__}")
    else:
        check("전각 대괄호 ［N～M］ 지문 머리도 인식한다",
              all("FULLWIDTH-PASSAGE" in getattr(fullwidth.get(n), "shared_passage_text", "") for n in (1, 2)))


def check_importer() -> None:
    from app import importers, storage

    stem, choices = importers._split_stem_and_choices(
        "12. Pick the right ones.\na. first item\nb. second item\n① a ② b ③ a, b ④ a, c ⑤ b, c")
    check("원문자 선지가 있으면 a./b. 줄은 <보기> 항목으로 본문에 남는다",
          len(choices) == 5 and "a. first item" in stem and "b. second item" in stem, repr((stem, choices)))
    _, lettered = importers._split_stem_and_choices("3. Pick one.\nA. alpha\nB. beta\nC. gamma\nD. delta")
    check("원문자가 없는 문항의 A.~D. 는 그대로 선지다", len(lettered) == 4, repr(lettered))

    storage.init_db()
    result = importers.import_pdf("korean_passage.pdf", same_page_passage_pdf(), {})
    created = [storage.get_problem(item["id"]) for item in result.get("created") or []]
    first = next((problem for problem in created if str(problem.get("number")) == "1"), {})
    layout = first.get("layout") or {}
    passage_lines = [line for line in layout.get("pdf_lines") or [] if "PASSAGE" in str(line.get("text") or "")]
    check("가져온 문항이 지문 사본을 지닌다", layout.get("block_type") == "problem_with_shared_passage"
          and "PASSAGE-ONE" in str(first.get("stem") or ""), repr(layout.get("block_type")))
    check("지문 줄 좌표는 글·상자·쪽만 저장한다(글자별 좌표 복제 없음)",
          bool(passage_lines) and all(set(line) <= {"text", "bbox_px", "page"} for line in passage_lines),
          repr([sorted(line) for line in passage_lines[:1]]))


def check_render_flag() -> None:
    data = table_pdf()
    full = recognize_pdf(data, subject=Subject.KOREAN)
    light = recognize_pdf(data, subject=Subject.KOREAN, render=False)
    check("render=False 도 번호·본문이 같다",
          [(p.number, p.text) for p in full.problems] == [(p.number, p.text) for p in light.problems])
    check("render=False 는 PNG 를 만들지 않는다",
          not any(p.figure_pngs or p.problem_image_png for p in light.problems))


def output_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = "".join(archive.read(name).decode("utf-8", "replace")
                      for name in sorted(archive.namelist()) if re.fullmatch(r"Contents/section\d+\.xml", name))
    return "".join(re.findall(r"<hp:t[^>]*>([^<]*)</hp:t>", xml))


def check_application() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    exports = Path(_tmp.name) / "exports"
    calls = {"segment": 0}
    original = pipeline.segment_pdf

    def counting(*args, **kwargs):
        calls["segment"] += 1
        return original(*args, **kwargs)

    payload = {"filename": "cover_exam.pdf", "data_base64": base64.b64encode(cover_page_pdf()).decode("ascii")}
    pipeline.segment_pdf = counting
    try:
        full = client.post("/api/pdf-layout-export", json=payload)
        full_calls = calls["segment"]
        fast = client.post("/api/pdf-layout-export", json={**payload, "quality_check": "fast"})
    finally:
        pipeline.segment_pdf = original

    check("표지 쪽이 있어도 편집형 변환 성공", full.status_code == 200, full.text[:200])
    if full.status_code != 200 or fast.status_code != 200:
        check("빠른 변환 성공", fast.status_code == 200, fast.text[:200])
        return
    body = full.json()
    grouping = (body.get("stats") or {}).get("question_grouping") or {}
    check("문항 인벤토리 일치(번호 없는 쪽 제외)", grouping.get("inventory_matches") is True
          and grouping.get("question_count") == 2, repr(grouping.get("missing_question_markers")))
    full_text = output_text(exports / body["export"]["name"])
    check("표지의 글은 편집 가능한 본문으로 남는다", "MidtermExamination" in re.sub(r"\s+", "", full_text))
    check("변환 한 번에 인식은 한 번", full_calls == 1, f"segment_pdf {full_calls}회")

    quick = fast.json()
    check("빠른 변환은 원본 대조만 생략", (quick.get("fidelity") or {}).get("skipped") is True
          and (quick.get("quality") or {}).get("quality_check") == "fast")
    check("빠른 변환의 화면 대조 판정은 미달이 아니라 미측정이다",
          (quick.get("quality") or {}).get("meets_objective_score_target") is None
          and "native_output_requires_layout_review" not in ((quick.get("quality") or {}).get("visual_review_flags") or []))
    notices = quick.get("notices") or []
    check("빠른 변환 안내가 있고 품질 미달로 표시하지 않는다",
          any("빠른 변환" in notice for notice in notices)
          and not any("품질 기준을 충족하지 못했습니다" in notice for notice in notices), repr(notices))
    check("빠른 변환과 정밀 변환의 본문이 같다", output_text(exports / quick["export"]["name"]) == full_text)
    check("빠른 변환도 문항별 검수는 한다", isinstance(quick.get("review"), dict))


def main() -> int:
    try:
        check_recognition()
        check_render_flag()
        check_importer()
        check_application()
    finally:
        _tmp.cleanup()
    if _failures:
        print(f"RECOGNITION_CONTENT_FAIL ({len(_failures)}): {', '.join(_failures)}")
        return 1
    print("RECOGNITION_CONTENT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
