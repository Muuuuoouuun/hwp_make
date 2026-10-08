"""Portable English PDF geometry regressions with independent source phrases."""
from pathlib import Path
import base64
import re
import sys

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.recognition.pipeline import recognize_pdf
from app.recognition.schema import Subject
from app.recognition.pdf_segment import _looks_like_footer_band_line
from app.recognition.schema import Box


def compact(value):
    return re.sub(r"\s+", "", value)


def recognize(document):
    payload = document.tobytes()
    document.close()
    return recognize_pdf(payload, filename="ENGLISH.pdf").problems


def check_copyright_body_choice():
    text = "⑤ 인공 지능을 활용한 창작 시 저작권법 준수가 필수적이다."
    for top in (300, 780):
        assert not _looks_like_footer_band_line({"text": text, "box": Box(40, top, 500, top + 15)}, 842)
    footer = "이 문제지에 관한 저작권은 한국교육과정평가원에 있습니다."
    assert _looks_like_footer_band_line({"text": footer, "box": Box(40, 790, 500, 805)}, 842)
    assert not _looks_like_footer_band_line({"text": footer, "box": Box(40, 300, 500, 315)}, 842)
    document = fitz.open()
    page = document.new_page()
    page.insert_text((40, 50), "English", fontsize=12)
    page.insert_text((40, 100), "2. Choose the correct statement.", fontsize=10)
    for y, marker in zip((125, 145, 165, 185), "①②③④"):
        page.insert_text((40, y), marker + " 다른 의견이다.", fontname="korea", fontsize=10)
    page.insert_text((40, 205), text, fontname="korea", fontsize=10)
    page.insert_text((40, 780), footer, fontname="korea", fontsize=10)
    problems = recognize(document)
    assert len(problems) == 1 and text in problems[0].text, problems
    assert footer not in problems[0].text
    print("PASS: copyright-topic choice remains editable; only source footer boilerplate is excluded")


def check_right_column_questions():
    document = fitz.open()
    page = document.new_page()
    page.insert_text((35, 50), "English", fontsize=12)
    page.insert_text((35, 100), "[41~42] Read the passage.", fontsize=10)
    prose = ["A lighthouse keeper records every ship.",
             "Only the red vessel arrived after sunset."]
    for y, text in zip((125, 145), prose):
        page.insert_text((35, y), text, fontsize=10)
    page.draw_rect(fitz.Rect(30, 110, 270, 160))
    page.insert_text((325, 100), "41. Choose the title.", fontsize=10)
    page.insert_text((325, 220), "42. Which vessel arrived?", fontsize=10)
    problems = recognize(document)
    assert [p.number for p in problems] == [41, 42]
    expected = compact(" ".join(prose))
    for problem in problems:
        assert expected in compact(problem.shared_passage_text), problem
        assert problem.column_index == 2 and problem.column_count == 2
        assert "lighthouse" not in problem.text, "Shared prose leaked into a question body"
    print("PASS: boxed left-column passage follows both right-column-only questions")


def check_previous_mixed_page():
    document = fitz.open()
    page = document.new_page()
    page.insert_text((40, 50), "English", fontsize=12)
    page.insert_text((40, 100), "40. A preceding independent question.", fontsize=10)
    page.insert_text((40, 220), "[41~42] Read the passage.", fontsize=10)
    prose = "A complete harbor record explains the unexpected arrival."
    page.insert_text((40, 245), prose, fontsize=10)
    page = document.new_page()
    page.insert_text((40, 50), "English", fontsize=12)
    page.insert_text((40, 120), "41. Choose the title.", fontsize=10)
    page.insert_text((40, 300), "42. Explain the arrival.", fontsize=10)
    problems = recognize(document)
    assert [p.number for p in problems] == [40, 41, 42]
    assert "harbor" not in problems[0].text
    for problem in problems[1:]:
        assert prose in problem.shared_passage_text
        assert problem.shared_passage_page_number == 1
    print("PASS: passage on a preceding mixed page belongs to each later question")


