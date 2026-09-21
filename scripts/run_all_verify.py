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
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
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
# These are artifact inspection CLIs, not standalone regression tests.
MANUAL_INPUTS = {
    "verify_detection_quality_97.py": "package_dir 필요",
    "verify_four_theme_quality.py": "package_dir 필요",
    "verify_hancom_pdf_visual_fidelity.py": "원본 PDF와 한컴 저장 PDF 필요",
    "verify_math_visual_spacing.py": "원본 PDF와 한컴 저장 PDF 필요",
    "verify_pdf_layout_hwpx.py": "검사할 HWPX 경로 필요 (API/변환 회귀에서도 검사)",
}
# 실물 시험 다건 변환+렌더+합성 스위트는 300초로 부족(단독 PASS인데 게이트에서만
# exit 124 타임아웃 FAIL 나던 사례, 2026-08-04). 스크립트별 상한 오버라이드.
TIMEOUT_OVERRIDES_SEC = {
    "verify_external_exam_detail_quality.py": 900,
    "verify_unseen_exam_quality.py": 900,
}


def discover_py() -> list[Path]:
    targets = sorted(SCRIPTS.glob("verify_*.py"))
    e2e = SCRIPTS / "e2e_verify.py"
    if e2e.exists():
        targets.append(e2e)
    return [p for p in targets if p.name not in EXCLUDE]


def classify(code: int, stderr: str = "") -> str:
    if code == 0:
        return "PASS"
    if code == 2:
        if re.search(r"(?m)^usage:|\berror:", stderr, re.IGNORECASE):
            return "FAIL"
        return "SKIP"
    return "FAIL"


def run_subprocess(cmd: list[str], *, timeout_sec: int = TIMEOUT_SEC,
                   log_path: Path | None = None) -> tuple[str, int, str]:
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
            timeout=timeout_sec,
        )
        stdout, stderr, code = proc.stdout or "", proc.stderr or "", proc.returncode
    except subprocess.TimeoutExpired as exc:
        def decoded(value):
            return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
        stdout, stderr, code = decoded(exc.stdout), decoded(exc.stderr) + "\n(타임아웃)", 124
    except OSError as exc:
        stdout, stderr, code = "", str(exc), 127
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(stdout + "\n--- stderr ---\n" + stderr, encoding="utf-8")
    status = classify(code, stderr)
    tail_lines = stdout.strip().splitlines()[-3:]
    if status == "FAIL" or not tail_lines:
        tail_lines += stderr.strip().splitlines()[-3:]
    tail = " / ".join(line.strip() for line in tail_lines if line.strip())
    return (status, code, tail)


def write_report(output_dir: Path, report: dict) -> None:
    """Keep the previous complete JSON while Windows briefly holds a reader."""
    temporary = output_dir / "report.json.tmp"
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(8):
        try:
            temporary.replace(output_dir / "report.json")
            return
        except PermissionError:
            if attempt == 7:
                # Retain both the previous report and the new temporary file
                # for diagnosis; persistent permission errors still fail.
                raise
            time.sleep(.05 * (attempt + 1))


def main() -> int:
    parser = argparse.ArgumentParser(description="통합 회귀 러너")
    parser.add_argument("--list", action="store_true", help="대상 스크립트만 나열")
    parser.add_argument("--only", nargs="+", help="스크립트 파일명으로 선택 실행")
    parser.add_argument("--output-dir", type=Path, help="JSON 결과와 전체 stdout/stderr 보관 경로")
    args = parser.parse_args()

    py_targets = discover_py()
    node_targets = sorted(SCRIPTS.glob("verify_*.js"))
    has_node = shutil.which("node") is not None
    if args.only:
        unknown = set(args.only) - {p.name for p in py_targets + node_targets}
        if unknown:
            parser.error("알 수 없는 검증: " + ", ".join(sorted(unknown)))
        py_targets = [p for p in py_targets if p.name in args.only]
        node_targets = [p for p in node_targets if p.name in args.only]

    if args.list:
        for path in py_targets:
            print(f"  py   {path.name}" + (f" (수동: {MANUAL_INPUTS[path.name]})" if path.name in MANUAL_INPUTS else ""))
        for node_target in node_targets:
            print(f"  node {node_target.name} ({'node 있음' if has_node else 'node 없음→SKIP'})")
        return 0

    results: list[tuple[str, str, int, str]] = []
    output_dir = args.output_dir or ROOT / "data" / "verification" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    started_at = datetime.now(timezone.utc).isoformat()

    def record(path, status, code, tail, started):
        results.append((path.name, status, code, tail))
        records.append({"name": path.name, "status": status, "exit_code": code,
                        "seconds": round(time.monotonic() - started, 3), "detail": tail,
                        "log": path.name + ".log" if (output_dir / (path.name + ".log")).exists() else None})
        summary = {s: sum(r["status"] == s for r in records) for s in ("PASS", "SKIP", "FAIL")}
        report = {"started_at": started_at, "total_targets": len(py_targets) + len(node_targets),
                  "completed": len(records), "summary": summary, "results": records}
        write_report(output_dir, report)
        print(f"  [{status:4}] {path.name} (exit {code}){('  · ' + tail) if tail else ''}", flush=True)

    for path in py_targets:
        started = time.monotonic()
        if path.name in MANUAL_INPUTS:
            status, code, tail = "SKIP", 2, "수동 검사: " + MANUAL_INPUTS[path.name]
        else:
            command = ([sys.executable, "-m", "pytest", str(path), "-q"]
                       if path.name == "verify_web_prototype.py" else [sys.executable, str(path)])
            status, code, tail = run_subprocess(
                command,
                timeout_sec=TIMEOUT_OVERRIDES_SEC.get(path.name, TIMEOUT_SEC),
                log_path=output_dir / (path.name + ".log"),
            )
        record(path, status, code, tail, started)

    for node_target in node_targets:
        started = time.monotonic()
        if has_node:
            status, code, tail = run_subprocess(["node", str(node_target)], log_path=output_dir / (node_target.name + ".log"))
        else:
            status, code, tail = ("SKIP", 2, "(node 미설치)")
        record(node_target, status, code, tail, started)

    passed = sum(1 for _, s, _, _ in results if s == "PASS")
    skipped = sum(1 for _, s, _, _ in results if s == "SKIP")
    failed = [name for name, s, _, _ in results if s == "FAIL"]
    print(f"\n요약: PASS {passed} · SKIP {skipped} · FAIL {len(failed)}")
    print(f"결과: {output_dir / 'report.json'}")
    if failed:
        print("FAIL: " + ", ".join(failed))
        return 1
    print("실행 검사 통과 (SKIP 항목은 미검증)" if skipped else "ALL GREEN (통합 회귀 게이트 통과)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
