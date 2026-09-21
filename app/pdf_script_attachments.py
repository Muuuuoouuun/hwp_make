"""Audit mathematical script attachment against independent PDF glyph geometry.

Literal text conservation cannot distinguish 10^15 from 1015, or R_1 from R^1.
This audit reads the source span baselines without invoking the writer's math
recovery, and requires the corresponding native equation attachment.
"""

from __future__ import annotations

from collections import Counter
import re

LETTERS = r"A-Za-z\u0370-\u03ff"
GREEK = {
    "ρ": "rho",
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "θ": "theta",
    "λ": "lambda",
    "μ": "mu",
    "ν": "nu",
    "π": "pi",
    "σ": "sigma",
    "Δ": "DELTA",
    "Φ": "PHI",
}


def _symbol(value):
    return "".join(GREEK.get(char, char) for char in value)


def source_script_attachments(lines: list[dict]) -> list[dict]:
    from .pdf_layout_writer import _pdf_output_text

    found = []
    for line in lines:
        spans = line.get("spans", [])
        for base, script in zip(spans, spans[1:]):
            base_text = _pdf_output_text(base.get("text", "")).strip()
            value = _pdf_output_text(script.get("text", "")).strip()
            base_text = re.sub(r"\s+", "", base_text).replace("×", "times")
            token = re.search(
                rf"(\d+(?:\.\d+)?times10|[{LETTERS}]+|\d+(?:\.\d+)?|[)\]])$", base_text
            )
            if not token or not re.fullmatch(r"[+−-]?[A-Za-z0-9]+", value):
                continue
            size, small = float(base.get("size", 0)), float(script.get("size", 0))
            if not size or not 0 < small <= size * 0.85:
                continue
            a, b = base.get("bbox"), script.get("bbox")
            if not a or not b:
                continue
            origin_a, origin_b = base.get("origin"), script.get("origin")
            # A PDF span can combine an elevated numerator with a later
            # baseline letter. Only the adjacent base glyph determines the
            # attachment; the span's first glyph is not its baseline.
            base_chars = [
                c for c in base.get("chars", []) if str(c.get("c", "")).strip()
            ]
            script_chars = [
                c for c in script.get("chars", []) if str(c.get("c", "")).strip()
            ]
            if base_chars:
                origin_a = base_chars[-1].get("origin", origin_a)
            if script_chars:
                origin_b = script_chars[0].get("origin", origin_b)
            if not origin_a or not origin_b:
                continue
            delta = float(origin_a[1]) - float(origin_b[1])
            gap = float(b[0]) - float(a[2])
            if not -size * 0.7 <= gap <= size * 0.8:
                continue
            if not size * 0.20 <= abs(delta) <= size * 0.85:
                continue
            found.append(
                {
                    "base": _symbol(token[1]),
                    "operator": "^" if delta > 0 else "_",
                    "value": value.replace("−", "-"),
                    "source_bbox_pt": [
                        float(a[0]),
                        min(a[1], b[1]),
                        max(a[2], b[2]),
                        max(a[3], b[3]),
                    ],
                }
            )
    return found


def inspect_script_attachments(expected: list[dict], native_scripts: list[str]) -> dict:
    required = Counter((x["base"], x["operator"], x["value"]) for x in expected)
    actual = Counter()
    pattern = re.compile(
        r"(\d+(?:\.\d+)?times10|[A-Za-z]+|\d+(?:\.\d+)?|[)\]])([_^])(?:\{([^{}]+)\}|([+-]?\d+|[A-Za-z]))"
    )
    for script in native_scripts:
        styled = re.sub(r"\b(?:rm|it|bold)\s*", "", script)
        compact = _symbol(
            re.sub(r"\s+", "", styled).replace("−", "-").replace("×", "times")
        )
        compact = re.sub(r"\{([A-Za-z]+)\}(?=[_^])", r"\1", compact)
        for match in pattern.finditer(compact):
            actual[(match[1], match[2], match[3] or match[4])] += 1
    missing = [
        {"base": base, "operator": operator, "value": value}
        for base, operator, value in (required - actual).elements()
    ]
    return {
        "ok": not missing,
        "source_attachments": len(expected),
        "missing_native_attachments": missing,
    }
