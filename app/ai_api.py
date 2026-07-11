"""Safe HTTP integration points for the existing AI, OCR, and math helpers.

The provider modules intentionally remain usable without FastAPI.  This router
only adds the small, sanitized contract needed by the local browser UI: key
status/update, capability discovery, deterministic math inspection, and an
explicit OCR action.  Raw provider keys are never returned.
"""
from __future__ import annotations

import base64
import binascii
import io
import os
import re
import uuid
import warnings
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from . import math_text, pdf_math_ai, storage
from .recognition import ocr_backend, reconstruct, settings


router = APIRouter(prefix="/api/ai", tags=["ai"])

_MAX_KEY_LENGTH = 512
_MAX_TEXT_LENGTH = 200_000
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_MAX_IMAGE_PIXELS = 25_000_000


class _StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AISettingsPayload(_StrictPayload):
    gemini_api_key: str | None = Field(default=None, alias="geminiApiKey", max_length=_MAX_KEY_LENGTH)
    openai_api_key: str | None = Field(default=None, alias="openAiApiKey", max_length=_MAX_KEY_LENGTH)


class MathAnalyzePayload(_StrictPayload):
    text: str = Field(min_length=1, max_length=_MAX_TEXT_LENGTH)


_ShortText = Annotated[str, Field(max_length=500)]
_LongText = Annotated[str, Field(max_length=_MAX_TEXT_LENGTH)]
_ChoiceText = Annotated[str, Field(max_length=20_000)]


class ProblemReviewPayload(_StrictPayload):
    number: _ShortText = ""
    subject: _ShortText = ""
    unit: _ShortText = ""
    tags: _ShortText = ""
    title: _ShortText = ""
    stem: _LongText = ""
    choices: list[_ChoiceText] = Field(default_factory=list, max_length=20)
    answer: _ShortText = ""
    explanation: _LongText = ""


class OCRPayload(_StrictPayload):
    filename: str = Field(default="image.png", max_length=200)
    data_base64: str = Field(alias="dataBase64", min_length=1, max_length=14_100_000)
    backend: Literal["auto", "gemini", "tesseract", "paddleocr", "none"] = "auto"
    model: str | None = Field(default=None, max_length=120)
    allow_remote: bool = Field(default=False, alias="allowRemote")


class ReconstructImagePayload(_StrictPayload):
    filename: str = Field(default="problem.png", max_length=200)
    data_base64: str = Field(alias="dataBase64", min_length=1, max_length=14_100_000)
    provider: Literal["gemini", "openai"] = "gemini"
    model: str | None = Field(default=None, max_length=120)
    prompt: str | None = Field(default=None, max_length=8_000)
    quality: str = Field(default=reconstruct.DEFAULT_IMAGE_QUALITY, max_length=40)
    size: str = Field(default=reconstruct.DEFAULT_IMAGE_SIZE, max_length=40)
    transparent_background: bool = Field(default=True, alias="transparentBackground")
    sharpen: bool = True
    allow_remote: bool = Field(default=False, alias="allowRemote")


def initialize_ai_runtime() -> dict[str, str]:
    """Apply stored provider keys without overriding shell-managed secrets."""
    return settings.apply_to_env(settings.load_user_settings(), overwrite=False)


def _ocr_capabilities(has_gemini_key: bool) -> dict[str, Any]:
    paddle_available = ocr_backend.PaddleOCR is not None
    tesseract_available = ocr_backend._tesseract_binary_available()
    if has_gemini_key:
        selected = "gemini"
    elif paddle_available:
        selected = "paddleocr"
    elif tesseract_available:
        selected = "tesseract"
    else:
        selected = "none"
    return {
        "available": selected != "none",
        "autoBackend": selected,
        "backends": {
            "gemini": {"available": has_gemini_key, "remote": True},
            "paddleocr": {"available": paddle_available, "remote": False},
            "tesseract": {"available": tesseract_available, "remote": False},
            "none": {"available": True, "remote": False},
        },
    }


