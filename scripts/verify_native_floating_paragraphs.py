"""Real PDFs: one paragraph wraps around a complete picture before/after edits."""
# ruff: noqa: E402
from copy import deepcopy
import base64
import io
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = tempfile.TemporaryDirectory(prefix="native_float_")
if __name__ == "__main__":
    os.environ["HWP_MAKE_DATA_DIR"] = runtime.name
import fitz
from lxml import etree
from PIL import Image, ImageDraw
import rhwp
from app.hwpx_writer_v2 import HwpxDocument, write_hwpx
from app.pdf_editability import inspect_pdf_editability
from app.pdf_floating_geometry import inspect_floating_picture
from app.pdf_native_content import extract_native_content
from app.pdf_picture_geometry import has_complete_picture_crop
from app.pdf_question_geometry import inspect_question_geometry
from app.pdf_question_rendering import inspect_question_rendering, _multiply, _transform, _bounds, _bitmap_identity, IDENTITY
from hwpx.oxml import HwpxOxmlParagraph

H = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
S = "{http://www.w3.org/2000/svg}"
LINES = ["Measured objects show", "two separate responses", "under the same pressure",
         "and support the conclusion", "that the original evidence remains fully editable",
         "after the text has been changed and saved again."]
BODY = " ".join(LINES)
ADDITION = (" Editing preserves the picture and keeps this entire passage in one paragraph."
            " Words return to the full column beneath the image. FLOAT_EDIT_END_QA0")


def package_state(path):
    with zipfile.ZipFile(path) as archive:
        root = etree.fromstring(archive.read("Contents/section0.xml"))
        assets = {name: archive.read(name) for name in archive.namelist() if name.startswith("BinData/")}
    return root, assets


def render_check(path, expected, left_picture, *, asset_payload=None):
    audit = inspect_question_rendering(path, rhwp)
    assert audit["ok"], audit
    assert audit["checked_floating_picture_instances"] >= 1
    document = rhwp.parse(str(path))
    if asset_payload is None:
        assert document.page_count == 1
    identity = _bitmap_identity(asset_payload) if asset_payload else None
    pictures, tokens = [], []
    for page in range(document.page_count):
        svg = etree.fromstring(document.render_svg(page).encode())
        for node in svg.iter():
            if node.tag not in {S + "image", S + "text"}:
                continue
            if any(a.tag == S + "defs" for a in node.iterancestors()):
                continue
            matrix = IDENTITY
            for ancestor in [*reversed(list(node.iterancestors())), node]:
                matrix = _multiply(matrix, _transform(ancestor.get("transform", "")))
            a, b = float(node.get("x", 0)), float(node.get("y", 0))
            if node.tag == S + "image":
                href = node.get("href") or node.get("{http://www.w3.org/1999/xlink}href", "")
                if identity and (not href.startswith("data:image/") or _bitmap_identity(base64.b64decode(href.split(",", 1)[1])) != identity):
                    continue
                pictures.append((page, _bounds(matrix, a, b, float(node.get("width", 0)), float(node.get("height", 0)))))
            else:
                tx, ty = matrix[0] * a + matrix[2] * b + matrix[4], matrix[1] * a + matrix[3] * b + matrix[5]
                value = "".join(node.itertext())
                tokens.extend((char, tx, ty, page) for char in value if not char.isspace())
    assert len(pictures) == 1, "the retained picture was duplicated or dropped"
    picture_page, (x, y, right, bottom) = pictures[0]
    w, h = right - x, bottom - y
    assert min(w, h) > 0
    text = "".join(token[0] for token in tokens)
    expected = re.sub(r"\s+", "", expected)
    start = text.find(expected)
    assert start >= 0, "the complete edited paragraph is not painted"
    body = tokens[start:start + len(expected)]
    assert {p for _, _, _, p in body} == {picture_page}, "the paragraph separated from its picture"
    assert not any(x - .1 <= tx <= x + w + .1 and y + .1 < ty < y + h - .1
                   for _, tx, ty, _ in body), "visible paragraph glyph overlaps its picture"
    assert any(ty > y + h and (tx < x + w if left_picture else tx > x)
               for _, tx, ty, _ in body), "text never returns to the full width below the figure"


