#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from app.recognition.ocr_backend import OCRLine, OCRResult
from app.recognition.schema import BlockType, Box, ContentBlock, PageModel

OCRCacheIdentity = Mapping[str, Any]


def _sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _image_hash(image: Image.Image) -> str:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    return hashlib.sha1(buffer.getvalue()).hexdigest()


def _safe_slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value.strip())
    return slug or "default"


def _stable_ocr_key(identity: OCRCacheIdentity) -> str:
    return _sha1_text(json.dumps(identity, ensure_ascii=False, sort_keys=True))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def default_pipeline_cache_dir(source_path: str | Path | None = None) -> Path:
    # hwp_make 포팅: edb_make 원본은 source_path 옆(또는 cwd)의 ``.pipeline_cache``
    # 디렉터리에 캐시를 썼지만, 여기서는 프로젝트 DATA_DIR 아래 ``recognition_cache``
    # 한 곳으로 모은다. 캐시 키가 content-addressed(이미지/페이지 해시) 이므로
    # 소스별로 디렉터리를 나눌 필요가 없다. ``source_path`` 인자는 원본 API 호환을
    # 위해 유지한다(현재는 사용하지 않음).
    from app.storage import DATA_DIR  # 지연 임포트로 import cycle 회피

    return Path(DATA_DIR) / "recognition_cache"


def _serialize_box(box: Box) -> dict[str, float]:
    return {
        "left": float(box.left),
        "top": float(box.top),
        "width": float(box.width),
        "height": float(box.height),
    }


def _deserialize_box(payload: dict[str, Any]) -> Box:
    return Box(
        left=float(payload.get("left", 0.0)),
        top=float(payload.get("top", 0.0)),
        width=float(payload.get("width", 0.0)),
        height=float(payload.get("height", 0.0)),
    )


def _serialize_ocr_result(result: OCRResult) -> dict[str, Any]:
    return {
        "text": result.text,
        "confidence": result.confidence,
        "backend_name": result.backend_name,
        "metadata": dict(result.metadata),
        "lines": [
            {
                "text": line.text,
                "confidence": line.confidence,
                "bbox": _serialize_box(line.bbox),
            }
            for line in result.lines
        ],
    }


def _deserialize_ocr_result(payload: dict[str, Any]) -> OCRResult:
    lines = [
        OCRLine(
            text=str(line.get("text", "")),
            confidence=float(line.get("confidence", 0.0) or 0.0),
            bbox=_deserialize_box(dict(line.get("bbox") or {})),
        )
        for line in payload.get("lines") or []
        if isinstance(line, dict)
    ]
    metadata = dict(payload.get("metadata") or {})
    metadata["cache_hit"] = True
    return OCRResult(
        text=str(payload.get("text", "")),
        confidence=float(payload["confidence"]) if payload.get("confidence") is not None else None,
        lines=lines,
        backend_name=str(payload.get("backend_name") or "none"),
        metadata=metadata,
    )


def _page_signature(page: PageModel) -> str:
    block_payload = []
    for block in page.blocks:
        block_payload.append(
            {
                "block_id": block.block_id,
                "block_type": block.block_type.value,
                "text": block.text or "",
                "confidence": round(block.confidence, 4) if block.confidence is not None else None,
                "bbox": {
                    "left": round(block.bbox.left, 1),
                    "top": round(block.bbox.top, 1),
                    "width": round(block.bbox.width, 1),
                    "height": round(block.bbox.height, 1),
                },
                "meta": {
                    key: block.metadata.get(key)
                    for key in (
                        "ocr_backend",
                        "display_title",
                        "column_index",
                        "question_band_index",
                        "fallback_reason",
                    )
                    if key in block.metadata
                },
            }
        )
    payload = {
        "page_id": page.page_id,
        "width_px": page.width_px,
        "height_px": page.height_px,
        "ocr_mode": page.metadata.get("ocr_mode"),
        "blocks": block_payload,
    }
    return _sha1_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


