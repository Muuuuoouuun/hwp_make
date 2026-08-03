"""PDF-coordinate based editable HWPX writer.

This writer is for exam PDFs where visual fidelity matters more than reflow.
It places PDF text spans, ruled lines, and embedded images at their original
page coordinates using editable HWPX drawing text boxes.
"""
from __future__ import annotations

import io
import math
import os
import re
import statistics
import sys
import tempfile
import time
import zipfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import fitz
import numpy as np
from lxml import etree
from PIL import Image, ImageFilter

from . import math_text, pdf_math_ai
from .hancom_pua_map import is_hancom_eq_font
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

_HWP_LANG_ATTRS = ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")
_KICE_B4_PRINT_PAPER_NAME = "B4"
_KICE_B4_PRINT_SCALE = 1.14
_KICE_B4_WIDTH_MM = 257.0
_KICE_B4_HEIGHT_MM = 364.0
_KICE_B4_114_WIDTH_MM = _KICE_B4_WIDTH_MM * _KICE_B4_PRINT_SCALE
_KICE_B4_114_HEIGHT_MM = _KICE_B4_HEIGHT_MM * _KICE_B4_PRINT_SCALE
_KICE_STANDARD_PAGE_PROFILES = (
    ("A4", 210.0, 297.0),
    ("B4", 257.0, 364.0),  # Used by some school/education-office source files.
    ("B4_114", _KICE_B4_114_WIDTH_MM, _KICE_B4_114_HEIGHT_MM),  # KICE A3 source printed on B4 at 114%.
    ("A3", 297.0, 420.0),  # Common for KICE PDF problem sheets.
)
_KICE_STANDARD_PAGES_MM = tuple((width, height) for _name, width, height in _KICE_STANDARD_PAGE_PROFILES)
_KICE_SOURCE_PAGE_OUTPUT_PROFILES = (
    {
        "source_name": "A4",
        "source_width_mm": 210.0,
        "source_height_mm": 297.0,
        "target_name": "A4",
        "target_width_mm": 210.0,
        "target_height_mm": 297.0,
        "print_paper": "",
        "print_scale": 1.0,
    },
    {
        "source_name": "B4",
        "source_width_mm": _KICE_B4_WIDTH_MM,
        "source_height_mm": _KICE_B4_HEIGHT_MM,
        "target_name": "B4",
        "target_width_mm": _KICE_B4_WIDTH_MM,
        "target_height_mm": _KICE_B4_HEIGHT_MM,
        "print_paper": "",
        "print_scale": 1.0,
    },
    {
        "source_name": "A3",
        "source_width_mm": 297.0,
        "source_height_mm": 420.0,
        "target_name": "B4_114",
        "target_width_mm": _KICE_B4_114_WIDTH_MM,
        "target_height_mm": _KICE_B4_114_HEIGHT_MM,
        "print_paper": _KICE_B4_PRINT_PAPER_NAME,
        "print_scale": _KICE_B4_PRINT_SCALE,
    },
)
_KICE_PAGE_SNAP_TOLERANCE_PT = 2.0
_KICE_PAGE_STANDARD_TOLERANCE_MM = 0.75
_MATH_OVERLAY_RENDER_ZOOM = 4.0
_HANCOM_FRACTION_RULE_CHAR = chr(0xE06D)
_MATH_VISUAL_RISK_RE = re.compile(
    r"(?:\\(?:frac|sqrt|sum|int|lim|log|ln|sin|cos|tan)|"
    r"\b(?:lim|log|ln|sin|cos|tan)\b|"
    r"[∫∑√∞≤≥≠≈±×÷∂∆∇πθαβγλμσΩ]|"
    r"[A-Za-z]\s*(?:[_^=<>]|\()|"
    r"(?:\d+\s*[/−-]\s*\d+)|"
    r"(?:[=<>]\s*[-+]?\d))"
)
_MATH_VISUAL_PLACEHOLDER_CHARS = {
    "\u25a1",  # white square
    "\u25a0",  # black square
    "\u25a2",
    "\u25a3",
    "\u25fb",
    "\u25fc",
    "\u25fd",
    "\u25fe",
    "\ufffd",
    "\ufffc",
}


def _pdf_output_text(text: str) -> str:
    """Normalize PDF math glyph recovery output before writing editable text."""
    normalized = math_text.normalize_recognized_math_layout_text(str(text or ""))
    return "".join(
        char
        for char in normalized
        if char not in _MATH_VISUAL_PLACEHOLDER_CHARS and not (0xE000 <= ord(char) <= 0xF8FF)
    )


_MATH_FONT_HINTS = (
    "math",
    "symbol",
    "cmsy",
    "cmmi",
    "cmex",
    "cmr",
    "stmary",
    "esint",
    "mt",
    "tex",
)
_CIRCLED_CHOICE_CHARS = "①②③④⑤⑥⑦⑧⑨"

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

# Thousands of axis-aligned segments usually come from a map or vector
# illustration, not document table chrome.  Quadratic component clustering on
# those paths is both slow and semantically wrong; explicit rectangle objects
# and embedded images still preserve the visual content on such pages.
_MAX_FLOW_LAYOUT_AXIS_LINES = 1200


def _flow_axis_line_count(drawings: list[dict[str, Any]]) -> int:
    """Count long axis-aligned strokes, the marker of vector-heavy pages."""
    count = 0
    for drawing in drawings:
        for item in drawing.get("items", []):
            if not item or item[0] != "l":
                continue
            p0, p1 = item[1], item[2]
            x0, y0, x1, y1 = float(p0.x), float(p0.y), float(p1.x), float(p1.y)
            if (abs(y1 - y0) <= 0.7 and abs(x1 - x0) >= 28) or (
                abs(x1 - x0) <= 0.7 and abs(y1 - y0) >= 8
            ):
                count += 1
    return count


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
    # Hancom 2024 stores portrait pages as WIDELY.  PORTRAIT makes Hancom
    # rotate a width < height page to landscape even though rhwp keeps it tall.
    return "PORTRAIT" if page.rect.width > page.rect.height else "WIDELY"


@dataclass(frozen=True)
class _PageTransform:
    source_width_pt: float
    source_height_pt: float
    target_width_pt: float
    target_height_pt: float
    standard_name: str | None = None
    print_paper: str = ""
    print_scale: float = 1.0

    @property
    def scale_x(self) -> float:
        return self.target_width_pt / max(1.0, self.source_width_pt)

    @property
    def scale_y(self) -> float:
        return self.target_height_pt / max(1.0, self.source_height_pt)

    @property
    def stroke_scale(self) -> float:
        return (self.scale_x + self.scale_y) / 2.0

    @property
    def target_rect(self) -> fitz.Rect:
        return fitz.Rect(0, 0, self.target_width_pt, self.target_height_pt)

    def x(self, value_pt: float) -> float:
        return float(value_pt) * self.scale_x

    def y(self, value_pt: float) -> float:
        return float(value_pt) * self.scale_y

    def width(self, value_pt: float) -> float:
        return float(value_pt) * self.scale_x

    def height(self, value_pt: float) -> float:
        return float(value_pt) * self.scale_y

    def rect(self, rect: fitz.Rect) -> fitz.Rect:
        return fitz.Rect(self.x(rect.x0), self.y(rect.y0), self.x(rect.x1), self.y(rect.y1))


def _standard_exam_page_transform(page: fitz.Page) -> _PageTransform:
    width_pt = float(page.rect.width)
    height_pt = float(page.rect.height)
    match = _match_exam_page_standard_pt(width_pt, height_pt)
    if match is not None:
        standard_name, standard_width_pt, standard_height_pt, print_paper, print_scale = match
        return _PageTransform(
            width_pt,
            height_pt,
            standard_width_pt,
            standard_height_pt,
            standard_name,
            print_paper,
            print_scale,
        )
    return _PageTransform(width_pt, height_pt, width_pt, height_pt)


def _pt_from_mm(value_mm: float) -> float:
    return float(value_mm) * 72.0 / 25.4


def _mm_from_hwp(value_hwp: int) -> float:
    return float(value_hwp) * 25.4 / 7200.0


def _match_exam_page_standard_pt(width_pt: float, height_pt: float) -> tuple[str, float, float, str, float] | None:
    for profile in _KICE_SOURCE_PAGE_OUTPUT_PROFILES:
        source_width_pt = _pt_from_mm(float(profile["source_width_mm"]))
        source_height_pt = _pt_from_mm(float(profile["source_height_mm"]))
        target_width_pt = _pt_from_mm(float(profile["target_width_mm"]))
        target_height_pt = _pt_from_mm(float(profile["target_height_mm"]))
        target_name = str(profile["target_name"])
        print_paper = str(profile["print_paper"])
        print_scale = float(profile["print_scale"])
        if (
            abs(width_pt - source_width_pt) <= _KICE_PAGE_SNAP_TOLERANCE_PT
            and abs(height_pt - source_height_pt) <= _KICE_PAGE_SNAP_TOLERANCE_PT
        ):
            return target_name, target_width_pt, target_height_pt, print_paper, print_scale
        if (
            abs(width_pt - source_height_pt) <= _KICE_PAGE_SNAP_TOLERANCE_PT
            and abs(height_pt - source_width_pt) <= _KICE_PAGE_SNAP_TOLERANCE_PT
        ):
            return target_name, target_height_pt, target_width_pt, print_paper, print_scale
    return None


def _match_exam_page_standard_hwp(width: int, height: int) -> dict[str, Any] | None:
    width_mm = _mm_from_hwp(width)
    height_mm = _mm_from_hwp(height)
    for name, standard_width_mm, standard_height_mm in _KICE_STANDARD_PAGE_PROFILES:
        portrait_delta = max(abs(width_mm - standard_width_mm), abs(height_mm - standard_height_mm))
        if portrait_delta <= _KICE_PAGE_STANDARD_TOLERANCE_MM:
            return {
                "standard_name": name,
                "standard_width_mm": standard_width_mm,
                "standard_height_mm": standard_height_mm,
                "width_delta_mm": round(width_mm - standard_width_mm, 3),
                "height_delta_mm": round(height_mm - standard_height_mm, 3),
                "orientation": "portrait",
                "print_paper": _KICE_B4_PRINT_PAPER_NAME if name == "B4_114" else "",
                "print_scale": _KICE_B4_PRINT_SCALE if name == "B4_114" else 1.0,
            }
        landscape_delta = max(abs(width_mm - standard_height_mm), abs(height_mm - standard_width_mm))
        if landscape_delta <= _KICE_PAGE_STANDARD_TOLERANCE_MM:
            return {
                "standard_name": name,
                "standard_width_mm": standard_height_mm,
                "standard_height_mm": standard_width_mm,
                "width_delta_mm": round(width_mm - standard_height_mm, 3),
                "height_delta_mm": round(height_mm - standard_width_mm, 3),
                "orientation": "landscape",
                "print_paper": _KICE_B4_PRINT_PAPER_NAME if name == "B4_114" else "",
                "print_scale": _KICE_B4_PRINT_SCALE if name == "B4_114" else 1.0,
            }
    return None


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
_PDF_HFT_FONT_FACES = frozenset({"신명 중명조", "한양신명조"})
_PDF_HFT_TYPE_INFO = {
    "familyType": "FCAT_MYUNGJO",
    "weight": "0",
    "proportion": "0",
    "contrast": "0",
    "strokeVariation": "0",
    "armStyle": "0",
    "letterform": "0",
    "midline": "0",
    "xHeight": "0",
}

_FLOW_CHAR_RATIO = 95
_FLOW_CHAR_SPACING = -5
_FLOW_BODY_LINE_SPACING = 165
_FLOW_ENGLISH_BODY_LINE_SPACING = 160
_FLOW_BOX_MIN_LINE_SPACING = 112
_FLOW_BOX_MAX_LINE_SPACING = 165
_FLOW_BOX_MIN_PADDING_PT = 1.2
_FLOW_BOX_MAX_PADDING_PT = 12.0
_FLOW_QUESTION_MARKER_RE = re.compile(r"^\s*([1-9][0-9]?)([.)])(?:\s|$)")


def _ensure_pdf_font_faces(header: Any) -> None:
    for face in _PDF_FONT_FACES:
        _ensure_header_font_face(header, face)


def _ensure_header_font_face(header: Any, face: str) -> None:
    changed = False
    for fontface in header.element.findall(f".//{_hh('fontface')}"):
        fonts = fontface.findall(_hh("font"))
        existing_font = next((font for font in fonts if font.get("face") == face), None)
        if existing_font is not None:
            expected_type = "HFT" if face in _PDF_HFT_FONT_FACES else "TTF"
            if existing_font.get("type") != expected_type:
                existing_font.set("type", expected_type)
                changed = True
            if existing_font.get("isEmbedded") != "0":
                existing_font.set("isEmbedded", "0")
                changed = True
            if expected_type == "HFT":
                type_info = existing_font.find(_hh("typeInfo"))
                if type_info is None:
                    type_info = existing_font.makeelement(_hh("typeInfo"), {})
                    existing_font.append(type_info)
                for name, value in _PDF_HFT_TYPE_INFO.items():
                    if type_info.get(name) != value:
                        type_info.set(name, value)
                        changed = True
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
        expected_type = "HFT" if face in _PDF_HFT_FONT_FACES else "TTF"
        new_font.set("type", expected_type)
        new_font.set("isEmbedded", "0")
        if expected_type == "HFT":
            type_info = new_font.find(_hh("typeInfo"))
            if type_info is None:
                type_info = new_font.makeelement(_hh("typeInfo"), {})
                new_font.append(type_info)
            for name, value in _PDF_HFT_TYPE_INFO.items():
                type_info.set(name, value)
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
    for char_pr_id in sorted(set(str(value) for value in char_pr_ids if value is not None)):
        char_pr = header.element.find(f".//{_hh('charPr')}[@id='{char_pr_id}']")
        if char_pr is None:
            continue
        for local_name, value in (("ratio", ratio), ("spacing", spacing)):
            child = _ensure_char_metric_child(char_pr, local_name)
            safe_value = str(int(value))
            for attr in _HWP_LANG_ATTRS:
                if child.get(attr) != safe_value:
                    child.set(attr, safe_value)
                    changed = True
    if changed:
        header.mark_dirty()


def _set_char_pr_font_face(header: Any, char_pr_id: str | int, face: str) -> None:
    target_font_ref = header.font_ref_for_face(face)
    if target_font_ref is None:
        return
    char_pr = header.element.find(f".//{_hh('charPr')}[@id='{char_pr_id}']")
    if char_pr is None:
        return
    font_ref = char_pr.find(_hh("fontRef"))
    if font_ref is None:
        font_ref = char_pr.makeelement(_hh("fontRef"), {})
        char_pr.insert(0, font_ref)
    changed = False
    for attr in list(font_ref.attrib):
        if attr not in _HWP_LANG_ATTRS:
            del font_ref.attrib[attr]
            changed = True
    for attr, value in target_font_ref.items():
        if font_ref.get(attr) != value:
            font_ref.set(attr, value)
            changed = True
    if changed:
        header.mark_dirty()


def _apply_exam_base_text_profile(header: Any) -> None:
    base_id = "0"
    char_pr = header.element.find(f".//{_hh('charPr')}[@id='{base_id}']")
    if char_pr is not None and char_pr.get("height") != "1000":
        char_pr.set("height", "1000")
        header.mark_dirty()
    _set_char_pr_font_face(header, base_id, "HY신명조")
    _apply_char_metrics(header, [base_id], ratio=_FLOW_CHAR_RATIO, spacing=_FLOW_CHAR_SPACING)


def _latin_ratio(text: str) -> float:
    meaningful = [ch for ch in text if ch.isalpha() or "\uac00" <= ch <= "\ud7a3"]
    if not meaningful:
        return 0.0
    latin = sum(1 for ch in meaningful if ("A" <= ch <= "Z") or ("a" <= ch <= "z"))
    return latin / len(meaningful)


def _span_size(span: dict[str, Any], default: float = 10.0) -> float:
    try:
        return float(span.get("size") or default)
    except (TypeError, ValueError):
        return default


def _is_exam_title_span(span: dict[str, Any]) -> bool:
    text = str(span.get("text") or "").strip()
    size = _span_size(span)
    if size >= 13.0:
        return True
    return size >= 12.0 and any(token in text for token in ("영역", "문제지", "선택", "홀수형"))


def _exam_bold_for_span(span: dict[str, Any]) -> bool:
    return _bold_for_span(span) or _is_exam_title_span(span)


def _flow_font_for_span(span: dict[str, Any]) -> str:
    text = str(span.get("text") or "")
    font = str(span.get("font") or "")
    recovered = _recover_pdf_font_name(font)
    if _is_exam_title_span(span):
        return "돋움"
    if is_hancom_eq_font(font):
        # Hancom equation PUA is recovered to Unicode symbols by
        # ``_pdf_output_text``; Times renders those far better than a Hangul face.
        return "Times New Roman"
    if _latin_ratio(text) >= 0.55 or "Times" in font or "NewRoman" in font:
        return "Times New Roman"
    if _bold_for_span(span):
        return "돋움"
    if any(token in recovered for token in ("고딕", "그래픽", "굴림")):
        return "돋움"
    if any(token in recovered for token in ("명조", "바탕")):
        return "HY신명조"
    return "HY신명조"


def _flow_size_for_span(span: dict[str, Any]) -> float:
    size = _span_size(span)
    if span.get("preserve_size"):
        return max(5.5, size)
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
            "baseUnit": "800",
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
    # Inline equations report a zero object width in OWPML and rely on the
    # following text run to reserve horizontal flow space.  Without this
    # placeholder rhwp/Hancom place consecutive fractions, integrals and
    # surrounding prose at the same x coordinate, which is the source of the
    # severe overlap seen in real KICE math papers.
    placeholder = _append_xml_child(run, _q("t"))
    placeholder.set(f"{{{XML}}}space", "preserve")
    placeholder.text = "\u00a0" * len(_equation_placeholder(script))


def _append_positioned_pdf_equation(
    anchor: Any,
    *,
    script: str,
    x_pt: float,
    y_pt: float,
    width_pt: float,
    height_pt: float,
    char_pr_id_ref: str,
    z_order: int,
    equation_index: int,
) -> None:
    parent = getattr(anchor, "element", anchor)
    run = _append_xml_child(parent, _q("run"))
    run.set("charPrIDRef", str(char_pr_id_ref))
    equation = _append_xml_child(
        run,
        _q("equation"),
        {
            "id": str(1900000000 + equation_index),
            "zOrder": str(max(0, int(z_order))),
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
        {
            "width": str(max(1, _hwp(width_pt))),
            "widthRelTo": "ABSOLUTE",
            "height": str(max(1, _hwp(height_pt))),
            "heightRelTo": "ABSOLUTE",
            "protect": "0",
        },
    )
    _append_xml_child(
        equation,
        _q("pos"),
        {
            "treatAsChar": "0",
            "affectLSpacing": "0",
            "flowWithText": "0",
            "allowOverlap": "1",
            "holdAnchorAndSO": "0",
            "vertRelTo": "PAPER",
            "horzRelTo": "PAPER",
            "vertAlign": "TOP",
            "horzAlign": "LEFT",
            "vertOffset": str(_hwp(y_pt)),
            "horzOffset": str(_hwp(x_pt)),
        },
    )
    _append_xml_child(equation, _q("outMargin"), {"left": "56", "right": "56", "top": "0", "bottom": "0"})
    comment = _append_xml_child(equation, _q("shapeComment"))
    comment.text = "?섏떇?낅땲??"
    script_node = _append_xml_child(equation, _q("script"))
    script_node.text = script


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
) -> dict[str, Any]:
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
            output_segment = _pdf_output_text(segment)
            if output_segment == "":
                continue
            if output_segment.isspace():
                output_segment = " "
            _append_pdf_text_run(paragraph, output_segment, char_pr_id_ref)
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


def _add_equation_text_box(
    doc: HwpxDocument,
    anchor: Any,
    *,
    x_pt: float,
    y_pt: float,
    width_pt: float,
    height_pt: float,
    script: str,
    char_pr_id_ref: str,
    para_pr_id_ref: str,
    z_order: int,
    equation_counter: list[int],
) -> bool:
    normalized_script = _hancom_eqn_script(script) or script.strip()
    if not normalized_script:
        return False
    eq_width_pt, eq_height_pt = (value / HWP_PER_PT for value in _equation_size(normalized_script))
    width_pt = max(2.0, width_pt, eq_width_pt + 3.0)
    height_pt = max(2.0, height_pt, eq_height_pt + 2.0)
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
    equation_counter[0] += 1
    _append_pdf_equation(run, normalized_script, equation_counter[0])
    _append_text_box_lineseg(paragraph, width_pt, height_pt)

    shadow = element.find(_q("shadow"))
    _insert_before_child(element, draw, shadow)
    return True


def _add_positioned_equation(
    anchor: Any,
    *,
    x_pt: float,
    y_pt: float,
    width_pt: float,
    height_pt: float,
    script: str,
    char_pr_id_ref: str,
    z_order: int,
    equation_counter: list[int],
) -> bool:
    normalized_script = _hancom_eqn_script(script) or script.strip()
    if not normalized_script:
        return False
    eq_width_pt, eq_height_pt = (value / HWP_PER_PT for value in _equation_size(normalized_script))
    equation_counter[0] += 1
    _append_positioned_pdf_equation(
        anchor,
        script=normalized_script,
        x_pt=x_pt,
        y_pt=y_pt,
        width_pt=max(2.0, width_pt, eq_width_pt + 3.0),
        height_pt=max(2.0, height_pt, eq_height_pt + 2.0),
        char_pr_id_ref=char_pr_id_ref,
        z_order=z_order,
        equation_index=equation_counter[0],
    )
    return True


def _add_positioned_equation_table(
    doc: HwpxDocument,
    anchor: Any,
    *,
    x_pt: float,
    y_pt: float,
    width_pt: float,
    height_pt: float,
    script: str,
    char_pr_id_ref: str,
    z_order: int,
    equation_counter: list[int],
) -> bool:
    """Place an inline editable equation inside an absolutely positioned table."""
    normalized_script = _hancom_eqn_script(script) or script.strip()
    if not normalized_script:
        return False
    eq_width_pt, eq_height_pt = (
        value / HWP_PER_PT for value in _equation_size(normalized_script)
    )
    width_pt = max(4.0, width_pt, eq_width_pt + 3.0)
    height_pt = max(4.0, height_pt, eq_height_pt + 2.0)
    no_border = _ensure_no_border_fill(doc.headers[0])
    table = anchor.add_table(
        1,
        1,
        width=max(1, _hwp(width_pt)),
        height=max(1, _hwp(height_pt)),
        border_fill_id_ref=no_border,
    )
    _set_z_order(table.element, z_order)
    _set_abs_position(table.element, x_pt, y_pt, width_pt, height_pt)
    cell = table.cell(0, 0)
    cell.set_size(max(1, _hwp(width_pt)), max(1, _hwp(height_pt)))
    _set_cell_vertical_alignment(cell, "CENTER")
    _set_cell_margin(cell, left_mm=0.0, right_mm=0.0, top_mm=0.0, bottom_mm=0.0)
    _clear_cell_paragraphs(cell)
    paragraph = cell.add_paragraph("", para_pr_id_ref="0", char_pr_id_ref=char_pr_id_ref)
    run = paragraph.element.find(_q("run"))
    if run is None:
        run = _append_xml_child(paragraph.element, _q("run"))
        run.set("charPrIDRef", str(char_pr_id_ref))
    equation_counter[0] += 1
    _append_pdf_equation(run, normalized_script, equation_counter[0])
    return True


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


def _add_line_rects(
    doc: HwpxDocument,
    anchor: Any,
    page: fitz.Page,
    z_counter: list[int],
    page_transform: _PageTransform | None = None,
    *,
    exclude_source_rects: list[fitz.Rect] | None = None,
    include_strokes: bool = True,
    include_fills: bool = True,
) -> int:
    count = 0
    transform = page_transform or _standard_exam_page_transform(page)
    seen: set[tuple[str, int, int, int, int, int, str]] = set()
    for drawing in page.get_drawings():
        width_pt = max(0.25, float(drawing.get("width") or 0.6) * transform.stroke_scale)
        color_hex = _pdf_color_hex(drawing.get("color"), "#000000")
        fill_hex = _pdf_color_hex(drawing.get("fill"), "")
        items = drawing.get("items", [])
        drawing_rect = drawing.get("rect")
        if drawing_rect is not None:
            drawing_rect = fitz.Rect(drawing_rect)
            target_drawing_rect = transform.rect(drawing_rect)
            if _is_hidden_header_rect(drawing_rect):
                continue
            if _rect_center_in_any(drawing_rect, exclude_source_rects):
                continue
            if (
                include_strokes
                and
                drawing.get("color") is not None
                and len(items) >= 8
                and drawing_rect.width <= 140
                and drawing_rect.height <= 70
                and all(item and item[0] == "l" for item in items)
            ):
                _add_rounded_rect_outline(
                    doc,
                    anchor,
                    x_pt=target_drawing_rect.x0,
                    y_pt=target_drawing_rect.y0,
                    width_pt=target_drawing_rect.width,
                    height_pt=target_drawing_rect.height,
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
                if not include_strokes:
                    continue
                p0, p1 = item[1], item[2]
                x0, y0, x1, y1 = float(p0.x), float(p0.y), float(p1.x), float(p1.y)
                line_rect = fitz.Rect(
                    min(x0, x1),
                    min(y0, y1) - max(0.5, width_pt),
                    max(x0, x1),
                    max(y0, y1) + max(0.5, width_pt),
                )
                if _rect_center_in_any(line_rect, exclude_source_rects):
                    continue
                key = _line_dedupe_key("l", x0, y0, x1, y1, width_pt, color_hex)
                if key in seen:
                    continue
                seen.add(key)
                tx0, ty0 = transform.x(x0), transform.y(y0)
                tx1, ty1 = transform.x(x1), transform.y(y1)
                if abs(y1 - y0) <= 0.35:
                    _add_straight_line(
                        doc,
                        anchor,
                        x0_pt=tx0,
                        y0_pt=ty0,
                        x1_pt=tx1,
                        y1_pt=ty1,
                        line_width_pt=width_pt,
                        color=color_hex,
                        z_order=_next_z(z_counter),
                    )
                    count += 1
                elif abs(x1 - x0) <= 0.35:
                    _add_straight_line(
                        doc,
                        anchor,
                        x0_pt=tx0,
                        y0_pt=ty0,
                        x1_pt=tx1,
                        y1_pt=ty1,
                        line_width_pt=width_pt,
                        color=color_hex,
                        z_order=_next_z(z_counter),
                    )
                    count += 1
            elif kind == "re":
                rect = item[1]
                if _rect_center_in_any(fitz.Rect(rect), exclude_source_rects):
                    continue
                target_rect = transform.rect(fitz.Rect(rect))
                if (
                    include_fills
                    and fill_hex
                    and fill_hex.upper() not in {"#FFFFFF", "#FFFFFE"}
                ):
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
                        x_pt=float(target_rect.x0),
                        y_pt=float(target_rect.y0),
                        width_pt=float(target_rect.width),
                        height_pt=float(target_rect.height),
                        color=fill_hex,
                        z_order=_next_z(z_counter),
                    )
                    count += 1
                if include_strokes and drawing.get("color") is not None:
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
                        x_pt=float(target_rect.x0),
                        y_pt=float(target_rect.y0),
                        width_pt=float(target_rect.width),
                        height_pt=float(target_rect.height),
                        line_width_pt=width_pt,
                        color=color_hex,
                        z_order=_next_z(z_counter),
                    )
                    count += 1
    return count


def _add_fraction_rule_glyph_lines(
    doc: HwpxDocument,
    anchor: Any,
    page: fitz.Page,
    z_counter: list[int],
    page_transform: _PageTransform | None = None,
    *,
    exclude_source_rects: list[fitz.Rect] | None = None,
) -> int:
    transform = page_transform or _standard_exam_page_transform(page)
    count = 0
    seen: set[tuple[int, int, int, int]] = set()
    try:
        blocks = page.get_text("rawdict").get("blocks", [])
    except Exception:
        return 0
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for char in span.get("chars") or []:
                    if str(char.get("c") or "") != _HANCOM_FRACTION_RULE_CHAR:
                        continue
                    rect = fitz.Rect(char.get("bbox") or (0, 0, 0, 0))
                    if rect.width < 2.0 or rect.height < 2.0:
                        continue
                    if _rect_center_in_any(rect, exclude_source_rects):
                        continue
                    key = (
                        int(round(rect.x0 * 10)),
                        int(round(rect.y0 * 10)),
                        int(round(rect.x1 * 10)),
                        int(round(rect.y1 * 10)),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    y_pt = rect.y0 + rect.height * 0.40
                    target = transform.rect(rect)
                    target_y = transform.y(y_pt)
                    _add_straight_line(
                        doc,
                        anchor,
                        x0_pt=target.x0,
                        y0_pt=target_y,
                        x1_pt=target.x1,
                        y1_pt=target_y,
                        line_width_pt=max(0.35, 0.52 * transform.stroke_scale),
                        color="#000000",
                        z_order=_next_z(z_counter),
                    )
                    count += 1
    return count


def _rect_center_in_any(rect: fitz.Rect, containers: list[fitz.Rect] | None) -> bool:
    if not containers:
        return False
    center_x = (float(rect.x0) + float(rect.x1)) / 2.0
    center_y = (float(rect.y0) + float(rect.y1)) / 2.0
    for container in containers:
        candidate = fitz.Rect(container)
        if candidate.is_empty:
            continue
        if (
            candidate.x0 - 0.5 <= center_x <= candidate.x1 + 0.5
            and candidate.y0 - 0.5 <= center_y <= candidate.y1 + 0.5
        ):
            return True
    return False


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
    page_transform: _PageTransform | None = None,
) -> tuple[int, int]:
    count = 0
    full_page_count = 0
    transform = page_transform or _standard_exam_page_transform(page)
    for info in page.get_image_info(xrefs=True):
        rect = fitz.Rect(info["bbox"])
        if rect.width < 2 or rect.height < 2:
            continue
        covers_page = _covers_page_area(page, rect)
        if _overlaps_text(rect, text_rects) and not covers_page:
            continue
        xref = int(info.get("xref") or 0)
        if xref <= 0:
            continue
        try:
            pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0), clip=rect, alpha=False)
            image_data = pix.tobytes("png")
        except Exception:
            continue
        target_rect = transform.rect(rect)
        item_id = doc.add_image(image_data, "png")
        pic = anchor.add_picture(
            item_id,
            width=max(1, _hwp(target_rect.width)),
            height=max(1, _hwp(target_rect.height)),
            treat_as_char=False,
        )
        _set_z_order(pic.element, _next_z(z_counter))
        _set_abs_position(pic.element, target_rect.x0, target_rect.y0, target_rect.width, target_rect.height)
        count += 1
        if covers_page:
            full_page_count += 1
    return count, full_page_count


def _span_uses_math_font(span: dict[str, Any]) -> bool:
    font = str(span.get("font") or "").lower()
    if any(hint in font for hint in _MATH_FONT_HINTS):
        return True
    recovered = _recover_pdf_font_name(font).lower()
    return any(hint in recovered for hint in _MATH_FONT_HINTS)


def _contains_private_or_placeholder(text: str) -> bool:
    if any(char in text for char in _MATH_VISUAL_PLACEHOLDER_CHARS):
        return True
    return any(0xE000 <= ord(char) <= 0xF8FF for char in text)


def _line_has_math_visual_risk(line: dict[str, Any]) -> bool:
    text = _line_text(line)
    if not text:
        return False
    normalized = math_text.normalize_recognized_math_text(text)
    if _contains_private_or_placeholder(text) or _contains_private_or_placeholder(normalized):
        return True
    spans = list(line.get("spans") or [])
    math_font_count = sum(1 for span in spans if _span_uses_math_font(span))
    has_math_font = math_font_count > 0
    has_choice = any(char in normalized for char in _CIRCLED_CHOICE_CHARS)
    has_operator = any(char in normalized for char in "+-=<>/()[]{}")
    has_digit = any(char.isdigit() for char in normalized)
    has_latin = bool(re.search(r"[A-Za-z]", normalized))
    if _MATH_VISUAL_RISK_RE.search(normalized):
        return True
    if has_math_font and (has_operator or has_digit or has_latin or has_choice):
        return True
    if has_choice and has_digit and (has_operator or math_font_count >= 2):
        return True
    if len(spans) >= 4 and has_digit and (has_operator or has_choice) and not re.search(r"[가-힣]{6,}", normalized):
        return True
    return False


def _clip_rect_with_padding(
    page: fitz.Page,
    rect: fitz.Rect,
    *,
    pad_x: float = 2.5,
    pad_y: float = 4.0,
    relative_vertical_pad: float = 0.55,
    max_vertical_pad: float = 10.0,
) -> fitz.Rect:
    padded = fitz.Rect(rect)
    vertical_pad = max(
        pad_y,
        min(max_vertical_pad, rect.height * relative_vertical_pad),
    )
    padded.x0 = max(float(page.rect.x0), padded.x0 - pad_x)
    padded.x1 = min(float(page.rect.x1), padded.x1 + pad_x)
    padded.y0 = max(float(page.rect.y0), padded.y0 - vertical_pad)
    padded.y1 = min(float(page.rect.y1), padded.y1 + vertical_pad)
    return padded


def _add_pdf_clip_overlay(
    doc: HwpxDocument,
    anchor: Any,
    page: fitz.Page,
    source_rect: fitz.Rect,
    z_counter: list[int],
    page_transform: _PageTransform,
    *,
    render_zoom: float = _MATH_OVERLAY_RENDER_ZOOM,
    tight_text_clip: bool = False,
    whiten_near_white: bool = False,
    soften_foreground_strokes: bool = False,
    foreground_stroke_soften_strength: float = 0.42,
    compress_grayscale: bool = False,
    force_grayscale: bool = False,
) -> tuple[bool, float]:
    clip = _clip_rect_with_padding(
        page,
        source_rect,
        pad_x=1.0 if tight_text_clip else 2.5,
        pad_y=1.2 if tight_text_clip else 4.0,
        relative_vertical_pad=0.16 if tight_text_clip else 0.55,
        max_vertical_pad=2.4 if tight_text_clip else 10.0,
    )
    if clip.width < 1.0 or clip.height < 1.0:
        return False, 0.0
    try:
        zoom = max(1.0, float(render_zoom))
        pix = page.get_pixmap(
            matrix=fitz.Matrix(zoom, zoom),
            clip=clip,
            alpha=False,
        )
        image_data = pix.tobytes("png")
        if soften_foreground_strokes:
            image = Image.open(io.BytesIO(image_data)).convert("RGB")
            eroded = image.filter(ImageFilter.MaxFilter(3))
            softened = Image.blend(
                image,
                eroded,
                max(0.0, min(1.0, float(foreground_stroke_soften_strength))),
            )
            output = io.BytesIO()
            softened.save(output, format="PNG", optimize=True)
            image_data = output.getvalue()
        if whiten_near_white:
            image = Image.open(io.BytesIO(image_data)).convert("RGB")
            pixels = np.asarray(image).copy()
            near_white = np.min(pixels, axis=2) >= 244
            pixels[near_white] = 255
            normalized = Image.fromarray(pixels, mode="RGB")
            output = io.BytesIO()
            normalized.save(output, format="PNG", optimize=True)
            image_data = output.getvalue()
        if compress_grayscale:
            image = Image.open(io.BytesIO(image_data)).convert("RGB")
            is_grayscale = force_grayscale
            if not is_grayscale:
                pixels = np.asarray(image)
                channel_spread = pixels.max(axis=2) - pixels.min(axis=2)
                is_grayscale = int(channel_spread.max(initial=0)) <= 2
            if is_grayscale:
                output = io.BytesIO()
                image.convert("L").save(output, format="PNG", compress_level=6)
                image_data = output.getvalue()
    except Exception:
        return False, 0.0
    target_rect = page_transform.rect(clip)
    item_id = doc.add_image(image_data, "png")
    pic = anchor.add_picture(
        item_id,
        width=max(1, _hwp(target_rect.width)),
        height=max(1, _hwp(target_rect.height)),
        treat_as_char=False,
    )
    _set_z_order(pic.element, _next_z(z_counter))
    _set_abs_position(pic.element, target_rect.x0, target_rect.y0, target_rect.width, target_rect.height)
    return True, clip.width * clip.height


