"""Synthetic security, batching, snapshot and atomic export regression gates."""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch
import warnings
import zipfile
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="hwpmake_development_")
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name

from fastapi.testclient import TestClient
from app import document_security, importers, main, storage
from app.recognition.pipeline import infer_subject
from app.recognition.schema import Subject
from app.recognition import settings


def package(entries, compression=zipfile.ZIP_DEFLATED):
    buffer = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        warnings.simplefilter("ignore", UserWarning)
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


def security(client):
    with TestClient(main.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50200)) as outsider:
        response = outsider.post("/api/import-text", headers={"Sec-Fetch-Site": "cross-site"},
                                 json={"text": "1. Cross-site modification"})
        assert response.status_code == 403
    attacks = [
        ([("../outside.xml", "x")], 400),
        ([("C:/outside.xml", "x")], 400),
        ([("/outside.xml", "x")], 400),
        ([("Contents/section0.xml", "a"), ("Contents/section0.xml", "b")], 400),
        ([("Contents/section0.xml", "a"), ("Contents/./section0.xml", "b")], 400),
        ([("Contents/section0.xml", "x" * 2_000_000)], 413),
    ]
    before = set(storage.UPLOAD_DIR.rglob("*"))
    for entries, status in attacks:
        data = package(entries)
        for kind in ("hwpx", "docx"):
            response = client.post("/api/import", json={"kind": kind, "filename": f"attack.{kind}",
                                  "data_base64": base64.b64encode(data).decode()})
            assert response.status_code == status, (response.status_code, response.text)
            try:
                getattr(importers, "import_" + kind)(f"attack.{kind}", data, {})
            except document_security.DocumentSecurityError:
                pass
            else:
                raise AssertionError("Direct importer bypassed the shared ZIP guard")
    assert set(storage.UPLOAD_DIR.rglob("*")) == before
    for encoding in ("utf-8", "utf-16"):
        xml = '<?xml version="1.0" encoding="' + encoding + '"?><!DOCTYPE root [<!ENTITY secret SYSTEM "file:///etc/passwd">]><root>&secret;</root>'
        try:
            document_security.parse_document_xml(xml.encode(encoding))
        except document_security.DocumentSecurityError:
            pass
        else:
            raise AssertionError("DTD/entity XML accepted")
    assert document_security.parse_document_xml(b"<root><t>safe</t></root>")[0].text == "safe"
    source = importers.save_upload("untrusted.html", b"<script>fetch('/api/problems')</script>")
    response = client.get("/files/" + source)
    assert response.status_code == 200
    assert response.headers["content-disposition"] == "attachment"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]
    source_pdf = importers.save_upload("original.pdf", b"%PDF-1.4\n")
    original = client.get("/files/" + source_pdf)
    assert original.status_code == 200 and original.headers["content-type"].startswith("application/pdf")
    assert "content-disposition" not in original.headers
    print("PASS package traversal, ambiguity, compression bombs, direct import, UTF-8/16 entities and source HTML isolation")


def batching(client):
    items = [storage.create_problem({"number": str(i + 1), "stem": f"Synthetic question {i + 1}: " + "본문 " * 40}) for i in range(300)]
    ids = [item["id"] for item in reversed(items)]
    missing_id = max(ids) + 100
    original_connect = storage.connect
    with patch.object(storage, "connect", wraps=original_connect) as connections:
        response = client.post("/api/problems/batch", json={"ids": ids + [missing_id, ids[0]]})
    assert response.status_code == 200, response.text
    assert connections.call_count == 1, "Batching must use one database read"
    data = response.json()
    assert [item["id"] for item in data["items"]] == ids
    assert data["missing_ids"] == [missing_id]
    for invalid in ([], [0], [-1], [True], ["1"], ids + ids):
        assert client.post("/api/problems/batch", json={"ids": invalid}).status_code == 422
    started = time.perf_counter()
    for item_id in ids:
        assert client.get(f"/api/problems/{item_id}").status_code == 200
    singles = time.perf_counter() - started
    started = time.perf_counter()
    assert client.post("/api/problems/batch", json={"ids": ids}).status_code == 200
    batch = time.perf_counter() - started
    print(f"PASS ordered batch/missing inventory/validation: 300 requests {singles:.3f}s -> 1 request {batch:.3f}s")
    return ids[:2]


