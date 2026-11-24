"""Iter 39 — Finance étape 3 : prévisionnel. QA uniquement, versions TEST_M39 supprimées à la fin."""
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
kp = lambda d: {k["key"]: k["value"] for k in d["results"]["kpis"]}  # noqa: E731
tb = lambda d, key: {r[0]: r[1:] for r in next(t for t in d["results"]["tables"] if t["key"] == key)["rows"]}  # noqa: E731


def sess(role="admin"):
    x = requests.Session()
    x.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip().splitlines()[-1]
    return x


@pytest.fixture(scope="module")
def s():
    x = sess()
    saved = list(DB.budgets.find({"org_id": QA, "year": 2027}))
    yield x
    DB.forecast_versions.delete_many({"org_id": QA, "name": {"$regex": f"^TEST_M39 {RUN}"}})
    DB.budgets.delete_many({"org_id": QA, "year": 2027})
    if saved:
        DB.budgets.insert_many(saved)


def test_reference_case_and_truck(s):
    v = s.post(f"{API}/finance/forecasts", json={"name": f"TEST_M39 {RUN} réaliste", "start_year": 2027, "mode": "blank"}).json()
    S["id"] = vid = v["id"]
    a = {**v["assumptions"], "staff_source": "manual", "activities": [{"name": "Mobilier", "events_per_year": 60, "basket_ht": 2500, "variable_cost_pct": 35}, {"name": "DJ", "events_per_year": 40, "basket_ht": 1400, "variable_cost_pct": 45}],
         "fixed": [{"label": "Structure", "monthly": 8000}]}
    S["a"] = a
    d = s.put(f"{API}/finance/forecasts/{vid}", json={"name": v["name"], "assumptions": a})
    assert d.status_code == 200, d.text
    d = d.json()
    assert kp(d)["ca"] == 206000 and kp(d)["gross"] == 128300 and kp(d)["ebe"] == 32300
    low0 = kp(d)["low"]
    a2 = {**a, "investments": [{"label": "Camion", "amount_ht": 25000, "date": "2027-03", "amort_years": 5, "vat_pct": 20}], "loans": [{"label": "Prêt camion", "amount": 20000, "date": "2027-03", "rate_pct": 4, "months": 48}]}
    d = s.put(f"{API}/finance/forecasts/{vid}", json={"name": v["name"], "assumptions": a2}).json()
    pnl, fp = tb(d, "pnl"), tb(d, "financing")
    assert next(t for t in d["results"]["tables"] if t["key"] == "invest")["rows"][0][4] == 451.58
    assert pnl["Dotations aux amortissements"][0] == round(25000 / 60 * 10, 2) and 550 < pnl["Charges financières"][0] < 620
    assert fp["Investissements HT"][0] == 25000 and fp["Emprunts"][0] == 20000 and kp(d)["low"] != low0
    assert tb(d, "balance")["Total actif"] == tb(d, "balance")["Total passif"]
    less = s.get(f"{API}/finance/forecasts/{vid}", params={"events_pct": -20}).json()
    assert kp(less)["ca"] == 164800 and kp(less)["net"] < kp(d)["net"] and kp(less)["low"] < kp(d)["low"]
    assert d["signed_share"]["pct"] is not None


def test_prefill_duplicate_compare_freeze_export(s):
    vid = S["id"]
    p = s.post(f"{API}/finance/forecasts", json={"name": f"TEST_M39 {RUN} données", "start_year": 2027, "mode": "data"})
    assert p.status_code == 200 and "activities" in p.json()["assumptions"]
    dup = s.post(f"{API}/finance/forecasts", json={"name": f"TEST_M39 {RUN} prudent", "start_year": 2027, "mode": "duplicate", "source_id": vid}).json()
    assert dup["parent_version_id"] == vid
    c = s.get(f"{API}/finance/forecasts/compare", params={"ids": f"{vid},{dup['id']}"}).json()["tables"][0]
    assert len(c["columns"]) == 3 and c["rows"][0][1] == c["rows"][0][2] == 206000
    for f in ("pdf", "xlsx"):
        r = s.get(f"{API}/finance/forecasts/{vid}/export", params={"format": f})
        assert r.status_code == 200 and len(r.content) > 3000
        open(f"/tmp/dossier.{f}", "wb").write(r.content)
    c = sess("comptable")
    assert c.get(f"{API}/finance/forecasts/{vid}").status_code == 200 and c.post(f"{API}/finance/forecasts/{vid}/freeze").status_code == 403
    for role in ("commercial", "technicien"):
        assert sess(role).get(f"{API}/finance/forecasts").status_code == 403
    fz = s.post(f"{API}/finance/forecasts/{vid}/freeze").json()
    assert fz["version"]["status"] == "frozen" and any(t["key"] == "follow" for t in fz["results"]["tables"])
    assert s.put(f"{API}/finance/forecasts/{vid}", json={"name": "x", "assumptions": S["a"]}).status_code == 409
    assert round(sum(b["amount"] for b in DB.budgets.find({"org_id": QA, "year": 2027, "line_kind": "ca"}))) == 206000
    assert DB.audit_logs.find_one({"org_id": QA, "action": "forecast_frozen"})
    assert s.put(f"{API}/finance/forecasts/{dup['id']}", json={"name": dup["name"], "assumptions": {"activities": [{"events_per_year": "abc"}]}}).status_code == 400
