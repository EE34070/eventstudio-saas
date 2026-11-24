"""Chaque tâche planifiée et chaque cron s'exécute société par société, sans erreur de routage."""
import logging

import pytest

import tenant_router as tenants


def _jobs():
    import messaging_core as mc
    import portal_core
    import providers_core as pc
    import routes_access
    import routes_admin
    import routes_communication
    import routes_crm
    import routes_dj
    import routes_logistics
    import routes_quote_docs
    import routes_stock
    from routes_billing import generate_all, today
    from routes_comms import run_auto_reminders
    from routes_dj_coverage import weekly_digest
    return {
        "messaging-sync": mc.sync_all, "messaging-watch": mc.renew_watches, "messaging-trash": mc.daily_trash,
        "providers-tick": pc.tick, "crm-daily": routes_crm.tick, "portal-daily": portal_core.tick,
        "tasks-auto": routes_admin.tick, "logistics-tick": routes_logistics.tick, "stock-options": routes_stock.tick,
        "quote-sign": routes_quote_docs.tick, "dj-daily": routes_dj.tick, "access-lifecycle": routes_access.tick,
        "comms-tick": routes_communication.tick,
        "cron-loading": lambda: generate_all(today()), "cron-reminders": lambda: run_auto_reminders("https://app.test"),
        "cron-dj-weekly": weekly_digest,
    }


@pytest.mark.parametrize("name", list(_jobs()))
async def test_job_runs_per_company(platform, caplog, name):
    caplog.set_level(logging.ERROR, logger="tenant_router")
    await tenants.for_each_org(_jobs()[name], label=name)
    assert "sans société active" not in caplog.text, caplog.text[-2000:]
    errors = [r for r in caplog.records if r.name == "tenant_router"]
    assert not errors, errors[0].exc_text[-1500:] if errors[0].exc_text else errors[0].getMessage()
