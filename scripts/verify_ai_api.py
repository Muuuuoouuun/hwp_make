"""Small offline contract check for the AI/OCR/math FastAPI router."""
from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app


def _image_base64() -> str:
    image = Image.new("RGB", (32, 24), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def main() -> None:
    client = TestClient(app)

    status = client.get("/api/ai/status")
    assert status.status_code == 200, status.text
    status_payload = status.json()
    assert status_payload["ok"] is True
    assert "mathRecognition" in status_payload["features"]
    assert "ocr" in status_payload["features"]
    assert status_payload["settings"]["geminiApiKey"] == ""
    assert status_payload["settings"]["openAiApiKey"] == ""

    analyzed = client.post("/api/ai/math/analyze", json={"text": r"함수 $f(x)=x^2$의 값"})
    assert analyzed.status_code == 200, analyzed.text
    analyzed_payload = analyzed.json()
    assert analyzed_payload["summary"]["count"] >= 1
    assert analyzed_payload["spans"]

    reviewed = client.post(
        "/api/ai/problem/review",
        json={
            "number": "7",
            "subject": "수학",
            "unit": "함수",
            "tags": "점검",
            "title": "함수 문항",
            "stem": "  $f(x)=x^2 일 때 값을 구하시오.  ",
            "choices": ["① 1", "② 1", "④ 3"],
            "answer": "5",
            "explanation": "",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    reviewed_payload = reviewed.json()
    assert reviewed_payload["score"] < 100
    finding_titles = {finding["title"] for finding in reviewed_payload["findings"]}
    assert "중복 선지" in finding_titles
    assert "선지 번호 불일치" in finding_titles
    assert "정답 범위 오류" in finding_titles
    assert "수식 구조 오류" in finding_titles
    assert "해설 없음" in finding_titles
    assert "불필요한 공백" in finding_titles
    assert all(
        {"severity", "title", "detail", "field"}.issubset(finding)
        for finding in reviewed_payload["findings"]
    )

    clean_review = client.post(
        "/api/ai/problem/review",
        json={
            "number": "1",
            "subject": "수학",
            "unit": "함수",
            "tags": "기본",
            "title": "함숫값",
            "stem": r"$f(x)=x^2$일 때 $f(2)$의 값은?",
            "choices": ["1", "2", "3", "4", "5"],
            "answer": "4",
            "explanation": r"$f(2)=2^2=4$이다.",
        },
    )
    assert clean_review.status_code == 200, clean_review.text
    assert clean_review.json()["score"] == 100, clean_review.text
    assert clean_review.json()["findings"] == []

    strict_review = client.post(
        "/api/ai/problem/review",
        json={"stem": "문항", "unexpected": True},
    )
    assert strict_review.status_code == 422, strict_review.text
    oversized_review = client.post(
        "/api/ai/problem/review",
        json={"stem": "문항", "choices": ["x" * 20_001]},
    )
    assert oversized_review.status_code == 422, oversized_review.text

    no_ocr = client.post(
        "/api/ai/ocr",
        json={"filename": "blank.png", "dataBase64": _image_base64(), "backend": "none"},
    )
    assert no_ocr.status_code == 200, no_ocr.text
    assert no_ocr.json()["backend"] == "none"

    malformed = client.post(
        "/api/ai/ocr",
        json={"filename": "bad.png", "dataBase64": "not-base64", "backend": "none"},
    )
    assert malformed.status_code == 400, malformed.text

    class _RemoteBackend:
        name = "gemini"

        def ocr_image(self, image):  # pragma: no cover - guard must prevent this call
            raise AssertionError("remote backend was called without consent")

    with patch("app.ai_api.ocr_backend.build_ocr_backend", return_value=_RemoteBackend()):
        guarded = client.post(
            "/api/ai/ocr",
            json={"filename": "blank.png", "dataBase64": _image_base64(), "backend": "auto"},
        )
    assert guarded.status_code == 409, guarded.text
    assert "allowRemote=true" in guarded.json()["detail"]

    reconstruct_guarded = client.post(
        "/api/ai/reconstruct",
        json={"filename": "blank.png", "dataBase64": _image_base64(), "provider": "gemini"},
    )
    assert reconstruct_guarded.status_code == 409, reconstruct_guarded.text
    assert "allowRemote=true" in reconstruct_guarded.json()["detail"]

    sanitized_settings = {
        "geminiApiKey": "",
        "geminiApiKeyPreview": "AIza\u02c7wxyz",
        "hasGeminiApiKey": True,
        "geminiApiKeySource": "user_settings",
        "geminiApiKeyStoredPreview": "AIza\u02c7wxyz",
        "hasStoredGeminiApiKey": True,
        "openAiApiKey": "",
        "openAiApiKeyPreview": "",
        "hasOpenAiApiKey": False,
        "openAiApiKeySource": "none",
        "openAiApiKeyStoredPreview": "",
        "hasStoredOpenAiApiKey": False,
    }
    raw_key = "AIza-test-secret-never-return"
    with (
        patch("app.ai_api.settings.update_api_keys", return_value=sanitized_settings) as update,
        patch("app.ai_api.settings.summarize_for_response", return_value=sanitized_settings),
    ):
        updated = client.put("/api/ai/settings", json={"geminiApiKey": raw_key})
    assert updated.status_code == 200, updated.text
    update.assert_called_once_with(None, gemini_api_key=raw_key, openai_api_key=None)
    assert raw_key not in json.dumps(updated.json())

    empty_update = client.put("/api/ai/settings", json={})
    assert empty_update.status_code == 400, empty_update.text

    print("AI API verification passed")


if __name__ == "__main__":
    main()
