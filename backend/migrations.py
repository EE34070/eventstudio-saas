"""Migrations de données versionnées. Jamais lancées au démarrage sans RUN_MIGRATIONS=true.

  python3 migrations.py --dry-run   -> ce que chaque migration en attente modifierait, par société (rien n'est écrit)
  python3 migrations.py --apply     -> exécute les migrations en attente (sauvegarde préalable en production)
"""
import asyncio
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
sys.path.insert(0, str(Path(__file__).parent))
from core import RETIRED_ROLES, db, new_id  # noqa: E402
from security import PROD  # noqa: E402

logger = logging.getLogger("migrations")
LINKS = (("quotes", "share_token"), ("invoices", "share_token"), ("logistics_missions", "share_token"), ("quote_views", "token"), ("request_recipients", "token"))
MISSING = {"$exists": False}


async def m001():
    for old, new in RETIRED_ROLES.items():
        await db.users.update_many({"role": old}, {"$set": {"role": new}})


async def m002():
    await db.contacts.update_many({"types": MISSING}, {"$set": {"types": ["client"]}})


async def m003():
    from providers_core import migrate_organizers
    await migrate_organizers()


async def m004():
    from routes_admin import migrate_crm_tasks
    await migrate_crm_tasks()


async def m005():
    import routes_stock
    await routes_stock.migrate()


async def m006():
    import routes_quote_blocks
    await routes_quote_blocks.migrate()


async def m007():
    import routes_quote_docs
    await routes_quote_docs.migrate()


async def m008():
    for c, k in LINKS:
        await db[c].update_many({k: {"$exists": True}}, {"$unset": {k: ""}})


async def m009():
    import access_grid
    import routes_access
    import server
    access_grid.init(server.app)
    await routes_access.migrate()


async def m010():
    from routes_main import normalize_onsite
    async for v in db.venues.find({"onsite_contacts": MISSING}):
        d = normalize_onsite({k: v.get(k, "") for k in ("contact_name", "contact_phone", "contact_email")})
        await db.venues.update_one({"_id": v["_id"]}, {"$set": {"onsite_contacts": d["onsite_contacts"]}})


async def m011():
    async for e in db.events.find({"client_contact_ids": MISSING}, {"client_id": 1}):
        cid = e.get("client_id") or ""
        await db.events.update_one({"_id": e["_id"], "client_contact_ids": MISSING}, {"$set": {
            "client_contact_ids": [cid] if cid else [], "signatory_contact_id": cid, "planner_contact_id": None, "main_contact_role": "client",
            "planner_commission_mode": "none", "planner_commission_value": 0, "planner_commission_status": "due"}})


STATUS_TARGET = {"types": {"$in": ["prestataire", "lieu", "fournisseur"]}, "statuses": MISSING}


async def m012(org_id: str = ""):
    import contact_status as cs
    now = datetime.now(timezone.utc).isoformat()
    async for c in db.contacts.find({**STATUS_TARGET, **({"org_id": org_id} if org_id else {})}):
        wp = bool(await db.provider_profiles.find_one({"org_id": c["org_id"], "contact_id": c["id"], "categories": cs.WP}))
        client = "client" in c["types"]
        st = {k: (c.get("status") or "prospect") if k == "client" else cs.FALLBACK[k] for k in cs.keys(c, wp)}
        hist = [] if client or not c.get("status") else [{"type": "ancien statut", "from": c["status"], "to": "", "at": now, "by": "Migration"}]
        await db.contacts.update_one({"_id": c["_id"]}, {"$set": {"statuses": st, "status": c.get("status", "") if client else ""}, "$push": {"status_history": {"$each": hist}}})


SUPPLIERS_TARGET = {"suppliers.0": {"$exists": True}, "suppliers_migrated": MISSING}


async def m013(org_id: str = ""):
    import routes_suppliers as sup
    async for e in db.equipment.find({**SUPPLIERS_TARGET, **({"org_id": org_id} if org_id else {})}):
        for s in e.get("suppliers") or []:
            if s.get("supplier_id") and not await db.supplier_product_map.find_one({"org_id": e["org_id"], "product_id": e["id"], "supplier_id": s["supplier_id"], "deleted_at": None}):
                await sup.learn(e["org_id"], s["supplier_id"], e["id"], s.get("unit_cost") or 0, (s.get("updated_at") or "")[:10], "quote", "", s.get("supplier_ref", ""), s.get("supplier_label", ""))
        await db.equipment.update_one({"_id": e["_id"]}, {"$set": {"suppliers_migrated": True}})


