"""Prove open outer grid cells from source rules, without inventing merges."""
from __future__ import annotations

import fitz


def source_grid_cell_bounds(page, grid, drawings=None):
    """Return detected cells, recovering only ruled, unmerged outer slots.

    ``find_tables`` can omit the first/last data column when the table has no
    outer vertical rules. A complete detected row supplies column boundaries;
    both horizontal edges and the inner vertical edge must exist in the PDF.
    A source cell spanning the candidate slot always prevents recovery.
    """
    original = [[tuple(cell) if cell else None for cell in row.cells]
                for row in grid.rows]
    if len(original) < 2 or grid.col_count < 3:
        return original
    complete = next((row for row in original if all(row)), None)
    if complete is None:
        return original
    tolerance = .5
    xs = [complete[0][0]] + [cell[2] for cell in complete]
    if any(abs(cell[0] - xs[col]) > tolerance or cell[2] <= cell[0]
           for col, cell in enumerate(complete)):
        return original
    segments = []
    for drawing in page.get_drawings() if drawings is None else drawings:
        color = drawing.get("color")
        if ("s" not in drawing.get("type", "")
            or not drawing.get("width") or drawing.get("stroke_opacity", 0) <= 0
            or color is None or min(color) >= .8
            or drawing.get("dashes") not in (None, "", "[] 0")):
            continue
        for item in drawing.get("items", []):
            if item[0] == "l":
                segments.append((*item[1], *item[2]))
            elif item[0] == "re":
                x0, y0, x1, y1 = item[1]
                segments.extend(((x0, y0, x1, y0), (x0, y1, x1, y1),
                                 (x0, y0, x0, y1), (x1, y0, x1, y1)))

    measured = _complete_ruled_grid(original, xs, segments, tolerance)
    if measured is not None:
        return measured

    def ruled(a, b, vertical=False):
        # One uninterrupted original segment proves this edge. Do not bridge
        # a missing separator, a dashed rule, or a gap inside a merged cell.
        for x0, y0, x1, y1 in segments:
            if vertical:
                if (abs(x0 - a[0]) <= tolerance and abs(x1 - a[0]) <= tolerance
                    and min(y0, y1) <= a[1] + tolerance
                    and max(y0, y1) >= b[1] - tolerance):
                    return True
            elif (abs(y0 - a[1]) <= tolerance and abs(y1 - a[1]) <= tolerance
                  and min(x0, x1) <= a[0] + tolerance
                  and max(x0, x1) >= b[0] - tolerance):
                return True
        return False

    result = [row[:] for row in original]
    source_cells = [fitz.Rect(cell) for row in original for cell in row if cell]
    for row_index, row in enumerate(original):
        present = [(col, cell) for col, cell in enumerate(row) if cell]
        if not present:
            continue
        top, bottom = present[0][1][1], present[0][1][3]
        if any(abs(cell[0] - xs[col]) > tolerance
               or abs(cell[2] - xs[col + 1]) > tolerance
               or abs(cell[1] - top) > tolerance
               or abs(cell[3] - bottom) > tolerance for col, cell in present):
            continue
        for col in (0, len(row) - 1):
            if row[col] is not None:
                continue
            candidate = fitz.Rect(xs[col], top, xs[col + 1], bottom)
            if candidate.is_empty or any((candidate & cell).get_area() > tolerance
                                         for cell in source_cells):
                continue
            inner = candidate.x1 if col == 0 else candidate.x0
            if (ruled(candidate.tl, candidate.tr)
                and ruled(candidate.bl, candidate.br)
                and ruled((inner, top), (inner, bottom), vertical=True)):
                result[row_index][col] = tuple(candidate)
    return result


def _complete_ruled_grid(original, xs, segments, tolerance):
    """Use one unique original rule chain when detector row joints drift.

    This does not widen the missing-edge tolerance. Every horizontal separator
    must span the whole grid and every inner vertical rail must span its whole
    height, so no merged source cell can be reconstructed as separate slots.
    """
    if any(cell is None for row in original for cell in row[1:-1]):return None
    present=[cell for row in original for cell in row if cell]
    top,bottom=min(cell[1] for cell in present),max(cell[3] for cell in present)
    rules=[]
    for x0,y0,x1,y1 in segments:
        if (abs(y0-y1)<=tolerance and min(x0,x1)<=xs[0]+tolerance
            and max(x0,x1)>=xs[-1]-tolerance and top-tolerance<=y0<=bottom+tolerance):
            if not any(abs(y0-old)<=tolerance for old in rules):rules.append(y0)
    rules.sort()
    if (len(rules)!=len(original)+1 or abs(rules[0]-top)>tolerance
        or abs(rules[-1]-bottom)>tolerance):return None
    for x in xs[1:-1]:
        if not any(abs(a-x)<=tolerance and abs(c-x)<=tolerance
                   and min(b,d)<=top+tolerance and max(b,d)>=bottom-tolerance
                   for a,b,c,d in segments):return None
    result=[]
    for r,row in enumerate(original):
        # Both ends of each detected cell must select this same unique source
        # band. A broad box or a real row span remains rejected.
        allowance=min(1.5,(rules[r+1]-rules[r])*.1)
        if rules[r+1]<=rules[r] or any(cell is not None and (
            abs(cell[0]-xs[c])>tolerance or abs(cell[2]-xs[c+1])>tolerance
            or abs(cell[1]-rules[r])>allowance or abs(cell[3]-rules[r+1])>allowance)
            for c,cell in enumerate(row)):
            return None
        result.append([(xs[c],rules[r],xs[c+1],rules[r+1]) for c in range(len(row))])
    return result
