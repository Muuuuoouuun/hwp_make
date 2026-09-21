"""Measured wraps must address UTF-16 text and reject unrelated source lines."""
from copy import deepcopy
from pathlib import Path
import sys
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pdf_source_line_cache import apply_source_line_cache, HP


def main():
    paragraph = etree.Element(HP + "p")
    etree.SubElement(etree.SubElement(paragraph, HP + "run"), HP + "t").text = "가😀 나 다"
    layout = {"source_page_width_pt": 595.28, "column_left_pt": 40,
              "source_typography": {"font_size_pt": 10, "lines": [
                  {"text": "가😀", "baseline_pt": 100, "bbox_pt": [40, 90, 60, 102]},
                  {"text": "나 다", "baseline_pt": 115, "bbox_pt": [40, 105, 65, 117]},
              ]}}
    assert apply_source_line_cache(paragraph, layout, 20000)
    lines = paragraph.findall(HP + "linesegarray/" + HP + "lineseg")
    assert [line.get("textpos") for line in lines] == ["0", "4"]
    assert [line.get("vertpos") for line in lines] == ["0", "1500"]
    assert "".join(paragraph.itertext()) == "가😀 나 다"
    assert not paragraph.findall(".//" + HP + "lineBreak")
    original = etree.tostring(paragraph)
    for kind in ("text", "position", "oversized", "separate_paragraph"):
        bad = deepcopy(layout)
        source = bad["source_typography"]["lines"]
        if kind == "text":
            source[1]["text"] = "나 마"
        elif kind == "position":
            source[1]["bbox_pt"][0] = -100
        elif kind == "oversized":
            source[1]["bbox_pt"][2] = 400
        else:
            source[1]["baseline_pt"] = 200
        assert not apply_source_line_cache(paragraph, bad, 20000), kind
        assert etree.tostring(paragraph) == original, "a rejected source corrupted the existing paragraph"
    print("NATIVE_SOURCE_LINE_CACHE_OK: UTF-16 offsets; single native paragraph; mismatch, overflow and separate block rejected")


if __name__ == "__main__":
    main()
