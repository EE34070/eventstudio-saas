import pytest

import tenant_router as tenants
from conftest import ORG_A, ORG_B


def tdb(clusters, org_id):
    return clusters.tenant(org_id)


async def test_each_company_has_its_own_database(platform):
    a = await platform.control.orgs.find_one({"id": ORG_A})
    b = await platform.control.orgs.find_one({"id": ORG_B})
    assert a["db"] == {"cluster": "default", "name": tenants.tenant_db_name(ORG_A)}
    assert b["db"]["cluster"] == "dedie-acme"
    assert "contacts" not in await platform.control.list_collection_names()


async def test_contact_written_in_own_database_only(client, as_user, platform):
    r = await client.post("/api/contacts", json={"first_name": "Mariés", "last_name": "A"}, headers=as_user("alice"))
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert await tdb(platform, ORG_A).contacts.find_one({"id": cid})
    assert await tdb(platform, ORG_B).contacts.find_one({"id": cid}) is None
    assert await platform.control.contacts.find_one({"id": cid}) is None


async def test_other_company_sees_nothing(client, as_user):
    cid = (await client.post("/api/contacts", json={"first_name": "Secret"}, headers=as_user("alice"))).json()["id"]
    assert (await client.get("/api/contacts", headers=as_user("bob"))).json() == []
    assert (await client.get(f"/api/contacts/{cid}", headers=as_user("bob"))).status_code == 404
    assert (await client.get(f"/api/contacts/{cid}", headers=as_user("alice"))).status_code == 200


async def test_me_and_dedicated_cluster(client, as_user, platform):
    r = await client.get("/api/me", headers=as_user("bob"))
    assert r.status_code == 200, r.text
    assert r.json()["org"]["name"] == "Société B"
    await client.post("/api/contacts", json={"first_name": "Client B"}, headers=as_user("bob"))
    assert await platform.clients["dedie-acme"][tenants.tenant_db_name(ORG_B)].contacts.count_documents({}) == 1


async def test_business_query_without_company_is_refused():
    import core
    with pytest.raises(tenants.TenantContextMissing):
        await core.db.contacts.find_one({"id": "x"})
    with pytest.raises(tenants.TenantContextMissing):
        core.db.events.find({})


async def test_platform_collections_work_without_company(platform):
    import core
    assert await core.db.orgs.count_documents({}) == 2


async def test_public_link_finds_its_company(platform):
    import core
    with tenants.org_scope(ORG_A):
        ctx = core.Ctx({"org_id": ORG_A, "role": "admin", "name": "t"})
        q = await ctx.insert("quotes", {"number": "DEV-1", "status": "envoye", "date": "2999-01-01", "valid_until": "2999-12-31"})
        token = await core.ensure_link("quotes", q)
    # Requête publique : aucune société active au départ
    found = await _in_fresh_context(core.link_doc, "quotes", token)
    assert found and found["id"] == q["id"]
    assert await platform.control.link_index.find_one({"org_id": ORG_A, "coll": "quotes"})
    assert await _in_fresh_context(core.link_doc, "quotes", "x" * 43) is None  # jeton inconnu : introuvable


async def _in_fresh_context(fn, *a):
    import asyncio
    import contextvars
    return await asyncio.get_running_loop().create_task(fn(*a), context=contextvars.Context())


async def test_scheduled_jobs_run_once_per_company(platform):
    import core
    seen = []

    async def job():
        # Une tâche historique qui boucle sur toutes les sociétés via Ctx
        async for o in core.db.orgs.find({}, {"_id": 0, "id": 1}):
            ctx = core.Ctx({"org_id": o["id"], "role": "admin", "name": "cron"})
            await ctx.insert("tasks", {"title": f"tick {o['id']}"})
        seen.append(tenants.current_org())
    await tenants.for_each_org(job)
    assert sorted(seen) == sorted([ORG_A, ORG_B])
    # Chaque base ne contient que la tâche de sa société, une seule fois
    for oid in (ORG_A, ORG_B):
        docs = await platform.tenant(oid).tasks.find({}).to_list(None)
        assert len(docs) == 2 and all(d["org_id"] == oid or d["title"] != f"tick {oid}" for d in docs)
        assert sum(1 for d in docs if d["title"] == f"tick {oid}" and d["org_id"] == oid) == 1


async def test_pinned_request_cannot_switch_company():
    with tenants.org_scope(ORG_A):
        with pytest.raises(tenants.TenantMismatch):
            tenants.pin_org(ORG_B)


async def test_onboarding_creates_company_database(client, as_user, platform):
    r = await client.post("/api/onboarding", json={"company_name": "Nouvelle Agence"}, headers=as_user("newbie"))
    assert r.status_code == 200, r.text
    org = await platform.control.orgs.find_one({"name": "Nouvelle Agence"})
    assert org["db"]["name"] == tenants.tenant_db_name(org["id"])
    t = platform.tenant(org["id"])
    assert await t.team.count_documents({"org_id": org["id"]}) == 1
    assert "org_start" in await t.events.index_information()
    me = await client.get("/api/me", headers=as_user("newbie"))
    assert me.json()["org"]["name"] == "Nouvelle Agence"


async def test_refuses_to_start_on_unsplit_legacy_database(platform):
    await platform.control.events.insert_one({"id": "e1", "org_id": "x"})
    with pytest.raises(RuntimeError, match="split_tenants"):
        await tenants.assert_split_done()
