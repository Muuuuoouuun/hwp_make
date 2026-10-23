"""Source-hashed real exam audit; recognition counts never stand in for fidelity.

Run with an explicit metadata manifest and an isolated output directory. Source
PDFs and generated documents stay in ignored data/tmp folders. This is an audit
command, not an automatic test that silently downloads copyrighted fixtures.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def inventory(numbers, expected):
    counts = Counter(numbers)
    matched = sum(min(counts[number], 1) for number in expected)
    precision = matched / len(numbers) if numbers else 0
    recall = matched / len(expected) if expected else 0
    return {
        "expected": len(expected), "detected": len(numbers), "numbers": numbers,
        "missing": sorted(set(expected) - set(numbers)),
        "unexpected": sorted(set(numbers) - set(expected)),
        "duplicates": sorted(number for number, count in counts.items() if count > 1),
        "ordered": numbers == expected,
        "precision": precision, "recall": recall,
        "f1_score": 200 * precision * recall / (precision + recall) if precision + recall else 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--recognition-only", action="store_true")
    parser.add_argument("--max-pages", type=int, help="Explicit development sample; cannot satisfy full-document acceptance")
    args = parser.parse_args()
    if args.max_pages is not None and not 1 <= args.max_pages <= 200:
        parser.error("--max-pages must be between 1 and 200")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ["HWP_MAKE_DATA_DIR"] = str(output / "runtime")
    from app import main as api
    from app.recognition.pipeline import recognize_pdf

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = {"measured_at": datetime.now(timezone.utc).isoformat(),
              "targets": {"average": 94, "minimum": 92},
              "scope": {"max_pages": args.max_pages, "recognition_only": args.recognition_only,
                        "hancom_gui_verified": False}, "sources": []}

    def persist():
        temporary = output / "report.json.tmp"
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(output / "report.json")

    for source in manifest["sources"]:
        row = {"path": source["path"], "sha256": source["sha256"], "subject": source["subject"]}
        report["sources"].append(row)
        try:
            path = ROOT / source["path"]
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != source["sha256"]:
                raise ValueError("Source hash differs from the declared audit corpus")
            started = time.perf_counter()
            result = recognize_pdf(data, filename=path.name)
            row["recognition_seconds"] = round(time.perf_counter() - started, 3)
            row["recognition"] = inventory([item.number for item in result.problems], source["expected_numbers"])
            row["source_pages"] = result.page_count
            row["unreliable_text_questions"] = sum(not item.text_reliable for item in result.problems)
            persist()
            if not args.recognition_only:
                encoded = base64.b64encode(data).decode("ascii")
                started = time.perf_counter()
                imported = api.import_file(api.ImportPayload(kind="pdf", filename=path.name, data_base64=encoded))
                row["import_seconds"] = round(time.perf_counter() - started, 3)
                items = {item["id"]: item for item in imported.get("created", []) + imported.get("existing", [])}
                row["import_inventory"] = inventory(
                    [int(items[item_id]["number"]) if str(items[item_id]["number"]).isdigit() else 0
                     for item_id in imported.get("ordered_ids", [])], source["expected_numbers"],
                )
                persist()
                started = time.perf_counter()
                converted = api.export_pdf_layout(api.PdfLayoutExportPayload(
                    filename=path.name, data_base64=encoded, math_ai_recognition=False,
                    variant_policy="all", max_pages=args.max_pages,
                ))
                row["conversion_seconds"] = round(time.perf_counter() - started, 3)
                row["output"] = converted["export"]
                row["scope"] = converted["scope"]
                row["quality"] = {key: converted["quality"].get(key) for key in (
                    "objective_score", "objective_score_target", "meets_native_editability_target",
                    "meets_open_safety_target", "visual_review_flags",
                )}
                fidelity = converted["fidelity"]
                row["fidelity"] = {key: fidelity.get(key) for key in (
                    "available", "pdf_page_count", "hwpx_page_count", "pages_compared",
                    "page_count_mismatch", "overall_layout_view_sync_ratio", "overall_sync_ratio",
                    "min_strict_alignment_ratio",
                )}
                row["page_alignment_scores"] = [round(float(page["strict_alignment_ratio"]) * 100, 2)
                                                for page in fidelity.get("pages", [])
                                                if page.get("strict_alignment_ratio") is not None]
                row["open_safety_ok"] = bool(converted.get("open_safety", {}).get("ok"))
        except Exception as exc:
            row["error"] = type(exc).__name__ + ": " + str(exc)
        persist()
        print(json.dumps({key: row.get(key) for key in (
            "path", "recognition_seconds", "import_seconds", "conversion_seconds", "quality", "error",
        )}, ensure_ascii=False), flush=True)

    rows = report["sources"]
    recognition = [row["recognition"]["f1_score"] for row in rows if "recognition" in row]
    alignment = [score for row in rows for score in row.get("page_alignment_scores", [])]
    report["summary"] = {
        "sources": len(rows), "errors": sum("error" in row for row in rows),
        "expected_questions": sum(len(source["expected_numbers"]) for source in manifest["sources"]),
        "recognized_questions": sum(row.get("recognition", {}).get("detected", 0) for row in rows),
        "recognition_average": round(statistics.mean(recognition), 2) if recognition else None,
        "recognition_minimum": round(min(recognition), 2) if recognition else None,
        "exact_inventories": sum(row.get("recognition", {}).get("ordered", False) for row in rows),
        "exact_import_inventories": sum(row.get("import_inventory", {}).get("ordered", False) for row in rows),
        "page_alignment_average": round(statistics.mean(alignment), 2) if alignment else None,
        "page_alignment_minimum": round(min(alignment), 2) if alignment else None,
        "pages_measured": len(alignment),
        "recognition_target_met": len(recognition) == len(rows) and bool(recognition)
                                  and min(recognition) >= 92 and statistics.mean(recognition) >= 94,
        "render_target_met": (not args.recognition_only and args.max_pages is None and bool(alignment)
                              and all(row.get("scope", {}).get("includes_entire_source")
                                      and not row.get("fidelity", {}).get("page_count_mismatch")
                                      and row.get("page_alignment_scores") for row in rows)
                              and min(alignment) >= 92 and statistics.mean(alignment) >= 94),
        # Cross-platform Hancom editing and independent security/operational
        # checks cannot be inferred from recognition or renderer scores.
        "overall_goal_verified": False,
    }
    persist()
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
    return 1 if report["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
