"""A native prose frame exemption must not hide adjacent decorative image ink."""

import io, sys
from pathlib import Path
from copy import deepcopy
import fitz
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pdf_source_image_validation import _native_tiled_frame_reconstructions


def png(image):
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def fixture(decoration=False, broken=False):
    frame = Image.new("RGB", (480, 240), "white")
    draw = ImageDraw.Draw(frame)
    draw.rectangle((2, 2, 477, 237), outline="black", width=2)
    if decoration:
        draw.ellipse((200, 130, 220, 150), fill="black")
    if broken:
        draw.rectangle((0, 0, 5, 240), fill="white")
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for i in range(3):
        page.insert_image(
            fitz.Rect(45, 175 + i * 40, 285, 215 + i * 40),
            stream=png(frame.crop((0, i * 80, 480, (i + 1) * 80))),
        )
    text = "This whole sentence must remain editable."
    page.insert_text((55, 195), text, fontsize=9)
    images = [b for b in page.get_text("dict")["blocks"] if b.get("type") == 1]
    return doc, page, images, [text.replace(" ", "")]


def main():
    doc, page, images, texts = fixture()
    proof = _native_tiled_frame_reconstructions(page, images, [], texts)
    assert (
        len(proof) == 3
        and len({tuple(p["source_tile_numbers"]) for p in proof.values()}) == 1
    )
    assert not _native_tiled_frame_reconstructions(
        page, images, [], ["A different native paragraph."]
    )
    for kind in ("gap", "wrong_grid"):
        changed = deepcopy(images)
        if kind == "gap":
            changed[1]["bbox"] = tuple(
                v + 1 if i in (1, 3) else v for i, v in enumerate(changed[1]["bbox"])
            )
        else:
            changed[1]["width"] += 1
        assert not _native_tiled_frame_reconstructions(page, changed, [], texts), kind
    doc.close()
    for options in ({"decoration": True}, {"broken": True}):
        doc, page, images, texts = fixture(**options)
        assert not _native_tiled_frame_reconstructions(page, images, [], texts), options
        doc.close()
    print(
        "NATIVE_TILED_FRAME_PROOF_OK: complete three-tile frame accepted; missing native prose, non-touching grid, mismatched pixels, interior decoration and broken border rejected"
    )


if __name__ == "__main__":
    main()
