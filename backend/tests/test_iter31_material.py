"""Iter 31 — Matériel : fiches PDF et besoins (QA uniquement). Données TEST_M31 créées puis supprimées, même en cas d'échec. Aucun e-mail."""
import io
import os
import subprocess
import uuid

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

API = "http://localhost:8001/api"
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
RUN = uuid.uuid4().hex[:6]
S = {"docs": [], "files": []}


def sess(role="admin"):
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip().splitlines()[-1]
    return s


def pdf(text):
    from reportlab.pdfgen.canvas import Canvas
    buf = io.BytesIO()
    c = Canvas(buf)
    c.drawString(72, 720, text)
    c.save()
    return buf.getvalue()


def upload(s, text):
    r = s.post(f"{API}/files", files={"file": ("fiche.pdf", pdf(text), "application/pdf")})
    assert r.status_code == 200, r.text
    S["files"].append(r.json()["id"])
    return r.json()["ref"]


@pytest.fixture(scope="module")
def s():
    return sess()


@pytest.fixture(scope="module", autouse=True)
def data(s):
    def eq(name, qty):
        r = s.post(f"{API}/equipment", json={"ref": f"TEST_M31_{RUN}_{name}", "name": f"TEST_M31 {name}", "qty_total": qty, "price_day": 10})
        assert r.status_code == 200, r.text
        return r.json()["id"]
    S["mic"], S["pile"], S["pied"], S["mic2"] = eq("Micro HF", 10), eq("Pile AA", 10), eq("Pied", 10), eq("Micro main", 5)
    r = s.post(f"{API}/events", json={"title": f"TEST_M31 {RUN}", "start": "2028-03-04T18:00", "end": "2028-03-05T02:00"})
    assert r.status_code == 200, r.text
    S["ev"] = r.json()["id"]
    yield
    ids = [S[k] for k in ("mic", "pile", "pied", "mic2") if k in S]
    DB.quotes.delete_many({"org_id": QA, "event_id": S.get("ev", "-")})
    DB.events.delete_many({"org_id": QA, "id": S.get("ev", "-")})
    DB.product_documents.delete_many({"org_id": QA, "id": {"$in": S["docs"]}})
    DB.requirement_templates.delete_many({"org_id": QA, "name": {"$regex": f"^TEST_M31_{RUN}"}})
    DB.files.update_many({"org_id": QA, "id": {"$in": S["files"]}}, {"$set": {"is_deleted": True}})
    for c in ("stock_levels", "stock_movements"):
        DB[c].delete_many({"org_id": QA, "product_id": {"$in": ids}})
    DB.equipment.delete_many({"org_id": QA, "id": {"$in": ids}})


def reqs(s):
    r = s.get(f"{API}/events/{S['ev']}/requirements")
    assert r.status_code == 200, r.text
    d = r.json()
    return d, {l["label"]: l for l in d["lines"]}


def test_documents_versions_links_primary(s):
    a = s.post(f"{API}/product-documents", json={"file_ref": upload(s, "fiche v1"), "title": "Fiche technique", "type": "fiche_technique", "visibility": "client", "is_primary": True, "product_ids": [S["mic"]]}).json()
    b = s.post(f"{API}/product-documents", json={"file_ref": upload(s, "notice v1"), "title": "Notice", "type": "notice", "visibility": "interne", "is_primary": True, "product_ids": [S["mic"]]}).json()
    S["docs"] += [a["id"], b["id"]]
    S["doc_client"], S["doc_interne"] = a["id"], b["id"]
    docs = {d["id"]: d for d in s.get(f"{API}/product-documents", params={"product_id": S["mic"]}).json()}
    assert len(docs) == 2 and docs[b["id"]]["is_primary"] and not docs[a["id"]]["is_primary"]
    old = b["file_ref"]
    r = s.patch(f"{API}/product-documents/{b['id']}", json={"file_ref": upload(s, "notice v2")}).json()
    assert r["version"] == 2 and r["history"][0]["file_ref"] == old
    assert s.get(f"{API}/files/{old[5:]}").status_code == 200
    r = s.patch(f"{API}/product-documents/{b['id']}", json={"product_ids": [S["mic"], S["mic2"]]}).json()
    assert len(s.get(f"{API}/product-documents", params={"product_id": S["mic2"]}).json()) == 1
    assert s.patch(f"{API}/product-documents/{b['id']}", json={"product_ids": []}).status_code == 400
    assert sess("technicien").post(f"{API}/product-documents", json={"file_ref": old, "title": "x", "product_ids": [S["mic"]]}).status_code in (403, 404)


