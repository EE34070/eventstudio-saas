"""Prestations DJ : couverture (aucun DJ / option / confirmé), alertes, affectation directe et ajout rapide d'un DJ."""
import tenant_router as tenants
from datetime import date, datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import routes_dj as dj
from core import Ctx, check_expiry, db, ensure_link, link_doc, now_iso

router = APIRouter(prefix="/api")
DONE = ("confirmed", "acknowledged")


ASK = ("availability_requested", "available", "not_available")
OPENQ = ["brouillon", "envoye", "vu", "negociation"]
isdj = lambda lab: any(k in f" {(lab or '').lower()} " for k in (" dj ", "dj-", "formule signature", "formule excellence"))  # noqa: E731


async def cover(org_id: str, frm: str = "", to: str = "", only: str = "", pending: bool = False) -> dict:
    key = {"org_id": org_id}
    frm = frm or date.today().isoformat()
    f = {**key, "deleted_at": None, "status": {"$nin": ["cloture", "annule"]}, "start": {"$gte": frm, **({"$lte": to + "T99"} if to else {})}, **({"id": only} if only else {})}
    evs = await db.events.find(f, {"_id": 0, "id": 1, "code": 1, "title": 1, "start": 1, "end": 1, "status": 1, "venue_id": 1, "language": 1, "dj_required": 1}).sort("start", 1).to_list(5000)
    ids = [e["id"] for e in evs]
    mod = {m["event_id"] async for m in db.event_modules.find({**key, "event_id": {"$in": ids}, "module_key": "dj", "status": "actif"}, {"event_id": 1})}
    formula: dict = {}
    async for q in db.quotes.find({**key, "event_id": {"$in": ids}, "status": "accepte", "active": {"$ne": False}}, {"_id": 0, "event_id": 1, "lines.label": 1}):
        for l in q.get("lines") or []:
            lab = f" {(l.get('label') or '').lower()} "
            if " dj " in lab or "dj-" in lab or "formule signature" in lab or "formule excellence" in lab:
                formula.setdefault(q["event_id"], l["label"])
    pend: dict = {}
    async for q in db.quotes.find({**key, "event_id": {"$in": ids}, "status": {"$in": OPENQ}, "active": {"$ne": False}}, {"_id": 0, "event_id": 1, "lines.label": 1}):
        for l in q.get("lines") or []:
            if isdj(l.get("label")):
                pend.setdefault(q["event_id"], l["label"])
    asks: dict = {}
    async for b in db.dj_bookings.find({**key, "status": {"$in": ASK}, "event_id": {"$in": ids}}, {"_id": 0}):
        asks.setdefault(b["event_id"], []).append({"booking_id": b["id"], "provider_id": b["provider_id"], "name": b["provider_name"], "status": b["status"]})
        if b["status"] == "availability_requested" and b.get("created_at", "") < (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat():
            import routes_stock
            await routes_stock.task(org_id, f"Relancer {b['provider_name']} : disponibilité demandée sans réponse depuis 48 h", f"dj-ask:{b['id']}")
    venues = {v["id"]: v.get("city") or v.get("name", "") async for v in db.venues.find(key, {"_id": 0, "id": 1, "city": 1, "name": 1})}
    books: dict = {}
    async for b in db.dj_bookings.find({**key, "status": {"$in": dj.LIVE}, "event_id": {"$in": ids}}, {"_id": 0}):
        books.setdefault(b["event_id"], []).append(b)
    today, days = date.today(), {}
    for e in evs:
        confirmed = e["status"] not in ("demande", "devis_envoye") or e["id"] in formula
        if (e["id"] not in mod and e["id"] not in formula and e["id"] not in pend) or (not confirmed and not pending):
            continue
        bs, left = books.get(e["id"], []), (date.fromisoformat(e["start"][:10]) - today).days
        conf, req = [b for b in bs if b["status"] in DONE], e.get("dj_required") or 1
        cov = "confirmed" if len(conf) >= req else "option" if bs else "none"
        days.setdefault(e["start"][:10], []).append({"event_id": e["id"], "code": e["code"], "title": e["title"], "city": venues.get(e.get("venue_id"), ""), "start": e["start"][11:16], "end": e["end"][11:16], "language": e.get("language") or "fr-FR",
                                                     "formula": formula.get(e["id"]) or pend.get(e["id"], ""), "status": e["status"], "coverage": cov, "confirmed": confirmed, "requests": asks.get(e["id"], []), "required": req, "days_left": left, "priority": "critical" if left <= 90 else "high" if left <= 180 else "normal",
                                                     "djs": [{"booking_id": b["id"], "provider_id": b["provider_id"], "name": b["provider_name"], "status": b["status"]} for b in bs]})
    out, alerts, none = [], [], 0
    for day, rows in days.items():
        seen, conflicts, okd = {}, [], set()
        for b in [b for bs in books.values() for b in bs if b["date"] == day]:
            prev = seen.get(b["provider_id"])
            if prev and prev["event_id"] != b["event_id"]:
                if b.get("conflict_override") or prev.get("conflict_override"):
                    okd |= {b["event_id"], prev["event_id"]}
                else:
                    conflicts.append(f"{b['provider_name']} est affecté à deux événements le {day[8:10]}/{day[5:7]}/{day[:4]}")
            seen[b["provider_id"]] = b
        for r in rows:
            r["conflict_accepted"] = r["event_id"] in okd
        allrows, rows = rows, [r for r in rows if r["confirmed"]]
        ok = sum(1 for r in rows if r["coverage"] == "confirmed")
        missing = [r for r in rows if r["coverage"] == "none"]
        none += len(missing)
        label = f"{day[8:10]}/{day[5:7]}/{day[:4]} — {len(rows)} prestation{'s' if len(rows) > 1 else ''} DJ : {ok} DJ affecté sur {len(rows)}"
        if not rows:
            label = f"{day[8:10]}/{day[5:7]}/{day[:4]} — devis DJ en cours (non confirmé)"
        out.append({"date": day, "label": label, "count": len(rows), "confirmed": ok, "red": bool(missing), "conflicts": sorted(set(conflicts)), "events": allrows})
        for c in set(conflicts) if len(rows) > 1 else []:
            alerts.append({"type": "conflit", "severity": "danger", "title": "Conflit DJ", "detail": c, "to": "/dj?tab=planning"})
        if len(rows) > 1 and missing:
            alerts.append({"type": "dj", "severity": "danger", "title": "Plusieurs prestations DJ le même jour", "detail": label, "to": "/dj?tab=planning"})
        for r in missing:
            if True:
                alerts.append({"type": "dj", "severity": "danger" if r["priority"] == "critical" else "warning", "event_id": r["event_id"], "title": "DJ non affecté" + {"critical": " — critique", "high": " — priorité haute", "normal": ""}[r["priority"]],
                               "detail": f"{r['code']} · {r['title']} — le {day[8:10]}/{day[5:7]}/{day[:4]} (J-{r['days_left']})"})
    return {"days": out, "without_dj": none, "alerts": sorted(alerts, key=lambda a: a["severity"] != "danger")}


@router.get("/dj/coverage")
async def coverage(frm: str = "", to: str = "", event_id: str = "", pending: bool = False, ctx: Ctx = Depends(dj.PM)):
    return await cover(ctx.org_id, frm, to, event_id, pending)


class AssignIn(BaseModel):
    provider_id: str
    fee: float = Field(0, ge=0)
    conflict_override: bool = False
    conflict_reason: str = Field("", max_length=300)


@router.post("/events/{eid}/dj/assign")
async def assign(eid: str, body: AssignIn, ctx: Ctx = Depends(dj.PM)):
    """Accord déjà pris hors application : réservation confirmée, sans e-mail."""
    ev = await ctx.get("events", eid)
    p = (await dj.named(ctx.org_id, [await ctx.get("provider_profiles", body.provider_id)]))[0]
    if "dj" not in (p.get("categories") or []):
        raise HTTPException(400, "Ce prestataire n'est pas un DJ")
    if await db.dj_bookings.find_one(ctx.q({"event_id": eid, "provider_id": p["id"], "status": {"$in": dj.LIVE}})):
        raise HTTPException(409, "Ce DJ est déjà sollicité pour cet événement")
    day = ev["start"][:10]
    import routes_dj_conflicts as cf
    chk = await cf.guard(ctx.org_id, p["id"], ev, ev["start"][11:16], ev["end"][11:16], body.conflict_override, body.conflict_reason)
    b = await ctx.insert("dj_bookings", {**chk, "event_id": eid, "provider_id": p["id"], "provider_name": dj.name_of(p, await dj.dj_doc(ctx.org_id, p["id"])), "quote_id": "", "preference_rank": 1, "status": "confirmed", "date": day,
                                         "city": "", "event_type": ev.get("type", ""), "option_expires_at": "", "proposed_fee": body.fee, "travel_fee": 0, "fee_tax_mode": "ht", "start_time": ev["start"][11:16], "end_time": ev["end"][11:16],
                                         "dj_reply": "", "dj_comment": "", "counter_fee": None, "confirmed_at": now_iso(), "created_by": ctx.member.get("name", "")})
    await dj.set_days(ctx.org_id, p["id"], [day], "confirmed", "booking", event_id=eid)
    await dj.blog(b, "confirmed", ctx.member.get("name", ""), "affectation directe, sans e-mail")
    if chk["conflict_override"]:
        await dj.blog(b, "conflict_forced", ctx.member.get("name", ""), chk["conflict_reason"])
    return await cover(ctx.org_id, day, day)


class QuickDj(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    city: str = Field("", max_length=120)
    base_rate: float = Field(0, ge=0)
    languages: List[str] = Field(default_factory=list, max_length=6)
    notes: str = Field("", max_length=1000)
    contact_id: str = ""


@router.post("/dj/quick")
async def quick_dj(body: QuickDj, ctx: Ctx = Depends(dj.PM)):
    import routes_providers as rp
    first, _, last = body.name.partition(" ")
    p = await rp._create(ctx, rp.ProviderIn(contact_id=body.contact_id, first_name=first, last_name=last, stage_name=body.name, email=body.email, phone=body.phone, base_city=body.city, base_rate=body.base_rate, categories=["dj"]))
    await db.provider_profiles.update_one(ctx.q({"id": p["id"]}), {"$set": {"status": "active", "name": body.name}})
    await dj.save_profile(ctx.org_id, p["id"], {"stage_name": body.name, "mc_languages": [{"lang": l, "level": "fluent"} for l in body.languages], "internal_notes": body.notes})
    return {"id": p["id"], "name": body.name}


async def weekly_digest() -> None:
    from html import escape
    from security import APP_ENV
    async for org in db.orgs.find({}, {"_id": 0, "id": 1, "name": 1}):
        c = await cover(org["id"])
        rows = [f"{d['label']} — " + ", ".join(e["title"] for e in d["events"] if e["coverage"] == "none") for d in c["days"] if d["red"]]
        if not rows:
            continue
        subject, sent = f"Prestations DJ sans DJ : {c['without_dj']}", 0
        if APP_ENV == "production":  # aucun e-mail depuis la préversion / QA
            from emailer import send_email
            async for u in db.users.find({"org_id": org["id"], "role": {"$in": ["admin", "gerant"]}, "status": {"$nin": ["suspended", "deleted", "disabled"]}}, {"_id": 0, "email": 1}):
                if u.get("email"):
                    await send_email(to=u["email"], subject=subject, html="<p>" + escape(subject) + "</p><ul>" + "".join(f"<li>{escape(r)}</li>" for r in rows) + "</ul>")
                    sent += 1
        await db.dj_digests.insert_one({"org_id": org["id"], "at": now_iso(), "subject": subject, "rows": rows, "emails_sent": sent})


from fastapi import BackgroundTasks, Request  # noqa: E402


@router.post("/cron/dj-weekly")
async def cron_dj_weekly(request: Request, bg: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    from routes_billing import cron_guard
    if not await cron_guard(request, "dj-weekly"):
        return {"ok": True, "duplicate": True}
    bg.add_task(tenants.for_each_org, weekly_digest, label="dj-weekly")
    return {"ok": True}


# ---------- Devis en cours : encart DJ interne et demande de disponibilité (ne bloque pas le DJ) ----------
@router.get("/quotes/{qid}/dj-status")
async def quote_dj(qid: str, ctx: Ctx = Depends(dj.PM)):
    q = await ctx.get("quotes", qid)
    day = q.get("event_date") or ""
    if not any(isdj(l.get("label")) for l in q.get("lines") or []) or not day or not q.get("event_id"):
        return {"has_dj": False}
    c = await cover(ctx.org_id, day, day, "", True)
    rows = [e for d in c["days"] if d["date"] == day for e in d["events"]]
    mine = next((e for e in rows if e["event_id"] == q["event_id"]), {"djs": [], "requests": []})
    busy = {x["provider_id"] for e in rows if e["confirmed"] for x in e["djs"]}
    soft = {x["provider_id"] for e in rows if not e["confirmed"] and e["event_id"] != q["event_id"] for x in e["djs"] + [r for r in e["requests"] if r["status"] == "available"]}
    djs = [{**r, "reserved": r["provider_id"] in soft} for r in await dj.search(day, True, False, ctx) if r["state"] not in ("confirmed", "unavailable") and r["provider_id"] not in busy]
    return {"has_dj": True, "date": day, "event_id": q["event_id"], "djs": djs, "free": len(djs), "options": mine["djs"], "requests": mine["requests"],
            "confirmed_count": sum(1 for e in rows if e["confirmed"]), "pending_count": sum(1 for e in rows if not e["confirmed"])}


class AskIn(BaseModel):
    provider_ids: List[str] = Field(min_length=1, max_length=10)


@router.post("/quotes/{qid}/dj/ask")
async def ask(qid: str, body: AskIn, ctx: Ctx = Depends(dj.PM)):
    q = await ctx.get("quotes", qid)
    ev = await ctx.get("events", q.get("event_id") or "-")
    from security import APP_ENV
    for pid in body.provider_ids:
        p = (await dj.named(ctx.org_id, [await ctx.get("provider_profiles", pid)]))[0]
        if await db.dj_bookings.find_one(ctx.q({"event_id": ev["id"], "provider_id": pid, "status": {"$in": [*dj.LIVE, *ASK]}})):
            continue
        name = dj.name_of(p, await dj.dj_doc(ctx.org_id, pid))
        nb = await ctx.insert("dj_bookings", {"event_id": ev["id"], "provider_id": pid, "provider_name": name, "quote_id": qid, "preference_rank": 1, "status": "availability_requested", "date": ev["start"][:10], "city": "",
                                         "event_type": ev.get("type", ""), "option_expires_at": "", "proposed_fee": 0, "travel_fee": 0, "fee_tax_mode": "ht", "start_time": ev["start"][11:16], "end_time": ev["end"][11:16],
                                         "dj_reply": "", "dj_comment": "", "counter_fee": None, "confirmed_at": None, "created_by": ctx.member.get("name", "")})
        if APP_ENV == "production" and p.get("email"):  # aucun e-mail depuis la préversion / QA
            from emailer import send_email
            d = ev["start"][:10]
            await send_email(to=p["email"], subject=f"Disponibilité le {d[8:10]}/{d[5:7]}/{d[:4]} ?", html=f"<p>Bonjour {name},</p><p>Es-tu disponible le {d[8:10]}/{d[5:7]}/{d[:4]}, de {ev['start'][11:16]} à {ev['end'][11:16]} ?</p><p><a href=\"{_link(await ensure_link('dj_bookings', {**nb, 'org_id': ctx.org_id}))}\">Répondre oui ou non en un clic</a></p>")
    return await quote_dj(qid, ctx)


class AnswerIn(BaseModel):
    available: bool


def _link(token: str) -> str:
    import os
    return f"{(os.environ.get('APP_URL') or '').rstrip('/')}/dispo-dj/{token}"


async def _answer(b: dict, available: bool, by: str, own: bool = False) -> str:
    st = "available" if available else "not_available"
    await db.dj_bookings.update_one({"org_id": b["org_id"], "id": b["id"]}, {"$set": {"status": st, "updated_at": now_iso(), "replied_at": now_iso()}})
    await dj.blog(b, st, by, "réponse du DJ" if own else "réponse saisie par l'équipe")
    if own:
        import routes_stock
        await routes_stock.task(b["org_id"], f"DJ {b['provider_name']} : {'disponible' if available else 'pas disponible'} le {b['date'][8:10]}/{b['date'][5:7]}/{b['date'][:4]}", f"dj-avail:{b['id']}:{st}")
    return st


@router.put("/dj/requests/{bid}")
async def answer(bid: str, body: AnswerIn, ctx: Ctx = Depends(dj.PM)):
    b = await ctx.get("dj_bookings", bid, {"status": {"$in": ASK}})
    await _answer({**b, "org_id": ctx.org_id}, body.available, ctx.member.get("name", ""))
    return {"ok": True, "event_id": b["event_id"]}


@router.get("/dj/requests/{bid}/link")
async def request_link(bid: str, ctx: Ctx = Depends(dj.PM)):
    b = await ctx.get("dj_bookings", bid, {"status": {"$in": ASK}})
    return {"path": f"/dispo-dj/{await ensure_link('dj_bookings', {**b, 'org_id': ctx.org_id})}"}


@router.post("/portal/provider/dj/bookings/{bid}/availability")
async def my_answer(bid: str, body: AnswerIn, request: Request, ctx: Ctx = Depends(dj.PV)):
    _, b = await dj.my_booking(ctx, request, bid)
    if b["status"] not in ASK:
        raise HTTPException(409, "Cette demande n'attend plus de réponse")
    return {"status": await _answer(b, body.available, b["provider_name"], True)}


async def _by_token(token: str) -> dict:
    b = await link_doc("dj_bookings", token)
    if not b:
        raise HTTPException(404, "Lien introuvable")
    check_expiry(b["date"])
    return b


@router.get("/public/dj-availability/{token}")
async def public_ask(token: str):
    """Sans compte : le DJ ne voit que la date, l'horaire, la ville et le type d'événement."""
    b = await _by_token(token)
    ev = await db.events.find_one({"org_id": b["org_id"], "id": b["event_id"]}, {"_id": 0, "venue_id": 1}) or {}
    v = await db.venues.find_one({"org_id": b["org_id"], "id": ev.get("venue_id") or "-"}, {"_id": 0, "city": 1}) or {}
    org = await db.orgs.find_one({"id": b["org_id"]}, {"_id": 0, "name": 1}) or {}
    return {"org": org.get("name", ""), "name": b["provider_name"], "date": b["date"], "start_time": b["start_time"], "end_time": b["end_time"], "city": v.get("city", ""), "event_type": b.get("event_type", ""),
            "status": b["status"] if b["status"] in ASK else "closed"}


@router.post("/public/dj-availability/{token}")
async def public_answer(token: str, body: AnswerIn):
    b = await _by_token(token)
    if b["status"] not in ASK:
        raise HTTPException(409, "Cette demande n'attend plus de réponse")
    return {"status": await _answer(b, body.available, b["provider_name"], True)}


class ReplaceIn(BaseModel):
    provider_id: str
    reason: str = Field("", max_length=500)
    fee: float = Field(0, ge=0)
    conflict_override: bool = False
    conflict_reason: str = Field("", max_length=300)


@router.post("/dj/replace/{bid}")
async def replace(bid: str, body: ReplaceIn, ctx: Ctx = Depends(dj.PM)):
    """Changer de DJ : l'ancien est libéré (journalisé), le nouveau est affecté directement, sans e-mail."""
    b = await ctx.get("dj_bookings", bid, {"status": {"$in": dj.LIVE}})
    p = await ctx.get("provider_profiles", body.provider_id)
    if "dj" not in (p.get("categories") or []) or p["id"] == b["provider_id"]:
        raise HTTPException(400, "Choisissez un autre DJ")
    if await db.dj_bookings.find_one(ctx.q({"event_id": b["event_id"], "provider_id": p["id"], "status": {"$in": dj.LIVE}})):
        raise HTTPException(409, "Ce DJ est déjà sollicité pour cet événement")
    import routes_dj_conflicts as cf
    ev = await ctx.get("events", b["event_id"])
    await cf.guard(ctx.org_id, p["id"], ev, ev["start"][11:16], ev["end"][11:16], body.conflict_override, body.conflict_reason)
    await dj.release(ctx.org_id, {**b, "org_id": ctx.org_id}, "cancelled" if b["status"] in DONE else "option_lifted", ctx.member.get("name", ""), body.reason or "Changement de DJ")
    await assign(b["event_id"], AssignIn(provider_id=p["id"], fee=body.fee or b.get("proposed_fee") or 0, conflict_override=body.conflict_override, conflict_reason=body.conflict_reason), ctx)
    return {"ok": True}


async def on_quote_closed(org_id: str, q: dict) -> int:
    """Devis refusé ou expiré : les demandes de disponibilité rattachées sont annulées (aucun message envoyé au DJ)."""
    return (await db.dj_bookings.update_many({"org_id": org_id, "quote_id": q["id"], "status": {"$in": ASK}}, {"$set": {"status": "cancelled", "updated_at": now_iso(), "release_pending": True}})).modified_count


class ShowIn(BaseModel):
    show: bool


@router.put("/events/{eid}/dj/show-client")
async def show_client(eid: str, body: ShowIn, ctx: Ctx = Depends(dj.PM)):
    await ctx.get("events", eid)
    await db.events.update_one(ctx.q({"id": eid}), {"$set": {"dj_show_client": body.show}})
    return {"dj_show_client": body.show}
