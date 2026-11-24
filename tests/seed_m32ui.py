"""Seed TEST_M32UI data (QA sandbox only) for shortages testing. Idempotent."""
import json
import os
import subprocess
import sys

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
API = "http://localhost:8001/api"
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
TAG = "TEST_M32UI"


def tok(role="admin"):
    return subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip().splitlines()[-1]


def sess(role="admin"):
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + tok(role)
    return s


def cleanup():
    evs = list(DB.events.find({"org_id": QA, "title": {"$regex": f"^{TAG}"}}, {"id": 1}))
    ev_ids = [e["id"] for e in evs]
    if ev_ids:
        DB.quotes.delete_many({"org_id": QA, "event_id": {"$in": ev_ids}})
        DB.shortages.delete_many({"org_id": QA, "event_id": {"$in": ev_ids}})
        DB.partner_requests.delete_many({"org_id": QA, "event_id": {"$in": ev_ids}})
        DB.purchase_needs.delete_many({"org_id": QA, "event_id": {"$in": ev_ids}})
        DB.tasks.delete_many({"org_id": QA, "event_id": {"$in": ev_ids}})
        DB.events.delete_many({"org_id": QA, "id": {"$in": ev_ids}})
    eqs = list(DB.equipment.find({"org_id": QA, "ref": {"$regex": f"^{TAG}"}}, {"id": 1}))
    eq_ids = [e["id"] for e in eqs]
    if eq_ids:
        DB.purchase_needs.delete_many({"org_id": QA, "product_id": {"$in": eq_ids}})
        for c in ("stock_levels", "stock_movements"):
            DB[c].delete_many({"org_id": QA, "product_id": {"$in": eq_ids}})
        DB.equipment.delete_many({"org_id": QA, "id": {"$in": eq_ids}})
    DB.venues.delete_many({"org_id": QA, "name": {"$regex": f"^{TAG}"}})


def seed():
    cleanup()
    s = sess()
    out = {}

    def eq(name, qty, price=10):
        r = s.post(f"{API}/equipment", json={"ref": f"{TAG}_{name}", "name": f"{TAG} {name}", "qty_total": qty, "price_day": price})
        r.raise_for_status()
        return r.json()["id"]

    out["pile"] = eq("Pile AA", 4, 1)
    out["mic"] = eq("Micro", 10, 20)

    # Set requirement on Micro: consommable Pile AA x2 per_unit_day, spare 100%, linked to pile
    r = s.put(f"{API}/equipment/{out['mic']}/requirements", json={"requirements": [{
        "type": "consommable", "label": "Pile AA", "linked_product_id": out["pile"],
        "quantity": 2, "unit": "u", "calc_mode": "per_unit_day", "spare_qty": 0, "spare_pct": 100, "mandatory": True
    }]})
    r.raise_for_status()

    # venue
    r = s.post(f"{API}/venues", json={"name": f"{TAG} Salle", "city": "Nîmes", "address": "12 rue test"})
    r.raise_for_status()
    out["venue"] = r.json()["id"]

    # event (1 day, status demande) + attach 3 micros via PATCH
    r = s.post(f"{API}/events", json={
        "title": f"{TAG} Event", "start": "2028-05-10T14:00", "end": "2028-05-10T22:00",
        "venue_id": out["venue"]
    })
    r.raise_for_status()
    out["event"] = r.json()["id"]
    r = s.patch(f"{API}/events/{out['event']}", json={"equipment": [{"equipment_id": out["mic"], "qty": 3}]})
    r.raise_for_status()

    print(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "clean":
        cleanup()
        print("cleaned")
    else:
        seed()
