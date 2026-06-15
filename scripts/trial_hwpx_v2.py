"""기존 hwpx_writer vs python-hwpx 기반 hwpx_writer_v2 비교 시험(평가용).

같은 문항 입력으로 두 writer를 돌려:
  1) 둘 다 정상 생성되는지
  2) v2 출력이 python-hwpx로 재열기/검증되는지 + 추출 텍스트 비교
  3) 두 출력이 rhwp로 렌더(페이지 수)되는지, PNG를 out 디렉터리에 저장
을 확인한다. 실행: python scripts/trial_hwpx_v2.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import hwpx_writer, hwpx_writer_v2, storage  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "exports" / "_trial_v2"
OUT.mkdir(parents=True, exist_ok=True)

# --- 대표 문항(텍스트/보기/표/이미지/정답/해설 전부 포함) ---
storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
_img_rel = "_trial_v2_img.png"
_img_abs = storage.DATA_DIR / _img_rel
try:
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (320, 160), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([8, 8, 311, 151], outline="black", width=2)
    d.text((20, 70), "trial diagram", fill="black")
    im.save(_img_abs)
    _have_img = True
except Exception as exc:  # pragma: no cover
    print("이미지 생성 실패, 이미지 없이 진행:", exc)
    _have_img = False

problems = [
    {
        "number": "1",
        "title": "분수의 덧셈",
        "subject": "수학",
        "unit": "5단원",
        "stem": "다음 중 계산 결과가 가장 큰 것은?\n(단, 모든 분수는 기약분수로 나타낸다.)",
        "choices": ["1/2 + 1/3", "2/5 + 1/5", "3/4 + 1/8", "1/6 + 1/6"],
        "answer": "③",
        "explanation": "3/4 + 1/8 = 7/8 로 가장 크다.",
        "tables": [[["구분", "값"], ["가", "0.83"], ["나", "0.6"]]],
        "image_paths": [_img_rel] if _have_img else [],
    },
    {
        "number": "2",
        "title": "도형의 둘레",
        "subject": "수학",
        "unit": "6단원",
        "stem": "한 변의 길이가 4cm인 정사각형의 둘레는 몇 cm인가?",
        "choices": ["8cm", "12cm", "16cm", "20cm"],
        "answer": "③",
        "explanation": "4 × 4 = 16cm",
        "tables": [],
        "image_paths": [],
    },
]

TEMPLATE = "basic"


def _members(path: Path) -> list[str]:
    import zipfile

    return sorted(zipfile.ZipFile(path).namelist())


def _render(path: Path, tag: str) -> str:
    try:
        import rhwp
    except Exception:
        return "rhwp 미설치 — 렌더 생략"
    try:
        doc = rhwp.parse(str(path))
        n = int(doc.page_count)
        for p in range(n):
            png = bytes(doc.render_png(p))
            (OUT / f"{tag}_p{p}.png").write_bytes(png)
        return f"{n} pages → {OUT}\\{tag}_p*.png"
    except Exception as exc:
        return f"렌더 실패: {type(exc).__name__}: {exc}"


def main() -> int:
    old_path = OUT / "old.hwpx"
    new_path = OUT / "v2.hwpx"

    print("=== 1) 생성 ===")
    hwpx_writer.write_hwpx(old_path, "시험 문항지", problems, template_key=TEMPLATE, include_answer_sheet=True)
    print("old  OK:", old_path.name, "| members:", len(_members(old_path)))
    hwpx_writer_v2.write_hwpx(new_path, "시험 문항지", problems, template_key=TEMPLATE, include_answer_sheet=True)
    print("v2   OK:", new_path.name, "| members:", len(_members(new_path)))
    print("  old members:", _members(old_path))
    print("  v2  members:", _members(new_path))

    print("\n=== 2) v2 재열기 + 검증 ===")
    from hwpx import HwpxDocument  # vendored, sys.path already patched by v2 import

    d = HwpxDocument.open(str(new_path))
    texts = [getattr(p, "text", "") for p in d.paragraphs if getattr(p, "text", "")]
    print("  추출 문단 수:", len(texts))
    for t in texts[:12]:
        print("   ·", t)
    try:
        from hwpx import validate_package

        report = validate_package(str(new_path))
        ok = getattr(report, "is_valid", getattr(report, "valid", "?"))
        errs = getattr(report, "errors", None)
        print("  validate_package:", ok, "| errors:", errs)
    except Exception as exc:
        print("  validate_package 호출 불가:", type(exc).__name__, exc)

    print("\n=== 3) rhwp 렌더 ===")
    print("  old:", _render(old_path, "old"))
    print("  v2 :", _render(new_path, "v2"))

    # 정리
    if _have_img:
        try:
            _img_abs.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