PEOPLE_C = {"types": {"$in": ["prestataire", "lieu", "fournisseur"]}, "people_migrated": MISSING}
PEOPLE_V = {"onsite_contacts.0": {"$exists": True}, "people_migrated": MISSING}
CATS_T = {"key": {"$in": ["location_mobilier", "autres"]}, "label": {"$in": ["Location mobilier", "Autres"]}}


async def m014(org_id: str = ""):
    import contact_people as cp
    o = {"org_id": org_id} if org_id else {}
    async for c in db.contacts.find({**PEOPLE_C, **o}):
        if (c.get("first_name") or c.get("last_name")) and not await db.contact_people.find_one({"org_id": c["org_id"], "contact_id": c["id"], "owner_type": "contact", "deleted_at": None}):
            await db.contact_people.insert_one({"id": new_id(), "org_id": c["org_id"], "owner_type": "contact", "contact_id": c["id"], "first_name": c.get("first_name", ""), "last_name": c.get("last_name") or c.get("first_name", ""),
                                                "role_id": "contact_principal", "role_label": "Contact principal", "phone": c.get("phone", ""), "email": (c.get("email") or "").lower(), "whatsapp": False, "language": c.get("language") or "fr-FR",
                                                "preferred_channel": "email", "is_primary": True, "cc_by_default": False, "active": True, "left_at": None, "notes": "", "deleted_at": None, "created_at": datetime.now(timezone.utc).isoformat()})
        await db.contacts.update_one({"_id": c["_id"]}, {"$set": {"people_migrated": True}})
    async for v in db.venues.find({**PEOPLE_V, **o}, {"_id": 0}):
        await cp.sync_venue(v["org_id"], v)
        await db.venues.update_one({"org_id": v["org_id"], "id": v["id"]}, {"$set": {"people_migrated": True}})


async def m015(org_id: str = ""):
    import providers_core as pc
    order = {k: i + 1 for i, (k, _) in enumerate(pc.CATEGORIES)}
    for oid in ([org_id] if org_id else await db.provider_categories.distinct("org_id")):
        have = {c["key"] async for c in db.provider_categories.find({"org_id": oid}, {"_id": 0, "key": 1})}
        if not have:
            continue
        for k, lab in pc.CATEGORIES:
            if k not in have:
                await db.provider_categories.insert_one({"id": new_id(), "org_id": oid, "key": k, "label": lab, "order": order[k], "active": True, "is_organizer": False, "created_at": datetime.now(timezone.utc).isoformat()})
            await db.provider_categories.update_one({"org_id": oid, "key": k}, {"$set": {"order": order[k]}})
        await db.provider_categories.update_one({"org_id": oid, "key": "location_mobilier", "label": "Location mobilier"}, {"$set": {"label": "Location mobilier / vaisselle"}})
        await db.provider_categories.update_one({"org_id": oid, "key": "autres", "label": "Autres"}, {"$set": {"label": "Autre"}})
        await db.provider_categories.update_many({"org_id": oid, "key": {"$nin": list(order)}}, {"$inc": {"order": 100}})


# identifiant, ce que fait la migration, [(collection, filtre des éléments concernés)], fonction
MIGRATIONS = [
    ("001_roles_retires", "Renomme les anciens rôles des comptes", [("users", {"role": {"$in": list(RETIRED_ROLES)}})], m001),
    ("002_types_contacts", "Ajoute le type « client » aux contacts sans type", [("contacts", {"types": MISSING})], m002),
    ("003_organisateurs", "Remplace le métier prestataire « wedding planner » par les types d'organisateur", [("provider_categories", {"key": "wedding_planner"})], m003),
    ("004_taches_crm", "Copie les anciennes tâches CRM dans la To-do", [("crm_tasks", {})], m004),
    ("005_entrepots", "Crée l'entrepôt par défaut et les niveaux de stock de chaque société", [("equipment", {"stocked": MISSING})], m005),
    ("006_blocs_devis", "Convertit les lignes des anciens devis en blocs", [("quotes", {"blocks": {"$in": [None, []]}})], m006),
    ("007_versions_devis", "Numérote V1 les devis sans version", [("quotes", {"version": MISSING})], m007),
    ("008_liens_haches", "Supprime les jetons de lien en clair (les anciens liens cessent de fonctionner)", [(c, {k: {"$exists": True}}) for c, k in LINKS], m008),
    ("009_grille_profils", "Ajoute la grille de permissions aux profils d'accès et finance:costs au profil Gérant",
     [("access_profiles", {"permissions": MISSING}), ("access_profiles", {"base_role": "gerant", "sensitive.finance_costs": MISSING})], m009),
    ("010_contacts_lieux", "Convertit le contact unique d'un lieu en liste de contacts sur place", [("venues", {"onsite_contacts": MISSING})], m010),
    ("011_clients_evenements", "Ajoute la liste des clients et la commission organisateur aux événements", [("events", {"client_contact_ids": MISSING})], m011),
    ("012_statuts_contacts", "Donne aux prestataires, wedding planners, lieux et fournisseurs le statut par défaut de leur type (ancien statut gardé en historique)", [("contacts", STATUS_TARGET)], m012),
    ("013_fournisseurs_produits", "Reprend la liste de fournisseurs de chaque produit dans la table fournisseurs/produits (le premier devient préféré)", [("equipment", SUPPLIERS_TARGET)], m013),
    ("014_personnes", "Crée la personne principale de chaque prestataire / fournisseur / lieu et reprend les contacts sur place des lieux dans la table commune", [("contacts", PEOPLE_C), ("venues", PEOPLE_V)], m014),
    ("015_metiers", "Ajoute Traiteur et Photographe, renomme « Location mobilier / vaisselle » et « Autre », remet les métiers dans l'ordre", [("provider_categories", CATS_T)], m015),
    ("016_videaste", "Ajoute le métier « Vidéaste » après Photographe et décale les suivants", [("provider_categories", {"key": "photographe"})], m015),
]


