"""Teacher-facing review summary for the PDF -> editable HWPX export.

The independent editability/rendering audits used to reject the whole
document (HTTP 422) when one or two questions had a local defect. The export
route now delivers the file and reports, per question, what a teacher should
compare against the original in Hancom. Only fatal conditions stay 422 (see
``app.main._export_pdf_layout``).
"""
from __future__ import annotations

import re
from typing import Any

# kind -> (short label, one-line explanation)
KINDS: dict[str, tuple[str, str]] = {
    "math": ("수식", "수식 구조(분수·지수·근호 등)가 원본과 다를 수 있습니다"),
    "script": ("첨자", "위·아래 첨자가 일반 글자로 바뀌었을 수 있습니다"),
    "text": ("문장 누락", "문장 일부가 빠졌거나 글상자 밖에 놓였을 수 있습니다"),
    "picture": ("그림", "그림이 빠졌거나 다른 문항에 들어갔을 수 있습니다"),
    "box": ("글상자 크기", "글상자가 내용보다 작아 일부가 가려질 수 있습니다"),
    "passage": ("공통 지문", "문항 뒤 공통 지문 일부가 빠졌을 수 있습니다"),
    "paragraph": ("문단", "문단이 줄마다 끊겼거나 일부 글자가 빠졌을 수 있습니다"),
    "rendering": ("화면 표시", "일부 내용이 한글 화면에 보이지 않을 수 있습니다"),
}

# Document-level audit codes -> (kind covering it per question, teacher text).
DOCUMENT_CODES: dict[str, tuple[str | None, str]] = {
    "source_question_semantics_mismatch": ("math", "수식 구조"),
    "source_question_script_attachment_missing": ("script", "첨자"),
    "native_source_script_attachment_missing": ("script", "첨자"),
    "source_question_content_outside_its_box": ("text", "문항 글상자 안 문장"),
    "source_question_picture_outside_its_box": ("picture", "문항 그림"),
    "question_container_smaller_than_native_content": ("box", "문항 글상자 크기"),
    "source_shared_passage_not_preserved_outside_questions": ("passage", "공통 지문"),
    "source_paragraph_split_at_visual_line": ("paragraph", "문단 줄바꿈"),
    "source_paragraph_text_missing": ("paragraph", "문단 글자"),
    "text_in_drawing_boxes": ("*", "문항 글상자 구성"),
    "question_box_must_have_one_question": (None, "한 글상자에 문항이 하나씩 들어갔는지"),
    "question_number_mismatch": (None, "문항 번호"),
    "question_container_inventory_mismatch": (None, "문항 수"),
    "question_container_order_mismatch": (None, "문항 순서"),
    "native_source_text_missing": (None, "본문 글자 누락"),
    "native_source_fraction_missing": (None, "분수"),
    "source_figure_missing_from_output": (None, "그림 누락"),
    "native_source_running_header_missing": (None, "머리글·쪽 정보"),
    "source_paragraph_uses_hard_line_breaks": (None, "문단 줄바꿈"),
    "source_paragraph_word_spacing_changed": (None, "띄어쓰기"),
}
GENERIC_DOCUMENT_TEXT = "문서 구조 일부"
QUESTION_ID = re.compile(r"(?:question:)?v(\d+):q(\d+)$")
MAX_LISTED = 8


def _question_key(value: Any) -> str | None:
    match = QUESTION_ID.search(str(value or ""))
    return f"v{int(match[1])}:q{int(match[2]):02d}" if match else None


def _region_owner(regions: list[dict], page: Any, bbox: Any) -> str | None:
    """Return the question whose source region holds most of ``bbox``."""
    try:
        x0, y0, x1, y1 = (float(v) for v in bbox)
        page = int(page)
    except (TypeError, ValueError):
        return None
    best, best_area = None, 0.0
    for region in regions:
        if int(region.get("page") or 0) != page:
            continue
        try:
            rx0, ry0, rx1, ry1 = (float(v) for v in region.get("bbox") or ())
        except (TypeError, ValueError):
            continue
        area = max(0.0, min(x1, rx1) - max(x0, rx0)) * max(0.0, min(y1, ry1) - max(y0, ry0))
        if area > best_area:
            best, best_area = _question_key(region.get("id")), area
    return best


def _label(key: str, page: Any, multi_variant: bool) -> str:
    match = QUESTION_ID.search(key)
    number = int(match[2]) if match else key
    return f"{number}번({page}쪽)" if multi_variant and page else f"{number}번"


