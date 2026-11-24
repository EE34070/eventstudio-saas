"""Iter 40 — abonnements enrichis, prêts & financements. QA uniquement, données TEST_M40 supprimées à la fin."""
import os
import subprocess
import uuid

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

API = "http://localhost:8001/api"
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
RUN = uuid.uuid4().hex[:6]
N = f"TEST_M40 {RUN}"
S = {}


def sess(role="admin"):
    x = requests.Session()
    x.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip().splitlines()[-1]
    return x


@pytest.fixture(scope="module")
def s():
    x = sess()
    yield x
    sids = [d["id"] for d in DB.subscriptions.find({"org_id": QA, "name": {"$regex": f"^{N}"}})]
    iids = [d["id"] for d in DB.purchase_invoices.find({"org_id": QA, "number": {"$regex": f"^{N}"}})]
    DB.subscription_occurrences.delete_many({"org_id": QA, "subscription_id": {"$in": sids}})
    DB.subscription_invoice_matches.delete_many({"org_id": QA, "purchase_invoice_id": {"$in": iids}})
    DB.purchase_invoices.delete_many({"org_id": QA, "id": {"$in": iids}})
    DB.subscriptions.delete_many({"org_id": QA, "id": {"$in": sids}})
    DB.loans.delete_many({"org_id": QA, "name": {"$regex": f"^{N}"}})


def sub(s, name, amount, **kw):
    r = s.post(f"{API}/subscriptions", json={"name": f"{N} {name}", "supplier_name": f"{N} {name}", "amount": amount, "period": "monthly", "renewal_date": "", **kw})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def row(s, sid, kind="subscriptions", as_of="2026-11-23"):
    return next(r for r in s.get(f"{API}/contracts/list", params={"as_of": as_of}).json()[kind] if r["id"] == sid)


def test_commitment_progress(s):
    S["a"] = sid = sub(s, "Logiciel", 49, start_date="2026-03-01", commitment_months=24, notice_days=30)
    r = row(s, sid)
    assert (r["remaining_count"], r["total_count"], r["progress"], r["remaining_amount"]) == (15, 24, 37, 735)
    assert r["time_left"].startswith("1 an 3 mois") and r["end_date"] == "2028-03-01" and r["deadline"] == "2028-01-31" and not r["has_contract"]
    assert row(s, sub(s, "Libre", 10, start_date="2026-01-15"))["time_left"] == "sans engagement"


def test_business_days_and_overrides(s):
    occ = lambda sid, as_of="2026-11-23": {o["contractual_date"]: o for o in s.get(f"{API}/subscriptions/{sid}/occurrences", params={"as_of": as_of}).json()["occurrences"]}  # noqa: E731
    a = occ(sub(s, "Premier", 120, start_date="2026-01-01"))
    assert a["2027-05-01"]["expected_debit_date"] == "2027-05-03" and a["2027-01-01"]["expected_debit_date"] == "2027-01-04"
    assert occ(sub(s, "Sans report", 120, start_date="2026-01-01", business_day_rule="none"))["2027-05-01"]["expected_debit_date"] == "2027-05-01"
    assert "2027-02-28" in occ(sub(s, "Jour 31", 120, start_date="2026-01-31", billing_day=31))
    sid = sub(s, "Tarif", 120, start_date="2026-01-01")
    assert s.put(f"{API}/subscriptions/{sid}/occurrences/2099-03-01", json={"amount": 180, "reason": "hors horizon"}).status_code == 400
    assert s.put(f"{API}/subscriptions/{sid}/occurrences/2027-03-01", json={"amount": 180}).status_code == 422
    assert s.put(f"{API}/subscriptions/{sid}/occurrences/2027-03-01", json={"amount": 180, "reason": "hausse ponctuelle"}).status_code == 200
    o = occ(sid)
    assert (o["2027-03-01"]["expected_amount"], o["2027-04-01"]["expected_amount"], o["2027-03-01"]["is_manual_override"]) == (180, 120, True)
    s.put(f"{API}/subscriptions/{sid}/occurrences/2027-03-01", json={"amount": 180, "reason": "nouveau tarif", "following": True})
    assert occ(sid)["2027-06-01"]["expected_amount"] == 180
    s.delete(f"{API}/subscriptions/{sid}/occurrences/2027-03-01")
    assert occ(sid)["2027-06-01"]["expected_amount"] == 120


