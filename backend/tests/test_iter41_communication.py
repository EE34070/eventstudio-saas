"""Iter 41 — Communication étapes 1 à 5. QA uniquement, données TEST_M41 retirées à la fin."""
import io
import os
import subprocess
import uuid

import pytest
import requests
from dotenv import load_dotenv
from PIL import Image

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

API = "http://localhost:8001/api"
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
RUN = uuid.uuid4().hex[:6]
N = f"TEST_M41 {RUN}"
S = {}


def sess(role="admin"):
    x = requests.Session()
    x.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip().splitlines()[-1]
    return x


def img(color, fmt="JPEG", size=(900, 600)):
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, fmt)
    return b.getvalue()


def upload(s, base, name, data, body):
    u = s.post(base, json={"filename": name, "size": len(data)})
    assert u.status_code == 200, u.text
    u = u.json()
    for i in range(u["chunks"]):
        assert s.put(f"{base}/{u['id']}/chunks/{i}", data=data[i * u["chunk_size"]:(i + 1) * u["chunk_size"]], headers={"Content-Type": "application/octet-stream"}).status_code == 200
    return s.post(f"{base}/{u['id']}/complete", json=body)


@pytest.fixture(scope="module")
def s():
    x = sess()
    ev = x.post(f"{API}/events", json={"title": f"{N} Mariage", "type": "Mariage", "start": "2026-10-10T16:00", "end": "2026-10-11T02:00"})
    assert ev.status_code == 200, ev.text
    S["ev"] = ev.json()["id"]
    yield x
    rx = {"$regex": f"^{N}"}
    aids = list(DB.media_assets.find({"org_id": QA, "$or": [{"event_id": S["ev"]}, {"filename": rx}]}))
    fids = [a[k][5:] for a in aids for k in ("file_ref", "thumb_ref") if a.get(k)]
    DB.files.update_many({"org_id": QA, "id": {"$in": fids}}, {"$set": {"is_deleted": True}})
    DB.media_assets.delete_many({"org_id": QA, "id": {"$in": [a["id"] for a in aids]}})
    rids = [r["id"] for r in DB.media_requests.find({"org_id": QA, "event_id": S["ev"]})]
    DB.tasks.delete_many({"org_id": QA, "source_ref": {"$in": [f"comm-drop:{r}" for r in rids] + [f"comm-post:{p}" for p in S.get("posts", [])]}})
    DB.media_requests.delete_many({"org_id": QA, "event_id": S["ev"]})
    DB.comm_posts.delete_many({"org_id": QA, "title": rx})
    DB.comm_events.delete_many({"org_id": QA, "event_id": S["ev"]})
    DB.contacts.delete_many({"org_id": QA, "last_name": rx})
    DB.events.delete_many({"org_id": QA, "id": S["ev"], "title": rx})
    if S.get("settings") is None:
        DB.comm_settings.delete_many({"org_id": QA})
    else:
        DB.comm_settings.replace_one({"org_id": QA}, S["settings"])


def test_overview_settings_rights(s):
    S["settings"] = DB.comm_settings.find_one({"org_id": QA})
    o = s.get(f"{API}/communication/overview").json()
    assert [b["name"] for b in o["brands"]] == ["Exclusivity Events", "Le Frenchie", "Exclusivity Music"] and o["reminder_days"] == [3, 14, 30, 45] or S["settings"]
    assert o["sending"] is False and {c["key"] for c in o["connectors"]} == {"meta", "canva", "stats"} and o["video"] is True
    r = s.put(f"{API}/communication/settings", json={"brands": [{"id": "le_frenchie", "handle": "https://instagram.com/lefrenchie.dj/", "hashtags": ["#dj", "mariage"]}], "reminder_days": [3, 14, 30, 45], "request_message": ""})
    assert r.status_code == 200 and r.json()["brands"][1]["handle"] == "lefrenchie.dj" and r.json()["brands"][1]["hashtags"] == ["dj", "mariage"]
    assert s.put(f"{API}/communication/settings", json={"brands": [{"id": "x", "handle": ""}]}).status_code == 400
    assert s.put(f"{API}/communication/settings", json={"brands": [{"id": "le_frenchie", "handle": "pas valide !"}]}).status_code == 400
    for role in ("technicien", "commercial", "comptable"):
        t = sess(role)
        assert t.get(f"{API}/communication/overview").status_code == 403 and t.get(f"{API}/communication/media").status_code == 403, role
    assert requests.get(f"{API}/communication/media").status_code == 401
    me = s.get(f"{API}/me").json()
    assert "comms:manage" in me["perms"]


