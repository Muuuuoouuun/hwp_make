"""Optional rhwp command line tool (MIT, https://github.com/edwardkim/rhwp).

The rhwp CLI writes HWP 5.0 from HWPX and turns distribution-only (배포용)
HWP into an editable HWP, without Hancom Office. The Python binding this app
renders with (rhwp-python) does neither, so the CLI is an extra, optional
executable. Filee (MIT) ships the same tool for its HWPX → HWP preset.

The binary is not committed. It is found, in order, at ``HWP_MAKE_RHWP_CLI``,
``packaging/rhwp-cli/rhwp[.exe]`` (``scripts/fetch_rhwp_cli.py`` downloads the
pinned release there) and ``rhwp`` on PATH. Without it, HWP export reports
that it is unavailable and imports behave as before.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_DIR = ROOT / "packaging" / "rhwp-cli"
TIMEOUT_SECONDS = 120
# rhwp convert: exit 3 = re-parsed IR differs, exit 4 = page count differs.
_VERIFY_EXIT_CODES = {3: "ir_mismatch", 4: "page_mismatch"}


class RhwpCliError(RuntimeError):
    """The rhwp CLI is missing or a conversion failed its own checks."""


def locate() -> Path | None:
    configured = os.environ.get("HWP_MAKE_RHWP_CLI", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_file() else None
    executable = "rhwp.exe" if sys.platform == "win32" else "rhwp"
    bundle_roots = [BUNDLED_DIR]
    if getattr(sys, "_MEIPASS", None):
        # PyInstaller desktop build (packaging/basic.spec).
        bundle_roots.insert(0, Path(sys._MEIPASS) / "packaging" / "rhwp-cli")
    for directory in bundle_roots:
        bundled = directory / executable
        if bundled.is_file():
            return bundled
    found = shutil.which("rhwp")
    return Path(found) if found else None


def available() -> bool:
    return locate() is not None


def _run_convert(source: Path, target: Path, *, verify: bool) -> dict[str, Any]:
    exe = locate()
    if exe is None:
        raise RhwpCliError("rhwp 명령줄 도구가 없습니다.")
    arguments = [str(exe), "convert", str(source), str(target), "--json"]
    if verify:
        arguments[4:4] = ["--verify", "--verify-pages"]
    try:
        result = subprocess.run(
            arguments,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RhwpCliError(f"rhwp 실행 실패: {exc}") from exc
    report: dict[str, Any] = {}
    try:
        report = json.loads(result.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    except (ValueError, IndexError):
        report = {}
    if result.returncode in _VERIFY_EXIT_CODES:
        raise RhwpCliError(f"rhwp 변환 검증 실패({_VERIFY_EXIT_CODES[result.returncode]}): {report}")
    if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()[-500:]
        raise RhwpCliError(f"rhwp 변환 실패(exit {result.returncode}): {stderr}")
    return report


def _run_export_hwpx(source: Path, target: Path) -> None:
    exe = locate()
    if exe is None:
        raise RhwpCliError("rhwp 명령줄 도구가 없습니다.")
    try:
        result = subprocess.run(
            [str(exe), "export-hwpx", str(source), str(target)],
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RhwpCliError(f"rhwp 실행 실패: {exc}") from exc
    if result.returncode != 0 or not target.is_file():
        stderr = result.stderr.decode("utf-8", "replace").strip()[-500:]
        raise RhwpCliError(f"HWP 재검사용 HWPX 추출 실패(exit {result.returncode}): {stderr}")


def hwpx_to_hwp(source: Path, target: Path) -> dict[str, Any]:
    """Write HWP 5.0 from HWPX and prove it kept the document.

    1. Rewrite the HWPX spellings rhwp misreads in a temporary copy
       (app/hwp_fidelity.py: fit-to-size picture fills, run-less paragraphs).
    2. ``rhwp convert --verify --verify-pages`` (rhwp IR and page count).
    3. Export the HWP back to HWPX and compare text, tables, merged cells,
       text boxes, pictures, equations, placements, paragraph shapes, line
       layout and fills with the source.

    Raises :class:`RhwpCliError` on any failure or difference and removes the
    HWP, so a lossy HWP is never handed out.
    """
    from . import hwp_fidelity

    source, target = Path(source), Path(target)
    try:
        with tempfile.TemporaryDirectory(prefix="hwp_make_rhwp_check_") as tmp:
            prepared = Path(tmp) / "prepared.hwpx"
            try:
                normalized = hwp_fidelity.normalize_for_hwp(source, prepared)
            except Exception as exc:  # noqa: BLE001 - unreadable HWPX parts
                raise RhwpCliError(f"HWP 변환 준비 실패: {exc}") from exc
            report = _run_convert(prepared, target, verify=True)
            round_trip = Path(tmp) / "round_trip.hwpx"
            _run_export_hwpx(target, round_trip)
            try:
                problems = hwp_fidelity.compare_profiles(
                    hwp_fidelity.structure_profile(source), hwp_fidelity.structure_profile(round_trip)
                )
            except Exception as exc:  # noqa: BLE001 - an unreadable round trip is a failed check
                raise RhwpCliError(f"HWP 왕복 대조 실패: {exc}") from exc
        if problems:
            raise RhwpCliError("HWP 왕복 대조 불일치: " + ", ".join(problems))
    except RhwpCliError:
        target.unlink(missing_ok=True)
        raise
    return {**report, "prepared": normalized, "round_trip_check": "identical"}


def unlock_distribution_hwp(payload: bytes) -> bytes | None:
    """Editable HWP bytes for a distribution-only HWP, or None when unavailable."""
    if not available():
        return None
    with tempfile.TemporaryDirectory(prefix="hwp_make_rhwp_") as tmp:
        source = Path(tmp) / "source.hwp"
        target = Path(tmp) / "editable.hwp"
        source.write_bytes(payload)
        try:
            report = _run_convert(source, target, verify=False)
        except RhwpCliError:
            return None
        if report and report.get("wasDistribution") is False:
            return None
        return target.read_bytes()
