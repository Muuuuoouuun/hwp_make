"""PDF-coordinate based editable HWPX writer.

This writer is for exam PDFs where visual fidelity matters more than reflow.
It places PDF text spans, ruled lines, and embedded images at their original
page coordinates using editable HWPX drawing text boxes.
"""
from __future__ import annotations

import io
import os
import re
import sys
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import fitz
from lxml import etree
from PIL import Image

from . import math_text
from .hwpx_writer import _equation_placeholder, _equation_size, _hancom_eqn_script

_VENDOR = Path(__file__).resolve().parent / "_vendor"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))
from hwpx import HwpxDocument  # noqa: E402

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
XML = "http://www.w3.org/XML/1998/namespace"
HWP_PER_PT = 100.0
OPF = "http://www.idpf.org/2007/opf/"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
HV = "http://www.hancom.co.kr/hwpml/2011/version"
HA = "http://www.hancom.co.kr/hwpml/2011/app"
HC = "http://www.hancom.co.kr/hwpml/2011/core"
CONFIG = "urn:oasis:names:tc:opendocument:xmlns:config:1.0"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
HWPX_PKG_META = "http://www.hancom.co.kr/hwpml/2016/meta/pkg#"
ODF_MANIFEST = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"

HWPX_COMPAT_NAMESPACES = {
    "ha": HA,
    "hp": HP,
    "hp10": "http://www.hancom.co.kr/hwpml/2016/paragraph",
    "hs": HS,
    "hc": HC,
    "hh": HH,
    "hhs": "http://www.hancom.co.kr/hwpml/2011/history",
    "hm": "http://www.hancom.co.kr/hwpml/2011/master-page",
    "hpf": "http://www.hancom.co.kr/schema/2011/hpf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "opf": OPF,
    "ooxmlchart": "http://www.hancom.co.kr/hwpml/2016/ooxmlchart",
    "hwpunitchar": "http://www.hancom.co.kr/hwpml/2016/HwpUnitChar",
    "epub": "http://www.idpf.org/2007/ops",
    "config": CONFIG,
}


def _q(tag: str) -> str:
    return f"{{{HP}}}{tag}"


def _opf(tag: str) -> str:
    return f"{{{OPF}}}{tag}"


def _hh(tag: str) -> str:
    return f"{{{HH}}}{tag}"


def _hc(tag: str) -> str:
    return f"{{{HC}}}{tag}"


def _append_xml_child(parent: Any, tag: str, attributes: dict[str, str] | None = None) -> Any:
    child = parent.makeelement(tag, attributes or {})
    parent.append(child)
    return child


def _insert_before_child(parent: Any, child: Any, before: Any | None) -> None:
    if before is None:
        parent.append(child)
        return
    children = list(parent)
    try:
        index = children.index(before)
    except ValueError:
        parent.append(child)
        return
    parent.insert(index, child)


def _hwp(value_pt: float) -> int:
    return int(round(float(value_pt) * HWP_PER_PT))


def _pdf_page_orientation(page: fitz.Page) -> str:
    return "WIDELY" if page.rect.width > page.rect.height else "PORTRAIT"


def _set_common_size(element: Any, width_pt: float, height_pt: float) -> None:
    width = str(max(1, _hwp(width_pt)))
    height = str(max(1, _hwp(height_pt)))
    for tag in ("orgSz", "curSz", "sz"):
        node = element.find(_q(tag))
        if node is not None:
            node.set("width", width)
            node.set("height", height)


def _set_abs_position(element: Any, x_pt: float, y_pt: float, width_pt: float, height_pt: float) -> None:
    _set_common_size(element, width_pt, height_pt)
    pos = element.find(_q("pos"))
    if pos is None:
        return
    pos.set("treatAsChar", "0")
    pos.set("affectLSpacing", "0")
    pos.set("flowWithText", "0")
    pos.set("allowOverlap", "1")
    pos.set("holdAnchorAndSO", "0")
    pos.set("vertRelTo", "PAPER")
    pos.set("horzRelTo", "PAPER")
    pos.set("vertAlign", "TOP")
    pos.set("horzAlign", "LEFT")
    pos.set("vertOffset", str(_hwp(y_pt)))
    pos.set("horzOffset", str(_hwp(x_pt)))


def _set_z_order(element: Any, z_order: int) -> None:
    element.set("zOrder", str(max(0, int(z_order))))


def _set_invisible_line_shape(element: Any) -> None:
    line_shape = element.find(_q("lineShape"))
    if line_shape is None:
        return
    # Hancom Viewer is stricter than rhwp about zero-width line shapes.
    line_shape.set("style", "SOLID")
    line_shape.set("width", "1")
    line_shape.set("color", "#FFFFFF")
    line_shape.set("alpha", "0")


def _next_z(counter: list[int]) -> int:
    value = counter[0]
    counter[0] += 1
    return value


def _paragraph_id() -> str:
    return str(uuid4().int & 0x7FFFFFFF)


def _font_for_span(span: dict[str, Any]) -> str:
    font = str(span.get("font") or "")
    recovered = _recover_pdf_font_name(font)
    if "Times" in font or "NewRoman" in font:
        return "Times New Roman"
    if "Gulim" in font or "\uad74\ub9bc" in recovered:
        return "GulimChe"
    if "HaansoftBatang" in font or "HCRBatang" in font or "Batang" in font:
        return "HCR Batang"
    if "\uc2e0\uadf8\ub798\ud53d" in recovered or "\uadf8\ub798\ud53d" in recovered:
        return "HYGraphic-Medium"
    if "\uacac\uace0\ub515" in recovered:
        return "HYGothic-Extra"
    if "\ud0dc\uace0\ub515" in recovered or "\uace0\ub515" in recovered:
        return "HYGothic-Medium"
    if "\ub514\ub098\ub8e8" in recovered:
        return "HYHeadLine-Medium"
    if "\uacac\uba85\uc870" in recovered:
        return "HYMyeongJo-Extra"
    return "HYSinMyeongJo-Medium"


def _recover_pdf_font_name(font: str) -> str:
    try:
        return font.encode("latin-1").decode("cp949")
    except UnicodeError:
        return font


def _bold_for_span(span: dict[str, Any]) -> bool:
    font = str(span.get("font") or "").lower()
    flags = int(span.get("flags") or 0)
    return "bold" in font or bool(flags & 16)


_PDF_FONT_FACES = (
    "신명 중명조",
    "한양신명조",
    "HY신명조",
    "돋움",
    "중고딕",
    "신명 중고딕",
    "HYSinMyeongJo-Medium",
    "HYMyeongJo-Extra",
    "HYGraphic-Medium",
    "HYGothic-Medium",
    "HYGothic-Extra",
    "HYHeadLine-Medium",
    "Times New Roman",
    "GulimChe",
    "HCR Batang",
)

_FLOW_CHAR_RATIO = 95
_FLOW_CHAR_SPACING = -5
_FLOW_BODY_LINE_SPACING = 165


def _ensure_pdf_font_faces(header: Any) -> None:
    for face in _PDF_FONT_FACES:
        _ensure_header_font_face(header, face)


def _ensure_header_font_face(header: Any, face: str) -> None:
    changed = False
    for fontface in header.element.findall(f".//{_hh('fontface')}"):
        fonts = fontface.findall(_hh("font"))
        if any(font.get("face") == face for font in fonts):
            continue
        next_id = 0
        for font in fonts:
            try:
                next_id = max(next_id, int(font.get("id") or 0) + 1)
            except ValueError:
                continue
        if fonts:
            new_font = deepcopy(fonts[-1])
            new_font.attrib.clear()
        else:
            new_font = fontface.makeelement(_hh("font"), {})
            type_info = new_font.makeelement(
                _hh("typeInfo"),
                {
                    "familyType": "FCAT_GOTHIC",
                    "weight": "6",
                    "proportion": "4",
                    "contrast": "0",
                    "strokeVariation": "1",
                    "armStyle": "1",
                    "letterform": "1",
                    "midline": "1",
                    "xHeight": "1",
                },
            )
            new_font.append(type_info)
        new_font.set("id", str(next_id))
        new_font.set("face", face)
        new_font.set("type", "TTF")
        new_font.set("isEmbedded", "0")
        fontface.append(new_font)
        fontface.set("fontCnt", str(len(fontface.findall(_hh("font")))))
        changed = True
    fontfaces = header.element.find(f".//{_hh('fontfaces')}")
    if fontfaces is not None:
        fontfaces.set("itemCnt", str(len(fontfaces.findall(_hh("fontface")))))
    if changed:
        header.mark_dirty()


def _ensure_char_metric_child(char_pr: Any, local_name: str) -> Any:
    child = char_pr.find(_hh(local_name))
    if child is not None:
        return child
    child = char_pr.makeelement(_hh(local_name), {})
    order = ["fontRef", "ratio", "spacing", "relSz", "offset"]
    insert_at = 0
    if local_name in order:
        target_index = order.index(local_name)
        for index, existing in enumerate(list(char_pr)):
            existing_local = etree.QName(existing).localname
            if existing_local in order and order.index(existing_local) < target_index:
                insert_at = index + 1
    char_pr.insert(insert_at, child)
    return child


def _apply_char_metrics(header: Any, char_pr_ids: list[str], *, ratio: int, spacing: int) -> None:
    changed = False
    lang_attrs = ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")
    for char_pr_id in sorted(set(str(value) for value in char_pr_ids if value is not None)):
        char_pr = header.element.find(f".//{_hh('charPr')}[@id='{char_pr_id}']")
        if char_pr is None:
            continue
        for local_name, value in (("ratio", ratio), ("spacing", spacing)):
            child = _ensure_char_metric_child(char_pr, local_name)
            safe_value = str(int(value))
            for attr in lang_attrs:
                if child.get(attr) != safe_value:
                    child.set(attr, safe_value)
                    changed = True
    if changed:
        header.mark_dirty()


def _latin_ratio(text: str) -> float:
    meaningful = [ch for ch in text if ch.isalpha() or "\uac00" <= ch <= "\ud7a3"]
    if not meaningful:
        return 0.0
    latin = sum(1 for ch in meaningful if ("A" <= ch <= "Z") or ("a" <= ch <= "z"))
    return latin / len(meaningful)


def _flow_font_for_span(span: dict[str, Any]) -> str:
    text = str(span.get("text") or "")
    font = str(span.get("font") or "")
    recovered = _recover_pdf_font_name(font)
    if _latin_ratio(text) >= 0.55 or "Times" in font or "NewRoman" in font:
        return "Times New Roman"
    if _bold_for_span(span):
        return "돋움"
    if any(token in recovered for token in ("고딕", "그래픽", "굴림")):
        return "돋움"
    if any(token in recovered for token in ("명조", "바탕")):
        return "신명 중명조"
    return "신명 중명조"


def _flow_size_for_span(span: dict[str, Any]) -> float:
    try:
        size = float(span.get("size") or 10.0)
    except (TypeError, ValueError):
        size = 10.0
    if size <= 8.6:
        return 8.8
    if size <= 12.8:
        return 10.0
    if size <= 15.0:
        return 12.0
    return min(16.0, round(size, 1))


def _add_text_box(
    doc: HwpxDocument,
    anchor: Any,
    *,
    x_pt: float,
    y_pt: float,
    width_pt: float,
    height_pt: float,
    text: str,
    char_pr_id_ref: str,
    para_pr_id_ref: str,
    z_order: int,
) -> None:
    shape = doc.add_rectangle(
        width=max(1, _hwp(width_pt)),
        height=max(1, _hwp(height_pt)),
        line_color="#FFFFFF",
        line_width="1",
        treat_as_char=False,
        paragraph=anchor,
    )
    element = shape.element
    _set_z_order(element, z_order)
    _set_abs_position(element, x_pt, y_pt, width_pt, height_pt)
    _set_invisible_line_shape(element)

    draw = element.makeelement(_q("drawText"), {})
    draw.set("lastWidth", str(max(1, _hwp(width_pt))))
    draw.set("name", "")
    draw.set("editable", "1")
    margin = _append_xml_child(draw, _q("textMargin"))
    for key in ("left", "right", "top", "bottom"):
        margin.set(key, "0")
    sub = _append_xml_child(draw, _q("subList"))
    _set_text_box_sublist_attrs(sub, width_pt, height_pt)
    paragraph = _append_xml_child(sub, _q("p"))
    paragraph.set("id", _paragraph_id())
    paragraph.set("paraPrIDRef", str(para_pr_id_ref))
    paragraph.set("styleIDRef", "0")
    paragraph.set("pageBreak", "0")
    paragraph.set("columnBreak", "0")
    paragraph.set("merged", "0")
    run = _append_xml_child(paragraph, _q("run"))
    run.set("charPrIDRef", str(char_pr_id_ref))
    node = _append_xml_child(run, _q("t"))
    node.set(f"{{{XML}}}space", "preserve")
    node.text = text
    _append_text_box_lineseg(paragraph, width_pt, height_pt)

    shadow = element.find(_q("shadow"))
    _insert_before_child(element, draw, shadow)


