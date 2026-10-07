"""회귀핀: HWP 가져오기 — 공유 지문 1열 상자(문단별 행) + 병합 셀(cellSpan) 방출.

- 2026-10-03 R3a: 지문 본문을 1×1 표 한 칸에 넣어 셀 높이가 쪽을 넘고(rhwp 491쪽) 병합 셀
  (TableCell.row_span/col_span)을 읽지 않아 4×5 보기 표가 20칸으로 풀리던 문제의 회귀 방지.
- 합성 IR 블록(SimpleNamespace)으로 _table_rows 의 span 수집을, 스트림 주입으로 import 경로
  (layout.passage_box / layout.table_spans)를, write_hwpx / write_docx 로 출력 구조를 검사한다.
- 실물 샘플(data/external_exam_qa 의 국어 HWP)이 있으면 cellSpan 97·셀 수 9 를 추가 확인하고,
  없으면 그 부분만 건너뛴다(합성 검사만으로도 exit 0/1 판정).
"""
from __future__ import annotations

import os
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RUNTIME_DIR = tempfile.TemporaryDirectory(prefix="hwpmake_passage_box_", ignore_cleanup_errors=True)
os.environ["HWP_MAKE_DATA_DIR"] = RUNTIME_DIR.name

from app import docx_writer, hwpx_writer_v2, importers, storage  # noqa: E402
from app import importers_hwp_ir as hwp_ir  # noqa: E402

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"

PASSAGE_PARAS = [f"지문 {i}번째 문단입니다. " * 12 for i in range(1, 31)]  # 30문단, 쪽 높이를 넘는 길이
STREAM = [
    ("text", "[1~2] 다음 글을 읽고 물음에 답하시오."),
    *[("text", para) for para in PASSAGE_PARAS],
    ("text", "1. 윗글의 내용과 일치하는 것은?"),
    ("text", "① 하나\t② 둘\t③ 셋\t④ 넷\t⑤ 다섯"),
    ("text", "2. <보기>를 참고하여 윗글을 이해한 내용으로 적절한 것은?"),
    ("table", None),  # _table_rows 결과(TableGrid)로 대체
    ("text", "① 가\t② 나\t③ 다\t④ 라\t⑤ 마"),
]


def _cell(row: int, col: int, row_span: int = 1, col_span: int = 1, text: str = "") -> SimpleNamespace:
    blocks = [SimpleNamespace(kind="paragraph", text=text)] if text else []
    return SimpleNamespace(row=row, col=col, row_span=row_span, col_span=col_span, blocks=blocks)


def synthetic_table_block() -> SimpleNamespace:
    """원본 국어 HWP 의 4×5 보기 표(9셀, 병합 7)와 같은 구조."""
    return SimpleNamespace(
        kind="table", rows=4, cols=5, text="",
        cells=[
            _cell(0, 0, 1, 2), _cell(0, 2, 2, 1, "< 보 기 >"), _cell(0, 3, 1, 2),
            _cell(1, 0, 1, 2), _cell(1, 3, 1, 2),
            _cell(2, 0), _cell(2, 1, 1, 3, "보기 본문입니다. " * 10), _cell(2, 4),
            _cell(3, 0, 1, 5),
        ],
    )


def hwpx_section(path: Path) -> ET.Element:
    with zipfile.ZipFile(path) as zf:
        return ET.fromstring(zf.read("Contents/section0.xml"))


def hwpx_header(path: Path) -> ET.Element:
    with zipfile.ZipFile(path) as zf:
        return ET.fromstring(zf.read("Contents/header.xml"))


