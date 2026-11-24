"""Iter 63 — Corbeille (QA uniquement)."""
import os
import uuid
from datetime import date, timedelta

from dotenv import load_dotenv
from pymongo import MongoClient

from tests.test_iter54_dj_tab_roadmap import BASE, sess

load_dotenv("/app/backend/.env")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
TAG = "TEST_M63_" + uuid.uuid4().hex[:5]


def test_trash():
    a = sess("admin")
    org = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
    O = {"org_id": org}
    T = lambda k, i, **o: a.post(f"{BASE}/api/trash/delete", json={"items": [{"kind": k, "id": i}], "options": o})  # noqa: E731
    fut, past = (date.today() + timedelta(days=20)).isoformat(), (date.today() - timedelta(days=20)).isoformat()
    ids = {k: k + TAG for k in ("veh", "rot", "wh1", "wh2", "prov", "bk1", "bk2", "inv", "tm")}
    try:
        # véhicule affecté à une rotation future
        DB.vehicles.insert_one({**O, "id": ids["veh"], "name": TAG + " camion", "active": True, "created_at": "2026-01-01"})
        DB.logistics_missions.insert_one({**O, "id": ids["rot"], "date": fut, "vehicles": [ids["veh"]], "status": "planifiee", "type": "livraison", "event_id": "", "created_at": "2026-01-01"})
        im = a.get(f"{BASE}/api/trash/impact", params={"kind": "vehicle", "id": ids["veh"]}).json()
        assert "1 rotation" in im["lines"][0]
        r = T("vehicle", ids["veh"]).json()
        rot = DB.logistics_missions.find_one({"id": ids["rot"]})
        assert r["deleted"] == 1 and rot["vehicles"] == [] and "aucun véhicule" in rot["coverage_alert"] and r["alerts"]
        assert ids["veh"] not in [v["id"] for v in a.get(f"{BASE}/api/vehicles").json()]
        assert ids["veh"] in [x["id"] for x in a.get(f"{BASE}/api/trash").json()["rows"]]
        assert a.post(f"{BASE}/api/trash/restore", json={"items": [{"kind": "vehicle", "id": ids["veh"]}]}).status_code == 200
        assert ids["veh"] in [v["id"] for v in a.get(f"{BASE}/api/vehicles").json()]
        # entrepôt avec stock : transfert obligatoire
        for k in ("wh1", "wh2"):
            DB.warehouses.insert_one({**O, "id": ids[k], "name": f"{TAG} {k}", "type": "secondaire", "active": True, "is_default": False, "created_at": "2026-01-01"})
        DB.stock_levels.insert_one({**O, "product_id": "p" + TAG, "warehouse_id": ids["wh1"], "qty_on_hand": 7})
        assert T("warehouse", ids["wh1"]).status_code == 400
        assert T("warehouse", ids["wh1"], transfer_to=ids["wh2"]).status_code == 200
        assert DB.stock_levels.find_one({"warehouse_id": ids["wh2"], "product_id": "p" + TAG})["qty_on_hand"] == 7
        assert ids["wh1"] not in [w["id"] for w in a.get(f"{BASE}/api/warehouses").json()]
        main = DB.warehouses.find_one({**O, "is_default": True, "deleted_at": None})
        if main:
            assert T("warehouse", main["id"], transfer_to="drop").status_code == 400
            assert DB.warehouses.count_documents({**O, "is_default": True, "deleted_at": None}) == 1
        # DJ : prestation passée garde le nom, future retirée
        DB.provider_profiles.insert_one({**O, "id": ids["prov"], "name": TAG + " DJ", "contact_id": "c" + TAG, "created_at": "2026-01-01"})
        DB.dj_bookings.insert_one({**O, "id": ids["bk1"], "provider_id": ids["prov"], "provider_name": TAG + " DJ", "date": past, "status": "confirmed", "event_id": "x"})
        DB.dj_bookings.insert_one({**O, "id": ids["bk2"], "provider_id": ids["prov"], "provider_name": TAG + " DJ", "date": fut, "status": "confirmed", "event_id": "y"})
        r = T("provider", ids["prov"]).json()
        assert DB.dj_bookings.find_one({"id": ids["bk1"]})["provider_name"] == TAG + " DJ (supprimé)" and DB.dj_bookings.find_one({"id": ids["bk2"]})["deleted_at"] and "aucun DJ" in r["alerts"][0]
        a.post(f"{BASE}/api/trash/restore", json={"items": [{"kind": "provider", "id": ids["prov"]}]})
        assert DB.dj_bookings.find_one({"id": ids["bk1"]})["provider_name"] == TAG + " DJ" and not DB.dj_bookings.find_one({"id": ids["bk2"]}).get("deleted_at")
        # facture émise : refus
        DB.invoices.insert_one({**O, "id": ids["inv"], "number": "FAC-" + TAG, "status": "emise", "kind": "solde", "quote_id": "q" + TAG, "created_at": "2026-01-01"})
        r = T("invoice", ids["inv"])
        assert r.status_code == 409 and "avoir" in r.json()["detail"]
        assert a.get(f"{BASE}/api/trash/impact", params={"kind": "invoice", "id": ids["inv"]}).json()["blocked"]
        DB.invoices.update_one({"id": ids["inv"]}, {"$set": {"lines": [{"label": "x", "description": "", "qty": 1, "unit_price": 100, "vat": 20}], "event_id": "", "event_code": "", "event_title": "", "client": {}}})
        av = a.post(f"{BASE}/api/invoices/{ids['inv']}/credit-note")
        assert av.status_code == 200 and av.json()["number"].startswith("AV") and av.json()["total_ttc"] == -120 and DB.invoices.find_one({"id": ids["inv"]})["status"] == "annulee"
        assert a.post(f"{BASE}/api/invoices/{ids['inv']}/credit-note").status_code == 409 and T("invoice", av.json()["id"]).status_code == 409
        DB.invoices.delete_one({"id": av.json()["id"]})
        # membre avec historique
        ev = a.post(f"{BASE}/api/events", json={"title": TAG, "start": past + "T10:00", "end": past + "T12:00"}).json()
        DB.team.insert_one({**O, "id": ids["tm"], "name": TAG + " Membre", "email": "", "active": True, "user_id": None, "skills": [], "color": "#000", "created_at": "2026-01-01"})
        DB.events.update_one({"id": ev["id"]}, {"$set": {"team": [{"member_id": ids["tm"], "role": "tech"}]}})
        assert T("member", ids["tm"]).status_code == 200 and DB.events.find_one({"id": ev["id"]})["team"][0]["member_id"] == ids["tm"]
        assert T("event", ev["id"]).status_code == 200 and a.get(f"{BASE}/api/events/{ev['id']}").status_code == 404
        # droits + purge + journal
        assert sess("technicien").post(f"{BASE}/api/trash/delete", json={"items": [{"kind": "vehicle", "id": ids["veh"]}]}).status_code == 403
        T("vehicle", ids["veh"])
        assert a.post(f"{BASE}/api/trash/purge", json={"items": [{"kind": "vehicle", "id": ids["veh"]}]}).status_code == 200 and not DB.vehicles.find_one({"id": ids["veh"]})
        acts = {x["action"] for x in DB.audit_logs.find({"org_id": org, "target": {"$regex": TAG}})}
        assert {"trash_deleted", "trash_restored", "trash_purged"} <= acts
    finally:
        for c in ("vehicles", "logistics_missions", "warehouses", "provider_profiles", "dj_bookings", "invoices", "team"):
            DB[c].delete_many({**O, "id": {"$in": list(ids.values())}})
        DB.stock_levels.delete_many({**O, "product_id": "p" + TAG})
        DB.events.delete_many({**O, "title": TAG})
