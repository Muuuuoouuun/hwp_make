"""Keep every native component of a question inside one editable drawing box."""
from __future__ import annotations

from itertools import groupby
import re
from xml.etree import ElementTree

from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def _source_group(layout: dict) -> tuple[int, int]:
    return (int(layout.get("source_page") or 1), int(layout.get("source_column") or 1))


def wrap_question_units(section, paragraphs, item_layouts, header, width):
    """Move existing paragraphs into one real, identified drawText per question.

    This never renders text into images or adds duplicate proof text. All native
    text, equations, figures and inner tables remain their original XML nodes.
    """
    from hwpx.oxml._document_impl import _create_rectangle_element
    from .hwpx_writer_v2 import _set_paragraph_element_lineseg
    from .pdf_native_typography import _flow_height

    if len(paragraphs) != len(item_layouts):
        raise ValueError("question container paragraph/source mapping is incomplete")
    width = int(round(width))
    if width <= 0:
        raise ValueError("question container width must be positive")
    page = section.find(f".//{HP}pagePr")
    margins = page.find(f"{HP}margin") if page is not None else None
    available = int(page.get("height", "84188")) if page is not None else 84188
    if margins is not None:
        available -= int(margins.get("top", "0")) + int(margins.get("bottom", "0"))
    ids = [int(e.get("id")) for e in section.iter() if str(e.get("id", "")).isdigit()]
    next_id = max(ids, default=1000000000) + 1
    outputs = []
    source_groups = []
    spacing_layouts = []
    seen = set()

    def key(pair):
        _paragraph, layout = pair
        if layout.get("question_group_kind") == "question":
            return layout.get("question_group")
        return None

    for group_id, entries in groupby(zip(paragraphs, item_layouts), key=key):
        entries = list(entries)
        if group_id is None:
            for paragraph, layout in entries:
                outputs.append(paragraph)
                source_groups.append(_source_group(layout))
                spacing_layouts.append([layout])
            continue
        if not re.fullmatch(r"v\d+:q\d{2}", str(group_id)):
            raise ValueError(f"invalid native question group: {group_id}")
        if group_id in seen:
            raise ValueError(f"question {group_id} is split into non-contiguous groups")
        seen.add(group_id)
        first, layout = entries[0]
        from .pdf_question_tables import flatten_question_fraction_tables

        flatten_question_fraction_tables([paragraph for paragraph, _ in entries], header, width=width)
        from .pdf_source_spacing import apply_question_internal_spacing
        from hwpx.tools.paragraph_spacing import paragraph_spacing

        apply_question_internal_spacing(entries, header, float(page.get("width", "59528")) if page is not None else 59528)
        styles = {p.get("id"): p for p in header.iter(HH + "paraPr")}
        height = round(sum(_flow_height(paragraph) + sum(paragraph_spacing(paragraph, styles))
                           for paragraph, _ in entries) + 400)
        if height > available - 1400:
            raise ValueError(
                f"question {group_id} needs {height} HWPUNIT but a page holds "
                f"{available - 1400}; a fixed question text box cannot fit"
            )
        anchor_index = section.index(first)
        outer = etree.Element(
            f"{HP}p", id=str(next_id), paraPrIDRef=first.get("paraPrIDRef", "0"),
            styleIDRef="0", pageBreak="0", columnBreak="0", merged="0",
        )
        # The outer flow receives its own measured spacing below. Do not
        # inherit the first inner paragraph's new after-spacing a second time.
        from .pdf_source_spacing import set_space_after
        set_space_after(outer, header, 0)
        next_id += 1
        first_run = first.find(f"{HP}run")
        run = etree.SubElement(outer, f"{HP}run", charPrIDRef=(first_run.get("charPrIDRef", "0") if first_run is not None else "0"))
        raw_shape = _create_rectangle_element(width, height, line_width="1", fill_color=None, treat_as_char=True)
        shape = etree.fromstring(ElementTree.tostring(raw_shape, encoding="utf-8"))
        shape.set("id", str(next_id))
        shape.set("instid", str(next_id))
        shape.set("zOrder", str(len(seen)))
        shape.set("textWrap", "TOP_AND_BOTTOM")
        shape.set("lock", "0")
        next_id += 1
        line = shape.find(f"{HP}lineShape")
        if line is not None:
            line.set("style", "NONE")
            line.set("alpha", "0")
        number = int(layout.get("question_number") or str(group_id).split("q")[-1])
        comment = shape.find(f"{HP}shapeComment")
        if comment is not None:
            comment.text = f"문항 {number} ({group_id})"
        draw = etree.Element(f"{HP}drawText", lastWidth=str(width), name=f"question:{group_id}", editable="1")
        etree.SubElement(draw, f"{HP}textMargin", left="0", right="0", top="0", bottom="0")
        sub = etree.SubElement(
            draw, f"{HP}subList", id="", textDirection="HORIZONTAL", lineWrap="BREAK",
            vertAlign="TOP", linkListIDRef="0", linkListNextIDRef="0", textWidth=str(width),
            textHeight=str(height), hasTextRef="0", hasNumRef="0",
        )
        for paragraph, _ in entries:
            paragraph.set("pageBreak", "0")
            paragraph.set("columnBreak", "0")
            sub.append(paragraph)
        shadow = shape.find(f"{HP}shadow")
        shape.insert(shape.index(shadow) if shadow is not None else len(shape), draw)
        run.append(shape)
        _set_paragraph_element_lineseg(outer, height, width=width, spacing_ratio=0.0)
        section.insert(anchor_index, outer)
        outputs.append(outer)
        source_groups.append(_source_group(layout))
        spacing_layouts.append([source for _, source in entries])
    from .pdf_masthead_flow import promote_masthead_to_header
    promote_masthead_to_header(section, outputs, spacing_layouts)
    from .pdf_source_spacing import apply_source_flow_spacing
    apply_source_flow_spacing(section, outputs, spacing_layouts, header)
    return outputs, source_groups
