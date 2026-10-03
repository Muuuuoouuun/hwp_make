"""로컬 앱의 Host 헤더·요청 출처 검사(DNS 리바인딩·교차 출처 변경 요청 차단).

순수 ASGI 미들웨어다(BaseHTTPMiddleware 는 요청 취소 감지를 깨므로 쓰지 않는다).
- Host 가 허용 목록(localhost, 127.0.0.1, [::1], HWP_MAKE_ALLOWED_HOSTS)에 없으면 400.
- POST/PUT/PATCH/DELETE 에 Origin 이 있고 같은 출처가 아니면 403. Origin 이 없는
  요청(curl, 데스크톱 워커, 테스트 클라이언트)은 그대로 통과한다.
"""
from __future__ import annotations

import os

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import local_auth

DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "::1")
STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Starlette TestClient 는 Host 'testserver', 접속자 'testclient' 로 요청한다(실제 소켓 아님).
_TEST_CLIENT_PEER = "testclient"


def allowed_hosts() -> set[str]:
    extra = os.environ.get("HWP_MAKE_ALLOWED_HOSTS", "")
    hosts = {*DEFAULT_ALLOWED_HOSTS, *(item.strip().lower() for item in extra.split(","))}
    return {host.strip("[]") for host in hosts if host}


def _host_name(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):
        return value[1:value.find("]")] if "]" in value else ""
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class LocalHostGuardMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        host = _host_name(headers.get(b"host", b"").decode("latin-1"))
        peer = (scope.get("client") or ("", 0))[0]
        if host not in allowed_hosts() and not (host == "testserver" and peer == _TEST_CLIENT_PEER):
            await JSONResponse(status_code=400, content={"detail": {
                "code": "host_not_allowed",
                "message": "허용되지 않은 주소로 접속했습니다. 이 컴퓨터의 주소(127.0.0.1 또는 localhost)로 다시 열어 주세요.",
            }})(scope, receive, send)
            return
        if scope.get("method", "").upper() in STATE_CHANGING_METHODS and b"origin" in headers:
            if local_auth.same_origin_problem(Request(scope)):
                await JSONResponse(status_code=403, content={"detail": {
                    "code": "same_origin_required",
                    "message": "다른 사이트에서 보낸 요청이라 처리하지 않았습니다. 이 앱 화면에서 다시 실행해 주세요.",
                }})(scope, receive, send)
                return
        await self.app(scope, receive, send)
