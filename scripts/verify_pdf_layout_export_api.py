from __future__ import annotations

import base64
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import fitz  # PyMuPDF
except Exception:
    print("SKIP: PyMuPDF(fitz) unavailable")
    raise SystemExit(2)

tmp = tempfile.TemporaryDirectory(prefix="hwp_make_pdf_layout_api_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = tmp.name

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.pdf_layout_writer import _flow_text_for_span  # noqa: E402
from scripts.verify_pdf_layout_hwpx import verify  # noqa: E402

_failures: list[str] = []
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}{(' - ' + detail) if detail else ''}")
    if not condition:
        _failures.append(name)


def make_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((48, 38), "Mock English Test", fontsize=12, fontname="helv")
    page.insert_textbox(
        fitz.Rect(48, 86, 270, 250),
        "1. Read the passage and choose the best answer.\n"
        "The river was quiet, and the old bridge held the morning light.\n"
        "1) bright  2) quiet  3) narrow  4) broken  5) distant",
        fontsize=10,
        fontname="times-roman",
    )
    page.insert_textbox(
        fitz.Rect(310, 86, 540, 250),
        "2. Which sentence best completes the paragraph?\n"
        "Students compared the two maps and wrote a short explanation.\n"
        "1) However  2) Therefore  3) Likewise  4) Instead  5) Otherwise",
        fontsize=10,
        fontname="times-roman",
    )
    page.draw_rect(fitz.Rect(48, 290, 270, 380), color=(0, 0, 0), width=0.8)
    page.insert_textbox(
        fitz.Rect(58, 302, 260, 368),
        "A boxed passage should stay inside a real HWPX table cell, not overlap choices.",
        fontsize=9.5,
        fontname="times-roman",
    )
    return doc.tobytes()


