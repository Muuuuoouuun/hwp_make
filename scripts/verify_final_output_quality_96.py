from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from lxml import etree
from PIL import Image, ImageChops, ImageStat

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

from hwpx.tools.package_validator import validate_editor_open_safety  # noqa: E402
from app.pdf_layout_fidelity import analyze_pdf_hwpx_fidelity  # noqa: E402
from scripts.qa_hwp_math_samples import _inspect_hwpx, _render_hwpx  # noqa: E402


FILES = {
    "korean": "국어_최종_96점.hwpx",
    "english": "영어_최종_96점.hwpx",
    "math_a": "수학A_최종_96점.hwpx",
    "math_b": "수학B_최종_96점.hwpx",
}
MATH_SUBJECTS = {"math_a", "math_b"}
A4_WIDTH = 59528
A4_HEIGHT = 84189
EXPECTED_MARGINS = {"left": 5669, "right": 5669, "top": 5669, "bottom": 5102}


def _local(element: etree._Element) -> str:
    return etree.QName(element).localname


def _children(element: etree._Element, name: str) -> list[etree._Element]:
    return [child for child in element if _local(child) == name]


def _first(element: etree._Element, name: str) -> etree._Element | None:
    return next((item for item in element.iter() if _local(item) == name), None)


def _load_xml(path: Path) -> tuple[etree._Element, list[etree._Element]]:
    with ZipFile(path) as archive:
        header = etree.fromstring(archive.read("Contents/header.xml"))
        sections = [
            etree.fromstring(archive.read(name))
            for name in sorted(archive.namelist())
            if name.startswith("Contents/section") and name.endswith(".xml")
        ]
    return header, sections


def _font_metrics(header: etree._Element) -> dict[str, Any]:
    hangul_fonts: dict[str, str] = {}
    for face_group in (item for item in header.iter() if _local(item) == "fontface"):
        if face_group.get("lang") != "HANGUL":
            continue
        for font in _children(face_group, "font"):
            hangul_fonts[str(font.get("id") or "")] = str(font.get("face") or "")

    refs: list[str] = []
    resolved: list[str] = []
    for char_pr in (item for item in header.iter() if _local(item) == "charPr"):
        font_ref = _first(char_pr, "fontRef")
        if font_ref is None:
            continue
        ref = str(font_ref.get("hangul") or "")
        refs.append(ref)
        resolved.append(hangul_fonts.get(ref, ""))
    exact = bool(resolved) and all(face == "HY신명조" for face in resolved)
    return {
        "char_property_count": len(resolved),
        "hangul_font_refs": sorted(set(refs)),
        "resolved_hangul_fonts": sorted(set(resolved)),
        "all_character_properties_use_hy_sinmyeongjo": exact,
    }


def _geometry_metrics(sections: list[etree._Element], expected_pages: int) -> dict[str, Any]:
    page_pr = next(
        (item for section in sections for item in section.iter() if _local(item) == "pagePr"),
        None,
    )
    margin = _first(page_pr, "margin") if page_pr is not None else None
    width = int(page_pr.get("width") or 0) if page_pr is not None else 0
    height = int(page_pr.get("height") or 0) if page_pr is not None else 0
    margins = {
        key: int(margin.get(key) or 0) if margin is not None else 0
        for key in EXPECTED_MARGINS
    }

    top_tables: list[tuple[int, int, int, int, str]] = []
    for section in sections:
        for table in (item for item in section.iter() if _local(item) == "tbl"):
            parent = table.getparent()
            grand = parent.getparent() if parent is not None else None
            great = grand.getparent() if grand is not None else None
            if not (
                parent is not None
                and grand is not None
                and great is not None
                and [_local(parent), _local(grand), _local(great)] == ["run", "p", "sec"]
            ):
                continue
            size = _first(table, "sz")
            if size is None:
                continue
            text = " ".join(
                (node.text or "").strip()
                for node in table.iter()
                if _local(node) == "t" and (node.text or "").strip()
            )
            top_tables.append(
                (
                    int(table.get("rowCnt") or 0),
                    int(table.get("colCnt") or 0),
                    int(size.get("width") or 0),
                    int(size.get("height") or 0),
                    text,
                )
            )
    body_tables = [item for item in top_tables if item[1] == 2 and item[3] > 40000]
    header_tables = [item for item in top_tables if item[1] >= 3 and item[3] < 20000]
    header_titles = sum("영역" in item[4] for item in header_tables)
    return {
        "page_size": [width, height],
        "margins": margins,
        "a4_ok": abs(width - A4_WIDTH) <= 50 and abs(height - A4_HEIGHT) <= 50,
        "margins_ok": all(abs(margins[key] - value) <= 100 for key, value in EXPECTED_MARGINS.items()),
        "top_level_table_count": len(top_tables),
        "two_column_body_tables": len(body_tables),
        "running_header_tables": len(header_tables),
        "running_headers_with_subject_title": header_titles,
        "two_column_pages_ok": len(body_tables) == expected_pages,
        "running_headers_ok": len(header_tables) == expected_pages and header_titles == expected_pages,
    }


