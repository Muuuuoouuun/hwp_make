from __future__ import annotations

import io
import json
import re
import threading
import zipfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import collector, docx_writer, exam_templates, hwpx_writer_v2, importers, pdf_layout_writer, preview, storage


STATIC_DIR = storage.PROJECT_ROOT / "static"
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_BASE64_CHARS = ((MAX_UPLOAD_BYTES + 2) // 3) * 4 + 4096
MAX_EXPORT_PROBLEMS = 500
MAX_ARCHIVE_ENTRIES = 5000
MAX_ARCHIVE_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_REQUEST_BODY_BYTES = MAX_BASE64_CHARS + 1_000_000
MAX_METADATA_BYTES = 64 * 1024
_EXPORT_LOCK = threading.Lock()
_CONVERSION_SLOTS = threading.BoundedSemaphore(value=2)


class NoCacheStaticFiles(StaticFiles):
    """정적 UI 파일은 항상 다시 확인하게 한다(앱 업데이트 후 stale JS/CSS 방지)."""

    def is_not_modified(self, response_headers, request_headers) -> bool:
        return False

    async def get_response(self, path: str, scope: Any) -> Any:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


app = FastAPI(title="HWP Make", version="0.1.0")
storage.init_db()


@app.middleware("http")
async def reject_oversized_request(request: Request, call_next: Any) -> Any:
    """Reject ordinary oversized JSON uploads before Pydantic/base64 parsing."""
    declared = request.headers.get("content-length")
    if declared:
        try:
            too_large = int(declared) > MAX_REQUEST_BODY_BYTES
        except ValueError:
            too_large = False
        if too_large:
            return JSONResponse(status_code=413, content={"detail": "요청 본문이 허용 크기를 초과합니다."})
    return await call_next(request)

app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")
# 데이터 루트(DATA_DIR) 전체를 마운트하면 problems.sqlite3·user_settings.json까지 HTTP로
# 노출된다. 실제 서빙이 필요한 uploads/exports 하위만 개별 마운트한다.
storage.ensure_dirs()
app.mount("/files/uploads", StaticFiles(directory=storage.UPLOAD_DIR), name="files-uploads")
app.mount("/files/exports", StaticFiles(directory=storage.EXPORT_DIR), name="files-exports")


class ProblemPayload(BaseModel):
    source_type: str = Field(default="manual", max_length=40)
    source_name: str = Field(default="", max_length=255)
    source_page: int | None = Field(default=None, ge=1, le=10000)
    number: str = Field(default="", max_length=40)
    subject: str = Field(default="", max_length=120)
    unit: str = Field(default="", max_length=200)
    tags: str = Field(default="", max_length=1000)
    title: str = Field(default="", max_length=300)
    stem: str = Field(default="", max_length=2_000_000)
    choices: list[str] = Field(default_factory=list, max_length=100)
    answer: str = Field(default="", max_length=100_000)
    explanation: str = Field(default="", max_length=2_000_000)
    image_paths: list[str] = Field(default_factory=list, max_length=100)
    tables: list[list[list[str]]] = Field(default_factory=list, max_length=100)


class ImportPayload(BaseModel):
    kind: Literal["pdf", "image", "csv", "sqlite", "hwp", "hwpx", "docx", "text"]
    filename: str = Field(min_length=1, max_length=255)
    data_base64: str = Field(min_length=1, max_length=MAX_BASE64_CHARS)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PdfLayoutExportPayload(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    data_base64: str = Field(min_length=1, max_length=MAX_BASE64_CHARS)
    max_pages: int | None = Field(default=None, ge=1, le=200)
    boxed_passages: bool = True


class TextInputPayload(BaseModel):
    title: str = Field(default="", max_length=300)
    text: str = Field(min_length=1, max_length=2_000_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_type: Literal["manual", "text"] = "manual"


class CollectPayload(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AttachImagePayload(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    data_base64: str = Field(min_length=1, max_length=MAX_BASE64_CHARS)


class ExportPayload(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=MAX_EXPORT_PROBLEMS)
    title: str = Field(default=exam_templates.DEFAULT_EXPORT_TITLE, max_length=300)
    format: Literal["hwpx", "docx"] = "hwpx"
    template_key: str = "basic"
    include_answer_sheet: bool = False
    native_math: bool | None = None


def _decode_upload(data_base64: str) -> bytes:
    data = importers.decode_base64(data_base64)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"파일은 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 이하만 처리할 수 있습니다.",
        )
    return data


def _validated_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    value = metadata or {}
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="metadata는 JSON 객체여야 합니다.") from exc
    if len(encoded) > MAX_METADATA_BYTES:
        raise HTTPException(status_code=413, detail="metadata가 허용 크기를 초과합니다.")
    return value


@contextmanager
def _conversion_slot():
    if not _CONVERSION_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="변환 작업이 많습니다. 잠시 후 다시 시도하세요.")
    try:
        yield
    finally:
        _CONVERSION_SLOTS.release()


def _validate_import_signature(kind: str, data: bytes) -> None:
    signatures = {
        "pdf": (b"%PDF",),
        "hwp": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
        "hwpx": (b"PK\x03\x04",),
        "docx": (b"PK\x03\x04",),
        "sqlite": (b"SQLite format 3\x00",),
    }
    allowed = signatures.get(kind)
    if allowed and not any(data.startswith(signature) for signature in allowed):
        raise HTTPException(status_code=400, detail=f"선택한 형식({kind})과 파일 내용이 일치하지 않습니다.")
    if kind in {"hwpx", "docx"}:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                expanded = sum(max(0, item.file_size) for item in entries)
        except (zipfile.BadZipFile, OSError) as exc:
            raise HTTPException(status_code=400, detail=f"손상된 {kind.upper()} 패키지입니다.") from exc
        if len(entries) > MAX_ARCHIVE_ENTRIES or expanded > MAX_ARCHIVE_EXPANDED_BYTES:
            raise HTTPException(status_code=413, detail=f"{kind.upper()} 압축 해제 크기가 허용 범위를 초과합니다.")


def _get_template_or_400(template_key: str) -> exam_templates.ExamTemplate:
    if template_key not in exam_templates.TEMPLATE_MAP:
        raise HTTPException(status_code=400, detail="Unknown export template")
    return exam_templates.get_template(template_key)


def _effective_native_math(payload: ExportPayload, template: exam_templates.ExamTemplate) -> bool:
    if payload.format != "hwpx":
        return False
    if payload.native_math is not None:
        return bool(payload.native_math)
    return bool(template.native_math_default)


def _safe_export_name(title: str, extension: str) -> str:
    name = re.sub(r"[^0-9A-Za-z가-힣._ -]+", "_", title or "문항 모음").strip()
    name = name[:80] or "문항 모음"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{name}.{extension}"


def _unique_export_path(filename: str) -> Path:
    """같은 초에 같은 제목으로 두 번 내보내도 덮어쓰지 않도록 충돌 시 접미사를 붙인다."""
    path = storage.EXPORT_DIR / filename
    if not path.exists():
        return path
    for counter in range(2, 1000):
        candidate = storage.EXPORT_DIR / f"{path.stem}_{counter}{path.suffix}"
        if not candidate.exists():
            return candidate
    return path


def _export_file_item(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "size": stat.st_size,
        "format": path.suffix.lstrip(".").lower(),
        "url": f"/files/exports/{path.name}",
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "data_dir": str(storage.DATA_DIR), "preview_available": preview.available()}


@app.get("/api/export-templates")
def export_templates() -> dict[str, Any]:
    return {"items": [template.export_option() for template in exam_templates.TEMPLATES]}


@app.get("/api/exports")
def list_exports() -> dict[str, Any]:
    return {"items": storage.list_exports()}


@app.delete("/api/exports/{name}")
def delete_export(name: str) -> dict[str, Any]:
    if not storage.delete_export(name):
        raise HTTPException(status_code=404, detail="Export not found")
    return {"ok": True}


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
        return {"item": storage.update_problem(problem_id, payload.model_dump(exclude_unset=True))}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Problem not found") from exc


@app.delete("/api/problems/{problem_id}")
def delete_problem(problem_id: int) -> dict[str, Any]:
    try:
        storage.get_problem(problem_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Problem not found") from exc
    storage.delete_problem(problem_id)
    return {"ok": True}


@app.post("/api/problems/{problem_id}/images")
def attach_image(problem_id: int, payload: AttachImagePayload) -> dict[str, Any]:
    try:
        problem = storage.get_problem(problem_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Problem not found") from exc
    try:
        data = _decode_upload(payload.data_base64)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    "text": importers.import_text,
}


@app.post("/api/import")
def import_file(payload: ImportPayload) -> dict[str, Any]:
    try:
        data = _decode_upload(payload.data_base64)
        _validate_import_signature(payload.kind, data)
        with _conversion_slot():
            result = IMPORTERS[payload.kind](payload.filename, data, _validated_metadata(payload.metadata))
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"가져오기 실패: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - 임포터 라이브러리별 오류를 500으로 감싼다
        raise HTTPException(status_code=500, detail=f"가져오기 중 오류가 발생했습니다: {exc}") from exc
    return {"ok": True, **result}


@app.post("/api/pdf-layout-export")
def export_pdf_layout(payload: PdfLayoutExportPayload) -> dict[str, Any]:
    """Create an editable HWPX that follows the original PDF page layout."""
    try:
        data = _decode_upload(payload.data_base64)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF 데이터 디코딩 실패: {exc}") from exc
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="PDF 파일만 원본 레이아웃 HWPX로 만들 수 있습니다.")

    storage.ensure_dirs()
    rel_path = importers.save_upload(payload.filename, data)
    source_path = (storage.DATA_DIR / rel_path).resolve()
    title = f"{Path(payload.filename).stem or 'PDF'}_원본_레이아웃"
    output_path: Path | None = None
    try:
        with _EXPORT_LOCK:
            output_path = _unique_export_path(_safe_export_name(title, "hwpx"))
            with _conversion_slot():
                stats = pdf_layout_writer.write_pdf_flow_hwpx(
                    source_path,
                    output_path,
                    max_pages=payload.max_pages,
                    boxed_passages=payload.boxed_passages,
                )
    except ValueError as exc:
        if output_path is not None:
            output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"PDF 레이아웃 변환 실패: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - PDF/HWPX 변환 오류를 API 오류로 감싼다.
        if output_path is not None:
            output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"PDF 레이아웃 HWPX 생성 중 오류가 발생했습니다: {exc}") from exc

    assert output_path is not None

    return {
        "ok": True,
        "mode": "pdf_flow_hwpx",
        "source": {"name": payload.filename, "path": rel_path},
        "export": _export_file_item(output_path),
        "stats": stats,
        "notices": ["텍스트는 편집 가능한 문단/표로 넣고, 표·그림 영역만 지역 이미지로 보존했습니다."],
    }


@app.post("/api/import-text")
def import_text(payload: TextInputPayload) -> dict[str, Any]:
    title = payload.title.strip() or "직접 입력"
    filename = f"{title}.txt"
    result = importers.import_text(
        filename,
        payload.text.encode("utf-8"),
        _validated_metadata(payload.metadata),
        source_type=payload.source_type,
    )
    return {"ok": True, **result}


@app.post("/api/collect")
def collect(payload: CollectPayload) -> dict[str, Any]:
    try:
        result = collector.collect_url(payload.url, _validated_metadata(payload.metadata))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"수집 실패: {exc}") from exc
    return {"ok": True, **result}


