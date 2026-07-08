#!/usr/bin/env python3
from __future__ import annotations

import base64
import io
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from app.recognition.schema import Box

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
# NOTE: The Gemini model ids below are forward-dated placeholders carried over
# verbatim from edb_make. Verify them against the live model catalog before
# relying on them in production; the graceful-degradation ladder means a bad
# id simply falls back to a local backend or NoOp rather than crashing.
DEFAULT_GEMINI_OCR_MODEL = "gemini-3.5-flash"
GEMINI_OCR_MODEL_ENV = "EDB_GEMINI_OCR_MODEL"
GEMINI_OCR_THINKING_LEVEL_ENV = "EDB_GEMINI_OCR_THINKING_LEVEL"
DEFAULT_GEMINI_FLASH_OCR_THINKING_LEVEL = "low"
FALLBACK_GEMINI_OCR_MODEL = "gemini-2.5-pro"
DEPRECATED_GEMINI_OCR_MODELS = {"gemini-3-pro-preview", "gemini-3.1-pro-preview"}

# Gemini's responseSchema follows an OpenAPI 3.0 subset: no `additionalProperties`,
# no `$ref`, no `oneOf`. Keep the shape simple and rely on `required` instead.
_OCR_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "Full extracted text from the image, preserving line breaks with \\n.",
        },
        "block_type": {
            "type": "string",
            "enum": ["stem", "choice", "figure", "formula", "title", "explanation", "unknown"],
            "description": (
                "Classification of the block. 'stem' for problem body text, "
                "'choice' for answer options (①②③④⑤ or ㄱㄴㄷ lists), "
                "'figure' for diagrams/tables/images with little text, "
                "'formula' for math equations, 'title' for problem-number headings, "
                "'explanation' for solution/commentary text."
            ),
        },
        "confidence": {
            "type": "number",
            "description": "Confidence in the OCR result, 0.0 to 1.0.",
        },
        "lines": {
            "type": "array",
            "description": "Individual text lines recognized, in reading order.",
            "items": {"type": "string"},
        },
    },
    "required": ["text", "block_type", "confidence", "lines"],
}

try:
    from paddleocr import PaddleOCR  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    PaddleOCR = None

try:
    import pytesseract  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    pytesseract = None


# Tiny crops (height below this) get upscaled before OCR. Korean OCR engines
# need ~28–40 px x-height to hit decent accuracy; cropped exam blocks are
# often half that.
_OCR_MIN_HEIGHT_PX = 64
_OCR_UPSCALE_CAP = 3.0
_OCR_CROP_PADDING_PX = 6


def resolve_gemini_ocr_model(model: str | None = None) -> str:
    requested = (model or "").strip()
    if requested:
        return requested
    env_model = os.environ.get(GEMINI_OCR_MODEL_ENV, "").strip()
    return env_model or DEFAULT_GEMINI_OCR_MODEL


def resolve_gemini_ocr_thinking_level(model: str, thinking_level: str | None = None) -> str:
    requested = (thinking_level or "").strip().lower()
    if requested:
        return requested
    env_level = os.environ.get(GEMINI_OCR_THINKING_LEVEL_ENV, "").strip().lower()
    if env_level:
        return env_level
    normalized_model = (model or "").strip().lower()
    if normalized_model == "gemini-3.5-flash":
        return DEFAULT_GEMINI_FLASH_OCR_THINKING_LEVEL
    return ""


def _gemini_model_supports_thinking_level(model: str) -> bool:
    normalized_model = (model or "").strip().lower()
    return normalized_model.startswith("gemini-3")


def _gemini_model_candidates(primary: str) -> list[str]:
    primary = resolve_gemini_ocr_model(primary)
    candidates = [primary]
    if (
        primary == DEFAULT_GEMINI_OCR_MODEL
        or primary in DEPRECATED_GEMINI_OCR_MODELS
        or primary.startswith("gemini-3")
        or "preview" in primary
    ):
        candidates.append(FALLBACK_GEMINI_OCR_MODEL)
    return list(dict.fromkeys(model for model in candidates if model))


