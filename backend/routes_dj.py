"""DJ partenaires : disponibilités, options et confirmation, factures, classement et matching."""
import base64
import csv
import io
import logging
import os
from datetime import datetime, timedelta
from html import escape
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

import messaging_core as mc
import portal_core as po
from core import Ctx, audit, db, need, new_id, now_iso
from routes_files import read_upload, store_bytes
from routes_music import GENRES
from routes_portal import _profile, c_event, nf
from security import APP_ENV, DATA_GUARD

router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)
PM, PV, C = need("providers:manage"), need("portal:provider"), need("portal:client")
DAY = r"^\d{4}-\d{2}-\d{2}$"
OPEN = ["option_requested", "option_accepted", "option_conditions"]
LIVE = OPEN + ["confirmed", "acknowledged"]
VIBES = ["Élégant & lounge", "Chic & festif", "Généraliste toutes générations", "Club/électro", "Urbain", "Latino", "Rétro 80-2000", "International/US", "Bohème/guinguette"]
WEIGHTS = {"languages": 25, "vibe": 25, "genres": 20, "style": 10, "tier": 10, "event_type": 5, "reliability": 5, "bonus_available": 5}
TIERS = ["standard", "premium", "signature"]
LEVEL = {"fluent": 1.0, "correct": 0.7, "basic": 0.0}
PUBLIC = ("stage_name", "photo_url", "bio_fr", "bio_en", "media_links", "mc_languages", "genres", "event_types", "options", "cancellation_terms")
PRIVATE = ("vibe_tags", "animation_style", "ideal_clientele", "tier", "internal_rating", "internal_notes", "dj_status")


def plus(day: str, n: int) -> str:
    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=n)).strftime("%Y-%m-%d")


async def named(org_id: str, ps: list) -> list:
    cs = {c["id"]: c async for c in db.contacts.find({"org_id": org_id, "id": {"$in": [p.get("contact_id") for p in ps]}}, {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "company": 1})}
    for p in ps:
        c = cs.get(p.get("contact_id")) or {}
        p["name"] = p.get("name") or f"{c.get('first_name', '')} {c.get('last_name', '')}".strip() or c.get("company") or "DJ"
    return ps


async def djs(ctx: Ctx, inactive: bool = True) -> list:
    import contact_status as cs
    out = set() if inactive else await cs.banned(ctx.org_id)
    return await named(ctx.org_id, [p for p in await ctx.list("provider_profiles", {"categories": "dj", "status": {"$ne": "archived"}}, limit=500) if p.get("contact_id") not in out])


async def dj_doc(org_id: str, pid: str) -> dict:
    return await db.dj_profiles.find_one({"org_id": org_id, "provider_id": pid}, {"_id": 0}) or {"provider_id": pid}


def has_public(d: dict) -> bool:
    return any((d.get(k) or "").strip() for k in ("stage_name", "bio_fr", "bio_en"))


def name_of(p: dict, d: dict) -> str:
    return d.get("stage_name") or p.get("stage_name") or p.get("name") or "DJ"


async def notify(org_id: str, to: str, subject: str, body: str, event_id: str = "", booking_id: str = "", kind: str = "") -> None:
    """Hors production : journalisé seulement, aucun envoi réel."""
    sent = False
    if APP_ENV == "production" and to:
        from emailer import send_email
        sent = bool(await send_email(to=to, subject=subject, html="".join(f"<p>{escape(l)}</p>" for l in body.split("\n") if l.strip())))
    await db.dj_messages.insert_one({"id": new_id(), "org_id": org_id, "at": now_iso(), "to": to, "subject": subject, "body": body, "event_id": event_id, "booking_id": booking_id, "kind": kind, "sent": sent})


async def mail_of(org_id: str, p: dict) -> tuple:
    c = await db.contacts.find_one({"org_id": org_id, "id": p.get("contact_id")}, {"_id": 0}) or {}
    return c.get("email", ""), (p.get("language") or c.get("language") or "fr").lower().startswith("en")


async def blog(b: dict, action: str, by: str, detail: str = "") -> None:
    await db.dj_booking_logs.insert_one({"id": new_id(), "org_id": b["org_id"], "booking_id": b["id"], "event_id": b["event_id"], "at": now_iso(), "action": action, "by": by, "detail": detail})


# ---------- Disponibilités ----------
def eff(av: dict | None, meta: dict | None) -> str:
    if av:
        return "unavailable" if av["state"] == "external_busy" else av["state"]
    return "available_default" if (meta or {}).get("default_state") == "available" else "unknown"


class AvailIn(BaseModel):
    dates: List[str] = Field(default=[], max_length=400)
    weekday: Optional[int] = Field(None, ge=0, le=6)
    start: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    end: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    state: Literal["available", "unavailable", "maybe", "external_busy", "clear"]
    from_time: str = Field("", pattern=r"^(\d{2}:\d{2})?$")
    private_title: str = Field("", max_length=120)
    default_state: Optional[Literal["unknown", "available"]] = None


async def set_days(org_id: str, pid: str, days: list, state: str, source: str, **extra) -> int:
    locked = {a["date"] async for a in db.dj_availability.find({"org_id": org_id, "provider_id": pid, "date": {"$in": days}, "state": {"$in": ["option", "confirmed"]}}, {"date": 1})} if source == "dj" else set()
    days = [d for d in days if d not in locked]
    if state == "clear":
        await db.dj_availability.delete_many({"org_id": org_id, "provider_id": pid, "date": {"$in": days}, "state": {"$nin": ["option", "confirmed"]} if source == "dj" else {"$exists": True}})
    else:
        for d in days:
            await db.dj_availability.update_one({"org_id": org_id, "provider_id": pid, "date": d}, {"$set": {"state": state, "source": source, "updated_at": now_iso(), **extra}, "$setOnInsert": {"id": new_id()}}, upsert=True)
    return len(days)


async def my_dj(ctx: Ctx, request: Request) -> dict:
    p = await _profile(ctx, request)
    if "dj" not in (p.get("categories") or []):
        await nf(ctx, request)
    return p


@router.get("/portal/provider/dj/availability")
async def my_availability(request: Request, start: str = "", end: str = "", ctx: Ctx = Depends(PV)):
    p = await my_dj(ctx, request)
    start = start or po.today()
    rows = await db.dj_availability.find(ctx.q({"provider_id": p["id"], "date": {"$gte": start, "$lte": end or plus(start, 400)}}), {"_id": 0, "org_id": 0}).to_list(2000)
    return {"days": rows, "meta": await db.dj_calendar_meta.find_one(ctx.q({"provider_id": p["id"]}), {"_id": 0, "org_id": 0}) or {"default_state": "unknown", "last_updated_at": None}, "today": po.today()}


