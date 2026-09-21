"""Independent source/native checks for lost or wrongly attached script glyphs."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import zipfile

import fitz
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import pdf_layout_writer as w  # noqa: E402
from app.pdf_script_attachments import (  # noqa: E402
    inspect_script_attachments,
    source_script_attachments,
)


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS:", message)


def synthetic():
    def span(text, x, y, size, width):
        return {"text": text, "origin": (x, y), "size": size,
                "bbox": (x, y-size, x+width, y+size*.2)}

    def pair(base, value, lower=False):
        return {"spans": [span(base, 10, 30, 10, 25), span(value, 35, 33 if lower else 25, 7, 8)]}

    lines = [pair("5×10", "-7"), pair("2.5×10", "-3"), pair("=10", "15"),
             pair("R", "2", True), pair("10m/s", "2"), pair("R", "2")]
    expected = source_script_attachments(lines)
    check(len(expected) == 6, "geometry recovers powers, unit squares and subscripts")
    correct = ["5 times 10^{-7}", "2.5 times 10^{-3}", "T_2-T_1=10^{15}", "R_2", "10m/s^2", "R^2"]
    check(inspect_script_attachments(expected, correct)["ok"], "native equation attachments preserve source geometry")
    check(not inspect_script_attachments(expected, [s.replace("^", "").replace("_", "") for s in correct])["ok"],
          "same literal characters cannot conceal flattened powers or subscripts")
    swapped = ["5times10^{-3}", "2.5times10^{-7}"] + correct[2:]
    check(not inspect_script_attachments(expected, swapped)["ok"], "same exponent inventory cannot conceal swapped scientific coefficients")
    wrong = correct.copy()
    wrong[3] = "R^2"
    check(not inspect_script_attachments(expected, wrong)["ok"], "superscript cannot replace the corresponding source subscript")
    repeated = expected + [expected[0]]
    check(not inspect_script_attachments(repeated, correct)["ok"], "one native attachment cannot satisfy two source occurrences")
    plain = deepcopy(lines)
    for line in plain:
        line["spans"][1]["origin"] = (35, 30)
    check(not source_script_attachments(plain), "small baseline text is not automatically interpreted as an exponent")
    distant = deepcopy(lines)
    for line in distant:
        line["spans"][1]["bbox"] = (150, 20, 158, 27)
    check(not source_script_attachments(distant), "distant raised table text cannot attach to another cell")


def actual(folder):
    rows = []
    for item in json.loads((folder / "audit.json").read_text(encoding="utf-8")):
        output = folder / (Path(item["source"]["name"]).stem + "_native.hwpx")
        source = ROOT / "data/uploads" / item["source"]["name"]
        expected = []
        with fitz.open(source) as pdf:
            for index, page in enumerate(pdf):
                body_top = w._page_body_top(page)
                regions = []
                for image in item["stats"]["image_provenance"]:
                    if image["page"] != index + 1:
                        continue
                    x, y, width, height = image["bbox_px"]
                    sx, sy = page.rect.width/image["page_width_px"], page.rect.height/image["page_height_px"]
                    regions.append(fitz.Rect(x*sx, y*sy, (x+width)*sx, (y+height)*sy))
                lines = [line for line in w._iter_text_lines(page)
                         if w._item_bbox(line).y1 >= body_top-1
                         and not w._is_flow_footer_line(page, line)
                         and not w._inside_any_region(w._item_bbox(line), regions)]
                for entry in source_script_attachments(lines):
                    entry["page"] = index + 1
                    expected.append(entry)
        with zipfile.ZipFile(output) as package:
            scripts = [node.text or "" for name in package.namelist()
                       if name.startswith("Contents/section") and name.endswith(".xml")
                       for node in etree.fromstring(package.read(name)).iter("{http://www.hancom.co.kr/hwpml/2011/paragraph}script")]
        report = inspect_script_attachments(expected, scripts)
        rows.append({"source": str(source), "output": str(output), "inventory": expected, **report})
        print(json.dumps(rows[-1], ensure_ascii=False))
    check(all(row["ok"] for row in rows), "all actual source attachment occurrences survive in native equations")


def question_ownership():
    from app.hwpx_writer_v2 import write_hwpx
    from app.pdf_native_content import annotate_question_groups
    from app.pdf_question_inspection import inspect_question_units

    with tempfile.TemporaryDirectory(prefix="script_ownership_") as temporary:
        source, output, wrong = [Path(temporary) / name for name in ("science.pdf", "native.hwpx", "wrong.hwpx")]
        items = []
        with fitz.open() as pdf:
            page = pdf.new_page(width=595, height=842)
            page.insert_text((45, 60), "Science examination", fontsize=14)
            for number, y, power in ((1, 140, 5), (2, 350, 7)):
                heading = f"{number}. Determine the scientific power."
                page.insert_text((45, y), heading, fontsize=10)
                page.insert_text((45, y+25), "10", fontsize=10)
                page.insert_text((56.2, y+20), str(power), fontsize=7)
                items.append({"stem": heading + f"\n$10^{{{power}}}$", "source_page": 1,
                              "layout": {"source_content": True, "source_column": 0}})
            pdf.save(source)
        annotate_question_groups(items)
        write_hwpx(output, "Science examination", items, "kice_science", native_math=True, preserve_source_layout=True)
        check(inspect_question_units(source, output, provenance=[])["ok"], "each synthetic question owns its source exponent")
        hp = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
        with zipfile.ZipFile(output) as archive, zipfile.ZipFile(wrong, "w") as target:
            for entry in archive.infolist():
                data = archive.read(entry.filename)
                if entry.filename == "Contents/section0.xml":
                    root = etree.fromstring(data)
                    scripts = [box.find(f".//{hp}equation/{hp}script") for box in root.iter(hp+"drawText")]
                    scripts[0].text, scripts[1].text = scripts[1].text, scripts[0].text
                    data = etree.tostring(root, encoding="utf-8", xml_declaration=True)
                target.writestr(entry, data)
        report = inspect_question_units(source, wrong, provenance=[])
        check("source_question_script_attachment_missing" in report["issues"],
              "moving valid exponents between questions fails despite unchanged global equation inventory")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-folder", type=Path)
    args = parser.parse_args()
    synthetic()
    question_ownership()
    if args.real_folder:
        actual(args.real_folder)
    print("PDF_SCRIPT_ATTACHMENTS_OK")
