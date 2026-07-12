from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pdf_layout_fidelity import analyze_pdf_hwpx_fidelity  # noqa: E402
from app.pdf_layout_writer import write_pdf_layout_hwpx  # noqa: E402
from hwpx.tools.package_validator import validate_editor_open_safety  # noqa: E402
from scripts.verify_pdf_layout_hwpx import verify as verify_hwpx  # noqa: E402


def _make_source(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 20)
    c.drawString(42, height - 52, "Layout Stress Suite - Portrait")
    c.setStrokeColor(colors.HexColor("#777777"))
    c.setLineWidth(0.45)
    c.line(42, height - 62, width - 42, height - 62)
    c.setFont("Times-Roman", 10)
    text = c.beginText(48, height - 92)
    text.setLeading(14)
    for line in (
        "This page combines flowing prose, a thin gray frame, and a native-style table.",
        "The conversion must preserve editable text while retaining exact line geometry.",
        "Longer sentences exercise wrapping, spacing, and paragraph alignment behavior.",
    ):
        text.textLine(line)
    c.drawText(text)
    c.setStrokeColor(colors.HexColor("#9A9A9A"))
    c.rect(46, height - 270, width - 92, 105, stroke=1, fill=0)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(58, height - 188, "Thin-rule callout")
    c.setFont("Times-Roman", 9)
    c.drawString(58, height - 207, "Borders lighter than ordinary text must remain continuous.")
    table_x, table_y, table_w, row_h = 58, height - 252, width - 116, 18
    c.setStrokeColor(colors.black)
    for row in range(3):
        c.rect(table_x, table_y + row * row_h, table_w, row_h, stroke=1, fill=0)
    for ratio in (0.28, 0.67):
        c.line(table_x + table_w * ratio, table_y, table_x + table_w * ratio, table_y + row_h * 3)
    c.setFillColor(colors.HexColor("#2057A6"))
    c.rect(58, 120, 160, 28, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(68, 129, "COLOR MUST SURVIVE")
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 8)
    c.drawRightString(width - 42, 32, "portrait / boxes / table / color")
    c.showPage()

    c.setPageSize(landscape(A4))
    width, height = landscape(A4)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(36, height - 42, "Landscape Three-column and Rotation")
    gutter = 18
    margin = 36
    column_w = (width - margin * 2 - gutter * 2) / 3
    body = (
        "Three-column layouts test arbitrary reading geometry. Each column contains enough "
        "content to expose drift, clipping, and unexpected line wrapping in the output."
    )
    for col in range(3):
        x = margin + col * (column_w + gutter)
        c.setStrokeColor(colors.HexColor("#B0B0B0"))
        c.rect(x, 80, column_w, height - 145, stroke=1, fill=0)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(x + 8, height - 70, f"Column {col + 1}")
        text = c.beginText(x + 8, height - 90)
        text.setFont("Times-Roman", 9)
        text.setLeading(12)
        words = body.split()
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if c.stringWidth(candidate, "Times-Roman", 9) > column_w - 16:
                text.textLine(line)
                line = word
            else:
                line = candidate
        if line:
            text.textLine(line)
        c.drawText(text)
    c.saveState()
    c.translate(width - 18, height / 2)
    c.rotate(90)
    c.setFillColor(colors.HexColor("#B3261E"))
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(0, 0, "ROTATED RED LABEL")
    c.restoreState()
    c.showPage()

    c.setPageSize(A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width / 2, height - 55, "Sparse Geometry")
    c.setStrokeColor(colors.HexColor("#777777"))
    c.setLineWidth(0.45)
    c.line(width / 2, height - 90, width / 2, 95)
    c.setFont("Times-Roman", 10)
    c.drawString(50, height - 125, "Left sparse item with an extended center divider.")
    c.drawString(width / 2 + 18, height - 125, "Right sparse item and a thin score box.")
    c.rect(width / 2 + 18, height - 185, 210, 34, stroke=1, fill=0)
    c.setFillColor(colors.HexColor("#2E7D32"))
    c.circle(90, 125, 24, stroke=0, fill=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 8)
    c.drawCentredString(width / 2, 38, "sparse / long rules / footer")
    c.save()


