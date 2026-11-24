"""Review iter M38UI — Finance & pilotage : parcours API. Seed TEST_M38UI pré-chargé."""
import os
import subprocess

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]


def tok(role):
    return subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip().splitlines()[-1]


@pytest.fixture(scope="module")
def admin():
    s = requests.Session(); s.headers["Authorization"] = "Bearer " + tok("admin"); return s


@pytest.fixture(scope="module")
def commercial():
    s = requests.Session(); s.headers["Authorization"] = "Bearer " + tok("commercial"); return s


@pytest.fixture(scope="module")
def comptable():
    s = requests.Session(); s.headers["Authorization"] = "Bearer " + tok("comptable"); return s


@pytest.fixture(scope="module")
def technicien():
    s = requests.Session(); s.headers["Authorization"] = "Bearer " + tok("technicien"); return s


# -- Access matrix ---------------------------------------------------------
def test_finance_settings_access(admin, commercial, comptable, technicien):
    assert admin.get(f"{BASE}/api/finance/settings").status_code == 200
    j = admin.get(f"{BASE}/api/finance/settings").json()
    assert j.get("pennylane") is False
    assert j.get("can_manage") is True
    # commercial & technicien = 403
    assert commercial.get(f"{BASE}/api/finance/settings").status_code == 403
    assert technicien.get(f"{BASE}/api/finance/settings").status_code == 403
    # comptable = 200 mais can_manage False
    r = comptable.get(f"{BASE}/api/finance/settings")
    assert r.status_code == 200
    assert r.json().get("can_manage") is False


def test_dashboard_access(admin, commercial, technicien, comptable):
    assert admin.get(f"{BASE}/api/finance/report/dashboard").status_code == 200
    assert commercial.get(f"{BASE}/api/finance/report/dashboard").status_code == 403
    assert technicien.get(f"{BASE}/api/finance/report/dashboard").status_code == 403
    assert comptable.get(f"{BASE}/api/finance/report/dashboard").status_code == 200


def test_forecasts_access(admin, commercial, technicien, comptable):
    assert admin.get(f"{BASE}/api/finance/forecasts").status_code == 200
    assert commercial.get(f"{BASE}/api/finance/forecasts").status_code == 403
    assert technicien.get(f"{BASE}/api/finance/forecasts").status_code == 403
    assert comptable.get(f"{BASE}/api/finance/forecasts").status_code == 200


def test_settings_write_restrictions(admin, comptable):
    cfg = admin.get(f"{BASE}/api/finance/settings").json()
    payload = {"activities": cfg["activities"], "channels": cfg["channels"]}
    # comptable PUT -> 403
    assert comptable.put(f"{BASE}/api/finance/settings", json=payload).status_code == 403


# -- Event finance filtering ------------------------------------------------
def _mixed_event_id():
    ev = DB.events.find_one({"org_id": QA, "title": "TEST_M38UI 10"})
    return ev["id"] if ev else None


def test_event_finance_commercial_no_costs(admin, commercial):
    eid = _mixed_event_id()
    assert eid
    j = admin.get(f"{BASE}/api/events/{eid}/finance").json()
    assert "charges" in j and "margin_planned" in j and "commitments" in j
    rc = commercial.get(f"{BASE}/api/events/{eid}/finance")
    assert rc.status_code == 200, rc.text
    jc = rc.json()
    for k in ("charges", "margin_planned", "margin_planned_pct", "margin_real", "alert", "threshold", "commitments"):
        assert k not in jc, f"commercial should not see {k}"


# -- Dashboard figures with seed data --------------------------------------
def test_dashboard_backlog_and_pipeline(admin):
    # Set finance settings to get breakeven
    cfg = admin.get(f"{BASE}/api/finance/settings").json()
    admin.put(f"{BASE}/api/finance/settings", json={
        "activities": cfg["activities"], "channels": cfg["channels"],
        "margin_threshold": 30, "provider_payment_days": 30,
        "fixed_costs_monthly": 8000, "variable_margin_rate": 50,
    })
    try:
        d = admin.get(f"{BASE}/api/finance/report/dashboard").json()
        backlog = dict(next(t for t in d["tables"] if t["key"] == "backlog")["rows"])
        assert backlog.get("2033-06") == 13000, backlog
        kp = {k["key"]: k["value"] for k in d["kpis"]}
        assert kp["breakeven"] == 16000
        # pipeline must contain TEST_M38UI 20 with pondéré 2000
        pipe_rows = next(t for t in d["tables"] if t["key"] == "pipeline")["rows"]
        hit = [r for r in pipe_rows if "TEST_M38UI 20" in str(r[0])]
        assert hit, pipe_rows
        assert hit[0][2] == 5000 and hit[0][3] == 40 and hit[0][4] == 2000
    finally:
        DB.finance_settings.delete_many({"org_id": QA})


