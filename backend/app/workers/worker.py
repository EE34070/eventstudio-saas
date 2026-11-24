"""Worker de tâches asynchrones (arq + Redis) — service « Background Worker » sur Render.

Tout ce qui est lent ou planifié sort de l'API : IA (lecture de devis PDF, saisie rapide),
OCR des factures d'achat, synchronisation Gmail/WhatsApp, relances, e-mails, exports,
purge de la corbeille, sauvegardes.

Règle multi-tenant : chaque tâche reçoit org_id en argument et n'agit QUE dans cette
organisation (même dépôt TenantRepository, contexte « système »).
Lancement : arq app.workers.worker.WorkerSettings
"""
from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.db import ClusterRouter
from app.core.entitlements import resolve
from app.core.rbac import Role
from app.core.tenancy import TenantContext


async def system_context(router: ClusterRouter, org_id: str) -> TenantContext:
    """Contexte limité à UNE société, avec sa base dédiée."""
    org = await router.control.orgs.find_one({"_id": org_id, "provisioning": "ready"})
    if not org:
        raise LookupError(org_id)
    return TenantContext(org_id=org_id, user_id="system", role=Role.ADMIN, permissions={"*"},
                         entitlements=resolve(org), org=org, db=router.tenant(org))


async def startup(ctx):
    ctx["router"] = ClusterRouter.from_settings()


async def parse_supplier_quote(ctx, org_id: str, file_key: str):
    """Import IA d'un devis prestataire PDF → lignes produits proposées (validation humaine)."""
    tctx = await system_context(ctx["router"], org_id)
    ...  # appel Anthropic, sortie validée par schéma, stockée en « brouillon à valider »
    return {"org_id": tctx.org_id, "file": file_key, "status": "pending_review"}


async def purge_trash(ctx):
    """Purge des éléments en corbeille depuis plus de 30 jours : boucle sur les sociétés,
    une base à la fois, via system_context()."""
    ...


async def sync_mailboxes(ctx):
    """Synchronisation incrémentale Gmail / WhatsApp pour chaque organisation connectée."""
    ...


class WorkerSettings:
    functions = [parse_supplier_quote]
    cron_jobs = [cron(purge_trash, hour=3, minute=17), cron(sync_mailboxes, minute={0, 10, 20, 30, 40, 50})]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().REDIS_URL)
    max_jobs = 10
