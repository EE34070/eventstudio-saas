import csv
import hmac
import io
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

import messaging_core as mc
from core import DEMO_SLUG, Ctx, db, need, new_id, now_iso
from i18n import doc_lang, fmt_date
from routes_main import contact_name, module_catalog
from routes_ops import EventIn, create_event

from core import ensure_link  # noqa: E402,F401
router = APIRouter(prefix="/api/crm")
logger = logging.getLogger(__name__)
C = need("crm:manage")
PARIS = ZoneInfo("Europe/Paris")
STAGES = [("nouvelle", "Nouvelle demande", 10), ("qualifiee", "Qualifiée", 25), ("devis_envoye", "Devis envoyé", 50), ("negociation", "Négociation / relance", 70),
          ("gagnee", "Gagnée", 100), ("perdue", "Perdue", 0)]
SOURCES = ["Instagram", "SMS", "WhatsApp", "Email", "Site web", "Organisateur", "Recommandation", "Salon", "Autre"]
LOST = ["prix", "date_indisponible", "concurrent", "sans_reponse", "projet_annule", "autre"]
FOLLOWUP = {"fr": ("Votre projet du {date_evenement}", "Bonjour {prénom},\n\nJe me permets de revenir vers vous au sujet de votre projet du {date_evenement} à {lieu} ({prestations}).\n"
                   "Avez-vous pu consulter notre proposition ? {lien_devis}\n\nJe reste à votre disposition pour en discuter.\n\nBien cordialement,"),
            "en": ("Your event on {date_evenement}", "Hello {prénom},\n\nI am following up on your event on {date_evenement} at {lieu} ({prestations}).\n"
                   "Have you had a chance to look at our proposal? {lien_devis}\n\nI remain at your disposal to discuss it.\n\nKind regards,")}


def today() -> str:
    return datetime.now(PARIS).strftime("%Y-%m-%d")


def key_of(label: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in label.lower()).strip("_")


async def config(org_id: str) -> dict:
    if not await db.crm_stages.find_one({"org_id": org_id}):
        await db.crm_stages.insert_many([{"id": new_id(), "org_id": org_id, "key": k, "label": lab, "order": i, "default_probability": p, "is_won": k == "gagnee", "is_lost": k == "perdue",
                                          "active": True} for i, (k, lab, p) in enumerate(STAGES)])
        await db.crm_sources.insert_many([{"id": new_id(), "org_id": org_id, "key": key_of(s), "label": s, "order": i, "active": True} for i, s in enumerate(SOURCES)])
    return {"stages": await db.crm_stages.find({"org_id": org_id}, {"_id": 0}).sort("order", 1).to_list(50),
            "sources": await db.crm_sources.find({"org_id": org_id}, {"_id": 0}).sort("order", 1).to_list(50), "lost_reasons": LOST}


@router.get("/config")
async def get_config(ctx: Ctx = Depends(C)):
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}) or {}
    return {**await config(ctx.org_id), "followup_days": org.get("crm_followup_days", 5), "modules": await module_catalog(ctx.org_id)}


class ConfigRow(BaseModel):
    key: str = ""
    label: str = Field(min_length=1, max_length=60)
    default_probability: float = Field(0, ge=0, le=100)
    active: bool = True


class ConfigIn(BaseModel):
    stages: Optional[List[ConfigRow]] = None
    sources: Optional[List[ConfigRow]] = None
    followup_days: Optional[int] = Field(None, ge=1, le=60)


