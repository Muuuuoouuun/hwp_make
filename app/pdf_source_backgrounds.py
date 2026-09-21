"""Original embedded decoration behind editable native table text.

This composes PDF image objects only: PDF text is never rendered into the asset.
"""

from copy import deepcopy
import hashlib
import io

import fitz
from lxml import etree
from PIL import Image

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"


def compose_source_background(page, region, numbers):
    region = fitz.Rect(region)
    canvas = Image.new(
        "RGBA",
        (max(1, round(region.width * 2)), max(1, round(region.height * 2))),
        "white",
    )
    seen = set()
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 1 or block.get("number") not in numbers:
            continue
        transform = fitz.Matrix(block["transform"])
        if (
            abs(transform.b) > 0.001
            or abs(transform.c) > 0.001
            or transform.a <= 0
            or transform.d <= 0
        ):
            raise ValueError("unsupported source decoration transform")
        bounds = fitz.Rect(block["bbox"]) & region
        if bounds.is_empty:
            continue
        with Image.open(io.BytesIO(block["image"])) as source:
            image = source.convert("RGBA")
        if block.get("mask"):
            with Image.open(io.BytesIO(block["mask"])) as mask:
                image.putalpha(mask.convert("L"))
        visible = bounds * ~transform
        image = image.crop(
            tuple(
                round(value * (image.width if i % 2 == 0 else image.height))
                for i, value in enumerate(visible)
            )
        )
        target = (
            round((bounds.x0 - region.x0) * 2),
            round((bounds.y0 - region.y0) * 2),
            round((bounds.x1 - region.x0) * 2),
            round((bounds.y1 - region.y0) * 2),
        )
        image = image.resize(
            (max(1, target[2] - target[0]), max(1, target[3] - target[1]))
        )
        canvas.alpha_composite(image, target[:2])
        seen.add(block["number"])
    if seen != set(numbers):
        raise ValueError("source decoration image inventory mismatch")
    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG")
    return out.getvalue()


def apply_native_table_background(
    doc, table, path, *, row=None, column=None, preserve_border=False
):
    """Use a real table fill, or an explicitly requested cell fill.

    A whole-table decoration belongs to the table, not to its text cell. Some
    readers omit cell image fills inside a drawing text box while correctly
    supporting table fills. Neither representation rasterizes the cell text.
    """
    header = doc.headers[0].element
    fills = header.find(f".//{HH}borderFills")
    identifier = str(max(int(fill.get("id", "0")) for fill in fills) + 1)
    target = table.element if row is None else table.cell(row, column).element
    template = next(
        (
            fill
            for fill in fills
            if fill.get("id") == target.get("borderFillIDRef")
        ),
        fills[0],
    )
    fill = deepcopy(template)
    fill.set("id", identifier)
    for child in list(fill):
        if etree.QName(child).localname == "fillBrush":
            fill.remove(child)
        elif (
            etree.QName(child).localname.endswith("Border")
            and table.element.get("rowCnt") == table.element.get("colCnt") == "1"
            and not preserve_border
        ):
            child.set("type", "NONE")
    brush = etree.SubElement(fill, HC + "fillBrush")
    image_brush = etree.SubElement(brush, HC + "imgBrush", mode="TOTAL")
    binary = doc.add_image(path.read_bytes(), "png")
    etree.SubElement(
        image_brush,
        HC + "img",
        binaryItemIDRef=binary,
        bright="0",
        contrast="0",
        effect="REAL_PIC",
        alpha="0",
    )
    fills.append(fill)
    fills.set("itemCnt", str(len(fills)))
    target.set("borderFillIDRef", identifier)
    if row is None and table.element.get("rowCnt") == table.element.get("colCnt") == "1":
        # The original bitmap supplies this frame's outline. Keep its cell
        # transparent so it cannot cover the table fill with a solid rectangle.
        cell_fill = deepcopy(fill)
        cell_id = str(int(identifier) + 1)
        cell_fill.set("id", cell_id)
        cell_fill.remove(cell_fill.find(HC + "fillBrush"))
        fills.append(cell_fill)
        table.cell(0, 0).element.set("borderFillIDRef", cell_id)
        fills.set("itemCnt", str(len(fills)))


