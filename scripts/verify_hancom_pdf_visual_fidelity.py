from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.pdf_layout_fidelity import (  # noqa: E402
    PDF_PDF_DEFAULT_RENDER_DPI,
    PDF_PDF_DUPLICATE_SIMILARITY_THRESHOLD,
    PDF_PDF_MINIMUM_ASSESSMENT_COVERAGE,
    STRICT_ALIGNMENT_REVIEW_THRESHOLD,
    analyze_pdf_pdf_fidelity,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render and compare every page of an original PDF and a PDF actually saved "
            "by Hancom. Writes raw visual metrics, a separate semantic implementation "
            "score, JSON, and per-page comparison images."
        )
    )
    parser.add_argument("source", type=Path, nargs="?", help="original source PDF")
    parser.add_argument("hancom_output", type=Path, nargs="?", help="Hancom-saved PDF")
    parser.add_argument("--source-pdf", type=Path, default=None, help="named source PDF")
    parser.add_argument(
        "--output-pdf", type=Path, default=None, help="named Hancom-saved output PDF"
    )
    parser.add_argument(
        "--output-dir",
        "--artifacts-dir",
        dest="output_dir",
        type=Path,
        default=None,
        help="directory for rendered comparison artifacts",
    )
    parser.add_argument(
        "--report",
        "--json-output",
        "--output",
        dest="report",
        type=Path,
        default=None,
        help="JSON report path (default: <output-dir>/report.json)",
    )
    parser.add_argument(
        "--artifact-mode",
        choices=("all", "comparisons", "failures", "none"),
        default="all",
        help="all saves separate panels too; comparisons saves only combined images",
    )
    parser.add_argument("--dpi", type=int, default=PDF_PDF_DEFAULT_RENDER_DPI)
    parser.add_argument(
        "--source-page-limit",
        type=int,
        default=None,
        help="compare only the first N source pages (for concatenated exam variants)",
    )
    parser.add_argument(
        "--min-raw-visual-ratio",
        type=float,
        default=STRICT_ALIGNMENT_REVIEW_THRESHOLD,
        help="minimum per-page strict alignment ratio",
    )
    parser.add_argument("--min-semantic-score", type=float, default=90.0)
    parser.add_argument(
        "--min-assessment-coverage",
        type=float,
        default=PDF_PDF_MINIMUM_ASSESSMENT_COVERAGE,
    )
    parser.add_argument(
        "--duplicate-threshold",
        type=float,
        default=PDF_PDF_DUPLICATE_SIMILARITY_THRESHOLD,
    )
    parser.add_argument(
        "--analysis-only",
        action="store_true",
        help="write findings but return success even when quality gates fail",
    )
    parser.add_argument(
        "--json-stdout",
        action="store_true",
        help="print the full JSON report after the concise summary",
    )
    return parser


def _resolve_input(
    parser: argparse.ArgumentParser,
    positional: Path | None,
    named: Path | None,
    label: str,
) -> Path:
    if positional is not None and named is not None and positional.resolve() != named.resolve():
        parser.error(f"conflicting positional and named {label} paths")
    path = named or positional
    if path is None:
        parser.error(f"{label} PDF is required")
    if not path.is_file():
        parser.error(f"{label} PDF was not found: {path}")
    return path


def _print_summary(report: dict[str, Any], report_path: Path) -> None:
    if report.get("error"):
        print(f"ERROR: {report['error']}")
        print(f"Report: {report_path.resolve()}")
        return

    raw = report.get("raw_visual_metrics") or {}
    semantic = report.get("semantic_implementation") or {}
    components = semantic.get("components") or {}
    text = components.get("text_preservation") or {}
    problems = components.get("problem_number_preservation") or {}
    duplicates = components.get("duplicate_pages") or {}
    divider = components.get("central_divider") or {}
    status = "PASS" if report.get("meets_target") else "REVIEW"
    print(
        f"Pages: source={report.get('source_page_count')} "
        f"output={report.get('output_page_count')} "
        f"compared={report.get('pages_compared')} (all pages analyzed)"
    )
    print(
        "Raw visual: "
        f"min_strict={float(raw.get('minimum_strict_alignment_ratio') or 0.0):.4f} "
        f"mean_strict={float(raw.get('mean_strict_alignment_ratio') or 0.0):.4f} "
        f"min_foreground={float(raw.get('minimum_foreground_overlap_ratio') or 0.0):.4f}"
    )
    print(
        "Semantic: "
        f"score={float(semantic.get('score') or 0.0):.2f} "
        f"conservative={float(semantic.get('conservative_score_unassessed_as_zero') or 0.0):.2f} "
        f"coverage={float(semantic.get('assessment_coverage_ratio') or 0.0):.4f}"
    )
    print(
        "Checks: "
        f"text={text.get('score')} "
        f"problem_numbers={problems.get('score')} "
        f"unexpected_duplicate_pages={duplicates.get('unexpected_output_duplicate_pages') or []} "
        f"divider_mismatches={divider.get('mismatch_pages') or []}"
    )
    flags = report.get("review_flags") or []
    print(f"Status: {status}{(' - ' + ', '.join(flags)) if flags else ''}")
    print(f"Report: {report_path.resolve()}")
    if report.get("artifact_mode") != "none":
        print(f"Artifacts: {report.get('artifact_dir')}")


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    source_pdf = _resolve_input(parser, args.source, args.source_pdf, "source")
    output_pdf = _resolve_input(
        parser, args.hancom_output, args.output_pdf, "Hancom output"
    )

    output_dir = args.output_dir or (
        ROOT
        / "output"
        / "pdf"
        / "hancom_pdf_visual_fidelity"
        / f"{output_pdf.stem}_vs_{source_pdf.stem}"
    )
    report_path = args.report or (output_dir / "report.json")
    report = analyze_pdf_pdf_fidelity(
        source_pdf,
        output_pdf,
        output_dir,
        render_dpi=args.dpi,
        artifact_mode=args.artifact_mode,
        target_visual_ratio=args.min_raw_visual_ratio,
        target_semantic_score=args.min_semantic_score,
        minimum_assessment_coverage=args.min_assessment_coverage,
        duplicate_similarity_threshold=args.duplicate_threshold,
        source_page_limit=args.source_page_limit,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report["report_path"] = str(report_path.resolve())
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _print_summary(report, report_path)
    if args.json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("error"):
        return 2
    if args.analysis_only:
        return 0
    return 0 if report.get("meets_target") else 1


if __name__ == "__main__":
    raise SystemExit(main())
