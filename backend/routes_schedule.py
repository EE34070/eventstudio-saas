"""Déroulé de l'événement (planning de l'organisateur + nos étapes) et plans organisateur annotables."""
import base64
import logging
import os
from datetime import datetime, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core import Ctx, db, need, new_id, now_iso
from routes_files import file_bytes, read_upload, store_bytes
from security import DATA_GUARD

router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)
R, W = need("events:read"), need("events:write")
DEFAULTS = {"chargement": 45, "dechargement": 30, "montage_dj": 90, "sono_ceremonie": 45, "raccordements": 20, "balances": 30, "tests_micros": 15, "bascule": 20, "demontage": 60, "chargement_retour": 30}
PROMPT = ("Tu lis le planning d'un événement envoyé par l'organisateur. Extrais chaque étape, sans rien inventer. Classe chaque étape pour un prestataire technique dont voici les prestations : {ctx}. "
          "concerns_us = touche à ces prestations, moments musicaux (entrée, sortie de cérémonie, première danse, discours, gâteau, ouverture de bal, fin de musique), accès au lieu, livraison, retrait, changement de salle, prises de parole, contraintes de bruit. "
          "not_concerned = préparatifs (maquillage, coiffure, habillage), shooting photo, fleurs, traiteur sans impact, transport des invités. to_check = ambigu. "
          'Réponds uniquement en JSON : {{"steps": [{{"day": "AAAA-MM-JJ ou vide", "start": "HH:MM", "end": "HH:MM ou vide", "title": "", "description": "", "space": "", "people": "", "relevance": "concerns_us|not_concerned|to_check", "unsure": false}}]}}')


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s[:16])


def _plus(s: str, minutes: float) -> str:
    return (_dt(s) + timedelta(minutes=minutes)).isoformat()[:16]