def _line_spacing_metrics(header: etree._Element, subject: str, inspect: dict[str, Any]) -> dict[str, Any]:
    spacing_nodes = [item for item in header.iter() if _local(item) == "lineSpacing"]
    values = [
        int(item.get("value") or 0)
        for item in spacing_nodes
        if str(item.get("value") or "").isdigit()
        and str(item.get("type") or "PERCENT").upper() != "FIXED"
    ]
    fixed_values = [
        int(item.get("value") or 0)
        for item in spacing_nodes
        if str(item.get("value") or "").isdigit()
        and str(item.get("type") or "").upper() == "FIXED"
    ]
    non_compact = [value for value in values if value != 100]
    if subject == "korean":
        paragraph_profile_ok = bool(non_compact) and sum(140 <= value <= 170 for value in non_compact) / len(non_compact) >= 0.9
    elif subject == "english":
        paragraph_profile_ok = bool(non_compact) and sum(110 <= value <= 170 for value in non_compact) / len(non_compact) >= 0.9
    else:
        paragraph_profile_ok = 105 in values and 115 in values
    return {
        "paragraph_line_spacing_percentages": values,
        "fixed_spacer_heights_hwp": fixed_values,
        "paragraph_profile_ok": paragraph_profile_ok,
        "equation_paragraph_count": int(inspect.get("math_paragraphs") or 0),
        "equation_lineseg_issue_count": int(inspect.get("math_lineseg_issue_count") or 0),
        "equation_lineseg_ok": int(inspect.get("math_lineseg_issue_count") or 0) == 0,
    }


def _dhash(path: Path) -> int:
    with Image.open(path) as image:
        gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        pixels = list(
            gray.get_flattened_data() if hasattr(gray, "get_flattened_data") else gray.getdata()
        )
    value = 0
    for row in range(8):
        for col in range(8):
            value = (value << 1) | int(pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    return value


def _mean_pixel_difference(left: Path, right: Path) -> float:
    with Image.open(left) as left_image, Image.open(right) as right_image:
        first = left_image.convert("L").resize((256, 362), Image.Resampling.LANCZOS)
        second = right_image.convert("L").resize(first.size, Image.Resampling.LANCZOS)
        return float(ImageStat.Stat(ImageChops.difference(first, second)).mean[0])


def _duplicate_metrics(saved_pages: list[Path]) -> dict[str, Any]:
    exact: list[list[int]] = []
    near: list[list[int]] = []
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in saved_pages]
    dhashes = [_dhash(path) for path in saved_pages]
    for left in range(len(saved_pages)):
        for right in range(left + 1, len(saved_pages)):
            if hashes[left] == hashes[right]:
                exact.append([left + 1, right + 1])
                continue
            distance = (dhashes[left] ^ dhashes[right]).bit_count()
            if distance <= 1 and _mean_pixel_difference(saved_pages[left], saved_pages[right]) <= 0.35:
                near.append([left + 1, right + 1])
    return {
        "exact_duplicate_page_pairs": exact,
        "near_duplicate_page_pairs": near,
        "duplicate_page_count": len(exact) + len(near),
    }


def _problem_anchor_metrics(subject: str, inspect: dict[str, Any], expected: int) -> dict[str, Any]:
    labels = [str(value).strip() for value in inspect.get("problem_label_numbers") or []]
    if subject not in MATH_SUBJECTS:
        found = len(labels)
        return {"expected": expected, "found": found, "ratio": min(1.0, found / max(1, expected))}

    numbers = {int(value) for value in labels if value.isdigit() and 1 <= int(value) <= expected}
    for text in inspect.get("paragraph_texts") or []:
        match = re.fullmatch(r"\s*(\d{1,2})\s*", str(text or ""))
        if match and 1 <= int(match.group(1)) <= expected:
            numbers.add(int(match.group(1)))
    for script in inspect.get("equation_scripts") or []:
        match = re.match(r"\s*(\d{1,2})\.\s*", str(script or ""))
        if match and 1 <= int(match.group(1)) <= expected:
            numbers.add(int(match.group(1)))
    return {
        "expected": expected,
        "found": len(numbers),
        "numbers": sorted(numbers),
        "ratio": min(1.0, len(numbers) / max(1, expected)),
    }


