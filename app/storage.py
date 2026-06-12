from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("HWP_MAKE_DATA_DIR", PROJECT_ROOT / "data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "problems.sqlite3"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS problems (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL DEFAULT 'manual',
                source_name TEXT NOT NULL DEFAULT '',
                source_page INTEGER,
                number TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL DEFAULT '',
                unit TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                stem TEXT NOT NULL DEFAULT '',
                choices_json TEXT NOT NULL DEFAULT '[]',
                answer TEXT NOT NULL DEFAULT '',
                explanation TEXT NOT NULL DEFAULT '',
                image_paths_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_problems_source ON problems(source_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_problems_subject ON problems(subject)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_problems_tags ON problems(tags)")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_list(value: Any) -> str:
    if value is None:
        return "[]"
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return json.dumps(parsed if isinstance(parsed, list) else [value], ensure_ascii=False)
        except json.JSONDecodeError:
            return json.dumps([value], ensure_ascii=False)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps([value], ensure_ascii=False)


def row_to_problem(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["choices"] = json.loads(item.pop("choices_json") or "[]")
    item["image_paths"] = json.loads(item.pop("image_paths_json") or "[]")
    item["image_urls"] = [f"/files/{path}" for path in item["image_paths"]]
    return item


def create_problem(data: dict[str, Any]) -> dict[str, Any]:
    stamp = now_iso()
    values = {
        "source_type": data.get("source_type") or "manual",
        "source_name": data.get("source_name") or "",
        "source_page": data.get("source_page"),
        "number": data.get("number") or "",
        "subject": data.get("subject") or "",
        "unit": data.get("unit") or "",
        "tags": data.get("tags") or "",
        "title": data.get("title") or "",
        "stem": data.get("stem") or "",
        "choices_json": _json_list(data.get("choices")),
        "answer": data.get("answer") or "",
        "explanation": data.get("explanation") or "",
        "image_paths_json": _json_list(data.get("image_paths")),
        "created_at": stamp,
        "updated_at": stamp,
    }
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO problems (
                source_type, source_name, source_page, number, subject, unit, tags,
                title, stem, choices_json, answer, explanation, image_paths_json,
                created_at, updated_at
            )
            VALUES (
                :source_type, :source_name, :source_page, :number, :subject, :unit, :tags,
                :title, :stem, :choices_json, :answer, :explanation, :image_paths_json,
                :created_at, :updated_at
            )
            """,
            values,
        )
        conn.commit()
        return get_problem(int(cursor.lastrowid))


def get_problem(problem_id: int) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM problems WHERE id = ?", (problem_id,)).fetchone()
    if row is None:
        raise KeyError(problem_id)
    return row_to_problem(row)


def update_problem(problem_id: int, data: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "source_type",
        "source_name",
        "source_page",
        "number",
        "subject",
        "unit",
        "tags",
        "title",
        "stem",
        "answer",
        "explanation",
    }
    assignments: list[str] = []
    values: dict[str, Any] = {"id": problem_id, "updated_at": now_iso()}
    for key in allowed:
        if key in data:
            assignments.append(f"{key} = :{key}")
            values[key] = data[key] if data[key] is not None else ""
    if "choices" in data:
        assignments.append("choices_json = :choices_json")
        values["choices_json"] = _json_list(data.get("choices"))
    if "image_paths" in data:
        assignments.append("image_paths_json = :image_paths_json")
        values["image_paths_json"] = _json_list(data.get("image_paths"))
    if not assignments:
        return get_problem(problem_id)
    assignments.append("updated_at = :updated_at")
    with connect() as conn:
        conn.execute(f"UPDATE problems SET {', '.join(assignments)} WHERE id = :id", values)
        conn.commit()
    return get_problem(problem_id)


def delete_problem(problem_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM problems WHERE id = ?", (problem_id,))
        conn.commit()


def list_problems(
    query: str = "",
    source_type: str = "",
    subject: str = "",
    tag: str = "",
    limit: int = 300,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if query:
        like = f"%{query}%"
        where.append(
            "(title LIKE ? OR stem LIKE ? OR source_name LIKE ? OR number LIKE ? OR answer LIKE ?)"
        )
        params.extend([like, like, like, like, like])
    if source_type:
        where.append("source_type = ?")
        params.append(source_type)
    if subject:
        where.append("subject LIKE ?")
        params.append(f"%{subject}%")
    if tag:
        where.append("tags LIKE ?")
        params.append(f"%{tag}%")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM problems {clause} ORDER BY id DESC LIMIT ?",
            [*params, limit],
        ).fetchall()
    return [row_to_problem(row) for row in rows]


def get_problems_by_ids(ids: list[int]) -> list[dict[str, Any]]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    order = {problem_id: index for index, problem_id in enumerate(ids)}
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM problems WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    problems = [row_to_problem(row) for row in rows]
    problems.sort(key=lambda item: order.get(item["id"], 0))
    return problems