@router.put("/portal/provider/dj/availability")
async def put_availability(body: AvailIn, request: Request, ctx: Ctx = Depends(PV)):
    p = await my_dj(ctx, request)
    days = list(body.dates)
    if body.weekday is not None and body.start and body.end:
        d = datetime.strptime(body.start, "%Y-%m-%d")
        while d.strftime("%Y-%m-%d") <= body.end and len(days) < 400:
            if d.weekday() == body.weekday:
                days.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)
    n = await set_days(ctx.org_id, p["id"], days, body.state, "dj", from_time=body.from_time, private_title=body.private_title if body.state == "external_busy" else "")
    meta = {"last_updated_at": now_iso(), **({"default_state": body.default_state} if body.default_state else {})}
    await db.dj_calendar_meta.update_one(ctx.q({"provider_id": p["id"]}), {"$set": meta}, upsert=True)
    return {"updated": n}


async def avail_map(ctx: Ctx, start: str, end: str) -> tuple:
    av: dict = {}
    async for a in db.dj_availability.find(ctx.q({"date": {"$gte": start, "$lte": end}}), {"_id": 0}):
        av.setdefault(a["provider_id"], {})[a["date"]] = a
    meta = {m["provider_id"]: m async for m in db.dj_calendar_meta.find(ctx.q({}), {"_id": 0})}
    return av, meta


def stale(meta: dict | None) -> bool:
    return not (meta or {}).get("last_updated_at") or meta["last_updated_at"][:10] < plus(po.today(), -30)


@router.get("/dj/availability")
async def grid(start: str = "", end: str = "", inactive: bool = False, ctx: Ctx = Depends(PM)):
    start = start or po.today()
    end = end or plus(start, 62)
    av, meta = await avail_map(ctx, start, end)
    out = []
    for p in await djs(ctx, inactive):
        d = await dj_doc(ctx.org_id, p["id"])
        m = meta.get(p["id"])
        out.append({"provider_id": p["id"], "name": name_of(p, d), "last_updated_at": (m or {}).get("last_updated_at"), "stale": stale(m), "default_state": (m or {}).get("default_state", "unknown"),
                    "days": {day: {"state": eff(a, m), "from_time": a.get("from_time", "")} for day, a in av.get(p["id"], {}).items()}})
    return {"start": start, "end": end, "djs": out}


@router.get("/dj/search")
async def search(date: str, all: bool = False, inactive: bool = False, ctx: Ctx = Depends(PM)):
    av, meta = await avail_map(ctx, date, date)
    order = {"available": 0, "available_default": 1, "maybe": 2, "unknown": 3, "option": 4, "confirmed": 5, "unavailable": 6}
    rows = []
    for p in await djs(ctx, inactive):
        s = eff(av.get(p["id"], {}).get(date), meta.get(p["id"]))
        if all or order[s] <= 3:
            rows.append({"provider_id": p["id"], "name": name_of(p, await dj_doc(ctx.org_id, p["id"])), "state": s, "stale": stale(meta.get(p["id"]))})
    return sorted(rows, key=lambda r: (order[r["state"]], r["name"]))


# ---------- Profils ----------
class Lang(BaseModel):
    lang: str = Field(min_length=2, max_length=5)
    level: Literal["fluent", "correct", "basic"]


class Genre(BaseModel):
    key: str
    level: int = Field(ge=1, le=3)


class PublicIn(BaseModel):
    stage_name: str = Field("", max_length=120)
    photo_url: str = Field("", max_length=500)
    bio_fr: str = Field("", max_length=3000)
    bio_en: str = Field("", max_length=3000)
    media_links: List[str] = Field(default=[], max_length=12)
    mc_languages: List[Lang] = []
    genres: List[Genre] = []
    event_types: List[str] = []
    options: List[str] = []
    cancellation_terms: str = Field("", max_length=2000)


class FullIn(PublicIn):
    vibe_tags: List[str] = []
    animation_style: Literal["", "discreet", "balanced", "mc"] = ""
    ideal_clientele: List[str] = []
    tier: Literal["", "standard", "premium", "signature"] = ""
    internal_rating: int = Field(0, ge=0, le=5)
    internal_notes: str = Field("", max_length=4000)
    dj_status: Literal["active", "trial", "blocked"] = "active"


async def save_profile(org_id: str, pid: str, data: dict) -> dict:
    if "genres" in data:
        data["genres"] = [g for g in data["genres"] if g["key"] in GENRES]
    await db.dj_profiles.update_one({"org_id": org_id, "provider_id": pid}, {"$set": {**data, "updated_at": now_iso()}, "$setOnInsert": {"id": new_id()}}, upsert=True)
    return await dj_doc(org_id, pid)


@router.get("/portal/provider/dj/profile")
async def my_profile(request: Request, ctx: Ctx = Depends(PV)):
    p = await my_dj(ctx, request)
    d = await dj_doc(ctx.org_id, p["id"])
    return {**{k: d.get(k, [] if k in ("media_links", "mc_languages", "genres", "event_types", "options") else "") for k in PUBLIC}, "base_rate": p.get("base_rate", 0), "genre_list": {k: v[0] for k, v in GENRES.items()}}


@router.put("/portal/provider/dj/profile")
async def put_my_profile(body: PublicIn, request: Request, ctx: Ctx = Depends(PV)):
    p = await my_dj(ctx, request)
    await save_profile(ctx.org_id, p["id"], body.model_dump())
    return {"ok": True}


async def reliability(ctx: Ctx, pid: str) -> dict:
    bs = await ctx.list("dj_bookings", {"provider_id": pid}, limit=500)
    replied = sum(1 for b in bs if b.get("dj_reply"))
    return {"missions": sum(1 for b in bs if b["status"] in ("done", "invoiced", "paid")), "options": len(bs), "reply_rate": round(replied / len(bs), 2) if bs else None}


@router.get("/dj/profiles")
async def list_profiles(ctx: Ctx = Depends(PM)):
    out = []
    for p in await djs(ctx):
        d = await dj_doc(ctx.org_id, p["id"])
        out.append({**{k: d.get(k) for k in PUBLIC + PRIVATE}, "provider_id": p["id"], "name": name_of(p, d), "base_rate": p.get("base_rate", 0), "dj_status": d.get("dj_status", "active"), **await reliability(ctx, p["id"])})
    s = await settings(ctx.org_id)
    return {"djs": out, "vibes": s["vibe_tags"], "genres": {k: v[0] for k, v in GENRES.items()}}


@router.put("/dj/profiles/{pid}")
async def put_profile(pid: str, body: FullIn, ctx: Ctx = Depends(PM)):
    await ctx.get("provider_profiles", pid)
    return await save_profile(ctx.org_id, pid, body.model_dump(exclude_unset=True))


