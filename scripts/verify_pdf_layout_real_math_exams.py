# -*- coding: utf-8 -*-
"""Regression gate for actual math-exam PDF -> HWPX layout export.

This gate intentionally uses real completed math exam PDFs when they are
available locally. It checks the acceptance criteria that matter for the final
artifact: visual sync against the source PDF, no full-page raster fallback,
complete BinData manifest references, KICE-style page/font profile, and
editor-open safety.
"""

from __future__ import annotations

import argparse
import base64
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
from scripts.verify_pdf_layout_hwpx import verify as verify_hwpx  # noqa: E402


DEFAULT_SAMPLE_NAMES = (
    "\uc218\ud559A_\uc9dd\uc218\ud615_\ucd5c\uc885.pdf",
    "\uc218\ud559B_\uc9dd\uc218\ud615_\ucd5c\uc885.pdf",
)
REPORT_PATH = storage.EXPORT_DIR / "pdf_layout_real_math_exam_report.json"
B4_PRINT_SCALE = 1.14
STANDARD_PAGES_MM = (
    ("A4", 210.0, 297.0),
    ("B4", 257.0, 364.0),
    ("B4_114", 257.0 * B4_PRINT_SCALE, 364.0 * B4_PRINT_SCALE),
    ("A3", 297.0, 420.0),
)
PAGE_SNAP_TOLERANCE_PT = 2.0


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
    return sorted(
        unique.values(),
        key=lambda item: (len(item.name), -item.stat().st_mtime),
    )


def _find_samples(requested: list[str] | None) -> list[Path]:
    if requested:
        result: list[Path] = []
        for value in requested:
            candidate = Path(value)
            if candidate.exists():
                result.append(candidate)
                continue
            for folder in _candidate_dirs():
                matches = _ranked_name_matches(folder, value)
                if matches:
                    result.append(matches[0])
                    break
        return result

    result = []
    for name in DEFAULT_SAMPLE_NAMES:
        for folder in _candidate_dirs():
            matches = _ranked_name_matches(folder, name)
            if matches:
                result.append(matches[0])
                break
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in result:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def _check(name: str, condition: bool, detail: str = "", failures: list[str] | None = None) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}{(' - ' + detail) if detail and not condition else ''}")
    if not condition and failures is not None:
        failures.append(f"{name}: {detail}".rstrip(": "))


def _pt_from_mm(value_mm: float) -> float:
    return float(value_mm) * 72.0 / 25.4


def _match_page_standard(width_pt: float, height_pt: float) -> str | None:
    for name, standard_width_mm, standard_height_mm in STANDARD_PAGES_MM:
        standard_width_pt = _pt_from_mm(standard_width_mm)
        standard_height_pt = _pt_from_mm(standard_height_mm)
        if (
            abs(width_pt - standard_width_pt) <= PAGE_SNAP_TOLERANCE_PT
            and abs(height_pt - standard_height_pt) <= PAGE_SNAP_TOLERANCE_PT
        ):
            return name
        if (
            abs(width_pt - standard_height_pt) <= PAGE_SNAP_TOLERANCE_PT
            and abs(height_pt - standard_width_pt) <= PAGE_SNAP_TOLERANCE_PT
        ):
            return name
    return None


def _source_page_standards(path: Path, max_pages: int | None) -> list[dict[str, Any]]:
    standards: list[dict[str, Any]] = []
    with fitz.open(path) as document:
        total_pages = len(document) if max_pages is None else min(len(document), max_pages)
        for index in range(total_pages):
            page = document[index]
            width_pt = float(page.rect.width)
            height_pt = float(page.rect.height)
            standards.append(
                {
                    "page": index + 1,
                    "width_pt": round(width_pt, 3),
                    "height_pt": round(height_pt, 3),
                    "width_mm": round(width_pt * 25.4 / 72.0, 3),
                    "height_mm": round(height_pt * 25.4 / 72.0, 3),
                    "standard_name": _match_page_standard(width_pt, height_pt) or "",
                }
            )
    return standards


def _source_page_count(path: Path) -> int:
    with fitz.open(path) as document:
        return len(document)


def _expected_output_standards(source_standard_names: list[str]) -> list[str]:
    expected = {"B4_114" if name == "A3" else name for name in source_standard_names}
    return sorted(expected)


def _has_scale(values: list[Any], target: float) -> bool:
    for value in values:
        try:
            if abs(float(value) - target) <= 0.001:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _all_source_pages_portrait(source_page_standards: list[dict[str, Any]]) -> bool:
    return all(float(item.get("width_pt") or 0.0) <= float(item.get("height_pt") or 0.0) for item in source_page_standards)


