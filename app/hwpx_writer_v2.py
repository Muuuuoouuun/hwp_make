"""python-hwpx(airmang, vendored) 기반 HWPX 작성기 — 시범 포팅(평가용).

기존 hwpx_writer.py는 HWPX를 문자열 템플릿으로 손수 직렬화한다. 이 모듈은
동일한 write_hwpx 시그니처를 vendored python-hwpx 고수준 API로 재구현해
출력/렌더 호환성을 비교하기 위한 실험본이다. 아직 main.py에 연결하지 않는다.
"""
from __future__ import annotations

import html
import os
import re
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image

# vendored python-hwpx (app/_vendor/hwpx). 내부적으로 `import hwpx` 절대경로를
# 쓰므로 _vendor 디렉터리를 sys.path에 얹어 top-level 패키지로 노출한다.
_VENDOR = Path(__file__).resolve().parent / "_vendor"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))
from hwpx import HwpxDocument  # noqa: E402

from . import layout_model, storage  # noqa: E402
from .exam_templates import (  # noqa: E402
    ANSWER_SHEET_TITLE,
    ExamTemplate,
    answer_blank_text,
    explanation_entries,
    format_answer,
    get_template,
    needs_answer_blank,
    quick_answer_lines,
    resolve_export_title,
)
from .hwpx_writer import (  # noqa: E402  (포맷 로직 재사용)
    COLUMN_GAP,
    MAX_IMAGE_WIDTH,
    PX_TO_HWPUNIT,
    SOURCE_MARKER_RE,
    _equation_size,
    _equation_placeholder,
    _format_choice,
    _hancom_eqn_script,
    _native_math_height,
    _strip_question_prefix,
)
from .math_text import split_math_text  # noqa: E402

# 기존 CHAR_HEIGHTS(HWPUNIT)를 포인트로 환산: height = pt * 100.
PT_TITLE = 16.0    # char 1 (1600)
PT_META = 12.5     # char 3 (1250)
PT_HEADING = 11.5  # char 2 (1150)
PT_BODY = 10.0     # char 0 (1000)
PT_SMALL = 9.0     # char 4 (900)

_IMG_FORMATS = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".gif": "gif", ".bmp": "bmp"}
_HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
_HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
_SECTION_PART_RE = re.compile(r"^Contents/section\d+\.xml$")
_PARAGRAPH_XML_RE = re.compile(r"<hp:p\b[\s\S]*?</hp:p>")
_LINESEG_XML_RE = re.compile(r"<hp:linesegarray\b[\s\S]*?</hp:linesegarray>")
_SCRIPT_XML_RE = re.compile(r"<hp:script>([\s\S]*?)</hp:script>")
_PASSAGE_LABEL_RE = re.compile(r"^\s*\[\s*\d{1,2}\s*[~∼\-–]\s*\d{1,2}\s*\]\s*$")

_STYLE_SPECS = {
    "title": {"size": PT_TITLE, "bold": True},
    "meta": {"size": PT_META},
    "heading": {"size": PT_HEADING, "bold": True},
    "body": {"size": PT_BODY},
    "small": {"size": PT_SMALL},
}

_STYLE_LINE_HEIGHTS = {
    "title": int(PT_TITLE * 125),
    "meta": int(PT_META * 125),
    "heading": int(PT_HEADING * 125),
    "body": int(PT_BODY * 125),
    "small": int(PT_SMALL * 125),
}

_KICE_FONT_FACES = (
    "신명 중명조",
    "한양신명조",
    "HY신명조",
    "Times New Roman",
    "돋움",
    "중고딕",
    "신명 중고딕",
    "HancomEQN",
)

_KICE_STYLE_SPECS = {
    "title": {"size": 16.0, "bold": True, "font": "돋움"},
    "meta": {"size": 11.0, "font": "돋움"},
    "heading": {"size": 11.0, "bold": True, "font": "돋움"},
    "body": {"size": 11.0, "font": "신명 중명조"},
    "small": {"size": 9.5, "font": "돋움"},
}

_KICE_ENGLISH_STYLE_SPECS = {
    **_KICE_STYLE_SPECS,
    "body": {"size": 11.0, "font": "Times New Roman"},
}

_KICE_STYLE_LINE_HEIGHTS = {
    "title": int(16.0 * 165),
    "meta": int(11.0 * 165),
    "heading": int(11.0 * 165),
    "body": int(11.0 * 165),
    "small": int(9.5 * 165),
}

# rhwp-verified flow budget for native-math two-column KICE exports.
#
# The physical A4 body is about 65762 HWPUNIT, but equations and tables render
# taller than the lightweight Python estimator. 46000 keeps the real HWP math
# samples compact while leaving enough bottom margin to avoid layout overflow.
KICE_MATH_COLUMN_BODY_HEIGHT = 46000


def _local_name(tag: Any) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _is_kice_template(template: ExamTemplate) -> bool:
    return str(template.key or "").startswith("kice_")


def _style_specs_for_template(template: ExamTemplate) -> dict[str, dict[str, Any]]:
    if not _is_kice_template(template):
        return _STYLE_SPECS
    if template.key == "kice_english":
        return _KICE_ENGLISH_STYLE_SPECS
    return _KICE_STYLE_SPECS


def _style_line_heights_for_template(template: ExamTemplate) -> dict[str, int]:
    return _KICE_STYLE_LINE_HEIGHTS if _is_kice_template(template) else _STYLE_LINE_HEIGHTS


def _ensure_header_font_face(header: Any, face: str) -> None:
    changed = False
    for fontface in header.element.findall(f".//{_HH}fontface"):
        fonts = fontface.findall(f"{_HH}font")
        if any(font.get("face") == face for font in fonts):
            continue
        next_id = 0
        for font in fonts:
            try:
                next_id = max(next_id, int(font.get("id") or 0) + 1)
            except ValueError:
                continue
        new_font = fontface.makeelement(
            f"{_HH}font",
            {
                "id": str(next_id),
                "face": face,
                "type": "TTF",
                "isEmbedded": "0",
            },
        )
        fontface.append(new_font)
        fontface.set("fontCnt", str(len(fontface.findall(f"{_HH}font"))))
        changed = True
    fontfaces = header.element.find(f".//{_HH}fontfaces")
    if fontfaces is not None:
        fontfaces.set("itemCnt", str(len(fontfaces.findall(f"{_HH}fontface"))))
    if changed:
        header.mark_dirty()


