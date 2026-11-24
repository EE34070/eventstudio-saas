"""Iter 27 — import IA des devis prestataires (QA sandbox uniquement, séquentiel). Appelle réellement Claude : PDF de test dans /tmp/decibel_*.pdf."""
import os
import subprocess
import uuid

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

from conftest import API  # noqa: E402

DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
ST = {}


def sess(role):
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip()
    return s


def extract(s, path, qid):
    with open(path, "rb") as fh:
        r = s.post(f"{API}/supplier-quotes/extract", params={"quote_id": qid}, files={"file": ("decibel.pdf", fh, "application/pdf")}, timeout=180)
    assert r.status_code == 200, r.text
    return r.json()


def body(x, qid, **kw):
    return {"file_ref": x["file_ref"], "quote_id": qid, "supplier": x["supplier"], "number": x["number"], "date": x["date"], "valid_until": x["valid_until"], "totals": x["totals"], "lines": x["lines"], **kw}


@pytest.fixture(scope="module")
def quote():
    if not os.path.exists("/tmp/decibel_v1.pdf"):
        pytest.skip("PDF de test absents")
    s = sess("admin")
    org = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
    evs = [e["id"] for e in DB.events.find({"org_id": org}, {"id": 1})]
    src = DB.quotes.find_one({"org_id": org, "status": "brouillon", "event_id": {"$in": evs}}, {"_id": 0}, sort=[("created_at", -1)])
    r = s.post(f"{API}/quotes/{src['id']}/duplicate", json={"destination": "same"})
    assert r.status_code == 200, r.text
    q = r.json()
    yield s, q.get("quote", q)["id"], org
    tag = ST.get("supplier_id")
    if tag:
        DB.equipment.delete_many({"org_id": org, "suppliers.supplier_id": tag})
        DB.supplier_quotes.delete_many({"org_id": org, "supplier_id": tag})
        DB.charge_commitments.delete_many({"org_id": org, "supplier_id": tag})
        DB.contacts.delete_one({"org_id": org, "id": tag})
    DB.tasks.delete_many({"org_id": org, "source_ref": {"$regex": "^supplier-order:"}})


def test_extract_12_lines_types_and_total(quote):
    s, qid, _ = quote
    x = extract(s, "/tmp/decibel_v1.pdf", qid)
    assert len(x["lines"]) == 12 and abs(sum(l["qty"] * l["unit_cost"] for l in x["lines"]) - 2092) < 0.05
    assert "decibel" in x["supplier"]["name"].lower() and not x["checks"]
    by = {l["ref"]: l for l in x["lines"]}
    assert by["DB-P01"]["type"] == "service" and by["DB-T01"]["type"] == "frais"
    ST["x"] = x


def test_import_creates_sublease_items_and_margins(quote):
    s, qid, org = quote
    x = ST["x"]
    for l in x["lines"]:
        l["action"] = "new"
    r = s.post(f"{API}/supplier-quotes/import", json=body(x, qid, margin_mode="coefficient", margin_value=1.25, rounding=5))
    assert r.status_code == 200, r.text
    d = r.json()
    ST.update(supplier_id=d["supplier_id"], sq=d["id"])
    assert d["created"] == 12 and d["inserted"] == 12
    eqs = list(DB.equipment.find({"org_id": org, "suppliers.supplier_id": d["supplier_id"]}))
    assert len(eqs) == 12 and all(e["kind"] == "sublease" and e["qty_total"] == 0 for e in eqs)
    assert not DB.stock_levels.find_one({"org_id": org, "product_id": {"$in": [e["id"] for e in eqs]}})
    st = s.get(f"{API}/quotes/{qid}/structure").json()
    lines = [b for b in st["blocks"] if b.get("supplier_quote_id") == d["id"]]
    x12 = next(b for b in lines if "X12" in b["label"])
    assert x12["unit_cost"] == 45 and x12["unit_price"] == 60 and st["can_cost"]
    assert {"SONORISATION", "ECLAIRAGE"} <= {b["title"].upper() for b in st["blocks"] if b["type"] == "section"}


