"""Iter 12 — Prompt 7: Navigation + admin pages (menu, dashboard, To do, auto tasks, CRM tasks,
expenses, purchase invoices, subscriptions, team CDDU, planning assign, search).
All tests target the qa-sandbox org via /app/scripts/qa_token.py.
Data created with TEST_P7 prefix; cleaned up by id at teardown.
"""
import io
import os
import subprocess
import time
import uuid

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in open("/app/frontend/.env"):
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
API = BASE_URL + "/api"

_mongo = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
_ORG = _mongo.orgs.find_one({"slug": "qa-sandbox"})  # created by qa_token.py
_tok_cache: dict = {}

CREATED = {"tasks": [], "expenses": [], "purchases": [], "subs": [],
           "events": [], "team": [], "vehicles": [], "equipment": [], "contacts": [], "venues": [],
           "providers": [], "opportunities": []}


def _tok(role: str) -> str:
    if role not in _tok_cache:
        out = subprocess.run(["python3", "/app/scripts/qa_token.py", role],
                             capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            pytest.skip(f"qa_token.py {role} failed: {out.stderr[-300:]}")
        _tok_cache[role] = out.stdout.strip().splitlines()[-1]
    return _tok_cache[role]


def c(role: str = "admin") -> requests.Session:
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {_tok(role)}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin():
    # Ensure qa-sandbox org exists via first call
    _tok("admin")
    return c("admin")


@pytest.fixture(scope="module")
def tech():
    return c("technicien")


@pytest.fixture(scope="module")
def commercial():
    return c("commercial")


@pytest.fixture(scope="module")
def comptable():
    return c("comptable")


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    org = _mongo.orgs.find_one({"slug": "qa-sandbox"})
    if not org:
        return
    org_id = org["id"]
    # Delete by id
    _mongo.tasks.delete_many({"org_id": org_id, "id": {"$in": CREATED["tasks"]}})
    _mongo.expense_reports.delete_many({"org_id": org_id, "id": {"$in": CREATED["expenses"]}})
    _mongo.purchase_invoices.delete_many({"org_id": org_id, "id": {"$in": CREATED["purchases"]}})
    _mongo.subscriptions.delete_many({"org_id": org_id, "id": {"$in": CREATED["subs"]}})
    _mongo.events.delete_many({"org_id": org_id, "id": {"$in": CREATED["events"]}})
    _mongo.team.delete_many({"org_id": org_id, "id": {"$in": CREATED["team"]}})
    _mongo.vehicles.delete_many({"org_id": org_id, "id": {"$in": CREATED["vehicles"]}})
    _mongo.equipment.delete_many({"org_id": org_id, "id": {"$in": CREATED["equipment"]}})
    _mongo.contacts.delete_many({"org_id": org_id, "id": {"$in": CREATED["contacts"]}})
    _mongo.venues.delete_many({"org_id": org_id, "id": {"$in": CREATED["venues"]}})
    _mongo.provider_profiles.delete_many({"org_id": org_id, "id": {"$in": CREATED["providers"]}})
    _mongo.opportunities.delete_many({"org_id": org_id, "id": {"$in": CREATED["opportunities"]}})
    # auto-tasks for cleaned events
    _mongo.tasks.delete_many({"org_id": org_id, "source_ref": {"$in": [f"loading:{e}" for e in CREATED["events"]]}})


# ------------------------------------------------------------- /api/menu

class TestMenu:
    def test_admin_sees_everything(self, admin):
        r = admin.get(f"{API}/menu")
        assert r.status_code == 200
        d = r.json()
        assert d["hidden"] == []
        assert isinstance(d["hidden_all"], dict)
        assert "badges" in d and isinstance(d["badges"], dict)
        for k in ("loadings", "deliveries", "tasks_overdue", "tasks_today", "messages", "crm"):
            assert k in d["badges"]

    def test_technicien_hides_admin_section(self, tech, admin):
        # Ensure default hidden config (fresh orgs rely on the fallback inside menu_hidden();
        # once anything was ever saved it may be an empty dict — seed it explicitly).
        admin_keys = ["devis", "factures", "contacts", "lieux", "equipe",
                      "notes-de-frais", "factures-achat", "abonnements", "organisation"]
        org = _mongo.orgs.find_one({"slug": "qa-sandbox"})
        prev = org.get("menu_hidden")
        admin.put(f"{API}/org/menu-visibility", json={"hidden": {"technicien": admin_keys}})
        try:
            r = tech.get(f"{API}/menu")
            assert r.status_code == 200
            d = r.json()
            for k in admin_keys:
                assert k in d["hidden"], f"technicien should hide {k}"
            assert d["hidden_all"] is None  # not allowed to see global config
        finally:
            if prev is None:
                _mongo.orgs.update_one({"slug": "qa-sandbox"}, {"$unset": {"menu_hidden": ""}})
            else:
                admin.put(f"{API}/org/menu-visibility",
                          json={"hidden": prev if isinstance(prev, dict) else {}})

    def test_menu_prefs_persistence(self, admin):
        payload = {"collapsed_sections": ["parc"], "dashboard_widgets": [
            {"key": "today", "visible": True}, {"key": "events14", "visible": False}]}
        r = admin.put(f"{API}/menu/prefs", json=payload)
        assert r.status_code == 200
        r2 = admin.get(f"{API}/menu")
        assert r2.status_code == 200
        p = r2.json()["prefs"]
        assert p["collapsed_sections"] == ["parc"]
        assert p["dashboard_widgets"] == payload["dashboard_widgets"]

    def test_menu_visibility_toggle_hides_for_role(self, admin, commercial):
        org = _mongo.orgs.find_one({"slug": "qa-sandbox"})
        prev = org.get("menu_hidden")
        prev_dict = prev if isinstance(prev, dict) else {}
        # Hide 'notes-de-frais' for commercial
        body = {"hidden": {**prev_dict, "commercial": sorted(set((prev_dict.get("commercial") or []) + ["notes-de-frais"]))}}
        r = admin.put(f"{API}/org/menu-visibility", json=body)
        assert r.status_code == 200
        try:
            r2 = commercial.get(f"{API}/menu")
            assert r2.status_code == 200
            assert "notes-de-frais" in r2.json()["hidden"]
        finally:
            if prev is None:
                _mongo.orgs.update_one({"slug": "qa-sandbox"}, {"$unset": {"menu_hidden": ""}})
            else:
                admin.put(f"{API}/org/menu-visibility", json={"hidden": prev_dict})

    def test_visibility_rejects_admin_key(self, admin):
        r = admin.put(f"{API}/org/menu-visibility", json={"hidden": {"admin": ["devis"]}})
        assert r.status_code == 200
        assert "admin" not in r.json()["hidden"]


# ----------------------------------------------------- /api/search

class TestSearch:
    def test_search_shape(self, admin):
        r = admin.get(f"{API}/search", params={"q": "TEST"})
        assert r.status_code == 200
        d = r.json()
        for k in ("events", "contacts", "venues", "equipment", "quotes", "invoices"):
            assert k in d, f"missing {k} in search payload"

    def test_search_technicien_no_finance_keys(self, tech):
        r = tech.get(f"{API}/search", params={"q": "zz"})
        assert r.status_code == 200
        d = r.json()
        assert "quotes" not in d and "invoices" not in d


# ----------------------------------------------------- Tasks + quick add

class TestTasks:
    def test_crud_and_quick(self, admin):
        r = admin.post(f"{API}/tasks", json={"title": "TEST_P7 tache"})
        assert r.status_code == 200
        tid = r.json()["id"]
        CREATED["tasks"].append(tid)
        r = admin.patch(f"{API}/tasks/{tid}", json={"status": "done"})
        assert r.status_code == 200 and r.json()["status"] == "done"
        # list contains it
        rows = admin.get(f"{API}/tasks").json()["tasks"]
        assert any(t["id"] == tid for t in rows)

    def test_quick_tomorrow_10h(self, admin):
        r = admin.post(f"{API}/tasks/quick", json={"text": "TEST_P7 rappeler le domaine demain 10h"})
        assert r.status_code == 200, r.text
        d = r.json()
        CREATED["tasks"].append(d["id"])
        assert "T10:00" in d["due_at"] or d["due_at"].endswith("T10:00")

    def test_overdue_badge(self, admin):
        # Create an overdue task; since created_by_id is the admin user_id with no assignees,
        # the "mine" filter will include it
        r = admin.post(f"{API}/tasks", json={"title": "TEST_P7 overdue",
                                             "due_at": "2000-01-01"})
        assert r.status_code == 200, r.text
        CREATED["tasks"].append(r.json()["id"])
        badges = admin.get(f"{API}/menu").json()["badges"]
        assert badges["tasks_overdue"] >= 1


# ----------------------------------------------------- Auto-task "Préparer le chargement"

@pytest.fixture(scope="module")
def _test_event(admin):
    """Create a confirmed event with equipment, future start, for auto-task tests."""
    # Create equipment
    ref = f"TESTP7-{uuid.uuid4().hex[:6]}"
    eq = admin.post(f"{API}/equipment", json={"ref": ref, "name": "TEST_P7 enceinte", "qty_total": 2})
    assert eq.status_code == 200, eq.text
    eq_id = eq.json()["id"]
    CREATED["equipment"].append(eq_id)

    # Create event (no venue needed for min)
    today = admin.get(f"{API}/dashboard/extra").json()["day"]
    # pick date 10 days later
    from datetime import datetime, timedelta
    d = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=10)).strftime("%Y-%m-%d")
    setup = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=9)).strftime("%Y-%m-%d")
    ev = admin.post(f"{API}/events", json={
        "title": "TEST_P7 event auto",
        "start": f"{d}T18:00",
        "end": f"{d}T23:00",
        "setup_start": f"{setup}T09:00",
        "return_end": f"{d}T23:30",
    })
    assert ev.status_code == 200, ev.text
    eid = ev.json()["id"]
    CREATED["events"].append(eid)

    # Attach equipment via PATCH
    r = admin.patch(f"{API}/events/{eid}", json={"equipment": [{"equipment_id": eq_id, "qty": 1}]})
    assert r.status_code == 200, r.text

    # Confirm
    r = admin.post(f"{API}/events/{eid}/status", json={"status": "confirme"})
    assert r.status_code == 200, r.text
    return {"id": eid, "setup_start": f"{setup}T09:00", "date": d, "equipment_id": eq_id}


