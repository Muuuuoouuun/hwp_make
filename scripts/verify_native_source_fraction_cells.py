"""Real source-grid fraction preservation and unsafe width/merge regressions."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pdf_question_tables import flatten_question_fraction_tables

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def inventory(node):
    return (Counter("".join(t.text or "" for t in node.iter(HP + "t"))),
            Counter(t.text or "" for t in node.iter(HP + "script")))


def transform(root, header):
    flatten_question_fraction_tables(root.findall(HP + "p"), header, width=22961)


def verify(folder):
    fixtures = {}
    for subject in ("g_che1", "g_ear2"):
        case = folder / ("2027_kice_september_high3__" + subject)
        fixtures[subject] = (etree.parse(str(case / "before.xml")).getroot(),
                             etree.parse(str(case / "before-header.xml")).getroot())
    cases = []
    for subject, (source, header) in fixtures.items():
        root, styles = deepcopy(source), deepcopy(header)
        before = inventory(root)
        transform(root, styles)
        assert inventory(root) == before, "flattening lost a source text character or equation script"
        tables = root.findall(HP + "p/" + HP + "run/" + HP + "tbl")
        assert all(not table.findall(".//" + HP + "tbl") for table in tables)
        for table in tables:
            width = int(table.find(HP + "sz").get("width"))
            assert width == 22961, "flattening changed the actual source view width"
            occupied = set()
            rows, cols = int(table.get("rowCnt")), int(table.get("colCnt"))
            for cell in table.findall(HP + "tr/" + HP + "tc"):
                address, span, size = (cell.find(HP + tag) for tag in ("cellAddr", "cellSpan", "cellSz"))
                c, r = int(address.get("colAddr")), int(address.get("rowAddr"))
                cs, rs = int(span.get("colSpan")), int(span.get("rowSpan"))
                assert min(int(size.get("width")), int(size.get("height"))) > 0
                area = {(x, y) for x in range(c, c+cs) for y in range(r, r+rs)}
                assert not occupied & area and c+cs <= cols and r+rs <= rows
                occupied.update(area)
            assert len(occupied) == rows * cols, "flattened grid has a hole"
        # Once the source fractions have become ordinary editable operand cells,
        # a repeated normalization must be a true no-op.
        baseline = etree.tostring(root), etree.tostring(styles)
        transform(root, styles)
        assert baseline == (etree.tostring(root), etree.tostring(styles))
        cases.append({"subject": subject, "text_and_equations_preserved": True,
                      "complete_nonoverlapping_flat_grid": True, "idempotent": True})

    # These are actual unsupported objects, not filename or producer flags.
    negatives = []
    for kind in ("pic", "rect", "container", "tbl", "floating", "nonfinite", "zero", "equation"):
        root, header = (deepcopy(node) for node in fixtures["g_ear2"])
        fraction = next(t for t in root.iter(HP + "tbl") if t.get("rowCnt") == "2")
        paragraph = fraction.find(HP + "tr/" + HP + "tc/" + HP + "subList/" + HP + "p")
        run = etree.SubElement(paragraph, HP + "run", charPrIDRef="10")
        tag = kind if kind in ("rect", "container", "tbl", "equation") else "pic"
        obj = etree.SubElement(run, HP + tag)
        etree.SubElement(obj, HP + "sz", width="NaN" if kind == "nonfinite" else "0" if kind == "zero" else "50000", height="1000")
        etree.SubElement(obj, HP + "pos", treatAsChar="0" if kind == "floating" else "1", flowWithText="1")
        if kind == "equation":
            etree.SubElement(obj, HP + "script").text = "x + 1"
        try:
            transform(root, header)
        except (ValueError, TypeError, AttributeError):
            negatives.append(kind)
        else:
            raise AssertionError(f"oversized/invalid {kind} was assigned a narrower fraction cell")

    for kind in ("overlap", "hole", "invalidspan", "invalidsize"):
        root, header = (deepcopy(node) for node in fixtures["g_che1"])
        table = root.find(HP + "p/" + HP + "run/" + HP + "tbl")
        target = next(cell for cell in table.findall(HP + "tr/" + HP + "tc") if cell.find(".//" + HP + "tbl") is not None)
        if kind == "overlap":
            target.find(HP + "cellSpan").set("rowSpan", "3")
        elif kind == "hole":
            real = next(cell for cell in table.findall(HP + "tr/" + HP + "tc")
                        if "실린더" in "".join(cell.itertext()))
            real.getparent().remove(real)
        elif kind == "invalidspan":
            target.find(HP + "cellSpan").set("colSpan", "2")
        else:
            target.find(HP + "cellSz").set("height", "0")
        try:
            transform(root, header)
        except (ValueError, TypeError, AttributeError, IndexError):
            negatives.append(kind)
        else:
            raise AssertionError(f"invalid merged source-grid {kind} was accepted")
    return {"ok": True, "source_fixtures": cases, "negative_cases": negatives}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=ROOT / "tmp/september-exam-matrix/fraction-root")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not all((args.fixtures / ("2027_kice_september_high3__" + subject) / "before.xml").is_file()
               for subject in ("g_che1", "g_ear2")):
        print("SKIP: captured pre-normalization real source-grid fixtures missing"); return 2
    report = verify(args.fixtures)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SOURCE_FRACTION_CELLS_OK", json.dumps(report, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
