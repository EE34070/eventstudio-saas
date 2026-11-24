"""Module wedding_planner : mariages, invitations, espace des mariés, questionnaire, récapitulatif, repas.

Données fictives uniquement, aucun e-mail réel (pas de RESEND_API_KEY en test).
"""
import re

import pytest

from app.modules.wedding_planner import forms as F
from app.platform.mailer import SENT_IN_DEV

API = "/api/wedding-planner"


class FakeForms:
    def __init__(self, items, responses):
        self.items, self.responses = items, responses

    async def get_form(self, form_id):
        return {"formId": form_id, "info": {"title": "Questionnaire"}, "responderUri": "https://docs.google.com/forms/d/e/xyz/viewform",
                "items": self.items}

    async def list_responses(self, form_id):
        return self.responses


def page(title):
    return {"itemId": f"pb-{title}", "title": title, "pageBreakItem": {}}


def q(item_id, title, qid):
    return {"itemId": item_id, "title": title, "questionItem": {"question": {"questionId": qid, "textQuestion": {}}}}


def form_items(extra=()):
    return [
        page("Quelques questions pour mieux vous connaître"),
        q("i3", "Quelle est votre profession à chacun ?", "0a"),
        page("Votre mariage"),
        q("i11", "Comment imaginez-vous votre mariage ? Décrivez-moi l’ambiance, le style et l’expérience", "0b"),
        q("i15", "Budget : budget total ; flexible ou plafond strict", "0c"),
        q("i16", "Nombre de personnes attendues ; nombre d'enfants", "0d"),
        q("i17", "Type de cérémonie", "0e"),
        page("Welcome dinner"),
        q("i22", "Nombre de personnes attendues", "0f"),
        page("Cérémonie"),
        q("i38", "Avez-vous défini le lieu de la cérémonie ?", "10"),
        *extra,
    ]


def answers(**kv):
    return {qid: {"questionId": qid, "textAnswers": {"answers": [{"value": v}]}} for qid, v in kv.items()}


@pytest.fixture
async def wedding(client, as_user):
    SENT_IN_DEV.clear()
    r = await client.post(f"{API}/weddings", headers=as_user("alice"), json={
        "partner1_email": "annie@example.com", "partner1_first_name": "Annie",
        "partner2_email": "patrick@example.com", "partner2_first_name": "Patrick",
        "lang": "en", "date": "2027-06-26"})
    assert r.status_code == 201, r.text
    return r.json()


def token_from_mail(email):
    mail = next(m for m in SENT_IN_DEV if m["to"] == [email])
    return re.search(r"/invitation/([\w-]+)", mail["html"]).group(1)


async def join(client, as_user, user, email):
    r = await client.post("/api/invitations/accept", json={"token": token_from_mail(email)}, headers=as_user(user))
    assert r.status_code == 200, r.text


async def test_create_wedding_creates_contacts_events_and_invitations(client, as_user, wedding, seeded):
    assert wedding["names"] == "Annie & Patrick"
    assert [e["key"] for e in wedding["events"]] == ["wd", "dj", "br"]
    assert [e["date"] for e in wedding["events"]] == ["2027-06-25", "2027-06-26", "2027-06-27"]
    assert all(e["event_id"] for e in wedding["events"])  # visibles dans le module Événements du socle
    events = (await client.get("/api/events", headers=as_user("alice"))).json()
    assert {e["title"] for e in events} == {"Annie & Patrick · Welcome dinner", "Annie & Patrick · Jour J", "Annie & Patrick · Brunch"}
    contacts = (await client.get("/api/contacts", headers=as_user("alice"))).json()
    assert {c["email"] for c in contacts} == {"annie@example.com", "patrick@example.com"}
    assert {m["to"][0] for m in SENT_IN_DEV} == {"annie@example.com", "patrick@example.com"}
    assert "your wedding space" in SENT_IN_DEV[0]["subject"]  # langue du couple
    cards = (await client.get(f"{API}/weddings", headers=as_user("alice"))).json()
    assert cards[0]["names"] == "Annie & Patrick" and cards[0]["vendors"] is None


async def test_module_isolation(client, as_user, wedding):
    wid = wedding["id"]
    # Org B (Essentiel, sans module métier) : module bloqué
    assert (await client.get(f"{API}/weddings", headers=as_user("bob"))).status_code == 403
    # Org D (Entreprise) : le mariage d'une autre société n'existe pas pour elle
    assert (await client.get(f"{API}/weddings/{wid}", headers=as_user("dora"))).status_code == 404
    assert (await client.get(f"{API}/weddings", headers=as_user("dora"))).json() == []
    # Technicien de l'org A : pas de droit sur le module
    assert (await client.get(f"{API}/weddings", headers=as_user("tech"))).status_code == 403


