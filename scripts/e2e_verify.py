"""제품 B 무회귀 골든 E2E 하네스.

원본 샘플(PDF/HWP/HWPX/DOCX) → import → storage → write_hwpx(프로덕션 v2) → reopen 까지
실제 파이프라인을 돌려 스냅샷(문항수·수식수·이미지수·섹션수·reopen 성공)을 JSON으로 덤프한다.
이후 좌표 배선 phase마다 이 스냅샷을 baseline과 비교해 '무회귀'를 자동 감지한다.

특징:
- 실행 시 임시 DATA_DIR(HWP_MAKE_DATA_DIR)로 격리 — 실제 DB를 오염시키지 않는다.
- 개인 경로 하드코딩 없음. 샘플은 (1) CLI 인자, 없으면 (2) data/uploads 자동탐색.
  샘플이 없으면 '검증할 것 없음'으로 안전 종료(코드 0).
- baseline 비교 모드: 첫 실행/--update 는 scripts/_e2e_baseline.json 저장, 이후는 diff.
  스냅샷이 baseline과 다르거나 import/export/reopen 이 실패하면 종료코드 1(CI 사용 가능).

사용:
  python scripts/e2e_verify.py                      # data/uploads 자동탐색(최대 각 1건)
  python scripts/e2e_verify.py a.pdf b.hwp          # 명시 샘플
  python scripts/e2e_verify.py --update             # 현재 결과를 baseline으로 저장
  python scripts/e2e_verify.py --all a.pdf b.pdf …  # 자동탐색 개수 제한 해제
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

# 콘솔 코드페이지(cp949 등)와 무관하게 UTF-8로 출력 — 어떤 환경에서도 UnicodeEncodeError 방지.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "scripts" / "_e2e_baseline.json"
SUPPORTED = ("pdf", "hwp", "hwpx", "docx")


def discover_samples(explicit: list[str], take_all: bool) -> list[Path]:
    if explicit:
        return [Path(p).resolve() for p in explicit]
    uploads = ROOT / "data" / "uploads"
    if not uploads.is_dir():
        return []
    found: dict[str, list[Path]] = {ext: [] for ext in SUPPORTED}
    for path in sorted(uploads.iterdir()):
        ext = path.suffix.lower().lstrip(".")
        if path.is_file() and ext in found:
            found[ext].append(path)
    picked: list[Path] = []
    for ext in SUPPORTED:
        picked.extend(found[ext] if take_all else found[ext][:1])
    return picked


def inspect_hwpx(path: Path) -> dict:
    """생성된 HWPX 를 unzip 해 수식/이미지/섹션 수를 세고, 벤더 라이브러리로 reopen 확인."""
    equations = images = sections = 0
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        images = sum(1 for n in names if n.startswith("BinData/") and not n.endswith("/"))
        section_names = [
            n for n in names if n.startswith("Contents/section") and n.endswith(".xml")
        ]
        sections = len(section_names)
        for name in section_names:
            xml = archive.read(name).decode("utf-8", "replace")
            equations += xml.count("<hp:equation")

    reopen_ok = False
    reopen_err = ""
    try:
        sys.path.insert(0, str(ROOT / "app" / "_vendor"))
        from hwpx import HwpxDocument  # type: ignore

        HwpxDocument.open(str(path))
        reopen_ok = True
    except Exception as exc:  # noqa: BLE001
        reopen_err = f"{type(exc).__name__}: {exc}"
    return {
        "equations": equations,
        "images": images,
        "sections": sections,
        "reopen_ok": reopen_ok,
        "reopen_err": reopen_err,
    }


def run_one(path: Path, storage, importers, writer) -> dict:
    ext = path.suffix.lower().lstrip(".")
    snap: dict = {"name": path.name, "ext": ext}
    importer_map = {
        "pdf": importers.import_pdf,
        "hwp": importers.import_hwp,
        "hwpx": importers.import_hwpx,
        "docx": importers.import_docx,
    }
    importer = importer_map.get(ext)
    if importer is None:
        snap["error"] = f"unsupported ext: {ext}"
        return snap
    try:
        result = importer(path.name, path.read_bytes(), {})
        created = result.get("created", []) or []
        ids = [p["id"] for p in created if "id" in p]
        problems = storage.get_problems_by_ids(ids)
        snap["problems"] = len(problems)

        out_dir = Path(os.environ["HWP_MAKE_DATA_DIR"]) / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{path.stem}.hwpx"
        # native_math=True: 제품 B는 수식 충실도가 기본이어야 한다(하네스는 항상 켜서 검증).
        writer.write_hwpx(out, path.stem, problems, "basic", native_math=True)
        snap.update(inspect_hwpx(out))
    except Exception as exc:  # noqa: BLE001
        snap["error"] = f"{type(exc).__name__}: {exc}"
    return snap


def normalize(snapshots: list[dict]) -> list[dict]:
    # reopen_err/error 메시지는 diff 안정성을 위해 존재여부(bool)로만 비교, 순서는 name 정렬.
    out = []
    for snap in sorted(snapshots, key=lambda s: s.get("name", "")):
        norm = dict(snap)
        if "reopen_err" in norm:
            norm["reopen_err"] = bool(norm["reopen_err"])
        norm["has_error"] = bool(norm.pop("error", ""))
        out.append(norm)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="제품 B 무회귀 골든 E2E 하네스")
    parser.add_argument("samples", nargs="*", help="검증할 샘플 파일(생략 시 data/uploads 자동탐색)")
    parser.add_argument("--update", action="store_true", help="현재 결과를 baseline으로 저장")
    parser.add_argument("--all", action="store_true", help="자동탐색 시 확장자별 1건 제한 해제")
    args = parser.parse_args()

    # 임시 DATA_DIR 격리는 반드시 app 모듈 import 전에 설정해야 한다(storage가 import 시 DATA_DIR 확정).
    tmp = tempfile.mkdtemp(prefix="hwpmake_e2e_")
    os.environ["HWP_MAKE_DATA_DIR"] = tmp
    sys.path.insert(0, str(ROOT))

    from app import storage, importers, hwpx_writer_v2  # noqa: E402

    storage.init_db()

    samples = discover_samples(args.samples, args.all)
    if not samples:
        print("샘플 없음: data/uploads에 PDF/HWP/HWPX/DOCX가 없거나 인자를 주지 않았습니다.")
        print("→ 검증할 것이 없어 안전 종료합니다(코드 0). 샘플 경로를 인자로 주면 실검증합니다.")
        return 0

    print(f"샘플 {len(samples)}건 검증 (격리 DATA_DIR={tmp})")
    snapshots = [run_one(p, storage, importers, hwpx_writer_v2) for p in samples]
    current = normalize(snapshots)

    for snap in current:
        status = "OK" if (snap.get("reopen_ok") and not snap["has_error"]) else "FAIL"
        print(
            f"  [{status}] {snap['name']}: 문항={snap.get('problems','?')} "
            f"수식={snap.get('equations','?')} 이미지={snap.get('images','?')} "
            f"섹션={snap.get('sections','?')} reopen={snap.get('reopen_ok')}"
        )

    hard_fail = any(s["has_error"] or not s.get("reopen_ok") for s in current)

    if args.update or not BASELINE_PATH.exists():
        BASELINE_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"baseline 저장: {BASELINE_PATH}")
        return 1 if hard_fail else 0

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if baseline == current:
        print("baseline과 일치 (무회귀).")
        return 1 if hard_fail else 0

    print("⚠ baseline과 다릅니다(회귀 가능). 의도된 변경이면 --update로 갱신하세요.")
    print("--- baseline ---")
    print(json.dumps(baseline, ensure_ascii=False, indent=2))
    print("--- current ---")
    print(json.dumps(current, ensure_ascii=False, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
