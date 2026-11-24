"""Finance & pilotage (sans comptabilité ni Pennylane) : activités, canaux, engagements, finances d'un événement."""
import re
import unicodedata
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import Ctx, audit, db, need, new_id, now_iso

router = APIRouter(prefix="/api")
R, W = need("pilot:view"), need("pilot:manage")
ACTIVITIES = [
    {"id": "dj_sax", "name": "DJ / sax", "color": "violet", "categories": [], "keywords": ["dj", "sax", "saxophon", "musicien", "violon", "percussion"]},
    {"id": "mobilier", "name": "Location de mobilier", "color": "ambre", "categories": ["Mobilier", "Scène & piste", "Vaisselle", "Décoration"], "keywords": ["mobilier", "chaise", "table"]},
    {"id": "son_lumiere", "name": "Son & lumière", "color": "bleu", "categories": ["Son", "Sonorisation", "Lumière", "Éclairage", "Vidéo"], "keywords": ["sono", "enceinte", "micro", "lumiere", "eclairage"]},
    {"id": "regie", "name": "Régie technique", "color": "vert", "categories": [], "keywords": ["regie", "regisseur", "technicien"]},
    {"id": "logistique", "name": "Logistique / transport", "color": "gris", "categories": [], "keywords": ["livraison", "transport", "reprise", "installation", "manutention", "deplacement"]},
    {"id": "autre", "name": "Autre", "color": "gris", "categories": [], "keywords": []}]
CHANNELS = [
    {"id": "client_direct", "name": "Client direct", "type": "direct", "source_keys": ["email", "sms", "whatsapp"]},
    {"id": "wedding_planner", "name": "Wedding planner", "type": "planner", "source_keys": ["organisateur"]},
    {"id": "lieu_partenaire", "name": "Lieu partenaire", "type": "venue", "source_keys": []},
    {"id": "site_internet", "name": "Site internet", "type": "other", "source_keys": ["site_web"]},
    {"id": "instagram", "name": "Instagram", "type": "other", "source_keys": ["instagram"]},
    {"id": "recommandation", "name": "Recommandation", "type": "other", "source_keys": ["recommandation"]},
    {"id": "autre", "name": "Autre", "type": "other", "source_keys": ["salon", "autre"]}]
DEFAULT = {"activities": ACTIVITIES, "channels": CHANNELS, "margin_threshold": 30, "provider_payment_days": 30, "fixed_costs_monthly": None, "variable_margin_rate": None}
CATS = {"prestataires": "Prestataires", "staff": "Staff", "materiel_loue": "Matériel loué", "consommables": "Consommables", "transport": "Transport", "casse": "Casse", "autre": "Autres frais"}
STATUSES = ["prevu", "confirme", "facture", "paye", "annule"]
r2 = lambda x: round(x or 0, 2)  # noqa: E731


def norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


async def settings(org_id: str) -> dict:
    d = await db.finance_settings.find_one({"org_id": org_id}, {"_id": 0}) or {}
    return {**DEFAULT, **{k: d[k] for k in DEFAULT if d.get(k) is not None}}


def activity_of(line: dict, eqs: dict, acts: list) -> str:
    if line.get("activity_id") in [a["id"] for a in acts]:
        return line["activity_id"]
    cat, text = norm((eqs.get(line.get("equipment_id")) or {}).get("category", "")), norm(line.get("label", ""))
    for a in acts:
        if cat and cat in [norm(c) for c in a.get("categories") or []]:
            return a["id"]
    for a in acts:
        if any(re.search(rf"\b{re.escape(norm(k))}", text) for k in a.get("keywords") or []):
            return a["id"]
    return acts[-1]["id"]


def split_by_activity(q: Optional[dict], eqs: dict, acts: list) -> dict:
    lines = (q or {}).get("lines") or []
    raw = [(activity_of(l, eqs, acts), (l.get("qty") or 0) * (l.get("unit_price") or 0)) for l in lines]
    total = sum(v for _, v in raw)
    out: dict = {}
    for a, v in raw:
        out[a] = out.get(a, 0) + (v / total * (q.get("total_ht") or 0) if total else 0)
    return {a: r2(v) for a, v in out.items() if v}


