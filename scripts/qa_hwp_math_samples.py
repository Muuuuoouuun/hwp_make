# -*- coding: utf-8 -*-
"""End-to-end QA for math-heavy HWP samples.

The script imports every supplied KICE-style math HWP, exports native-math HWPX,
inspects the generated XML, and renders all pages with rhwp to catch layout
overflow. It is intentionally stricter than the small unit verifiers because it
targets the real sample workflow.

Usage:
    python scripts/qa_hwp_math_samples.py
    python scripts/qa_hwp_math_samples.py "C:/path/sample.hwp" --save-pages 3
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree as ET

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HWP_MAKE_DATA_DIR", str(ROOT / "data" / "hwp_math_sample_qa"))

from app import hwpx_writer, hwpx_writer_v2, importers, math_text, storage  # noqa: E402


HP_NS = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
MATH_WORD = "\uc218\ud559"
EDIT_WORD = "\ud3b8\uc9d1"
EXPECTED_SAMPLE_NAMES = (
    "2024\ub144 3\uc6d4 \uad50\uc721\uccad \ubaa8\uc758\uace0\uc0ac \uc218\ud559(\ud3b8\uc9d1).hwp",
    "2024\ub144 5\uc6d4 \uad50\uc721\uccad \ubaa8\uc758\uace0\uc0ac \uc218\ud559(\ud3b8\uc9d1).hwp",
    "2024\ub144 6\uc6d4 \ud3c9\uac00\uc6d0 \ubaa8\uc758\uace0\uc0ac \uc218\ud559(\ud3b8\uc9d1).hwp",
    "2025\ud559\ub144\ub3c4 \uc218\ub2a5 \uc218\ud559(\ud3b8\uc9d1).hwp",
)
PROBLEM_LABEL_RE = re.compile(r"^\s*(?P<number>\d{1,3})\.\s*")
UNIT_MARKER_RE = re.compile("^\\s*\\[(?P<score>\\d+\\s*점)\\]\\[(?P<section>.*?)(?P<number>\\d{1,3})\\]\\s*$")
HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
BAD_EQN_SQRT_RE = re.compile(
    r"(?<![A-Za-z])sqrt(?=\{|[A-Za-z0-9])|(?<![A-Za-z])sqrt\s*(?=$|[^\s{])"
)
MOJIBAKE_TEXT_PATTERNS = (
    "臾몄젣",
    "鍮좊Ⅸ",
    "?뺣떟",
    "?댁꽕",
    "?깅챸",
    "?섑뿕",
    "泥⑤",
    "留묒?",
)


def _safe_stem(value: str, index: int) -> str:
    stem = re.sub(r"[^0-9A-Za-z_-]+", "_", value).strip("_")
    return (stem[:72] or f"sample_{index:02d}").lower()


def _discover_samples() -> list[Path]:
    downloads = Path.home() / "Downloads"
    return sorted(
        path
        for path in downloads.glob("*.hwp")
        if path.name.startswith("202") and MATH_WORD in path.name and EDIT_WORD in path.name
    )


def _discover_default_samples() -> tuple[list[Path], list[str]]:
    discovered = _discover_samples()
    by_name = {path.name: path for path in discovered}
    missing = [name for name in EXPECTED_SAMPLE_NAMES if name not in by_name]
    ordered = [by_name[name] for name in EXPECTED_SAMPLE_NAMES if name in by_name]
    extras = [path for path in discovered if path.name not in EXPECTED_SAMPLE_NAMES]
    return [*ordered, *extras], missing


def _inspect_hwpx(path: Path) -> dict[str, Any]:
    def paragraph_text(paragraph: ET.Element, *, include_nested_paragraphs: bool = False) -> str:
        texts: list[str] = []

        def walk(node: ET.Element) -> None:
            for child in list(node):
                if (
                    not include_nested_paragraphs
                    and child is not paragraph
                    and child.tag == f"{HP_NS}p"
                ):
                    continue
                if child.tag == f"{HP_NS}t":
                    texts.append(child.text or "")
                walk(child)

        walk(paragraph)
        return "".join(texts).strip()

    def paragraph_equations(paragraph: ET.Element) -> list[ET.Element]:
        found: list[ET.Element] = []

        def walk(node: ET.Element) -> None:
            for child in list(node):
                if child is not paragraph and child.tag == f"{HP_NS}p":
                    continue
                if child.tag == f"{HP_NS}equation":
                    found.append(child)
                walk(child)

        walk(paragraph)
        return found

    def equation_script(equation: ET.Element) -> str:
        return "".join(node.text or "" for node in equation.iter(f"{HP_NS}script")).strip()

    def equation_object_issues(
        equation: ET.Element,
        *,
        section_name: str,
        equation_index: int,
    ) -> list[dict[str, Any]]:
        script = equation_script(equation)
        reasons: list[str] = []
        for attr, expected in (
            ("numberingType", "EQUATION"),
            ("lineMode", "CHAR"),
            ("font", "HancomEQN"),
        ):
            if equation.get(attr) != expected:
                reasons.append(f"{attr}={equation.get(attr)!r}")
        if not equation.get("id"):
            reasons.append("missing id")
        if not equation.get("zOrder"):
            reasons.append("missing zOrder")
        if not equation.get("version"):
            reasons.append("missing version")
        if not script:
            reasons.append("missing script")

        sz = equation.find(f"{HP_NS}sz")
        if sz is None:
            reasons.append("missing sz")
        else:
            if sz.get("widthRelTo") != "ABSOLUTE":
                reasons.append(f"sz.widthRelTo={sz.get('widthRelTo')!r}")
            if sz.get("heightRelTo") != "ABSOLUTE":
                reasons.append(f"sz.heightRelTo={sz.get('heightRelTo')!r}")
            if sz.get("protect") not in {"0", None}:
                reasons.append(f"sz.protect={sz.get('protect')!r}")

        pos = equation.find(f"{HP_NS}pos")
        if pos is None:
            reasons.append("missing pos")
        else:
            for attr, expected in (
                ("treatAsChar", "1"),
                ("flowWithText", "1"),
                ("allowOverlap", "0"),
                ("vertRelTo", "PARA"),
                ("horzRelTo", "PARA"),
            ):
                if pos.get(attr) != expected:
                    reasons.append(f"pos.{attr}={pos.get(attr)!r}")

        if equation.find(f"{HP_NS}outMargin") is None:
            reasons.append("missing outMargin")
        if equation.find(f"{HP_NS}script") is None:
            reasons.append("missing script node")

        if not reasons:
            return []
        return [
            {
                "section": section_name,
                "equation": equation_index,
                "id": equation.get("id"),
                "zOrder": equation.get("zOrder"),
                "script": script[:120],
                "reasons": reasons,
            }
        ]

    def iter_outer_paragraphs(node: ET.Element):
        for child in list(node):
            if child.tag == f"{HP_NS}p":
                yield child
            else:
                yield from iter_outer_paragraphs(child)

    def table_summary(table: ET.Element, section_name: str, table_index: int) -> dict[str, Any]:
        table_texts = [
            paragraph_text(paragraph)
            for paragraph in table.iter(f"{HP_NS}p")
            if paragraph_text(paragraph)
        ]
        marker_count = sum(
            text.count(marker)
            for text in table_texts
            for marker in importers.CIRCLED_CHOICE_MARKERS
        )
        is_choice_grid = marker_count >= 3
        summary_text = " | ".join(table_texts)
        full_text = "\n".join(table_texts)
        return {
            "section": section_name,
            "table": table_index,
            "kind": "choice_grid" if is_choice_grid else "content",
            "rows": sum(1 for _ in table.iter(f"{HP_NS}tr")),
            "cells": sum(1 for _ in table.iter(f"{HP_NS}tc")),
            "marker_count": marker_count,
            "text": summary_text[:180],
            "full_text": full_text,
        }

    with zipfile.ZipFile(path) as archive:
        section_names = sorted(
            name for name in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", name)
        )
        paragraphs = []
        equations = []
        equation_scripts: list[str] = []
        hangul_equation_scripts: list[str] = []
        delimited_equation_scripts: list[str] = []
        malformed_equation_scripts: list[dict[str, Any]] = []
        equation_object_issue_list: list[dict[str, Any]] = []
        equation_ids: list[str] = []
        equation_zorders: list[str] = []
        math_paragraphs = []
        math_lineseg_paragraphs = []
        math_lineseg_issues: list[dict[str, Any]] = []
        paragraph_texts: list[str] = []
        source_marker_texts: list[str] = []
        problem_label_numbers: list[str] = []
        picture_count = 0
        content_table_count = 0
        choice_grid_table_count = 0
        table_summaries: list[dict[str, Any]] = []
        output_segments: list[dict[str, Any]] = []
        column_breaks: list[tuple[str, int]] = []
        orphan_source_markers: list[dict[str, Any]] = []
        choice_table_breaks: list[dict[str, Any]] = []
        oversized_objects: list[dict[str, Any]] = []
        col_pr_count = 0
        for name in section_names:
            root = ET.fromstring(archive.read(name))
            col_pr_count += sum(1 for _ in root.iter(f"{HP_NS}colPr"))
            picture_count += sum(1 for _ in root.iter(f"{HP_NS}pic"))
            for table_index, table in enumerate(root.iter(f"{HP_NS}tbl"), start=1):
                summary = table_summary(table, name, table_index)
                if summary["kind"] == "choice_grid":
                    choice_grid_table_count += 1
                else:
                    content_table_count += 1
                if len(table_summaries) < 20:
                    table_summaries.append(summary)
            section_equations = list(root.iter(f"{HP_NS}equation"))
            equations.extend(section_equations)
            for equation_index, equation in enumerate(section_equations, start=1):
                if equation.get("id"):
                    equation_ids.append(str(equation.get("id")))
                if equation.get("zOrder"):
                    equation_zorders.append(str(equation.get("zOrder")))
                equation_object_issue_list.extend(
                    equation_object_issues(
                        equation,
                        section_name=name,
                        equation_index=equation_index,
                    )
                )
                script = equation_script(equation)
                if script:
                    equation_scripts.append(script)
                    if HANGUL_RE.search(script):
                        hangul_equation_scripts.append(script)
                    if "$" in script:
                        delimited_equation_scripts.append(script)
                    if BAD_EQN_SQRT_RE.search(script):
                        malformed_equation_scripts.append(
                            {
                                "section": name,
                                "equation": equation_index,
                                "script": script[:160],
                            }
                        )
            for index, paragraph in enumerate(root.iter(f"{HP_NS}p")):
                paragraphs.append(paragraph)
                para_text = paragraph_text(paragraph)
                nested_para_text = paragraph_text(paragraph, include_nested_paragraphs=True)
                if para_text:
                    paragraph_texts.append(para_text)
                    if UNIT_MARKER_RE.match(para_text):
                        source_marker_texts.append(para_text)
                    label_match = PROBLEM_LABEL_RE.match(para_text)
                    if label_match:
                        problem_label_numbers.append(label_match.group("number"))
                para_equations = paragraph_equations(paragraph)
                if para_equations:
                    math_paragraphs.append(paragraph)
                    lineseg = paragraph.find(f"{HP_NS}linesegarray/{HP_NS}lineseg")
                    if lineseg is not None:
                        math_lineseg_paragraphs.append(paragraph)
                        try:
                            actual_height = int(lineseg.get("textheight") or lineseg.get("vertsize") or "0")
                        except ValueError:
                            actual_height = 0
                        scripts = [equation_script(equation) for equation in para_equations]
                        expected_height = max(
                            [1200, *[hwpx_writer._equation_size(script)[1] for script in scripts if script]]
                        )
                        if actual_height < expected_height:
                            math_lineseg_issues.append(
                                {
                                    "section": name,
                                    "paragraph": index,
                                    "actual": actual_height,
                                    "expected": expected_height,
                                    "scripts": scripts[:4],
                                }
                            )
                if paragraph.get("columnBreak") == "1":
                    column_breaks.append((name, index))
                if UNIT_MARKER_RE.match(para_text) and (
                    paragraph.get("columnBreak") == "1" or paragraph.get("pageBreak") == "1"
                ):
                    orphan_source_markers.append(
                        {
                            "section": name,
                            "paragraph": index,
                            "text": para_text,
                            "columnBreak": paragraph.get("columnBreak"),
                            "pageBreak": paragraph.get("pageBreak"),
                        }
                    )
                if (
                    list(paragraph.iter(f"{HP_NS}tbl"))
                    and any(marker in nested_para_text for marker in importers.CIRCLED_CHOICE_MARKERS)
                    and (paragraph.get("columnBreak") == "1" or paragraph.get("pageBreak") == "1")
                ):
                    choice_table_breaks.append(
                        {
                            "section": name,
                            "paragraph": index,
                            "text": nested_para_text[:120],
                            "columnBreak": paragraph.get("columnBreak"),
                            "pageBreak": paragraph.get("pageBreak"),
                        }
                    )
                for size_node in paragraph.iter(f"{HP_NS}sz"):
                    try:
                        width = int(size_node.get("width") or "0")
                        height = int(size_node.get("height") or "0")
                    except ValueError:
                        continue
                    if width > 0 and height > 30000:
                        oversized_objects.append(
                            {
                                "section": name,
                                "paragraph": index,
                                "width": width,
                                "height": height,
                                "text": para_text[:80],
                            }
                        )
            current_segment = {
                "source_marker": "",
                "problem_labels": [],
                "choice_markers": 0,
                "pictures": 0,
                "content_tables": 0,
                "choice_grid_tables": 0,
                "equation_scripts": [],
                "text_parts": [],
            }
            for paragraph in iter_outer_paragraphs(root):
                para_text = paragraph_text(paragraph)
                if para_text:
                    current_segment["text_parts"].append(para_text)
                label_match = PROBLEM_LABEL_RE.match(para_text)
                if label_match:
                    current_segment["problem_labels"].append(label_match.group("number"))
                current_segment["choice_markers"] += sum(
                    para_text.count(marker)
                    for marker in importers.CIRCLED_CHOICE_MARKERS
                )
                current_segment["pictures"] += sum(1 for _ in paragraph.iter(f"{HP_NS}pic"))
                for equation in paragraph_equations(paragraph):
                    script = equation_script(equation)
                    if script:
                        current_segment["equation_scripts"].append(script)
                for table_index, table in enumerate(paragraph.iter(f"{HP_NS}tbl"), start=1):
                    summary = table_summary(table, name, table_index)
                    if summary.get("full_text"):
                        current_segment["text_parts"].append(str(summary["full_text"]))
                    current_segment["choice_markers"] += int(summary.get("marker_count") or 0)
                    if summary["kind"] == "choice_grid":
                        current_segment["choice_grid_tables"] += 1
                    else:
                        current_segment["content_tables"] += 1
                    for equation in table.iter(f"{HP_NS}equation"):
                        script = equation_script(equation)
                        if script:
                            current_segment["equation_scripts"].append(script)
                if UNIT_MARKER_RE.match(para_text):
                    current_segment["source_marker"] = para_text
                    snapshot = dict(current_segment)
                    snapshot["text"] = "\n".join(str(part) for part in snapshot.pop("text_parts", []) if part)
                    output_segments.append(snapshot)
                    current_segment = {
                        "source_marker": "",
                        "problem_labels": [],
                        "choice_markers": 0,
                        "pictures": 0,
                        "content_tables": 0,
                        "choice_grid_tables": 0,
                        "equation_scripts": [],
                        "text_parts": [],
                    }
    return {
        "sections": len(section_names),
        "paragraphs": len(paragraphs),
        "equations": len(equations),
        "equation_scripts": equation_scripts,
        "paragraph_texts": paragraph_texts,
        "source_marker_texts": source_marker_texts,
        "problem_label_numbers": problem_label_numbers,
        "pictures": picture_count,
        "content_tables": content_table_count,
        "choice_grid_tables": choice_grid_table_count,
        "table_summaries": table_summaries,
        "output_segments": output_segments,
        "hangul_equation_scripts": hangul_equation_scripts,
        "delimited_equation_scripts": delimited_equation_scripts,
        "malformed_equation_scripts": malformed_equation_scripts[:20],
        "malformed_equation_script_count": len(malformed_equation_scripts),
        "equation_object_issues": equation_object_issue_list[:20],
        "equation_object_issue_count": len(equation_object_issue_list),
        "duplicate_equation_ids": [
            value for value, count in Counter(equation_ids).items() if count > 1
        ][:20],
        "duplicate_equation_zorders": [
            value for value, count in Counter(equation_zorders).items() if count > 1
        ][:20],
        "math_paragraphs": len(math_paragraphs),
        "math_lineseg_paragraphs": len(math_lineseg_paragraphs),
        "math_lineseg_issues": math_lineseg_issues[:20],
        "math_lineseg_issue_count": len(math_lineseg_issues),
        "column_breaks": column_breaks,
        "orphan_source_markers": orphan_source_markers,
        "choice_table_breaks": choice_table_breaks,
        "oversized_objects": oversized_objects,
        "col_pr_count": col_pr_count,
    }


def _render_hwpx(
    path: Path,
    png_dir: Path,
    save_pages: int,
    timeout_sec: int = 240,
) -> dict[str, Any]:
    code = r"""
