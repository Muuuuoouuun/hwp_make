"""Source-confirmed English blanks: native underline, wraps, edits and render."""
from __future__ import annotations

import argparse
from copy import deepcopy
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="english_answer_blanks_")
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import fitz
from lxml import etree
import rhwp
from app.pdf_answer_blanks import measure_answer_blanks, restore_answer_blanks
from app.pdf_layout_writer import _iter_text_lines, write_pdf_structured_hwpx
from app.pdf_native_content import extract_native_content
from app.pdf_source_line_cache import apply_source_line_cache
from app.hwpx_writer_v2 import HwpxDocument
from hwpx.oxml import HwpxOxmlParagraph

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
SVG = "{http://www.w3.org/2000/svg}"


def compact(text):
    return re.sub(r"\s+", "", text)


def painted_controls():
    for label in ("visible", "white_mask_above", "white_stroke", "transparent",
                  "faint", "covered", "partially_covered", "frame"):
        with fitz.open() as document:
            page = document.new_page(width=595, height=842)
            page.insert_text((50, 100), "A complete sentence                     follows.", fontsize=10)
            color = (1, 1, 1) if label == "white_stroke" else (0, 0, 0)
            opacity = 0 if label == "transparent" else .001 if label == "faint" else 1
            page.draw_line((151, 102), (190, 102), color=color, width=.5,
                           stroke_opacity=opacity)
            if label == "white_mask_above":
                page.draw_rect(fitz.Rect(189.5, 92, 190, 101.5), color=None, fill=(1, 1, 1))
            elif label == "covered":
                page.draw_rect(fitz.Rect(150.5, 92, 190.5, 103), color=None, fill=(1, 1, 1))
            elif label == "partially_covered":
                page.draw_rect(fitz.Rect(165, 100, 175, 104), color=None, fill=(1, 1, 1))
            elif label == "frame":
                page.draw_rect(fitz.Rect(151, 92, 190, 102), color=(0, 0, 0),
                               fill=(1, 1, 1), width=.5)
            blanks = measure_answer_blanks(page, _iter_text_lines(page), area_hint="영어 영역")
            assert len(blanks) == (1 if label in {"visible", "white_mask_above"} else 0), (label, blanks)


def synthetic():
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((50, 100), "A complete sentence                     follows.", fontsize=10)
    page.draw_line((151, 102), (190, 102), width=.5)
    page.insert_text((50, 125), "                       .", fontsize=10)
    page.draw_line((50, 127), (108, 127), width=.5)
    # Ordinary underlined words, grid edges and isolated diagram labels.
    page.insert_text((50, 160), "These underlined words remain words.", fontsize=10)
    page.draw_line((50, 162), (199, 162), width=.5)
    page.insert_text((50, 200), "A", fontsize=10)
    page.draw_line((65, 202), (180, 202), width=.5)
    page.insert_text((50, 240), "Table header                           .", fontsize=10)
    page.draw_rect(fitz.Rect(45, 230, 250, 242), width=.5)
    page.draw_line((150, 242), (250, 242), width=.5)
    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 210, 30))
    image.clear_with(255)
    page.insert_image(fitz.Rect(40, 290, 250, 320), pixmap=image)
    page.insert_text((50, 310), "Image leader                           .", fontsize=10)
    page.draw_line((150, 312), (230, 312), width=.5)
    lines = _iter_text_lines(page)
    original = deepcopy(lines)
    blanks = measure_answer_blanks(page, lines, area_hint="영어 영역")
    assert len(blanks) == 2, blanks
    assert not measure_answer_blanks(page, lines, area_hint="수학 영역")
    assert str(lines) == str(original), "blank measurement rewrote source characters"
    records = []
    for line in lines[:2]:
        records.append({"text": "".join(s["text"] for s in line["spans"]).strip(),
                        "bbox_pt": list(line["bbox"]), "baseline_pt": line["spans"][0]["origin"][1],
                        "spans": line["spans"]})
    paragraph = etree.Element(HP+"p")
    run = etree.SubElement(paragraph, HP+"run", charPrIDRef="0")
    etree.SubElement(run, HP+"t").text = " ".join(r["text"] for r in records)
    before = compact("".join(paragraph.itertext()))
    layout = {"source_page_width_pt": 595, "native_page_width": 59500,
              "column_left_pt": 50, "source_answer_blanks": blanks,
              "source_typography": {"font_size_pt": 10, "lines": records}}
    created = {}

    def style(base, height, *, underline=False):
        identifier = str(len(created)+1)
        created[identifier] = (height, underline)
        return identifier

    assert restore_answer_blanks(paragraph, layout, 59500, blank_style=style) == 2
    assert compact("".join(paragraph.itertext())) == before, "blank added or removed words"
    assert not list(paragraph.iter(HP+"line")) and not list(paragraph.iter(HP+"pic"))
    assert sum(underline for _,underline in created.values()) == 2
    assert apply_source_line_cache(paragraph, layout, 30000), "source wrap cache rejected measured blanks"
    last = paragraph.findall(HP+"linesegarray/"+HP+"lineseg")[-1]
    prefix = "".join(t.text or "" for r in paragraph.findall(HP+"run")
                     for t in r.findall(HP+"t"))
    assert prefix[int(last.get("textpos"))].isspace(), "leading rule was excluded from its source line"
    document.close()