def _ensure_kice_font_faces(header: Any) -> None:
    for face in _KICE_FONT_FACES:
        _ensure_header_font_face(header, face)


def _ensure_char_metric_child(char_pr: Any, local_name: str) -> Any:
    child = char_pr.find(f"{_HH}{local_name}")
    if child is not None:
        return child
    child = char_pr.makeelement(f"{_HH}{local_name}", {})
    order = ["fontRef", "ratio", "spacing", "relSz", "offset"]
    target_index = order.index(local_name)
    insert_at = 0
    for index, existing in enumerate(list(char_pr)):
        existing_local = _local_name(existing.tag)
        if existing_local in order and order.index(existing_local) < target_index:
            insert_at = index + 1
    char_pr.insert(insert_at, child)
    return child


def _apply_char_metrics(header: Any, char_pr_ids: list[str], *, ratio: int, spacing: int) -> None:
    changed = False
    lang_attrs = ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")
    for char_pr_id in sorted(set(str(value) for value in char_pr_ids if value is not None)):
        char_pr = header.element.find(f".//{_HH}charPr[@id='{char_pr_id}']")
        if char_pr is None:
            continue
        for local_name, value in (("ratio", ratio), ("spacing", spacing)):
            child = _ensure_char_metric_child(char_pr, local_name)
            for attr in lang_attrs:
                safe_value = str(int(value))
                if child.get(attr) != safe_value:
                    child.set(attr, safe_value)
                    changed = True
    if changed:
        header.mark_dirty()


def _math_style_spec(spec: dict[str, Any]) -> dict[str, Any]:
    math_spec = {key: value for key, value in spec.items() if key != "font"}
    math_spec["font"] = "HancomEQN"
    math_spec["color"] = "#111111"
    return math_spec


def _set_paragraph_lineseg(paragraph: Any, height: int) -> None:
    element = paragraph.element
    for child in list(element):
        if _local_name(child.tag).lower() == "linesegarray":
            element.remove(child)
    line_seg_array = element.makeelement(f"{_HP}linesegarray", {})
    line_seg_array.append(
        element.makeelement(
            f"{_HP}lineseg",
            {
                "textpos": "0",
                "vertpos": "0",
                "vertsize": str(height),
                "textheight": str(height),
                "baseline": str(int(height * 0.85)),
                "spacing": str(int(height * 0.6)),
                "horzpos": "0",
                "horzsize": str(MAX_IMAGE_WIDTH),
                "flags": "393216",
            },
        )
    )
    element.append(line_seg_array)


def _lineseg_xml(height: int) -> str:
    return (
        '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" '
        f'vertsize="{height}" textheight="{height}" baseline="{int(height * 0.85)}" '
        f'spacing="{int(height * 0.6)}" horzpos="0" horzsize="{MAX_IMAGE_WIDTH}" '
        'flags="393216"/></hp:linesegarray>'
    )


def _patch_section_math_linesegs(xml: str) -> tuple[str, int]:
    replacements = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal replacements
        paragraph = match.group(0)
        if "<hp:equation" not in paragraph:
            return paragraph
        scripts = [html.unescape(value) for value in _SCRIPT_XML_RE.findall(paragraph)]
        if not scripts:
            return paragraph
        height = max(1200, *(_equation_size(script)[1] for script in scripts))
        patched = _LINESEG_XML_RE.sub("", paragraph)
        patched = patched.replace("</hp:p>", _lineseg_xml(height) + "</hp:p>", 1)
        if patched != paragraph:
            replacements += 1
        return patched

    return _PARAGRAPH_XML_RE.sub(replace, xml), replacements


def _patch_hwpx_native_math_linesegs(path: Path) -> int:
    updates: dict[str, bytes] = {}
    total = 0
    with zipfile.ZipFile(path, "r") as archive:
        infos = archive.infolist()
        payloads = {info.filename: archive.read(info.filename) for info in infos}
    for name, data in payloads.items():
        if not _SECTION_PART_RE.match(name):
            continue
        xml = data.decode("utf-8")
        patched, count = _patch_section_math_linesegs(xml)
        if count:
            updates[name] = patched.encode("utf-8")
            total += count
    if not updates:
        return 0

    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=path.suffix + ".tmp")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp_path, "w") as out:
            for info in infos:
                out.writestr(info, updates.get(info.filename, payloads[info.filename]))
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
    return total


def _is_passage_label(label: Any) -> bool:
    return bool(_PASSAGE_LABEL_RE.match(str(label or "")))


def _visual_units(text: str) -> int:
    total = 0
    for char in text:
        if char.isspace():
            total += 1
        elif unicodedata.east_asian_width(char) in {"W", "F", "A"}:
            total += 2
        else:
            total += 1
    return total


