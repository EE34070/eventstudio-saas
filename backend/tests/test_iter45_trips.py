"""Iter 45 — Devis : tarification + trajets (QA sandbox uniquement)."""
import os
import subprocess
import uuid

import pytest
import requests

BASE = next(l.split("=", 1)[1].strip().rstrip("/") for l in open("/app/frontend/.env") if l.startswith("REACT_APP_BACKEND_URL="))
TAG = "TEST_M45_" + uuid.uuid4().hex[:5]


def sess(role):
    t = subprocess.run(["python3", "/app/scripts/qa_token.py", role], capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {t}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def w():
    a = sess("admin")
    ok = lambda r: (r.raise_for_status(), r.json())[1]  # noqa: E731
    venue = ok(a.post(f"{BASE}/api/venues", json={"name": f"{TAG} Rocabella", "city": "Le Pradet", "zip": "83220", "lat": 43.1056, "lng": 6.0236}))
    origin = ok(a.post(f"{BASE}/api/warehouses", json={"name": f"{TAG} Vestric", "city": "Vestric-et-Candiac", "lat": 43.7400, "lng": 4.2580, "priority": 50}))
    depot = ok(a.post(f"{BASE}/api/warehouses", json={"name": f"{TAG} dépôt sur place", "type": "site_client", "venue_id": venue["id"], "lat": 43.1056, "lng": 6.0236}))
    chair = ok(a.post(f"{BASE}/api/equipment", json={"ref": f"{TAG}-CH", "name": f"{TAG} chaise bistro", "category": "Mobilier", "qty_total": 0, "weight_kg": 4, "price_day": 3}))
    kit = ok(a.post(f"{BASE}/api/equipment", json={"ref": f"{TAG}-KS", "name": f"{TAG} kit son", "category": "Sonorisation", "qty_total": 0, "weight_kg": 60, "price_day": 150}))
    ok(a.post(f"{BASE}/api/stock/movements", json={"type": "entree", "product_id": chair["id"], "warehouse_id": depot["id"], "qty": 150}))
    van = ok(a.post(f"{BASE}/api/vehicles", json={"name": f"{TAG} utilitaire 12", "capacity_kg": 1000, "volume_m3": 12, "cost_km": 0.4}))
    ev = ok(a.post(f"{BASE}/api/events", json={"title": f"{TAG} mariage", "venue_id": venue["id"], "start": "2027-06-12T18:00", "end": "2027-06-13T02:00", "setup_start": "2027-06-12T10:00", "return_end": "2027-06-14T11:00"}))
    q = ok(a.post(f"{BASE}/api/events/{ev['id']}/quotes"))
    bag = dict(a=a, venue=venue, origin=origin, depot=depot, chair=chair, kit=kit, van=van, ev=ev, q=q)
    yield bag
    a.delete(f"{BASE}/api/events/{ev['id']}")
    a.delete(f"{BASE}/api/venues/{venue['id']}")


def compute(w, chairs, **kw):
    veh = [{"vehicle_id": w["van"]["id"]}]
    trips = kw.pop("trips", [{"id": "t1", "type": "delivery", "origin_id": w["origin"]["id"], "vehicles": veh}, {"id": "t2", "type": "pickup", "origin_id": w["origin"]["id"], "vehicles": veh}])
    r = w["a"].post(f"{BASE}/api/quotes/{w['q']['id']}/trips/compute", json={"lines": [{"equipment_id": w["chair"]["id"], "qty": chairs}, {"equipment_id": w["kit"]["id"], "qty": 1}], "trips": trips, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_pricing_defaults_and_rights(w):
    d = w["a"].get(f"{BASE}/api/pricing-settings").json()
    assert d["transport_mode"] == "zone" and d["zone_grid"]["utilitaire"][0] == {"max_km": 30, "price": 90} and d["employer_charge_coef"]["cddu"] == 1.65
    assert requests.get(f"{BASE}/api/pricing-settings").status_code == 401
    assert sess("technicien").get(f"{BASE}/api/pricing-settings").status_code in (401, 403)
    assert sess("commercial").put(f"{BASE}/api/pricing-settings", json=d).status_code in (401, 403)


def test_rocabella_only_to_deliver_part(w):
    d = compute(w, 180)
    t1, t2 = d["trips"]
    assert t1["weight_kg"] == 30 * 4 + 60 and t2["weight_kg"] == t1["weight_kg"]
    assert t1["date"] == "2027-06-12" and t2["date"] == "2027-06-14"
    assert 300 < t1["distance_km_rt"] < 600 and t1["fill_pct"] <= 100 and not t1["alerts"]
    assert len(d["lines"]) == 2 and d["lines"][0]["label"].startswith("Livraison et installation — 12/06")
    assert "kg" not in d["lines"][0]["label"] and "km" not in d["lines"][0]["label"]
    assert t1["cost_ht"] == round(t1["distance_km_rt"] * 0.4, 2)


def test_auto_vehicle_proposed(w):
    d = compute(w, 180, trips=[{"id": "t1", "type": "delivery", "origin_id": w["origin"]["id"]}])
    assert len(d["trips"][0]["vehicles"]) == 1


def test_400_chairs_alert_and_recalc(w):
    base = compute(w, 180, trips=[{"id": "t1", "type": "delivery", "origin_id": w["origin"]["id"], "vehicles": [{"vehicle_id": w["van"]["id"]}], "pricing_mode": "computed"}])
    big = compute(w, 550, trips=[{"id": "t1", "type": "delivery", "origin_id": w["origin"]["id"], "vehicles": [{"vehicle_id": w["van"]["id"]}], "pricing_mode": "computed"}])
    t = big["trips"][0]
    assert t["weight_kg"] == 400 * 4 + 60 and t["fill_pct"] > 100 and t["payload_alert"] and "ajoutez un véhicule" in t["alerts"][0]
    two = compute(w, 550, trips=[{"id": "t1", "type": "delivery", "origin_id": w["origin"]["id"], "pricing_mode": "computed",
                                  "vehicles": [{"vehicle_id": w["van"]["id"]}, {"rental_label": "Camion loué", "rental_cost_ht": 180, "rental_volume_m3": 20, "rental_capacity_kg": 1200}]}])
    t2 = two["trips"][0]
    assert t2["fill_pct"] <= 100 and t2["price_ht"] > base["trips"][0]["price_ht"] and t2["cost_ht"] >= 180
    assert t2["price_ht"] == round(60 + t2["distance_km_rt"] * 0.9 + 60 + t2["distance_km_rt"] * 1.3, 2)


def test_grouped_weight_and_all_on_site(w):
    g = compute(w, 180, display="grouped")
    assert len(g["lines"]) == 1 and g["lines"][0]["label"] == "Transport aller-retour (livraison et retrait)"
    assert "kg" in compute(w, 180, display="grouped", show_weight=True)["lines"][0]["label"]
    r = w["a"].post(f"{BASE}/api/quotes/{w['q']['id']}/trips/compute", json={"lines": [{"equipment_id": w["chair"]["id"], "qty": 100}]}).json()
    assert r["all_on_site"] and r["trips"][0]["on_site"] and r["lines"][0]["label"] == "Mise en place sur site"


def test_zone_manual_and_disabled_period(w):
    veh = [{"vehicle_id": w["van"]["id"]}]
    d = compute(w, 180, trips=[{"id": "t1", "type": "delivery", "vehicles": veh, "distance_manual": True, "distance_km_rt": 80, "tolls_ht": 12}, {"id": "t2", "type": "pickup", "vehicles": veh, "pricing_mode": "manual", "price_ht": 333}],
                dates={"delivery": {"enabled": True, "date": "2027-06-12", "start": "10:00", "end": "12:00"}, "operation": {"start": "2027-06-12T18:00", "end": "2027-06-13T02:00"}, "pickup": {"enabled": False, "date": "", "start": "", "end": ""}})
    assert d["trips"][0]["price_ht"] == 150 + 12 and d["trips"][1]["price_ht"] == 333 and not d["trips"][1]["enabled"]
    assert len(d["lines"]) == 1 and "10 h – 12 h" in d["lines"][0]["label"]


def test_save_sync_and_client_views(w):
    a, qid = w["a"], w["q"]["id"]
    veh = [{"vehicle_id": w["van"]["id"]}]
    body = {"lines": [{"equipment_id": w["chair"]["id"], "qty": 180}, {"equipment_id": w["kit"]["id"], "qty": 1}],
            "trips": [{"id": "t1", "type": "delivery", "origin_id": w["origin"]["id"], "vehicles": veh}, {"id": "t2", "type": "pickup", "origin_id": w["origin"]["id"], "vehicles": veh}]}
    d = a.put(f"{BASE}/api/quotes/{qid}/trips", json=body)
    assert d.status_code == 200, d.text
    st = a.get(f"{BASE}/api/quotes/{qid}/structure").json()
    assert st["has_trips"] and st["logistics_section"] == "Logistique & installation"
    sec = st["blocks"][0]["id"]
    line = lambda i, **k: {"id": i, "parent_id": k.pop("p", sec), "type": "line", **k}  # noqa: E731
    blocks = st["blocks"][:1] + [line("c1", label="Chaises", qty=180, unit_price=3, equipment_id=w["chair"]["id"], kind="catalog"), {"id": "s2", "type": "section", "title": "Logistique & installation"}] + \
        [line(f"g{i}", p="s2", **{k: v for k, v in l.items()}) for i, l in enumerate(d.json()["lines"])]
    r = a.put(f"{BASE}/api/quotes/{qid}/structure", json={"blocks": blocks, "dates": st["dates"]})
    assert r.status_code == 200, r.text
    st = a.get(f"{BASE}/api/quotes/{qid}/structure").json()
    tl = [b for b in st["blocks"] if b.get("source_type") == "trip"]
    assert len(tl) == 2 and tl[0]["kind"] == "transport" and tl[0]["unit_cost"] > 0
    link = a.post(f"{BASE}/api/quotes/{qid}/share")
    assert link.status_code == 200, link.text
    tok = link.json().get("token") or link.json().get("url", "").rstrip("/").split("/")[-1]
    if tok:
        pub = requests.get(f"{BASE}/api/public/quotes/{tok}").text
        assert "unit_cost" not in pub and "distance" not in pub and "weight" not in pub and "cost_ht" not in pub
    com = sess("commercial")
    c = com.get(f"{BASE}/api/quotes/{qid}/structure")
    if c.status_code == 200 and not c.json()["can_cost"]:
        assert all("unit_cost" not in b for b in c.json()["blocks"])
        cc = com.post(f"{BASE}/api/quotes/{qid}/trips/compute", json={}).json()
        assert "cost_ht" not in cc["trips"][0] and "unit_cost" not in cc["lines"][0]
    assert sess("technicien").post(f"{BASE}/api/quotes/{qid}/trips/compute", json={}).status_code in (401, 403)


OP = {"delivery": {"enabled": True, "date": "2027-06-12", "start": "10:00", "end": "12:00"}, "operation": {"start": "2027-06-12T18:00", "end": "2027-06-13T02:00"}, "pickup": {"enabled": True, "date": "2027-06-13", "start": "22:00", "end": "03:00"}}


def test_labor_surcharge_and_cddu(w):
    lab = [{"id": "l1", "role": "technicien_son", "headcount": 2, "phase": "operation", "unit": "hour", "cost_source": "employee", "contract": "cddu", "gross_hour": 20}]
    d = compute(w, 180, dates=OP, labor=lab)
    r = d["labor"][0]  # samedi 18 h -> dimanche 2 h : 2 h nuit (+25 %), 2 h dimanche (+50 %)
    assert r["computed_hours"] == 8 and r["multiplier"] == round(1 + (2 * 25 + 2 * 50) / 8 / 100, 4) and "nuit" in r["surcharge_note"]
    assert r["cost_ht"] == round(20 * 1.65 * 8 * r["multiplier"] * 2, 2) and r["price_ht"] == round(45 * 8 * r["multiplier"] * 2, 2)
    line = next(l for l in d["lines"] if l["source_type"] == "labor")
    assert line["label"].startswith("2 techniciens son — exploitation") and line["kind"] == "labor"
    g = compute(w, 180, dates=OP, labor=lab, labor_display="grouped")
    assert [l["label"] for l in g["lines"] if l["source_type"] == "labor"] == ["Main-d'œuvre (exploitation)"]


def test_expense_suggestions_and_modes(w):
    lab = [{"id": "l2", "role": "manutentionnaire", "headcount": 2, "phase": "pickup", "unit": "hour"}]
    d = compute(w, 180, dates=OP, labor=lab)
    sug = {x["label"]: x for x in d["suggested_expenses"]}
    assert sug["Nuitée"]["persons"] == 2 and sug["Nuitée"]["qty"] == 1 and sug["Nuitée"]["unit_price_ht"] == 95 and sug["Repas du soir"]["persons"] == 2
    ex = [{"id": "e1", "type": "lodging", "label": "Nuitée", "persons": 2, "qty": 1, "unit_cost_ht": 95, "unit_price_ht": 95}, {"id": "e2", "type": "meal", "persons": 2, "qty": 1, "unit_cost_ht": 20, "unit_price_ht": 20}]
    d = compute(w, 180, dates=OP, labor=lab, expenses=ex)
    el = [l for l in d["lines"] if l["source_type"] == "expense"]
    assert len(el) == 1 and el[0]["unit_price"] == 230 and el[0]["vat"] == 20 and el[0]["label"].startswith("Frais de déplacement")
    d = compute(w, 180, dates=OP, expenses=[{**ex[0], "mode": "client_provided"}, {**ex[1], "mode": "included"}, {"id": "e3", "type": "train", "label": "Billets", "unit_price_ht": 80, "mode": "actual", "debours": True}])
    el = {l["source_id"]: l for l in d["lines"] if l["source_type"] == "expense"}
    assert el["expenses_client"]["unit_price"] == 0 and "fournis par le client" in el["expenses_client"]["label"] and el["e3"]["vat"] == 0 and d["included_cost_ht"] == 40 and len(el) == 2


def test_signature_effects_idempotent(w):
    a, qid, eid = w["a"], w["q"]["id"], w["ev"]["id"]
    veh = [{"vehicle_id": w["van"]["id"]}, {"rental_label": "Camion loué", "rental_cost_ht": 180, "rental_volume_m3": 20, "rental_capacity_kg": 1200}]
    body = {"lines": [{"equipment_id": w["chair"]["id"], "qty": 180}], "dates": OP, "trips": [{"id": "t1", "type": "delivery", "origin_id": w["origin"]["id"], "vehicles": veh}],
            "labor": [{"id": "l1", "role": "technicien_son", "headcount": 2, "phase": "operation", "cost_source": "provider", "provider_rate": 300}],
            "expenses": [{"id": "e1", "type": "lodging", "persons": 2, "qty": 1, "unit_cost_ht": 95, "unit_price_ht": 95}, {"id": "e2", "type": "meal", "persons": 2, "mode": "client_provided"}]}
    assert a.put(f"{BASE}/api/quotes/{qid}/trips", json=body).status_code == 200
    for _ in range(2):
        r = a.post(f"{BASE}/api/quotes/{qid}/status", json={"status": "accepte"})
        assert r.status_code == 200, r.text
        a.post(f"{BASE}/api/quotes/{qid}/status", json={"status": "envoye"})
    pos = [p for p in a.get(f"{BASE}/api/events/{eid}/positions").json()["positions"]]
    assert len(pos) == 1 and pos[0]["quantity"] == 2 and pos[0]["start_time"] == "18:00" and pos[0]["end_time"] == "02:00"
    fin = a.get(f"{BASE}/api/events/{eid}/finance").json()
    labels = [c["label"] for c in fin.get("commitments", []) if c.get("source") == "quote_logistics"]
    assert len(labels) == 3 and any("Hôtel" in x for x in labels) and any("Location" in x for x in labels) and any("externe" in x for x in labels), labels
    tasks = [t["title"] for t in a.get(f"{BASE}/api/tasks", params={"event_id": eid}).json()["tasks"] if t.get("event_id") == eid]
    assert sum("Réserver hôtel" in t for t in tasks) == 1 and sum("Confirmer hébergement" in t for t in tasks) == 1, tasks
