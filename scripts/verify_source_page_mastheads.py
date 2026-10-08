"""Per-form English mastheads remain measured, editable native headers."""
from pathlib import Path
from copy import deepcopy
import sys
import tempfile
import zipfile

import fitz
from lxml import etree
import rhwp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.hwpx_writer_v2 import HwpxDocument, write_hwpx
from app.pdf_masthead_flow import restore_measured_page_header
from app.pdf_masthead_sections import _coherent_running
from app.pdf_masthead_typography import measure_source_page_masthead
from app.pdf_layout_writer import _page_body_top, _prepare_hancom_compatibility, _save_hancom_compatible_document
from app.pdf_native_content import annotate_question_groups
from verify_native_masthead_typography import text_positions
from verify_raster_english_masthead import fixture

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def running_fixture():
    document = fixture(title=False, period=False)
    page = document[0]
    page.add_redact_annot(fitz.Rect(730, 70, 755, 110))
    page.apply_redactions()
    page.insert_text((90, 155), "2", fontsize=25)
    return document


def save_postprocessed(path, section, header):
    """Match the measured-typography phase after base compatibility cleanup."""
    with zipfile.ZipFile(path) as archive:
        payloads = {info.filename: (info, archive.read(info.filename)) for info in archive.infolist()}
    for name, root in (("Contents/section0.xml", section), ("Contents/header.xml", header)):
        info, _ = payloads[name]
        payloads[name] = (info, etree.tostring(root, encoding="utf-8", xml_declaration=True, standalone=True))
    with zipfile.ZipFile(path, "w") as archive:
        for info, payload in payloads.values():
            archive.writestr(info, payload)


def verify_builder(meta, folder):
    meta = deepcopy(meta)
    meta["outlines"] = [{"bbox_pt": [670, 130, 750, 165], "width_pt": .5,
                         "points_pt": [[670, 130], [750, 130], [750, 165], [670, 165], [670, 130]]}]
    document = HwpxDocument.new()
    scale = 59528 / meta["source_page_width_pt"]
    document.set_page_size(width=59528, height=84188)
    document.set_page_margins(left=round(85 * scale), right=round(85 * scale),
                              top=round(230 * scale), bottom=4000, header=0, footer=0)
    document.add_paragraph("Original complete body remains editable.")
    path = folder / (meta["kind"] + ".hwpx")
    _prepare_hancom_compatibility(document)
    _save_hancom_compatible_document(document, path)
    document = HwpxDocument.open(path)
    body = document.sections[0].paragraphs[-1]
    before = etree.tostring(body.element)
    section = document.sections[0].element
    header = document.headers[0].element

    def char_style(base, height, font, spacing, ratio, bold=None):
        identifier = document.ensure_run_style(base_char_pr_id=base, size=height / 100,
                                               font=font, bold=bool(bold))
        style = header.find(".//" + HH + 'charPr[@id="' + identifier + '"]')
        for tag, value in (("spacing", spacing), ("ratio", ratio)):
            node = style.find(HH + tag)
            for language in node.attrib:
                node.set(language, str(value))
        document.headers[0].mark_dirty()
        return identifier

    assert restore_measured_page_header(section, header, meta, char_style,
                                         body_top_hwp=230 * scale)
    assert etree.tostring(body.element) == before, "Header builder altered body text/style/cache"
    running = section.find(".//" + HP + "header")
    assert running is not None and not list(running.iter(HP + "pic"))
    polygon = running.find(".//" + HP + "polygon")
    assert polygon is not None
    tags = [etree.QName(node).localname for node in polygon]
    assert tags.index("pt") < tags.index("sz") < tags.index("pos")
    assert len(polygon.findall("{http://www.hancom.co.kr/hwpml/2011/core}pt")) == 5
    text = "".join(running.itertext())
    fields = [name for name in ("title", "area", "period_geometry", "variant_geometry", "page_number") if meta.get(name)]
    for name in fields:
        assert meta[name]["text"] in text, (name, text)
    margin = section.find(".//" + HP + "pagePr/" + HP + "margin")
    assert abs(int(margin.get("top")) + int(margin.get("header")) - 230 * scale) < 1
    # Production applies measured geometry after compatibility normalization.
    # Serialize that postprocessing phase directly so its measured line caches
    # are checked rather than replaced by the base writer's generic caches.
    save_postprocessed(path, section, header)
    parsed = rhwp.parse(str(path))
    assert parsed.page_count == 1 and bytes(parsed.render_png(0))
    positions = text_positions(path)
    for name in fields:
        record = meta[name]
        x, y = record["bbox_pt"][0] * scale / 75, record["baseline_pt"] * scale / 75
        assert any(abs(a - x) < .1 and abs(b - y) < .1 for _, a, b in positions), (name, x, y, positions)
    svg = etree.fromstring(parsed.render_svg(0).encode())
    rule = meta["bottom_rule"]
    y = rule["y_pt"] * scale / 75
    segments = [node for node in svg.iter("{http://www.w3.org/2000/svg}line")
                if abs(float(node.get("y1")) - y) < .1 and abs(float(node.get("y2")) - y) < .1]
    assert segments, "Measured source separating rule is absent from the rendered header"
    assert abs(min(float(node.get("x1")) for node in segments) - rule["left_pt"] * scale / 75) < .2
    assert abs(max(float(node.get("x2")) for node in segments) - rule["right_pt"] * scale / 75) < .1
    reopened = folder / (meta["kind"] + "_reopened.hwpx")
    HwpxDocument.open(path).save_to_path(reopened)
    with zipfile.ZipFile(reopened) as archive:
        assert etree.tostring(etree.fromstring(archive.read("Contents/section0.xml"))) == etree.tostring(section)
    # Parity variants replace only their own header and preserve the other side.
    assert restore_measured_page_header(section, header, meta, char_style,
                                         body_top_hwp=230 * scale, page_type="EVEN", automatic_page_number=True)
    assert restore_measured_page_header(section, header, meta, char_style,
                                         body_top_hwp=230 * scale, page_type="ODD", automatic_page_number=True)
    assert {node.get("applyPageType") for node in section.iter(HP + "header")} == {"BOTH", "EVEN", "ODD"}
    assert len(list(section.iter(HP + "autoNum"))) == 2
    if meta["kind"] == "running":
        even, odd = deepcopy(meta), deepcopy(meta)
        odd["page_number"]["baseline_pt"] -= .84
        top = min((record["baseline_pt"] - max(s["font_size_pt"] for s in record["spans"]) * .85) * scale
                  for peer in (even, odd) for record in (peer["area"], peer["variant_geometry"], peer["page_number"]))
        for old in list(section.iter(HP + "header")):
            old.getparent().remove(old)
        for parity, peer in (("EVEN", even), ("ODD", odd)):
            assert restore_measured_page_header(section, header, peer, char_style,
                                                body_top_hwp=230 * scale, page_type=parity,
                                                automatic_page_number=True, header_top_hwp=top)
        second = deepcopy(body.element)
        second.set("id", "99999"); second.set("pageBreak", "1")
        section.append(second)
        save_postprocessed(path, section, header)
        assert rhwp.parse(str(path)).page_count == 2
        for page_index, peer in enumerate((odd, even)):
            positions = text_positions(path, page_index)
            for name in ("area", "variant_geometry", "page_number"):
                record = peer[name]
                x, y = record["bbox_pt"][0] * scale / 75, record["baseline_pt"] * scale / 75
                assert any(abs(a - x) < .1 and abs(b - y) < .1 for _, a, b in positions), (page_index, name, x, y, positions)


