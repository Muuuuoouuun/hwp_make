from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SUBJECTS = {
    "korean": {
        "pages": 20,
        "template": "kice_korean",
        "problems": 56,
        "equations": 0,
        "figures": 8,
        "title": "국어 영역",
        "markers": ["국어 영역"],
    },
    "english": {
        "pages": 8,
        "template": "kice_english",
        "problems": 45,
        "equations": 0,
        "figures": 2,
        "title": "영어 영역",
        "markers": ["영어 영역"],
    },
    "math_a": {
        "pages": 12,
        "template": "kice_math",
        "problems": 30,
        "equations": 224,
        "figures": 5,
        "title": None,
        "markers": ["[13~14]", "0.3413", "0.3944", "0.4332", "0.4599", "확인 사항"],
    },
    "math_b": {
        "pages": 12,
        "template": "kice_math",
        "problems": 30,
        "equations": 263,
        "figures": 7,
        "title": None,
        "markers": ["[11~12]", "0.3413", "0.3849", "0.4192", "0.4452", "확인 사항"],
    },
}
PARALLEL_WALL_SLA_SECONDS = 15.0
WORST_SUBJECT_SECONDS_PER_PAGE_SLA = 0.85
TOTAL_CPU_SECONDS_PER_PAGE_SLA = 0.50


def _bounded_score(actual: float, target: float) -> float:
    if actual <= 0.0:
        return 0.0
    return min(100.0, target / actual * 100.0)


def _hwpx_text(path: Path) -> str:
    chunks: list[str] = []
    with ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.startswith("Contents/section") or not name.endswith(".xml"):
                continue
            root = ElementTree.fromstring(archive.read(name))
            chunks.extend(root.itertext())
    return "".join(chunks)


