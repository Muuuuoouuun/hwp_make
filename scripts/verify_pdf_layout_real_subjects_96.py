from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
VENDOR = ROOT / "app" / "_vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import fitz  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from hwpx.tools.package_validator import validate_editor_open_safety  # noqa: E402

from app import storage  # noqa: E402
from app.main import app  # noqa: E402
from scripts.qa_hwp_math_samples import _render_hwpx  # noqa: E402
from scripts.verify_hwpx_native_math import _equation_object_issues  # noqa: E402

REPORT_PATH = storage.EXPORT_DIR / "pdf_layout_real_subjects_98_report.json"
DEFAULT_SUBJECTS = (
    ("korean", "\uad6d\uc5b4", "25\uc218\ub2a5 \uad6d\uc5b4.pdf"),
    ("english", "\uc601\uc5b4", "25\uc218\ub2a5 \uc601\uc5b4.pdf"),
    ("math_a", "\uc218\ud559", "\uc218\ud559A_\uc9dd\uc218\ud615_\ucd5c\uc885.pdf"),
    ("math_b", "\uc218\ud559", "\uc218\ud559B_\uc9dd\uc218\ud615_\ucd5c\uc885.pdf"),
)


def _candidate_dirs() -> list[Path]:
    home = Path.home()
    return [
        ROOT / "data" / "uploads",
        home / "Downloads" / "\ubb38\uc11c",
        home / "Downloads",
    ]


def _ranked_name_matches(folder: Path, name: str) -> list[Path]:
    candidates: list[Path] = []
    direct = folder / name
    if direct.exists():
        candidates.append(direct)
    candidates.extend(folder.glob(f"*{name}"))
    unique = {path.resolve(): path for path in candidates}
    return sorted(unique.values(), key=lambda item: (len(item.name), -item.stat().st_mtime))


def _find_default_samples() -> list[tuple[str, str, Path]]:
    samples: list[tuple[str, str, Path]] = []
    for subject, family, name in DEFAULT_SUBJECTS:
        for folder in _candidate_dirs():
            matches = _ranked_name_matches(folder, name)
            if matches:
                samples.append((subject, family, matches[0]))
                break
    return samples


def _source_page_count(path: Path) -> int:
    with fitz.open(path) as document:
        return len(document)


def _check(name: str, condition: bool, detail: str, failures: list[str]) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}{(' - ' + detail) if detail and not condition else ''}")
    if not condition:
        failures.append(f"{name}: {detail}".rstrip(": "))


