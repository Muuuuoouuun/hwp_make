from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pdf_layout_fidelity import analyze_pdf_hwpx_fidelity  # noqa: E402
from app.pdf_layout_writer import write_pdf_structured_hwpx  # noqa: E402
from hwpx.tools.package_validator import validate_editor_open_safety  # noqa: E402
from scripts.verify_pdf_layout_hwpx import verify as verify_hwpx  # noqa: E402


CASES = (
    ("2026_csat", "korean"),
    ("2026_csat", "math"),
    ("2026_csat", "english"),
    ("2026_march_high1", "korean"),
    ("2026_march_high1", "math"),
    ("2026_march_high1", "english"),
)


def _evaluation_source(source: Path, render_dir: Path, page_count: int) -> tuple[Path, int]:
    """Return the exact first form when an official PDF concatenates forms."""
    with fitz.open(source) as original:
        original_pages = len(original)
        if original_pages <= page_count:
            return source, original_pages
        render_dir.mkdir(parents=True, exist_ok=True)
        evaluation = render_dir / "source_first_complete_form.pdf"
        subset = fitz.open()
        subset.insert_pdf(original, from_page=0, to_page=page_count - 1)
        subset.save(evaluation)
        subset.close()
        return evaluation, original_pages


def main() -> int:
    source_root = ROOT / "data" / "external_exam_qa" / "second_pass_unseen"
    render_root = ROOT / "tmp" / "pdfs" / "exam_detail_unseen"
    report: dict[str, object] = {
        "source_policy": "unseen_after_first_pass",
        "average_target": 97.0,
        "minimum_target": 95.0,
        "cases": [],
        "failures": [],
    }
    failures: list[str] = report["failures"]  # type: ignore[assignment]

    for group, subject in CASES:
        source = source_root / group / f"{subject}.pdf"
        output = source.parent / "outputs_developed" / f"{subject}.hwpx"
        output.parent.mkdir(parents=True, exist_ok=True)
        render_dir = render_root / group / subject
        started = time.perf_counter()
        stats = write_pdf_structured_hwpx(source, output, native_math=True)
        conversion_seconds = time.perf_counter() - started
        evaluation_source, original_pdf_pages = _evaluation_source(
            source, render_dir, int(stats.get("pages") or 0)
        )
        fidelity = analyze_pdf_hwpx_fidelity(
            evaluation_source,
            output,
            render_dir,
            max_pages=int(stats.get("pages") or 0),
            target_sync_ratio=0.80,
            artifact_mode="all",
        )
        structure_issues = verify_hwpx(output, render=False)
        open_safety = validate_editor_open_safety(output)
        case = {
            "group": group,
            "subject": subject,
            "source": str(source.relative_to(ROOT)),
            "output": str(output.relative_to(ROOT)),
            "conversion_seconds": round(conversion_seconds, 3),
            "output_bytes": output.stat().st_size,
            "pages": int(stats.get("pages") or 0),
            "original_pdf_pages": original_pdf_pages,
            "evaluation_pdf_pages": int(stats.get("pages") or 0),
            "editable_text_coverage_ratio": stats.get("editable_text_coverage_ratio"),
            "full_page_images": stats.get("full_page_images"),
            "text_visual_overlays": stats.get("text_visual_overlays"),
            "math_visual_overlays": stats.get("math_visual_overlays"),
            "positioned_native_math_enabled": stats.get("positioned_native_math_enabled"),
            "positioned_native_equations": stats.get("positioned_native_equations"),
            "native_math_coverage_ratio": stats.get("native_math_coverage_ratio"),
            "fidelity": {
                key: fidelity.get(key)
                for key in (
                    "pdf_page_count",
                    "hwpx_page_count",
                    "pages_compared",
                    "page_count_mismatch",
                    "overall_sync_ratio",
                    "min_strict_alignment_ratio",
                    "min_foreground_overlap_ratio",
                    "overall_detailed_layout_score",
                    "minimum_detailed_layout_score",
                    "overall_harsh_layout_score",
                    "minimum_harsh_layout_score",
                    "review_flags",
                )
            },
            "structure_issues": structure_issues,
            "editor_open_safe": bool(open_safety.ok),
        }
        report["cases"].append(case)  # type: ignore[union-attr]
        prefix = f"{group}/{subject}"
        if float(fidelity.get("overall_harsh_layout_score") or 0.0) < 97.0:
            failures.append(f"{prefix}: average harsh score below 97")
        if float(fidelity.get("minimum_harsh_layout_score") or 0.0) < 95.0:
            failures.append(f"{prefix}: minimum harsh score below 95")
        if fidelity.get("page_count_mismatch"):
            failures.append(f"{prefix}: page count mismatch")
        if int(fidelity.get("pages_compared") or 0) != int(stats.get("pages") or 0):
            failures.append(f"{prefix}: not all converted pages compared")
        if float(stats.get("editable_text_coverage_ratio") or 0.0) < 0.99:
            failures.append(f"{prefix}: editable text coverage below 99%")
        if int(stats.get("full_page_images") or 0) > 0:
            failures.append(f"{prefix}: full-page raster image used")
        if output.stat().st_size / max(1, int(stats.get("pages") or 0)) > 1_000_000:
            failures.append(f"{prefix}: output exceeds 1 MB per page")
        if subject == "math":
            if not stats.get("positioned_native_math_enabled"):
                failures.append(f"{prefix}: positioned native math disabled")
            if int(stats.get("positioned_native_equations") or 0) <= 0:
                failures.append(f"{prefix}: no positioned native equations")
            if float(stats.get("native_math_coverage_ratio") or 0.0) < 0.90:
                failures.append(f"{prefix}: native math coverage below 90%")
        if float(fidelity.get("min_strict_alignment_ratio") or 0.0) < 0.96:
            failures.append(f"{prefix}: raw strict alignment below 96%")
        if float(fidelity.get("min_foreground_overlap_ratio") or 0.0) < 0.97:
            failures.append(f"{prefix}: raw foreground overlap below 97%")
        if structure_issues:
            failures.append(f"{prefix}: structure issues: {structure_issues[:3]}")
        if not open_safety.ok:
            failures.append(f"{prefix}: editor-open safety failed")

    cases: list[dict[str, object]] = report["cases"]  # type: ignore[assignment]
    total_pages = sum(int(case["pages"]) for case in cases)
    weighted = sum(
        int(case["pages"])
        * float(case["fidelity"]["overall_harsh_layout_score"] or 0.0)  # type: ignore[index]
        for case in cases
    )
    global_minimum = min(
        float(case["fidelity"]["minimum_harsh_layout_score"] or 0.0)  # type: ignore[index]
        for case in cases
    )
    report["weighted_average_harsh_layout_score"] = round(
        weighted / max(1, total_pages), 2
    )
    report["minimum_harsh_layout_score"] = round(global_minimum, 2)
    report["total_pages"] = total_pages
    report["total_conversion_seconds"] = round(
        sum(float(case["conversion_seconds"]) for case in cases), 3
    )
    if weighted / max(1, total_pages) < 97.0:
        failures.append("second-pass weighted harsh average below 97")
    if global_minimum < 95.0:
        failures.append("second-pass global harsh minimum below 95")

    report_path = source_root / "unseen_quality_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Report: {report_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
