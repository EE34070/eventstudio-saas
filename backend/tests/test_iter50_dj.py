"""Iter 50/53 — Couverture DJ : seules les prestations confirmées alertent ; encart DJ du devis ; demande de dispo (QA)."""
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
TAG = "TEST_M53_" + uuid.uuid4().hex[:5]


def sess(role):
    t = subprocess.run(["python3", "/app/scripts/qa_token.py", role], capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {t}", "Content-Type": "application/json"})
    return s


def test_dj_rules():
    a = sess("admin")
    ok = lambda r: (r.status_code < 300 or pytest.fail(r.text), r.json())[1]  # noqa: E731
    day = (date.today() + timedelta(days=80)).isoformat()
    evs = [ok(a.post(f"{BASE}/api/events", json={"title": f"{TAG} {n}", "start": f"{day}T18:00", "end": f"{(date.fromisoformat(day) + timedelta(days=1)).isoformat()}T02:00", "modules": ["dj"]})) for n in "ABC"]
    try:
        cov = lambda **k: ok(a.get(f"{BASE}/api/dj/coverage", params={"frm": day, "to": day, **k}))  # noqa: E731
        mine = lambda c: [e for d in c["days"] for e in d["events"] if e["title"].startswith(TAG)]  # noqa: E731
        assert not mine(cov()) and not any(TAG in x["detail"] for x in cov()["alerts"])  # non confirmé : aucune alerte
        p = mine(cov(pending=True))
        assert len(p) == 3 and not any(e["confirmed"] for e in p) and not any(TAG in x["detail"] for x in cov(pending=True)["alerts"])
        q = ok(a.post(f"{BASE}/api/events/{evs[2]['id']}/quotes"))
        st = ok(a.get(f"{BASE}/api/quotes/{q['id']}/structure"))
        sec = st["blocks"][0]
        ok(a.put(f"{BASE}/api/quotes/{q['id']}/structure", json={"blocks": [sec, {"id": "l1", "parent_id": sec["id"], "type": "line", "label": "Prestation DJ soirée", "qty": 1, "unit_price": 900, "vat": 20}], "dates": st["dates"]}))
        dj1 = ok(a.post(f"{BASE}/api/dj/quick", json={"name": f"DJ {TAG}"}))
        s = ok(a.get(f"{BASE}/api/quotes/{q['id']}/dj-status"))
        assert s["has_dj"] and s["free"] >= 1 and any(x["provider_id"] == dj1["id"] for x in s["djs"]) and not s["requests"]
        s = ok(a.post(f"{BASE}/api/quotes/{q['id']}/dj/ask", json={"provider_ids": [dj1["id"]]}))
        assert [r["status"] for r in s["requests"]] == ["availability_requested"]
        ok(a.put(f"{BASE}/api/dj/requests/{s['requests'][0]['booking_id']}", json={"available": True}))
        assert ok(a.get(f"{BASE}/api/quotes/{q['id']}/dj-status"))["requests"][0]["status"] == "available"
        tok = ok(a.post(f"{BASE}/api/quotes/{q['id']}/share"))["token"]
        assert f"DJ {TAG}" not in requests.get(f"{BASE}/api/public/quotes/{tok}").text
        ok(a.post(f"{BASE}/api/quotes/{q['id']}/status", json={"status": "accepte"}))
        c = cov()
        row = next(e for e in mine(c) if e["event_id"] == evs[2]["id"])
        assert row["confirmed"] and row["coverage"] == "none" and row["priority"] == "critical" and any(TAG in x["detail"] and x["title"].startswith("DJ non affecté") for x in c["alerts"])
        DB.events.update_many({"id": {"$in": [e["id"] for e in evs[:2]]}}, {"$set": {"status": "confirme"}})
        ok(a.post(f"{BASE}/api/events/{evs[0]['id']}/dj/assign", json={"provider_id": dj1["id"]}))
        r0 = next(e for e in mine(cov()) if e["event_id"] == evs[0]["id"])
        assert r0["coverage"] == "confirmed" and r0["djs"][0]["name"] == f"DJ {TAG}"
        r = a.post(f"{BASE}/api/events/{evs[1]['id']}/dj/assign", json={"provider_id": dj1["id"]})
        assert r.status_code == 409 and r.json()["detail"]["conflicts"][0]["level"] == "blocking"
        assert a.post(f"{BASE}/api/events/{evs[1]['id']}/dj/assign", json={"provider_id": dj1["id"], "conflict_override": True}).status_code == 409  # motif obligatoire
        ok(a.post(f"{BASE}/api/events/{evs[1]['id']}/dj/assign", json={"provider_id": dj1["id"], "conflict_override": True, "conflict_reason": "deux sets courts"}))
        c = cov()
        assert not any(x["title"] == "Conflit DJ" for x in c["alerts"]) and sum(1 for e in mine(c) if e.get("conflict_accepted")) == 2
        DB.dj_bookings.update_many({"event_id": evs[1]["id"]}, {"$set": {"conflict_override": False}})
        assert any(x["title"] == "Conflit DJ" for x in cov()["alerts"])
        q2 = ok(a.post(f"{BASE}/api/events/{evs[1]['id']}/quotes"))
        dj2 = ok(a.post(f"{BASE}/api/dj/quick", json={"name": f"DJ2 {TAG}"}))
        DB.quotes.update_one({"id": q2["id"]}, {"$set": {"lines": [{"label": "Prestation DJ", "qty": 1, "unit_price": 1, "vat": 20}]}})
        ok(a.post(f"{BASE}/api/quotes/{q2['id']}/dj/ask", json={"provider_ids": [dj2["id"]]}))
        ok(a.post(f"{BASE}/api/quotes/{q2['id']}/status", json={"status": "refuse"}))
        assert DB.dj_bookings.find_one({"quote_id": q2["id"]})["status"] == "cancelled"
        assert sess("technicien").get(f"{BASE}/api/quotes/{q['id']}/dj-status").status_code in (401, 403)
    finally:
        for e in evs:
            a.delete(f"{BASE}/api/events/{e['id']}")
        DB.provider_profiles.update_many({"name": {"$regex": TAG}}, {"$set": {"status": "archived"}})
