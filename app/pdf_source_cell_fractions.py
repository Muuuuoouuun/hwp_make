"""Flatten source-grid cells containing word fractions into the same native grid."""

from copy import deepcopy
from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def flatten_source_cell_fractions(
    table, header, is_fraction, flatten_one, new_paragraph_id
):
    cells = table.findall(f"{HP}tr/{HP}tc")
    targets = [
        cell
        for cell in cells
        if any(is_fraction(t) for t in cell.findall(f".//{HP}tbl"))
    ]
    if not targets:
        return False

    def address(cell):
        a, s = cell.find(f"{HP}cellAddr"), cell.find(f"{HP}cellSpan")
        return tuple(
            int(node.get(key))
            for node, key in (
                (a, "colAddr"),
                (a, "rowAddr"),
                (s, "colSpan"),
                (s, "rowSpan"),
            )
        )

    def dimensions(cell):
        size = cell.find(f"{HP}cellSz")
        return int(size.get("width")), int(size.get("height"))

    def axes(grid):
        cols, rows = int(grid.get("colCnt")), int(grid.get("rowCnt"))
        widths, heights = [0] * cols, [0] * rows
        cc = grid.findall(f"{HP}tr/{HP}tc")
        for cell in cc:
            col, row, cs, rs = address(cell)
            width, height = dimensions(cell)
            if cs == 1:
                widths[col] = max(widths[col], width)
            if rs == 1:
                heights[row] = max(heights[row], height)
        for _ in range(cols + rows):
            for cell in cc:
                col, row, cs, rs = address(cell)
                width, height = dimensions(cell)
                for values, start, length, total in (
                    (widths, col, cs, width),
                    (heights, row, rs, height),
                ):
                    missing = [i for i in range(start, start + length) if not values[i]]
                    if len(missing) == 1:
                        values[missing[0]] = max(
                            0, total - sum(values[start : start + length])
                        )
        if not all(widths) or not all(heights):
            raise ValueError("source word-fraction grid has unresolved cell boundaries")
        return widths, heights

    widths, heights = axes(table)
    replacements = {}
    for cell in targets:
        col, row, cs, rs = address(cell)
        if rs != 1:
            raise ValueError(
                "word fraction in a vertically merged source cell is not supported"
            )
        wrapper = deepcopy(table)
        for tr in list(wrapper.findall(f"{HP}tr")):
            wrapper.remove(tr)
        wrapper.set("rowCnt", "1")
        wrapper.set("colCnt", "1")
        local = deepcopy(cell)
        local.find(f"{HP}cellAddr").set("colAddr", "0")
        local.find(f"{HP}cellAddr").set("rowAddr", "0")
        local.find(f"{HP}cellSpan").set("colSpan", "1")
        local.find(f"{HP}cellSpan").set("rowSpan", "1")
        cell_width = sum(widths[col : col + cs])
        wrapper.find(f"{HP}sz").set("width", str(cell_width))
        local.find(f"{HP}cellSz").set("width", str(cell_width))
        etree.SubElement(wrapper, f"{HP}tr").append(local)
        host = etree.Element(f"{HP}p", id=new_paragraph_id(), paraPrIDRef="0")
        etree.SubElement(host, f"{HP}run", charPrIDRef="0").append(wrapper)
        flatten_one([host], header, width=cell_width)
        local_widths, local_heights = axes(wrapper)
        if wrapper.findall(f".//{HP}tbl"):
            raise ValueError("source cell fraction remained nested after flattening")
        heights[row] = max(heights[row], sum(local_heights))
        replacements[id(cell)] = wrapper, local_widths, local_heights

    def cumulative(values):
        result = [0]
        for value in values:
            result.append(result[-1] + value)
        return result

    xs, ys = cumulative(widths), cumulative(heights)
    located = []
    for cell in cells:
        col, row, cs, rs = address(cell)
        if min(dimensions(cell)) <= 0:
            continue  # zero-size placeholders covered by an existing merged cell
        if id(cell) not in replacements:
            located.append(
                (deepcopy(cell), xs[col], ys[row], xs[col + cs], ys[row + rs])
            )
            continue
        wrapper, local_widths, local_heights = replacements[id(cell)]
        local_x, local_y = cumulative(local_widths), cumulative(local_heights)
        for child in wrapper.findall(f"{HP}tr/{HP}tc"):
            c, r, cspan, rspan = address(child)
            bounds = (
                xs[col] + round(local_x[c] * (xs[col + cs] - xs[col]) / local_x[-1]),
                ys[row] + round(local_y[r] * heights[row] / local_y[-1]),
                xs[col]
                + round(local_x[c + cspan] * (xs[col + cs] - xs[col]) / local_x[-1]),
                ys[row] + round(local_y[r + rspan] * heights[row] / local_y[-1]),
            )
            copied = deepcopy(child)
            for paragraph in copied.iter(f"{HP}p"):
                paragraph.set("id", new_paragraph_id())
            located.append((copied, *bounds))
    xcuts = sorted({v for _, left, _, right, _ in located for v in (left, right)})
    ycuts = sorted({v for _, _, top, _, bottom in located for v in (top, bottom)})
    for tr in list(table.findall(f"{HP}tr")):
        table.remove(tr)
    rows = [etree.SubElement(table, f"{HP}tr") for _ in range(len(ycuts) - 1)]
    for cell, left, top, right, bottom in sorted(
        located, key=lambda item: (item[2], item[1])
    ):
        col, row = xcuts.index(left), ycuts.index(top)
        addr, span, size = (
            cell.find(f"{HP}cellAddr"),
            cell.find(f"{HP}cellSpan"),
            cell.find(f"{HP}cellSz"),
        )
        addr.set("colAddr", str(col))
        addr.set("rowAddr", str(row))
        span.set("colSpan", str(xcuts.index(right) - col))
        span.set("rowSpan", str(ycuts.index(bottom) - row))
        size.set("width", str(right - left))
        size.set("height", str(bottom - top))
        rows[row].append(cell)
    table.set("colCnt", str(len(xcuts) - 1))
    table.set("rowCnt", str(len(ycuts) - 1))
    table.find(f"{HP}sz").set("height", str(ys[-1]))
    return True
