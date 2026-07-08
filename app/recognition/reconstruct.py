#!/usr/bin/env python3
"""Provider-agnostic problem-image reconstruction (Gemini / OpenAI).

edb_make/image_reconstruction_backend.py 를 그대로 포팅한 것. 공통 IR(schema)에
의존하지 않으며, PIL(선택)·numpy(선택) 외에 새로운 의존성을 끌어오지 않는다.
API 키가 없으면 각 함수가 ``ValueError`` 를 던지므로 호출부에서 graceful하게
건너뛸 수 있다(AI는 절대 필수가 아니다).
"""
from __future__ import annotations

import base64
import json
import mimetypes
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

try:
    import numpy as np  # type: ignore
except ImportError:  # pragma: no cover
    np = None


OPENAI_IMAGE_EDIT_URL = "https://api.openai.com/v1/images/edits"
GEMINI_IMAGE_API_BASE = "https://generativelanguage.googleapis.com/v1/models"

# NOTE: The default model ids below (``gemini-3.1-flash-image`` / ``gpt-image-2``)
# are forward-dated placeholders carried over verbatim from edb_make. Verify
# them against the live provider catalogs before relying on them in production.
DEFAULT_IMAGE_RECONSTRUCTION_PROVIDER = "gemini"
DEFAULT_GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"
DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-2"
DEFAULT_IMAGE_QUALITY = "high"
DEFAULT_IMAGE_SIZE = "auto"
DEFAULT_RECONSTRUCTION_UPSCALE_FACTOR = 2.0
DEFAULT_RECONSTRUCTION_MAX_PIXELS = 16_000_000
DEFAULT_TRANSPARENT_INK_RGB = (248, 248, 246)


DEFAULT_RECONSTRUCTION_PROMPT = """Edit the provided exam-problem crop into a clean high-resolution transparent PNG.

Preserve the source content exactly:
- Keep every Korean character, English word, number, equation, symbol, option label, diagram, table, graph, arrow, and relative layout unchanged.
- Do not solve, explain, translate, summarize, replace, omit, or invent any text or mathematical content.
- Do not add headers, page numbers, watermarks, decorations, extra marks, shadows, or decorative backgrounds.
- If a PDF page number, header/footer marker, page-corner badge, website watermark, or scanner overlay appears at an outer edge, remove it unless it is part of the actual problem content.

Improve only visual quality:
- Reconstruct as a sharp, high-resolution asset at least 2x the source pixel detail while keeping the original aspect ratio and composition.
- Rebuild glyph strokes and mathematical notation as OCR-safe clean print: Korean letters, numbers, operators, subscripts, superscripts, fractions, roots, vectors, units, and labels must be crisp and readable.
- Make thin lines, table borders, axes, arrows, graph ticks, diagram labels, and small option text clear without thickening or changing geometry.
- Remove blur, scanner noise, paper texture, compression artifacts, and low-resolution jagged edges.
- Output chalk-white ink/lines on a fully transparent alpha background. The background must be transparent, not black, white, gray, or checkerboard.
- Keep diagrams and tables faithful to the original geometry.
"""


@dataclass(slots=True)
class ImageReconstructionResult:
    output_path: Path
    provider: str
    model: str
    prompt: str
    source_path: Path
    latency_ms: int
    revised_prompt: str | None = None
    usage: dict[str, Any] | None = None
    response_id: str | None = None
    response_text: str | None = None
    mime_type: str | None = None
    postprocess: dict[str, Any] | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "status": "applied",
            "provider": self.provider,
            "model": self.model,
            "source_path": str(self.source_path),
            "output_path": str(self.output_path),
            "latency_ms": self.latency_ms,
            "revised_prompt": self.revised_prompt,
            "usage": self.usage or {},
            "response_id": self.response_id,
            "response_text": self.response_text,
            "mime_type": self.mime_type,
            "postprocess": self.postprocess or {},
        }