def _convert_one(
    subject: str,
    source_path: str,
    output_path: str,
    pages: int,
    template: str,
    expected_problems: int,
    expected_equations: int,
    expected_figures: int,
    expected_title: str | None,
    expected_markers: list[str],
) -> dict[str, Any]:
    from app.pdf_layout_writer import write_pdf_structured_hwpx

    started = time.perf_counter()
    stats = write_pdf_structured_hwpx(
        Path(source_path),
        Path(output_path),
        max_pages=pages,
        template_key=template,
        native_math=True,
    )
    elapsed = time.perf_counter() - started
    output = Path(output_path)
    problem_count = int(stats.get("output_problem_count") or 0)
    native_equations = int(stats.get("native_equations") or 0)
    figure_count = int(stats.get("images") or 0)
    hwpx_text = _hwpx_text(output)
    subject_title_present = not expected_title or expected_title in hwpx_text
    marker_presence = {marker: marker in hwpx_text for marker in expected_markers}
    return {
        "subject": subject,
        "source": str(Path(source_path).resolve()),
        "output": str(output.resolve()),
        "elapsed_seconds": round(elapsed, 4),
        "seconds_per_page": round(elapsed / max(1, pages), 4),
        "expected_pages": pages,
        "output_pages": int(stats.get("pages") or 0),
        "expected_problem_count": expected_problems,
        "problem_count": problem_count,
        "expected_native_equations": expected_equations,
        "native_equations": native_equations,
        "expected_figure_count": expected_figures,
        "figure_count": figure_count,
        "expected_subject_title": expected_title,
        "subject_title_present": subject_title_present,
        "required_marker_presence": marker_presence,
        "generation_stats": stats,
        "output_bytes": output.stat().st_size if output.is_file() else 0,
        "ok": output.is_file()
        and output.stat().st_size > 0
        and int(stats.get("pages") or 0) == pages
        and problem_count == expected_problems
        and native_equations == expected_equations
        and figure_count == expected_figures
        and subject_title_present
        and all(marker_presence.values()),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark the four real PDF-to-HWPX conversions in parallel."
    )
    parser.add_argument(
        "package_dir",
        type=Path,
        help="final package containing source_pdf/{korean,english,math_a,math_b}.pdf",
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--generation-report", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--keep-outputs", action="store_true")
    parser.add_argument("--min-score", type=float, default=97.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    package_dir = args.package_dir.resolve()
    if not package_dir.is_dir():
        raise SystemExit(f"package directory not found: {package_dir}")
    source_dir = package_dir / "source_pdf"
    jobs: list[
        tuple[str, Path, Path, int, str, int, int, int, str | None, list[str]]
    ] = []
    temporary_output = args.output_dir is None
    output_dir = (
        Path(tempfile.mkdtemp(prefix="hwp_make_four_subject_benchmark_"))
        if temporary_output
        else args.output_dir.resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        for subject, config in SUBJECTS.items():
            source = source_dir / f"{subject}.pdf"
            if not source.is_file():
                raise SystemExit(f"source PDF not found: {source}")
            jobs.append(
                (
                    subject,
                    source,
                    output_dir / f"{subject}.hwpx",
                    int(config["pages"]),
                    str(config["template"]),
                    int(config["problems"]),
                    int(config["equations"]),
                    int(config["figures"]),
                    str(config["title"]) if config["title"] else None,
                    [str(marker) for marker in config["markers"]],
                )
            )

        started = time.perf_counter()
        results: list[dict[str, Any]] = []
        with ProcessPoolExecutor(max_workers=len(jobs)) as executor:
            futures = {
                executor.submit(
                    _convert_one,
                    subject,
                    str(source),
                    str(output),
                    pages,
                    template,
                    expected_problems,
                    expected_equations,
                    expected_figures,
                    expected_title,
                    expected_markers,
                ): subject
                for (
                    subject,
                    source,
                    output,
                    pages,
                    template,
                    expected_problems,
                    expected_equations,
                    expected_figures,
                    expected_title,
                    expected_markers,
                ) in jobs
            }
            for future in as_completed(futures):
                results.append(future.result())
        parallel_wall = time.perf_counter() - started
        results.sort(key=lambda item: str(item["subject"]))
        total_pages = sum(int(item["expected_pages"]) for item in results)
        total_cpu = sum(float(item["elapsed_seconds"]) for item in results)
        worst_seconds_per_page = max(
            (float(item["seconds_per_page"]) for item in results),
            default=float("inf"),
        )
        component_scores = {
            "parallel_wall_time": round(
                _bounded_score(parallel_wall, PARALLEL_WALL_SLA_SECONDS), 2
            ),
            "worst_subject_throughput": round(
                _bounded_score(
                    worst_seconds_per_page,
                    WORST_SUBJECT_SECONDS_PER_PAGE_SLA,
                ),
                2,
            ),
            "aggregate_cpu_throughput": round(
                _bounded_score(
                    total_cpu / max(1, total_pages),
                    TOTAL_CPU_SECONDS_PER_PAGE_SLA,
                ),
                2,
            ),
        }
        score = round(
            component_scores["parallel_wall_time"] * 0.50
            + component_scores["worst_subject_throughput"] * 0.30
            + component_scores["aggregate_cpu_throughput"] * 0.20,
            2,
        )
        correctness_ok = all(bool(item["ok"]) for item in results)
        report = {
            "schema_version": 1,
            "theme": "speed",
            "score": score,
            "minimum_score": float(args.min_score),
            "ok": correctness_ok and score >= float(args.min_score),
            "correctness_gate": correctness_ok,
            "measurements": {
                "parallel_wall_seconds": round(parallel_wall, 4),
                "total_cpu_seconds": round(total_cpu, 4),
                "total_pages": total_pages,
                "aggregate_cpu_seconds_per_page": round(
                    total_cpu / max(1, total_pages), 4
                ),
                "worst_subject_seconds_per_page": round(
                    worst_seconds_per_page, 4
                ),
            },
            "sla": {
                "parallel_wall_seconds": PARALLEL_WALL_SLA_SECONDS,
                "worst_subject_seconds_per_page": WORST_SUBJECT_SECONDS_PER_PAGE_SLA,
                "aggregate_cpu_seconds_per_page": TOTAL_CPU_SECONDS_PER_PAGE_SLA,
            },
            "weights": {
                "parallel_wall_time": 0.50,
                "worst_subject_throughput": 0.30,
                "aggregate_cpu_throughput": 0.20,
            },
            "component_scores": component_scores,
            "subjects": results,
        }
        report_path = args.report.resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if args.generation_report is not None:
            generation_report_path = args.generation_report.resolve()
            generation_report_path.parent.mkdir(parents=True, exist_ok=True)
            generation_report = {
                item["subject"]: {
                    "source": item["source"],
                    "output": item["output"],
                    "stats": item["generation_stats"],
                }
                for item in results
            }
            generation_report_path.write_text(
                json.dumps(generation_report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        print(
            json.dumps(
                {
                    "score": score,
                    "ok": report["ok"],
                    **report["measurements"],
                    "report": str(report_path),
                },
                ensure_ascii=False,
            )
        )
        return 0 if report["ok"] else 1
    finally:
        if temporary_output and not args.keep_outputs:
            shutil.rmtree(output_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
