"""Iter 18 — PROMPT_DEVIS §3 / §5 / §6 / §7 (pages, versions destinataires, signature OTP, V2). QA sandbox only.
Real e-mails: 2, both to contact@exclusivity-events.com (signature request + OTP code)."""
import hashlib
import os

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
from pymongo import MongoClient  # noqa: E402

from conftest import API  # noqa: E402
from test_iter17_quote_blocks import RUN, _contact, _created, _direct, _venue, sess  # noqa: E402,F401

MONGO = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
ALLOWED = "contact@exclusivity-events.com"
S = {}


@pytest.fixture(scope="module", autouse=True)
def _clean():
    yield
    s = sess("admin")
    for k in ("quotes", "events", "venues", "contacts"):
        for i in _created[k]:
            s.delete(f"{API}/{k}/{i}")
    qa = MONGO.orgs.find_one({"slug": "qa-sandbox"})["id"]
    MONGO.quote_views.delete_many({"org_id": qa, "quote_id": {"$in": _created["quotes"]}})
    MONGO.document_pages.delete_many({"org_id": qa, "name": f"TEST_PDi18_Garde_{RUN}"})


def _tree(price=100):
    return {"blocks": [{"id": "a" + RUN, "type": "section", "title": "Cérémonie", "space_id": S.get("space", "")},
                       {"id": "b" + RUN, "parent_id": "a" + RUN, "type": "line", "label": "Enceinte", "qty": 2, "unit_price": price, "vat": 20},
                       {"id": "c" + RUN, "type": "section", "title": "Cocktail"},
                       {"id": "d" + RUN, "parent_id": "c" + RUN, "type": "line", "label": "Micro HF", "qty": 1, "unit_price": 50, "vat": 20}],
            "price_display": "detailed", "deposit_percent": 30}


class TestPagesAndViews:
    def test_library_defaults_and_crud(self):
        s = sess("admin")
        d = s.get(f"{API}/document-pages").json()
        assert d["pages"] and "client.nom" in d["fields"]
        assert any(b["is_default"] for b in s.get(f"{API}/brand-templates").json())
        r = s.post(f"{API}/document-pages", json={"name": f"TEST_PDi18_Garde_{RUN}", "kind": "header", "default_on": True,
                                                  "blocks_fr": [{"id": "1", "type": "title", "text": "Bonjour {client.nom}"}],
                                                  "blocks_en": [{"id": "1", "type": "title", "text": "Welcome {client.nom} — {devis.numero} — {lieu.nom}"}]})
        assert r.status_code == 200, r.text
        S["page"] = r.json()["id"]
        assert sess("technicien").get(f"{API}/document-pages").status_code == 403

    def test_cover_page_en_with_fields_filled(self):
        s = sess("admin")
        v = _venue(s, "DocVen")
        sp = s.post(f"{API}/venues/{v['id']}/spaces", json={"name": "Le Temple"}).json()
        MONGO.venues.update_one({"id": v["id"], "sections.id": sp["id"]}, {"$set": {"sections.$.power": "2 x 16 A"}})
        S.update(venue=v, space=sp["id"])
        c = _contact(s)
        MONGO.contacts.update_one({"id": c["id"]}, {"$set": {"language": "en-US"}})
        q = _direct(s, v["id"], c["id"], [{"label": "Base", "qty": 1, "unit_price": 100, "vat": 20}])
        MONGO.quotes.update_one({"id": q["id"]}, {"$set": {"language": "en-US"}})
        assert s.put(f"{API}/quotes/{q['id']}/structure", json=_tree()).status_code == 200
        S["q_en"] = q
        assert s.get(f"{API}/quotes/{q['id']}/pages").json()["header"][0]["enabled"] is False  # pages désactivées par défaut
        assert s.put(f"{API}/quotes/{q['id']}/pages", json={"header": [{"template_id": S["page"], "enabled": True}], "closing": [{"template_id": x["template_id"], "enabled": True} for x in s.get(f"{API}/quotes/{q['id']}/pages").json()["closing"]]}).status_code == 200
        tok = s.post(f"{API}/quotes/{q['id']}/share").json()["token"]
        pub = requests.get(f"{API}/public/quotes/{tok}").json()
        titles = [b["text"] for p in pub["pages"]["header"] for b in p["blocks"] if b["type"] == "title"]
        mine = next(t for t in titles if t.startswith("Welcome"))
        assert "{" not in mine and q["number"] in mine and v["name"] in mine and pub["client_name"] in mine
        assert any(b["type"] == "schedule" and b["rows"] for p in pub["pages"]["closing"] for b in p["blocks"])
        pdf = requests.get(f"{API}/public/quotes/{tok}/pdf")
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    def test_page_override_and_uncheck_for_one_quote(self):
        s, q = sess("admin"), S["q_en"]
        d = s.get(f"{API}/quotes/{q['id']}/pages").json()
        header = [{"template_id": p["template_id"], "enabled": p["template_id"] == S["page"],
                   "override": [{"id": "o", "type": "title", "text": "Only here {devis.numero}"}] if p["template_id"] == S["page"] else None} for p in d["header"]]
        r = s.put(f"{API}/quotes/{q['id']}/pages", json={"brand_template_id": d["brand_template_id"], "header": header, "closing": []})
        assert r.status_code == 200, r.text
        tok = s.post(f"{API}/quotes/{q['id']}/share").json()["token"]
        pub = requests.get(f"{API}/public/quotes/{tok}").json()
        assert len(pub["pages"]["header"]) == 1 and pub["pages"]["header"][0]["blocks"][0]["text"] == f"Only here {q['number']}"
        assert pub["pages"]["closing"] == []
        tpl = next(p for p in s.get(f"{API}/document-pages").json()["pages"] if p["id"] == S["page"])
        assert tpl["blocks_en"][0]["text"].startswith("Welcome")

    def test_venue_view_has_no_amount_but_spaces_and_power(self):
        s, q = sess("admin"), S["q_en"]
        r = s.post(f"{API}/quotes/{q['id']}/views", json={"kind": "venue", "label": "Domaine"})
        assert r.status_code == 200, r.text
        tok = r.json()["token"]
        res = requests.get(f"{API}/public/quote-views/{tok}")
        assert res.status_code == 200, res.text
        d = res.json()
        assert d["no_prices"] and d["total_ttc"] is None and d["total_ht"] is None and d["vat_breakdown"] == [] and d["lines"] == []
        assert all("unit_price" not in r and "amount" not in r for r in d["rows"])
        assert not any(b["type"] == "schedule" for k in ("header", "closing") for p in d["pages"][k] for b in p["blocks"])
        for amount in ("250", "300", "100.0", "50.0"):
            assert amount not in res.text.replace(q["number"], "").replace(tok, "")
        assert d["spaces"] == [{"name": "Le Temple", "description": "", "power": "2 x 16 A", "notes": "", "indoor": "", "vehicle_access": ""}] or d["spaces"][0]["power"] == "2 x 16 A"
        assert d["sign"]["can"] is False
        pdf = requests.get(f"{API}/public/quote-views/{tok}/pdf")
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        assert requests.post(f"{API}/public/quotes/{tok}/sign/request").status_code == 404

    def test_provider_view_only_its_sections(self):
        s, q = sess("admin"), S["q_en"]
        tok = s.post(f"{API}/quotes/{q['id']}/views", json={"kind": "provider", "section_ids": ["c" + RUN], "price_display": "detailed"}).json()["token"]
        d = requests.get(f"{API}/public/quote-views/{tok}").json()
        labels = [r["label"] for r in d["rows"]]
        assert any("Micro HF" in x for x in labels) and not any("Enceinte" in x for x in labels) and d["no_prices"]

    def test_organizer_view_can_mask_prices(self):
        s, q = sess("admin"), S["q_en"]
        tok = s.post(f"{API}/quotes/{q['id']}/views", json={"kind": "organizer", "price_display": "total_only"}).json()["token"]
        d = requests.get(f"{API}/public/quote-views/{tok}").json()
        assert d["total_ttc"] == 300 and all("unit_price" not in r for r in d["rows"])


