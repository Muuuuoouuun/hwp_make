"""Synthetic guest acceptance checks. Run with pytest on the isolated web app."""
import io
import os
import zipfile
from unittest.mock import patch

import fitz
from docx import Document
from scripts.verify_guest_beta import ORIGIN, client, pdf, submit, quota
from app.web_main import create_app
from app.web_worker import Worker


def test_valid_word_shared_quota_and_false_extensions(tmp_path):
    app = create_app(tmp_path, worker_enabled=False, origin=ORIGIN)
    store = app.state.store
    with client(app) as browser:
        browser.post("/api/guest").raise_for_status()
        package = io.BytesIO()
        with zipfile.ZipFile(package, "w") as workbook:
            workbook.writestr("xl/workbook.xml", "<workbook/>")
            workbook.writestr("[Content_Types].xml", "<Types/>")
        for name in ("worksheet.xls", "worksheet.pdf", "worksheet.docx"):
            rejected = submit(browser, "invalid-spreadsheet", package.getvalue(), name=name)
            assert rejected.status_code == 400
        assert quota(browser)["remaining"] == 3
        doc = Document()
        doc.add_paragraph("1. 분수의 합을 구하세요.")
        payload = io.BytesIO()
        doc.save(payload)
        job = submit(browser,"sample-docx",payload.getvalue(),name="lesson.docx").json()["job"]
        Worker(store).run(store.claim())
        url = f"/api/jobs/{job['id']}/download"
        result = browser.get(url)
        assert result.status_code == 200
        with zipfile.ZipFile(io.BytesIO(result.content)) as output:
            assert "분수의 합을 구하세요." in output.read("Contents/section0.xml").decode()
        replay = submit(browser,"sample-docx",payload.getvalue(),name="lesson.docx")
        assert replay.json()["job"]["id"] == job["id"]
        assert browser.get(url).content == result.content
        assert browser.get(url+"?source=true").content == payload.getvalue()
        assert quota(browser) == {"limit":3,"used":1,"pending":0,"remaining":2}
        stored = next(store.job_dir(job["id"]).glob("*/output.hwpx"))
        stored.write_bytes(result.content[:100])
        assert browser.get(url).status_code == 404
        stored.unlink()
        assert browser.get(url).status_code == 404


def test_unnumbered_text_and_scan_only_pdf(tmp_path):
    app = create_app(tmp_path, worker_enabled=False, origin=ORIGIN)
    with client(app) as browser, fitz.open() as document:
        browser.post("/api/guest").raise_for_status()
        first = document.new_page()
        first.draw_rect(fitz.Rect(60, 80, 250, 120), fill=(0.2, 0.3, 0.4))
        assert submit(browser, "no-text-layer", document.tobytes()).status_code == 400
        assert quota(browser)["remaining"] == 3
    with client(app) as browser, fitz.open() as document:
        browser.post("/api/guest").raise_for_status()
        for text in ("Observe the water.", "Record your findings."):
            document.new_page().insert_text((60, 90), text)
        response = submit(browser, "unnumbered-handout", document.tobytes())
        response.raise_for_status()
        job_id = response.json()["job"]["id"]
        worker = Worker(app.state.store)
        worker.run(app.state.store.claim())
        result = browser.get(f"/api/jobs/{job_id}/download")
        assert result.status_code == 200
        with zipfile.ZipFile(io.BytesIO(result.content)) as package:
            body = package.read("Contents/section0.xml").decode()
            assert "Observe the water." in body and "Record your findings." in body
            assert 'pageBreak="1"' in body
        assert browser.get(f"/api/jobs/{job_id}").json()["job"]["result"]["source_pages"] == 2


def test_expiry_cleanup_and_locked_deletion(tmp_path):
    app = create_app(tmp_path, worker_enabled=False, origin=ORIGIN)
    store = app.state.store
    worker = Worker(store)
    with client(app) as a, client(app) as b:
        a.post("/api/guest").raise_for_status()
        b.post("/api/guest").raise_for_status()
        source = pdf()
        job = submit(a,"synthetic-expiry",source).json()["job"]["id"]
        worker.run(store.claim())
        other = submit(b,"synthetic-other",source).json()["job"]["id"]
        folder = store.job_dir(job)
        url = f"/api/jobs/{job}"
        original = folder/"source"
        assert a.get(url+"/download?source=true").content == source
        assert a.get(url+"/download").status_code == 200
        owner = store.authenticate_guest(a.cookies["hwp_guest_beta"])["id"]
        with store.connect() as db:
            db.execute("UPDATE guests SET expires=0 WHERE owner_id=?", (owner,))
        assert a.get(url+"/download").status_code == a.get(url+"/download?source=true").status_code == 401
        assert original.exists()  # access is revoked before the physical sweep
        assert b.get(url+"/download").status_code == 404
        worker.sweep()
        assert not folder.exists()
        with store.connect() as db:
            assert not db.execute("SELECT 1 FROM users WHERE id=?", (owner,)).fetchone()
            assert not db.execute("SELECT 1 FROM jobs WHERE id=?", (job,)).fetchone()
        other_url = f"/api/jobs/{other}"
        assert b.get(other_url+"/download?source=true").content == source
        assert b.post(other_url+"/cancel").status_code == 200
        other_folder = store.job_dir(other)
        if os.name == "nt":
            with (other_folder/"source").open("rb") as held:
                assert b.delete(other_url).status_code == 202
                assert b.get(other_url+"/download?source=true").status_code == 404
                assert held.read() == source
        else:
            with patch("app.web_store.shutil.rmtree", side_effect=PermissionError):
                assert b.delete(other_url).status_code == 202
                assert b.get(other_url+"/download?source=true").status_code == 404
        worker.sweep()
        assert not other_folder.exists()
        with store.connect() as db:
            assert tuple(db.execute("SELECT deleted,filename FROM jobs WHERE id=?", (other,)).fetchone()) == (2,"")