async def test_couple_space_and_rights(client, as_user, wedding):
    wid = wedding["id"]
    await client.put(f"{API}/weddings/{wid}/notes", json={"notes": "Secret Manon"}, headers=as_user("alice"))
    await join(client, as_user, "annie", "annie@example.com")

    # Les mariés n'accèdent jamais aux routes internes
    assert (await client.get(f"{API}/weddings", headers=as_user("annie"))).status_code == 403
    assert (await client.get(f"{API}/weddings/{wid}/recap", headers=as_user("annie"))).status_code == 403

    home = (await client.get("/api/portal/wedding", headers=as_user("annie"))).json()
    assert home["names"] == "Annie & Patrick" and home["lang"] == "en"
    assert "notes" not in str(home) and "Secret" not in str(home)

    info = (await client.get("/api/portal/wedding/info", headers=as_user("annie"))).json()["info"]
    info["budget"] = 48000
    info["venue"] = "Domaine des Oliviers"
    info["guests"] = {"adults": 999, "kids": 0}  # champ calculé : ignoré
    info["partners"][0]["address"] = "12 rue des Lilas, Lyon"
    info["same_address"] = True
    r = await client.put("/api/portal/wedding/info", json=info, headers=as_user("annie"))
    assert r.status_code == 200
    w = (await client.get(f"{API}/weddings/{wid}", headers=as_user("alice"))).json()
    assert w["info"]["venue"] == "Domaine des Oliviers" and w["info"]["budget"] == 48000
    assert w["info"]["partners"][1]["address"] == "12 rue des Lilas, Lyon"  # « Même adresse »
    assert w["info"]["guests"]["adults"] is None
    notifs = (await client.get(f"{API}/notifications", headers=as_user("alice"))).json()
    kinds = [n["kind"] for n in notifs["items"]]
    assert "info_changed" in kinds and "invitation_accepted" in kinds

    # Droits : budget masqué, modification fermée
    rights = {"budget": False, "vendor_prices": True, "dday_planning": False, "documents": True, "edit_info": False}
    await client.put(f"{API}/weddings/{wid}/rights", json=rights, headers=as_user("alice"))
    assert (await client.get("/api/portal/wedding/info", headers=as_user("annie"))).json()["info"]["budget"] is None
    assert (await client.put("/api/portal/wedding/info", json=info, headers=as_user("annie"))).status_code == 403

    # Le partenaire qui n'a pas encore accepté n'a pas d'accès
    assert (await client.get("/api/portal/wedding", headers=as_user("patrick"))).status_code == 403
    account = (await client.get(f"{API}/weddings/{wid}/account", headers=as_user("alice"))).json()
    assert [p["status"] for p in account["partners"]] == ["accepted", "pending"]


async def test_invitation_cannot_be_reused(client, as_user, wedding):
    token = token_from_mail("annie@example.com")
    assert (await client.post("/api/invitations/accept", json={"token": token}, headers=as_user("annie"))).status_code == 200
    assert (await client.post("/api/invitations/accept", json={"token": token}, headers=as_user("mallory"))).status_code == 409
    assert (await client.post("/api/invitations/accept", json={"token": "faux"}, headers=as_user("mallory"))).status_code == 404
    # Un membre de l'équipe ne peut pas devenir « client » de sa propre organisation par erreur
    r = await client.post("/api/invitations/accept", json={"token": token_from_mail("patrick@example.com")},
                          headers=as_user("alice"))
    assert r.status_code == 409