def channel_of(ev: dict, opp: Optional[dict], chans: list) -> str:
    ids = [c["id"] for c in chans]
    if ev.get("channel_id") in ids:
        return ev["channel_id"]
    hit = next((c["id"] for c in chans if (opp or {}).get("source_key") in (c.get("source_keys") or [])), None)
    return hit or next((c["id"] for c in chans if c.get("type") == ("planner" if ev.get("planner_contact_id") else "direct")), ids[0])


def pick_quote(qs: list) -> Optional[dict]:
    qs = sorted(qs, key=lambda q: q.get("created_at", ""), reverse=True)
    return next((q for q in qs if q["status"] == "accepte"), None) or next((q for q in qs if q["status"] in ("envoye", "vu")), None)


def event_finance(ev: dict, qs: list, invs: list, cms: list, cfg: dict, eqs: dict, opp: Optional[dict] = None, sent_prob: float = 50) -> dict:
    q = pick_quote(qs)
    signed = bool(q and q["status"] == "accepte")
    quoted = (q or {}).get("total_ht") or (0 if q else ev.get("amount_ht") or 0)
    acc = [x for x in qs if x["status"] == "accepte" and x.get("active") is not False]
    quoted = sum(x.get("total_ht") or 0 for x in acc) if acc else quoted
    invs = [i for i in invs if i.get("status") != "annulee"]
    inv_ht, inv_ttc, paid = sum(i.get("total_ht") or 0 for i in invs), sum(i.get("total_ttc") or 0 for i in invs), sum(i.get("paid_amount") or 0 for i in invs)
    live = [c for c in cms if c["kind"] == "expense" and c["status"] != "annule"]
    cats = {k: {"label": l, "planned": 0, "invoiced": 0, "paid": 0} for k, l in CATS.items()}
    for c in live:
        row, real = cats[c["category"] if c["category"] in cats else "autre"], c.get("actual_ht") if c.get("actual_ht") is not None else c["amount_ht"]
        row["planned"] += c["amount_ht"]
        row["invoiced"] += real if c["status"] in ("facture", "paye") else 0
        row["paid"] += real if c["status"] == "paye" else 0
    extra = ev.get("extra_costs") or 0
    for k in ("planned", "invoiced", "paid"):
        cats["autre"][k] += extra
    est = sum(p.get("cost") or 0 for p in ev.get("prestations") or [])
    if est and not cats["prestataires"]["planned"]:
        cats["prestataires"]["planned"], cats["prestataires"]["estimated"] = est, True
    planned, real = sum(c["planned"] for c in cats.values()), sum(c["invoiced"] for c in cats.values())
    mp, mr = quoted - planned, inv_ht - real
    pct = lambda m, b: round(m / b * 100, 1) if b else None  # noqa: E731
    return {"event_id": ev["id"], "quote": {"id": q["id"], "number": q.get("number"), "status": q["status"]} if q else None, "signed": signed,
            "probability": 100 if signed else (opp or {}).get("probability", sent_prob) if q else 0,
            "revenue": {"quoted_ht": r2(quoted), "invoiced_ht": r2(inv_ht), "paid_ttc": r2(paid), "due_ttc": r2(max(0, inv_ttc - paid))},
            "by_activity": split_by_activity(q, eqs, cfg["activities"]),
            "charges": {"categories": [{"key": k, **{x: r2(y) if isinstance(y, (int, float)) and not isinstance(y, bool) else y for x, y in v.items()}} for k, v in cats.items() if v["planned"] or v["invoiced"]],
                        "planned": r2(planned), "invoiced": r2(real), "paid": r2(sum(c["paid"] for c in cats.values()))},
            "margin_planned": r2(mp), "margin_planned_pct": pct(mp, quoted), "margin_real": r2(mr) if inv_ht else None, "margin_real_pct": pct(mr, inv_ht),
            "threshold": cfg["margin_threshold"], "alert": pct(mp, quoted) is not None and pct(mp, quoted) < cfg["margin_threshold"]}


