from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pdf_layout_writer import write_pdf_structured_hwpx  # noqa: E402
from hwpx.tools.package_validator import validate_editor_open_safety  # noqa: E402
from scripts.verify_pdf_layout_hwpx import verify as verify_hwpx  # noqa: E402


CASES = (
    ("2027_kice_june_high3", "korean", 20),
    ("2027_kice_june_high3", "math", 20),
    ("2027_kice_june_high3", "english", 8),
    ("2026_june_high1", "korean", 16),
    ("2026_june_high1", "math", 12),
    ("2026_june_high1", "english", 8),
    ("second_pass_unseen/2026_csat", "korean", 20),
    ("second_pass_unseen/2026_csat", "math", 20),
    ("second_pass_unseen/2026_csat", "english", 8),
    ("second_pass_unseen/2026_march_high1", "korean", 16),
    ("second_pass_unseen/2026_march_high1", "math", 12),
    ("second_pass_unseen/2026_march_high1", "english", 8),
)


def main() -> int:
    report: dict[str, object] = {"cases": [], "failures": []}
    failures: list[str] = report["failures"]  # type: ignore[assignment]
    for group, subject, expected_pages in CASES:
        source_dir = ROOT / "data" / "external_exam_qa" / group
        source = source_dir / f"{subject}.pdf"
        output = source_dir / "outputs_developed" / f"{subject}.hwpx"
        started = time.perf_counter()
        stats = write_pdf_structured_hwpx(source, output, native_math=True)
        seconds = time.perf_counter() - started
        structure_issues = verify_hwpx(output, render=False)
        open_safety = validate_editor_open_safety(output)
        size = output.stat().st_size
        case = {
            "group": group,
            "subject": subject,
            "source": str(source.relative_to(ROOT)),
            "output": str(output.relative_to(ROOT)),
            "seconds": round(seconds, 3),
            "pages": int(stats.get("pages") or 0),
            "seconds_per_page": round(seconds / max(1, expected_pages), 4),
            "bytes": size,
            "bytes_per_page": round(size / max(1, expected_pages), 1),
            "editable_text_coverage_ratio": stats.get("editable_text_coverage_ratio"),
            "positioned_native_equations": stats.get("positioned_native_equations"),
            "native_math_coverage_ratio": stats.get("native_math_coverage_ratio"),
            "full_page_images": stats.get("full_page_images"),
            "structure_issues": structure_issues,
            "editor_open_safe": bool(open_safety.ok),
        }
        report["cases"].append(case)  # type: ignore[union-attr]
        prefix = f"{group}/{subject}"
        if int(stats.get("pages") or 0) != expected_pages:
            failures.append(f"{prefix}: page count mismatch")
        if size / max(1, expected_pages) > 1_000_000:
            failures.append(f"{prefix}: output exceeds 1 MB per page")
        if structure_issues:
            failures.append(f"{prefix}: structure issues: {structure_issues[:3]}")
        if not open_safety.ok:
            failures.append(f"{prefix}: editor-open safety failed")
    cases: list[dict[str, object]] = report["cases"]  # type: ignore[assignment]
    total_pages = sum(int(case["pages"]) for case in cases)
    total_seconds = sum(float(case["seconds"]) for case in cases)
    total_bytes = sum(int(case["bytes"]) for case in cases)
    report.update(
        {
            "total_pages": total_pages,
            "total_seconds": round(total_seconds, 3),
            "seconds_per_page": round(total_seconds / max(1, total_pages), 4),
            "total_bytes": total_bytes,
            "bytes_per_page": round(total_bytes / max(1, total_pages), 1),
        }
    )
    report_path = ROOT / "data" / "external_exam_qa" / "final_conversion_benchmark.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Report: {report_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
