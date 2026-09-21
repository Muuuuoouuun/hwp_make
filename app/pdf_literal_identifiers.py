"""Check literal PDF identifiers without equation-syntax normalization."""

from collections import Counter
import re

from ._vendor.hwpx_text_content import text_with_controls

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
IDENTIFIER = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?![A-Za-z0-9_])"
)


def source_identifiers(lines):
    """Use source glyphs, including short names, independently of math guessing."""
    from .hancom_pua_map import is_hancom_eq_font

    result = []
    for line in lines:
        # A font run may end in the middle of a name; join ordinary adjacent
        # spans, but never join across a source equation-font span.
        parts = []
        for span in line.get("spans", []):
            parts.append("\0" if is_hancom_eq_font(str(span.get("font", "")))
                         else str(span.get("text", "")))
        result.extend(IDENTIFIER.findall("".join(parts)))
    return result


def inspect_literal_identifiers(expected, roots):
    actual = Counter()
    for root in roots:
        for paragraph in root.iter(HP + "p"):
            parts = []
            for run in paragraph.findall(HP + "run"):
                for child in run:
                    # An equation or nested container cannot satisfy a literal
                    # text requirement, even if its script retains '_'.
                    parts.append(text_with_controls(child) if child.tag == HP + "t" else "\0")
            actual.update(IDENTIFIER.findall("".join(parts)))
    required = Counter(expected)
    missing = required - actual
    return {
        "ok": not missing,
        "source_occurrences": sum(required.values()),
        "source_identifiers": dict(sorted(required.items())),
        "missing_native_identifiers": dict(sorted(missing.items())),
    }
