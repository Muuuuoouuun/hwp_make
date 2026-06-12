from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import collector, docx_writer, exam_templates, hwpx_writer, importers, storage


STATIC_DIR = storage.PROJECT_ROOT / "static"

app = FastAPI(title="HWP Make", version="0.1.0")
storage.init_db()

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/files", StaticFiles(directory=storage.DATA_DIR), name="files")


class ProblemPayload(BaseModel):
    source_type: str = "manual"
    source_name: str = ""
    source_page: int | None = None
    number: str = ""
    subject: str = ""
    unit: str = ""
    tags: str = ""
    title: str = ""
    stem: str = ""
    choices: list[str] = Field(default_factory=list)
    answer: str = ""
    explanation: str = ""
    image_paths: list[str] = Field(default_factory=list)


class ImportPayload(BaseModel):
    kind: Literal["pdf", "image", "csv", "sqlite", "hwp", "hwpx", "docx"]
    filename: str
    data_base64: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CollectPayload(BaseModel):
    url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AttachImagePayload(BaseModel):
    filename: str
    data_base64: str


class ExportPayload(BaseModel):
    ids: list[int]
    title: str = exam_templates.DEFAULT_EXPORT_TITLE
    format: Literal["hwpx", "docx"] = "hwpx"
    template_key: str = "basic"


def _safe_export_name(title: str, extension: str) -> str:
    name = re.sub(r"[^0-9A-Za-z가-힣._ -]+", "_", title or "문항 모음").strip()
    name = name[:80] or "문항 모음"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{name}.{extension}"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "data_dir": str(storage.DATA_DIR)}


@app.get("/api/export-templates")
def export_templates() -> dict[str, Any]:
    return {"items": [template.export_option() for template in exam_templates.TEMPLATES]}


@app.get("/api/problems")
def problems(
    q: str = "",
    source_type: str = "",
    subject: str = "",
    tag: str = "",
    limit: int = Query(300, ge=1, le=1000),
) -> dict[str, Any]:
    return {
        "items": storage.list_problems(
            query=q,
            source_type=source_type,
            subject=subject,
            tag=tag,
            limit=limit,
        )
    }


@app.post("/api/problems")
def create_problem(payload: ProblemPayload) -> dict[str, Any]:
    return {"item": storage.create_problem(payload.model_dump())}


@app.put("/api/problems/{problem_id}")
def update_problem(problem_id: int, payload: ProblemPayload) -> dict[str, Any]:
    try:
        return {"item": storage.update_problem(problem_id, payload.model_dump())}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Problem not found") from exc


@app.delete("/api/problems/{problem_id}")
def delete_problem(problem_id: int) -> dict[str, Any]:
    storage.delete_problem(problem_id)
    return {"ok": True}


@app.post("/api/problems/{problem_id}/images")
def attach_image(problem_id: int, payload: AttachImagePayload) -> dict[str, Any]:
    try:
        problem = storage.get_problem(problem_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Problem not found") from exc
    data = importers.decode_base64(payload.data_base64)
    rel_path = importers._save_image_bytes(payload.filename, data)
    if rel_path is None:
        raise HTTPException(status_code=400, detail="이미지 파일이 아닙니다.")
    image_paths = [*problem["image_paths"], rel_path]
    return {"item": storage.update_problem(problem_id, {"image_paths": image_paths})}


IMPORTERS = {
    "pdf": importers.import_pdf,
    "image": importers.import_image,
    "csv": importers.import_csv,
    "sqlite": importers.import_sqlite,
    "hwp": importers.import_hwp,
    "hwpx": importers.import_hwpx,
    "docx": importers.import_docx,
}


@app.post("/api/import")
def import_file(payload: ImportPayload) -> dict[str, Any]:
    data = importers.decode_base64(payload.data_base64)
    result = IMPORTERS[payload.kind](payload.filename, data, payload.metadata or {})
    return {"ok": True, **result}


@app.post("/api/collect")
def collect(payload: CollectPayload) -> dict[str, Any]:
    try:
        result = collector.collect_url(payload.url, payload.metadata or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"수집 실패: {exc}") from exc
    return {"ok": True, **result}


@app.post("/api/export")
def export(payload: ExportPayload) -> FileResponse:
    template = exam_templates.get_template(payload.template_key)
    if payload.template_key and payload.template_key not in exam_templates.TEMPLATE_MAP:
        raise HTTPException(status_code=400, detail="Unknown export template")
    problems = storage.get_problems_by_ids(payload.ids)
    if not problems:
        raise HTTPException(status_code=400, detail="No problems selected")
    storage.ensure_dirs()
    title = exam_templates.resolve_export_title(payload.title, template)
    filename = _safe_export_name(title, payload.format)
    path = storage.EXPORT_DIR / filename
    if payload.format == "docx":
        docx_writer.write_docx(path, title, problems, template.key)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        hwpx_writer.write_hwpx(path, title, problems, template.key)
        media_type = "application/hwp+zip"
    return FileResponse(path, media_type=media_type, filename=filename)
