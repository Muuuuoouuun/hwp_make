# -*- coding: utf-8 -*-
"""HWPX 단 정의(colPr) 불리언 표기 검증.

한컴 저장본과 한컴 템플릿은 colPr sameSz 를 "1"/"0"으로 쓴다. 벤더 python-hwpx
생성 경로가 "true"를 써서 python-hwpx 6.7·HwpForge가 산출물을 거부했다
(2026-10-03 작업 정리 §4 오픈소스 PoC 1). 앱 템플릿별 산출물의 sameSz 를 고정한다.
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

from app import hwpx_writer_v2  # noqa: E402

failures: list[str] = []


def main() -> int:
    problems = [{"number": 1, "stem": "1. 값은?", "choices": ["1", "2", "3", "4", "5"]}]
    for template_key in ("basic", "kice_math", "school_exam"):
        path = Path(_TMP.name) / f"{template_key}.hwpx"
        hwpx_writer_v2.write_hwpx(path, "단 정의", problems, template_key=template_key)
        with zipfile.ZipFile(path) as archive:
            xml = "".join(
                archive.read(name).decode("utf-8")
                for name in archive.namelist()
                if name.startswith("Contents/section")
            )
        values = re.findall(r'<hp:colPr\b[^>]*\bsameSz="([^"]*)"', xml)
        ok = bool(values) and all(value in {"0", "1"} for value in values)
        print(f"  [{'PASS' if ok else 'FAIL'}] {template_key} sameSz={values}")
        if not ok:
            failures.append(template_key)
    if failures:
        print("FAIL: " + ", ".join(failures))
        return 1
    print("HWPX_COLUMN_ATTRIBUTES_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