import io
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

path = Path(sys.argv[1])
png_dir = Path(sys.argv[2])
save_pages = int(sys.argv[3])

def _prepare_png_dir():
    if save_pages == 0:
        return
    png_dir.mkdir(parents=True, exist_ok=True)
    for old in png_dir.glob(f"{path.stem}.page*.png"):
        try:
            old.unlink()
        except OSError:
            pass
    contact = png_dir / f"{path.stem}.contact.png"
    try:
        contact.unlink()
    except OSError:
        pass

def _write_contact_sheet(saved_pages):
    if not saved_pages:
        return ""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return ""
    thumbs = []
    for page_no, page_path in enumerate(saved_pages, start=1):
        try:
            image = Image.open(page_path).convert("RGB")
        except Exception:
            continue
        image.thumbnail((220, 310))
        thumbs.append((page_no, image.copy()))
    if not thumbs:
        return ""
    cols = 4
    label_h = 24
    pad = 14
    cell_w = 220 + pad * 2
    cell_h = 310 + label_h + pad * 2
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (page_no, image) in enumerate(thumbs):
        col = index % cols
        row = index // cols
        x = col * cell_w + pad
        y = row * cell_h + pad
        draw.text((x, y), f"page {page_no}", fill=(30, 30, 30))
        sheet.paste(image, (x, y + label_h))
        draw.rectangle(
            [x, y + label_h, x + image.width - 1, y + label_h + image.height - 1],
            outline=(190, 190, 190),
        )
    contact = png_dir / f"{path.stem}.contact.png"
    sheet.save(contact)
    return str(contact)

def _column_crossing_issues(png_bytes, page_number):
    try:
        from PIL import Image
    except Exception:
        return []
    image = Image.open(io.BytesIO(png_bytes)).convert("L")
    width, height = image.size
    pix = image.load()
    y0, y1 = int(height * 0.12), int(height * 0.90)
    separator_score = 0
    separator_x = width // 2
    for x in range(int(width * 0.45), int(width * 0.55)):
        score = sum(1 for y in range(y0, y1) if pix[x, y] < 150)
        if score > separator_score:
            separator_score = score
            separator_x = x
    if separator_score <= (y1 - y0) * 0.35:
        separator_x = width // 2

    x0, x1 = int(width * 0.25), int(width * 0.75)
    y0, y1 = int(height * 0.12), int(height * 0.92)
    visited = set()
    issues = []

    def dark(x, y):
        if abs(x - separator_x) <= 2:
            return False
        return pix[x, y] < 130

    for y in range(y0, y1):
        for x in range(x0, x1):
            if (x, y) in visited or not dark(x, y):
                continue
            stack = [(x, y)]
            visited.add((x, y))
            min_x = max_x = x
            min_y = max_y = y
            count = 0
            while stack:
                cx, cy = stack.pop()
                count += 1
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)
                for nx in (cx - 1, cx, cx + 1):
                    for ny in (cy - 1, cy, cy + 1):
                        if nx == cx and ny == cy:
                            continue
                        if nx < x0 or nx >= x1 or ny < y0 or ny >= y1:
                            continue
                        if (nx, ny) in visited or not dark(nx, ny):
                            continue
                        visited.add((nx, ny))
                        stack.append((nx, ny))
            if count >= 20 and min_x < separator_x - 8 and max_x > separator_x + 8:
                issues.append({
                    "page": page_number,
                    "separator_x": separator_x,
                    "bbox": [min_x, min_y, max_x, max_y],
                    "pixels": count,
                })
                if len(issues) >= 8:
                    return issues
    return issues

