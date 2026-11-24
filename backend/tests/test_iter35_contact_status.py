"""Iter 35 — wedding planners dans Contacts et statuts par type. QA uniquement, données TEST_M35 créées puis supprimées."""
import asyncio
import os
import subprocess
import sys
import uuid

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
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
    cids = [c["id"] for c in DB.contacts.find({"org_id": QA, "last_name": {"$regex": f"^TEST_M35 {RUN}"}})]
    pids = [p["id"] for p in DB.provider_profiles.find({"org_id": QA, "contact_id": {"$in": cids}})]
    DB.dj_profiles.delete_many({"org_id": QA, "provider_id": {"$in": pids}})
    DB.provider_profiles.delete_many({"org_id": QA, "contact_id": {"$in": cids}})
    DB.contacts.delete_many({"org_id": QA, "id": {"$in": cids}})


def prov(s, name, cat):
    r = s.post(f"{API}/providers", json={"first_name": "Zoé", "last_name": f"TEST_M35 {RUN} {name}", "categories": [cat]})
    assert r.status_code == 200, r.text
    return r.json()


def test_wedding_planner_filter_badge_search(s):
    S["wp"], S["dj"] = prov(s, "wp", "wedding_planner"), prov(s, "dj", "dj")
    rows = s.get(f"{API}/contacts", params={"role": "wedding_planner"}).json()
    assert S["wp"]["contact_id"] in [r["id"] for r in rows] and all(r["is_wedding_planner"] for r in rows)
    assert S["dj"]["contact_id"] not in [r["id"] for r in rows]
    hit = s.get(f"{API}/contacts", params={"q": "planner"}).json()
    assert S["wp"]["contact_id"] in [r["id"] for r in hit] and S["dj"]["contact_id"] not in [r["id"] for r in hit]
    wp = next(r for r in rows if r["id"] == S["wp"]["contact_id"])
    assert wp["statuses"] == {"wedding_planner": "nouvelle_relation"} and wp["status_badges"][0]["label"] == "Nouvelle relation"
    ids = [r["id"] for r in s.get(f"{API}/contacts", params={"type": "prestataire", "exclude_wp": True}).json()]
    assert S["dj"]["contact_id"] in ids and S["wp"]["contact_id"] not in ids
    assert S["dj"]["contact_id"] in [r["id"] for r in s.get(f"{API}/contacts", params={"provider_category": "dj"}).json()]
    one = s.get(f"{API}/contacts/{S['wp']['contact_id']}").json()
    assert one["is_wedding_planner"] and one["provider_id"] == S["wp"]["id"] and one["planner_events"] == {"upcoming": 0, "past": 0}


def _put(s, cid, **kw):
    c = s.get(f"{API}/contacts/{cid}").json()
    body = {k: c.get(k) for k in ("kind", "first_name", "last_name", "company", "email", "phone", "city", "types", "language") if c.get(k) is not None}
    return s.put(f"{API}/contacts/{cid}", json={**body, **kw})


def test_status_lists_per_type(s):
    meta = s.get(f"{API}/contact-statuses").json()
    assert [x["label"] for x in meta["lists"]["prestataire"]] == ["À tester", "Partenaire actif", "Occasionnel", "Inactif", "Ne plus travailler avec"]
    assert [x["id"] for x in meta["lists"]["client"]][:2] == ["prospect", "client"]
    cid = S["dj"]["contact_id"]
    assert _put(s, cid, statuses={"prestataire": "prospect"}).status_code == 400
    r = _put(s, cid, statuses={"prestataire": "a_tester"})
    assert r.status_code == 200 and r.json()["statuses"] == {"prestataire": "a_tester"} and r.json()["status"] == ""
    r = _put(s, cid, types=["client", "prestataire"], statuses={"client": "client"})
    assert r.json()["statuses"] == {"client": "client", "prestataire": "a_tester"} and r.json()["status"] == "client"
    assert len(DB.contacts.find_one({"id": cid})["status_history"]) >= 2
    assert cid in [x["id"] for x in s.get(f"{API}/contacts", params={"status": "a_tester"}).json()]


def test_ne_plus_hidden_from_dj_tools(s):
    cid, pid = S["dj"]["contact_id"], S["dj"]["id"]
    day = "2031-06-07"
    ids = lambda **p: [r["provider_id"] for r in s.get(f"{API}/dj/search", params={"date": day, "all": True, **p}).json()]  # noqa: E731
    assert pid in ids()
    assert _put(s, cid, types=["prestataire"], statuses={"prestataire": "ne_plus"}).status_code == 200
    assert pid not in ids() and pid in ids(inactive=True)
    grid = s.get(f"{API}/dj/availability").json()["djs"]
    assert pid not in [r["provider_id"] for r in grid]


def test_migration_on_qa_contact_only(s):
    import migrations
    cid = str(uuid.uuid4())
    DB.contacts.insert_one({"id": cid, "org_id": QA, "kind": "particulier", "status": "prospect", "first_name": "", "last_name": f"TEST_M35 {RUN} legacy", "company": "", "email": "", "types": ["fournisseur"], "interactions": []})
    before = DB.contacts.count_documents({"org_id": {"$ne": QA}, "statuses": {"$exists": True}})

    async def run():
        from motor.motor_asyncio import AsyncIOMotorClient
        migrations.db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        import contact_status
        contact_status.db = migrations.db
        await migrations.m012(QA)
    asyncio.run(run())
    c = DB.contacts.find_one({"id": cid})
    assert c["statuses"] == {"fournisseur": "actif"} and c["status"] == "" and c["status_history"][0]["from"] == "prospect"
    assert DB.contacts.count_documents({"org_id": QA, "types": {"$in": ["prestataire", "lieu", "fournisseur"]}, "types": {"$ne": "client"}, "status": {"$in": ["prospect", "client"]}}) == 0  # noqa: F601
    assert DB.contacts.count_documents({"org_id": {"$ne": QA}, "statuses": {"$exists": True}}) == before
    assert DB.contacts.count_documents({"org_id": QA, "types": ["client"], "statuses": {"$exists": True}, "status_history.by": "Migration"}) == 0


def test_rights(s):
    t = sess("technicien")
    assert t.put(f"{API}/contact-statuses/client", json={"items": [{"label": "x"}]}).status_code == 403
    assert requests.get(f"{API}/contact-statuses").status_code == 401
    assert s.put(f"{API}/contact-statuses/zzz", json={"items": [{"label": "x"}]}).status_code == 404
