"""Iter 32 — manques de matériel : jamais de blocage, liste en logistique, achats, partenaires. QA uniquement, aucun e-mail."""
import hashlib
import io
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

API = "http://localhost:8001/api"
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
RUN = uuid.uuid4().hex[:6]
S = {"files": []}


def sess(*a):
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", *a], text=True).strip().splitlines()[-1]
    return s


@pytest.fixture(scope="module")
def s():
    return sess("admin")


@pytest.fixture(scope="module", autouse=True)
def data(s):
    def eq(name, qty):
        r = s.post(f"{API}/equipment", json={"ref": f"TEST_M32_{RUN}_{name}", "name": f"TEST_M32 {name}", "qty_total": qty, "price_day": 10})
        assert r.status_code == 200, r.text
        return r.json()["id"]
    S["mic"], S["pile"] = eq("Micro", 10), eq("Pile AA", 4)
    r = s.put(f"{API}/equipment/{S['mic']}/requirements", json={"requirements": [{"type": "consommable", "label": "Pile AA", "linked_product_id": S["pile"], "quantity": 2, "calc_mode": "per_unit_day", "spare_pct": 100}]})
    assert r.status_code == 200, r.text
    S["client"] = str(uuid.uuid4())
    DB.contacts.insert_one({"id": S["client"], "org_id": QA, "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00", "test_tag": "TEST_M32",
                            "first_name": "TEST_M32", "last_name": RUN, "email": "test_m32_client@example.com", "language": "fr-FR", "types": ["client"]})
    for k in ("ev", "ev2"):
        r = s.post(f"{API}/events", json={"title": f"TEST_M32 {RUN} {k}", "start": "2029-03-04T18:00", "end": "2029-03-05T02:00", "client_id": S["client"]})
        assert r.status_code == 200, r.text
        S[k] = r.json()["id"]
    DB.events.update_many({"org_id": QA, "id": {"$in": [S["ev"], S["ev2"]]}}, {"$set": {"client_contact_ids": [S["client"]]}})
    yield
    evs, ids = [S[k] for k in ("ev", "ev2") if k in S], [S[k] for k in ("mic", "pile") if k in S]
    for c in ("quotes", "shortages", "purchase_needs", "partner_requests", "logistics_missions"):
        DB[c].delete_many({"org_id": QA, "event_id": {"$in": evs}})
    DB.tasks.delete_many({"org_id": QA, "$or": [{"event_id": {"$in": evs}}, {"source_ref": {"$in": [f"quote-signed:{S.get('q', '-')}"]}}]})
    DB.events.delete_many({"org_id": QA, "id": {"$in": evs}})
    DB.contacts.delete_many({"org_id": QA, "id": S["client"]})
    DB.files.update_many({"org_id": QA, "id": {"$in": S["files"]}}, {"$set": {"is_deleted": True}})
    for c in ("stock_levels", "stock_movements"):
        DB[c].delete_many({"org_id": QA, "product_id": {"$in": ids}})
    DB.equipment.delete_many({"org_id": QA, "id": {"$in": ids}})


def lines(s, ev="ev"):
    r = s.get(f"{API}/events/{S[ev]}/shortages")
    assert r.status_code == 200, r.text
    return r.json(), {x["product_id"]: x for x in r.json()["lines"]}


def test_confirm_never_blocked_and_list_created(s):
    assert s.patch(f"{API}/events/{S['ev']}", json={"equipment": [{"equipment_id": S["mic"], "qty": 3}]}).status_code == 200
    p = s.get(f"{API}/events/{S['ev']}/shortages/preview").json()
    assert len(p["lines"]) == 1 and p["summary"].startswith("1 manque : 8 × TEST_M32 Pile AA")
    assert lines(s)[0]["lines"] == []
    r = s.post(f"{API}/events/{S['ev']}/status", json={"status": "confirme"})
    assert r.status_code == 200 and r.json()["status"] == "confirme" and r.json()["shortages_count"] == 1, r.text
    d, L = lines(s)
    x = L[S["pile"]]
    assert x["status"] == "a_traiter" and x["missing"] == 8 and x["requested"] == 12 and x["available"] == 4 and x["auto"]
    assert "pour 3 ×" in x["origin"] and x["date_from"] and sum(w["qty"] for w in x["by_warehouse"]) == 4
    assert any("echnicien" in a for a in d["alerts"])
    ev = next(e for e in s.get(f"{API}/events", params={"q": f"TEST_M32 {RUN} ev"}).json() if e["id"] == S["ev"])
    assert ev["shortages_count"] == 1
    assert any(a["type"] == "manque" and a["event_id"] == S["ev"] for a in s.get(f"{API}/notifications").json()["alerts"])


