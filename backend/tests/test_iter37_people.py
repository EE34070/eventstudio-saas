"""Iter 37 — personnes d'une structure + métiers. QA uniquement, données TEST_M37 créées puis supprimées."""
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
S = {}


def sess(role="admin"):
    x = requests.Session()
    x.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip().splitlines()[-1]
    return x


@pytest.fixture(scope="module")
def s():
    x = sess()
    yield x
    cids = [c["id"] for c in DB.contacts.find({"org_id": QA, "last_name": {"$regex": f"^TEST_M37 {RUN}"}})]
    DB.events.delete_many({"org_id": QA, "title": f"TEST_M37 {RUN}"})
    DB.conversations.delete_many({"org_id": QA, "subject": f"TEST_M37 {RUN}"})
    DB.contact_people.delete_many({"org_id": QA, "contact_id": {"$in": cids}})
    DB.provider_profiles.delete_many({"org_id": QA, "contact_id": {"$in": cids}})
    DB.contacts.delete_many({"org_id": QA, "id": {"$in": cids}})


def test_people_primary_cc_search_duplicate(s):
    p = s.post(f"{API}/providers", json={"first_name": "Manon", "last_name": f"TEST_M37 {RUN}", "categories": ["wedding_planner"]}).json()
    S["c"], S["prov"] = cid, p["id"] = p["contact_id"], p["id"]
    r = s.post(f"{API}/contacts/{cid}/people", json={"first_name": "Manon", "last_name": "Gérante", "role_label": "Gérant·e"})
    assert r.status_code == 200, r.text
    mail = f"julie{RUN}@example.com"
    r = s.post(f"{API}/contacts/{cid}/people", json={"first_name": f"Julie{RUN}", "last_name": "Martin", "role_label": "Assistant·e", "email": mail, "cc_by_default": True}).json()
    manon, julie = r["people"]
    S["manon"], S["julie"], S["mail"] = manon, julie, mail
    assert manon["is_primary"] and not julie["is_primary"] and julie["cc_by_default"] and "Assistant·e" in r["roles"]
    hit = s.get(f"{API}/contacts", params={"q": f"Julie{RUN}"}).json()
    assert [h["id"] for h in hit] == [cid] and "Assistant·e" in hit[0]["matched_people"][0]
    assert s.post(f"{API}/contacts/{cid}/people", json={"last_name": "X", "role_label": "Autre", "email": mail}).status_code == 409


def test_event_interlocutor_and_stats(s):
    cid = S["c"]
    client = s.post(f"{API}/contacts", json={"first_name": "Léa", "last_name": f"TEST_M37 {RUN} cliente"}).json()["id"]
    r = s.post(f"{API}/events", json={"title": f"TEST_M37 {RUN}", "start": "2031-06-14T16:00", "end": "2031-06-15T02:00", "client_id": client, "planner_contact_id": cid, "planner_person_id": S["julie"]["id"]})
    assert r.status_code == 200, r.text
    S["ev"] = eid = r.json()["id"]
    pl = s.get(f"{API}/events/{eid}").json()["planner"]
    assert pl["person"]["id"] == S["julie"]["id"] and pl["cc"] == []
    assert s.patch(f"{API}/events/{eid}", json={"planner_person_id": S["manon"]["id"]}).status_code == 200
    pl = s.get(f"{API}/events/{eid}").json()["planner"]
    assert pl["person"]["id"] == S["manon"]["id"] and [p["id"] for p in pl["cc"]] == [S["julie"]["id"]]
    assert DB.event_person_history.count_documents({"org_id": QA, "event_id": eid}) == 1
    assert s.patch(f"{API}/events/{eid}", json={"planner_person_id": str(uuid.uuid4())}).status_code == 400
    s.patch(f"{API}/events/{eid}", json={"planner_person_id": S["julie"]["id"]})
    rows = s.get(f"{API}/providers/{S['prov']}/events").json()
    assert f"Julie{RUN} Martin" in str(rows)
    j = {k: S["julie"][k] for k in ("first_name", "last_name", "role_label", "email", "cc_by_default")}
    assert s.put(f"{API}/contact-people/{S['julie']['id']}", json={**j, "active": False}).status_code == 200
    assert S["julie"]["id"] not in [p["id"] for p in s.get(f"{API}/contacts/{cid}/people").json()["people"] if p["active"]]
    assert s.get(f"{API}/events/{eid}").json()["planner"]["person"]["id"] == S["julie"]["id"]
    DB.event_person_history.delete_many({"org_id": QA, "event_id": eid})


def test_message_attached_to_structure(s):
    import asyncio
    import sys
    sys.path.insert(0, "/app/backend")
    s.put(f"{API}/contact-people/{S['julie']['id']}", json={**{k: S["julie"][k] for k in ("first_name", "last_name", "role_label", "email")}, "active": True})
    conv = str(uuid.uuid4())
    DB.conversations.insert_one({"id": conv, "org_id": QA, "channel": "gmail", "subject": f"TEST_M37 {RUN}", "contact_id": None, "event_id": None, "counterpart": {"email": S["mail"]}, "deleted_at": None})

    async def run():
        from motor.motor_asyncio import AsyncIOMotorClient
        import messaging_core as mc
        mc.db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        await mc.link_conv(conv)
    asyncio.run(run())
    c = DB.conversations.find_one({"id": conv})
    assert c["contact_id"] == S["c"] and "Assistant·e" in c["person_name"]


def test_categories_and_rights(s):
    cats = [c["label"] for c in s.get(f"{API}/provider-categories").json()]
    assert cats[:12] == ["Wedding planner", "Traiteur", "Photographe", "Location mobilier / vaisselle", "DJ", "Technicien polyvalent", "Manutentionnaire", "Fournisseur son & lumière", "Saxophoniste", "Violoniste", "Percussionniste", "Autre"]
    assert s.put(f"{API}/contacts/{S['c']}/categories", json={"categories": ["wedding_planner", "traiteur"]}).json()["categories"] == ["wedding_planner", "traiteur"]
    assert {k["key"] for k in s.get(f"{API}/contacts/{S['c']}").json()["categories"]} == {"wedding_planner", "traiteur"}
    assert s.put(f"{API}/contacts/{S['c']}/categories", json={"categories": ["zzz"]}).status_code == 400
    t = sess("technicien")
    assert t.get(f"{API}/contacts/{S['c']}/people").status_code == 403 and requests.get(f"{API}/contact-roles").status_code == 401
