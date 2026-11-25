"""Authenticated web prototype, intentionally separate from app.main."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import sqlite3
import unicodedata
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .web_store import MAX_FILE, ROOT, Store
from .web_worker import Worker

STATIC = Path(__file__).resolve().parents[1] / "static" / "web"


class Login(BaseModel):
    email: str = Field(
        min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
    )
    password: str = Field(min_length=10, max_length=128)


class Setup(Login):
    name: str = Field(min_length=1, max_length=60)
    token: str = Field(min_length=20, max_length=200)


class ReportViewport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: int = Field(ge=0, le=20000)
    height: int = Field(ge=0, le=20000)


class BugReport(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=160)
    category: Literal["conversion", "upload", "download", "interface", "other"] = (
        "other"
    )
    description: str = Field(min_length=5, max_length=6000)
    steps: str = Field(default="", max_length=4000)
    expected: str = Field(default="", max_length=2000)
    job_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    browser: str = Field(default="", max_length=300)
    viewport: ReportViewport | None = None


class BodyLimit:
    """Count received bytes even when Content-Length is absent or incorrect."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > MAX_FILE + 128 * 1024:
                raise HTTPException(413, "파일은 20MB 이하만 올릴 수 있습니다.")
            return message

        await self.app(scope, limited_receive, send)


def converted_download_name(original: str, output_format: str) -> str:
    stem = unicodedata.normalize("NFC", Path(original.replace("\\", "/")).stem)
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", stem).strip(" .") or "문서"
    if re.fullmatch(r"CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[1-9¹²³]", stem.partition(".")[0].rstrip(), re.I):
        stem = "_" + stem
    suffix = "_변환." + output_format
    # Leave room in a filesystem component for the browser's duplicate counter.
    budget = 200 - len(suffix.encode("utf-8"))
    stem = stem.encode("utf-8")[:budget].decode("utf-8", errors="ignore").rstrip(" .")
    return (stem or "문서") + suffix


def validate_upload(path: Path, kind: str, *, text_pdf_only: bool = False):
    with path.open("rb") as stream:
        prefix = stream.read(16)
    signatures = {
        "pdf": b"%PDF",
        "hwp": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
        "hwpx": b"PK\x03\x04",
        "docx": b"PK\x03\x04",
    }
    if kind in signatures and not prefix.startswith(signatures[kind]):
        raise HTTPException(400, "확장자와 파일 내용이 일치하지 않습니다.")
    if kind in ("hwpx", "docx"):
        from lxml.etree import XMLSyntaxError
        from .document_security import DocumentSecurityError, parse_document_xml, validate_archive

        try:
            with zipfile.ZipFile(path) as archive:
                validate_archive(archive)
                if kind == "docx":
                    types_info = archive.getinfo("[Content_Types].xml")
                    if types_info.file_size > 1024 * 1024 or "word/document.xml" not in archive.namelist():
                        raise ValueError("Missing Word document")
                    types = parse_document_xml(archive.read(types_info))
                    word_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
                    if not any(part.get("PartName") == "/word/document.xml" and part.get("ContentType") == word_type
                               for part in types):
                        raise ValueError("Missing Word document type")
        except DocumentSecurityError as exc:
            raise HTTPException(413 if exc.too_large else 400, str(exc)) from exc
        except (zipfile.BadZipFile, KeyError, ValueError, RuntimeError, XMLSyntaxError) as exc:
            raise HTTPException(400, "손상된 문서입니다.") from exc
    if kind == "pdf":
        import fitz

        try:
            with fitz.open(path) as doc:
                if doc.needs_pass:
                    raise HTTPException(400, "암호가 걸린 PDF는 지원하지 않습니다.")
                if not 1 <= len(doc) <= 50:
                    raise HTTPException(413, "PDF는 1~50쪽까지 지원합니다.")
                if text_pdf_only and not any(page.get_text("words") for page in doc):
                    raise HTTPException(400, "선택할 수 있는 글자가 없는 PDF예요. 텍스트 PDF 또는 DOCX를 올려 주세요.")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, "PDF를 열 수 없습니다.") from exc


