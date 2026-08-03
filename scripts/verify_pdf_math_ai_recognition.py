from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
VENDOR = ROOT / "app" / "_vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from app import storage  # noqa: E402
from app.pdf_math_ai import GEMINI_MATH_MAX_CALLS_ENV, GEMINI_MATH_MOCK_RESPONSE_ENV  # noqa: E402
from app.pdf_layout_writer import write_pdf_layout_hwpx  # noqa: E402
from hwpx.tools.package_validator import validate_editor_open_safety  # noqa: E402
from scripts.verify_pdf_layout_hwpx import verify as verify_hwpx  # noqa: E402


SAMPLE_SUFFIXES = (
    "\uc218\ud559A_\uc9dd\uc218\ud615_\ucd5c\uc885.pdf",
    "\uc218\ud559B_\uc9dd\uc218\ud615_\ucd5c\uc885.pdf",
)


def _find_sample() -> Path | None:
    upload_dir = storage.DATA_DIR / "uploads"
    candidates: list[Path] = []
    for suffix in SAMPLE_SUFFIXES:
        candidates.extend(upload_dir.glob(f"*{suffix}"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def main() -> int:
    sample = _find_sample()
    if sample is None:
        print("SKIP: no local math exam PDF sample under data/uploads")
        return 0

    os.environ[GEMINI_MATH_MAX_CALLS_ENV] = "2"
    os.environ[GEMINI_MATH_MOCK_RESPONSE_ENV] = json.dumps(
        {
            "plain_text": "(x-1)/(2x+k)",
            "latex": r"\frac{x-1}{2x+k}",
            "hancom_eqn": "",
            "confidence": 0.96,
            "reading_order": [
                {"text": "x-1", "role": "numerator"},
                {"text": "2x+k", "role": "denominator"},
            ],
            "notes": "",
        }
    )
    output_dir = storage.EXPORT_DIR / "pdf_layout_ai_mock"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "mock_gemini_math_ai.hwpx"

    stats = write_pdf_layout_hwpx(
        sample,
        output_path,
        max_pages=4,
        include_images=True,
        include_lines=True,
        text_mode="line",
        native_math=False,
        math_ai_recognition=True,
        math_ai_model="gemini-3.5-flash",
    )
    issues = verify_hwpx(output_path, render=False, allow_draw_text_equations=True)
    open_safety = validate_editor_open_safety(output_path)
    failures = []
    if int(stats.get("math_ai_attempts") or 0) <= 0:
        failures.append("expected at least one math AI attempt")
    if int(stats.get("math_ai_accepted") or 0) <= 0:
        failures.append(f"expected accepted math AI equations: {stats!r}")
    if int(stats.get("native_equations") or 0) < int(stats.get("math_ai_accepted") or 0):
        failures.append(f"native equation count below accepted AI count: {stats!r}")
    if int(stats.get("math_visual_overlays") or 0) != 0:
        failures.append(f"image overlays must stay disabled: {stats!r}")
    if not open_safety.ok:
        failures.append(open_safety.summary)
    if issues:
        failures.extend(issues[:8])

    print(
        json.dumps(
            {
                "sample": str(sample),
                "output": str(output_path),
                "stats": stats,
                "open_safety": {"ok": open_safety.ok, "summary": open_safety.summary},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("OK: Gemini math AI mock path inserts native HWPX equations without overlays")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