@app.post("/api/preview")
def preview_export(payload: ExportPayload) -> dict[str, Any]:
    if not preview.available():
        raise HTTPException(status_code=501, detail="미리보기 엔진(rhwp-python)이 설치되어 있지 않습니다.")
    template = _get_template_or_400(payload.template_key)
    problems = storage.get_problems_by_ids(payload.ids)
    if not problems:
        raise HTTPException(status_code=400, detail="No problems selected")
    title = exam_templates.resolve_export_title(payload.title, template)
    native_math = _effective_native_math(payload, template)
    try:
        with _conversion_slot():
            result = preview.render_preview(
                title,
                problems,
                template.key,
                include_answer_sheet=payload.include_answer_sheet,
                native_math=native_math,
            )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"미리보기 실패: {exc}") from exc
    if template.columns > 1:
        result["note"] = "미리보기 엔진이 다단 배치를 아직 1단으로 보여줍니다. 실제 한글에서는 설정된 단 수로 표시됩니다."
    return result


@app.post("/api/export")
def export(payload: ExportPayload) -> FileResponse:
    template = _get_template_or_400(payload.template_key)
    problems = storage.get_problems_by_ids(payload.ids)
    if not problems:
        raise HTTPException(status_code=400, detail="No problems selected")
    storage.ensure_dirs()
    title = exam_templates.resolve_export_title(payload.title, template)
    native_math = _effective_native_math(payload, template)
    path: Path | None = None
    try:
        # 이름 선정부터 writer 완료까지 직렬화해 같은 초의 동시 변환이 서로의
        # 산출물을 덮어쓰지 않게 한다. 로컬 문서 변환은 원래 CPU-bound라 이 제한이
        # 메모리 급증과 SQLite/파일 경합도 함께 막는다.
        with _EXPORT_LOCK:
            path = _unique_export_path(_safe_export_name(title, payload.format))
            filename = path.name
            with _conversion_slot():
                if payload.format == "docx":
                    docx_writer.write_docx(
                        path, title, problems, template.key, include_answer_sheet=payload.include_answer_sheet
                    )
                    media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                else:
                    # v2(vendored python-hwpx) 만 실제 한컴에서 열린다. v1(hwpx_writer)은 version.xml
                    # 등 패키지 스켈레톤이 비표준이라 한컴이 "파일 손상"으로 거부한다(실제 뷰어 확인).
                    hwpx_writer_v2.write_hwpx(
                        path,
                        title,
                        problems,
                        template.key,
                        include_answer_sheet=payload.include_answer_sheet,
                        native_math=native_math,
                    )
                    media_type = "application/hwp+zip"
    except Exception as exc:  # noqa: BLE001 - 작성기 오류를 500으로 감싼다
        if path is not None:
            path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"내보내기에 실패했습니다: {exc}") from exc
    return FileResponse(path, media_type=media_type, filename=filename)
