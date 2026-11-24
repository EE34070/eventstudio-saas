"""Iter 51 — Déroulé, plans organisateur, restes devis / DJ (QA uniquement)."""
import io
import os
import subprocess
import uuid

import pytest
import requests

BASE = next(l.split("=", 1)[1].strip().rstrip("/") for l in open("/app/frontend/.env") if l.startswith("REACT_APP_BACKEND_URL="))
TAG = "TEST_M51_" + uuid.uuid4().hex[:5]
D = "2027-08-21"


def sess(role):
    t = subprocess.run(["python3", "/app/scripts/qa_token.py", role], capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {t}"})
    return s


@pytest.fixture(scope="module")
def w():
    a = sess("admin")
    r = a.post(f"{BASE}/api/events", json={"title": f"{TAG} mariage", "start": f"{D}T10:00", "end": "2027-08-22T02:00", "modules": ["dj"]})
    assert r.status_code < 300, r.text
    yield a, r.json()["id"]
    a.delete(f"{BASE}/api/events/{r.json()['id']}")


def test_schedule_chain_and_conflict(w):
    a, eid = w
    st = lambda t, title, dur, rel="concerns_us": {"title": title, "start": f"{D}T{t}", "duration_min": dur, "relevance": rel}  # noqa: E731
    r = a.post(f"{BASE}/api/events/{eid}/schedule/validate", json={"steps": [st("10:00", "Maquillage", 120, "not_concerned"), st("16:00", "Cérémonie laïque", 30), st("17:00", "Cocktail", 120), st("23:00", "Ouverture de bal", 180)]})
    assert r.status_code == 200, r.text
    d = r.json()
    titles = [s["title"] for s in d["steps"]]
    assert [s["title"] for s in d["hidden"]] == ["Maquillage"] and "Balances son et réglages lumière" in titles and "Bascule sonorisation cérémonie → cocktail" in titles and titles[-1] == "Départ du site"
    fin = next(s for s in d["steps"] if s["title"].startswith("Fin d'installation"))
    assert fin["start"] == f"{D}T15:30" and fin["source"] == "auto" and d["conflicts"] == 0
    d = a.post(f"{BASE}/api/events/{eid}/schedule/steps", json={"after_id": fin["id"], "title": "Test micros officiant", "duration_min": 15}).json()
    i = [s["title"] for s in d["steps"]].index("Test micros officiant")
    assert d["steps"][i]["start"] == f"{D}T15:30" and d["steps"][i + 1]["title"] == "Cérémonie laïque" and d["steps"][i + 1]["start"] == f"{D}T16:00" and d["conflicts"] == 0
    d = a.put(f"{BASE}/api/schedule/steps/{d['steps'][i]['id']}", json={"duration_min": 45}).json()
    cer = next(s for s in d["steps"] if s["title"] == "Cérémonie laïque")
    assert cer["start"] == f"{D}T16:00" and "déborde de 15 min" in cer["conflict"] and d["conflicts"] == 1
    d = a.put(f"{BASE}/api/schedule/steps/{d['hidden'][0]['id']}", json={"visible": True}).json()
    assert not d["hidden"] and d["steps"][0]["title"] == "Chargement à l'entrepôt"
    # V2 : la cérémonie passe à 16 h 30, nos étapes sont conservées
    d = a.post(f"{BASE}/api/events/{eid}/schedule/validate", json={"steps": [st("16:30", "Cérémonie laïque", 45), st("17:30", "Cocktail", 120)]}).json()
    assert any(s["title"] == "Test micros officiant" for s in d["steps"]) and next(s for s in d["steps"] if s["title"] == "Cérémonie laïque")["start"] == f"{D}T16:30"
    assert sess("technicien").post(f"{BASE}/api/events/{eid}/schedule/steps", json={"title": "x"}).status_code in (401, 403, 404)


def test_ai_text_import(w):
    a, eid = w
    txt = "Planning mariage\n10h00 Maquillage et coiffure de la mariée\n14h00 Shooting photo du couple\n16h00 Cérémonie laïque dans le jardin\n17h00 Cocktail sur la terrasse\n20h00 Dîner\n22h30 Première danse\n02h00 Fin de la musique"
    r = a.post(f"{BASE}/api/events/{eid}/schedule/sources", data={"text": txt})
    assert r.status_code == 200, r.text
    rows = {x["title"].lower(): x for x in r.json()["raw_extraction"]}
    if not rows:
        pytest.skip("IA indisponible : " + r.json().get("warning", ""))
    rel = lambda k: next(v["relevance"] for t, v in rows.items() if k in t)  # noqa: E731
    assert rel("maquillage") == "not_concerned" and rel("shooting") == "not_concerned" and rel("cérémonie") == "concerns_us" and rel("première danse") == "concerns_us"
    assert next(v for t, v in rows.items() if "fin" in t)["start"].startswith("2027-08-22T02:00")


def test_plans_and_annotations(w):
    a, eid = w
    import pymupdf
    doc = pymupdf.open()
    doc.new_page()
    doc.new_page()
    pdf = doc.tobytes()
    p = a.post(f"{BASE}/api/events/{eid}/organizer-plans", files={"file": ("salle.pdf", io.BytesIO(pdf), "application/pdf")}, data={"zone_label": "Dîner"})
    assert p.status_code == 200, p.text
    p = p.json()
    assert p["page_count"] == 2 and p["version"] == 1
    img = a.get(f"{BASE}/api/organizer-plans/{p['id']}/page/1")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    anns = [{"id": "a1", "page": 0, "type": "pin", "geometry": {"x": 0.4, "y": 0.5}, "text": "Régie ici ?", "visibility": "shared"}, {"id": "a2", "page": 0, "type": "text", "geometry": {"x": 0.1, "y": 0.1}, "text": "note interne", "visibility": "internal"},
            {"id": "a3", "page": 0, "type": "arrow", "geometry": {"x1": 0.1, "y1": 0.1, "x2": 0.3, "y2": 0.3}}]
    assert a.put(f"{BASE}/api/organizer-plans/{p['id']}/annotations", json={"annotations": anns}).status_code == 200
    shared = a.get(f"{BASE}/api/events/{eid}/organizer-plans", params={"shared": True}).json()[0]["annotations"]
    assert [x["text"] for x in shared] == ["Régie ici ?"] and shared[0]["author"]
    v2 = a.post(f"{BASE}/api/events/{eid}/organizer-plans", files={"file": ("salle-v2.pdf", io.BytesIO(pdf), "application/pdf")}, data={"zone_label": "Dîner"}).json()
    assert v2["version"] == 2 and v2["previous_id"] == p["id"]


def test_quote_list_brand_remind_and_cron(w):
    a, _ = w
    d = a.get(f"{BASE}/api/quote-list?group=all&status=envoye&size=3").json()
    assert all(r["brand"] in ("Le Frenchie", "Exclusivity Events") for r in d["rows"])
    prev = a.post(f"{BASE}/api/quote-list/remind", json={"ids": [r["id"] for r in d["rows"]], "send": False})
    assert prev.status_code == 200, prev.text
    assert all(m["subject"] and len(m["body"]) == 4 and "sent" not in m for m in prev.json())
    assert requests.post(f"{BASE}/api/cron/dj-weekly", json={}).status_code == 401
    secret = next(l.split("=", 1)[1].strip().strip('"') for l in open("/app/backend/.env") if l.startswith("WEBHOOK_CRON_SECRET="))
    r = requests.post(f"{BASE}/api/cron/dj-weekly", json={"event": "schedule.triggered", "run_id": uuid.uuid4().hex}, headers={"Authorization": f"Bearer {secret}", "X-Webhook-Id": uuid.uuid4().hex})
    assert r.status_code == 200 and r.json()["ok"]
