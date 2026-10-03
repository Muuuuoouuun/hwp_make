# -*- coding: utf-8 -*-
"""Report Hancom's real page/column layout from a Hancom-saved HWPX.

Get the file on Windows with Hancom installed:
  powershell -File scripts/probe_hwp_open.ps1 -Path out.hwpx -ExportHwpxDirectory hancom_saved

Then on any OS:
  python scripts/inspect_hancom_layout.py hancom_saved/out.hancom.hwpx
  python scripts/inspect_hancom_layout.py hancom_saved/out.hancom.hwpx --expect expected.json

``--expect`` takes {"pages": N, "questions": {"1": {"page": 1, "column": 1}, ...}}
(for example the UI's predicted page/column per question) and exits 1 on any
mismatch. Files written by this app still carry placeholder line layout and
are reported as not usable.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.hwpx_lineseg_layout import summarize  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("hwpx", type=Path)
    parser.add_argument("--expect", type=Path, help="expected pages/question positions JSON")
    args = parser.parse_args()

    summary = summarize(args.hwpx)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["usable"]:
        print("NOT USABLE: no Hancom line layout (save the file from Hancom first)", file=sys.stderr)
        return 2
    if not args.expect:
        return 0
    expected = json.loads(args.expect.read_text(encoding="utf-8"))
    mismatches: list[str] = []
    if "pages" in expected and expected["pages"] != summary["pages"]:
        mismatches.append(f"pages expected {expected['pages']} got {summary['pages']}")
    for number, position in (expected.get("questions") or {}).items():
        actual = summary["questions"].get(str(number))
        if actual != position:
            mismatches.append(f"question {number} expected {position} got {actual}")
    for line in mismatches:
        print("MISMATCH " + line)
    print("LAYOUT_MATCH" if not mismatches else f"LAYOUT_MISMATCH {len(mismatches)}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
