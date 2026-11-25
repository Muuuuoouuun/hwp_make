"""Isolated guest acceptance; all PDF payloads and identities are synthetic."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import secrets
import zipfile

import fitz
from fastapi.testclient import TestClient

from app.web_main import create_app
from app.web_worker import Worker

ORIGIN = "http://127.0.0.1:8789"
HEADERS = {"X-HWP-Request": "1", "Origin": ORIGIN}
COOKIE = "hwp_guest_beta"


def pdf():
    with fitz.open() as doc:
        p = doc.new_page()
        p.insert_text((60, 90), "1. What is 2 + 2?", fontsize=12)
        p.insert_text((60, 120), "1) 3    2) 4    3) 5", fontsize=12)
        return doc.tobytes()


def client(app, **kwargs):
    return TestClient(app, base_url=ORIGIN, headers=HEADERS, **kwargs)


def submit(c, key, data, fmt="hwpx", name="synthetic.pdf"):
    return c.post("/api/jobs", files={"file": (name, data)},
                  data={"output_format":fmt},headers={"Idempotency-Key":key})


def quota(c):
    return c.get("/api/jobs").json()["quota"]


def test_actual_guest_workflow_and_private_artifacts(tmp_path):
    app = create_app(tmp_path, worker_enabled=False, origin=ORIGIN)
    store = app.state.store
    launch_token = store.bootstrap()
    with client(app) as a, client(app) as b, client(app) as no_cookie, client(app) as account:
        res = a.post("/api/guest")
        assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
        assert "HttpOnly" in res.headers["set-cookie"] and "SameSite=strict" in res.headers["set-cookie"]
        assert res.json() == {"user":{"guest":True,"name":"게스트"},
                              "quota":{"limit":3,"used":0,"pending":0,"remaining":3}}
        assert a.post("/api/guest").headers.get("set-cookie") is None
        assert b.post("/api/guest").status_code == 200
        assert a.get("/api/me").status_code == 401
        assert a.get("/api/bug-reports").status_code == 401
        assert no_cookie.get("/api/jobs").status_code == 401
        assert no_cookie.post("/api/guest",headers={"Origin":"https://invalid.example"}).status_code == 403
        password = secrets.token_urlsafe(22)
        assert account.post("/api/setup",json={"token":launch_token,"email":"example@example.test",
                          "name":"Synthetic","password":password}).status_code == 200
        assert account.get("/api/me").status_code == 200
        assert account.post("/api/guest").status_code == 409
        assert submit(a,"wrong-kind",b"no",name="synthetic.docx").status_code == 400
        assert submit(a,"wrong-type",pdf(),fmt="docx").status_code == 400
        assert submit(a,"invalid-pdf",b"this is not a PDF").status_code == 400
        assert quota(a)["remaining"]==3
        pending=submit(a,"cancelled-example",pdf()).json()["job"]["id"]
        assert quota(a)["remaining"]==2
        assert a.post(f"/api/jobs/{pending}/cancel").status_code==200
        assert quota(a)["remaining"]==3
        pending=submit(a,"failed-worker-example",pdf()).json()["job"]["id"]
        claimed=store.claim()
        assert claimed["id"]==pending
        store.finish(pending,claimed["attempt"],"failed",error="Synthetic failed worker")
        assert quota(a)["remaining"]==3
        for n in range(3):
            key=f"success-example-{n}"
            payload=pdf()
            res=submit(a,key,payload)
            assert res.status_code==202,res.text
            ident=res.json()["job"]["id"]
            replay=submit(a,key,payload)
            assert replay.status_code==202 and replay.json()["job"]["id"]==ident
            assert quota(a)["pending"]==1
            Worker(store).run(store.claim())
            out=a.get(f"/api/jobs/{ident}/download")
            assert out.status_code==200
            with zipfile.ZipFile(BytesIO(out.content)) as z:
                assert z.testzip() is None and "Contents/content.hpf" in z.namelist()
            assert quota(a)["used"]==n+1 and quota(a)["pending"]==0
            for url in [f"/api/jobs/{ident}", f"/api/jobs/{ident}/download",
                        f"/api/jobs/{ident}/download?source=true"]:
                assert b.get(url).status_code==404
                assert account.get(url).status_code==404
                assert no_cookie.get(url).status_code==401
            assert b.delete(f"/api/jobs/{ident}").status_code==404
            assert account.delete(f"/api/jobs/{ident}").status_code==404
        assert submit(a,"fourth-conversion",pdf()).status_code==429
        assert a.delete(f"/api/jobs/{ident}").status_code==200
        assert a.get(f"/api/jobs/{ident}/download").status_code==404
        assert submit(a,"fourth-after-delete",pdf()).status_code==429
        assert quota(a)=={"limit":3,"used":3,"pending":0,"remaining":0}
        assert quota(b)["remaining"]==3


def test_concurrent_reservations_and_guest_expiry(tmp_path):
    app=create_app(tmp_path,worker_enabled=False,origin=ORIGIN)
    with client(app) as a:
        assert a.post("/api/guest").status_code==200
        token=a.cookies.get(COOKIE)
        payload=pdf()
        def post(n):
            with client(app,cookies={COOKIE:token}) as c:
                return submit(c,f"parallel-{n}",payload).status_code
        with ThreadPoolExecutor(max_workers=5) as pool:
            assert sorted(pool.map(post,range(5)))==[202,202,202,429,429]
        assert quota(a)=={"limit":3,"used":0,"pending":3,"remaining":0}
        with app.state.store.connect() as db:
            db.execute("UPDATE guests SET expires=0")
        assert a.get("/api/jobs").status_code==401
        assert a.post("/api/guest").status_code==200 and a.cookies.get(COOKIE)!=token
        assert a.get("/api/jobs").json()["items"]==[]
