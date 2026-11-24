"""Iter 11 — LOT 6/6 Staff & missions: gaps NOT covered by /tmp/p6.py smoke.

Covered by smoke (p6.py, green): network/private visibility, apply, confirm,
'Poste pourvu', invitation accept flow, cross-404 on mission/timesheet,
intermittent 11h + payroll CSV, freelance invoice happy path, private busy title
masking, IBAN encrypted + admin read + commercial 403, iCal, planning stub,
withdrawal happy path.

This file adds:
- Public /api/public/join/{org_id} 404/200
- POST /api/join as a user without org => pending profile, then admin GET /staff/overview
- Admin validate (active/refuse/more_info) decisions
- Team invite: /staff-teams + /positions/{pid}/invite with team_id => private-team visibility to team member only
- Withdrawal J-7 window: refused (409) when date is within 7 days
- Timesheet correction / refuse with reason
- Invoice PDF content (art. 293 B mention, number, service date)
- 'Inviter maintenant' (/api/providers/{pid}/invite)
- 'Retenir' with no_account=true keeps provider without Clerk invite
- Pending profile (validation_status=pending) => 404 on /portal/provider/positions
- DPAE alert in /staff/overview + disappears after /missions/{id}/dpae
- Portal role guards: client/commercial/comptable/technicien tokens 403 on /api/staff/* and /api/events/{id}/positions
"""
import io
import os
import subprocess
import uuid

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

from conftest import API  # noqa: E402

MONGO = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
ORG = MONGO.orgs.find_one({"slug": "qa-sandbox"})
assert ORG, "qa-sandbox org missing"
ORG_ID = ORG["id"]


def _tok(*a):
    r = subprocess.run(["python3", "/app/scripts/qa_token.py", *a], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        pytest.skip(f"qa_token.py: {r.stderr[-200:]}")
    return r.stdout.strip().splitlines()[-1]


def _sess(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "qa-it11"})
    return s


# ---------------- session fixtures ----------------
@pytest.fixture(scope="module")
def admin():
    return _sess(_tok("admin"))


@pytest.fixture(scope="module")
def commercial():
    return _sess(_tok("commercial"))


@pytest.fixture(scope="module")
def comptable():
    return _sess(_tok("comptable"))


@pytest.fixture(scope="module")
def technicien():
    return _sess(_tok("technicien"))


# ---------------- seed ----------------
@pytest.fixture(scope="module")
def seed(admin):
    """Create 1 freelance provider + an event + a far-future position (J+365 => outside withdraw window)
    and a near position (J+3 => inside withdraw window, for J-7 refusal).
    Uses existing TEST_P4 event if any, else creates TEST_IT11 event."""
    created = {"providers": [], "events": [], "positions": [], "teams": [], "contacts": [], "missions": [], "users": [],
               "apps": [], "ts": [], "inv": []}

    ev = MONGO.events.find_one({"org_id": ORG_ID, "title": {"$regex": "^TEST_P4"}})
    if not ev:
        cli = admin.post(f"{API}/contacts", json={"first_name": "TEST_IT11", "last_name": "Cli",
                                                   "email": f"it11cli{uuid.uuid4().hex[:4]}@example.com"}).json()
        created["contacts"].append(cli["id"])
        ev = admin.post(f"{API}/events", json={"title": f"TEST_IT11_Ev_{uuid.uuid4().hex[:4]}", "type": "Mariage",
                                                "start": "2028-10-10T16:00", "end": "2028-10-11T02:00",
                                                "client_contact_ids": [cli["id"]], "venue_type": "autre",
                                                "guests": 80}).json()
        created["events"].append(ev["id"])
    ev_id = ev["id"]

    def mk_prov(suffix, es):
        em = f"it11_{suffix}_{uuid.uuid4().hex[:4]}+clerk_test@example.com"
        p = admin.post(f"{API}/providers", json={"first_name": f"TEST_IT11 {suffix}", "last_name": "S",
                                                  "email": em, "categories": ["saxophoniste"],
                                                  "base_rate": 300}).json()
        MONGO.provider_profiles.update_one({"id": p["id"]}, {"$set": {"employment_status": es, "withdrawals": 0}})
        created["providers"].append(p["id"])
        created["contacts"].append(p["contact_id"])
        return p, em

    pA, emA = mk_prov("A", "freelance")
    pB, emB = mk_prov("B", "freelance")
    pPend, emPend = mk_prov("Pend", "freelance")
    MONGO.provider_profiles.update_one({"id": pPend["id"]}, {"$set": {"validation_status": "pending", "status": "pending"}})

    tokA = _tok("provider", "qa_it11_a+clerk_test@example.com", pA["contact_id"])
    tokB = _tok("provider", "qa_it11_b+clerk_test@example.com", pB["contact_id"])
    tokPend = _tok("provider", "qa_it11_pend+clerk_test@example.com", pPend["contact_id"])
    # Mark the pend user as pending too (qa_token defaults to active)
    MONGO.users.update_one({"contact_id": pPend["contact_id"]}, {"$set": {"status": "pending"}})

    yield {"admin": admin, "ev_id": ev_id, "pA": pA, "pB": pB, "pPend": pPend,
           "sA": _sess(tokA), "sB": _sess(tokB), "sPend": _sess(tokPend),
           "created": created}

    # ---- cleanup by id ----
    for col, ids in [("provider_invoices", created["inv"]), ("timesheets", created["ts"]),
                     ("position_applications", created["apps"]), ("missions", created["missions"]),
                     ("positions", created["positions"]), ("staff_teams", created["teams"]),
                     ("provider_profiles", created["providers"]), ("contacts", created["contacts"]),
                     ("events", created["events"])]:
        if ids:
            MONGO[col].delete_many({"org_id": ORG_ID, "id": {"$in": ids}})
    # Remove orphan unavailabilities
    MONGO.provider_unavailabilities.delete_many({"org_id": ORG_ID, "provider_id": {"$in": created["providers"]}})
    MONGO.position_applications.delete_many({"org_id": ORG_ID, "provider_id": {"$in": created["providers"]}})


