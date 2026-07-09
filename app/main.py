from __future__ import annotations

import re
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (
    collector,
    docx_writer,
    exam_templates,
    hwpx_writer_v2,
    importers,
    pdf_layout_fidelity,
    pdf_layout_writer,
    preview,
    storage,
)


STATIC_DIR = storage.PROJECT_ROOT / "static"


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

app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")
# 데이터 루트(DATA_DIR) 전체를 마운트하면 problems.sqlite3·user_settings.json까지 HTTP로
# 노출된다. 실제 서빙이 필요한 uploads/exports 하위만 개별 마운트한다.
storage.ensure_dirs()
app.mount("/files/uploads", StaticFiles(directory=storage.UPLOAD_DIR), name="files-uploads")
app.mount("/files/exports", StaticFiles(directory=storage.EXPORT_DIR), name="files-exports")


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
    tables: list[list[list[str]]] = Field(default_factory=list)


class ImportPayload(BaseModel):
    kind: Literal["pdf", "image", "csv", "sqlite", "hwp", "hwpx", "docx", "text"]
    filename: str
    data_base64: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PdfLayoutExportPayload(BaseModel):
    filename: str
    data_base64: str
    max_pages: int | None = Field(default=None, ge=1, le=200)
    boxed_passages: bool = True


class TextInputPayload(BaseModel):
    title: str = ""
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_type: Literal["manual", "text"] = "manual"


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
    include_answer_sheet: bool = False
    native_math: bool | None = None


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


def _safe_path_name(value: str, fallback: str = "output") -> str:
    name = re.sub(r"[^0-9A-Za-z가-힣._ -]+", "_", value or fallback).strip(" ._")
    return name[:80] or fallback


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


def _unique_export_dir(parent: Path, dirname: str) -> Path:
    path = parent / dirname
    if not path.exists():
        return path
    for counter in range(2, 1000):
        candidate = parent / f"{dirname}_{counter}"
        if not candidate.exists():
            return candidate
    return path


def _unique_path_in_dir(directory: Path, filename: str) -> Path:
    path = directory / filename
    if not path.exists():
        return path
    for counter in range(2, 1000):
        candidate = directory / f"{path.stem}_{counter}{path.suffix}"
        if not candidate.exists():
            return candidate
    return path


def _export_file_item(path: Path) -> dict[str, Any]:
    stat = path.stat()
    rel_path = path.resolve().relative_to(storage.EXPORT_DIR.resolve()).as_posix()
    return {
        "name": rel_path,
        "display_name": path.name,
        "size": stat.st_size,
        "format": path.suffix.lstrip(".").lower(),
        "url": f"/files/exports/{quote(rel_path, safe='/')}",
    }


def _attach_fidelity_artifact_refs(fidelity: dict[str, Any], render_dir: Path) -> None:
    if not isinstance(fidelity, dict) or not fidelity.get("pages"):
        return
    try:
        artifact_dir = render_dir.resolve().relative_to(storage.EXPORT_DIR.resolve()).as_posix()
    except ValueError:
        return
    fidelity["artifact_dir"] = artifact_dir
    for page in fidelity.get("pages") or []:
        if not isinstance(page, dict):
            continue
        for key in ("source_png", "output_png", "diff_png"):
            name = str(page.get(key) or "")
            if not name:
                continue
            artifact_path = render_dir / name
            if not artifact_path.is_file():
                continue
            page[f"{key}_url"] = _export_file_item(artifact_path)["url"]


def _clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = 0.0
    return round(max(0.0, min(100.0, score)), 2)


def _ratio_score(value: Any) -> float:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        ratio = 0.0
    return _clamp_score(ratio * 100.0)


def _inspect_hwpx_open_safety(path: Path) -> dict[str, Any]:
    try:
        from hwpx.tools.package_validator import validate_editor_open_safety
    except Exception as exc:  # pragma: no cover - vendored validator should be available.
        return {"ok": False, "summary": f"validator unavailable: {exc}", "error": str(exc)}
    try:
        return validate_editor_open_safety(path).to_dict()
    except Exception as exc:  # noqa: BLE001 - recorded as quality evidence.
        return {"ok": False, "summary": f"editor-open safety validation failed: {exc}", "error": str(exc)}