class PipelineCache:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_source(cls, source_path: str | Path | None) -> "PipelineCache":
        return cls(default_pipeline_cache_dir(source_path))

    def _ocr_cache_path(self, image: Image.Image, backend_name: str) -> Path:
        image_key = _image_hash(image)
        return self.root_dir / "ocr" / _safe_slug(backend_name) / f"{image_key}.json"

    def _ocr_stable_index_path(self, *, backend_name: str, cache_identity: OCRCacheIdentity) -> Path:
        return self.root_dir / "ocr_index" / _safe_slug(backend_name) / f"{_stable_ocr_key(cache_identity)}.json"

    def _load_ocr_payload(self, path: Path, *, cache_key_kind: str) -> OCRResult | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        result = _deserialize_ocr_result(payload)
        result.metadata["cache_path"] = str(path)
        result.metadata["cache_key_kind"] = cache_key_kind
        return result

    def _load_ocr_result_from_index(self, *, backend_name: str, cache_identity: OCRCacheIdentity) -> OCRResult | None:
        index_path = self._ocr_stable_index_path(
            backend_name=backend_name,
            cache_identity=cache_identity,
        )
        if not index_path.exists():
            return None
        try:
            index_payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(index_payload, dict):
            return None

        target_value = index_payload.get("target") or index_payload.get("payload_path")
        if not isinstance(target_value, str) or not target_value.strip():
            return None
        target_path = Path(target_value)
        if not target_path.is_absolute():
            target_path = self.root_dir / target_path
        try:
            expected_dir = (self.root_dir / "ocr" / _safe_slug(backend_name)).resolve()
            resolved_target = target_path.resolve()
        except OSError:
            return None
        if resolved_target.parent != expected_dir:
            return None

        result = self._load_ocr_payload(resolved_target, cache_key_kind="stable_index")
        if result is not None:
            result.metadata["cache_index_path"] = str(index_path)
        return result

    def load_ocr_result(
        self,
        image: Image.Image,
        *,
        backend_name: str,
        cache_identity: OCRCacheIdentity | None = None,
    ) -> OCRResult | None:
        if cache_identity is not None:
            result = self._load_ocr_result_from_index(
                backend_name=backend_name,
                cache_identity=cache_identity,
            )
            if result is not None:
                return result

        path = self._ocr_cache_path(image, backend_name)
        return self._load_ocr_payload(path, cache_key_kind="image_hash")

    def save_ocr_result(
        self,
        image: Image.Image,
        result: OCRResult,
        *,
        backend_name: str,
        cache_identity: OCRCacheIdentity | None = None,
    ) -> Path:
        path = self._ocr_cache_path(image, backend_name)
        payload = _serialize_ocr_result(result)
        payload["cached_backend_name"] = backend_name
        _write_json_atomic(path, payload)
        if cache_identity is not None:
            index_path = self._ocr_stable_index_path(
                backend_name=backend_name,
                cache_identity=cache_identity,
            )
            _write_json_atomic(
                index_path,
                {
                    "version": "ocr_index_v1",
                    "target": str(path.relative_to(self.root_dir)),
                    "image_sha1": path.stem,
                    "backend_name": backend_name,
                },
            )
        return path

    def _ai_cache_path(
        self,
        *,
        page: PageModel,
        provider: str,
        model: str,
        trigger_reasons: list[str],
    ) -> Path:
        signature_payload = {
            "provider": provider,
            "model": model,
            "trigger_reasons": list(trigger_reasons),
            "page_signature": _page_signature(page),
        }
        signature = _sha1_text(json.dumps(signature_payload, ensure_ascii=False, sort_keys=True))
        return self.root_dir / "ai_repairs" / _safe_slug(provider) / _safe_slug(model) / f"{signature}.json"

    def load_ai_repair(
        self,
        *,
        page: PageModel,
        provider: str,
        model: str,
        trigger_reasons: list[str],
    ) -> tuple[dict[str, Any], str | None] | None:
        path = self._ai_cache_path(page=page, provider=provider, model=model, trigger_reasons=trigger_reasons)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        repair_payload = payload.get("repair_payload")
        if not isinstance(repair_payload, dict):
            return None
        return dict(repair_payload), payload.get("response_id")

    def save_ai_repair(
        self,
        *,
        page: PageModel,
        provider: str,
        model: str,
        trigger_reasons: list[str],
        repair_payload: dict[str, Any],
        response_id: str | None,
    ) -> Path:
        path = self._ai_cache_path(page=page, provider=provider, model=model, trigger_reasons=trigger_reasons)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "provider": provider,
            "model": model,
            "trigger_reasons": list(trigger_reasons),
            "response_id": response_id,
            "repair_payload": repair_payload,
        }
        _write_json_atomic(path, payload)
        return path


def summarize_ocr_cache(blocks: list[ContentBlock]) -> dict[str, int]:
    eligible_blocks = [block for block in blocks if block.block_type not in {BlockType.IMAGE, BlockType.DIAGRAM, BlockType.TABLE}]
    return {
        "eligible_block_count": len(eligible_blocks),
        "ocr_cache_hit_count": sum(1 for block in blocks if block.metadata.get("ocr_cache_hit")),
        "ocr_cache_miss_count": sum(1 for block in blocks if block.metadata.get("ocr_cache_miss")),
    }
