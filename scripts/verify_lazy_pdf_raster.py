"""Regression gate for demand-driven PDF page rasterization.

The recognition pipeline must preserve regional figures and mixed-document page
fallbacks while avoiding raster work for text-only pages.  This synthetic test
does not depend on private exam samples and is discovered by run_all_verify.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import fitz
except Exception:
    print("SKIP: PyMuPDF(fitz) is unavailable")
    raise SystemExit(2)

from app.recognition import cutout  # noqa: E402
from app.recognition.pipeline import recognize_pdf  # noqa: E402


def _make_pdf() -> bytes:
    doc = fitz.open()

    text_page = doc.new_page(width=595, height=842)
    text_page.insert_text((72, 100), "1. Text-only problem.", fontsize=12)
    text_page.insert_text((90, 130), "No raster content is needed here.", fontsize=11)

    figure_page = doc.new_page(width=595, height=842)
    figure_page.insert_text((72, 100), "2. Problem with a diagram.", fontsize=12)
    figure_page.draw_rect(fitz.Rect(260, 180, 430, 350), width=1.5)
    figure_page.draw_line(fitz.Point(270, 330), fitz.Point(410, 200), width=1.5)

    fallback_page = doc.new_page(width=595, height=842)
    fallback_page.insert_text((72, 100), "Unnumbered mixed-document page.", fontsize=12)

    data = doc.tobytes()
    doc.close()
    return data


def main() -> int:
    requested: list[set[int]] = []
    original = cutout.render_selected_page_images

    def recording_renderer(pdf_bytes: bytes, page_indexes: object, *, dpi: int = 150):
        indexes = {int(index) for index in page_indexes}  # type: ignore[arg-type]
        requested.append(indexes)
        return original(pdf_bytes, indexes, dpi=dpi)

    cutout.render_selected_page_images = recording_renderer
    try:
        result = recognize_pdf(_make_pdf(), filename="lazy_raster_test.pdf")
    finally:
        cutout.render_selected_page_images = original

    selected = requested[0] if requested else set()
    text_items = [item for item in result.problems if item.page_number == 1]
    figure_items = [item for item in result.problems if item.page_number == 2]
    fallback_items = [item for item in result.problems if item.page_number == 3]

    failures: list[str] = []
    if selected != {1, 2}:
        failures.append(f"expected raster pages {{1, 2}}, got {selected}")
    if not text_items or any(item.figure_pngs or item.problem_image_png for item in text_items):
        failures.append("text-only page unexpectedly produced raster artifacts")
    if not figure_items or not any(item.figure_pngs for item in figure_items):
        failures.append("regional figure crop was not preserved")
    if not fallback_items or not any(item.problem_image_png for item in fallback_items):
        failures.append("mixed-document page fallback was not preserved")

    if failures:
        for failure in failures:
            print(f"  [FAIL] {failure}")
        print("LAZY_PDF_RASTER_FAIL")
        return 1

    print(f"  [PASS] rendered only pages {sorted(selected)} of 3")
    print("  [PASS] regional figure and mixed-page fallback preserved")
    print("LAZY_PDF_RASTER_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
