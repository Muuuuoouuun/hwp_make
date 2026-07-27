"""API hardening regression checks.

This verifier intentionally uses an isolated data directory.  It exercises
validation and failure paths without retaining uploads, exports, or DB rows in
the normal application data directory.

Exit codes: 0 = PASS, 1 = FAIL.
"""

from __future__ import annotations

import base64
import concurrent.futures
import gc
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME_DIR = tempfile.TemporaryDirectory(prefix="hwpmake_api_hardening_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME_DIR.name

import httpx  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import collector, main, storage  # noqa: E402


failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def expect_raises(
    exception_type: type[BaseException],
    callback: Callable[[], Any],
    message: str,
) -> BaseException | None:
    try:
        callback()
    except exception_type as exc:
        return exc
    except Exception as exc:  # noqa: BLE001 - report an unexpected exception type
        failures.append(f"{message}: expected {exception_type.__name__}, got {type(exc).__name__}: {exc}")
        return None
    failures.append(f"{message}: expected {exception_type.__name__}, but no exception was raised")
    return None


def field_max_length(model: type[Any], field_name: str) -> int | None:
    field = model.model_fields[field_name]
    for constraint in field.metadata:
        value = getattr(constraint, "max_length", None)
        if isinstance(value, int):
            return value
    return None


def api_validation_checks(client: TestClient) -> None:
    oversized_request = client.post(
        "/api/import-text",
        headers={"content-length": str(main.MAX_REQUEST_BODY_BYTES + 1)},
        json={"title": "x", "text": "x"},
    )
    check(oversized_request.status_code == 413, f"oversized request body returned {oversized_request.status_code}")

    oversized_metadata = client.post(
        "/api/import-text",
        json={"title": "x", "text": "x", "metadata": {"note": "x" * (main.MAX_METADATA_BYTES + 1)}},
    )
    check(oversized_metadata.status_code == 413, f"oversized metadata returned {oversized_metadata.status_code}")

    invalid_base64 = client.post(
        "/api/import",
        json={"kind": "text", "filename": "bad.txt", "data_base64": "%%%%"},
    )
    check(invalid_base64.status_code == 400, f"invalid Base64 returned {invalid_base64.status_code}")

    wrong_signature = client.post(
        "/api/import",
        json={
            "kind": "pdf",
            "filename": "not-a-pdf.pdf",
            "data_base64": base64.b64encode(b"plain text").decode("ascii"),
        },
    )
    check(wrong_signature.status_code == 400, f"PDF signature mismatch returned {wrong_signature.status_code}")

    corrupt_pdf = client.post(
        "/api/import",
        json={
            "kind": "pdf",
            "filename": "corrupt.pdf",
            "data_base64": base64.b64encode(b"%PDF-1.7\nnot a complete PDF").decode("ascii"),
        },
    )
    check(corrupt_pdf.status_code == 400, f"corrupt PDF returned {corrupt_pdf.status_code}")

    corrupt_archive = client.post(
        "/api/import",
        json={
            "kind": "hwpx",
            "filename": "corrupt.hwpx",
            "data_base64": base64.b64encode(b"PK\x03\x04not a zip").decode("ascii"),
        },
    )
    check(corrupt_archive.status_code == 400, f"corrupt HWPX returned {corrupt_archive.status_code}")

    check(not any(storage.UPLOAD_DIR.iterdir()), "rejected imports left files in uploads/")
    check(not storage.list_problems(), "rejected imports created problem rows")

    configured_limit = field_max_length(main.ImportPayload, "data_base64")
    check(
        configured_limit == main.MAX_BASE64_CHARS,
        f"ImportPayload Base64 field limit is {configured_limit}, expected {main.MAX_BASE64_CHARS}",
    )

    original_limit = main.MAX_UPLOAD_BYTES
    try:
        main.MAX_UPLOAD_BYTES = 8
        exc = expect_raises(
            HTTPException,
            lambda: main._decode_upload(base64.b64encode(b"123456789").decode("ascii")),
            "decoded upload byte limit",
        )
        if isinstance(exc, HTTPException):
            check(exc.status_code == 413, f"oversized decoded upload raised HTTP {exc.status_code}, expected 413")
    finally:
        main.MAX_UPLOAD_BYTES = original_limit

    acquired = [main._CONVERSION_SLOTS.acquire(blocking=False) for _ in range(2)]
    try:
        exc = expect_raises(HTTPException, lambda: main._conversion_slot().__enter__(), "busy conversion gate")
        if isinstance(exc, HTTPException):
            check(exc.status_code == 429, f"busy conversion gate raised HTTP {exc.status_code}, expected 429")
    finally:
        for success in acquired:
            if success:
                main._CONVERSION_SLOTS.release()


def ssrf_checks() -> None:
    blocked_urls = (
        "http://localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
    )
    for url in blocked_urls:
        expect_raises(ValueError, lambda url=url: collector._validate_url(url), f"SSRF URL was not blocked: {url}")

    redirect_request = httpx.Request("GET", "http://127.0.0.1/internal")
    expect_raises(
        ValueError,
        lambda: collector._validate_outgoing_request(redirect_request),
        "redirect request hook did not revalidate a private destination",
    )
    with collector._client() as client:
        hooks = client._event_hooks.get("request", [])
        check(
            collector._validate_outgoing_request in hooks,
            "HTTP client does not register the outgoing-request SSRF hook",
        )


def concurrent_dedup_check() -> None:
    payload = {
        "source_type": "audit",
        "stem": "same payload submitted concurrently",
        "choices": ["A", "B"],
        "answer": "A",
    }

    def create(_: int) -> dict[str, Any] | None:
        return storage.create_problem_unique(payload)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(create, range(32)))
    except Exception as exc:  # noqa: BLE001
        failures.append(f"concurrent create_problem_unique raised {type(exc).__name__}: {exc}")
        return

    created = [item for item in results if item is not None]
    check(len(created) == 1, f"concurrent dedup returned {len(created)} created rows, expected 1")
    with storage.connect() as conn:
        row_count = conn.execute(
            "SELECT COUNT(*) FROM problems WHERE stem = ?",
            (payload["stem"],),
        ).fetchone()[0]
    check(row_count == 1, f"concurrent dedup persisted {row_count} rows, expected 1")


