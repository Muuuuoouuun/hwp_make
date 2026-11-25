# -*- coding: utf-8 -*-
"""DOCX 가져오기 의미 검증: 글 조각·숨김 글자·글상자·자동 번호·병합 셀.

Filee(MIT) DocxReader 비교에서 확인한 결함을 합성 DOCX로 고정한다.
- 탭·줄바꿈, 하이퍼링크·콘텐츠 컨트롤 안의 글자를 잃지 않는다.
- 숨김 글자(vanish)와 삭제 표시 글자는 넣지 않는다.
- mc:AlternateContent 글상자는 한 갈래만 읽어 두 번 들어가지 않는다.
- Word 자동 번호(numPr)로 매긴 문항 번호와 ①~⑤를 복원해 문항을 나눈다.
- 병합 셀은 왼쪽 위 칸에만 글을 두고 layout.table_spans 로 저장해 HWPX·DOCX 내보내기의 병합으로 잇는다.
- HWPX 가져오기의 병합 셀도 같은 layout.table_spans 를 남긴다.
종료코드 0=통과, 1=실패.
"""
from __future__ import annotations

import io
import os
import re
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

from docx import Document  # noqa: E402
from docx.oxml import parse_xml  # noqa: E402

from app import docx_writer, hwpx_writer_v2, importers, storage  # noqa: E402

storage.init_db()
failures: list[str] = []
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
NS = (
    W
    + ' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
    + ' xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"'
    + ' xmlns:v="urn:schemas-microsoft-com:vml"'
    + ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)
