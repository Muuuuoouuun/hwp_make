"""Verify September 2026 papers through the real native PDF export API.

Default scope is explicitly the three English papers; --all requires all 51
manifest entries. Source hashes, physical pages and printed question runs are
frozen before the application is imported. Each API case uses isolated storage.
0 = all selected checks passed, 1 = measured defect/tool error, 2 = incomplete.
An English-subset pass never means that the complete matrix passed.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
DATASETS = {1: "2026_september_high1", 2: "2026_september_high2", 3: "2027_kice_september_high3"}
REQUIRED_COUNTS = {1: 6, 2: 6, 3: 39}
REQUIRED_SUBJECTS = {
    1: ("국어", "수학", "영어", "한국사", "통합사회", "통합과학"),
    2: ("국어", "수학", "영어", "한국사", "통합사회", "통합과학"),
    3: ("화법과 작문", "언어와 매체", "미적분", "확률과 통계", "기하", "영어", "한국사",
        "생활과윤리", "윤리와사상", "한국지리", "세계지리", "동아시아사", "세계사", "정치와 법", "경제", "사회·문화",
        "물리학Ⅰ", "물리학Ⅱ", "화학Ⅰ", "화학Ⅱ", "생명과학Ⅰ", "생명과학Ⅱ", "지구과학Ⅰ", "지구과학Ⅱ",
        "농업 기초 기술", "공업 일반", "상업 경제", "수산·해운 산업 기초", "인간 발달", "성공적인 직업 생활",
        "독일어Ⅰ", "프랑스어Ⅰ", "스페인어Ⅰ", "중국어Ⅰ", "일본어Ⅰ", "러시아어Ⅰ", "아랍어Ⅰ", "베트남어Ⅰ", "한문Ⅰ"),
}
TARGETS = {"api_objective": 98.0, "development_progress": 93.0,
           "external_harsh_mean": 97.0, "external_harsh_minimum": 95.0,
           "external_strict_alignment_minimum": 0.96,
           "external_foreground_overlap_minimum": 0.97,
           "layout_view_sync": 0.94, "independent_native_text_coverage": 0.98}
NUMBER = re.compile(r"^([1-9]\d?)[.．](?!\d)")
LINE_NUMBER = re.compile(r"^\s*([1-9]\d?)\s*[.．](?!\d)")


def dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def code_fingerprint() -> dict:
    """Identify in-flight product changes without copying source code to logs."""
    paths = sorted((ROOT / "app").rglob("*.py"))
    paths += [Path(__file__).resolve()]
    hashes = {path.relative_to(ROOT).as_posix(): digest(path) for path in paths}
    combined = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode("utf-8")).hexdigest()
    return {"sha256": combined, "files": hashes}


def renderer_fingerprint() -> dict:
    """Fingerprint the installed Python/native renderer used by this worker."""
    import rhwp

    package = Path(rhwp.__file__).resolve().parent
    paths = sorted(p for p in package.rglob('*') if p.is_file()
                   and p.suffix.lower() in {'.py', '.pyd', '.so', '.dll', '.dylib'})
    hashes = {p.relative_to(package).as_posix(): digest(p) for p in paths}
    native = {name: value for name, value in hashes.items()
              if Path(name).suffix.lower() != '.py'}
    try:
        version = metadata.version('rhwp-python')
    except metadata.PackageNotFoundError:
        version = None
    signature = {'distribution_version': version, 'files': hashes}
    return {'available': bool(version and native), 'package_directory': str(package),
            **signature, 'native_libraries': native,
            'sha256': hashlib.sha256(json.dumps(signature, sort_keys=True).encode('utf8')).hexdigest()}


def source_path(row: dict, manifest_path: Path) -> Path:
    if row.get("source_path"):
        path = Path(row["source_path"])
        return path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    return (manifest_path.parent / str(row.get("file") or "")).resolve()


def is_english(row: dict) -> bool:
    return str(row.get("subject") or row.get("area") or "").strip().lower() in {"영어", "english"}


def subject_key(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def load_matrix(paths: list[Path]) -> tuple[list[dict], list[str], list[str]]:
    rows, errors, missing = [], [], []
    seen_grades = set()
    for path in paths:
        if not path.is_file():
            missing.append(f"manifest unavailable: {path}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            grade = int(payload["grade"])
            files = payload["files"]
            if grade not in REQUIRED_COUNTS or grade in seen_grades:
                raise ValueError("unsupported or duplicate grade")
            seen_grades.add(grade)
            if payload.get("schema_version") != 1 or not isinstance(files, list):
                raise ValueError("expected schema_version=1 and files list")
            if len(files) != REQUIRED_COUNTS[grade] or payload.get("inventory_count") != len(files):
                errors.append(f"grade {grade}: required inventory is {REQUIRED_COUNTS[grade]}, received {len(files)}")
            actual_subjects = Counter(subject_key(str(entry.get("subject") or "")) for entry in files)
            required_subjects = Counter(map(subject_key, REQUIRED_SUBJECTS[grade]))
            if actual_subjects != required_subjects:
                errors.append(f"grade {grade}: required subject/track inventory differs: missing={list((required_subjects-actual_subjects).elements())}, extra={list((actual_subjects-required_subjects).elements())}")
            if payload.get("exam_date") != "2026-09-02":
                errors.append(f"grade {grade}: exam_date must be pinned to 2026-09-02")
            for entry in files:
                row = dict(entry)
                row["grade"] = grade
                row["manifest"] = str(path.resolve())
                row["manifest_sha256"] = digest(path)
                row["source"] = str(source_path(row, path))
                row["academic_year"] = row.get("academic_year", payload.get("academic_year"))
                row["exam_date"] = row.get("exam_date", payload.get("exam_date"))
                row["organizer"] = payload.get("organizer")
                if not row.get("id") or not row.get("subject") or not (row.get("source_path") or row.get("file")):
                    errors.append(f"grade {grade}: row lacks id/subject/source path")
                if row.get("academic_year") != (2027 if grade == 3 else 2026):
                    errors.append(f"{row.get('id')}: academic year mismatch")
                rows.append(row)
        except (KeyError, TypeError, ValueError, OSError) as exc:
            errors.append(f"invalid manifest {path}: {type(exc).__name__}: {exc}")
    for grade in REQUIRED_COUNTS.keys() - seen_grades:
        missing.append(f"grade {grade}: required manifest missing")
    identities = Counter(str(row.get("id")) for row in rows)
    errors.extend(f"duplicate source id: {identity}" for identity, count in identities.items() if count > 1)
    for grade in seen_grades:
        if sum(is_english(row) for row in rows if row["grade"] == grade) != 1:
            errors.append(f"grade {grade}: exactly one required English paper must be present")
    return rows, errors, missing


def _expected_questions(row: dict) -> int | None:
    value = row.get("expected_question_count")
    if isinstance(value, int) and not isinstance(value, bool) and 0 < value < 100:
        return value
    label = str(row.get("subject") or "") + " " + str(row.get("area") or "")
    if any(term in label for term in ("영어", "english", "국어", "korean")):
        return 45
    if any(term in label for term in ("수학", "math")):
        return 30
    if row["grade"] in (1, 2) and any(term in label for term in ("통합사회", "통합과학")):
        return 25
    if "한국사" in label or (row["grade"] == 3 and "탐구" in label):
        return 20
    if row["grade"] == 3 and any(term in label for term in ("외국어", "한문")):
        return 30
    return None


def freeze_source(row: dict) -> dict:
    """Read the actual PDF only, without recognizer/writer imports or statistics."""
    import fitz

    path = Path(row["source"])
    result = {"id": row["id"], "grade": row["grade"], "subject": row["subject"],
              "area": row.get("area"), "track": row.get("track"), "variant": row.get("variant"),
              "source_question_groups": row.get("source_question_groups"),
              "source": str(path), "manifest_sha256": row["manifest_sha256"],
              "errors": [], "incomplete": [], "pages": []}
    if not path.is_file():
        result["incomplete"].append("source PDF unavailable")
        return result
    result["sha256"] = digest(path)
    result["bytes"] = path.stat().st_size
    if not row.get("sha256") or result["sha256"] != row["sha256"]:
        result["errors"].append("source SHA-256 differs from required manifest")
    if result["bytes"] != row.get("bytes"):
        result["errors"].append("source byte size differs from required manifest")
    if row.get("status") != "downloaded":
        result["incomplete"].append("manifest source is not marked downloaded")
    all_markers = []
    with fitz.open(path) as pdf:
        result["physical_pages"] = len(pdf)
        if len(pdf) != row.get("pages"):
            result["errors"].append("physical PDF pages differ from required manifest")
        for page_number, page in enumerate(pdf, 1):
            text = page.get_text("text")
            lines = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    value = unicodedata.normalize("NFKC", "".join(span.get("text", "") for span in line["spans"]))
                    match = LINE_NUMBER.match(value)
                    visible_spans = [span for span in line["spans"] if span.get("text", "").strip()]
                    # Corpus registration independently established the printed
                    # question-number font at >=12 source pt. Small numbered
                    # lists in passages are not additional questions.
                    if match and visible_spans and float(visible_spans[0].get("size") or 0) >= 12.0:
                        lines.append({"number": int(match[1]), "bbox_pt": list(visible_spans[0]["bbox"]),
                                      "first_span_font_size_pt": float(visible_spans[0]["size"])})
            candidates = []
            for word in page.get_text("words"):
                match = NUMBER.match(unicodedata.normalize("NFKC", str(word[4])).strip())
                if match:
                    candidates.append({"number": int(match[1]), "bbox_pt": list(word[:4])})
            printed_candidates = [candidate for candidate in candidates if any(
                line["number"] == candidate["number"]
                and abs(line["bbox_pt"][0] - candidate["bbox_pt"][0]) <= 5
                and abs(line["bbox_pt"][1] - candidate["bbox_pt"][1]) <= 5
                for line in lines)]
            markers = sorted(printed_candidates, key=lambda marker: (
                marker["bbox_pt"][0] >= page.rect.width / 2,
                marker["bbox_pt"][1], marker["bbox_pt"][0]))
            for marker in markers:
                marker["line_agreement"] = any(
                    line["number"] == marker["number"]
                    and abs(line["bbox_pt"][0] - marker["bbox_pt"][0]) <= 5
                    and abs(line["bbox_pt"][1] - marker["bbox_pt"][1]) <= 5
                    for line in lines)
                all_markers.append({"page": page_number, **marker})
            result["pages"].append({"physical_page": page_number,
                "width_pt": float(page.rect.width), "height_pt": float(page.rect.height),
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "text_chars": len(text), "word_marker_candidates": candidates,
                "line_marker_candidates": lines, "question_markers": markers,
                "printed_variants": [value for value in ("홀수형", "짝수형") if value in text],
                "printed_page_fractions": re.findall(r"(?m)^\s*(\d{1,2})\s*\n\s*(\d{1,2})\s*$", text)})
    runs = []
    for marker in all_markers:
        if not runs or marker["number"] <= runs[-1][-1]["number"]:
            runs.append([])
        runs[-1].append(marker)
    expected_count = _expected_questions(row)
    result["expected_questions_per_run"] = expected_count
    result["question_runs"] = [[marker["number"] for marker in run] for run in runs]
    result["question_ids"] = [f"v{variant}:q{marker['number']:02d}"
                              for variant, run in enumerate(runs, 1) for marker in run]
    result["question_count"] = len(all_markers)
    if not runs or expected_count is None:
        result["incomplete"].append("source question run cannot be independently established")
    elif any([marker["number"] for marker in run] != list(range(1, expected_count + 1)) for run in runs):
        result["incomplete"].append("source printed number runs require independent review")
    if any(not marker["line_agreement"] for marker in all_markers):
        result["incomplete"].append("source word/line marker extractors disagree")
    declared_runs = row.get("expected_number_runs")
    if declared_runs is not None:
        expected_runs = (len(declared_runs) if isinstance(declared_runs, list) else declared_runs)
        if expected_runs != len(runs):
            result["incomplete"].append("source number run count differs from required manifest")
        elif isinstance(declared_runs, list) and declared_runs != result["question_runs"]:
            result["incomplete"].append("source printed question runs differ from required manifest")
    declared_markers = row.get("source_question_markers")
    if isinstance(declared_markers, list):
        declared = [(marker["page"], marker["number"]) for marker in declared_markers]
        observed = [(marker["page"], marker["number"]) for marker in all_markers]
        if declared != observed:
            result["incomplete"].append("fresh source question markers differ from registered source proof")
    return result


def evaluate_evidence(inventory: dict, evidence: dict) -> dict:
    """Missing booleans/numbers fail; transport success is not quality success."""
    checks = {}
    def check(name, passed):
        checks[name] = passed is True
    def at_least(value, target):
        return finite(value) and value >= target
    check("http_200", evidence.get("http_status") == 200)
    check("output_exists", evidence.get("output_exists"))
    check("source_unchanged", evidence.get("source_sha256_after") == inventory.get("sha256"))
    check("renderer_runtime_available", (evidence.get("renderer_before") or {}).get("available"))
    check("renderer_runtime_unchanged", evidence.get("renderer_changed_during_case") is False)
    if evidence.get("http_status") != 200:
        return {"checks": checks, "failures": [key for key, value in checks.items() if not value],
                "development_93_met": False}
    quality = evidence.get("quality") or {}
    fidelity = evidence.get("fidelity") or {}
    audit = evidence.get("independent_editability") or {}
    rendering = evidence.get("independent_rendering") or {}
    check("api_objective_target_is_98", quality.get("objective_score_target") == 98.0)
    check("api_objective_at_least_98", at_least(quality.get("objective_score"), 98.0))
    check("api_meets_objective_target", quality.get("meets_objective_score_target"))
    check("api_review_ok", (quality.get("review") or {}).get("ok"))
    check("api_editability_ok", (quality.get("editability") or {}).get("ok"))
    check("independent_editability_ok", audit.get("ok"))
    check("independent_native_text_at_least_98pct", at_least(audit.get("native_source_text_coverage"), 0.98))
    check("independent_open_safety", (evidence.get("independent_open_safety") or {}).get("ok"))
    check("independent_rendering_ok", rendering.get("ok"))
    check("all_physical_pages_rendered", evidence.get("rendered_page_count") == inventory.get("physical_pages"))
    check("all_source_pages_compared", fidelity.get("pages_compared") == inventory.get("physical_pages"))
    check("fidelity_source_pages_exact", fidelity.get("pdf_page_count") == inventory.get("physical_pages"))
    check("fidelity_output_pages_exact", fidelity.get("hwpx_page_count") == inventory.get("physical_pages"))
    check("fidelity_available", fidelity.get("available") is True and not fidelity.get("skipped"))
    check("no_page_count_mismatch", fidelity.get("page_count_mismatch") is False)
    check("no_truncated_comparison", fidelity.get("truncated") is False)
    check("layout_view_at_least_94pct", at_least(fidelity.get("overall_layout_view_sync_ratio"), 0.94))
    check("external_harsh_mean_at_least_97", at_least(fidelity.get("overall_harsh_layout_score"), 97.0))
    check("external_harsh_minimum_at_least_95", at_least(fidelity.get("minimum_harsh_layout_score"), 95.0))
    check("external_raw_strict_alignment_at_least_96pct", at_least(fidelity.get("min_strict_alignment_ratio"), 0.96))
    check("external_raw_foreground_overlap_at_least_97pct", at_least(fidelity.get("min_foreground_overlap_ratio"), 0.97))
    check("source_printed_question_ids_exact", (audit.get("question_units") or {}).get("question_ids") == inventory.get("question_ids"))
    check("no_body_raster_crops", audit.get("rasterized_prose") == [])
    stats = evidence.get("stats") or {}
    check("no_full_page_images", stats.get("full_page_images") == 0)
    check("no_full_page_raster_fallback", stats.get("full_page_raster_fallback") is False)
    overlays = [stats.get(key) for key in ("text_visual_overlays", "math_visual_overlays")]
    check("no_text_or_math_visual_overlays", all(finite(value) and value == 0 for value in overlays))
    return {"checks": checks, "failures": [key for key, value in checks.items() if not value],
            "development_93_met": at_least(quality.get("objective_score"), 93.0)}


def worker(case_path: Path) -> int:
    case = json.loads(case_path.read_text(encoding="utf-8"))
    folder = case_path.parent
    os.environ["HWP_MAKE_DATA_DIR"] = str(folder / "engine")
    os.environ["HWP_MAKE_SETTINGS_DIR"] = str(folder / "settings")
    code_before = code_fingerprint()
    dump(folder / "code_before.json", code_before)
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient
    from app import main as api, storage
    from app.pdf_editability import inspect_pdf_editability
    from app.pdf_question_rendering import inspect_question_rendering
    from hwpx.tools.package_validator import validate_editor_open_safety
    import rhwp

    source = Path(case["inventory"]["source"])
    evidence = {"source": str(source), "requested_layout_mode": case["mode"], "output_exists": False,
                "worker_run_id": case["worker_run_id"], "code_sha256_before": code_before["sha256"],
                "runtime": {"platform": sys.platform, "python": sys.version,
                            "python_executable": sys.executable, "rhwp_module": getattr(rhwp, "__file__", None)}}
    evidence['renderer_before'] = renderer_fingerprint()
    for package in ("PyMuPDF", "rhwp-python", "fastapi", "lxml"):
        try:
            evidence["runtime"][package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            evidence["runtime"][package] = "distribution metadata unavailable"
    start = time.perf_counter()
    try:
        with TestClient(api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
            client.headers["Origin"] = "http://127.0.0.1"
            response = client.post("/api/pdf-layout-export", json={
                "filename": source.name, "data_base64": base64.b64encode(source.read_bytes()).decode("ascii"),
                "layout_mode": case["mode"], "native_math": True,
                "math_ai_recognition": False, "variant_policy": "all", "strict": True})
            evidence["api_seconds"] = round(time.perf_counter() - start, 3)
            evidence["http_status"] = response.status_code
            payload = response.json()
            dump(folder / "api_result.json", payload)
            if response.status_code == 200:
                export = payload.get("export") or {}
                output = (storage.EXPORT_DIR / str(export.get("name") or "")).resolve()
                output.relative_to(storage.EXPORT_DIR.resolve())
                evidence["output_exists"] = output.is_file()
                evidence["output"] = str(output)
                evidence["output_sha256"] = digest(output)
                evidence.update({key: payload.get(key) for key in ("quality", "fidelity", "stats")})
                evidence["independent_open_safety"] = validate_editor_open_safety(output).to_dict()
                evidence["independent_editability"] = inspect_pdf_editability(
                    source, output, (payload.get("stats") or {}).get("image_provenance") or [],
                    page_limit=case["inventory"]["physical_pages"], require_question_boxes=True)
                evidence["independent_rendering"] = inspect_question_rendering(output, rhwp)
                document = rhwp.parse(str(output))
                evidence["rendered_page_count"] = int(document.page_count)
            else:
                evidence["rejection"] = payload
    except Exception as exc:
        evidence["error"] = f"{type(exc).__name__}: {exc}"
    evidence["source_sha256_after"] = digest(source)
    evidence['renderer_after'] = renderer_fingerprint()
    evidence['renderer_changed_during_case'] = evidence['renderer_before'] != evidence['renderer_after']
    code_after = code_fingerprint()
    evidence["code_sha256_after"] = code_after["sha256"]
    evidence["code_changed_during_case"] = code_before["sha256"] != code_after["sha256"]
    if evidence["code_changed_during_case"]:
        dump(folder / "code_after.json", code_after)
    evidence["total_worker_seconds"] = round(time.perf_counter() - start, 3)
    evidence["verification"] = evaluate_evidence(case["inventory"], evidence)
    dump(folder / "evidence.json", evidence)
    return 0 if not evidence["verification"]["failures"] and not evidence.get("error") else 1


def summarize(records: list[dict], *, full_scope: bool, errors: list[str], incomplete: list[str]) -> dict:
    selected = [record for record in records if record["selected"]]
    modes = [mode for record in selected for mode in record.get("modes", [])]
    code_hashes = {mode.get("code_sha256_before") for mode in modes if mode.get("code_sha256_before")}
    renderer_hashes = {mode.get('renderer_sha256_before') for mode in modes if mode.get('renderer_sha256_before')}
    unstable = (len(code_hashes) > 1 or len(renderer_hashes) > 1
                or any(mode.get("code_changed_during_case") or mode.get('renderer_changed_during_case') for mode in modes))
    failed = any(record["status"] == "FAIL" for record in selected) or bool(errors)
    unavailable = (bool(incomplete) or unstable or (full_scope and len(selected) != sum(REQUIRED_COUNTS.values()))
                   or any(record["status"] in {"INCOMPLETE", "NOT_RUN"} for record in selected))
    selected_passed = bool(selected) and not failed and not unavailable and all(record["status"] == "PASS" for record in selected)
    full_passed = full_scope and selected_passed and len(selected) == sum(REQUIRED_COUNTS.values())
    status = "FAIL" if failed else "INCOMPLETE" if not selected_passed else "PASS" if full_passed else "PASS_SUBSET"
    return {"status": status, "exit_code": 1 if failed else 0 if selected_passed else 2,
            "selected_scope_passed": selected_passed, "full_matrix_passed": full_passed,
            "required_papers": sum(REQUIRED_COUNTS.values()), "selected_papers": len(selected),
            "baseline_stability": "UNSTABLE" if unstable else "STABLE" if code_hashes else "UNCHECKED",
            "distinct_product_code_snapshots": len(code_hashes),
            "status_counts": dict(Counter(record["status"] for record in records)),
            "manifest_errors": errors, "incomplete_reasons": incomplete}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", action="append", type=Path, help="Repeat for the three dataset manifests")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--all", action="store_true", help="Require every one of the 51 papers")
    selection.add_argument("--case", action="append", help="Explicit manifest id; repeatable")
    parser.add_argument("--mode", choices=("structured", "coordinate", "both"), default="structured")
    parser.add_argument("--inventory-only", action="store_true", help="Freeze source proof without executing the API; remains incomplete")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--timeout", type=int, default=900, help="Per case/mode subprocess timeout, seconds")
    parser.add_argument("--_worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._worker:
        return worker(args._worker)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    manifests = args.manifest or [ROOT / "data/external_exam_qa" / dataset / "manifest.json" for dataset in DATASETS.values()]
    manifests = [path.resolve() for path in manifests]
    rows, errors, missing = load_matrix(manifests)
    scope = "all_51" if args.all else "explicit_subset" if args.case else "english_3_subset"
    selected_ids = set(args.case or [row["id"] for row in rows if args.all or is_english(row)])
    unknown = selected_ids - {row["id"] for row in rows}
    errors.extend(f"unknown required case id: {identity}" for identity in sorted(unknown))
    if not args.all and not args.case and len(selected_ids) != 3:
        missing.append("English subset requires exactly one English paper for each of the three grades")
    output = (args.output_dir or ROOT / "tmp/september-exam-matrix" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")).resolve()
    output.mkdir(parents=True, exist_ok=True)
    inventories, records = [], []
    for row in rows:
        selected = row["id"] in selected_ids
        record = {"id": row["id"], "grade": row["grade"], "subject": row["subject"],
                  "area": row.get("area"), "track": row.get("track"), "variant": row.get("variant"),
                  "selected": selected, "status": "NOT_RUN", "modes": []}
        try:
            inventory = freeze_source(row)
        except Exception as exc:
            inventory = {"id": row["id"], "source": row["source"],
                         "errors": [f"source inventory error: {type(exc).__name__}: {exc}"], "incomplete": []}
        inventories.append(inventory)
        record["source_inventory_index"] = len(inventories) - 1
        if selected:
            if inventory["errors"]:
                record.update(status="FAIL", source_errors=inventory["errors"])
            elif not inventory.get("physical_pages"):
                record.update(status="INCOMPLETE", incomplete_reasons=inventory["incomplete"])
        records.append(record)
    dump(output / "source_inventory.json", {"frozen_at": datetime.now(timezone.utc).isoformat(),
        "source_policy": "actual PDF byte/page/line/word reads before app import; no generation counts",
        "cases": inventories})
    report = {"scope": scope, "targets": TARGETS, "mode": args.mode,
              "source_inventory": str(output / "source_inventory.json"), "records": records,
              "not_covered": ["premium import/template HWPX and DOCX workflows", "actual Hancom GUI/edit/print", "actual macOS runtime"],
              "started_at": datetime.now(timezone.utc).isoformat()}
    modes = ("structured", "coordinate") if args.mode == "both" else (args.mode,)
    def save():
        report["summary"] = summarize(records, full_scope=args.all, errors=errors, incomplete=missing)
        dump(output / "report.json", report)
    save()
    for record in records:
        if not record["selected"] or record["status"] != "NOT_RUN":
            continue
        inventory = inventories[record["source_inventory_index"]]
        if args.inventory_only:
            record.update(status="INCOMPLETE", incomplete_reasons=["API not run (--inventory-only)", *inventory["incomplete"]])
            save()
            continue
        for mode in modes:
            safe_id = re.sub(r"[^0-9A-Za-z_.-]", "_", str(record["id"]))
            # Digest prevents distinct Unicode ids from colliding after sanitizing.
            safe_id += "_" + hashlib.sha256(str(record["id"]).encode("utf-8")).hexdigest()[:8]
            folder = output / "cases" / safe_id / mode
            case_path = folder / "case.json"
            worker_run_id = f"{time.time_ns()}-{os.getpid()}"
            dump(case_path, {"inventory": inventory, "mode": mode, "worker_run_id": worker_run_id})
            started = time.perf_counter()
            try:
                proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--_worker", str(case_path)],
                    cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=args.timeout)
                (folder / "worker.log").write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr, encoding="utf-8")
                evidence_path = folder / "evidence.json"
                evidence = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.is_file() else {}
                measured = evidence.get("verification") or {}
                status = "PASS" if (proc.returncode == 0 and evidence.get("worker_run_id") == worker_run_id
                    and measured.get("checks") and measured.get("failures") == []) else "FAIL"
                if status == "PASS" and evidence.get("code_changed_during_case"):
                    status = "INCOMPLETE"
                mode_record = {"mode": mode, "status": status, "exit_code": proc.returncode,
                    "evidence": str(evidence_path), "failures": measured.get("failures", ["worker produced no verification result"]),
                    "objective_score": (evidence.get("quality") or {}).get("objective_score"),
                    "harsh_mean": (evidence.get("fidelity") or {}).get("overall_harsh_layout_score"),
                    "harsh_minimum": (evidence.get("fidelity") or {}).get("minimum_harsh_layout_score"),
                    "development_93_met": measured.get("development_93_met") is True}
                if evidence.get("worker_run_id") != worker_run_id:
                    mode_record["failures"] = [*mode_record["failures"], "no evidence from the current worker run"]
                if evidence.get("error"):
                    mode_record["failures"] = [*mode_record["failures"], evidence["error"]]
                mode_record.update(code_sha256_before=evidence.get("code_sha256_before"),
                    code_sha256_after=evidence.get("code_sha256_after"),
                    code_changed_during_case=evidence.get("code_changed_during_case"),
                    renderer_sha256_before=(evidence.get('renderer_before') or {}).get('sha256'),
                    renderer_sha256_after=(evidence.get('renderer_after') or {}).get('sha256'),
                    renderer_changed_during_case=evidence.get('renderer_changed_during_case'))
                mode_record["baseline_stability"] = "UNSTABLE" if (
                    evidence.get("code_changed_during_case") or evidence.get('renderer_changed_during_case')) else "STABLE"
            except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
                (folder / "worker.log").write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")
                mode_record = {"mode": mode, "status": "FAIL", "failures": [f"worker error: {type(exc).__name__}: {exc}"]}
            mode_record["seconds"] = round(time.perf_counter() - started, 3)
            record["modes"].append(mode_record)
            print(f"{record['id']} {mode}: {mode_record['status']} score={mode_record.get('objective_score')} failures={len(mode_record['failures'])}", flush=True)
        if any(mode["status"] == "FAIL" for mode in record["modes"]):
            record["status"] = "FAIL"
        elif inventory["incomplete"] or any(mode["status"] == "INCOMPLETE" for mode in record["modes"]):
            record.update(status="INCOMPLETE", incomplete_reasons=[*inventory["incomplete"],
                *(["product code changed during API case"] if any(mode["status"] == "INCOMPLETE" for mode in record["modes"]) else [])])
        else:
            record["status"] = "PASS"
        save()
    save()
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(f"Report: {output / 'report.json'}")
    return report["summary"]["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
