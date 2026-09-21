"""Size real table rows from paragraph content, including merged cells."""
from collections import deque
from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _number(node, name, default=0):
    return float(node.get(name, default)) if node is not None else default


def _cells(table):
    count = int(table.get("rowCnt", "0"))
    for cell in table.findall(HP + "tr/" + HP + "tc"):
        size, addr, span = (cell.find(HP + name) for name in ("cellSz", "cellAddr", "cellSpan"))
        if _number(size, "width") <= 0:
            continue  # Covered placeholders are not additional cells.
        start = int(_number(addr, "rowAddr", -1))
        end = start + int(_number(span, "rowSpan", 1))
        if not 0 <= start < end <= count:
            raise ValueError("native table cell has an invalid row span")
        yield cell, start, end


def _existing_rows(table, cells):
    """Recover shared row boundaries from actual cell sizes, not their maxima.

    Taking the maximum cell height in each row counts a spanning cell multiple
    times. Difference edges recover the exact original boundaries instead.
    """
    count = int(table.get("rowCnt"))
    edges = [[] for _ in range(count + 1)]
    for cell, start, end in cells:
        height = _number(cell.find(HP + "cellSz"), "height")
        edges[start].append((end, height))
        edges[end].append((start, -height))
    positions = {0: 0.0}
    queue = deque([0])
    while queue:
        start = queue.popleft()
        for end, delta in edges[start]:
            value = positions[start] + delta
            if end in positions:
                if abs(positions[end] - value) > 2:
                    raise ValueError("inconsistent native merged-cell heights")
            else:
                positions[end] = value
                queue.append(end)
    if count not in positions:
        raise ValueError("native table rows do not cover the table")
    # Internal boundaries with no cell edge have no independent visible rule.
    # Divide that interval equally without changing any existing cell height.
    known = sorted(positions)
    for start, end in zip(known, known[1:]):
        for index in range(start + 1, end):
            positions[index] = positions[start] + (positions[end] - positions[start]) * (index - start) / (end - start)
    rows = [round(positions[i + 1]) - round(positions[i]) for i in range(count)]
    if min(rows, default=0) < 0:
        raise ValueError("native table row boundaries are reversed")
    return rows


def fit_table_rows(table, measure_paragraph, *, grow_only=False):
    """Meet every cell's content requirement without changing ownership/spans."""
    cells = list(_cells(table))
    count = int(table.get("rowCnt", "0"))
    if not count or not cells:
        return
    rows = _existing_rows(table, cells) if grow_only else [800] * count
    for cell, start, end in sorted(cells, key=lambda item: item[2] - item[1]):
        sub = cell.find(HP + "subList")
        margins = cell.find(HP + "cellMargin")
        height = sum(measure_paragraph(p) for p in sub.findall(HP + "p")) if sub is not None else 0
        required = round(height + _number(margins, "top") + _number(margins, "bottom") + 200)
        deficit = max(0, required - sum(rows[start:end]))
        step, remainder = divmod(deficit, end - start)
        for i in range(start, end):
            rows[i] += step + (i - start < remainder)
    for cell, start, end in cells:
        cell.find(HP + "cellSz").set("height", str(sum(rows[start:end])))
    height = sum(rows)
    table.find(HP + "sz").set("height", str(height))

    # A table-only anchor's previous estimate must not keep its question box
    # hundreds of points taller after the actual merged table has been fitted.
    run = table.getparent()
    parent = run.getparent() if run is not None else None
    if parent is None or parent.tag != HP + "p":
        return
    if any((t.text or "").strip() for t in parent.findall(HP + "run/" + HP + "t")):
        return
    objects = [n for r in parent.findall(HP + "run") for n in r
               if n.tag in {HP + name for name in ("tbl", "pic", "rect", "equation")}]
    if len(objects) != 1 or objects[0] is not table:
        return
    cache = parent.find(HP + "linesegarray")
    if cache is None:
        cache = etree.SubElement(parent, HP + "linesegarray")
    for child in list(cache):
        cache.remove(child)
    height += 400
    etree.SubElement(cache, HP + "lineseg", textpos="0", vertpos="0",
                     vertsize=str(height), textheight=str(height), baseline=str(round(height * .85)),
                     spacing="0", horzpos="0", horzsize=table.find(HP + "sz").get("width"), flags="393216")
