# -*- coding: utf-8 -*-
"""HWP 변환 충실도 검증: rhwp가 잘못 읽는 표기를 미리 고치고 독립 왕복 대조로 증명한다.

2026-10-14 실측(25수능 영어·국어 원본 레이아웃 출력):
- rhwp 0.8.7 HWPX 판독기는 표준 채우기 이름 TOTAL(크기에 맞추어)을 몰라 HWP에
  바둑판(0)으로 쓴다. 영어 편지 상자 틀이 사라지고 그림이 띠처럼 반복됐다.
  같은 뜻의 rhwp 이름 FIT 은 5(크기에 맞추어)로 쓴다. LEFT_*·RIGHT_* 도 모른다.
- run 없는 빈 문단(빈 표 칸)에 rhwp가 글자 모양 0을 지어내 자체 IR 검증이 실패했다.

이 스크립트는 같은 두 구조를 합성 HWPX로 만들어
1) 그대로 바꾸면 독립 왕복 대조가 차이를 잡고(글자 크기 변화도 따로 잡는지 확인),
2) app.rhwp_cli.hwpx_to_hwp 는 임시 사본에서 TOTAL→FIT, 빈 문단 run 을 고쳐 대조를 통과하며
   원본 HWPX 는 건드리지 않고,
3) 같은 렌더러로 그린 HWPX·HWP 쪽 그림이 같고,
4) rhwp가 모르는 채우기(LEFT_TOP)는 HWP를 내주지 않고 지움을 확인한다.
PDF 원본 레이아웃 변환의 output_format=hwp 경로도 합성 PDF로 끝까지 확인한다.
종료코드 0=통과, 1=실패, 2=rhwp CLI 없음(SKIP; scripts/fetch_rhwp_cli.py).
"""
from __future__ import annotations

import base64
import io
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory()
os.environ["HWP_MAKE_DATA_DIR"] = str(Path(_TMP.name) / "data")

from PIL import Image  # noqa: E402

from app import hwp_fidelity, rhwp_cli  # noqa: E402

SKELETON = ROOT / "app" / "_vendor" / "hwpx" / "data" / "Skeleton.hwpx"
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}{('  · ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def framed_cell_document(path: Path, mode: str = "TOTAL") -> None:
    """A 2-cell table: a fitted background picture cell and an empty run-less cell."""
    frame = io.BytesIO()
    image = Image.new("RGB", (200, 60), "white")
    for x in range(200):
        image.putpixel((x, 0), (0, 0, 0))
        image.putpixel((x, 59), (0, 0, 0))
    for y in range(60):
        image.putpixel((0, y), (0, 0, 0))
        image.putpixel((199, y), (0, 0, 0))
    image.save(frame, "PNG")
    with zipfile.ZipFile(SKELETON) as skeleton:
        header = skeleton.read("Contents/header.xml").decode("utf-8")
        section = skeleton.read("Contents/section0.xml").decode("utf-8")
        hpf = skeleton.read("Contents/content.hpf").decode("utf-8")
        count = header.count("<hh:borderFill ")
        fill_id = count + 1
        fill = (
            f'<hh:borderFill id="{fill_id}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
            '<hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
            '<hh:leftBorder type="NONE" width="0.12 mm" color="#000000"/><hh:rightBorder type="NONE" width="0.12 mm" color="#000000"/>'
            '<hh:topBorder type="NONE" width="0.12 mm" color="#000000"/><hh:bottomBorder type="NONE" width="0.12 mm" color="#000000"/>'
            '<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>'
            f'<hc:fillBrush><hc:imgBrush mode="{mode}"><hc:img binaryItemIDRef="frame1" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
            "</hc:imgBrush></hc:fillBrush></hh:borderFill>"
        )
        header = header.replace("</hh:borderFills>", fill + "</hh:borderFills>")
        header = header.replace(f'<hh:borderFills itemCnt="{count}">', f'<hh:borderFills itemCnt="{fill_id}">')

        def cell(col: int, inner: str, border_fill: int) -> str:
            return (
                f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="1" borderFillIDRef="{border_fill}">'
                '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" '
                'linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
                f'<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">{inner}</hp:p></hp:subList>'
                f'<hp:cellAddr colAddr="{col}" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
                '<hp:cellSz width="15000" height="4500"/><hp:cellMargin left="0" right="0" top="0" bottom="0"/></hp:tc>'
            )

        table = (
            '<hp:tbl id="7001" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" '
            'dropcapstyle="None" pageBreak="CELL" repeatHeader="0" rowCnt="1" colCnt="2" cellSpacing="0" borderFillIDRef="1" noAdjust="0">'
            '<hp:sz width="30000" widthRelTo="ABSOLUTE" height="4500" heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" '
            'horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:inMargin left="0" right="0" top="0" bottom="0"/>'
            "<hp:tr>"
            + cell(0, '<hp:run charPrIDRef="0"><hp:t>Dear runners, the race is cancelled.</hp:t></hp:run>', fill_id)
            + cell(1, "", 1)
            + "</hp:tr></hp:tbl>"
        )
        body = (
            '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="0">{table}<hp:t/></hp:run></hp:p>'
        )
        section = section.replace("</hs:sec>", body + "</hs:sec>")
        hpf = hpf.replace(
            "</opf:manifest>",
            '<opf:item id="frame1" href="BinData/frame1.png" media-type="image/png" isEmbeded="1"/></opf:manifest>',
        )
        with zipfile.ZipFile(path, "w") as archive:
            for name in skeleton.namelist():
                data = skeleton.read(name)
                if name == "Contents/header.xml":
                    data = header.encode("utf-8")
                elif name == "Contents/section0.xml":
                    data = section.encode("utf-8")
                elif name == "Contents/content.hpf":
                    data = hpf.encode("utf-8")
                archive.writestr(name, data, compress_type=zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED)
            archive.writestr("BinData/frame1.png", frame.getvalue())


def render_pages(document: Path, folder: Path) -> list[bytes]:
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(rhwp_cli.locate()), "export-png", str(document), "-o", str(folder)],
        capture_output=True, timeout=120, check=False,
    )
    return [png.read_bytes() for png in sorted(folder.glob("*.png"))]


