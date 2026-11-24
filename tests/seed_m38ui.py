"""Seed QA pour l'écran Finance (TEST_M38UI). `clean` supprime uniquement ces données de test."""
import os, subprocess, sys, uuid, requests
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from pymongo import MongoClient
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
API = "http://localhost:8001/api"
if sys.argv[1:] == ["clean"]:
    evs = [e["id"] for e in DB.events.find({"org_id": QA, "title": {"$regex": "^TEST_M38UI"}})]
    for c in ("commitments", "quotes", "missions", "opportunities"):
        DB[c].delete_many({"org_id": QA, "event_id": {"$in": evs}})
    DB.forecast_versions.delete_many({"org_id": QA, "name": {"$regex": "^TEST_M38UI"}})
    print("cleaned", DB.events.delete_many({"org_id": QA, "id": {"$in": evs}}).deleted_count); sys.exit()
s = requests.Session(); s.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", "admin"], text=True).strip().splitlines()[-1]
def ev(day, lines, status="accepte"):
    e = s.post(f"{API}/events", json={"title": f"TEST_M38UI {day}", "start": f"2033-06-{day}T16:00", "end": f"2033-06-{day}T23:00"}).json()["id"]
    ht = sum(p for _, p in lines)
    DB.quotes.insert_one({"id": str(uuid.uuid4()), "org_id": QA, "event_id": e, "number": f"TEST_M38UI-{day}", "status": status, "created_at": "2030-01-01T00:00:00", "date": "2030-01-01", "total_ht": ht, "total_ttc": ht * 1.2,
                          "lines": [{"label": l, "qty": 1, "unit_price": p} for l, p in lines]})
    return e
mixed = ev("10", [("Prestation DJ soirée", 1500), ("Location chaises et tables", 2500)])
ev("11", [("Location mobilier", 6500)]); ev("12", [("Location mobilier", 2500)])
p = ev("20", [("Location mobilier", 5000)], "envoye")
DB.opportunities.insert_one({"id": str(uuid.uuid4()), "org_id": QA, "event_id": p, "title": "TEST_M38UI", "probability": 40, "source_key": "instagram", "stage_key": "devis_envoye"})
DB.missions.insert_one({"id": str(uuid.uuid4()), "org_id": QA, "event_id": mixed, "provider_id": "x", "provider_name": "TEST_M38UI Sax", "category_key": "saxophoniste", "date": "2033-06-10", "total_ht": 450, "total_ttc": 450, "status": "confirmed"})
print({"mixed_event": mixed})
