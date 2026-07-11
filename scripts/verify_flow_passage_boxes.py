from __future__ import annotations

import io
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import fitz
except Exception:
    print("SKIP: PyMuPDF(fitz) unavailable")
    raise SystemExit(2)
from PIL import Image

from app.pdf_layout_writer import (  # noqa: E402
    _merge_flow_images,
    _rail_box_rects,
    write_pdf_flow_hwpx,
)
from scripts.verify_pdf_layout_hwpx import verify  # noqa: E402

HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _make_passage_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((48, 38), "Mock Passage Box Layout", fontsize=12, fontname="helv")
    page.draw_line((48, 56), (540, 56), color=(0, 0, 0), width=0.9)
    page.draw_line((297, 56), (297, 800), color=(0, 0, 0), width=0.8)

    page.insert_text((48, 82), "1. Read the following passage.", fontsize=10, fontname="helv")
    page.insert_text((62, 98), "Continuation lines preserve their source indent.", fontsize=9.5, fontname="times-roman")
    page.draw_rect(fitz.Rect(48, 120, 270, 186), color=(0, 0, 0), width=0.7)
    page.insert_text((62, 134), "A short boxed passage should keep", fontsize=9.5, fontname="times-roman")
    page.insert_text((62, 148), "its inset and compact line rhythm.", fontsize=9.5, fontname="times-roman")

    page.insert_text((310, 82), "2. Read the following passage.", fontsize=10, fontname="helv")
    page.draw_rect(fitz.Rect(310, 120, 540, 446), color=(0, 0, 0), width=0.7)
    for index in range(18):
        y = 136 + index * 16
        page.insert_text(
            (326, y),
            f"This longer passage line {index + 1:02d} checks paragraph alignment.",
            fontsize=9.5,
            fontname="times-roman",
        )
    page.insert_textbox(
        fitz.Rect(350, 460, 500, 480),
        "Centered note",
        fontsize=9.5,
        fontname="times-roman",
        align=1,
    )

    doc.save(str(path))


def _make_split_rail_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for box_index, (top, bottom) in enumerate(
        ((104.0, 210.0), (240.0, 350.0), (380.0, 500.0)),
        start=1,
    ):
        left, right = 310.0, 540.0
        if box_index == 3:
            middle = (left + right) / 2.0
            page.draw_line((left, top), (middle - 18, top), color=(0, 0, 0), width=0.7)
            page.draw_line((middle + 18, top), (right, top), color=(0, 0, 0), width=0.7)
        else:
            page.draw_line((left, top), (right, top), color=(0, 0, 0), width=0.7)
        page.draw_line((left, bottom), (right, bottom), color=(0, 0, 0), width=0.7)
        page.draw_line((left, top), (left, bottom), color=(0, 0, 0), width=0.7)
        page.draw_line((right, top), (right, bottom), color=(0, 0, 0), width=0.7)
        for line_index in range(4):
            page.insert_text(
                (324, top + 18 + line_index * 16),
                f"Rail box {box_index} line {line_index + 1}",
                fontsize=9.5,
                fontname="times-roman",
            )
    doc.save(str(path))


def _verify_same_row_image_merge() -> str | None:
    image = Image.new("RGB", (20, 20), "white")
    payload = io.BytesIO()
    image.save(payload, format="PNG")
    png = payload.getvalue()
    items = [
        {"type": "image", "bbox": fitz.Rect(310, 100, 360, 150), "image": png, "ext": "png"},
        {"type": "image", "bbox": fitz.Rect(368, 102, 418, 151), "image": png, "ext": "png"},
        {"type": "image", "bbox": fitz.Rect(430, 101, 480, 151), "image": png, "ext": "png"},
        {"type": "image", "bbox": fitz.Rect(500, 190, 550, 240), "image": png, "ext": "png"},
    ]
    merged = _merge_flow_images(items)
    if len(merged) != 2:
        return f"expected one same-row composite and one separate image, got {len(merged)}"
    bounds = sorted((fitz.Rect(item["bbox"]) for item in merged), key=lambda rect: rect.y0)
    expected = fitz.Rect(310, 100, 480, 151)
    if any(abs(actual - wanted) > 0.1 for actual, wanted in zip(bounds[0], expected)):
        return f"same-row composite bounds changed: {bounds[0]}"
    return None


def _box_border_ids(header: ET.Element) -> set[str]:
    result: set[str] = set()
    for border in header.findall(f".//{HH}borderFill"):
        borders = [
            border.find(f"{HH}{name}")
            for name in ("leftBorder", "rightBorder", "topBorder", "bottomBorder")
        ]
        if all(
            item is not None
            and item.get("type") == "SOLID"
            and item.get("width") == "0.20 mm"
            and (item.get("color") or "").upper() == "#000000"
            for item in borders
        ):
            result.add(border.get("id") or "")
    return result


def _inspect_boxes(path: Path) -> list[dict[str, object]]:
    with zipfile.ZipFile(path) as archive:
        header = ET.fromstring(archive.read("Contents/header.xml"))
        section = ET.fromstring(archive.read("Contents/section0.xml"))

    border_ids = _box_border_ids(header)
    para_props = {item.get("id") or "": item for item in header.findall(f".//{HH}paraPr")}
    boxes: list[dict[str, object]] = []
    for cell in section.findall(f".//{HP}tc"):
        if (cell.get("borderFillIDRef") or "") not in border_ids:
            continue
        size = cell.find(f"{HP}cellSz")
        margin = cell.find(f"{HP}cellMargin")
        alignments: set[str] = set()
        spacings: set[int] = set()
        for para in cell.findall(f".//{HP}p"):
            prop = para_props.get(para.get("paraPrIDRef") or "")
            if prop is None:
                continue
            align = prop.find(f"{HH}align")
            spacing = prop.find(f".//{HH}lineSpacing")
            if align is not None and align.get("horizontal"):
                alignments.add(str(align.get("horizontal")))
            if spacing is not None and spacing.get("value"):
                spacings.add(int(spacing.get("value") or "0"))
        boxes.append(
            {
                "width": int(size.get("width") or "0") if size is not None else 0,
                "height": int(size.get("height") or "0") if size is not None else 0,
                "margin": tuple(
                    int(margin.get(key) or "0") for key in ("left", "right", "top", "bottom")
                )
                if margin is not None
                else (),
                "alignments": sorted(alignments),
                "spacings": sorted(spacings),
                "vert_align": (
                    cell.find(f"{HP}subList").get("vertAlign")
                    if cell.find(f"{HP}subList") is not None
                    else None
                ),
            }
        )
    return boxes


