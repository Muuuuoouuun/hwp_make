from __future__ import annotations

import base64
import os
import sys
import tempfile
from pathlib import Path

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
from scripts.verify_pdf_layout_hwpx import verify  # noqa: E402

_failures: list[str] = []


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


def main() -> int:
    try:
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
        if output_path.is_file():
            issues = verify(output_path, render=False)
            check("HWPX structure", not issues, "; ".join(issues[:5]))
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
