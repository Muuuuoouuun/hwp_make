"""One conversion per OS process. Only this process imports the local engine."""

from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path


def write_unnumbered_pdf(source: Path, destination: Path) -> tuple[int, str]:
    """Write unnumbered handouts using the supported text or ruled-table flow."""
    import fitz
    from .pdf_layout_writer import HwpxDocument, _save_hancom_compatible_document

    document = HwpxDocument.new()
    with fitz.open(source) as pdf:
        for index, page in enumerate(pdf):
            if page.get_image_info():
                raise ValueError("Unnumbered handout contains graphics")
            drawings = page.get_drawings()
            if drawings:
                from .web_ruled_table import write_ruled_worksheet
                write_ruled_worksheet(source, destination, pdf)
                return len(pdf), "표는 셀 단위로, 본문과 한 줄 수식은 글자로 편집할 수 있어요. 열 간격과 줄바꿈은 한글에서 확인해 주세요."
            paragraphs = [block[4].strip() for block in page.get_text("blocks", sort=True)
                          if block[6] == 0 and block[4].strip()]
            if not paragraphs:
                raise ValueError("Page has no editable text")
            for number, text in enumerate(paragraphs):
                for line_number, line in enumerate(text.splitlines()):
                    document.add_paragraph(line, pageBreak="1" if index and not number and not line_number else "0")
        _save_hancom_compatible_document(document, destination)
        return len(pdf), "번호 없는 텍스트 PDF의 본문을 문단으로 옮겼어요. 원본의 글꼴과 줄 간격은 달라질 수 있어요."


def convert(directory: Path):
    spec = json.loads((directory / "spec.json").read_text(encoding="utf-8"))
    # Some multipart clients can send names longer than a desktop component.
    # Only the private conversion engine has a 255-character input name limit.
    if len(spec["filename"]) > 255:
        name = Path(spec["filename"])
        spec["filename"] = name.stem[:255 - len(name.suffix)] + name.suffix
    runtime = directory / "engine"
    os.environ["HWP_MAKE_DATA_DIR"] = str(runtime)
    # The prototype must never spend a locally configured provider key.
    for key in list(os.environ):
        if key.startswith(("OPENAI_", "ANTHROPIC_", "GEMINI_", "GOOGLE_")) or key == "HWP_MAKE_SETTINGS_DIR":
            os.environ.pop(key, None)
    os.environ["HWP_MAKE_SETTINGS_DIR"] = str(runtime / "settings")
    from . import main, storage

    source = Path(spec["source"])
    data = source.read_bytes()
    warnings = ["원본 배치와 수식은 다운로드 후 한글에서 확인해 주세요."]
    pages = None
    count = None
    if spec["kind"] == "pdf" and spec["format"] == "hwpx":
        try:
            response = main.export_pdf_layout(
                main.PdfLayoutExportPayload(
                    filename=spec["filename"],
                    data_base64=base64.b64encode(data).decode(),
                    math_ai_recognition=False,
                    variant_policy="all",
                    layout_mode="structured",
                )
            )
        except main.HTTPException as exc:
            if not isinstance(exc.detail, dict) or exc.detail.get("code") not in ("no_questions", "scan_only"):
                raise
            path = directory / "paragraphs.hwpx"
            pages, note = write_unnumbered_pdf(source, path)
            warnings.append(note)
        else:
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
        imported = importer(spec["filename"], data, {"math_ai_recognition": False, "allow_remote": False})
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
                # 기본 변환 전용 양식: 원번호·원문자 선지 유지, 정답은 끝 정답표로만.
                template_key="simple",
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
    if path.parent == directory:
        path.replace(output)
    else:
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
