# -*- coding: utf-8 -*-
"""Stress the UI reorder/export contract at column and page boundaries."""

from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "reorder_layout_regression"
os.environ.setdefault("HWP_MAKE_DATA_DIR", str(OUT_DIR))
sys.path.insert(0, str(ROOT))

from app import hwpx_writer_v2, storage  # noqa: E402
from scripts import qa_hwp_math_samples as qa  # noqa: E402


def _problem(marker: str, lines: int, **extra: Any) -> dict[str, Any]:
    body = [f"{marker} 문항 시작"]
    body.extend(
        f"{marker} 본문 {index:02d} — 문항 이동 뒤에도 단과 페이지 경계에서 잘리지 않아야 합니다."
        for index in range(1, lines + 1)
    )
    return {
        "number": marker.removeprefix("LAYOUT"),
        "subject": "수학",
        "unit": "[3점][layout stress]",
        "title": marker,
        "stem": "\n".join(body),
        "choices": [],
        "tables": [],
        "image_paths": [],
        **extra,
    }


def _items() -> list[dict[str, Any]]:
    table = [["구분", "긴 자료 내용"]]
    table.extend(
        [str(index), f"표 행 {index:02d}의 설명이 반복되어 한 단보다 커질 때 행 단위로 나뉩니다."]
        for index in range(1, 29)
    )
    return [
        _problem("LAYOUTA", 2),
        _problem("LAYOUTB", 9),
        _problem("LAYOUTC", 2, tables=[table]),
        _problem("LAYOUTD", 34),
        _problem(
            "LAYOUTE",
            3,
            choices=[
                "첫 번째 선택지는 비교를 위한 긴 설명을 포함합니다.",
                "두 번째 선택지도 줄바꿈과 경계 이동을 확인합니다.",
                "세 번째 선택지는 예외 조건을 포함합니다.",
                "네 번째 선택지는 충분히 긴 문장입니다.",
                "다섯 번째 선택지는 마지막 결론입니다.",
            ],
        ),
        _problem("LAYOUTF", 1),
    ]


def _section_text(path: Path) -> str:
    texts: list[str] = []
    with zipfile.ZipFile(path, "r") as archive:
        section_names = sorted(
            name for name in archive.namelist() if name.startswith("Contents/section") and name.endswith(".xml")
        )
        for name in section_names:
            root = ET.fromstring(archive.read(name))
            texts.extend(str(node.text or "") for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "t")
    return "\n".join(texts)


def _column_break_count(path: Path) -> int:
    count = 0
    with zipfile.ZipFile(path, "r") as archive:
        for name in archive.namelist():
            if name.startswith("Contents/section") and name.endswith(".xml"):
                count += archive.read(name).count(b'columnBreak="1"')
    return count


def _ordered(text: str, markers: list[str]) -> bool:
    positions = [text.find(marker) for marker in markers]
    return all(position >= 0 for position in positions) and positions == sorted(positions)


def _write_and_check(label: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    path = OUT_DIR / f"reorder_{label}.hwpx"
    hwpx_writer_v2.write_hwpx(
        path,
        f"Reorder layout {label}",
        items,
        template_key="kice_math",
        native_math=True,
    )
    text = _section_text(path)
    render = qa._render_hwpx(path, OUT_DIR / "renders", 0)
    markers = [item["title"] for item in items]
    return {
        "path": str(path),
        "markers": markers,
        "ordered": _ordered(text, markers),
        "column_breaks": _column_break_count(path),
        "table_count": text.count("구분"),
        "render": {
            "page_count": render.get("page_count"),
            "overflow_count": render.get("overflow_count"),
            "column_crossing_issues": render.get("column_crossing_issues") or [],
            "error": render.get("error"),
        },
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    storage.init_db()
    items = _items()
    forward = _write_and_check("forward", items)
    reversed_result = _write_and_check("reversed", list(reversed(items)))
    failures: list[str] = []
    for result in (forward, reversed_result):
        render = result["render"]
        if not result["ordered"]:
            failures.append(f"{result['path']}: output marker order does not match requested order")
        if int(result["column_breaks"] or 0) < 2:
            failures.append(f"{result['path']}: expected explicit column boundary moves")
        if int(result["table_count"] or 0) < 2:
            failures.append(f"{result['path']}: oversized table header was not repeated across chunks")
        if render.get("error"):
            failures.append(f"{result['path']}: render failed: {render['error']}")
        if int(render.get("overflow_count") or 0):
            failures.append(f"{result['path']}: layout overflow: {render['overflow_count']}")
        if render.get("column_crossing_issues"):
            failures.append(f"{result['path']}: column crossing: {render['column_crossing_issues'][:4]}")
        pages = int(render.get("page_count") or 0)
        if pages < 2 or pages > 10:
            failures.append(f"{result['path']}: unexpected page count {pages}")

    report = {"ok": not failures, "forward": forward, "reversed": reversed_result, "failures": failures}
    (OUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "forward pages={forward_pages} breaks={forward_breaks}; reversed pages={reverse_pages} breaks={reverse_breaks}".format(
            forward_pages=forward["render"].get("page_count"),
            forward_breaks=forward["column_breaks"],
            reverse_pages=reversed_result["render"].get("page_count"),
            reverse_breaks=reversed_result["column_breaks"],
        )
    )
    if failures:
        print("REORDER_LAYOUT_FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("REORDER_LAYOUT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
