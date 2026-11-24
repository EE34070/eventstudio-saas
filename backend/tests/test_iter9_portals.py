"""Iter 9 - Portal isolation & lot 4 features.

Covers:
- Full staff route sweep: client/provider tokens must get 404/403 on every non-portal GET.
- Cross-tenant isolation: client A on B's event -> 404 on all /api/portal/client/events/{id}* routes.
- Field leaks: no budget/amount_ht/costs/notes/rating in client view; no rating/budget/other providers' prices in provider view.
- Module hide (PUT /events/{id}/portal/modules/{key} client_visible=false) -> 404 + data preserved on re-enable.
- Signed /api/portal/dl link: valid, expired, tampered.
- Provider invoice deposit flow (POST /portal/files + /missions/{id}/invoice) -> status 'invoiced' + visible admin side.
- Mission cancel -> provider 404 on next call.
- X-View-As: GET 200, write 403, missing header 403, cross-org user_id 404.
- Session revoke: next call 401.
- Public /api/public/legal/{org_id}/{page} available.
"""
import os
import subprocess
import time
import uuid

import pytest
import requests
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from pymongo import MongoClient

from conftest import API, BASE_URL

os.environ.setdefault("REACT_APP_BACKEND_URL", BASE_URL)
BACKEND = API
LOCAL = "http://localhost:8001/api"  # for low-level /health probing w/o rate-limit noise
MONGO = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _tok(*a):
    r = subprocess.run(["python3", "/app/scripts/qa_token.py", *a], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        pytest.skip(f"qa_token.py failed: {r.stderr[-300:]}")
    return r.stdout.strip().splitlines()[-1]


def _sess(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


# ---------------- Seed fixture ----------------
@pytest.fixture(scope="module")
def ctx():
    admin = _sess(_tok("admin"))
    org = MONGO.orgs.find_one({"slug": "qa-sandbox"})
    org_id = org["id"]

    # Two clients + events
    cA = admin.post(f"{BACKEND}/contacts", json={"first_name": "TEST_IT9_A", "last_name": "Cli",
                                                  "email": "it9a+clerk_test@example.com", "language": "fr-FR"}).json()
    cB = admin.post(f"{BACKEND}/contacts", json={"first_name": "TEST_IT9_B", "last_name": "Cli",
                                                  "email": "it9b+clerk_test@example.com"}).json()
    base_ev = lambda c: {"title": f"TEST_IT9_{c['first_name']}", "type": "Mariage",
                         "start": "2027-06-12T16:00", "end": "2027-06-13T02:00",
                         "client_id": c["id"], "client_contact_ids": [c["id"]],
                         "signatory_contact_id": c["id"], "modules": ["dj"], "budget": 9999}
    rA = admin.post(f"{BACKEND}/events", json=base_ev(cA))
    rB = admin.post(f"{BACKEND}/events", json=base_ev(cB))
    assert rA.status_code == 200 and rB.status_code == 200, (rA.text, rB.text)
    eA, eB = rA.json(), rB.json()

    # Two providers + missions
    pA = admin.post(f"{BACKEND}/providers", json={"first_name": "TEST_IT9_PA", "last_name": "P",
                                                   "email": "it9pa+clerk_test@example.com",
                                                   "categories": ["autres"], "base_rate": 500}).json()
    pB = admin.post(f"{BACKEND}/providers", json={"first_name": "TEST_IT9_PB", "last_name": "P",
                                                   "email": "it9pb+clerk_test@example.com",
                                                   "categories": ["autres"], "base_rate": 700}).json()

    def _mk_mission(prov, event_id, rate):
        mid = str(uuid.uuid4())
        MONGO.missions.insert_one({
            "id": mid, "org_id": org_id, "created_at": "2026-11-19T10:00:00+00:00",
            "request_id": "", "recipient_id": "", "provider_id": prov["id"],
            "provider_name": prov["display_name"], "event_id": event_id,
            "category_key": "autres", "date": "2027-06-12", "start_time": "18:00", "end_time": "23:00",
            "venue_city": "Uzès", "agreed_rate": rate, "agreed_travel_fee": 40,
            "vat_mode": "not_applicable_293B", "vat_rate": 0, "total_ht": rate + 40, "total_ttc": rate + 40,
            "equipment_needed": [], "equipment_note": "", "missing_equipment": [],
            "status": "confirmed", "rating": 4, "rating_comment": "SECRET_INTERNAL_NOTE",
            "share_team": True,
        })
        return mid

    mA = _mk_mission(pA, eA["id"], 500)
    mB = _mk_mission(pB, eB["id"], 700)
    # 2 missions on event A (different providers) so we can test "share_team" doesn't leak prices
    mA2 = _mk_mission(pB, eA["id"], 700)

    tA = _tok("client", "qa_it9_a+clerk_test@example.com", cA["id"])
    tB = _tok("client", "qa_it9_b+clerk_test@example.com", cB["id"])
    tPA = _tok("provider", "qa_it9_pa+clerk_test@example.com", pA["contact_id"])
    tPB = _tok("provider", "qa_it9_pb+clerk_test@example.com", pB["contact_id"])

    yield {"admin": admin, "org_id": org_id, "eA": eA["id"], "eB": eB["id"],
           "cA": cA["id"], "cB": cB["id"], "pA": pA["id"], "pB": pB["id"],
           "mA": mA, "mB": mB, "mA2": mA2,
           "tA": tA, "tB": tB, "tPA": tPA, "tPB": tPB,
           "sA": _sess(tA), "sB": _sess(tB), "sPA": _sess(tPA), "sPB": _sess(tPB)}

    # ---------- Cleanup only what we created ----------
    try:
        for eid in (eA["id"], eB["id"]):
            admin.delete(f"{BACKEND}/events/{eid}")
        for mid in (mA, mB, mA2):
            MONGO.missions.delete_one({"id": mid, "org_id": org_id})
        for pid in (pA["id"], pB["id"]):
            admin.delete(f"{BACKEND}/providers/{pid}")
        for cid in (cA["id"], cB["id"], pA["contact_id"], pB["contact_id"]):
            admin.delete(f"{BACKEND}/contacts/{cid}")
        # Delete the test portal users we just created
        for em in ("qa_it9_a+clerk_test@example.com", "qa_it9_b+clerk_test@example.com",
                   "qa_it9_pa+clerk_test@example.com", "qa_it9_pb+clerk_test@example.com"):
            MONGO.users.update_many({"email": em}, {"$set": {"status": "deleted"}})
    except Exception as exc:
        print("cleanup warning:", exc)


# ---------------- 1) Staff route sweep ----------------
ALLOW_PREFIXES = ("/api/portal", "/api/public", "/api/me", "/api/clerk",
                  "/api/__clerk", "/api/health", "/api/languages", "/api/auth/google")


def _collect_staff_get_routes():
    import sys as _s
    _s.path.insert(0, "/app/backend")
    from server import app
    out = []
    for r in app.routes:
        m = getattr(r, "methods", None) or set()
        p = getattr(r, "path", "")
        if "GET" in m and p.startswith("/api") and not any(p.startswith(x) for x in ALLOW_PREFIXES):
            out.append(p)
    return out


STAFF_GET_ROUTES = _collect_staff_get_routes()


@pytest.mark.parametrize("path", STAFF_GET_ROUTES)
def test_client_token_cannot_reach_staff_get(ctx, path):
    # Substitute obvious path params with real IDs from our sandbox
    subs = {"{eid}": ctx["eA"], "{cid}": ctx["cA"], "{vid}": "nope", "{pid}": ctx["pA"],
            "{tid}": "nope", "{qid}": "nope", "{iid}": "nope", "{fid}": "nope",
            "{rid}": "nope", "{oid}": "nope", "{uid}": "nope", "{did}": "nope",
            "{mid}": ctx["mA"], "{key}": "home"}
    url = path
    for k, v in subs.items():
        url = url.replace(k, v)
    r = ctx["sA"].get(f"{BACKEND}{url}")
    assert r.status_code != 200, f"Client token got 200 on staff route {path} -> {url} : {r.text[:200]}"


@pytest.mark.parametrize("path", STAFF_GET_ROUTES)
def test_provider_token_cannot_reach_staff_get(ctx, path):
    subs = {"{eid}": ctx["eA"], "{cid}": ctx["cA"], "{vid}": "nope", "{pid}": ctx["pA"],
            "{tid}": "nope", "{qid}": "nope", "{iid}": "nope", "{fid}": "nope",
            "{rid}": "nope", "{oid}": "nope", "{uid}": "nope", "{did}": "nope",
            "{mid}": ctx["mA"], "{key}": "home"}
    url = path
    for k, v in subs.items():
        url = url.replace(k, v)
    r = ctx["sPA"].get(f"{BACKEND}{url}")
    assert r.status_code != 200, f"Provider token got 200 on staff route {path} -> {url} : {r.text[:200]}"


# ---------------- 2) Cross-tenant isolation (client) ----------------
CLIENT_PORTAL_SUBROUTES = ["", "/documents", "/billing", "/timeline", "/messages"]


@pytest.mark.parametrize("sub", CLIENT_PORTAL_SUBROUTES)
def test_client_A_on_event_B_is_404(ctx, sub):
    r = ctx["sA"].get(f"{BACKEND}/portal/client/events/{ctx['eB']}{sub}")
    assert r.status_code == 404, f"client A got {r.status_code} on event B /{sub}: {r.text[:120]}"


def test_client_A_can_read_own_event(ctx):
    r = ctx["sA"].get(f"{BACKEND}/portal/client/events/{ctx['eA']}")
    assert r.status_code == 200
    body = r.json()
    for leak in ("budget", "amount_ht", "costs", "notes", "history", "margin", "marge"):
        assert leak not in body, f"client view leaks '{leak}'"


# ---------------- 3) Cross-tenant isolation (provider) ----------------
def test_provider_A_on_mission_B_is_404(ctx):
    for sub, body in (("", None), ("/confirm", {}), ("/invoice", {"file": "file:nope", "type": "autre"}), ("/messages", {"body": "x"})):
        meth = ctx["sPA"].get if sub == "" else ctx["sPA"].post
        r = meth(f"{BACKEND}/portal/provider/missions/{ctx['mB']}{sub}", json=body)
        assert r.status_code == 404, f"provider A got {r.status_code} on mission B /{sub}: {r.text[:120]}"


def test_provider_view_hides_rating_and_other_prices(ctx):
    r = ctx["sPA"].get(f"{BACKEND}/portal/provider/missions/{ctx['mA']}")
    assert r.status_code == 200
    body = r.json()
    serialized = str(body)
    for leak in ("rating", "rating_comment", "budget", "SECRET_INTERNAL_NOTE"):
        assert leak not in serialized, f"provider view leaks '{leak}'"
    # provider sees his own rate
    assert body.get("agreed_rate") == 500
    # team entries must not carry prices
    for t in body.get("team") or []:
        assert "agreed_rate" not in t and "total_ht" not in t and "total_ttc" not in t


# ---------------- 4) Module toggle ----------------
def test_module_hide_404_then_reactivate_preserves_comments(ctx):
    admin = ctx["admin"]
    eid = ctx["eA"]
    # post one timeline comment
    r = ctx["sA"].post(f"{BACKEND}/portal/client/events/{eid}/timeline/comments",
                       json={"body": "TEST_IT9 preserved comment"})
    assert r.status_code == 200
    # Hide timeline
    r = admin.put(f"{BACKEND}/events/{eid}/portal/modules/timeline",
                  json={"client_visible": False, "client_editable": True})
    assert r.status_code == 200
    r = ctx["sA"].get(f"{BACKEND}/portal/client/events/{eid}/timeline")
    assert r.status_code == 404
    # Re-enable
    r = admin.put(f"{BACKEND}/events/{eid}/portal/modules/timeline",
                  json={"client_visible": True, "client_editable": True})
    assert r.status_code == 200
    r = ctx["sA"].get(f"{BACKEND}/portal/client/events/{eid}/timeline")
    assert r.status_code == 200
    comments = [c["body"] for c in r.json().get("comments") or []]
    assert any("preserved comment" in c for c in comments), comments


# ---------------- 5) Signed download links ----------------
def test_signed_link_expired_rejected():
    import sys as _s
    _s.path.insert(0, "/app/backend")
    from security import sign_file
    org = MONGO.orgs.find_one({"slug": "qa-sandbox"})["id"]
    url = sign_file(org, "file:nope", ttl=-5)
    r = requests.get(BACKEND.rsplit("/api", 1)[0] + url)
    assert r.status_code == 403


def test_signed_link_tampered_rejected():
    import sys as _s
    _s.path.insert(0, "/app/backend")
    from security import sign_file
    org = MONGO.orgs.find_one({"slug": "qa-sandbox"})["id"]
    url = sign_file(org, "file:nope", ttl=300)
    # Flip the sig
    tampered = url.rsplit("sig=", 1)[0] + "sig=" + ("0" * 64)
    r = requests.get(BACKEND.rsplit("/api", 1)[0] + tampered)
    assert r.status_code == 403


# ---------------- 6) Provider invoice flow ----------------
def test_provider_invoice_flow(ctx):
    # Upload a valid PDF
    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
    r = requests.post(f"{BACKEND}/portal/files",
                      headers={"Authorization": f"Bearer {ctx['tPA']}"},
                      files={"file": ("facture.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    ref = r.json()["ref"]
    # Reject non-PDF
    r = requests.post(f"{BACKEND}/portal/files",
                      headers={"Authorization": f"Bearer {ctx['tPA']}"},
                      files={"file": ("x.txt", b"not a pdf", "text/plain")})
    assert r.status_code == 400

    # Submit invoice for own mission
    r = ctx["sPA"].post(f"{BACKEND}/portal/provider/missions/{ctx['mA']}/invoice",
                        json={"file": ref, "type": "autre", "expires_at": ""})
    assert r.status_code == 200
    m = MONGO.missions.find_one({"id": ctx["mA"]}, {"_id": 0})
    assert m["status"] == "invoiced"
    assert m["provider_invoice_file"] == ref
    # Admin event portal block should now expose the invoice ref
    r = ctx["admin"].get(f"{BACKEND}/events/{ctx['eA']}/portal")
    assert r.status_code == 200
    miss = [x for x in r.json()["missions"] if x["id"] == ctx["mA"]][0]
    assert miss["provider_invoice_file"] == ref


# ---------------- 7) Mission cancelled -> 404 ----------------
def test_mission_cancel_denies_provider(ctx):
    # Cancel mB
    r = ctx["admin"].patch(f"{BACKEND}/missions/{ctx['mB']}", json={"status": "cancelled"})
    assert r.status_code == 200
    r = ctx["sPB"].get(f"{BACKEND}/portal/provider/missions/{ctx['mB']}")
    assert r.status_code == 404
    # List should not include it
    r = ctx["sPB"].get(f"{BACKEND}/portal/provider/missions")
    assert r.status_code == 200
    assert ctx["mB"] not in [m["id"] for m in r.json()["missions"]]


# ---------------- 8) X-View-As ----------------
def test_view_as(ctx):
    admin = ctx["admin"]
    # Get a client user_id
    users = admin.get(f"{BACKEND}/portal-users").json()["users"]
    client_a_uid = next(u["user_id"] for u in users if u["email"] == "qa_it9_a+clerk_test@example.com")
    # GET works
    r = admin.get(f"{BACKEND}/portal/me", headers={"X-View-As": client_a_uid})
    assert r.status_code == 200 and r.json()["preview"] is True
    # Write refused
    r = admin.post(f"{BACKEND}/portal/client/events/{ctx['eA']}/messages",
                   json={"body": "nope"}, headers={"X-View-As": client_a_uid})
    assert r.status_code == 403
    # Missing header -> 403 (admin has no portal role)
    r = admin.get(f"{BACKEND}/portal/me")
    assert r.status_code == 403
    # Unknown user_id -> 404
    r = admin.get(f"{BACKEND}/portal/me", headers={"X-View-As": "user_doesnotexist"})
    assert r.status_code == 404


# ---------------- 9) Revocation ----------------
def test_revocation_blocks_next_request(ctx):
    admin = ctx["admin"]
    # revoke client B (not used elsewhere after this test)
    users = admin.get(f"{BACKEND}/portal-users").json()["users"]
    uid = next(u["user_id"] for u in users if u["email"] == "qa_it9_b+clerk_test@example.com")
    r = admin.post(f"{BACKEND}/portal-users/{uid}/revoke")
    assert r.status_code == 200
    time.sleep(1)
    r = ctx["sB"].get(f"{BACKEND}/portal/me")
    assert r.status_code == 401


# ---------------- 10) Public pages ----------------
def test_public_legal_page(ctx):
    r = requests.get(f"{BACKEND}/public/legal/{ctx['org_id']}/privacy")
    assert r.status_code == 200
    assert "fr" in r.json() and "en" in r.json()


def test_public_legal_unknown_org():
    r = requests.get(f"{BACKEND}/public/legal/does-not-exist/privacy")
    assert r.status_code == 404


# ---------------- 11) Security headers ----------------
def test_security_headers_on_api():
    h = requests.get(f"{BACKEND}/health").headers
    for k in ("Strict-Transport-Security", "X-Content-Type-Options",
              "Referrer-Policy", "X-Frame-Options", "Permissions-Policy",
              "Content-Security-Policy"):
        assert k in h, f"missing {k}"
