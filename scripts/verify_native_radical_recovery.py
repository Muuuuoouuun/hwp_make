"""Source vinculum recovery retains real operands and outside suffix glyphs."""
from collections import Counter
from pathlib import Path
import re
import sys

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import pdf_layout_writer as w  # noqa: E402
from app.pdf_math_geometry import recover_native_radicals  # noqa: E402
from app.pdf_native_content import recover_stacked_fractions  # noqa: E402


def check(value, label):
    assert value, label
    print("PASS:", label)


def span(text, box, origin, size):
    return {"text": text, "font": "HyhwpEQ", "size": size, "bbox": box,
            "origin": origin, "chars": [{"c": text, "bbox": box, "origin": origin}]}


def literal(lines):
    text = "".join(w._pdf_output_text(s["text"]) for line in lines for s in line["spans"])
    text = text.replace(r"\sqrt", "√")
    return Counter(re.sub(r"[\s${}_^□▢]", "", text))


def main():
    with fitz.open() as doc:
        page = doc.new_page(width=200, height=200)
        root = span("√", (20,40,30,53), (20,50), 12)
        bar = span(w._HANCOM_FRACTION_RULE_CHAR, (29,20,60,55), (29,50),35)
        a = span("x",(30,42,35,53),(30,51),11)
        b = span("+",(37,42,42,53),(37,51),11)
        c = span("y",(44,42,49,53),(44,51),11)
        tail = span("z",(62,42,67,53),(62,51),11)
        lines = [{"spans":[root,bar,a,b,c,tail]}]
        check(not any(s.get("source_radical_chars") for line in recover_native_radicals(lines,source_page=page) for s in line["spans"]),
              "a tall placeholder alone cannot prove a root vinculum")
        page.draw_line((29,38),(60,38),width=.5)
        # An unrelated full-width header also crosses the tall placeholder box.
        page.draw_line((0,22),(100,22),width=.5)
        after = recover_native_radicals(lines,source_page=page)
        check(any(s["text"] == r"$\sqrt{x+y}$" for line in after for s in line["spans"]),
              "actual vinculum near the radical sign wins over an unrelated header rule")
        check(any(s["text"] == "z" for line in after for s in line["spans"]),
              "a following symbol outside the source vinculum stays outside the root")
        check(literal(after) == literal(lines), "synthetic recovery conserves every operand and suffix glyph")
    with fitz.open(ROOT/'data/uploads/25수능 수학.pdf') as doc:
        for index in (12,13,32,33):
            before = w._iter_text_lines(doc[index])
            after = recover_native_radicals(before,source_page=doc[index])
            expected = {r"$\sqrt{sinx-sin^{3}x}$"} if index in (12,32) else {r"$\sqrt{9n^{2}-5}$",r"$\sqrt{x+xlnx}$"}
            found = {s['text'] for line in after for s in line['spans'] if s.get('source_radical_chars')}
            check(expected <= found, f"page {index+1} restores its actual compound root operands")
            check(literal(before) == literal(after),f"page {index+1} conserves original literal glyph inventory")
            fractions, _ = recover_stacked_fractions(after,doc[index].get_drawings(),[],source_page=doc[index])
            check(all(text.strip('$') in ''.join(s['text'] for line in fractions for s in line['spans']) for text in expected),
                  f"page {index+1} retains restored roots through subsequent fraction processing")
        for index in (2,13,22,33):
            recovered = recover_native_radicals(w._iter_text_lines(doc[index]),source_page=doc[index])
            _, fractions = recover_stacked_fractions(recovered,doc[index].get_drawings(),[],source_page=doc[index])
            required = (r"\frac{3\sqrt{10}}{10}" if index in (2,22)
                        else r"\frac{\sqrt{3}(3+8ln2)}{16}")
            check(required in fractions and all('$' not in value for value in fractions),
                  f"page {index+1} nests root inside one outer fraction without nested math delimiters")
    print("NATIVE_RADICAL_RECOVERY_OK: 20")


if __name__ == '__main__':
    main()