def snapshots(client, ids):
    payload = {"ids": ids, "workspace": "premium", "numbering_mode": "sequential", "start_number": 41}
    assert client.post("/api/export-plan", json=payload).status_code == 401
    assert client.post("/api/session/setup", json={"name": "검증", "password": "isolated-test-password"}).status_code == 200
    before = set(storage.EXPORT_DIR.rglob("*"))
    plan = client.post("/api/export-plan", json=payload)
    assert plan.status_code == 200, plan.text
    plan = plan.json()
    assert [item["id"] for item in plan["items"]] == ids
    assert [item["output_number"] for item in plan["items"]] == ["41", "42"]
    assert plan["question_count"] == 2 and plan["answer_count"] == 0
    assert set(storage.EXPORT_DIR.rglob("*")) == before, "Review must not render or create outputs"
    revision = plan["source_revision"]
    with storage.connect() as connection:
        connection.execute("UPDATE problems SET updated_at=? WHERE id=?", ("2099-01-01T00:00:00Z", ids[0]))
    assert client.post("/api/export-plan", json=payload).json()["source_revision"] == revision
    storage.update_problem(ids[0], {"stem": "Source edited after review"})
    for endpoint in ("/api/preview", "/api/export"):
        response = client.post(endpoint, json={**payload, "source_revision": revision})
        assert response.status_code == 409 and response.json()["detail"]["code"] == "source_changed"
    new_plan = client.post("/api/export-plan", json=payload).json()
    assert new_plan["source_revision"] != revision
    exported = client.post("/api/export", json={**payload, "source_revision": new_plan["source_revision"], "format": "docx"})
    assert exported.status_code == 200 and exported.content.startswith(b"PK")
    assert [storage.get_problem(item_id)["number"] for item_id in ids] != ["41", "42"]
    print("PASS authenticated premium review, numbering map, immutable sources and stale-source rejection")


def atomic_exports(ids):
    barrier = threading.Barrier(2)
    before = {item["name"] for item in storage.list_exports()}
    staged_paths = []

    def writer(path, *_args, **_kwargs):
        path = Path(path)
        staged_paths.append(path)
        assert not path.is_relative_to(storage.EXPORT_DIR)
        path.write_bytes(b"partial")
        # Both writers must run at once; an export lock around the writer would
        # time out here. Neither partial file may appear in history.
        barrier.wait(timeout=10)
        assert {item["name"] for item in storage.list_exports()} == before
        barrier.wait(timeout=10)
        path.write_bytes(package([("word/document.xml", "<document/>")]))

    with patch.object(main.docx_writer, "write_docx", side_effect=writer), patch.object(
        main, "_safe_export_name", return_value="concurrent.docx"
    ), ThreadPoolExecutor(max_workers=2) as pool:
        payload = main.ExportPayload(ids=ids, format="docx")
        results = list(pool.map(lambda _: main.export(payload), range(2)))
    paths = [Path(result.path) for result in results]
    assert len(set(paths)) == 2 and all(path.is_file() for path in paths)
    for path in paths:
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
    assert all(not path.parent.exists() for path in staged_paths)

    def fail(path, *_args, **_kwargs):
        Path(path).write_bytes(b"partial")
        raise RuntimeError("synthetic failure")

    completed = {item["name"] for item in storage.list_exports()}
    with patch.object(main.docx_writer, "write_docx", side_effect=fail):
        try:
            main.export(payload)
        except main.HTTPException as exc:
            assert exc.status_code == 500
        else:
            raise AssertionError("Failure was swallowed")
    assert {item["name"] for item in storage.list_exports()} == completed
    assert not list(storage.DATA_DIR.glob("export_*"))
    print("PASS simultaneous writers, unique atomic publication, hidden partial files and failure cleanup")


def atomic_settings():
    folder = storage.DATA_DIR / "isolated-settings"
    settings.save_user_settings(folder, {"saved": "previous"})
    with patch.dict(os.environ), patch.object(Path, "replace", side_effect=OSError("synthetic disk failure")):
        try:
            settings.update_api_keys(folder, gemini_api_key="synthetic-provider-key")
        except OSError:
            pass
        else:
            raise AssertionError("Settings failure was swallowed")
    assert settings.load_user_settings(folder) == {"saved": "previous"}
    assert not list(folder.glob("*.tmp"))
    barrier = threading.Barrier(2)

    def update(provider):
        barrier.wait(timeout=10)
        settings.update_api_keys(folder, **{provider: "synthetic-" + provider})

    with patch.dict(os.environ), ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(update, ["gemini_api_key", "openai_api_key"]))
    saved = settings.load_user_settings(folder)
    assert saved["gemini_api_key"] and saved["openai_api_key"]
    if os.name != "nt":
        assert settings.settings_path(folder).stat().st_mode & 0o077 == 0
    print("PASS private atomic settings, disk-failure preservation and concurrent provider updates")


def run():
    assert infer_subject("MATH.PDF") == Subject.MATH
    assert infer_subject(unicodedata.normalize("NFD", "고1 수학.pdf")) == Subject.MATH
    assert infer_subject("확률과 통계.pdf") == Subject.MATH
    assert infer_subject("ENGLISH.PDF") == Subject.ENGLISH
    print("PASS subject recognition for uppercase, decomposed Hangul and spaced subject names")
    with TestClient(main.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50100)) as client:
        client.headers["Origin"] = "http://127.0.0.1"
        security(client)
        ids = batching(client)
        snapshots(client, ids)
        atomic_exports(ids)
        atomic_settings()
    print("WORKSPACE_DEVELOPMENT_OK")


if __name__ == "__main__":
    try:
        run()
    finally:
        RUNTIME.cleanup()
