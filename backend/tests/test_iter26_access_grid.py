"""Iter 26 — grille module × action, « Voir comme ce membre », cycle de vie, transfert (QA sandbox uniquement, à lancer en séquentiel)."""
import os
import subprocess
import uuid
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

from conftest import API  # noqa: E402

DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
MAIL = "qa_{}+clerk_test@example.com"


def sess(role):
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip()
    return s


def boot():
    s = sess("admin")
    d = s.get(f"{API}/access-profiles").json()
    return s, d, {u["email"]: u["user_id"] for u in d["users"]}, {p["name"]: p for p in d["profiles"]}


def test_grid_listed_and_admin_locked():
    s, d, _, profs = boot()
    assert len(d["modules"]) >= 20 and "validate" in next(m for m in d["modules"] if m["key"] == "quotes")["actions"]
    adm = profs["Administrateur"]
    assert adm["locked"] and s.put(f"{API}/access-profiles/{adm['id']}", json={"name": "XX", "permissions": {}}).status_code == 403
    assert s.get(f"{API}/me").json()["grid"] is None


def test_grid_cells_enforced_and_menu():
    c = sess("commercial")
    s, d, users, profs = boot()
    uid, com = users[MAIL.format("commercial")], profs["Commercial"]
    grid = {**com["permissions"], "contacts": {"view": False}, "quotes": {"view": True, "create": False, "update": False, "delete": False, "export": True, "validate": False}}
    p = s.post(f"{API}/access-profiles", json={"name": f"TEST_GRID_{uuid.uuid4().hex[:6]}", "permissions": grid, "sensitive": {"send_quotes_invoices": False}})
    assert p.status_code == 200, p.text
    p = p.json()
    try:
        assert p["permissions"]["contacts"]["create"] is False
        assert s.patch(f"{API}/users/{uid}/profile", json={"profile_id": p["id"]}).status_code == 200
        assert c.get(f"{API}/quotes").status_code == 200
        assert c.post(f"{API}/quotes/direct", json={}).status_code == 403
        assert c.get(f"{API}/contacts").status_code == 403
        assert c.get(f"{API}/events").status_code == 200
        me = c.get(f"{API}/me").json()
        assert me["grid"]["contacts"]["view"] is False and me["grid"]["quotes"]["view"] is True
        assert "contacts" not in c.get(f"{API}/search", params={"q": "aa"}).json() or c.get(f"{API}/search", params={"q": "aa"}).json()["contacts"] == []
    finally:
        s.patch(f"{API}/users/{uid}/profile", json={"profile_id": com["id"]})
        assert s.delete(f"{API}/access-profiles/{p['id']}").status_code == 200
    assert c.get(f"{API}/contacts").status_code == 200


def test_default_profiles_keep_legacy_rights():
    for role, ok, ko in (("commercial", ["/events", "/contacts", "/quotes", "/crm/opportunities"], ["/access-profiles", "/providers"]),
                         ("comptable", ["/quotes", "/invoices"], ["/crm/opportunities", "/access-profiles", "/purchase-invoices"]),
                         ("technicien", ["/events", "/equipment", "/tasks"], ["/quotes", "/contacts", "/access-profiles"])):
        c = sess(role)
        for path in ok:
            assert c.get(API + path).status_code == 200, (role, path)
        for path in ko:
            assert c.get(API + path).status_code == 403, (role, path)


def test_view_as_member_read_only_and_audited():
    sess("commercial")
    s, d, users, _ = boot()
    uid = users[MAIL.format("commercial")]
    h = {"X-View-As-Member": uid}
    me = s.get(f"{API}/me", headers=h).json()
    assert me["preview"] and "users:manage" not in me["perms"] and me["grid"]
    assert s.get(f"{API}/access-profiles", headers=h).status_code == 403
    assert s.get(f"{API}/events", headers=h).status_code == 200
    assert s.post(f"{API}/tasks", headers=h, json={"title": "x"}).status_code == 403
    assert DB.audit_logs.find_one({"action": "view_as_member", "target": MAIL.format("commercial")})
    c = sess("commercial")
    assert c.get(f"{API}/me", headers={"X-View-As-Member": users[MAIL.format("admin")]}).status_code == 403


