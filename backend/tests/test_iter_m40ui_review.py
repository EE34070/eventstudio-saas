"""Iter M40UI — Review (abonnements, prêts, factures, sécurité). Uses existing TEST_M40UI seed."""
import os
import subprocess

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

API = "http://localhost:8001/api"
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]


def tok(role):
    return subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip().splitlines()[-1]


def sess(role="admin"):
    x = requests.Session()
    x.headers["Authorization"] = "Bearer " + tok(role)
    return x


@pytest.fixture(scope="module")
def s():
    return sess()


# ---- Review point 1: GET /api/contracts/list?as_of=2026-11-23 for TEST_M40UI Logiciel ----
def test_logiciel_progress(s):
    r = s.get(f"{API}/contracts/list", params={"as_of": "2026-11-23"})
    assert r.status_code == 200
    subs = r.json().get("subscriptions", [])
    log = next((x for x in subs if x.get("name") == "TEST_M40UI Logiciel"), None)
    assert log is not None, "TEST_M40UI Logiciel not found - seed missing?"
    # 15/24 occurrences, 37% progress, 735 € remaining (24-15=9 * 49 + manque M12 inclus, 15/24=62.5%?)
    # per review: 15 / 24, 37 %, 735 €, « 1 an 3 mois »
    # Actually 15 passed out of 24 total means 9 remaining -> 9*49=441 remaining... let me check what fields exist
    print("LOGICIEL FIELDS:", list(log.keys()))
    print("LOGICIEL:", log)
    # review mentions: 15 / 24 (remaining? passed?), 37%, 735 €, 1 an 3 mois
    assert log.get("remaining_count") == 15 or log.get("installments_left") == 15 or log.get("left") == 15, log
    assert log.get("total_count") == 24 or log.get("installments_total") == 24, log
    rem = log.get("remaining_amount") or log.get("remaining") or 0
    assert 700 <= rem <= 770, f"remaining amount {rem} not ~735"
    assert log.get("missing_contract") is True or log.get("has_contract") is False


# ---- Totals in footer ----
def test_footer_totals(s):
    r = s.get(f"{API}/contracts/list", params={"as_of": "2026-11-23"})
    data = r.json()
    assert "footer" in data, f"missing footer in response, keys={list(data.keys())}"
    f = data["footer"]
    assert "monthly_subscriptions" in f and "monthly_loans" in f and "monthly_total" in f, f
    assert "remaining_total" in f and "remaining_principal_total" in f, f
    print("FOOTER:", f)


# ---- Review point 2: candidates for TEST_M40UI-G (should propose link to Google Workspace) ----
def test_pending_invoices(s):
    r = s.get(f"{API}/subscription-invoices/pending")
    assert r.status_code == 200
    items = r.json()
    print("PENDING KEYS:", items if isinstance(items, list) else list(items.keys()))
    pend = items if isinstance(items, list) else items.get("items", [])
    g = next((x for x in pend if (x.get("number") or x.get("invoice", {}).get("number")) == "TEST_M40UI-G"), None)
    assert g is not None, f"TEST_M40UI-G not found in pending: {pend}"
    print("TEST_M40UI-G:", g)


# ---- Review point 3: TEST_M40UI Camion loan schedule ----
def test_camion_loan(s):
    lid = (DB.loans.find_one({"org_id": QA, "name": "TEST_M40UI Camion"}) or {}).get("id")
    assert lid, "Camion loan missing"
    r = s.get(f"{API}/loans/{lid}", params={"as_of": "2026-11-23"})
    assert r.status_code == 200
    d = r.json()
    print("LOAN KEYS:", list(d.keys()))
    sched = d.get("schedule") or d.get("installments") or []
    assert len(sched) == 60, f"expected 60 installments, got {len(sched)}"
    last = sched[-1]
    rem = last.get("remaining_principal", 0)
    assert rem < 1, f"last installment remaining {rem} not 0"
    pay = d.get("installment") or d.get("monthly")
    assert 550 <= pay <= 555, f"payment {pay} not ~552.50"
    assert d.get("total_count") == 60
    assert d.get("end_date") == "2030-12-05"


# ---- Simulator ----
def test_simulator(s):
    lid = (DB.loans.find_one({"org_id": QA, "name": "TEST_M40UI Camion"}) or {}).get("id")
    r = s.get(f"{API}/loans/{lid}/simulate", params={"amount": 5000, "mode": "duration", "as_of": "2026-11-23"})
    assert r.status_code == 200, r.text
    print("SIM DURATION:", r.json())
    r2 = s.get(f"{API}/loans/{lid}/simulate", params={"amount": 5000, "mode": "payment", "as_of": "2026-11-23"})
    assert r2.status_code == 200
    print("SIM PAYMENT:", r2.json())


# ---- Debits calendar ----
def test_debits(s):
    r = s.get(f"{API}/debits", params={"start": "2026-11-23", "end": "2027-02-23"})
    assert r.status_code == 200
    d = r.json()
    print("DEBITS KEYS:", list(d.keys()) if isinstance(d, dict) else "list")
    assert d  # not empty


# ---- Exports ----
@pytest.mark.parametrize("kind,fmt", [("subscriptions", "xlsx"), ("subscriptions", "pdf"), ("loans", "xlsx"), ("loans", "pdf")])
def test_exports(s, kind, fmt):
    r = s.get(f"{API}/contracts/export", params={"kind": kind, "format": fmt, "as_of": "2026-11-23"})
    assert r.status_code == 200, f"{kind}/{fmt} failed: {r.status_code}"
    assert len(r.content) > 100


# ---- Security: technician 403 ----
def test_security_technicien():
    t = sess("technicien")
    assert t.get(f"{API}/contracts/list").status_code == 403
    assert t.get(f"{API}/debits").status_code == 403
    # /api/loans is POST only; GET /loans/<id> list? Check list
    r = t.get(f"{API}/subscription-invoices/pending")
    assert r.status_code == 403


def test_security_commercial_cannot_create_loan():
    c = sess("commercial")
    r = c.post(f"{API}/loans", json={"name": "TEST_M40UI Forbidden", "bank": "X", "capital": 1000, "rate_pct": 2, "months": 12, "first_due_date": "2026-06-01"})
    assert r.status_code == 403, f"commercial should get 403, got {r.status_code}"
