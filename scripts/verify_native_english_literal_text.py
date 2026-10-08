"""Source-proven English prose keeps literal characters and ordinary text fonts."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="english_literal_text_")
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import fitz
from lxml import etree
import rhwp
from app.hwpx_writer_v2 import (HwpxDocument, _add_table,
                                _replace_paragraph_runs, write_hwpx)
from app.pdf_layout_writer import is_hancom_eq_font
from app.pdf_native_content import annotate_question_groups, extract_native_content

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
PROSE = [
    "Compare financial(A), memories(a), and financial(A^2).",
    "The prices are $40 and $50, respectively.",
    "Choose (A), (B), or (C); keep CO2 and x2 as English labels.",
    "Options (a) and (b): don't turn (t) into a variable.",
]


def ordinary_text(root):
    return "".join(node.text or "" for node in root.iter(HP + "t"))


def assert_literal_runs(root, expected, body_style):
    assert not list(root.iter(HP + "equation")), "English prose became a native equation"
    assert ordinary_text(root) == expected, (expected, ordinary_text(root))
    assert all(run.get("charPrIDRef") == body_style for run in root.iter(HP + "run")
               if run.find(HP + "t") is not None), "Literal English inherited the math font"


def verify_run_and_table_helpers():
    for native_math in (False, True):
        document = HwpxDocument.new()
        body = document.ensure_run_style(font="Times New Roman", size=11)
        # Distinguish the math style even when the bare template has not yet
        # registered this font face; the saved-PDF check resolves real fonts.
        math = document.ensure_run_style(font="HancomEQN", size=11, bold=True)
        assert body != math
        for text in PROSE:
            paragraph = document.add_paragraph("")
            counter = [0]
            _replace_paragraph_runs(paragraph, text, char_pr_id_ref=body,
                                    math_char_pr_id_ref=math, native_math=native_math,
                                    equation_counter=counter, literal_text=True)
            assert_literal_runs(paragraph.element, text, body)
            assert counter == [0]
        rows = [PROSE[:2], PROSE[2:]]
        _add_table(document, rows, char_pr_id_ref=body, math_char_pr_id_ref=math,
                   native_math=native_math, content_width=40000, height=5000,
                   native_paragraphs=True, literal_text=True)
        table = list(document.sections[0].element.iter(HP + "tbl"))[-1]
        assert_literal_runs(table, "".join(PROSE), body)
    document = HwpxDocument.new()
    for text in ("f(x)", "$x^{2}$"):
        paragraph = document.add_paragraph("")
        counter = [0]
        _replace_paragraph_runs(paragraph, text, char_pr_id_ref="0", math_char_pr_id_ref="0",
                                native_math=True, equation_counter=counter)
        assert counter[0] > 0 and list(paragraph.element.iter(HP + "equation")), text


def synthetic_pdf(path, *, area="영어 영역", equation_font=None, ordinary_math=False):
    document = fitz.open()
    page = document.new_page(width=842, height=1191)
    page.insert_text((160, 100), "2026학년도 시험 문제지", fontname="korea", fontsize=19)
    if area:
        page.insert_text((340, 155), area, fontname="korea", fontsize=30)
    page.draw_line((85, 200), (755, 200), width=1)
    for index, text in enumerate(PROSE):
        page.insert_text((90, 250 + index * 28), text, fontname="tiro", fontsize=11)
    # Ordinary English source glyphs with a raised small digit must remain CO2.
    page.insert_text((90, 370), "CO", fontname="tiro", fontsize=11)
    page.insert_text((106, 366), "2", fontname="tiro", fontsize=7)
    page.insert_text((111, 370), " emissions remain prose.", fontname="tiro", fontsize=11)
    # Exercise literal cell text through the actual PDF table extractor.
    for x in (90, 235, 390):
        page.draw_line((x, 410), (x, 470), width=.5)
    for y in (410, 440, 470):
        page.draw_line((90, y), (390, y), width=.5)
    for x, y, text in ((96, 430, "financial(A)"), (241, 430, "$40 and $50"),
                       (96, 460, "memories(a)"), (241, 460, "(A), (B), (C)")):
        page.insert_text((x, y), text, fontname="tiro", fontsize=11)
    if equation_font:
        page.insert_font(fontname="sourceeq", fontfile=str(equation_font))
        page.insert_text((90, 530), "f(x)", fontname="sourceeq", fontsize=12)
    if ordinary_math:
        page.insert_text((90, 570), "f(x)", fontname="tiro", fontsize=11)
    document.save(path)
    document.close()


def item_text(item):
    return str(item.get("stem") or "") + "".join(str(cell) for table in item.get("tables") or []
                                                for row in table for cell in row)


def package(path):
    with zipfile.ZipFile(path) as archive:
        header = etree.fromstring(archive.read("Contents/header.xml"))
        roots = [etree.fromstring(archive.read(name)) for name in archive.namelist()
                 if name.startswith("Contents/section") and name.endswith(".xml")]
    return roots, header


def verify_source_extraction(folder):
    for source_area, hint in (("영어 영역", ""), ("", "영어 영역")):
        path = folder / ("actual_area.pdf" if source_area else "hint.pdf")
        synthetic_pdf(path, area=source_area)
        items, _ = extract_native_content(path, area_hint=hint)
        textual = [item for item in items if item_text(item)]
        assert textual and all(item["layout"].get("source_literal_text") for item in textual)
        source_text = "".join(item_text(item) for item in textual)
        for text in PROSE:
            assert text in source_text, (text, source_text)
        assert "CO2 emissions remain prose." in source_text, source_text
        assert any(item.get("tables") for item in items), "PDF table fixture did not reach native table extraction"
        annotate_question_groups(items)
        output = path.with_suffix(".hwpx")
        write_hwpx(output, "English source text", items, "kice_english",
                   native_math=True, preserve_source_layout=True)
        roots, header = package(output)
        assert not any(list(root.iter(HP + "equation")) for root in roots)
        output_text = "".join(ordinary_text(root) for root in roots)
        for text in PROSE + ["CO2 emissions remain prose.", "financial(A)", "memories(a)"]:
            assert text in output_text, (text, output_text)
        cells = [ordinary_text(cell) for root in roots for cell in root.iter(HP + "tc")]
        for item in items:
            for table in item.get("tables") or []:
                for row in table:
                    for text in row:
                        assert text in cells, ("native table cell changed", text, cells)
        styles = {node.get("id"): node for node in header.iter(HH + "charPr")}
        faces = {language.get("lang"): {font.get("id"): font.get("face") for font in language.findall(HH + "font")}
                 for language in header.iter(HH + "fontface")}
        body_runs = [run for root in roots for paragraph in root.iter(HP + "p")
                     if ordinary_text(paragraph) and ordinary_text(paragraph) in source_text
                     for run in paragraph.findall(HP + "run") if run.find(HP + "t") is not None]
        assert body_runs
        for run in body_runs:
            style = styles[run.get("charPrIDRef")]
            ref = style.find(HH + "fontRef")
            font = faces["LATIN"][ref.get("latin")]
            assert font in {"Times-Roman", "Times New Roman"}, (ordinary_text(run), font)
        rendered = rhwp.parse(str(output))
        assert rendered.page_count == 1 and bytes(rendered.render_png(0))
    wrong = folder / "math_with_english_hint.pdf"
    synthetic_pdf(wrong, area="수학 영역", ordinary_math=True)
    items, _ = extract_native_content(wrong, area_hint="영어 영역")
    assert not any(item["layout"].get("source_literal_text") for item in items), "Actual math masthead lost to the English hint"
    assert any("f(x)" in item_text(item) for item in items)
    continuation = folder / "math_continuation_without_area.pdf"
    synthetic_pdf(continuation, area="", ordinary_math=True)
    merged = folder / "english_then_math.pdf"
    with fitz.open() as combined, fitz.open(folder / "actual_area.pdf") as english, fitz.open(wrong) as math, fitz.open(continuation) as following:
        combined.insert_pdf(english)
        combined.insert_pdf(math)
        combined.insert_pdf(following)
        combined.save(merged)
    items, _ = extract_native_content(merged, area_hint="영어 영역")
    for page_number, literal in ((1, True), (2, False), (3, False)):
        page_items = [item for item in items if item["source_page"] == page_number and item_text(item)]
        assert page_items and all(bool(item["layout"].get("source_literal_text")) == literal for item in page_items), (
            "Latest actual page area must override the initial document area and English hint", page_number)
        assert any("financial(A)" in item_text(item) for item in page_items)
    math_items = [item for item in items if item["source_page"] in (2, 3) and "f(x)" in item_text(item)]
    assert {item["source_page"] for item in math_items} == {2, 3}
    assert all(not any(is_hancom_eq_font(span.get("font", ""))
                             for line in item["layout"]["source_typography"]["lines"]
                             for span in line["spans"]) for item in math_items), "Math-area guard depends on actual area even for ordinary prose fonts"
    candidates = [Path("C:/Windows/Fonts/HancomEQN.ttf"), Path("C:/Windows/Fonts/HYHWPEQ.TTF")]
    font = next((candidate for candidate in candidates if candidate.is_file()), None)
    if font:
        path = folder / "english_with_equation_font.pdf"
        synthetic_pdf(path, equation_font=font)
        items, _ = extract_native_content(path)
        equation_items = [item for item in items if any(
            is_hancom_eq_font(span.get("font", ""))
            for line in item["layout"].get("source_typography", {}).get("lines", [])
            for span in line.get("spans", []))]
        assert equation_items, "Actual equation font was not present in the PDF fixture"
        assert all(not item["layout"].get("source_literal_text") for item in equation_items)
        assert any(item["layout"].get("source_literal_text") for item in items), "Equation font disabled all ordinary English blocks"
    else:
        print("SKIP optional embedded HancomEq-font PDF case: font file unavailable")


def verify_source_content_math(folder):
    for index, text in enumerate(("f(x)", "$x^{2}$")):
        path = folder / f"math_{index}.hwpx"
        items = [{"number": "", "stem": text, "choices": [], "tables": [[[text]]], "source_page": 1,
                  "layout": {"source_content": True, "source_page_width_pt": 842,
                             "source_column": 1, "source_bbox_pt": [90, 230, 390, 245],
                             "source_typography": {"font_name": "Times New Roman", "font_size_pt": 11}}}]
        write_hwpx(path, "Mathematics", items, "kice_math", native_math=True, preserve_source_layout=True)
        roots, _ = package(path)
        assert sum(len(list(root.iter(HP + "equation"))) for root in roots) >= 2, text


def main():
    verify_run_and_table_helpers()
    with tempfile.TemporaryDirectory(prefix="native_english_literal_") as temporary:
        folder = Path(temporary)
        verify_source_extraction(folder)
        verify_source_content_math(folder)
    print("NATIVE_ENGLISH_LITERAL_TEXT_OK: exact prose/prices/labels, ordinary body fonts, native tables, actual area/font guards, preserved math equations")


if __name__ == "__main__":
    main()
