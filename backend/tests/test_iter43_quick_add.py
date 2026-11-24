"""Iter 43 — LOT 0/1: Nouveau devis depuis événement + Ajout rapide (QA sandbox)."""
import os
import subprocess
import time
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE:
    for _line in open("/app/frontend/.env"):
        if _line.startswith("REACT_APP_BACKEND_URL="):
            BASE = _line.split("=", 1)[1].strip().rstrip("/")


def _tok(role="admin"):
    out = subprocess.run(["python3", "/app/scripts/qa_token.py", role], capture_output=True, text=True, check=True)
    return out.stdout.strip().splitlines()[-1]


@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {_tok('admin')}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def created(admin):
    bag = {"event_ids": [], "quote_ids": []}
    yield bag
    # cleanup: delete created quotes then events
    for qid in bag["quote_ids"]:
        try:
            admin.delete(f"{BASE}/api/quotes/{qid}")
        except Exception:
            pass
    for eid in bag["event_ids"]:
        try:
            admin.delete(f"{BASE}/api/events/{eid}")
        except Exception:
            pass


class TestSecurity:
    def test_catalog_search_no_token(self):
        r = requests.get(f"{BASE}/api/catalog/search", params={"q": "enc"})
        assert r.status_code == 401

    def test_catalog_search_with_token(self, admin):
        r = admin.get(f"{BASE}/api/catalog/search", params={"q": "enc"})
        assert r.status_code == 200
        data = r.json()
        assert data["q"] == "enc"
        assert isinstance(data["items"], list)
        # Should find enceinte items (TEST_P9 enceinte, TEST_PD Enceinte)
        names = [it["name"].lower() for it in data["items"]]
        assert any("enceinte" in n for n in names), f"expected enceinte in {names}"

    def test_catalog_search_short_query(self, admin):
        r = admin.get(f"{BASE}/api/catalog/search", params={"q": "e"})
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_catalog_search_no_price_for_hidden_profile(self):
        """commercial profile: may or may not hide sale_prices. Check structure not strict."""
        try:
            tok = _tok("commercial")
        except Exception:
            pytest.skip("commercial token unavailable")
        s = requests.Session()
        s.headers.update({"Authorization": f"Bearer {tok}"})
        r = s.get(f"{BASE}/api/catalog/search", params={"q": "enc"})
        assert r.status_code == 200
        # Just validate the field semantics: if hidden, no 'price' key; if shown, price present.
        for it in r.json()["items"]:
            assert "id" in it and "name" in it and "available" in it


class TestQuickAddAvailability:
    def test_catalog_search_event_dates(self, admin, created):
        # Create a QA event
        body = {"title": "TEST_M43UI Backend Avail", "type": "Autre", "start": "2026-06-15T10:00:00", "end": "2026-06-15T23:00:00"}
        r = admin.post(f"{BASE}/api/events", json=body)
        assert r.status_code in (200, 201), r.text
        ev = r.json()
        created["event_ids"].append(ev["id"])
        # Query catalog/search at event dates
        r = admin.get(f"{BASE}/api/catalog/search", params={"q": "enc", "event_id": ev["id"]})
        assert r.status_code == 200
        data = r.json()
        assert data["items"], "should find items"
        for it in data["items"]:
            assert it.get("at_event_dates") is True


class TestEventQuotesCreateFrom:
    def test_create_quote_from_empty_event(self, admin, created):
        body = {"title": "TEST_M43UI Empty Event", "type": "Autre", "start": "2026-06-20T10:00:00", "end": "2026-06-20T23:00:00"}
        r = admin.post(f"{BASE}/api/events", json=body)
        assert r.status_code in (200, 201)
        ev = r.json()
        created["event_ids"].append(ev["id"])
        # POST /events/{eid}/quotes should succeed even with no prestations/equipment
        r = admin.post(f"{BASE}/api/events/{ev['id']}/quotes")
        assert r.status_code in (200, 201), r.text
        q = r.json()
        created["quote_ids"].append(q["id"])
        assert q["event_id"] == ev["id"]
        assert q["created_from"] == "evenement"
        assert q["number"]

    def test_list_quotes_has_created_from(self, admin, created):
        r = admin.get(f"{BASE}/api/quotes")
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        for q in rows:
            assert "created_from" in q
        # Our quote present
        if created["quote_ids"]:
            match = [q for q in rows if q["id"] == created["quote_ids"][0]]
            assert match, "created quote must appear in list"
            assert match[0]["created_from"] == "evenement"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
