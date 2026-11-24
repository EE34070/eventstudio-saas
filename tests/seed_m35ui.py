"""Seed QA pour l'écran Contacts (TEST_M35UI). `clean` supprime uniquement ces fiches de test."""
import os, subprocess, sys, requests
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from pymongo import MongoClient
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
API = "http://localhost:8001/api"
if sys.argv[1:] == ["clean"]:
    cids = [c["id"] for c in DB.contacts.find({"org_id": QA, "last_name": {"$regex": "^TEST_M35UI"}})]
    pids = [p["id"] for p in DB.provider_profiles.find({"org_id": QA, "contact_id": {"$in": cids}})]
    DB.dj_profiles.delete_many({"org_id": QA, "provider_id": {"$in": pids}})
    print("cleaned", DB.provider_profiles.delete_many({"org_id": QA, "contact_id": {"$in": cids}}).deleted_count, DB.contacts.delete_many({"org_id": QA, "id": {"$in": cids}}).deleted_count); sys.exit()
s = requests.Session(); s.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", "admin"], text=True).strip().splitlines()[-1]
for n, c in (("Planner", "wedding_planner"), ("Dj", "dj")):
    print(n, s.post(f"{API}/providers", json={"first_name": "Zoé", "last_name": f"TEST_M35UI {n}", "categories": [c]}).json().get("contact_id"))
print("client", s.post(f"{API}/contacts", json={"first_name": "Léa", "last_name": "TEST_M35UI Client", "types": ["client"]}).json().get("id"))
