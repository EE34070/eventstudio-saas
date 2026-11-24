"""Usage: python3 /app/scripts/clerk_ticket.py <email>  -> prints a Clerk sign-in ticket (preview testing)."""
import json
import os
import sys
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
if (os.environ.get("ENV") or "").strip().lower() != "development" or os.environ.get("CLERK_SECRET_KEY", "").startswith("sk_live_"):
    sys.exit("Refusé : ce script de test ne tourne jamais en production.")
SK = os.environ["CLERK_SECRET_KEY"]


def bapi(path, body=None, method="POST"):
    req = urllib.request.Request("https://api.clerk.com/v1" + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Authorization": "Bearer " + SK, "Content-Type": "application/json",
                                                         "User-Agent": "emergent-test"})
    return json.load(urllib.request.urlopen(req))


u = bapi("/users?" + urllib.parse.urlencode({"email_address": sys.argv[1]}), method="GET")[0]
print(bapi("/sign_in_tokens", {"user_id": u["id"], "expires_in_seconds": 3600})["token"])
