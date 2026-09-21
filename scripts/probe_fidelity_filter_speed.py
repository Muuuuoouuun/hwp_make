"""Verify the production QA filter against captured pre-optimization scores.

Run with --baseline pointing at a benchmark captured before the filter change.
The retained separable_filter function supports the original isolated experiment.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import pdf_layout_fidelity as fidelity  # noqa: E402

ORIGINAL_FILTER = Image.Image.filter


def separable_filter(image, filter):
    if not isinstance(filter, ImageFilter.MaxFilter) or image.mode != "L":
        return ORIGINAL_FILTER(image, filter)
    values = np.asarray(image)
    radius = filter.size // 2
    height, width = values.shape
    horizontal = np.pad(values, ((0, 0), (radius, radius)), mode="edge")
    result = horizontal[:, :width].copy()
    for offset in range(1, filter.size):
        np.maximum(result, horizontal[:, offset:offset + width], out=result)
    vertical = np.pad(result, ((radius, radius), (0, 0)), mode="edge")
    result = vertical[:height].copy()
    for offset in range(1, filter.size):
        np.maximum(result, vertical[offset:offset + height], out=result)
    return Image.fromarray(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    target = args.output_dir or args.baseline / "filter_experiment"
    target.mkdir(exist_ok=False)
    comparisons = []
    rng = np.random.default_rng(20260909)
    for shape in ((1, 1), (2, 13), (31, 37), (100, 150)):
        for binary in (True, False):
            values = rng.integers(0, 2 if binary else 256, size=shape, dtype=np.uint8)
            if binary:
                values *= 255
            image = Image.fromarray(values)
            for size in (3, 5, 7, 9, 15, 17, 21):
                expected = ORIGINAL_FILTER(image, ImageFilter.MaxFilter(size))
                actual = separable_filter(image, ImageFilter.MaxFilter(size))
                equal = np.array_equal(np.asarray(expected), np.asarray(actual))
                comparisons.append({"shape": shape, "binary": binary, "size": size, "equal": equal})
                assert equal, comparisons[-1]
    report = {"filter_pixel_checks": comparisons, "cases": []}
    for case in ("math", "english", "history"):
        folder = args.baseline / f"{case}_1_web"
        spec = json.loads((folder / "spec.json").read_text(encoding="utf-8"))
        previous = json.loads((folder / "engine_report.json").read_text(encoding="utf-8"))
        hwpx = folder / "output.hwpx"
        previous_pages = previous["fidelity"].get("pages", [])
        started = time.perf_counter()
        result = fidelity.analyze_pdf_hwpx_fidelity(Path(spec["source"]), hwpx, target / case, max_pages=previous["scope"]["selected_page_count"], target_sync_ratio=0.94, artifact_mode="all")
        seconds = time.perf_counter() - started
        differences = []
        for before, after in zip(previous_pages, result.get("pages", [])):
            for key in (before.keys() | after.keys()) - {"source_png_url", "output_png_url", "diff_png_url"}:
                if before.get(key) != after.get(key):
                    differences.append({"page": before["page"], "field": key, "before": before.get(key), "after": after.get(key)})
        if previous_pages and len(previous_pages) != len(result.get("pages", [])):
            differences.append({"error": "compared page counts differ"})
        if previous_pages and previous["fidelity"].get("review_flags") != result.get("review_flags"):
            differences.append({"error": "review flags differ"})
        timings = json.loads((folder / "timings.json").read_text(encoding="utf-8"))
        row = {"case": case, "baseline_fidelity_seconds": timings.get("fidelity"), "production_api_compared_pages": len(previous_pages), "experiment_fidelity_seconds": seconds, "pages": len(result.get("pages", [])), "differences": differences, "review_flags": result.get("review_flags"), "layout_view_sync_ratio": result.get("overall_layout_view_sync_ratio"), "hwpx_page_count": result.get("hwpx_page_count"), "pdf_page_count": result.get("pdf_page_count")}
        report["cases"].append(row)
        (target / f"{case}_fidelity.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(row, ensure_ascii=False), flush=True)
        assert not differences
    (target / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