def check_passage_across_columns():
    document = fitz.open()
    page = document.new_page()
    page.insert_text((35, 50), "English", fontsize=12)
    page.insert_text((35, 500), "[41~42] Read the passage.", fontsize=10)
    left_prose = "The keeper starts the record in the left column."
    right_prose = ["A vital continuation begins at the top of the right column.",
                   "The second ship brought the missing cargo."]
    page.insert_text((35, 525), left_prose, fontsize=10)
    page.insert_text((325, 45), "English Area", fontsize=12)
    page.insert_text((325, 65), "8 영어 영역", fontsize=10, fontname="korea")
    page.insert_text((440, 65), "홀수형", fontsize=10, fontname="korea")
    page.insert_text((510, 65), "고1", fontsize=10, fontname="korea")
    page.insert_text((560, 45), "3", fontsize=10)
    for y, text in zip((120, 145), right_prose):
        page.insert_text((325, y), text, fontsize=9)
    page.insert_text((325, 300), "41. Choose the title.", fontsize=10)
    page.insert_text((325, 420), "42. Which ship brought the cargo?", fontsize=10)
    problems = recognize(document)
    assert [p.number for p in problems] == [41, 42]
    for problem in problems:
        assert problem.column_index == 2 and problem.column_count == 2
        for text in [left_prose, *right_prose]:
            assert text in problem.shared_passage_text, problem.shared_passage_text
            assert text not in problem.text
        assert "English Area" not in problem.shared_passage_text
        assert "영어 영역" not in problem.shared_passage_text
        assert "홀수형" not in problem.shared_passage_text
        assert "고1" not in problem.shared_passage_text
        assert "3" not in problem.shared_passage_text.splitlines()
    print("PASS: passage crosses into the next column's top; running headers stay out")


def check_passage_across_columns_before_next_page():
    for has_divider in (False, True):
        document = fitz.open()
        page = document.new_page()
        page.insert_text((35, 50), "English", fontsize=12)
        page.insert_text((35, 100), "40. A preceding independent question.", fontsize=10)
        page.insert_text((35, 500), "[41~42] Read the passage.", fontsize=10)
        left_prose = "The keeper starts the record in the left column."
        right_prose = "The next ship brings the missing cargo."
        page.insert_text((35, 525), left_prose, fontsize=10)
        page.insert_text((325, 120), right_prose, fontsize=10)
        page.insert_text((325, 45), "English Area", fontsize=12)
        page.insert_text((510, 65), "고1", fontsize=10, fontname="korea")
        if has_divider:
            page.draw_line((page.rect.width / 2, 80), (page.rect.width / 2, 780))
        page = document.new_page()
        page.insert_text((35, 50), "English", fontsize=12)
        page.insert_text((35, 120), "41. Choose the title.", fontsize=10)
        page.insert_text((35, 300), "42. Which ship brought the cargo?", fontsize=10)
        problems = recognize(document)
        assert [p.number for p in problems] == [40, 41, 42]
        if not has_divider:
            assert problems[0].column_count == 1, "Prose alone must not create a second column"
            continue
        assert problems[0].column_count == 2
        assert left_prose not in problems[0].text and right_prose not in problems[0].text
        for problem in problems[1:]:
            assert left_prose in problem.shared_passage_text, problem.shared_passage_text
            assert right_prose in problem.shared_passage_text, problem.shared_passage_text
            assert problem.shared_passage_page_number == 1
            assert "English Area" not in problem.shared_passage_text
            assert "고1" not in problem.shared_passage_text
    print("PASS: a central divider preserves continuation before next-page questions; prose alone keeps one column")


