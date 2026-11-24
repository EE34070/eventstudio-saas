"""Iter 20 — PROMPT_DEVIS_DEPUIS_EVENEMENT §7 : dupliquer un devis, modèles de devis. QA sandbox only, no e-mail."""
import os

import pytest
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

from conftest import API  # noqa: E402
from test_iter17_quote_blocks import RUN, _contact, _created, _direct, _eq, _venue, sess  # noqa: E402,F401

MONGO = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
S = {}


@pytest.fixture(scope="module", autouse=True)
def _clean():
    yield
    s = sess("admin")
    for t in S.get("tpl", []):
        s.delete(f"{API}/quote-templates/{t}")
    for k in ("quotes", "events", "venues", "contacts", "equipment"):
        for i in _created[k]:
            s.delete(f"{API}/{k}/{i}")


def _dup(s, qid, **body):
    r = s.post(f"{API}/quotes/{qid}/duplicate", json=body)
    assert r.status_code == 200, r.text
    _created["quotes"].append(r.json()["id"])
    return r.json()


class TestDuplicate:
    def test_setup_signed_source(self):
        s = sess("admin")
        v1, v2, c1, c2 = _venue(s, "DupA"), _venue(s, "DupB"), _contact(s), _contact(s)
        sp = s.post(f"{API}/venues/{v1['id']}/spaces", json={"name": "Le Temple"}).json()
        eq = _eq(s, "Table", 50)
        qa_org = MONGO.orgs.find_one({"slug": "qa-sandbox"})["id"]
        MONGO.equipment.update_one({"org_id": qa_org, "id": eq["id"]}, {"$set": {"price_day": 9}})
        base = [{"label": "Base", "qty": 1, "unit_price": 100, "vat": 20}]
        src, other = _direct(s, v1["id"], c1["id"], base, "2027-05-10"), _direct(s, v2["id"], c2["id"], base, "2027-06-15")
        body = {"blocks": [{"id": "s" + RUN, "type": "section", "title": "Cérémonie", "space_id": sp["id"], "optional": True, "selected": True},
                           {"id": "l" + RUN, "parent_id": "s" + RUN, "type": "line", "label": eq["name"], "qty": 4, "unit_price": 5, "vat": 20, "discount_percent": 10, "equipment_id": eq["id"], "kind": "catalog"},
                           {"id": "t" + RUN, "parent_id": "s" + RUN, "type": "text", "description": "Texte libre"}],
                "price_display": "section_totals", "deposit_percent": 40, "global_discount_percent": 0}
        assert s.put(f"{API}/quotes/{src['id']}/structure", json=body).status_code == 200
        assert s.post(f"{API}/quotes/{src['id']}/share").status_code == 200
        assert s.post(f"{API}/quotes/{src['id']}/status", json={"status": "accepte"}).status_code == 200
        S.update(src=s.get(f"{API}/quotes/{src['id']}").json(), other=other, c2=c2, eq=eq)

    def test_signed_quote_to_other_event(self):
        s, src = sess("admin"), S["src"]
        d = _dup(s, src["id"], destination="event", event_id=S["other"]["event_id"], client="event", dates="event")
        assert d["number"] != src["number"] and d["status"] == "brouillon" and d["event_id"] == S["other"]["event_id"]
        assert d["client_id"] == S["c2"]["id"] and d["event_date"] == "2027-06-15" and "dates" not in d
        assert d["duplicated_from"]["number"] == src["number"]
        for k in ("signature", "share_token", "sent_at", "root_id", "applied_at", "version"):
            assert not d.get(k), k
        assert len(s.get(f"{API}/quotes/{d['id']}/versions").json()) == 1
        assert s.get(f"{API}/quotes/{d['id']}/views").json()["views"] == []
        assert [(b["type"], b["label"], b["qty"], b["unit_price"], b["discount_percent"], b["description"]) for b in d["blocks"]] == \
            [(b["type"], b["label"], b["qty"], b["unit_price"], b["discount_percent"], b["description"]) for b in src["blocks"]]
        assert d["price_display"] == "section_totals" and d["deposit_percent"] == 40 and d["total_ttc"] == src["total_ttc"] and d["blocks"][0]["optional"]
        assert all(not b["space_id"] for b in d["blocks"]) and any("emplacement" in w for w in d["warnings"])
        after = s.get(f"{API}/quotes/{src['id']}").json()
        assert {k: v for k, v in after.items() if k != "share_token"} == {k: v for k, v in src.items() if k != "share_token"}
        assert s.get(f"{API}/quotes/{d['id']}/structure").json()["dates"]["operation"]["start"].startswith("2027-06-15")

    def test_same_event_catalog_prices_keep_discounts_and_spaces(self):
        s, src = sess("admin"), S["src"]
        d = _dup(s, src["id"], destination="same", prices="catalog")
        line = next(b for b in d["blocks"] if b["type"] == "line")
        assert line["unit_price"] == 9 and line["discount_percent"] == 10 and d["total_ht"] == 32.4
        assert d["blocks"][0]["space_id"] == src["blocks"][0]["space_id"] and d["warnings"] == [] and d["client_id"] == src["client_id"]

    def test_no_event_and_custom_dates(self):
        s, src = sess("admin"), S["src"]
        d = _dup(s, src["id"], destination="none", dates="custom", custom_dates={"delivery": {"enabled": True}, "pickup": {"enabled": True}, "operation": {"start": "2027-09-01T18:00", "end": "2027-09-02T02:00"},
                                                                                 "delivery_same_day": True, "pickup_after_operation": True})
        assert d["event_id"] == "" and d["event_date"] == "2027-09-01" and d["dates"]["pickup"]["date"] == "2027-09-02"
        assert s.post(f"{API}/quotes/{src['id']}/duplicate", json={"destination": "event"}).status_code == 400

    def test_template_save_and_use(self):
        s, src = sess("admin"), S["src"]
        r = s.post(f"{API}/quote-templates", json={"quote_id": src["id"], "name": f"TEST_TPL_{RUN}"})
        assert r.status_code == 200, r.text
        S["tpl"] = [r.json()["id"]]
        assert any(t["id"] == S["tpl"][0] for t in s.get(f"{API}/quote-templates").json())
        r = s.post(f"{API}/quote-templates/{S['tpl'][0]}/use", json={"event_id": S["other"]["event_id"]})
        assert r.status_code == 200, r.text
        q = r.json()
        _created["quotes"].append(q["id"])
        assert q["status"] == "brouillon" and q["client_id"] == S["c2"]["id"] and q["total_ttc"] == src["total_ttc"] and q["number"] != src["number"]

    def test_duplicate_quote_without_stored_blocks(self):
        s = sess("admin")
        qa_org = MONGO.orgs.find_one({"slug": "qa-sandbox"})["id"]
        MONGO.quotes.update_one({"org_id": qa_org, "id": S["other"]["id"]}, {"$unset": {"blocks": ""}})
        d = _dup(s, S["other"]["id"], destination="same")
        assert d["total_ttc"] == 120 and [b["type"] for b in d["blocks"]] == ["section", "line"]

    def test_rbac(self):
        assert sess("technicien").post(f"{API}/quotes/{S['src']['id']}/duplicate", json={}).status_code == 403