@router.put("/config")
async def put_config(body: ConfigIn, ctx: Ctx = Depends(need("org:write"))):
    cur = await config(ctx.org_id)
    for coll, rows in (("crm_stages", body.stages), ("crm_sources", body.sources)):
        for i, r in enumerate(rows or []):
            old = next((x for x in cur["stages" if coll == "crm_stages" else "sources"] if x["key"] == r.key), None)
            data = {"label": r.label, "order": i, "active": r.active, **({"default_probability": r.default_probability} if coll == "crm_stages" else {})}
            if old:
                await db[coll].update_one({"org_id": ctx.org_id, "key": r.key}, {"$set": data})
            else:
                await db[coll].insert_one({"id": new_id(), "org_id": ctx.org_id, "key": key_of(r.label), "is_won": False, "is_lost": False, **data})
    if body.followup_days:
        await db.orgs.update_one({"id": ctx.org_id}, {"$set": {"crm_followup_days": body.followup_days}})
    return await get_config(ctx)


class OppIn(BaseModel):
    title: str = Field("", max_length=200)
    client_contact_id: str = Field(min_length=1)
    organizer_contact_id: str = ""
    main_contact_id: str = ""
    venue_id: str = ""
    city: str = Field("", max_length=80)
    event_date: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    event_type: str = "Autre"
    guest_count: int = Field(0, ge=0)
    services: List[str] = []
    source_key: str = "autre"
    stage_key: str = "nouvelle"
    probability: Optional[float] = Field(None, ge=0, le=100)
    amount: float = Field(0, ge=0)
    amount_tax_mode: Literal["ht", "ttc"] = "ttc"
    external_ref: str = Field("", max_length=120)
    owner_id: str = ""
    next_action: str = Field("", max_length=200)
    next_action_date: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    notes: str = Field("", max_length=5000)
    force: bool = False


class OppPatch(OppIn):
    client_contact_id: Optional[str] = None
    lost_reason: Optional[str] = None
    lost_comment: Optional[str] = None


async def log(ctx_or_org, oid: str, kind: str, body: str, by: str = "", meta: dict | None = None, contact_id: str = "") -> None:
    org_id = ctx_or_org.org_id if isinstance(ctx_or_org, Ctx) else ctx_or_org
    by = by or (ctx_or_org.member.get("name") if isinstance(ctx_or_org, Ctx) else "Système")
    await db.crm_activities.insert_one({"id": new_id(), "org_id": org_id, "opportunity_id": oid, "contact_id": contact_id, "type": kind, "direction": "", "body": body,
                                        "meta": meta or {}, "occurred_at": now_iso(), "created_by": by})
    await db.opportunities.update_one({"org_id": org_id, "id": oid}, {"$set": {"last_activity_at": now_iso()}})


def weighted(o: dict) -> float:
    return round(o.get("amount", 0) * o.get("probability", 0) / 100, 2)


async def create_opp(ctx: Ctx, body: OppIn) -> dict:
    cfg = await config(ctx.org_id)
    c = await ctx.get("contacts", body.client_contact_id)
    if not body.force and body.event_date:
        dup = await db.opportunities.find_one(ctx.q({"client_contact_id": c["id"], "event_date": body.event_date}), {"_id": 0})
        if dup:
            raise HTTPException(409, {"message": "Une opportunité existe déjà pour ce client à cette date", "opportunity_id": dup["id"]})
    stage = next((s for s in cfg["stages"] if s["key"] == body.stage_key), cfg["stages"][0])
    d = body.model_dump(exclude={"force"})
    d["title"] = d["title"] or f"{body.event_type} {c.get('last_name') or contact_name(c)}" + (f" — {body.event_date[8:]}/{body.event_date[5:7]}/{body.event_date[:4]}" if body.event_date else "")
    d.update(stage_key=stage["key"], probability=stage["default_probability"] if body.probability is None else body.probability, main_contact_id=body.main_contact_id or c["id"],
             next_action=body.next_action or "Répondre à la demande", next_action_date=body.next_action_date or today(), language=c.get("language") or "fr-FR",
             owner_id=body.owner_id or ctx.member.get("user_id", ""), quote_ids=[], event_id=None, lost_reason="", lost_comment="", won_at=None, lost_at=None, last_activity_at=now_iso())
    d["weighted_amount"] = weighted(d)
    o = await ctx.insert("opportunities", d)
    await log(ctx, o["id"], "stage_change", f"Opportunité créée — {stage['label']}")
    return o


