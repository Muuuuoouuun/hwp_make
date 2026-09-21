"""Source geometry, not proximity alone, must authorize prose/figure sideflow."""

from copy import deepcopy
from pathlib import Path
import sys
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pdf_question_sideflow import restore_question_sideflow, HP, HH


def fixture():
    section = etree.Element("section")
    etree.SubElement(section, HP + "pagePr", width="59528")
    table = etree.SubElement(section, HP + "tbl", id="100")
    etree.SubElement(table, HP + "sz", width="22000", height="1000")
    etree.SubElement(table, HP + "pos", treatAsChar="1")
    row = etree.SubElement(table, HP + "tr")
    cell = etree.SubElement(row, HP + "tc")
    etree.SubElement(cell, HP + "subList")
    etree.SubElement(cell, HP + "cellAddr")
    etree.SubElement(cell, HP + "cellSpan")
    etree.SubElement(cell, HP + "cellSz")
    etree.SubElement(cell, HP + "cellMargin")
    header = etree.Element("header")
    border = etree.SubElement(header, HH + "borderFill", id="1")
    for edge in ("left", "right", "top", "bottom"):
        etree.SubElement(border, HH + edge + "Border", type="NONE")
    p = etree.SubElement(section, HP + "p", id="101", paraPrIDRef="0")
    run = etree.SubElement(p, HP + "run", charPrIDRef="0")
    etree.SubElement(run, HP + "t").text = (
        "1. Read the measured evidence and explain the result in one continuous paragraph."
    )
    picture = etree.SubElement(section, HP + "p", id="102", paraPrIDRef="0")
    pic = etree.SubElement(etree.SubElement(picture, HP + "run"), HP + "pic", id="103")
    etree.SubElement(pic, HP + "sz", width="9000", height="8000")
    meta = {
        "question_group": "v1:q01",
        "question_group_start": True,
        "source_page": 1,
        "source_column": 1,
        "column_left_pt": 20,
        "source_page_width_pt": 842,
        "source_typography": {"font_size_pt": 11, "line_spacing_pt": 16},
    }
    layouts = [
        dict(deepcopy(meta), source_bbox_pt=[20, 100, 190, 150]),
        dict(deepcopy(meta), source_bbox_pt=[200, 100, 330, 210]),
    ]
    layouts[1]["question_group_start"] = False
    return section, [p, picture], layouts, header


def check():
    section, ps, ls, header = fixture()
    original = ps[:]
    text = "".join(section.itertext())
    out, meta, count = restore_question_sideflow(section, ps, ls, header, 22000)
    assert count == 1 and len(out) == 1
    assert "".join(section.itertext()) == text
    cells = out[0].findall(".//" + HP + "tc")
    assert cells[0].find(HP + "subList/" + HP + "p") is original[0]
    assert cells[1].find(HP + "subList/" + HP + "p") is original[1]
    assert len(out[0].findall(".//" + HP + "tbl")) == 1
    assert meta[0]["question_group_start"] and meta[0]["source_sideflow"]
    assert int(cells[0].find(HP + "cellMargin").get("right")) > 0
    for kind in (
        "horizontal_overlap",
        "no_vertical_overlap",
        "another_question",
        "intervening_content",
    ):
        section, ps, ls, header = fixture()
        if kind == "horizontal_overlap":
            ls[0]["source_bbox_pt"][2] = 220
        elif kind == "no_vertical_overlap":
            ls[0]["source_bbox_pt"] = [20, 20, 190, 80]
        elif kind == "another_question":
            ls[1]["question_group"] = "v1:q02"
        else:
            extra = etree.Element(HP + "p", id="104")
            section.insert(section.index(ps[1]), extra)
            ps.insert(1, extra)
            ls.insert(1, dict(ls[0], source_bbox_pt=[20, 155, 330, 165]))
        out, meta, count = restore_question_sideflow(section, ps, ls, header, 22000)
        assert count == 0, kind
    print(
        "NATIVE_QUESTION_SIDEFLOW_OK: native nodes preserved; overlapping, separate, cross-question and intervening content rejected"
    )


if __name__ == "__main__":
    check()