def _run_one(
    client: TestClient,
    *,
    subject: str,
    family: str,
    path: Path,
    min_objective_score: float,
    min_layout_view_sync: float,
    min_math_visual_score: float,
) -> dict[str, Any]:
    print(f"\nRUN {subject}: {path}")
    started = time.perf_counter()
    response = client.post(
        "/api/pdf-layout-export",
        json={
            "filename": path.name,
            "data_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
            "layout_mode": "structured",
            "native_math": True,
        },
    )
    elapsed = round(time.perf_counter() - started, 3)
    failures: list[str] = []
    if response.status_code != 200:
        failures.append(f"HTTP {response.status_code}: {response.text[:1000]}")
        return {
            "subject": subject,
            "family": family,
            "source": str(path),
            "elapsed_seconds": elapsed,
            "failures": failures,
        }

    payload = response.json()
    export_name = str((payload.get("export") or {}).get("name") or "")
    output_path = storage.EXPORT_DIR / export_name
    report_name = str(((payload.get("run") or {}).get("report") or {}).get("name") or "")
    report_path = storage.EXPORT_DIR / report_name
    quality = payload.get("quality") or {}
    stats = payload.get("stats") or {}
    fidelity = payload.get("fidelity") or {}
    style_profile = payload.get("style_profile") or {}
    components = quality.get("score_components") or {}
    math_component = components.get("math") or {}
    expected_pages = _source_page_count(path)
    structure_issues = _equation_object_issues(output_path) if output_path.exists() else ["missing output HWPX"]
    open_safety = validate_editor_open_safety(output_path) if output_path.exists() else None
    render = (
        _render_hwpx(output_path, storage.EXPORT_DIR / "structured_qa_renders", save_pages=200)
        if output_path.exists()
        else {"available": False, "error": "missing output HWPX"}
    )
    rendered_pages = [Path(item) for item in render.get("saved_pages") or []]
    rendered_hashes = [hashlib.sha256(item.read_bytes()).hexdigest() for item in rendered_pages if item.is_file()]
    duplicate_rendered_pages = len(rendered_hashes) - len(set(rendered_hashes))
    target_render_pages = int(stats.get("output_page_count_target") or 0)
    actual_render_pages = int(render.get("page_count") or 0)
    layout_component = components.get("layout") or {}
    page_count_ratio = (
        min(target_render_pages, actual_render_pages) / max(target_render_pages, actual_render_pages)
        if target_render_pages > 0 and actual_render_pages > 0
        else 0.0
    )
    rendered_layout_score = round(
        page_count_ratio * 35.0
        + (15.0 if int(render.get("overflow_count") or 0) == 0 else 0.0)
        + (10.0 if duplicate_rendered_pages == 0 else 0.0)
        + min(15.0, float(stats.get("source_layout_coverage_ratio") or 0.0) * 15.0)
        + (10.0 if layout_component.get("page_breaks_match") is True else 0.0)
        + (10.0 if layout_component.get("column_breaks_match") is True else 0.0)
        + (5.0 if style_profile.get("page_margin_profile_ok") is True else 0.0),
        2,
    )

    _check("objective score >= target", float(quality.get("objective_score") or 0.0) >= min_objective_score, repr(quality.get("objective_score")), failures)
    _check("structured mode", stats.get("layout_mode") == "structured", repr(stats.get("layout_mode")), failures)
    _check("font target", quality.get("meets_font_template_target") is True, repr(quality), failures)
    _check("paging target", quality.get("meets_paging_target") is True, repr(quality), failures)
    _check("page standard target", quality.get("meets_page_standard_target") is True, repr(quality), failures)
    _check("open safety target", quality.get("meets_open_safety_target") is True, repr(quality), failures)
    _check("full source pages converted", int(stats.get("pages") or 0) == expected_pages, f"expected={expected_pages} stats={stats.get('pages')}", failures)
    _check("problem completeness", int(stats.get("output_problem_count") or 0) == int(stats.get("source_problem_count") or 0), repr(stats), failures)
    _check("no duplicate problems", int(stats.get("duplicate_problem_count") or 0) == 0, repr(stats), failures)
    _check("no unreliable problem text", int(stats.get("unreliable_text_problems") or 0) == 0, repr(stats), failures)
    _check("editable coverage", float(stats.get("editable_text_coverage_ratio") or 0.0) >= 0.9, repr(stats), failures)
    _check(
        "source text preservation >= 98%",
        float(stats.get("source_text_preservation_ratio") or 0.0) >= 0.98,
        repr(stats),
        failures,
    )
    _check("no drawText boxes", int(stats.get("draw_text_boxes") or 0) == 0, repr(stats), failures)
    _check("no full-page raster fallback", stats.get("full_page_raster_fallback") is False, repr(stats), failures)
    _check("no full-page images", int(stats.get("full_page_images") or 0) == 0, repr(stats), failures)
    _check("no unresolved math placeholders", int(stats.get("unresolved_math_placeholders") or 0) == 0, repr(stats), failures)
    _check("HWPX structure", not structure_issues, "; ".join(structure_issues[:6]), failures)
    _check("editor-open safety", bool(open_safety and open_safety.ok), open_safety.summary if open_safety else "", failures)
    _check("render available", bool(render.get("available")) and not render.get("error"), repr(render.get("error")), failures)
    _check("rendered page count matches source layout", actual_render_pages == target_render_pages, f"target={target_render_pages} actual={actual_render_pages}", failures)
    _check("rendered layout score >= 98", rendered_layout_score >= 98.0, repr(rendered_layout_score), failures)
    _check("render overflow clean", int(render.get("overflow_count") or 0) == 0, repr(render.get("overflow_lines")), failures)
    _check("no duplicate rendered pages", duplicate_rendered_pages == 0, repr(duplicate_rendered_pages), failures)
    _check("style profile available", style_profile.get("available") is True, repr(style_profile), failures)
    _check("required font faces", style_profile.get("has_required_font_faces") is True, repr(style_profile), failures)
    _check("required font types", style_profile.get("font_face_type_ok") is True, repr(style_profile), failures)
    _check("char metrics", style_profile.get("char_metric_ok") is True, repr(style_profile), failures)
    _check("font size bucket", style_profile.get("font_size_bucket_ok") is True, repr(style_profile), failures)
    _check("exam line spacing", style_profile.get("uses_exam_line_spacing") is True, repr(style_profile), failures)
    _check("exam page margins", style_profile.get("page_margin_profile_ok") is True, repr(style_profile), failures)
    _check("exam column gap", style_profile.get("column_gap_profile_ok") is True, repr(style_profile), failures)
    _check("Hancom page orientation", style_profile.get("page_orientation_ok") is True, repr(style_profile), failures)
    if int(stats.get("source_math_segments") or 0) > 0:
        _check(
            "native math coverage",
            float(stats.get("native_math_coverage_ratio") or 0.0) >= 0.95,
            repr(math_component),
            failures,
        )

    return {
        "subject": subject,
        "family": family,
        "source": str(path),
        "output": str(output_path),
        "report": str(report_path),
        "elapsed_seconds": elapsed,
        "expected_pages": expected_pages,
        "quality": {
            "objective_score": quality.get("objective_score"),
            "layout_view_sync_ratio": quality.get("layout_view_sync_ratio"),
            "visual_sync_ratio": quality.get("visual_sync_ratio"),
            "whole_page_visual_sync_ratio": quality.get("whole_page_visual_sync_ratio"),
            "meets_objective_score_target": quality.get("meets_objective_score_target"),
            "meets_visual_sync_target": quality.get("meets_visual_sync_target"),
            "meets_layout_view_sync_target": quality.get("meets_layout_view_sync_target"),
            "meets_page_standard_target": quality.get("meets_page_standard_target"),
        },
        "math_component": math_component,
        "stats": stats,
        "fidelity": {
            "available": fidelity.get("available"),
            "pdf_page_count": fidelity.get("pdf_page_count"),
            "hwpx_page_count": fidelity.get("hwpx_page_count"),
            "pages_compared": fidelity.get("pages_compared"),
            "page_count_mismatch": fidelity.get("page_count_mismatch"),
            "review_flags": fidelity.get("review_flags") or [],
            "overall_layout_view_sync_ratio": fidelity.get("overall_layout_view_sync_ratio"),
            "overall_sync_ratio": fidelity.get("overall_sync_ratio"),
            "min_strict_alignment_ratio": fidelity.get("min_strict_alignment_ratio"),
            "min_foreground_overlap_ratio": fidelity.get("min_foreground_overlap_ratio"),
        },
        "style_profile": {
            "has_required_font_faces": style_profile.get("has_required_font_faces"),
            "font_face_type_ok": style_profile.get("font_face_type_ok"),
            "char_metric_ok": style_profile.get("char_metric_ok"),
            "font_size_bucket_ok": style_profile.get("font_size_bucket_ok"),
            "uses_exam_line_spacing": style_profile.get("uses_exam_line_spacing"),
            "line_spacing_values": style_profile.get("line_spacing_values") or [],
            "page_margin_profile_ok": style_profile.get("page_margin_profile_ok"),
            "page_margins": style_profile.get("page_margins") or [],
            "column_gap_profile_ok": style_profile.get("column_gap_profile_ok"),
            "column_gaps_mm": style_profile.get("column_gaps_mm") or [],
            "page_orientation_ok": style_profile.get("page_orientation_ok"),
            "page_standard_names": style_profile.get("page_standard_names") or [],
            "page_print_paper_names": style_profile.get("page_print_paper_names") or [],
            "page_print_scale_values": style_profile.get("page_print_scale_values") or [],
        },
        "open_safety": open_safety.to_dict() if open_safety else {"ok": False},
        "render": {
            "available": render.get("available"),
            "page_count": render.get("page_count"),
            "overflow_count": render.get("overflow_count"),
            "duplicate_rendered_pages": duplicate_rendered_pages,
            "target_page_count": target_render_pages,
            "rendered_layout_score": rendered_layout_score,
            "contact_sheet": render.get("contact_sheet"),
        },
        "structure_issues": structure_issues,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify real Korean, English, and Math PDF layout exports at 98+.")
    parser.add_argument("--min-objective-score", type=float, default=98.0)
    parser.add_argument("--min-layout-view-sync", type=float, default=0.94)
    parser.add_argument("--min-math-visual-score", type=float, default=95.0)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()

    samples = _find_default_samples()
    expected_subjects = {subject for subject, _family, _name in DEFAULT_SUBJECTS}
    found_subjects = {subject for subject, _family, _path in samples}
    missing = sorted(expected_subjects - found_subjects)
    if missing:
        print("Missing default samples: " + ", ".join(missing))
        return 2

    client = TestClient(app)
    reports = [
        _run_one(
            client,
            subject=subject,
            family=family,
            path=path,
            min_objective_score=args.min_objective_score,
            min_layout_view_sync=args.min_layout_view_sync,
            min_math_visual_score=args.min_math_visual_score,
        )
        for subject, family, path in samples
    ]
    failed = any(report.get("failures") for report in reports)
    report = {
        "ok": not failed,
        "min_objective_score": args.min_objective_score,
        "min_layout_view_sync": args.min_layout_view_sync,
        "min_math_visual_score": args.min_math_visual_score,
        "samples": reports,
    }
    report_path = args.report_path.expanduser()
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nSummary")
    for item in reports:
        quality = item.get("quality") or {}
        stats = item.get("stats") or {}
        math_component = item.get("math_component") or {}
        print(
            f"- {item.get('subject')}: pages={stats.get('pages')}/{item.get('expected_pages')} "
            f"objective={quality.get('objective_score')} "
            f"layout={quality.get('layout_view_sync_ratio')} "
            f"visual={quality.get('visual_sync_ratio')} "
            f"math={math_component.get('score')} "
            f"source_math={stats.get('source_math_segments')} "
            f"full_page_images={stats.get('full_page_images')} "
            f"status={'FAIL' if item.get('failures') else 'OK'}"
        )
        for failure in item.get("failures") or []:
            print(f"  - {failure}")
    print(f"Report: {report_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
