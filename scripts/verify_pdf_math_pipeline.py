# -*- coding: utf-8 -*-
"""Verify PDF text-layer math survives as native HWPX equations.

This is a deterministic guard for the PDF side of the math-exam workflow. It
creates a small born-digital PDF with LaTeX-like math text, imports it through
the app's PDF importer, exports native-math HWPX, then checks equation scripts,
equation object integrity, and rendered equation visibility.
"""
from __future__ import annotations

import json
import os
import sys
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from xml.etree import ElementTree as ET

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HWP_MAKE_DATA_DIR", str(ROOT / "data" / "pdf_math_qa"))

from app import hwpx_writer, hwpx_writer_v2, importers, math_text, storage  # noqa: E402
from app.recognition.pdf_segment import segment_pdf  # noqa: E402
from app.recognition.schema import Subject  # noqa: E402
from scripts.qa_hwp_math_samples import _render_hwpx  # noqa: E402
from scripts.verify_hwpx_native_math import (  # noqa: E402
    _equation_object_issues,
    _native_math_visibility,
)

HP_NS = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
OUT_DIR = ROOT / "data" / "pdf_math_qa" / "exports"
RENDER_DIR = OUT_DIR / "renders"
PDF_PATH = OUT_DIR / "synthetic_pdf_math.pdf"
HWPX_PATH = OUT_DIR / "synthetic_pdf_math_native.hwpx"
PDF_2COL_PATH = OUT_DIR / "synthetic_pdf_math_2col.pdf"
HWPX_2COL_PATH = OUT_DIR / "synthetic_pdf_math_2col_native.hwpx"
PDF_VISUAL_PATH = OUT_DIR / "synthetic_pdf_math_visual.pdf"
HWPX_VISUAL_PATH = OUT_DIR / "synthetic_pdf_math_visual_native.hwpx"
REPORT_PATH = OUT_DIR / "pdf_math_pipeline_report.json"

PDF_LINES = (
    r"1. Evaluate x^2 + \frac{1}{2} and \sqrt{x}.",
    r"1) x^2",
    r"2) \frac{1}{2}",
    r"3) \sqrt{x}",
    r"4) x+1",
    r"5) x-1",
    "",
    r"2. Let A=\begin{matrix}a & b \\ c & d\end{matrix}. Find \lim_{x\to0}\frac{\sin x}{x}.",
    r"Also compute \int_{0}^{1} x^2\,dx and \left\{x\mid x>0\right\}.",
    r"1) 0",
    r"2) 1",
    r"3) 2",
    r"4) \infty",
    r"5) none",
)

