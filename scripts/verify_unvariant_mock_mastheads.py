"""Official mock headers without grade/variant require independent source proof."""
from __future__ import annotations
import argparse
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME = tempfile.TemporaryDirectory(prefix="unvariant_mock_")
os.environ["HWP_MAKE_DATA_DIR"] = str(Path(RUNTIME.name) / "engine")
os.environ["HWP_MAKE_SETTINGS_DIR"] = str(Path(RUNTIME.name) / "settings")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import fitz  # noqa: E402
from lxml import etree  # noqa: E402
import rhwp  # noqa: E402
from app.pdf_layout_writer import _page_body_top  # noqa: E402
from app.pdf_masthead_typography import measure_source_page_masthead  # noqa: E402
from app.pdf_masthead_sections import _coherent_running  # noqa: E402
from app.hwpx_writer_v2 import HwpxDocument  # noqa: E402
from hwpx.oxml import HwpxOxmlParagraph  # noqa: E402
from verify_native_masthead_typography import text_positions  # noqa: E402

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
SOURCE = ROOT / "data/external_exam_qa/2027_kice_september_high3/english.pdf"


def check(condition, text):
    assert condition, text
    print("PASS:", text, flush=True)


def fixture(*, official=True, period="제3 교시", number="1", rule=True,
            duplicate=False, extra=False, running_number="2", wrong_rail=False,
            running_rule=True, running_ratio=False):
    stamp = fitz.open()
    sp = stamp.new_page(width=162, height=42)
    sp.insert_text((1, 34), "영어 영역", fontname="korea", fontsize=32)
    image = sp.get_pixmap().tobytes("png")
    stamp.close()
    document = fitz.open()
    first = document.new_page(width=842, height=1191)
    title = ("2027학년도 대학수학능력시험 9월 모의평가 문제지" if official
             else "2027학년도 시험 문제지")
    first.insert_text((190, 134), title, fontname="korea", fontsize=19)
    if period:
        first.insert_text((90, 180), period, fontname="korea", fontsize=19)
    first.insert_text((735, 134), number, fontsize=25)
    first.insert_image(fitz.Rect(340, 154, 502, 196), stream=image)
    if duplicate:
        first.insert_image(fitz.Rect(340, 165, 502, 207), stream=image)
    if extra:
        first.insert_text((680, 180), "Unverified", fontsize=12)
    if rule:
        first.draw_line((85, 218), (755, 218), width=1)
    first.insert_text((90, 245), "1. Listen to the English conversation.", fontsize=10)
    second = document.new_page(width=842, height=1191)
    second.insert_text((735 if wrong_rail else 90, 134), running_number, fontsize=25)
    second.insert_image(fitz.Rect(367, 112, 475 if not running_ratio else 495, 140), stream=image,
                        keep_proportion=False)
    if running_rule:
        second.draw_line((85, 147), (755, 147), width=1)
    second.insert_text((90, 170), "2. Read the next English passage.", fontsize=10)
    return document


def records(document):
    return [measure_source_page_masthead(page, _page_body_top(page), area_hint="영어 영역")
            for page in document]


def synthetic():
    with fixture() as document:
        full, running = records(document)
        check(full.get("kind") == "full" and running.get("kind") == "running",
              "official first-page proof admits the unlabelled running header")
        check(full.get("unvariant_mock") and running.get("unvariant_mock"),
              "both headers retain independent official title/period/geometry proof")
        check(not any(record.get(key) for record in (full, running)
                      for key in ("variant_geometry", "grade_geometry")),
              "no absent grade or odd/even field is invented")
        check(_coherent_running([running]), "source-proven unlabelled run is coherent")
        altered = deepcopy(running); altered.pop("unvariant_mock")
        check(not _coherent_running([altered]), "a missing form label without source proof still fails")
        altered = deepcopy(running); altered["source_page"] = 3
        check(not _coherent_running([altered]), "physical/printed page mismatch still fails")
        for hint in ("", "수학 영역", "영어 듣기 문제"):
            check(not measure_source_page_masthead(document[0], _page_body_top(document[0]), area_hint=hint),
                  "an unverified or conflicting subject cannot identify a raster logo")
    for options in ({"official": False}, {"period": "제2 교시"}, {"period": ""},
                    {"number": "5"}, {"rule": False}, {"duplicate": True}, {"extra": True}):
        with fixture(**options) as document:
            check(not records(document)[0], f"incomplete/ambiguous first-page proof is rejected: {options}")
            check(not records(document)[1], "unproven first page cannot authorize another page's image")
    for options in ({"running_number": "3"}, {"wrong_rail": True},
                    {"running_rule": False}, {"running_ratio": True}):
        with fixture(**options) as document:
            check(not records(document)[1], f"inconsistent running source geometry is rejected: {options}")


def header_xml(path):
    with zipfile.ZipFile(path) as archive:
        roots = [etree.fromstring(archive.read(name)) for name in archive.namelist()
                 if name.startswith("Contents/section") and name.endswith(".xml")]
    return [etree.tostring(header) for root in roots for header in root.iter(HP + "header")]