def test_activity_report_split(admin):
    a = admin.get(f"{BASE}/api/finance/report/activite", params={"start": "2033-01-01", "end": "2033-12-31"}).json()
    kp = {k["key"]: k["value"] for k in a["kpis"]}
    assert kp["ca"] == 13000
    assert kp["events"] == 3
    by_act = next(t for t in a["tables"] if t["key"] == "by_activity")["rows"]
    d = {r[0]: r[1] for r in by_act}
    # DJ/sax 1500, Mobilier 2500+6500+2500 = 11500
    assert d.get("DJ / sax") == 1500, d
    assert d.get("Location de mobilier") == 11500, d


def test_marges_export(admin):
    m = admin.get(f"{BASE}/api/finance/report/marges", params={"start": "2033-01-01", "end": "2033-12-31"})
    assert m.status_code == 200
    data = m.json()
    assert len(next(t for t in data["tables"] if t["key"] == "events")["rows"]) == 3
    for fmt in ("xlsx", "pdf"):
        r = admin.get(f"{BASE}/api/finance/export/marges", params={"format": fmt, "start": "2033-01-01", "end": "2033-12-31"})
        assert r.status_code == 200 and len(r.content) > 1500


# -- Event finance TEST_M38UI 10 margin & commitment flow ------------------
def test_event_finance_mixed_commitments(admin):
    eid = _mixed_event_id()
    j = admin.get(f"{BASE}/api/events/{eid}/finance").json()
    assert j["revenue"]["quoted_ht"] == 4000
    assert j["signed"] is True
    by = j["by_activity"]
    assert by.get("dj_sax") == 1500 and by.get("mobilier") == 2500
    # Commitment auto-created from mission "TEST_M38UI Sax" 450
    cm = [c for c in j["commitments"] if c["source"] == "mission"]
    assert cm and cm[0]["amount_ht"] == 450
    # Marge prévisionnelle = 4000 - 450 = 3550, 88.75 %
    assert j["margin_planned"] == 3550
    assert j["margin_planned_pct"] == 88.8
    assert j["alert"] is False

    # Add transport 3000 -> total charges 3450, margin 550, 13.75% < 30% -> alert
    r = admin.post(f"{BASE}/api/events/{eid}/finance/commitments", json={
        "kind": "expense", "category": "transport", "label": "TEST_M38UI Transport",
        "amount_ht": 3000, "vat": 0, "due_date": "", "probability": 100,
    })
    assert r.status_code == 200, r.text
    j2 = r.json()
    assert j2["alert"] is True
    assert j2["margin_planned_pct"] is not None and j2["margin_planned_pct"] < 30

    # Move transport commitment to "facture" with actual 3300
    newcm = [c for c in j2["commitments"] if c["label"] == "TEST_M38UI Transport"][0]
    r2 = admin.put(f"{BASE}/api/events/{eid}/finance/commitments/{newcm['id']}", json={
        "status": "facture", "actual_ht": 3300, "invoice_ref": "",
    })
    assert r2.status_code == 200
    updated = [c for c in r2.json()["commitments"] if c["id"] == newcm["id"]][0]
    assert updated["status"] == "facture"
    assert updated["actual_ht"] == 3300

    # Cleanup: remove manual commitments
    DB.commitments.delete_many({"org_id": QA, "event_id": eid, "source": "manual"})


# -- Forecasts : create / save / sensibility / freeze / export / duplicate -
def _mk(session, name, year, mode="blank", source_id=""):
    r = session.post(f"{BASE}/api/finance/forecasts", json={"name": name, "start_year": year, "mode": mode, "source_id": source_id})
    assert r.status_code == 200, r.text
    return r.json()