def _append_pdf_equation(run: Any, script: str, equation_index: int) -> None:
    equation = _append_xml_child(
        run,
        _q("equation"),
        {
            "id": str(1900000000 + equation_index),
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
    _append_xml_child(
        equation,
        _q("sz"),
        {"width": "0", "widthRelTo": "ABSOLUTE", "height": "0", "heightRelTo": "ABSOLUTE", "protect": "0"},
    )
    _append_xml_child(
        equation,
        _q("pos"),
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
    _append_xml_child(equation, _q("outMargin"), {"left": "56", "right": "56", "top": "0", "bottom": "0"})
    comment = _append_xml_child(equation, _q("shapeComment"))
    comment.text = "수식입니다."
    script_node = _append_xml_child(equation, _q("script"))
    script_node.text = script
    placeholder = _append_xml_child(run, _q("t"))
    placeholder.set(f"{{{XML}}}space", "preserve")
    placeholder.text = _equation_placeholder(script)


def _append_pdf_text_run(paragraph: Any, text: str, char_pr_id_ref: str) -> None:
    run = _append_xml_child(paragraph, _q("run"))
    run.set("charPrIDRef", str(char_pr_id_ref))
    node = _append_xml_child(run, _q("t"))
    node.set(f"{{{XML}}}space", "preserve")
    node.text = text


def _append_pdf_runs(
    paragraph: Any,
    runs: list[tuple[str, str]],
    *,
    equation_counter: list[int] | None = None,
    native_math: bool = False,
) -> dict[str, int]:
    stats = {"native_equations": 0, "source_math_segments": 0}
    for text, char_pr_id_ref in runs:
        if text == "":
            continue
        for segment, is_math in math_text.split_math_text(text):
            if segment == "":
                continue
            if is_math:
                stats["source_math_segments"] += 1
            if is_math and native_math and equation_counter is not None:
                script = _hancom_eqn_script(segment)
                if script:
                    equation_counter[0] += 1
                    stats["native_equations"] += 1
                    run = _append_xml_child(paragraph, _q("run"))
                    run.set("charPrIDRef", str(char_pr_id_ref))
                    _append_pdf_equation(run, script, equation_counter[0])
                    continue
            _append_pdf_text_run(paragraph, segment, char_pr_id_ref)
    return stats


def _text_runs_height_pt(runs: list[tuple[str, str]], height_pt: float, *, native_math: bool = False) -> float:
    result = float(height_pt)
    if not native_math:
        return result
    for text, _ in runs:
        for segment, is_math in math_text.split_math_text(text):
            if not is_math:
                continue
            script = _hancom_eqn_script(segment)
            if script:
                result = max(result, (_equation_size(script)[1] / HWP_PER_PT) + 2.0)
    return result


def _add_text_box_runs(
    doc: HwpxDocument,
    anchor: Any,
    *,
    x_pt: float,
    y_pt: float,
    width_pt: float,
    height_pt: float,
    runs: list[tuple[str, str]],
    para_pr_id_ref: str,
    z_order: int,
    equation_counter: list[int] | None = None,
    native_math: bool = False,
) -> dict[str, int]:
    if not runs:
        return {"native_equations": 0, "source_math_segments": 0}
    height_pt = _text_runs_height_pt(runs, height_pt, native_math=native_math)
    shape = doc.add_rectangle(
        width=max(1, _hwp(width_pt)),
        height=max(1, _hwp(height_pt)),
        line_color="#FFFFFF",
        line_width="1",
        treat_as_char=False,
        paragraph=anchor,
    )
    element = shape.element
    _set_z_order(element, z_order)
    _set_abs_position(element, x_pt, y_pt, width_pt, height_pt)
    _set_invisible_line_shape(element)

    draw = element.makeelement(_q("drawText"), {})
    draw.set("lastWidth", str(max(1, _hwp(width_pt))))
    draw.set("name", "")
    draw.set("editable", "1")
    margin = _append_xml_child(draw, _q("textMargin"))
    for key in ("left", "right", "top", "bottom"):
        margin.set(key, "0")
    sub = _append_xml_child(draw, _q("subList"))
    _set_text_box_sublist_attrs(sub, width_pt, height_pt)
    paragraph = _append_xml_child(sub, _q("p"))
    paragraph.set("id", _paragraph_id())
    paragraph.set("paraPrIDRef", str(para_pr_id_ref))
    paragraph.set("styleIDRef", "0")
    paragraph.set("pageBreak", "0")
    paragraph.set("columnBreak", "0")
    paragraph.set("merged", "0")
    run_stats = _append_pdf_runs(
        paragraph,
        runs,
        equation_counter=equation_counter or [0],
        native_math=native_math,
    )
    _append_text_box_lineseg(paragraph, width_pt, height_pt)

    shadow = element.find(_q("shadow"))
    _insert_before_child(element, draw, shadow)
    return run_stats


def _set_text_box_sublist_attrs(sub: Any, width_pt: float, height_pt: float) -> None:
    sub.set("id", "")
    sub.set("textDirection", "HORIZONTAL")
    sub.set("lineWrap", "BREAK")
    sub.set("vertAlign", "TOP")
    sub.set("linkListIDRef", "0")
    sub.set("linkListNextIDRef", "0")
    sub.set("textWidth", str(max(1, _hwp(width_pt))))
    sub.set("textHeight", str(max(1, _hwp(height_pt))))
    sub.set("hasTextRef", "0")
    sub.set("hasNumRef", "0")


def _append_text_box_lineseg(paragraph: Any, width_pt: float, height_pt: float) -> None:
    height = max(1, _hwp(height_pt))
    line_seg_array = _append_xml_child(paragraph, _q("linesegarray"))
    _append_xml_child(
        line_seg_array,
        _q("lineseg"),
        {
            "textpos": "0",
            "vertpos": "0",
            "vertsize": str(height),
            "textheight": str(height),
            "baseline": str(max(1, int(height * 0.85))),
            "spacing": str(max(0, int(height * 0.15))),
            "horzpos": "0",
            "horzsize": str(max(1, _hwp(width_pt))),
            "flags": "393216",
        },
    )


def _add_filled_rect(
    doc: HwpxDocument,
    anchor: Any,
    *,
    x_pt: float,
    y_pt: float,
    width_pt: float,
    height_pt: float,
    color: str = "#000000",
    z_order: int = 0,
) -> None:
    shape = doc.add_rectangle(
        width=max(1, _hwp(width_pt)),
        height=max(1, _hwp(height_pt)),
        line_color=color,
        line_width="1",
        fill_color=color,
        treat_as_char=False,
        paragraph=anchor,
    )
    _set_z_order(shape.element, z_order)
    _set_abs_position(shape.element, x_pt, y_pt, width_pt, height_pt)


def _add_rounded_rect_outline(
    doc: HwpxDocument,
    anchor: Any,
    *,
    x_pt: float,
    y_pt: float,
    width_pt: float,
    height_pt: float,
    line_width_pt: float,
    color: str = "#000000",
    z_order: int = 0,
) -> None:
    shape = doc.add_rectangle(
        width=max(1, _hwp(width_pt)),
        height=max(1, _hwp(height_pt)),
        ratio=35,
        line_color=color,
        line_width=str(max(1, _hwp(line_width_pt))),
        treat_as_char=False,
        paragraph=anchor,
    )
    _set_z_order(shape.element, z_order)
    _set_abs_position(shape.element, x_pt, y_pt, width_pt, height_pt)


def _add_rect_outline(
    doc: HwpxDocument,
    anchor: Any,
    *,
    x_pt: float,
    y_pt: float,
    width_pt: float,
    height_pt: float,
    line_width_pt: float,
    color: str = "#000000",
    z_order: int = 0,
) -> None:
    shape = doc.add_rectangle(
        width=max(1, _hwp(width_pt)),
        height=max(1, _hwp(height_pt)),
        line_color=color,
        line_width=str(max(1, _hwp(line_width_pt))),
        treat_as_char=False,
        paragraph=anchor,
    )
    _set_z_order(shape.element, z_order)
    _set_abs_position(shape.element, x_pt, y_pt, width_pt, height_pt)


def _set_line_position(element: Any, x_pt: float, y_pt: float) -> None:
    pos = element.find(_q("pos"))
    if pos is None:
        return
    pos.set("treatAsChar", "0")
    pos.set("affectLSpacing", "0")
    pos.set("flowWithText", "0")
    pos.set("allowOverlap", "1")
    pos.set("holdAnchorAndSO", "0")
    pos.set("vertRelTo", "PAPER")
    pos.set("horzRelTo", "PAPER")
    pos.set("vertAlign", "TOP")
    pos.set("horzAlign", "LEFT")
    pos.set("vertOffset", str(_hwp(y_pt)))
    pos.set("horzOffset", str(_hwp(x_pt)))


def _add_straight_line(
    doc: HwpxDocument,
    anchor: Any,
    *,
    x0_pt: float,
    y0_pt: float,
    x1_pt: float,
    y1_pt: float,
    line_width_pt: float,
    color: str = "#000000",
    z_order: int = 0,
) -> None:
    horizontal = abs(y1_pt - y0_pt) <= abs(x1_pt - x0_pt)
    if horizontal:
        length_pt = max(line_width_pt, abs(x1_pt - x0_pt))
        shape = anchor.add_line(
            start_x=0,
            start_y=0,
            end_x=_hwp(length_pt),
            end_y=0,
            line_color=color,
            line_width=str(max(1, _hwp(line_width_pt))),
            treat_as_char=False,
        )
        _set_line_position(shape.element, min(x0_pt, x1_pt), y0_pt)
    else:
        length_pt = max(line_width_pt, abs(y1_pt - y0_pt))
        shape = anchor.add_line(
            start_x=0,
            start_y=0,
            end_x=0,
            end_y=_hwp(length_pt),
            line_color=color,
            line_width=str(max(1, _hwp(line_width_pt))),
            treat_as_char=False,
        )
        _set_line_position(shape.element, x0_pt, min(y0_pt, y1_pt))
    _set_z_order(shape.element, z_order)


def _is_hidden_header_rect(rect: fitz.Rect) -> bool:
    # Exam-form badges and header rules live in this area and matter for
    # whole-page sync. Preserve them instead of treating them as hidden chrome.
    return False


def _line_dedupe_key(
    kind: str,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    width_pt: float,
    color: str,
) -> tuple[str, int, int, int, int, int, str]:
    return (
        kind,
        int(round(x0 * 10)),
        int(round(y0 * 10)),
        int(round(x1 * 10)),
        int(round(y1 * 10)),
        int(round(width_pt * 100)),
        color,
    )


def _add_line_rects(doc: HwpxDocument, anchor: Any, page: fitz.Page, z_counter: list[int]) -> int:
    count = 0
    seen: set[tuple[str, int, int, int, int, int, str]] = set()
    for drawing in page.get_drawings():
        width_pt = max(0.25, float(drawing.get("width") or 0.6))
        color_hex = _pdf_color_hex(drawing.get("color"), "#000000")
        fill_hex = _pdf_color_hex(drawing.get("fill"), "")
        items = drawing.get("items", [])
        drawing_rect = drawing.get("rect")
        if drawing_rect is not None:
            drawing_rect = fitz.Rect(drawing_rect)
            if _is_hidden_header_rect(drawing_rect):
                continue
            if (
                drawing.get("color") is not None
                and len(items) >= 8
                and drawing_rect.width <= 140
                and drawing_rect.height <= 70
                and all(item and item[0] == "l" for item in items)
            ):
                _add_rounded_rect_outline(
                    doc,
                    anchor,
                    x_pt=drawing_rect.x0,
                    y_pt=drawing_rect.y0,
                    width_pt=drawing_rect.width,
                    height_pt=drawing_rect.height,
                    line_width_pt=width_pt,
                    color=color_hex,
                    z_order=_next_z(z_counter),
                )
                count += 1
                continue
        for item in items:
            if not item:
                continue
            kind = item[0]
            if kind == "l":
                p0, p1 = item[1], item[2]
                x0, y0, x1, y1 = float(p0.x), float(p0.y), float(p1.x), float(p1.y)
                key = _line_dedupe_key("l", x0, y0, x1, y1, width_pt, color_hex)
                if key in seen:
                    continue
                seen.add(key)
                if abs(y1 - y0) <= 0.35:
                    _add_straight_line(
                        doc,
                        anchor,
                        x0_pt=x0,
                        y0_pt=y0,
                        x1_pt=x1,
                        y1_pt=y1,
                        line_width_pt=width_pt,
                        color=color_hex,
                        z_order=_next_z(z_counter),
                    )
                    count += 1
                elif abs(x1 - x0) <= 0.35:
                    _add_straight_line(
                        doc,
                        anchor,
                        x0_pt=x0,
                        y0_pt=y0,
                        x1_pt=x1,
                        y1_pt=y1,
                        line_width_pt=width_pt,
                        color=color_hex,
                        z_order=_next_z(z_counter),
                    )
                    count += 1
            elif kind == "re":
                rect = item[1]
                if fill_hex and fill_hex.upper() not in {"#FFFFFF", "#FFFFFE"}:
                    key = _line_dedupe_key(
                        "re_fill",
                        float(rect.x0),
                        float(rect.y0),
                        float(rect.x1),
                        float(rect.y1),
                        width_pt,
                        fill_hex,
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    _add_filled_rect(
                        doc,
                        anchor,
                        x_pt=float(rect.x0),
                        y_pt=float(rect.y0),
                        width_pt=float(rect.width),
                        height_pt=float(rect.height),
                        color=fill_hex,
                        z_order=_next_z(z_counter),
                    )
                    count += 1
                if drawing.get("color") is not None:
                    key = _line_dedupe_key(
                        "re_outline",
                        float(rect.x0),
                        float(rect.y0),
                        float(rect.x1),
                        float(rect.y1),
                        width_pt,
                        color_hex,
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    _add_rect_outline(
                        doc,
                        anchor,
                        x_pt=float(rect.x0),
                        y_pt=float(rect.y0),
                        width_pt=float(rect.width),
                        height_pt=float(rect.height),
                        line_width_pt=width_pt,
                        color=color_hex,
                        z_order=_next_z(z_counter),
                    )
                    count += 1
    return count


def _pdf_color_hex(color: Any, default: str) -> str:
    if not color or len(color) < 3:
        return default
    return "#" + "".join(f"{max(0, min(255, int(c * 255))):02X}" for c in color[:3])


def _png_from_extracted_image(data: bytes, ext: str) -> bytes:
    image = Image.open(io.BytesIO(data))
    out = io.BytesIO()
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGB")
    image.save(out, format="PNG")
    return out.getvalue()


def _image_info_colorspace(info: dict[str, Any]) -> str:
    for key in ("cs-name", "colorspace", "color_space", "colorspace_name"):
        value = info.get(key)
        if value:
            return str(value)
    return ""


def _rect_intersection_area(a: fitz.Rect, b: fitz.Rect) -> float:
    left = max(a.x0, b.x0)
    top = max(a.y0, b.y0)
    right = min(a.x1, b.x1)
    bottom = min(a.y1, b.y1)
    if right <= left or bottom <= top:
        return 0.0
    return (right - left) * (bottom - top)


def _overlaps_text(rect: fitz.Rect, text_rects: list[fitz.Rect]) -> bool:
    area = max(1.0, rect.width * rect.height)
    for text_rect in text_rects:
        if _rect_intersection_area(rect, text_rect) > area * 0.02:
            return True
    return False


def _covers_page_area(page: fitz.Page, rect: fitz.Rect, *, threshold: float = 0.5) -> bool:
    page_area = max(1.0, float(page.rect.width * page.rect.height))
    covered_area = _rect_intersection_area(page.rect, rect)
    return covered_area / page_area >= threshold


def _add_pdf_images(
    doc: HwpxDocument,
    anchor: Any,
    pdf_doc: fitz.Document,
    page: fitz.Page,
    text_rects: list[fitz.Rect],
    z_counter: list[int],
) -> tuple[int, int]:
    count = 0
    full_page_count = 0
    for info in page.get_image_info(xrefs=True):
        rect = fitz.Rect(info["bbox"])
        if rect.width < 2 or rect.height < 2:
            continue
        if _overlaps_text(rect, text_rects):
            continue
        xref = int(info.get("xref") or 0)
        if xref <= 0:
            continue
        try:
            pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0), clip=rect, alpha=False)
            image_data = pix.tobytes("png")
        except Exception:
            continue
        item_id = doc.add_image(image_data, "png")
        pic = anchor.add_picture(
            item_id,
            width=max(1, _hwp(rect.width)),
            height=max(1, _hwp(rect.height)),
            treat_as_char=False,
        )
        _set_z_order(pic.element, _next_z(z_counter))
        _set_abs_position(pic.element, rect.x0, rect.y0, rect.width, rect.height)
        count += 1
        if _covers_page_area(page, rect):
            full_page_count += 1
    return count, full_page_count


def _iter_text_spans(page: fitz.Page) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = str(span.get("text") or "")
                if text == "":
                    continue
                bbox = span.get("bbox")
                if not bbox:
                    continue
                rect = fitz.Rect(bbox)
                if rect.x0 < 210 and rect.y1 < 150 and "홀수형" in text:
                    continue
                spans.append(span)
    return spans


def _iter_text_lines(page: fitz.Page) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans: list[dict[str, Any]] = []
            for span in line.get("spans", []):
                text = str(span.get("text") or "")
                if text == "":
                    continue
                bbox = span.get("bbox")
                if not bbox:
                    continue
                rect = fitz.Rect(bbox)
                if rect.x0 < 210 and rect.y1 < 150 and "??섑삎" in text:
                    continue
                spans.append(span)
            if not spans:
                continue
            lines.append({"spans": spans, "bbox": _union_rect([fitz.Rect(span["bbox"]) for span in spans])})
    return lines


def _union_rect(rects: list[fitz.Rect]) -> fitz.Rect:
    if not rects:
        return fitz.Rect(0, 0, 0, 0)
    result = fitz.Rect(rects[0])
    for rect in rects[1:]:
        result.include_rect(rect)
    return result


def _text_rects(spans: list[dict[str, Any]]) -> list[fitz.Rect]:
    return [fitz.Rect(span["bbox"]) for span in spans if span.get("text", "").strip()]


def _ensure_char_pr(
    doc: HwpxDocument,
    styles: dict[tuple[str, float, bool], str],
    span: dict[str, Any],
) -> str:
    size = _flow_size_for_span(span)
    font = _flow_font_for_span(span)
    bold = _bold_for_span(span)
    key = (font, size, bold)
    char_pr = styles.get(key)
    if char_pr is None:
        char_pr = doc.ensure_run_style(font=font, size=size, bold=bold)
        _apply_char_metrics(doc.headers[0], [char_pr], ratio=_FLOW_CHAR_RATIO, spacing=_FLOW_CHAR_SPACING)
        styles[key] = char_pr
    return char_pr


def _span_text_runs(
    doc: HwpxDocument,
    styles: dict[tuple[str, float, bool], str],
    spans: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    runs: list[tuple[str, str]] = []
    previous_rect: fitz.Rect | None = None
    previous_size = 10.0
    for span in spans:
        text = math_text.normalize_recognized_math_text(str(span.get("text") or ""))
        if text == "":
            continue
        rect = fitz.Rect(span["bbox"])
        size = float(span.get("size") or previous_size)
        if previous_rect is not None and not text.startswith(" "):
            gap = rect.x0 - previous_rect.x1
            if gap > max(2.2, previous_size * 0.22):
                runs.append((" ", _ensure_char_pr(doc, styles, span)))
        runs.append((text, _ensure_char_pr(doc, styles, span)))
        previous_rect = rect
        previous_size = size
    return runs


def _expanded_text_width(
    page_rect: fitz.Rect,
    bbox: fitz.Rect,
    x_pt: float,
    *,
    pad_x: float,
    extra_right_pt: float,
) -> float:
    desired = bbox.width + pad_x * 2 + extra_right_pt
    right_limit = float(page_rect.width) - 28.0
    page_center = float(page_rect.width) / 2.0
    if bbox.x0 < page_center and bbox.x1 < page_center + 20.0:
        right_limit = min(right_limit, page_center - 4.0)
    return max(2.0, min(desired, max(2.0, right_limit - x_pt)))


def _serialize_xml(root: Any) -> bytes:
    return etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        standalone=True,
    )


def _ensure_compatible_document(header: Any) -> Any:
    compatible = header.find(_hh("compatibleDocument"))
    if compatible is None:
        compatible = header.makeelement(_hh("compatibleDocument"), {})
        header.append(compatible)
    compatible.set("targetProgram", "HWP201X")
    if compatible.find(_hh("layoutCompatibility")) is None:
        compatible.append(compatible.makeelement(_hh("layoutCompatibility"), {}))
    return compatible


def _ensure_begin_num(header: Any) -> Any:
    begin_num = header.find(_hh("beginNum"))
    if begin_num is None:
        begin_num = header.makeelement(_hh("beginNum"), {})
        header.insert(0, begin_num)
    for name in ("page", "footnote", "endnote", "pic", "tbl", "equation"):
        begin_num.set(name, begin_num.get(name) or "1")
    return begin_num


def _ensure_doc_option(header: Any) -> Any:
    doc_option = header.find(_hh("docOption"))
    if doc_option is None:
        doc_option = header.makeelement(_hh("docOption"), {})
        header.append(doc_option)
    link_info = doc_option.find(_hh("linkinfo"))
    if link_info is None:
        link_info = doc_option.makeelement(_hh("linkinfo"), {})
        doc_option.append(link_info)
    link_info.set("path", link_info.get("path") or "")
    link_info.set("pageInherit", link_info.get("pageInherit") or "0")
    link_info.set("footnoteInherit", link_info.get("footnoteInherit") or "0")
    return doc_option


def _ensure_header_text_child(header: Any, name: str, text: str) -> Any:
    child = header.find(_hh(name))
    if child is None:
        child = header.makeelement(_hh(name), {})
        header.append(child)
    if not (child.text or "").strip():
        child.text = text
    return child


def _ensure_track_change_config(header: Any) -> Any:
    config = header.find(_hh("trackchageConfig"))
    if config is None:
        config = header.makeelement(_hh("trackchageConfig"), {})
        header.append(config)
    config.set("flags", config.get("flags") or "56")
    return config


def _ensure_hancom_header_shell(header: Any, *, section_count: int | None = None) -> None:
    header.set("version", "1.5")
    if section_count is not None:
        header.set("secCnt", str(max(1, int(section_count))))

    ordered_children = [
        _ensure_begin_num(header),
        header.find(_hh("refList")),
        _ensure_compatible_document(header),
        _ensure_doc_option(header),
        _ensure_header_text_child(header, "metaTag", '{"name":""}'),
        _ensure_track_change_config(header),
    ]

    existing = list(header)
    ordered_ids = {id(child) for child in ordered_children if child is not None}
    remaining = [child for child in existing if id(child) not in ordered_ids]
    for child in existing:
        header.remove(child)
    for child in ordered_children:
        if child is not None:
            header.append(child)
    for child in remaining:
        header.append(child)


def _ensure_section_root_namespace(section: Any) -> bool:
    if etree.QName(section).localname != "sec" or section.tag == f"{{{HS}}}sec":
        return False
    section.tag = f"{{{HS}}}sec"
    return True


def _section_names_from_payloads(payloads: dict[str, bytes]) -> list[str]:
    names = [
        name
        for name in payloads
        if re.fullmatch(r"Contents/section\d+\.xml", name)
    ]
    return sorted(names, key=lambda value: int(re.search(r"section(\d+)", value).group(1)))  # type: ignore[union-attr]


def _ensure_attributes(element: Any, defaults: dict[str, str], *, overwrite: bool = False) -> bool:
    changed = False
    for key, value in defaults.items():
        if overwrite or element.get(key) is None:
            if element.get(key) != value:
                element.set(key, value)
                changed = True
    return changed


def _ensure_single_child(parent: Any, local_name: str, attrs: dict[str, str] | None = None) -> tuple[Any, bool]:
    children = parent.findall(_q(local_name))
    changed = False
    if children:
        child = children[0]
        for duplicate in children[1:]:
            parent.remove(duplicate)
            changed = True
    else:
        child = parent.makeelement(_q(local_name), {})
        parent.append(child)
        changed = True
    if attrs:
        changed = _ensure_attributes(child, attrs) or changed
    return child, changed


def _ensure_note_properties(sec_pr: Any, local_name: str, *, end_note: bool) -> tuple[Any, bool]:
    note, changed = _ensure_single_child(sec_pr, local_name)
    specs = [
        ("autoNumFormat", {"type": "DIGIT", "userChar": "", "prefixChar": "", "suffixChar": ")", "supscript": "0"}),
        (
            "noteLine",
            {
                "length": "14692344" if end_note else "-1",
                "type": "SOLID",
                "width": "0.12 mm",
                "color": "#000000",
            },
        ),
        (
            "noteSpacing",
            {
                "betweenNotes": "0" if end_note else "283",
                "belowLine": "567",
                "aboveLine": "850",
            },
        ),
        ("numbering", {"type": "CONTINUOUS", "newNum": "1"}),
        ("placement", {"place": "END_OF_DOCUMENT" if end_note else "EACH_COLUMN", "beneathText": "0"}),
    ]
    ordered: list[Any] = []
    for child_name, attrs in specs:
        child, child_changed = _ensure_single_child(note, child_name, attrs)
        ordered.append(child)
        changed = child_changed or changed
    changed = _reorder_children(note, ordered) or changed
    return note, changed


def _ensure_page_border_fills(sec_pr: Any, border_fill_id_ref: str) -> tuple[list[Any], bool]:
    changed = False
    by_type: dict[str, Any] = {}
    for element in list(sec_pr.findall(_q("pageBorderFill"))):
        border_type = element.get("type") or ""
        if border_type in {"BOTH", "EVEN", "ODD"} and border_type not in by_type:
            by_type[border_type] = element
            continue
        sec_pr.remove(element)
        changed = True

    ordered: list[Any] = []
    for border_type in ("BOTH", "EVEN", "ODD"):
        element = by_type.get(border_type)
        if element is None:
            element = sec_pr.makeelement(_q("pageBorderFill"), {})
            sec_pr.append(element)
            changed = True
        changed = _ensure_attributes(
            element,
            {
                "type": border_type,
                "borderFillIDRef": border_fill_id_ref,
                "textBorder": "PAPER",
                "headerInside": "0",
                "footerInside": "0",
                "fillArea": "PAPER",
            },
            overwrite=True,
        ) or changed
        offset, offset_changed = _ensure_single_child(
            element,
            "offset",
            {"left": "1417", "right": "1417", "top": "1417", "bottom": "1417"},
        )
        changed = offset_changed or changed
        changed = _reorder_children(element, [offset]) or changed
        ordered.append(element)
    return ordered, changed


def _reorder_children(parent: Any, ordered_children: list[Any]) -> bool:
    existing = list(parent)
    ordered_ids = {id(child) for child in ordered_children}
    remaining = [child for child in existing if id(child) not in ordered_ids]
    target = [*ordered_children, *remaining]
    if existing == target:
        return False
    for child in existing:
        parent.remove(child)
    for child in target:
        parent.append(child)
    return True


def _ensure_section_properties_shell(section: Any, *, border_fill_id_ref: str) -> bool:
    sec_pr = section.find(f".//{_q('secPr')}")
    if sec_pr is None:
        return False
    changed = _ensure_attributes(
        sec_pr,
        {
            "id": "",
            "textDirection": "HORIZONTAL",
            "spaceColumns": "1134",
            "tabStop": "8000",
            "tabStopVal": "4000",
            "tabStopUnit": "HWPUNIT",
            "outlineShapeIDRef": "1",
            "memoShapeIDRef": "0",
            "textVerticalWidthHead": "0",
            "masterPageCnt": "0",
        },
    )
    grid, child_changed = _ensure_single_child(
        sec_pr,
        "grid",
        {"lineGrid": "0", "charGrid": "0", "wonggojiFormat": "0"},
    )
    changed = child_changed or changed
    start_num, child_changed = _ensure_single_child(
        sec_pr,
        "startNum",
        {"pageStartsOn": "BOTH", "page": "0", "pic": "0", "tbl": "0", "equation": "0"},
    )
    changed = child_changed or changed
    changed = _ensure_attributes(
        start_num,
        {"pageStartsOn": "BOTH", "page": "0", "pic": "0", "tbl": "0", "equation": "0"},
        overwrite=True,
    ) or changed
    visibility, child_changed = _ensure_single_child(
        sec_pr,
        "visibility",
        {
            "hideFirstHeader": "0",
            "hideFirstFooter": "0",
            "hideFirstMasterPage": "0",
            "border": "SHOW_ALL",
            "fill": "SHOW_ALL",
            "hideFirstPageNum": "0",
            "hideFirstEmptyLine": "0",
            "showLineNumber": "0",
        },
    )
    changed = child_changed or changed
    line_number_shape, child_changed = _ensure_single_child(
        sec_pr,
        "lineNumberShape",
        {"restartType": "0", "countBy": "0", "distance": "0", "startNumber": "0"},
    )
    changed = child_changed or changed
    page_pr, child_changed = _ensure_single_child(
        sec_pr,
        "pagePr",
        {"landscape": "PORTRAIT", "width": "59528", "height": "84188", "gutterType": "LEFT_ONLY"},
    )
    changed = child_changed or changed
    margin, child_changed = _ensure_single_child(
        page_pr,
        "margin",
        {"left": "0", "right": "0", "top": "0", "bottom": "0", "header": "0", "footer": "0", "gutter": "0"},
    )
    changed = child_changed or changed
    changed = _reorder_children(page_pr, [margin]) or changed
    foot_note, child_changed = _ensure_note_properties(sec_pr, "footNotePr", end_note=False)
    changed = child_changed or changed
    end_note, child_changed = _ensure_note_properties(sec_pr, "endNotePr", end_note=True)
    changed = child_changed or changed
    page_borders, child_changed = _ensure_page_border_fills(sec_pr, border_fill_id_ref)
    changed = child_changed or changed
    changed = _reorder_children(
        sec_pr,
        [grid, start_num, visibility, line_number_shape, page_pr, foot_note, end_note, *page_borders],
    ) or changed
    return changed


def _ensure_section_run_shell(section: Any) -> bool:
    first_paragraph = section.find(_q("p"))
    if first_paragraph is None:
        return False
    first_run = first_paragraph.find(_q("run"))
    if first_run is None:
        first_run = first_paragraph.makeelement(_q("run"), {"charPrIDRef": "0"})
        first_paragraph.insert(0, first_run)

    changed = False
    sec_pr = first_run.find(_q("secPr"))
    if sec_pr is None:
        sec_pr = first_paragraph.find(f".//{_q('secPr')}")
        if sec_pr is None:
            return changed
        parent = sec_pr.getparent()
        if parent is not None:
            parent.remove(sec_pr)
        first_run.insert(0, sec_pr)
        changed = True

    text_nodes = [child for child in list(first_run) if child.tag == _q("t")]
    moved_text = False
    if text_nodes:
        text_run = first_paragraph.makeelement(_q("run"), {"charPrIDRef": first_run.get("charPrIDRef") or "0"})
        for text_node in text_nodes:
            first_run.remove(text_node)
            text_run.append(text_node)
        first_paragraph.insert(list(first_paragraph).index(first_run) + 1, text_run)
        moved_text = True
        changed = True

    ctrl = first_run.find(_q("ctrl"))
    if ctrl is None:
        ctrl = first_run.makeelement(_q("ctrl"), {})
        changed = True
    col_pr = ctrl.find(_q("colPr"))
    if col_pr is None:
        col_pr = ctrl.makeelement(_q("colPr"), {})
        ctrl.append(col_pr)
        changed = True
    changed = _ensure_attributes(
        col_pr,
        {
            "id": "",
            "type": "NEWSPAPER",
            "layout": "LEFT",
            "colCount": "1",
            "sameSz": "1",
            "sameGap": "0",
        },
        overwrite=True,
    ) or changed

    changed = _reorder_children(first_run, [sec_pr, ctrl]) or changed
    has_text = any(child.tag == _q("t") for run in first_paragraph.findall(_q("run")) for child in list(run))
    if not moved_text and not has_text:
        text_run = first_paragraph.makeelement(_q("run"), {"charPrIDRef": first_run.get("charPrIDRef") or "0"})
        text_run.append(text_run.makeelement(_q("t"), {}))
        first_paragraph.insert(list(first_paragraph).index(first_run) + 1, text_run)
        changed = True
    return changed


def _ensure_no_border_fill_element(header: Any) -> tuple[str, bool]:
    changed = False
    ref_list = header.find(_hh("refList"))
    if ref_list is None:
        ref_list = header.makeelement(_hh("refList"), {})
        header.append(ref_list)
        changed = True
    border_fills = ref_list.find(_hh("borderFills"))
    if border_fills is None:
        border_fills = ref_list.makeelement(_hh("borderFills"), {"itemCnt": "0"})
        ref_list.append(border_fills)
        changed = True

    border_child_names = ("leftBorder", "rightBorder", "topBorder", "bottomBorder")
    for border_fill in border_fills.findall(_hh("borderFill")):
        borders = [border_fill.find(_hh(name)) for name in border_child_names]
        if borders and all(border is not None and (border.get("type") or "").upper() == "NONE" for border in borders):
            return str(border_fill.get("id") or "0"), changed

    next_id = 1
    for border_fill in border_fills.findall(_hh("borderFill")):
        try:
            next_id = max(next_id, int(border_fill.get("id") or 0) + 1)
        except ValueError:
            continue
    element = border_fills.makeelement(
        _hh("borderFill"),
        {
            "id": str(next_id),
            "threeD": "0",
            "shadow": "0",
            "centerLine": "NONE",
            "breakCellSeparateLine": "0",
        },
    )
    for child_name, attrs in (
        ("slash", {"type": "NONE", "Crooked": "0", "isCounter": "0"}),
        ("backSlash", {"type": "NONE", "Crooked": "0", "isCounter": "0"}),
        ("leftBorder", {"type": "NONE", "width": "0.1 mm", "color": "#000000"}),
        ("rightBorder", {"type": "NONE", "width": "0.1 mm", "color": "#000000"}),
        ("topBorder", {"type": "NONE", "width": "0.1 mm", "color": "#000000"}),
        ("bottomBorder", {"type": "NONE", "width": "0.1 mm", "color": "#000000"}),
        ("diagonal", {"type": "NONE", "width": "0.1 mm", "color": "#000000"}),
    ):
        element.append(element.makeelement(_hh(child_name), attrs))
    border_fills.append(element)
    border_fills.set("itemCnt", str(len(border_fills.findall(_hh("borderFill")))))
    return str(next_id), True


def _ensure_package_item(
    manifest: Any,
    *,
    item_id: str,
    href: str,
    media_type: str,
    properties: str | None = None,
) -> tuple[Any, bool]:
    changed = False
    item = None
    for candidate in manifest.findall(_opf("item")):
        if candidate.get("id") == item_id or candidate.get("href") == href:
            item = candidate
            break
    if item is None:
        item = manifest.makeelement(_opf("item"), {})
        manifest.append(item)
        changed = True
    attrs = {"id": item_id, "href": href, "media-type": media_type}
    if properties is not None:
        attrs["properties"] = properties
    changed = _ensure_attributes(item, attrs, overwrite=True) or changed
    return item, changed


def _media_type_for_bindata_name(name: str) -> str:
    ext = Path(name).suffix.lower().lstrip(".")
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "tif": "image/tiff",
        "tiff": "image/tiff",
        "svg": "image/svg+xml",
    }.get(ext, "application/octet-stream")


def _ensure_spine_itemref(spine: Any, *, idref: str, linear: str = "yes") -> tuple[Any, bool]:
    changed = False
    itemref = None
    for candidate in spine.findall(_opf("itemref")):
        if candidate.get("idref") == idref:
            itemref = candidate
            break
    if itemref is None:
        itemref = spine.makeelement(_opf("itemref"), {})
        spine.append(itemref)
        changed = True
    changed = _ensure_attributes(itemref, {"idref": idref, "linear": linear}, overwrite=True) or changed
    return itemref, changed


def _ensure_content_hpf_shell(
    package: Any,
    section_names: list[str],
    *,
    bindata_names: list[str] | None = None,
) -> bool:
    changed = False
    package.set("version", package.get("version") or "")
    package.set("unique-identifier", package.get("unique-identifier") or "")
    package.set("id", package.get("id") or "")
    metadata = package.find(_opf("metadata"))
    if metadata is None:
        metadata = package.makeelement(_opf("metadata"), {})
        package.insert(0, metadata)
        changed = True
    manifest = package.find(_opf("manifest"))
    if manifest is None:
        manifest = package.makeelement(_opf("manifest"), {})
        package.append(manifest)
        changed = True
    spine = package.find(_opf("spine"))
    if spine is None:
        spine = package.makeelement(_opf("spine"), {})
        package.append(spine)
        changed = True

    ordered_manifest: list[Any] = []
    for item_id, href, media_type, properties in [
        ("version", "version.xml", "application/xml", "version"),
        ("header", "Contents/header.xml", "application/xml", None),
        *[
            (f"section{index}", section_name, "application/xml", None)
            for index, section_name in enumerate(section_names)
        ],
        ("settings", "settings.xml", "application/xml", None),
    ]:
        item, item_changed = _ensure_package_item(
            manifest,
            item_id=item_id,
            href=href,
            media_type=media_type,
            properties=properties,
        )
        ordered_manifest.append(item)
        changed = item_changed or changed

    for name in sorted(set(bindata_names or [])):
        if not name:
            continue
        href = f"BinData/{name}"
        item, item_changed = _ensure_package_item(
            manifest,
            item_id=Path(name).stem,
            href=href,
            media_type=_media_type_for_bindata_name(name),
        )
        if item.get("isEmbeded") != "1":
            item.set("isEmbeded", "1")
            item_changed = True
        ordered_manifest.append(item)
        changed = item_changed or changed

    ordered_spine: list[Any] = []
    itemref, itemref_changed = _ensure_spine_itemref(spine, idref="header", linear="yes")
    ordered_spine.append(itemref)
    changed = itemref_changed or changed
    for index, _section_name in enumerate(section_names):
        itemref, itemref_changed = _ensure_spine_itemref(spine, idref=f"section{index}", linear="yes")
        ordered_spine.append(itemref)
        changed = itemref_changed or changed

    changed = _reorder_children(manifest, ordered_manifest) or changed
    changed = _reorder_children(spine, ordered_spine) or changed
    changed = _reorder_children(package, [metadata, manifest, spine]) or changed
    return changed


def _normalize_content_hpf_root(package: Any) -> tuple[Any, bool]:
    if all(package.nsmap.get(prefix) == uri for prefix, uri in HWPX_COMPAT_NAMESPACES.items()):
        return package, False
    normalized = etree.Element(_opf("package"), nsmap=HWPX_COMPAT_NAMESPACES)
    for key, value in package.attrib.items():
        normalized.set(key, value)
    normalized.text = package.text
    normalized.tail = package.tail
    for child in list(package):
        package.remove(child)
        normalized.append(child)
    return normalized, True


def _hancom_settings_xml() -> bytes:
    root = etree.Element(f"{{{HA}}}HWPApplicationSetting", nsmap={"ha": HA, "config": CONFIG})
    etree.SubElement(root, f"{{{HA}}}CaretPosition", {"listIDRef": "0", "paraIDRef": "0", "pos": "0"})
    return _serialize_xml(root)


def _hancom_manifest_xml() -> bytes:
    root = etree.Element(f"{{{ODF_MANIFEST}}}manifest", nsmap={"odf": ODF_MANIFEST})
    return _serialize_xml(root)


def _hancom_container_xml() -> bytes:
    ocf = "urn:oasis:names:tc:opendocument:xmlns:container"
    root = etree.Element(f"{{{ocf}}}container", nsmap={"ocf": ocf, "hpf": HWPX_COMPAT_NAMESPACES["hpf"]})
    rootfiles = etree.SubElement(root, f"{{{ocf}}}rootfiles")
    for full_path, media_type in (
        ("Contents/content.hpf", "application/hwpml-package+xml"),
        ("Preview/PrvText.txt", "text/plain"),
        ("META-INF/container.rdf", "application/rdf+xml"),
    ):
        etree.SubElement(rootfiles, f"{{{ocf}}}rootfile", {"full-path": full_path, "media-type": media_type})
    return _serialize_xml(root)


def _hancom_container_rdf(section_names: list[str]) -> bytes:
    root = etree.Element(f"{{{RDF}}}RDF", nsmap={"rdf": RDF})

    def add_part(resource: str, type_name: str) -> None:
        owner = etree.SubElement(root, f"{{{RDF}}}Description", {f"{{{RDF}}}about": ""})
        etree.SubElement(owner, f"{{{HWPX_PKG_META}}}hasPart", {f"{{{RDF}}}resource": resource})
        part = etree.SubElement(root, f"{{{RDF}}}Description", {f"{{{RDF}}}about": resource})
        etree.SubElement(part, f"{{{RDF}}}type", {f"{{{RDF}}}resource": HWPX_PKG_META + type_name})

    add_part("Contents/header.xml", "HeaderFile")
    for section_name in section_names:
        add_part(section_name, "SectionFile")
    document = etree.SubElement(root, f"{{{RDF}}}Description", {f"{{{RDF}}}about": ""})
    etree.SubElement(document, f"{{{RDF}}}type", {f"{{{RDF}}}resource": HWPX_PKG_META + "Document"})
    return _serialize_xml(root)


def _preview_image_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (160, 226), "#FFFFFF").save(buffer, format="PNG")
    return buffer.getvalue()


def _preview_text_from_payloads(payloads: dict[str, bytes], *, limit: int = 200000) -> str:
    texts: list[str] = []
    for name in sorted(payloads):
        if not (name.startswith("Contents/") and Path(name).name.startswith("section") and name.endswith(".xml")):
            continue
        try:
            section = etree.fromstring(payloads[name])
        except Exception:
            continue
        for node in section.findall(f".//{_q('t')}"):
            if node.text:
                texts.append(node.text)
                if sum(len(text) for text in texts) >= limit:
                    break
        if sum(len(text) for text in texts) >= limit:
            break
    preview = "\r\n".join(texts).strip()
    if not preview:
        preview = "HWP Make PDF layout export"
    return preview[:limit]


def _patch_hancom_compatibility(path: Path) -> None:
    with zipfile.ZipFile(path, "r") as archive:
        infos = archive.infolist()
        payloads = {info.filename: archive.read(info.filename) for info in infos}

    section_names = _section_names_from_payloads(payloads)
    page_border_fill_id = "0"

    if "Contents/header.xml" in payloads:
        header = etree.fromstring(payloads["Contents/header.xml"])
        _ensure_hancom_header_shell(header, section_count=len(section_names))
        page_border_fill_id, _ = _ensure_no_border_fill_element(header)
        payloads["Contents/header.xml"] = _serialize_xml(header)

    for name in section_names:
        section = etree.fromstring(payloads[name])
        changed = _ensure_section_root_namespace(section)
        changed = _patch_rect_point_namespaces(section) or changed
        changed = _patch_line_point_namespaces(section) or changed
        changed = _patch_rect_shape_model(section) or changed
        changed = _ensure_section_properties_shell(section, border_fill_id_ref=page_border_fill_id) or changed
        changed = _patch_text_box_paragraphs(section) or changed
        changed = _patch_section_paragraph_linesegs(section) or changed
        changed = _patch_initial_section_paragraph(section) or changed
        changed = _ensure_section_run_shell(section) or changed
        if changed:
            payloads[name] = _serialize_xml(section)

    if "Contents/content.hpf" in payloads:
        package = etree.fromstring(payloads["Contents/content.hpf"])
        package, _ = _normalize_content_hpf_root(package)
        bindata_names = [
            Path(name).name
            for name in payloads
            if name.startswith("BinData/") and Path(name).name
        ]
        _ensure_content_hpf_shell(package, section_names, bindata_names=bindata_names)
        payloads["Contents/content.hpf"] = _serialize_xml(package)

    if "version.xml" in payloads:
        version = etree.fromstring(payloads["version.xml"])
        if version.tag == f"{{{HV}}}HCFVersion":
            version.set("xmlVersion", "1.5")
            version.set("os", version.get("os") or "1")
            version.set("application", version.get("application") or "Hancom Office Hangul")
            version.set("appVersion", version.get("appVersion") or "13, 0, 0, 3622 WIN32LEWindows_10")
        payloads["version.xml"] = _serialize_xml(version)

    if "Preview/PrvText.txt" not in payloads:
        payloads["Preview/PrvText.txt"] = _preview_text_from_payloads(payloads).encode("utf-8")
    payloads["META-INF/container.xml"] = _hancom_container_xml()
    if "settings.xml" not in payloads:
        payloads["settings.xml"] = _hancom_settings_xml()
    if "META-INF/manifest.xml" not in payloads:
        payloads["META-INF/manifest.xml"] = _hancom_manifest_xml()
    if "META-INF/container.rdf" not in payloads:
        payloads["META-INF/container.rdf"] = _hancom_container_rdf(section_names)
    if "Preview/PrvImage.png" not in payloads:
        payloads["Preview/PrvImage.png"] = _preview_image_png()

    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=path.suffix + ".tmp")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with zipfile.ZipFile(tmp_path, "w") as out:
            info_by_name = {info.filename: info for info in infos}
            preferred_order = [
                "mimetype",
                "version.xml",
                "Contents/header.xml",
                *section_names,
                "Preview/PrvText.txt",
                "settings.xml",
                "Preview/PrvImage.png",
                "META-INF/container.rdf",
                "Contents/content.hpf",
                "META-INF/container.xml",
                "META-INF/manifest.xml",
            ]
            written = set()
            for name in preferred_order:
                if name not in payloads or name in written:
                    continue
                info = info_by_name.get(name)
                if info is None:
                    compress_type = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
                    out.writestr(name, payloads[name], compress_type=compress_type)
                else:
                    if name == "mimetype":
                        info.compress_type = zipfile.ZIP_STORED
                    out.writestr(info, payloads[name])
                written.add(name)
            for info in infos:
                if info.filename in written:
                    continue
                out.writestr(info, payloads[info.filename])
                written.add(info.filename)
            for name in sorted(payloads):
                if name in written:
                    continue
                out.writestr(name, payloads[name], compress_type=zipfile.ZIP_DEFLATED)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def _patch_initial_section_paragraph(section: Any) -> bool:
    paragraphs = section.findall(_q("p"))
    if len(paragraphs) < 2:
        return False
    first, second = paragraphs[0], paragraphs[1]
    first_run = first.find(_q("run"))
    second_run = second.find(_q("run"))
    if first_run is None or second_run is None:
        return False
    if first_run.find(_q("secPr")) is None:
        return False
    if first.findall(f".//{_q('tbl')}") or first.findall(f".//{_q('pic')}"):
        return False
    if not second.findall(f"{_q('run')}/{_q('tbl')}"):
        return False
    nonempty_text = [
        text.text
        for text in first.findall(f".//{_q('t')}")
        if text.text and text.text.strip()
    ]
    if nonempty_text:
        return False
    move_nodes = [
        child
        for child in list(first_run)
        if child.tag in {_q("secPr"), _q("ctrl")}
    ]
    if not move_nodes:
        return False
    insert_at = 0
    for child in move_nodes:
        second_run.insert(insert_at, child)
        insert_at += 1
    parent = first.getparent()
    if parent is None:
        return False
    parent.remove(first)
    return True


