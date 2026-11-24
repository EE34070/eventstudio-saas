"""Iter 36 — fournisseurs multiples par produit. QA uniquement, données TEST_M36 créées puis supprimées."""
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
    cids = [c["id"] for c in DB.contacts.find({"org_id": QA, "company": {"$regex": f"^TEST_M36 {RUN}"}})]
    mids = [m["id"] for m in DB.supplier_product_map.find({"org_id": QA, "supplier_id": {"$in": cids}})]
    DB.supplier_price_history.delete_many({"org_id": QA, "map_id": {"$in": mids}})
    DB.supplier_product_map.delete_many({"org_id": QA, "id": {"$in": mids}})
    DB.purchase_invoices.delete_many({"org_id": QA, "supplier_contact_id": {"$in": cids}})
    DB.equipment.delete_many({"org_id": QA, "ref": f"TEST_M36_{RUN}"})
    DB.contacts.delete_many({"org_id": QA, "id": {"$in": cids}})


def test_two_suppliers_compare_and_prefer(s):
    r = s.post(f"{API}/equipment", json={"ref": f"TEST_M36_{RUN}", "name": "TEST_M36 Moquette", "qty_total": 0, "price_day": 1, "category": "Scène & piste"})
    assert r.status_code == 200, r.text
    S["p"] = pid = r.json()["id"]
    r = s.post(f"{API}/equipment/{pid}/suppliers", json={"new_supplier": {"company": f"TEST_M36 {RUN} ESL"}, "purchase_uom": "rouleau 2 × 25 m", "conversion_factor": 50, "unit_price_ht": 180, "lead_time_days": 3})
    assert r.status_code == 200, r.text
    r = s.post(f"{API}/equipment/{pid}/suppliers", json={"new_supplier": {"company": f"TEST_M36 {RUN} Distriscene"}, "purchase_uom": "m²", "unit_price_ht": 3.9})
    rows = r.json()
    esl, dis = (next(x for x in rows if n in x["supplier_name"]) for n in ("ESL", "Distriscene"))
    S["esl"], S["dis"] = esl, dis
    assert esl["stock_price_ht"] == 3.6 and dis["stock_price_ht"] == 3.9 and esl["cheapest"] and not dis["cheapest"] and esl["is_preferred"] and not dis["is_preferred"]
    assert rows[0]["id"] == esl["id"]
    assert s.post(f"{API}/equipment/{pid}/suppliers", json={"supplier_id": esl["supplier_id"]}).status_code == 409
    assert DB.equipment.find_one({"id": pid})["default_supplier_id"] == esl["supplier_id"]
    assert DB.contacts.find_one({"id": esl["supplier_id"]})["types"] == ["fournisseur"]
    assert [x["product_id"] for x in s.get(f"{API}/supplier-products", params={"supplier_id": esl["supplier_id"]}).json()["rows"]] == [pid]
    r = s.put(f"{API}/supplier-products/{dis['id']}", json={"purchase_uom": "m²", "unit_price_ht": 3.9, "is_preferred": True}).json()
    assert [x["is_preferred"] for x in sorted(r, key=lambda x: x["supplier_name"])] == [True, False]
    assert DB.equipment.find_one({"id": pid})["default_supplier_id"] == dis["supplier_id"]


def test_invoice_updates_price_without_duplicate(s):
    body = {"supplier_contact_id": S["dis"]["supplier_id"], "number": "TEST_M36", "date": "2030-01-10", "amount_ht": 420, "lines": [{"product_id": S["p"], "qty": 100, "unit_price_ht": 4.5}]}
    r = s.post(f"{API}/purchase-invoices", json=body)
    assert r.status_code == 200, r.text
    up = r.json()["price_updates"][0]
    assert up["old_price"] == 3.9 and up["new_price"] == 4.5 and up["rise_alert"] is True and up["map_id"] == S["dis"]["id"]
    rows = s.get(f"{API}/equipment/{S['p']}/suppliers").json()
    assert len(rows) == 2 and next(x for x in rows if x["id"] == S["dis"]["id"])["unit_price_ht"] == 4.5
    h = s.get(f"{API}/supplier-products/{S['dis']['id']}/history").json()
    assert [x["price"] for x in h] == [4.5, 3.9] and h[0]["purchase_invoice_id"] == r.json()["id"]


def test_offers_in_purchase_needs_and_draft(s):
    r = s.post(f"{API}/purchase-needs", json={"label": "TEST_M36 moquette", "qty": 10})
    nid = r.json()["id"]
    DB.purchase_needs.update_one({"id": nid, "org_id": QA}, {"$set": {"product_id": S["p"]}})
    try:
        n = next(x for x in s.get(f"{API}/purchase-needs").json() if x["id"] == nid)
        assert [o["supplier_id"] for o in n["offers"]] == [S["dis"]["supplier_id"], S["esl"]["supplier_id"]]
    finally:
        DB.purchase_needs.delete_one({"id": nid, "org_id": QA})
    d = s.get(f"{API}/supplier-products/{S['esl']['id']}/price-request", params={"qty": 4}).json()
    assert "Demande de prix" in d["subject"] and "4 rouleau" in d["text"]


def test_costs_hidden_without_right(s):
    t = sess("technicien")
    assert t.get(f"{API}/equipment/{S['p']}/suppliers").status_code == 403
    assert t.get(f"{API}/supplier-products").json() == {"rows": [], "allowed": False} or t.get(f"{API}/supplier-products").status_code == 403
    assert requests.get(f"{API}/supplier-products").status_code == 401
    assert s.delete(f"{API}/supplier-products/{S['esl']['id']}").status_code == 200
    assert len(s.get(f"{API}/equipment/{S['p']}/suppliers").json()) == 1