def test_stock_added_resolves_automatically(s):
    wid = DB.warehouses.find_one({"org_id": QA, "is_default": True})["id"]
    r = s.post(f"{API}/stock/movements", json={"type": "entree", "product_id": S["pile"], "warehouse_id": wid, "qty": 10})
    assert r.status_code == 200, r.text
    x = DB.shortages.find_one({"org_id": QA, "event_id": S["ev"], "product_id": S["pile"]})
    assert x["status"] == "resolu" and x["resolved_auto"]
    assert lines(s)[0]["open"] == 0


def test_change_reopens_and_purchase_solution(s):
    r = s.patch(f"{API}/events/{S['ev']}", json={"equipment": [{"equipment_id": S["mic"], "qty": 12}]})
    assert r.status_code == 200, r.text
    d, L = lines(s)
    assert L[S["mic"]]["missing"] == 2 and not L[S["mic"]]["auto"] and L[S["pile"]]["status"] == "a_traiter" and L[S["pile"]]["missing"] == 34
    r = s.patch(f"{API}/shortages/{L[S['mic']]['id']}", json={"solution_type": "achat", "note": "urgent"})
    assert r.status_code == 200 and r.json()["line"]["status"] == "solution", r.text
    needs = [n for n in s.get(f"{API}/purchase-needs").json() if n["event_id"] == S["ev"]]
    assert len(needs) == 1 and needs[0]["qty"] == 2 and needs[0]["status"] == "a_acheter" and needs[0]["event_code"]
    s.patch(f"{API}/shortages/{L[S['mic']]['id']}", json={"solution_type": "achat"})
    assert len([n for n in s.get(f"{API}/purchase-needs").json() if n["event_id"] == S["ev"]]) == 1
    assert s.patch(f"{API}/purchase-needs/{needs[0]['id']}", json={"status": "commande"}).json()["status"] == "commande"
    s.patch(f"{API}/events/{S['ev']}", json={"equipment": [{"equipment_id": S["mic"], "qty": 11}]})
    x = lines(s)[1][S["mic"]]
    assert x["missing"] == 1 and x["status"] == "solution" and x["solution"]["type"] == "achat"
    wid = DB.warehouses.find_one({"org_id": QA, "is_default": True})["id"]
    r = s.patch(f"{API}/shortages/{x['id']}", json={"solution_type": "transfert", "warehouse_id": wid})
    assert r.json()["line"]["solution"]["warehouse_name"]
    assert s.patch(f"{API}/shortages/{x['id']}", json={"solution_type": "substitution", "substitute_id": S["pile"]}).json()["line"]["solution"]["substitute_id"] == S["pile"]
    assert s.patch(f"{API}/shortages/{x['id']}", json={"status": "resolu"}).json()["line"]["status"] == "resolu"
    s.patch(f"{API}/events/{S['ev']}", json={"equipment": [{"equipment_id": S["mic"], "qty": 12}]})
    assert lines(s)[1][S["mic"]]["status"] == "resolu"
    assert sess("technicien").patch(f"{API}/shortages/{x['id']}", json={"status": "a_traiter"}).status_code in (403, 404)


def test_client_signature_confirms_with_internal_notice_only(s):
    r = s.post(f"{API}/quotes/direct", json={"event_id": S["ev2"], "lines": [{"label": "Micro", "qty": 3, "unit_price": 30, "vat": 20, "equipment_id": S["mic"]}]})
    assert r.status_code == 200, r.text
    S["q"] = qid = r.json()["id"]
    token = s.post(f"{API}/quotes/{qid}/share").json()["token"]
    from reportlab.pdfgen.canvas import Canvas
    buf = io.BytesIO()
    Canvas(buf).save()
    f = s.post(f"{API}/files", files={"file": ("devis.pdf", buf.getvalue(), "application/pdf")}).json()
    S["files"].append(f["id"])
    stored = s.get(f"{API}/files/{f['id']}").content
    DB.quotes.update_one({"org_id": QA, "id": qid}, {"$set": {"status": "envoye", "signature": {
        "status": "ongoing", "provider": "otp", "otp_salt": "s", "otp_hash": hashlib.sha256(b"s:123456").hexdigest(), "otp_tries": 0, "sent_to": "test_m32_client@example.com",
        "otp_expires": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(), "frozen_file": f["ref"], "hash": hashlib.sha256(stored).hexdigest()}}})
    r = requests.post(f"{API}/public/quotes/{token}/sign/confirm", json={"code": "123456", "name": "Jean Test", "title": "", "accept": True})
    assert r.status_code == 200 and r.json()["status"] == "accepte", r.text
    pub = r.text + requests.get(f"{API}/public/quotes/{token}").text
    assert "manque" not in pub.lower() and "shortage" not in pub.lower() and "stock_alerts" not in pub
    assert DB.events.find_one({"id": S["ev2"]})["status"] == "confirme"
    d, L = lines(s, "ev2")
    assert L[S["mic"]]["missing"] == 3 and d["open"] == 2
    t = DB.tasks.find_one({"org_id": QA, "source_ref": f"shortage:{S['ev2']}"})
    assert t and "confirmé — 2 manques à traiter" in t["title"] and t["priority"] == "urgent"
    assert any(a["type"] == "manque" and a["event_id"] == S["ev2"] for a in s.get(f"{API}/notifications").json()["alerts"])
    r = s.patch(f"{API}/shortages/{L[S['mic']]['id']}", json={"solution_type": "reduction", "qty": 1})
    assert "touche le devis client" in r.json()["warning"]


