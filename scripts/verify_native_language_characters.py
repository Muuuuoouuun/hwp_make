"""Source glyph decoding and visible (not merely declared) dot-leader checks."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pdf_source_characters import normalize_source_span
from app.pdf_question_rendering import _visible_svg_text


def main():
    span = {"font": "*¿¾ÇÑ±Û", "text": "\ue7c0\ued7f\ue1a7\ue38b", "chars": []}
    decoded = normalize_source_span(span)
    assert decoded["text"] == "ᄣᅢᅀᅵᄀᆞᄃᆞᆨ"
    assert decoded["source_encoded_text"] == span["text"]
    assert normalize_source_span({**span, "font": "HyhwpEQ"})["text"] == span["text"]
    assert normalize_source_span({**span, "font": "Arial"})["text"] == span["text"]
    assert (
        normalize_source_span(
            {"font": "HaansoftBatang", "text": "\U000f0854제목\U000f0855"}
        )["text"]
        == "《제목》"
    )
    circles = "".join(
        f'<circle cx="{10+i*3}" cy="20" r="1" fill="#000000"/>' for i in range(6)
    )

    def svg(dots, group=""):
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><g {group}>{dots}<text transform="translate(30,24)" font-size="10">①</text></g></svg>'

    assert _visible_svg_text(svg(circles))[0] == "······①"
    assert (
        _visible_svg_text(svg(circles.replace('fill="#000000"', 'fill="#FFFFFF"', 1)))[
            0
        ]
        == "·····①"
    )
    assert _visible_svg_text(svg(circles, 'opacity="0"'))[0] == ""
    assert _visible_svg_text(svg(circles, 'transform="translate(0,100)"'))[0] == ""
    assert _visible_svg_text(svg(circles.replace('cx="16"', 'cx="17"')))[0] == "①"
    assert _visible_svg_text(svg(circles).replace("①", "graph"))[0] == "graph"
    print("NATIVE_LANGUAGE_CHARACTERS_OK (11 checks)")


if __name__ == "__main__":
    main()
