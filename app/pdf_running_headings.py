"""Restore repeated source subject names using a real editable section header."""
from __future__ import annotations

from statistics import median
import re

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def measure_running_heading(page, body_top, subject):
    def compact(text):
        return re.sub(r"\s+", "", text)

    if not subject:
        return None
    matches = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            if line["bbox"][3] >= body_top:
                continue
            spans = line["spans"]
            if compact("".join(s.get("text", "") for s in spans)) != compact(subject):
                # A PDF may put the page number, subject and trailing spacing
                # in one line. Select the subject's own spans, never the number.
                spans = [s for s in spans if compact(s.get("text", "")) == compact(subject)]
                if len(spans) != 1:
                    continue
            bounds = [min(s["bbox"][0] for s in spans), min(s["bbox"][1] for s in spans),
                      max(s["bbox"][2] for s in spans), max(s["bbox"][3] for s in spans)]
            matches.append({"spans": spans, "bbox": bounds})
    if len(matches) != 1:
        return None
    line = matches[0]
    from .pdf_running_furniture import measure_running_furniture
    return {"page": page.number + 1, "page_width_pt": page.rect.width,
            "bbox_pt": list(line["bbox"]), "text": subject,
            "furniture": measure_running_furniture(page, body_top, subject),
            "spans": [{"text": s["text"], "size": s["size"], "font": s["font"],
                       "bold": bool(s.get("flags", 0) & 16)} for s in line["spans"]]}


def apply_running_heading(path, records, page_count):
    from .hwpx_writer_v2 import HwpxDocument
    from .pdf_native_typography import _font_name

    evidence = {"applied": False, "source_pages": len(records)}
    # A section header repeats on every following page. Require the source
    # subject on each of those pages before introducing that repetition.
    if (page_count < 2 or len(records) != page_count - 1
        or [r["page"] for r in records] != list(range(2, page_count + 1))
        or len({re.sub(r"\s+", "", r["text"]) for r in records}) != 1):
        return evidence
    document = HwpxDocument.open(path)
    if len(document.sections) != 2:
        return evidence
    section = document.sections[1]
    properties = section.properties
    width = properties.page_size.width
    original = properties.page_margins
    body_top = original.top + original.header
    from .pdf_running_furniture import apply_running_furniture
    furniture = apply_running_furniture(document, records, body_top)
    if furniture is not None:
        document.save_to_path(path)
        return furniture
    heading_top = round(median(r["bbox_pt"][1] / r["page_width_pt"] for r in records) * width)
    source = records[0]
    scale = width / source["page_width_pt"]
    heading_height = max(s["size"] for s in source["spans"]) * scale
    if not 0 <= heading_top < body_top - heading_height:
        return evidence
    document.set_page_margins(section_index=1, top=heading_top, header=body_top-heading_top)
    document.set_header_content([{"align": "CENTER", "runs": [
        {"text": span["text"], "size": span["size"] * scale / 100,
         "font": _font_name(span["font"]), "bold": span["bold"]}
        for span in source["spans"]]}], section_index=1)
    document.save_to_path(path)
    return {"applied": True, "source_pages": len(records), "text": source["text"],
            "body_top_hwp": body_top, "header_top_hwp": heading_top,
            "source_font_faces": sorted({s["font"] for r in records for s in r["spans"]}),
            "page_numbers_restored": False}