def _ink_density(png_bytes):
    try:
        from PIL import Image
    except Exception:
        return None
    image = Image.open(io.BytesIO(png_bytes)).convert("L")
    width, height = image.size
    pix = image.load()
    x0, x1 = int(width * 0.06), int(width * 0.94)
    y0, y1 = int(height * 0.08), int(height * 0.94)
    total = max(1, (x1 - x0) * (y1 - y0))
    dark = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            if pix[x, y] < 220:
                dark += 1
    return round(dark / total, 5)

def _content_bounds(png_bytes, page_number):
    try:
        from PIL import Image
    except Exception:
        return {"page": page_number, "bbox": None}
    image = Image.open(io.BytesIO(png_bytes)).convert("L")
    width, height = image.size
    pix = image.load()
    x0, x1 = int(width * 0.03), int(width * 0.97)
    y0, y1 = int(height * 0.04), int(height * 0.98)
    min_x = width
    min_y = height
    max_x = -1
    max_y = -1
    dark_pixels = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            if pix[x, y] < 220:
                dark_pixels += 1
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if max_x < 0:
        return {"page": page_number, "bbox": None, "dark_pixels": 0}
    return {
        "page": page_number,
        "bbox": [min_x, min_y, max_x, max_y],
        "bbox_ratio": [
            round(min_x / width, 4),
            round(min_y / height, 4),
            round(max_x / width, 4),
            round(max_y / height, 4),
        ],
        "width_ratio": round((max_x - min_x + 1) / width, 4),
        "height_ratio": round((max_y - min_y + 1) / height, 4),
        "dark_pixels": dark_pixels,
    }