def verify_sections(folder, first_pages=4, second_pages=4):
    with fixture() as full_source, running_fixture() as running_source:
        full = measure_source_page_masthead(full_source[0], 220, area_hint="영어 영역")
        running = measure_source_page_masthead(running_source[0], 220, area_hint="영어 영역")
    records, items = [], []
    for index in range(first_pages + second_pages):
        printed = index + 1 if index < first_pages else index - first_pages + 1
        record = deepcopy(full if printed == 1 else running)
        record["source_page"] = index + 1
        for field, value in (("variant_geometry", "홀수형" if index < first_pages else "짝수형"),
                             ("page_number", str(printed))):
            record[field]["text"] = value
            record[field]["spans"][0]["text"] = value
        if printed > 1 and printed % 2:
            # The source switches the printed page number and variant sides;
            # its odd-page number also has a slightly different baseline.
            record["page_number"]["bbox_pt"] = [x + (645 if axis % 2 == 0 else -.84)
                                                      for axis, x in enumerate(record["page_number"]["bbox_pt"])]
            record["page_number"]["baseline_pt"] -= .84
            record["variant_geometry"]["bbox_pt"] = [x - (590 if axis % 2 == 0 else 0)
                                                           for axis, x in enumerate(record["variant_geometry"]["bbox_pt"])]
        records.append(record)
        for column, left in ((1, 90), (2, 435)):
            items.append({
                "stem": f"{index * 2 + column}. Complete editable question from source page {index + 1} column {column}.",
                "source_page": index + 1,
                "layout": {"source_content": True, "source_page_width_pt": 842,
                           "source_column": column, "source_bbox_pt": [left, 230, left + 310, 245],
                           "source_masthead_area": "영어 영역",
                           "source_typography": {"font_size_pt": 11, "font_name": "Helvetica",
                                                 "line_spacing_pt": 16, "source_column_width_pt": 310}},
            })
    items[0]["layout"]["source_masthead_typography"] = full
    items[0]["layout"]["source_page_mastheads"] = records
    annotate_question_groups(items)
    assert _coherent_running(records[1:first_pages])
    if first_pages == 4:
        for mutate in (
            lambda r: r[0]["variant_geometry"].update(text="짝수형"),
            lambda r: r[0]["bottom_rule"].update(y_pt=205),
            lambda r: r[0]["area"]["bbox_pt"].__setitem__(0, 330),
        ):
            bad = deepcopy(records[1:4]); mutate(bad)
            assert not _coherent_running(bad), "Inconsistent repeating source geometry accepted"
    expected_sections = 4 if second_pages else 2
    for scenario in (("complete", "missing_page", "number_gap") if first_pages == 4 and second_pages else ("complete",)):
        complete = scenario == "complete"
        copied = deepcopy(items)
        if scenario == "missing_page":
            copied[0]["layout"]["source_page_mastheads"].pop()
        elif scenario == "number_gap":
            copied[0]["layout"]["source_page_mastheads"][2]["page_number"]["text"] = "7"
        copied[0]["layout"]["source_page_mastheads_restored"] = 99
        path = folder / f"booklet_{first_pages}_{second_pages}_{scenario}.hwpx"
        write_hwpx(path, full["title"]["text"], copied, "kice_english",
                   native_math=True, preserve_source_layout=True)
        restored = copied[0]["layout"].get("source_page_mastheads_restored")
        assert restored == (expected_sections if complete else None), (scenario, restored)
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.startswith("Contents/section") and name.endswith(".xml")]
            sections = [etree.fromstring(archive.read(name)) for name in names]
        assert len(sections) == (expected_sections if complete else 2), "Unproven per-page metadata must preserve the existing section path"
        rendered = rhwp.parse(str(path))
        assert rendered.page_count == len(records), (scenario, rendered.page_count)
        if complete:
            assert names == [f"Contents/section{index}.xml" for index in range(expected_sections)]
            assert [[h.get("applyPageType") for h in section.iter(HP + "header")] for section in sections] == [
                ["BOTH"], ["EVEN", "ODD"], ["BOTH"], ["EVEN", "ODD"]][:expected_sections]
            for page_index, record in enumerate(records):
                nodes = [(text, x, y) for text, x, y in text_positions(path, page_index) if y < 160]
                for field in ("area", "variant_geometry", "page_number"):
                    measured = record[field]
                    x, y = measured["bbox_pt"][0] * 59528 / 842 / 75, measured["baseline_pt"] * 59528 / 842 / 75
                    assert any(abs(a - x) < .1 and abs(b - y) < .1 for _, a, b in nodes), (first_pages, page_index, field, nodes)
                number = record["page_number"]
                x, y = number["bbox_pt"][0] * 59528 / 842 / 75, number["baseline_pt"] * 59528 / 842 / 75
                assert any(text == number["text"] and abs(a - x) < .1 and abs(b - y) < .1
                           for text, a, b in nodes), (page_index, number["text"], nodes)
                compact = "".join(text for text, _, _ in nodes)
                assert record["variant_geometry"]["text"] in compact
        for item in items:
            assert item["stem"] in "".join("".join(section.itertext()) for section in sections)


