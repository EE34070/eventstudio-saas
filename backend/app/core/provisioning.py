"""Création d'une société cliente et de sa base dédiée, et mises à jour de structure.

create_org() :
  1. choisit le cluster (dédié si demandé, sinon le cluster partagé le moins rempli)
  2. enregistre la société dans la base plateforme, statut « provisioning »
  3. crée la base t_<org_id> : collections et index de tous les modules
  4. crée la membership du propriétaire, puis passe la société en « ready »
Idempotent : relancer sur une société à moitié créée la termine sans doublon.

Migrations : liste ordonnée de fonctions appliquées à CHAQUE base société.
La version atteinte est stockée dans la base société (_meta) et journalisée
dans la base plateforme (migrations_log).
"""
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from .config import get_settings
from .db import ClusterRouter, tenant_db_name
from .modules import registry


def _now() -> datetime:
    return datetime.now(UTC)


async def sync_tenant_schema(db: AsyncIOMotorDatabase) -> None:
    """Crée les collections et index déclarés par les modules (sans effet s'ils existent)."""
    existing = set(await db.list_collection_names())
    for m in registry().values():
        for col in m.collections:
            if col not in existing:
                await db.create_collection(col)
                existing.add(col)
        for col, specs in m.indexes.items():
            for keys in specs:
                if keys[0][0] != "org_id":
                    raise RuntimeError(f"{m.key}.{col} : tout index métier doit commencer par org_id")
                await db[col].create_index(keys)
    await db.audit_log.create_index([("org_id", 1), ("at", -1)])


async def _pick_cluster(router: ClusterRouter, dedicated: str | None) -> str:
    if dedicated:
        if dedicated not in router.clients:
            raise ValueError(f"Cluster dédié « {dedicated} » non configuré")
        return dedicated
    control = router.control
    shared = [c for c in router.clients if not c.startswith("dedie-")]
    counts = {c: await control.orgs.count_documents({"db.cluster": c, "deleted_at": None}) for c in shared}
    cluster = min(counts, key=counts.get)
    if counts[cluster] >= get_settings().MAX_TENANTS_PER_CLUSTER:
        raise RuntimeError("Clusters partagés pleins : ajouter un cluster dans TENANT_CLUSTERS")
    return cluster


async def create_org(
    router: ClusterRouter,
    *,
    name: str,
    slug: str,
    owner_user_id: str,
    plan: str = "essentiel",
    status: str = "trialing",
    org_id: str | None = None,
    dedicated_cluster: str | None = None,
) -> dict:
    control = router.control
    org = await control.orgs.find_one({"slug": slug})
    if org is None:
        org_id = org_id or uuid4().hex[:16]
        cluster = await _pick_cluster(router, dedicated_cluster)
        org = {
            "_id": org_id, "slug": slug, "name": name,
            "db": {"cluster": cluster, "name": tenant_db_name(org_id)},
            "subscription": {"plan": plan, "status": status},
            "provisioning": "pending", "created_at": _now(), "deleted_at": None,
        }
        await control.orgs.insert_one(org)

    tdb = router.tenant(org)
    await sync_tenant_schema(tdb)
    await tdb["_meta"].update_one(
        {"_id": "schema"},
        {"$setOnInsert": {"org_id": org["_id"], "version": len(MIGRATIONS), "created_at": _now()}},
        upsert=True,
    )
    await control.memberships.update_one(
        {"user_id": owner_user_id, "org_id": org["_id"]},
        {"$setOnInsert": {"role": "owner", "status": "active", "created_at": _now()}},
        upsert=True,
    )
    await control.orgs.update_one({"_id": org["_id"]}, {"$set": {"provisioning": "ready"}})
    return await control.orgs.find_one({"_id": org["_id"]})


# --- Migrations -------------------------------------------------------------------
Migration = Callable[[AsyncIOMotorDatabase], Awaitable[None]]


async def _m001_schema(db: AsyncIOMotorDatabase) -> None:
    await sync_tenant_schema(db)


async def _m002_wedding_planner(db: AsyncIOMotorDatabase) -> None:
    """Collections et index du module wedding_planner pour les sociétés déjà créées."""
    await sync_tenant_schema(db)


MIGRATIONS: list[Migration] = [
    _m001_schema,
    _m002_wedding_planner,
    # Ajouter les suivantes ici, jamais au milieu : _m002_..., _m003_...
]


async def migrate_all(router: ClusterRouter) -> dict[str, int]:
    """Applique les migrations manquantes à chaque base société. Rejouable sans risque."""
    control = router.control
    done: dict[str, int] = {}
    async for org in control.orgs.find({"deleted_at": None, "provisioning": "ready"}):
        tdb = router.tenant(org)
        meta = await tdb["_meta"].find_one({"_id": "schema"}) or {"version": 0}
        version = meta["version"]
        for i in range(version, len(MIGRATIONS)):
            await MIGRATIONS[i](tdb)
            await tdb["_meta"].update_one({"_id": "schema"}, {"$set": {"version": i + 1}}, upsert=True)
            await control.migrations_log.insert_one(
                {"org_id": org["_id"], "version": i + 1, "name": MIGRATIONS[i].__name__, "at": _now()}
            )
        done[org["_id"]] = len(MIGRATIONS)
    return done


async def drop_org(router: ClusterRouter, org_id: str) -> None:
    """Suppression définitive (fin de contrat + délai de restitution) : la base entière disparaît."""
    control = router.control
    org = await control.orgs.find_one({"_id": org_id})
    if not org:
        return
    tdb = router.tenant(org)
    await tdb.client.drop_database(tdb.name)
    await control.memberships.delete_many({"org_id": org_id})
    await control.orgs.update_one({"_id": org_id}, {"$set": {"deleted_at": _now(), "provisioning": "dropped"}})