class TestAutoTask:
    def test_appears_and_disappears(self, admin, _test_event):
        # Call list_tasks to trigger sync_auto
        rows = admin.get(f"{API}/tasks").json()["tasks"]
        autos = [t for t in rows if t.get("source") == "auto"
                 and t.get("source_ref") == f"loading:{_test_event['id']}"]
        assert autos, "auto task should be created for confirmed event with equipment"
        at = autos[0]
        assert "Préparer le chargement" in at["title"]
        # Due at J-2 of setup_start
        from datetime import datetime, timedelta
        expected = (datetime.strptime(_test_event["setup_start"][:10], "%Y-%m-%d") - timedelta(days=2)).strftime("%Y-%m-%d")
        assert at["due_at"] == expected

        # Cannot delete
        r = admin.delete(f"{API}/tasks/{at['id']}")
        assert r.status_code == 400

        # Revert event to demande -> task soft-deleted
        r = admin.post(f"{API}/events/{_test_event['id']}/status", json={"status": "demande"})
        assert r.status_code == 200
        rows = admin.get(f"{API}/tasks").json()["tasks"]
        assert not any(t.get("source_ref") == f"loading:{_test_event['id']}" for t in rows)

        # Re-confirm for later tests
        admin.post(f"{API}/events/{_test_event['id']}/status", json={"status": "confirme"})