def _pdf_layout_objective_score(
    *,
    stats: dict[str, Any],
    fidelity: dict[str, Any],
    style_profile: dict[str, Any],
    open_safety: dict[str, Any],
) -> dict[str, Any]:
    target = 95.0
    fidelity_available = bool(fidelity.get("available")) and not bool(fidelity.get("skipped"))
    style_available = bool(style_profile.get("available"))
    score_available = fidelity_available and style_available

    font_score = 0.0
    if style_available:
        font_score += 35.0 if style_profile.get("has_required_font_faces") else 0.0
        font_score += 25.0 if style_profile.get("char_metric_ok") else 0.0
        font_score += 20.0 if style_profile.get("font_size_bucket_ok") else 0.0
        font_score += 20.0 if style_profile.get("uses_165_line_spacing") else 0.0

    source_math_segments = int(stats.get("source_math_segments") or 0)
    native_equations = int(stats.get("native_equations") or 0)
    structured_equations = int(style_profile.get("native_equations") or 0)
    native_math_enabled = bool(stats.get("native_math_enabled"))
    math_coverage = float(stats.get("native_math_coverage_ratio") or (1.0 if source_math_segments == 0 else 0.0))

    strict_alignment_score = _ratio_score(fidelity.get("min_strict_alignment_ratio"))
    try:
        overlap_ratio = float(fidelity.get("min_foreground_overlap_ratio") or 0.0)
        overlap_threshold = float(fidelity.get("foreground_overlap_review_threshold") or 0.10)
    except (TypeError, ValueError):
        overlap_ratio = 0.0
        overlap_threshold = 0.10
    overlap_score = _clamp_score((overlap_ratio / max(0.01, overlap_threshold)) * 100.0)
    balance_score = round((strict_alignment_score * 0.7) + (overlap_score * 0.3), 2)
    if fidelity.get("review_flags"):
        balance_score = min(balance_score, 75.0)
    content_visual_score = _ratio_score(fidelity.get("overall_sync_ratio"))
    math_visual_score = round((content_visual_score * 0.75) + (strict_alignment_score * 0.25), 2)
    if native_math_enabled and source_math_segments > 0:
        math_score = _ratio_score(math_coverage)
        if structured_equations < native_equations:
            math_score = min(math_score, 80.0)
    else:
        math_score = math_visual_score

    paging_score = 100.0
    if fidelity.get("page_count_mismatch"):
        paging_score -= 60.0
    if fidelity.get("truncated_by_max_pages") or fidelity.get("limited_by_max_pages"):
        paging_score -= 15.0
    if fidelity.get("aspect_ratio_mismatch_pages"):
        paging_score -= 20.0
    if stats.get("full_page_raster_fallback"):
        paging_score -= 45.0
    paging_score = _clamp_score(paging_score)

    open_safety_score = 100.0 if open_safety.get("ok") else 0.0
    editable_score = _ratio_score(stats.get("editable_text_coverage_ratio"))
    layout_score = _ratio_score(fidelity.get("overall_layout_view_sync_ratio"))

    components = {
        "layout": {
            "score": layout_score,
            "weight": 0.30,
            "layout_view_sync_ratio": fidelity.get("overall_layout_view_sync_ratio"),
            "target_sync_ratio": fidelity.get("target_sync_ratio"),
        },
        "font": {
            "score": _clamp_score(font_score),
            "weight": 0.20,
            "required_font_faces": style_profile.get("required_font_faces") or [],
            "missing_required_font_faces": style_profile.get("missing_required_font_faces") or [],
            "char_metric_ok": bool(style_profile.get("char_metric_ok")),
            "font_size_bucket_ok": bool(style_profile.get("font_size_bucket_ok")),
            "uses_165_line_spacing": bool(style_profile.get("uses_165_line_spacing")),
        },
        "math": {
            "score": _clamp_score(math_score),
            "weight": 0.20,
            "source_math_segments": source_math_segments,
            "native_math_enabled": native_math_enabled,
            "native_equations": native_equations,
            "structured_equations": structured_equations,
            "native_math_coverage_ratio": round(math_coverage, 4),
            "math_visual_score": _clamp_score(math_visual_score),
            "content_visual_sync_ratio": fidelity.get("overall_sync_ratio"),
            "visual_first": not native_math_enabled,
            "not_applicable": source_math_segments == 0,
        },
        "balance": {
            "score": _clamp_score(balance_score),
            "weight": 0.10,
            "min_strict_alignment_ratio": fidelity.get("min_strict_alignment_ratio"),
            "min_foreground_overlap_ratio": fidelity.get("min_foreground_overlap_ratio"),
            "review_flags": fidelity.get("review_flags") or [],
        },
        "paging": {
            "score": paging_score,
            "weight": 0.10,
            "pdf_page_count": fidelity.get("pdf_page_count"),
            "hwpx_page_count": fidelity.get("hwpx_page_count"),
            "page_count_mismatch": bool(fidelity.get("page_count_mismatch")),
            "limited_by_max_pages": bool(fidelity.get("limited_by_max_pages")),
            "full_page_raster_fallback": bool(stats.get("full_page_raster_fallback")),
        },
        "editable_text": {
            "score": editable_score,
            "weight": 0.05,
            "editable_text_coverage_ratio": stats.get("editable_text_coverage_ratio"),
        },
        "open_safety": {
            "score": open_safety_score,
            "weight": 0.05,
            "ok": bool(open_safety.get("ok")),
            "summary": open_safety.get("summary"),
        },
    }
    objective_score = None
    if score_available:
        objective_score = round(
            sum(float(component["score"]) * float(component["weight"]) for component in components.values()),
            2,
        )

    return {
        "objective_score_target": target,
        "objective_score_available": score_available,
        "objective_score": objective_score,
        "meets_objective_score_target": (objective_score >= target if objective_score is not None else None),
        "score_components": components,
        "meets_font_template_target": components["font"]["score"] >= 95.0,
        "meets_native_math_target": (
            source_math_segments == 0 or math_coverage >= 0.95 if native_math_enabled else None
        ),
        "meets_math_visual_sync_target": math_visual_score >= 95.0,
        "meets_paging_target": components["paging"]["score"] >= 95.0,
        "meets_open_safety_target": bool(open_safety.get("ok")),
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


@app.delete("/api/exports/{name:path}")
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
    "text": importers.import_text,
}


