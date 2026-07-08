# -*- coding: utf-8 -*-
"""Analyze real HWP exam templates through rhwp-exported HWPX.

This is the calibration bridge for the HWP/PDF -> editable HWPX pipeline:

1. Parse original .hwp samples with rhwp.
2. Export each source to HWPX, preserving header.xml style tables.
3. Inspect font faces, charPr, paraPr, page/column layout, equations, and
   observed style usage in section XML.

The output is intentionally practical: a JSON report for tooling and a compact
Markdown report for deciding writer template constants.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any
from xml.etree import ElementTree as ET

try:
    import rhwp
except Exception as exc:  # pragma: no cover - environment guard
    rhwp = None
    _RHWP_IMPORT_ERROR = exc
else:
    _RHWP_IMPORT_ERROR = None

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = ROOT / "data" / "hwp_template_analysis"

HH_NS = "http://www.hancom.co.kr/hwpml/2011/head"
HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS_NS = "http://www.hancom.co.kr/hwpml/2011/section"
HH = f"{{{HH_NS}}}"
HP = f"{{{HP_NS}}}"
HS = f"{{{HS_NS}}}"

LANG_ATTR_TO_FONTFACE = {
    "hangul": "hangul",
    "latin": "latin",
    "hanja": "hanja",
    "japanese": "japanese",
    "other": "other",
    "symbol": "symbol",
    "user": "user",
}

CIRCLED = "①②③④⑤⑥⑦⑧⑨"
SOURCE_MARKER_RE = re.compile(r"^\s*\[\d+\s*점]\[[^\]]+\d{1,3}\]\s*$")
PROBLEM_LABEL_RE = re.compile(r"^\s*\d{1,3}[.)]\s*")

EXPECTED_SAMPLE_NAMES = (
    "2024년 3월 교육청 모의고사 수학(편집).hwp",
    "2024년 5월 교육청 모의고사 수학(편집).hwp",
    "2024년 6월 평가원 모의고사 수학(편집).hwp",
    "2025학년도 수능 수학(편집).hwp",
    "평가원 수학 양식.hwp",
    "평가원 국어 양식.hwp",
    "평가원 영어 양식.hwp",
    "평가원 사탐 양식.hwp",
    "평가원 과탐 양식.hwp",
)


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", value).strip("._-")
    return stem[:96] or "sample"


def _discover_default_samples() -> list[Path]:
    downloads = Path.home() / "Downloads"
    by_name = {path.name: path for path in downloads.glob("*.hwp")}
    ordered = [by_name[name] for name in EXPECTED_SAMPLE_NAMES if name in by_name]
    extras = [
        path
        for path in sorted(downloads.glob("*.hwp"))
        if path.name not in EXPECTED_SAMPLE_NAMES
        and any(token in path.name for token in ("평가원", "수학", "국어", "영어", "탐구"))
        and path.stat().st_size > 0
    ]
    return [*ordered, *extras]


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _text_of(element: ET.Element) -> str:
    parts: list[str] = []
    for text_node in element.iter(f"{HP}t"):
        parts.append(text_node.text or "")
    return "".join(parts)


def _direct_run_text(run: ET.Element) -> str:
    parts: list[str] = []
    for child in list(run):
        if child.tag == f"{HP}t":
            parts.append(child.text or "")
    return "".join(parts)


def _compact_sample(text: str, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _font_faces(header: ET.Element) -> dict[str, dict[str, str]]:
    faces: dict[str, dict[str, str]] = {}
    for fontface in header.findall(f".//{HH}fontface"):
        lang = (fontface.get("lang") or "").lower()
        bucket = faces.setdefault(lang, {})
        for font in fontface.findall(f"{HH}font"):
            font_id = font.get("id")
            face = font.get("face") or font.get("name")
            if font_id is not None and face:
                bucket[font_id] = face
    return faces


def _font_ref_faces(font_ref: ET.Element | None, faces: dict[str, dict[str, str]]) -> dict[str, str]:
    if font_ref is None:
        return {}
    resolved: dict[str, str] = {}
    for attr, font_id in sorted(font_ref.attrib.items()):
        lang = LANG_ATTR_TO_FONTFACE.get(attr, attr).lower()
        resolved[attr] = faces.get(lang, {}).get(font_id, f"#{font_id}")
    return resolved


def _child_attrs(element: ET.Element, child_name: str) -> dict[str, str]:
    child = element.find(f"{HH}{child_name}")
    return dict(child.attrib) if child is not None else {}


def _char_properties(header: ET.Element, faces: dict[str, dict[str, str]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for char_pr in header.findall(f".//{HH}charPr"):
        char_id = char_pr.get("id")
        if char_id is None:
            continue
        font_ref = char_pr.find(f"{HH}fontRef")
        ratio = _child_attrs(char_pr, "ratio")
        spacing = _child_attrs(char_pr, "spacing")
        rel_sz = _child_attrs(char_pr, "relSz")
        offset = _child_attrs(char_pr, "offset")
        height = _int_or_none(char_pr.get("height"))
        out[char_id] = {
            "id": char_id,
            "height": height,
            "size_pt": round(height / 100, 2) if height is not None else None,
            "text_color": char_pr.get("textColor"),
            "border_fill_id_ref": char_pr.get("borderFillIDRef"),
            "font_ref": dict(font_ref.attrib) if font_ref is not None else {},
            "font_faces": _font_ref_faces(font_ref, faces),
            "ratio": ratio,
            "spacing": spacing,
            "rel_size": rel_sz,
            "offset": offset,
            "bold": char_pr.find(f"{HH}bold") is not None,
            "italic": char_pr.find(f"{HH}italic") is not None,
            "underline": char_pr.find(f"{HH}underline") is not None,
            "strikeout": char_pr.find(f"{HH}strikeout") is not None,
        }
    return out


def _margin_values(para_pr: ET.Element) -> dict[str, int | None]:
    margin = para_pr.find(f"{HH}margin")
    if margin is None:
        return {}
    values: dict[str, int | None] = {}
    for child in list(margin):
        values[_local_name(child.tag)] = _int_or_none(child.get("value"))
    return values


def _para_properties(header: ET.Element) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for para_pr in header.findall(f".//{HH}paraPr"):
        para_id = para_pr.get("id")
        if para_id is None:
            continue
        align = para_pr.find(f"{HH}align")
        line_spacing = para_pr.find(f"{HH}lineSpacing")
        break_setting = para_pr.find(f"{HH}breakSetting")
        out[para_id] = {
            "id": para_id,
            "align": dict(align.attrib) if align is not None else {},
            "line_spacing": dict(line_spacing.attrib) if line_spacing is not None else {},
            "line_spacing_value": _int_or_none(line_spacing.get("value") if line_spacing is not None else None),
            "line_spacing_type": line_spacing.get("type") if line_spacing is not None else None,
            "margin": _margin_values(para_pr),
            "break_setting": dict(break_setting.attrib) if break_setting is not None else {},
            "font_line_height": para_pr.get("fontLineHeight"),
            "snap_to_grid": para_pr.get("snapToGrid"),
        }
    return out


def _style_table(header: ET.Element) -> list[dict[str, str]]:
    styles = []
    for style in header.findall(f".//{HH}style"):
        styles.append(dict(style.attrib))
    return styles


def _classify_text(text: str, *, in_table: bool) -> str:
    stripped = (text or "").strip()
    if not stripped:
        return "empty"
    if SOURCE_MARKER_RE.match(stripped):
        return "source_marker"
    if any(ch in stripped for ch in CIRCLED):
        return "choices"
    if PROBLEM_LABEL_RE.match(stripped):
        return "problem_label_or_body"
    if in_table and any(token in stripped for token in ("영역", "문제지", "모의고사", "수능", "선택")):
        return "masthead_or_title"
    if len(stripped) <= 5 and stripped.isdigit():
        return "page_number"
    return "body"


def _is_descendant_of(element: ET.Element, parent_by_child: dict[int, ET.Element], tag_local: str) -> bool:
    current = parent_by_child.get(id(element))
    while current is not None:
        if _local_name(current.tag) == tag_local:
            return True
        current = parent_by_child.get(id(current))
    return False


def _add_sample(bucket: dict[str, Any], text: str, limit: int = 6) -> None:
    sample = _compact_sample(text)
    if not sample:
        return
    samples = bucket.setdefault("samples", [])
    if sample not in samples and len(samples) < limit:
        samples.append(sample)


def _equation_patterns(script: str) -> list[str]:
    checks = {
        "fraction_over": r"\bover\b",
        "sqrt": r"\bsqrt\s*\{",
        "root": r"\broot\b",
        "limit": r"\blim\b",
        "cases": r"\bcases\b",
        "matrix": r"\bmatrix\b|pmatrix|bmatrix",
        "vector": r"\bvec\b|overrightarrow|underarrow|harpoon",
        "summation": r"\bsum\b",
        "integral": r"\bint\b",
        "trig": r"\b(sin|cos|tan)\b",
        "log": r"\blog\b|\bln\b",
        "left_right": r"\bLEFT\b|\bRIGHT\b",
        "subscript": r"_\{",
        "superscript": r"\^\{",
        "roman": r"\brm\b",
        "italic": r"\bit\b",
    }
    return [name for name, pattern in checks.items() if re.search(pattern, script)]


def _section_layout(root: ET.Element) -> dict[str, Any]:
    page_pr = root.find(f".//{HP}pagePr")
    margin = page_pr.find(f"{HP}margin") if page_pr is not None else None
    col_pr = root.find(f".//{HP}colPr")
    page_width = _int_or_none(page_pr.get("width") if page_pr is not None else None)
    page_height = _int_or_none(page_pr.get("height") if page_pr is not None else None)
    margins = {key: _int_or_none(value) for key, value in (margin.attrib if margin is not None else {}).items()}
    body_width = None
    body_height = None
    if page_width is not None:
        body_width = page_width - int(margins.get("left") or 0) - int(margins.get("right") or 0)
    if page_height is not None:
        body_height = page_height - int(margins.get("top") or 0) - int(margins.get("bottom") or 0)
    return {
        "page": {
            "width": page_width,
            "height": page_height,
            "landscape": page_pr.get("landscape") if page_pr is not None else None,
            "margins": margins,
            "body_width": body_width,
            "body_height": body_height,
        },
        "columns": dict(col_pr.attrib) if col_pr is not None else {},
    }


def _line_segment_summary(root: ET.Element) -> dict[str, Any]:
    heights: list[int] = []
    spacings: list[int] = []
    for line_seg in root.findall(f".//{HP}lineseg"):
        height = _int_or_none(line_seg.get("textheight") or line_seg.get("vertsize"))
        spacing = _int_or_none(line_seg.get("spacing"))
        if height is not None:
            heights.append(height)
        if spacing is not None:
            spacings.append(spacing)

    def summary(values: list[int]) -> dict[str, Any]:
        if not values:
            return {"count": 0}
        return {
            "count": len(values),
            "min": min(values),
            "median": median(values),
            "max": max(values),
            "top_values": Counter(values).most_common(10),
        }

    return {"textheight": summary(heights), "spacing": summary(spacings)}


def _inspect_sections(
    archive: zipfile.ZipFile,
    char_props: dict[str, dict[str, Any]],
    para_props: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    section_names = sorted(name for name in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", name))
    char_usage: dict[str, dict[str, Any]] = defaultdict(lambda: {"runs": 0, "chars": 0, "roles": Counter()})
    para_usage: dict[str, dict[str, Any]] = defaultdict(lambda: {"paragraphs": 0, "nonempty": 0, "roles": Counter()})
    object_counts = Counter()
    equation_pattern_counts = Counter()
    equation_examples: list[dict[str, str]] = []
    layouts: list[dict[str, Any]] = []
    line_segments: list[dict[str, Any]] = []
    para_char_pairs = Counter()

    for section_name in section_names:
        root = ET.fromstring(archive.read(section_name))
        parent_by_child = {id(child): parent for parent in root.iter() for child in list(parent)}
        layouts.append({"section": section_name, **_section_layout(root)})
        line_segments.append({"section": section_name, **_line_segment_summary(root)})

        for element in root.iter():
            local = _local_name(element.tag)
            if local in {"tbl", "pic", "equation", "line", "rect", "container"}:
                object_counts[local] += 1

        for equation in root.findall(f".//{HP}equation"):
            script = "".join(script_node.text or "" for script_node in equation.findall(f".//{HP}script")).strip()
            for pattern in _equation_patterns(script):
                equation_pattern_counts[pattern] += 1
            if script and len(equation_examples) < 40:
                equation_examples.append({"section": section_name, "script": script[:180]})

        for paragraph in root.findall(f".//{HP}p"):
            para_id = paragraph.get("paraPrIDRef") or ""
            text = _text_of(paragraph)
            in_table = _is_descendant_of(paragraph, parent_by_child, "tbl")
            role = _classify_text(text, in_table=in_table)
            para_usage[para_id]["paragraphs"] += 1
            if text.strip():
                para_usage[para_id]["nonempty"] += 1
                _add_sample(para_usage[para_id], text)
            para_usage[para_id]["roles"][role] += 1

            for run in paragraph.findall(f"{HP}run"):
                char_id = run.get("charPrIDRef") or ""
                run_text = _direct_run_text(run)
                if not run_text and list(run):
                    # Some runs contain controls/equations only. They still matter for style inventory.
                    run_text = _text_of(run)
                char_usage[char_id]["runs"] += 1
                char_usage[char_id]["chars"] += len(run_text)
                char_usage[char_id]["roles"][role] += 1
                _add_sample(char_usage[char_id], run_text or text)
                para_char_pairs[(para_id, char_id)] += 1

    def normalize_usage(
        usage: dict[str, dict[str, Any]],
        props: dict[str, dict[str, Any]],
        *,
        kind: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for style_id, data in usage.items():
            row = {
                "id": style_id,
                **{k: v for k, v in data.items() if k != "roles"},
                "roles": dict(data["roles"].most_common()),
                "style": props.get(style_id, {}),
            }
            rows.append(row)
        key = "chars" if kind == "char" else "paragraphs"
        return sorted(rows, key=lambda item: int(item.get(key) or 0), reverse=True)

    return {
        "section_names": section_names,
        "layouts": layouts,
        "line_segments": line_segments,
        "object_counts": dict(object_counts),
        "equation_pattern_counts": dict(equation_pattern_counts.most_common()),
        "equation_examples": equation_examples,
        "char_style_usage": normalize_usage(char_usage, char_props, kind="char"),
        "para_style_usage": normalize_usage(para_usage, para_props, kind="para"),
        "para_char_pairs": [
            {"para_pr": para_id, "char_pr": char_id, "count": count}
            for (para_id, char_id), count in para_char_pairs.most_common(30)
        ],
    }


def _analyze_one(path: Path, out_dir: Path, *, keep_exports: bool) -> dict[str, Any]:
    if rhwp is None:
        raise RuntimeError(f"rhwp import failed: {_RHWP_IMPORT_ERROR}")

    export_dir = out_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_path = export_dir / f"{_safe_stem(path.stem)}.hwpx"

    doc = rhwp.parse(str(path))
    exported_size = doc.export_hwpx(str(export_path))

    with zipfile.ZipFile(export_path) as archive:
        header = ET.fromstring(archive.read("Contents/header.xml"))
        faces = _font_faces(header)
        char_props = _char_properties(header, faces)
        para_props = _para_properties(header)
        sections = _inspect_sections(archive, char_props, para_props)
        bin_data = [name for name in archive.namelist() if name.startswith("BinData/")]

    block_counts = Counter()
    raw_style_counts = Counter()
    formula_count = 0
    ir = doc.to_ir()
    for block in getattr(ir, "body", []) or []:
        kind = str(getattr(block, "kind", "") or "")
        block_counts[kind] += 1
        if kind == "formula":
            formula_count += 1
        for inline in getattr(block, "inlines", []) or []:
            raw_style_counts[str(getattr(inline, "raw_style_id", ""))] += len(getattr(inline, "text", "") or "")

    result = {
        "source": str(path),
        "source_name": path.name,
        "source_size": path.stat().st_size,
        "export_hwpx": str(export_path) if keep_exports else "",
        "exported_size": exported_size,
        "rhwp": {
            "page_count": getattr(doc, "page_count", None),
            "section_count": getattr(doc, "section_count", None),
            "paragraph_count": getattr(doc, "paragraph_count", None),
            "body_block_counts": dict(block_counts),
            "formula_count": formula_count,
            "raw_style_char_counts": dict(raw_style_counts.most_common()),
        },
        "header": {
            "font_faces": faces,
            "char_properties": char_props,
            "para_properties": para_props,
            "styles": _style_table(header),
            "counts": {
                "font_faces": sum(len(v) for v in faces.values()),
                "char_properties": len(char_props),
                "para_properties": len(para_props),
                "styles": len(_style_table(header)),
                "bin_data": len(bin_data),
            },
        },
        "sections": sections,
    }

    if not keep_exports:
        try:
            export_path.unlink()
        except OSError:
            pass
    return result


def _style_brief(style: dict[str, Any]) -> str:
    if not style:
        return "unresolved"
    faces = style.get("font_faces") or {}
    hangul = faces.get("hangul") or faces.get("hanja") or ""
    latin = faces.get("latin") or ""
    flags = []
    if style.get("bold"):
        flags.append("bold")
    if style.get("italic"):
        flags.append("italic")
    if style.get("underline"):
        flags.append("underline")
    ratio = (style.get("ratio") or {}).get("hangul") or (style.get("ratio") or {}).get("latin")
    spacing = (style.get("spacing") or {}).get("hangul") or (style.get("spacing") or {}).get("latin")
    return (
        f"{style.get('size_pt')}pt"
        f", ko={hangul or '-'}"
        f", en={latin or '-'}"
        f", ratio={ratio or '-'}"
        f", spacing={spacing or '-'}"
        f"{', ' + '/'.join(flags) if flags else ''}"
    )


def _para_brief(style: dict[str, Any]) -> str:
    if not style:
        return "unresolved"
    spacing = style.get("line_spacing") or {}
    align = style.get("align") or {}
    margin = style.get("margin") or {}
    return (
        f"line={spacing.get('value', '-')}{spacing.get('type', '')}"
        f", align={align.get('horizontal', '-')}"
        f", margin L/R={margin.get('left', '-')}/{margin.get('right', '-')}"
        f", intent={margin.get('intent', '-')}"
    )


def _write_markdown(reports: list[dict[str, Any]], out_path: Path) -> None:
    lines: list[str] = []
    lines.append("# HWP Template Analysis")
    lines.append("")
    lines.append("Generated from original `.hwp` files via `rhwp.export_hwpx()`, then inspected through HWPX XML.")
    lines.append("")
    lines.append("## Overview")
    lines.append("")
    lines.append("| Source | Pages | Blocks | Eq | Fonts | CharPr | ParaPr | Tables | Pics | Columns |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for report in reports:
        object_counts = report["sections"]["object_counts"]
        first_layout = (report["sections"]["layouts"] or [{}])[0]
        columns = (first_layout.get("columns") or {}).get("colCount") or "-"
        lines.append(
            "| "
            + " | ".join(
                [
                    report["source_name"],
                    str(report["rhwp"].get("page_count")),
                    str(sum(report["rhwp"].get("body_block_counts", {}).values())),
                    str(report["rhwp"].get("formula_count")),
                    str(report["header"]["counts"].get("font_faces")),
                    str(report["header"]["counts"].get("char_properties")),
                    str(report["header"]["counts"].get("para_properties")),
                    str(object_counts.get("tbl", 0)),
                    str(object_counts.get("pic", 0)),
                    str(columns),
                ]
            )
            + " |"
        )

    for report in reports:
        lines.append("")
        lines.append(f"## {report['source_name']}")
        lines.append("")
        lines.append(f"- Source: `{report['source']}`")
        if report.get("export_hwpx"):
            lines.append(f"- Exported HWPX: `{report['export_hwpx']}`")
        layouts = report["sections"]["layouts"]
        if layouts:
            page = layouts[0].get("page") or {}
            columns = layouts[0].get("columns") or {}
            lines.append(
                "- Page/Layout: "
                f"{page.get('width')}x{page.get('height')}, body="
                f"{page.get('body_width')}x{page.get('body_height')}, margins={page.get('margins')}, "
                f"columns={columns}"
            )

        font_faces = report["header"]["font_faces"]
        lines.append("- Font faces:")
        for lang, fonts in font_faces.items():
            face_values = ", ".join(f"{font_id}:{face}" for font_id, face in fonts.items())
            lines.append(f"  - `{lang}`: {face_values}")

        lines.append("")
        lines.append("### Top Character Styles")
        lines.append("")
        lines.append("| charPr | Runs | Chars | Roles | Style | Samples |")
        lines.append("| --- | ---: | ---: | --- | --- | --- |")
        for usage in report["sections"]["char_style_usage"][:12]:
            roles = ", ".join(f"{k}:{v}" for k, v in (usage.get("roles") or {}).items())
            samples = "<br>".join(usage.get("samples") or [])
            lines.append(
                f"| {usage.get('id')} | {usage.get('runs')} | {usage.get('chars')} | "
                f"{roles} | {_style_brief(usage.get('style') or {})} | {samples} |"
            )

        lines.append("")
        lines.append("### Top Paragraph Styles")
        lines.append("")
        lines.append("| paraPr | Paragraphs | Nonempty | Roles | Style | Samples |")
        lines.append("| --- | ---: | ---: | --- | --- | --- |")
        for usage in report["sections"]["para_style_usage"][:12]:
            roles = ", ".join(f"{k}:{v}" for k, v in (usage.get("roles") or {}).items())
            samples = "<br>".join(usage.get("samples") or [])
            lines.append(
                f"| {usage.get('id')} | {usage.get('paragraphs')} | {usage.get('nonempty')} | "
                f"{roles} | {_para_brief(usage.get('style') or {})} | {samples} |"
            )

        lines.append("")
        lines.append("### Equation Patterns")
        lines.append("")
        patterns = report["sections"].get("equation_pattern_counts") or {}
        lines.append(", ".join(f"`{key}`={value}" for key, value in patterns.items()) or "No equations.")
        examples = report["sections"].get("equation_examples") or []
        if examples:
            lines.append("")
            lines.append("Representative scripts:")
            for item in examples[:8]:
                script = str(item.get("script") or "").replace("|", "\\|")
                lines.append(f"- `{script}`")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("samples", nargs="*", type=Path, help="HWP sample paths; defaults to Downloads exam HWP files.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--no-keep-exports", action="store_true", help="Delete intermediate exported HWPX files.")
    args = parser.parse_args(argv)

    if rhwp is None:
        print(f"rhwp is not available: {_RHWP_IMPORT_ERROR}", file=sys.stderr)
        return 2

    samples = [path.expanduser().resolve() for path in args.samples] if args.samples else _discover_default_samples()
    samples = [path for path in samples if path.exists()]
    if not samples:
        print("No HWP samples found. Pass paths explicitly or put samples in Downloads.", file=sys.stderr)
        return 2

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for path in samples:
        print(f"analyze: {path.name}")
        reports.append(_analyze_one(path, out_dir, keep_exports=not args.no_keep_exports))

    json_path = out_dir / "hwp_template_analysis.json"
    md_path = out_dir / "hwp_template_analysis.md"
    json_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(reports, md_path)

    print(f"\n{'source':<44} {'pages':>5} {'eq':>5} {'fonts':>5} {'char':>5} {'para':>5} top char style")
    print("-" * 100)
    for report in reports:
        top_style = ""
        usage = report["sections"]["char_style_usage"]
        if usage:
            top_style = f"{usage[0].get('id')} ({_style_brief(usage[0].get('style') or {})})"
        print(
            f"{report['source_name'][:44]:<44} "
            f"{str(report['rhwp'].get('page_count')):>5} "
            f"{str(report['rhwp'].get('formula_count')):>5} "
            f"{str(report['header']['counts'].get('font_faces')):>5} "
            f"{str(report['header']['counts'].get('char_properties')):>5} "
            f"{str(report['header']['counts'].get('para_properties')):>5} "
            f"{top_style}"
        )
    print(f"\nJSON: {json_path}")
    print(f"Markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
