"""Gemini-backed recognition for risky PDF math crops.

This module never paints AI output as an image. It only asks Gemini to recover
the reading order and math structure for a crop, then the PDF layout writer can
turn that structure into HWPX text/equation elements.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

import fitz
from PIL import Image

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_GEMINI_MATH_MODEL = "gemini-3.5-flash"
GEMINI_MATH_MODEL_ENV = "HWP_MATH_AI_MODEL"
GEMINI_MATH_ENABLED_ENV = "HWP_MATH_AI_RECOGNITION"
GEMINI_MATH_MAX_CALLS_ENV = "HWP_MATH_AI_MAX_CALLS"
GEMINI_MATH_MOCK_RESPONSE_ENV = "HWP_MATH_AI_MOCK_RESPONSE"
DEFAULT_GEMINI_MATH_TIMEOUT_MS = 20000
DEFAULT_GEMINI_MATH_MIN_CONFIDENCE = 0.72
DEFAULT_GEMINI_MATH_MAX_CALLS = 16
_API_KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
_LATEX_FENCE_RE = re.compile(r"^```(?:latex|tex|math)?\s*|\s*```$", re.IGNORECASE)
_SEVERE_RESPONSE_MARKERS = (
    "can't determine",
    "cannot determine",
    "not enough information",
    "unable to read",
)
_BAD_MATH_CHARS = {"\u25a1", "\u25a0", "\u25a2", "\u25a3", "\ufffd", "\ufffc"}

_MATH_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "plain_text": {
            "type": "string",
            "description": "Human-readable exact math expression, without solving it.",
        },
        "latex": {
            "type": "string",
            "description": "LaTeX for the visible math expression.",
        },
        "hancom_eqn": {
            "type": "string",
            "description": "Hancom Equation script for the visible math expression.",
        },
        "confidence": {
            "type": "number",
            "description": "Recognition confidence from 0.0 to 1.0.",
        },
        "reading_order": {
            "type": "array",
            "description": "Visible math tokens in reading order.",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "role": {
                        "type": "string",
                        "enum": [
                            "base",
                            "operator",
                            "numerator",
                            "denominator",
                            "subscript",
                            "superscript",
                            "radicand",
                            "limit",
                            "other",
                        ],
                    },
                },
                "required": ["text", "role"],
            },
        },
        "notes": {
            "type": "string",
            "description": "Short uncertainty note, empty when confident.",
        },
    },
    "required": ["plain_text", "latex", "hancom_eqn", "confidence", "reading_order", "notes"],
}


@dataclass(slots=True)
class MathAIRecognition:
    status: str
    provider: str = "gemini"
    model: str = DEFAULT_GEMINI_MATH_MODEL
    confidence: float = 0.0
    plain_text: str = ""
    latex: str = ""
    hancom_eqn: str = ""
    reading_order: list[dict[str, str]] = field(default_factory=list)
    notes: str = ""
    error: str = ""
    latency_ms: int = 0
    source_rect: tuple[float, float, float, float] | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)
    validation_issues: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.raw_response:
            payload["raw_response"] = {"present": True}
        return payload


def resolve_math_ai_model(model: str | None = None) -> str:
    requested = (model or "").strip()
    if not requested:
        requested = os.environ.get(GEMINI_MATH_MODEL_ENV, "").strip()
    value = requested or DEFAULT_GEMINI_MATH_MODEL
    if value.lower() in {"3.5", "gemini-3.5", "gemini 3.5"}:
        return DEFAULT_GEMINI_MATH_MODEL
    return value


def resolve_math_ai_enabled(value: bool | None = None) -> bool:
    if value is not None:
        return bool(value)
    raw = os.environ.get(GEMINI_MATH_ENABLED_ENV, "auto").strip().lower()
    if raw in {"0", "false", "off", "no", "disabled"}:
        return False
    if raw in {"1", "true", "on", "yes", "enabled"}:
        return True
    return False


def resolve_math_ai_max_calls(value: int | None = None) -> int:
    if value is not None:
        return max(0, int(value))
    raw = os.environ.get(GEMINI_MATH_MAX_CALLS_ENV, "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return DEFAULT_GEMINI_MATH_MAX_CALLS


def recognize_math_crop(
    page: fitz.Page,
    source_rect: fitz.Rect,
    *,
    api_key: str | None = None,
    model: str | None = None,
    min_confidence: float = DEFAULT_GEMINI_MATH_MIN_CONFIDENCE,
    timeout_ms: int = DEFAULT_GEMINI_MATH_TIMEOUT_MS,
    max_retries: int = 2,
    text_hint: str | None = None,
    token_hints: list[dict[str, Any]] | None = None,
) -> MathAIRecognition:
    resolved_model = resolve_math_ai_model(model)
    rect = fitz.Rect(source_rect)
    if rect.is_empty or rect.width <= 1 or rect.height <= 1:
        return MathAIRecognition(
            status="skipped",
            model=resolved_model,
            error="empty_source_rect",
            source_rect=_rect_tuple(rect),
        )
    key = (api_key or _configured_gemini_api_key()).strip()
    mock = os.environ.get(GEMINI_MATH_MOCK_RESPONSE_ENV, "").strip()
    if not key and not mock:
        return MathAIRecognition(
            status="skipped",
            model=resolved_model,
            error="missing_gemini_api_key",
            source_rect=_rect_tuple(rect),
        )

    started = time.perf_counter()
    try:
        parsed = json.loads(mock) if mock else _request_gemini_math_with_retries(
            page,
            rect,
            key,
            resolved_model,
            timeout_ms,
            max_retries=max_retries,
            text_hint=text_hint,
            token_hints=token_hints,
        )
    except Exception as exc:  # noqa: BLE001 - caller records and falls back locally
        return MathAIRecognition(
            status="error",
            model=resolved_model,
            error=redact_error(str(exc)),
            latency_ms=_elapsed_ms(started),
            source_rect=_rect_tuple(rect),
        )

    result = _parse_math_response(
        parsed,
        model=resolved_model,
        started=started,
        source_rect=rect,
        text_hint=text_hint,
    )
    if result.confidence < float(min_confidence):
        result.status = "rejected"
        if not result.error:
            result.error = "low_confidence"
    if not (result.hancom_eqn or result.latex or result.plain_text):
        result.status = "rejected"
        result.error = result.error or "empty_math_result"
    if result.validation_issues and result.status == "accepted":
        result.status = "rejected"
        result.error = result.error or "; ".join(result.validation_issues[:3])
    return result


def _request_gemini_math_with_retries(
    page: fitz.Page,
    source_rect: fitz.Rect,
    api_key: str,
    model: str,
    timeout_ms: int,
    *,
    max_retries: int,
    text_hint: str | None,
    token_hints: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(max(0, max_retries) + 1):
        if attempt > 0:
            time.sleep(min(1.0 * attempt, 3.0))
        try:
            return _request_gemini_math(
                page,
                source_rect,
                api_key,
                model,
                timeout_ms,
                text_hint=text_hint,
                token_hints=token_hints,
            )
        except Exception as exc:  # noqa: BLE001 - provider errors are inspected by text below.
            last_exc = exc
            if not _is_retryable_math_ai_error(exc):
                break
    raise RuntimeError(redact_error(str(last_exc)) if last_exc else "Gemini math recognition failed")


def redact_error(message: str) -> str:
    text = str(message or "")
    text = _API_KEY_RE.sub("[REDACTED_API_KEY]", text)
    text = re.sub(r"([?&]key=)[^&\s\"']+", r"\1[REDACTED_API_KEY]", text)
    return text


def _is_retryable_math_ai_error(exc: Exception) -> bool:
    message = str(exc).lower()
    retry_markers = (
        "http 408",
        "http 409",
        "http 425",
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "unavailable",
        "rate",
    )
    return any(marker in message for marker in retry_markers)


def _request_gemini_math(
    page: fitz.Page,
    source_rect: fitz.Rect,
    api_key: str,
    model: str,
    timeout_ms: int,
    *,
    text_hint: str | None = None,
    token_hints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    media_type, image_data = _encode_page_crop(page, source_rect)
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": media_type, "data": image_data}},
                    {"text": _math_prompt(text_hint=text_hint, token_hints=token_hints)},
                ],
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _MATH_RESPONSE_SCHEMA,
            "maxOutputTokens": 2048,
            "temperature": 0.0,
        },
    }
    if model.startswith("gemini-3"):
        payload["generationConfig"]["thinkingConfig"] = {"thinkingLevel": "low"}
    url = f"{GEMINI_API_BASE}/{model}:generateContent"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=max(1.0, timeout_ms / 1000.0)) as resp:
            response = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(redact_error(f"Gemini math recognition failed with HTTP {exc.code}: {body}")) from exc
    text = _extract_gemini_text(response)
    if not text:
        raise RuntimeError(f"Gemini math recognition returned no text (finish={_finish_reason(response)})")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Gemini math recognition JSON decode failed: {exc}: {text[:500]}") from exc


def _parse_math_response(
    parsed: dict[str, Any],
    *,
    model: str,
    started: float,
    source_rect: fitz.Rect,
    text_hint: str | None = None,
) -> MathAIRecognition:
    confidence = _safe_float(parsed.get("confidence"), 0.0)
    reading_order: list[dict[str, str]] = []
    for item in parsed.get("reading_order") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        role = str(item.get("role") or "other").strip() or "other"
        if text:
            reading_order.append({"text": text, "role": role})
    plain_text = _clean_ai_math_string(parsed.get("plain_text"))
    latex = _normalize_ai_latex(parsed.get("latex"))
    hancom_eqn = _normalize_ai_hancom(parsed.get("hancom_eqn"))
    hancom_eqn = _best_hancom_eqn(hancom_eqn, latex, plain_text)
    validation_issues = _validate_math_ai_payload(
        plain_text=plain_text,
        latex=latex,
        hancom_eqn=hancom_eqn,
        reading_order=reading_order,
        text_hint=text_hint,
    )
    return MathAIRecognition(
        status="accepted",
        model=model,
        confidence=max(0.0, min(1.0, confidence)),
        plain_text=plain_text,
        latex=latex,
        hancom_eqn=hancom_eqn,
        reading_order=reading_order,
        notes=str(parsed.get("notes") or "").strip(),
        latency_ms=_elapsed_ms(started),
        source_rect=_rect_tuple(source_rect),
        raw_response=parsed,
        validation_issues=validation_issues,
    )


def _clean_ai_math_string(value: Any) -> str:
    text = str(value or "").strip()
    text = _LATEX_FENCE_RE.sub("", text).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return text


def _normalize_ai_latex(value: Any) -> str:
    text = _clean_ai_math_string(value)
    if not text:
        return ""
    for prefix, suffix in (("$", "$"), (r"\(", r"\)"), (r"\[", r"\]")):
        if text.startswith(prefix) and text.endswith(suffix):
            text = text[len(prefix) : len(text) - len(suffix)].strip()
    text = text.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    text = text.replace("\\left.", "").replace("\\right.", "")
    text = re.sub(r"\\operatorname\{([^{}]{1,40})\}", r"\\mathrm{\1}", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_ai_hancom(value: Any) -> str:
    text = _clean_ai_math_string(value)
    if not text:
        return ""
    text = text.replace("\\leq", "<=").replace("\\geq", ">=").replace("\\neq", "!=")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _best_hancom_eqn(*candidates: str) -> str:
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        try:
            from app.hwpx_writer import _hancom_eqn_script

            converted = _hancom_eqn_script(text)
        except Exception:
            converted = None
        if converted:
            return converted
    return str(candidates[0] or candidates[1] or candidates[2] or "").strip()


def _validate_math_ai_payload(
    *,
    plain_text: str,
    latex: str,
    hancom_eqn: str,
    reading_order: list[dict[str, str]],
    text_hint: str | None,
) -> list[str]:
    issues: list[str] = []
    combined = "\n".join(value for value in (plain_text, latex, hancom_eqn) if value)
    lower = combined.lower()
    if any(marker in lower for marker in _SEVERE_RESPONSE_MARKERS):
        issues.append("non_math_refusal_text")
    if any(char in combined for char in _BAD_MATH_CHARS):
        issues.append("unresolved_placeholder")
    if any(0xE000 <= ord(char) <= 0xF8FF for char in combined):
        issues.append("unresolved_pua")
    for label, value in (("latex", latex), ("hancom_eqn", hancom_eqn)):
        if value and not _balanced_math_delimiters(value):
            issues.append(f"unbalanced_{label}")
    if text_hint and _hint_has_fraction_signal(text_hint) and not _result_has_fraction_signal(combined):
        issues.append("missing_fraction_structure_from_hint")
    if not reading_order:
        issues.append("empty_reading_order")
    return issues


def _balanced_math_delimiters(value: str) -> bool:
    pairs = {"{": "}", "[": "]", "(": ")"}
    stack: list[str] = []
    escaped = False
    for char in str(value or ""):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in pairs:
            stack.append(pairs[char])
        elif char in pairs.values():
            if not stack or stack.pop() != char:
                return False
    return not stack


def _hint_has_fraction_signal(value: str) -> bool:
    text = str(value or "")
    return any(token in text for token in ("\\frac", " over ", "\ue06d", "□")) or bool(re.search(r"\d+\s*/\s*\d+", text))


def _result_has_fraction_signal(value: str) -> bool:
    text = str(value or "")
    return any(token in text for token in ("\\frac", " over ", "OVER", "/"))


def _configured_gemini_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    try:
        from app.recognition.settings import load_user_settings

        return str(load_user_settings().get("gemini_api_key") or "").strip()
    except Exception:
        return ""


def _encode_page_crop(page: fitz.Page, source_rect: fitz.Rect) -> tuple[str, str]:
    clip = fitz.Rect(source_rect)
    clip.x0 = max(float(page.rect.x0), clip.x0 - 3.0)
    clip.y0 = max(float(page.rect.y0), clip.y0 - 3.0)
    clip.x1 = min(float(page.rect.x1), clip.x1 + 3.0)
    clip.y1 = min(float(page.rect.y1), clip.y1 + 3.0)
    pix = page.get_pixmap(matrix=fitz.Matrix(4.0, 4.0), clip=clip, alpha=False)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return "image/png", base64.b64encode(buf.getvalue()).decode("ascii")


def _math_prompt(*, text_hint: str | None = None, token_hints: list[dict[str, Any]] | None = None) -> str:
    hint_block = ""
    clean_hint = _compact_hint(text_hint)
    clean_tokens = _compact_tokens(token_hints)
    if clean_hint or clean_tokens:
        hint_block = (
            "\n\nLocal PDF extraction hints follow. They may contain broken private-use glyphs or placeholders; "
            "use them only as reading-order and alignment hints, while the crop image remains authoritative.\n"
            f"normalized_text_hint: {clean_hint or '(none)'}\n"
            f"token_bbox_hints: {json.dumps(clean_tokens, ensure_ascii=False)}"
        )
    return (
        "You are reading a cropped math expression from a Korean CSAT/KICE-style exam PDF. "
        "Return JSON only. Do not solve, explain, translate, simplify, or invent content. "
        "Recover the exact visible expression and its reading order. Pay special attention "
        "to fractions, radicals, limits, integrals, sums, superscripts, subscripts, and "
        "Korean exam answer-choice fractions. If prose is present, focus on the math "
        "expression inside the crop.\n\n"
        "For hancom_eqn, use Hancom Equation script where possible: "
        "'{a} over {b}' for fractions, 'sqrt {x}' for roots, '_{...}' and '^{...}' "
        "for scripts, '<=' and '>=' for inequalities, and 'lim_{...}' for limits. "
        "If LaTeX and Hancom disagree, make LaTeX canonical and derive Hancom from it. "
        "Use a confidence below 0.65 if the expression is ambiguous."
        f"{hint_block}"
    )


def _compact_hint(value: str | None) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:1200]


def _compact_tokens(tokens: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    for item in tokens or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        clean.append(
            {
                "text": text[:20],
                "x": _round_hint_number(item.get("x")),
                "y": _round_hint_number(item.get("y")),
                "w": _round_hint_number(item.get("w")),
                "h": _round_hint_number(item.get("h")),
            }
        )
        if len(clean) >= 80:
            break
    return clean


def _round_hint_number(value: Any) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def _extract_gemini_text(response: dict[str, Any]) -> str:
    candidates = response.get("candidates") or []
    if not candidates:
        return ""
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    return "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))


def _finish_reason(response: dict[str, Any]) -> str:
    candidates = response.get("candidates") or []
    if not candidates:
        return "no_candidates"
    return str(candidates[0].get("finishReason") or "unknown")


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _elapsed_ms(started: float) -> int:
    return int(round((time.perf_counter() - started) * 1000.0))


def _rect_tuple(rect: fitz.Rect) -> tuple[float, float, float, float]:
    return (
        round(float(rect.x0), 3),
        round(float(rect.y0), 3),
        round(float(rect.x1), 3),
        round(float(rect.y1), 3),
    )
