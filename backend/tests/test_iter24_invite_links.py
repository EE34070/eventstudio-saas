"""Iter 24 — Bug fixes autour de l'invitation d'un membre et du ticket d'invitation.

QA sandbox only. Vérifie :
- /api/team POST sans e-mail (pas de plantage, access.status none)
- /api/team POST avec e-mail + send_invite=false (status none, pas de lien)
- /api/team POST avec e-mail + send_invite=true (vers un e-mail @example.com) :
    * pas d'exception 500
    * le lien d'invitation stocké pointe vers l'hôte de REACT_APP_BACKEND_URL (pas un hôte 'cluster-...emergentcf.cloud')
      lorsque la requête envoie l'en-tête Origin.
- /api/public/invitations/renew avec un ticket bidon renvoie 404 avec un détail français propre (pas 500, pas écran blanc).
- Les membres TEST_ créés sont supprimés en fin de module.
"""
import os
import uuid
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

from conftest import API, BASE_URL  # noqa: E402
from test_iter17_quote_blocks import sess  # noqa: E402

MONGO = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
PUBLIC_HOST = urlparse(BASE_URL).hostname or ""
STATE: dict = {"ids": []}


def _mk(s, **kw):
    body = {"name": f"TEST_IT24 {uuid.uuid4().hex[:5]}", "access_role": "technicien", **kw}
    r = s.post(f"{API}/team", json=body, headers={"Origin": BASE_URL, "Referer": BASE_URL + "/equipe"})
    assert r.status_code == 200, r.text
    j = r.json()
    STATE["ids"].append(j["id"])
    return j


def teardown_module():
    s = sess("admin")
    for i in STATE["ids"]:
        s.delete(f"{API}/team/{i}")


def test_create_no_email_no_crash():
    s = sess("admin")
    m = _mk(s, email="")
    assert m["access"]["status"] == "none"
    assert "invite_link" not in m and "invite_token_id" not in m
    # Pas de lien à récupérer
    r = s.get(f"{API}/team/{m['id']}/invite-link")
    assert r.status_code == 404


def test_create_with_email_no_send():
    s = sess("admin")
    email = f"qa_it24_noinv_{uuid.uuid4().hex[:6]}+clerk_test@example.com"
    m = _mk(s, email=email, send_invite=False)
    assert m["access"]["status"] == "none"
    assert s.get(f"{API}/team/{m['id']}/invite-link").status_code == 404


def test_create_with_send_invite_stores_public_host_link():
    """Le lien doit pointer vers l'hôte public (REACT_APP_BACKEND_URL / Origin),
    jamais vers l'hôte interne du cluster."""
    s = sess("admin")
    email = f"qa_it24_send_{uuid.uuid4().hex[:6]}+clerk_test@example.com"
    m = _mk(s, email=email, send_invite=True)
    a = m["access"]
    # En préversion, @example.com est bloqué par la garde domaine -> status 'error'
    # mais le lien doit avoir été créé côté Clerk et stocké en base.
    assert a["status"] in ("sent", "error"), a
    assert a["invited_at"]
    # On vérifie le lien directement en base (jamais exposé en lecture)
    qa = MONGO.orgs.find_one({"slug": "qa-sandbox"})
    assert qa, "org qa-sandbox absente"
    row = MONGO.team.find_one({"org_id": qa["id"], "id": m["id"]})
    link = row.get("invite_link") or ""
    assert link, f"invite_link absent (access={a})"
    parsed = urlparse(link)
    assert parsed.scheme == "https"
    assert parsed.hostname == PUBLIC_HOST, (
        f"Le lien d'invitation pointe vers {parsed.hostname!r}, pas vers "
        f"l'hôte public {PUBLIC_HOST!r} (regression : hôte interne utilisé)"
    )
    assert "/sign-in" in parsed.path and "__clerk_ticket=" in (parsed.query or "")


def test_renew_invitation_with_bogus_ticket_returns_404_french():
    """Un ticket inconnu (ou mal formé) ne doit jamais crasher : 404 avec message FR."""
    import requests
    r = requests.post(
        f"{API}/public/invitations/renew",
        json={"ticket": "sit_" + "x" * 40 + ".abc.def"},
        timeout=15,
    )
    assert r.status_code == 404, r.text
    body = r.json()
    assert "detail" in body
    # Message français attendu
    assert any(w in body["detail"].lower() for w in ("lien", "reconnu", "invitation")), body


def test_renew_invitation_with_random_ticket_returns_404():
    """Ticket complètement bidon (ex. 'abc.def.ghi' reçu depuis l'UI de secours)."""
    import requests
    r = requests.post(
        f"{API}/public/invitations/renew",
        json={"ticket": "abcdefghijklmnopqrstuvwxyz.aGVsbG8=.ZmFrZXNpZw=="},
        timeout=15,
    )
    assert r.status_code == 404