def create_app(
    root: Path = ROOT, *, worker_enabled: bool = True, origin: str | None = None
) -> FastAPI:
    store = Store(root)
    origin = (
        origin or os.environ.get("HWP_WEB_ORIGIN", "http://127.0.0.1:8788")
    ).rstrip("/")
    secure = urlsplit(origin).scheme == "https"
    account_cookie = os.environ.get("HWP_WEB_AUTH_COOKIE", "hwp_session")
    guest_cookie = "hwp_guest_beta"


    @asynccontextmanager
    async def lifespan(app):
        worker = Worker(store) if worker_enabled else None
        if worker:
            worker.start()
        yield
        if worker:
            worker.close()

    app = FastAPI(
        title="HWP Make Web Prototype",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store
    app.add_middleware(BodyLimit)

    @app.middleware("http")
    async def protections(request: Request, call_next):
        if request.headers.get("host") != urlsplit(origin).netloc:
            return JSONResponse(
                {"detail": "허용되지 않은 서버 주소입니다."}, status_code=400
            )
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("x-hwp-request") != "1" or request.headers.get(
                "origin"
            ) not in (None, origin):
                return JSONResponse(
                    {
                        "detail": "요청 출처를 확인할 수 없습니다. 화면을 새로고침해 주세요."
                    },
                    status_code=403,
                )
        try:
            if int(request.headers.get("content-length", "0")) > MAX_FILE + 128 * 1024:
                return JSONResponse(
                    {"detail": "파일은 20MB 이하만 올릴 수 있습니다."}, status_code=413
                )
        except ValueError:
            return JSONResponse({"detail": "잘못된 요청 크기입니다."}, status_code=400)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            }
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def bad_input(request, exc):
        # Validation errors must not echo passwords, bootstrap tokens or content.
        return JSONResponse(
            {
                "detail": "신고 제목과 증상(5자 이상), 입력 길이를 확인해 주세요."
                if request.url.path == "/api/bug-reports"
                else "입력 형식과 필수 항목을 확인해 주세요. 비밀번호는 10~128자입니다."
            },
            status_code=422,
        )

    def current_user(request: Request):
        user = store.authenticate(request.cookies.get(account_cookie, ""))
        if not user:
            raise HTTPException(401, "로그인이 필요합니다.")
        return user

    def current_actor(request: Request):
        user = store.authenticate(request.cookies.get(account_cookie, ""))
        if user:
            return user
        guest = store.authenticate_guest(request.cookies.get(guest_cookie, ""))
        if not guest:
            raise HTTPException(401, "현재 브라우저의 게스트 세션 또는 로그인이 필요합니다.")
        return guest

    @app.post("/api/guest")
    def guest_session(request: Request):
        if store.authenticate(request.cookies.get(account_cookie, "")):
            raise HTTPException(409, "이미 계정으로 로그인되어 있습니다.")
        guest = store.authenticate_guest(request.cookies.get(guest_cookie, ""))
        token = None
        if not guest:
            if not store.rate_limit("guest-session:" + (request.client.host if request.client else "unknown"),
                                    limit=90, seconds=3600):
                raise HTTPException(429, "게스트 세션 요청이 많습니다. 잠시 후 다시 시도해 주세요.")
            token = store.new_guest()
            guest = store.authenticate_guest(token)
        if not guest:
            raise HTTPException(500, "게스트 세션을 시작하지 못했습니다.")
        result = JSONResponse({"user": {"guest": True, "name": "게스트"},
                               "quota": store.guest_quota(guest["id"])})
        if token:
            result.set_cookie(guest_cookie, token, max_age=86400, httponly=True,
                              secure=secure, samesite="strict", path="/")
        return result

    def authorized_job(job_id: str, user: dict):
        row = store.get(user["id"], job_id)
        if not row:
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        return row

    def session_response(user, request):
        store.logout(request.cookies.get(account_cookie, ""))
        response = JSONResponse({"user": user})
        response.set_cookie(
            account_cookie,
            store.session(user["id"]),
            httponly=True,
            secure=secure,
            samesite="strict",
            max_age=86400,
        )
        return response

    @app.get("/")
    def home():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/health")
    def health():
        return {"ok": True, "mode": "prototype"}

    @app.post("/api/setup")
    def setup(payload: Setup, request: Request):
        if not store.rate_limit(
            "setup:" + (request.client.host if request.client else "unknown")
        ):
            raise HTTPException(429, "잠시 후 다시 시도해 주세요.")
        try:
            user = store.create_user(
                payload.email,
                payload.name.strip() or "사용자",
                payload.password,
                payload.token,
            )
        except (ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(
                400,
                "초기 설정 링크가 만료되었거나 계정이 이미 있습니다. 로그인해 주세요.",
            ) from exc
        return session_response(user, request)

    @app.post("/api/login")
    def login(payload: Login, request: Request):
        if not store.rate_limit(
            "login:" + (request.client.host if request.client else "unknown")
        ):
            raise HTTPException(
                429,
                "로그인 시도가 많습니다. 15분 후 다시 시도해 주세요.",
                headers={"Retry-After": "900"},
            )
        user = store.login(payload.email, payload.password)
        if not user:
            raise HTTPException(401, "이메일 또는 비밀번호가 맞지 않습니다.")
        return session_response(user, request)

    @app.post("/api/logout")
    def logout(request: Request):
        store.logout(request.cookies.get(account_cookie, ""))
        response = JSONResponse({"ok": True})
        response.delete_cookie(account_cookie)
        return response

    @app.get("/api/me")
    def me(user=Depends(current_user)):
        return {"user": user}

    @app.post("/api/bug-reports", status_code=201)
    def submit_report(
        payload: BugReport,
        idempotency_key: str = Header(min_length=8, max_length=128),
        user=Depends(current_user),
    ):
        try:
            return {
                "report": store.create_report(
                    user["id"], idempotency_key, payload.model_dump()
                )
            }
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except OverflowError as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": "3600"}) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/bug-reports")
    def my_reports(user=Depends(current_user)):
        return store.reports(user["id"])

    @app.get("/api/bug-reports/{report_id}")
    def get_report(report_id: str, user=Depends(current_user)):
        report = store.report(user["id"], report_id)
        if report is None:
            raise HTTPException(404, "신고를 찾을 수 없습니다.")
        return {"report": report}

    @app.get("/api/jobs")
    def jobs(
        offset: int = Query(0, ge=0, le=100000),
        status: Literal["all", "active", "succeeded"] = "all",
        user=Depends(current_actor),
    ):
        payload = store.list_jobs(user["id"], offset, status)
        if user.get("guest"):
            payload["quota"] = store.guest_quota(user["id"])
        return payload

    @app.post("/api/jobs", status_code=202)
    def submit(
        file: UploadFile = File(...),
        output_format: Literal["hwpx", "docx"] = Form("hwpx"),
        idempotency_key: str = Header(min_length=8, max_length=128),
        user=Depends(current_actor),
    ):
        filename = Path((file.filename or "document").replace("\\", "/")).name
        kind = Path(filename).suffix.lower().lstrip(".")
        kind = "text" if kind == "txt" else kind
        if user.get("guest") and (kind not in ("pdf", "docx") or output_format != "hwpx"):
            raise HTTPException(400, "게스트는 PDF와 DOCX를 HWPX로 변환할 수 있습니다.")
        if kind not in {"pdf", "hwp", "hwpx", "docx", "text"}:
            raise HTTPException(400, "PDF, HWP, HWPX, DOCX, TXT 파일을 선택해 주세요.")
        job_id = secrets.token_hex(16)
        folder = store.job_dir(job_id)
        folder.mkdir()
        keep = False
        try:
            size = 0
            content_hash = hashlib.sha256()
            with (folder / "source").open("wb") as out:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_FILE:
                        raise HTTPException(413, "파일은 20MB 이하만 올릴 수 있습니다.")
                    content_hash.update(chunk)
                    out.write(chunk)
            if not size:
                raise HTTPException(400, "빈 파일은 변환할 수 없습니다.")
            validate_upload(folder / "source", kind, text_pdf_only=bool(user.get("guest")))
            fingerprint = (
                content_hash.hexdigest() + ":" + output_format + ":" + filename
            )
            job, keep = store.enqueue(
                user["id"],
                idempotency_key,
                fingerprint,
                job_id,
                filename,
                kind,
                output_format,
                size,
            )
            return {"job": store.public(job)}
        except PermissionError as exc:
            raise HTTPException(401, str(exc)) from exc
        except OverflowError as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": "10"}) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            if not keep:
                shutil.rmtree(folder, ignore_errors=True)

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: str, user=Depends(current_actor)):
        return {"job": store.public(authorized_job(job_id, user))}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str, user=Depends(current_actor)):
        if not store.cancel(user["id"], job_id):
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        return {"job": store.public(authorized_job(job_id, user))}

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    def retry(
        job_id: str,
        idempotency_key: str = Header(min_length=8, max_length=128),
        user=Depends(current_actor),
    ):
        original = authorized_job(job_id, user)
        if original["state"] not in ("failed", "cancelled"):
            raise HTTPException(
                409, "실패하거나 취소된 작업만 다시 시도할 수 있습니다."
            )
        source = store.job_dir(job_id) / "source"
        if not source.is_file():
            raise HTTPException(404, "원본이 없습니다. 파일을 다시 올려 주세요.")
        new_id = secrets.token_hex(16)
        folder = store.job_dir(new_id)
        folder.mkdir()
        keep = False
        try:
            shutil.copyfile(source, folder / "source")
            job, keep = store.enqueue(
                user["id"],
                idempotency_key,
                original["fingerprint"],
                new_id,
                original["filename"],
                original["kind"],
                original["format"],
                original["input_size"],
            )
            return {"job": store.public(job)}
        except PermissionError as exc:
            raise HTTPException(401, str(exc)) from exc
        except OverflowError as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": "10"}) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            if not keep:
                shutil.rmtree(folder, ignore_errors=True)

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str, user=Depends(current_actor)):
        try:
            if not store.mark_deleted(user["id"], job_id):
                raise HTTPException(404, "작업을 찾을 수 없습니다.")
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        # Access is revoked in DB first. Worker sweeper retries any locked files.
        if not store.purge_files(job_id):
            return JSONResponse({"deletion": "pending"}, status_code=202)
        return {"ok": True, "deletion": "complete"}

    @app.get("/api/jobs/{job_id}/download")
    def download(job_id: str, source: bool = False, user=Depends(current_actor)):
        row = authorized_job(job_id, user)
        try:
            folder = store.job_dir(job_id)
        except (OSError, ValueError) as exc:
            raise HTTPException(404, "보관된 파일을 찾을 수 없습니다.") from exc
        if source:
            path, filename = folder / "source", row["filename"]
        else:
            if row["state"] != "succeeded":
                raise HTTPException(409, "아직 다운로드할 결과가 없습니다.")
            if not re.fullmatch(r"[0-9a-f]{32}", row["attempt"] or "") or row["format"] not in ("hwpx", "docx"):
                raise HTTPException(404, "보관된 파일을 찾을 수 없습니다.")
            path = folder / row["attempt"] / f"output.{row['format']}"
            filename = converted_download_name(row["filename"], row["format"])
        expected_size = row["input_size"] if source else row["output_size"]
        if path.resolve() != path or not path.is_file() or path.stat().st_size != expected_size or expected_size <= 0:
            raise HTTPException(404, "보관된 파일을 찾을 수 없습니다.")
        return FileResponse(
            path, filename=filename, media_type="application/octet-stream"
        )

    # Only web UI assets are public. No local routes, uploads or AI settings.
    app.mount("/web-static", StaticFiles(directory=STATIC), name="web-static")
    return app


app = create_app()
