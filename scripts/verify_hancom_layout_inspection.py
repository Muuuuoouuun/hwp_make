# -*- coding: utf-8 -*-
"""Hancom lineseg 조판 판독(app/hwpx_lineseg_layout.py) 규칙 검증.

합성한 한컴 저장본 모양의 2단 구역으로 쪽 경계·단 이동·명시 쪽나눔·
분할 표·표 꼬리 억제·앱 생성본의 자리표시 lineseg 판정을 고정한다.
종료코드 0=통과, 1=실패.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.hwpx_lineseg_layout import summarize  # noqa: E402

NS = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}{('  · ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def seg(vertical: int, horizontal: int = 0) -> str:
    return f'<hp:lineseg textpos="0" vertpos="{vertical}" horzpos="{horizontal}" vertsize="1000" horzsize="20000"/>'


def para(text: str, segs: list[tuple[int, int]], extra: str = "", page_break: bool = False) -> str:
    lines = "".join(seg(v, h) for v, h in segs)
    attribute = ' pageBreak="1"' if page_break else ""
    return (
        f'<hp:p id="0"{attribute}><hp:run charPrIDRef="0">{extra}<hp:t>{text}</hp:t></hp:run>'
        f"<hp:linesegarray>{lines}</hp:linesegarray></hp:p>"
    )


def split_table() -> str:
    cell = (
        '<hp:tc><hp:subList><hp:p id="0"><hp:run charPrIDRef="0"><hp:t>셀</hp:t></hp:run>'
        f"<hp:linesegarray>{seg(0)}{seg(40000)}{seg(0)}</hp:linesegarray></hp:p></hp:subList>"
        '<hp:cellAddr colAddr="0" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/></hp:tc>'
    )
    return f'<hp:tbl rowCnt="1" colCnt="1"><hp:tr>{cell}</hp:tr></hp:tbl>'


def hwpx(body: str, columns: int = 2) -> Path:
    col_pr = f'<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="{columns}" sameSz="1" sameGap="1134"/></hp:ctrl>'
    xml = f'<?xml version="1.0" encoding="UTF-8"?><hs:sec {NS}>{body.replace("<hp:t>머리</hp:t>", col_pr + "<hp:t>머리</hp:t>", 1)}</hs:sec>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", xml)
    path = ROOT / "data" / "verify_tmp_layout.hwpx"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.getvalue())
    return path


def main() -> int:
    body = "".join(
        [
            para("머리", [(0, 0)]),
            para("1. 첫 문항", [(3000, 0), (4000, 0)]),
            para("2. 둘째 문항", [(60000, 0)]),
            # vertpos returns up while horzpos moves right: column 2, same page.
            para("3. 셋째 문항", [(1000, 22000), (2000, 22000)]),
            # vertpos returns up and horzpos returns left: page 2, column 1.
            para("4. 넷째 문항", [(1000, 0)]),
            para("5. 다섯째 문항", [(5000, 0)], page_break=True),
            # A table split across pages restarts its cell flow once.
            para("", [(8000, 0)], extra=split_table()),
            # Table tail occupies the top; mid-page resume is not a new page.
            para("6. 여섯째 문항", [(3000, 0)]),
            para("7. 일곱째 문항", [(1000, 22000)]),
        ]
    )
    summary = summarize(hwpx(body))
    questions = summary["questions"]
    check("usable", summary["usable"] and not summary["placeholder_linesegs"], str(summary["sections"]))
    check("q1 page1 col1", questions.get("1") == {"page": 1, "column": 1}, str(questions.get("1")))
    check("q3 column move", questions.get("3") == {"page": 1, "column": 2}, str(questions.get("3")))
    check("q4 page return", questions.get("4") == {"page": 2, "column": 1}, str(questions.get("4")))
    check("q5 explicit pageBreak", questions.get("5") == {"page": 3, "column": 1}, str(questions.get("5")))
    check("q6 split table + tail suppression", questions.get("6") == {"page": 4, "column": 1}, str(questions.get("6")))
    check("q7 column 2 after table", questions.get("7") == {"page": 4, "column": 2}, str(questions.get("7")))
    check("page count", summary["pages"] == 4, str(summary["pages"]))

    placeholder = "".join(para(f"{index}. 문항", [(0, 0)]) for index in range(1, 6))
    summary = summarize(hwpx("".join([para("머리", [(0, 0)]), placeholder])))
    check(
        "app placeholder linesegs are not a layout",
        not summary["usable"] and summary["placeholder_linesegs"] and summary["pages"] is None and not summary["questions"],
        str(summary["pages"]),
    )

    (ROOT / "data" / "verify_tmp_layout.hwpx").unlink(missing_ok=True)
    if failures:
        print("FAIL: " + ", ".join(failures))
        return 1
    print("HANCOM_LAYOUT_INSPECTION_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
