"""Exercise actual ASGI chunks, header bypasses, and endpoint side effects."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.request_limits import RequestBodyLimitMiddleware


async def check(chunks, declared, expected, *, disconnect=False):
    sent, calls, received = [], [], []
    pending = iter([
        {"type": "http.request", "body": chunk,
         "more_body": index < len(chunks) - 1 or disconnect}
        for index, chunk in enumerate(chunks)
    ] + ([{"type": "http.disconnect"}] if disconnect else []))

    async def receive():
        return next(pending)

    async def send(message):
        sent.append(message)

    async def endpoint(scope, receive, send):
        calls.append(True)
        while True:
            message = await receive()
            received.append(message["body"])
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    headers = [] if declared is None else [(b"content-length", declared)]
    await RequestBodyLimitMiddleware(endpoint, 8)(
        {"type": "http", "headers": headers}, receive, send)
    assert (sent[0]["status"] if sent else None) == expected, sent
    assert bool(calls) == (expected == 200), "Rejected request reached endpoint"
    if expected == 200:
        assert b"".join(received) == b"".join(chunks)


async def main():
    for declared in (None, b"1", b"invalid", b"-1"):
        await check([b"1234", b"56789"], declared, 413)
    await check([b"1234", b"", b"5678"], None, 200)
    await check([b"12345678"], b"8", 200)
    await check([b""], b"0", 200)
    await check([b"1"], b"9", 413)
    await check([b"1234"], None, None, disconnect=True)
    print("REQUEST_LIMITS_OK: header bypass, chunk boundary, replay, disconnect, no rejected side effects")


if __name__ == "__main__":
    asyncio.run(main())
