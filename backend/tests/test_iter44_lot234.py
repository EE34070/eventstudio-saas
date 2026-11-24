"""Iter 44 — Devis ajout rapide (produit + prestation libre), prêts/abonnements overrides, debits, RBAC.
QA sandbox only. Cleans up TEST_ records it creates.
"""
import os
import subprocess
from datetime import date, timedelta

import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE:
    for _line in open("/app/frontend/.env"):
        if _line.startswith("REACT_APP_BACKEND_URL="):
            BASE = _line.split("=", 1)[1].strip().rstrip("/")

LOCKED_MSG = "Échéance déjà prélevée ou rapprochée : son montant n'est plus modifiable"


def _tok(role="admin"):
    out = subprocess.run(["python3", "/app/scripts/qa_token.py", role], capture_output=True, text=True, check=True)
    return out.stdout.strip().splitlines()[-1]


def _sess(role="admin"):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {_tok(role)}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin():
    return _sess("admin")


@pytest.fixture(scope="module")
def technicien():
    return _sess("technicien")


@pytest.fixture(scope="module")
def commercial():
    return _sess("commercial")


@pytest.fixture(scope="module")
def created(admin):
    bag = {"equipment_ids": [], "loan_ids": [], "subscription_ids": []}
    yield bag
    # cleanup loans (soft delete exposed) & subscriptions
    for lid in bag["loan_ids"]:
        try:
            admin.delete(f"{BASE}/api/loans/{lid}")
        except Exception:
            pass
    for sid in bag["subscription_ids"]:
        try:
            admin.delete(f"{BASE}/api/subscriptions/{sid}")
        except Exception:
            pass
    # equipment: no deletion route; archive if possible
    for eid in bag["equipment_ids"]:
        try:
            admin.put(f"{BASE}/api/equipment/{eid}", json={"archived": True})
        except Exception:
            pass


# ---------- LOT 1: Ajout rapide / NewProduct ----------

