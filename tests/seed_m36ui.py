"""Seed QA pour l'écran Fournisseurs (TEST_M36UI). `clean` supprime uniquement ces fiches de test."""
import os, subprocess, sys, requests
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from pymongo import MongoClient
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
API = "http://localhost:8001/api"
if sys.argv[1:] == ["clean"]:
    cids = [c["id"] for c in DB.contacts.find({"org_id": QA, "company": {"$regex": "^TEST_M36UI"}})]
    pids = [p["id"] for p in DB.equipment.find({"org_id": QA, "ref": {"$regex": "^TEST_M36UI"}})]
    mids = [m["id"] for m in DB.supplier_product_map.find({"org_id": QA, "$or": [{"supplier_id": {"$in": cids}}, {"product_id": {"$in": pids}}]})]
    DB.supplier_price_history.delete_many({"org_id": QA, "map_id": {"$in": mids}})
    DB.supplier_product_map.delete_many({"org_id": QA, "id": {"$in": mids}})
    DB.purchase_invoices.delete_many({"org_id": QA, "$or": [{"supplier_contact_id": {"$in": cids}}, {"number": {"$regex": "^TEST_M36UI"}}]})
    DB.purchase_needs.delete_many({"org_id": QA, "label": {"$regex": "TEST_M36UI"}})
    print("cleaned", DB.equipment.delete_many({"org_id": QA, "id": {"$in": pids}}).deleted_count, DB.contacts.delete_many({"org_id": QA, "id": {"$in": cids}}).deleted_count); sys.exit()
s = requests.Session(); s.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", "admin"], text=True).strip().splitlines()[-1]
p = s.post(f"{API}/equipment", json={"ref": "TEST_M36UI_MOQ", "name": "TEST_M36UI Moquette", "qty_total": 0, "price_day": 1, "category": "Scène & piste"}).json()["id"]
c = s.post(f"{API}/contacts", json={"kind": "entreprise", "company": "TEST_M36UI ESL", "types": ["fournisseur"]}).json()["id"]
n = s.post(f"{API}/purchase-needs", json={"label": "TEST_M36UI moquette", "qty": 10}).json()["id"]
DB.purchase_needs.update_one({"org_id": QA, "id": n}, {"$set": {"product_id": p}})
print({"product": p, "esl": c, "need": n})
