"""Logique partagée du module : réglages, notifications, événements, contacts, calculs."""
from datetime import UTC, date, datetime
from uuid import uuid4

from app.core.repository import TenantRepository
from app.core.tenancy import TenantContext
from app.platform.mailer import send_email

from .models import WeddingInfo
from .seed import DEFAULT_NOTIFICATION_PREFS, NOTIFICATION_TYPES, RUBRICS

MODULE = "wedding_planner"
WEDDINGS = "wp_weddings"
SETTINGS = "wp_settings"
QUESTIONS = "wp_questions"
RESPONSES = "wp_responses"
RECAPS = "wp_recaps"
FOOD = "wp_food"
NOTIFS = "wp_notifications"
AI_USAGE = "wp_ai_usage"
SETTINGS_ID = "settings"


def now() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    return now().date()


def repo(ctx: TenantContext, name: str) -> TenantRepository:
    return TenantRepository(ctx, name)


# --- Réglages de l'organisation ---------------------------------------------------

async def get_settings(ctx: TenantContext) -> dict:
    r = repo(ctx, SETTINGS)
    doc = await r.get(SETTINGS_ID)
    if not doc:
        doc = await r.insert({
            "_id": SETTINGS_ID, "form_id": None, "form_url": None, "notify_email": None,
            "notification_prefs": DEFAULT_NOTIFICATION_PREFS,
            "rubrics": [{"key": k, "title": t} for k, t in RUBRICS],
            "last_sync": None, "sync_error": None, "seed_applied": False,
        })
    prefs = {**DEFAULT_NOTIFICATION_PREFS, **(doc.get("notification_prefs") or {})}
    doc["notification_prefs"] = prefs
    return doc


async def update_settings(ctx: TenantContext, changes: dict) -> dict:
    await get_settings(ctx)
    await repo(ctx, SETTINGS).update(SETTINGS_ID, changes)
    return await get_settings(ctx)


# --- Notifications (système générique : tout type déclaré dans NOTIFICATION_TYPES) --

async def notify(ctx: TenantContext, kind: str, text: str, *, wedding_id: str | None = None) -> None:
    if kind not in NOTIFICATION_TYPES:
        raise ValueError(f"Type de notification inconnu : {kind}")
    s = await get_settings(ctx)
    pref = s["notification_prefs"].get(kind, {"app": True, "email": False})
    if pref.get("app"):
        await repo(ctx, NOTIFS).insert({"kind": kind, "text": text, "wedding_id": wedding_id, "read": False})
    if pref.get("email") and s.get("notify_email"):
        await send_email(s["notify_email"], text, f"<p>{_escape(text)}</p>")


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- Mariage ------------------------------------------------------------------------

def default_events(date_str: str | None, wd: bool, br: bool) -> list[dict]:
    d = date.fromisoformat(date_str) if date_str else None
    shift = (lambda n: (d.fromordinal(d.toordinal() + n)).isoformat()) if d else (lambda n: None)
    return [
        {"id": uuid4().hex[:10], "key": "wd", "name": "Welcome dinner", "enabled": wd, "fixed": False,
         "date": shift(-1), "place": "", "estimate": None},
        {"id": uuid4().hex[:10], "key": "dj", "name": "Jour J", "enabled": True, "fixed": True,
         "date": date_str, "place": "", "estimate": None},
        {"id": uuid4().hex[:10], "key": "br", "name": "Brunch", "enabled": br, "fixed": False,
         "date": shift(1), "place": "", "estimate": None},
    ]


def couple_names(info: dict) -> str:
    names = [p.get("first_name") for p in info.get("partners", []) if p.get("first_name")]
    if names:
        return " & ".join(names)
    emails = [p.get("email") for p in info.get("partners", []) if p.get("email")]
    return " & ".join(e.split("@")[0] for e in emails) or "Nouveau mariage"


def days_left(date_str: str | None) -> int | None:
    if not date_str:
        return None
    return max(0, (date.fromisoformat(date_str) - today()).days)