# ---------------- 1. Public join info ----------------
class TestJoinPublic:
    def test_bad_org_404(self):
        r = requests.get(f"{API}/public/join/does-not-exist", headers={"User-Agent": "qa"})
        assert r.status_code == 404

    def test_good_org_returns_name_and_categories(self):
        r = requests.get(f"{API}/public/join/{ORG_ID}", headers={"User-Agent": "qa"})
        assert r.status_code == 200
        b = r.json()
        assert b["org"]
        assert isinstance(b["categories"], list) and len(b["categories"]) > 0
        assert all({"key", "label"} <= set(c) for c in b["categories"])


# ---------------- 2. POST /join + admin validation ----------------
class TestJoinAndValidate:
    def test_full_flow(self, admin, seed):
        # Create a standalone Clerk user with NO org (reuse fixed email to avoid Clerk throttling)
        email = "qa_it11_join+clerk_test@example.com"
        tok = _tok("provider", email)
        # qa_token attached him to org by default. Reset his org to simulate autonomous signup.
        MONGO.users.update_one({"email": email}, {"$unset": {"org_id": "", "contact_id": "", "role": ""}})

        s = _sess(tok)
        body = {"org_id": ORG_ID, "first_name": "TEST_IT11_Newbie", "last_name": "Join",
                "phone": f"+336{uuid.uuid4().int % 10**8:08d}", "categories": ["saxophoniste"],
                "employment_status": "freelance", "language": "fr-FR", "accept": True}
        r = s.post(f"{API}/join", json=body)
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # Must now appear in overview with validation_status pending
        ov = admin.get(f"{API}/staff/overview")
        assert ov.status_code == 200
        apps = ov.json()["applications"]
        mine = [a for a in apps if a.get("name", "").startswith("TEST_IT11_Newbie")]
        assert len(mine) == 1, "join application not in overview"
        pid = mine[0]["id"]
        assert mine[0]["validation_status"] == "pending"
        assert "completion_pct" in mine[0]

        # cleanup
        prof = MONGO.provider_profiles.find_one({"id": pid})
        assert prof
        seed["created"]["providers"].append(pid)
        seed["created"]["contacts"].append(prof["contact_id"])

        # Second POST /join from same user => 400 (déjà rattaché)
        r2 = s.post(f"{API}/join", json=body)
        assert r2.status_code == 400

        # Admin validates -> active
        r = admin.post(f"{API}/providers/{pid}/validate", json={"decision": "active"})
        assert r.status_code == 200
        assert MONGO.provider_profiles.find_one({"id": pid})["validation_status"] == "active"

        # Admin refuse works too (on another synthetic profile)
        # Re-pending then refuse
        MONGO.provider_profiles.update_one({"id": pid}, {"$set": {"validation_status": "pending", "status": "pending"}})
        r = admin.post(f"{API}/providers/{pid}/validate", json={"decision": "refused", "message": "test"})
        assert r.status_code == 200
        assert MONGO.provider_profiles.find_one({"id": pid})["validation_status"] == "refused"

        # more_info branch
        MONGO.provider_profiles.update_one({"id": pid}, {"$set": {"validation_status": "pending"}})
        r = admin.post(f"{API}/providers/{pid}/validate", json={"decision": "more_info", "message": "SIRET manquant"})
        assert r.status_code == 200


