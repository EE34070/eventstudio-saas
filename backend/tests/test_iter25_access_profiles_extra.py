"""Iter 25 — compléments aux tests iter22 sur les profils d'accès (QA sandbox uniquement).

Scénarios :
    - costs_margins décoché : cost / margin / rate disparaissent des réponses prestataires & finances événement
    - qa_admin voit toujours tous les montants et coordonnées (contrôle positif)
    - Un non-admin ne peut pas ajuster ses propres droits (PUT /users/<soi>/overrides = 403)
    - Dérogation avec date de fin passée : sans effet ; future : appliquée (cas supplémentaires)
    - Audit logs 'access_profile_updated' et 'member_overrides_changed' contiennent 'avant' / 'après'
    - Invitation @example.com : POST /team/<id>/invite renvoie access.status='error' avec motif 'Adresse de test' et has_link=True
"""
import os
import uuid
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

from conftest import API  # noqa: E402
from test_iter17_quote_blocks import sess  # noqa: E402

MONGO = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _bootstrap():
    """Activate profiles if needed, return (admin_session, dict_payload)."""
    s = sess("admin")
    d = s.get(f"{API}/access-profiles").json()
    if not d["active"]:
        assert s.post(f"{API}/access-profiles/activate").status_code == 200
        d = s.get(f"{API}/access-profiles").json()
    return s, d


def _commercial(d):
    com = next(p for p in d["profiles"] if p["name"] == "Commercial")
    uid = next(u["user_id"] for u in d["users"] if u["email"] == "qa_commercial+clerk_test@example.com")
    return com, uid


# --- 1. costs_margins : les champs cost / margin / rate disparaissent ------
def test_costs_margins_hidden_removes_rate_and_cost_fields():
    s, d = _bootstrap()
    com, uid = _commercial(d)
    c = sess("commercial")
    # Contrôle initial : l'admin voit base_rate / vat_rate sur les prestataires
    provs_admin = s.get(f"{API}/providers").json()
    assert any("base_rate" in p or "vat_rate" in p for p in provs_admin), "pré-requis : admin doit voir les tarifs"
    perms_with_providers = sorted(set(com["perms"]) | {"providers:manage"})
    r = s.post(f"{API}/access-profiles", json={"name": "TEST_Sans couts", "perms": perms_with_providers, "sensitive": {"costs_margins": False}})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    try:
        assert s.patch(f"{API}/users/{uid}/profile", json={"profile_id": pid}).status_code == 200
        rp = c.get(f"{API}/providers")
        assert rp.status_code == 200, rp.text
        txt = rp.text
        # Fields explicitly listed in the brief + core.KEYS['costs_margins']
        for k in ('"cost"', '"margin"', '"rate"', '"margin_percent"', '"purchase_price"'):
            assert k not in txt, f"{k} ne doit pas apparaître avec costs_margins=False"
        # Les events : costs_total / purchases_total masqués
        evs = c.get(f"{API}/events")
        assert evs.status_code == 200
        evs_txt = evs.text
        for k in ('"costs_total"', '"purchases_total"', '"margin"', '"cost"'):
            assert k not in evs_txt, f"{k} ne doit pas apparaître dans /events"
        # qa_admin voit toujours tout (contrôle positif)
        assert '"base_rate"' in s.get(f"{API}/providers").text or '"vat_rate"' in s.get(f"{API}/providers").text
    finally:
        assert s.patch(f"{API}/users/{uid}/profile", json={"profile_id": com["id"]}).status_code == 200
        assert s.delete(f"{API}/access-profiles/{pid}").status_code == 200


# --- 2. qa_admin voit toujours montants et coordonnées ------
def test_admin_always_sees_amounts_and_contacts():
    s, _ = _bootstrap()
    q = s.get(f"{API}/quotes").json()
    assert q and any("total_ttc" in x for x in q), "admin doit voir total_ttc"
    ct = s.get(f"{API}/contacts").json()
    assert ct and any(x.get("email") or x.get("phone") for x in ct), "admin doit voir email/phone"


