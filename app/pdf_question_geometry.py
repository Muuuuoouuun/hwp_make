"""Check a real question container against its native content geometry.

Some renderers paint overflowing drawing text despite a collapsed shape. A
painted preview therefore does not prove that the editable container is sound.
"""

from __future__ import annotations

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _number(element, attribute):
    if element is None:
        return 0
    try:
        return max(0, int(element.get(attribute, "0")))
    except (TypeError, ValueError):
        return 0


def _paragraph_minimum_height(paragraph):
    lines = paragraph.findall(HP + "linesegarray/" + HP + "lineseg")
    # Final HWPX caches may place every paragraph relative to its subList rather
    # than restarting at zero. Measure each paragraph's own occupied band before
    # adding flow heights, so earlier paragraphs are not counted repeatedly.
    line_height = max(
        (
            _number(line, "vertpos")
            + max(_number(line, "vertsize"), _number(line, "textheight"))
            for line in lines
        ),
        default=0,
    )
    line_height -= min((_number(line, "vertpos") for line in lines), default=0)
    objects = []
    for run in paragraph.findall(HP + "run"):
        for child in run:
            if child.tag in {HP + "pic", HP + "rect", HP + "equation", HP + "tbl", HP + "container"}:
                height = _number(child.find(HP + "sz"), "height")
                pos = child.find(HP + "pos")
                if (child.tag == HP + "pic" and pos is not None
                    and pos.get("treatAsChar") == "0" and pos.get("vertRelTo") == "PARA"):
                    try:
                        height = max(0, height + int(pos.get("vertOffset", "0")))
                    except ValueError:
                        return float("inf")
                if child.tag == HP + "tbl":
                    # An inline table and its anchor line occupy the same flow
                    # position. Cell content provides an independent lower bound
                    # if a table's own declared height was also corrupted.
                    height = max(
                        height,
                        max(
                            (
                                sum(
                                    _paragraph_minimum_height(p)
                                    for p in cell.findall(HP + "subList/" + HP + "p")
                                )
                                for cell in child.findall(HP + "tr/" + HP + "tc")
                            ),
                            default=0,
                        ),
                    )
                objects.append(height)
    return max(line_height, max(objects, default=0))


def inspect_question_geometry(draw):
    sub = draw.find(HP + "subList")
    shape = draw.getparent()
    size = shape.find(HP + "sz") if shape is not None else None
    margin = draw.find(HP + "textMargin")
    required = (
        sum(_paragraph_minimum_height(p) for p in sub.findall(HP + "p"))
        if sub is not None
        else 0
    )
    # Cumulative line positions also include real inter-paragraph whitespace.
    # A collapsed box must fail even if a renderer paints beyond its boundary.
    if sub is not None:
        required = max(required, max((
            _number(line, "vertpos") + max(_number(line, "vertsize"), _number(line, "textheight"))
            for p in sub.findall(HP + "p")
            for line in p.findall(HP + "linesegarray/" + HP + "lineseg")
        ), default=0))
    height = _number(size, "height")
    available = height - _number(margin, "top") - _number(margin, "bottom")
    text_height = _number(sub, "textHeight")
    return {
        "ok": required > 0
        and _number(size, "width") > 0
        and available > 0
        and text_height > 0
        and min(available, text_height) + 4 >= required,
        "id": draw.get("name"),
        "minimum_content_height": required,
        "shape_height": height,
        "available_height": available,
        "text_height": text_height,
    }
