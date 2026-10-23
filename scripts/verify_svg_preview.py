"""Preview uses inert SVG image URLs; PNG remains an explicit compatibility path."""
from __future__ import annotations

import base64
import os
from pathlib import Path
import sys
import re
import tempfile
import time
from unittest.mock import patch
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
RUNTIME = tempfile.TemporaryDirectory(prefix="hwpmake_svg_preview_")
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name

from fastapi.testclient import TestClient
from app import main, preview, storage


def run():
    if not preview.available():
        print("SKIP: native preview renderer unavailable")
        return 2
    problem = storage.create_problem({"number": "27", "stem": "27. PREVIEWQUESTION Find the value.", "answer": "2"})
    started = time.perf_counter()
    vector = preview.render_preview("Preview", [problem], image_format="svg", max_pages=1)
    vector_seconds = time.perf_counter() - started
    assert vector["image_format"] == "svg" and vector["rendered_page_count"] == 1
    prefix, encoded = vector["pages"][0].split(",", 1)
    assert prefix == "data:image/svg+xml;base64"
    root = ET.fromstring(base64.b64decode(encoded))
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert "PREVIEWQUESTION" in re.sub(r"\s+", "", "".join(root.itertext()))
    started = time.perf_counter()
    raster = preview.render_preview("Preview", [problem], image_format="png", max_pages=1)
    png_seconds = time.perf_counter() - started
    assert raster["image_format"] == "png"
    assert base64.b64decode(raster["pages"][0].split(",", 1)[1]).startswith(b"\x89PNG\r\n\x1a\n")
    with TestClient(main.app) as client:
        with patch.object(main.preview, "render_preview", wraps=main.preview.render_preview) as renderer:
            response = client.post("/api/preview", json={"ids": [problem["id"]]})
            assert response.status_code == 200, response.text
            assert renderer.call_args.kwargs["image_format"] == "svg"
            assert response.json()["pages"][0].startswith("data:image/svg+xml;base64,")
        assert client.post("/api/preview?image_format=html", json={"ids": [problem["id"]]}).status_code == 422
        with patch.object(main.preview, "render_preview", return_value=raster) as renderer:
            assert client.post("/api/preview?image_format=png", json={"ids": [problem["id"]]}).status_code == 200
            assert renderer.call_args.kwargs["image_format"] == "png"
    source = (Path(__file__).resolve().parents[1] / "static/app.js").read_text(encoding="utf-8")
    assert "els.actualPreviewImage.src =" in source, "Preview must use an image element, never inject active SVG markup"
    print(f"PASS actual HWPX -> SVG/PNG, API defaults/validation and image embedding; SVG {vector_seconds:.3f}s, PNG {png_seconds:.3f}s")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    finally:
        RUNTIME.cleanup()
