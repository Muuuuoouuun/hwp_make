from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
SUBJECTS = ("korean", "english", "math_a", "math_b")
SUBJECT_LABELS = {
    "korean": "국어",
    "english": "영어",
    "math_a": "수학A",
    "math_b": "수학B",
}
GLOB_CHARACTERS = frozenset("*?[]")


class PackagingError(RuntimeError):
    """Raised when a package operation is incomplete or unsafe."""


@dataclass(frozen=True)
class SubjectInputs:
    hwpx: Path
    hancom_pdf: Path
    source_pdf: Path


@dataclass(frozen=True)
class PackagePlan:
    workspace: Path
    output_dir: Path | None
    subjects: dict[str, SubjectInputs]
    validation_inputs: tuple[Path, ...]
    comparison_inputs: tuple[Path, ...]
    obsolete_exports: tuple[Path, ...]
    package_requested: bool


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _contains_glob(value: str | os.PathLike[str]) -> bool:
    return any(character in os.fspath(value) for character in GLOB_CHARACTERS)


def _lexical_path(value: str | os.PathLike[str], workspace: Path) -> Path:
    if _contains_glob(value):
        raise PackagingError(f"glob patterns are not allowed: {value}")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = workspace / path
    return Path(os.path.abspath(path))


def _resolved_path(
    value: str | os.PathLike[str],
    workspace: Path,
    *,
    must_exist: bool,
    role: str,
) -> Path:
    lexical = _lexical_path(value, workspace)
    try:
        return lexical.resolve(strict=must_exist)
    except (FileNotFoundError, OSError) as exc:
        raise PackagingError(f"{role} does not exist or cannot be resolved: {lexical}") from exc


def _is_within(path: Path, directory: Path, *, allow_equal: bool = True) -> bool:
    try:
        relative = path.relative_to(directory)
    except ValueError:
        return False
    return allow_equal or bool(relative.parts)


def _paths_overlap(first: Path, second: Path) -> bool:
    return _is_within(first, second) or _is_within(second, first)


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _assert_strict_workspace_child(path: Path, workspace: Path, role: str) -> None:
    if not _is_within(path, workspace, allow_equal=False):
        raise PackagingError(f"{role} must be a strict child of the workspace: {path}")


def _validate_regular_file(path: Path, suffix: str, role: str) -> None:
    if not path.is_file():
        raise PackagingError(f"{role} must be a regular file: {path}")
    if path.suffix.casefold() != suffix.casefold():
        raise PackagingError(f"{role} must end with {suffix}: {path}")
    if path.stat().st_size <= 0:
        raise PackagingError(f"{role} is empty: {path}")


