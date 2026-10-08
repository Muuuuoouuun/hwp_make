"""Prove source open-edge cells, native ownership, and rejection of data loss.

Synthetic checks always run. Optional --high1-pdf audits the actual September
Q10 source and converts only its first page in isolated storage. --old-hwpx
proves that the previously generated empty edge cells still fail verification.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="open_edge_grid_")
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name

import fitz  # noqa: E402
from lxml import etree  # noqa: E402
import rhwp  # noqa: E402
from app import pdf_layout_writer as writer  # noqa: E402
from app.pdf_source_grid_geometry import source_grid_cell_bounds  # noqa: E402
from app.pdf_source_semantics import (  # noqa: E402
    HP, _native_grids, inspect_source_question_semantics, source_grid_cells,
)


def check(condition, message):
    assert condition, message
    print("PASS:", message, flush=True)


def fixture(path):
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_text((180, 45), "English source table", fontsize=14)
        page.insert_text((40, 95), "1. Choose the matching model.", fontsize=10)
        page.insert_text((315, 95), "2. Read the other English passage.", fontsize=10)
        xs, ys = [40, 85, 130, 175, 220, 265], [125, 150, 170, 190, 210]
        for col in range(5):
            page.draw_rect(fitz.Rect(xs[col], ys[0], xs[col + 1], ys[1]),
                           color=None, fill=(.85, .85, .85))
        for x in xs[1:-1]:
            page.draw_line((x, ys[0]), (x, ys[-1]), width=.5)
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y), width=.5)
        cells = [["Model", "Price", "Space", "Size", "Mode"],
                 ["A", "$40", "16", "10", "X"],
                 ["B", "$50", "32", "10", "X"],
                 ["C", "$60", "32", "16", "O"]]
        for row, values in enumerate(cells):
            for col, text in enumerate(values):
                page.insert_text((xs[col] + 5, ys[row] + 15), text, fontsize=9)
        document.save(path)
    return cells


def package(path, question=None):
    with zipfile.ZipFile(path) as archive:
        header = etree.fromstring(archive.read("Contents/header.xml"))
        roots = [etree.fromstring(archive.read(name)) for name in archive.namelist()
                 if name.startswith("Contents/section") and name.endswith(".xml")]
    if question:
        draws = [draw for root in roots for draw in root.iter(HP + "drawText")
                 if draw.get("name") == question]
        assert len(draws) == 1, (question, len(draws))
        return draws[0], header
    return roots[0], header


def audit(source, output, *, question, expected_edges):
    with fitz.open(source) as document:
        page = document[0]
        grids = source_grid_cells(page, writer._iter_text_lines(page))
        check(len(grids) == 1, "one independently detected source grid")
        expected = grids[0]["cells"]
        check([row[-1] for row in expected[1:]] == expected_edges,
              "source glyphs retain the last-column row associations")
        check([row[-5] for row in expected[1:]] == list("ABCDE")[:len(expected)-1],
              "source glyphs retain A/B/C model row associations")
        draw, header = package(output, question)
        report = inspect_source_question_semantics([], draw, fitz.Rect(page.rect), grids,
                                                   header=header)
        check(report["ok"], "native table matches every source row/column value")
        check(len(_native_grids(draw, header)) == 1,
              "source data belongs to one real native table")
        table = next(draw.iter(HP + "tbl"))
        # Deleting a model is real data loss, regardless of literal text elsewhere.
        altered = deepcopy(draw)
        cell = next(c for c in altered.iter(HP + "tc")
                    if c.find(HP + "cellAddr").get("rowAddr") == "1"
                    and c.find(HP + "cellAddr").get("colAddr") == str(len(expected[0])-5))
        for text in cell.iter(HP + "t"):
            text.text = ""
        check(not inspect_source_question_semantics([], altered, fitz.Rect(page.rect), grids,
                                                    header=header)["ok"],
              "deleting a restored outer model cell is rejected")
        altered = deepcopy(draw)
        outer = [c for c in altered.iter(HP + "tc")
                 if c.find(HP + "cellAddr").get("colAddr") == str(len(expected[0])-1)
                 and c.find(HP + "cellAddr").get("rowAddr") in ("1", str(len(expected)-1))]
        a, b = [next(c.iter(HP + "t")) for c in outer]
        a.text, b.text = b.text, a.text
        check(not inspect_source_question_semantics([], altered, fitz.Rect(page.rect), grids,
                                                    header=header)["ok"],
              "exchanging different outer mode values is rejected")
        check(not list(table.iter(HP + "pic")) and not list(table.iter(HP + "equation")),
              "restored data remains native literal cell text")
    rendered = rhwp.parse(str(output)).render_svg(0)
    for letter in list("ABCDE")[:len(expected)-1]:
        check(f">{letter}<" in rendered, f"restored model {letter} is actually painted")
    return grids


def negative_geometry(page, grid):
    original = [[cell for cell in row.cells] for row in grid.rows]
    drawings = page.get_drawings()
    header = next(row for row in original if all(row))
    target = next(i for i, row in enumerate(original) if row[0] is None)
    fixed = source_grid_cell_bounds(page, grid)
    check(fixed[target][0] is not None, "open outer cell has complete source rule proof")
    fake_rows = deepcopy(original)
    fake_rows[target][2] = None
    fake = SimpleNamespace(rows=[SimpleNamespace(cells=row) for row in fake_rows], col_count=5)
    check(source_grid_cell_bounds(page, fake)[target][2] is None,
          "a missing interior cell is never invented")
    # A real rowspan occupies the apparent None slot: no blank normalization.
    fake_rows = deepcopy(original)
    fake_rows[target-1][0] = (header[0][0], header[0][1], header[0][2], fixed[target][0][3])
    fake = SimpleNamespace(rows=[SimpleNamespace(cells=row) for row in fake_rows], col_count=5)
    check(source_grid_cell_bounds(page, fake)[target][0] is None,
          "an actual spanning source cell prevents false outer-cell recovery")
    for key, value, label in (("stroke_opacity", 0, "hidden"),
                              ("color", (1, 1, 1), "white"),
                              ("dashes", "[2 2] 0", "dashed")):
        altered = [{**drawing, key: value} for drawing in drawings]
        check(source_grid_cell_bounds(page, grid, altered)[target][0] is None,
              f"{label} source rules cannot prove an outer cell")
    check(source_grid_cell_bounds(page, grid, [d for d in drawings
          if all(item[0] != "l" or abs(item[1].y-item[2].y) > .5
                 or abs(item[1].y-fixed[target][0][3]) > .5 for item in d["items"])])[target][0] is None,
          "a missing row separator prevents recovery")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--high1-pdf", type=Path)
    parser.add_argument("--old-hwpx", type=Path)
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args()
    folder = args.artifacts or Path(RUNTIME.name)
    folder.mkdir(parents=True, exist_ok=True)
    source, output = folder / "english-open-edge.pdf", folder / "open-edge.hwpx"
    fixture(source)
    with fitz.open(source) as document:
        grid = document[0].find_tables().tables[0]
        check(any(row.cells[0] is None for row in grid.rows[1:]),
              "synthetic source reproduces the detector's open-edge omission")
        negative_geometry(document[0], grid)
    writer.write_pdf_structured_hwpx(source, output, template_key="kice_english")
    audit(source, output, question="question:v1:q01", expected_edges=["X", "X", "O"])
    if args.high1_pdf:
        if not args.high1_pdf.is_file():
            print("MISSING:", args.high1_pdf)
            return 2
        actual = folder / "high1-september-p1.hwpx"
        writer.write_pdf_structured_hwpx(args.high1_pdf, actual, max_pages=1,
                                         template_key="kice_english")
        grids = audit(args.high1_pdf, actual, question="question:v1:q10",
                      expected_edges=["*", "*", "○", "○", "○"])
        if args.old_hwpx:
            old, header = package(args.old_hwpx, "question:v1:q10")
            check(not inspect_source_question_semantics([], old, fitz.Rect(0, 0, 841, 1190),
                                                       grids, header=header)["ok"],
                  "the original export with missing edge data still fails")
        doc = rhwp.parse(str(actual))
        (folder / "high1-september-p1.png").write_bytes(bytes(doc.render_png(0)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
