"""Read-only-to-product audit probes; all application writes use a fresh TEMP dir.

Run from the repository root: python docs/audits/2026-09-05/conversion-probes.py
These describe current behavior, not desired regression assertions.
"""
from pathlib import Path
import base64
import json
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sandbox = tempfile.TemporaryDirectory(prefix="hwpmake_conversion_audit_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = sandbox.name

from app import main, storage
from fastapi.testclient import TestClient

results = {}
with TestClient(main.app, raise_server_exceptions=False) as client:
    problem = storage.create_problem({"stem": "An audit fixture", "source_name": "audit.txt"})
    busy = []
    for _ in range(2):
        main._CONVERSION_SLOTS.acquire()
    try:
        for route, body in [
            ("/api/export", {"ids": [problem["id"]], "format": "docx"}),
            ("/api/preview", {"ids": [problem["id"]]}),
            ("/api/pdf-layout-export", {"filename": "audit.pdf", "data_base64": base64.b64encode(b"%PDF-1.7\n").decode()}),
        ]:
            response = client.post(route, json=body)
            busy.append({"route": route, "status": response.status_code, "body": response.json()})
    finally:
        for _ in range(2):
            main._CONVERSION_SLOTS.release()
    results["busy_slots"] = busy
    results["uploads_after_rejected_busy_pdf"] = [p.name for p in storage.UPLOAD_DIR.iterdir()]
    response = client.post("/api/export", json={"ids": [problem["id"], 999999], "format": "docx"})
    results["missing_id_export"] = {
        "status": response.status_code,
        "requested_ids": [problem["id"], 999999],
        "resolved_ids": [p["id"] for p in storage.get_problems_by_ids([problem["id"], 999999])],
        "output_bytes": len(response.content),
    }
    rows = []
    for filename, csv_text in [
        ("case_math.csv", "number,stem\n1,Find f(x)\n2,Find f(X)\n"),
        ("different_source.csv", "number,stem\n1,Find f(x)\n"),
        ("different_source.csv", "number,stem\n1,Find f(x)\n"),
    ]:
        response = client.post("/api/import", json={
            "kind": "csv", "filename": filename,
            "data_base64": base64.b64encode(csv_text.encode()).decode(),
        })
        body = response.json()
        rows.append({
            "filename": filename, "status": response.status_code,
            "created": [{k: p[k] for k in ("id", "number", "stem")} for p in body.get("created", [])],
            "existing": [{k: p[k] for k in ("id", "number", "stem")} for p in body.get("existing", [])],
            "notices": body.get("notices"),
        })
    results["case_and_source_dedup"] = rows
print(json.dumps(results, ensure_ascii=False, indent=2))
