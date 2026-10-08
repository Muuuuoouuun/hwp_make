"""Prove trailing PDF spaces cannot split native prose or erase answer blanks."""
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
RUNTIME = tempfile.TemporaryDirectory(prefix="native_prose_ink_")
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name

import fitz
from lxml import etree
import rhwp
from app.hwpx_writer_v2 import HwpxDocument
from app.pdf_layout_writer import _pdf_output_text, write_pdf_structured_hwpx
from app.pdf_native_content import _semantic_line_groups, _source_prose_ink_bounds, extract_native_content
from app.pdf_paragraph_flow import inspect_paragraph_flow
from app.pdf_question_geometry import inspect_question_geometry
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools.package_validator import validate_editor_open_safety

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
SVG = "{http://www.w3.org/2000/svg}"
ADDITION = (" An editable continuation adds enough ordinary prose to grow this same paragraph."
            " The original passage and its answer blank remain editable after saving." * 3
            + " PROSE_INK_EDIT_END")


def compact(value):
    return re.sub(r"\s+", "", _pdf_output_text(value))


def line(text, top, *, right=300, trailing=0, left=50):
    width = (right - left) / len(text)
    chars = [{"c": c, "bbox": [left + i * width, top, left + (i + 1) * width, top + 10]}
             for i, c in enumerate(text)]
    chars += [{"c": " ", "bbox": [right, top, right + trailing, top + 10]}] if trailing else []
    span = {"text": text + (" " if trailing else ""), "bbox": [left, top, right + trailing, top + 10],
            "size": 10, "font": "TimesNewRomanPSMT", "chars": chars}
    return {"bbox": span["bbox"], "spans": [span]}


def verify_guards():
    rows = [line("The first full printed sentence ends.", 100),
            line("Its wrapped continuation includes a blank", 115, trailing=60),
            line("and the source paragraph continues here.", 130)]
    rows[1]["source_answer_blanks"] = [{"bbox_pt": [100, 125, 200, 125]}]
    original = deepcopy(rows)
    assert len(_semantic_line_groups(rows)) == 1
    assert tuple(_source_prose_ink_bounds(rows[1])) == (50, 115, 300, 125)
    assert rows == original, "paragraph geometry changed source text, spaces or answer blank evidence"
    short = [line("A genuine paragraph ends.", 100, right=180), line("The next paragraph starts here.", 115)]
    assert len(_semantic_line_groups(short)) == 2, "a true short final sentence was joined"
    forged = deepcopy(rows)
    forged[1]["spans"][0]["bbox"][2] += 500
    assert _source_prose_ink_bounds(forged[1]).x1 == 860, "unproven bounding box was accepted"
    assert len(_semantic_line_groups(forged)) > 1
    unsupported = deepcopy(rows[1])
    unsupported["spans"][0]["chars"].pop()
    assert _source_prose_ink_bounds(unsupported).x1 == 360, "partial character proof was accepted"
    assert rows == original


def paragraph_text(paragraph):
    return "".join(node.text or "" for node in paragraph.findall(HP + "run/" + HP + "t"))


def state(output, expected):
    with zipfile.ZipFile(output) as archive:
        roots = [etree.fromstring(archive.read(name)) for name in archive.namelist()
                 if re.fullmatch(r"Contents/section\d+\.xml", name)]
        header = etree.fromstring(archive.read("Contents/header.xml"))
    draws = [draw for root in roots for draw in root.iter(HP + "drawText")
             if draw.get("name") == "question:v1:q32"]
    assert len(draws) == 1
    candidates = [p for p in draws[0].iter(HP + "p") if compact(paragraph_text(p)) == compact(expected)]
    assert len(candidates) == 1, "complete Q32 source must remain one native paragraph"
    p = candidates[0]
    assert not p.findall(".//" + HP + "lineBreak"), "visual wraps became explicit text breaks"
    geometry = inspect_question_geometry(draws[0])
    assert geometry["ok"], geometry
    style_ids = [node.get("id") for node in header.iter(HH + "charPr")]
    assert len(style_ids) == len(set(style_ids)), "duplicate character style IDs"
    underlined = []
    styles = {node.get("id"): node for node in header.iter(HH + "charPr")}
    for run in p.findall(HP + "run"):
        value = "".join(node.text or "" for node in run.findall(HP + "t"))
        underline = styles[run.get("charPrIDRef")].find(HH + "underline")
        if value and not value.strip() and underline is not None and underline.get("type") == "BOTTOM":
            underlined.append((value, run.get("charPrIDRef")))
    assert len(underlined) == 1, "source answer blank was removed or duplicated"
    return draws[0], p, geometry, underlined