async def on_mission(org_id: str, m: dict) -> None:
    """Prestataire retenu → engagement de charge (une seule fois par mission)."""
    if not m.get("event_id") or await db.commitments.find_one({"org_id": org_id, "source": "mission", "source_id": m["id"]}):
        return
    from datetime import date, timedelta
    days = (await settings(org_id))["provider_payment_days"]
    due = (date.fromisoformat(m["date"][:10]) + timedelta(days=days)).isoformat() if m.get("date") else ""
    ht = m.get("total_ht") or 0
    await db.commitments.insert_one({"id": new_id(), "org_id": org_id, "event_id": m["event_id"], "kind": "expense", "category": "prestataires", "label": f"{m.get('provider_name', 'Prestataire')} — {m.get('category_key', '')}",
                                     "amount_ht": ht, "vat": r2((m.get("total_ttc") or ht) - ht), "due_date": due, "probability": 100, "source": "mission", "source_id": m["id"], "status": "confirme",
                                     "invoice_ref": "", "paid_at": None, "actual_ht": None, "history": [], "created_at": now_iso()})


async def sync_missions(org_id: str, eid: str) -> None:
    async for m in db.missions.find({"org_id": org_id, "event_id": eid, "status": {"$ne": "cancelled"}}, {"_id": 0}):
        await on_mission(org_id, m)


class Activity(BaseModel):
    id: str = Field("", max_length=40)
    name: str = Field(min_length=1, max_length=60)
    color: str = "gris"
    categories: List[str] = []
    keywords: List[str] = []


class Channel(BaseModel):
    id: str = Field("", max_length=40)
    name: str = Field(min_length=1, max_length=60)
    type: Literal["direct", "planner", "venue", "other"] = "other"
    source_keys: List[str] = []


class SettingsIn(BaseModel):
    activities: List[Activity] = Field(min_length=1, max_length=20)
    channels: List[Channel] = Field(min_length=1, max_length=20)
    margin_threshold: float = Field(30, ge=0, le=100)
    provider_payment_days: int = Field(30, ge=0, le=180)
    fixed_costs_monthly: Optional[float] = Field(None, ge=0)
    variable_margin_rate: Optional[float] = Field(None, gt=0, le=100)


def _ids(rows: list) -> list:
    seen, out = set(), []
    for r in rows:
        rid = r["id"] or re.sub(r"[^a-z0-9]+", "_", norm(r["name"])).strip("_") or "x"
        while rid in seen:
            rid += "_2"
        seen.add(rid)
        out.append({**r, "id": rid})
    return out


@router.get("/finance/settings")
async def get_settings(ctx: Ctx = Depends(R)):
    return {**await settings(ctx.org_id), "categories": CATS, "statuses": STATUSES, "can_manage": ctx.can("pilot:manage"), "pennylane": False,
            "catalog_categories": sorted(c for c in await db.equipment.distinct("category", {"org_id": ctx.org_id}) if c)}


@router.put("/finance/settings")
async def put_settings(body: SettingsIn, ctx: Ctx = Depends(W)):
    d = body.model_dump()
    d["activities"], d["channels"] = _ids(d["activities"]), _ids(d["channels"])
    await db.finance_settings.update_one({"org_id": ctx.org_id}, {"$set": {**d, "updated_at": now_iso()}}, upsert=True)
    await audit(ctx.org_id, ctx.member, "finance_settings", "Réglages Finance", f"{len(d['activities'])} activités, {len(d['channels'])} canaux")
    return await get_settings(ctx)


async def _event(ctx: Ctx, eid: str) -> dict:
    return await ctx.get("events", eid, ctx.event_scope())