async def settings(org_id: str) -> dict:
    s = await db.dj_matching_settings.find_one({"org_id": org_id}, {"_id": 0}) or {}
    return {"vibe_tags": s.get("vibe_tags") or VIBES, "weights": {**WEIGHTS, **(s.get("weights") or {})}}


class SettingsIn(BaseModel):
    vibe_tags: List[str] = Field(min_length=1, max_length=40)
    weights: Dict[str, float]


@router.get("/dj/settings")
async def get_settings(ctx: Ctx = Depends(PM)):
    return await settings(ctx.org_id)


@router.put("/dj/settings")
async def put_settings(body: SettingsIn, ctx: Ctx = Depends(PM)):
    await db.dj_matching_settings.update_one({"org_id": ctx.org_id}, {"$set": {"vibe_tags": body.vibe_tags, "weights": {k: v for k, v in body.weights.items() if k in WEIGHTS}}}, upsert=True)
    return await settings(ctx.org_id)


# ---------- Vibe de l'événement et score ----------
class CriteriaIn(BaseModel):
    languages: List[str] = []
    vibe_tags: List[str] = []
    animation_style: Literal["", "discreet", "balanced", "mc"] = ""
    genres_love: List[str] = []
    genres_avoid: List[str] = []
    tier: Literal["", "standard", "premium", "signature"] = ""


async def criteria_of(ctx: Ctx, ev: dict) -> dict:
    c = await db.event_dj_criteria.find_one(ctx.q({"event_id": ev["id"]}), {"_id": 0, "org_id": 0})
    if c:
        return c
    cl = await db.contacts.find_one(ctx.q({"id": ev.get("client_id")}), {"_id": 0, "language": 1}) or {}
    mp = await db.music_plans.find_one(ctx.q({"event_id": ev["id"]}), {"_id": 0}) or {}
    langs = {(cl.get("language") or "fr")[:2].lower()} | {x.strip().lower()[:2] for x in str((mp.get("useful_info") or {}).get("languages") or "").replace(",", "/").split("/") if x.strip()}
    gp = mp.get("genre_preferences") or {}
    return {**CriteriaIn(languages=sorted(langs), genres_love=[k for k, v in gp.items() if v == "love"], genres_avoid=[k for k, v in gp.items() if v == "avoid"]).model_dump(), "prefilled": True}


def score(c: dict, d: dict, state: str, ev_type: str, w: dict) -> dict:
    lv = {(x.get("lang") or x.get("code") or "")[:2].lower(): LEVEL.get(x.get("level"), 0) for x in d.get("mc_languages") or []}
    out = []
    if state in ("unavailable", "option", "confirmed"):
        out.append("Indisponible à cette date")
    if d.get("dj_status") == "blocked":
        out.append("Ne plus solliciter")
    out += [f"N'anime pas en {x.upper()} (niveau « correct » requis)" for x in c["languages"] if lv.get(x, 0) < LEVEL["correct"]]
    lines = []

    def add(key: str, ratio: float, why: str) -> None:
        lines.append({"key": key, "points": round(w[key] * ratio, 1), "max": w[key], "why": why})
    add("languages", sum(lv.get(x, 0) for x in c["languages"]) / len(c["languages"]) if c["languages"] else 1, ", ".join(f"{x.upper()} {'courant' if lv.get(x) == 1 else 'correct' if lv.get(x) else 'non'}" for x in c["languages"]) or "Aucune langue requise")
    hit = [v for v in c["vibe_tags"] if v in (d.get("vibe_tags") or [])]
    add("vibe", len(hit) / len(c["vibe_tags"]) if c["vibe_tags"] else 1, f"{len(hit)}/{len(c['vibe_tags'])} vibe(s) : {', '.join(hit) or '—'}" if c["vibe_tags"] else "Aucune vibe demandée")
    g = {x["key"]: x["level"] for x in d.get("genres") or []}
    love = c["genres_love"]
    avoid = [k for k in c["genres_avoid"] if g.get(k) == 3]
    add("genres", max(0, (sum(g.get(k, 0) / 3 for k in love) / len(love) if love else 1) - 0.2 * len(avoid)), ", ".join(f"{GENRES.get(k, (k,))[0]} {g.get(k, 0)}/3" for k in love) or "Aucun genre demandé")
    st, need_st = d.get("animation_style") or "", c["animation_style"]
    add("style", 1 if not need_st or st == need_st else 0.5 if "balanced" in (st, need_st) else 0, "Style d'animation identique" if st == need_st and st else "Style proche ou non renseigné")
    t, nt = d.get("tier") or "", c["tier"]
    gap = abs(TIERS.index(t) - TIERS.index(nt)) if t and nt else 0 if not nt else 1
    add("tier", 1 if gap == 0 else 0.5 if gap == 1 else 0, f"Niveau {t or 'non renseigné'}")
    add("event_type", 1 if ev_type and ev_type in (d.get("event_types") or []) else 0, f"Type « {ev_type} » {'pratiqué' if ev_type in (d.get('event_types') or []) else 'non déclaré'}")
    add("reliability", (d.get("internal_rating") or 3) / 5, f"Note interne {d.get('internal_rating') or '—'}/5")
    if state == "available":
        lines.append({"key": "bonus_available", "points": w["bonus_available"], "max": w["bonus_available"], "why": "Disponible explicitement"})
    return {"score": min(100, round(sum(l["points"] for l in lines))), "lines": lines, "excluded": out}


async def ev_ctx(ctx: Ctx, eid: str) -> tuple:
    ev = await ctx.get("events", eid)
    return ev, (ev.get("start") or "")[:10]


@router.put("/events/{eid}/dj/criteria")
async def put_criteria(eid: str, body: CriteriaIn, ctx: Ctx = Depends(PM)):
    await ctx.get("events", eid)
    await db.event_dj_criteria.update_one(ctx.q({"event_id": eid}), {"$set": body.model_dump()}, upsert=True)
    return body.model_dump()


@router.get("/events/{eid}/dj/match")
async def match(eid: str, inactive: bool = False, ctx: Ctx = Depends(PM)):
    ev, day = await ev_ctx(ctx, eid)
    c, s = await criteria_of(ctx, ev), await settings(ctx.org_id)
    av, meta = await avail_map(ctx, day, day)
    rows = []
    for p in await djs(ctx, inactive):
        d = await dj_doc(ctx.org_id, p["id"])
        state = eff(av.get(p["id"], {}).get(day), meta.get(p["id"]))
        rows.append({"provider_id": p["id"], "name": name_of(p, d), "state": state, "base_rate": p.get("base_rate", 0), "tier": d.get("tier", ""), **score(c, d, state, ev.get("type", ""), s["weights"])})
    rows.sort(key=lambda r: -r["score"])
    return {"date": day, "criteria": c, "matches": [r for r in rows if not r["excluded"]], "excluded": [r for r in rows if r["excluded"]]}


