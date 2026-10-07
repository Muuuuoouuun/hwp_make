# -*- coding: utf-8 -*-
"""데스크톱 런처 macOS 분기 회귀 핀 (2026-10-07).

macOS 에는 os.startfile 이 없고 Tk 가 .ico 를 거부해 창이 안 떴다. sys.platform 을 darwin 으로
바꿔 열기 명령·데이터 폴더가 macOS 경로로 가는지, 실패가 OSError 로 오는지 확인한다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_desktop  # noqa: E402

calls: list[list[str]] = []
real_platform, real_call = sys.platform, subprocess.call
try:
    sys.platform = "darwin"
    subprocess.call = lambda cmd: calls.append(cmd) or 0
    run_desktop.open_path(Path("/tmp/결과.hwpx"))
    assert calls[-1][0] == "open", calls
    assert run_desktop.default_data_dir().parts[-3:] == ("Library", "Application Support", "HWP Make Basic")
    subprocess.call = lambda cmd: 1
    try:
        run_desktop.open_path(Path("/tmp/x"))
        raise AssertionError("failure must raise OSError")
    except OSError:
        pass
finally:
    sys.platform, subprocess.call = real_platform, real_call
print("DESKTOP_MACOS_PATHS_OK")
