"""Preserve geometric prescripts, ionic charges and real flat fraction cells."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runtime = tempfile.TemporaryDirectory(prefix="native_chemical_structures_")
os.environ["HWP_MAKE_DATA_DIR"] = runtime.name
from lxml import etree  # noqa: E402
from app.pdf_native_content import recover_native_scripts  # noqa: E402
from app.pdf_source_table_semantics import logical_native_grid  # noqa: E402
from app.pdf_source_semantics import _native_text, _cell_value  # noqa: E402
from app.hwpx_writer_v2 import write_hwpx  # noqa: E402

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
count = 0


def check(value, label):
    global count
    assert value, label
    count += 1
    print("PASS:", label)


def span(text, x, y, size, width):
    return {"text": text, "font": "HyhwpEQ", "origin": (x, y),
            "bbox": (x, y-size, x+width, y+size*.2), "size": size}


def recover(spans):
    return "".join(s["text"] for line in recover_native_scripts([{"spans": spans}])
                   for s in line["spans"])


def main():
    check(recover([span("3a+5b", 10, 33, 7, 15), span("X", 26, 29, 11, 7)])
          == "${}_{3a+5b}X$", "source left lower index remains before its element")
    check(recover([span("3", 20, 25, 7, 4), span("2", 20, 33, 7, 4), span("He", 25, 29, 11, 12)])
          == "${}_{2}^{3}He$", "one element retains BOTH measured left scripts")
    check(recover([span("d", 20, 29, 11, 7), span("2", 28, 25, 7, 4), span("0", 28, 33, 7, 4)])
          == "$d^{2}_{0}$", "one denominator base retains both right scripts")
    check(recover([span("Na", 20, 29, 11, 12), span("+", 33, 25, 7, 4)])
          == "$Na^{+}$", "ionic plus is a native superscript after its element")
    check("H_{2}" in recover([span("H", 10, 29, 11, 7), span("2", 18, 33, 7, 4), span("O", 23, 29, 11, 7)]),
          "H2O index belongs to H even beside the following element")
    check("^{+}" not in recover([span("Na", 20, 29, 11, 12), span("+", 33, 29, 7, 4)]),
          "a baseline plus is not fabricated into a charge")
    check("^{+}" not in recover([span("Na", 20, 29, 11, 12), span("+", 60, 25, 7, 4)]),
          "a distant charge does not attach across a cell")
    output = Path(runtime.name) / "chemical.hwpx"
    fraction = r"$\frac{X^{-}의양+Y^{-}의양}{Na^{+}의양}$(상댓값)"
    items = [{"number": "", "stem": "1. Compare the ionic amounts.",
              "tables": [[["Amount", "Value"], [fraction, "9"]]],
              "source_page": 1, "layout": {"source_content": True, "source_column": 1,
              "question_group": "v1:q01", "question_number": 1,
              "question_variant": 1, "question_group_kind": "question", "question_group_start": True,
              "native_tables": [{"index": 0, "cell_bounds": [
                  [[0,0,180,20],[180,0,220,20]], [[0,20,180,60],[180,20,220,60]]]}]}}]
    write_hwpx(output, "Science", items, "kice_science", native_math=True, preserve_source_layout=True)
    with zipfile.ZipFile(output) as archive:
        root = etree.fromstring(archive.read("Contents/section0.xml"))
        header = etree.fromstring(archive.read("Contents/header.xml"))
    tables = list(root.iter(HP+"tbl"))
    check(len(tables) == 1 and not tables[0].findall(".//"+HP+"tbl"),
          "source cell fraction uses a single real native grid, without nested tables")
    grid = logical_native_grid(tables[0], header, _native_text, _cell_value)
    check(grid is not None and len(grid["cells"]) == 2 and len(grid["cells"][0]) == 2,
          "physical flat rows reconstruct exactly two original logical rows and columns")
    check("Na+" in grid["cells"][1][0] and grid["cells"][1][1] == "9",
          "native ion charge and addressed numeric cell both survive")
    original = tables[0]
    bad = deepcopy(original)
    denominator = next(c for c in bad.iter(HP+"tc") if c.get("name", "").endswith(":denominator"))
    denominator.find(HP+"cellAddr").set("rowAddr", "0")
    check(logical_native_grid(bad, header, _native_text, _cell_value) is None,
          "a labelled denominator in the wrong physical row is rejected")
    bad_header = deepcopy(header)
    numerator = next(c for c in original.iter(HP+"tc") if c.get("name", "").endswith(":numerator"))
    fill = next(x for x in bad_header.iter(HH+"borderFill") if x.get("id") == numerator.get("borderFillIDRef"))
    fill.find(HH+"bottomBorder").set("color", "#FFFFFF")
    check(logical_native_grid(original, bad_header, _native_text, _cell_value) is None,
          "fraction labels cannot excuse an invisible white fraction bar")
    print(f"NATIVE_CHEMICAL_STRUCTURES_OK: {count}")


if __name__ == "__main__":
    main()
