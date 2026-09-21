"""Bound request bodies before JSON parsing, including chunked uploads."""
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def reject() -> None:
            await JSONResponse(
                status_code=413,
                content={"detail": "요청 본문이 허용 크기를 초과합니다."},
            )(scope, receive, send)

        for key, value in scope.get("headers", []):
            if key.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    continue
                if declared > self.max_bytes:
                    await reject()
                    return

        # Validate before handing any bytes to an endpoint. Coalesce chunks so
        # millions of tiny/empty messages cannot grow per-message metadata.
        payload = bytearray()
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > self.max_bytes:
                await reject()
                return
            payload.extend(body)
            if not message.get("more_body", False):
                break

        pending = {"type": "http.request", "body": bytes(payload), "more_body": False}
        del payload

        async def replay():
            nonlocal pending
            message, pending = pending, None
            return message if message is not None else await receive()

        await self.app(scope, replay, send)
