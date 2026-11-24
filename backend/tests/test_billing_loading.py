"""Iteration 2 regression: Quotes, Invoices, Payments, PDF, Vehicles, Loading, Cron."""
import os
import time
import uuid

import pytest
import requests

from conftest import API, client


# -------- Quotes / Invoices / Payments --------
class TestBilling:
    def _fresh_event_with_prestations(self, admin):
        r = admin.post(f"{API}/events", json={
            "title": f"TEST_Bill_{int(time.time()*1000)}",
            "start": "2027-10-10T18:00", "end": "2027-10-11T02:00",
        })
        assert r.status_code == 200, r.text
        eid = r.json()["id"]
        r = admin.patch(f"{API}/events/{eid}", json={"prestations": [
            {"module": "dj", "title": "Prestation A HT 20%", "price": 100.0},
            {"module": "dj", "title": "Prestation B HT 5.5%", "price": 33.33},
        ]})
        assert r.status_code == 200, r.text
        return eid

    def test_create_quote_edit_vat_deposit_totals(self, admin):
        eid = self._fresh_event_with_prestations(admin)
        try:
            r = admin.post(f"{API}/events/{eid}/quotes")
            assert r.status_code == 200, r.text
            q = r.json()
            qid = q["id"]
            # Modify lines: mixed VAT, qty 3 of 33.33 @ 5.5%, deposit 30%
            lines = [
                {"label": "A", "description": "", "qty": 1, "unit_price": 100.0, "vat": 20},
                {"label": "B x3 @5.5", "description": "", "qty": 3, "unit_price": 33.33, "vat": 5.5},
            ]
            r = admin.put(f"{API}/quotes/{qid}", json={
                "lines": lines, "deposit_percent": 30, "valid_until": "", "notes": "n"
            })
            assert r.status_code == 200, r.text
            q = r.json()
            # 100 HT @20 => 20 VAT ; 99.99 HT @5.5 => 5.50 VAT
            assert q["total_ht"] == 199.99
            assert q["total_vat"] == pytest.approx(25.5, abs=0.02)
            assert q["total_ttc"] == pytest.approx(q["total_ht"] + q["total_vat"], abs=0.01)
            assert len(q["vat_breakdown"]) == 2

            # Status cycle
            r = admin.post(f"{API}/quotes/{qid}/status", json={"status": "envoye"})
            assert r.status_code == 200 and r.json()["status"] == "envoye"

            # PDF 200
            tok = admin.headers["Authorization"]
            pr = requests.get(f"{API}/quotes/{qid}/pdf", headers={"Authorization": tok})
            assert pr.status_code == 200 and pr.content[:4] == b"%PDF"

            # Acompte
            r = admin.post(f"{API}/quotes/{qid}/invoice", json={"kind": "acompte"})
            assert r.status_code == 200, r.text
            acompte = r.json()
            # Quote is now locked (invoiced)
            r2 = admin.put(f"{API}/quotes/{qid}", json={"lines": lines, "deposit_percent": 30})
            assert r2.status_code == 400

            # Duplicate acompte => 409
            r = admin.post(f"{API}/quotes/{qid}/invoice", json={"kind": "acompte"})
            assert r.status_code == 409

            # Solde
            r = admin.post(f"{API}/quotes/{qid}/invoice", json={"kind": "solde"})
            assert r.status_code == 200, r.text
            solde = r.json()
            # acompte TTC + solde TTC == quote TTC
            ttc_sum = round(acompte["total_ttc"] + solde["total_ttc"], 2)
            assert ttc_sum == pytest.approx(q["total_ttc"], abs=0.02)

            # Duplicate solde => 409
            r = admin.post(f"{API}/quotes/{qid}/invoice", json={"kind": "solde"})
            assert r.status_code == 409

            # Payment overpay => 400
            iid = acompte["id"]
            over = acompte["total_ttc"] + 10
            r = admin.post(f"{API}/invoices/{iid}/payments", json={
                "amount": over, "date": "2026-01-10", "method": "virement"})
            assert r.status_code == 400

            # Partial payment
            partial = round(acompte["total_ttc"] / 2, 2)
            r = admin.post(f"{API}/invoices/{iid}/payments", json={
                "amount": partial, "date": "2026-01-10", "method": "virement"})
            assert r.status_code == 200
            inv = r.json()
            assert inv["status"] == "partielle"
            assert inv["paid_amount"] == pytest.approx(partial, abs=0.01)

            # Cancel payment
            pid = inv["payments"][-1]["id"]
            r = admin.delete(f"{API}/invoices/{iid}/payments/{pid}")
            assert r.status_code == 200 and r.json()["status"] == "emise"

            # Pay full -> event invoice_paid false (solde not paid yet)
            r = admin.post(f"{API}/invoices/{iid}/payments", json={
                "amount": acompte["total_ttc"], "date": "2026-01-10", "method": "virement"})
            assert r.status_code == 200 and r.json()["status"] == "payee"
            ev = admin.get(f"{API}/events/{eid}").json()
            assert ev["deposit_paid"] == pytest.approx(acompte["total_ttc"], abs=0.01)
            assert ev["invoice_paid"] is False

            # Pay solde -> invoice_paid true
            sid = solde["id"]
            r = admin.post(f"{API}/invoices/{sid}/payments", json={
                "amount": solde["total_ttc"], "date": "2026-01-10", "method": "virement"})
            assert r.status_code == 200
            ev = admin.get(f"{API}/events/{eid}").json()
            assert ev["invoice_paid"] is True

            # Manual switch on event should be blocked (guard)
            r = admin.patch(f"{API}/events/{eid}", json={"invoice_paid": False})
            # Either 400 or kept True; just assert it does not falsify when invoices say paid
            ev = admin.get(f"{API}/events/{eid}").json()
            assert ev["invoice_paid"] is True

        finally:
            # Clean-up: events cannot be deleted if they have invoices by current impl? try anyway.
            admin.delete(f"{API}/events/{eid}")

    def test_deposit_zero_no_acompte(self, admin):
        eid = self._fresh_event_with_prestations(admin)
        try:
            r = admin.post(f"{API}/events/{eid}/quotes")
            assert r.status_code == 200
            q = r.json()
            qid = q["id"]
            r = admin.put(f"{API}/quotes/{qid}", json={
                "lines": q["lines"], "deposit_percent": 0, "notes": ""
            })
            assert r.status_code == 200 and r.json()["deposit_percent"] == 0
            r = admin.post(f"{API}/quotes/{qid}/invoice", json={"kind": "acompte"})
            assert r.status_code == 400
            # Solde direct OK
            r = admin.post(f"{API}/quotes/{qid}/invoice", json={"kind": "solde"})
            assert r.status_code == 200
        finally:
            admin.delete(f"{API}/events/{eid}")

    def test_refused_quote_cannot_invoice(self, admin):
        eid = self._fresh_event_with_prestations(admin)
        try:
            qid = admin.post(f"{API}/events/{eid}/quotes").json()["id"]
            admin.post(f"{API}/quotes/{qid}/status", json={"status": "refuse"})
            r = admin.post(f"{API}/quotes/{qid}/invoice", json={"kind": "solde"})
            assert r.status_code == 400
        finally:
            admin.delete(f"{API}/events/{eid}")