def native_background_assets(root, header, hrefs, archive):
    fills = {fill.get("id"): fill for fill in header.iter(HH + "borderFill")}
    result = []
    for container in root.iter():
        if container.tag not in (HP + "tc", HP + "tbl"):
            continue
        fill = fills.get(container.get("borderFillIDRef"))
        if fill is None:
            continue
        brush = fill.find(f".//{HC}imgBrush")
        if brush is None or brush.get("mode") != "TOTAL":
            continue
        image = brush.find(HC + "img")
        if image is not None and (
            image.get("bright", "0") != "0"
            or image.get("contrast", "0") != "0"
            or image.get("effect", "REAL_PIC") != "REAL_PIC"
            or image.get("alpha", "0") != "0"
        ):
            raise ValueError("source decoration visibility was altered")
        href = hrefs.get(image.get("binaryItemIDRef")) if image is not None else None
        if not href or href not in archive.namelist():
            raise ValueError("unresolved native table background asset")
        data = archive.read(href)
        result.append((hashlib.sha256(data).hexdigest(), data))
    return result


def native_background_texts(root, header, hrefs, archive):
    result = {}
    for container in root.iter():
        if container.tag not in (HP + "tc", HP + "tbl"):
            continue
        # Inspect only this owner's fill; a parent's prose must not prove the
        # source of a decoration belonging to a different child cell.
        owner = etree.Element(container.tag, attrib=dict(container.attrib))
        for digest, _ in native_background_assets(owner, header, hrefs, archive):
            parts = []
            for node in container.iter():
                if node.tag == HP + "t":
                    parts.append(node.text or "")
                elif node.tag == HP + "script" and node.getparent().tag == HP + "equation":
                    # A native equation is editable content too. Translate only
                    # exact single-symbol scripts; do not rewrite prose words
                    # or pretend an unparsed complex formula is plain text.
                    script = (node.text or "").strip()
                    parts.append({"times": "×", "div": "÷", "LEQ": "≤",
                                  "GEQ": "≥", "NEQ": "≠"}.get(script, script))
            text = "".join(parts)
            result[digest] = result.get(digest, "") + text
    return result


def prove_background_source_text(page, region, png, native_text):
    """Verify editable prose actually replaces blank pixels in the raw bitmap."""
    import re
    import numpy as np
    from .pdf_layout_writer import _iter_text_lines, _line_text, _pdf_output_text

    def compact(value):
        return re.sub(r"\s+", "", value)

    target = compact(native_text)
    pixels = np.asarray(Image.open(io.BytesIO(png)).convert("L"), dtype=np.int16)
    required = []
    for line in _iter_text_lines(page):
        bounds = fitz.Rect(line["bbox"])
        if not region.contains(bounds):
            continue
        text = compact(_pdf_output_text(_line_text(line)))
        if len(text) < 4:
            continue
        if text not in target:
            return {
                "ok": False,
                "reason": "background_native_text_missing",
                "fragment": text,
            }
        x0, y0 = round((bounds.x0 - region.x0) * 2), round((bounds.y0 - region.y0) * 2)
        x1, y1 = round((bounds.x1 - region.x0) * 2), round((bounds.y1 - region.y0) * 2)
        crop = pixels[max(0, y0) : y1, max(0, x0) : x1]
        if min(crop.shape, default=0) > 1:
            density = max(
                float(np.mean(np.abs(np.diff(crop, axis=0)) > 24)),
                float(np.mean(np.abs(np.diff(crop, axis=1)) > 24)),
            )
            if density >= 0.015:
                return {"ok": False, "reason": "background_contains_prose_ink"}
        required.append(text)
    return {
        "ok": not required or bool(target),
        "source_native_text_chars": sum(map(len, required)),
    }