# ---------------- 3. Pending profile sees no positions ----------------
class TestPendingIsolation:
    def test_pending_cannot_list_open(self, seed):
        r = seed["sPend"].get(f"{API}/portal/provider/positions")
        assert r.status_code == 404


# ---------------- 4. Team invite + team visibility ----------------
class TestTeamsVisibility:
    def test_team_private_only_visible_to_members(self, admin, seed):
        # Create a team with pA only (NOT pB)
        t = admin.post(f"{API}/staff-teams", json={"name": f"TEST_IT11_Team_{uuid.uuid4().hex[:4]}",
                                                    "provider_ids": [seed["pA"]["id"]]}).json()
        seed["created"]["teams"].append(t["id"])
        pos = admin.post(f"{API}/events/{seed['ev_id']}/positions",
                        json={"category_key": "saxophoniste", "quantity": 1, "date": "2028-06-15",
                              "start_time": "19:00", "end_time": "23:00", "rate": 250,
                              "visibility": "team", "team_id": t["id"]}).json()
        seed["created"]["positions"].append(pos["id"])
        # pA (team member) sees it
        oa = seed["sA"].get(f"{API}/portal/provider/positions").json()
        if not any(p["id"] == pos["id"] for p in oa["open"]):
            # Diagnose
            team_doc = MONGO.staff_teams.find_one({"id": t["id"]})
            prof_doc = MONGO.provider_profiles.find_one({"id": seed["pA"]["id"]})
            pos_doc = MONGO.positions.find_one({"id": pos["id"]})
            raise AssertionError(f"team member should see team position.\n"
                                  f"team={team_doc}\nprofile categories={prof_doc.get('categories')} status={prof_doc.get('status')} vs={prof_doc.get('validation_status')} es={prof_doc.get('employment_status')}\n"
                                  f"pos visibility={pos_doc.get('visibility')} team_id={pos_doc.get('team_id')} accepted_statuses={pos_doc.get('accepted_statuses')} status={pos_doc.get('status')}\n"
                                  f"open ids={[p['id'] for p in oa['open']]}")
        # pB (not member) does NOT see it
        ob = seed["sB"].get(f"{API}/portal/provider/positions").json()
        assert all(p["id"] != pos["id"] for p in ob["open"]), "non-member must not see team position"
        # Invite via team_id => pB NOT invited, pA invited (though already visible)
        r = admin.post(f"{API}/positions/{pos['id']}/invite", json={"provider_ids": [], "team_id": t["id"]})
        assert r.status_code == 200
        assert r.json()["invited"] == 1  # only pA (member)

    def test_no_event_leak_in_open_positions(self, seed):
        # Already tested in smoke: open positions should NOT contain event_id/client/addr
        out = seed["sA"].get(f"{API}/portal/provider/positions").json()
        for p in out["open"] + out.get("invitations", []):
            for leaky in ("event_id", "client", "address", "notes", "rating"):
                assert leaky not in p, f"leaked key {leaky} in {p}"


