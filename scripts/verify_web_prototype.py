"""Behavioral checks using isolated accounts, files and the actual converter.

Run: python -m pytest scripts/verify_web_prototype.py -q
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import fitz
import pytest
from fastapi.testclient import TestClient

from app.web_main import create_app
from app.web_store import Store
from app.web_worker import Worker

ORIGIN = "http://127.0.0.1:8788"
HEADERS = {"X-HWP-Request": "1", "Origin": ORIGIN}
PASSWORD = "test-password-only-2026"


@pytest.fixture
def env(tmp_path):
    app = create_app(tmp_path, worker_enabled=False, origin=ORIGIN)
    store = app.state.store
    alice = store.create_user("alice@example.test", "Alice", PASSWORD)
    bob = store.create_user("bob@example.test", "Bob", PASSWORD)
    clients = []
    for user in (alice, bob):
        client = TestClient(app, base_url=ORIGIN, headers=HEADERS)
        client.cookies.set("hwp_session", store.session(user["id"]))
        clients.append(client)
    yield store, clients[0], clients[1], alice, bob
    for client in clients:
        client.close()


def submit(
    client,
    name="questions.txt",
    content=b"1. What is 2 + 2?\n1) 3\n2) 4\n3) 5",
    fmt="hwpx",
    key="request-0001",
):
    return client.post(
        "/api/jobs",
        files={"file": (name, content)},
        data={"output_format": fmt},
        headers={"Idempotency-Key": key},
    )


def pdf_bytes(pages=1):
    with fitz.open() as doc:
        for n in range(pages):
            page = doc.new_page()
            page.insert_text((60, 90), f"{n + 1}. What is 2 + 2?", fontsize=12)
            page.insert_text((60, 120), "1) 3    2) 4    3) 5", fontsize=12)
        return doc.tobytes()


def test_setup_and_session(tmp_path):
    app = create_app(tmp_path, worker_enabled=False, origin=ORIGIN)
    store = app.state.store
    token = store.bootstrap()
    with TestClient(app, base_url=ORIGIN, headers=HEADERS) as client:
        body = {
            "name": "Teacher",
            "email": "teacher@example.test",
            "password": PASSWORD,
            "token": token,
        }
        assert client.get("/api/me").status_code == 401
        result = client.post("/api/setup", json=body)
        assert result.status_code == 200
        assert "HttpOnly" in result.headers["set-cookie"]
        assert "SameSite=strict" in result.headers["set-cookie"]
        assert PASSWORD not in result.text and token not in result.text
        assert client.post("/api/setup", json=body).status_code == 400
        assert client.get("/api/me").json()["user"]["name"] == "Teacher"
        assert client.post("/api/logout").status_code == 200
        assert client.get("/api/me").status_code == 401
        result = client.post(
            "/api/login", json={"email": body["email"], "password": PASSWORD}
        )
        assert result.status_code == 200
        assert (
            client.post(
                "/api/login",
                json={"email": body["email"], "password": "wrong-password"},
            ).status_code
            == 401
        )
        bad = client.post("/api/login", json={"email": "invalid", "password": "secret"})
        assert bad.status_code == 422 and "secret" not in bad.text
        assert store.bootstrap() is None


def test_private_boundaries_and_csrf(env):
    store, alice, bob, *_ = env
    response = submit(alice)
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]["id"]
    assert len(alice.get("/api/jobs").json()["items"]) == 1
    assert bob.get("/api/jobs").json()["items"] == []
    for suffix in ("", "/download", "/download?source=true"):
        assert bob.get(f"/api/jobs/{job_id}{suffix}").status_code == 404
    for action in ("cancel", "retry"):
        assert (
            bob.post(
                f"/api/jobs/{job_id}/{action}",
                headers={"Idempotency-Key": "retry-test-key"},
            ).status_code
            == 404
        )
    assert bob.delete(f"/api/jobs/{job_id}").status_code == 404
    assert alice.get(f"/api/jobs/{job_id}/download?source=true").status_code == 200
    assert (
        alice.post(
            f"/api/jobs/{job_id}/cancel", headers={"Origin": "https://attacker.invalid"}
        ).status_code
        == 403
    )
    assert alice.post("/api/logout", headers={"X-HWP-Request": ""}).status_code == 403
    assert alice.get("/", headers={"Host": "attacker.invalid"}).status_code == 400
    for path in (
        "/files/uploads/source",
        "/files/exports/output.hwpx",
        "/api/ai/settings",
        "/api/problems",
        "/api/export",
        "/docs",
    ):
        assert alice.get(path).status_code == 404
    assert "data_dir" not in alice.get("/api/health").text


def test_idempotency_limits_and_retry(env):
    store, alice, *_ = env
    first = submit(alice).json()["job"]
    same = submit(alice)
    assert same.status_code == 202 and same.json()["job"]["id"] == first["id"]
    assert len(list((store.root / "jobs").iterdir())) == 1
    assert submit(alice, content=b"other content").status_code == 409
    assert (
        alice.post(
            f"/api/jobs/{first['id']}/retry",
            headers={"Idempotency-Key": "bad-retry-key"},
        ).status_code
        == 409
    )
    assert (
        alice.post(f"/api/jobs/{first['id']}/cancel").json()["job"]["state"]
        == "cancelled"
    )
    retry = alice.post(
        f"/api/jobs/{first['id']}/retry", headers={"Idempotency-Key": "valid-retry-key"}
    )
    assert retry.status_code == 202
    assert retry.json()["job"]["id"] != first["id"]
    assert submit(alice, key="request-0002").status_code == 202
    assert submit(alice, key="request-0003").status_code == 202
    assert submit(alice, key="request-0004").status_code == 429
    assert alice.get("/api/jobs?status=active").json()["total"] == 3
    assert alice.get("/api/jobs?status=succeeded").json()["items"] == []


def test_invalid_files_cleaned(env):
    store, alice, *_ = env
    assert submit(alice, name="bad.pdf", content=b"not PDF").status_code == 400
    assert submit(alice, name="unsafe.html", content=b"<script>").status_code == 400
    assert submit(alice, content=b"").status_code == 400
    assert submit(alice, name="long.pdf", content=pdf_bytes(51)).status_code == 413
    oversized = alice.post(
        "/api/jobs", content=b"", headers={"Content-Length": str(22 * 1024 * 1024)}
    )
    assert oversized.status_code == 413
    assert not list((store.root / "jobs").iterdir())


def test_streamed_body_limit(env):
    store, alice, *_ = env

    def chunks():
        yield b'--test-boundary\r\nContent-Disposition: form-data; name="file"; filename="large.txt"\r\nContent-Type: text/plain\r\n\r\n'
        for _ in range(22):
            yield b"x" * (1024 * 1024)
        yield b"\r\n--test-boundary--\r\n"

    response = alice.post(
        "/api/jobs",
        content=chunks(),
        headers={
            "Content-Type": "multipart/form-data; boundary=test-boundary",
            "Idempotency-Key": "streamed-body-key",
        },
    )
    assert response.status_code == 413
    assert not list((store.root / "jobs").iterdir())


def test_claim_cancellation_and_stale_worker(env):
    store, alice, _, user, _ = env
    first = submit(alice).json()["job"]
    submit(alice, key="request-0002")
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: store.claim(), range(4)))
    assert sum(job is not None for job in claims) == 1
    old = next(job for job in claims if job)
    with store.connect() as db:
        db.execute("UPDATE jobs SET lease=0 WHERE id=?", (old["id"],))
    new = store.claim()
    assert new["id"] == old["id"] and new["attempt"] != old["attempt"]
    assert not store.finish(old["id"], old["attempt"], "succeeded", {"warnings": []})
    cancelled = alice.post(f"/api/jobs/{first['id']}/cancel")
    assert cancelled.json()["job"]["state"] == "cancel_requested"
    assert not store.finish(new["id"], new["attempt"], "succeeded", {"warnings": []})
    assert store.get(user["id"], new["id"])["state"] == "cancelled"
    assert alice.get(f"/api/jobs/{first['id']}/download").status_code == 409


@pytest.mark.parametrize(
    "kind,fmt", [("text", "hwpx"), ("text", "docx"), ("pdf", "hwpx")]
)
def test_actual_conversion_and_delete(env, kind, fmt):
    store, alice, bob, user, _ = env
    response = submit(
        alice,
        name="exam.pdf" if kind == "pdf" else "questions.txt",
        content=pdf_bytes()
        if kind == "pdf"
        else b"1. What is 2 + 2?\n1) 3\n2) 4\n3) 5",
        fmt=fmt,
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]["id"]
    worker = Worker(store)
    worker.run(store.claim())
    job = store.get(user["id"], job_id)
    assert job["state"] == "succeeded", job["error"]
    result = alice.get(f"/api/jobs/{job_id}/download")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        assert archive.testzip() is None
        assert (
            "word/document.xml" if fmt == "docx" else "Contents/content.hpf"
        ) in archive.namelist()
    assert bob.get(f"/api/jobs/{job_id}/download").status_code == 404
    assert json.loads(job["result"])["warnings"]
    assert alice.delete(f"/api/jobs/{job_id}").status_code == 200
    assert alice.get(f"/api/jobs/{job_id}/download").status_code == 404
    assert not store.job_dir(job_id).exists()


def test_timeout_and_restart_queue(env):
    store, alice, _, user, _ = env
    job_id = submit(alice).json()["job"]["id"]
    job = store.claim()
    worker = Worker(store, timeout=0)
    worker.run(job)
    assert store.get(user["id"], job_id)["state"] == "failed"
    assert not (store.job_dir(job_id) / job["attempt"]).exists()
    retry = alice.post(
        f"/api/jobs/{job_id}/retry", headers={"Idempotency-Key": "restart-retry-key"}
    ).json()["job"]
    # A fresh application/store sees the same queued work; no in-memory future.
    restarted = Store(store.root)
    assert restarted.get(user["id"], retry["id"])["state"] == "queued"
    claim = restarted.claim()
    stopped = Worker(restarted)
    stopped.stop.set()
    stopped.run(claim)
    assert restarted.get(user["id"], retry["id"])["state"] == "queued"


def test_retention(env):
    store, alice, _, user, _ = env
    job_id = submit(alice).json()["job"]["id"]
    with store.connect() as db:
        db.execute(
            "UPDATE jobs SET created=? WHERE id=?", (time.time() - 31 * 86400, job_id)
        )
    Worker(store).sweep()
    assert store.get(user["id"], job_id) is not None  # queued uploads survive
    store.cancel(user["id"], job_id)
    Worker(store).sweep()
    assert store.get(user["id"], job_id) is None
    assert not store.job_dir(job_id).exists()


def report_payload(**changes):
    return {
        "title": "수식 잘림",
        "category": "conversion",
        "description": "3번 문항의 수식 아래쪽이 잘립니다.",
        "steps": "파일을 변환한 뒤 한글에서 열기",
        "expected": "전체 수식이 보여야 합니다.",
        "browser": "Synthetic QA Browser",
        "viewport": {"width": 390, "height": 844},
        **changes,
    }


def test_report_receipt_isolation_and_operator_reply(env):
    store, alice, bob, owner, _ = env
    job_id = submit(alice).json()["job"]["id"]
    response = alice.post(
        "/api/bug-reports",
        json=report_payload(job_id=job_id),
        headers={"Idempotency-Key": "report-request-01"},
    )
    assert response.status_code == 201, response.text
    report = response.json()["report"]
    assert report["status"] == "submitted" and report["id"].startswith("BUG-")
    assert report["context"]["job"]["state"] == "queued"
    assert "filename" not in report["context"]["job"]
    assert "source" not in json.dumps(report["context"])
    assert alice.get("/api/bug-reports").json()["total"] == 1
    assert bob.get("/api/bug-reports").json()["items"] == []
    assert bob.get(f"/api/bug-reports/{report['id']}").status_code == 404
    assert (
        bob.post(
            "/api/bug-reports",
            json=report_payload(job_id=job_id),
            headers={"Idempotency-Key": "report-request-02"},
        ).status_code
        == 404
    )
    assert (
        alice.patch(
            f"/api/bug-reports/{report['id']}", json={"status": "resolved"}
        ).status_code
        == 405
    )
    assert store.update_report(report["id"], "investigating", "재현하여 확인 중입니다.")
    updated = alice.get(f"/api/bug-reports/{report['id']}").json()["report"]
    assert (
        updated["status"] == "investigating"
        and updated["reply"] == "재현하여 확인 중입니다."
    )
    alice.post(f"/api/jobs/{job_id}/cancel")
    alice.delete(f"/api/jobs/{job_id}")
    assert (
        store.report(owner["id"], report["id"])["context"]["job"]["state"] == "queued"
    )


def test_report_idempotency_validation_and_auth(env):
    store, alice, *_ = env
    payload = report_payload()
    headers = {"Idempotency-Key": "report-request-01"}
    first = alice.post("/api/bug-reports", json=payload, headers=headers)
    same = alice.post("/api/bug-reports", json=payload, headers=headers)
    assert first.json()["report"]["id"] == same.json()["report"]["id"]
    assert (
        alice.post(
            "/api/bug-reports",
            json=report_payload(title="변경된 내용"),
            headers=headers,
        ).status_code
        == 409
    )
    for bad in (
        report_payload(title="  "),
        report_payload(description="짧음"),
        report_payload(description="x" * 6001),
        report_payload(context={"cookies": "secret"}),
        report_payload(viewport={"width": -1, "height": 100}),
    ):
        result = alice.post("/api/bug-reports", json=bad, headers=headers)
        assert result.status_code == 422 and "secret" not in result.text
    assert (
        alice.post(
            "/api/bug-reports",
            json=payload,
            headers={**headers, "Origin": "https://attacker.invalid"},
        ).status_code
        == 403
    )
    alice.post("/api/logout")
    assert alice.get("/api/bug-reports").status_code == 401
    assert (
        alice.post("/api/bug-reports", json=payload, headers=headers).status_code == 401
    )


def test_report_rate_limit_and_persistence(env):
    store, alice, _, owner, _ = env
    for index in range(20):
        result = alice.post(
            "/api/bug-reports",
            json=report_payload(),
            headers={"Idempotency-Key": f"report-request-{index:02}"},
        )
        assert result.status_code == 201
    assert (
        alice.post(
            "/api/bug-reports",
            json=report_payload(),
            headers={"Idempotency-Key": "report-request-20"},
        ).status_code
        == 429
    )
    assert (
        alice.post(
            "/api/bug-reports",
            json=report_payload(),
            headers={"Idempotency-Key": "report-request-00"},
        ).status_code
        == 201
    )
    assert Store(store.root).reports(owner["id"])["total"] == 20