# ---------- Options, confirmation ----------
class OptionsIn(BaseModel):
    provider_ids: List[str] = Field(min_length=1, max_length=3)
    proposed_fee: float = Field(ge=0)
    travel_fee: float = Field(0, ge=0)
    fee_tax_mode: Literal["ht", "ttc", "net"] = "ht"
    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    expires_at: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    conflict_override: bool = False
    conflict_reason: str = Field("", max_length=300)


async def last_quote(ctx_q, eid: str) -> dict:
    return await db.quotes.find_one(ctx_q({"event_id": eid, "active": {"$ne": False}}), {"_id": 0, "id": 1, "status": 1, "valid_until": 1, "number": 1}, sort=[("created_at", -1)]) or {}


async def venue_of(org_id: str, ev: dict) -> dict:
    return await db.venues.find_one({"org_id": org_id, "id": ev.get("venue_id")}, {"_id": 0}) or {}


@router.post("/events/{eid}/dj/options")
async def pose_options(eid: str, body: OptionsIn, ctx: Ctx = Depends(PM)):
    ev, day = await ev_ctx(ctx, eid)
    q = await last_quote(ctx.q, eid)
    exp = body.expires_at or (q.get("valid_until") if q.get("status") in ("brouillon", "envoye") and (q.get("valid_until") or "") >= po.today() else "") or plus(po.today(), 14)
    v, out = await venue_of(ctx.org_id, ev), []
    for rank, pid in enumerate(body.provider_ids, 1):
        p = (await named(ctx.org_id, [await ctx.get("provider_profiles", pid)]))[0]
        if "dj" not in (p.get("categories") or []) or await db.dj_bookings.find_one(ctx.q({"event_id": eid, "provider_id": pid, "status": {"$in": LIVE}})):
            raise HTTPException(409, f"{p.get('name') or 'Ce prestataire'} : pas un DJ, ou déjà sollicité pour cet événement")
        import routes_dj_conflicts as cf
        chk = await cf.guard(ctx.org_id, pid, ev, body.start_time, body.end_time, body.conflict_override, body.conflict_reason)
        b = await ctx.insert("dj_bookings", {**body.model_dump(exclude={"provider_ids", "expires_at", "conflict_override", "conflict_reason"}), **chk, "event_id": eid, "provider_id": pid, "provider_name": name_of(p, await dj_doc(ctx.org_id, pid)), "quote_id": q.get("id", ""),
                                             "preference_rank": rank, "status": "option_requested", "date": day, "city": v.get("city", ""), "event_type": ev.get("type", ""), "option_expires_at": exp,
                                             "dj_reply": "", "dj_comment": "", "counter_fee": None, "created_by": ctx.member.get("name", "")})
        to, en = await mail_of(ctx.org_id, p)
        await notify(ctx.org_id, to, f"Option — {day}" if not en else f"Hold request — {day}",
                     f"Exclusivity Events pose une option sur vous le {day} ({body.start_time}–{body.end_time}) à {v.get('city', '')}, {ev.get('type', '')}.\nCachet proposé : {body.proposed_fee:g} €.\nRépondez dans votre espace avant le {exp}.", eid, b["id"], "option")
        await blog(b, "option_requested", ctx.member.get("name", ""), f"rang {rank}, expire le {exp}")
        if chk["conflict_override"]:
            await blog(b, "conflict_forced", ctx.member.get("name", ""), chk["conflict_reason"])
        out.append(b)
    return out


def dj_view(b: dict, full: dict | None = None) -> dict:
    keys = ("id", "date", "start_time", "end_time", "city", "event_type", "proposed_fee", "travel_fee", "fee_tax_mode", "status", "option_expires_at", "dj_reply", "dj_comment", "counter_fee", "acknowledged_at", "mission_id", "cancel_reason")
    return {**{k: b.get(k) for k in keys}, **(full or {})}


async def my_booking(ctx: Ctx, request: Request, bid: str) -> tuple:
    p = await my_dj(ctx, request)
    b = await db.dj_bookings.find_one(ctx.q({"id": bid, "provider_id": p["id"]}), {"_id": 0})
    if not b:
        await nf(ctx, request)
    return p, b


async def _busy(org_id: str, b: dict) -> bool:
    """Côté DJ : simple oui / non, jamais le client ni le lieu de l'autre prestation."""
    import routes_dj_conflicts as cf
    s, e, _ = cf.span(b["date"], b.get("start_time"), b.get("end_time"))
    return any(c["level"] == "blocking" for c in await cf.find(org_id, b["provider_id"], s, e, "", b["id"], b["event_id"]))


@router.get("/portal/provider/dj/home")
async def dj_home(request: Request, ctx: Ctx = Depends(PV)):
    p = await my_dj(ctx, request)
    rows = []
    for b in await db.dj_bookings.find(ctx.q({"provider_id": p["id"], "status": {"$nin": ["option_lifted"]}}), {"_id": 0}).sort("date", 1).to_list(300):
        full = None
        if b["status"] in ("confirmed", "acknowledged", "done", "invoiced", "paid"):
            ev = await db.events.find_one(ctx.q({"id": b["event_id"]}), {"_id": 0}) or {}
            v = await venue_of(ctx.org_id, ev)
            full = {"event_title": ev.get("title", ""), "venue_name": v.get("name", ""), "address": f"{v.get('address', '')} {v.get('zip', '')} {v.get('city', '')}".strip(), "access": v.get("access_instructions", ""), "onsite_contacts": v.get("onsite_contacts") or []}
        row = dj_view(b, full)
        if b["status"] in OPEN:
            import routes_dj_conflicts as cf
            row["conflict"] = await _busy(ctx.org_id, b)
        rows.append(row)
    inv = await db.dj_invoices.find(ctx.q({"provider_id": p["id"], "kind": "dj"}), {"_id": 0, "org_id": 0, "extracted": 0}).to_list(200)
    return {"today": po.today(), "bookings": rows, "invoices": inv, "to_invoice": [r["id"] for r in rows if r["status"] == "done"]}


class ReplyIn(BaseModel):
    reply: Literal["accept", "refuse", "conditions"]
    comment: str = Field("", max_length=1000)
    counter_fee: Optional[float] = Field(None, ge=0)