# ----------------------------------------------------- CRM tasks sync

class TestCrmTasks:
    def test_crm_task_appears_in_tasks_and_hidden_for_tech(self, admin, tech, _test_event):
        # Create a contact + opportunity
        contact = admin.post(f"{API}/contacts", json={"first_name": "TEST_P7", "last_name": "CrmLead",
                                                     "email": f"test_p7_crm_{uuid.uuid4().hex[:6]}@example.com"})
        assert contact.status_code == 200, contact.text
        cid = contact.json()["id"]
        CREATED["contacts"].append(cid)
        opp = admin.post(f"{API}/crm/opportunities", json={
            "title": "TEST_P7 opp", "client_contact_id": cid, "amount": 100,
            "event_date": _test_event["date"]})
        assert opp.status_code == 200, opp.text
        oid = opp.json()["id"]
        CREATED["opportunities"].append(oid)
        # Add a CRM task
        from datetime import datetime, timedelta
        due = (datetime.utcnow() + timedelta(days=3)).strftime("%Y-%m-%d")
        r = admin.post(f"{API}/crm/opportunities/{oid}/tasks", json={
            "title": "TEST_P7 crm task", "due_date": due, "done": False})
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        CREATED["tasks"].append(tid)

        # admin sees it in /api/tasks with source=crm
        rows = admin.get(f"{API}/tasks").json()["tasks"]
        found = [t for t in rows if t["id"] == tid]
        assert found and found[0].get("source") == "crm"

        # technicien does NOT see CRM tasks (opportunity_id filter)
        rows_t = tech.get(f"{API}/tasks").json()["tasks"]
        assert not any(t["id"] == tid for t in rows_t)

        # PATCH done -> status syncs
        r = admin.patch(f"{API}/crm/tasks/{tid}", json={"title": "TEST_P7 crm task",
                                                       "due_date": due, "done": True})
        assert r.status_code == 200
        rows = admin.get(f"{API}/tasks").json()["tasks"]
        found = [t for t in rows if t["id"] == tid]
        assert found and found[0]["status"] == "done"


