"""Ensure tooling errors cannot masquerade as unavailable test fixtures."""
import sys
import tempfile
import json
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_all_verify import run_subprocess, write_report


def main():
    with tempfile.TemporaryDirectory() as folder:
        log = Path(folder) / "case.log"
        status, code, detail = run_subprocess([
            sys.executable, "-c",
            "import argparse; p=argparse.ArgumentParser(); p.add_argument('required'); p.parse_args()",
        ], log_path=log)
        assert (status, code) == ("FAIL", 2)
        assert "required" in detail and "usage:" in log.read_text(encoding="utf-8")
        assert run_subprocess([sys.executable, "-c", "print('SKIP: fixture absent'); exit(2)"])[0] == "SKIP"
        assert run_subprocess([sys.executable, "-c", "raise ValueError('diagnostic pin')"])[2].endswith("ValueError: diagnostic pin")
        result = run_subprocess([sys.executable, "-u", "-c", "import time; print('before timeout'); time.sleep(10)"], timeout_sec=1, log_path=log)
        assert result[:2] == ("FAIL", 124)
        assert "before timeout" in log.read_text(encoding="utf-8")
        assert run_subprocess([str(Path(folder) / "missing-program")])[0] == "FAIL"
        output = Path(folder)
        before, after = {"completed": 1}, {"completed": 2}
        write_report(output, before)
        original = Path.replace
        attempts = []
        def briefly_locked(source, target):
            assert json.loads(target.read_text(encoding="utf-8")) == before
            attempts.append(source)
            if len(attempts) <= 2:
                raise PermissionError("temporary Windows sharing violation")
            return original(source, target)
        with patch.object(Path, "replace", briefly_locked):
            write_report(output, after)
        assert json.loads((output / "report.json").read_text(encoding="utf-8")) == after
        assert not (output / "report.json.tmp").exists()
        with patch.object(Path, "replace", side_effect=PermissionError("persistent denial")) as replace:
            try:
                write_report(output, {"completed": 3})
                raise AssertionError("persistent denial was silently accepted")
            except PermissionError:
                pass
            assert 1 < replace.call_count <= 10, "unbounded permission retry"
        assert json.loads((output / "report.json").read_text(encoding="utf-8")) == after
        assert json.loads((output / "report.json.tmp").read_text(encoding="utf-8")) == {"completed": 3}
    print("REGRESSION_RUNNER_OK: tooling failures, transient report lock recovery, bounded permanent-error failure and preserved evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
