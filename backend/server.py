import asyncio
import logging
import os
import sys
from contextlib import suppress
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI  # noqa: E402
from pymongo import ASCENDING, IndexModel  # noqa: E402
from starlette.middleware.cors import CORSMiddleware  # noqa: E402
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402

from clerk_auth import clerk_router  # noqa: E402
from core import RETIRED_ROLES, client, db  # noqa: E402
import tenant_router as tenants  # noqa: E402
from i18n import router as i18n_router  # noqa: E402
from routes_billing import router as billing_router  # noqa: E402
from routes_comms import router as comms_router  # noqa: E402
from routes_delivery import router as delivery_router  # noqa: E402
from routes_files import router as files_router  # noqa: E402
from routes_inbound import router as inbound_router  # noqa: E402
from routes_main import router as main_router, seed_module_defs  # noqa: E402
from routes_messaging import router as messaging_router  # noqa: E402
from routes_providers import router as providers_router  # noqa: E402
from routes_ops import router as ops_router  # noqa: E402
from scheduler import start as start_scheduler  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _org_id(name: str = "org_id") -> IndexModel:
    return IndexModel([("org_id", ASCENDING), ("id", ASCENDING)], name=name)


INDEXES: dict[str, list[IndexModel]] = {
    "users": [IndexModel([("user_id", ASCENDING)], name="user_id", unique=True),
              IndexModel([("org_id", ASCENDING)], name="org")],
    "orgs": [IndexModel([("id", ASCENDING)], name="id", unique=True), IndexModel([("slug", ASCENDING)], name="slug")],
    "team": [_org_id(), IndexModel([("email", ASCENDING)], name="email")],
    "events": [_org_id(), IndexModel([("org_id", ASCENDING), ("planner_contact_id", ASCENDING), ("start", ASCENDING)], name="org_planner_start"),
               IndexModel([("org_id", ASCENDING), ("start", ASCENDING)], name="org_start"),
               IndexModel([("org_id", ASCENDING), ("status", ASCENDING)], name="org_status")],
    "equipment": [_org_id()],
    "contacts": [_org_id(), IndexModel([("org_id", ASCENDING), ("types", ASCENDING)], name="org_types"), IndexModel([("org_id", ASCENDING), ("statuses.prestataire", ASCENDING)], name="org_status_prestataire", sparse=True)],
    "supplier_product_map": [IndexModel([("org_id", ASCENDING), ("product_id", ASCENDING)], name="org_product"), IndexModel([("org_id", ASCENDING), ("supplier_id", ASCENDING)], name="org_supplier")],
    "supplier_price_history": [IndexModel([("org_id", ASCENDING), ("map_id", ASCENDING)], name="org_map")],
    "contact_people": [IndexModel([("org_id", ASCENDING), ("contact_id", ASCENDING)], name="org_owner"), IndexModel([("org_id", ASCENDING), ("email", ASCENDING)], name="org_email")],
    "commitments": [IndexModel([("org_id", ASCENDING), ("event_id", ASCENDING)], name="org_event")],
    "contact_statuses": [IndexModel([("org_id", ASCENDING), ("contact_type", ASCENDING)], name="org_type", unique=True)],
    "venues": [_org_id()],
    "packs": [_org_id()],
    "vehicles": [_org_id()],
    "files": [_org_id()],
    "event_modules": [_org_id(), IndexModel([("org_id", ASCENDING), ("event_id", ASCENDING), ("module_key", ASCENDING)], name="event_module", unique=True)],
    "deliveries": [_org_id(), IndexModel([("org_id", ASCENDING), ("day", ASCENDING), ("event_id", ASCENDING)], name="day_event", unique=True)],
    "quotes": [_org_id(), IndexModel([("share_token", ASCENDING)], name="share_token", sparse=True), IndexModel([("org_id", ASCENDING), ("event_id", ASCENDING)], name="org_event")],
    "invoices": [_org_id(), IndexModel([("share_token", ASCENDING)], name="share_token", sparse=True), IndexModel([("org_id", ASCENDING), ("event_id", ASCENDING)], name="org_event"),
                 IndexModel([("org_id", ASCENDING), ("quote_id", ASCENDING), ("kind", ASCENDING)], name="quote_kind", unique=True)],
    "channel_accounts": [IndexModel([("org_id", ASCENDING), ("channel", ASCENDING)], name="org_channel", unique=True), IndexModel([("email", ASCENDING)], name="email")],
    "conversations": [_org_id(), IndexModel([("org_id", ASCENDING), ("account_id", ASCENDING), ("thread_id", ASCENDING)], name="thread", unique=True),
                      IndexModel([("org_id", ASCENDING), ("last_message_at", ASCENDING)], name="org_last")],
    "mail_labels": [_org_id(), IndexModel([("org_id", ASCENDING), ("account_id", ASCENDING), ("gmail_id", ASCENDING)], name="gmail_label", unique=True)],
    "messages": [_org_id(), IndexModel([("org_id", ASCENDING), ("gmail_id", ASCENDING)], name="gmail_id", unique=True),
                 IndexModel([("org_id", ASCENDING), ("conversation_id", ASCENDING), ("sent_at", ASCENDING)], name="conv_sent")],
    "sync_queue": [IndexModel([("account_id", ASCENDING), ("gmail_id", ASCENDING)], name="account_gmail", unique=True),
                   IndexModel([("account_id", ASCENDING), ("status", ASCENDING)], name="account_status")],
    "provider_profiles": [IndexModel([("org_id", ASCENDING), ("categories", ASCENDING)], name="org_categories"), IndexModel([("org_id", ASCENDING), ("contact_id", ASCENDING)], name="org_contact", unique=True)],
    "provider_categories": [IndexModel([("org_id", ASCENDING), ("key", ASCENDING)], name="org_key", unique=True)],
    "provider_documents": [IndexModel([("org_id", ASCENDING), ("provider_id", ASCENDING)], name="org_provider")],
    "provider_unavailabilities": [IndexModel([("org_id", ASCENDING), ("provider_id", ASCENDING), ("date", ASCENDING)], name="org_provider_date")],
    "service_requests": [_org_id()],
    "request_recipients": [IndexModel([("share_hash", ASCENDING)], name="share_hash", sparse=True), IndexModel([("org_id", ASCENDING), ("request_id", ASCENDING)], name="org_request")],
    "missions": [_org_id()],
    "message_templates": [_org_id()],
    "internal_notes": [IndexModel([("org_id", ASCENDING), ("conversation_id", ASCENDING)], name="org_conv")],
    "inbound_requests": [_org_id()],
    "opportunities": [_org_id()],
    "crm_activities": [IndexModel([("org_id", ASCENDING), ("opportunity_id", ASCENDING)], name="org_opp")],
    "crm_tasks": [_org_id()],
    "warehouses": [_org_id(), IndexModel([("org_id", ASCENDING)], name="one_default", unique=True, partialFilterExpression={"is_default": True})],
    "stock_levels": [IndexModel([("org_id", ASCENDING), ("product_id", ASCENDING), ("warehouse_id", ASCENDING)], name="org_product_wh", unique=True)],
    "stock_movements": [_org_id()],
    "logistics_missions": [_org_id(), IndexModel([("org_id", ASCENDING), ("date", ASCENDING)], name="org_date")],
    "vehicle_capacities": [IndexModel([("org_id", ASCENDING), ("vehicle_id", ASCENDING), ("key", ASCENDING)], name="org_vehicle_key", unique=True)],
    "reminder_logs": [_org_id()],
    "quote_section_templates": [_org_id()],
    "load_observations": [_org_id()],
    "urgent_reminders": [_org_id()],
    "tasks": [_org_id(), IndexModel([("org_id", ASCENDING), ("due_at", ASCENDING)], name="org_due")],
    "expense_reports": [_org_id()],
    "purchase_invoices": [_org_id()],
    "subscriptions": [_org_id()],
    "menu_prefs": [IndexModel([("org_id", ASCENDING), ("user_id", ASCENDING)], name="org_user", unique=True)],
    "audit_logs": [IndexModel([("org_id", ASCENDING), ("at", ASCENDING)], name="org_at"), IndexModel([("at_dt", ASCENDING)], name="ttl_12m", expireAfterSeconds=366 * 86400)],
    "portal_modules": [IndexModel([("org_id", ASCENDING), ("key", ASCENDING)], name="org_key", unique=True)],
    "event_portal_modules": [IndexModel([("org_id", ASCENDING), ("event_id", ASCENDING), ("module_key", ASCENDING)], name="event_module", unique=True)],
    "client_documents": [IndexModel([("org_id", ASCENDING), ("event_id", ASCENDING)], name="org_event")],
    "timelines": [IndexModel([("org_id", ASCENDING), ("event_id", ASCENDING)], name="org_event", unique=True)],
    "portal_messages": [IndexModel([("org_id", ASCENDING), ("event_id", ASCENDING), ("thread", ASCENDING)], name="org_event_thread")],
    "email_templates": [IndexModel([("org_id", ASCENDING), ("key", ASCENDING), ("language", ASCENDING)], name="org_key_lang", unique=True)],
    "provider_profile_changes": [_org_id()],
    "positions": [IndexModel([("org_id", ASCENDING), ("event_id", ASCENDING)], name="org_event")],
    "position_applications": [IndexModel([("org_id", ASCENDING), ("position_id", ASCENDING), ("provider_id", ASCENDING)], name="pos_provider", unique=True)],
    "timesheets": [IndexModel([("org_id", ASCENDING), ("mission_id", ASCENDING)], name="org_mission", unique=True)],
    "provider_invoices": [IndexModel([("org_id", ASCENDING), ("mission_id", ASCENDING)], name="org_mission", unique=True)],
    "staff_teams": [_org_id()],
    "music_plans": [IndexModel([("org_id", ASCENDING), ("event_id", ASCENDING)], name="org_event", unique=True), IndexModel([("guest_token_hash", ASCENDING)], name="guest")],
    "guest_suggestions": [IndexModel([("org_id", ASCENDING), ("plan_id", ASCENDING), ("status", ASCENDING)], name="plan_status")],
    "gdpr_requests": [_org_id()],
    "supplier_quotes": [_org_id(), IndexModel([("org_id", ASCENDING), ("quote_id", ASCENDING)], name="org_quote")],
    "work_orders": [_org_id(), IndexModel([("org_id", ASCENDING), ("status", ASCENDING), ("deadline", ASCENDING)], name="org_status_deadline"),
                    IndexModel([("org_id", ASCENDING), ("scheduled_start", ASCENDING)], name="org_start"),
                    IndexModel([("org_id", ASCENDING), ("parent_id", ASCENDING)], name="org_parent"),
                    IndexModel([("org_id", ASCENDING), ("recurrence_id", ASCENDING), ("occurrence_date", ASCENDING)], name="org_occurrence")],
    "work_templates": [_org_id()],
    "work_recurrences": [_org_id()],
    "loadings": [_org_id(), IndexModel([("org_id", ASCENDING), ("day", ASCENDING), ("event_id", ASCENDING)], name="day_event", unique=True)],
}


