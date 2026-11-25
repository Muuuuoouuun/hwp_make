"""Download names use the full uploaded basename, including across retries."""
from urllib.parse import unquote

import pytest

from app.web_main import converted_download_name, create_app
from app.web_worker import Worker
from scripts.verify_guest_beta import ORIGIN, client, pdf, submit, quota


@pytest.mark.parametrize(("name","fmt","expected"), [
    ("분수 연습.v2.PDF","hwpx","분수 연습.v2_변환.hwpx"),
    ("C:\\sample\\관찰.초안.DOCX","hwpx","관찰.초안_변환.hwpx"),
    ("CON.note.pdf","docx","_CON.note_변환.docx"),
    ("예시?초안.pdf","hwpx","예시_초안_변환.hwpx"),
    ("한" * 201 + ".PDF","hwpx","한" * 62 + "_변환.hwpx"),
])
def test_converted_name(name, fmt, expected):
    result = converted_download_name(name, fmt)
    assert result == expected and len(result.encode()) <= 200


def test_long_original_is_separate_from_result(tmp_path):
    app = create_app(tmp_path, worker_enabled=False, origin=ORIGIN)
    store = app.state.store
    name = "a" * 195 + " 수업.v2.PDF"
    assert len(name) == 205
    with client(app) as c:
        c.post("/api/guest").raise_for_status()
        data = pdf()
        rejected = submit(c,"wrong-format",data,name=name+".xls")
        assert rejected.status_code == 400 and quota(c)["remaining"] == 3
        response = submit(c,"long-original",data,name=name)
        response.raise_for_status()
        job = response.json()["job"]
        assert job["filename"] == name
        Worker(store).run(store.claim())
        url = f"/api/jobs/{job['id']}/download"
        result, source = c.get(url), c.get(url+"?source=true")
        result.raise_for_status()
        source.raise_for_status()
        assert unquote(result.headers["content-disposition"]).endswith(converted_download_name(name,"hwpx"))
        assert unquote(source.headers["content-disposition"]).endswith(name)
        assert source.content == data
        assert c.get(url).content == result.content and quota(c)["used"] == 1