@router.get("/events/{eid}/finance")
async def get_event_finance(eid: str, ctx: Ctx = Depends(need("finance:read"))):
    ev = await _event(ctx, eid)
    await sync_missions(ctx.org_id, eid)
    cfg = await settings(ctx.org_id)
    eqs = {e["id"]: e async for e in db.equipment.find(ctx.q({}), {"_id": 0, "id": 1, "category": 1})}
    opp = await db.opportunities.find_one(ctx.q({"event_id": eid}), {"_id": 0, "source_key": 1, "probability": 1})
    cms = await ctx.list("commitments", {"event_id": eid}, sort=[("due_date", 1)])
    from routes_social_pay import event_costs
    cms += await event_costs(ctx.org_id, eid)
    out = event_finance(ev, await ctx.list("quotes", {"event_id": eid}), await ctx.list("invoices", {"event_id": eid}), cms, cfg, eqs, opp)
    out.update(channel_id=channel_of(ev, opp, cfg["channels"]), channels=[{"id": c["id"], "name": c["name"]} for c in cfg["channels"]],
               activities={a["id"]: a["name"] for a in cfg["activities"]}, costs=ctx.can("finance:costs"), write=ctx.can("finance:write") and ctx.can("finance:costs"))
    if not out["costs"]:
        for k in ("charges", "margin_planned", "margin_planned_pct", "margin_real", "margin_real_pct", "alert", "threshold"):
            out.pop(k)
        return out
    return {**out, "commitments": cms, "categories": CATS}


class CommitIn(BaseModel):
    kind: Literal["income", "expense"] = "expense"
    category: str = "autre"
    label: str = Field(min_length=1, max_length=160)
    amount_ht: float = Field(ge=0, le=10000000)
    vat: float = Field(0, ge=0)
    due_date: str = Field("", max_length=10)
    probability: float = Field(100, ge=0, le=100)


def costs_w(ctx: Ctx = Depends(need("finance:write"))) -> Ctx:
    if not ctx.can("finance:costs"):
        raise HTTPException(403, "Réservé aux profils qui voient les coûts")
    return ctx


@router.post("/events/{eid}/finance/commitments")
async def add_commitment(eid: str, body: CommitIn, ctx: Ctx = Depends(costs_w)):
    await _event(ctx, eid)
    if body.category not in CATS:
        raise HTTPException(400, "Catégorie inconnue")
    await ctx.insert("commitments", {**body.model_dump(), "event_id": eid, "source": "manual", "source_id": "", "status": "prevu", "invoice_ref": "", "paid_at": None, "actual_ht": None, "history": []})
    return await get_event_finance(eid, ctx)


class CommitStatus(BaseModel):
    status: str
    actual_ht: Optional[float] = Field(None, ge=0)
    invoice_ref: str = Field("", max_length=80)


@router.put("/events/{eid}/finance/commitments/{cid}")
async def set_commitment(eid: str, cid: str, body: CommitStatus, ctx: Ctx = Depends(costs_w)):
    c = await ctx.get("commitments", cid, {"event_id": eid})
    if body.status not in STATUSES:
        raise HTTPException(400, "Statut inconnu")
    real = body.actual_ht if body.actual_ht is not None else c.get("actual_ht")
    h = {"at": now_iso(), "by": ctx.member.get("name"), "from": c["status"], "to": body.status, "planned_ht": c["amount_ht"], "actual_ht": real, "gap": r2(real - c["amount_ht"]) if real is not None else None}
    await db.commitments.update_one(ctx.q({"id": cid}), {"$set": {"status": body.status, "actual_ht": real, "invoice_ref": body.invoice_ref or c.get("invoice_ref", ""),
                                                                 "paid_at": now_iso() if body.status == "paye" else None, "updated_at": now_iso()}, "$push": {"history": h}})
    return await get_event_finance(eid, ctx)


class ChannelIn(BaseModel):
    channel_id: str = ""


@router.put("/events/{eid}/finance/channel")
async def set_channel(eid: str, body: ChannelIn, ctx: Ctx = Depends(need("finance:write"))):
    await _event(ctx, eid)
    await db.events.update_one(ctx.q({"id": eid}), {"$set": {"channel_id": body.channel_id or None}})
    return await get_event_finance(eid, ctx)
