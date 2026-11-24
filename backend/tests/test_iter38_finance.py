"""Iter 38 — Finance étape 1 : accès, réglages, engagements, finances d'un événement. QA uniquement."""
import os
import subprocess
import uuid

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

API = "http://localhost:8001/api"
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
RUN = uuid.uuid4().hex[:6]
S = {}


def sess(role="admin"):
    x = requests.Session()
    x.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip().splitlines()[-1]
    return x


@pytest.fixture(scope="module")
def s():
    x = sess()
    yield x
    evs = [e["id"] for e in DB.events.find({"org_id": QA, "title": f"TEST_M38 {RUN}"})]
    for c in ("commitments", "quotes", "missions"):
        DB[c].delete_many({"org_id": QA, "event_id": {"$in": evs}})
    DB.events.delete_many({"org_id": QA, "id": {"$in": evs}})


def test_access(s):
    assert s.get(f"{API}/finance/settings").status_code == 200
    for role in ("commercial", "technicien", "chef_projet"):
        assert sess(role).get(f"{API}/finance/settings").status_code == 403, role
    assert requests.get(f"{API}/finance/settings").status_code == 401
    me = s.get(f"{API}/me").json()
    assert "pilot:view" in me["perms"] and "pilot:view" not in sess("commercial").get(f"{API}/me").json()["perms"]
    c = sess("comptable")
    assert c.get(f"{API}/finance/settings").status_code == 200
    assert c.put(f"{API}/finance/settings", json={"activities": [{"name": "x"}], "channels": [{"name": "y"}]}).status_code == 403


def test_retained_provider_creates_commitment_and_mixed_event_split(s):
    r = s.post(f"{API}/events", json={"title": f"TEST_M38 {RUN}", "start": "2031-06-14T16:00", "end": "2031-06-15T02:00"})
    S["ev"] = eid = r.json()["id"]
    mid = str(uuid.uuid4())
    DB.missions.insert_one({"id": mid, "org_id": QA, "event_id": eid, "provider_id": "x", "provider_name": "TEST_M38 Sax", "category_key": "saxophoniste", "date": "2031-06-14", "total_ht": 450, "total_ttc": 450, "status": "confirmed"})
    DB.quotes.insert_one({"id": str(uuid.uuid4()), "org_id": QA, "event_id": eid, "number": "TEST_M38", "status": "accepte", "created_at": "2030-01-01", "total_ht": 4000, "total_ttc": 4800,
                          "lines": [{"label": "Prestation DJ soirée", "qty": 1, "unit_price": 1500}, {"label": "Location chaises et tables", "qty": 1, "unit_price": 2500}]})
    f = s.get(f"{API}/events/{eid}/finance").json()
    assert [(c["amount_ht"], c["source"], c["due_date"]) for c in f["commitments"]] == [(450, "mission", "2031-07-14")]
    assert f["by_activity"] == {"dj_sax": 1500, "mobilier": 2500} and f["revenue"]["quoted_ht"] == 4000 and f["signed"]
    assert f["charges"]["planned"] == 450 and f["margin_planned"] == 3550 and f["margin_planned_pct"] == 88.8 and not f["alert"]
    assert len(s.get(f"{API}/events/{eid}/finance").json()["commitments"]) == 1
    f = s.post(f"{API}/events/{eid}/finance/commitments", json={"label": "Camion", "category": "transport", "amount_ht": 3000}).json()
    assert f["alert"] and f["margin_planned_pct"] == 13.8
    cid = next(c["id"] for c in f["commitments"] if c["source"] == "manual")
    f = s.put(f"{API}/events/{eid}/finance/commitments/{cid}", json={"status": "facture", "actual_ht": 3300}).json()
    c = next(c for c in f["commitments"] if c["id"] == cid)
    assert c["actual_ht"] == 3300 and c["history"][0]["gap"] == 300 and f["charges"]["invoiced"] == 3300


def test_costs_never_sent_without_right(s):
    c = sess("commercial").get(f"{API}/events/{S['ev']}/finance")
    assert c.status_code == 200 and "commitments" not in c.json() and "margin_planned" not in c.json() and "charges" not in c.json()
    assert sess("commercial").post(f"{API}/events/{S['ev']}/finance/commitments", json={"label": "x", "amount_ht": 1}).status_code == 403
    assert sess("technicien").get(f"{API}/events/{S['ev']}/finance").status_code == 403


def _signed(eid, ht, status="accepte", n=0):
    DB.quotes.insert_one({"id": str(uuid.uuid4()), "org_id": QA, "event_id": eid, "number": f"TEST_M38-{n}", "status": status, "created_at": "2030-01-01T00:00:00", "date": "2030-01-01", "total_ht": ht, "total_ttc": ht * 1.2,
                          "lines": [{"label": "Location chaises", "qty": 1, "unit_price": ht}]})


def test_dashboard_backlog_pipeline_breakeven(s):
    kp = lambda d: {k["key"]: k["value"] for k in d["kpis"]}  # noqa: E731
    before = s.get(f"{API}/finance/report/dashboard").json()
    for i, ht in enumerate((4000, 6500, 2500)):
        eid = s.post(f"{API}/events", json={"title": f"TEST_M38 {RUN}", "start": "2033-06-1%dT16:00" % i, "end": "2033-06-1%dT23:00" % i}).json()["id"]
        _signed(eid, ht, n=i)
    eid = s.post(f"{API}/events", json={"title": f"TEST_M38 {RUN}", "start": "2033-06-20T16:00", "end": "2033-06-20T23:00"}).json()["id"]
    _signed(eid, 5000, "envoye", 9)
    oid = str(uuid.uuid4())
    DB.opportunities.insert_one({"id": oid, "org_id": QA, "event_id": eid, "title": f"TEST_M38 {RUN}", "probability": 40, "source_key": "instagram", "stage_key": "devis_envoye"})
    cur = DB.finance_settings.find_one({"org_id": QA})
    try:
        cfg = s.get(f"{API}/finance/settings").json()
        assert s.put(f"{API}/finance/settings", json={"activities": cfg["activities"], "channels": cfg["channels"], "fixed_costs_monthly": 8000, "variable_margin_rate": 50}).status_code == 200
        d = s.get(f"{API}/finance/report/dashboard").json()
        assert dict(next(t for t in d["tables"] if t["key"] == "backlog")["rows"])["2033-06"] == 13000
        assert round(kp(d)["pipeline"] - kp(before)["pipeline"], 2) == 2000 and kp(d)["breakeven"] == 16000
        a = s.get(f"{API}/finance/report/activite", params={"start": "2033-01-01", "end": "2033-12-31"}).json()
        assert kp(a)["ca"] == 13000 and kp(a)["events"] == 3 and next(t for t in a["tables"] if t["key"] == "by_activity")["rows"][0][:2] == ["Location de mobilier", 13000]
        m = s.get(f"{API}/finance/report/marges", params={"start": "2033-01-01", "end": "2033-12-31"}).json()
        assert kp(m)["ca"] == 13000 and len(next(t for t in m["tables"] if t["key"] == "events")["rows"]) == 3
        for f in ("xlsx", "pdf"):
            r = s.get(f"{API}/finance/export/marges", params={"format": f, "start": "2033-01-01", "end": "2033-12-31"})
            assert r.status_code == 200 and len(r.content) > 1500
        assert sess("commercial").get(f"{API}/finance/report/marges").status_code == 403
    finally:
        DB.opportunities.delete_one({"org_id": QA, "id": oid})
        DB.finance_settings.delete_one({"org_id": QA}) if not cur else DB.finance_settings.replace_one({"org_id": QA}, cur)
