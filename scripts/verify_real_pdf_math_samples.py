# -*- coding: utf-8 -*-
"""Real PDF math sample regression gate.

This gate covers the user-facing path that matters most for product B:
KICE/CSAT-style math PDF -> editable/native-math HWPX. It is deliberately
separate from the synthetic PDF gate because the real files expose HyhwpEQ PUA,
footers, two-column segmentation, figures, and page-number noise.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("HWP_MAKE_DATA_DIR", str(ROOT / "data" / "real_pdf_math_qa"))
sys.path.insert(0, str(ROOT))

from app import hwpx_writer_v2, importers, pdf_math_geometry, storage  # noqa: E402
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
PLACEHOLDER_CHARS = ("\u25a1", "\u25a2")


def _sample_paths(requested: list[str] | None = None) -> list[Path]:
    upload_dir = ROOT / "data" / "uploads"
    discovered = [upload_dir / name for name in SAMPLE_NAMES if (upload_dir / name).exists()]
    if not requested:
        return discovered

    selected: list[Path] = []
    for value in requested:
        candidate = Path(value)
        if candidate.exists():
            selected.append(candidate)
            continue
        direct = upload_dir / value
        if direct.exists():
            selected.append(direct)
            continue
        matches = [path for path in discovered if value in path.name]
        selected.extend(matches)
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in selected:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def _safe_stem(path: Path, index: int) -> str:
    text = re.sub(r"[^0-9A-Za-z_-]+", "_", path.stem).strip("_").lower()
    return text[:60] or f"sample_{index:02d}"


def _elapsed(start: float) -> float:
    return round(time.perf_counter() - start, 3)


def _count_placeholders(value: Any) -> int:
    text = str(value or "")
    return sum(text.count(char) for char in PLACEHOLDER_CHARS)


def _context(text: str, offset: int, radius: int = 44) -> str:
    start = max(0, offset - radius)
    end = min(len(text), offset + radius + 1)
    return text[start:end].replace("\n", " / ")


def _classify_placeholder_context(context: str) -> str:
    visible = str(context or "")
    # `_context` uses " / " as a human-readable line break marker. Do not
    # treat that marker as a mathematical slash when classifying residuals.
    math_text = re.sub(r"\s+/\s+", " ", visible)
    lowered = math_text.lower()
    if "vec" in lowered or "\u20d7" in math_text or "\u2192" in math_text or "\u2190" in math_text:
        return "vector_or_arrow"
    if "sqrt" in lowered or "\u221a" in math_text:
        return "root"
    if "\\frac" in lowered or " over " in lowered or re.search(r"\S/\S", math_text):
        return "fraction"
    if "lim" in lowered or "\u221e" in math_text:
        return "limit"
    if "{" in math_text or "}" in math_text:
        return "cases_or_grouping"
    if re.search(r"[0-9A-Za-z가-힣]\s*[\u25a1\u25a2]|[\u25a1\u25a2]\s*[0-9A-Za-z가-힣]", math_text):
        return "adjacent_script_or_structure"
    return "unknown"


def _self_check_placeholder_classifier() -> None:
    checks = [
        ("x□ / y", "adjacent_script_or_structure"),
        ("AC⋅□⃗ / \\frac{p}{q}", "vector_or_arrow"),
        ("q√5이고 □p", "root"),
        ("\\frac{1}{2}+□", "fraction"),
        ("{x|0≤x<□ / 3kπ}", "cases_or_grouping"),
    ]
    for context, expected in checks:
        actual = _classify_placeholder_context(context)
        if actual != expected:
            raise AssertionError(
                f"placeholder classifier regression: {context!r} -> {actual!r}, expected {expected!r}"
            )


def _line_has_placeholder(line: dict[str, Any]) -> bool:
    text = str(line.get("text") or "")
    return any(char in text for char in PLACEHOLDER_CHARS)


def _placeholder_glyph_types(pdf_lines: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """Geometry label for every placeholder glyph of one problem, by line index.

    An equation font draws a fraction bar, a radical vinculum, a vector accent,
    an overline, and an empty answer box with the same private-use glyph, so the
    only sound way to name a residual is the geometry of that glyph itself.  The
    rule lives in ``app.pdf_math_geometry`` next to the repairs it mirrors.

    The raw ``pdf_line_chars`` still carry the private-use code point, which is
    why matching them against the normalized square never found anything; the
    glyph view normalizes first, so every bar is seen here.
    """
    grouped: dict[int, list[dict[str, Any]]] = {}
    try:
        glyphs = pdf_math_geometry.line_geometry_glyphs(pdf_lines)
    except Exception:
        return grouped
    for bar in glyphs:
        if bar.text not in PLACEHOLDER_CHARS:
            continue
        grouped.setdefault(bar.line_index, []).append(
            {
                "c": bar.text,
                "bbox": [bar.left, bar.top, bar.right, bar.bottom],
                "font": bar.font,
                "size": bar.size,
                "type": pdf_math_geometry.classify_placeholder_glyph(glyphs, bar),
            }
        )
    return grouped


def _dominant_type(entries: list[dict[str, Any]]) -> str:
    labels = [str(entry.get("type") or "") for entry in entries if entry.get("type")]
    if not labels:
        return ""
    return Counter(labels).most_common(1)[0][0]


def _overlap_score(line_text: str, context: str) -> int:
    """Longest run of the line's own text that also appears in the residual context."""
    stripped = re.sub(rf"[{''.join(PLACEHOLDER_CHARS)}\s]+", "", str(line_text or ""))
    if not stripped or not context:
        return 0
    matcher = difflib.SequenceMatcher(None, stripped, str(context), autojunk=False)
    return matcher.find_longest_match(0, len(stripped), 0, len(context)).size


