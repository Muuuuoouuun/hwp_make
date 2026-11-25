"""Two-page guest worksheets with merged cells and an unsupported second page."""
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import fitz
import pytest

from app.web_main import create_app
from app.pdf_running_headings import measure_second_sheet_heading
from app.web_worker import Worker
from scripts.verify_guest_beta import ORIGIN, client, quota, submit


@pytest.mark.parametrize("subtitle, expected", [(False, "Autumn record"), (True, None)])
def test_only_one_prominent_following_title(subtitle, expected):
    with fitz.open() as doc:
        for title in ["Spring record", "Autumn record"]:
            page = doc.new_page()
            page.insert_text((52, 80), title, fontsize=22)
            if subtitle and title == "Autumn record":
                page.insert_text((52, 105), "Another line")
        heading = measure_second_sheet_heading(doc[0], 130, doc[1], 130)
        assert (heading["text"] if heading else None) == expected


def handout(unexpected_art):
    with fitz.open() as doc:
        for i in range(2):
            page = doc.new_page()
            page.insert_text((50, 50), ["Spring record", "Autumn record"][i], fontsize=18)
            x, other = (320, 50) if i == 0 else (50, 320)
            page.insert_text((other, 125), ["First calculation", "Next calculation"][i])
            for c in range(4):
                top = 120 if (i == 0 and c == 1) else 100
                page.draw_line((x + c * 50, top), (x + c * 50, 160))
            for r in range(4):
                left = x + 50 if (i == 1 and r == 2) else x
                page.draw_line((left, 100 + r * 20), (x + 150, 100 + r * 20))
            for c, r, label in [(0, 0, "Header"), (2, 0, "Count"), (0, 1, "Summer"),
                                (2, 1, str(i + 1))]:
                page.insert_text((x + c * 50 + 3, 114 + r * 20), label, fontsize=8)
            if unexpected_art and i == 1:
                page.draw_line((180, 200), (200, 210))
        return doc.tobytes()


@pytest.mark.parametrize("unexpected_art", [False, True])
def test_guest_multipage_table(tmp_path, unexpected_art):
    app = create_app(tmp_path, worker_enabled=False, origin=ORIGIN)
    with client(app) as browser:
        browser.post("/api/guest").raise_for_status()
        result = submit(browser, "two-page-grid", handout(unexpected_art))
        result.raise_for_status()
        job = result.json()["job"]["id"]
        worker = Worker(app.state.store)
        worker.run(worker.store.claim())
        download = browser.get(f"/api/jobs/{job}/download")
        if unexpected_art:
            assert browser.get(f"/api/jobs/{job}").json()["job"]["state"] == "failed"
            assert download.status_code == 409 and quota(browser)["remaining"] == 3
            return
        download.raise_for_status()
        assert quota(browser)["remaining"] == 2
        with ZipFile(BytesIO(download.content)) as package:
            section = ET.fromstring(package.read("Contents/section0.xml"))
        assert not section.findall(".//{*}pic")
        tables = [t for t in section.iterfind(".//{*}tbl") if t.find(".//{*}tbl") is None]
        assert len(tables) == 2
        first_row = tables[0].find("{*}tr").findall("{*}tc")
        assert len(first_row) == 2
        assert "".join(first_row[1].itertext()) == "Count"
        for table, key, spans, value in [(tables[0], (0, 0), (1, 2), "Header"),
                                        (tables[1], (1, 0), (2, 1), "Summer")]:
            for cell in table.iterfind("{*}tr/{*}tc"):
                addr = cell.find("{*}cellAddr")
                if (int(addr.get("rowAddr")), int(addr.get("colAddr"))) != key:
                    continue
                span = cell.find("{*}cellSpan")
                assert (int(span.get("rowSpan")), int(span.get("colSpan"))) == spans
                assert "".join(t.text or "" for t in cell.iterfind(".//{*}t")) == value
                break
            else:
                pytest.fail(f"Missing source cell {key}")
        text = "".join(section.itertext())
        markers = ["Spring record", "First calculation", "Header", "Autumn record", "Next calculation"]
        assert [text.index(m) for m in markers] == sorted(text.index(m) for m in markers)
        assert len(section.findall(".//{*}p[@pageBreak='1']")) == 1