def _status_payload() -> dict[str, Any]:
    key_status = settings.summarize_for_response()
    has_gemini = bool(key_status["hasGeminiApiKey"])
    has_openai = bool(key_status["hasOpenAiApiKey"])
    return {
        "ok": True,
        "settings": key_status,
        "features": {
            "mathAnalysis": {"available": True, "remote": False},
            "mathRecognition": {
                "available": has_gemini,
                "remote": True,
                "provider": "gemini",
                "defaultModel": pdf_math_ai.resolve_math_ai_model(),
                "maxCallsPerExport": pdf_math_ai.resolve_math_ai_max_calls(),
                "enabledByDefault": pdf_math_ai.resolve_math_ai_enabled(),
            },
            "ocr": _ocr_capabilities(has_gemini),
            "imageReconstruction": {
                "available": has_gemini or has_openai,
                "remote": True,
                "providers": {
                    "gemini": {
                        "available": has_gemini,
                        "defaultModel": reconstruct.DEFAULT_GEMINI_IMAGE_MODEL,
                    },
                    "openai": {
                        "available": has_openai,
                        "defaultModel": reconstruct.DEFAULT_OPENAI_IMAGE_MODEL,
                    },
                },
            },
        },
    }


@router.get("/status")
def ai_status() -> dict[str, Any]:
    return _status_payload()


@router.get("/settings")
def get_ai_settings() -> dict[str, Any]:
    return {"ok": True, "settings": settings.summarize_for_response()}


@router.put("/settings")
def update_ai_settings(payload: AISettingsPayload) -> dict[str, Any]:
    supplied = payload.model_fields_set
    if not supplied:
        raise HTTPException(status_code=400, detail="Provide at least one API key field")
    key_status = settings.update_api_keys(
        None,
        gemini_api_key=payload.gemini_api_key if "gemini_api_key" in supplied else None,
        openai_api_key=payload.openai_api_key if "openai_api_key" in supplied else None,
    )
    return {"ok": True, "settings": key_status, "features": _status_payload()["features"]}


@router.post("/math/analyze")
def analyze_math(payload: MathAnalyzePayload) -> dict[str, Any]:
    normalized = math_text.normalize_recognized_math_layout_text(payload.text)
    spans = [span.to_dict() for span in math_text.extract_math_spans(normalized)]
    return {
        "ok": True,
        "normalizedText": normalized,
        "spans": spans,
        "summary": math_text.summarize_math_spans(spans),
    }


_CHOICE_LABEL_RE = re.compile(r"^\s*(?:(?P<number>[1-9]\d*)[.)]|(?P<circled>[①②③④⑤⑥⑦⑧⑨⑩]))\s*")
_CIRCLED_CHOICE_VALUES = {char: index for index, char in enumerate("①②③④⑤⑥⑦⑧⑨⑩", start=1)}
_ANSWER_NUMBER_RE = re.compile(r"(?<!\d)([1-9]\d*)(?!\d)")
_EXCESS_BLANK_LINES_RE = re.compile(r"\n[ \t]*\n[ \t]*\n")
_MULTISPACE_RE = re.compile(r"(?<!\n)[ \t]{2,}")


def _review_finding(
    severity: Literal["error", "warning", "info"],
    title: str,
    detail: str,
    field: str,
    suggestion: str | None = None,
) -> dict[str, str]:
    finding = {"severity": severity, "title": title, "detail": detail, "field": field}
    if suggestion:
        finding["suggestion"] = suggestion
    return finding


def _choice_label(choice: str) -> int | None:
    match = _CHOICE_LABEL_RE.match(str(choice or ""))
    if not match:
        return None
    if match.group("number"):
        return int(match.group("number"))
    return _CIRCLED_CHOICE_VALUES.get(match.group("circled"))


def _choice_content(choice: str) -> str:
    return _CHOICE_LABEL_RE.sub("", str(choice or ""), count=1).strip()


def _normalized_duplicate_key(choice: str) -> str:
    return re.sub(r"\s+", "", _choice_content(choice)).casefold()


def _answer_numbers(answer: str) -> list[int]:
    values = [int(value) for value in _ANSWER_NUMBER_RE.findall(str(answer or ""))]
    values.extend(_CIRCLED_CHOICE_VALUES[char] for char in answer if char in _CIRCLED_CHOICE_VALUES)
    return list(dict.fromkeys(values))


