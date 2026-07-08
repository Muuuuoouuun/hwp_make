# -*- coding: utf-8 -*-
"""Run the full math-exam HWPX conversion QA gate.

This is the one-command guard for the current completion target:
editable/native math, KICE-style layout, problem/choice/source sync, and the
real HWP sample workflow.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
NATIVE_MATH_REPORT = ROOT / "data" / "exports" / "native_math_qa" / "native_math_report.json"
PDF_MATH_REPORT = ROOT / "data" / "pdf_math_qa" / "exports" / "pdf_math_pipeline_report.json"
HWP_SAMPLE_REPORT = ROOT / "data" / "hwp_math_sample_qa" / "exports" / "hwp_math_sample_qa_report.json"
HWP_SAMPLE_REVIEW = ROOT / "data" / "hwp_math_sample_qa" / "exports" / "hwp_math_sample_review.html"
KNOWN_MANIFEST_FALLBACK_TOKENS = ("masterPage", "history", "version", "header", "section")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


@dataclass(frozen=True)
class Check:
    name: str
    command: list[str]
    timeout: int


@dataclass(frozen=True)
class FilteredOutput:
    text: str
    manifest_fallback_warnings: int = 0
    crlf_warnings: int = 0


@dataclass(frozen=True)
class CheckResult:
    name: str
    command: list[str]
    returncode: int
    elapsed_seconds: float
    manifest_fallback_warnings: int
    crlf_warnings: int


def _decode_output(data: bytes) -> str:
    if not data:
        return ""
    candidates = []
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        decoded = data.decode(encoding, errors="replace")
        candidates.append((decoded.count("\ufffd"), encoding, decoded))
    candidates.sort(key=lambda item: (item[0], 0 if item[1].startswith("utf-8") else 1))
    return candidates[0][2].replace("\r\n", "\n").replace("\r", "\n")


def _filter_known_noise(text: str, *, show_known_warnings: bool) -> FilteredOutput:
    if show_known_warnings or not text:
        return FilteredOutput(text=text)

    kept: list[str] = []
    manifest_count = 0
    crlf_count = 0
    for line in text.splitlines():
        if (
            line.startswith("manifest")
            and "fallback" in line
            and any(token in line for token in KNOWN_MANIFEST_FALLBACK_TOKENS)
        ):
            manifest_count += 1
            continue
        if line.startswith("warning: in the working copy of") and "LF will be replaced by CRLF" in line:
            crlf_count += 1
            continue
        kept.append(line)
    output = "\n".join(kept)
    if text.endswith("\n") and output:
        output += "\n"
    return FilteredOutput(output, manifest_count, crlf_count)


def _print_filtered_output(label: str, output: FilteredOutput) -> None:
    if output.text:
        print(output.text, end="" if output.text.endswith("\n") else "\n", flush=True)
    summaries = []
    if output.manifest_fallback_warnings:
        summaries.append(f"{output.manifest_fallback_warnings} known manifest fallback warnings")
    if output.crlf_warnings:
        summaries.append(f"{output.crlf_warnings} Git CRLF normalization warnings")
    if summaries:
        print(f"[{label}] suppressed: {', '.join(summaries)}", flush=True)


def _as_existing_path(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return str(path)


def _read_json_if_present(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        return {"error": f"invalid JSON: {exc}"}


def _equation_visibility_weak_pages(
    visibility: dict[str, object],
    *,
    min_page_pixels: int = 700,
    min_page_ratio: float = 0.0008,
) -> list[object]:
    return [
        page
        for page in visibility.get("page_diffs") or []
        if isinstance(page, dict)
        and (
            int(page.get("changed_pixels") or 0) < min_page_pixels
            or float(page.get("changed_ratio") or 0) < min_page_ratio
        )
    ]


def _equation_visibility_failed(visibility: object) -> bool:
    if not isinstance(visibility, dict):
        return True
    if visibility.get("skipped"):
        return False
    if visibility.get("error"):
        return True
    changed_pixels = int(visibility.get("changed_pixels") or 0)
    changed_ratio = float(visibility.get("changed_ratio") or 0)
    if changed_pixels < 4000 or changed_ratio < 0.001:
        return True
    if visibility.get("actual_page_count") != visibility.get("control_page_count"):
        return True
    return bool(_equation_visibility_weak_pages(visibility))


def _equation_visibility_summary(
    visibility: dict[str, object],
    *,
    min_page_pixels: int = 700,
    min_page_ratio: float = 0.0008,
) -> dict[str, object]:
    page_diffs = [
        page for page in visibility.get("page_diffs") or [] if isinstance(page, dict)
    ]
    min_page_changed_pixels = min(
        (int(page.get("changed_pixels") or 0) for page in page_diffs),
        default=None,
    )
    min_page_changed_ratio = min(
        (float(page.get("changed_ratio") or 0) for page in page_diffs),
        default=None,
    )
    weak_pages = _equation_visibility_weak_pages(
        visibility,
        min_page_pixels=min_page_pixels,
        min_page_ratio=min_page_ratio,
    )
    return {
        "available": visibility.get("available"),
        "page_count": visibility.get("page_count"),
        "actual_page_count": visibility.get("actual_page_count"),
        "control_page_count": visibility.get("control_page_count"),
        "changed_pixels": visibility.get("changed_pixels"),
        "changed_ratio": visibility.get("changed_ratio"),
        "min_page_changed_pixels": min_page_changed_pixels,
        "min_page_changed_ratio": min_page_changed_ratio,
        "min_page_pixel_threshold": min_page_pixels,
        "min_page_ratio_threshold": min_page_ratio,
        "weak_page_count": len(weak_pages),
        "weak_pages": weak_pages,
        "control_path": _as_existing_path(visibility.get("control_path")),
        "page_diffs": page_diffs,
        "error": visibility.get("error"),
    }


def _sample_artifact_summary(record: object) -> dict[str, object]:
    if not isinstance(record, dict):
        return {"error": "sample record is not an object"}
    render = record.get("render")
    source_render = record.get("source_render")
    inspect = record.get("inspect")
    table_math = record.get("table_math")
    equation_visibility = record.get("equation_visibility")
    source = record.get("source")
    output = record.get("output")
    summary: dict[str, object] = {
        "source": Path(source).name if isinstance(source, str) else source,
        "output": _as_existing_path(output),
        "created_problems": record.get("created"),
        "choice_distribution": record.get("choice_dist"),
        "first_unit": record.get("first_unit"),
        "last_unit": record.get("last_unit"),
        "review_flags": record.get("review_flags") or [],
        "mojibake_hits": record.get("mojibake_hits") or [],
        "failures": record.get("failures") or [],
    }
    if isinstance(table_math, dict):
        summary["table_math"] = {
            "tables": table_math.get("tables"),
            "tables_with_math": table_math.get("tables_with_math"),
            "math_spans": table_math.get("math_spans"),
        }
    if isinstance(equation_visibility, dict):
        summary["equation_visibility"] = _equation_visibility_summary(equation_visibility)
    if isinstance(inspect, dict):
        summary["inspect"] = {
            "native_equations": inspect.get("equations"),
            "math_paragraphs": inspect.get("math_paragraphs"),
            "math_lineseg_paragraphs": inspect.get("math_lineseg_paragraphs"),
            "equation_object_issue_count": inspect.get("equation_object_issue_count"),
            "equation_object_issues": inspect.get("equation_object_issues") or [],
            "duplicate_equation_ids": inspect.get("duplicate_equation_ids") or [],
            "duplicate_equation_zorders": inspect.get("duplicate_equation_zorders") or [],
            "math_lineseg_issue_count": inspect.get("math_lineseg_issue_count"),
            "math_lineseg_issues": inspect.get("math_lineseg_issues") or [],
            "oversized_objects": len(inspect.get("oversized_objects") or []),
            "orphan_source_markers": len(inspect.get("orphan_source_markers") or []),
        }
    if isinstance(render, dict):
        summary["render"] = {
            "available": render.get("available"),
            "page_count": render.get("page_count"),
            "overflow_count": render.get("overflow_count"),
            "column_crossing_issues": len(render.get("column_crossing_issues") or []),
            "contact_sheet": _as_existing_path(render.get("contact_sheet")),
            "saved_pages": [_as_existing_path(page) for page in render.get("saved_pages") or []],
        }
    if isinstance(source_render, dict):
        summary["source_render"] = {
            "available": source_render.get("available"),
            "page_count": source_render.get("page_count"),
            "contact_sheet": _as_existing_path(source_render.get("contact_sheet")),
            "saved_pages": [_as_existing_path(page) for page in source_render.get("saved_pages") or []],
        }
    density = record.get("density_summary")
    if isinstance(density, dict):
        summary["density_summary"] = {
            "source": density.get("source"),
            "output": density.get("output"),
            "output_to_source_median_ratio": density.get("output_to_source_median_ratio"),
        }
    output_sync = record.get("output_sync")
    if isinstance(output_sync, dict):
        summary["output_sync"] = {
            "expected_problem_labels": output_sync.get("expected_problem_labels"),
            "actual_problem_labels": output_sync.get("actual_problem_labels"),
            "expected_source_markers": output_sync.get("expected_source_markers"),
            "actual_source_markers": output_sync.get("actual_source_markers"),
            "expected_choice_counts": output_sync.get("expected_choice_counts"),
            "actual_choice_counts": output_sync.get("actual_choice_counts"),
            "choice_count_mismatch_count": output_sync.get("choice_count_mismatch_count"),
            "choice_count_mismatches": output_sync.get("choice_count_mismatches"),
            "problem_label_mismatch": output_sync.get("problem_label_mismatch"),
            "source_marker_mismatch": output_sync.get("source_marker_mismatch"),
        }
    object_sync = record.get("object_sync")
    if isinstance(object_sync, dict):
        summary["object_sync"] = {
            "expected_pictures": object_sync.get("expected_pictures"),
            "actual_pictures": object_sync.get("actual_pictures"),
            "expected_content_tables": object_sync.get("expected_content_tables"),
            "actual_content_tables": object_sync.get("actual_content_tables"),
            "expected_choice_grid_tables": object_sync.get("expected_choice_grid_tables"),
            "actual_choice_grid_tables": object_sync.get("actual_choice_grid_tables"),
            "mismatches": object_sync.get("mismatches") or [],
        }
    problem_inventory = record.get("problem_inventory")
    if isinstance(problem_inventory, dict):
        summary["problem_inventory"] = {
            "problem_count": problem_inventory.get("problem_count"),
            "output_segment_count": problem_inventory.get("output_segment_count"),
            "expected_equations": problem_inventory.get("expected_equations"),
            "actual_equations": problem_inventory.get("actual_equations"),
            "mismatch_count": problem_inventory.get("mismatch_count"),
            "mismatches": problem_inventory.get("mismatches") or [],
        }
    text_sync = record.get("text_sync")
    if isinstance(text_sync, dict):
        summary["text_sync"] = {
            "expected_fragments": text_sync.get("expected_fragments"),
            "missing_count": text_sync.get("missing_count"),
            "problem_count": text_sync.get("problem_count"),
            "output_segment_count": text_sync.get("output_segment_count"),
            "mismatches": text_sync.get("mismatches") or [],
        }
    layout = record.get("layout_summary")
    if isinstance(layout, dict):
        summary["layout_summary"] = layout
    return summary


def _artifact_summary() -> dict[str, object]:
    native_report = _read_json_if_present(NATIVE_MATH_REPORT)
    sample_report = _read_json_if_present(HWP_SAMPLE_REPORT)
    summary: dict[str, object] = {
        "paths": {
            "native_math_report": str(NATIVE_MATH_REPORT),
            "pdf_math_report": str(PDF_MATH_REPORT),
            "hwp_sample_report": str(HWP_SAMPLE_REPORT),
            "hwp_sample_review": str(HWP_SAMPLE_REVIEW),
        }
    }
    if isinstance(native_report, dict):
        rhwp = native_report.get("rhwp")
        native_summary: dict[str, object] = {
            "ok": native_report.get("ok"),
            "equation_count": native_report.get("equation_count"),
            "direct_cases": len(native_report.get("direct_cases") or []),
            "width_cases": len(native_report.get("width_cases") or []),
            "script_count": len(native_report.get("scripts") or []),
            "equation_object_issue_count": native_report.get("equation_object_issue_count"),
            "equation_object_issues": native_report.get("equation_object_issues") or [],
            "hwpx_path": _as_existing_path(native_report.get("hwpx_path")),
            "failures": native_report.get("failures") or [],
        }
        if isinstance(rhwp, dict):
            native_summary["render"] = {
                "available": rhwp.get("available"),
                "page_count": rhwp.get("page_count"),
                "render_path": _as_existing_path(rhwp.get("render_path")),
            }
        visibility = native_report.get("render_visibility")
        if isinstance(visibility, dict):
            native_summary["render_visibility"] = {
                "available": visibility.get("available"),
                "page_count": visibility.get("page_count"),
                "changed_pixels": visibility.get("changed_pixels"),
                "changed_ratio": visibility.get("changed_ratio"),
                "control_path": _as_existing_path(visibility.get("control_path")),
                "page_diffs": visibility.get("page_diffs") or [],
                "error": visibility.get("error"),
            }
        summary["native_math"] = native_summary
    elif native_report is None:
        summary["native_math"] = {"missing": True}
    else:
        summary["native_math"] = native_report

    pdf_report = _read_json_if_present(PDF_MATH_REPORT)
    if isinstance(pdf_report, dict):
        visibility = pdf_report.get("equation_visibility")
        pdf_summary: dict[str, object] = {
            "ok": pdf_report.get("ok"),
            "pdf_path": _as_existing_path(pdf_report.get("pdf_path")),
            "hwpx_path": _as_existing_path(pdf_report.get("hwpx_path")),
            "created": pdf_report.get("created"),
            "numbers": pdf_report.get("numbers") or [],
            "choice_counts": pdf_report.get("choice_counts") or [],
            "math_count": pdf_report.get("math_count"),
            "equation_count": pdf_report.get("equation_count"),
            "equation_object_issue_count": pdf_report.get("equation_object_issue_count"),
            "failures": pdf_report.get("failures") or [],
            "notices": pdf_report.get("notices") or [],
            "importer_warning_count": len(pdf_report.get("importer_warnings") or []),
            "importer_warnings": pdf_report.get("importer_warnings") or [],
        }
        if isinstance(visibility, dict):
            pdf_summary["equation_visibility"] = _equation_visibility_summary(
                visibility,
                min_page_pixels=300,
                min_page_ratio=0.0005,
            )
        render = pdf_report.get("render")
        if isinstance(render, dict):
            pdf_summary["render"] = {
                "available": render.get("available"),
                "page_count": render.get("page_count"),
                "overflow_count": render.get("overflow_count"),
                "column_crossing_issues": len(render.get("column_crossing_issues") or []),
                "ink_densities": render.get("ink_densities") or [],
                "content_bounds": render.get("content_bounds") or [],
                "contact_sheet": _as_existing_path(render.get("contact_sheet")),
                "saved_pages": [_as_existing_path(page) for page in render.get("saved_pages") or []],
                "error": render.get("error"),
            }
        two_column = pdf_report.get("two_column")
        if isinstance(two_column, dict):
            two_column_visibility = two_column.get("equation_visibility")
            two_column_summary: dict[str, object] = {
                "ok": two_column.get("ok"),
                "pdf_path": _as_existing_path(two_column.get("pdf_path")),
                "hwpx_path": _as_existing_path(two_column.get("hwpx_path")),
                "created": two_column.get("created"),
                "numbers": two_column.get("numbers") or [],
                "choice_counts": two_column.get("choice_counts") or [],
                "math_count": two_column.get("math_count"),
                "equation_count": two_column.get("equation_count"),
                "equation_object_issue_count": two_column.get("equation_object_issue_count"),
                "failures": two_column.get("failures") or [],
                "notices": two_column.get("notices") or [],
            }
            if isinstance(two_column_visibility, dict):
                two_column_summary["equation_visibility"] = _equation_visibility_summary(
                    two_column_visibility,
                    min_page_pixels=300,
                    min_page_ratio=0.0005,
                )
            two_column_render = two_column.get("render")
            if isinstance(two_column_render, dict):
                two_column_summary["render"] = {
                    "available": two_column_render.get("available"),
                    "page_count": two_column_render.get("page_count"),
                    "overflow_count": two_column_render.get("overflow_count"),
                    "column_crossing_issues": len(two_column_render.get("column_crossing_issues") or []),
                    "ink_densities": two_column_render.get("ink_densities") or [],
                    "content_bounds": two_column_render.get("content_bounds") or [],
                    "contact_sheet": _as_existing_path(two_column_render.get("contact_sheet")),
                    "saved_pages": [
                        _as_existing_path(page) for page in two_column_render.get("saved_pages") or []
                    ],
                    "error": two_column_render.get("error"),
                }
            pdf_summary["two_column"] = two_column_summary
        visual = pdf_report.get("visual")
        if isinstance(visual, dict):
            visual_visibility = visual.get("equation_visibility")
            visual_summary: dict[str, object] = {
                "ok": visual.get("ok"),
                "pdf_path": _as_existing_path(visual.get("pdf_path")),
                "hwpx_path": _as_existing_path(visual.get("hwpx_path")),
                "created": visual.get("created"),
                "numbers": visual.get("numbers") or [],
                "choice_counts": visual.get("choice_counts") or [],
                "image_counts": visual.get("image_counts") or [],
                "picture_count": visual.get("picture_count"),
                "math_count": visual.get("math_count"),
                "equation_count": visual.get("equation_count"),
                "equation_object_issue_count": visual.get("equation_object_issue_count"),
                "failures": visual.get("failures") or [],
                "notices": visual.get("notices") or [],
            }
            if isinstance(visual_visibility, dict):
                visual_summary["equation_visibility"] = _equation_visibility_summary(
                    visual_visibility,
                    min_page_pixels=300,
                    min_page_ratio=0.0005,
                )
            visual_render = visual.get("render")
            if isinstance(visual_render, dict):
                visual_summary["render"] = {
                    "available": visual_render.get("available"),
                    "page_count": visual_render.get("page_count"),
                    "overflow_count": visual_render.get("overflow_count"),
                    "column_crossing_issues": len(visual_render.get("column_crossing_issues") or []),
                    "ink_densities": visual_render.get("ink_densities") or [],
                    "content_bounds": visual_render.get("content_bounds") or [],
                    "contact_sheet": _as_existing_path(visual_render.get("contact_sheet")),
                    "saved_pages": [
                        _as_existing_path(page) for page in visual_render.get("saved_pages") or []
                    ],
                    "error": visual_render.get("error"),
                }
            pdf_summary["visual"] = visual_summary
        summary["pdf_math"] = pdf_summary
    elif pdf_report is None:
        summary["pdf_math"] = {"missing": True}
    else:
        summary["pdf_math"] = pdf_report

    if isinstance(sample_report, list):
        samples = [_sample_artifact_summary(record) for record in sample_report]
        summary["hwp_samples"] = {
            "sample_count": len(samples),
            "total_created_problems": sum(
                int(sample.get("created_problems") or 0)
                for sample in samples
                if isinstance(sample, dict)
            ),
            "samples_with_failures": sum(
                1
                for sample in samples
                if isinstance(sample, dict) and sample.get("failures")
            ),
            "samples_with_review_flags": sum(
                1
                for sample in samples
                if isinstance(sample, dict) and sample.get("review_flags")
            ),
            "samples_with_output_sync_failures": sum(
                1
                for sample in samples
                if isinstance(sample, dict)
                and isinstance(sample.get("output_sync"), dict)
                and (
                    sample["output_sync"].get("problem_label_mismatch")
                    or sample["output_sync"].get("source_marker_mismatch")
                    or sample["output_sync"].get("choice_count_mismatch_count")
                )
            ),
            "samples_with_object_sync_failures": sum(
                1
                for sample in samples
                if isinstance(sample, dict)
                and isinstance(sample.get("object_sync"), dict)
                and sample["object_sync"].get("mismatches")
            ),
            "samples_with_problem_inventory_failures": sum(
                1
                for sample in samples
                if isinstance(sample, dict)
                and isinstance(sample.get("problem_inventory"), dict)
                and sample["problem_inventory"].get("mismatch_count")
            ),
            "samples_with_text_sync_failures": sum(
                1
                for sample in samples
                if isinstance(sample, dict)
                and isinstance(sample.get("text_sync"), dict)
                and sample["text_sync"].get("missing_count")
            ),
            "samples_with_equation_visibility_failures": sum(
                1
                for sample in samples
                if isinstance(sample, dict) and _equation_visibility_failed(sample.get("equation_visibility"))
            ),
            "samples_with_mojibake": sum(
                1
                for sample in samples
                if isinstance(sample, dict) and sample.get("mojibake_hits")
            ),
            "total_native_equations": sum(
                int((sample.get("inspect") or {}).get("native_equations") or 0)
                for sample in samples
                if isinstance(sample, dict) and isinstance(sample.get("inspect"), dict)
            ),
            "total_render_overflows": sum(
                int((sample.get("render") or {}).get("overflow_count") or 0)
                for sample in samples
                if isinstance(sample, dict) and isinstance(sample.get("render"), dict)
            ),
            "samples": samples,
        }
    elif sample_report is None:
        summary["hwp_samples"] = {"missing": True}
    else:
        summary["hwp_samples"] = sample_report
    return summary


def _run_check(check: Check, *, show_known_warnings: bool) -> CheckResult:
    started_at_utc = datetime.now(timezone.utc)
    started = time.monotonic()
    print(f"\n=== {check.name} ===", flush=True)
    print(" ".join(check.command), flush=True)
    try:
        completed = subprocess.run(
            check.command,
            cwd=str(ROOT),
            capture_output=True,
            timeout=check.timeout,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - started
        print(f"TIMEOUT after {elapsed:.1f}s: {check.name}", file=sys.stderr, flush=True)
        return CheckResult(
            name=check.name,
            command=check.command,
            returncode=124,
            elapsed_seconds=round(elapsed, 3),
            manifest_fallback_warnings=0,
            crlf_warnings=0,
        )
    stdout = _filter_known_noise(_decode_output(completed.stdout or b""), show_known_warnings=show_known_warnings)
    stderr = _filter_known_noise(_decode_output(completed.stderr or b""), show_known_warnings=show_known_warnings)
    _print_filtered_output("stdout", stdout)
    _print_filtered_output("stderr", stderr)
    elapsed = time.monotonic() - started
    if completed.returncode == 0:
        print(f"PASS {check.name} ({elapsed:.1f}s)", flush=True)
    else:
        print(f"FAIL {check.name} ({elapsed:.1f}s, exit {completed.returncode})", file=sys.stderr, flush=True)
    return CheckResult(
        name=check.name,
        command=check.command,
        returncode=int(completed.returncode),
        elapsed_seconds=round(elapsed, 3),
        manifest_fallback_warnings=stdout.manifest_fallback_warnings + stderr.manifest_fallback_warnings,
        crlf_warnings=stdout.crlf_warnings + stderr.crlf_warnings,
    )


def _checks(args: argparse.Namespace) -> list[Check]:
    checks = [
        Check(
            "frontend formula detection and native-math UI payload",
            ["node", "scripts/verify_frontend_math.js"],
            120,
        ),
        Check(
            "native HWPX equation corpus",
            [sys.executable, "scripts/verify_hwpx_native_math.py"],
            120,
        ),
        Check(
            "synthetic PDF math import to native HWPX equations",
            [sys.executable, "scripts/verify_pdf_math_pipeline.py"],
            120,
        ),
        Check(
            "import/export roundtrip and API preview/export sync",
            [sys.executable, "scripts/verify_importers.py"],
            180,
        ),
        Check(
            "HWPX v2 template coverage",
            [sys.executable, "scripts/coverage_hwpx_v2.py"],
            180,
        ),
    ]
    if not args.skip_samples:
        checks.append(
            Check(
                "real HWP math samples: native math, layout, sync, render bounds",
                [
                    sys.executable,
                    "scripts/qa_hwp_math_samples.py",
                    "--save-pages",
                    str(args.save_pages),
                    "--save-source-pages",
                    str(args.save_source_pages),
                ],
                300,
            )
        )
    if not args.skip_git_check:
        checks.append(
            Check(
                "git whitespace check",
                ["git", "diff", "--check"],
                120,
            )
        )
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the full math exam HWPX QA gate.")
    parser.add_argument(
        "--skip-samples",
        action="store_true",
        help="Skip the slow real-HWP sample render QA.",
    )
    parser.add_argument(
        "--save-pages",
        type=int,
        default=-1,
        help="Page PNG count passed to qa_hwp_math_samples.py; -1 saves all pages.",
    )
    parser.add_argument(
        "--save-source-pages",
        type=int,
        default=-1,
        help="Source HWP page PNG count passed to qa_hwp_math_samples.py; -1 saves all pages.",
    )
    parser.add_argument(
        "--skip-git-check",
        action="store_true",
        help="Skip git diff --check.",
    )
    parser.add_argument(
        "--show-known-warnings",
        action="store_true",
        help="Print repeated non-fatal manifest fallback and CRLF warnings instead of summarizing them.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=ROOT / "data" / "exports" / "math_exam_pipeline_report.json",
        help="JSON report path for the full QA gate result.",
    )
    args = parser.parse_args(argv)

    started_at_utc = datetime.now(timezone.utc)
    started = time.monotonic()
    results: list[CheckResult] = []
    failures: list[CheckResult] = []
    for check in _checks(args):
        result = _run_check(check, show_known_warnings=args.show_known_warnings)
        results.append(result)
        if result.returncode != 0:
            failures.append(result)
            break

    elapsed = time.monotonic() - started
    report = {
        "ok": not failures,
        "started_at_utc": started_at_utc.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "skip_samples": bool(args.skip_samples),
        "skip_git_check": bool(args.skip_git_check),
        "save_pages": int(args.save_pages),
        "save_source_pages": int(args.save_source_pages),
        "checks": [
            {
                "name": result.name,
                "command": result.command,
                "returncode": result.returncode,
                "elapsed_seconds": result.elapsed_seconds,
                "manifest_fallback_warnings": result.manifest_fallback_warnings,
                "crlf_warnings": result.crlf_warnings,
            }
            for result in results
        ],
        "artifacts": _artifact_summary(),
    }
    report_path = args.report_path.expanduser()
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Summary ===", flush=True)
    print(f"Report: {report_path}", flush=True)
    if failures:
        for result in failures:
            print(f"FAIL {result.name}: exit {result.returncode}", flush=True)
        print(f"RESULT: FAIL ({elapsed:.1f}s)", flush=True)
        return failures[0].returncode or 1
    print(f"RESULT: ALL OK ({elapsed:.1f}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