# --- 3. Non-admin ne peut pas ajuster ses propres droits ------
def test_cannot_adjust_own_overrides():
    s, d = _bootstrap()
    _, uid = _commercial(d)
    c = sess("commercial")
    r = c.put(f"{API}/users/{uid}/overrides", json={"overrides": []})
    assert r.status_code == 403, r.text
    # Message may be either the self-rights guard or the users:manage guard; both are acceptable 403s per the brief.


# --- 4. Dérogation avec date de fin passée : sans effet ; future : appliquée ------
def test_override_past_date_is_noop_future_applied():
    s, d = _bootstrap()
    _, uid = _commercial(d)
    c = sess("commercial")
    try:
        # Passé : retirer finance:read avec expires_at d'hier → doit rester accordé
        r = s.put(f"{API}/users/{uid}/overrides",
                  json={"overrides": [{"perm": "finance:read", "grant": False, "expires_at": (date.today() - timedelta(days=1)).isoformat()}]})
        assert r.status_code == 200
        assert c.get(f"{API}/quotes").status_code == 200, "dérogation expirée ne doit pas s'appliquer"
        # Futur : même dérogation avec expires_at de demain → 403
        r = s.put(f"{API}/users/{uid}/overrides",
                  json={"overrides": [{"perm": "finance:read", "grant": False, "expires_at": (date.today() + timedelta(days=1)).isoformat()}]})
        assert r.status_code == 200
        assert c.get(f"{API}/quotes").status_code == 403, "dérogation future doit s'appliquer"
    finally:
        assert s.put(f"{API}/users/{uid}/overrides", json={"overrides": []}).status_code == 200


# --- 5. Audit logs 'access_profile_updated' + 'member_overrides_changed' ------
def test_audit_logs_contain_before_after():
    s, d = _bootstrap()
    _, uid = _commercial(d)
    org = MONGO.orgs.find_one({"slug": "qa-sandbox"})["id"]
    # Create then update a profile
    pid = s.post(f"{API}/access-profiles", json={"name": f"TEST_AUD_{uuid.uuid4().hex[:6]}", "perms": ["events:read"]}).json()["id"]
    try:
        r = s.put(f"{API}/access-profiles/{pid}", json={"name": f"TEST_AUD_ren_{uuid.uuid4().hex[:6]}", "perms": ["events:read", "catalog:read"]})
        assert r.status_code == 200
        log = MONGO.audit_logs.find_one({"org_id": org, "action": "access_profile_updated"}, sort=[("at", -1)])
        assert log and "avant" in log["detail"] and "après" in log["detail"], log

        # Overrides audit
        assert s.put(f"{API}/users/{uid}/overrides", json={"overrides": [{"perm": "users:manage", "grant": True}]}).status_code == 200
        olog = MONGO.audit_logs.find_one({"org_id": org, "action": "member_overrides_changed"}, sort=[("at", -1)])
        assert olog and "avant" in olog["detail"] and "après" in olog["detail"], olog
    finally:
        assert s.put(f"{API}/users/{uid}/overrides", json={"overrides": []}).status_code == 200
        assert s.delete(f"{API}/access-profiles/{pid}").status_code == 200


# --- 6. Invitation @example.com → 'Adresse de test' + has_link ------
def test_invitation_to_example_com_returns_test_address_error_with_link():
    s, _ = _bootstrap()
    # Create a TEST_ team member with @example.com address
    body = {"name": f"TEST_IT25_{uuid.uuid4().hex[:6]}", "email": f"test_it25_{uuid.uuid4().hex[:8]}@example.com",
            "access_role": "technicien", "send_invite": False}
    r = s.post(f"{API}/team", json=body)
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    try:
        inv = s.post(f"{API}/team/{tid}/invite", headers={"Origin": os.environ.get("REACT_APP_BACKEND_URL", "")})
        assert inv.status_code == 200, inv.text
        access = inv.json()["access"]
        assert access["status"] == "error", access
        assert "test" in access["error"].lower() or "adresse de test" in access["error"].lower(), access
        assert access["has_link"] is True, "Le lien doit être disponible même quand l'envoi échoue sur adresse de test"
        # Le lien doit être récupérable
        link = s.get(f"{API}/team/{tid}/invite-link").json().get("link", "")
        assert "sign-in" in link and "__clerk_ticket=" in link
    finally:
        s.delete(f"{API}/team/{tid}")