def _text_visual_overlay_rects(
    page: fitz.Page,
    text_lines: list[dict[str, Any]],
) -> list[fitz.Rect]:
    """Group editable source lines into compact visual overlay regions.

    The overlay preserves exact glyphs and nearby vector frames while the
    coordinate text underneath remains editable. Grouping by column and visual
    continuity avoids thousands of one-line pictures and never creates a
    full-page raster fallback.
    """
    page_rect = fitz.Rect(page.rect)
    midpoint = page_rect.width / 2.0
    lanes: dict[int, list[fitz.Rect]] = {0: [], 1: [], 2: []}
    for line in text_lines:
        bbox = _item_bbox(line)
        if bbox.width <= 0 or bbox.height <= 0:
            continue
        center_x = (bbox.x0 + bbox.x1) / 2.0
        if bbox.width >= page_rect.width * 0.56:
            lane = 2
        else:
            lane = 0 if center_x < midpoint else 1
        lanes[lane].append(fitz.Rect(bbox))

    groups: list[fitz.Rect] = []
    for lane, rects in lanes.items():
        active: fitz.Rect | None = None
        active_lines = 0
        for rect in sorted(rects, key=lambda value: (value.y0, value.x0)):
            if active is None:
                active = fitz.Rect(rect)
                active_lines = 1
                continue
            vertical_gap = rect.y0 - active.y1
            same_band = rect.y0 <= active.y1 + 1.5
            maximum_gap = 13.0 if lane != 2 else 10.0
            if (
                (same_band or vertical_gap <= maximum_gap)
                and active_lines < 44
                and max(active.y1, rect.y1) - min(active.y0, rect.y0)
                <= page_rect.height * 0.52
            ):
                active.include_rect(rect)
                active_lines += 1
            else:
                groups.append(active)
                active = fitz.Rect(rect)
                active_lines = 1
        if active is not None:
            groups.append(active)

    drawing_rects: list[fitz.Rect] = []
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing.get("rect") or (0, 0, 0, 0))
        if rect.width <= 0.5 or rect.height <= 0.5:
            continue
        if rect.get_area() >= page_rect.get_area() * 0.42:
            continue
        if rect.width <= 3.0 and rect.height >= page_rect.height * 0.38:
            continue
        drawing_rects.append(rect)
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 1:
            continue
        rect = fitz.Rect(block.get("bbox") or (0, 0, 0, 0))
        if rect.width <= 1.0 or rect.height <= 1.0:
            continue
        if rect.get_area() >= page_rect.get_area() * 0.42:
            continue
        drawing_rects.append(rect)

    expanded: list[fitz.Rect] = []
    for group in groups:
        region = fitz.Rect(group)
        for _ in range(3):
            changed = False
            probe = fitz.Rect(region.x0 - 3.0, region.y0 - 3.0, region.x1 + 3.0, region.y1 + 3.0)
            for drawing_rect in drawing_rects:
                if not probe.intersects(drawing_rect):
                    continue
                combined = fitz.Rect(region)
                combined.include_rect(drawing_rect)
                if (
                    combined.width <= page_rect.width * 0.58
                    and combined.height <= page_rect.height * 0.58
                ):
                    before = tuple(region)
                    region.include_rect(drawing_rect)
                    changed = changed or tuple(region) != before
            if not changed:
                break
        region.x0 = max(page_rect.x0, region.x0 - 2.0)
        region.y0 = max(page_rect.y0, region.y0 - 2.0)
        region.x1 = min(page_rect.x1, region.x1 + 2.0)
        region.y1 = min(page_rect.y1, region.y1 + 2.0)
        expanded.append(region)

    # Merge only heavily overlapping regions; adjacent question blocks remain
    # separate so their combined pictures cannot resemble a tiled page image.
    merged: list[fitz.Rect] = []
    for region in sorted(expanded, key=lambda value: (value.y0, value.x0)):
        for existing in merged:
            intersection = existing & region
            if (
                not intersection.is_empty
                and intersection.get_area()
                >= min(existing.get_area(), region.get_area()) * 0.72
            ):
                existing.include_rect(region)
                break
        else:
            merged.append(fitz.Rect(region))
    return merged


def _foreground_visual_overlay_rects(
    page: fitz.Page,
    *,
    right_pad: float = 5.0,
) -> list[fitz.Rect]:
    """Cover every rendered ink band without creating a full-page picture."""
    # Thin gray table, callout, and column rules can land above the general
    # 170-luma ink cutoff at the one-point detection render. A wider detection
    # cutoff keeps those source rules continuous; final clips remain bounded
    # by the actual detected geometry and retain the stricter pixel content.
    dark = _page_dark_pixels(page, threshold=220)
    if dark is None or not dark.any():
        return []
    height, width = dark.shape
    midpoint = width // 2
    gutter = max(3, int(round(width * 0.004)))
    lanes = (
        (0, max(1, midpoint - gutter), 10),
        (min(width - 1, midpoint + gutter), width, 10),
        (max(0, midpoint - gutter), min(width, midpoint + gutter), 5),
    )
    regions: list[fitz.Rect] = []
    for lane_left, lane_right, merge_gap in lanes:
        if lane_right - lane_left <= 0:
            continue
        lane = dark[:, lane_left:lane_right]
        minimum_row_ink = max(1, int(round((lane_right - lane_left) * 0.0025)))
        occupied_rows = lane.sum(axis=1) >= minimum_row_ink
        raw_runs = _binary_runs(occupied_rows, minimum=1)
        merged_runs: list[list[int]] = []
        for start, end in raw_runs:
            if merged_runs and start - merged_runs[-1][1] <= merge_gap:
                merged_runs[-1][1] = end
            else:
                merged_runs.append([start, end])
        for start, end in merged_runs:
            band = lane[start:end, :]
            points = np.argwhere(band)
            if points.size == 0:
                continue
            x0 = lane_left + int(points[:, 1].min())
            x1 = lane_left + int(points[:, 1].max()) + 1
            y0 = int(start + points[:, 0].min())
            y1 = int(start + points[:, 0].max()) + 1
            rect = fitz.Rect(
                max(0.0, float(x0 - 2)),
                max(0.0, float(y0 - 2)),
                min(float(width), float(x1 + right_pad)),
                min(float(height), float(y1 + 2)),
            )
            if rect.width >= 2.0 and rect.height >= 2.0:
                regions.append(rect)

    return regions


def _column_visual_overlay_rects(page: fitz.Page) -> list[fitz.Rect]:
    """Return two source-ink column crops with stable within-column geometry."""
    dark = _page_dark_pixels(page)
    if dark is None or not dark.any():
        return []
    height, width = dark.shape
    midpoint = width // 2
    regions: list[fitz.Rect] = []
    for lane_left, lane_right in ((0, midpoint + 2), (midpoint - 2, width)):
        lane = dark[:, lane_left:lane_right]
        points = np.argwhere(lane)
        if points.size == 0:
            continue
        x0 = lane_left + int(points[:, 1].min())
        x1 = lane_left + int(points[:, 1].max()) + 1
        y0 = int(points[:, 0].min())
        y1 = int(points[:, 0].max()) + 1
        regions.append(
            fitz.Rect(
                max(0.0, float(x0 - 5)),
                max(0.0, float(y0 - 5)),
                min(float(width), float(x1 + 22)),
                min(float(height), float(y1 + 5)),
            )
        )
    return regions


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
    for block in page.get_text("rawdict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans: list[dict[str, Any]] = []
            for span in line.get("spans", []):
                chars = [char for char in span.get("chars", []) if str(char.get("c") or "") != ""]
                text = "".join(str(char.get("c") or "") for char in chars)
                if text == "":
                    continue
                bbox = span.get("bbox") or _union_rect([fitz.Rect(char["bbox"]) for char in chars])
                if not bbox:
                    continue
                rect = fitz.Rect(bbox)
                if rect.x0 < 210 and rect.y1 < 150 and "홀수형" in text:
                    continue
                copied = dict(span)
                copied["text"] = text
                copied["chars"] = chars
                copied["bbox"] = tuple(rect)
                spans.append(copied)
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
    *,
    size_scale: float = 1.0,
    force_font: str | None = None,
) -> str:
    size = max(5.5, round(_flow_size_for_span(span) * max(0.1, size_scale), 2))
    font = force_font or _flow_font_for_span(span)
    bold = _exam_bold_for_span(span)
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
    *,
    size_scale: float = 1.0,
    force_font: str | None = None,
) -> list[tuple[str, str]]:
    runs: list[tuple[str, str]] = []
    previous_rect: fitz.Rect | None = None
    previous_size = 10.0
    for span in spans:
        text = _pdf_output_text(str(span.get("text") or ""))
        if text == "":
            continue
        rect = fitz.Rect(span["bbox"])
        size = float(span.get("size") or previous_size)
        if previous_rect is not None and not text.startswith(" "):
            gap = rect.x0 - previous_rect.x1
            if gap > max(2.2, previous_size * 0.22):
                runs.append(
                    (
                        " ",
                        _ensure_char_pr(
                            doc,
                            styles,
                            span,
                            size_scale=size_scale,
                            force_font=force_font,
                        ),
                    )
                )
        runs.append(
            (
                text,
                _ensure_char_pr(
                    doc,
                    styles,
                    span,
                    size_scale=size_scale,
                    force_font=force_font,
                ),
            )
        )
        previous_rect = rect
        previous_size = size
    return runs