async def counts(targets: list) -> dict:
    out: dict = {}
    for coll, f in targets:
        async for r in db[coll].aggregate([{"$match": f}, {"$group": {"_id": "$org_id", "n": {"$sum": 1}}}]):
            out[r["_id"]] = out.get(r["_id"], 0) + r["n"]
    return out


async def pending() -> list:
    done = {d["_id"] async for d in db.schema_migrations.find({"status": "ok"}, {"_id": 1})}
    return [m for m in MIGRATIONS if m[0] not in done]


async def run(apply: bool, backup: bool = True) -> int:
    """Migrations de la société active (une base par société : appelé via run_all)."""
    todo = await pending()
    names = {o["id"]: f"{o.get('name')}{' [SOCIÉTÉ RÉELLE]' if o.get('slug') == 'exclusivity-events' else ''}" async for o in db.orgs.find({}, {"_id": 0, "id": 1, "name": 1, "slug": 1})}
    if apply and todo and PROD and backup:
        subprocess.run([sys.executable, str(Path(__file__).parent.parent / "scripts" / "backup_mongo.py"), "backup"], check=True)
    for mid, what, targets, fn in todo:
        c = await counts(targets)
        total = sum(c.values())
        print(f"{mid} — {what} : {total} élément(s)")
        for oid, n in sorted(c.items(), key=lambda x: -x[1]):
            if "RÉELLE" in names.get(oid, "") or not apply:
                print(f"    {names.get(oid, oid or 'sans société')} : {n}")
        if not apply:
            continue
        try:
            await fn()
        except Exception as exc:
            await db.schema_migrations.update_one({"_id": mid}, {"$set": {"status": "failed", "at": datetime.now(timezone.utc).isoformat(), "error": str(exc)[:300]}}, upsert=True)
            raise RuntimeError(f"Migration {mid} en échec : arrêt. Les suivantes ne sont pas lancées.") from exc
        now = datetime.now(timezone.utc)
        await db.schema_migrations.update_one({"_id": mid}, {"$set": {"status": "ok", "at": now.isoformat(), "description": what, "modified": total, "by_org": {k or "none": v for k, v in c.items()}}}, upsert=True)
        for oid, n in c.items():
            if oid:
                await db.audit_logs.insert_one({"id": new_id(), "org_id": oid, "at": now.isoformat(), "at_dt": now, "actor_id": "", "actor_name": "Système", "actor_role": "", "action": "migration", "target": mid, "detail": f"{what} : {n} élément(s)"})
    if not todo:
        print("Aucune migration en attente.")
    return len(todo)


async def run_all(apply: bool) -> None:
    """Une passe par base société ; sauvegarde unique avant la première écriture en production."""
    import tenant_router as tenants
    if apply and PROD:
        subprocess.run([sys.executable, str(Path(__file__).parent.parent / "scripts" / "backup_mongo.py"), "backup"], check=True)
    await tenants.for_each_org(lambda: run(apply, backup=False), label="migrations")


async def pending_all() -> dict:
    import tenant_router as tenants
    out: dict = {}

    async def one():
        todo = await pending()
        if todo:
            out[tenants.current_org()] = [m[0] for m in todo]
    await tenants.for_each_org(one, label="migrations-pending")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("--dry-run", "--apply"):
        sys.exit(__doc__)
    asyncio.run(run_all(sys.argv[1] == "--apply"))
