"""Une base par société : emplacement, cloisonnement physique, création, migrations, suppression."""
import pytest

from app.core.provisioning import MIGRATIONS, create_org, drop_org, migrate_all
from app.core.repository import TenantIsolationError, TenantRepository
from app.core.tenancy import TenantContext


async def test_each_org_has_its_own_database(seeded):
    orgs = {o["_id"]: o async for o in seeded.control.orgs.find()}
    assert orgs["org_a"]["db"] == {"cluster": "default", "name": "t_org_a"}
    assert orgs["org_d"]["db"] == {"cluster": "dedie-acme", "name": "t_org_d"}
    # Aucune donnée métier dans la base plateforme
    assert "contacts" not in await seeded.control.list_collection_names()


async def test_data_lands_in_the_org_database_only(client, as_user, seeded):
    r = await client.post("/api/contacts", json={"display_name": "Mariés A"}, headers=as_user("alice"))
    cid = r.json()["id"]
    db_a = seeded.clients["default"]["t_org_a"]
    db_b = seeded.clients["default"]["t_org_b"]
    assert await db_a.contacts.find_one({"_id": cid})
    assert await db_b.contacts.find_one({"_id": cid}) is None
    assert await db_a.audit_log.count_documents({"ref": cid}) == 1  # audit dans la base de la société


async def test_dedicated_cluster_org_works(client, as_user, seeded):
    r = await client.post("/api/contacts", json={"display_name": "Client Acme"}, headers=as_user("dora"))
    assert r.status_code == 201
    assert await seeded.clients["dedie-acme"]["t_org_d"].contacts.count_documents({}) == 1
    assert "t_org_d" not in await seeded.clients["default"].list_database_names()


async def test_provisioning_creates_indexes_and_is_idempotent(seeded):
    db_a = seeded.clients["default"]["t_org_a"]
    info = await db_a.contacts.index_information()
    assert any(k[0][0] == "org_id" for k in (v["key"] for v in info.values()) if k)
    again = await create_org(seeded, name="Org A", slug="a", owner_user_id="alice")
    assert again["_id"] == "org_a"
    assert await seeded.control.orgs.count_documents({"slug": "a"}) == 1


async def test_migrations_run_once_per_org(seeded):
    done = await migrate_all(seeded)
    assert set(done) == {"org_a", "org_b", "org_c", "org_d"}
    assert await seeded.control.migrations_log.count_documents({}) == 0  # déjà à jour depuis la création
    # Simule une société restée en version 0
    await seeded.clients["default"]["t_org_b"]["_meta"].update_one({"_id": "schema"}, {"$set": {"version": 0}})
    await migrate_all(seeded)
    assert await seeded.control.migrations_log.count_documents({"org_id": "org_b"}) == len(MIGRATIONS)


async def test_repository_refuses_mismatched_database(seeded):
    org_a = await seeded.control.orgs.find_one({"_id": "org_a"})
    org_b = await seeded.control.orgs.find_one({"_id": "org_b"})
    ctx = TenantContext(org_id="org_a", user_id="x", role="owner", permissions={"*"},
                        entitlements=None, org=org_a, db=seeded.tenant(org_b))
    with pytest.raises(TenantIsolationError):
        TenantRepository(ctx, "contacts")


async def test_drop_org_removes_its_database(client, as_user, seeded):
    await client.post("/api/contacts", json={"display_name": "x"}, headers=as_user("bob"))
    await drop_org(seeded, "org_b")
    assert "t_org_b" not in await seeded.clients["default"].list_database_names()
    assert (await client.get("/api/contacts", headers=as_user("bob"))).status_code == 403
