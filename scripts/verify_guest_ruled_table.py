"""End-to-end worker regression for an unnumbered handout and unsupported artwork."""
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import fitz
import pytest

from app.web_main import create_app
from app.web_worker import Worker
from scripts.verify_guest_beta import ORIGIN, client, quota, submit


def worksheet(include_diagonal: bool) -> bytes:
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((50, 90), "Measure the change in temperature.")
        page.insert_text((50, 131), "T = 2x + 6")
        for x in (320, 390, 460):
            page.draw_line((x, 100), (x, 160))
        for y in (100, 120, 140, 160):
            page.draw_line((320, y), (460, y))
        for x, y, text in [(324,115,"Time"), (394,115,"Temp"), (324,135,"AM"),
                           (394,135,"12"), (324,155,"PM")]:
            page.insert_text((x, y), text, fontsize=9)
        if include_diagonal:
            page.draw_line((100, 180), (150, 190))
        return document.tobytes()


@pytest.mark.parametrize("include_diagonal", [False, True])
def test_unnumbered_table_is_editable_or_fails_without_charge(tmp_path, include_diagonal):
    app = create_app(tmp_path, worker_enabled=False, origin=ORIGIN)
    with client(app) as browser:
        browser.post("/api/guest").raise_for_status()
        response = submit(browser, "grid-test", worksheet(include_diagonal))
        response.raise_for_status()
        job = response.json()["job"]["id"]
        worker = Worker(app.state.store)
        worker.run(worker.store.claim())
        output = browser.get(f"/api/jobs/{job}/download")
        if include_diagonal:
            assert browser.get(f"/api/jobs/{job}").json()["job"]["state"] == "failed"
            assert output.status_code == 409 and quota(browser)["remaining"] == 3
            return
        assert output.status_code == 200 and quota(browser)["remaining"] == 2
        with ZipFile(BytesIO(output.content)) as package:
            section = ET.fromstring(package.read("Contents/section0.xml"))
        assert not section.findall(".//{*}pic")
        native = [t for t in section.iterfind(".//{*}tbl") if t.get("rowCnt") == "3" and t.get("colCnt") == "2"]
        assert len(native) == 1
        cells = [["".join(t.text or "" for t in cell.iterfind(".//{*}t"))
                  for cell in row.findall("{*}tc")] for row in native[0].findall("{*}tr")]
        assert cells == [["Time", "Temp"], ["AM", "12"], ["PM", ""]]
        assert "T = 2x + 6" in "".join(section.itertext())
