"""Run a separate web prototype on localhost; no shared/default credentials."""

from __future__ import annotations

import argparse
import getpass
import os
import threading
import webbrowser


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--create-user", action="store_true", help="로컬에서 추가 계정 생성"
    )
    args = parser.parse_args()
    os.environ.setdefault("HWP_WEB_ORIGIN", f"http://127.0.0.1:{args.port}")
    from app.web_store import Store

    store = Store()
    if args.create_user:
        email = input("이메일: ").strip().lower()
        name = input("표시 이름: ").strip()
        password = getpass.getpass("비밀번호 (10~128자): ")
        if "@" not in email or not name or not 10 <= len(password) <= 128:
            parser.error("이메일, 이름, 비밀번호 길이를 확인하세요.")
        store.create_user(email, name, password)
        print("계정을 만들었습니다.")
        return
    token = store.bootstrap()
    url = f"http://127.0.0.1:{args.port}/" + (f"#setup={token}" if token else "")
    print(f"HWP Make 웹 프로토타입: {url}", flush=True)
    print("별도 데이터: " + str(store.root), flush=True)
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    import uvicorn

    uvicorn.run("app.web_main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
