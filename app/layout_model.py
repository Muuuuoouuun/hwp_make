"""레이아웃 정보 소비 헬퍼 — 병목 #1(인식 레이아웃 소실)의 격리 모듈.

인식이 이미 계산한 컬럼/좌표 정보를 writer가 소비하는 순수 로직만 모은다. 판정 로직을
여기 격리해 hwpx_writer_v2.py(코덱스 핫존) 편집을 append-only 최소 배선(호출 1~2줄)으로
줄인다. problem dict의 nullable ``layout`` 페이로드를 읽되, 없으면 안전한 폴백값을 낸다.

layout 페이로드(importers가 채움, 없으면 None):
  {"column_count": 1|2, "column_index": int, "reading_order": int,
   "page": {"number": int, "width_px": int, "height_px": int},
   "bbox_px": [left, top, w, h], "block_type": str, "stem_group": str|None}
"""
from __future__ import annotations

from typing import Any


def _layout(problem: dict[str, Any]) -> dict[str, Any]:
    value = problem.get("layout")
    return value if isinstance(value, dict) else {}


def recognized_column_count(problems: list[dict[str, Any]]) -> int:
    """인식이 검출한 문서 컬럼 수(1 또는 2). 정보 없으면 0(= 호출부가 template 폴백)."""
    counts = []
    for problem in problems:
        count = _layout(problem).get("column_count") or 0
        if count in (1, 2):
            counts.append(count)
    return max(counts) if counts else 0


def column_break_before(prev: dict[str, Any] | None, cur: dict[str, Any]) -> bool:
    """원본에서 cur 문항이 이전 문항 대비 다음 컬럼에서 시작하면 True(2차 배선용).

    layout 정보가 없으면 항상 False → 호출부는 기존 높이추정 경로로 폴백.
    """
    if prev is None:
        return False
    a = _layout(prev)
    b = _layout(cur)
    if not a or not b or "column_index" not in b:
        return False
    same_page = b.get("page", {}).get("number") == a.get("page", {}).get("number")
    return bool(same_page and b["column_index"] > a.get("column_index", b["column_index"]))


def px_to_hwpunit(px: float, dpi: int = 150) -> int:
    """인식 렌더 픽셀(dpi) → HWPUNIT(1/7200인치). 좌표 앵커/폭 계산용.

    HWPUNIT = inch * 7200 = (px / dpi) * 7200. 인식 기본 dpi=150 → px*48.
    """
    if dpi <= 0:
        return 0
    return round(px * 7200.0 / dpi)