def _math_structure_issues(value: str) -> list[str]:
    text = str(value or "")
    issues: list[str] = []
    if len(re.findall(r"(?<!\\)\$", text)) % 2:
        issues.append("$ 수식 구분자의 짝이 맞지 않습니다.")
    if text.count(r"\(") != text.count(r"\)"):
        issues.append(r"\( ... \) 수식 구분자의 짝이 맞지 않습니다.")
    if text.count(r"\[") != text.count(r"\]"):
        issues.append(r"\[ ... \] 수식 구분자의 짝이 맞지 않습니다.")
    balance = 0
    for match in re.finditer(r"(?<!\\)[{}]", text):
        balance += 1 if match.group() == "{" else -1
        if balance < 0:
            break
    if balance != 0:
        issues.append("수식 중괄호 { }의 짝이 맞지 않습니다.")
    if any(char in text for char in ("�", "□", "▢", "■")) or any(0xE000 <= ord(char) <= 0xF8FF for char in text):
        issues.append("복원되지 않은 글리프 또는 수식 자리표시자가 남아 있습니다.")
    return issues


def _whitespace_issue(value: str) -> bool:
    text = str(value or "")
    return bool(
        text != text.strip()
        or _EXCESS_BLANK_LINES_RE.search(text)
        or _MULTISPACE_RE.search(text)
        or any(line.endswith((" ", "\t")) for line in text.splitlines())
    )


