"""Iter 34 — nomenclatures et calculateur de scène (lot 1). QA uniquement, données TEST_M34 créées puis supprimées."""
import os
import subprocess
import sys
import uuid

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
from pymongo import MongoClient  # noqa: E402

API = "http://localhost:8001/api"
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
RUN = uuid.uuid4().hex[:6]
SYS = f"T{RUN}"
S = {"ids": []}


@pytest.fixture(scope="module")
def s():
    x = requests.Session()
    x.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", "admin"], text=True).strip().splitlines()[-1]
    return x


def eq(s, name, qty, **attrs):
    r = s.post(f"{API}/equipment", json={"ref": f"TEST_M34_{RUN}_{name}", "name": f"TEST_M34 {name}", "qty_total": qty, "price_day": 1, "category": "Scène & piste"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    S["ids"].append(pid)
    r = s.put(f"{API}/equipment/{pid}/attributes", json={"attributes": {"systeme": SYS, **attrs}})
    assert r.status_code == 200 and r.json()["attributes"]["role"] == attrs["role"], r.text
    return pid


@pytest.fixture(scope="module", autouse=True)
def data(s):
    S["p21"] = eq(s, "Praticable 2x1", 30, role="praticable", longueur_m=2, largeur_m=1)
    S["p11"] = eq(s, "Praticable 1x1", 20, role="praticable", longueur_m=1, largeur_m=1)
    S["pied60"] = eq(s, "Pied 60", 200, role="pied", hauteur_fixe_cm=60)
    S["pied120"] = eq(s, "Pied 120", 200, role="pied", hauteur_fixe_cm=120)
    S["moq2"] = eq(s, "Moquette noire 2 m", 100, role="moquette", largeur_rouleau_m=2, couleur="noir")
    S["moq4"] = eq(s, "Moquette noire 4 m", 100, role="moquette", largeur_rouleau_m=4, couleur="noir")
    S["scotch"] = eq(s, "Scotch", 10, role="scotch")
    S["clamp"] = eq(s, "Clamp", 300, role="clamp")
    S["jupe"] = eq(s, "Jupe", 50, role="jupe")
    S["dalle"] = eq(s, "Dalle piste", 40, role=f"dalle_{RUN}", longueur_m=1, largeur_m=1)
    r = s.post(f"{API}/events", json={"title": f"TEST_M34 {RUN}", "start": "2030-03-04T18:00", "end": "2030-03-05T02:00"})
    assert r.status_code == 200, r.text
    S["ev"] = r.json()["id"]
    yield
    for c in ("shortages", "tasks"):
        DB[c].delete_many({"org_id": QA, "event_id": S["ev"]})
    DB.events.delete_many({"org_id": QA, "id": S["ev"]})
    DB.kits.delete_many({"org_id": QA, "name": {"$regex": f"^TEST_M34 {RUN}"}})
    for c in ("stock_levels", "stock_movements"):
        DB[c].delete_many({"org_id": QA, "product_id": {"$in": S["ids"]}})
    DB.equipment.delete_many({"org_id": QA, "id": {"$in": S["ids"]}})


BASE = {"systeme": SYS, "ouverture": 10, "profondeur": 5, "hauteur": 60}


def calc(s, **params):
    r = s.post(f"{API}/events/{S['ev']}/kits/compute", json={"kit_id": params.pop("kit_id", "scene"), "params": {**BASE, **params}})
    assert r.status_code == 200, r.text
    return r.json(), {l["product_id"]: l for l in r.json()["lines"]}


def casse(s, pid, qty):
    wid = DB.warehouses.find_one({"org_id": QA, "is_default": True})["id"]
    assert s.post(f"{API}/stock/movements", json={"type": "casse", "product_id": pid, "warehouse_id": wid, "qty": qty}).status_code == 200


def test_formula_engine(s):
    from routes_kits import FormulaError, evaluate
    assert evaluate("ceil((30 + 20) * 1.1 / 25)", {}) == 3
    assert evaluate("if(terrain, n, ceil(n * 0.1))", {"terrain": False, "n": 100}) == 10
    assert evaluate("moquette == oui and h >= 40", {"moquette": True, "h": 60}) is True
    assert evaluate("min(3, max(1, 2)) + round(2.6)", {}) == 5
    for bad in ("__import__('os').system('ls')", "a.b", "inconnue + 1", "1 +", "(lambda: 1)()", "1 / 0"):
        with pytest.raises(FormulaError):
            evaluate(bad, {"a": 1})
    assert s.post(f"{API}/kits/test-formula", json={"formula": "x * 2", "variables": {"x": 4}}).json() == {"ok": True, "result": 8}
    assert "Variable inconnue" in s.post(f"{API}/kits/test-formula", json={"formula": "y * 2"}).json()["error"]


def test_scene_10x5(s):
    d, L = calc(s, moquette=True, jupe=True)
    assert L[S["p21"]]["qty"] == 25 and L[S["pied60"]]["qty"] == 100 and S["p11"] not in L
    pcs = d["layout"]["pieces"]
    assert len(pcs) == 25 and len({p["x"] for p in pcs}) == 5 and len({p["y"] for p in pcs}) == 5 and not any(p["missing"] for p in pcs)
    c = d["layout"]["carpet"]
    assert (c["largeur"], c["sens"], c["les"], c["longueur_le"], c["ml"], c["m2"], c["chute"]) == (2, "profondeur", 5, 5.2, 26, 52, 2)
    assert L[S["moq2"]]["qty"] == 26 and L[S["scotch"]]["qty"] == 3 and L[S["jupe"]]["qty"] == 20
    assert d["vars"]["perimetre"] == 30 and d["vars"]["joints_moquette"] == 20 and "moquette noir" in d["label"]


def test_surface_only_proposals(s):
    r = s.post(f"{API}/events/{S['ev']}/kits/compute", json={"params": {"systeme": SYS, "surface_cible": 50, "hauteur": 60}}).json()
    assert len(r["proposals"]) == 3 and (r["proposals"][0]["ouverture"], r["proposals"][0]["profondeur"]) == (10, 5)


def test_mixed_formats_then_legs(s):
    casse(s, S["p21"], 10)
    d, L = calc(s)
    assert L[S["p21"]]["qty"] == 20 and L[S["p11"]]["qty"] == 10 and not any(l["missing"] for l in L.values())
    casse(s, S["pied60"], 140)
    d, L = calc(s)
    assert d["vars"]["nb_pieds"] == 120 and L[S["pied60"]]["qty"] == 120 and L[S["pied60"]]["missing"] == 60
    S["tele"] = eq(s, "Pied télescopique 60-100", 70, role="pied_telescopique", hauteur_min_cm=60, hauteur_max_cm=100)
    d, L = calc(s)
    assert L[S["pied60"]]["qty"] == 60 and L[S["tele"]]["qty"] == 60 and not L[S["pied60"]]["missing"]


def test_apply_adjust_recompute_delete(s):
    r = s.post(f"{API}/events/{S['ev']}/kits", json={"kit_id": "scene", "params": BASE})
    assert r.status_code == 200, r.text
    iid = r.json()["id"]
    ev = DB.events.find_one({"id": S["ev"]})
    assert {"equipment_id": S["p21"], "qty": 20} in ev["auto_equipment"] and ev["equipment"] == []
    r = s.patch(f"{API}/events/{S['ev']}/kits/{iid}", json={"product_id": S["clamp"], "adjusted_qty": 99})
    assert next(l for l in r.json()["lines"] if l["product_id"] == S["clamp"])["qty"] == 99
    assert s.post(f"{API}/events/{S['ev']}/status", json={"status": "confirme"}).status_code == 200
    r = s.patch(f"{API}/events/{S['ev']}/kits/{iid}", json={"params": {"hauteur": 120}}).json()
    L = {l["product_id"]: l for l in r["lines"]}
    assert L[S["pied120"]]["qty"] == 120 and S["pied60"] not in L and S["tele"] not in L and L[S["clamp"]]["qty"] == 99
    assert any("Garde-corps" in a for a in r["alerts"])
    o = s.get(f"{API}/events/{S['ev']}/origin").json()
    assert any(l["equipment_id"] == S["pied120"] and l["auto"] for g in o["groups"] for l in g["lines"])
    assert s.get(f"{API}/events/{S['ev']}/kits/{iid}/plan").content.startswith(b"%PDF")
    r = s.patch(f"{API}/events/{S['ev']}/kits/{iid}", json={"params": {"ouverture": 20, "profondeur": 10}}).json()
    assert any(p["missing"] for p in r["layout"]["pieces"])
    sh = {x["product_id"]: x for x in s.get(f"{API}/events/{S['ev']}/shortages").json()["lines"] if x["status"] != "resolu"}
    assert S["p21"] in sh and "nomenclature" in sh[S["p21"]]["origin"].lower()
    assert s.delete(f"{API}/events/{S['ev']}/kits/{iid}").status_code == 200
    assert DB.events.find_one({"id": S["ev"]})["auto_equipment"] == []


def test_custom_kit_without_code_and_bad_formula(s):
    r = s.put(f"{API}/kits/new", json={"name": f"TEST_M34 {RUN} Piste de danse", "tile_role": f"dalle_{RUN}", "use_legs": False,
                                       "lines": [{"role": "scotch", "label": "Scotch", "qty": "ceil(perimetre / 25)"}, {"role": "clamp", "label": "Cassé", "qty": "nimporte * 2"}]})
    assert r.status_code == 200, r.text
    d, L = calc(s, kit_id=r.json()["id"], ouverture=4, profondeur=3, hauteur=0)
    assert L[S["dalle"]]["qty"] == 12 and L[S["scotch"]]["qty"] == 1 and any("Variable inconnue" in e for e in d["errors"])
    real = DB.orgs.find_one({"slug": "exclusivity-events"})["id"]
    assert DB.kits.count_documents({"org_id": real}) == 0