# ---------------- 5. Withdrawal J-7 refusal ----------------
class TestWithdrawalWindow:
    def test_withdraw_within_7_days_refused(self, admin, seed):
        # Create a near-term position (date = tomorrow), apply, confirm => mission in <7 days
        from datetime import datetime, timedelta
        soon = (datetime.utcnow() + timedelta(days=2)).strftime("%Y-%m-%d")
        pos = admin.post(f"{API}/events/{seed['ev_id']}/positions",
                        json={"category_key": "saxophoniste", "quantity": 1, "date": soon,
                              "start_time": "18:00", "end_time": "22:00", "rate": 200,
                              "visibility": "network"}).json()
        seed["created"]["positions"].append(pos["id"])
        ap = seed["sA"].post(f"{API}/portal/provider/positions/{pos['id']}/apply", json={}).json()
        seed["created"]["apps"].append(ap["id"])
        c = admin.post(f"{API}/applications/{ap['id']}/confirm").json()
        seed["created"]["missions"].append(c["mission_id"])
        r = seed["sA"].post(f"{API}/portal/provider/missions/{c['mission_id']}/withdraw",
                            json={"reason": "indispo last minute"})
        assert r.status_code == 409, f"expected 409 J-7 refusal, got {r.status_code} {r.text[:120]}"

    def test_withdraw_far_future_ok_and_position_reopens(self, admin, seed):
        pos = admin.post(f"{API}/events/{seed['ev_id']}/positions",
                        json={"category_key": "saxophoniste", "quantity": 1, "date": "2028-11-20",
                              "start_time": "18:00", "end_time": "22:00", "rate": 200,
                              "visibility": "network"}).json()
        seed["created"]["positions"].append(pos["id"])
        ap = seed["sA"].post(f"{API}/portal/provider/positions/{pos['id']}/apply", json={}).json()
        seed["created"]["apps"].append(ap["id"])
        c = admin.post(f"{API}/applications/{ap['id']}/confirm").json()
        mid = c["mission_id"]
        seed["created"]["missions"].append(mid)
        r = seed["sA"].post(f"{API}/portal/provider/missions/{mid}/withdraw",
                            json={"reason": "conflit agenda personnel"})
        assert r.status_code == 200
        # Mission inaccessible
        assert seed["sA"].get(f"{API}/portal/provider/missions/{mid}").status_code == 404
        # Counter incremented (use .get to tolerate schema without the field initialized)
        assert (MONGO.provider_profiles.find_one({"id": seed["pA"]["id"]}) or {}).get("withdrawals", 0) >= 1
        # Position reopened
        assert MONGO.positions.find_one({"id": pos["id"]})["status"] == "open"


# ---------------- 6. Timesheet correction / refuse ----------------
class TestTimesheetReview:
    def test_correct_and_refuse_with_reason(self, admin, seed):
        pos = admin.post(f"{API}/events/{seed['ev_id']}/positions",
                        json={"category_key": "saxophoniste", "quantity": 1, "date": "2028-07-01",
                              "start_time": "18:00", "end_time": "23:00", "rate": 20,
                              "rate_type": "hourly", "visibility": "network"}).json()
        seed["created"]["positions"].append(pos["id"])
        ap = seed["sA"].post(f"{API}/portal/provider/positions/{pos['id']}/apply", json={}).json()
        seed["created"]["apps"].append(ap["id"])
        c = admin.post(f"{API}/applications/{ap['id']}/confirm").json()
        mid = c["mission_id"]
        seed["created"]["missions"].append(mid)
        ts = seed["sA"].put(f"{API}/portal/provider/missions/{mid}/timesheet",
                            json={"start_time": "18:00", "end_time": "23:00", "break_min": 0,
                                  "night_hours": 0, "km": 0, "expenses": 0, "comment": "", "reason": ""}).json()
        tid = ts["id"]
        seed["created"]["ts"].append(tid)

        # Refuse without reason => 400
        r = admin.post(f"{API}/timesheets/{tid}/refuse", json={"start_time": "18:00", "end_time": "23:00",
                                                                "break_min": 0, "night_hours": 0, "km": 0,
                                                                "expenses": 0, "comment": "", "reason": ""})
        assert r.status_code == 400

        # Correct with reason => status validated + review_reason stored
        r = admin.post(f"{API}/timesheets/{tid}/correct", json={"start_time": "18:00", "end_time": "22:00",
                                                                 "break_min": 0, "night_hours": 0, "km": 0,
                                                                 "expenses": 0, "comment": "",
                                                                 "reason": "Horaire corrigé selon badge"})
        assert r.status_code == 200
        doc = MONGO.timesheets.find_one({"id": tid})
        assert doc["status"] == "validated"
        assert doc.get("review_reason") == "Horaire corrigé selon badge"
        # Reason visible to provider in /space
        sp = seed["sA"].get(f"{API}/portal/provider/space").json()
        mine = [m for m in sp["missions"] if m["id"] == mid][0]
        assert mine["timesheet"]["review_reason"] == "Horaire corrigé selon badge"

        # Refuse => status refused, provider can re-declare
        r = admin.post(f"{API}/timesheets/{tid}/refuse", json={"start_time": "18:00", "end_time": "22:00",
                                                                "break_min": 0, "night_hours": 0, "km": 0,
                                                                "expenses": 0, "comment": "",
                                                                "reason": "Horaire non conforme"})
        assert r.status_code == 200
        assert MONGO.timesheets.find_one({"id": tid})["status"] == "refused"
        # Re-declare possible after refusal
        r = seed["sA"].put(f"{API}/portal/provider/missions/{mid}/timesheet",
                           json={"start_time": "18:00", "end_time": "22:30", "break_min": 0,
                                 "night_hours": 0, "km": 0, "expenses": 0, "comment": "corrigé", "reason": ""})
        assert r.status_code == 200
        assert MONGO.timesheets.find_one({"id": tid})["status"] == "declared"


