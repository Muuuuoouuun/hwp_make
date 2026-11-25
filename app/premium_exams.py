"""Saved premium exam drafts, scoped by owner and guarded by a revision number.

The store holds only the composition (ordered problem references and output
settings), never problem content: exports still resolve problems at generation
time. It has no web/local dependency so the local app (owner "local") and a
future web server (owner = account id) can share it. Another owner's exam is
indistinguishable from a missing one.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Literal
import uuid

from pydantic import BaseModel, Field, field_validator


MAX_ITEMS = 500  # Same bound as app.main.MAX_EXPORT_PROBLEMS.


class ExamItem(BaseModel):
    id: int = Field(ge=1)
    label: str = Field(default="", max_length=200)


class ExamDraft(BaseModel):
    title: str = Field(default="새 시험지", max_length=300)
    items: list[ExamItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    numbering_mode: Literal["preserve", "sequential"] = "sequential"
    start_number: int = Field(default=1, ge=1, le=999, strict=True)
    template_key: str = Field(default="basic", max_length=80)
    format: Literal["hwpx", "docx", "hwp"] = "hwpx"
    include_answer_sheet: bool = False

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return value.strip() or "새 시험지"

    @field_validator("items")
    @classmethod
    def _unique(cls, items: list[ExamItem]) -> list[ExamItem]:
        if len({item.id for item in items}) != len(items):
            raise ValueError("같은 문항은 한 시험지에 한 번만 담을 수 있습니다.")
        return items


class ExamUpdate(ExamDraft):
    expected_revision: int = Field(ge=1, strict=True)


class ExamNotFound(LookupError):
    pass


class ExamConflict(Exception):
    def __init__(self, current: dict[str, Any]):
        super().__init__("exam revision conflict")
        self.current = current


class ExamStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS exams (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    data TEXT NOT NULL
                )
            """)
            connection.execute("CREATE INDEX IF NOT EXISTS idx_exams_owner ON exams(owner_id, updated_at)")

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "title": row["title"], "revision": row["revision"],
                "created_at": row["created_at"], "updated_at": row["updated_at"], **json.loads(row["data"])}

    @staticmethod
    def _data(draft: ExamDraft) -> str:
        return json.dumps(draft.model_dump(include=set(ExamDraft.model_fields) - {"title"}), ensure_ascii=False)

    def _row(self, connection: sqlite3.Connection, owner_id: str, exam_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM exams WHERE id = ? AND owner_id = ?", (exam_id, owner_id)).fetchone()
        if row is None:
            raise ExamNotFound(exam_id)
        return row

    def list_exams(self, owner_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM exams WHERE owner_id = ? ORDER BY updated_at DESC", (owner_id,)).fetchall()
        summaries = []
        for row in rows:
            exam = self._public(row)
            summaries.append({key: exam[key] for key in (
                "id", "title", "revision", "updated_at", "numbering_mode", "start_number")}
                | {"item_count": len(exam["items"])})
        return summaries

    def get(self, owner_id: str, exam_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            return self._public(self._row(connection, owner_id, exam_id))

    def create(self, owner_id: str, draft: ExamDraft) -> dict[str, Any]:
        now = time.time()
        exam_id = uuid.uuid4().hex
        with self._connection() as connection:
            connection.execute("INSERT INTO exams VALUES (?, ?, ?, 1, ?, ?, ?)",
                               (exam_id, owner_id, draft.title, now, now, self._data(draft)))
            return self._public(self._row(connection, owner_id, exam_id))

    def update(self, owner_id: str, exam_id: str, update: ExamUpdate) -> dict[str, Any]:
        with self._connection() as connection:
            # One write transaction: the revision check and the write cannot interleave
            # with another tab's save.
            connection.execute("BEGIN IMMEDIATE")
            row = self._row(connection, owner_id, exam_id)
            if row["revision"] != update.expected_revision:
                raise ExamConflict(self._public(row))
            connection.execute(
                "UPDATE exams SET title = ?, revision = revision + 1, updated_at = ?, data = ? WHERE id = ?",
                (update.title, time.time(), self._data(update), exam_id))
            return self._public(self._row(connection, owner_id, exam_id))

    def delete(self, owner_id: str, exam_id: str) -> None:
        with self._connection() as connection:
            if not connection.execute("DELETE FROM exams WHERE id = ? AND owner_id = ?", (exam_id, owner_id)).rowcount:
                raise ExamNotFound(exam_id)

    def duplicate(self, owner_id: str, exam_id: str) -> dict[str, Any]:
        source = self.get(owner_id, exam_id)
        draft = ExamDraft.model_validate({**source, "title": f"{source['title']} (복사본)"[:300]})
        return self.create(owner_id, draft)
