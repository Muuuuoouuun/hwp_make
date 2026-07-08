"""회귀핀: recognition IR 스키마(Box/ContentBlock/ProblemUnit/PageModel)의 불변식.

종합 병목 #1(인식 레이아웃정보 소실)을 풀려면 이 IR을 pipeline→storage→writer까지
확장·소비해야 한다. 그 작업 중 IR 계약이 조용히 깨지지 않도록, COLD한 순수 stdlib
모듈 app/recognition/schema.py 를 **수정 없이 import 만** 해서 핵심 불변식을 고정한다.

- Box 좌표 변환(from_points/normalize/denormalize) 왕복 정합
- 블록 분류기(classify_text_block/is_choice_marker/infer_math_like_text) 기대 동작
- PageModel 직렬화(page_to_dict/pages_to_json) 라운드트립 무손실

종료코드 0=통과, 1=실패.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.recognition.schema import (  # noqa: E402
    BlockType,
    Box,
    ContentBlock,
    PageModel,
    ProblemUnit,
    Subject,
    classify_text_block,
    infer_math_like_text,
    is_choice_marker,
    page_to_dict,
    pages_to_json,
)

_failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}{('  · ' + detail) if detail else ''}")
    if not condition:
        _failures.append(name)


def close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def main() -> int:
    # 1) Box 좌표 변환 왕복
    box = Box.from_points(10.0, 20.0, 110.0, 220.0)
    check(
        "Box.from_points 폭/높이",
        close(box.width, 100.0) and close(box.height, 200.0) and close(box.right, 110.0) and close(box.bottom, 220.0),
        f"w={box.width} h={box.height}",
    )
    norm = box.normalize(1000.0, 2000.0)
    back = norm.denormalize(1000.0, 2000.0)
    check(
        "Box normalize→denormalize 왕복",
        close(back.left, box.left) and close(back.top, box.top) and close(back.width, box.width) and close(back.height, box.height),
    )

    # 2) 블록 분류기
    check("infer_math_like_text(수식)", infer_math_like_text("f(x) = lim x^2") is True)
    check("infer_math_like_text(평문)", infer_math_like_text("다음 글을 읽고") is False)
    check("is_choice_marker(원문자)", is_choice_marker("① 첫 번째 선지") is True)
    check("is_choice_marker(평문)", is_choice_marker("가나다 라마바") is False)
    check("classify_text_block(수식)", classify_text_block("함수 f(x)=2x+1의 값") == BlockType.FORMULA)
    check("classify_text_block(선지)", classify_text_block("① 보기 하나") == BlockType.CHOICE)
    check("classify_text_block(본문)", classify_text_block("아래 자료를 분석하여 물음에 대한 답을 서술형으로 자세히 쓰시오") == BlockType.STEM)
    check("classify_text_block(섹션제목)", classify_text_block("제3장") == BlockType.SECTION)

    # 3) PageModel 직렬화 라운드트립
    title_block = ContentBlock(
        block_id="p1-b1",
        block_type=BlockType.TITLE,
        bbox=Box.from_points(0, 0, 500, 40),
        reading_order=0,
        text="1.",
        metadata={"problem_number": 1, "column_index": 1},
    )
    unit = ProblemUnit(
        unit_id="p1-u1",
        subject=Subject.MATH,
        title="1",
        stem_block_ids=["p1-b1"],
        metadata={"problem_number": 1, "title_block_id": "p1-b1"},
    )
    page = PageModel(
        page_id="page-001",
        width_px=1000,
        height_px=1400,
        subject=Subject.MATH,
        blocks=[title_block],
        problems=[unit],
        metadata={"column_count": 2, "marker_count": 1},
    )
    as_dict = page_to_dict(page)
    check(
        "page_to_dict 키 보존",
        {"page_id", "width_px", "height_px", "blocks", "problems", "metadata"}.issubset(as_dict.keys()),
    )
    check("page_to_dict 블록 bbox 보존", as_dict["blocks"][0]["bbox"]["width"] == 500.0)
    check("page_to_dict metadata column_count 보존", as_dict["metadata"].get("column_count") == 2)
    try:
        parsed = json.loads(pages_to_json([page]))
        json_ok = isinstance(parsed, list) and parsed and parsed[0]["problems"][0]["title"] == "1"
    except Exception as exc:  # noqa: BLE001
        json_ok = False
        print(f"    (pages_to_json 예외: {exc})")
    check("pages_to_json JSON 라운드트립", bool(json_ok))

    # 4) PageModel.normalize + sorted_blocks 무크래시
    try:
        page.normalize()
        _ = page.sorted_blocks()
        norm_ok = True
    except Exception as exc:  # noqa: BLE001
        norm_ok = False
        print(f"    (normalize/sorted_blocks 예외: {exc})")
    check("PageModel.normalize/sorted_blocks 무크래시", norm_ok)

    if _failures:
        print(f"RECOGNITION_SCHEMA_FAIL ({len(_failures)}건): {', '.join(_failures)}")
        return 1
    print("RECOGNITION_SCHEMA_OK — IR 계약 불변식 유지")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
