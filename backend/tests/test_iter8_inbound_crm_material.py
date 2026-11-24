"""Backend e2e for iter8 lots: Saisie IA (inbound), CRM, Matériel.
Always targets the QA sandbox org (slug qa-sandbox) via qa_token.py.
Never writes into the real "Exclusivity Events" org.
Never sends emails / followups / Gmail.
"""
import base64
import os
import subprocess
import time
import uuid

import pytest
import requests

from conftest import API

PREFIX = "TEST_IT8_"
RUN = uuid.uuid4().hex[:6]


def qa_token(role="admin"):
    out = subprocess.run(["python3", "/app/scripts/qa_token.py", role],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        pytest.skip(f"qa_token failed: {out.stderr[-300:]}")
    return out.stdout.strip().splitlines()[-1]


_sessions: dict[str, requests.Session] = {}


def sess(role="admin") -> requests.Session:
    if role in _sessions:
        return _sessions[role]
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {qa_token(role)}", "Content-Type": "application/json"})
    _sessions[role] = s
    return s


# ------------------------- cleanup registry ------------------------- #
_created: dict[str, list[str]] = {
    "inbound_requests": [], "opportunities": [], "events": [], "contacts": [],
    "venues": [], "product_documents": [], "equipment": [], "crm_tasks": [],
}


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    s = sess("admin")
    # Opportunities + related
    for oid in _created["opportunities"]:
        s.delete(f"{API}/crm/opportunities/{oid}")
    # Events
    for eid in _created["events"]:
        s.delete(f"{API}/events/{eid}")
    # Product documents
    for did in _created["product_documents"]:
        s.delete(f"{API}/product-documents/{did}")
    # Contacts
    for cid in _created["contacts"]:
        s.delete(f"{API}/contacts/{cid}")
    # Venues
    for vid in _created["venues"]:
        s.delete(f"{API}/venues/{vid}")
    # Equipment items we created
    for eqid in _created["equipment"]:
        s.delete(f"{API}/equipment/{eqid}")


# ============================================================================
# 0. SMOKE
# ============================================================================
def test_health():
    s = sess("admin")
    r = s.get(f"{API}/me")
    assert r.status_code == 200, r.text
    me = r.json()
    assert me.get("user", {}).get("role") == "admin"
    # must be QA org
    assert me.get("org", {}).get("slug") == "qa-sandbox", f"Wrong org! {me.get('org')}"


# ============================================================================
# 1. INBOUND / SAISIE IA
# ============================================================================
SAMPLE_TEXT = (
    f"Bonjour, je suis Claire {PREFIX}Dupont{RUN} (06 12 34 56 78, "
    f"claire.{RUN}@example.com), nous nous marions le 12 septembre 2027 au "
    "Domaine de Test à Uzès, 120 invités, on cherche un DJ et un photobooth, "
    "budget 3000 euros"
)


def test_inbound_parse_returns_structure():
    s = sess("admin")
    r = s.post(f"{API}/inbound-requests/parse",
               json={"raw_text": SAMPLE_TEXT, "source": "sms"})
    assert r.status_code == 200, r.text
    data = r.json()
    _created["inbound_requests"].append(data["id"])
    assert data["status"] == "draft"
    assert data["parsed"] is True, "AI parse failed"
    x = data["extracted_json"]
    # client
    assert "claire" in (x["client"]["first_name"] + x["client"]["last_name"]).lower()
    # event date (2027-09-12 expected)
    assert x["event"]["date"] == "2027-09-12", x["event"]["date"]
    assert x["event"]["guests"] == 120
    # modules include dj and photobooth
    mods = set(x["event"]["modules"])
    assert "dj" in mods and "photobooth" in mods, mods
    # budget
    assert x["event"]["budget_amount"] in (3000, 3000.0)
    # matches structure
    assert "matches" in data
    pytest.rid_parse = data["id"]


def test_inbound_parse_empty_meaningless_does_not_500():
    s = sess("admin")
    r = s.post(f"{API}/inbound-requests/parse",
               json={"raw_text": "aaaa bbbb cccc dddd", "source": "sms"})
    assert r.status_code == 200, r.text
    d = r.json()
    _created["inbound_requests"].append(d["id"])
    # parsed may be True (empty fields) or False — must not 500 anyway
    assert d["status"] == "draft"


def test_inbound_convert_to_opportunity():
    rid = getattr(pytest, "rid_parse", None)
    if not rid:
        pytest.skip("parse test did not run")
    s = sess("admin")
    r = s.get(f"{API}/inbound-requests/{rid}")
    assert r.status_code == 200
    x = r.json()["extracted_json"]
    client = {
        "first_name": x["client"]["first_name"] or f"{PREFIX}Claire",
        "last_name": x["client"]["last_name"] or f"Dupont{RUN}",
        "phone": x["client"]["phone"], "email": x["client"]["email"],
        "language": x["client"]["language"] or "fr-FR",
    }
    event = {
        "title": x["event"]["title_suggestion"] or f"{PREFIX}Mariage {RUN}",
        "type": x["event"]["category"] or "Mariage",
        "date": x["event"]["date"], "start_time": "18:00", "end_time": "02:00",
        "guests": x["event"]["guests"], "venue_name": x["event"]["venue_name"] or f"{PREFIX}Domaine",
        "venue_city": x["event"]["venue_city"] or "Uzès",
        "modules": x["event"]["modules"] or ["dj"],
        "budget": x["event"]["budget_amount"], "budget_tax_mode": "ttc", "notes": "",
    }
    body = {"target": "opportunity", "client": client, "event": event, "asked": []}
    r = s.post(f"{API}/inbound-requests/{rid}/convert", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["kind"] == "opportunity"
    _created["opportunities"].append(out["id"])
    # Follow-up: client contact should now exist
    pytest.opp_id = out["id"]


def test_inbound_convert_event_without_date_rejected():
    s = sess("admin")
    r = s.post(f"{API}/inbound-requests/parse",
               json={"raw_text": f"{PREFIX} test sans date aucune info", "source": "autre"})
    rid = r.json()["id"]
    _created["inbound_requests"].append(rid)
    body = {
        "target": "event",
        "client": {"first_name": f"{PREFIX}NoDate", "last_name": RUN},
        "event": {"title": f"{PREFIX}No date {RUN}", "type": "Autre", "date": "",
                  "modules": ["dj"], "budget": 0, "budget_tax_mode": "ttc"},
    }
    r = s.post(f"{API}/inbound-requests/{rid}/convert", json=body)
    assert r.status_code == 400, r.text
    assert "date" in r.text.lower()


def test_inbound_list_contains_drafts():
    s = sess("admin")
    r = s.get(f"{API}/inbound-requests")
    assert r.status_code == 200, r.text
    ids = {row["id"] for row in r.json()}
    assert any(rid in ids for rid in _created["inbound_requests"])


def test_inbound_availability():
    s = sess("admin")
    r = s.get(f"{API}/inbound-requests/availability", params={"day": "2099-01-01"})
    assert r.status_code == 200
    assert r.json() == []


# ============================================================================
# 2. CRM
# ============================================================================
def test_crm_config():
    s = sess("admin")
    r = s.get(f"{API}/crm/config")
    assert r.status_code == 200, r.text
    cfg = r.json()
    keys = {s["key"] for s in cfg["stages"]}
    assert {"nouvelle", "qualifiee", "devis_envoye", "negociation", "gagnee", "perdue"} <= keys


def _mk_client(s):
    r = s.post(f"{API}/contacts", json={
        "kind": "particulier", "first_name": f"{PREFIX}CRM", "last_name": f"Client{RUN}",
        "email": f"crm.{RUN}@example.com", "phone": "+33612345678",
        "types": ["client"], "language": "fr-FR",
    })
    assert r.status_code in (200, 201), r.text
    c = r.json()
    _created["contacts"].append(c["id"])
    return c["id"]


def test_crm_create_opp():
    s = sess("admin")
    cid = _mk_client(s)
    r = s.post(f"{API}/crm/opportunities", json={
        "title": f"{PREFIX}Opp {RUN}", "client_contact_id": cid, "event_type": "Mariage",
        "event_date": "2027-06-15", "amount": 5000, "amount_tax_mode": "ttc",
        "source_key": "instagram", "services": ["dj"],
    })
    assert r.status_code == 200, r.text
    o = r.json()
    _created["opportunities"].append(o["id"])
    assert o["stage_key"] == "nouvelle"
    pytest.opp2_id = o["id"]
    pytest.opp2_client = cid


def test_crm_duplicate_client_date_rejected():
    s = sess("admin")
    cid = getattr(pytest, "opp2_client")
    r = s.post(f"{API}/crm/opportunities", json={
        "title": f"{PREFIX}Dup {RUN}", "client_contact_id": cid, "event_type": "Mariage",
        "event_date": "2027-06-15", "amount": 1000,
    })
    assert r.status_code == 409, r.text


def test_crm_stage_change_requires_lost_reason():
    s = sess("admin")
    oid = pytest.opp2_id
    r = s.patch(f"{API}/crm/opportunities/{oid}", json={"stage_key": "perdue"})
    assert r.status_code == 400
    r = s.patch(f"{API}/crm/opportunities/{oid}",
                json={"stage_key": "perdue", "lost_reason": "prix"})
    assert r.status_code == 200, r.text
    assert r.json()["stage_key"] == "perdue"


def test_crm_postpone():
    s = sess("admin")
    # fresh opp (previous one is lost)
    cid = _mk_client(s)
    r = s.post(f"{API}/crm/opportunities", json={
        "title": f"{PREFIX}Post {RUN}", "client_contact_id": cid,
        "event_type": "Mariage", "event_date": "2027-07-01",
    })
    oid = r.json()["id"]
    _created["opportunities"].append(oid)
    r = s.post(f"{API}/crm/opportunities/{oid}/postpone", json={"days": 7, "done": False})
    assert r.status_code == 200, r.text
    r = s.post(f"{API}/crm/opportunities/{oid}/postpone",
               json={"days": 3, "done": True, "next_action": "Rappeler"})
    assert r.status_code == 200
    assert r.json()["next_action"] == "Rappeler"
    pytest.opp3_id = oid


def test_crm_activity_and_followup_preview():
    s = sess("admin")
    oid = pytest.opp3_id
    r = s.post(f"{API}/crm/opportunities/{oid}/activities",
               json={"type": "note", "body": f"{PREFIX}note test"})
    assert r.status_code == 200
    r = s.get(f"{API}/crm/opportunities/{oid}/followup")
    assert r.status_code == 200, r.text
    assert "subject" in r.json() and "body" in r.json()
    # DO NOT POST — would send mail


def test_crm_win_creates_event():
    s = sess("admin")
    oid = pytest.opp3_id
    r = s.post(f"{API}/crm/opportunities/{oid}/win", json={})
    assert r.status_code == 200, r.text
    opp = r.json()
    assert opp["event_id"]
    _created["events"].append(opp["event_id"])
    ev = s.get(f"{API}/events/{opp['event_id']}")
    assert ev.status_code == 200


def test_crm_dashboard_and_export():
    s = sess("admin")
    r = s.get(f"{API}/crm/dashboard")
    assert r.status_code == 200
    d = r.json()
    assert "open" in d and "won" in d and "lost" in d
    r = s.get(f"{API}/crm/opportunities/export.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    assert "Titre;Client" in r.text


def test_crm_rbac_technicien_forbidden():
    tok = qa_token("technicien")
    r = requests.get(f"{API}/crm/opportunities",
                     headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403, r.status_code


def test_crm_rbac_comptable_forbidden():
    tok = qa_token("comptable")
    r = requests.get(f"{API}/crm/opportunities",
                     headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403, r.status_code


# ============================================================================
# 3. MATÉRIEL
# ============================================================================
def _mk_equipment(s, name):
    ref = f"IT8{uuid.uuid4().hex[:6].upper()}"
    r = s.post(f"{API}/equipment", json={
        "name": f"{PREFIX}{name}_{RUN}", "ref": ref,
        "category": "sono", "qty_total": 10, "unit": "u",
    })
    assert r.status_code in (200, 201), r.text
    eq = r.json()
    _created["equipment"].append(eq["id"])
    return eq


def test_material_requirements_persist():
    s = sess("admin")
    eq = _mk_equipment(s, "Micro")
    # linked product (piles)
    piles = _mk_equipment(s, "Piles")
    reqs = [{
        "type": "consommable", "label": "Piles AA", "linked_product_id": piles["id"],
        "quantity": 2, "unit": "pile", "calc_mode": "per_unit_day",
        "spare_pct": 100, "mandatory": True,
    }]
    r = s.put(f"{API}/equipment/{eq['id']}/requirements", json={"requirements": reqs})
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1 and r.json()[0]["label"] == "Piles AA"
    # reopen (list, no single GET)
    r2 = s.get(f"{API}/equipment")
    assert r2.status_code == 200
    items = r2.json().get("items", [])
    eq_reloaded = next(x for x in items if x["id"] == eq["id"])
    assert len(eq_reloaded.get("requirements", [])) == 1
    pytest.mat_eq_id = eq["id"]
    pytest.mat_piles_id = piles["id"]


def test_product_documents_crud():
    s = sess("admin")
    eq_id = pytest.mat_eq_id
    # Upload a tiny PDF through /api/files
    pdf_bytes = b"%PDF-1.1\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
    files = {"file": ("doc.pdf", pdf_bytes, "application/pdf")}
    r = requests.post(f"{API}/files",
                      headers={"Authorization": s.headers["Authorization"]},
                      files=files)
    if r.status_code not in (200, 201):
        pytest.skip(f"files upload not available: {r.status_code} {r.text[:200]}")
    file_ref = r.json().get("ref") or r.json().get("file_ref") or r.json().get("id")
    if not file_ref:
        pytest.skip(f"files endpoint shape unexpected: {r.text[:200]}")
    if not file_ref.startswith("file:"):
        file_ref = f"file:{file_ref}"
    r = s.post(f"{API}/product-documents", json={
        "file_ref": file_ref, "type": "fiche_technique",
        "title": f"{PREFIX}Doc {RUN}", "visibility": "interne",
        "is_primary": True, "product_ids": [eq_id],
    })
    assert r.status_code == 200, r.text
    d = r.json()
    _created["product_documents"].append(d["id"])
    assert d["version"] == 1
    # replace
    r2 = requests.post(f"{API}/files",
                       headers={"Authorization": s.headers["Authorization"]},
                       files={"file": ("doc2.pdf", pdf_bytes + b"v2", "application/pdf")})
    if r2.status_code in (200, 201):
        new_ref = r2.json().get("ref") or r2.json().get("file_ref") or r2.json().get("id")
        if new_ref and not new_ref.startswith("file:"):
            new_ref = f"file:{new_ref}"
        r3 = s.patch(f"{API}/product-documents/{d['id']}",
                     json={"file_ref": new_ref, "visibility": "client"})
        assert r3.status_code == 200, r3.text
        assert r3.json()["version"] == 2
        assert len(r3.json()["history"]) == 1
    # list filtered by product
    r = s.get(f"{API}/product-documents", params={"product_id": eq_id})
    assert r.status_code == 200
    assert any(x["id"] == d["id"] for x in r.json())


def test_event_requirements_compute():
    s = sess("admin")
    # make a tiny event with 3 micros for 1 day
    cid = _mk_client(s)
    r = s.post(f"{API}/events", json={
        "title": f"{PREFIX}EV {RUN}", "type": "Mariage", "client_id": cid,
        "client_contact_ids": [cid], "signatory_contact_id": cid,
        "start": "2027-08-01T18:00", "end": "2027-08-02T02:00",
        "guests": 50, "modules": ["dj"],
    })
    assert r.status_code == 200, r.text
    ev = r.json()
    _created["events"].append(ev["id"])
    # attach 3 micros
    r = s.patch(f"{API}/events/{ev['id']}", json={
        "equipment": [{"equipment_id": pytest.mat_eq_id, "qty": 3}],
    })
    assert r.status_code == 200, r.text
    # compute requirements
    r = s.get(f"{API}/events/{ev['id']}/requirements")
    assert r.status_code == 200, r.text
    comp = r.json()
    piles_line = next((l for l in comp["lines"] if l["label"] == "Piles AA"), None)
    assert piles_line is not None, comp["lines"]
    # 2 per_unit_day * 3 units * 1 day * (1 + 100% spare) = 12
    assert piles_line["computed_qty"] == 12, piles_line
    # adjust quantity
    r = s.patch(f"{API}/events/{ev['id']}/requirements",
                json={"key": piles_line["key"], "adjusted_qty": 15})
    assert r.status_code == 200
    adj = next(l for l in r.json()["lines"] if l["key"] == piles_line["key"])
    assert adj["status"] == "adjusted" and adj["qty"] == 15
