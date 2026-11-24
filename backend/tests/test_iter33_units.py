"""Iter 33 — unités de mesure et caractéristiques par produit. QA uniquement, données TEST_M33 créées puis supprimées."""
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
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip().splitlines()[-1]
    return s


@pytest.fixture(scope="module")
def s():
    return sess()


@pytest.fixture(scope="module", autouse=True)
def data(s):
    def eq(name, qty, **kw):
        r = s.post(f"{API}/equipment", json={"ref": f"TEST_M33_{RUN}_{name}", "name": f"TEST_M33 {name}", "qty_total": qty, "price_day": 25, **kw})
        assert r.status_code == 200, r.text
        return r.json()["id"]
    S["gui"] = eq("Guirlande 10 m", 8, category="Lumière", subcategory="Guirlandes & ciels lumineux")
    S["coton"] = eq("Coton gratté", 120, category="Textile & linge")
    S["table"] = eq("Table ovale 26", 2, category="Mobilier", subcategory="Tables")
    S["raccord"] = eq("Raccord", 50)
    for k in ("ev", "ev2"):
        r = s.post(f"{API}/events", json={"title": f"TEST_M33 {RUN} {k}", "start": "2029-09-04T18:00", "end": "2029-09-05T02:00"})
        assert r.status_code == 200, r.text
        S[k] = r.json()["id"]
    yield
    evs, ids = [S[k] for k in ("ev", "ev2") if k in S], [S[k] for k in ("gui", "coton", "table", "raccord") if k in S]
    for c in ("quotes", "shortages", "tasks"):
        DB[c].delete_many({"org_id": QA, "event_id": {"$in": evs}})
    DB.events.delete_many({"org_id": QA, "id": {"$in": evs}})
    DB.attribute_templates.delete_many({"org_id": QA, "id": "guirlandes"})
    for c in ("stock_levels", "stock_movements"):
        DB[c].delete_many({"org_id": QA, "product_id": {"$in": ids}})
    DB.equipment.delete_many({"org_id": QA, "id": {"$in": ids}})


def item(s, pid, **params):
    return next(i for i in s.get(f"{API}/equipment", params=params).json()["items"] if i["id"] == pid)


PERIOD = {"start": "2029-09-04T12:00", "end": "2029-09-05T12:00"}


def test_units_on_product(s):
    assert s.put(f"{API}/equipment/{S['gui']}/units", json={"secondary_uom": "m"}).status_code == 400
    r = s.put(f"{API}/equipment/{S['gui']}/units", json={"secondary_uom": "m", "qty_per_piece": 10, "quote_uom": "secondary", "price_per_secondary": 2.5})
    assert r.status_code == 200, r.text
    g = item(s, S["gui"])
    assert g["qty_total"] == 8 and g["secondary_uom"] == "m" and g["qty_per_piece"] == 10 and g["price_day"] == 25 and g["price_per_secondary"] == 2.5
    assert sess("technicien").put(f"{API}/equipment/{S['gui']}/units", json={}).status_code in (403, 404)
    assert "m²" in s.get(f"{API}/uoms").json()["stock_uoms"]


