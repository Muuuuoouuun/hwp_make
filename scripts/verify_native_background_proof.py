"""Original bitmap decoration is verified without granting rasterized prose."""

from copy import deepcopy
import hashlib
import io
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz
from PIL import Image, ImageDraw
from app.pdf_source_backgrounds import compose_source_background
from app.pdf_source_image_validation import (
    inspect_source_images,
    _uncovered_source_pixels_are_white,
)
from app.pdf_source_characters import source_spans_in_cell


def main():
    bitmap = Image.new("RGB", (400, 200), "white")
    draw = ImageDraw.Draw(bitmap)
    draw.rounded_rectangle((1, 1, 398, 198), radius=20, outline="black", width=3)
    buffer = io.BytesIO()
    bitmap.save(buffer, format="PNG")
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((45, 140), "1. Read the announcement.", fontsize=10)
    region = fitz.Rect(45, 200, 245, 300)
    page.insert_image(region, stream=buffer.getvalue())
    prose = "The announcement remains editable native text."
    page.insert_text((55, 245), prose, fontsize=7)
    number = next(
        b["number"] for b in page.get_text("dict")["blocks"] if b["type"] == 1
    )
    data = compose_source_background(page, region, [number])
    digest = hashlib.sha256(data).hexdigest()
    record = {
        "sha256": digest,
        "role": "source_background_frame",
        "page": 1,
        "bbox_px": [45, 200, 200, 100],
        "page_width_px": 595,
        "page_height_px": 842,
        "source_image_numbers": [number],
    }
    result = inspect_source_images(
        document, {digest: data}, [record], background_texts={digest: prose}
    )
    assert result["ok"], result
    assert not inspect_source_images(
        document, {}, [record], background_texts={digest: prose}
    )["ok"]
    assert not inspect_source_images(
        document, {digest: data}, [record], background_texts={digest: "missing"}
    )["ok"]
    page_pixels = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=region).tobytes("png")
    forged = deepcopy(record)
    forged["sha256"] = hashlib.sha256(page_pixels).hexdigest()
    assert not inspect_source_images(
        document,
        {forged["sha256"]: page_pixels},
        [forged],
        background_texts={forged["sha256"]: prose},
    )["ok"]
    chars = [
        {"c": c, "bbox": (i * 10, 0, i * 10 + 8, 10)} for i, c in enumerate("ABC123")
    ]
    span = {"text": "ABC123", "bbox": (0, 0, 58, 10), "chars": chars}
    assert source_spans_in_cell([span], (0, 0, 30, 11))[0]["text"] == "ABC"
    assert source_spans_in_cell([span], (30, 0, 60, 11))[0]["text"] == "123"
    original = next(b for b in page.get_text("dict")["blocks"] if b["type"] == 1)
    rim = [
        fitz.Rect(45, 200, 65, 300),
        fitz.Rect(225, 200, 245, 300),
        fitz.Rect(45, 200, 245, 220),
        fitz.Rect(45, 280, 245, 300),
    ]
    assert _uncovered_source_pixels_are_white(original, region, rim)
    bitmap.putpixel((200, 100), (254, 254, 254))
    modified = io.BytesIO()
    bitmap.save(modified, format="PNG")
    assert (
        _uncovered_source_pixels_are_white(
            {**original, "image": modified.getvalue()}, region, rim
        )
        is None
    )
    print("NATIVE_BACKGROUND_PROOF_OK (8 checks)")


if __name__ == "__main__":
    main()
