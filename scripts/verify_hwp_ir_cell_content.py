# -*- coding: utf-8 -*-
"""HWP(rhwp IR) 표 셀 안의 그림·중첩 표 보존 검증.

2026-10-03 작업 정리 §4: 국어 HWP 셀 안 그림 9개와 중첩 표 2개가 사라졌다.
rhwp IR 셀 blocks 의 picture/table 을 읽어, 중첩 표 글은 셀 글에 넣고
셀 그림은 표 바로 뒤 문항 그림으로 낸다(표 모델이 문자열 격자이므로).
종료코드 0=통과, 1=실패, 2=rhwp 없음(SKIP).
"""
from __future__ import annotations

import io
import os
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

from app import importers_hwp_ir  # noqa: E402

SKELETON = ROOT / "app" / "_vendor" / "hwpx" / "data" / "Skeleton.hwpx"
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}{('  · ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def para(inner: str) -> str:
    return f'<hp:p id="0" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0">{inner}</hp:run></hp:p>'


def text(value: str) -> str:
    return f"<hp:t>{value}</hp:t>"


def cell(inner: str, col: int, row: int) -> str:
    return (
        f'<hp:tc><hp:subList>{inner}</hp:subList><hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
        '<hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz width="10000" height="2000"/></hp:tc>'
    )


def table(rows: list[list[str]]) -> str:
    body = "".join(
        "<hp:tr>" + "".join(cell(inner, col, row) for col, inner in enumerate(cells)) + "</hp:tr>"
        for row, cells in enumerate(rows)
    )
    return f'<hp:tbl rowCnt="{len(rows)}" colCnt="{len(rows[0])}"><hp:sz width="20000" height="4000"/>{body}</hp:tbl>'


def fixture() -> bytes:
    picture = (
        '<hp:pic id="77"><hp:sz width="3000" height="3000"/><hp:pos treatAsChar="1"/>'
        '<hc:img xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" binaryItemIDRef="image1"/></hp:pic>'
    )
    nested = table([[para(text("안쪽 가")), para(text("안쪽 나"))]])
    body = para(text("1. 표를 보고 답하시오.")) + para(
        table([[para(text("그림칸") + picture), para(nested)], [para(text("아래")), para(text("끝"))]])
    )
    image = io.BytesIO()
    Image.new("RGB", (40, 40), (200, 0, 0)).save(image, "PNG")
    buffer = io.BytesIO()
    with zipfile.ZipFile(SKELETON) as skeleton, zipfile.ZipFile(buffer, "w") as archive:
        for name in skeleton.namelist():
            data = skeleton.read(name)
            if name == "Contents/section0.xml":
                data = data.decode("utf-8").replace("</hs:sec>", body + "</hs:sec>").encode("utf-8")
            elif name == "Contents/content.hpf":
                data = data.decode("utf-8").replace(
                    "</opf:manifest>",
                    '<opf:item id="image1" href="BinData/image1.png" media-type="image/png" isEmbeded="1"/></opf:manifest>',
                ).encode("utf-8")
            archive.writestr(name, data, compress_type=zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED)
        archive.writestr("BinData/image1.png", image.getvalue())
    return buffer.getvalue()


def main() -> int:
    if not importers_hwp_ir.available():
        print("SKIP: rhwp is not available")
        return 2
    saved: list[int] = []

    def save_image(name: str, payload: bytes) -> str:
        saved.append(len(payload))
        return f"images/{name}"

    stream = importers_hwp_ir._ordered_stream(fixture(), "cells.hwp", save_image) or []
    tables = [list(value) for kind, value in stream if kind == "table"]
    kinds = [kind for kind, value in stream if kind != "text" or str(value).strip()]
    check("표 1개", len(tables) == 1, str(tables))
    check("중첩 표 글이 셀에 남음", bool(tables) and tables[0][0][1] == "안쪽 가 안쪽 나", str(tables))
    check("셀 그림 저장", len(saved) == 1 and saved[0] > 0, str(saved))
    check("셀 그림이 표 바로 뒤 문항 그림", kinds[-2:] == ["table", "image"], str(kinds))

    if failures:
        print("FAIL: " + ", ".join(failures))
        return 1
    print("HWP_IR_CELL_CONTENT_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
