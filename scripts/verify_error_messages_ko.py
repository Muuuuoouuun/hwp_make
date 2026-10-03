"""Pin teacher-facing Korean error details (2026-10-03 fix step 5a).

Conversion failures used to return the engine's English diagnostics together
with the server's absolute upload path, e.g.
``PDF 레이아웃 변환 실패: structured PDF recognition found no editable problems: C:\\...``.
They now return ``detail = {code, message, hint}`` in Korean; the raw exception
goes to the server log only.

All inputs are synthetic (fitz/PIL), so this verifier never SKIPs.
Exit codes: 0 = PASS, 1 = FAIL.
"""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory(prefix="hwpmake_error_ko_", ignore_cleanup_errors=True)
# Always isolated: this verifier uploads failing files and must not touch real data.
os.environ["HWP_MAKE_DATA_DIR"] = _TMP.name

import logging  # noqa: E402

import fitz  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import main, storage, user_errors  # noqa: E402

# Expected failures are logged with tracebacks by design; keep this output readable.
logging.getLogger("hwp_make.errors").disabled = True

failures: list[str] = []
PATH_RE = re.compile(r"[A-Za-z]:[\\/]|\\\\|/(?:home|Users|tmp)/")
ENGLISH_SENTENCE_RE = re.compile(r"[A-Za-z]{3,}(?:[ _][A-Za-z]{2,}){2,}")
HANGUL_RE = re.compile(r"[가-힣]")


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def scan_only_pdf() -> bytes:
    image = Image.new("RGB", (600, 800), "white")
    for x in range(100, 500):
        for y in (200, 201, 400, 401):
            image.putpixel((x, y), (0, 0, 0))
    png = io.BytesIO()
    image.save(png, format="PNG")
    document = fitz.open()
    page = document.new_page()
    page.insert_image(page.rect, stream=png.getvalue())
    return document.tobytes()


def encrypted_pdf() -> bytes:
    document = fitz.open()
    document.new_page().insert_text((72, 72), "1. question?")
    buffer = io.BytesIO()
    document.save(buffer, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="user-pw-1", owner_pw="owner-pw-1")
    return buffer.getvalue()


def no_question_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 90), "Plain paragraph without numbered questions for the classifier.")
    page.insert_text((72, 120), "Another plain paragraph that keeps the text layer populated.")
    return document.tobytes()


def assert_teacher_detail(label: str, response: Any, *, status: int, code: str | None = None) -> None:
    body_text = response.text
    check(response.status_code == status, f"{label}: status {response.status_code}, expected {status}: {body_text[:200]}")
    check(not PATH_RE.search(body_text), f"{label}: response leaks a filesystem path: {body_text[:240]}")
    try:
        body = response.json()
    except ValueError:
        failures.append(f"{label}: response is not JSON: {body_text[:200]}")
        return
    detail = body.get("detail")
    # Validation errors keep the field list in detail and put the message at top level.
    payload = body if isinstance(detail, list) else detail
    if not isinstance(payload, dict):
        failures.append(f"{label}: detail is not an object: {body_text[:200]}")
        return
    message = str(payload.get("message") or "")
    check(set(payload) >= {"code", "message", "hint"}, f"{label}: detail lacks code/message/hint: {payload}")
    check(bool(HANGUL_RE.search(message)), f"{label}: message is not Korean: {message!r}")
    for key in ("message", "hint"):
        value = str(payload.get(key) or "")
        check(not ENGLISH_SENTENCE_RE.search(value), f"{label}: {key} contains an English sentence: {value!r}")
    if code is not None:
        check(payload.get("code") == code, f"{label}: code {payload.get('code')!r}, expected {code!r}")


def classification_checks() -> None:
    check(user_errors.classify_pdf_failure(ValueError("x"), b"") == "empty", "empty bytes -> empty")
    check(user_errors.classify_pdf_failure(ValueError("x"), b"%PDF-1.4\n") == "damaged", "truncated -> damaged")
    check(user_errors.classify_pdf_failure(ValueError("x"), encrypted_pdf()) == "encrypted", "encrypted -> encrypted")
    check(user_errors.classify_pdf_failure(ValueError("x"), scan_only_pdf()) == "scan_only", "image-only -> scan_only")
    check(user_errors.classify_pdf_failure(
        ValueError("structured PDF recognition found no editable problems: a.pdf"), no_question_pdf()) == "no_questions",
        "text PDF without questions -> no_questions")
    check(user_errors.classify_pdf_failure(
        ValueError("native question grouping does not match source inventory: [...]"), no_question_pdf())
        == "unsupported_structure", "grouping mismatch -> unsupported_structure")
    check(user_errors.teacher_head(ValueError("PDF를 열 수 없습니다: Stream has ended")) == "PDF를 열 수 없습니다",
          "Korean head is kept without the English tail")
    check(user_errors.teacher_head(ValueError(r"C:\Users\홍 길동\a.pdf 실패")) is None, "a path head is dropped")
    check(user_errors.teacher_head(ValueError("C:/Users/홍 길동/a.pdf 실패")) is None, "a forward-slash path head is dropped")
    check(user_errors.teacher_head(ValueError("no hangul here")) is None, "an English-only message is dropped")
    check(user_errors.classify_pdf_failure(ValueError("no native PDF body content"), no_question_pdf())
          == "no_editable_content", "no native body -> no_editable_content")
    # teacher_message keeps an all-Korean message whole ('지원 형식: …') but cuts an English tail.
    check(user_errors.teacher_message(ValueError("지원 형식: PDF, HWP, HWPX, DOCX, TXT, 이미지"))
          == "지원 형식: PDF, HWP, HWPX, DOCX, TXT, 이미지", "all-Korean message kept whole")
    check(user_errors.teacher_message(ValueError("PDF를 열 수 없습니다: Stream has ended unexpectedly"))
          == "PDF를 열 수 없습니다", "English tail cut by teacher_message")
    check(user_errors.teacher_message(ValueError("저장 실패: C:/Users/홍길동/a.hwpx")) == "저장 실패",
          "path tail cut by teacher_message")


