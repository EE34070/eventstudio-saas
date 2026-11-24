"""Module Wedding planner : mariage, événements, espace des mariés, questionnaire Google Form, récapitulatif, repas.

Données fictives, sans Clerk, Google, Gmail ni IA réels.
"""
import pytest

import portal_core as po
import tenant_router as tenants
import wedding_core as wc
from conftest import ORG_A, ORG_B
from core import Ctx

API = "/api/wedding"


class FakeForms:
    def __init__(self, items, responses):
        self.items, self.responses = items, responses

    async def get_form(self, form_id):
        return {"info": {"title": "Questionnaire"}, "responderUri": "https://docs.google.com/forms/d/e/xyz/viewform", "items": self.items}

    async def list_responses(self, form_id):
        return self.responses


def page(t):
    return {"itemId": f"pb-{t}", "title": t, "pageBreakItem": {}}


def q(item, title, qid):
    return {"itemId": item, "title": title, "questionItem": {"question": {"questionId": qid, "textQuestion": {}}}}


def items(extra=()):
    return [page("Quelques questions pour mieux vous connaître"), q("i3", "Quelle est votre profession à chacun ?", "0a"),
            page("Votre mariage"), q("i11", "Comment imaginez-vous votre mariage ? Décrivez-moi l’ambiance", "0b"),
            q("i15", "Budget : budget total ; flexible ou plafond strict", "0c"), q("i16", "Nombre de personnes attendues ; nombre d'enfants", "0d"),
            q("i17", "Type de cérémonie", "0e"), page("Welcome dinner"), q("i22", "Nombre de personnes attendues", "0f"),
            page("Cérémonie"), q("i38", "Avez-vous défini le lieu de la cérémonie ?", "10"), *extra]


def answers(**kv):
    return {k: {"questionId": k, "textAnswers": {"answers": [{"value": v}]}} for k, v in kv.items()}


@pytest.fixture
async def setup(platform, monkeypatch):
    c = platform.control
    await c.orgs.update_one({"id": ORG_A}, {"$set": {"modules": ["dj", "wedding_planner"]}})
    invited = []

    async def fake_invite(org, contact, role, actor, base, event_title=""):
        invited.append(contact["email"])
        return {"user_id": f"u-{contact['id']}", "email": contact["email"], "sent": False, "link": "https://app/sign-in?__clerk_ticket=x"}

    async def fake_send(*a, **k):
        return False
    monkeypatch.setattr(po, "invite", fake_invite)
    monkeypatch.setattr(po, "send_tpl", fake_send)
    return invited


async def make(client, as_user):
    r = await client.post(f"{API}/weddings", headers=as_user("alice"), json={
        "partner1_email": "annie@example.com", "partner1_first_name": "Annie", "partner2_email": "patrick@example.com",
        "partner2_first_name": "Patrick", "lang": "en", "date": "2027-06-26"})
    assert r.status_code == 201, r.text
    return r.json()


async def couple_user(platform, w, uid="annie", i=0):
    await platform.control.users.insert_one({"user_id": uid, "email": f"{uid}@example.com", "name": uid, "org_id": ORG_A, "role": "client",
                                             "contact_id": w["contact_ids"][i], "env": "preview", "status": "active", "last_login_at": "2999",
                                             "terms_version": po.TERMS_VERSION})


def ctx_a():
    tenants.pin_org(ORG_A)
    return Ctx({"org_id": ORG_A, "role": "admin", "user_id": "alice", "name": "alice"})


async def test_creation_contacts_events_invitations(client, as_user, setup):
    w = await make(client, as_user)
    assert w["names"] == "Annie & Patrick" and [e["key"] for e in w["events"]] == ["wd", "dj", "br"]
    assert [e["date"] for e in w["events"]] == ["2027-06-25", "2027-06-26", "2027-06-27"] and all(e["event_id"] for e in w["events"])
    assert setup == ["annie@example.com", "patrick@example.com"] and w["invitations"][0]["link"]
    events = (await client.get("/api/events", headers=as_user("alice"))).json()
    titles = {e["title"] for e in (events if isinstance(events, list) else events.get("items", []))}
    assert "Annie & Patrick · Jour J" in titles
    cards = (await client.get(f"{API}/weddings", headers=as_user("alice"))).json()
    assert cards[0]["names"] == "Annie & Patrick" and cards[0]["vendors"] is None


