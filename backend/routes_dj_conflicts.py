"""DJ : détection des conflits de créneau au moment de la sélection (contrôle serveur, jamais seulement l'interface)."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import routes_dj as dj
from core import Ctx, db, now_iso

router = APIRouter(prefix="/api")
ASK = ["availability_requested", "available"]
LABEL = {"option_requested": "en option", "option_accepted": "en option", "option_conditions": "en option", "confirmed": "confirmé", "acknowledged": "confirmé", "availability_requested": "sollicité", "available": "sollicité"}
MARGIN, REST = 120, 360
HARD = ("blocking", "unavailable")
ORDER = {"blocking": 0, "unavailable": 0, "probable": 1, "tentative": 2}
fr = lambda d: f"{d[8:10]}/{d[5:7]}/{d[:4]}"  # noqa: E731


def span(day: str, st: str, en: str) -> tuple:
    if not st or not en:
        a = datetime.fromisoformat(day)
        return a, a + timedelta(days=1), False
    a, e = datetime.fromisoformat(f"{day}T{st}"), datetime.fromisoformat(f"{day}T{en}")
    return a, e + timedelta(days=1) if e <= a else e, True


async def margin_of(org_id: str) -> int:
    m = (await db.orgs.find_one({"id": org_id}, {"_id": 0, "dj_travel_margin_min": 1}) or {}).get("dj_travel_margin_min")
    return MARGIN if m is None else m


async def find(org_id: str, pid: str, s: datetime, e: datetime, venue_id: str = "", exclude: str = "", event_id: str = "") -> list:
    import routes_quote_logistics as ql
    org = await db.orgs.find_one({"id": org_id}, {"_id": 0}) or {}
    margin = MARGIN if org.get("dj_travel_margin_min") is None else org["dj_travel_margin_min"]
    here = await db.venues.find_one({"org_id": org_id, "id": venue_id or "-"}, {"_id": 0}) or {}
    out = []
    q = {"org_id": org_id, "provider_id": pid, "status": {"$in": dj.LIVE + ASK}, "date": {"$gte": (s - timedelta(days=2)).date().isoformat(), "$lte": (e + timedelta(days=2)).date().isoformat()}, "id": {"$ne": exclude}, "event_id": {"$ne": event_id}}
    async for b in db.dj_bookings.find(q, {"_id": 0}):
        ev = await db.events.find_one({"org_id": org_id, "id": b["event_id"], "deleted_at": None}, {"_id": 0, "code": 1, "title": 1, "status": 1, "venue_id": 1})
        if not ev:
            continue
        v = await db.venues.find_one({"org_id": org_id, "id": ev.get("venue_id") or "-"}, {"_id": 0}) or {}
        a, z, timed = span(b["date"], b.get("start_time"), b.get("end_time"))
        firm = b["status"] in ("confirmed", "acknowledged") or (b["status"] in dj.OPEN and (ev["status"] not in ("demande", "devis_envoye") or bool(await db.quotes.find_one({"org_id": org_id, "event_id": b["event_id"], "status": "accepte", "active": {"$ne": False}}, {"_id": 1}))))
        level, note, travel = "", "", None
        if a < e and s < z:
            level, note = ("blocking" if firm else "tentative"), ("" if timed else " (horaires à préciser)")
        elif firm:
            first_end, second_start = (z, s) if s >= z else (e, a)
            gap = (second_start - first_end).total_seconds() / 60
            travel = (await ql.road(org, here, v)).get("minutes") if here and v and here.get("id") != v.get("id") else (0 if here and v else None)
            rest = REST if first_end.hour < 6 else 0
            if travel is not None and gap < travel + margin + rest:
                level, note = "probable", f" — {int(gap // 60)} h entre les deux, trajet estimé {travel} min + {margin} min d'installation" + (f" + {rest // 60} h de repos après une fin de nuit" if rest else "")
            elif travel is None and (gap < margin + rest or first_end.date() == second_start.date()):
                level, note = "probable", " — même jour, vérifier le trajet"
        if level:
            out.append({"level": level, "booking_id": b["id"], "event_id": b["event_id"], "event_code": ev.get("code", ""), "event_title": ev.get("title", ""), "venue": v.get("name", ""), "date": b["date"], "start_time": b.get("start_time", ""),
                        "end_time": b.get("end_time", ""), "status": b["status"], "travel_minutes": travel, "accepted": bool(b.get("conflict_override")),
                        "detail": f"Déjà {LABEL[b['status']]} sur {ev.get('title', '')} — {v.get('name') or 'lieu à définir'}, {fr(b['date'])}, {b.get('start_time') or '?'} → {b.get('end_time') or '?'}{note}"})
    days = {s.date().isoformat()} | ({e.date().isoformat()} if e.hour >= 6 else set())
    async for a in db.dj_availability.find({"org_id": org_id, "provider_id": pid, "date": {"$in": list(days)}, "state": {"$in": ["unavailable", "external_busy"]}}, {"_id": 0, "date": 1}):
        out.append({"level": "unavailable", "booking_id": "", "event_id": "", "event_title": "", "venue": "", "date": a["date"], "start_time": "", "end_time": "", "status": "", "travel_minutes": None, "accepted": False,
                    "detail": f"Indisponible le {fr(a['date'])} (déclaré dans son calendrier)"})
    return sorted(out, key=lambda c: ORDER[c["level"]])


async def guard(org_id: str, pid: str, ev: dict, st: str, en: str, override: bool, reason: str) -> dict:
    """409 avec le détail si le DJ est en conflit bloquant ; forçage possible seulement avec un motif."""
    s, e, _ = span(ev["start"][:10], st, en)
    cs = [c for c in await find(org_id, pid, s, e, ev.get("venue_id") or "", "", ev["id"]) if c["level"] in HARD]
    if cs and not (override and reason.strip()):
        raise HTTPException(409, {"message": "Conflit DJ : " + cs[0]["detail"] + (" — motif obligatoire pour affecter quand même" if override else ""), "conflicts": cs})
    return {"conflict_override": bool(cs), "conflict_reason": reason.strip()[:300] if cs else "", "conflict_checked_at": now_iso()}


@router.get("/dj/selection")
async def selection(event_id: str, ctx: Ctx = Depends(dj.PM)):
    """Statut de conflit de chaque DJ pour le créneau de l'événement : alimente toutes les listes de sélection."""
    ev = await ctx.get("events", event_id)
    s, e = datetime.fromisoformat(ev["start"][:16]), datetime.fromisoformat(ev["end"][:16])
    v = await db.venues.find_one(ctx.q({"id": ev.get("venue_id") or "-"}), {"_id": 0, "name": 1}) or {}
    rows = []
    for p in await dj.djs(ctx, False):
        cs = await find(ctx.org_id, p["id"], s, e, ev.get("venue_id") or "", "", event_id)
        rows.append({"provider_id": p["id"], "name": dj.name_of(p, await dj.dj_doc(ctx.org_id, p["id"])), "level": cs[0]["level"] if cs else "free", "conflicts": cs})
    return {"event": {"title": ev["title"], "code": ev.get("code", ""), "date": ev["start"][:10], "start_time": ev["start"][11:16], "end_time": ev["end"][11:16], "venue": v.get("name", "")}, "margin_min": await margin_of(ctx.org_id),
            "djs": sorted(rows, key=lambda r: ({"free": 0, "tentative": 1, "probable": 2}.get(r["level"], 3), r["name"]))}