def _residual_geometry_type(context: str, line_contexts: list[dict[str, Any]]) -> str:
    """Geometry label for one residual square.

    A residual is a bar the repair chain could not resolve, so it is named after
    the unresolved bars of the same problem.  The PDF line whose own text
    overlaps the residual context most wins; when no line stands out, the
    distinct labels of every unresolved bar are reported together instead of
    being guessed apart.
    """
    scored: list[tuple[int, str]] = []
    labels: set[str] = set()
    for line in line_contexts:
        entries = line.get("placeholder_char_bboxes") or []
        dominant = _dominant_type(entries)
        if not dominant:
            continue
        labels.update(str(entry.get("type")) for entry in entries if entry.get("type"))
        scored.append((_overlap_score(str(line.get("text") or ""), context), dominant))
    if not labels:
        return ""
    best = max((score for score, _ in scored), default=0)
    if best >= 2 and sum(1 for score, _ in scored if score == best) == 1:
        return next(label for score, label in scored if score == best)
    ordered = sorted(labels)
    return "+".join(ordered) if len(ordered) <= 3 else "mixed"


def _summarize_pdf_line(
    line: dict[str, Any],
    glyph_types: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    chars = line.get("pdf_line_chars") or []
    spans = line.get("pdf_line_spans") or []
    entries = glyph_types or []
    return {
        "block_id": line.get("block_id"),
        "block_type": line.get("block_type"),
        "text": str(line.get("text") or "")[:240],
        "bbox_px": line.get("bbox_px"),
        "char_count": len(chars),
        "span_count": len(spans),
        "placeholder_char_bboxes": entries[:12],
        "geometry_type": _dominant_type(entries),
        "spans": spans[:8],
    }


def _output_placeholder_reports(item: dict[str, Any], item_index: int) -> list[dict[str, Any]]:
    layout = item.get("layout") or {}
    pdf_lines = [line for line in (layout.get("pdf_lines") or []) if isinstance(line, dict)]
    glyph_types = _placeholder_glyph_types(pdf_lines)
    line_contexts = [
        _summarize_pdf_line(line, glyph_types.get(index))
        for index, line in enumerate(pdf_lines)
        if _line_has_placeholder(line)
    ]
    base = {
        "item_index": item_index,
        "number": item.get("number"),
        "source_page": item.get("source_page"),
        "layout_page": (layout.get("page") or {}).get("number"),
        "column_index": layout.get("column_index"),
        "problem_bbox_px": layout.get("bbox_px"),
    }
    reports: list[dict[str, Any]] = []

    fields: list[tuple[str, int | None, str]] = [("stem", None, str(item.get("stem") or ""))]
    fields.extend(
        ("choice", index, str(choice or ""))
        for index, choice in enumerate(item.get("choices") or [], start=1)
    )
    for field, choice_index, text in fields:
        for match in re.finditer(r"[\u25a1\u25a2]", text):
            context = _context(text, match.start())
            geometry_type = _residual_geometry_type(context, line_contexts)
            report = {
                **base,
                "field": field,
                "choice_index": choice_index,
                "offset": match.start(),
                "char": match.group(0),
                "context": context,
                # Geometry first: the surrounding LaTeX only says what else the
                # line happened to carry, never what this square itself is.
                "inferred_type": geometry_type or _classify_placeholder_context(context),
                "geometry_type": geometry_type,
                "context_type": _classify_placeholder_context(context),
                "pdf_line_contexts": line_contexts[:8],
            }
            reports.append(report)

    return reports


def _source_placeholder_hint_reports(item: dict[str, Any], item_index: int) -> list[dict[str, Any]]:
    layout = item.get("layout") or {}
    pdf_lines = [line for line in (layout.get("pdf_lines") or []) if isinstance(line, dict)]
    glyph_types = _placeholder_glyph_types(pdf_lines)
    base = {
        "item_index": item_index,
        "number": item.get("number"),
        "source_page": item.get("source_page"),
        "layout_page": (layout.get("page") or {}).get("number"),
        "column_index": layout.get("column_index"),
        "problem_bbox_px": layout.get("bbox_px"),
    }
    reports: list[dict[str, Any]] = []
    summaries = [
        _summarize_pdf_line(line, glyph_types.get(index))
        for index, line in enumerate(pdf_lines)
        if _line_has_placeholder(line)
    ]
    for line in summaries:
        context = str(line.get("text") or "")
        geometry_type = str(line.get("geometry_type") or "")
        reports.append(
            {
                **base,
                "field": "source_pdf_line",
                "choice_index": None,
                "offset": None,
                "char": None,
                "context": line.get("text"),
                "inferred_type": geometry_type or _classify_placeholder_context(context),
                "geometry_type": geometry_type,
                "context_type": _classify_placeholder_context(context),
                "pdf_line_contexts": [line],
                "hint_only": True,
            }
        )
    return reports


def _question_inventory(items: list[dict[str, Any]]) -> dict[str, Any]:
    numbers: list[int] = []
    malformed: list[str] = []
    for item in items:
        value = str(item.get("number") or "").strip()
        if not value:
            malformed.append(value)
            continue
        try:
            numbers.append(int(value))
        except ValueError:
            malformed.append(value)
    counts = Counter(numbers)
    duplicates = sorted(number for number, count in counts.items() if count > 1)
    sequential_46 = list(range(1, 47))
    kice_math_display_46 = list(range(1, 31)) + list(range(23, 31)) + list(range(23, 31))
    if numbers == sequential_46:
        sync_model = "sequential_1_to_46"
    elif numbers == kice_math_display_46:
        sync_model = "kice_math_common_plus_three_electives"
    else:
        sync_model = "unknown"
    expected = set(range(1, 47)) if sync_model == "sequential_1_to_46" else set(range(1, 31))
    actual = set(numbers)
    return {
        "numbers": numbers,
        "count": len(numbers),
        "unique_count": len(actual),
        "expected_display_number_set": sorted(expected),
        "missing_display_numbers": sorted(expected - actual),
        "extra_display_numbers": sorted(actual - expected),
        "duplicates": duplicates,
        "malformed": malformed,
        "sync_model": sync_model,
        "accepted_46_sync": len(items) == 46 and sync_model != "unknown" and not malformed,
        "strict_46_sync": numbers == sequential_46,
    }


def _render_enabled(mode: str) -> bool:
    return mode in {"render", "all"}


def _write_enabled(mode: str) -> bool:
    return mode in {"write", "render", "all"}


def _run_one(
    path: Path,
    index: int,
    *,
    mode: str,
    save_pages: int,
    render_timeout_sec: int,
) -> dict[str, Any]:
    total_start = time.perf_counter()
    timings: dict[str, float] = {}

    setup_start = time.perf_counter()
    storage.DB_PATH = storage.DATA_DIR / f"real_pdf_math_{os.getpid()}_{index:02d}.sqlite3"
    storage.DB_PATH.unlink(missing_ok=True)
    storage.init_db()
    timings["setup"] = _elapsed(setup_start)

    import_start = time.perf_counter()
    result = importers.import_pdf(path.name, path.read_bytes(), {})
    timings["import"] = _elapsed(import_start)

    analysis_start = time.perf_counter()
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
    unknown_square_count = sum(_count_placeholders(item.get("stem")) for item in items)
    choice_unknown_square_count = sum(
        _count_placeholders(choice)
        for item in items
        for choice in (item.get("choices") or [])
    )
    placeholder_reports = [
        report
        for item_index, item in enumerate(items, start=1)
        for report in _output_placeholder_reports(item, item_index)
    ]
    source_placeholder_hint_reports = [
        report
        for item_index, item in enumerate(items, start=1)
        for report in _source_placeholder_hint_reports(item, item_index)
    ]
    placeholder_type_counts = Counter(str(report.get("inferred_type") or "unknown") for report in placeholder_reports)
    source_placeholder_hint_type_counts = Counter(
        str(report.get("inferred_type") or "unknown") for report in source_placeholder_hint_reports
    )
    inventory = _question_inventory(items)
    timings["analysis"] = _elapsed(analysis_start)

    out_path: Path | None = None
    inspect: dict[str, Any] = {"skipped": True}
    render: dict[str, Any] = {"skipped": True}

    if _write_enabled(mode):
        out_path = OUT_DIR / f"{index:02d}_{_safe_stem(path, index)}_native_math.hwpx"
        write_start = time.perf_counter()
        hwpx_writer_v2.write_hwpx(
            out_path,
            result.get("exam_title") or f"{path.stem} real PDF math QA",
            items,
            template_key="kice_math",
            native_math=True,
        )
        timings["write_hwpx"] = _elapsed(write_start)

        inspect_start = time.perf_counter()
        inspect = qa._inspect_hwpx(out_path)
        timings["inspect_hwpx"] = _elapsed(inspect_start)

    if out_path is not None and _render_enabled(mode):
        render_start = time.perf_counter()
        render = qa._render_hwpx(
            out_path,
            OUT_DIR / "renders",
            save_pages,
            timeout_sec=render_timeout_sec,
        )
        timings["render_hwpx"] = _elapsed(render_start)

    failures: list[str] = []
    if not (40 <= len(items) <= 55):
        failures.append(f"unexpected imported problem count: {len(items)}")
    if textful < 30:
        failures.append(f"too few editable-text problems: {textful}")
    if sum(count for choices, count in choice_dist.items() if int(choices) == 5) < 30:
        failures.append(f"too few five-choice problems: {dict(choice_dist)}")
    if footer_hits:
        failures.append(f"footer/copyright text leaked into stems: {footer_hits[:8]}")
    if not inventory["accepted_46_sync"]:
        failures.append(f"question inventory does not match an accepted 46-item math pattern: {inventory}")
    if _write_enabled(mode):
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
    if _render_enabled(mode):
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

    timings["total"] = _elapsed(total_start)
    return {
        "source": str(path),
        "mode": mode,
        "output": str(out_path) if out_path is not None else "",
        "created": len(items),
        "textful": textful,
        "choice_dist": dict(sorted(choice_dist.items())),
        "question_inventory": inventory,
        "image_count": image_count,
        "unknown_square_count": unknown_square_count,
        "choice_unknown_square_count": choice_unknown_square_count,
        "total_unknown_square_count": unknown_square_count + choice_unknown_square_count,
        "placeholder_report_count": len(placeholder_reports),
        "placeholder_type_counts": dict(sorted(placeholder_type_counts.items())),
        "placeholder_reports": placeholder_reports[:120],
        "source_placeholder_hint_count": len(source_placeholder_hint_reports),
        "source_placeholder_hint_type_counts": dict(sorted(source_placeholder_hint_type_counts.items())),
        "source_placeholder_hint_reports": source_placeholder_hint_reports[:120],
        "footer_hit_count": len(footer_hits),
        "phase_timings_sec": timings,
        "inspect": {
            "skipped": inspect.get("skipped", False),
            "equations": inspect.get("equations"),
            "malformed_equation_script_count": inspect.get("malformed_equation_script_count"),
            "equation_object_issue_count": inspect.get("equation_object_issue_count"),
            "content_tables": inspect.get("content_tables"),
            "choice_grid_tables": inspect.get("choice_grid_tables"),
            "pictures": inspect.get("pictures"),
        },
        "render": {
            "skipped": render.get("skipped", False),
            "available": render.get("available"),
            "page_count": render.get("page_count"),
            "overflow_count": render.get("overflow_count"),
            "column_crossing_issues": render.get("column_crossing_issues") or [],
            "log_tail": render.get("log_tail") or [],
        },
        "notices": result.get("notices") or [],
        "review_flags": review_flags,
        "failures": failures,
    }


def _report_path_for_mode(mode: str) -> Path:
    if mode == "all":
        return REPORT_PATH
    return OUT_DIR / f"real_pdf_math_qa_report_{mode}.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Real PDF math sample QA")
    parser.add_argument(
        "--mode",
        choices=("import", "write", "render", "all"),
        default="all",
        help=(
            "import=PDF import only, write=import+HWPX+XML inspect, "
            "render=import+write+render, all=same as render"
        ),
    )
    parser.add_argument("--sample", action="append", help="Sample filename, path, or substring. Repeatable.")
    parser.add_argument("--limit", type=int, default=0, help="Limit sample count after filtering.")
    parser.add_argument("--save-pages", type=int, default=0, help="PNG pages to save during render; -1 saves all.")
    parser.add_argument("--render-timeout-sec", type=int, default=240, help="Per-sample rhwp render timeout.")
    args = parser.parse_args()

    _self_check_placeholder_classifier()

    paths = _sample_paths(args.sample)
    if args.limit > 0:
        paths = paths[: args.limit]
    if not paths:
        print("No real math PDF samples found in data/uploads; skipping.")
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    reports = [
        _run_one(
            path,
            index,
            mode=args.mode,
            save_pages=args.save_pages,
            render_timeout_sec=args.render_timeout_sec,
        )
        for index, path in enumerate(paths, start=1)
    ]
    report_path = _report_path_for_mode(args.mode)
    report_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")

    square = "\u25a1"
    print(
        f"{'sample':<44} {'problems':>8} {'choices':<14} {'eq':>5} "
        f"{'pages':>5} {'overflow':>8} {('stem' + square):>7} "
        f"{('choice' + square):>9} {'time':>7} status"
    )
    print("-" * 126)
    failed = False
    for report in reports:
        status = "FAIL" if report["failures"] else "OK"
        failed = failed or bool(report["failures"])
        timings = report.get("phase_timings_sec") or {}
        print(
            f"{Path(report['source']).name:<44} {report['created']:>8} "
            f"{str(report['choice_dist']):<14} {str(report['inspect'].get('equations') or '-'):>5} "
            f"{str(report['render'].get('page_count') or '-'):>5} "
            f"{str(report['render'].get('overflow_count') if report['render'].get('overflow_count') is not None else '-'):>8} "
            f"{report.get('unknown_square_count', 0):>7} "
            f"{report.get('choice_unknown_square_count', 0):>9} "
            f"{timings.get('total', 0):>6.1f}s {status}"
        )
        phase_text = ", ".join(f"{name}={value:.2f}s" for name, value in timings.items())
        if phase_text:
            print(f"  phases: {phase_text}")
        for failure in report["failures"]:
            print(f"  - {failure}")
        for flag in report["review_flags"]:
            print(f"  ? {flag}")
        placeholders = report.get("placeholder_reports") or []
        source_hints = report.get("source_placeholder_hint_reports") or []
        if placeholders:
            print(f"  residual placeholder types: {report.get('placeholder_type_counts') or {}}")
        for item in placeholders[:5]:
            print(
                "  placeholder: "
                f"q{item.get('number')} {item.get('field')}"
                f"{'' if item.get('choice_index') is None else '[' + str(item.get('choice_index')) + ']'} "
                f"{item.get('inferred_type')} :: {item.get('context')}"
            )
        if len(placeholders) > 5:
            print(f"  placeholder: ... {len(placeholders) - 5} more in JSON report")
        if source_hints:
            hint_counts = report.get("source_placeholder_hint_type_counts") or {}
            print(
                "  source placeholder hints: "
                f"{report.get('source_placeholder_hint_count', len(source_hints))} "
                f"{hint_counts}"
            )
    print(f"\nReport: {report_path}")
    if failed:
        print("RESULT: FAIL")
        return 1
    print("RESULT: ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
