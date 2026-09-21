"""Real PDF: labels stay in their figure and adjacent wraps stay one paragraph."""
# ruff: noqa: E402
from copy import deepcopy
import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = tempfile.TemporaryDirectory(prefix="native_figure_labels_")
os.environ["HWP_MAKE_DATA_DIR"] = runtime.name
import fitz
from lxml import etree
from PIL import Image, ImageDraw
import rhwp
from app.hwpx_writer_v2 import write_hwpx
from app.pdf_native_content import extract_native_content
from app.pdf_layout_writer import _iter_text_lines, _line_text
from app.pdf_question_rendering import inspect_question_rendering
from app.pdf_source_image_validation import inspect_source_images
from app.pdf_table_gutters import retained_figure_label

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def run():
    folder = Path(runtime.name)
    source, target = folder / "source.pdf", folder / "native.hwpx"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((40, 38), "Original illustration and native paragraph")
    page.insert_text((40, 85), "1. Explain the measured evidence in the diagram.", fontsize=10)
    picture = Image.new("RGB", (140, 120), "white")
    drawing = ImageDraw.Draw(picture)
    drawing.rectangle((1, 1, 138, 118), outline="black", width=2)
    drawing.ellipse((10, 18, 63, 77), outline="black", width=2)
    drawing.polygon([(78, 75), (106, 17), (130, 75)], outline="black", width=2)
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    region = fitz.Rect(45, 130, 145, 216)
    page.insert_image(region, stream=buffer.getvalue())
    page.insert_text((56, 158), "Alpha", fontsize=7)
    page.insert_text((105, 184), "Beta", fontsize=7)
    lines = ["Measured objects", "show two separate", "responses under", "the same pressure."]
    # The first baseline precedes the image top; its ink still overlaps the
    # figure vertically, exactly where naive top sorting split the paragraph.
    for y, text in zip((132, 147, 162, 177), lines):
        page.insert_text((155, y), text, fontsize=10)
    page.insert_text((310, 85), "2. Retain the complete explanation as editable text.", fontsize=10)
    page.insert_text((310, 108), "Every sentence must survive the conversion.", fontsize=10)
    doc.save(source)
    items, provenance = extract_native_content(source)
    body = " ".join(lines)
    matching = [i for i in items if body in i.get("stem", "")]
    assert len(matching) == 1, [(i["stem"], i["tables"]) for i in items]
    assert not any("Alpha" in i.get("stem", "") or "Beta" in i.get("stem", "")
                   or any("Alpha" in str(t) or "Beta" in str(t) for t in i["tables"])
                   for i in items), "source illustration labels leaked into prose"
    assert sum(len(i.get("image_paths", [])) for i in items) == 1
    assert not any(i["tables"] for i in items), "figure outline became an extra text box"
    write_hwpx(target, "Illustration labels", items, "kice_english", native_math=True,
               preserve_source_layout=True)
    with zipfile.ZipFile(target) as package:
        roots = [etree.fromstring(package.read(n)) for n in package.namelist()
                 if n.startswith("Contents/section") and n.endswith(".xml")]
        assets = {hashlib.sha256(package.read(n)).hexdigest(): package.read(n)
                  for n in package.namelist() if n.startswith("BinData/")}
    paragraphs = ["".join(t.text or "" for t in p.findall(HP + "run/" + HP + "t"))
                  for root in roots for p in root.iter(HP + "p")]
    assert sum(body in p for p in paragraphs) == 1, paragraphs
    assert inspect_source_images(doc, assets, provenance)["ok"]
    assert inspect_question_rendering(target, rhwp)["ok"]
    label = next(line for line in _iter_text_lines(page) if _line_text(line) == "Alpha")
    assert retained_figure_label(label, [{"bbox": region}], body_font_size=10)
    for text, size in (("1. solve", 7), ("① answer", 7), ("End.", 7),
                       ("a complete native sentence", 7), ("Alpha", 10)):
        mutant = deepcopy(label)
        mutant["spans"][0].update(text=text, size=size)
        assert not retained_figure_label(mutant, [{"bbox": region}], body_font_size=10), text
    outside = deepcopy(label)
    outside["bbox"] = fitz.Rect(300, 150, 330, 160)
    assert not retained_figure_label(outside, [{"bbox": region}], body_font_size=10)
    print("NATIVE_FIGURE_LABELS_OK: original figure pixels; no duplicate label boxes; adjacent wraps remain one native paragraph; prose/markers retained")


if __name__ == "__main__":
    run()