def desktop_worker_checks() -> None:
    """The desktop worker's result.json 'error' is shown to the teacher as is."""
    import json

    from app import desktop_convert

    job = Path(_TMP.name) / "desktop_job"
    job.mkdir(exist_ok=True)
    spec = job / "spec.json"
    leaked = r"C:\Users\홍길동\Documents\시험.hwpx"

    def run(source: Path) -> str:
        spec.write_text(json.dumps({"source": str(source), "destination": str(job / "out.hwpx")}), encoding="utf-8")
        desktop_convert.worker(spec)
        return json.loads((job / "result.json").read_text(encoding="utf-8"))["error"]

    unsupported = job / "a.xyz"
    unsupported.write_bytes(b"x")
    check(run(unsupported) == "지원 형식: PDF, HWP, HWPX, DOCX, TXT, 이미지",
          "desktop: Korean validation message must stay whole")
    original = desktop_convert.convert
    try:
        for raised, expected in (
            (PermissionError(13, "Permission denied", leaked), user_errors.MESSAGES["save_failed"][0]),
            (OSError(f"[Errno 22] Invalid argument: '{leaked}'"), user_errors.MESSAGES["conversion_failed"][0]),
            (ValueError(f"structured PDF recognition found no editable problems: {leaked}"),
             user_errors.MESSAGES["conversion_failed"][0]),
        ):
            def convert(*_args: Any, raised: Exception = raised, **_kwargs: Any) -> dict[str, Any]:
                raise raised

            desktop_convert.convert = convert
            error = run(unsupported)
            check(error == expected, f"desktop {type(raised).__name__}: {error!r}, expected {expected!r}")
            check(not PATH_RE.search(error), f"desktop {type(raised).__name__} leaks a path: {error!r}")
    finally:
        desktop_convert.convert = original


