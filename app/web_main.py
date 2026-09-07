"""Authenticated web prototype, intentionally separate from app.main."""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import sqlite3
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


def validate_upload(path: Path, kind: str):
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
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                if (
                    len(entries) > 5000
                    or sum(x.file_size for x in entries) > 256 * 1024 * 1024
                ):
                    raise HTTPException(413, "문서 압축 해제 크기가 너무 큽니다.")
        except zipfile.BadZipFile as exc:
            raise HTTPException(400, "손상된 문서입니다.") from exc
    if kind == "pdf":
        import fitz

        try:
            with fitz.open(path) as doc:
                if doc.needs_pass:
                    raise HTTPException(400, "암호가 걸린 PDF는 지원하지 않습니다.")
                if not 1 <= len(doc) <= 50:
                    raise HTTPException(413, "PDF는 1~50쪽까지 지원합니다.")
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
        user = store.authenticate(request.cookies.get("hwp_session", ""))
        if not user:
            raise HTTPException(401, "로그인이 필요합니다.")
        return user

    def authorized_job(job_id: str, user: dict):
        row = store.get(user["id"], job_id)
        if not row:
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        return row

    def session_response(user, request):
        store.logout(request.cookies.get("hwp_session", ""))
        response = JSONResponse({"user": user})
        response.set_cookie(
            "hwp_session",
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
        store.logout(request.cookies.get("hwp_session", ""))
        response = JSONResponse({"ok": True})
        response.delete_cookie("hwp_session")
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
        user=Depends(current_user),
    ):
        return store.list_jobs(user["id"], offset, status)

    @app.post("/api/jobs", status_code=202)
    def submit(
        file: UploadFile = File(...),
        output_format: Literal["hwpx", "docx"] = Form("hwpx"),
        idempotency_key: str = Header(min_length=8, max_length=128),
        user=Depends(current_user),
    ):
        filename = Path((file.filename or "document").replace("\\", "/")).name[:200]
        kind = Path(filename).suffix.lower().lstrip(".")
        kind = "text" if kind == "txt" else kind
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
            validate_upload(folder / "source", kind)
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
        except OverflowError as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": "10"}) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            if not keep:
                shutil.rmtree(folder, ignore_errors=True)

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: str, user=Depends(current_user)):
        return {"job": store.public(authorized_job(job_id, user))}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str, user=Depends(current_user)):
        if not store.cancel(user["id"], job_id):
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        return {"job": store.public(authorized_job(job_id, user))}

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    def retry(
        job_id: str,
        idempotency_key: str = Header(min_length=8, max_length=128),
        user=Depends(current_user),
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
        except OverflowError as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": "10"}) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            if not keep:
                shutil.rmtree(folder, ignore_errors=True)

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str, user=Depends(current_user)):
        try:
            if not store.mark_deleted(user["id"], job_id):
                raise HTTPException(404, "작업을 찾을 수 없습니다.")
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        # Access is revoked in DB first. Worker sweeper retries any locked files.
        shutil.rmtree(store.job_dir(job_id), ignore_errors=True)
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/download")
    def download(job_id: str, source: bool = False, user=Depends(current_user)):
        row = authorized_job(job_id, user)
        if source:
            path, filename = store.job_dir(job_id) / "source", row["filename"]
        else:
            if row["state"] != "succeeded":
                raise HTTPException(409, "아직 다운로드할 결과가 없습니다.")
            path = store.job_dir(job_id) / row["attempt"] / f"output.{row['format']}"
            filename = Path(row["filename"]).stem + "." + row["format"]
        if not path.is_file():
            raise HTTPException(404, "보관된 파일을 찾을 수 없습니다.")
        return FileResponse(
            path, filename=filename, media_type="application/octet-stream"
        )

    # Only web UI assets are public. No local routes, uploads or AI settings.
    app.mount("/web-static", StaticFiles(directory=STATIC), name="web-static")
    return app


app = create_app()
