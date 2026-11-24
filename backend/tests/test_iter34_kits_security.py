"""Iter 34 — Sécurité multi-tenant pour nomenclatures et scènes (QA uniquement)."""
import os
import subprocess
import sys

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
from pymongo import MongoClient  # noqa: E402

API = "http://localhost:8001/api"
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]


def _tok(role):
    return subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip().splitlines()[-1]


@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + _tok("admin")
    return s


@pytest.fixture(scope="module")
def technicien():
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + _tok("technicien")
    return s


@pytest.fixture(scope="module")
def qa_event_id():
    e = DB.events.find_one({"org_id": QA, "title": "TEST_M34UI scène"})
    assert e, "seed_m34ui.py a besoin d'être exécuté en amont"
    return e["id"]


def test_no_token_returns_401():
    r = requests.get(f"{API}/kits")
    assert r.status_code == 401, r.text


def test_technicien_cannot_edit_kit(technicien):
    r = technicien.put(f"{API}/kits/new", json={"code": "TEST_SEC_kit", "name": "x", "rows": []})
    assert r.status_code == 403, r.text


def test_technicien_cannot_add_kit_to_event(technicien, qa_event_id):
    r = technicien.post(f"{API}/events/{qa_event_id}/kits", json={"code": "scene_modulaire", "params": {"ouverture_m": 10, "profondeur_m": 5, "hauteur_cm": 60, "systeme": "M34UI"}})
    assert r.status_code == 403, r.text


def test_event_from_other_org_returns_404(admin):
    # take an event that doesn't belong to QA
    other = DB.events.find_one({"org_id": {"$ne": QA}})
    if not other:
        pytest.skip("Aucun event d'une autre org disponible")
    r = admin.post(f"{API}/events/{other['id']}/kits", json={"code": "scene_modulaire", "params": {"ouverture_m": 10, "profondeur_m": 5, "hauteur_cm": 60, "systeme": "M34UI"}})
    assert r.status_code == 404, r.text
    r2 = admin.get(f"{API}/events/{other['id']}/kits/anything/plan")
    assert r2.status_code == 404, r2.text