def recalc(steps: list) -> list:
    """Déterministe : une étape enchaînée suit la précédente ; une heure fixe n'est jamais écrasée, le débordement est signalé."""
    prev = None
    for i, s in enumerate(steps):
        s["order"], s["conflict"] = i, ""
        if not s.get("visible", True):
            s["end"] = _plus(s["start"], s["duration_min"])
            continue
        if s["time_mode"] == "chained" and prev:
            s["start"] = prev["end"]
        elif prev and s["start"] < prev["end"] and not (prev["source"] == "organizer" and s["source"] == "organizer"):
            late = int((_dt(prev["end"]) - _dt(s["start"])).total_seconds() // 60)
            s["conflict"] = f"« {prev['title']} » déborde de {late} min sur cette heure fixe"
        s["end"] = _plus(s["start"], s["duration_min"])
        prev = s
    return steps


async def _steps(ctx: Ctx, eid: str) -> list:
    return recalc(await ctx.list("schedule_steps", {"event_id": eid, "deleted_at": None}, sort=[("order", 1)], limit=500))


async def _save(ctx: Ctx, steps: list) -> None:
    for s in recalc(steps):
        await db.schedule_steps.update_one(ctx.q({"id": s["id"]}), {"$set": {"start": s["start"], "order": s["order"]}})


async def _view(ctx: Ctx, eid: str) -> dict:
    steps = await _steps(ctx, eid)
    return {"steps": [s for s in steps if s.get("visible", True)], "hidden": [s for s in steps if not s.get("visible", True)], "conflicts": sum(1 for s in steps if s["conflict"]),
            "sources": await ctx.list("schedule_sources", {"event_id": eid}, sort=[("version", -1)], limit=20)}


@router.get("/events/{eid}/schedule")
async def get_schedule(eid: str, ctx: Ctx = Depends(R)):
    await ctx.get("events", eid, ctx.event_scope())
    return await _view(ctx, eid)


async def _extract(ctx: Ctx, ev: dict, data: bytes | None, ctype: str, text: str) -> tuple:
    import messaging_core as mc
    from routes_admin import _json
    mods = [m["module_key"] async for m in db.event_modules.find(ctx.q({"event_id": ev["id"], "status": "actif"}), {"module_key": 1})]
    lines = [l["label"] async for q in db.quotes.find(ctx.q({"event_id": ev["id"], "status": "accepte"}), {"lines.label": 1}) for l in q.get("lines") or []][:40]
    context = f"modules {', '.join(mods) or 'son, lumière, DJ'} ; lignes du devis accepté : {' ; '.join(lines) or 'non précisé'} ; jour de l'événement {ev['start'][:10]}"
    content = [{"type": "document" if ctype == "application/pdf" else "image", "source": {"type": "base64", "media_type": ctype, "data": base64.b64encode(data).decode()}}] if data else []
    content.append({"type": "text", "text": f"Planning à analyser :\n{text[:20000]}" if text else "Extrais le planning."})
    try:
        r = await mc.claude().messages.create(model=os.environ.get("LLM_MODEL") or os.environ.get("SUPPLIER_QUOTE_MODEL") or "claude-sonnet-5-5", max_tokens=6000, system=DATA_GUARD + " " + PROMPT.format(ctx=context), messages=[{"role": "user", "content": content}])
        return (_json("".join(b.text for b in r.content if b.type == "text")).get("steps") or []), ""
    except Exception as exc:
        return [], mc.ai_fail(exc, False) + " — ajoutez les étapes à la main."


@router.post("/events/{eid}/schedule/sources")
async def add_source(eid: str, file: Optional[UploadFile] = File(None), text: str = Form(""), ctx: Ctx = Depends(W)):
    ev = await ctx.get("events", eid, ctx.event_scope())
    if not file and len(text.strip()) < 10:
        raise HTTPException(400, "Déposez un fichier (PDF ou image) ou collez le texte du planning")
    data, ctype, ref = None, "", ""
    if file:
        data, ctype = await read_upload(file)
        ref = await store_bytes(ctx.org_id, data, ctype, file.filename or "planning", ctx.member.get("name"))
    raw, warn = await _extract(ctx, ev, data, ctype, text.strip())
    day = ev["start"][:10]
    steps = []
    for x in raw[:120]:
        try:
            d = x.get("day") or day
            start = f"{d}T{x['start'][:5]}"
            if d == day and x["start"][:5] < "06:00":
                start = _plus(start, 1440)
            dur = max(0, int((_dt(f"{start[:10]}T{x['end'][:5]}") - _dt(start)).total_seconds() // 60) % 1440) if x.get("end") else 0
            steps.append({"start": start, "duration_min": dur, "title": str(x.get("title") or "")[:200], "description": str(x.get("description") or "")[:1000], "space_label": str(x.get("space") or "")[:120],
                          "people": str(x.get("people") or "")[:200], "relevance": x.get("relevance") if x.get("relevance") in ("concerns_us", "not_concerned", "to_check") else "to_check", "unsure": bool(x.get("unsure"))})
        except Exception:
            continue
    n = await db.schedule_sources.count_documents(ctx.q({"event_id": eid}))
    src = await ctx.insert("schedule_sources", {"event_id": eid, "file_ref": ref, "filename": (file.filename if file else "Texte collé"), "text": text.strip()[:20000], "received_at": now_iso(), "version": n + 1, "status": "importe", "raw_extraction": steps})
    return {**src, "warning": warn}


class StepIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
    duration_min: int = Field(0, ge=0, le=1440)
    description: str = Field("", max_length=1000)
    space_label: str = Field("", max_length=120)
    people: str = Field("", max_length=200)
    relevance: Literal["concerns_us", "not_concerned", "to_check"] = "concerns_us"


class ValidateIn(BaseModel):
    source_id: str = ""
    steps: List[StepIn] = Field(max_length=150)


def _doc(eid: str, source: str, title: str, start: str, dur: int, mode: str, phase: str, **k) -> dict:
    return {"event_id": eid, "source": source, "title": title, "start": start, "duration_min": dur, "time_mode": mode, "phase": phase, "relevance": "concerns_us", "visible": True, "description": "", "space_label": "", "people": "",
            "internal_notes": "", "status": "planned", "deleted_at": None, **k}


def auto_steps(eid: str, org_steps: list, d: dict, dj: bool) -> list:
    """Nos étapes techniques autour des étapes retenues de l'organisateur (durées par défaut de la société)."""
    kept = [s for s in org_steps if s["visible"]]
    if not kept:
        return org_steps
    low = lambda s: s["title"].lower()  # noqa: E731
    cer = next((s for s in kept if "cérémonie" in low(s) or "ceremon" in low(s)), None)
    seq = [("Chargement à l'entrepôt", d["chargement"]), ("Arrivée sur site et déchargement", d["dechargement"]), *([("Montage sonorisation cérémonie", d["sono_ceremonie"])] if cer else []),
           ("Montage régie DJ, son et lumière" if dj else "Montage son et lumière", d["montage_dj"]), ("Raccordements électriques", d["raccordements"]), ("Balances son et réglages lumière", d["balances"]), ("Tests micros", d["tests_micros"]), ("Fin d'installation — prêt", 0)]
    t0 = _plus(kept[0]["start"], -30 - sum(x[1] for x in seq))
    out = [_doc(eid, "auto", t, t0, n, "fixed" if i == 0 else "chained", "installation") for i, (t, n) in enumerate(seq)]
    for s in org_steps:
        out.append(s)
        if s is cer and any("cocktail" in low(x) for x in kept):
            out.append(_doc(eid, "auto", "Bascule sonorisation cérémonie → cocktail", s["start"], d["bascule"], "chained", "exploitation"))
    return out + [_doc(eid, "auto", t, kept[-1]["start"], n, "chained", "dismantling") for t, n in (("Démontage", d["demontage"]), ("Chargement retour", d["chargement_retour"]), ("Départ du site", 0))]


@router.post("/events/{eid}/schedule/validate")
async def validate(eid: str, body: ValidateIn, ctx: Ctx = Depends(W)):
    await ctx.get("events", eid, ctx.event_scope())
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "schedule_defaults": 1}) or {}
    new = [_doc(eid, "organizer", s.title, s.start, s.duration_min, "fixed", "organizer", description=s.description, space_label=s.space_label, people=s.people, relevance=s.relevance, visible=s.relevance != "not_concerned", source_id=body.source_id)
           for s in sorted(body.steps, key=lambda s: s.start)]
    old = await _steps(ctx, eid)
    if old:  # nouvelle version : on remplace les étapes de l'organisateur, nos étapes sont conservées
        await db.schedule_steps.update_many(ctx.q({"event_id": eid, "source": "organizer", "deleted_at": None}), {"$set": {"deleted_at": now_iso()}})
        steps = sorted([s for s in old if s["source"] != "organizer"] + new, key=lambda s: (s["start"], s.get("order", 0)))
    else:
        dj = bool(await db.event_modules.find_one(ctx.q({"event_id": eid, "module_key": "dj", "status": "actif"})))
        steps = auto_steps(eid, new, {**DEFAULTS, **(org.get("schedule_defaults") or {})}, dj)
    for i, s in enumerate(steps):
        if "id" not in s:
            steps[i] = await ctx.insert("schedule_steps", {**s, "order": i})
    await _save(ctx, steps)
    if body.source_id:
        await db.schedule_sources.update_many(ctx.q({"event_id": eid, "status": "valide"}), {"$set": {"status": "remplace"}})
        await db.schedule_sources.update_one(ctx.q({"id": body.source_id}), {"$set": {"status": "valide"}})
    return await _view(ctx, eid)


class NewStep(BaseModel):
    after_id: str = ""
    title: str = Field(min_length=1, max_length=200)
    duration_min: int = Field(15, ge=0, le=1440)
    time_mode: Literal["fixed", "chained"] = "chained"
    start: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})?$")
    phase: Literal["installation", "exploitation", "dismantling"] = "exploitation"


