"""HWP output fidelity: prepare HWPX for rhwp's HWP writer, then prove the result.

rhwp's own ``convert --verify`` re-parses the HWP into rhwp IR, which has no
text boxes, paragraph shapes or fills, so it cannot see every loss. This
module adds two things around ``rhwp convert``:

1. **Preparation.** Two HWPX spellings that rhwp 0.8.7 misreads are rewritten
   in a temporary copy before conversion:

   - ``hc:imgBrush mode="TOTAL"`` (fit the picture to the area, HWP 5.0 image
     fill type 5) is unknown to rhwp's HWPX reader, which falls back to
     tiling (type 0). The framed letter boxes of English exams then repeat as
     a band and lose their frame. rhwp reads its own name for type 5,
     ``FIT``, correctly, so ``TOTAL`` becomes ``FIT``. (Measured 2026-10-14:
     rhwp also ignores ``LEFT_*``/``RIGHT_*``; this app never writes them and
     the check below refuses an HWP that lost them.)
   - A run-less ``hp:p`` (an empty table cell) gets an empty run. HWP 5.0
     stores at least one character shape per paragraph and Hancom always
     writes a run; without one rhwp invents shape 0 and its own re-parse
     check fails.

2. **Independent check.** The HWP is exported back to HWPX by rhwp and
   compared with the original HWPX: text, tables and merged cells, text
   boxes, pictures, equations, object sizes/positions, paragraph shapes, line
   layout and image fill modes. Any difference refuses the HWP.
"""
from __future__ import annotations

import collections
import re
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)


def _local(element: Any) -> str:
    tag = element.tag
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


# --- HWPX preparation before conversion ------------------------------------------

# OWPML image fill names rhwp's HWPX reader does not know → the name it reads
# for the same HWP 5.0 fill type.
RHWP_FILL_ALIASES = {"TOTAL": "FIT"}


def _alias_image_fills(root: Any) -> int:
    count = 0
    for node in root.iter():
        if _local(node) == "imgBrush" and node.get("mode") in RHWP_FILL_ALIASES:
            node.set("mode", RHWP_FILL_ALIASES[node.get("mode")])
            count += 1
    return count


def _give_bare_paragraphs_a_run(root: Any) -> int:
    """Insert an empty run into run-less paragraphs.

    The run takes the character shape of the nearest following run (the
    neighbouring cell), else the nearest previous one.
    """
    elements = list(root.iter())
    positions = [
        (index, node) for index, node in enumerate(elements)
        if _local(node) == "run" and node.get("charPrIDRef")
    ]
    bare = [
        (index, node) for index, node in enumerate(elements)
        if _local(node) == "p" and not any(_local(child) == "run" for child in node)
    ]
    for here, paragraph in bare:
        following = next((run for at, run in positions if at > here), None)
        previous = next((run for at, run in reversed(positions) if at < here), None)
        reference = following if following is not None else previous
        namespace = paragraph.tag.rsplit("}", 1)[0] + "}" if "}" in paragraph.tag else ""
        run = etree.Element(f"{namespace}run", charPrIDRef=reference.get("charPrIDRef") if reference is not None else "0")
        paragraph.insert(0, run)
    return len(bare)


def normalize_for_hwp(source: Path, target: Path) -> dict[str, int]:
    """Copy ``source`` to ``target`` in the spelling rhwp's HWP writer reads.

    Returns how many image fills were renamed and empty paragraphs given a run.
    """
    fills = paragraphs = 0
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(target, "w") as output:
        for info in archive.infolist():
            data = archive.read(info.filename)
            section = re.fullmatch(r"Contents/section\d+\.xml", info.filename) is not None
            if section or info.filename == "Contents/header.xml":
                root = etree.fromstring(data, _PARSER)
                renamed = _alias_image_fills(root)
                given = _give_bare_paragraphs_a_run(root) if section else 0
                if renamed or given:
                    fills += renamed
                    paragraphs += given
                    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            output.writestr(info, data)
    return {"image_fills": fills, "empty_paragraphs": paragraphs}


# --- Independent structure check -------------------------------------------------

_COUNTED = (
    "p", "tbl", "tc", "rect", "drawText", "pic", "equation", "container", "line",
    "ellipse", "arc", "polygon", "curve", "ole", "colPr", "lineseg", "footNote", "endNote",
    "header", "footer", "pageNum", "autoNum",
)
_PLACED = ("rect", "pic", "tbl", "equation", "container", "line", "ellipse", "arc", "polygon", "curve")


def _fill_mode(node: Any) -> str:
    # rhwp names HWP image fill type 5 "FIT"; OWPML calls it TOTAL.
    mode = node.get("mode") or ""
    return next((name for name, alias in RHWP_FILL_ALIASES.items() if alias == mode), mode)


