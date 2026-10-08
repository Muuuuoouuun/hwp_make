"""Measured English question bounds, generic reserves and edited native flow."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="source_question_height_")
os.environ["HWP_MAKE_DATA_DIR"] = str(Path(RUNTIME.name) / "engine")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fitz  # noqa: E402
from lxml import etree  # noqa: E402
import rhwp  # noqa: E402
from app.hwpx_writer_v2 import HwpxDocument, write_hwpx  # noqa: E402
from app.pdf_native_content import extract_native_content, annotate_question_groups  # noqa: E402
from app.pdf_native_typography import _flow_height, _source_literal_flow_bounds  # noqa: E402
from app.pdf_question_geometry import inspect_question_geometry  # noqa: E402
from app.pdf_question_rendering import inspect_question_rendering  # noqa: E402
from hwpx.oxml import HwpxOxmlParagraph  # noqa: E402
from hwpx.tools.package_validator import validate_package  # noqa: E402
from scripts.verify_native_shared_table_paragraphs import tokens, locate  # noqa: E402

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def check(condition, message):
    assert condition, message
    print("PASS:", message, flush=True)


def package(path):
    with zipfile.ZipFile(path) as archive:
        roots = [etree.fromstring(archive.read(name)) for name in sorted(archive.namelist())
                 if re.fullmatch(r"Contents/section\d+\.xml", name)]
        assets = {name: archive.read(name) for name in archive.namelist() if name.startswith("BinData/")}
    boxes = {draw.get("name"): draw for root in roots for draw in root.iter(HP + "drawText")
             if (draw.get("name") or "").startswith("question:")}
    return roots, boxes, assets


def paragraph_text(paragraph):
    return "".join(t.text or "" for t in paragraph.findall(HP + "run/" + HP + "t"))


def synthetic(folder):
    paragraph = etree.Element(HP + "p")
    cache = etree.SubElement(paragraph, HP + "linesegarray")
    for pos in (0, 1800):
        etree.SubElement(cache, HP + "lineseg", vertpos=str(pos), vertsize="1000",
                         textheight="1000", baseline="850", spacing="200")
    layout = {"source_content": True, "source_literal_text": True, "source_page_width_pt": 595,
              "source_typography": {"font_size_pt": 10, "source_bbox_pt": [40, 90, 260, 125],
                                    "lines": [{"bbox_pt": [40, 90, 260, 100]}]}}
    check(_source_literal_flow_bounds(paragraph, layout), "source English and positive native descender authorize measured flow")
    check(_flow_height(paragraph) == 2400 and _flow_height(paragraph, source_layout=layout) == 3000,
          "measured cache band retains a real baseline gap and final descender")
    run = etree.SubElement(paragraph, HP + "run")
    table = etree.SubElement(run, HP + "tbl")
    etree.SubElement(table, HP + "sz", height="5000", width="12000")
    check(_flow_height(paragraph, source_layout=layout) == 5400,
          "native table reserve remains 400 units for proved English too")
    for key in ("source_content", "source_literal_text", "source_page_width_pt"):
        bad = deepcopy(layout); bad.pop(key)
        check(not _source_literal_flow_bounds(paragraph, bad), f"missing {key} keeps the generic reserve")
    for key, value in (("font_size_pt", 0), ("source_bbox_pt", [40, 90, 40, 125]), ("lines", [])):
        bad = deepcopy(layout); bad["source_typography"][key] = value
        check(not _source_literal_flow_bounds(paragraph, bad), f"invalid source {key} cannot shrink a wrapper")
    for field, value in (("baseline", "1000"), ("textheight", "0"), ("spacing", "-1"), ("vertpos", "nan")):
        bad = deepcopy(paragraph); next(bad.iter(HP + "lineseg")).set(field, value)
        check(not _source_literal_flow_bounds(bad, layout), f"invalid cached {field} retains the generic reserve")
    bad = deepcopy(paragraph); etree.SubElement(next(bad.iter(HP + "run")), HP + "equation")
    check(not _source_literal_flow_bounds(bad, layout), "native math remains on the original conservative path")

    source = folder / "source.pdf"
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_text((150, 38), "English source height")
        page.insert_text((40, 95), "1. Read the original English paragraph.", fontsize=10)
        for index, text in enumerate(("A growing paragraph retains its descenders.",
                                      "Every printed word remains editable here.",
                                      "Following questions move after an ordinary edit.")):
            page.insert_text((40, 125 + index * 15), text, fontsize=10)
        page.insert_text((40, 230), "2. The next question follows the first one.", fontsize=10)
        document.save(source)
    items, _ = extract_native_content(source, area_hint="영어 영역")
    annotate_question_groups(items)
    output = folder / "proved.hwpx"
    write_hwpx(output, "English source", items, "kice_english", native_math=True, preserve_source_layout=True)
    _, proved, _ = package(output)
    altered = deepcopy(items)
    next(item for item in altered if item["layout"].get("question_number") == 1)["layout"].pop("source_literal_text")
    fallback = folder / "unproved.hwpx"
    write_hwpx(fallback, "English source", altered, "kice_english", native_math=True, preserve_source_layout=True)
    _, unproved, _ = package(fallback)
    # The removed reserve becomes real source whitespace when the following
    # source anchor still has room; compare the editable content band rather
    # than a wrapper which may also carry that conserved bottom margin.
    height = lambda boxes: int(boxes["question:v1:q01"].find(HP + "subList").get("textHeight"))
    check(height(unproved) - height(proved) == 400,
          "real saved wrapper drops exactly one reserve only when every source entry is proved")
    check(all(inspect_question_geometry(draw)["ok"] for draw in proved.values()),
          "saved proved question boxes contain actual native geometry")


def check_native(path, expected_count=45):
    roots, boxes, assets = package(path)
    check(len(boxes) == expected_count and all(inspect_question_geometry(draw)["ok"] for draw in boxes.values()),
          f"{path.name}: all {expected_count} native question bounds contain their content")
    validation = validate_package(path)
    check(validation.ok and not validation.warnings, f"{path.name}: package schema references and controls remain valid")
    rendered = inspect_question_rendering(path, rhwp)
    check(rendered["ok"], f"{path.name}: all native text and figure assets paint visibly")
    return roots, boxes, assets


def actual(path, folder):
    if not path.is_file():
        print("MISSING:", path); return 2
    roots, boxes, assets = check_native(path)
    parsed = rhwp.parse(str(path))
    check(parsed.page_count == 8, "actual high3 source retains eight rendered pages")
    before_tokens = tokens(path)
    q27, q28 = boxes["question:v1:q27"], boxes["question:v1:q28"]
    last27 = paragraph_text(q27.find(HP + "subList").findall(HP + "p")[-1])
    first28 = paragraph_text(q28.find(HP + "subList").findall(HP + "p")[0])
    a, b = locate(before_tokens, last27), locate(before_tokens, first28)
    check(a[-1][3] == b[0][3] == 3 and b[0][2] - a[-1][2] > 10,
          "source page four contains Q27/Q28 with a visible nonoverlapping gap")

    document = HwpxDocument.open(path)
    section, draw = next((section, draw) for section in document.sections for draw in section.element.iter(HP + "drawText")
                         if draw.get("name") == "question:v1:q27")
    node = next(p for p in draw.iter(HP + "p")
                if paragraph_text(p).startswith("Our school is holding"))
    public = HwpxOxmlParagraph(node, section)
    original = public.text
    addition = " A longer editable condition must grow this notice and move the following question." * 3 + " HEIGHT_EDIT_END"
    public.text = original + addition
    edited = folder / "high3-height-edited.hwpx"
    document.save_to_path(edited)
    edited_roots, edited_boxes, edited_assets = check_native(edited)
    check(edited_assets == assets and sum(1 for root in roots for _ in root.iter(HP + "p")) ==
          sum(1 for root in edited_roots for _ in root.iter(HP + "p")),
          "ordinary table-cell edit retains all assets and paragraph ownership")
    old_height = int(q27.getparent().find(HP + "sz").get("height"))
    new_height = int(edited_boxes["question:v1:q27"].getparent().find(HP + "sz").get("height"))
    check(new_height > old_height, "positive text growth enlarges the native question wrapper")
    painted = tokens(edited)
    grown = locate(painted, original + addition)
    after27, after28 = locate(painted, last27), locate(painted, first28)
    check(len({(t[3], t[1] > 400) for t in grown}) == 1,
          "edited notice remains inside one native page/column")
    check((after28[0][3], after28[0][1]) > (b[0][3], b[0][1]) or after28[0][2] > b[0][2],
          "growing Q27 moves the following Q28 in document flow")
    check((after27[-1][3], after27[-1][1] > 400) < (after28[0][3], after28[0][1] > 400)
          or after28[0][2] > after27[-1][2] + 10, "edited consecutive questions do not overlap")
    # Assess real PDF font ink, including descenders, rather than baseline-only SVG points.
    parsed_edited = rhwp.parse(str(edited))
    with fitz.open(stream=bytes(parsed_edited.render_pdf()), filetype="pdf") as pdf:
        ink = [char for page in pdf for trace in page.get_texttrace() for char in trace["chars"]
               if not chr(char[0]).isspace()]
        sequence = "".join(chr(char[0]) for char in ink)
        value = re.sub(r"\s+", "", original + addition)
        check(sequence.count(value) == 1, "edited text has one complete independent native PDF glyph inventory")
        selected = ink[sequence.index(value):sequence.index(value) + len(value)]
        source_root = edited_roots[1]
        page = source_root.find(".//" + HP + "pagePr")
        margin = page.find(HP + "margin")
        left, right = float(margin.get("left")) / 100, (float(page.get("width")) - float(margin.get("right"))) / 100
        top = (float(margin.get("top")) + float(margin.get("header", "0"))) / 100
        bottom = (float(page.get("height")) - float(margin.get("bottom"))) / 100
        check(all(left - .3 <= char[3][0] < char[3][2] <= right + .3 and
                  top - .3 <= char[3][1] < char[3][3] <= bottom + .3 for char in selected),
              "edited native glyph ink and positive descenders remain in printable bounds")
    reopened = folder / "high3-height-reopened.hwpx"
    HwpxDocument.open(edited).save_to_path(reopened)
    again, _, _ = package(reopened)
    check([etree.tostring(root) for root in again] == [etree.tostring(root) for root in edited_roots]
          and tokens(reopened) == painted, "reopening and resaving preserves stable grown native geometry and painting")
    (folder / "height-edit-summary.json").write_text(json.dumps({"pages_before": parsed.page_count,
        "pages_edited": parsed_edited.page_count, "height_before": old_height, "height_after": new_height,
        "q28_before": b[0][1:], "q28_after": after28[0][1:], "edited_glyphs": len(selected)}, indent=2), encoding="utf-8")
    (folder / "height-edited-p4.png").write_bytes(bytes(parsed_edited.render_png(3)))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--high3-hwpx", type=Path)
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args()
    folder = args.artifacts or Path(RUNTIME.name)
    folder.mkdir(parents=True, exist_ok=True)
    synthetic(folder)
    return actual(args.high3_hwpx, folder) if args.high3_hwpx else 0


if __name__ == "__main__":
    raise SystemExit(main())