def normalize_image_provider(provider: str | None) -> str:
    value = (provider or DEFAULT_IMAGE_RECONSTRUCTION_PROVIDER).strip().lower()
    aliases = {
        "google": "gemini",
        "gemini": "gemini",
        "nano": "gemini",
        "nanobanana": "gemini",
        "nano-banana": "gemini",
        "nanobanana2": "gemini",
        "nano-banana-2": "gemini",
        "gemini-flash-image-2": "gemini",
        "gemini flash image 2": "gemini",
        "openai": "openai",
        "gpt": "openai",
        "gpt-image": "openai",
        "gpt-image-2": "openai",
    }
    normalized = aliases.get(value)
    if not normalized:
        raise ValueError(f"unsupported image reconstruction provider: {provider!r}")
    return normalized


def default_image_model(provider: str | None) -> str:
    normalized = normalize_image_provider(provider)
    if normalized == "gemini":
        return DEFAULT_GEMINI_IMAGE_MODEL
    return DEFAULT_OPENAI_IMAGE_MODEL


def normalize_image_model(provider: str | None, model: str | None) -> str:
    normalized_provider = normalize_image_provider(provider)
    value = (model or "").strip()
    if not value:
        return default_image_model(normalized_provider)
    lower = value.lower()
    if normalized_provider == "gemini" and lower in {
        "nanobanana2",
        "nano-banana-2",
        "gemini-flash-image-2",
        "gemini flash image 2",
    }:
        return DEFAULT_GEMINI_IMAGE_MODEL
    if normalized_provider == "openai" and lower in {"gpt image 2", "gpt-image"}:
        return DEFAULT_OPENAI_IMAGE_MODEL
    return value


def reconstruct_problem_image(
    source_path: str | Path,
    output_path: str | Path,
    *,
    api_key: str,
    provider: str = DEFAULT_IMAGE_RECONSTRUCTION_PROVIDER,
    model: str | None = None,
    prompt: str = DEFAULT_RECONSTRUCTION_PROMPT,
    quality: str = DEFAULT_IMAGE_QUALITY,
    size: str = DEFAULT_IMAGE_SIZE,
    timeout_ms: int = 120000,
    transparent_background: bool = True,
    sharpen: bool = True,
) -> ImageReconstructionResult:
    normalized_provider = normalize_image_provider(provider)
    normalized_model = normalize_image_model(normalized_provider, model)
    if normalized_provider == "gemini":
        return _reconstruct_with_gemini(
            source_path,
            output_path,
            api_key=api_key,
            model=normalized_model,
            prompt=prompt,
            timeout_ms=timeout_ms,
            transparent_background=transparent_background,
            sharpen=sharpen,
        )
    return _reconstruct_with_openai(
        source_path,
        output_path,
        api_key=api_key,
        model=normalized_model,
        prompt=prompt,
        quality=quality,
        size=size,
        timeout_ms=timeout_ms,
        transparent_background=transparent_background,
        sharpen=sharpen,
    )