def _is_retryable_gemini_error(exc: Exception) -> bool:
    if _is_fatal_gemini_error(exc):
        return False
    if not isinstance(exc, urllib.error.HTTPError):
        return True
    status_code = int(exc.code)
    return status_code in {408, 409, 425, 429} or status_code >= 500


def _format_gemini_error(exc: Exception) -> str:
    if not isinstance(exc, urllib.error.HTTPError):
        return str(exc)
    body = getattr(exc, "_edb_response_body", None)
    if body is None:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        try:
            setattr(exc, "_edb_response_body", body)
        except Exception:
            pass
    if body:
        return f"Gemini request failed with HTTP {exc.code}: {body}"
    return str(exc)


def _is_fatal_gemini_error(exc: Exception) -> bool:
    if not isinstance(exc, urllib.error.HTTPError):
        return False
    status_code = int(exc.code)
    message = _format_gemini_error(exc).lower()
    if status_code in {400, 401, 403}:
        return True
    if status_code == 429 and any(
        marker in message
        for marker in (
            "api_key_invalid",
            "api key not found",
            "billing",
            "credits are depleted",
            "prepayment",
            "quota",
            "resource_exhausted",
        )
    ):
        return True
    return False


def _prep_crop_for_ocr(image: Image.Image) -> Image.Image:
    """Pad and upscale a block crop so per-character pixels are within the
    range Korean OCR engines expect. Returns a new image; the input is not
    mutated."""
    if image.width <= 0 or image.height <= 0:
        return image

    padded = image
    pad = _OCR_CROP_PADDING_PX
    if pad > 0:
        new_w = image.width + pad * 2
        new_h = image.height + pad * 2
        padded = Image.new("RGB", (new_w, new_h), (255, 255, 255))
        padded.paste(image.convert("RGB"), (pad, pad))

    if padded.height >= _OCR_MIN_HEIGHT_PX:
        return padded

    scale = min(_OCR_UPSCALE_CAP, _OCR_MIN_HEIGHT_PX / max(padded.height, 1))
    if scale <= 1.0:
        return padded
    new_size = (int(round(padded.width * scale)), int(round(padded.height * scale)))
    return padded.resize(new_size, Image.Resampling.LANCZOS)


@dataclass(slots=True)
class OCRLine:
    text: str
    confidence: float
    bbox: Box


@dataclass(slots=True)
class OCRResult:
    text: str
    confidence: float | None
    lines: list[OCRLine] = field(default_factory=list)
    backend_name: str = "none"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def engine(self) -> str:
        return self.backend_name


def _line_confidence_summary(lines: list[OCRLine]) -> dict[str, Any]:
    confidences = [line.confidence for line in lines if line.confidence is not None]
    if not confidences:
        return {
            "line_confidence_count": 0,
            "line_confidence_mean": None,
            "line_confidence_min": None,
            "line_confidence_max": None,
        }
    return {
        "line_confidence_count": len(confidences),
        "line_confidence_mean": sum(confidences) / len(confidences),
        "line_confidence_min": min(confidences),
        "line_confidence_max": max(confidences),
    }


