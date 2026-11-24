"""Iter 28 — audit de sécurité : accès croisés, rôles, champs sensibles, liens publics, en-têtes (QA sandbox + société jetable TEST_SEC_, séquentiel)."""
import os
import subprocess
import uuid

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

from conftest import API  # noqa: E402

DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]


def sess(role, *extra):
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", role, *extra], text=True).strip()
    return s


@pytest.fixture(scope="module")
def other():
    """Société B jetable avec un enregistrement de chaque type."""
    oid = "TEST_SEC_" + uuid.uuid4().hex[:8]
    DB.orgs.insert_one({"id": oid, "name": "TEST_SEC société B", "slug": oid})
    ids = {}
    for c in ("events", "contacts", "quotes", "invoices", "equipment", "venues", "tasks", "files", "supplier_quotes", "team"):
        ids[c] = str(uuid.uuid4())
        DB[c].insert_one({"id": ids[c], "org_id": oid, "title": "TEST_SEC", "name": "TEST_SEC", "number": "TEST_SEC", "status": "brouillon", "lines": [], "blocks": []})
    yield ids
    for c in ids:
        DB[c].delete_many({"org_id": oid})
    DB.orgs.delete_one({"id": oid})


def test_cross_company_read_and_write_refused(other):
    s = sess("admin")
    paths = {"events": "/events/{}", "contacts": "/contacts/{}", "quotes": "/quotes/{}/structure", "equipment": "/equipment/{}", "venues": "/venues/{}", "files": "/files/{}",
             "supplier_quotes": "/supplier-quotes/{}/order-draft", "invoices": "/invoices/{}/pdf"}
    for c, p in paths.items():
        assert s.get(API + p.format(other[c])).status_code in (404, 405), c
    assert s.delete(f"{API}/contacts/{other['contacts']}").status_code == 404
    assert s.patch(f"{API}/tasks/{other['tasks']}", json={"title": "x"}).status_code == 404
    assert s.post(f"{API}/quotes/{other['quotes']}/send").status_code == 404
    assert s.post(f"{API}/quotes/{other['quotes']}/share/revoke").status_code == 404
    assert s.get(f"{API}/contacts/{other['contacts']}/gdpr-export").status_code == 404
    for c in ("events", "contacts", "quotes", "equipment"):
        assert "TEST_SEC" not in s.get(f"{API}/{c}").text, c
    assert DB.contacts.find_one({"id": other["contacts"]})


def test_technician_refused_on_finance_and_admin():
    t = sess("technicien")
    for p in ("/quotes", "/invoices", "/purchase-invoices", "/contacts", "/access-profiles", "/audit-logs", "/supplier-quotes", "/margin-rules", "/portal-users", "/crm/opportunities"):
        assert t.get(API + p).status_code == 403, p
    assert t.post(f"{API}/quotes/direct", json={}).status_code in (403, 422)
    assert t.put(f"{API}/margin-rules", json={}).status_code == 403
    raw = t.get(f"{API}/equipment").text
    for k in ("unit_cost", "cost_history", '"suppliers"', "supplier_name"):
        assert k not in raw, k


def test_cost_fields_hidden_from_non_managers_in_catalog():
    eid = str(uuid.uuid4())
    DB.equipment.insert_one({"id": eid, "org_id": QA, "ref": "TEST_SEC", "name": "TEST_SEC sous-loc", "category": "Son", "qty_total": 0, "price_day": 10, "kind": "sublease", "state": "bon", "maintenance_log": [],
                             "qty_maintenance": 0, "suppliers": [{"supplier_id": "x", "supplier_name": "SECRETSUPPLIER", "unit_cost": 7}], "cost_history": [{"unit_cost": 7, "supplier_name": "SECRETSUPPLIER"}]})
    try:
        for role in ("commercial", "technicien", "chef_projet"):
            assert "SECRETSUPPLIER" not in sess(role).get(f"{API}/equipment").text, role
        assert "SECRETSUPPLIER" in sess("admin").get(f"{API}/equipment").text
    finally:
        DB.equipment.delete_one({"id": eid, "org_id": QA})