# ----------------------------------------------------- Notes de frais

class TestExpenses:
    def test_crud_role_and_csv(self, admin, tech, comptable):
        r = admin.post(f"{API}/expenses", json={"date": "2026-11-10", "category": "repas",
                                                "amount_ttc": 42.50, "vat": 7.08, "note": "TEST_P7"})
        assert r.status_code == 200, r.text
        xid = r.json()["id"]
        CREATED["expenses"].append(xid)
        # Status: tech forbidden
        rs = tech.post(f"{API}/expenses/{xid}/status", json={"status": "validee"})
        assert rs.status_code == 403
        # Admin can validate
        rs = admin.post(f"{API}/expenses/{xid}/status", json={"status": "validee"})
        assert rs.status_code == 200
        # Technicien sees only his own
        mine = tech.get(f"{API}/expenses").json()["rows"]
        assert all(r_["user_id"] != "" for r_ in mine)
        # CSV export
        csv = admin.get(f"{API}/expenses?month=2026-11&format=csv")
        assert csv.status_code == 200
        assert "text/csv" in csv.headers.get("content-type", "")
        assert "TEST_P7" in csv.text or "repas" in csv.text


# ----------------------------------------------------- Factures d'achat

class TestPurchaseInvoices:
    def test_crud_and_tech_denied(self, admin, tech):
        r = admin.post(f"{API}/purchase-invoices", json={
            "supplier_name": "TEST_P7 fournisseur", "number": f"TESTP7-{uuid.uuid4().hex[:5]}",
            "date": "2026-11-10", "due_date": "2026-12-10",
            "amount_ht": 100.0, "vat": 20.0, "amount_ttc": 0, "category": "divers"})
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        CREATED["purchases"].append(pid)
        assert r.json()["amount_ttc"] == 120.0  # auto-calc
        # tech 403
        rt = tech.get(f"{API}/purchase-invoices")
        assert rt.status_code == 403
        # mark payée
        r2 = admin.put(f"{API}/purchase-invoices/{pid}", json={
            "supplier_name": "TEST_P7 fournisseur", "number": "X", "date": "2026-11-10",
            "due_date": "2026-12-10", "amount_ht": 100, "vat": 20, "amount_ttc": 120,
            "category": "divers", "status": "payee"})
        assert r2.status_code == 200
        assert r2.json()["paid_at"] is not None

    def test_extract_without_ai_returns_ref(self, admin):
        # Small fake PDF (header only); endpoint stores it and returns ref + message if no AI
        fake_pdf = b"%PDF-1.4\n%fake\n%%EOF"
        s = requests.Session()
        s.headers.update({"Authorization": f"Bearer {_tok('admin')}"})
        r = s.post(f"{API}/documents/extract?kind=invoice",
                   files={"file": ("test_p7.pdf", io.BytesIO(fake_pdf), "application/pdf")})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ref"].startswith("file:")
        assert "ai" in d and "message" in d


# ----------------------------------------------------- Abonnements + dashboard alert

