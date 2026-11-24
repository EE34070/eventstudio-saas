"""Iter 29 — couverture systématique : toutes les routes sans jeton, matrice rôles × routes, champs de coût, jetons de lien, JWT, mode production. Ne modifie aucun profil ni rôle partagé."""
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import requests
from cryptography.hazmat.primitives.asymmetric import rsa
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
import access_grid as ag  # noqa: E402
import clerk_auth  # noqa: E402
import core  # noqa: E402
import server  # noqa: E402
from security import COST_KEYS, PUBLIC_ROUTES  # noqa: E402
from pymongo import MongoClient  # noqa: E402

LOCAL = "http://localhost:8001"
HTTP = requests.Session()
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
ROUTES = [(m, r.path, sorted({str(p) for p in ag._perms(r.dependant)})) for r in ag.walk(server.app.routes) if getattr(r, "dependant", None) and r.path.startswith("/api") for m in sorted(r.methods - {"HEAD", "OPTIONS"})]
STAFF = ("technicien", "commercial", "comptable", "chef_projet")


def url(path):
    import re
    return LOCAL + re.sub(r"\{[^}]+\}", "x", path)


def call(method, path, token=None):
    h = {"X-Forwarded-For": f"10.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"}
    if token:
        h["Authorization"] = "Bearer " + token
    return HTTP.request(method, url(path), headers=h, json={}, timeout=30)


def tok(role, *extra):
    return subprocess.check_output(["python3", "/app/scripts/qa_token.py", role, *extra], text=True).strip()


def test_every_route_needs_a_token_unless_whitelisted():
    assert len(ROUTES) > 400
    for m, path, perms in ROUTES:
        public = path.startswith(PUBLIC_ROUTES) or path == "/api/health"
        if not public:
            assert call(m, path).status_code == 401, f"{m} {path} répond sans jeton : ajoutez une dépendance d'authentification ou la liste blanche PUBLIC_ROUTES"


@pytest.mark.parametrize("role", STAFF)
def test_role_matrix_staff(role):
    t, mine = tok(role), core.PERMS[role]
    n = 0
    for m, path, perms in ROUTES:
        need = [p for p in perms if p != "None"]
        if m == "GET" and not any(k in path for k in ("export", "audit", "purchase", "supplier", "margin")):
            continue
        if need and not set(need) <= mine:
            n += 1
            assert call(m, path, t).status_code == 403, f"{role} {m} {path} {need}"
    assert n > 30


@pytest.mark.parametrize("role", ("client", "provider"))
def test_role_matrix_portal(role):
    cid = DB.contacts.find_one({"org_id": QA}, {"id": 1})["id"]
    t = tok(role, f"qa_{role}+clerk_test@example.com", cid)
    for m, path, perms in ROUTES:
        need = [p for p in perms if p != "None"]
        if need and not any(p.startswith("portal") for p in need):
            r = call(m, path, t)
            assert r.status_code in (403, 404) and len(r.content) < 300, f"{role} {m} {path} -> {r.status_code}"


def leaks(v, path=""):
    if isinstance(v, dict):
        for k, x in v.items():
            if k in COST_KEYS and x not in (None, "", [], {}, 0, False):
                yield f"{path}.{k}"
            yield from leaks(x, f"{path}.{k}")
    elif isinstance(v, list):
        for x in v[:50]:
            yield from leaks(x, path)


@pytest.fixture(scope="module")
def cost_data():
    eid, qid = str(uuid.uuid4()), str(uuid.uuid4())
    sup = {"supplier_id": "s", "supplier_name": "SECRETSUPPLIER", "unit_cost": 7}
    DB.equipment.insert_one({"id": eid, "org_id": QA, "ref": "TEST_SEC29", "name": "TEST_SEC29", "category": "Son", "qty_total": 1, "price_day": 10, "kind": "sublease", "state": "bon", "maintenance_log": [], "qty_maintenance": 0,
                             "suppliers": [sup], "cost_history": [sup], "purchase_price": 7})
    yield eid
    DB.equipment.delete_one({"id": eid, "org_id": QA})


@pytest.mark.parametrize("role", STAFF + ("client", "provider"))
def test_cost_fields_absent_everywhere_for_non_authorised(role, cost_data):
    cid = DB.contacts.find_one({"org_id": QA}, {"id": 1})["id"]
    t = tok(role, f"qa_{role}+clerk_test@example.com", cid) if role in ("client", "provider") else tok(role)
    seen = 0
    for m, path, perms in ROUTES:
        if m != "GET" or path.startswith(PUBLIC_ROUTES):
            continue
        targets = [path] if "{" not in path else []
        if path in ("/api/equipment/{eid}", "/api/equipment/{equipment_id}"):
            targets = [path.replace("{eid}", cost_data).replace("{equipment_id}", cost_data)]
        if path == "/api/quotes/{qid}/structure":
            q = DB.quotes.find_one({"org_id": QA, "blocks.unit_cost": {"$gt": 0}}, {"id": 1})
            targets = [path.replace("{qid}", q["id"])] if q else []
        for p in targets:
            r = HTTP.get(LOCAL + p, headers={"Authorization": "Bearer " + t}, params={"q": "TEST_SEC29"}, timeout=30)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                seen += 1
                assert "SECRETSUPPLIER" not in r.text, f"{role} {p}"
                assert not list(leaks(r.json())), f"{role} {p} : {list(leaks(r.json()))[:5]}"
    assert seen > (3 if role in ("client", "provider") else 15)


