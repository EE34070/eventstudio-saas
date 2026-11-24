"""Iter 30 — DJ partenaires (QA uniquement). Données propres au test (préfixe TEST_DJ30), supprimées à la fin même en cas d'échec. Appelle Claude pour la facture."""
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
DAY = "2027-06-12"
S = {}


def sess(role, *extra):
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", role, *extra], text=True).strip()
    return s


def dj(n):
    return sess("provider", f"qa_prov_{n}+clerk_test@example.com" if n == "a" else "qa_provider+clerk_test@example.com", S[f"c_{n}"])


@pytest.fixture(scope="module", autouse=True)
def data():
    ids = {k: str(uuid.uuid4()) for k in ("c_a", "c_b", "p_a", "p_b", "p_c", "c_c", "client", "ev", "venue", "quote")}
    S.update(ids)
    base = {"org_id": QA, "created_at": "2026-11-22T00:00:00+00:00", "test_tag": "TEST_DJ30"}
    for n in "abc":
        DB.contacts.insert_one({**base, "id": ids[f"c_{n}"], "first_name": "TEST_DJ30", "last_name": n, "email": f"test_dj30_{n}@example.com", "language": "fr-FR", "types": ["prestataire"]})
        DB.provider_profiles.insert_one({**base, "id": ids[f"p_{n}"], "contact_id": ids[f"c_{n}"], "name": f"TEST_DJ30 {n}", "categories": ["dj"], "status": "active", "base_rate": 400, "language": "fr-FR"})
    DB.contacts.insert_one({**base, "id": ids["client"], "first_name": "TEST_DJ30", "last_name": "Client", "email": "test_dj30_client@example.com", "language": "en-US", "types": ["client"]})
    DB.venues.insert_one({**base, "id": ids["venue"], "name": "TEST_DJ30 Domaine", "address": "12 chemin des Vignes", "zip": "30000", "city": "Nîmes", "access_instructions": "Parking prestataires au nord", "onsite_contacts": []})
    DB.events.insert_one({**base, "id": ids["ev"], "title": "TEST_DJ30 Wedding SECRETCLIENT", "type": "Mariage", "start": f"{DAY}T18:00", "end": "2027-06-13T03:00", "client_id": ids["client"], "client_contact_ids": [ids["client"]],
                          "venue_id": ids["venue"], "status": "confirme"})
    DB.quotes.insert_one({**base, "id": ids["quote"], "event_id": ids["ev"], "number": "TEST_DJ30", "status": "envoye", "valid_until": "2027-01-31", "lines": [], "blocks": [], "active": True})
    yield
    for c in ("contacts", "provider_profiles", "venues", "events", "quotes"):
        DB[c].delete_many({"org_id": QA, "test_tag": "TEST_DJ30"})
    ps = [ids["p_a"], ids["p_b"], ids["p_c"]]
    for c in ("dj_availability", "dj_calendar_meta", "dj_profiles", "dj_bookings", "dj_invoices", "missions"):
        DB[c].delete_many({"org_id": QA, "provider_id": {"$in": ps}})
    for c in ("dj_booking_logs", "dj_messages", "event_dj_criteria", "client_dj_shortlists"):
        DB[c].delete_many({"org_id": QA, "event_id": ids["ev"]})
    DB.tasks.delete_many({"org_id": QA, "source_ref": {"$regex": "^dj-"}})


def test_dj_marks_all_saturdays_and_admin_sees_them():
    a = dj("a")
    r = a.put(f"{API}/portal/provider/dj/availability", json={"weekday": 5, "start": "2027-06-01", "end": "2027-09-30", "state": "available"})
    assert r.status_code == 200 and r.json()["updated"] == 17
    b = dj("b")
    assert b.put(f"{API}/portal/provider/dj/availability", json={"dates": [DAY], "state": "external_busy", "private_title": "Mariage SECRETGIG"}).status_code == 200
    adm = sess("admin")
    g = adm.get(f"{API}/dj/availability", params={"start": "2027-06-01", "end": "2027-06-30"})
    row = {d["provider_id"]: d for d in g.json()["djs"]}
    assert row[S["p_a"]]["days"][DAY]["state"] == "available" and row[S["p_b"]]["days"][DAY]["state"] == "unavailable" and "SECRETGIG" not in g.text
    assert row[S["p_c"]]["stale"] is True
    found = {x["provider_id"]: x["state"] for x in adm.get(f"{API}/dj/search", params={"date": DAY}).json()}
    assert found[S["p_a"]] == "available" and found[S["p_c"]] == "unknown" and S["p_b"] not in found
    assert S["p_b"] in {x["provider_id"] for x in adm.get(f"{API}/dj/search", params={"date": DAY, "all": True}).json()}


