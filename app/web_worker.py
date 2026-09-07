"""Durable SQLite queue supervisor for the single-host web prototype."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .web_store import Store


class Worker:
    def __init__(self, store: Store, timeout: float = 1200):
        self.store = store
        self.timeout = timeout
        self.stop = threading.Event()
        self.thread = threading.Thread(
            target=self.loop, name="hwp-conversion-worker", daemon=True
        )

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=10)

    def loop(self):
        while not self.stop.is_set():
            try:
                self.sweep()
                job = self.store.claim()
                if job:
                    self.run(job)
                    continue
            except Exception:
                # A transient DB failure must not silently kill the supervisor.
                import logging

                logging.getLogger(__name__).exception("Conversion supervisor failure")
            self.stop.wait(1)

    def sweep(self):
        now = time.time()
        with self.store.connect() as db:
            # Prototype has no persistent problem bank; entire job expiry is safe.
            db.execute(
                "UPDATE jobs SET deleted=1 WHERE deleted=0 AND state NOT IN ('queued','running','validating','cancel_requested') AND created<?",
                (now - 30 * 86400,),
            )
            deleted = [
                row[0] for row in db.execute("SELECT id FROM jobs WHERE deleted=1")
            ]
            known = {row[0] for row in db.execute("SELECT id FROM jobs")}
        for job_id in deleted:
            shutil.rmtree(self.store.job_dir(job_id), ignore_errors=True)
        for path in (self.store.root / "jobs").iterdir():
            if (
                path.is_dir()
                and path.name not in known
                and path.stat().st_mtime < now - 86400
            ):
                shutil.rmtree(path, ignore_errors=True)

    def run(self, job: dict):
        folder = self.store.job_dir(job["id"])
        attempt_dir = folder / job["attempt"]
        attempt_dir.mkdir(parents=True, exist_ok=True)
        # Previous attempts are unreachable and cannot be served by the API.
        (attempt_dir / "spec.json").write_text(
            json.dumps(
                {
                    "source": str(folder / "source"),
                    "filename": job["filename"],
                    "kind": job["kind"],
                    "format": job["format"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        environment = dict(os.environ)
        environment["HWP_MAKE_DATA_DIR"] = str(attempt_dir / "engine")
        process = None
        succeeded = False
        try:
            with (attempt_dir / "worker.log").open("wb") as log:
                process = subprocess.Popen(
                    [sys.executable, "-m", "app.web_convert", str(attempt_dir)],
                    cwd=str(Path(__file__).resolve().parents[1]),
                    env=environment,
                    stdout=log,
                    stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                started = time.monotonic()
                while process.poll() is None:
                    state = self.store.heartbeat(
                        job["id"], job["attempt"], (attempt_dir / "validating").exists()
                    )
                    if (
                        state in (None, "cancel_requested")
                        or self.stop.is_set()
                        or time.monotonic() - started > self.timeout
                    ):
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                        if state == "cancel_requested":
                            self.store.finish(job["id"], job["attempt"], "cancelled")
                        elif self.stop.is_set():
                            # Graceful shutdown returns to queue, preserving the upload.
                            with self.store.connect() as db:
                                db.execute(
                                    "UPDATE jobs SET state=CASE WHEN state='cancel_requested' THEN 'cancelled' ELSE 'queued' END,lease=NULL,updated=? WHERE id=? AND attempt=? AND state IN ('running','validating','cancel_requested')",
                                    (time.time(), job["id"], job["attempt"]),
                                )
                        elif state is not None:
                            self.store.finish(
                                job["id"],
                                job["attempt"],
                                "failed",
                                error="처리 제한 시간을 초과했습니다. 더 작은 파일로 다시 시도해 주세요.",
                            )
                        return
                    self.stop.wait(0.5)
            if process.returncode != 0:
                self.store.finish(
                    job["id"],
                    job["attempt"],
                    "failed",
                    error="문서를 변환하지 못했습니다. 파일의 텍스트·암호 설정과 형식을 확인해 주세요.",
                )
                return
            result = json.loads(
                (attempt_dir / "result.json").read_text(encoding="utf-8")
            )
            output = attempt_dir / f"output.{job['format']}"
            shutil.rmtree(attempt_dir / "engine", ignore_errors=True)
            succeeded = self.store.finish(
                job["id"],
                job["attempt"],
                "succeeded",
                result=result,
                size=output.stat().st_size,
            )
        except Exception:
            self.store.finish(
                job["id"],
                job["attempt"],
                "failed",
                error="작업 실행 중 문제가 발생했습니다. 파일을 다시 접수해 주세요.",
            )
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if not succeeded:
                shutil.rmtree(attempt_dir, ignore_errors=True)
