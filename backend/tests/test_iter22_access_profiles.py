"""Iter 22 — profils d'accès configurables (étapes 1 à 4 partielles). QA sandbox only."""
import os

from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

from conftest import API  # noqa: E402
from test_iter17_quote_blocks import sess  # noqa: E402

MONGO = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
LEGACY = {"commercial": "Commercial", "comptable": "Comptabilité", "technicien": "Technicien / chauffeur", "chef_projet": "Chargé de projet", "admin": "Administrateur"}


def _d():
    s = sess("admin")
    d = s.get(f"{API}/access-profiles").json()
    if not d["active"]:
        assert s.post(f"{API}/access-profiles/activate").status_code == 200
        d = s.get(f"{API}/access-profiles").json()
    return s, d


def test_migration_keeps_exact_rights_per_role():
    import sys
    sys.path.insert(0, '/app/backend')
    import core
    s, d = _d()
    assert s.post(f"{API}/access-profiles/activate").status_code == 409
    names = {p["id"]: p for p in d["profiles"]}
    assert {"Gérant", "Logistique / dépôt", "Lecture seule"} <= {p["name"] for p in d["profiles"]}
    for role, name in LEGACY.items():
        me = sess(role).get(f"{API}/me/permissions").json()
        assert me["profile"]["name"] == name and set(me["perms"]) == core.PERMS[role], role
        u = next(u for u in d["users"] if u["email"] == f"qa_{role}+clerk_test@example.com")
        assert names[u["access_profile_id"]]["name"] == name
    assert sess("technicien").get(f"{API}/me/permissions").json()["scope"] == "assigned"


def test_custom_profile_applies_on_next_request_and_guards():
    s, d = _d()
    com = next(p for p in d["profiles"] if p["name"] == "Commercial")
    uid = next(u["user_id"] for u in d["users"] if u["email"] == "qa_commercial+clerk_test@example.com")
    c = sess("commercial")
    assert c.get(f"{API}/quotes").status_code == 200
    r = s.post(f"{API}/access-profiles", json={"name": "TEST_Wedding planner interne", "perms": [p for p in com["perms"] if p != "finance:read"]})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    try:
        assert s.patch(f"{API}/users/{uid}/profile", json={"profile_id": pid}).status_code == 200
        assert c.get(f"{API}/quotes").status_code == 403
        assert "finance:read" not in c.get(f"{API}/me").json()["perms"]
        assert c.get(f"{API}/events").status_code == 200
        assert s.delete(f"{API}/access-profiles/{pid}").status_code == 409
        assert c.get(f"{API}/access-profiles").status_code == 403
        assert c.patch(f"{API}/users/{uid}/profile", json={"profile_id": com["id"]}).status_code == 403
    finally:
        assert s.patch(f"{API}/users/{uid}/profile", json={"profile_id": com["id"]}).status_code == 200
        assert s.delete(f"{API}/access-profiles/{pid}").status_code == 200
    assert c.get(f"{API}/quotes").status_code == 200
    qa = MONGO.orgs.find_one({"slug": "qa-sandbox"})["id"]
    assert MONGO.audit_logs.find_one({"org_id": qa, "action": "member_profile_changed"}) and MONGO.audit_logs.find_one({"org_id": qa, "action": "access_profile_deleted"})


def test_admin_profile_locked_and_self_protected():
    s, d = _d()
    adm = next(p for p in d["profiles"] if p["locked"])
    body = {"name": "X admin", "perms": []}
    assert s.put(f"{API}/access-profiles/{adm['id']}", json=body).status_code == 403
    assert s.delete(f"{API}/access-profiles/{adm['id']}").status_code == 403
    me = next(u["user_id"] for u in d["users"] if u["email"] == "qa_admin+clerk_test@example.com")
    assert s.patch(f"{API}/users/{me}/profile", json={"profile_id": adm["id"]}).status_code == 403
    assert s.post(f"{API}/access-profiles", json={"name": "TEST_bad", "perms": ["nope:x"]}).status_code == 400


def _commercial(d):
    return next(p for p in d["profiles"] if p["name"] == "Commercial"), next(u["user_id"] for u in d["users"] if u["email"] == "qa_commercial+clerk_test@example.com")


def test_sensitive_fields_removed_server_side():
    s, d = _d()
    com, uid = _commercial(d)
    c = sess("commercial")
    q0 = c.get(f"{API}/quotes").json()[0]
    assert "total_ttc" in q0 and any(x.get("email") for x in c.get(f"{API}/contacts").json())
    pid = s.post(f"{API}/access-profiles", json={"name": "TEST_Sans prix", "perms": com["perms"], "sensitive": {"sale_prices": False, "client_contacts": False}}).json()["id"]
    try:
        assert s.patch(f"{API}/users/{uid}/profile", json={"profile_id": pid}).status_code == 200
        r = c.get(f"{API}/quotes")
        assert r.status_code == 200 and r.json() and '"total_ttc"' not in r.text and '"unit_price"' not in r.text and '"total_ht"' not in r.text
        r = c.get(f"{API}/contacts")
        assert r.status_code == 200 and r.json() and '"email"' not in r.text and '"phone"' not in r.text and all(x.get("last_name") is not None for x in r.json())
        assert c.get(f"{API}/quotes/{q0['id']}/pdf").status_code == 403
        assert c.get(f"{API}/me").json()["user"]["email"]
        assert "total_ttc" in s.get(f"{API}/quotes").json()[0]
    finally:
        assert s.patch(f"{API}/users/{uid}/profile", json={"profile_id": com["id"]}).status_code == 200
        assert s.delete(f"{API}/access-profiles/{pid}").status_code == 200
    assert "total_ttc" in c.get(f"{API}/quotes").json()[0]


def test_overrides_with_end_date():
    from datetime import date, timedelta
    s, d = _d()
    _, uid = _commercial(d)
    c, put = sess("commercial"), lambda rows: s.put(f"{API}/users/{uid}/overrides", json={"overrides": rows})
    try:
        assert put([{"perm": "finance:read", "grant": False}]).status_code == 200
        assert c.get(f"{API}/quotes").status_code == 403
        assert put([{"perm": "finance:read", "grant": False, "expires_at": (date.today() - timedelta(days=1)).isoformat()}]).status_code == 200
        assert c.get(f"{API}/quotes").status_code == 200
        assert c.get(f"{API}/access-profiles").status_code == 403
        assert put([{"perm": "users:manage", "grant": True, "expires_at": (date.today() + timedelta(days=3)).isoformat()}]).status_code == 200
        assert c.get(f"{API}/access-profiles").status_code == 200
        assert c.put(f"{API}/users/{uid}/overrides", json={"overrides": []}).status_code == 403
        assert put([{"perm": "nope:x", "grant": True}]).status_code == 400
    finally:
        assert put([]).status_code == 200
    assert c.get(f"{API}/access-profiles").status_code == 403
    me = next(u["user_id"] for u in d["users"] if u["email"] == "qa_admin+clerk_test@example.com")
    assert s.put(f"{API}/users/{me}/overrides", json={"overrides": []}).status_code == 403