@router.post("/portal/provider/dj/bookings/{bid}/reply")
async def reply(bid: str, body: ReplyIn, request: Request, ctx: Ctx = Depends(PV)):
    p, b = await my_booking(ctx, request, bid)
    if b["status"] not in OPEN:
        raise HTTPException(409, "Cette option n'attend plus de réponse")
    st = {"accept": "option_accepted", "refuse": "option_refused", "conditions": "option_conditions"}[body.reply]
    await db.dj_bookings.update_one(ctx.q({"id": bid}), {"$set": {"status": st, "dj_reply": body.reply, "dj_comment": body.comment, "counter_fee": body.counter_fee, "replied_at": now_iso()}})
    if body.reply == "accept":
        await set_days(ctx.org_id, p["id"], [b["date"]], "option", "booking", booking_id=bid)
    await blog(b, st, b["provider_name"], body.comment)
    import routes_stock
    nxt = await db.dj_bookings.find_one(ctx.q({"event_id": b["event_id"], "status": "option_requested", "id": {"$ne": bid}}), {"_id": 0}, sort=[("preference_rank", 1)]) if body.reply == "refuse" else None
    await routes_stock.task(ctx.org_id, f"DJ {b['provider_name']} : option {'acceptée' if body.reply == 'accept' else 'refusée' if body.reply == 'refuse' else 'sous conditions'} ({b['date']})", f"dj-reply:{bid}",
                            desc=(body.comment or "") + (f" DJ suivant en attente : {nxt['provider_name']}." if nxt else " Aucun autre DJ en option : proposez le suivant." if body.reply == "refuse" else ""))
    return {"status": st, "warning": "Vous avez déjà une prestation à ce créneau" if body.reply == "accept" and await _busy(ctx.org_id, b) else ""}


def release_text(b: dict, status: str, why: str = "", terms: str = "") -> tuple:
    d = f"{b['date'][8:10]}/{b['date'][5:7]}/{b['date'][:4]}"
    if status == "cancelled" and b["status"] in ("confirmed", "acknowledged"):
        return f"Annulation — {d}", f"Bonjour,\nLa prestation du {d} est annulée. Motif : {why}.\nConditions d'annulation : {terms or 'selon nos accords'}."
    return f"Vous êtes libre le {d}", f"Bonjour,\nLe projet du {d} pour lequel nous vous avions sollicité ne se fera pas avec nous : vous êtes de nouveau libre à cette date.\nMerci pour votre disponibilité, à très vite sur une prochaine date.\n\nExclusivity Events"


async def release(org_id: str, b: dict, status: str, by: str, why: str = "", subject: str = "", body: str = "") -> None:
    await db.dj_bookings.update_one({"org_id": org_id, "id": b["id"]}, {"$set": {"status": status, "cancel_reason": why, "cancelled_at": now_iso(), "release_pending": False, "release_sent_at": now_iso()}})
    await db.dj_availability.delete_many({"org_id": org_id, "provider_id": b["provider_id"], "booking_id": b["id"]})
    if b.get("mission_id"):
        await db.missions.update_one({"org_id": org_id, "id": b["mission_id"]}, {"$set": {"status": "cancelled"}})
    p = await db.provider_profiles.find_one({"org_id": org_id, "id": b["provider_id"]}, {"_id": 0}) or {}
    to, _ = await mail_of(org_id, p)
    sub, text = release_text(b, status, why, (await dj_doc(org_id, b["provider_id"])).get("cancellation_terms") or "")
    await notify(org_id, to, subject or sub, body or text, b["event_id"], b["id"], status)
    await blog(b, status, by, why)


async def draft(ctx: Ctx, b: dict) -> dict:
    ev = await ctx.get("events", b["event_id"])
    v = await venue_of(ctx.org_id, ev)
    p = await ctx.get("provider_profiles", b["provider_id"])
    to, en = await mail_of(ctx.org_id, p)
    fee = f"{b['proposed_fee']:g} € {b['fee_tax_mode'].upper()}" + (f" + {b['travel_fee']:g} € déplacement" if b.get("travel_fee") else "")
    contacts = ", ".join(f"{c.get('name', '')} {c.get('phone', '')}".strip() for c in v.get("onsite_contacts") or []) or "—"
    link = f"{(os.environ.get('APP_URL') or '').rstrip('/')}/portail"
    addr = f"{v.get('name', '')}, {v.get('address', '')} {v.get('zip', '')} {v.get('city', '')}".strip(", ")
    body = (f"Hello,\n\nWe confirm your booking on {b['date']}, {b['start_time']}–{b['end_time']}.\nVenue: {addr}\nOn-site contact: {contacts}\nAccess / parking: {v.get('access_instructions') or '—'}\nFee: {fee}\nMission and client music brief: {link}\n\nPlease acknowledge receipt in your space.\n\nExclusivity Events" if en else
            f"Bonjour,\n\nNous confirmons votre prestation du {b['date']}, de {b['start_time']} à {b['end_time']}.\nLieu : {addr}\nContact sur place : {contacts}\nAccès / parking : {v.get('access_instructions') or '—'}\nTenue : à préciser\nCachet : {fee}\nMatériel : {p.get('equipment_brought') or 'à préciser'}\nVotre mission et « Ma musique » du client : {link}\n\nMerci d'accuser réception dans votre espace.\n\nExclusivity Events")
    return {"to": to, "subject": (f"Booking confirmed — {b['date']}" if en else f"Confirmation de prestation — {b['date']}"), "body": body}


class ActionIn(BaseModel):
    reason: str = Field("", max_length=500)
    days: int = Field(7, ge=1, le=60)
    subject: str = Field("", max_length=200)
    body: str = Field("", max_length=6000)


@router.get("/dj/bookings/{bid}/confirmation-draft")
async def confirmation_draft(bid: str, ctx: Ctx = Depends(PM)):
    return await draft(ctx, await ctx.get("dj_bookings", bid))


@router.get("/dj/bookings/{bid}/release-draft")
async def release_draft(bid: str, ctx: Ctx = Depends(PM)):
    b = await ctx.get("dj_bookings", bid)
    to, _ = await mail_of(ctx.org_id, await ctx.get("provider_profiles", b["provider_id"]))
    sub, text = release_text(b, "option_lifted")
    return {"to": to, "subject": sub, "body": text}


class MsgIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=6000)


@router.post("/dj/bookings/{bid}/release-message")
async def release_message(bid: str, body: MsgIn, ctx: Ctx = Depends(PM)):
    """Demande de disponibilité close par un devis refusé ou expiré : message envoyé seulement sur clic."""
    b = await ctx.get("dj_bookings", bid, {"release_pending": True})
    to, _ = await mail_of(ctx.org_id, await ctx.get("provider_profiles", b["provider_id"]))
    await notify(ctx.org_id, to, body.subject, body.body, b["event_id"], bid, "release")
    await db.dj_bookings.update_one(ctx.q({"id": bid}), {"$set": {"release_pending": False, "release_sent_at": now_iso()}})
    await blog({**b, "org_id": ctx.org_id}, "release_message", ctx.member.get("name", ""))
    return {"ok": True, "to": to}


