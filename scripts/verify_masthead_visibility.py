"""Paint-order evidence removes covered headers without deleting visible text."""
from pathlib import Path
import sys

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pdf_masthead_visibility import visible_masthead_lines
from app.pdf_masthead_typography import measure_source_page_masthead
from app.pdf_masthead_sections import _coherent_running


def texts(page):
    return ["".join(span["text"] for span in line["spans"])
            for line in visible_masthead_lines(page, 220)]


def cover_case(*, before=False, opacity=1, partial=False, triangle=False):
    document = fitz.open()
    page = document.new_page(width=842, height=1191)
    rectangle = fitz.Rect(90, 70, 160 if not partial else 103, 110)
    def cover():
        if triangle:
            shape = page.new_shape()
            shape.draw_polyline([(90, 70), (160, 70), (160, 110), (90, 70)])
            shape.finish(fill=(1, 1, 1), fill_opacity=opacity)
            shape.commit()
        else:
            page.draw_rect(rectangle, fill=(1, 1, 1), fill_opacity=opacity)
    if before:
        cover()
    page.insert_text((100, 100), "13", fontsize=25)
    if not before:
        cover()
    page.insert_text((300, 100), "Visible replacement", fontsize=19)
    return document


with cover_case() as document:
    assert texts(document[0]) == ["Visible replacement"]
for options in ({"before": True}, {"opacity": .5}, {"partial": True}, {"triangle": True}):
    with cover_case(**options) as document:
        assert "13" in texts(document[0]), options

with fitz.open() as document:
    page = document.new_page(width=842, height=1191)
    page.insert_text((740, 100), "13", fontsize=25)
    page.insert_text((350, 100), "영어 영역", fontname="korea", fontsize=25)
    page.draw_rect(fitz.Rect(80, 60, 780, 215), fill=(1, 1, 1))
    page.insert_text((150, 100), "2026학년도 시험 문제지", fontname="korea", fontsize=19)
    page.insert_text((735, 100), "1", fontsize=25)
    page.insert_text((90, 150), "제3 교시", fontname="korea", fontsize=19)
    page.insert_text((350, 160), "영어 영역", fontname="korea", fontsize=25)
    page.draw_line((85, 215), (755, 215), width=1)
    meta = measure_source_page_masthead(page, 220, area_hint="영어 영역")
    assert meta["kind"] == "full" and meta["page_number"]["text"] == "1", meta
    assert meta["area"]["baseline_pt"] == 160, meta

with fitz.open() as document:
    page = document.new_page(width=842, height=1191)
    page.insert_text((90, 155), "2", fontsize=25)
    page.insert_text((350, 155), "영어 영역", fontname="korea", fontsize=25)
    page.insert_text((680, 155), "고2", fontname="korea", fontsize=19)
    page.draw_line((85, 215), (755, 215), width=1)
    meta = measure_source_page_masthead(page, 220, area_hint="영어 영역")
    assert meta["kind"] == "running" and meta["grade_geometry"]["text"] == "고2", meta
    assert _coherent_running([meta])
    page.insert_text((680, 185), "고1", fontname="korea", fontsize=19)
    assert not measure_source_page_masthead(page, 220, area_hint="영어 영역"), "Ambiguous grade accepted"

print("MASTHEAD_VISIBILITY_OK: opaque rectangle/order proof, partial/transparent/path guards, native grade headers")
