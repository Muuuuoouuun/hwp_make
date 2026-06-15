from __future__ import annotations

import hashlib
import json
import os
import re
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
        # 중복 감지용 콘텐츠 해시 (기존 DB에는 없을 수 있어 마이그레이션한다).
        columns = {row[1] for row in conn.execute("PRAGMA table_info(problems)")}
        if "content_hash" not in columns:
            conn.execute("ALTER TABLE problems ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''")
            for row in conn.execute("SELECT id, stem, choices_json, answer FROM problems").fetchall():
                digest = _content_hash(
                    {
                        "stem": row["stem"],
                        "choices": row["choices_json"],
                        "answer": row["answer"],
                    }
                )
                if digest:
                    conn.execute(
                        "UPDATE problems SET content_hash = ? WHERE id = ?", (digest, row["id"])
                    )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_problems_source ON problems(source_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_problems_subject ON problems(subject)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_problems_tags ON problems(tags)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_problems_hash ON problems(content_hash)")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _as_choice_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return [str(item) for item in parsed] if isinstance(parsed, list) else [value]
    return [str(value)]


def _content_hash(data: dict[str, Any]) -> str:
    """본문·선지·정답을 정규화한 콘텐츠 지문. 식별 텍스트가 없으면 빈 문자열(중복 검사 제외)."""
    parts = [str(data.get("stem") or "")]
    parts.extend(_as_choice_list(data.get("choices")))
    parts.append(str(data.get("answer") or ""))
    normalized = re.sub(r"\s+", " ", "\n".join(parts)).strip().lower()
    if not normalized:
        return ""
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def hash_exists(content_hash: str) -> bool:
    if not content_hash:
        return False
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM problems WHERE content_hash = ? LIMIT 1", (content_hash,)
        ).fetchone()
    return row is not None


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
    item.pop("content_hash", None)
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
        "content_hash": _content_hash(data),
        "created_at": stamp,
        "updated_at": stamp,
    }
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO problems (
                source_type, source_name, source_page, number, subject, unit, tags,
                title, stem, choices_json, answer, explanation, image_paths_json,
                content_hash, created_at, updated_at
            )
            VALUES (
                :source_type, :source_name, :source_page, :number, :subject, :unit, :tags,
                :title, :stem, :choices_json, :answer, :explanation, :image_paths_json,
                :content_hash, :created_at, :updated_at
            )
            """,
            values,
        )
        conn.commit()
        return get_problem(int(cursor.lastrowid))


def create_problem_unique(
    data: dict[str, Any], seen: set[str] | None = None
) -> dict[str, Any] | None:
    """중복(동일 콘텐츠 해시)이면 만들지 않고 None을 돌려준다.

    seen에는 이번 가져오기 안에서 이미 만든 해시를 모아 한 파일 내 중복도 막는다.
    식별 텍스트가 없는(빈 해시) 문항은 항상 새로 만든다(이미지 전용 등)."""
    digest = _content_hash(data)
    if digest:
        if seen is not None and digest in seen:
            return None
        if hash_exists(digest):
            return None
        if seen is not None:
            seen.add(digest)
    return create_problem(data)


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
    if any(key in data for key in ("stem", "choices", "answer")):
        current = get_problem(problem_id)
        assignments.append("content_hash = :content_hash")
        values["content_hash"] = _content_hash(
            {
                "stem": data.get("stem", current["stem"]),
                "choices": data["choices"] if "choices" in data else current["choices"],
                "answer": data.get("answer", current["answer"]),
            }
        )
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


# --- 내보내기 기록 -----------------------------------------------------------


def list_exports() -> list[dict[str, Any]]:
    """data/exports/에 저장된 내보내기 결과를 최신순으로 나열한다."""
    ensure_dirs()
    items: list[dict[str, Any]] = []
    for path in EXPORT_DIR.iterdir():
        if not path.is_file():
            continue
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(
                    timespec="seconds"
                ),
                "modified_ts": stat.st_mtime,
                "format": path.suffix.lstrip(".").lower(),
                "url": f"/files/exports/{path.name}",
            }
        )
    items.sort(key=lambda item: item["modified_ts"], reverse=True)
    for item in items:
        item.pop("modified_ts")
    return items


def delete_export(name: str) -> bool:
    """내보내기 파일을 삭제한다. 경로 탈출을 막고 EXPORT_DIR 직속 파일만 허용한다."""
    if not name or "/" in name or "\\" in name:
        return False
    target = (EXPORT_DIR / name).resolve()
    if target.parent != EXPORT_DIR.resolve() or not target.is_file():
        return False
    target.unlink()
    return True