def _color_mae(render_dir: Path, pages: int) -> float:
    values: list[float] = []
    for page in range(1, pages + 1):
        source = np.asarray(
            Image.open(render_dir / f"source_page_{page:03d}.png").convert("RGB"),
            dtype=np.int16,
        )
        output = np.asarray(
            Image.open(render_dir / f"output_page_{page:03d}.png").convert("RGB"),
            dtype=np.int16,
        )
        spread = source.max(axis=2) - source.min(axis=2)
        colored = spread >= 15
        if colored.any():
            values.append(float(np.abs(source[colored] - output[colored]).mean()))
    return sum(values) / len(values) if values else 0.0


def _white_on_color_ratio(render_dir: Path) -> float:
    source = np.asarray(
        Image.open(render_dir / "source_page_001.png").convert("RGB"),
        dtype=np.uint8,
    )
    output = np.asarray(
        Image.open(render_dir / "output_page_001.png").convert("RGB"),
        dtype=np.uint8,
    )
    height, width, _ = source.shape
    page_width, page_height = A4
    x0 = int(round(58.0 / page_width * width))
    x1 = int(round(218.0 / page_width * width))
    y0 = int(round((page_height - 148.0) / page_height * height))
    y1 = int(round((page_height - 120.0) / page_height * height))
    source_white = int((source[y0:y1, x0:x1].min(axis=2) > 220).sum())
    output_white = int((output[y0:y1, x0:x1].min(axis=2) > 220).sum())
    return output_white / max(1, source_white)


def main() -> int:
    work = ROOT / "tmp" / "pdfs" / "layout_stress_suite"
    source = work / "layout_stress_suite.pdf"
    output = work / "layout_stress_suite.hwpx"
    render_dir = work / "render"
    _make_source(source)
    stats = write_pdf_layout_hwpx(
        source,
        output,
        include_images=True,
        include_lines=True,
        text_mode="line",
        native_math=False,
        text_visual_overlays=True,
        text_visual_overlay_mode="foreground",
        foreground_stroke_soften_strength=0.30,
        math_ai_recognition=False,
    )
    fidelity = analyze_pdf_hwpx_fidelity(
        source,
        output,
        render_dir,
        max_pages=3,
        target_sync_ratio=0.80,
        artifact_mode="all",
    )
    color_mae = _color_mae(render_dir, 3)
    white_on_color_ratio = _white_on_color_ratio(render_dir)
    structure_issues = verify_hwpx(output, render=False)
    open_safety = validate_editor_open_safety(output)
    failures: list[str] = []
    if int(stats.get("pages") or 0) != 3:
        failures.append("page count mismatch")
    if float(stats.get("editable_text_coverage_ratio") or 0.0) < 0.98:
        failures.append("editable text coverage below 98%")
    if int(stats.get("full_page_images") or 0) > 0:
        failures.append("full-page image used")
    if float(fidelity.get("overall_harsh_layout_score") or 0.0) < 95.0:
        failures.append("harsh layout average below 95")
    if float(fidelity.get("minimum_harsh_layout_score") or 0.0) < 95.0:
        failures.append("harsh layout minimum below 95")
    if color_mae > 18.0:
        failures.append("color MAE above 18")
    if white_on_color_ratio < 0.80:
        failures.append("white-on-color text coverage below 80%")
    if structure_issues:
        failures.append(f"structure issues: {structure_issues[:3]}")
    if not open_safety.ok:
        failures.append("editor-open safety failed")
    report = {
        "source": str(source.relative_to(ROOT)),
        "output": str(output.relative_to(ROOT)),
        "stats": stats,
        "fidelity": {
            key: fidelity.get(key)
            for key in (
                "pages_compared",
                "overall_harsh_layout_score",
                "minimum_harsh_layout_score",
                "min_strict_alignment_ratio",
                "min_foreground_overlap_ratio",
                "review_flags",
            )
        },
        "color_mae": round(color_mae, 3),
        "white_on_color_ratio": round(white_on_color_ratio, 3),
        "structure_issues": structure_issues,
        "editor_open_safe": bool(open_safety.ok),
        "failures": failures,
    }
    report_path = ROOT / "data" / "external_exam_qa" / "layout_stress_suite_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Report: {report_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
