"""Verified English image-heading geometry yields an editable native masthead."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import zipfile

import fitz
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass
from app.hwpx_writer_v2 import HwpxDocument, write_hwpx  # noqa: E402
from app.pdf_masthead_typography import measure_source_masthead  # noqa: E402
from app.pdf_native_content import annotate_question_groups  # noqa: E402

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def fixture(*, duplicate=False, period=True, variant=True, title=True, prose_image=False):
    stamp = fitz.open()
    heading = stamp.new_page(width=162, height=42)
    heading.insert_text((1, 34), "영어 영역", fontname="korea", fontsize=32)
    image = heading.get_pixmap(alpha=False).tobytes("png")
    stamp.close()
    document = fitz.open()
    page = document.new_page(width=842, height=1191)
    if title:
        page.insert_text((150, 100), "2026학년도 시험 문제지", fontname="korea", fontsize=19)
    page.insert_text((735, 100), "1", fontsize=25)
    if period:
        page.insert_text((90, 150), "제3 교시", fontname="korea", fontsize=19)
    if variant:
        page.insert_text((680, 155), "홀수형", fontname="korea", fontsize=19)
    page.insert_image(fitz.Rect(340, 240 if prose_image else 120, 502, 282 if prose_image else 162), stream=image)
    if duplicate:
        page.insert_image(fitz.Rect(340, 165, 502, 207), stream=image)
    page.draw_line((85, 215), (755, 215), width=1)
    return document


def package(path):
    with zipfile.ZipFile(path) as archive:
        return etree.fromstring(archive.read("Contents/section0.xml"))


def native_header(meta, directory):
    items = [{
        "stem": "1. Read the original complete question before choosing an answer.",
        "source_page": 1,
        "layout": {
            "source_content": True, "source_page_width_pt": 842,
            "source_column": 1, "source_bbox_pt": [100, 230, 420, 245],
            "source_masthead_area": meta["area"]["text"],
            "source_masthead_typography": meta,
            "source_typography": {"font_size_pt": 11, "font_name": "Helvetica",
                                  "line_spacing_pt": 16, "source_column_width_pt": 320},
        },
    }]
    annotate_question_groups(items)
    path = directory / "raster_area_native.hwpx"
    write_hwpx(path, meta["title"]["text"], items, "kice_english",
               native_math=True, preserve_source_layout=True)
    section = package(path)
    header = section.find(".//" + HP + "header")
    assert header is not None, "measured image-area geometry did not create a native header"
    texts = [node.text or "" for node in header.iter(HP + "t")]
    for field in ("title", "area", "period_geometry", "variant_geometry", "page_number"):
        expected = meta[field]["text"]
        assert texts.count(expected) == 1, f"masthead {field} was lost or duplicated: {texts!r}"
    assert not list(header.iter(HP + "pic")), "heading image copied instead of editable known area text"
    assert "Read the original complete question" in "".join(section.itertext()), "question prose changed"
    table = header.find(".//" + HP + "tbl")
    assert len(table.findall(HP + "tr")) == 2
    bottom_cells = table.findall(HP + "tr")[1].findall(HP + "tc")
    labels = ["".join(node.text or "" for node in cell.iter(HP + "t")) for cell in bottom_cells]
    assert [label for label in labels if label] == [meta[name]["text"] for name in
            ("period_geometry", "area", "variant_geometry")], "period, area and variant must retain independent source cells"
    reopened = directory / "raster_area_reopened.hwpx"
    HwpxDocument.open(path).save_to_path(reopened)
    assert etree.tostring(package(reopened)) == etree.tostring(section), "masthead changed after native reopen/save"
    try:
        import rhwp
    except ImportError:
        pass
    else:
        parsed = rhwp.parse(str(reopened))
        assert parsed.page_count == 1 and bytes(parsed.render_png(0)), "native masthead failed to render"


def main():
    with fixture() as document:
        page = document[0]
        assert not measure_source_masthead(page, 220), "image area requires an independently verified hint"
        assert not measure_source_masthead(page, 220, area_hint="수학 영역"), "wrong subject hint accepted"
        meta = measure_source_masthead(page, 220, area_hint="영어 영역")
        assert meta["area"]["raster_geometry"]
        assert all(abs(a - b) < .01 for a, b in zip(meta["area"]["bbox_pt"], (340, 120, 502, 162)))
        assert meta["title"]["text"] == "2026학년도 시험 문제지"
        assert meta["period_geometry"]["text"] == "제3 교시"
        assert meta["variant_geometry"]["text"] == "홀수형"
        assert meta["bottom_rule"]["y_pt"] == 215
        with tempfile.TemporaryDirectory(prefix="english_raster_masthead_") as temporary:
            native_header(meta, Path(temporary))
    for options in ({"duplicate": True}, {"period": False}, {"variant": False},
                    {"title": False}, {"prose_image": True}):
        with fixture(**options) as document:
            assert not measure_source_masthead(document[0], 220, area_hint="영어 영역"), options
    source = ROOT / "data/external_exam_qa/2026_csat/문제지/영어/영어.pdf"
    if source.is_file():
        with fitz.open(source) as document:
            page = document[0]
            assert not measure_source_masthead(page, 229)
            real = measure_source_masthead(page, 229, area_hint="영어 영역")
            assert real["area"]["text"] == "영어 영역" and real["area"]["raster_geometry"]
            expected = (340.32, 154.02, 502.08, 195.30)
            assert all(abs(a - b) < .01 for a, b in zip(real["area"]["bbox_pt"], expected))
            assert real["title"]["text"] == "2026학년도 대학수학능력시험 문제지"
            assert real["period_geometry"]["text"] == "제3 교시"
            assert real["variant_geometry"]["text"] == "홀수형"
            assert abs(real["bottom_rule"]["y_pt"] - 218.281) < .01
        with tempfile.TemporaryDirectory(prefix="csat_raster_masthead_") as temporary:
            native_header(real, Path(temporary))
        print("PASS: actual CSAT English image-area bbox, original title/period/variant/rule")
    else:
        print("SKIP: actual CSAT source missing; portable native-header regression passed")
    print("RASTER_ENGLISH_MASTHEAD_OK: measured native text, independent fields, ambiguity guards, reopen/render")


if __name__ == "__main__":
    main()
