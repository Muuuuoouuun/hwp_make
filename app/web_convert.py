"""One conversion per OS process. Only this process imports the local engine."""

from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path


def convert(directory: Path):
    spec = json.loads((directory / "spec.json").read_text(encoding="utf-8"))
    runtime = directory / "engine"
    os.environ["HWP_MAKE_DATA_DIR"] = str(runtime)
    # The prototype must never spend a locally configured provider key.
    for key in list(os.environ):
        if key in {"OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"}:
            os.environ.pop(key, None)
    from . import main, storage

    source = Path(spec["source"])
    data = source.read_bytes()
    warnings = ["원본 배치와 수식은 다운로드 후 한글에서 확인해 주세요."]
    pages = None
    count = None
    if spec["kind"] == "pdf" and spec["format"] == "hwpx":
        response = main.export_pdf_layout(
            main.PdfLayoutExportPayload(
                filename=spec["filename"],
                data_base64=base64.b64encode(data).decode(),
                math_ai_recognition=False,
                variant_policy="all",
                layout_mode="structured",
            )
        )
        outputs = list(storage.EXPORT_DIR.rglob("*.hwpx"))
        if len(outputs) != 1 or not response["open_safety"].get("ok"):
            raise ValueError("생성 문서의 구조 검사에 실패했습니다.")
        path = outputs[0]
        pages = response["scope"]["selected_page_count"]
        count = response["stats"].get("output_problem_count")
        warnings.extend(response.get("notices", []))
        warnings.extend(
            str(x) for x in response.get("quality", {}).get("visual_review_flags", [])
        )
    else:
        main._validate_import_signature(spec["kind"], data)
        importer = main.IMPORTERS[spec["kind"]]
        imported = importer(spec["filename"], data, {})
        problems = imported.get("created", []) + imported.get("existing", [])
        ids = list(dict.fromkeys(p["id"] for p in problems))
        if not ids:
            raise ValueError(
                "편집 가능한 문항을 찾지 못했습니다. 텍스트가 포함된 문서를 사용해 주세요."
            )
        exported = main.export(
            main.ExportPayload(
                ids=ids,
                title=Path(spec["filename"]).stem,
                format=spec["format"],
                native_math=True,
            )
        )
        path = Path(exported.path)
        count = len(ids)
        warnings.extend(imported.get("notices", []))
    (directory / "validating").touch()
    with zipfile.ZipFile(path) as package:
        if package.testzip() is not None:
            raise ValueError("생성 문서 패키지가 손상되었습니다.")
        expected = (
            "Contents/content.hpf" if spec["format"] == "hwpx" else "word/document.xml"
        )
        if expected not in package.namelist():
            raise ValueError("생성 문서의 필수 내용이 없습니다.")
    output = directory / f"output.{spec['format']}"
    shutil.copyfile(path, output)
    # Retain only the deliverable and a sanitized summary, not internal URLs.
    result = {
        "source_pages": pages,
        "problem_count": count,
        "warnings": list(dict.fromkeys(warnings)),
        "format": spec["format"],
    }
    (directory / "result.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )
    # The supervising process removes engine files after this process exits.
    # SQLite handles in the legacy engine can remain open until process exit.


if __name__ == "__main__":
    target = Path(sys.argv[1]).resolve()
    try:
        convert(target)
    except Exception as exc:
        # A generic failure is published to users; engine details stay local.
        print(f"{type(exc).__name__}: conversion failed", file=sys.stderr)
        sys.exit(1)