NUMBERING = f"""<w:numbering {W}>
<w:abstractNum w:abstractNumId="0">
 <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
 <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimalEnclosedCircle"/><w:lvlText w:val="%2"/></w:lvl>
</w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
<w:num w:numId="2"><w:abstractNumId w:val="0"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="7"/></w:lvlOverride></w:num>
</w:numbering>"""


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}{('  · ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def run(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def numbered(level: int, inner: str, num_id: int = 1) -> str:
    return f'<w:p {NS}><w:pPr><w:numPr><w:ilvl w:val="{level}"/><w:numId w:val="{num_id}"/></w:numPr></w:pPr>{inner}</w:p>'


def cell(text: str, props: str = "") -> str:
    return f"<w:tc><w:tcPr>{props}</w:tcPr><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>"


def sample() -> bytes:
    document = Document()
    end = document.element.body[-1]

    def add(xml: str) -> None:
        end.addprevious(parse_xml(xml))

    textbox = (
        "<w:r><mc:AlternateContent><mc:Choice Requires=\"wps\"><w:drawing><wps:txbx><w:txbxContent>"
        "<w:p><w:r><w:t>보기상자</w:t></w:r></w:p></w:txbxContent></wps:txbx></w:drawing></mc:Choice>"
        "<mc:Fallback><w:pict><v:shape><v:textbox><w:txbxContent><w:p><w:r><w:t>보기상자</w:t></w:r></w:p>"
        "</w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback></mc:AlternateContent></w:r>"
    )
    add(numbered(0, run("다음 값은?")
        + "<w:r><w:tab/><w:t>단위 cm</w:t><w:br/><w:t>둘째 줄</w:t></w:r>"
        + '<w:hyperlink r:id="rIdX"><w:r><w:t> 링크글</w:t></w:r></w:hyperlink>'
        + "<w:sdt><w:sdtContent><w:r><w:t> 컨트롤글</w:t></w:r></w:sdtContent></w:sdt>"
        + "<w:r><w:rPr><w:vanish/></w:rPr><w:t>[숨긴 정답 ③]</w:t></w:r>"
        + textbox
        + "<w:del><w:r><w:delText>지운글</w:delText></w:r></w:del>"))
    for index in range(1, 6):
        add(numbered(1, run(f"선지{index}")))
    add(numbered(0, run("둘째 문항의 값은?")))
    for index in range(1, 6):
        add(numbered(1, run(f"답{index}")))
    add(
        f'<w:tbl {W}><w:tblGrid><w:gridCol w:w="2000"/><w:gridCol w:w="2000"/><w:gridCol w:w="2000"/></w:tblGrid>'
        "<w:tr>" + cell("머리", '<w:gridSpan w:val="2"/>') + cell("우") + "</w:tr>"
        "<w:tr>" + cell("가", '<w:vMerge w:val="restart"/>') + cell("나") + cell("다") + "</w:tr>"
        "<w:tr>" + cell("", "<w:vMerge/>") + cell("라") + cell("마") + "</w:tr></w:tbl>"
    )
    add(numbered(0, run("일곱째부터 시작하는 문항"), num_id=2))
    add(
        f'<w:p {NS}><w:r><w:object><v:shape id="eq1"/>'
        '<o:OLEObject xmlns:o="urn:schemas-microsoft-com:office:office" Type="Embed" ProgID="Equation.DSMT4" ShapeID="eq1"/>'
        "</w:object></w:r></w:p>"
    )
    document.part.numbering_part._element = parse_xml(NUMBERING)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def main() -> int:
    result = importers.import_docx("sample.docx", sample(), {})
    check("MathType 수식 누락 안내", any("MathType" in notice and "1개" in notice for notice in result.get("notices", [])), str(result.get("notices")))
    problems = [storage.get_problem(problem_id) for problem_id in result.get("ordered_ids", [])]
    first = problems[0] if problems else {"stem": "", "choices": []}
    check("자동 번호로 3문항", [p["number"] for p in problems] == ["1", "2", "7"], str([p["number"] for p in problems]))
    check("탭·줄바꿈 보존", "다음 값은?\t단위 cm\n둘째 줄" in first["stem"], repr(first["stem"]))
    check("하이퍼링크·콘텐츠 컨트롤 글자", "링크글" in first["stem"] and "컨트롤글" in first["stem"], repr(first["stem"]))
    check("숨김 글자 제외", "숨긴 정답" not in first["stem"])
    check("삭제 글자 제외", "지운글" not in first["stem"])
    check("글상자 한 번", first["stem"].count("보기상자") == 1, repr(first["stem"]))
    check("자동 번호 선지 ①~⑤", first["choices"] == [f"선지{i}" for i in range(1, 6)], str(first["choices"]))

    second = problems[1] if len(problems) > 1 else {"tables": [], "layout": None}
    tables = second.get("tables") or []
    spans = ((second.get("layout") or {}).get("table_spans")) or []
    check("병합 셀 글은 왼쪽 위 칸에만", tables == [[["머리", "", "우"], ["가", "나", "다"], ["", "라", "마"]]], str(tables))
    check("병합 정보 저장", spans == [[[0, 0, 1, 2], [1, 0, 2, 1]]], str(spans))

    hwpx_path = Path(_TMP.name) / "merged.hwpx"
    hwpx_writer_v2.write_hwpx(hwpx_path, "병합", [second])
    with zipfile.ZipFile(hwpx_path) as archive:
        section = archive.read("Contents/section0.xml").decode("utf-8")
    check("HWPX 내보내기 colSpan=2", re.search(r'<hp:cellSpan colSpan="2" rowSpan="1"', section) is not None)
    check("HWPX 내보내기 rowSpan=2", re.search(r'<hp:cellSpan colSpan="1" rowSpan="2"', section) is not None)
    docx_path = Path(_TMP.name) / "merged.docx"
    docx_writer.write_docx(docx_path, "병합", [second])
    with zipfile.ZipFile(docx_path) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
    check("DOCX 내보내기 gridSpan·vMerge", 'w:gridSpan w:val="2"' in document_xml and "w:vMerge" in document_xml)

    hwpx_problem = _hwpx_merged_problem()
    check(
        "HWPX 가져오기도 병합 정보 저장",
        ((hwpx_problem.get("layout") or {}).get("table_spans")) == [[[0, 0, 1, 2], [0, 2, 2, 1]]],
        str(hwpx_problem.get("layout")),
    )

    if failures:
        print("FAIL: " + ", ".join(failures))
        return 1
    print("DOCX_IMPORT_SEMANTICS_OK")
    return 0


def _hwpx_merged_problem() -> dict:
    ns = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'

    def para(inner: str) -> str:
        return f'<hp:p id="0" paraPrIDRef="0"><hp:run charPrIDRef="0">{inner}</hp:run></hp:p>'

    def hwpx_cell(text: str, col: int, row: int, col_span: int = 1, row_span: int = 1) -> str:
        return (
            f"<hp:tc><hp:subList>{para(f'<hp:t>{text}</hp:t>')}</hp:subList>"
            f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/><hp:cellSpan colSpan="{col_span}" rowSpan="{row_span}"/></hp:tc>'
        )

    table = (
        '<hp:tbl rowCnt="2" colCnt="3"><hp:tr>' + hwpx_cell("머리", 0, 0, col_span=2) + hwpx_cell("우", 2, 0, row_span=2)
        + "</hp:tr><hp:tr>" + hwpx_cell("가", 0, 1) + hwpx_cell("나", 1, 1) + "</hp:tr></hp:tbl>"
    )
    section = f'<?xml version="1.0" encoding="UTF-8"?><hs:sec {ns}>{para("<hp:t>1. 표 문항</hp:t>")}{para(table)}</hs:sec>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", section)
    result = importers.import_hwpx("merged.hwpx", buffer.getvalue(), {})
    ids = result.get("ordered_ids") or []
    return storage.get_problem(ids[0]) if ids else {}


if __name__ == "__main__":
    sys.exit(main())