@router.post("/opportunities")
async def post_opp(body: OppIn, ctx: Ctx = Depends(C)):
    return await create_opp(ctx, body)


async def sync_quotes(ctx: Ctx, o: dict, cfg: dict) -> dict:
    if not o.get("quote_ids") or o["stage_key"] in ("gagnee", "perdue"):
        return o
    qs = await ctx.list("quotes", {"id": {"$in": o["quote_ids"]}})
    order = {s["key"]: s["order"] for s in cfg["stages"]}
    target = "gagnee" if any(q["status"] == "accepte" for q in qs) else "devis_envoye" if any(q["status"] in ("envoye", "vu", "negociation") for q in qs) else None
    if target and order.get(target, 0) > order.get(o["stage_key"], 0):
        o = await set_stage(ctx, o, target, cfg, auto=True)
    return o


async def set_stage(ctx: Ctx, o: dict, key: str, cfg: dict, auto: bool = False, extra: dict | None = None) -> dict:
    st = next((s for s in cfg["stages"] if s["key"] == key), None)
    if not st:
        raise HTTPException(400, "Étape inconnue")
    old = next((s["label"] for s in cfg["stages"] if s["key"] == o["stage_key"]), o["stage_key"])
    upd = {"stage_key": key, "probability": st["default_probability"], **(extra or {})}
    if st["is_won"]:
        upd["won_at"] = now_iso()
    if st["is_lost"]:
        upd["lost_at"] = now_iso()
    upd["weighted_amount"] = weighted({**o, **upd})
    o = await ctx.update("opportunities", o["id"], upd)
    await log(ctx, o["id"], "stage_change", f"{old} → {st['label']} ({st['default_probability']:g} %)" + (" — automatique (devis)" if auto else ""))
    return o


async def enrich(ctx: Ctx, rows: list) -> list:
    ids = {x for o in rows for x in (o["client_contact_id"], o.get("organizer_contact_id")) if x}
    names = {c["id"]: contact_name(c) for c in await ctx.list("contacts", {"id": {"$in": list(ids)}})}
    taken = {e["start"][:10] for e in await ctx.list("events", {"status": {"$in": ["confirme", "en_preparation"]}, "date_tbc": {"$ne": True}})}
    day = today()
    for o in rows:
        o["client_name"], o["organizer_name"] = names.get(o["client_contact_id"], ""), names.get(o.get("organizer_contact_id"), "")
        o["open"] = o["stage_key"] not in ("gagnee", "perdue")
        o["overdue"] = bool(o["open"] and o.get("next_action_date") and o["next_action_date"] < day)
        o["date_taken"] = bool(o["open"] and o.get("event_date") in taken)
    return rows


@router.get("/opportunities")
async def list_opps(ctx: Ctx = Depends(C)):
    cfg = await config(ctx.org_id)
    rows = [await sync_quotes(ctx, o, cfg) for o in await ctx.list("opportunities", sort=[("next_action_date", 1)])]
    return await enrich(ctx, rows)


@router.get("/opportunities/export.csv")
async def export(ctx: Ctx = Depends(C)):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Titre", "Client", "Organisateur", "Étape", "Source", "Date événement", "Montant", "HT/TTC", "Probabilité", "Pondéré", "Prochaine action", "Échéance"])
    for o in await enrich(ctx, await ctx.list("opportunities")):
        w.writerow([o["title"], o["client_name"], o["organizer_name"], o["stage_key"], o["source_key"], o["event_date"], o["amount"], o["amount_tax_mode"].upper(), o["probability"],
                    o["weighted_amount"], o["next_action"], o["next_action_date"]])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=opportunites.csv"})