def package(path):
    with zipfile.ZipFile(path) as archive:
        header = etree.fromstring(archive.read("Contents/header.xml"))
        roots = [etree.fromstring(archive.read(name)) for name in archive.namelist()
                 if re.fullmatch(r"Contents/section\d+\.xml", name)]
    styles = {node.get("id"): node for node in header.iter(HH+"charPr")}
    return roots, styles


def blank_runs(path):
    roots, styles = package(path)
    result = []
    for root in roots:
        for run in root.iter(HP+"run"):
            text = "".join(t.text or "" for t in run.findall(HP+"t"))
            style = styles.get(run.get("charPrIDRef"))
            underline = style.find(HH+"underline") if style is not None else None
            if text and not text.strip() and underline is not None and underline.get("type") == "BOTTOM":
                assert underline.get("shape") == "SOLID"
                assert not list(run.iter(HP+"pic")) and not list(run.iter(HP+"line"))
                width = len(text)*float(style.get("height"))*.5/75
                result.append((run, width))
    return result


def painted_rules(render, page):
    svg = etree.fromstring(render.render_svg(page).encode())
    width = float(svg.get("width"))
    height = float(svg.get("height"))
    result = []
    for line in svg.iter(SVG+"line"):
        x0,y0,x1,y1 = [float(line.get(key, 0)) for key in ("x1", "y1", "x2", "y2")]
        if abs(y0-y1) < .01 and 20 < abs(x1-x0) < width*.45:
            assert 0 <= min(x0,x1) < max(x0,x1) <= width, "answer rule outside rendered page"
            assert 0 <= y0 <= height
            result.append((abs(x1-x0), min(x0,x1), y0))
    return result


def verify_real(source, output, expected, folder):
    items, _ = extract_native_content(source, area_hint="영어 영역")
    measured = [(item["source_page"]-1, blank) for item in items
                for blank in item["layout"].get("source_answer_blanks", [])]
    assert len(measured) == expected, f"{source.name}: measured {len(measured)}, expected {expected}"
    if output is None:
        output = folder/(source.stem+"-blanks.hwpx")
        write_pdf_structured_hwpx(source, output, native_math=True)
    runs = blank_runs(output)
    assert len(runs) == expected, f"native blank run count {len(runs)} != {expected}"
    render = rhwp.parse(str(output))
    errors = []
    native_widths = [width for _,width in runs]
    with fitz.open(source) as document:
        for page_index in sorted({page for page,_ in measured}):
            rules = painted_rules(render, page_index)
            native_width = float(etree.fromstring(render.render_svg(page_index).encode()).get("width"))
            scale = native_width/document[page_index].rect.width
            available = list(rules)
            for page,blank in measured:
                if page != page_index:
                    continue
                target = (blank["bbox_pt"][2]-blank["bbox_pt"][0])*scale
                native = next((width for width in native_widths if abs(width-target) < .3), None)
                assert native is not None, f"stored native rule length differs from source: {target:.3f}"
                native_widths.remove(native)
                # The reader can compress a complete line to its available
                # width when surrounding font advances differ from the PDF.
                # Stored rule geometry is exact; separately bound and report
                # this reader adjustment instead of concealing it.
                match = next((rule for rule in available if abs(rule[0]-target) < max(1, target*.05)), None)
                assert match is not None, f"page {page_index+1}: missing visible source-length rule {target:.3f}, got {rules}"
                errors.append(abs(match[0]-target))
                available.remove(match)
    print(f"{source.name}: {expected} stored source lengths within .3px; max reader width adjustment {max(errors):.3f}px")
    return output