def _reconstruct_with_gemini(
    source_path: str | Path,
    output_path: str | Path,
    *,
    api_key: str,
    model: str,
    prompt: str,
    timeout_ms: int,
    transparent_background: bool,
    sharpen: bool,
) -> ImageReconstructionResult:
    source = Path(source_path)
    output = Path(output_path)
    if not source.exists():
        raise FileNotFoundError(f"source image not found: {source}")
    key = api_key.strip()
    if not key:
        raise ValueError("GEMINI_API_KEY is required for image reconstruction")

    content_type = mimetypes.guess_type(str(source))[0] or "image/png"
    image_data = base64.b64encode(source.read_bytes()).decode("ascii")
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt.strip() or DEFAULT_RECONSTRUCTION_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": content_type,
                            "data": image_data,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
        },
    }
    req = request.Request(
        f"{GEMINI_IMAGE_API_BASE}/{model}:generateContent",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": key,
        },
        method="POST",
    )

    started_at = time.perf_counter()
    try:
        with request.urlopen(req, timeout=max(1.0, timeout_ms / 1000.0)) as resp:
            response_payload = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini image reconstruction failed ({exc.code}): {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Gemini image reconstruction failed: {exc.reason}") from exc

    image_b64, mime_type, response_text = _extract_gemini_image(response_payload)
    if not image_b64:
        finish_reason = _gemini_finish_reason(response_payload)
        raise RuntimeError(f"Gemini image reconstruction returned no image data (finish={finish_reason})")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(base64.b64decode(image_b64))
    postprocess = postprocess_reconstructed_problem_image(
        output,
        transparent_background=transparent_background,
        sharpen=sharpen,
        source_size=_read_image_size(source),
    )
    latency_ms = int(round((time.perf_counter() - started_at) * 1000.0))
    return ImageReconstructionResult(
        output_path=output,
        provider="gemini",
        model=model,
        prompt=prompt.strip() or DEFAULT_RECONSTRUCTION_PROMPT,
        source_path=source,
        latency_ms=latency_ms,
        usage=response_payload.get("usageMetadata") if isinstance(response_payload.get("usageMetadata"), dict) else None,
        response_id=str(response_payload.get("responseId") or response_payload.get("id") or "") or None,
        response_text=response_text or None,
        mime_type=mime_type,
        postprocess=postprocess,
    )


def _reconstruct_with_openai(
    source_path: str | Path,
    output_path: str | Path,
    *,
    api_key: str,
    model: str,
    prompt: str,
    quality: str,
    size: str,
    timeout_ms: int,
    transparent_background: bool,
    sharpen: bool,
) -> ImageReconstructionResult:
    source = Path(source_path)
    output = Path(output_path)
    if not source.exists():
        raise FileNotFoundError(f"source image not found: {source}")
    key = api_key.strip()
    if not key:
        raise ValueError("OPENAI_API_KEY is required for image reconstruction")

    fields: list[tuple[str, str]] = [
        ("model", model.strip() or DEFAULT_OPENAI_IMAGE_MODEL),
        ("prompt", prompt.strip() or DEFAULT_RECONSTRUCTION_PROMPT),
        ("size", size.strip() or DEFAULT_IMAGE_SIZE),
        ("quality", quality.strip() or DEFAULT_IMAGE_QUALITY),
    ]
    content_type = mimetypes.guess_type(str(source))[0] or "image/png"
    body, multipart_type = _encode_multipart(
        fields=fields,
        files=[
            (
                "image[]",
                source.name or "problem.png",
                content_type,
                source.read_bytes(),
            )
        ],
    )
    req = request.Request(
        OPENAI_IMAGE_EDIT_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": multipart_type,
        },
        method="POST",
    )

    started_at = time.perf_counter()
    try:
        with request.urlopen(req, timeout=max(1.0, timeout_ms / 1000.0)) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI image reconstruction failed ({exc.code}): {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"OpenAI image reconstruction failed: {exc.reason}") from exc

    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise RuntimeError("OpenAI image reconstruction returned no image data")
    first = data[0] if isinstance(data[0], dict) else {}
    b64_image = first.get("b64_json")
    if not isinstance(b64_image, str) or not b64_image:
        raise RuntimeError("OpenAI image reconstruction response did not include b64_json")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(base64.b64decode(b64_image))
    postprocess = postprocess_reconstructed_problem_image(
        output,
        transparent_background=transparent_background,
        sharpen=sharpen,
        source_size=_read_image_size(source),
    )
    latency_ms = int(round((time.perf_counter() - started_at) * 1000.0))
    return ImageReconstructionResult(
        output_path=output,
        provider="openai",
        model=str(fields[0][1]),
        prompt=str(fields[1][1]),
        source_path=source,
        latency_ms=latency_ms,
        revised_prompt=first.get("revised_prompt") if isinstance(first.get("revised_prompt"), str) else None,
        usage=payload.get("usage") if isinstance(payload.get("usage"), dict) else first.get("usage"),
        response_id=str(payload.get("id")) if payload.get("id") else None,
        mime_type="image/png",
        postprocess=postprocess,
    )


