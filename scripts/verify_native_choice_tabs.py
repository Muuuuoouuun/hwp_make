"""Real PDF choices retain native tab stops and reflow as one editable paragraph."""
# ruff: noqa: E402
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = tempfile.TemporaryDirectory(prefix="native_choice_tabs_")
if __name__ == "__main__":
    os.environ["HWP_MAKE_DATA_DIR"] = runtime.name
import fitz
from lxml import etree
import rhwp
from app.hwpx_writer_v2 import HwpxDocument
from app.pdf_layout_writer import write_pdf_structured_hwpx
from app.pdf_editability import inspect_pdf_editability
from app.pdf_question_rendering import _transform, _multiply, IDENTITY
from hwpx.oxml import HwpxOxmlParagraph
from hwpx.tools.paragraph_spacing import paragraph_tab_stops
from hwpx.tools.package_validator import validate_editor_open_safety

H = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
S = "{http://www.w3.org/2000/svg}"
MARKERS = "①②③④⑤"


def painted(path):
    document = rhwp.parse(str(path))
    assert document.page_count == 1
    root = etree.fromstring(document.render_svg(0).encode())
    tokens, markers = [], []
    for node in root.iter(S + "text"):
        matrix = IDENTITY
        for ancestor in [*reversed(list(node.iterancestors())), node]:
            matrix = _multiply(matrix, _transform(ancestor.get("transform", "")))
        x, y = float(node.get("x", 0)), float(node.get("y", 0))
        x, y = matrix[0] * x + matrix[2] * y + matrix[4], matrix[1] * x + matrix[3] * y + matrix[5]
        value = "".join(node.itertext())
        if value in MARKERS and value:
            markers.append((value, x, y))
        tokens.extend((c, x, y) for c in value if not c.isspace())
    return tokens, markers


def main():
    folder = Path(runtime.name)
    source, output = folder / "choices.pdf", folder / "choices.hwpx"
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((150, 38), "Native choice spacing")
    page.insert_text((40, 85), "1. Choose the correct value.", fontsize=10)
    font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/batang.ttc"
    if not font.is_file():
        print("SKIP: source/renderer matching Batang fixture font is unavailable")
        raise SystemExit(2)
    page.insert_font(fontname="ChoiceFont", fontfile=str(font))
    starts = (40, 85, 130, 175, 220)
    for index, (label, x) in enumerate(zip(MARKERS, starts)):
        page.insert_text((x, 115), f"{label} {index + 2}", fontsize=10, fontname="ChoiceFont")
    page.insert_text((315, 85), "2. Retain every option.", fontsize=10)
    pdf.save(source)
    stats = write_pdf_structured_hwpx(source, output, native_math=True)
    assert stats['choice_tab_measurement']['measured_rows'] == 1
    audit = inspect_pdf_editability(source, output, stats["image_provenance"], require_question_boxes=True)
    assert audit["ok"], audit["issues"]
    document = HwpxDocument.open(output)
    section, node = next((s, p) for s in document.sections for p in s.element.iter(H + "p")
                         if len(p.findall(H + "run/" + H + "tab")) == 4)
    styles = {p.get("id"): p for p in document.headers[0].element.iter(HH + "paraPr")}
    stops = paragraph_tab_stops(node, styles)
    assert len(stops) == 4
    assert all(abs(a - (b - starts[0]) * 59528 / 595) < 1 for a, b in zip(stops, starts[1:]))
    _, marks = painted(output)
    assert "".join(v[0] for v in marks) == MARKERS
    maximum_position_error = max(abs(v[1] - x * 59528 / 595 / 75) for v, x in zip(marks, starts))
    public = HwpxOxmlParagraph(node, section)
    assert public.text.count("\t") == 4
    count = sum(len(list(s.element.iter(H + "p"))) for s in document.sections)
    public.text = public.text.replace("① 2", "① 22") + " Additional editable explanation remains within this column." * 4
    edited = folder / "choices_edited.hwpx"
    document.save_to_path(edited)
    tokens, marks = painted(edited)
    expected = re.sub(r"\s+", "", public.text)
    visible = "".join(t[0] for t in tokens)
    start = visible.find(expected)
    assert start >= 0, "an option or part of the edited paragraph was not painted"
    assert "".join(v[0] for v in marks) == MARKERS
    assert max(v[1] for v in tokens[start:start + len(expected)]) < 390, "edited text overflowed into column two"
    lines = node.findall(H + "linesegarray/" + H + "lineseg")
    assert len(lines) > 1
    assert not node.findall(".//" + H + "lineBreak")
    assert count == sum(len(list(s.element.iter(H + "p"))) for s in document.sections)
    assert paragraph_tab_stops(node, styles) == stops
    twice = folder / "choices_twice.hwpx"
    document.save_to_path(twice)
    with zipfile.ZipFile(edited) as a, zipfile.ZipFile(twice) as b:
        assert a.read("Contents/header.xml") == b.read("Contents/header.xml")
        assert a.read("Contents/section0.xml") == b.read("Contents/section0.xml")
    corrupted = folder / "choices_invalid_offset.hwpx"
    with zipfile.ZipFile(edited) as original, zipfile.ZipFile(corrupted, "w") as mutant:
        for name in original.namelist():
            payload = original.read(name)
            if name == "Contents/section0.xml":
                section_xml = etree.fromstring(payload)
                bad = next(p for p in section_xml.iter(H + "p") if p.get("id") == node.get("id"))
                bad.findall(H + "linesegarray/" + H + "lineseg")[-1].set("textpos", "100000")
                payload = etree.tostring(section_xml)
            mutant.writestr(name, payload)
    assert not validate_editor_open_safety(corrupted).ok, "invalid text offsets were accepted"
    print("PASS: measured PDF choice gaps, native tab stops, one paragraph after editing, complete painted text within its column, stable re-save")
    assert maximum_position_error < 6, f"choice position error {maximum_position_error:.2f}px exceeds the unchanged 6px limit"
    print(f"NATIVE_CHOICE_TABS_OK: maximum position error {maximum_position_error:.4f}px (unchanged limit: 6px)")


if __name__ == "__main__":
    main()
