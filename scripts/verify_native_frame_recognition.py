"""Decorative frames must not become overlapping table cells or rasterized prose."""
from __future__ import annotations

import io
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="hwpmake_frame_recognition_")
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name

import fitz
from PIL import Image, ImageDraw
from app import hwpx_writer_v2
from app.pdf_native_content import _overlapping_source_cells, extract_native_content
from app.pdf_editability import inspect_pdf_editability


def rows(*bounds):
    return [SimpleNamespace(cells=row) for row in bounds]


def run():
    assert not _overlapping_source_cells(rows([(0, 0, 20, 10), None], [(0, 10, 10, 20), (10, 10, 20, 20)]))
    assert _overlapping_source_cells(rows([(0, 0, 20, 20), (10, 0, 20, 10)], [(0, 10, 10, 20), None]))
    assert not _overlapping_source_cells(rows([(0, 0, 10, 10), (9.99, 0, 20, 10)]))
    print("PASS real grid/merged cell partitions, nested false cells and subpixel tolerance")

    folder = Path(RUNTIME.name)
    source, output = folder / "frame.pdf", folder / "frame.hwpx"
    frame = Image.new("RGB", (440, 220), "white")
    ImageDraw.Draw(frame).rounded_rectangle((1, 1, 438, 218), radius=12, outline="black", width=2)
    buffer = io.BytesIO()
    frame.save(buffer, format="PNG")
    graph = Image.new("RGB", (60, 35), "white")
    ImageDraw.Draw(graph).line([(1, 28), (20, 3), (42, 17), (58, 2)], fill="black", width=2)
    picture = io.BytesIO()
    graph.save(picture, format="PNG")
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_text((40, 85), "9. Read the framed procedure.", fontsize=10)
        page.insert_image(fitz.Rect(40, 120, 260, 230), stream=buffer.getvalue())
        # This is shorter than the old long-prose threshold. The numbered
        # heading still has to remain native text inside the original frame.
        page.insert_text((52, 127), "1. Warm the sample.", fontsize=9)
        page.insert_text((52, 162), "The sample must remain at a steady temperature.", fontsize=8)
        page.insert_image(fitz.Rect(185, 185, 215, 203), stream=picture.getvalue(), keep_proportion=False)
        page.insert_image(fitz.Rect(310, 120, 510, 210), stream=buffer.getvalue(), keep_proportion=False)
        page.insert_text((325, 155), "2. Cool the sample.", fontsize=9)
        document.save(source)
    nested = SimpleNamespace(
        bbox=(40, 120, 260, 230), row_count=2, col_count=2,
        rows=rows([(40, 120, 260, 230), (150, 120, 260, 150)],
                  [(40, 150, 150, 230), (150, 150, 260, 230)]),
    )
    with patch.object(fitz.Page, "find_tables", return_value=SimpleNamespace(tables=[nested])):
        items, provenance = extract_native_content(source)
    assert items and any(p["role"] == "source_background_frame" for p in provenance)
    hwpx_writer_v2.write_hwpx(output, "Frame regression", items, "kice_science",
                             native_math=True, preserve_source_layout=True)
    # The independent auditor reads the real source; its table finder is not
    # patched. A nominally successful export must not conceal a prose crop.
    audit = inspect_pdf_editability(source, output, provenance, page_limit=1)
    assert not audit["rasterized_prose"], audit["rasterized_prose"]
    assert audit["native_source_text_coverage"] == 1, audit["missing_source_fragments"]
    assert audit["source_images"]["ok"], audit["source_images"]
    print("PASS false table rejected, short numbered prose native, source figure/background retained")
    print("NATIVE_FRAME_RECOGNITION_OK")


if __name__ == "__main__":
    try:
        run()
    finally:
        RUNTIME.cleanup()