for _c in ("quotes", "invoices", "logistics_missions", "quote_views", "request_recipients", "media_requests", "dj_bookings", "partner_requests"):
    INDEXES.setdefault(_c, []).append(IndexModel([("share_hash", ASCENDING)], name="share_hash", sparse=True))
INDEXES["partner_requests"].append(IndexModel([("token_hash", ASCENDING)], name="token_hash", sparse=True))
PLATFORM_INDEXES = {"users": INDEXES.pop("users"), "orgs": INDEXES.pop("orgs"),
                    "link_index": [IndexModel([("org_id", ASCENDING)], name="org")]}


async def ensure_indexes() -> None:
    """Index de la base plateforme, puis de chaque base société (création si absente)."""
    for collection, models in PLATFORM_INDEXES.items():
        for model in models:
            try:
                await tenants.CLUSTERS.control[collection].create_indexes([model])
            except Exception as exc:
                logger.error("ensure_indexes(platform.%s.%s): %s", collection, model.document["name"], exc)
    async for org in tenants.CLUSTERS.control.orgs.find({}, {"_id": 0, "id": 1}):
        try:
            await tenants.provision(org["id"], INDEXES)
        except Exception as exc:
            logger.error("provision(%s): %s", org["id"], exc)


from security import APP_ENV, PROD  # noqa: E402

ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()] or ([] if PROD else ["*"])