def _line_chars(line: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    chars: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for span in line.get("spans", []):
        for char in span.get("chars") or []:
            if str(char.get("c") or "") == "":
                continue
            chars.append((span, char))
    return chars


def _hangul_count(text: str) -> int:
    return sum(1 for char in text if "\uac00" <= char <= "\ud7a3")


def _line_should_use_char_layout(line: dict[str, Any]) -> bool:
    text = _line_text(line)
    if not text:
        return False
    chars = _line_chars(line)
    if not chars:
        return False
    normalized = math_text.normalize_recognized_math_text(text)
    compact_len = max(1, len(normalized.replace(" ", "")))
    if _hangul_count(normalized) / compact_len > 0.30:
        return False
    has_fraction_rule = any(str(char.get("c") or "") == _HANCOM_FRACTION_RULE_CHAR for _span, char in chars)
    has_pua = any(0xE000 <= ord(str(char.get("c") or "\0")[0]) <= 0xF8FF for _span, char in chars)
    has_math_font = any(_span_uses_math_font(span) for span, _char in chars)
    if has_fraction_rule:
        return True
    return (has_pua or has_math_font) and _line_has_math_visual_risk(line)


def _line_has_choice_marker(line: dict[str, Any]) -> bool:
    text = math_text.normalize_recognized_math_text(_line_text(line))
    if any("\u2460" <= char <= "\u2473" for char in text):
        return True
    return any(char in _CIRCLED_CHOICE_CHARS for char in text)


def _line_is_math_ai_candidate(line: dict[str, Any]) -> bool:
    if not _line_should_use_char_layout(line) or _line_has_choice_marker(line):
        return False
    if not any(str(char.get("c") or "") == _HANCOM_FRACTION_RULE_CHAR for _span, char in _line_chars(line)):
        return False
    text = math_text.normalize_recognized_math_text(_line_text(line))
    compact_len = max(1, len(text.replace(" ", "")))
    if _hangul_count(text) / compact_len > 0.20:
        return False
    return True


def _math_ai_line_group(lines: list[dict[str, Any]], start_index: int) -> tuple[list[dict[str, Any]], int]:
    first = lines[start_index]
    group = [first]
    group_bbox = fitz.Rect(first["bbox"])
    index = start_index + 1
    while index < len(lines) and _line_is_math_ai_candidate(lines[index]):
        rect = fitz.Rect(lines[index]["bbox"])
        max_height = max(group_bbox.height, rect.height, 1.0)
        vertical_gap = max(0.0, rect.y0 - group_bbox.y1, group_bbox.y0 - rect.y1)
        x_overlap = min(group_bbox.x1, rect.x1) - max(group_bbox.x0, rect.x0)
        if vertical_gap > max(5.0, max_height * 0.85):
            break
        if x_overlap < -max(10.0, max_height):
            break
        group.append(lines[index])
        group_bbox.include_rect(rect)
        index += 1
    return group, index


def _math_ai_group_rect(lines: list[dict[str, Any]]) -> fitz.Rect:
    return _union_rect([fitz.Rect(line["bbox"]) for line in lines])


def _math_ai_text_hint(lines: list[dict[str, Any]]) -> str:
    raw = "\n".join(_line_text(line) for line in lines if _line_text(line))
    return math_text.normalize_recognized_math_layout_text(raw)


def _math_ai_token_hints(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for line in lines:
        for _span, char in _line_chars(line):
            raw = str(char.get("c") or "")
            normalized = math_text.normalize_recognized_math_text(raw)
            if not normalized:
                continue
            rect = fitz.Rect(char.get("bbox") or (0, 0, 0, 0))
            if rect.is_empty:
                continue
            hints.append(
                {
                    "text": normalized,
                    "x": float(rect.x0),
                    "y": float(rect.y0),
                    "w": float(rect.width),
                    "h": float(rect.height),
                }
            )
            if len(hints) >= 100:
                return hints
    return hints


def _math_ai_result_insertable(lines: list[dict[str, Any]], result: pdf_math_ai.MathAIRecognition) -> bool:
    if not result.accepted:
        return False
    if not (result.hancom_eqn or result.latex or result.plain_text).strip():
        return False
    return any(line.get("spans") for line in lines)


def _recognize_math_ai_page_groups(
    page: fitz.Page,
    lines: list[dict[str, Any]],
    *,
    enabled: bool,
    model: str,
    remaining_calls: int,
) -> tuple[
    dict[int, tuple[list[dict[str, Any]], int, pdf_math_ai.MathAIRecognition]],
    list[fitz.Rect],
    int,
    dict[str, Any],
]:
    recognized: dict[int, tuple[list[dict[str, Any]], int, pdf_math_ai.MathAIRecognition]] = {}
    accepted_rects: list[fitz.Rect] = []
    stats: dict[str, Any] = {"attempts": 0, "skipped": 0, "errors": 0, "rejected": 0, "last_error": ""}
    if not enabled or remaining_calls <= 0:
        return recognized, accepted_rects, remaining_calls, stats

    index = 0
    while index < len(lines) and remaining_calls > 0:
        line = lines[index]
        if not _line_is_math_ai_candidate(line):
            index += 1
            continue
        group_lines, next_index = _math_ai_line_group(lines, index)
        stats["attempts"] += 1
        remaining_calls -= 1
        source_rect = _math_ai_group_rect(group_lines)
        result = pdf_math_ai.recognize_math_crop(
            page,
            source_rect,
            model=model,
            text_hint=_math_ai_text_hint(group_lines),
            token_hints=_math_ai_token_hints(group_lines),
        )
        if _math_ai_result_insertable(group_lines, result):
            recognized[index] = (group_lines, next_index, result)
            accepted_rects.append(source_rect)
        elif result.status == "skipped":
            stats["skipped"] += 1
        elif result.status == "error":
            stats["errors"] += 1
            stats["last_error"] = pdf_math_ai.redact_error(str(result.error or ""))[:500]
        else:
            stats["rejected"] += 1
            stats["last_error"] = pdf_math_ai.redact_error(str(result.error or result.notes or ""))[:500]
        index = next_index
    return recognized, accepted_rects, remaining_calls, stats


def _add_math_ai_group_equation(
    doc: HwpxDocument,
    anchor: Any,
    page: fitz.Page,
    lines: list[dict[str, Any]],
    *,
    styles: dict[tuple[str, float, bool], str],
    para_pr_id_ref: str,
    z_counter: list[int],
    page_transform: _PageTransform,
    equation_counter: list[int],
    model: str,
) -> tuple[bool, pdf_math_ai.MathAIRecognition]:
    source_rect = _math_ai_group_rect(lines)
    result = pdf_math_ai.recognize_math_crop(
        page,
        source_rect,
        model=model,
        text_hint=_math_ai_text_hint(lines),
        token_hints=_math_ai_token_hints(lines),
    )
    return _add_math_ai_recognition_equation(
        doc,
        anchor,
        lines,
        result,
        styles=styles,
        para_pr_id_ref=para_pr_id_ref,
        z_counter=z_counter,
        page_transform=page_transform,
        equation_counter=equation_counter,
    )


def _add_math_ai_recognition_equation(
    doc: HwpxDocument,
    anchor: Any,
    lines: list[dict[str, Any]],
    result: pdf_math_ai.MathAIRecognition,
    *,
    styles: dict[tuple[str, float, bool], str],
    para_pr_id_ref: str,
    z_counter: list[int],
    page_transform: _PageTransform,
    equation_counter: list[int],
) -> tuple[bool, pdf_math_ai.MathAIRecognition]:
    if not result.accepted:
        return False, result
    script = result.hancom_eqn or result.latex or result.plain_text
    if not script.strip():
        result.status = "rejected"
        result.error = result.error or "empty_math_script"
        return False, result
    target = page_transform.rect(_math_ai_group_rect(lines))
    first_span = next((span for line in lines for span in line.get("spans", [])), None)
    if first_span is None:
        result.status = "rejected"
        result.error = result.error or "missing_span_style"
        return False, result
    char_pr = _ensure_char_pr(doc, styles, first_span)
    inserted = _add_positioned_equation(
        anchor,
        x_pt=max(0.0, target.x0 - 1.5),
        y_pt=max(0.0, target.y0 - 2.0),
        width_pt=max(4.0, target.width + 4.0),
        height_pt=max(4.0, target.height + 4.0),
        script=script,
        char_pr_id_ref=char_pr,
        z_order=_next_z(z_counter),
        equation_counter=equation_counter,
    )
    if not inserted:
        result.status = "rejected"
        result.error = result.error or "equation_insert_failed"
        return False, result
    return True, result


def _add_positioned_native_math_for_line(
    doc: HwpxDocument,
    anchor: Any,
    line: dict[str, Any],
    *,
    styles: dict[tuple[str, float, bool], str],
    z_counter: list[int],
    page_transform: _PageTransform,
    equation_counter: list[int],
) -> tuple[int, int]:
    """Add editable equations outside drawText, underneath the visual layer."""
    raw_text = _line_text(line)
    normalized = math_text.normalize_recognized_math_text(raw_text)
    math_spans = math_text.extract_math_spans(normalized)
    if not math_spans:
        return 0, 0
    line_spans = list(line.get("spans") or [])
    first_span = next(
        (span for span in line_spans if str(span.get("text") or "").strip()),
        None,
    )
    if first_span is None:
        return 0, len(math_spans)
    source_box = fitz.Rect(line.get("bbox") or (0, 0, 0, 0))
    if source_box.width <= 0 or source_box.height <= 0:
        return 0, len(math_spans)
    target_box = page_transform.rect(source_box)
    char_pr = _ensure_char_pr(doc, styles, first_span)
    text_length = max(1, len(normalized))
    inserted = 0
    for math_span in math_spans:
        token = str(math_span.normalized or math_span.text or "").strip()
        if not token or any(char in token for char in _MATH_VISUAL_PLACEHOLDER_CHARS):
            continue
        script = _hancom_eqn_script(token)
        if not script:
            continue
        left_ratio = max(0.0, min(1.0, float(math_span.start) / text_length))
        width_ratio = max(
            0.04,
            min(1.0 - left_ratio, float(max(1, math_span.end - math_span.start)) / text_length),
        )
        x_pt = target_box.x0 + target_box.width * left_ratio
        width_pt = max(4.0, target_box.width * width_ratio + 4.0)
        if _add_positioned_equation_table(
            doc,
            anchor,
            x_pt=max(0.0, x_pt - 1.5),
            y_pt=max(0.0, target_box.y0 - 2.0),
            width_pt=width_pt,
            height_pt=max(4.0, target_box.height + 4.0),
            script=script,
            char_pr_id_ref=char_pr,
            z_order=_next_z(z_counter),
            equation_counter=equation_counter,
        ):
            inserted += 1
    return inserted, len(math_spans)


def _add_char_layout_text_boxes(
    doc: HwpxDocument,
    anchor: Any,
    line: dict[str, Any],
    *,
    styles: dict[tuple[str, float, bool], str],
    para_pr_id_ref: str,
    z_counter: list[int],
    page_transform: _PageTransform,
    equation_counter: list[int] | None = None,
    native_math: bool = False,
) -> dict[str, int]:
    stats = {"native_equations": 0, "source_math_segments": 0, "text_items": 0}
    for span, char in _line_chars(line):
        raw = str(char.get("c") or "")
        text = _pdf_output_text(raw)
        if text == "" or text.isspace():
            continue
        rect = fitz.Rect(char.get("bbox") or span.get("bbox") or line.get("bbox"))
        if rect.width <= 0 or rect.height <= 0:
            continue
        bbox = page_transform.rect(rect)
        char_pr = _ensure_char_pr(doc, styles, span)
        pad_x = max(0.6, min(1.6, bbox.height * 0.12))
        pad_y = max(0.8, min(2.0, bbox.height * 0.12))
        width_pt = max(2.0, bbox.width + pad_x * 2)
        height_pt = max(2.0, bbox.height + pad_y * 2)
        run_stats = _add_text_box_runs(
            doc,
            anchor,
            x_pt=max(0.0, bbox.x0 - pad_x * 0.45),
            y_pt=max(0.0, bbox.y0 - pad_y * 0.70),
            width_pt=width_pt,
            height_pt=height_pt,
            runs=[(text, char_pr)],
            para_pr_id_ref=para_pr_id_ref,
            z_order=_next_z(z_counter),
            equation_counter=equation_counter,
            native_math=native_math,
        )
        stats["native_equations"] += int(run_stats.get("native_equations") or 0)
        stats["source_math_segments"] += int(run_stats.get("source_math_segments") or 0)
        stats["text_items"] += 1
    return stats


def _median_float(values: list[float], default: float = 0.0) -> float:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return default
    return float(statistics.median(clean))


def _line_median_font_size(line: dict[str, Any], default: float = 10.0) -> float:
    return _median_float([_span_size(span, default) for span in line.get("spans", [])], default)


def _flow_box_line_spacing_percent(lines: list[dict[str, Any]]) -> int:
    ordered = sorted(lines, key=lambda item: (fitz.Rect(item["bbox"]).y0, fitz.Rect(item["bbox"]).x0))
    if len(ordered) < 2:
        return 130
    gaps: list[float] = []
    for previous, current in zip(ordered, ordered[1:]):
        prev_box = fitz.Rect(previous["bbox"])
        cur_box = fitz.Rect(current["bbox"])
        gap = cur_box.y0 - prev_box.y0
        if 4.0 <= gap <= 28.0:
            gaps.append(gap)
    median_size = _median_float([_line_median_font_size(line) for line in ordered], 10.0)
    if not gaps or median_size <= 0:
        return 130
    percent = int(round((_median_float(gaps, median_size * 1.3) / median_size) * 100.0))
    return max(_FLOW_BOX_MIN_LINE_SPACING, min(_FLOW_BOX_MAX_LINE_SPACING, percent))


def _flow_box_padding_pt(rect: fitz.Rect, lines: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    if not lines:
        return (2.0, 2.0, 1.6, 1.6)
    line_boxes = [fitz.Rect(line["bbox"]) for line in lines]
    left = min(box.x0 for box in line_boxes) - rect.x0
    right = rect.x1 - max(box.x1 for box in line_boxes)
    top = min(box.y0 for box in line_boxes) - rect.y0
    bottom = rect.y1 - max(box.y1 for box in line_boxes)

    def clamp(value: float, fallback: float) -> float:
        if value < 0:
            value = fallback
        return max(_FLOW_BOX_MIN_PADDING_PT, min(_FLOW_BOX_MAX_PADDING_PT, value))

    return (
        clamp(left, 2.0),
        clamp(right, 2.0),
        clamp(top, 1.6),
        clamp(bottom, 1.6),
    )


def _flow_box_line_alignment(
    line: dict[str, Any],
    rect: fitz.Rect,
    padding: tuple[float, float, float, float],
) -> str:
    bbox = fitz.Rect(line["bbox"])
    pad_left, pad_right, _pad_top, _pad_bottom = padding
    inner_left = rect.x0 + pad_left
    inner_right = rect.x1 - pad_right
    inner_width = max(1.0, inner_right - inner_left)
    line_width = max(1.0, bbox.width)
    left_gap = bbox.x0 - inner_left
    right_gap = inner_right - bbox.x1
    center_delta = abs(((bbox.x0 + bbox.x1) / 2.0) - ((inner_left + inner_right) / 2.0))
    if line_width <= inner_width * 0.72 and center_delta <= max(4.0, inner_width * 0.08):
        return "CENTER"
    if left_gap >= max(10.0, inner_width * 0.18) and right_gap <= max(5.0, inner_width * 0.05):
        return "RIGHT"
    return "LEFT"


def _flow_box_line_indent_hwp(
    line: dict[str, Any],
    rect: fitz.Rect,
    padding: tuple[float, float, float, float],
    alignment: str,
    coordinate_scale: float = 1.0,
) -> int:
    if alignment != "LEFT":
        return 0
    bbox = fitz.Rect(line["bbox"])
    pad_left, _pad_right, _pad_top, _pad_bottom = padding
    indent_pt = bbox.x0 - (rect.x0 + pad_left)
    if indent_pt <= 1.0:
        return 0
    return _pt_to_hwp(min(36.0, indent_pt) * coordinate_scale)


def _flow_line_layout_hwp(
    block: dict[str, Any],
    line: dict[str, Any],
    *,
    cell_width: int,
    coordinate_scale: float,
) -> tuple[str, int]:
    bbox = _item_bbox(line)
    column_left = float(block.get("column_left_pt") or bbox.x0)
    column_right = float(block.get("column_right_pt") or bbox.x1)
    column_width = max(1.0, column_right - column_left)
    line_width = max(1.0, bbox.width)
    line_center = (bbox.x0 + bbox.x1) / 2.0
    column_center = (column_left + column_right) / 2.0
    if (
        line_width <= column_width * 0.76
        and abs(line_center - column_center) <= max(4.0, column_width * 0.075)
    ):
        return "CENTER", 0
    if (
        bbox.x0 - column_left >= max(10.0, column_width * 0.18)
        and column_right - bbox.x1 <= max(5.0, column_width * 0.05)
    ):
        return "RIGHT", 0
    desired_indent = _pt_to_hwp(max(0.0, bbox.x0 - column_left) * coordinate_scale)
    rendered_line_width = _pt_to_hwp(line_width * coordinate_scale)
    maximum_indent = max(
        0,
        cell_width - rendered_line_width - _pt_to_hwp(4.0 * coordinate_scale),
    )
    return "LEFT", min(desired_indent, maximum_indent)


_FLOW_NON_PROSE_START_RE = re.compile(
    r"^\s*(?:"
    r"\d{1,3}[.)]|"
    r"[①②③④⑤⑥⑦⑧⑨⑩]|[㉠-㉿]|"
    r"[•∙·●○■□▪▫‣⁃]|"
    r"(?:보기|참고|자료|조건|주석|Note|Notes?)\s*[:：]|"
    r"<\s*보\s*기\s*>|"
    r"\[[^]]{1,12}\]|\([^)]{1,10}\)|"
    r"[가-힣A-Z]\s*[.)]"
    r")",
    re.IGNORECASE,
)


def _flow_prose_candidate(line: dict[str, Any], *, column_width: float) -> bool:
    """Return whether a source line belongs to reflowable body prose.

    Question numbers, answer choices, short labels and formula-heavy lines must
    remain independent.  Long Korean/English body lines can be joined into one
    semantic paragraph so Hancom can perform real bilateral justification.
    """
    text = _line_text(line).strip()
    if not text or _FLOW_NON_PROSE_START_RE.match(text):
        return False
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 14:
        return False
    bbox = _item_bbox(line)
    if bbox.width < max(72.0, column_width * 0.43) and len(compact) < 28:
        return False
    math_marks = len(re.findall(r"[=+×÷∑∫√∞<>≤≥{}_^]", text))
    if math_marks >= 2 and math_marks / max(1, len(compact)) >= 0.08:
        return False
    return True


def _flow_paragraph_line_spacing_percent(
    lines: list[dict[str, Any]],
    *,
    coordinate_scale: float,
    font_scale: float,
    fallback: int,
) -> int:
    if len(lines) < 2:
        return fallback
    ordered = sorted(lines, key=lambda item: _item_bbox(item).y0)
    baselines = [
        _median_float(
            [float(span.get("origin", (0.0, _item_bbox(line).y1))[1]) for span in line.get("spans", [])],
            _item_bbox(line).y1,
        )
        for line in ordered
    ]
    gaps = [
        current - previous
        for previous, current in zip(baselines, baselines[1:])
        if 5.0 <= current - previous <= 34.0
    ]
    if not gaps:
        return fallback
    rendered_sizes = [
        _flow_size_for_span(span) * font_scale
        for line in ordered
        for span in line.get("spans", [])
        if str(span.get("text") or "").strip()
    ]
    rendered_size = _median_float(rendered_sizes, 8.0 * font_scale)
    if rendered_size <= 0:
        return fallback
    percent = int(round(_median_float(gaps, 0.0) * coordinate_scale / rendered_size * 100.0))
    return max(115, min(190, percent))


def _flow_paragraph_geometry_hwp(
    lines: list[dict[str, Any]],
    *,
    column_left: float,
    cell_width: int,
    coordinate_scale: float,
) -> tuple[int, int]:
    if not lines:
        return 0, 0
    lefts = [float(_item_bbox(line).x0) for line in lines]
    continuation_left = _median_float(lefts[1:], min(lefts)) if len(lefts) > 1 else lefts[0]
    paragraph_left = min(continuation_left, min(lefts))
    left_margin = _pt_to_hwp(max(0.0, paragraph_left - column_left) * coordinate_scale)
    left_margin = min(left_margin, max(0, cell_width - _pt_to_hwp(48.0)))
    intent = _pt_to_hwp((lefts[0] - continuation_left) * coordinate_scale)
    # Large differences usually indicate a label or quotation layout rather
    # than a first-line indent.  Keep semantic indents within a normal range.
    intent = max(_pt_to_hwp(-6.0), min(_pt_to_hwp(18.0), intent))
    return left_margin, intent


def _group_flow_prose_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge consecutive visual lines into editable, justified paragraphs."""
    grouped: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal active
        if len(active) >= 2:
            first = active[0]
            grouped.append(
                {
                    "type": "paragraph",
                    "lines": [item["line"] for item in active],
                    "column_left_pt": first.get("column_left_pt"),
                    "column_right_pt": first.get("column_right_pt"),
                    "before_gap_pt": first.get("before_gap_pt", 0.0),
                }
            )
        else:
            grouped.extend(active)
        active = []

    for block in blocks:
        if block.get("type") != "line":
            flush()
            grouped.append(block)
            continue
        line = block["line"]
        column_left = float(block.get("column_left_pt") or _item_bbox(line).x0)
        column_right = float(block.get("column_right_pt") or _item_bbox(line).x1)
        column_width = max(1.0, column_right - column_left)
        if not _flow_prose_candidate(line, column_width=column_width):
            flush()
            grouped.append(block)
            continue
        if active:
            previous = active[-1]["line"]
            previous_bbox = _item_bbox(previous)
            current_bbox = _item_bbox(line)
            baseline_gap = current_bbox.y0 - previous_bbox.y0
            paragraph_break = (
                baseline_gap > max(27.0, _line_median_font_size(line) * 2.15)
                or (
                    current_bbox.x0 - column_left >= 8.0
                    and _line_text(previous).rstrip().endswith((".", "?", "!", "다.", "함."))
                )
            )
            if paragraph_break:
                flush()
        active.append(block)
    flush()
    return grouped


def _expose_para_margin(header: Any, para_pr_id: str) -> None:
    """Mirror a paragraph's margins onto the documented ``hh:paraPr/hh:margin``.

    ``HwpxDocument.new()`` resolves its skeleton at runtime: when the vendored
    package ships ``hwpx/data/Skeleton.hwpx`` the base paragraph property keeps
    ``margin``/``lineSpacing`` inside an ``hp:switch`` alternative-content block
    whose values live in the ``hc`` namespace, and every format derived from it
    inherits that shape.  Without that asset the generated fallback skeleton is
    used and the same call emits a plain ``hh:margin`` child instead.  The flow
    writer must not publish two different paragraph-geometry layouts depending
    on which skeleton happened to be installed, so copy the resolved values to
    the direct ``hh:margin`` child that readers and the layout QA tooling look
    at.  The ``hp:switch`` block is deliberately left untouched: it carries the
    same numbers, so whichever representation a reader honours agrees.
    """

    para_pr = header.element.find(f".//{_hh('paraPr')}[@id='{para_pr_id}']")
    if para_pr is None or para_pr.find(_hh("margin")) is not None:
        return
    source = para_pr.find(f".//{_hh('margin')}")
    if source is None:
        return
    mirror = para_pr.makeelement(_hh("margin"), {})
    for child in source:
        local_name = etree.QName(child).localname
        value = child.get("value")
        if value is None:
            value = (child.text or "").strip() or "0"
        attributes = {"value": str(value), "unit": child.get("unit") or "HWPUNIT"}
        _append_xml_child(mirror, _hh(local_name), attributes)
    para_pr.append(mirror)
    header.mark_dirty()


def _ensure_flow_para_format(
    doc: HwpxDocument,
    para_styles: dict[tuple[Any, ...], str],
    *,
    alignment: str,
    line_spacing_percent: int,
    left_margin_hwp: int = 0,
    prev_margin_hwp: int = 0,
    first_line_indent_hwp: int = 0,
    next_margin_hwp: int = 0,
) -> str:
    safe_spacing = max(80, min(200, int(line_spacing_percent)))
    safe_left = max(0, int(left_margin_hwp))
    safe_prev = max(0, int(prev_margin_hwp))
    safe_intent = int(first_line_indent_hwp)
    safe_next = max(0, int(next_margin_hwp))
    key = (
        alignment.upper(),
        safe_spacing,
        safe_left,
        safe_prev,
        safe_intent,
        safe_next,
    )
    para_pr_id = para_styles.get(key)
    if para_pr_id is None:
        header = doc.headers[0]
        para_pr_id = header.ensure_paragraph_format(
            alignment=alignment,
            line_spacing_percent=safe_spacing,
            margins={
                "left": safe_left,
                "prev": safe_prev,
                "next": safe_next,
                "intent": safe_intent,
            },
        )
        _expose_para_margin(header, para_pr_id)
        para_styles[key] = para_pr_id
    return para_pr_id


def _flow_box_host_indent_hwp(
    block: dict[str, Any], cell_width: int, coordinate_scale: float = 1.0
) -> int:
    rect = block.get("rect")
    if rect is None:
        return 0
    column_left = float(block.get("column_left_pt") or rect.x0)
    indent_pt = max(0.0, float(rect.x0) - column_left)
    indent_hwp = _pt_to_hwp(min(36.0, indent_pt) * coordinate_scale)
    return max(0, min(indent_hwp, max(0, cell_width - _pt_to_hwp(48.0))))


def _flow_box_table_width_hwp(
    block: dict[str, Any],
    lines: list[dict[str, Any]],
    cell_width: int,
    indent_hwp: int,
    coordinate_scale: float = 1.0,
) -> int:
    rect = block.get("rect")
    if rect is None:
        line_bounds = _union_rect([fitz.Rect(line["bbox"]) for line in lines])
        desired_pt = line_bounds.width + 6.0
    else:
        desired_pt = max(24.0, float(rect.width))
    max_width = max(1, cell_width - indent_hwp - _pt_to_hwp(2.0))
    return max(1, min(max_width, _pt_to_hwp(desired_pt * coordinate_scale)))


def _flow_box_table_height_hwp(
    block: dict[str, Any], lines: list[dict[str, Any]], coordinate_scale: float = 1.0
) -> int:
    rect = block.get("rect")
    if rect is not None:
        return max(
            _pt_to_hwp(12.0 * coordinate_scale),
            _pt_to_hwp(float(rect.height) * coordinate_scale),
        )
    line_height = sum(max(8.0, fitz.Rect(line["bbox"]).height + 1.5) for line in lines)
    return max(
        _pt_to_hwp(12.0 * coordinate_scale),
        _pt_to_hwp(line_height * coordinate_scale),
    )


def _flow_box_trailing_balance_hwp(
    lines: list[dict[str, Any]],
    *,
    table_height_hwp: int,
    padding: tuple[float, float, float, float],
    line_spacing_percent: int,
    coordinate_scale: float,
    font_scale: float,
) -> int:
    if len(lines) < 2:
        return 0
    box_text = " ".join(_line_text(line) for line in lines)
    if _latin_ratio(box_text) >= 0.45:
        return 0
    line_boxes = [fitz.Rect(line["bbox"]) for line in lines]
    source_text_height = (
        max(box.y1 for box in line_boxes) - min(box.y0 for box in line_boxes)
    ) * coordinate_scale
    estimated_flow_height = sum(
        max(
            1.0,
            max(
                (_flow_size_for_span(span) * font_scale for span in line.get("spans", [])),
                default=8.0 * font_scale,
            ),
        )
        * line_spacing_percent
        / 100.0
        for line in lines
    )
    _pad_left, _pad_right, pad_top, pad_bottom = padding
    balance_pt = (
        source_text_height
        - estimated_flow_height
        + (pad_bottom - pad_top) * coordinate_scale
    )
    table_height_pt = max(0.0, table_height_hwp / HWP_PER_PT)
    inner_height_pt = max(
        0.0,
        table_height_pt - (pad_top + pad_bottom) * coordinate_scale,
    )
    maximum_balance_pt = max(0.0, inner_height_pt - estimated_flow_height - 1.0)
    balance_pt = min(
        max(0.0, balance_pt),
        maximum_balance_pt,
        table_height_pt * 0.35,
    )
    return _pt_to_hwp(balance_pt) if balance_pt >= 1.0 else 0


def _flow_effective_item_bbox(item: dict[str, Any], boxes: list[fitz.Rect]) -> fitz.Rect:
    bbox = _item_bbox(item)
    if item.get("type") != "image":
        box_index = _box_for_line(item, boxes)
        if box_index is not None:
            return boxes[box_index]
    return bbox


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
            {"left": "0", "right": "0", "top": "0", "bottom": "0"},
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
        if borders and all(
            border is not None
            and (
                (border.get("type") or "").upper() == "NONE"
                or (
                    (border.get("type") or "").upper() == "SOLID"
                    and (border.get("color") or "").upper() == "#FFFFFF"
                )
            )
            for border in borders
        ):
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
        ("leftBorder", {"type": "SOLID", "width": "0.1 mm", "color": "#FFFFFF"}),
        ("rightBorder", {"type": "SOLID", "width": "0.1 mm", "color": "#FFFFFF"}),
        ("topBorder", {"type": "SOLID", "width": "0.1 mm", "color": "#FFFFFF"}),
        ("bottomBorder", {"type": "SOLID", "width": "0.1 mm", "color": "#FFFFFF"}),
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
    text_length = 0
    for name in _section_names_from_payloads(payloads):
        try:
            section = etree.fromstring(payloads[name])
        except Exception:
            continue
        for node in section.findall(f".//{_q('t')}"):
            if node.text:
                texts.append(node.text)
                text_length += len(node.text)
                if text_length >= limit:
                    break
        if text_length >= limit:
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
        changed = _ensure_table_cell_paragraph_shells(section) or changed
        changed = _patch_text_box_paragraphs(section) or changed
        changed = _patch_flow_multiline_linesegs(section) or changed
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

    existing_preview = payloads.get("Preview/PrvText.txt")
    if existing_preview is None or not existing_preview.strip():
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


def _ensure_table_cell_paragraph_shells(section: Any) -> bool:
    """Keep empty table cells valid for Hancom's native HWPX loader."""
    changed = False
    for cell in section.findall(f".//{_q('tc')}"):
        sublist = cell.find(_q("subList"))
        if sublist is None:
            sublist = etree.SubElement(
                cell,
                _q("subList"),
                {
                    "id": "0",
                    "textDirection": "HORIZONTAL",
                    "lineWrap": "BREAK",
                    "vertAlign": "TOP",
                    "linkListIDRef": "0",
                    "linkListNextIDRef": "0",
                    "textWidth": "0",
                    "textHeight": "0",
                    "hasTextRef": "0",
                    "hasNumRef": "0",
                },
            )
            changed = True
        paragraphs = list(sublist.findall(_q("p")))
        if not paragraphs:
            paragraph = etree.SubElement(
                sublist,
                _q("p"),
                {
                    "id": _paragraph_id(),
                    "paraPrIDRef": "0",
                    "styleIDRef": "0",
                    "pageBreak": "0",
                    "columnBreak": "0",
                    "merged": "0",
                },
            )
            run = etree.SubElement(paragraph, _q("run"), {"charPrIDRef": "0"})
            etree.SubElement(run, _q("t"))
            paragraphs = [paragraph]
            changed = True

        cell_size = cell.find(_q("cellSz"))
        cell_width = _positive_int(cell_size.get("width")) if cell_size is not None else None
        cell_height = _positive_int(cell_size.get("height")) if cell_size is not None else None

        def is_pure_empty_paragraph(paragraph: Any) -> bool:
            if any(str(node.text or "").strip() for node in paragraph.findall(f".//{_q('t')}")):
                return False
            for run in paragraph.findall(_q("run")):
                if any(child.tag != _q("t") for child in run):
                    return False
            return True

        if paragraphs and all(is_pure_empty_paragraph(paragraph) for paragraph in paragraphs):
            line_height = min(1000, max(1, (cell_height or 1000) // len(paragraphs)))
            for paragraph in paragraphs:
                lineseg = paragraph.find(f"{_q('linesegarray')}/{_q('lineseg')}")
                if lineseg is None:
                    _append_text_box_lineseg_hwp(paragraph, cell_width or 1, line_height)
                    changed = True
                    continue
                desired = {
                    "vertsize": str(line_height),
                    "textheight": str(line_height),
                    "baseline": str(max(1, int(line_height * 0.85))),
                    "spacing": str(max(0, int(line_height * 0.15))),
                    "horzsize": str(cell_width or 1),
                }
                for attr, value in desired.items():
                    if lineseg.get(attr) != value:
                        lineseg.set(attr, value)
                        changed = True
    return changed


def _direct_native_equation_height(paragraph: Any) -> int:
    heights: list[int] = []
    for equation in paragraph.findall(f"{_q('run')}/{_q('equation')}"):
        script = equation.find(_q("script"))
        value = str(script.text or "").strip() if script is not None else ""
        if value:
            heights.append(_equation_size(value)[1])
    return max(heights, default=0)


def _patch_flow_multiline_linesegs(section: Any) -> bool:
    changed = False
    for paragraph in section.findall(f".//{_q('p')}"):
        raw_count = paragraph.attrib.pop("dataFlowLineCount", None)
        raw_positions = paragraph.attrib.pop("dataFlowLinePositions", None)
        raw_width = paragraph.attrib.pop("dataFlowLineWidth", None)
        raw_height = paragraph.attrib.pop("dataFlowLineHeight", None)
        if raw_count is None:
            continue
        try:
            count = max(1, int(raw_count))
            width = max(1, int(raw_width or _section_text_width(section)))
            line_height = max(1, int(raw_height or 1000))
            positions = [max(0, int(value)) for value in str(raw_positions or "0").split(",")]
        except (TypeError, ValueError):
            count, width, line_height, positions = 1, _section_text_width(section), 1000, [0]
        if len(positions) < count:
            text = "".join(str(node.text or "") for node in paragraph.findall(f".//{_q('t')}"))
            step = max(1, len(text) // count)
            positions = [index * step for index in range(count)]
        for existing in list(paragraph.findall(_q("linesegarray"))):
            paragraph.remove(existing)
        array = etree.SubElement(paragraph, _q("linesegarray"))
        for index in range(count):
            etree.SubElement(
                array,
                _q("lineseg"),
                {
                    "textpos": str(positions[index]),
                    "vertpos": str(index * line_height),
                    "vertsize": str(line_height),
                    "textheight": str(line_height),
                    "baseline": str(max(1, int(line_height * 0.85))),
                    "spacing": str(max(0, int(line_height * 0.15))),
                    "horzpos": "0",
                    "horzsize": str(width),
                    "flags": "393216",
                },
            )
        changed = True
    return changed


def _patch_section_paragraph_linesegs(section: Any) -> bool:
    changed = False
    width = _section_text_width(section)
    for paragraph in section.findall(f".//{_q('p')}"):
        if not paragraph.get("id"):
            paragraph.set("id", _paragraph_id())
            changed = True
        equation_height = _direct_native_equation_height(paragraph)
        height = max(1000, equation_height)
        lineseg = paragraph.find(f"{_q('linesegarray')}/{_q('lineseg')}")
        if lineseg is None:
            _append_text_box_lineseg_hwp(paragraph, width, height)
            changed = True
        elif equation_height and (_positive_int(lineseg.get("vertsize")) or 0) < height:
            lineseg.set("vertsize", str(height))
            lineseg.set("textheight", str(height))
            lineseg.set("baseline", str(int(height * 0.85)))
            lineseg.set("spacing", str(int(height * 0.15)))
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
        if children and all(
            (child.get("type") or "").upper() == "NONE"
            or (
                (child.get("type") or "").upper() == "SOLID"
                and (child.get("color") or "").upper() == "#FFFFFF"
            )
            for child in children
        ):
            for child in children:
                if etree.QName(child).localname == "diagonal":
                    child.set("type", "NONE")
                    child.set("width", "0.0 mm")
                    child.set("color", "#FFFFFF")
                else:
                    child.set("type", "SOLID")
                    child.set("width", "0.1 mm")
                    child.set("color", "#FFFFFF")
            header.mark_dirty()
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
        ("leftBorder", {"type": "SOLID", "width": "0.1 mm", "color": "#FFFFFF"}),
        ("rightBorder", {"type": "SOLID", "width": "0.1 mm", "color": "#FFFFFF"}),
        ("topBorder", {"type": "SOLID", "width": "0.1 mm", "color": "#FFFFFF"}),
        ("bottomBorder", {"type": "SOLID", "width": "0.1 mm", "color": "#FFFFFF"}),
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
        if all(border is not None and border.get("type") == "SOLID" and border.get("width") == "0.20 mm" for border in borders):
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
        ("leftBorder", {"type": "SOLID", "width": "0.20 mm", "color": "#000000"}),
        ("rightBorder", {"type": "SOLID", "width": "0.20 mm", "color": "#000000"}),
        ("topBorder", {"type": "SOLID", "width": "0.20 mm", "color": "#000000"}),
        ("bottomBorder", {"type": "SOLID", "width": "0.20 mm", "color": "#000000"}),
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
            and right.get("width") == "0.20 mm"
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
        ("rightBorder", {"type": "SOLID", "width": "0.20 mm", "color": "#000000"}),
        ("topBorder", {"type": "NONE", "width": "0.0 mm", "color": "#FFFFFF"}),
        ("bottomBorder", {"type": "NONE", "width": "0.0 mm", "color": "#FFFFFF"}),
        ("diagonal", {"type": "NONE", "width": "0.0 mm", "color": "#FFFFFF"}),
    ):
        element.append(element.makeelement(_hh(child_name), attrs))
    border_fills.append(element)
    border_fills.set("itemCnt", str(len(border_fills.findall(_hh("borderFill")))))
    header.mark_dirty()
    return str(next_id)


def _ensure_header_divider_border_fill(header: Any) -> str:
    border_fills = header.element.find(f".//{_hh('borderFills')}")
    if border_fills is None:
        ref_list = header.element.find(f".//{_hh('refList')}")
        if ref_list is None:
            return _ensure_no_border_fill(header)
        border_fills = ref_list.makeelement(_hh("borderFills"), {"itemCnt": "0"})
        ref_list.append(border_fills)
    for border_fill in border_fills.findall(_hh("borderFill")):
        borders = {
            name: border_fill.find(_hh(name))
            for name in ("leftBorder", "rightBorder", "topBorder", "bottomBorder")
        }
        bottom = borders["bottomBorder"]
        if (
            bottom is not None
            and bottom.get("type") == "SOLID"
            and bottom.get("width") == "0.20 mm"
            and all(
                borders[name] is not None
                and (borders[name].get("type") or "").upper() == "NONE"
                for name in ("leftBorder", "rightBorder", "topBorder")
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
        ("rightBorder", {"type": "NONE", "width": "0.0 mm", "color": "#FFFFFF"}),
        ("topBorder", {"type": "NONE", "width": "0.0 mm", "color": "#FFFFFF"}),
        ("bottomBorder", {"type": "SOLID", "width": "0.20 mm", "color": "#000000"}),
        ("diagonal", {"type": "NONE", "width": "0.0 mm", "color": "#FFFFFF"}),
    ):
        element.append(element.makeelement(_hh(child_name), attrs))
    border_fills.append(element)
    border_fills.set("itemCnt", str(len(border_fills.findall(_hh("borderFill")))))
    header.mark_dirty()
    return str(next_id)


def _append_multiline_linesegs_hwp(
    paragraph: Any,
    lines: list[dict[str, Any]],
    *,
    width: int,
    line_height: int,
) -> None:
    """Describe every source line so compatibility patching does not clip it."""
    if not lines:
        return
    line_seg_array = etree.SubElement(paragraph, _q("linesegarray"))
    text_position = 0
    for index, line in enumerate(lines):
        etree.SubElement(
            line_seg_array,
            _q("lineseg"),
            {
                "textpos": str(max(0, text_position)),
                "vertpos": str(max(0, index * line_height)),
                "vertsize": str(max(1, line_height)),
                "textheight": str(max(1, line_height)),
                "baseline": str(max(1, int(line_height * 0.85))),
                "spacing": str(max(0, int(line_height * 0.15))),
                "horzpos": "0",
                "horzsize": str(max(1, width)),
                "flags": "393216",
            },
        )
        text_position += len(_pdf_output_text(_line_text(line)))
        if index + 1 < len(lines):
            text_position += 1


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


def _set_cell_vertical_alignment(cell: Any, alignment: str = "TOP") -> None:
    sub = cell.element.find(_q("subList"))
    if sub is None:
        cell.set_text("", split_paragraphs=True)
        sub = cell.element.find(_q("subList"))
    if sub is not None:
        sub.set("vertAlign", alignment.upper())


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


def _append_empty_flow_table(
    cell: Any,
    *,
    width: int,
    height: int,
    border_fill_id_ref: str,
) -> int:
    safe_height = max(0, int(height))
    if safe_height < _pt_to_hwp(1.0):
        return 0
    safe_width = max(1, int(width))
    table = cell.add_table(
        1,
        1,
        width=safe_width,
        height=safe_height,
        border_fill_id_ref=border_fill_id_ref,
    )
    nested = table.cell(0, 0)
    nested.set_size(safe_width, safe_height)
    _set_cell_border_fill(nested, border_fill_id_ref)
    _set_cell_margin(
        nested,
        left_mm=0.0,
        right_mm=0.0,
        top_mm=0.0,
        bottom_mm=0.0,
    )
    _clear_cell_paragraphs(nested)
    return safe_height


def _append_cell_line(
    doc: HwpxDocument,
    cell: Any,
    line: dict[str, Any],
    *,
    styles: dict[tuple[str, float, bool], str],
    para_pr_id_ref: str,
    font_scale: float = 1.0,
    force_font: str | None = None,
    line_height_hwp: int | None = None,
    line_width_hwp: int | None = None,
) -> bool:
    runs = _span_text_runs(
        doc,
        styles,
        line.get("spans", []),
        size_scale=font_scale,
        force_font=force_font,
    )
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
    if line_height_hwp is not None:
        _append_text_box_lineseg_hwp(
            paragraph.element,
            max(1, int(line_width_hwp or _section_text_width(paragraph.section.element))),
            max(1, int(line_height_hwp)),
        )
    return True


def _append_cell_paragraph_lines(
    doc: HwpxDocument,
    cell: Any,
    lines: list[dict[str, Any]],
    *,
    styles: dict[tuple[str, float, bool], str],
    para_pr_id_ref: str,
    font_scale: float = 1.0,
    force_font: str | None = None,
    line_width_hwp: int | None = None,
    line_height_hwp: int | None = None,
) -> bool:
    all_runs: list[tuple[str, str]] = []
    line_positions: list[int] = []
    text_cursor = 0
    for line in lines:
        line_runs = _span_text_runs(
            doc,
            styles,
            line.get("spans", []),
            size_scale=font_scale,
            force_font=force_font,
        )
        if not line_runs:
            continue
        if all_runs:
            previous_text = all_runs[-1][0]
            current_text = line_runs[0][0]
            if (
                not previous_text.endswith((" ", "-", "(", "[", "‘", "“"))
                and not current_text.startswith((" ", ".", ",", ")", "]", ":", ";", "?", "!", "%"))
            ):
                all_runs.append((" ", all_runs[-1][1]))
                text_cursor += 1
        line_positions.append(text_cursor)
        all_runs.extend(line_runs)
        text_cursor += sum(len(text) for text, _char_pr in line_runs)
    if not all_runs:
        return False
    paragraph = cell.add_paragraph(
        "",
        para_pr_id_ref=para_pr_id_ref,
        char_pr_id_ref=all_runs[0][1],
    )
    # Temporary private attributes survive the vendor serializer and are
    # consumed by the Hancom compatibility patch below.  They are removed
    # before the final HWPX is written.
    paragraph.element.set("dataFlowLineCount", str(len(lines)))
    paragraph.element.set(
        "dataFlowLinePositions",
        ",".join(str(value) for value in line_positions),
    )
    if line_width_hwp is not None:
        paragraph.element.set("dataFlowLineWidth", str(max(1, int(line_width_hwp))))
    if line_height_hwp is not None:
        paragraph.element.set("dataFlowLineHeight", str(max(1, int(line_height_hwp))))
    for run in list(paragraph.element.findall(_q("run"))):
        paragraph.element.remove(run)
    for text, char_pr_id_ref in all_runs:
        if text == "":
            continue
        run = etree.SubElement(
            paragraph.element,
            _q("run"),
            {"charPrIDRef": str(char_pr_id_ref)},
        )
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
    if x_ratio >= 0.82 and vertical_touch:
        return True

    y_overlap = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    y_ratio = y_overlap / max(1.0, min(a.height, b.height))
    horizontal_gap = max(a.x0, b.x0) - min(a.x1, b.x1)
    return y_ratio >= 0.72 and horizontal_gap <= 12.0


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


def _expand_flow_image_frames(
    page: fitz.Page,
    images: list[dict[str, Any]],
    drawings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Include a nearby regional figure frame without rasterizing the page."""
    verticals: list[tuple[float, float, float]] = []
    horizontals: list[tuple[float, float, float]] = []
    if drawings is None:
        drawings = page.get_drawings()
    for drawing in drawings:
        for item in drawing.get("items", []):
            if not item or item[0] != "l":
                continue
            p0, p1 = item[1], item[2]
            x0, y0, x1, y1 = float(p0.x), float(p0.y), float(p1.x), float(p1.y)
            if abs(x1 - x0) <= 0.7 and abs(y1 - y0) >= 20.0:
                verticals.append(((x0 + x1) / 2.0, min(y0, y1), max(y0, y1)))
            elif abs(y1 - y0) <= 0.7 and abs(x1 - x0) >= 30.0:
                horizontals.append(((y0 + y1) / 2.0, min(x0, x1), max(x0, x1)))

    if not verticals or not horizontals:
        return images

    expanded: list[dict[str, Any]] = []
    matrix = fitz.Matrix(2.0, 2.0)
    for image in images:
        bbox = _item_bbox(image)
        left_candidates = [
            line
            for line in verticals
            if bbox.x0 - 22.0 <= line[0] <= bbox.x0 + 2.0
            and line[1] <= bbox.y0 + 5.0
            and line[2] >= bbox.y1 - 2.0
        ]
        right_candidates = [
            line
            for line in verticals
            if bbox.x1 - 2.0 <= line[0] <= bbox.x1 + 22.0
            and line[1] <= bbox.y0 + 5.0
            and line[2] >= bbox.y1 - 2.0
        ]
        if not left_candidates or not right_candidates:
            expanded.append(image)
            continue

        left = max(left_candidates, key=lambda line: line[0])
        right = min(right_candidates, key=lambda line: line[0])
        frame_width = right[0] - left[0]
        if frame_width <= bbox.width or frame_width > bbox.width + 45.0:
            expanded.append(image)
            continue

        bottom_candidates = [
            line
            for line in horizontals
            if bbox.y1 - 2.0 <= line[0] <= bbox.y1 + 16.0
            and line[1] <= left[0] + 3.0
            and line[2] >= right[0] - 3.0
            and line[2] - line[1] <= frame_width + 12.0
        ]
        if not bottom_candidates:
            expanded.append(image)
            continue
        bottom = min(bottom_candidates, key=lambda line: line[0])
        top_candidates = [
            line
            for line in horizontals
            if bbox.y0 - 16.0 <= line[0] <= bbox.y0 + 2.0
            and line[1] <= left[0] + 3.0
            and line[2] >= right[0] - 3.0
            and line[2] - line[1] <= frame_width + 12.0
        ]
        top_y = (
            max(top_candidates, key=lambda line: line[0])[0]
            if top_candidates
            else min(bbox.y0, left[1], right[1])
        )
        frame = fitz.Rect(left[0], top_y, right[0], bottom[0]) & page.rect
        if frame.height <= bbox.height or frame.height > bbox.height + 35.0:
            expanded.append(image)
            continue

        pix = page.get_pixmap(matrix=matrix, clip=frame, alpha=False)
        expanded.append(
            {
                **image,
                "bbox": frame,
                "image": pix.tobytes("png"),
                "ext": "png",
                "frame_expanded": True,
            }
        )
    return expanded


def _text_line_count_in_region(
    page: fitz.Page,
    region: fitz.Rect,
    text_lines: list[dict[str, Any]] | None = None,
) -> int:
    count = 0
    for line in text_lines if text_lines is not None else _iter_text_lines(page):
        if not _line_text(line):
            continue
        bbox = fitz.Rect(line["bbox"])
        center = fitz.Point((bbox.x0 + bbox.x1) / 2.0, (bbox.y0 + bbox.y1) / 2.0)
        if region.contains(center):
            count += 1
    return count


def _text_char_count_in_region(
    page: fitz.Page,
    region: fitz.Rect,
    text_lines: list[dict[str, Any]] | None = None,
) -> int:
    count = 0
    for line in text_lines if text_lines is not None else _iter_text_lines(page):
        bbox = fitz.Rect(line["bbox"])
        center = fitz.Point((bbox.x0 + bbox.x1) / 2.0, (bbox.y0 + bbox.y1) / 2.0)
        if region.contains(center):
            count += len(re.sub(r"\s+", "", _line_text(line)))
    return count


def _convert_textual_image_regions(
    page: fitz.Page,
    images: list[dict[str, Any]],
    *,
    preserve_editable_text: bool = False,
    text_lines: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[fitz.Rect]]:
    converted: list[dict[str, Any]] = []
    text_regions: list[fitz.Rect] = []
    matrix = fitz.Matrix(2.0, 2.0)
    for item in images:
        region = _item_bbox(item)
        if (
            region.width >= page.rect.width * 0.24
            and region.height >= 60
            and _text_line_count_in_region(page, region, text_lines) >= 3
            and _text_char_count_in_region(page, region, text_lines) >= 24
        ):
            text_regions.append(region)
            if preserve_editable_text:
                continue
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
        else:
            converted.append(item)
    return converted, text_regions


def _has_table_lines(
    page: fitz.Page,
    rect: fitz.Rect,
    drawings: list[dict[str, Any]] | None = None,
) -> bool:
    horizontal = 0
    vertical = 0
    probe = fitz.Rect(rect)
    probe.x0 -= 4
    probe.y0 -= 4
    probe.x1 += 4
    probe.y1 += 4
    if drawings is None:
        drawings = page.get_drawings()
    for drawing in drawings:
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
            if horizontal >= 2 and vertical >= 2:
                return True
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


def _drawing_table_regions(
    page: fitz.Page,
    drawings: list[dict[str, Any]] | None = None,
) -> list[fitz.Rect]:
    line_items: list[tuple[fitz.Rect, str]] = []
    if drawings is None:
        drawings = page.get_drawings()
    for drawing in drawings:
        for item in drawing.get("items", []):
            if not item or item[0] != "l":
                continue
            p0, p1 = item[1], item[2]
            x0, y0, x1, y1 = float(p0.x), float(p0.y), float(p1.x), float(p1.y)
            if max(y0, y1) < page.rect.height * 0.13:
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

    if len(line_items) > _MAX_FLOW_LAYOUT_AXIS_LINES:
        # Thousands of axis-aligned segments come from a map or vector
        # illustration, not table chrome.  Component clustering on those paths
        # is slow and semantically wrong; the embedded images still carry the
        # visual content of such pages.
        return []

    components: list[list[tuple[fitz.Rect, str]]] = []
    component_bounds: list[fitz.Rect] = []
    for rect, orientation in line_items:
        placed = False
        for component_index, component in enumerate(components):
            bounds = component_bounds[component_index]
            if _rects_touch(bounds, rect, gap=12):
                component.append((rect, orientation))
                bounds.include_rect(rect)
                placed = True
                break
        if not placed:
            components.append([(rect, orientation)])
            component_bounds.append(fitz.Rect(rect))

    changed = True
    while changed:
        changed = False
        for left_index in range(len(components)):
            left_bounds = component_bounds[left_index]
            for right_index in range(left_index + 1, len(components)):
                right_bounds = component_bounds[right_index]
                if not _rects_touch(left_bounds, right_bounds, gap=8):
                    continue
                components[left_index].extend(components.pop(right_index))
                left_bounds.include_rect(component_bounds.pop(right_index))
                changed = True
                break
            if changed:
                break

    changed = True
    while changed:
        changed = False
        merged: list[list[tuple[fitz.Rect, str]]] = []
        merged_bounds: list[fitz.Rect] = []
        while components:
            current = components.pop(0)
            current_bounds = component_bounds.pop(0)
            index = 0
            while index < len(components):
                other = components[index]
                other_bounds = component_bounds[index]
                if _rects_touch(current_bounds, other_bounds, gap=12):
                    current.extend(other)
                    current_bounds.include_rect(other_bounds)
                    components.pop(index)
                    component_bounds.pop(index)
                    changed = True
                else:
                    index += 1
            merged.append(current)
            merged_bounds.append(current_bounds)
        components = merged
        component_bounds = merged_bounds

    regions: list[fitz.Rect] = []
    for component, bounds in zip(components, component_bounds):
        orientations = [orientation for _, orientation in component]
        horizontal = orientations.count("h")
        vertical = orientations.count("v")
        if horizontal < 3 or vertical < 2:
            continue
        if bounds.width < page.rect.width * 0.10 or bounds.height < 28:
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


def _cluster_flow_axes(values: list[float], *, tolerance: float = 2.0) -> list[float]:
    clusters: list[list[float]] = []
    for value in sorted(values):
        if not clusters or abs(value - sum(clusters[-1]) / len(clusters[-1])) > tolerance:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return [sum(cluster) / len(cluster) for cluster in clusters]


def _flow_native_table_items(
    page: fitz.Page,
    text_lines: list[dict[str, Any]] | None = None,
    drawings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if text_lines is None:
        text_lines = _iter_text_lines(page)
    if drawings is None:
        drawings = page.get_drawings()
    result: list[dict[str, Any]] = []
    for region in _drawing_table_regions(page, drawings):
        horizontal_segments: list[tuple[float, float, float]] = []
        vertical_axes: list[float] = []
        for drawing in drawings:
            for raw in drawing.get("items", []):
                if not raw or raw[0] != "l":
                    continue
                p0, p1 = raw[1], raw[2]
                x0, y0, x1, y1 = float(p0.x), float(p0.y), float(p1.x), float(p1.y)
                center = fitz.Point((x0 + x1) / 2.0, (y0 + y1) / 2.0)
                if not region.contains(center):
                    continue
                if abs(y1 - y0) <= 0.7 and abs(x1 - x0) >= region.width * 0.35:
                    horizontal_segments.append((min(x0, x1), max(x0, x1), (y0 + y1) / 2.0))
                elif abs(x1 - x0) <= 0.7 and abs(y1 - y0) >= 12.0:
                    vertical_axes.append((x0 + x1) / 2.0)

        if len(horizontal_segments) < 3:
            continue
        y_boundaries = _cluster_flow_axes([segment[2] for segment in horizontal_segments])
        if len(y_boundaries) < 4:
            continue
        grid_left = min(segment[0] for segment in horizontal_segments)
        grid_right = max(segment[1] for segment in horizontal_segments)
        x_boundaries = _cluster_flow_axes([grid_left, grid_right, *vertical_axes])
        x_boundaries = [value for value in x_boundaries if grid_left - 2 <= value <= grid_right + 2]
        if len(x_boundaries) < 3:
            continue

        spans: list[dict[str, Any]] = []
        for line in text_lines:
            for span in line.get("spans", []):
                text = str(span.get("text") or "").strip()
                if not text:
                    continue
                bbox = fitz.Rect(span.get("bbox") or (0, 0, 0, 0))
                center = fitz.Point((bbox.x0 + bbox.x1) / 2.0, (bbox.y0 + bbox.y1) / 2.0)
                if region.contains(center):
                    spans.append({**span, "text": text, "bbox": tuple(bbox)})
        region_text = " ".join(str(span.get("text") or "") for span in spans)
        private_use_ratio = (
            sum(1 for char in region_text if 0xE000 <= ord(char) <= 0xF8FF)
            / max(1, len(region_text))
        )
        if _latin_ratio(region_text) < 0.35 and private_use_ratio < 0.35:
            continue
        text_x_clusters = _cluster_flow_axes(
            [
                (fitz.Rect(span["bbox"]).x0 + fitz.Rect(span["bbox"]).x1) / 2.0
                for span in spans
                if y_boundaries[0] <= (fitz.Rect(span["bbox"]).y0 + fitz.Rect(span["bbox"]).y1) / 2.0 <= y_boundaries[-1]
            ],
            tolerance=18.0,
        )
        if len(text_x_clusters) < 2:
            continue

        has_label_column = any(
            (fitz.Rect(span["bbox"]).x0 + fitz.Rect(span["bbox"]).x1) / 2.0 < grid_left - 1.0
            and y_boundaries[0]
            <= (fitz.Rect(span["bbox"]).y0 + fitz.Rect(span["bbox"]).y1) / 2.0
            <= y_boundaries[-1]
            for span in spans
        )
        if has_label_column:
            x_boundaries = [min(region.x0, grid_left - 12.0), *x_boundaries]
            x_boundaries = _cluster_flow_axes(x_boundaries)

        row_count = len(y_boundaries) - 1
        column_count = len(x_boundaries) - 1
        cells: list[list[list[dict[str, Any]]]] = [
            [[] for _column in range(column_count)] for _row in range(row_count)
        ]
        title_spans: list[dict[str, Any]] = []
        for span in spans:
            bbox = fitz.Rect(span["bbox"])
            center_x = (bbox.x0 + bbox.x1) / 2.0
            center_y = (bbox.y0 + bbox.y1) / 2.0
            if center_y < y_boundaries[0]:
                title_spans.append(span)
                continue
            row_index = next(
                (
                    index
                    for index in range(row_count)
                    if y_boundaries[index] - 1.0 <= center_y <= y_boundaries[index + 1] + 1.0
                ),
                None,
            )
            column_index = next(
                (
                    index
                    for index in range(column_count)
                    if x_boundaries[index] - 1.0 <= center_x <= x_boundaries[index + 1] + 1.0
                ),
                None,
            )
            if row_index is not None and column_index is not None:
                cells[row_index][column_index].append(span)

        populated_rows = sum(1 for row in cells if sum(bool(cell) for cell in row) >= 2)
        if populated_rows < 2:
            continue
        table_bbox = fitz.Rect(
            x_boundaries[0],
            min((fitz.Rect(span["bbox"]).y0 for span in title_spans), default=y_boundaries[0]),
            x_boundaries[-1],
            y_boundaries[-1],
        )
        result.append(
            {
                "type": "native_table",
                "bbox": table_bbox,
                "grid_bbox": fitz.Rect(grid_left, y_boundaries[0], grid_right, y_boundaries[-1]),
                "x_boundaries": x_boundaries,
                "y_boundaries": y_boundaries,
                "cells": cells,
                "title_spans": title_spans,
            }
        )
    return result


def _iter_flow_table_images(
    page: fitz.Page,
    drawings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if drawings is None:
        drawings = page.get_drawings()
    blocks = [block for block in page.get_text("dict").get("blocks", []) if block.get("type") == 0]
    used: set[int] = set()
    table_images: list[dict[str, Any]] = []
    matrix = fitz.Matrix(2.0, 2.0)
    for region in _drawing_table_regions(page, drawings):
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
        if rect.width < page.rect.width * 0.22 or rect.height < 8:
            continue
        if _span_count(block) < 5 or _x_cluster_count(block) < 5:
            continue
        seed_probe = fitz.Rect(rect)
        seed_probe.x0 = max(0.0, seed_probe.x0 - 4)
        seed_probe.y0 = max(0.0, seed_probe.y0 - 4)
        seed_probe.x1 = min(page.rect.width, seed_probe.x1 + 4)
        seed_probe.y1 = min(page.rect.height, seed_probe.y1 + 4)
        if not _has_table_lines(page, seed_probe, drawings):
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
        if not _has_table_lines(page, padded, drawings):
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
    coordinate_scale: float = 1.0,
    para_styles: dict[tuple[Any, ...], str] | None = None,
    left_margin_hwp: int = 0,
    before_gap_hwp: int = 0,
) -> bool:
    bbox = _item_bbox(image)
    try:
        image_data = _png_from_extracted_image(bytes(image["image"]), str(image.get("ext") or "png"))
    except Exception:
        return False
    width = min(
        max(
            1,
            cell_width
            - max(0, int(left_margin_hwp))
            - _pt_to_hwp(4 * coordinate_scale),
        ),
        max(1, _pt_to_hwp(bbox.width * coordinate_scale)),
    )
    height = max(1, int(round(width * max(1.0, bbox.height) / max(1.0, bbox.width))))
    item_id = doc.add_image(image_data, "png")
    if para_styles is not None:
        host_para = _ensure_flow_para_format(
            doc,
            para_styles,
            alignment="LEFT",
            line_spacing_percent=100,
            left_margin_hwp=max(0, int(left_margin_hwp)),
            prev_margin_hwp=max(0, int(before_gap_hwp)),
        )
        host = cell.add_paragraph("", para_pr_id_ref=host_para, char_pr_id_ref="0")
        table = host.add_table(
            1,
            1,
            width=width,
            height=height,
            border_fill_id_ref=border_fill_id_ref,
        )
    else:
        table = cell.add_table(
            1,
            1,
            width=width,
            height=height,
            border_fill_id_ref=border_fill_id_ref,
        )
    nested = table.cell(0, 0)
    _clear_cell_paragraphs(nested)
    paragraph = nested.add_paragraph("", para_pr_id_ref=para_pr_id_ref, char_pr_id_ref="0")
    paragraph.add_picture(item_id, width=width, height=height)
    return True


def _flow_lines_from_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[list[dict[str, Any]]] = []
    for span in sorted(
        spans,
        key=lambda item: (
            (fitz.Rect(item["bbox"]).y0 + fitz.Rect(item["bbox"]).y1) / 2.0,
            fitz.Rect(item["bbox"]).x0,
        ),
    ):
        center_y = (fitz.Rect(span["bbox"]).y0 + fitz.Rect(span["bbox"]).y1) / 2.0
        if rows:
            previous = rows[-1][0]
            previous_y = (fitz.Rect(previous["bbox"]).y0 + fitz.Rect(previous["bbox"]).y1) / 2.0
            if abs(center_y - previous_y) <= 3.0:
                rows[-1].append(span)
                continue
        rows.append([span])
    lines: list[dict[str, Any]] = []
    for row in rows:
        row.sort(key=lambda item: fitz.Rect(item["bbox"]).x0)
        lines.append(
            {
                "type": "line",
                "bbox": _union_rect([fitz.Rect(item["bbox"]) for item in row]),
                "spans": row,
            }
        )
    return lines


def _append_native_flow_table(
    doc: HwpxDocument,
    cell: Any,
    block: dict[str, Any],
    *,
    styles: dict[tuple[str, float, bool], str],
    para_styles: dict[tuple[Any, ...], str],
    cell_width: int,
    border_fill_id_ref: str,
    coordinate_scale: float,
    font_scale: float,
    force_font: str | None,
) -> int:
    item = block["native_table"]
    bbox = _item_bbox(item)
    column_left = float(block.get("column_left_pt") or bbox.x0)
    indent_hwp = _pt_to_hwp(
        min(36.0, max(0.0, bbox.x0 - column_left)) * coordinate_scale
    )
    maximum_width = max(1, cell_width - indent_hwp - _pt_to_hwp(4.0 * coordinate_scale))
    table_width = min(maximum_width, max(1, _pt_to_hwp(bbox.width * coordinate_scale)))
    count = 0

    title_lines = _flow_lines_from_spans(list(item.get("title_spans") or []))
    for title_line in title_lines:
        title_para = _ensure_flow_para_format(
            doc,
            para_styles,
            alignment="CENTER",
            line_spacing_percent=100,
            left_margin_hwp=indent_hwp,
        )
        if _append_cell_line(
            doc,
            cell,
            title_line,
            styles=styles,
            para_pr_id_ref=title_para,
            font_scale=font_scale,
            force_font=force_font,
        ):
            count += 1

    x_boundaries = [float(value) for value in item.get("x_boundaries") or []]
    y_boundaries = [float(value) for value in item.get("y_boundaries") or []]
    cells = item.get("cells") or []
    row_count = max(0, len(y_boundaries) - 1)
    column_count = max(0, len(x_boundaries) - 1)
    if row_count <= 0 or column_count <= 0:
        return count

    source_widths = [max(1.0, x_boundaries[index + 1] - x_boundaries[index]) for index in range(column_count)]
    width_total = sum(source_widths)
    column_widths = [max(1, int(round(table_width * width / width_total))) for width in source_widths]
    column_widths[-1] = max(1, table_width - sum(column_widths[:-1]))
    row_heights = [
        max(_pt_to_hwp(8.0), _pt_to_hwp((y_boundaries[index + 1] - y_boundaries[index]) * coordinate_scale))
        for index in range(row_count)
    ]
    table_height = sum(row_heights)
    host_para = _ensure_flow_para_format(
        doc,
        para_styles,
        alignment="LEFT",
        line_spacing_percent=100,
        left_margin_hwp=indent_hwp,
    )
    host = cell.add_paragraph("", para_pr_id_ref=host_para, char_pr_id_ref="0")
    table = host.add_table(
        row_count,
        column_count,
        width=table_width,
        height=table_height,
        border_fill_id_ref=border_fill_id_ref,
    )
    try:
        table.set_column_widths(source_widths)
    except Exception:
        pass

    for row_index in range(row_count):
        for column_index in range(column_count):
            target = table.cell(row_index, column_index)
            target.set_size(column_widths[column_index], row_heights[row_index])
            _set_cell_border_fill(target, border_fill_id_ref)
            _set_cell_margin(
                target,
                left_mm=0.25,
                right_mm=0.25,
                top_mm=0.1,
                bottom_mm=0.1,
            )
            _clear_cell_paragraphs(target)
            span_lines = _flow_lines_from_spans(list(cells[row_index][column_index]))
            for span_line in span_lines:
                text = _line_text(span_line)
                alignment = "LEFT" if len(text) > 22 else "CENTER"
                para = _ensure_flow_para_format(
                    doc,
                    para_styles,
                    alignment=alignment,
                    line_spacing_percent=100,
                )
                if _append_cell_line(
                    doc,
                    target,
                    span_line,
                    styles=styles,
                    para_pr_id_ref=para,
                    font_scale=font_scale,
                    force_font=force_font,
                ):
                    count += 1
    return count


def _flow_box_rects(
    page: fitz.Page,
    text_lines: list[dict[str, Any]] | None = None,
    drawings: list[dict[str, Any]] | None = None,
    raster_dark: np.ndarray | None = None,
) -> list[fitz.Rect]:
    boxes: list[fitz.Rect] = []
    page_area = float(page.rect.width * page.rect.height)
    if drawings is None:
        drawings = page.get_drawings()
    for drawing in drawings:
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
            long_passage_box = (
                page.rect.width * 0.22 <= rect.width <= page.rect.width * 0.55
                and rect.height <= page.rect.height * 0.78
                and _text_line_count_in_region(page, rect, text_lines) >= 4
            )
            if rect.width > page.rect.width * 0.55 or (
                rect.height > page.rect.height * 0.33 and not long_passage_box
            ):
                continue
            if area > page_area * 0.75:
                continue
            if rect.y0 < 35 and rect.height < 35:
                continue
            if not any(_rects_close(rect, existing) for existing in boxes):
                boxes.append(rect)
    for rect in _drawing_box_rects(page, text_lines, drawings):
        if not any(_rects_close(rect, existing) or rect.intersects(existing) for existing in boxes):
            boxes.append(rect)
    for rect in _rail_box_rects(page, text_lines, drawings):
        if not any(_rects_close(rect, existing) or rect.intersects(existing) for existing in boxes):
            boxes.append(rect)
    for rect in _raster_box_rects(page, text_lines, raster_dark):
        if not any(
            _rects_close(rect, existing)
            or (
                rect.intersects(existing)
                and (rect & existing).get_area()
                >= max(rect.get_area(), existing.get_area()) * 0.82
            )
            for existing in boxes
        ):
            boxes.append(rect)
    boxes.sort(key=lambda item: (item.y0, item.x0, item.width * item.height))
    return boxes


def _rail_box_rects(
    page: fitz.Page,
    text_lines: list[dict[str, Any]] | None = None,
    drawings: list[dict[str, Any]] | None = None,
) -> list[fitz.Rect]:
    verticals: list[fitz.Rect] = []
    horizontals: list[fitz.Rect] = []
    if drawings is None:
        drawings = page.get_drawings()
    for drawing in drawings:
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
            vertically_connected = (
                segment.y0 <= rail.y1 + 3.0
                and segment.y1 >= rail.y0 - 3.0
            )
            if abs(center_x - rail_x) <= 2.0 and vertically_connected:
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
        intervals = sorted(
            (max(lx, line.x0), min(rx, line.x1))
            for line in horizontals
            if abs(((line.y0 + line.y1) / 2.0) - y) <= 8
            and line.x1 >= lx - 4
            and line.x0 <= rx + 4
        )
        intervals = [interval for interval in intervals if interval[1] > interval[0]]
        if not intervals or intervals[0][0] > lx + 4:
            return False
        maximum_title_gap = max(12.0, (rx - lx) * 0.18)
        covered_right = intervals[0][1]
        for start, end in intervals[1:]:
            if start - covered_right > maximum_title_gap:
                return False
            covered_right = max(covered_right, end)
        return covered_right >= rx - 4

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
            if bottom - top < max(96.0, page.rect.height * 0.10):
                continue
            if not (
                has_edge(left, right, top)
                and has_edge(left, right, bottom)
            ):
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
        text_line_count = _text_line_count_in_region(page, padded, text_lines)
        if text_line_count < 4:
            continue
        if text_line_count > 52:
            continue
        if text_line_count >= 20 and padded.height / max(1, text_line_count) < 12.0:
            continue
        boxes.append(padded)
        used.add(left_index)
        used.add(best_index)
    return boxes


def _binary_runs(values: np.ndarray, *, minimum: int) -> list[tuple[int, int]]:
    padded = np.concatenate((np.array([False]), values.astype(bool), np.array([False])))
    changes = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    return [
        (int(start), int(end))
        for start, end in zip(starts, ends)
        if int(end) - int(start) >= minimum
    ]


def _page_dark_pixels(page: fitz.Page, *, threshold: int = 170) -> np.ndarray | None:
    try:
        pix = page.get_pixmap(
            matrix=fitz.Matrix(1.0, 1.0),
            colorspace=fitz.csGRAY,
            alpha=False,
        )
        gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height,
            pix.stride,
        )[:, : pix.width]
    except Exception:
        return None
    return gray < threshold


def _merge_axis_segments(
    segments: list[tuple[float, float, float]],
    *,
    axis_tolerance: float = 2.0,
    edge_tolerance: float = 8.0,
) -> list[tuple[float, float, float]]:
    groups: list[list[tuple[float, float, float]]] = []
    for segment in sorted(segments):
        axis, start, end = segment
        placed = False
        for group in groups:
            g_axis = _median_float([item[0] for item in group])
            g_start = _median_float([item[1] for item in group])
            g_end = _median_float([item[2] for item in group])
            if (
                abs(axis - g_axis) <= axis_tolerance
                and abs(start - g_start) <= edge_tolerance
                and abs(end - g_end) <= edge_tolerance
            ):
                group.append(segment)
                placed = True
                break
        if not placed:
            groups.append([segment])
    return [
        (
            _median_float([item[0] for item in group]),
            min(item[1] for item in group),
            max(item[2] for item in group),
        )
        for group in groups
    ]


def _raster_box_rects(
    page: fitz.Page,
    text_lines: list[dict[str, Any]] | None = None,
    raster_dark: np.ndarray | None = None,
) -> list[fitz.Rect]:
    """Recover ruled passage boxes that PyMuPDF exposes only as pixels."""
    dark = raster_dark if raster_dark is not None else _page_dark_pixels(page)
    if dark is None:
        return []
    min_horizontal = max(60, int(page.rect.width * 0.075))
    horizontal: list[tuple[float, float, float]] = []
    join_gap = max(24, int(page.rect.width * 0.075))
    for y in range(dark.shape[0]):
        runs = _binary_runs(dark[y, :], minimum=min_horizontal)
        if not runs:
            continue
        combined: list[list[int]] = []
        for start, end in runs:
            if combined and start - combined[-1][1] <= join_gap:
                combined[-1][1] = end
            else:
                combined.append([start, end])
        for start, end in combined:
            width = end - start
            if page.rect.width * 0.16 <= width <= page.rect.width * 0.54:
                horizontal.append((float(y), float(start), float(end)))
    horizontal = _merge_axis_segments(horizontal)

    vertical: list[tuple[float, float, float]] = []
    min_vertical = max(20, int(page.rect.height * 0.02))
    for x in range(dark.shape[1]):
        for start, end in _binary_runs(dark[:, x], minimum=min_vertical):
            if page.rect.height * 0.02 <= end - start <= page.rect.height * 0.55:
                vertical.append((float(x), float(start), float(end)))
    vertical = _merge_axis_segments(vertical, edge_tolerance=10.0)

    candidates: list[fitz.Rect] = []
    for top_index, (top_y, top_x0, top_x1) in enumerate(horizontal):
        for bottom_y, bottom_x0, bottom_x1 in horizontal[top_index + 1 :]:
            height = bottom_y - top_y
            if height < 20.0 or height > page.rect.height * 0.46:
                continue
            x0 = min(top_x0, bottom_x0)
            x1 = max(top_x1, bottom_x1)
            width = x1 - x0
            overlap = max(0.0, min(top_x1, bottom_x1) - max(top_x0, bottom_x0))
            if width < page.rect.width * 0.18 or width > page.rect.width * 0.54:
                continue
            if overlap < min(top_x1 - top_x0, bottom_x1 - bottom_x0) * 0.72:
                continue
            left_side = any(
                abs(axis - x0) <= 5.0
                and start <= top_y + 8.0
                and end >= bottom_y - 8.0
                for axis, start, end in vertical
            )
            right_side = any(
                abs(axis - x1) <= 5.0
                and start <= top_y + 8.0
                and end >= bottom_y - 8.0
                for axis, start, end in vertical
            )
            if not (left_side and right_side):
                continue
            rect = fitz.Rect(x0, top_y, x1, bottom_y)
            if _text_line_count_in_region(page, rect, text_lines) < 3:
                continue
            candidates.append(rect)

    selected: list[fitz.Rect] = []
    for rect in sorted(candidates, key=lambda item: item.get_area(), reverse=True):
        if any(existing.contains(rect) for existing in selected):
            continue
        selected.append(rect)
    return selected


def _raster_native_table_items(
    page: fitz.Page,
    text_lines: list[dict[str, Any]] | None = None,
    raster_dark: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """Recover compact ruled tables whose borders are flattened in the PDF."""
    if text_lines is None:
        text_lines = _iter_text_lines(page)
    dark = raster_dark if raster_dark is not None else _page_dark_pixels(page)
    if dark is None:
        return []
    horizontal: list[tuple[float, float, float]] = []
    minimum = max(70, int(page.rect.width * 0.08))
    for y in range(dark.shape[0]):
        for start, end in _binary_runs(dark[y, :], minimum=minimum):
            width = end - start
            if page.rect.width * 0.18 <= width <= page.rect.width * 0.52:
                horizontal.append((float(y), float(start), float(end)))
    horizontal = _merge_axis_segments(horizontal)
    candidates: list[list[tuple[float, float, float]]] = []
    for index, seed in enumerate(horizontal):
        group = [seed]
        for candidate in horizontal[index + 1 :]:
            gap = candidate[0] - group[-1][0]
            if gap > 42.0:
                break
            if gap < 5.0:
                continue
            if (
                abs(candidate[1] - seed[1]) <= 12.0
                and abs(candidate[2] - seed[2]) <= 12.0
            ):
                group.append(candidate)
        if 3 <= len(group) <= 12 and group[-1][0] - group[0][0] <= page.rect.height * 0.18:
            candidates.append(group)

    result: list[dict[str, Any]] = []
    occupied: list[fitz.Rect] = []
    for group in sorted(candidates, key=lambda value: value[-1][0] - value[0][0], reverse=True):
        y_boundaries = [item[0] for item in group]
        x0 = _median_float([item[1] for item in group])
        x1 = _median_float([item[2] for item in group])
        grid = fitz.Rect(x0, y_boundaries[0], x1, y_boundaries[-1])
        if any(existing.contains(grid) or grid.contains(existing) for existing in occupied):
            continue
        row_spans: list[list[dict[str, Any]]] = [[] for _ in range(len(y_boundaries) - 1)]
        for line in text_lines:
            for span in line.get("spans", []):
                if not str(span.get("text") or "").strip():
                    continue
                bbox = fitz.Rect(span.get("bbox") or line.get("bbox"))
                center = fitz.Point((bbox.x0 + bbox.x1) / 2.0, (bbox.y0 + bbox.y1) / 2.0)
                if not grid.contains(center):
                    continue
                row_index = next(
                    (
                        index
                        for index in range(len(y_boundaries) - 1)
                        if y_boundaries[index] <= center.y <= y_boundaries[index + 1]
                    ),
                    None,
                )
                if row_index is not None:
                    row_spans[row_index].append(span)
        while row_spans and not row_spans[-1]:
            row_spans.pop()
            y_boundaries.pop()
        while row_spans and not row_spans[0]:
            row_spans.pop(0)
            y_boundaries.pop(0)
        if len(y_boundaries) >= 2:
            grid = fitz.Rect(x0, y_boundaries[0], x1, y_boundaries[-1])
        populated = [row for row in row_spans if row]
        if len(populated) < 2 or sum(len(row) for row in populated) < 4:
            continue
        reference = max(populated, key=len)
        centers = sorted((fitz.Rect(span["bbox"]).x0 + fitz.Rect(span["bbox"]).x1) / 2.0 for span in reference)
        clustered_centers = _cluster_flow_axes(centers, tolerance=14.0)
        if not 2 <= len(clustered_centers) <= 8:
            continue
        x_boundaries = [x0]
        x_boundaries.extend(
            (left + right) / 2.0
            for left, right in zip(clustered_centers, clustered_centers[1:])
        )
        x_boundaries.append(x1)
        cells: list[list[list[dict[str, Any]]]] = [
            [[] for _ in range(len(x_boundaries) - 1)]
            for _ in range(len(y_boundaries) - 1)
        ]
        for row_index, spans in enumerate(row_spans):
            for span in spans:
                bbox = fitz.Rect(span["bbox"])
                center_x = (bbox.x0 + bbox.x1) / 2.0
                column_index = max(
                    0,
                    min(
                        len(x_boundaries) - 2,
                        next(
                            (
                                index
                                for index in range(len(x_boundaries) - 1)
                                if x_boundaries[index] <= center_x <= x_boundaries[index + 1]
                            ),
                            len(x_boundaries) - 2,
                        ),
                    ),
                )
                cells[row_index][column_index].append(span)
        result.append(
            {
                "type": "native_table",
                "bbox": grid,
                "grid_bbox": grid,
                "x_boundaries": x_boundaries,
                "y_boundaries": y_boundaries,
                "cells": cells,
            }
        )
        occupied.append(grid)
    return result


def _drawing_box_rects(
    page: fitz.Page,
    text_lines: list[dict[str, Any]] | None = None,
    drawings: list[dict[str, Any]] | None = None,
) -> list[fitz.Rect]:
    line_items: list[tuple[fitz.Rect, str]] = []
    if drawings is None:
        drawings = page.get_drawings()
    for drawing in drawings:
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
                # The page gutter intersects otherwise independent question
                # frames in many exam PDFs.  If it participates as a box rail,
                # those frames are merged into one column-height rectangle.
                midpoint = float(page.rect.width) / 2.0
                if (
                    abs(((x0 + x1) / 2.0) - midpoint) <= page.rect.width * 0.025
                    and abs(y1 - y0) >= page.rect.height * 0.45
                ):
                    continue
                rect = fitz.Rect(x0 - 1, min(y0, y1), x1 + 1, max(y0, y1))
                line_items.append((rect, "v"))
    if len(line_items) > _MAX_FLOW_LAYOUT_AXIS_LINES:
        # Maps and vector illustrations carry thousands of axis-aligned strokes
        # that are not passage-box chrome.  Skip the quadratic clustering; the
        # embedded images still preserve those pages visually.
        return []
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
        horizontal_lines = [rect for rect, orientation in component if orientation == "h"]
        vertical_lines = [rect for rect, orientation in component if orientation == "v"]

        def unique_axes(rects: list[fitz.Rect], *, horizontal_axis: bool) -> list[float]:
            values = sorted(
                ((rect.y0 + rect.y1) / 2.0) if horizontal_axis else ((rect.x0 + rect.x1) / 2.0)
                for rect in rects
            )
            unique: list[float] = []
            for value in values:
                if not unique or abs(value - unique[-1]) > 2.0:
                    unique.append(value)
            return unique

        horizontal = len(unique_axes(horizontal_lines, horizontal_axis=True))
        vertical = len(unique_axes(vertical_lines, horizontal_axis=False))
        if horizontal < 2 or vertical < 2:
            continue
        if horizontal >= 3 and vertical >= 2:
            continue
        if bounds.width < page.rect.width * 0.18 or bounds.width > page.rect.width * 0.58:
            continue
        long_passage_box = (
            bounds.height <= page.rect.height * 0.78
            and _text_line_count_in_region(page, bounds, text_lines) >= 4
        )
        if bounds.height < 20 or (bounds.height > page.rect.height * 0.34 and not long_passage_box):
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


def _flow_column_blocks(
    page: fitz.Page,
    items: list[dict[str, Any]],
    boxes: list[fitz.Rect],
    *,
    preserve_gaps: bool = False,
) -> list[list[dict[str, Any]]]:
    columns: list[list[dict[str, Any]]] = [[], []]
    midpoint = float(page.rect.width) / 2.0
    for item in items:
        bbox = _item_bbox(item)
        column = 0 if (bbox.x0 + bbox.x1) / 2.0 < midpoint else 1
        columns[column].append(item)

    result: list[list[dict[str, Any]]] = []
    for column_items in columns:
        column_items.sort(key=lambda item: (_item_bbox(item).y0, _item_bbox(item).x0))
        column_left_candidates = [
            _flow_effective_item_bbox(item, boxes).x0
            for item in column_items
            if item.get("type") != "gap"
        ]
        column_left_pt = min(column_left_candidates) if column_left_candidates else 0.0
        column_right_candidates = [
            _flow_effective_item_bbox(item, boxes).x1
            for item in column_items
            if item.get("type") != "gap"
        ]
        column_right_pt = max(column_right_candidates) if column_right_candidates else column_left_pt
        spaced_items: list[dict[str, Any]] = []
        previous_bottom: float | None = None
        previous_box: int | None = None
        for item in column_items:
            box_index = _box_for_line(item, boxes) if item.get("type") != "image" else None
            bbox = _flow_effective_item_bbox(item, boxes)
            same_box = previous_box is not None and box_index == previous_box
            if previous_bottom is not None and not same_box:
                gap_pt = bbox.y0 - previous_bottom
                spacer_pt = _flow_gap_height_pt(gap_pt, preserve=preserve_gaps)
                if spacer_pt > 0:
                    spaced_items.append({"type": "gap", "height_pt": spacer_pt})
            spaced_items.append(item)
            previous_bottom = max(bbox.y1, previous_bottom or bbox.y1)
            previous_box = box_index

        blocks: list[dict[str, Any]] = []
        active_box: int | None = None
        active_lines: list[dict[str, Any]] = []
        for item in spaced_items:
            nested_table_box = (
                _box_for_line(item, boxes)
                if item.get("type") == "native_table"
                else None
            )
            if nested_table_box is not None:
                if active_box is not None and nested_table_box != active_box and active_lines:
                    blocks.append({
                        "type": "box",
                        "lines": active_lines,
                        "rect": boxes[active_box],
                        "column_left_pt": column_left_pt,
                        "column_right_pt": column_right_pt,
                    })
                    active_lines = []
                active_box = nested_table_box
                active_lines.append(item)
                continue
            if item.get("type") in {"image", "native_table", "gap"}:
                if active_lines:
                    blocks.append({
                        "type": "box",
                        "lines": active_lines,
                        "rect": boxes[active_box] if active_box is not None else None,
                        "column_left_pt": column_left_pt,
                        "column_right_pt": column_right_pt,
                    })
                    active_lines = []
                    active_box = None
                if item.get("type") in {"image", "native_table"}:
                    blocks.append(
                        {
                            "type": item["type"],
                            item["type"]: item,
                            "column_left_pt": column_left_pt,
                            "column_right_pt": column_right_pt,
                        }
                    )
                else:
                    blocks.append(item)
                continue
            box_index = _box_for_line(item, boxes)
            if box_index is None:
                if active_lines:
                    blocks.append({
                        "type": "box",
                        "lines": active_lines,
                        "rect": boxes[active_box] if active_box is not None else None,
                        "column_left_pt": column_left_pt,
                        "column_right_pt": column_right_pt,
                    })
                    active_lines = []
                    active_box = None
                blocks.append(
                    {
                        "type": "line",
                        "line": item,
                        "column_left_pt": column_left_pt,
                        "column_right_pt": column_right_pt,
                    }
                )
                continue
            if active_box is not None and box_index != active_box and active_lines:
                blocks.append({
                    "type": "box",
                    "lines": active_lines,
                    "rect": boxes[active_box],
                    "column_left_pt": column_left_pt,
                    "column_right_pt": column_right_pt,
                })
                active_lines = []
            active_box = box_index
            active_lines.append(item)
        if active_lines:
            blocks.append({
                "type": "box",
                "lines": active_lines,
                "rect": boxes[active_box] if active_box is not None else None,
                "column_left_pt": column_left_pt,
                "column_right_pt": column_right_pt,
            })
        grouped_blocks = _group_flow_prose_blocks(blocks)
        for grouped_block in grouped_blocks:
            rect = grouped_block.get("rect")
            if grouped_block.get("type") == "box" and rect is not None:
                grouped_block["near_page_bottom"] = (
                    float(rect.y1) >= float(page.rect.height) * 0.78
                )
        result.append(grouped_blocks)
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


def _flow_gap_height_pt(raw_gap_pt: float, *, preserve: bool = False) -> float:
    if preserve:
        # The paragraphs on both sides already consume roughly one baseline
        # each.  Reserving the raw gap minus only one baseline can overfill a
        # fixed page cell and make Hancom collapse the preceding lines.
        return max(0.0, raw_gap_pt - 18.0)
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
    # Several education-office PDFs encode the running-header rule as a long
    # box-drawing text run instead of a vector line.  Treat its lower edge as
    # the body boundary so page number, subject and grade badge stay in the
    # header rather than being misclassified into the right body column.
    for line in _iter_text_lines(page):
        text = re.sub(r"\s+", "", _line_text(line))
        bbox = _item_bbox(line)
        rule_chars = sum(char in "━─—―_" for char in text)
        if (
            len(text) >= 20
            and rule_chars / max(1, len(text)) >= 0.80
            and bbox.width >= page.rect.width * 0.55
            and 45 <= bbox.y0 <= page.rect.height * 0.35
        ):
            candidates.append(float(bbox.y1))
    detected_top = max(candidates) + 4.0 if candidates else 0.0
    # Some official exam PDFs draw the header rule only on the first page.  The
    # first real question marker is a more stable semantic boundary there, and
    # it keeps a repeated page header out of the body columns.
    question_candidates = [
        max(0.0, _item_bbox(line).y0 - 6.0)
        for line in _iter_text_lines(page)
        if page.rect.height * 0.05 <= _item_bbox(line).y0 <= page.rect.height * 0.42
        and _FLOW_QUESTION_MARKER_RE.match(_line_text(line))
    ]
    question_top = min(question_candidates) if question_candidates else 0.0
    if detected_top and question_top and abs(detected_top - question_top) <= 30.0:
        return max(detected_top, question_top)
    return detected_top or question_top


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
            center_x = (bbox.x0 + bbox.x1) / 2.0
            if (
                bbox.y1 <= page.rect.height * 0.18
                and bbox.width >= page.rect.width * 0.10
                and page.rect.width * 0.30 <= center_x <= page.rect.width * 0.70
            ):
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


def _has_full_flow_header(page: fitz.Page, items: list[dict[str, Any]]) -> bool:
    for item in items:
        if item.get("type") == "image":
            continue
        text = _line_text(item)
        if not text:
            continue
        bbox = _item_bbox(item)
        compact = re.sub(r"[\s\d./()[\]\-]+", "", text)
        if len(compact) >= 12 or bbox.width >= page.rect.width * 0.36:
            return True
    return False


def _compact_running_header_items(
    page: fitz.Page,
    source_items: list[dict[str, Any]],
    *,
    page_number: int,
    subject_title: str | None,
    form_label: str | None,
    force_font: str | None,
) -> list[dict[str, Any]]:
    source_texts = [
        _line_text(item).strip()
        for item in source_items
        if item.get("type") == "line" and _line_text(item).strip()
    ]
    subject_candidates = [
        text
        for text in source_texts
        if "영역" in text and "시험" not in text and len(text) <= 40
    ]
    subject = max(subject_candidates, key=len, default=subject_title or "")
    form_candidates = [
        text
        for text in source_texts
        if text in {"홀수형", "짝수형"}
    ]
    form = form_candidates[0] if form_candidates else (form_label or "")
    page_on_right = page_number % 2 == 1
    labels = (form, subject, str(page_number)) if page_on_right else (str(page_number), subject, form)
    x_ranges = ((0.05, 0.25), (0.30, 0.70), (0.75, 0.95))
    sizes = (11.0, 16.0, 16.0) if page_on_right else (16.0, 16.0, 11.0)
    items: list[dict[str, Any]] = []
    for index, label in enumerate(labels):
        if not label:
            continue
        x0 = page.rect.width * x_ranges[index][0]
        x1 = page.rect.width * x_ranges[index][1]
        bbox = fitz.Rect(x0, 0.0, x1, 24.0)
        items.append(
            {
                "type": "line",
                "bbox": bbox,
                "spans": [
                    {
                        "text": label,
                        "bbox": tuple(bbox),
                        "size": sizes[index],
                        "font": force_font or "HYSMyeongJo-Medium",
                        "flags": 16,
                    }
                ],
            }
        )
    return items


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
    coordinate_scale: float = 1.0,
    font_scale: float = 1.0,
    force_font: str | None = None,
    bottom_border_fill: str | None = None,
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
        target = table.cell(0, column)
        _clear_cell_paragraphs(target)
        if bottom_border_fill:
            _set_cell_border_fill(target, bottom_border_fill)
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
                    coordinate_scale=coordinate_scale,
                ):
                    count += 1
            elif _append_cell_line(
                doc,
                cell,
                item,
                styles=styles,
                para_pr_id_ref=compact_para,
                font_scale=font_scale,
                force_font=force_font,
            ):
                count += 1
    return count


def _append_header_content_to_cell(
    doc: HwpxDocument,
    cell: Any | None,
    page: fitz.Page,
    items: list[dict[str, Any]],
    *,
    table_width: int,
    table_height: int,
    no_border_fill: str,
    compact_para: str,
    styles: dict[tuple[str, float, bool], str],
    para_styles: dict[tuple[Any, ...], str],
    coordinate_scale: float = 1.0,
    font_scale: float = 1.0,
    force_font: str | None = None,
    source_margin_left_pt: float = 0.0,
    source_margin_top_pt: float = 0.0,
    subject_title: str | None = None,
    form_label: str | None = None,
    page_break: bool = False,
    header_divider_border_fill: str | None = None,
) -> int:
    if not items:
        return 0
    if cell is not None:
        _clear_cell_paragraphs(cell)

    clean_items: list[dict[str, Any]] = []
    seen_lines: list[tuple[str, fitz.Rect]] = []
    title_images = [
        item
        for item in items
        if item.get("type") == "image"
        and page.rect.width * 0.38 <= (_item_bbox(item).x0 + _item_bbox(item).x1) / 2.0 <= page.rect.width * 0.62
        and 90.0 <= _item_bbox(item).width <= page.rect.width * 0.50
        and 20.0 <= _item_bbox(item).height <= 64.0
    ]
    title_image = max(title_images, key=lambda item: (_item_bbox(item).y0, _item_bbox(item).height), default=None)
    for item in items:
        if item.get("type") == "image":
            if item is not title_image:
                continue
            if subject_title:
                bbox = _item_bbox(item)
                title_size = max(24.0, min(42.0, bbox.height * 0.90))
                clean_items.append(
                    {
                        "type": "line",
                        "role": "subject_title",
                        "bbox": fitz.Rect(bbox),
                        "spans": [
                            {
                                "text": subject_title,
                                "bbox": tuple(bbox),
                                "size": title_size,
                                "font": force_font or "HYSMyeongJo-Medium",
                                "flags": 16,
                            }
                        ],
                    }
                )
            continue
        text = _line_text(item).strip()
        bbox = _item_bbox(item)
        if not text:
            continue
        duplicate = False
        for previous_text, previous_bbox in seen_lines:
            if text != previous_text:
                continue
            overlap = previous_bbox & bbox
            if overlap.is_empty:
                continue
            if overlap.get_area() >= min(previous_bbox.get_area(), bbox.get_area()) * 0.80:
                duplicate = True
                break
        if duplicate:
            continue
        seen_lines.append((text, fitz.Rect(bbox)))
        clean_items.append(item)

    has_form_label = any(
        form_label and form_label in _line_text(item)
        for item in clean_items
        if item.get("type") == "line"
    )
    page_number_on_right = any(
        _line_text(item).strip().isdigit()
        and (_item_bbox(item).x0 + _item_bbox(item).x1) / 2.0 > page.rect.width * 0.70
        for item in clean_items
        if item.get("type") == "line"
    )
    if form_label and not has_form_label and page_number_on_right:
        bbox = fitz.Rect(98.0, 113.0, 170.0, 137.0)
        clean_items.append(
            {
                "type": "line",
                "role": "form_label",
                "bbox": bbox,
                "spans": [
                    {
                        "text": form_label,
                        "bbox": tuple(bbox),
                        "size": 18.9,
                        "font": force_font or "HYSMyeongJo-Medium",
                        "flags": 16,
                    }
                ],
            }
        )

    for title_item in [item for item in clean_items if item.get("role") == "subject_title"]:
        title_bbox = _item_bbox(title_item)
        for candidate in list(clean_items):
            if candidate is title_item or candidate.get("type") != "line":
                continue
            candidate_text = _line_text(candidate).strip()
            candidate_bbox = _item_bbox(candidate)
            overlap = max(
                0.0,
                min(title_bbox.y1, candidate_bbox.y1)
                - max(title_bbox.y0, candidate_bbox.y0),
            )
            if (
                candidate_text.startswith("(")
                and candidate_text.endswith(")")
                and overlap >= min(title_bbox.height, candidate_bbox.height) * 0.45
                and candidate_bbox.x0 >= title_bbox.x1 - 8.0
            ):
                title_item["spans"].extend(candidate.get("spans", []))
                title_bbox.include_rect(candidate_bbox)
                title_item["bbox"] = title_bbox
                clean_items.remove(candidate)

    clean_items.sort(key=lambda item: (_item_bbox(item).y0, _item_bbox(item).x0))
    rows: list[list[dict[str, Any]]] = []
    for item in clean_items:
        bbox = _item_bbox(item)
        placed = False
        for row in rows:
            row_bbox = _union_rect([_item_bbox(member) for member in row])
            overlap = max(0.0, min(row_bbox.y1, bbox.y1) - max(row_bbox.y0, bbox.y0))
            if overlap >= min(row_bbox.height, bbox.height) * 0.42:
                row.append(item)
                placed = True
                break
        if not placed:
            rows.append([item])
    rows.sort(key=lambda row: min(_item_bbox(item).y0 for item in row))

    segments: list[tuple[str, float, list[dict[str, Any]]]] = []
    previous_bottom = float(source_margin_top_pt)
    for row in rows:
        row.sort(key=lambda item: _item_bbox(item).x0)
        row_bbox = _union_rect([_item_bbox(item) for item in row])
        gap = max(0.0, row_bbox.y0 - previous_bottom)
        if gap >= 0.8:
            segments.append(("gap", gap, []))
        segments.append(("content", max(1.0, row_bbox.height), row))
        previous_bottom = max(previous_bottom, row_bbox.y1)

    source_table_height = table_height / HWP_PER_PT / max(0.01, coordinate_scale)
    trailing = source_margin_top_pt + source_table_height - previous_bottom
    if trailing >= 0.8:
        segments.append(("gap", trailing, []))
    if not segments:
        return 0

    if cell is None:
        attrs = {"pageBreak": "1"} if page_break else {}
        grid = doc.add_table(
            len(segments),
            3,
            width=table_width,
            height=table_height,
            border_fill_id_ref=no_border_fill,
            para_pr_id_ref=compact_para,
            **attrs,
        )
    else:
        grid = cell.add_table(
            len(segments),
            3,
            width=table_width,
            height=table_height,
            border_fill_id_ref=no_border_fill,
        )
    column_weights = (2.0, 4.0, 2.0)
    try:
        grid.set_column_widths(column_weights)
    except Exception:
        pass
    weight_total = sum(column_weights)
    column_widths = [int(round(table_width * weight / weight_total)) for weight in column_weights]
    column_widths[-1] = max(1, table_width - sum(column_widths[:-1]))
    row_heights = [
        max(_pt_to_hwp(1.0), _pt_to_hwp(height_pt * coordinate_scale))
        for _kind, height_pt, _row in segments
    ]
    row_heights[-1] = max(1, row_heights[-1] + table_height - sum(row_heights))
    source_table_width = table_width / HWP_PER_PT / max(0.01, coordinate_scale)
    source_boundaries = [
        source_margin_left_pt,
        source_margin_left_pt + source_table_width * 0.25,
        source_margin_left_pt + source_table_width * 0.75,
        source_margin_left_pt + source_table_width,
    ]

    count = 0
    for row_index, (kind, _height_pt, row) in enumerate(segments):
        for column_index in range(3):
            target = grid.cell(row_index, column_index)
            target.set_size(column_widths[column_index], row_heights[row_index])
            border_fill = (
                header_divider_border_fill
                if row_index == len(segments) - 1 and header_divider_border_fill
                else no_border_fill
            )
            _set_cell_border_fill(target, border_fill)
            _set_cell_margin(target, left_mm=0.0, right_mm=0.0, top_mm=0.0, bottom_mm=0.0)
            _clear_cell_paragraphs(target)
        if kind == "gap":
            continue

        by_column: list[list[dict[str, Any]]] = [[], [], []]
        for item in row:
            bbox = _item_bbox(item)
            center_x = (bbox.x0 + bbox.x1) / 2.0
            if center_x < page.rect.width * 0.30:
                column_index = 0
            elif center_x > page.rect.width * 0.70:
                column_index = 2
            else:
                column_index = 1
            by_column[column_index].append(item)

        for column_index, column_items in enumerate(by_column):
            if not column_items:
                continue
            target = grid.cell(row_index, column_index)
            column_items.sort(key=lambda item: (_item_bbox(item).y0, _item_bbox(item).x0))
            if column_index == 0:
                alignment = "LEFT"
                left_gap = max(
                    0.0,
                    min(_item_bbox(item).x0 for item in column_items)
                    - source_boundaries[column_index],
                )
                _set_cell_margin(
                    target,
                    left_mm=_pt_to_mm(left_gap * coordinate_scale),
                    right_mm=0.0,
                    top_mm=0.0,
                    bottom_mm=0.0,
                )
            elif column_index == 2:
                alignment = "RIGHT"
                right_gap = max(
                    0.0,
                    source_boundaries[column_index + 1]
                    - max(_item_bbox(item).x1 for item in column_items),
                )
                _set_cell_margin(
                    target,
                    left_mm=0.0,
                    right_mm=_pt_to_mm(right_gap * coordinate_scale),
                    top_mm=0.0,
                    bottom_mm=0.0,
                )
            else:
                alignment = "CENTER"
            row_para = _ensure_flow_para_format(
                doc,
                para_styles,
                alignment=alignment,
                line_spacing_percent=100,
            )
            for item in column_items:
                line = dict(item)
                line["spans"] = [
                    {**span, "preserve_size": True}
                    for span in item.get("spans", [])
                ]
                if _append_cell_line(
                    doc,
                    target,
                    line,
                    styles=styles,
                    para_pr_id_ref=row_para,
                    font_scale=font_scale,
                    force_font=force_font,
                ):
                    count += 1
    return count


def _append_header_snapshot(
    doc: HwpxDocument,
    page: fitz.Page,
    *,
    source_left_pt: float,
    source_right_pt: float,
    source_top_pt: float,
    source_bottom_pt: float,
    table_width: int,
    table_height: int,
    no_border_fill: str,
    compact_para: str,
    page_break: bool,
) -> int:
    """Embed the small running-header strip at source fidelity.

    Exam headers contain grade pills, form labels, page numbers and thin rules
    whose geometry is more important than editability.  Restricting the raster
    fallback to this narrow strip keeps all body content editable while
    preserving those details exactly.
    """
    clip = fitz.Rect(
        max(float(page.rect.x0), source_left_pt),
        max(float(page.rect.y0), source_top_pt),
        min(float(page.rect.x1), source_right_pt),
        min(float(page.rect.y1), source_bottom_pt),
    )
    if clip.width < 4.0 or clip.height < 4.0 or table_height <= 0:
        return 0
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), clip=clip, alpha=False)
        image_data = pix.tobytes("png")
    except Exception:
        return 0
    attrs = {"pageBreak": "1"} if page_break else {}
    table = doc.add_table(
        1,
        1,
        width=table_width,
        height=table_height,
        border_fill_id_ref=no_border_fill,
        para_pr_id_ref=compact_para,
        **attrs,
    )
    target = table.cell(0, 0)
    target.set_size(table_width, table_height)
    _set_cell_border_fill(target, no_border_fill)
    _set_cell_margin(target, left_mm=0.0, right_mm=0.0, top_mm=0.0, bottom_mm=0.0)
    _clear_cell_paragraphs(target)
    _set_cell_vertical_alignment(target, "TOP")
    item_id = doc.add_image(image_data, "png")
    paragraph = target.add_paragraph(
        "",
        para_pr_id_ref=compact_para,
        char_pr_id_ref="0",
    )
    paragraph.add_picture(
        item_id,
        width=max(1, table_width),
        height=max(1, table_height),
    )
    return 1


def _flow_subject_title(pdf_path: Path) -> str | None:
    stem = pdf_path.stem
    if "국어" in stem:
        return "국어 영역"
    if "영어" in stem:
        return "영어 영역"
    if "수학" in stem:
        variant = ""
        match = re.search(r"수학\s*([AB])", stem, re.IGNORECASE)
        if match:
            variant = f"({match.group(1).upper()}형)"
        return f"수학 영역{variant}"
    return None


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
    para_styles: dict[tuple[Any, ...], str],
    para_pr_id_ref: str,
    cell_width: int,
    border_fill_id_ref: str,
    image_border_fill_id_ref: str,
    coordinate_scale: float = 1.0,
    font_scale: float = 1.0,
    force_font: str | None = None,
    spacer_para_pr_id_ref: str | None = None,
    spacer_char_pr_id_ref: str | None = None,
    line_spacing_percent: int = _FLOW_BODY_LINE_SPACING,
    physical_gap_tables: bool = False,
) -> int:
    if block["type"] == "gap":
        height_pt = float(block.get("height_pt") or 0.0)
        # Moderate inter-question whitespace is already represented by normal
        # paragraph leading. Reserve physical spacer tables for genuinely
        # sparse layouts; using them for 1-2 line gaps over-shifts English text.
        minimum_gap = 110.0 if physical_gap_tables else 60.0
        if height_pt < minimum_gap:
            return 0
        gap_height = max(
            _pt_to_hwp(1.0),
            _pt_to_hwp(height_pt * coordinate_scale),
        )
        if physical_gap_tables:
            # Hancom/rhwp can collapse an oversized fixed-line paragraph inside
            # a vertically centred cell. An invisible table retains its height.
            _append_empty_flow_table(
                cell,
                width=max(1, cell_width - _pt_to_hwp(2.0 * coordinate_scale)),
                height=gap_height,
                border_fill_id_ref=image_border_fill_id_ref,
            )
        else:
            gap_para = doc.headers[0].ensure_paragraph_format(
                alignment="LEFT",
                line_spacing_percent=100,
                margins={"left": 0, "prev": 0, "next": 0},
            )
            para_prop = doc.headers[0].element.find(
                f".//{_hh('paraPr')}[@id='{gap_para}']"
            )
            line_spacing = (
                para_prop.find(_hh("lineSpacing")) if para_prop is not None else None
            )
            if line_spacing is not None:
                line_spacing.set("type", "FIXED")
                line_spacing.set("value", str(gap_height))
                line_spacing.set("unit", "HWPUNIT")
                doc.headers[0].mark_dirty()
            cell.add_paragraph(
                "\u00a0",
                para_pr_id_ref=gap_para,
                char_pr_id_ref=spacer_char_pr_id_ref or "0",
            )
        return 0
    before_gap_hwp = _pt_to_hwp(
        max(0.0, float(block.get("before_gap_pt") or 0.0)) * coordinate_scale
    )
    if block["type"] == "paragraph":
        lines = list(block.get("lines") or [])
        if not lines:
            return 0
        first_bbox = _item_bbox(lines[0])
        column_left = float(block.get("column_left_pt") or first_bbox.x0)
        left_margin, first_line_indent = _flow_paragraph_geometry_hwp(
            lines,
            column_left=column_left,
            cell_width=cell_width,
            coordinate_scale=coordinate_scale,
        )
        paragraph_spacing = _flow_paragraph_line_spacing_percent(
            lines,
            coordinate_scale=coordinate_scale,
            font_scale=font_scale,
            fallback=line_spacing_percent,
        )
        paragraph_para = _ensure_flow_para_format(
            doc,
            para_styles,
            alignment="JUSTIFY",
            line_spacing_percent=paragraph_spacing,
            left_margin_hwp=left_margin,
            prev_margin_hwp=before_gap_hwp,
            first_line_indent_hwp=first_line_indent,
        )
        rendered_font_size = _median_float(
            [
                _flow_size_for_span(span) * font_scale
                for line in lines
                for span in line.get("spans", [])
                if str(span.get("text") or "").strip()
            ],
            8.0 * font_scale,
        )
        line_height_hwp = _pt_to_hwp(
            max(6.0, rendered_font_size * paragraph_spacing / 100.0)
        )
        paragraph_added = _append_cell_paragraph_lines(
            doc,
            cell,
            lines,
            styles=styles,
            para_pr_id_ref=paragraph_para,
            font_scale=font_scale,
            force_font=force_font,
            line_width_hwp=max(1, cell_width - left_margin),
            line_height_hwp=line_height_hwp,
        )
        if paragraph_added and len(lines) > 1:
            _append_empty_flow_table(
                cell,
                width=max(1, cell_width - left_margin),
                height=(len(lines) - 1) * line_height_hwp,
                border_fill_id_ref=image_border_fill_id_ref,
            )
        return len(lines) if paragraph_added else 0
    if block["type"] == "line":
        line = block["line"]
        alignment, indent_hwp = _flow_line_layout_hwp(
            block,
            line,
            cell_width=cell_width,
            coordinate_scale=coordinate_scale,
        )
        line_para = _ensure_flow_para_format(
            doc,
            para_styles,
            alignment=alignment,
            line_spacing_percent=line_spacing_percent,
            left_margin_hwp=indent_hwp,
            prev_margin_hwp=before_gap_hwp,
        )
        return 1 if _append_cell_line(
            doc,
            cell,
            line,
            styles=styles,
            para_pr_id_ref=line_para,
            font_scale=font_scale,
            force_font=force_font,
        ) else 0
    if block["type"] == "native_table":
        return _append_native_flow_table(
            doc,
            cell,
            block,
            styles=styles,
            para_styles=para_styles,
            cell_width=cell_width,
            border_fill_id_ref=border_fill_id_ref,
            coordinate_scale=coordinate_scale,
            font_scale=font_scale,
            force_font=force_font,
        )
    if block["type"] == "image":
        image = block["image"]
        bbox = _item_bbox(image)
        column_left = float(block.get("column_left_pt") or bbox.x0)
        indent_hwp = _pt_to_hwp(
            min(36.0, max(0.0, bbox.x0 - column_left)) * coordinate_scale
        )
        indent_hwp = min(
            indent_hwp,
            max(0, cell_width - _pt_to_hwp(48.0)),
        )
        return 1 if _append_cell_image(
            doc,
            cell,
            image,
            cell_width=cell_width,
            para_pr_id_ref=para_pr_id_ref,
            border_fill_id_ref=image_border_fill_id_ref,
            coordinate_scale=coordinate_scale,
            para_styles=para_styles,
            left_margin_hwp=indent_hwp,
            before_gap_hwp=before_gap_hwp,
        ) else 0

    box_items = list(block.get("lines", []))
    lines = [line for line in box_items if line.get("type") == "line" and _line_text(line)]
    nested_tables = [item for item in box_items if item.get("type") == "native_table"]
    near_page_bottom = bool(block.get("near_page_bottom"))
    content_font_scale = font_scale * (
        0.92 if near_page_bottom or nested_tables else 1.0
    )
    if not lines and not nested_tables:
        return 0
    rect = block.get("rect")
    if rect is None:
        rect = _union_rect([_item_bbox(item) for item in box_items])
    indent_hwp = _flow_box_host_indent_hwp(block, cell_width, coordinate_scale)
    table_width = _flow_box_table_width_hwp(
        block, lines, cell_width, indent_hwp, coordinate_scale
    )
    table_height = _flow_box_table_height_hwp(block, lines, coordinate_scale)
    if nested_tables:
        # rhwp reserves an extra baseline around nested tables.  Add one row
        # of breathing room so the final table row and following choices do
        # not clip against the source passage-box boundary.
        table_height += _pt_to_hwp(16.0)
    host_para = _ensure_flow_para_format(
        doc,
        para_styles,
        alignment="LEFT",
        line_spacing_percent=100,
        left_margin_hwp=indent_hwp,
        prev_margin_hwp=before_gap_hwp,
    )
    host = cell.add_paragraph("", para_pr_id_ref=host_para, char_pr_id_ref="0")
    table = host.add_table(1, 1, width=table_width, height=table_height, border_fill_id_ref=border_fill_id_ref)
    nested = table.cell(0, 0)
    nested.set_size(table_width, table_height)
    _set_cell_vertical_alignment(nested, "CENTER")
    padding = _flow_box_padding_pt(rect, lines)
    pad_left, pad_right, pad_top, pad_bottom = padding
    _set_cell_margin(
        nested,
        left_mm=_pt_to_mm(pad_left * coordinate_scale),
        right_mm=_pt_to_mm(pad_right * coordinate_scale),
        top_mm=_pt_to_mm(pad_top * coordinate_scale),
        bottom_mm=_pt_to_mm(pad_bottom * coordinate_scale),
    )
    _clear_cell_paragraphs(nested)
    count = 0
    line_spacing = _flow_box_line_spacing_percent(lines)
    if near_page_bottom:
        line_spacing = min(line_spacing, 135)
    inner_width = max(
        1,
        table_width - _pt_to_hwp((pad_left + pad_right) * coordinate_scale),
    )
    box_flow_blocks: list[dict[str, Any]] = []
    for item in box_items:
        if item.get("type") == "native_table":
            box_flow_blocks.append(item)
        else:
            box_flow_blocks.append(
                {
                    "type": "line",
                    "line": item,
                    "column_left_pt": rect.x0 + pad_left,
                    "column_right_pt": rect.x1 - pad_right,
                }
            )
    box_flow_blocks = _group_flow_prose_blocks(box_flow_blocks)
    for line_block in box_flow_blocks:
        if line_block.get("type") == "native_table":
            count += _append_native_flow_table(
                doc,
                nested,
                {
                    "type": "native_table",
                    "native_table": line_block,
                    "column_left_pt": rect.x0 + pad_left,
                },
                styles=styles,
                para_styles=para_styles,
                cell_width=inner_width,
                border_fill_id_ref=border_fill_id_ref,
                coordinate_scale=coordinate_scale,
                font_scale=content_font_scale,
                force_font=force_font,
            )
            continue
        if line_block.get("type") == "paragraph":
            paragraph_lines = list(line_block.get("lines") or [])
            left_margin, first_line_indent = _flow_paragraph_geometry_hwp(
                paragraph_lines,
                column_left=rect.x0 + pad_left,
                cell_width=inner_width,
                coordinate_scale=coordinate_scale,
            )
            paragraph_spacing = _flow_paragraph_line_spacing_percent(
                paragraph_lines,
                coordinate_scale=coordinate_scale,
                font_scale=content_font_scale,
                fallback=line_spacing,
            )
            line_para = _ensure_flow_para_format(
                doc,
                para_styles,
                alignment="JUSTIFY",
                line_spacing_percent=paragraph_spacing,
                left_margin_hwp=left_margin,
                first_line_indent_hwp=first_line_indent,
            )
            rendered_font_size = _median_float(
                [
                    _flow_size_for_span(span) * content_font_scale
                    for paragraph_line in paragraph_lines
                    for span in paragraph_line.get("spans", [])
                    if str(span.get("text") or "").strip()
                ],
                8.0 * content_font_scale,
            )
            line_height_hwp = _pt_to_hwp(
                max(6.0, rendered_font_size * paragraph_spacing / 100.0)
            )
            paragraph_added = _append_cell_paragraph_lines(
                doc,
                nested,
                paragraph_lines,
                styles=styles,
                para_pr_id_ref=line_para,
                font_scale=content_font_scale,
                force_font=force_font,
                line_width_hwp=max(1, inner_width - left_margin),
                line_height_hwp=line_height_hwp,
            )
            if paragraph_added:
                count += len(paragraph_lines)
            continue
        line = line_block["line"]
        alignment = _flow_box_line_alignment(line, rect, padding)
        line_para = _ensure_flow_para_format(
            doc,
            para_styles,
            alignment=alignment,
            line_spacing_percent=line_spacing,
            left_margin_hwp=_flow_box_line_indent_hwp(
                line, rect, padding, alignment, coordinate_scale
            ),
        )
        if _append_cell_line(
            doc,
            nested,
            line,
            styles=styles,
            para_pr_id_ref=line_para,
            font_scale=content_font_scale,
            force_font=force_font,
        ):
            count += 1
    trailing_balance = 0 if nested_tables else _flow_box_trailing_balance_hwp(
        lines,
        table_height_hwp=table_height,
        padding=padding,
        line_spacing_percent=line_spacing,
        coordinate_scale=coordinate_scale,
        font_scale=content_font_scale,
    )
    if trailing_balance > 0:
        _append_empty_flow_table(
            nested,
            width=max(1, table_width - _pt_to_hwp(2.0 * coordinate_scale)),
            height=trailing_balance,
            border_fill_id_ref=image_border_fill_id_ref,
        )
    return count


def _flow_column_balance_gap_pt(
    blocks: list[dict[str, Any]],
    *,
    body_height_hwp: int,
    coordinate_scale: float,
    english_body: bool,
) -> float:
    """Balance centered flow cells with an invisible trailing gap."""
    scale = max(0.01, float(coordinate_scale))
    body_height_pt = max(0.0, body_height_hwp / HWP_PER_PT)
    line_count = sum(1 for block in blocks if block.get("type") == "line")
    gap_height_pt = sum(
        max(0.0, float(block.get("height_pt") or 0.0)) * scale
        for block in blocks
        if block.get("type") == "gap"
    )
    if line_count == 0 or any(block.get("type") == "image" for block in blocks):
        return 0.0
    target_gap_pt = gap_height_pt + (9.0 if english_body else 12.0)
    if any(block.get("type") == "box" for block in blocks):
        target_gap_pt *= 0.60

    target_gap_pt = min(target_gap_pt, body_height_pt * 0.35)
    if target_gap_pt < 1.0:
        return 0.0
    return target_gap_pt / scale


def write_pdf_flow_hwpx(
    pdf_path: str | Path,
    output_path: str | Path,
    *,
    max_pages: int | None = None,
    boxed_passages: bool = True,
    target_a4: bool = False,
    rasterize_tables: bool = True,
    preserve_repeated_headers: bool = False,
    force_font: str | None = None,
    subject_title_override: str | None = None,
) -> dict[str, int]:
    """Write a Hancom-viewer-safe editable HWPX using regular paragraphs/tables."""
    started_at = time.perf_counter()
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = HwpxDocument.new()
    header = doc.headers[0]
    _ensure_pdf_font_faces(header)
    _apply_exam_base_text_profile(header)
    no_border_fill = _ensure_no_border_fill(header)
    box_border_fill = _ensure_box_border_fill(header)
    column_divider_border_fill = _ensure_column_divider_border_fill(header)
    header_divider_border_fill = _ensure_header_divider_border_fill(header)
    compact_para = header.ensure_paragraph_format(
        alignment="LEFT",
        line_spacing_percent=100,
        margins={"prev": 0, "next": 0},
    )
    spacer_para = header.ensure_paragraph_format(
        alignment="LEFT",
        line_spacing_percent=100,
        margins={"prev": 0, "next": 0},
    )
    spacer_cp = doc.ensure_run_style(
        font=force_font or "HY신명조",
        size=1.0,
        bold=False,
    )
    _apply_char_metrics(header, [spacer_cp], ratio=100, spacing=0)

    styles: dict[tuple[str, float, bool], str] = {}
    para_styles: dict[tuple[Any, ...], str] = {}
    page_count = 0
    line_count = 0
    boxed_count = 0
    image_count = 0
    source_text_lines = 0
    source_body_text_fragments: list[str] = []
    page_times_ms: list[int] = []
    axis_line_count = 0
    dense_vector_pages = 0

    with fitz.open(pdf_path) as pdf_doc:
        if not pdf_doc:
            raise ValueError(f"empty PDF: {pdf_path}")
        first = pdf_doc[0]
        first_page_lines = _iter_text_lines(first)
        first_page_text = " ".join(_line_text(line) for line in first_page_lines)
        form_label = next(
            (label for label in ("홀수형", "짝수형") if label in first_page_text),
            None,
        )
        source_width_mm = _pt_to_mm(first.rect.width)
        source_height_mm = _pt_to_mm(first.rect.height)
        if target_a4:
            width_mm = 210.0
            height_mm = 297.0
            coordinate_scale = width_mm / max(1.0, source_width_mm)
            margin_left_mm = 20.0
            margin_right_mm = 20.0
            margin_top_mm = 20.0
            margin_bottom_mm = 18.0
        else:
            width_mm = source_width_mm
            height_mm = source_height_mm
            coordinate_scale = 1.0
            margin_left_mm = 7.0
            margin_right_mm = 7.0
            margin_top_mm = 7.0
            margin_bottom_mm = 7.0
        subject_title = subject_title_override or _flow_subject_title(pdf_path)
        english_body = "english" in pdf_path.stem.lower() or "영어" in pdf_path.stem
        font_scale = coordinate_scale * (
            1.0 if english_body else 1.08
        )
        body_line_spacing = (
            _FLOW_ENGLISH_BODY_LINE_SPACING
            if english_body
            else _FLOW_BODY_LINE_SPACING
        )
        body_para = header.ensure_paragraph_format(
            alignment="LEFT",
            line_spacing_percent=body_line_spacing,
            margins={"prev": 0, "next": 0},
        )
        body_width_mm = max(10.0, width_mm - margin_left_mm - margin_right_mm)
        table_width = _mm_to_hwp(body_width_mm)
        cell_width = max(1, table_width // 2)
        margin_top_pt = margin_top_mm * 72.0 / 25.4 / coordinate_scale
        margin_left_pt = margin_left_mm * 72.0 / 25.4 / coordinate_scale
        margin_right_pt = margin_right_mm * 72.0 / 25.4 / coordinate_scale
        margin_bottom_pt = margin_bottom_mm * 72.0 / 25.4 / coordinate_scale
        page_orientation = _pdf_page_orientation(first)

        doc.set_page_size(
            width=_mm_to_hwp(width_mm),
            height=_mm_to_hwp(height_mm),
            orientation=page_orientation,
        )
        doc.set_page_margins(
            left=_mm_to_hwp(margin_left_mm),
            right=_mm_to_hwp(margin_right_mm),
            top=_mm_to_hwp(margin_top_mm),
            bottom=_mm_to_hwp(margin_bottom_mm),
        )

        total_pages = len(pdf_doc) if max_pages is None else min(len(pdf_doc), max_pages)
        for page_index in range(total_pages):
            page_started_at = time.perf_counter()
            page = pdf_doc[page_index]
            page_text_lines = (
                first_page_lines
                if page_index == 0
                else _iter_text_lines(page)
            )
            footer_lines = [
                line for line in page_text_lines if _is_flow_footer_line(page, line)
            ]
            page_drawings = page.get_drawings()
            page_axis_lines = _flow_axis_line_count(page_drawings)
            axis_line_count += page_axis_lines
            dense_vector_pages += int(page_axis_lines > _MAX_FLOW_LAYOUT_AXIS_LINES)
            page_dark_pixels = (
                _page_dark_pixels(page)
                if boxed_passages or not rasterize_tables
                else None
            )
            body_top = _page_body_top(page)
            if body_top <= margin_top_pt:
                body_top = margin_top_pt
            table_image_items = (
                _iter_flow_table_images(page, page_drawings)
                if rasterize_tables
                else []
            )
            native_table_items = (
                []
                if rasterize_tables
                else _flow_native_table_items(
                    page,
                    page_text_lines,
                    page_drawings,
                )
            )
            if not rasterize_tables:
                for raster_table in _raster_native_table_items(
                    page,
                    page_text_lines,
                    page_dark_pixels,
                ):
                    raster_bbox = _item_bbox(raster_table)
                    if any(
                        (_item_bbox(existing) & raster_bbox).get_area()
                        >= min(_item_bbox(existing).get_area(), raster_bbox.get_area()) * 0.80
                        for existing in native_table_items
                    ):
                        continue
                    native_table_items.append(raster_table)
            table_regions = [
                *(_item_bbox(item) for item in table_image_items),
                *(_item_bbox(item) for item in native_table_items),
            ]
            native_image_items = []
            for item in _merge_flow_images(_iter_flow_images(page)):
                image_bbox = _item_bbox(item)
                image_center = fitz.Point(
                    (image_bbox.x0 + image_bbox.x1) / 2.0,
                    (image_bbox.y0 + image_bbox.y1) / 2.0,
                )
                covered_by_table = any(
                    region.contains(image_center)
                    and image_bbox.width <= region.width * 1.25
                    and image_bbox.height <= region.height * 1.25
                    for region in table_regions
                )
                if not covered_by_table:
                    native_image_items.append(item)
            native_image_items = _expand_flow_image_frames(
                page,
                native_image_items,
                page_drawings,
            )
            native_image_items, textual_image_regions = _convert_textual_image_regions(
                page,
                native_image_items,
                preserve_editable_text=True,
                text_lines=page_text_lines,
            )
            excluded_text_regions = table_regions
            page_text_lines = [line for line in page_text_lines if _line_text(line)]
            source_text_lines += len(page_text_lines)
            source_body_text_fragments.extend(
                fragment
                for line in page_text_lines
                if _item_bbox(line).y1 >= body_top - 1
                and not _is_flow_footer_line(page, line)
                for fragment in [_pdf_output_text(_line_text(line)).strip()]
                if fragment
            )
            line_items = [
                {"type": "line", "bbox": fitz.Rect(line["bbox"]), "spans": line["spans"]}
                for line in page_text_lines
                if not _is_flow_footer_line(page, line)
                and not _inside_any_region(fitz.Rect(line["bbox"]), excluded_text_regions)
            ]
            image_items = native_image_items + table_image_items
            image_count += len(image_items)
            all_items = line_items + image_items + native_table_items
            header_items = [item for item in all_items if _item_bbox(item).y1 < body_top - 1]
            body_items = [item for item in all_items if _item_bbox(item).y1 >= body_top - 1]
            body_items = _merge_same_row_flow_lines(page, body_items)
            repeated_header_spacer = 0
            header_gap_pt = max(0.0, body_top - margin_top_pt)
            if header_items and page_index > 0 and not preserve_repeated_headers:
                repeated_header_spacer = _pt_to_hwp(
                    min(header_gap_pt, 140.0) * coordinate_scale
                )
                header_items = []
            elif header_items and not _has_substantial_flow_header(page, header_items):
                body_items = all_items
                header_items = []
                body_top = margin_top_pt
                header_gap_pt = 0.0
            body_font_scale = (
                coordinate_scale
                if (
                    page_index > 0
                    and header_items
                    and _has_full_flow_header(page, header_items)
                )
                else font_scale
            )
            header_height = _pt_to_hwp(header_gap_pt * coordinate_scale)
            body_height_pt = max(24.0, page.rect.height - body_top - margin_bottom_pt)
            body_height = _pt_to_hwp(
                body_height_pt * coordinate_scale
                if target_a4
                else min(body_height_pt, page.rect.height * 0.62)
            )
            if target_a4:
                # Leave enough room for Hancom's native table-anchor metrics.
                # A near-full-height body can otherwise move wholesale to the
                # next page even though its source geometry fits on A4.
                # KICE high-school senior forms carry a slightly taller anchor
                # stack than the education-office form, so retain the larger
                # reserve there to keep the footer inside the printable area.
                anchor_reserve_pt = (
                    36.0 if "high3" in str(pdf_path).lower() else 20.0
                )
                body_height = max(
                    _pt_to_hwp(24),
                    body_height - _pt_to_hwp(anchor_reserve_pt),
                )
            header_row_height = 0
            if header_items:
                header_row_height = max(
                    _pt_to_hwp(24 * coordinate_scale),
                    min(header_height, _pt_to_hwp(140 * coordinate_scale)),
                )
            elif repeated_header_spacer > 0:
                header_row_height = max(
                    _pt_to_hwp(4 * coordinate_scale), repeated_header_spacer
                )
            has_header_row = header_row_height > 0
            starts_page = False
            if header_items:
                header_added = 0
                used_header_snapshot = False
                if target_a4:
                    header_added = _append_header_snapshot(
                        doc,
                        page,
                        source_left_pt=margin_left_pt,
                        source_right_pt=page.rect.width - margin_right_pt,
                        source_top_pt=margin_top_pt,
                        source_bottom_pt=body_top,
                        table_width=table_width,
                        table_height=header_row_height,
                        no_border_fill=no_border_fill,
                        compact_para=compact_para,
                        page_break=page_index > 0,
                    )
                    if header_added:
                        used_header_snapshot = True
                        image_count += 1
                        line_count += sum(
                            1 for item in header_items if item.get("type") == "line"
                        )
                if not header_added:
                    header_added = _append_header_content_to_cell(
                        doc,
                        None,
                        page,
                        header_items,
                        table_width=table_width,
                        table_height=header_row_height,
                        no_border_fill=no_border_fill,
                        compact_para=compact_para,
                        styles=styles,
                        para_styles=para_styles,
                        coordinate_scale=coordinate_scale,
                        font_scale=coordinate_scale,
                        force_font=force_font,
                        source_margin_left_pt=margin_left_pt,
                        source_margin_top_pt=margin_top_pt,
                        subject_title=subject_title,
                        form_label=form_label,
                        page_break=page_index > 0,
                        header_divider_border_fill=header_divider_border_fill,
                    )
                if not used_header_snapshot:
                    line_count += header_added
                starts_page = True
            elif repeated_header_spacer > 0:
                _append_spacer_table(
                    doc,
                    table_width=table_width,
                    table_height=header_row_height,
                    no_border_fill=no_border_fill,
                    compact_para=compact_para,
                    page_break=page_index > 0,
                )
                starts_page = True
            table_attrs = (
                {"pageBreak": "1"}
                if page_index > 0 and not starts_page
                else {}
            )
            table = doc.add_table(
                1,
                2,
                width=table_width,
                height=body_height,
                border_fill_id_ref=no_border_fill,
                para_pr_id_ref=compact_para,
                **table_attrs,
            )
            body_cells = [table.cell(0, column) for column in (0, 1)]
            for body_cell in body_cells:
                body_cell.set_size(cell_width, body_height)
                _clear_cell_paragraphs(body_cell)
                # Hancom/rhwp collapse sequential cell paragraphs at TOP in
                # this fixed-height page-table layout. CENTER keeps their
                # native flow order; explicit gap tables determine the visible
                # question positions on sparse pages.
                _set_cell_vertical_alignment(body_cell, "CENTER")
            left_cell, right_cell = body_cells
            _set_cell_border_fill(left_cell, column_divider_border_fill)
            _set_cell_margin(left_cell, left_mm=0.4, right_mm=2.3, top_mm=0.0, bottom_mm=0.0)
            _set_cell_margin(right_cell, left_mm=2.3, right_mm=0.4, top_mm=0.0, bottom_mm=0.0)

            boxes = (
                _flow_box_rects(
                    page,
                    page_text_lines,
                    page_drawings,
                    page_dark_pixels,
                )
                if boxed_passages
                else []
            )
            if boxed_passages:
                for region in textual_image_regions:
                    if any(_rects_close(region, existing) for existing in boxes):
                        continue
                    boxes.append(fitz.Rect(region))
                boxes.sort(key=lambda rect: (rect.y0, rect.x0, rect.width * rect.height))
            if boxes and (image_items or native_table_items):
                image_rects = [
                    *(_item_bbox(item) for item in image_items),
                    *(_item_bbox(item) for item in native_table_items),
                ]
                boxes = [
                    box
                    for box in boxes
                    if not any(
                        box.intersects(image_rect)
                        and (box & image_rect).get_area() >= box.get_area() * 0.72
                        for image_rect in image_rects
                    )
                ]
            columns = _flow_column_blocks(
                page,
                body_items,
                boxes,
                preserve_gaps=target_a4,
            )
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
                        para_styles=para_styles,
                        para_pr_id_ref=body_para,
                        cell_width=cell_width,
                        border_fill_id_ref=box_border_fill,
                        image_border_fill_id_ref=no_border_fill,
                        coordinate_scale=coordinate_scale,
                        font_scale=body_font_scale,
                        force_font=force_font,
                        spacer_para_pr_id_ref=spacer_para,
                        spacer_char_pr_id_ref=spacer_cp,
                        line_spacing_percent=body_line_spacing,
                        physical_gap_tables=target_a4 and not english_body,
                    )
            if target_a4 and footer_lines:
                footer_bounds = _union_rect([_item_bbox(line) for line in footer_lines])
                footer_top = max(
                    float(page.rect.y0),
                    footer_bounds.y0 - 3.0,
                )
                footer_bottom = min(
                    float(page.rect.y1),
                    footer_bounds.y1 + 3.0,
                )
                footer_height_pt = (
                    max(4.0, footer_bottom - footer_top) * coordinate_scale
                )
                if "high3" in str(pdf_path).lower():
                    footer_height_pt = max(4.0, footer_height_pt - 4.0)
                footer_height = _pt_to_hwp(footer_height_pt)
                footer_added = _append_header_snapshot(
                    doc,
                    page,
                    source_left_pt=margin_left_pt,
                    source_right_pt=page.rect.width - margin_right_pt,
                    source_top_pt=footer_top,
                    source_bottom_pt=footer_bottom,
                    table_width=table_width,
                    table_height=footer_height,
                    no_border_fill=no_border_fill,
                    compact_para=compact_para,
                    page_break=False,
                )
                image_count += int(bool(footer_added))
            page_count += 1
            page_times_ms.append(round((time.perf_counter() - page_started_at) * 1000))

    _prepare_hancom_compatibility(doc)
    _save_hancom_compatible_document(doc, output_path)
    editable_coverage = 1.0
    compact_fragments = [re.sub(r"\s+", "", fragment) for fragment in source_body_text_fragments]
    source_body_text_chars = sum(len(fragment) for fragment in compact_fragments)
    matched_body_text_chars = source_body_text_chars
    if source_body_text_chars > 0:
        output_plain_text = re.sub(r"\s+", "", _structured_hwpx_plain_text(output_path))
        matched_body_text_chars = sum(
            len(fragment)
            for fragment in compact_fragments
            if fragment in output_plain_text
        )
        editable_coverage = min(1.0, matched_body_text_chars / source_body_text_chars)
    return {
        "pages": page_count,
        "source_text_lines": source_text_lines,
        "flow_lines": line_count,
        "editable_text_coverage_ratio": round(editable_coverage, 4),
        "source_text_char_count": source_body_text_chars,
        "matched_text_char_count": matched_body_text_chars,
        "boxed_blocks": boxed_count,
        "images": image_count,
        "axis_lines": axis_line_count,
        "dense_vector_pages": dense_vector_pages,
        "slowest_page_ms": max(page_times_ms, default=0),
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000),
    }


def _structured_pdf_template_key(filename: str, exam_title: str) -> str:
    name = filename.lower()
    if "국어" in name or "korean" in name:
        return "kice_korean"
    if "영어" in name or "english" in name:
        return "kice_english"
    if "수학" in name or "math" in name:
        return "kice_math"
    hint = f"{filename} {exam_title}".lower()
    if "수학" in hint or "math" in hint:
        return "kice_math"
    if "영어" in hint or "english" in hint:
        return "kice_english"
    return "kice_korean"


def _structured_hwpx_counts(path: Path) -> dict[str, int]:
    counts = {
        "native_equations": 0,
        "draw_text_boxes": 0,
        "paragraphs": 0,
        "tables": 0,
        "page_breaks": 0,
        "column_breaks": 0,
        "two_column_page_tables": 0,
        "running_header_tables": 0,
    }
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not re.fullmatch(r"Contents/section\d+\.xml", name):
                continue
            root = etree.fromstring(archive.read(name))
            counts["native_equations"] += len(root.findall(f".//{{{HP}}}equation"))
            counts["draw_text_boxes"] += len(root.findall(f".//{{{HP}}}drawText"))
            counts["paragraphs"] += len(root.findall(f".//{{{HP}}}p"))
            counts["tables"] += len(root.findall(f".//{{{HP}}}tbl"))
            for table in root.findall(f".//{{{HP}}}tbl"):
                parent = table.getparent()
                grandparent = parent.getparent() if parent is not None else None
                great_grandparent = grandparent.getparent() if grandparent is not None else None
                if not (
                    parent is not None
                    and grandparent is not None
                    and great_grandparent is root
                    and etree.QName(parent).localname == "run"
                    and etree.QName(grandparent).localname == "p"
                ):
                    continue
                size = table.find(_q("sz"))
                try:
                    height = int(size.get("height") or "0") if size is not None else 0
                    columns = int(table.get("colCnt") or "0")
                except ValueError:
                    continue
                if columns == 2 and height > 40000:
                    counts["two_column_page_tables"] += 1
                elif columns >= 3 and height < 20000:
                    counts["running_header_tables"] += 1
                elif (
                    columns == 1
                    and height < 20000
                    and table.find(f".//{_q('pic')}") is not None
                ):
                    counts["running_header_tables"] += 1
            counts["page_breaks"] += sum(
                1 for paragraph in root.findall(f".//{{{HP}}}p") if paragraph.get("pageBreak") == "1"
            )
            counts["column_breaks"] += sum(
                1 for paragraph in root.findall(f".//{{{HP}}}p") if paragraph.get("columnBreak") == "1"
            )
    return counts


def _structured_hwpx_plain_text(path: Path) -> str:
    chunks: list[str] = []
    with zipfile.ZipFile(path, "r") as archive:
        for name in archive.namelist():
            if not re.fullmatch(r"Contents/section\d+\.xml", name):
                continue
            root = etree.fromstring(archive.read(name))
            chunks.extend(
                str(node.text or "")
                for node in root.findall(f".//{{{HP}}}t")
                if str(node.text or "")
            )
    return re.sub(r"\s+", "", "".join(chunks))


def _structured_editable_text_fragments(items: list[dict[str, Any]]) -> list[str]:
    fragments: list[str] = []
    for item in items:
        values = [
            str(item.get("stem") or ""),
            *(str(choice or "") for choice in item.get("choices") or []),
            *(
                str(line or "")
                for block in (item.get("condition_blocks") or [])
                if isinstance(block, dict)
                for line in (block.get("lines") or [])
            ),
            *(
                str(cell or "")
                for table in (item.get("native_tables") or [])
                if isinstance(table, dict)
                for row in (table.get("text_rows") or [])
                for cell in row
            ),
        ]
        for value in values:
            for line in value.splitlines():
                plain = "".join(
                    segment
                    for segment, is_math in math_text.split_math_text(line)
                    if not is_math
                )
                compact = re.sub(r"\s+", "", plain)
                if len(compact) >= 4:
                    fragments.append(compact)
    return fragments


def _structured_page_continuation_text(
    page: fitz.Page,
    *,
    first_problem_top_px: float,
    page_height_px: int,
    column_index: int,
) -> str:
    """Recover editable preamble text above the first problem in one column."""
    if page_height_px <= 0:
        return ""
    first_top_ratio = float(first_problem_top_px) / float(page_height_px)
    if first_top_ratio <= 0.15:
        return ""
    scale = float(page_height_px) / max(1.0, float(page.rect.height))
    start_y = float(page.rect.height) * 0.13
    end_y = max(start_y, float(first_problem_top_px) / max(0.01, scale) - 4.0)
    selected_lines: list[tuple[float, float, str]] = []
    for block in page.get_text("dict").get("blocks") or []:
        if int(block.get("type") or 0) != 0:
            continue
        for line in block.get("lines") or []:
            bbox = line.get("bbox") or []
            if len(bbox) != 4:
                continue
            try:
                left, top, right, bottom = (float(value) for value in bbox)
            except (TypeError, ValueError):
                continue
            if bottom < start_y or top >= end_y:
                continue
            is_left_column = (left + right) / 2.0 < float(page.rect.width) / 2.0
            if is_left_column != (column_index == 1):
                continue
            text = "".join(str(span.get("text") or "") for span in line.get("spans") or []).strip()
            if not text:
                continue
            compact = re.sub(r"\s+", "", text)
            if (
                re.fullmatch(r"\d{1,2}", compact)
                or compact in {"홀수형", "짝수형", "국어영역", "영어영역", "수학영역"}
                or "저작권은한국교육과정평가원" in compact
            ):
                continue
            item = (top, left, text)
            selected_lines.append(item)
    return "\n".join(text for _top, _left, text in sorted(selected_lines))


def _structured_page_continuation_figures(
    page: fitz.Page,
    *,
    first_problem_top_px: float,
    page_height_px: int,
    column_index: int,
) -> list[tuple[bytes, fitz.Rect]]:
    """Extract source figure images that belong to a column preamble."""
    if page_height_px <= 0:
        return []
    scale = float(page_height_px) / max(1.0, float(page.rect.height))
    start_y = float(page.rect.height) * 0.13
    end_y = max(start_y, float(first_problem_top_px) / max(0.01, scale) - 4.0)
    figures: list[tuple[bytes, fitz.Rect]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for info in page.get_image_info(xrefs=True):
        values = info.get("bbox") or []
        if len(values) != 4:
            continue
        rect = fitz.Rect(*(float(value) for value in values))
        if rect.width < 24.0 or rect.height < 20.0:
            continue
        if rect.y0 < start_y or rect.y1 > end_y + 2.0:
            continue
        is_left_column = (rect.x0 + rect.x1) / 2.0 < float(page.rect.width) / 2.0
        if is_left_column != (column_index == 1):
            continue
        key = tuple(int(round(value * 10.0)) for value in (rect.x0, rect.y0, rect.x1, rect.y1))
        if key in seen:
            continue
        seen.add(key)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), clip=rect, alpha=False)
        figures.append((pixmap.tobytes("png"), rect))
    return figures


def _structured_page_postamble_text(
    page: fitz.Page,
    *,
    last_problem_bottom_px: float,
    page_height_px: int,
    column_index: int,
) -> str:
    """Recover a final-column instruction block below the last problem."""
    if page_height_px <= 0:
        return ""
    scale = float(page_height_px) / max(1.0, float(page.rect.height))
    start_y = float(last_problem_bottom_px) / max(0.01, scale) + 4.0
    end_y = float(page.rect.height) * 0.92
    if start_y >= end_y:
        return ""
    selected_lines: list[tuple[float, float, str]] = []
    for block in page.get_text("dict").get("blocks") or []:
        if int(block.get("type") or 0) != 0:
            continue
        for line in block.get("lines") or []:
            bbox = line.get("bbox") or []
            if len(bbox) != 4:
                continue
            left, top, right, bottom = (float(value) for value in bbox)
            if bottom < start_y or top >= end_y:
                continue
            is_left_column = (left + right) / 2.0 < float(page.rect.width) / 2.0
            if is_left_column != (column_index == 1):
                continue
            text = "".join(
                str(span.get("text") or "") for span in line.get("spans") or []
            ).strip()
            if not text:
                continue
            compact = re.sub(r"\s+", "", text)
            if (
                re.fullmatch(r"\d{1,2}", compact)
                or "저작권" in compact
                or "한국교육과정평가원" in compact
            ):
                continue
            selected_lines.append((top, left, text))
    text = "\n".join(value for _top, _left, value in sorted(selected_lines))
    compact = re.sub(r"\s+", "", text)
    if "확인사항" not in compact and "답안지" not in compact:
        return ""
    return text


def _structured_pdf_body_lines(page: fitz.Page) -> list[dict[str, Any]]:
    """Return editable KICE body lines in source page/column order."""
    start_y = float(page.rect.height) * 0.13
    end_y = float(page.rect.height) * 0.92
    lines: list[dict[str, Any]] = []
    for block in page.get_text("dict").get("blocks") or []:
        if int(block.get("type") or 0) != 0:
            continue
        for line in block.get("lines") or []:
            bbox = line.get("bbox") or []
            if len(bbox) != 4:
                continue
            try:
                left, top, right, bottom = (float(value) for value in bbox)
            except (TypeError, ValueError):
                continue
            if bottom < start_y or top >= end_y:
                continue
            spans = list(line.get("spans") or [])
            text = "".join(str(span.get("text") or "") for span in spans).strip()
            if not text:
                continue
            compact = re.sub(r"\s+", "", text)
            if re.fullmatch(r"\d{1,2}", compact):
                continue
            if any(
                token in compact
                for token in (
                    "\uad6d\uc5b4\uc601\uc5ed",
                    "\uc601\uc5b4\uc601\uc5ed",
                    "\uc218\ud559\uc601\uc5ed",
                    "\ud640\uc218\ud615",
                    "\uc9dd\uc218\ud615",
                    "\uc81c1\uad50\uc2dc",
                    "\uc800\uc791\uad8c",
                    "\ud55c\uad6d\uad50\uc721\uacfc\uc815\ud3c9\uac00\uc6d0",
                )
            ):
                continue
            style = "heading" if re.match(
                r"^(?:\d{1,2}\s*\.|\[\s*\d{1,2}\s*[~\-]\s*\d{1,2}\s*\]|<\s*\ubcf4\uae30\s*>)",
                text,
            ) else "body"
            midpoint = (left + right) / 2.0
            font_sizes = [float(span.get("size") or 0.0) for span in spans if float(span.get("size") or 0.0) > 0]
            lines.append(
                {
                    "top": top,
                    "left": left,
                    "right": right,
                    "bottom": bottom,
                    "text": text,
                    "style": style,
                    "font_size": statistics.median(font_sizes) if font_sizes else 11.2,
                    "column_index": 1 if midpoint < float(page.rect.width) / 2.0 else 2,
                }
            )

    merged: list[dict[str, Any]] = []
    for column_index in (1, 2):
        groups: list[list[dict[str, Any]]] = []
        ordered = sorted(
            (line for line in lines if int(line["column_index"]) == column_index),
            key=lambda item: (
                (float(item["top"]) + float(item["bottom"])) / 2.0,
                float(item["left"]),
            ),
        )
        for line in ordered:
            if groups:
                first = groups[-1][0]
                first_center = (float(first["top"]) + float(first["bottom"])) / 2.0
                line_center = (float(line["top"]) + float(line["bottom"])) / 2.0
                overlap = max(
                    0.0,
                    min(float(first["bottom"]), float(line["bottom"]))
                    - max(float(first["top"]), float(line["top"])),
                )
                min_height = min(
                    float(first["bottom"]) - float(first["top"]),
                    float(line["bottom"]) - float(line["top"]),
                )
                if abs(first_center - line_center) <= 2.2 or overlap >= min_height * 0.55:
                    groups[-1].append(line)
                    continue
            groups.append([line])

        for group in groups:
            group.sort(key=lambda item: float(item["left"]))
            text_parts: list[str] = []
            previous_right: float | None = None
            median_size = statistics.median(float(item["font_size"]) for item in group)
            for item in group:
                if previous_right is not None:
                    gap = max(0.0, float(item["left"]) - previous_right)
                    if gap > median_size * 0.35:
                        space_width = max(2.0, median_size * 0.34)
                        text_parts.append(" " * max(1, int(round(gap / space_width))))
                text_parts.append(str(item["text"]))
                previous_right = max(previous_right or float(item["right"]), float(item["right"]))
            merged.append(
                {
                    "top": min(float(item["top"]) for item in group),
                    "left": min(float(item["left"]) for item in group),
                    "right": max(float(item["right"]) for item in group),
                    "bottom": max(float(item["bottom"]) for item in group),
                    "text": "".join(text_parts).strip(),
                    "style": "heading" if any(item["style"] == "heading" for item in group) else "body",
                    "font_size": median_size,
                    "column_index": column_index,
                }
            )
    return sorted(
        merged,
        key=lambda item: (int(item["column_index"]), float(item["top"]), float(item["left"])),
    )


def _structured_pdf_text_flow_items(
    pdf_path: Path,
    regular_items: list[dict[str, Any]],
    *,
    page_limit: int | None,
) -> list[dict[str, Any]]:
    """Reflow Korean/English PDF text directly without positioned text boxes."""
    page_info_by_number: dict[int, dict[str, Any]] = {}
    figures_by_page_column: dict[tuple[int, int], list[tuple[float, list[str]]]] = {}
    for item in regular_items:
        source_page = int(item.get("source_page") or 0)
        layout = item.get("layout") if isinstance(item.get("layout"), dict) else {}
        page_info = layout.get("page") if isinstance(layout.get("page"), dict) else {}
        if source_page > 0 and page_info:
            page_info_by_number.setdefault(source_page, page_info)
        image_paths = [str(path) for path in item.get("image_paths") or [] if str(path)]
        if not image_paths:
            continue
        bbox = layout.get("bbox_px") or []
        fallback_column = max(1, min(2, int(layout.get("column_index") or 1)))
        if len(bbox) == 4:
            fallback_top_px = float(bbox[1]) + float(bbox[3]) * 0.35
        else:
            fallback_top_px = 0.0
        figure_boxes = layout.get("figure_boxes_px") or []
        page_width_px = float(page_info.get("width_px") or 0.0)
        for figure_index, image_path in enumerate(image_paths):
            figure_box = figure_boxes[figure_index] if figure_index < len(figure_boxes) else []
            if len(figure_box) == 4:
                figure_left, figure_top, figure_width, _figure_height = (
                    float(value) for value in figure_box
                )
                figure_center = figure_left + figure_width / 2.0
                column_index = (
                    1
                    if page_width_px <= 0 or figure_center < page_width_px / 2.0
                    else 2
                )
                figure_top_px = figure_top
            else:
                column_index = fallback_column
                figure_top_px = fallback_top_px
            figures_by_page_column.setdefault((source_page, column_index), []).append(
                (figure_top_px, [image_path])
            )

    def text_item(
        *,
        source_page: int,
        column_index: int,
        page_info: dict[str, Any],
        page: fitz.Page,
        lines: list[dict[str, Any]],
    ) -> dict[str, Any]:
        page_height_px = int(page_info.get("height_px") or round(float(page.rect.height) * 150.0 / 72.0))
        first_top = float(lines[0]["top"]) if lines else 0.0
        last_bottom = float(lines[-1]["top"]) if lines else first_top
        scale = float(page_height_px) / max(1.0, float(page.rect.height))
        source_lines = [
            {
                "top_px": float(line["top"]) * scale,
                "left_px": float(line["left"]) * scale,
                "right_px": float(line["right"]) * scale,
                "bottom_px": float(line["bottom"]) * scale,
                "font_size_pt": float(line["font_size"]),
                "style": str(line["style"]),
            }
            for line in lines
        ]
        return {
            "number": "",
            "title": "",
            "stem": "\n".join(str(line["text"]) for line in lines),
            "choices": [],
            "image_paths": [],
            "tables": [],
            "source_page": source_page,
            "layout": {
                "source_page": source_page,
                "column_index": column_index,
                "column_count": 2,
                "source_text_flow": True,
                "line_styles": [str(line["style"]) for line in lines],
                "source_lines": source_lines,
                "page": page_info,
                "bbox_px": [
                    0.0 if column_index == 1 else float(page_info.get("width_px") or 0) / 2.0,
                    first_top * scale,
                    float(page_info.get("width_px") or 0) / 2.0,
                    max(0.0, (last_bottom - first_top) * scale),
                ],
            },
        }

    output: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as source_pdf:
        final_page = min(len(source_pdf), page_limit or len(source_pdf))
        for source_page in range(1, final_page + 1):
            page = source_pdf[source_page - 1]
            page_info = page_info_by_number.get(source_page) or {
                "number": source_page,
                "width_px": round(float(page.rect.width) * 150.0 / 72.0),
                "height_px": round(float(page.rect.height) * 150.0 / 72.0),
            }
            page_height_px = int(page_info.get("height_px") or 1)
            point_per_px = float(page.rect.height) / max(1.0, float(page_height_px))
            body_lines = _structured_pdf_body_lines(page)
            for column_index in (1, 2):
                column_lines = [
                    line for line in body_lines if int(line["column_index"]) == column_index
                ]
                cursor = 0
                figures = sorted(figures_by_page_column.get((source_page, column_index), []))
                for figure_top_px, image_paths in figures:
                    figure_top = figure_top_px * point_per_px
                    split = cursor
                    while split < len(column_lines) and float(column_lines[split]["top"]) < figure_top:
                        split += 1
                    if split > cursor:
                        output.append(
                            text_item(
                                source_page=source_page,
                                column_index=column_index,
                                page_info=page_info,
                                page=page,
                                lines=column_lines[cursor:split],
                            )
                        )
                    output.append(
                        {
                            "number": "",
                            "title": "",
                            "stem": "",
                            "choices": [],
                            "image_paths": image_paths,
                            "tables": [],
                            "source_page": source_page,
                            "layout": {
                                "source_page": source_page,
                                "column_index": column_index,
                                "column_count": 2,
                                "source_figure_flow": True,
                                "page": page_info,
                                "bbox_px": [0.0, figure_top_px, 0.0, 0.0],
                            },
                        }
                    )
                    cursor = split
                if cursor < len(column_lines):
                    output.append(
                        text_item(
                            source_page=source_page,
                            column_index=column_index,
                            page_info=page_info,
                            page=page,
                            lines=column_lines[cursor:],
                        )
                    )
    return output


def _merge_compact_math_stem_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line:
            continue
        operator_continuation = bool(re.match(r"^\$\s*[+\-=/]", line))
        short_prompt_continuation = bool(
            merged
            and "$" in merged[-1]
            and len(re.sub(r"\s+", "", merged[-1] + line)) <= 72
            and line.startswith(("의 값", "이면", "일 경우"))
        )
        if merged and (operator_continuation or short_prompt_continuation):
            merged[-1] = merged[-1].rstrip() + ("" if operator_continuation else " ") + line
        else:
            merged.append(line)
    return merged


def _pdf_geometry_line_rect_px(line: dict[str, Any]) -> fitz.Rect | None:
    rects: list[fitz.Rect] = []
    for key in ("pdf_line_chars", "pdf_line_spans"):
        for item in line.get(key) or []:
            values = item.get("bbox") or []
            if len(values) != 4:
                continue
            rect = fitz.Rect(float(values[0]), float(values[1]), float(values[2]), float(values[3]))
            if rect.width > 0 and rect.height > 0:
                rects.append(rect)
        if rects:
            break
    return _union_rect(rects) if rects else None


def _structured_math_component_geometry_px(
    geometry: list[dict[str, Any]],
) -> dict[str, float]:
    lines: list[tuple[str, fitz.Rect]] = []
    for raw in geometry:
        rect = _pdf_geometry_line_rect_px(raw)
        if rect is None:
            continue
        text = math_text.normalize_recognized_math_layout_text(str(raw.get("text") or "")).strip()
        if text:
            lines.append((text, rect))
    choice_rects = [
        rect
        for text, rect in lines
        if re.match(r"^[\u2460-\u2464]", text)
    ]
    if not choice_rects:
        return {}
    choice_top = min(rect.y0 for rect in choice_rects)
    stem_rects = [rect for _text, rect in lines if rect.y0 < choice_top - 1.0]
    result = {
        "choice_top": float(choice_top),
        "choice_bottom": float(max(rect.y1 for rect in choice_rects)),
    }
    if stem_rects:
        result["stem_bottom"] = float(max(rect.y1 for rect in stem_rects))
    return result


def _structured_math_line_anchors_px(
    geometry: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for raw in geometry:
        rect = _pdf_geometry_line_rect_px(raw)
        if rect is None:
            continue
        text = math_text.normalize_recognized_math_layout_text(str(raw.get("text") or "")).strip()
        if not text:
            continue
        anchors.append(
            {
                "text": text,
                "top": float(rect.y0),
                "bottom": float(rect.y1),
            }
        )
    anchors.sort(key=lambda item: (float(item["top"]), float(item["bottom"])))
    return anchors


def _raw_pdf_line_geometry(line: dict[str, Any]) -> dict[str, Any]:
    rect = fitz.Rect(line.get("bbox") or (0, 0, 0, 0))
    chars: list[dict[str, Any]] = []
    spans: list[dict[str, Any]] = []
    for span_index, span in enumerate(line.get("spans") or []):
        span_chars: list[dict[str, Any]] = []
        for char_index, char in enumerate(span.get("chars") or []):
            item = {
                "c": str(char.get("c") or ""),
                "bbox": [float(value) for value in (char.get("bbox") or (0, 0, 0, 0))],
                "span": span_index,
                "index": char_index,
                "font": str(span.get("font") or ""),
                "size": float(span.get("size") or 0.0),
                "flags": int(span.get("flags") or 0),
            }
            chars.append(item)
            span_chars.append(item)
        spans.append(
            {
                "text": str(span.get("text") or ""),
                "index": span_index,
                "bbox": [float(value) for value in (span.get("bbox") or (0, 0, 0, 0))],
                "font": str(span.get("font") or ""),
                "size": float(span.get("size") or 0.0),
                "flags": int(span.get("flags") or 0),
                "chars": span_chars,
            }
        )
    return {
        "text": math_text.normalize_recognized_math_layout_text(_line_text(line)),
        "bbox_px": [float(rect.x0), float(rect.y0), float(rect.width), float(rect.height)],
        "pdf_line_chars": chars,
        "pdf_line_spans": spans,
    }


def _math_condition_box_rects(page: fitz.Page) -> list[fitz.Rect]:
    boxes = list(_flow_box_rects(page))
    for drawing in page.get_drawings():
        rect_value = drawing.get("rect")
        if rect_value is None:
            continue
        rect = fitz.Rect(rect_value)
        if (
            rect.width < page.rect.width * 0.18
            or rect.width > page.rect.width * 0.58
            or rect.height < 20
            or rect.height > page.rect.height * 0.34
        ):
            continue
        horizontal = 0
        vertical = 0
        for drawing_item in drawing.get("items") or []:
            if not drawing_item or drawing_item[0] != "l":
                continue
            p0, p1 = drawing_item[1], drawing_item[2]
            if abs(float(p1.y) - float(p0.y)) <= 0.7 and abs(float(p1.x) - float(p0.x)) >= rect.width * 0.75:
                horizontal += 1
            elif abs(float(p1.x) - float(p0.x)) <= 0.7 and abs(float(p1.y) - float(p0.y)) >= rect.height * 0.70:
                vertical += 1
        if horizontal >= 2 and vertical >= 2 and not any(_rects_close(rect, existing) for existing in boxes):
            boxes.append(rect)
    boxes.sort(key=lambda rect: (rect.y0, rect.x0))
    return boxes


def _attach_structured_math_condition_blocks(pdf_path: Path, items: list[dict[str, Any]]) -> None:
    from .pdf_math_geometry import reconstruct_condition_math_lines

    with fitz.open(pdf_path) as source_pdf:
        for item in items:
            source_page = int(item.get("source_page") or 0)
            if source_page <= 0 or source_page > len(source_pdf):
                continue
            layout = item.get("layout") if isinstance(item.get("layout"), dict) else {}
            bbox_px = layout.get("bbox_px") or []
            page_info = layout.get("page") if isinstance(layout.get("page"), dict) else {}
            page_width_px = float(page_info.get("width_px") or 0.0)
            page_height_px = float(page_info.get("height_px") or 0.0)
            if len(bbox_px) != 4 or page_width_px <= 0 or page_height_px <= 0:
                continue
            page = source_pdf[source_page - 1]
            problem_rect = fitz.Rect(
                float(bbox_px[0]) / page_width_px * page.rect.width,
                float(bbox_px[1]) / page_height_px * page.rect.height,
                (float(bbox_px[0]) + float(bbox_px[2])) / page_width_px * page.rect.width,
                (float(bbox_px[1]) + float(bbox_px[3])) / page_height_px * page.rect.height,
            )
            page_lines = _iter_text_lines(page)
            blocks: list[dict[str, Any]] = []
            for box in _math_condition_box_rects(page):
                center = fitz.Point((box.x0 + box.x1) / 2.0, (box.y0 + box.y1) / 2.0)
                if not problem_rect.contains(center):
                    continue
                contained = []
                for line in page_lines:
                    line_rect = fitz.Rect(line["bbox"])
                    line_center = fitz.Point(
                        (line_rect.x0 + line_rect.x1) / 2.0,
                        (line_rect.y0 + line_rect.y1) / 2.0,
                    )
                    if box.contains(line_center):
                        contained.append(line)
                normalized = [
                    math_text.normalize_recognized_math_layout_text(_line_text(line))
                    for line in contained
                ]
                if not any(
                    re.match(r"^(?:\([\uac00-\ud7a3]\)|[\u3131-\u314e][.)])", value.strip())
                    or "\ubcf4\uae30" in value
                    for value in normalized
                ):
                    continue
                geometry = [_raw_pdf_line_geometry(line) for line in contained]
                lines = reconstruct_condition_math_lines(geometry)
                if not lines:
                    continue
                blocks.append(
                    {
                        "lines": lines,
                        "bbox_pt": [float(box.x0), float(box.y0), float(box.width), float(box.height)],
                        "top_px": float(box.y0) / max(1.0, float(page.rect.height)) * page_height_px,
                    }
                )
            if blocks:
                item["condition_blocks"] = blocks


def _attach_structured_math_native_tables(
    pdf_path: Path,
    items: list[dict[str, Any]],
) -> None:
    """Attach source grid tables to the problem whose geometry contains them."""
    items_by_page: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        items_by_page.setdefault(int(item.get("source_page") or 0), []).append(item)

    with fitz.open(pdf_path) as source_pdf:
        for source_page, page_items in items_by_page.items():
            if source_page <= 0 or source_page > len(source_pdf):
                continue
            page = source_pdf[source_page - 1]
            candidates = _flow_native_table_items(page)
            if not candidates:
                continue
            problem_rects: list[tuple[dict[str, Any], fitz.Rect, dict[str, Any]]] = []
            for item in page_items:
                layout = item.get("layout") if isinstance(item.get("layout"), dict) else {}
                bbox_px = layout.get("bbox_px") or []
                page_info = layout.get("page") if isinstance(layout.get("page"), dict) else {}
                page_width_px = float(page_info.get("width_px") or 0.0)
                page_height_px = float(page_info.get("height_px") or 0.0)
                if len(bbox_px) != 4 or page_width_px <= 0 or page_height_px <= 0:
                    continue
                rect = fitz.Rect(
                    float(bbox_px[0]) / page_width_px * page.rect.width,
                    float(bbox_px[1]) / page_height_px * page.rect.height,
                    (float(bbox_px[0]) + float(bbox_px[2]))
                    / page_width_px
                    * page.rect.width,
                    (float(bbox_px[1]) + float(bbox_px[3]))
                    / page_height_px
                    * page.rect.height,
                )
                problem_rects.append((item, rect, page_info))

            for candidate in candidates:
                table_rect = fitz.Rect(candidate.get("grid_bbox") or candidate.get("bbox"))
                center = fitz.Point(
                    (table_rect.x0 + table_rect.x1) / 2.0,
                    (table_rect.y0 + table_rect.y1) / 2.0,
                )
                owner = next(
                    (
                        (item, page_info)
                        for item, problem_rect, page_info in problem_rects
                        if problem_rect.contains(center)
                    ),
                    None,
                )
                if owner is None:
                    continue
                item, page_info = owner
                page_height_px = float(page_info.get("height_px") or 0.0)
                text_rows: list[list[str]] = []
                for row in candidate.get("cells") or []:
                    text_row: list[str] = []
                    for cell_spans in row:
                        cell_lines = _flow_lines_from_spans(list(cell_spans))
                        text = " ".join(
                            _line_text(line).strip()
                            for line in cell_lines
                            if _line_text(line).strip()
                        )
                        text_row.append(
                            math_text.normalize_recognized_math_layout_text(text)
                        )
                    text_rows.append(text_row)
                if not text_rows or not any(any(cell for cell in row) for row in text_rows):
                    continue
                item.setdefault("native_tables", []).append(
                    {
                        "bbox_pt": [
                            float(table_rect.x0),
                            float(table_rect.y0),
                            float(table_rect.width),
                            float(table_rect.height),
                        ],
                        "top_px": (
                            float(table_rect.y0)
                            / max(1.0, float(page.rect.height))
                            * page_height_px
                        ),
                        "bottom_px": (
                            float(table_rect.y1)
                            / max(1.0, float(page.rect.height))
                            * page_height_px
                        ),
                        "x_boundaries": [
                            float(value) for value in candidate.get("x_boundaries") or []
                        ],
                        "y_boundaries": [
                            float(value) for value in candidate.get("y_boundaries") or []
                        ],
                        "text_rows": text_rows,
                    }
                )


def _write_structured_math_page_tables(
    pdf_path: Path,
    output_path: Path,
    title: str,
    items: list[dict[str, Any]],
    *,
    max_pages: int | None,
) -> None:
    from . import storage

    doc = HwpxDocument.new()
    header = doc.headers[0]
    _ensure_pdf_font_faces(header)
    _apply_exam_base_text_profile(header)
    no_border_fill = _ensure_no_border_fill(header)
    box_border_fill = _ensure_box_border_fill(header)
    column_divider_border_fill = _ensure_column_divider_border_fill(header)
    header_divider_border_fill = _ensure_header_divider_border_fill(header)
    compact_para = header.ensure_paragraph_format(
        alignment="LEFT",
        line_spacing_percent=100,
        margins={"prev": 0, "next": 0},
    )
    body_para = header.ensure_paragraph_format(
        alignment="LEFT",
        line_spacing_percent=105,
        margins={"prev": 0, "next": 0},
    )
    center_para = header.ensure_paragraph_format(
        alignment="CENTER",
        line_spacing_percent=115,
        margins={"prev": 0, "next": 0},
    )
    right_para = header.ensure_paragraph_format(
        alignment="RIGHT",
        line_spacing_percent=100,
        margins={"prev": 0, "next": 0},
    )
    header_left_para = header.ensure_paragraph_format(
        alignment="LEFT",
        line_spacing_percent=100,
        margins={"prev": 0, "next": 0},
    )
    body_cp = doc.ensure_run_style(font="HY신명조", size=8.0, bold=False)
    bold_cp = doc.ensure_run_style(font="HY신명조", size=8.0, bold=True)
    small_cp = doc.ensure_run_style(font="HY신명조", size=7.2, bold=False)
    running_page_cp = doc.ensure_run_style(font="HY신명조", size=16.0, bold=True)
    running_title_cp = doc.ensure_run_style(font="HY신명조", size=15.5, bold=True)
    running_form_cp = doc.ensure_run_style(font="HY신명조", size=10.5, bold=True)
    _apply_char_metrics(
        header,
        [body_cp, bold_cp, small_cp, running_page_cp, running_title_cp, running_form_cp],
        ratio=_FLOW_CHAR_RATIO,
        spacing=_FLOW_CHAR_SPACING,
    )
    header_styles: dict[tuple[str, float, bool], str] = {}
    para_styles: dict[tuple[Any, ...], str] = {}
    equation_counter = [0]

    width_mm = 210.0
    height_mm = 297.0
    margin_left_mm = 20.0
    margin_right_mm = 20.0
    margin_top_mm = 20.0
    margin_bottom_mm = 18.0
    table_width = _mm_to_hwp(width_mm - margin_left_mm - margin_right_mm)
    cell_width = table_width // 2
    doc.set_page_size(
        width=_mm_to_hwp(width_mm),
        height=_mm_to_hwp(height_mm),
        orientation="WIDELY",
    )
    doc.set_page_margins(
        left=_mm_to_hwp(margin_left_mm),
        right=_mm_to_hwp(margin_right_mm),
        top=_mm_to_hwp(margin_top_mm),
        bottom=_mm_to_hwp(margin_bottom_mm),
    )

    items_by_page: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        items_by_page.setdefault(int(item.get("source_page") or 0), []).append(item)

    def append_math_paragraph(cell: Any, text: str, *, center: bool = False, small: bool = False) -> int:
        value = str(text or "").strip()
        if not value:
            return 0
        para_pr = center_para if center else body_para
        char_pr = small_cp if small else body_cp
        paragraph = cell.add_paragraph(
            "",
            para_pr_id_ref=para_pr,
            char_pr_id_ref=char_pr,
        )
        for run in list(paragraph.element.findall(_q("run"))):
            paragraph.element.remove(run)
        runs: list[tuple[str, str]] = []
        match = re.match(r"^(\d+\.)\s+(.+)$", value, re.DOTALL)
        if match:
            runs.append((match.group(1) + "  ", bold_cp))
            if match.group(2):
                runs.append((match.group(2), char_pr))
        else:
            runs.append((value, char_pr))
        _append_pdf_runs(
            paragraph.element,
            runs,
            equation_counter=equation_counter,
            native_math=True,
        )
        equation_height = _direct_native_equation_height(paragraph.element)
        line_height = max(1000, equation_height)
        if paragraph.element.find(f"{_q('linesegarray')}/{_q('lineseg')}") is None:
            cell_size = cell.element.find(_q("cellSz"))
            line_width = _positive_int(cell_size.get("width")) if cell_size is not None else None
            _append_text_box_lineseg_hwp(paragraph.element, line_width or table_width, line_height)
        return line_height

    def append_choices(cell: Any, choices: list[str], width: int) -> int:
        if not choices:
            return 0
        markers = ("①", "②", "③", "④", "⑤")
        if len(choices) <= 5:
            equation_height = 0
            equation_widths: list[int] = []
            for choice in choices:
                choice_width = 0
                for segment, is_math in math_text.split_math_text(str(choice or "")):
                    if not is_math:
                        choice_width += _pt_to_hwp(
                            sum(7.2 if ord(char) > 127 else 3.8 for char in segment)
                        )
                        continue
                    script = _hancom_eqn_script(segment)
                    if script:
                        equation_width, current_height = _equation_size(script)
                        choice_width += int(round(equation_width * 0.8))
                        equation_height = max(equation_height, current_height)
                choice_width += _pt_to_hwp(9.0)
                equation_widths.append(choice_width)
            base_choice_height = max(
                _pt_to_hwp(15),
                equation_height + (_pt_to_hwp(4.0) if equation_height else 0),
            )
            columns = len(choices)
            widest = max(equation_widths or [0])
            while columns > 1 and widest > width / max(1, columns) * 0.88:
                columns = 3 if columns > 3 else columns - 1
            cell_content_width = max(1, width // max(1, columns) - _pt_to_hwp(2.0))
            maximum_wraps = max(
                1,
                max(
                    int(math.ceil(choice_width / cell_content_width))
                    for choice_width in (equation_widths or [0])
                ),
            )
            choice_height = base_choice_height * maximum_wraps
            rows = max(1, int(math.ceil(len(choices) / max(1, columns))))
            choice_table = cell.add_table(
                rows,
                columns,
                width=max(1, width),
                height=choice_height * rows,
                border_fill_id_ref=no_border_fill,
            )
            try:
                choice_table.set_column_widths([1] * columns)
            except Exception:
                pass
            choice_width = max(1, width // columns)
            for row_index in range(rows):
                for column_index in range(columns):
                    target = choice_table.cell(row_index, column_index)
                    target.set_size(choice_width, choice_height)
                    _set_cell_border_fill(target, no_border_fill)
                    _set_cell_margin(target, left_mm=0.0, right_mm=0.0, top_mm=0.0, bottom_mm=0.0)
                    _clear_cell_paragraphs(target)
            for index, choice in enumerate(choices):
                target = choice_table.cell(index // columns, index % columns)
                append_math_paragraph(
                    target,
                    f"{markers[index]} {choice}",
                    center=True,
                    small=True,
                )
            # Hancom 2024 requires every table cell to contain at least one
            # paragraph. A 5-choice 2x3 grid otherwise leaves the sixth cell's
            # subList empty, which can terminate Hancom while opening the file.
            for index in range(len(choices), rows * columns):
                target = choice_table.cell(index // columns, index % columns)
                target.set_text("", split_paragraphs=True)
            return choice_height * rows
        total_height = 0
        for index, choice in enumerate(choices):
            marker = markers[index] if index < len(markers) else f"{index + 1}."
            total_height += append_math_paragraph(cell, f"{marker} {choice}", small=True)
        return total_height

    def append_figure(cell: Any, item: dict[str, Any], figure_index: int, width: int, page: fitz.Page) -> int:
        image_paths = list(item.get("image_paths") or [])
        if figure_index >= len(image_paths):
            return 0
        full_path = storage.resolve_data_image_path(image_paths[figure_index])
        if full_path is None:
            return 0
        try:
            image_data = _png_from_extracted_image(full_path.read_bytes(), full_path.suffix.lstrip("."))
        except Exception:
            return 0
        layout = item.get("layout") if isinstance(item.get("layout"), dict) else {}
        figure_boxes = list(layout.get("figure_boxes_px") or [])
        page_info = layout.get("page") if isinstance(layout.get("page"), dict) else {}
        page_width_px = float(page_info.get("width_px") or 0.0)
        page_height_px = float(page_info.get("height_px") or 0.0)
        desired_width = width * 0.54
        desired_height = desired_width * 0.55
        if figure_index < len(figure_boxes) and page_width_px > 0 and page_height_px > 0:
            box = figure_boxes[figure_index]
            if len(box) == 4:
                desired_width = (
                    float(box[2]) / page_width_px * page.rect.width * coordinate_scale * HWP_PER_PT
                )
                desired_height = (
                    float(box[3]) / page_height_px * page.rect.height * coordinate_scale * HWP_PER_PT
                )
        picture_width = max(_pt_to_hwp(18), min(int(desired_width), width - _pt_to_hwp(6)))
        picture_height = max(_pt_to_hwp(12), int(desired_height))
        item_id = doc.add_image(image_data, "png")
        paragraph = cell.add_paragraph(
            "",
            para_pr_id_ref=center_para,
            char_pr_id_ref=body_cp,
        )
        paragraph.add_picture(item_id, width=picture_width, height=picture_height)
        # Hancom reserves the full height of this inline picture. A synthetic
        # spacer here counts the image twice and can create a physical page.
        return picture_height

    def append_native_math_table(
        cell: Any,
        item: dict[str, Any],
        table_index: int,
        width: int,
    ) -> int:
        native_tables = list(item.get("native_tables") or [])
        if table_index >= len(native_tables):
            return 0
        table_item = native_tables[table_index]
        text_rows = [list(row) for row in table_item.get("text_rows") or []]
        if not text_rows:
            return 0
        row_count = len(text_rows)
        column_count = max((len(row) for row in text_rows), default=0)
        if row_count <= 0 or column_count <= 0:
            return 0
        x_boundaries = [float(value) for value in table_item.get("x_boundaries") or []]
        y_boundaries = [float(value) for value in table_item.get("y_boundaries") or []]
        source_widths = (
            [
                max(1.0, x_boundaries[index + 1] - x_boundaries[index])
                for index in range(column_count)
            ]
            if len(x_boundaries) == column_count + 1
            else [1.0] * column_count
        )
        source_heights = (
            [
                max(1.0, y_boundaries[index + 1] - y_boundaries[index])
                for index in range(row_count)
            ]
            if len(y_boundaries) == row_count + 1
            else [18.0] * row_count
        )
        source_width = sum(source_widths)
        table_width = min(
            max(_pt_to_hwp(72.0), _pt_to_hwp(source_width * coordinate_scale)),
            max(1, width - _pt_to_hwp(6.0)),
        )
        width_total = max(1.0, sum(source_widths))
        column_widths = [
            max(1, int(round(table_width * source_width / width_total)))
            for source_width in source_widths
        ]
        column_widths[-1] = max(1, table_width - sum(column_widths[:-1]))
        row_heights = [
            max(_pt_to_hwp(15.0), _pt_to_hwp(value * coordinate_scale))
            for value in source_heights
        ]
        table_height = sum(row_heights)
        host_para = _ensure_flow_para_format(
            doc,
            para_styles,
            alignment="LEFT",
            line_spacing_percent=100,
            left_margin_hwp=max(0, (width - table_width) // 2),
        )
        host = cell.add_paragraph(
            "",
            para_pr_id_ref=host_para,
            char_pr_id_ref=small_cp,
        )
        table = host.add_table(
            row_count,
            column_count,
            width=table_width,
            height=table_height,
            border_fill_id_ref=box_border_fill,
        )
        try:
            table.set_column_widths(source_widths)
        except Exception:
            pass
        for row_index in range(row_count):
            row = text_rows[row_index]
            for column_index in range(column_count):
                target = table.cell(row_index, column_index)
                target.set_size(column_widths[column_index], row_heights[row_index])
                _set_cell_border_fill(target, box_border_fill)
                _set_cell_margin(
                    target,
                    left_mm=0.25,
                    right_mm=0.25,
                    top_mm=0.1,
                    bottom_mm=0.1,
                )
                _clear_cell_paragraphs(target)
                value = str(row[column_index] if column_index < len(row) else "").strip()
                if value:
                    append_math_paragraph(target, value, center=True, small=True)
                else:
                    target.set_text("", split_paragraphs=True)
        return table_height

    def append_running_header(
        *,
        page_number: int,
        header_height: int,
        subject: str,
        form: str,
    ) -> None:
        table_attrs = {"pageBreak": "1"} if page_number > 1 else {}
        table = doc.add_table(
            1,
            3,
            width=table_width,
            height=header_height,
            border_fill_id_ref=no_border_fill,
            para_pr_id_ref=compact_para,
            **table_attrs,
        )
        weights = (2, 4, 2)
        try:
            table.set_column_widths(weights)
        except Exception:
            pass
        widths = [table_width // 4, table_width // 2, table_width - (table_width // 4 * 3)]
        page_on_right = page_number % 2 == 1
        labels = (
            (form, subject, str(page_number))
            if page_on_right
            else (str(page_number), subject, form)
        )
        para_ids = (header_left_para, center_para, right_para)
        char_ids = (
            running_form_cp if page_on_right else running_page_cp,
            running_title_cp,
            running_page_cp if page_on_right else running_form_cp,
        )
        for column_index in range(3):
            target = table.cell(0, column_index)
            target.set_size(widths[column_index], header_height)
            _set_cell_border_fill(target, header_divider_border_fill)
            _set_cell_margin(
                target,
                left_mm=0.0,
                right_mm=0.0,
                top_mm=7.0,
                bottom_mm=0.0,
            )
            _clear_cell_paragraphs(target)
            paragraph = target.add_paragraph(
                labels[column_index],
                para_pr_id_ref=para_ids[column_index],
                char_pr_id_ref=char_ids[column_index],
            )
            _append_text_box_lineseg_hwp(
                paragraph.element,
                widths[column_index],
                _pt_to_hwp(18.0),
            )

    def append_problem(cell: Any, item: dict[str, Any], width: int, page: fitz.Page) -> int:
        layout = item.get("layout") if isinstance(item.get("layout"), dict) else {}
        stem_lines = _merge_compact_math_stem_lines(str(item.get("stem") or "").splitlines())
        problem_number = str(item.get("number") or "").strip()
        if stem_lines and problem_number.isdigit():
            first_line = stem_lines[0]
            first_line = re.sub(
                rf"^\$\s*{re.escape(problem_number)}\.\s*",
                "$",
                first_line,
            )
            first_line = re.sub(
                rf"^{re.escape(problem_number)}\.\s*",
                "",
                first_line,
            )
            stem_lines[0] = f"{problem_number}. {first_line.lstrip()}"
        condition_blocks = [
            block for block in (item.get("condition_blocks") or []) if isinstance(block, dict)
        ]
        content_height = 0
        insertion_index = len(stem_lines)
        if condition_blocks:
            for index, line in enumerate(stem_lines):
                if ("영역을" in line and "라 하자" in line) or (
                    "다음 조건" in line and "만족" in line and line.rstrip().endswith(".")
                ):
                    insertion_index = index + 1
                    if "영역을" in line and "라 하자" in line:
                        break

        def append_condition_blocks() -> int:
            total_height = 0
            for block in condition_blocks:
                bbox_pt = block.get("bbox_pt") or []
                source_height = float(bbox_pt[3]) if len(bbox_pt) == 4 else 36.0
                source_width = float(bbox_pt[2]) if len(bbox_pt) == 4 else 0.0
                block_height = max(
                    _pt_to_hwp(24.0),
                    _pt_to_hwp(source_height * coordinate_scale),
                )
                block_width = min(
                    width,
                    max(
                        _pt_to_hwp(72.0),
                        _pt_to_hwp(source_width * coordinate_scale)
                        if source_width > 0
                        else width,
                    ),
                )
                block_indent = max(0, (width - block_width) // 2)
                host_para = _ensure_flow_para_format(
                    doc,
                    para_styles,
                    alignment="LEFT",
                    line_spacing_percent=100,
                    left_margin_hwp=block_indent,
                )
                host = cell.add_paragraph(
                    "",
                    para_pr_id_ref=host_para,
                    char_pr_id_ref=body_cp,
                )
                box_table = host.add_table(
                    1,
                    1,
                    width=max(1, block_width),
                    height=block_height,
                    border_fill_id_ref=box_border_fill,
                )
                box_cell = box_table.cell(0, 0)
                box_cell.set_size(block_width, block_height)
                _set_cell_border_fill(box_cell, box_border_fill)
                _set_cell_margin(
                    box_cell,
                    left_mm=1.5,
                    right_mm=1.5,
                    top_mm=0.8,
                    bottom_mm=0.8,
                )
                _clear_cell_paragraphs(box_cell)
                text_height = 0
                for line in block.get("lines") or []:
                    text_height += append_math_paragraph(box_cell, str(line or ""))
                reserved_height = max(block_height, text_height + _mm_to_hwp(1.6))
                if reserved_height != block_height:
                    table_size = box_table.element.find(_q("sz"))
                    if table_size is not None:
                        table_size.set("height", str(reserved_height))
                    box_cell.set_size(block_width, reserved_height)
                    box_table.mark_dirty()
                total_height += reserved_height
            return total_height

        expanded_lines: list[str] = []
        for line in stem_lines:
            if "\\begin{pmatrix}" in line and line.count("$") >= 2:
                closing = line.find("$", line.find("$") + 1)
                trailing = line[closing + 1 :].strip() if closing >= 0 else ""
                if trailing:
                    expanded_lines.extend([line[: closing + 1].rstrip(), trailing])
                    continue
            sentence_parts = [part.strip() for part in re.split(r"(?<=\.)\s+(?=\$)", line) if part.strip()]
            expanded_lines.extend(sentence_parts or [line])
        if len(expanded_lines) != len(stem_lines) and insertion_index < len(stem_lines):
            insertion_index += len(expanded_lines) - len(stem_lines)
        stem_lines = expanded_lines

        line_anchors = list(layout.get("line_anchors_px") or [])
        condition_tops = [
            float(block.get("top_px"))
            for block in condition_blocks
            if block.get("top_px") is not None
        ]
        if line_anchors and condition_tops:
            mapped_line_tops: list[tuple[int, float]] = []
            anchor_cursor = 0
            for line_index, line in enumerate(stem_lines):
                line_key = re.sub(r"[\W_]+", "", line)
                if len(line_key) < 4:
                    continue
                for anchor_index in range(anchor_cursor, len(line_anchors)):
                    anchor = line_anchors[anchor_index]
                    anchor_key = re.sub(r"[\W_]+", "", str(anchor.get("text") or ""))
                    prefix = min(12, len(line_key), len(anchor_key))
                    if prefix >= 4 and line_key[:prefix] == anchor_key[:prefix]:
                        mapped_line_tops.append((line_index, float(anchor.get("top") or 0.0)))
                        anchor_cursor = anchor_index + 1
                        break
            condition_top = min(condition_tops)
            following = [
                line_index
                for line_index, line_top in mapped_line_tops
                if line_top >= condition_top - 1.0
            ]
            if following:
                insertion_index = min(following)

        for index, line in enumerate(stem_lines):
            if index == insertion_index:
                content_height += append_condition_blocks()
            content_height += append_math_paragraph(cell, line)
        if insertion_index >= len(stem_lines):
            content_height += append_condition_blocks()
        component_geometry = (
            layout.get("component_geometry_px")
            if isinstance(layout.get("component_geometry_px"), dict)
            else {}
        )
        page_info = layout.get("page") if isinstance(layout.get("page"), dict) else {}
        page_height_px = float(page_info.get("height_px") or 0.0)
        figure_boxes = list(layout.get("figure_boxes_px") or [])
        component_events: list[dict[str, Any]] = []
        for figure_index, _image_path in enumerate(item.get("image_paths") or []):
            box = figure_boxes[figure_index] if figure_index < len(figure_boxes) else []
            top = float(box[1]) if len(box) == 4 else float("inf")
            bottom = top + float(box[3]) if len(box) == 4 else float("inf")
            component_events.append(
                {
                    "type": "figure",
                    "index": figure_index,
                    "top": top,
                    "bottom": bottom,
                }
            )
        native_tables = list(item.get("native_tables") or [])
        for table_index, table_item in enumerate(native_tables):
            component_events.append(
                {
                    "type": "native_table",
                    "index": table_index,
                    "top": float(table_item.get("top_px") or float("inf")),
                    "bottom": float(table_item.get("bottom_px") or float("inf")),
                }
            )
        choices = [str(choice or "") for choice in item.get("choices") or []]
        if choices:
            choice_top = float(component_geometry.get("choice_top") or float("inf"))
            choice_bottom = float(component_geometry.get("choice_bottom") or choice_top)
            component_events.append(
                {
                    "type": "choices",
                    "top": choice_top,
                    "bottom": choice_bottom,
                }
            )
        component_events.sort(key=lambda event: (float(event["top"]), event["type"] != "figure"))
        previous_source_bottom = float(component_geometry.get("stem_bottom") or 0.0)
        for event in component_events:
            event_top = float(event["top"])
            if (
                previous_source_bottom > 0
                and math.isfinite(event_top)
                and page_height_px > 0
            ):
                source_gap_pt = (
                    max(0.0, event_top - previous_source_bottom)
                    / page_height_px
                    * page.rect.height
                    * coordinate_scale
                )
                content_height += add_spacer(
                    cell,
                    _pt_to_hwp(max(0.0, source_gap_pt - 3.5)),
                    width,
                )
            if event["type"] == "figure":
                content_height += append_figure(
                    cell,
                    item,
                    int(event["index"]),
                    width,
                    page,
                )
            elif event["type"] == "native_table":
                content_height += append_native_math_table(
                    cell,
                    item,
                    int(event["index"]),
                    width,
                )
            else:
                content_height += append_choices(cell, choices, width)
            event_bottom = float(event["bottom"])
            if math.isfinite(event_bottom):
                previous_source_bottom = max(previous_source_bottom, event_bottom)
        return content_height

    def add_spacer(cell: Any, height: int, width: int) -> int:
        safe_height = max(0, int(height))
        if safe_height < _pt_to_hwp(1.0):
            return 0
        spacer_table = cell.add_table(
            1,
            1,
            width=max(1, width),
            height=safe_height,
            border_fill_id_ref=no_border_fill,
        )
        spacer_cell = spacer_table.cell(0, 0)
        spacer_cell.set_size(max(1, width), safe_height)
        _set_cell_border_fill(spacer_cell, no_border_fill)
        _set_cell_margin(
            spacer_cell,
            left_mm=0.0,
            right_mm=0.0,
            top_mm=0.0,
            bottom_mm=0.0,
        )
        _clear_cell_paragraphs(spacer_cell)
        return safe_height

    with fitz.open(pdf_path) as source_pdf:
        if not source_pdf:
            raise ValueError(f"empty PDF: {pdf_path}")
        source_width_mm = _pt_to_mm(source_pdf[0].rect.width)
        coordinate_scale = width_mm / max(1.0, source_width_mm)
        margin_left_pt = margin_left_mm * 72.0 / 25.4 / coordinate_scale
        margin_right_pt = margin_right_mm * 72.0 / 25.4 / coordinate_scale
        margin_top_pt = margin_top_mm * 72.0 / 25.4 / coordinate_scale
        margin_bottom_pt = margin_bottom_mm * 72.0 / 25.4 / coordinate_scale
        first_page_text = " ".join(_line_text(line) for line in _iter_text_lines(source_pdf[0]))
        form_label = next(
            (label for label in ("홀수형", "짝수형") if label in first_page_text),
            None,
        )
        subject_title = _flow_subject_title(pdf_path) or "수학 영역"
        total_pages = len(source_pdf) if max_pages is None else min(len(source_pdf), max_pages)

        for page_index in range(total_pages):
            page = source_pdf[page_index]
            body_top = _page_body_top(page)
            if body_top <= margin_top_pt:
                body_top = margin_top_pt
            native_images = _merge_flow_images(_iter_flow_images(page))
            native_images, textual_image_regions = _convert_textual_image_regions(page, native_images)
            page_lines = [line for line in _iter_text_lines(page) if _line_text(line)]
            line_items = [
                {"type": "line", "bbox": fitz.Rect(line["bbox"]), "spans": line["spans"]}
                for line in page_lines
                if not _is_flow_footer_line(page, line)
                and not _inside_any_region(fitz.Rect(line["bbox"]), textual_image_regions)
            ]
            all_items = line_items + native_images
            header_items = [item for item in all_items if _item_bbox(item).y1 < body_top - 1]
            header_gap_pt = max(0.0, body_top - margin_top_pt)
            header_height = _pt_to_hwp(header_gap_pt * coordinate_scale)
            header_height = max(
                _pt_to_hwp(24 * coordinate_scale),
                min(header_height, _pt_to_hwp(140 * coordinate_scale)),
            )
            header_added = _append_header_snapshot(
                doc,
                page,
                source_left_pt=margin_left_pt,
                source_right_pt=page.rect.width - margin_right_pt,
                source_top_pt=margin_top_pt,
                source_bottom_pt=body_top,
                table_width=table_width,
                table_height=header_height,
                no_border_fill=no_border_fill,
                compact_para=compact_para,
                page_break=page_index > 0,
            )
            if not header_added:
                append_running_header(
                    page_number=page_index + 1,
                    header_height=header_height,
                    subject=subject_title,
                    form=form_label or "",
                )

            body_bottom = page.rect.height - margin_bottom_pt
            body_height = max(
                _pt_to_hwp(24),
                # Leave room for Hancom/rhwp's outer table-anchor metrics.
                # A 10pt reserve still overflowed by about 9pt on the 2026
                # high-school Grade 1 June math paper even though its content
                # was well inside the body, so keep a full 20pt safety band.
                _pt_to_hwp((body_bottom - body_top) * coordinate_scale) - _pt_to_hwp(20.0),
            )
            body_table = doc.add_table(
                1,
                2,
                width=table_width,
                height=body_height,
                border_fill_id_ref=no_border_fill,
                para_pr_id_ref=compact_para,
            )
            left_cell = body_table.cell(0, 0)
            right_cell = body_table.cell(0, 1)
            for target in (left_cell, right_cell):
                target.set_size(cell_width, body_height)
                _clear_cell_paragraphs(target)
                sub_list = target.element.find(_q("subList"))
                if sub_list is not None:
                    sub_list.set("vertAlign", "TOP")
            _set_cell_border_fill(left_cell, column_divider_border_fill)
            _set_cell_border_fill(right_cell, no_border_fill)
            _set_cell_margin(left_cell, left_mm=0.4, right_mm=2.3, top_mm=0.0, bottom_mm=0.0)
            _set_cell_margin(right_cell, left_mm=2.3, right_mm=0.4, top_mm=0.0, bottom_mm=0.0)

            page_items = items_by_page.get(page_index + 1, [])
            for column_index, target in ((1, left_cell), (2, right_cell)):
                column_items = [
                    item
                    for item in page_items
                    if int((item.get("layout") or {}).get("column_index") or 1) == column_index
                ]
                column_items.sort(
                    key=lambda item: float(((item.get("layout") or {}).get("bbox_px") or [0, 0])[1])
                )
                used_height = 0
                cursor_pt = body_top
                inner_width = max(1, cell_width - _pt_to_hwp(5.0))
                preamble_line = None
                if column_index == 1 and column_items:
                    first_layout = (
                        column_items[0].get("layout")
                        if isinstance(column_items[0].get("layout"), dict)
                        else {}
                    )
                    first_bbox = first_layout.get("bbox_px") or []
                    first_page_info = (
                        first_layout.get("page")
                        if isinstance(first_layout.get("page"), dict)
                        else {}
                    )
                    first_page_height_px = float(first_page_info.get("height_px") or 0.0)
                    first_top_pt = (
                        float(first_bbox[1]) / first_page_height_px * page.rect.height
                        if len(first_bbox) == 4 and first_page_height_px > 0
                        else body_bottom
                    )
                    preamble_line = next(
                        (
                            line
                            for line in page_lines
                            if body_top <= fitz.Rect(line["bbox"]).y0 < first_top_pt
                            and fitz.Rect(line["bbox"]).x1 < page.rect.width / 2.0
                            and re.search(
                                r"(?:\uc9c0\uc120\ub2e4|\ub2e8\ub2f5)\ud615",
                                _line_text(line),
                            )
                        ),
                        None,
                    )
                for item_index, item in enumerate(column_items):
                    layout = item.get("layout") if isinstance(item.get("layout"), dict) else {}
                    bbox_px = layout.get("bbox_px") or []
                    page_info = layout.get("page") if isinstance(layout.get("page"), dict) else {}
                    page_height_px = float(page_info.get("height_px") or 0.0)
                    if len(bbox_px) == 4 and page_height_px > 0:
                        top_pt = float(bbox_px[1]) / page_height_px * page.rect.height
                        item_height_pt = max(18.0, float(bbox_px[3]) / page_height_px * page.rect.height)
                    else:
                        top_pt = cursor_pt
                        item_height_pt = 48.0
                    gap_hwp = max(
                        0,
                        _pt_to_hwp(max(0.0, top_pt - cursor_pt) * coordinate_scale),
                    )
                    if item_index == 0 and preamble_line is not None and gap_hwp >= _pt_to_hwp(10):
                        gap_hwp += _pt_to_hwp(5.0)
                        preamble_bbox = fitz.Rect(preamble_line["bbox"])
                        preamble_width = min(
                            inner_width,
                            _pt_to_hwp((preamble_bbox.width + 40.0) * coordinate_scale),
                        )
                        preamble_table = target.add_table(
                            1,
                            1,
                            width=preamble_width,
                            height=gap_hwp,
                            border_fill_id_ref=no_border_fill,
                        )
                        preamble_cell = preamble_table.cell(0, 0)
                        preamble_cell.set_size(preamble_width, gap_hwp)
                        _set_cell_border_fill(preamble_cell, no_border_fill)
                        _set_cell_margin(
                            preamble_cell,
                            left_mm=0.0,
                            right_mm=0.0,
                            top_mm=0.0,
                            bottom_mm=0.0,
                        )
                        _clear_cell_paragraphs(preamble_cell)
                        append_math_paragraph(
                            preamble_cell,
                            _line_text(preamble_line),
                            center=True,
                        )
                        used_height += gap_hwp
                    else:
                        used_height += add_spacer(target, gap_hwp, inner_width)
                    item_start_pt = cursor_pt + (
                        gap_hwp / HWP_PER_PT / max(0.01, coordinate_scale)
                    )
                    item_height = max(
                        _pt_to_hwp(18),
                        _pt_to_hwp(item_height_pt * coordinate_scale),
                    )
                    problem_table = target.add_table(
                        1,
                        1,
                        width=inner_width,
                        height=item_height,
                        border_fill_id_ref=no_border_fill,
                    )
                    problem_cell = problem_table.cell(0, 0)
                    problem_cell.set_size(inner_width, item_height)
                    _set_cell_border_fill(problem_cell, no_border_fill)
                    _set_cell_margin(problem_cell, left_mm=0.0, right_mm=0.0, top_mm=0.0, bottom_mm=0.0)
                    _clear_cell_paragraphs(problem_cell)
                    content_height = append_problem(problem_cell, item, inner_width, page)
                    item_height = max(item_height, content_height)
                    is_last_problem_before_postamble = all(
                        bool((following.get("layout") or {}).get("postamble"))
                        for following in column_items[item_index + 1 :]
                    )
                    if item_index == len(column_items) - 1 or is_last_problem_before_postamble:
                        remaining_height = max(
                            0,
                            body_height - used_height - _pt_to_hwp(14.0),
                        )
                        if content_height <= remaining_height:
                            item_height = min(item_height, remaining_height)
                    balance_height = max(
                        0,
                        item_height - content_height - _pt_to_hwp(10.0),
                    )
                    if balance_height >= _pt_to_hwp(1.0):
                        add_spacer(problem_cell, balance_height, inner_width)
                    table_size = problem_table.element.find(_q("sz"))
                    if table_size is not None:
                        table_size.set("height", str(item_height))
                    problem_cell.set_size(inner_width, item_height)
                    problem_table.mark_dirty()
                    used_height += item_height
                    reserved_height_pt = item_height / HWP_PER_PT / max(0.01, coordinate_scale)
                    cursor_pt = item_start_pt + reserved_height_pt

    _prepare_hancom_compatibility(doc)
    _save_hancom_compatible_document(doc, output_path)


def write_pdf_structured_hwpx(
    pdf_path: str | Path,
    output_path: str | Path,
    *,
    max_pages: int | None = None,
    template_key: str | None = None,
    native_math: bool = True,
    high_fidelity_math: bool = True,
) -> dict[str, Any]:
    """Write a paragraph/table HWPX with deterministic native-math recovery.

    Source figures may remain embedded pictures, but problem text and equations
    are never replaced with page or formula screenshots.
    """
    from . import hwpx_writer_v2, importers
    from .pdf_math_geometry import repair_problem_math_layout
    from .recognition.pipeline import recognize_pdf

    pdf_path = Path(pdf_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = pdf_path.read_bytes()
    recognized = recognize_pdf(payload, filename=pdf_path.name)
    if not recognized.found:
        raise ValueError(f"structured PDF recognition found no editable problems: {pdf_path}")
    title = str(getattr(recognized, "exam_title", "") or pdf_path.stem)
    resolved_template = template_key or _structured_pdf_template_key(pdf_path.name, title)

    # Some supplied exam PDFs concatenate odd/even forms. Their question
    # numbers restart halfway through and nearly every stem is duplicated.
    # Keep the first complete form so the editable output does not grow extra
    # near-duplicate pages from small segmentation differences in the second.
    variant_page_limit: int | None = None
    variant_overlap_ratio = 0.0
    total_recognized_pages = int(getattr(recognized, "page_count", 0) or 0)
    if total_recognized_pages >= 8 and total_recognized_pages % 2 == 0:
        half_pages = total_recognized_pages // 2

        def variant_key(problem: Any) -> tuple[str, str] | None:
            raw = str(getattr(problem, "text", "") or "")
            stem, _choices = importers._split_stem_and_choices(raw)
            compact = re.sub(r"\s+", "", math_text.normalize_recognized_math_layout_text(stem))[:240]
            if not compact:
                return None
            return str(getattr(problem, "number", "") or ""), compact

        first_keys = {
            key
            for problem in recognized.problems
            if int(getattr(problem, "page_number", 0) or 0) <= half_pages
            for key in [variant_key(problem)]
            if key is not None
        }
        second_keys = {
            key
            for problem in recognized.problems
            if int(getattr(problem, "page_number", 0) or 0) > half_pages
            for key in [variant_key(problem)]
            if key is not None
        }
        second_numbers = [
            int(getattr(problem, "number", 0) or 0)
            for problem in recognized.problems
            if int(getattr(problem, "page_number", 0) or 0) > half_pages
            and int(getattr(problem, "number", 0) or 0) > 0
        ]
        denominator = max(1, min(len(first_keys), len(second_keys)))
        variant_overlap_ratio = len(first_keys & second_keys) / denominator
        if second_numbers and min(second_numbers) <= 5 and variant_overlap_ratio >= 0.80:
            variant_page_limit = half_pages

    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    duplicate_count = 0
    figure_count = 0
    unreliable_count = 0
    repair_totals = {
        "matrices": 0,
        "integrals": 0,
        "limits": 0,
        "fractions": 0,
        "radicals": 0,
        "vectors": 0,
        "script_lines": 0,
        "wrapped_math_lines": 0,
        "wrapped_math_choices": 0,
    }
    recognized_problem_count = 0
    variant_duplicate_problem_count = 0

    for problem in recognized.problems:
        page_number = int(getattr(problem, "page_number", 0) or 0)
        if max_pages is not None and page_number > max_pages:
            continue
        if variant_page_limit is not None and page_number > variant_page_limit:
            variant_duplicate_problem_count += 1
            continue
        recognized_problem_count += 1
        if not bool(getattr(problem, "text_reliable", True)):
            unreliable_count += 1

        source_problem_text = str(getattr(problem, "text", "") or "")
        stem, choices = importers._split_stem_and_choices(source_problem_text)
        source_choice_labels = re.findall(r"[①②③④⑤]", source_problem_text)
        source_choice_order_noncanonical = source_choice_labels[:5] != sorted(source_choice_labels[:5])
        geometry = list(getattr(problem, "line_geometries", []) or [])
        geometry_split = importers._split_stem_and_choices_from_pdf_geometry(
            source_problem_text,
            geometry,
        )
        if geometry_split is not None:
            geometry_stem, geometry_choices = geometry_split
            geometry_placeholder_count = importers._placeholder_count_in_fields(
                geometry_stem, geometry_choices
            )
            text_placeholder_count = importers._placeholder_count_in_fields(stem, choices)
            geometry_nonempty = sum(1 for choice in geometry_choices if str(choice or "").strip())
            text_nonempty = sum(1 for choice in choices if str(choice or "").strip())
            if (
                (
                    len(geometry_choices) >= len(choices)
                    and geometry_placeholder_count < text_placeholder_count
                )
                or (
                    len(geometry_choices) > len(choices)
                    and geometry_placeholder_count <= text_placeholder_count
                    and geometry_nonempty >= max(text_nonempty, min(4, len(geometry_choices)))
                )
                or (
                    len(geometry_choices) == len(choices)
                    and len(geometry_choices) >= 4
                    and geometry_placeholder_count <= text_placeholder_count
                    and geometry_nonempty >= 4
                    and geometry_choices != choices
                    and source_choice_order_noncanonical
                )
            ):
                stem, choices = geometry_stem, geometry_choices
        stem = math_text.normalize_recognized_math_layout_text(stem)
        choices = [math_text.normalize_recognized_math_layout_text(choice) for choice in choices]
        geometry_stem = importers._repair_pdf_stem_fractions_from_geometry(stem, geometry)
        if importers._placeholder_count_in_fields(geometry_stem, choices) < importers._placeholder_count_in_fields(
            stem, choices
        ):
            stem = geometry_stem
        stem, choices, repair_stats = repair_problem_math_layout(stem, choices, geometry)
        for key in repair_totals:
            repair_totals[key] += int(repair_stats.get(key) or 0)

        number = str(getattr(problem, "number", "") or "")
        duplicate_key = (number, re.sub(r"\s+", "", stem)[:240])
        if duplicate_key in seen:
            duplicate_count += 1
            continue
        seen.add(duplicate_key)

        image_paths: list[str] = []
        figure_boxes_px: list[list[float]] = []
        problem_figure_boxes = list(getattr(problem, "figure_boxes", []) or [])
        for figure_index, figure_png in enumerate(getattr(problem, "figure_pngs", []) or [], start=1):
            relative_path = importers._save_image_bytes(
                f"{output_path.stem}_p{page_number}_q{number or 'x'}_fig{figure_index}.png",
                bytes(figure_png),
            )
            if relative_path:
                image_paths.append(relative_path)
                if figure_index <= len(problem_figure_boxes):
                    figure_box = problem_figure_boxes[figure_index - 1]
                    figure_boxes_px.append(
                        [
                            float(getattr(figure_box, "left", 0.0) or 0.0),
                            float(getattr(figure_box, "top", 0.0) or 0.0),
                            float(getattr(figure_box, "width", 0.0) or 0.0),
                            float(getattr(figure_box, "height", 0.0) or 0.0),
                        ]
                    )
                figure_count += 1
        problem_box = getattr(problem, "box", None)
        bbox_px = None
        if problem_box is not None:
            bbox_px = [
                float(getattr(problem_box, "left", 0.0) or 0.0),
                float(getattr(problem_box, "top", 0.0) or 0.0),
                float(getattr(problem_box, "width", 0.0) or 0.0),
                float(getattr(problem_box, "height", 0.0) or 0.0),
            ]
        column_index = int(getattr(problem, "column_index", 0) or 0)
        column_count = int(getattr(problem, "column_count", 0) or 0)
        page_width_px = int(getattr(problem, "page_width_px", 0) or 0)
        page_height_px = int(getattr(problem, "page_height_px", 0) or 0)
        component_geometry_px = _structured_math_component_geometry_px(geometry)
        line_anchors_px = _structured_math_line_anchors_px(geometry)
        items.append(
            {
                "number": number,
                "title": "",
                "stem": stem,
                "choices": choices,
                "image_paths": image_paths,
                "tables": [],
                "source_page": page_number,
                "layout": {
                    "source_page": page_number,
                    "column_index": column_index,
                    "column_count": column_count,
                    "bbox_px": bbox_px,
                    "figure_boxes_px": figure_boxes_px,
                    "component_geometry_px": component_geometry_px,
                    "line_anchors_px": line_anchors_px,
                    "page": {
                        "number": page_number,
                        "width_px": page_width_px,
                        "height_px": page_height_px,
                    },
                    "math_geometry_repairs": repair_stats,
                },
            }
        )

    if not items:
        raise ValueError(f"structured PDF recognition produced no output problems: {pdf_path}")

    problem_item_count = len(items)
    direct_text_flow = resolved_template in {"kice_korean", "kice_english"}
    output_page_limit = variant_page_limit
    if max_pages is not None:
        output_page_limit = min(output_page_limit or max_pages, max_pages)
    flow_page_limit: int | None = None
    visual_math_stats: dict[str, Any] = {}
    visual_math_mode = False
    visual_text_stats: dict[str, Any] = {}
    visual_text_mode = False
    if direct_text_flow:
        flow_page_limit = output_page_limit
        items = _structured_pdf_text_flow_items(
            pdf_path,
            items,
            page_limit=flow_page_limit,
        )
        if not items:
            raise ValueError(f"structured PDF text flow produced no output content: {pdf_path}")

    continuation_count = 0
    continuation_lines = 0
    postamble_count = 0
    postamble_lines = 0
    items_by_page: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        items_by_page.setdefault(int(item.get("source_page") or 0), []).append(item)
    continuation_items: dict[tuple[int, int], dict[str, Any]] = {}
    with fitz.open(pdf_path) as source_pdf:
        for source_page, page_items in items_by_page.items():
            if direct_text_flow:
                break
            if source_page <= 0 or source_page > len(source_pdf):
                continue
            page = source_pdf[source_page - 1]
            for column_index in (1, 2):
                column_layouts = [
                    item.get("layout")
                    for item in page_items
                    if isinstance(item.get("layout"), dict)
                    and int((item.get("layout") or {}).get("column_index") or 1)
                    == column_index
                ]
                first_layout = min(
                    column_layouts,
                    key=lambda layout: float((layout.get("bbox_px") or [0.0, 0.0])[1]),
                    default=None,
                )
                if not first_layout:
                    continue
                bbox_px = first_layout.get("bbox_px") or []
                page_info = (
                    first_layout.get("page")
                    if isinstance(first_layout.get("page"), dict)
                    else {}
                )
                if len(bbox_px) != 4:
                    continue
                page_width_px = int(page_info.get("width_px") or 0)
                page_height_px = int(page_info.get("height_px") or 0)
                continuation = _structured_page_continuation_text(
                    page,
                    first_problem_top_px=float(bbox_px[1]),
                    page_height_px=page_height_px,
                    column_index=column_index,
                )
                figure_data = _structured_page_continuation_figures(
                    page,
                    first_problem_top_px=float(bbox_px[1]),
                    page_height_px=page_height_px,
                    column_index=column_index,
                )
                if not continuation.strip() and not figure_data:
                    continue
                continuation = math_text.normalize_recognized_math_layout_text(
                    continuation
                )
                image_paths: list[str] = []
                figure_boxes_px: list[list[float]] = []
                scale_x = float(page_width_px) / max(1.0, float(page.rect.width))
                scale_y = float(page_height_px) / max(1.0, float(page.rect.height))
                for figure_index, (figure_png, figure_rect) in enumerate(
                    figure_data,
                    start=1,
                ):
                    relative_path = importers._save_image_bytes(
                        f"{output_path.stem}_p{source_page}_c{column_index}_preamble_fig{figure_index}.png",
                        figure_png,
                    )
                    if not relative_path:
                        continue
                    image_paths.append(relative_path)
                    figure_boxes_px.append(
                        [
                            float(figure_rect.x0) * scale_x,
                            float(figure_rect.y0) * scale_y,
                            float(figure_rect.width) * scale_x,
                            float(figure_rect.height) * scale_y,
                        ]
                    )
                    figure_count += 1
                continuation_count += 1
                continuation_lines += len(continuation.splitlines())
                start_y_px = float(page_height_px) * 0.13
                column_width_px = float(page_width_px) / 2.0
                continuation_items[(source_page, column_index)] = {
                    "number": "",
                    "title": "",
                    "stem": continuation,
                    "choices": [],
                    "image_paths": image_paths,
                    "tables": [],
                    "source_page": source_page,
                    "layout": {
                        "source_page": source_page,
                        "column_index": column_index,
                        "column_count": 2,
                        "continuation": True,
                        "page": page_info,
                        "figure_boxes_px": figure_boxes_px,
                        "bbox_px": [
                            0.0 if column_index == 1 else column_width_px,
                            start_y_px,
                            column_width_px,
                            max(1.0, float(bbox_px[1]) - start_y_px),
                        ],
                    },
                }
    with fitz.open(pdf_path) as source_pdf:
        for source_page, page_items in items_by_page.items():
            if direct_text_flow:
                break
            if source_page <= 0 or source_page > len(source_pdf):
                continue
            page = source_pdf[source_page - 1]
            for column_index in (1, 2):
                column_items = [
                    item
                    for item in page_items
                    if isinstance(item.get("layout"), dict)
                    and int((item.get("layout") or {}).get("column_index") or 1)
                    == column_index
                    and len((item.get("layout") or {}).get("bbox_px") or []) == 4
                ]
                last_item = max(
                    column_items,
                    key=lambda item: float(
                        ((item.get("layout") or {}).get("bbox_px") or [0, 0, 0, 0])[1]
                    )
                    + float(
                        ((item.get("layout") or {}).get("bbox_px") or [0, 0, 0, 0])[3]
                    ),
                    default=None,
                )
                if not last_item:
                    continue
                last_layout = last_item.get("layout") or {}
                bbox_px = last_layout.get("bbox_px") or []
                page_info = (
                    last_layout.get("page")
                    if isinstance(last_layout.get("page"), dict)
                    else {}
                )
                page_width_px = int(page_info.get("width_px") or 0)
                page_height_px = int(page_info.get("height_px") or 0)
                anchor_bottoms = [
                    float(anchor.get("bottom") or 0.0)
                    for anchor in (last_layout.get("line_anchors_px") or [])
                    if float(anchor.get("bottom") or 0.0)
                    <= float(page_height_px) * 0.90
                ]
                last_bottom_px = (
                    max(anchor_bottoms)
                    if anchor_bottoms
                    else float(bbox_px[1]) + float(bbox_px[3])
                )
                postamble = _structured_page_postamble_text(
                    page,
                    last_problem_bottom_px=last_bottom_px,
                    page_height_px=page_height_px,
                    column_index=column_index,
                )
                if not postamble.strip():
                    continue
                postamble_count += 1
                postamble_lines += len(postamble.splitlines())
                last_item["stem"] = (
                    str(last_item.get("stem") or "").rstrip()
                    + "\n\n"
                    + postamble.strip()
                )
                last_layout["postamble_attached"] = True
    if continuation_items:
        merged_items: list[dict[str, Any]] = []
        emitted_columns: set[tuple[int, int]] = set()
        for item in items:
            source_page = int(item.get("source_page") or 0)
            layout = item.get("layout") if isinstance(item.get("layout"), dict) else {}
            column_index = int(layout.get("column_index") or 1)
            key = (source_page, column_index)
            if key not in emitted_columns and key in continuation_items:
                merged_items.append(continuation_items[key])
                emitted_columns.add(key)
            merged_items.append(item)
        items = merged_items

    if resolved_template == "kice_math" and native_math:
        _attach_structured_math_condition_blocks(pdf_path, items)
        _attach_structured_math_native_tables(pdf_path, items)

    output_source_page_numbers: list[int] = []
    source_page_seen: set[int] = set()
    source_layout_items = 0
    expected_page_breaks = 0
    expected_column_breaks = 0
    previous_item: dict[str, Any] | None = None
    for item in items:
        source_page = int(item.get("source_page") or 0)
        layout = item.get("layout") if isinstance(item.get("layout"), dict) else {}
        if source_page > 0 and int(layout.get("column_index") or 0) > 0:
            source_layout_items += 1
        if source_page > 0 and source_page not in source_page_seen:
            source_page_seen.add(source_page)
            output_source_page_numbers.append(source_page)
        if previous_item is not None:
            previous_page = int(previous_item.get("source_page") or 0)
            previous_layout = (
                previous_item.get("layout")
                if isinstance(previous_item.get("layout"), dict)
                else {}
            )
            if source_page > 0 and previous_page > 0 and source_page != previous_page:
                expected_page_breaks += 1
            elif (
                source_page == previous_page
                and int(layout.get("column_index") or 0)
                > int(previous_layout.get("column_index") or 0)
            ):
                expected_column_breaks += 1
        previous_item = item
    editable_text_fragments = _structured_editable_text_fragments(items)
    if direct_text_flow:
        visual_text_stats = write_pdf_layout_hwpx(
            pdf_path,
            output_path,
            max_pages=flow_page_limit,
            include_images=True,
            include_lines=False,
            text_mode="line",
            native_math=False,
            math_visual_overlays=False,
            text_visual_overlays=True,
            text_visual_overlay_mode="foreground",
            foreground_stroke_soften_strength=(
                0.30 if "english" in resolved_template else 0.42
            ),
            force_grayscale_overlays=True,
            math_ai_recognition=False,
        )
        visual_text_mode = True
    elif resolved_template == "kice_math" and native_math and high_fidelity_math:
        # KICE PDFs encode equations as positioned private glyph fragments.
        # OCR reflow can keep the equation editable but cannot reliably infer
        # every stacked exponent, fraction and limit.  The coordinate writer
        # keeps normal text editable and overlays only math-risk clips for
        # source-exact visual fidelity.  It never falls back to a full-page
        # raster image or embeds structurally unsafe equations in drawText.
        visual_math_stats = write_pdf_layout_hwpx(
            pdf_path,
            output_path,
            max_pages=output_page_limit,
            include_images=True,
            include_lines=False,
            text_mode="line",
            native_math=False,
            math_visual_overlays=True,
            text_visual_overlays=True,
            text_visual_overlay_mode="foreground",
            foreground_overlay_right_pad=22.0,
            positioned_native_math=True,
            force_grayscale_overlays=True,
            math_ai_recognition=False,
        )
        visual_math_mode = True
    elif resolved_template == "kice_math" and native_math:
        _write_structured_math_page_tables(
            pdf_path,
            output_path,
            title,
            items,
            max_pages=max_pages,
        )
    else:
        hwpx_writer_v2.write_hwpx(
            output_path,
            title,
            items,
            resolved_template,
            native_math=native_math,
            preserve_source_layout=True,
        )
    structure = _structured_hwpx_counts(output_path)
    visual_layout_stats = visual_math_stats if visual_math_mode else visual_text_stats
    visual_layout_mode = visual_math_mode or visual_text_mode
    output_plain_text = _structured_hwpx_plain_text(output_path)
    source_text_char_count = sum(len(fragment) for fragment in editable_text_fragments)
    matched_text_char_count = sum(
        len(fragment)
        for fragment in editable_text_fragments
        if fragment in output_plain_text
    )
    source_text_preservation_ratio = (
        1.0
        if source_text_char_count == 0
        else matched_text_char_count / source_text_char_count
    )
    if visual_layout_mode:
        source_text_preservation_ratio = float(
            visual_layout_stats.get("editable_text_coverage_ratio") or 0.0
        )
        matched_text_char_count = int(round(source_text_char_count * source_text_preservation_ratio))
    source_math_segments = 0
    unresolved_placeholders = 0
    for item in items:
        values = [
            str(item.get("stem") or ""),
            *(str(choice or "") for choice in item.get("choices") or []),
            *(
                str(line or "")
                for block in (item.get("condition_blocks") or [])
                if isinstance(block, dict)
                for line in (block.get("lines") or [])
            ),
            *(
                str(cell or "")
                for table in (item.get("native_tables") or [])
                if isinstance(table, dict)
                for row in (table.get("text_rows") or [])
                for cell in row
            ),
        ]
        for value in values:
            source_math_segments += sum(1 for _segment, is_math in math_text.split_math_text(value) if is_math)
            unresolved_placeholders += sum(value.count(marker) for marker in ("□", "▢", "�"))
    if source_math_segments == 0:
        unresolved_placeholders = 0
    if visual_math_mode:
        if visual_math_stats.get("positioned_native_math_enabled"):
            source_math_segments = int(
                visual_math_stats.get("positioned_native_math_segments") or 0
            )
        else:
            source_math_segments = int(visual_math_stats.get("source_math_segments") or 0)
        unresolved_placeholders = 0
    native_equations = int(
        visual_math_stats.get("positioned_native_equations")
        if visual_math_mode and visual_math_stats.get("positioned_native_math_enabled")
        else visual_math_stats.get("native_equations")
        if visual_math_mode
        else structure["native_equations"]
    )
    coverage = 1.0 if source_math_segments == 0 else min(1.0, native_equations / source_math_segments)
    source_problem_count = max(0, recognized_problem_count - duplicate_count)
    editable_coverage = min(1.0, len(items) / max(1, source_problem_count))
    if visual_layout_mode:
        editable_coverage = float(
            visual_layout_stats.get("editable_text_coverage_ratio") or 0.0
        )
    with fitz.open(pdf_path) as source_pdf:
        source_pages = len(source_pdf)
    effective_page_limit = max_pages
    if variant_page_limit is not None:
        effective_page_limit = min(effective_page_limit or variant_page_limit, variant_page_limit)
    if effective_page_limit is not None:
        source_pages = min(source_pages, effective_page_limit)
    return {
        "layout_mode": (
            "structured_math_visual_overlay"
            if visual_math_mode
            else "structured_text_visual_overlay"
            if visual_text_mode
            else "structured"
        ),
        "structure": (
            "positioned_editable_text_math_overlays"
            if visual_math_mode
            else "positioned_editable_text_visual_overlays"
            if visual_text_mode
            else "paragraphs_tables_native_equations"
        ),
        "pages": source_pages,
        "source_pages": source_pages,
        "source_problem_count": source_problem_count,
        "recognized_problem_count": recognized_problem_count,
        "output_problem_count": problem_item_count,
        "continuation_block_count": continuation_count,
        "continuation_line_count": continuation_lines,
        "postamble_block_count": postamble_count,
        "postamble_line_count": postamble_lines,
        "output_page_count_target": len(output_source_page_numbers),
        "output_source_page_numbers": output_source_page_numbers,
        "source_layout_items": source_layout_items,
        "source_layout_coverage_ratio": round(source_layout_items / max(1, len(items)), 4),
        "expected_page_breaks": expected_page_breaks,
        "expected_column_breaks": expected_column_breaks,
        "duplicate_problem_count": 0,
        "deduplicated_problem_count": duplicate_count + variant_duplicate_problem_count,
        "variant_page_limit": variant_page_limit,
        "variant_overlap_ratio": round(variant_overlap_ratio, 4),
        "variant_duplicate_problem_count": variant_duplicate_problem_count,
        "unreliable_text_problems": unreliable_count,
        "editable_text_coverage_ratio": round(
            float(visual_layout_stats.get("editable_text_coverage_ratio") or editable_coverage)
            if visual_layout_mode
            else editable_coverage,
            4,
        ),
        "source_text_char_count": source_text_char_count,
        "matched_text_char_count": matched_text_char_count,
        "source_text_preservation_ratio": round(source_text_preservation_ratio, 4),
        "native_math_enabled": (
            bool(visual_layout_stats.get("native_math_enabled"))
            if visual_layout_mode
            else bool(native_math)
        ),
        "source_math_segments": source_math_segments,
        "native_equations": native_equations,
        "native_math_coverage_ratio": round(coverage, 4),
        "positioned_native_math_enabled": bool(
            visual_math_stats.get("positioned_native_math_enabled", False)
        ),
        "positioned_native_equations": int(
            visual_math_stats.get("positioned_native_equations") or 0
        ),
        "positioned_native_math_segments": int(
            visual_math_stats.get("positioned_native_math_segments") or 0
        ),
        "draw_text_boxes": int(structure["draw_text_boxes"]),
        "paragraphs": int(structure["paragraphs"]),
        "tables": int(structure["tables"]),
        "page_breaks": int(structure["page_breaks"]),
        "column_breaks": int(structure["column_breaks"]),
        "two_column_page_tables": int(structure["two_column_page_tables"]),
        "running_header_tables": int(structure["running_header_tables"]),
        "column_layout_mode": "positioned_source_geometry" if visual_layout_mode else "page_tables",
        "images": int(visual_layout_stats.get("images") or 0) if visual_layout_mode else figure_count,
        "full_page_images": int(visual_layout_stats.get("full_page_images") or 0),
        "full_page_raster_fallback": bool(visual_layout_stats.get("full_page_raster_fallback", False)),
        "math_visual_overlays": int(visual_math_stats.get("math_visual_overlays") or 0),
        "math_visual_overlay_area_ratio": float(
            visual_math_stats.get("math_visual_overlay_area_ratio") or 0.0
        ),
        "math_visual_overlay_enabled": bool(
            visual_math_stats.get("math_visual_overlay_enabled", False)
        ),
        "text_visual_overlays": int(visual_layout_stats.get("text_visual_overlays") or 0),
        "text_visual_overlay_area_ratio": float(
            visual_layout_stats.get("text_visual_overlay_area_ratio") or 0.0
        ),
        "text_visual_overlay_enabled": bool(
            visual_layout_stats.get("text_visual_overlay_enabled", False)
        ),
        "fraction_rule_lines": int(visual_math_stats.get("fraction_rule_lines") or 0),
        "math_char_text_items": int(visual_math_stats.get("math_char_text_items") or 0),
        "line_rects": int(visual_math_stats.get("line_rects") or 0),
        "page_standard_names": list(visual_layout_stats.get("page_standard_names") or []),
        "page_print_paper_names": list(visual_layout_stats.get("page_print_paper_names") or []),
        "page_print_scale_values": list(visual_layout_stats.get("page_print_scale_values") or []),
        "unresolved_math_placeholders": unresolved_placeholders,
        "template_key": resolved_template,
        "font_face": "HY신명조",
        "math_geometry_repairs": repair_totals,
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
    math_visual_overlays: bool = False,
    text_visual_overlays: bool = False,
    text_visual_overlay_mode: Literal[
        "line", "block", "foreground", "column"
    ] = "block",
    foreground_overlay_right_pad: float = 5.0,
    foreground_stroke_soften_strength: float = 0.42,
    positioned_native_math: bool = False,
    force_grayscale_overlays: bool = False,
    math_ai_recognition: bool | None = None,
    math_ai_model: str | None = None,
) -> dict[str, Any]:
    pdf_path = Path(pdf_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = HwpxDocument.new()
    header = doc.headers[0]
    _ensure_pdf_font_faces(header)
    _apply_exam_base_text_profile(header)
    para_left = header.ensure_paragraph_format(
        alignment="LEFT",
        line_spacing_percent=_FLOW_BODY_LINE_SPACING,
    )
    para_visual_text = header.ensure_paragraph_format(
        alignment="JUSTIFY",
        line_spacing_percent=_FLOW_BODY_LINE_SPACING,
    )
    text_para_pr = para_visual_text if text_visual_overlays else para_left

    text_count = 0
    image_count = 0
    line_count = 0
    page_count = 0
    source_text_lines = 0
    full_page_image_count = 0
    native_equation_count = 0
    source_math_segment_count = 0
    fraction_rule_line_count = 0
    math_char_text_count = 0
    math_visual_overlay_count = 0
    math_visual_overlay_area = 0.0
    text_visual_overlay_count = 0
    text_visual_overlay_area = 0.0
    total_source_page_area = 0.0
    page_standard_names: set[str] = set()
    page_print_paper_names: set[str] = set()
    page_print_scale_values: set[float] = set()
    styles: dict[tuple[str, float, bool], str] = {}
    z_counter = [0]
    equation_counter = [0]
    math_ai_enabled = pdf_math_ai.resolve_math_ai_enabled(math_ai_recognition)
    resolved_math_ai_model = pdf_math_ai.resolve_math_ai_model(math_ai_model)
    math_ai_remaining_calls = pdf_math_ai.resolve_math_ai_max_calls()
    math_ai_attempts = 0
    math_ai_accepted = 0
    math_ai_rejected = 0
    math_ai_skipped = 0
    math_ai_errors = 0
    math_ai_native_equations = 0
    positioned_native_equations = 0
    positioned_native_math_segments = 0
    math_ai_last_error = ""

    with fitz.open(pdf_path) as pdf_doc:
        if not pdf_doc:
            raise ValueError(f"empty PDF: {pdf_path}")

        total_pages = len(pdf_doc) if max_pages is None else min(len(pdf_doc), max_pages)
        for page_index in range(total_pages):
            page = pdf_doc[page_index]
            page_transform = _standard_exam_page_transform(page)
            total_source_page_area += max(1.0, float(page.rect.width * page.rect.height))
            if page_transform.standard_name:
                page_standard_names.add(str(page_transform.standard_name))
            if page_transform.print_paper:
                page_print_paper_names.add(str(page_transform.print_paper))
                page_print_scale_values.add(round(float(page_transform.print_scale), 4))
            section = doc.sections[0] if page_index == 0 else doc.add_section()
            doc.set_page_size(
                width=_hwp(page_transform.target_width_pt),
                height=_hwp(page_transform.target_height_pt),
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
            math_ai_page_groups, math_ai_applied_source_rects, math_ai_remaining_calls, ai_page_stats = (
                _recognize_math_ai_page_groups(
                    page,
                    page_text_lines,
                    enabled=math_ai_enabled,
                    model=resolved_math_ai_model,
                    remaining_calls=math_ai_remaining_calls,
                )
            )
            math_ai_attempts += int(ai_page_stats.get("attempts") or 0)
            math_ai_skipped += int(ai_page_stats.get("skipped") or 0)
            math_ai_errors += int(ai_page_stats.get("errors") or 0)
            math_ai_rejected += int(ai_page_stats.get("rejected") or 0)
            if ai_page_stats.get("last_error"):
                math_ai_last_error = str(ai_page_stats.get("last_error") or "")[:500]

            if include_images:
                added_images, added_full_page_images = _add_pdf_images(
                    doc,
                    anchor,
                    pdf_doc,
                    page,
                    text_rects,
                    z_counter,
                    page_transform,
                )
                image_count += added_images
                full_page_image_count += added_full_page_images
            if include_lines:
                line_count += _add_line_rects(
                    doc,
                    anchor,
                    page,
                    z_counter,
                    page_transform,
                    exclude_source_rects=math_ai_applied_source_rects,
                    include_strokes=False,
                    include_fills=True,
                )
            if positioned_native_math:
                for native_math_line in page_text_lines:
                    inserted, segments = _add_positioned_native_math_for_line(
                        doc,
                        anchor,
                        native_math_line,
                        styles=styles,
                        z_counter=z_counter,
                        page_transform=page_transform,
                        equation_counter=equation_counter,
                    )
                    positioned_native_equations += inserted
                    positioned_native_math_segments += segments
                    native_equation_count += inserted

            if text_mode == "line":
                line_index = 0
                while line_index < len(page_text_lines):
                    line = page_text_lines[line_index]
                    if _line_should_use_char_layout(line):
                        planned_ai_group = math_ai_page_groups.get(line_index)
                        if planned_ai_group is not None:
                            group_lines, next_index, planned_ai_result = planned_ai_group
                        else:
                            group_lines, next_index = (
                                _math_ai_line_group(page_text_lines, line_index)
                                if _line_is_math_ai_candidate(line)
                                else ([line], line_index + 1)
                            )
                            planned_ai_result = None
                        ai_inserted = False
                        if planned_ai_result is not None:
                            ai_inserted, ai_result = _add_math_ai_recognition_equation(
                                doc,
                                anchor,
                                group_lines,
                                planned_ai_result,
                                styles=styles,
                                para_pr_id_ref=text_para_pr,
                                z_counter=z_counter,
                                page_transform=page_transform,
                                equation_counter=equation_counter,
                            )
                            if ai_inserted:
                                math_ai_accepted += 1
                                math_ai_native_equations += 1
                                native_equation_count += 1
                                source_math_segment_count += 1
                                text_count += 1
                                line_index = next_index
                                continue
                            math_ai_rejected += 1
                            math_ai_last_error = pdf_math_ai.redact_error(
                                str(ai_result.error or ai_result.notes or "")
                            )[:500]
                        for fallback_line in group_lines:
                            run_stats = _add_char_layout_text_boxes(
                                doc,
                                anchor,
                                fallback_line,
                                styles=styles,
                                para_pr_id_ref=text_para_pr,
                                z_counter=z_counter,
                                page_transform=page_transform,
                                equation_counter=equation_counter,
                                native_math=native_math,
                            )
                            native_equation_count += int(run_stats.get("native_equations") or 0)
                            source_math_segment_count += int(run_stats.get("source_math_segments") or 0)
                            added_text_items = int(run_stats.get("text_items") or 0)
                            if added_text_items > 0:
                                text_count += 1
                            math_char_text_count += added_text_items
                            if (
                                text_visual_overlays
                                and text_visual_overlay_mode == "line"
                            ) or (
                                math_visual_overlays
                                and _line_has_math_visual_risk(fallback_line)
                            ):
                                added_overlay, overlay_area = _add_pdf_clip_overlay(
                                    doc,
                                    anchor,
                                    page,
                                    fitz.Rect(fallback_line["bbox"]),
                                    z_counter,
                                    page_transform,
                                    render_zoom=(
                                        2.0
                                        if text_visual_overlays
                                        else _MATH_OVERLAY_RENDER_ZOOM
                                    ),
                                    tight_text_clip=text_visual_overlays,
                                    compress_grayscale=True,
                                    force_grayscale=force_grayscale_overlays,
                                )
                                if added_overlay:
                                    if (
                                        math_visual_overlays
                                        and _line_has_math_visual_risk(fallback_line)
                                    ):
                                        math_visual_overlay_count += 1
                                        math_visual_overlay_area += overlay_area
                                    else:
                                        text_visual_overlay_count += 1
                                        text_visual_overlay_area += overlay_area
                                    image_count += 1
                        line_index = next_index
                        continue
                    line_spans = line["spans"]
                    bbox = page_transform.rect(fitz.Rect(line["bbox"]))
                    runs = _span_text_runs(doc, styles, line_spans)
                    if runs:
                        pad_x = 1.5
                        pad_y = 1.0
                        x_pt = max(0.0, bbox.x0 - 0.3)
                        run_stats = _add_text_box_runs(
                            doc,
                            anchor,
                            x_pt=x_pt,
                            y_pt=max(0.0, bbox.y0 - 0.8),
                            width_pt=_expanded_text_width(
                                page_transform.target_rect,
                                bbox,
                                x_pt,
                                pad_x=pad_x,
                                extra_right_pt=18.0,
                            ),
                            height_pt=max(2.0, bbox.height + pad_y * 2),
                            runs=runs,
                            para_pr_id_ref=text_para_pr,
                            z_order=_next_z(z_counter),
                            equation_counter=equation_counter,
                            native_math=native_math,
                        )
                        native_equation_count += int(run_stats.get("native_equations") or 0)
                        source_math_segment_count += int(run_stats.get("source_math_segments") or 0)
                        text_count += 1
                    if (
                        text_visual_overlays
                        and text_visual_overlay_mode == "line"
                    ) or (
                        math_visual_overlays and _line_has_math_visual_risk(line)
                    ):
                        added_overlay, overlay_area = _add_pdf_clip_overlay(
                            doc,
                            anchor,
                            page,
                            fitz.Rect(line["bbox"]),
                            z_counter,
                            page_transform,
                            render_zoom=(
                                2.0
                                if text_visual_overlays
                                else _MATH_OVERLAY_RENDER_ZOOM
                            ),
                            tight_text_clip=text_visual_overlays,
                            compress_grayscale=True,
                            force_grayscale=force_grayscale_overlays,
                        )
                        if added_overlay:
                            if math_visual_overlays and _line_has_math_visual_risk(line):
                                math_visual_overlay_count += 1
                                math_visual_overlay_area += overlay_area
                            else:
                                text_visual_overlay_count += 1
                                text_visual_overlay_area += overlay_area
                            image_count += 1
                    line_index += 1
            else:
                for span in spans:
                    text = _pdf_output_text(str(span.get("text") or ""))
                    bbox = page_transform.rect(fitz.Rect(span["bbox"]))
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
                            page_transform.target_rect,
                            bbox,
                            x_pt,
                            pad_x=pad_x,
                            extra_right_pt=6.0,
                        ),
                        height_pt=max(2.0, bbox.height + pad_y * 2),
                        runs=[(text, char_pr)],
                        para_pr_id_ref=text_para_pr,
                        z_order=_next_z(z_counter),
                        equation_counter=equation_counter,
                        native_math=native_math,
                    )
                    native_equation_count += int(run_stats.get("native_equations") or 0)
                    source_math_segment_count += int(run_stats.get("source_math_segments") or 0)
                    text_count += 1
            if text_visual_overlays and text_visual_overlay_mode in {
                "block",
                "foreground",
                "column",
            }:
                overlay_rects = (
                    _column_visual_overlay_rects(page)
                    if text_visual_overlay_mode == "column"
                    else _foreground_visual_overlay_rects(
                        page,
                        right_pad=foreground_overlay_right_pad,
                    )
                    if text_visual_overlay_mode == "foreground"
                    else _text_visual_overlay_rects(page, page_text_lines)
                )
                for overlay_rect in overlay_rects:
                    added_overlay, overlay_area = _add_pdf_clip_overlay(
                        doc,
                        anchor,
                        page,
                        overlay_rect,
                        z_counter,
                        page_transform,
                        render_zoom=2.0,
                        tight_text_clip=True,
                        soften_foreground_strokes=(
                            text_visual_overlay_mode == "foreground"
                        ),
                        foreground_stroke_soften_strength=(
                            foreground_stroke_soften_strength
                        ),
                        whiten_near_white=(
                            text_visual_overlay_mode == "foreground"
                        ),
                        compress_grayscale=True,
                        force_grayscale=force_grayscale_overlays,
                    )
                    if added_overlay:
                        text_visual_overlay_count += 1
                        text_visual_overlay_area += overlay_area
                        image_count += 1
            if include_lines:
                line_count += _add_line_rects(
                    doc,
                    anchor,
                    page,
                    z_counter,
                    page_transform,
                    exclude_source_rects=math_ai_applied_source_rects,
                    include_strokes=True,
                    include_fills=False,
                )
            if include_lines or math_visual_overlays:
                fraction_rule_line_count += _add_fraction_rule_glyph_lines(
                    doc,
                    anchor,
                    page,
                    z_counter,
                    page_transform,
                    exclude_source_rects=math_ai_applied_source_rects,
                )
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
        "fraction_rule_lines": fraction_rule_line_count,
        "math_char_text_items": math_char_text_count,
        "page_standard_names": sorted(page_standard_names),
        "page_print_paper_names": sorted(page_print_paper_names),
        "page_print_scale_values": sorted(page_print_scale_values),
        "math_visual_overlays": math_visual_overlay_count,
        "math_visual_overlay_area_ratio": (
            round(math_visual_overlay_area / max(1.0, total_source_page_area), 4)
            if total_source_page_area > 0
            else 0.0
        ),
        "math_visual_overlay_enabled": bool(math_visual_overlays),
        "text_visual_overlays": text_visual_overlay_count,
        "text_visual_overlay_area_ratio": (
            round(text_visual_overlay_area / max(1.0, total_source_page_area), 4)
            if total_source_page_area > 0
            else 0.0
        ),
        "text_visual_overlay_enabled": bool(text_visual_overlays),
        "math_ai_recognition_enabled": bool(math_ai_enabled),
        "math_ai_model": resolved_math_ai_model if math_ai_enabled else "",
        "math_ai_attempts": math_ai_attempts,
        "math_ai_accepted": math_ai_accepted,
        "math_ai_rejected": math_ai_rejected,
        "math_ai_skipped": math_ai_skipped,
        "math_ai_errors": math_ai_errors,
        "math_ai_native_equations": math_ai_native_equations,
        "math_ai_last_error": math_ai_last_error,
        "native_math_enabled": bool(native_math or positioned_native_math),
        "native_equations": native_equation_count,
        "source_math_segments": source_math_segment_count,
        "native_math_coverage_ratio": (
            round(min(1.0, native_equation_count / source_math_segment_count), 4)
            if source_math_segment_count > 0
            else 1.0
        ),
        "positioned_native_math_enabled": bool(positioned_native_math),
        "positioned_native_equations": positioned_native_equations,
        "positioned_native_math_segments": positioned_native_math_segments,
        "positioned_native_math_coverage_ratio": (
            round(
                min(
                    1.0,
                    positioned_native_equations / positioned_native_math_segments,
                ),
                4,
            )
            if positioned_native_math_segments > 0
            else 1.0
        ),
    }


_LAYOUT_REQUIRED_FONT_FACES = ("HY신명조", "Times New Roman", "돋움")
_LAYOUT_REQUIRED_FONT_TYPES = {"HY신명조": "TTF", "Times New Roman": "TTF", "돋움": "TTF"}
_LAYOUT_OLD_DENSE_HEIGHTS = ("840", "940", "1080")


def _exam_page_ratio_ok(width: int, height: int) -> bool:
    if width <= 0 or height <= 0:
        return False
    actual = min(width, height) / max(width, height)
    for width_mm, height_mm in _KICE_STANDARD_PAGES_MM:
        expected = min(width_mm, height_mm) / max(width_mm, height_mm)
        if abs(actual - expected) <= 0.002:
            return True
    return False


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

    face_types: dict[str, set[str]] = {}
    for font in header.findall(f".//{_hh('font')}"):
        face = font.get("face")
        if face:
            face_types.setdefault(face, set()).add((font.get("type") or "").upper())
    faces = sorted(face_types)
    missing_faces = [face for face in _LAYOUT_REQUIRED_FONT_FACES if face not in faces]
    invalid_required_font_types = [
        face
        for face, expected_type in _LAYOUT_REQUIRED_FONT_TYPES.items()
        if face in face_types and expected_type not in face_types[face]
    ]

    char_metric_ok = False
    metric_heights: set[str] = set()
    for char_pr in header.findall(f".//{_hh('charPr')}"):
        ratio = char_pr.find(_hh("ratio"))
        spacing = char_pr.find(_hh("spacing"))
        if ratio is None or spacing is None:
            continue
        if (
            ratio.get("hangul") in {"90", str(_FLOW_CHAR_RATIO)}
            and ratio.get("latin") in {"90", str(_FLOW_CHAR_RATIO)}
            and spacing.get("hangul") == str(_FLOW_CHAR_SPACING)
            and spacing.get("latin") == str(_FLOW_CHAR_SPACING)
        ):
            char_metric_ok = True
            if char_pr.get("height"):
                metric_heights.add(str(char_pr.get("height")))

    para_165_ids: set[str] = set()
    para_exam_ids: set[str] = set()
    line_spacing_values: set[int] = set()
    for para_pr in header.findall(f".//{_hh('paraPr')}"):
        line_spacing = para_pr.find(f".//{_hh('lineSpacing')}")
        if line_spacing is not None and line_spacing.get("type") == "PERCENT":
            try:
                spacing_value = int(line_spacing.get("value") or "0")
            except ValueError:
                spacing_value = 0
            if spacing_value > 0:
                line_spacing_values.add(spacing_value)
            para_id = para_pr.get("id")
            if para_id and spacing_value == _FLOW_BODY_LINE_SPACING:
                para_165_ids.add(str(para_id))
            if para_id and 115 <= spacing_value <= 170:
                para_exam_ids.add(str(para_id))
    used_para_ids = {
        str(paragraph.get("paraPrIDRef") or "")
        for section in sections
        for paragraph in section.findall(f".//{_q('p')}")
    }
    uses_165 = any(
        para_id in para_165_ids for para_id in used_para_ids
    )
    uses_exam_line_spacing = uses_165 or any(
        para_id in para_exam_ids for para_id in used_para_ids
    )

    metric_height_values = sorted(metric_heights)
    old_dense_used = sorted(set(metric_height_values) & set(_LAYOUT_OLD_DENSE_HEIGHTS))
    font_size_bucket_ok = bool({"750", "780", "790", "800", "820", "830", "850", "880", "900", "950", "1000", "1100"} & metric_heights) and not old_dense_used
    native_equations = sum(len(section.findall(f".//{_q('equation')}")) for section in sections)
    page_breaks = sum(
        1
        for section in sections
        for paragraph in section.findall(f".//{_q('p')}")
        if paragraph.get("pageBreak") == "1"
    )
    two_column_page_table_count = 0
    running_header_table_count = 0
    for section in sections:
        for table in section.findall(f".//{_q('tbl')}"):
            parent = table.getparent()
            grandparent = parent.getparent() if parent is not None else None
            if not (
                parent is not None
                and grandparent is not None
                and grandparent.getparent() is section
                and etree.QName(parent).localname == "run"
                and etree.QName(grandparent).localname == "p"
            ):
                continue
            size = table.find(_q("sz"))
            try:
                height = int(size.get("height") or "0") if size is not None else 0
                columns = int(table.get("colCnt") or "0")
            except ValueError:
                continue
            if columns == 2 and height > 40000:
                two_column_page_table_count += 1
            elif columns >= 3 and height < 20000:
                running_header_table_count += 1
            elif (
                columns == 1
                and height < 20000
                and table.find(f".//{_q('pic')}") is not None
            ):
                running_header_table_count += 1
    page_pr_ok = True
    page_ratio_ok = True
    page_standard_ok = True
    page_portrait_ok = True
    page_orientation_ok = True
    page_sizes: list[dict[str, float | int | str]] = []
    page_margins: list[dict[str, float]] = []
    column_gaps_mm: list[float] = []
    page_standard_counts: dict[str, int] = {}
    page_print_paper_counts: dict[str, int] = {}
    page_print_scale_counts: dict[str, int] = {}
    for section in sections:
        page_pr = section.find(f".//{_q('pagePr')}")
        if page_pr is None:
            page_pr_ok = False
            page_ratio_ok = False
            page_standard_ok = False
            page_portrait_ok = False
            page_orientation_ok = False
            continue
        try:
            width = int(page_pr.get("width") or "0")
            height = int(page_pr.get("height") or "0")
            valid_size = width > 0 and height > 0
            page_pr_ok = page_pr_ok and valid_size
            page_portrait_ok = page_portrait_ok and valid_size and width <= height
            expected_orientation = "WIDELY" if width <= height else "PORTRAIT"
            page_orientation_ok = (
                page_orientation_ok
                and valid_size
                and (page_pr.get("landscape") or "").upper() == expected_orientation
            )
            page_ratio_ok = page_ratio_ok and _exam_page_ratio_ok(width, height)
            standard = _match_exam_page_standard_hwp(width, height) if valid_size else None
            if standard is None:
                page_standard_ok = False
            else:
                standard_name = str(standard["standard_name"])
                page_standard_counts[standard_name] = page_standard_counts.get(standard_name, 0) + 1
                print_paper = str(standard.get("print_paper") or "")
                if print_paper:
                    page_print_paper_counts[print_paper] = page_print_paper_counts.get(print_paper, 0) + 1
                print_scale = float(standard.get("print_scale") or 1.0)
                if abs(print_scale - 1.0) > 0.0001:
                    scale_key = f"{print_scale:.4g}"
                    page_print_scale_counts[scale_key] = page_print_scale_counts.get(scale_key, 0) + 1
            page_sizes.append(
                {
                    "width_hwp": width,
                    "height_hwp": height,
                    "width_mm": round(_mm_from_hwp(width), 3),
                    "height_mm": round(_mm_from_hwp(height), 3),
                    "ratio": round(width / max(1, height), 6),
                    "landscape": page_pr.get("landscape") or "",
                    "standard_name": str(standard["standard_name"]) if standard else "",
                    "standard_width_mm": float(standard["standard_width_mm"]) if standard else 0.0,
                    "standard_height_mm": float(standard["standard_height_mm"]) if standard else 0.0,
                    "width_delta_mm": float(standard["width_delta_mm"]) if standard else 0.0,
                    "height_delta_mm": float(standard["height_delta_mm"]) if standard else 0.0,
                    "print_paper": str(standard.get("print_paper") or "") if standard else "",
                    "print_scale": float(standard.get("print_scale") or 1.0) if standard else 1.0,
                }
            )
            margin = page_pr.find(_q("margin"))
            if margin is not None:
                page_margins.append(
                    {
                        name: round(_mm_from_hwp(int(margin.get(name) or "0")), 3)
                        for name in ("left", "right", "top", "bottom")
                    }
                )
            for col_pr in section.findall(f".//{_q('colPr')}"):
                try:
                    same_gap = int(col_pr.get("sameGap") or "0")
                except ValueError:
                    same_gap = 0
                if same_gap > 0:
                    column_gaps_mm.append(round(_mm_from_hwp(same_gap), 3))
        except ValueError:
            page_pr_ok = False
            page_ratio_ok = False
            page_standard_ok = False
            page_portrait_ok = False
            page_orientation_ok = False

    page_standard_names = sorted(page_standard_counts)
    page_physical_size_ok = (
        page_pr_ok
        and page_ratio_ok
        and page_standard_ok
        and page_portrait_ok
        and page_orientation_ok
    )
    page_margin_profile_ok = bool(page_margins) and all(
        17.0 <= margin["left"] <= 23.0
        and 17.0 <= margin["right"] <= 23.0
        and 17.0 <= margin["top"] <= 23.0
        and 15.0 <= margin["bottom"] <= 21.0
        for margin in page_margins
    )
    table_column_layout_ok = (
        two_column_page_table_count > 0
        and two_column_page_table_count == page_breaks + len(sections)
    )
    column_gap_profile_ok = (
        bool(column_gaps_mm) and all(6.0 <= value <= 10.0 for value in column_gaps_mm)
    ) or table_column_layout_ok

    return {
        "available": True,
        "required_font_faces": list(_LAYOUT_REQUIRED_FONT_FACES),
        "required_font_types": dict(_LAYOUT_REQUIRED_FONT_TYPES),
        "faces": faces,
        "face_types": {face: sorted(types) for face, types in sorted(face_types.items())},
        "missing_required_font_faces": missing_faces,
        "has_required_font_faces": not missing_faces,
        "invalid_required_font_types": invalid_required_font_types,
        "font_face_type_ok": not invalid_required_font_types,
        "char_metric_ok": char_metric_ok,
        "metric_heights": metric_height_values,
        "font_size_bucket_ok": font_size_bucket_ok,
        "old_dense_metric_heights": old_dense_used,
        "uses_165_line_spacing": uses_165,
        "uses_exam_line_spacing": uses_exam_line_spacing,
        "line_spacing_values": sorted(line_spacing_values),
        "native_equations": native_equations,
        "page_break_count": page_breaks,
        "section_count": len(sections),
        "page_pr_ok": page_pr_ok,
        "page_ratio_ok": page_ratio_ok,
        "page_standard_ok": page_standard_ok,
        "page_portrait_ok": page_portrait_ok,
        "page_orientation_ok": page_orientation_ok,
        "page_physical_size_ok": page_physical_size_ok,
        "page_standard_names": page_standard_names,
        "page_standard_counts": dict(sorted(page_standard_counts.items())),
        "page_print_paper_names": sorted(page_print_paper_counts),
        "page_print_paper_counts": dict(sorted(page_print_paper_counts.items())),
        "page_print_scale_values": sorted(float(value) for value in page_print_scale_counts),
        "page_print_scale_counts": dict(sorted(page_print_scale_counts.items())),
        "page_size_consistent": len(page_standard_names) <= 1,
        "page_sizes": page_sizes,
        "page_margins": page_margins,
        "page_margin_profile_ok": page_margin_profile_ok,
        "column_gaps_mm": column_gaps_mm,
        "column_gap_profile_ok": column_gap_profile_ok,
        "table_column_layout_ok": table_column_layout_ok,
        "two_column_page_table_count": two_column_page_table_count,
        "running_header_table_count": running_header_table_count,
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
    _apply_exam_base_text_profile(doc.headers[0])
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
            page_transform = _standard_exam_page_transform(page)
            page_width = _hwp(page_transform.target_width_pt)
            page_height = _hwp(page_transform.target_height_pt)
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
            _set_abs_position(
                pic.element,
                page_transform.target_rect.x0,
                page_transform.target_rect.y0,
                page_transform.target_rect.width,
                page_transform.target_rect.height,
            )
            page_count += 1

    _prepare_hancom_compatibility(doc)
    _save_hancom_compatible_document(doc, output_path)
    return {"pages": page_count, "page_images": page_count}