@router.post("/problem/review")
def review_problem(payload: ProblemReviewPayload) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    stem = payload.stem.strip()
    choices = [str(choice or "") for choice in payload.choices]
    nonempty_choices = [choice for choice in choices if choice.strip()]

    if not stem:
        findings.append(
            _review_finding("error", "본문 없음", "문항 본문이 비어 있습니다.", "stem", "문제 지문 또는 질문을 입력하세요.")
        )
    if not payload.number.strip():
        findings.append(_review_finding("info", "문항 번호 없음", "문항 번호가 비어 있습니다.", "number"))
    if not payload.title.strip():
        findings.append(_review_finding("info", "제목 없음", "문항 제목이 비어 있습니다.", "title"))

    if choices and len(nonempty_choices) != len(choices):
        findings.append(
            _review_finding("error", "빈 선지", "내용이 없는 선지가 포함되어 있습니다.", "choices", "빈 선지를 삭제하거나 내용을 입력하세요.")
        )
    if choices and len(nonempty_choices) < 2:
        findings.append(
            _review_finding("warning", "선지 부족", "객관식 문항의 유효한 선지가 2개 미만입니다.", "choices")
        )

    labels = [_choice_label(choice) for choice in nonempty_choices]
    labeled = [label for label in labels if label is not None]
    if labeled and len(labeled) != len(nonempty_choices):
        findings.append(
            _review_finding(
                "warning",
                "선지 번호 형식 혼용",
                "번호가 붙은 선지와 번호가 없는 선지가 함께 있습니다.",
                "choices",
                "선지 번호는 모두 제거하거나 1부터 순서대로 통일하세요.",
            )
        )
    elif labeled and labeled != list(range(1, len(labeled) + 1)):
        findings.append(
            _review_finding(
                "error",
                "선지 번호 불일치",
                f"선지 번호가 1부터 순서대로 이어지지 않습니다: {labeled}",
                "choices",
                "선지 번호를 실제 배열 순서와 일치시키세요.",
            )
        )

    duplicate_groups: dict[str, list[int]] = {}
    for index, choice in enumerate(nonempty_choices, start=1):
        key = _normalized_duplicate_key(choice)
        if key:
            duplicate_groups.setdefault(key, []).append(index)
    duplicates = [indexes for indexes in duplicate_groups.values() if len(indexes) > 1]
    if duplicates:
        rendered = ", ".join("/".join(map(str, indexes)) for indexes in duplicates)
        findings.append(
            _review_finding(
                "error",
                "중복 선지",
                f"공백과 번호를 제외했을 때 같은 선지가 있습니다: {rendered}번",
                "choices",
                "중복 선지를 수정하거나 제거하세요.",
            )
        )

    answer = payload.answer.strip()
    if nonempty_choices:
        if not answer:
            findings.append(
                _review_finding("error", "정답 없음", "객관식 선지가 있지만 정답이 비어 있습니다.", "answer", "정답 선지 번호를 입력하세요.")
            )
        else:
            answer_numbers = _answer_numbers(answer)
            if not answer_numbers:
                findings.append(
                    _review_finding(
                        "warning",
                        "정답 범위 확인 불가",
                        "정답에서 선지 번호를 판별하지 못했습니다.",
                        "answer",
                        "정답을 1~선지 수 범위의 번호로 입력하세요.",
                    )
                )
            else:
                out_of_range = [number for number in answer_numbers if number > len(nonempty_choices)]
                if out_of_range:
                    findings.append(
                        _review_finding(
                            "error",
                            "정답 범위 오류",
                            f"정답 {out_of_range}은(는) 선지 1~{len(nonempty_choices)} 범위를 벗어납니다.",
                            "answer",
                            "존재하는 선지 번호로 정답을 수정하세요.",
                        )
                    )
    elif answer and _answer_numbers(answer):
        findings.append(
            _review_finding(
                "info",
                "선지 없는 번호형 정답",
                "선지는 없지만 정답이 선지 번호처럼 보입니다.",
                "answer",
                "주관식 정답인지 선지 누락인지 확인하세요.",
            )
        )

    if not payload.explanation.strip():
        findings.append(
            _review_finding("warning", "해설 없음", "문항 해설이 비어 있습니다.", "explanation", "풀이 근거 또는 해설을 추가하세요.")
        )

    text_fields: list[tuple[str, str]] = [
        ("title", payload.title),
        ("stem", payload.stem),
        ("answer", payload.answer),
        ("explanation", payload.explanation),
    ]
    text_fields.extend((f"choices[{index}]", choice) for index, choice in enumerate(choices))
    for field_name, value in text_fields:
        for issue in _math_structure_issues(value):
            findings.append(
                _review_finding("error", "수식 구조 오류", issue, field_name, "수식 구분자와 괄호의 짝을 확인하세요.")
            )
        if value and _whitespace_issue(value):
            findings.append(
                _review_finding(
                    "info",
                    "불필요한 공백",
                    "앞뒤 공백, 연속 공백, 줄 끝 공백 또는 과도한 빈 줄이 있습니다.",
                    field_name,
                    "의미를 유지하면서 공백을 정리하세요.",
                )
            )

    counts = {severity: sum(1 for item in findings if item["severity"] == severity) for severity in ("error", "warning", "info")}
    score = max(0, 100 - counts["error"] * 20 - counts["warning"] * 10 - counts["info"] * 3)
    if counts["error"]:
        summary_text = "수정이 필요한 오류가 있습니다."
    elif counts["warning"]:
        summary_text = "사용 가능하지만 보완을 권장합니다."
    elif counts["info"]:
        summary_text = "핵심 구조는 정상이며 정리할 항목이 있습니다."
    else:
        summary_text = "문항 구조 점검을 통과했습니다."
    return {
        "ok": True,
        "score": score,
        "summary": {"text": summary_text, "total": len(findings), **counts},
        "findings": findings,
    }


def _decode_image(data_base64: str) -> Image.Image:
    encoded = data_base64.strip()
    if encoded.startswith("data:"):
        try:
            encoded = encoded.split(",", 1)[1]
        except IndexError as exc:
            raise HTTPException(status_code=400, detail="Invalid image data URL") from exc
    encoded = "".join(encoded.split())
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 image data") from exc
    if len(raw) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds the 10 MiB limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            opened = Image.open(io.BytesIO(raw))
            if opened.width * opened.height > _MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=413, detail="Image exceeds the 25 megapixel limit")
            opened.load()
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(status_code=400, detail="Unsupported or unsafe image data") from exc
    return image


def _sanitize_provider_value(value: Any) -> Any:
    """Remove credentials from nested provider diagnostics before JSON output."""
    secrets = [
        str(value).strip()
        for value in settings.load_user_settings().values()
        if isinstance(value, str) and str(value).strip()
    ]
    secrets.extend(
        key for key in (os.environ.get("GEMINI_API_KEY", ""), os.environ.get("OPENAI_API_KEY", "")) if key
    )

    def sanitize(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                str(key): sanitize(child)
                for key, child in item.items()
                if not any(marker in str(key).lower() for marker in ("api_key", "apikey", "authorization", "token"))
            }
        if isinstance(item, list):
            return [sanitize(child) for child in item]
        if isinstance(item, tuple):
            return [sanitize(child) for child in item]
        if isinstance(item, str):
            text = item
            for secret in secrets:
                text = text.replace(secret, "[REDACTED]")
            return pdf_math_ai.redact_error(text)
        return item

    return sanitize(value)