def test_client_and_provider_isolated():
    cs = [c["id"] for c in DB.contacts.find({"org_id": QA}, {"id": 1}).limit(2)]
    a = sess("client", "qa_client+clerk_test@example.com", cs[0])
    for p in ("/events", "/quotes", "/contacts", "/equipment", "/team", "/supplier-quotes", "/access-profiles"):
        r = a.get(API + p)
        assert r.status_code in (403, 404) and len(r.text) < 200, p
    mine = {e["id"] for e in a.get(f"{API}/portal/client/events").json()}
    foreign = DB.events.find_one({"org_id": QA, "id": {"$nin": list(mine)}}, {"id": 1})
    assert a.get(f"{API}/portal/client/events/{foreign['id']}").status_code in (403, 404)
    assert a.get(f"{API}/portal/client/events/{foreign['id']}/billing").status_code in (403, 404)
    p = sess("provider", "qa_provider+clerk_test@example.com", cs[1])
    for path in ("/events", "/quotes", "/providers", "/staff/planning", "/portal/client/events"):
        r = p.get(API + path)
        assert r.status_code in (403, 404) and len(r.text) < 200, path
    other_mission = DB.missions.find_one({"org_id": QA}, {"id": 1})
    if other_mission:
        assert p.get(f"{API}/portal/provider/missions/{other_mission['id']}").status_code in (403, 404)


def test_no_token_and_bad_token_refused():
    for p in ("/me", "/events", "/quotes", "/files/abc", "/access-profiles"):
        assert requests.get(API + p).status_code == 401, p
        assert requests.get(API + p, headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401, p


def test_public_links_and_headers():
    for p in ("/public/quotes/" + "a" * 32, "/public/quote-views/" + "a" * 32, "/public/tracking/" + "a" * 32, "/public/provider-requests/" + "a" * 43, "/public/music/" + "a" * 43, "/public/ical/" + "a" * 43 + ".ics"):
        r = requests.get(API + p)
        assert r.status_code == 404, p
        assert r.headers["X-Robots-Tag"].startswith("noindex") and r.headers["X-Content-Type-Options"] == "nosniff" and "max-age" in r.headers["Strict-Transport-Security"]
    assert requests.post(f"{API}/cron/reminders").status_code == 401
    assert requests.post(f"{API}/crm/leads", json={"email": "a@example.com"}).status_code in (401, 503)
    assert requests.post(f"{API}/webhooks/yousign", data="{}").status_code in (401, 503)


def test_share_link_revocation():
    s = sess("admin")
    q = DB.quotes.find_one({"org_id": QA, "status": "brouillon", "valid_until": {"$gte": "2026-12-31"}}, {"id": 1}) or DB.quotes.find_one({"org_id": QA, "status": "accepte"}, {"id": 1})
    old = s.post(f"{API}/quotes/{q['id']}/share").json()["token"]
    assert requests.get(f"{API}/public/quotes/{old}").status_code == 200
    new = s.post(f"{API}/quotes/{q['id']}/share/revoke").json()["token"]
    assert new != old and len(new) >= 32
    assert requests.get(f"{API}/public/quotes/{old}").status_code == 404
    assert requests.get(f"{API}/public/quotes/{new}").status_code == 200
    assert sess("comptable").post(f"{API}/quotes/{q['id']}/signature/refresh").status_code in (400, 403, 200)


def test_gdpr_export_and_anonymize_contact():
    s = sess("admin")
    c = s.post(f"{API}/contacts", json={"first_name": "TEST_SEC", "last_name": "Rgpd", "email": "test_sec_rgpd@example.com", "phone": "0600000000"}).json()
    try:
        assert sess("commercial").get(f"{API}/contacts/{c['id']}/gdpr-export").status_code == 403
        assert s.get(f"{API}/contacts/{c['id']}/gdpr-export").json()["contact"]["email"] == "test_sec_rgpd@example.com"
        assert s.post(f"{API}/contacts/{c['id']}/gdpr-anonymize").status_code == 200
        d = DB.contacts.find_one({"id": c["id"]})
        assert d["email"] == "" and d["first_name"] == "Anonymisé" and d["phone"] == ""
        assert DB.audit_logs.find_one({"org_id": QA, "action": "anonymized", "target": c["id"]})
    finally:
        DB.contacts.delete_one({"id": c["id"], "org_id": QA})


def test_upload_content_checked():
    s = sess("admin")
    r = s.post(f"{API}/files", files={"file": ("x.pdf", b"<html>pas un pdf</html>", "application/pdf")})
    assert r.status_code == 400
    assert s.post(f"{API}/files", files={"file": ("x.exe", b"MZ", "application/x-msdownload")}).status_code == 400
