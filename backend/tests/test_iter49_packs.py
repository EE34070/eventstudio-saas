"""Iter 49 — Packs à composition visible + plusieurs devis acceptés par événement (QA uniquement)."""
import subprocess
import uuid

import pytest
import requests

BASE = next(l.split("=", 1)[1].strip().rstrip("/") for l in open("/app/frontend/.env") if l.startswith("REACT_APP_BACKEND_URL="))
TAG = "TEST_M49_" + uuid.uuid4().hex[:5]


def sess(role):
    t = subprocess.run(["python3", "/app/scripts/qa_token.py", role], capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {t}", "Content-Type": "application/json"})
    return s


def test_pack_and_two_accepted_quotes():
    a = sess("admin")
    ok = lambda r: (r.status_code < 300 or pytest.fail(r.text), r.json())[1]  # noqa: E731
    eq = lambda n, t, q: ok(a.post(f"{BASE}/api/equipment", json={"ref": f"{TAG}-{n}", "name": f"{TAG} {n}", "category": "Sonorisation", "product_type": t, "qty_total": q, "price_day": 10}))  # noqa: E731
    enc, tube, dj, chair = eq("enceinte", "Location", 4), eq("tube Astera", "Location", 10), eq("DJ 8 h", "Prestation artistique", 0), eq("chaise", "Location", 100)
    pack = eq("Formule Signature", "Pack", 0)
    comps = [{"equipment_id": enc["id"], "qty": 2, "client_label": "enceintes (200 pers. max)"}, {"equipment_id": tube["id"], "qty": 5}, {"equipment_id": dj["id"], "qty": 1, "client_label": "DJ set son & lumière"}]
    p = ok(a.put(f"{BASE}/api/equipment/{pack['id']}/pack", json={"components": comps}))
    assert len(p["components"]) == 3 and p["product_type"] == "Pack"
    assert a.put(f"{BASE}/api/equipment/{pack['id']}/pack", json={"components": [{"equipment_id": pack["id"], "qty": 1}]}).status_code == 400
    assert sess("technicien").put(f"{BASE}/api/equipment/{pack['id']}/pack", json={"components": []}).status_code in (401, 403)
    ev = ok(a.post(f"{BASE}/api/events", json={"title": f"{TAG} mariage", "start": "2027-10-09T18:00", "end": "2027-10-10T02:00"}))
    try:
        def quote(lines):
            q = ok(a.post(f"{BASE}/api/events/{ev['id']}/quotes"))
            st = ok(a.get(f"{BASE}/api/quotes/{q['id']}/structure"))
            sec = st["blocks"][0]
            ok(a.put(f"{BASE}/api/quotes/{q['id']}/structure", json={"blocks": [sec] + [{"id": f"l{i}", "parent_id": sec["id"], "type": "line", **l} for i, l in enumerate(lines)], "dates": st["dates"]}))
            return q
        names = {enc["id"]: enc["name"], tube["id"]: tube["name"], dj["id"]: dj["name"]}
        pc = [{**c, "name": names[c["equipment_id"]], "base_qty": c["qty"], "visible_client": True, "service": c["equipment_id"] == dj["id"]} for c in comps]
        pc[1]["qty"] = 7
        q1 = quote([{"label": "Formule Signature", "qty": 1, "unit_price": 2083.33, "vat": 20, "equipment_id": pack["id"], "kind": "catalog", "pack_components": pc, "show_components": True}])
        tok = ok(a.post(f"{BASE}/api/quotes/{q1['id']}/share"))["token"]
        pub = requests.get(f"{BASE}/api/public/quotes/{tok}").json()
        row = next(r for r in pub["rows"] if r["kind"] == "line")
        assert row["unit_price"] == 2083.33 and "Matériel inclus : 2 × enceintes (200 pers. max) · 7 × " in row["description"] and "Prestations incluses : 1 × DJ set son & lumière" in row["description"]
        assert "10" not in row["description"].replace(TAG, "") and "pack_components" not in str(pub.get("lines"))[:0]
        assert requests.get(f"{BASE}/api/public/quotes/{tok}/pdf").status_code == 200
        ok(a.post(f"{BASE}/api/quotes/{q1['id']}/status", json={"status": "accepte"}))
        e = ok(a.get(f"{BASE}/api/events/{ev['id']}"))
        assert {l["equipment_id"]: l["qty"] for l in e["equipment"]} == {enc["id"]: 2, tube["id"]: 7} and e["amount_ht"] == 2083.33
        cat = next(x for x in ok(a.get(f"{BASE}/api/equipment", params={"start": "2027-10-09T18:00", "end": "2027-10-10T02:00"}))["items"] if x["id"] == pack["id"])
        assert [c["qty"] for c in cat["components"]] == [2, 5, 1]
        q2 = quote([{"label": "Chaises", "qty": 40, "unit_price": 5, "vat": 20, "equipment_id": chair["id"], "kind": "catalog"}])
        ok(a.post(f"{BASE}/api/quotes/{q2['id']}/status", json={"status": "accepte"}))
        e = ok(a.get(f"{BASE}/api/events/{ev['id']}"))
        assert e["amount_ht"] == 2283.33 and {l["equipment_id"]: l["qty"] for l in e["equipment"]} == {enc["id"]: 2, tube["id"]: 7, chair["id"]: 40}
        fin = ok(a.get(f"{BASE}/api/events/{ev['id']}/finance"))
        assert fin["revenue"]["quoted_ht"] == 2283.33 and fin["signed"]
        ok(a.post(f"{BASE}/api/quotes/{q1['id']}/status", json={"status": "envoye"}))
        st = ok(a.get(f"{BASE}/api/quotes/{q1['id']}/structure"))
        st["blocks"][1]["show_components"] = False
        ok(a.put(f"{BASE}/api/quotes/{q1['id']}/structure", json={"blocks": st["blocks"], "dates": st["dates"]}))
        row = next(r for r in requests.get(f"{BASE}/api/public/quotes/{tok}").json()["rows"] if r["kind"] == "line")
        assert "inclus" not in row["description"]
        assert ok(a.get(f"{BASE}/api/events/{ev['id']}"))["amount_ht"] == 200
    finally:
        a.delete(f"{BASE}/api/events/{ev['id']}")
