"""Regression checks for stacked math rows and tiled prose backgrounds."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

import fitz
from PIL import Image, ImageDraw
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="conversion_quality_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name

from app import pdf_layout_writer as w, pdf_math_geometry as geometry, hwpx_writer_v2  # noqa: E402
from app.pdf_native_content import _native_images_and_frames  # noqa: E402
from app.pdf_editability import inspect_pdf_editability  # noqa: E402


def png(image):
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def main():
    fixtures = json.loads((ROOT / "scripts/fixtures/stacked_math_rows.json").read_text(encoding="utf-8"))
    expected = {
        "12": (r"\overline{AC}=2\sqrt{14}", r"\overline{MH}^{3}+\overline{NH}^{3}"),
        "18": (r"\overline{BF}=\overline{CG}",
               r"\frac{2\sqrt{3}}{3}-1<\overline{BF}<\frac{2\sqrt{3}}{3}"),
        "25": (r"\frac{\overline{z}}{z})^{2n}+(\frac{z}{\sqrt{2}})^{2n}=0",),
    }
    for key, lines in fixtures.items():
        source = "\n".join(line["text"] for line in lines)
        # Repeat to catch reuse of temporary nested-token object identities.
        for _ in range(12):
            repaired, remaining = geometry.reconstruct_stacked_math_rows(source, lines)
            compact = re.sub(r"[\s$]+", "", repaired)
            assert all(value in compact for value in expected[key]), (key, repaired)
            assert "□" not in repaired and not remaining, (key, repaired)

    source = Path(RUNTIME.name) / "frames.pdf"
    frame = Image.new("RGB", (480, 240), "white")
    draw = ImageDraw.Draw(frame)
    draw.rectangle((2, 2, 477, 237), outline="black", width=2)
    figure = Image.new("RGB", (100, 60), "white")
    draw = ImageDraw.Draw(figure)
    for x in range(5, 96, 5):
        draw.line((x, 4, 100 - x, 55), fill="black", width=2)
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_text((45, 60), "Science examination", fontsize=15)
        page.insert_text((45, 145), "1. Read the observation in the following box.", fontsize=9)
        for index in range(3):
            page.insert_image(fitz.Rect(45, 175 + index * 40, 285, 215 + index * 40),
                              stream=png(frame.crop((0, index * 80, 480, (index + 1) * 80))))
        page.insert_text((55, 195), "This whole sentence must remain editable.", fontsize=9)
        page.insert_text((55, 210), "The illustration beneath it must also survive.", fontsize=9)
        page.insert_image(fitz.Rect(70, 230, 170, 290), stream=png(figure))
        page.insert_text((320, 145), "2. Compare the results of the experiment.", fontsize=9)
        pictures, frames = _native_images_and_frames(page, w._iter_text_lines(page))
        assert len(frames) == 1 and len(pictures) == 1, (frames, pictures)
        assert w._item_bbox(pictures[0]) == fitz.Rect(70, 230, 170, 290)
        document.save(source)
    output = Path(RUNTIME.name) / "frames.hwpx"
    stats = w.write_pdf_structured_hwpx(source, output)
    audit = inspect_pdf_editability(source, output, stats["image_provenance"])
    assert audit["ok"] and audit["images"] == 1, audit
    plain = w._structured_hwpx_plain_text(output)
    assert "Thiswholesentencemustremaineditable." in plain
    assert "Theillustrationbeneathitmustalsosurvive." in plain
    with zipfile.ZipFile(output) as package:
        root = etree.fromstring(package.read("Contents/section0.xml"))
    previous_y = -1
    for paragraph in root.findall(f"{{{w.HP}}}p"):
        if (paragraph.get("pageBreak") == "1" or paragraph.get("columnBreak") == "1"
                or paragraph.find(f".//{{{w.HP}}}colPr") is not None):
            previous_y = -1
        for line in paragraph.findall(f"{{{w.HP}}}linesegarray/{{{w.HP}}}lineseg"):
            current_y = int(line.get("vertpos", "0"))
            assert current_y >= previous_y, "paragraph cache accidentally resets the column"
            previous_y = current_y
    assert w._pdf_output_text("\ue0c8") == "°"
    choice_output = Path(RUNTIME.name) / "choice_fractions.hwpx"
    hwpx_writer_v2.write_hwpx(choice_output, "Native fraction choices", [{
        "number": "1", "stem": "Choose the correct fraction.",
        "choices": [rf"$\frac{{\sqrt{{3}}}}{{{n}}}$" for n in range(2, 7)],
        "source_page": 1, "layout": {"column_count": 2, "column_index": 1},
    }], "kice_math", native_math=True, preserve_source_layout=True)
    with zipfile.ZipFile(choice_output) as package:
        root = etree.fromstring(package.read("Contents/section0.xml"))
    checked_cells = 0
    for cell in root.findall(f".//{{{w.HP}}}tc"):
        equations = cell.findall(f".//{{{w.HP}}}equation/{{{w.HP}}}script")
        if not equations:
            continue
        checked_cells += 1
        height = int(cell.find(f"{{{w.HP}}}cellSz").get("height"))
        assert height >= max(hwpx_writer_v2._equation_size(script.text)[1]
                             for script in equations) + 300, "choice denominator is clipped"
    assert checked_cells == 5
    print("CONVERSION_QUALITY_REPAIRS_OK: 36 math-row checks; native prose, nested figure and column cache verified")


if __name__ == "__main__":
    main()
