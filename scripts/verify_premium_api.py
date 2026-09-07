"""Exercise the local Premium numbering boundary using isolated API storage.

Real HWPX and DOCX output is inspected; only the optional preview renderer is
stubbed so this check does not require a native renderer or a paid service.
"""

from __future__ import annotations

import copy
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="hwpmake_premium_api_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME.name

from fastapi.testclient import TestClient  # noqa: E402

from app import main, storage  # noqa: E402


def document_text(data: bytes, extension: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = ["word/document.xml"] if extension == "docx" else sorted(
            name for name in archive.namelist()
            if name.startswith("Contents/section") and name.endswith(".xml")
        )
        text = "".join(
            node.text or ""
            for name in names
            for node in ET.fromstring(archive.read(name)).iter()
            if node.tag.rsplit("}", 1)[-1] == "t"
        )
    return " ".join(text.split())


def check_response(response, status: int) -> None:
    assert response.status_code == status, (response.status_code, response.text[:1200])


def run() -> None:
    first = storage.create_problem({
        "number": "12", "stem": "FIRSTQUESTION 본문", "answer": "1",
        "explanation": "FIRSTEXPLANATION", "choices": ["선택가", "선택나"],
        "tables": [[["열", "값"], ["항목", "3.14"]]],
    })
    second = storage.create_problem({
        "number": "27", "stem": "27. SECONDQUESTION 본문", "answer": "2",
        "explanation": "SECONDEXPLANATION", "choices": ["선택다", "선택라"],
    })
    ordered = [second, first]
    originals = copy.deepcopy(ordered)
    base = {"ids": [item["id"] for item in ordered], "template_key": "kice_math", "include_answer_sheet": True}

    with TestClient(main.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        client.headers["Origin"] = "http://127.0.0.1"
        for route in ("/", "/premium", "/premium/studio"):
            response = client.get(route)
            check_response(response, 200)
            assert "text/html" in response.headers["content-type"]

        # Anonymous conversion stays available; claiming premium in JSON does
        # not authorize editing or disclose whether arbitrary source IDs exist.
        with patch.object(main.preview, "available", return_value=True), patch.object(
            main.preview, "render_preview", return_value={"pages": []},
        ):
            check_response(client.post("/api/preview", json=base), 200)
        for endpoint in ("/api/preview", "/api/export"):
            check_response(client.post(endpoint, json={**base, "workspace": "premium"}), 401)
            check_response(client.post(endpoint, json={**base, "workspace": "premium", "ids": [9999999]}), 401)
        anonymous = client.get("/api/session")
        check_response(anonymous, 200)
        assert anonymous.json()["authenticated"] is False
        assert anonymous.json()["premium_access"] is False
        setup = client.post("/api/session/setup", json={"name": "격리 검증 사용자", "password": "local-test-password-2026"})
        check_response(setup, 200)
        signed_in = client.get("/api/session")
        check_response(signed_in, 200)
        assert signed_in.json()["authenticated"] is True
        assert signed_in.json()["premium_access"] is True
        response = client.get("/api/premium-capabilities")
        check_response(response, 200)
        capabilities = response.json()
        assert capabilities["available"] is True
        assert capabilities["mode"] == "local_preview"
        assert capabilities["billing_enabled"] is False

        for options, labels in (
            ({}, ["27", "12"]),
            ({"workspace": "premium", "numbering_mode": "preserve"}, ["27", "12"]),
            ({"workspace": "premium", "numbering_mode": "sequential"}, ["1", "2"]),
            ({"workspace": "premium", "numbering_mode": "sequential", "start_number": 41}, ["41", "42"]),
        ):
            payload = {**base, **options}
            prepared_preview = []

            def capture_preview(title, problems, template_key, **kwargs):
                prepared_preview.append(copy.deepcopy(problems))
                return {"pages": [], "page_count": 0}

            with patch.object(main.preview, "available", return_value=True), patch.object(
                main.preview, "render_preview", side_effect=capture_preview,
            ):
                check_response(client.post("/api/preview", json=payload), 200)
            assert [str(item["number"]) for item in prepared_preview[0]] == labels
            for extension in ("hwpx", "docx"):
                writer = main.hwpx_writer_v2 if extension == "hwpx" else main.docx_writer
                method = "write_hwpx" if extension == "hwpx" else "write_docx"
                original_writer = getattr(writer, method)
                written = []

                def capture_writer(path, title, problems, *args, **kwargs):
                    written.append(copy.deepcopy(problems))
                    return original_writer(path, title, problems, *args, **kwargs)

                with patch.object(writer, method, side_effect=capture_writer):
                    response = client.post("/api/export", json={**payload, "format": extension})
                check_response(response, 200)
                assert written[0] == prepared_preview[0], "Preview and export disagree on prepared problems"
                text = document_text(response.content, extension)
                assert text.index("SECONDQUESTION") < text.index("FIRSTQUESTION"), text
                for label, marker, answer in zip(labels, ("SECONDQUESTION", "FIRSTQUESTION"), ("②", "①")):
                    assert f"{label}. {marker}" in text, text
                    assert f"{label}. 정답 {answer}" in text, text
                assert f"{labels[0]}. ② {labels[1]}. ①" in text, text
                assert "SECONDEXPLANATION" in text and "FIRSTEXPLANATION" in text
            assert storage.get_problems_by_ids(base["ids"]) == originals, "Source DB rows changed"

        # Test deep copying at the actual API boundary, not merely a DB re-read.
        def mutate_preview(title, problems, template_key, **kwargs):
            problems[0]["choices"].append("RENDERER MUTATION")
            problems[1]["tables"][0][1][1] = "RENDERER MUTATION"
            return {"pages": []}

        with patch.object(main.storage, "get_problems_by_ids", return_value=ordered), patch.object(
            main.preview, "available", return_value=True,
        ), patch.object(main.preview, "render_preview", side_effect=mutate_preview):
            check_response(client.post("/api/preview", json={**base, "workspace": "premium", "numbering_mode": "sequential"}), 200)
        assert ordered == originals, "Premium render preparation mutated shared source objects"

        for endpoint in ("/api/preview", "/api/export"):
            for forbidden in (
                {"numbering_mode": "sequential"},
                {"start_number": 41},
                {"confirm_duplicate_numbers": True},
            ):
                response = client.post(endpoint, json={**base, **forbidden})
                check_response(response, 422)
                assert response.json()["detail"]["code"] == "premium_workspace_required"
            for invalid in (
                {"start_number": 0}, {"start_number": 1000},
                {"numbering_mode": "custom"}, {"workspace": "paid_bypass"},
                {"numbering_mode": "sequential", "start_number": 999},
                {"ids": []},
            ):
                check_response(client.post(endpoint, json={**base, "workspace": "premium", **invalid}), 422)
            check_response(client.post(endpoint, json={**base, "workspace": "premium", "ids": [first["id"], first["id"]]}), 400)
            response = client.post(endpoint, json={**base, "workspace": "premium", "ids": [first["id"], 9999999]})
            check_response(response, 409)
            assert response.json()["detail"]["missing_ids"] == [9999999]

        unsupported = [
            {"problem_type": "passage", "number": "21~23", "stem": "SHARED PASSAGE"},
            {"number": "21", "stem": "GROUPED QUESTION", "layout": {"shared_passage": {"range": [21, 23]}}},
            {"number": "21", "stem": "IMAGE FALLBACK", "layout": {"block_type": "image_fallback"}},
            {"number": "21", "source_type": "image", "stem": "", "image_paths": ["uploads/missing.png"]},
        ]
        existing_exports = set(storage.EXPORT_DIR.rglob("*"))
        for fixture in unsupported:
            item = storage.create_problem(fixture)
            for endpoint in ("/api/preview", "/api/export"):
                for mode in ("preserve", "sequential"):
                    with patch.object(main.preview, "available", return_value=True), patch.object(
                        main.preview, "render_preview", return_value={"pages": []},
                    ):
                        response = client.post(endpoint, json={**base, "ids": [item["id"]], "workspace": "premium", "numbering_mode": mode})
                    check_response(response, 422)
        assert set(storage.EXPORT_DIR.rglob("*")) == existing_exports, "Rejected input created partial exports"

        blank = storage.create_problem({"number": "", "stem": "UNNUMBERED QUESTION"})
        duplicate = storage.create_problem({"number": "12", "stem": "DUPLICATE SOURCE NUMBER"})
        for endpoint in ("/api/preview", "/api/export"):
            check_response(client.post(endpoint, json={**base, "ids": [blank["id"]], "workspace": "premium"}), 422)
            check_response(client.post(endpoint, json={**base, "ids": [first["id"], duplicate["id"]], "workspace": "premium"}), 422)
        with patch.object(main.preview, "available", return_value=True), patch.object(
            main.preview, "render_preview", return_value={"pages": []},
        ):
            check_response(client.post("/api/preview", json={**base, "ids": [first["id"], duplicate["id"]], "workspace": "premium", "confirm_duplicate_numbers": True}), 200)
            check_response(client.post("/api/preview", json={**base, "ids": [first["id"]], "workspace": "premium", "numbering_mode": "sequential", "start_number": 999}), 200)
            check_response(client.post("/api/preview", json={**base, "ids": [blank["id"]], "workspace": "premium", "numbering_mode": "sequential"}), 200)
            check_response(client.post("/api/preview", json={**base, "ids": [first["id"], duplicate["id"]], "workspace": "premium", "numbering_mode": "sequential"}), 200)

        decimal = storage.create_problem({"number": "27", "stem": "27.5 + 27.+x 값과 27번 참조를 보존한다."})
        for extension in ("hwpx", "docx"):
            response = client.post("/api/export", json={**base, "ids": [decimal["id"]], "workspace": "premium", "numbering_mode": "sequential", "start_number": 27, "format": extension, "native_math": False})
            check_response(response, 200)
            text = document_text(response.content, extension)
            assert "27.5+27.+x" in text.replace(" ", ""), text
            assert "27번 참조" in text, text
        assert storage.get_problems_by_ids(base["ids"]) == originals

    print("PREMIUM_API_OK: routes, real session, anonymous boundary, numbering, real HWPX/DOCX, preview parity, source preservation, unsupported inputs")


if __name__ == "__main__":
    try:
        run()
    finally:
        RUNTIME.cleanup()