def test_gerant_cannot_touch_admin():
    g = sess("gerant")
    s, d, users, profs = boot()
    adm = users[MAIL.format("admin")]
    assert g.get(f"{API}/me", headers={"X-View-As-Member": adm}).status_code == 404
    assert g.post(f"{API}/members/{adm}/do/suspend").status_code == 403
    assert g.patch(f"{API}/users/{users[MAIL.format('commercial')]}/profile", json={"profile_id": profs["Administrateur"]["id"]}).status_code == 403
    assert s.post(f"{API}/members/{adm}/do/disable").status_code == 403


def test_contract_end_disables_then_reactivate():
    c = sess("comptable")
    s, d, users, _ = boot()
    uid = users[MAIL.format("comptable")]
    org = DB.users.find_one({"user_id": uid})["org_id"]
    tid = str(uuid.uuid4())
    body = {"name": "TEST_IT26 fin", "email": f"test_it26_{tid[:6]}@example.com", "contract_type": "cdd"}
    DB.team.insert_one({**body, "id": tid, "org_id": org, "user_id": uid, "active": True, "access_role": "comptable", "skills": [], "unavailabilities": []})
    try:
        soon = (date.today() + timedelta(days=3)).isoformat()
        assert s.put(f"{API}/team/{tid}", json={**body, "end_date": soon}).status_code == 200
        assert DB.tasks.find_one({"source_ref": f"contract-end:{tid}"}) and c.get(f"{API}/quotes").status_code == 200
        past = (date.today() - timedelta(days=2)).isoformat()
        assert s.put(f"{API}/team/{tid}", json={**body, "end_date": past}).status_code == 200
        assert DB.users.find_one({"user_id": uid})["status"] == "disabled"
        assert c.get(f"{API}/quotes").status_code in (401, 403)
        assert sess("comptable").get(f"{API}/me").status_code == 403
        assert s.post(f"{API}/members/{uid}/do/reactivate").status_code == 200
        assert sess("comptable").get(f"{API}/quotes").status_code == 200
    finally:
        DB.team.delete_one({"id": tid})
        DB.tasks.delete_many({"source_ref": f"contract-end:{tid}"})
        DB.users.update_one({"user_id": uid}, {"$set": {"status": "active"}, "$unset": {"sessions_revoked_at": ""}})


def test_handover_moves_open_tasks():
    sess("commercial")
    s, d, users, _ = boot()
    src, dst = users[MAIL.format("commercial")], users[MAIL.format("admin")]
    t = s.post(f"{API}/tasks", json={"title": "TEST_IT26 transfert", "assignee_ids": [src]}).json()
    try:
        assert s.get(f"{API}/members/{src}/handover").json()["tasks"] >= 1
        r = s.post(f"{API}/members/{src}/handover", json={"to_user_id": dst, "events": False, "opportunities": False})
        assert r.status_code == 200 and r.json()["tâches"] >= 1
        assert DB.tasks.find_one({"id": t["id"]})["assignee_ids"] == [dst]
        assert s.post(f"{API}/members/{src}/handover", json={"to_user_id": src}).status_code == 400
    finally:
        DB.tasks.delete_one({"id": t["id"]})


def test_2fa_required_per_profile_blocks_until_enabled():
    c = sess("commercial")
    s, d, users, profs = boot()
    com = profs["Commercial"]
    base = {"name": com["name"], "permissions": com["permissions"], "sensitive": com.get("sensitive") or {}}
    try:
        assert s.put(f"{API}/access-profiles/{com['id']}", json={**base, "require_2fa": "required"}).status_code == 200
        assert c.get(f"{API}/me").json()["needs_2fa"] is True
        assert c.get(f"{API}/events").status_code == 403
    finally:
        assert s.put(f"{API}/access-profiles/{com['id']}", json={**base, "require_2fa": "optional"}).status_code == 200
    assert c.get(f"{API}/events").status_code == 200