def build_export_review(editability: dict[str, Any], rendering: dict[str, Any] | None = None,
                        *, strict: bool = False) -> dict[str, Any]:
    units = editability.get("question_units") or {}
    regions = list(units.get("source_semantic_regions") or [])
    pages = {_question_key(r.get("id")): r.get("page") for r in regions}
    flagged: dict[str, dict[str, Any]] = {}

    def flag(key: str | None, kind: str, page: Any = None) -> bool:
        if not key:
            return False
        entry = flagged.setdefault(key, {"id": key, "page": pages.get(key) or page, "kinds": []})
        if entry["page"] is None and page is not None:
            entry["page"] = page
        if kind not in entry["kinds"]:
            entry["kinds"].append(kind)
        return True

    for item in units.get("wrong_question_semantics") or []:
        flag(_question_key(item.get("id")), "math")
    for item in units.get("wrong_question_script_attachments") or []:
        flag(_question_key(item.get("id")), "script")
    for item in units.get("missing_question_content") or []:
        flag(_question_key(item.get("id")), "text")
    for item in units.get("wrong_question_pictures") or []:
        flag(_question_key(item.get("id")), "picture")
    for item in units.get("wrong_question_geometry") or []:
        flag(_question_key(item.get("id")), "box")
    for item in units.get("wrong_shared_passages") or []:
        flag(_question_key(item.get("after_question")), "passage", item.get("source_page"))

    flow = editability.get("paragraph_flow") or {}
    unmapped_flow: dict[str, list[int]] = {}  # e.g. shared passages outside question boxes
    for code, field in (("source_paragraph_split_at_visual_line", "fragmented_paragraphs"),
                        ("source_paragraph_text_missing", "missing_text")):
        for record in flow.get(field) or []:
            owner = _region_owner(regions, record.get("page"), record.get("bbox"))
            if not flag(owner, "paragraph", record.get("page")):
                pages_seen = unmapped_flow.setdefault(code, [])
                if isinstance(record.get("page"), int) and record["page"] not in pages_seen:
                    pages_seen.append(record["page"])

    render_document: dict[str, str] = {}
    if rendering and rendering.get("ok") is False:
        for item in rendering.get("invisible_native_content") or []:
            if not flag(_question_key(item.get("question")), "rendering"):
                render_document["rendered_content_missing"] = "화면에 보이지 않는 내용"
        for code, fields, text in (
                ("rendered_text_missing", ("missing_rendered_text", "missing_rendered_inline_labels",
                                           "unassessed_svg_text_nodes"), "화면에 보이지 않는 글자"),
                ("rendered_picture_missing", ("missing_rendered_pictures", "missing_rendered_floating_pictures",
                                              "missing_rendered_backgrounds"), "화면에 보이지 않는 그림"),
                ("unsupported_nested_tables", ("unsupported_nested_tables",), "표 안의 표")):
            if any(rendering.get(field) for field in fields):
                render_document[code] = text

    flagged_kinds = {kind for entry in flagged.values() for kind in entry["kinds"]}
    document: dict[str, str] = {}
    for code in editability.get("issues") or []:
        kind, text = DOCUMENT_CODES.get(code, (None, GENERIC_DOCUMENT_TEXT))
        if kind == "*" and flagged:
            continue  # derived from question-unit failures already listed per question
        if kind in KINDS and kind in flagged_kinds and code not in unmapped_flow:
            continue
        if unmapped_flow.get(code):
            text += "(" + ", ".join(f"{page}쪽" for page in sorted(unmapped_flow[code])) + ")"
        document[code] = text
    document.update(render_document)

    multi_variant = any(not str(key).startswith("v1:") for key in units.get("question_ids") or [])
    # Page order is how a teacher walks through the printed exam.
    ordered = sorted(flagged.values(), key=lambda e: (int(e["page"] or 0), int(e["id"][1:e["id"].index(":")]), e["id"]))
    questions = []
    for entry in ordered:
        label = _label(entry["id"], entry["page"], multi_variant)
        questions.append({
            "id": entry["id"],
            "label": label,
            "page": entry["page"],
            "issues": entry["kinds"],
            "issue_labels": [KINDS[kind][0] for kind in entry["kinds"]],
            "summary": f"{label}: " + " / ".join(KINDS[kind][1] for kind in entry["kinds"]),
        })

    labels = [q["label"] for q in questions]
    listed = ", ".join(labels[:MAX_LISTED]) + (f" 외 {len(labels) - MAX_LISTED}개" if len(labels) > MAX_LISTED else "")
    categories = "·".join(dict.fromkeys(label for q in questions for label in q["issue_labels"]))
    document_texts = list(dict.fromkeys(document.values()))
    message = headline = ""
    if questions:
        headline = f"확인 필요 문항 {len(questions)}개: {listed} ({categories})"
        message = (f"문항 {len(questions)}개는 수식·문단 복원이 불완전할 수 있습니다. "
                   f"한글에서 {listed} 문항을 원본과 비교해 확인하세요.")
    if document_texts:
        detail = ", ".join(document_texts)
        if questions:
            message += f" 문서 전체 점검에서도 확인할 부분이 있습니다: {detail}."
        else:
            headline = f"확인 필요: {detail}"
            message = f"문서 일부의 복원이 불완전할 수 있습니다: {detail}. 한글에서 원본과 비교해 확인하세요."
    return {
        "ok": not questions and not document,
        "strict": strict,
        "flag_count": len(questions),
        "flagged_questions": questions,
        "document_issues": [{"code": code, "summary": text} for code, text in document.items()],
        "headline": headline,
        "message": message,
    }
