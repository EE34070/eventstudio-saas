"""Seed TEST_M31UI data (QA sandbox only). Idempotent: deletes previous TEST_M31UI data then creates fresh set."""
import io
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
TAG = "TEST_M31UI"


def tok(role="admin"):
    return subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip().splitlines()[-1]


def sess(role="admin"):
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + tok(role)
    return s


def pdf(text):
    from reportlab.pdfgen.canvas import Canvas
    buf = io.BytesIO()
    c = Canvas(buf)
    c.drawString(72, 720, text)
    c.save()
    return buf.getvalue()


def cleanup():
    # Delete events whose title starts with TEST_M31UI
    evs = list(DB.events.find({"org_id": QA, "title": {"$regex": f"^{TAG}"}}, {"id": 1}))
    ev_ids = [e["id"] for e in evs]
    if ev_ids:
        DB.quotes.delete_many({"org_id": QA, "event_id": {"$in": ev_ids}})
        DB.events.delete_many({"org_id": QA, "id": {"$in": ev_ids}})
    # Equipment by TEST_M31UI ref
    eqs = list(DB.equipment.find({"org_id": QA, "ref": {"$regex": f"^{TAG}"}}, {"id": 1}))
    eq_ids = [e["id"] for e in eqs]
    if eq_ids:
        DB.product_documents.delete_many({"org_id": QA, "product_ids": {"$in": eq_ids}})
        DB.requirement_templates.delete_many({"org_id": QA, "name": {"$regex": f"^{TAG}"}})
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

    out["mic"] = eq("MicroHF", 10, 20)
    out["pile"] = eq("PileAA", 10, 1)
    out["pied"] = eq("Pied", 10, 5)
    out["mic2"] = eq("MicroMain", 5, 15)

    # venue
    r = s.post(f"{API}/venues", json={"name": f"{TAG} Salle", "city": "Nîmes", "address": "12 rue test", "power_capacity_w": 10000})
    r.raise_for_status()
    out["venue"] = r.json()["id"]

    # event (demande)
    r = s.post(f"{API}/events", json={"title": f"{TAG} Event", "start": "2028-04-10T18:00", "end": "2028-04-11T02:00", "venue_id": out["venue"]})
    r.raise_for_status()
    out["event"] = r.json()["id"]

    print(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "clean":
        cleanup()
        print("cleaned")
    else:
        seed()
