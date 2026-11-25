"""Guest conversion keeps each printed equation editable as a single object."""
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas

from app.math_text import split_math_text
from app.web_main import create_app
from app.web_worker import Worker
from scripts.verify_guest_beta import ORIGIN, client, submit


def test_editable_equations_on_either_side_of_prose(tmp_path):
    data = BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    pdf = Canvas(data, pagesize=A4)
    for x, y, size, text in [
        (52, 765, 22, "수식 연습"),
        (52, 689, 15, "1. 값을 계산하세요."), (312, 689, 15, "2. 식을 비교하세요."),
        (52, 646, 13, "V = 2x^2 / 3 + 6"), (312, 646, 12, "a = 2x + 1 이고 b = 3y + 4"),
    ]:
        pdf.setFont("HYSMyeongJo-Medium", size)
        pdf.drawString(x, y, text)
    pdf.save()

    app = create_app(tmp_path, worker_enabled=False, origin=ORIGIN)
    with client(app) as guest:
        guest.post("/api/guest").raise_for_status()
        submitted = submit(guest, "equation-groups", data.getvalue())
        submitted.raise_for_status()
        job_id = submitted.json()["job"]["id"]
        worker = Worker(app.state.store)
        worker.run(worker.store.claim())
        download = guest.get(f"/api/jobs/{job_id}/download")
        download.raise_for_status()
        with ZipFile(BytesIO(download.content)) as archive:
            section = ET.fromstring(archive.read("Contents/section0.xml"))
    assert [n.text for n in section.iterfind(".//{*}equation/{*}script")] == [
        "V = 2x^{2} / 3 + 6", "a = 2x + 1", "b = 3y + 4"]
    runs = [n.text.strip() for n in section.iter() if n.text and
            n.tag.rsplit("}", 1)[-1] in {"script", "t"}]
    index = runs.index("a = 2x + 1")
    assert runs[index:index+3] == ["a = 2x + 1", "이고", "b = 3y + 4"]


def test_coefficient_is_complete_and_words_stay_outside():
    assert split_math_text("t = 2.5x(t) + 30") == [("t = 2.5x(t) + 30", True)]
    assert split_math_text("A = b x h") == [("A = b x h", True)]
    assert split_math_text("t = 30minutes") == [("t = 30", True), ("minutes", False)]
