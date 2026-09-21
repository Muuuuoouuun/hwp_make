"""Inspect real paragraph boundaries separately from cached visual line breaks.

This is a diagnostic inventory, not a fidelity or semantic-accuracy score.
Usage: python scripts/inspect_hwpx_paragraph_flow.py output.hwpx [more.hwpx]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import zipfile

from lxml import etree

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
NS = {"hp": HP}


def paragraph_text(paragraph):
    # Nested table text belongs to the cell's paragraph, not its container.
    return "".join(paragraph.xpath("./hp:run/hp:t/text()", namespaces=NS)).strip()


def paragraph_units(paragraph):
    units = 0
    for run in paragraph.findall(f"{{{HP}}}run"):
        for child in run:
            if child.tag == f"{{{HP}}}t":
                units += len((child.text or "").encode("utf-16-le")) // 2
                units += len(child)
            elif child.tag in {
                f"{{{HP}}}equation",
                f"{{{HP}}}tbl",
                f"{{{HP}}}pic",
                f"{{{HP}}}rect",
                f"{{{HP}}}ctrl",
            }:
                units += 8
    return units


def paragraph_inventory(paragraphs):
    records = []
    invalid_offsets = []
    for paragraph in paragraphs:
        text = paragraph_text(paragraph)
        if not text:
            continue
        lines = paragraph.findall(f"{{{HP}}}linesegarray/{{{HP}}}lineseg")
        offsets = [int(line.get("textpos", "0")) for line in lines]
        units = paragraph_units(paragraph)
        if offsets and (
            offsets[0] != 0 or offsets != sorted(set(offsets)) or offsets[-1] >= units
        ):
            invalid_offsets.append(
                {"text": text, "offsets": offsets, "text_units": units}
            )
        records.append(
            {"characters": len(text), "cached_lines": len(lines), "text": text}
        )
    return {
        "nonempty_paragraphs": len(records),
        "multiple_visual_lines_in_one_paragraph": sum(
            r["cached_lines"] > 1 for r in records
        ),
        "median_characters": statistics.median(r["characters"] for r in records)
        if records
        else 0,
        "invalid_cache_text_offsets": invalid_offsets,
        "longest_paragraphs": sorted(
            records, key=lambda r: r["characters"], reverse=True
        )[:3],
    }


def inspect(path: Path):
    body, question_body, cells, roots = [], [], [], []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.startswith("Contents/section") and name.endswith(".xml"):
                root = etree.fromstring(archive.read(name))
                roots.append(root)
                body.extend(root.findall(f"{{{HP}}}p"))
                question_body.extend(root.findall(f".//{{{HP}}}drawText/{{{HP}}}subList/{{{HP}}}p"))
                cells.extend(root.findall(f".//{{{HP}}}tc/{{{HP}}}subList/{{{HP}}}p"))
    return {
        "file": str(path.resolve()),
        "draw_text_boxes": sum(
            len(root.findall(f".//{{{HP}}}drawText")) for root in roots
        ),
        "pictures": sum(len(root.findall(f".//{{{HP}}}pic")) for root in roots),
        "body": paragraph_inventory(body),
        "question_body": paragraph_inventory(question_body),
        "table_cells": paragraph_inventory(cells),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(
        [inspect(path) for path in args.files], ensure_ascii=False, indent=2
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(payload)


if __name__ == "__main__":
    main()
