"""Iter 58 — PDF de devis : flux continu, aucune section en double, validité, mentions, titre traduisible (QA)."""
import os
import uuid

import pymupdf
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

from tests.test_iter54_dj_tab_roadmap import BASE, sess

load_dotenv("/app/backend/.env")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
TAG = "TEST_M58_" + uuid.uuid4().hex[:5]


def test_pdf_and_titles():
    a = sess("admin")
    ok = lambda r: (r.status_code < 300 or pytest.fail(f"{r.status_code} {r.text}"), r.json())[1]  # noqa: E731
    v = ok(a.post(f"{BASE}/api/venues", json={"name": f"{TAG} Domaine", "city": "Nîmes"}))
    ev = ok(a.post(f"{BASE}/api/events", json={"title": f"Mariage {TAG}", "start": "2028-07-10T15:00", "end": "2028-07-11T02:00", "venue_id": v["id"]}))
    try:
        q = ok(a.post(f"{BASE}/api/events/{ev['id']}/quotes"))
        lines = [{"label": "Sonorisation", "description": "Enceintes et régie", "qty": 1, "unit_price": 800, "vat": 20}, {"label": "Éclairage", "qty": 2, "unit_price": 100, "vat": 20}]
        DB.quotes.update_one({"id": q["id"]}, {"$set": {"lines": lines, "blocks": [], "total_ht": 1000, "total_vat": 200, "total_ttc": 1200, "vat_breakdown": [{"rate": 20, "ht": 1000, "vat": 200}], "deposit_percent": 50,
                                                        "date": "2026-11-23", "valid_until": "2026-10-02", "notes": "Réf. Odoo S01075 — devis du 2026-09-17\nMerci de votre confiance"}})

        def pdf():
            r = a.get(f"{BASE}/api/quotes/{q['id']}/pdf")
            assert r.status_code == 200, r.text
            d = pymupdf.open(stream=r.content, filetype="pdf")
            return len(d), " ".join("".join(p.get_text() for p in d).split()), r.content
        n, t, raw = pdf()
        open("/tmp/qa-quote-fr.pdf", "wb").write(raw)
        assert n <= 2 and t.count("Conditions de paiement") == 1 and t.count("Bon pour accord") == 2 and t.count("Acompte") == 1  # titre + mention du cadre
        assert "Réf. Odoo" not in t and "Merci de votre confiance" in t and "23/12/2026" in t and "02/10/2026" not in t
        assert f"{TAG} Domaine, Nîmes" in t and "J-15 avant l'événement" in t and "Page 1 / " in t and "même jour" not in t and "[" not in t
        w = [x for x in ok(a.get(f"{BASE}/api/quotes/{q['id']}/translation-check"))["warnings"] if "CGV" not in x]
        assert len(w) == 1 and "antérieure" in w[0]
        # titre traduit : en-US
        tv = ok(a.put(f"{BASE}/api/events/{ev['id']}/title-translations", json={"lang": "en-US", "title": f"{TAG}'s Wedding"}))
        assert not next(x for x in tv["languages"] if x["code"] == "en-US")["stale"]
        DB.quotes.update_one({"id": q["id"]}, {"$set": {"language": "en-US", "valid_until": "2026-12-30"}})
        n, t, _ = pdf()
        assert n <= 2 and f"{TAG}'s Wedding" in t and f"Mariage {TAG}" not in t and t.count("Payment terms") == 1 and "Approved and agreed" in t and "Total incl. VAT" in t
        tk = ok(a.post(f"{BASE}/api/quotes/{q['id']}/share"))["token"]
        assert requests.get(f"{BASE}/api/public/quotes/{tk}").json()["event_title"] == f"{TAG}'s Wedding"
        assert ok(a.get(f"{BASE}/api/quotes/{q['id']}"))["event_title"] == f"Mariage {TAG}"  # interne : français
        # espagnol absent : alerte + repli anglais
        DB.quotes.update_one({"id": q["id"]}, {"$set": {"language": "es-ES"}})
        w = [x for x in ok(a.get(f"{BASE}/api/quotes/{q['id']}/translation-check"))["warnings"] if "CGV" not in x]
        assert any("Español" in x or "es" in x.lower() for x in w) and f"{TAG}'s Wedding" in w[0]
        assert f"{TAG}'s Wedding" in pdf()[1]
        ok(a.put(f"{BASE}/api/quotes/{q['id']}/title-translations", json={"lang": "es-ES", "title": f"Boda {TAG}"}))
        assert f"Boda {TAG}" in pdf()[1] and [x for x in ok(a.get(f"{BASE}/api/quotes/{q['id']}/translation-check"))["warnings"] if "CGV" not in x] == []
        # titre français modifié : à revoir
        ok(a.patch(f"{BASE}/api/events/{ev['id']}", json={"title": f"Mariage {TAG} bis"}))
        assert next(x for x in ok(a.get(f"{BASE}/api/events/{ev['id']}/title-translations"))["languages"] if x["code"] == "en-US")["stale"]
        assert sess("technicien").put(f"{BASE}/api/events/{ev['id']}/title-translations", json={"lang": "en-US", "title": "x"}).status_code in (401, 403)
    finally:
        a.delete(f"{BASE}/api/events/{ev['id']}")
        a.delete(f"{BASE}/api/venues/{v['id']}")
        DB.quotes.update_many({"event_id": ev["id"]}, {"$set": {"active": False, "status": "remplace"}})