@router.post("/dj/bookings/{bid}/{action}")
async def booking_action(bid: str, action: Literal["confirm", "lift", "extend", "cancel"], body: ActionIn, ctx: Ctx = Depends(PM)):
    b, by = await ctx.get("dj_bookings", bid), ctx.member.get("name", "")
    if action == "extend":
        if b["status"] not in OPEN:
            raise HTTPException(409, "Option close")
        exp = plus(max(b["option_expires_at"], po.today()), body.days)
        await ctx.update("dj_bookings", bid, {"option_expires_at": exp, "alerted": False})
        await blog(b, "extended", by, exp)
    elif action == "lift":
        if b["status"] not in OPEN:
            raise HTTPException(409, "Option close")
        await release(ctx.org_id, b, "option_lifted", by, "", body.subject, body.body)
    elif action == "cancel":
        if b["status"] not in ("confirmed", "acknowledged") or not body.reason.strip():
            raise HTTPException(400, "Annulation : prestation confirmée et motif obligatoires")
        await release(ctx.org_id, b, "cancelled", by, body.reason, body.subject, body.body)
    else:
        if b["status"] not in ("option_accepted", "option_conditions", "option_requested"):
            raise HTTPException(409, "Cette option ne peut pas être confirmée")
        d = await draft(ctx, b)
        m = await ctx.insert("missions", {"request_id": "", "recipient_id": "", "provider_id": b["provider_id"], "provider_name": b["provider_name"], "event_id": b["event_id"], "category_key": "dj", "date": b["date"], "start_time": b["start_time"],
                                          "end_time": b["end_time"], "venue_city": b["city"], "agreed_rate": b["proposed_fee"], "agreed_travel_fee": b.get("travel_fee", 0), "vat_mode": "", "vat_rate": 0, "total_ht": b["proposed_fee"] + b.get("travel_fee", 0),
                                          "total_ttc": b["proposed_fee"] + b.get("travel_fee", 0), "equipment_needed": [], "equipment_note": "", "missing_equipment": [], "status": "confirmed", "dj_booking_id": bid})
        await ctx.update("dj_bookings", bid, {"status": "confirmed", "confirmed_at": now_iso(), "mission_id": m["id"]})
        await set_days(ctx.org_id, b["provider_id"], [b["date"]], "confirmed", "booking", booking_id=bid)
        await notify(ctx.org_id, d["to"], body.subject or d["subject"], body.body or d["body"], b["event_id"], bid, "confirmation")
        await blog(b, "confirmed", by)
        for o in await ctx.list("dj_bookings", {"event_id": b["event_id"], "status": {"$in": OPEN}, "id": {"$ne": bid}}):
            await release(ctx.org_id, o, "option_lifted", by)
    return await ctx.get("dj_bookings", bid)


@router.post("/portal/provider/dj/bookings/{bid}/ack")
async def ack(bid: str, request: Request, ctx: Ctx = Depends(PV)):
    _, b = await my_booking(ctx, request, bid)
    if b["status"] != "confirmed":
        raise HTTPException(409, "Rien à accuser")
    await db.dj_bookings.update_one(ctx.q({"id": bid}), {"$set": {"status": "acknowledged", "acknowledged_at": now_iso()}})
    await blog(b, "acknowledged", b["provider_name"])
    return {"ok": True}


@router.get("/events/{eid}/dj")
async def event_dj(eid: str, ctx: Ctx = Depends(PM)):
    ev, day = await ev_ctx(ctx, eid)
    bs = await ctx.list("dj_bookings", {"event_id": eid}, sort=[("preference_rank", 1)])
    q = await last_quote(ctx.q, eid)
    ready = next((b for b in bs if b["status"] == "option_accepted"), None)
    banner = {"kind": "confirm", "booking_id": ready["id"], "text": f"Le client a accepté — confirmer {ready['provider_name']} ?"} if q.get("status") == "accepte" and ready else \
        {"kind": "lift", "text": "Devis refusé ou expiré : lever les options ?"} if q.get("status") in ("refuse", "expire") and any(b["status"] in OPEN for b in bs) else None
    sl = await db.client_dj_shortlists.find_one(ctx.q({"event_id": eid}), {"_id": 0, "org_id": 0}) or {"provider_ids": [], "preferred_id": ""}
    ps = {p["id"]: p.get("contact_id") async for p in db.provider_profiles.find(ctx.q({"id": {"$in": [b["provider_id"] for b in bs]}}), {"_id": 0, "id": 1, "contact_id": 1})}
    cs = {c["id"]: c async for c in db.contacts.find(ctx.q({"id": {"$in": list(ps.values())}}), {"_id": 0, "id": 1, "email": 1, "phone": 1})}
    contacts = {pid: {"email": (cs.get(cid) or {}).get("email", ""), "phone": (cs.get(cid) or {}).get("phone", "")} for pid, cid in ps.items()}
    return {"date": day, "show_client": bool(ev.get("dj_show_client")), "contacts": contacts, "criteria": await criteria_of(ctx, ev), "bookings": bs, "quote": q, "banner": banner, "shortlist": sl, "vibes": (await settings(ctx.org_id))["vibe_tags"], "genres": {k: v[0] for k, v in GENRES.items()},
            "log": await ctx.list("dj_booking_logs", {"event_id": eid}, sort=[("at", -1)], limit=100), "messages": await ctx.list("dj_messages", {"event_id": eid}, sort=[("at", -1)], limit=50)}


async def on_quote_accepted(org_id: str, q: dict) -> None:
    b = await db.dj_bookings.find_one({"org_id": org_id, "event_id": q.get("event_id") or "__", "status": "option_accepted"}, {"_id": 0}, sort=[("preference_rank", 1)])
    if b:
        import routes_stock
        await routes_stock.task(org_id, f"Devis {q.get('number', '')} accepté : confirmer le DJ {b['provider_name']}", f"dj-confirm:{b['id']}", desc="Ouvrez l'événement, bloc DJ, puis « Confirmer la prestation ».")


# ---------- Proposition au client ----------
class ShortlistIn(BaseModel):
    provider_ids: List[str] = Field(max_length=3)


@router.put("/events/{eid}/dj/shortlist")
async def put_shortlist(eid: str, body: ShortlistIn, ctx: Ctx = Depends(PM)):
    await ctx.get("events", eid)
    for pid in body.provider_ids:
        p = (await named(ctx.org_id, [await ctx.get("provider_profiles", pid)]))[0]
        if not has_public(await dj_doc(ctx.org_id, pid)):
            raise HTTPException(409, f"{p['name']} n'a pas encore rempli son profil public (nom de scène ou présentation) : impossible de le proposer au client.")
    await db.client_dj_shortlists.update_one(ctx.q({"event_id": eid}), {"$set": {"provider_ids": body.provider_ids, "updated_at": now_iso()}, "$setOnInsert": {"preferred_id": ""}}, upsert=True)
    return {"ok": True}


