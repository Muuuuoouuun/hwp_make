"""python-hwpx(airmang, vendored) 기반 HWPX 작성기 — 시범 포팅(평가용).

기존 hwpx_writer.py는 HWPX를 문자열 템플릿으로 손수 직렬화한다. 이 모듈은
동일한 write_hwpx 시그니처를 vendored python-hwpx 고수준 API로 재구현해
출력/렌더 호환성을 비교하기 위한 실험본이다. 아직 main.py에 연결하지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PIL import Image

# vendored python-hwpx (app/_vendor/hwpx). 내부적으로 `import hwpx` 절대경로를
# 쓰므로 _vendor 디렉터리를 sys.path에 얹어 top-level 패키지로 노출한다.
_VENDOR = Path(__file__).resolve().parent / "_vendor"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))
from hwpx import HwpxDocument  # noqa: E402

from . import storage  # noqa: E402
from .exam_templates import (  # noqa: E402
    ANSWER_SHEET_TITLE,
    ExamTemplate,
    explanation_entries,
    get_template,
    quick_answer_lines,
    resolve_export_title,
)
from .hwpx_writer import (  # noqa: E402  (포맷 로직 재사용)
    COLUMN_GAP,
    MAX_IMAGE_WIDTH,
    PX_TO_HWPUNIT,
    _format_choice,
    _strip_question_prefix,
)

# 기존 CHAR_HEIGHTS(HWPUNIT)를 포인트로 환산: height = pt * 100.
PT_TITLE = 16.0    # char 1 (1600)
PT_META = 12.5     # char 3 (1250)
PT_HEADING = 11.5  # char 2 (1150)
PT_BODY = 10.0     # char 0 (1000)
PT_SMALL = 9.0     # char 4 (900)

_IMG_FORMATS = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".gif": "gif", ".bmp": "bmp"}


def _picture_size(full_path: Path, max_width: int) -> tuple[int, int] | None:
    try:
        with Image.open(full_path) as image:
            px_width, px_height = image.size
    except Exception:
        return None
    width = px_width * PX_TO_HWPUNIT
    height = px_height * PX_TO_HWPUNIT
    if width > max_width:
        height = int(height * max_width / width)
        width = max_width
    return width, height


def write_hwpx(
    path: Path,
    title: str,
    problems: list[dict[str, Any]],
    template_key: str = "basic",
    include_answer_sheet: bool = False,
) -> None:
    template = get_template(template_key)
    title = resolve_export_title(title, template)
    columns = max(1, min(template.columns, 2))
    content_width = (
        (MAX_IMAGE_WIDTH - COLUMN_GAP * (columns - 1)) // columns
        if columns > 1
        else MAX_IMAGE_WIDTH
    )

    doc = HwpxDocument.new()
    header = doc.headers[0]

    # paraPr(정렬) / charPr(크기) 참조를 한 번씩만 만들어 재사용한다.
    pr_left = header.ensure_paragraph_alignment("LEFT")
    pr_center = header.ensure_paragraph_alignment("CENTER")
    cp = {
        "title": doc.ensure_run_style(size=PT_TITLE, bold=True),
        "meta": doc.ensure_run_style(size=PT_META),
        "heading": doc.ensure_run_style(size=PT_HEADING, bold=True),
        "body": doc.ensure_run_style(size=PT_BODY),
        "small": doc.ensure_run_style(size=PT_SMALL),
    }

    def para(text: str, style: str = "body", center: bool = False, **attrs: str) -> None:
        doc.add_paragraph(
            text,
            para_pr_id_ref=pr_center if center else pr_left,
            char_pr_id_ref=cp[style],
            inherit_style=False,
            **attrs,
        )

    if columns > 1:
        doc.set_columns(columns, same_gap=COLUMN_GAP)

    # --- 머리말 ---
    if template.key == "basic":
        para(title, "title", center=True)
        para("")
    else:
        para(template.masthead_title or title, "title", center=True)
        meta = "   ".join(p for p in (template.area, template.period, template.variant) if p)
        if meta:
            para(meta, "meta", center=True)
        if template.show_student_fields:
            para("성명 ____________     수험 번호 ____________     " + template.selection, "small", center=True)
        elif template.selection:
            para(template.selection, "small", center=True)
        for direction in template.directions:
            para(direction, "small")
        para("")

    # --- 문항 ---
    for index, problem in enumerate(problems, start=1):
        label = problem.get("number") or str(index)
        subject = problem.get("subject") or ""
        unit = problem.get("unit") or ""
        meta = " / ".join(p for p in [subject, unit] if p)

        stem_lines = (problem.get("stem") or "").splitlines()
        if template.merge_question_number:
            first_line = _strip_question_prefix(stem_lines[0], label) if stem_lines else ""
            para(f"{label}. {first_line or problem.get('title') or '문제'}", "heading")
            for line in stem_lines[1:]:
                para(line, "body")
            if meta:
                para(f"[{meta}]", "small")
        else:
            heading = f"{label}. {problem.get('title') or '문제'}"
            if meta:
                heading += f" [{meta}]"
            para(heading, "heading")
            for line in stem_lines or [""]:
                para(line, "body")

        for rows in problem.get("tables") or []:
            _add_table(doc, rows)

        for image_path in problem.get("image_paths") or []:
            _add_picture(doc, image_path, content_width)

        choices = [
            _format_choice(ci, choice, template)
            for ci, choice in enumerate(problem.get("choices") or [], start=1)
        ]
        if choices and template.inline_short_choices and sum(len(c) for c in choices) <= 90:
            para("    ".join(choices), "body")
        else:
            for choice in choices:
                para(choice, "body")

        if template.include_answers and problem.get("answer"):
            para(f"정답: {problem['answer']}", "body")
        if template.include_explanations and problem.get("explanation"):
            para(f"해설: {problem['explanation']}", "body")
        para("")

    # --- 정답지 ---
    if include_answer_sheet:
        para(ANSWER_SHEET_TITLE, "title", center=True, pageBreak="1")
        para("")
        para("빠른 정답", "heading")
        for line in quick_answer_lines(problems, template):
            para(line, "body")
        entries = explanation_entries(problems, template)
        if entries:
            para("")
            para("해설", "heading")
            for heading, lines in entries:
                para(heading, "meta")
                for line in lines:
                    para(line, "body")
                para("")

    doc.save_to_path(str(path))


def _add_table(doc: "HwpxDocument", rows: list[list[str]]) -> None:
    if not rows or not any(rows):
        return
    row_cnt = len(rows)
    col_cnt = max(len(r) for r in rows)
    table = doc.add_table(row_cnt, col_cnt)
    for r, row in enumerate(rows):
        for c in range(col_cnt):
            value = row[c] if c < len(row) else ""
            table.set_cell_text(r, c, value)


def _add_picture(doc: "HwpxDocument", image_path: str, content_width: int) -> None:
    full_path = storage.DATA_DIR / image_path
    if not full_path.exists():
        return
    size = _picture_size(full_path, content_width)
    if size is None:
        return
    width, height = size
    fmt = _IMG_FORMATS.get(full_path.suffix.lower(), "png")
    doc.add_picture(full_path.read_bytes(), fmt, width=width, height=height)
