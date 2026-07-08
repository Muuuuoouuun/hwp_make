# -*- coding: utf-8 -*-
"""Real PDF math sample regression gate.

This gate covers the user-facing path that matters most for product B:
KICE/CSAT-style math PDF -> editable/native-math HWPX. It is deliberately
separate from the synthetic PDF gate because the real files expose HyhwpEQ PUA,
footers, two-column segmentation, figures, and page-number noise.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("HWP_MAKE_DATA_DIR", str(ROOT / "data" / "real_pdf_math_qa"))
sys.path.insert(0, str(ROOT))

from app import hwpx_writer_v2, importers, storage  # noqa: E402
from scripts import qa_hwp_math_samples as qa  # noqa: E402


SAMPLE_NAMES = (
    "25\uc218\ub2a5 \uc218\ud559.pdf",
    "26-6\uc6d4 \uc218\ud559\uc601\uc5ed_\ubb38\uc81c\uc9c0.pdf",
    "\uc218\ud559 2\uad50\uc2dc.pdf",
    "\uc218\ud559\uc601\uc5ed_\ubb38\uc81c\uc9c0_\ud640\uc218\ud615_2025\ud559\ub144\ub3c4.pdf",
)
OUT_DIR = ROOT / "data" / "real_pdf_math_qa" / "exports"
REPORT_PATH = OUT_DIR / "real_pdf_math_qa_report.json"
FOOTER_RE = re.compile(r"\uc800\uc791\uad8c|\ud55c\uad6d\uad50\uc721\uacfc\uc815\ud3c9\uac00\uc6d0")


def _sample_paths() -> list[Path]:
    upload_dir = ROOT / "data" / "uploads"
    return [upload_dir / name for name in SAMPLE_NAMES if (upload_dir / name).exists()]


def _safe_stem(path: Path, index: int) -> str:
    text = re.sub(r"[^0-9A-Za-z_-]+", "_", path.stem).strip("_").lower()
    return text[:60] or f"sample_{index:02d}"


def _run_one(path: Path, index: int) -> dict[str, Any]:
    storage.DB_PATH = storage.DATA_DIR / f"real_pdf_math_{os.getpid()}_{index:02d}.sqlite3"
    storage.DB_PATH.unlink(missing_ok=True)
    storage.init_db()

    result = importers.import_pdf(path.name, path.read_bytes(), {})
    items = list(result.get("created") or [])
    choice_dist = Counter(len(item.get("choices") or []) for item in items)
    footer_hits = [
        {
            "number": item.get("number"),
            "stem": str(item.get("stem") or "")[:160],
        }
        for item in items
        if FOOTER_RE.search(str(item.get("stem") or ""))
    ]
    textful = sum(1 for item in items if str(item.get("stem") or "").strip())
    image_count = sum(len(item.get("image_paths") or []) for item in items)
    unknown_square_count = sum(str(item.get("stem") or "").count("\u25a1") for item in items)
    choice_unknown_square_count = sum(
        str(choice or "").count("\u25a1")
        for item in items
        for choice in (item.get("choices") or [])
    )
    total_unknown_square_count = unknown_square_count + choice_unknown_square_count

    out_path = OUT_DIR / f"{index:02d}_{_safe_stem(path, index)}_native_math.hwpx"
    hwpx_writer_v2.write_hwpx(
        out_path,
        result.get("exam_title") or f"{path.stem} real PDF math QA",
        items,
        template_key="kice_math",
        native_math=True,
    )
    inspect = qa._inspect_hwpx(out_path)
    render = qa._render_hwpx(out_path, OUT_DIR / "renders", 0)

    failures: list[str] = []
    if not (40 <= len(items) <= 55):
        failures.append(f"unexpected imported problem count: {len(items)}")
    if textful < 30:
        failures.append(f"too few editable-text problems: {textful}")
    if sum(count for choices, count in choice_dist.items() if int(choices) == 5) < 30:
        failures.append(f"too few five-choice problems: {dict(choice_dist)}")
    if footer_hits:
        failures.append(f"footer/copyright text leaked into stems: {footer_hits[:8]}")
    if inspect.get("malformed_equation_script_count"):
        failures.append(
            "malformed native equation scripts: "
            f"{inspect.get('malformed_equation_scripts') or []}"
        )
    if inspect.get("equation_object_issue_count"):
        failures.append(
            "native equation object issues: "
            f"{inspect.get('equation_object_issues') or []}"
        )
    if render.get("error"):
        failures.append(f"rhwp render failed: {render['error']}")
    if render.get("overflow_count"):
        failures.append(f"rhwp layout overflow count: {render['overflow_count']}")
    if render.get("column_crossing_issues"):
        failures.append(f"rendered content crosses column separator: {render['column_crossing_issues'][:8]}")

    review_flags: list[str] = []
    if unknown_square_count:
        review_flags.append(f"unknown square placeholders remain in recovered math text: {unknown_square_count}")
    if choice_unknown_square_count:
        review_flags.append(
            "unknown square placeholders remain in recovered choices: "
            f"{choice_unknown_square_count}"
        )
    if len(items) != 46:
        review_flags.append(f"problem count differs from expected 46-question math paper: {len(items)}")

    return {
        "source": str(path),
        "output": str(out_path),
        "created": len(items),
        "textful": textful,
        "choice_dist": dict(sorted(choice_dist.items())),
        "image_count": image_count,
        "unknown_square_count": unknown_square_count,
        "choice_unknown_square_count": choice_unknown_square_count,
        "total_unknown_square_count": total_unknown_square_count,
        "footer_hit_count": len(footer_hits),
        "inspect": {
            "equations": inspect.get("equations"),
            "malformed_equation_script_count": inspect.get("malformed_equation_script_count"),
            "equation_object_issue_count": inspect.get("equation_object_issue_count"),
            "content_tables": inspect.get("content_tables"),
            "choice_grid_tables": inspect.get("choice_grid_tables"),
            "pictures": inspect.get("pictures"),
        },
        "render": {
            "available": render.get("available"),
            "page_count": render.get("page_count"),
            "overflow_count": render.get("overflow_count"),
            "column_crossing_issues": render.get("column_crossing_issues") or [],
        },
        "notices": result.get("notices") or [],
        "review_flags": review_flags,
        "failures": failures,
    }


def main() -> int:
    paths = _sample_paths()
    if not paths:
        print("No real math PDF samples found in data/uploads; skipping.")
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    reports = [_run_one(path, index) for index, path in enumerate(paths, start=1)]
    REPORT_PATH.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"{'sample':<44} {'problems':>8} {'choices':<14} {'eq':>5} "
        f"{'pages':>5} {'overflow':>8} {'stem□':>6} {'choice□':>8} status"
    )
    print("-" * 114)
    failed = False
    for report in reports:
        status = "FAIL" if report["failures"] else "OK"
        failed = failed or bool(report["failures"])
        print(
            f"{Path(report['source']).name:<44} {report['created']:>8} "
            f"{str(report['choice_dist']):<14} {report['inspect'].get('equations'):>5} "
            f"{str(report['render'].get('page_count')):>5} "
            f"{str(report['render'].get('overflow_count')):>8} "
            f"{report.get('unknown_square_count', 0):>6} "
            f"{report.get('choice_unknown_square_count', 0):>8} {status}"
        )
        for failure in report["failures"]:
            print(f"  - {failure}")
        for flag in report["review_flags"]:
            print(f"  ? {flag}")
    print(f"\nReport: {REPORT_PATH}")
    if failed:
        print("RESULT: FAIL")
        return 1
    print("RESULT: ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
