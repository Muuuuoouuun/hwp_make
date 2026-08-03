from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable


SUBJECTS = ("korean", "english", "math_a", "math_b")
MATH_SUBJECTS = ("math_a", "math_b")
DEFAULT_MINIMUM_SCORE = 97.0
DEFAULT_PARALLEL_WALL_SLA_SECONDS = 15.0
DEFAULT_WORST_SUBJECT_SECONDS_PER_PAGE_SLA = 0.85
DEFAULT_AGGREGATE_CPU_SECONDS_PER_PAGE_SLA = 0.50

NATIVE_ISSUE_FIELDS = (
    "missing_script_count",
    "paragraph_shortage_count",
    "cell_shortage_count",
    "figure_layout_issue_count",
    "problem_balance_shortage_count",
    "problem_content_overflow_count",
    "logical_page_table_overflow_count",
    "equation_width_placeholder_count",
    "required_shortage_count",
)


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if _is_number(value) else default


def _integer(value: Any, default: int = 0) -> int:
    return int(value) if _is_number(value) else default


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _symmetric_ratio(first: float, second: float) -> float:
    if first <= 0.0 or second <= 0.0:
        return 0.0
    return min(first, second) / max(first, second)


def _bounded_sla_score(actual: float, sla: float) -> float:
    if actual <= 0.0 or sla <= 0.0:
        return 0.0
    return _clip(sla / actual * 100.0)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _json_path(path: Path, package_dir: Path) -> str:
    try:
        return path.resolve().relative_to(package_dir.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _looks_like_generation(data: dict[str, Any]) -> bool:
    container = data.get("subjects") if isinstance(data.get("subjects"), dict) else data
    if not isinstance(container, dict):
        return False
    for subject in SUBJECTS:
        entry = container.get(subject)
        if not isinstance(entry, dict):
            return False
        stats = entry.get("stats", entry)
        if not isinstance(stats, dict) or not any(
            key in stats
            for key in ("source_pages", "pages", "source_problem_count")
        ):
            return False
    return True


def _looks_like_independent_quality(data: dict[str, Any]) -> bool:
    subjects = data.get("subjects")
    return (
        isinstance(subjects, list)
        and any(
            isinstance(item, dict)
            and item.get("subject") in SUBJECTS
            and "categories" in item
            and "hard_gates" in item
            for item in subjects
        )
    )


def _looks_like_detection_quality(data: dict[str, Any]) -> bool:
    result = _as_dict(data.get("result"))
    policy = _as_dict(data.get("independence_policy"))
    return (
        str(data.get("verifier") or "").endswith("verify_detection_quality_97.py")
        and _is_number(result.get("score"))
        and policy.get("generation_report_read") is False
    )


def _looks_like_native_math(data: dict[str, Any]) -> bool:
    return any(
        isinstance(item, dict) and "direct_equation_count" in item
        for item in _as_list(data.get("results"))
    )


def _looks_like_visual(data: dict[str, Any]) -> bool:
    semantic = _as_dict(data.get("semantic_implementation"))
    components = _as_dict(semantic.get("components"))
    return "page_count" in components and "problem_number_preservation" in components


def _looks_like_speed(data: dict[str, Any]) -> bool:
    measurements = _as_dict(data.get("measurements"))
    return data.get("theme") == "speed" and any(
        key in measurements
        for key in ("parallel_wall_seconds", "parallel_wall_time", "total_cpu_seconds")
    )


def _subject_from_visual_path(path: Path, data: dict[str, Any]) -> str | None:
    lowered_parts = [part.casefold() for part in path.parts]
    for subject in SUBJECTS:
        if subject in lowered_parts:
            return subject
    joined = " ".join(
        str(data.get(key) or "").replace("\\", "/").casefold()
        for key in ("source_pdf", "output_pdf", "artifact_dir", "report_path")
    )
    return next((subject for subject in SUBJECTS if subject in joined), None)


def _candidate_rank(path: Path, package_dir: Path, preferred_name: str) -> tuple[int, int, str]:
    relative = _json_path(path, package_dir)
    return (
        0 if path.name.casefold() == preferred_name.casefold() else 1,
        0 if relative.startswith("validation/reports/") else 1,
        relative,
    )


def _discover_evidence(package_dir: Path) -> dict[str, Any]:
    generation: list[tuple[Path, dict[str, Any]]] = []
    detection: list[tuple[Path, dict[str, Any]]] = []
    independent: list[tuple[Path, dict[str, Any]]] = []
    native_math: list[tuple[Path, dict[str, Any]]] = []
    speed: list[tuple[Path, dict[str, Any]]] = []
    summaries: list[tuple[Path, dict[str, Any]]] = []
    visual: dict[str, list[tuple[Path, dict[str, Any]]]] = {
        subject: [] for subject in SUBJECTS
    }

    for path in sorted(package_dir.rglob("*.json")):
        if path.name.casefold() == "package_manifest.json":
            continue
        data = _load_json(path)
        if data is None:
            continue
        if _looks_like_generation(data):
            generation.append((path, data))
        if _looks_like_detection_quality(data):
            detection.append((path, data))
        if _looks_like_independent_quality(data):
            independent.append((path, data))
        if _looks_like_native_math(data):
            native_math.append((path, data))
        if _looks_like_speed(data):
            speed.append((path, data))
        if isinstance(data.get("generation_elapsed_seconds"), dict):
            summaries.append((path, data))
        if _looks_like_visual(data):
            subject = _subject_from_visual_path(path, data)
            if subject is not None:
                visual[subject].append((path, data))

    def choose(
        candidates: list[tuple[Path, dict[str, Any]]], preferred_name: str
    ) -> tuple[Path | None, dict[str, Any] | None, list[str]]:
        ordered = sorted(
            candidates,
            key=lambda item: _candidate_rank(item[0], package_dir, preferred_name),
        )
        if not ordered:
            return None, None, []
        return (
            ordered[0][0],
            ordered[0][1],
            [_json_path(item[0], package_dir) for item in ordered[1:]],
        )

    generation_path, generation_data, generation_alternates = choose(
        generation, "generation_report.json"
    )
    detection_path, detection_data, detection_alternates = choose(
        detection, "detection_quality_97.json"
    )
    independent_path, independent_data, independent_alternates = choose(
        independent, "independent_quality_98.json"
    )
    native_path, native_data, native_alternates = choose(
        native_math, "native_math_structure.json"
    )
    speed_path, speed_data, speed_alternates = choose(speed, "speed_benchmark.json")
    summary_path, summary_data, summary_alternates = choose(
        summaries, "final_validation_summary.json"
    )

    visual_selected: dict[str, dict[str, Any]] = {}
    visual_alternates: dict[str, list[str]] = {}
    for subject in SUBJECTS:
        path, data, alternates = choose(visual[subject], "report.json")
        if path is not None and data is not None:
            visual_selected[subject] = {"path": path, "data": data}
        if alternates:
            visual_alternates[subject] = alternates

    return {
        "generation": {"path": generation_path, "data": generation_data},
        "detection": {"path": detection_path, "data": detection_data},
        "independent": {"path": independent_path, "data": independent_data},
        "native_math": {"path": native_path, "data": native_data},
        "speed": {"path": speed_path, "data": speed_data},
        "summary": {"path": summary_path, "data": summary_data},
        "visual": visual_selected,
        "alternates": {
            "generation": generation_alternates,
            "detection_quality": detection_alternates,
            "independent_quality": independent_alternates,
            "native_math_structure": native_alternates,
            "speed": speed_alternates,
            "summary": summary_alternates,
            "visual": visual_alternates,
        },
    }


def _generation_subjects(data: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(data, dict):
        return {}
    container: Any = data.get("subjects", data)
    if isinstance(container, list):
        container = {
            item.get("subject"): item
            for item in container
            if isinstance(item, dict) and item.get("subject") in SUBJECTS
        }
    if not isinstance(container, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for subject in SUBJECTS:
        entry = _as_dict(container.get(subject))
        stats = _as_dict(entry.get("stats", entry))
        if stats:
            result[subject] = stats
    return result


def _independent_subjects(data: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(data, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in _as_list(data.get("subjects")):
        if isinstance(item, dict) and item.get("subject") in SUBJECTS:
            result[str(item["subject"])] = item
    return result


def _weighted_average(rows: Iterable[tuple[float, float]]) -> float:
    numerator = 0.0
    denominator = 0.0
    for value, weight in rows:
        effective_weight = weight if weight > 0.0 else 1.0
        numerator += _clip(value) * effective_weight
        denominator += effective_weight
    return numerator / denominator if denominator else 0.0


def _component(
    component_id: str,
    weight: float,
    normalized_score: float,
    raw: Any,
    method: str,
    evidence: list[str],
) -> dict[str, Any]:
    normalized = _clip(normalized_score)
    return {
        "id": component_id,
        "weight": weight,
        "normalized_score": round(normalized, 4),
        "points": round(weight * normalized / 100.0, 4),
        "raw": raw,
        "method": method,
        "evidence": evidence,
    }


def _gate(gate_id: str, passed: bool, requirement: str, raw: Any) -> dict[str, Any]:
    return {
        "id": gate_id,
        "passed": bool(passed),
        "requirement": requirement,
        "raw": raw,
    }


def _theme(
    theme_id: str,
    label: str,
    components: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    minimum_score: float,
) -> dict[str, Any]:
    weight_sum = round(sum(_number(item.get("weight")) for item in components), 6)
    if weight_sum != 100.0:
        raise ValueError(f"{theme_id} component weights sum to {weight_sum}, not 100")
    score = round(sum(_number(item.get("points")) for item in components), 2)
    gate_passed = all(bool(item.get("passed")) for item in gates)
    return {
        "id": theme_id,
        "label": label,
        "score": score,
        "maximum_score": 100.0,
        "minimum_score": minimum_score,
        "score_passed": score >= minimum_score,
        "gate_passed": gate_passed,
        "passed": score >= minimum_score and gate_passed,
        "components": components,
        "gates": gates,
    }


def _iter_manifest_file_records(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if all(key in value for key in ("path", "bytes", "sha256")):
            yield value
        for child in value.values():
            yield from _iter_manifest_file_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_manifest_file_records(child)


def _normalize_manifest_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or any(":" in part for part in path.parts):
        return None
    normalized = path.as_posix()
    return normalized if normalized not in ("", ".") else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_manifest(
    package_dir: Path,
    manifest: dict[str, Any] | None,
    required_evidence_paths: list[str],
) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        return {
            "score": 0.0,
            "record_count": 0,
            "valid_record_count": 0,
            "valid_paths": set(),
            "core_asset_count": 12,
            "valid_core_asset_count": 0,
            "all_records_valid": False,
            "all_core_assets_valid": False,
            "all_evidence_declared": False,
            "undeclared_evidence": required_evidence_paths,
            "issues": [{"kind": "missing_or_invalid_manifest"}],
        }

    records: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    for record in _iter_manifest_file_records(manifest):
        relative = _normalize_manifest_path(record.get("path"))
        if relative is None:
            issues.append({"kind": "unsafe_or_invalid_path", "path": record.get("path")})
            continue
        previous = records.get(relative)
        if previous is not None and (
            previous.get("bytes") != record.get("bytes")
            or str(previous.get("sha256") or "").casefold()
            != str(record.get("sha256") or "").casefold()
        ):
            issues.append({"kind": "conflicting_duplicate_record", "path": relative})
            continue
        records[relative] = record

    package_root = package_dir.resolve()
    valid_paths: set[str] = set()
    for relative, record in records.items():
        path = package_dir.joinpath(*PurePosixPath(relative).parts)
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(package_root)
        except (FileNotFoundError, OSError, ValueError):
            issues.append({"kind": "missing_or_outside_package", "path": relative})
            continue
        if not resolved.is_file():
            issues.append({"kind": "not_a_regular_file", "path": relative})
            continue
        expected_bytes = record.get("bytes")
        expected_hash = record.get("sha256")
        if not _is_number(expected_bytes) or int(expected_bytes) != resolved.stat().st_size:
            issues.append(
                {
                    "kind": "size_mismatch",
                    "path": relative,
                    "expected": expected_bytes,
                    "actual": resolved.stat().st_size,
                }
            )
            continue
        actual_hash = _sha256(resolved)
        if not isinstance(expected_hash, str) or actual_hash != expected_hash.casefold():
            issues.append(
                {
                    "kind": "sha256_mismatch",
                    "path": relative,
                    "expected": expected_hash,
                    "actual": actual_hash,
                }
            )
            continue
        valid_paths.add(relative)

    subjects = _as_dict(manifest.get("subjects"))
    core_paths: list[str | None] = []
    for subject in SUBJECTS:
        subject_record = _as_dict(subjects.get(subject))
        for role in ("source_pdf", "hwpx", "hancom_pdf"):
            core_paths.append(_normalize_manifest_path(_as_dict(subject_record.get(role)).get("path")))
    valid_core = sum(path in valid_paths for path in core_paths if path is not None)
    undeclared_evidence = sorted(
        path for path in required_evidence_paths if path not in records
    )
    record_count = len(records)
    score = 100.0 * len(valid_paths) / record_count if record_count else 0.0
    return {
        "score": round(score, 4),
        "record_count": record_count,
        "valid_record_count": len(valid_paths),
        "valid_paths": valid_paths,
        "core_asset_count": len(core_paths),
        "valid_core_asset_count": valid_core,
        "all_records_valid": bool(record_count) and len(valid_paths) == record_count and not issues,
        "all_core_assets_valid": len(core_paths) == 12 and valid_core == 12,
        "all_evidence_declared": not undeclared_evidence,
        "undeclared_evidence": undeclared_evidence,
        "issues": issues[:50],
        "issue_count": len(issues),
    }


def _native_result_subject(
    item: dict[str, Any], manifest: dict[str, Any] | None
) -> str | None:
    stem = PureWindowsPath(str(item.get("path") or "")).stem.casefold()
    for subject in MATH_SUBJECTS:
        if subject in stem:
            return subject
    subjects = _as_dict(_as_dict(manifest).get("subjects"))
    for subject in MATH_SUBJECTS:
        hwpx = _as_dict(_as_dict(subjects.get(subject)).get("hwpx"))
        package_stem = PureWindowsPath(str(hwpx.get("path") or "")).stem.casefold()
        if package_stem and package_stem == stem:
            return subject
    return None


def _assess_native_math(
    native_data: dict[str, Any] | None,
    generation_subjects: dict[str, dict[str, Any]],
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    native = _as_dict(native_data)
    mapped: dict[str, dict[str, Any]] = {}
    unmapped: list[dict[str, Any]] = []
    for value in _as_list(native.get("results")):
        if not isinstance(value, dict):
            continue
        subject = _native_result_subject(value, manifest)
        if subject is None:
            unmapped.append(value)
        elif subject not in mapped:
            mapped[subject] = value

    for subject in MATH_SUBJECTS:
        if subject in mapped:
            continue
        expected = _integer(generation_subjects.get(subject, {}).get("native_equations"))
        exact = [
            item
            for item in unmapped
            if _integer(item.get("direct_equation_count")) == expected and expected > 0
        ]
        if len(exact) == 1:
            mapped[subject] = exact[0]
            unmapped.remove(exact[0])

    subject_raw: dict[str, Any] = {}
    subject_scores: list[tuple[float, float]] = []
    all_subjects_valid = True
    for subject in MATH_SUBJECTS:
        stats = generation_subjects.get(subject, {})
        expected_source = _integer(stats.get("source_math_segments"))
        expected_native = _integer(stats.get("native_equations"))
        expected = expected_native or expected_source
        item = mapped.get(subject, {})
        direct = _integer(item.get("direct_equation_count"))
        scripts = _integer(item.get("direct_script_count"))
        missing_scripts = _integer(item.get("missing_script_count"))
        issue_counts = {field: _integer(item.get(field)) for field in NATIVE_ISSUE_FIELDS}
        issue_total = sum(issue_counts.values())
        equation_ratio = _symmetric_ratio(float(expected), float(direct))
        script_ratio = min(1.0, scripts / direct) if direct > 0 else 0.0
        issue_free_ratio = max(0.0, 1.0 - issue_total / max(1, direct))
        score = 100.0 * (
            0.50 * equation_ratio + 0.25 * script_ratio + 0.25 * issue_free_ratio
        )
        valid = (
            bool(item)
            and expected > 0
            and direct == expected
            and (expected_source <= 0 or direct == expected_source)
            and scripts == direct
            and missing_scripts == 0
            and issue_total == 0
            and bool(item.get("ok", True))
        )
        all_subjects_valid = all_subjects_valid and valid
        subject_scores.append((score, float(max(1, expected))))
        subject_raw[subject] = {
            "expected_source_math_segments": expected_source,
            "expected_native_equations": expected_native,
            "direct_equation_count": direct,
            "direct_script_count": scripts,
            "missing_script_count": missing_scripts,
            "issue_counts": issue_counts,
            "issue_total": issue_total,
            "equation_count_ratio": round(equation_ratio, 6),
            "script_coverage_ratio": round(script_ratio, 6),
            "valid": valid,
        }

    report_ok = (
        bool(native)
        and bool(native.get("ok"))
        and _integer(native.get("required_shortage_count")) == 0
        and _integer(native.get("shortage_count")) == 0
    )
    return {
        "score": round(_weighted_average(subject_scores), 4),
        "report_ok": report_ok,
        "all_subjects_valid": report_ok and all_subjects_valid,
        "files_checked": _integer(native.get("files_checked")),
        "subjects": subject_raw,
        "unmapped_result_count": len(unmapped),
    }


def _score_independent_detection(
    detection: dict[str, Any],
    detection_path: str | None,
    minimum_score: float,
) -> dict[str, Any]:
    rubric = _as_dict(detection.get("rubric"))
    source_components = _as_dict(rubric.get("components"))
    evidence = [detection_path] if detection_path else []
    components: list[dict[str, Any]] = []
    for component_id in (
        "page_and_variant",
        "problem_inventory",
        "native_math",
        "source_feature_contract",
    ):
        source = _as_dict(source_components.get(component_id))
        weight = _number(source.get("weight"))
        points = _number(source.get("score"))
        normalized = _clip(points / weight * 100.0) if weight > 0.0 else 0.0
        components.append(
            _component(
                component_id,
                weight,
                normalized,
                source,
                "Independent source-PDF inventory cross-checked against HWPX XML and actual Hancom PDF.",
                evidence,
            )
        )

    result = _as_dict(detection.get("result"))
    policy = _as_dict(detection.get("independence_policy"))
    source_gates = _as_dict(detection.get("hard_gates"))
    reported_score = _number(result.get("score"))
    component_score = sum(_number(item.get("points")) for item in components)
    failed_source_gates = sorted(
        str(name) for name, passed in source_gates.items() if not bool(passed)
    )
    gates = [
        _gate(
            "independent_detection_report_present",
            bool(detection_path),
            "A verify_detection_quality_97 report must be packaged.",
            {"path": detection_path},
        ),
        _gate(
            "generation_statistics_not_used_as_ground_truth",
            policy.get("generation_report_read") is False
            and policy.get("generation_statistics_as_ground_truth") is False,
            "Detection evidence must be rebuilt from packaged source PDFs, not generation statistics.",
            policy,
        ),
        _gate(
            "independent_detection_hard_gates",
            bool(source_gates) and not failed_source_gates,
            "Every independent detection hard gate must pass.",
            {"failed": failed_source_gates, "all": source_gates},
        ),
        _gate(
            "independent_detection_score_consistent",
            abs(component_score - reported_score) <= 0.01,
            "Reported detection score must equal the sum of its four weighted components.",
            {
                "reported_score": reported_score,
                "component_score": round(component_score, 6),
            },
        ),
        _gate(
            "independent_detection_result_passed",
            bool(result.get("passed")) and reported_score >= minimum_score,
            "The independent verifier must pass at the requested minimum score.",
            result,
        ),
    ]
    return _theme("detection", "감지", components, gates, minimum_score)


def _score_detection(
    generation: dict[str, Any] | None,
    generation_path: str | None,
    minimum_score: float,
) -> dict[str, Any]:
    subjects = _generation_subjects(generation)
    evidence = [generation_path] if generation_path else []
    raw: dict[str, dict[str, Any]] = {}
    page_rows: list[tuple[float, float]] = []
    problem_rows: list[tuple[float, float]] = []
    layout_rows: list[tuple[float, float]] = []
    text_rows: list[tuple[float, float]] = []
    reliability_rows: list[tuple[float, float]] = []

    for subject in SUBJECTS:
        stats = subjects.get(subject, {})
        source_pages = _integer(stats.get("source_pages"))
        detected_pages = _integer(stats.get("pages"))
        source_problems = _integer(stats.get("source_problem_count"))
        recognized_problems = _integer(stats.get("recognized_problem_count"))
        layout_coverage = _clip(
            _number(stats.get("source_layout_coverage_ratio")) * 100.0
        )
        source_chars = _integer(stats.get("source_text_char_count"))
        matched_chars = _integer(stats.get("matched_text_char_count"))
        text_ratio = (
            min(1.0, matched_chars / source_chars)
            if source_chars > 0
            else _clip(_number(stats.get("source_text_preservation_ratio")), 0.0, 1.0)
        )
        reliability_issues = (
            _integer(stats.get("unreliable_text_problems"))
            + _integer(stats.get("duplicate_problem_count"))
            + _integer(stats.get("variant_duplicate_problem_count"))
        )
        reliability_ratio = max(
            0.0, 1.0 - reliability_issues / max(1, source_problems)
        )
        page_ratio = _symmetric_ratio(float(source_pages), float(detected_pages))
        problem_ratio = _symmetric_ratio(
            float(source_problems), float(recognized_problems)
        )
        raw[subject] = {
            "source_pages": source_pages,
            "detected_pages": detected_pages,
            "page_ratio": round(page_ratio, 6),
            "source_problem_count": source_problems,
            "recognized_problem_count": recognized_problems,
            "problem_ratio": round(problem_ratio, 6),
            "source_layout_items": _integer(stats.get("source_layout_items")),
            "source_layout_coverage_ratio": round(layout_coverage / 100.0, 6),
            "source_text_char_count": source_chars,
            "matched_text_char_count": matched_chars,
            "source_text_preservation_ratio": round(text_ratio, 6),
            "reliability_issue_count": reliability_issues,
            "unreliable_text_problems": _integer(stats.get("unreliable_text_problems")),
            "duplicate_problem_count": _integer(stats.get("duplicate_problem_count")),
            "variant_duplicate_problem_count": _integer(
                stats.get("variant_duplicate_problem_count")
            ),
        }
        page_rows.append((page_ratio * 100.0, float(max(1, source_pages))))
        problem_rows.append((problem_ratio * 100.0, float(max(1, source_problems))))
        layout_rows.append((layout_coverage, float(max(1, source_pages))))
        text_rows.append((text_ratio * 100.0, float(max(1, source_chars))))
        reliability_rows.append(
            (reliability_ratio * 100.0, float(max(1, source_problems)))
        )

    components = [
        _component(
            "source_page_detection",
            25.0,
            _weighted_average(page_rows),
            {subject: raw[subject] for subject in SUBJECTS},
            "Symmetric detected/source page ratio, weighted by source pages.",
            evidence,
        ),
        _component(
            "problem_detection",
            30.0,
            _weighted_average(problem_rows),
            {subject: raw[subject] for subject in SUBJECTS},
            "Symmetric recognized/source problem ratio, weighted by source problems.",
            evidence,
        ),
        _component(
            "layout_detection_coverage",
            20.0,
            _weighted_average(layout_rows),
            {subject: raw[subject] for subject in SUBJECTS},
            "Generation-reported source layout coverage, weighted by source pages.",
            evidence,
        ),
        _component(
            "recognized_text_preservation",
            15.0,
            _weighted_average(text_rows),
            {subject: raw[subject] for subject in SUBJECTS},
            "Matched/source text characters; missing text evidence receives zero.",
            evidence,
        ),
        _component(
            "recognition_reliability",
            10.0,
            _weighted_average(reliability_rows),
            {subject: raw[subject] for subject in SUBJECTS},
            "Problem-weighted penalty for unreliable or duplicate detections.",
            evidence,
        ),
    ]
    missing_subjects = [subject for subject in SUBJECTS if subject not in subjects]
    exact_pages = all(
        raw[subject]["source_pages"] > 0
        and raw[subject]["source_pages"] == raw[subject]["detected_pages"]
        for subject in SUBJECTS
    )
    problem_coverage_ok = all(
        raw[subject]["source_problem_count"] > 0
        and raw[subject]["problem_ratio"] >= 0.97
        for subject in SUBJECTS
    )
    layout_coverage_ok = all(
        raw[subject]["source_layout_coverage_ratio"] >= 0.97 for subject in SUBJECTS
    )
    no_reliability_issues = all(
        raw[subject]["reliability_issue_count"] == 0 for subject in SUBJECTS
    )
    text_evidence_present = all(
        raw[subject]["source_text_char_count"] > 0
        and raw[subject]["matched_text_char_count"] > 0
        for subject in SUBJECTS
    )
    gates = [
        _gate(
            "generation_report_present",
            bool(generation_path),
            "A generation_report JSON must be discoverable in the final package.",
            {"path": generation_path},
        ),
        _gate(
            "all_subjects_present",
            not missing_subjects,
            "Generation evidence must cover korean, english, math_a, and math_b.",
            {"missing_subjects": missing_subjects},
        ),
        _gate(
            "exact_source_page_detection",
            exact_pages,
            "Every subject must detect exactly the source page count.",
            {subject: raw[subject]["page_ratio"] for subject in SUBJECTS},
        ),
        _gate(
            "problem_detection_at_least_97_percent",
            problem_coverage_ok,
            "Every subject must recognize at least 97% of source problems.",
            {subject: raw[subject]["problem_ratio"] for subject in SUBJECTS},
        ),
        _gate(
            "layout_detection_at_least_97_percent",
            layout_coverage_ok,
            "Every subject must report at least 97% source layout coverage.",
            {
                subject: raw[subject]["source_layout_coverage_ratio"]
                for subject in SUBJECTS
            },
        ),
        _gate(
            "no_unreliable_or_duplicate_detections",
            no_reliability_issues,
            "Unreliable and duplicate detection counts must be zero.",
            {
                subject: raw[subject]["reliability_issue_count"]
                for subject in SUBJECTS
            },
        ),
        _gate(
            "text_detection_evidence_present",
            text_evidence_present,
            "Source and matched text character counts must be measured for every subject.",
            {
                subject: {
                    "source": raw[subject]["source_text_char_count"],
                    "matched": raw[subject]["matched_text_char_count"],
                }
                for subject in SUBJECTS
            },
        ),
    ]
    return _theme("detection", "감지", components, gates, minimum_score)


def _category_score(item: dict[str, Any], names: tuple[str, ...]) -> tuple[float, float]:
    maxima = {
        "page_mapping": 12.0,
        "duplicate_control": 8.0,
        "editable_composition": 15.0,
        "font": 10.0,
        "native_math": 15.0,
        "page_geometry": 10.0,
        "headers_columns": 10.0,
        "line_spacing": 10.0,
        "problem_integrity": 6.0,
        "figures": 4.0,
    }
    categories = _as_dict(item.get("categories"))
    earned = sum(_number(categories.get(name)) for name in names)
    possible = sum(maxima[name] for name in names)
    return earned, possible


def _score_conversion(
    independent: dict[str, Any] | None,
    independent_path: str | None,
    generation_subjects: dict[str, dict[str, Any]],
    native_assessment: dict[str, Any],
    native_path: str | None,
    manifest_assessment: dict[str, Any],
    manifest_path: str | None,
    minimum_score: float,
) -> dict[str, Any]:
    subjects = _independent_subjects(independent)
    quality_rows: list[tuple[float, float]] = []
    editability_rows: list[tuple[float, float]] = []
    structure_rows: list[tuple[float, float]] = []
    integrity_rows: list[tuple[float, float]] = []
    raw: dict[str, Any] = {}
    failed_hard_gates: dict[str, list[str]] = {}

    for subject in SUBJECTS:
        item = subjects.get(subject, {})
        page_weight = float(
            max(1, _integer(generation_subjects.get(subject, {}).get("source_pages")))
        )
        quality = _clip(_number(item.get("score")))
        editable_earned, editable_possible = _category_score(
            item, ("editable_composition", "font")
        )
        structure_earned, structure_possible = _category_score(
            item,
            ("page_mapping", "page_geometry", "headers_columns", "line_spacing"),
        )
        integrity_earned, integrity_possible = _category_score(
            item, ("problem_integrity", "figures", "duplicate_control")
        )
        hard_gates = _as_dict(item.get("hard_gates"))
        failed = sorted(name for name, passed in hard_gates.items() if not passed)
        if not hard_gates:
            failed.append("hard_gates_missing")
        failed_hard_gates[subject] = failed
        raw[subject] = {
            "independent_score": quality,
            "categories": _as_dict(item.get("categories")),
            "failed_hard_gates": failed,
        }
        quality_rows.append((quality, page_weight))
        editability_rows.append(
            (
                100.0 * editable_earned / editable_possible
                if editable_possible
                else 0.0,
                page_weight,
            )
        )
        structure_rows.append(
            (
                100.0 * structure_earned / structure_possible
                if structure_possible
                else 0.0,
                page_weight,
            )
        )
        integrity_rows.append(
            (
                100.0 * integrity_earned / integrity_possible
                if integrity_possible
                else 0.0,
                page_weight,
            )
        )

    independent_evidence = [independent_path] if independent_path else []
    native_evidence = [native_path] if native_path else []
    manifest_evidence = [manifest_path] if manifest_path else []
    manifest_raw = {
        key: value
        for key, value in manifest_assessment.items()
        if key != "valid_paths"
    }
    components = [
        _component(
            "independent_editable_quality",
            25.0,
            _weighted_average(quality_rows),
            raw,
            "Page-weighted independent_quality subject scores.",
            independent_evidence,
        ),
        _component(
            "editability_and_font",
            15.0,
            _weighted_average(editability_rows),
            raw,
            "Independent editable_composition (15) and font (10), normalized to 100.",
            independent_evidence,
        ),
        _component(
            "document_structure",
            20.0,
            _weighted_average(structure_rows),
            raw,
            "Independent page mapping, geometry, columns/headers, and spacing categories.",
            independent_evidence,
        ),
        _component(
            "problem_figure_and_duplicate_integrity",
            15.0,
            _weighted_average(integrity_rows),
            raw,
            "Independent problem integrity, figures, and duplicate-control categories.",
            independent_evidence,
        ),
        _component(
            "native_math_structure",
            15.0,
            _number(native_assessment.get("score")),
            native_assessment,
            "50% equation-count match, 25% script coverage, and 25% issue-free native structure.",
            native_evidence,
        ),
        _component(
            "package_manifest_integrity",
            10.0,
            _number(manifest_assessment.get("score")),
            manifest_raw,
            "SHA-256 and byte-size verification over every unique manifest file record.",
            manifest_evidence,
        ),
    ]
    missing_subjects = [subject for subject in SUBJECTS if subject not in subjects]
    below_threshold = {
        subject: raw[subject]["independent_score"]
        for subject in SUBJECTS
        if raw[subject]["independent_score"] < minimum_score
    }
    cheat_raw = {
        subject: {
            "draw_text_boxes": _integer(
                generation_subjects.get(subject, {}).get("draw_text_boxes")
            ),
            "full_page_images": _integer(
                generation_subjects.get(subject, {}).get("full_page_images")
            ),
            "full_page_raster_fallback": generation_subjects.get(subject, {}).get(
                "full_page_raster_fallback"
            ),
        }
        for subject in SUBJECTS
    }
    no_cheat = all(
        item["draw_text_boxes"] == 0
        and item["full_page_images"] == 0
        and item["full_page_raster_fallback"] is False
        for item in cheat_raw.values()
    )
    gates = [
        _gate(
            "independent_quality_present",
            bool(independent_path),
            "An independent_quality JSON must be discoverable in the package.",
            {"path": independent_path},
        ),
        _gate(
            "all_subjects_independently_scored",
            not missing_subjects,
            "Independent quality evidence must contain all four subjects.",
            {"missing_subjects": missing_subjects},
        ),
        _gate(
            "each_subject_at_least_minimum",
            not below_threshold,
            "Every independent subject score must meet the CLI minimum score.",
            {"below_minimum": below_threshold},
        ),
        _gate(
            "all_independent_hard_gates",
            all(not value for value in failed_hard_gates.values()),
            "Every independent_quality hard gate must pass.",
            {"failed_by_subject": failed_hard_gates},
        ),
        _gate(
            "no_text_box_or_full_page_raster_cheat",
            no_cheat,
            "Generation must use no draw-text boxes, full-page images, or raster fallback.",
            cheat_raw,
        ),
        _gate(
            "native_math_structure_valid",
            bool(native_assessment.get("all_subjects_valid")),
            "Both math HWPX files must have exact native equation/script counts and no structure issues.",
            native_assessment,
        ),
        _gate(
            "package_manifest_all_records_valid",
            bool(manifest_assessment.get("all_records_valid"))
            and bool(manifest_assessment.get("all_core_assets_valid")),
            "All manifest records and all twelve core source/HWPX/Hancom-PDF assets must verify.",
            manifest_raw,
        ),
        _gate(
            "quality_evidence_declared_in_manifest",
            bool(manifest_assessment.get("all_evidence_declared")),
            "Every report used by this scorer must be declared by package_manifest.json.",
            {"undeclared_evidence": manifest_assessment.get("undeclared_evidence", [])},
        ),
    ]
    return _theme("conversion", "변환", components, gates, minimum_score)


def _first_positive(mapping: dict[str, Any], keys: tuple[str, ...]) -> tuple[float, str | None]:
    for key in keys:
        value = _number(mapping.get(key))
        if value > 0.0:
            return value, key
    return 0.0, None


def _subject_timings_from_list(subjects: Any) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in _as_list(subjects):
        if not isinstance(item, dict) or item.get("subject") not in SUBJECTS:
            continue
        elapsed = _number(item.get("elapsed_seconds"))
        if elapsed > 0.0:
            result[str(item["subject"])] = elapsed
    return result


def _extract_speed_measurements(
    speed_data: dict[str, Any] | None,
    speed_path: str | None,
    summary_data: dict[str, Any] | None,
    summary_path: str | None,
    generation_data: dict[str, Any] | None,
    generation_path: str | None,
    generation_subjects: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_kind: str | None = None
    source_path: str | None = None
    source_data: dict[str, Any] = {}
    measurements: dict[str, Any] = {}
    subject_elapsed: dict[str, float] = {}
    correctness_gate: bool | None = None

    if isinstance(speed_data, dict):
        source_kind = "speed_benchmark"
        source_path = speed_path
        source_data = speed_data
        measurements = _as_dict(speed_data.get("measurements"))
        subject_elapsed = _subject_timings_from_list(speed_data.get("subjects"))
        correctness_gate = bool(speed_data.get("correctness_gate"))
    else:
        for kind, path, data in (
            ("final_validation_summary", summary_path, summary_data),
            ("generation_report", generation_path, generation_data),
        ):
            timing = _as_dict(_as_dict(data).get("generation_elapsed_seconds"))
            if timing:
                source_kind = kind
                source_path = path
                source_data = _as_dict(data)
                measurements = timing
                subject_elapsed = {
                    subject: _number(timing.get(subject))
                    for subject in SUBJECTS
                    if _number(timing.get(subject)) > 0.0
                }
                break

    parallel_wall, parallel_field = _first_positive(
        measurements,
        (
            "parallel_wall_seconds",
            "parallel_wall_time",
            "parallel_wall_time_approx",
            "wall_seconds",
        ),
    )
    total_cpu, total_cpu_field = _first_positive(
        measurements, ("total_cpu_seconds", "aggregate_cpu_seconds")
    )
    total_pages = _integer(measurements.get("total_pages"))
    if total_pages <= 0:
        total_pages = sum(
            _integer(generation_subjects.get(subject, {}).get("source_pages"))
            for subject in SUBJECTS
        )
    if total_cpu <= 0.0 and len(subject_elapsed) == len(SUBJECTS):
        total_cpu = sum(subject_elapsed.values())
        total_cpu_field = "derived_sum_of_subject_elapsed_seconds"

    aggregate_cpu, aggregate_field = _first_positive(
        measurements,
        ("aggregate_cpu_seconds_per_page", "total_cpu_seconds_per_page"),
    )
    if aggregate_cpu <= 0.0 and total_cpu > 0.0 and total_pages > 0:
        aggregate_cpu = total_cpu / total_pages
        aggregate_field = "derived_total_cpu_seconds_divided_by_total_pages"

    worst_subject, worst_field = _first_positive(
        measurements,
        ("worst_subject_seconds_per_page", "maximum_subject_seconds_per_page"),
    )
    per_subject_seconds_per_page: dict[str, float] = {}
    for subject, elapsed in subject_elapsed.items():
        pages = _integer(generation_subjects.get(subject, {}).get("source_pages"))
        if pages > 0:
            per_subject_seconds_per_page[subject] = elapsed / pages
    if worst_subject <= 0.0 and len(per_subject_seconds_per_page) == len(SUBJECTS):
        worst_subject = max(per_subject_seconds_per_page.values())
        worst_field = "derived_maximum_subject_elapsed_divided_by_subject_pages"

    if correctness_gate is None:
        correctness_gate = all(
            _integer(generation_subjects.get(subject, {}).get("source_pages")) > 0
            and _integer(generation_subjects.get(subject, {}).get("source_pages"))
            == _integer(generation_subjects.get(subject, {}).get("pages"))
            for subject in SUBJECTS
        )

    return {
        "source_kind": source_kind,
        "source_path": source_path,
        "parallel_wall_seconds": parallel_wall,
        "parallel_wall_source_field": parallel_field,
        "total_cpu_seconds": total_cpu,
        "total_cpu_source_field": total_cpu_field,
        "total_pages": total_pages,
        "aggregate_cpu_seconds_per_page": aggregate_cpu,
        "aggregate_cpu_source_field": aggregate_field,
        "worst_subject_seconds_per_page": worst_subject,
        "worst_subject_source_field": worst_field,
        "subject_elapsed_seconds": {
            key: round(value, 6) for key, value in subject_elapsed.items()
        },
        "subject_seconds_per_page": {
            key: round(value, 6)
            for key, value in per_subject_seconds_per_page.items()
        },
        "correctness_gate": bool(correctness_gate),
        "reported_sla": _as_dict(source_data.get("sla")),
    }


def _score_speed(
    measurements: dict[str, Any],
    parallel_wall_sla: float,
    worst_subject_sla: float,
    aggregate_cpu_sla: float,
    minimum_score: float,
) -> dict[str, Any]:
    evidence = [measurements["source_path"]] if measurements.get("source_path") else []
    parallel = _number(measurements.get("parallel_wall_seconds"))
    worst = _number(measurements.get("worst_subject_seconds_per_page"))
    aggregate = _number(measurements.get("aggregate_cpu_seconds_per_page"))
    components = [
        _component(
            "parallel_wall_time",
            50.0,
            _bounded_sla_score(parallel, parallel_wall_sla),
            {
                "actual_seconds": parallel,
                "sla_seconds": parallel_wall_sla,
                "actual_over_sla_ratio": round(parallel / parallel_wall_sla, 6)
                if parallel > 0.0
                else None,
                "source_field": measurements.get("parallel_wall_source_field"),
            },
            "min(100, SLA / actual * 100); non-positive or missing actual is zero.",
            evidence,
        ),
        _component(
            "worst_subject_throughput",
            30.0,
            _bounded_sla_score(worst, worst_subject_sla),
            {
                "actual_seconds_per_page": round(worst, 6),
                "sla_seconds_per_page": worst_subject_sla,
                "actual_over_sla_ratio": round(worst / worst_subject_sla, 6)
                if worst > 0.0
                else None,
                "source_field": measurements.get("worst_subject_source_field"),
                "subjects": measurements.get("subject_seconds_per_page", {}),
            },
            "min(100, SLA / actual * 100) for the slowest subject.",
            evidence,
        ),
        _component(
            "aggregate_cpu_throughput",
            20.0,
            _bounded_sla_score(aggregate, aggregate_cpu_sla),
            {
                "actual_seconds_per_page": round(aggregate, 6),
                "sla_seconds_per_page": aggregate_cpu_sla,
                "actual_over_sla_ratio": round(aggregate / aggregate_cpu_sla, 6)
                if aggregate > 0.0
                else None,
                "source_field": measurements.get("aggregate_cpu_source_field"),
                "total_cpu_seconds": round(
                    _number(measurements.get("total_cpu_seconds")), 6
                ),
                "total_pages": _integer(measurements.get("total_pages")),
            },
            "min(100, SLA / actual * 100) for summed CPU seconds per source page.",
            evidence,
        ),
    ]
    actuals_present = parallel > 0.0 and worst > 0.0 and aggregate > 0.0
    four_subject_timings = set(
        _as_dict(measurements.get("subject_elapsed_seconds"))
    ) == set(SUBJECTS)
    gates = [
        _gate(
            "measured_elapsed_evidence_present",
            bool(measurements.get("source_path")) and actuals_present,
            "Speed must use positive elapsed measurements from a packaged report, never file timestamps.",
            {
                "source_kind": measurements.get("source_kind"),
                "source_path": measurements.get("source_path"),
                "parallel_wall_seconds": parallel,
                "worst_subject_seconds_per_page": worst,
                "aggregate_cpu_seconds_per_page": aggregate,
            },
        ),
        _gate(
            "four_subject_elapsed_measurements_present",
            four_subject_timings,
            "Measured elapsed_seconds must be present for all four subjects.",
            {"subject_elapsed_seconds": measurements.get("subject_elapsed_seconds", {})},
        ),
        _gate(
            "timed_conversions_correct",
            bool(measurements.get("correctness_gate")),
            "The conversions used for timing must also pass their page/output correctness gate.",
            {"correctness_gate": measurements.get("correctness_gate")},
        ),
    ]
    return _theme("speed", "속도", components, gates, minimum_score)


def _semantic_component(report: dict[str, Any], name: str) -> dict[str, Any]:
    semantic = _as_dict(report.get("semantic_implementation"))
    return _as_dict(_as_dict(semantic.get("components")).get(name))


def _assessed_score(component: dict[str, Any]) -> float:
    if str(component.get("status") or "").casefold() != "assessed":
        return 0.0
    return _clip(_number(component.get("score")))


def _score_final_comparison(
    visual: dict[str, dict[str, Any]],
    generation_subjects: dict[str, dict[str, Any]],
    native_assessment: dict[str, Any],
    native_path: str | None,
    minimum_score: float,
) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    page_scores: list[tuple[float, float]] = []
    render_scores: list[tuple[float, float]] = []
    text_scores: list[tuple[float, float]] = []
    problem_scores: list[tuple[float, float]] = []
    duplicate_scores: list[tuple[float, float]] = []
    divider_scores: list[tuple[float, float]] = []
    visual_paths: list[str] = []

    for subject in SUBJECTS:
        selected = visual.get(subject, {})
        report = _as_dict(selected.get("data"))
        path = selected.get("path")
        path_text = str(path) if isinstance(path, str) else None
        if path_text:
            visual_paths.append(path_text)
        page_component = _semantic_component(report, "page_count")
        text_component = _semantic_component(report, "text_preservation")
        problem_component = _semantic_component(report, "problem_number_preservation")
        duplicate_component = _semantic_component(report, "duplicate_pages")
        divider_component = _semantic_component(report, "central_divider")
        raw_visual = _as_dict(report.get("raw_visual_metrics"))
        source_pages = _integer(report.get("source_page_count")) or _integer(
            generation_subjects.get(subject, {}).get("source_pages")
        )
        page_weight = float(max(1, source_pages))
        available = bool(report.get("available")) and not bool(report.get("skipped"))
        page_score = _assessed_score(page_component) if available else 0.0
        minimum_strict = _number(raw_visual.get("minimum_strict_alignment_ratio"))
        strict_target = _number(
            raw_visual.get("target_minimum_strict_alignment_ratio"), 0.75
        )
        render_score = (
            _clip(minimum_strict / strict_target * 100.0)
            if available and minimum_strict > 0.0 and strict_target > 0.0
            else 0.0
        )
        text_score = _assessed_score(text_component) if available else 0.0
        problem_score = _assessed_score(problem_component) if available else 0.0
        duplicate_score = _assessed_score(duplicate_component) if available else 0.0
        divider_score = _assessed_score(divider_component) if available else 0.0
        rows[subject] = {
            "report_path": path_text,
            "available": available,
            "source_page_count": source_pages,
            "output_page_count": _integer(report.get("output_page_count")),
            "pages_compared": _integer(report.get("pages_compared")),
            "all_pages_analyzed": bool(report.get("all_pages_analyzed")),
            "missing_output_pages": _as_list(report.get("missing_output_pages")),
            "unexpected_output_pages": _as_list(report.get("unexpected_output_pages")),
            "aspect_ratio_mismatch_pages": _as_list(
                report.get("aspect_ratio_mismatch_pages")
            ),
            "page_count": {
                "status": page_component.get("status"),
                "score": page_score,
                "exact_match": bool(page_component.get("exact_match")),
            },
            "strict_render_alignment": {
                "minimum_ratio": minimum_strict,
                "target_ratio": strict_target,
                "normalized_score": round(render_score, 4),
            },
            "pdf_text_preservation": {
                "status": text_component.get("status"),
                "score": text_score,
                "source_extracted_characters": _integer(
                    text_component.get("source_extracted_characters")
                ),
                "output_extracted_characters": _integer(
                    text_component.get("output_extracted_characters")
                ),
                "recall_ratio": _number(text_component.get("recall_ratio")),
                "precision_ratio": _number(text_component.get("precision_ratio")),
            },
            "problem_numbers": {
                "status": problem_component.get("status"),
                "score": problem_score,
                "missing_numbers": _as_list(problem_component.get("missing_numbers")),
                "unexpected_numbers": _as_list(
                    problem_component.get("unexpected_numbers")
                ),
            },
            "duplicates": {
                "status": duplicate_component.get("status"),
                "score": duplicate_score,
                "unexpected_output_duplicate_pairs": _as_list(
                    duplicate_component.get("unexpected_output_duplicate_pairs")
                ),
                "unexpected_output_duplicate_pages": _as_list(
                    duplicate_component.get("unexpected_output_duplicate_pages")
                ),
            },
            "central_divider": {
                "status": divider_component.get("status"),
                "score": divider_score,
                "mismatch_pages": _as_list(divider_component.get("mismatch_pages")),
            },
        }
        page_scores.append((page_score, page_weight))
        render_scores.append((render_score, page_weight))
        text_scores.append((text_score, page_weight))
        problem_scores.append((problem_score, page_weight))
        duplicate_scores.append((duplicate_score, page_weight))
        divider_scores.append((divider_score, page_weight))

    native_evidence = [native_path] if native_path else []
    components = [
        _component(
            "page_and_render_completeness",
            15.0,
            _weighted_average(page_scores),
            rows,
            "Assessed exact page-count preservation across all visual reports.",
            visual_paths,
        ),
        _component(
            "strict_pdf_render_alignment",
            20.0,
            _weighted_average(render_scores),
            rows,
            "Per subject min(100, minimum strict-alignment ratio / explicit visual target).",
            visual_paths,
        ),
        _component(
            "pdf_text_extraction_evidence",
            10.0,
            _weighted_average(text_scores),
            rows,
            "Actual assessed PDF text-preservation score. Unassessed text is zero, never free credit.",
            visual_paths,
        ),
        _component(
            "native_math_structure_evidence",
            20.0,
            _number(native_assessment.get("score")),
            native_assessment,
            "Independent HWPX native equation count, script coverage, and structure validation for math.",
            native_evidence,
        ),
        _component(
            "problem_number_preservation",
            15.0,
            _weighted_average(problem_scores),
            rows,
            "Assessed source/output problem-number preservation from rendered PDFs.",
            visual_paths,
        ),
        _component(
            "rendered_duplicate_control",
            10.0,
            _weighted_average(duplicate_scores),
            rows,
            "Assessed unexpected rendered-page duplicate detection.",
            visual_paths,
        ),
        _component(
            "central_divider_preservation",
            10.0,
            _weighted_average(divider_scores),
            rows,
            "Assessed vector/raster central-divider preservation by page.",
            visual_paths,
        ),
    ]
    missing_visual = [subject for subject in SUBJECTS if subject not in visual]
    pages_exact = all(
        rows[subject]["available"]
        and rows[subject]["all_pages_analyzed"]
        and rows[subject]["source_page_count"] > 0
        and rows[subject]["source_page_count"] == rows[subject]["output_page_count"]
        and rows[subject]["page_count"]["exact_match"]
        and not rows[subject]["missing_output_pages"]
        and not rows[subject]["unexpected_output_pages"]
        and not rows[subject]["aspect_ratio_mismatch_pages"]
        for subject in SUBJECTS
    )
    strict_ok = all(
        rows[subject]["strict_render_alignment"]["minimum_ratio"]
        >= rows[subject]["strict_render_alignment"]["target_ratio"]
        > 0.0
        for subject in SUBJECTS
    )
    text_assessed = all(
        rows[subject]["pdf_text_preservation"]["status"] == "assessed"
        and rows[subject]["pdf_text_preservation"]["source_extracted_characters"] > 0
        and rows[subject]["pdf_text_preservation"]["output_extracted_characters"] > 0
        for subject in SUBJECTS
    )
    problems_ok = all(
        rows[subject]["problem_numbers"]["status"] == "assessed"
        and rows[subject]["problem_numbers"]["score"] == 100.0
        and not rows[subject]["problem_numbers"]["missing_numbers"]
        and not rows[subject]["problem_numbers"]["unexpected_numbers"]
        for subject in SUBJECTS
    )
    duplicates_ok = all(
        rows[subject]["duplicates"]["status"] == "assessed"
        and rows[subject]["duplicates"]["score"] == 100.0
        and not rows[subject]["duplicates"]["unexpected_output_duplicate_pairs"]
        and not rows[subject]["duplicates"]["unexpected_output_duplicate_pages"]
        for subject in SUBJECTS
    )
    dividers_ok = all(
        rows[subject]["central_divider"]["status"] == "assessed"
        and rows[subject]["central_divider"]["score"] == 100.0
        and not rows[subject]["central_divider"]["mismatch_pages"]
        for subject in SUBJECTS
    )
    math_combined_ok = bool(native_assessment.get("all_subjects_valid")) and all(
        rows[subject]["strict_render_alignment"]["minimum_ratio"]
        >= rows[subject]["strict_render_alignment"]["target_ratio"]
        and rows[subject]["problem_numbers"]["score"] == 100.0
        and rows[subject]["duplicates"]["score"] == 100.0
        and rows[subject]["central_divider"]["score"] == 100.0
        for subject in MATH_SUBJECTS
    )
    gates = [
        _gate(
            "all_visual_reports_present",
            not missing_visual,
            "A visual report must be discoverable for each of the four subjects.",
            {"missing_subjects": missing_visual},
        ),
        _gate(
            "all_rendered_pages_exact_and_analyzed",
            pages_exact,
            "All pages must be analyzed with exact counts and no missing, extra, or aspect-mismatched pages.",
            {
                subject: {
                    "source": rows[subject]["source_page_count"],
                    "output": rows[subject]["output_page_count"],
                    "all_pages_analyzed": rows[subject]["all_pages_analyzed"],
                }
                for subject in SUBJECTS
            },
        ),
        _gate(
            "strict_render_alignment_targets_met",
            strict_ok,
            "Every minimum strict rendered-PDF alignment ratio must meet its explicit target.",
            {
                subject: rows[subject]["strict_render_alignment"]
                for subject in SUBJECTS
            },
        ),
        _gate(
            "pdf_text_evidence_not_waived",
            text_assessed,
            "PDF text evidence must be assessed and non-empty; unavailable equation text receives no free score.",
            {
                subject: rows[subject]["pdf_text_preservation"]
                for subject in SUBJECTS
            },
        ),
        _gate(
            "problem_numbers_complete",
            problems_ok,
            "Rendered source/output problem numbers must match exactly for every subject.",
            {subject: rows[subject]["problem_numbers"] for subject in SUBJECTS},
        ),
        _gate(
            "no_unexpected_rendered_duplicates",
            duplicates_ok,
            "Rendered outputs must contain no unexpected exact or near duplicate pages.",
            {subject: rows[subject]["duplicates"] for subject in SUBJECTS},
        ),
        _gate(
            "central_dividers_match",
            dividers_ok,
            "Central-divider presence must match on every rendered page.",
            {subject: rows[subject]["central_divider"] for subject in SUBJECTS},
        ),
        _gate(
            "math_native_render_and_semantics_combined",
            math_combined_ok,
            "Math requires native HWPX equations plus render alignment, problem numbers, duplicates, and divider evidence.",
            {
                "native_math": native_assessment,
                "math_visual": {subject: rows[subject] for subject in MATH_SUBJECTS},
            },
        ),
    ]
    return _theme(
        "final_comparison", "완성본 비교", components, gates, minimum_score
    )


def _evidence_paths(discovery: dict[str, Any], package_dir: Path) -> dict[str, Any]:
    def selected_path(name: str) -> str | None:
        path = _as_dict(discovery.get(name)).get("path")
        return _json_path(path, package_dir) if isinstance(path, Path) else None

    visual = {
        subject: _json_path(_as_dict(value).get("path"), package_dir)
        for subject, value in _as_dict(discovery.get("visual")).items()
        if isinstance(_as_dict(value).get("path"), Path)
    }
    return {
        "package_manifest": "package_manifest.json",
        "generation_report": selected_path("generation"),
        "detection_quality": selected_path("detection"),
        "independent_quality": selected_path("independent"),
        "native_math_structure": selected_path("native_math"),
        "visual_reports": visual,
        "speed_benchmark": selected_path("speed"),
        "final_validation_summary": selected_path("summary"),
        "ignored_alternates": discovery.get("alternates", {}),
    }


def evaluate_package(
    package_dir: Path,
    *,
    minimum_score: float,
    parallel_wall_sla: float,
    worst_subject_sla: float,
    aggregate_cpu_sla: float,
) -> dict[str, Any]:
    manifest_path = package_dir / "package_manifest.json"
    manifest = _load_json(manifest_path) if manifest_path.is_file() else None
    discovery = _discover_evidence(package_dir)
    evidence = _evidence_paths(discovery, package_dir)
    generation_data = _as_dict(_as_dict(discovery.get("generation")).get("data"))
    detection_data = _as_dict(_as_dict(discovery.get("detection")).get("data"))
    independent_data = _as_dict(_as_dict(discovery.get("independent")).get("data"))
    native_data = _as_dict(_as_dict(discovery.get("native_math")).get("data"))
    speed_data = _as_dict(_as_dict(discovery.get("speed")).get("data"))
    summary_data = _as_dict(_as_dict(discovery.get("summary")).get("data"))
    generation_subjects = _generation_subjects(generation_data)

    required_evidence = [
        path
        for path in (
            evidence.get("generation_report"),
            evidence.get("detection_quality"),
            evidence.get("independent_quality"),
            evidence.get("native_math_structure"),
            *evidence.get("visual_reports", {}).values(),
            evidence.get("speed_benchmark") or evidence.get("final_validation_summary"),
        )
        if isinstance(path, str)
    ]
    manifest_assessment = _validate_manifest(
        package_dir, manifest, required_evidence
    )
    native_assessment = _assess_native_math(
        native_data or None, generation_subjects, manifest
    )
    speed_measurements = _extract_speed_measurements(
        speed_data or None,
        evidence.get("speed_benchmark"),
        summary_data or None,
        evidence.get("final_validation_summary"),
        generation_data or None,
        evidence.get("generation_report"),
        generation_subjects,
    )
    visual_for_scoring = {
        subject: {
            "path": evidence.get("visual_reports", {}).get(subject),
            "data": _as_dict(value).get("data"),
        }
        for subject, value in _as_dict(discovery.get("visual")).items()
    }

    themes = {
        "detection": (
            _score_independent_detection(
                detection_data,
                evidence.get("detection_quality"),
                minimum_score,
            )
            if detection_data
            else _score_detection(
                generation_data or None,
                evidence.get("generation_report"),
                minimum_score,
            )
        ),
        "conversion": _score_conversion(
            independent_data or None,
            evidence.get("independent_quality"),
            generation_subjects,
            native_assessment,
            evidence.get("native_math_structure"),
            manifest_assessment,
            evidence.get("package_manifest"),
            minimum_score,
        ),
        "speed": _score_speed(
            speed_measurements,
            parallel_wall_sla,
            worst_subject_sla,
            aggregate_cpu_sla,
            minimum_score,
        ),
        "final_comparison": _score_final_comparison(
            visual_for_scoring,
            generation_subjects,
            native_assessment,
            evidence.get("native_math_structure"),
            minimum_score,
        ),
    }
    below_minimum = [
        name for name, theme in themes.items() if _number(theme.get("score")) < minimum_score
    ]
    failed_gates = {
        name: [gate["id"] for gate in theme["gates"] if not gate["passed"]]
        for name, theme in themes.items()
        if not theme["gate_passed"]
    }
    return {
        "schema_version": 1,
        "rubric": "four_theme_quality_100",
        "package_dir": str(package_dir.resolve()),
        "minimum_score": minimum_score,
        "policy": {
            "theme_scores_are_independent": True,
            "maximum_score_per_theme": 100.0,
            "exit_1_when_any_theme_below_minimum": True,
            "hard_gates_also_required": True,
            "speed_sla": {
                "parallel_wall_seconds": parallel_wall_sla,
                "worst_subject_seconds_per_page": worst_subject_sla,
                "aggregate_cpu_seconds_per_page": aggregate_cpu_sla,
            },
            "math_pdf_text_policy": (
                "PDF text preservation is scored as measured and unassessed text gets zero; "
                "native HWPX equations, strict PDF renders, problem numbers, duplicates, and "
                "central dividers are separate evidence, not a text-extraction waiver."
            ),
        },
        "evidence": evidence,
        "scores": {name: theme["score"] for name, theme in themes.items()},
        "themes": themes,
        "below_minimum": below_minimum,
        "failed_gates": failed_gates,
        "ok": not below_minimum and not failed_gates,
    }


def _positive_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return number


def _minimum_score(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 100.0:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Score detection, conversion, speed, and final-output comparison as four "
            "independent 100-point themes from a packaged four-subject delivery."
        )
    )
    parser.add_argument("package_dir", type=Path, help="final package directory")
    parser.add_argument(
        "--report",
        "--output",
        dest="report",
        type=Path,
        default=None,
        help="optional path for the full JSON report; JSON is always printed to stdout",
    )
    parser.add_argument(
        "--minimum-score",
        "--min-score",
        dest="minimum_score",
        type=_minimum_score,
        default=DEFAULT_MINIMUM_SCORE,
    )
    parser.add_argument(
        "--parallel-wall-sla-seconds",
        type=_positive_float,
        default=DEFAULT_PARALLEL_WALL_SLA_SECONDS,
    )
    parser.add_argument(
        "--worst-subject-seconds-per-page-sla",
        type=_positive_float,
        default=DEFAULT_WORST_SUBJECT_SECONDS_PER_PAGE_SLA,
    )
    parser.add_argument(
        "--aggregate-cpu-seconds-per-page-sla",
        type=_positive_float,
        default=DEFAULT_AGGREGATE_CPU_SECONDS_PER_PAGE_SLA,
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    package_dir = args.package_dir.expanduser().resolve()
    if not package_dir.is_dir():
        _parser().error(f"package directory not found: {package_dir}")
    report = evaluate_package(
        package_dir,
        minimum_score=float(args.minimum_score),
        parallel_wall_sla=float(args.parallel_wall_sla_seconds),
        worst_subject_sla=float(args.worst_subject_seconds_per_page_sla),
        aggregate_cpu_sla=float(args.aggregate_cpu_seconds_per_page_sla),
    )
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report is not None:
        report_path = args.report.expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(output + "\n", encoding="utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    print(output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