class TestSubscriptions:
    def test_alert_in_25_days(self, admin):
        from datetime import datetime, timedelta
        today = admin.get(f"{API}/dashboard/extra").json()["day"]
        renewal = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=25)).strftime("%Y-%m-%d")
        r = admin.post(f"{API}/subscriptions", json={
            "name": "TEST_P7 abo", "amount": 29.0, "period": "monthly",
            "renewal_date": renewal, "notice_days": 30, "active": True})
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        CREATED["subs"].append(sid)

        subs = admin.get(f"{API}/subscriptions").json()
        assert subs["monthly_total"] > 0 and subs["yearly_total"] > 0
        s = next(x for x in subs["rows"] if x["id"] == sid)
        assert s["days_left"] == 25 and s["alert"] is True

        extra = admin.get(f"{API}/dashboard/extra").json()
        alerts = [a for a in extra["alerts"] if a["type"] == "abonnement"]
        assert any("TEST_P7 abo" in a["title"] for a in alerts)


# ----------------------------------------------------- Team contract_type CDDU

@pytest.fixture(scope="module")
def _cddu_member(admin):
    r = admin.post(f"{API}/team", json={
        "name": "TEST_P7 CDDU Guy",
        "email": f"test_p7_cddu_{uuid.uuid4().hex[:6]}@example.com",
        "job": "Tech", "contract_type": "cddu",
        "licences": ["B", "BE"], "licence_valid_until": "2030-01-01",
        "is_driver": True, "day_rate": 200.0, "access_role": "technicien"})
    assert r.status_code == 200, r.text
    m = r.json()
    CREATED["team"].append(m["id"])
    return m


@pytest.fixture(scope="module")
def _cdi_member(admin):
    r = admin.post(f"{API}/team", json={
        "name": "TEST_P7 CDI Guy",
        "email": f"test_p7_cdi_{uuid.uuid4().hex[:6]}@example.com",
        "job": "Tech", "contract_type": "cdi",
        "day_rate": 180.0, "access_role": "technicien"})
    assert r.status_code == 200, r.text
    m = r.json()
    CREATED["team"].append(m["id"])
    return m


class TestTeamCddu:
    def test_contract_and_licences(self, admin, _cddu_member):
        rows = admin.get(f"{API}/team").json()
        m = next(x for x in rows if x["id"] == _cddu_member["id"])
        assert m["contract_type"] == "cddu"
        assert m["employment_status"] == "intermittent"
        assert "BE" in m["licences"]

    def test_cdi_is_salarie(self, admin, _cdi_member):
        rows = admin.get(f"{API}/team").json()
        m = next(x for x in rows if x["id"] == _cdi_member["id"])
        assert m["employment_status"] == "salarie"


# ----------------------------------------------------- CDDU in staff flows (DPAE, payroll, planning)

@pytest.fixture(scope="module")
def _cddu_assigned_event(admin, _cddu_member):
    """Event tomorrow, status confirme, with CDDU member in team."""
    from datetime import datetime, timedelta
    today = admin.get(f"{API}/dashboard/extra").json()["day"]
    tomorrow = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    ev = admin.post(f"{API}/events", json={
        "title": "TEST_P7 CDDU event",
        "start": f"{tomorrow}T18:00", "end": f"{tomorrow}T23:00",
    })
    assert ev.status_code == 200, ev.text
    eid = ev.json()["id"]
    CREATED["events"].append(eid)
    # Assign team + confirm
    r = admin.patch(f"{API}/events/{eid}", json={
        "team": [{"member_id": _cddu_member["id"], "role": "Tech"}]})
    assert r.status_code == 200, r.text
    r = admin.post(f"{API}/events/{eid}/status", json={"status": "confirme"})
    assert r.status_code == 200, r.text
    return {"id": eid, "date": tomorrow}


