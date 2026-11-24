"""Usage: python3 /app/scripts/qa_token.py [role] [email] [contact_id]  (role client / provider: pass the contact_id of the QA org)  -> prints a 10-min session JWT for a user attached to the dedicated QA org (slug qa-sandbox).
Never touches the real company. Create test data there only."""
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
import uuid

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
if (os.environ.get("ENV") or "").strip().lower() != "development" or os.environ.get("CLERK_SECRET_KEY", "").startswith("sk_live_"):
    sys.exit("Refusé : ce script de test ne tourne jamais en production.")
SK = os.environ["CLERK_SECRET_KEY"]


def bapi(path, body=None, method="POST"):
    req = urllib.request.Request("https://api.clerk.com/v1" + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Authorization": "Bearer " + SK, "Content-Type": "application/json", "User-Agent": "emergent-test"})
    return json.load(urllib.request.urlopen(req))


role = sys.argv[1] if len(sys.argv) > 1 else "admin"
email = sys.argv[2] if len(sys.argv) > 2 else f"qa_{role}+clerk_test@example.com"
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
org = db.orgs.find_one({"slug": "qa-sandbox"})
if not org:
    org = {"id": str(uuid.uuid4()), "name": "QA Sandbox", "slug": "qa-sandbox", "city": "Nîmes", "default_vat": 20, "deposit_percent": 30, "quote_prefix": "DEV", "invoice_prefix": "FAC",
           "modules": ["dj", "son_lumiere", "photobooth", "photographe", "wedding_planner", "agence", "loueur_materiel"]}
    db.orgs.insert_one(org)
found = bapi("/users?" + urllib.parse.urlencode({"email_address": email}), method="GET")
user = found[0] if found else bapi("/users", {"email_address": [email], "password": os.environ.get("TEST_USERS_PASSWORD") or secrets.token_urlsafe(24), "skip_password_checks": True})
db.users.update_one({"user_id": user["id"]}, {"$set": {"user_id": user["id"], "email": email, "name": f"QA {role}", "org_id": org["id"], "role": role, "env": "preview", "team_id": None, **({"contact_id": sys.argv[3], "status": "active"} if len(sys.argv) > 3 else {})}}, upsert=True)
session = bapi("/sessions", {"user_id": user["id"]})
print(bapi(f"/sessions/{session['id']}/tokens", {"expires_in_seconds": 600})["jwt"])