def api_checks(client: TestClient) -> None:
    layout = lambda name, data: client.post("/api/pdf-layout-export", json={  # noqa: E731
        "filename": name, "data_base64": data, "layout_mode": "structured", "native_math": True})
    imported = lambda name, data: client.post("/api/import", json={  # noqa: E731
        "kind": "pdf", "filename": name, "data_base64": data, "metadata": {"math_ai_recognition": False}})

    cases = {
        "scan_only": ("scan.pdf", b64(scan_only_pdf())),
        "encrypted": ("locked.pdf", b64(encrypted_pdf())),
        "damaged": ("broken.pdf", b64(b"%PDF-1.4\n")),
    }
    for code, (name, data) in cases.items():
        assert_teacher_detail(f"layout {code}", layout(name, data), status=400, code=code)
    assert_teacher_detail("layout no_questions", layout("plain.pdf", b64(no_question_pdf())), status=400, code="no_questions")
    for code in ("encrypted", "damaged"):
        name, data = cases[code]
        assert_teacher_detail(f"import {code}", imported(name, data), status=400, code=code)
    # Zero-byte upload arrives as an empty Base64 string (pydantic min_length).
    assert_teacher_detail("layout zero-byte", layout("zero.pdf", ""), status=422, code="empty")
    assert_teacher_detail("import zero-byte", imported("zero.pdf", ""), status=422, code="empty")
    assert_teacher_detail("layout non-PDF", layout("note.pdf", b64(b"plain text")), status=400, code="not_pdf")
    assert_teacher_detail("layout bad Base64", layout("x.pdf", "%%%%"), status=400, code="invalid_request")

    # Engine messages that embed the server path or English diagnostics stay in the log.
    text_pdf = b64(no_question_pdf())
    original = main.pdf_layout_writer.write_pdf_structured_hwpx
    leaked = r"C:\Projects\hwp_make\data\uploads\20261003_1_시험 1.pdf"
    try:
        def value_error(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise ValueError(f"native question grouping does not match source inventory: {leaked}")

        main.pdf_layout_writer.write_pdf_structured_hwpx = value_error
        assert_teacher_detail("layout engine ValueError", layout("s.pdf", text_pdf), status=400, code="unsupported_structure")

        def runtime_error(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError(f"Generated HWPX package failed validation: {leaked}")

        main.pdf_layout_writer.write_pdf_structured_hwpx = runtime_error
        assert_teacher_detail("layout engine crash", layout("s.pdf", text_pdf), status=500, code="conversion_failed")
    finally:
        main.pdf_layout_writer.write_pdf_structured_hwpx = original

    original_importer = main.IMPORTERS["text"]
    try:
        for raised, expected in (
            (ValueError("PDF는 200쪽 이하만 처리할 수 있습니다."), "PDF는 200쪽 이하만 처리할 수 있습니다."),
            (ValueError(f"PDF를 열 수 없습니다: {leaked}"), "PDF를 열 수 없습니다"),
            (ValueError("unexpected token in stream object"), user_errors.MESSAGES["import_failed"][0]),
        ):
            def importer(*_args: Any, raised: Exception = raised, **_kwargs: Any) -> dict[str, Any]:
                raise raised

            main.IMPORTERS["text"] = importer
            response = client.post("/api/import", json={"kind": "text", "filename": "a.txt", "data_base64": b64(b"x")})
            assert_teacher_detail(f"import ValueError {expected}", response, status=400, code="import_failed")
            check(response.json()["detail"]["message"] == expected,
                  f"import message {response.json()['detail']['message']!r}, expected {expected!r}")

        def crash(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise KeyError(leaked)

        main.IMPORTERS["text"] = crash
        response = client.post("/api/import", json={"kind": "text", "filename": "a.txt", "data_base64": b64(b"x")})
        assert_teacher_detail("import crash", response, status=500, code="conversion_failed")
    finally:
        main.IMPORTERS["text"] = original_importer

    # Signature/package checks on the import path used to return plain strings; now the same shape.
    response = imported("note.pdf", b64(b"plain text, not a pdf"))
    assert_teacher_detail("import non-PDF signature", response, status=400, code="format_mismatch")
    response = client.post("/api/import", json={"kind": "hwpx", "filename": "b.hwpx", "data_base64": b64(b"PK\x03\x04broken")})
    assert_teacher_detail("import damaged HWPX package", response, status=400, code="damaged")

    # /api/collect: Korean address-guard messages stay, internal English exceptions do not leak.
    original_collect = main.collector.collect_url
    try:
        for raised, status, expected in (
            (ValueError("로컬 또는 사설 네트워크 주소는 수집할 수 없습니다."), 400, "로컬 또는 사설 네트워크 주소는 수집할 수 없습니다."),
            (ValueError("not enough values to unpack (expected 3, got 2)"), 400, user_errors.MESSAGES["collect_failed"][0]),
            (OSError(f"[Errno 11001] getaddrinfo failed {leaked}"), 502, user_errors.MESSAGES["collect_failed"][0]),
        ):
            def collect_url(*_args: Any, raised: Exception = raised, **_kwargs: Any) -> dict[str, Any]:
                raise raised

            main.collector.collect_url = collect_url
            response = client.post("/api/collect", json={"url": "https://example.com/exam"})
            assert_teacher_detail(f"collect {type(raised).__name__} {status}", response, status=status, code="collect_failed")
            if response.status_code == status:
                check(response.json()["detail"]["message"] == expected,
                      f"collect message {response.json()['detail']['message']!r}, expected {expected!r}")
    finally:
        main.collector.collect_url = original_collect

    problem = storage.create_problem({"source_type": "audit", "stem": "1. 내보내기 실패 확인"})
    original_writer = main.hwpx_writer_v2.write_hwpx
    try:
        def failing_writer(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError(f"writer failure at {leaked}")

        main.hwpx_writer_v2.write_hwpx = failing_writer
        response = client.post("/api/export", json={"ids": [problem["id"]], "title": "x", "format": "hwpx"})
        assert_teacher_detail("export crash", response, status=500, code="export_failed")
    finally:
        main.hwpx_writer_v2.write_hwpx = original_writer

    # Remaining plain/English details on the editing and export paths ('Problem not found',
    # 'Unknown export template', duplicate selection) now use the same shape.
    assert_teacher_detail("missing problem", client.get("/api/problems/987654"), status=404, code="not_found")
    assert_teacher_detail("unknown template", client.post("/api/export", json={
        "ids": [problem["id"]], "title": "x", "format": "hwpx", "template_key": "no-such-template"}),
        status=400, code="invalid_request")
    assert_teacher_detail("duplicate selection", client.post("/api/export", json={
        "ids": [problem["id"], problem["id"]], "title": "x", "format": "hwpx"}), status=400, code="invalid_request")


def main_check() -> int:
    storage.init_db()
    classification_checks()
    with TestClient(main.app) as client:
        api_checks(client)
    desktop_worker_checks()
    if failures:
        print(f"Korean error message verification FAILED ({len(failures)} issues)")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("Korean error message verification PASS")
    print("  failure classification (empty/encrypted/damaged/scan_only/no_questions/structure): PASS")
    print("  /api/pdf-layout-export, /api/import, /api/export, /api/collect details: code+message+hint, no path, no English: PASS")
    print("  not-found/unknown-template/duplicate details and desktop worker errors: Korean, no path: PASS")
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
        _TMP.cleanup()
