"""Check source line wraps against real HWPX paragraph boundaries.

The PDF geometry supplies wrap evidence. Writer grouping labels and line-cache
counts alone cannot prove that a passage is one editable paragraph.
"""
from __future__ import annotations

from pathlib import Path
from collections import Counter
import re
import zipfile

import fitz
from lxml import etree

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
LABEL = re.compile(r"^(?:[①-⑳㉠-㉻↳↪→]|\d{1,2}[.)]|[ㄱ-ㅎ][.)]|\([가-힣A-Za-z0-9]\)|[\[［<〈※○●•]|[-–]\s)")


def compact(text):
    return re.sub(r"[\s\u200b]+", "", text)


def inspect_paragraph_flow(source: Path, output: Path, *, page_limit=None) -> dict:
    from . import pdf_layout_writer as w

    paragraphs, invalid, raw_paragraphs = [], [], []
    with zipfile.ZipFile(output) as archive:
        for name in archive.namelist():
            if not re.fullmatch(r"Contents/section\d+\.xml", name):
                continue
            root = etree.fromstring(archive.read(name))
            for p in root.iter(HP + "p"):
                from .pdf_editability import _compact_text
                text = "".join((child.text or "") if child.tag == HP + "t"
                               else _compact_text(child.findtext(HP + "script", ""))
                               for run in p.findall(HP + "run") for child in run
                               if child.tag in {HP + "t", HP + "equation"})
                if not text.strip():
                    continue
                breaks = bool(p.findall(HP + "run/" + HP + "t/" + HP + "lineBreak")
                              or p.findall(HP + "run/" + HP + "lineBreak"))
                paragraphs.append((_compact_text(text), breaks))
                raw_paragraphs.append(text)
                prose = "".join(t.text or "" for t in p.findall(HP + "run/" + HP + "t"))
                if prose != text:
                    # Inline equations are independently compared against the
                    # source. Their presence must not defeat paragraph proof.
                    paragraphs.append((_compact_text(prose), breaks))
                units = sum(len((t.text or "").encode("utf-16-le")) // 2
                            + sum(8 if child.tag == HP + "tab" else 1 for child in t)
                            for t in p.findall(HP + "run/" + HP + "t"))
                units += 8 * sum(child.tag in {HP + tag for tag in ("equation", "tbl", "pic", "rect", "ctrl", "tab")}
                                 for run in p.findall(HP + "run") for child in run)
                units += sum(child.tag == HP + 'lineBreak' for run in p.findall(HP + 'run') for child in run)
                offsets = [int(line.get("textpos", "0")) for line in p.findall(HP + "linesegarray/" + HP + "lineseg")]
                if offsets and (offsets[0] != 0 or offsets != sorted(set(offsets)) or offsets[-1] >= units):
                    invalid.append({"section": name, "paragraph": p.get("id"), "offsets": offsets, "units": units})

    checked, fragmented, missing, hard_breaks = 0, [], [], []
    boundaries_checked, spacing_errors = 0, []
    with fitz.open(source) as document:
        for page_index in range(min(len(document), page_limit or len(document))):
            page = document[page_index]
            body_top = w._page_body_top(page)
            candidates = []
            explicit_end_spaces = Counter()
            for line in w._iter_text_lines(page):
                rect = w._item_bbox(line)
                raw = "".join(s.get("text", "") for s in line["spans"])
                spans = [s for s in line["spans"] if s.get("text", "").strip()]
                first_font = spans[0].get("font", "") if spans else ""
                last_font = spans[-1].get("font", "") if spans else ""
                if (rect.y0 >= body_top and not w._is_flow_footer_line(page, line)
                    and len(re.findall(r"[가-힣]", raw)) >= 12 and raw[-1:].isspace()):
                    explicit_end_spaces[last_font] += 1
                text = w._pdf_output_text("".join(s.get("text", "") for s in line["spans"]
                                               if not w.is_hancom_eq_font(str(s.get("font", ""))))).strip()
                if (rect.y0 < body_top or w._is_flow_footer_line(page, line)
                        or len(compact(text)) < 12 or rect.width < page.rect.width * 0.18):
                    continue
                mixed_math = any(w.is_hancom_eq_font(str(s.get("font", ""))) for s in line["spans"])
                candidates.append((rect, text, w._line_median_font_size(line), mixed_math,
                                   raw, first_font, last_font))
            for column in (0, 1):
                lines = sorted((x for x in candidates if int(x[0].x0 >= page.rect.width / 2) == column), key=lambda x: (x[0].y0, x[0].x0))
                right_edge = max((entry[0].x1 for entry in lines), default=0)
                for (a, first, size, math_a, raw_a, _, end_font), (b, second, next_size, math_b, raw_b, start_font, _) in zip(lines, lines[1:]):
                    if (LABEL.match(second) or not 0.8 * size <= next_size <= 1.2 * size
                            or not size * 0.9 <= b.y0 - a.y0 <= size * 2.0
                            or abs(b.x0 - a.x0) > size * 0.45
                            or abs(b.x1 - a.x1) > size * 2
                            or min(a.x1, b.x1) < right_edge - size * 2.5):
                        continue
                    # Two equally full consecutive prose lines: punctuation
                    # at their right margin is not a paragraph boundary.
                    first, second = _compact_text(first), _compact_text(second)
                    compared = paragraphs
                    if math_a or math_b:
                        # Hangul prose across inline equations is the anchor;
                        # the independent math gate checks the omitted atoms.
                        first, second = [re.sub(r"[^가-힣]", "", t) for t in (first, second)]
                        if min(len(first), len(second)) < 12:
                            continue
                        compared = [(re.sub(r"[^가-힣]", "", t), hard) for t, hard in paragraphs]
                    else:
                        # Printed marginal [A] labels can sit between two
                        # source lines within the same valid native paragraph.
                        compared = [(re.sub(r"\[[A-Z]\]", "", t), hard) for t, hard in paragraphs]
                    checked += 1
                    record = {"page": page_index + 1, "bbox": list(a | b), "first": first, "second": second}
                    # This gate proves paragraph membership, not adjacency of
                    # extracted spans. A source marginal label or separate
                    # Roman numeral can legitimately occur between the two
                    # prose anchors. Keep their order and require the SAME
                    # actual native paragraph; content gates check the atoms.
                    matches = [
                        hard for text, hard in compared
                        if (start := text.find(first)) >= 0
                        and text.find(second, start + len(first)) >= 0
                    ]
                    if matches:
                        if all(matches):
                            hard_breaks.append(record)
                    elif any(first in text for text, _ in compared) and any(second in text for text, _ in compared):
                        fragmented.append(record)
                    else:
                        missing.append(record)
                    # Whitespace-free matching above cannot detect a word
                    # split such as "극히" -> "극 히". Read original span endings
                    # independently from the writer's paragraph-join decisions.
                    if (not math_a and not math_b and end_font == start_font
                        and explicit_end_spaces[end_font] >= 2
                        and re.search(r"[가-힣]$", raw_a.strip())
                        and re.match(r"[가-힣]", raw_b.strip())):
                        pattern = (r"\s*".join(map(re.escape, first[-12:]))
                                   + r"(?P<gap>\s*)"
                                   + r"\s*".join(map(re.escape, second[:12])))
                        observed = [bool(m["gap"]) for text in raw_paragraphs
                                    for m in re.finditer(pattern, text)]
                        if observed:
                            boundaries_checked += 1
                            expected_space = raw_a[-1:].isspace() or raw_b[:1].isspace()
                            if any(space != expected_space for space in observed):
                                spacing_errors.append({**record, "expected_space": expected_space})
    issues = []
    for code, records in (("source_paragraph_split_at_visual_line", fragmented),
                          ("source_paragraph_text_missing", missing),
                          ("source_paragraph_uses_hard_line_breaks", hard_breaks),
                          ("source_paragraph_word_spacing_changed", spacing_errors),
                          ("invalid_paragraph_line_cache", invalid)):
        if records:
            issues.append(code)
    return {"ok": not issues, "issues": issues, "source_wrap_pairs_checked": checked,
            "fragmented_paragraphs": fragmented, "missing_text": missing,
            "hard_line_breaks": hard_breaks, "invalid_cache_offsets": invalid,
            "source_word_boundaries_checked": boundaries_checked,
            "word_spacing_mismatches": spacing_errors,
            "scope": "adjacent aligned prose lines near the column margin; Korean boundary spaces checked where source end-space evidence is repeated; inline equations checked separately; short poetry/list/sideflow lines are not inferred"}
