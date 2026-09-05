"""내보내기 전 미리보기: 생성한 HWPX를 rhwp 엔진으로 PNG 렌더링한다.

rhwp는 선택 의존성이다. 없으면 미리보기 기능만 비활성화된다.
한계: rhwp 렌더러는 다단(colPr) 레이아웃을 아직 1단으로 그린다.
"""

from __future__ import annotations

import base64
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from . import hwpx_writer_v2

try:
    import rhwp
except Exception:
    rhwp = None


MAX_PREVIEW_PAGES = 6


def available() -> bool:
    return rhwp is not None


def render_preview(
    title: str,
    problems: list[dict[str, Any]],
    template_key: str = "basic",
    max_pages: int = MAX_PREVIEW_PAGES,
    include_answer_sheet: bool = False,
    native_math: bool = False,
) -> dict[str, Any]:
    if rhwp is None:
        raise RuntimeError("미리보기 엔진(rhwp-python)이 설치되어 있지 않습니다.")
    max_pages = max(1, min(MAX_PREVIEW_PAGES, int(max_pages)))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "preview.hwpx"
        hwpx_writer_v2.write_hwpx(
            path,
            title,
            problems,
            template_key=template_key,
            include_answer_sheet=include_answer_sheet,
            native_math=native_math,
        )
        # Read the generated file: source layout metadata can override the
        # template's column count, so the template alone is not authoritative.
        columns = 1
        with zipfile.ZipFile(path) as package:
            for name in package.namelist():
                if not name.startswith("Contents/section") or not name.endswith(".xml"):
                    continue
                section = ET.fromstring(package.read(name))
                for column in section.iter("{http://www.hancom.co.kr/hwpml/2011/paragraph}colPr"):
                    columns = max(columns, int(column.get("colCount") or "1"))
        doc = rhwp.parse(str(path))
        page_count = int(doc.page_count)
        pages: list[str] = []
        for page in range(min(page_count, max_pages)):
            png = bytes(doc.render_png(page))
            pages.append("data:image/png;base64," + base64.b64encode(png).decode("ascii"))
    note = (
        f"출력 파일은 {columns}단입니다. 이 렌더는 문항 내용 확인용으로, 다단 배치와 쪽수가 한글에서 달라질 수 있습니다."
        if columns > 1
        else "생성한 HWPX의 렌더입니다. 설치된 글꼴과 편집기에 따라 줄바꿈이 달라질 수 있습니다."
    )
    return {
        "pages": pages,
        "page_count": page_count,
        "rendered_page_count": len(pages),
        "truncated": page_count > max_pages,
        "source_format": "hwpx",
        "renderer": "rhwp",
        "column_count": columns,
        "layout_fidelity": "content_only_multicolumn" if columns > 1 else "rendered",
        "note": note,
    }