def _all_output_pages_portrait(style_profile: dict[str, Any]) -> bool:
    page_sizes = style_profile.get("page_sizes") or []
    return bool(page_sizes) and all(
        float(item.get("width_mm") or 0.0) <= float(item.get("height_mm") or 0.0) for item in page_sizes
    )


def _run_one(
    client: TestClient,
    path: Path,
    *,
    max_pages: int | None,
    min_objective_score: float,
    min_math_visual_score: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    response = client.post(
        "/api/pdf-layout-export",
        json={
            "filename": path.name,
            "data_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
            "max_pages": max_pages,
            "layout_mode": "structured",
            "native_math": True,
        },
    )
    elapsed = round(time.perf_counter() - started, 3)
    failures: list[str] = []
    if response.status_code != 200:
        return {
            "source": str(path),
            "elapsed_seconds": elapsed,
            "status_code": response.status_code,
            "failures": [response.text[:1000]],
        }

    payload = response.json()
    output_path = storage.EXPORT_DIR / str((payload.get("export") or {}).get("name") or "")
    report_path = storage.EXPORT_DIR / str(((payload.get("run") or {}).get("report") or {}).get("name") or "")
    quality = payload.get("quality") or {}
    stats = payload.get("stats") or {}
    components = quality.get("score_components") or {}
    math_component = components.get("math") or {}
    fidelity = payload.get("fidelity") or {}
    style_profile = payload.get("style_profile") or {}
    structured_mode = stats.get("layout_mode") == "structured"
    visual_math_mode = stats.get("layout_mode") == "structured_math_visual_overlay"
    ai_accepted = int(stats.get("math_ai_accepted") or 0)
    open_safety = validate_editor_open_safety(output_path) if output_path.exists() else None
    structure_issues = (
        verify_hwpx(
            output_path,
            render=False,
            allow_draw_text_equations=ai_accepted > 0,
            require_pdf_font_faces=not structured_mode,
        )
        if output_path.exists()
        else ["missing output HWPX"]
    )
    total_source_pages = _source_page_count(path)
    source_page_standards = _source_page_standards(path, max_pages)
    expected_pages = total_source_pages if max_pages is None else min(total_source_pages, max_pages)
    source_standard_names = sorted(
        {str(item.get("standard_name") or "") for item in source_page_standards if item.get("standard_name")}
    )
    output_standard_names = sorted({str(value) for value in style_profile.get("page_standard_names") or []})
    expected_output_standard_names = ["A4"] if structured_mode else _expected_output_standards(source_standard_names)

    _check(
        "objective score",
        float(quality.get("objective_score") or 0.0) >= min_objective_score,
        repr(quality.get("objective_score")),
        failures,
    )
    _check("objective target pass", quality.get("meets_objective_score_target") is True, repr(quality), failures)
    if structured_mode:
        _check("structured paragraphs", int(stats.get("paragraphs") or 0) > 0, repr(stats), failures)
        _check("no draw-text boxes", int(stats.get("draw_text_boxes") or 0) == 0, repr(stats), failures)
    else:
        _check("visual sync target", quality.get("meets_visual_sync_target") is True, repr(quality), failures)
        _check("layout-view sync target", quality.get("meets_layout_view_sync_target") is True, repr(quality), failures)
        _check(
            "math visual score",
            float(math_component.get("math_visual_score") or 0.0) >= min_math_visual_score,
            repr(math_component),
            failures,
        )
    _check("math visual target", quality.get("meets_math_visual_sync_target") is True, repr(quality), failures)
    _check("source math segments present", int(stats.get("source_math_segments") or 0) > 0, repr(stats), failures)
    native_equations = int(stats.get("native_equations") or 0)
    if structured_mode:
        _check("native math enabled", stats.get("native_math_enabled") is True, repr(stats), failures)
        _check(
            "native equations cover math",
            native_equations >= int(stats.get("source_math_segments") or 0) > 0,
            repr(stats),
            failures,
        )
        _check(
            "no unresolved math placeholders",
            int(stats.get("unresolved_math_placeholders") or 0) == 0,
            repr(stats),
            failures,
        )
    else:
        _check("positioned native math enabled", stats.get("native_math_enabled") is True, repr(stats), failures)
        _check(
            "positioned native equations cover math",
            native_equations >= int(stats.get("source_math_segments") or 0) > 0
            and float(stats.get("native_math_coverage_ratio") or 0.0) >= 0.90,
            repr(stats),
            failures,
        )
    _check(
        "full source pages converted",
        int(stats.get("pages") or 0) == expected_pages,
        f"source={total_source_pages} expected={expected_pages} stats={stats.get('pages')}",
        failures,
    )
    if max_pages is None:
        _check(
            "no page limit applied",
            quality.get("limited_by_max_pages") is False
            and (structured_mode or fidelity.get("limited_by_max_pages") is False),
            repr({"quality": quality.get("limited_by_max_pages"), "fidelity": fidelity.get("limited_by_max_pages")}),
            failures,
        )
    if visual_math_mode:
        _check("math visual overlays present", int(stats.get("math_visual_overlays") or 0) > 0, repr(stats), failures)
        _check("math visual overlay option on", bool(stats.get("math_visual_overlay_enabled")), repr(stats), failures)
        _check(
            "math visual overlay area bounded",
            0.0 < float(stats.get("math_visual_overlay_area_ratio") or 0.0) < 0.25,
            repr(stats),
            failures,
        )
    else:
        _check("math visual overlays disabled", int(stats.get("math_visual_overlays") or 0) == 0, repr(stats), failures)
        _check("math visual overlay option off", not bool(stats.get("math_visual_overlay_enabled")), repr(stats), failures)
        _check(
            "math visual overlay area zero",
            float(stats.get("math_visual_overlay_area_ratio") or 0.0) == 0.0,
            repr(stats),
            failures,
        )
    if not structured_mode:
        _check("fraction rule lines restored", int(stats.get("fraction_rule_lines") or 0) > 0, repr(stats), failures)
        _check("math char bbox text restored", int(stats.get("math_char_text_items") or 0) > 0, repr(stats), failures)
    _check("no full-page raster fallback", stats.get("full_page_raster_fallback") is False, repr(stats), failures)
    _check("no full-page images", int(stats.get("full_page_images") or 0) == 0, repr(stats), failures)
    if structured_mode or visual_math_mode:
        _check(
            "source text preservation >= 98%",
            float(stats.get("source_text_preservation_ratio") or 0.0) >= 0.98,
            repr(stats),
            failures,
        )
    _check("exam font faces", style_profile.get("has_required_font_faces") is True, repr(style_profile), failures)
    _check("exam char metrics", style_profile.get("char_metric_ok") is True, repr(style_profile), failures)
    _check("exam font size bucket", style_profile.get("font_size_bucket_ok") is True, repr(style_profile), failures)
    _check("exam line spacing", style_profile.get("uses_exam_line_spacing") is True, repr(style_profile), failures)
    if structured_mode:
        _check("exam page margins", style_profile.get("page_margin_profile_ok") is True, repr(style_profile), failures)
        _check("exam column gap", style_profile.get("column_gap_profile_ok") is True, repr(style_profile), failures)
    _check("source page standard detected", bool(source_standard_names), repr(source_page_standards), failures)
    _check("source pages portrait", _all_source_pages_portrait(source_page_standards), repr(source_page_standards), failures)
    _check("exam page ratio", style_profile.get("page_ratio_ok") is True, repr(style_profile), failures)
    _check("exam pages portrait", style_profile.get("page_portrait_ok") is True, repr(style_profile), failures)
    _check("exam page sizes portrait", _all_output_pages_portrait(style_profile), repr(style_profile), failures)
    _check("exam page standard", style_profile.get("page_standard_ok") is True, repr(style_profile), failures)
    _check("exam physical page", style_profile.get("page_physical_size_ok") is True, repr(style_profile), failures)
    _check(
        "exam page standard matches print target",
        output_standard_names == expected_output_standard_names,
        f"source={source_standard_names!r} expected={expected_output_standard_names!r} output={output_standard_names!r}",
        failures,
    )
    if not structured_mode and "B4_114" in expected_output_standard_names:
        _check(
            "exam B4 print paper",
            style_profile.get("page_print_paper_names") == ["B4"],
            repr(style_profile),
            failures,
        )
        _check(
            "exam 114% print scale",
            _has_scale(list(style_profile.get("page_print_scale_values") or []), B4_PRINT_SCALE),
            repr(style_profile),
            failures,
        )
    _check("quality page standard target", quality.get("meets_page_standard_target") is True, repr(quality), failures)
    _check("editor-open safety", bool(open_safety and open_safety.ok), open_safety.summary if open_safety else "", failures)
    _check("HWPX structure", not structure_issues, "; ".join(structure_issues[:6]), failures)
    _check("fidelity review flags clean", fidelity.get("review_flags") == [], repr(fidelity), failures)
    if structured_mode:
        _check("coordinate fidelity skipped", fidelity.get("skipped") is True, repr(fidelity), failures)
    else:
        _check("fidelity available", bool(fidelity.get("available")) and not fidelity.get("skipped"), repr(fidelity), failures)
        _check("pages compared", int(fidelity.get("pages_compared") or 0) == int(stats.get("pages") or 0), repr(fidelity), failures)
        _check(
            "all converted pages compared",
            int(fidelity.get("pages_compared") or 0) == expected_pages,
            f"expected={expected_pages} fidelity={fidelity.get('pages_compared')}",
            failures,
        )
        _check("fidelity not truncated", fidelity.get("truncated") is False, repr(fidelity), failures)
        _check("fidelity page count matched", fidelity.get("page_count_mismatch") is False, repr(fidelity), failures)
        _check(
            "strict alignment floor",
            float(fidelity.get("min_strict_alignment_ratio") or 0.0) >= 0.94,
            repr(fidelity),
            failures,
        )
        _check(
            "foreground overlap floor",
            float(fidelity.get("min_foreground_overlap_ratio") or 0.0) >= 0.80,
            repr(fidelity),
            failures,
        )

    return {
        "source": str(path),
        "output": str(output_path),
        "report": str(report_path),
        "elapsed_seconds": elapsed,
        "source_page_count": total_source_pages,
        "expected_pages": expected_pages,
        "quality": {
            "objective_score": quality.get("objective_score"),
            "layout_view_sync_ratio": quality.get("layout_view_sync_ratio"),
            "visual_sync_ratio": quality.get("visual_sync_ratio"),
            "whole_page_visual_sync_ratio": quality.get("whole_page_visual_sync_ratio"),
            "meets_objective_score_target": quality.get("meets_objective_score_target"),
            "meets_visual_sync_target": quality.get("meets_visual_sync_target"),
            "meets_layout_view_sync_target": quality.get("meets_layout_view_sync_target"),
            "meets_math_visual_sync_target": quality.get("meets_math_visual_sync_target"),
            "meets_page_standard_target": quality.get("meets_page_standard_target"),
        },
        "math_component": math_component,
        "fidelity": {
            "available": fidelity.get("available"),
            "pdf_page_count": fidelity.get("pdf_page_count"),
            "hwpx_page_count": fidelity.get("hwpx_page_count"),
            "pages_compared": fidelity.get("pages_compared"),
            "truncated": fidelity.get("truncated"),
            "limited_by_max_pages": fidelity.get("limited_by_max_pages"),
            "page_count_mismatch": fidelity.get("page_count_mismatch"),
            "aspect_ratio_mismatch_pages": fidelity.get("aspect_ratio_mismatch_pages") or [],
            "review_flags": fidelity.get("review_flags") or [],
            "min_strict_alignment_ratio": fidelity.get("min_strict_alignment_ratio"),
            "min_foreground_overlap_ratio": fidelity.get("min_foreground_overlap_ratio"),
        },
        "stats": stats,
        "style_profile": style_profile,
        "source_page_standards": source_page_standards,
        "expected_output_standard_names": expected_output_standard_names,
        "open_safety": open_safety.to_dict() if open_safety else {"ok": False},
        "structure_issues": structure_issues,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify actual math PDF layout export artifacts.")
    parser.add_argument("--sample", action="append", help="PDF filename/path. Repeatable.")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Limit pages for a debug run. Omit for final full-document verification.",
    )
    parser.add_argument("--min-objective-score", type=float, default=98.0)
    parser.add_argument("--min-math-visual-score", type=float, default=95.0)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()

    samples = _find_samples(args.sample)
    if not samples:
        print("No actual math exam PDFs found; pass --sample or place files in data/uploads or Downloads/문서.")
        return 2

    client = TestClient(app)
    reports = [
        _run_one(
            client,
            sample,
            max_pages=args.max_pages,
            min_objective_score=args.min_objective_score,
            min_math_visual_score=args.min_math_visual_score,
        )
        for sample in samples
    ]
    failed = any(report.get("failures") for report in reports)
    report = {
        "ok": not failed,
        "min_objective_score": args.min_objective_score,
        "min_math_visual_score": args.min_math_visual_score,
        "max_pages": args.max_pages,
        "full_document": args.max_pages is None,
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
        style_profile = item.get("style_profile") or {}
        print(
            f"- {Path(str(item.get('source'))).name}: "
            f"pages={((item.get('stats') or {}).get('pages'))}/{item.get('source_page_count')} "
            f"objective={quality.get('objective_score')} "
            f"layout={quality.get('layout_view_sync_ratio')} "
            f"visual={quality.get('visual_sync_ratio')} "
            f"math={((item.get('math_component') or {}).get('math_visual_score'))} "
            f"page={','.join(style_profile.get('page_standard_names') or [])} "
            f"print={','.join(style_profile.get('page_print_paper_names') or [])}:"
            f"{','.join(str(value) for value in (style_profile.get('page_print_scale_values') or []))} "
            f"status={'FAIL' if item.get('failures') else 'OK'}"
        )
        for failure in item.get("failures") or []:
            print(f"  - {failure}")
    print(f"Report: {report_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
