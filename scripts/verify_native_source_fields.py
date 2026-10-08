"""Actual-source proof for semantic label fields and measured hanging rails."""
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
RUNTIME = tempfile.TemporaryDirectory(prefix="source_fields_")
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name

import fitz
from lxml import etree
import rhwp
from app.hwpx_writer_v2 import HwpxDocument  # initializes the bundled HWPX library
from app.pdf_illustrated_prose_frames import restore_source_field_paragraphs
from app.pdf_native_content import extract_native_content
from hwpx.tools.paragraph_spacing import paragraph_spacing

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"
SVG = "{http://www.w3.org/2000/svg}"
LABEL = re.compile(r"^[A-Z][A-Za-z ]{1,20}:\s*\S")


def compact(value):
    return re.sub(r"\s+", "", value)


def text(paragraph):
    return "".join(t.text or "" for t in paragraph.findall(HP + "run/" + HP + "t"))


def package(path, wanted):
    with zipfile.ZipFile(path) as archive:
        header = etree.fromstring(archive.read("Contents/header.xml"))
        roots = [etree.fromstring(archive.read(name)) for name in archive.namelist()
                 if re.fullmatch(r"Contents/section\d+\.xml", name)]
    tables = [table for root in roots for table in root.iter(HP + "tbl")
              if compact("".join(t.text or "" for t in table.iter(HP + "t"))) == compact(wanted)]
    assert len(tables) == 1, "one complete native frame must match every source character"
    return header, tables[0], float(tables[0].getroottree().getroot().find(".//" + HP + "pagePr").get("width"))


def styles(header):
    return {p.get("id"): p for p in header.iter(HH + "paraPr")}


def flow(paragraphs, header):
    return sum(sum(float(line.get("vertsize")) + float(line.get("spacing"))
                   for line in p.findall(HP + "linesegarray/" + HP + "lineseg"))
               + sum(paragraph_spacing(p, styles(header))) for p in paragraphs)


def inventory(paragraphs):
    return [(char, tuple(sorted(run.attrib.items()))) for p in paragraphs for run in p.findall(HP + "run")
            for char in "".join(t.text or "" for t in run.findall(HP + "t"))]


def candidate(table):
    matches = [p for p in table.iter(HP + "p") if LABEL.match(text(p))
               and len(p.findall(HP + "linesegarray/" + HP + "lineseg")) > 2]
    assert len(matches) == 1
    return matches[0]


def source_rows(source, frame_text, layout):
    # Independent raw PDF extraction, without the producer's grouping helper.
    box = fitz.Rect(layout["native_tables"][0]["bbox_pt"])
    with fitz.open(source) as pdf:
        found = []
        for page in pdf:
            records = []
            for block in page.get_text("rawdict")["blocks"]:
                for line in block.get("lines", []):
                    if box.contains(fitz.Rect(line["bbox"])):
                        chars = [c for s in line["spans"] for c in s["chars"]]
                        records.append(("".join(c["c"] for c in chars), chars))
            records.sort(key=lambda r: (r[1][0]["origin"][1], r[1][0]["origin"][0]))
            if compact("".join(r[0] for r in records)) == compact(frame_text):
                found.append((page.number, records))
    assert len(found) == 1
    return found[0]