def painted(output, expected):
    parsed = rhwp.parse(str(output))
    values = []
    for index in range(parsed.page_count):
        root = etree.fromstring(parsed.render_svg(index).encode())
        values.extend("".join(node.itertext()) for node in root.iter(SVG + "text")
                      if not any(parent.tag == SVG + "defs" for parent in node.iterancestors()))
    assert compact("".join(values)).count(compact(expected)) == 1, "complete native text was not painted exactly once"
    return parsed.page_count


def verify_real(source, folder, existing=None):
    # The complete printed Q32 body is measured independently of writer groups.
    # Its trailing blank-space span genuinely extends to x815.475pt.
    bounds = fitz.Rect(429, 655, 817, 967)
    with fitz.open(source) as pdf:
        raw_rows = {}
        for block in pdf[4].get_text("rawdict")["blocks"]:
            for row in block.get("lines", []):
                if bounds.contains(fitz.Rect(row["bbox"])):
                    for span in row["spans"]:
                        raw_rows.setdefault(round(span["origin"][1], 1), []).append(span)
        actual_rows = [sorted(spans, key=lambda span: span["bbox"][0])
                       for _, spans in sorted(raw_rows.items())]
        source_text = " ".join("".join(char["c"] for span in spans for char in span["chars"])
                               for spans in actual_rows)
        assert len(actual_rows) == 18 and compact(source_text).startswith("32.Ofthecognitivemotivations")
        assert compact(source_text).endswith("membershipinastablegroup.[3점]")
        source_bbox_right = max(span["bbox"][2] for spans in actual_rows for span in spans)
        source_ink_right = max(char["bbox"][2] for spans in actual_rows for span in spans
                               for char in span["chars"] if char["c"].strip())
        assert source_bbox_right - source_ink_right > 50
    items, _ = extract_native_content(source, area_hint="영어 영역")
    items = [item for item in items if item.get("source_page") == 5
             and "living in the lounge" in item.get("stem", "")]
    assert len(items) == 1, "Q32 source extraction split its prose"
    item = items[0]
    records = item["layout"]["source_typography"]["lines"]
    assert len(records) == 18
    expected = item["stem"]
    assert compact(expected) == compact(source_text), "complete independent Q32 source text was not retained"
    assert "But what is wrong" in expected and len(item["layout"]["source_answer_blanks"]) == 1
    output = existing or folder / "high2-native.hwpx"
    if existing is None:
        write_pdf_structured_hwpx(source, output, native_math=True, variant_policy="all")
    draw, p, before, blanks = state(output, expected)
    assert len(p.findall(HP + "linesegarray/" + HP + "lineseg")) == 18
    flow = inspect_paragraph_flow(source, output)
    assert flow["ok"], flow
    assert validate_editor_open_safety(output).ok
    pages = painted(output, expected)
    public = HwpxDocument.open(output)
    actual = next((section, node) for section in public.sections for node in section.element.iter(HP + "p")
                  if compact(paragraph_text(node)) == compact(expected))
    paragraph = HwpxOxmlParagraph(actual[1], actual[0])
    last = next(run for run in reversed(paragraph.runs) if run.text.strip())
    last.text += ADDITION
    edited = folder / "high2-edited.hwpx"
    public.save_to_path(edited)
    _, ep, after, edited_blanks = state(edited, expected + ADDITION)
    assert after["shape_height"] > before["shape_height"], "editing did not grow the native question container"
    assert edited_blanks == blanks, "editing changed the source answer blank run"
    assert validate_editor_open_safety(edited).ok
    painted(edited, expected + ADDITION)
    reopened = folder / "high2-reopened.hwpx"
    HwpxDocument.open(edited).save_to_path(reopened)
    _, rp, reopened_geometry, reopened_blanks = state(reopened, expected + ADDITION)
    assert etree.tostring(ep) == etree.tostring(rp), "reopen/save changed the semantic paragraph"
    assert reopened_geometry == after and reopened_blanks == blanks
    assert validate_editor_open_safety(reopened).ok
    painted(reopened, expected + ADDITION)
    return {"source_lines": 18, "native_body_paragraphs": 1, "source_wrap_pairs_checked": flow["source_wrap_pairs_checked"],
            "source_bbox_right_pt": source_bbox_right, "source_nonspace_ink_right_pt": source_ink_right,
            "output_pages": pages, "container_height_before": before["shape_height"],
            "container_height_after": after["shape_height"], "source_answer_blanks": len(blanks),
            "output": str(output), "edited": str(edited), "reopened": str(reopened)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--high2-hwpx", type=Path)
    args = parser.parse_args()
    verify_guards()
    source = ROOT / "data/external_exam_qa/2026_september_high2/english.pdf"
    if not source.is_file():
        print("SKIP: NATIVE_PROSE_INK_BOUNDS synthetic guards passed; real high2 September source missing")
        return 2
    folder = (args.output_dir or Path(RUNTIME.name)).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    result = verify_real(source, folder, args.high2_hwpx)
    (folder / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("NATIVE_PROSE_INK_BOUNDS_OK: " + json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