def test_profiles_public_private_and_matching():
    adm = sess("admin")
    pub = {"stage_name": "DJ Alpha", "bio_fr": "Bio FR", "bio_en": "Bio EN", "mc_languages": [{"lang": "fr", "level": "fluent"}, {"lang": "en", "level": "fluent"}], "genres": [{"key": "pop", "level": 3}, {"key": "2000s", "level": 3}], "event_types": ["Mariage"]}
    assert adm.put(f"{API}/dj/profiles/{S['p_a']}", json={**pub, "vibe_tags": ["Chic & festif"], "tier": "premium", "internal_rating": 5, "internal_notes": "SECRETNOTE"}).status_code == 200
    assert adm.put(f"{API}/dj/profiles/{S['p_c']}", json={"stage_name": "DJ Charlie", "mc_languages": [{"lang": "fr", "level": "fluent"}, {"lang": "en", "level": "basic"}], "vibe_tags": ["Chic & festif"]}).status_code == 200
    mine = dj("a").get(f"{API}/portal/provider/dj/profile")
    assert mine.json()["stage_name"] == "DJ Alpha" and "SECRETNOTE" not in mine.text and "vibe_tags" not in mine.json() and "tier" not in mine.json()
    assert dj("a").put(f"{API}/portal/provider/dj/profile", json={**pub, "bio_fr": "Bio modifiée"}).status_code == 200
    assert DB.dj_profiles.find_one({"provider_id": S["p_a"]})["internal_notes"] == "SECRETNOTE"
    assert adm.put(f"{API}/events/{S['ev']}/dj/criteria", json={"languages": ["en"], "vibe_tags": ["Chic & festif"], "genres_love": ["pop", "2000s"], "tier": "premium"}).status_code == 200
    m = adm.get(f"{API}/events/{S['ev']}/dj/match").json()
    assert m["matches"][0]["provider_id"] == S["p_a"] and m["matches"][0]["score"] >= 85 and len(m["matches"][0]["lines"]) >= 7
    ex = {x["provider_id"]: x["excluded"] for x in m["excluded"]}
    assert S["p_c"] in ex and "EN" in ex[S["p_c"]][0] and S["p_b"] in ex


def test_option_accept_quote_signed_confirm_and_lift_other():
    adm, a = sess("admin"), dj("a")
    r = adm.post(f"{API}/events/{S['ev']}/dj/options", json={"provider_ids": [S["p_a"], S["p_c"]], "proposed_fee": 400, "start_time": "19:00", "end_time": "03:00"})
    assert r.status_code == 200, r.text
    ba, bc = r.json()
    assert ba["option_expires_at"] == "2027-01-31"
    home = a.get(f"{API}/portal/provider/dj/home")
    assert "SECRETCLIENT" not in home.text and "chemin des Vignes" not in home.text and home.json()["bookings"][0]["city"] == "Nîmes"
    assert a.post(f"{API}/portal/provider/dj/bookings/{ba['id']}/reply", json={"reply": "accept"}).status_code == 200
    assert DB.dj_availability.find_one({"provider_id": S["p_a"], "date": DAY})["state"] == "option"
    assert a.put(f"{API}/portal/provider/dj/availability", json={"dates": [DAY], "state": "unavailable"}).json()["updated"] == 0
    DB.quotes.update_one({"id": S["quote"]}, {"$set": {"status": "accepte"}})
    ev = adm.get(f"{API}/events/{S['ev']}/dj").json()
    assert ev["banner"]["kind"] == "confirm" and ev["banner"]["booking_id"] == ba["id"]
    d = adm.get(f"{API}/dj/bookings/{ba['id']}/confirmation-draft").json()
    assert "12 chemin des Vignes" in d["body"] and "400" in d["body"]
    c = adm.post(f"{API}/dj/bookings/{ba['id']}/confirm", json={})
    assert c.status_code == 200 and c.json()["status"] == "confirmed" and c.json()["mission_id"]
    assert DB.dj_availability.find_one({"provider_id": S["p_a"], "date": DAY})["state"] == "confirmed"
    assert DB.dj_bookings.find_one({"id": bc["id"]})["status"] == "option_lifted"
    msgs = list(DB.dj_messages.find({"event_id": S["ev"]}))
    assert {"option", "confirmation", "option_lifted"} <= {m["kind"] for m in msgs} and not any(m["sent"] for m in msgs)
    home = a.get(f"{API}/portal/provider/dj/home").json()["bookings"][0]
    assert "chemin des Vignes" in home["address"] and a.post(f"{API}/portal/provider/dj/bookings/{ba['id']}/ack").status_code == 200
    S.update(ba=ba["id"], bc=bc["id"])


def test_refused_quote_proposes_lift():
    adm = sess("admin")
    DB.dj_bookings.update_one({"id": S["bc"]}, {"$set": {"status": "option_requested"}})
    DB.quotes.update_one({"id": S["quote"]}, {"$set": {"status": "refuse"}})
    assert adm.get(f"{API}/events/{S['ev']}/dj").json()["banner"]["kind"] == "lift"
    assert adm.post(f"{API}/dj/bookings/{S['bc']}/lift", json={}).json()["status"] == "option_lifted"
    DB.quotes.update_one({"id": S["quote"]}, {"$set": {"status": "accepte"}})


