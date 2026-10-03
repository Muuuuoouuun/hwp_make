"""Pin the 2026-10-03 validator false-positive fixes (audit GAP2-01/02/03).

Three validators rejected real exam PDFs with 422 although the writer output was
correct:

1. ``pdf_source_semantics._source_fraction_lines`` dropped the tail glyphs of a
   fraction exponent (``n+1`` -> ``n+``), so ``{4times3^{n+1}} over {...}`` was
   reported missing (math26_6 q23).
2. ``pdf_paragraph_flow.LABEL`` had no circled Latin example markers (ⓐ~ⓩ), so
   separate example sentences were reported as split paragraphs, and printed
   marginal ``[B]`` labels were removed from native text only, so source lines
   containing them were reported missing (kor20).
3. ``pdf_script_attachments`` absorbed equation keywords into the script base
   (``LEQx^{4}`` vs source ``x^{4}``), hiding real misses and inventing others.

Part 1 fixes these with synthetic glyph geometry. Part 2 runs the real samples
named in ``docs/reference_samples_manifest.md`` when they exist locally; without
them it exits 2 (SKIP) after the synthetic part passes.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory(prefix="semantics_false_positives_")
os.environ.setdefault("HWP_MAKE_DATA_DIR", _TMP.name)

import fitz  # noqa: E402

from app import pdf_source_semantics as semantics  # noqa: E402
from app.pdf_paragraph_flow import LABEL, _strip_marginal_labels  # noqa: E402
from app.pdf_script_attachments import (  # noqa: E402
    _script_base,
    inspect_script_attachments,
    source_script_attachments,
)

REAL_SAMPLES = {
    # Audit key -> local private original (docs/reference_samples_manifest.md).
    "math26_6": ROOT / "data" / "uploads" / "26-6월 수학영역_문제지.pdf",
    "kor20": ROOT / "data" / "uploads" / "국어.pdf",
}


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS:", message)


def _glyph_span(text, chars, size):
    """Equation-font span whose per-glyph rectangles mirror a real PDF dump."""
    boxes = [c[1] for c in chars]
    bbox = (
        min(b[0] for b in boxes), min(b[1] for b in boxes),
        max(b[2] for b in boxes), max(b[3] for b in boxes),
    )
    return {
        "text": text, "font": "HyhwpEQ", "size": size, "bbox": bbox,
        "origin": chars[0][2],
        "chars": [{"c": c, "bbox": box, "origin": origin} for c, box, origin in chars],
    }


def fraction_exponent_tail():
    """math26_6 v2:q23 geometry: lim (4*3^{n+1}) / (2^n + 3^n)."""
    rule = _glyph_span("", [("", (136.74, 272.18, 180.06, 303.02), (136.74, 296.88))], 30.84)
    numerator = _glyph_span("4×3", [
        ("4", (138.42, 277.32, 143.94, 288.33), (138.42, 286.14)),
        ("×", (145.2, 277.32, 154.16, 288.33), (145.2, 286.14)),
        ("3", (154.98, 277.32, 160.5, 288.33), (154.98, 286.14)),
    ], 11.01)
    exponent = _glyph_span("n+1", [
        ("n", (161.16, 275.3, 165.62, 282.77), (161.16, 281.28)),
        ("+", (167.64, 274.94, 173.41, 282.41), (167.64, 280.92)),
        ("1", (174.72, 275.3, 178.44, 282.77), (174.72, 281.28)),
    ], 7.47)
    d1 = _glyph_span("2", [("2", (141.78, 293.76, 147.3, 304.77), (141.78, 302.58))], 11.01)
    d1_script = _glyph_span("n", [("n", (147.96, 291.74, 152.42, 299.21), (147.96, 297.72))], 7.47)
    d2 = _glyph_span("+3", [
        ("+", (154.62, 293.22, 163.19, 304.23), (154.62, 302.04)),
        ("3", (164.46, 293.76, 169.98, 304.77), (164.46, 302.58)),
    ], 11.01)
    d2_script = _glyph_span("n", [("n", (170.64, 291.74, 175.1, 299.21), (170.64, 297.72))], 7.47)
    # A same-size glyph on the exponent baseline but far to the right is prose
    # of another expression. The tail rule must stay adjacency-bound.
    stray = _glyph_span("k", [("k", (190.0, 275.3, 194.5, 282.77), (190.0, 281.28))], 7.47)
    lines = [
        {"spans": [rule, d1, d1_script, d2, d2_script]},
        {"spans": [numerator, exponent, stray]},
    ]
    with fitz.open() as document:
        page = document.new_page(width=595, height=842)
        page.draw_line(fitz.Point(136.74, 290.2), fitz.Point(180.06, 290.2), width=0.7)
        found = semantics._source_math(lines, source_page=page)
    expected = semantics._tokens("{4times3^{n+1}} over {2^{n}+3^{n}}")
    check(expected in found,
          "fraction operand keeps the exponent tail glyphs: " + " ".join(expected))
    check(not any("k" in tokens for tokens in found if "over" in tokens),
          "a distant same-size glyph is not absorbed into the fraction exponent")


def example_labels_and_marginal_tags():
    for sample in ("ⓐ우리가들은이야기는", "ⓑ곁에있어도", "ⓩ끝"):
        check(bool(LABEL.match(sample)), f"circled Latin example marker is a label: {sample[:3]}")
    for sample in ("된다니신기해요", "상황이자신들에게", "ⒶX"):
        check(not LABEL.match(sample), f"ordinary prose start is not a label: {sample[:3]}")
    source_first = "수있는부정적인영향을,[B]에서는상대방으로인해변화된"
    native = "수있는부정적인영향을,에서는상대방으로인해변화된상황이자신들에게미치는"
    check(_strip_marginal_labels(source_first) in _strip_marginal_labels(native),
          "marginal [B] label is removed from the source line as well as the native text")
    check(_strip_marginal_labels("x[AB]y") == "x[AB]y",
          "only single-letter marginal tags are removed")


def reserved_keyword_script_bases():
    check(_script_base("LEQx") == "x" and _script_base("sintheta") == "theta",
          "equation keywords are stripped from the script base")
    check(_script_base("log") == "log" and _script_base("lim") == "lim" and _script_base("rho") == "rho",
          "a keyword standing alone or a Greek name remains the base")
    expected = [{"base": "x", "operator": "^", "value": "4"}]
    check(inspect_script_attachments(expected, ["-2 LEQ x^{4} LEQ 2"])["ok"],
          "native LEQ x^{4} satisfies the source x^{4} attachment")
    check(not inspect_script_attachments(expected, ["-2 LEQ x LEQ 2"])["ok"],
          "flattened x4 still fails the attachment audit")
    check(inspect_script_attachments(
        [{"base": "log", "operator": "_", "value": "2"}], ["log_{2} a"])["ok"],
        "log_{2} keeps log as its own base")
    # Source side: the PDF span ends in "≤x" followed by a raised small "4".
    base = {"text": "≤x", "origin": (293.76, 260.94), "size": 11.0,
            "bbox": (293.76, 250.0, 313.0, 263.0)}
    script = {"text": "4", "origin": (313.5, 256.08), "size": 7.5,
              "bbox": (313.5, 249.0, 318.0, 257.5)}
    found = source_script_attachments([{"spans": [base, script]}])
    check([(x["base"], x["operator"], x["value"]) for x in found] == [("x", "^", "4")],
          "source geometry yields the variable x as the attachment base")
    check(inspect_script_attachments(found, ["LEQx^{4}"])["ok"]
          and not inspect_script_attachments(found, ["LEQy^{4}"])["ok"],
          "keyword-glued native base compares by its variable only")


def real_samples():
    from app import pdf_layout_writer, storage
    from app.pdf_editability import inspect_pdf_editability

    available = {key: path for key, path in REAL_SAMPLES.items() if path.exists()}
    if not available:
        print("SKIP: private samples missing:", ", ".join(str(p) for p in REAL_SAMPLES.values()))
        return 2
    storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
    for key, source in available.items():
        # Conversion assets must live under the (isolated) data directory.
        with tempfile.TemporaryDirectory(prefix=f"semantics_{key}_", dir=storage.DATA_DIR) as temporary:
            run_dir = Path(temporary)
            output = run_dir / f"{key}.hwpx"
            with storage.scoped_upload_directory(run_dir / "assets"):
                stats = pdf_layout_writer.write_pdf_structured_hwpx(
                    source, output, native_math=True, variant_policy="all")
            editability = inspect_pdf_editability(
                source, output, stats.get("image_provenance") or [],
                require_question_boxes=bool(stats.get("question_grouping", {}).get("question_count")))
        units = editability["question_units"]
        flow = editability["paragraph_flow"]
        if key == "math26_6":
            check(not units.get("wrong_question_semantics"),
                  "math26_6: no question semantics mismatch (q23 fraction exponent tail)")
            check(editability["ok"], "math26_6: editability gate passes (no 422)")
        if key == "kor20":
            flags = flow["fragmented_paragraphs"] + flow["missing_text"]
            check(not flow["missing_text"],
                  "kor20: marginal [B] lines are no longer reported missing")
            check(not any(record["first"].startswith(("ⓐ", "ⓑ")) for record in flow["fragmented_paragraphs"]),
                  "kor20: separate ⓐ/ⓑ example sentences are not reported as split paragraphs")
            check(len(flags) <= 1,
                  f"kor20: at most the one real split remains (found {len(flags)})")
    return 0


def main():
    fraction_exponent_tail()
    example_labels_and_marginal_tags()
    reserved_keyword_script_bases()
    if "--synthetic-only" in sys.argv:
        return 0
    return real_samples()


if __name__ == "__main__":
    sys.exit(main())
