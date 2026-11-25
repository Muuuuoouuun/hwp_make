"""Editable two-column worksheets with one verifiable ruled table per page."""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import fitz


def _source_grid(page):
    # Limit this flow to a grid made from straight strokes. Other art must never
    # disappear as a side effect of converting the table.
    drawings = page.get_drawings()
    if (not drawings or len(drawings) > 512 or page.get_image_info()
            or any(d["type"] != "s" for d in drawings)):
        raise ValueError("Unsupported worksheet graphics")
    tables = page.find_tables(strategy="lines_strict").tables
    if len(tables) != 1:
        raise ValueError("Expected one ruled table")
    table = tables[0]
    if not (2 <= table.row_count <= 40 and 2 <= table.col_count <= 12):
        raise ValueError("Unsupported grid size")
    bounds = fitz.Rect(table.bbox)
    mid = (page.rect.x0 + page.rect.x1) / 2
    words = page.get_text("words")
    if not any(y0 < bounds.y1 and y1 > bounds.y0 and
               (x1 < mid < bounds.x0 or bounds.x1 < mid < x0)
               for x0, y0, x1, y1, *_ in words):
        raise ValueError("Expected body text opposite the table")

    # Accept strokes on identified grid boundaries only, including segmented
    # rules. A diagonal, drawing in a cell, or a separate figure is unsupported.
    xs = {x for cell in table.cells for x in (cell[0], cell[2])}
    ys = {y for cell in table.cells for y in (cell[1], cell[3])}
    margin = bounds + (-1, -1, 1, 1)
    for drawing in drawings:
        for item in drawing["items"]:
            if item[0] != "l":
                raise ValueError("Unsupported worksheet drawing")
            start, end = item[1:3]
            if start not in margin or end not in margin:
                raise ValueError("Artwork outside the grid")
            vertical = abs(start.x - end.x) < 0.1 and any(abs(start.x - x) < 1 for x in xs)
            horizontal = abs(start.y - end.y) < 0.1 and any(abs(start.y - y) < 1 for y in ys)
            if not (vertical or horizontal):
                raise ValueError("Artwork inside the grid")
    x_edges, y_edges = sorted(xs), sorted(ys)
    if len(x_edges) != table.col_count + 1 or len(y_edges) != table.row_count + 1:
        raise ValueError("Irregular table grid")
    text = table.extract()
    cells = [[[] for _ in row] for row in text]
    expected, merges, occupied = {}, [], set()
    for r, row in enumerate(table.rows):
        for c, rect in enumerate(row.cells):
            if rect is None:
                continue
            x0, y0, x1, y1 = rect
            if x0 != x_edges[c] or y0 != y_edges[r]:
                raise ValueError("Cell anchor outside the grid")
            r_end, c_end = y_edges.index(y1), x_edges.index(x1)
            slots = {(i, j) for i in range(r, r_end) for j in range(c, c_end)}
            if not slots or occupied & slots:
                raise ValueError("Overlapping source cells")
            occupied.update(slots)
            value = text[r][c] or ""
            expected[r, c] = (r_end-r, c_end-c, "".join(value.split()))
            if len(slots) > 1:
                merges.append((r, c, r_end-1, c_end-1))
            lines = value.splitlines()
            for i, line in enumerate(lines):
                height = (y1-y0) / len(lines)
                cells[r][c].append({"text": line, "bbox": (x0, y0+i*height, x1, y0+(i+1)*height),
                                    "size": min(10.0, height * .8), "font": "HY신명조"})
    if len(occupied) != table.row_count * table.col_count:
        raise ValueError("Incomplete table grid")
    return {"type": "native_table", "bbox": bounds, "grid_bbox": bounds,
            "x_boundaries": x_edges, "y_boundaries": y_edges, "cells": cells,
            "merges": merges}, expected


def _saved_grids(path: Path) -> list[dict]:
    grids = []
    with ZipFile(path) as package:
        root = ElementTree.fromstring(package.read("Contents/section0.xml"))
    for table in root.iterfind(".//{*}tbl"):
        if table.find(".//{*}tbl") is not None:
            continue  # The outer two-column layout also uses a table.
        grid = {}
        for cell in table.iterfind("{*}tr/{*}tc"):
            size = cell.find("{*}cellSz")
            if size.get("width") == "0" and size.get("height") == "0":
                raise ValueError("Unexpected placeholder in output table")
            address, span = cell.find("{*}cellAddr"), cell.find("{*}cellSpan")
            key = int(address.get("rowAddr")), int(address.get("colAddr"))
            if key in grid:
                raise ValueError("Duplicate output cell")
            text = "".join(t.text or "" for t in cell.iterfind(".//{*}t"))
            grid[key] = int(span.get("rowSpan")), int(span.get("colSpan")), "".join(text.split())
        grids.append(grid)
    return grids


def write_ruled_worksheet(source: Path, destination: Path, pdf) -> None:
    from .pdf_layout_writer import write_pdf_flow_hwpx

    grids, expected = [], []
    for page in pdf:
        if page.rect != pdf[0].rect or page.rotation:
            raise ValueError("Mixed page sizes or rotation need review")
        grid, cells = _source_grid(page)
        grids.append(grid)
        expected.append(cells)
    stats = write_pdf_flow_hwpx(source, destination, rasterize_tables=False,
                                boxed_passages=False, preserve_repeated_headers=True,
                                worksheet_grids=grids)
    if (stats["pages"] != len(pdf) or stats["images"]
            or stats["matched_text_char_count"] != stats["source_text_char_count"]
            or _saved_grids(destination) != expected):
        raise ValueError("Editable table content does not match the source")
