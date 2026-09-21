"""Original decorations must paint behind editable paragraphs and table cells."""
# ruff: noqa: E402
from copy import copy, deepcopy
import io
import os
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = tempfile.TemporaryDirectory(prefix="native_background_rendering_")
os.environ["HWP_MAKE_DATA_DIR"] = runtime.name

import fitz
from lxml import etree
from PIL import Image, ImageDraw
import rhwp
from app.pdf_editability import inspect_pdf_editability
from app.pdf_layout_writer import write_pdf_structured_hwpx
from app.pdf_question_rendering import inspect_question_rendering

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def bitmap(width, height):
    picture = Image.new("RGB", (width * 2, height * 2), "white")
    draw = ImageDraw.Draw(picture)
    draw.rounded_rectangle((1, 1, width * 2 - 2, height * 2 - 2),
                           radius=18, outline="black", width=3)
    draw.ellipse((10, 10, 18, 18), fill="black")
    data = io.BytesIO()
    picture.save(data, format="PNG")
    return data.getvalue()


def main():
    folder = Path(runtime.name)
    source, output = folder / "source.pdf", folder / "native.hwpx"
    lines = ["This announcement remains editable as a paragraph.",
             "The following sentence continues within the same box."]
    with fitz.open() as doc:
        page = doc.new_page(width=620, height=850)
        page.insert_text((40, 40), "English Test")
        page.insert_text((40, 100), "1. Read the announcement.", fontsize=10)
        page.insert_image(fitz.Rect(40, 140, 285, 265), stream=bitmap(245, 125))
        for i, text in enumerate(lines):
            page.insert_text((50, 180 + i * 14), text, fontsize=8)
        page.insert_text((330, 100), "2. Compare the descriptions.", fontsize=10)
        page.insert_image(fitz.Rect(325, 140, 575, 250), stream=bitmap(250, 110))
        for x in (325, 450, 575):
            page.draw_line((x, 140), (x, 250))
        for y in (140, 195, 250):
            page.draw_line((325, y), (575, y))
        for x, y, text in [
            (334, 166, "Apples grow during sunny summer days"),
            (459, 166, "Oranges grow during sunny winter days"),
            (334, 221, "Melons grow during sunny autumn days"),
            (459, 221, "Grapes grow during sunny spring days"),
        ]:
            page.insert_text((x, y), text, fontsize=5.5)
        doc.save(source)
    stats = write_pdf_structured_hwpx(source, output, native_math=True)
    audit = inspect_pdf_editability(source, output, stats["image_provenance"],
                                   require_question_boxes=True)
    assert audit["ok"], audit["issues"]
    rendered = inspect_question_rendering(output, rhwp)
    assert rendered["ok"], rendered
    assert rendered["checked_background_instances"] == 2, rendered
    assert rendered["rendered_pages"] == 1, rendered
    with zipfile.ZipFile(output) as package:
        root = etree.fromstring(package.read("Contents/section0.xml"))
        header = etree.fromstring(package.read("Contents/header.xml"))
        fills = {e.get("id"): e for e in header.iter(HH + "borderFill")}
        tables = [t for t in root.iter(HP + "tbl")
                  if fills[t.get("borderFillIDRef")].find(".//" + HC + "imgBrush") is not None]
        assert len(tables) == 2
        assert len(list(root.iter(HP + "drawText"))) == 2
        assert not list(root.iter(HP + "pic")), "decorations must not replace native text"
        assert {t.get("colCnt") for t in tables} == {"1", "2"}
        prose = ["".join(t.text or "" for t in p.findall(HP + "run/" + HP + "t"))
                 for p in root.iter(HP + "p")]
        assert any(all(line in p for line in lines) for p in prose), prose

        # A cell fill is a valid native representation. Embedded table cells
        # must paint it too; this used to disappear only inside a textbox.
        broken_root = deepcopy(root)
        table = next(t for t in broken_root.iter(HP + "tbl")
                     if t.get("rowCnt") == t.get("colCnt") == "1")
        cell = table.find(HP + "tr/" + HP + "tc")
        table_fill, cell_fill = table.get("borderFillIDRef"), cell.get("borderFillIDRef")
        table.set("borderFillIDRef", cell_fill)
        cell.set("borderFillIDRef", table_fill)
        broken = folder / "cell_fill_only.hwpx"
        with zipfile.ZipFile(broken, "w") as target:
            for info in package.infolist():
                data = etree.tostring(broken_root) if info.filename == "Contents/section0.xml" else package.read(info.filename)
                target.writestr(copy(info), data)
    regression = inspect_question_rendering(broken, rhwp)
    assert regression['ok'] and regression['checked_background_instances'] == 2, regression
    # Retain a real missing-paint mutation: all asset bytes and native text are
    # intact, but the source frame is placed outside the rendered page.
    with zipfile.ZipFile(broken) as package:
        hidden_root = etree.fromstring(package.read('Contents/section0.xml'))
        hidden_table = next(t for t in hidden_root.iter(HP+'tbl') if t.get('rowCnt') == t.get('colCnt') == '1')
        hidden_table.find(HP+'pos').set('horzOffset', '1000000')
        hidden = folder/'off_page_cell_fill.hwpx'
        with zipfile.ZipFile(hidden, 'w') as target:
            for info in package.infolist():
                target.writestr(copy(info), etree.tostring(hidden_root) if info.filename == 'Contents/section0.xml' else package.read(info.filename))
    regression = inspect_question_rendering(hidden, rhwp)
    assert not regression['ok'] and regression['missing_rendered_backgrounds'], regression
    print("NATIVE_BACKGROUND_RENDERING_OK: native table/cell fills paint, off-page background rejected")


if __name__ == "__main__":
    main()
