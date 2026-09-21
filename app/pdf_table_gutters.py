"""Keep source row labels beside a real grid as editable borderless cells."""
import re
import fitz


def attach_table_gutters(tables, lines):
    for side in ("left", "right"):
        _attach_side(tables, lines, side)


def _attach_side(tables, lines, side):
    from . import pdf_layout_writer as w

    for table in tables:
        bounds = table.get("cell_bounds") or []
        if not bounds:
            continue
        grid = w._item_bbox(table)
        # A merged grid can have extra physical rows from a neighbouring
        # spacer column. Labels follow the cells on the relevant outside edge.
        row_bounds = {}
        for r, row in enumerate(bounds):
            cells = [fitz.Rect(cell) for cell in row if cell
                     and abs((cell[0] - grid.x0) if side == "left"
                             else (cell[2] - grid.x1)) < .5]
            if len(cells) == 1:
                row_bounds[r] = (cells[0].y0, cells[0].y1)
        if not 3 <= len(row_bounds) <= 6 or 0 not in row_bounds:
            continue
        labels = {}
        for number, (r, (top, bottom)) in enumerate(list(row_bounds.items())[1:], 1):
            matches = []
            for line in lines:
                text = w._pdf_output_text(w._line_text(line)).strip()
                box = w._item_bbox(line)
                distance = grid.x0 - box.x1 if side == "left" else box.x0 - grid.x1
                pattern = r"[①-⑤]" if side == "left" else r"[.…·⋯]*\s*[①-⑤]"
                if (re.fullmatch(pattern, text)
                    and top <= (box.y0 + box.y1) / 2 < bottom
                    and 0 <= distance <= box.height * 1.5):
                    matches.append(line)
            if len(matches) != 1 or w._pdf_output_text(w._line_text(matches[0])).strip()[-1:] != chr(0x2460 + number - 1):
                break
            labels[r] = matches[0]
        if len(labels) != len(row_bounds) - 1:
            continue
        left = min(w._item_bbox(line).x0 for line in labels.values()) if side == "left" else grid.x1
        right = grid.x0 if side == "left" else max(w._item_bbox(line).x1 for line in labels.values())
        table["bbox"] = fitz.Rect(min(left, grid.x0), grid.y0, max(right, grid.x1), grid.y1)
        def add(row, cell):
            return [cell] + row if side == "left" else row + [cell]
        table["cells"] = [add(row, labels[r]["spans"] if r in labels else [])
                          for r, row in enumerate(table["cells"])]
        table["cell_bounds"] = [
            add(row, [left, row_bounds[r][0], right, row_bounds[r][1]] if r in row_bounds else None)
            for r, row in enumerate(bounds)]
        existing = table.get("borderless_columns", [])
        table["borderless_columns"] = (
            [0] + [c + 1 for c in existing] if side == "left"
            else existing + [len(table["cells"][0]) - 1])


def retained_figure_label(line, figures, *, body_font_size=0):
    """Recognize a small label already painted inside a retained illustration.

    A short line alone is not evidence: non-marker labels must also use a
    smaller font than the surrounding body, occupy a small part of the image,
    and have bounded label syntax. Prose and question/choice starts stay native.
    """
    from . import pdf_layout_writer as w

    text = w._pdf_output_text(w._line_text(line)).strip()
    bounds = w._item_bbox(line)
    owners = [w._item_bbox(picture) for picture in figures
              if w._item_bbox(picture).contains(bounds)]
    if not owners:
        return False
    if re.fullmatch(r"[①-⑳]", text):
        return True
    compact = re.sub(r"\s+", "", text)
    sizes = [float(span.get("size", 0)) for span in line.get("spans", [])
             if span.get("text", "").strip()]
    if (not compact or len(compact) > 16 or len(text.split()) > 3
        or len(re.findall(r"[가-힣]", text)) > 8
        or len(re.findall(r"[a-zA-Z]", text)) > 12
        or re.match(r"^(?:\d{1,3}[.)]|[①-⑳]|[ㄱ-ㅎ][.)])", text)
        or re.search(r"[.!?。！？]$", text)
        or not sizes or min(sizes) <= 0 or body_font_size <= 0
        or max(sizes) > body_font_size * .85):
        return False
    return any(bounds.width <= owner.width * .70
               and bounds.height <= owner.height * .25 for owner in owners)