def pdf(amount):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    b = io.BytesIO()
    c = canvas.Canvas(b, pagesize=A4)
    for i, line in enumerate(["DJ Alpha - SIRET 812 345 678 00021", "FACTURE N° F-2027-014 du 14/06/2027", "Client : EXCLUSIVITY EVENTS SARL, 530 rue Raymond Recouly, 34070 Montpellier, TVA FR40918494238",
                              "Prestation DJ du 12/06/2027", f"Total HT : {amount},00 EUR", "TVA non applicable, art. 293 B du CGI", f"Total TTC : {amount},00 EUR"]):
        c.drawString(60, 780 - 26 * i, line)
    c.save()
    return b.getvalue()


def test_invoice_mismatch_refuse_redeposit_validate_paid():
    adm, a = sess("admin"), dj("a")
    DB.orgs.find_one({"id": QA})
    assert a.post(f"{API}/portal/provider/dj/invoices", data={"booking_ids": S["ba"]}, files={"file": ("f.pdf", pdf(450), "application/pdf")}).status_code == 409
    DB.dj_bookings.update_one({"id": S["ba"]}, {"$set": {"status": "done"}})
    r = a.post(f"{API}/portal/provider/dj/invoices", data={"booking_ids": S["ba"]}, files={"file": ("f.pdf", pdf(450), "application/pdf")}, timeout=120)
    assert r.status_code == 200 and r.json()["match_status"] == "mismatch" and any("450" in w for w in r.json()["mismatch_reasons"]), r.text
    assert adm.post(f"{API}/dj/invoices/{r.json()['id']}/refuse", json={"reason": "Montant"}).json()["status"] == "refused"
    r2 = a.post(f"{API}/portal/provider/dj/invoices", data={"booking_ids": S["ba"]}, files={"file": ("f.pdf", pdf(400), "application/pdf")}, timeout=120)
    assert r2.status_code == 200 and not any("Montant" in w for w in r2.json()["mismatch_reasons"]), r2.text
    iid = r2.json()["id"]
    assert [i["id"] for i in adm.get(f"{API}/dj/invoices", params={"provider_id": S["p_a"]}).json()] == [iid]
    assert adm.post(f"{API}/dj/invoices/{iid}/paid", json={}).status_code == 409
    assert adm.post(f"{API}/dj/invoices/{iid}/validate", json={}).json()["status"] == "validated"
    assert adm.post(f"{API}/dj/invoices/{iid}/paid", json={"paid_at": "2027-06-20", "mode": "virement"}).json()["status"] == "paid"
    assert DB.dj_bookings.find_one({"id": S["ba"]})["status"] == "paid" and DB.dj_messages.find_one({"kind": "invoice_paid", "booking_id": S["ba"]})
    assert "F-2027-014" in adm.get(f"{API}/dj/invoices/export").text


def test_dj_cannot_read_another_dj_and_staff_guards():
    b = dj("b")
    assert b.post(f"{API}/portal/provider/dj/bookings/{S['ba']}/reply", json={"reply": "accept"}).status_code == 404
    assert b.post(f"{API}/portal/provider/dj/bookings/{S['ba']}/ack").status_code == 404
    assert b.post(f"{API}/portal/provider/dj/invoices", data={"booking_ids": S["ba"]}, files={"file": ("f.pdf", pdf(400), "application/pdf")}).status_code == 404
    home = b.get(f"{API}/portal/provider/dj/home")
    assert home.json()["bookings"] == [] and home.json()["invoices"] == [] and "DJ Alpha" not in home.text
    for p in ("/dj/profiles", "/dj/availability", "/dj/invoices", f"/events/{S['ev']}/dj", f"/events/{S['ev']}/dj/match"):
        assert b.get(API + p).status_code in (403, 404), p
        assert sess("technicien").get(API + p).status_code == 403, p


def test_client_sees_public_profiles_without_price_and_chooses():
    adm = sess("admin")
    assert adm.put(f"{API}/events/{S['ev']}/dj/shortlist", json={"provider_ids": [S["p_a"], S["p_c"]]}).status_code == 200
    c = sess("client", "qa_client+clerk_test@example.com", S["client"])
    r = c.get(f"{API}/portal/client/events/{S['ev']}/dj")
    assert r.status_code == 200, r.text
    d = r.json()["djs"]
    assert d[0]["stage_name"] == "DJ Alpha" and d[0]["bio"] == "Bio EN"
    for word in ("400", "SECRETNOTE", "base_rate", "fee", "tier", "vibe", "internal"):
        assert word not in r.text, word
    assert c.post(f"{API}/portal/client/events/{S['ev']}/dj/preference", json={"provider_id": S["p_b"]}).status_code == 404
    assert c.post(f"{API}/portal/client/events/{S['ev']}/dj/preference", json={"provider_id": S["p_a"]}).status_code == 200
    assert adm.get(f"{API}/events/{S['ev']}/dj").json()["shortlist"]["preferred_id"] == S["p_a"]
    other = DB.events.find_one({"org_id": QA, "client_contact_ids": {"$ne": S["client"]}}, {"id": 1})
    assert c.get(f"{API}/portal/client/events/{other['id']}/dj").status_code == 404