def _walk_material_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    files: list[Path] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if _is_link_like(path):
            raise PackagingError(f"material trees cannot contain links or junctions: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise PackagingError(f"material tree contains a non-regular entry: {path}")
        files.append(path)
    return files


def _validate_material(path: Path, role: str) -> None:
    if _is_link_like(path):
        raise PackagingError(f"{role} cannot be a link or junction: {path}")
    if not path.is_file() and not path.is_dir():
        raise PackagingError(f"{role} must be a file or directory: {path}")
    _walk_material_files(path)


def _validate_json_file(path: Path) -> None:
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackagingError(f"invalid validation JSON: {path}: {exc}") from exc


def _deduplicate_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return tuple(result)


def _validate_material_names(paths: Sequence[Path], role: str) -> None:
    destinations: dict[str, Path] = {}
    for path in paths:
        key = os.path.normcase(path.name)
        previous = destinations.get(key)
        if previous is not None:
            raise PackagingError(
                f"{role} inputs have the same top-level name: {previous} and {path}"
            )
        destinations[key] = path


def _manifest_list(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PackagingError(f"inputs manifest field '{key}' must be a list of paths")
    return value


def _load_inputs_manifest(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            data = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackagingError(f"cannot read inputs manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PackagingError("inputs manifest must contain a JSON object")
    allowed = {
        "output_dir",
        "subjects",
        "validation",
        "validation_json",
        "comparison",
        "comparison_materials",
        "obsolete_exports",
    }
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise PackagingError(f"unknown inputs manifest fields: {', '.join(unknown)}")
    return data


def _subject_values_from_manifest(data: dict[str, Any]) -> dict[str, dict[str, str]]:
    raw_subjects = data.get("subjects", {})
    if raw_subjects is None:
        return {}
    if not isinstance(raw_subjects, dict):
        raise PackagingError("inputs manifest field 'subjects' must be an object")
    unknown_subjects = sorted(set(raw_subjects) - set(SUBJECTS))
    if unknown_subjects:
        raise PackagingError(f"unknown subjects: {', '.join(unknown_subjects)}")

    result: dict[str, dict[str, str]] = {}
    for subject, raw in raw_subjects.items():
        if not isinstance(raw, dict):
            raise PackagingError(f"manifest subject '{subject}' must be an object")
        allowed = {"hwpx", "hancom_pdf", "actual_pdf", "source_pdf"}
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise PackagingError(
                f"unknown fields for manifest subject '{subject}': {', '.join(unknown)}"
            )
        values: dict[str, str] = {}
        for key in ("hwpx", "source_pdf"):
            if key in raw:
                if not isinstance(raw[key], str):
                    raise PackagingError(f"manifest {subject}.{key} must be a path string")
                values[key] = raw[key]
        hancom_value = raw.get("hancom_pdf", raw.get("actual_pdf"))
        if hancom_value is not None:
            if not isinstance(hancom_value, str):
                raise PackagingError(f"manifest {subject}.hancom_pdf must be a path string")
            values["hancom_pdf"] = hancom_value
        result[subject] = values
    return result


def _package_fields_present(args: argparse.Namespace, manifest: dict[str, Any]) -> bool:
    if manifest.get("subjects"):
        return True
    if manifest.get("validation") or manifest.get("validation_json"):
        return True
    if manifest.get("comparison") or manifest.get("comparison_materials"):
        return True
    for subject in SUBJECTS:
        for field in ("hwpx", "hancom_pdf", "source_pdf"):
            if getattr(args, f"{subject}_{field}") is not None:
                return True
    return bool(args.validation_json or args.comparison_material)


def _build_plan(args: argparse.Namespace) -> PackagePlan:
    workspace_lexical = Path(args.workspace).expanduser()
    try:
        workspace = workspace_lexical.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise PackagingError(f"workspace does not exist: {workspace_lexical}") from exc
    if not workspace.is_dir():
        raise PackagingError(f"workspace is not a directory: {workspace}")

    manifest: dict[str, Any] = {}
    if args.inputs_manifest is not None:
        manifest_path = _resolved_path(
            args.inputs_manifest,
            workspace,
            must_exist=True,
            role="inputs manifest",
        )
        _validate_regular_file(manifest_path, ".json", "inputs manifest")
        manifest = _load_inputs_manifest(manifest_path)

    package_requested = _package_fields_present(args, manifest) or args.replace
    manifest_subjects = _subject_values_from_manifest(manifest)
    subjects: dict[str, SubjectInputs] = {}
    missing: list[str] = []
    if package_requested:
        for subject in SUBJECTS:
            values = manifest_subjects.get(subject, {}).copy()
            for field in ("hwpx", "hancom_pdf", "source_pdf"):
                command_line_value = getattr(args, f"{subject}_{field}")
                if command_line_value is not None:
                    values[field] = os.fspath(command_line_value)
                if field not in values:
                    missing.append(f"--{subject.replace('_', '-')}-{field.replace('_', '-')}")
            if all(field in values for field in ("hwpx", "hancom_pdf", "source_pdf")):
                subjects[subject] = SubjectInputs(
                    hwpx=_resolved_path(
                        values["hwpx"], workspace, must_exist=True, role=f"{subject} HWPX"
                    ),
                    hancom_pdf=_resolved_path(
                        values["hancom_pdf"],
                        workspace,
                        must_exist=True,
                        role=f"{subject} Hancom PDF",
                    ),
                    source_pdf=_resolved_path(
                        values["source_pdf"],
                        workspace,
                        must_exist=True,
                        role=f"{subject} source PDF",
                    ),
                )
        if missing:
            raise PackagingError(
                "a package requires all three inputs for all four subjects; missing: "
                + ", ".join(missing)
            )

    validation_values = (
        _manifest_list(manifest.get("validation"), "validation")
        + _manifest_list(manifest.get("validation_json"), "validation_json")
        + [os.fspath(path) for path in (args.validation_json or [])]
    )
    comparison_values = (
        _manifest_list(manifest.get("comparison"), "comparison")
        + _manifest_list(manifest.get("comparison_materials"), "comparison_materials")
        + [os.fspath(path) for path in (args.comparison_material or [])]
    )
    obsolete_values = _manifest_list(manifest.get("obsolete_exports"), "obsolete_exports") + [
        os.fspath(path) for path in (args.obsolete_export or [])
    ]

    validation_inputs = _deduplicate_paths(
        _resolved_path(value, workspace, must_exist=True, role="validation input")
        for value in validation_values
    )
    comparison_inputs = _deduplicate_paths(
        _resolved_path(value, workspace, must_exist=True, role="comparison input")
        for value in comparison_values
    )

    obsolete_paths: list[Path] = []
    for value in obsolete_values:
        lexical = _lexical_path(value, workspace)
        if _is_link_like(lexical):
            raise PackagingError(f"obsolete export cannot be a link or junction: {lexical}")
        path = _resolved_path(
            value,
            workspace,
            must_exist=False,
            role="obsolete export",
        )
        _assert_strict_workspace_child(path, workspace, "obsolete export")
        if path.exists() and not path.is_dir():
            raise PackagingError(f"obsolete export is not a directory: {path}")
        obsolete_paths.append(path)
    obsolete_exports = _deduplicate_paths(obsolete_paths)

    output_dir: Path | None = None
    if package_requested:
        output_value = args.output_dir or manifest.get("output_dir") or "data/exports/final_results"
        if not isinstance(output_value, (str, os.PathLike)):
            raise PackagingError("output_dir must be a path string")
        output_lexical = _lexical_path(output_value, workspace)
        if _is_link_like(output_lexical):
            raise PackagingError(f"output directory cannot be a link or junction: {output_lexical}")
        output_dir = _resolved_path(
            output_value,
            workspace,
            must_exist=False,
            role="output directory",
        )
        _assert_strict_workspace_child(output_dir, workspace, "output directory")
        if output_dir.exists() and not output_dir.is_dir():
            raise PackagingError(f"output path exists and is not a directory: {output_dir}")
        if output_dir.parent.exists() and not output_dir.parent.is_dir():
            raise PackagingError(f"output parent is not a directory: {output_dir.parent}")

    plan = PackagePlan(
        workspace=workspace,
        output_dir=output_dir,
        subjects=subjects,
        validation_inputs=validation_inputs,
        comparison_inputs=comparison_inputs,
        obsolete_exports=obsolete_exports,
        package_requested=package_requested,
    )
    _validate_plan(plan, replace=args.replace, clean=args.clean)
    return plan


def _validate_plan(plan: PackagePlan, *, replace: bool, clean: bool) -> None:
    if not plan.package_requested and not plan.obsolete_exports:
        raise PackagingError("nothing to do: provide package inputs or --obsolete-export")
    if replace and not plan.package_requested:
        raise PackagingError("--replace requires a complete package input set")
    if clean and not plan.obsolete_exports:
        raise PackagingError("--clean requires at least one explicit --obsolete-export")
    if clean and plan.package_requested and not replace:
        raise PackagingError("--clean with package inputs also requires --replace")

    source_roots: list[Path] = []
    if plan.package_requested:
        if plan.output_dir is None:
            raise PackagingError("internal error: package output is missing")
        if len(plan.subjects) != len(SUBJECTS):
            raise PackagingError("all four subjects are required")
        if not plan.validation_inputs:
            raise PackagingError("a package requires at least one --validation-json input")
        if not plan.comparison_inputs:
            raise PackagingError("a package requires at least one --comparison-material input")

        for subject, inputs in plan.subjects.items():
            _validate_regular_file(inputs.hwpx, ".hwpx", f"{subject} HWPX")
            _validate_regular_file(inputs.hancom_pdf, ".pdf", f"{subject} Hancom PDF")
            _validate_regular_file(inputs.source_pdf, ".pdf", f"{subject} source PDF")
            source_roots.extend((inputs.hwpx, inputs.hancom_pdf, inputs.source_pdf))

        validation_json_count = 0
        for path in plan.validation_inputs:
            _validate_material(path, "validation input")
            json_files = [
                item
                for item in _walk_material_files(path)
                if item.suffix.casefold() == ".json"
            ]
            for json_file in json_files:
                _validate_json_file(json_file)
            validation_json_count += len(json_files)
        if validation_json_count == 0:
            raise PackagingError("validation inputs do not contain any .json files")

        for path in plan.comparison_inputs:
            _validate_material(path, "comparison input")
        _validate_material_names(plan.validation_inputs, "validation")
        _validate_material_names(plan.comparison_inputs, "comparison")
        source_roots.extend(plan.validation_inputs)
        source_roots.extend(plan.comparison_inputs)

        for source in source_roots:
            if _paths_overlap(source, plan.output_dir):
                raise PackagingError(
                    f"package input and output directory must not overlap: {source} / {plan.output_dir}"
                )

    for index, first in enumerate(plan.obsolete_exports):
        for second in plan.obsolete_exports[index + 1 :]:
            if _paths_overlap(first, second):
                raise PackagingError(
                    f"obsolete export directories must not overlap: {first} / {second}"
                )
        if plan.output_dir is not None and _paths_overlap(first, plan.output_dir):
            raise PackagingError(
                f"obsolete export cannot overlap the package output: {first} / {plan.output_dir}"
            )

    if clean and plan.package_requested:
        for obsolete in plan.obsolete_exports:
            for source in source_roots:
                if _is_within(source, obsolete) and not replace:
                    raise PackagingError(
                        f"refusing to clean a directory containing an uncopied package input: {obsolete}"
                    )


def _display_path(path: Path, workspace: Path) -> str:
    try:
        return path.relative_to(workspace).as_posix()
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_verified_file(source: Path, destination: Path, workspace: Path) -> dict[str, Any]:
    source_hash_before = _sha256(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    source_hash_after = _sha256(source)
    destination_hash = _sha256(destination)
    if source_hash_before != source_hash_after or source_hash_after != destination_hash:
        raise PackagingError(f"source changed while it was being packaged: {source}")
    return {
        "source": _display_path(source, workspace),
        "path": destination.as_posix(),
        "bytes": destination.stat().st_size,
        "sha256": destination_hash,
    }


def _copy_material_root(
    source: Path,
    staging: Path,
    category: str,
    workspace: Path,
) -> dict[str, Any]:
    relative_root = Path(category) / source.name
    destination_root = staging / relative_root
    records: list[dict[str, Any]] = []
    if source.is_file():
        metadata = _copy_verified_file(source, destination_root, workspace)
        metadata["path"] = relative_root.as_posix()
        records.append(metadata)
        kind = "file"
    else:
        destination_root.mkdir(parents=True, exist_ok=False)
        for entry in sorted(source.rglob("*"), key=lambda item: item.as_posix().casefold()):
            relative = entry.relative_to(source)
            destination = destination_root / relative
            if entry.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            metadata = _copy_verified_file(entry, destination, workspace)
            metadata["path"] = (relative_root / relative).as_posix()
            records.append(metadata)
        kind = "directory"
    return {
        "source": _display_path(source, workspace),
        "path": relative_root.as_posix(),
        "kind": kind,
        "files": records,
    }


def _write_json_atomic_source(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _build_staging(plan: PackagePlan, staging: Path) -> dict[str, Any]:
    if plan.output_dir is None:
        raise PackagingError("internal error: package output is missing")
    manifest_subjects: dict[str, Any] = {}
    for subject in SUBJECTS:
        inputs = plan.subjects[subject]
        subject_manifest: dict[str, Any] = {"label": SUBJECT_LABELS[subject]}
        artifacts = (
            ("hwpx", inputs.hwpx, Path("hwpx") / f"{subject}.hwpx"),
            ("hancom_pdf", inputs.hancom_pdf, Path("hancom_pdf") / f"{subject}.pdf"),
            ("source_pdf", inputs.source_pdf, Path("source_pdf") / f"{subject}.pdf"),
        )
        for role, source, relative_destination in artifacts:
            metadata = _copy_verified_file(source, staging / relative_destination, plan.workspace)
            metadata["path"] = relative_destination.as_posix()
            subject_manifest[role] = metadata
        manifest_subjects[subject] = subject_manifest

    validation_manifest = [
        _copy_material_root(source, staging, "validation", plan.workspace)
        for source in plan.validation_inputs
    ]
    comparison_manifest = [
        _copy_material_root(source, staging, "comparison", plan.workspace)
        for source in plan.comparison_inputs
    ]
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "output": _display_path(plan.output_dir, plan.workspace),
        "subjects": manifest_subjects,
        "validation": validation_manifest,
        "comparison": comparison_manifest,
    }
    _write_json_atomic_source(staging / "package_manifest.json", manifest)
    return manifest


def _remove_generated_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir() and not _is_link_like(path):
        shutil.rmtree(path)
    else:
        path.unlink()


def _publish_staging(staging: Path, output_dir: Path) -> list[str]:
    backup: Path | None = None
    warnings: list[str] = []
    if output_dir.exists():
        backup = output_dir.with_name(f".{output_dir.name}.backup-{uuid.uuid4().hex}")
        os.replace(output_dir, backup)
    try:
        os.replace(staging, output_dir)
    except BaseException:
        if backup is not None and backup.exists() and not output_dir.exists():
            os.replace(backup, output_dir)
        raise
    if backup is not None:
        try:
            _remove_generated_path(backup)
        except OSError as exc:
            warnings.append(f"new package is live, but old backup remains at {backup}: {exc}")
    return warnings


def _execute_package(plan: PackagePlan) -> tuple[dict[str, Any], list[str]]:
    if plan.output_dir is None:
        raise PackagingError("internal error: package output is missing")
    plan.output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{plan.output_dir.name}.staging-",
            dir=plan.output_dir.parent,
        )
    )
    try:
        manifest = _build_staging(plan, staging)
        warnings = _publish_staging(staging, plan.output_dir)
        return manifest, warnings
    except BaseException:
        _remove_generated_path(staging)
        raise


def _clean_obsolete_export(path: Path, workspace: Path) -> str:
    _assert_strict_workspace_child(path, workspace, "obsolete export")
    if not path.exists():
        return "missing"
    if _is_link_like(path):
        raise PackagingError(f"obsolete export became a link or junction: {path}")
    try:
        current = path.resolve(strict=True)
    except OSError as exc:
        raise PackagingError(f"cannot re-resolve obsolete export before deletion: {path}") from exc
    if current != path or not _is_within(current, workspace, allow_equal=False):
        raise PackagingError(f"obsolete export moved outside the workspace: {path} -> {current}")
    if not path.is_dir():
        raise PackagingError(f"obsolete export is no longer a directory: {path}")

    tombstone = path.with_name(f".{path.name}.deleting-{uuid.uuid4().hex}")
    os.replace(path, tombstone)
    try:
        shutil.rmtree(tombstone)
    except BaseException as exc:
        if tombstone.exists() and not path.exists():
            try:
                os.replace(tombstone, path)
            except OSError as rollback_exc:
                raise PackagingError(
                    f"cleanup failed and rollback also failed; inspect {tombstone}: {rollback_exc}"
                ) from exc
        raise PackagingError(f"cleanup failed for {path}: {exc}") from exc
    return "removed"


def _print_plan(plan: PackagePlan, *, replace: bool, clean: bool) -> None:
    if plan.package_requested:
        assert plan.output_dir is not None
        print(f"package: {'APPLY (--replace)' if replace else 'DRY RUN (--replace required)'}")
        print(f"output:  {plan.output_dir}")
        for subject in SUBJECTS:
            inputs = plan.subjects[subject]
            print(f"  {subject}: HWPX         {inputs.hwpx} -> hwpx/{subject}.hwpx")
            print(f"  {subject}: Hancom PDF   {inputs.hancom_pdf} -> hancom_pdf/{subject}.pdf")
            print(f"  {subject}: source PDF   {inputs.source_pdf} -> source_pdf/{subject}.pdf")
        for source in plan.validation_inputs:
            print(f"  validation: {source} -> validation/{source.name}")
        for source in plan.comparison_inputs:
            print(f"  comparison: {source} -> comparison/{source.name}")
    if plan.obsolete_exports:
        print(f"cleanup: {'APPLY (--clean)' if clean else 'DRY RUN (--clean required)'}")
        for path in plan.obsolete_exports:
            state = "missing; no-op" if not path.exists() else "directory"
            print(f"  obsolete: {path} ({state})")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Atomically package the four final HWPX files, actual Hancom PDFs, source PDFs, "
            "validation JSON, and comparison materials. The default is a dry run."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Inputs manifest schema (paths are relative to --workspace):\n"
            "  {\n"
            "    \"output_dir\": \"data/exports/final_delivery\",\n"
            "    \"subjects\": {\n"
            "      \"korean\": {\"hwpx\": \"...\", \"hancom_pdf\": \"...\", "
            "\"source_pdf\": \"...\"}\n"
            "    },\n"
            "    \"validation_json\": [\"...json\"],\n"
            "    \"comparison_materials\": [\"...\"],\n"
            "    \"obsolete_exports\": [\"data/exports/old\"]\n"
            "  }\n\n"
            "Use --replace to publish/replace the package and --clean to remove only the exact\n"
            "directories listed with --obsolete-export (or in the inputs manifest)."
        ),
    )
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--inputs-manifest", type=Path)
    parser.add_argument("--output-dir", "--output", dest="output_dir", type=Path)

    for subject in SUBJECTS:
        option_subject = subject.replace("_", "-")
        parser.add_argument(f"--{option_subject}-hwpx", dest=f"{subject}_hwpx", type=Path)
        parser.add_argument(
            f"--{option_subject}-hancom-pdf",
            f"--{option_subject}-actual-pdf",
            dest=f"{subject}_hancom_pdf",
            type=Path,
        )
        parser.add_argument(
            f"--{option_subject}-source-pdf",
            dest=f"{subject}_source_pdf",
            type=Path,
        )

    parser.add_argument(
        "--validation-json",
        "--validation",
        dest="validation_json",
        action="append",
        type=Path,
        help="Validation JSON file or a directory containing validation JSON (repeatable).",
    )
    parser.add_argument(
        "--comparison-material",
        "--comparison",
        dest="comparison_material",
        action="append",
        type=Path,
        help="Comparison file or directory to include (repeatable).",
    )
    parser.add_argument(
        "--obsolete-export",
        action="append",
        type=Path,
        help="Exact obsolete directory to remove; globs are rejected (repeatable).",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Build in staging and publish the complete package, replacing an existing output.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove only explicitly listed obsolete export directories after packaging.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicitly request the default no-change mode.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_console()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.dry_run and (args.replace or args.clean):
        parser.error("--dry-run cannot be combined with --replace or --clean")
    try:
        plan = _build_plan(args)
        _print_plan(plan, replace=args.replace, clean=args.clean)

        if plan.package_requested and args.replace:
            manifest, warnings = _execute_package(plan)
            print(
                f"published: {plan.output_dir} "
                f"({len(manifest['subjects'])} subjects, package_manifest.json written)"
            )
            for warning in warnings:
                print(f"warning: {warning}", file=sys.stderr)

        if plan.obsolete_exports and args.clean:
            for path in plan.obsolete_exports:
                result = _clean_obsolete_export(path, plan.workspace)
                print(f"cleanup {result}: {path}")

        if not args.replace and not args.clean:
            print("dry run complete; no files were changed")
        return 0
    except PackagingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: filesystem operation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
