"""Pin the narrowed /api/pdf-layout-export lock scope (2026-10-03 speed work).

``_EXPORT_LOCK`` must guard only the time-stamped run directory and file-name
choice.  The writer itself runs outside the lock, so two admitted conversions
can run their writer passes at the same time while still getting distinct run
directories, and a failed run still cleans up after itself.  Runs against an
isolated data directory with a stubbed writer; no server, no private samples.
"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_TEMP = tempfile.TemporaryDirectory(prefix="hwp_make_lock_scope_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = _TEMP.name  # must precede app imports (storage reads it at import)

try:
    import fitz
except Exception:
    print("SKIP: PyMuPDF(fitz) is unavailable")
    raise SystemExit(2)

from fastapi import HTTPException  # noqa: E402

from app import main, storage, pdf_layout_writer  # noqa: E402


def _pdf() -> bytes:
    doc = fitz.open()
    doc.new_page(width=595, height=842).insert_text((72, 100), "1. synthetic", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def main_check() -> int:
    failures: list[str] = []
    if Path(storage.DATA_DIR).resolve() != Path(_TEMP.name).resolve():
        print("SKIP: storage did not pick up the isolated data directory")
        return 2
    records: list[dict] = []
    original = pdf_layout_writer.write_pdf_structured_hwpx

    def stub_writer(source_path, output_path, **kwargs):
        start = time.perf_counter()
        time.sleep(0.4)
        records.append({
            "lock_held": main._EXPORT_LOCK.locked(),
            "run_dir": Path(output_path).parent,
            "run_dir_exists": Path(output_path).parent.is_dir(),
            "source_copy_exists": any(p.suffix == ".pdf" for p in Path(output_path).parent.iterdir()),
            "scoped_assets": storage._SCOPED_UPLOAD_DIR.get(None),
            "start": start, "end": time.perf_counter(),
        })
        raise ValueError("synthetic writer stop")

    pdf_layout_writer.write_pdf_structured_hwpx = stub_writer
    quiet_log = main.user_errors.log_failure
    main.user_errors.log_failure = lambda *args, **kwargs: None  # the synthetic stop is expected
    try:
        payload = main.PdfLayoutExportPayload(
            filename="lock_scope.pdf", data_base64=base64.b64encode(_pdf()).decode("ascii"),
            boxed_passages=True, layout_mode="structured", variant_policy="all", native_math=True,
        )
        statuses: list[int | str] = []

        def worker():
            try:
                main.export_pdf_layout(payload)
                statuses.append("200?")
            except HTTPException as exc:
                statuses.append(exc.status_code)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
    finally:
        pdf_layout_writer.write_pdf_structured_hwpx = original
        main.user_errors.log_failure = quiet_log

    if len(records) != 2:
        failures.append(f"both admitted conversions must reach the writer (got {len(records)})")
    if any(record["lock_held"] for record in records):
        failures.append("_EXPORT_LOCK must not be held while the writer runs")
    if not all(record["run_dir_exists"] and record["source_copy_exists"] for record in records):
        failures.append("run directory and source copy must exist before the writer starts")
    if len({record["run_dir"] for record in records}) != len(records):
        failures.append("concurrent conversions must get distinct run directories")
    if any(record["scoped_assets"] != record["run_dir"] / "assets" for record in records):
        failures.append("asset directory must be scoped to each run (ContextVar) inside the writer")
    if len(records) == 2:
        a, b = sorted(records, key=lambda r: r["start"])
        if b["start"] >= a["end"]:
            failures.append("the second writer pass must overlap the first (it no longer waits for the lock)")
    if sorted(statuses) != [400, 400]:
        failures.append(f"stubbed failures must surface as 400 for both requests, got {statuses}")
    leftovers = list((Path(storage.EXPORT_DIR) / "pdf_layout").glob("*")) if (Path(storage.EXPORT_DIR) / "pdf_layout").is_dir() else []
    if leftovers:
        failures.append(f"failed runs must clean their run directories: {[p.name for p in leftovers]}")
    if main._EXPORT_LOCK.locked():
        failures.append("lock leaked")

    if failures:
        for failure in failures:
            print("FAIL:", failure)
        return 1
    print("PDF export lock scope OK: writer outside the lock, distinct run dirs, overlapping passes, cleanup")
    return 0


if __name__ == "__main__":
    code = main_check()
    _TEMP.cleanup()
    raise SystemExit(code)
