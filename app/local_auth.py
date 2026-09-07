"""Single-owner login for a local workspace, separate from the web SaaS account store.

This protects the premium compose endpoints. Legacy local conversion/file APIs
retain their existing scope; this module does not make a shared workspace a
multi-user service or grant a paid subscription.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import ipaddress
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


COOKIE_NAME = "hwp_local_session"
SESSION_SECONDS = 12 * 60 * 60
PASSWORD_ITERATIONS = 600_000
LOGIN_WINDOW_SECONDS = 60
LOGIN_MAX_FAILURES = 5


class SetupPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=256)


class LoginPayload(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _loopback(value: str) -> bool:
    if value.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(value)
        mapped = getattr(address, "ipv4_mapped", None)
        return bool(address.is_loopback or (mapped and mapped.is_loopback))
    except ValueError:
        return False


def _check_same_origin(request: Request) -> None:
    origin = request.headers.get("origin", "")
    expected = str(request.base_url).rstrip("/")
    if origin != expected or request.headers.get("sec-fetch-site") == "cross-site":
        raise _error(403, "same_origin_required", "이 앱 화면에서 로그인 요청을 다시 실행해 주세요.")


class LocalWorkspaceAuth:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "local_auth.sqlite3"
        data_dir.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS owner (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    name TEXT NOT NULL,
                    salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_failures (attempted_at REAL NOT NULL);
            """)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def status(self, token: str = "") -> dict[str, Any]:
        with self._connection() as connection:
            owner = connection.execute("SELECT name FROM owner WHERE singleton = 1").fetchone()
            session = connection.execute(
                "SELECT 1 FROM sessions WHERE token_hash = ? AND expires_at > ?",
                (_token_hash(token), time.time()),
            ).fetchone() if token else None
        authenticated = bool(owner and session)
        return {
            "authenticated": authenticated,
            "user": {"name": owner["name"]} if authenticated else None,
            "setup_required": owner is None,
            "mode": "local_workspace",
            "premium_access": authenticated,
        }

    def require_user(self, request: Request | None) -> dict[str, str]:
        state = self.status(request.cookies.get(COOKIE_NAME, "") if request else "")
        if not state["authenticated"]:
            raise _error(401, "login_required", "프리미엄 시험지 작업을 계속하려면 로그인해 주세요.")
        if request is not None and request.method not in {"GET", "HEAD", "OPTIONS"}:
            _check_same_origin(request)
        return state["user"]

    def _new_session(self, connection: sqlite3.Connection, previous: str = "") -> str:
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))
        if previous:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(previous),))
        token = secrets.token_urlsafe(32)
        connection.execute("INSERT INTO sessions VALUES (?, ?)", (_token_hash(token), time.time() + SESSION_SECONDS))
        return token

    def setup(self, name: str, password: str) -> str:
        name = name.strip()
        if not name:
            raise _error(422, "name_required", "사용할 이름을 입력해 주세요.")
        salt = secrets.token_bytes(32)
        password_hash = _password_hash(password, salt)
        with self._connection() as connection:
            # The transaction covers both owner existence and insertion, including
            # concurrent first-run requests from another process or browser tab.
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM owner WHERE singleton = 1").fetchone():
                raise _error(409, "workspace_already_configured", "이미 계정이 설정되어 있습니다. 비밀번호로 로그인해 주세요.")
            connection.execute("INSERT INTO owner VALUES (1, ?, ?, ?)", (name, salt, password_hash))
            return self._new_session(connection)

    def login(self, password: str, previous: str = "") -> str:
        failure: HTTPException | None = None
        token = ""
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cutoff = time.time() - LOGIN_WINDOW_SECONDS
            connection.execute("DELETE FROM login_failures WHERE attempted_at < ?", (cutoff,))
            failures = connection.execute("SELECT COUNT(*) FROM login_failures").fetchone()[0]
            if failures >= LOGIN_MAX_FAILURES:
                raise _error(429, "login_rate_limited", "로그인 시도가 많습니다. 1분 후 다시 시도해 주세요.")
            owner = connection.execute("SELECT * FROM owner WHERE singleton = 1").fetchone()
            if owner is None:
                raise _error(409, "workspace_setup_required", "먼저 이 작업 공간의 계정을 설정해 주세요.")
            if not hmac.compare_digest(_password_hash(password, owner["salt"]), owner["password_hash"]):
                connection.execute("INSERT INTO login_failures VALUES (?)", (time.time(),))
                failure = _error(401, "invalid_password", "비밀번호가 맞지 않습니다.")
            else:
                connection.execute("DELETE FROM login_failures")
                token = self._new_session(connection, previous)
        # Failed-attempt recording must commit before raising the HTTP error.
        if failure:
            raise failure
        return token

    def logout(self, token: str) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))

    def router(self) -> APIRouter:
        router = APIRouter()

        def response(request: Request, token: str) -> JSONResponse:
            result = JSONResponse(self.status(token), headers={"Cache-Control": "no-store"})
            result.set_cookie(
                COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
                secure=request.url.scheme == "https", samesite="strict", path="/",
            )
            return result

        @router.get("/api/session")
        def session_status(request: Request):
            return JSONResponse(self.status(request.cookies.get(COOKIE_NAME, "")), headers={"Cache-Control": "no-store"})

        @router.post("/api/session/setup")
        def setup(payload: SetupPayload, request: Request):
            _check_same_origin(request)
            peer = request.client.host if request.client else ""
            host = urlsplit(str(request.base_url)).hostname or ""
            if not _loopback(peer) or not _loopback(host):
                raise _error(403, "local_setup_required", "처음 계정 설정은 이 컴퓨터의 localhost 주소에서 진행해 주세요.")
            return response(request, self.setup(payload.name, payload.password))

        @router.post("/api/session/login")
        def login(payload: LoginPayload, request: Request):
            _check_same_origin(request)
            return response(request, self.login(payload.password, request.cookies.get(COOKIE_NAME, "")))

        @router.post("/api/session/logout")
        def logout(request: Request):
            _check_same_origin(request)
            self.logout(request.cookies.get(COOKIE_NAME, ""))
            result = JSONResponse(self.status(), headers={"Cache-Control": "no-store"})
            result.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
            return result

        return router
