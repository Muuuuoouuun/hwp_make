"""Real package + source tests: paragraph wraps, currency, Greek atom boundaries."""
# ruff: noqa: E402
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import zipfile

import fitz
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import math_text, hwpx_writer, hwpx_writer_v2
from app.pdf_editability import _compact_text, inspect_pdf_editability
from app.pdf_native_content import extract_native_content, annotate_question_groups
from app.pdf_paragraph_flow import inspect_paragraph_flow
from app.pdf_question_markers import document_note_heading
from app.pdf_source_semantics import _tokens

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def rewrite(source, target, change):
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w") as output:
        root = etree.fromstring(original.read("Contents/section0.xml"))
        change(root)
        for info in original.infolist():
            output.writestr(info, etree.tostring(root) if info.filename == "Contents/section0.xml" else original.read(info.filename))


def main():
    money = "① $100 ② $104 ③ $110 ④ $114 ⑤ $120"
    for prices in (money, money.replace(" ", ""), "① $100② $104 ③ $110④ $114⑤ $120"):
        assert math_text.split_math_text(prices) == [(prices, False)]
    mixed = math_text.split_math_text(money + " and $x^2+1$")
    assert [text for text, is_math in mixed if is_math] == ["$x^2+1$"]
    for formula in (r"$2\pi$", "$2π$", "$2 pi$", "$60 r$", "$2$", "$2 $",
                    r"$14-\sqrt{34}$", r"$20-2\sqrt{34}$", "$3√3$",
                    "$4 sqrt{5}$", r"$18+15\sqrt{3}$", "$2 ln{3}$"):
        assert [text for text, is_math in math_text.split_math_text("① " + formula) if is_math] == [formula]
    assert _tokens(hwpx_writer._hancom_eqn_script("αi+β=0")) == ("α", "i", "+", "β", "=", "0")
    assert _tokens(hwpx_writer._hancom_eqn_script("xα+αβ")) == ("x", "α", "+", "α", "β")
    assert _compact_text("t NEQ 2)에 대하여 선분") == "t≠2)에대하여선분"
    assert document_note_heading("＊ 확 인 사 항") and not document_note_heading("확인 사항을 구하시오.")
    with tempfile.TemporaryDirectory(prefix="native_paragraph_contract_") as tmp:
        folder = Path(tmp)
        source, native = folder / "source.pdf", folder / "native.hwpx"
        lines = ["This source sentence ends at the margin.",
                 "Another full sentence follows right here.",
                 "And a third line continues this paragraph."]
        with fitz.open() as doc:
            page = doc.new_page(width=595, height=842)
            page.insert_text((40, 40), "Paragraph Test")
            page.insert_text((40, 95), "1. Read the three lines.", fontsize=10)
            for i, line in enumerate(lines):
                page.insert_text((40, 130 + i*14), line, fontsize=10)
            page.insert_text((22, 137), "[A]", fontsize=10)
            page.insert_text((50, 190), "A separate paragraph remains separate.", fontsize=10)
            page.insert_text((310, 95), "2. Choose the next answer.", fontsize=10)
            doc.save(source)
        items, _ = extract_native_content(source)
        hwpx_writer_v2.write_hwpx(native, "Paragraph Test", items, "kice_science", native_math=True, preserve_source_layout=True)
        audit = inspect_paragraph_flow(source, native)
        assert audit["ok"] and audit["source_wrap_pairs_checked"] >= 2, audit
        with zipfile.ZipFile(native) as archive:
            root = etree.fromstring(archive.read("Contents/section0.xml"))
        paragraph = next(p for p in root.iter(HP+"p") if lines[0] in "".join(t.text or "" for t in p.findall(HP+"run/"+HP+"t")))
        original = "".join(t.text or "" for t in paragraph.findall(HP+"run/"+HP+"t"))
        assert all(line in original for line in lines) and "separate paragraph" not in original
        assert len(paragraph.findall(HP+"linesegarray/"+HP+"lineseg")) >= 2

        # Paragraph membership remains valid when independently extracted
        # marginal labels sit between the two prose anchors. Exact text
        # fidelity is a separate gate; this one must not call it a split.
        def interleave(root):
            for t in root.iter(HP+"t"):
                if t.text and lines[1] in t.text:
                    t.text = t.text.replace(lines[1], "Ⅰ " + lines[1])
        labelled = folder / "labelled.hwpx"
        rewrite(native, labelled, interleave)
        assert inspect_paragraph_flow(source, labelled)["ok"]

        def split(root):
            p = next(p for p in root.iter(HP+"p") if lines[0] in "".join(t.text or "" for t in p.findall(HP+"run/"+HP+"t")))
            parent, index = p.getparent(), p.getparent().index(p)
            for offset, text in enumerate(lines):
                child = deepcopy(p)
                for run in child.findall(HP+"run"):
                    child.remove(run)
                run = etree.SubElement(child, HP+"run", charPrIDRef="0")
                etree.SubElement(run, HP+"t").text = text
                cache = child.find(HP+"linesegarray")
                if cache is not None:
                    child.remove(cache)
                parent.insert(index+offset, child)
            parent.remove(p)
        broken = folder / "split.hwpx"
        rewrite(native, broken, split)
        assert "source_paragraph_split_at_visual_line" in inspect_paragraph_flow(source, broken)["issues"]
        assert "source_paragraph_split_at_visual_line" in inspect_pdf_editability(source, broken, [], require_question_boxes=True)["issues"]

        def hard_break(root):
            text = next(t for t in root.iter(HP+"t") if t.text and lines[0] in t.text)
            etree.SubElement(text, HP+"lineBreak")
        rewrite(native, folder / "hard_break.hwpx", hard_break)
        assert "source_paragraph_uses_hard_line_breaks" in inspect_paragraph_flow(source, folder / "hard_break.hwpx")["issues"]

        # Actual saved controls, not just the string converter.
        items = [{"stem": "1. Price choices: " + money + " Formula: $αi+β=0$", "source_page": 1,
                  "layout": {"source_content": True, "source_column": 1, "source_page_width_pt": 595}}]
        annotate_question_groups(items)
        hwpx_writer_v2.write_hwpx(folder / "money.hwpx", "Source values", items, "kice_science", native_math=True, preserve_source_layout=True)
        with zipfile.ZipFile(folder / "money.hwpx") as archive:
            root = etree.fromstring(archive.read("Contents/section0.xml"))
        text = "".join(t.text or "" for t in root.iter(HP+"t"))
        assert all(value in text for value in ("$100", "$104", "$110", "$114", "$120")), text
        assert any(_tokens(s.text) == ("α", "i", "+", "β", "=", "0") for s in root.iter(HP+"script"))
    print("NATIVE_PARAGRAPH_CONTRACT_OK: actual paragraph wraps, split/hard-break rejection, currency choices, Greek symbols")


if __name__ == "__main__":
    main()