def inv(s, supplier, ht, number, day="2026-11-05", **kw):
    r = s.post(f"{API}/purchase-invoices", json={"supplier_name": f"{N} {supplier}", "number": f"{N} {number}", "date": day, "amount_ht": ht, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_invoice_matching(s):
    render = sub(s, "Render", 25, start_date="2026-01-05")
    r = inv(s, "Render", 25, "R-11")
    assert r["subscription_status"] == "linked" and r["subscription_links"][0]["occurrence"] == "2026-11-05" and r["subscription_links"][0]["delta"] == 0
    o = next(x for x in s.get(f"{API}/subscriptions/{render}/occurrences").json()["occurrences"] if x["contractual_date"] == "2026-11-05")
    assert o["status"] == "facturee" and o["purchase_invoice_ids"] == [r["id"]]
    gw = sub(s, "Google Workspace", 13.80, start_date="2026-01-05")
    g = inv(s, "Google Workspace", 16.10, "G-11")
    assert g["subscription_status"] == "to_confirm"
    p = {x["id"]: x for x in s.get(f"{API}/subscription-invoices/pending").json()}
    assert (p[g["id"]]["candidates"][0]["delta"], p[g["id"]]["candidates"][0]["delta_pct"]) == (2.3, 16.7)
    dom = sub(s, "Google Workspace domaine", 1, start_date="2026-01-05")
    done = s.post(f"{API}/subscription-invoices/{g['id']}/link", json={"links": [{"subscription_id": gw, "amount": 15.10}, {"subscription_id": dom, "amount": 1}]}).json()
    assert done["subscription_status"] == "linked" and [x["subscription_id"] for x in done["subscription_links"]] == [gw, dom] and done["subscription_links"][0]["delta"] == 1.3
    c = inv(s, "Canva", 110, "C-1", category="abonnement annuel")
    assert c["subscription_status"] == "to_create"
    sug = next(x for x in s.get(f"{API}/subscription-invoices/pending").json() if x["id"] == c["id"])["suggested"]
    assert sug["amount"] == 110 and sug["period"] == "yearly" and sug["start_date"] == "2026-11-05"
    assert s.post(f"{API}/subscription-invoices/{c['id']}/link", json={"ignore": True}).json()["subscription_status"] == "ignored"
    assert "subscription_status" not in inv(s, "Plombier", 300, "P-1")


def test_loans_schedule_import_simulate_calendar(s):
    base = {"name": f"{N} Camion", "bank": "Crédit Agricole", "capital": 30000, "rate_pct": 4, "months": 60, "first_due_date": "2026-01-05"}
    lid = s.post(f"{API}/loans", json=base).json()["id"]
    r = row(s, lid, "loans")
    assert (r["total_count"], r["remaining_count"], r["installment"], r["end_date"]) == (60, 49, 552.5, "2030-12-05") and 24000 < r["remaining_principal"] < 25500 and r["split"]["interest"] > 0
    full = s.get(f"{API}/loans/{lid}", params={"as_of": "2026-11-23"}).json()
    assert full["schedule"][-1]["remaining_principal"] == 0 and round(sum(x["principal"] for x in full["schedule"])) == 30000
    sim = s.get(f"{API}/loans/{lid}/simulate", params={"amount": 5000, "as_of": "2026-11-23"}).json()
    assert sim["new_installments"] < 49 and sim["interest_saved"] > 0 and sim["penalty"] == 100
    assert s.get(f"{API}/loans/{lid}/simulate", params={"amount": 5000, "mode": "payment", "as_of": "2026-11-23"}).json()["new_payment"] < 552.5
    assert s.put(f"{API}/loans/{lid}/installments/1", json={"amount": 1, "reason": "test"}).status_code == 400
    imp = s.post(f"{API}/loans", json={**base, "name": f"{N} Importé", "installments": [{"contractual_date": f"2027-{m:02d}-10", "principal": 500, "interest": 60, "insurance": 5, "total": 565, "remaining_principal": 6000 - 500 * m} for m in range(1, 13)]}).json()
    g = s.get(f"{API}/loans/{imp['id']}", params={"as_of": "2026-11-23"}).json()
    assert g["total_count"] == 12 and g["schedule"][0]["expected_debit_date"] == "2027-01-10" and g["gap_alert"]
    fine = row(s, s.post(f"{API}/loans", json={**base, "name": f"{N} In fine", "type": "in_fine", "months": 12}).json()["id"], "loans", "2026-01-01")
    lease = s.post(f"{API}/loans", json={**base, "name": f"{N} LOA", "type": "lease", "capital": 0, "months": 36, "rent": 400, "first_rent": 2000, "option_value": 3000, "option_date": "2026-12-20"}).json()
    lv = row(s, lease["id"], "loans")
    assert fine["installment"] == 100 and lv["alert"].startswith("levée") and lv["category"].startswith("Crédit-bail")
    cal = s.get(f"{API}/debits", params={"start": "2026-12-01", "end": "2026-12-31", "as_of": "2026-11-23"}).json()
    mine = [x for x in cal["rows"] if x["name"].startswith(N)]
    assert {x["kind"] for x in mine} == {"subscription", "loan"} and round(sum(d["total"] for d in cal["by_day"]), 2) == cal["total"] == round(sum(a["total"] for a in cal["by_account"]), 2)
    f = s.get(f"{API}/contracts/list", params={"as_of": "2026-11-23"}).json()
    assert f["footer"]["monthly_total"] == round(f["footer"]["monthly_subscriptions"] + f["footer"]["monthly_loans"], 2) and round(f["footer"]["monthly_loans"], 2) == round(sum(x["monthly"] for x in f["loans"]), 2)
    for fmt in ("xlsx", "pdf"):
        assert s.get(f"{API}/contracts/export", params={"kind": "loans", "format": fmt}).status_code == 200
    t = sess("technicien")
    assert t.get(f"{API}/contracts/list").status_code == 403 and t.get(f"{API}/debits").status_code == 403 and requests.get(f"{API}/loans/{lid}").status_code == 401
    assert sess("commercial").post(f"{API}/loans", json=base).status_code == 403
