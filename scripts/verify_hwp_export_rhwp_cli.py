# -*- coding: utf-8 -*-
"""rhwp 명령줄 도구로 하는 HWP 내보내기·배포용 HWP 해제 검증.

Filee(MIT)가 쓰는 rhwp CLI `convert`로 한컴 없이 HWPX → HWP 5.0을 만든다.
- /api/export format=hwp: OLE HWP 5.0, 이 앱의 HWP 가져오기로 다시 읽으면 문항·수식·표 유지.
- rhwp 자체 검증(다시 읽은 IR 차이, 쪽 수)에 실패하거나 도구가 없으면 HWP를 내주지 않는다.
- 배포용이 아닌 HWP는 해제 경로를 타지 않는다.

한컴이 이 HWP를 여는지는 Windows 한글에서 따로 확인해야 한다.
종료코드 0=통과, 1=실패, 2=rhwp CLI 없음(SKIP; scripts/fetch_rhwp_cli.py로 받는다).
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory()
os.environ["HWP_MAKE_DATA_DIR"] = _TMP.name

import olefile  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app import importers, main, rhwp_cli, storage  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}{('  · ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def main_check() -> int:
    if not rhwp_cli.available():
        print("SKIP: rhwp CLI not found (python scripts/fetch_rhwp_cli.py)")
        return 2
    storage.init_db()
    ids = []
    for number in range(1, 5):
        created = storage.create_problem(
            {
                "number": str(number),
                "stem": f"{number}. 함수 $f(x)=\\frac{{x^2+{number}}}{{x-1}}$ 에 대하여 $\\lim_{{x\\to\\infty}} f(x)$ 의 값은?",
                "choices": [f"${value}$" for value in range(1, 6)],
                "tables": [[["x", "1"], ["f(x)", "$\\sqrt{2}$"]]] if number == 2 else [],
                "answer": "1",
            }
        )
        ids.append(created["id"])

    check("health 에 HWP 내보내기 가능 표시", main.health().get("hwp_export_available") is True)
    payload = main.ExportPayload(ids=ids, title="HWP 내보내기", format="hwp", template_key="kice_math")
    response = main.export(payload)
    path = Path(response.path)
    data = path.read_bytes()
    check("파일 이름 .hwp", path.suffix == ".hwp", path.name)
    check("OLE 서명", data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    with olefile.OleFileIO(io.BytesIO(data)) as ole:
        header = ole.openstream("FileHeader").read()
        check("HWP 5.0 FileHeader", header[:17] == b"HWP Document File" and header[35] == 5, header[32:36].hex())
        check("본문 구역 있음", ole.exists("BodyText/Section0"))
    check("중간 HWPX 삭제", not list(path.parent.glob("*.stage.hwpx")))

    result = importers.import_hwp("roundtrip.hwp", data, {})
    problems = [storage.get_problem(problem_id) for problem_id in result.get("ordered_ids", [])]
    stems = "\n".join(problem["stem"] for problem in problems)
    tables = [table for problem in problems for table in problem.get("tables") or []]
    check("다시 가져온 문항 4개", len(problems) == 4, str([p["number"] for p in problems]))
    check("한컴 수식 유지", "over" in stems and "lim" in stems, stems[:120])
    check("표 안 수식 유지", any("sqrt" in cell for table in tables for row in table for cell in row), str(tables)[:200])

    check("배포용 아닌 HWP는 해제하지 않음", rhwp_cli.unlock_distribution_hwp(data) is None)

    original_locate = rhwp_cli.locate
    rhwp_cli.locate = lambda: None
    try:
        try:
            main.export(payload)
            missing = None
        except HTTPException as exc:
            missing = exc
    finally:
        rhwp_cli.locate = original_locate
    check(
        "도구가 없으면 503 hwp_unavailable",
        missing is not None and missing.status_code == 503 and missing.detail.get("code") == "hwp_unavailable",
        str(getattr(missing, "detail", None)),
    )

    original_convert = rhwp_cli._run_convert

    def failing_convert(source: Path, target: Path, *, verify: bool) -> dict:
        raise rhwp_cli.RhwpCliError("rhwp 변환 검증 실패(page_mismatch)")

    rhwp_cli._run_convert = failing_convert
    before = set(storage.EXPORT_DIR.glob("*.hwp"))
    try:
        try:
            main.export(payload)
            failed = None
        except HTTPException as exc:
            failed = exc
    finally:
        rhwp_cli._run_convert = original_convert
    check(
        "검증 실패면 HWP를 내주지 않음",
        failed is not None and failed.detail.get("code") == "hwp_convert_failed"
        and set(storage.EXPORT_DIR.glob("*.hwp")) == before
        and not list(storage.EXPORT_DIR.glob("*.stage.hwpx")),
        str(getattr(failed, "detail", None)),
    )

    if failures:
        print("FAIL: " + ", ".join(failures))
        return 1
    print("HWP_EXPORT_RHWP_CLI_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main_check())
