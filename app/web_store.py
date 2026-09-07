"""Isolated, single-host prototype accounts and durable conversion queue.

This module deliberately never imports app.storage: the user's local library
must not become the web application's database or public file directory.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(
    os.environ.get(
        "HWP_WEB_DATA_DIR",
        Path(__file__).resolve().parents[1] / "data" / "web_prototype",
    )
).resolve()
MAX_FILE = 20 * 1024 * 1024
MAX_STORAGE = 500 * 1024 * 1024
ACTIVE = ("queued", "running", "validating", "cancel_requested")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 600_000
    ).hex()
    return f"{salt}:{key}"


def password_matches(password: str, stored: str) -> bool:
    return hmac.compare_digest(password_hash(password, stored.split(":")[0]), stored)


class Store:
    def __init__(self, root: Path = ROOT):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "jobs").mkdir(exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL, password TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
                    request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    filename TEXT NOT NULL, kind TEXT NOT NULL, format TEXT NOT NULL,
                    input_size INTEGER NOT NULL, output_size INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL DEFAULT 'queued', created REAL NOT NULL, updated REAL NOT NULL,
                    attempt TEXT, lease REAL, tries INTEGER NOT NULL DEFAULT 0,
                    result TEXT, error TEXT, deleted INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(owner_id, request_key));
                CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner_id, created DESC);
                CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(state, created);
                CREATE TABLE IF NOT EXISTS bug_reports (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
                    request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    title TEXT NOT NULL, category TEXT NOT NULL, description TEXT NOT NULL,
                    steps TEXT NOT NULL, expected TEXT NOT NULL, job_id TEXT,
                    context TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'submitted',
                    reply TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL,
                    UNIQUE(owner_id, request_key));
                CREATE INDEX IF NOT EXISTS reports_owner ON bug_reports(owner_id, created DESC);
            """)

    def create_report(self, owner: str, key: str, payload: dict) -> dict:
        fingerprint = digest(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM bug_reports WHERE owner_id=? AND request_key=?",
                (owner, key),
            ).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise ValueError(
                        "신고 내용이 변경되었습니다. 새 접수 키로 다시 제출해 주세요."
                    )
                return self.public_report(dict(existing))
            job_context = None
            if payload.get("job_id"):
                job = db.execute(
                    "SELECT * FROM jobs WHERE id=? AND owner_id=? AND deleted=0",
                    (payload["job_id"], owner),
                ).fetchone()
                if not job:
                    raise LookupError("연결할 작업을 찾을 수 없습니다.")
                # Snapshot survives job deletion without retaining files or engine paths.
                job_context = {
                    k: job[k] for k in ("id", "kind", "format", "state", "error")
                }
            count = db.execute(
                "SELECT count(*) FROM bug_reports WHERE owner_id=? AND created>?",
                (owner, now - 86400),
            ).fetchone()[0]
            if count >= 20:
                raise OverflowError(
                    "하루 신고 한도(20건)에 도달했습니다. 내 신고에서 접수 내역을 확인해 주세요."
                )
            context = {
                "app_version": "web-prototype-1",
                "job": job_context,
                "browser": payload["browser"],
                "viewport": payload["viewport"],
            }
            report_id = "BUG-" + secrets.token_hex(8).upper()
            db.execute(
                """INSERT INTO bug_reports
                (id,owner_id,request_key,fingerprint,title,category,description,steps,expected,job_id,context,created,updated)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    report_id,
                    owner,
                    key,
                    fingerprint,
                    payload["title"],
                    payload["category"],
                    payload["description"],
                    payload["steps"],
                    payload["expected"],
                    payload.get("job_id"),
                    json.dumps(context, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            return self.public_report(
                dict(
                    db.execute(
                        "SELECT * FROM bug_reports WHERE id=?", (report_id,)
                    ).fetchone()
                )
            )

    @staticmethod
    def public_report(row: dict) -> dict:
        return {
            **{
                key: row[key]
                for key in (
                    "id",
                    "title",
                    "category",
                    "description",
                    "steps",
                    "expected",
                    "job_id",
                    "status",
                    "reply",
                    "created",
                    "updated",
                )
            },
            "context": json.loads(row["context"]),
        }

    def reports(self, owner: str) -> dict:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM bug_reports WHERE owner_id=? ORDER BY created DESC LIMIT 50",
                (owner,),
            ).fetchall()
            total = db.execute(
                "SELECT count(*) FROM bug_reports WHERE owner_id=?", (owner,)
            ).fetchone()[0]
        return {
            "items": [self.public_report(dict(row)) for row in rows],
            "total": total,
        }

    def report(self, owner: str, report_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM bug_reports WHERE id=? AND owner_id=?",
                (report_id, owner),
            ).fetchone()
        return self.public_report(dict(row)) if row else None

    def update_report(self, report_id: str, status: str, reply: str) -> bool:
        """Local operator CLI only; never exposed as a user API."""
        if (
            status not in {"submitted", "investigating", "resolved"}
            or len(reply) > 4000
        ):
            raise ValueError("처리 상태 또는 답변 길이를 확인해 주세요.")
        with self.connect() as db:
            changed = db.execute(
                "UPDATE bug_reports SET status=?,reply=?,updated=? WHERE id=?",
                (status, reply, time.time(), report_id),
            ).rowcount
        return bool(changed)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "web.sqlite3", timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def bootstrap(self) -> str | None:
        """Only the local launcher receives this one-use setup credential."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                return None
            token = secrets.token_urlsafe(32)
            db.execute(
                "INSERT OR REPLACE INTO settings VALUES ('bootstrap', ?)",
                (digest(token),),
            )
            return token

    def create_user(
        self, email: str, name: str, password: str, bootstrap: str | None = None
    ) -> dict:
        encoded = password_hash(password)
        user_id = secrets.token_hex(16)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if bootstrap is not None:
                expected = db.execute(
                    "SELECT value FROM settings WHERE key='bootstrap'"
                ).fetchone()
                if (
                    not expected
                    or not hmac.compare_digest(expected[0], digest(bootstrap))
                    or db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
                ):
                    raise ValueError(
                        "초기 설정 링크가 만료되었습니다. 실행기를 다시 시작해 주세요."
                    )
            db.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                (user_id, email.lower(), name, encoded, time.time()),
            )
            db.execute("DELETE FROM settings WHERE key='bootstrap'")
        return {"id": user_id, "email": email.lower(), "name": name}

    def login(self, email: str, password: str) -> dict | None:
        with self.connect() as db:
            user = db.execute(
                "SELECT * FROM users WHERE email=?", (email.lower(),)
            ).fetchone()
        # Equal-cost unknown account lookup, without a reusable default account.
        encoded = user["password"] if user else ("00" * 16 + ":" + "00" * 32)
        if not password_matches(password, encoded) or user is None:
            return None
        return {key: user[key] for key in ("id", "email", "name")}

    def rate_limit(self, bucket: str, limit: int = 12, seconds: int = 900) -> bool:
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM attempts WHERE expires < ?", (now,))
            row = db.execute(
                "SELECT count FROM attempts WHERE bucket=?", (bucket,)
            ).fetchone()
            if row and row[0] >= limit:
                return False
            db.execute(
                "INSERT INTO attempts VALUES (?,1,?) ON CONFLICT(bucket) DO UPDATE SET count=count+1",
                (bucket, now + seconds),
            )
        return True

    def session(self, owner: str) -> str:
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            db.execute(
                "INSERT INTO sessions VALUES (?,?,?)",
                (digest(token), owner, time.time() + 86400),
            )
        return token

    def authenticate(self, token: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT u.id,u.email,u.name FROM sessions s JOIN users u ON u.id=s.owner_id WHERE s.token=? AND s.expires>?",
                (digest(token), time.time()),
            ).fetchone()
        return dict(row) if row else None

    def logout(self, token: str):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (digest(token),))

    def job_dir(self, job_id: str) -> Path:
        # IDs come from our DB, but containment is also enforced at the boundary.
        path = (self.root / "jobs" / job_id).resolve()
        if path.parent != self.root / "jobs":
            raise ValueError("Invalid job path")
        return path

    def enqueue(
        self,
        owner: str,
        key: str,
        fingerprint: str,
        job_id: str,
        filename: str,
        kind: str,
        output_format: str,
        size: int,
    ) -> tuple[dict, bool]:
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM jobs WHERE owner_id=? AND request_key=?", (owner, key)
            ).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint or existing["deleted"]:
                    raise ValueError(
                        "이미 사용한 접수 키입니다. 새 작업으로 다시 접수해 주세요."
                    )
                return dict(existing), False
            active = db.execute(
                "SELECT count(*) FROM jobs WHERE owner_id=? AND state IN ('queued','running','validating','cancel_requested')",
                (owner,),
            ).fetchone()[0]
            queued = db.execute(
                "SELECT count(*) FROM jobs WHERE state='queued'"
            ).fetchone()[0]
            daily = db.execute(
                "SELECT count(*) FROM jobs WHERE owner_id=? AND created>? AND state NOT IN ('failed','cancelled')",
                (owner, now - 86400),
            ).fetchone()[0]
            usage = db.execute(
                "SELECT coalesce(sum(input_size+output_size),0) FROM jobs WHERE owner_id=? AND deleted=0",
                (owner,),
            ).fetchone()[0]
            if active >= 3 or queued >= 20 or daily >= 10:
                raise OverflowError(
                    "접수 한도에 도달했습니다. 진행 중 작업이 끝난 뒤 다시 시도해 주세요."
                )
            if usage + size > MAX_STORAGE:
                raise OverflowError(
                    "보관 용량이 부족합니다. 이전 작업을 삭제해 주세요."
                )
            db.execute(
                "INSERT INTO jobs(id,owner_id,request_key,fingerprint,filename,kind,format,input_size,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    owner,
                    key,
                    fingerprint,
                    filename,
                    kind,
                    output_format,
                    size,
                    now,
                    now,
                ),
            )
            return dict(
                db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            ), True

    def list_jobs(self, owner: str, offset: int = 0, status: str = "all") -> dict:
        clause = (
            " AND state IN ('queued','running','validating','cancel_requested')"
            if status == "active"
            else " AND state='succeeded'"
            if status == "succeeded"
            else ""
        )
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM jobs WHERE owner_id=? AND deleted=0"
                + clause
                + " ORDER BY created DESC LIMIT 50 OFFSET ?",
                (owner, offset),
            ).fetchall()
            total = db.execute(
                "SELECT count(*) FROM jobs WHERE owner_id=? AND deleted=0" + clause,
                (owner,),
            ).fetchone()[0]
        return {"items": [self.public(dict(row)) for row in rows], "total": total}

    def get(self, owner: str, job_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE id=? AND owner_id=? AND deleted=0",
                (job_id, owner),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def public(row: dict) -> dict:
        return {
            **{
                key: row[key]
                for key in (
                    "id",
                    "filename",
                    "format",
                    "input_size",
                    "state",
                    "created",
                    "updated",
                    "error",
                )
            },
            "result": json.loads(row["result"]) if row["result"] else None,
        }

    def cancel(self, owner: str, job_id: str) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state FROM jobs WHERE id=? AND owner_id=? AND deleted=0",
                (job_id, owner),
            ).fetchone()
            if not row:
                return False
            if row[0] in ACTIVE:
                state = "cancelled" if row[0] == "queued" else "cancel_requested"
                db.execute(
                    "UPDATE jobs SET state=?,updated=? WHERE id=?",
                    (state, time.time(), job_id),
                )
        return True

    def mark_deleted(self, owner: str, job_id: str) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state FROM jobs WHERE id=? AND owner_id=? AND deleted=0",
                (job_id, owner),
            ).fetchone()
            if not row:
                return False
            if row[0] in ACTIVE:
                raise ValueError("작업 취소가 완료된 뒤 삭제할 수 있습니다.")
            db.execute(
                "UPDATE jobs SET deleted=1,updated=? WHERE id=?", (time.time(), job_id)
            )
        return True

    def claim(self) -> dict | None:
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Late processes cannot publish: finish() also compares attempt IDs.
            db.execute(
                "UPDATE jobs SET state='cancelled',updated=? WHERE state='cancel_requested' AND lease<?",
                (now, now),
            )
            db.execute(
                "UPDATE jobs SET state=CASE WHEN tries<2 THEN 'queued' ELSE 'failed' END,error=CASE WHEN tries<2 THEN NULL ELSE '작업 실행기가 중단되었습니다. 파일을 다시 접수해 주세요.' END,updated=? WHERE state IN ('running','validating') AND lease<?",
                (now, now),
            )
            if db.execute(
                "SELECT 1 FROM jobs WHERE state IN ('running','validating','cancel_requested') LIMIT 1"
            ).fetchone():
                return None  # Prototype: one worker slot across all processes.
            row = db.execute(
                "SELECT * FROM jobs WHERE state='queued' AND deleted=0 ORDER BY created LIMIT 1"
            ).fetchone()
            if not row:
                return None
            attempt = secrets.token_hex(16)
            db.execute(
                "UPDATE jobs SET state='running',attempt=?,lease=?,tries=tries+1,updated=? WHERE id=?",
                (attempt, now + 30, now, row["id"]),
            )
            return dict(
                db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
            )

    def heartbeat(
        self, job_id: str, attempt: str, validating: bool = False
    ) -> str | None:
        with self.connect() as db:
            # Do not overwrite a concurrent cancellation between read and update.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state FROM jobs WHERE id=? AND attempt=?", (job_id, attempt)
            ).fetchone()
            if not row or row[0] not in ACTIVE:
                return None
            state = "validating" if validating and row[0] == "running" else row[0]
            db.execute(
                "UPDATE jobs SET state=?,lease=?,updated=? WHERE id=? AND attempt=?",
                (state, time.time() + 30, time.time(), job_id, attempt),
            )
        return state

    def finish(
        self,
        job_id: str,
        attempt: str,
        state: str,
        result: dict | None = None,
        error: str | None = None,
        size: int = 0,
    ) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT * FROM jobs WHERE id=? AND attempt=? AND state IN ('running','validating','cancel_requested')",
                (job_id, attempt),
            ).fetchone()
            if not current:
                return False
            if current["state"] == "cancel_requested":
                state, result, error, size = "cancelled", None, None, 0
            if state == "succeeded":
                used = db.execute(
                    "SELECT coalesce(sum(input_size+output_size),0) FROM jobs WHERE owner_id=? AND deleted=0",
                    (current["owner_id"],),
                ).fetchone()[0]
                if used + size > MAX_STORAGE:
                    state, result, error, size = (
                        "failed",
                        None,
                        "결과를 보관할 용량이 부족합니다. 이전 작업을 삭제해 주세요.",
                        0,
                    )
            db.execute(
                "UPDATE jobs SET state=?,result=?,error=?,output_size=?,lease=NULL,updated=? WHERE id=? AND attempt=?",
                (
                    state,
                    json.dumps(result, ensure_ascii=False) if result else None,
                    error,
                    size,
                    time.time(),
                    job_id,
                    attempt,
                ),
            )
        return state == "succeeded"
