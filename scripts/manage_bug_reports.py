"""Local-only triage: python scripts/manage_bug_reports.py list|show|update."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.web_store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--status", choices=["submitted", "investigating", "resolved"])
    listing.add_argument("--limit", type=int, default=50)
    show = sub.add_parser("show")
    show.add_argument("id")
    update = sub.add_parser("update")
    update.add_argument("id")
    update.add_argument(
        "--status", choices=["submitted", "investigating", "resolved"], required=True
    )
    update.add_argument(
        "--reply", required=True, help="신고자에게 표시할 답변 (최대 4000자)"
    )
    args = parser.parse_args()
    store = Store()
    if args.command == "update":
        try:
            if not store.update_report(args.id, args.status, args.reply):
                parser.error("신고를 찾을 수 없습니다.")
        except ValueError as exc:
            parser.error(str(exc))
        print("처리 상태와 답변을 저장했습니다.")
        return
    with store.connect() as db:
        if args.command == "show":
            row = db.execute(
                "SELECT * FROM bug_reports WHERE id=?", (args.id,)
            ).fetchone()
            if not row:
                parser.error("신고를 찾을 수 없습니다.")
            result = store.public_report(dict(row))
        else:
            clause = " WHERE status=?" if args.status else ""
            params = ([args.status] if args.status else []) + [
                max(1, min(args.limit, 500))
            ]
            result = [
                dict(row)
                for row in db.execute(
                    "SELECT id,title,category,status,created FROM bug_reports"
                    + clause
                    + " ORDER BY created DESC LIMIT ?",
                    params,
                )
            ]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
