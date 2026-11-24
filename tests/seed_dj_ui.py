"""Seed TEST_DJUI data for Playwright DJ tests. Idempotent. QA org only."""
import os, sys, uuid, subprocess, json
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from pymongo import MongoClient

DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
assert QA

# cleanup prior
for c in ("contacts", "provider_profiles", "venues", "events", "quotes"):
    DB[c].delete_many({"org_id": QA, "test_tag": "TEST_DJUI"})
ids_known = [d["provider_id"] for d in DB.provider_profiles.find({"org_id": QA, "test_tag": "TEST_DJUI"}, {"provider_id": 1})]
for c in ("dj_availability","dj_calendar_meta","dj_profiles","dj_bookings","dj_invoices","missions","dj_booking_logs","dj_messages","event_dj_criteria","client_dj_shortlists"):
    DB[c].delete_many({"org_id": QA, "provider_id": {"$regex": "^TESTDJUI_"}})

ids = {k: str(uuid.uuid4()) for k in ("c_a","c_b","c_c","p_a","p_b","p_c","client","ev","venue","quote")}
base = {"org_id": QA, "created_at": "2026-11-22T00:00:00+00:00", "test_tag": "TEST_DJUI"}
for n, suf in (("a","prov_a"),("b","provider"),("c","prov_c")):
    DB.contacts.insert_one({**base, "id": ids[f"c_{n}"], "first_name": f"TEST_DJUI_{n.upper()}", "last_name": n, "email": f"test_djui_{n}@example.com", "language":"fr-FR", "types":["prestataire"]})
    DB.provider_profiles.insert_one({**base, "id": ids[f"p_{n}"], "contact_id": ids[f"c_{n}"], "name": f"TEST_DJUI {n.upper()}", "categories":["dj"], "status":"active", "base_rate":400, "language":"fr-FR"})
DB.contacts.insert_one({**base, "id": ids["client"], "first_name":"TEST_DJUI", "last_name":"Client", "email":"test_djui_client@example.com", "language":"fr-FR", "types":["client"]})
DB.venues.insert_one({**base, "id": ids["venue"], "name":"TEST_DJUI Domaine", "address":"12 chemin des Vignes", "zip":"30000", "city":"Nîmes", "access_instructions":"Parking nord", "onsite_contacts":[]})
DB.events.insert_one({**base, "id": ids["ev"], "title":"TEST_DJUI Mariage", "type":"Mariage", "start":"2027-06-12T18:00", "end":"2027-06-13T03:00", "client_id":ids["client"], "client_contact_ids":[ids["client"]], "venue_id":ids["venue"], "status":"confirme"})
DB.quotes.insert_one({**base, "id": ids["quote"], "event_id":ids["ev"], "number":"TEST_DJUI", "status":"envoye", "valid_until":"2027-01-31", "lines":[], "blocks":[], "active":True})

# Also update QA org to allow dj module
DB.orgs.update_one({"id": QA}, {"$addToSet": {"modules": "dj"}})

# Ensure Clerk users exist for providers A (qa_prov_a) and B (qa_provider) and client (qa_client), attach contact_id
def tok(role, email, cid=None):
    args = ["python3","/app/scripts/qa_token.py", role, email]
    if cid: args.append(cid)
    return subprocess.check_output(args, text=True).strip()
tok("provider", "qa_prov_a+clerk_test@example.com", ids["c_a"])
tok("provider", "qa_provider+clerk_test@example.com", ids["c_b"])
tok("client",   "qa_client+clerk_test@example.com",  ids["client"])
tok("admin",    "qa_admin+clerk_test@example.com")

print(json.dumps(ids))