@router.get("/opportunities/{oid}")
async def get_opp(oid: str, ctx: Ctx = Depends(C)):
    cfg = await config(ctx.org_id)
    o = (await enrich(ctx, [await sync_quotes(ctx, await ctx.get("opportunities", oid), cfg)]))[0]
    cids = [x for x in (o["client_contact_id"], o.get("organizer_contact_id")) if x]
    o["contacts"] = [{**{k: c.get(k, "") for k in ("id", "email", "phone", "language")}, "display_name": contact_name(c), "role": "Client" if c["id"] == o["client_contact_id"] else "Organisateur"}
                     for c in await ctx.list("contacts", {"id": {"$in": cids}})]
    tl = [{"at": a["occurred_at"], "type": a["type"], "body": a["body"], "by": a["created_by"], "meta": a.get("meta", {})} for a in await ctx.list("crm_activities", {"opportunity_id": oid})]
    convs = [c["id"] for c in await ctx.list("conversations", {"contact_id": {"$in": cids}, "deleted_at": None})]
    if convs:
        for m in await ctx.list("messages", {"conversation_id": {"$in": convs}, "deleted_at": None}, sort=[("sent_at", -1)], limit=50):
            tl.append({"at": m["sent_at"], "type": "email", "body": f"{m.get('subject', '')} — {(m.get('text') or '')[:300]}", "by": "Nous" if m["direction"] == "out" else (m.get("from") or {}).get("email", ""),
                       "meta": {"message_id": m["id"], "conversation_id": m["conversation_id"]}})
    o["timeline"] = sorted(tl, key=lambda x: x["at"], reverse=True)
    o["tasks"] = await ctx.list("tasks", {"opportunity_id": oid}, sort=[("due_date", 1)])
    o["quotes"] = [{k: q.get(k) for k in ("id", "number", "status", "total_ttc", "total_ht", "sent_at")} | {"share_token": await ensure_link("quotes", q)} for q in await ctx.list("quotes", {"id": {"$in": o.get("quote_ids", [])}})]
    v = await db.venues.find_one(ctx.q({"id": o.get("venue_id")}), {"_id": 0, "name": 1, "city": 1}) if o.get("venue_id") else None
    o["venue_name"] = (v or {}).get("name", "")
    return o


@router.patch("/opportunities/{oid}")
async def patch_opp(oid: str, body: OppPatch, ctx: Ctx = Depends(C)):
    cfg = await config(ctx.org_id)
    o = await ctx.get("opportunities", oid)
    ch = body.model_dump(exclude_unset=True, exclude={"force"})
    stage = ch.pop("stage_key", None)
    new = {**o, **ch}
    target = next((s for s in cfg["stages"] if s["key"] == (stage or o["stage_key"])), None)
    if not target:
        raise HTTPException(400, "Étape inconnue")
    if target["is_lost"] and new.get("lost_reason") not in LOST:
        raise HTTPException(400, "Un motif de perte est obligatoire")
    if not (target["is_lost"] or target["is_won"]) and not (new.get("next_action") and new.get("next_action_date")):
        raise HTTPException(400, "Une prochaine action datée est obligatoire tant que l'opportunité est ouverte")
    if "amount" in ch and ch["amount"] != o.get("amount"):
        await log(ctx, oid, "note", f"Montant : {o.get('amount', 0):g} € → {ch['amount']:g} €")
    if ch:
        ch["weighted_amount"] = weighted(new)
        o = await ctx.update("opportunities", oid, ch)
    if stage and stage != o["stage_key"]:
        o = await set_stage(ctx, o, stage, cfg, extra={"probability": ch["probability"]} if "probability" in ch else None)
    return o


