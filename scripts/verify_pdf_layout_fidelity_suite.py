from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import fitz
    from PIL import Image, ImageDraw
except Exception as exc:
    print(f"SKIP: PDF/Pillow runtime unavailable ({exc})")
    raise SystemExit(2)

try:
    import rhwp
except Exception as exc:
    print(f"SKIP: rhwp unavailable ({exc})")
    raise SystemExit(2)

from app import pdf_layout_fidelity, pdf_layout_writer, storage  # noqa: E402
from scripts.verify_pdf_layout_hwpx import verify as verify_hwpx  # noqa: E402

TARGET_SYNC_RATIO = 0.90
QA_DIR = storage.EXPORT_DIR / "pdf_layout_fidelity_qa"

_failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}{(' - ' + detail) if detail else ''}")
    if not condition:
        _failures.append(name)


def _safe_recreate_dir(path: Path) -> None:
    storage.ensure_dirs()
    export_root = storage.EXPORT_DIR.resolve()
    target = path.resolve()
    try:
        target.relative_to(export_root)
    except ValueError as exc:
        raise RuntimeError(f"refusing to recreate outside exports: {target}") from exc
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)


def _diagram_png() -> bytes:
    image = Image.new("RGB", (180, 110), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((5, 5, 175, 105), outline="black", width=2)
    draw.line((20, 90, 60, 55, 100, 70, 150, 25), fill="black", width=3)
    draw.text((18, 12), "Diagram", fill="black")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _add_exam_page(page: fitz.Page, title: str) -> None:
    width = float(page.rect.width)
    page.insert_text((48, 38), title, fontsize=12, fontname="helv")
    page.insert_textbox(
        fitz.Rect(48, 86, width / 2 - 28, 250),
        "1. Read the passage and choose the best answer.\n"
        "The river was quiet, and the old bridge held the morning light.\n"
        "1) bright  2) quiet  3) narrow  4) broken  5) distant",
        fontsize=10,
        fontname="times-roman",
    )
    page.insert_textbox(
        fitz.Rect(width / 2 + 20, 86, width - 48, 250),
        "2. Which sentence best completes the paragraph?\n"
        "Students compared the two maps and wrote a short explanation.\n"
        "1) However  2) Therefore  3) Likewise  4) Instead  5) Otherwise",
        fontsize=10,
        fontname="times-roman",
    )
    page.draw_rect(fitz.Rect(48, 290, min(270, width - 60), 380), color=(0, 0, 0), width=0.8)
    page.insert_textbox(
        fitz.Rect(58, 302, min(260, width - 70), 368),
        "A boxed passage should stay inside an editable text box.",
        fontsize=9.5,
        fontname="times-roman",
    )


def make_portrait_exam_pdf(path: Path, pages: int = 4) -> None:
    doc = fitz.open()
    for page_no in range(1, pages + 1):
        page = doc.new_page(width=595, height=842)
        _add_exam_page(page, f"Portrait English Test page {page_no}")
    doc.save(path)
    doc.close()


def make_landscape_exam_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    _add_exam_page(page, "Landscape English Test")
    doc.save(path)
    doc.close()


def make_table_image_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((48, 38), "Table and diagram test", fontsize=12, fontname="helv")
    x0, y0, width, height = 48.0, 90.0, 360.0, 120.0
    for row in range(5):
        y = y0 + row * height / 4
        page.draw_line((x0, y), (x0 + width, y), color=(0, 0, 0), width=0.8)
    for col in range(4):
        x = x0 + col * width / 3
        page.draw_line((x, y0), (x, y0 + height), color=(0, 0, 0), width=0.8)
    for row in range(4):
        for col in range(3):
            page.insert_text(
                (x0 + col * width / 3 + 8, y0 + row * height / 4 + 18),
                f"{row + 1}-{col + 1}",
                fontsize=9,
                fontname="helv",
            )
    page.insert_image(fitz.Rect(430, 90, 560, 170), stream=_diagram_png())
    page.insert_textbox(
        fitz.Rect(48, 250, 270, 390),
        "1. The table summarizes observations.\n"
        "Which statement is correct?\n"
        "1) A  2) B  3) C  4) D  5) E",
        fontsize=10,
        fontname="times-roman",
    )
    page.draw_rect(fitz.Rect(310, 250, 540, 360), color=(0, 0, 0), width=0.8)
    page.insert_textbox(
        fitz.Rect(320, 262, 530, 348),
        "A boxed note with dense text should preserve the rectangle and editable text.",
        fontsize=9.5,
        fontname="times-roman",
    )
    doc.save(path)
    doc.close()


def make_mixed_page_pdf(path: Path) -> None:
    doc = fitz.open()
    first = doc.new_page(width=595, height=842)
    _add_exam_page(first, "Mixed page test portrait")
    second = doc.new_page(width=842, height=595)
    _add_exam_page(second, "Mixed page test landscape")
    doc.save(path)
    doc.close()


def render_all_hwpx_pages(path: Path, expected_pages: int) -> None:
    document = rhwp.parse(str(path))
    check(f"{path.name} page count", int(document.page_count) == expected_pages, f"pages={document.page_count}")
    for page_index in range(int(document.page_count)):
        png = bytes(document.render_png(page_index))
        check(f"{path.name} render page {page_index + 1}", len(png) > 1000, f"bytes={len(png)}")


def run_case(
    name: str,
    pdf_path: Path,
    *,
    expected_pages: int,
    min_visual_sync: float = 0.95,
    min_foreground_overlap: float = 0.85,
    min_images: int = 0,
    min_line_rects: int = 1,
) -> dict[str, Any]:
    output_path = QA_DIR / name / f"{name}.hwpx"
    render_dir = QA_DIR / name / "fidelity_renders"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stats = pdf_layout_writer.write_pdf_layout_hwpx(
        pdf_path,
        output_path,
        max_pages=None,
        include_images=True,
        include_lines=True,
        text_mode="line",
    )
    fidelity = pdf_layout_fidelity.analyze_pdf_hwpx_fidelity(
        pdf_path,
        output_path,
        render_dir,
        max_pages=int(stats.get("pages") or 0),
        target_sync_ratio=TARGET_SYNC_RATIO,
    )
    issues = verify_hwpx(output_path, render=False)

    check(f"{name} HWPX structure", not issues, "; ".join(issues[:5]))
    render_all_hwpx_pages(output_path, expected_pages)
    check(f"{name} page stats", stats.get("pages") == expected_pages, repr(stats))
    check(f"{name} source lines", int(stats.get("source_text_lines") or 0) > 0, repr(stats))
    check(f"{name} editable coverage", float(stats.get("editable_text_coverage_ratio") or 0.0) >= 0.9, repr(stats))
    check(f"{name} image count", int(stats.get("images") or 0) >= min_images, repr(stats))
    check(f"{name} line rect count", int(stats.get("line_rects") or 0) >= min_line_rects, repr(stats))
    check(f"{name} fidelity no error", not fidelity.get("error"), repr(fidelity))
    check(f"{name} all pages compared", int(fidelity.get("pages_compared") or 0) == expected_pages, repr(fidelity))
    check(f"{name} no truncation", fidelity.get("truncated") is False, repr(fidelity))
    check(f"{name} no aspect mismatch", fidelity.get("aspect_ratio_mismatch_pages") == [], repr(fidelity))
    check(f"{name} no review flags", fidelity.get("review_flags") == [], repr(fidelity))
    check(f"{name} visual sync", float(fidelity.get("overall_sync_ratio") or 0.0) >= min_visual_sync, repr(fidelity))
    check(
        f"{name} foreground overlap",
        float(fidelity.get("min_foreground_overlap_ratio") or 0.0) >= min_foreground_overlap,
        repr(fidelity),
    )
    check(f"{name} meets target", fidelity.get("meets_target") is True, repr(fidelity))
    return {
        "name": name,
        "pdf": str(pdf_path),
        "hwpx": str(output_path),
        "stats": stats,
        "fidelity": fidelity,
    }


def check_negative_guards(portrait_pdf: Path, portrait_hwpx: Path) -> dict[str, Any]:
    truncated = pdf_layout_fidelity.analyze_pdf_hwpx_fidelity(
        portrait_pdf,
        portrait_hwpx,
        QA_DIR / "portrait_four_page" / "truncated_renders",
        max_pages=3,
        target_sync_ratio=TARGET_SYNC_RATIO,
    )
    check("truncated fidelity flagged", truncated.get("truncated_by_max_pages") is True, repr(truncated))
    check("truncated fidelity does not meet target", truncated.get("meets_target") is False, repr(truncated))
    check("truncated review flag", "truncated_by_max_pages" in (truncated.get("review_flags") or []), repr(truncated))

    return {"truncated": truncated}


def main() -> int:
    _safe_recreate_dir(QA_DIR)
    portrait_pdf = QA_DIR / "portrait_four_page.pdf"
    landscape_pdf = QA_DIR / "landscape_exam.pdf"
    table_image_pdf = QA_DIR / "table_image_exam.pdf"
    mixed_pdf = QA_DIR / "mixed_page_guard.pdf"
    make_portrait_exam_pdf(portrait_pdf, pages=4)
    make_landscape_exam_pdf(landscape_pdf)
    make_table_image_pdf(table_image_pdf)
    make_mixed_page_pdf(mixed_pdf)

    results = [
        run_case(
            "portrait_four_page",
            portrait_pdf,
            expected_pages=4,
            min_visual_sync=0.95,
            min_foreground_overlap=0.90,
            min_line_rects=4,
        ),
        run_case(
            "landscape_exam",
            landscape_pdf,
            expected_pages=1,
            min_visual_sync=0.95,
            min_foreground_overlap=0.90,
            min_line_rects=1,
        ),
        run_case(
            "table_image_exam",
            table_image_pdf,
            expected_pages=1,
            min_visual_sync=0.95,
            min_foreground_overlap=0.85,
            min_images=1,
            min_line_rects=8,
        ),
        run_case(
            "mixed_page_exam",
            mixed_pdf,
            expected_pages=2,
            min_visual_sync=0.95,
            min_foreground_overlap=0.90,
            min_line_rects=2,
        ),
    ]
    negative = check_negative_guards(
        portrait_pdf,
        Path(results[0]["hwpx"]),
    )
    report = {
        "ok": not _failures,
        "failures": list(_failures),
        "target_sync_ratio": TARGET_SYNC_RATIO,
        "cases": results,
        "negative_guards": negative,
    }
    report_path = QA_DIR / "pdf_layout_fidelity_suite_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {report_path}")
    print(f"Output dir: {QA_DIR}")
    if _failures:
        print(f"PDF_LAYOUT_FIDELITY_SUITE_FAIL ({len(_failures)}): {', '.join(_failures)}")
        return 1
    print("PDF_LAYOUT_FIDELITY_SUITE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