def main() -> int:
    failures: list[str] = []
    storage.init_db()

    # 1) _table_rows: 병합 정보 수집
    grid = hwp_ir._table_rows(synthetic_table_block())
    spans = getattr(grid, "spans", None)
    if len(grid) != 4 or any(len(row) != 5 for row in grid):
        failures.append(f"_table_rows grid shape: {len(grid)}x{[len(r) for r in grid]}")
    if sorted(spans or []) != sorted([[0, 0, 1, 2], [0, 2, 2, 1], [0, 3, 1, 2], [1, 0, 1, 2], [1, 3, 1, 2], [2, 1, 1, 3], [3, 0, 1, 5]]):
        failures.append(f"_table_rows spans: {spans}")
    if not grid[2][1].startswith("보기 본문") or grid[0][2] != "< 보 기 >":
        failures.append(f"_table_rows cell text: {grid[0][2]!r} / {grid[2][1][:10]!r}")

    # 2) import 경로: 지문 → 문단별 행 + layout.passage_box, 표 → layout.table_spans
    stream = [("table", grid) if kind == "table" and value is None else (kind, value) for kind, value in STREAM]
    original = hwp_ir._ordered_stream
    hwp_ir._ordered_stream = lambda payload, filename, save_image: list(stream)
    try:
        result = importers._import_hwp_via_ir("fixture_box.hwp", b"fixture", {})
    finally:
        hwp_ir._ordered_stream = original
    if not result:
        print("FAIL: _import_hwp_via_ir returned None")
        return 1
    created = result["created"]
    passages = [p for p in created if p.get("problem_type") == "passage"]
    questions = [p for p in created if p.get("problem_type") != "passage"]
    if len(passages) != 1:
        failures.append(f"expected 1 passage, got {len(passages)}")
    else:
        passage = passages[0]
        tables = passage.get("tables") or []
        if len(tables) != 1 or len(tables[0]) != len(PASSAGE_PARAS) or any(len(row) != 1 for row in tables[0]):
            failures.append(f"passage rows: {[len(t) for t in tables]} (expected {len(PASSAGE_PARAS)}x1)")
        if not (passage.get("layout") or {}).get("passage_box"):
            failures.append(f"passage layout.passage_box missing: {passage.get('layout')}")
        if max((len(cell) for t in tables for row in t for cell in row), default=0) > 400:
            failures.append("passage body still packed into one oversized cell")
        if "".join(cell for t in tables for row in t for cell in row).replace(" ", "") != "".join(PASSAGE_PARAS).replace(" ", ""):
            failures.append("passage text not preserved across rows")
    spanned = [p for p in questions if (p.get("layout") or {}).get("table_spans")]
    if len(spanned) != 1:
        failures.append(f"expected 1 question with layout.table_spans, got {len(spanned)}")
    else:
        stored_spans = spanned[0]["layout"]["table_spans"]
        if stored_spans != [list(map(list, spans))]:
            failures.append(f"stored table_spans mismatch: {stored_spans}")
        if spanned[0].get("tables") != [list(map(list, grid))]:
            failures.append("tables model (2-D strings) changed by span capture")

    # 3) HWPX 출력: 1열 상자(행 사이 선 없음, 쪽 높이 분할) + cellSpan 9셀
    problems = storage.get_problems_by_ids(result["ordered_ids"])
    export_dir = Path(RUNTIME_DIR.name) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    for template_key in ("basic", "simple"):
        out = export_dir / f"box_{template_key}.hwpx"
        hwpx_writer_v2.write_hwpx(out, "지문 상자 테스트", problems, template_key)
        section = hwpx_section(out)
        tables = list(section.iter(f"{HP}tbl"))
        box_tables = [t for t in tables if t.get("colCnt") == "1" and int(t.get("rowCnt", "0")) > 1]
        if not box_tables:
            failures.append(f"{template_key}: passage box tables (1-column, multi-row) missing")
        box_rows = sum(int(t.get("rowCnt")) for t in box_tables)
        if box_rows != len(PASSAGE_PARAS):
            failures.append(f"{template_key}: passage rows emitted {box_rows}, expected {len(PASSAGE_PARAS)}")
        if len(box_tables) < 2:
            failures.append(f"{template_key}: long passage was not split by page height ({len(box_tables)} table)")
        max_cell_h = max(int(c.find(f"{HP}cellSz").get("height", "0")) for t in tables for c in t.iter(f"{HP}tc"))
        if max_cell_h > 60000:
            failures.append(f"{template_key}: a cell is taller than the page body ({max_cell_h})")
        fills = {f.get("id"): f for f in hwpx_header(out).iter(f"{HH}borderFill")}
        for t in box_tables:
            rows = t.findall(f"{HP}tr")
            for r_index, tr in enumerate(rows):
                fill = fills.get(tr.find(f"{HP}tc").get("borderFillIDRef"))
                if fill is None:
                    failures.append(f"{template_key}: box cell borderFill missing")
                    break
                top = fill.find(f"{HH}topBorder").get("type")
                bottom = fill.find(f"{HH}bottomBorder").get("type")
                left = fill.find(f"{HH}leftBorder").get("type")
                want_top = "SOLID" if r_index == 0 else "NONE"
                want_bottom = "SOLID" if r_index == len(rows) - 1 else "NONE"
                if (left, top, bottom) != ("SOLID", want_top, want_bottom):
                    failures.append(f"{template_key}: box row {r_index} borders {(left, top, bottom)} != {('SOLID', want_top, want_bottom)}")
                    break
        span_tables = [t for t in tables if t.get("colCnt") == "5"]
        if len(span_tables) != 1:
            failures.append(f"{template_key}: expected one 5-column table, got {len(span_tables)}")
        else:
            tcs = list(span_tables[0].iter(f"{HP}tc"))
            merged = [c for c in tcs if c.find(f"{HP}cellSpan").get("colSpan") != "1" or c.find(f"{HP}cellSpan").get("rowSpan") != "1"]
            if len(tcs) != 9 or len(merged) != 7:
                failures.append(f"{template_key}: span table cells {len(tcs)} (expected 9), merged {len(merged)} (expected 7)")
            addrs = {(c.find(f"{HP}cellAddr").get("rowAddr"), c.find(f"{HP}cellAddr").get("colAddr")) for c in tcs}
            if ("0", "1") in addrs or ("1", "2") in addrs:
                failures.append(f"{template_key}: covered cells were not removed")
            texts = ["".join(t.text or "" for t in c.iter(f"{HP}t")) for c in tcs]
            if not any("보기 본문" in t for t in texts) or not any("< 보 기 >" in t for t in texts):
                failures.append(f"{template_key}: merged cell text lost")

    # 4) DOCX: 같은 의미(지문 행 사이 선 없음, python-docx 병합)
    from docx import Document
    from docx.oxml.ns import qn

    docx_path = export_dir / "box.docx"
    docx_writer.write_docx(docx_path, "지문 상자 테스트", problems, "basic")
    document = Document(str(docx_path))
    docx_box = [t for t in document.tables if len(t.columns) == 1 and len(t.rows) == len(PASSAGE_PARAS)]
    if len(docx_box) != 1:
        failures.append(f"DOCX: passage table ({len(PASSAGE_PARAS)}x1) missing")
    else:
        middle = docx_box[0].rows[1].cells[0]._tc.tcPr.find(qn("w:tcBorders"))
        if middle is None or middle.find(qn("w:top")) is None or middle.find(qn("w:top")).get(qn("w:val")) != "nil":
            failures.append("DOCX: inner row border of passage box not removed")
    docx_span = [t for t in document.tables if len(t.columns) == 5]
    if len(docx_span) != 1:
        failures.append(f"DOCX: 5-column table missing ({len(docx_span)})")
    else:
        grid_spans = [tc.tcPr.find(qn("w:gridSpan")) for tr in docx_span[0]._tbl.tr_lst for tc in tr.tc_lst]
        if sum(1 for g in grid_spans if g is not None) != 6:
            failures.append(f"DOCX: gridSpan count {sum(1 for g in grid_spans if g is not None)} != 6")
        if not any(tc.tcPr.find(qn("w:vMerge")) is not None for tr in docx_span[0]._tbl.tr_lst for tc in tr.tc_lst):
            failures.append("DOCX: vertical merge missing")

    # 5) 실물(선택): 국어 HWP 가 있으면 cellSpan 97 / 지문 1×1 표 없음
    real = next((p for p in [
        ROOT / "data/external_exam_qa/2026_march_high3/01.3월_고3_국어_언어와매체.hwp",
        ROOT / "tmp/audit-2026-10-02/k1_formats/inputs/01.3월_고3_국어_언어와매체.hwp",
    ] if p.exists()), None)
    if real is not None and hwp_ir.available():
        real_result = importers._import_hwp_via_ir(real.name, real.read_bytes(), {})
        if real_result:
            real_problems = storage.get_problems_by_ids(real_result["ordered_ids"])
            out = export_dir / "real_basic.hwpx"
            hwpx_writer_v2.write_hwpx(out, "실물", real_problems, "basic")
            section = hwpx_section(out)
            merged = sum(
                1 for s in section.iter(f"{HP}cellSpan")
                if int(s.get("colSpan", "1")) > 1 or int(s.get("rowSpan", "1")) > 1
            )
            max_cell_h = max(int(c.find(f"{HP}cellSz").get("height", "0")) for c in section.iter(f"{HP}tc"))
            print(f"real sample: cellSpan>1 = {merged}, max cell height = {max_cell_h}")
            if merged < 90:
                failures.append(f"real sample: cellSpan>1 {merged} < 90")
            if max_cell_h > 60000:
                failures.append(f"real sample: oversized cell {max_cell_h}")
    else:
        print("real sample skipped (file or rhwp missing)")

    if failures:
        print("FAIL")
        for item in failures:
            print(" -", item)
        return 1
    print("PASS: HWP passage box rows + cellSpan emission")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