def test_45m_reserves_5_pieces_and_90m_misses_one(s):
    r = s.put(f"{API}/equipment/{S['gui']}/requirements", json={"requirements": [{"type": "accessoire_obligatoire", "label": "Raccord", "linked_product_id": S["raccord"], "quantity": 0.1, "calc_mode": "per_secondary"}]})
    assert r.status_code == 200, r.text
    r = s.patch(f"{API}/events/{S['ev']}", json={"equipment": [{"equipment_id": S["gui"], "qty": 1, "entered_qty": 45, "entered_uom": "secondary"}]})
    assert r.status_code == 200, r.text
    l = r.json()["equipment"][0]
    assert l["qty"] == 5 and l["entered_qty"] == 45
    assert s.post(f"{API}/events/{S['ev']}/status", json={"status": "confirme"}).status_code == 200
    g = item(s, S["gui"], **PERIOD)
    assert g["reserved"] == 5 and g["available"] == 3
    L = {x["label"]: x for x in s.get(f"{API}/events/{S['ev']}/requirements").json()["lines"]}
    assert L["Raccord"]["qty"] == 5
    import pymupdf
    pdf = s.get(f"{API}/events/{S['ev']}/requirements/checklist").content
    text = " ".join("".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf")).split())
    assert "Guirlande 10 m 5" in text
    s.patch(f"{API}/events/{S['ev']}", json={"equipment": [{"equipment_id": S["gui"], "qty": 1, "entered_qty": 90, "entered_uom": "secondary"}]})
    d = s.get(f"{API}/events/{S['ev']}/shortages").json()
    x = next(x for x in d["lines"] if x["product_id"] == S["gui"])
    assert x["missing"] == 1 and x["missing_secondary"] == 10 and x["secondary_uom"] == "m" and "(10 m)" in d["summary"]
    s.patch(f"{API}/events/{S['ev']}", json={"equipment": []})


def test_fabric_in_metres_exact(s):
    assert s.patch(f"{API}/events/{S['ev']}", json={"equipment": [{"equipment_id": S["table"], "qty": 1.5}]}).status_code == 400
    assert s.put(f"{API}/equipment/{S['coton']}/units", json={"stock_uom": "m", "rounding": "exact"}).status_code == 200
    r = s.patch(f"{API}/events/{S['ev']}", json={"equipment": [{"equipment_id": S["coton"], "qty": 37.5}]})
    assert r.status_code == 200 and r.json()["equipment"][0]["qty"] == 37.5, r.text
    c = item(s, S["coton"], **PERIOD)
    assert c["reserved"] == 37.5 and c["available"] == 82.5
    o = s.get(f"{API}/events/{S['ev']}/origin").json()
    assert sum(l["qty"] for g in o["groups"] for l in g["lines"] if l["equipment_id"] == S["coton"]) == 37.5
    wid = DB.warehouses.find_one({"org_id": QA, "is_default": True})["id"]
    assert s.post(f"{API}/stock/movements", json={"type": "entree", "product_id": S["coton"], "warehouse_id": wid, "qty": 2.5}).status_code == 200
    assert item(s, S["coton"])["qty_total"] == 122.5
    assert s.post(f"{API}/stock/movements", json={"type": "entree", "product_id": S["table"], "warehouse_id": wid, "qty": 0.5}).status_code == 400


def test_quote_in_secondary_unit(s):
    r = s.post(f"{API}/quotes/direct", json={"event_id": S["ev2"], "lines": [{"label": "Guirlande guinguette", "qty": 45, "unit_price": 2.5, "vat": 20, "equipment_id": S["gui"], "uom": "secondary", "unit": "m"}]})
    assert r.status_code == 200, r.text
    qid = r.json()["id"]
    assert r.json()["lines"][0]["uom"] == "secondary" and r.json()["total_ht"] == 112.5
    import pymupdf
    pdf = s.get(f"{API}/quotes/{qid}/pdf").content
    text = " ".join("".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf")).split())
    assert "45 m" in text
    L = {x["label"]: x for x in s.get(f"{API}/quotes/{qid}/requirements").json()["lines"]}
    assert L["Raccord"]["source_qty"] == 5
    r = s.post(f"{API}/quotes/{qid}/status", json={"status": "accepte"})
    assert r.status_code == 200, r.text
    l = DB.events.find_one({"id": S["ev2"]})["equipment"][0]
    assert l["qty"] == 5 and l["entered_qty"] == 45 and l["price_day"] == 22.5


def test_attributes_and_templates(s):
    t = {x["id"]: x for x in s.get(f"{API}/attribute-templates").json()}
    assert not t["tables"]["custom"] and any(f["code"] == "places_assises" for f in t["tables"]["fields"])
    r = s.put(f"{API}/equipment/{S['table']}/attributes", json={"attributes": {"places_assises": "26", "matiere": "Bois", "inconnu": "x"}, "extra_attributes": [{"label": "Pieds", "value": "pliants"}]})
    assert r.status_code == 200 and r.json()["attributes"] == {"places_assises": 26, "matiere": "Bois"} and r.json()["extra_attributes"][0]["label"] == "Pieds", r.text
    assert s.put(f"{API}/equipment/{S['table']}/attributes", json={"attributes": {"places_assises": "beaucoup"}}).status_code == 400
    assert item(s, S["table"])["attributes"]["places_assises"] == 26
    g = t["guirlandes"]
    r = s.put(f"{API}/attribute-templates/guirlandes", json={"name": g["name"], "scopes": g["scopes"], "fields": g["fields"] + [{"label": "Type de douille", "type": "text"}]})
    assert r.status_code == 200, r.text
    g2 = next(x for x in r.json() if x["id"] == "guirlandes")
    assert g2["custom"] and g2["fields"][-1]["code"] == "type_de_douille"
    real = DB.orgs.find_one({"slug": "exclusivity-events"})["id"]
    assert DB.attribute_templates.count_documents({"org_id": real}) == 0
    assert s.put(f"{API}/equipment/{S['gui']}/attributes", json={"attributes": {"type_de_douille": "E27", "puissance_w": 60}}).json()["attributes"] == {"type_de_douille": "E27", "puissance_w": 60}
    back = s.delete(f"{API}/attribute-templates/guirlandes").json()
    assert not next(x for x in back if x["id"] == "guirlandes")["custom"]


def test_import_accepts_unit_columns():
    import sys
    sys.path.insert(0, "/app/backend")
    from catalogue_import import normalize
    doc, stock, why = normalize({"ref": "X", "name": "Coton", "type": "Location", "stock_main": 120.5, "unite_stock": "m", "arrondi": "exact", "carac:couleur": "noir"})
    assert not why and stock == 120.5 and doc["stock_uom"] == "m" and doc["rounding"] == "exact" and doc["attributes"] == {"couleur": "noir"}
    assert normalize({"ref": "Y", "name": "Table", "type": "Location", "stock_main": 6.57})[1] == 6


def test_logistics_and_transfers_accept_measured_products(s):
    wid = DB.warehouses.find_one({"org_id": QA, "is_default": True})["id"]
    other = DB.warehouses.find_one({"org_id": QA, "id": {"$ne": wid}, "active": {"$ne": False}})
    if other:
        r = s.post(f"{API}/stock/transfers", json={"product_id": S["coton"], "qty": 2.5, "from_warehouse_id": wid, "to_warehouse_id": other["id"]})
        assert r.status_code == 200, r.text
        assert s.post(f"{API}/stock/transfers", json={"product_id": S["table"], "qty": 0.5, "from_warehouse_id": wid, "to_warehouse_id": other["id"]}).status_code == 400
        assert s.post(f"{API}/stock/transfers", json={"product_id": S["coton"], "qty": 2.5, "from_warehouse_id": other["id"], "to_warehouse_id": wid}).status_code == 200
    r = s.post(f"{API}/stock/availability", json={"date": "2029-10-01", "lines": [{"equipment_id": S["gui"], "qty": 45, "uom": "secondary"}]})
    assert r.status_code == 200 and r.json()["rows"][0]["qty"] == 5, r.text
    ms = s.get(f"{API}/events/{S['ev']}/logistics").json()
    items = [i for m in (ms if isinstance(ms, list) else ms.get("missions", [])) for i in m.get("items", []) if i["product_id"] == S["coton"]]
    assert not items or sum(i["qty"] for i in items if i.get("mv_id") is not None) > 0