# ---------------- 7. Invoice PDF content ----------------
class TestInvoicePdf:
    def test_pdf_mentions_art_293B_and_number(self, admin, seed):
        pos = admin.post(f"{API}/events/{seed['ev_id']}/positions",
                        json={"category_key": "saxophoniste", "quantity": 1, "date": "2028-08-01",
                              "start_time": "18:00", "end_time": "23:00", "rate": 300,
                              "visibility": "network"}).json()
        seed["created"]["positions"].append(pos["id"])
        ap = seed["sA"].post(f"{API}/portal/provider/positions/{pos['id']}/apply", json={}).json()
        seed["created"]["apps"].append(ap["id"])
        c = admin.post(f"{API}/applications/{ap['id']}/confirm").json()
        mid = c["mission_id"]
        seed["created"]["missions"].append(mid)
        # Declare + validate timesheet
        ts = seed["sA"].put(f"{API}/portal/provider/missions/{mid}/timesheet",
                            json={"start_time": "18:00", "end_time": "23:00", "break_min": 0,
                                  "night_hours": 0, "km": 0, "expenses": 0, "comment": "", "reason": ""}).json()
        seed["created"]["ts"].append(ts["id"])
        admin.post(f"{API}/timesheets/validate", json={"ids": [ts["id"]]})
        r = seed["sA"].post(f"{API}/portal/provider/missions/{mid}/make-invoice")
        assert r.status_code == 200, r.text
        number = r.json()["number"]
        # Second attempt => 409
        assert seed["sA"].post(f"{API}/portal/provider/missions/{mid}/make-invoice").status_code == 409
        # Fetch PDF via admin via signed url
        inv = MONGO.provider_invoices.find_one({"mission_id": mid})
        assert inv
        seed["created"]["inv"].append(inv["id"])
        # Load file bytes: use admin /portal/dl via sign_file is complicated; easier: read storage
        sp = seed["sA"].get(f"{API}/portal/provider/space").json()
        mine = [m for m in sp["missions"] if m["id"] == mid][0]
        url = mine["invoice"]["url"]
        from conftest import BASE_URL
        pdf = requests.get(url if url.startswith("http") else BASE_URL + url,
                           headers={"User-Agent": "qa"}).content
        assert pdf.startswith(b"%PDF"), "not a PDF"
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf))
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        assert "293" in text, f"art. 293 B mention missing from PDF text: {text[:400]}"
        assert number in text, f"invoice number {number} missing. got {text[:400]}"
        # Service date (mission date) must be present (fr-formatted dd/mm/yyyy from pc.fr_date)
        assert "08/2028" in text or "2028-08-01" in text or "1 août 2028" in text.lower() or "août 2028" in text.lower(), \
            f"service date not in PDF: {text[:400]}"


# ---------------- 8. Inviter maintenant ----------------
class TestInviteNow:
    def test_invite_now_returns_ok(self, admin, seed):
        r = admin.post(f"{API}/providers/{seed['pA']['id']}/invite")
        assert r.status_code == 200
        # expected keys: sent (bool) or link
        b = r.json()
        assert "sent" in b or "link" in b, b