def verify_edit(output, folder):
    document = HwpxDocument.open(output)
    selected = None
    for section in document.sections:
        for draw in section.element.iter(HP+"drawText"):
            if draw.get("name") == "question:v1:q33":
                for node in draw.iter(HP+"p"):
                    if "Talking about" in "".join(t.text or "" for t in node.iter(HP+"t")):
                        selected = HwpxOxmlParagraph(node, section)
                        break
        if selected is not None:
            break
    assert selected is not None
    before = sorted(round(width, 2) for _,width in blank_runs(output))
    first = next(run for run in selected.runs if run.text.strip())
    first.text += " The added observation helps readers compare these familiar experiences clearly."
    edited = folder/"blanks-edited.hwpx"
    document.save_to_path(edited)
    after = sorted(round(width, 2) for _,width in blank_runs(edited))
    assert before == after, "editing changed or removed measured native blank widths"
    render = rhwp.parse(str(edited))
    visible = []
    text = ""
    for page in range(render.page_count):
        visible += [width for width,_,_ in painted_rules(render, page)]
        svg = etree.fromstring(render.render_svg(page).encode())
        text += "".join("".join(node.itertext()) for node in svg.iter(SVG+"text"))
    assert compact("The added observation helps readers") in compact(text), "edited prose is not painted"
    for width in after:
        match = next((candidate for candidate in visible if abs(candidate-width) < max(1,width*.05)), None)
        assert match is not None, f"editing split or hid a native answer rule of width {width}"
        visible.remove(match)
    def first_anchor(path):
        reader = rhwp.parse(str(path))
        for page in range(reader.page_count):
            svg = etree.fromstring(reader.render_svg(page).encode())
            chars, anchors = [], []
            for node in svg.iter(SVG+"text"):
                value = compact("".join(node.itertext()))
                chars.extend(value)
                anchors.extend([(float(node.get("x", 0)), float(node.get("y", 0)))]*len(value))
            index = "".join(chars).find("33.Talkingabout")
            if index >= 0:
                return page, anchors[index]
        raise AssertionError("edited Q33 first line is not painted")
    old_page, old_anchor = first_anchor(output)
    new_page, new_anchor = first_anchor(edited)
    assert old_page == new_page and abs(old_anchor[0]-new_anchor[0]) < 1, "editing displaced Q33's first line from its normal rail"
    from app.pdf_question_geometry import inspect_question_geometry
    roots, _ = package(edited)
    for root in roots:
        for draw in root.iter(HP+"drawText"):
            if draw.get("name", "").startswith("question:"):
                assert inspect_question_geometry(draw)["ok"], "edited question exceeds its native container"
    reopened = folder/"blanks-edited-reopened.hwpx"
    HwpxDocument.open(edited).save_to_path(reopened)
    assert sorted(round(width, 2) for _,width in blank_runs(reopened)) == before


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--high1-hwpx", type=Path)
    parser.add_argument("--csat-hwpx", type=Path)
    args = parser.parse_args()
    painted_controls()
    synthetic()
    print("PASS: actual painted/covered/faint line controls, synthetic positions, native whitespace/cache, underline/grid/diagram negatives")
    if not args.synthetic_only:
        high1 = ROOT/"data/external_exam_qa/2026_june_high1/english.pdf"
        csat = ROOT/"data/external_exam_qa/2026_csat/문제지/영어/영어.pdf"
        if not high1.is_file() or not csat.is_file():
            print("MISSING_SOURCE: both real English PDFs are required")
            return 2
        folder = Path(RUNTIME.name)
        high1_output = verify_real(high1, args.high1_hwpx, 7, folder)
        verify_real(csat, args.csat_hwpx, 8, folder)
        verify_edit(high1_output, folder)
        print("PASS: high1 Q13/14/15/31–34, CSAT Q31–34 both forms, exact widths and edited native render")
    print("NATIVE_ENGLISH_ANSWER_BLANKS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
