"""Problem-library pagination and detail-route regression checks."""

from __future__ import annotations

import gc
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME_DIR = tempfile.TemporaryDirectory(prefix="hwpmake_pagination_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME_DIR.name

from fastapi.testclient import TestClient  # noqa: E402

from app import main, storage  # noqa: E402


def main_check() -> int:
    storage.init_db()
    for index in range(205):
        storage.create_problem({"title": f"page-item-{index:03d}", "stem": f"unique stem {index}"})

    with TestClient(main.app) as client:
        first = client.get("/api/problems", params={"limit": 100, "offset": 0})
        second = client.get("/api/problems", params={"limit": 100, "offset": 100})
        last = client.get("/api/problems", params={"limit": 100, "offset": 200})
        assert first.status_code == second.status_code == last.status_code == 200
        pages = [response.json() for response in (first, second, last)]
        assert [len(page["items"]) for page in pages] == [100, 100, 5]
        assert all(page["total"] == 205 for page in pages)
        assert [page["has_more"] for page in pages] == [True, True, False]
        ids = [item["id"] for page in pages for item in page["items"]]
        assert len(ids) == len(set(ids)) == 205
        detail = client.get(f"/api/problems/{ids[0]}")
        assert detail.status_code == 200 and detail.json()["item"]["id"] == ids[0]

    try:
        with storage.connect() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode=DELETE")
    except Exception:
        pass
    gc.collect()
    print("Problem pagination OK (205 rows -> 100/100/5, total + has_more + detail)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main_check())
    finally:
        RUNTIME_DIR.cleanup()