async def test_module_gating_and_isolation(client, as_user, setup):
    w = await make(client, as_user)
    assert (await client.get(f"{API}/weddings", headers=as_user("bob"))).status_code == 403  # module non activé
    await tenants.CLUSTERS.control.orgs.update_one({"id": ORG_B}, {"$set": {"modules": ["wedding_planner"]}})
    assert (await client.get(f"{API}/weddings/{w['id']}", headers=as_user("bob"))).status_code == 404
    assert (await client.get(f"{API}/weddings", headers=as_user("bob"))).json() == []


async def test_couple_space_rights(client, as_user, setup, platform):
    w = await make(client, as_user)
    await client.put(f"{API}/weddings/{w['id']}/notes", json={"notes": "Secret interne"}, headers=as_user("alice"))
    await couple_user(platform, w)
    assert (await client.get(f"{API}/weddings", headers=as_user("annie"))).status_code == 404  # route interne
    home = (await client.get("/api/portal/wedding", headers=as_user("annie"))).json()
    assert home["names"] == "Annie & Patrick" and home["lang"] == "en" and "Secret" not in str(home)

    info = (await client.get("/api/portal/wedding/info", headers=as_user("annie"))).json()["info"]
    info.update(budget=48000, venue="Domaine des Oliviers", guests={"adults": 999, "kids": 0}, same_address=True)
    info["partners"][0]["address"] = "12 rue des Lilas, Lyon"
    r0 = await client.put("/api/portal/wedding/info", json=info, headers=as_user("annie"))
    assert r0.status_code == 200, r0.text
    full = (await client.get(f"{API}/weddings/{w['id']}", headers=as_user("alice"))).json()
    assert full["info"]["budget"] == 48000 and full["info"]["partners"][1]["address"] == "12 rue des Lilas, Lyon"
    assert full["info"]["guests"]["adults"] is None  # champ calculé, ignoré
    kinds = [n["kind"] for n in (await client.get(f"{API}/notifications", headers=as_user("alice"))).json()["items"]]
    assert "info_changed" in kinds

    rights = {"budget": False, "vendor_prices": True, "dday_planning": False, "documents": True, "edit_info": False}
    await client.put(f"{API}/weddings/{w['id']}/rights", json=rights, headers=as_user("alice"))
    assert (await client.get("/api/portal/wedding/info", headers=as_user("annie"))).json()["info"]["budget"] is None
    assert (await client.put("/api/portal/wedding/info", json=info, headers=as_user("annie"))).status_code == 403
    acc = (await client.get(f"{API}/weddings/{w['id']}/account", headers=as_user("alice"))).json()
    assert [p["status"] for p in acc["partners"]] == ["accepted", "not_invited"]


