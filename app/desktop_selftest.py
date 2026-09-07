"""Exercise the shipped Tk controller and frozen worker, with synthetic documents."""
from __future__ import annotations

import json
from pathlib import Path
import time
import tkinter as tk
import traceback
import zipfile


def run(directory: Path, app_class) -> int:
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    checks = []
    root = None
    ui = None
    try:
        import fitz
        from PIL import Image
        from app.desktop_convert import validate_source

        root = tk.Tk()
        root.withdraw()
        ui = app_class(root, directory / "profile")
        assert str(ui.convert_button["state"]) == "disabled"
        assert ui.format.get() == "HWPX"
        checks.append("Native Tk window and initial control states")

        def conversion(source, destination, expected_ok=True):
            ui.set_source(source)
            assert str(ui.open_button["state"]) == "disabled"
            ui.start_to(destination)
            assert ui.process is not None
            assert str(ui.pick["state"]) == "disabled"
            until = time.monotonic() + 180
            while ui.process and time.monotonic() < until:
                root.update()
                time.sleep(.05)
            assert ui.process is None, "Worker timed out"
            result = json.loads((ui.job / "result.json").read_text(encoding="utf-8"))
            assert result["ok"] == expected_ok, result
            assert str(ui.pick["state"]) == "normal"
            assert not (ui.job / "engine").exists(), "Private engine data was not cleaned"
            if expected_ok:
                assert destination.is_file()
                assert str(ui.open_button["state"]) == "normal"
                with zipfile.ZipFile(destination) as archive:
                    assert archive.testzip() is None
            return result

        text = directory / "원본 문항.txt"
        text.write_text("7. 다음 계산의 결과는?\n2 + 3 = ?\n① 3\n② 4\n③ 5\n④ 6\n⑤ 7", encoding="utf-8")
        result = conversion(text, directory / "텍스트 결과.hwpx")
        assert result["problems"] == 1
        checks.append("TXT to HWPX, real worker, Korean paths, completion controls")
        conversion(directory / "텍스트 결과.hwpx", directory / "워드 결과.docx")
        checks.append("HWPX import to valid DOCX")
        conversion(directory / "워드 결과.docx", directory / "워드 재변환.hwpx")
        checks.append("DOCX import to valid HWPX")
        pdf = directory / "전체 원본.pdf"
        document = fitz.open()
        for index in range(2):
            page = document.new_page()
            page.insert_text((72, 90), f"{index + 1}. Calculate 2 + 3.")
            page.insert_text((72, 120), "A. 3    B. 4    C. 5")
        document.save(pdf)
        document.close()
        result = conversion(pdf, directory / "전체 결과.hwpx")
        assert result["pages"] == 2, result
        checks.append("PDF to HWPX, all 2 pages, native math and renderer dependencies")
        picture = directory / "그림.png"
        Image.new("RGB", (120, 80), "white").save(picture)
        conversion(picture, directory / "그림 결과.hwpx")
        checks.append("Image import without AI credentials or external OCR")
        invalid = directory / "잘못된 파일.pdf"
        invalid.write_bytes(b"not a PDF")
        protected = directory / "기존 결과.hwpx"
        protected.write_bytes(b"keep existing destination")
        conversion(invalid, protected, expected_ok=False)
        assert protected.read_bytes() == b"keep existing destination"
        checks.append("Invalid file failure, destination preserved, UI unlocked")
        empty = directory / "빈 파일.txt"
        empty.touch()
        try:
            validate_source(empty)
            raise AssertionError("Empty source accepted")
        except ValueError:
            pass
        large = directory / "용량 초과.txt"
        with large.open("wb") as stream:
            stream.truncate(64 * 1024 * 1024 + 1)
        try:
            validate_source(large)
            raise AssertionError("Oversized source accepted")
        except ValueError:
            pass
        large.unlink()
        checks.append("Empty and over-64MB file validation")
        assert len(ui.load_history()) == 5
        checks.append("Recent history persists successful conversions only")
        result = {"ok": True, "checks": checks}
    except Exception:
        result = {"ok": False, "checks": checks, "error": traceback.format_exc()}
    finally:
        if ui and ui.process:
            ui.process.terminate()
            ui.process.wait(timeout=10)
            ui.process = None
        if root:
            root.destroy()
    (directory / "selftest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1
