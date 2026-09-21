"""A background resource is not proof that its pixels are actually painted."""
import base64
import io
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw
from app.pdf_question_rendering import _bitmap_identity, _visible_svg_images


def main():
    bitmap = Image.new("RGB", (20,20), "white")
    ImageDraw.Draw(bitmap).rectangle((0,0,19,19), outline="black", width=2)
    data = io.BytesIO()
    bitmap.save(data, format="PNG")
    payload = data.getvalue()
    identity = _bitmap_identity(payload)
    uri = "data:image/png;base64," + base64.b64encode(payload).decode()
    picture = f'<image x="10" y="10" width="20" height="20" href="{uri}"/>'
    def svg(content):
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">{content}</svg>'
    assert _visible_svg_images(svg(picture))[identity] == 1
    assert not _visible_svg_images(svg(""))
    assert not _visible_svg_images(svg(f'<defs>{picture}</defs>'))
    assert not _visible_svg_images(svg(f'<g opacity="0">{picture}</g>'))
    assert not _visible_svg_images(svg(f'<g visibility="hidden">{picture}</g>'))
    assert not _visible_svg_images(svg(f'<g transform="translate(200,0)">{picture}</g>'))
    assert not _visible_svg_images(svg(f'<defs><clipPath id="small"><rect width="15" height="15"/></clipPath></defs><g clip-path="url(#small)">{picture}</g>'))
    assert not _visible_svg_images(svg(picture + '<rect x="10" y="10" width="20" height="20" fill="white"/>'))
    assert _visible_svg_images(svg(picture + picture))[identity] == 2
    changed = Image.new("RGB", (20,20), "white")
    other = io.BytesIO()
    changed.save(other, format="PNG")
    forged = picture.replace(base64.b64encode(payload).decode(), base64.b64encode(other.getvalue()).decode())
    assert _visible_svg_images(svg(forged))[identity] == 0
    print("RENDERED_BACKGROUND_VISIBILITY_OK (10 checks)")


if __name__ == "__main__":
    main()