def _math_segment_units(segment: str, is_math: bool) -> int:
    if is_math:
        script = _hancom_eqn_script(segment)
        if script:
            width, _ = _equation_size(script)
            return max(3, min(28, width // 650))
    return _visual_units(segment)


def _is_display_math_script(script: str | None, *, block_complex_math: bool = True) -> bool:
    if not script or not block_complex_math:
        return False
    compact = script.replace(" ", "")
    multiline_tokens = ("cases{", "matrix{", "pmatrix{", "bmatrix{", "eqalign{")
    nary_tokens = ("int", "sum", "prod", "lim")
    tall_inline_tokens = (" over ", "sqrt", "choose")
    structural_tokens = multiline_tokens + nary_tokens
    if len(compact) <= 14 and not any(token in script for token in structural_tokens):
        return False
    width, _ = _equation_size(script)
    if any(token in script for token in multiline_tokens):
        return True
    if any(token in script for token in tall_inline_tokens) and width <= 14000:
        return False
    return (
        any(token in script for token in structural_tokens)
        or width > 20000
    )


def _wrap_math_line_parts(line: str, limit: int) -> list[str]:
    tokens: list[tuple[str, int]] = []
    for segment, is_math in split_math_text(line):
        if not segment:
            continue
        if is_math:
            tokens.append((segment, _math_segment_units(segment, True)))
            continue
        for token in re.findall(r"\S+\s*", segment):
            tokens.append((token, _visual_units(token)))

    wrapped: list[str] = []
    current: list[str] = []
    current_units = 0
    for token, units in tokens:
        if current and current_units + units > limit:
            wrapped.append("".join(current).strip())
            current = []
            current_units = 0
        current.append(token)
        current_units += units
    if current:
        wrapped.append("".join(current).strip())
    return [part for part in wrapped if part]


def _table_cell_render_lines(text: str, limit: int) -> list[str]:
    lines: list[str] = []
    for raw_line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n") or [""]:
        raw_line = raw_line.strip()
        if not raw_line:
            lines.append("")
            continue
        parts = [(segment, is_math) for segment, is_math in split_math_text(raw_line) if segment]
        scripts = [_hancom_eqn_script(segment) if is_math else None for segment, is_math in parts]
        if not any(_is_display_math_script(script) for script in scripts):
            lines.extend(_wrap_math_line_parts(raw_line, limit) or [raw_line])
            continue

        buffer: list[str] = []

        def flush_buffer() -> None:
            buffered = "".join(buffer).strip()
            buffer.clear()
            if buffered:
                lines.extend(_wrap_math_line_parts(buffered, limit) or [buffered])

        for (segment, is_math), script in zip(parts, scripts):
            if is_math and _is_display_math_script(script):
                flush_buffer()
                lines.append(segment.strip())
            else:
                buffer.append(segment)
        flush_buffer()
    return lines or [""]


def _picture_size(full_path: Path, max_width: int, max_height: int | None = None) -> tuple[int, int] | None:
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
    if max_height is not None and height > max_height:
        width = int(width * max_height / height)
        height = max_height
    return width, height


def _append_equation_run(
    paragraph: Any,
    script: str,
    char_pr_id_ref: str,
    equation_index: int,
) -> None:
    run = paragraph.add_run("", char_pr_id_ref=char_pr_id_ref).element
    for child in list(run):
        run.remove(child)
    equation = run.makeelement(
        f"{_HP}equation",
        {
            "id": str(1000000000 + equation_index),
            "zOrder": str(equation_index),
            "numberingType": "EQUATION",
            "textWrap": "TOP_AND_BOTTOM",
            "textFlow": "BOTH_SIDES",
            "lock": "0",
            "dropcapstyle": "None",
            "version": "Equation Version 60",
            "baseLine": "0",
            "textColor": "#000000",
            "baseUnit": "1000",
            "lineMode": "CHAR",
            "font": "HancomEQN",
        },
    )
    equation.append(
        equation.makeelement(
            f"{_HP}sz",
            {
                "width": "0",
                "widthRelTo": "ABSOLUTE",
                "height": "0",
                "heightRelTo": "ABSOLUTE",
                "protect": "0",
            },
        )
    )
    equation.append(
        equation.makeelement(
            f"{_HP}pos",
            {
                "treatAsChar": "1",
                "affectLSpacing": "0",
                "flowWithText": "1",
                "allowOverlap": "0",
                "holdAnchorAndSO": "0",
                "vertRelTo": "PARA",
                "horzRelTo": "PARA",
                "vertAlign": "TOP",
                "horzAlign": "LEFT",
                "vertOffset": "0",
                "horzOffset": "0",
            },
        )
    )
    equation.append(
        equation.makeelement(
            f"{_HP}outMargin",
            {"left": "56", "right": "56", "top": "0", "bottom": "0"},
        )
    )
    comment = equation.makeelement(f"{_HP}shapeComment", {})
    comment.text = "수식입니다."
    equation.append(comment)
    script_node = equation.makeelement(f"{_HP}script", {})
    script_node.text = script
    equation.append(script_node)
    run.append(equation)
    placeholder = run.makeelement(f"{_HP}t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"})
    placeholder.text = _equation_placeholder(script)
    run.append(placeholder)


def _replace_paragraph_runs(
    paragraph: Any,
    text: str,
    *,
    char_pr_id_ref: str,
    math_char_pr_id_ref: str,
    native_math: bool,
    equation_counter: list[int],
    min_line_height: int = 1000,
) -> None:
    for child in list(paragraph.element):
        if str(child.tag).endswith("}run") or child.tag == "run":
            paragraph.element.remove(child)

    wrote = False
    for segment, is_math in split_math_text(text):
        if native_math and is_math:
            script = _hancom_eqn_script(segment)
            if script:
                equation_counter[0] += 1
                _append_equation_run(paragraph, script, char_pr_id_ref, equation_counter[0])
                wrote = True
                continue
        paragraph.add_run(
            segment,
            char_pr_id_ref=math_char_pr_id_ref if is_math else char_pr_id_ref,
        )
        wrote = True
    if not wrote:
        paragraph.add_run("", char_pr_id_ref=char_pr_id_ref)
    para_height = min_line_height
    if native_math:
        math_height = _native_math_height(text)
        if math_height:
            para_height = max(para_height, math_height)
    _set_paragraph_lineseg(paragraph, para_height)


def _set_table_cell_rich_text(
    table: Any,
    row_index: int,
    col_index: int,
    text: str,
    *,
    char_pr_id_ref: str,
    math_char_pr_id_ref: str,
    native_math: bool,
    equation_counter: list[int],
    cell_para_pr_id_ref: str | None = None,
    min_line_height: int = 1000,
    cell_line_limit: int = 46,
) -> None:
    cell = table.cell(row_index, col_index)
    lines = _table_cell_render_lines(text, cell_line_limit)
    cell.set_text("", split_paragraphs=True)
    for line_index, line in enumerate(lines):
        paragraphs = cell.paragraphs
        paragraph = (
            paragraphs[0]
            if line_index == 0 and paragraphs
            else cell.add_paragraph("", char_pr_id_ref=char_pr_id_ref)
        )
        _replace_paragraph_runs(
            paragraph,
            line,
            char_pr_id_ref=char_pr_id_ref,
            math_char_pr_id_ref=math_char_pr_id_ref,
            native_math=native_math,
            equation_counter=equation_counter,
            min_line_height=min_line_height,
        )
        if cell_para_pr_id_ref is not None:
            try:
                paragraph.element.set("paraPrIDRef", cell_para_pr_id_ref)
            except Exception:
                pass
    # 셀 문단은 기본 paraPr(양쪽정렬)이라 지문 같은 긴 텍스트가 글자 사이가 벌어진다.
    # 좌측정렬 paraPr 로 바꿔 원본 문제지처럼 자연스럽게 읽히게 한다.
    cell.element.set("dirty", "1")
    table.mark_dirty()


def write_hwpx(
    path: Path,
    title: str,
    problems: list[dict[str, Any]],
    template_key: str = "basic",
    include_answer_sheet: bool = False,
    native_math: bool = False,
) -> None:
    template = get_template(template_key)
    title = resolve_export_title(title, template)
    recognized_columns = layout_model.recognized_column_count(problems)
    columns = recognized_columns or max(1, min(template.columns, 2))
    content_width = (
        (MAX_IMAGE_WIDTH - COLUMN_GAP * (columns - 1)) // columns
        if columns > 1
        else MAX_IMAGE_WIDTH
    )

    doc = HwpxDocument.new()
    header = doc.headers[0]
    if _is_kice_template(template):
        _ensure_kice_font_faces(header)
    style_specs = _style_specs_for_template(template)
    style_line_heights = _style_line_heights_for_template(template)

    # paraPr(정렬) / charPr(크기) 참조를 한 번씩만 만들어 재사용한다.
    if _is_kice_template(template):
        pr_left = header.ensure_paragraph_format(alignment="LEFT", line_spacing_percent=165)
        pr_center = header.ensure_paragraph_format(alignment="CENTER", line_spacing_percent=165)
        pr_right = header.ensure_paragraph_format(alignment="RIGHT", line_spacing_percent=165)
    else:
        pr_left = header.ensure_paragraph_alignment("LEFT")
        pr_center = header.ensure_paragraph_alignment("CENTER")
        pr_right = header.ensure_paragraph_alignment("RIGHT")
    cp = {name: doc.ensure_run_style(**spec) for name, spec in style_specs.items()}
    math_cp = {name: doc.ensure_run_style(**_math_style_spec(spec)) for name, spec in style_specs.items()}
    if _is_kice_template(template):
        _apply_char_metrics(header, list(cp.values()), ratio=95, spacing=-5)
    equation_counter = [0]
    flow_y = 0
    pending_column_break = False
    column_body_height = KICE_MATH_COLUMN_BODY_HEIGHT
    math_picture_max_height = (
        int(column_body_height * 0.45)
        if native_math and template.key == "kice_math" and columns > 1
        else None
    )

    def add_single_para(
        text: str,
        style: str = "body",
        center: bool = False,
        right: bool = False,
        *,
        math_enabled: bool = True,
        allow_column_break: bool = True,
        **attrs: str,
    ) -> None:
        nonlocal flow_y, pending_column_break
        para_height = style_line_heights.get(style, 1000)
        if native_math and math_enabled:
            para_height = max(para_height, _native_math_height(str(text or "")))
        if (
            columns > 1
            and not str(text or "").strip()
            and not attrs
            and flow_y > column_body_height - 2500
        ):
            pending_column_break = True
            return
        if pending_column_break and allow_column_break:
            attrs.setdefault("columnBreak", "1")
            pending_column_break = False
            flow_y = 0
        elif pending_column_break:
            pending_column_break = False
        elif columns > 1 and allow_column_break and flow_y > 0 and flow_y + para_height > column_body_height:
            attrs.setdefault("columnBreak", "1")
            flow_y = 0
        if attrs.get("pageBreak") == "1" or attrs.get("columnBreak") == "1":
            flow_y = 0
        para_pr = pr_right if right else pr_center if center else pr_left
        paragraph = doc.add_paragraph(
            "",
            para_pr_id_ref=para_pr,
            char_pr_id_ref=cp[style],
            include_run=False,
            inherit_style=False,
            **attrs,
        )
        _replace_paragraph_runs(
            paragraph,
            str(text or ""),
            char_pr_id_ref=cp[style],
            math_char_pr_id_ref=math_cp[style],
            native_math=native_math and math_enabled,
            equation_counter=equation_counter,
            min_line_height=style_line_heights.get(style, 1000),
        )
        flow_y += para_height

    def visual_units(text: str) -> int:
        return _visual_units(text)

    def segment_units(segment: str, is_math: bool) -> int:
        return _math_segment_units(segment, is_math)

    def wrap_line_parts(line: str, limit: int) -> list[str]:
        return _wrap_math_line_parts(line, limit)

    def wrapped_choice_lines(choices: list[str], limit: int = 48) -> list[str]:
        gap = "\u3000\u3000"
        gap_units = visual_units(gap)
        lines: list[str] = []
        current: list[str] = []
        current_units = 0
        for choice in choices:
            choice_units = sum(
                segment_units(segment, is_math)
                for segment, is_math in split_math_text(choice)
                if segment
            )
            if current and (len(current) >= 3 or current_units + gap_units + choice_units > limit):
                lines.append(gap.join(current))
                current = [choice]
                current_units = choice_units
            else:
                if current:
                    current_units += gap_units
                current.append(choice)
                current_units += choice_units
        if current:
            lines.append(gap.join(current))
        return lines or [""]

    def add_wrapped_line(
        line: str,
        style: str,
        *,
        center: bool = False,
        right: bool = False,
        math_enabled: bool = True,
        allow_column_break: bool = True,
        **attrs: str,
    ) -> None:
        if not (columns > 1 and not center and not right and style in {"heading", "body", "small"}):
            add_single_para(
                line,
                style,
                center=center,
                right=right,
                math_enabled=math_enabled,
                allow_column_break=allow_column_break,
                **attrs,
            )
            return
        limits = {"heading": 44, "body": 48, "small": 56}
        for wrapped in wrap_line_parts(line, limits.get(style, 48)):
            add_single_para(
                wrapped,
                style,
                center=center,
                right=right,
                math_enabled=math_enabled,
                allow_column_break=allow_column_break,
                **attrs,
            )

    def para(
        text: str,
        style: str = "body",
        center: bool = False,
        right: bool = False,
        *,
        math_blocks: bool = False,
        block_complex_math: bool = True,
        allow_column_break: bool = True,
        **attrs: str,
    ) -> None:
        value = str(text or "")
        if native_math and math_blocks:
            emitted = False
            for raw_line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                line = raw_line.strip()
                if not line:
                    continue

                parts = [(segment, is_math) for segment, is_math in split_math_text(line) if segment]
                scripts = [
                    _hancom_eqn_script(segment) if is_math else None
                    for segment, is_math in parts
                ]
                has_native_math = any(scripts)
                if not has_native_math:
                    add_wrapped_line(
                        line,
                        style,
                        center=center,
                        right=right,
                        math_enabled=False,
                        allow_column_break=allow_column_break,
                        **attrs,
                    )
                    emitted = True
                    continue

                math_only_line = all(is_math or not segment.strip() for segment, is_math in parts)
                if math_only_line:
                    add_single_para(
                        line,
                        style,
                        center=True,
                        math_enabled=True,
                        allow_column_break=allow_column_break,
                        **attrs,
                    )
                    emitted = True
                    continue

                def is_display_script(script: str | None) -> bool:
                    return _is_display_math_script(script, block_complex_math=block_complex_math)

                if not any(is_display_script(script) for script in scripts):
                    add_wrapped_line(
                        line,
                        style,
                        center=center,
                        right=right,
                        math_enabled=True,
                        allow_column_break=allow_column_break,
                        **attrs,
                    )
                    emitted = True
                    continue

                buffer: list[str] = []

                def flush_buffer() -> None:
                    nonlocal emitted
                    buffered = "".join(buffer).strip()
                    buffer.clear()
                    if buffered:
                        add_wrapped_line(
                            buffered,
                            style,
                            center=center,
                            right=right,
                            math_enabled=True,
                            allow_column_break=allow_column_break,
                            **attrs,
                        )
                        emitted = True

                for (segment, is_math), script in zip(parts, scripts):
                    if is_math and is_display_script(script):
                        flush_buffer()
                        add_single_para(
                            segment.strip(),
                            style,
                            center=True,
                            math_enabled=True,
                            allow_column_break=allow_column_break,
                            **attrs,
                        )
                        emitted = True
                    else:
                        buffer.append(segment)
                flush_buffer()
            if emitted:
                return
        add_single_para(
            text,
            style,
            center=center,
            right=right,
            math_enabled=True,
            allow_column_break=allow_column_break,
            **attrs,
        )

    def has_math(text: str) -> bool:
        return any(is_math for _, is_math in split_math_text(text))

    def has_complex_choice_math(text: str) -> bool:
        for segment, is_math in split_math_text(text):
            if not is_math:
                continue
            script = _hancom_eqn_script(segment)
            if not script:
                continue
            width, _ = _equation_size(script)
            compact = script.replace(" ", "")
            if any(token in script for token in ("cases{", "matrix{", "pmatrix{", "bmatrix{", "eqalign{")):
                return True
            if any(token in script for token in ("int", "sum", "prod", "lim")):
                return True
            if width > 12000 or len(compact) > 34:
                return True
        return False

    def estimate_single_para_height(text: str, style: str = "body", *, math_enabled: bool = True) -> int:
        height = style_line_heights.get(style, 1000)
        if native_math and math_enabled:
            height = max(height, _native_math_height(str(text or "")))
        return height

    def estimate_wrapped_line_height(
        line: str,
        style: str,
        *,
        center: bool = False,
        right: bool = False,
        math_enabled: bool = True,
    ) -> int:
        if not (columns > 1 and not center and not right and style in {"heading", "body", "small"}):
            return estimate_single_para_height(line, style, math_enabled=math_enabled)
        limits = {"heading": 44, "body": 48, "small": 56}
        parts = wrap_line_parts(line, limits.get(style, 48))
        if not parts:
            return 0
        return sum(estimate_single_para_height(part, style, math_enabled=math_enabled) for part in parts)

    def estimate_para_height(
        text: str,
        style: str = "body",
        *,
        center: bool = False,
        right: bool = False,
        math_blocks: bool = False,
        block_complex_math: bool = True,
    ) -> int:
        value = str(text or "")
        if not (native_math and math_blocks):
            return estimate_single_para_height(value, style)

        total = 0
        for raw_line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            parts = [(segment, is_math) for segment, is_math in split_math_text(line) if segment]
            scripts = [_hancom_eqn_script(segment) if is_math else None for segment, is_math in parts]
            if not any(scripts):
                total += estimate_wrapped_line_height(
                    line, style, center=center, right=right, math_enabled=False
                )
                continue
            if all(is_math or not segment.strip() for segment, is_math in parts):
                total += estimate_single_para_height(line, style)
                continue

            def is_display_script(script: str | None) -> bool:
                return _is_display_math_script(script, block_complex_math=block_complex_math)

            if not any(is_display_script(script) for script in scripts):
                total += estimate_wrapped_line_height(
                    line, style, center=center, right=right, math_enabled=True
                )
                continue

            buffer: list[str] = []
            for (segment, is_math), script in zip(parts, scripts):
                if is_math and is_display_script(script):
                    buffered = "".join(buffer).strip()
                    buffer.clear()
                    if buffered:
                        total += estimate_wrapped_line_height(
                            buffered, style, center=center, right=right, math_enabled=True
                        )
                    total += estimate_single_para_height(segment.strip(), style)
                else:
                    buffer.append(segment)
            buffered = "".join(buffer).strip()
            if buffered:
                total += estimate_wrapped_line_height(
                    buffered, style, center=center, right=right, math_enabled=True
                )
        return total

    def estimate_table_height(rows: list[list[str]]) -> int:
        if not rows or not any(rows):
            return 0
        col_count = max(1, max(len(row) for row in rows))
        cell_line_limit = max(16, 46 // col_count)
        total = 800
        for row in rows:
            row_height = 1300
            for cell in row:
                cell_text = str(cell or "")
                cell_height = 0
                for part in _table_cell_render_lines(cell_text, cell_line_limit):
                    cell_height += estimate_para_height(
                        part,
                        "body",
                        math_blocks=native_math and template.key == "kice_math",
                    )
                row_height = max(row_height, cell_height + 700)
            total += row_height
        return total + 800

    def estimate_picture_height(image_path: str) -> int:
        full_path = storage.DATA_DIR / image_path
        size = _picture_size(full_path, content_width, math_picture_max_height)
        if size is None:
            return 0
        return size[1] + 600

    def reserve_object_height(height: int) -> dict[str, str]:
        nonlocal flow_y
        attrs: dict[str, str] = {}
        if columns > 1 and height > 0 and flow_y > 0 and flow_y + height > column_body_height:
            attrs["columnBreak"] = "1"
            flow_y = 0
        flow_y += height
        return attrs

    def choice_visual_units(choice: str) -> int:
        return sum(
            segment_units(segment, is_math)
            for segment, is_math in split_math_text(choice)
            if segment
        )

    def use_choice_grid(choices: list[str]) -> bool:
        return (
            native_math
            and template.key == "kice_math"
            and bool(choices)
            and any(has_math(choice) for choice in choices)
        )

    def choice_grid_columns(choices: list[str]) -> int:
        max_units = max((choice_visual_units(choice) for choice in choices), default=0)
        return 2 if max_units > 14 else 3

    def estimate_choice_grid_height(choices: list[str]) -> int:
        col_count = choice_grid_columns(choices)
        row_count = max(1, (len(choices) + col_count - 1) // col_count)
        return row_count * 2200 + 200

    def add_choice_grid(choices: list[str]) -> None:
        if not choices:
            return
        col_count = choice_grid_columns(choices)
        row_count = (len(choices) + col_count - 1) // col_count
        table_height = estimate_choice_grid_height(choices)
        table = doc.add_table(
            row_count,
            col_count,
            char_pr_id_ref=cp["body"],
            width=content_width,
            height=table_height,
            border_fill_id_ref="1",
            **reserve_object_height(table_height),
        )
        try:
            base = content_width // col_count
            widths = [base] * col_count
            widths[-1] = content_width - base * (col_count - 1)
            table.set_column_widths(widths)
        except Exception:
            pass
        for row_index in range(row_count):
            for col_index in range(col_count):
                choice_index = row_index * col_count + col_index
                text = choices[choice_index] if choice_index < len(choices) else ""
                _set_table_cell_rich_text(
                    table,
                    row_index,
                    col_index,
                    text,
                    char_pr_id_ref=cp["body"],
                    math_char_pr_id_ref=math_cp["body"],
                    native_math=native_math,
                    equation_counter=equation_counter,
                    cell_para_pr_id_ref=pr_left,
                    min_line_height=style_line_heights["body"],
                    cell_line_limit=24,
                )

    def estimate_problem_height(problem: dict[str, Any], index: int) -> int:
        label = problem.get("number") or str(index)
        subject = problem.get("subject") or ""
        unit = problem.get("unit") or ""
        source_marker = unit if SOURCE_MARKER_RE.match(str(unit)) else ""
        meta_unit = "" if source_marker else unit
        meta = " / ".join(p for p in [subject, meta_unit] if p)
        stem_lines = (problem.get("stem") or "").splitlines()
        is_passage_block = _is_passage_label(label) and not problem.get("choices")
        total = 0
        if is_passage_block:
            total += estimate_para_height(stem_lines[0] if stem_lines else label, "heading")
            for line in stem_lines[1:]:
                total += estimate_para_height(line, "body")
        elif template.merge_question_number:
            first_line = _strip_question_prefix(stem_lines[0], label) if stem_lines else ""
            total += estimate_para_height(
                f"{label}. {first_line or problem.get('title') or '문제'}",
                "heading",
                math_blocks=native_math and template.key == "kice_math",
            )
            for line in stem_lines[1:]:
                total += estimate_para_height(
                    line,
                    "body",
                    math_blocks=native_math and template.key == "kice_math",
                )
            if meta:
                total += estimate_para_height(f"[{meta}]", "small")
        else:
            heading = f"{label}. {problem.get('title') or '문제'}"
            if meta:
                heading += f" [{meta}]"
            total += estimate_para_height(
                heading,
                "heading",
                math_blocks=native_math and template.key == "kice_math",
            )
            for line in stem_lines or [""]:
                total += estimate_para_height(
                    line,
                    "body",
                    math_blocks=native_math and template.key == "kice_math",
                )
        for rows in problem.get("tables") or []:
            total += estimate_table_height(rows)
        for image_path in problem.get("image_paths") or []:
            total += estimate_picture_height(image_path)
        if source_marker:
            total += estimate_para_height(source_marker, "small", right=True)
        choices = [
            _format_choice(ci, choice, template)
            for ci, choice in enumerate(problem.get("choices") or [], start=1)
        ]
        choices_have_complex_math = any(has_complex_choice_math(choice) for choice in choices)
        if choices and use_choice_grid(choices):
            total += estimate_choice_grid_height(choices)
        elif (
            choices
            and template.inline_short_choices
            and sum(len(c) for c in choices) <= 90
            and not choices_have_complex_math
        ):
            for choice_line in wrapped_choice_lines(choices):
                total += estimate_para_height(
                    choice_line,
                    "body",
                    math_blocks=native_math and template.key == "kice_math",
                    block_complex_math=False,
                )
        else:
            for choice in choices:
                total += estimate_para_height(
                    choice,
                    "body",
                    math_blocks=native_math and template.key == "kice_math",
                    block_complex_math=False,
                )
        if needs_answer_blank(problem, template):
            total += estimate_para_height(answer_blank_text(template), "body")
        if template.include_answers and problem.get("answer"):
            total += estimate_para_height(f"정답: {format_answer(problem, template)}", "body")
        if template.include_explanations and problem.get("explanation"):
            total += estimate_para_height(f"해설: {problem['explanation']}", "body")
        total += estimate_para_height("", "body")
        return total

    def split_table_tail_lines(stem_lines: list[str], has_tables: bool) -> tuple[list[str], list[str]]:
        if not has_tables or len(stem_lines) < 2:
            return stem_lines, []
        final_line = stem_lines[-1].strip()
        if not final_line:
            return stem_lines, []
        condition_intro_seen = any(
            "다음 조건" in line or "조건을 만족" in line
            for line in stem_lines[:-1]
        )
        final_prompt = (
            final_line.endswith("?")
            or "값을 구하시오" in final_line
            or "개수를 구하시오" in final_line
            or "넓이는?" in final_line
        )
        condition_intro_seen = condition_intro_seen or any(
            any(
                marker in line
                for marker in (
                    "\ub2e4\uc74c \uc870\uac74",
                    "\uc870\uac74\uc744 \ub9cc\uc871",
                )
            )
            for line in stem_lines[:-1]
        )
        final_prompt = final_prompt or (
            "\uac12\uc744 \uad6c\ud558\uc2dc\uc624" in final_line
            or "\uac1c\uc218\ub97c \uad6c\ud558\uc2dc\uc624" in final_line
            or "\ub113\uc774\ub294?" in final_line
        )
        if condition_intro_seen and final_prompt:
            return stem_lines[:-1], [stem_lines[-1]]
        return stem_lines, []

    def render_stem_lines(
        label: str,
        problem: dict[str, Any],
        stem_lines: list[str],
        is_passage_block: bool,
        meta: str,
    ) -> None:
        if is_passage_block:
            para(stem_lines[0] if stem_lines else str(label), "heading")
            for line in stem_lines[1:]:
                para(line, "body")
        elif template.merge_question_number:
            first_line = _strip_question_prefix(stem_lines[0], label) if stem_lines else ""
            para(
                f"{label}. {first_line or problem.get('title') or '문제'}",
                "heading",
                math_blocks=native_math and template.key == "kice_math",
            )
            for line in stem_lines[1:]:
                para(line, "body", math_blocks=native_math and template.key == "kice_math")
            if meta:
                para(f"[{meta}]", "small")
        else:
            heading = f"{label}. {problem.get('title') or '문제'}"
            if meta:
                heading += f" [{meta}]"
            para(heading, "heading", math_blocks=native_math and template.key == "kice_math")
            for line in stem_lines or [""]:
                para(line, "body", math_blocks=native_math and template.key == "kice_math")

    def apply_columns() -> None:
        nonlocal flow_y, pending_column_break
        if columns > 1:
            doc.set_columns(
                columns,
                same_gap=COLUMN_GAP,
                separator_type="SOLID",
                separator_width="0.12 mm",
                separator_color="#000000",
            )
        flow_y = 0
        pending_column_break = False

    # --- 머리말 ---
    if template.key == "basic":
        para(title, "title", center=True)
        para("")
    else:
        para(title or template.masthead_title, "title", center=True)
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

    apply_columns()

    # --- 문항 ---
    for index, problem in enumerate(problems, start=1):
        if native_math and template.key == "kice_math" and columns > 1:
            estimated_height = estimate_problem_height(problem, index)
            if flow_y > 0 and flow_y + estimated_height > column_body_height:
                pending_column_break = True
        label = problem.get("number") or str(index)
        subject = problem.get("subject") or ""
        unit = problem.get("unit") or ""
        source_marker = unit if SOURCE_MARKER_RE.match(str(unit)) else ""
        meta_unit = "" if source_marker else unit
        meta = " / ".join(p for p in [subject, meta_unit] if p)

        # 이미지-only 문항(인식 이미지-폴백): stem/선지가 비고 이미지만 있으면 번호/텍스트
        # heading 없이 이미지만 렌더한다. crop 이미지가 번호·본문·선지를 이미 담고 있어
        # writer 가 번호를 또 붙이면 중복되기 때문(원본과 픽셀 동일 재현 목적).
        if not (problem.get("stem") or "").strip() and not problem.get("choices") and problem.get("image_paths"):
            for image_path in problem.get("image_paths"):
                image_height = estimate_picture_height(image_path)
                _add_picture(
                    doc,
                    image_path,
                    content_width,
                    max_height=math_picture_max_height,
                    paragraph_attrs=reserve_object_height(image_height),
                )
            para("")
            continue

        stem_lines = (problem.get("stem") or "").splitlines()
        is_passage_block = _is_passage_label(label) and not problem.get("choices")
        table_tail_lines: list[str] = []
        if not is_passage_block:
            stem_lines, table_tail_lines = split_table_tail_lines(
                stem_lines,
                bool(problem.get("tables")),
            )
        if is_passage_block:
            para(stem_lines[0] if stem_lines else str(label), "heading")
            for line in stem_lines[1:]:
                para(line, "body")
        elif template.merge_question_number:
            first_line = _strip_question_prefix(stem_lines[0], label) if stem_lines else ""
            para(
                f"{label}. {first_line or problem.get('title') or '문제'}",
                "heading",
                math_blocks=native_math and template.key == "kice_math",
            )
            for line in stem_lines[1:]:
                para(line, "body", math_blocks=native_math and template.key == "kice_math")
            if meta:
                para(f"[{meta}]", "small")
        else:
            heading = f"{label}. {problem.get('title') or '문제'}"
            if meta:
                heading += f" [{meta}]"
            para(heading, "heading", math_blocks=native_math and template.key == "kice_math")
            for line in stem_lines or [""]:
                para(line, "body", math_blocks=native_math and template.key == "kice_math")

        for rows in problem.get("tables") or []:
            table_height = estimate_table_height(rows)
            _add_table(
                doc,
                rows,
                char_pr_id_ref=cp["body"],
                math_char_pr_id_ref=math_cp["body"],
                native_math=native_math,
                equation_counter=equation_counter,
                cell_para_pr_id_ref=pr_left,
                min_line_height=style_line_heights["body"],
                content_width=content_width,
                height=table_height,
                paragraph_attrs=reserve_object_height(table_height),
            )
        for line in table_tail_lines:
            para(line, "body", math_blocks=native_math and template.key == "kice_math")

        for image_path in problem.get("image_paths") or []:
            image_height = estimate_picture_height(image_path)
            _add_picture(
                doc,
                image_path,
                content_width,
                max_height=math_picture_max_height,
                paragraph_attrs=reserve_object_height(image_height),
            )

        choices = [
            _format_choice(ci, choice, template)
            for ci, choice in enumerate(problem.get("choices") or [], start=1)
        ]
        choices_have_complex_math = any(has_complex_choice_math(choice) for choice in choices)
        if choices and use_choice_grid(choices):
            add_choice_grid(choices)
        elif (
            choices
            and template.inline_short_choices
            and sum(len(c) for c in choices) <= 90
            and not choices_have_complex_math
        ):
            for choice_line in wrapped_choice_lines(choices):
                para(
                    choice_line,
                    "body",
                    math_blocks=native_math and template.key == "kice_math",
                    block_complex_math=False,
                )
        else:
            for choice in choices:
                para(
                    choice,
                    "body",
                    math_blocks=native_math and template.key == "kice_math",
                    block_complex_math=False,
                )
        if needs_answer_blank(problem, template):
            para(answer_blank_text(template), "body")
        if source_marker:
            para(source_marker, "small", right=True, allow_column_break=False)

        if template.include_answers and problem.get("answer"):
            para(f"정답: {format_answer(problem, template)}", "body")
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
    if native_math:
        _patch_hwpx_native_math_linesegs(Path(path))


def _add_table(
    doc: "HwpxDocument",
    rows: list[list[str]],
    *,
    char_pr_id_ref: str = "0",
    math_char_pr_id_ref: str = "0",
    native_math: bool = False,
    equation_counter: list[int] | None = None,
    cell_para_pr_id_ref: str | None = None,
    min_line_height: int = 1000,
    content_width: int | None = None,
    height: int | None = None,
    paragraph_attrs: dict[str, str] | None = None,
) -> None:
    if not rows or not any(rows):
        return
    if equation_counter is None:
        equation_counter = [0]
    row_cnt = len(rows)
    col_cnt = max(len(r) for r in rows)
    cell_line_limit = max(16, 46 // col_cnt)
    table = doc.add_table(
        row_cnt,
        col_cnt,
        char_pr_id_ref=char_pr_id_ref,
        width=content_width,
        height=height,
        **(paragraph_attrs or {}),
    )
    # 표(지문/보기 박스)가 컬럼 폭을 꽉 채우게 한다. 폭을 안 정하면 벤더 기본폭(~2cm)
    # 이라 지문이 한 줄에 1~2단어씩 좁게 줄바꿈되는 버그가 난다.
    if content_width:
        try:
            base = content_width // col_cnt
            widths = [base] * col_cnt
            widths[-1] = content_width - base * (col_cnt - 1)
            table.set_column_widths(widths)
        except Exception:
            pass
    # 지문/보기 박스를 '블록 표'(treatAsChar=0)로 만들어 컬럼·페이지 경계에서 자연스럽게
    # 분할·흐르게 한다. 벤더 기본(treatAsChar=1, 인라인)은 분할 불가 단일 라인유닛이라,
    # 1단 헤더가 페이지1 상단을 먹은 뒤 시작되는 2단 영역에서 키 큰 지문표가 어느 컬럼에도
    # 안 들어가 통째로 다음 페이지로 점프 → 페이지1 하단이 통째 비는 버그가 난다.
    try:
        pos = table.element.find(f"{_HP}pos")
        if pos is not None:
            pos.set("treatAsChar", "0")
            pos.set("vertRelTo", "PARA")
            pos.set("horzRelTo", "COLUMN")
            pos.set("vertAlign", "TOP")
            pos.set("horzAlign", "LEFT")
    except Exception:
        pass
    for r, row in enumerate(rows):
        for c in range(col_cnt):
            value = row[c] if c < len(row) else ""
            _set_table_cell_rich_text(
                table,
                r,
                c,
                str(value or ""),
                char_pr_id_ref=char_pr_id_ref,
                math_char_pr_id_ref=math_char_pr_id_ref,
                native_math=native_math,
                equation_counter=equation_counter,
                cell_para_pr_id_ref=cell_para_pr_id_ref,
                min_line_height=min_line_height,
                cell_line_limit=cell_line_limit,
            )


def _add_picture(
    doc: "HwpxDocument",
    image_path: str,
    content_width: int,
    *,
    max_height: int | None = None,
    paragraph_attrs: dict[str, str] | None = None,
) -> None:
    full_path = storage.DATA_DIR / image_path
    if not full_path.exists():
        return
    size = _picture_size(full_path, content_width, max_height)
    if size is None:
        return
    width, height = size
    fmt = _IMG_FORMATS.get(full_path.suffix.lower(), "png")
    doc.add_picture(
        full_path.read_bytes(),
        fmt,
        width=width,
        height=height,
        **(paragraph_attrs or {}),
    )
