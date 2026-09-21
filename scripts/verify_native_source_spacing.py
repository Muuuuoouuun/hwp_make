"""Measured margins and inter-question gaps survive column/section transitions."""
# ruff: noqa: E402
import os
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = tempfile.TemporaryDirectory(prefix="native_source_spacing_")
os.environ["HWP_MAKE_DATA_DIR"] = runtime.name
import fitz
from lxml import etree
import rhwp
from app.pdf_layout_writer import write_pdf_structured_hwpx
from app.pdf_editability import inspect_pdf_editability
from scripts.verify_native_question_edit_reflow import verify as verify_edit

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
SVG = "{http://www.w3.org/2000/svg}"


def run():
    folder = Path(runtime.name)
    source, target = folder / "source.pdf", folder / "native.hwpx"
    doc = fitz.open()
    for index in range(3):
        page = doc.new_page(width=595, height=842)
        page.insert_text((150, 38), "Flow test")
        for column, left in enumerate((40, 310)):
            for row, top in enumerate((130 if index == 0 else 90, 470)):
                number = index * 4 + column * 2 + row + 1
                page.insert_textbox(fitz.Rect(left, top, left + 235, top + 80),
                    f"{number}. This is a coherent paragraph with several printed lines. "
                    "The answer must preserve the entire paragraph as one editable text block.", fontsize=10)
    doc.save(source)
    stats = write_pdf_structured_hwpx(source, target, native_math=True)
    audit = inspect_pdf_editability(source, target, stats["image_provenance"], require_question_boxes=True)
    assert audit["ok"], audit["issues"]
    assert stats["section_count"] == 2 and stats["section_breaks"] == 1
    assert stats["page_breaks"] == 1 and stats["page_breaks"] + stats["section_breaks"] == stats["expected_page_breaks"] == 2
    with zipfile.ZipFile(target) as package:
        sections = [etree.fromstring(package.read(f"Contents/section{i}.xml")) for i in range(2)]
        manifest = etree.fromstring(package.read("Contents/content.hpf"))
        assert any(n.get("href") == "Contents/section1.xml" for n in manifest.iter())
        scale = float(sections[0].find(".//" + HP + "pagePr").get("width")) / 595 / 75
        for section in sections:
            page_pr = section.find(".//" + HP + "pagePr")
            margin = page_pr.find(HP + "margin")
            col = next(c for c in section.iter(HP + "colPr") if c.get("colCount") == "2")
            left, right, gap = (float(margin.get("left")), float(margin.get("right")), float(col.get("sameGap")))
            width = (float(page_pr.get("width")) - left - right - gap) / 2
            assert abs(left / 75 - 40 * scale) < .02
            assert abs((left + width + gap) / 75 - 310 * scale) < .02
            for draw in section.iter(HP + "drawText"):
                paragraphs = draw.find(HP + "subList").findall(HP + "p")
                assert len(paragraphs) == 1, "one paragraph was split into its printed lines"
                assert len(paragraphs[0].findall(HP + "linesegarray/" + HP + "lineseg")) >= 2
    rendered = rhwp.parse(str(target))
    assert rendered.page_count == 3
    for index in range(3):
        svg = etree.fromstring(rendered.render_svg(index).encode())
        starts = {0: [], 1: []}
        for node in svg.iter(SVG + "text"):
            if not node.text or not node.text.isdigit() or node.get("x") is None:
                continue
            x, y = float(node.get("x")), float(node.get("y"))
            for column, left in enumerate((40, 310)):
                if abs(x - left * scale) < .1:
                    starts[column].append(y)
        assert len(starts[0]) == len(starts[1]) == 2
        assert max(abs(a - b) for a, b in zip(starts[0], starts[1])) < .1, "column switch inserted an empty line"
        if index:
            for ys in starts.values():
                assert abs(ys[1] - ys[0] - 380 * scale) < .1, "native box padding was counted twice"
    for index in range(2):
        edited = folder / f"edit_section_{index}"
        edited.mkdir()
        verify_edit(target, edited, section_index=index)
    print("NATIVE_SOURCE_SPACING_OK: 3 pages, measured rails/gaps, section inventory, paragraph edits in both sections")


if __name__ == "__main__":
    run()