@router.get("/portal/client/events/{eid}/dj")
async def client_djs(eid: str, request: Request, ctx: Ctx = Depends(C)):
    await c_event(ctx, request, eid)
    sl = await db.client_dj_shortlists.find_one(ctx.q({"event_id": eid}), {"_id": 0}) or {}
    en = ((await db.contacts.find_one(ctx.q({"id": ctx.contact_id}), {"_id": 0, "language": 1}) or {}).get("language") or "fr").lower().startswith("en")
    out = []
    ids = sl.get("provider_ids") or []
    ps = {p["id"]: p for p in await named(ctx.org_id, await db.provider_profiles.find(ctx.q({"id": {"$in": ids}}), {"_id": 0}).to_list(10))}
    for pid in ids:
        d = await dj_doc(ctx.org_id, pid)
        if pid not in ps or not has_public(d):
            continue
        out.append({"id": pid, "stage_name": name_of(ps[pid], d), "photo_url": d.get("photo_url", ""), "bio": (d.get("bio_en") if en else "") or d.get("bio_fr", ""), "media_links": d.get("media_links") or [],
                    "languages": [x.get("lang") or x.get("code") or "" for x in d.get("mc_languages") or []]})
    ev = await db.events.find_one(ctx.q({"id": eid}), {"_id": 0, "dj_show_client": 1}) or {}
    conf = [b["provider_name"] async for b in db.dj_bookings.find(ctx.q({"event_id": eid, "status": {"$in": ["confirmed", "acknowledged"]}}), {"_id": 0, "provider_name": 1})] if ev.get("dj_show_client") else []
    return {"djs": out, "preferred_id": sl.get("preferred_id", ""), "confirmed": conf}


class PrefIn(BaseModel):
    provider_id: str


@router.post("/portal/client/events/{eid}/dj/preference")
async def client_pref(eid: str, body: PrefIn, request: Request, ctx: Ctx = Depends(C)):
    await c_event(ctx, request, eid)
    r = await db.client_dj_shortlists.update_one(ctx.q({"event_id": eid, "provider_ids": body.provider_id}), {"$set": {"preferred_id": body.provider_id, "preferred_at": now_iso()}})
    if not r.matched_count:
        await nf(ctx, request)
    import routes_stock
    await routes_stock.task(ctx.org_id, "Le client a indiqué son DJ préféré", f"dj-pref:{eid}", desc="Ouvrez l'événement, bloc DJ.")
    return {"ok": True}


# ---------- Factures ----------
INVOICE_PROMPT = ("Tu lis une facture de prestataire. Réponds uniquement en JSON, sans rien inventer (inconnu = \"\" ou 0) : "
                  '{"number": "", "date": "AAAA-MM-JJ", "issuer": "", "siret": "", "recipient": "", "total_ht": 0, "vat": 0, "total_ttc": 0, "mention_293b": false, "service_date": "AAAA-MM-JJ", "confidence": 1}')


async def read_invoice(data: bytes, ctype: str) -> dict | None:
    try:
        src = {"type": "base64", "media_type": ctype, "data": base64.b64encode(data).decode()}
        r = await mc.claude().messages.create(model=os.environ.get("LLM_MODEL") or os.environ.get("SUPPLIER_QUOTE_MODEL") or "claude-sonnet-5-5", max_tokens=1000, system=DATA_GUARD + " " + INVOICE_PROMPT,
                                              messages=[{"role": "user", "content": [{"type": "document" if ctype == "application/pdf" else "image", "source": src}, {"type": "text", "text": "Extrais la facture."}]}])
        from routes_admin import _json
        return _json("".join(b.text for b in r.content if b.type == "text"))
    except Exception as exc:
        mc.ai_fail(exc, False)
        return None


def check(x: dict | None, expected: float, org_name: str) -> tuple:
    if not x or float(x.get("confidence") or 0) < 0.6:
        return "manual", ["Lecture automatique incertaine : vérification manuelle"]
    why = []
    ht = float(x.get("total_ht") or x.get("total_ttc") or 0)
    if abs(ht - expected) > 0.01:
        why.append(f"Montant HT {ht:g} € au lieu de {expected:g} € prévus")
    if not float(x.get("vat") or 0) and not x.get("mention_293b"):
        why.append("Pas de TVA et mention « art. 293 B du CGI » absente")
    if org_name.split()[0].lower() not in str(x.get("recipient") or "").lower():
        why.append(f"Destinataire différent de {org_name}")
    return ("conform" if not why else "mismatch"), why


@router.post("/portal/provider/dj/invoices")
async def deposit(request: Request, booking_ids: str = Form(...), file: UploadFile = File(...), ctx: Ctx = Depends(PV)):
    p = await my_dj(ctx, request)
    bs = [(await my_booking(ctx, request, bid))[1] for bid in booking_ids.split(",") if bid]
    if not bs or any(b["status"] not in ("done", "invoiced") for b in bs):
        raise HTTPException(409, "La facture se dépose sur une mission réalisée")
    data, ctype = await read_upload(file)
    x = await read_invoice(data, ctype)
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "name": 1, "legal_name": 1}) or {}
    expected = round(sum(b["proposed_fee"] + b.get("travel_fee", 0) for b in bs), 2)
    status, why = check(x, expected, org.get("legal_name") or org.get("name") or "Exclusivity")
    ev = await db.events.find_one(ctx.q({"id": bs[0]["event_id"]}), {"_id": 0, "title": 1}) or {}
    safe = lambda s: "".join(ch for ch in str(s) if ch.isalnum() or ch in "-")[:40]  # noqa: E731
    name = f"{po.today()}_Facture_{safe(bs[0]['provider_name'])}_{safe(ev.get('title', ''))}_{safe((x or {}).get('number') or 'sans-numero')}.pdf"
    await db.dj_invoices.update_many(ctx.q({"provider_id": p["id"], "kind": "dj", "booking_ids": {"$in": [b["id"] for b in bs]}, "status": "refused"}), {"$set": {"superseded": True}})
    inv = await ctx.insert("dj_invoices", {"kind": "dj", "provider_id": p["id"], "provider_name": bs[0]["provider_name"], "mission_id": bs[0].get("mission_id", ""), "event_id": bs[0]["event_id"], "booking_ids": [b["id"] for b in bs],
                                                 "number": (x or {}).get("number", ""), "date": (x or {}).get("date") or po.today(), "service_date": bs[0]["date"], "total_ht": float((x or {}).get("total_ht") or 0), "vat_rate": 0,
                                                 "total_ttc": float((x or {}).get("total_ttc") or 0), "file": await store_bytes(ctx.org_id, data, ctype, name, bs[0]["provider_name"]), "file_name": name, "status": "to_check", "paid_at": None,
                                                 "gap": round(float((x or {}).get("total_ht") or 0) - expected, 2), "expected_ht": expected, "extracted": x, "match_status": status, "mismatch_reasons": why})
    await db.dj_bookings.update_many(ctx.q({"id": {"$in": inv["booking_ids"]}}), {"$set": {"status": "invoiced"}})
    import routes_stock
    await routes_stock.task(ctx.org_id, f"Facture DJ {inv['provider_name']} déposée ({'conforme' if status == 'conform' else 'écart' if status == 'mismatch' else 'à vérifier'})", f"dj-invoice:{inv['id']}", desc=" ; ".join(why))
    return {"id": inv["id"], "match_status": status, "mismatch_reasons": why}