# -------- RBAC on billing --------
class TestBillingRBAC:
    def test_technicien_forbidden(self, tech, admin):
        # List & create
        assert tech.get(f"{API}/quotes").status_code == 403
        assert tech.get(f"{API}/invoices").status_code == 403
        # PDF of an existing demo quote
        qs = admin.get(f"{API}/quotes").json()
        if qs:
            qid = qs[0]["id"]
            assert tech.get(f"{API}/quotes/{qid}/pdf").status_code == 403
        invs = admin.get(f"{API}/invoices").json()
        if invs:
            assert tech.get(f"{API}/invoices/{invs[0]['id']}/pdf").status_code == 403

    def test_commercial_can_quote_not_invoice(self, commercial, admin):
        # Can read
        assert commercial.get(f"{API}/quotes").status_code == 200
        # Find a brouillon/envoye quote, else create one
        qs = commercial.get(f"{API}/quotes").json()
        editable = next((q for q in qs if q["status"] in ("brouillon", "envoye")), None)
        if editable is None:
            # create via an existing event they can access
            ev = commercial.get(f"{API}/events").json()[0]
            r = commercial.post(f"{API}/events/{ev['id']}/quotes")
            # may fail if event has no prestations; skip
            if r.status_code != 200:
                pytest.skip("no suitable event to create quote as commercial")
            editable = r.json()
        # Commercial cannot create invoice (requires finance:write)
        r = commercial.post(f"{API}/quotes/{editable['id']}/invoice", json={"kind": "acompte"})
        assert r.status_code == 403
        # Cannot record payment
        invs = admin.get(f"{API}/invoices").json()
        if invs:
            iid = invs[0]["id"]
            r = commercial.post(f"{API}/invoices/{iid}/payments", json={
                "amount": 1, "date": "2026-01-10", "method": "virement"})
            assert r.status_code == 403

    def test_comptable_can_invoice_and_pay(self, compta, admin):
        assert compta.get(f"{API}/invoices").status_code == 200
        # Payment dry-run on an unpaid invoice from demo
        invs = compta.get(f"{API}/invoices").json()
        unpaid = next((i for i in invs if i["balance_due"] > 0.01), None)
        if unpaid:
            r = compta.post(f"{API}/invoices/{unpaid['id']}/payments", json={
                "amount": 0.01, "date": "2026-01-10", "method": "virement", "reference": "TEST_rbac"})
            assert r.status_code == 200
            # Cancel it
            pid = r.json()["payments"][-1]["id"]
            assert compta.delete(f"{API}/invoices/{unpaid['id']}/payments/{pid}").status_code == 200


