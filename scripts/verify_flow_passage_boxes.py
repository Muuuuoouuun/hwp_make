from __future__ import annotations

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

from app.pdf_layout_writer import write_pdf_flow_hwpx  # noqa: E402
from scripts.verify_pdf_layout_hwpx import verify  # noqa: E402

HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _make_passage_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((48, 38), "Mock Passage Box Layout", fontsize=12, fontname="helv")

    page.insert_text((48, 82), "1. Read the following passage.", fontsize=10, fontname="helv")
    page.draw_rect(fitz.Rect(48, 104, 270, 170), color=(0, 0, 0), width=0.7)
    page.insert_text((62, 118), "A short boxed passage should keep", fontsize=9.5, fontname="times-roman")
    page.insert_text((62, 132), "its inset and compact line rhythm.", fontsize=9.5, fontname="times-roman")

    page.insert_text((310, 82), "2. Read the following passage.", fontsize=10, fontname="helv")
    page.draw_rect(fitz.Rect(310, 104, 540, 430), color=(0, 0, 0), width=0.7)
    for index in range(18):
        y = 120 + index * 16
        page.insert_text(
            (326, y),
            f"This longer passage line {index + 1:02d} checks paragraph alignment.",
            fontsize=9.5,
            fontname="times-roman",
        )

    doc.save(str(path))


def _box_border_ids(header: ET.Element) -> set[str]:
    result: set[str] = set()
    for border in header.findall(f".//{HH}borderFill"):
        borders = [
            border.find(f"{HH}{name}")
            for name in ("leftBorder", "rightBorder", "topBorder", "bottomBorder")
        ]
        if all(
            item is not None and item.get("type") == "SOLID" and item.get("width") == "0.12 mm"
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
            }
        )
    return boxes


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="hwp_make_flow_passage_") as tmp:
        base = Path(tmp)
        pdf_path = base / "passage_boxes.pdf"
        hwpx_path = base / "passage_boxes.hwpx"
        _make_passage_pdf(pdf_path)
        stats = write_pdf_flow_hwpx(pdf_path, hwpx_path, boxed_passages=True)
        issues = verify(hwpx_path, render=False)
        boxes = _inspect_boxes(hwpx_path)

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

        if failures:
            print("FLOW_PASSAGE_BOXES_FAIL")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        print("FLOW_PASSAGE_BOXES_OK")
        print({"stats": stats, "boxes": boxes})
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