def _inspect_structural_lines(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        header = ET.fromstring(archive.read("Contents/header.xml"))
        section = ET.fromstring(archive.read("Contents/section0.xml"))

    def ids_for_side(side: str) -> set[str]:
        result: set[str] = set()
        side_names = ("leftBorder", "rightBorder", "topBorder", "bottomBorder")
        for border in header.findall(f".//{HH}borderFill"):
            matches = True
            for name in side_names:
                item = border.find(f"{HH}{name}")
                if item is None:
                    matches = False
                    break
                if name == side:
                    matches = (
                        item.get("type") == "SOLID"
                        and item.get("width") == "0.20 mm"
                        and (item.get("color") or "").upper() == "#000000"
                    )
                else:
                    matches = (item.get("type") or "").upper() == "NONE"
                if not matches:
                    break
            if matches:
                result.add(border.get("id") or "")
        return result

    right_ids = ids_for_side("rightBorder")
    bottom_ids = ids_for_side("bottomBorder")
    cells = section.findall(f".//{HP}tc")
    para_props = {item.get("id") or "": item for item in header.findall(f".//{HH}paraPr")}
    left_margins: list[int] = []
    alignments: list[str] = []
    for paragraph in section.findall(f".//{HP}p"):
        prop = para_props.get(paragraph.get("paraPrIDRef") or "")
        if prop is None:
            continue
        left = prop.find(f"{HH}margin/{HH}left")
        align = prop.find(f"{HH}align")
        if left is not None:
            left_margins.append(int(left.get("value") or "0"))
        if align is not None and align.get("horizontal"):
            alignments.append(str(align.get("horizontal")))
    return {
        "column_divider_cells": sum(
            1 for cell in cells if (cell.get("borderFillIDRef") or "") in right_ids
        ),
        "header_divider_cells": sum(
            1 for cell in cells if (cell.get("borderFillIDRef") or "") in bottom_ids
        ),
        "left_margins": left_margins,
        "alignments": alignments,
    }


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="hwp_make_flow_passage_") as tmp:
        base = Path(tmp)
        pdf_path = base / "passage_boxes.pdf"
        hwpx_path = base / "passage_boxes.hwpx"
        split_rail_path = base / "split_rail_boxes.pdf"
        _make_passage_pdf(pdf_path)
        _make_split_rail_pdf(split_rail_path)
        stats = write_pdf_flow_hwpx(pdf_path, hwpx_path, boxed_passages=True)
        issues = verify(hwpx_path, render=False)
        boxes = _inspect_boxes(hwpx_path)
        structure = _inspect_structural_lines(hwpx_path)
        with fitz.open(split_rail_path) as split_doc:
            rail_boxes = _rail_box_rects(split_doc[0])
        image_merge_issue = _verify_same_row_image_merge()

        if stats.get("boxed_blocks") != 2:
            failures.append(f"expected 2 boxed blocks, got {stats.get('boxed_blocks')}: {stats}")
        if issues:
            failures.append("HWPX verification issues: " + "; ".join(issues[:5]))
        if len(boxes) != 2:
            failures.append(f"expected 2 box cells, got {len(boxes)}: {boxes}")
        if not any(int(box["height"]) < 10000 for box in boxes):
            failures.append(f"missing compact English-style box: {boxes}")
        if not any(int(box["height"]) > 25000 for box in boxes):
            failures.append(f"missing tall passage box: {boxes}")
        if not all(box["margin"] and min(box["margin"]) > 0 for box in boxes):
            failures.append(f"box cell margins were not applied: {boxes}")
        if not any(any(value < 150 for value in box["spacings"]) for box in boxes):
            failures.append(f"compact line spacing was not applied: {boxes}")
        if any(box["vert_align"] == "TOP" for box in boxes):
            failures.append(f"box text uses collapsing TOP cell alignment: {boxes}")
        if len(rail_boxes) != 3:
            failures.append(f"expected 3 split rail boxes, got {len(rail_boxes)}: {rail_boxes}")
        if any(rect.height > 150.0 for rect in rail_boxes):
            failures.append(f"disconnected rail boxes were merged: {rail_boxes}")
        if int(structure["column_divider_cells"]) < 1:
            failures.append(f"missing 0.20 mm black column divider: {structure}")
        if int(structure["header_divider_cells"]) < 1:
            failures.append(f"missing 0.20 mm black header divider: {structure}")
        if max(structure["left_margins"] or [0]) < 900:
            failures.append(f"source continuation indent was not preserved: {structure}")
        if "CENTER" not in structure["alignments"]:
            failures.append(f"source-centered line was not preserved: {structure}")
        if image_merge_issue:
            failures.append(image_merge_issue)

        if failures:
            print("FLOW_PASSAGE_BOXES_FAIL")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        print("FLOW_PASSAGE_BOXES_OK")
        print({"stats": stats, "boxes": boxes, "structure": structure})
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