def test_media_import_dedupe_status(s):
    base = f"{API}/communication/uploads"
    red = img((200, 30, 30))
    r = upload(s, base, f"{N} a.jpg", red, {"event_id": S["ev"], "brand_id": "exclusivity_events"})
    assert r.status_code == 200, r.text
    a = r.json()
    S["a"] = a["id"]
    assert (a["kind"], a["width"], a["height"], a["duplicate"], a["status"]) == ("image", 900, 600, False, "bloque") and a["thumb_ref"] and len(a["blocked_reasons"]) == 2
    assert upload(s, base, f"{N} copie.jpg", red, {}).json()["duplicate"] is True
    assert upload(s, base, f"{N} faux.jpg", b"pas une image" * 10, {}).status_code == 400
    assert s.post(base, json={"filename": "x.exe", "size": 10}).status_code == 400
    big = os.urandom(6 * 1024 * 1024)
    assert upload(s, base, f"{N} gros.png", big, {}).status_code == 400
    import pillow_heif
    pillow_heif.register_heif_opener()
    hb = io.BytesIO()
    Image.new("RGB", (640, 480), (20, 90, 200)).save(hb, "HEIF")
    h = upload(s, base, f"{N} iphone.HEIC", hb.getvalue(), {}).json()
    assert h["content_type"] == "image/jpeg" and h["converted"] and h["width"] == 640
    assert s.get(f"{API}/files/{h['file_ref'][5:]}").content[:2] == b"\xff\xd8"
    vid = "/tmp/m41.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10", "-pix_fmt", "yuv420p", vid], check=True)
    v = upload(s, base, f"{N} clip.mp4", open(vid, "rb").read(), {"event_id": S["ev"]}).json()
    assert v["kind"] == "video" and 2.5 <= v["duration"] <= 3.5 and (v["width"], v["height"]) == (320, 240) and v["thumb_ref"]
    assert s.put(f"{API}/communication/media/{S['a']}", json={"rights": "ok"}).json()["blocked_reasons"] == ["Accord du client à demander"]
    e = s.put(f"{API}/communication/events/{S['ev']}", json={"brand_id": "exclusivity_events", "consent": "accorde", "embargo_date": "2099-01-01"})
    assert e.status_code == 200, e.text
    one = lambda: next(x for x in s.get(f"{API}/communication/media", params={"event_id": S["ev"]}).json() if x["id"] == S["a"])  # noqa: E731
    assert one()["blocked_reasons"] == ["Sous embargo jusqu'au 01/01/2099"]
    s.put(f"{API}/communication/events/{S['ev']}", json={"brand_id": "exclusivity_events", "consent": "accorde"})
    assert one()["status"] == "publiable"
    assert [x["id"] for x in s.get(f"{API}/communication/media", params={"event_id": S["ev"], "status": "publiable"}).json()] == [S["a"]]
    assert s.put(f"{API}/communication/media/bulk", json={"ids": [v["id"]], "patch": {"rights": "refused"}}).status_code == 200
    assert next(x for x in s.get(f"{API}/communication/media", params={"kind": "video", "event_id": S["ev"]}).json())["blocked_reasons"] == ["Droits refusés"]
    S["v"] = v["id"]


def test_requests_drop_page_no_send(s):
    r = s.post(f"{API}/communication/requests", json={"event_id": S["ev"], "name": f"{N} Photo", "email": "photo@example.com"})
    assert r.status_code == 200, r.text
    r = r.json()
    assert [x["date"] for x in r["reminders"]] == ["2026-10-13", "2026-10-24", "2026-11-09", "2026-11-24"] and r["status"] == "a_envoyer" and "share_hash" not in r
    sent = s.post(f"{API}/communication/requests/{r['id']}/send").json()
    assert sent["sent"] is False and sent["status"] == "demandee" and "Aucun e-mail" in sent["message"]
    pub = f"{API}/public/media-drop/{r['token']}"
    info = requests.get(pub).json()
    assert info["name"] == f"{N} Photo" and "10/10/2026" in info["event"] and "email" not in info and "org_id" not in info
    assert requests.get(f"{API}/public/media-drop/{'x' * 43}").status_code == 404
    d = upload(requests.Session(), f"{pub}/uploads", f"{N} depot.png", img((10, 200, 90), "PNG"), {"authorize": True, "handle": "@studio.photo"})
    assert d.status_code == 200 and d.json() == {"ok": True, "duplicate": False, "filename": f"{N} depot.png"}
    got = next(x for x in s.get(f"{API}/communication/media", params={"event_id": S["ev"]}).json() if x["filename"] == f"{N} depot.png")
    assert (got["rights"], got["author_handle"], got["source"], got["status"]) == ("ok", "studio.photo", "collecte", "publiable")
    row = next(x for x in s.get(f"{API}/communication/requests", params={"event_id": S["ev"]}).json() if x["id"] == r["id"])
    assert (row["status"], row["received"], row["handle"]) == ("recue", 1, "studio.photo")
    assert DB.tasks.count_documents({"org_id": QA, "source_ref": f"comm-drop:{r['id']}"}) == 1
    DB.media_requests.update_one({"id": r["id"], "org_id": QA}, {"$set": {"status": "demandee"}})
    import asyncio
    import sys
    sys.path.insert(0, "/app/backend")
    import routes_communication as rc
    asyncio.get_event_loop().run_until_complete(rc.tick())
    rem = DB.media_requests.find_one({"id": r["id"]})["reminders"]
    assert [x["status"] for x in rem] == ["sautee", "sautee", "sautee" if rem[3]["date"] <= rc.today() else "retenue", "retenue" if rem[3]["date"] <= rc.today() else "planifiee"] or [x["status"] for x in rem].count("retenue") == 1
    assert "envoyee" not in [x["status"] for x in rem]
    s.put(f"{API}/communication/requests/{r['id']}", json={"status": "close"})
    assert requests.get(pub).status_code == 410