@router.post("/events/{eid}/schedule/steps")
async def insert_step(eid: str, body: NewStep, ctx: Ctx = Depends(W)):
    ev = await ctx.get("events", eid, ctx.event_scope())
    steps = await _steps(ctx, eid)
    i = next((k for k, s in enumerate(steps) if s["id"] == body.after_id), len(steps) - 1)
    start = body.start or (steps[i]["end"] if steps else ev["start"][:16])
    s = await ctx.insert("schedule_steps", _doc(eid, "internal", body.title, start, body.duration_min, body.time_mode if steps else "fixed", body.phase, order=i + 1))
    steps.insert(i + 1, s)
    await _save(ctx, steps)
    return await _view(ctx, eid)


class StepPatch(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    start: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
    duration_min: Optional[int] = Field(None, ge=0, le=1440)
    time_mode: Optional[Literal["fixed", "chained"]] = None
    visible: Optional[bool] = None
    status: Optional[Literal["planned", "done"]] = None
    internal_notes: Optional[str] = Field(None, max_length=1000)
    space_label: Optional[str] = Field(None, max_length=120)
    people: Optional[str] = Field(None, max_length=200)
    move: Optional[Literal[-1, 1]] = None
    deleted: Optional[bool] = None


@router.put("/schedule/steps/{sid}")
async def patch_step(sid: str, body: StepPatch, ctx: Ctx = Depends(W)):
    s = await ctx.get("schedule_steps", sid, {"deleted_at": None})
    await ctx.get("events", s["event_id"], ctx.event_scope())
    upd = body.model_dump(exclude_none=True, exclude={"move", "deleted"})
    if body.visible:
        upd["relevance"] = "concerns_us"
    if body.deleted:
        upd["deleted_at"] = now_iso()
    if upd:
        await db.schedule_steps.update_one(ctx.q({"id": sid}), {"$set": upd})
    steps = await _steps(ctx, s["event_id"])
    if body.move:
        vis = [x for x in steps if x.get("visible", True)]
        i = next(k for k, x in enumerate(vis) if x["id"] == sid)
        if 0 <= i + body.move < len(vis):
            a, b = steps.index(vis[i]), steps.index(vis[i + body.move])
            steps[a], steps[b] = steps[b], steps[a]
    await _save(ctx, steps)
    return await _view(ctx, s["event_id"])


TITLES = {"team": "Équipe", "dj": "DJ", "organizer": "Organisateur"}


async def _for(ctx: Ctx, eid: str, audience: str) -> list:
    steps = [s for s in await _steps(ctx, eid) if s.get("visible", True)]
    return [s for s in steps if s["source"] == "organizer" or s["phase"] in ("installation", "dismantling")] if audience == "organizer" else steps


async def _people(ctx: Ctx, ev: dict, audience: str) -> list:
    if audience == "dj":
        import routes_dj as dj
        out = []
        async for b in db.dj_bookings.find(ctx.q({"event_id": ev["id"], "status": {"$in": ["confirmed", "acknowledged"]}}), {"_id": 0, "provider_id": 1, "provider_name": 1}):
            p = await db.provider_profiles.find_one(ctx.q({"id": b["provider_id"]}), {"_id": 0}) or {}
            out.append({"id": b["provider_id"], "name": b["provider_name"], "email": (await dj.mail_of(ctx.org_id, p))[0]})
        return out
    ids = [t["member_id"] for t in ev.get("team") or []]
    return [{"id": t["id"], "name": t.get("name", ""), "email": t.get("email") or ""} async for t in db.team.find(ctx.q({"id": {"$in": ids}}), {"_id": 0, "id": 1, "name": 1, "email": 1})]


@router.get("/events/{eid}/schedule/roadmap/draft")
async def roadmap_draft(eid: str, audience: Literal["team", "dj"] = "team", ctx: Ctx = Depends(W)):
    ev = await ctx.get("events", eid, ctx.event_scope())
    v = await db.venues.find_one(ctx.q({"id": ev.get("venue_id") or "-"}), {"_id": 0}) or {}
    d, team = ev["start"][:10], audience == "team"
    lines = [f"{s['start'][11:16]}{' – ' + s['end'][11:16] if s['duration_min'] else ''}  {s['title']}" + (f" ({s['space_label']})" if s.get("space_label") else "") + (f" — {s['internal_notes']}" if team and s.get("internal_notes") else "")
             for s in await _for(ctx, eid, audience)]
    addr = ", ".join(x for x in (v.get("name"), f"{v.get('address', '')} {v.get('zip', '')} {v.get('city', '')}".strip()) if x) or "à préciser"
    body = f"Bonjour,\n\nVoici la feuille de route de {ev.get('title', '')}, le {d[8:10]}/{d[5:7]}/{d[:4]}.\nLieu : {addr}\n\n" + "\n".join(lines) + "\n\nMerci de nous signaler tout point bloquant.\n\nExclusivity Events"
    return {"recipients": await _people(ctx, ev, audience), "subject": f"Feuille de route — {ev.get('title', '')} — {d[8:10]}/{d[5:7]}/{d[:4]}", "body": body, "steps": len(lines)}


class SendIn(BaseModel):
    audience: Literal["team", "dj"]
    recipient_ids: List[str] = Field(min_length=1, max_length=50)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)


