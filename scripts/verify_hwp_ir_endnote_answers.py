# -*- coding: utf-8 -*-
"""HWP(rhwp IR) 가져오기의 미주 정답·풀이 연결 검증.

수학 HWP 미주 46개의 정답·풀이가 0/46으로 들어오던 문제(2026-10-03 작업 정리 §4)를
고정한다. rhwp IR은 미주를 furniture.endnotes(번호·내용·표지 문단)로 주므로,
번호 1..N이 빠짐없고 80% 이상 정답이 있을 때만 정답 열쇠로 쓴다.

- 본문에 번호 글자가 없는 "문N）" 미주형: 미주 위치로 문항을 나누고 정답·풀이를 넣는다.
- "[N점][...NN]" 마커형: 마커가 나눈 문항에 같은 번호의 미주를 붙인다.
- 번호가 이어지지 않는 미주는 정답으로 쓰지 않는다.

rhwp 는 형식을 내용으로 판별하므로 합성 HWPX 바이트를 HWP 경로에 넣어 시험한다.
종료코드 0=통과, 1=실패, 2=rhwp 없음(SKIP).
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory()
os.environ["HWP_MAKE_DATA_DIR"] = _TMP.name

from app import importers, importers_hwp_ir, storage  # noqa: E402

storage.init_db()
SKELETON = ROOT / "app" / "_vendor" / "hwpx" / "data" / "Skeleton.hwpx"
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}{('  · ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def para(inner: str) -> str:
    return f'<hp:p id="0" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0">{inner}</hp:run></hp:p>'


def text(value: str) -> str:
    return f"<hp:t>{value}</hp:t>"


def endnote(number: int, answer: str, explanation_xml: str) -> str:
    auto_num = (
        f'<hp:ctrl><hp:autoNum num="{number}" numType="ENDNOTE">'
        '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="문" suffixChar="）" supscript="0"/>'
        "</hp:autoNum></hp:ctrl>"
    )
    return (
        f'<hp:ctrl><hp:endNote number="{number}" instId="7"><hp:subList>'
        f"{para(auto_num + text(answer))}{para(explanation_xml)}</hp:subList></hp:endNote></hp:ctrl>"
    )


def hwpx(body: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(SKELETON) as skeleton, zipfile.ZipFile(buffer, "w") as archive:
        for name in skeleton.namelist():
            data = skeleton.read(name)
            if name == "Contents/section0.xml":
                data = data.decode("utf-8").replace("</hs:sec>", body + "</hs:sec>").encode("utf-8")
            archive.writestr(name, data, compress_type=zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def imported(name: str, payload: bytes) -> tuple[list[dict], list[str]]:
    result = importers._import_hwp_via_ir(name, payload, {}) or {}
    problems = [storage.get_problem(problem_id) for problem_id in result.get("ordered_ids", [])]
    return problems, result.get("notices", [])


def main() -> int:
    if not importers_hwp_ir.available():
        print("SKIP: rhwp is not available")
        return 2
    equation = '</hp:t><hp:equation id="90"><hp:script>{1} over {2}</hp:script></hp:equation><hp:t>'
    choices = para(text("① 1 ② 2 ③ 3 ④ 4 ⑤ 5"))

    # 1. Endnote marks are the only question numbers.
    body = "".join(
        para(endnote(number, answer, text(f"풀이 {number} 값은 {equation} 이다")) + text(f"문항 {number}의 값은?")) + choices
        for number, answer in ((1, " ④"), (2, " ②"), (3, " 12"))
    )
    problems, notices = imported("notes.hwp", hwpx(body))
    check("미주형 3문항", len(problems) == 3, str([p["stem"] for p in problems]))
    check("미주형 번호", [p["number"] for p in problems] == ["1", "2", "3"], str([p["number"] for p in problems]))
    check("미주형 정답", [p["answer"] for p in problems] == ["④", "②", "12"], str([p["answer"] for p in problems]))
    check(
        "미주 풀이 안 수식 보존",
        all(p["explanation"] == f"풀이 {p['number']} 값은 ${{1}} over {{2}}$ 이다" for p in problems),
        str([p["explanation"] for p in problems]),
    )
    check("미주 글이 본문에 없음", all("풀이" not in p["stem"] for p in problems))
    check("선지 분리", all(len(p["choices"]) == 5 for p in problems), str([p["choices"] for p in problems]))
    check("가져오기 안내", any("미주 3개" in notice for notice in notices), str(notices))

    # 2. [N점] markers split questions; endnotes attach by number.
    body = "".join(
        para(endnote(number, answer, text(f"마커 풀이 {number}")) + text(f"마커형 문항 {number} 본문"))
        + para(text(f"[{score}점][2026 모의 {number:02d}]"))
        + choices
        for number, answer, score in ((1, " ③", 2), (2, " ⑤", 3))
    )
    problems, _ = imported("markers.hwp", hwpx(body))
    check("마커형 2문항", len(problems) == 2, str([p["stem"] for p in problems]))
    check("마커형 정답", [p["answer"] for p in problems] == ["③", "⑤"], str([p["answer"] for p in problems]))
    check("마커형 풀이", [p["explanation"] for p in problems] == ["마커 풀이 1", "마커 풀이 2"], str([p["explanation"] for p in problems]))

    # 3. Notes numbered out of sequence are not an answer key.
    body = (
        para(endnote(1, " ①", text("참고 1")) + text("1. 첫 문항의 값은?"))
        + choices
        + para(endnote(5, " ②", text("참고 5")) + text("2. 둘째 문항의 값은?"))
        + choices
    )
    problems, _ = imported("loose.hwp", hwpx(body))
    check("비연속 미주는 정답으로 쓰지 않음", problems and all(not p["answer"] for p in problems), str([(p["number"], p["answer"]) for p in problems]))

    if failures:
        print("FAIL: " + ", ".join(failures))
        return 1
    print("HWP_IR_ENDNOTE_ANSWERS_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
