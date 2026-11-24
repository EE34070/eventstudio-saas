"""Iter 52 — Réemploi du matériel : stock mobilisé, contrôles, invisibilité client (QA uniquement)."""
import subprocess
import uuid

import pytest
import requests

BASE = next(l.split("=", 1)[1].strip().rstrip("/") for l in open("/app/frontend/.env") if l.startswith("REACT_APP_BACKEND_URL="))
TAG = "TEST_M52_" + uuid.uuid4().hex[:5]


def test_reuse():
    t = subprocess.run(["python3", "/app/scripts/qa_token.py", "admin"], capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
    a = requests.Session()
    a.headers.update({"Authorization": f"Bearer {t}", "Content-Type": "application/json"})
    ok = lambda r: (r.status_code < 300 or pytest.fail(r.text), r.json())[1]  # noqa: E731
    eq = lambda n, **k: ok(a.post(f"{BASE}/api/equipment", json={"ref": f"{TAG}-{n}", "name": f"{TAG} {n}", "category": "Sonorisation", "qty_total": 10, "price_day": 50, **k}))["id"]  # noqa: E731
    ev50, mic, mix, truss = eq("EV50"), eq("micro HF"), eq("table de mixage"), eq("truss", movable_during_event=False)
    ev = ok(a.post(f"{BASE}/api/events", json={"title": f"{TAG} mariage", "start": "2027-11-06T16:00", "end": "2027-11-07T01:00"}))
    try:
        q = ok(a.post(f"{BASE}/api/events/{ev['id']}/quotes"))
        dates = ok(a.get(f"{BASE}/api/quotes/{q['id']}/structure"))["dates"]
        L = lambda i, p, e, n, **k: {"id": i, "parent_id": p, "type": "line", "label": i, "qty": n, "unit_price": 50, "vat": 20, "equipment_id": e, "kind": "catalog", **k}  # noqa: E731

        def put(repas_start="19:30", mics=2, cer_end="17:00", **k):
            blocks = [{"id": "cer", "type": "section", "title": "Cérémonie", "usage_start": "16:00", "usage_end": cer_end}, L("c-ev", "cer", ev50, 1), L("c-mic", "cer", mic, 2), L("c-truss", "cer", truss, 1),
                      {"id": "rep", "type": "section", "title": "Repas", "usage_start": repas_start, "usage_end": "01:00"}, L("r-ev", "rep", ev50, 1, reuse_from="c-ev"), L("r-mic", "rep", mic, mics, reuse_from="c-mic", **k),
                      L("r-mix", "rep", mix, 1), L("r-truss", "rep", truss, 1, reuse_from="c-truss")]
            st = ok(a.put(f"{BASE}/api/quotes/{q['id']}/structure", json={"blocks": blocks, "dates": dates}))
            return {b["id"]: b for b in st["blocks"]}, {r["equipment_id"]: r for r in ok(a.get(f"{BASE}/api/quotes/{q['id']}/mobilized"))}
        b, m = put()
        assert b["r-mic"]["reuse_status"] == "validated" and (m[ev50]["mobilized"], m[mic]["mobilized"], m[mix]["mobilized"]) == (1, 2, 1) and m[mic]["quoted"] == 4
        assert b["r-truss"]["reuse_status"] == "invalid" and "non déplaçable" in b["r-truss"]["reuse_alert"] and m[truss]["mobilized"] == 2
        steps = ok(a.get(f"{BASE}/api/events/{ev['id']}/schedule"))["steps"]
        assert [s["title"] for s in steps] == ["Bascule Cérémonie → Repas"] and steps[0]["start"] == "2027-11-06T17:00" and "micro HF" not in steps[0]["title"] and "2 × r-mic" in steps[0]["description"]
        tok = ok(a.post(f"{BASE}/api/quotes/{q['id']}/share"))["token"]
        pub = requests.get(f"{BASE}/api/public/quotes/{tok}")
        assert pub.status_code == 200 and not any(k in pub.text for k in ("reuse", "reused", "usage_start", "Bascule", "mobilis"))
        assert sum(r["qty"] for r in pub.json()["rows"] if r["kind"] == "line" and r["label"] in ("c-mic", "r-mic")) == 4
        assert put(mics=3)[1][mic]["mobilized"] == 3
        b, m = put(repas_start="16:30")
        assert b["r-mic"]["reuse_status"] == "invalid" and "en même temps" in b["r-mic"]["reuse_alert"] and m[mic]["mobilized"] == 4
        assert not ok(a.get(f"{BASE}/api/events/{ev['id']}/schedule"))["steps"]
        b, m = put(repas_start="16:30", reuse_force_reason="deux régies proches")
        assert b["r-mic"]["reuse_status"] == "forced" and m[mic]["mobilized"] == 2
        b, _ = put(repas_start="17:10")
        assert b["r-mic"]["reuse_status"] == "validated" and "10 min" in b["r-mic"]["reuse_alert"]
        put()
        ok(a.post(f"{BASE}/api/quotes/{q['id']}/status", json={"status": "accepte"}))
        e = ok(a.get(f"{BASE}/api/events/{ev['id']}"))
        assert {l["equipment_id"]: l["qty"] for l in e["equipment"]} == {ev50: 1, mic: 2, mix: 1, truss: 2} and e["amount_ht"] == 450
    finally:
        a.delete(f"{BASE}/api/events/{ev['id']}")
