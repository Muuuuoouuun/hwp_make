"""Regression: native source tables retain cell images and merged geometry."""
# ruff: noqa: E402 -- isolate application storage before importing the writer.
import io
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = tempfile.TemporaryDirectory(prefix="native_table_assets_")
os.environ["HWP_MAKE_DATA_DIR"] = runtime.name
import fitz
from lxml import etree
from PIL import Image, ImageDraw
from app import hwpx_writer_v2
from app.pdf_native_content import extract_native_content, _figure_inside_table
from app.pdf_source_image_validation import inspect_source_images

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def run():
    # Real Korean page-5 boundary: centre in table, only 58% of figure inside.
    boundary_figure = fitz.Rect(99.371, 412.478, 410.311, 439.608)
    boundary_table = fitz.Rect(106.643, 231.739, 374.55, 430.852)
    assert boundary_table.contains((boundary_figure.tl + boundary_figure.br) / 2)
    assert not _figure_inside_table(boundary_figure, boundary_table)
    assert not _figure_inside_table(fitz.Rect(), boundary_table)
    folder = Path(runtime.name)
    source, output = folder / "source.pdf", folder / "native.hwpx"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((40, 40), "Science Test")
    page.insert_text((40, 90), "1. Compare the two distributions.")
    xs, ys = [40, 70, 170, 270], [115, 140, 205, 235]
    for x in xs:
        page.draw_line((x, ys[1] if x == 170 else ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    page.insert_text((90, 133), "A")
    page.insert_text((190, 133), "B")
    page.insert_text((45, 225), "Size", fontsize=8)
    page.insert_text((90, 225), "10")
    page.insert_text((190, 225), "20")
    page.insert_text((40, 255), "Choose A or B and explain the difference.", fontsize=10)
    for col, points in [(1, [(3, 35), (22, 5), (60, 20)]), (2, [(3, 5), (22, 35), (60, 10)])]:
        picture = Image.new("RGB", (70, 42), "white")
        ImageDraw.Draw(picture).line(points, fill="black", width=3)
        buffer = io.BytesIO()
        picture.save(buffer, format="PNG")
        page.insert_image(fitz.Rect(xs[col] + 5, 148, xs[col+1] - 5, 197), stream=buffer.getvalue())
    # Cross the final table edge, with the centre just inside. It must remain
    # a whole sibling figure instead of failing cell assignment or disappearing.
    page.insert_image(fitz.Rect(30, 227, 280, 242), stream=buffer.getvalue(), keep_proportion=False)
    page.insert_text((310, 90), "2. Explain your answer.")
    doc.save(source)
    items, provenance = extract_native_content(source)
    assert len(provenance) == 3
    hwpx_writer_v2.write_hwpx(output, "Science Test", items, "kice_science", native_math=True, preserve_source_layout=True)
    with zipfile.ZipFile(output) as package:
        root = etree.fromstring(package.read("Contents/section0.xml"))
        assets = {hashlib.sha256(package.read(name)).hexdigest(): package.read(name)
                  for name in package.namelist() if name.startswith("BinData/")}
    boxes = list(root.iter(HP + "drawText"))
    assert len(boxes) == 2
    box = next(b for b in boxes if b.get("name") == "question:v1:q01")
    picture_cells = [cell for cell in box.iter(HP + "tc") if list(cell.iter(HP + "pic"))]
    assert len(picture_cells) == 2
    assert [(c.find(HP + "cellAddr").get("rowAddr"), c.find(HP + "cellAddr").get("colAddr")) for c in picture_cells] == [("1", "1"), ("1", "2")]
    assert all(len(list(c.iter(HP + "pic"))) == 1 for c in picture_cells)
    merged = [cell for cell in box.iter(HP + "tc")
              if cell.find(HP + "cellSpan").get("colSpan") == "2"]
    assert len(merged) == 1
    assert merged[0].find(HP + "cellAddr").get("rowAddr") == "0"
    assert "A" in "".join(merged[0].itertext()) and "B" in "".join(merged[0].itertext())
    with fitz.open(source) as document:
        audit = inspect_source_images(document, assets, provenance)
    assert audit["ok"], audit
    import rhwp
    from app.pdf_question_rendering import inspect_question_rendering
    assert inspect_question_rendering(output, rhwp)["ok"]
    rendered = rhwp.parse(str(output)).render_svg(0)
    assert rendered.count("<image") == 3
    print("NATIVE_TABLE_ASSETS_OK: two cell figures plus boundary sibling, native text, geometry and rendering")


if __name__ == "__main__":
    run()
