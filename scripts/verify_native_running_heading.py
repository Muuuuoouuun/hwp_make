"""Repeated source heading is a native header and does not displace body text."""
# ruff: noqa: E402
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runtime = tempfile.TemporaryDirectory(prefix="native_running_heading_")
os.environ["HWP_MAKE_DATA_DIR"] = runtime.name
import fitz
from lxml import etree
import rhwp
from app.pdf_native_content import extract_native_content
from app.pdf_layout_writer import write_pdf_structured_hwpx
from app.pdf_running_headings import apply_running_heading, measure_running_heading
from scripts.verify_native_question_edit_reflow import verify as verify_edit

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
SVG = "{http://www.w3.org/2000/svg}"


def run():
    folder = Path(runtime.name)
    source, output = folder / "source.pdf", folder / "native.hwpx"
    pdf = fitz.open()
    font = fitz.Font("korea")
    subject = "국어영역"
    for index in range(3):
        page = pdf.new_page(width=595, height=842)
        if not index:
            page.insert_text((120, 60), "2026학년도 시험 문제지", fontname="korea", fontsize=19)
        size = 30 if not index else 24
        y = 110 if not index else 75
        page.insert_text(((595-font.text_length(subject, fontsize=size))/2, y), subject, fontname="korea", fontsize=size)
        for column, x in enumerate((40, 310)):
            page.insert_textbox(fitz.Rect(x, 210 if not index else 135, x+235, 410),
                f"{index*2+column+1}. Read this entire paragraph before answering the question. "
                "The second sentence belongs to the same paragraph and must remain editable.", fontsize=10)
    pdf.save(source)
    items, _ = extract_native_content(source)
    records = items[0]["layout"]["source_running_headings"]
    assert len(records) == 2 and [r["page"] for r in records] == [2, 3]
    from types import SimpleNamespace
    span = {"text": subject, "font": "Test", "size": 24, "flags": 0, "bbox": [250, 45, 345, 78]}
    mixed = {"blocks": [{"lines": [{"bbox": [40, 40, 550, 80], "spans": [
        {**span, "text": "2           ", "bbox": [40, 40, 230, 80]}, span,
        {**span, "text": "       ", "bbox": [345, 40, 550, 80]}]}]}]}
    measured = measure_running_heading(SimpleNamespace(get_text=lambda _: mixed, rect=fitz.Rect(0, 0, 595, 842), number=1), 120, subject)
    assert measured["bbox_pt"] == span["bbox"] and measured["spans"][0]["text"] == subject
    stats = write_pdf_structured_hwpx(source, output, native_math=True)
    assert stats["running_heading"]["applied"] and stats["running_heading"]["source_pages"] == 2
    before = output.read_bytes()
    assert not apply_running_heading(output, records[:1], 3)["applied"]
    assert output.read_bytes() == before, "incomplete source evidence must not introduce a repeated header"
    with zipfile.ZipFile(output) as package:
        section = etree.fromstring(package.read("Contents/section1.xml"))
        margin = section.find(".//" + HP + "pagePr/" + HP + "margin")
        body_top = int(margin.get("top")) + int(margin.get("header"))
        assert body_top == stats["running_heading"]["body_top_hwp"]
        assert section.find(f"./{HP}p/{HP}run/{HP}ctrl/{HP}header") is not None
    document = rhwp.parse(str(output))
    assert document.page_count == 3
    positions = []
    for index in (1, 2):
        svg = etree.fromstring(document.render_svg(index).encode())
        nodes = list(svg.iter(SVG + "text"))
        text = re.sub(r"\s+", "", "".join("".join(n.itertext()) for n in nodes))
        assert text.count(subject) == 1, "native repeated header absent or duplicated"
        starts = [(float(n.get("x")), float(n.get("y"))) for n in nodes
                  if n.text == str(index*2+1) and n.get("x") is not None]
        assert len(starts) == 1
        assert abs(starts[0][1] - body_top/75 - 11.34) < .5, "header displaced existing body"
        positions.append(starts[0][1])
    assert abs(positions[0]-positions[1]) < .1
    edit = folder / "edited"
    edit.mkdir()
    verify_edit(output, edit, section_index=1)
    print("NATIVE_RUNNING_HEADING_OK: source evidence, visible repeated header, fixed body origin, paragraph editing")


if __name__ == "__main__":
    run()
