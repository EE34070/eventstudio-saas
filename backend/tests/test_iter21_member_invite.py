"""Iter 21 — invitation des membres (envoyer / renvoyer / copier le lien / échec). QA sandbox only, aucun e-mail réel (adresses example.com bloquées en préversion)."""
import os
import uuid

import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

from conftest import API  # noqa: E402
from test_iter17_quote_blocks import sess  # noqa: E402

MONGO = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
CLERK = {"Authorization": f"Bearer {os.environ['CLERK_SECRET_KEY']}", "User-Agent": "emergent-app"}
ORPHAN = os.environ.get("QA_ORPHAN_CLERK_EMAIL", "")
S = {}


def _mk(s, email, send=False):
    r = s.post(f"{API}/team", json={"name": f"TEST_Inv {uuid.uuid4().hex[:5]}", "email": email, "access_role": "technicien", "send_invite": send})
    assert r.status_code == 200, r.text
    S.setdefault("ids", []).append(r.json()["id"])
    return r.json()


def teardown_module():
    s = sess("admin")
    for i in S.get("ids", []):
        s.delete(f"{API}/team/{i}")


def test_created_without_invite_is_not_invited():
    s = sess("admin")
    m = _mk(s, f"qa_noinv_{uuid.uuid4().hex[:6]}+clerk_test@example.com")
    assert m["access"]["status"] == "none" and "invite_link" not in m
    assert s.get(f"{API}/team/{m['id']}/invite-link").status_code == 404


def test_failed_send_shows_error_with_reason_never_success():
    s = sess("admin")
    m = _mk(s, f"qa_fail_{uuid.uuid4().hex[:6]}+clerk_test@example.com", send=True)
    a = m["access"]
    assert a["status"] == "error" and a["error"] and a["invited_at"], a
    row = next(x for x in s.get(f"{API}/team").json() if x["id"] == m["id"])
    assert row["access"]["status"] == "error" and "invite_link" not in row and "invite_token_id" not in row
    qa = MONGO.orgs.find_one({"slug": "qa-sandbox"})["id"]
    log = MONGO.audit_logs.find_one({"org_id": qa, "action": "member_invitation", "target": m["email"]})
    assert log and log["detail"].startswith("échec") and log["actor_name"]


def test_send_resend_invalidates_previous_link_and_copy():
    if not ORPHAN:
        import pytest
        pytest.skip("Aucun compte Clerk libre (quota de 100 atteint) : parcours lien créé / renvoyé non exécutable")
    s = sess("admin")
    m = _mk(s, ORPHAN)
    a = s.post(f"{API}/team/{m['id']}/invite").json()["access"]
    assert a["has_link"] and a["status"] == "error" and "préversion" in a["error"]
    l1 = s.get(f"{API}/team/{m['id']}/invite-link").json()["link"]
    assert "/sign-in?__clerk_ticket=" in l1
    qa = MONGO.orgs.find_one({"slug": "qa-sandbox"})["id"]
    t1 = MONGO.team.find_one({"org_id": qa, "id": m["id"]})["invite_token_id"]
    assert s.post(f"{API}/team/{m['id']}/invite").status_code == 200
    l2 = s.get(f"{API}/team/{m['id']}/invite-link").json()["link"]
    assert l2 != l1
    toks = requests.get("https://api.clerk.com/v1/sign_in_tokens/" + t1, headers=CLERK, timeout=15)
    assert toks.status_code != 200 or toks.json().get("status") == "revoked", toks.text


def test_rbac():
    s = sess("admin")
    m = _mk(s, "")
    assert sess("technicien").post(f"{API}/team/{m['id']}/invite").status_code == 403
    assert s.post(f"{API}/team/{m['id']}/invite").json()["access"]["status"] == "error"
