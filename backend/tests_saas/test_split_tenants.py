"""Migration d'une base unique vers une base par société : copie fidèle, source intacte."""
from mongomock_motor import AsyncMongoMockClient

import tenant_router as tenants
from scripts_saas import split_tenants


async def test_split_single_database(capsys):
    src = AsyncMongoMockClient()["legacy"]
    await src.orgs.insert_many([{"id": "org-1", "name": "Exclusivity"}, {"id": "org-2", "name": "Autre"}])
    await src.users.insert_one({"user_id": "u1", "org_id": "org-1"})
    await src.contacts.insert_many([{"id": "c1", "org_id": "org-1"}, {"id": "c2", "org_id": "org-2"}, {"id": "c3", "org_id": "org-1"}])
    await src.quotes.insert_one({"id": "q1", "org_id": "org-1", "share_hash": "h" * 64})
    await src.channel_accounts.insert_one({"id": "acc1", "org_id": "org-2"})
    await src.sync_queue.insert_one({"account_id": "acc1", "gmail_id": "g"})
    await src.schema_migrations.insert_one({"_id": "m001", "status": "ok"})
    await src.strays.insert_one({"x": 1})  # sans société

    tenants.init(tenants.Clusters({"default": AsyncMongoMockClient()}, "platform"))
    assert await split_tenants.main(apply=False, force=False, src=src, clusters=True) == 0
    assert await tenants.CLUSTERS.control.orgs.count_documents({}) == 0  # simulation : rien d'écrit

    assert await split_tenants.main(apply=True, force=False, src=src, clusters=True) == 0
    c = tenants.CLUSTERS
    assert await c.control.users.count_documents({}) == 1
    assert {d["id"] async for d in c.tenant("org-1").contacts.find({})} == {"c1", "c3"}
    assert {d["id"] async for d in c.tenant("org-2").contacts.find({})} == {"c2"}
    assert await c.tenant("org-2").sync_queue.count_documents({}) == 1
    assert await c.tenant("org-1").schema_migrations.count_documents({}) == 1
    assert await c.tenant("org-2").schema_migrations.count_documents({}) == 1
    assert (await c.control.link_index.find_one({"_id": "h" * 64}))["org_id"] == "org-1"
    assert (await c.control.orgs.find_one({"id": "org-1"}))["db"]["name"] == tenants.tenant_db_name("org-1")
    assert await src.contacts.count_documents({}) == 3  # source intacte
    out = capsys.readouterr().out
    assert "strays: 1" in out and "aucun écart" in out