async def test_questionnaire_sync_prefill_adaptability(client, as_user, setup):
    w = await make(client, as_user)
    await client.put(f"{API}/settings", json={"form_url": "https://docs.google.com/forms/d/1nG9CCTxUqPafON1n-8PmzNgN4j_cgfPMjysauNq0sLg/edit"}, headers=as_user("alice"))
    fake = FakeForms(items(), [{"responseId": "r1", "respondentEmail": "Annie@example.com", "lastSubmittedTime": "2026-11-18T10:00:00Z",
                                "answers": answers(**{"0a": "Annie : architecte. Patrick : professeur.", "0b": "Champêtre chic", "0c": "48 000 $, plafond souple",
                                                      "0d": "112 personnes, 20 enfants", "0e": "Laïque", "0f": "60", "10": "Allée des oliviers"})}])
    r = await wc.sync(ctx_a(), fake)
    assert r["status"] == "ok" and r["new_questions"] == 0 and r["unassigned"] == 0
    full = (await client.get(f"{API}/weddings/{w['id']}", headers=as_user("alice"))).json()
    assert full["info"]["budget"] == 48000 and full["info"]["guests"] == {"adults": 92, "kids": 20}
    assert full["info"]["ceremony"]["type"] == "Laïque" and [p["job"] for p in full["info"]["partners"]] == ["Architecte", "Professeur"]
    qs = {x["id"]: x for x in (await client.get(f"{API}/questions", headers=as_user("alice"))).json()["questions"]}
    assert qs["i22"]["rubric"] == "wd" and qs["i16"]["rubric"] == "budget" and qs["i15"]["fiche_field"] == "budget"

    fake.responses[0].update(answers=answers(**{"0c": "52 000 $", "0e": "Laïque", "10": "Allée des oliviers"}), lastSubmittedTime="2026-11-20T10:00:00Z")
    fake.items = [i for i in items([q("new1", "Souhaitez-vous un feu d'artifice ?", "11")]) if i["itemId"] != "i11"]
    fake.items[1]["title"] = "Quelle est la profession de chacun de vous ?"
    r = await wc.sync(ctx_a(), fake)
    assert (r["new_questions"], r["deleted"], r["renamed"]) == (1, 1, 1)
    full = (await client.get(f"{API}/weddings/{w['id']}", headers=as_user("alice"))).json()
    assert full["info"]["budget"] == 48000  # la fiche reste la référence
    d = next(x for x in full["discrepancies"] if x["field"] == "budget")
    qs = {x["id"]: x for x in (await client.get(f"{API}/questions", headers=as_user("alice"))).json()["questions"]}
    assert qs["new1"]["status"] == "to_classify" and qs["new1"]["suggestion"] and qs["i11"]["status"] == "deleted"
    view = (await client.get(f"{API}/weddings/{w['id']}/questionnaire", headers=as_user("alice"))).json()
    assert [x for s in view["sections"] for x in s["questions"] if x["deleted"]][0]["answer"] == "Champêtre chic"
    assert (await client.patch(f"{API}/questions/new1", json={"rubric": "vendors"}, headers=as_user("alice"))).json()["status"] == "active"
    r = await client.post(f"{API}/weddings/{w['id']}/discrepancies/{d['id']}/resolve", json={"keep": "form"}, headers=as_user("alice"))
    assert r.json()["info"]["budget"] == 52000

    events = full["events"]
    for e in events:
        e["enabled"] = e["enabled"] and e["key"] != "wd"
    await client.put(f"{API}/weddings/{w['id']}/events", json={"events": events}, headers=as_user("alice"))
    view = (await client.get(f"{API}/weddings/{w['id']}/questionnaire", headers=as_user("alice"))).json()
    assert "Welcome dinner" not in [s["title"] for s in view["sections"]]


async def test_unassigned_response(client, as_user, setup):
    w = await make(client, as_user)
    await client.put(f"{API}/settings", json={"form_url": "https://docs.google.com/forms/d/1nG9CCTxUqPafON1n-8PmzNgN4j_cgfPMjysauNq0sLg/edit"}, headers=as_user("alice"))
    fake = FakeForms(items(), [{"responseId": "r9", "respondentEmail": "inconnu@example.com", "lastSubmittedTime": "2026-11-18T10:00:00Z",
                                "answers": answers(**{"0e": "Religieuse"})}])
    assert (await wc.sync(ctx_a(), fake))["unassigned"] == 1
    assert (await client.get(f"{API}/responses/unassigned", headers=as_user("alice"))).json()[0]["email"] == "inconnu@example.com"
    await client.put(f"{API}/responses/r9/assign", json={"wedding_id": w["id"]}, headers=as_user("alice"))
    assert (await client.get(f"{API}/weddings/{w['id']}", headers=as_user("alice"))).json()["info"]["ceremony"]["type"] == "Religieuse"


