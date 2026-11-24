"""Iter 19 — PROMPT_DEVIS_DEPUIS_EVENEMENT : onglet Devis de l'événement, rattacher / déplacer / détacher. QA sandbox only, no e-mail."""
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
    for k in ("quotes", "events", "venues", "contacts", "equipment"):
        for i in _created[k]:
            s.delete(f"{API}/{k}/{i}")


def _nums(s, eid):
    r = s.get(f"{API}/events/{eid}/quotes")
    assert r.status_code == 200, r.text
    return [q["number"] for q in r.json()]


class TestEventQuotes:
    def test_setup_and_empty_tab(self):
        s = sess("admin")
        v, c = _venue(s, "EvQ"), _contact(s)
        eq = _eq(s, "Chaise", 10)
        line = [{"label": eq["name"], "qty": 4, "unit_price": 5, "vat": 20, "kind": "catalog", "equipment_id": eq["id"]}]
        qa = _direct(s, v["id"], c["id"], line, "2027-03-10")
        qb = _direct(s, v["id"], c["id"], [{"label": "Base", "qty": 1, "unit_price": 100, "vat": 20}], "2027-04-20")
        S.update(v=v, c=c, eq=eq, qa=qa, qb=qb, A=qa["event_id"], B=qb["event_id"])
        assert s.post(f"{API}/quotes/{qb['id']}/detach").status_code == 200
        assert _nums(s, S["B"]) == []
        assert s.get(f"{API}/quotes/{qb['id']}").json()["event_id"] == ""

    def test_new_quote_from_event_is_linked_and_prefilled(self):
        s = sess("admin")
        r = s.post(f"{API}/quotes/direct", json={"event_id": S["B"], "lines": [{"label": "Sono", "qty": 1, "unit_price": 200, "vat": 20}]})
        assert r.status_code == 200, r.text
        q = r.json()
        _created["quotes"].append(q["id"])
        assert q["event_id"] == S["B"] and q["client_id"] == S["c"]["id"] and q["language"] == "fr-FR" and q["event_date"] == "2027-04-20"
        st = s.get(f"{API}/quotes/{q['id']}/structure").json()
        assert st["venue_id"] == S["v"]["id"] and st["dates"]["operation"]["start"].startswith("2027-04-20") and st["event_id"] == S["B"]
        rows = s.get(f"{API}/events/{S['B']}/quotes").json()
        assert rows[0]["number"] == q["number"] and rows[0]["version"] == 1 and rows[0]["total_ttc"] == 240
        S["q_new"] = q

    def test_attach_quote_without_event_and_stock_on_event_dates(self):
        s, qb = sess("admin"), S["qb"]
        cands = s.get(f"{API}/events/{S['B']}/quote-candidates", params={"q": qb["number"]}).json()
        assert [x["id"] for x in cands] == [qb["id"]] and cands[0]["event_id"] == ""
        r = s.post(f"{API}/events/{S['B']}/quotes/attach", json={"quote_ids": [qb["id"]]})
        assert r.status_code == 200, r.text
        assert qb["number"] in _nums(s, S["B"])
        logs = MONGO.audit_logs.find_one({"action": "quote_attached", "target": qb["number"]})
        assert logs and logs["org_id"] == MONGO.orgs.find_one({"slug": "qa-sandbox"})["id"]

    def test_move_needs_confirmation_then_leaves_first_event(self):
        s, qa = sess("admin"), S["qa"]
        assert s.get(f"{API}/quotes/{qa['id']}/availability").json()["rows"]
        opt = [o for o in s.get(f"{API}/stock/options").json()["rows"] if o["quote_id"] == qa["id"]]
        assert opt and opt[0]["event_id"] == S["A"] and opt[0]["date"].startswith("2027-03")
        c = next(x for x in s.get(f"{API}/events/{S['B']}/quote-candidates").json() if x["id"] == qa["id"])
        assert c["event_id"] == S["A"] and c["event_label"] and "dates" in c["diffs"]
        r = s.post(f"{API}/events/{S['B']}/quotes/attach", json={"quote_ids": [qa["id"]]})
        assert r.status_code == 409 and "lié à" in r.text
        r = s.post(f"{API}/events/{S['B']}/quotes/attach", json={"quote_ids": [qa["id"]], "confirm_move": True, "align": "event"})
        assert r.status_code == 200, r.text
        assert qa["number"] in _nums(s, S["B"]) and qa["number"] not in _nums(s, S["A"])
        q = s.get(f"{API}/quotes/{qa['id']}").json()
        assert q["event_id"] == S["B"] and q["event_date"] == "2027-04-20"
        opt = [o for o in s.get(f"{API}/stock/options").json()["rows"] if o["quote_id"] == qa["id"]]
        assert opt and opt[0]["event_id"] == S["B"] and opt[0]["date"].startswith("2027-04"), opt
        assert MONGO.audit_logs.find_one({"action": "quote_moved", "target": qa["number"]})

    def test_signed_quote_is_not_modified_only_relinked(self):
        s, q = sess("admin"), S["q_new"]
        assert s.post(f"{API}/quotes/{q['id']}/status", json={"status": "accepte"}).status_code == 200
        before = s.get(f"{API}/quotes/{q['id']}").json()
        r = s.post(f"{API}/events/{S['A']}/quotes/attach", json={"quote_ids": [q["id"]], "confirm_move": True, "align": "event"})
        assert r.status_code == 200, r.text
        after = s.get(f"{API}/quotes/{q['id']}").json()
        assert after["event_id"] == S["A"]
        for k in ("event_title", "event_date", "client", "client_id", "language", "lines", "total_ttc", "status"):
            assert after[k] == before[k], k
        assert s.get(f"{API}/events/{S['A']}").json()["status"] == "confirme"

    def test_detach_keeps_quote(self):
        s, qb = sess("admin"), S["qb"]
        assert s.post(f"{API}/quotes/{qb['id']}/detach").status_code == 200
        assert qb["number"] not in _nums(s, S["B"])
        assert s.get(f"{API}/quotes/{qb['id']}").status_code == 200
        assert any(x["id"] == qb["id"] for x in s.get(f"{API}/quotes").json())
        assert MONGO.audit_logs.find_one({"action": "quote_detached", "target": qb["number"]})
        assert s.post(f"{API}/quotes/{qb['id']}/detach").status_code == 400

    def test_profile_without_price_right_gets_no_amounts(self):
        t = sess("technicien")
        assert t.get(f"{API}/events/{S['B']}/quotes").status_code == 404
        qa_org = MONGO.orgs.find_one({"slug": "qa-sandbox"})["id"]
        tid = f"qa-i19-{RUN}"
        MONGO.users.update_one({"org_id": qa_org, "email": "qa_technicien+clerk_test@example.com"}, {"$set": {"team_id": tid}})
        MONGO.events.update_one({"org_id": qa_org, "id": S["B"]}, {"$push": {"team": {"member_id": tid, "role": "Technicien"}}})
        r = t.get(f"{API}/events/{S['B']}/quotes")
        assert r.status_code == 200, r.text
        assert r.json() and all("total_ttc" not in x and "total_ht" not in x for x in r.json()) and "€" not in r.text
        assert t.post(f"{API}/events/{S['B']}/quotes/attach", json={"quote_ids": [S["qb"]["id"]]}).status_code == 403
        assert t.get(f"{API}/events/{S['B']}/quote-candidates").status_code == 403
        MONGO.users.update_one({"org_id": qa_org, "email": "qa_technicien+clerk_test@example.com"}, {"$set": {"team_id": None}})