async def confirmed_counts(ctx: TenantContext, wedding: dict) -> dict[str, int]:
    """Nombre d'invités confirmés par événement, calculé depuis la Guest List (phase 2).

    Point d'extension unique : tant que la Guest List n'existe pas, aucun nombre confirmé,
    l'estimation saisie par l'organisatrice s'affiche partout.
    """
    return {}


def guests_for(event: dict, confirmed: dict[str, int]) -> tuple[int | None, str]:
    if confirmed.get(event["id"]):
        return confirmed[event["id"]], "guest_list"
    return event.get("estimate"), "estimate"


def progress(wedding: dict) -> int:
    """Avancement de la phase 1 : fiche complète (60 %) + questionnaire (40 %).
    Les modules suivants (prestataires, paiements, tâches) viendront s'y ajouter."""
    info = WeddingInfo(**wedding.get("info", {}))
    checks = [
        all(p.first_name and p.last_name and p.email for p in info.partners),
        bool(info.date), bool(info.venue), info.budget is not None, info.guests.total is not None,
        bool(info.ceremony.type), bool(info.ceremony.place and info.ceremony.time),
    ]
    score = 60 * sum(checks) / len(checks)
    if (wedding.get("questionnaire") or {}).get("submitted_at"):
        score += 40
    return round(score)


async def ensure_contacts(ctx: TenantContext, wedding: dict) -> list[str]:
    """Chaque partenaire est un contact du socle (rôle client) : une seule saisie, réutilisée par
    les devis, le CRM, la facturation. Crée ou met à jour les contacts, renvoie leurs ids."""
    contacts = repo(ctx, "contacts")
    ids = []
    for i, p in enumerate(wedding["info"]["partners"]):
        name = " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x) or (p.get("email") or f"Partenaire {i + 1}")
        data = {"kind": "person", "display_name": name, "email": p.get("email"), "phone": p.get("phone") or None,
                "roles": ["client"], "language": wedding.get("lang", "fr")}
        cid = (wedding.get("contact_ids") or [None, None])[i]
        if cid and await contacts.get(cid):
            await contacts.update(cid, data)
        elif p.get("email") or p.get("first_name"):
            cid = (await contacts.insert(data))["_id"]
        else:
            cid = None
        ids.append(cid)
    return ids


async def sync_core_events(ctx: TenantContext, wedding: dict) -> list[dict]:
    """Chaque événement daté du mariage existe aussi dans le module Événements du socle,
    pour que les autres modules (DJ, son et lumière, traiteur, logistique) s'y rattachent."""
    events = repo(ctx, "events")
    names = couple_names(wedding["info"])
    client_id = next((c for c in wedding.get("contact_ids") or [] if c), None)
    out = []
    for ev in wedding.get("events", []):
        core_id = ev.get("event_id")
        if not ev.get("enabled") or not ev.get("date"):
            if core_id:
                await events.update(core_id, {"status": "canceled"})
            out.append(ev)
            continue
        data = {
            "title": f"{names} · {ev['name']}", "status": "confirmed",
            "starts_at": datetime.fromisoformat(f"{ev['date']}T12:00:00+00:00"),
            "client_id": client_id, "venue_ids": [], "phases": [], "title_i18n": {},
            "enabled_modules": [MODULE], "wedding_id": wedding["_id"], "wedding_event_key": ev["key"],
        }
        if core_id and await events.get(core_id):
            await events.update(core_id, data)
        else:
            core_id = (await events.insert(data))["_id"]
        out.append({**ev, "event_id": core_id})
    return out


async def ai_credit(ctx: TenantContext) -> bool:
    """Décompte d'un crédit IA du mois. Faux si la limite du plan est atteinte (blocage doux)."""
    month = now().strftime("%Y-%m")
    r = repo(ctx, AI_USAGE)
    doc = await r.get(month)
    used = (doc or {}).get("used", 0)
    if used >= ctx.entitlements.limits.get("ai_credits", 0):
        return False
    if doc:
        await r.update(month, {"used": used + 1})
    else:
        await r.insert({"_id": month, "used": 1})
    return True