def test_credits(s):
    c = s.post(f"{API}/contacts", json={"kind": "entreprise", "company": f"{N} WP", "last_name": f"{N} WP", "types": ["prestataire"], "instagram_handle": ""})
    assert c.status_code == 200, c.text
    cid = c.json()["id"]
    DB.events.update_one({"org_id": QA, "id": S["ev"]}, {"$set": {"planner_contact_id": cid}})
    v = s.get(f"{API}/communication/events/{S['ev']}").json()
    wp = next(x for x in v["credits"] if x["key"] == f"contact:{cid}")
    assert wp["role"] == "Wedding planner" and wp["handle"] == "" and v["missing_handles"] >= 1
    assert s.put(f"{API}/communication/handles", json={"kind": "contact", "id": cid, "handle": "@wp.sud"}).status_code == 200
    v = s.put(f"{API}/communication/events/{S['ev']}", json={"brand_id": "exclusivity_events", "consent": "accorde", "credits": [{"key": "", "role": "Fleuriste", "name": "Fleurs", "handle": "fleurs_du_sud", "included": True}, {"key": f"contact:{cid}", "role": "Organisation", "handle": "", "included": True}]}).json()
    assert "Organisation : @wp.sud" in v["credit_text"] and "Fleuriste : @fleurs_du_sud" in v["credit_text"] and "Photographe / vidéaste : @studio.photo" in v["credit_text"]
    assert any(x["event"]["id"] == S["ev"] for x in s.get(f"{API}/communication/credits").json())


def test_posts_manual_reminder_and_captions(s):
    p = {"title": f"{N} Post", "brand_id": "exclusivity_events", "event_id": S["ev"], "asset_ids": [S["a"], S["v"]], "status": "planifie", "scheduled_at": "2026-11-01T18:00"}
    bad = s.post(f"{API}/communication/posts", json=p)
    assert bad.status_code == 400 and "Droits refusés" in bad.json()["detail"]
    assert s.post(f"{API}/communication/posts", json={**p, "status": "brouillon"}).status_code == 200
    assert s.post(f"{API}/communication/posts", json={**p, "asset_ids": [S["a"]], "scheduled_at": ""}).status_code == 400
    ok = s.post(f"{API}/communication/posts", json={**p, "asset_ids": [S["a"]]}).json()
    assert ok["publish_mode"] == "rappel_manuel" and ok["assets"][0]["status"] == "publiable"
    S["posts"] = [ok["id"]]
    import asyncio
    import routes_communication as rc
    asyncio.get_event_loop().run_until_complete(rc.tick())
    assert DB.tasks.count_documents({"org_id": QA, "source_ref": f"comm-post:{ok['id']}"}) == 1 and DB.comm_posts.find_one({"id": ok["id"]})["reminded_at"]
    assert s.delete(f"{API}/communication/media/{S['a']}").status_code == 409
    done = s.put(f"{API}/communication/posts/{ok['id']}", json={**p, "asset_ids": [S["a"]], "status": "publie", "permalink": "https://www.instagram.com/p/x/"}).json()
    assert done["published_at"] and s.put(f"{API}/communication/posts/{ok['id']}", json={**p, "asset_ids": [S["a"]], "status": "publie", "permalink": "javascript:x"}).status_code == 400
    cal = s.get(f"{API}/communication/posts", params={"start": "2026-11-01", "end": "2026-11-30"}).json()
    assert ok["id"] in [x["id"] for x in cal]
    cap = s.post(f"{API}/communication/captions", json={"brand_id": "exclusivity_events", "event_id": S["ev"], "type": "post", "brief": "ambiance bougies"})
    assert cap.status_code in (200, 502, 503), cap.text
    if cap.status_code == 200:
        ps = cap.json()["proposals"]
        assert len(ps) == 3 and all(x["fr"] and x["en"] and x["hashtags"] for x in ps)
    print("captions", cap.status_code)
