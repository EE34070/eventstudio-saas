"""Iteration 5: event form (venues inline, modules, budget split) and contact types. Cleans up its TEST_ data."""
import os
import uuid

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient

from conftest import API

load_dotenv("/app/backend/.env")
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
TAG = f"TEST_F5_{uuid.uuid4().hex[:6]}"
BASE = {"type": "Mariage", "start": "2028-03-04T18:00", "end": "2028-03-05T02:00"}
NV = {"name": f"{TAG} Domaine", "address": "1 chemin des Oliviers", "zip": "13100", "city": "Aix-en-Provence",
      "contact_name": "Paul", "contact_phone": "0600000000", "access_instructions": "Portail vert"}


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    rx = {"$regex": f"^{TAG}"}
    ids = [e["id"] for e in db.events.find({"title": rx})]
    db.event_modules.delete_many({"event_id": {"$in": ids}})
    db.events.delete_many({"id": {"$in": ids}})
    db.venues.delete_many({"name": rx})
    db.contacts.delete_many({"last_name": rx})


def test_modules_catalog_from_db(admin):
    d = admin.get(f"{API}/modules").json()
    keys = [m["key"] for m in d["modules"]]
    assert "dj" in keys and "loueur_materiel" in keys
    assert d["defaults"].get("Mariage") == ["dj", "son_lumiere"]


def test_module_required_on_create(admin):
    r = admin.post(f"{API}/events", json={**BASE, "title": f"{TAG} sans module", "modules": []})
    assert r.status_code == 400
    r = admin.post(f"{API}/events", json={**BASE, "title": f"{TAG} inconnu", "modules": ["nope"]})
    assert r.status_code == 400


def test_create_with_new_venue_modules_budget(admin):
    r = admin.post(f"{API}/events", json={**BASE, "title": f"{TAG} complet", "modules": ["dj", "son_lumiere"], "budget": 12500,
                                          "budget_tax_mode": "ht", "module_budgets": {"dj": 4000, "son_lumiere": 6000}, "new_venue": NV})
    assert r.status_code == 200, r.text
    ev = admin.get(f"{API}/events/{r.json()['id']}").json()
    assert ev["venue"]["name"] == NV["name"] and ev["venue"]["access_instructions"] == "Portail vert"
    assert ev["budget"] == 12500 and ev["budget_tax_mode"] == "ht"
    assert {m["module_key"]: m["budget_amount"] for m in ev["modules"]} == {"dj": 4000, "son_lumiere": 6000}
    assert any(v["name"] == NV["name"] for v in admin.get(f"{API}/venues").json())
    # anti-doublon : même nom + code postal réutilise le lieu
    r2 = admin.post(f"{API}/events", json={**BASE, "title": f"{TAG} doublon", "modules": ["dj"], "new_venue": {**NV, "name": NV["name"].upper()}})
    assert r2.status_code == 200
    assert admin.get(f"{API}/events/{r2.json()['id']}").json()["venue_id"] == ev["venue_id"]
    assert db.venues.count_documents({"name": {"$regex": f"^{TAG}", "$options": "i"}}) == 1
    # modification : retrait d'un module
    p = admin.patch(f"{API}/events/{ev['id']}", json={"modules": ["dj"], "module_budgets": {"dj": 5000}})
    assert p.status_code == 200 and [(m["module_key"], m["budget_amount"]) for m in p.json()["modules"]] == [("dj", 5000)]


def test_rental_requires_delivery_venue(admin):
    body = {**BASE, "title": f"{TAG} location", "modules": ["loueur_materiel"]}
    assert admin.post(f"{API}/events", json=body).status_code == 400
    assert admin.post(f"{API}/events", json={**body, "new_venue": NV, "delivery_same_as_venue": False}).status_code == 400
    r = admin.post(f"{API}/events", json={**body, "new_venue": NV, "delivery_same_as_venue": False,
                                          "new_delivery_venue": {**NV, "name": f"{TAG} Quai", "zip": "13002", "city": "Marseille"}})
    assert r.status_code == 200, r.text
    ev = admin.get(f"{API}/events/{r.json()['id']}").json()
    assert ev["delivery_venue"]["name"] == f"{TAG} Quai" and ev["delivery_same_as_venue"] is False


def test_legacy_create_and_budget_hidden(admin, tech):
    r = admin.post(f"{API}/events", json={**BASE, "title": f"{TAG} ancien"})
    assert r.status_code == 200
    assert tech.post(f"{API}/events", json={**BASE, "title": f"{TAG} tech", "modules": ["dj"]}).status_code == 403


def test_contact_types(admin):
    c = admin.post(f"{API}/contacts", json={"last_name": f"{TAG} Traiteur", "types": ["prestataire", "bidon"]}).json()
    assert c["types"] == ["prestataire"]
    d = admin.post(f"{API}/contacts", json={"last_name": f"{TAG} Defaut"}).json()
    assert d["types"] == ["client"]
    names = [x["last_name"] for x in admin.get(f"{API}/contacts", params={"type": "prestataire"}).json()]
    assert f"{TAG} Traiteur" in names and f"{TAG} Defaut" not in names
    assert db.contacts.count_documents({"types": {"$exists": False}}) == 0
