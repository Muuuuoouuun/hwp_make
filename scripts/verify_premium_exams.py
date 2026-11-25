"""Saved premium exams: owner isolation, revision conflicts, validation and the local API."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="hwp-premium-exams-", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main
from app.premium_exams import ExamConflict, ExamDraft, ExamNotFound, ExamStore, ExamUpdate

ORIGIN = "http://127.0.0.1"
SAME = {"origin": ORIGIN}


def check(response, status, code=None):
    assert response.status_code == status, (response.status_code, response.text)
    if code:
        assert response.json()["detail"]["code"] == code, response.text
    return response.json()


def verify_store():
    store = ExamStore(Path(RUNTIME.name) / "store-only.sqlite3")
    draft = ExamDraft(title="  복습 1  ", items=[{"id": 27, "label": "원본 27"}, {"id": 5}],
                      numbering_mode="sequential", start_number=21)
    exam = store.create("alice", draft)
    assert exam["title"] == "복습 1" and exam["revision"] == 1 and [i["id"] for i in exam["items"]] == [27, 5]
    assert exam["start_number"] == 21 and "expected_revision" not in exam

    # Another owner sees nothing and cannot read, write, copy or delete.
    assert store.list_exams("bob") == []
    for call in (lambda: store.get("bob", exam["id"]), lambda: store.delete("bob", exam["id"]),
                 lambda: store.duplicate("bob", exam["id"]),
                 lambda: store.update("bob", exam["id"], ExamUpdate(expected_revision=1))):
        try:
            call()
        except ExamNotFound:
            pass
        else:
            raise AssertionError("cross-owner access must look like a missing exam")

    moved = store.update("alice", exam["id"], ExamUpdate(
        **{**draft.model_dump(), "items": [{"id": 5}, {"id": 27}]}, expected_revision=1))
    assert moved["revision"] == 2 and [i["id"] for i in moved["items"]] == [5, 27]
    try:
        store.update("alice", exam["id"], ExamUpdate(**draft.model_dump(), expected_revision=1))
    except ExamConflict as conflict:
        assert conflict.current["revision"] == 2 and [i["id"] for i in conflict.current["items"]] == [5, 27]
    else:
        raise AssertionError("stale revision must conflict, not overwrite")
    assert store.get("alice", exam["id"])["revision"] == 2

    copy = store.duplicate("alice", exam["id"])
    assert copy["id"] != exam["id"] and copy["title"] == "복습 1 (복사본)" and copy["revision"] == 1
    assert [i["id"] for i in copy["items"]] == [5, 27]
    summaries = store.list_exams("alice")
    assert [s["id"] for s in summaries] == [copy["id"], exam["id"]], "newest first"
    assert summaries[1]["item_count"] == 2 and "items" not in summaries[1]
    store.delete("alice", copy["id"])
    assert [s["id"] for s in store.list_exams("alice")] == [exam["id"]]

    for bad in ({"items": [{"id": 1}, {"id": 1}]}, {"start_number": 0}, {"start_number": 1000},
                {"start_number": "3"}, {"numbering_mode": "random"}, {"items": [{"id": 0}]},
                {"title": "x" * 301}, {"format": "pdf"}, {"items": [{"id": i} for i in range(1, 502)]}):
        try:
            ExamDraft(**bad)
        except ValidationError:
            pass
        else:
            raise AssertionError(f"invalid draft accepted: {list(bad)}")
    assert ExamDraft(title="   ").title == "새 시험지"
    print("PASS store: owner isolation, revision conflict, duplicate, delete, validation")


def verify_api():
    with TestClient(main.app, base_url=ORIGIN, client=("127.0.0.1", 50000)) as client:
        check(client.get("/api/exams"), 401, "login_required")
        check(client.post("/api/exams", json={}, headers=SAME), 401, "login_required")
        check(client.post("/api/session/setup", json={"name": "Owner", "password": "isolated-exam-password"},
                          headers=SAME), 200)
        check(client.post("/api/exams", json={}), 403, "same_origin_required")
        check(client.post("/api/exams", json={"items": [{"id": 1}, {"id": 1}]}, headers=SAME), 422)

        exam = check(client.post("/api/exams", json={"title": "중간 대비", "items": [{"id": 12}, {"id": 27}]},
                                 headers=SAME), 201)
        assert exam["numbering_mode"] == "sequential" and exam["start_number"] == 1
        assert check(client.get("/api/exams"), 200)["exams"][0]["id"] == exam["id"]
        assert check(client.get(f"/api/exams/{exam['id']}"), 200) == exam

        body = {**exam, "items": [{"id": 27}, {"id": 12}], "start_number": 21, "expected_revision": 1}
        check(client.put(f"/api/exams/{exam['id']}", json=body), 403, "same_origin_required")
        saved = check(client.put(f"/api/exams/{exam['id']}", json=body, headers=SAME), 200)
        assert saved["revision"] == 2 and saved["start_number"] == 21
        conflict = check(client.put(f"/api/exams/{exam['id']}", json=body, headers=SAME), 409, "exam_conflict")
        assert conflict["detail"]["exam"]["revision"] == 2 and conflict["detail"]["message"]

        copy = check(client.post(f"/api/exams/{exam['id']}/duplicate", headers=SAME), 201)
        assert copy["title"] == "중간 대비 (복사본)" and copy["start_number"] == 21
        check(client.delete(f"/api/exams/{copy['id']}", headers=SAME), 200)
        for request in (lambda: client.get(f"/api/exams/{copy['id']}"),
                        lambda: client.delete(f"/api/exams/{copy['id']}", headers=SAME),
                        lambda: client.post("/api/exams/nope/duplicate", headers=SAME),
                        lambda: client.put("/api/exams/nope", json=body, headers=SAME)):
            check(request(), 404, "exam_not_found")

        check(client.post("/api/session/logout", headers=SAME), 200)
        check(client.get(f"/api/exams/{exam['id']}"), 401, "login_required")
    print("PASS api: login, same-origin writes, 201/200/404/409/422 contract")


if __name__ == "__main__":
    verify_store()
    verify_api()
    print("PREMIUM_EXAMS_OK")