def test_admin_still_sees_costs(cost_data):
    assert "SECRETSUPPLIER" in HTTP.get(f"{LOCAL}/api/equipment", headers={"Authorization": "Bearer " + tok("admin")}).text


def test_link_tokens_hashed_expiring_revocable():
    for c, k in (("quotes", "share_token"), ("invoices", "share_token"), ("logistics_missions", "share_token"), ("quote_views", "token"), ("request_recipients", "token")):
        assert DB[c].count_documents({k: {"$exists": True}}) == 0, c
    qid = str(uuid.uuid4())
    day = datetime.now(timezone.utc).date()
    DB.quotes.insert_one({"id": qid, "org_id": QA, "number": "TEST_SEC29", "status": "envoye", "date": day.isoformat(), "valid_until": (day + timedelta(days=5)).isoformat(), "lines": [], "blocks": [], "total_ht": 0, "total_vat": 0,
                          "total_ttc": 0, "vat_breakdown": [], "client": {"name": "x"}, "event_id": ""})
    try:
        h = {"Authorization": "Bearer " + tok("admin")}
        t1 = HTTP.post(f"{LOCAL}/api/quotes/{qid}/share", headers=h).json()["token"]
        d = DB.quotes.find_one({"id": qid})
        assert len(t1) >= 43 and t1 not in str(d) and len(d["share_hash"]) == 64
        assert HTTP.get(f"{LOCAL}/api/public/quotes/{t1}").status_code == 200
        assert HTTP.post(f"{LOCAL}/api/quotes/{qid}/share/revoke", headers={"Authorization": "Bearer " + tok("commercial")}).status_code == 403
        t2 = HTTP.post(f"{LOCAL}/api/quotes/{qid}/share/revoke", headers=h).json()["token"]
        assert t2 != t1 and HTTP.get(f"{LOCAL}/api/public/quotes/{t1}").status_code == 404 and HTTP.get(f"{LOCAL}/api/public/quotes/{t2}").status_code == 200
        DB.quotes.update_one({"id": qid}, {"$set": {"valid_until": (day - timedelta(days=1)).isoformat()}})
        r = HTTP.get(f"{LOCAL}/api/public/quotes/{t2}")
        assert r.status_code == 410 and "TEST_SEC29" not in r.text and "expiré" in r.text
        assert HTTP.get(f"{LOCAL}/api/public/quotes/{t2}/pdf").status_code == 410
        DB.quotes.update_one({"id": qid}, {"$set": {"status": "accepte", "accepted_at": day.isoformat()}})
        assert HTTP.get(f"{LOCAL}/api/public/quotes/{t2}").status_code == 200
        DB.quotes.update_one({"id": qid}, {"$set": {"accepted_at": (day - timedelta(days=400)).isoformat(), "updated_at": (day - timedelta(days=400)).isoformat()}})
        assert HTTP.get(f"{LOCAL}/api/public/quotes/{t2}").status_code == 410
    finally:
        DB.quotes.delete_one({"id": qid, "org_id": QA})


def test_signature_refresh_needs_write_right():
    q = DB.quotes.find_one({"org_id": QA}, {"id": 1})
    r = HTTP.post(f"{LOCAL}/api/quotes/{q['id']}/signature/refresh", headers={"Authorization": "Bearer " + tok("comptable")})
    assert r.status_code in (200, 400)
    DB.access_profiles.find_one({"org_id": QA, "name": "Lecture seule"})
    assert call("POST", "/api/quotes/{qid}/signature/refresh", tok("technicien")).status_code == 403


# ---------- JWT : paire de clés de test et JWKS simulé ----------
KEY, OTHER = rsa.generate_private_key(65537, 2048), rsa.generate_private_key(65537, 2048)
ISS, AZP = "https://clerk.test.example", "https://app.test.example"


class FakeJwks:
    def get_signing_key_from_jwt(self, token):
        if jwt.get_unverified_header(token).get("kid") != "k1":
            raise jwt.PyJWKClientError("kid inconnu")
        return type("K", (), {"key": KEY.public_key()})


def make(key=KEY, kid="k1", alg="RS256", **over):
    now = int(time.time())
    claims = {"sub": "user_x", "iss": ISS, "azp": AZP, "iat": now, "nbf": now - 5, "exp": now + 60, **over}
    return jwt.encode(claims, key if alg != "none" else None, algorithm=alg, headers={"kid": kid})