class TestQuickProduct:
    def test_quick_product_admin_creates_tocomplete(self, admin, created):
        payload = {
            "name": "TEST_M44 Machine à bulles",
            "category": "Effets spéciaux",
            "subcategory": "Bulles",
            "product_type": "Location",
            "price_day": 45,
            "qty_total": 2,
        }
        r = admin.post(f"{BASE}/api/equipment/quick", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["name"] == payload["name"]
        assert data["to_complete"] is True
        assert data["ref"].startswith("EFF-BUL-"), data["ref"]
        assert len(data["ref"].split("-")[-1]) == 3
        created["equipment_ids"].append(data["id"])

        # verify persistence via list endpoint (no GET-by-id for equipment)
        g = admin.get(f"{BASE}/api/equipment")
        assert g.status_code == 200
        items = g.json().get("items", [])
        found = next((e for e in items if e.get("id") == data["id"]), None)
        assert found is not None, "created equipment not in list"
        assert found.get("to_complete") is True
        assert found["ref"] == data["ref"]

    def test_quick_product_technicien_forbidden(self, technicien):
        r = technicien.post(f"{BASE}/api/equipment/quick", json={
            "name": "TEST_M44 denied", "category": "Divers",
        })
        assert r.status_code in (401, 403), r.text

    def test_quick_product_commercial_forbidden(self, commercial):
        r = commercial.post(f"{BASE}/api/equipment/quick", json={
            "name": "TEST_M44 denied2", "category": "Divers",
        })
        assert r.status_code in (401, 403), r.text


class TestCatalogSearchFree:
    def test_search_returns_free_array_for_admin(self, admin):
        r = admin.get(f"{BASE}/api/catalog/search", params={"q": "technicien"})
        assert r.status_code == 200
        body = r.json()
        assert "items" in body and "free" in body
        assert isinstance(body["free"], list)
        # free entries have label + uses
        for f in body["free"]:
            assert "label" in f and "uses" in f and isinstance(f["uses"], int)

    def test_search_no_access_for_technicien_free_hidden(self, technicien):
        # technicien has catalog:read but not finance:read -> free list must be empty
        r = technicien.get(f"{BASE}/api/catalog/search", params={"q": "technicien"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("free", []) == []

    def test_search_requires_auth(self):
        r = requests.get(f"{BASE}/api/catalog/search", params={"q": "enceinte"})
        assert r.status_code == 401


# ---------- LOT 3: Prêts — override échéances ----------

class TestLoanOverride:
    @pytest.fixture(scope="class")
    def loan(self, admin, created):
        first_due = (date.today() + timedelta(days=45)).replace(day=5).isoformat()
        payload = {
            "name": "TEST_M44 prêt",
            "bank": "TEST bank",
            "type": "amortissable",
            "capital": 12000,
            "rate_pct": 3.0,
            "months": 12,
            "period": "monthly",
            "first_due_date": first_due,
            "business_day_rule": "next",
        }
        r = admin.post(f"{BASE}/api/loans", json=payload)
        assert r.status_code == 200, r.text
        lid = r.json()["id"]
        created["loan_ids"].append(lid)
        return lid

    def test_override_detail_following_false(self, admin, loan):
        r = admin.get(f"{BASE}/api/loans/{loan}")
        assert r.status_code == 200
        sched = r.json()["schedule"]
        future = [row for row in sched if row["status"] == "a_venir"]
        assert future, "Loan should have future rows"
        target = future[1]  # second future installment
        n = target["n"]
        body = {
            "principal": 500, "interest": 40, "insurance": 0, "fees": 10,
            "reason": "TEST_M44 révision", "following": False,
        }
        r2 = admin.put(f"{BASE}/api/loans/{loan}/installments/{n}", json=body)
        assert r2.status_code == 200, r2.text
        updated = r2.json()
        row = next(x for x in updated["schedule"] if x["n"] == n)
        assert abs(row["total"] - 550) < 0.01
        assert row["is_manual_override"] is True
        assert row["history"], "history should be present"
        # Non-following: next row should be close to the pre-existing amount (not propagated)
        nxt = next(x for x in updated["schedule"] if x["n"] == n + 1)
        assert abs(nxt["total"] - 550) > 0.01 or nxt.get("is_manual_override") in (False, None)
        # Remaining principal recalculated: final row principal adjusts; last row should bring remaining_principal to 0
        last = updated["schedule"][-1]
        assert abs(last["remaining_principal"]) < 1.0, f"last remaining_principal={last['remaining_principal']}"

    def test_override_reset_restores(self, admin, loan):
        sched = admin.get(f"{BASE}/api/loans/{loan}").json()["schedule"]
        # find the overridden row from previous test
        target = next((r for r in sched if r.get("is_manual_override")), None)
        assert target is not None
        n = target["n"]
        r = admin.delete(f"{BASE}/api/loans/{loan}/installments/{n}")
        assert r.status_code == 200, r.text
        row = next(x for x in r.json()["schedule"] if x["n"] == n)
        assert not row["is_manual_override"] or row.get("override_reason", "") == ""
        # history still kept (reset event appended)
        assert row["history"], "history must still carry the reset event"

    def test_override_following_true(self, admin, loan):
        sched = admin.get(f"{BASE}/api/loans/{loan}").json()["schedule"]
        future = [r for r in sched if r["status"] == "a_venir"]
        target = future[0]
        n = target["n"]
        body = {"amount": 1111, "reason": "TEST_M44 et suivantes", "following": True}
        r = admin.put(f"{BASE}/api/loans/{loan}/installments/{n}", json=body)
        assert r.status_code == 200, r.text
        updated = r.json()["schedule"]
        # Every future row from n onward should be 1111 OR carry propagated recomputed total.
        # Behaviour: next untouched rows should follow -> check row n+1 is also 1111.
        nxt = next(x for x in updated if x["n"] == n + 1)
        assert abs(nxt["total"] - 1111) < 0.01 or nxt.get("is_manual_override"), (
            f"following=True but row {n+1} total={nxt['total']}"
        )

    def test_override_past_installment_rejected(self, admin, created):
        # Create a tiny loan with first_due in the past -> first installment is "passed" and locked
        past = (date.today() - timedelta(days=90)).isoformat()
        r = admin.post(f"{BASE}/api/loans", json={
            "name": "TEST_M44 prêt passé", "bank": "TEST", "type": "amortissable",
            "capital": 1200, "rate_pct": 2.0, "months": 12, "period": "monthly",
            "first_due_date": past,
        })
        assert r.status_code == 200, r.text
        lid = r.json()["id"]
        created["loan_ids"].append(lid)
        sched = admin.get(f"{BASE}/api/loans/{lid}").json()["schedule"]
        past_row = next((row for row in sched if row["status"] == "payee"), None)
        assert past_row is not None, f"expected at least one paid installment, got statuses={[r['status'] for r in sched[:3]]}"
        n = past_row["n"]
        r2 = admin.put(f"{BASE}/api/loans/{lid}/installments/{n}", json={
            "amount": 100, "reason": "TEST_M44 should fail"
        })
        assert r2.status_code == 400
        assert LOCKED_MSG in r2.json().get("detail", ""), r2.json()

    def test_debits_reflect_override(self, admin, loan, created):
        # Fresh loan to avoid interference from previous test
        first_due = (date.today() + timedelta(days=45)).replace(day=10).isoformat()
        r = admin.post(f"{BASE}/api/loans", json={
            "name": "TEST_M44 prêt debit", "bank": "TEST", "type": "amortissable",
            "capital": 6000, "rate_pct": 2.5, "months": 12, "period": "monthly",
            "first_due_date": first_due,
        })
        assert r.status_code == 200
        lid = r.json()["id"]
        created["loan_ids"].append(lid)
        sched = admin.get(f"{BASE}/api/loans/{lid}").json()["schedule"]
        future = [row for row in sched if row["status"] == "a_venir"]
        target = future[0]
        new_amt = 777.77
        admin.put(f"{BASE}/api/loans/{lid}/installments/{target['n']}", json={
            "amount": new_amt, "reason": "TEST_M44 debit check"
        })
        # Query debits over a window covering target date
        start = (date.today() - timedelta(days=5)).isoformat()
        end = (date.today() + timedelta(days=400)).isoformat()
        d = admin.get(f"{BASE}/api/debits", params={"start": start, "end": end})
        assert d.status_code == 200
        rows = [r for r in d.json()["rows"] if r.get("name") == "TEST_M44 prêt debit"]
        assert any(abs(r["amount"] - new_amt) < 0.01 for r in rows), (
            f"override not reflected in /debits: {rows}"
        )


# ---------- LOT 3b: Subscriptions ----------

class TestSubscriptionOverride:
    @pytest.fixture(scope="class")
    def sub(self, admin, created):
        start = (date.today() + timedelta(days=10)).isoformat()
        r = admin.post(f"{BASE}/api/subscriptions", json={
            "name": "TEST_M44 abonnement",
            "supplier_name": "TEST_M44 SaaS",
            "amount": 99.0,
            "period": "monthly",
            "start_date": start,
            "business_day_rule": "next",
        })
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        created["subscription_ids"].append(sid)
        return sid

    def test_override_single_occurrence(self, admin, sub):
        occ = admin.get(f"{BASE}/api/subscriptions/{sub}/occurrences").json()["occurrences"]
        future = [o for o in occ if o["status"] == "a_venir"]
        assert future
        target = future[1]
        day = target["contractual_date"]
        r = admin.put(f"{BASE}/api/subscriptions/{sub}/occurrences/{day}", json={
            "amount": 150, "reason": "TEST_M44 unique", "following": False
        })
        assert r.status_code == 200, r.text
        rows = r.json()["occurrences"]
        row = next(o for o in rows if o["contractual_date"] == day)
        assert row["expected_amount"] == 150
        assert row["is_manual_override"]
        # following=False so next one stays original
        nxt = next(o for o in rows if o["contractual_date"] > day)
        assert nxt["expected_amount"] == 99.0

    def test_override_following_and_reset(self, admin, created):
        # Use a dedicated subscription to isolate from previous overrides
        start = (date.today() + timedelta(days=10)).isoformat()
        r0 = admin.post(f"{BASE}/api/subscriptions", json={
            "name": "TEST_M44 abo suivantes", "supplier_name": "TEST", "amount": 99.0,
            "period": "monthly", "start_date": start, "business_day_rule": "next",
        })
        assert r0.status_code == 200
        sub = r0.json()["id"]
        created["subscription_ids"].append(sub)

        occ = admin.get(f"{BASE}/api/subscriptions/{sub}/occurrences").json()["occurrences"]
        future = [o for o in occ if o["status"] == "a_venir"]
        target = future[0]
        day = target["contractual_date"]
        r = admin.put(f"{BASE}/api/subscriptions/{sub}/occurrences/{day}", json={
            "amount": 200, "reason": "TEST_M44 suivantes", "following": True
        })
        assert r.status_code == 200
        rows = r.json()["occurrences"]
        after = [o for o in rows if o["contractual_date"] >= day and o["status"] == "a_venir"]
        assert all(o["expected_amount"] == 200 for o in after[:3]), (
            [(o["contractual_date"], o["expected_amount"]) for o in after[:5]]
        )
        # reset
        r2 = admin.delete(f"{BASE}/api/subscriptions/{sub}/occurrences/{day}")
        assert r2.status_code == 200
        reset_row = next(o for o in r2.json()["occurrences"] if o["contractual_date"] == day)
        assert reset_row["expected_amount"] == 99.0

    def test_subscription_past_locked(self, admin, created):
        # create a sub with start_date in the past -> first occurrence is past
        start = (date.today() - timedelta(days=90)).isoformat()
        r = admin.post(f"{BASE}/api/subscriptions", json={
            "name": "TEST_M44 abo passé", "supplier_name": "TEST", "amount": 10.0,
            "period": "monthly", "start_date": start,
        })
        assert r.status_code == 200
        sid = r.json()["id"]
        created["subscription_ids"].append(sid)
        occ = admin.get(f"{BASE}/api/subscriptions/{sid}/occurrences").json()["occurrences"]
        past = [o for o in occ if o["status"] == "passee"]
        assert past, "should have past occurrences"
        day = past[0]["contractual_date"]
        r2 = admin.put(f"{BASE}/api/subscriptions/{sid}/occurrences/{day}", json={
            "amount": 5, "reason": "TEST_M44 should fail"
        })
        assert r2.status_code == 400
        assert LOCKED_MSG in r2.json().get("detail", "")