EXPECTED_SCRIPTS = (
    hwpx_writer._hancom_eqn_script("x^2 + \\frac{1}{2}"),
    hwpx_writer._hancom_eqn_script("\\sqrt{x}"),
    hwpx_writer._hancom_eqn_script("\\begin{matrix}a & b \\\\ c & d\\end{matrix}"),
    hwpx_writer._hancom_eqn_script("\\lim_{x\\to0}\\frac{\\sin x}{x}"),
    hwpx_writer._hancom_eqn_script("\\int_{0}^{1} x^2\\,dx"),
    hwpx_writer._hancom_eqn_script("\\left\\{x\\mid x>0\\right\\}"),
    hwpx_writer._hancom_eqn_script("\\infty"),
)
EXPECTED_CHOICE_COUNTS = (5, 5)
TWO_COLUMN_PROBLEMS = (
    (
        72,
        72,
        (
            r"1. Compute \sum_{k=1}^{3} k.",
            r"1) 3",
            r"2) 4",
            r"3) 5",
            r"4) 6",
            r"5) 7",
        ),
    ),
    (
        72,
        300,
        (
            r"2. Solve \log_{2}{x} = 3.",
            r"1) 4",
            r"2) 6",
            r"3) 8",
            r"4) 10",
            r"5) 12",
        ),
    ),
    (
        330,
        72,
        (
            r"3. Find \int_{0}^{1} x^2 dx.",
            r"1) \frac{1}{2}",
            r"2) \frac{1}{3}",
            r"3) \frac{2}{3}",
            r"4) 1",
            r"5) 2",
        ),
    ),
    (
        330,
        300,
        (
            r"4. If f(x)=x^2, find f'(2).",
            r"1) 2",
            r"2) 3",
            r"3) 4",
            r"4) 5",
            r"5) 6",
        ),
    ),
)
EXPECTED_2COL_SCRIPTS = (
    hwpx_writer._hancom_eqn_script("\\sum_{k=1}^{3} k"),
    hwpx_writer._hancom_eqn_script("\\log_{2}{x} = 3"),
    hwpx_writer._hancom_eqn_script("\\int_{0}^{1} x^2 dx"),
    hwpx_writer._hancom_eqn_script("\\frac{1}{3}"),
    hwpx_writer._hancom_eqn_script("f(x)=x^2"),
    hwpx_writer._hancom_eqn_script("f'(2)"),
)
VISUAL_PDF_LINES = (
    (
        72,
        72,
        (
            r"1. The graph below shows y=x^2. Find the shaded area.",
            r"1) \frac{1}{4}",
            r"2) \frac{1}{3}",
            r"3) \frac{1}{2}",
            r"4) 1",
            r"5) 2",
        ),
    ),
    (
        72,
        390,
        (
            r"2. The table below gives f(x). Find \sum_{x=1}^{4} f(x).",
            r"1) f(1)+f(2)+f(3)+f(4)=10",
            r"2) f(1)+f(2)+f(3)+f(4)=12",
            r"3) f(1)+f(2)+f(3)+f(4)=14",
            r"4) f(1)+f(2)+f(3)+f(4)=16",
            r"5) f(1)+f(2)+f(3)+f(4)=18",
        ),
    ),
)
EXPECTED_VISUAL_SCRIPTS = (
    hwpx_writer._hancom_eqn_script("y=x^2"),
    hwpx_writer._hancom_eqn_script("\\frac{1}{3}"),
    hwpx_writer._hancom_eqn_script("\\sum_{x=1}^{4} f(x)"),
    hwpx_writer._hancom_eqn_script("f(1)+f(2)+f(3)+f(4)=10"),
)


def _create_pdf(path: Path) -> None:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(f"PyMuPDF(fitz) is required to create the synthetic PDF: {exc}") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    y = 72
    for line in PDF_LINES:
        if line:
            page.insert_text((72, y), line, fontsize=11, fontname="helv")
        y += 24
    doc.save(path)
    doc.close()


def _create_two_column_pdf(path: Path) -> None:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(f"PyMuPDF(fitz) is required to create the synthetic PDF: {exc}") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for x, y, lines in TWO_COLUMN_PROBLEMS:
        cursor = y
        for line in lines:
            page.insert_text((x, cursor), line, fontsize=10.5, fontname="helv")
            cursor += 21
    doc.save(path)
    doc.close()


def _create_visual_pdf(path: Path) -> None:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(f"PyMuPDF(fitz) is required to create the synthetic PDF: {exc}") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)

    # Problem 1: graph-like drawing between the stem and choices.
    y = 72
    page.insert_text((72, y), VISUAL_PDF_LINES[0][2][0], fontsize=10.5, fontname="helv")
    graph = fitz.Rect(102, 108, 280, 250)
    page.draw_rect(graph, color=(0, 0, 0), width=0.8)
    page.draw_line((118, 232), (264, 232), color=(0, 0, 0), width=0.8)
    page.draw_line((132, 240), (132, 120), color=(0, 0, 0), width=0.8)
    points = [(132, 232), (154, 220), (176, 196), (198, 160), (220, 124)]
    for start, end in zip(points, points[1:]):
        page.draw_line(start, end, color=(0, 0, 0), width=1.2)
    page.draw_rect(fitz.Rect(176, 196, 220, 232), color=(0, 0, 0), fill=(0.85, 0.85, 0.85), width=0.5)
    page.insert_text((232, 134), r"y=x^2", fontsize=9.5, fontname="helv")
    y = 272
    for line in VISUAL_PDF_LINES[0][2][1:]:
        page.insert_text((90, y), line, fontsize=10.5, fontname="helv")
        y += 20

    # Problem 2: ruled table-like drawing and long math choices.
    y = 390
    page.insert_text((72, y), VISUAL_PDF_LINES[1][2][0], fontsize=10.5, fontname="helv")
    table_left, table_top = 104, 426
    cell_w, cell_h = 54, 26
    for row in range(3):
        page.draw_line(
            (table_left, table_top + row * cell_h),
            (table_left + 5 * cell_w, table_top + row * cell_h),
            color=(0, 0, 0),
            width=0.7,
        )
    for col in range(6):
        page.draw_line(
            (table_left + col * cell_w, table_top),
            (table_left + col * cell_w, table_top + 2 * cell_h),
            color=(0, 0, 0),
            width=0.7,
        )
    table_values = (
        ("x", "1", "2", "3", "4"),
        ("f(x)", "1", "2", "3", "4"),
    )
    for row, values in enumerate(table_values):
        for col, value in enumerate(values):
            page.insert_text(
                (table_left + col * cell_w + 18, table_top + row * cell_h + 17),
                value,
                fontsize=9.5,
                fontname="helv",
            )
    y = 500
    for line in VISUAL_PDF_LINES[1][2][1:]:
        page.insert_text((90, y), line, fontsize=10.2, fontname="helv")
        y += 20

    doc.save(path)
    doc.close()


