from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Cm, Pt

from . import storage
from .exam_templates import ExamTemplate, get_template, resolve_export_title

CIRCLED_NUMBERS = ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")
QUESTION_PREFIX_RE = re.compile(r"^\s*(?:문제\s*)?(\d{1,3})\s*[\.\)]\s*")
CHOICE_PREFIX_RE = re.compile(r"^\s*(?:[①②③④⑤⑥⑦⑧⑨]|\d+\s*[\.\)])\s*")


def _set_font(paragraph, size: int = 10, bold: bool = False) -> None:
    for run in paragraph.runs:
        run.font.name = "Malgun Gothic"
        run.font.size = Pt(size)
        run.bold = bold


def _choice_label(index: int, template: ExamTemplate) -> str:
    if template.circled_choices and index <= len(CIRCLED_NUMBERS):
        return CIRCLED_NUMBERS[index - 1]
    return f"{index})"


def _strip_question_prefix(text: str, label: str) -> str:
    match = QUESTION_PREFIX_RE.match(text)
    if match and match.group(1) == str(label):
        return text[match.end() :].lstrip()
    return text


def _format_choice(index: int, choice: str, template: ExamTemplate) -> str:
    clean = CHOICE_PREFIX_RE.sub("", choice or "").strip()
    return f"{_choice_label(index, template)} {clean}".rstrip()


def _add_masthead(document: Document, title: str, template: ExamTemplate) -> None:
    heading = document.add_heading(template.masthead_title or title, level=1)
    _set_font(heading, 16, True)

    meta = "   ".join(
        part for part in (template.area, template.period, template.variant) if part
    )
    if meta:
        paragraph = document.add_paragraph(meta)
        _set_font(paragraph, 11, True)
    if template.show_student_fields:
        paragraph = document.add_paragraph(
            "성명 ____________     수험 번호 ____________     " + template.selection
        )
        _set_font(paragraph, 9, False)
    elif template.selection:
        paragraph = document.add_paragraph(template.selection)
        _set_font(paragraph, 9, False)
    for direction in template.directions:
        paragraph = document.add_paragraph(direction)
        _set_font(paragraph, 9, False)


def write_docx(
    path: Path,
    title: str,
    problems: list[dict[str, Any]],
    template_key: str = "basic",
) -> None:
    template = get_template(template_key)
    title = resolve_export_title(title, template)
    document = Document()
    styles = document.styles
    styles["Normal"].font.name = "Malgun Gothic"
    styles["Normal"].font.size = Pt(10)

    _add_masthead(document, title, template)

    for index, problem in enumerate(problems, start=1):
        label = problem.get("number") or str(index)
        subject = problem.get("subject") or ""
        unit = problem.get("unit") or ""
        meta = " / ".join(part for part in [subject, unit] if part)

        stem = problem.get("stem") or ""
        stem_lines = stem.splitlines()
        if template.merge_question_number:
            first_line = (
                _strip_question_prefix(stem_lines[0], label)
                if stem_lines
                else problem.get("title") or "문제"
            )
            paragraph = document.add_paragraph()
            run = paragraph.add_run(f"{label}. {first_line}")
            run.bold = True
            run.font.size = Pt(11)
            if meta:
                paragraph.add_run(f"  [{meta}]").font.size = Pt(9)
            for line in stem_lines[1:]:
                document.add_paragraph(line)
        else:
            paragraph = document.add_paragraph()
            run = paragraph.add_run(f"{label}. {problem.get('title') or '문제'}")
            run.bold = True
            run.font.size = Pt(11)
            if meta:
                paragraph.add_run(f"  [{meta}]").font.size = Pt(9)
            if stem:
                for line in stem_lines:
                    document.add_paragraph(line)

        for image_path in problem.get("image_paths") or []:
            full_path = storage.DATA_DIR / image_path
            if full_path.exists():
                try:
                    document.add_picture(str(full_path), width=Cm(14.5))
                except Exception:
                    document.add_paragraph(f"[이미지 삽입 실패: {Path(image_path).name}]")

        choices = problem.get("choices") or []
        for choice_index, choice in enumerate(choices, start=1):
            document.add_paragraph(_format_choice(choice_index, choice, template))

        answer = problem.get("answer") or ""
        explanation = problem.get("explanation") or ""
        if template.include_answers and answer:
            document.add_paragraph(f"정답: {answer}")
        if template.include_explanations and explanation:
            document.add_paragraph(f"해설: {explanation}")
        if index != len(problems):
            document.add_paragraph("")

    document.save(path)