def test_client_and_non_manager_never_see_supplier_or_costs(quote):
    s, qid, _ = quote
    tok = s.post(f"{API}/quotes/{qid}/share").json()
    token = tok.get("token") or tok.get("share_token") or tok["url"].rsplit("/", 1)[-1]
    raw = requests.get(f"{API}/public/quotes/{token}").text.lower()
    for word in ("decibel", "db-s01", "unit_cost", "supplier", "margin"):
        assert word not in raw, word
    pdf = s.get(f"{API}/quotes/{qid}/pdf")
    assert pdf.status_code == 200
    import fitz
    assert "decibel" not in "".join(p.get_text() for p in fitz.open(stream=pdf.content, filetype="pdf")).lower()
    c = sess("commercial")
    st = c.get(f"{API}/quotes/{qid}/structure").json()
    assert not st["can_cost"] and all("unit_cost" not in b for b in st["blocks"]) and not st.get("supplier_quotes")
    assert c.get(f"{API}/supplier-quotes", params={"quote_id": qid}).status_code == 403
    put = {k: st[k] for k in ("blocks", "dates", "price_display", "numbering", "global_discount_percent", "deposit_percent", "valid_until", "notes")}
    assert c.put(f"{API}/quotes/{qid}/structure", json=put).status_code == 200
    assert any(b.get("unit_cost") == 45 for b in s.get(f"{API}/quotes/{qid}/structure").json()["blocks"])


def test_bad_total_flagged_and_at_cost_blocks_send(quote):
    s, qid, org = quote
    x = extract(s, "/tmp/decibel_bad.pdf", qid)
    assert x["supplier"]["known"] and any(c["line"] is None for c in x["checks"])
    assert all(l["action"] == "existing" for l in x["lines"])
    r = s.post(f"{API}/supplier-quotes/import", json=body(x, qid, at_cost=True, target="new", section_title="TEST_IT27 coûtant"))
    assert r.status_code == 200 and r.json()["pending"] == 3 and r.json()["updated"] == 3
    r = s.post(f"{API}/quotes/{qid}/send")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "margin_pending"
    e = DB.equipment.find_one({"org_id": org, "suppliers.supplier_ref": "DB-S01"})
    assert len(e["cost_history"]) == 2


def test_v2_reimport_diff_and_costs(quote):
    s, qid, _ = quote
    x = extract(s, "/tmp/decibel_v2.pdf", qid)
    p = x["previous"]
    assert p and p["id"] == ST["sq"] and len(p["added"]) == 1 and len(p["changed"]) == 1 and p["changed"][0]["new"] == 50
    r = s.post(f"{API}/supplier-quotes/import", json=body(x, qid, previous_id=p["id"], keep_margin=True))
    assert r.status_code == 200 and r.json()["inserted"] == 1, r.text
    blocks = s.get(f"{API}/quotes/{qid}/structure").json()["blocks"]
    x12 = next(b for b in blocks if "X12" in b["label"] and b.get("supplier_quote_id") == r.json()["id"])
    assert x12["unit_cost"] == 50 and abs(x12["unit_price"] - 66.67) < 0.01
    ST["sq2"] = r.json()["id"]


def test_accept_creates_commitment_and_order_draft(quote):
    s, qid, org = quote
    import asyncio
    import sys
    sys.path.insert(0, "/app/backend")
    import routes_supplier_quotes as sq
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(sq.on_quote_accepted(org, DB.quotes.find_one({"id": qid}, {"_id": 0})))
    c = DB.charge_commitments.find_one({"org_id": org, "supplier_quote_id": ST["sq2"]})
    assert c and c["amount_ht"] > 2000
    d = s.get(f"{API}/supplier-quotes/{ST['sq2']}/order-draft").json()
    assert "DC-2026-118" in d["subject"] and "DC-2026-118" in d["body"]


def test_margin_rules_and_guards(quote):
    s, qid, _ = quote
    assert s.get(f"{API}/margin-rules").json()["mode"] in ("coefficient", "markup")
    assert sess("commercial").put(f"{API}/margin-rules", json={}).status_code == 403
    assert sess("technicien").post(f"{API}/supplier-quotes/import", json={}).status_code == 403
    assert s.post(f"{API}/supplier-quotes/import", json={"file_ref": f"file:{uuid.uuid4()}", "quote_id": qid, "supplier": {"name": "X"}, "lines": [{"label": "a"}]}).status_code == 404
