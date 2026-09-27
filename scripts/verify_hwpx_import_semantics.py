# -*- coding: utf-8 -*-
"""HWPX 가져오기 의미 검증: 글 조각·대체 표현·누름틀·미주 정답·표 격자·구역 순서.

kordoc(MIT) HWPX 파서 검토에서 옮긴 규칙을 합성 HWPX로 고정한다.
- hp:t 안 tab/lineBreak/빈칸 뒤 글(tail)을 잃지 않는다.
- hp:switch 는 hp:case 한 갈래만 읽는다(같은 글이 두 번 나오지 않음).
- 숨은 설명(hiddenComment)과 입력 전 누름틀 안내문은 본문이 아니다.
- "문3） ④"형 미주(번호는 autoNum, 첫 글이 정답)를 정답·풀이로 나눈다.
- 병합 셀은 격자 자리에 두고, 중첩 표는 바깥 표와 따로 중복되지 않는다.
- section10 이 section2 보다 앞에 오지 않는다.

종료코드 0=통과, 1=실패.
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

from app import importers, storage  # noqa: E402

storage.init_db()

NS = (
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
)
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}{('  · ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def para(inner: str) -> str:
    return f'<hp:p id="0" paraPrIDRef="0"><hp:run charPrIDRef="0">{inner}</hp:run></hp:p>'


def text(value: str) -> str:
    return f"<hp:t>{value}</hp:t>"


def section(body: str) -> bytes:
    return f'<?xml version="1.0" encoding="UTF-8"?><hs:sec {NS}>{body}</hs:sec>'.encode("utf-8")


def make_hwpx(sections: dict[str, bytes], spine: list[str] | None = None) -> bytes:
    items = "".join(
        f'<opf:item id="{Path(name).stem}" href="{name}" media-type="application/xml"/>' for name in sections
    )
    refs = "".join(f'<opf:itemref idref="{Path(name).stem}"/>' for name in (spine or []))
    hpf = (
        '<?xml version="1.0" encoding="UTF-8"?><opf:package xmlns:opf="http://www.idpf.org/2007/opf/">'
        f"<opf:manifest>{items}</opf:manifest><opf:spine>{refs}</opf:spine></opf:package>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("Contents/content.hpf", hpf)
        for name, payload in sections.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def endnote(number: int, answer_text: str, explanation: str) -> str:
    auto_num = (
        f'<hp:ctrl><hp:autoNum num="{number}" numType="ENDNOTE">'
        '<hp:autoNumFormat type="DIGIT" userChar="" prefixChar="문" suffixChar="）" supscript="0"/>'
        "</hp:autoNum></hp:ctrl>"
    )
    return (
        f'<hp:ctrl><hp:endNote number="{number}" prefixChar="47928" suffixChar="65289" instId="7">'
        f"<hp:subList>{para(auto_num + text(answer_text))}{para(text(explanation))}</hp:subList>"
        "</hp:endNote></hp:ctrl>"
    )


def imported(name: str, payload: bytes) -> list[dict]:
    result = importers.import_hwpx(name, payload, {})
    ids = result.get("ordered_ids") or [problem["id"] for problem in result.get("created", [])]
    return [storage.get_problem(problem_id) for problem_id in ids]


def _distribution_hwp_notice() -> bool:
    import struct

    import olefile

    class _Stream:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def read(self) -> bytes:
            return self.payload

    class _DistributionOle:
        def __init__(self, *_args: object) -> None:
            header = bytearray(256)
            header[:17] = b"HWP Document File"
            struct.pack_into("<I", header, 36, 0x1 | 0x4)
            self.streams = {"FileHeader": bytes(header), "PrvText": "1. 첫 문항\n".encode("utf-16-le")}

        def __enter__(self) -> "_DistributionOle":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def exists(self, name: str) -> bool:
            return name in self.streams

        def openstream(self, name: str) -> _Stream:
            return _Stream(self.streams[name])

        def listdir(self) -> list[list[str]]:
            return [["FileHeader"], ["PrvText"], ["ViewText", "Section0"]]

    saved = (importers._import_hwp_via_ir, importers.rhwp, olefile.OleFileIO)
    importers._import_hwp_via_ir = lambda *_args, **_kwargs: None
    importers.rhwp = None
    olefile.OleFileIO = _DistributionOle
    try:
        result = importers.import_hwp("distribution.hwp", b"hwp", {})
    finally:
        importers._import_hwp_via_ir, importers.rhwp, olefile.OleFileIO = saved
    return any("배포용" in notice for notice in result.get("notices", []))


def main() -> int:
    # 1. hp:t tail text, hp:switch single branch, hidden comment, click-here guide.
    caption = text("[그림 5] 그래프")
    switch = (
        "<hp:switch><hp:case><hp:chart>" + caption + "</hp:chart></hp:case>"
        "<hp:default><hp:ole>" + caption + "</hp:ole></hp:default></hp:switch>"
    )
    hidden = "<hp:ctrl><hp:hiddenComment><hp:subList>" + para(text("출제자 메모")) + "</hp:subList></hp:hiddenComment></hp:ctrl>"
    guide = (
        '<hp:ctrl><hp:fieldBegin id="11" type="CLICK_HERE" dirty="0"><hp:parameters cnt="1">'
        '<hp:stringParam name="Direction">이름을 입력하세요</hp:stringParam></hp:parameters></hp:fieldBegin></hp:ctrl>'
        + text("이름을 입력하세요")
        + '<hp:ctrl><hp:fieldEnd beginIDRef="11"/></hp:ctrl>'
    )
    filled = (
        '<hp:ctrl><hp:fieldBegin id="12" type="CLICK_HERE" dirty="1"><hp:parameters cnt="1">'
        '<hp:stringParam name="Direction">학교</hp:stringParam></hp:parameters></hp:fieldBegin></hp:ctrl>'
        + text("한빛고")
        + '<hp:ctrl><hp:fieldEnd beginIDRef="12"/></hp:ctrl>'
    )
    body = para(
        "<hp:t>1. 다음 값은?<hp:tab/>단위 cm<hp:lineBreak/>둘째 줄<hp:nbSpace/>끝</hp:t>"
        + switch + hidden + guide + filled
    )
    problems = imported("inline.hwpx", make_hwpx({"Contents/section0.xml": section(body)}))
    stem = "\n".join(problem["stem"] for problem in problems)
    check("tab 뒤 글 보존", "단위 cm" in stem, repr(stem))
    check("lineBreak·nbSpace 뒤 글 보존", "둘째 줄 끝" in stem, repr(stem))
    check("hp:switch 캡션 한 번", stem.count("[그림 5] 그래프") == 1, repr(stem))
    check("숨은 설명 제외", "출제자 메모" not in stem)
    check("입력 전 누름틀 안내문 제외", "이름을 입력하세요" not in stem)
    check("입력한 누름틀 값 유지", "한빛고" in stem)

    # 2. 문N） endnotes: answer is the first text after the autoNum mark.
    body = "".join(
        para(endnote(number, answer, f"풀이 {number}") + text(f"문항 {number}의 값은?"))
        + para(text("① 1 ② 2 ③ 3 ④ 4 ⑤ 5"))
        for number, answer in ((1, " ④"), (2, " ②"), (3, " 12"))
    )
    problems = imported("endnote.hwpx", make_hwpx({"Contents/section0.xml": section(body)}))
    check("문N） 미주 3개 → 3문항", len(problems) == 3, str(len(problems)))
    check(
        "문N） 미주 정답",
        [problem["answer"] for problem in problems] == ["④", "②", "12"],
        str([problem["answer"] for problem in problems]),
    )
    check(
        "문N） 미주 풀이",
        [problem["explanation"] for problem in problems] == ["풀이 1", "풀이 2", "풀이 3"],
        str([problem["explanation"] for problem in problems]),
    )
    check("미주 글이 본문에 새지 않음", all("풀이" not in problem["stem"] for problem in problems))

    # 3. Merged cells land on the grid; nested tables are not duplicated.
    def cell(inner: str, col: int, row: int, col_span: int = 1, row_span: int = 1) -> str:
        return (
            f"<hp:tc><hp:subList>{inner}</hp:subList><hp:cellAddr colAddr=\"{col}\" rowAddr=\"{row}\"/>"
            f"<hp:cellSpan colSpan=\"{col_span}\" rowSpan=\"{row_span}\"/></hp:tc>"
        )

    nested = (
        '<hp:tbl rowCnt="1" colCnt="1"><hp:tr>' + cell(para(text("안쪽")), 0, 0) + "</hp:tr></hp:tbl>"
    )
    table = (
        '<hp:tbl rowCnt="2" colCnt="3"><hp:tr>'
        + cell(para(text("머리")), 0, 0, col_span=2)
        + cell(para(text("우")), 2, 0, row_span=2)
        + "</hp:tr><hp:tr>"
        + cell(para(text("가")), 0, 1)
        + cell(para(nested), 1, 1)
        + "</hp:tr></hp:tbl>"
    )
    body = para(text("1. 표를 보고 답하시오.")) + para(table)
    problems = imported("table.hwpx", make_hwpx({"Contents/section0.xml": section(body)}))
    tables = [grid for problem in problems for grid in (problem.get("tables") or [])]
    check("표 1개(중첩 표 중복 없음)", len(tables) == 1, str(tables))
    if tables:
        check(
            "병합 셀 격자",
            tables[0] == [["머리", "", "우"], ["가", "안쪽", ""]],
            str(tables[0]),
        )

    # 4. Section order follows the spine, and numeric order without one.
    sections = {
        f"Contents/section{index}.xml": section(para(text(f"{index + 1}. 구역 {index} 문항")))
        for index in (0, 1, 2, 10)
    }
    payload = make_hwpx(sections, spine=[f"Contents/section{index}.xml" for index in (0, 1, 2, 10)])
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        ordered = importers._hwpx_section_order(archive, archive.namelist())
    check(
        "구역 순서(spine)",
        ordered == [f"Contents/section{index}.xml" for index in (0, 1, 2, 10)],
        str(ordered),
    )
    payload = make_hwpx(sections, spine=[])
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        ordered = importers._hwpx_section_order(archive, archive.namelist())
    check(
        "구역 순서(숫자)",
        ordered == [f"Contents/section{index}.xml" for index in (0, 1, 2, 10)],
        str(ordered),
    )

    # 5. Distribution-only HWP (flag 0x4): the fallback path explains why only
    #    the preview text came through instead of silently truncating.
    check("배포용 HWP 안내", _distribution_hwp_notice())

    if failures:
        print("FAIL: " + ", ".join(failures))
        return 1
    print("HWPX_IMPORT_SEMANTICS_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
