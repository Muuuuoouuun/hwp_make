"""Keep conjoining Korean letters together when measuring editable lines.

This implements only the Hangul GB6-GB8 subset of Unicode grapheme boundaries,
not a general grapheme segmenter. https://www.unicode.org/reports/tr29/
Text and UTF-16 offsets remain unchanged.
"""


def _hangul_type(char):
    value = ord(char)
    if 0x1100 <= value <= 0x115F or 0xA960 <= value <= 0xA97C:
        return "L"
    if 0x1160 <= value <= 0x11A7 or 0xD7B0 <= value <= 0xD7C6:
        return "V"
    if 0x11A8 <= value <= 0x11FF or 0xD7CB <= value <= 0xD7FB:
        return "T"
    if 0xAC00 <= value <= 0xD7A3:
        return "LVT" if (value - 0xAC00) % 28 else "LV"
    return ""


def hangul_clusters(text):
    cluster = ""
    previous = ""
    for char in text:
        current = _hangul_type(char)
        joins = (
            previous == "L" and current in {"L", "V", "LV", "LVT"}
            or previous in {"LV", "V"} and current in {"V", "T"}
            or previous in {"LVT", "T"} and current == "T"
        )
        if cluster and not joins:
            yield cluster
            cluster = ""
        cluster += char
        previous = current
    if cluster:
        yield cluster
