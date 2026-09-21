"""Validate actual picture pixels and source bitmap completeness independently.

Writer provenance selects a source region; its digest is not evidence that the
picture depicts that region. Only pixel-verified regions satisfy the separate
inventory of source embedded images (including images inside native tables).
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import re

import fitz
import numpy as np
from PIL import Image, ImageFilter


def render_source_crop(source: str | Path | bytes, page_index: int, region: fitz.Rect) -> bytes:
    """Render one source clip without inheriting any extraction/decode cache.

    Each crop has its own document. Text/image extraction and prior crops can
    select a different JPEG subsampling level in MuPDF, so even a shared render
    document is not a sufficiently isolated canonical pixel source.
    """
    document = fitz.open(stream=source, filetype="pdf") if isinstance(source, bytes) else fitz.open(source)
    with document:
        return document[page_index].get_pixmap(
            matrix=fitz.Matrix(2, 2), clip=region, alpha=False
        ).tobytes("png")


def compare_source_crop(source_png: bytes, actual: bytes) -> dict:
    """Allow bounded resampling differences, never resize a replacement to fit.

    MuPDF JPEG decode-cache state can change a crop's pixels even for the same
    PDF and 2x matrix. A one-pixel blur removes much of that sampling noise.
    Mean, changed-area and worst-tile limits must all pass, so a mostly-white
    graph cannot hide a different graph behind a good whole-image average.
    These are pixel-fidelity bounds, not a guarantee of graph-label semantics.
    """
    if hashlib.sha256(source_png).digest() == hashlib.sha256(actual).digest():
        return {"ok": True, "exact_bytes": True}
    try:
        with Image.open(io.BytesIO(source_png)) as expected_image, Image.open(io.BytesIO(actual)) as actual_image:
            if expected_image.size != actual_image.size:
                return {"ok": False, "reason": "pixel_dimensions_differ", "expected_size": list(expected_image.size), "actual_size": list(actual_image.size)}
            arrays = []
            for image in (expected_image, actual_image):
                rgba = image.convert("RGBA")
                white = Image.new("RGBA", rgba.size, "white")
                white.alpha_composite(rgba)
                arrays.append(np.asarray(white.convert("RGB").filter(ImageFilter.GaussianBlur(1)), dtype=np.float32))
    except (OSError, ValueError, Image.DecompressionBombError):
        return {"ok": False, "reason": "undecodable_picture"}
    difference = np.abs(arrays[0] - arrays[1]).mean(axis=2)
    tiles = [tile for row in np.array_split(difference, 8, axis=0) for tile in np.array_split(row, 8, axis=1) if tile.size]
    mean = float(difference.mean())
    changed = float((difference > 24).mean())
    worst = max(float(tile.mean()) for tile in tiles)
    return {
        "ok": mean <= 4.0 and changed <= 0.03 and worst <= 12.0,
        "exact_bytes": False,
        "blurred_mean_absolute_error": round(mean, 5),
        "changed_area_ratio_above_24": round(changed, 5),
        "worst_eighth_tile_mean_error": round(worst, 5),
    }


def _union_coverage(bounds: fitz.Rect, regions: list[fitz.Rect]) -> float:
    clipped = [bounds & region for region in regions if bounds.intersects(region)]
    xs = sorted({x for region in clipped for x in (region.x0, region.x1)})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        intervals = sorted((r.y0, r.y1) for r in clipped if r.x0 < right and r.x1 > left)
        bottom = -float("inf")
        for top, end in intervals:
            area += (right-left) * max(0, end-max(top, bottom))
            bottom = max(bottom, end)
    return area / bounds.get_area() if bounds.get_area() > 0 else 0.0


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _uncovered_source_pixels_are_white(image, bounds, verified):
    """Prove omitted bitmap area is exactly blank, at original pixel resolution.

    No coverage/ink threshold is relaxed. A single non-white source pixel in
    the visible, unverified area prevents this proof.
    """
    transform = fitz.Matrix(image["transform"])
    if abs(transform.b) > .001 or abs(transform.c) > .001 or transform.a <= 0 or transform.d <= 0:
        return None
    with Image.open(io.BytesIO(image["image"])) as original:
        rgba = original.convert("RGBA")
    if image.get("mask"):
        with Image.open(io.BytesIO(image["mask"])) as mask:
            rgba.putalpha(mask.convert("L"))
    canvas = Image.new("RGBA", rgba.size, "white")
    canvas.alpha_composite(rgba)
    pixels = np.asarray(canvas.convert("RGB"))
    height, width = pixels.shape[:2]
    def indices(rect, inward=False):
        values = rect * ~transform
        # Classify original pixel centres, so a shared crop boundary neither
        # invents a missing one-pixel seam nor counts pixels from another area.
        return [max(0, min(width if i%2 == 0 else height,
                           int(np.ceil(value * (width if i%2 == 0 else height) - 0.5))))
                for i, value in enumerate(values)]
    x0,y0,x1,y1 = indices(bounds)
    pending = np.zeros((height,width), dtype=bool)
    pending[y0:y1,x0:x1] = True
    for region in verified:
        clip = bounds & region
        if not clip.is_empty:
            x0,y0,x1,y1 = indices(clip, inward=True)
            pending[y0:y1,x0:x1] = False
    count = int(pending.sum())
    if count and not np.any(pixels[pending] != 255):
        return {"reason": "uncovered_original_bitmap_pixels_are_exactly_white", "verified_white_pixels": count}
    return None


def native_bordered_table_texts(roots, header) -> list[str]:
    """Read actual native table text only when every outside edge is visible."""
    hp = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
    hh = "{http://www.hancom.co.kr/hwpml/2011/head}"
    fills = {}
    for fill in header.iter(f"{hh}borderFill"):
        visible = set()
        for side in ("left", "right", "top", "bottom"):
            edge = fill.find(f"{hh}{side}Border")
            if edge is None:
                continue
            color = (edge.get("color") or "").upper().lstrip("#")
            width = re.search(r"[\d.]+", edge.get("width", "0"))
            if edge.get("type", "NONE") != "NONE" and color not in ("", "FFFFFF", "FFFFFFFF") and width and float(width[0]) > 0:
                visible.add(side)
        fills[fill.get("id")] = visible
    result = []
    for root in roots:
        for table in root.iter(f"{hp}tbl"):
            rows, cols = int(table.get("rowCnt", 0)), int(table.get("colCnt", 0))
            edges = {side: [] for side in ("left", "right", "top", "bottom")}
            cells = table.findall(f"{hp}tr/{hp}tc")
            for cell in cells:
                address, span = cell.find(f"{hp}cellAddr"), cell.find(f"{hp}cellSpan")
                if address is None or span is None:
                    continue
                row, col = int(address.get("rowAddr", 0)), int(address.get("colAddr", 0))
                endrow, endcol = row+int(span.get("rowSpan", 1)), col+int(span.get("colSpan", 1))
                for side, on_edge in (("left", col == 0), ("right", endcol == cols), ("top", row == 0), ("bottom", endrow == rows)):
                    if on_edge:
                        edges[side].append(side in fills.get(cell.get("borderFillIDRef"), set()))
            if rows and cols and all(values and all(values) for values in edges.values()):
                result.append(_compact("".join(t.text or "" for t in table.iter(f"{hp}t"))))
    return result


def _native_frame_reconstruction(page, image, bounds, verified, table_texts) -> dict | None:
    """Accept only leftover rectangular frame ink with its prose in a native table.

    Inspect the original bitmap, not the page composite: the native PDF prose
    laid over the bitmap must stay editable instead of being rasterized with it.
    A graph, icon or letter remaining inside the frame prevents this exemption.
    """
    if not table_texts:
        return None
    with Image.open(io.BytesIO(image["image"])) as decoded:
        rgba = decoded.convert("RGBA")
        white = Image.new("RGBA", rgba.size, "white")
        white.alpha_composite(rgba)
        pixels = np.asarray(white.convert("L"))
    ink = pixels < 200
    height, width = ink.shape
    for region in verified:
        clip = bounds & region
        if clip.is_empty:
            continue
        x0, x1 = max(0, int((clip.x0-bounds.x0)*width/bounds.width)), min(width, int(np.ceil((clip.x1-bounds.x0)*width/bounds.width)))
        y0, y1 = max(0, int((clip.y0-bounds.y0)*height/bounds.height)), min(height, int(np.ceil((clip.y1-bounds.y0)*height/bounds.height)))
        ink[y0:y1, x0:x1] = False
    bx = min(width//4, max(1, int(np.ceil(2*width/bounds.width))))
    by = min(height//4, max(1, int(np.ceil(2*height/bounds.height))))
    if ink[by:height-by, bx:width-bx].any():
        return None
    straight_rows = ink.sum(axis=1) >= width*0.8
    straight_cols = ink.sum(axis=0) >= height*0.8
    if (ink & ~straight_rows[:, None] & ~straight_cols[None, :]).any():
        return None
    fragments = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            rectangle = fitz.Rect(line["bbox"])
            if not bounds.contains(rectangle):
                continue
            text = _compact("".join(span.get("text", "") for span in line.get("spans", [])))
            if text:
                fragments.append(text)
    if sum(map(len, fragments)) < 12:
        return None
    if not any(all(fragment in text for fragment in fragments) for text in table_texts):
        return None
    return {"reason": "rectangular_frame_rebuilt_as_native_bordered_table", "source_native_text_chars": sum(map(len, fragments)), "remaining_border_ink_pixels": int(ink.sum())}


def _native_tiled_frame_reconstructions(page, images, verified, table_texts) -> dict:
    """Prove complete vertical bitmap frames, never exempt a tile by proximity.

    Some PDFs encode a single rectangular prose frame as several touching
    strips. A lower strip has no prose of its own. Join only an exact common
    pixel grid and then require all four continuous outside edges plus the
    same native-prose/interior-ink proof used for an individual bitmap.
    """
    if not table_texts:
        return {}
    remaining = sorted(images, key=lambda image: (image["bbox"][0], image["bbox"][1]))
    result = {}
    while remaining:
        first = remaining.pop(0)
        group = [first]
        first_box = fitz.Rect(first["bbox"])
        bottom = first_box.y1
        while True:
            next_tile = next((image for image in remaining
                if abs(image["bbox"][0] - first_box.x0) <= 0.05
                and abs(image["bbox"][2] - first_box.x1) <= 0.05
                and abs(image["bbox"][1] - bottom) <= 0.05
                and image["width"] == first["width"]), None)
            if next_tile is None:
                break
            group.append(next_tile)
            remaining.remove(next_tile)
            bottom = next_tile["bbox"][3]
        if len(group) < 2:
            continue
        bounds = fitz.Rect(first_box.x0, first_box.y0, first_box.x1, bottom)
        if not page.rect.contains(bounds) or bounds.get_area() >= page.rect.get_area() * 0.5:
            continue
        # No scaling: all strips must have the same source pixel pitch.
        sx = first["width"] / first_box.width
        if any(abs(image["height"] / fitz.Rect(image["bbox"]).height - sx) > sx * 0.005
               for image in group):
            continue
        merged = Image.new("RGBA", (first["width"], sum(image["height"] for image in group)), "white")
        cursor = 0
        valid = True
        for image in group:
            with Image.open(io.BytesIO(image["image"])) as decoded:
                if decoded.size != (image["width"], image["height"]):
                    valid = False
                    break
                merged.alpha_composite(decoded.convert("RGBA"), (0, cursor))
            cursor += image["height"]
        if not valid:
            continue
        ink = np.asarray(merged.convert("L")) < 200
        height, width = ink.shape
        band = max(1, int(np.ceil(2 * sx)))
        if not (ink[:band].sum(axis=1).max() >= width * 0.8
                and ink[-band:].sum(axis=1).max() >= width * 0.8
                and ink[:, :band].sum(axis=0).max() >= height * 0.8
                and ink[:, -band:].sum(axis=0).max() >= height * 0.8):
            continue
        stream = io.BytesIO()
        merged.save(stream, format="PNG")
        proof = _native_frame_reconstruction(page, {"image": stream.getvalue()}, bounds,
                                             verified, table_texts)
        if proof:
            proof = dict(proof, reason="continuous_tiled_frame_rebuilt_as_native_bordered_table",
                         source_tile_numbers=[image["number"] for image in group],
                         reconstructed_frame_bbox_pt=list(bounds))
            for image in group:
                result[image["number"]] = proof
    return result


def inspect_source_images(document, assets: dict[str, bytes], provenance: list[dict], *, page_limit: int | None = None, native_table_texts: list[str] | None = None, background_texts: dict[str, str] | None = None) -> dict:
    from .pdf_layout_writer import _page_body_top

    issues = []
    verified_regions: dict[int, list[fitz.Rect]] = {}
    mismatch = []
    pixel_checks = []
    source = document.name if document.name and Path(document.name).is_file() else document.tobytes()
    limit = min(len(document), page_limit or len(document))
    for index, record in enumerate(provenance):
        try:
            page_number = int(record["page"])
            if not 1 <= page_number <= limit or record.get("role") not in {"source_figure", "source_background_frame"}:
                raise ValueError("invalid figure page/role")
            page = document[page_number-1]
            x, y, width, height = map(float, record["bbox_px"])
            sx = page.rect.width / float(record["page_width_px"])
            sy = page.rect.height / float(record["page_height_px"])
            region = fitz.Rect(x*sx, y*sy, (x+width)*sx, (y+height)*sy)
            if region.is_empty or region.is_infinite or not page.rect.contains(region):
                raise ValueError("invalid figure bounds")
            actual = assets.get(record.get("sha256"))
            if actual is None:
                result = {"ok": False, "reason": "declared_asset_missing"}
            else:
                if record.get("role") == "source_background_frame":
                    from .pdf_source_backgrounds import compose_source_background, prove_background_source_text
                    source_png = compose_source_background(page, region, record.get("source_image_numbers", []))
                    result = compare_source_crop(source_png, actual)
                    proof = prove_background_source_text(page, region, source_png, (background_texts or {}).get(record.get("sha256"), ""))
                    if not proof["ok"]:
                        result = proof
                    else:
                        result["native_background_proof"] = proof
                else:
                    source_png = render_source_crop(source, page_number-1, region)
                    result = compare_source_crop(source_png, actual)
            detail = {"index": index, "page": page_number, "bbox_pt": list(region), **result}
            pixel_checks.append(detail)
            if result["ok"]:
                if record.get("role") == "source_background_frame":
                    numbers = set(record.get("source_image_numbers", []))
                    # A bounding union must not accidentally satisfy a separate
                    # foreground figure that was never embedded in this asset.
                    verified_regions.setdefault(page_number, []).extend(
                        fitz.Rect(block["bbox"]) & region
                        for block in page.get_text("dict").get("blocks", [])
                        if block.get("type") == 1 and block.get("number") in numbers
                    )
                else:
                    verified_regions.setdefault(page_number, []).append(region)
            else:
                mismatch.append(detail)
        except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
            mismatch.append({"index": index, "ok": False, "reason": "invalid_source_region"})
    if mismatch:
        issues.append("source_picture_pixels_mismatch")

    inventory, missing = [], []
    for index in range(limit):
        page = document[index]
        body_top = _page_body_top(page)
        # Text extraction reports the visible, PDF-clipped image bounds.
        # get_image_info() instead includes invisible bitmap margins outside
        # clipping paths, which would falsely report cropped-off source ink.
        image_blocks = [image for image in page.get_text("dict").get("blocks", [])
                        if image.get("type") == 1 and image.get("image")]
        tiled_frames = _native_tiled_frame_reconstructions(
            page, image_blocks, verified_regions.get(index+1, []), native_table_texts or [])
        for image in image_blocks:
            if image.get("type") != 1 or not image.get("image"):
                continue
            bounds = fitz.Rect(image["bbox"]) & page.rect
            # Ignore running heads, hairline/rule bitmaps and full-page scans.
            # A native-text export has separate whole-page raster/prose gates.
            if (bounds.y0 < body_top-1 or bounds.width < 12 or bounds.height < 8
                    or bounds.get_area() >= page.rect.get_area()*0.5):
                continue
            coverage = _union_coverage(bounds, verified_regions.get(index+1, []))
            detail = {"page": index+1, "source_image_number": image["number"],
                      "bbox_pt": list(bounds), "pixels": [image["width"], image["height"]],
                      "verified_crop_coverage": round(coverage, 5)}
            inventory.append(detail)
            if coverage < 0.98:
                rebuilt = (_uncovered_source_pixels_are_white(image, bounds, verified_regions.get(index+1, []))
                           or tiled_frames.get(image["number"])
                           or _native_frame_reconstruction(page, image, bounds, verified_regions.get(index+1, []), native_table_texts or []))
                if rebuilt:
                    detail["native_reconstruction"] = rebuilt
                else:
                    missing.append(detail)
    if missing:
        issues.append("source_embedded_picture_missing")
    return {"ok": not issues, "issues": issues, "source_embedded_images": len(inventory),
            "scope": "body embedded bitmaps at least 12x8pt and less than half a page; vector completeness is separate",
            "missing_source_images": missing, "mismatched_source_crops": mismatch,
            "source_crop_checks": pixel_checks, "source_image_inventory": inventory}