class TestSignatureAndVersions:
    def test_send_for_signature_then_viewed(self):
        s = sess("admin")
        c = _contact(s, email=ALLOWED)
        q = _direct(s, S["venue"]["id"], c["id"], [{"label": "Base", "qty": 1, "unit_price": 100, "vat": 20}])
        assert s.put(f"{API}/quotes/{q['id']}/structure", json=_tree()).status_code == 200
        o = s.post(f"{API}/crm/opportunities", json={"client_contact_id": c["id"], "title": f"TEST_PDi18_{RUN}"})
        assert o.status_code == 200, o.text
        assert s.post(f"{API}/crm/opportunities/{o.json()['id']}/quotes", json={"quote_id": q["id"]}).status_code == 200
        r = s.post(f"{API}/quotes/{q['id']}/signature")
        assert r.status_code == 200, r.text
        sig = r.json()["signature"]
        assert sig["provider"] == "otp" and sig["level"] == "simple" and len(sig["hash"]) == 64 and r.json()["status"] == "envoye"
        tok = s.post(f"{API}/quotes/{q['id']}/share").json()["token"]
        S.update(q=q, tok=tok, opp=o.json()["id"])
        assert requests.post(f"{API}/public/quotes/{tok}/viewed").status_code == 200
        assert s.get(f"{API}/quotes/{q['id']}").json()["status"] == "vu"
        assert requests.get(f"{API}/public/quotes/{tok}").json()["sign"]["can"] is True

    def test_wrong_code_then_sign(self):
        s, q, tok = sess("admin"), S["q"], S["tok"]
        r = requests.post(f"{API}/public/quotes/{tok}/sign/request")
        assert r.status_code == 200, r.text
        assert "***@" in r.json()["to"]
        assert requests.post(f"{API}/public/quotes/{tok}/sign/request").status_code == 429
        salt = MONGO.quotes.find_one({"id": q["id"]})["signature"]["otp_salt"]
        MONGO.quotes.update_one({"id": q["id"]}, {"$set": {"signature.otp_hash": hashlib.sha256(f"{salt}:123456".encode()).hexdigest()}})
        body = {"code": "000000", "name": "Jean Test", "title": "Gérant", "accept": True}
        assert requests.post(f"{API}/public/quotes/{tok}/sign/confirm", json=body).status_code == 400
        assert requests.post(f"{API}/public/quotes/{tok}/sign/confirm", json={**body, "code": "123456", "accept": False}).status_code == 400
        r = requests.post(f"{API}/public/quotes/{tok}/sign/confirm", json={**body, "code": "123456"})
        assert r.status_code == 200, r.text
        assert r.json()["sign"]["status"] == "done" and r.json()["status"] == "accepte"
        d = s.get(f"{API}/quotes/{q['id']}").json()
        assert d["status"] == "accepte" and d["signature"]["signed_file"] and "otp_hash" not in d["signature"]
        pdf = s.get(f"{API}/quotes/{q['id']}/signed-pdf")
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        proof = s.get(f"{API}/quotes/{q['id']}/signature/proof").json()
        assert proof["signer_name"] == "Jean Test" and proof["hash"] == d["signature"]["hash"] and proof["level"] == "simple"
        assert s.get(f"{API}/crm/opportunities/{S['opp']}").json()["stage_key"] == "gagnee"
        assert any(q["number"] in t["title"] and "acompte" in t["title"] for t in s.get(f"{API}/tasks").json()["tasks"])
        assert requests.post(f"{API}/public/quotes/{tok}/sign/request").status_code == 409

    def test_edit_after_signature_requires_v2(self):
        s, q = sess("admin"), S["q"]
        assert s.put(f"{API}/quotes/{q['id']}/structure", json=_tree(120)).status_code == 400
        r = s.post(f"{API}/quotes/{q['id']}/new-version")
        assert r.status_code == 200, r.text
        v2 = r.json()
        _created["quotes"].append(v2["id"])
        assert v2["version"] == 2 and v2["status"] == "brouillon" and v2["number"] == q["number"] and "signature" not in v2 and s.post(f"{API}/quotes/{v2['id']}/share").json()["token"] != S["tok"]
        body = _tree(120)
        body["blocks"].append({"id": "e" + RUN, "parent_id": "c" + RUN, "type": "line", "label": "Lumière", "qty": 1, "unit_price": 10, "vat": 20})
        body["blocks"] = [b for b in body["blocks"] if b["id"] != "d" + RUN]
        assert s.put(f"{API}/quotes/{v2['id']}/structure", json=body).status_code == 200
        vs = s.get(f"{API}/quotes/{v2['id']}/versions").json()
        assert [(x["version"], x["active"]) for x in vs] == [(1, False), (2, True)] and vs[0]["signed"]
        cmp_ = s.get(f"{API}/quotes/{v2['id']}/compare", params={"other": q["id"]}).json()
        assert [x["label"] for x in cmp_["added"]] == ["Lumière"] and [x["label"] for x in cmp_["removed"]] == ["Micro HF"]
        assert cmp_["changed"][0]["before"]["unit_price"] == 100 and cmp_["changed"][0]["after"]["unit_price"] == 120
        assert cmp_["from"]["total_ttc"] == 300 and cmp_["to"]["total_ttc"] == 300 and cmp_["diff_ttc"] == 0
        old = requests.get(f"{API}/public/quotes/{S['tok']}").json()
        assert old["active"] is False and old["sign"]["can"] is False
        assert s.post(f"{API}/quotes/{q['id']}/signature").status_code == 400
        assert s.post(f"{API}/quotes/{q['id']}/new-version").status_code == 400

    def test_client_refusal_with_reason(self):
        s = sess("admin")
        c = _contact(s)
        q = _direct(s, S["venue"]["id"], c["id"], [{"label": "Base", "qty": 1, "unit_price": 100, "vat": 20}])
        assert s.post(f"{API}/quotes/{q['id']}/status", json={"status": "envoye"}).status_code == 200
        tok = s.post(f"{API}/quotes/{q['id']}/share").json()["token"]
        r = requests.post(f"{API}/public/quotes/{tok}/refuse", json={"reason": "Trop cher"})
        assert r.status_code == 200, r.text
        d = s.get(f"{API}/quotes/{q['id']}").json()
        assert d["status"] == "refuse" and d["refused_reason"] == "Trop cher"
        assert requests.post(f"{API}/public/quotes/{tok}/refuse", json={}).status_code == 409

    def test_no_price_blocks_signature(self):
        s = sess("admin")
        c = _contact(s)
        q = _direct(s, S["venue"]["id"], c["id"], [{"label": "Base", "qty": 1, "unit_price": 100, "vat": 20}])
        assert s.put(f"{API}/quotes/{q['id']}/structure", json={**_tree(), "price_display": "none"}).status_code == 200
        r = s.post(f"{API}/quotes/{q['id']}/signature")
        assert r.status_code == 400 and "Sans prix" in r.text
