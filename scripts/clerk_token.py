"""Usage: python3 /app/scripts/clerk_token.py <email> <role> [org=demo|none]  -> prints a 10-min session JWT.
Creates the Clerk dev user if needed and attaches it to the demo org with the given role (preview only)."""
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
if (os.environ.get("ENV") or "").strip().lower() != "development" or os.environ.get("CLERK_SECRET_KEY", "").startswith("sk_live_"):
    sys.exit("Refusé : ce script de test ne tourne jamais en production.")
SK = os.environ["CLERK_SECRET_KEY"]


def bapi(path, body=None, method="POST"):
    req = urllib.request.Request("https://api.clerk.com/v1" + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Authorization": "Bearer " + SK, "Content-Type": "application/json",
                                                         "User-Agent": "emergent-test"})
    return json.load(urllib.request.urlopen(req))


email, role = sys.argv[1], sys.argv[2]
org_mode = sys.argv[3] if len(sys.argv) > 3 else "demo"
found = bapi("/users?" + urllib.parse.urlencode({"email_address": email}), method="GET")
user = found[0] if found else bapi("/users", {"email_address": [email], "password": os.environ.get("TEST_USERS_PASSWORD") or secrets.token_urlsafe(24), "skip_password_checks": True})
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
if org_mode == "demo":
    org = db.orgs.find_one({"slug": "exclusivity-events"})
    team = db.team.find_one({"org_id": org["id"], "access_role": role, "email": ""}) if role == "technicien" else None
    db.users.update_one({"user_id": user["id"]}, {"$set": {"user_id": user["id"], "email": email, "name": f"TEST {role}",
                                                          "org_id": org["id"], "role": role, "env": "preview",
                                                          "team_id": team["id"] if team else None}}, upsert=True)
session = bapi("/sessions", {"user_id": user["id"]})
print(bapi(f"/sessions/{session['id']}/tokens", {"expires_in_seconds": 600})["jwt"])