try:
    import rhwp
    _prepare_png_dir()
    document = rhwp.parse(str(path))
    page_count = int(document.page_count)
    render_bytes = []
    ink_densities = []
    content_bounds = []
    saved_pages = []
    column_crossing_issues = []
    for page_index in range(page_count):
        png = bytes(document.render_png(page_index))
        render_bytes.append(len(png))
        ink_densities.append(_ink_density(png))
        content_bounds.append(_content_bounds(png, page_index + 1))
        column_crossing_issues.extend(_column_crossing_issues(png, page_index + 1))
        if save_pages < 0 or page_index < save_pages:
            png_dir.mkdir(parents=True, exist_ok=True)
            png_path = png_dir / f"{path.stem}.page{page_index + 1}.png"
            png_path.write_bytes(png)
            saved_pages.append(str(png_path))
    contact_sheet = _write_contact_sheet(saved_pages)
    print(json.dumps({
        "available": True,
        "page_count": page_count,
        "render_bytes": render_bytes,
        "ink_densities": ink_densities,
        "content_bounds": content_bounds,
        "saved_pages": saved_pages,
        "contact_sheet": contact_sheet,
        "column_crossing_issues": column_crossing_issues,
    }, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({
        "available": True,
        "error": f"{type(exc).__name__}: {exc}",
    }, ensure_ascii=False))
    raise
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(path), str(png_dir), str(save_pages)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
    )
    log = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    json_lines = [line for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    if not json_lines:
        return {
            "available": False,
            "error": f"rhwp subprocess produced no JSON (exit {completed.returncode})",
            "log_tail": log.splitlines()[-20:],
        }
    try:
        report = json.loads(json_lines[-1])
    except json.JSONDecodeError as exc:
        return {
            "available": False,
            "error": f"rhwp subprocess JSON parse failed: {exc}",
            "log_tail": log.splitlines()[-20:],
        }
    overflow_lines = [line for line in log.splitlines() if "LAYOUT_OVERFLOW" in line]
    report["overflow_count"] = len(overflow_lines)
    report["overflow_lines"] = overflow_lines[:20]
    report["log_tail"] = log.splitlines()[-20:]
    if completed.returncode != 0 and not report.get("error"):
        report["error"] = f"rhwp subprocess exited {completed.returncode}"
    return report


def _blank_equation_scripts(path: Path, control_dir: Path) -> Path:
    control_dir.mkdir(parents=True, exist_ok=True)
    control_path = control_dir / f"{path.stem}_blank_equations{path.suffix}"
    with zipfile.ZipFile(path, "r") as archive:
        infos = archive.infolist()
        payloads = {info.filename: archive.read(info.filename) for info in infos}

    updates: dict[str, bytes] = {}
    for name, data in payloads.items():
        if not re.fullmatch(r"Contents/section\d+\.xml", name):
            continue
        root = ET.fromstring(data)
        changed = False
        for script in root.iter(f"{HP_NS}script"):
            if script.text:
                script.text = ""
                changed = True
        if changed:
            updates[name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    with zipfile.ZipFile(control_path, "w") as out:
        for info in infos:
            out.writestr(info, updates.get(info.filename, payloads[info.filename]))
    return control_path


def _equation_render_visibility(path: Path, inspect: dict[str, Any]) -> dict[str, Any]:
    if int(inspect.get("equations") or 0) <= 0:
        return {"available": True, "skipped": True, "reason": "no native equations"}
    control_path = _blank_equation_scripts(path, storage.EXPORT_DIR / "equation_controls")
    code = r"""
import json
import sys
from io import BytesIO
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

actual_path = Path(sys.argv[1])
control_path = Path(sys.argv[2])

try:
    import rhwp
    from PIL import Image, ImageChops
except Exception as exc:
    print(json.dumps({"available": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
    raise SystemExit(0)

try:
    actual = rhwp.parse(str(actual_path))
    control = rhwp.parse(str(control_path))
    page_count = min(int(actual.page_count), int(control.page_count))
    changed_total = 0
    pixel_total = 0
    page_diffs = []
    for page_index in range(page_count):
        actual_png = bytes(actual.render_png(page_index))
        control_png = bytes(control.render_png(page_index))
        actual_image = Image.open(BytesIO(actual_png)).convert("L")
        control_image = Image.open(BytesIO(control_png)).convert("L")
        if actual_image.size != control_image.size:
            control_image = control_image.resize(actual_image.size)
        diff = ImageChops.difference(actual_image, control_image)
        hist = diff.histogram()
        changed = sum(count for value, count in enumerate(hist) if value > 30)
        total = actual_image.width * actual_image.height
        changed_total += changed
        pixel_total += total
        page_diffs.append({
            "page": page_index + 1,
            "changed_pixels": changed,
            "total_pixels": total,
            "changed_ratio": round(changed / total, 6) if total else 0,
        })
    print(json.dumps({
        "available": True,
        "page_count": page_count,
        "actual_page_count": int(actual.page_count),
        "control_page_count": int(control.page_count),
        "changed_pixels": changed_total,
        "total_pixels": pixel_total,
        "changed_ratio": round(changed_total / pixel_total, 6) if pixel_total else 0,
        "page_diffs": page_diffs,
    }, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"available": True, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
    raise
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(path), str(control_path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
    )
    log = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    json_lines = [line for line in completed.stdout.splitlines() if line.strip().startswith("{")]
    if not json_lines:
        return {
            "available": False,
            "control_path": str(control_path),
            "error": f"equation visibility subprocess produced no JSON (exit {completed.returncode})",
            "log_tail": log.splitlines()[-20:],
        }
    try:
        report = json.loads(json_lines[-1])
    except json.JSONDecodeError as exc:
        return {
            "available": False,
            "control_path": str(control_path),
            "error": f"equation visibility subprocess JSON parse failed: {exc}",
            "log_tail": log.splitlines()[-20:],
        }
    report["control_path"] = str(control_path)
    report["log_tail"] = log.splitlines()[-20:]
    if completed.returncode != 0 and not report.get("error"):
        report["error"] = f"equation visibility subprocess exited {completed.returncode}"
    return report


def _choice_failures(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for index, item in enumerate(items, start=1):
        count = len(item.get("choices") or [])
        if count not in (0, 5):
            failures.append(
                {
                    "index": index,
                    "number": item.get("number"),
                    "choice_count": count,
                    "unit": item.get("unit"),
                }
            )
    return failures


def _number_failures(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for index, item in enumerate(items, start=1):
        number = str(item.get("number") or "").strip()
        if not number.isdigit() or not 1 <= int(number) <= 46:
            failures.append({"index": index, "number": number, "unit": item.get("unit")})
            continue
        unit = str(item.get("unit") or "")
        unit_number = re.search(r"(\d{1,2})\]\s*$", unit)
        if unit_number and str(int(unit_number.group(1))) != number:
            failures.append({"index": index, "number": number, "unit": unit})
    return failures


def _section_sequences(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sequences: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for index, item in enumerate(items, start=1):
        unit = str(item.get("unit") or "")
        match = UNIT_MARKER_RE.match(unit)
        if not match:
            continue
        section = match.group("section").strip()
        number = int(match.group("number"))
        entry = {"index": index, "number": number, "unit": unit}
        if current is None or current["section"] != section:
            current = {"section": section, "items": [entry]}
            sequences.append(current)
        else:
            current["items"].append(entry)
    return sequences


def _section_sequence_failures(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    seen_sections: set[str] = set()
    for sequence in _section_sequences(items):
        section = str(sequence["section"])
        if section in seen_sections:
            failures.append({"section": section, "reason": "section appears in multiple separated runs"})
        seen_sections.add(section)
        entries = list(sequence.get("items") or [])
        numbers = [int(entry["number"]) for entry in entries]
        if not numbers:
            continue
        expected = list(range(numbers[0], numbers[0] + len(numbers)))
        if numbers != expected:
            failures.append(
                {
                    "section": section,
                    "reason": "numbers are not consecutive in document order",
                    "actual": numbers,
                    "expected": expected,
                    "units": [entry["unit"] for entry in entries[:12]],
                }
            )
    return failures


def _leading_choice_leak_failures(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    markers = re.escape(importers.CIRCLED_CHOICE_MARKERS)
    leading_choice_re = re.compile(rf"^\s*[{markers}]")
    failures = []
    for index, item in enumerate(items, start=1):
        if not (item.get("choices") or []):
            continue
        stem = str(item.get("stem") or "")
        if leading_choice_re.match(stem):
            failures.append(
                {
                    "index": index,
                    "number": item.get("number"),
                    "unit": item.get("unit"),
                    "stem_start": stem[:80],
                }
            )
    return failures


def _answer_section_leak_failures(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    answer_re = re.compile(r"(?:\[\uc815\ub2f5\]|\ube60\ub978\s*\uc815\ub2f5|\uc815\ub2f5\s*(?:\ubc0f|\uacfc)\s*\ud574\uc124)")
    failures = []
    for index, item in enumerate(items, start=1):
        table_text = " ".join(
            str(cell or "")
            for table in (item.get("tables") or [])
            if isinstance(table, list)
            for row in table
            if isinstance(row, list)
            for cell in row
        )
        combined = "\n".join([str(item.get("stem") or ""), table_text])
        if answer_re.search(combined):
            failures.append(
                {
                    "index": index,
                    "number": item.get("number"),
                    "unit": item.get("unit"),
                    "text": combined[:160],
                }
            )
    return failures


def _known_sample_sync_failures(path: Path, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if "2025" not in path.name:
        return failures

    def find(unit_suffix: str) -> dict[str, Any] | None:
        return next((item for item in items if str(item.get("unit") or "").endswith(unit_suffix)), None)

    common13 = find("\uc218\ub2a5 13]")
    common14 = find("\uc218\ub2a5 14]")
    common15 = find("\uc218\ub2a5 15]")
    geo30 = find("\uc218\ub2a5 \uae30\ud55830]")
    checks = [
        (
            common13,
            "2025 common 13 graph",
            lambda item: len(item.get("image_paths") or []) == 1
            and len(item.get("choices") or []) == 5
            and any("37" in str(choice) for choice in item.get("choices") or []),
        ),
        (
            common14,
            "2025 common 14 geometry",
            lambda item: len(item.get("image_paths") or []) == 1
            and len(item.get("choices") or []) == 5
            and any("sqrt{3}" in str(choice) for choice in item.get("choices") or []),
        ),
        (
            common15,
            "2025 common 15 table",
            lambda item: len(item.get("image_paths") or []) == 0
            and len(item.get("tables") or []) == 1
            and (item.get("choices") or [])[:2] == ["30", "32"],
        ),
        (
            geo30,
            "2025 geometry 30 final problem",
            lambda item: len(item.get("image_paths") or []) == 1
            and "\ube60\ub978" not in str(item.get("tables") or ""),
        ),
    ]
    for item, label, predicate in checks:
        if item is None or not predicate(item):
            failures.append(
                {
                    "check": label,
                    "item": {
                        "unit": item.get("unit") if item else None,
                        "choices": item.get("choices") if item else None,
                        "images": item.get("image_paths") if item else None,
                        "tables": len(item.get("tables") or []) if item else None,
                    },
                }
            )
    return failures


def _table_math_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    table_count = 0
    tables_with_math = 0
    math_spans = 0
    examples: list[dict[str, Any]] = []
    for item in items:
        for table_index, table in enumerate(item.get("tables") or []):
            if not isinstance(table, list):
                continue
            table_count += 1
            table_spans = math_text.analyze_problem_math({"tables": [table]})
            math_spans += len(table_spans)
            if table_spans:
                tables_with_math += 1
                if len(examples) < 8:
                    text = " | ".join(" / ".join(str(cell or "") for cell in row) for row in table)
                    examples.append(
                        {
                            "number": item.get("number"),
                            "unit": item.get("unit"),
                            "table": table_index,
                            "math_spans": len(table_spans),
                            "text": text[:180],
                        }
                    )
    return {
        "tables": table_count,
        "tables_with_math": tables_with_math,
        "math_spans": math_spans,
        "examples": examples,
    }


def _expected_item_math_scripts(item: dict[str, Any]) -> list[str]:
    scripts: list[str] = []

    def add_text(value: Any) -> None:
        for segment, is_math in math_text.split_math_text(str(value or "")):
            if not is_math:
                continue
            script = hwpx_writer._hancom_eqn_script(segment)
            if script:
                scripts.append(script)

    add_text(item.get("stem"))
    for choice in item.get("choices") or []:
        add_text(choice)
    for table in item.get("tables") or []:
        if not isinstance(table, list):
            continue
        for row in table:
            if not isinstance(row, list):
                continue
            for cell in row:
                add_text(cell)
    return scripts


def _expected_math_scripts(items: list[dict[str, Any]]) -> list[str]:
    scripts: list[str] = []
    for item in items:
        scripts.extend(_expected_item_math_scripts(item))
    return scripts


def _math_script_mismatch(expected: list[str], actual: list[str]) -> dict[str, Any] | None:
    expected_counter = Counter(expected)
    actual_counter = Counter(actual)
    missing_counter = expected_counter - actual_counter
    extra_counter = actual_counter - expected_counter
    if not missing_counter and not extra_counter:
        return None

    def sample(counter: Counter[str]) -> list[dict[str, Any]]:
        return [
            {"script": script, "count": count}
            for script, count in counter.most_common(8)
        ]

    return {
        "expected": len(expected),
        "actual": len(actual),
        "missing": sample(missing_counter),
        "extra": sample(extra_counter),
    }


def _sequence_mismatch(expected: list[str], actual: list[str]) -> dict[str, Any] | None:
    expected_counter = Counter(expected)
    actual_counter = Counter(actual)
    missing_counter = expected_counter - actual_counter
    extra_counter = actual_counter - expected_counter
    first_mismatch = None
    for index, (expected_value, actual_value) in enumerate(zip(expected, actual), start=1):
        if expected_value != actual_value:
            first_mismatch = {
                "index": index,
                "expected": expected_value,
                "actual": actual_value,
            }
            break
    if first_mismatch is None and len(expected) != len(actual):
        first_mismatch = {
            "index": min(len(expected), len(actual)) + 1,
            "expected": expected[min(len(expected), len(actual))] if len(expected) > len(actual) else None,
            "actual": actual[min(len(expected), len(actual))] if len(actual) > len(expected) else None,
        }
    if not missing_counter and not extra_counter and first_mismatch is None:
        return None

    def sample(counter: Counter[str]) -> list[dict[str, Any]]:
        return [
            {"value": value, "count": count}
            for value, count in counter.most_common(8)
        ]

    return {
        "expected": len(expected),
        "actual": len(actual),
        "first_mismatch": first_mismatch,
        "missing": sample(missing_counter),
        "extra": sample(extra_counter),
    }


def _output_sync_summary(items: list[dict[str, Any]], inspect: dict[str, Any]) -> dict[str, Any]:
    expected_labels = [
        str(item.get("number") or index).strip()
        for index, item in enumerate(items, start=1)
    ]
    expected_markers = [
        str(item.get("unit") or "").strip()
        for item in items
        if str(item.get("unit") or "").strip()
    ]
    expected_choice_counts = [len(item.get("choices") or []) for item in items]
    actual_labels = [str(value).strip() for value in inspect.get("problem_label_numbers") or []]
    actual_markers = [str(value).strip() for value in inspect.get("source_marker_texts") or []]
    output_segments = [segment for segment in inspect.get("output_segments") or [] if isinstance(segment, dict)]
    actual_choice_counts = [int(segment.get("choice_markers") or 0) for segment in output_segments]
    choice_count_mismatches = [
        {
            "index": index,
            "number": items[index - 1].get("number") if index - 1 < len(items) else None,
            "unit": items[index - 1].get("unit") if index - 1 < len(items) else None,
            "expected": expected,
            "actual": actual,
        }
        for index, (expected, actual) in enumerate(zip(expected_choice_counts, actual_choice_counts), start=1)
        if expected != actual
    ]
    if len(expected_choice_counts) != len(actual_choice_counts):
        longer = expected_choice_counts if len(expected_choice_counts) > len(actual_choice_counts) else actual_choice_counts
        for index in range(min(len(expected_choice_counts), len(actual_choice_counts)) + 1, len(longer) + 1):
            choice_count_mismatches.append(
                {
                    "index": index,
                    "number": items[index - 1].get("number") if index - 1 < len(items) else None,
                    "unit": items[index - 1].get("unit") if index - 1 < len(items) else None,
                    "expected": expected_choice_counts[index - 1] if index - 1 < len(expected_choice_counts) else None,
                    "actual": actual_choice_counts[index - 1] if index - 1 < len(actual_choice_counts) else None,
                }
            )
    return {
        "expected_problem_labels": len(expected_labels),
        "actual_problem_labels": len(actual_labels),
        "expected_source_markers": len(expected_markers),
        "actual_source_markers": len(actual_markers),
        "expected_choice_counts": len(expected_choice_counts),
        "actual_choice_counts": len(actual_choice_counts),
        "choice_count_mismatch_count": len(choice_count_mismatches),
        "choice_count_mismatches": choice_count_mismatches[:12],
        "problem_label_mismatch": _sequence_mismatch(expected_labels, actual_labels),
        "source_marker_mismatch": _sequence_mismatch(expected_markers, actual_markers),
        "problem_label_sample": actual_labels[:12],
        "source_marker_sample": actual_markers[:12],
    }


def _text_has_math(value: Any) -> bool:
    return any(is_math and segment for segment, is_math in math_text.split_math_text(str(value or "")))


def _object_sync_summary(items: list[dict[str, Any]], inspect: dict[str, Any]) -> dict[str, Any]:
    expected_pictures = sum(len(item.get("image_paths") or []) for item in items)
    expected_content_tables = sum(len(item.get("tables") or []) for item in items)
    expected_choice_grids = sum(
        1
        for item in items
        if item.get("choices") and any(_text_has_math(choice) for choice in item.get("choices") or [])
    )
    actual_pictures = int(inspect.get("pictures") or 0)
    actual_content_tables = int(inspect.get("content_tables") or 0)
    actual_choice_grids = int(inspect.get("choice_grid_tables") or 0)
    mismatches = []
    for key, expected, actual in (
        ("pictures", expected_pictures, actual_pictures),
        ("content_tables", expected_content_tables, actual_content_tables),
        ("choice_grid_tables", expected_choice_grids, actual_choice_grids),
    ):
        if expected != actual:
            mismatches.append({"kind": key, "expected": expected, "actual": actual})
    return {
        "expected_pictures": expected_pictures,
        "actual_pictures": actual_pictures,
        "expected_content_tables": expected_content_tables,
        "actual_content_tables": actual_content_tables,
        "expected_choice_grid_tables": expected_choice_grids,
        "actual_choice_grid_tables": actual_choice_grids,
        "mismatches": mismatches,
        "table_summaries": inspect.get("table_summaries") or [],
    }


def _problem_inventory_summary(items: list[dict[str, Any]], inspect: dict[str, Any]) -> dict[str, Any]:
    segments = [segment for segment in inspect.get("output_segments") or [] if isinstance(segment, dict)]
    entries: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        segment = segments[index - 1] if index - 1 < len(segments) else {}
        choices = item.get("choices") or []
        expected_choice_grid = 1 if choices and any(_text_has_math(choice) for choice in choices) else 0
        expected_equations = _expected_item_math_scripts(item)
        actual_equations = [str(script or "").strip() for script in segment.get("equation_scripts") or []]
        expected = {
            "label": str(item.get("number") or index).strip(),
            "source_marker": str(item.get("unit") or "").strip(),
            "choices": len(choices),
            "pictures": len(item.get("image_paths") or []),
            "content_tables": len(item.get("tables") or []),
            "choice_grid_tables": expected_choice_grid,
            "equations": len(expected_equations),
        }
        actual_labels = [str(value).strip() for value in segment.get("problem_labels") or []]
        actual = {
            "labels": actual_labels,
            "source_marker": str(segment.get("source_marker") or "").strip(),
            "choices": int(segment.get("choice_markers") or 0),
            "pictures": int(segment.get("pictures") or 0),
            "content_tables": int(segment.get("content_tables") or 0),
            "choice_grid_tables": int(segment.get("choice_grid_tables") or 0),
            "equations": len(actual_equations),
        }
        entry_mismatches = []
        if actual["labels"] != [expected["label"]]:
            entry_mismatches.append({"field": "label", "expected": expected["label"], "actual": actual["labels"]})
        for field in ("source_marker", "choices", "pictures", "content_tables", "choice_grid_tables"):
            if expected[field] != actual[field]:
                entry_mismatches.append({"field": field, "expected": expected[field], "actual": actual[field]})
        equation_mismatch = _math_script_mismatch(expected_equations, actual_equations)
        if equation_mismatch:
            entry_mismatches.append(
                {
                    "field": "equations",
                    "expected": len(expected_equations),
                    "actual": len(actual_equations),
                    "detail": equation_mismatch,
                }
            )
        entry = {
            "index": index,
            "number": item.get("number"),
            "unit": item.get("unit"),
            "expected": expected,
            "actual": actual,
            "mismatches": entry_mismatches,
        }
        entries.append(entry)
        if entry_mismatches:
            mismatches.append(entry)
    if len(segments) != len(items):
        mismatches.append(
            {
                "index": None,
                "number": None,
                "unit": None,
                "expected": {"segments": len(items)},
                "actual": {"segments": len(segments)},
                "mismatches": [
                    {"field": "segments", "expected": len(items), "actual": len(segments)}
                ],
            }
        )
    return {
        "problem_count": len(items),
        "output_segment_count": len(segments),
        "expected_equations": sum(int(entry["expected"].get("equations") or 0) for entry in entries),
        "actual_equations": sum(int(entry["actual"].get("equations") or 0) for entry in entries),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:12],
        "entries": entries,
    }


def _visible_non_math_text(value: Any) -> str:
    return "".join(
        segment
        for segment, is_math in math_text.split_math_text(str(value or ""))
        if not is_math
    )


def _normalize_visible_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"^\s*[①②③④⑤]\s*", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def _is_checkable_text_fragment(value: str) -> bool:
    if len(value) < 2:
        return False
    return any(char.isalnum() or "\uac00" <= char <= "\ud7a3" for char in value)


def _expected_visible_fragments(item: dict[str, Any], index: int) -> list[dict[str, str]]:
    fragments: list[dict[str, str]] = []

    def add(field: str, value: Any) -> None:
        visible = _visible_non_math_text(value)
        for raw_line in visible.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            if field == "stem":
                line = hwpx_writer._strip_question_prefix(
                    line,
                    str(item.get("number") or index),
                ).strip()
            norm = _normalize_visible_text(line)
            if _is_checkable_text_fragment(norm):
                fragments.append({"field": field, "text": line, "norm": norm})

    add("stem", item.get("stem"))
    for choice_index, choice in enumerate(item.get("choices") or [], start=1):
        add(f"choice{choice_index}", choice)
    for table_index, table in enumerate(item.get("tables") or [], start=1):
        if not isinstance(table, list):
            continue
        for row_index, row in enumerate(table, start=1):
            if not isinstance(row, list):
                continue
            for col_index, cell in enumerate(row, start=1):
                add(f"table{table_index}r{row_index}c{col_index}", cell)
    return fragments


def _text_sync_summary(items: list[dict[str, Any]], inspect: dict[str, Any]) -> dict[str, Any]:
    segments = [segment for segment in inspect.get("output_segments") or [] if isinstance(segment, dict)]
    entries: list[dict[str, Any]] = []
    missing_entries: list[dict[str, Any]] = []
    total_expected = 0
    total_missing = 0
    for index, item in enumerate(items, start=1):
        segment = segments[index - 1] if index - 1 < len(segments) else {}
        actual_norm = _normalize_visible_text(segment.get("text") or "")
        expected_fragments = _expected_visible_fragments(item, index)
        missing = [
            {
                "field": fragment["field"],
                "text": fragment["text"][:120],
            }
            for fragment in expected_fragments
            if fragment["norm"] not in actual_norm
        ]
        entry = {
            "index": index,
            "number": item.get("number"),
            "unit": item.get("unit"),
            "expected_fragments": len(expected_fragments),
            "missing_count": len(missing),
            "missing": missing[:8],
        }
        entries.append(entry)
        total_expected += len(expected_fragments)
        total_missing += len(missing)
        if missing:
            missing_entries.append(entry)
    if len(segments) != len(items):
        missing_entries.append(
            {
                "index": None,
                "number": None,
                "unit": None,
                "expected_fragments": 0,
                "missing_count": 1,
                "missing": [
                    {
                        "field": "segments",
                        "text": f"expected {len(items)} output segments, got {len(segments)}",
                    }
                ],
            }
        )
        total_missing += 1
    return {
        "expected_fragments": total_expected,
        "missing_count": total_missing,
        "problem_count": len(items),
        "output_segment_count": len(segments),
        "mismatches": missing_entries[:12],
        "entries": entries,
    }


def _mojibake_text_hits(inspect: dict[str, Any]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for index, text in enumerate(inspect.get("paragraph_texts") or [], start=1):
        value = str(text or "")
        matched = [pattern for pattern in MOJIBAKE_TEXT_PATTERNS if pattern in value]
        if matched:
            hits.append(
                {
                    "paragraph": index,
                    "patterns": matched,
                    "text": value[:160],
                }
            )
            if len(hits) >= 12:
                break
    return hits


def _density_summary(values: list[Any]) -> dict[str, float | int | None]:
    densities = sorted(float(value) for value in values if isinstance(value, (int, float)))
    if not densities:
        return {"count": 0, "min": None, "median": None, "max": None}
    middle = len(densities) // 2
    median = densities[middle] if len(densities) % 2 else (densities[middle - 1] + densities[middle]) / 2
    return {
        "count": len(densities),
        "min": round(densities[0], 5),
        "median": round(median, 5),
        "max": round(densities[-1], 5),
    }


def _ranked_page_values(values: list[Any], *, reverse: bool = True, limit: int = 3) -> list[dict[str, float | int]]:
    ranked = [
        {"page": page, "value": round(float(value), 5)}
        for page, value in enumerate(values, start=1)
        if isinstance(value, (int, float))
    ]
    ranked.sort(key=lambda item: float(item["value"]), reverse=reverse)
    return ranked[:limit]


def _layout_metric_summary(render: dict[str, Any]) -> dict[str, Any]:
    bounds = [bound for bound in (render.get("content_bounds") or []) if isinstance(bound, dict)]

    def ranked_bound_value(key: str, *, reverse: bool = True) -> list[dict[str, float | int]]:
        values = [
            {"page": int(bound.get("page") or 0), "value": round(float(bound.get(key) or 0), 5)}
            for bound in bounds
            if isinstance(bound.get(key), (int, float))
        ]
        values.sort(key=lambda item: float(item["value"]), reverse=reverse)
        return values[:3]

    margins = []
    for bound in bounds:
        ratios = bound.get("bbox_ratio")
        if not ratios:
            continue
        left, top, right, bottom = [float(value) for value in ratios]
        margins.append(
            {
                "page": int(bound.get("page") or 0),
                "left": round(left, 5),
                "top": round(top, 5),
                "right": round(1 - right, 5),
                "bottom": round(1 - bottom, 5),
            }
        )
    tightest_margins: dict[str, dict[str, float | int] | None] = {}
    for key in ("left", "top", "right", "bottom"):
        ordered = sorted(margins, key=lambda item: float(item[key]))
        tightest_margins[key] = ordered[0] if ordered else None
    return {
        "page_count": render.get("page_count"),
        "overflow_count": render.get("overflow_count"),
        "column_crossing_count": len(render.get("column_crossing_issues") or []),
        "densest_pages": _ranked_page_values(render.get("ink_densities") or []),
        "widest_content_pages": ranked_bound_value("width_ratio"),
        "tallest_content_pages": ranked_bound_value("height_ratio"),
        "tightest_margins": tightest_margins,
    }


def _review_flags(report: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if report.get("failures"):
        flags.append("QA failure present")
    density_ratio = (report.get("density_summary") or {}).get("output_to_source_median_ratio")
    if isinstance(density_ratio, (int, float)):
        if density_ratio > 1.65:
            flags.append(f"output is much denser than source ({density_ratio})")
        elif density_ratio < 0.75:
            flags.append(f"output is much lighter than source ({density_ratio})")
    source_pages = (report.get("source_render") or {}).get("page_count")
    output_pages = (report.get("render") or {}).get("page_count")
    if isinstance(source_pages, int) and source_pages and isinstance(output_pages, int):
        page_ratio = output_pages / source_pages
        if page_ratio < 0.32:
            flags.append(f"output is highly compressed ({output_pages}/{source_pages} pages)")
        elif page_ratio > 0.7:
            flags.append(f"output page count is close to source ({output_pages}/{source_pages} pages)")
    output_summary = (report.get("layout_summary") or {}).get("output") or {}
    widest = (output_summary.get("widest_content_pages") or [{}])[0].get("value")
    tallest = (output_summary.get("tallest_content_pages") or [{}])[0].get("value")
    if isinstance(widest, (int, float)) and widest > 0.82:
        flags.append(f"wide content bbox on output page ({widest})")
    if isinstance(tallest, (int, float)) and tallest > 0.84:
        flags.append(f"tall content bbox on output page ({tallest})")
    return flags


def _relative_uri(path_value: object, base_dir: Path) -> str:
    if not isinstance(path_value, str) or not path_value:
        return ""
    path = Path(path_value)
    if not path.is_absolute():
        path = ROOT / path
    try:
        relative = path.resolve().relative_to(base_dir.resolve())
        text = relative.as_posix()
    except ValueError:
        text = path.resolve().as_uri()
    if text.startswith("file:"):
        return text
    return quote(text, safe="/:#?&=%")


def _write_review_html(reports: list[dict[str, Any]], report_path: Path, review_path: Path) -> None:
    base_dir = review_path.parent

    def esc(value: object) -> str:
        return html.escape("" if value is None else str(value), quote=True)

    def link(path_value: object, label: str) -> str:
        href = _relative_uri(path_value, base_dir)
        if not href:
            return ""
        return f'<a href="{href}">{esc(label)}</a>'

    def metric_list(summary: dict[str, Any]) -> str:
        densest = ", ".join(f"p{item['page']} {item['value']}" for item in summary.get("densest_pages") or [])
        widest = ", ".join(f"p{item['page']} {item['value']}" for item in summary.get("widest_content_pages") or [])
        tallest = ", ".join(f"p{item['page']} {item['value']}" for item in summary.get("tallest_content_pages") or [])
        return (
            f"<dl>"
            f"<dt>Pages</dt><dd>{esc(summary.get('page_count'))}</dd>"
            f"<dt>Overflow</dt><dd>{esc(summary.get('overflow_count'))}</dd>"
            f"<dt>Column Cross</dt><dd>{esc(summary.get('column_crossing_count'))}</dd>"
            f"<dt>Densest</dt><dd>{esc(densest)}</dd>"
            f"<dt>Widest</dt><dd>{esc(widest)}</dd>"
            f"<dt>Tallest</dt><dd>{esc(tallest)}</dd>"
            f"</dl>"
        )

    def equation_visibility_cell(visibility: dict[str, Any]) -> str:
        page_diffs = [page for page in visibility.get("page_diffs") or [] if isinstance(page, dict)]
        weak_pages = [
            page
            for page in page_diffs
            if int(page.get("changed_pixels") or 0) < 700
            or float(page.get("changed_ratio") or 0) < 0.0008
        ]
        min_ratio = min((float(page.get("changed_ratio") or 0) for page in page_diffs), default=None)
        min_pixels = min((int(page.get("changed_pixels") or 0) for page in page_diffs), default=None)
        return (
            f"{esc(visibility.get('changed_pixels'))}/{esc(visibility.get('changed_ratio'))}"
            f"<br><span class=\"muted\">min p {esc(min_pixels)}/{esc(min_ratio)}, weak {esc(len(weak_pages))}</span>"
        )

    def inventory_table(problem_inventory: dict[str, Any]) -> str:
        rows = []
        for entry in problem_inventory.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            expected = entry.get("expected") or {}
            actual = entry.get("actual") or {}
            mismatches = entry.get("mismatches") or []
            row_class = ' class="bad"' if mismatches else ""
            mismatch_text = "; ".join(str(item.get("field") or item) for item in mismatches) if mismatches else "-"
            rows.append(
                f"<tr{row_class}>"
                f"<td>{esc(entry.get('index'))}</td>"
                f"<td>{esc(entry.get('unit'))}</td>"
                f"<td>{esc('/'.join(actual.get('labels') or []))}/{esc(expected.get('label'))}</td>"
                f"<td>{esc(actual.get('equations'))}/{esc(expected.get('equations'))}</td>"
                f"<td>{esc(actual.get('choices'))}/{esc(expected.get('choices'))}</td>"
                f"<td>{esc(actual.get('pictures'))}/{esc(expected.get('pictures'))}</td>"
                f"<td>{esc(actual.get('content_tables'))}/{esc(expected.get('content_tables'))}</td>"
                f"<td>{esc(actual.get('choice_grid_tables'))}/{esc(expected.get('choice_grid_tables'))}</td>"
                f"<td>{esc(mismatch_text)}</td>"
                "</tr>"
            )
        return (
            "<details class=\"inventory\"><summary>Problem Inventory</summary>"
            "<table>"
            "<thead><tr><th>#</th><th>Unit</th><th>Label</th><th>Eq</th><th>Choices</th><th>Pictures</th><th>Tables</th><th>Choice Grids</th><th>Mismatches</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
            "</details>"
        )

    def text_sync_table(text_sync: dict[str, Any]) -> str:
        rows = []
        entries = text_sync.get("entries") or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            missing = entry.get("missing") or []
            if not missing:
                continue
            missing_text = "; ".join(
                f"{item.get('field')}: {item.get('text')}"
                for item in missing
                if isinstance(item, dict)
            )
            rows.append(
                "<tr class=\"bad\">"
                f"<td>{esc(entry.get('index'))}</td>"
                f"<td>{esc(entry.get('unit'))}</td>"
                f"<td>{esc(entry.get('missing_count'))}/{esc(entry.get('expected_fragments'))}</td>"
                f"<td>{esc(missing_text)}</td>"
                "</tr>"
            )
        if not rows:
            return (
                "<details class=\"inventory\"><summary>Text Sync</summary>"
                f"<p class=\"flags\">No missing visible text fragments "
                f"({esc(text_sync.get('expected_fragments'))} checked).</p>"
                "</details>"
            )
        return (
            "<details class=\"inventory\"><summary>Text Sync</summary>"
            "<table>"
            "<thead><tr><th>#</th><th>Unit</th><th>Missing</th><th>Fragments</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
            "</details>"
        )

    overview_rows = []
    sample_sections = []
    for report in reports:
        source_name = Path(str(report.get("source") or "")).name
        render = report.get("render") or {}
        source_render = report.get("source_render") or {}
        density = report.get("density_summary") or {}
        output_sync = report.get("output_sync") or {}
        object_sync = report.get("object_sync") or {}
        problem_inventory = report.get("problem_inventory") or {}
        text_sync = report.get("text_sync") or {}
        equation_visibility = report.get("equation_visibility") or {}
        mojibake_hits = report.get("mojibake_hits") or []
        flags = report.get("review_flags") or []
        status = "FAIL" if report.get("failures") else ("REVIEW" if flags else "OK")
        overview_rows.append(
            "<tr>"
            f"<td>{esc(source_name)}</td>"
            f"<td>{esc(status)}</td>"
            f"<td>{esc(report.get('created'))}</td>"
            f"<td>{esc(report.get('choice_dist'))}</td>"
            f"<td>{esc((report.get('inspect') or {}).get('equations'))}</td>"
            f"<td>{esc(problem_inventory.get('actual_equations'))}/{esc(problem_inventory.get('expected_equations'))}</td>"
            f"<td>{equation_visibility_cell(equation_visibility)}</td>"
            f"<td>{esc(output_sync.get('actual_problem_labels'))}/{esc(output_sync.get('expected_problem_labels'))}</td>"
            f"<td>{esc(output_sync.get('actual_source_markers'))}/{esc(output_sync.get('expected_source_markers'))}</td>"
            f"<td>{esc(output_sync.get('choice_count_mismatch_count'))}</td>"
            f"<td>{esc(object_sync.get('actual_pictures'))}/{esc(object_sync.get('expected_pictures'))}</td>"
            f"<td>{esc(object_sync.get('actual_content_tables'))}/{esc(object_sync.get('expected_content_tables'))}</td>"
            f"<td>{esc(object_sync.get('actual_choice_grid_tables'))}/{esc(object_sync.get('expected_choice_grid_tables'))}</td>"
            f"<td>{esc(problem_inventory.get('mismatch_count'))}</td>"
            f"<td>{esc(text_sync.get('missing_count'))}/{esc(text_sync.get('expected_fragments'))}</td>"
            f"<td>{esc(len(mojibake_hits))}</td>"
            f"<td>{esc(source_render.get('page_count'))}/{esc(render.get('page_count'))}</td>"
            f"<td>{esc(density.get('output_to_source_median_ratio'))}</td>"
            f"<td>{esc('; '.join(flags) or '-')}</td>"
            "</tr>"
        )
        output_contact = _relative_uri(render.get("contact_sheet"), base_dir)
        source_contact = _relative_uri(source_render.get("contact_sheet"), base_dir)
        links = " ".join(
            value
            for value in (
                link(report.get("source"), "source HWP"),
                link(report.get("output"), "output HWPX"),
                link(render.get("contact_sheet"), "output contact"),
                link(source_render.get("contact_sheet"), "source contact"),
            )
            if value
        )
        output_summary = ((report.get("layout_summary") or {}).get("output") or {})
        source_summary = ((report.get("layout_summary") or {}).get("source") or {})
        sample_sections.append(
            "<section>"
            f"<h2>{esc(source_name)}</h2>"
            f"<p class=\"links\">{links}</p>"
            f"<p class=\"flags\">{esc('; '.join(flags) or 'No review flags')}</p>"
            "<div class=\"metrics\">"
            f"<div><h3>Source Metrics</h3>{metric_list(source_summary)}</div>"
            f"<div><h3>Output Metrics</h3>{metric_list(output_summary)}</div>"
            "</div>"
            f"{inventory_table(problem_inventory)}"
            f"{text_sync_table(text_sync)}"
            "<div class=\"compare\">"
            f"<figure><figcaption>Source Render</figcaption><img src=\"{source_contact}\" alt=\"source contact sheet\"></figure>"
            f"<figure><figcaption>Output Render</figcaption><img src=\"{output_contact}\" alt=\"output contact sheet\"></figure>"
            "</div>"
            "</section>"
        )

    html_text = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>HWP Math Sample QA Review</title>
  <style>
    body {{ font-family: Arial, "Malgun Gothic", sans-serif; margin: 24px; color: #202124; }}
    h1 {{ font-size: 24px; margin: 0 0 8px; }}
    h2 {{ font-size: 20px; margin: 32px 0 8px; border-top: 1px solid #d0d7de; padding-top: 18px; }}
    h3 {{ font-size: 15px; margin: 0 0 8px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 18px 0 24px; font-size: 13px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 7px 8px; vertical-align: top; }}
    th {{ background: #f6f8fa; text-align: left; }}
    a {{ color: #0969da; margin-right: 12px; }}
    .links, .flags {{ font-size: 13px; margin: 6px 0; }}
    .flags {{ color: #6e7781; }}
    .muted {{ color: #6e7781; font-size: 12px; }}
    .metrics {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 14px 0; }}
    .metrics > div {{ border: 1px solid #d0d7de; padding: 12px; }}
    .inventory {{ margin: 14px 0 18px; }}
    .inventory summary {{ cursor: pointer; font-weight: 700; font-size: 13px; }}
    .inventory table {{ margin: 10px 0 0; font-size: 12px; }}
    .inventory tr.bad td {{ background: #fff5f5; }}
    dl {{ display: grid; grid-template-columns: 120px 1fr; gap: 4px 10px; margin: 0; font-size: 13px; }}
    dt {{ color: #57606a; }}
    dd {{ margin: 0; }}
    .compare {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; align-items: start; }}
    figure {{ margin: 0; }}
    figcaption {{ font-size: 13px; font-weight: 700; margin: 0 0 8px; }}
    img {{ max-width: 100%; border: 1px solid #d0d7de; background: white; }}
    @media (max-width: 1100px) {{
      .metrics, .compare {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <h1>HWP Math Sample QA Review</h1>
  <p>JSON report: {link(str(report_path), "hwp_math_sample_qa_report.json")}</p>
  <table>
    <thead><tr><th>Sample</th><th>Status</th><th>Problems</th><th>Choices</th><th>Eq</th><th>Eq Inv</th><th>Eq Visible</th><th>Labels</th><th>Markers</th><th>Choice Sync Issues</th><th>Pictures</th><th>Tables</th><th>Choice Grids</th><th>Problem Inv Issues</th><th>Text Missing</th><th>Mojibake</th><th>Source/Output Pages</th><th>Density Ratio</th><th>Review Flags</th></tr></thead>
    <tbody>{"".join(overview_rows)}</tbody>
  </table>
  {"".join(sample_sections)}
</body>
</html>
"""
    review_path.write_text(html_text, encoding="utf-8")


def _clean_saved_render_artifacts() -> None:
    targets = (
        (storage.EXPORT_DIR / "renders", ("*_native_math.page*.png", "*_native_math.contact.png")),
        (storage.EXPORT_DIR / "source_renders", ("*.page*.png", "*.contact.png")),
        (storage.EXPORT_DIR / "equation_controls", ("*_blank_equations.hwpx",)),
    )
    for render_dir, patterns in targets:
        if not render_dir.exists():
            continue
        for pattern in patterns:
            for path in render_dir.glob(pattern):
                try:
                    path.unlink()
                except OSError:
                    pass


def _run_one(
    path: Path,
    index: int,
    *,
    save_pages: int,
    save_source_pages: int,
    template_key: str,
    render_source: bool,
) -> dict[str, Any]:
    storage.DB_PATH = storage.DATA_DIR / f"qa_sample_{os.getpid()}_{index:02d}.sqlite3"
    storage.DB_PATH.unlink(missing_ok=True)
    storage.init_db()

    result = importers.import_hwp(path.name, path.read_bytes(), {})
    items = list(result.get("created") or [])
    choice_dist = Counter(len(item.get("choices") or []) for item in items)

    out_path = storage.EXPORT_DIR / f"{index:02d}_{_safe_stem(path.stem, index)}_native_math.hwpx"
    hwpx_writer_v2.write_hwpx(
        out_path,
        f"{path.stem} native math QA",
        items,
        template_key=template_key,
        native_math=True,
    )

    inspect = _inspect_hwpx(out_path)
    render = _render_hwpx(out_path, storage.EXPORT_DIR / "renders", save_pages)
    equation_visibility = _equation_render_visibility(out_path, inspect)
    source_render = (
        _render_hwpx(path, storage.EXPORT_DIR / "source_renders", save_source_pages)
        if render_source
        else {}
    )
    source_density = _density_summary(source_render.get("ink_densities") or [])
    output_density = _density_summary(render.get("ink_densities") or [])
    layout_summary = {
        "source": _layout_metric_summary(source_render) if source_render else {},
        "output": _layout_metric_summary(render),
    }
    source_median = source_density.get("median")
    output_median = output_density.get("median")
    density_ratio = (
        round(float(output_median) / float(source_median), 3)
        if isinstance(source_median, (int, float)) and source_median
        and isinstance(output_median, (int, float))
        else None
    )
    table_math = _table_math_summary(items)
    expected_scripts = _expected_math_scripts(items)
    script_mismatch = _math_script_mismatch(expected_scripts, inspect["equation_scripts"])
    output_sync = _output_sync_summary(items, inspect)
    object_sync = _object_sync_summary(items, inspect)
    problem_inventory = _problem_inventory_summary(items, inspect)
    text_sync = _text_sync_summary(items, inspect)
    mojibake_hits = _mojibake_text_hits(inspect)

    failures: list[str] = []
    if len(items) != 46:
        failures.append(f"expected 46 imported problems for KICE-style math sample, got {len(items)}")
    bad_choices = _choice_failures(items)
    if bad_choices:
        failures.append(f"bad choice counts: {bad_choices[:8]}")
    bad_numbers = _number_failures(items)
    if bad_numbers:
        failures.append(f"problem number/source marker mismatch: {bad_numbers[:8]}")
    bad_sequences = _section_sequence_failures(items)
    if bad_sequences:
        failures.append(f"problem order is not consecutive within source sections: {bad_sequences[:8]}")
    leaked_choices = _leading_choice_leak_failures(items)
    if leaked_choices:
        failures.append(f"leading stale choice blocks in stems: {leaked_choices[:8]}")
    answer_leaks = _answer_section_leak_failures(items)
    if answer_leaks:
        failures.append(f"answer/solution section leaked into imported problems: {answer_leaks[:8]}")
    sync_failures = _known_sample_sync_failures(path, items)
    if sync_failures:
        failures.append(f"known image/choice/problem sync regressions: {sync_failures[:8]}")
    if any(not (item.get("unit") or "").strip() for item in items):
        failures.append("one or more problems are missing source/unit markers")
    if table_math["tables"] and table_math["tables_with_math"] == 0:
        failures.append(f"table formulas were not preserved: {table_math}")
    if inspect["equations"] < 30:
        failures.append(f"too few native equations in HWPX: {inspect['equations']}")
    if inspect.get("hangul_equation_scripts"):
        failures.append(
            "Hangul text leaked into native equation scripts: "
            f"{inspect['hangul_equation_scripts'][:8]}"
        )
    if inspect.get("delimited_equation_scripts"):
        failures.append(
            "Math delimiters leaked into native equation scripts: "
            f"{inspect['delimited_equation_scripts'][:8]}"
        )
    if inspect.get("malformed_equation_script_count"):
        failures.append(
            "Malformed native equation scripts may render incorrectly: "
            f"{inspect['malformed_equation_scripts'][:8]}"
        )
    if inspect.get("equation_object_issue_count"):
        failures.append(
            "native equation objects are missing edit/layout attributes: "
            f"{inspect['equation_object_issues'][:8]}"
        )
    if inspect.get("duplicate_equation_ids"):
        failures.append(f"duplicate native equation ids: {inspect['duplicate_equation_ids'][:8]}")
    if inspect.get("duplicate_equation_zorders"):
        failures.append(f"duplicate native equation zOrder values: {inspect['duplicate_equation_zorders'][:8]}")
    if script_mismatch:
        failures.append(f"native equation scripts do not match imported math: {script_mismatch}")
    if equation_visibility.get("error"):
        failures.append(f"native equation render visibility check failed: {equation_visibility['error']}")
    elif not equation_visibility.get("skipped"):
        if equation_visibility.get("actual_page_count") != equation_visibility.get("control_page_count"):
            failures.append(
                "native equation visibility control changed page count: "
                f"{equation_visibility.get('actual_page_count')}/{equation_visibility.get('control_page_count')}"
            )
        changed_pixels = int(equation_visibility.get("changed_pixels") or 0)
        changed_ratio = float(equation_visibility.get("changed_ratio") or 0)
        min_changed_pixels = max(4000, int(inspect.get("equations") or 0) * 8)
        if changed_pixels < min_changed_pixels or changed_ratio < 0.001:
            failures.append(
                "native equations do not visibly affect render versus blank-script control: "
                f"changed_pixels={changed_pixels}, changed_ratio={changed_ratio}, "
                f"min_changed_pixels={min_changed_pixels}"
            )
        weak_pages = [
            page
            for page in equation_visibility.get("page_diffs") or []
            if isinstance(page, dict)
            and (
                int(page.get("changed_pixels") or 0) < 700
                or float(page.get("changed_ratio") or 0) < 0.0008
            )
        ]
        if weak_pages:
            failures.append(
                "one or more pages have weak native equation render visibility: "
                f"{weak_pages[:8]}"
            )
    if output_sync.get("problem_label_mismatch"):
        failures.append(f"output problem labels are out of sync: {output_sync['problem_label_mismatch']}")
    if output_sync.get("source_marker_mismatch"):
        failures.append(f"output source markers are out of sync: {output_sync['source_marker_mismatch']}")
    if output_sync.get("choice_count_mismatch_count"):
        failures.append(f"output choice marker counts are out of sync: {output_sync['choice_count_mismatches']}")
    if object_sync.get("mismatches"):
        failures.append(f"output picture/table objects are out of sync: {object_sync['mismatches']}")
    if problem_inventory.get("mismatch_count"):
        failures.append(f"per-problem output inventory is out of sync: {problem_inventory['mismatches']}")
    if text_sync.get("missing_count"):
        failures.append(f"per-problem visible text is missing from output: {text_sync['mismatches']}")
    if mojibake_hits:
        failures.append(f"mojibake text leaked into output paragraphs: {mojibake_hits}")
    if inspect["math_paragraphs"] != inspect["math_lineseg_paragraphs"]:
        failures.append(
            "some equation paragraphs are missing line segment height reservations: "
            f"{inspect['math_lineseg_paragraphs']}/{inspect['math_paragraphs']}"
        )
    if inspect.get("math_lineseg_issue_count"):
        failures.append(
            "some equation paragraphs reserve less height than their formulas need: "
            f"{inspect['math_lineseg_issues'][:8]}"
        )
    if inspect["col_pr_count"] < 1:
        failures.append("missing 2-column definition")
    if inspect.get("orphan_source_markers"):
        failures.append(f"source markers start a new page/column by themselves: {inspect['orphan_source_markers'][:8]}")
    if inspect.get("choice_table_breaks"):
        failures.append(f"choice grids start a new page/column away from their stems: {inspect['choice_table_breaks'][:8]}")
    if inspect.get("oversized_objects"):
        failures.append(f"drawings are taller than a two-column math layout can safely hold: {inspect['oversized_objects'][:8]}")
    if render.get("error"):
        failures.append(f"rhwp render failed: {render['error']}")
    if render.get("overflow_count"):
        failures.append(f"rhwp layout overflow count: {render['overflow_count']}")
    if render.get("column_crossing_issues"):
        failures.append(f"rendered content crosses the two-column separator: {render['column_crossing_issues'][:8]}")
    content_bound_issues = []
    for bound in render.get("content_bounds") or []:
        bbox_ratio = bound.get("bbox_ratio") if isinstance(bound, dict) else None
        if not bbox_ratio:
            continue
        left, top, right, bottom = [float(value) for value in bbox_ratio]
        width_ratio = float(bound.get("width_ratio") or 0)
        height_ratio = float(bound.get("height_ratio") or 0)
        if left < 0.035 or top < 0.055 or right > 0.965 or bottom > 0.935:
            content_bound_issues.append({"reason": "outside safe page bounds", **bound})
        elif width_ratio > 0.86 or height_ratio > 0.88:
            content_bound_issues.append({"reason": "content bbox is unusually large", **bound})
    if content_bound_issues:
        failures.append(f"rendered content bounding boxes look unsafe: {content_bound_issues[:8]}")
    if render.get("render_bytes") and any(int(size) < 5000 for size in render["render_bytes"]):
        failures.append(f"one or more rendered pages are suspiciously small: {render['render_bytes']}")
    densities = [value for value in (render.get("ink_densities") or []) if isinstance(value, (int, float))]
    blank_like_pages = [
        {"page": page, "density": density}
        for page, density in enumerate(densities, start=1)
        if density < 0.004
    ]
    overfull_like_pages = [
        {"page": page, "density": density}
        for page, density in enumerate(densities, start=1)
        if density > 0.12
    ]
    if blank_like_pages:
        failures.append(f"one or more rendered pages look blank: {blank_like_pages[:8]}")
    if overfull_like_pages:
        failures.append(f"one or more rendered pages look over-dense: {overfull_like_pages[:8]}")

    report = {
        "source": str(path),
        "output": str(out_path),
        "created": len(items),
        "choice_dist": dict(sorted(choice_dist.items())),
        "first_unit": items[0].get("unit") if items else "",
        "last_unit": items[-1].get("unit") if items else "",
        "section_sequences": [
            {
                "section": sequence["section"],
                "numbers": [entry["number"] for entry in sequence.get("items") or []],
            }
            for sequence in _section_sequences(items)
        ],
        "messages": result.get("messages") or [],
        "table_math": table_math,
        "expected_equation_scripts": len(expected_scripts),
        "math_script_mismatch": script_mismatch,
        "equation_visibility": equation_visibility,
        "output_sync": output_sync,
        "object_sync": object_sync,
        "problem_inventory": problem_inventory,
        "text_sync": text_sync,
        "mojibake_hits": mojibake_hits,
        "source_render": source_render,
        "density_summary": {
            "source": source_density,
            "output": output_density,
            "output_to_source_median_ratio": density_ratio,
        },
        "layout_summary": layout_summary,
        "inspect": inspect,
        "render": render,
        "failures": failures,
    }
    report["review_flags"] = _review_flags(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("samples", nargs="*", type=Path, help="HWP sample paths. Defaults to Downloads math samples.")
    parser.add_argument("--save-pages", type=int, default=2, help="PNG pages to save per output; -1 saves all pages.")
    parser.add_argument(
        "--save-source-pages",
        type=int,
        default=0,
        help="PNG pages to save per source HWP render; -1 saves all pages.",
    )
    parser.add_argument("--template-key", default="kice_math")
    parser.add_argument(
        "--skip-source-render",
        action="store_true",
        help="Do not render source HWP files for report-only comparison metrics.",
    )
    args = parser.parse_args(argv)

    storage.ensure_dirs()
    missing_required_samples: list[str] = []
    if args.samples:
        samples = [path.expanduser().resolve() for path in args.samples]
    else:
        samples, missing_required_samples = _discover_default_samples()
    if missing_required_samples:
        print("Missing required default HWP math samples:")
        for name in missing_required_samples:
            print(f"  - {name}")
        return 2
    if not samples:
        print("No HWP math samples found. Pass sample paths explicitly.")
        return 2
    if args.save_pages != 0 or (not args.skip_source_render and args.save_source_pages != 0):
        _clean_saved_render_artifacts()

    reports = [
        _run_one(
            path,
            index,
            save_pages=args.save_pages,
            save_source_pages=args.save_source_pages,
            template_key=args.template_key,
            render_source=not args.skip_source_render,
        )
        for index, path in enumerate(samples, start=1)
    ]
    report_path = storage.EXPORT_DIR / "hwp_math_sample_qa_report.json"
    report_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    review_path = storage.EXPORT_DIR / "hwp_math_sample_review.html"
    _write_review_html(reports, report_path, review_path)

    print(
        f"{'sample':<42} {'problems':>8} {'choices':<18} {'tbl':>7} {'eq':>5} "
        f"{'eqvis':>9} {'pages':>9} {'dens':>6} {'overflow':>8} status"
    )
    print("-" * 122)
    all_ok = True
    for report in reports:
        source_name = Path(report["source"]).name[:42]
        render = report["render"]
        source_render = report.get("source_render") or {}
        pages = (
            f"{source_render.get('page_count')}/{render.get('page_count')}"
            if source_render.get("page_count") is not None
            else str(render.get("page_count", "-"))
        )
        overflow = render.get("overflow_count", "-")
        failures = report["failures"]
        density_ratio = (report.get("density_summary") or {}).get("output_to_source_median_ratio")
        table_math = report.get("table_math") or {}
        table_summary = f"{table_math.get('tables_with_math', 0)}/{table_math.get('tables', 0)}"
        equation_visibility = report.get("equation_visibility") or {}
        eqvis = (
            f"{int(equation_visibility.get('changed_pixels') or 0) // 1000}k"
            if equation_visibility.get("changed_pixels") is not None
            else "-"
        )
        all_ok = all_ok and not failures
        print(
            f"{source_name:<42} {report['created']:>8} "
            f"{str(report['choice_dist']):<18} {table_summary:>7} {report['inspect']['equations']:>5} "
            f"{eqvis:>9} {str(pages):>9} {str(density_ratio or '-'):>6} {str(overflow):>8} "
            f"{'OK' if not failures else 'FAIL'}"
        )
        for failure in failures:
            print(f"  - {failure}")
    print(f"\nReport: {report_path}")
    print(f"Review: {review_path}")
    print("RESULT:", "ALL OK" if all_ok else "SEE ISSUES ABOVE")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
