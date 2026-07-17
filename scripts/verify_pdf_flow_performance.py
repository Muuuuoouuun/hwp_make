from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz

from app.pdf_layout_writer import write_pdf_flow_hwpx
from scripts.verify_pdf_layout_hwpx import verify


MAX_ELAPSED_MS = 10_000


def _dense_vector_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((42, 42), "Dense vector regression", fontsize=11)
    page.insert_textbox(
        fitz.Rect(45, 90, 275, 190),
        "1. A real boxed passage must remain editable and bounded.\n"
        "The synthetic lines below imitate a vector-heavy map.",
        fontsize=9,
    )
    page.draw_rect(fitz.Rect(40, 82, 282, 198), color=(0, 0, 0), width=0.7)

    # More than _MAX_FLOW_LAYOUT_AXIS_LINES long axis-aligned strokes.  The old
    # O(n^2) component grouping took tens of seconds on this shape class.
    for index in range(1_300):
        y = 330 + (index % 430) * 0.7
        x = 305 + (index % 11) * 1.4
        if index % 2:
            page.draw_line((x, y), (x + 120, y), color=(0.4, 0.4, 0.4), width=0.2)
        else:
            page.draw_line((x, y), (x, min(810, y + 34)), color=(0.4, 0.4, 0.4), width=0.2)
    payload = document.tobytes()
    document.close()
    return payload


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="hwp_make_pdf_flow_perf_", ignore_cleanup_errors=True) as temp:
        root = Path(temp)
        pdf_path = root / "dense-vector.pdf"
        output_path = root / "dense-vector.hwpx"
        pdf_path.write_bytes(_dense_vector_pdf())
        stats = write_pdf_flow_hwpx(pdf_path, output_path)

        checks = {
            "page count": int(stats.get("pages") or 0) == 1,
            "dense vector routing": int(stats.get("dense_vector_pages") or 0) == 1,
            "vector inventory": int(stats.get("axis_lines") or 0) >= 1_200,
            "boxed passage preserved": int(stats.get("boxed_blocks") or 0) >= 1,
            "performance gate": int(stats.get("elapsed_ms") or MAX_ELAPSED_MS + 1) < MAX_ELAPSED_MS,
            "HWPX structure": not verify(output_path, render=False),
        }
        for name, ok in checks.items():
            print(f"[{'PASS' if ok else 'FAIL'}] {name}")
            if not ok:
                failures.append(name)
        print(f"stats={stats}")
    if failures:
        print("PDF_FLOW_PERFORMANCE_FAIL: " + ", ".join(failures))
        return 1
    print("PDF_FLOW_PERFORMANCE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