def verify(source, baseline, product):
    items, _ = extract_native_content(source, area_hint="영어 영역")
    layouts = [item["layout"] for item in items if len(item.get("layout", {}).get("native_tables", [])) == 1
               and item["layout"]["native_tables"][0].get("source_prose_frame")
               and len(item["layout"]["native_tables"][0].get("images", [])) == 2]
    assert len(layouts) == 1
    layout = layouts[0]
    frame_text = layout["native_tables"][0]["source_frame_text"]
    header, table, width = package(baseline, frame_text)
    original = candidate(table)
    original_value = text(original)
    page, raw = source_rows(source, frame_text, layout)
    start = next(i for i, r in enumerate(raw) if LABEL.match(r[0].strip()))
    end, joined = start, ""
    while len(joined) < len(compact(original_value)):
        joined += compact(raw[end][0]); end += 1
    field_rows = raw[start:end]
    assert joined == compact(original_value) and len(field_rows) == 5
    first_inks = [next(c for c in chars if c["c"].strip())["origin"] for _, chars in field_rows]
    assert field_rows[1][0].startswith("  ") and not LABEL.match(field_rows[1][0].strip())
    indent = first_inks[1][0] - first_inks[0][0]
    old_flow, old_inventory = flow([original], header), inventory([original])

    changed, changed_header = deepcopy(table), deepcopy(header)
    old_style_refs = list(changed_header.find(".//" + HH + "paraProperties"))
    old_style_bytes = [etree.tostring(p) for p in old_style_refs]
    assert restore_source_field_paragraphs(changed, layout, changed_header, width) == 1
    parts = [p for p in changed.iter(HP + "p") if text(p)]
    field_start = next(i for i, p in enumerate(parts) if LABEL.match(text(p)))
    fields = parts[field_start:field_start + 4]
    assert [len(p.findall(HP + "linesegarray/" + HP + "lineseg")) for p in fields] == [2, 1, 1, 1]
    assert "".join(text(p) for p in fields) == original_value
    assert inventory(fields) == old_inventory
    assert abs(flow(fields, changed_header) - old_flow) <= 1
    assert all(ref is list(changed_header.find(".//" + HH + "paraProperties"))[i]
               and etree.tostring(ref) == old_style_bytes[i] for i, ref in enumerate(old_style_refs))
    snapshot = (etree.tostring(changed), etree.tostring(changed_header))
    assert restore_source_field_paragraphs(changed, layout, changed_header, width) == 0
    assert snapshot == (etree.tostring(changed), etree.tostring(changed_header))

    own_start = next(i for i, r in enumerate(layout["source_typography"]["lines"])
                     if compact(r["text"]) == compact(field_rows[0][0]))
    cases = ("literal_false", "body", "answer_blank", "native_blank", "equation", "equation_font",
             "missing_raw", "raw_shape", "origin_shape", "span_nan", "record_nan", "prefix_tab", "internal_spaces", "trailing_spaces",
             "partial_text", "width_nan", "height_nan", "page_nan", "source_width_nan",
             "textpos_nan", "textpos_order", "oversized_cache", "left", "intent", "horzpos", "negative_horzpos")
    for case in cases:
        native, head, meta, page_width = deepcopy(table), deepcopy(header), deepcopy(layout), width
        p = candidate(native)
        row = meta["source_typography"]["lines"][own_start + 1]
        span = row["spans"][0]
        line = p.find(HP + "linesegarray/" + HP + "lineseg")
        style = styles(head)[p.get("paraPrIDRef")]
        if case == "literal_false": meta["source_literal_text"] = False
        elif case == "body": meta["native_tables"][0]["source_prose_frame"] = False
        elif case == "answer_blank": meta["source_answer_blanks"] = [{"bbox_pt": [1, 2, 3, 2]}]
        elif case == "native_blank":
            char = deepcopy(next(head.iter(HH + "charPr"))); char.set("id", "99999")
            underline = char.find(HH + "underline")
            if underline is None: underline = etree.SubElement(char, HH + "underline")
            underline.set("type", "BOTTOM"); next(head.iter(HH + "charProperties")).append(char)
            run = etree.SubElement(p, HP + "run", charPrIDRef="99999"); etree.SubElement(run, HP + "t").text = " "
        elif case == "equation": etree.SubElement(p.find(HP + "run"), HP + "equation")
        elif case == "equation_font": span["font"] = "HancomEQN"
        elif case == "missing_raw": span.pop("chars")
        elif case == "raw_shape": span["chars"][0]["bbox"] = [1, 2, 3]
        elif case == "origin_shape": span["chars"][0]["origin"] = [1]
        elif case == "span_nan": span["bbox"] = [float("nan"), *span["bbox"][1:]]
        elif case == "record_nan": row["bbox_pt"] = [float("nan"), *row["bbox_pt"][1:]]
        elif case == "prefix_tab": span["chars"][0]["c"] = "\t"; span["text"] = "\t" + span["text"][1:]
        elif case in ("internal_spaces", "trailing_spaces"):
            if case == "internal_spaces":
                index = next(i for i, c in enumerate(span["chars"]) if c["c"] == " " and i > 8)
            else:
                index = len(span["chars"])
            space = deepcopy(span["chars"][0]); space["c"] = " "
            span["chars"][index:index] = [deepcopy(space), deepcopy(space), deepcopy(space)]
            span["text"] = "".join(c["c"] for c in span["chars"])
        elif case == "partial_text": next(p.iter(HP + "t")).text = "Incomplete source"
        elif case in ("width_nan", "height_nan"): native.find(HP + "sz").set(case.split("_")[0], "nan")
        elif case == "page_nan": page_width = float("nan")
        elif case == "source_width_nan": meta["source_page_width_pt"] = float("nan")
        elif case == "textpos_nan": line.set("textpos", "nan")
        elif case == "textpos_order": p.findall(HP + "linesegarray/" + HP + "lineseg")[1].set("textpos", "0")
        elif case == "oversized_cache": line.set("vertsize", "200000"); line.set("textheight", "200000")
        elif case in ("left", "intent"): style.find(".//" + HC + case).set("value", "10")
        elif case in ("horzpos", "negative_horzpos"): line.set("horzpos", "10" if case == "horzpos" else "-10")
        before = (etree.tostring(native), etree.tostring(head), repr(meta))
        assert restore_source_field_paragraphs(native, meta, head, page_width) == 0, case
        assert before == (etree.tostring(native), etree.tostring(head), repr(meta)), case

    # A supplementary code point has one Python character and two UTF-16
    # units. Keep the actual fixture's raw geometry and replace one value
    # character so source and native inventories remain exact.
    unicode_table, unicode_header, unicode_layout = deepcopy(table), deepcopy(header), deepcopy(layout)
    unicode_p = candidate(unicode_table)
    old_value = text(unicode_p)
    replace_at = next(i for i in range(old_value.index(":") + 1, len(old_value)) if not old_value[i].isspace())
    old_char, consumed = old_value[replace_at], 0
    for run in unicode_p.findall(HP + "run"):
        for node in run.findall(HP + "t"):
            value = node.text or ""
            if consumed <= replace_at < consumed + len(value):
                index = replace_at - consumed
                node.text = value[:index] + "😀" + value[index + 1:]
            consumed += len(value)
    raw_record = unicode_layout["source_typography"]["lines"][own_start]
    raw_value = "".join(s["text"] for s in raw_record["spans"])
    source_at = next(i for i in range(raw_value.index(":") + 1, len(raw_value)) if not raw_value[i].isspace())
    assert raw_value[source_at] == old_char
    chars = [c for s in raw_record["spans"] for c in s["chars"]]
    chars[source_at]["c"] = "😀"
    for span in raw_record["spans"]: span["text"] = "".join(c["c"] for c in span["chars"])
    raw_record["text"] = raw_record["text"].replace(raw_value.strip(),
        (raw_value[:source_at] + "😀" + raw_value[source_at + 1:]).strip(), 1)
    unicode_layout["native_tables"][0]["source_frame_text"] = "".join(
        r["text"] for r in unicode_layout["source_typography"]["lines"])
    for line in unicode_p.findall(HP + "linesegarray/" + HP + "lineseg")[1:]:
        line.set("textpos", str(int(line.get("textpos")) + 1))
    assert restore_source_field_paragraphs(unicode_table, unicode_layout, unicode_header, width) == 1
    assert "😀" in "".join(t.text or "" for t in unicode_table.iter(HP + "t"))

    # Before/after distances are genuine paragraph flow, including nonzero
    # values. They must be carried through the field split exactly.
    spacing_table, spacing_header = deepcopy(table), deepcopy(header)
    spacing_p = candidate(spacing_table)
    spacing_style = styles(spacing_header)[spacing_p.get("paraPrIDRef")]
    for margin in spacing_style.findall(".//" + HH + "margin"):
        margin.find(HC + "prev").set("value", "137")
    spacing_flow = flow([spacing_p], spacing_header)
    assert restore_source_field_paragraphs(spacing_table, layout, spacing_header, width) == 1
    spacing_parts = [p for p in spacing_table.iter(HP + "p") if text(p)]
    spacing_start = next(i for i, p in enumerate(spacing_parts) if LABEL.match(text(p)))
    assert flow(spacing_parts[spacing_start:spacing_start + 4], spacing_header) == spacing_flow

    product_header, product_table, product_width = package(product, frame_text)
    product_parts = [p for p in product_table.iter(HP + "p") if text(p)]
    product_start = next(i for i, p in enumerate(product_parts) if LABEL.match(text(p)))
    selected = product_parts[product_start:product_start + 4]
    assert inventory(selected) == old_inventory and flow(selected, product_header) == old_flow
    assert [len(p.findall(HP + "linesegarray/" + HP + "lineseg")) for p in selected] == [2, 1, 1, 1]
    original_svg, actual_svg = rhwp.parse(str(baseline)), rhwp.parse(str(product))
    assert original_svg.page_count == actual_svg.page_count == 8
    def glyphs(document):
        svg = etree.fromstring(document.render_svg(page).encode())
        values = [(c, float(n.get("x")), float(n.get("y"))) for n in svg.iter(SVG + "text")
                  if n.get("x") and n.get("y") and not any(a.tag == SVG + "defs" for a in n.iterancestors())
                  for c in compact("".join(n.itertext()))]
        joined = "".join(c for c, _, _ in values)
        assert joined.count(compact(original_value)) == 1
        start = joined.index(compact(original_value))
        values = values[start:start + len(compact(original_value))]
        result, cursor = [], 0
        for value, _ in field_rows:
            result.append(values[cursor][1:]); cursor += len(compact(value))
        return result
    before_xy, after_xy = glyphs(original_svg), glyphs(actual_svg)
    assert all(abs(a[1] - b[1]) < .05 for a, b in zip(before_xy, after_xy))
    scale = product_width / layout["source_page_width_pt"] / 75
    assert abs(after_xy[1][0] - after_xy[0][0] - indent * scale) < .02
    assert all(abs(after_xy[i][0] - before_xy[i][0]) < .02 for i in (0, 2, 3, 4))
    return {"source": str(source), "source_rows": len(raw), "semantic_cache_rows": [2, 1, 1, 1],
            "negative_cases": list(cases), "native_text_and_run_styles_exact": True,
            "existing_style_objects_unchanged": True, "idempotent": True,
            "utf16_supplementary_character": True, "nonzero_before_preserved": True,
            "flow_hwp_before": old_flow, "flow_hwp_after": flow(selected, product_header),
            "pages": actual_svg.page_count, "actual_five_first_inks_px": after_xy,
            "source_continuation_advance_px": indent * scale}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/external_exam_qa/2026_september_high2/english.pdf")
    parser.add_argument("--baseline", type=Path, default=ROOT / "tmp/september-exam-matrix/high2-illustrated-native.hwpx")
    parser.add_argument("--hwpx", type=Path, default=ROOT / "tmp/september-exam-matrix/field-product/high2-native.hwpx")
    parser.add_argument("--report", type=Path, default=ROOT / "tmp/september-exam-matrix/field-product/source-fields-report.json")
    args = parser.parse_args()
    missing = [str(p) for p in (args.source, args.baseline, args.hwpx) if not p.is_file()]
    if missing:
        print("SOURCE_FIELDS_SKIP missing=" + json.dumps(missing, ensure_ascii=False)); return 2
    report = verify(args.source, args.baseline, args.hwpx)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SOURCE_FIELDS_OK " + json.dumps(report, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
