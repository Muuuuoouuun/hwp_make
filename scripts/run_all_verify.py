"""통합 회귀 러너 — scripts/verify_*.py + e2e_verify.py 를 한 게이트로 집계.

병렬 편집(코덱스 핫존)이 빠른 저장소에서 '단일 회귀 게이트'가 없어 재퇴행을 못 잡는
문제(종합 병목 #7)를 해결한다. 각 검증 스크립트를 **격리 서브프로세스**로 돌려
(소스 import 충돌 0) exit 코드로 판정하고 요약한다.

판정 관례(이 저장소 공통):
  0 = PASS, 2 = SKIP(개인 샘플 없음 등), 그 외 = FAIL, 타임아웃 = FAIL.

모든 서브프로세스에 UTF-8 환경(PYTHONUTF8=1)을 강제해 cp949 콘솔 크래시/인코딩
비결정성을 차단한다. 뷰어/개인경로 의존 스크립트는 기본 제외(자동화 부적합).

사용:
  python scripts/run_all_verify.py            # 자동화 검증 전체
  python scripts/run_all_verify.py --list     # 대상만 나열
종료코드: FAIL 0건이면 0, 하나라도 FAIL이면 1.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 뷰어 실행/개인경로(~/Downloads·바탕화면) 의존이라 CI 부적합 → 기본 제외.
# (대부분 verify_ prefix가 아니라 자동 제외되지만 방어적으로 명시.)
EXCLUDE = {
    "run_all_verify.py",
    "pos_frame_probe.py",
    "reflow_korean_e2e.py",
    "qa_hwp_math_samples.py",
    "pdf_layout_hwpx_probe.py",
}
TIMEOUT_SEC = 300


def discover_py() -> list[Path]:
    targets = sorted(SCRIPTS.glob("verify_*.py"))
    e2e = SCRIPTS / "e2e_verify.py"
    if e2e.exists():
        targets.append(e2e)
    return [p for p in targets if p.name not in EXCLUDE]


def classify(code: int) -> str:
    if code == 0:
        return "PASS"
    if code == 2:
        return "SKIP"
    return "FAIL"


def run_subprocess(cmd: list[str]) -> tuple[str, int, str]:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return ("FAIL", 124, "(타임아웃)")
    tail_lines = (proc.stdout or "").strip().splitlines()[-3:]
    tail = " / ".join(line.strip() for line in tail_lines if line.strip())
    return (classify(proc.returncode), proc.returncode, tail)


def main() -> int:
    parser = argparse.ArgumentParser(description="통합 회귀 러너")
    parser.add_argument("--list", action="store_true", help="대상 스크립트만 나열")
    args = parser.parse_args()

    py_targets = discover_py()
    node_target = SCRIPTS / "verify_frontend_math.js"
    has_node = shutil.which("node") is not None

    if args.list:
        for path in py_targets:
            print(f"  py   {path.name}")
        if node_target.exists():
            print(f"  node {node_target.name} ({'node 있음' if has_node else 'node 없음→SKIP'})")
        return 0

    results: list[tuple[str, str, int, str]] = []

    for path in py_targets:
        status, code, tail = run_subprocess([sys.executable, str(path)])
        results.append((path.name, status, code, tail))
        print(f"  [{status:4}] {path.name} (exit {code}){('  · ' + tail) if tail else ''}")

    if node_target.exists():
        if has_node:
            status, code, tail = run_subprocess(["node", str(node_target)])
        else:
            status, code, tail = ("SKIP", 2, "(node 미설치)")
        results.append((node_target.name, status, code, tail))
        print(f"  [{status:4}] {node_target.name} (exit {code}){('  · ' + tail) if tail else ''}")

    passed = sum(1 for _, s, _, _ in results if s == "PASS")
    skipped = sum(1 for _, s, _, _ in results if s == "SKIP")
    failed = [name for name, s, _, _ in results if s == "FAIL"]
    print(f"\n요약: PASS {passed} · SKIP {skipped} · FAIL {len(failed)}")
    if failed:
        print("FAIL: " + ", ".join(failed))
        return 1
    print("ALL GREEN (통합 회귀 게이트 통과)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