@router.post("/ocr")
def recognize_image_text(payload: OCRPayload) -> dict[str, Any]:
    image = _decode_image(payload.data_base64)
    backend_name = payload.model.strip() if payload.backend == "gemini" and payload.model else payload.backend
    try:
        backend = ocr_backend.build_ocr_backend(backend_name)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    resolved_backend = str(getattr(backend, "name", "none") or "none")
    if resolved_backend == "gemini" and not payload.allow_remote:
        raise HTTPException(
            status_code=409,
            detail="Remote OCR requires allowRemote=true because it sends the image to Gemini",
        )
    try:
        result = backend.ocr_image(image)
    except Exception as exc:  # provider/local engine failures are an upstream capability error
        raise HTTPException(status_code=502, detail=pdf_math_ai.redact_error(str(exc))) from exc
    lines = [
        {
            "text": line.text,
            "confidence": line.confidence,
            "bbox": {
                "left": line.bbox.left,
                "top": line.bbox.top,
                "width": line.bbox.width,
                "height": line.bbox.height,
            },
        }
        for line in result.lines
    ]
    return {
        "ok": True,
        "filename": payload.filename,
        "backend": result.backend_name,
        "text": result.text,
        "normalizedText": math_text.normalize_recognized_math_layout_text(result.text),
        "confidence": result.confidence,
        "lines": lines,
        "metadata": _sanitize_provider_value(result.metadata),
    }


@router.post("/reconstruct")
def reconstruct_problem_image(payload: ReconstructImagePayload) -> dict[str, Any]:
    if not payload.allow_remote:
        raise HTTPException(
            status_code=409,
            detail="Image reconstruction requires allowRemote=true because it sends the image to an AI provider",
        )
    key_name = "GEMINI_API_KEY" if payload.provider == "gemini" else "OPENAI_API_KEY"
    api_key = os.environ.get(key_name, "").strip()
    if not api_key:
        saved = settings.load_user_settings()
        saved_name = "gemini_api_key" if payload.provider == "gemini" else "openai_api_key"
        api_key = str(saved.get(saved_name) or "").strip()
    if not api_key:
        raise HTTPException(status_code=409, detail=f"{key_name} is not configured")

    image = _decode_image(payload.data_base64)
    output_dir = storage.UPLOAD_DIR / "ai_reconstruction"
    output_dir.mkdir(parents=True, exist_ok=True)
    operation_id = uuid.uuid4().hex
    source_path = output_dir / f"{operation_id}_source.png"
    output_path = output_dir / f"{operation_id}_reconstructed.png"
    image.save(source_path, format="PNG", optimize=True)
    try:
        result = reconstruct.reconstruct_problem_image(
            source_path,
            output_path,
            api_key=api_key,
            provider=payload.provider,
            model=payload.model,
            prompt=payload.prompt or reconstruct.DEFAULT_RECONSTRUCTION_PROMPT,
            quality=payload.quality,
            size=payload.size,
            transparent_background=payload.transparent_background,
            sharpen=payload.sharpen,
        )
    except ValueError as exc:
        source_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=pdf_math_ai.redact_error(str(exc))) from exc
    except Exception as exc:
        source_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=pdf_math_ai.redact_error(str(exc))) from exc

    relative_output = output_path.relative_to(storage.UPLOAD_DIR).as_posix()
    return {
        "ok": True,
        "operationId": operation_id,
        "provider": result.provider,
        "model": result.model,
        "latencyMs": result.latency_ms,
        "file": {
            "name": output_path.name,
            "path": f"uploads/{relative_output}",
            "url": f"/files/uploads/{relative_output}",
        },
        "metadata": _sanitize_provider_value(
            {
                "usage": result.usage or {},
                "response_id": result.response_id,
                "mime_type": result.mime_type,
                "postprocess": result.postprocess or {},
            }
        ),
    }
