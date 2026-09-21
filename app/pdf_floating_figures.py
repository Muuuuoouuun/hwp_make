"""Attach a retained figure to a paragraph whose width changes below it."""
from copy import deepcopy

from .pdf_source_line_cache import apply_source_line_cache, HP


def _attach_picture(paragraph, run, layout, figure, page_width):
    from .pdf_picture_geometry import set_picture_display_size
    meta = layout["source_typography"]
    scale = page_width / layout["source_page_width_pt"]
    left = float(layout.get("column_left_pt") or meta["source_bbox_pt"][0])
    picture = run.find(HP + "pic")
    set_picture_display_size(picture, (figure[2] - figure[0]) * scale, (figure[3] - figure[1]) * scale)
    pos = picture.find(HP + "pos")
    pos.attrib.update({"treatAsChar": "0", "affectLSpacing": "0", "flowWithText": "1",
                       "allowOverlap": "0", "vertRelTo": "PARA", "horzRelTo": "COLUMN",
                       "vertAlign": "TOP", "horzAlign": "LEFT",
                       "horzOffset": str(round((figure[0] - left) * scale)),
                       "vertOffset": str(round((figure[1] - meta["source_bbox_pt"][1]) * scale))})
    picture.set("textWrap", "SQUARE")
    picture.set("textFlow", "BOTH_SIDES")
    beside = [record["bbox_pt"] for record in meta.get("lines", [])
              if min(record["bbox_pt"][3], figure[3]) > max(record["bbox_pt"][1], figure[1])]
    margin = picture.find(HP + "outMargin")
    if beside and margin is not None:
        text_left = all(box[2] <= figure[0] for box in beside)
        gaps = [figure[0] - box[2] if text_left else box[0] - figure[2] for box in beside]
        clearance = max(0, min(min(gaps), float(meta["font_size_pt"])))
        margin.set("left" if text_left else "right", str(round(clearance * scale)))
    text_run = next(r for r in paragraph.findall(HP + "run") if r.find(HP + "t") is not None)
    run.set("charPrIDRef", text_run.get("charPrIDRef", "0"))
    paragraph.insert(0, run)


def restore_floating_figures(section, paragraphs, layouts, width):
    restored = 0
    page_width = float(section.find(".//" + HP + "pagePr").get("width"))
    index = 0
    while index < len(paragraphs):
        holder, source = paragraphs[index], layouts[index]
        pictures = holder.findall(HP + "run/" + HP + "pic")
        figure = source.get("source_bbox_pt")
        if (len(pictures) != 1 or not figure or holder.findall(".//" + HP + "tbl")
            or any((t.text or "").strip() for t in holder.findall(HP + "run/" + HP + "t"))):
            index += 1
            continue
        key = tuple(source.get(k) for k in ("question_group", "source_page", "source_column"))
        selected = None
        for j in (index + 1, index - 1):
            if not 0 <= j < len(paragraphs):
                continue
            layout = layouts[j]
            if not key[0] or key != tuple(layout.get(k) for k in ("question_group", "source_page", "source_column")):
                continue
            meta = layout.get("source_typography") or {}
            records = meta.get("lines") or []
            size = float(meta.get("font_size_pt") or 0)
            sides, below = [], []
            for record in records:
                box = record["bbox_pt"]
                if min(box[3], figure[3]) > max(box[1], figure[1]):
                    sides.append("left" if box[2] <= figure[0] + size * .15
                                 else "right" if box[0] >= figure[2] - size * .15 else "overlap")
                elif box[1] >= figure[3]:
                    below.append(box)
            if (len(sides) < 2 or len(set(sides)) != 1 or sides[0] == "overlap" or not below
                or not any(b[0] < figure[2] - size and b[2] > figure[0] + size for b in below)):
                continue
            probe = deepcopy(paragraphs[j])
            if not apply_source_line_cache(probe, {**layout, "native_page_width": page_width}, width):
                continue
            _attach_picture(probe, deepcopy(pictures[0].getparent()), layout, figure, page_width)
            if not apply_source_line_cache(probe, {**layout, "native_page_width": page_width}, width):
                continue
            selected = j
            break
        if selected is None:
            index += 1
            continue
        paragraph, layout = paragraphs[selected], layouts[selected]
        _attach_picture(paragraph, pictures[0].getparent(), layout, figure, page_width)
        if not apply_source_line_cache(paragraph, {**layout, "native_page_width": page_width}, width):
            raise ValueError("Floating figure paragraph lost source line correspondence")
        layout["question_group_start"] = layout.get("question_group_start") or source.get("question_group_start")
        layout["source_floating_figure"] = True
        section.remove(holder)
        del paragraphs[index]
        del layouts[index]
        restored += 1
    return paragraphs, layouts, restored