def check_header_subject_continuation():
    document = fitz.open()
    page = document.new_page()
    page.insert_text((35, 50), "English", fontsize=12)
    page.insert_text((35, 120), "28. Read the announcement.", fontsize=10)
    page = document.new_page()
    page.insert_text((35, 120), "29. Check the grammar in the passage.", fontsize=10)
    payload = document.tobytes()
    document.close()
    result = recognize_pdf(payload, filename="exam.pdf")
    assert [p.subject for p in result.problems] == [Subject.ENGLISH, Subject.ENGLISH]
    # An explicit filename subject remains the default on later pages.
    result = recognize_pdf(payload, filename="math.pdf")
    assert [p.subject for p in result.problems] == [Subject.ENGLISH, Subject.MATH]
    document = fitz.open(stream=payload, filetype="pdf")
    document[1].insert_text((35, 50), "수학 영역", fontsize=12, fontname="korea")
    result = recognize_pdf(document.tobytes(), filename="exam.pdf")
    document.close()
    assert [p.subject for p in result.problems] == [Subject.ENGLISH, Subject.MATH]
    print("PASS: neutral documents retain a detected English subject; explicit hints and new area headings take precedence")


def check_inline_blank_reading_order():
    document = fitz.open()
    page = document.new_page()
    page.insert_text((40, 50), "English", fontsize=12)
    page.insert_text((40, 120), "40. Complete the summary.", fontsize=10)
    page.insert_text((40, 160), "Financial", fontsize=11)
    page.insert_text((105, 158.8), "(A)", fontsize=11)
    page.insert_text((140, 160), "affects audiences.", fontsize=11)
    page.draw_rect(fitz.Rect(35, 140, 280, 180))
    problem, = recognize(document)
    assert "Financial(A)affectsaudiences." in compact(problem.text), problem.text
    print("PASS: raised inline blank stays between the surrounding editable words")


def check_answer_rules():
    document = fitz.open()
    page = document.new_page()
    page.insert_text((40, 50), "English", fontsize=12)
    page.insert_text((40, 120), "31. Complete the sentence.", fontsize=10)
    page.insert_text((40, 160), "Their", fontsize=11)
    page.insert_text((155, 160), ", depends on trust.", fontsize=11)
    page.draw_line((70, 162), (153, 162))
    page.insert_text((40, 190), "Underlined words remain intact.", fontsize=11)
    page.draw_line((40, 192), (93, 192))
    problem, = recognize(document)
    assert "Their________,dependsontrust." in compact(problem.text), problem.text
    assert problem.text.count("________") == 1, "Underlined prose was mistaken for an answer blank"
    print("PASS: source answer rule remains editable; underlined words remain prose")


def check_picture_leaders():
    document = fitz.open()
    page = document.new_page()
    page.insert_text((40, 50), "English", fontsize=12)
    page.insert_text((40, 120), "10. Which place is described?", fontsize=10)
    bitmap = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXh8AAAAASUVORK5CYII=")
    page.insert_image(fitz.Rect(40, 140, 260, 260), stream=bitmap)
    page.insert_text((60, 165), "A", fontsize=11)
    page.draw_line((70, 167), (130, 167))
    problem, = recognize(document)
    assert "________" not in problem.text, "A leader inside an original picture became an answer blank"
    print("PASS: picture leader lines remain part of the source graphic")


def check_vector_leaders():
    document = fitz.open()
    page = document.new_page()
    page.insert_text((40, 50), "English", fontsize=12)
    page.insert_text((40, 120), "10. Which place is described?", fontsize=10)
    page.insert_text((60, 165), "A", fontsize=11)
    page.draw_line((70, 167), (130, 167))
    problem, = recognize(document)
    assert "________" not in problem.text, "An isolated vector diagram label became an answer blank"
    print("PASS: an isolated vector label does not acquire an answer blank")


if __name__ == "__main__":
    check_copyright_body_choice()
    check_right_column_questions()
    check_previous_mixed_page()
    check_passage_across_columns()
    check_passage_across_columns_before_next_page()
    check_header_subject_continuation()
    check_inline_blank_reading_order()
    check_answer_rules()
    check_picture_leaders()
    check_vector_leaders()
    print("ENGLISH_RECOGNITION_OK")
