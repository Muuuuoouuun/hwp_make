"""Old Korean syllables stay intact in source and post-edit line caches."""
# ruff: noqa: E402
from pathlib import Path
import sys
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import hwpx_writer_v2  # noqa: F401 -- initialize the bundled native library
from app.pdf_native_typography import _line_cache, _font_name
from hwpx.tools.question_reflow import cache_lines

H = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def main():
    assert _font_name("ABCDEF+TimesNewRoman") == "Times New Roman"
    assert _font_name("TimesNewRomanPSMT") == "Times New Roman"
    # Three real source-like syllables: arae-a, pansios+i, and modern gak.
    text = "ᄀᆞᆷᅀᅵ각"
    p = etree.Element(H + "p")
    etree.SubElement(etree.SubElement(p, H + "run"), H + "t").text = text
    _line_cache(p, 1050, 1000, 1500, {})
    offsets = [int(line.get("textpos")) for line in p.findall(H + "linesegarray/" + H + "lineseg")]
    assert offsets == [0, 3, 5], offsets
    assert p.find(H + "run/" + H + "t").text == text
    cache_lines(p, 1100, {}, {})
    offsets = [int(line.get("textpos")) for line in p.findall(H + "linesegarray/" + H + "lineseg")]
    assert offsets == [0, 3, 5], offsets
    # Ordinary Hangul syllables and UTF-16 astral offsets remain independent.
    p.find(H + "run/" + H + "t").text = "가😀나"
    _line_cache(p, 1050, 1000, 1500, {})
    assert [int(line.get("textpos")) for line in p.findall(H + "linesegarray/" + H + "lineseg")] == [0, 1, 3]
    print("HANGUL_LAYOUT_UNITS_OK: source and edit caches preserve old Korean syllables and UTF-16 offsets")


if __name__ == "__main__":
    main()
