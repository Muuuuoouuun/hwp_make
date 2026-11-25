# -*- coding: utf-8 -*-
"""DOCX·HWPX 내보내기 기본값 검증 (Filee DOCX/HWPX writer 비교 후속).

- DOCX: A4 용지, 호환 모드 15, 문단 뒤 간격 2pt·1.2줄, 동아시아 글꼴 명시, 검은 제목.
- DOCX 표: 단 폭에 맞춘 고정 폭, 연속된 두 표 사이 빈 문단(Word가 한 표로 합치지 않게).
- WebP 같은 그림도 DOCX·HWPX에 PNG로 들어간다(이전: DOCX "[이미지 삽입 실패]",
  HWPX는 WebP 바이트에 png 표시).
종료코드 0=통과, 1=실패.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory()
os.environ["HWP_MAKE_DATA_DIR"] = _TMP.name

from PIL import Image  # noqa: E402

from app import docx_writer, hwpx_writer_v2, storage  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}{('  · ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def main() -> int:
    storage.ensure_dirs()
    image_dir = storage.DATA_DIR / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (80, 40), (200, 30, 30)).save(image_dir / "figure.webp", "WEBP")
    problem = {
        "number": "1",
        "stem": "1. 두 표를 보고 답하시오.",
        "choices": ["1", "2", "3", "4", "5"],
        "image_paths": ["images/figure.webp"],
        "tables": [[["a", "b", "c"], ["d", "e", "f"]], [["x", "y"], ["z", "w"]]],
    }

    docx_path = Path(_TMP.name) / "exam.docx"
    docx_writer.write_docx(docx_path, "기본값", [problem], "kice_math")
    with zipfile.ZipFile(docx_path) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
        styles = archive.read("word/styles.xml").decode("utf-8")
        settings = archive.read("word/settings.xml").decode("utf-8")
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
    check("A4 용지", '<w:pgSz w:w="11906" w:h="16838"/>' in document, str(re.findall(r"<w:pgSz[^>]*>", document)))
    check("호환 모드 15", re.search(r'compatibilityMode"[^>]*w:val="15"', settings) is not None)
    normal = re.search(r'w:styleId="Normal">.*?</w:style>', styles, re.S)
    normal_xml = normal.group(0) if normal else ""
    check("문단 뒤 2pt·1.2줄", 'w:after="40"' in normal_xml and 'w:line="288"' in normal_xml, normal_xml[:200])
    check("동아시아 글꼴 명시", 'w:eastAsia="Malgun Gothic"' in normal_xml)
    heading = re.search(r'w:styleId="Heading1">.*?</w:style>', styles, re.S)
    check("제목 검은색", heading is not None and 'w:color w:val="000000"' in heading.group(0))
    widths = [int(value) for value in re.findall(r'<w:gridCol w:w="(\d+)"/>', document)]
    column_width = (11906 - 2 * 1800 - 567) // 2
    check("표 폭이 단 폭 안", bool(widths) and sum(widths[:3]) <= column_width and sum(widths[3:]) <= column_width, str(widths))
    check("연속된 표 사이 문단", re.search(r"</w:tbl>\s*<w:tbl>", document) is None)
    check("WebP 그림 DOCX 삽입", len(media) == 1 and "이미지 삽입 실패" not in document, str(media))

    hwpx_path = Path(_TMP.name) / "exam.hwpx"
    hwpx_writer_v2.write_hwpx(hwpx_path, "기본값", [problem])
    with zipfile.ZipFile(hwpx_path) as archive:
        binaries = {name: archive.read(name)[:8] for name in archive.namelist() if name.startswith("BinData/")}
    check(
        "WebP 그림 HWPX에 PNG로",
        bool(binaries) and all(name.endswith(".png") and data.startswith(b"\x89PNG") for name, data in binaries.items()),
        str(binaries),
    )

    if failures:
        print("FAIL: " + ", ".join(failures))
        return 1
    print("EXPORT_DOCUMENT_DEFAULTS_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
