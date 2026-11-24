"""Seed QA pour l'écran Personnes (TEST_M37UI). `clean` supprime uniquement ces fiches de test."""
import os, subprocess, sys, requests
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from pymongo import MongoClient
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
API = "http://localhost:8001/api"
if sys.argv[1:] == ["clean"]:
    cids = [c["id"] for c in DB.contacts.find({"org_id": QA, "last_name": {"$regex": "^TEST_M37UI"}})]
    evs = [e["id"] for e in DB.events.find({"org_id": QA, "title": {"$regex": "^TEST_M37UI"}})]
    DB.event_person_history.delete_many({"org_id": QA, "event_id": {"$in": evs}})
    DB.contact_people.delete_many({"org_id": QA, "contact_id": {"$in": cids}})
    DB.provider_profiles.delete_many({"org_id": QA, "contact_id": {"$in": cids}})
    print("cleaned", DB.events.delete_many({"org_id": QA, "id": {"$in": evs}}).deleted_count, DB.contacts.delete_many({"org_id": QA, "id": {"$in": cids}}).deleted_count); sys.exit()
s = requests.Session(); s.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", "admin"], text=True).strip().splitlines()[-1]
p = s.post(f"{API}/providers", json={"first_name": "Manon", "last_name": "TEST_M37UI Planner", "categories": ["wedding_planner"]}).json()
c = s.post(f"{API}/contacts", json={"first_name": "Léa", "last_name": "TEST_M37UI Cliente"}).json()["id"]
e = s.post(f"{API}/events", json={"title": "TEST_M37UI mariage", "start": "2031-06-14T16:00", "end": "2031-06-15T02:00", "client_id": c, "planner_contact_id": p["contact_id"]}).json()
print({"planner_contact": p["contact_id"], "provider": p["id"], "event": e.get("id")})
