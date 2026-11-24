"""Seed TEST_M33UI data in QA sandbox only. Usage: python3 seed_m33ui.py [clean]"""
import os
import subprocess
import sys

import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

API = "http://localhost:8001/api"
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
TAG = "TEST_M33UI"


def token(role="admin"):
    return subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip().splitlines()[-1]


def session(role="admin"):
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + token(role)
    return s


def clean():
    # Find ids of TEST_M33UI equipment and events
    eq_ids = [e["id"] for e in DB.equipment.find({"org_id": QA, "ref": {"$regex": f"^{TAG}_"}}, {"id": 1})]
    ev_ids = [e["id"] for e in DB.events.find({"org_id": QA, "title": {"$regex": f"^{TAG}"}}, {"id": 1})]
    for c in ("quotes", "shortages", "tasks", "partner_requests", "purchase_needs"):
        DB[c].delete_many({"org_id": QA, "event_id": {"$in": ev_ids}})
    DB.events.delete_many({"org_id": QA, "id": {"$in": ev_ids}})
    for c in ("stock_levels", "stock_movements"):
        DB[c].delete_many({"org_id": QA, "product_id": {"$in": eq_ids}})
    DB.equipment.delete_many({"org_id": QA, "id": {"$in": eq_ids}})
    DB.attribute_templates.delete_many({"org_id": QA})
    print("cleaned:", {"eq": len(eq_ids), "ev": len(ev_ids)})


def seed():
    s = session()

    def mk(name, qty, price=25, **kw):
        ref = f"{TAG}_{name.replace(' ', '_')}"
        # Check if exists
        existing = DB.equipment.find_one({"org_id": QA, "ref": ref})
        if existing:
            return existing["id"]
        r = s.post(f"{API}/equipment", json={"ref": ref, "name": f"{TAG} {name}", "qty_total": qty, "price_day": price, **kw})
        assert r.status_code == 200, r.text
        return r.json()["id"]

    gui = mk("Guirlande 10 m", 8, 25, category="Lumière", subcategory="Guirlandes & ciels lumineux")
    coton = mk("Coton gratte", 120, 5, category="Textile & linge")
    table = mk("Table ovale 26", 2, 40, category="Mobilier", subcategory="Tables")

    # Event
    existing_ev = DB.events.find_one({"org_id": QA, "title": f"{TAG} Event"})
    if existing_ev:
        ev = existing_ev["id"]
    else:
        r = s.post(f"{API}/events", json={"title": f"{TAG} Event", "start": "2029-09-04T18:00", "end": "2029-09-05T02:00"})
        assert r.status_code == 200, r.text
        ev = r.json()["id"]

    print({"gui": gui, "coton": coton, "table": table, "ev": ev})
    return {"gui": gui, "coton": coton, "table": table, "ev": ev}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "clean":
        clean()
    else:
        seed()
