"""Iter 55 — Envoi feuille de route, message de libération, DJ visible client, bascule par emplacement (QA)."""
import os
import uuid
from datetime import date, timedelta

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

from tests.test_iter54_dj_tab_roadmap import BASE, sess

load_dotenv("/app/backend/.env")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
TAG = "TEST_M55_" + uuid.uuid4().hex[:5]


def test_four():
    a = sess("admin")
    ok = lambda r: (r.status_code < 300 or pytest.fail(f"{r.status_code} {r.text}"), r.json())[1]  # noqa: E731
    day = (date.today() + timedelta(days=70)).isoformat()
    venue = ok(a.post(f"{BASE}/api/venues", json={"name": f"{TAG} lieu", "city": "Lyon", "sections": [{"name": "Cérémonie"}, {"name": "Repas", "transfer_minutes": 45}]}))
    rep = next(s["id"] for s in venue["sections"] if s["name"] == "Repas")
    ev = ok(a.post(f"{BASE}/api/events", json={"title": f"{TAG} A", "start": f"{day}T16:00", "end": f"{(date.fromisoformat(day) + timedelta(days=1)).isoformat()}T01:00", "modules": ["dj"], "venue_id": venue["id"]}))
    try:
        d1 = ok(a.post(f"{BASE}/api/dj/quick", json={"name": f"DJ1 {TAG}", "email": f"{TAG.lower()}@example.com"}))
        # message de libération après devis refusé
        q = ok(a.post(f"{BASE}/api/events/{ev['id']}/quotes"))
        DB.quotes.update_one({"id": q["id"]}, {"$set": {"lines": [{"label": "Prestation DJ", "qty": 1, "unit_price": 1, "vat": 20}]}})
        bid = ok(a.post(f"{BASE}/api/quotes/{q['id']}/dj/ask", json={"provider_ids": [d1["id"]]}))["requests"][0]["booking_id"]
        ok(a.post(f"{BASE}/api/quotes/{q['id']}/status", json={"status": "refuse"}))
        b = next(x for x in ok(a.get(f"{BASE}/api/events/{ev['id']}/dj"))["bookings"] if x["id"] == bid)
        assert b["status"] == "cancelled" and b["release_pending"] and not DB.dj_messages.find_one({"booking_id": bid})
        dr = ok(a.get(f"{BASE}/api/dj/bookings/{bid}/release-draft"))
        assert dr["to"].endswith("@example.com") and "libre" in dr["body"]
        ok(a.post(f"{BASE}/api/dj/bookings/{bid}/release-message", json={"subject": dr["subject"], "body": "Texte modifié"}))
        m = DB.dj_messages.find_one({"booking_id": bid})
        assert m["body"] == "Texte modifié" and m["sent"] is False
        assert a.post(f"{BASE}/api/dj/bookings/{bid}/release-message", json={"subject": "x", "body": "y"}).status_code == 404
        # DJ visible client + envoi feuille de route
        ok(a.post(f"{BASE}/api/events/{ev['id']}/dj/assign", json={"provider_id": d1["id"]}))
        assert ok(a.get(f"{BASE}/api/events/{ev['id']}/dj"))["show_client"] is False
        ok(a.put(f"{BASE}/api/events/{ev['id']}/dj/show-client", json={"show": True}))
        assert ok(a.get(f"{BASE}/api/events/{ev['id']}/dj"))["show_client"] is True
        v = ok(a.post(f"{BASE}/api/events/{ev['id']}/schedule/steps", json={"title": "Montage régie", "duration_min": 60, "phase": "installation"}))
        ok(a.put(f"{BASE}/api/schedule/steps/{v['steps'][0]['id']}", json={"internal_notes": "NOTE_XYZ"}))
        dj_d, team_d = (ok(a.get(f"{BASE}/api/events/{ev['id']}/schedule/roadmap/draft", params={"audience": x})) for x in ("dj", "team"))
        assert "Montage régie" in dj_d["body"] and "NOTE_XYZ" not in dj_d["body"] and "NOTE_XYZ" in team_d["body"] and dj_d["recipients"][0]["id"] == d1["id"]
        r = ok(a.post(f"{BASE}/api/events/{ev['id']}/schedule/roadmap/send", json={"audience": "dj", "recipient_ids": [d1["id"]], "subject": dj_d["subject"], "body": dj_d["body"]}))
        assert r["sent"] is False and DB.dj_messages.find_one({"event_id": ev["id"], "kind": "roadmap_dj"})["sent"] is False
        assert a.post(f"{BASE}/api/events/{ev['id']}/schedule/roadmap/send", json={"audience": "team", "recipient_ids": ["x"], "subject": "s", "body": "b"}).status_code == 400
        assert sess("technicien").get(f"{BASE}/api/events/{ev['id']}/schedule/roadmap/draft").status_code in (401, 403, 404)
        # bascule par emplacement : 45 min vers « Repas », 30 min d'écart => alerte
        eq = ok(a.post(f"{BASE}/api/equipment", json={"name": f"{TAG} enceinte", "ref": TAG, "category": "Son", "qty_total": 4, "price_day": 10}))
        q2 = ok(a.post(f"{BASE}/api/events/{ev['id']}/quotes"))
        dates = ok(a.get(f"{BASE}/api/quotes/{q2['id']}/structure"))["dates"]
        L = lambda i, p, **k: {"id": i, "parent_id": p, "type": "line", "label": i, "qty": 1, "unit_price": 50, "vat": 20, "equipment_id": eq["id"], "kind": "catalog", **k}  # noqa: E731

        def put(space):
            blocks = [{"id": "cer", "type": "section", "title": "Cérémonie", "usage_start": "16:00", "usage_end": "17:00"}, L("c", "cer"),
                      {"id": "rep", "type": "section", "title": "Repas", "usage_start": "17:30", "usage_end": "23:00", "space_id": space}, L("r", "rep", reuse_from="c")]
            return {x["id"]: x for x in ok(a.put(f"{BASE}/api/quotes/{q2['id']}/structure", json={"blocks": blocks, "dates": dates}))["blocks"]}["r"]
        assert put("")["reuse_alert"] == ""
        r = put(rep)
        assert "45 min" in r["reuse_alert"] and r["reuse_status"] == "validated"
        assert DB.schedule_steps.find_one({"event_id": ev["id"], "source_ref": {"$regex": "^reuse:"}, "deleted_at": None})["duration_min"] == 45
    finally:
        a.delete(f"{BASE}/api/events/{ev['id']}")
        a.delete(f"{BASE}/api/venues/{venue['id']}")
        DB.provider_profiles.update_many({"name": {"$regex": TAG}}, {"$set": {"status": "archived"}})
        DB.equipment.delete_many({"ref": TAG})