def verify_existing(path, folder):
    document = HwpxDocument.open(path)
    candidates = [(section, p) for section in document.sections for p in section.element.iter(H + "p")
                  if any(pic.get("textWrap") == "SQUARE" and pic.find(H + "pos").get("treatAsChar") == "0"
                         for pic in p.findall(H + "run/" + H + "pic"))]
    if not candidates:
        return {"applicable": False, "checked_paragraphs": 0}
    section, node = max(candidates, key=lambda item: len("".join(item[1].itertext())))
    picture = node.find(H + "run/" + H + "pic")
    bitmap = picture.find("{http://www.hancom.co.kr/hwpml/2011/core}img")
    with zipfile.ZipFile(path) as archive:
        manifest = etree.fromstring(archive.read("Contents/content.hpf"))
        href = next(n.get("href") for n in manifest.iter("{http://www.idpf.org/2007/opf/}item") if n.get("id") == bitmap.get("binaryItemIDRef"))
        asset = archive.read(href)
        before_assets = {n: archive.read(n) for n in archive.namelist() if n.startswith("BinData/")}
    paragraph = HwpxOxmlParagraph(node, section)
    original = paragraph.text
    left_picture = int(picture.find(H + "pos").get("horzOffset")) < int(picture.find(H + "sz").get("width"))
    render_check(path, original, left_picture, asset_payload=asset)
    count = sum(len(list(s.element.iter(H + "p"))) for s in document.sections)
    paragraph.text += ADDITION
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "edited.hwpx"
    document.save_to_path(target)
    assert count == sum(len(list(s.element.iter(H + "p"))) for s in document.sections)
    assert inspect_floating_picture(picture, document.headers[0].element)["ok"]
    render_check(target, original + ADDITION, left_picture, asset_payload=asset)
    with zipfile.ZipFile(target) as archive:
        assert before_assets == {n: archive.read(n) for n in archive.namelist() if n.startswith("BinData/")}
        first = {n: archive.read(n) for n in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)}
    second = folder / "edited_twice.hwpx"
    document.save_to_path(second)
    with zipfile.ZipFile(second) as archive:
        assert first == {n: archive.read(n) for n in first}
    return {"applicable": True, "ok": True, "checked_paragraphs": 1, "added_characters": len(ADDITION)}