# -------- Tenant isolation --------
class TestBillingTenant:
    def test_other_org_cannot_see(self, admin):
        qs = admin.get(f"{API}/quotes").json()
        invs = admin.get(f"{API}/invoices").json()
        if not qs or not invs:
            pytest.skip("no demo quote/invoice to test isolation")
        other = client(f"test_tenantbill{int(time.time())}+clerk_test@example.com", "admin", "none")
        r = other.post(f"{API}/onboarding", json={"company_name": "TEST_Org_B", "city": "Nice"})
        assert r.status_code == 200
        assert other.get(f"{API}/quotes/{qs[0]['id']}/pdf").status_code == 404
        assert other.get(f"{API}/invoices/{invs[0]['id']}/pdf").status_code == 404
        # vehicles & loadings isolation
        assert other.get(f"{API}/vehicles").json() == []


# -------- Vehicles --------
class TestVehicles:
    def test_crud(self, admin):
        r = admin.post(f"{API}/vehicles", json={"name": f"TEST_VH_{int(time.time())}", "plate": "AA-123-ZZ",
                                                 "capacity_kg": 500, "volume_m3": 5, "active": True})
        assert r.status_code == 200, r.text
        vid = r.json()["id"]
        r = admin.put(f"{API}/vehicles/{vid}", json={"name": "TEST_VH_renamed", "plate": "AA-123-ZZ",
                                                     "capacity_kg": 600, "volume_m3": 5, "active": True})
        assert r.status_code == 200 and r.json()["capacity_kg"] == 600
        assert any(v["id"] == vid for v in admin.get(f"{API}/vehicles").json())
        # No delete endpoint by design - leave but rename to TEST_ for easy id

    def test_rbac(self, tech, commercial):
        # read: ok
        assert tech.get(f"{API}/vehicles").status_code == 200
        # write: forbidden for tech/commercial (needs catalog:write)
        assert tech.post(f"{API}/vehicles", json={"name": "X"}).status_code == 403
        assert commercial.post(f"{API}/vehicles", json={"name": "X"}).status_code == 403


