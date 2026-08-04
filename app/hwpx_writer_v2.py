"""python-hwpx(airmang, vendored) 기반 HWPX 작성기.

기존 hwpx_writer.py는 HWPX를 문자열 템플릿으로 손수 직렬화한다. 이 모듈은
동일한 write_hwpx 시그니처를 vendored python-hwpx 고수준 API로 재구현해
출력/렌더 호환성을 높인 현재 기본 writer이며 ``app.main``의 HWPX 내보내기
경로에 연결되어 있다. ``v2`` 이름은 기존 모듈과의 구분을 위해 유지한다.
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
from lxml import etree

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
    _equation_reserved_width,
    _equation_size,
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
    "title": {"size": 16.0, "bold": True, "font": "HY신명조"},
    "meta": {"size": 11.0, "font": "HY신명조"},
    "heading": {"size": 11.0, "bold": True, "font": "HY신명조"},
    "body": {"size": 11.0, "font": "HY신명조"},
    "small": {"size": 9.5, "font": "HY신명조"},
}

_KICE_ENGLISH_STYLE_SPECS = {
    **_KICE_STYLE_SPECS,
    "body": {"size": 11.0, "font": "HY신명조"},
}

_KICE_STYLE_LINE_HEIGHTS = {
    "title": int(16.0 * 165),
    "meta": int(11.0 * 165),
    "heading": int(11.0 * 165),
    "body": int(11.0 * 165),
    "small": int(9.5 * 165),
}

# PDF 시험지의 A3 원고를 A4로 70.7% 축소한 구조형 변환 프로필.
_KICE_SOURCE_STYLE_SPECS = {
    "title": {"size": 20.0, "bold": True, "font": "HY신명조"},
    "meta": {"size": 9.5, "font": "HY신명조"},
    "heading": {"size": 8.3, "bold": True, "font": "HY신명조"},
    "body": {"size": 7.9, "font": "HY신명조"},
    "small": {"size": 7.2, "font": "HY신명조"},
}
_KICE_SOURCE_LINE_SPACING = 165
_KICE_SOURCE_LINE_SPACING_BY_TEMPLATE = {
    "kice_korean": 155,
    "kice_english": 110,
}
_KICE_SOURCE_STYLE_LINE_HEIGHTS = {
    name: int(float(spec["size"]) * _KICE_SOURCE_LINE_SPACING)
    for name, spec in _KICE_SOURCE_STYLE_SPECS.items()
}
_KICE_SOURCE_MARGIN_LEFT_MM = 20.0
_KICE_SOURCE_MARGIN_RIGHT_MM = 20.0
_KICE_SOURCE_MARGIN_TOP_MM = 20.0
_KICE_SOURCE_MARGIN_BOTTOM_MM = 18.0
_KICE_SOURCE_COLUMN_GAP_MM = 8.0
_A4_WIDTH_HWP = 59528
_A4_HEIGHT_HWP = 84188


def _mm_to_hwp(value_mm: float) -> int:
    return round(float(value_mm) * 7200.0 / 25.4)

# rhwp-verified flow budget for native-math two-column KICE exports.
#
# The physical A4 body is about 65762 HWPUNIT, but equations and tables render
# taller than the lightweight Python estimator. 43500 keeps the real HWP math
# samples compact while leaving enough bottom margin to avoid layout overflow.
KICE_MATH_COLUMN_BODY_HEIGHT = 43500
# Single-column exports have no column to spill into, so the flow budget is the
# usable page body instead of a column.  Native-math pages need more slack for
# the taller equation runs than plain text pages do.
SINGLE_COLUMN_MATH_BODY_HEIGHT = 35000
SINGLE_COLUMN_TEXT_BODY_HEIGHT = 60000
# Slack kept at the bottom of a column so a problem that *just* fits is moved
# instead of being clipped by the renderer's own rounding.
PROBLEM_LAYOUT_GUARD = 900


def _local_name(tag: Any) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _is_kice_template(template: ExamTemplate) -> bool:
    return str(template.key or "").startswith("kice_")


def _style_specs_for_template(
    template: ExamTemplate,
    *,
    preserve_source_layout: bool = False,
) -> dict[str, dict[str, Any]]:
    if preserve_source_layout and _is_kice_template(template):
        return _KICE_SOURCE_STYLE_SPECS
    if not _is_kice_template(template):
        return _STYLE_SPECS
    if template.key == "kice_english":
        return _KICE_ENGLISH_STYLE_SPECS
    return _KICE_STYLE_SPECS


def _style_line_heights_for_template(
    template: ExamTemplate,
    *,
    preserve_source_layout: bool = False,
) -> dict[str, int]:
    if preserve_source_layout and _is_kice_template(template):
        line_spacing = _KICE_SOURCE_LINE_SPACING_BY_TEMPLATE.get(
            template.key,
            _KICE_SOURCE_LINE_SPACING,
        )
        return {
            name: int(float(spec["size"]) * line_spacing)
            for name, spec in _KICE_SOURCE_STYLE_SPECS.items()
        }
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


def _set_paragraph_element_lineseg(
    element: Any,
    height: int,
    *,
    width: int = MAX_IMAGE_WIDTH,
    spacing_ratio: float = 0.15,
) -> None:
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
                "spacing": str(int(height * max(0.0, spacing_ratio))),
                "horzpos": "0",
                "horzsize": str(width),
                "flags": "393216",
            },
        )
    )
    element.append(line_seg_array)


def _set_paragraph_lineseg(paragraph: Any, height: int) -> None:
    _set_paragraph_element_lineseg(paragraph.element, height)


def _lineseg_xml(height: int) -> str:
    return (
        '<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" '
        f'vertsize="{height}" textheight="{height}" baseline="{int(height * 0.85)}" '
        f'spacing="{int(height * 0.15)}" horzpos="0" horzsize="{MAX_IMAGE_WIDTH}" '
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


def _patch_hwpx_exam_flow_linesegs(path: Path) -> int:
    """Restore compact text and inline-object heights after package serialization.

    The vendored serializer clears layout caches and the Hancom compatibility
    pass fills missing line segments with a fixed 1000 HWPUNIT height. That
    flattens 8 pt exam text and, more importantly, makes picture paragraphs
    occupy only one text line so following choices overlap the picture.
    """
    with zipfile.ZipFile(path, "r") as archive:
        infos = archive.infolist()
        payloads = {info.filename: archive.read(info.filename) for info in infos}
    header_payload = payloads.get("Contents/header.xml")
    if not header_payload:
        return 0
    header_root = etree.fromstring(header_payload)
    char_heights = {
        str(char_pr.get("id") or ""): int(char_pr.get("height") or "1000")
        for char_pr in header_root.findall(f".//{_HH}charPr")
        if str(char_pr.get("id") or "")
    }
    para_line_spacings: dict[str, int] = {}
    for para_pr in header_root.findall(f".//{_HH}paraPr"):
        para_id = str(para_pr.get("id") or "")
        line_spacing = para_pr.find(f"{_HH}lineSpacing")
        if not para_id or line_spacing is None:
            continue
        try:
            para_line_spacings[para_id] = int(line_spacing.get("value") or "160")
        except ValueError:
            continue
    total = 0
    updates: dict[str, bytes] = {}
    for name, payload in payloads.items():
        if not _SECTION_PART_RE.fullmatch(name):
            continue
        root = etree.fromstring(payload)
        changed = False
        for paragraph in root.findall(f".//{_HP}p"):
            if paragraph.findall(f".//{_HP}equation") or paragraph.findall(f".//{_HP}tbl"):
                continue
            pictures = paragraph.findall(f".//{_HP}pic")
            if pictures:
                picture_heights: list[int] = []
                for picture in pictures:
                    size = picture.find(f"{_HP}sz")
                    if size is None:
                        continue
                    try:
                        picture_heights.append(int(size.get("height") or "0"))
                    except ValueError:
                        continue
                target_height = max(picture_heights, default=1000) + 300
            else:
                run_heights = [
                    char_heights.get(str(run.get("charPrIDRef") or ""), 1000)
                    for run in paragraph.findall(f"{_HP}run")
                ]
                char_height = max(run_heights, default=1000)
                line_spacing_percent = para_line_spacings.get(
                    str(paragraph.get("paraPrIDRef") or ""),
                    _KICE_SOURCE_LINE_SPACING,
                )
                target_height = max(
                    700,
                    round(char_height * line_spacing_percent / 115.0),
                )
            current = paragraph.find(f"{_HP}linesegarray")
            if current is not None:
                paragraph.remove(current)
            _set_paragraph_element_lineseg(
                paragraph,
                target_height,
                spacing_ratio=0.0 if pictures else 0.15,
            )
            changed = True
            total += 1
        if changed:
            updates[name] = etree.tostring(
                root,
                encoding="utf-8",
                xml_declaration=True,
                standalone=True,
            )
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


def _save_hwpx_with_hancom_compat(doc: Any, path: Path, *, native_math: bool) -> None:
    """Save a python-hwpx document after applying Hancom 2024 safety sidecars."""

    from hwpx.tools.package_validator import validate_editor_open_safety

    from .pdf_layout_writer import _patch_hancom_compatibility

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), suffix=target.suffix + ".tmp")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_bytes(doc._to_bytes_for_validation())
        _patch_hancom_compatibility(tmp_path)
        _patch_hwpx_exam_flow_linesegs(tmp_path)
        if native_math:
            _patch_hwpx_native_math_linesegs(tmp_path)

        report = validate_editor_open_safety(tmp_path)
        if not report.ok:
            raise ValueError("Generated HWPX package failed open-safety validation: " + report.summary)
        os.replace(tmp_path, target)
        mark_clean = getattr(doc, "_mark_save_clean", None)
        if callable(mark_clean):
            mark_clean()
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


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
    *,
    compact_placeholder: bool = False,
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
    # Inline equations are treatAsChar objects: the renderer advances the text
    # cursor by this width.  A zero width makes Hancom/rhwp draw the following
    # prose on top of the equation, so declare the estimated extent instead of
    # padding the flow with blank text runs.
    equation.append(
        equation.makeelement(
            f"{_HP}sz",
            {
                "width": str(_equation_reserved_width(script, compact=compact_placeholder)),
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


def _replace_paragraph_runs(
    paragraph: Any,
    text: str,
    *,
    char_pr_id_ref: str,
    math_char_pr_id_ref: str,
    native_math: bool,
    equation_counter: list[int],
    min_line_height: int = 1000,
    compact_math_placeholder: bool = False,
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
                _append_equation_run(
                    paragraph,
                    script,
                    char_pr_id_ref,
                    equation_counter[0],
                    compact_placeholder=compact_math_placeholder,
                )
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
    preserve_source_layout: bool = False,
) -> None:
    template = get_template(template_key)
    title = resolve_export_title(title, template)
    recognized_columns = layout_model.recognized_column_count(problems)
    columns = recognized_columns or max(1, min(template.columns, 2))
    page_body_width = MAX_IMAGE_WIDTH
    column_gap = COLUMN_GAP
    if preserve_source_layout and _is_kice_template(template):
        page_body_width = (
            _A4_WIDTH_HWP
            - _mm_to_hwp(_KICE_SOURCE_MARGIN_LEFT_MM)
            - _mm_to_hwp(_KICE_SOURCE_MARGIN_RIGHT_MM)
        )
        column_gap = _mm_to_hwp(_KICE_SOURCE_COLUMN_GAP_MM)
    content_width = (
        (page_body_width - column_gap * (columns - 1)) // columns
        if columns > 1
        else page_body_width
    )

    doc = HwpxDocument.new()
    # The bundled Hancom skeleton contains version.xml but omits its OPF
    # manifest entry.  Explicitly relate it so validators and alternate
    # readers do not have to guess the package-level compatibility metadata.
    doc.package.add_manifest_item("version", "version.xml", "application/xml")
    # Hancom interprets WIDELY as portrait when width < height in HWPX pagePr.
    doc.set_page_size(width=_A4_WIDTH_HWP, height=_A4_HEIGHT_HWP, orientation="WIDELY")
    if preserve_source_layout and _is_kice_template(template):
        doc.set_page_margins(
            left=_mm_to_hwp(_KICE_SOURCE_MARGIN_LEFT_MM),
            right=_mm_to_hwp(_KICE_SOURCE_MARGIN_RIGHT_MM),
            top=_mm_to_hwp(_KICE_SOURCE_MARGIN_TOP_MM),
            bottom=_mm_to_hwp(_KICE_SOURCE_MARGIN_BOTTOM_MM),
            header=0,
            footer=0,
            gutter=0,
        )
    header = doc.headers[0]
    if _is_kice_template(template):
        _ensure_kice_font_faces(header)
    style_specs = _style_specs_for_template(
        template,
        preserve_source_layout=preserve_source_layout,
    )
    style_line_heights = _style_line_heights_for_template(
        template,
        preserve_source_layout=preserve_source_layout,
    )

    # paraPr(정렬) / charPr(크기) 참조를 한 번씩만 만들어 재사용한다.
    if _is_kice_template(template):
        default_line_spacing_percent = (
            _KICE_SOURCE_LINE_SPACING_BY_TEMPLATE.get(
                template.key,
                _KICE_SOURCE_LINE_SPACING,
            )
            if preserve_source_layout
            else 165
        )
        pr_left = header.ensure_paragraph_format(
            alignment="LEFT",
            line_spacing_percent=default_line_spacing_percent,
        )
        pr_center = header.ensure_paragraph_format(
            alignment="CENTER",
            line_spacing_percent=default_line_spacing_percent,
        )
        pr_right = header.ensure_paragraph_format(
            alignment="RIGHT",
            line_spacing_percent=default_line_spacing_percent,
        )
    else:
        default_line_spacing_percent = 160
        pr_left = header.ensure_paragraph_alignment("LEFT")
        pr_center = header.ensure_paragraph_alignment("CENTER")
        pr_right = header.ensure_paragraph_alignment("RIGHT")
    cp = {name: doc.ensure_run_style(**spec) for name, spec in style_specs.items()}
    math_cp = {name: doc.ensure_run_style(**_math_style_spec(spec)) for name, spec in style_specs.items()}
    if _is_kice_template(template):
        char_ratio = (
            90
            if preserve_source_layout and template.key == "kice_english"
            else 95
        )
        _apply_char_metrics(header, list(cp.values()), ratio=char_ratio, spacing=-5)
    equation_counter = [0]
    flow_y = 0
    pending_column_break = False
    pending_page_break = False
    current_flow_column = 1
    next_source_anchor_top_hwp: int | None = None
    dynamic_para_formats: dict[tuple[str, int, int, int], str] = {}
    source_layout_flow = bool(
        preserve_source_layout
        and columns > 1
        and any(int(problem.get("source_page") or 0) > 0 for problem in problems)
    )
    source_text_document = any(
        isinstance(problem.get("layout"), dict)
        and bool(problem["layout"].get("source_text_flow"))
        for problem in problems
    )
    if source_layout_flow:
        column_body_height = (
            _A4_HEIGHT_HWP
            - _mm_to_hwp(_KICE_SOURCE_MARGIN_TOP_MM)
            - _mm_to_hwp(_KICE_SOURCE_MARGIN_BOTTOM_MM)
        )
    elif columns > 1:
        column_body_height = KICE_MATH_COLUMN_BODY_HEIGHT
    else:
        column_body_height = (
            SINGLE_COLUMN_MATH_BODY_HEIGHT if native_math else SINGLE_COLUMN_TEXT_BODY_HEIGHT
        )
    picture_height_ratio = 0.20 if source_text_document else 0.25
    math_picture_max_height = (
        int(column_body_height * picture_height_ratio)
        if columns > 1
        else None
    )

    def source_target_top_hwp(layout: dict[str, Any], top_px: float | None = None) -> int | None:
        page = layout.get("page") if isinstance(layout.get("page"), dict) else {}
        bbox = layout.get("bbox_px") or []
        if top_px is None:
            if len(bbox) != 4:
                return None
            top_px = float(bbox[1])
        page_height_px = float(page.get("height_px") or 0.0)
        if page_height_px <= 0:
            return None
        absolute = int(round(_A4_HEIGHT_HWP * float(top_px) / page_height_px))
        target = absolute - _mm_to_hwp(_KICE_SOURCE_MARGIN_TOP_MM)
        source_page = int(layout.get("source_page") or page.get("number") or 0)
        if source_page == 1:
            first_page_origins = {
                "kice_korean": 10200,
                "kice_english": 5000,
                "kice_math": 9150,
            }
            target -= first_page_origins.get(template.key, 0)
        return max(0, target)

    def source_left_margin_hwp(layout: dict[str, Any], left_px: float) -> int:
        page = layout.get("page") if isinstance(layout.get("page"), dict) else {}
        page_width_px = float(page.get("width_px") or 0.0)
        if page_width_px <= 0:
            return 0
        absolute = int(round(_A4_WIDTH_HWP * float(left_px) / page_width_px))
        column_index = max(1, min(columns, int(layout.get("column_index") or 1)))
        column_left = _mm_to_hwp(_KICE_SOURCE_MARGIN_LEFT_MM)
        if column_index > 1:
            column_left += (content_width + column_gap) * (column_index - 1)
        return max(0, min(content_width - 100, absolute - column_left))

    def source_line_spacing_percent(
        layout: dict[str, Any],
        current: dict[str, Any],
        following: dict[str, Any] | None,
        style: str,
    ) -> int:
        typical_spacing = {
            "kice_korean": 165,
            "kice_english": 150,
            "kice_math": 165,
        }.get(template.key, default_line_spacing_percent)
        if following is None:
            return typical_spacing
        page = layout.get("page") if isinstance(layout.get("page"), dict) else {}
        page_height_px = float(page.get("height_px") or 0.0)
        delta_px = float(following.get("top_px") or 0.0) - float(current.get("top_px") or 0.0)
        if page_height_px <= 0 or delta_px <= 1.0:
            return typical_spacing
        desired_height = _A4_HEIGHT_HWP * delta_px / page_height_px
        char_height = max(100, int(round(float(style_specs.get(style, style_specs["body"])["size"]) * 100.0)))
        if desired_height > char_height * 2.4:
            return typical_spacing
        percent = int(round(desired_height * 100.0 / char_height))
        return max(90, min(300, percent))

    def dynamic_para_pr(
        *,
        alignment: str,
        line_spacing_percent: int,
        left_margin_hwp: int,
        previous_margin_hwp: int,
    ) -> str:
        safe_spacing = max(80, min(300, int(line_spacing_percent)))
        safe_left = max(0, int(round(left_margin_hwp / 10.0) * 10))
        safe_previous = max(0, int(round(previous_margin_hwp / 10.0) * 10))
        key = (alignment.upper(), safe_spacing, safe_left, safe_previous)
        para_pr = dynamic_para_formats.get(key)
        if para_pr is None:
            para_pr = header.ensure_paragraph_format(
                alignment=alignment,
                line_spacing_percent=safe_spacing,
                margins={"left": safe_left, "prev": safe_previous, "next": 0},
            )
            dynamic_para_formats[key] = para_pr
        return para_pr

    def add_single_para(
        text: str,
        style: str = "body",
        center: bool = False,
        right: bool = False,
        *,
        math_enabled: bool = True,
        allow_column_break: bool = True,
        target_top_hwp: int | None = None,
        left_margin_hwp: int = 0,
        line_spacing_percent: int | None = None,
        compact_math_placeholder: bool = False,
        **attrs: str,
    ) -> int:
        nonlocal flow_y, pending_column_break, pending_page_break, current_flow_column
        nonlocal next_source_anchor_top_hwp
        effective_spacing = int(line_spacing_percent or default_line_spacing_percent)
        if source_layout_flow and _is_kice_template(template):
            char_height = max(
                100,
                int(round(float(style_specs.get(style, style_specs["body"])["size"]) * 100.0)),
            )
            para_height = max(700, round(char_height * effective_spacing / 115.0))
        else:
            para_height = style_line_heights.get(style, 1000)
        if native_math and math_enabled:
            para_height = max(para_height, _native_math_height(str(text or "")))
        if (
            not source_layout_flow
            and
            columns > 1
            and not str(text or "").strip()
            and not attrs
            and flow_y > column_body_height - 2500
        ):
            pending_column_break = True
            return 0
        if pending_page_break:
            attrs.setdefault("pageBreak", "1")
            pending_page_break = False
            pending_column_break = False
            flow_y = 0
            current_flow_column = 1
        elif pending_column_break and allow_column_break:
            # A columnBreak is meaningless in a single-column section; spill to
            # the next page instead so the deferred break is not silently lost.
            attrs.setdefault("columnBreak" if columns > 1 else "pageBreak", "1")
            pending_column_break = False
            flow_y = 0
            current_flow_column = min(columns, current_flow_column + 1)
        elif pending_column_break:
            pending_column_break = False
        elif (
            allow_column_break
            and not source_layout_flow
            and flow_y > 0
            and flow_y + para_height > column_body_height
        ):
            attrs.setdefault("columnBreak" if columns > 1 else "pageBreak", "1")
            flow_y = 0
            current_flow_column = min(columns, current_flow_column + 1)
        if attrs.get("pageBreak") == "1" or attrs.get("columnBreak") == "1":
            flow_y = 0
        if target_top_hwp is None and next_source_anchor_top_hwp is not None:
            target_top_hwp = next_source_anchor_top_hwp
            next_source_anchor_top_hwp = None
        previous_margin_hwp = (
            max(0, int(target_top_hwp) - flow_y)
            if target_top_hwp is not None
            else 0
        )
        if left_margin_hwp or previous_margin_hwp or line_spacing_percent is not None:
            alignment = "RIGHT" if right else "CENTER" if center else "LEFT"
            para_pr = dynamic_para_pr(
                alignment=alignment,
                line_spacing_percent=effective_spacing,
                left_margin_hwp=left_margin_hwp,
                previous_margin_hwp=previous_margin_hwp,
            )
        else:
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
            compact_math_placeholder=compact_math_placeholder,
        )
        flow_y += previous_margin_hwp + para_height
        return previous_margin_hwp + para_height

    def visual_units(text: str) -> int:
        return _visual_units(text)

    def segment_units(segment: str, is_math: bool) -> int:
        return _math_segment_units(segment, is_math)

    def wrap_line_parts(line: str, limit: int) -> list[str]:
        return _wrap_math_line_parts(line, limit)

    def wrapped_choice_lines(choices: list[str], limit: int = 68) -> list[str]:
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
        limits = {"heading": 62, "body": 68, "small": 76}
        # `or [line]` keeps the original line when the wrapper yields nothing,
        # so content is never silently dropped.
        for wrapped in wrap_line_parts(line, limits.get(style, 68)) or [line]:
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
        preserve_inline_math: bool = False,
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

                if preserve_inline_math:
                    add_single_para(
                        line,
                        style,
                        center=center,
                        right=right,
                        math_enabled=True,
                        allow_column_break=allow_column_break,
                        compact_math_placeholder=True,
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
        add_wrapped_line(
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
        limits = {"heading": 62, "body": 68, "small": 76}
        parts = wrap_line_parts(line, limits.get(style, 68))
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
            return estimate_wrapped_line_height(
                value,
                style,
                center=center,
                right=right,
                math_enabled=True,
            )

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

    def split_table_chunks(rows: list[list[str]]) -> list[list[list[str]]]:
        if not rows:
            return []
        max_height = column_body_height - PROBLEM_LAYOUT_GUARD * 2
        if columns <= 1 or len(rows) <= 1 or estimate_table_height(rows) <= max_height:
            return [rows]
        header_row = rows[0]
        chunks: list[list[list[str]]] = []
        current: list[list[str]] = [header_row]
        for row in rows[1:]:
            candidate = [*current, row]
            if len(current) > 1 and estimate_table_height(candidate) > max_height:
                chunks.append(current)
                current = [header_row, row]
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks

    def estimate_picture_height(image_path: str) -> int:
        full_path = storage.resolve_data_image_path(image_path)
        if full_path is None:
            return 0
        size = _picture_size(full_path, content_width, math_picture_max_height)
        if size is None:
            return 0
        return size[1] + 600

    def reserve_object_height(height: int) -> dict[str, str]:
        nonlocal flow_y, pending_column_break, pending_page_break, current_flow_column
        attrs: dict[str, str] = {}
        if pending_page_break:
            attrs["pageBreak"] = "1"
            pending_page_break = False
            pending_column_break = False
            flow_y = 0
            current_flow_column = 1
        elif pending_column_break:
            attrs["columnBreak" if columns > 1 else "pageBreak"] = "1"
            pending_column_break = False
            flow_y = 0
            current_flow_column = min(columns, current_flow_column + 1)
        elif (
            not source_layout_flow
            and height > 0
            and flow_y > 0
            and flow_y + height > column_body_height
        ):
            attrs["columnBreak" if columns > 1 else "pageBreak"] = "1"
            flow_y = 0
            current_flow_column = min(columns, current_flow_column + 1)
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
        if source_layout_flow and len(choices) <= 5:
            return max(1, len(choices))
        max_units = max((choice_visual_units(choice) for choice in choices), default=0)
        return 2 if max_units > 14 else 3

    def estimate_choice_grid_height(choices: list[str]) -> int:
        col_count = choice_grid_columns(choices)
        row_count = max(1, (len(choices) + col_count - 1) // col_count)
        row_height = 1400 if source_layout_flow else 2200
        return row_count * row_height + 200

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
        layout = problem.get("layout") or {}
        if isinstance(layout, dict) and (
            layout.get("continuation") or layout.get("source_text_flow")
        ):
            lines = (problem.get("stem") or "").splitlines()
            line_styles = layout.get("line_styles") or []
            total = sum(
                estimate_para_height(
                    line,
                    str(line_styles[line_index]) if line_index < len(line_styles) else "body",
                    math_blocks=native_math and template.key == "kice_math",
                )
                for line_index, line in enumerate(lines)
            )
            if layout.get("continuation"):
                total += estimate_para_height("", "body")
            return total

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

    def merge_source_math_stem_lines(stem_lines: list[str]) -> list[str]:
        if not (source_layout_flow and template.key == "kice_math"):
            return stem_lines
        merged: list[str] = []
        for raw_line in stem_lines:
            line = str(raw_line or "").strip()
            if not line:
                continue
            operator_continuation = bool(re.match(r"^\$\s*[+\-=/]", line))
            question_continuation = bool(
                merged
                and "$" in merged[-1]
                and re.match(r"^(?:의\s*값|의\s*개수|일\s*때|이면|에서)", line)
                and len(re.sub(r"\s+", "", merged[-1] + line)) <= 110
            )
            if merged and (operator_continuation or question_continuation):
                separator = "" if operator_continuation else " "
                merged[-1] = merged[-1].rstrip() + separator + line
            else:
                merged.append(line)
        return merged

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
                preserve_inline_math=source_layout_flow and template.key == "kice_math",
            )
            for line in stem_lines[1:]:
                para(
                    line,
                    "body",
                    math_blocks=native_math and template.key == "kice_math",
                    preserve_inline_math=source_layout_flow and template.key == "kice_math",
                )
            if meta:
                para(f"[{meta}]", "small")
        else:
            heading = f"{label}. {problem.get('title') or '문제'}"
            if meta:
                heading += f" [{meta}]"
            para(
                heading,
                "heading",
                math_blocks=native_math and template.key == "kice_math",
                preserve_inline_math=source_layout_flow and template.key == "kice_math",
            )
            for line in stem_lines or [""]:
                para(
                    line,
                    "body",
                    math_blocks=native_math and template.key == "kice_math",
                    preserve_inline_math=source_layout_flow and template.key == "kice_math",
                )

    def apply_columns() -> None:
        nonlocal flow_y, pending_column_break, pending_page_break, current_flow_column
        if columns > 1:
            doc.set_columns(
                columns,
                same_gap=column_gap,
                separator_type="SOLID",
                separator_width="0.12 mm",
                separator_color="#000000",
            )
        # The masthead is emitted before ``set_columns`` and is budgeted
        # separately from the problem flow: ``column_body_height`` (e.g.
        # ``KICE_MATH_COLUMN_BODY_HEIGHT``) is calibrated against a column that
        # starts empty at the first problem.  Carrying the masthead height into
        # that budget makes the estimator break a column/page one item early on
        # every template and spills a nearly empty tail page.
        flow_y = 0
        pending_column_break = False
        pending_page_break = False
        current_flow_column = 1

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
    previous_problem: dict[str, Any] | None = None
    for index, problem in enumerate(problems, start=1):
        if source_layout_flow:
            # Source-faithful flow is driven by the recognised page/column of the
            # original exam, not by the height estimator.
            if previous_problem is not None:
                previous_page = int(previous_problem.get("source_page") or 0)
                current_page = int(problem.get("source_page") or 0)
                if current_page > 0 and previous_page > 0 and current_page != previous_page:
                    pending_page_break = True
                    pending_column_break = False
                elif layout_model.column_break_before(previous_problem, problem):
                    current_layout = problem.get("layout") or {}
                    target_column = (
                        int(current_layout.get("column_index") or 0)
                        if isinstance(current_layout, dict)
                        else 0
                    )
                    if target_column <= 0 or current_flow_column < target_column:
                        pending_column_break = True
        else:
            estimated_height = estimate_problem_height(problem, index)
            # Problems taller than a whole column can never fit; breaking for
            # them would only leave an empty column behind.  No extra guard band
            # is added here: ``column_body_height`` is already budgeted below the
            # physical column so the estimator's optimism is absorbed there.
            if (
                flow_y > 0
                and estimated_height <= column_body_height
                and flow_y + estimated_height > column_body_height
            ):
                pending_column_break = True
        label = problem.get("number") or str(index)
        subject = problem.get("subject") or ""
        unit = problem.get("unit") or ""
        source_marker = unit if SOURCE_MARKER_RE.match(str(unit)) else ""
        meta_unit = "" if source_marker else unit
        meta = " / ".join(p for p in [subject, meta_unit] if p)

        layout = problem.get("layout") or {}
        if (
            source_layout_flow
            and not source_text_document
            and isinstance(layout, dict)
        ):
            next_source_anchor_top_hwp = source_target_top_hwp(layout)
        if isinstance(layout, dict) and (
            layout.get("continuation") or layout.get("source_text_flow")
        ):
            line_styles = layout.get("line_styles") or []
            source_lines = layout.get("source_lines") or []
            stem_lines = (problem.get("stem") or "").splitlines()
            for line_index, line in enumerate(stem_lines):
                style = str(line_styles[line_index]) if line_index < len(line_styles) else "body"
                source_line = (
                    source_lines[line_index]
                    if line_index < len(source_lines) and isinstance(source_lines[line_index], dict)
                    else None
                )
                following = (
                    source_lines[line_index + 1]
                    if line_index + 1 < len(source_lines)
                    and isinstance(source_lines[line_index + 1], dict)
                    else None
                )
                target_top = (
                    source_target_top_hwp(layout, float(source_line.get("top_px") or 0.0))
                    if source_line is not None
                    else None
                )
                left_margin = (
                    source_left_margin_hwp(layout, float(source_line.get("left_px") or 0.0))
                    if source_line is not None
                    else 0
                )
                source_spacing = (
                    source_line_spacing_percent(layout, source_line, following, style)
                    if source_line is not None
                    else None
                )
                add_single_para(
                    line,
                    style,
                    math_enabled=False,
                    target_top_hwp=target_top,
                    left_margin_hwp=left_margin,
                    line_spacing_percent=source_spacing,
                )
            if layout.get("continuation"):
                para("")
            previous_problem = problem
            continue

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
            previous_problem = problem
            continue

        stem_lines = merge_source_math_stem_lines((problem.get("stem") or "").splitlines())
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
                preserve_inline_math=source_layout_flow and template.key == "kice_math",
            )
            for line in stem_lines[1:]:
                para(
                    line,
                    "body",
                    math_blocks=native_math and template.key == "kice_math",
                    preserve_inline_math=source_layout_flow and template.key == "kice_math",
                )
            if meta:
                para(f"[{meta}]", "small")
        else:
            heading = f"{label}. {problem.get('title') or '문제'}"
            if meta:
                heading += f" [{meta}]"
            para(
                heading,
                "heading",
                math_blocks=native_math and template.key == "kice_math",
                preserve_inline_math=source_layout_flow and template.key == "kice_math",
            )
            for line in stem_lines or [""]:
                para(
                    line,
                    "body",
                    math_blocks=native_math and template.key == "kice_math",
                    preserve_inline_math=source_layout_flow and template.key == "kice_math",
                )

        for rows in problem.get("tables") or []:
            for table_rows in split_table_chunks(rows):
                table_height = estimate_table_height(table_rows)
                _add_table(
                    doc,
                    table_rows,
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
            para(
                line,
                "body",
                math_blocks=native_math and template.key == "kice_math",
                preserve_inline_math=source_layout_flow and template.key == "kice_math",
            )

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
        previous_problem = problem

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

    _save_hwpx_with_hancom_compat(doc, Path(path), native_math=native_math)


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
    full_path = storage.resolve_data_image_path(image_path)
    if full_path is None:
        return
    size = _picture_size(full_path, content_width, max_height)
    if size is None:
        return
    width, height = size
    fmt = _IMG_FORMATS.get(full_path.suffix.lower(), "png")
    picture = doc.add_picture(
        full_path.read_bytes(),
        fmt,
        width=width,
        height=height,
        **(paragraph_attrs or {}),
    )
    paragraph_element = picture.element
    while paragraph_element is not None and _local_name(paragraph_element.tag).lower() != "p":
        paragraph_element = paragraph_element.getparent()
    if paragraph_element is not None:
        _set_paragraph_element_lineseg(
            paragraph_element,
            max(1000, height + 300),
            width=content_width,
            spacing_ratio=0.0,
        )