def main():
    with tempfile.TemporaryDirectory(prefix="source_page_mastheads_") as temporary:
        folder = Path(temporary)
        for factory, kind in ((fixture, "full"), (running_fixture, "running")):
            with factory() as document:
                meta = measure_source_page_masthead(document[0], 220, area_hint="영어 영역")
                assert meta["kind"] == kind and meta["source_page"] == 1
                verify_builder(meta, folder)
        for options in ({"duplicate": True}, {"variant": False}, {"prose_image": True}):
            with fixture(**options) as document:
                assert not measure_source_page_masthead(document[0], 220, area_hint="영어 영역")
        for factory in (fixture, running_fixture):
            with factory() as document:
                for hint in ("", "수학 영역", "영어 듣기 문제"):
                    assert not measure_source_page_masthead(document[0], 220, area_hint=hint)
        with fitz.open() as document:
            page = document.new_page(width=842, height=1191)
            page.insert_text((150, 100), "2026학년도 시험 문제지", fontname="korea", fontsize=19)
            page.insert_text((340, 155), "수학 영역", fontname="korea", fontsize=30)
            assert not measure_source_page_masthead(page, 220, area_hint="영어 영역"), "native source area overrides a conflicting hint"
        verify_sections(folder)
        verify_sections(folder, first_pages=3)
        verify_sections(folder, second_pages=0)
    source = ROOT / "data/external_exam_qa/2026_csat/문제지/영어/영어.pdf"
    if source.is_file():
        with fitz.open(source) as document:
            records = [measure_source_page_masthead(page, _page_body_top(page), area_hint="영어 영역")
                       for page in document]
        assert len(records) == 16 and all(records)
        for index, meta in enumerate(records):
            assert meta["source_page"] == index + 1
            assert meta["kind"] == ("full" if index % 8 == 0 else "running")
            assert meta["page_number"]["text"] == str(index % 8 + 1)
            assert meta["variant_geometry"]["text"] == ("홀수형" if index < 8 else "짝수형")
            assert meta["bottom_rule"]["width_pt"] > 0
            assert meta["area"]["raster_geometry"]
        assert records[1]["page_number"]["bbox_pt"][0] < 200
        assert records[2]["page_number"]["bbox_pt"][0] > 650
        print("PASS actual 16-page CSAT: independent full/running geometry, original form and restarted page numbers")
    print("SOURCE_PAGE_MASTHEADS_OK: editable native fields at source baselines, body isolation, parity controls, ambiguity guards")


if __name__ == "__main__":
    main()
