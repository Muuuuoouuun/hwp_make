from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pdf_layout_writer import write_pdf_flow_hwpx
from app.recognition.pipeline import recognize_pdf


SUBJECTS = (
    {"subject": "국어", "filename": "2026-06-고1-국어-문제.pdf", "problems": 45},
    {"subject": "영어", "filename": "2026-06-고1-영어-문제.pdf", "problems": 45},
    {"subject": "수학", "filename": "2026-06-고1-수학-문제.pdf", "problems": 30},
    {"subject": "사회", "filename": "2026-06-고1-통합사회-문제.pdf", "problems": 25},
    {"subject": "과학", "filename": "2026-06-고1-통합과학-문제.pdf", "problems": 25},
    {"subject": "한국사", "filename": "2026-06-고1-한국사-문제.pdf", "problems": 20},
)


def _seconds(values: list[float]) -> dict[str, float]:
    return {
        "median": round(statistics.median(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


def _load_baseline(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("subjects", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("file") or row.get("filename") or ""): row
        for row in rows
        if isinstance(row, dict)
    }


def _baseline_seconds(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if isinstance(value, dict):
        value = value.get("median")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _change_percent(current: float, previous: float | None) -> float | None:
    if previous is None or previous <= 0:
        return None
    return round((current - previous) / previous * 100.0, 1)


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 과목별 PDF 변환시간 벤치마크",
        "",
        f"측정 시각: {report['measured_at']}",
        f"반복 횟수: {report['runs']}",
        "",
        "| 과목 | 쪽 | 문항 | 문항 인식 중앙값 | 원본 레이아웃 HWPX 중앙값 | 기준선 대비 | 품질 게이트 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report["subjects"]:
        recognition = row.get("recognition_s", {}).get("median")
        flow = row.get("flow_hwpx_s", {}).get("median")
        delta = row.get("flow_change_percent")
        lines.append(
            "| {subject} | {pages} | {problems} | {recognition} | {flow} | {delta} | {quality} |".format(
                subject=row["subject"],
                pages=row.get("pages", "-"),
                problems=row.get("problems", "-"),
                recognition=f"{recognition:.3f}초" if recognition is not None else "미측정",
                flow=f"{flow:.3f}초" if flow is not None else "미측정",
                delta=f"{delta:+.1f}%" if delta is not None else "-",
                quality="통과" if row.get("quality_ok") else "실패",
            )
        )
    totals = report["totals"]
    lines.extend(
        [
            "",
            f"- 문항 인식 합계(과목별 중앙값): {totals['recognition_s']:.3f}초",
            f"- 원본 레이아웃 HWPX 합계(과목별 중앙값): {totals['flow_hwpx_s']:.3f}초",
            f"- 문항 수 게이트: {totals['problems']} / {totals['expected_problems']}",
            "",
            "문항 인식은 PDF를 편집 가능한 문항 모델로 나누는 시간이고, 원본 레이아웃 HWPX는 PDF 한 부를 페이지 흐름형 HWPX로 직접 만드는 시간이다.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark six subject PDF conversion paths.")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=ROOT / "data" / "full_subject_qa" / "sources",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data" / "subject_conversion_benchmark" / "current",
    )
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--only", choices=[item["subject"] for item in SUBJECTS])
    parser.add_argument("--skip-recognition", action="store_true")
    parser.add_argument("--skip-flow", action="store_true")
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()

    if args.runs < 1:
        parser.error("--runs must be at least 1")
    selected = [item for item in SUBJECTS if args.only in (None, item["subject"])]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    baseline = _load_baseline(args.baseline)
    rows: list[dict[str, Any]] = []
    failed = False

    for spec in selected:
        pdf_path = args.source_dir / spec["filename"]
        if not pdf_path.is_file():
            print(f"MISSING {pdf_path}", flush=True)
            failed = True
            continue

        pdf_bytes = pdf_path.read_bytes()
        recognition_values: list[float] = []
        flow_values: list[float] = []
        pages = 0
        problems = 0
        flow_stats: dict[str, Any] = {}
        for run_index in range(1, args.runs + 1):
            if not args.skip_recognition:
                started = time.perf_counter()
                recognized = recognize_pdf(pdf_bytes, filename=pdf_path.name)
                recognition_values.append(time.perf_counter() - started)
                pages = recognized.page_count
                problems = len(recognized.problems)

            if not args.skip_flow:
                output_path = args.output_dir / f"{pdf_path.stem}-run{run_index}.hwpx"
                started = time.perf_counter()
                flow_stats = write_pdf_flow_hwpx(pdf_path, output_path)
                flow_values.append(time.perf_counter() - started)
                pages = pages or int(flow_stats.get("pages") or 0)

        quality_ok = args.skip_recognition or problems == spec["problems"]
        failed = failed or not quality_ok
        row: dict[str, Any] = {
            "subject": spec["subject"],
            "file": pdf_path.name,
            "source_bytes": len(pdf_bytes),
            "pages": pages,
            "problems": problems if not args.skip_recognition else None,
            "expected_problems": spec["problems"],
            "quality_ok": quality_ok,
        }
        if recognition_values:
            row["recognition_s"] = _seconds(recognition_values)
        if flow_values:
            row["flow_hwpx_s"] = _seconds(flow_values)
            row["flow_stats"] = flow_stats
            prior = _baseline_seconds(baseline.get(pdf_path.name, {}), "flow_hwpx_s")
            row["flow_change_percent"] = _change_percent(row["flow_hwpx_s"]["median"], prior)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    totals = {
        "recognition_s": round(sum(row.get("recognition_s", {}).get("median", 0.0) for row in rows), 3),
        "flow_hwpx_s": round(sum(row.get("flow_hwpx_s", {}).get("median", 0.0) for row in rows), 3),
        "problems": sum(int(row.get("problems") or 0) for row in rows),
        "expected_problems": sum(int(row["expected_problems"]) for row in rows),
    }
    report = {
        "measured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "runs": args.runs,
        "source_dir": str(args.source_dir.resolve()),
        "subjects": rows,
        "totals": totals,
    }
    (args.output_dir / "results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.output_dir / "results.md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"totals": totals, "output_dir": str(args.output_dir)}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