# -------- Loading --------
class TestLoading:
    def _day_of(self, admin, code):
        ev = admin.get(f"{API}/events").json()
        e = next((x for x in ev if x["code"] == code), None)
        if not e:
            return None
        return e["setup_start"][:10] if e.get("setup_start") else e["start"][:10]

    def test_loading_006(self, admin):
        day = self._day_of(admin, "EVT-2026-006")
        if not day:
            pytest.skip("EVT-2026-006 not found")
        r = admin.get(f"{API}/loading", params={"day": day})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["day"] == day
        loadings = [lo for lo in data["loadings"] if lo["event_code"] == "EVT-2026-006"]
        assert loadings, "loading for EVT-2026-006 missing"
        lo = loadings[0]
        assert lo["lines"]
        assert "vehicles" in data

    def test_report_missing_and_validate(self, admin):
        day = self._day_of(admin, "EVT-2026-010")
        if not day:
            pytest.skip("EVT-2026-010 not found")
        r = admin.get(f"{API}/loading", params={"day": day}).json()
        lo = next(l for l in r["loadings"] if l["event_code"] == "EVT-2026-010")
        lid = lo["id"]
        # Reopen if previously validated (state may be left as 'charge' by prior runs)
        if lo["status"] == "charge":
            admin.post(f"{API}/loading/{lid}/status", json={"status": "en_cours"})
            lo = admin.get(f"{API}/loading", params={"day": day}).json()["loadings"]
            lo = next(l for l in lo if l["event_code"] == "EVT-2026-010")
        first = lo["lines"][0]
        # Report missing 1 on first line
        eid = first["equipment_id"]
        qty = first["qty"]
        r = admin.patch(f"{API}/loading/{lid}/lines/{eid}", json={
            "loaded_qty": max(0, qty - 1), "missing_qty": 1, "note": "TEST_missing"})
        assert r.status_code == 200
        # Over-quantity => 400
        r = admin.patch(f"{API}/loading/{lid}/lines/{eid}", json={
            "loaded_qty": qty + 5, "missing_qty": 0})
        assert r.status_code == 400
        # Reset the chosen line to unchecked state to make the "pending" assertion deterministic
        if len(lo["lines"]) > 1:
            other_eid = next(l["equipment_id"] for l in lo["lines"] if l["equipment_id"] != eid)
            admin.patch(f"{API}/loading/{lid}/lines/{other_eid}", json={"loaded_qty": 0, "missing_qty": 0})
        # Cannot validate when other lines unchecked (if any)
        other_pending = [l for l in lo["lines"] if l["equipment_id"] != eid]
        if other_pending:
            r = admin.post(f"{API}/loading/{lid}/status", json={"status": "charge"})
            assert r.status_code == 400
        # Complete all lines: load fully
        for line in lo["lines"]:
            if line["equipment_id"] == eid:
                admin.patch(f"{API}/loading/{lid}/lines/{eid}", json={
                    "loaded_qty": line["qty"], "missing_qty": 0, "note": ""})
            else:
                admin.patch(f"{API}/loading/{lid}/lines/{line['equipment_id']}", json={
                    "loaded_qty": line["qty"], "missing_qty": 0, "note": ""})
        r = admin.post(f"{API}/loading/{lid}/status", json={"status": "charge"})
        assert r.status_code == 200 and r.json()["status"] == "charge"
        # Reopen
        r = admin.post(f"{API}/loading/{lid}/status", json={"status": "en_cours"})
        assert r.status_code == 200 and r.json()["status"] == "en_cours"

    def test_assign_vehicle(self, admin):
        day = self._day_of(admin, "EVT-2026-007")
        if not day:
            pytest.skip("EVT-2026-007 not found")
        r = admin.get(f"{API}/loading", params={"day": day}).json()
        lo = next((l for l in r["loadings"] if l["event_code"] == "EVT-2026-007"), None)
        if not lo:
            pytest.skip("loading not generated")
        vehicles = admin.get(f"{API}/vehicles").json()
        if not vehicles:
            pytest.skip("no vehicles")
        vid = vehicles[0]["id"]
        r = admin.put(f"{API}/loading/{lo['id']}/vehicle", json={"vehicle_id": vid})
        assert r.status_code == 200 and r.json()["vehicle_id"] == vid
        # Clear
        r = admin.put(f"{API}/loading/{lo['id']}/vehicle", json={"vehicle_id": ""})
        assert r.status_code == 200

    def test_technicien_scope(self, tech):
        r = tech.get(f"{API}/loading", params={"day": "2026-11-25"})
        assert r.status_code == 200


# -------- Cron --------
class TestCron:
    def test_no_auth(self):
        r = requests.post(f"{API}/cron/loading", json={"run_id": "TEST_nothing"})
        assert r.status_code == 401

    def test_wrong_bearer(self):
        r = requests.post(f"{API}/cron/loading", json={"run_id": "TEST_wrong"},
                          headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401

    def test_ok_and_idempotent(self):
        sec = os.environ.get("WEBHOOK_CRON_SECRET")
        if not sec:
            # read from backend .env
            for line in open("/app/backend/.env"):
                if line.startswith("WEBHOOK_CRON_SECRET="):
                    sec = line.split("=", 1)[1].strip()
                    break
        assert sec, "WEBHOOK_CRON_SECRET not found"
        run_id = f"TEST_cron_{uuid.uuid4()}"
        h = {"Authorization": f"Bearer {sec}", "X-Webhook-Id": run_id}
        r = requests.post(f"{API}/cron/loading", json={}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        # idempotent
        r2 = requests.post(f"{API}/cron/loading", json={}, headers=h)
        assert r2.status_code == 200 and r2.json().get("duplicate") is True
