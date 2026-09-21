"""Pixel equivalence and complete score parity against the original Pillow QA."""
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import pdf_layout_fidelity as fidelity  # noqa: E402


def pillow_max(image, size):
    return image.filter(ImageFilter.MaxFilter(size))


def main():
    rng = np.random.default_rng(20260909)
    checks = 0
    for shape in ((1, 1), (2, 13), (31, 37), (100, 150)):
        for binary in (True, False):
            pixels = rng.integers(0, 2 if binary else 256, shape, dtype=np.uint8)
            if binary:
                pixels *= 255
            mask = Image.fromarray(pixels)
            for size in (1, 3, 5, 7, 9, 15, 17, 21):
                expected = np.asarray(pillow_max(mask, size))
                actual = np.asarray(fidelity._max_filter(mask, size))
                assert np.array_equal(actual, expected), (shape, binary, size)
                assert np.array_equal(np.asarray(mask), pixels), "input was changed"
                checks += 1
    source = Image.new("RGB", (360, 510), "white")
    draw = ImageDraw.Draw(source)
    draw.rectangle((15, 20, 150, 95), outline="black", width=2)
    for row in range(110, 430, 17):
        draw.text((20, row), "1. Fractions, text and figures", fill="black")
        draw.line((190, row, 320, row + 2), fill=(170, 170, 170), width=2)
    for output in (source.copy(), source.transform(source.size, Image.Transform.AFFINE,
                                                  (1, 0, 3, 0, 1, -2), fillcolor="white"),
                   Image.new("RGB", source.size, "white")):
        with patch.object(fidelity, "_max_filter", pillow_max):
            expected = fidelity._page_metrics(source, output)
        assert fidelity._page_metrics(source, output) == expected
    print(f"FIDELITY_MAX_FILTER_OK: {checks} pixel cases; 3 complete score comparisons")


if __name__ == "__main__":
    main()
