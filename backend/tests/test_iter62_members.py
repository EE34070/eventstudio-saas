"""Iter 62 — modifier / supprimer des membres (QA uniquement, aucun e-mail : adresses +clerk_test@example.com)."""
import os
import uuid

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

from tests.test_iter54_dj_tab_roadmap import BASE, sess

load_dotenv("/app/backend/.env")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
CK = lambda m, p, **k: requests.request(m, "https://api.clerk.com/v1" + p, headers={"Authorization": f"Bearer {os.environ['CLERK_SECRET_KEY']}"}, timeout=15, **k)  # noqa: E731
TAG = "TESTM62" + uuid.uuid4().hex[:5]


def test_members():
    a, g, t = sess("admin"), sess("gerant"), sess("technicien")
    org = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
    tech = DB.users.find_one({"email": "qa_technicien+clerk_test@example.com"})
    row0 = DB.team.find_one({"org_id": org, "user_id": tech["user_id"]})
    made = None if row0 else DB.team.insert_one({"id": "tm" + TAG, "org_id": org, "name": "QA Technicien", "email": tech["email"], "access_role": "technicien", "active": True, "user_id": tech["user_id"], "skills": [], "color": "#000", "created_at": "2026-01-01"})
    tid = (row0 or {}).get("id") or "tm" + TAG
    DB.users.update_one({"user_id": tech["user_id"]}, {"$set": {"team_id": tid}})
    try:
        d = a.get(f"{BASE}/api/members").json()
        me_row = next(r for r in d["rows"] if r["user_id"] == tech["user_id"])
        profs = {p["base_role"]: p["id"] for p in d["profiles"] if p["base_role"]}
        body = {k: me_row.get(k) or "" for k in ("first_name", "last_name", "email", "phone", "photo", "job", "start_date", "end_date")} | {"contract_type": me_row["contract_type"], "language": "fr-FR", "status": "active"}
        # 1. changement de profil appliqué à la requête suivante, sans reconnexion
        before = set(t.get(f"{BASE}/api/me").json()["perms"])
        assert "contacts:write" not in before and d["can_delete"]
        r = a.put(f"{BASE}/api/members/{tid}", json={**body, "profile_id": profs["commercial"], "job": "Poste " + TAG})
        assert r.status_code == 200, r.text
        assert "contacts:write" in t.get(f"{BASE}/api/me").json()["perms"] and "contacts:write" in t.get(f"{BASE}/api/me/permissions").json()["perms"]
        a.put(f"{BASE}/api/members/{tid}", json={**body, "profile_id": profs["technicien"]})
        assert set(t.get(f"{BASE}/api/me").json()["perms"]) == before
        log = DB.audit_logs.find_one({"org_id": org, "action": "member_updated", "detail": {"$regex": TAG}})
        assert log and "→" in log["detail"]
        assert not g.get(f"{BASE}/api/members").json()["can_delete"] and "users:delete" not in g.get(f"{BASE}/api/me").json()["perms"]
        mine = next(r for r in d["rows"] if r["is_self"])
        if mine["id"]:
            assert a.post(f"{BASE}/api/trash/delete", json={"items": [{"kind": "member", "id": mine["id"]}]}).status_code == 403
        mail = f"{TAG.lower()}+clerk_test@example.com"
        inv = a.post(f"{BASE}/api/team", json={"name": f"{TAG} Invité", "email": mail, "access_role": "technicien", "send_invite": True}).json()
        tok = DB.team.find_one({"id": inv["id"]})["invite_token_id"]
        assert g.post(f"{BASE}/api/trash/delete", json={"items": [{"kind": "member", "id": inv["id"]}]}).status_code == 403
        mail2 = f"{TAG.lower()}b+clerk_test@example.com"
        r = a.put(f"{BASE}/api/members/{inv['id']}", json={"first_name": TAG, "last_name": "Invité", "email": mail2, "contract_type": "cdi", "status": "invited"}).json()
        assert r["invitation_resent"] and CK("GET", "/users", params={"email_address": mail}).json() == []
        tok2 = DB.team.find_one({"id": inv["id"]})["invite_token_id"]
        assert tok2 != tok
        assert a.post(f"{BASE}/api/trash/delete", json={"items": [{"kind": "member", "id": inv["id"]}]}).status_code == 200
        assert CK("GET", "/users", params={"email_address": mail2}).json()[0]["banned"] is True
        assert inv["id"] not in [r["id"] for r in a.get(f"{BASE}/api/members").json()["rows"]] and inv["id"] not in [r["id"] for r in a.get(f"{BASE}/api/team").json()]
        assert a.post(f"{BASE}/api/trash/restore", json={"items": [{"kind": "member", "id": inv["id"]}]}).status_code == 200
        assert CK("GET", "/users", params={"email_address": mail2}).json()[0]["banned"] is False and inv["id"] in [r["id"] for r in a.get(f"{BASE}/api/team").json()]
        a.post(f"{BASE}/api/trash/delete", json={"items": [{"kind": "member", "id": inv["id"]}]})
        assert a.post(f"{BASE}/api/trash/purge", json={"items": [{"kind": "member", "id": inv["id"]}]}).status_code == 200
        assert CK("GET", "/users", params={"email_address": mail2}).json() == [] and not DB.team.find_one({"id": inv["id"]})
    finally:
        a.put(f"{BASE}/api/members/{tid}", json={**body, "profile_id": profs["technicien"]})
        for m in (f"{TAG.lower()}+clerk_test@example.com", f"{TAG.lower()}b+clerk_test@example.com"):
            for cu in CK("GET", "/users", params={"email_address": m}).json():
                CK("DELETE", f"/users/{cu['id']}")
        DB.team.delete_many({"org_id": org, "name": {"$regex": "^" + TAG}})
        if made:
            DB.team.delete_one({"id": "tm" + TAG})
            DB.users.update_one({"user_id": tech["user_id"]}, {"$set": {"team_id": None}})


def test_delete_visible_for_all():
    from tests.test_iter54_dj_tab_roadmap import BASE, sess
    rows = sess("admin").get(f"{BASE}/api/members").json()["rows"]
    assert all("delete_block" in m for m in rows)
    me = [m for m in rows if m["is_self"]]
    assert me and all("propre compte" in m["delete_block"] for m in me)
    assert all(not m["delete_block"] or m["is_self"] or "Dernier administrateur" in m["delete_block"] for m in rows)
    assert all(m["delete_block"] for m in sess("gerant").get(f"{BASE}/api/members").json()["rows"])
