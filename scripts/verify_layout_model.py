"""단위 테스트: app/layout_model.py — 병목 #1 레이아웃 소비 헬퍼.

인식 레이아웃 정보(컬럼/좌표)를 problem dict에서 읽는 순수 로직과 px→HWPUNIT 변환을
고정한다. 이 헬퍼가 안정적이어야 코덱스가 hwpx_writer_v2에 1~2줄만 배선하면 된다.

종료코드 0=통과, 1=실패.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.layout_model import (  # noqa: E402
    column_break_before,
    px_to_hwpunit,
    recognized_column_count,
)

_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}{('  · ' + detail) if detail else ''}")
    if not cond:
        _failures.append(name)


def L(**kw):  # layout 페이로드 헬퍼
    return {"layout": kw}


def main() -> int:
    # recognized_column_count
    check("2단 인식", recognized_column_count([L(column_count=2), L(column_count=2)]) == 2)
    check("1단 인식", recognized_column_count([L(column_count=1)]) == 1)
    check("layout 없음 → 0(폴백)", recognized_column_count([{}, {"layout": None}]) == 0)
    check("잘못된 값(3) → 0", recognized_column_count([L(column_count=3)]) == 0)
    check("혼재 → max(2)", recognized_column_count([L(column_count=1), L(column_count=2)]) == 2)

    # column_break_before
    p_c1 = {**L(column_index=1), "layout": {"column_index": 1, "page": {"number": 1}}}
    p_c2 = {"layout": {"column_index": 2, "page": {"number": 1}}}
    p_p2c1 = {"layout": {"column_index": 1, "page": {"number": 2}}}
    check("같은 페이지 col1→col2 True", column_break_before(p_c1, p_c2) is True)
    check("prev None False", column_break_before(None, p_c2) is False)
    check("layout 없음 False", column_break_before({}, {}) is False)
    check("페이지 바뀜 False", column_break_before(p_c2, p_p2c1) is False)

    # px_to_hwpunit
    check("150px@150dpi = 7200(1인치)", px_to_hwpunit(150, dpi=150) == 7200)
    check("300px@150dpi = 14400", px_to_hwpunit(300, dpi=150) == 14400)
    check("dpi 0 방어 → 0", px_to_hwpunit(100, dpi=0) == 0)

    if _failures:
        print(f"LAYOUT_MODEL_FAIL ({len(_failures)}건): {', '.join(_failures)}")
        return 1
    print("LAYOUT_MODEL_OK — 레이아웃 소비 헬퍼 계약 유지")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
