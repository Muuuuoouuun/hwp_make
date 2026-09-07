"""Offline, single-document worker for the installed Basic desktop edition.

No HTTP listener, premium workspace or provider credentials are exposed.
Every conversion receives a fresh engine database under its private job folder.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

SUPPORTED = {".pdf": "pdf", ".hwp": "hwp", ".hwpx": "hwpx", ".docx": "docx",
             ".txt": "text", ".png": "image", ".jpg": "image", ".jpeg": "image",
             ".bmp": "image", ".tif": "image", ".tiff": "image", ".webp": "image"}
MAX_BYTES = 64 * 1024 * 1024


def validate_source(source: Path) -> str:
    kind = SUPPORTED.get(source.suffix.lower())
    if not kind:
        raise ValueError("지원 형식: PDF, HWP, HWPX, DOCX, TXT, 이미지")
    size = source.stat().st_size
    if not size:
        raise ValueError("빈 파일은 변환할 수 없습니다.")
    if size > MAX_BYTES:
        raise ValueError("64MB 이하의 파일을 선택해 주세요.")
    return kind


def convert(source: Path, destination: Path, job: Path) -> dict:
    source, destination, job = source.resolve(), destination.resolve(), job.resolve()
    kind = validate_source(source)
    fmt = destination.suffix.lower().lstrip(".")
    if fmt not in {"hwpx", "docx"}:
        raise ValueError("저장 형식은 HWPX 또는 DOCX여야 합니다.")
    if source == destination:
        raise ValueError("원본 파일과 다른 이름으로 저장해 주세요.")
    job.mkdir(parents=True, exist_ok=True)
    engine = job / "engine"
    os.environ["HWP_MAKE_DATA_DIR"] = str(engine)
    for key in tuple(os.environ):
        if key.startswith(("OPENAI_", "GEMINI_", "GOOGLE_")) or key == "HWP_MAKE_SETTINGS_DIR":
            os.environ.pop(key, None)
    # Imported only in the dedicated worker, after its data/credential boundary.
    from . import main, storage

    warnings = ["변환한 문서의 수식·그림·배치를 한글 또는 Word에서 확인해 주세요."]
    temporary_output = None
    try:
        encoded = base64.b64encode(source.read_bytes()).decode("ascii")
        if kind == "pdf" and fmt == "hwpx":
            result = main.export_pdf_layout(main.PdfLayoutExportPayload(
                filename=source.name, data_base64=encoded, layout_mode="structured",
                native_math=True, math_ai_recognition=False, variant_policy="all"))
            output = storage.EXPORT_DIR / result["export"]["name"]
            if not output.is_file():
                candidates = list((storage.EXPORT_DIR / result["run"]["folder"]).glob("*.hwpx"))
                if len(candidates) != 1:
                    raise ValueError("생성 파일을 확인할 수 없습니다.")
                output = candidates[0]
            if not result["open_safety"].get("ok"):
                raise ValueError("생성 문서의 구조 검사를 통과하지 못했습니다.")
            count = result["stats"].get("output_problem_count")
            pages = result["scope"]["selected_page_count"]
            warnings.extend(result.get("notices", []))
        else:
            imported = main.import_file(main.ImportPayload(
                kind=kind, filename=source.name, data_base64=encoded,
                metadata={"math_ai_recognition": False, "allow_remote": False}))
            problems = imported.get("created", []) + imported.get("existing", [])
            ids = list(dict.fromkeys(p["id"] for p in problems))
            if not ids:
                raise ValueError("변환할 내용을 찾지 못했습니다. 텍스트가 포함된 파일을 확인해 주세요.")
            response = main.export(main.ExportPayload(
                ids=ids, title=source.stem, format=fmt, native_math=True,
                workspace="basic", numbering_mode="preserve"))
            output = Path(response.path)
            count, pages = len(ids), None
            warnings.extend(imported.get("notices", []))
            warnings.append("문항 내용과 원번호를 기준으로 다시 구성한 문서입니다. 원본 페이지 배치와 다를 수 있습니다.")
        with zipfile.ZipFile(output) as package:
            expected = "Contents/content.hpf" if fmt == "hwpx" else "word/document.xml"
            if package.testzip() is not None or expected not in package.namelist():
                raise ValueError("생성 문서 패키지 검사에 실패했습니다.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".hwpmake-", suffix=".tmp", dir=destination.parent)
        os.close(fd)
        temporary_output = Path(name)
        shutil.copyfile(output, temporary_output)
        os.replace(temporary_output, destination)
        return {"ok": True, "output": str(destination), "source": str(source),
                "pages": pages, "problems": count,
                "warnings": list(dict.fromkeys(str(x) for x in warnings))}
    finally:
        if temporary_output:
            temporary_output.unlink(missing_ok=True)
        # This worker owns only this validated, request-local engine directory.
        if engine.resolve().is_relative_to(job) and engine.name == "engine":
            shutil.rmtree(engine, ignore_errors=True)


def worker(spec_path: Path) -> int:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    try:
        result = convert(Path(spec["source"]), Path(spec["destination"]), spec_path.parent)
    except Exception as exc:
        detail = getattr(exc, "detail", None)
        if isinstance(detail, dict):
            detail = detail.get("message")
        result = {"ok": False, "error": str(detail or exc or "변환하지 못했습니다.")}
    result_path = spec_path.parent / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1
