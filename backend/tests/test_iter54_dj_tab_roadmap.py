"""Iter 54 — Onglet DJ (coordonnées, changer), réponse du DJ par lien, stock mobilisé, feuille de route PDF (QA)."""
import os
import subprocess
import uuid
from datetime import date, timedelta

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
BASE = next(l.split("=", 1)[1].strip().rstrip("/") for l in open("/app/frontend/.env") if l.startswith("REACT_APP_BACKEND_URL="))
TAG = "TEST_M54_" + uuid.uuid4().hex[:5]


def sess(role):
    t = subprocess.run(["python3", "/app/scripts/qa_token.py", role], capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {t}", "Content-Type": "application/json"})
    return s


def test_all():
    a = sess("admin")
    ok = lambda r: (r.status_code < 300 or pytest.fail(f"{r.status_code} {r.text}"), r.json())[1]  # noqa: E731
    day = (date.today() + timedelta(days=75)).isoformat()
    ev = ok(a.post(f"{BASE}/api/events", json={"title": f"{TAG} A", "start": f"{day}T18:00", "end": f"{(date.fromisoformat(day) + timedelta(days=1)).isoformat()}T02:00", "modules": ["dj"]}))
    try:
        d1 = ok(a.post(f"{BASE}/api/dj/quick", json={"name": f"DJ1 {TAG}", "email": f"{TAG.lower()}@example.com", "phone": "0600000000"}))
        d2 = ok(a.post(f"{BASE}/api/dj/quick", json={"name": f"DJ2 {TAG}"}))
        # réponse du DJ par lien public
        q = ok(a.post(f"{BASE}/api/events/{ev['id']}/quotes"))
        DB.quotes.update_one({"id": q["id"]}, {"$set": {"lines": [{"label": "Prestation DJ", "qty": 1, "unit_price": 1, "vat": 20}]}})
        s = ok(a.post(f"{BASE}/api/quotes/{q['id']}/dj/ask", json={"provider_ids": [d1["id"]]}))
        bid = s["requests"][0]["booking_id"]
        path = ok(a.get(f"{BASE}/api/dj/requests/{bid}/link"))["path"]
        tok = path.rsplit("/", 1)[1]
        pub = requests.get(f"{BASE}/api/public/dj-availability/{tok}")
        assert pub.status_code == 200 and pub.json()["status"] == "availability_requested" and set(pub.json()) == {"org", "name", "date", "start_time", "end_time", "city", "event_type", "status"}
        assert TAG not in pub.text.replace(f"DJ1 {TAG}", "")  # ni titre d'événement ni client
        assert requests.get(f"{BASE}/api/public/dj-availability/{'x' * 43}").status_code == 404
        assert requests.post(f"{BASE}/api/public/dj-availability/{tok}", json={"available": True}).json()["status"] == "available"
        assert ok(a.get(f"{BASE}/api/quotes/{q['id']}/dj-status"))["requests"][0]["status"] == "available"
        # onglet DJ : coordonnées + changer de DJ
        ok(a.post(f"{BASE}/api/events/{ev['id']}/dj/assign", json={"provider_id": d2["id"], "fee": 500}))
        v = ok(a.get(f"{BASE}/api/events/{ev['id']}/dj"))
        b2 = next(b for b in v["bookings"] if b["provider_id"] == d2["id"])
        assert v["contacts"][d1["id"]]["phone"] == "0600000000" and b2["status"] == "confirmed"
        d3 = ok(a.post(f"{BASE}/api/dj/quick", json={"name": f"DJ3 {TAG}"}))
        ok(a.post(f"{BASE}/api/dj/replace/{b2['id']}", json={"provider_id": d3["id"], "reason": "test"}))
        v = ok(a.get(f"{BASE}/api/events/{ev['id']}/dj"))
        st = {b["provider_id"]: b for b in v["bookings"]}
        assert st[d2["id"]]["status"] == "cancelled" and st[d3["id"]]["status"] == "confirmed" and st[d3["id"]]["proposed_fee"] == 500
        assert any(l["action"] == "cancelled" for l in v["log"])
        t = sess("technicien")
        assert t.get(f"{BASE}/api/events/{ev['id']}/dj").status_code in (401, 403) and t.post(f"{BASE}/api/dj/replace/{b2['id']}", json={"provider_id": d1["id"]}).status_code in (401, 403)
        # stock mobilisé : quantités seulement
        m = ok(a.get(f"{BASE}/api/events/{ev['id']}/mobilized"))
        assert set(m) == {"basis", "rows", "transfers"} and "price" not in str(m)
        # feuille de route : l'organisateur ne voit ni notes internes ni bascules
        ok(a.post(f"{BASE}/api/events/{ev['id']}/schedule/steps", json={"title": "Montage régie", "duration_min": 60, "phase": "installation"}))
        v2 = ok(a.post(f"{BASE}/api/events/{ev['id']}/schedule/steps", json={"title": "Bascule secrète", "duration_min": 20, "phase": "exploitation"}))
        sid = next(x["id"] for x in v2["steps"] if x["title"] == "Bascule secrète")
        ok(a.put(f"{BASE}/api/schedule/steps/{sid}", json={"internal_notes": "NOTE_INTERNE_XYZ"}))
        import pymupdf
        txt = {}
        for aud in ("team", "dj", "organizer"):
            r = a.get(f"{BASE}/api/events/{ev['id']}/schedule/roadmap", params={"audience": aud})
            assert r.status_code == 200 and r.content[:4] == b"%PDF"
            open(f"/tmp/roadmap-{aud}.pdf", "wb").write(r.content)
            txt[aud] = "".join(p.get_text() for p in pymupdf.open(stream=r.content, filetype="pdf"))
        assert "NOTE_INTERNE_XYZ" in txt["team"] and "NOTE_INTERNE_XYZ" not in txt["dj"] and "NOTE_INTERNE_XYZ" not in txt["organizer"]
        assert "Bascule secrète" in txt["dj"] and "Bascule secrète" not in txt["organizer"] and "Montage régie" in txt["organizer"]
        assert f"DJ3 {TAG}" in txt["team"] and f"DJ3 {TAG}" not in txt["organizer"]
    finally:
        if os.environ.get("KEEP") != "1":
            a.delete(f"{BASE}/api/events/{ev['id']}")
        DB.provider_profiles.update_many({"name": {"$regex": TAG}}, {"$set": {"status": "archived"}})
