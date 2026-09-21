"""Exercise independent source bitmap inventory and forged image provenance."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

import fitz
from lxml import etree
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app.pdf_source_image_validation import inspect_source_images, compare_source_crop, render_source_crop, native_bordered_table_texts  # noqa: E402


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS:", message)


def png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def synthetic():
    pictures = []
    for rising in (True, False):
        image = Image.new("RGB", (240, 180), "white")
        draw = ImageDraw.Draw(image)
        draw.line((20, 10, 20, 160, 225, 160), fill="black", width=3)
        draw.line((25, 145 if rising else 30, 210, 30 if rising else 145), fill="black", width=7)
        pictures.append(png(image))
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_text((45, 60), "Science examination", fontsize=14)
        page.insert_text((45, 140), "1. Compare graphs A and B in the table.", fontsize=10)
        page.draw_rect(fitz.Rect(40, 190, 330, 300))
        page.draw_line(fitz.Point(185, 190), fitz.Point(185, 300))
        rectangles = [fitz.Rect(50, 200, 170, 290), fitz.Rect(200, 200, 320, 290)]
        for rectangle, image in zip(rectangles, pictures):
            page.insert_image(rectangle, stream=image)
        page.get_text("dict")
        provenance, assets = [], {}
        for rectangle in rectangles:
            payload = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rectangle, alpha=False).tobytes("png")
            digest = hashlib.sha256(payload).hexdigest()
            assets[digest] = payload
            provenance.append({"sha256": digest, "role": "source_figure", "page": 1,
                               "bbox_px": [rectangle.x0, rectangle.y0, rectangle.width, rectangle.height],
                               "page_width_px": 595, "page_height_px": 842})
        good = inspect_source_images(document, assets, provenance)
        check(good["ok"] and good["source_embedded_images"] == 2,
              "independent source inventory includes both pictures inside the table")
        omitted = inspect_source_images(document, assets, provenance[:1])
        check(len(omitted["missing_source_images"]) == 1 and "source_embedded_picture_missing" in omitted["issues"],
              "omitting a picture from writer provenance cannot erase it from expected source inventory")
        forged = deepcopy(provenance)
        forged[0]["sha256"] = forged[1]["sha256"]
        wrong = inspect_source_images(document, {forged[1]["sha256"]: assets[forged[1]["sha256"]]}, forged)
        check("source_picture_pixels_mismatch" in wrong["issues"] and wrong["mismatched_source_crops"][0]["index"] == 0,
              "another same-size graph is rejected even when the writer replaces its digest claim")
        check(len(wrong["missing_source_images"]) == 1,
              "a pixel-invalid source claim cannot satisfy source image completeness")
        removed = inspect_source_images(document, {}, [])
        check(len(removed["missing_source_images"]) == 2,
              "deleting all pictures and all provenance fails the independent source inventory")
        actual = assets[provenance[0]["sha256"]]
        with Image.open(io.BytesIO(actual)) as image:
            tiny = png(image.resize((20, 15)))
        check(not compare_source_crop(actual, tiny)["ok"],
              "a low-resolution thumbnail is not resized into a passing source match")
        wrong_white = png(Image.new("RGB", (240, 180), "white"))
        check(not compare_source_crop(actual, wrong_white)["ok"],
              "an empty same-size image cannot replace the source graph")

    # High-resolution JPEGs can be decoded at different subsampling levels by
    # MuPDF. The canonical clip is independent of extraction and crop order.
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        texture = Image.effect_noise((1600, 1200), 70).convert("RGB")
        encoded = io.BytesIO()
        texture.save(encoded, format="JPEG", quality=83)
        page.insert_image(fitz.Rect(40, 160, 360, 400), stream=encoded.getvalue())
        source = document.tobytes()
        region = fitz.Rect(70, 185, 240, 320)
        first = render_source_crop(source, 0, region)
        page.get_text("dict")
        page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5))
        render_source_crop(source, 0, fitz.Rect(45, 170, 120, 225))
        check(first == render_source_crop(source, 0, region),
              "fresh source rendering is exact after text decode and unrelated crops")


def native_frame_regression():
    hp = "http://www.hancom.co.kr/hwpml/2011/paragraph"
    hh = "http://www.hancom.co.kr/hwpml/2011/head"
    header = etree.fromstring(f'<head xmlns="{hh}"><borderFill id="1">' + ''.join(
        f'<{side}Border type="SOLID" color="#000000" width="0.1 mm"/>'
        for side in ('left', 'right', 'top', 'bottom')) + '</borderFill></head>')
    root = etree.fromstring(f'<root xmlns="{hp}"><tbl rowCnt="1" colCnt="1"><tr><tc borderFillIDRef="1"><cellAddr rowAddr="0" colAddr="0"/><cellSpan rowSpan="1" colSpan="1"/><subList><p><run><t>Actual editable passage.</t></run></p></subList></tc></tr></tbl></root>')
    proofs = native_bordered_table_texts([root], header)
    check(proofs == ['Actualeditablepassage.'], 'native frame proof reads actual text and all four visible cell borders')
    broken = deepcopy(header)
    broken.find(f'.//{{{hh}}}rightBorder').set('color', '#FFFFFF')
    check(not native_bordered_table_texts([root], broken), 'a white native table edge does not prove visible frame reconstruction')
    for graph in (False, True):
        image = Image.new('RGB', (400, 200), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 399, 199), outline='black', width=2)
        draw.ellipse((20, 20, 40, 40), fill='black')  # preserved corner decoration
        if graph:
            draw.line((200, 150, 300, 90), fill='black', width=4)
        with fitz.open() as document:
            page = document.new_page(width=595, height=842)
            page.insert_text((45, 140), '1. Read the boxed passage.', fontsize=10)
            page.insert_image(fitz.Rect(100, 200, 300, 300), stream=png(image))
            page.insert_text((115, 240), 'Actual editable passage.', fontsize=10)
            source = document.tobytes()
            region = fitz.Rect(108, 208, 122, 222)
            payload = render_source_crop(source, 0, region)
            digest = hashlib.sha256(payload).hexdigest()
            provenance = [{'sha256': digest, 'role': 'source_figure', 'page': 1,
                           'bbox_px': [108, 208, 14, 14], 'page_width_px': 595, 'page_height_px': 842}]
            result = inspect_source_images(document, {digest: payload}, provenance, native_table_texts=proofs)
            check(result['ok'] != graph, 'a reconstructed frame passes but a missing diagram inside that frame fails' + f' (diagram={graph})')
            if not graph:
                check(not inspect_source_images(document, {}, [], native_table_texts=proofs)['ok'],
                      'native frame reconstruction cannot conceal its missing decoration')
                check(not inspect_source_images(document, {digest: payload}, provenance, native_table_texts=['Differenttext'])['ok'],
                      'a bordered native table containing different text cannot satisfy the frame proof')


def verify_real(source, output, provenance, *, missing_expected=0):
    with zipfile.ZipFile(output) as package:
        manifest = etree.fromstring(package.read("Contents/content.hpf"))
        hrefs = {n.get("id"): n.get("href") for n in manifest.iter("{http://www.idpf.org/2007/opf/}item")}
        assets = {}
        for filename in package.namelist():
            if not (filename.startswith("Contents/section") and filename.endswith(".xml")):
                continue
            root = etree.fromstring(package.read(filename))
            for pic in root.iter("{http://www.hancom.co.kr/hwpml/2011/paragraph}pic"):
                img = pic.find(".//{http://www.hancom.co.kr/hwpml/2011/core}img")
                data = package.read(hrefs[img.get("binaryItemIDRef")])
                assets[hashlib.sha256(data).hexdigest()] = data
    with fitz.open(source) as document:
        result = inspect_source_images(document, assets, provenance)
    check(not result["mismatched_source_crops"], f"actual source crop pixels match: {output.name}")
    check(len(result["missing_source_images"]) == missing_expected,
          f"independent expected-source inventory: {output.name}, missing={missing_expected}")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-folder", type=Path)
    parser.add_argument("--old-earth2-missing", action="store_true")
    args = parser.parse_args()
    synthetic()
    native_frame_regression()
    if args.audit_folder:
        for folder in ("earth1", "earth2", "earth_csat"):
            directory = args.audit_folder / folder / "run_1"
            report = json.loads((directory / "engine_report.json").read_text(encoding="utf-8"))
            stats = json.loads((directory / "writer_stats.json").read_text(encoding="utf-8"))
            source = ROOT / "data/uploads" / report["source"]["name"]
            output = directory / (source.stem + "_native.hwpx")
            verify_real(source, output, stats["image_provenance"],
                        missing_expected=2 if args.old_earth2_missing and folder == "earth2" else 0)
    print("SOURCE_IMAGE_VALIDATION_OK")