def _equation_scripts(path: Path) -> list[str]:
    scripts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if not name.startswith("Contents/section") or not name.endswith(".xml"):
                continue
            root = ET.fromstring(archive.read(name))
            for equation in root.iter(f"{HP_NS}equation"):
                scripts.append(
                    "".join(node.text or "" for node in equation.iter(f"{HP_NS}script")).strip()
                )
    return scripts


def _picture_count(path: Path) -> int:
    count = 0
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if not name.startswith("Contents/section") or not name.endswith(".xml"):
                continue
            root = ET.fromstring(archive.read(name))
            count += sum(1 for _ in root.iter(f"{HP_NS}pic"))
    return count


def _visible_math_count(items: list[dict[str, object]]) -> int:
    return sum(len(math_text.analyze_problem_math(item)) for item in items)


def _text_payload(items: list[dict[str, object]]) -> str:
    return "\n".join(
        "\n".join(
            [
                str(item.get("stem") or ""),
                *[str(choice or "") for choice in item.get("choices") or []],
            ]
        )
        for item in items
    )


def _import_pdf_with_warnings(path: Path) -> tuple[dict[str, object], list[str]]:
    stdout_buffer = StringIO()
    stderr_buffer = StringIO()
    with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
        result = importers.import_pdf(path.name, path.read_bytes(), {})
    warnings = [
        f"{path.name}: {line}"
        for line in [*stdout_buffer.getvalue().splitlines(), *stderr_buffer.getvalue().splitlines()]
        if line.strip()
    ]
    return result, warnings


def _layout_failures(render: dict[str, object], label: str) -> list[str]:
    failures: list[str] = []
    if render.get("error"):
        failures.append(f"{label} rhwp render failed: {render['error']}")
    if int(render.get("overflow_count") or 0):
        failures.append(f"{label} rhwp layout overflow count: {render.get('overflow_count')}")
    if render.get("column_crossing_issues"):
        failures.append(f"{label} rendered content crosses the two-column separator: {render['column_crossing_issues'][:8]}")

    content_bound_issues: list[dict[str, object]] = []
    for bound in render.get("content_bounds") or []:
        if not isinstance(bound, dict):
            continue
        bbox_ratio = bound.get("bbox_ratio")
        if not bbox_ratio:
            continue
        left, top, right, bottom = [float(value) for value in bbox_ratio]
        width_ratio = float(bound.get("width_ratio") or 0)
        height_ratio = float(bound.get("height_ratio") or 0)
        if left < 0.03 or top < 0.045 or right > 0.97 or bottom > 0.945:
            content_bound_issues.append({"reason": "outside safe page bounds", **bound})
        elif width_ratio > 0.88 or height_ratio > 0.9:
            content_bound_issues.append({"reason": "content bbox is unusually large", **bound})
    if content_bound_issues:
        failures.append(f"{label} rendered content bounding boxes look unsafe: {content_bound_issues[:8]}")

    render_bytes = [int(size) for size in render.get("render_bytes") or [] if isinstance(size, (int, float))]
    if render_bytes and any(size < 5000 for size in render_bytes):
        failures.append(f"{label} one or more rendered pages are suspiciously small: {render_bytes}")

    densities = [
        float(value)
        for value in render.get("ink_densities") or []
        if isinstance(value, (int, float))
    ]
    blank_like_pages = [
        {"page": page, "density": density}
        for page, density in enumerate(densities, start=1)
        if density < 0.003
    ]
    overfull_like_pages = [
        {"page": page, "density": density}
        for page, density in enumerate(densities, start=1)
        if density > 0.14
    ]
    if blank_like_pages:
        failures.append(f"{label} one or more rendered pages look blank: {blank_like_pages[:8]}")
    if overfull_like_pages:
        failures.append(f"{label} one or more rendered pages look over-dense: {overfull_like_pages[:8]}")
    return failures


