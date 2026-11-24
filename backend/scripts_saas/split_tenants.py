"""Migration « base unique » -> « base plateforme + une base par société ».

La base source n'est JAMAIS modifiée : on copie vers une nouvelle destination
(idéalement un nouveau cluster en Union européenne), puis on vérifie les comptes.

  # 1. Simulation : ce qui serait copié, collection par collection et société par société
  SRC_MONGO_URL=... SRC_DB=... MONGO_URL=... CONTROL_DB=platform \
      python -m scripts_saas.split_tenants --dry-run

  # 2. Copie réelle (refuse si la destination contient déjà des données, sauf --force)
  ... python -m scripts_saas.split_tenants --apply

Règles :
  - collections plateforme (tenant_router.PLATFORM) : copiées telles quelles dans CONTROL_DB
  - autres collections : chaque document va dans t_<org_id> selon son champ org_id
  - documents sans org_id : rattachés quand c'est possible (sync_queue -> via channel_accounts,
    schema_migrations -> copié dans chaque société, sinon à la société --default-org-slug si
    elle est donnée), sinon listés et NON copiés
  - empreintes de liens publics (share_hash, token_hash…) indexées dans platform.link_index
  - index de chaque base créés (mêmes définitions que server.INDEXES)
"""
import argparse
import asyncio
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

import tenant_router as tenants  # noqa: E402

SKIP = {"job_locks", "cron_runs"}           # états techniques éphémères, recréés automatiquement
COPY_TO_EVERY_TENANT = {"schema_migrations"}  # état des migrations : identique pour chaque société au départ
BATCH = 500


async def main(apply: bool, force: bool, src=None, clusters=None, default_org_slug: str | None = None) -> int:
    src = src if src is not None else AsyncIOMotorClient(os.environ["SRC_MONGO_URL"])[os.environ["SRC_DB"]]
    if clusters is None:
        tenants.init(tenants.Clusters.from_env())
    dst = tenants.CLUSTERS
    import server  # INDEXES

    orgs = [o async for o in src.orgs.find({}, {"_id": 0})]
    org_ids = {o["id"] for o in orgs}
    default_org_slug = default_org_slug or os.environ.get("SPLIT_DEFAULT_ORG_SLUG") or None
    default_org = next((o["id"] for o in orgs if o.get("slug") == default_org_slug), None) if default_org_slug else None
    if default_org_slug and not default_org:
        sys.exit(f"Société « {default_org_slug} » introuvable pour les documents sans société")
    print(f"Sociétés : {len(orgs)} — " + ", ".join(o.get("name", o["id"]) for o in orgs))

    if apply and not force:
        if await dst.control.orgs.count_documents({}):
            sys.exit("Destination non vide (platform.orgs). Utilisez --force en connaissance de cause.")

    # Rattachement des documents sans org_id
    account_org = {a["id"]: a["org_id"] async for a in src.channel_accounts.find({}, {"_id": 0, "id": 1, "org_id": 1})}

    report: dict[str, Counter] = {}
    orphans: Counter = Counter()
    links = 0
    for coll in sorted(await src.list_collection_names()):
        if coll.startswith("system.") or coll in SKIP:
            continue
        counts: Counter = Counter()
        if coll in tenants.PLATFORM:
            docs = [d async for d in src[coll].find({})]
            counts["platform"] = len(docs)
            if apply and docs:
                await dst.control[coll].insert_many(docs, ordered=False)
            report[coll] = counts
            continue

        buffers: dict[str, list] = defaultdict(list)

        async def flush(org_id: str) -> None:
            if apply and buffers[org_id]:
                await dst.tenant(org_id)[coll].insert_many(buffers[org_id], ordered=False)
            buffers[org_id].clear()

        async for d in src[coll].find({}):
            org_id = d.get("org_id")
            if not org_id and coll == "sync_queue":
                org_id = account_org.get(d.get("account_id"))
            if coll in COPY_TO_EVERY_TENANT:
                for oid in org_ids:
                    buffers[oid].append(dict(d))
                    counts[oid] += 1
                continue
            if org_id not in org_ids and default_org and not org_id:
                org_id = d["org_id"] = default_org  # base historique mono-société : rattachement explicite
            if org_id not in org_ids:
                orphans[coll] += 1
                continue
            buffers[org_id].append(d)
            counts[org_id] += 1
            for field in tenants.TOKEN_FIELDS:
                v = d.get(field)
                if isinstance(v, str) and len(v) >= 32:
                    links += 1
                    if apply:
                        await dst.control.link_index.update_one(
                            {"_id": v}, {"$set": {"org_id": org_id, "coll": coll, "field": field}}, upsert=True)
            if len(buffers[org_id]) >= BATCH:
                await flush(org_id)
        for oid in list(buffers):
            await flush(oid)
        report[coll] = counts

    # Emplacements + index
    if apply:
        for oid in org_ids:
            await tenants.provision(oid, server.INDEXES)

    names = {o["id"]: o.get("name", o["id"]) for o in orgs}
    print("\nCollection".ljust(34) + "Documents copiés")
    for coll, c in report.items():
        detail = ", ".join(f"{names.get(k, k)}: {v}" for k, v in c.most_common())
        print(f"  {coll.ljust(32)}{sum(c.values()):>7}  {detail}")
    print(f"\nLiens publics indexés : {links}")
    if orphans:
        print("\nDocuments SANS société identifiable (non copiés, à examiner) :")
        for coll, n in orphans.most_common():
            print(f"  {coll}: {n}")

    if apply:
        return await verify(src, dst, org_ids, orphans)
    print("\nSimulation uniquement : rien n'a été écrit. Relancez avec --apply.")
    return 0


async def verify(src, dst, org_ids: set, orphans: Counter) -> int:
    """Compare, pour chaque collection, la source et la somme des destinations."""
    bad = 0
    for coll in sorted(await src.list_collection_names()):
        if coll.startswith("system.") or coll in SKIP:
            continue
        n_src = await src[coll].count_documents({})
        if coll in tenants.PLATFORM:
            n_dst = await dst.control[coll].count_documents({})
        elif coll in COPY_TO_EVERY_TENANT:
            n_dst = sum([await dst.tenant(o)[coll].count_documents({}) for o in org_ids]) // max(len(org_ids), 1)
        else:
            n_dst = sum([await dst.tenant(o)[coll].count_documents({}) for o in org_ids]) + orphans.get(coll, 0)
        if n_src != n_dst:
            bad += 1
            print(f"ÉCART {coll}: source {n_src} / destination {n_dst}")
    print("\nVérification : " + ("OK, aucun écart." if not bad else f"{bad} collection(s) en écart."))
    return 1 if bad else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--default-org-slug", help="société à qui rattacher les documents sans org_id (ex. exclusivity-events)")
    a = p.parse_args()
    sys.exit(asyncio.run(main(a.apply, a.force, default_org_slug=a.default_org_slug)))
