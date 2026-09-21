"""Regression checks for scientific values, addressed cells and painted text."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import zipfile

import fitz
from lxml import etree
import rhwp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import pdf_layout_writer as writer  # noqa: E402
from app.hwpx_writer_v2 import write_hwpx  # noqa: E402
from app.pdf_source_semantics import (  # noqa: E402
    inspect_source_question_semantics,
    source_grid_cells,
)
from app.pdf_question_rendering import inspect_question_rendering, _visible_svg_text  # noqa: E402
from app.pdf_editability import _compact_text  # noqa: E402

H = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print("PASS:", label)


def span(text, x=40, y=60, size=10):
    return {
        "text": text,
        "font": "HyhwpEQ",
        "size": size,
        "origin": (x, y),
        "bbox": (x, y - size, x + len(text) * size * 0.55, y + size * 0.2),
    }


def paragraph(text, equation=False):
    p = etree.Element(H + "p")
    r = etree.SubElement(p, H + "run")
    if equation:
        r = etree.SubElement(r, H + "equation")
    etree.SubElement(r, H + ("script" if equation else "t")).text = text
    return p


def native(expressions):
    sub = etree.Element(H + "subList")
    for expression in expressions:
        sub.append(paragraph(expression, True))
    return sub


def tests(directory):
    bounds = fitz.Rect(0, 0, 595, 842)
    check(
        _compact_text("코ᇰ\u200b") == _compact_text("코ᇰ")
        and _compact_text("코ᇰ") != _compact_text("콩"),
        "zero-width break normalization preserves historical Hangul jamo",
    )
    source = [
        {"spans": [span("v=1500m/s")]},
        {"spans": [span("x=1")]},
        {"spans": [span("y=2")]},
    ]
    good = native(["v=1500m/s", "x=1", "y=2"])
    check(
        inspect_source_question_semantics(source, good, bounds, [])["ok"],
        "source units and equations match native equation structure",
    )
    wrong = native(["v=9999m/s", "x=1", "y=2"])
    check(
        not inspect_source_question_semantics(source, wrong, bounds, [])["ok"],
        "changed scientific constant is rejected",
    )
    wrong = native(["v=1500m/s", "x=2", "y=1"])
    check(
        not inspect_source_question_semantics(source, wrong, bounds, [])["ok"],
        "same numeric inventory cannot conceal exchanged equation associations",
    )
    check(
        not inspect_source_question_semantics(source + source, good, bounds, [])["ok"],
        "one formula occurrence cannot satisfy duplicate source occurrences",
    )
    # A real PDF producer can put the numerator and suffix in the same span,
    # despite their different baselines. Only glyph geometry preserves 3/5 p.
    numerator = span("3p", 42, 52)
    numerator["chars"] = [
        {"c": "3", "bbox": (42, 44, 48, 54), "origin": (42, 52)},
        {"c": "p", "bbox": (52, 51, 58, 61), "origin": (52, 59)},
    ]
    denominator = span("5", 42, 67)
    denominator["chars"] = [{"c": "5", "bbox": (42, 59, 48, 69), "origin": (42, 67)}]
    rule = span("\ue06d", 40, 64)
    rule["chars"] = [{"c": "\ue06d", "bbox": (40, 52, 50, 66), "origin": (40, 64)}]
    fraction_source = [{"spans": [numerator]}, {"spans": [rule, denominator]}]
    check(
        inspect_source_question_semantics(
            fraction_source, native(["{3} over {5}p"]), bounds, []
        )["ok"],
        "source fraction rule binds denominator despite combined numerator/suffix span",
    )
    check(
        not inspect_source_question_semantics(
            fraction_source, native(["{3} over {4}p"]), bounds, []
        )["ok"],
        "changed fraction denominator is rejected",
    )
    check(
        not inspect_source_question_semantics(
            fraction_source, native(["35p"]), bounds, []
        )["ok"],
        "flattened numerator/denominator cannot satisfy native fraction structure",
    )
    relation = [{"spans": [span("0≤x<5")]}]
    check(
        inspect_source_question_semantics(relation, native(["0 LEQ x<5"]), bounds, [])[
            "ok"
        ],
        "equivalent encoded relation signs retain their meaning",
    )
    check(
        not inspect_source_question_semantics(
            relation, native(["0 GEQ x<5"]), bounds, []
        )["ok"],
        "reversed inequality is rejected",
    )
    with fitz.open() as pdf:
        page = pdf.new_page(width=595, height=842)
        xs = [40, 110, 180, 250]
        ys = [40, 70, 100]
        for x in xs:
            page.draw_line((x, 40), (x, 100))
        for y in ys:
            page.draw_line((40, y), (250, y))
        cells = [["Sample", "T", "S"], ["A", "4.0", "34.2"]]
        for row, values in enumerate(cells):
            for col, text in enumerate(values):
                page.insert_text((xs[col] + 5, ys[row] + 20), text, fontsize=10)
        grid_cache = {}
        specs = source_grid_cells(
            page, writer._iter_text_lines(page), raw_grid_collector=grid_cache
        )
        check(
            specs == source_grid_cells(page, writer._iter_text_lines(page))
            and grid_cache[1][0]["bbox"] == specs[0]["bbox"],
            "shared source-grid detection retains identical independent table evidence",
        )
        check(
            len(specs) == 1 and specs[0]["cells"] == cells,
            "actual PDF grid glyphs are associated with their source row and column",
        )
        sub = etree.Element(H + "subList")
        p = etree.SubElement(sub, H + "p")
        run = etree.SubElement(p, H + "run")
        table = etree.SubElement(run, H + "tbl", rowCnt="2", colCnt="3", id="1")
        for row, values in enumerate(cells):
            tr = etree.SubElement(table, H + "tr")
            for col, text in enumerate(values):
                cell = etree.SubElement(tr, H + "tc")
                etree.SubElement(
                    cell, H + "cellAddr", rowAddr=str(row), colAddr=str(col)
                )
                etree.SubElement(cell, H + "subList").append(paragraph(text))
        check(
            inspect_source_question_semantics([], sub, bounds, specs)["ok"],
            "unchanged addressed native table passes",
        )
        altered = deepcopy(sub)
        values = altered.findall(".//" + H + "tr")[1].findall(H + "tc")
        a = values[1].find(".//" + H + "t")
        b = values[2].find(".//" + H + "t")
        a.text, b.text = b.text, a.text
        report = inspect_source_question_semantics([], altered, bounds, specs)
        check(
            not report["ok"] and len(report["wrong_source_cells"][0]["cells"]) == 2,
            "temperature/salinity cell swap is rejected with both source addresses",
        )
        merged = deepcopy(sub)
        first_row = merged.findall(".//" + H + "tr")[0].findall(H + "tc")
        first_row[1].find(".//" + H + "t").text = "T and S"
        etree.SubElement(first_row[1], H + "cellSpan", rowSpan="1", colSpan="2")
        etree.SubElement(first_row[1], H + "cellSz", width="2000", height="1000")
        first_row[2].find(".//" + H + "t").text = ""
        etree.SubElement(first_row[2], H + "cellSz", width="0", height="1000")
        merged_specs = [
            {
                "bbox": specs[0]["bbox"],
                "cells": [
                    ["Sample", "T and S".replace(" ", ""), None],
                    ["A", "4.0", "34.2"],
                ],
            }
        ]
        check(
            inspect_source_question_semantics([], merged, bounds, merged_specs)["ok"],
            "covered zero-area schema placeholder represents a real colspan",
        )
        first_row[1].find(H + "cellSpan").set("colSpan", "1")
        check(
            not inspect_source_question_semantics([], merged, bounds, merged_specs)[
                "ok"
            ],
            "an empty placeholder without actual spanning geometry cannot fake a merged source cell",
        )
    for tag, extra in [
        ("white", 'fill="white"'),
        ("transparent", 'opacity="0"'),
        ("hidden", 'style="display:none"'),
        ("offpage", 'transform="translate(300,0)"'),
    ]:
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text x="10" y="30" font-size="12" {extra}>VISIBLE</text></svg>'
        check(
            not _visible_svg_text(svg)[0], f"{tag} SVG text does not count as visible"
        )
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs><clipPath id="c"><rect x="0" y="0" width="5" height="5"/></clipPath></defs><g clip-path="url(#c)"><text x="10" y="30" font-size="12">CLIPPED</text></g></svg>'
    check(
        not _visible_svg_text(svg)[0],
        "fully clipped SVG text does not count as visible",
    )
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><g transform="translate(5,5)"><text x="10" y="30" fill="black" font-size="12">VISIBLE</text></g></svg>'
    check(
        _visible_svg_text(svg)[0] == "VISIBLE",
        "painted in-bounds transformed text remains visible",
    )
    path = directory / "native.hwpx"
    hidden = directory / "white.hwpx"
    items = [
        {
            "stem": "1. This scientific condition must remain visible.\n$1500m/s$",
            "source_page": 1,
            "layout": {
                "source_content": True,
                "source_column": 1,
                "question_group": "v1:q01",
                "question_group_kind": "question",
                "question_number": 1,
            },
        }
    ]
    write_hwpx(
        path,
        "Scientific visibility",
        items,
        "kice_science",
        native_math=True,
        preserve_source_layout=True,
    )
    check(
        inspect_question_rendering(path, rhwp)["ok"],
        "real native question drawing renders visibly",
    )
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(hidden, "w") as out:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "Contents/header.xml":
                root = etree.fromstring(data)
                for style in root.iter(HH + "charPr"):
                    style.set("textColor", "#FFFFFF")
                data = etree.tostring(root)
            out.writestr(info, data)
    report = inspect_question_rendering(hidden, rhwp)
    check(
        not report["ok"] and report["invisible_native_content"],
        "real white-text HWPX is rejected even though SVG still contains the words",
    )
    (directory / "visibility_failure.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="source_semantics_") as temporary:
        tests(Path(temporary))
    print("PDF_SOURCE_SEMANTICS_OK")
