"""Iter 60 — Devis sans mentions légales, CGV FR / EN jointes selon la langue (QA)."""
import io
import os

import pymupdf
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

from tests.test_iter54_dj_tab_roadmap import BASE, sess

load_dotenv("/app/backend/.env")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
GONE = ["SARL au capital", "RCS Montpellier", "APE", "PLATESV", "médiateur", "mediator", "CM2C", "pénalités", "penalties", "40 €", "€40", "Licence", "licence"]
KEYS = ["siret", "terms", "terms_en", "terms_file_fr", "terms_file_en", "terms_annex", "legal_form_capital", "rcs", "ape", "licence", "mediator"]


def test_cgv():
    a = sess("admin")
    ok = lambda r: (r.status_code < 300 or pytest.fail(f"{r.status_code} {r.text}"), r.json())[1]  # noqa: E731
    org = DB.orgs.find_one({"slug": "qa-sandbox"})
    DB.orgs.update_one({"id": org["id"]}, {"$set": {"terms": "CGV FR TEXTE", "terms_en": "", "terms_annex": True, "siret": "91849423800010", "legal_form_capital": "SARL au capital de 1 000 €", "rcs": "RCS Montpellier 918 494 238", "ape": "9001Z", "licence": "PLATESV-D-2022-005735", "mediator": "CM2C"},
                                               "$unset": {"terms_file_fr": "", "terms_file_en": ""}})
    ev = ok(a.post(f"{BASE}/api/events", json={"title": "TEST_M60 ev", "start": "2028-08-10T15:00", "end": "2028-08-11T02:00"}))
    try:
        q = ok(a.post(f"{BASE}/api/events/{ev['id']}/quotes"))
        DB.quotes.update_one({"id": q["id"]}, {"$set": {"lines": [{"label": "Sonorisation", "qty": 1, "unit_price": 800, "vat": 20}], "blocks": [], "total_ht": 800, "total_vat": 160, "total_ttc": 960, "vat_breakdown": [{"rate": 20, "ht": 800, "vat": 160}]}})
        tok = ok(a.post(f"{BASE}/api/quotes/{q['id']}/share"))["token"]

        def text(lang):
            DB.quotes.update_one({"id": q["id"]}, {"$set": {"language": lang}})
            r = requests.get(f"{BASE}/api/public/quotes/{tok}/pdf")
            assert r.status_code == 200, r.text
            open(f"/tmp/cgv-{lang}.pdf", "wb").write(r.content)
            return " ".join("".join(p.get_text() for p in pymupdf.open(stream=r.content, filetype="pdf")).split())
        warn = lambda: [w for w in ok(a.get(f"{BASE}/api/quotes/{q['id']}/translation-check"))["warnings"] if "CGV" in w]  # noqa: E731
        fr = text("fr-FR")
        assert "CGV FR TEXTE" in fr and "SIRET" in fr and "Page 1 / " in fr and not [g for g in GONE if g in fr] and warn() == []
        en = text("en-US")
        assert "CGV FR TEXTE" not in en and not [g for g in GONE if g in en] and len(warn()) == 1 and "anglaise" in warn()[0]
        d = pymupdf.open(); d.new_page().insert_text((72, 72), "ENGLISH TERMS PDF")
        r = a.post(f"{BASE}/api/org/terms-file?lang=en", files={"file": ("terms-en.pdf", io.BytesIO(d.tobytes()), "application/pdf")}, headers={"Content-Type": None})
        assert r.status_code == 200, r.text
        en = text("en-US")
        assert "ENGLISH TERMS PDF" in en and "CGV FR TEXTE" not in en and warn() == [] and "ENGLISH TERMS PDF" in text("es-ES")
        pub = requests.get(f"{BASE}/api/public/quotes/{tok}").json()
        assert pub["terms"]["url"] and requests.get(BASE + pub["terms"]["url"]).content[:4] == b"%PDF"
        fr = text("fr-FR")
        assert "CGV FR TEXTE" in fr and "ENGLISH TERMS PDF" not in fr and requests.get(f"{BASE}/api/public/quotes/{tok}").json()["terms"] == {"text": "CGV FR TEXTE", "url": ""}
        DB.orgs.update_one({"id": org["id"]}, {"$set": {"terms_annex": False}})
        assert "CGV FR TEXTE" not in text("fr-FR")
        assert sess("commercial").post(f"{BASE}/api/org/terms-file?lang=fr", files={"file": ("x.pdf", io.BytesIO(d.tobytes()), "application/pdf")}, headers={"Content-Type": None}).status_code == 403
    finally:
        a.delete(f"{BASE}/api/events/{ev['id']}")
        DB.quotes.update_many({"event_id": ev["id"]}, {"$set": {"active": False, "status": "remplace"}})
        DB.orgs.update_one({"id": org["id"]}, {"$set": {k: org[k] for k in KEYS if k in org}, "$unset": {k: "" for k in KEYS if k not in org}})