def _build_ocr_metadata(
    *,
    backend: str,
    started_at: float,
    text: str,
    confidence: float | None,
    lines: list[OCRLine],
    extra: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    normalized_text = text.strip()
    diagnostics: dict[str, Any] = {
        "backend": backend,
        "backend_latency_ms": int(max(0.0, (time.perf_counter() - started_at) * 1000.0)),
        "line_count": len(lines),
        "empty_text": not bool(normalized_text),
        "text_length": len(normalized_text),
        "confidence_available": confidence is not None,
        "result_confidence": confidence,
    }
    diagnostics.update(_line_confidence_summary(lines))
    if error:
        diagnostics["error"] = error
    if extra:
        diagnostics.update(extra)
    return diagnostics


class OCRBackend:
    name = "base"

    @property
    def engine_name(self) -> str:
        return self.name

    def ocr_image(self, image: Image.Image) -> OCRResult:
        raise NotImplementedError

    def ocr_box(self, image: Image.Image, box: Box) -> OCRResult:
        crop = image.crop((int(box.left), int(box.top), int(box.right), int(box.bottom)))
        return self.ocr_image(crop)

    def recognize(self, image: Image.Image) -> OCRResult:
        return self.ocr_image(image)


class NoOcrBackend(OCRBackend):
    name = "none"

    def ocr_image(self, image: Image.Image) -> OCRResult:
        started_at = time.perf_counter()
        return OCRResult(
            text="",
            confidence=None,
            backend_name=self.name,
            metadata=_build_ocr_metadata(
                backend=self.name,
                started_at=started_at,
                text="",
                confidence=None,
                lines=[],
            ),
        )


NoOpOCRBackend = NoOcrBackend


class PaddleOCRBackend(OCRBackend):
    name = "paddleocr"

    def __init__(self, *, lang: str = "korean", use_angle_cls: bool = True) -> None:
        if PaddleOCR is None:
            raise RuntimeError("paddleocr is not installed")
        self.engine = PaddleOCR(lang=lang, use_angle_cls=use_angle_cls, show_log=False)

    def ocr_image(self, image: Image.Image) -> OCRResult:
        started_at = time.perf_counter()
        prepped = _prep_crop_for_ocr(image)
        try:
            raw = self.engine.ocr(prepped.convert("RGB"), cls=True)
        except Exception as exc:  # pragma: no cover - runtime fallback
            return OCRResult(
                text="",
                confidence=None,
                lines=[],
                backend_name=self.name,
                metadata=_build_ocr_metadata(
                    backend=self.name,
                    started_at=started_at,
                    text="",
                    confidence=None,
                    lines=[],
                    error=str(exc),
                ),
            )

        entries = raw[0] if raw else []
        lines: list[OCRLine] = []
        collected: list[str] = []
        confidences: list[float] = []

        for entry in entries or []:
            polygon, payload = entry
            text = str(payload[0]).strip()
            if not text:
                continue
            confidence = float(payload[1]) if len(payload) > 1 else 0.0
            xs = [point[0] for point in polygon]
            ys = [point[1] for point in polygon]
            lines.append(
                OCRLine(
                    text=text,
                    confidence=confidence,
                    bbox=Box.from_points(min(xs), min(ys), max(xs), max(ys)),
                )
            )
            collected.append(text)
            confidences.append(confidence)

        average_confidence = sum(confidences) / len(confidences) if confidences else None
        return OCRResult(
            text="\n".join(collected),
            confidence=average_confidence,
            lines=lines,
            backend_name=self.name,
            metadata=_build_ocr_metadata(
                backend=self.name,
                started_at=started_at,
                text="\n".join(collected),
                confidence=average_confidence,
                lines=lines,
            ),
        )


class TesseractOCRBackend(OCRBackend):
    name = "tesseract"

    def __init__(self, *, lang: str = "kor+eng") -> None:
        if pytesseract is None:
            raise RuntimeError("pytesseract is not installed")
        self.lang = lang

    def ocr_image(self, image: Image.Image) -> OCRResult:
        started_at = time.perf_counter()
        prepped = _prep_crop_for_ocr(image)

        try:
            data = pytesseract.image_to_data(prepped, lang=self.lang, output_type=pytesseract.Output.DICT)
        except Exception as exc:
            return OCRResult(
                text="",
                confidence=None,
                lines=[],
                backend_name=self.name,
                metadata=_build_ocr_metadata(
                    backend=self.name,
                    started_at=started_at,
                    text="",
                    confidence=None,
                    lines=[],
                    error=str(exc),
                ),
            )

        lines: list[OCRLine] = []
        collected: list[str] = []
        confidences: list[float] = []

        for idx, text in enumerate(data.get("text", [])):
            cleaned = str(text).strip()
            if not cleaned:
                continue
            raw_conf = data["conf"][idx]
            confidence = float(raw_conf) / 100.0 if raw_conf not in {"-1", -1} else 0.0
            left = float(data["left"][idx])
            top = float(data["top"][idx])
            width = float(data["width"][idx])
            height = float(data["height"][idx])
            lines.append(
                OCRLine(
                    text=cleaned,
                    confidence=confidence,
                    bbox=Box(left=left, top=top, width=width, height=height),
                )
            )
            collected.append(cleaned)
            confidences.append(confidence)

        average_confidence = sum(confidences) / len(confidences) if confidences else None
        return OCRResult(
            text="\n".join(collected),
            confidence=average_confidence,
            lines=lines,
            backend_name=self.name,
            metadata=_build_ocr_metadata(
                backend=self.name,
                started_at=started_at,
                text="\n".join(collected),
                confidence=average_confidence,
                lines=lines,
            ),
        )


class GeminiOCRBackend(OCRBackend):
    """OCR backend that uses Google Gemini vision API for text extraction and block classification."""

    name = "gemini"

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        timeout_ms: int = 15000,
        max_tokens: int = 1024,
        max_retries: int = 1,
        thinking_level: str | None = None,
    ) -> None:
        self.model = resolve_gemini_ocr_model(model)
        self.thinking_level = resolve_gemini_ocr_thinking_level(self.model, thinking_level)
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable is required for GeminiOCRBackend")
        self.timeout_s = timeout_ms / 1000.0
        self.max_tokens = max_tokens
        self.max_retries = max(0, max_retries)

    def _encode_image(self, image: Image.Image) -> tuple[str, str]:
        """Pick JPEG for large crops (smaller payload), PNG for small crops
        (lossless for tiny text). Returns (media_type, base64-data)."""
        rgb = image.convert("RGB")
        if rgb.height < 200 or rgb.width < 200:
            buf = io.BytesIO()
            rgb.save(buf, format="PNG", optimize=True)
            return "image/png", base64.b64encode(buf.getvalue()).decode("ascii")
        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=92, optimize=True)
        return "image/jpeg", base64.b64encode(buf.getvalue()).decode("ascii")

    def _image_to_base64(self, image: Image.Image) -> str:
        # Kept for backward compatibility with external callers.
        _, data = self._encode_image(image)
        return data

    def ocr_image(self, image: Image.Image) -> OCRResult:
        started_at = time.perf_counter()
        prompt = (
            "This is a cropped block from a Korean exam paper. "
            "Extract ALL visible text exactly as written — do not summarize, paraphrase, or skip anything. "
            "Read the entire crop from top to bottom, including text above and below tables, diagrams, and figures. "
            "If a table or diagram is followed by numbered questions or answer choices, include those lines too. "
            "If multiple problem numbers are visible in one crop, include every problem number on its own line. "
            "Preserve Korean characters, math symbols, circled numbers ①②③④⑤, and ㄱ/ㄴ/ㄷ markers. "
            "Use \\n between visual lines. Keep digits, parentheses, and punctuation as-is. "
            "Classify the block by content:\n"
            "  - 'title' : a problem-number heading like '1.', '문제 3', '[4]'\n"
            "  - 'stem'  : main question body text\n"
            "  - 'choice': stand-alone answer-option block (① ② ③ ④ ⑤ or A–E)\n"
            "  - 'formula': a math equation or expression line\n"
            "  - 'figure': diagram/table/photo with little or no text\n"
            "  - 'explanation': solution or commentary text\n"
            "Set confidence based on how legible the text is (0.0–1.0). "
            "If the block is mostly figure with no useful text, return text='' and block_type='figure'."
        )

        prepped = _prep_crop_for_ocr(image)
        media_type, image_data = self._encode_image(prepped)
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"inline_data": {"mime_type": media_type, "data": image_data}},
                        {"text": prompt},
                    ],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": _OCR_RESPONSE_SCHEMA,
                "maxOutputTokens": self.max_tokens,
                "temperature": 0.0,
            },
        }
        model_candidates = _gemini_model_candidates(self.model)
        used_model = model_candidates[0]
        url = f"{GEMINI_API_BASE}/{used_model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        thinking_levels_by_model: dict[str, str] = {}

        def _body_for_model(model: str) -> bytes:
            generation_config = dict(payload["generationConfig"])
            generation_config.pop("thinkingConfig", None)
            thinking_level = (
                self.thinking_level
                if model == self.model
                else resolve_gemini_ocr_thinking_level(model)
            )
            if thinking_level and _gemini_model_supports_thinking_level(model):
                generation_config["thinkingConfig"] = {
                    "thinkingLevel": thinking_level,
                }
                thinking_levels_by_model[model] = thinking_level
            else:
                thinking_levels_by_model[model] = ""
            model_payload = dict(payload)
            model_payload["generationConfig"] = generation_config
            return json.dumps(model_payload).encode("utf-8")

        last_exc: Exception | None = None
        response_data: dict[str, Any] | None = None
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                time.sleep(min(1.5 * attempt, 4.0))
            try:
                body = _body_for_model(used_model)
                req = urllib.request.Request(url, data=body, method="POST", headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    response_data = json.loads(resp.read().decode("utf-8"))
                break
            except Exception as exc:  # network / API errors → retry
                last_exc = exc
                if not _is_retryable_gemini_error(exc):
                    break

        model_attempts: list[dict[str, str]] = []
        if response_data is None:
            model_attempts.append(
                {
                    "model": used_model,
                    "status": "error",
                    "error": _format_gemini_error(last_exc) if last_exc else "no response",
                }
            )
            fallback_models = [] if last_exc and _is_fatal_gemini_error(last_exc) else model_candidates[1:]
            for fallback_model in fallback_models:
                used_model = fallback_model
                url = f"{GEMINI_API_BASE}/{used_model}:generateContent?key={self.api_key}"
                last_exc = None
                for attempt in range(self.max_retries + 1):
                    if attempt > 0:
                        time.sleep(min(1.5 * attempt, 4.0))
                    try:
                        body = _body_for_model(used_model)
                        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
                        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                            response_data = json.loads(resp.read().decode("utf-8"))
                        break
                    except Exception as exc:
                        last_exc = exc
                        if not _is_retryable_gemini_error(exc):
                            break
                if response_data is not None:
                    model_attempts.append({"model": used_model, "status": "ok"})
                    break
                model_attempts.append(
                    {
                        "model": used_model,
                        "status": "error",
                        "error": _format_gemini_error(last_exc) if last_exc else "no response",
                    }
                )
        else:
            model_attempts.append({"model": used_model, "status": "ok"})

        if response_data is None:
            return OCRResult(
                text="",
                confidence=None,
                lines=[],
                backend_name=self.name,
                metadata=_build_ocr_metadata(
                    backend=self.name,
                    started_at=started_at,
                    text="",
                    confidence=None,
                    lines=[],
                    error=_format_gemini_error(last_exc) if last_exc else "no response",
                    extra={"retry_count": self.max_retries, "model_attempts": model_attempts},
                ),
            )

        # Gemini returns structured output as a JSON string inside the first
        # text part of candidate[0].
        json_text = _gemini_extract_text(response_data)
        if not json_text:
            finish_reason = _gemini_finish_reason(response_data)
            return OCRResult(
                text="",
                confidence=None,
                lines=[],
                backend_name=self.name,
                metadata=_build_ocr_metadata(
                    backend=self.name,
                    started_at=started_at,
                    text="",
                    confidence=None,
                    lines=[],
                    error=f"no text in response (finish={finish_reason})",
                    extra={"retry_count": self.max_retries, "model_attempts": model_attempts},
                ),
            )

        try:
            parsed: dict[str, Any] = json.loads(json_text)
        except json.JSONDecodeError as exc:
            return OCRResult(
                text="",
                confidence=None,
                lines=[],
                backend_name=self.name,
                metadata=_build_ocr_metadata(
                    backend=self.name,
                    started_at=started_at,
                    text="",
                    confidence=None,
                    lines=[],
                    error=f"json decode failed: {exc}",
                    extra={"retry_count": self.max_retries, "model_attempts": model_attempts},
                ),
            )

        raw_text = str(parsed.get("text", "")).strip()
        raw_lines = parsed.get("lines") or []
        confidence = float(parsed.get("confidence", 0.8))
        block_type_hint = str(parsed.get("block_type", "unknown"))

        # Build OCRLine list (Gemini does not return per-line bboxes; use even
        # vertical splits of the original crop so downstream consumers still
        # have a usable coordinate hint).
        lines: list[OCRLine] = []
        image_h = float(image.height) or 1.0
        image_w = float(image.width) or 1.0
        for idx, line_text in enumerate(raw_lines):
            cleaned = str(line_text).strip()
            if not cleaned:
                continue
            line_h = image_h / max(len(raw_lines), 1)
            lines.append(
                OCRLine(
                    text=cleaned,
                    confidence=confidence,
                    bbox=Box(left=0.0, top=idx * line_h, width=image_w, height=line_h),
                )
            )

        return OCRResult(
            text=raw_text,
            confidence=confidence,
            lines=lines,
            backend_name=self.name,
            metadata=_build_ocr_metadata(
                backend=self.name,
                started_at=started_at,
                text=raw_text,
                confidence=confidence,
                lines=lines,
                extra={
                    "block_type_hint": block_type_hint,
                    "model": used_model,
                    "model_attempts": model_attempts,
                    "thinking_level": thinking_levels_by_model.get(used_model, ""),
                },
            ),
        )


def _gemini_extract_text(response: dict[str, Any]) -> str:
    """Return the concatenated text from the first candidate's parts, or ''."""
    candidates = response.get("candidates") or []
    if not candidates:
        return ""
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    collected: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str) and text:
            collected.append(text)
    return "".join(collected)


