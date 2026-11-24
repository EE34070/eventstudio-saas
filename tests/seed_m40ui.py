"""Seed QA pour l'écran Abonnements / Prêts (TEST_M40UI). `clean` supprime uniquement ces données de test."""
import os, subprocess, sys, requests
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from pymongo import MongoClient
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
API = "http://localhost:8001/api"
if sys.argv[1:] == ["clean"]:
    rx = {"$regex": "^TEST_M40UI"}
    sids = [d["id"] for d in DB.subscriptions.find({"org_id": QA, "name": rx})]; lids = [d["id"] for d in DB.loans.find({"org_id": QA, "name": rx})]
    iids = [d["id"] for d in DB.purchase_invoices.find({"org_id": QA, "$or": [{"number": rx}, {"supplier_name": rx}]})]
    DB.subscription_occurrences.delete_many({"org_id": QA, "subscription_id": {"$in": sids}}); DB.subscription_invoice_matches.delete_many({"org_id": QA, "purchase_invoice_id": {"$in": iids}})
    DB.contract_documents.delete_many({"org_id": QA, "owner_id": {"$in": sids + lids}}); DB.purchase_invoices.delete_many({"org_id": QA, "id": {"$in": iids}})
    print("cleaned", DB.subscriptions.delete_many({"org_id": QA, "id": {"$in": sids}}).deleted_count, DB.loans.delete_many({"org_id": QA, "id": {"$in": lids}}).deleted_count); sys.exit()
s = requests.Session(); s.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", "admin"], text=True).strip().splitlines()[-1]
sub = lambda n, a, **k: s.post(f"{API}/subscriptions", json={"name": f"TEST_M40UI {n}", "supplier_name": f"TEST_M40UI {n}", "amount": a, "period": "monthly", "renewal_date": "", **k}).status_code
print(sub("Logiciel", 49, start_date="2026-03-01", commitment_months=24, notice_days=30), sub("Google Workspace", 13.8, start_date="2026-01-05"),
      s.post(f"{API}/loans", json={"name": "TEST_M40UI Camion", "bank": "Crédit Agricole", "capital": 30000, "rate_pct": 4, "months": 60, "first_due_date": "2026-01-05"}).status_code,
      s.post(f"{API}/purchase-invoices", json={"supplier_name": "TEST_M40UI Google Workspace", "number": "TEST_M40UI-G", "date": "2026-11-05", "amount_ht": 16.1}).json().get("subscription_status"),
      s.post(f"{API}/purchase-invoices", json={"supplier_name": "TEST_M40UI Canva", "number": "TEST_M40UI-C", "date": "2026-11-05", "amount_ht": 110, "category": "abonnement annuel"}).json().get("subscription_status"))