def _patch_text_box_paragraphs(section: Any) -> bool:
    changed = False
    for draw in section.findall(f".//{_q('drawText')}"):
        sub = draw.find(_q("subList"))
        if sub is None:
            continue
        width = _positive_int(sub.get("textWidth")) or _positive_int(draw.get("lastWidth"))
        height = _positive_int(sub.get("textHeight"))
        parent = draw.getparent()
        if parent is not None:
            size = parent.find(_q("sz"))
            if size is not None:
                width = width or _positive_int(size.get("width"))
                height = height or _positive_int(size.get("height"))
        if width is None:
            width = 1
        if height is None:
            height = 1
        for paragraph in sub.findall(_q("p")):
            if not paragraph.get("id"):
                paragraph.set("id", _paragraph_id())
                changed = True
            if paragraph.find(f"{_q('linesegarray')}/{_q('lineseg')}") is None:
                _append_text_box_lineseg_hwp(paragraph, width, height)
                changed = True
    return changed


def _patch_section_paragraph_linesegs(section: Any) -> bool:
    changed = False
    width = _section_text_width(section)
    height = 1000
    for paragraph in section.findall(f".//{_q('p')}"):
        if not paragraph.get("id"):
            paragraph.set("id", _paragraph_id())
            changed = True
        if paragraph.find(f"{_q('linesegarray')}/{_q('lineseg')}") is None:
            _append_text_box_lineseg_hwp(paragraph, width, height)
            changed = True
    return changed