def test_client_sees_nothing(s):
    c = sess("client", "qa_client+clerk_test@example.com", S["client"])
    for path in (f"/events/{S['ev2']}/shortages", f"/events/{S['ev2']}/shortages/preview", f"/events/{S['ev2']}/shortages/pdf", "/logistics/shortages", "/purchase-needs"):
        assert c.get(API + path).status_code == 404, path
    sid = DB.shortages.find_one({"org_id": QA, "event_id": S["ev2"]})["id"]
    assert c.patch(f"{API}/shortages/{sid}", json={"status": "resolu"}).status_code == 404
    for sub in ("", "/documents", "/billing", "/timeline"):
        r = c.get(f"{API}/portal/client/events/{S['ev2']}{sub}")
        assert r.status_code in (200, 404) and "manque" not in r.text.lower() and "shortage" not in r.text.lower(), sub
    assert "shortage" not in c.get(f"{API}/portal/client/events").text.lower()


def test_partner_requests_flow(s):
    d, L = lines(s, "ev2")
    ids = [x["id"] for x in d["lines"] if x["status"] != "resolu"]
    r = s.post(f"{API}/events/{S['ev2']}/partner-requests", json={"partners": [{"name": "Partenaire A", "email": "a@example.com"}, {"name": "Partenaire B"}], "shortage_ids": ids, "deadline": "2029-02-20"})
    assert r.status_code == 200 and len(r.json()) == 2 and not any(x["email_sent"] for x in r.json()), r.text
    assert all("token_hash" not in x and "share_nonce" not in x for x in r.json())
    a, b = r.json()
    tok = a["link"].rsplit("/", 1)[1]
    pub = requests.get(f"{API}/public/partner-requests/{tok}")
    assert pub.status_code == 200 and len(pub.json()["items"]) == 2 and "org_id" not in pub.text and "TEST_M32" in pub.text
    assert requests.get(f"{API}/public/partner-requests/{tok}x").status_code == 404
    assert s.post(f"{API}/partner-requests/{a['id']}/accept").status_code == 409
    mic = L[S["mic"]]["id"]
    r = requests.post(f"{API}/public/partner-requests/{tok}/reply", json={"items": [{"shortage_id": mic, "available_qty": 3, "unit_cost": 2}, {"shortage_id": "inconnu", "available_qty": 9}], "conditions": "Enlèvement"})
    assert r.status_code == 200, r.text
    got = next(x for x in lines(s, "ev2")[0]["requests"] if x["id"] == a["id"])
    assert got["status"] == "repondue" and got["reply"]["cost_total"] == 6 and len(got["reply"]["items"]) == 1
    r = s.post(f"{API}/partner-requests/{a['id']}/accept")
    assert r.status_code == 200 and {x["id"]: x["status"] for x in r.json()} == {a["id"]: "acceptee", b["id"]: "non_retenue"}
    x = lines(s, "ev2")[1][S["mic"]]
    assert x["status"] == "resolu" and "Partenaire A" in x["solution"]["note"]
    assert lines(s, "ev2")[1][S["pile"]]["status"] == "solution"
    assert requests.post(f"{API}/public/partner-requests/{tok}/reply", json={"items": []}).status_code == 409


def test_pdf_and_global_view(s):
    r = s.get(f"{API}/events/{S['ev2']}/shortages/pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    import pymupdf
    assert "Pile AA" in "".join(p.get_text() for p in pymupdf.open(stream=r.content, filetype="pdf"))
    g = s.get(f"{API}/logistics/shortages", params={"date_from": "2029-03-01", "date_to": "2029-03-31"}).json()
    assert {S["ev"], S["ev2"]} <= {e["id"] for e in g["events"]} and all(x["status"] != "resolu" and x["event_code"] for x in g["lines"])
    assert S["ev"] not in {e["id"] for e in s.get(f"{API}/logistics/shortages", params={"date_from": "2030-01-01"}).json()["events"]}
