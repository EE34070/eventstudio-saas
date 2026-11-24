"""Iter 46 — Devis importés : montants et matériel repris dans l'événement (QA uniquement)."""
import subprocess
import uuid

import pytest
import requests

BASE = next(l.split("=", 1)[1].strip().rstrip("/") for l in open("/app/frontend/.env") if l.startswith("REACT_APP_BACKEND_URL="))
TAG = "TEST_M46_" + uuid.uuid4().hex[:5]


def sess(role):
    t = subprocess.run(["python3", "/app/scripts/qa_token.py", role], capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {t}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def w():
    a = sess("admin")
    ok = lambda r: (r.status_code < 300 or pytest.fail(r.text), r.json())[1]  # noqa: E731
    chair = ok(a.post(f"{BASE}/api/equipment", json={"ref": f"{TAG}-CH", "name": f"{TAG} chaise", "category": "Mobilier", "qty_total": 100, "price_day": 3}))
    sono = ok(a.post(f"{BASE}/api/equipment", json={"ref": f"{TAG}-SO", "name": f"{TAG} sono", "category": "Sonorisation", "qty_total": 2, "price_day": 150}))
    evs = [ok(a.post(f"{BASE}/api/events", json={"title": f"{TAG} {n}", "start": "2027-09-11T18:00", "end": "2027-09-12T02:00"})) for n in ("X", "Y")]
    bag = dict(a=a, ok=ok, chair=chair, sono=sono, x=evs[0], y=evs[1])
    yield bag
    for e in evs:
        a.delete(f"{BASE}/api/events/{e['id']}")


def ev(w, k):
    return w["ok"](w["a"].get(f"{BASE}/api/events/{w[k]['id']}"))


def test_import_amounts_material_and_moves(w):
    a, ok = w["a"], w["ok"]
    body = {"ref": f"S-{TAG}", "event_id": w["x"]["id"], "status": "envoye", "total_ht": 3200, "lines": [
        {"ref": f"{TAG}-CH", "label": "Chaise pliante", "qty": 40, "unit_price": 5}, {"label": f"{TAG} sono", "qty": 1, "unit_price": 2000},
        {"label": "Prestation DJ", "qty": 1, "unit_price": 900}, {"label": f"Bidule inconnu {TAG}", "qty": 1, "unit_price": 100}]}
    q = ok(a.post(f"{BASE}/api/quotes/import", json=body))
    assert q["total_ht"] == 3200 and q["matched"] == 3 and q["to_match"] == 1 and q["import_gap"] == 0
    assert ok(a.post(f"{BASE}/api/quotes/import", json=body))["already_imported"]
    row = ok(a.get(f"{BASE}/api/events/{w['x']['id']}/quotes"))[0]
    assert row["total_ht"] == 3200 and row["unmatched"] == 1 and row["imported"]
    assert ev(w, "x")["amount_ht"] == 3200 and not ev(w, "x")["equipment"]
    fin = ok(a.get(f"{BASE}/api/events/{w['x']['id']}/finance"))
    assert fin["revenue"]["quoted_ht"] == 3200 and not fin["signed"]
    ok(a.post(f"{BASE}/api/quotes/{q['id']}/status", json={"status": "accepte"}))
    e = ev(w, "x")
    assert {l["equipment_id"]: l["qty"] for l in e["equipment"]} == {w["chair"]["id"]: 40, w["sono"]["id"]: 1} and e["amount_ht"] == 3200 and e["status"] == "confirme"
    assert ok(a.get(f"{BASE}/api/events/{w['x']['id']}/finance"))["probability"] == 100
    assert sorted(p["title"] for p in e["prestations"]) == sorted(["Prestation DJ", f"Bidule inconnu {TAG}"])
    m = ok(a.get(f"{BASE}/api/quotes/{q['id']}/matching"))
    unk = next(r for r in m["rows"] if r["label"].startswith("Bidule"))
    assert next(r for r in m["rows"] if r["label"] == "Prestation DJ")["action"] == "service" and unk["action"] == ""
    m = ok(a.put(f"{BASE}/api/quotes/{q['id']}/matching", json={"rows": [{"block_id": unk["block_id"], "action": "existing", "equipment_id": w["sono"]["id"]}]}))
    assert m["unmatched"] == 0
    e = ev(w, "x")
    assert {l["equipment_id"]: l["qty"] for l in e["equipment"]}[w["sono"]["id"]] == 2 and [p["title"] for p in e["prestations"]] == ["Prestation DJ"] and e["amount_ht"] == 3200
    ok(a.post(f"{BASE}/api/events/{w['x']['id']}/recalc-quotes"))
    assert len(ev(w, "x")["equipment"]) == 2
    ok(a.post(f"{BASE}/api/quotes/{q['id']}/detach"))
    e = ev(w, "x")
    assert e["amount_ht"] == 0 and not e["equipment"] and not e["prestations"]
    assert ok(a.get(f"{BASE}/api/events/{w['x']['id']}/finance"))["revenue"]["quoted_ht"] == 0
    ok(a.post(f"{BASE}/api/events/{w['y']['id']}/quotes/attach", json={"quote_ids": [q["id"]]}))
    e = ev(w, "y")
    assert e["amount_ht"] == 3200 and len(e["equipment"]) == 2
    q2 = ok(a.post(f"{BASE}/api/quotes/import", json={**body, "ref": f"S2-{TAG}", "event_id": "", "lines": [{"label": f"Bidule inconnu {TAG}", "qty": 3, "unit_price": 10}]}))
    assert q2["matched"] == 1 and q2["import_gap"] == -3170


def test_flat_import_and_rights(w):
    a, ok = w["a"], w["ok"]
    q = ok(a.post(f"{BASE}/api/quotes/import", json={"ref": f"F-{TAG}", "event_id": w["x"]["id"], "status": "envoye", "total_ht": 1500, "vat_rate": 20}))
    assert q["total_ht"] == 1500 and q["total_ttc"] == 1800 and q["import_flat"] and q["lines"][0]["label"].startswith("Prestation selon devis importé")
    row = ok(a.get(f"{BASE}/api/events/{w['x']['id']}/quotes"))[0]
    assert row["flat"] and row["unmatched"] == 0 and ev(w, "x")["amount_ht"] == 1500
    t = sess("technicien")
    assert t.post(f"{BASE}/api/quotes/import", json={"ref": "x", "total_ht": 1}).status_code in (401, 403)
    assert t.get(f"{BASE}/api/quotes/{q['id']}/matching").status_code in (401, 403)
    r = t.get(f"{BASE}/api/events/{w['x']['id']}/quotes")
    assert r.status_code != 200 or all("total_ht" not in x and "import_gap" not in x for x in r.json())
    r = t.get(f"{BASE}/api/events/{w['x']['id']}")
    assert r.status_code != 200 or not r.json().get("quote_ht")
