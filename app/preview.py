"""내보내기 전 미리보기: 생성한 HWPX를 rhwp 엔진으로 PNG 렌더링한다.

rhwp는 선택 의존성이다. 없으면 미리보기 기능만 비활성화된다.
한계: rhwp 렌더러는 다단(colPr) 레이아웃을 아직 1단으로 그린다.
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Any

from . import hwpx_writer

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
) -> dict[str, Any]:
    if rhwp is None:
        raise RuntimeError("미리보기 엔진(rhwp-python)이 설치되어 있지 않습니다.")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "preview.hwpx"
        hwpx_writer.write_hwpx(
            path,
            title,
            problems,
            template_key=template_key,
            include_answer_sheet=include_answer_sheet,
        )
        doc = rhwp.parse(str(path))
        page_count = int(doc.page_count)
        pages: list[str] = []
        for page in range(min(page_count, max_pages)):
            png = bytes(doc.render_png(page))
            pages.append("data:image/png;base64," + base64.b64encode(png).decode("ascii"))
    return {"pages": pages, "page_count": page_count, "truncated": page_count > max_pages}
