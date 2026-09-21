"""Real PDF regression for duplicate figure markers and editable table gutters."""
# ruff: noqa: E402
from copy import deepcopy
import io
import os
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = tempfile.TemporaryDirectory(prefix="native_gutters_")
os.environ["HWP_MAKE_DATA_DIR"] = runtime.name
import fitz
from lxml import etree
from PIL import Image, ImageDraw
import rhwp
from app.hwpx_writer_v2 import write_hwpx
from app.pdf_native_content import extract_native_content
from app.pdf_layout_writer import _iter_text_lines
from app.pdf_source_semantics import source_grid_cells, _native_grids
from app.pdf_source_image_validation import inspect_source_images
from app.pdf_question_rendering import inspect_question_rendering

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def run(side="left"):
    folder = Path(runtime.name) / side
    folder.mkdir()
    merged = side.endswith("_merged")
    side = side.split("_")[0]
    source, target = folder / "source.pdf", folder / "native.hwpx"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((40, 38), "Diagram and row labels")
    page.insert_textbox(fitz.Rect(40, 85, 280, 123),
                        "1. Choose the numbered object in the illustration.", fontsize=10)
    picture = Image.new("RGB", (225, 140), "white")
    drawing = ImageDraw.Draw(picture)
    drawing.ellipse((15, 15, 95, 110), outline="black", width=3)
    drawing.rectangle((120, 30, 215, 100), outline="black", width=3)
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    region = fitz.Rect(45, 130, 270, 270)
    page.insert_image(region, stream=buffer.getvalue())
    for value, position in [("①", (65, 165)), ("②", (205, 205))]:
        page.insert_text(position, value, fontname="korea", fontsize=11)
    page.insert_text((40, 295), "Explain the differences between the two objects.", fontsize=10)
    page.insert_text((310, 85), "2. Compare the entries in the table.", fontsize=10)
    xs, ys = [331, 380, 442, 550], [120, 147, 174, 201, 228]
    if side == "right":
        xs = [310, 359, 421, 529]
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    if merged:
        for top, bottom in zip(ys[1:-1], ys[2:]):
            page.draw_line((xs[0], (top + bottom) / 2), (xs[-2], (top + bottom) / 2))
    matrix = [["Item", "Month", "Gift"], ["A", "June", "socks"],
              ["B", "July", "shirt"], ["C", "August", "bag"]]
    for r, row in enumerate(matrix):
        for c, text in enumerate(row):
            page.insert_text((xs[c] + 4, ys[r] + 18), text, fontsize=9)
        if r:
            value = chr(0x2460 + r - 1)
            if side == "right":
                value = "… " + value
            page.insert_text((315 if side == "left" else 533, ys[r] + 18), value,
                             fontname="korea", fontsize=10)
    doc.save(source)
    items, provenance = extract_native_content(source)
    diagram = [item for item in items if item["layout"].get("question_group") == "v1:q01"]
    assert sum(len(item.get("image_paths", [])) for item in diagram) == 1
    assert not any(item.get("tables") for item in diagram), "diagram markers duplicated into a prose table"
    assert "Explain the differences" in " ".join(item.get("stem", "") for item in diagram)
    source_grid = source_grid_cells(page, _iter_text_lines(page))[0]["cells"]
    gutter_col = 0 if side == "left" else 3
    assert [row[gutter_col] for row in source_grid if row[gutter_col] is not None] == (
        ["", "①", "②", "③"] if side == "left" else ["", "…①", "…②", "…③"])
    write_hwpx(target, "Diagram and row labels", items, "kice_english",
               native_math=True, preserve_source_layout=True)
    with zipfile.ZipFile(target) as package:
        root = etree.fromstring(package.read("Contents/section0.xml"))
        header = etree.fromstring(package.read("Contents/header.xml"))
        import hashlib
        assets = {hashlib.sha256(package.read(name)).hexdigest(): package.read(name)
                  for name in package.namelist() if name.startswith("BinData/")}
    box = root.find(f'.//{HP}drawText[@name="question:v1:q02"]')
    native = _native_grids(box, header)
    assert len(native) == 1 and native[0]["cells"] == source_grid
    table = box.find(".//" + HP + "tbl")
    assert not table.findall(".//" + HP + "tbl"), "gutter introduced nested tables"
    fills = {f.get("id"): f for f in header.iter(HH + "borderFill")}
    for row in table.findall(HP + "tr"):
        gutter = next((c for c in row.findall(HP + "tc")
                       if c.find(HP + "cellAddr").get("colAddr") == str(gutter_col)), None)
        if gutter is None:
            continue
        assert all(fills[gutter.get("borderFillIDRef")].find(HH + edge + "Border").get("type") == "NONE"
                   for edge in ("left", "right", "top", "bottom"))
    for mutation in ("missing", "swapped", "wrong_cell"):
        mutant = deepcopy(box)
        cells = mutant.findall(f".//{HP}tbl/{HP}tr/{HP}tc")
        labels = [c.find(".//" + HP + "t") for c in cells
                  if c.find(HP + "cellAddr").get("colAddr") == str(gutter_col)
                  and c.find(HP + "cellAddr").get("rowAddr") != "0"]
        a, b = labels[:2]
        if mutation == "missing":
            a.text = ""
        elif mutation == "swapped":
            a.text, b.text = b.text, a.text
        else:
            destination = next(c.find(".//" + HP + "t") for c in cells
                               if c.find(HP + "cellAddr").get("colAddr") != str(gutter_col))
            destination.text = (destination.text or "") + a.text
            a.text = ""
        assert _native_grids(mutant, header)[0]["cells"] != source_grid, mutation
    assert inspect_source_images(doc, assets, provenance)["ok"]
    assert inspect_question_rendering(target, rhwp)["ok"]
    print(f"NATIVE_TABLE_GUTTERS_OK ({side}, merged={merged}): source pixels retained; editable row labels; missing/swapped/misplaced labels rejected")


if __name__ == "__main__":
    run("left")
    run("right")
    run("right_merged")