def _score_subject(
    subject: str,
    source_path: Path,
    path: Path,
    stats: dict[str, Any],
    render_dir: Path,
    fidelity_dir: Path,
) -> dict[str, Any]:
    expected_pages = int(stats.get("pages") or stats.get("source_pages") or 0)
    expected_problems = int(stats.get("source_problem_count") or 0)
    inspect = _inspect_hwpx(path)
    render = _render_hwpx(path, render_dir, save_pages=-1)
    fidelity = analyze_pdf_hwpx_fidelity(
        source_path,
        path,
        fidelity_dir / subject,
        max_pages=expected_pages,
        target_sync_ratio=0.96,
        allow_truncated_by_max_pages=True,
        artifact_mode="none",
    )
    header, sections = _load_xml(path)
    font = _font_metrics(header)
    geometry = _geometry_metrics(sections, expected_pages)
    spacing = _line_spacing_metrics(header, subject, inspect)
    saved_pages = [Path(item) for item in render.get("saved_pages") or []]
    duplicates = _duplicate_metrics(saved_pages)
    anchors = _problem_anchor_metrics(subject, inspect, expected_problems)
    open_safety = validate_editor_open_safety(path)
    bounds = [
        float(item.get("bbox_ratio", [0, 0, 0, 0])[3])
        for item in render.get("content_bounds") or []
        if item.get("bbox_ratio")
    ]
    bottom_safe = bool(bounds) and max(bounds) <= 0.96

    categories: dict[str, float] = {}
    rendered_pages = int(render.get("page_count") or 0)
    page_ratio = min(rendered_pages, expected_pages) / max(1, max(rendered_pages, expected_pages))
    pages_match = (
        rendered_pages == expected_pages
        and int(stats.get("source_pages") or 0) == expected_pages
        and int(stats.get("page_breaks") or 0) == max(0, expected_pages - 1)
    )
    categories["page_mapping"] = round(12.0 * page_ratio if not pages_match else 12.0, 2)
    categories["duplicate_control"] = 8.0 if duplicates["duplicate_page_count"] == 0 else 0.0

    no_draw_text = int(stats.get("draw_text_boxes") or 0) == 0
    no_page_raster = (
        int(stats.get("full_page_images") or 0) == 0
        and stats.get("full_page_raster_fallback") is False
    )
    text_coverage = min(
        float(stats.get("editable_text_coverage_ratio") or 0.0),
        float(stats.get("source_text_preservation_ratio") or 0.0),
    )
    categories["editable_composition"] = round(
        (5.0 if no_draw_text else 0.0)
        + (5.0 if no_page_raster else 0.0)
        + min(5.0, 5.0 * text_coverage),
        2,
    )
    categories["font"] = 10.0 if font["all_character_properties_use_hy_sinmyeongjo"] else 0.0

    math_coverage = float(stats.get("native_math_coverage_ratio") or 0.0)
    equation_issues = (
        int(inspect.get("equation_object_issue_count") or 0)
        + int(inspect.get("malformed_equation_script_count") or 0)
    )
    if subject in MATH_SUBJECTS:
        math_score = min(10.0, math_coverage * 10.0) + (5.0 if equation_issues == 0 else 0.0)
    else:
        math_score = 15.0 if int(inspect.get("equations") or 0) == 0 else 10.0
    categories["native_math"] = round(math_score, 2)

    categories["page_geometry"] = (
        (5.0 if geometry["a4_ok"] else 0.0) + (5.0 if geometry["margins_ok"] else 0.0)
    )
    categories["headers_columns"] = round(
        (4.0 if geometry["two_column_pages_ok"] else 4.0 * geometry["two_column_body_tables"] / max(1, expected_pages))
        + (3.0 if geometry["running_headers_ok"] else 3.0 * geometry["running_header_tables"] / max(1, expected_pages))
        + (3.0 if not render.get("column_crossing_issues") else 0.0),
        2,
    )
    categories["line_spacing"] = round(
        (4.0 if spacing["paragraph_profile_ok"] else 0.0)
        + (4.0 if spacing["equation_lineseg_ok"] else 0.0)
        + (2.0 if bottom_safe else 0.0),
        2,
    )
    problems_complete = int(stats.get("output_problem_count") or 0) == expected_problems
    no_problem_duplicates = int(stats.get("duplicate_problem_count") or 0) == 0
    categories["problem_integrity"] = round(
        (2.0 if problems_complete else 0.0)
        + 3.0 * float(anchors["ratio"])
        + (1.0 if no_problem_duplicates else 0.0),
        2,
    )
    expected_figures = int(stats.get("images") or 0)
    figures_found = int(inspect.get("pictures") or 0)
    figure_ok = figures_found >= expected_figures and (expected_figures > 0 or figures_found == 0)
    categories["figures"] = 4.0 if figure_ok else round(4.0 * figures_found / max(1, expected_figures), 2)

    score = round(sum(categories.values()), 2)
    hard_gates = {
        "pages_match": pages_match,
        "no_duplicate_pages": duplicates["duplicate_page_count"] == 0,
        "no_text_box_or_full_page_raster_cheat": no_draw_text and no_page_raster,
        "editor_open_safe": bool(open_safety.ok),
        "hy_sinmyeongjo_only": bool(font["all_character_properties_use_hy_sinmyeongjo"]),
        "problem_count_complete": problems_complete and anchors["ratio"] >= 1.0,
        "math_native_and_valid": (
            subject not in MATH_SUBJECTS
            or (
                math_coverage >= 0.99
                and equation_issues == 0
                and int(stats.get("unresolved_math_placeholders") or 0) == 0
                and spacing["equation_lineseg_ok"]
            )
        ),
        "rendered_layout_similarity": (
            float(fidelity.get("overall_sync_ratio") or 0.0) >= 0.96
            if subject in MATH_SUBJECTS
            else float(fidelity.get("overall_layout_view_sync_ratio") or 0.0) >= 0.925
        ),
    }
    passed = score >= 96.0 and all(hard_gates.values())
    return {
        "subject": subject,
        "file": str(path),
        "score": score,
        "passed_96": passed,
        "categories": categories,
        "hard_gates": hard_gates,
        "page_render": {
            "expected_pages": expected_pages,
            "rendered_pages": rendered_pages,
            "max_content_bottom_ratio": round(max(bounds), 4) if bounds else None,
            "bottom_safe": bottom_safe,
            "column_crossing_issues": render.get("column_crossing_issues") or [],
            "contact_sheet": render.get("contact_sheet"),
        },
        "visual_layout_gate": {
            "metric": "overall_sync_ratio" if subject in MATH_SUBJECTS else "overall_layout_view_sync_ratio",
            "threshold": 0.96 if subject in MATH_SUBJECTS else 0.925,
            "overall_sync_ratio": fidelity.get("overall_sync_ratio"),
            "overall_layout_view_sync_ratio": fidelity.get("overall_layout_view_sync_ratio"),
            "overall_detailed_layout_score_diagnostic": fidelity.get("overall_detailed_layout_score"),
            "minimum_detailed_layout_score_diagnostic": fidelity.get("minimum_detailed_layout_score"),
        },
        "duplicates": duplicates,
        "font": font,
        "geometry": geometry,
        "line_spacing": spacing,
        "problem_anchors": anchors,
        "math": {
            "source_math_segments": int(stats.get("source_math_segments") or 0),
            "native_equations": int(stats.get("native_equations") or 0),
            "native_math_coverage_ratio": math_coverage,
            "unresolved_math_placeholders": int(stats.get("unresolved_math_placeholders") or 0),
            "equation_object_issue_count": int(inspect.get("equation_object_issue_count") or 0),
            "malformed_equation_script_count": int(inspect.get("malformed_equation_script_count") or 0),
        },
        "figures": {"expected": expected_figures, "found": figures_found, "ok": figure_ok},
        "open_safety": open_safety.to_dict(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score the four final editable HWPX outputs on an independent 100-point rubric.")
    parser.add_argument(
        "--directory",
        type=Path,
        default=ROOT / "data" / "exports" / "final_results_96",
    )
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    directory = args.directory if args.directory.is_absolute() else ROOT / args.directory
    generation_path = directory / "generation_report.json"
    # 최종 산출물 패키지는 벤치마크 수동 실행 산출물(로컬 전용) — 없으면 저장소 관례대로 SKIP(exit 2).
    if not generation_path.is_file():
        print(f"SKIP: final output package missing (run the four-subject benchmark first): {generation_path}")
        return 2
    generation = json.loads(generation_path.read_text(encoding="utf-8"))
    render_dir = directory / "quality_96_renders"
    fidelity_dir = directory / "quality_96_fidelity"
    report_path = args.report or directory / "전체_품질검증_96_최종.json"
    if not report_path.is_absolute():
        report_path = ROOT / report_path

    results: list[dict[str, Any]] = []
    for subject, filename in FILES.items():
        path = directory / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        source_path = ROOT / generation[subject]["source"]
        result = _score_subject(
            subject,
            source_path,
            path,
            generation[subject]["stats"],
            render_dir,
            fidelity_dir,
        )
        results.append(result)
        print(f"{subject}: {result['score']:.2f} {'PASS' if result['passed_96'] else 'FAIL'}")
        for category, value in result["categories"].items():
            print(f"  {category}: {value}")
        failed_gates = [name for name, ok in result["hard_gates"].items() if not ok]
        if failed_gates:
            print("  failed gates: " + ", ".join(failed_gates))

    report = {
        "rubric": "independent_editable_print_layout_100",
        "threshold": 96.0,
        "ok": all(item["passed_96"] for item in results),
        "subjects": results,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {report_path}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
