"""앱 자체 업데이트(git 기반).

로컬 앱은 git clone 상태로 배포되므로, 업데이트는 원격 추적 브랜치를 fetch한 뒤
fast-forward만 허용해서 pull 한다. 사용자의 로컬 수정이 있거나 갈라진 이력이면
덮어쓰지 않고 이유를 돌려준다.

새 파이썬 코드는 서버를 다시 띄워야 반영된다. run_local.ps1로 실행한 경우
(HWP_MAKE_SUPERVISED=1) 종료 코드 RESTART_EXIT_CODE로 끝내면 스크립트가
의존성 변경을 확인하고 서버를 다시 실행한다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException

from . import storage


RESTART_EXIT_CODE = 3
GIT_TIMEOUT_SECONDS = 30
MAX_INCOMING_COMMITS = 20

router = APIRouter(prefix="/api/update", tags=["update"])
_UPDATE_LOCK = threading.Lock()


class GitError(RuntimeError):
    pass


def _git_executable() -> str | None:
    return shutil.which("git")


def _git(*args: str, timeout: int = GIT_TIMEOUT_SECONDS) -> str:
    exe = _git_executable()
    if not exe:
        raise GitError("git이 설치되어 있지 않습니다.")
    env = dict(os.environ)
    # 비공개 저장소 등에서 자격 증명 프롬프트로 서버가 멈추지 않게 한다.
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_ASKPASS", "echo")
    try:
        completed = subprocess.run(
            [exe, *args],
            cwd=storage.PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]} 시간이 초과되었습니다.") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        raise GitError(detail[-1] if detail else f"git {args[0]} 실패 (코드 {completed.returncode})")
    return completed.stdout.strip()


def _is_git_repo() -> bool:
    if not _git_executable():
        return False
    try:
        return _git("rev-parse", "--is-inside-work-tree") == "true"
    except GitError:
        return False


def _upstream() -> str | None:
    try:
        return _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}") or None
    except GitError:
        return None


def _commit_info(ref: str) -> dict[str, str]:
    raw = _git("log", "-1", "--format=%h%x1f%s%x1f%cI", ref)
    short, subject, date = (raw.split("\x1f") + ["", "", ""])[:3]
    return {"sha": short, "subject": subject, "date": date}


def _dirty_files() -> list[str]:
    raw = _git("status", "--porcelain", "--untracked-files=no")
    return [line[3:] for line in raw.splitlines() if line.strip()]


def supervised() -> bool:
    return os.environ.get("HWP_MAKE_SUPERVISED") == "1"


def update_status(fetch: bool = True) -> dict[str, Any]:
    base: dict[str, Any] = {
        "available": False,
        "can_update": False,
        "restart_supported": supervised(),
        "reason": "",
    }
    if not _git_executable():
        return {**base, "reason": "git이 설치되어 있지 않아 자동 업데이트를 쓸 수 없습니다."}
    if not _is_git_repo():
        return {**base, "reason": "git으로 받은 폴더가 아니어서 자동 업데이트를 쓸 수 없습니다."}

    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    status: dict[str, Any] = {
        **base,
        "available": True,
        "branch": branch,
        "current": _commit_info("HEAD"),
        "upstream": None,
        "behind": 0,
        "ahead": 0,
        "dirty_files": [],
        "incoming": [],
        "fetched": False,
        "fetch_error": None,
    }
    if branch == "HEAD":
        status["reason"] = "특정 커밋에 고정된 상태(detached HEAD)라 업데이트할 수 없습니다."
        return status
    upstream = _upstream()
    if not upstream:
        status["reason"] = f"'{branch}' 브랜치에 연결된 원격 브랜치가 없습니다."
        return status
    status["upstream"] = upstream

    if fetch:
        remote = upstream.split("/", 1)[0]
        try:
            _git("fetch", "--quiet", remote, timeout=GIT_TIMEOUT_SECONDS * 2)
            status["fetched"] = True
        except GitError as exc:
            status["fetch_error"] = str(exc)

    counts = _git("rev-list", "--left-right", "--count", f"HEAD...{upstream}").split()
    ahead, behind = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (0, 0)
    status["ahead"] = ahead
    status["behind"] = behind
    status["dirty_files"] = _dirty_files()[:20]
    if behind:
        status["latest"] = _commit_info(upstream)
        log = _git("log", f"--max-count={MAX_INCOMING_COMMITS}", "--format=%h%x1f%s%x1f%cI", f"HEAD..{upstream}")
        status["incoming"] = [
            dict(zip(("sha", "subject", "date"), line.split("\x1f"))) for line in log.splitlines() if line
        ]

    if status["fetch_error"]:
        status["reason"] = f"원격 저장소를 확인하지 못했습니다: {status['fetch_error']}"
    elif not behind:
        status["reason"] = "이미 최신 버전입니다."
    elif ahead:
        status["reason"] = "로컬 커밋이 원격과 갈라져 있어 자동 업데이트를 할 수 없습니다."
    elif status["dirty_files"]:
        status["reason"] = "수정된 앱 파일이 있어 자동 업데이트를 할 수 없습니다."
    else:
        status["can_update"] = True
        status["reason"] = f"새 업데이트 {behind}건이 있습니다."
    return status


def apply_update() -> dict[str, Any]:
    if not _UPDATE_LOCK.acquire(blocking=False):
        raise GitError("이미 업데이트가 진행 중입니다.")
    try:
        status = update_status(fetch=True)
        if not status["can_update"]:
            raise GitError(status["reason"] or "업데이트할 수 없습니다.")
        before = _git("rev-parse", "HEAD")
        _git("merge", "--ff-only", status["upstream"], timeout=GIT_TIMEOUT_SECONDS * 2)
        after = _git("rev-parse", "HEAD")
        changed = _git("diff", "--name-only", before, after).splitlines()
        return {
            "updated": before != after,
            "from": before[:7],
            "to": after[:7],
            "current": _commit_info("HEAD"),
            "changed_files": len(changed),
            "requirements_changed": "requirements.txt" in changed,
            "restart_required": any(path.endswith(".py") or path == "requirements.txt" for path in changed),
            "restart_supported": supervised(),
        }
    finally:
        _UPDATE_LOCK.release()


def _exit_for_restart() -> None:
    time.sleep(0.6)
    os._exit(RESTART_EXIT_CODE)


@router.get("/status")
def get_update_status(fetch: bool = True) -> dict[str, Any]:
    try:
        return update_status(fetch=fetch)
    except GitError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/apply")
def post_update_apply() -> dict[str, Any]:
    try:
        return apply_update()
    except GitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/restart")
def post_update_restart() -> dict[str, Any]:
    if not supervised():
        raise HTTPException(status_code=409, detail="run_local.ps1로 실행한 경우에만 자동 재시작할 수 있습니다.")
    threading.Thread(target=_exit_for_restart, daemon=True).start()
    return {"ok": True}