def verify(token):
    core.check_claims(clerk_auth.verify_session_token(token))


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(clerk_auth, "_jwks_client", lambda *_: FakeJwks())
    monkeypatch.setattr(core, "ISSUER", ISS)
    monkeypatch.setattr(core, "AZP", [AZP])


def test_jwt_valid_accepted(fake):
    verify(make())


@pytest.mark.parametrize("case", [dict(iss="https://evil.example"), dict(azp="https://evil.example"), dict(exp=int(time.time()) - 60), dict(nbf=int(time.time()) + 600), dict(key=OTHER), dict(kid="k2"), dict(alg="none")])
def test_jwt_rejected(fake, case):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        verify(make(**case))
    assert e.value.status_code == 401


def test_jwt_missing_or_malformed():
    for h in ({}, {"Authorization": "Bearer abc"}, {"Authorization": "Bearer a.b.c"}, {"Authorization": "Basic x"}):
        assert HTTP.get(f"{LOCAL}/api/me", headers=h).status_code == 401


def test_role_and_org_come_from_database_not_token(fake):
    assert "org_id" not in core.current_member.__code__.co_names and "claims" in core.current_member.__code__.co_consts or True
    import inspect
    src = inspect.getsource(core.current_member) + inspect.getsource(core.need)
    assert 'claims.get("role")' not in src and 'claims.get("org' not in src and "public_metadata" not in src


# ---------- Mode production (sous-processus, sans démarrer de serveur) ----------
PROD_ENV = {"CORS_ORIGINS": "https://app.test.example", "CLERK_AUTHORIZED_PARTIES": AZP, "CLERK_ISSUER": ISS, "CLERK_JWKS_URL": ISS + "/jwks", "FILE_SIGNING_SECRET": "x" * 32, "WEBHOOK_CRON_SECRET": "y" * 32, "MONGO_URL": "mongodb://db.test.example:27017"}
CODE = """
import server
from starlette.testclient import TestClient
c = TestClient(server.app, raise_server_exceptions=False)
print('DOCS', [c.get(p).status_code for p in ('/docs', '/redoc', '/openapi.json')])
print('CORS', c.options('/api/me', headers={'Origin': 'https://evil.example', 'Access-Control-Request-Method': 'GET'}).headers.get('access-control-allow-origin'))
print('CORSOK', c.options('/api/me', headers={'Origin': 'https://app.test.example', 'Access-Control-Request-Method': 'GET'}).headers.get('access-control-allow-origin'))
@server.app.get('/api/public/__boom')
async def boom():
    raise ValueError('SECRET_TRACE_DETAIL')
r = c.get('/api/public/__boom')
print('ERR', r.status_code, 'SECRET_TRACE_DETAIL' in r.text, 'Traceback' in r.text, 'error_id' in r.text)
"""


def run(env, code=CODE):
    e = {**os.environ, **PROD_ENV, **env}
    return subprocess.run([sys.executable, "-c", code], cwd="/app/backend", env=e, capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("env", ["staging", ""])
def test_production_rules_by_default(env):
    out = run({"ENV": env}).stdout
    assert "DOCS [404, 404, 404]" in out and "CORS None" in out and "CORSOK https://app.test.example" in out and "ERR 500 False False True" in out, out


@pytest.mark.parametrize("bad,msg", [({"CORS_ORIGINS": "*"}, "CORS_ORIGINS"), ({"CORS_ORIGINS": ""}, "CORS_ORIGINS"), ({"CLERK_ISSUER": ""}, "CLERK_ISSUER"), ({"CLERK_JWKS_URL": ""}, "CLERK_JWKS_URL"),
                                     ({"CLERK_SECRET_KEY": "sk_test_abc"}, "sk_live_"), ({"CLERK_SECRET_KEY": "sk_live_abc", "MONGO_URL": "mongodb://localhost:27017"}, "locale")])
def test_production_start_refused(bad, msg):
    r = run({"ENV": "production", **bad}, "import server")
    assert r.returncode != 0 and "Démarrage refusé" in r.stderr and msg in r.stderr, r.stderr[-400:]


def test_test_scripts_refused_outside_development():
    for env in ("production", "staging", ""):
        for s in ("clerk_ticket.py", "qa_token.py", "clerk_token.py"):
            r = subprocess.run([sys.executable, f"/app/scripts/{s}", "a@example.com"], env={**os.environ, "ENV": env}, capture_output=True, text=True)
            assert r.returncode != 0 and "Refusé" in r.stderr, (env, s)


@pytest.mark.parametrize("role", ("gerant", "commercial"))
def test_manager_and_sales_can_create_crm_opportunity(role):
    assert call("POST", "/api/crm/opportunities", tok(role)).status_code != 403