def run() -> int:
    storage.ensure_dirs()
    storage.DB_PATH = storage.DATA_DIR / "pdf_math_pipeline.sqlite3"
    storage.DB_PATH.unlink(missing_ok=True)
    storage.init_db()

    failures: list[str] = []
    _create_pdf(PDF_PATH)
    segmented_pages = segment_pdf(PDF_PATH.read_bytes(), subject=Subject.MATH)
    geometry_blocks = [
        block
        for page in segmented_pages
        for block in page.blocks
        if block.metadata.get("pdf_line_chars")
    ]
    if not geometry_blocks:
        failures.append("PDF segmenter did not preserve raw line character geometry metadata")
    else:
        first_chars = geometry_blocks[0].metadata.get("pdf_line_chars") or []
        first_char_box = first_chars[0].get("bbox") if first_chars else None
        if not (
            isinstance(first_char_box, list)
            and len(first_char_box) == 4
            and all(isinstance(value, (int, float)) for value in first_char_box)
        ):
            failures.append(
                f"PDF segmenter raw character geometry has an invalid bbox: {first_char_box!r}"
            )
    result, importer_warnings = _import_pdf_with_warnings(PDF_PATH)
    items = list(result.get("created") or [])
    imported_pdf_lines = [
        line
        for item in items
        for line in ((item.get("layout") or {}).get("pdf_lines") or [])
        if isinstance(line, dict)
    ]
    if not imported_pdf_lines:
        failures.append("PDF import did not carry raw line geometry into problem layout metadata")
    else:
        first_line = imported_pdf_lines[0]
        if not (
            isinstance(first_line.get("bbox_px"), list)
            and len(first_line.get("bbox_px") or []) == 4
            and first_line.get("pdf_line_chars")
        ):
            failures.append(f"imported PDF line geometry is incomplete: {first_line!r}")
    numbers = [str(item.get("number") or "") for item in items]
    choice_counts = [len(item.get("choices") or []) for item in items]
    text_payload = _text_payload(items)
    math_count = _visible_math_count(items)

    if len(items) != 2:
        failures.append(f"expected 2 imported PDF problems, got {len(items)}")
    if numbers != ["1", "2"]:
        failures.append(f"expected PDF problem numbers ['1', '2'], got {numbers}")
    if choice_counts != list(EXPECTED_CHOICE_COUNTS):
        failures.append(
            f"expected PDF choice counts {list(EXPECTED_CHOICE_COUNTS)}, got {choice_counts}"
        )
    for source in (
        r"\frac{1}{2}",
        r"\sqrt{x}",
        r"\begin{matrix}",
        r"\lim_{x\to0}",
        r"\int_{0}^{1}",
        r"\left\{x\mid",
        r"\infty",
    ):
        if source not in text_payload:
            failures.append(f"PDF import lost math text token {source!r}")
    if math_count < 7:
        failures.append(f"PDF imported math analyzer count too small: {math_count}")

    hwpx_writer_v2.write_hwpx(
        HWPX_PATH,
        "Synthetic PDF Math QA",
        items,
        template_key="kice_math",
        native_math=True,
    )
    scripts = _equation_scripts(HWPX_PATH)
    for expected in EXPECTED_SCRIPTS:
        if expected and expected not in scripts:
            failures.append(f"native HWPX script from PDF missing: {expected!r}")
    object_issues = _equation_object_issues(HWPX_PATH)
    if object_issues:
        failures.append(f"native equation object integrity issues: {object_issues[:8]}")
    render = _render_hwpx(HWPX_PATH, RENDER_DIR, save_pages=1)
    failures.extend(_layout_failures(render, "single-column PDF HWPX"))
    visibility = _native_math_visibility(HWPX_PATH)
    if visibility.get("error"):
        failures.append(f"native equation render visibility failed: {visibility['error']}")
    elif visibility.get("available"):
        changed_pixels = int(visibility.get("changed_pixels") or 0)
        changed_ratio = float(visibility.get("changed_ratio") or 0)
        min_changed_pixels = max(300, len(scripts) * 80)
        if changed_pixels < min_changed_pixels or changed_ratio < 0.0005:
            failures.append(
                "native equations from PDF do not visibly affect render: "
                f"changed_pixels={changed_pixels}, changed_ratio={changed_ratio}, "
                f"min_changed_pixels={min_changed_pixels}"
            )

    _create_two_column_pdf(PDF_2COL_PATH)
    two_col_result, two_col_warnings = _import_pdf_with_warnings(PDF_2COL_PATH)
    importer_warnings.extend(two_col_warnings)
    two_col_items = list(two_col_result.get("created") or [])
    two_col_numbers = [str(item.get("number") or "") for item in two_col_items]
    two_col_choice_counts = [len(item.get("choices") or []) for item in two_col_items]
    two_col_math_count = _visible_math_count(two_col_items)
    two_col_payload = _text_payload(two_col_items)
    two_col_failures: list[str] = []

    if len(two_col_items) != 4:
        two_col_failures.append(f"expected 4 imported two-column PDF problems, got {len(two_col_items)}")
    if two_col_numbers != ["1", "2", "3", "4"]:
        two_col_failures.append(f"expected two-column PDF problem numbers ['1', '2', '3', '4'], got {two_col_numbers}")
    if two_col_choice_counts != [5, 5, 5, 5]:
        two_col_failures.append(f"expected two-column PDF choice counts [5, 5, 5, 5], got {two_col_choice_counts}")
    for source in (
        r"\sum_{k=1}^{3}",
        r"\log_{2}",
        r"\int_{0}^{1}",
        r"\frac{1}{3}",
        "f'(2)",
    ):
        if source not in two_col_payload:
            two_col_failures.append(f"two-column PDF import lost math text token {source!r}")
    if two_col_math_count < 8:
        two_col_failures.append(
            f"two-column PDF imported math analyzer count too small: {two_col_math_count}"
        )

    hwpx_writer_v2.write_hwpx(
        HWPX_2COL_PATH,
        "Synthetic Two-Column PDF Math QA",
        two_col_items,
        template_key="kice_math",
        native_math=True,
    )
    two_col_scripts = _equation_scripts(HWPX_2COL_PATH)
    for expected in EXPECTED_2COL_SCRIPTS:
        if expected and expected not in two_col_scripts:
            two_col_failures.append(f"native HWPX script from two-column PDF missing: {expected!r}")
    two_col_object_issues = _equation_object_issues(HWPX_2COL_PATH)
    if two_col_object_issues:
        two_col_failures.append(
            f"two-column native equation object integrity issues: {two_col_object_issues[:8]}"
        )
    two_col_render = _render_hwpx(HWPX_2COL_PATH, RENDER_DIR, save_pages=1)
    two_col_failures.extend(_layout_failures(two_col_render, "two-column PDF HWPX"))
    two_col_visibility = _native_math_visibility(HWPX_2COL_PATH)
    if two_col_visibility.get("error"):
        two_col_failures.append(
            f"two-column native equation render visibility failed: {two_col_visibility['error']}"
        )
    elif two_col_visibility.get("available"):
        two_col_changed_pixels = int(two_col_visibility.get("changed_pixels") or 0)
        two_col_changed_ratio = float(two_col_visibility.get("changed_ratio") or 0)
        two_col_min_changed_pixels = max(300, len(two_col_scripts) * 80)
        if two_col_changed_pixels < two_col_min_changed_pixels or two_col_changed_ratio < 0.0005:
            two_col_failures.append(
                "two-column native equations from PDF do not visibly affect render: "
                f"changed_pixels={two_col_changed_pixels}, "
                f"changed_ratio={two_col_changed_ratio}, "
                f"min_changed_pixels={two_col_min_changed_pixels}"
            )
    failures.extend(two_col_failures)

    _create_visual_pdf(PDF_VISUAL_PATH)
    visual_result, visual_warnings = _import_pdf_with_warnings(PDF_VISUAL_PATH)
    importer_warnings.extend(visual_warnings)
    visual_items = list(visual_result.get("created") or [])
    visual_numbers = [str(item.get("number") or "") for item in visual_items]
    visual_choice_counts = [len(item.get("choices") or []) for item in visual_items]
    visual_image_counts = [len(item.get("image_paths") or []) for item in visual_items]
    visual_math_count = _visible_math_count(visual_items)
    visual_payload = _text_payload(visual_items)
    visual_failures: list[str] = []

    if len(visual_items) != 2:
        visual_failures.append(f"expected 2 imported visual PDF problems, got {len(visual_items)}")
    if visual_numbers != ["1", "2"]:
        visual_failures.append(f"expected visual PDF problem numbers ['1', '2'], got {visual_numbers}")
    if visual_choice_counts != [5, 5]:
        visual_failures.append(f"expected visual PDF choice counts [5, 5], got {visual_choice_counts}")
    if sum(visual_image_counts) < 2 or any(count < 1 for count in visual_image_counts):
        visual_failures.append(f"expected visual PDF figure/table cutouts on both problems, got {visual_image_counts}")
    missing_images: list[str] = []
    for item in visual_items:
        for image_path in item.get("image_paths") or []:
            candidate = storage.DATA_DIR / str(image_path)
            if not candidate.exists():
                missing_images.append(str(image_path))
    if missing_images:
        visual_failures.append(f"visual PDF image cutouts missing on disk: {missing_images[:8]}")
    for source in (
        r"y=x^2",
        r"\frac{1}{3}",
        r"\sum_{x=1}^{4}",
        "f(1)+f(2)+f(3)+f(4)=10",
    ):
        if source not in visual_payload:
            visual_failures.append(f"visual PDF import lost text/math token {source!r}")
    if visual_math_count < 9:
        visual_failures.append(f"visual PDF imported math analyzer count too small: {visual_math_count}")

    hwpx_writer_v2.write_hwpx(
        HWPX_VISUAL_PATH,
        "Synthetic Visual PDF Math QA",
        visual_items,
        template_key="kice_math",
        native_math=True,
    )
    visual_scripts = _equation_scripts(HWPX_VISUAL_PATH)
    for expected in EXPECTED_VISUAL_SCRIPTS:
        if expected and expected not in visual_scripts:
            visual_failures.append(f"native HWPX script from visual PDF missing: {expected!r}")
    visual_object_issues = _equation_object_issues(HWPX_VISUAL_PATH)
    if visual_object_issues:
        visual_failures.append(
            f"visual native equation object integrity issues: {visual_object_issues[:8]}"
        )
    visual_picture_count = _picture_count(HWPX_VISUAL_PATH)
    if visual_picture_count < 2:
        visual_failures.append(f"expected at least 2 HWPX pictures from visual PDF, got {visual_picture_count}")
    visual_render = _render_hwpx(HWPX_VISUAL_PATH, RENDER_DIR, save_pages=1)
    visual_failures.extend(_layout_failures(visual_render, "visual PDF HWPX"))
    visual_visibility = _native_math_visibility(HWPX_VISUAL_PATH)
    if visual_visibility.get("error"):
        visual_failures.append(
            f"visual native equation render visibility failed: {visual_visibility['error']}"
        )
    elif visual_visibility.get("available"):
        visual_changed_pixels = int(visual_visibility.get("changed_pixels") or 0)
        visual_changed_ratio = float(visual_visibility.get("changed_ratio") or 0)
        visual_min_changed_pixels = max(300, len(visual_scripts) * 80)
        if visual_changed_pixels < visual_min_changed_pixels or visual_changed_ratio < 0.0005:
            visual_failures.append(
                "visual native equations from PDF do not visibly affect render: "
                f"changed_pixels={visual_changed_pixels}, "
                f"changed_ratio={visual_changed_ratio}, "
                f"min_changed_pixels={visual_min_changed_pixels}"
            )
    failures.extend(visual_failures)

    report = {
        "ok": not failures,
        "pdf_path": str(PDF_PATH),
        "hwpx_path": str(HWPX_PATH),
        "created": len(items),
        "numbers": numbers,
        "choice_counts": choice_counts,
        "math_count": math_count,
        "equation_count": len(scripts),
        "expected_scripts": list(EXPECTED_SCRIPTS),
        "equation_scripts": scripts,
        "equation_object_issue_count": len(object_issues),
        "equation_object_issues": object_issues[:20],
        "render": render,
        "equation_visibility": visibility,
        "two_column": {
            "ok": not two_col_failures,
            "pdf_path": str(PDF_2COL_PATH),
            "hwpx_path": str(HWPX_2COL_PATH),
            "created": len(two_col_items),
            "numbers": two_col_numbers,
            "choice_counts": two_col_choice_counts,
            "math_count": two_col_math_count,
            "equation_count": len(two_col_scripts),
            "expected_scripts": list(EXPECTED_2COL_SCRIPTS),
            "equation_scripts": two_col_scripts,
            "equation_object_issue_count": len(two_col_object_issues),
            "equation_object_issues": two_col_object_issues[:20],
            "render": two_col_render,
            "equation_visibility": two_col_visibility,
            "notices": two_col_result.get("notices") or [],
            "failures": two_col_failures,
        },
        "visual": {
            "ok": not visual_failures,
            "pdf_path": str(PDF_VISUAL_PATH),
            "hwpx_path": str(HWPX_VISUAL_PATH),
            "created": len(visual_items),
            "numbers": visual_numbers,
            "choice_counts": visual_choice_counts,
            "image_counts": visual_image_counts,
            "math_count": visual_math_count,
            "equation_count": len(visual_scripts),
            "picture_count": visual_picture_count,
            "expected_scripts": list(EXPECTED_VISUAL_SCRIPTS),
            "equation_scripts": visual_scripts,
            "equation_object_issue_count": len(visual_object_issues),
            "equation_object_issues": visual_object_issues[:20],
            "render": visual_render,
            "equation_visibility": visual_visibility,
            "notices": visual_result.get("notices") or [],
            "failures": visual_failures,
        },
        "notices": result.get("notices") or [],
        "importer_warnings": importer_warnings,
        "failures": failures,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"PDF: {PDF_PATH}")
    print(f"HWPX: {HWPX_PATH}")
    print(f"Two-column PDF: {PDF_2COL_PATH}")
    print(f"Two-column HWPX: {HWPX_2COL_PATH}")
    print(f"Visual PDF: {PDF_VISUAL_PATH}")
    print(f"Visual HWPX: {HWPX_VISUAL_PATH}")
    print(f"Report: {REPORT_PATH}")
    print(f"Imported problems: {len(items)}; equations: {len(scripts)}; math spans: {math_count}")
    print(
        "Two-column imported problems: "
        f"{len(two_col_items)}; equations: {len(two_col_scripts)}; "
        f"math spans: {two_col_math_count}"
    )
    print(
        "Visual imported problems: "
        f"{len(visual_items)}; pictures: {visual_picture_count}; "
        f"equations: {len(visual_scripts)}; math spans: {visual_math_count}"
    )
    if importer_warnings:
        print(f"Importer warnings: {len(importer_warnings)}")
    if visibility.get("available"):
        print(
            "Render visibility: "
            f"changed_pixels={visibility.get('changed_pixels')}, "
            f"changed_ratio={visibility.get('changed_ratio')}"
        )
    if failures:
        print("FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("PDF math pipeline QA OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
