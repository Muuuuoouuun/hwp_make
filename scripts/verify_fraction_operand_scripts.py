"""Regress actual math numerator/subscript loss without weakening validators."""
from __future__ import annotations

from pathlib import Path
import sys

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import pdf_layout_writer as w  # noqa: E402
from app.pdf_native_content import recover_stacked_fractions, recover_native_scripts  # noqa: E402
from app.pdf_script_attachments import inspect_script_attachments  # noqa: E402


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS:", message)


def span(text, bbox, origin, size):
    return {"text": text, "bbox": bbox, "origin": origin, "size": size,
            "font": "HyhwpEQ", "chars": [{"c": text, "bbox": bbox, "origin": origin}]}


def synthetic():
    lines = [{"spans": [span(w._HANCOM_FRACTION_RULE_CHAR, (100,220,170,260), (100,252),40)]},
             {"spans": [span("x",(120,231,126,242),(120,240),11), span("2",(126.3,226,130,234),(126.3,235),7.5)]},
             {"spans": [span("a",(120,249,126,260),(120,258),11), span("2",(126.3,244,130,252),(126.3,253),7.5)]}]
    with fitz.open() as document:
        page = document.new_page(width=595,height=842)
        page.draw_line(fitz.Point(100,245),fitz.Point(170,245),width=.6)
        _, result = recover_stacked_fractions(lines,[],[],source_page=page)
        check(result == [r"\frac{x^{2}}{a^{2}}"], "actual long rule position preserves a numerator superscript outside the baseline band")
    with fitz.open() as document:
        page = document.new_page(width=595,height=842)
        page.draw_line(fitz.Point(100,245),fitz.Point(125,245),width=1)
        fallback = recover_stacked_fractions(lines,[],[])[1]
        check(recover_stacked_fractions(lines,[],[],source_page=page)[1] == fallback,
              "a short horizontal stroke cannot replace the fraction rule position")
    separated = [{"spans": [span("a",(10,20,16,31),(10,29),11),span("n+1",(16.3,25,26,32),(16.3,32),7.5)]}]
    recovered = recover_native_scripts(separated)
    check(recovered[0]["spans"][0]["text"] == "$a_{n+1}$", "source-proven compound index n+1 remains attached to its base")
    separated[0]["spans"][1]["origin"] = (16.3,29)
    check(len(recover_native_scripts(separated)[0]["spans"]) == 2, "baseline n+1 is not invented as a subscript")


def actual():
    source = ROOT / "data/uploads/25수능 수학.pdf"
    with fitz.open(source) as document:
        for page_index, required in (
            (13, [r"\frac{(a_{n}+2)^{2}}{na_{n}+5n^{2}-2}"]),
            (15, [r"\frac{1}{a_{i}}", r"\frac{1}{a_{n}a_{n+1}}"]),
            (17, [r"\frac{x^{2}}{a^{2}}", r"\frac{y^{2}}{a^{2}}"]),
        ):
            for index in (page_index, page_index+20):
                page = document[index]
                _, fractions = recover_stacked_fractions(w._iter_text_lines(page),page.get_drawings(),[],source_page=page)
                check(all(expression in fractions for expression in required), f"source page {index+1} preserves its actual fraction operands")
    expected = [{"base":"x","operator":"^","value":"2"}, {"base":"y","operator":"^","value":"2"}]
    check(not inspect_script_attachments(expected, ["{x} over {a^{2}}", "{y} over {a^{2}}"])["ok"],
          "the original lossy ellipse equations remain rejected by the independent attachment gate")
    check(inspect_script_attachments(expected, ["{x^{2}} over {a^{2}}", "{y^{2}} over {a^{2}}"])["ok"],
          "correct native ellipse numerator attachments pass the unchanged semantic gate")


if __name__ == "__main__":
    synthetic()
    actual()
    print("FRACTION_OPERAND_SCRIPTS_OK")
