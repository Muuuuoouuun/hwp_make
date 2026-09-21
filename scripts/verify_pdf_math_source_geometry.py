"""Independent source geometry regressions, including the actual 40-page exam."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import fitz
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import pdf_layout_writer as w  # noqa: E402
from app.pdf_script_attachments import source_script_attachments  # noqa: E402
from app.pdf_source_semantics import (  # noqa: E402
    HP,
    _source_math,
    _source_radicals,
    _source_script_lines,
    _native_radicals,
    _tokens,
    _cell_value,
)


def check(value, message):
    if not value:
        raise AssertionError(message)
    print("PASS:", message)


def span(text, x, y, size=10):
    chars = [
        {
            "c": c,
            "bbox": (
                x + i * size * 0.5,
                y - size * 0.8,
                x + (i + 1) * size * 0.5,
                y + size * 0.2,
            ),
            "origin": (x + i * size * 0.5, y),
        }
        for i, c in enumerate(text)
    ]
    return {
        "text": text,
        "font": "HYhwpEQ",
        "size": size,
        "origin": (x, y),
        "bbox": (x, y - size * 0.8, x + len(text) * size * 0.5, y + size * 0.2),
        "chars": chars,
    }


def synthetic():
    mixed = span("1x", 20, 22)
    mixed["chars"][1]["origin"] = (25, 30)
    mixed["chars"][1]["bbox"] = (25, 22, 30, 32)
    script = span("2", 30, 25, 7)
    found = source_script_attachments([{"spans": [mixed, script]}])
    check(
        found[0]["operator"] == "^",
        "mixed numerator/base span uses adjacent glyph baseline",
    )
    left = [{"spans": [span("2", 10, 33, 7), span("3", 10, 25, 7), span("He", 14, 30)]}]
    text = "".join(s["text"] for s in _source_script_lines(left)[0]["spans"])
    check(
        text == "{}_{2}^{3}He", "left isotope scripts attach to their following element"
    )
    charge = [
        {"spans": [span("Na", 20, 30), span("+", 30, 25, 7), span("의 양", 35, 30)]}
    ]
    text = "".join(s["text"] for s in _source_script_lines(charge)[0]["spans"])
    check(
        _cell_value(text) == "Na+의양",
        "detached ion charge remains after its source element",
    )


def actual(source):
    with fitz.open(source) as document:

        def lines(index, region):
            result = []
            for line in w._iter_text_lines(document[index]):
                spans = [
                    s
                    for s in line["spans"]
                    if region.contains(
                        (fitz.Rect(s["bbox"]).tl + fitz.Rect(s["bbox"]).br) / 2
                    )
                ]
                if spans:
                    result.append({"spans": spans})
            return result

        source_lines = lines(13, fitz.Rect(0, 150, 421, 450))
        fragments = _source_math(source_lines, document[13])
        correct = _tokens("{(a_n+2)^2} over {na_n+5n^2-2}")
        check(
            any(correct == f[-len(correct) :] for f in fragments),
            "actual large fraction uses painted rule and preserves both operand scripts",
        )
        check(
            _tokens("2 over n") not in fragments,
            "tall fraction glyph cannot create a false numerator 2 over denominator n",
        )
        roots = _source_radicals(source_lines)
        check(
            _tokens("9n^2-5") in roots,
            "source radical operand stops at original vinculum endpoint",
        )
        good, broken = etree.Element(HP + "drawText"), etree.Element(HP + "drawText")
        for element, script in [
            (good, "sqrt {9n^2-5}+2n"),
            (broken, "sqrt {□}9n^2-5+2n"),
        ]:
            etree.SubElement(
                etree.SubElement(element, HP + "equation"), HP + "script"
            ).text = script
        check(
            roots[0] in _native_radicals(good)
            and roots[0] not in _native_radicals(broken),
            "same radicand letters outside an empty native root are rejected",
        )
        geometry = lines(18, fitz.Rect(0, 150, 421, 600))
        check(
            not any("over" in f for f in _source_math(geometry, document[18])),
            "actual segment overlines cannot borrow preceding-line letters as fractions",
        )
        coordinate = lines(17, fitz.Rect(0, 150, 421, 240))
        check(
            not any(
                f[:2] == ("(", "^") for f in _source_math(coordinate, document[17])
            ),
            "tall opening parenthesis cannot turn a coordinate into a superscript",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    synthetic()
    if args.source:
        actual(args.source)
    print("PDF_MATH_SOURCE_GEOMETRY_OK")
