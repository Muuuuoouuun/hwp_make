from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pdf_layout_fidelity import analyze_pdf_hwpx_fidelity


DEFAULT_REPORT = ROOT / "data" / "exports" / "final_results_98" / "전체_품질검증_98_report.json"
DEFAULT_OUTPUT = ROOT / "data" / "exports" / "pdf_layout_visual_fidelity_report.json"


def _default_report() -> Path:
    if DEFAULT_REPORT.is_file():
        return DEFAULT_REPORT
    candidates = sorted(
        (ROOT / "data" / "exports" / "final_results_98").glob("*_98_report.json")
    )
    if not candidates:
        raise FileNotFoundError("final subject report was not found")
    return candidates[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-score", type=float, default=96.0)
    parser.add_argument("--min-page-score", type=float, default=90.0)
    parser.add_argument("--save-artifacts", action="store_true")
    args = parser.parse_args()

    # 상세 리포트 패키지는 로컬 전용 산출물 — 없으면 저장소 관례대로 SKIP(exit 2).
    try:
        report_path = args.report or _default_report()
    except FileNotFoundError as exc:
        print(f"SKIP: {exc} (generate data/exports/final_results_98 first)")
        return 2
    source_report = json.loads(report_path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for sample in source_report.get("samples") or []:
        subject = str(sample.get("subject") or "unknown")
        target_pages = int((sample.get("stats") or {}).get("output_page_count_target") or 0)
        fidelity = analyze_pdf_hwpx_fidelity(
            sample["source"],
            sample["output"],
            args.output.parent / "visual_fidelity_artifacts" / subject,
            max_pages=target_pages,
            target_sync_ratio=0.96,
            allow_truncated_by_max_pages=True,
            artifact_mode="all" if args.save_artifacts else "none",
        )
        overall = float(fidelity.get("overall_detailed_layout_score") or 0.0)
        minimum = float(fidelity.get("minimum_detailed_layout_score") or 0.0)
        passed = overall >= args.min_score and minimum >= args.min_page_score
        print(
            f"{subject}: detailed={overall:.2f} min_page={minimum:.2f} "
            f"foreground={float(fidelity.get('min_foreground_overlap_ratio') or 0.0):.4f} "
            f"status={'PASS' if passed else 'FAIL'}"
        )
        if not passed:
            failures.append(
                f"{subject}: detailed {overall:.2f} < {args.min_score:.2f} "
                f"or min page {minimum:.2f} < {args.min_page_score:.2f}"
            )
        results.append({"subject": subject, "passed": passed, "fidelity": fidelity})

    output = {
        "ok": not failures,
        "source_report": str(report_path),
        "min_score": args.min_score,
        "min_page_score": args.min_page_score,
        "results": results,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {args.output}")
    if failures:
        for failure in failures:
            print(f"  - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