async def test_recap_keeps_manual_edits(client, as_user, setup):
    w = await make(client, as_user)
    await client.put(f"{API}/settings", json={"form_url": "https://docs.google.com/forms/d/1nG9CCTxUqPafON1n-8PmzNgN4j_cgfPMjysauNq0sLg/edit"}, headers=as_user("alice"))
    fake = FakeForms(items(), [{"responseId": "r1", "respondentEmail": "annie@example.com", "lastSubmittedTime": "2026-11-18T10:00:00Z",
                                "answers": answers(**{"0b": "Champêtre chic", "0e": "Laïque"})}])
    await wc.sync(ctx_a(), fake)
    rec = (await client.post(f"{API}/weddings/{w['id']}/recap/generate", headers=as_user("alice"))).json()
    assert "Champêtre chic" in next(x for x in rec["rubrics"] if x["key"] == "vision")["text"]
    await client.patch(f"{API}/weddings/{w['id']}/recap/vision", json={"text": "Ma version"}, headers=as_user("alice"))
    fake.responses[0].update(answers=answers(**{"0b": "Bohème lumineux", "0e": "Laïque"}), lastSubmittedTime="2026-11-19T10:00:00Z")
    await wc.sync(ctx_a(), fake)
    rec = (await client.post(f"{API}/weddings/{w['id']}/recap/generate", headers=as_user("alice"))).json()
    v = next(x for x in rec["rubrics"] if x["key"] == "vision")
    assert v["text"] == "Ma version" and "Bohème" in v["proposal"]
    r = await client.get(f"{API}/weddings/{w['id']}/recap/pdf", headers=as_user("alice"))
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


async def test_food_and_couple_view(client, as_user, setup, platform):
    w = await make(client, as_user)
    evs = w["events"]
    for e in evs:
        if e["key"] == "dj":
            e["estimate"] = 110
    await client.put(f"{API}/weddings/{w['id']}/events", json={"events": evs}, headers=as_user("alice"))
    body = {"vendor": "Maison Exemple", "formula": "Repas assis", "price": "95 $ par personne", "courses": [{"name": "Plat", "chosen": "Poulet", "options": []}],
            "included": [], "external": [{"name": "Vin rouge", "supplier": "Domaine Exemple", "per_guest": 0.4, "unit": "bottle"}], "notes": "Acompte en janvier"}
    r = (await client.put(f"{API}/weddings/{w['id']}/food/dj", json=body, headers=as_user("alice"))).json()
    assert r["guests"] == 110 and r["food"]["external"][0]["quantity"] == 44
    assert (await client.get(f"{API}/weddings/{w['id']}/food/dj/pdf", headers=as_user("alice"))).content[:4] == b"%PDF"
    await couple_user(platform, w)
    assert (await client.get("/api/portal/wedding/food/dj", headers=as_user("annie"))).status_code == 404  # pas encore ouvert
    await client.put(f"{API}/weddings/{w['id']}/open-sections", json={"open_sections": ["food"]}, headers=as_user("alice"))
    v = (await client.get("/api/portal/wedding/food/dj", headers=as_user("annie"))).json()
    assert v["food"]["vendor"] == "Maison Exemple" and "notes" not in v["food"] and v["food"]["price"]
    assert (await client.put(f"{API}/weddings/{w['id']}/open-sections", json={"open_sections": ["seating"]}, headers=as_user("alice"))).status_code == 422


async def test_events_rules(client, as_user, setup):
    w = await make(client, as_user)
    r = await client.put(f"{API}/weddings/{w['id']}/events", json={"events": [e for e in w["events"] if e["key"] != "dj"]}, headers=as_user("alice"))
    assert r.status_code == 422
    evs = w["events"] + [{"id": "x1", "key": "x1", "name": "After-party", "enabled": True, "date": "2027-06-27", "place": "Plage", "estimate": 40}]
    after = next(e for e in (await client.put(f"{API}/weddings/{w['id']}/events", json={"events": evs}, headers=as_user("alice"))).json()["events"] if e["key"] == "x1")
    assert after["event_id"] and after["guests"] == 40
    evs = [e for e in evs if e["key"] != "br"]
    w2 = (await client.put(f"{API}/weddings/{w['id']}/events", json={"events": evs}, headers=as_user("alice"))).json()
    assert "br" not in [e["key"] for e in w2["events"]]