# ---------------- 9. Retenir ?no_account=true ----------------
class TestRetainNoAccount:
    def test_retain_no_account_does_not_create_user(self, admin, seed):
        # Create a fresh provider with no user account, build a service request, retain with no_account=true.
        em = f"it11_noacc_{uuid.uuid4().hex[:4]}@example.com"
        prov = admin.post(f"{API}/providers", json={"first_name": "TEST_IT11_NoAcc", "last_name": "P",
                                                     "email": em, "categories": ["saxophoniste"], "base_rate": 300}).json()
        seed["created"]["providers"].append(prov["id"])
        seed["created"]["contacts"].append(prov["contact_id"])
        req = admin.post(f"{API}/service-requests", json={"category_key": "saxophoniste", "quantity": 1,
                                                           "date": "2028-09-10", "start_time": "18:00",
                                                           "end_time": "23:00", "venue_address": "1 rue test",
                                                           "venue_city": "Nîmes"})
        assert req.status_code == 200, f"create req: {req.status_code} {req.text[:200]}"
        rid = req.json()["id"]
        # Directly insert the recipient (skip /send which requires Gmail connected)
        import secrets as _secrets
        import uuid as _uuid
        from datetime import datetime as _dt
        rec_id = str(_uuid.uuid4())
        MONGO.request_recipients.insert_one({"id": rec_id, "org_id": ORG_ID, "request_id": rid,
                                              "provider_id": prov["id"], "provider_name": prov["display_name"],
                                              "token": _secrets.token_urlsafe(32), "channels": ["email"],
                                              "order": 0, "sent_at": None, "opened_at": None,
                                              "reminded_at": None, "replied_at": None,
                                              "send_error": None, "claim": None, "reply": "none",
                                              "retained": False, "created_at": _dt.utcnow().isoformat()})
        MONGO.service_requests.update_one({"id": rid, "org_id": ORG_ID}, {"$set": {"status": "sent"}})
        before = MONGO.users.count_documents({"contact_id": prov["contact_id"]})
        r = admin.post(f"{API}/service-requests/{rid}/recipients/{rec_id}/retain?no_account=true")
        assert r.status_code == 200, r.text
        import time
        time.sleep(1.5)
        after = MONGO.users.count_documents({"contact_id": prov["contact_id"]})
        assert after == before, "no_account=true should NOT create a new user row"
        mid = r.json().get("mission", {}).get("id")
        if mid:
            seed["created"]["missions"].append(mid)
        MONGO.service_requests.delete_one({"id": rid, "org_id": ORG_ID})
        MONGO.request_recipients.delete_many({"request_id": rid})


# ---------------- 10. Role guards on /api/staff/* ----------------
class TestStaffRouteGuards:
    @pytest.mark.parametrize("role_sess", ["commercial", "comptable", "technicien"])
    def test_portal_roles_denied(self, role_sess, request, seed):
        s = request.getfixturevalue(role_sess)
        for path in ["/staff/overview", "/staff/planning", "/staff/stats",
                     "/staff-teams", "/timesheets", "/provider-invoices", "/payroll-export",
                     f"/events/{seed['ev_id']}/positions"]:
            r = s.get(f"{API}{path}")
            assert r.status_code in (401, 403), f"{role_sess} should be denied on {path}, got {r.status_code}"


# ---------------- 11. DPAE alert visible then cleared ----------------
class TestDpaeAlert:
    def test_dpae_alert_appears_and_clears(self, admin, seed):
        # Create intermittent provider + near-tomorrow mission
        from datetime import datetime, timedelta
        tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
        em = f"it11_int_{uuid.uuid4().hex[:4]}+clerk_test@example.com"
        pi = admin.post(f"{API}/providers", json={"first_name": "TEST_IT11 Int", "last_name": "S",
                                                   "email": em, "categories": ["saxophoniste"], "base_rate": 300}).json()
        MONGO.provider_profiles.update_one({"id": pi["id"]}, {"$set": {"employment_status": "intermittent"}})
        seed["created"]["providers"].append(pi["id"])
        seed["created"]["contacts"].append(pi["contact_id"])
        tokI = _tok("provider", "qa_it11_int+clerk_test@example.com", pi["contact_id"])
        sI = _sess(tokI)
        pos = admin.post(f"{API}/events/{seed['ev_id']}/positions",
                        json={"category_key": "saxophoniste", "quantity": 1, "date": tomorrow,
                              "start_time": "18:00", "end_time": "23:00", "rate": 200,
                              "visibility": "network",
                              "accepted_statuses": ["intermittent"]}).json()
        seed["created"]["positions"].append(pos["id"])
        ap = sI.post(f"{API}/portal/provider/positions/{pos['id']}/apply", json={}).json()
        seed["created"]["apps"].append(ap["id"])
        c = admin.post(f"{API}/applications/{ap['id']}/confirm").json()
        mid = c["mission_id"]
        seed["created"]["missions"].append(mid)
        ov = admin.get(f"{API}/staff/overview").json()
        dpae_ids = [d["id"] for d in ov.get("dpae_alerts", [])]
        assert mid in dpae_ids, f"expected DPAE alert for mission {mid}, got {dpae_ids}"
        # Mark DPAE done
        r = admin.post(f"{API}/missions/{mid}/dpae")
        assert r.status_code == 200
        ov2 = admin.get(f"{API}/staff/overview").json()
        assert mid not in [d["id"] for d in ov2.get("dpae_alerts", [])]