@router.get("/dj/{pid}/conflicts")
async def conflicts(pid: str, start: str, end: str, venue_id: str = "", exclude_booking_id: str = "", event_id: str = "", ctx: Ctx = Depends(dj.PM)):
    await ctx.get("provider_profiles", pid)
    try:
        s, e = datetime.fromisoformat(start[:16]), datetime.fromisoformat(end[:16])
    except ValueError:
        raise HTTPException(400, "Créneau invalide (AAAA-MM-JJTHH:MM)")
    return await find(ctx.org_id, pid, s, max(e, s + timedelta(minutes=1)), venue_id, exclude_booking_id, event_id)


class MarginIn(BaseModel):
    minutes: int = Field(ge=0, le=720)


@router.put("/dj/conflict-settings")
async def put_margin(body: MarginIn, ctx: Ctx = Depends(dj.PM)):
    await db.orgs.update_one({"id": ctx.org_id}, {"$set": {"dj_travel_margin_min": body.minutes}})
    return {"margin_min": body.minutes}


async def on_event_moved(org_id: str, ev: dict) -> list:
    """Date ou horaires modifiés : les réservations suivent, les forçages tombent et le contrôle est relancé."""
    out = []
    async for b in db.dj_bookings.find({"org_id": org_id, "event_id": ev["id"], "status": {"$in": dj.LIVE + ASK}}, {"_id": 0}):
        new = {"date": ev["start"][:10], "start_time": ev["start"][11:16], "end_time": ev["end"][11:16]}
        if all(b.get(k) == v for k, v in new.items()):
            continue
        await db.dj_bookings.update_one({"org_id": org_id, "id": b["id"]}, {"$set": {**new, "conflict_override": False, "conflict_reason": "", "conflict_checked_at": now_iso()}})
        await db.dj_availability.update_many({"org_id": org_id, "provider_id": b["provider_id"], "booking_id": b["id"]}, {"$set": {"date": new["date"]}})
        await db.dj_bookings.update_many({"org_id": org_id, "provider_id": b["provider_id"], "conflict_override": True}, {"$set": {"conflict_override": False}})
        s, e, _ = span(new["date"], new["start_time"], new["end_time"])
        for c in await find(org_id, b["provider_id"], s, e, ev.get("venue_id") or "", b["id"], ev["id"]):
            if c["level"] in HARD and b["status"] in dj.LIVE:
                import routes_stock
                out.append(f"{b['provider_name']} : {c['detail']}")
                await routes_stock.task(org_id, f"Conflit DJ après changement de date : {b['provider_name']} ({ev.get('code', '')})", f"dj-conflict:{b['id']}:{new['date']}", desc=c["detail"])
    return out
