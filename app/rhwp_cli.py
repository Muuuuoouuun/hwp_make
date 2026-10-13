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
    bundled = BUNDLED_DIR / executable
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


def hwpx_to_hwp(source: Path, target: Path) -> dict[str, Any]:
    """Write HWP 5.0 from HWPX; rhwp re-parses the result and compares pages.

    Raises :class:`RhwpCliError` when the tool is missing or its own IR/page
    verification fails, so a lossy HWP is never handed out silently.
    """
    return _run_convert(Path(source), Path(target), verify=True)


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
