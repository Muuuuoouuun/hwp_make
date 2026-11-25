"""A measured title can only redistribute the empty lead paragraph's space."""
import pytest
from lxml import etree

from app.pdf_masthead_typography import HH, HP, _position_first_title

HC = "{http://www.hancom.co.kr/hwpml/2011/core}"


@pytest.mark.parametrize("target,lead_text,applied", [(6050, "", True), (5000, "", False),
                                                     (8500, "", False), (6050, "note", False)])
def test_title_does_not_move_body_or_visible_lead(target, lead_text, applied):
    header = etree.Element("header")
    props = etree.SubElement(header, HH + "paraProperties", itemCnt="2")
    lead_style = etree.SubElement(props, HH + "paraPr", id="0")
    etree.SubElement(lead_style, HH + "lineSpacing", type="PERCENT", value="160")
    title_style = etree.SubElement(props, HH + "paraPr", id="1")
    margin = etree.SubElement(title_style, HH + "margin")
    after = etree.SubElement(margin, HC + "next", value="100")
    etree.SubElement(header, HH + "charPr", id="0", height="1000")
    section = etree.Element("section")
    lead = etree.SubElement(section, HP + "p", paraPrIDRef="0")
    run = etree.SubElement(lead, HP + "run", charPrIDRef="0")
    secpr = etree.SubElement(run, HP + "secPr")
    page = etree.SubElement(secpr, HP + "pagePr")
    etree.SubElement(page, HP + "margin", top="5650", header="0")
    etree.SubElement(run, HP + "t").text = lead_text
    title = etree.SubElement(section, HP + "p", paraPrIDRef="1")
    _position_first_title(section, header, title, title_style, page, target)
    if applied:
        spacing = props.find(HH + "paraPr[@id='2']/" + HH + "lineSpacing")
        assert spacing.get("type") == "FIXED"
        assert int(spacing.get("value")) == 400
        assert int(spacing.get("value")) + int(after.get("value")) == 1600 + 100
        assert lead.get("paraPrIDRef") == "2"
    else:
        assert len(props) == 2 and after.get("value") == "100"
        assert lead.get("paraPrIDRef") == "0"
