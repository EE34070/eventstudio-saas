"""Iter10 — Module DJ « Ma musique ». Covers parts not already exercised by /tmp/p5.py:
- 5 guest-suggestion-per-device limit (429)
- French PDF (fr) + English PDF (en) + CSV content
- Templates (apply + refused if tracks exist)
- Preview "Voir comme" on music: read-only for admin via X-View-As
- Non-DJ provider mission -> 404 on music routes
- Cancelled DJ mission -> 404 on music routes
- Staff without events:write cannot save
- Guest-page 'website' honeypot refused, bad https refused, limit 5
- Music plans list present for staff
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO = MongoClient(os.environ["MONGO_URL"])
DB = MONGO[os.environ["DB_NAME"]]
ORG = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]


def tok(*a):
    return subprocess.check_output(["python3", "/app/scripts/qa_token.py", *a]).decode().strip()


def call(t, method, path, body=None, raw=False, extra_headers=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": "Bearer " + t, "Content-Type": "application/json", "User-Agent": "qa-iter10"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(BASE + "/api" + path, data=data, method=method, headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=20)
        payload = r.read()
        return r.status, (payload if raw else json.loads(payload or b"null"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


@pytest.fixture(scope="module")
def admin():
    return tok("admin")


@pytest.fixture(scope="module")
def tech():
    return tok("technicien")


@pytest.fixture(scope="module")
def client_ctx():
    u = DB.users.find_one({"email": "qa_client_a+clerk_test@example.com"})
    DB.users.update_one({"_id": u["_id"]}, {"$unset": {"sessions_revoked_at": ""}, "$set": {"status": "active"}})
    ev = DB.events.find_one({"org_id": ORG, "client_contact_ids": u["contact_id"]})
    t = tok("client", u["email"], u["contact_id"])
    return {"tok": t, "event_id": ev["id"], "user_id": u["user_id"], "base": f"/portal/client/events/{ev['id']}/music"}


@pytest.fixture(scope="module")
def plan_with_guest(admin, client_ctx):
    # ensure the module is visible and editable with a future lock date
    call(admin, "PUT", f"/events/{client_ctx['event_id']}/portal/modules/music",
         {"client_visible": True, "client_editable": True, "lock_date": "2027-06-02"})
    s, p = call(client_ctx["tok"], "GET", client_ctx["base"])
    assert s == 200, p
    body = {
        "moments": p["moments"],
        "genre_preferences": {"pop": "love"},
        "banned": ["Macarena"],
        "useful_info": {"languages": "FR/EN"},
        "guest_requests_enabled": True,
    }
    s, r = call(client_ctx["tok"], "PUT", client_ctx["base"], body)
    assert s == 200, r
    token = r["guest_url"].split("/")[-1]
    return {"token": token, "plan": p}


# ---------- Guest page ----------

class TestGuestLink:
    def test_guest_page_returns_only_event_title_and_challenge(self, plan_with_guest):
        s, d = call("", "GET", f"/public/music/{plan_with_guest['token']}")
        assert s == 200
        assert set(d.keys()) == {"event", "language", "challenge"}
        assert set(d["challenge"].keys()) == {"a", "b", "exp", "sig"}

    def test_guest_honeypot_rejected(self, plan_with_guest):
        s, d = call("", "GET", f"/public/music/{plan_with_guest['token']}")
        c = d["challenge"]
        code, _ = call("", "POST", f"/public/music/{plan_with_guest['token']}",
                       {"name": "Bot", "title": "X", "answer": c["a"] + c["b"], "exp": c["exp"], "sig": c["sig"],
                        "website": "http://spam"})
        assert code == 400

    def test_guest_bad_https_url_rejected(self, plan_with_guest):
        s, d = call("", "GET", f"/public/music/{plan_with_guest['token']}")
        c = d["challenge"]
        code, _ = call("", "POST", f"/public/music/{plan_with_guest['token']}",
                       {"name": "Bob", "title": "Bad", "url": "http://not-https.example",
                        "answer": c["a"] + c["b"], "exp": c["exp"], "sig": c["sig"]})
        assert code == 422

    def test_guest_bad_token_404(self):
        code, _ = call("", "GET", "/public/music/" + "a" * 40)
        assert code == 404

    def test_guest_device_limit_of_5(self, plan_with_guest):
        token = plan_with_guest["token"]
        device = "iter10-dev-" + uuid.uuid4().hex
        statuses = []
        # 6 submissions from same device: 1st–5th OK, 6th 429
        for i in range(6):
            s, d = call("", "GET", f"/public/music/{token}")
            c = d["challenge"]
            code, _ = call(
                "", "POST", f"/public/music/{token}",
                {"name": f"TEST_IT10_guest{i}", "title": f"TEST_IT10_s{i}", "answer": c["a"] + c["b"],
                 "exp": c["exp"], "sig": c["sig"], "device": device},
                extra_headers={"X-Forwarded-For": "203.0.113.17"},
            )
            statuses.append(code)
        assert statuses[:5] == [200] * 5, statuses
        assert statuses[5] == 429, statuses
        # cleanup
        DB.guest_suggestions.delete_many({"plan_id": {"$ne": ""}, "name": {"$regex": "^TEST_IT10_guest"}})


# ---------- PDF (fr / en) + CSV ----------

class TestExports:
    def test_pdf_fr_and_en(self, client_ctx):
        # write a track we can look for by moment name etc.
        s, p = call(client_ctx["tok"], "GET", client_ctx["base"])
        body = {
            "moments": p["moments"],
            "genre_preferences": {"pop": "love", "rap": "avoid"},
            "banned": ["Macarena"],
            "useful_info": {"languages": "FR/EN"},
            "guest_requests_enabled": True,
        }
        assert call(client_ctx["tok"], "PUT", client_ctx["base"], body)[0] == 200
        s, fr = call(client_ctx["tok"], "GET", client_ctx["base"] + "/pdf?lang=fr", raw=True)
        assert s == 200 and fr[:4] == b"%PDF" and len(fr) > 800
        s, en = call(client_ctx["tok"], "GET", client_ctx["base"] + "/pdf?lang=en", raw=True)
        assert s == 200 and en[:4] == b"%PDF" and len(en) > 800
        # PDFs should differ (different localized strings)
        assert fr != en

    def test_csv_contains_header_and_bom(self, client_ctx):
        s, body = call(client_ctx["tok"], "GET", client_ctx["base"] + "/csv", raw=True)
        assert s == 200
        txt = body.decode("utf-8")
        assert txt.startswith("\ufeff")
        assert "Titre" in txt and "Artiste" in txt and "Priorité" in txt


# ---------- Templates ----------

class TestTemplates:
    def test_client_cannot_apply_template(self, client_ctx):
        code, _ = call(client_ctx["tok"], "POST", client_ctx["base"] + "/template", {"key": "wedding"})
        assert code == 403

    def test_staff_cannot_apply_template_when_tracks_exist(self, admin, client_ctx):
        # by now p5.py and fixtures already added tracks
        code, body = call(admin, "POST", f"/events/{client_ctx['event_id']}/music/template", {"key": "wedding"})
        assert code == 409, body

    def test_staff_template_applies_on_fresh_event(self, admin):
        # create isolated TEST_IT10 event
        cid = "TEST_IT10_" + uuid.uuid4().hex[:8]
        eid = "TEST_IT10_" + uuid.uuid4().hex[:8]
        DB.contacts.insert_one({"id": cid, "org_id": ORG, "kind": "client", "first_name": "TEST_IT10", "last_name": "Fresh",
                                "email": f"test_it10_{uuid.uuid4().hex[:6]}@example.com", "language": "fr-FR",
                                "created_at": "2026-11-19T00:00:00+00:00"})
        DB.events.insert_one({"id": eid, "org_id": ORG, "title": "TEST_IT10_FreshEvent", "type": "Mariage",
                              "start": "2027-07-01T18:00", "client_contact_ids": [cid], "language": "fr-FR",
                              "created_at": "2026-11-19T00:00:00+00:00"})
        try:
            # read to auto-create plan
            s, p = call(admin, "GET", f"/events/{eid}/music")
            assert s == 200 and len(p["moments"]) == 8  # wedding template
            # apply birthday template
            code, _ = call(admin, "POST", f"/events/{eid}/music/template", {"key": "birthday"})
            assert code == 200
            s, p = call(admin, "GET", f"/events/{eid}/music")
            assert len(p["moments"]) == 6  # birthday default has 6
        finally:
            DB.events.delete_one({"id": eid})
            DB.contacts.delete_one({"id": cid})
            DB.music_plans.delete_many({"event_id": eid})


# ---------- Preview "Voir comme" ----------

class TestPreview:
    def test_admin_view_as_client_read_only(self, admin, client_ctx):
        # read as the client via X-View-As
        headers = {"X-View-As": client_ctx["user_id"]}
        s, p = call(admin, "GET", client_ctx["base"], extra_headers=headers)
        assert s == 200, p
        assert "moments" in p
        # write must be refused
        code, _ = call(admin, "PUT", client_ctx["base"], {"moments": p["moments"], "banned": [], "useful_info": {},
                                                          "genre_preferences": {}, "guest_requests_enabled": False},
                       extra_headers=headers)
        assert code == 403

    def test_view_as_unknown_user_404(self, admin, client_ctx):
        code, _ = call(admin, "GET", client_ctx["base"], extra_headers={"X-View-As": "does-not-exist"})
        assert code == 404


# ---------- DJ permissions ----------

class TestDJEdgeCases:
    @pytest.fixture(scope="class")
    def dj_mission(self, admin, client_ctx):
        # create a DJ provider + mission for the client event
        email = f"test_it10_dj_{uuid.uuid4().hex[:6]}@example.com"
        s, pr = call(admin, "POST", "/providers", {"first_name": "TEST_IT10_DJ", "last_name": "X",
                                                   "email": email, "categories": ["dj"], "base_rate": 500,
                                                   "language": "fr-FR"})
        assert s == 200, pr
        mid = str(uuid.uuid4())
        DB.missions.insert_one({
            "id": mid, "org_id": ORG, "created_at": "2026-11-19T10:00:00+00:00",
            "request_id": "", "recipient_id": "", "provider_id": pr["id"], "provider_name": "TEST_IT10 DJ",
            "event_id": client_ctx["event_id"], "category_key": "dj", "date": "2027-06-12",
            "start_time": "18:00", "end_time": "23:00", "venue_city": "Uzès", "agreed_rate": 500,
            "agreed_travel_fee": 0, "vat_mode": "not_applicable_293B", "vat_rate": 0,
            "total_ht": 500, "total_ttc": 500, "equipment_needed": [], "equipment_note": "",
            "missing_equipment": [], "status": "confirmed",
        })
        # also a non-DJ mission (photographer category)
        other_email = f"test_it10_photog_{uuid.uuid4().hex[:6]}@example.com"
        s, pr2 = call(admin, "POST", "/providers", {"first_name": "TEST_IT10_Photog", "last_name": "Y",
                                                    "email": other_email, "categories": ["saxophoniste"],
                                                    "base_rate": 500, "language": "fr-FR"})
        assert s == 200, pr2
        mid2 = str(uuid.uuid4())
        DB.missions.insert_one({
            "id": mid2, "org_id": ORG, "created_at": "2026-11-19T10:00:00+00:00",
            "request_id": "", "recipient_id": "", "provider_id": pr2["id"],
            "provider_name": "TEST_IT10 Photog", "event_id": client_ctx["event_id"],
            "category_key": "saxophoniste", "date": "2027-06-12", "start_time": "18:00",
            "end_time": "23:00", "venue_city": "Uzès", "agreed_rate": 500, "agreed_travel_fee": 0,
            "vat_mode": "not_applicable_293B", "vat_rate": 0, "total_ht": 500, "total_ttc": 500,
            "equipment_needed": [], "equipment_note": "", "missing_equipment": [], "status": "confirmed",
        })
        # Instance Clerk de dev plafonnée à 100 utilisateurs : on réutilise deux comptes QA existants pour la connexion
        logins = ["qa_dj_a+clerk_test@example.com", "qa_prov_a+clerk_test@example.com"]
        saved = list(DB.users.find({"email": {"$in": logins}}))
        yield {"dj_mid": mid, "dj_contact": pr["contact_id"], "dj_email": logins[0],
               "other_mid": mid2, "other_contact": pr2["contact_id"], "other_email": logins[1],
               "pr_id": pr["id"], "pr2_id": pr2["id"]}
        DB.missions.delete_one({"id": mid})
        DB.missions.delete_one({"id": mid2})
        DB.provider_profiles.delete_one({"id": pr["id"]})
        DB.provider_profiles.delete_one({"id": pr2["id"]})
        DB.contacts.delete_many({"email": {"$in": [email, other_email]}})
        for u in saved:
            DB.users.replace_one({"_id": u["_id"]}, u)

    def test_non_dj_mission_returns_404_on_music(self, dj_mission):
        t = tok("provider", dj_mission["other_email"], dj_mission["other_contact"])
        code, _ = call(t, "GET", f"/portal/provider/missions/{dj_mission['other_mid']}/music")
        assert code == 404

    def test_dj_cannot_edit(self, dj_mission):
        t = tok("provider", dj_mission["dj_email"], dj_mission["dj_contact"])
        s, p = call(t, "GET", f"/portal/provider/missions/{dj_mission['dj_mid']}/music")
        assert s == 200
        # DJ never exposes guest_url / suggestions
        assert "guest_url" not in p
        assert "suggestions" not in p
        # DJ cannot PUT
        body = {"moments": p["moments"], "banned": [], "useful_info": {},
                "genre_preferences": {}, "guest_requests_enabled": False}
        code, _ = call(t, "PUT", f"/portal/provider/missions/{dj_mission['dj_mid']}/music", body)
        assert code == 403

    def test_cancelled_dj_mission_returns_404(self, admin, dj_mission):
        mid = dj_mission["dj_mid"]
        code, _ = call(admin, "PATCH", f"/missions/{mid}", {"status": "cancelled"})
        assert code in (200, 204), code
        t = tok("provider", dj_mission["dj_email"], dj_mission["dj_contact"])
        code, _ = call(t, "GET", f"/portal/provider/missions/{mid}/music")
        assert code == 404
        # restore so other tests in the class can still reuse (teardown deletes)
        DB.missions.update_one({"id": mid}, {"$set": {"status": "confirmed"}})


# ---------- Staff permissions ----------

class TestStaffPermissions:
    def test_technicien_cannot_save_music(self, tech, client_ctx):
        s, p = call(tech, "GET", f"/events/{client_ctx['event_id']}/music")
        # technicien has no access to arbitrary events -> 404 is fine; if 200, PUT must 403
        if s == 200:
            body = {"moments": p["moments"], "banned": [], "useful_info": {},
                    "genre_preferences": {}, "guest_requests_enabled": False}
            code, _ = call(tech, "PUT", f"/events/{client_ctx['event_id']}/music", body)
            assert code == 403
        else:
            assert s == 404


# ---------- /music-plans list ----------

class TestMusicPlansList:
    def test_music_plans_has_expected_event(self, admin, client_ctx):
        s, rows = call(admin, "GET", "/music-plans")
        assert s == 200
        ids = [r["event_id"] for r in rows]
        assert client_ctx["event_id"] in ids
        row = next(r for r in rows if r["event_id"] == client_ctx["event_id"])
        for k in ("title", "start", "status", "lock_date", "completion", "visible", "pending"):
            assert k in row
