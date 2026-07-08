"""절대좌표 글상자 타당성 테스트.

PDF→편집HWPX(같은 레이아웃) 를 위해 필요한 핵심 원시기능:
각 요소를 '페이지 절대좌표'에 편집 가능한 글상자로 배치할 수 있는가?
알려진 3좌표에 글상자를 놓고 한컴 뷰어에서 위치/텍스트를 눈으로 확인한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "_vendor"))

from lxml import etree  # noqa: E402
from hwpx import HwpxDocument  # noqa: E402

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
MM = 7200.0 / 25.4  # 1mm in HWPUNIT


def _q(tag: str) -> str:
    return f"{{{HP}}}{tag}"


def add_text_box(doc, x_mm: float, y_mm: float, w_mm: float, h_mm: float,
                 text: str, *, border: bool = True) -> None:
    """페이지 절대좌표(mm)에 편집 가능한 글상자를 놓는다."""
    w = int(w_mm * MM)
    h = int(h_mm * MM)
    sh = doc.add_rectangle(width=w, height=h, treat_as_char=False,
                           line_width=("283" if border else "0"))
    el = sh.element
    # 크기
    for tag in ("orgSz", "curSz"):
        node = el.find(_q(tag))
        if node is not None:
            node.set("width", str(w)); node.set("height", str(h))
    sz = el.find(_q("sz"))
    if sz is not None:
        sz.set("width", str(w)); sz.set("height", str(h))
    # 위치: 페이지(PAPER) 기준 절대 오프셋
    pos = el.find(_q("pos"))
    if pos is not None:
        pos.set("vertRelTo", "PAPER"); pos.set("horzRelTo", "PAPER")
        pos.set("vertAlign", "TOP"); pos.set("horzAlign", "LEFT")
        pos.set("vertOffset", str(int(y_mm * MM)))
        pos.set("horzOffset", str(int(x_mm * MM)))
    # 편집 텍스트: drawText > subList > p > run > t
    draw = etree.SubElement(el, _q("drawText"))
    draw.set("lastWidth", str(w)); draw.set("name", ""); draw.set("editable", "1")
    tm = etree.SubElement(draw, _q("textMargin"))
    for k in ("left", "right", "top", "bottom"):
        tm.set(k, "141")
    sub = etree.SubElement(draw, _q("subList"))
    sub.set("id", ""); sub.set("textDirection", "HORIZONTAL")
    sub.set("lineWrap", "BREAK"); sub.set("vertAlign", "TOP")
    sub.set("linkListIDRef", "0"); sub.set("linkListNextIDRef", "0")
    sub.set("textWidth", "0"); sub.set("textHeight", "0"); sub.set("metaTag", "")
    p = etree.SubElement(sub, _q("p"))
    p.set("paraPrIDRef", "0"); p.set("styleIDRef", "0")
    p.set("pageBreak", "0"); p.set("columnBreak", "0"); p.set("merged", "0")
    run = etree.SubElement(p, _q("run"))
    run.set("charPrIDRef", "0")
    t = etree.SubElement(run, _q("t"))
    t.text = text


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Desktop" / "위치테스트.hwpx"
    doc = HwpxDocument.new()
    add_text_box(doc, 30, 30, 60, 12, "① 좌상단 (30,30)mm")
    add_text_box(doc, 75, 140, 60, 12, "② 중앙 (75,140)mm")
    add_text_box(doc, 130, 250, 60, 12, "③ 우하단 (130,250)mm")
    doc.save(str(out))
    print("SAVED", out)
    # 검증
    doc2 = HwpxDocument.open(str(out))
    print("reopen OK, sections:", len(doc2.sections))


if __name__ == "__main__":
    main()