def test_requirements_and_templates(s):
    rows = [{"type": "consommable", "label": "Pile AA", "linked_product_id": S["pile"], "quantity": 2, "unit": "pièce", "calc_mode": "per_unit_day", "spare_pct": 100},
            {"type": "accessoire_optionnel", "label": "Pied de micro", "linked_product_id": S["pied"], "quantity": 1, "calc_mode": "per_unit"},
            {"type": "alimentation", "label": "Récepteur 230 V", "quantity": 1, "calc_mode": "per_unit", "power_w": 15, "sockets": 1, "voltage": "230 V"},
            {"type": "humain", "label": "Technicien son", "quantity": 1, "calc_mode": "per_event", "setup_min": 10}]
    r = s.put(f"{API}/equipment/{S['mic']}/requirements", json={"requirements": rows})
    assert r.status_code == 200 and len(r.json()) == 4, r.text
    t = s.post(f"{API}/requirement-templates", json={"name": f"TEST_M31_{RUN} micro", "lines": rows})
    assert t.status_code == 200 and len(t.json()["lines"]) == 4
    assert any(x["id"] == t.json()["id"] for x in s.get(f"{API}/requirement-templates").json())
    assert s.delete(f"{API}/requirement-templates/{t.json()['id']}").status_code == 200


def test_compute_three_mics_one_day(s):
    r = s.patch(f"{API}/events/{S['ev']}", json={"equipment": [{"equipment_id": S["mic"], "qty": 3}]})
    assert r.status_code == 200, r.text
    d, L = reqs(s)
    assert L["Pile AA"]["qty"] == 12 and L["Pile AA"]["auto_added"]
    assert L["Pied de micro"]["qty"] == 3 and not L["Pied de micro"]["accepted"] and not L["Pied de micro"]["auto_added"]
    assert d["totals"]["power_w"] == 45 and d["totals"]["sockets"] == 3
    assert any("Stock insuffisant" in a and "Pile AA" in a for a in d["alerts"])
    assert any("Technicien" in a for a in d["alerts"])
    ev = DB.events.find_one({"id": S["ev"]})
    assert ev["auto_equipment"] == [{"equipment_id": S["pile"], "qty": 12}]
    assert [l["equipment_id"] for l in ev["equipment"]] == [S["mic"]]


def test_two_days_recalc_and_adjusted_kept(s):
    assert s.patch(f"{API}/events/{S['ev']}", json={"end": "2028-03-06T18:00", "return_end": "2028-03-06T22:00"}).status_code == 200
    d, L = reqs(s)
    assert d["days"] == 2 and L["Pile AA"]["qty"] == 24
    r = s.patch(f"{API}/events/{S['ev']}/requirements", json={"key": L["Pile AA"]["key"], "adjusted_qty": 8})
    assert r.status_code == 200
    assert s.patch(f"{API}/events/{S['ev']}", json={"equipment": [{"equipment_id": S["mic"], "qty": 4}]}).status_code == 200
    d, L = reqs(s)
    assert L["Pile AA"]["qty"] == 8 and L["Pile AA"]["status"] == "adjusted" and L["Pile AA"]["computed_qty"] == 32
    assert not any("Stock insuffisant" in a for a in d["alerts"])
    assert DB.events.find_one({"id": S["ev"]})["auto_equipment"] == [{"equipment_id": S["pile"], "qty": 8}]
    s.patch(f"{API}/events/{S['ev']}/requirements", json={"key": L["Pied de micro"]["key"], "accepted": True})
    assert {"equipment_id": S["pied"], "qty": 4} in DB.events.find_one({"id": S["ev"]})["auto_equipment"]