def _gemini_finish_reason(response: dict[str, Any]) -> str:
    candidates = response.get("candidates") or []
    if not candidates:
        return "no_candidates"
    return str(candidates[0].get("finishReason") or "unknown")


def _tesseract_binary_available() -> bool:
    """Return True only if the tesseract binary is actually callable."""
    if pytesseract is None:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def build_ocr_backend(name: str = "auto") -> OCRBackend:
    raw_name = (name or "auto").strip()
    normalized = raw_name.lower()
    if normalized in {"none", "noop"}:
        return NoOcrBackend()
    if normalized in {"paddle", "paddleocr"}:
        return PaddleOCRBackend()
    if normalized == "tesseract":
        return TesseractOCRBackend()
    if normalized in {"gemini", "google", "claude", "anthropic"}:
        # 'claude'/'anthropic' kept as aliases for transitional configs; both
        # resolve to the Gemini backend now.
        return GeminiOCRBackend()
    if normalized.startswith("gemini-"):
        return GeminiOCRBackend(model=raw_name)

    # --- auto selection: Korean exam pages with diagrams and math need a
    # vision-language model to read reliably, so prefer Gemini when an API
    # key is configured. Local engines stay as the offline fallback.
    if os.environ.get("GEMINI_API_KEY", "").strip():
        try:
            return GeminiOCRBackend()
        except Exception:
            pass
    if PaddleOCR is not None:
        try:
            return PaddleOCRBackend()
        except Exception:
            pass
    if _tesseract_binary_available():
        try:
            return TesseractOCRBackend()
        except Exception:
            pass
    # Last resort. Surface this loudly: a silent NoOcr fallback is the most
    # common reason problem numbers, choices, and figures get split into
    # separate fake "problems" downstream.
    print(
        "[ocr_backend] WARNING: 'auto' resolved to NoOcrBackend — no OCR engine "
        "is available. Set GEMINI_API_KEY (in .env.local or the user settings UI) "
        "or install paddleocr / tesseract. Problem-number detection will be "
        "disabled and every detected band will become its own pseudo-problem.",
        flush=True,
    )
    return NoOcrBackend()


def create_ocr_backend(name: str = "auto") -> OCRBackend:
    return build_ocr_backend(name)


OcrResult = OCRResult
