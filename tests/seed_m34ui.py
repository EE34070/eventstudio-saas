"""Seed QA pour l'écran scène (TEST_M34UI). `clean` supprime tout."""
import json, os, subprocess, sys, requests
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from pymongo import MongoClient
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
API = "http://localhost:8001/api"
if sys.argv[1:] == ["clean"]:
    ids = [e["id"] for e in DB.equipment.find({"org_id": QA, "ref": {"$regex": "^TEST_M34UI"}})]
    evs = [e["id"] for e in DB.events.find({"org_id": QA, "title": {"$regex": "^TEST_M34UI"}})]
    for c in ("shortages", "tasks"): DB[c].delete_many({"org_id": QA, "event_id": {"$in": evs}})
    for c in ("stock_levels", "stock_movements"): DB[c].delete_many({"org_id": QA, "product_id": {"$in": ids}})
    print("cleaned", DB.equipment.delete_many({"org_id": QA, "id": {"$in": ids}}).deleted_count, DB.events.delete_many({"org_id": QA, "id": {"$in": evs}}).deleted_count); sys.exit()
s = requests.Session(); s.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", "admin"], text=True).strip().splitlines()[-1]
out = {}
for k, name, qty, at in (("p21", "Praticable 2x1", 30, {"role": "praticable", "longueur_m": 2, "largeur_m": 1}), ("pied", "Pied 60", 60, {"role": "pied", "hauteur_fixe_cm": 60})):
    out[k] = s.post(f"{API}/equipment", json={"ref": f"TEST_M34UI_{k}", "name": f"TEST_M34UI {name}", "qty_total": qty, "price_day": 1, "category": "Scène & piste"}).json()["id"]
    s.put(f"{API}/equipment/{out[k]}/attributes", json={"attributes": {"systeme": "M34UI", **at}})
out["ev"] = s.post(f"{API}/events", json={"title": "TEST_M34UI scène", "start": "2030-05-04T18:00", "end": "2030-05-05T02:00"}).json()["id"]
json.dump(out, open("/tmp/m34.json", "w")); print(out)