def _patch_rect_point_namespaces(section: Any) -> bool:
    changed = False
    for rect in section.findall(f".//{_q('rect')}"):
        for point_name in ("pt0", "pt1", "pt2", "pt3"):
            point = rect.find(_q(point_name))
            if point is not None:
                point.tag = _hc(point_name)
                changed = True
    return changed


def _patch_line_point_namespaces(section: Any) -> bool:
    changed = False
    for line in section.findall(f".//{_q('line')}"):
        for point_name in ("startPt", "endPt"):
            point = line.find(_q(point_name))
            if point is not None:
                point.tag = _hc(point_name)
                changed = True
    return changed


def _patch_rect_shape_model(section: Any) -> bool:
    changed = False
    for rect in section.findall(f".//{_q('rect')}"):
        for key, value in (
            ("textWrap", "SQUARE"),
            ("textFlow", "BOTH_SIDES"),
            ("reverse", "0"),
        ):
            if rect.get(key) != value:
                rect.set(key, value)
                changed = True
        for child in rect:
            local_name = etree.QName(child).localname
            if local_name == "fillBrush" and child.tag != _hc("fillBrush"):
                child.tag = _hc("fillBrush")
                changed = True
            if local_name == "winBrush" and child.tag != _hc("winBrush"):
                child.tag = _hc("winBrush")
                changed = True
            for grandchild in child:
                if etree.QName(grandchild).localname == "winBrush" and grandchild.tag != _hc("winBrush"):
                    grandchild.tag = _hc("winBrush")
                    changed = True
        if rect.find(_q("shapeComment")) is None:
            _append_xml_child(rect, _q("shapeComment"))
            changed = True
    return changed