@router.get("/dj/invoices")
async def invoices(status: str = "", provider_id: str = "", start: str = "", end: str = "", ctx: Ctx = Depends(PM)):
    f: dict = {"kind": "dj", "superseded": {"$ne": True}, **({"status": status} if status else {}), **({"provider_id": provider_id} if provider_id else {})}
    if start or end:
        f["service_date"] = {"$gte": start or "0", "$lte": end or "9"}
    return await ctx.list("dj_invoices", f, sort=[("created_at", -1)], limit=500)


@router.get("/dj/invoices/export")
async def export(ctx: Ctx = Depends(PM)):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["DJ", "Numéro", "Date", "Prestation", "HT", "TTC", "Prévu HT", "Contrôle", "Statut", "Payée le", "Fichier"])
    for i in await ctx.list("dj_invoices", {"kind": "dj", "superseded": {"$ne": True}}, limit=2000):
        w.writerow([i["provider_name"], i["number"], i["date"], i["service_date"], i["total_ht"], i["total_ttc"], i["expected_ht"], i["match_status"], i["status"], i.get("paid_at") or "", i.get("file_name", "")])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="factures-dj.csv"'})


class InvActIn(BaseModel):
    reason: str = Field("", max_length=500)
    paid_at: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    mode: str = Field("", max_length=40)


@router.post("/dj/invoices/{iid}/{action}")
async def invoice_action(iid: str, action: Literal["validate", "refuse", "paid"], body: InvActIn, ctx: Ctx = Depends(PM)):
    i = await ctx.get("dj_invoices", iid)
    if i.get("kind") != "dj" or (action == "paid" and i["status"] != "validated") or (action != "paid" and i["status"] != "to_check"):
        raise HTTPException(409, "Action impossible dans cet état")
    if action == "refuse" and not body.reason.strip():
        raise HTTPException(400, "Motif obligatoire")
    st = {"validate": "validated", "refuse": "refused", "paid": "paid"}[action]
    await ctx.update("dj_invoices", iid, {"status": st, **({"refuse_reason": body.reason} if action == "refuse" else {}), **({"paid_at": body.paid_at or po.today(), "payment_mode": body.mode} if action == "paid" else {})})
    if action != "validate":
        await db.dj_bookings.update_many(ctx.q({"id": {"$in": i["booking_ids"]}}), {"$set": {"status": "done" if action == "refuse" else "paid"}})
        p = await ctx.get("provider_profiles", i["provider_id"])
        to, _ = await mail_of(ctx.org_id, p)
        await notify(ctx.org_id, to, "Facture refusée" if action == "refuse" else "Facture payée", f"Bonjour,\nVotre facture {i['number']} {'est refusée : ' + body.reason + '. Merci de la redéposer.' if action == 'refuse' else 'a été payée le ' + (body.paid_at or po.today()) + '.'}", i["event_id"], i["booking_ids"][0], f"invoice_{st}")
    await audit(ctx.org_id, ctx.member, f"dj_invoice_{st}", i["number"] or iid, body.reason)
    return await ctx.get("dj_invoices", iid)


# ---------- Rappels quotidiens ----------
async def tick() -> None:
    import routes_stock
    day = po.today()
    async for b in db.dj_bookings.find({"status": {"$in": LIVE + ["done"]}}, {"_id": 0}):
        oid, key = b["org_id"], {"org_id": b["org_id"], "id": b["id"]}
        p = await db.provider_profiles.find_one({"org_id": oid, "id": b["provider_id"]}, {"_id": 0}) or {}
        to, _ = await mail_of(oid, p)
        old = (b.get("confirmed_at") or b["created_at"])[:10] <= plus(day, -2)
        if b["status"] in OPEN and b["option_expires_at"] < day:
            await release(oid, b, "option_lifted", "Système", "expiration")
        elif b["status"] in OPEN and b["option_expires_at"] <= plus(day, 3) and not b.get("alerted"):
            await routes_stock.task(oid, f"Option DJ {b['provider_name']} : expire le {b['option_expires_at']}", f"dj-expiry:{b['id']}:{b['option_expires_at']}", desc="Prolonger ou lever l'option depuis l'événement.")
            await db.dj_bookings.update_one(key, {"$set": {"alerted": True}})
        elif b["status"] in ("option_requested", "confirmed") and old and not b.get(f"reminded_{b['status']}"):
            await notify(oid, to, f"Rappel — {b['date']}", "Bonjour,\nMerci de répondre à l'option dans votre espace." if b["status"] == "option_requested" else "Bonjour,\nMerci d'accuser réception de la confirmation dans votre espace.", b["event_id"], b["id"], "reminder")
            await db.dj_bookings.update_one(key, {"$set": {f"reminded_{b['status']}": True}})
        elif b["status"] in ("confirmed", "acknowledged") and b["date"] < day:
            await db.dj_bookings.update_one(key, {"$set": {"status": "done"}})
            await db.missions.update_one({"org_id": oid, "id": b.get("mission_id")}, {"$set": {"status": "done"}})
        elif b["status"] == "done" and b["date"] <= plus(day, -7) and not b.get("invoice_reminded"):
            await notify(oid, to, f"Facture à déposer — prestation du {b['date']}", "Bonjour,\nMerci de déposer votre facture dans votre espace.", b["event_id"], b["id"], "invoice_reminder")
            await db.dj_bookings.update_one(key, {"$set": {"invoice_reminded": True}})
    if day.endswith("-01"):
        async for p in db.provider_profiles.find({"categories": "dj", "status": {"$ne": "archived"}}, {"_id": 0}):
            m = await db.dj_calendar_meta.find_one({"org_id": p["org_id"], "provider_id": p["id"]}, {"_id": 0})
            if stale(m):
                to, _ = await mail_of(p["org_id"], p)
                await notify(p["org_id"], to, "Vos disponibilités des 6 prochains mois", "Bonjour,\nMerci de mettre à jour votre calendrier, en particulier les week-ends non renseignés des 6 prochains mois.", kind="calendar_reminder")