def prod_problems() -> list:
    e, out = os.environ.get, []
    if not ORIGINS or "*" in ORIGINS:
        out.append("CORS_ORIGINS vide ou contenant *")
    out += [f"{k} manquante" for k in ("CLERK_AUTHORIZED_PARTIES", "CLERK_ISSUER", "CLERK_JWKS_URL", "FILE_SIGNING_SECRET", "WEBHOOK_CRON_SECRET") if not e(k)]
    if APP_ENV == "production" and not e("CLERK_SECRET_KEY", "").startswith("sk_live_"):
        out.append("CLERK_SECRET_KEY n'est pas une clé de production (sk_live_)")
    if any(h in e("MONGO_URL", "") for h in ("localhost", "127.0.0.1")):
        out.append("MONGO_URL pointe sur une base locale")
    return out


for _k in ("LLM_PROVIDER", "LLM_API_KEY", "EMAIL_FROM"):
    if PROD and not os.environ.get(_k):
        logger.warning("Variable %s absente : %s", _k, "les e-mails échoueront" if _k == "EMAIL_FROM" else "l'assistant IA sera indisponible")
if PROD and prod_problems():
    raise RuntimeError(f"Démarrage refusé (ENV={APP_ENV or 'absente'} : règles de production). " + " ; ".join(prod_problems()) + ". Pour un poste de développement, définir ENV=development.")