def postprocess_reconstructed_problem_image(
    output_path: str | Path,
    *,
    transparent_background: bool = True,
    sharpen: bool = True,
    source_size: tuple[int, int] | None = None,
    upscale_factor: float = DEFAULT_RECONSTRUCTION_UPSCALE_FACTOR,
    max_upscaled_pixels: int = DEFAULT_RECONSTRUCTION_MAX_PIXELS,
) -> dict[str, Any]:
    try:
        from PIL import Image, ImageFilter, ImageOps
    except ImportError:
        return {"status": "skipped", "reason": "pillow_unavailable"}

    path = Path(output_path)
    image = Image.open(path).convert("RGBA")
    original_size = image.size
    if sharpen:
        alpha = image.getchannel("A")
        rgb = ImageOps.autocontrast(image.convert("RGB"), cutoff=0.2)
        rgb = rgb.filter(ImageFilter.UnsharpMask(radius=0.8, percent=150, threshold=2))
        image = rgb.convert("RGBA")
        image.putalpha(alpha)

    image, transparency_stats = clean_problem_image_transparency(
        image,
        transparent_background=transparent_background,
        remove_corner_page_artifacts=True,
    )

    target_size, resize_stats = _reconstruction_resize_target(
        current_size=image.size,
        source_size=source_size,
        upscale_factor=upscale_factor,
        max_pixels=max_upscaled_pixels,
    )
    if target_size != image.size:
        image = image.resize(target_size, _lanczos_resample(Image))

    clarity_stats: dict[str, Any] = {}
    if transparent_background and sharpen:
        image, clarity_stats = _boost_transparent_ink_clarity(image)

    image.save(path, format="PNG", optimize=True)
    return {
        "status": "applied",
        "transparent_background": bool(transparent_background),
        "sharpen": bool(sharpen),
        "input_width": original_size[0],
        "input_height": original_size[1],
        "width": image.width,
        "height": image.height,
        "source_width": source_size[0] if source_size else None,
        "source_height": source_size[1] if source_size else None,
        **resize_stats,
        **clarity_stats,
        **transparency_stats,
    }


