"""Seed QA pour Communication (TEST_M41UI). `clean` retire uniquement ces données de test."""
import io, os, subprocess, sys, requests
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from pymongo import MongoClient
from PIL import Image
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
API = "http://localhost:8001/api"
rx = {"$regex": "^TEST_M41UI"}
if sys.argv[1:] == ["clean"]:
    eids = [e["id"] for e in DB.events.find({"org_id": QA, "title": rx})]
    assets = list(DB.media_assets.find({"org_id": QA, "$or": [{"event_id": {"$in": eids}}, {"filename": rx}]}))
    DB.files.update_many({"org_id": QA, "id": {"$in": [a[k][5:] for a in assets for k in ("file_ref", "thumb_ref") if a.get(k)]}}, {"$set": {"is_deleted": True}})
    rids = [r["id"] for r in DB.media_requests.find({"org_id": QA, "event_id": {"$in": eids}})]
    pids = [p["id"] for p in DB.comm_posts.find({"org_id": QA, "title": rx})]
    DB.tasks.delete_many({"org_id": QA, "source_ref": {"$in": [f"comm-drop:{r}" for r in rids] + [f"comm-post:{p}" for p in pids]}})
    print("cleaned", DB.media_assets.delete_many({"org_id": QA, "id": {"$in": [a["id"] for a in assets]}}).deleted_count, DB.media_requests.delete_many({"org_id": QA, "id": {"$in": rids}}).deleted_count,
          DB.comm_posts.delete_many({"org_id": QA, "id": {"$in": pids}}).deleted_count, DB.comm_events.delete_many({"org_id": QA, "event_id": {"$in": eids}}).deleted_count,
          DB.contacts.delete_many({"org_id": QA, "last_name": rx}).deleted_count, DB.events.delete_many({"org_id": QA, "id": {"$in": eids}}).deleted_count)
    sys.exit()
s = requests.Session(); s.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", "admin"], text=True).strip().splitlines()[-1]
ev = s.post(f"{API}/events", json={"title": "TEST_M41UI Mariage", "type": "Mariage", "start": "2026-11-14T16:00", "end": "2026-11-15T02:00"}).json()["id"]
def up(name, color, body):
    b = io.BytesIO(); Image.new("RGB", (1200, 800), color).save(b, "JPEG"); d = b.getvalue()
    u = s.post(f"{API}/communication/uploads", json={"filename": name, "size": len(d)}).json()
    s.put(f"{API}/communication/uploads/{u['id']}/chunks/0", data=d, headers={"Content-Type": "application/octet-stream"})
    return s.post(f"{API}/communication/uploads/{u['id']}/complete", json=body).json()["id"]
a = up("TEST_M41UI ok.jpg", (180, 140, 90), {"event_id": ev, "rights": "ok"}); b = up("TEST_M41UI attente.jpg", (60, 90, 150), {"event_id": ev})
c = s.post(f"{API}/contacts", json={"kind": "entreprise", "company": "TEST_M41UI Planner", "last_name": "TEST_M41UI Planner", "types": ["prestataire"]}).json()["id"]
DB.events.update_one({"org_id": QA, "id": ev}, {"$set": {"planner_contact_id": c}})
r = s.post(f"{API}/communication/requests", json={"event_id": ev, "name": "TEST_M41UI Photographe", "email": "photo@example.com"}).json()
print("event", ev, "| médias", a, b, "| contact", c, "| dépôt /depot/" + r["token"])