def actual(folder, existing=None, api_result=None):
    if not SOURCE.is_file():
        print("MISSING:", SOURCE)
        return 2
    for source, count in ((SOURCE, 8),
                          (ROOT / "data/external_exam_qa/2026_september_high1/english.pdf", 8),
                          (ROOT / "data/external_exam_qa/2026_september_high2/english.pdf", 8),
                          (ROOT / "data/external_exam_qa/2026_csat/문제지/영어/영어.pdf", 16)):
        if not source.is_file():
            print("MISSING:", source)
            return 2
        with fitz.open(source) as document:
            measured = records(document)
        check(len(measured) == count and all(measured), f"all {count} actual source mastheads recognized: {source.parent.name}")
        if source == SOURCE:
            high3 = measured
            check(_coherent_running(high3[1:]), "all seven actual unlabelled running pages share proven geometry")
        else:
            check(not any(record.get("unvariant_mock") for record in measured),
                  "existing labelled source keeps its original masthead path")
    from app.pdf_editability import inspect_pdf_editability
    if existing:
        if not api_result:
            raise ValueError("--existing-hwpx requires its --api-result report")
        payload = json.loads(api_result.read_text(encoding="utf-8"))
        output = existing
        print("REUSE: existing actual API export", existing, flush=True)
    else:
        from fastapi.testclient import TestClient
        from app import main as api, storage
        with TestClient(api.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
            client.headers["Origin"] = "http://127.0.0.1"
            response = client.post("/api/pdf-layout-export", json={
                "filename": "neutral-source.pdf", "data_base64": base64.b64encode(SOURCE.read_bytes()).decode(),
                "layout_mode": "structured", "native_math": True,
                "math_ai_recognition": False, "variant_policy": "all", "strict": True})
        payload = response.json()
        (folder / "api-result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        check(response.status_code == 200, f"actual high3 strict API returns 200: {response.status_code}")
        output = storage.EXPORT_DIR / payload["export"]["name"]
    # Copy the result out of auto-cleaned isolated application storage.
    saved = folder / "high3-native.hwpx"; saved.write_bytes(output.read_bytes())
    stats = payload["stats"]
    check(stats["question_grouping"]["question_count"] == 45, "actual full output owns all 45 native question units")
    page_count = rhwp.parse(str(saved)).page_count
    print("ACTUAL_RENDERED_PAGE_COUNT:", page_count, flush=True)
    editability = inspect_pdf_editability(SOURCE, saved, stats.get("image_provenance") or [], require_question_boxes=True)
    (folder / "editability.json").write_text(json.dumps(editability, ensure_ascii=False, indent=2), encoding="utf-8")
    check(editability["ok"], "independent full-source editability passes")
    headers = header_xml(saved)
    check(len(headers) == 3 and all(b"pic" not in node for node in headers),
          "full/even/odd headers contain editable fields and no copied logo images")
    for index, record in enumerate(high3):
        positions = text_positions(saved, index)
        for key in ("title", "period_geometry", "area", "page_number"):
            if key not in record:
                continue
            field = record[key]
            scale = 59528 / record["source_page_width_pt"] / 75
            x, y = field["bbox_pt"][0] * scale, field["baseline_pt"] * scale
            check(any(abs(a-x) < .1 and abs(b-y) < .1 for _, a, b in positions),
                  f"actual p{index+1} {key} retains its source rail and baseline")
        if index in (0, 1, 7):
            (folder / f"high3-p{index+1}.png").write_bytes(bytes(rhwp.parse(str(saved)).render_png(index)))
    document = HwpxDocument.open(saved)
    selected = next((HwpxOxmlParagraph(node, section) for section in document.sections
                     for draw in section.element.iter(HP + "drawText") if draw.get("name") == "question:v1:q01"
                     for node in draw.iter(HP + "p") if any((t.text or "").strip() for t in node.iter(HP + "t"))), None)
    check(selected is not None, "a body question is independently editable")
    next(run for run in selected.runs if run.text.strip()).text += " EDIT_HEADER_PROOF"
    edited = folder / "high3-edited.hwpx"; document.save_to_path(edited)
    check(header_xml(edited) == headers, "ordinary body editing/resaving preserves native header XML")
    parsed = rhwp.parse(str(edited))
    painted = "".join(text for text, _, _ in text_positions(edited, 0))
    check(parsed.page_count == page_count and "EDIT_HEADER_PROOF" in painted,
          "edited body paints and the original page/header flow survives resave")
    print("QUALITY_DIAGNOSTIC:", json.dumps({"objective": payload.get("quality", {}).get("objective_score"),
          "harsh": payload.get("fidelity", {}).get("overall_harsh_layout_score")}), flush=True)
    check(page_count == 8, "actual full output renders on eight pages")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--actual", action="store_true")
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--existing-hwpx", type=Path)
    parser.add_argument("--api-result", type=Path)
    args = parser.parse_args()
    synthetic()
    folder = args.artifacts or Path(RUNTIME.name)
    folder.mkdir(parents=True, exist_ok=True)
    return actual(folder, args.existing_hwpx, args.api_result) if args.actual else 0


if __name__ == "__main__":
    raise SystemExit(main())
