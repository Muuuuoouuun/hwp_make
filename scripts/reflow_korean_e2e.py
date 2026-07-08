"""국어 HWP → 편집추출 → 2단 시험지 재구성(흐름기반) 엔드투엔드 테스트.

원본 국어 HWP의 레이아웃(2단·헤더·지문박스·선지)을 흐름기반 HWPX로 얼마나
재현하는지 뷰어에서 원본과 비교하기 위한 산출물을 만든다.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 매 실행마다 깨끗한 임시 데이터 디렉터리(=신규 DB) 를 써서 중복 스킵을 피한다.
os.environ["HWP_MAKE_DATA_DIR"] = tempfile.mkdtemp(prefix="hwpmake_reflow_")

from app import importers, hwpx_writer_v2, storage  # noqa: E402

storage.init_db()

SRC = Path.home() / "Downloads" / "01.3월_고3_국어_언어와매체.hwp"
OUT = Path.home() / "OneDrive" / "바탕 화면" / "국어_재구성_2단.hwpx"
TEMPLATE = "kice_korean_language_media"


def main() -> None:
    payload = SRC.read_bytes()
    result = importers.import_hwp(SRC.name, payload, {})
    problems = result.get("created", [])
    print(f"추출 문항 수: {len(problems)}")
    for p in problems[:3]:
        stem = (p.get("stem") or "")[:60].replace("\n", " ")
        print(f"  #{p.get('number')}: choices={len(p.get('choices') or [])} "
              f"imgs={len(p.get('image_paths') or [])} tbls={len(p.get('tables') or [])} | {stem}")
    if not problems:
        print("문항 없음 — 중단")
        return
    hwpx_writer_v2.write_hwpx(
        OUT, "국어 영역", problems, TEMPLATE,
        include_answer_sheet=False, native_math=False,
    )
    print("SAVED", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
