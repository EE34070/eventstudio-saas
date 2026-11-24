import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import messaging_core as mc
import tenant_router as tenants
import providers_core as pc

logger = logging.getLogger(__name__)


def locked(name: str, ttl: int, fn):
    async def run():
        if not await mc.acquire(f"job:{name}", ttl):
            return
        try:
            await tenants.for_each_org(fn, label=name)  # une passe par société, sur sa base
        except Exception:
            logger.exception("Scheduled job %s failed", name)
    return run


def start() -> AsyncIOScheduler:
    s = AsyncIOScheduler(timezone="Europe/Paris")
    s.add_job(locked("messaging-sync", 240, mc.sync_all), "interval", minutes=5, max_instances=1, coalesce=True)
    s.add_job(locked("messaging-watch", 3600, mc.renew_watches), "cron", hour=2, minute=30)
    s.add_job(locked("messaging-trash", 3600, mc.daily_trash), "cron", hour=3, minute=0)
    s.add_job(locked("providers-tick", 840, pc.tick), "interval", minutes=15, max_instances=1, coalesce=True)
    import routes_crm
    s.add_job(locked("crm-daily", 3600, routes_crm.tick), "cron", hour=8, minute=0)
    import portal_core
    s.add_job(locked("portal-daily", 3600, portal_core.tick), "cron", hour=9, minute=30)
    import routes_admin
    s.add_job(locked("tasks-auto", 1800, routes_admin.tick), "interval", minutes=60, max_instances=1, coalesce=True)
    import routes_logistics
    s.add_job(locked("logistics-tick", 1800, routes_logistics.tick), "interval", minutes=60, max_instances=1, coalesce=True)
    import routes_stock
    s.add_job(locked("stock-options", 1800, routes_stock.tick), "interval", minutes=60, max_instances=1, coalesce=True)
    import routes_quote_docs
    s.add_job(locked("quote-sign", 1800, routes_quote_docs.tick), "interval", minutes=60, max_instances=1, coalesce=True)
    import routes_access
    import routes_dj
    s.add_job(locked("dj-daily", 3600, routes_dj.tick), "cron", hour=9, minute=0)
    s.add_job(locked("access-lifecycle", 1800, routes_access.tick), "interval", minutes=60, max_instances=1, coalesce=True)
    import routes_works
    s.add_job(locked("works-recurrence", 3600, routes_works.tick), "cron", hour=4, minute=10)
    import routes_communication
    s.add_job(locked("comms-tick", 840, routes_communication.tick), "interval", minutes=15, max_instances=1, coalesce=True)
    s.start()
    return s
