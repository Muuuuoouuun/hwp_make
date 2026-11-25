# -*- coding: utf-8 -*-
"""데스크톱(기본판) 작업자의 한글(HWP) 저장 경로 검증.

app.desktop_convert.convert 를 실제 작업자처럼 변환마다 새 프로세스에서 부른다.
- TXT·PDF → .hwp: HWP 5.0(OLE, FileHeader, BodyText/Section0), format=hwp.
- rhwp 변환이 검증에 실패하면(가짜 도구, exit 3) HWPX로 대신 저장하고 이유를 경고에 남긴다.
  같은 이름의 .hwpx 가 이미 있으면 덮어쓰지 않고 "이름 (1).hwpx" 에 저장한다.
- rhwp 도구가 없으면 처음부터 HWPX로 저장한다.
종료코드 0=통과, 1=실패, 2=rhwp CLI 없음(SKIP; scripts/fetch_rhwp_cli.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}{('  · ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def convert(source: Path, destination: Path, job: Path, rhwp: str | None = None) -> dict:
    """One conversion in a fresh process, like run_desktop.py --worker."""
    env = dict(os.environ)
    if rhwp is not None:
        env["HWP_MAKE_RHWP_CLI"] = rhwp
    code = (
        "import json, sys; from pathlib import Path; sys.path.insert(0, sys.argv[4]);"
        "from app.desktop_convert import convert;"
        "print('RESULT ' + json.dumps(convert(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])), ensure_ascii=False))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code, str(source), str(destination), str(job), str(ROOT)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=900, check=False,
    )
    line = next((x for x in completed.stdout.splitlines() if x.startswith("RESULT ")), None)
    if line is None:
        return {"ok": False, "error": (completed.stderr or completed.stdout)[-800:]}
    return json.loads(line[len("RESULT "):])


def is_hwp(path: Path) -> bool:
    import olefile

    if not path.is_file() or not olefile.isOleFile(str(path)):
        return False
    with olefile.OleFileIO(str(path)) as package:
        return (
            package.exists("FileHeader")
            and package.openstream("FileHeader").read(17) == b"HWP Document File"
            and package.exists("BodyText/Section0")
        )


def main() -> int:
    from app import rhwp_cli

    if not rhwp_cli.available():
        print("SKIP: rhwp CLI not found (python scripts/fetch_rhwp_cli.py)")
        return 2
    import fitz

    with tempfile.TemporaryDirectory(prefix="hwp_make_desktop_hwp_") as tmp:
        work = Path(tmp)
        text = work / "원본 문항.txt"
        text.write_text("7. 다음 계산의 결과는?\n2 + 3 = ?\n① 3\n② 4\n③ 5\n④ 6\n⑤ 7", encoding="utf-8")
        pdf = work / "전체 원본.pdf"
        document = fitz.open()
        for index in range(2):
            page = document.new_page()
            page.insert_text((72, 90), f"{index + 1}. Calculate 2 + 3.")
            page.insert_text((72, 120), "A. 3    B. 4    C. 5")
        document.save(pdf)
        document.close()

        result = convert(text, work / "텍스트 결과.hwp", work / "job1")
        check("TXT → HWP", result.get("format") == "hwp" and is_hwp(work / "텍스트 결과.hwp"), str(result)[:300])
        result = convert(pdf, work / "전체 결과.hwp", work / "job2")
        check(
            "PDF 원본 배치 → HWP(2쪽)",
            result.get("format") == "hwp" and result.get("pages") == 2 and is_hwp(work / "전체 결과.hwp"),
            str(result)[:300],
        )

        # A converter that fails its verification (exit 3 = IR mismatch).
        fake = work / "rhwp_fails"
        fake.write_text("#!/bin/sh\necho 'verify: IR differs' >&2\nexit 3\n", encoding="utf-8")
        fake.chmod(0o755)
        taken = work / "실패 대체.hwpx"
        taken.write_bytes(b"user file")
        result = convert(text, work / "실패 대체.hwp", work / "job3", rhwp=str(fake))
        output = Path(result.get("output", ""))
        check("검증 실패 TXT는 HWPX로 대신 저장", result.get("format") == "hwpx" and output.suffix == ".hwpx", str(result)[:300])
        check("사용자의 같은 이름 HWPX는 그대로", taken.read_bytes() == b"user file" and output.name == "실패 대체 (1).hwpx", output.name)
        check("대신 저장한 이유 안내", any("HWPX로 저장" in w for w in result.get("warnings", [])), str(result.get("warnings")))
        check("거절한 HWP는 남기지 않음", not (work / "실패 대체.hwp").exists())
        result = convert(pdf, work / "PDF 실패 대체.hwp", work / "job4", rhwp=str(fake))
        check(
            "검증 실패 PDF는 원본 배치 HWPX로 대신 저장",
            result.get("format") == "hwpx" and Path(result.get("output", "")).name == "PDF 실패 대체.hwpx",
            str(result)[:300],
        )
        check("PDF 대체 이유 안내", any("HWPX로 제공" in w for w in result.get("warnings", [])), str(result.get("warnings")))

        result = convert(pdf, work / "도구 없음.hwp", work / "job5", rhwp=str(work / "없는 도구"))
        check("rhwp 도구가 없으면 HWPX로 저장", result.get("format") == "hwpx" and Path(result.get("output", "")).suffix == ".hwpx", str(result)[:300])
        check("도구 없음 안내", any("rhwp" in w for w in result.get("warnings", [])), str(result.get("warnings")))

    if failures:
        print("FAIL: " + ", ".join(failures))
        return 1
    print("DESKTOP_HWP_OUTPUT_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
