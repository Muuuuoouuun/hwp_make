"""Native sigma limits: source geometry, editability, and anti-flattening tests."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from pathlib import Path
import sys

import fitz
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app import pdf_layout_writer as w  # noqa: E402
from app.hwpx_writer import _hancom_eqn_script  # noqa: E402
from app.pdf_native_content import recover_native_sum_limits  # noqa: E402
from app.pdf_source_semantics import (  # noqa: E402
    HP,
    _source_sum_limits,
    _native_sum_limits,
    inspect_source_question_semantics,
)


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS:", message)


def span(text, bounds, size, baseline):
    return {
        "text": text,
        "font": "HyhwpEQ",
        "bbox": bounds,
        "size": size,
        "origin": (bounds[0], baseline),
        "chars": [],
    }


def native(lines):
    draw = etree.Element(HP + "drawText")
    for line in lines:
        for item in line["spans"]:
            if not item.get("source_sum_limits"):
                continue
            paragraph = etree.SubElement(draw, HP + "p")
            equation = etree.SubElement(
                etree.SubElement(paragraph, HP + "run"), HP + "equation"
            )
            etree.SubElement(equation, HP + "script").text = _hancom_eqn_script(
                item["text"].strip("$")
            )
    return draw


def synthetic():
    lines = [
        {
            "spans": [span("∑", (40, 40, 54, 60), 20, 56)],
            "bbox": fitz.Rect(40, 40, 54, 60),
        },
        {
            "spans": [span("4", (45, 34, 49, 42), 7, 40)],
            "bbox": fitz.Rect(45, 34, 49, 42),
        },
        {
            "spans": [span("k=1", (39, 56, 55, 64), 7, 62)],
            "bbox": fitz.Rect(39, 56, 55, 64),
        },
    ]
    fixed = recover_native_sum_limits(lines)
    check(
        len(fixed) == 1 and fixed[0]["spans"][0]["text"] == r"$\sum_{k=1}^{4}$",
        "explicit centered upper/lower source bands become one native sum",
    )
    check(
        lines[1]["spans"][0]["text"] == "4",
        "original source glyph dictionaries remain unchanged",
    )
    draw = native(fixed)
    region = fitz.Rect(0, 0, 200, 200)
    check(
        inspect_source_question_semantics(lines, draw, region, [])["ok"],
        "source limits match an actual native equation's attached bounds",
    )
    broken = deepcopy(draw)
    next(broken.iter(HP + "script")).text = "sum_{k=1}^{5}"
    p = etree.SubElement(broken, HP + "p")
    etree.SubElement(etree.SubElement(p, HP + "run"), HP + "t").text = "4"
    report = inspect_source_question_semantics(lines, broken, region, [])
    check(
        any(
            x.get("structure") == "sum_limits" for x in report["missing_math_fragments"]
        ),
        "plain copied upper-limit digit cannot conceal a changed native sum bound",
    )
    distant = deepcopy(lines)
    distant[1]["spans"][0]["bbox"] = (90, 34, 94, 42)
    check(
        not any(
            s.get("source_sum_limits")
            for line in recover_native_sum_limits(distant)
            for s in line["spans"]
        ),
        "unrelated nearby-row number cannot supply a missing sum bound",
    )


def actual(source):
    expected, recovered = Counter(), Counter()
    with fitz.open(source) as pdf:
        for page in pdf:
            lines = w._iter_text_lines(page)
            expected.update(_source_sum_limits(lines))
            recovered.update(
                _native_sum_limits(native(recover_native_sum_limits(lines)))
            )
    check(
        expected and expected == recovered,
        f"all {sum(expected.values())} source sigma limit pairs survive native conversion",
    )
    check(
        expected[(("k", "=", "1"), ("4",))] >= 4,
        "first-row sums retain upper limits crossing the body-start boundary",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    synthetic()
    if args.source:
        actual(args.source)
    print("NATIVE_SUM_LIMITS_OK")
