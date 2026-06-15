# -*- coding: utf-8 -*-
"""임포터/내보내기 자체 검증 스크립트 (서버 없이 직접 호출)."""

from __future__ import annotations

import html
import io
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["HWP_MAKE_DATA_DIR"] = str(ROOT / "data" / "verify_tmp2")

from PIL import Image  # noqa: E402

from app import exam_templates, hwpx_writer, importers, storage  # noqa: E402

# 중복 감지 검증이 결정적으로 동작하도록 매 실행마다 DB를 비운다.
storage.DB_PATH.unlink(missing_ok=True)
storage.init_db()

ROUNDTRIP_TEMPLATE_KEY = "school_exam"


def hwpx_text(path: Path) -> str:
    """내보낸 HWPX의 본문 텍스트를 zip/XML에서 직접 뽑는다(임포터·중복검사와 무관하게 출력 검증)."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("Contents/section0.xml").decode("utf-8")
    return html.unescape("".join(re.findall(r"<hp:t[^>]*>(.*?)</hp:t>", xml, re.S)))


def hwpx_section_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read("Contents/section0.xml").decode("utf-8")


def docx_text(path: Path) -> str:
    from docx import Document as DocxDocument

    document = DocxDocument(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def reset_problems() -> None:
    with storage.connect() as conn:
        conn.execute("DELETE FROM problems")
        conn.commit()


def make_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (120, 60), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def make_docx() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph("1. 다음 중 광합성이 일어나는 장소는?")
    doc.add_paragraph("① 미토콘드리아  ② 엽록체  ③ 리보솜")
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "세포소기관"
    table.rows[0].cells[1].text = "기능"
    table.rows[1].cells[0].text = "엽록체"
    table.rows[1].cells[1].text = "광합성"
    image_path = Path(tempfile.mkdtemp()) / "t.png"
    image_path.write_bytes(make_png())
    doc.add_picture(str(image_path))
    doc.add_paragraph("2. 세포 호흡의 결과 생성되는 물질은?")
    doc.add_paragraph("물과 이산화탄소에 대해 서술하시오.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


failures = []

# 1) DOCX import
result = importers.import_docx("sample.docx", make_docx(), {})
created = result["created"]
print("DOCX import:", len(created), "problems;", result["notices"])
if len(created) != 2:
    failures.append(f"DOCX: expected 2 problems, got {len(created)}")
if not created[0]["image_paths"]:
    failures.append("DOCX: first problem missing image")
if "광합성" not in created[0]["stem"]:
    failures.append("DOCX: stem text wrong")
if not created[0].get("tables"):
    failures.append("DOCX: table not captured into tables model")
elif "세포소기관" not in str(created[0]["tables"]):
    failures.append("DOCX: table content wrong")

# 2) image import
result = importers.import_image("pic.png", make_png(), {})
print("Image import:", len(result["created"]), "problems;", result["notices"])
if not result["created"][0]["image_paths"]:
    failures.append("Image: missing image path")

from app import docx_writer  # noqa: E402

# 3) 내보내기 준비: 정답/선지/해설을 채운 뒤 in-memory로 문항을 잡아 둔다.
template = exam_templates.get_template(ROUNDTRIP_TEMPLATE_KEY)
if template.key != ROUNDTRIP_TEMPLATE_KEY or template.key == "basic":
    failures.append(f"HWPX template: expected non-default template {ROUNDTRIP_TEMPLATE_KEY!r}")
ids = [p["id"] for p in created]
for problem_id in ids:
    storage.update_problem(
        problem_id,
        {
            "answer": "2",
            "explanation": "엽록체에서 광합성이 일어난다.",
            "choices": ["미토콘드리아", "엽록체", "리보솜"],
        },
    )
# 표 출력 검증용: 첫 문항에 자료 표를 붙인다.
storage.update_problem(
    ids[0], {"tables": [[["구분", "결과물"], ["광합성", "포도당"], ["호흡", "에너지"]]]}
)
problems = storage.get_problems_by_ids(ids)
if not problems[0].get("tables"):
    failures.append("Tables: not persisted/round-tripped through storage")
storage.ensure_dirs()

# 3a) 기본 HWPX 내보내기 → 출력 파일을 직접 검사(임포터/중복검사와 분리해 출력 충실도 검증)
export_path = storage.EXPORT_DIR / "roundtrip.hwpx"
hwpx_writer.write_hwpx(export_path, "라운드트립 테스트", problems, template_key=ROUNDTRIP_TEMPLATE_KEY)
body_text = hwpx_text(export_path)
print(f"HWPX export ({ROUNDTRIP_TEMPLATE_KEY} template): {len(body_text)} chars in body")
if "광합성" not in body_text or "세포 호흡" not in body_text:
    failures.append("HWPX export: stem text missing from section XML")

# 3a-2) 표(hp:tbl) 출력 검증: 구조 태그 + 셀 텍스트가 본문에 살아있는지
section_xml = hwpx_section_xml(export_path)
if "<hp:tbl" not in section_xml or "<hp:tc" not in section_xml:
    failures.append("HWPX export: hp:tbl/hp:tc structure missing")
if "구분" not in body_text or "포도당" not in body_text:
    failures.append("HWPX export: table cell text missing from section XML")

# 3b) rhwp 엔진으로 생성 HWPX 구조 검증 + 렌더링 (설치된 경우)
try:
    import rhwp
except Exception:
    rhwp = None
if rhwp is not None:
    doc = rhwp.parse(str(export_path))
    rendered = bytes(doc.render_png(0))
    print(f"rhwp validation: pages={doc.page_count}, render={len(rendered)} bytes")
    if doc.page_count < 1 or not rendered:
        failures.append("rhwp: generated HWPX failed to parse/render")
    if "광합성" not in doc.extract_text():
        failures.append("rhwp: text not extractable from generated HWPX")
else:
    print("rhwp not installed; skipping render validation")

# 3c) 정답·해설지 포함 HWPX — 출력 파일 직접 검사 + 페이지 나눔 확인
sheet_path = storage.EXPORT_DIR / "answer_sheet.hwpx"
hwpx_writer.write_hwpx(
    sheet_path, "정답지 테스트", problems, template_key=ROUNDTRIP_TEMPLATE_KEY, include_answer_sheet=True
)
sheet_text = hwpx_text(sheet_path)
if "빠른 정답" not in sheet_text or "②" not in sheet_text:
    failures.append("Answer sheet: quick answers missing from exported HWPX")
if "엽록체에서 광합성이 일어난다" not in sheet_text:
    failures.append("Answer sheet: explanation missing from exported HWPX")
if rhwp is not None:
    sheet_doc = rhwp.parse(str(sheet_path))
    print(f"Answer sheet pages: {sheet_doc.page_count}")
    if sheet_doc.page_count < 2:
        failures.append("Answer sheet: expected page break to add a page")

# 3d) DOCX 정답·해설지 — 출력 파일 직접 검사
docx_sheet_path = storage.EXPORT_DIR / "answer_sheet.docx"
docx_writer.write_docx(
    docx_sheet_path, "정답지 테스트", problems, template_key=ROUNDTRIP_TEMPLATE_KEY, include_answer_sheet=True
)
docx_body = docx_text(docx_sheet_path)
if "빠른 정답" not in docx_body or "②" not in docx_body:
    failures.append("Answer sheet: quick answers missing from exported DOCX")
print("DOCX answer sheet: ok" if "빠른 정답" in docx_body else "DOCX answer sheet: MISSING")

# 3e) HWPX 임포터 라운드트립: 빈 DB에서 다시 읽어 본문이 살아있는지 확인
reset_problems()
result = importers.import_hwpx("roundtrip.hwpx", export_path.read_bytes(), {})
roundtrip_text = "\n".join(p["stem"] for p in result["created"])
print("HWPX importer roundtrip:", len(result["created"]), "problems")
if "광합성" not in roundtrip_text or "세포 호흡" not in roundtrip_text:
    failures.append("HWPX roundtrip: text lost on re-import")
roundtrip_tables = [p.get("tables") for p in result["created"] if p.get("tables")]
if not roundtrip_tables:
    failures.append("HWPX roundtrip: table lost on re-import")
elif "포도당" not in str(roundtrip_tables):
    failures.append("HWPX roundtrip: table cell text lost on re-import")

# 4) CSV import still fine
csv_data = "번호,문제,정답\n1,사과는 영어로?,apple\n2,바다는 영어로?,sea\n".encode("utf-8-sig")
result = importers.import_csv("words.csv", csv_data, {})
print("CSV import:", len(result["created"]), "problems")
if len(result["created"]) != 2:
    failures.append("CSV: expected 2 problems")

# 5) 중복 감지: 같은 CSV를 다시 가져오면 0개 생성 + 건너뜀 안내
result = importers.import_csv("words.csv", csv_data, {})
print("CSV re-import (dedup):", len(result["created"]), "created;", result["notices"])
if result["created"]:
    failures.append("Dedup: re-import should create 0 problems")
if not any("건너뛰" in notice for notice in result["notices"]):
    failures.append("Dedup: missing skip notice on re-import")

# 5b) 한 파일 안의 동일 문항도 한 번만 생성
dup_csv = "번호,문제,정답\n1,중복질문,A\n2,중복질문,A\n3,다른질문,B\n".encode("utf-8-sig")
result = importers.import_csv("dups.csv", dup_csv, {})
print("CSV intra-file dedup:", len(result["created"]), "created")
if len(result["created"]) != 2:
    failures.append(f"Dedup: intra-file expected 2 unique, got {len(result['created'])}")

print()
if failures:
    print("FAILURES:")
    for failure in failures:
        print(" -", failure)
    sys.exit(1)
print("ALL OK")