@router.post("/events/{eid}/schedule/roadmap/send")
async def roadmap_send(eid: str, body: SendIn, ctx: Ctx = Depends(W)):
    """Envoi sur clic uniquement ; hors production le message est journalisé, jamais envoyé."""
    import routes_dj as dj
    ev = await ctx.get("events", eid, ctx.event_scope())
    out = []
    from html import escape
    from emailer import EMAIL_PROVIDER, send_email
    from security import APP_ENV
    name, pdf = f"feuille-de-route-{ev.get('code', '')}.pdf", (await roadmap(eid, body.audience, ctx)).body
    joined = EMAIL_PROVIDER in ("resend", "smtp")  # le service d'e-mail par défaut n'accepte pas les pièces jointes
    for p in await _people(ctx, ev, body.audience):
        if p["id"] in body.recipient_ids and p["email"]:
            sent = False
            if APP_ENV == "production":
                sent = bool(await send_email(to=p["email"], subject=body.subject, html="".join(f"<p>{escape(l)}</p>" for l in body.body.split("\n") if l.strip()), attachments=[(name, pdf)] if joined else None))
            await db.dj_messages.insert_one({"id": new_id(), "org_id": ctx.org_id, "at": now_iso(), "to": p["email"], "subject": body.subject, "body": body.body, "event_id": eid, "booking_id": "", "kind": f"roadmap_{body.audience}", "sent": sent,
                                             "attachment": name if joined else "", "attachment_bytes": len(pdf)})
            out.append(p["name"])
    if not out:
        raise HTTPException(400, "Aucun destinataire avec une adresse e-mail")
    return {"recipients": out, "sent": APP_ENV == "production", "attachment": name if joined else ""}