app = FastAPI(title=os.environ.get("APP_NAME", "EventStudio"), **({"docs_url": None, "redoc_url": None, "openapi_url": None} if PROD else {}))


@app.exception_handler(Exception)
async def unhandled(request, exc):
    import uuid
    from starlette.responses import JSONResponse
    eid = uuid.uuid4().hex[:12]
    logger.exception("Erreur %s sur %s %s", eid, request.method, request.url.path)
    return JSONResponse({"detail": "Erreur interne. Réessayez, ou transmettez cet identifiant au support.", "error_id": eid}, status_code=500)
app.include_router(clerk_router)
app.include_router(main_router)
app.include_router(ops_router)
app.include_router(billing_router)
app.include_router(files_router)
app.include_router(comms_router)
app.include_router(delivery_router)
app.include_router(messaging_router)
app.include_router(providers_router)
app.include_router(i18n_router)
app.include_router(inbound_router)
from routes_quotes import router as quotes_router  # noqa: E402
app.include_router(quotes_router)
from routes_crm import router as crm_router  # noqa: E402
app.include_router(crm_router)
from routes_material import router as material_router  # noqa: E402
app.include_router(material_router)

from routes_portal import router as portal_router  # noqa: E402
from routes_portal_admin import router as portal_admin_router  # noqa: E402
from routes_music import router as music_router  # noqa: E402
from routes_staff import router as staff_router  # noqa: E402
app.include_router(staff_router)
from routes_admin import migrate_crm_tasks, router as admin_router  # noqa: E402
app.include_router(admin_router)
import routes_stock  # noqa: E402
app.include_router(routes_stock.router)
import routes_shortages  # noqa: E402
import routes_units  # noqa: E402
app.include_router(routes_units.router)
import routes_kits  # noqa: E402
app.include_router(routes_kits.router)
import contact_status  # noqa: E402
app.include_router(contact_status.router)
import routes_suppliers  # noqa: E402
import contact_people  # noqa: E402
import routes_finance  # noqa: E402
app.include_router(routes_finance.router)
import routes_finance_reports  # noqa: E402
app.include_router(routes_finance_reports.router)
import routes_forecast  # noqa: E402
import routes_contracts  # noqa: E402
app.include_router(routes_contracts.router)
import routes_communication  # noqa: E402
app.include_router(routes_communication.router)
app.include_router(routes_forecast.router)
app.include_router(contact_people.router)
app.include_router(routes_suppliers.router)
app.include_router(routes_shortages.router)
import routes_logistics  # noqa: E402
import routes_quote_blocks  # noqa: E402
app.include_router(routes_quote_blocks.router)
import routes_quote_logistics  # noqa: E402
app.include_router(routes_quote_logistics.router)
import routes_quote_sync  # noqa: E402
app.include_router(routes_quote_sync.router)
import routes_dj_coverage  # noqa: E402
app.include_router(routes_dj_coverage.router)
import routes_dj_conflicts  # noqa: E402
import routes_pack_i18n  # noqa: E402
import routes_titles  # noqa: E402
import routes_statements  # noqa: E402
import routes_tax  # noqa: E402
app.include_router(routes_tax.router)
import routes_social  # noqa: E402
import routes_social_pay  # noqa: E402
import routes_members  # noqa: E402
import trash  # noqa: E402
app.include_router(trash.router)
app.include_router(routes_members.router)
app.include_router(routes_social.router)
app.include_router(routes_social_pay.router)
app.include_router(routes_statements.router)
app.include_router(routes_titles.router)
app.include_router(routes_pack_i18n.router)
app.include_router(routes_dj_conflicts.router)
import routes_works  # noqa: E402
app.include_router(routes_works.router)
import routes_works_planning  # noqa: E402
app.include_router(routes_works_planning.router)
import routes_schedule  # noqa: E402
app.include_router(routes_schedule.router)
import routes_reuse  # noqa: E402
app.include_router(routes_reuse.router)
import routes_quote_docs  # noqa: E402
app.include_router(routes_quote_docs.router)
import routes_supplier_quotes  # noqa: E402
app.include_router(routes_supplier_quotes.router)
import routes_wedding  # noqa: E402
app.include_router(routes_wedding.router)
for _coll, _keys in routes_wedding.INDEXES.items():  # module Wedding planner : index des bases société
    INDEXES.setdefault(_coll, []).extend(IndexModel(k, name="_".join(f"{f}_{d}" for f, d in k)) for k in _keys)
