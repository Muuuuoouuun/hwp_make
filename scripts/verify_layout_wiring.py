"""인수 테스트: recognition layout → storage → writer 배선.

병목 #1은 pdf_segment/pipeline 이 알고 있는 column/bbox 정보를 import/storage 에서
잃어버려 writer 가 템플릿 기본 단수로만 재추론하던 문제다. 이 테스트는 핫존을
작게 찌른다:

- storage.create_problem/get_problem 이 layout dict 를 보존한다.
- hwpx_writer_v2.write_hwpx 는 problem.layout.column_count=1 을 template.columns=2
  보다 우선해 2단 colPr 를 만들지 않는다.
- layout.column_count=2 는 기존 2단 출력을 계속 만든다.
"""
from __future__ import annotations

import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

tmp = tempfile.TemporaryDirectory(prefix="hwp_make_layout_wiring_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = tmp.name

from app import hwpx_writer_v2, storage  # noqa: E402

_failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}{('  · ' + detail) if detail else ''}")
    if not condition:
        _failures.append(name)


def section_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read("Contents/section0.xml").decode("utf-8", errors="replace")


def main() -> int:
    storage.init_db()
    layout = {
        "column_count": 1,
        "column_index": 1,
        "page": {"number": 1, "width_px": 1200, "height_px": 1700},
        "bbox_px": [10, 20, 500, 300],
    }
    item = storage.create_problem(
        {
            "source_type": "pdf",
            "source_name": "layout.pdf",
            "number": "1",
            "title": "layout",
            "stem": "1. layout one-column",
            "layout": layout,
        }
    )
    loaded = storage.get_problem(item["id"])
    check("storage layout 보존", loaded.get("layout") == layout, repr(loaded.get("layout")))

    one_col_path = storage.EXPORT_DIR / "layout_one_col.hwpx"
    hwpx_writer_v2.write_hwpx(
        one_col_path,
        "Layout One Column",
        [loaded],
        template_key="kice_math",
        native_math=True,
    )
    one_xml = section_xml(one_col_path)
    check("layout=1 이 kice_math 기본 2단을 이김", 'colCount="2"' not in one_xml)

    two_col_problem = {
        **loaded,
        "layout": {**layout, "column_count": 2, "column_index": 1},
    }
    two_col_path = storage.EXPORT_DIR / "layout_two_col.hwpx"
    hwpx_writer_v2.write_hwpx(
        two_col_path,
        "Layout Two Column",
        [two_col_problem],
        template_key="kice_math",
        native_math=True,
    )
    two_xml = section_xml(two_col_path)
    check("layout=2 는 2단 colPr 유지", 'colCount="2"' in two_xml)

    if _failures:
        print(f"LAYOUT_WIRING_FAIL ({len(_failures)}건): {', '.join(_failures)}")
        return 1
    print("LAYOUT_WIRING_OK — layout 정보가 writer까지 보존/소비됨")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        tmp.cleanup()