async def test_questionnaire_sync_prefill_and_adaptability(client, as_user, wedding, seeded):
    wid = wedding["id"]
    await client.put(f"{API}/settings", json={"form_url": "https://docs.google.com/forms/d/1nG9CCTxUqPafON1n-8PmzNgN4j_cgfPMjysauNq0sLg/edit"},
                     headers=as_user("alice"))
    ctx = await _ctx(seeded, "org_a")
    fake = FakeForms(form_items(), [{
        "responseId": "r1", "respondentEmail": "Annie@example.com", "lastSubmittedTime": "2026-11-18T10:00:00Z",
        "answers": answers(**{"0a": "Annie : architecte. Patrick : professeur.", "0b": "Champêtre chic",
                              "0c": "48 000 $, plafond souple", "0d": "112 personnes, 20 enfants", "0e": "Laïque",
                              "0f": "60", "10": "Allée des oliviers"})}])
    res = await F.sync(ctx, fake)
    assert res["status"] == "ok" and res["new_questions"] == 0 and res["unassigned"] == 0

    w = (await client.get(f"{API}/weddings/{wid}", headers=as_user("alice"))).json()
    assert w["info"]["budget"] == 48000
    assert w["info"]["guests"] == {"adults": 92, "kids": 20}
    assert w["info"]["ceremony"]["type"] == "Laïque" and w["info"]["ceremony"]["place"] == "Allée des oliviers"
    assert [p["job"] for p in w["info"]["partners"]] == ["Architecte", "Professeur"]
    assert w["questionnaire"]["status"] == "submitted"

    qs = (await client.get(f"{API}/questions", headers=as_user("alice"))).json()["questions"]
    by_id = {x["id"]: x for x in qs}
    assert by_id["i22"]["rubric"] == "wd" and by_id["i16"]["rubric"] == "budget"  # même intitulé, sections différentes
    assert by_id["i15"]["fiche_field"] == "budget"

    view = (await client.get(f"{API}/weddings/{wid}/questionnaire", headers=as_user("alice"))).json()
    assert [s["title"] for s in view["sections"]][:2] == ["Quelques questions pour mieux vous connaître", "Votre mariage"]

    # La fiche est la référence : réponse différente → alerte, rien n'est écrasé
    fake.responses[0]["answers"] = answers(**{"0c": "52 000 $", "0e": "Laïque", "10": "Allée des oliviers"})
    fake.responses[0]["lastSubmittedTime"] = "2026-11-20T10:00:00Z"
    # Manon ajoute une question, renomme une autre, en supprime une
    fake.items = [i for i in form_items([q("new1", "Souhaitez-vous un feu d'artifice ?", "11")]) if i["itemId"] != "i11"]
    fake.items[1]["title"] = "Quelle est la profession de chacun de vous ?"
    res = await F.sync(ctx, fake)
    assert res["new_questions"] == 1 and res["deleted"] == 1 and res["renamed"] == 1

    w = (await client.get(f"{API}/weddings/{wid}", headers=as_user("alice"))).json()
    assert w["info"]["budget"] == 48000
    d = next(x for x in w["discrepancies"] if x["field"] == "budget")
    assert d["form_value"] == 52000

    qs = {x["id"]: x for x in (await client.get(f"{API}/questions", headers=as_user("alice"))).json()["questions"]}
    assert qs["new1"]["status"] == "to_classify" and qs["new1"]["suggestion"] == "ceremony"
    assert qs["i11"]["status"] == "deleted" and qs["i3"]["rubric"] == "couple"
    # Les anciennes réponses à la question supprimée restent consultables
    view = (await client.get(f"{API}/weddings/{wid}/questionnaire", headers=as_user("alice"))).json()
    deleted = [x for s in view["sections"] for x in s["questions"] if x["deleted"]]
    assert deleted and deleted[0]["answer"] == "Champêtre chic"

    # Classement en un clic, mémorisé pour tous les couples
    r = await client.patch(f"{API}/questions/new1", json={"rubric": "vendors"}, headers=as_user("alice"))
    assert r.json()["status"] == "active"

    # Résolution de la différence : on garde la valeur du formulaire
    r = await client.post(f"{API}/weddings/{wid}/discrepancies/{d['id']}/resolve", json={"keep": "form"}, headers=as_user("alice"))
    assert r.json()["info"]["budget"] == 52000 and not [x for x in r.json()["discrepancies"] if x["field"] == "budget"]

    # Welcome dinner désactivé : section masquée, réponses conservées
    events = w["events"]
    for e in events:
        if e["key"] == "wd":
            e["enabled"] = False
    await client.put(f"{API}/weddings/{wid}/events", json={"events": events}, headers=as_user("alice"))
    view = (await client.get(f"{API}/weddings/{wid}/questionnaire", headers=as_user("alice"))).json()
    assert "Welcome dinner" not in [s["title"] for s in view["sections"]]


async def test_unmatched_response_can_be_assigned(client, as_user, wedding, seeded):
    await client.put(f"{API}/settings", json={"form_id": "form123"}, headers=as_user("alice"))
    ctx = await _ctx(seeded, "org_a")
    fake = FakeForms(form_items(), [{"responseId": "r9", "respondentEmail": "inconnu@example.com",
                                     "lastSubmittedTime": "2026-11-18T10:00:00Z", "answers": answers(**{"0e": "Religieuse"})}])
    assert (await F.sync(ctx, fake))["unassigned"] == 1
    un = (await client.get(f"{API}/responses/unassigned", headers=as_user("alice"))).json()
    assert un[0]["email"] == "inconnu@example.com"
    await client.put(f"{API}/responses/r9/assign", json={"wedding_id": wedding["id"]}, headers=as_user("alice"))
    w = (await client.get(f"{API}/weddings/{wedding['id']}", headers=as_user("alice"))).json()
    assert w["info"]["ceremony"]["type"] == "Religieuse"