class TestCdduStaffFlow:
    def test_dpae_alert_appears_and_clears(self, admin, _cddu_member, _cdi_member, _cddu_assigned_event):
        r = admin.get(f"{API}/staff/overview")
        assert r.status_code == 200, r.text
        d = r.json()
        alerts = d.get("dpae_alerts", [])
        mine = [a for a in alerts if a.get("team_id") == _cddu_member["id"]]
        assert mine, "CDDU tomorrow confirmed should raise a DPAE alert"
        assert mine[0]["event_id"] == _cddu_assigned_event["id"]
        # CDI not here
        assert not any(a.get("team_id") == _cdi_member["id"] for a in alerts)

        # Clear it
        r = admin.post(f"{API}/team/{_cddu_member['id']}/dpae",
                       json={"event_id": _cddu_assigned_event["id"]})
        assert r.status_code == 200
        d2 = admin.get(f"{API}/staff/overview").json()
        assert not any(a.get("team_id") == _cddu_member["id"] for a in d2.get("dpae_alerts", []))

    def test_planning_includes_cddu(self, admin, _cddu_member, _cdi_member, _cddu_assigned_event):
        r = admin.get(f"{API}/staff/planning", params={"start": _cddu_assigned_event["date"],
                                                      "end": _cddu_assigned_event["date"]})
        assert r.status_code == 200, r.text
        rows = r.json()["rows"]
        names = [x["provider_name"] for x in rows]
        assert any(_cddu_member["name"] in n for n in names)
        assert not any(_cdi_member["name"] in n for n in names)

    def test_payroll_export_has_cddu_line(self, admin, _cddu_member, _cddu_assigned_event):
        # Flip to realise
        r = admin.post(f"{API}/events/{_cddu_assigned_event['id']}/status", json={"status": "realise"})
        assert r.status_code == 200
        r = admin.get(f"{API}/payroll-export")
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers.get("content-type", "")
        assert _cddu_member["name"] in r.text


# ----------------------------------------------------- Planning assign conflict

class TestPlanningAssign:
    def test_vehicle_conflict_then_force(self, admin):
        # 2 vehicles + 2 overlapping confirmed events
        v1 = admin.post(f"{API}/vehicles", json={"name": "TEST_P7 V1", "active": True}).json()
        v2 = admin.post(f"{API}/vehicles", json={"name": "TEST_P7 V2", "active": True}).json()
        CREATED["vehicles"] += [v1["id"], v2["id"]]
        from datetime import datetime, timedelta
        today = admin.get(f"{API}/dashboard/extra").json()["day"]
        d = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=30)).strftime("%Y-%m-%d")
        eA = admin.post(f"{API}/events", json={"title": "TEST_P7 planA",
                                               "start": f"{d}T10:00", "end": f"{d}T20:00"}).json()
        eB = admin.post(f"{API}/events", json={"title": "TEST_P7 planB",
                                               "start": f"{d}T12:00", "end": f"{d}T22:00"}).json()
        CREATED["events"] += [eA["id"], eB["id"]]
        admin.post(f"{API}/events/{eA['id']}/status", json={"status": "confirme"})
        admin.post(f"{API}/events/{eB['id']}/status", json={"status": "confirme"})
        # Assign V1 to A
        r = admin.post(f"{API}/planning/assign", json={"event_id": eA["id"], "vehicle_id": v1["id"]})
        assert r.status_code == 200
        # Assign V1 to B -> 409 resource_conflict
        r = admin.post(f"{API}/planning/assign", json={"event_id": eB["id"], "vehicle_id": v1["id"]})
        assert r.status_code == 409
        err = r.json().get("detail", {})
        assert (err if isinstance(err, dict) else {}).get("code") == "resource_conflict"
        # Force passes
        r = admin.post(f"{API}/planning/assign", json={"event_id": eB["id"],
                                                      "vehicle_id": v1["id"], "force": True})
        assert r.status_code == 200 and r.json()["forced"] is True


# ----------------------------------------------------- POST /providers withdrawals = 0

class TestProvidersInit:
    def test_withdrawals_initialized(self, admin):
        cats = admin.get(f"{API}/provider-categories").json()
        cat_key = cats[0]["key"] if cats else "wedding_planner"
        r = admin.post(f"{API}/providers", json={
            "first_name": "TEST_P7", "last_name": f"Prov {uuid.uuid4().hex[:5]}",
            "email": f"test_p7_prov_{uuid.uuid4().hex[:6]}@example.com",
            "base_city": "Nîmes", "categories": [cat_key]})
        assert r.status_code == 200, r.text
        p = r.json()
        CREATED["providers"].append(p["id"])
        if p.get("contact_id"):
            CREATED["contacts"].append(p["contact_id"])
        assert p.get("withdrawals") == 0