def test_auto_lines_reserved_when_confirmed(s):
    r = s.post(f"{API}/events/{S['ev']}/status", json={"status": "confirme"})
    assert r.status_code == 200, r.text
    o = s.get(f"{API}/events/{S['ev']}/origin").json()
    auto = [l for g in o["groups"] for l in g["lines"] if l["auto"]]
    assert {(l["equipment_id"], l["qty"]) for l in auto} == {(S["pile"], 8), (S["pied"], 4)}
    assert [l["equipment_id"] for l in o["lines"]] == [S["mic"]]
    items = s.get(f"{API}/equipment", params={"start": "2028-03-04T12:00", "end": "2028-03-05T12:00"}).json()["items"]
    pile = next(i for i in items if i["id"] == S["pile"])
    assert pile["reserved"] == 8 and pile["available"] == 2


def test_checklist_pdf_and_consumption(s):
    r = s.get(f"{API}/events/{S['ev']}/requirements/checklist")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    import pymupdf
    text = "".join(p.get_text() for p in pymupdf.open(stream=r.content, filetype="pdf"))
    assert "Micro HF" in text and "Pile AA" in text and "Pied de micro" in text
    base = len(pymupdf.open(stream=r.content, filetype="pdf"))
    r2 = s.get(f"{API}/events/{S['ev']}/requirements/checklist", params={"annex": "true"})
    assert len(pymupdf.open(stream=r2.content, filetype="pdf")) == base + 1
    _, L = reqs(s)
    r = s.patch(f"{API}/events/{S['ev']}/requirements", json={"key": L["Pile AA"]["key"], "checked_out": True, "used_qty": 4})
    assert r.status_code == 200, r.text
    assert DB.equipment.find_one({"id": S["pile"]})["qty_total"] == 6
    mv = DB.stock_movements.find_one({"org_id": QA, "product_id": S["pile"], "note": "Consommable utilisé"})
    assert mv["qty"] == -4 and mv["event_id"] == S["ev"]
    s.patch(f"{API}/events/{S['ev']}/requirements", json={"key": L["Pile AA"]["key"], "used_qty": 3})
    assert DB.equipment.find_one({"id": S["pile"]})["qty_total"] == 7


def test_quote_requirements_and_shared_docs(s):
    r = s.post(f"{API}/quotes/direct", json={"event_id": S["ev"], "lines": [{"label": "Micro HF", "qty": 2, "unit_price": 30, "vat": 20, "equipment_id": S["mic"]}]})
    assert r.status_code == 200, r.text
    qid = r.json()["id"]
    d = s.get(f"{API}/quotes/{qid}/requirements").json()
    L = {l["label"]: l for l in d["lines"]}
    assert L["Pile AA"]["qty"] == 16 and d["totals"]["power_w"] == 30
    docs = s.get(f"{API}/quotes/{qid}/product-documents").json()
    assert [x["id"] for x in docs] == [S["doc_client"]] and not docs[0]["selected"]
    r = s.put(f"{API}/quotes/{qid}/product-documents", json={"doc_ids": [S["doc_client"], S["doc_interne"]]})
    assert r.json()["doc_ids"] == [S["doc_client"]]
    token = s.post(f"{API}/quotes/{qid}/share").json()["token"]
    pub = requests.get(f"{API}/public/quotes/{token}").json()
    assert [x["id"] for x in pub["documents"]] == [S["doc_client"]]
    assert "Pile AA" not in str(pub.get("lines")) + str(pub.get("rows"))
    assert requests.get(f"{API}/public/quotes/{token}/documents/{S['doc_client']}").content.startswith(b"%PDF")
    assert requests.get(f"{API}/public/quotes/{token}/documents/{S['doc_interne']}").status_code == 404
    s.patch(f"{API}/product-documents/{S['doc_client']}", json={"visibility": "interne"})
    assert requests.get(f"{API}/public/quotes/{token}/documents/{S['doc_client']}").status_code == 404