def verify(folder, shared, left_picture, first_indent=False):
    stem = ("shared" if shared else "question") + ("_left" if left_picture else "_right")
    stem += "_indented" if first_indent else ""
    source, target = folder / f"{stem}.pdf", folder / f"{stem}.hwpx"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((40, 38), "Native paragraph flow", fontsize=12)
    page.insert_text((40, 85), "[1 ~ 2] Read the passage." if shared else "1. Explain the evidence in the diagram.", fontsize=10)
    bitmap = Image.new("RGB", (170, 118), "white")
    drawing = ImageDraw.Draw(bitmap)
    drawing.rectangle((0, 0, 169, 117), outline="black", width=3)
    drawing.ellipse((20, 15, 150, 110), outline="blue", width=4)
    data = io.BytesIO()
    bitmap.save(data, format="PNG")
    page.insert_image(fitz.Rect(40, 105, 125, 164) if left_picture else fitz.Rect(180, 105, 265, 164), stream=data.getvalue())
    for baseline, text in zip((115, 130, 145, 160, 175, 190), LINES):
        x = 140 if left_picture and baseline < 175 else 40
        x += 12 if first_indent and baseline == 115 else 0
        page.insert_text((x, baseline), text, fontsize=10)
    if shared:
        page.insert_text((40, 370), "1. Choose the supported conclusion.", fontsize=10)
    page.insert_text((315, 85), "2. Retain every sentence.", fontsize=10)
    doc.save(source)
    items, provenance = extract_native_content(source)
    assert sum(BODY in item.get("stem", "") for item in items) == 1
    write_hwpx(target, "Paragraphs", items, "kice_english", native_math=True, preserve_source_layout=True)
    audit = inspect_pdf_editability(source, target, provenance, require_question_boxes=True)
    assert audit["ok"], audit["issues"]
    before, assets = package_state(target)
    with zipfile.ZipFile(target) as package:
        header = etree.fromstring(package.read("Contents/header.xml"))
    picture = before.find(".//" + H + "pic")
    paragraph = picture.getparent().getparent()
    assert "".join(paragraph.itertext()) == BODY
    assert len(paragraph.findall(H + "linesegarray/" + H + "lineseg")) == len(LINES)
    assert not paragraph.findall(".//" + H + "lineBreak")
    assert inspect_floating_picture(picture, header)["ok"]
    if first_indent:
        from hwpx.tools.paragraph_spacing import paragraph_indentation
        styles = {p.get("id"): p for p in header.iter("{http://www.hancom.co.kr/hwpml/2011/head}paraPr")}
        assert abs(paragraph_indentation(paragraph, styles)[2] - 12 * 59528 / 595) < 2
    assert bool(any(a.tag == H + "drawText" for a in paragraph.iterancestors())) != shared
    render_check(target, BODY, left_picture)
    for kind in ("cover", "detached", "off_column", "bad_wrap"):
        mutant = deepcopy(before)
        pic = mutant.find(".//" + H + "pic")
        pos = pic.find(H + "pos")
        if kind == "cover":
            line = pic.getparent().getparent().find(H + "linesegarray/" + H + "lineseg")
            line.set("horzpos", pos.get("horzOffset"))
            line.set("horzsize", pic.find(H + "sz").get("width"))
        elif kind == "detached":
            pos.set("vertOffset", "100000")
        elif kind == "off_column":
            pos.set("horzOffset", "100000")
        else:
            pic.set("textWrap", "IN_FRONT_OF_TEXT")
        assert not inspect_floating_picture(pic, header)["ok"], kind
    cropped = deepcopy(picture)
    cropped.find(H + "imgClip").set("right", "100")
    assert not has_complete_picture_crop(cropped, next(iter(assets.values())))
    altered = deepcopy(before)
    altered.find(".//" + H + "pic/" + H + "imgClip").set("right", "100")
    mutant_path = folder / f"{stem}_cropped.hwpx"
    with zipfile.ZipFile(target) as original, zipfile.ZipFile(mutant_path, "w") as mutant:
        for name in original.namelist():
            mutant.writestr(name, etree.tostring(altered) if name == "Contents/section0.xml" else original.read(name))
    assert "source_picture_cropped_in_output" in inspect_pdf_editability(source, mutant_path, provenance)["issues"]
    assert not inspect_question_rendering(mutant_path, rhwp)["ok"], "a partially cropped picture was counted as fully painted"
    editable = HwpxDocument.open(target)
    section, node = next((section, p) for section in editable.sections
                         for p in section.element.iter(H + "p") if p.find(H + "run/" + H + "pic") is not None)
    public = HwpxOxmlParagraph(node, section)
    public.text += ADDITION
    edited = folder / f"{stem}_edited.hwpx"
    editable.save_to_path(edited)
    after, retained = package_state(edited)
    assert assets == retained
    assert len(list(before.iter(H + "p"))) == len(list(after.iter(H + "p")))
    assert len(list(before.iter(H + "drawText"))) == len(list(after.iter(H + "drawText")))
    assert all(inspect_question_geometry(draw)["ok"] for draw in after.iter(H + "drawText"))
    pic = after.find(".//" + H + "pic")
    assert inspect_floating_picture(pic, editable.headers[0].element)["ok"]
    assert "".join(pic.getparent().getparent().itertext()) == BODY + ADDITION
    render_check(edited, BODY + ADDITION, left_picture)
    twice = folder / f"{stem}_twice.hwpx"
    editable.save_to_path(twice)
    assert etree.tostring(after) == etree.tostring(package_state(twice)[0])
    print(f"PASS: {stem}: one continuous paragraph, full source picture, {len(ADDITION)}-character edit/re-save and painted non-overlap; broken anchors/crops rejected")


def main():
    for shared in (False, True):
        for left_picture in (False, True):
            for first_indent in (False, True):
                verify(Path(runtime.name), shared, left_picture, first_indent)
    print("NATIVE_FLOATING_PARAGRAPHS_OK")


if __name__ == "__main__":
    main()
