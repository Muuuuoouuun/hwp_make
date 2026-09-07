"""Isolated local-owner session checks; never uses an existing workspace account."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import gc
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="hwp-local-auth-")
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name

from fastapi import HTTPException
from fastapi.testclient import TestClient
from app import local_auth, main, storage


PASSWORD = "isolated-test-password-2026"
ORIGIN = "http://127.0.0.1"


def check(response, status, code=None):
    assert response.status_code == status, (response.status_code, response.text)
    if code:
        assert response.json()["detail"]["code"] == code, response.text


def client_for(**options):
    return TestClient(main.app, base_url=ORIGIN, client=("127.0.0.1", 50000), **options)


def verify_sessions():
    with client_for() as client:
        initial = client.get("/api/session")
        check(initial, 200)
        assert initial.json() == {
            "authenticated": False, "user": None, "setup_required": True,
            "mode": "local_workspace", "premium_access": False,
        }
        assert initial.headers["cache-control"] == "no-store"
        premium = {"ids": [999999], "workspace": "premium", "numbering_mode": "sequential"}
        for endpoint in ("/api/export", "/api/preview"):
            check(client.post(endpoint, json=premium), 401, "login_required")
        payload = {"name": "Local test owner", "password": PASSWORD}
        check(client.post("/api/session/setup", json=payload), 403, "same_origin_required")
        check(client.post("/api/session/setup", json=payload, headers={"origin": "https://other.example"}), 403)
        check(client.post("/api/session/setup", json={**payload, "password": "short"}, headers={"origin": ORIGIN}), 422)
        with TestClient(main.app, base_url=ORIGIN, client=("203.0.113.10", 50000)) as remote:
            check(remote.post("/api/session/setup", json=payload, headers={"origin": ORIGIN}), 403, "local_setup_required")

        response = client.post("/api/session/setup", json=payload, headers={"origin": ORIGIN})
        check(response, 200)
        state = response.json()
        assert state["authenticated"] and state["premium_access"] and not state["setup_required"]
        assert state["user"] == {"name": payload["name"]}
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie and "max-age=43200" in cookie
        token = client.cookies.get(local_auth.COOKIE_NAME)
        assert token and local_auth.LocalWorkspaceAuth(Path(RUNTIME.name)).status(token)["authenticated"]
        assert "local_auth.sqlite3" not in client.get("/api/session").text
        with closing(sqlite3.connect(main._LOCAL_AUTH.path)) as connection, connection:
            owner = connection.execute("SELECT salt, password_hash FROM owner").fetchone()
            saved_token = connection.execute("SELECT token_hash FROM sessions").fetchone()[0]
        assert len(owner[0]) == 32 and len(owner[1]) == 32
        assert PASSWORD.encode() not in main._LOCAL_AUTH.path.read_bytes()
        assert token != saved_token and local_auth._token_hash(token) == saved_token
        check(client.post("/api/session/setup", json=payload, headers={"origin": ORIGIN}), 409, "workspace_already_configured")
        check(client.post("/api/export", json=premium), 403, "same_origin_required")
        check(client.post("/api/export", json=premium, headers={"origin": "http://127.0.0.1:9999"}), 403, "same_origin_required")
        client.headers["Origin"] = ORIGIN
        for endpoint in ("/api/export", "/api/preview"):
            check(client.post(endpoint, json=premium), 409, "missing_problems")

        # Anonymous basic conversion retains the existing single-workspace API.
        created = storage.create_problem({"number": "27", "stem": "27. Basic question"})
        assert main._export_problems(main.ExportPayload(ids=[created["id"]]))[0]["number"] == "27"
        try:
            main._export_problems(main.ExportPayload(ids=[created["id"]], workspace="premium"))
        except HTTPException as error:
            assert error.status_code == 401
        else:
            raise AssertionError("Missing request must not authorize premium")

        # A cross-site logout cannot destroy a valid session.
        check(client.post("/api/session/logout", headers={"origin": "https://other.example"}), 403)
        assert client.get("/api/session").json()["authenticated"]
        check(client.post("/api/session/logout", headers={"origin": ORIGIN}), 200)
        assert not main._LOCAL_AUTH.status(token)["authenticated"]
        assert client.get("/api/session").json()["user"] is None
        check(client.post("/api/session/login", json={"password": "incorrect"}, headers={"origin": ORIGIN}), 401, "invalid_password")
        check(client.post("/api/session/login", json={"password": PASSWORD}, headers={"origin": ORIGIN}), 200)
        old_token = client.cookies.get(local_auth.COOKIE_NAME)
        check(client.post("/api/session/login", json={"password": PASSWORD}, headers={"origin": ORIGIN}), 200)
        assert not main._LOCAL_AUTH.status(old_token)["authenticated"], "Login must rotate browser session"
        with closing(sqlite3.connect(main._LOCAL_AUTH.path)) as connection, connection:
            connection.execute("UPDATE sessions SET expires_at = 0")
        assert not client.get("/api/session").json()["authenticated"]
        for _ in range(local_auth.LOGIN_MAX_FAILURES):
            check(client.post("/api/session/login", json={"password": "incorrect"}, headers={"origin": ORIGIN}), 401)
        check(client.post("/api/session/login", json={"password": PASSWORD}, headers={"origin": ORIGIN}), 429, "login_rate_limited")
        with closing(sqlite3.connect(main._LOCAL_AUTH.path)) as connection, connection:
            connection.execute("UPDATE login_failures SET attempted_at = 0")
        check(client.post("/api/session/login", json={"password": PASSWORD}, headers={"origin": ORIGIN}), 200)
    print("PASS setup/login/logout, origin and loopback checks, premium gate, rotation/expiry, KDF storage, throttling")


def verify_setup_race():
    folder = Path(RUNTIME.name) / "race"
    first = local_auth.LocalWorkspaceAuth(folder)
    second = local_auth.LocalWorkspaceAuth(folder)

    def setup(store, name):
        try:
            return 200, store.setup(name, PASSWORD)
        except HTTPException as error:
            return error.status_code, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(setup, first, "First"), pool.submit(setup, second, "Second")]
        results = [call.result() for call in calls]
    assert sorted(result[0] for result in results) == [200, 409], results
    with closing(sqlite3.connect(first.path)) as connection, connection:
        assert connection.execute("SELECT COUNT(*) FROM owner").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    assert not local_auth.LocalWorkspaceAuth(Path(RUNTIME.name) / "separate").status()["authenticated"]
    assert local_auth.LocalWorkspaceAuth(Path(RUNTIME.name) / "separate").status()["setup_required"]
    print("PASS concurrent first-owner setup and separate data-directory isolation")


if __name__ == "__main__":
    try:
        verify_sessions()
        verify_setup_race()
        print("LOCAL_AUTH_OK")
    finally:
        # Legacy storage connections are finalized by GC; release Windows file
        # handles before removing the isolated test workspace.
        gc.collect()
        RUNTIME.cleanup()