def failed_export_cleanup_check(client: TestClient) -> None:
    problem = storage.create_problem({"source_type": "audit", "stem": "export cleanup fixture"})
    original_writer = main.hwpx_writer_v2.write_hwpx

    def failing_writer(path: str | Path, *_args: Any, **_kwargs: Any) -> None:
        Path(path).write_bytes(b"partial export")
        raise RuntimeError("intentional writer failure")

    try:
        main.hwpx_writer_v2.write_hwpx = failing_writer
        response = client.post(
            "/api/export",
            json={"ids": [problem["id"]], "title": "cleanup", "format": "hwpx"},
        )
    finally:
        main.hwpx_writer_v2.write_hwpx = original_writer

    check(response.status_code == 500, f"failing export returned {response.status_code}, expected 500")
    check(not any(storage.EXPORT_DIR.iterdir()), "failed export left a partial file in exports/")

    original_pdf_writer = main.pdf_layout_writer.write_pdf_flow_hwpx

    def failing_pdf_writer(_source: str | Path, output: str | Path, **_kwargs: Any) -> dict[str, Any]:
        Path(output).write_bytes(b"partial PDF-layout export")
        raise RuntimeError("intentional PDF-layout writer failure")

    try:
        main.pdf_layout_writer.write_pdf_flow_hwpx = failing_pdf_writer
        pdf_response = client.post(
            "/api/pdf-layout-export",
            json={
                "filename": "cleanup.pdf",
                "data_base64": base64.b64encode(b"%PDF-1.7\ncleanup fixture").decode("ascii"),
                "max_pages": 1,
            },
        )
    finally:
        main.pdf_layout_writer.write_pdf_flow_hwpx = original_pdf_writer

    check(
        pdf_response.status_code == 500,
        f"failing PDF-layout export returned {pdf_response.status_code}, expected 500",
    )
    check(not any(storage.EXPORT_DIR.iterdir()), "failed PDF-layout export left a partial file in exports/")


def main_check() -> int:
    storage.init_db()
    with TestClient(main.app) as client:
        api_validation_checks(client)
        ssrf_checks()
        concurrent_dedup_check()
        failed_export_cleanup_check(client)

    if failures:
        print(f"API hardening verification FAILED ({len(failures)} issues)")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("API hardening verification PASS")
    print("  strict Base64/signatures/corrupt inputs: PASS")
    print("  upload size model/helper limits: PASS")
    print("  request/metadata size + conversion admission limits: PASS")
    print("  SSRF private targets + request hook: PASS")
    print("  concurrent dedup single row: PASS")
    print("  failed export partial cleanup: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main_check())
    finally:
        try:
            with storage.connect() as connection:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("PRAGMA journal_mode = DELETE")
        except Exception:
            pass
        gc.collect()
        RUNTIME_DIR.cleanup()
