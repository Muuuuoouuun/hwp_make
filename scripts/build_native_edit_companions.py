from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pdf_layout_writer import (  # noqa: E402
    write_pdf_flow_hwpx,
    write_pdf_structured_hwpx,
)
from hwpx.tools.package_validator import validate_editor_open_safety  # noqa: E402
from scripts.verify_external_exam_detail_quality import _paragraph_audit  # noqa: E402
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    selected = CASES[: args.limit] if args.limit > 0 else CASES
    report: dict[str, object] = {
        "purpose": "native_edit_companions",
        "cases": [],
        "failures": [],
    }
    failures: list[str] = report["failures"]  # type: ignore[assignment]

    for group, subject, page_limit in selected:
        source_dir = ROOT / "data" / "external_exam_qa" / group
        source = source_dir / f"{subject}.pdf"
        output = source_dir / "outputs_native_edit" / f"{subject}.hwpx"
        output.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        if subject == "math":
            stats = write_pdf_structured_hwpx(
                source,
                output,
                max_pages=page_limit,
                native_math=True,
                high_fidelity_math=False,
            )
            mode = "native_page_tables_equations"
        else:
            stats = write_pdf_flow_hwpx(
                source,
                output,
                max_pages=page_limit,
                boxed_passages=True,
                target_a4=False,
                rasterize_tables=False,
                preserve_repeated_headers=False,
            )
            mode = "native_reflow_paragraphs_tables"
        seconds = time.perf_counter() - started
        audit = _paragraph_audit(output)
        structure_issues = verify_hwpx(output, render=False)
        open_safety = validate_editor_open_safety(output)
        case = {
            "group": group,
            "subject": subject,
            "mode": mode,
            "source": str(source.relative_to(ROOT)),
            "output": str(output.relative_to(ROOT)),
            "seconds": round(seconds, 3),
            "bytes": output.stat().st_size,
            "stats": stats,
            "paragraph_audit": audit,
            "editor_open_safe": bool(open_safety.ok),
            "structure_issues": structure_issues,
        }
        report["cases"].append(case)  # type: ignore[union-attr]
        prefix = f"{group}/{subject}"
        if int(stats.get("pages") or 0) != page_limit:
            failures.append(f"{prefix}: page count mismatch")
        if float(stats.get("editable_text_coverage_ratio") or 0.0) < 0.98:
            failures.append(f"{prefix}: editable text coverage below 98%")
        if int(stats.get("full_page_images") or 0) > 0:
            failures.append(f"{prefix}: full-page image used")
        if subject == "math":
            if int(stats.get("native_equations") or 0) <= 0:
                failures.append(f"{prefix}: no native equations")
            if float(stats.get("native_math_coverage_ratio") or 0.0) < 0.90:
                failures.append(f"{prefix}: native math coverage below 90%")
        else:
            if audit["justified_paragraphs"] <= 0:
                failures.append(f"{prefix}: no justified paragraphs")
            if audit["first_line_indented_paragraphs"] <= 0:
                failures.append(f"{prefix}: no first-line indented paragraphs")
            if audit["tables"] <= 0:
                failures.append(f"{prefix}: no native layout tables")
        if structure_issues:
            failures.append(f"{prefix}: structure issues: {structure_issues[:3]}")
        if not open_safety.ok:
            failures.append(f"{prefix}: editor-open safety failed")

    cases: list[dict[str, object]] = report["cases"]  # type: ignore[assignment]
    report["total_seconds"] = round(sum(float(case["seconds"]) for case in cases), 3)
    report["total_bytes"] = sum(int(case["bytes"]) for case in cases)
    report_path = (
        ROOT / "data" / "external_exam_qa" / "native_edit_companion_report.json"
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Report: {report_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