@router.delete("/opportunities/{oid}")
async def delete_opp(oid: str, ctx: Ctx = Depends(C)):
    await ctx.delete("opportunities", oid)
    await db.crm_activities.delete_many(ctx.q({"opportunity_id": oid}))
    await db.tasks.update_many(ctx.q({"opportunity_id": oid}), {"$set": {"deleted_at": now_iso(), "deleted_by": ctx.member.get("name", ""), "purge_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()}})
    return {"ok": True}


class ActivityIn(BaseModel):
    type: Literal["note", "call", "meeting", "whatsapp"] = "note"
    body: str = Field(min_length=1, max_length=5000)
    duration_min: int = Field(0, ge=0)


@router.post("/opportunities/{oid}/activities")
async def add_activity(oid: str, body: ActivityIn, ctx: Ctx = Depends(C)):
    await ctx.get("opportunities", oid)
    await log(ctx, oid, body.type, body.body, meta={"duration_min": body.duration_min} if body.duration_min else None)
    return {"ok": True}


class PostponeIn(BaseModel):
    days: int = Field(ge=0, le=60)
    done: bool = False
    next_action: str = Field("", max_length=200)


@router.post("/opportunities/{oid}/postpone")
async def postpone(oid: str, body: PostponeIn, ctx: Ctx = Depends(C)):
    o = await ctx.get("opportunities", oid)
    base = max(o.get("next_action_date") or today(), today()) if not body.done else today()
    d = (datetime.strptime(base, "%Y-%m-%d") + timedelta(days=body.days or (3 if body.done else 0))).strftime("%Y-%m-%d")
    if body.done:
        await log(ctx, oid, "note", f"Action faite : {o.get('next_action', '')}")
    return await ctx.update("opportunities", oid, {"next_action_date": d, **({"next_action": body.next_action or "Relancer"} if body.done else {})})


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    done: bool = False


@router.post("/opportunities/{oid}/tasks")
async def add_task(oid: str, body: TaskIn, ctx: Ctx = Depends(C)):
    o = await ctx.get("opportunities", oid)
    from routes_admin import crm_task
    return await ctx.insert("tasks", {**crm_task(oid, body.due_date, body.done, o.get("owner_id", "")), **body.model_dump(), "opportunity_id": oid, "event_id": o.get("event_id"), "owner_id": o.get("owner_id", ""), "done_at": None, "created_by": ctx.member.get("name")})


@router.patch("/tasks/{tid}")
async def patch_task(tid: str, body: TaskIn, ctx: Ctx = Depends(C)):
    await ctx.get("tasks", tid, {"opportunity_id": {"$nin": [None, ""]}})
    return await ctx.update("tasks", tid, {**body.model_dump(), "done_at": now_iso() if body.done else None, "due_at": body.due_date, "status": "done" if body.done else "todo"})


class LinkIn(BaseModel):
    quote_id: str


@router.post("/opportunities/{oid}/quotes")
async def link_quote(oid: str, body: LinkIn, ctx: Ctx = Depends(C)):
    o = await ctx.get("opportunities", oid)
    q = await ctx.get("quotes", body.quote_id)
    upd = {"quote_ids": list(dict.fromkeys(o.get("quote_ids", []) + [q["id"]])), "event_id": o.get("event_id") or q["event_id"], "amount": q["total_ttc"], "amount_tax_mode": "ttc"}
    upd["weighted_amount"] = weighted({**o, **upd})
    await log(ctx, oid, "quote_sent", f"Devis {q['number']} lié ({q['total_ttc']:.2f} € TTC)", meta={"quote_id": q["id"]})
    return await ctx.update("opportunities", oid, upd)


class WinIn(BaseModel):
    event_id: str = ""


@router.post("/opportunities/{oid}/win")
async def win(oid: str, body: WinIn, ctx: Ctx = Depends(C)):
    cfg = await config(ctx.org_id)
    o = await ctx.get("opportunities", oid)
    eid = body.event_id or o.get("event_id")
    if eid:
        await ctx.get("events", eid)
    else:
        if not ctx.can("events:write"):
            raise HTTPException(403, "Action non autorisée pour votre rôle")
        d = o.get("event_date")
        start = f"{d}T18:00" if d else "2099-12-31T18:00"
        mods = [m["key"] for m in await module_catalog(ctx.org_id)]
        r = await create_event(EventIn(title=o["title"], type=o.get("event_type") or "Autre", client_id=o["client_contact_id"], client_contact_ids=[o["client_contact_id"]],
                                       signatory_contact_id=o["client_contact_id"], planner_contact_id=o.get("organizer_contact_id") or None, venue_id=o.get("venue_id") or "", start=start,
                                       end=(datetime.strptime(start[:10], "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%dT02:00"), guests=o.get("guest_count", 0), budget=o.get("amount", 0),
                                       budget_tax_mode=o.get("amount_tax_mode", "ttc"), modules=[k for k in o.get("services", []) if k in mods] or mods[:1], date_tbc=not d, notes=o.get("notes", "")), ctx)
        eid = r["id"]
    if o["stage_key"] != "gagnee":
        o = await set_stage(ctx, o, "gagnee", cfg)
    return await ctx.update("opportunities", oid, {"event_id": eid})


async def followup_text(ctx: Ctx, o: dict) -> dict:
    c = await ctx.get("contacts", o.get("main_contact_id") or o["client_contact_id"])
    lg = doc_lang(c.get("language"))
    t = await db.message_templates.find_one(ctx.q({"type": "crm_followup", "language": lg}), {"_id": 0})
    subject, body = (t["subject"], t["body"]) if t else FOLLOWUP[lg]
    labels = {m["key"]: m["label"] for m in await module_catalog(ctx.org_id)}
    q = await db.quotes.find_one(ctx.q({"id": {"$in": o.get("quote_ids", [])}}), {"_id": 0}, sort=[("created_at", -1)])
    org = await db.contacts.find_one(ctx.q({"id": o.get("organizer_contact_id")}), {"_id": 0}) if o.get("organizer_contact_id") else None
    v = {"prénom": c.get("first_name") or contact_name(c), "date_evenement": fmt_date(o.get("event_date", ""), c.get("language")), "lieu": o.get("city") or "—",
         "prestations": ", ".join(labels.get(k, k) for k in o.get("services", [])) or "—", "lien_devis": f"{os.environ.get('APP_URL', '')}/devis/{await ensure_link('quotes', q)}" if q else "",
         "nom_organisateur": contact_name(org) if org else ""}
    from providers_core import render
    return {"to": c.get("email", ""), "contact_id": c["id"], "language": lg, "subject": render(subject, v), "body": render(body, v)}


@router.get("/opportunities/{oid}/followup")
async def followup(oid: str, ctx: Ctx = Depends(C)):
    return await followup_text(ctx, await ctx.get("opportunities", oid))


class SendIn(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)


@router.post("/opportunities/{oid}/followup")
async def send_followup(oid: str, body: SendIn, ctx: Ctx = Depends(C)):
    o = await ctx.get("opportunities", oid)
    f = await followup_text(ctx, o)
    acc = await db.channel_accounts.find_one(ctx.q({"channel": "gmail", "status": "connected"}), {"_id": 0})
    if not acc or not f["to"]:
        raise HTTPException(400, "Boîte Gmail non connectée ou interlocuteur sans e-mail : copiez le message")
    cid = await mc.send_mail(acc, await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}), f["to"], body.subject, body.body)
    await db.conversations.update_one(ctx.q({"id": cid}), {"$set": {"contact_id": f["contact_id"]}})
    await log(ctx, oid, "email", f"Relance envoyée à {f['to']} : {body.subject}", contact_id=f["contact_id"])
    return {"ok": True}


@router.post("/opportunities/{oid}/summary")
async def summary(oid: str, ctx: Ctx = Depends(C)):
    if not mc.ai_ready():
        mc.ai_fail()
    o = await get_opp(oid, ctx)
    text = "\n".join(f"[{t['at'][:10]} {t['type']} {t['by']}] {t['body']}" for t in reversed(o["timeline"][:40]))
    r = await mc.claude().messages.create(
        model=os.environ.get("LLM_MODEL") or os.environ.get("CLAUDE_REPLY_MODEL") or "claude-sonnet-5-5", max_tokens=700,
        system="Tu résumes en français une opportunité commerciale d'une société événementielle : synthèse en 5 lignes, puis « Besoins », « Points en suspens », « Prochaine action suggérée ». N'invente rien." + mc.GUARD,
        messages=[{"role": "user", "content": f"Opportunité : {o['title']} — {o['client_name']} — {o.get('event_date')} — {o.get('city')} — {o.get('amount')} € — notes : {o.get('notes', '')}\n\nHistorique :\n{text}"}])
    return {"summary": "".join(b.text for b in r.content if b.type == "text").strip()}


@router.get("/dashboard")
async def dashboard(ctx: Ctx = Depends(C), date_from: str = "", date_to: str = ""):
    rows = await ctx.list("opportunities")
    opened = [o for o in rows if o["stage_key"] not in ("gagnee", "perdue")]
    inp = lambda d: bool(d) and (not date_from or d[:10] >= date_from) and (not date_to or d[:10] <= date_to)  # noqa: E731
    won, lost = [o for o in rows if o["stage_key"] == "gagnee" and inp(o.get("won_at"))], [o for o in rows if o["stage_key"] == "perdue" and inp(o.get("lost_at"))]

    def rate(key: str) -> list:
        out = {}
        for o in won + lost:
            x = out.setdefault(o.get(key) or "—", [0, 0])
            x[0 if o["stage_key"] == "gagnee" else 1] += 1
        return [{"key": k, "won": w, "lost": l, "rate": round(100 * w / (w + l))} for k, (w, l) in sorted(out.items())]
    days = [(datetime.fromisoformat(o["won_at"]) - datetime.fromisoformat(o["created_at"])).days for o in won]
    first = []
    for o in rows:
        a = await db.crm_activities.find_one(ctx.q({"opportunity_id": o["id"], "type": {"$in": ["call", "email", "note", "meeting", "whatsapp", "quote_sent"]}}), {"_id": 0}, sort=[("occurred_at", 1)])
        if a:
            first.append((datetime.fromisoformat(a["occurred_at"]) - datetime.fromisoformat(o["created_at"])).total_seconds() / 3600)
    reasons, forecast = {}, {}
    for o in lost:
        reasons[o.get("lost_reason") or "autre"] = reasons.get(o.get("lost_reason") or "autre", 0) + 1
    for o in [x for x in rows if x["stage_key"] == "gagnee" and x.get("event_date")]:
        forecast[o["event_date"][:7]] = round(forecast.get(o["event_date"][:7], 0) + o.get("amount", 0), 2)
    return {"open": {"count": len(opened), "total": round(sum(o.get("amount", 0) for o in opened), 2), "weighted": round(sum(weighted(o) for o in opened), 2)},
            "won": {"count": len(won), "total": round(sum(o.get("amount", 0) for o in won), 2)}, "lost": {"count": len(lost), "total": round(sum(o.get("amount", 0) for o in lost), 2)},
            "conversion_rate": round(100 * len(won) / (len(won) + len(lost))) if won or lost else None, "by_source": rate("source_key"), "by_type": rate("event_type"),
            "avg_first_response_h": round(sum(first) / len(first), 1) if first else None, "avg_days_to_win": round(sum(days) / len(days), 1) if days else None,
            "lost_reasons": reasons, "forecast": dict(sorted(forecast.items()))}


class LeadIn(BaseModel):
    first_name: str = Field("", max_length=80)
    last_name: str = Field("", max_length=80)
    email: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    event_type: str = "Autre"
    event_date: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    city: str = Field("", max_length=80)
    guest_count: int = Field(0, ge=0)
    services: List[str] = []
    amount: float = Field(0, ge=0)
    notes: str = Field("", max_length=5000)
    language: str = "fr-FR"


@router.post("/leads")
async def lead(body: LeadIn, x_api_key: str = Header("")):
    key = os.environ.get("CRM_LEADS_API_KEY")
    if not key:
        raise HTTPException(503, "Webhook non configuré")
    if not hmac.compare_digest(x_api_key.encode(), key.encode()):
        raise HTTPException(401, "Unauthorized")
    org = await db.orgs.find_one({"slug": os.environ.get("CRM_LEADS_ORG_SLUG") or DEMO_SLUG}, {"_id": 0})
    if not org or not (body.email or body.phone):
        raise HTTPException(400, "E-mail ou téléphone requis")
    ctx = Ctx({"org_id": org["id"], "role": "gerant", "name": "Site web"})
    c = await db.contacts.find_one(ctx.q({"email": body.email.lower()}), {"_id": 0}) if body.email else None
    if not c:
        c = await ctx.insert("contacts", {"kind": "particulier", "status": "prospect", "first_name": body.first_name, "last_name": body.last_name, "company": "", "email": body.email.lower(),
                                          "phone": body.phone, "address": "", "city": body.city, "source": "Site web", "tags": [], "notes": "", "types": ["client"], "language": body.language, "interactions": []})
    o = await create_opp(ctx, OppIn(client_contact_id=c["id"], source_key="site_web", force=True, **body.model_dump(exclude={"first_name", "last_name", "email", "phone", "language"})))
    return {"opportunity_id": o["id"]}


async def tick() -> None:
    day = today()
    async for org in db.orgs.find({}, {"_id": 0}):
        limit = (datetime.now(PARIS) - timedelta(days=org.get("crm_followup_days", 5))).isoformat()
        async for o in db.opportunities.find({"org_id": org["id"], "stage_key": "devis_envoye", "last_activity_at": {"$lt": limit}}, {"_id": 0}):
            if await db.tasks.find_one({"org_id": org["id"], "opportunity_id": o["id"], "auto": True, "done": False}):
                continue
            from routes_admin import crm_task
            await db.tasks.insert_one({**crm_task(o["id"], day, False, o.get("owner_id", ""), True), "created_by": "Système", "id": new_id(), "org_id": org["id"], "opportunity_id": o["id"], "event_id": o.get("event_id"), "title": f"Relancer : {o['title']}", "due_date": day,
                                           "owner_id": o.get("owner_id", ""), "done": False, "done_at": None, "auto": True, "created_at": now_iso()})
        due = await db.opportunities.find({"org_id": org["id"], "stage_key": {"$nin": ["gagnee", "perdue"]}, "next_action_date": {"$lte": day, "$gt": ""}}, {"_id": 0}).to_list(200)
        acc = await db.channel_accounts.find_one({"org_id": org["id"], "channel": "gmail", "status": "connected"}, {"_id": 0})
        if due and acc:
            lines = "\n".join(f"- {o['next_action_date'][8:]}/{o['next_action_date'][5:7]} · {o['title']} : {o['next_action']}" for o in due)
            try:
                await mc.send_mail(acc, org, acc["email"], f"CRM — {len(due)} action(s) à faire aujourd'hui", f"Bonjour,\n\nActions du jour et en retard :\n{lines}")
            except Exception as exc:
                logger.error("Récap CRM en échec : %s", exc)


async def alerts(ctx: Ctx) -> list:
    if not ctx.can("crm:manage"):
        return []
    rows = await ctx.list("opportunities", {"stage_key": {"$nin": ["gagnee", "perdue"]}, "next_action_date": {"$lte": today(), "$gt": ""}})
    return [{"type": "crm", "severity": "warning", "event_id": None, "opportunity_id": o["id"], "title": f"CRM : {o['next_action']}", "detail": o["title"]} for o in rows]