def changed_pixels(a: bytes, b: bytes) -> int:
    first = Image.open(io.BytesIO(a)).convert("L")
    second = Image.open(io.BytesIO(b)).convert("L")
    if first.size != second.size:
        return -1
    return sum(1 for x, y in zip(first.tobytes(), second.tobytes()) if abs(x - y) > 32)


def main() -> int:
    if not rhwp_cli.available():
        print("SKIP: rhwp CLI not found (python scripts/fetch_rhwp_cli.py)")
        return 2

    work = Path(_TMP.name)
    source = work / "framed.hwpx"
    framed_cell_document(source)

    # 1. Plain rhwp output loses the fitted fill; the independent check sees it.
    raw_hwp = work / "raw.hwp"
    subprocess.run([str(rhwp_cli.locate()), "convert", str(source), str(raw_hwp)], capture_output=True, timeout=120, check=False)
    raw_round_trip = work / "raw_round_trip.hwpx"
    rhwp_cli._run_export_hwpx(raw_hwp, raw_round_trip)
    problems = hwp_fidelity.compare_profiles(
        hwp_fidelity.structure_profile(source), hwp_fidelity.structure_profile(raw_round_trip)
    )
    check("보정 없는 rhwp 결과의 채우기 손실을 대조가 잡음", "그림 채우기 방식" in problems, str(problems))

    # A changed character shape (size of charPr 0) is caught by content, not id.
    resized = work / "resized.hwpx"
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(resized, "w") as copy:
        for info in original.infolist():
            data = original.read(info.filename)
            if info.filename == "Contents/header.xml":
                text = data.decode("utf-8")
                start = text.index('<hh:charPr id="0"')
                end = text.index(">", start)
                tag = text[start:end]
                height = tag.split('height="', 1)[1].split('"', 1)[0]
                text = text[:start] + tag.replace(f'height="{height}"', f'height="{int(height) + 200}"', 1) + text[end:]
                data = text.encode("utf-8")
            copy.writestr(info, data)
    problems = hwp_fidelity.compare_profiles(
        hwp_fidelity.structure_profile(source), hwp_fidelity.structure_profile(resized)
    )
    check("글자 크기 변화를 대조가 잡음", problems == ["글자 모양"], str(problems))

    # 2. The app path prepares a copy and passes both checks.
    original = source.read_bytes()
    hwp = work / "framed.hwp"
    report = rhwp_cli.hwpx_to_hwp(source, hwp)
    prepared = report.get("prepared") or {}
    check("채우기 TOTAL→FIT", prepared.get("image_fills") == 1, str(prepared))
    check("빈 문단 run 보정", prepared.get("empty_paragraphs") == 1, str(prepared))
    check("원본 HWPX는 그대로", source.read_bytes() == original)
    round_trip = work / "round_trip.hwpx"
    rhwp_cli._run_export_hwpx(hwp, round_trip)
    with zipfile.ZipFile(round_trip) as archive:
        header = archive.read("Contents/header.xml").decode("utf-8")
    check("HWP 채우기가 크기에 맞추어(FIT)", 'imgBrush mode="FIT"' in header and 'mode="TILE"' not in header)
    check("rhwp 자체 IR 검증", (report.get("verify") or {}).get("identical") is True, str(report.get("verify")))
    check("독립 왕복 대조 일치", report.get("round_trip_check") == "identical")
    check("HWP 5.0 파일", hwp.read_bytes()[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")

    # 3. Same renderer, same pages.
    source_pages = render_pages(source, work / "png_source")
    hwp_pages = render_pages(hwp, work / "png_hwp")
    raw_pages = render_pages(raw_hwp, work / "png_raw")
    check("쪽 수 같음", bool(source_pages) and len(source_pages) == len(hwp_pages), f"{len(source_pages)}/{len(hwp_pages)}")
    if source_pages and hwp_pages:
        check("보정한 HWP 렌더가 HWPX와 같음", changed_pixels(source_pages[0], hwp_pages[0]) == 0)
    if source_pages and raw_pages:
        check("보정 전 HWP 렌더는 달랐음", changed_pixels(source_pages[0], raw_pages[0]) != 0)

    # 4. A fill rhwp cannot write is refused, and no HWP is left behind.
    unsupported = work / "left_top.hwpx"
    framed_cell_document(unsupported, mode="LEFT_TOP")
    refused = work / "left_top.hwp"
    try:
        rhwp_cli.hwpx_to_hwp(unsupported, refused)
        check("rhwp가 모르는 채우기는 거절", False, "변환이 통과함")
    except rhwp_cli.RhwpCliError as exc:
        check("rhwp가 모르는 채우기는 거절", "그림 채우기 방식" in str(exc), str(exc))
    check("거절한 HWP는 남기지 않음", not refused.exists())

    # 5. PDF original-layout export straight to HWP.
    import fitz

    from app import main as app_main

    pdf = work / "letter.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 90), "1. Choose the best title for the passage.")
    page.insert_text((72, 120), "Dear runners, the race is cancelled because of heavy rain.")
    page.insert_text((72, 150), "(1) Rain   (2) Race   (3) Runners   (4) Roads   (5) Rest")
    document.save(pdf)
    document.close()
    result = app_main.export_pdf_layout(
        app_main.PdfLayoutExportPayload(
            filename="letter.pdf",
            data_base64=base64.b64encode(pdf.read_bytes()).decode("ascii"),
            layout_mode="structured",
            native_math=True,
            math_ai_recognition=False,
            output_format="hwp",
        )
    )
    hwp_info = result.get("hwp") or {}
    check("PDF 원본 레이아웃 → HWP", hwp_info.get("ok") is True and result["export"]["name"].endswith(".hwp"), str(hwp_info))
    check("같은 내용의 HWPX 보관", str((result.get("hwpx_export") or {}).get("name", "")).endswith(".hwpx"))
    from app import storage

    history = {item["name"]: item for item in storage.list_exports()}
    for key, label in (("export", "HWP"), ("hwpx_export", "HWPX")):
        item = history.get((result.get(key) or {}).get("name"), {})
        report_ref = ((item.get("conversion") or {}).get("report") or {}).get("name", "")
        check(f"변환 기록의 {label}에 원본·보고서 연결", report_ref.endswith("layout_report.json"), str(item.get("conversion"))[:200])

    if failures:
        print("FAIL: " + ", ".join(failures))
        return 1
    print("HWP_FIDELITY_ROUNDTRIP_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
