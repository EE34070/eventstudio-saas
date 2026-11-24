"""Iter 56 — Conflits DJ à la sélection : niveaux, 409 serveur, forçage, relance au changement de date (QA)."""
import os
import uuid
from datetime import date, timedelta

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient

from tests.test_iter54_dj_tab_roadmap import BASE, sess

load_dotenv("/app/backend/.env")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
TAG = "TEST_M56_" + uuid.uuid4().hex[:5]


def test_conflicts():
    a = sess("admin")
    ok = lambda r: (r.status_code < 300 or pytest.fail(f"{r.status_code} {r.text}"), r.json())[1]  # noqa: E731
    d0 = date.today() + timedelta(days=200)
    D = lambda n: (d0 + timedelta(days=n)).isoformat()  # noqa: E731
    v1 = ok(a.post(f"{BASE}/api/venues", json={"name": f"{TAG} Paris", "city": "Paris", "lat": 48.8566, "lng": 2.3522}))
    v2 = ok(a.post(f"{BASE}/api/venues", json={"name": f"{TAG} Lyon", "city": "Lyon", "lat": 45.764, "lng": 4.8357}))
    E = lambda t, s, e, v=v1, **k: ok(a.post(f"{BASE}/api/events", json={"title": f"{TAG} {t}", "start": s, "end": e, "modules": ["dj"], "venue_id": v["id"], **k}))  # noqa: E731
    cv, va, br = E("Coralie", f"{D(0)}T18:00", f"{D(1)}T02:00"), E("Virginie", f"{D(0)}T19:00", f"{D(1)}T01:00"), E("Brunch", f"{D(1)}T11:00", f"{D(1)}T15:00", v2)
    o1, o2 = E("Devis1", f"{D(7)}T18:00", f"{D(8)}T02:00"), E("Devis2", f"{D(7)}T19:00", f"{D(8)}T01:00")
    evs = [cv, va, br, o1, o2]
    try:
        dj = ok(a.post(f"{BASE}/api/dj/quick", json={"name": f"DJ {TAG}"}))["id"]
        other = ok(a.post(f"{BASE}/api/dj/quick", json={"name": f"DJ libre {TAG}"}))["id"]
        ok(a.post(f"{BASE}/api/events/{cv['id']}/dj/assign", json={"provider_id": dj}))
        sel = lambda e: {x["provider_id"]: x for x in ok(a.get(f"{BASE}/api/dj/selection", params={"event_id": e["id"]}))["djs"]}  # noqa: E731
        s = sel(va)
        assert s[dj]["level"] == "blocking" and "Coralie" in s[dj]["conflicts"][0]["detail"] and "18:00 → 02:00" in s[dj]["conflicts"][0]["detail"] and s[other]["level"] == "free"
        assert sel(br)[dj]["level"] == "probable"  # brunch le lendemain à Lyon après une fin à 2 h
        r = a.post(f"{BASE}/api/events/{va['id']}/dj/assign", json={"provider_id": dj})
        assert r.status_code == 409 and r.json()["detail"]["conflicts"][0]["event_id"] == cv["id"]
        r = a.post(f"{BASE}/api/events/{va['id']}/dj/options", json={"provider_ids": [dj], "proposed_fee": 1, "start_time": "19:00", "end_time": "01:00"})
        assert r.status_code == 409
        assert a.post(f"{BASE}/api/events/{va['id']}/dj/assign", json={"provider_id": dj, "conflict_override": True, "conflict_reason": " "}).status_code == 409
        ok(a.post(f"{BASE}/api/events/{va['id']}/dj/assign", json={"provider_id": dj, "conflict_override": True, "conflict_reason": "deux sets courts, même domaine"}))
        b = DB.dj_bookings.find_one({"event_id": va["id"], "provider_id": dj})
        assert b["conflict_override"] and b["conflict_reason"].startswith("deux sets") and DB.dj_booking_logs.find_one({"booking_id": b["id"], "action": "conflict_forced"})
        cov = ok(a.get(f"{BASE}/api/dj/coverage", params={"frm": D(0), "to": D(0), "pending": True}))
        rows = [e for d in cov["days"] for e in d["events"] if e["title"].startswith(TAG)]
        assert len(rows) == 2 and all(e["conflict_accepted"] for e in rows) and not any(x["title"] == "Conflit DJ" and TAG in x["detail"] for x in cov["alerts"])
        # sous réserve : option sur un devis non accepté
        ok(a.post(f"{BASE}/api/events/{o1['id']}/dj/options", json={"provider_ids": [other], "proposed_fee": 1, "start_time": "18:00", "end_time": "02:00"}))
        s = sel(o2)
        assert s[other]["level"] == "tentative"
        ok(a.post(f"{BASE}/api/events/{o2['id']}/dj/options", json={"provider_ids": [other], "proposed_fee": 1, "start_time": "19:00", "end_time": "01:00"}))
        # indisponibilité déclarée
        DB.dj_availability.insert_one({"id": uuid.uuid4().hex, "org_id": b["org_id"], "provider_id": other, "date": D(0), "state": "unavailable", "source": "dj", "private_title": "SECRET"})
        c = ok(a.get(f"{BASE}/api/dj/{other}/conflicts", params={"start": f"{D(0)}T19:00", "end": f"{D(1)}T01:00"}))
        assert c[0]["level"] == "unavailable" and "SECRET" not in str(c)
        # décalage de Coralie : le forçage tombe, le contrôle est relancé
        DB.dj_bookings.update_one({"event_id": va["id"], "provider_id": dj}, {"$set": {"date": D(7), "start_time": "19:00", "end_time": "01:00", "event_id": o2["id"]}})
        r = ok(a.patch(f"{BASE}/api/events/{cv['id']}", json={"start": f"{D(7)}T18:00", "end": f"{D(8)}T02:00", "setup_start": f"{D(7)}T12:00", "return_end": f"{D(8)}T12:00"}))
        assert r["dj_conflicts"] and "Devis2" in r["dj_conflicts"][0]
        nb = DB.dj_bookings.find_one({"event_id": cv["id"], "provider_id": dj})
        assert nb["date"] == D(7) and not nb.get("conflict_override")
        assert sess("technicien").get(f"{BASE}/api/dj/selection", params={"event_id": va["id"]}).status_code in (401, 403)
    finally:
        for e in evs:
            a.delete(f"{BASE}/api/events/{e['id']}")
        DB.dj_bookings.update_many({"event_id": {"$in": [e["id"] for e in evs]}}, {"$set": {"status": "cancelled"}})
        DB.dj_availability.delete_many({"provider_id": {"$in": [x["id"] for x in DB.provider_profiles.find({"name": {"$regex": TAG}})]}})
        DB.provider_profiles.update_many({"name": {"$regex": TAG}}, {"$set": {"status": "archived"}})
        for v in (v1, v2):
            a.delete(f"{BASE}/api/venues/{v['id']}")
