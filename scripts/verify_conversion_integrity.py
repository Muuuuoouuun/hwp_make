"""Conversion inventory, legacy dedup, admission, cleanup and source-scope gate.

Uses only synthetic sources and an isolated TEMP database/output directory.
"""
from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RUNTIME = tempfile.TemporaryDirectory(prefix="hwpmake_integrity_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name

import fitz
from fastapi.testclient import TestClient
from PIL import Image
from app import importers, main, storage


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print("PASS:", message)


def pdf_bytes(pages: int = 1, *, variants: bool = False) -> bytes:
    with fitz.open() as document:
        for index in range(pages):
            page = document.new_page(width=595, height=842)
            number = index % (pages // 2) + 1 if variants else index + 1
            page.insert_text((48, 90), f"{number}. Find the value of x plus {number}.", fontsize=10)
            page.insert_text((48, 125), "1) 10  2) 20  3) 30  4) 40  5) 50", fontsize=10)
        return document.tobytes()


def payload(data: bytes, **kwargs) -> dict:
    return {"filename": "math_variants.pdf", "data_base64": base64.b64encode(data).decode(),
            "math_ai_recognition": False, **kwargs}


def files() -> set[str]:
    return {str(p.relative_to(storage.DATA_DIR)) for directory in (storage.UPLOAD_DIR, storage.EXPORT_DIR)
            for p in directory.rglob("*") if p.is_file()}


def verify(client: TestClient) -> None:
    data = {"source_name": "legacy.csv", "stem": "Find f(x)", "choices": ["A", "B"]}
    legacy = storage.create_problem(data)
    old_hash = storage._content_hash(data, legacy_casefold=True)
    with storage.connect() as connection:
        connection.execute("UPDATE problems SET content_hash = ? WHERE id = ?", (old_hash, legacy["id"]))
    check(storage.create_problem_unique(data) is None, "legacy exact duplicate remains idempotent")
    check(storage.find_existing_problem(data)["id"] == legacy["id"], "legacy existing ID is reusable")
    changed = storage.create_problem_unique({**data, "stem": "Find f(X)"})
    check(changed is not None and changed["id"] != legacy["id"], "legacy lowercase hash does not delete uppercase math")
    with storage.connect() as connection:
        retained = connection.execute("SELECT content_hash FROM problems WHERE id=?", (legacy["id"],)).fetchone()[0]
    check(retained == old_hash, "legacy compatibility does not rewrite existing rows")
    check(storage.create_problem_unique({**data, "source_name": "other.csv"}) is not None,
          "different source retains identical content")
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    image_path = importers._save_image_bytes("legacy.png", buffer.getvalue())
    rich = {**data, "source_name": "rich_legacy.csv", "image_paths": [image_path], "tables": [[["A", "B"]]]}
    old_rich = storage.create_problem(rich)
    with storage.connect() as connection:
        connection.execute("UPDATE problems SET content_hash=? WHERE id=?",
                           (storage._content_hash(rich, legacy_casefold=True), old_rich["id"]))
    check(storage.create_problem_unique(rich) is None, "legacy image/table content stays idempotent")
    check(storage.create_problem_unique({**rich, "tables": [[["a", "B"]]]}) is not None,
          "case-sensitive table cell is preserved against legacy hash")
    csv = b"number,stem\n1,Find f(x)\n2,Find f(X)\n"
    response = client.post("/api/import", json={"kind": "csv", "filename": "case.csv",
                           "data_base64": base64.b64encode(csv).decode()})
    check(response.status_code == 200 and len(response.json()["created"]) == 2,
          "same CSV preserves both x and X questions")

    before = files()
    for endpoint in ("/api/export", "/api/preview"):
        response = client.post(endpoint, json={"ids": [legacy["id"], 999999]})
        check(response.status_code == 409 and response.json()["detail"]["missing_ids"] == [999999],
              endpoint + " rejects a missing selected ID with exact inventory")
        response = client.post(endpoint, json={"ids": [legacy["id"], legacy["id"]]})
        check(response.status_code == 400, endpoint + " rejects duplicate IDs")
    check(files() == before, "invalid selection creates no output")

    for _ in range(2):
        main._CONVERSION_SLOTS.acquire()
    try:
        for endpoint, body in [("/api/export", {"ids": [legacy["id"]]}),
                               ("/api/preview", {"ids": [legacy["id"]]}),
                               ("/api/pdf-layout-export", payload(pdf_bytes()))]:
            response = client.post(endpoint, json=body)
            check(response.status_code == 429 and response.headers.get("retry-after") == "2",
                  endpoint + " preserves retryable admission status")
    finally:
        for _ in range(2):
            main._CONVERSION_SLOTS.release()
    check(files() == before, "busy PDF request leaves no upload/export")

    def failing_writer(_source, target, **_kwargs):
        Path(target).write_bytes(b"partial")
        importers.save_upload("intermediate.png", b"partial image")
        raise RuntimeError("synthetic write failure")

    for writer_name, mode in (("write_pdf_structured_hwpx", "structured"), ("write_pdf_structured_hwpx", "coordinate")):
        with patch.object(main.pdf_layout_writer, writer_name, failing_writer):
            response = client.post("/api/pdf-layout-export", json=payload(pdf_bytes(), layout_mode=mode))
        check(response.status_code == 500 and files() == before, mode + " failure cleans source, assets and export")
    with patch.object(main, "_pdf_export_scope", side_effect=RuntimeError("synthetic report failure")):
        response = client.post("/api/pdf-layout-export", json=payload(pdf_bytes(), layout_mode="coordinate"))
    check(response.status_code == 500 and files() == before, "postprocessing failure cleans complete run")
    response = client.post("/api/export", json={"ids": [legacy["id"]], "format": "docx"})
    check(response.status_code == 200 and response.content[:2] == b"PK", "released admission permits a real export")

    # Synthetic eight-page combined exam: both forms have the same stems but
    # source pages remain distinct. Exercise the actual writer, not a fake stats response.
    combined = pdf_bytes(8, variants=True)
    outputs = {}
    for policy, expected_pages in (("all", 8), ("first", 4)):
        response = client.post("/api/pdf-layout-export", json=payload(combined, variant_policy=policy))
        check(response.status_code == 200, f"{policy} variant conversion succeeds: {response.text[:160]}")
        result = response.json()
        outputs[policy] = result
        check(result["scope"]["selected_page_count"] == expected_pages, f"{policy} selected-page inventory is {expected_pages}")
        check(result["stats"]["output_problem_count"] == expected_pages, f"{policy} preserves every selected question")
        check(result["scope"]["original_page_count"] == 8, f"{policy} retains original-page inventory")
        check(result["fidelity"]["source_scope"]["selected_page_count"] == expected_pages,
              f"{policy} compares its declared source scope even when native reflow changes page count")
        if policy == "first":
            check(result["scope"]["excluded_page_count"] == 4 and "1–4" in result["notices"][0],
                  "first-form conversion discloses excluded pages")
    check(main.PdfLayoutExportPayload(**payload(combined)).variant_policy == "all", "API default preserves complete source")
    history = client.get("/api/exports").json()["items"]
    item = next(i for i in history if i["name"] == outputs["all"]["export"]["name"])
    conversion = item.get("conversion") or {}
    check(conversion.get("source", {}).get("url") and conversion.get("report", {}).get("url"),
          "export history links source and report")
    check(conversion["scope"]["selected_page_count"] == 8 and "objective_score" in conversion["quality"],
          "export history retains quality and scope")
    check(conversion["summary"]["output_page_count"] == outputs["all"]["fidelity"]["hwpx_page_count"]
          and conversion["summary"]["output_problem_count"] == 8,
          "export history reports measured output inventory")


if __name__ == "__main__":
    try:
        with TestClient(main.app, raise_server_exceptions=False) as client:
            verify(client)
        print("CONVERSION_INTEGRITY_OK")
    finally:
        RUNTIME.cleanup()
