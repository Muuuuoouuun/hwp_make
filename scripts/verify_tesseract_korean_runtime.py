"""Exercise the installed Korean OCR engine on a real paragraph image."""
from pathlib import Path
import io
import re
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont
from app.recognition import ocr_backend


def main():
    engine = ocr_backend.pytesseract
    if engine is None:
        print("SKIP: pytesseract is unavailable")
        return 2
    try:
        languages = engine.get_languages(config="")
    except Exception:
        print("SKIP: tesseract executable is unavailable")
        return 2
    if not {"kor", "eng"}.issubset(languages):
        print("SKIP: Korean and English traineddata are required")
        return 2
    candidates = [
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("C:/Windows/Fonts/malgun.ttf"),
        Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    ]
    font_path = next((p for p in candidates if p.exists()), None)
    if font_path is None:
        print("SKIP: a Korean fixture font is unavailable")
        return 2
    font = ImageFont.truetype(str(font_path), 40)
    image = Image.new("RGB", (1500, 320), "white")
    draw = ImageDraw.Draw(image)
    source = ["1. 다음 글을 읽고 물음에 답하시오.",
              "한글 변환기의 문제 인식 기능을 점검합니다.",
              "2. 올바른 답을 고르시오."]
    for index, line in enumerate(source):
        draw.text((35, 20 + index * 90), line, font=font, fill="black")
    backend = ocr_backend.TesseractOCRBackend()
    result = backend.ocr_image(image)
    compact = lambda value: re.sub(r"\s+", "", value)
    assert compact(result.text) == compact("".join(source)), result
    assert result.lines and all(0 <= line.confidence <= 1 for line in result.lines)
    assert not result.metadata.get("error"), result.metadata
    assert not backend.ocr_image(Image.new("RGB", image.size, "white")).text
    from app import importers, storage
    with tempfile.TemporaryDirectory(prefix="tesseract_korean_import_") as temporary:
        directory = Path(temporary)
        with patch.multiple(storage, DATA_DIR=directory, UPLOAD_DIR=directory / "uploads",
                            EXPORT_DIR=directory / "exports", DB_PATH=directory / "problems.sqlite3"):
            storage.init_db()
            encoded = io.BytesIO()
            image.save(encoded, format="PNG")
            imported = importers.import_image("korean-paragraph.png", encoded.getvalue(), {})
            assert len(imported["ordered_ids"]) == 1, imported
            saved = storage.get_problem(imported["ordered_ids"][0])
            assert compact(saved["stem"]) == compact("".join(source)), saved
    with patch.object(engine, "image_to_data", side_effect=RuntimeError("OCR timed out")):
        failed = backend.ocr_image(image)
    assert failed.text == "" and failed.metadata.get("error") == "OCR timed out"
    print("TESSERACT_KOREAN_RUNTIME_OK: Korean paragraph recognized and imported, blank and failure handled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
