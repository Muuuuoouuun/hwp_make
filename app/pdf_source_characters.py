"""Decode source-font-specific historical Korean characters before math parsing.

The KTUG Hanyang PUA table is public-domain factual mapping data, retained with
its attribution in data/hypua2jamocomposed.txt. No bitmap or guessed OCR is used.
"""

from functools import lru_cache
from pathlib import Path
import re
import hashlib
import io

import fitz
from PIL import Image

# A manually transcribed single-character source glyph, not a page/image OCR
# heuristic. The exact grayscale pixels and dimensions must match. Its source
# sample is the national-language paper's historical Korean letter ㆁ.
_BITMAP_CHARACTERS = {
    (80, 101, "0c0759940fafb99cd4e0e3ec911e2e176c037f8427a6d14c234140b6d2577074"): "ㆁ",
}


@lru_cache(maxsize=1)
def _old_hangul_map():
    table = {}
    path = Path(__file__).with_name("data") / "hypua2jamocomposed.txt"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("U+") and "=>" in line:
            codes = re.findall(r"U\+([0-9A-F]+)", line)
            table[chr(int(codes[0], 16))] = "".join(chr(int(v, 16)) for v in codes[1:])
    return table


def _source_font_name(font):
    name = str(font)
    try:
        name = name.encode("latin1").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return name


def normalize_source_span(span):
    """Use the PDF's own font designation to disambiguate overlapping PUA maps."""
    name = _source_font_name(span.get("font", ""))
    mapping = _old_hangul_map() if "옛한글" in name else {}
    if "Haansoft" in name or "함초롬" in name:
        mapping = {**mapping, "\U000f0854": "《", "\U000f0855": "》"}
    if not mapping:
        return span
    text = str(span.get("text", ""))
    converted = "".join(mapping.get(c, c) for c in text)
    if converted == text:
        return span
    result = dict(span)
    result["source_encoded_text"] = text
    result["text"] = converted
    result["chars"] = [
        {**char, "c": "".join(mapping.get(c, c) for c in str(char.get("c", "")))}
        for char in span.get("chars", [])
    ]
    return result


def restore_bitmap_characters(page, lines):
    """Insert exactly recognized tiny original glyphs into their source lines."""
    for image in page.get_text("dict").get("blocks", []):
        if image.get("type") != 1 or not image.get("image"):
            continue
        bounds = fitz.Rect(image["bbox"])
        if bounds.width >= 12 or bounds.height >= 12:
            continue
        with Image.open(io.BytesIO(image["image"])) as bitmap:
            gray = bitmap.convert("L")
            key = (*gray.size, hashlib.sha256(gray.tobytes()).hexdigest())
        character = _BITMAP_CHARACTERS.get(key)
        if not character:
            continue
        candidates = []
        for line in lines:
            line_bounds = fitz.Rect(line["bbox"])
            overlap = max(
                0, min(bounds.y1, line_bounds.y1) - max(bounds.y0, line_bounds.y0)
            )
            distance = max(line_bounds.x0 - bounds.x1, bounds.x0 - line_bounds.x1, 0)
            if overlap >= bounds.height * 0.8 and distance <= bounds.height:
                candidates.append((distance, line))
        if not candidates:
            raise ValueError(
                "recognized source bitmap character has no source text line"
            )
        candidates.sort(key=lambda item: item[0])
        line = candidates[0][1]
        nearest = min(line["spans"], key=lambda span: abs(span["bbox"][0] - bounds.x0))
        span = {
            **nearest,
            "text": character,
            "bbox": tuple(bounds),
            "source_bitmap_character": key[2],
            "chars": [
                {
                    "c": character,
                    "bbox": tuple(bounds),
                    "origin": (bounds.x0, nearest.get("origin", (0, bounds.y1))[1]),
                }
            ],
        }
        # A bitmap may be embedded in the middle of a text span whose bounding
        # box covers both adjacent words. Split using actual glyph x positions.
        rebuilt = []
        for existing in line["spans"]:
            chars = existing.get("chars", [])
            left = [char for char in chars if char["bbox"][0] < bounds.x0]
            right = [char for char in chars if char["bbox"][0] >= bounds.x0]
            for group in (left, right):
                if group:
                    region = fitz.Rect(group[0]["bbox"])
                    for char in group[1:]:
                        region |= fitz.Rect(char["bbox"])
                    rebuilt.append(
                        {
                            **existing,
                            "chars": group,
                            "text": "".join(char["c"] for char in group),
                            "bbox": tuple(region),
                        }
                    )
        line["spans"] = sorted([*rebuilt, span], key=lambda value: value["bbox"][0])
    return lines


def source_spans_in_cell(spans, bounds):
    """Split a physical PDF span at real cell edges using original glyph boxes."""
    bounds = fitz.Rect(bounds)
    result = []
    for span in spans:
        chars = span.get("chars")
        if not chars:
            region = fitz.Rect(span["bbox"])
            if (
                bounds.x0 <= (region.x0 + region.x1) / 2 < bounds.x1
                and bounds.y0 <= (region.y0 + region.y1) / 2 < bounds.y1
            ):
                result.append(span)
            continue
        selected = [
            char
            for char in chars
            if bounds.x0 <= (char["bbox"][0] + char["bbox"][2]) / 2 < bounds.x1
            and bounds.y0 <= (char["bbox"][1] + char["bbox"][3]) / 2 < bounds.y1
        ]
        if selected:
            region = fitz.Rect(selected[0]["bbox"])
            for char in selected[1:]:
                region |= fitz.Rect(char["bbox"])
            result.append(
                {
                    **span,
                    "text": "".join(char["c"] for char in selected),
                    "chars": selected,
                    "bbox": tuple(region),
                }
            )
    return result