def _read_image_size(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as image:
            return image.size
    except OSError:
        return None


def _lanczos_resample(image_module: Any) -> Any:
    resampling = getattr(image_module, "Resampling", image_module)
    return resampling.LANCZOS


def _reconstruction_resize_target(
    *,
    current_size: tuple[int, int],
    source_size: tuple[int, int] | None,
    upscale_factor: float,
    max_pixels: int,
) -> tuple[tuple[int, int], dict[str, Any]]:
    width, height = current_size
    source_width, source_height = _valid_size(source_size)
    if width <= 0 or height <= 0 or not source_width or not source_height or upscale_factor <= 1:
        return current_size, {
            "upscaled": False,
            "upscale_scale": 1.0,
            "upscale_factor": float(upscale_factor),
            "upscale_capped": False,
        }

    target_width = max(width, int(round(source_width * upscale_factor)))
    target_height = max(height, int(round(source_height * upscale_factor)))
    scale = max(target_width / width, target_height / height, 1.0)
    next_width = max(width, int(round(width * scale)))
    next_height = max(height, int(round(height * scale)))
    capped = False

    pixel_cap = max(width * height, int(max_pixels or 0))
    if next_width * next_height > pixel_cap:
        capped = True
        cap_scale = (pixel_cap / max(1, next_width * next_height)) ** 0.5
        next_width = max(width, int(round(next_width * cap_scale)))
        next_height = max(height, int(round(next_height * cap_scale)))
        scale = next_width / width

    return (next_width, next_height), {
        "upscaled": (next_width, next_height) != current_size,
        "upscale_scale": round(float(scale), 4),
        "upscale_factor": float(upscale_factor),
        "upscale_capped": capped,
    }


def _valid_size(value: tuple[int, int] | None) -> tuple[int | None, int | None]:
    if not value or len(value) != 2:
        return None, None
    width, height = value
    if width <= 0 or height <= 0:
        return None, None
    return int(width), int(height)


def _boost_transparent_ink_clarity(image: Any) -> tuple[Any, dict[str, Any]]:
    try:
        from PIL import Image, ImageFilter, ImageOps
    except ImportError:
        return image, {}

    alpha = image.getchannel("A")
    alpha_values = alpha.get_flattened_data() if hasattr(alpha, "get_flattened_data") else alpha.getdata()
    visible_before = [int(value) for value in alpha_values if value > 6]
    if not visible_before:
        return image, {"ink_clarity": "empty"}

    alpha = ImageOps.autocontrast(alpha)
    alpha = alpha.filter(ImageFilter.UnsharpMask(radius=0.7, percent=180, threshold=1))

    def boost_alpha(value: int) -> int:
        if value <= 6:
            return 0
        if value >= 210:
            return 255
        boosted = int(round(((value / 255.0) ** 0.45) * 255))
        return max(value, min(255, boosted))

    alpha = alpha.point(boost_alpha)
    next_values = alpha.get_flattened_data() if hasattr(alpha, "get_flattened_data") else alpha.getdata()
    visible_after = [int(value) for value in next_values if value > 6]

    clarified = Image.new("RGBA", image.size, (*DEFAULT_TRANSPARENT_INK_RGB, 0))
    clarified.putalpha(alpha)
    before_mean = sum(visible_before) / len(visible_before)
    after_mean = sum(visible_after) / len(visible_after) if visible_after else 0.0
    return clarified, {
        "ink_clarity": "boosted",
        "ink_alpha_mean_before": round(before_mean, 2),
        "ink_alpha_mean_after": round(after_mean, 2),
    }


def clean_problem_image_transparency(
    image: Any,
    *,
    transparent_background: bool = True,
    remove_corner_page_artifacts: bool = True,
) -> tuple[Any, dict[str, Any]]:
    """Return an RGBA image with uniform page/board backgrounds converted to alpha.

    Gemini/OpenAI may return either black-board style output or paper-white
    output even when prompted for transparency. Border sampling lets us remove
    whichever flat background the model produced while preserving chalk/text
    strokes and graph lines.
    """
    try:
        from PIL import Image
    except ImportError:
        return image, {"status": "skipped", "reason": "pillow_unavailable"}

    rgba = image.convert("RGBA")
    total_pixels = max(1, rgba.width * rgba.height)
    transparent_pixels = 0
    partial_pixels = 0
    background_color: tuple[int, int, int] | None = None
    background_luminance: float | None = None
    background_kind = "none"
    alpha_backend = "none"

    if transparent_background and rgba.width > 0 and rgba.height > 0:
        background_color = _estimate_border_background(rgba)
        background_luminance = _luminance(background_color)
        background_kind = "dark" if background_luminance <= 128 else "light"
        if np is not None:
            rgba, transparent_pixels, partial_pixels = _remove_background_with_numpy(
                rgba,
                background_color=background_color,
                background_luminance=background_luminance,
                background_kind=background_kind,
            )
            alpha_backend = "numpy"
        else:
            pixels = []
            image_pixels = rgba.get_flattened_data() if hasattr(rgba, "get_flattened_data") else rgba.getdata()
            for r, g, b, a in image_pixels:
                next_alpha = _alpha_after_background_removal(
                    r,
                    g,
                    b,
                    a,
                    background_color=background_color,
                    background_luminance=background_luminance,
                    background_kind=background_kind,
                )
                if next_alpha <= 0:
                    transparent_pixels += 1
                elif next_alpha < a:
                    partial_pixels += 1
                pixels.append((r, g, b, max(0, min(255, next_alpha))))
            rgba.putdata(pixels)
            alpha_backend = "python"

    removed_artifacts = 0
    if remove_corner_page_artifacts:
        removed_artifacts = _remove_corner_page_artifacts(rgba)
        if removed_artifacts:
            alpha_pixels = rgba.getchannel("A").get_flattened_data() if hasattr(rgba.getchannel("A"), "get_flattened_data") else rgba.getchannel("A").getdata()
            transparent_pixels = sum(1 for a in alpha_pixels if a <= 0)

    stats: dict[str, Any] = {
        "background_kind": background_kind,
        "background_color": list(background_color) if background_color else None,
        "background_luminance": round(background_luminance, 2) if background_luminance is not None else None,
        "alpha_backend": alpha_backend,
        "transparent_pixels": transparent_pixels,
        "partial_alpha_pixels": partial_pixels,
        "transparent_ratio": round(transparent_pixels / total_pixels, 4),
        "removed_corner_artifacts": removed_artifacts,
    }
    return rgba, stats


def _remove_background_with_numpy(
    image: Any,
    *,
    background_color: tuple[int, int, int],
    background_luminance: float,
    background_kind: str,
) -> tuple[Any, int, int]:
    if np is None:
        raise RuntimeError("numpy is required for _remove_background_with_numpy")
    from PIL import Image

    arr = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    rgb = arr[..., :3].astype(np.float32)
    original_alpha = arr[..., 3].astype(np.float32)
    alpha = original_alpha.copy()
    background = np.asarray(background_color, dtype=np.float32)

    luminance = (0.299 * rgb[..., 0]) + (0.587 * rgb[..., 1]) + (0.114 * rgb[..., 2])
    saturation = rgb.max(axis=2) - rgb.min(axis=2)
    distance = np.sqrt(np.sum((rgb - background) ** 2, axis=2))
    visible = original_alpha > 0

    if background_kind == "dark":
        remove = visible & (distance <= 22.0) & (luminance <= background_luminance + 18.0)
        alpha[remove] = 0.0
        partial = (
            visible
            & ~remove
            & (distance <= 72.0)
            & (luminance <= background_luminance + 62.0)
            & (saturation <= 42.0)
        )
        keep = np.clip((distance - 22.0) / 50.0, 0.0, 1.0) * 255.0
        alpha[partial] = np.minimum(original_alpha[partial], np.rint(keep[partial]))
    else:
        handled = np.zeros(alpha.shape, dtype=bool)
        remove = (
            visible
            & (saturation <= 20.0)
            & (luminance >= max(238.0, background_luminance - 8.0))
            & (distance <= 34.0)
        )
        alpha[remove] = 0.0
        handled |= remove

        partial = (
            visible
            & ~handled
            & (saturation <= 32.0)
            & (luminance >= 210.0)
            & (distance <= 88.0)
        )
        keep = np.clip((distance - 34.0) / 54.0, 0.0, 1.0) * 255.0
        alpha[partial] = np.minimum(original_alpha[partial], np.rint(keep[partial]))
        handled |= partial

        remove_bright = visible & ~handled & (saturation <= 20.0) & (luminance >= 248.0)
        alpha[remove_bright] = 0.0
        handled |= remove_bright

        fade_bright = visible & ~handled & (saturation <= 28.0) & (luminance >= 218.0)
        faded = np.clip(((255.0 - luminance) / 37.0) * 255.0, 0.0, 255.0)
        alpha[fade_bright] = np.minimum(original_alpha[fade_bright], np.rint(faded[fade_bright]))

    next_alpha = np.clip(alpha, 0.0, 255.0).astype(np.uint8)
    out = arr.copy()
    out[..., 3] = next_alpha
    transparent_pixels = int(np.count_nonzero(next_alpha <= 0))
    partial_pixels = int(np.count_nonzero((next_alpha > 0) & (next_alpha < arr[..., 3])))
    return Image.fromarray(out, mode="RGBA"), transparent_pixels, partial_pixels


def _estimate_border_background(image: Any) -> tuple[int, int, int]:
    width, height = image.size
    border = max(2, min(24, int(round(min(width, height) * 0.035))))
    step = max(1, int(round(min(width, height) / 220)))
    pixels = image.load()

    corner_samples: list[tuple[int, int, int]] = []
    corner_boxes = [
        (0, 0, min(border, width), min(border, height)),
        (max(0, width - border), 0, width, min(border, height)),
        (0, max(0, height - border), min(border, width), height),
        (max(0, width - border), max(0, height - border), width, height),
    ]
    for left, top, right, bottom in corner_boxes:
        for y in range(top, bottom, step):
            for x in range(left, right, step):
                r, g, b, a = pixels[x, y]
                if a >= 180:
                    corner_samples.append((r, g, b))
    if len(corner_samples) >= 4:
        return _median_rgb(corner_samples)

    samples: list[tuple[int, int, int]] = []
    for y in range(0, height, step):
        for x in range(0, width, step):
            if x >= border and x < width - border and y >= border and y < height - border:
                continue
            r, g, b, a = pixels[x, y]
            if a >= 180:
                samples.append((r, g, b))
    if not samples:
        return (255, 255, 255)
    return _median_rgb(samples)


def _median_rgb(samples: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    samples.sort(key=lambda item: (_luminance(item), item[0], item[1], item[2]))
    return samples[len(samples) // 2]


def _alpha_after_background_removal(
    r: int,
    g: int,
    b: int,
    a: int,
    *,
    background_color: tuple[int, int, int],
    background_luminance: float,
    background_kind: str,
) -> int:
    if a <= 0:
        return 0

    luminance = _luminance((r, g, b))
    saturation = max(r, g, b) - min(r, g, b)
    distance = ((r - background_color[0]) ** 2 + (g - background_color[1]) ** 2 + (b - background_color[2]) ** 2) ** 0.5

    if background_kind == "dark":
        # Remove black/charcoal board rectangles produced by image models,
        # while keeping white/gray chalk strokes and graph guide lines.
        if distance <= 22 and luminance <= background_luminance + 18:
            return 0
        if distance <= 72 and luminance <= background_luminance + 62 and saturation <= 42:
            keep = (distance - 22.0) / 50.0
            return min(a, int(round(max(0.0, min(1.0, keep)) * 255)))
        return a

    # Light paper background or off-white model output.
    if saturation <= 20 and luminance >= max(238, background_luminance - 8) and distance <= 34:
        return 0
    if saturation <= 32 and luminance >= 210 and distance <= 88:
        keep = (distance - 34.0) / 54.0
        return min(a, int(round(max(0.0, min(1.0, keep)) * 255)))
    if saturation <= 20 and luminance >= 248:
        return 0
    if saturation <= 28 and luminance >= 218:
        return min(a, int(round(((255 - luminance) / 37.0) * 255)))
    return a


def _remove_corner_page_artifacts(image: Any) -> int:
    """Erase small page-number/header/footer marks glued to safe page corners."""
    width, height = image.size
    if width < 80 or height < 80:
        return 0

    removed = 0
    for side, vertical_edge in (("right", "bottom"), ("left", "bottom"), ("right", "top")):
        roi_width = max(40, int(round(width * 0.24)))
        roi_height = max(36, int(round(height * 0.22)))
        left = width - roi_width if side == "right" else 0
        top = height - roi_height if vertical_edge == "bottom" else 0
        bottom = top + roi_height
        roi = image.crop((left, top, left + roi_width, bottom))
        alpha = roi.getchannel("A")
        bbox = alpha.point(lambda px: 255 if px > 36 else 0).getbbox()
        if bbox is None:
            continue

        x0, y0, x1, y1 = bbox
        box_width = x1 - x0
        box_height = y1 - y0
        if box_width <= 0 or box_height <= 0:
            continue

        touches_outer_edge = x1 >= roi_width - 3 if side == "right" else x0 <= 3
        touches_vertical_edge = y1 >= roi_height - 3 if vertical_edge == "bottom" else y0 <= 3
        if not (touches_outer_edge or touches_vertical_edge):
            continue
        if box_width > width * 0.20 or box_height > height * 0.20:
            continue

        alpha_data = alpha.crop(bbox)
        alpha_values = alpha_data.get_flattened_data() if hasattr(alpha_data, "get_flattened_data") else alpha_data.getdata()
        visible_pixels = sum(1 for px in alpha_values if px > 36)
        if visible_pixels > width * height * 0.018:
            continue

        pad = max(2, int(round(min(width, height) * 0.006)))
        erase_left = max(0, left + x0 - pad)
        erase_top = max(0, top + y0 - pad)
        erase_right = min(width, left + x1 + pad)
        erase_bottom = min(height, top + y1 + pad)
        patch = image.crop((erase_left, erase_top, erase_right, erase_bottom))
        patch_pixels = patch.get_flattened_data() if hasattr(patch, "get_flattened_data") else patch.getdata()
        patch_data = [(r, g, b, 0) for r, g, b, _a in patch_pixels]
        patch.putdata(patch_data)
        image.paste(patch, (erase_left, erase_top))
        removed += 1
    return removed


def _luminance(rgb: tuple[int, int, int]) -> float:
    return (0.299 * rgb[0]) + (0.587 * rgb[1]) + (0.114 * rgb[2])


def _extract_gemini_image(payload: dict[str, Any]) -> tuple[str | None, str | None, str]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return None, None, ""
    text_parts: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        parts = (candidate.get("content") or {}).get("parts") or []
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            if isinstance(part.get("text"), str):
                text_parts.append(part["text"])
            inline_data = part.get("inlineData") or part.get("inline_data")
            if not isinstance(inline_data, dict):
                continue
            data = inline_data.get("data")
            if isinstance(data, str) and data:
                mime_type = inline_data.get("mimeType") or inline_data.get("mime_type")
                return data, str(mime_type) if mime_type else None, "\n".join(text_parts).strip()
    return None, None, "\n".join(text_parts).strip()


def _gemini_finish_reason(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        candidate = candidates[0]
        if isinstance(candidate, dict):
            return str(candidate.get("finishReason") or candidate.get("finish_reason") or "unknown")
    prompt_feedback = payload.get("promptFeedback")
    if isinstance(prompt_feedback, dict):
        return str(prompt_feedback.get("blockReason") or prompt_feedback.get("block_reason") or "prompt_feedback")
    return "unknown"


def _encode_multipart(
    *,
    fields: list[tuple[str, str]],
    files: list[tuple[str, str, str, bytes]],
) -> tuple[bytes, str]:
    boundary = f"codex-edb-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    def add(line: str | bytes) -> None:
        chunks.append(line if isinstance(line, bytes) else line.encode("utf-8"))

    for name, value in fields:
        add(f"--{boundary}\r\n")
        add(f'Content-Disposition: form-data; name="{name}"\r\n\r\n')
        add(str(value))
        add("\r\n")

    for name, filename, content_type, content in files:
        add(f"--{boundary}\r\n")
        safe_filename = filename.replace('"', "")
        add(
            f'Content-Disposition: form-data; name="{name}"; '
            f'filename="{safe_filename}"\r\n'
        )
        add(f"Content-Type: {content_type}\r\n\r\n")
        add(content)
        add("\r\n")

    add(f"--{boundary}--\r\n")
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
