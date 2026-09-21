"""Preserve PDF-encoded Korean word boundaries when joining printed lines."""
from collections import Counter
import re


def raw_line_text(line):
    return "".join(str(span.get("text") or "") for span in line.get("spans", []))


def edge_font(line, *, last=False):
    spans = [s for s in line.get("spans", []) if str(s.get("text") or "").strip()]
    return str(spans[-1 if last else 0].get("font", "")) if spans else ""


def boundary_space_fonts(lines):
    """Require repeated evidence that the PDF retains explicit end spaces.

    PDFs which strip every line ending do not supply this distinction. Keep
    the normal word separator for those inputs instead of guessing language.
    """
    counts = Counter()
    for line in lines:
        raw = raw_line_text(line)
        if len(re.findall(r"[가-힣]", raw)) >= 12 and raw[-1:].isspace():
            counts[edge_font(line, last=True)] += 1
    return {font for font, count in counts.items() if font and count >= 2}


def join_source_paragraph(lines, space_fonts=()):
    from .pdf_layout_writer import _pdf_output_text

    result, previous = "", None
    for line in lines:
        raw = raw_line_text(line)
        text = _pdf_output_text(raw).strip()
        if not text:
            continue
        separator = " "
        if previous is not None:
            previous_line, previous_raw = previous
            if (re.search(r"[가-힣]$", previous_raw)
                and re.match(r"[가-힣]", raw)
                and edge_font(previous_line, last=True) in space_fonts
                and edge_font(previous_line, last=True) == edge_font(line)):
                separator = ""
        result += (separator if result else "") + text
        previous = line, raw
    return result
