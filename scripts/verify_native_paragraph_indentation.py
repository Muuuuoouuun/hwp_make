"""Real PDF paragraph indents must survive native text edits and re-saving."""
# ruff: noqa: E402
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = tempfile.TemporaryDirectory(prefix="native_indent_")
os.environ["HWP_MAKE_DATA_DIR"] = runtime.name
import fitz
from lxml import etree
import rhwp
from app.hwpx_writer_v2 import HwpxDocument
from app.pdf_layout_writer import write_pdf_structured_hwpx
from app.pdf_editability import inspect_pdf_editability
from app.pdf_question_rendering import _transform, _multiply, IDENTITY
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools.paragraph_spacing import paragraph_indentation

H = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
S = "{http://www.w3.org/2000/svg}"
LINES = ["The first line introduces the evidence", "and the following lines explain the result",
         "within the same editable paragraph."]
ADDITION = " Further editing must keep the paragraph indentation and preserve every word. " * 2


def line_starts(path, expected, right_edge):
    doc = rhwp.parse(str(path))
    assert doc.page_count == 1
    root = etree.fromstring(doc.render_svg(0).encode())
    tokens = []
    for node in root.iter(S + "text"):
        matrix = IDENTITY
        for ancestor in [*reversed(list(node.iterancestors())), node]:
            matrix = _multiply(matrix, _transform(ancestor.get("transform", "")))
        x, y = float(node.get("x", 0)), float(node.get("y", 0))
        size = float(node.get("font-size", "13"))
        value = "".join(node.itertext())
        painted_width = float(node.get("textLength", size * sum(1 if ord(c) > 255 else .6 for c in value)))
        x, y = matrix[0] * x + matrix[2] * y + matrix[4], matrix[1] * x + matrix[3] * y + matrix[5]
        tokens.extend((char, x, y, x + abs(matrix[0]) * painted_width) for char in value if not char.isspace())
    compact = "".join(t[0] for t in tokens)
    expected = re.sub(r"\s+", "", expected)
    start = compact.find(expected)
    assert start >= 0, "the edited paragraph is missing from the actual renderer"
    lines = []
    for _, x, y, right in tokens[start:start + len(expected)]:
        assert right <= right_edge + 1, "edited text crosses its column boundary"
        if not lines or abs(y - lines[-1][1]) > .5:
            lines.append((x, y))
    return lines


def verify(folder, shared, hanging):
    name = ("shared" if shared else "question") + ("_hanging" if hanging else "_first")
    source, output = folder / f"{name}.pdf", folder / f"{name}.hwpx"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((150, 38), "Paragraph formatting")
    if shared:
        page.insert_text((40, 85), "[1 ~ 2] Read the passage.", fontsize=10)
    lines = LINES.copy()
    if not shared:
        lines[0] = "1. " + lines[0]
    for index, (baseline, text) in enumerate(zip((115, 130, 145), lines)):
        inset = 12 if (index > 0 if hanging else index == 0) else 0
        page.insert_text((40 + inset, baseline), text, fontsize=10)
    if shared:
        page.insert_text((40, 370), "1. Explain the result.", fontsize=10)
    page.insert_text((315, 85), "2. Retain the complete explanation.", fontsize=10)
    doc.save(source)
    stats = write_pdf_structured_hwpx(source, output, native_math=True)
    audit = inspect_pdf_editability(source, output, stats["image_provenance"], require_question_boxes=True)
    assert audit["ok"], audit["issues"]
    document = HwpxDocument.open(output)
    expected = " ".join(lines)
    section, node = next((s, p) for s in document.sections for p in s.element.iter(H + "p")
                         if "".join(t.text or "" for t in p.findall(H + "run/" + H + "t")) == expected)
    styles = {p.get("id"): p for p in document.headers[0].element.iter(HH + "paraPr")}
    left, right, indent = paragraph_indentation(node, styles)
    expected_indent = (-1 if hanging else 1) * 12 * 59528 / 595
    assert abs(indent - expected_indent) < 2, (name, left, right, indent)
    page_props = section.element.find(".//" + H + "pagePr")
    margins = page_props.find(H + "margin")
    columns = next(c for c in section.element.iter(H + "colPr") if c.get("colCount") == "2")
    right_edge = (float(page_props.get("width")) + float(margins.get("left"))
                  - float(margins.get("right")) - float(columns.get("sameGap"))) / 150
    starts = line_starts(output, expected, right_edge)
    assert len(starts) == 3
    assert abs((starts[0][0] - starts[1][0]) - expected_indent / 75) < .6, starts
    public = HwpxOxmlParagraph(node, section)
    count = sum(len(list(s.element.iter(H + "p"))) for s in document.sections)
    public.text += ADDITION
    edited = folder / f"{name}_edited.hwpx"
    document.save_to_path(edited)
    starts = line_starts(edited, expected + ADDITION, right_edge)
    assert len(starts) > 3
    assert abs((starts[0][0] - starts[1][0]) - expected_indent / 75) < .6, starts
    assert count == sum(len(list(s.element.iter(H + "p"))) for s in document.sections)
    assert paragraph_indentation(node, styles) == (left, right, indent)
    reopened = HwpxDocument.open(edited)
    saved = next(p for s in reopened.sections for p in s.element.iter(H + "p") if p.get("id") == node.get("id"))
    saved_styles = {p.get("id"): p for p in reopened.headers[0].element.iter(HH + "paraPr")}
    assert paragraph_indentation(saved, saved_styles) == (left, right, indent)
    assert not saved.findall(".//" + H + "lineBreak")
    twice = folder / f"{name}_twice.hwpx"
    document.save_to_path(twice)
    with zipfile.ZipFile(edited) as a, zipfile.ZipFile(twice) as b:
        for part in ("Contents/header.xml", "Contents/section0.xml"):
            assert a.read(part) == b.read(part)
    print(f"PASS: {name}: measured 12pt indent, native style, painted line starts after edit, stable re-save")


def main():
    for shared in (False, True):
        for hanging in (False, True):
            verify(Path(runtime.name), shared, hanging)
    print("NATIVE_PARAGRAPH_INDENTATION_OK")


if __name__ == "__main__":
    main()