import routes_dj  # noqa: E402
app.include_router(routes_dj.router)
import access_grid  # noqa: E402
import routes_access  # noqa: E402
app.include_router(routes_access.router)
app.include_router(routes_logistics.router)
app.include_router(music_router)
from security import harden  # noqa: E402
app.include_router(portal_router)
app.include_router(portal_admin_router)
app.middleware("http")(routes_access.scrub_mw)
app.middleware("http")(harden)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.get("/api/health")
async def health():
    await db.command("ping")
    return {"status": "ok"}


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _split_on_boot() -> None:
    """Préproduction uniquement : migration à blanc de la base unique (SRC_MONGO_URL / SRC_DB)
    vers la base plateforme + une base par société, au démarrage, si la destination est vide.
    La source n'est jamais modifiée. Rapport dans les journaux Render."""
    if os.environ.get("ENV", "").lower() == "production":
        raise RuntimeError("SPLIT_ON_BOOT interdit en production : utilisez scripts_saas/split_tenants.py")
    if await tenants.CLUSTERS.control.orgs.count_documents({}):
        logger.info("SPLIT_ON_BOOT : destination déjà remplie, migration ignorée")
        return
    from scripts_saas import split_tenants
    code = await split_tenants.main(apply=True, force=False, clusters=True)
    logger.warning("SPLIT_ON_BOOT terminé : %s", "aucun écart" if code == 0 else "ÉCARTS, voir le rapport ci-dessus")


@app.on_event("startup")
async def startup():
    import migrations
    if os.environ.get("SPLIT_ON_BOOT", "").lower() == "true":
        await _split_on_boot()
    await tenants.assert_split_done()
    await tenants.load_placements()
    await seed_module_defs()
    access_grid.init(app)
    if os.environ.get("RUN_MIGRATIONS", "").lower() == "true":
        await migrations.run_all(True)
    else:
        todo = await migrations.pending_all()
        if todo:
            logger.warning("Migrations en attente (non lancées sans RUN_MIGRATIONS=true) : %s", todo)
    if PROD:
        n = await db.orgs.count_documents({"$or": [{"slug": "qa-sandbox"}, {"name": {"$regex": "^TEST_"}}]})
        if n:
            logger.error("PRODUCTION : %s société(s) de test présente(s). Lancez scripts/purge_test_data.py", n)
    app.state.index_task = asyncio.create_task(ensure_indexes())
    app.state.scheduler = start_scheduler()


@app.on_event("shutdown")
async def shutdown_db_client():
    app.state.scheduler.shutdown(wait=False)
    app.state.index_task.cancel()
    with suppress(asyncio.CancelledError):
        await app.state.index_task
    tenants.CLUSTERS.close()