def _inspect_flow_style(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        header = ET.fromstring(archive.read("Contents/header.xml"))
        section = ET.fromstring(archive.read("Contents/section0.xml"))
    faces = {font.get("face") for font in header.findall(f".//{HH}font") if font.get("face")}
    char_metric_ok = False
    metric_heights = set()
    for char_pr in header.findall(f".//{HH}charPr"):
        ratio = char_pr.find(f"{HH}ratio")
        spacing = char_pr.find(f"{HH}spacing")
        if ratio is None or spacing is None:
            continue
        if (
            ratio.get("hangul") == "86"
            and ratio.get("latin") == "86"
            and spacing.get("hangul") == "-5"
            and spacing.get("latin") == "-5"
        ):
            char_metric_ok = True
            if char_pr.get("height"):
                metric_heights.add(char_pr.get("height"))

    para_150_ids = set()
    for para_pr in header.findall(f".//{HH}paraPr"):
        line_spacing = para_pr.find(f".//{HH}lineSpacing")
        if line_spacing is not None and line_spacing.get("type") == "PERCENT" and line_spacing.get("value") == "150":
            para_id = para_pr.get("id")
            if para_id:
                para_150_ids.add(para_id)
    uses_150 = any((para.get("paraPrIDRef") or "") in para_150_ids for para in section.findall(f".//{HP}p"))

    border_by_id = {border.get("id") or "": border for border in header.findall(f".//{HH}borderFill")}
    divider_refs = {cell.get("borderFillIDRef") or "" for cell in section.findall(f".//{HP}tc")}
    divider_ok = False
    header_bottom_ok = False
    for ref in divider_refs:
        border = border_by_id.get(ref)
        if border is None:
            continue
        right = border.find(f"{HH}rightBorder")
        left = border.find(f"{HH}leftBorder")
        top = border.find(f"{HH}topBorder")
        bottom = border.find(f"{HH}bottomBorder")
        if (
            right is not None
            and right.get("type") == "SOLID"
            and right.get("width") == "0.12 mm"
            and all(
                item is not None and (item.get("type") or "").upper() == "NONE"
                for item in (left, top, bottom)
            )
        ):
            divider_ok = True
        if (
            bottom is not None
            and bottom.get("type") == "SOLID"
            and bottom.get("width") == "0.2 mm"
            and all(
                item is not None and (item.get("type") or "").upper() == "NONE"
                for item in (left, right, top)
            )
        ):
            header_bottom_ok = True
    margin_ok = False
    for cell in section.findall(f".//{HP}tc"):
        margin = cell.find(f"{HP}cellMargin")
        if cell.get("hasMargin") == "1" and margin is not None:
            try:
                if int(margin.get("left") or "0") > 0 or int(margin.get("right") or "0") > 0:
                    margin_ok = True
                    break
            except ValueError:
                pass
    page_margin = section.find(f".//{HP}pagePr/{HP}margin")
    header_footer_zero = (
        page_margin is not None
        and page_margin.get("header") == "0"
        and page_margin.get("footer") == "0"
    )
    table_columns = {table.get("colCnt") for table in section.findall(f".//{HP}tbl")}
    return {
        "faces": faces,
        "char_metric_ok": char_metric_ok,
        "metric_heights": metric_heights,
        "uses_150": uses_150,
        "divider_ok": divider_ok,
        "header_bottom_ok": header_bottom_ok,
        "header_footer_zero": header_footer_zero,
        "separate_header_body_tables": {"2", "3"}.issubset(table_columns),
        "margin_ok": margin_ok,
    }


def main() -> int:
    try:
        check(
            "HyhwpEQ PUA flow recovery",
            _flow_text_for_span({"text": "\ue0fc\ue036", "font": "HyhwpEQ", "size": 7.0}) == "x³",
        )
        client = TestClient(app)
        rejected = client.post(
            "/api/pdf-layout-export",
            json={
                "filename": "not_pdf.txt",
                "data_base64": base64.b64encode(b"not a pdf").decode("ascii"),
                "boxed_passages": True,
            },
        )
        check("reject non-PDF", rejected.status_code == 400, rejected.text[:240])

        response = client.post(
            "/api/pdf-layout-export",
            json={
                "filename": "mock_english.pdf",
                "data_base64": base64.b64encode(make_pdf()).decode("ascii"),
                "boxed_passages": True,
            },
        )
        check("API status", response.status_code == 200, response.text[:240] if response.status_code != 200 else "")
        if response.status_code != 200:
            return 1
        payload = response.json()
        check("mode", payload.get("mode") == "pdf_flow_hwpx", repr(payload.get("mode")))
        export = payload.get("export") or {}
        output_path = Path(tmp.name) / "exports" / str(export.get("name") or "")
        check("export exists", output_path.is_file(), str(output_path))
        stats = payload.get("stats") or {}
        check("stats pages", stats.get("pages") == 1, repr(stats))
        check("editable flow lines", int(stats.get("flow_lines") or 0) > 0, repr(stats))
        check("header row detected", int(stats.get("header_rows") or 0) == 1, repr(stats))
        page_margins = stats.get("page_margins_mm") or {}
        check(
            "source-derived side margins",
            float(page_margins.get("left") or 0) > 7 and float(page_margins.get("right") or 0) > 7,
            repr(page_margins),
        )
        if output_path.is_file():
            issues = verify(output_path, render=False)
            check("HWPX structure", not issues, "; ".join(issues[:5]))
            style = _inspect_flow_style(output_path)
            faces = style["faces"]
            check("flow font faces", {"신명 중명조", "Times New Roman", "돋움"}.issubset(faces), repr(sorted(faces)))
            check("flow char ratio/spacing", bool(style["char_metric_ok"]))
            metric_heights = set(style["metric_heights"])
            old_dense_heights = {"840", "940", "1080"}
            check(
                "flow font size buckets",
                "1000" in metric_heights and not (metric_heights & old_dense_heights),
                repr(sorted(metric_heights)),
            )
            check("flow line spacing 150", bool(style["uses_150"]))
            check("flow middle divider", bool(style["divider_ok"]))
            check("flow header bottom border", bool(style["header_bottom_ok"]))
            check("zero implicit header/footer margins", bool(style["header_footer_zero"]))
            check("separate header/body tables", bool(style["separate_header_body_tables"]))
            check("flow cell margins", bool(style["margin_ok"]))
        return 1 if _failures else 0
    finally:
        tmp.cleanup()


if __name__ == "__main__":
    code = main()
    if code == 0:
        print("PDF_LAYOUT_EXPORT_API_OK")
    else:
        print(f"PDF_LAYOUT_EXPORT_API_FAIL ({len(_failures)}): {', '.join(_failures)}")
    raise SystemExit(code)