def _section_text_width(section: Any) -> int:
    page_pr = section.find(f".//{_q('pagePr')}")
    if page_pr is None:
        return 42520
    width = _positive_int(page_pr.get("width")) or 42520
    margin = page_pr.find(_q("margin"))
    if margin is None:
        return width
    left = _positive_int(margin.get("left")) or 0
    right = _positive_int(margin.get("right")) or 0
    gutter = _positive_int(margin.get("gutter")) or 0
    return max(1, width - left - right - gutter)


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _append_text_box_lineseg_hwp(paragraph: Any, width: int, height: int) -> None:
    line_seg_array = etree.SubElement(paragraph, _q("linesegarray"))
    etree.SubElement(
        line_seg_array,
        _q("lineseg"),
        {
            "textpos": "0",
            "vertpos": "0",
            "vertsize": str(height),
            "textheight": str(height),
            "baseline": str(max(1, int(height * 0.85))),
            "spacing": str(max(0, int(height * 0.15))),
            "horzpos": "0",
            "horzsize": str(width),
            "flags": "393216",
        },
    )


def _prepare_hancom_compatibility(doc: HwpxDocument) -> None:
    header = doc.headers[0]
    _ensure_hancom_header_shell(header.element)
    header.mark_dirty()

    doc.package.version_info.set("xmlVersion", "1.5")
    doc.package.add_manifest_item("version", "version.xml", "application/xml")


def _save_hancom_compatible_document(doc: HwpxDocument, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(output_path.parent), suffix=output_path.suffix + ".tmp")
    os.close(fd)
    tmp_path = Path(tmp_name)

    try:
        tmp_path.write_bytes(doc._to_bytes_for_validation())
        _patch_hancom_compatibility(tmp_path)

        from hwpx.tools.package_validator import validate_editor_open_safety

        report = validate_editor_open_safety(tmp_path)
        if not report.ok:
            raise RuntimeError("Generated HWPX package failed Hancom compatibility validation: " + report.summary)
        os.replace(tmp_path, output_path)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def _ensure_no_border_fill(header: Any) -> str:
    border_fills = header.element.find(f".//{_hh('borderFills')}")
    if border_fills is None:
        ref_list = header.element.find(f".//{_hh('refList')}")
        if ref_list is None:
            return "0"
        border_fills = ref_list.makeelement(_hh("borderFills"), {"itemCnt": "0"})
        ref_list.append(border_fills)
    for border_fill in border_fills.findall(_hh("borderFill")):
        children = [child for child in border_fill if etree.QName(child).localname.endswith("Border")]
        if children and all((child.get("type") or "").upper() == "NONE" for child in children):
            return str(border_fill.get("id") or "0")
    next_id = 1
    for border_fill in border_fills.findall(_hh("borderFill")):
        try:
            next_id = max(next_id, int(border_fill.get("id") or 0) + 1)
        except ValueError:
            continue
    element = border_fills.makeelement(
        _hh("borderFill"),
        {
            "id": str(next_id),
            "threeD": "0",
            "shadow": "0",
            "centerLine": "NONE",
            "breakCellSeparateLine": "0",
        },
    )
    for child_name, attrs in (
        ("slash", {"type": "NONE", "Crooked": "0", "isCounter": "0"}),
        ("backSlash", {"type": "NONE", "Crooked": "0", "isCounter": "0"}),
        ("leftBorder", {"type": "NONE", "width": "0.0 mm", "color": "#FFFFFF"}),
        ("rightBorder", {"type": "NONE", "width": "0.0 mm", "color": "#FFFFFF"}),
        ("topBorder", {"type": "NONE", "width": "0.0 mm", "color": "#FFFFFF"}),
        ("bottomBorder", {"type": "NONE", "width": "0.0 mm", "color": "#FFFFFF"}),
        ("diagonal", {"type": "NONE", "width": "0.0 mm", "color": "#FFFFFF"}),
    ):
        element.append(element.makeelement(_hh(child_name), attrs))
    border_fills.append(element)
    border_fills.set("itemCnt", str(len(border_fills.findall(_hh("borderFill")))))
    header.mark_dirty()
    return str(next_id)


def _ensure_box_border_fill(header: Any) -> str:
    border_fills = header.element.find(f".//{_hh('borderFills')}")
    if border_fills is None:
        ref_list = header.element.find(f".//{_hh('refList')}")
        if ref_list is None:
            return header.ensure_basic_border_fill()
        border_fills = ref_list.makeelement(_hh("borderFills"), {"itemCnt": "0"})
        ref_list.append(border_fills)
    for border_fill in border_fills.findall(_hh("borderFill")):
        borders = [
            border_fill.find(_hh(name))
            for name in ("leftBorder", "rightBorder", "topBorder", "bottomBorder")
        ]
        if all(border is not None and border.get("type") == "SOLID" and border.get("width") == "0.2 mm" for border in borders):
            return str(border_fill.get("id") or "0")
    next_id = 1
    for border_fill in border_fills.findall(_hh("borderFill")):
        try:
            next_id = max(next_id, int(border_fill.get("id") or 0) + 1)
        except ValueError:
            continue
    element = border_fills.makeelement(
        _hh("borderFill"),
        {
            "id": str(next_id),
            "threeD": "0",
            "shadow": "0",
            "centerLine": "NONE",
            "breakCellSeparateLine": "0",
        },
    )
    for child_name, attrs in (
        ("slash", {"type": "NONE", "Crooked": "0", "isCounter": "0"}),
        ("backSlash", {"type": "NONE", "Crooked": "0", "isCounter": "0"}),
        ("leftBorder", {"type": "SOLID", "width": "0.2 mm", "color": "#000000"}),
        ("rightBorder", {"type": "SOLID", "width": "0.2 mm", "color": "#000000"}),
        ("topBorder", {"type": "SOLID", "width": "0.2 mm", "color": "#000000"}),
        ("bottomBorder", {"type": "SOLID", "width": "0.2 mm", "color": "#000000"}),
        ("diagonal", {"type": "NONE", "width": "0.0 mm", "color": "#FFFFFF"}),
    ):
        element.append(element.makeelement(_hh(child_name), attrs))
    border_fills.append(element)
    border_fills.set("itemCnt", str(len(border_fills.findall(_hh("borderFill")))))
    header.mark_dirty()
    return str(next_id)


def _ensure_column_divider_border_fill(header: Any) -> str:
    border_fills = header.element.find(f".//{_hh('borderFills')}")
    if border_fills is None:
        ref_list = header.element.find(f".//{_hh('refList')}")
        if ref_list is None:
            return _ensure_no_border_fill(header)
        border_fills = ref_list.makeelement(_hh("borderFills"), {"itemCnt": "0"})
        ref_list.append(border_fills)
    for border_fill in border_fills.findall(_hh("borderFill")):
        right = border_fill.find(_hh("rightBorder"))
        left = border_fill.find(_hh("leftBorder"))
        top = border_fill.find(_hh("topBorder"))
        bottom = border_fill.find(_hh("bottomBorder"))
        if (
            right is not None
            and right.get("type") == "SOLID"
            and right.get("width") == "0.12 mm"
            and all(
                border is not None and (border.get("type") or "").upper() == "NONE"
                for border in (left, top, bottom)
            )
        ):
            return str(border_fill.get("id") or "0")
    next_id = 1
    for border_fill in border_fills.findall(_hh("borderFill")):
        try:
            next_id = max(next_id, int(border_fill.get("id") or 0) + 1)
        except ValueError:
            continue
    element = border_fills.makeelement(
        _hh("borderFill"),
        {
            "id": str(next_id),
            "threeD": "0",
            "shadow": "0",
            "centerLine": "NONE",
            "breakCellSeparateLine": "0",
        },
    )
    for child_name, attrs in (
        ("slash", {"type": "NONE", "Crooked": "0", "isCounter": "0"}),
        ("backSlash", {"type": "NONE", "Crooked": "0", "isCounter": "0"}),
        ("leftBorder", {"type": "NONE", "width": "0.0 mm", "color": "#FFFFFF"}),
        ("rightBorder", {"type": "SOLID", "width": "0.12 mm", "color": "#404040"}),
        ("topBorder", {"type": "NONE", "width": "0.0 mm", "color": "#FFFFFF"}),
        ("bottomBorder", {"type": "NONE", "width": "0.0 mm", "color": "#FFFFFF"}),
        ("diagonal", {"type": "NONE", "width": "0.0 mm", "color": "#FFFFFF"}),
    ):
        element.append(element.makeelement(_hh(child_name), attrs))
    border_fills.append(element)
    border_fills.set("itemCnt", str(len(border_fills.findall(_hh("borderFill")))))
    header.mark_dirty()
    return str(next_id)


def _pt_to_mm(value_pt: float) -> float:
    return float(value_pt) * 25.4 / 72.0


def _mm_to_hwp(value_mm: float) -> int:
    return int(round(float(value_mm) * 7200.0 / 25.4))


def _pt_to_hwp(value_pt: float) -> int:
    return _hwp(value_pt)


def _line_text(line: dict[str, Any]) -> str:
    return "".join(str(span.get("text") or "") for span in line.get("spans", [])).strip()


def _item_bbox(item: dict[str, Any]) -> fitz.Rect:
    return fitz.Rect(item["bbox"])


def _clear_cell_paragraphs(cell: Any) -> None:
    sub = cell.element.find(_q("subList"))
    if sub is None:
        cell.set_text("", split_paragraphs=True)
        sub = cell.element.find(_q("subList"))
    if sub is None:
        return
    for paragraph in list(sub.findall(_q("p"))):
        sub.remove(paragraph)


def _set_cell_margin(
    cell: Any,
    *,
    left_mm: float = 0.0,
    right_mm: float = 0.0,
    top_mm: float = 0.0,
    bottom_mm: float = 0.0,
) -> None:
    margin = cell.element.find(_q("cellMargin"))
    if margin is None:
        margin = cell.element.makeelement(_q("cellMargin"), {})
        cell.element.append(margin)
    for name, value in {
        "left": left_mm,
        "right": right_mm,
        "top": top_mm,
        "bottom": bottom_mm,
    }.items():
        margin.set(name, str(max(0, _mm_to_hwp(value))))
    cell.element.set("hasMargin", "1")
    cell.table.mark_dirty()


def _set_cell_border_fill(cell: Any, border_fill_id_ref: str) -> None:
    cell.element.set("borderFillIDRef", str(border_fill_id_ref))
    cell.table.mark_dirty()


def _append_cell_line(
    doc: HwpxDocument,
    cell: Any,
    line: dict[str, Any],
    *,
    styles: dict[tuple[str, float, bool], str],
    para_pr_id_ref: str,
) -> bool:
    runs = _span_text_runs(doc, styles, line.get("spans", []))
    if not runs:
        return False
    paragraph = cell.add_paragraph("", para_pr_id_ref=para_pr_id_ref, char_pr_id_ref=runs[0][1])
    for run in list(paragraph.element.findall(_q("run"))):
        paragraph.element.remove(run)
    for text, char_pr_id_ref in runs:
        if text == "":
            continue
        run = etree.SubElement(paragraph.element, _q("run"), {"charPrIDRef": str(char_pr_id_ref)})
        node = etree.SubElement(run, _q("t"))
        node.set(f"{{{XML}}}space", "preserve")
        node.text = text
    return True


def _iter_flow_images(page: fitz.Page) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 1:
            continue
        bbox = fitz.Rect(block.get("bbox") or (0, 0, 0, 0))
        if bbox.width < 12 or bbox.height < 8:
            continue
        data = block.get("image")
        if not data:
            continue
        images.append(
            {
                "type": "image",
                "bbox": bbox,
                "image": bytes(data),
                "ext": str(block.get("ext") or "png"),
            }
        )
    return images


def _image_rects_related(a: fitz.Rect, b: fitz.Rect) -> bool:
    x_overlap = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    x_ratio = x_overlap / max(1.0, min(a.width, b.width))
    vertical_touch = max(a.y0, b.y0) <= min(a.y1, b.y1) + 2.0
    return x_ratio >= 0.82 and vertical_touch


