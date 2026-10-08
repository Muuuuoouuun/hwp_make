"""Source-matched mixed fonts survive as ordinary editable native runs."""
from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lxml import etree
from app.pdf_source_run_styles import HP, restore_source_run_styles
from app.pdf_native_typography import _font_name


def verify_latin_tracking():
    def span(text, start, tracking):
        chars = []
        for char in text:
            width = 3 if char.isspace() else 6
            chars.append({"c": char, "origin": [start, 200],
                          "bbox": [start, 188, start + width, 202]})
            start += width + 12 * tracking / 100
        return {"text": text, "font": "TimesNewRoman", "size": 12,
                "flags": 0, "chars": chars}

    text = "normal compressed ordinary"
    paragraph = etree.Element(HP + "p")
    etree.SubElement(etree.SubElement(paragraph, HP + "run", charPrIDRef="0"), HP + "t").text = text
    layout = {"source_literal_text": True, "source_page_width_pt": 600,
              "source_typography": {"letter_spacing_percent": 0, "lines": [{"spans": [
                  span("normal ", 50, 0), span("compressed", 100, -1.57),
                  span(" ordinary", 180, 0),
              ]}]}}
    styles = {}
    def style(base, height, font, spacing, ratio, bold, *, italic):
        identifier = str(len(styles) + 1)
        styles[identifier] = (height, font, spacing, ratio, bold, italic)
        return identifier
    original = etree.tostring(paragraph)
    assert restore_source_run_styles(paragraph, layout, 60000, style) == 3
    assert "".join(paragraph.itertext()) == text
    actual = [("".join(run.itertext()), styles[run.get("charPrIDRef")])
              for run in paragraph.findall(HP + "run")]
    assert actual == [("normal", (1200, "Times New Roman", 0, 100, False, False)),
                      (" compressed", (1200, "Times New Roman", -2, 100, False, False)),
                      (" ordinary", (1200, "Times New Roman", 0, 100, False, False))], actual
    # Each non-space source character retains exactly its own span's tracking.
    expected_tracking = [(char, tracking) for word, tracking in
                         (("normal", 0), ("compressed", -2), ("ordinary", 0)) for char in word]
    assert [(char, styles[run.get("charPrIDRef")][2])
            for run in paragraph.findall(HP + "run") for char in "".join(run.itertext())
            if not char.isspace()] == expected_tracking
    for reason in ("nonliteral", "insufficient_pairs", "whole_text_mismatch"):
        guarded = deepcopy(layout)
        if reason == "nonliteral":
            guarded["source_literal_text"] = False
        elif reason == "insufficient_pairs":
            guarded["source_typography"]["lines"][0]["spans"][1]["chars"] = guarded[
                "source_typography"]["lines"][0]["spans"][1]["chars"][:4]
        else:
            guarded["source_typography"]["lines"][0]["spans"][1]["text"] = "changed"
        untouched = etree.fromstring(original)
        calls = len(styles)
        assert restore_source_run_styles(untouched, guarded, 60000, style) == 0, reason
        assert etree.tostring(untouched) == original and len(styles) == calls, reason


def main():
    assert _font_name("ABCDEF+ArialBlack") == "Arial Black"
    assert _font_name("Arial Black") == "Arial Black"
    assert _font_name("Blackadder ITC") == "Blackadder ITC"
    paragraph = etree.Element(HP + "p")
    run = etree.SubElement(paragraph, HP + "run", charPrIDRef="0")
    etree.SubElement(run, HP + "t").text = "③ 한글 English word"
    layout = {"source_page_width_pt": 600, "source_typography": {"lines": [{"spans": [
        {"text": "③ 한글 ", "font": "Gulim", "size": 11, "flags": 0},
        {"text": "English", "font": "TimesNewRoman,Italic", "size": 12, "flags": 2},
        {"text": " word", "font": "TimesNewRoman,Bold", "size": 12, "flags": 16},
    ]}]}}
    before = "".join(paragraph.itertext())
    styles = {}
    def style(base, height, font, spacing, ratio, bold, *, italic):
        identifier = str(len(styles) + 1)
        styles[identifier] = (height, font, bold, italic)
        return identifier
    assert restore_source_run_styles(paragraph, layout, 60000, style) == 3
    assert "".join(paragraph.itertext()) == before
    actual = [("".join(r.itertext()), styles[r.get("charPrIDRef")])
              for r in paragraph.findall(HP + "run")]
    assert actual == [("③ 한글", (1100, "Gulim", False, False)),
                      (" English", (1200, "Times New Roman", False, True)),
                      (" word", (1200, "Times New Roman", True, False))], actual
    assert len(paragraph.findall(HP + "run/" + HP + "t")) == 3
    mismatch = deepcopy(layout)
    mismatch["source_typography"]["lines"][0]["spans"][1]["text"] = "Changed"
    untouched = etree.tostring(paragraph)
    assert restore_source_run_styles(paragraph, mismatch, 60000, style) == 0
    assert etree.tostring(paragraph) == untouched
    equation = deepcopy(paragraph)
    etree.SubElement(equation[0], HP + "equation")
    untouched = etree.tostring(equation)
    assert restore_source_run_styles(equation, layout, 60000, style) == 0
    assert etree.tostring(equation) == untouched
    uniform = deepcopy(layout)
    for span in uniform["source_typography"]["lines"][0]["spans"]:
        span.update(font="Gulim", flags=0)
    # Size-only variation stays with the existing source-family typography.
    untouched = etree.tostring(paragraph)
    assert restore_source_run_styles(paragraph, uniform, 60000, style) == 0
    assert etree.tostring(paragraph) == untouched
    assert _font_name("ABCDEF+TimesNewRoman,Bold") == "Times New Roman"
    verify_latin_tracking()
    print("NATIVE_SOURCE_RUN_STYLES_OK: mixed sizes, italic/bold, exact text, per-span Latin tracking, mismatch/control guards")


if __name__ == "__main__":
    main()
