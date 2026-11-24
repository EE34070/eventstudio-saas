"""Iteration 4 regression: quote email send, Yousign stubs (no key -> 503), overdue reminders
(+ cron), deliveries (sync/photos/sign/order/bon PDF), event documents tab, implantation PDF,
org terms + signature fields persist. Uses delivered@resend.dev as the ONLY recipient address."""
import io
import os
import struct
import time
import uuid
import zlib

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio

from conftest import API, client


# ---------- helpers ----------
def _png(w=4, h=4, color=(0, 90, 200)):
    def chunk(t, data):
        c = zlib.crc32(t + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", c)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b""
    for _ in range(h):
        raw += b"\x00" + bytes(color) * w
    idat = zlib.compress(raw, 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _png_data_url(w=240, h=90):
    # Not fully blank - draw a stripe so signature is accepted
    data = _png(w=w, h=h, color=(20, 20, 20))
    import base64
    return "data:image/png;base64," + base64.b64encode(data).decode()


def _blank_png_data_url():
    import base64
    return "data:image/png;base64," + base64.b64encode(_png(4, 4, (255, 255, 255))).decode()


MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
if not MONGO_URL:
    for line in open("/app/backend/.env"):
        if line.startswith("MONGO_URL="):
            MONGO_URL = line.split("=", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("DB_NAME="):
            DB_NAME = line.split("=", 1)[1].strip().strip('"').strip("'")


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


async def _db():
    cli = AsyncIOMotorClient(MONGO_URL)
    return cli, cli[DB_NAME]


async def _get_org_id(admin_email="test_admin+clerk_test@example.com"):
    cli, db = await _db()
    try:
        u = await db.users.find_one({"email": admin_email})
        return u["org_id"] if u else None
    finally:
        cli.close()


async def _db_update(coll, flt, upd):
    cli, db = await _db()
    try:
        return await db[coll].update_one(flt, upd)
    finally:
        cli.close()


async def _db_find_one(coll, flt):
    cli, db = await _db()
    try:
        return await db[coll].find_one(flt, {"_id": 0})
    finally:
        cli.close()


async def _db_delete(coll, flt):
    cli, db = await _db()
    try:
        return await db[coll].delete_many(flt)
    finally:
        cli.close()


DELIVERED = "delivered@resend.dev"


# ---------- TestQuoteSend ----------
class TestQuoteSend:
    created_contacts = []
    created_events = []
    created_quotes = []

    @classmethod
    def teardown_class(cls):
        # Restore any demo records we may have touched (none in this class) + delete TEST_ events
        s = client("test_admin+clerk_test@example.com", "admin")
        for eid in cls.created_events:
            s.delete(f"{API}/events/{eid}")
        for cid in cls.created_contacts:
            s.delete(f"{API}/contacts/{cid}")

    def _make_event_with_contact(self, admin, email=DELIVERED, first="TEST", last="Buyer"):
        tag = uuid.uuid4().hex[:6]
        r = admin.post(f"{API}/contacts", json={"kind": "client", "status": "client",
            "first_name": first, "last_name": f"{last}_{tag}", "company": f"TEST_Co_{tag}",
            "email": email, "phone": "0600000000", "address": "", "city": ""})
        assert r.status_code in (200, 201), r.text
        c = r.json()
        self.__class__.created_contacts.append(c["id"])
        # Need a venue - grab first
        vr = admin.get(f"{API}/venues")
        venues = vr.json()
        venue_id = venues[0]["id"] if venues else ""
        er = admin.post(f"{API}/events", json={
            "title": f"TEST_SendQuote_{tag}", "type": "Mariage",
            "client_id": c["id"], "venue_id": venue_id, "guests": 10,
            "start": "2040-09-12T15:00", "end": "2040-09-13T04:00",
            "setup_start": "2040-09-11T14:00", "return_end": "2040-09-14T10:00"})
        assert er.status_code in (200, 201), er.text
        ev = er.json()
        self.__class__.created_events.append(ev["id"])
        # Add one prestation to the event so quote creation works
        pr = admin.patch(f"{API}/events/{ev['id']}", json={"prestations": [{"module": "loueur_materiel", "title": "Prestation TEST", "price": 500}]})
        assert pr.status_code == 200, pr.text
        # Create quote
        qr = admin.post(f"{API}/events/{ev['id']}/quotes")
        assert qr.status_code in (200, 201), qr.text
        q = qr.json()
        self.__class__.created_quotes.append(q["id"])
        return c, ev, q

    def test_send_no_email_400(self, admin):
        tag = uuid.uuid4().hex[:6]
        r = admin.post(f"{API}/contacts", json={"kind": "client", "status": "client",
            "first_name": "TEST", "last_name": f"NoMail_{tag}", "company": f"TEST_Co_{tag}",
            "email": "", "phone": "", "address": "", "city": ""})
        c = r.json()
        self.__class__.created_contacts.append(c["id"])
        vr = admin.get(f"{API}/venues")
        venue_id = vr.json()[0]["id"]
        er = admin.post(f"{API}/events", json={
            "title": f"TEST_NoMail_{tag}", "type": "Mariage",
            "client_id": c["id"], "venue_id": venue_id, "guests": 10,
            "start": "2041-01-10T15:00", "end": "2041-01-11T04:00",
            "setup_start": "2041-01-09T14:00", "return_end": "2041-01-12T10:00"})
        ev = er.json()
        self.__class__.created_events.append(ev["id"])
        admin.patch(f"{API}/events/{ev['id']}", json={"prestations": [{"module": "loueur_materiel", "title": "X", "price": 100}]})
        q = admin.post(f"{API}/events/{ev['id']}/quotes").json()
        self.__class__.created_quotes.append(q["id"])
        s = admin.post(f"{API}/quotes/{q['id']}/send")
        assert s.status_code == 400
        assert "e-mail" in s.json().get("detail", "").lower()

    def test_send_ok_then_429(self, admin):
        _, ev, q = self._make_event_with_contact(admin)
        assert q["status"] == "brouillon"
        r = admin.post(f"{API}/quotes/{q['id']}/send")
        if r.status_code == 502:
            pytest.skip("Emergent email upstream returned 502 (transient)")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "envoye"
        assert body.get("sent_to") == DELIVERED
        assert body.get("sent_at")
        # Immediate resend -> 429
        r2 = admin.post(f"{API}/quotes/{q['id']}/send")
        assert r2.status_code == 429, r2.text

    def test_send_refused_400(self, admin):
        _, ev, q = self._make_event_with_contact(admin)
        # Move to refuse
        r = admin.post(f"{API}/quotes/{q['id']}/status", json={"status": "refuse"})
        assert r.status_code == 200, r.text
        s = admin.post(f"{API}/quotes/{q['id']}/send")
        assert s.status_code == 400
        assert "refus" in s.json().get("detail", "").lower()

    def test_send_technicien_403(self, admin, tech):
        _, ev, q = self._make_event_with_contact(admin)
        r = tech.post(f"{API}/quotes/{q['id']}/send")
        assert r.status_code == 403

    def test_send_tenant_isolation(self, admin):
        _, ev, q = self._make_event_with_contact(admin)
        other = client(f"test_otherorg_i4_{uuid.uuid4().hex[:4]}+clerk_test@example.com", "admin", "none")
        # Create the other org via onboarding
        o = other.post(f"{API}/onboarding", json={"company_name": f"TEST_OtherOrg_{uuid.uuid4().hex[:4]}"})
        assert o.status_code in (200, 201, 400), o.text
        r = other.post(f"{API}/quotes/{q['id']}/send")
        assert r.status_code == 404


# ---------- TestPublicPdf ----------
class TestPublicPdf:
    def test_public_quote_pdf_ok(self, admin):
        qs = admin.get(f"{API}/quotes").json()
        assert qs, "need a seeded quote"
        q = qs[0]
        token = q.get("share_token") or admin.post(f"{API}/quotes/{q['id']}/share").json()["token"]
        r = requests.get(f"{API}/public/quotes/{token}/pdf")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF-")

    def test_public_quote_pdf_404(self):
        r = requests.get(f"{API}/public/quotes/{'x' * 30}/pdf")
        assert r.status_code == 404

    def test_public_invoice_pdf_ok(self, admin):
        invs = admin.get(f"{API}/invoices").json()
        if not invs:
            pytest.skip("no invoices seeded")
        i = invs[0]
        token = i.get("share_token")
        if not token:
            # invoices get token on first reminder; set one via API not available -> skip
            pytest.skip("no token on invoice")
        r = requests.get(f"{API}/public/invoices/{token}/pdf")
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF-")

    def test_public_invoice_pdf_404(self):
        r = requests.get(f"{API}/public/invoices/{'y' * 30}/pdf")
        assert r.status_code == 404


# ---------- TestYousignStubs (no key) ----------
class TestYousignStubs:
    def test_start_signature_503(self, admin):
        # Build a TEST quote with a contact that has first_name + last_name + email so the 503 is triggered by the missing key, not by validation.
        tag = uuid.uuid4().hex[:6]
        c = admin.post(f"{API}/contacts", json={"kind": "particulier", "status": "client",
            "first_name": "TEST", "last_name": f"Signer_{tag}", "company": "",
            "email": DELIVERED, "phone": "", "address": "", "city": ""}).json()
        vid = admin.get(f"{API}/venues").json()[0]["id"]
        ev = admin.post(f"{API}/events", json={"title": f"TEST_YS_{tag}", "type": "Mariage",
            "client_id": c["id"], "venue_id": vid, "guests": 10,
            "start": "2044-02-10T15:00", "end": "2044-02-11T04:00",
            "setup_start": "2044-02-09T14:00", "return_end": "2044-02-12T10:00"}).json()
        admin.patch(f"{API}/events/{ev['id']}", json={"prestations": [{"module": "loueur_materiel", "title": "X", "price": 100}]})
        q = admin.post(f"{API}/events/{ev['id']}/quotes").json()
        r = admin.post(f"{API}/quotes/{q['id']}/signature")
        assert r.status_code == 503, r.text
        detail = r.json().get("detail", "")
        assert any(k in detail.lower() for k in ("yousign", "signature"))
        admin.delete(f"{API}/events/{ev['id']}")
        admin.delete(f"{API}/contacts/{c['id']}")

    def test_refresh_signature_no_request_400(self, admin):
        qs = admin.get(f"{API}/quotes").json()
        q = next((x for x in qs if not x.get("signature")), qs[0])
        r = admin.post(f"{API}/quotes/{q['id']}/signature/refresh")
        assert r.status_code == 400

    def test_cancel_signature_no_request_400(self, admin):
        qs = admin.get(f"{API}/quotes").json()
        q = qs[0]
        r = admin.post(f"{API}/quotes/{q['id']}/signature/cancel")
        assert r.status_code in (400, 503)

    def test_webhook_yousign_503_when_not_configured(self):
        r = requests.post(f"{API}/webhooks/yousign", json={"event_id": "x", "event_name": "signature_request.done"})
        # 503 when secret not set; 401 when set but bad sig
        assert r.status_code in (503, 401), r.text

    def test_signed_pdf_404(self, admin):
        qs = admin.get(f"{API}/quotes").json()
        q = qs[0]
        r = admin.get(f"{API}/quotes/{q['id']}/signed-pdf")
        assert r.status_code == 404

    def test_edit_blocked_when_signature_ongoing(self, admin):
        # Create a TEST quote, set signature.status=ongoing in DB, verify PUT 400
        tag = uuid.uuid4().hex[:6]
        c = admin.post(f"{API}/contacts", json={"kind": "client", "status": "client",
            "first_name": "TEST", "last_name": f"Sig_{tag}", "company": "TEST_Co",
            "email": DELIVERED, "phone": "", "address": "", "city": ""}).json()
        vid = admin.get(f"{API}/venues").json()[0]["id"]
        ev = admin.post(f"{API}/events", json={"title": f"TEST_Sig_{tag}", "type": "Mariage",
            "client_id": c["id"], "venue_id": vid, "guests": 10,
            "start": "2042-05-10T15:00", "end": "2042-05-11T04:00",
            "setup_start": "2042-05-09T14:00", "return_end": "2042-05-12T10:00"}).json()
        admin.patch(f"{API}/events/{ev['id']}", json={"prestations": [{"module": "loueur_materiel", "title": "X", "price": 100}]})
        q = admin.post(f"{API}/events/{ev['id']}/quotes").json()
        asyncio.run(_db_update("quotes", {"id": q["id"]}, {"$set": {"signature": {"status": "ongoing", "request_id": "fake"}}}))
        put = admin.put(f"{API}/quotes/{q['id']}", json={
            "lines": [{"label": "NewLine", "description": "", "qty": 1, "unit_price": 100, "vat": 20, "equipment_id": ""}],
            "deposit_percent": 30, "valid_until": "", "notes": ""})
        assert put.status_code == 400
        assert "signature" in put.json().get("detail", "").lower()
        # cleanup
        admin.delete(f"{API}/events/{ev['id']}")
        admin.delete(f"{API}/contacts/{c['id']}")


# ---------- TestReminders ----------
class TestReminders:
    """Overdue invoice reminders. Rely on a TEST_ invoice by shifting due_date via DB."""
    overdue_invoice_ids = []
    original_due_dates = {}

    @classmethod
    def teardown_class(cls):
        # restore due dates
        for iid, due in cls.original_due_dates.items():
            asyncio.run(_db_update("invoices", {"id": iid}, {"$set": {"due_date": due, "reminders": [], "auto_level": 0}}))
        # ensure auto_reminders off on demo org
        org_id = asyncio.run(_get_org_id())
        asyncio.run(_db_update("orgs", {"id": org_id}, {"$set": {"auto_reminders": False}}))

    def _make_overdue(self, admin, days_late=10, email=DELIVERED):
        """Pick a seeded invoice to the TEST_ contact (or create one), ensure it has an email contact and past due_date."""
        # Create a TEST contact + event + quote + invoice path is heavy. We'll instead find or create minimal flow.
        tag = uuid.uuid4().hex[:6]
        c = admin.post(f"{API}/contacts", json={"kind": "client", "status": "client",
            "first_name": "TEST", "last_name": f"Over_{tag}", "company": f"TEST_Co_{tag}",
            "email": email, "phone": "", "address": "", "city": ""}).json()
        vid = admin.get(f"{API}/venues").json()[0]["id"]
        ev = admin.post(f"{API}/events", json={"title": f"TEST_Over_{tag}", "type": "Mariage",
            "client_id": c["id"], "venue_id": vid, "guests": 10,
            "start": "2043-03-10T15:00", "end": "2043-03-11T04:00",
            "setup_start": "2043-03-09T14:00", "return_end": "2043-03-12T10:00"}).json()
        admin.patch(f"{API}/events/{ev['id']}", json={"prestations": [{"module": "loueur_materiel", "title": "X", "price": 100}]})
        q = admin.post(f"{API}/events/{ev['id']}/quotes").json()
        admin.post(f"{API}/quotes/{q['id']}/status", json={"status": "accepte"})
        inv = admin.post(f"{API}/quotes/{q['id']}/invoice", json={"kind": "solde"})
        if inv.status_code not in (200, 201):
            # Some backends use a different endpoint name
            inv = admin.post(f"{API}/events/{ev['id']}/invoices", json={"kind": "solde", "quote_id": q["id"]})
        assert inv.status_code in (200, 201), inv.text
        invoice = inv.json()
        iid = invoice["id"]
        # shift due_date to days_late in the past
        from datetime import date, timedelta
        past = (date.today() - timedelta(days=days_late)).isoformat()
        self.__class__.original_due_dates[iid] = invoice["due_date"]
        asyncio.run(_db_update("invoices", {"id": iid}, {"$set": {"due_date": past}}))
        self.__class__.overdue_invoice_ids.append(iid)
        return c, ev, q, invoice

    def test_reminders_list_shows_overdue(self, admin):
        c, ev, q, inv = self._make_overdue(admin, days_late=10)
        r = admin.get(f"{API}/reminders")
        assert r.status_code == 200
        body = r.json()
        assert "auto" in body and "steps" in body and body["steps"] == [7, 15, 30]
        row = next((x for x in body["rows"] if x["id"] == inv["id"]), None)
        assert row, "overdue invoice must be in list"
        assert row["days_late"] >= 10
        assert row["next_level"] >= 1
        assert row["subject"]
        assert inv["number"] in row["message"]
        assert "/api/public/invoices/" in row["message"]
        assert "pdf" in row["message"].lower()

    def test_remind_send_then_429(self, admin):
        c, ev, q, inv = self._make_overdue(admin, days_late=8)
        r = admin.post(f"{API}/invoices/{inv['id']}/remind")
        if r.status_code == 502:
            pytest.skip("Emergent email upstream 502 (transient)")
        assert r.status_code == 200, r.text
        updated = r.json()
        assert updated.get("reminders")
        r2 = admin.post(f"{API}/invoices/{inv['id']}/remind")
        assert r2.status_code == 429

    def test_remind_not_overdue_400(self, admin):
        # Use the same flow but don't shift due_date -> should be future-due
        tag = uuid.uuid4().hex[:6]
        c = admin.post(f"{API}/contacts", json={"kind": "client", "status": "client",
            "first_name": "TEST", "last_name": f"ND_{tag}", "company": "TEST_Co",
            "email": DELIVERED, "phone": "", "address": "", "city": ""}).json()
        vid = admin.get(f"{API}/venues").json()[0]["id"]
        ev = admin.post(f"{API}/events", json={"title": f"TEST_ND_{tag}", "type": "Mariage",
            "client_id": c["id"], "venue_id": vid, "guests": 10,
            "start": "2043-04-10T15:00", "end": "2043-04-11T04:00",
            "setup_start": "2043-04-09T14:00", "return_end": "2043-04-12T10:00"}).json()
        admin.patch(f"{API}/events/{ev['id']}", json={"prestations": [{"module": "loueur_materiel", "title": "X", "price": 100}]})
        q = admin.post(f"{API}/events/{ev['id']}/quotes").json()
        admin.post(f"{API}/quotes/{q['id']}/status", json={"status": "accepte"})
        inv_r = admin.post(f"{API}/quotes/{q['id']}/invoice", json={"kind": "solde"})
        if inv_r.status_code not in (200, 201):
            inv_r = admin.post(f"{API}/events/{ev['id']}/invoices", json={"kind": "solde", "quote_id": q["id"]})
        inv = inv_r.json()
        r = admin.post(f"{API}/invoices/{inv['id']}/remind")
        assert r.status_code == 400
        admin.delete(f"{API}/events/{ev['id']}")
        admin.delete(f"{API}/contacts/{c['id']}")

    def test_comptable_can_commercial_cannot(self, admin, commercial, compta):
        c, ev, q, inv = self._make_overdue(admin, days_late=8)
        # commercial 403 (finance:write role check)
        r1 = commercial.post(f"{API}/invoices/{inv['id']}/remind")
        assert r1.status_code == 403
        # compta 200 (comptable has finance:write); may be 429 if previous test sent within hour
        r2 = compta.post(f"{API}/invoices/{inv['id']}/remind")
        assert r2.status_code in (200, 429, 502)

    def test_technicien_cannot_see_reminders(self, tech):
        r = tech.get(f"{API}/reminders")
        assert r.status_code == 403

    def test_auto_toggle_persists(self, admin):
        r1 = admin.put(f"{API}/reminders/settings", json={"auto": True})
        assert r1.status_code == 200 and r1.json()["auto"] is True
        r2 = admin.get(f"{API}/reminders")
        assert r2.json()["auto"] is True
        r3 = admin.put(f"{API}/reminders/settings", json={"auto": False})
        assert r3.json()["auto"] is False

    def test_cron_reminders_401_without_bearer(self):
        r = requests.post(f"{API}/cron/reminders", json={"run_id": uuid.uuid4().hex})
        assert r.status_code == 401

    def test_cron_reminders_401_wrong_bearer(self):
        r = requests.post(f"{API}/cron/reminders", json={"run_id": uuid.uuid4().hex},
                          headers={"Authorization": "Bearer WRONG"})
        assert r.status_code == 401

    def test_cron_reminders_ok_and_idempotent(self):
        secret = None
        for line in open("/app/backend/.env"):
            if line.startswith("WEBHOOK_CRON_SECRET="):
                secret = line.split("=", 1)[1].strip()
        assert secret, "WEBHOOK_CRON_SECRET missing"
        run_id = uuid.uuid4().hex
        h = {"Authorization": f"Bearer {secret}", "X-Webhook-Id": run_id, "Content-Type": "application/json"}
        r1 = requests.post(f"{API}/cron/reminders", json={}, headers=h)
        assert r1.status_code == 200 and r1.json()["ok"] is True
        r2 = requests.post(f"{API}/cron/reminders", json={}, headers=h)
        assert r2.status_code == 200 and r2.json().get("duplicate") is True


# ---------- TestDeliveries ----------
class TestDeliveries:
    def test_list_for_day_with_confirmed_events(self, admin):
        # EVT-2026-007 setup 2026-12-04, EVT-2026-010 setup 2026-12-19
        r = admin.get(f"{API}/deliveries", params={"day": "2026-12-04"})
        assert r.status_code == 200
        body = r.json()
        assert body["day"] == "2026-12-04"
        codes = [d["event_code"] for d in body["deliveries"]]
        assert "EVT-2026-007" in codes

    def test_reorder_persists(self, admin):
        r = admin.get(f"{API}/deliveries", params={"day": "2026-12-04"})
        ids = [d["id"] for d in r.json()["deliveries"]]
        if len(ids) < 2:
            pytest.skip("need 2+ deliveries for reorder")
        new_order = list(reversed(ids))
        ro = admin.put(f"{API}/deliveries/order", json={"ids": new_order})
        assert ro.status_code == 200
        r2 = admin.get(f"{API}/deliveries", params={"day": "2026-12-04"})
        ids2 = [d["id"] for d in r2.json()["deliveries"]]
        assert ids2 == new_order

    def test_photo_upload_image_only(self, admin):
        r = admin.get(f"{API}/deliveries", params={"day": "2026-12-04"})
        d = next(x for x in r.json()["deliveries"] if x["status"] != "livre")
        s = requests.Session()
        s.headers.update({"Authorization": admin.headers["Authorization"]})
        # text/plain refused
        files = {"file": ("TEST_.txt", b"hello", "text/plain")}
        bad = s.post(f"{API}/deliveries/{d['id']}/photos", files=files)
        assert bad.status_code == 400
        # image ok
        files = {"file": ("TEST_.png", _png(), "image/png")}
        ok = s.post(f"{API}/deliveries/{d['id']}/photos", files=files)
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert len(body["photos"]) >= 1

    def test_sign_empty_signature_refused(self, admin):
        r = admin.get(f"{API}/deliveries", params={"day": "2026-12-19"})
        d = next((x for x in r.json()["deliveries"] if x["status"] != "livre"), None)
        if not d:
            pytest.skip("no unsigned delivery")
        bad = admin.post(f"{API}/deliveries/{d['id']}/sign", json={
            "signer_name": "TEST Signer", "signature": _blank_png_data_url(), "notes": ""})
        assert bad.status_code == 400
        assert "vide" in bad.json().get("detail", "").lower() or "illisible" in bad.json().get("detail", "").lower()

    def test_sign_name_required(self, admin):
        r = admin.get(f"{API}/deliveries", params={"day": "2026-12-19"})
        d = next((x for x in r.json()["deliveries"] if x["status"] != "livre"), None)
        if not d:
            pytest.skip("no unsigned delivery")
        bad = admin.post(f"{API}/deliveries/{d['id']}/sign", json={
            "signer_name": "A", "signature": _png_data_url(), "notes": ""})
        assert bad.status_code in (400, 422)

    def test_sign_ok_then_409_and_bon_pdf(self, admin):
        r = admin.get(f"{API}/deliveries", params={"day": "2026-12-19"})
        d = next((x for x in r.json()["deliveries"] if x["status"] != "livre"), None)
        if not d:
            pytest.skip("no unsigned delivery on 2026-12-19")
        ok = admin.post(f"{API}/deliveries/{d['id']}/sign", json={
            "signer_name": "TEST Receiver", "signature": _png_data_url(), "notes": "TEST notes"})
        assert ok.status_code == 200, ok.text
        signed = ok.json()
        assert signed["status"] == "livre"
        assert signed.get("bon_file", "").startswith("file:")
        # double sign 409
        again = admin.post(f"{API}/deliveries/{d['id']}/sign", json={
            "signer_name": "TEST Receiver", "signature": _png_data_url(), "notes": ""})
        assert again.status_code == 409
        # photo after sign refused
        files = {"file": ("TEST_.png", _png(), "image/png")}
        s = requests.Session()
        s.headers.update({"Authorization": admin.headers["Authorization"]})
        rej = s.post(f"{API}/deliveries/{d['id']}/photos", files=files)
        assert rej.status_code == 400
        # Bon PDF downloadable via /files
        ref = signed["bon_file"]
        fid = ref.split(":", 1)[1] if ":" in ref else ref
        pdf = admin.get(f"{API}/files/{fid}")
        assert pdf.status_code == 200
        assert pdf.content.startswith(b"%PDF-")
        # Appears in event documents
        docs = admin.get(f"{API}/events/{signed['event_id']}/documents").json()
        assert any(d2["ref"] == ref for d2 in docs)
        assert any(d2["kind"] == "Bon de livraison signé" for d2 in docs)


# ---------- TestImplantation ----------
class TestImplantation:
    def test_implantation_pdf(self, admin, events_by_code):
        ev = events_by_code.get("EVT-2026-002") or next(iter(events_by_code.values()))
        r = admin.get(f"{API}/events/{ev['id']}/implantation/pdf")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF-")

    def test_implantation_technicien_non_assigned_404(self, tech, events_by_code):
        # Find an event without current tech in team
        # technicien seeded as Maxime Garcia -> seeded events assign various techs; pick one not in his missions
        # simplest: get tech's events, pick an event code not in that list
        from conftest import API as _A
        my = tech.get(f"{_A}/events").json()
        my_ids = {e["id"] for e in my}
        other = next((e for e in events_by_code.values() if e["id"] not in my_ids), None)
        if other is None:
            pytest.skip("technicien is assigned to all events")
        r = tech.get(f"{API}/events/{other['id']}/implantation/pdf")
        assert r.status_code == 404


# ---------- TestOrgTerms ----------
class TestOrgTerms:
    def test_terms_and_signature_fields_persist(self, admin):
        before = admin.get(f"{API}/org").json()
        orig_terms = before.get("terms", "")
        orig_fields = before.get("signature_fields", [])
        # Build a clean payload matching OrgIn
        keys = ["name", "legal_name", "siret", "vat_number", "address", "zip", "city", "phone", "email",
                "website", "logo_url", "legal_mentions", "iban", "payment_terms", "quote_prefix",
                "invoice_prefix", "default_vat", "deposit_percent", "terms", "signature_fields"]
        base = {k: before.get(k, "") for k in keys}
        base["default_vat"] = before.get("default_vat", 20)
        base["deposit_percent"] = before.get("deposit_percent", 30)
        base["signature_fields"] = orig_fields
        new_terms = "TEST_ Conditions générales § " + uuid.uuid4().hex[:6]
        new_fields = ["Champ A", "Champ B", "Champ C"]
        r = admin.put(f"{API}/org", json={**base, "terms": new_terms, "signature_fields": new_fields})
        assert r.status_code == 200, r.text
        after = admin.get(f"{API}/org").json()
        assert after["terms"] == new_terms
        assert after["signature_fields"] == new_fields
        # max 6
        too_many = ["a", "b", "c", "d", "e", "f", "g"]
        bad = admin.put(f"{API}/org", json={**base, "signature_fields": too_many})
        assert bad.status_code in (400, 422)
        # restore
        admin.put(f"{API}/org", json={**base, "terms": orig_terms, "signature_fields": orig_fields})
