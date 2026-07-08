# -*- coding: utf-8 -*-
"""Regression guard for native-math two-column HWPX layout density.

The real HWP sample gate is the source of truth, but it is intentionally slow
and tied to local Downloads files. This synthetic gate keeps the writer's
current contract pinned in every verify run:

* native equations are emitted and visibly render,
* problem labels, source markers, choices, tables, and equations stay in sync,
* two-column output remains compact without rhwp layout overflow or separator
  crossing.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("HWP_MAKE_DATA_DIR", str(ROOT / "data" / "density_regression"))
sys.path.insert(0, str(ROOT))

from app import hwpx_writer_v2, storage  # noqa: E402
from scripts import qa_hwp_math_samples as qa  # noqa: E402


OUT_DIR = ROOT / "data" / "density_regression" / "exports"
OUT_PATH = OUT_DIR / "synthetic_kice_math_density.hwpx"
REPORT_PATH = OUT_DIR / "density_regression_report.json"


STEM_FORMULAS = [
    r"$f(x)=x^{2}+2x+1$",
    r"$a_{n+1}=a_n+2n-1$",
    r"$\sum_{k=1}^{n} k=\frac{n(n+1)}{2}$",
    r"$\int_{0}^{1}(x^{2}+1)\,dx$",
    r"$\lim_{x\to 0}\frac{\sin x}{x}=1$",
    r"$\sin\theta+\cos\theta$",
    r"$\alpha+\beta+\gamma=2\pi$",
    r"$\sqrt{x+1}+\frac{1}{x+2}$",
]

CHOICE_FORMULAS = [
    r"$\frac{1}{2}$",
    r"$\sqrt{2}$",
    r"$2\pi$",
    r"$n+1$",
    r"$x^{2}-1$",
]


def _formula(index: int, offset: int = 0) -> str:
    return STEM_FORMULAS[(index + offset) % len(STEM_FORMULAS)]


def _source_marker(index: int) -> str:
    score = 2 if index <= 15 else 3 if index <= 33 else 4
    return f"[{score}\uC810][synthetic {index:02d}]"


def _problem(index: int) -> dict[str, Any]:
    stem_lines = [
        f"Given {_formula(index)} and {_formula(index, 2)}, find the requested value.",
        f"The condition {_formula(index, 4)} is also satisfied.",
    ]
    if index % 5 == 0:
        stem_lines.append(
            f"Use the relation {_formula(index, 5)} to compare both expressions."
        )
    if index % 11 == 0:
        stem_lines.append(
            r"The graph has tangent slope $f'(1)=3$ and area $S=\int_{0}^{2}f(x)\,dx$."
        )

    tables = []
    if index % 7 == 0:
        tables.append(
            [
                ["x", r"$0$", r"$1$", r"$2$"],
                ["f(x)", _formula(index, 1), _formula(index, 3), _formula(index, 5)],
            ]
        )

    choices = []
    if index <= 33:
        choices = [
            f"{formula} option {choice_index}"
            for choice_index, formula in enumerate(CHOICE_FORMULAS, start=1)
        ]

    return {
        "number": str(index),
        "subject": "synthetic",
        "unit": _source_marker(index),
        "stem": "\n".join(stem_lines),
        "choices": choices,
        "tables": tables,
        "image_paths": [],
    }


def _synthetic_items() -> list[dict[str, Any]]:
    return [_problem(index) for index in range(1, 47)]


def _content_bound_failures(render: dict[str, Any]) -> list[dict[str, Any]]:
    failures = []
    for bound in render.get("content_bounds") or []:
        if not isinstance(bound, dict):
            continue
        bbox_ratio = bound.get("bbox_ratio")
        if not bbox_ratio:
            continue
        left, top, right, bottom = [float(value) for value in bbox_ratio]
        width_ratio = float(bound.get("width_ratio") or 0)
        height_ratio = float(bound.get("height_ratio") or 0)
        if left < 0.035 or top < 0.055 or right > 0.965 or bottom > 0.935:
            failures.append({"reason": "outside safe page bounds", **bound})
        elif width_ratio > 0.86 or height_ratio > 0.88:
            failures.append({"reason": "content bbox is unusually large", **bound})
    return failures


def _run() -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    storage.init_db()
    items = _synthetic_items()

    hwpx_writer_v2.write_hwpx(
        OUT_PATH,
        "Synthetic KICE math density regression",
        items,
        template_key="kice_math",
        native_math=True,
    )

    inspect = qa._inspect_hwpx(OUT_PATH)
    render = qa._render_hwpx(OUT_PATH, OUT_DIR / "renders", 0)
    visibility = qa._equation_render_visibility(OUT_PATH, inspect)
    expected_scripts = qa._expected_math_scripts(items)
    script_mismatch = qa._math_script_mismatch(expected_scripts, inspect["equation_scripts"])
    output_sync = qa._output_sync_summary(items, inspect)
    object_sync = qa._object_sync_summary(items, inspect)
    inventory = qa._problem_inventory_summary(items, inspect)
    text_sync = qa._text_sync_summary(items, inspect)
    layout = qa._layout_metric_summary(render)

    failures: list[str] = []
    if len(items) != 46:
        failures.append(f"expected 46 synthetic problems, got {len(items)}")
    if Counter(len(item.get("choices") or []) for item in items) != Counter({5: 33, 0: 13}):
        failures.append("synthetic fixture no longer matches 33 choice + 13 free-response mix")
    if inspect.get("col_pr_count", 0) < 1:
        failures.append("missing two-column section definition")
    if inspect.get("equations", 0) < 180:
        failures.append(f"too few native equations emitted: {inspect.get('equations')}")
    if script_mismatch:
        failures.append(f"native equation scripts are out of sync: {script_mismatch}")
    if inspect.get("equation_object_issue_count"):
        failures.append(f"native equation object issues: {inspect['equation_object_issues'][:8]}")
    if inspect.get("math_lineseg_issue_count"):
        failures.append(f"equation line segment reservation issues: {inspect['math_lineseg_issues'][:8]}")
    if output_sync.get("problem_label_mismatch"):
        failures.append(f"problem labels out of sync: {output_sync['problem_label_mismatch']}")
    if output_sync.get("source_marker_mismatch"):
        failures.append(f"source markers out of sync: {output_sync['source_marker_mismatch']}")
    if output_sync.get("choice_count_mismatch_count"):
        failures.append(f"choice counts out of sync: {output_sync['choice_count_mismatches']}")
    if object_sync.get("mismatches"):
        failures.append(f"table/object sync mismatch: {object_sync['mismatches']}")
    if inventory.get("mismatch_count"):
        failures.append(f"per-problem inventory mismatch: {inventory['mismatches'][:8]}")
    if text_sync.get("missing_count"):
        failures.append(f"visible text missing from output: {text_sync['mismatches'][:8]}")
    if visibility.get("error"):
        failures.append(f"equation visibility check failed: {visibility['error']}")
    elif not visibility.get("skipped"):
        changed_pixels = int(visibility.get("changed_pixels") or 0)
        changed_ratio = float(visibility.get("changed_ratio") or 0)
        if changed_pixels < 5000 or changed_ratio < 0.001:
            failures.append(
                "native equations do not visibly affect the render: "
                f"changed_pixels={changed_pixels}, changed_ratio={changed_ratio}"
            )
    if render.get("error"):
        failures.append(f"rhwp render failed: {render['error']}")
    if render.get("overflow_count"):
        failures.append(f"rhwp layout overflow count: {render['overflow_count']}")
    if render.get("column_crossing_issues"):
        failures.append(f"content crosses the column separator: {render['column_crossing_issues'][:8]}")
    page_count = int(render.get("page_count") or 0)
    if page_count < 8 or page_count > 18:
        failures.append(f"unexpected synthetic output page count: {page_count}")
    bound_failures = _content_bound_failures(render)
    if bound_failures:
        failures.append(f"rendered content bounds look unsafe: {bound_failures[:8]}")

    return {
        "ok": not failures,
        "output": str(OUT_PATH),
        "problem_count": len(items),
        "choice_distribution": dict(sorted(Counter(len(item.get("choices") or []) for item in items).items())),
        "expected_equations": len(expected_scripts),
        "actual_equations": inspect.get("equations"),
        "equation_visibility": {
            "changed_pixels": visibility.get("changed_pixels"),
            "changed_ratio": visibility.get("changed_ratio"),
            "actual_page_count": visibility.get("actual_page_count"),
            "control_page_count": visibility.get("control_page_count"),
            "error": visibility.get("error"),
        },
        "render": {
            "page_count": render.get("page_count"),
            "overflow_count": render.get("overflow_count"),
            "column_crossing_issues": render.get("column_crossing_issues") or [],
        },
        "layout_summary": layout,
        "output_sync": output_sync,
        "object_sync": object_sync,
        "problem_inventory": {
            "problem_count": inventory.get("problem_count"),
            "output_segment_count": inventory.get("output_segment_count"),
            "expected_equations": inventory.get("expected_equations"),
            "actual_equations": inventory.get("actual_equations"),
            "mismatch_count": inventory.get("mismatch_count"),
            "mismatches": inventory.get("mismatches") or [],
        },
        "text_sync": {
            "problem_count": text_sync.get("problem_count"),
            "output_segment_count": text_sync.get("output_segment_count"),
            "missing_count": text_sync.get("missing_count"),
            "mismatches": text_sync.get("mismatches") or [],
        },
        "failures": failures,
    }


def main() -> int:
    report = _run()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {REPORT_PATH}")
    print(
        "synthetic problems={problem_count} choices={choice_distribution} "
        "equations={actual_equations}/{expected_equations} pages={pages} overflow={overflow}".format(
            problem_count=report["problem_count"],
            choice_distribution=report["choice_distribution"],
            actual_equations=report["actual_equations"],
            expected_equations=report["expected_equations"],
            pages=(report.get("render") or {}).get("page_count"),
            overflow=(report.get("render") or {}).get("overflow_count"),
        )
    )
    if report["failures"]:
        print("RESULT: FAIL")
        for failure in report["failures"]:
            print(f"- {failure}")
        return 1
    print("RESULT: ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
