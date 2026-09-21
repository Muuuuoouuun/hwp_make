"""Visible circle glyphs count; removed, hidden or unrelated circles do not."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pdf_question_rendering import _visible_svg_text


def main():
    # Radius/baseline captured from real rhwp output for a 10pt middle dot.
    def circle(x, **attrs):
        extra = " ".join(f'{key}="{value}"' for key, value in attrs.items())
        return f'<circle cx="{x}" cy="46.5" r="0.8" fill="black" {extra}/>'

    def text(x, value, y=50):
        return f'<text x="{x}" y="{y}" font-size="10" fill="black">{value}</text>'

    def visible(content):
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">{content}</svg>'
        return _visible_svg_text(svg)[0]

    assert visible(circle(12) + text(18, "Item")) == "·Item"
    dots = "".join(circle(x) for x in (30, 33, 36, 39))
    assert visible(text(24, "끝") + dots + text(45, "㉣")) == "끝····㉣"
    assert visible(text(24, "끝") + dots + text(12, "②", 68)) == "끝····②"
    assert visible(text(24, "끝") + dots) == "끝····"
    assert visible(text(24, "끝") + dots.replace(circle(33), "")) != "끝····"
    for attrs in ({"opacity": "0"}, {"visibility": "hidden"},
                  {"transform": "translate(300,0)"}, {"style": "fill:white"}):
        assert visible(circle(12, **attrs) + text(18, "Item")) == "Item", attrs
    assert visible(circle(12).replace('r="0.8"', 'r="4"') + text(18, "Item")) == "Item"
    assert visible(circle(12).replace('cy="46.5"', 'cy="35"') + text(18, "Item")) == "Item"
    assert visible(circle(12) + text(85, "Item")) == "Item"
    assert visible(f'<defs>{circle(12)}{text(18, "Item")}</defs>') == ""
    print("RENDERED_DOT_GLYPHS_OK: bullets, wrapped leaders, deletion and invisible-paint mutations")


if __name__ == "__main__":
    main()