@app.post("/api/import")
def import_file(payload: ImportPayload) -> dict[str, Any]:
    try:
        data = importers.decode_base64(payload.data_base64)
        result = IMPORTERS[payload.kind](payload.filename, data, payload.metadata or {})
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
        data = importers.decode_base64(payload.data_base64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF 데이터 디코딩 실패: {exc}") from exc
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="PDF 파일만 원본 레이아웃 HWPX로 만들 수 있습니다.")

    storage.ensure_dirs()
    rel_path = importers.save_upload(payload.filename, data)
    source_path = (storage.DATA_DIR / rel_path).resolve()
    source_stem = _safe_path_name(Path(payload.filename).stem or "PDF", "pdf")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = _unique_export_dir(storage.EXPORT_DIR / "pdf_layout", f"{stamp}_{source_stem}")
    run_dir.mkdir(parents=True, exist_ok=True)
    source_copy = _unique_path_in_dir(run_dir, f"{source_stem}.pdf")
    source_copy.write_bytes(data)
    output_path = _unique_path_in_dir(run_dir, f"{source_stem}_original_layout.hwpx")
    try:
        stats = pdf_layout_writer.write_pdf_layout_hwpx(
            source_path,
            output_path,
            max_pages=payload.max_pages,
            include_images=True,
            include_lines=True,
            text_mode="line",
            native_math=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"PDF 레이아웃 변환 실패: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - PDF/HWPX 변환 오류를 API 오류로 감싼다.
        raise HTTPException(status_code=500, detail=f"PDF 레이아웃 HWPX 생성 중 오류가 발생했습니다: {exc}") from exc

    render_dir = run_dir / "fidelity_renders"
    fidelity = pdf_layout_fidelity.analyze_pdf_hwpx_fidelity(
        source_copy,
        output_path,
        render_dir,
        max_pages=int(stats.get("pages") or 1),
        target_sync_ratio=0.94,
        allow_truncated_by_max_pages=payload.max_pages is not None,
        artifact_mode="failures",
    )
    _attach_fidelity_artifact_refs(fidelity, render_dir)
    style_profile = pdf_layout_writer.inspect_layout_template_profile(output_path)
    open_safety = _inspect_hwpx_open_safety(output_path)
    visual_sync_ratio = fidelity.get("overall_sync_ratio")
    whole_page_visual_sync_ratio = fidelity.get("overall_whole_page_sync_ratio")
    layout_view_sync_ratio = fidelity.get("overall_layout_view_sync_ratio")
    meets_visual_target = (
        bool(fidelity.get("meets_visual_similarity_target")) if fidelity.get("available") else None
    )
    meets_whole_page_visual_target = (
        bool(fidelity.get("meets_whole_page_sync_target")) if fidelity.get("available") else None
    )
    meets_layout_view_target = (
        bool(fidelity.get("meets_layout_view_sync_target")) if fidelity.get("available") else None
    )
    full_page_raster_fallback = bool(stats.get("full_page_raster_fallback"))
    quality = {
        "target_sync_ratio": 0.94,
        "editable_text_coverage_ratio": stats.get("editable_text_coverage_ratio"),
        "meets_editable_text_target": float(stats.get("editable_text_coverage_ratio") or 0.0) >= 0.9,
        "visual_sync_ratio": visual_sync_ratio,
        "whole_page_visual_sync_ratio": whole_page_visual_sync_ratio,
        "layout_view_sync_ratio": layout_view_sync_ratio,
        "meets_visual_sync_target": meets_visual_target,
        "meets_whole_page_sync_target": meets_whole_page_visual_target,
        "meets_layout_view_sync_target": meets_layout_view_target,
        "visual_review_flags": fidelity.get("review_flags") or [],
        "limited_by_max_pages": bool(fidelity.get("limited_by_max_pages")),
        "full_page_raster_fallback": full_page_raster_fallback,
        "full_page_images": int(stats.get("full_page_images") or 0),
        "visual_sync_requires_human_review": True,
    }
    quality.update(
        _pdf_layout_objective_score(
            stats=stats,
            fidelity=fidelity,
            style_profile=style_profile,
            open_safety=open_safety,
        )
    )
    report_path = _unique_path_in_dir(run_dir, "layout_report.json")
    report = {
        "mode": "pdf_coordinate_hwpx",
        "source": {"name": payload.filename, "upload_path": rel_path},
        "export": _export_file_item(output_path),
        "stats": stats,
        "quality": quality,
        "fidelity": fidelity,
        "style_profile": style_profile,
        "open_safety": open_safety,
        "notes": [
            "editable_text_coverage_ratio tracks text-line preservation, not pixel-perfect visual similarity.",
            "layout_view_sync_ratio is the primary 94-point whole-page margin/spacing/scale signal.",
            "objective_score_target is 95 and combines layout, font profile, native math coverage, balance, paging, editable text, and editor-open safety.",
            "whole_page_visual_sync_ratio compares raw full-page luminance and remains a strict renderer-difference diagnostic.",
            "visual_sync_ratio compares rendered PDF and HWPX content crops; foreground_overlap_ratio is a stricter text-position diagnostic.",
            "Use rendered HWPX review or Hancom open check for final acceptance.",
            "API render artifacts are saved for pages below the target; full audit runs may use artifact_mode='all'.",
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "mode": "pdf_coordinate_hwpx",
        "source": {"name": payload.filename, "path": rel_path, "copy": _export_file_item(source_copy)},
        "export": _export_file_item(output_path),
        "run": {
            "folder": run_dir.resolve().relative_to(storage.EXPORT_DIR.resolve()).as_posix(),
            "report": _export_file_item(report_path),
        },
        "stats": stats,
        "quality": quality,
        "fidelity": fidelity,
        "style_profile": style_profile,
        "open_safety": open_safety,
        "notices": ["텍스트는 편집 가능한 문단/표로 넣고, 표·그림 영역만 지역 이미지로 보존했습니다."],
    }


@app.post("/api/import-text")
def import_text(payload: TextInputPayload) -> dict[str, Any]:
    title = payload.title.strip() or "직접 입력"
    filename = f"{title}.txt"
    result = importers.import_text(
        filename,
        payload.text.encode("utf-8"),
        payload.metadata or {},
        source_type=payload.source_type,
    )
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


@app.post("/api/preview")
def preview_export(payload: ExportPayload) -> dict[str, Any]:
    if not preview.available():
        raise HTTPException(status_code=501, detail="미리보기 엔진(rhwp-python)이 설치되어 있지 않습니다.")
    template = exam_templates.get_template(payload.template_key)
    problems = storage.get_problems_by_ids(payload.ids)
    if not problems:
        raise HTTPException(status_code=400, detail="No problems selected")
    title = exam_templates.resolve_export_title(payload.title, template)
    native_math = _effective_native_math(payload, template)
    try:
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
    template = exam_templates.get_template(payload.template_key)
    if payload.template_key and payload.template_key not in exam_templates.TEMPLATE_MAP:
        raise HTTPException(status_code=400, detail="Unknown export template")
    problems = storage.get_problems_by_ids(payload.ids)
    if not problems:
        raise HTTPException(status_code=400, detail="No problems selected")
    storage.ensure_dirs()
    title = exam_templates.resolve_export_title(payload.title, template)
    native_math = _effective_native_math(payload, template)
    path = _unique_export_path(_safe_export_name(title, payload.format))
    filename = path.name
    try:
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
        raise HTTPException(status_code=500, detail=f"내보내기에 실패했습니다: {exc}") from exc
    return FileResponse(path, media_type=media_type, filename=filename)
