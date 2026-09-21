"""Restore measured prose beside a figure without fragmenting its paragraphs."""

from copy import deepcopy
from collections import defaultdict
from statistics import median
from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def bounds(layout):
    return layout.get("source_bbox_pt") or (layout.get("source_typography") or {}).get(
        "source_bbox_pt"
    )


def restore_question_sideflow(section, paragraphs, layouts, header, column_width):
    from .pdf_native_typography import _line_cache, _flow_height

    template = section.find(".//" + HP + "tbl")
    if template is None:
        return paragraphs, layouts, 0
    cell_template = deepcopy(template.find(HP + "tr/" + HP + "tc"))
    template = deepcopy(template)
    no_border = next(
        (
            b.get("id")
            for b in header.iter(HH + "borderFill")
            if all(
                (e := b.find(HH + edge + "Border")) is not None
                and e.get("type") == "NONE"
                for edge in ("left", "right", "top", "bottom")
            )
        ),
        None,
    )
    if no_border is None:
        return paragraphs, layouts, 0
    next_id = (
        max(
            (int(e.get("id")) for e in section.iter() if e.get("id", "").isdigit()),
            default=1000000000,
        )
        + 1
    )
    made = 0
    while True:
        selected = None
        for index, (picture, layout) in enumerate(zip(paragraphs, layouts)):
            figure = bounds(layout)
            if (
                not figure
                or not picture.findall(HP + "run/" + HP + "pic")
                or picture.findall(".//" + HP + "tbl")
            ):
                continue
            if any(
                (t.text or "").strip() for t in picture.findall(HP + "run/" + HP + "t")
            ):
                continue
            key = (
                layout.get("question_group"),
                layout.get("source_page"),
                layout.get("source_column"),
            )
            if not key[0]:
                continue
            candidates = []
            for j in range(max(0, index - 4), min(len(paragraphs), index + 5)):
                if j == index:
                    continue
                p, other = paragraphs[j], layouts[j]
                if (
                    other.get("question_group"),
                    other.get("source_page"),
                    other.get("source_column"),
                ) != key:
                    continue
                box = bounds(other)
                if (
                    not box
                    or p.findall(".//" + HP + "tbl")
                    or p.findall(".//" + HP + "pic")
                ):
                    continue
                text = "".join(t.text or "" for t in p.findall(HP + "run/" + HP + "t"))
                if len(text.strip()) < 12 or text.lstrip().startswith(
                    ("①", "②", "③", "④", "⑤")
                ):
                    continue
                overlap = min(box[3], figure[3]) - max(box[1], figure[1])
                if overlap <= 0:
                    continue
                if box[2] <= figure[0] + 1:
                    candidates.append((j, "left"))
                elif box[0] >= figure[2] - 1:
                    candidates.append((j, "right"))
            if not candidates or len({side for _, side in candidates}) != 1:
                continue
            indices = sorted([index] + [j for j, _ in candidates])
            if indices != list(range(indices[0], indices[-1] + 1)):
                continue
            selected = index, candidates[0][1], indices
            break
        if selected is None:
            break
        image_index, text_side, indices = selected
        picture_layout = layouts[image_index]
        figure = bounds(picture_layout)
        scale = float(section.find(".//" + HP + "pagePr").get("width")) / float(
            picture_layout.get("source_page_width_pt") or 842
        )
        left = float(
            picture_layout.get("column_left_pt")
            or min(bounds(layouts[i])[0] for i in indices)
        )
        right = left + column_width / scale
        split = figure[0] if text_side == "left" else figure[2]
        widths = [round((split - left) * scale), round((right - split) * scale)]
        if min(widths) < 1500:
            break
        width = sum(widths)
        start = section.index(paragraphs[indices[0]])
        first_layout = dict(layouts[indices[0]], source_sideflow=True)
        first_layout["question_group_start"] = any(
            layouts[i].get("question_group_start") for i in indices
        )
        table = deepcopy(template)
        for row in table.findall(HP + "tr"):
            table.remove(row)
        table.set("id", str(next_id))
        next_id += 1
        table.set("rowCnt", "1")
        table.set("colCnt", "2")
        table.set("borderFillIDRef", no_border)
        table.find(HP + "pos").set("treatAsChar", "1")
        table.find(HP + "pos").set("affectLSpacing", "1")
        row = etree.SubElement(table, HP + "tr")
        top = min(bounds(layouts[i])[1] for i in indices)
        heights = []
        for col in range(2):
            is_text = col == (0 if text_side == "left" else 1)
            members = [i for i in indices if (i != image_index) == is_text]
            cell = deepcopy(cell_template)
            cell.set(
                "name", f"source-sideflow:{made}:{'text' if is_text else 'figure'}"
            )
            cell.set("borderFillIDRef", no_border)
            cell.set("editable", "1")
            cell.set("hasMargin", "1")
            sub = cell.find(HP + "subList")
            for child in list(sub):
                sub.remove(child)
            sub.set("vertAlign", "TOP")
            cell.find(HP + "cellAddr").set("rowAddr", "0")
            cell.find(HP + "cellAddr").set("colAddr", str(col))
            cell.find(HP + "cellSpan").set("rowSpan", "1")
            cell.find(HP + "cellSpan").set("colSpan", "1")
            margin = cell.find(HP + "cellMargin")
            for edge in ("left", "right", "top", "bottom"):
                margin.set(edge, "0")
            offset = round((min(bounds(layouts[i])[1] for i in members) - top) * scale)
            margin.set("top", str(max(0, offset)))
            # A source glyph bbox can touch a figure's extraction rectangle.
            # Reserve half an em at that boundary so substituted renderer glyphs
            # cannot paint over the adjacent editable picture cell.
            gutter = 0
            if is_text:
                source_edge = (
                    max(bounds(layouts[i])[2] for i in members)
                    if text_side == "left"
                    else min(bounds(layouts[i])[0] for i in members)
                )
                source_gap = (
                    figure[0] - source_edge
                    if text_side == "left"
                    else source_edge - figure[2]
                )
                font_pt = max(
                    float(
                        (layouts[i].get("source_typography") or {}).get("font_size_pt")
                        or 11.21
                    )
                    for i in members
                )
                gutter = round(max(source_gap, font_pt * 0.5) * scale)
                margin.set("right" if text_side == "left" else "left", str(gutter))
            for i in members:
                p = paragraphs[i]
                meta = layouts[i].get("source_typography") or {}
                if is_text:
                    font_height = float(meta.get("font_size_pt") or 11.21) * scale
                    spacing = float(meta.get("letter_spacing_percent") or 0)
                    samples = defaultdict(list)
                    for line in meta.get("lines") or []:
                        for span in line.get("spans") or []:
                            for char in span.get("chars") or []:
                                box = char.get("bbox") or []
                                if len(box) == 4:
                                    samples[char.get("c", "")].append(
                                        max(
                                            1,
                                            (box[2] - box[0]) * scale
                                            + font_height * spacing / 100,
                                        )
                                    )
                    measured = {
                        char: median(values) for char, values in samples.items()
                    }
                    measured.setdefault(" ", font_height * 0.3)
                    _line_cache(
                        p,
                        widths[col] - gutter,
                        font_height,
                        float(meta.get("line_spacing_pt") or 16.7) * scale,
                        measured,
                    )
                else:
                    for line in p.findall(HP + "linesegarray/" + HP + "lineseg"):
                        line.set("horzsize", str(widths[col]))
                p.set("pageBreak", "0")
                p.set("columnBreak", "0")
                sub.append(p)
            height = sum(_flow_height(p) for p in sub.findall(HP + "p")) + max(
                0, offset
            )
            heights.append(height)
            cell.find(HP + "cellSz").set("width", str(widths[col]))
            row.append(cell)
        height = round(max(heights))
        for cell in row:
            cell.find(HP + "cellSz").set("height", str(height))
        table.find(HP + "sz").set("width", str(width))
        table.find(HP + "sz").set("height", str(height))
        wrapper = etree.Element(
            HP + "p",
            id=str(next_id),
            paraPrIDRef=paragraphs[indices[0]].get("paraPrIDRef", "0"),
            styleIDRef="0",
            pageBreak="0",
            columnBreak="0",
            merged="0",
        )
        next_id += 1
        run = etree.SubElement(wrapper, HP + "run", charPrIDRef="0")
        run.append(table)
        _line_cache(wrapper, width, 1, 1, {})
        section.insert(start, wrapper)
        paragraphs = (
            paragraphs[: indices[0]] + [wrapper] + paragraphs[indices[-1] + 1 :]
        )
        layouts = layouts[: indices[0]] + [first_layout] + layouts[indices[-1] + 1 :]
        made += 1
    return paragraphs, layouts, made
