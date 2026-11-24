"""Backend e2e for iter 15 — Prompt 9 (Logistics) + Prompt 8 corrections.

Targets the QA sandbox org only (slug qa-sandbox) via qa_token.py.
Never touches 'Exclusivity Events' or TEST_ companies. All created records
are prefixed TEST_P9i15_ and cleaned up by id at module teardown.
No real messages: the only email allowed is contact@exclusivity-events.com and
the reminder-send test monkeypatches the mailer, so no email actually leaves.
"""
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta

import pytest
import requests

from conftest import API

PREFIX = "TEST_P9i15_"
RUN = uuid.uuid4().hex[:6]
ALLOWED_EMAIL = "contact@exclusivity-events.com"

_tokens: dict[str, str] = {}
_sessions: dict[str, requests.Session] = {}


def qa_token(role="admin"):
    if role in _tokens:
        return _tokens[role]
    out = subprocess.run(["python3", "/app/scripts/qa_token.py", role],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        pytest.skip(f"qa_token failed: {out.stderr[-300:]}")
    _tokens[role] = out.stdout.strip().splitlines()[-1]
    return _tokens[role]


def sess(role="admin") -> requests.Session:
    if role in _sessions:
        return _sessions[role]
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {qa_token(role)}", "Content-Type": "application/json"})
    _sessions[role] = s
    return s


_created: dict[str, list[str]] = {
    "vehicles": [], "equipment": [], "venues": [], "contacts": [],
    "events": [], "quotes": [], "tasks": [], "warehouses": [],
}


def _rm(path, items):
    s = sess("admin")
    for i in items:
        try:
            s.delete(f"{API}/{path}/{i}")
        except Exception:
            pass


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    _rm("quotes", _created["quotes"])
    _rm("events", _created["events"])
    _rm("tasks", _created["tasks"])
    _rm("venues", _created["venues"])
    _rm("contacts", _created["contacts"])
    _rm("equipment", _created["equipment"])
    _rm("vehicles", _created["vehicles"])


# ============================================================================
# Helpers
# ============================================================================
_VENUE_FIELDS = ("name", "type", "address", "zip", "city", "lat", "lng", "capacity",
                 "power_capacity_w", "contact_name", "contact_phone", "contact_email",
                 "onsite_contacts", "truck_access", "electricity", "sound_limiter",
                 "setup_hours", "teardown_hours", "access_instructions", "photos",
                 "plans", "sections", "notes")


def _mk_venue(s, name_suffix="", lat=None, lng=None, logistics=None, onsite_contacts=None):
    body = {"name": f"{PREFIX}{name_suffix}_{RUN}", "type": "Domaine",
            "address": "12 rue du Test", "zip": "30000", "city": "Nîmes"}
    if lat is not None:
        body["lat"], body["lng"] = lat, lng
    if onsite_contacts:
        body["onsite_contacts"] = onsite_contacts
    r = s.post(f"{API}/venues", json=body)
    assert r.status_code in (200, 201), r.text
    v = r.json()
    _created["venues"].append(v["id"])
    if logistics:
        r = s.put(f"{API}/venues/{v['id']}/logistics", json=logistics)
        assert r.status_code == 200, r.text
    return v


def _update_venue(s, v, **over):
    body = {k: v.get(k) for k in _VENUE_FIELDS}
    # normalise None lists
    for k in ("onsite_contacts", "photos", "plans", "sections"):
        if body.get(k) is None:
            body[k] = [] if k != "onsite_contacts" else None
    body.update(over)
    r = s.put(f"{API}/venues/{v['id']}", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _mk_eq(s, name, qty=500, cat="mobilier"):
    r = s.post(f"{API}/equipment", json={
        "name": f"{PREFIX}{name}_{RUN}",
        "ref": f"P9{uuid.uuid4().hex[:6].upper()}",
        "category": cat, "qty_total": qty, "unit": "u",
        "weight_kg": 2.0, "volume_m3": 0.05,
    })
    assert r.status_code in (200, 201), r.text
    eq = r.json()
    _created["equipment"].append(eq["id"])
    return eq


def _mk_contact(s, lang="fr-FR", email=None):
    email = email or f"c.{uuid.uuid4().hex[:8]}@example.com"
    r = s.post(f"{API}/contacts", json={
        "kind": "particulier", "first_name": f"{PREFIX}First",
        "last_name": f"Last{RUN}", "email": email,
        "phone": "+33612345678", "types": ["client"], "language": lang,
    })
    assert r.status_code in (200, 201), r.text
    c = r.json()
    _created["contacts"].append(c["id"])
    return c


def _mk_event(s, venue_id, client_id, title, start_date=None, equipment=None, status=None):
    if not start_date:
        start_date = (datetime.utcnow() + timedelta(days=45)).strftime("%Y-%m-%d")
    body = {
        "title": f"{PREFIX}{title}_{RUN}", "type": "Mariage",
        "client_id": client_id, "client_contact_ids": [client_id],
        "signatory_contact_id": client_id,
        "venue_id": venue_id,
        "start": f"{start_date}T18:00", "end": f"{start_date}T23:59",
        "guests": 50, "modules": ["loueur_materiel"],
    }
    r = s.post(f"{API}/events", json=body)
    assert r.status_code == 200, r.text
    ev = r.json()
    _created["events"].append(ev["id"])
    if equipment:
        r = s.patch(f"{API}/events/{ev['id']}", json={"equipment": equipment})
        assert r.status_code == 200, r.text
        ev = r.json()
    if status:
        r = s.post(f"{API}/events/{ev['id']}/status", json={"status": status})
        assert r.status_code == 200, r.text
        ev = r.json()
    return ev


def _mk_vehicle(s, name, **over):
    body = {"name": f"{PREFIX}{name}_{RUN}", "plate": f"AA-{uuid.uuid4().hex[:3].upper()}-ZZ",
            "type": "utilitaire", "licence_required": "B", "tailgate": True,
            "length_m": 5.5, "height_m": 2.5, "capacity_kg": 1200, "seats": 3,
            "cost_km": 0.5, "ownership": "propre", "active": True,
            "ct_due": "", "insurance_due": "", "service_due": "",
            "unavailabilities": [], "rental_start": "", "rental_end": "", "rental_cost": 0,
            "volume_m3": 10}
    body.update(over)
    r = s.post(f"{API}/vehicles", json=body)
    assert r.status_code in (200, 201), r.text
    v = r.json()
    _created["vehicles"].append(v["id"])
    return v


# ============================================================================
# 1. Correction P8 #1 — urgent reminder failure (monkeypatched mailer)
# ============================================================================
class TestCorrection1UrgentReminderFailure:
    """Via fastapi TestClient + monkeypatch of routes_stock._send.
    Verifies the route returns 502 reminder_failed and NOTHING persists
    (no last_urgent_reminder_at, no urgent_reminders row, no 'Relance urgente'
    history line) and the 48h block does NOT trigger on retry.
    """

    @pytest.fixture(scope="class")
    def tc(self):
        sys.path.insert(0, "/app/backend")
        try:
            from fastapi.testclient import TestClient
            from server import app
        except Exception as e:
            pytest.skip(f"cannot import app: {e}")
        # Enter context so a single BlockingPortal/event-loop is reused across
        # requests — Motor caches its io loop on first call.
        client = TestClient(app, raise_server_exceptions=False)
        with client as c:
            yield c

    @pytest.fixture(scope="class")
    def quote_ready(self):
        """Create a confirmed event + send a quote on it so status='envoye'."""
        s = sess("admin")
        v = _mk_venue(s, "FailVenue")
        c = _mk_contact(s, email=ALLOWED_EMAIL)
        eq = _mk_eq(s, "FailChair", qty=500)
        ev = _mk_event(s, v["id"], c["id"], "FailEv",
                       equipment=[{"equipment_id": eq["id"], "qty": 10, "price_day": 5}])
        # direct quote on existing event
        r = s.post(f"{API}/quotes/direct", json={
            "event_id": ev["id"], "lines": [{"label": f"{PREFIX}Chair", "qty": 10,
                                              "unit_price": 10, "vat": 20, "equipment_id": eq["id"]}],
        })
        assert r.status_code == 200, r.text
        q = r.json()
        _created["quotes"].append(q["id"])
        # send the quote
        r = s.post(f"{API}/quotes/{q['id']}/status", json={"status": "envoye"})
        assert r.status_code == 200, r.text
        return q

    def _fetch_quote(self, q_id):
        return sess("admin").get(f"{API}/quotes/{q_id}").json()

    def _urgent_count(self, q_id):
        # endpoint for urgent_reminders list is not available; infer via quote.history
        q = self._fetch_quote(q_id)
        return sum(1 for h in q.get("history") or [] if h.get("action") == "Relance urgente")

    def test_failure_http_exception_returns_502_and_persists_nothing(self, tc, quote_ready, monkeypatch):
        import routes_stock
        from fastapi import HTTPException

        async def boom(fn, **kw):
            raise HTTPException(502, "SMTP down")
        monkeypatch.setattr(routes_stock, "_send", boom)

        tok = qa_token("admin")
        r = tc.post(f"/api/quotes/{quote_ready['id']}/urgent-reminder",
                    headers={"Authorization": f"Bearer {tok}"},
                    json={"deadline": "", "set_deadline": True})
        assert r.status_code == 502, r.text
        d = r.json().get("detail") or {}
        assert d.get("code") == "reminder_failed"
        assert d.get("message", "").startswith("La relance n'a pas pu être envoyée")

        q = self._fetch_quote(quote_ready["id"])
        assert not q.get("last_urgent_reminder_at"), q.get("last_urgent_reminder_at")
        assert self._urgent_count(quote_ready["id"]) == 0

    def test_failure_generic_exception_also_502_no_persistence(self, tc, quote_ready, monkeypatch):
        import routes_stock

        async def boom(fn, **kw):
            raise RuntimeError("boom")
        monkeypatch.setattr(routes_stock, "_send", boom)

        tok = qa_token("admin")
        r = tc.post(f"/api/quotes/{quote_ready['id']}/urgent-reminder",
                    headers={"Authorization": f"Bearer {tok}"},
                    json={"deadline": "", "set_deadline": True})
        assert r.status_code == 502, r.text
        d = r.json().get("detail") or {}
        assert d.get("code") == "reminder_failed"
        assert d.get("message", "").startswith("La relance n'a pas pu être envoyée")

        q = self._fetch_quote(quote_ready["id"])
        assert not q.get("last_urgent_reminder_at")
        assert self._urgent_count(quote_ready["id"]) == 0

    def test_retry_not_blocked_by_48h_rule_after_failures(self, tc, quote_ready):
        """A retry WITHOUT monkeypatch must NOT be blocked by 409 reminder_recent."""
        tok = qa_token("admin")
        r = tc.post(f"/api/quotes/{quote_ready['id']}/urgent-reminder",
                    headers={"Authorization": f"Bearer {tok}"},
                    json={"deadline": "", "set_deadline": True})
        # The real mailer may fail (SMTP not configured) -> 502 is acceptable,
        # but 409 reminder_recent would mean the 48h rule got armed on a failed send.
        if r.status_code == 409:
            d = (r.json() or {}).get("detail") or {}
            assert d.get("code") != "reminder_recent", \
                f"48h block incorrectly triggered after a failed send: {d}"
        else:
            assert r.status_code in (200, 502), r.text


# ============================================================================
# 2. Correction P8 #2 — PATCH option_expires_at with past date releases immediately
# ============================================================================
class TestCorrection2PastOption:
    def _release_cycle(self, status):
        s = sess("admin")
        v = _mk_venue(s, f"Opt{status}")
        c = _mk_contact(s, email=f"opt.{uuid.uuid4().hex[:6]}@example.com")
        eq = _mk_eq(s, f"OptChair{status}", qty=300)
        ev = _mk_event(s, v["id"], c["id"], f"OptEv{status}",
                       equipment=[{"equipment_id": eq["id"], "qty": 20, "price_day": 5}])
        r = s.post(f"{API}/quotes/direct", json={
            "event_id": ev["id"], "lines": [{"label": f"{PREFIX}Chair", "qty": 20,
                                              "unit_price": 10, "vat": 20, "equipment_id": eq["id"]}],
        })
        assert r.status_code == 200, r.text
        q = r.json()
        _created["quotes"].append(q["id"])
        if status == "envoye":
            r = s.post(f"{API}/quotes/{q['id']}/status", json={"status": "envoye"})
            assert r.status_code == 200
        # PATCH with past date
        past = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d")
        r = s.patch(f"{API}/quotes/{q['id']}/option",
                    json={"option_expires_at": past})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("option_released_at"), f"option_released_at missing: {body}"
        # Task 'Relancer ou clôturer le devis <number>'
        r = s.get(f"{API}/tasks")
        assert r.status_code == 200
        want = f"Relancer ou clôturer le devis {q['number']}"
        all_tasks = r.json().get("tasks", []) if isinstance(r.json(), dict) else r.json()
        tasks = [t for t in all_tasks if t.get("title") == want]
        assert tasks, f"task '{want}' not found; got titles: {[t.get('title') for t in all_tasks if 'devis' in (t.get('title') or '').lower()][:10]}"
        for t in tasks:
            _created["tasks"].append(t["id"])
        return q

    def test_past_date_on_sent_releases_and_creates_task(self):
        self._release_cycle("envoye")

    def test_past_date_on_draft_releases_and_creates_task(self):
        self._release_cycle("brouillon")

    def test_future_date_keeps_option_active(self):
        s = sess("admin")
        v = _mk_venue(s, "OptFut")
        c = _mk_contact(s, email=f"fut.{uuid.uuid4().hex[:6]}@example.com")
        eq = _mk_eq(s, "FutChair", qty=100)
        ev = _mk_event(s, v["id"], c["id"], "FutEv",
                       equipment=[{"equipment_id": eq["id"], "qty": 5, "price_day": 5}])
        r = s.post(f"{API}/quotes/direct", json={
            "event_id": ev["id"], "lines": [{"label": f"{PREFIX}Chair", "qty": 5,
                                              "unit_price": 10, "vat": 20, "equipment_id": eq["id"]}],
        })
        q = r.json()
        _created["quotes"].append(q["id"])
        future = (datetime.utcnow() + timedelta(days=10)).strftime("%Y-%m-%d")
        r = s.patch(f"{API}/quotes/{q['id']}/option",
                    json={"option_expires_at": future})
        assert r.status_code == 200
        assert not r.json().get("option_released_at"), r.json()


# ============================================================================
# 3. Vehicles — new fields persisted + fleet_alerts at 30 days
# ============================================================================
class TestVehicles:
    def test_create_and_update_vehicle_with_new_fields(self):
        s = sess("admin")
        v = _mk_vehicle(s, "Master", type="utilitaire", licence_required="B",
                        tailgate=True, length_m=5.5, height_m=2.5,
                        ct_due="2026-12-01", insurance_due="2026-12-15",
                        service_due="2026-11-01")
        assert v["type"] == "utilitaire"
        assert v["licence_required"] == "B"
        assert v["tailgate"] is True
        assert v["length_m"] == 5.5
        assert v["height_m"] == 2.5
        assert v["ct_due"] == "2026-12-01"
        # Update
        r = s.put(f"{API}/vehicles/{v['id']}", json={
            **{k: v.get(k) for k in ("name", "plate", "capacity_kg", "volume_m3", "active",
                                       "type", "licence_required", "tailgate", "length_m",
                                       "height_m", "seats", "cost_km", "ownership", "ct_due",
                                       "insurance_due", "service_due", "unavailabilities",
                                       "rental_start", "rental_end", "rental_cost")},
            "length_m": 6.0, "licence_required": "C",
        })
        assert r.status_code == 200, r.text
        assert r.json()["length_m"] == 6.0
        assert r.json()["licence_required"] == "C"

    def test_fleet_alert_within_30_days(self):
        s = sess("admin")
        soon = (datetime.utcnow() + timedelta(days=15)).strftime("%Y-%m-%d")
        v = _mk_vehicle(s, "Soon", ct_due=soon)
        today = datetime.utcnow().strftime("%Y-%m-%d")
        r = s.get(f"{API}/logistics/day", params={"day": today})
        assert r.status_code == 200, r.text
        fleet = r.json().get("fleet_alerts") or []
        assert any(a["vehicle"] == v["name"] and a["date"] == soon for a in fleet), \
            f"no fleet alert found for {v['name']} on {soon}: {fleet}"


# ============================================================================
# 4. Matrix (vehicle × product / family) — product value > family value
# ============================================================================
class TestCapacityMatrix:
    def test_matrix_crud_and_product_overrides_family(self):
        s = sess("admin")
        veh = _mk_vehicle(s, "Mx")
        eq = _mk_eq(s, "MxChair", qty=300, cat="TEST_MXCAT")
        # family row
        r = s.put(f"{API}/logistics/capacities",
                  json={"vehicle_id": veh["id"], "key": f"fam:TEST_MXCAT",
                        "max_qty": 150})
        assert r.status_code == 200, r.text
        # product row
        r = s.put(f"{API}/logistics/capacities",
                  json={"vehicle_id": veh["id"], "key": eq["id"], "max_qty": 200})
        assert r.status_code == 200, r.text
        # read back
        r = s.get(f"{API}/logistics/capacities")
        d = r.json()
        assert any(v["id"] == veh["id"] for v in d["vehicles"])
        assert any(p["id"] == eq["id"] for p in d["products"])
        assert "TEST_MXCAT" in d["families"]
        cells = {(c["vehicle_id"], c["key"]): c["max_qty"] for c in d["cells"]}
        assert cells.get((veh["id"], eq["id"])) == 200
        assert cells.get((veh["id"], "fam:TEST_MXCAT")) == 150

        # Empty value -> stored as 0 (unknown/empty)
        r = s.put(f"{API}/logistics/capacities",
                  json={"vehicle_id": veh["id"], "key": eq["id"], "max_qty": None})
        assert r.status_code == 200
        d = s.get(f"{API}/logistics/capacities").json()
        cell = next((c for c in d["cells"] if c["vehicle_id"] == veh["id"]
                     and c["key"] == eq["id"]), None)
        assert cell is not None and cell["max_qty"] == 0


# ============================================================================
# 5. Generate logistics plan — missions + delivery_start pre-fill
# ============================================================================
class TestGenerate:
    def test_generate_creates_livraison_and_retrait_with_delivery_start(self):
        s = sess("admin")
        v = _mk_venue(s, "Gen", logistics={
            "delivery_address": "", "access_hours": "", "delivery_start": "09:30",
            "delivery_end": "11:00", "pickup_start": "17:00", "pickup_end": "19:00",
            "max_length_m": 0, "max_height_m": 0, "max_tonnage_t": 0,
            "tailgate_required": False, "dock_distance_m": 0, "stairs": "",
            "parking": "", "gate_code": "", "instructions": "",
            "preferred_channel": "email", "reminders_off": False,
        })
        c = _mk_contact(s)
        eq = _mk_eq(s, "GenChair", qty=400)
        ev = _mk_event(s, v["id"], c["id"], "Gen",
                       equipment=[{"equipment_id": eq["id"], "qty": 30, "price_day": 5}],
                       status="confirme")
        r = s.post(f"{API}/events/{ev['id']}/logistics/generate")
        assert r.status_code == 200, r.text
        d = r.json()
        types = {m["type"] for m in d["missions"]}
        assert {"livraison", "retrait"}.issubset(types), types
        liv = next(m for m in d["missions"] if m["type"] == "livraison")
        assert liv["window_start"] == "09:30", liv


# ============================================================================
# 6. RBAC — technicien 403 on generate / auto / capacities PUT
# ============================================================================
class TestRbac:
    def test_tech_cannot_generate(self):
        admin = sess("admin")
        tech = sess("technicien")
        v = _mk_venue(admin, "RbacGen")
        c = _mk_contact(admin)
        eq = _mk_eq(admin, "RbacChair", qty=50)
        ev = _mk_event(admin, v["id"], c["id"], "RbacGen",
                       equipment=[{"equipment_id": eq["id"], "qty": 5, "price_day": 5}],
                       status="confirme")
        r = tech.post(f"{API}/events/{ev['id']}/logistics/generate")
        assert r.status_code == 403, r.text

    def test_tech_cannot_put_capacities(self):
        admin = sess("admin")
        veh = _mk_vehicle(admin, "RbacV")
        tech = sess("technicien")
        r = tech.put(f"{API}/logistics/capacities",
                     json={"vehicle_id": veh["id"], "key": "fam:test", "max_qty": 10})
        assert r.status_code == 403, r.text

    def test_tech_cannot_auto_place(self):
        # Use an existing mission via admin generate
        admin = sess("admin")
        tech = sess("technicien")
        v = _mk_venue(admin, "RbacAuto")
        c = _mk_contact(admin)
        eq = _mk_eq(admin, "RbacAutoCh", qty=50)
        ev = _mk_event(admin, v["id"], c["id"], "RbacAuto",
                       equipment=[{"equipment_id": eq["id"], "qty": 5, "price_day": 5}],
                       status="confirme")
        r = admin.post(f"{API}/events/{ev['id']}/logistics/generate")
        liv = next(m for m in r.json()["missions"] if m["type"] == "livraison")
        r = tech.post(f"{API}/logistics/missions/{liv['id']}/auto",
                      json={"mode": "auto"})
        assert r.status_code == 403, r.text


# ============================================================================
# 7. Venue reminders — J-1 draft default, EN contact -> english, de-dup
# ============================================================================
class TestVenueReminders:
    def test_run_creates_english_draft_j1_no_dup(self):
        s = sess("admin")
        from zoneinfo import ZoneInfo
        tomorrow = (datetime.now(ZoneInfo("Europe/Paris")) + timedelta(days=1)).strftime("%Y-%m-%d")
        v = _mk_venue(s, "ReminderVen", logistics={
            "delivery_start": "10:00", "delivery_end": "12:00",
            "pickup_start": "17:00", "pickup_end": "19:00",
            "delivery_address": "", "access_hours": "", "max_length_m": 0,
            "max_height_m": 0, "max_tonnage_t": 0, "tailgate_required": False,
            "dock_distance_m": 0, "stairs": "", "parking": "", "gate_code": "",
            "instructions": "", "preferred_channel": "email", "reminders_off": False,
        })
        # Add an English onsite contact
        _update_venue(s, v, onsite_contacts=[{
            "name": "John", "role": "regisseur", "phone": "",
            "email": ALLOWED_EMAIL, "language": "en-US", "is_primary": True,
        }])

        c = _mk_contact(s)
        eq = _mk_eq(s, "ReminderCh", qty=50)
        ev = _mk_event(s, v["id"], c["id"], "ReminderEv",
                       start_date=tomorrow,
                       equipment=[{"equipment_id": eq["id"], "qty": 3, "price_day": 5}],
                       status="confirme")
        # Generate logistics missions so reminders have a target
        r = s.post(f"{API}/events/{ev['id']}/logistics/generate")
        assert r.status_code == 200, r.text
        liv_id = next(m["id"] for m in r.json()["missions"] if m["type"] == "livraison")

        # Run reminders (idempotent)
        r1 = s.post(f"{API}/logistics/reminders/run")
        assert r1.status_code == 200, r1.text
        # Second run should not dup
        r2 = s.post(f"{API}/logistics/reminders/run")
        assert r2.status_code == 200

        logs = s.get(f"{API}/logistics/reminders").json()["logs"]
        mine = [l for l in logs if l.get("mission_id") == liv_id and l.get("rule") == "j1"]
        assert len(mine) == 1, f"expected 1 j1 log, got {len(mine)}: {mine}"
        log = mine[0]
        assert log["status"] == "draft", log
        assert log["language"].startswith("en"), log
        assert "Reminder" in log["subject"] or "delivery" in log["subject"].lower(), log["subject"]
        assert log["to"] == ALLOWED_EMAIL
        pytest.p9_reminder_id = log["id"]
        pytest.p9_reminder_body = log["body"]
        pytest.p9_reminder_subject = log["subject"]

    def test_rule_auto_then_back_to_draft(self):
        s = sess("admin")
        # Fetch current rules
        d = s.get(f"{API}/logistics/reminders").json()["rules"]
        new = [{"key": r["key"], "channel": r["channel"],
                "mode": "auto" if r["key"] == "j7" else r["mode"],
                "active": r["active"], "days": r["days"]} for r in d]
        r = s.put(f"{API}/logistics/reminders/rules", json={"rules": new})
        assert r.status_code == 200
        assert any(x["key"] == "j7" and x["mode"] == "auto" for x in r.json())
        # Back to draft
        back = [{"key": r["key"], "channel": r["channel"], "mode": "draft",
                 "active": r["active"], "days": r["days"]} for r in new]
        r = s.put(f"{API}/logistics/reminders/rules", json={"rules": back})
        assert r.status_code == 200
        assert all(x["mode"] == "draft" for x in r.json())
