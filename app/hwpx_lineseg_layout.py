"""Read Hancom's own page/column layout back from a Hancom-saved HWPX.

Hancom stores its layout result in every paragraph's ``hp:linesegarray``
(page-local ``vertpos``/``horzpos`` per line). A file re-saved by Hancom (for
example ``scripts/probe_hwp_open.ps1 -ExportHwpxDirectory``) therefore carries
the real page breaks, column moves and line counts, and they can be checked
on any OS without screenshots.

Page boundary rules follow kordoc ``src/hwpx/page-boundary.ts`` (MIT), which
validated them against HWP/HWPX/PDF triples:

1. A top-level ``vertpos`` going backwards starts a new page; in a
   multi-column section only when ``horzpos`` also returns left (otherwise it
   is a column move). An equal ``vertpos`` on a paragraph's first line that
   does not advance ``horzpos`` is also a page start.
2. ``<hp:p pageBreak="1">`` starts a page (counted once with rule 1).
3. A table split across pages restarts its cell flows at 0; the per-row
   maximum of those resets adds page boundaries after the host paragraph.
4. Right after such a table, one backwards move that resumes mid-page
   (``vertpos >= 2000``) is the table tail, not a new page.

Files written by this app carry single placeholder linesegs (all
``vertpos=0``); those are reported as not usable instead of as one page.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree

MIDPAGE_V = 2000
_QUESTION_START_RE = re.compile(r"^\s*(\d{1,3})\s*[.)]")


def _local(element: Any) -> str:
    tag = element.tag
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _children(element: Any, name: str | None = None) -> list[Any]:
    return [child for child in element if name is None or _local(child) == name]


def _num(element: Any, name: str) -> int:
    try:
        return int(float(element.get(name)))
    except (TypeError, ValueError):
        return 0


def _linesegs(paragraph: Any) -> list[Any]:
    for child in paragraph:
        if _local(child) == "linesegarray":
            return _children(child, "lineseg")
    return []


def _cell_flow_resets(sub_list: Any) -> int:
    previous = float("-inf")
    resets = 0
    for paragraph in _children(sub_list, "p"):
        for seg in _linesegs(paragraph):
            value = _num(seg, "vertpos")
            if value < previous:
                resets += 1
            previous = value
    return resets


def _table_intra_breaks(table: Any) -> int:
    row_max: dict[int, int] = {}
    for row in _children(table, "tr"):
        for cell in _children(row, "tc"):
            address = next(iter(_children(cell, "cellAddr")), None)
            row_index = _num(address, "rowAddr") if address is not None else 0
            sub_list = next(iter(_children(cell, "subList")), None)
            if sub_list is None:
                continue
            row_max[row_index] = max(row_max.get(row_index, 0), _cell_flow_resets(sub_list))
    return sum(row_max.values())


def _paragraph_text(paragraph: Any, limit: int = 60) -> str:
    """Lead text of the paragraph itself (not of tables or notes it hosts)."""
    parts: list[str] = []

    def walk(element: Any) -> None:
        for child in element:
            name = _local(child)
            if name in {"tbl", "ctrl", "linesegarray", "equation", "pic", "rect"}:
                continue
            if name == "t":
                parts.append(child.text or "")
                for inner in child:
                    parts.append(inner.tail or "")
                continue
            walk(child)

    walk(paragraph)
    return "".join(parts).strip()[:limit]


@dataclass
class ParagraphPlacement:
    index: int
    page: int
    column: int
    lines: int
    text: str


@dataclass
class SectionLayout:
    name: str
    pages: int
    columns: int
    usable: bool
    placeholder: bool
    paragraphs: list[ParagraphPlacement] = field(default_factory=list)


def analyze_section(root: Any, name: str = "section0") -> SectionLayout:
    col_pr = next((node for node in root.iter() if _local(node) == "colPr"), None)
    column_count = max(1, _num(col_pr, "colCount")) if col_pr is not None else 1
    multi_column = column_count > 1

    placements: list[ParagraphPlacement] = []
    page = 0
    column = 0
    previous_v = float("-inf")
    previous_h = float("-inf")
    first = True
    suppress_mid_reset = False
    top_level = 0
    with_segs = 0
    all_vertpos: list[int] = []

    for index, paragraph in enumerate(_children(root, "p")):
        top_level += 1
        broke_by_explicit = False
        if paragraph.get("pageBreak") == "1" and not first:
            page += 1
            column = 0
            broke_by_explicit = True
            suppress_mid_reset = False
        segs = _linesegs(paragraph)
        if segs:
            with_segs += 1
        paragraph_first = True
        start_page, start_column = page, column
        for seg in segs:
            vertical = _num(seg, "vertpos")
            horizontal = _num(seg, "horzpos")
            all_vertpos.append(vertical)
            if vertical < previous_v:
                new_page = not multi_column or horizontal <= previous_h
                column_move = multi_column and horizontal > previous_h
            else:
                new_page = paragraph_first and vertical == previous_v and horizontal <= previous_h
                column_move = False
            if new_page and not (paragraph_first and broke_by_explicit):
                if not (paragraph_first and suppress_mid_reset and vertical >= MIDPAGE_V):
                    page += 1
                    column = 0
            elif column_move:
                column += 1
            if paragraph_first:
                suppress_mid_reset = False
                start_page, start_column = page, column
            paragraph_first = False
            previous_v, previous_h = vertical, horizontal
        placements.append(
            ParagraphPlacement(index, start_page, start_column, len(segs), _paragraph_text(paragraph))
        )
        first = False
        added = sum(
            _table_intra_breaks(table)
            for run in _children(paragraph, "run")
            for table in _children(run, "tbl")
        )
        if added:
            page += added
            column = 0
            suppress_mid_reset = True

    placeholder = bool(all_vertpos) and all(value == 0 for value in all_vertpos) and top_level > 1
    usable = top_level > 0 and with_segs == top_level and not placeholder
    return SectionLayout(name, page + 1, column_count, usable, placeholder, placements)


def analyze_hwpx(path: Path | str) -> list[SectionLayout]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    layouts: list[SectionLayout] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            (name for name in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", name)),
            key=lambda name: int(re.search(r"(\d+)\.xml$", name).group(1)),
        )
        for name in names:
            root = etree.fromstring(archive.read(name), parser)
            layouts.append(analyze_section(root, name))
    return layouts


def question_positions(layouts: list[SectionLayout]) -> dict[str, dict[str, int]]:
    """First paragraph that starts with ``N.``/``N)`` → its page and column.

    Pages are counted across sections (section pages add up).
    """
    positions: dict[str, dict[str, int]] = {}
    page_offset = 0
    for layout in layouts:
        for placement in layout.paragraphs:
            match = _QUESTION_START_RE.match(placement.text)
            if match and match.group(1) not in positions:
                positions[match.group(1)] = {
                    "page": page_offset + placement.page + 1,
                    "column": placement.column + 1,
                }
        page_offset += layout.pages
    return positions


def summarize(path: Path | str) -> dict[str, Any]:
    layouts = analyze_hwpx(path)
    return {
        "path": str(path),
        "usable": all(layout.usable for layout in layouts) and bool(layouts),
        "placeholder_linesegs": any(layout.placeholder for layout in layouts),
        # Placeholder linesegs carry no layout, so no page count can be read.
        "pages": None if any(layout.placeholder for layout in layouts) else sum(layout.pages for layout in layouts),
        "sections": [
            {"name": layout.name, "pages": layout.pages, "columns": layout.columns, "usable": layout.usable}
            for layout in layouts
        ],
        "questions": question_positions(layouts) if not any(layout.placeholder for layout in layouts) else {},
    }