@router.get("/events/{eid}/schedule/roadmap")
async def roadmap(eid: str, audience: Literal["team", "dj", "organizer"] = "team", ctx: Ctx = Depends(R)):
    """Feuille de route PDF. Organisateur : ni notes internes, ni équipe, ni bascules de matériel."""
    from reportlab.lib.units import mm
    from routes_delivery import P, _build, _styles, _table
    ev = await ctx.get("events", eid, ctx.event_scope())
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "name": 1}) or {}
    v = await db.venues.find_one(ctx.q({"id": ev.get("venue_id") or "-"}), {"_id": 0}) or {}
    steps = await _for(ctx, eid, audience)
    S, team = _styles(), audience == "team"
    d = ev["start"][:10]
    story = [P(org.get("name", ""), S["sm"]), P(f"Feuille de route — {TITLES[audience]}", S["big"]), P(f"{ev.get('code', '')} · {ev.get('title', '')} · {d[8:10]}/{d[5:7]}/{d[:4]}", S["bold"]),
             P(", ".join(x for x in (v.get("name"), f"{v.get('address', '')} {v.get('zip', '')} {v.get('city', '')}".strip()) if x) or "Lieu à définir", S["st"])]
    if audience != "organizer":
        names = [b["provider_name"] async for b in db.dj_bookings.find(ctx.q({"event_id": eid, "status": {"$in": ["confirmed", "acknowledged"]}}), {"_id": 0, "provider_name": 1})]
        contacts = ", ".join(f"{c.get('name', '')} {c.get('phone', '')}".strip() for c in v.get("onsite_contacts") or [])
        story += [P(t, S["sm"]) for t in (f"DJ : {', '.join(names)}" if names else "", f"Contact sur place : {contacts}" if contacts else "", f"Accès : {v['access_instructions']}" if v.get("access_instructions") else "") if t]
    widths = [24 * mm, 68 * mm, 34 * mm, 48 * mm] if team else [26 * mm, 106 * mm, 42 * mm]
    if not steps:
        story.append(P("Aucune étape dans le déroulé pour l'instant.", S["st"]))
    for day in sorted({s["start"][:10] for s in steps}):
        rows = [[P(h, S["bold"]) for h in (["Heure", "Étape", "Espace", "Notes internes"] if team else ["Heure", "Étape", "Espace"])]]
        for s in [s for s in steps if s["start"][:10] == day]:
            hours = s["start"][11:16] + (f" – {s['end'][11:16]}" if s["duration_min"] else "")
            what = [P(s["title"], S["bold"])] + ([P(s["description"], S["sm"])] if s.get("description") and (audience != "organizer" or s["source"] == "organizer") else [])
            rows.append([P(hours, S["st"]), what, P(s.get("space_label", ""), S["st"])] + ([P(s.get("internal_notes", ""), S["sm"])] if team else []))
        story += [P(" ", S["st"]), P(f"{day[8:10]}/{day[5:7]}/{day[:4]}", S["h2"]), _table(rows, widths)]
    return Response(_build(story, f"Feuille de route {TITLES[audience]}", org), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="feuille-de-route-{audience}-{ev.get("code", "")}.pdf"'})


# ---------- Plans fournis par l'organisateur ----------
class Ann(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    page: int = Field(0, ge=0, le=500)
    type: Literal["pin", "arrow", "rect", "text"]
    geometry: dict
    text: str = Field("", max_length=500)
    layer: str = Field("", max_length=40)
    visibility: Literal["internal", "shared"] = "internal"
    status: Literal["open", "resolved"] = "open"
    author: str = Field("", max_length=120)
    at: str = Field("", max_length=40)


class AnnIn(BaseModel):
    annotations: List[Ann] = Field(max_length=500)


@router.get("/events/{eid}/organizer-plans")
async def list_plans(eid: str, shared: bool = False, ctx: Ctx = Depends(R)):
    await ctx.get("events", eid, ctx.event_scope())
    rows = await ctx.list("organizer_plans", {"event_id": eid, "deleted_at": None}, sort=[("uploaded_at", -1)], limit=200)
    return [{**p, "annotations": [a for a in p.get("annotations") or [] if not shared or a["visibility"] == "shared"]} for p in rows]


@router.post("/events/{eid}/organizer-plans")
async def add_plan(eid: str, file: UploadFile = File(...), zone_label: str = Form(""), source: str = Form(""), ctx: Ctx = Depends(W)):
    await ctx.get("events", eid, ctx.event_scope())
    data, ctype = await read_upload(file)
    pages = 1
    if ctype == "application/pdf":
        import pymupdf
        pages = len(pymupdf.open(stream=data, filetype="pdf"))
    prev = await db.organizer_plans.find_one(ctx.q({"event_id": eid, "zone_label": zone_label[:80], "deleted_at": None}), {"_id": 0}, sort=[("version", -1)]) if zone_label.strip() else None
    return await ctx.insert("organizer_plans", {"event_id": eid, "file_ref": await store_bytes(ctx.org_id, data, ctype, file.filename or "plan", ctx.member.get("name")), "filename": (file.filename or "plan")[:200], "content_type": ctype,
                                                "page_count": pages, "zone_label": zone_label[:80], "source": source[:120], "version": (prev or {}).get("version", 0) + 1, "previous_id": (prev or {}).get("id", ""),
                                                "annotations": [], "uploaded_by": ctx.member.get("name", ""), "uploaded_at": now_iso(), "deleted_at": None})


@router.get("/organizer-plans/{pid}/page/{n}")
async def plan_page(pid: str, n: int, ctx: Ctx = Depends(R)):
    p = await ctx.get("organizer_plans", pid, {"deleted_at": None})
    await ctx.get("events", p["event_id"], ctx.event_scope())
    got = await file_bytes(ctx.org_id, p["file_ref"])
    if not got:
        raise HTTPException(404, "Fichier introuvable")
    data, ctype = got
    if ctype == "application/pdf":
        import pymupdf
        doc = pymupdf.open(stream=data, filetype="pdf")
        data, ctype = doc[max(0, min(n, len(doc) - 1))].get_pixmap(dpi=110).tobytes("png"), "image/png"
    return Response(data, media_type=ctype, headers={"Cache-Control": "private, max-age=3600"})


@router.put("/organizer-plans/{pid}/annotations")
async def put_annotations(pid: str, body: AnnIn, ctx: Ctx = Depends(W)):
    """Calque non destructif : le fichier d'origine n'est jamais modifié."""
    p = await ctx.get("organizer_plans", pid, {"deleted_at": None})
    await ctx.get("events", p["event_id"], ctx.event_scope())
    old = {a["id"]: a for a in p.get("annotations") or []}
    anns = [{**a.model_dump(), "author": old.get(a.id, {}).get("author") or ctx.member.get("name", ""), "at": old.get(a.id, {}).get("at") or now_iso()} for a in body.annotations]
    return await ctx.update("organizer_plans", pid, {"annotations": anns})
