"""Recover logical source cells from an actual bordered native fraction grid."""

from collections import defaultdict
import re

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def source_grid_gutter(rows, lines, bounds, *, side="left"):
    """Independently read an ordered choice gutter from individual PDF glyphs."""
    edge_rows = [(i, [c for c in row.cells if c and abs(
        c[0] - bounds.x0 if side == "left" else c[2] - bounds.x1) < .5])
        for i, row in enumerate(rows)]
    edge_rows = [(i, boxes[0]) for i, boxes in edge_rows if len(boxes) == 1]
    if not 3 <= len(edge_rows) <= 6 or edge_rows[0][0] != 0:
        return None
    result, edge = [None] * len(rows), bounds.x0 if side == "left" else bounds.x1
    result[0] = ""
    for index, (row_index, cell) in enumerate(edge_rows[1:]):
        top, bottom = cell[1], cell[3]
        candidates = [char for line in lines for span in line.get("spans", [])
                      for char in span.get("chars", [])
                      if char.get("c", "").strip()
                      and top <= (char["bbox"][1] + char["bbox"][3]) / 2 < bottom
                      and 0 <= (bounds.x0 - char["bbox"][2] if side == "left"
                                else char["bbox"][0] - bounds.x1)
                      <= (char["bbox"][3] - char["bbox"][1]) * (1.5 if side == "left" else 3)]
        candidates.sort(key=lambda char: char["bbox"][0])
        text = "".join(c["c"] for c in candidates)
        expected = chr(0x2460 + index)
        if (text != expected if side == "left" else not re.fullmatch(r"[.…·⋯]*" + expected, text)):
            return None
        result[row_index] = text
        edge = (min(edge, candidates[0]["bbox"][0]) if side == "left"
                else max(edge, candidates[-1]["bbox"][2]))
    return result, edge


def logical_native_grid(table, header, native_text, cell_value):
    cells = table.findall(HP + "tr/" + HP + "tc")
    if header is None or not any(
        c.get("name", "").startswith("fraction:") for c in cells
    ):
        return None
    fills = {f.get("id"): f for f in header.iter(HH + "borderFill")}

    def edge(cell, side):
        fill = fills.get(cell.get("borderFillIDRef"))
        node = fill.find(HH + side + "Border") if fill is not None else None
        if node is None:
            return "unknown"
        if node.get("type") == "NONE":
            return "none"
        width = re.search(r"[\d.]+", node.get("width", ""))
        color = node.get("color", "").upper().lstrip("#")
        return (
            "visible"
            if width and float(width[0]) > 0 and color not in ("", "FFFFFF", "FFFFFFFF")
            else "unknown"
        )

    rows, cols = int(table.get("rowCnt", 0)), int(table.get("colCnt", 0))
    occupancy = {}
    bounds = []
    for index, cell in enumerate(cells):
        addr, span, size = (
            cell.find(HP + x) for x in ("cellAddr", "cellSpan", "cellSz")
        )
        if any(x is None for x in (addr, span, size)):
            return None
        c, r = int(addr.get("colAddr")), int(addr.get("rowAddr"))
        cs, rs = int(span.get("colSpan")), int(span.get("rowSpan"))
        if not (
            0 <= c < c + cs <= cols
            and 0 <= r < r + rs <= rows
            and int(size.get("width")) > 0
            and int(size.get("height")) > 0
        ):
            return None
        bounds.append((c, r, c + cs, r + rs))
        for y in range(r, r + rs):
            for x in range(c, c + cs):
                if (y, x) in occupancy:
                    return None
                occupancy[y, x] = index
    if len(occupancy) != rows * cols:
        return None
    pairs = defaultdict(dict)
    for index, cell in enumerate(cells):
        match = re.fullmatch(
            r"fraction:(.+):(numerator|denominator)", cell.get("name", "")
        )
        if match:
            if match[2] in pairs[match[1]]:
                return None
            pairs[match[1]][match[2]] = index
    for pair in pairs.values():
        if set(pair) != {"numerator", "denominator"}:
            return None
        n, d = pair["numerator"], pair["denominator"]
        a, b = bounds[n], bounds[d]
        if not (a[0] == b[0] and a[2] == b[2] and a[3] == b[1]):
            return None
        if (
            edge(cells[n], "bottom") != "visible"
            or any(edge(cells[n], s) != "none" for s in ("left", "right", "top"))
            or any(
                edge(cells[d], s) != "none" for s in ("left", "right", "top", "bottom")
            )
        ):
            return None
    parents = list(range(len(cells)))

    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    def join(a, b):
        parents[find(a)] = find(b)

    for (r, c), index in occupancy.items():
        for neighbour, side, other_side in (
            ((r, c + 1), "right", "left"),
            ((r + 1, c), "bottom", "top"),
        ):
            other = occupancy.get(neighbour)
            if (
                other is not None
                and other != index
                and edge(cells[index], side) == edge(cells[other], other_side) == "none"
            ):
                join(index, other)
    groups = defaultdict(list)
    for i in range(len(cells)):
        groups[find(i)].append(i)
    regions = []
    for indices in groups.values():
        left, top = (
            min(bounds[i][0] for i in indices),
            min(bounds[i][1] for i in indices),
        )
        right, bottom = (
            max(bounds[i][2] for i in indices),
            max(bounds[i][3] for i in indices),
        )
        if any(
            occupancy[y, x] not in indices
            for y in range(top, bottom)
            for x in range(left, right)
        ):
            return None
        for side, slots in (
            ("left", [(y, left) for y in range(top, bottom)]),
            ("right", [(y, right - 1) for y in range(top, bottom)]),
            ("top", [(top, x) for x in range(left, right)]),
            ("bottom", [(bottom - 1, x) for x in range(left, right)]),
        ):
            if any(edge(cells[occupancy[slot]], side) != "visible" for slot in slots):
                return None
        text = "".join(
            native_text(p)
            for i in sorted(indices, key=lambda j: (bounds[j][1], bounds[j][0]))
            for p in cells[i].findall(HP + "subList/" + HP + "p")
        )
        regions.append((left, top, right, bottom, cell_value(text)))
    xs = sorted({v for left, _, right, _, _ in regions for v in (left, right)})
    ys = sorted({v for _, t, _, b, _ in regions for v in (t, b)})
    matrix = [[None] * (len(xs) - 1) for _ in range(len(ys) - 1)]
    for left, top, _, _, value in regions:
        matrix[ys.index(top)][xs.index(left)] = value
    return {"id": table.get("id"), "cells": matrix}
