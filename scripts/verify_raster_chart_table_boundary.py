"""A bar chart is not a numeric table; real ruled and aligned tables survive."""
from pathlib import Path
import io
import sys

import fitz
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pdf_layout_writer import _raster_native_table_items


def fixture(kind):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    bitmap = Image.new("RGB", (595, 842), "white")
    paint = ImageDraw.Draw(bitmap)
    ys = (150, 175, 200, 225) if kind == "aligned" else (150, 162, 182, 194, 214, 226)
    for y in ys:
        paint.line((40, y, 280, y), fill="black", width=1)
    if kind == "empty_ruled":
        for x in (40, 280):
            paint.line((x, 150, x, 226), fill="black", width=1)
    buffer = io.BytesIO()
    bitmap.save(buffer, format="PNG")
    page.insert_image(page.rect, stream=buffer.getvalue())
    font = fitz.Font("helv")
    for row, baseline in enumerate((161, 193, 225) if kind != "aligned" else (164, 189, 214)):
        for col, right in enumerate((75, 130, 190, 260)):
            text = str((row + 1) * (col + 1) * (2 if row % 2 else 11))
            # A data table remains aligned even when digit counts differ.
            x = right - font.text_length(text, fontsize=8)
            if kind == "bars":
                x += (row - 1) * (col + 2) * 5
            page.insert_text((x, baseline), text, fontsize=8)
    return doc


def main():
    for kind in ("bars", "empty_ruled", "aligned"):
        with fixture(kind) as doc:
            tables = _raster_native_table_items(doc[0])
            assert bool(tables) == (kind != "bars"), (kind, [list(t["bbox"]) for t in tables])
        print("PASS:", kind, "rejected" if kind == "bars" else "retained")
    print("RASTER_CHART_TABLE_BOUNDARY_OK")


if __name__ == "__main__":
    main()
