"""전 템플릿 커버리지 검증: hwpx_writer(v1) vs hwpx_writer_v2(python-hwpx).

각 ExamTemplate에 대해:
  - v1/v2 둘 다 생성되는가
  - v2가 python-hwpx로 재열기/검증(validate_package errors 비었는가)
  - v1·v2를 같은 추출기로 읽어 텍스트(문단/표셀)가 일치하는가  ← 핵심 패리티
  - v1/v2가 rhwp로 렌더되며 페이지 수가 같은가
실행: python scripts/coverage_hwpx_v2.py
"""
from __future__ import annotations

import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import hwpx_writer, hwpx_writer_v2, storage  # noqa: E402
from app.exam_templates import TEMPLATES  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "exports" / "_cov_v2"
OUT.mkdir(parents=True, exist_ok=True)

# 표/이미지/긴보기/짧은보기 등 모든 분기를 타도록 구성한 문항.
storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
_img_rel = "_cov_v2_img.png"
_img_abs = storage.DATA_DIR / _img_rel
try:
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (300, 150), "white")
    ImageDraw.Draw(im).rectangle([6, 6, 293, 143], outline="black", width=2)
    im.save(_img_abs)
    _have_img = True
except Exception:
    _have_img = False

PROBLEMS = [
    {
        "number": "1", "title": "분수의 덧셈", "subject": "수학", "unit": "5단원",
        "stem": "1. 다음 중 계산 결과가 가장 큰 것은?\n(단, 기약분수로 나타낸다.)",
        "choices": ["1/2+1/3", "2/5+1/5", "3/4+1/8", "1/6+1/6", "5/6+1/6"],
        "answer": "3", "explanation": "3/4 + 1/8 = 7/8 로 가장 크다.",
        "tables": [[["구분", "값"], ["가", "0.83"], ["나", "0.6"]]],
        "image_paths": [_img_rel] if _have_img else [],
    },
    {
        "number": "2", "title": "도형의 둘레", "subject": "수학", "unit": "6단원",
        "stem": "2. 한 변의 길이가 4cm인 정사각형의 둘레는?",
        "choices": ["8cm", "12cm", "16cm", "20cm", "24cm"],
        "answer": "3", "explanation": "4 × 4 = 16cm",
        "tables": [], "image_paths": [],
    },
]


def _extract(path: Path) -> list[str]:
    """문단 + 표 셀 텍스트를 순서대로 뽑아 정규화(빈줄 제거, strip)."""
    from hwpx import HwpxDocument

    doc = HwpxDocument.open(str(path))
    out: list[str] = []
    for p in doc.paragraphs:
        t = (getattr(p, "text", "") or "").strip()
        if t:
            out.append(t)
    return out


def _normalized_stream(items: list[str]) -> str:
    text = "\n".join(items).replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


def _validate(path: Path) -> str:
    try:
        from hwpx import validate_package

        rep = validate_package(str(path))
        errs = getattr(rep, "errors", None)
        return "clean" if not errs else f"ERRORS={errs}"
    except Exception as exc:
        return f"call-fail:{type(exc).__name__}"


def _pages(path: Path) -> int | str:
    try:
        import rhwp

        return int(rhwp.parse(str(path)).page_count)
    except Exception as exc:
        return f"fail:{type(exc).__name__}"


def main() -> int:
    print(f"{'template':<28}{'v1':<5}{'v2':<5}{'valid':<8}{'pages v1/v2':<12}{'text parity'}")
    print("-" * 78)
    all_ok = True
    for tpl in TEMPLATES:
        ans = tpl.include_answers or tpl.include_explanations or tpl.key == "basic"
        p1 = OUT / f"{tpl.key}_v1.hwpx"
        p2 = OUT / f"{tpl.key}_v2.hwpx"
        gen1 = gen2 = "ok"
        try:
            hwpx_writer.write_hwpx(p1, "", PROBLEMS, template_key=tpl.key, include_answer_sheet=ans)
        except Exception as exc:
            gen1 = f"ERR:{type(exc).__name__}"; all_ok = False
        try:
            hwpx_writer_v2.write_hwpx(p2, "", PROBLEMS, template_key=tpl.key, include_answer_sheet=ans)
        except Exception as exc:
            gen2 = f"ERR:{type(exc).__name__}"; all_ok = False

        valid = _validate(p2) if gen2 == "ok" else "-"
        pg1 = _pages(p1) if gen1 == "ok" else "-"
        pg2 = _pages(p2) if gen2 == "ok" else "-"

        parity = "-"
        if gen1 == "ok" and gen2 == "ok":
            t1, t2 = _extract(p1), _extract(p2)
            if t1 == t2:
                parity = f"MATCH ({len(t1)})"
            elif _normalized_stream(t1) == _normalized_stream(t2):
                parity = f"MATCH normalized (v1={len(t1)} v2={len(t2)})"
            else:
                parity = f"DIFF v1={len(t1)} v2={len(t2)}"
                all_ok = False
                # 첫 불일치 지점 출력
                for i, (a, b) in enumerate(zip(t1, t2)):
                    if a != b:
                        print(f"    [{tpl.key}] first diff @#{i}: v1={a!r} | v2={b!r}")
                        break

        if valid != "clean" and valid != "-":
            all_ok = False
        print(f"{tpl.key:<28}{gen1:<5}{gen2:<5}{valid:<8}{str(pg1)+'/'+str(pg2):<12}{parity}")

    if _have_img:
        try:
            _img_abs.unlink()
        except OSError:
            pass
    print("\nRESULT:", "ALL OK" if all_ok else "SEE ISSUES ABOVE")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