def _char_shape(char_pr: Any) -> tuple[Any, ...]:
    """Content of a charPr without its id, order-free.

    rhwp writes an explicit ``strikeout shape="NONE"`` into every character
    shape; that default carries no meaning and is ignored.
    """
    parts = []
    for node in char_pr.iter():
        name = _local(node)
        if not name:
            continue
        attrs = tuple(sorted((key.rsplit("}", 1)[-1], value) for key, value in node.attrib.items() if key != "id"))
        if name == "strikeout" and ("shape", "NONE") in attrs:
            continue
        parts.append((name, attrs))
    return tuple(sorted(parts))


def structure_profile(hwpx: Path) -> dict[str, Any]:
    counts: collections.Counter[str] = collections.Counter()
    text: list[str] = []
    scripts: list[str] = []
    placements: list[tuple[Any, ...]] = []
    spans: list[tuple[str | None, ...]] = []
    paragraphs: list[tuple[str | None, ...]] = []
    linesegs: list[tuple[str | None, ...]] = []
    fills: collections.Counter[str] = collections.Counter()
    with zipfile.ZipFile(hwpx) as archive:
        names = archive.namelist()
        bindata = sum(1 for name in names if name.startswith("BinData/"))
        sections = sorted(
            (name for name in names if re.fullmatch(r"Contents/section\d+\.xml", name)),
            key=lambda name: int(re.search(r"(\d+)\.xml$", name).group(1)),
        )
        parts = [etree.fromstring(archive.read(name), _PARSER) for name in sections]
        header = etree.fromstring(archive.read("Contents/header.xml"), _PARSER)
    char_shapes: dict[str | None, tuple[Any, ...]] = {}
    for node in header.iter():
        name = _local(node)
        if name == "imgBrush":
            fills[_fill_mode(node)] += 1
        elif name == "charPr":
            char_shapes[node.get("id")] = _char_shape(node)
    # Character shape of every visible character, run-length encoded. Shapes
    # are compared by content because a writer may renumber them.
    shaped: list[list[Any]] = []
    for root in parts:
        for node in root.iter():
            name = _local(node)
            if not name:
                continue
            if name in _COUNTED:
                counts[name] += 1
            if name == "t":
                piece = "".join(node.itertext())
                text.append(piece)
                run = node.getparent()
                shape = char_shapes.get(run.get("charPrIDRef")) if run is not None else None
                visible = sum(1 for char in piece if not char.isspace())
                if visible:
                    if shaped and shaped[-1][0] == shape:
                        shaped[-1][1] += visible
                    else:
                        shaped.append([shape, visible])
            elif name == "script":
                scripts.append(re.sub(r"\s+", " ", node.text or "").strip())
            elif name == "imgBrush":
                fills[_fill_mode(node)] += 1
            elif name == "cellSpan":
                spans.append((node.get("colSpan"), node.get("rowSpan")))
            elif name == "p":
                paragraphs.append((node.get("paraPrIDRef"), node.get("pageBreak"), node.get("columnBreak")))
            elif name == "lineseg":
                linesegs.append(tuple(node.get(key) for key in ("textpos", "vertpos", "vertsize", "horzpos", "horzsize")))
            if name in _PLACED:
                size = next((child for child in node if _local(child) == "sz"), None)
                pos = next((child for child in node if _local(child) == "pos"), None)
                placements.append(
                    (
                        name,
                        size.get("width") if size is not None else None,
                        size.get("height") if size is not None else None,
                        pos.get("vertOffset") if pos is not None else None,
                        pos.get("horzOffset") if pos is not None else None,
                        pos.get("treatAsChar") if pos is not None else None,
                    )
                )
    return {
        "counts": dict(counts),
        "text": re.sub(r"\s+", "", "".join(text)),
        "equations": scripts,
        "placements": placements,
        "cell_spans": spans,
        "paragraphs": paragraphs,
        "linesegs": linesegs,
        "image_fills": dict(fills),
        "char_shapes": shaped,
        "bindata": bindata,
    }


def compare_profiles(source: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """Readable differences that change what a teacher sees or edits."""
    problems: list[str] = []
    for name in _COUNTED:
        a, b = source["counts"].get(name, 0), result["counts"].get(name, 0)
        if a != b:
            problems.append(f"{name} {a}→{b}")
    if source["text"] != result["text"]:
        problems.append(f"본문 글자 {len(source['text'])}→{len(result['text'])}자")
    if source["equations"] != result["equations"]:
        problems.append(f"수식 스크립트 {len(source['equations'])}→{len(result['equations'])}개 중 불일치")
    for key, label in (
        ("placements", "개체 크기·위치"),
        ("cell_spans", "표 병합"),
        ("paragraphs", "문단 모양 연결"),
        ("linesegs", "줄 배치"),
        ("image_fills", "그림 채우기 방식"),
        ("char_shapes", "글자 모양"),
    ):
        if source[key] != result[key]:
            problems.append(label)
    if source["bindata"] != result["bindata"]:
        problems.append(f"그림 데이터 {source['bindata']}→{result['bindata']}")
    return problems