async def test_recap_keeps_manual_edits(client, as_user, wedding, seeded):
    wid = wedding["id"]
    await client.put(f"{API}/settings", json={"form_id": "form123"}, headers=as_user("alice"))
    ctx = await _ctx(seeded, "org_a")
    fake = FakeForms(form_items(), [{"responseId": "r1", "respondentEmail": "annie@example.com",
                                     "lastSubmittedTime": "2026-11-18T10:00:00Z",
                                     "answers": answers(**{"0b": "Champêtre chic", "0e": "Laïque"})}])
    await F.sync(ctx, fake)
    recap = (await client.post(f"{API}/weddings/{wid}/recap/generate", headers=as_user("alice"))).json()
    vision = next(x for x in recap["rubrics"] if x["key"] == "vision")
    assert "Champêtre chic" in vision["text"] and vision["source"] == "plain"
    await client.patch(f"{API}/weddings/{wid}/recap/vision", json={"text": "Ma version"}, headers=as_user("alice"))

    fake.responses[0]["answers"] = answers(**{"0b": "Bohème lumineux", "0e": "Laïque"})
    fake.responses[0]["lastSubmittedTime"] = "2026-11-19T10:00:00Z"
    await F.sync(ctx, fake)
    recap = (await client.post(f"{API}/weddings/{wid}/recap/generate", headers=as_user("alice"))).json()
    vision = next(x for x in recap["rubrics"] if x["key"] == "vision")
    assert vision["text"] == "Ma version" and "Bohème" in vision["proposal"]

    r = await client.get(f"{API}/weddings/{wid}/recap.pdf", headers=as_user("alice"))
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


async def test_food_and_drinks(client, as_user, wedding):
    wid = wedding["id"]
    events = wedding["events"]
    for e in events:
        if e["key"] == "dj":
            e["estimate"] = 110
    await client.put(f"{API}/weddings/{wid}/events", json={"events": events}, headers=as_user("alice"))
    body = {"vendor": "Maison Exemple Table", "formula": "Repas assis", "price": "95 $ par personne",
            "courses": [{"name": "Plat", "chosen": "Poulet rôti", "options": ["Poulet", "Risotto"]}],
            "included": [{"name": "Eau", "detail": "Pendant le repas"}],
            "external": [{"name": "Vin rouge", "supplier": "Domaine Exemple", "per_guest": 0.4, "unit": "bottle"}],
            "notes": "Acompte versé en janvier"}
    r = (await client.put(f"{API}/weddings/{wid}/food/dj", json=body, headers=as_user("alice"))).json()
    assert r["guests"] == 110 and r["food"]["external"][0]["quantity"] == 44
    assert (await client.get(f"{API}/weddings/{wid}/food/dj/pdf", headers=as_user("alice"))).content[:4] == b"%PDF"

    await join(client, as_user, "annie", "annie@example.com")
    assert (await client.get("/api/portal/wedding/food/dj", headers=as_user("annie"))).status_code == 404  # pas encore ouvert
    await client.put(f"{API}/weddings/{wid}/open-sections", json={"open_sections": ["food"]}, headers=as_user("alice"))
    couple = (await client.get("/api/portal/wedding/food/dj", headers=as_user("annie"))).json()
    assert couple["food"]["vendor"] == "Maison Exemple Table" and "notes" not in couple["food"]
    assert couple["food"]["price"] == "95 $ par personne"
    rights = {"budget": True, "vendor_prices": False, "dday_planning": False, "documents": True, "edit_info": True}
    await client.put(f"{API}/weddings/{wid}/rights", json=rights, headers=as_user("alice"))
    couple = (await client.get("/api/portal/wedding/food/dj", headers=as_user("annie"))).json()
    assert couple["food"]["price"] is None
    # Une rubrique pas encore construite ne peut pas être ouverte
    r = await client.put(f"{API}/weddings/{wid}/open-sections", json={"open_sections": ["seating"]}, headers=as_user("alice"))
    assert r.status_code == 422


async def test_events_rules(client, as_user, wedding):
    wid = wedding["id"]
    events = [e for e in wedding["events"] if e["key"] != "dj"]
    r = await client.put(f"{API}/weddings/{wid}/events", json={"events": events}, headers=as_user("alice"))
    assert r.status_code == 422
    events = wedding["events"] + [{"id": "x1", "key": "x1", "name": "After-party", "enabled": True,
                                   "date": "2027-06-27", "place": "Plage", "estimate": 40}]
    w = (await client.put(f"{API}/weddings/{wid}/events", json={"events": events}, headers=as_user("alice"))).json()
    after = next(e for e in w["events"] if e["key"] == "x1")
    assert after["event_id"] and after["guests"] == 40 and after["guests_source"] == "estimate"


async def _ctx(router, org_id):
    from app.workers.worker import system_context
    return await system_context(router, org_id)