def _merge_flow_images(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(images) < 2:
        return images
    groups: list[list[dict[str, Any]]] = []
    for image in sorted(images, key=lambda item: (_item_bbox(item).x0, _item_bbox(item).y0)):
        rect = _item_bbox(image)
        for group in groups:
            if any(_image_rects_related(rect, _item_bbox(existing)) for existing in group):
                group.append(image)
                break
        else:
            groups.append([image])

    merged: list[dict[str, Any]] = []
    for group in groups:
        if len(group) == 1:
            merged.append(group[0])
            continue
        rects = [_item_bbox(item) for item in group]
        bounds = _union_rect(rects)
        scale = 2.0
        width_px = max(1, int(round(bounds.width * scale)))
        height_px = max(1, int(round(bounds.height * scale)))
        canvas = Image.new("RGBA", (width_px, height_px), (255, 255, 255, 255))
        for item in sorted(group, key=lambda value: (_item_bbox(value).y0, _item_bbox(value).x0)):
            rect = _item_bbox(item)
            try:
                part = Image.open(io.BytesIO(item["image"])).convert("RGBA")
            except Exception:
                continue
            part_size = (max(1, int(round(rect.width * scale))), max(1, int(round(rect.height * scale))))
            if part.size != part_size:
                part = part.resize(part_size, Image.Resampling.LANCZOS)
            left = int(round((rect.x0 - bounds.x0) * scale))
            top = int(round((rect.y0 - bounds.y0) * scale))
            canvas.alpha_composite(part, (left, top))
        output = io.BytesIO()
        canvas.convert("RGB").save(output, format="PNG")
        merged.append({"type": "image", "bbox": bounds, "image": output.getvalue(), "ext": "png"})
    merged.sort(key=lambda item: (_item_bbox(item).y0, _item_bbox(item).x0))
    return merged


def _text_line_count_in_region(page: fitz.Page, region: fitz.Rect) -> int:
    count = 0
    for line in _iter_text_lines(page):
        if not _line_text(line):
            continue
        bbox = fitz.Rect(line["bbox"])
        center = fitz.Point((bbox.x0 + bbox.x1) / 2.0, (bbox.y0 + bbox.y1) / 2.0)
        if region.contains(center):
            count += 1
    return count


def _convert_textual_image_regions(page: fitz.Page, images: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[fitz.Rect]]:
    converted: list[dict[str, Any]] = []
    text_regions: list[fitz.Rect] = []
    matrix = fitz.Matrix(2.0, 2.0)
    for item in images:
        region = _item_bbox(item)
        if region.width >= page.rect.width * 0.24 and region.height >= 60 and _text_line_count_in_region(page, region) >= 3:
            pix = page.get_pixmap(matrix=matrix, clip=region, alpha=False)
            converted.append(
                {
                    "type": "image",
                    "bbox": region,
                    "image": pix.tobytes("png"),
                    "ext": "png",
                    "textual_image": True,
                }
            )
            text_regions.append(region)
        else:
            converted.append(item)
    return converted, text_regions


def _has_table_lines(page: fitz.Page, rect: fitz.Rect) -> bool:
    horizontal = 0
    vertical = 0
    probe = fitz.Rect(rect)
    probe.x0 -= 4
    probe.y0 -= 4
    probe.x1 += 4
    probe.y1 += 4
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if not item or item[0] != "l":
                continue
            p0, p1 = item[1], item[2]
            x0, y0, x1, y1 = float(p0.x), float(p0.y), float(p1.x), float(p1.y)
            if not probe.contains(fitz.Point(x0, y0)) and not probe.contains(fitz.Point(x1, y1)):
                continue
            if abs(y1 - y0) <= 0.6 and abs(x1 - x0) >= 30:
                horizontal += 1
            elif abs(x1 - x0) <= 0.6 and abs(y1 - y0) >= 12:
                vertical += 1
    return horizontal >= 2 and vertical >= 2


def _span_count(block: dict[str, Any]) -> int:
    return sum(len(line.get("spans", [])) for line in block.get("lines", []))


def _x_cluster_count(block: dict[str, Any]) -> int:
    centers: list[float] = []
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            bbox = fitz.Rect(span.get("bbox") or (0, 0, 0, 0))
            text = str(span.get("text") or "").strip()
            if text:
                centers.append((bbox.x0 + bbox.x1) / 2.0)
    centers.sort()
    clusters: list[float] = []
    for center in centers:
        if not clusters or abs(center - clusters[-1]) > 18:
            clusters.append(center)
    return len(clusters)


def _rects_touch(a: fitz.Rect, b: fitz.Rect, *, gap: float = 10.0) -> bool:
    expanded = fitz.Rect(a)
    expanded.x0 -= gap
    expanded.y0 -= gap
    expanded.x1 += gap
    expanded.y1 += gap
    return expanded.intersects(b)


def _drawing_table_regions(page: fitz.Page) -> list[fitz.Rect]:
    line_items: list[tuple[fitz.Rect, str]] = []
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if not item or item[0] != "l":
                continue
            p0, p1 = item[1], item[2]
            x0, y0, x1, y1 = float(p0.x), float(p0.y), float(p1.x), float(p1.y)
            if max(y0, y1) < page.rect.height * 0.35:
                continue
            if abs(y1 - y0) <= 0.7 and abs(x1 - x0) >= 28:
                rect = fitz.Rect(min(x0, x1), y0, max(x0, x1), y1)
                rect.y0 -= 1
                rect.y1 += 1
                line_items.append((rect, "h"))
            elif abs(x1 - x0) <= 0.7 and abs(y1 - y0) >= 12:
                rect = fitz.Rect(x0, min(y0, y1), x1, max(y0, y1))
                rect.x0 -= 1
                rect.x1 += 1
                line_items.append((rect, "v"))

    components: list[list[tuple[fitz.Rect, str]]] = []
    for rect, orientation in line_items:
        placed = False
        for component in components:
            bounds = fitz.Rect(component[0][0])
            for existing, _ in component[1:]:
                bounds.include_rect(existing)
            if _rects_touch(bounds, rect, gap=12):
                component.append((rect, orientation))
                placed = True
                break
        if not placed:
            components.append([(rect, orientation)])

    changed = True
    while changed:
        changed = False
        merged: list[list[tuple[fitz.Rect, str]]] = []
        while components:
            current = components.pop(0)
            current_bounds = fitz.Rect(current[0][0])
            for rect, _ in current[1:]:
                current_bounds.include_rect(rect)
            index = 0
            while index < len(components):
                other = components[index]
                other_bounds = fitz.Rect(other[0][0])
                for rect, _ in other[1:]:
                    other_bounds.include_rect(rect)
                if _rects_touch(current_bounds, other_bounds, gap=12):
                    current.extend(other)
                    current_bounds.include_rect(other_bounds)
                    components.pop(index)
                    changed = True
                else:
                    index += 1
            merged.append(current)
        components = merged

    regions: list[fitz.Rect] = []
    for component in components:
        bounds = fitz.Rect(component[0][0])
        orientations = [orientation for _, orientation in component]
        for rect, _ in component[1:]:
            bounds.include_rect(rect)
        horizontal = orientations.count("h")
        vertical = orientations.count("v")
        if horizontal < 3 or vertical < 2:
            continue
        if bounds.width < page.rect.width * 0.18 or bounds.height < 28:
            continue
        if bounds.height > page.rect.height * 0.24:
            continue
        padded = fitz.Rect(bounds)
        padded.x0 = max(0.0, padded.x0 - 16)
        padded.y0 = max(0.0, padded.y0 - 24)
        padded.x1 = min(page.rect.width, padded.x1 + 4)
        padded.y1 = min(page.rect.height, padded.y1 + 4)
        if not any(_rects_close(padded, existing) or padded.intersects(existing) for existing in regions):
            regions.append(padded)
    regions.sort(key=lambda rect: (rect.y0, rect.x0))
    return regions


def _iter_flow_table_images(page: fitz.Page) -> list[dict[str, Any]]:
    blocks = [block for block in page.get_text("dict").get("blocks", []) if block.get("type") == 0]
    used: set[int] = set()
    table_images: list[dict[str, Any]] = []
    matrix = fitz.Matrix(2.0, 2.0)
    for region in _drawing_table_regions(page):
        pix = page.get_pixmap(matrix=matrix, clip=region, alpha=False)
        table_images.append(
            {
                "type": "image",
                "bbox": region,
                "image": pix.tobytes("png"),
                "ext": "png",
                "table_image": True,
            }
        )
    for index, block in enumerate(blocks):
        if index in used:
            continue
        rect = fitz.Rect(block.get("bbox") or (0, 0, 0, 0))
        if any(rect.intersects(_item_bbox(item)) for item in table_images):
            continue
        if rect.y0 < page.rect.height * 0.35:
            continue
        if rect.width < page.rect.width * 0.22 or rect.height < 25:
            continue
        if _span_count(block) < 10 or _x_cluster_count(block) < 5:
            continue
        seed_probe = fitz.Rect(rect)
        seed_probe.x0 = max(0.0, seed_probe.x0 - 4)
        seed_probe.y0 = max(0.0, seed_probe.y0 - 4)
        seed_probe.x1 = min(page.rect.width, seed_probe.x1 + 4)
        seed_probe.y1 = min(page.rect.height, seed_probe.y1 + 4)
        if not _has_table_lines(page, seed_probe):
            continue
        region = fitz.Rect(rect)
        member_indexes = {index}
        changed = True
        while changed:
            changed = False
            for other_index, other in enumerate(blocks):
                if other_index in member_indexes or other_index in used:
                    continue
                other_rect = fitz.Rect(other.get("bbox") or (0, 0, 0, 0))
                if other_rect.y0 < region.y0 - 4:
                    continue
                x_overlap = max(0.0, min(region.x1, other_rect.x1) - max(region.x0, other_rect.x0))
                if x_overlap < min(region.width, other_rect.width) * 0.45:
                    continue
                y_gap = max(0.0, max(other_rect.y0 - region.y1, region.y0 - other_rect.y1))
                if y_gap > 28:
                    continue
                trial = fitz.Rect(region)
                trial.include_rect(other_rect)
                if trial.height > page.rect.height * 0.22:
                    continue
                region = trial
                member_indexes.add(other_index)
                changed = True
        padded = fitz.Rect(region)
        padded.x0 = max(0.0, padded.x0 - 4)
        padded.y0 = max(0.0, padded.y0 - 4)
        padded.x1 = min(page.rect.width, padded.x1 + 4)
        padded.y1 = min(page.rect.height, padded.y1 + 4)
        if not _has_table_lines(page, padded):
            continue
        pix = page.get_pixmap(matrix=matrix, clip=padded, alpha=False)
        table_images.append(
            {
                "type": "image",
                "bbox": padded,
                "image": pix.tobytes("png"),
                "ext": "png",
                "table_image": True,
            }
        )
        used.update(member_indexes)
    return table_images


def _inside_any_region(rect: fitz.Rect, regions: list[fitz.Rect]) -> bool:
    center = fitz.Point((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0)
    return any(region.contains(center) for region in regions)


def _is_flow_footer_line(page: fitz.Page, line: dict[str, Any]) -> bool:
    bbox = _item_bbox(line)
    if bbox.y0 < page.rect.height * 0.90:
        return False
    text = _line_text(line)
    if not text:
        return True
    compact = re.sub(r"\s+", "", text)
    if compact.isdigit():
        return True
    if re.fullmatch(r"\d+/\d+", compact):
        return True
    return "저작권" in text or "한국교육과정평가원" in text


def _append_cell_image(
    doc: HwpxDocument,
    cell: Any,
    image: dict[str, Any],
    *,
    cell_width: int,
    para_pr_id_ref: str,
    border_fill_id_ref: str,
) -> bool:
    bbox = _item_bbox(image)
    try:
        image_data = _png_from_extracted_image(bytes(image["image"]), str(image.get("ext") or "png"))
    except Exception:
        return False
    width = min(max(1, cell_width - _pt_to_hwp(4)), max(1, _pt_to_hwp(bbox.width)))
    height = max(1, int(round(width * max(1.0, bbox.height) / max(1.0, bbox.width))))
    item_id = doc.add_image(image_data, "png")
    table = cell.add_table(1, 1, width=width, height=height, border_fill_id_ref=border_fill_id_ref)
    nested = table.cell(0, 0)
    _clear_cell_paragraphs(nested)
    paragraph = nested.add_paragraph("", para_pr_id_ref=para_pr_id_ref, char_pr_id_ref="0")
    paragraph.add_picture(item_id, width=width, height=height)
    return True


def _flow_box_rects(page: fitz.Page) -> list[fitz.Rect]:
    boxes: list[fitz.Rect] = []
    page_area = float(page.rect.width * page.rect.height)
    for drawing in page.get_drawings():
        rects: list[fitz.Rect] = []
        drawing_rect = drawing.get("rect")
        if drawing_rect is not None:
            rects.append(fitz.Rect(drawing_rect))
        for item in drawing.get("items", []):
            if item and item[0] == "re":
                rects.append(fitz.Rect(item[1]))
        for rect in rects:
            if _is_hidden_header_rect(rect):
                continue
            area = float(rect.width * rect.height)
            if rect.width < 80 or rect.height < 18:
                continue
            if rect.width > page.rect.width * 0.55 or rect.height > page.rect.height * 0.33:
                continue
            if area > page_area * 0.75:
                continue
            if rect.y0 < 35 and rect.height < 35:
                continue
            if not any(_rects_close(rect, existing) for existing in boxes):
                boxes.append(rect)
    for rect in _drawing_box_rects(page):
        if not any(_rects_close(rect, existing) or rect.intersects(existing) for existing in boxes):
            boxes.append(rect)
    for rect in _rail_box_rects(page):
        if not any(_rects_close(rect, existing) or rect.intersects(existing) for existing in boxes):
            boxes.append(rect)
    boxes.sort(key=lambda item: (item.y0, item.x0, item.width * item.height))
    return boxes


def _rail_box_rects(page: fitz.Page) -> list[fitz.Rect]:
    verticals: list[fitz.Rect] = []
    horizontals: list[fitz.Rect] = []
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if not item or item[0] != "l":
                continue
            p0, p1 = item[1], item[2]
            x0, y0, x1, y1 = float(p0.x), float(p0.y), float(p1.x), float(p1.y)
            if abs(x1 - x0) <= 0.7 and abs(y1 - y0) >= 8:
                verticals.append(fitz.Rect(x0 - 0.6, min(y0, y1), x0 + 0.6, max(y0, y1)))
            elif abs(y1 - y0) <= 0.7 and abs(x1 - x0) >= 30:
                horizontals.append(fitz.Rect(min(x0, x1), y0 - 0.6, max(x0, x1), y0 + 0.6))

    rails: list[fitz.Rect] = []
    for segment in sorted(verticals, key=lambda rect: (round(rect.x0, 1), rect.y0)):
        center_x = (segment.x0 + segment.x1) / 2.0
        matched: fitz.Rect | None = None
        for rail in rails:
            rail_x = (rail.x0 + rail.x1) / 2.0
            if abs(center_x - rail_x) <= 2.0:
                matched = rail
                break
        if matched is None:
            rails.append(fitz.Rect(segment))
        else:
            matched.include_rect(segment)

    rails.sort(key=lambda rect: (rect.x0 + rect.x1) / 2.0)

    def has_edge(left: fitz.Rect, right: fitz.Rect, y: float) -> bool:
        lx = (left.x0 + left.x1) / 2.0
        rx = (right.x0 + right.x1) / 2.0
        for line in horizontals:
            if abs(((line.y0 + line.y1) / 2.0) - y) > 8:
                continue
            if line.x0 <= lx + 4 and line.x1 >= rx - 4:
                return True
        return False

    boxes: list[fitz.Rect] = []
    used: set[int] = set()
    for left_index, left in enumerate(rails):
        if left_index in used:
            continue
        best_index: int | None = None
        best_rect: fitz.Rect | None = None
        for right_index in range(left_index + 1, len(rails)):
            if right_index in used:
                continue
            right = rails[right_index]
            width = ((right.x0 + right.x1) - (left.x0 + left.x1)) / 2.0
            if width < page.rect.width * 0.24 or width > page.rect.width * 0.43:
                continue
            top = max(left.y0, right.y0)
            bottom = min(left.y1, right.y1)
            if bottom - top < page.rect.height * 0.18:
                continue
            if not (has_edge(left, right, top) or has_edge(left, right, bottom)):
                continue
            best_index = right_index
            best_rect = fitz.Rect(left.x0, top, right.x1, bottom)
            break
        if best_index is None or best_rect is None:
            continue
        padded = fitz.Rect(best_rect)
        padded.x0 = max(0.0, padded.x0 - 2)
        padded.y0 = max(0.0, padded.y0 - 2)
        padded.x1 = min(page.rect.width, padded.x1 + 2)
        padded.y1 = min(page.rect.height, padded.y1 + 2)
        boxes.append(padded)
        used.add(left_index)
        used.add(best_index)
    return boxes


def _drawing_box_rects(page: fitz.Page) -> list[fitz.Rect]:
    line_items: list[tuple[fitz.Rect, str]] = []
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if not item or item[0] != "l":
                continue
            p0, p1 = item[1], item[2]
            x0, y0, x1, y1 = float(p0.x), float(p0.y), float(p1.x), float(p1.y)
            if min(y0, y1) < 120:
                continue
            if abs(y1 - y0) <= 0.7 and abs(x1 - x0) >= 40:
                rect = fitz.Rect(min(x0, x1), y0 - 1, max(x0, x1), y1 + 1)
                line_items.append((rect, "h"))
            elif abs(x1 - x0) <= 0.7 and abs(y1 - y0) >= 18:
                rect = fitz.Rect(x0 - 1, min(y0, y1), x1 + 1, max(y0, y1))
                line_items.append((rect, "v"))
    components: list[list[tuple[fitz.Rect, str]]] = []
    for rect, orientation in line_items:
        placed = False
        for component in components:
            bounds = fitz.Rect(component[0][0])
            for existing, _ in component[1:]:
                bounds.include_rect(existing)
            if _rects_touch(bounds, rect, gap=8):
                component.append((rect, orientation))
                placed = True
                break
        if not placed:
            components.append([(rect, orientation)])

    regions: list[fitz.Rect] = []
    for component in components:
        bounds = fitz.Rect(component[0][0])
        orientations = [orientation for _, orientation in component]
        for rect, _ in component[1:]:
            bounds.include_rect(rect)
        horizontal = orientations.count("h")
        vertical = orientations.count("v")
        if horizontal < 2 or vertical < 2:
            continue
        if horizontal >= 3 and vertical >= 2:
            continue
        if bounds.width < page.rect.width * 0.18 or bounds.width > page.rect.width * 0.58:
            continue
        if bounds.height < 20 or bounds.height > page.rect.height * 0.34:
            continue
        padded = fitz.Rect(bounds)
        padded.x0 = max(0.0, padded.x0 - 2)
        padded.y0 = max(0.0, padded.y0 - 2)
        padded.x1 = min(page.rect.width, padded.x1 + 2)
        padded.y1 = min(page.rect.height, padded.y1 + 2)
        regions.append(padded)
    regions.sort(key=lambda rect: (rect.y0, rect.x0))
    return regions


def _rects_close(a: fitz.Rect, b: fitz.Rect) -> bool:
    return abs(a.x0 - b.x0) < 1 and abs(a.y0 - b.y0) < 1 and abs(a.x1 - b.x1) < 1 and abs(a.y1 - b.y1) < 1


def _box_for_line(line: dict[str, Any], boxes: list[fitz.Rect]) -> int | None:
    bbox = _item_bbox(line)
    center_x = (bbox.x0 + bbox.x1) / 2.0
    center_y = (bbox.y0 + bbox.y1) / 2.0
    for index, rect in enumerate(boxes):
        if rect.x0 - 2 <= center_x <= rect.x1 + 2 and rect.y0 - 2 <= center_y <= rect.y1 + 2:
            return index
    return None


def _flow_column_blocks(page: fitz.Page, items: list[dict[str, Any]], boxes: list[fitz.Rect]) -> list[list[dict[str, Any]]]:
    columns: list[list[dict[str, Any]]] = [[], []]
    midpoint = float(page.rect.width) / 2.0
    for item in items:
        bbox = _item_bbox(item)
        column = 0 if (bbox.x0 + bbox.x1) / 2.0 < midpoint else 1
        columns[column].append(item)

    result: list[list[dict[str, Any]]] = []
    for column_items in columns:
        column_items.sort(key=lambda item: (_item_bbox(item).y0, _item_bbox(item).x0))
        spaced_items: list[dict[str, Any]] = []
        previous_bottom: float | None = None
        previous_box: int | None = None
        for item in column_items:
            bbox = _item_bbox(item)
            box_index = _box_for_line(item, boxes) if item.get("type") != "image" else None
            same_box = previous_box is not None and box_index == previous_box
            if previous_bottom is not None and not same_box:
                gap_pt = bbox.y0 - previous_bottom
                spacer_pt = _flow_gap_height_pt(gap_pt)
                if spacer_pt > 0:
                    spaced_items.append({"type": "gap", "height_pt": spacer_pt})
            spaced_items.append(item)
            previous_bottom = max(bbox.y1, previous_bottom or bbox.y1)
            previous_box = box_index

        blocks: list[dict[str, Any]] = []
        active_box: int | None = None
        active_lines: list[dict[str, Any]] = []
        for item in spaced_items:
            if item.get("type") in {"image", "gap"}:
                if active_lines:
                    blocks.append({"type": "box", "lines": active_lines, "rect": boxes[active_box] if active_box is not None else None})
                    active_lines = []
                    active_box = None
                if item.get("type") == "image":
                    blocks.append({"type": "image", "image": item})
                else:
                    blocks.append(item)
                continue
            box_index = _box_for_line(item, boxes)
            if box_index is None:
                if active_lines:
                    blocks.append({"type": "box", "lines": active_lines, "rect": boxes[active_box] if active_box is not None else None})
                    active_lines = []
                    active_box = None
                blocks.append({"type": "line", "line": item})
                continue
            if active_box is not None and box_index != active_box and active_lines:
                blocks.append({"type": "box", "lines": active_lines, "rect": boxes[active_box]})
                active_lines = []
            active_box = box_index
            active_lines.append(item)
        if active_lines:
            blocks.append({"type": "box", "lines": active_lines, "rect": boxes[active_box] if active_box is not None else None})
        result.append(blocks)
    return result


def _merge_same_row_flow_lines(page: fitz.Page, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines = [item for item in items if item.get("type") == "line"]
    others = [item for item in items if item.get("type") != "line"]
    if len(lines) < 2:
        return items

    def column_index(item: dict[str, Any]) -> int:
        bbox = _item_bbox(item)
        return 0 if (bbox.x0 + bbox.x1) / 2.0 < page.rect.width / 2.0 else 1

    def center_y(item: dict[str, Any]) -> float:
        bbox = _item_bbox(item)
        return (bbox.y0 + bbox.y1) / 2.0

    groups: list[list[dict[str, Any]]] = []
    for line in sorted(lines, key=lambda item: (column_index(item), center_y(item), _item_bbox(item).x0)):
        if groups:
            previous = groups[-1][0]
            if column_index(previous) == column_index(line):
                prev_box = _item_bbox(previous)
                box = _item_bbox(line)
                center_delta = abs(center_y(previous) - center_y(line))
                overlap = max(0.0, min(prev_box.y1, box.y1) - max(prev_box.y0, box.y0))
                if center_delta <= 2.2 or overlap >= min(prev_box.height, box.height) * 0.55:
                    groups[-1].append(line)
                    continue
        groups.append([line])

    merged: list[dict[str, Any]] = []
    for group in groups:
        if len(group) == 1:
            merged.append(group[0])
            continue
        spans: list[dict[str, Any]] = []
        rects: list[fitz.Rect] = []
        for line in group:
            spans.extend(line.get("spans", []))
            rects.append(_item_bbox(line))
        spans.sort(key=lambda span: (fitz.Rect(span["bbox"]).x0, fitz.Rect(span["bbox"]).y0))
        merged.append({"type": "line", "bbox": _union_rect(rects), "spans": spans})
    return merged + others


def _flow_gap_height_pt(raw_gap_pt: float) -> float:
    if raw_gap_pt <= 10.0:
        return 0.0
    return min(6.0, max(0.6, (raw_gap_pt - 10.0) * 0.20))


def _page_body_top(page: fitz.Page) -> float:
    candidates: list[float] = []
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if not item or item[0] != "l":
                continue
            p0, p1 = item[1], item[2]
            x0, y0, x1, y1 = float(p0.x), float(p0.y), float(p1.x), float(p1.y)
            if abs(y1 - y0) > 0.5:
                continue
            if abs(x1 - x0) < page.rect.width * 0.55:
                continue
            y = (y0 + y1) / 2.0
            if 45 <= y <= page.rect.height * 0.35:
                candidates.append(y)
    if not candidates:
        return 0.0
    return max(candidates) + 4.0


def _flow_header_columns(page: fitz.Page, items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    columns: list[list[dict[str, Any]]] = [[], [], []]
    for item in items:
        bbox = _item_bbox(item)
        center_x = (bbox.x0 + bbox.x1) / 2.0
        if center_x < page.rect.width * 0.28:
            column = 0
        elif center_x > page.rect.width * 0.72:
            column = 2
        else:
            column = 1
        columns[column].append(item)
    for column_items in columns:
        column_items.sort(key=lambda item: (_item_bbox(item).y0, _item_bbox(item).x0))
    return columns


def _has_substantial_flow_header(page: fitz.Page, items: list[dict[str, Any]]) -> bool:
    for item in items:
        bbox = _item_bbox(item)
        if item.get("type") == "image":
            if bbox.width >= page.rect.width * 0.16 or bbox.height >= 34:
                return True
            continue
        text = _line_text(item)
        if not text:
            continue
        compact = re.sub(r"[\s\d./()[\]\-]+", "", text)
        if len(compact) >= 12:
            return True
        if bbox.width >= page.rect.width * 0.36:
            return True
    return False


def _append_header_table(
    doc: HwpxDocument,
    page: fitz.Page,
    items: list[dict[str, Any]],
    *,
    table_width: int,
    table_height: int,
    no_border_fill: str,
    compact_para: str,
    styles: dict[tuple[str, float, bool], str],
    page_break: bool,
) -> int:
    if not items:
        return 0
    attrs = {"pageBreak": "1"} if page_break else {}
    table = doc.add_table(
        1,
        3,
        width=table_width,
        height=max(_pt_to_hwp(24), min(table_height, _pt_to_hwp(140))),
        border_fill_id_ref=no_border_fill,
        para_pr_id_ref=compact_para,
        **attrs,
    )
    header_weights = (1.2, 5.6, 1.2)
    try:
        table.set_column_widths(header_weights)
    except Exception:
        pass
    weight_total = sum(header_weights)
    header_cell_widths = [int(round(table_width * weight / weight_total)) for weight in header_weights]
    header_cell_widths[-1] = max(1, table_width - sum(header_cell_widths[:-1]))
    for column in (0, 1, 2):
        _clear_cell_paragraphs(table.cell(0, column))
    count = 0
    for column_index, column_items in enumerate(_flow_header_columns(page, items)):
        cell = table.cell(0, column_index)
        for item in column_items:
            if item.get("type") == "image":
                if _append_cell_image(
                    doc,
                    cell,
                    item,
                    cell_width=max(1, header_cell_widths[column_index]),
                    para_pr_id_ref=compact_para,
                    border_fill_id_ref=no_border_fill,
                ):
                    count += 1
            elif _append_cell_line(doc, cell, item, styles=styles, para_pr_id_ref=compact_para):
                count += 1
    return count


def _append_header_content_to_cell(
    doc: HwpxDocument,
    cell: Any,
    page: fitz.Page,
    items: list[dict[str, Any]],
    *,
    table_width: int,
    table_height: int,
    no_border_fill: str,
    compact_para: str,
    styles: dict[tuple[str, float, bool], str],
) -> int:
    if not items:
        return 0
    _clear_cell_paragraphs(cell)
    table = cell.add_table(
        1,
        3,
        width=table_width,
        height=table_height,
        border_fill_id_ref=no_border_fill,
    )
    header_weights = (1.2, 5.6, 1.2)
    try:
        table.set_column_widths(header_weights)
    except Exception:
        pass
    weight_total = sum(header_weights)
    header_cell_widths = [int(round(table_width * weight / weight_total)) for weight in header_weights]
    header_cell_widths[-1] = max(1, table_width - sum(header_cell_widths[:-1]))
    for column in (0, 1, 2):
        _clear_cell_paragraphs(table.cell(0, column))
    count = 0
    for column_index, column_items in enumerate(_flow_header_columns(page, items)):
        nested_cell = table.cell(0, column_index)
        for item in column_items:
            if item.get("type") == "image":
                if _append_cell_image(
                    doc,
                    nested_cell,
                    item,
                    cell_width=max(1, header_cell_widths[column_index]),
                    para_pr_id_ref=compact_para,
                    border_fill_id_ref=no_border_fill,
                ):
                    count += 1
            elif _append_cell_line(doc, nested_cell, item, styles=styles, para_pr_id_ref=compact_para):
                count += 1
    return count


def _append_spacer_table(
    doc: HwpxDocument,
    *,
    table_width: int,
    table_height: int,
    no_border_fill: str,
    compact_para: str,
    page_break: bool,
) -> bool:
    if table_height <= 0:
        return False
    attrs = {"pageBreak": "1"} if page_break else {}
    doc.add_table(
        1,
        1,
        width=table_width,
        height=max(_pt_to_hwp(4), table_height),
        border_fill_id_ref=no_border_fill,
        para_pr_id_ref=compact_para,
        **attrs,
    )
    return True


def _append_flow_block(
    doc: HwpxDocument,
    cell: Any,
    block: dict[str, Any],
    *,
    styles: dict[tuple[str, float, bool], str],
    para_pr_id_ref: str,
    cell_width: int,
    border_fill_id_ref: str,
    image_border_fill_id_ref: str,
) -> int:
    if block["type"] == "gap":
        height_pt = float(block.get("height_pt") or 0.0)
        if height_pt <= 0:
            return 0
        cell.add_table(
            1,
            1,
            width=max(1, cell_width - _pt_to_hwp(4)),
            height=max(_pt_to_hwp(2), _pt_to_hwp(height_pt)),
            border_fill_id_ref=image_border_fill_id_ref,
        )
        return 0
    if block["type"] == "line":
        return 1 if _append_cell_line(doc, cell, block["line"], styles=styles, para_pr_id_ref=para_pr_id_ref) else 0
    if block["type"] == "image":
        return 1 if _append_cell_image(
            doc,
            cell,
            block["image"],
            cell_width=cell_width,
            para_pr_id_ref=para_pr_id_ref,
            border_fill_id_ref=image_border_fill_id_ref,
        ) else 0

    lines = [line for line in block.get("lines", []) if _line_text(line)]
    if not lines:
        return 0
    height_pt = 14.0
    rect = block.get("rect")
    if rect is not None:
        height_pt = max(height_pt, min(float(rect.height), sum(max(8.0, fitz.Rect(line["bbox"]).height + 1.5) for line in lines)))
    table = cell.add_table(
        1,
        1,
        width=max(1, cell_width - _pt_to_hwp(4)),
        height=max(_pt_to_hwp(height_pt), _pt_to_hwp(12)),
        border_fill_id_ref=border_fill_id_ref,
    )
    nested = table.cell(0, 0)
    _set_cell_margin(nested, left_mm=1.0, right_mm=1.0, top_mm=0.6, bottom_mm=0.6)
    _clear_cell_paragraphs(nested)
    count = 0
    for line in lines:
        if _append_cell_line(doc, nested, line, styles=styles, para_pr_id_ref=para_pr_id_ref):
            count += 1
    return count


def write_pdf_flow_hwpx(
    pdf_path: str | Path,
    output_path: str | Path,
    *,
    max_pages: int | None = None,
    boxed_passages: bool = True,
) -> dict[str, int]:
    """Write a Hancom-viewer-safe editable HWPX using regular paragraphs/tables."""
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = HwpxDocument.new()
    header = doc.headers[0]
    _ensure_pdf_font_faces(header)
    no_border_fill = _ensure_no_border_fill(header)
    box_border_fill = _ensure_box_border_fill(header)
    column_divider_border_fill = _ensure_column_divider_border_fill(header)
    compact_para = header.ensure_paragraph_format(
        alignment="LEFT",
        line_spacing_percent=100,
        margins={"prev": 0, "next": 0},
    )
    body_para = header.ensure_paragraph_format(
        alignment="LEFT",
        line_spacing_percent=_FLOW_BODY_LINE_SPACING,
        margins={"prev": 0, "next": 0},
    )

    styles: dict[tuple[str, float, bool], str] = {}
    page_count = 0
    line_count = 0
    boxed_count = 0
    image_count = 0
    source_text_lines = 0

    with fitz.open(pdf_path) as pdf_doc:
        if not pdf_doc:
            raise ValueError(f"empty PDF: {pdf_path}")
        first = pdf_doc[0]
        width_mm = _pt_to_mm(first.rect.width)
        height_mm = _pt_to_mm(first.rect.height)
        margin_left_mm = 7.0
        margin_right_mm = 7.0
        margin_top_mm = 7.0
        margin_bottom_mm = 7.0
        body_width_mm = max(10.0, width_mm - margin_left_mm - margin_right_mm)
        table_width = _mm_to_hwp(body_width_mm)
        cell_width = max(1, table_width // 2)
        margin_top_pt = margin_top_mm * 72.0 / 25.4
        margin_bottom_pt = margin_bottom_mm * 72.0 / 25.4
        page_orientation = _pdf_page_orientation(first)

        doc.set_page_setup(
            width_mm=width_mm,
            height_mm=height_mm,
            orientation=page_orientation,
            margin_left_mm=margin_left_mm,
            margin_right_mm=margin_right_mm,
            margin_top_mm=margin_top_mm,
            margin_bottom_mm=margin_bottom_mm,
        )

        total_pages = len(pdf_doc) if max_pages is None else min(len(pdf_doc), max_pages)
        for page_index in range(total_pages):
            page = pdf_doc[page_index]
            body_top = _page_body_top(page)
            if body_top <= margin_top_pt:
                body_top = margin_top_pt
            table_image_items = _iter_flow_table_images(page)
            table_regions = [_item_bbox(item) for item in table_image_items]
            native_image_items = [
                item
                for item in _iter_flow_images(page)
                if not _inside_any_region(_item_bbox(item), table_regions)
            ]
            native_image_items = _merge_flow_images(native_image_items)
            native_image_items, textual_image_regions = _convert_textual_image_regions(page, native_image_items)
            excluded_text_regions = table_regions + textual_image_regions
            page_text_lines = [line for line in _iter_text_lines(page) if _line_text(line)]
            source_text_lines += len(page_text_lines)
            line_items = [
                {"type": "line", "bbox": fitz.Rect(line["bbox"]), "spans": line["spans"]}
                for line in page_text_lines
                if not _is_flow_footer_line(page, line)
                and not _inside_any_region(fitz.Rect(line["bbox"]), excluded_text_regions)
            ]
            image_items = native_image_items + table_image_items
            image_count += len(image_items)
            all_items = line_items + image_items
            header_items = [item for item in all_items if _item_bbox(item).y1 < body_top - 1]
            body_items = [item for item in all_items if _item_bbox(item).y1 >= body_top - 1]
            body_items = _merge_same_row_flow_lines(page, body_items)
            repeated_header_spacer = 0
            header_gap_pt = max(0.0, body_top - margin_top_pt)
            if header_items and page_index > 0:
                repeated_header_spacer = _pt_to_hwp(min(header_gap_pt, 140.0))
                header_items = []
            elif header_items and not _has_substantial_flow_header(page, header_items):
                body_items = all_items
                header_items = []
                body_top = margin_top_pt
                header_gap_pt = 0.0
            header_height = _pt_to_hwp(header_gap_pt)
            body_height_pt = max(24.0, page.rect.height - body_top - margin_bottom_pt)
            body_height = _pt_to_hwp(min(body_height_pt, page.rect.height * 0.62))
            header_row_height = 0
            if header_items:
                header_row_height = max(_pt_to_hwp(24), min(header_height, _pt_to_hwp(140)))
            elif repeated_header_spacer > 0:
                header_row_height = max(_pt_to_hwp(4), repeated_header_spacer)
            has_header_row = header_row_height > 0
            body_row_index = 1 if has_header_row else 0
            table_attrs = {"pageBreak": "1"} if page_index > 0 else {}
            table = doc.add_table(
                2 if has_header_row else 1,
                2,
                width=table_width,
                height=body_height + header_row_height,
                border_fill_id_ref=no_border_fill,
                para_pr_id_ref=compact_para,
                **table_attrs,
            )
            body_cells = [table.cell(body_row_index, column) for column in (0, 1)]
            if has_header_row:
                header_cell = table.merge_cells(0, 0, 0, 1)
                header_cell.set_size(table_width, header_row_height)
                _set_cell_border_fill(header_cell, no_border_fill)
                _set_cell_margin(header_cell, left_mm=0.0, right_mm=0.0, top_mm=0.0, bottom_mm=0.0)
                if header_items:
                    line_count += _append_header_content_to_cell(
                        doc,
                        header_cell,
                        page,
                        header_items,
                        table_width=table_width,
                        table_height=header_row_height,
                        no_border_fill=no_border_fill,
                        compact_para=compact_para,
                        styles=styles,
                    )
            for body_cell in body_cells:
                body_cell.set_size(cell_width, body_height)
                _clear_cell_paragraphs(body_cell)
            left_cell, right_cell = body_cells
            _set_cell_border_fill(left_cell, column_divider_border_fill)
            _set_cell_margin(left_cell, left_mm=0.4, right_mm=2.3, top_mm=0.0, bottom_mm=0.0)
            _set_cell_margin(right_cell, left_mm=2.3, right_mm=0.4, top_mm=0.0, bottom_mm=0.0)

            boxes = _flow_box_rects(page) if boxed_passages else []
            columns = _flow_column_blocks(page, body_items, boxes)
            for column_index, blocks in enumerate(columns):
                cell = body_cells[column_index]
                for block in blocks:
                    if block["type"] == "box":
                        boxed_count += 1
                    line_count += _append_flow_block(
                        doc,
                        cell,
                        block,
                        styles=styles,
                        para_pr_id_ref=body_para,
                        cell_width=cell_width,
                        border_fill_id_ref=box_border_fill,
                        image_border_fill_id_ref=no_border_fill,
                    )
            page_count += 1

    _prepare_hancom_compatibility(doc)
    _save_hancom_compatible_document(doc, output_path)
    editable_coverage = 1.0
    if source_text_lines > 0:
        editable_coverage = min(1.0, line_count / source_text_lines)
    return {
        "pages": page_count,
        "source_text_lines": source_text_lines,
        "flow_lines": line_count,
        "editable_text_coverage_ratio": round(editable_coverage, 4),
        "boxed_blocks": boxed_count,
        "images": image_count,
    }


def write_pdf_layout_hwpx(
    pdf_path: str | Path,
    output_path: str | Path,
    *,
    max_pages: int | None = None,
    include_images: bool = True,
    include_lines: bool = True,
    text_mode: Literal["line", "span"] = "line",
    native_math: bool = False,
) -> dict[str, int]:
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = HwpxDocument.new()
    header = doc.headers[0]
    _ensure_pdf_font_faces(header)
    para_left = header.ensure_paragraph_format(
        alignment="LEFT",
        line_spacing_percent=_FLOW_BODY_LINE_SPACING,
    )

    text_count = 0
    image_count = 0
    line_count = 0
    page_count = 0
    source_text_lines = 0
    full_page_image_count = 0
    native_equation_count = 0
    source_math_segment_count = 0
    styles: dict[tuple[str, float, bool], str] = {}
    z_counter = [0]
    equation_counter = [0]

    with fitz.open(pdf_path) as pdf_doc:
        if not pdf_doc:
            raise ValueError(f"empty PDF: {pdf_path}")

        total_pages = len(pdf_doc) if max_pages is None else min(len(pdf_doc), max_pages)
        for page_index in range(total_pages):
            page = pdf_doc[page_index]
            section = doc.sections[0] if page_index == 0 else doc.add_section()
            doc.set_page_size(
                width=_hwp(page.rect.width),
                height=_hwp(page.rect.height),
                orientation=_pdf_page_orientation(page),
                section=section,
            )
            doc.set_page_margins(
                left=0,
                right=0,
                top=0,
                bottom=0,
                header=0,
                footer=0,
                gutter=0,
                section=section,
            )
            attrs = {"inherit_style": False, "include_run": False}
            anchor = doc.add_paragraph("", section=section, **attrs)
            spans = _iter_text_spans(page)
            page_text_lines = [line for line in _iter_text_lines(page) if _line_text(line)]
            source_text_lines += len(page_text_lines)
            text_rects = _text_rects(spans)

            if include_images:
                added_images, added_full_page_images = _add_pdf_images(
                    doc,
                    anchor,
                    pdf_doc,
                    page,
                    text_rects,
                    z_counter,
                )
                image_count += added_images
                full_page_image_count += added_full_page_images
            if include_lines:
                line_count += _add_line_rects(doc, anchor, page, z_counter)

            if text_mode == "line":
                for line in page_text_lines:
                    line_spans = line["spans"]
                    bbox = fitz.Rect(line["bbox"])
                    runs = _span_text_runs(doc, styles, line_spans)
                    if not runs:
                        continue
                    pad_x = 1.5
                    pad_y = 1.0
                    x_pt = max(0.0, bbox.x0 - 0.3)
                    run_stats = _add_text_box_runs(
                        doc,
                        anchor,
                        x_pt=x_pt,
                        y_pt=max(0.0, bbox.y0 - 0.8),
                        width_pt=_expanded_text_width(
                            page.rect,
                            bbox,
                            x_pt,
                            pad_x=pad_x,
                            extra_right_pt=18.0,
                        ),
                        height_pt=max(2.0, bbox.height + pad_y * 2),
                        runs=runs,
                        para_pr_id_ref=para_left,
                        z_order=_next_z(z_counter),
                        equation_counter=equation_counter,
                        native_math=native_math,
                    )
                    native_equation_count += int(run_stats.get("native_equations") or 0)
                    source_math_segment_count += int(run_stats.get("source_math_segments") or 0)
                    text_count += 1
            else:
                for span in spans:
                    text = math_text.normalize_recognized_math_text(str(span.get("text") or ""))
                    bbox = fitz.Rect(span["bbox"])
                    char_pr = _ensure_char_pr(doc, styles, span)
                    pad_x = 1.2
                    pad_y = 1.0
                    x_pt = max(0.0, bbox.x0 - 0.2)
                    run_stats = _add_text_box_runs(
                        doc,
                        anchor,
                        x_pt=x_pt,
                        y_pt=max(0.0, bbox.y0 - 0.8),
                        width_pt=_expanded_text_width(
                            page.rect,
                            bbox,
                            x_pt,
                            pad_x=pad_x,
                            extra_right_pt=6.0,
                        ),
                        height_pt=max(2.0, bbox.height + pad_y * 2),
                        runs=[(text, char_pr)],
                        para_pr_id_ref=para_left,
                        z_order=_next_z(z_counter),
                        equation_counter=equation_counter,
                        native_math=native_math,
                    )
                    native_equation_count += int(run_stats.get("native_equations") or 0)
                    source_math_segment_count += int(run_stats.get("source_math_segments") or 0)
                    text_count += 1
            page_count += 1

    _prepare_hancom_compatibility(doc)
    _save_hancom_compatible_document(doc, output_path)
    editable_coverage = 1.0
    if source_text_lines > 0:
        editable_coverage = min(1.0, text_count / source_text_lines)
    elif full_page_image_count > 0:
        editable_coverage = 0.0
    return {
        "pages": page_count,
        "source_text_lines": source_text_lines,
        "editable_text_coverage_ratio": round(editable_coverage, 4),
        "text_items": text_count,
        "flow_lines": text_count if text_mode == "line" else 0,
        "text_lines": text_count if text_mode == "line" else 0,
        "text_spans": text_count if text_mode == "span" else 0,
        "images": image_count,
        "full_page_images": full_page_image_count,
        "full_page_raster_fallback": full_page_image_count > 0,
        "line_rects": line_count,
        "native_math_enabled": bool(native_math),
        "native_equations": native_equation_count,
        "source_math_segments": source_math_segment_count,
        "native_math_coverage_ratio": (
            round(min(1.0, native_equation_count / source_math_segment_count), 4)
            if source_math_segment_count > 0
            else 1.0
        ),
    }


_LAYOUT_REQUIRED_FONT_FACES = ("신명 중명조", "Times New Roman", "돋움")
_LAYOUT_OLD_DENSE_HEIGHTS = ("840", "940", "1080")


def _section_part_names(archive: zipfile.ZipFile) -> list[str]:
    names = []
    for name in archive.namelist():
        if re.fullmatch(r"Contents/section\d+\.xml", name):
            names.append(name)
    return sorted(names, key=lambda value: int(re.search(r"section(\d+)", value).group(1)))  # type: ignore[union-attr]


def inspect_layout_template_profile(path: str | Path) -> dict[str, Any]:
    """Inspect the generated coordinate-layout HWPX for exam template guards."""
    try:
        with zipfile.ZipFile(path) as archive:
            header = etree.fromstring(archive.read("Contents/header.xml"))
            sections = [etree.fromstring(archive.read(name)) for name in _section_part_names(archive)]
    except Exception as exc:  # noqa: BLE001 - caller records this as an objective quality failure.
        return {"available": False, "error": str(exc)}

    faces = sorted({font.get("face") for font in header.findall(f".//{_hh('font')}") if font.get("face")})
    missing_faces = [face for face in _LAYOUT_REQUIRED_FONT_FACES if face not in faces]

    char_metric_ok = False
    metric_heights: set[str] = set()
    for char_pr in header.findall(f".//{_hh('charPr')}"):
        ratio = char_pr.find(_hh("ratio"))
        spacing = char_pr.find(_hh("spacing"))
        if ratio is None or spacing is None:
            continue
        if (
            ratio.get("hangul") == str(_FLOW_CHAR_RATIO)
            and ratio.get("latin") == str(_FLOW_CHAR_RATIO)
            and spacing.get("hangul") == str(_FLOW_CHAR_SPACING)
            and spacing.get("latin") == str(_FLOW_CHAR_SPACING)
        ):
            char_metric_ok = True
            if char_pr.get("height"):
                metric_heights.add(str(char_pr.get("height")))

    para_165_ids: set[str] = set()
    for para_pr in header.findall(f".//{_hh('paraPr')}"):
        line_spacing = para_pr.find(f".//{_hh('lineSpacing')}")
        if (
            line_spacing is not None
            and line_spacing.get("type") == "PERCENT"
            and line_spacing.get("value") == str(_FLOW_BODY_LINE_SPACING)
        ):
            para_id = para_pr.get("id")
            if para_id:
                para_165_ids.add(str(para_id))
    uses_165 = any(
        (paragraph.get("paraPrIDRef") or "") in para_165_ids
        for section in sections
        for paragraph in section.findall(f".//{_q('p')}")
    )

    metric_height_values = sorted(metric_heights)
    old_dense_used = sorted(set(metric_height_values) & set(_LAYOUT_OLD_DENSE_HEIGHTS))
    font_size_bucket_ok = "1000" in metric_heights and not old_dense_used
    native_equations = sum(len(section.findall(f".//{_q('equation')}")) for section in sections)
    page_breaks = sum(
        1
        for section in sections
        for paragraph in section.findall(f".//{_q('p')}")
        if paragraph.get("pageBreak") == "1"
    )
    page_pr_ok = True
    for section in sections:
        page_pr = section.find(f".//{_q('pagePr')}")
        if page_pr is None:
            page_pr_ok = False
            continue
        try:
            page_pr_ok = page_pr_ok and int(page_pr.get("width") or "0") > 0 and int(page_pr.get("height") or "0") > 0
        except ValueError:
            page_pr_ok = False

    return {
        "available": True,
        "required_font_faces": list(_LAYOUT_REQUIRED_FONT_FACES),
        "faces": faces,
        "missing_required_font_faces": missing_faces,
        "has_required_font_faces": not missing_faces,
        "char_metric_ok": char_metric_ok,
        "metric_heights": metric_height_values,
        "font_size_bucket_ok": font_size_bucket_ok,
        "old_dense_metric_heights": old_dense_used,
        "uses_165_line_spacing": uses_165,
        "native_equations": native_equations,
        "page_break_count": page_breaks,
        "section_count": len(sections),
        "page_pr_ok": page_pr_ok,
    }


def write_pdf_raster_hwpx(
    pdf_path: str | Path,
    output_path: str | Path,
    *,
    dpi: int = 150,
    max_pages: int | None = None,
) -> dict[str, int]:
    """Write a Hancom-viewer-safe HWPX with one rendered page image per page."""
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = HwpxDocument.new()
    _ensure_pdf_font_faces(doc.headers[0])
    doc.set_page_margins(left=0, right=0, top=0, bottom=0, header=0, footer=0, gutter=0)
    page_count = 0
    z_counter = [0]
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)

    with fitz.open(pdf_path) as pdf_doc:
        if not pdf_doc:
            raise ValueError(f"empty PDF: {pdf_path}")
        total_pages = len(pdf_doc) if max_pages is None else min(len(pdf_doc), max_pages)
        current_section = doc.sections[0]
        current_signature: tuple[int, int, str] | None = None
        for page_index in range(total_pages):
            page = pdf_doc[page_index]
            page_width = _hwp(page.rect.width)
            page_height = _hwp(page.rect.height)
            orientation = _pdf_page_orientation(page)
            signature = (page_width, page_height, orientation)
            starts_new_section = current_signature is None or signature != current_signature
            if starts_new_section:
                current_section = doc.sections[0] if page_index == 0 else doc.add_section()
                current_signature = signature
                doc.set_page_size(
                    width=page_width,
                    height=page_height,
                    orientation=orientation,
                    section=current_section,
                )
                doc.set_page_margins(
                    left=0,
                    right=0,
                    top=0,
                    bottom=0,
                    header=0,
                    footer=0,
                    gutter=0,
                    section=current_section,
                )
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            out = io.BytesIO()
            image.save(out, format="PNG", optimize=True)
            image_data = out.getvalue()

            attrs = {"inherit_style": False, "include_run": False}
            if page_index > 0 and not starts_new_section:
                attrs["pageBreak"] = "1"
            anchor = doc.add_paragraph("", section=current_section, **attrs)
            item_id = doc.add_image(image_data, "png")
            pic = anchor.add_picture(
                item_id,
                width=max(1, page_width),
                height=max(1, page_height),
                treat_as_char=False,
            )
            _set_z_order(pic.element, _next_z(z_counter))
            _set_abs_position(pic.element, page.rect.x0, page.rect.y0, page.rect.width, page.rect.height)
            page_count += 1

    _prepare_hancom_compatibility(doc)
    _save_hancom_compatible_document(doc, output_path)
    return {"pages": page_count, "page_images": page_count}
