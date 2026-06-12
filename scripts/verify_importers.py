# -*- coding: utf-8 -*-
"""임포터/내보내기 자체 검증 스크립트 (서버 없이 직접 호출)."""

from __future__ import annotations

import io
import os
import sys
import tempfile
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

storage.init_db()

ROUNDTRIP_TEMPLATE_KEY = "school_exam"


def make_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (120, 60), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def make_docx() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph("1. 다음 중 광합성이 일어나는 장소는?")
    doc.add_paragraph("① 미토콘드리아  ② 엽록체  ③ 리보솜")
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

# 2) image import
result = importers.import_image("pic.png", make_png(), {})
print("Image import:", len(result["created"]), "problems;", result["notices"])
if not result["created"][0]["image_paths"]:
    failures.append("Image: missing image path")

# 3) HWPX export -> re-import roundtrip
template = exam_templates.get_template(ROUNDTRIP_TEMPLATE_KEY)
if template.key != ROUNDTRIP_TEMPLATE_KEY or template.key == "basic":
    failures.append(f"HWPX template: expected non-default template {ROUNDTRIP_TEMPLATE_KEY!r}")
ids = [p["id"] for p in created]
problems = storage.get_problems_by_ids(ids)
export_path = storage.EXPORT_DIR / "roundtrip.hwpx"
storage.ensure_dirs()
hwpx_writer.write_hwpx(
    export_path,
    "라운드트립 테스트",
    problems,
    template_key=ROUNDTRIP_TEMPLATE_KEY,
)
payload = export_path.read_bytes()
result = importers.import_hwpx("roundtrip.hwpx", payload, {})
print(
    f"HWPX roundtrip import ({ROUNDTRIP_TEMPLATE_KEY} template):",
    len(result["created"]),
    "problems;",
    result["notices"],
)
texts = "\n".join(p["stem"] for p in result["created"])
if "광합성" not in texts or "세포 호흡" not in texts:
    failures.append("HWPX roundtrip: text lost")

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

# 3c) 정답·해설지 포함 내보내기
for problem_id in ids:
    storage.update_problem(
        problem_id,
        {
            "answer": "2",
            "explanation": "엽록체에서 광합성이 일어난다.",
            "choices": ["미토콘드리아", "엽록체", "리보솜"],
        },
    )
problems = storage.get_problems_by_ids(ids)
sheet_path = storage.EXPORT_DIR / "answer_sheet.hwpx"
hwpx_writer.write_hwpx(
    sheet_path,
    "정답지 테스트",
    problems,
    template_key=ROUNDTRIP_TEMPLATE_KEY,
    include_answer_sheet=True,
)
result = importers.import_hwpx("answer_sheet.hwpx", sheet_path.read_bytes(), {})
sheet_text = "\n".join(p["stem"] for p in result["created"])
print("Answer sheet roundtrip:", len(result["created"]), "problems")
if "빠른 정답" not in sheet_text or "②" not in sheet_text:
    failures.append("Answer sheet: quick answers missing from exported HWPX")
if "엽록체에서 광합성이 일어난다" not in sheet_text:
    failures.append("Answer sheet: explanation missing from exported HWPX")
if rhwp is not None:
    sheet_doc = rhwp.parse(str(sheet_path))
    if sheet_doc.page_count < 2:
        failures.append("Answer sheet: expected page break to add a page")
    else:
        print(f"Answer sheet pages: {sheet_doc.page_count}")

# 3d) DOCX 정답·해설지
from app import docx_writer  # noqa: E402

docx_sheet_path = storage.EXPORT_DIR / "answer_sheet.docx"
docx_writer.write_docx(
    docx_sheet_path,
    "정답지 테스트",
    problems,
    template_key=ROUNDTRIP_TEMPLATE_KEY,
    include_answer_sheet=True,
)
result = importers.import_docx("answer_sheet.docx", docx_sheet_path.read_bytes(), {})
docx_text = "\n".join(p["stem"] for p in result["created"])
if "빠른 정답" not in docx_text or "②" not in docx_text:
    failures.append("Answer sheet: quick answers missing from exported DOCX")
print("DOCX answer sheet roundtrip: ok" if "빠른 정답" in docx_text else "DOCX answer sheet roundtrip: MISSING")

# 4) CSV import still fine
csv_data = "번호,문제,정답\n1,사과는 영어로?,apple\n2,바다는 영어로?,sea\n".encode("utf-8-sig")
result = importers.import_csv("words.csv", csv_data, {})
print("CSV import:", len(result["created"]), "problems")
if len(result["created"]) != 2:
    failures.append("CSV: expected 2 problems")

print()
if failures:
    print("FAILURES:")
    for failure in failures:
        print(" -", failure)
    sys.exit(1)
print("ALL OK")
