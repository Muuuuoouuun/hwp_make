"""Verify math typography uses its source span size, independently of prose."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import zipfile

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app.hwpx_writer_v2 import write_hwpx  # noqa: E402
from app.pdf_native_content import annotate_question_groups  # noqa: E402

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS:", message)


def span(text, x, baseline, size, font, width):
    box = (x, baseline - size, x + width, baseline + size * 0.2)
    return {
        "text": text,
        "font": font,
        "size": size,
        "origin": (x, baseline),
        "bbox": box,
        "chars": [
            {
                "c": char,
                "origin": (x + i * width / len(text), baseline),
                "bbox": (
                    x + i * width / len(text),
                    box[1],
                    x + (i + 1) * width / len(text),
                    box[3],
                ),
            }
            for i, char in enumerate(text)
        ],
    }


def main():
    prose = span(
        "1. Compare the scientific quantities.", 100, 180, 8.772, "Helvetica", 190
    )
    small = [
        span("5×10", 100, 210, 9.99, "HyhwpEQ", 27),
        span("-7", 127, 205, 6.81, "HyhwpEQ", 10),
    ]
    large = [
        span("10m/s", 100, 240, 11.01, "HyhwpEQ", 31),
        span("2", 131, 235, 7.47, "HyhwpEQ", 4),
    ]
    density = [
        span("ρ", 100, 270, 11.01, "HyhwpEQ", 5.708),
        span("1", 106.6, 273, 7.47, "HyhwpEQ", 3.72),
    ]
    meta = {
        "font_name": "Helvetica",
        "font_name_recovered": "Helvetica",
        "font_size_pt": 8.772,
        "line_spacing_pt": 13,
        "source_column_width_pt": 320,
        "source_bbox_pt": [100, 170, 420, 255],
        "alignment": "LEFT",
        "lines": [],
    }
    for spans in ([prose], small, large, density):
        meta["lines"].append(
            {
                "text": "".join(s["text"] for s in spans),
                "spans": spans,
                "bbox_pt": [
                    100,
                    min(s["bbox"][1] for s in spans),
                    420,
                    max(s["bbox"][3] for s in spans),
                ],
                "baseline_pt": spans[0]["origin"][1],
                "font_size_pt": spans[0]["size"],
            }
        )
    items = [
        {
            "stem": "1. Compare the scientific quantities.",
            "tables": [
                [
                    ["Small", "$5\\times10^{-7}$"],
                    ["Large", "$10m/s^{2}$"],
                    ["Density", "$ρ_{1}$"],
                ]
            ],
            "source_page": 1,
            "layout": {
                "source_content": True,
                "source_column": 0,
                "source_page_width_pt": 842,
                "source_typography": meta,
            },
        }
    ]
    annotate_question_groups(items)
    with tempfile.TemporaryDirectory(prefix="equation_source_font_") as directory:
        output = Path(directory) / "source_fonts.hwpx"
        unscaled = Path(directory) / "unscaled_fonts.hwpx"
        unmeasured = deepcopy(items)
        unmeasured[0]["layout"].pop("source_typography")
        write_hwpx(
            unscaled,
            "Science examination",
            unmeasured,
            "kice_science",
            native_math=True,
            preserve_source_layout=True,
        )
        write_hwpx(
            output,
            "Science examination",
            deepcopy(items),
            "kice_science",
            native_math=True,
            preserve_source_layout=True,
        )
        with zipfile.ZipFile(output) as package:
            root = etree.fromstring(package.read("Contents/section0.xml"))
            header = etree.fromstring(package.read("Contents/header.xml"))
        with zipfile.ZipFile(unscaled) as package:
            original = etree.fromstring(package.read("Contents/section0.xml"))
            original_equations = list(original.iter(HP + "equation"))
        scale = int(root.find(f".//{HP}pagePr").get("width")) / 842
        equations = list(root.iter(HP + "equation"))
        check(len(equations) == 3, "all scientific quantities remain native equations")
        actual = [int(eq.get("baseUnit")) for eq in equations]
        expected = [round(9.99 * scale), round(11.01 * scale), round(11.01 * scale)]
        check(
            all(abs(a - b) <= 1 for a, b in zip(actual, expected)),
            f"math sizes follow their distinct PDF spans and physical page scale: {actual} expected {expected}",
        )
        runs = [
            run
            for run in root.iter(HP + "run")
            if "Compare" in (run.findtext(HP + "t") or "")
        ]
        style = header.find(f".//{HH}charPr[@id='{runs[0].get('charPrIDRef')}']")
        check(
            abs(int(style.get("height")) - round(8.772 * scale)) <= 1
            and int(style.get("height")) not in actual,
            "smaller surrounding prose does not force its font size onto equations",
        )
        for equation, source_width in zip(equations, [37, 35, 10.32]):
            paragraph = equation.getparent().getparent()
            size = equation.find(HP + "sz")
            expected_width = round(source_width * scale)
            check(
                abs(int(size.get("width")) - expected_width) <= 1,
                "inline equation advance matches actual PDF glyph bounds, including attached scripts",
            )
            lines = paragraph.findall(f"{HP}linesegarray/{HP}lineseg")
            check(
                int(size.get("width")) > 0
                and any(
                    int(line.get("vertsize")) >= int(size.get("height"))
                    for line in lines
                ),
                "native equation size and paragraph cache reserve its scaled height",
            )
        import rhwp

        rendered = etree.fromstring(rhwp.parse(str(output)).render_svg(0).encode())
        svg = "{http://www.w3.org/2000/svg}"
        rho = next(node for node in rendered.iter(svg + "text") if node.text == "ρ")
        import re

        transform = rho.getparent().get("transform", "")
        stretch = re.search(r"scale\(([\d.]+),([\d.]+)\)", transform)
        check(
            stretch is None or abs(float(stretch[1]) / float(stretch[2]) - 1) < 0.10,
            f"actual rho glyph rendering no longer stretches horizontally by 2.44x: {transform}",
        )
    from app.pdf_native_typography import _line_cache

    paragraph = etree.Element(HP + "p")
    run = etree.SubElement(paragraph, HP + "run")
    equation = etree.SubElement(run, HP + "equation", baseUnit="1000")
    etree.SubElement(equation, HP + "script").text = "P_{1}"
    etree.SubElement(equation, HP + "sz", width="3000", height="2200")
    etree.SubElement(run, HP + "t").text = "가나다라마바사아자차카타파하"
    _line_cache(paragraph, 4000, 1000, 1500, {})
    baselines = [
        int(line.get("vertpos")) + int(line.get("baseline"))
        for line in paragraph.findall(HP + "linesegarray/" + HP + "lineseg")
    ]
    check(
        all(right - left >= 1499 for left, right in zip(baselines, baselines[1:])),
        "a tall equation followed by prose preserves the measured baseline interval",
    )
    print("NATIVE_EQUATION_SOURCE_FONT_OK")


if __name__ == "__main__":
    main()