def test_forecast_full_flow(admin, comptable):
    created = []
    try:
        v = _mk(admin, "TEST_M38UI 2027", 2027, "blank")
        created.append(v["id"])
        payload = {
            "name": "TEST_M38UI 2027", "notes": "", "presentation_text": "",
            "assumptions": {
                "activities": [
                    {"name": "Mobilier", "events_per_year": 60, "basket_ht": 2500, "variable_cost_pct": 35, "growth_y2_pct": 0, "growth_y3_pct": 0, "vat_pct": 20, "start": "", "seasonality": []},
                    {"name": "DJ", "events_per_year": 40, "basket_ht": 1400, "variable_cost_pct": 45, "growth_y2_pct": 0, "growth_y3_pct": 0, "vat_pct": 20, "start": "", "seasonality": []},
                ],
                "fixed": [{"label": "Loyer", "monthly": 8000, "start": "", "end": ""}],
                "staff": [], "investments": [], "loans": [], "contributions": [], "dividends": [],
                "raise_pct": 0, "indexation_pct": 0, "opening_cash": 0,
            },
        }
        r = admin.put(f"{BASE}/api/finance/forecasts/{v['id']}", json=payload)
        assert r.status_code == 200, r.text
        res = r.json()["results"]
        kp = {k["key"]: k["value"] for k in res["kpis"]}
        # CA HT 2027 = 60*2500 + 40*1400 = 150000 + 56000 = 206000
        assert kp["ca"] == 206000
        # Marge brute = 206000 - (150000*0.35 + 56000*0.45) = 206000 - (52500+25200)= 128300
        assert kp["gross"] == 128300
        # EBE = 128300 - 8000*12 = 128300 - 96000 = 32300
        assert kp["ebe"] == 32300

        # Add investment + loan
        payload["assumptions"]["investments"] = [{"label": "Camion", "amount_ht": 25000, "date": "2027-03", "amort_years": 5, "vat_pct": 20}]
        payload["assumptions"]["loans"] = [{"label": "Prêt", "amount": 20000, "date": "2027-03", "rate_pct": 4, "months": 48, "deferral_months": 0}]
        r = admin.put(f"{BASE}/api/finance/forecasts/{v['id']}", json=payload)
        assert r.status_code == 200
        res = r.json()["results"]
        invest = next(t for t in res["tables"] if t["key"] == "invest")["rows"]
        assert invest, invest
        # monthly payment of 20000 at 4%/48m -> ~451.58
        assert abs(invest[0][4] - 451.58) < 1, invest

        # Sensibility events_pct=-20 via query
        r = admin.get(f"{BASE}/api/finance/forecasts/{v['id']}", params={"events_pct": -20})
        kp2 = {k["key"]: k["value"] for k in r.json()["results"]["kpis"]}
        # CA = 206000 * 0.8 = 164800
        assert kp2["ca"] == 164800

        # Duplicate
        v2 = _mk(admin, "TEST_M38UI 2027 bis", 2027, "duplicate", source_id=v["id"])
        created.append(v2["id"])
        # Compare
        rc = admin.get(f"{BASE}/api/finance/forecasts/compare", params={"ids": f"{v['id']},{v2['id']}"})
        assert rc.status_code == 200
        cmp_rows = rc.json()["tables"][0]["rows"]
        assert cmp_rows, cmp_rows

        # Mode "data"
        v3 = _mk(admin, "TEST_M38UI 2027 data", 2027, "data")
        created.append(v3["id"])
        full = admin.get(f"{BASE}/api/finance/forecasts/{v3['id']}").json()
        assert "signed_share" in full
        assert "pct" in full["signed_share"]

        # Freeze v1 (restricted for comptable)
        assert comptable.post(f"{BASE}/api/finance/forecasts/{v['id']}/freeze").status_code == 403
        rf = admin.post(f"{BASE}/api/finance/forecasts/{v['id']}/freeze")
        assert rf.status_code == 200, rf.text
        assert rf.json()["version"]["status"] == "frozen"

        # Frozen => PUT must fail (409)
        r = admin.put(f"{BASE}/api/finance/forecasts/{v['id']}", json=payload)
        assert r.status_code == 409

        # Export frozen (pdf + xlsx)
        for fmt in ("pdf", "xlsx"):
            e = admin.get(f"{BASE}/api/finance/forecasts/{v['id']}/export", params={"format": fmt})
            assert e.status_code == 200 and len(e.content) > 2000

        # Follow table must appear
        got = admin.get(f"{BASE}/api/finance/forecasts/{v['id']}").json()
        tbl_keys = [t["key"] for t in got["results"]["tables"]]
        assert "follow" in tbl_keys
    finally:
        # cleanup forecasts by direct DB (DELETE is blocked for frozen)
        for vid in created:
            DB.forecast_versions.delete_one({"id": vid})
        DB.budgets.delete_many({"org_id": QA, "year": 2027})
