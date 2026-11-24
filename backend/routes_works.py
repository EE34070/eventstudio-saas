"""Travaux internes (ordres de travail) — lot 1 : données, API, backlog, chantiers en étapes, modèles, récurrence.

Hors événements : construction, rangement d'entrepôt, inventaires, réparations, atelier retour,
préparation, entretien véhicule, formation… Les lots suivants ajoutent le Planning (vue Équipe,
glisser-déposer, contrôles), « Mon planning » et le pointage, puis les effets stock / heures / coûts.

Droits (module « works » de la grille d'accès) : voir = events:read, écrire = catalog:write.
Technicien, ou profil en portée « own » : uniquement ses propres ordres, sans aucun coût.
"""
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import Ctx, audit, db, need, now_iso

router = APIRouter(prefix="/api")
R, W = need("events:read"), need("catalog:write")

DEFAULT_TYPES = [
    ("construction", "Construction / fabrication"), ("rangement", "Rangement / réorganisation entrepôt"),
    ("inventaire", "Inventaire"), ("reparation", "Réparation / maintenance matériel"),
    ("atelier_retour", "Atelier retour (lavage, contrôle, recharge)"), ("preparation", "Préparation"),
    ("entretien_vehicule", "Entretien véhicule"), ("formation", "Formation"), ("autre", "Autre"),
]
PRIORITIES = ("basse", "normale", "haute", "urgente")
STATUSES = ("a_planifier", "planifie", "en_cours", "en_pause", "fait", "reporte", "annule")
OPEN = ("a_planifier", "planifie", "en_cours", "en_pause", "reporte")
COST_FIELDS = ("cost_labor", "cost_materials", "cost_total")
Priority = Literal["basse", "normale", "haute", "urgente"]
Status = Literal["a_planifier", "planifie", "en_cours", "en_pause", "fait", "reporte", "annule"]
Effect = Literal["unavailable", "consume", "produce"]


# --------------------------------------------------------------------------------------
# Modèles d'entrée
# --------------------------------------------------------------------------------------
class Item(BaseModel):
    product_id: str = ""
    label: str = ""          # article à produire pas encore au catalogue (construction)
    quantity: float = Field(1, gt=0)
    effect: Effect = "unavailable"


class Tool(BaseModel):
    product_id: str = ""
    label: str = ""
    quantity: float = Field(1, gt=0)


class Check(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    done: bool = False


class WorkIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: str = "autre"
    description: str = ""
    priority: Priority = "normale"
    warehouse_id: str = ""
    zone: str = ""                     # rayonnage, atelier, quai…
    site: str = ""                     # site extérieur
    vehicle_id: str = ""
    event_id: str = ""
    scheduled_start: str = ""          # AAAA-MM-JJTHH:MM ; vide = à planifier (backlog)
    scheduled_end: str = ""
    deadline: str = ""                 # date limite souhaitée (AAAA-MM-JJ)
    estimated_minutes: int = Field(60, ge=0, le=60 * 24 * 60)  # minutes-personne
    required_people: int = Field(1, ge=1, le=50)
    required_skills: list[str] = []
    assignee_ids: list[str] = []       # identifiants des fiches Équipe
    lead_id: str = ""
    items: list[Item] = []
    tools: list[Tool] = []
    checklist: list[Check] = []
    attachments: list[str] = []
    photos_before: list[str] = []
    photos_after: list[str] = []
    status: Status | None = None
    parent_id: str = ""                # étape d'un chantier
    depends_on_ids: list[str] = []
    min_delay_after_hours: float = Field(0, ge=0, le=24 * 60)
    step_order: int = 0
    template_id: str = ""


class WorkPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    type: str | None = None
    description: str | None = None
    priority: Priority | None = None
    warehouse_id: str | None = None
    zone: str | None = None
    site: str | None = None
    vehicle_id: str | None = None
    event_id: str | None = None
    scheduled_start: str | None = None
    scheduled_end: str | None = None
    deadline: str | None = None
    estimated_minutes: int | None = Field(None, ge=0, le=60 * 24 * 60)
    required_people: int | None = Field(None, ge=1, le=50)
    required_skills: list[str] | None = None
    assignee_ids: list[str] | None = None
    lead_id: str | None = None
    items: list[Item] | None = None
    tools: list[Tool] | None = None
    checklist: list[Check] | None = None
    attachments: list[str] | None = None
    photos_before: list[str] | None = None
    photos_after: list[str] | None = None
    status: Status | None = None
    depends_on_ids: list[str] | None = None
    min_delay_after_hours: float | None = Field(None, ge=0, le=24 * 60)
    step_order: int | None = None


class TemplateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: str = "autre"
    description: str = ""
    estimated_minutes: int = Field(60, ge=0, le=60 * 24 * 60)
    required_people: int = Field(1, ge=1, le=50)
    required_skills: list[str] = []
    checklist: list[Check] = []
    items: list[Item] = []
    tools: list[Tool] = []
    priority: Priority = "normale"
    warehouse_id: str = ""
    zone: str = ""


class RecurrenceIn(BaseModel):
    template_id: str
    freq: Literal["weekly", "monthly"] = "weekly"
    interval: int = Field(1, ge=1, le=24)        # toutes les N semaines / N mois (6 = semestriel)
    weekdays: list[int] = [0]                    # 0 = lundi (freq weekly)
    monthday: int = Field(1, ge=1, le=28)        # jour du mois (freq monthly)
    start_time: str = "08:00"
    end_time: str = ""                           # vide = début + durée estimée / effectif
    start: str                                   # AAAA-MM-JJ
    end: str = ""                                # vide = sans fin
    default_assignee_ids: list[str] = []
    active: bool = True


class TypesIn(BaseModel):
    types: list[dict]


# --------------------------------------------------------------------------------------
# Outils
# --------------------------------------------------------------------------------------
def _own(ctx: Ctx) -> bool:
    return ctx.role == "technicien" or ctx.own("works") or (ctx.assigned_only and not ctx.can("catalog:write"))


def _scope(ctx: Ctx, f: dict | None = None) -> dict:
    f = dict(f or {})
    if _own(ctx):
        me = ctx.team_id or "__none__"
        f["$or"] = [{"assignee_ids": me}, {"lead_id": me}]
    return f


def _clean(ctx: Ctx, request: Request, d: dict) -> dict:
    if getattr(request.state, "no_cost", True) or _own(ctx):
        for k in COST_FIELDS:
            d.pop(k, None)
    return d


def _dt(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s[:16]) if s else None
    except ValueError:
        raise HTTPException(422, f"Date invalide : {s}")


def _end_from(start: str, minutes: int, people: int) -> str:
    """Fin par défaut : durée estimée répartie sur l'effectif requis."""
    st = _dt(start)
    dur = max(15, round(minutes / max(people, 1)))
    return (st + timedelta(minutes=dur)).strftime("%Y-%m-%dT%H:%M")


async def types_of(org_id: str) -> list[dict]:
    org = await db.orgs.find_one({"id": org_id}, {"_id": 0, "work_types": 1}) or {}
    return org.get("work_types") or [{"key": k, "label": lbl, "active": True} for k, lbl in DEFAULT_TYPES]


async def _check_refs(ctx: Ctx, d: dict) -> None:
    keys = {t["key"] for t in await types_of(ctx.org_id)}
    if d.get("type") and d["type"] not in keys:
        raise HTTPException(422, f"Type de travail inconnu : {d['type']}")
    for coll, field in (("events", "event_id"), ("warehouses", "warehouse_id"), ("vehicles", "vehicle_id"), ("team", "lead_id")):
        if d.get(field) and not await db[coll].find_one(ctx.q({"id": d[field]}), {"_id": 1}):
            raise HTTPException(422, f"Référence introuvable : {field}")
    ids = list(set(d.get("assignee_ids") or []))
    if ids and await db.team.count_documents(ctx.q({"id": {"$in": ids}})) != len(ids):
        raise HTTPException(422, "Personne affectée introuvable")
    if d.get("lead_id") and ids and d["lead_id"] not in ids:
        d["assignee_ids"] = ids + [d["lead_id"]]


def _schedule(d: dict, cur: dict | None = None) -> None:
    """Statut cohérent avec le créneau : sans créneau = à planifier ; créneau posé = planifié."""
    merged = {**(cur or {}), **d}
    start, end = merged.get("scheduled_start") or "", merged.get("scheduled_end") or ""
    if start and not end:
        d["scheduled_end"] = end = _end_from(start, merged.get("estimated_minutes") or 60, merged.get("required_people") or 1)
    if start and end and _dt(end) <= _dt(start):
        raise HTTPException(422, "La fin doit être après le début")
    status = d.get("status") or merged.get("status")
    if not start and status in (None, "planifie"):
        d["status"] = "a_planifier"
    elif start and status in (None, "a_planifier", "reporte"):
        d["status"] = "planifie"


async def _check_dependencies(ctx: Ctx, wid: str | None, merged: dict) -> None:
    """Une étape ne peut pas commencer avant la fin de ses dépendances + délai minimum (ex. séchage 24 h)."""
    deps = merged.get("depends_on_ids") or []
    if wid and wid in deps:
        raise HTTPException(422, "Une étape ne peut pas dépendre d'elle-même")
    if not deps:
        return
    rows = await db.work_orders.find(ctx.q({"id": {"$in": deps}}), {"_id": 0}).to_list(100)
    if len(rows) != len(set(deps)):
        raise HTTPException(422, "Étape dépendante introuvable")
    start = _dt(merged.get("scheduled_start") or "")
    if not start:
        return
    delay = timedelta(hours=merged.get("min_delay_after_hours") or 0)
    for r in rows:
        end = _dt(r.get("scheduled_end") or "")
        if not end:
            raise HTTPException(422, f"Planifiez d'abord l'étape « {r['title']} » dont celle-ci dépend")
        if start < end + delay:
            earliest = (end + delay).strftime("%d/%m/%Y %H:%M")
            raise HTTPException(422, f"Cette étape ne peut pas commencer avant le {earliest} (après « {r['title']} »"
                                     + (f" + {merged.get('min_delay_after_hours'):g} h" if delay else "") + ")")


async def _progress(ctx: Ctx, parent: dict) -> dict:
    steps = await db.work_orders.find(ctx.q({"parent_id": parent["id"]}), {"_id": 0}).sort("step_order", 1).to_list(200)
    live = [s for s in steps if s.get("status") != "annule"]
    done = sum(1 for s in live if s.get("status") == "fait")
    return {"steps": steps, "progress": {"done": done, "total": len(live), "percent": round(100 * done / len(live)) if live else 0,
                                         "estimated_minutes": sum(s.get("estimated_minutes") or 0 for s in live),
                                         "actual_minutes": sum(s.get("actual_minutes") or 0 for s in live)}}


def urgency(w: dict, events: dict, today: str) -> tuple:
    """Tri du backlog : en retard, date limite, priorité, événement lié qui approche."""
    ev_day = (events.get(w.get("event_id")) or {}).get("start", "")[:10] or "9999"
    limit = min(w.get("deadline") or "9999", ev_day)
    return (limit >= today, limit, -PRIORITIES.index(w.get("priority") or "normale"), w.get("created_at", ""))


# --------------------------------------------------------------------------------------
# Types de travaux (paramétrables par société)
# --------------------------------------------------------------------------------------
@router.get("/work-types")
async def get_types(ctx: Ctx = Depends(R)):
    return await types_of(ctx.org_id)


@router.put("/work-types")
async def put_types(body: TypesIn, ctx: Ctx = Depends(need("org:write"))):
    seen, out = set(), []
    for t in body.types:
        key, label = str(t.get("key") or "").strip(), str(t.get("label") or "").strip()
        if not key or not label or key in seen:
            raise HTTPException(422, "Chaque type doit avoir une clé unique et un libellé")
        seen.add(key)
        out.append({"key": key[:40], "label": label[:80], "active": bool(t.get("active", True))})
    used = await db.work_orders.distinct("type", ctx.q({"deleted_at": None}))
    missing = [u for u in used if u not in seen]
    if missing:
        raise HTTPException(422, f"Types encore utilisés, désactivez-les au lieu de les supprimer : {', '.join(missing)}")
    await db.orgs.update_one({"id": ctx.org_id}, {"$set": {"work_types": out}})
    return out


# --------------------------------------------------------------------------------------
# Ordres de travail
# --------------------------------------------------------------------------------------
@router.get("/work-orders")
async def list_orders(request: Request, status: str = "", type: str = "", backlog: bool = False, warehouse_id: str = "",
                      person: str = "", date_from: str = "", date_to: str = "", include_steps: bool = False, ctx: Ctx = Depends(R)):
    f: dict = {}
    if backlog:
        f["status"] = {"$in": ["a_planifier", "reporte"]}
    elif status:
        f["status"] = {"$in": status.split(",")}
    if type:
        f["type"] = {"$in": type.split(",")}
    if warehouse_id:
        f["warehouse_id"] = warehouse_id
    if person:
        f["assignee_ids"] = person
    if date_from or date_to:
        f["scheduled_start"] = {"$gt": "", **({"$lte": date_to} if date_to else {})}
        if date_from:
            f["scheduled_end"] = {"$gte": date_from}
    if not include_steps:
        f["parent_id"] = {"$in": ["", None]}
    rows = await ctx.list("work_orders", _scope(ctx, f), limit=5000)
    evs = {e["id"]: e for e in await ctx.list("events", {"id": {"$in": list({r.get("event_id") for r in rows if r.get("event_id")})}})}
    today = date.today().isoformat()
    rows.sort(key=(lambda w: urgency(w, evs, today)) if backlog else (lambda w: (w.get("scheduled_start") or "9999", w.get("created_at", ""))))
    for r in rows:
        r["late"] = r.get("status") in OPEN and bool(r.get("deadline")) and r["deadline"] < today
        r["event_title"] = (evs.get(r.get("event_id")) or {}).get("title", "")
        _clean(ctx, request, r)
    return {"orders": rows, "types": await types_of(ctx.org_id), "today": today}


@router.get("/work-orders/{wid}")
async def get_order(wid: str, request: Request, ctx: Ctx = Depends(R)):
    w = await db.work_orders.find_one(ctx.q(_scope(ctx, {"id": wid})), {"_id": 0})
    if not w:
        raise HTTPException(404, "Introuvable")
    out = {**w, **await _progress(ctx, w)}
    out["steps"] = [_clean(ctx, request, s) for s in out["steps"]]
    return _clean(ctx, request, out)


async def _create(ctx: Ctx, data: dict) -> dict:
    if data.get("template_id"):
        tpl = await ctx.get("work_templates", data["template_id"])
        base = {k: tpl[k] for k in ("title", "type", "description", "estimated_minutes", "required_people", "required_skills",
                                     "checklist", "items", "tools", "priority", "warehouse_id", "zone") if k in tpl}
        data = {**base, **{k: v for k, v in data.items() if v not in ("", [], None) or k not in base}}
    if data.get("parent_id"):
        parent = await ctx.get("work_orders", data["parent_id"])
        if parent.get("parent_id"):
            raise HTTPException(422, "Une étape ne peut pas avoir elle-même d'étapes")
        for k in ("event_id", "warehouse_id", "type"):
            data.setdefault(k, parent.get(k, ""))
            if not data[k]:
                data[k] = parent.get(k, "")
    await _check_refs(ctx, data)
    _schedule(data)
    await _check_dependencies(ctx, None, data)
    data.update({"actual_minutes": 0, "cost_labor": 0.0, "cost_materials": 0.0, "created_by": ctx.member.get("name", ""),
                 "recurrence_id": data.get("recurrence_id", ""), "occurrence_date": data.get("occurrence_date", ""), "detached": False})
    return await ctx.insert("work_orders", data)


@router.post("/work-orders")
async def create_order(body: WorkIn, request: Request, ctx: Ctx = Depends(W)):
    w = await _create(ctx, body.model_dump())
    await audit(ctx.org_id, ctx.member, "work_order_created", w["title"])
    return _clean(ctx, request, w)


@router.patch("/work-orders/{wid}")
async def patch_order(wid: str, body: WorkPatch, request: Request, ctx: Ctx = Depends(W)):
    cur = await ctx.get("work_orders", wid)
    d = body.model_dump(exclude_unset=True)
    for k in ("items", "tools", "checklist"):
        if k in d and d[k] is not None:
            d[k] = [x if isinstance(x, dict) else x.model_dump() for x in d[k]]
    if "scheduled_start" in d and not d["scheduled_start"]:
        d["scheduled_end"] = ""
    await _check_refs(ctx, {**cur, **d})
    _schedule(d, cur)
    await _check_dependencies(ctx, wid, {**cur, **d})
    if cur.get("recurrence_id") and ({"scheduled_start", "scheduled_end", "assignee_ids", "status"} & d.keys()):
        d["detached"] = True  # occurrence modifiée à la main : la récurrence ne la régénère plus
    if d.get("status") == "fait" and cur.get("status") != "fait":
        d["done_at"] = now_iso()
    w = await ctx.update("work_orders", wid, d)
    return _clean(ctx, request, w)


@router.delete("/work-orders/{wid}")
async def delete_order(wid: str, ctx: Ctx = Depends(W)):
    w = await ctx.get("work_orders", wid)
    for s in await ctx.list("work_orders", {"parent_id": wid}):
        await ctx.delete("work_orders", s["id"])
    await ctx.delete("work_orders", wid)
    await audit(ctx.org_id, ctx.member, "work_order_deleted", w["title"])
    return {"ok": True}


@router.post("/tasks/{tid}/to-work-order")
async def from_task(tid: str, request: Request, ctx: Ctx = Depends(W)):
    """Transformer une tâche de la To-do en travail planifiable."""
    t = await ctx.get("tasks", tid)
    team = {m["user_id"]: m["id"] for m in await ctx.list("team", {"user_id": {"$ne": None}})}
    w = await _create(ctx, {**WorkIn(title=t["title"]).model_dump(), "description": t.get("description", ""),
                            "deadline": (t.get("due_at") or "")[:10], "event_id": t.get("event_id", ""),
                            "priority": {"low": "basse", "high": "haute", "urgent": "urgente"}.get(t.get("priority"), "normale"),
                            "checklist": [{"label": c.get("label") or c.get("text") or "", "done": bool(c.get("done"))} for c in t.get("checklist") or [] if c.get("label") or c.get("text")],
                            "assignee_ids": [team[u] for u in t.get("assignee_ids") or [] if u in team], "attachments": t.get("attachments") or []})
    await db.tasks.update_one(ctx.q({"id": tid}), {"$set": {"work_order_id": w["id"], "status": "done"}})
    return _clean(ctx, request, w)


# --------------------------------------------------------------------------------------
# Modèles
# --------------------------------------------------------------------------------------
@router.get("/work-templates")
async def list_templates(ctx: Ctx = Depends(R)):
    return await ctx.list("work_templates", sort=[("title", 1)])


@router.post("/work-templates")
async def create_template(body: TemplateIn, ctx: Ctx = Depends(W)):
    d = body.model_dump()
    await _check_refs(ctx, d)
    return await ctx.insert("work_templates", d)


@router.put("/work-templates/{tid}")
async def update_template(tid: str, body: TemplateIn, ctx: Ctx = Depends(W)):
    d = body.model_dump()
    await _check_refs(ctx, d)
    return await ctx.update("work_templates", tid, d)


@router.delete("/work-templates/{tid}")
async def delete_template(tid: str, ctx: Ctx = Depends(W)):
    if await db.work_recurrences.count_documents(ctx.q({"template_id": tid, "active": True})):
        raise HTTPException(409, "Ce modèle sert à une tâche récurrente active : désactivez-la d'abord")
    await ctx.delete("work_templates", tid)
    return {"ok": True}


# --------------------------------------------------------------------------------------
# Récurrence
# --------------------------------------------------------------------------------------
HORIZON_DAYS = 56  # 8 semaines


def occurrences(rec: dict, frm: date, to: date) -> list[date]:
    start = date.fromisoformat(rec["start"])
    end = min(to, date.fromisoformat(rec["end"])) if rec.get("end") else to
    out, n = [], rec.get("interval") or 1
    if rec["freq"] == "weekly":
        monday = start - timedelta(days=start.weekday())
        d = max(start, frm)
        while d <= end:
            if d.weekday() in (rec.get("weekdays") or [0]) and ((d - monday).days // 7) % n == 0:
                out.append(d)
            d += timedelta(days=1)
    else:  # monthly / months : le jour monthday, tous les `interval` mois
        y, m, k = start.year, start.month, 0
        while True:
            d = date(y, m, rec.get("monthday") or 1)
            if d > end:
                break
            if d >= max(start, frm) and k % n == 0:
                out.append(d)
            k += 1
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


async def generate(ctx: Ctx, rec: dict, horizon_days: int = HORIZON_DAYS) -> int:
    """Crée les occurrences manquantes sur l'horizon ; ne touche jamais une occurrence modifiée à la main."""
    if not rec.get("active", True):
        return 0
    tpl = await db.work_templates.find_one(ctx.q({"id": rec["template_id"]}), {"_id": 0})
    if not tpl:
        return 0
    today = date.today()
    existing = set(await db.work_orders.distinct("occurrence_date", ctx.q({"recurrence_id": rec["id"]})))
    n = 0
    for d in occurrences(rec, today, today + timedelta(days=horizon_days)):
        day = d.isoformat()
        if day in existing:
            continue
        start = f"{day}T{rec.get('start_time') or '08:00'}"
        end = f"{day}T{rec['end_time']}" if rec.get("end_time") else ""
        await _create(ctx, {**WorkIn(title=tpl["title"]).model_dump(), "template_id": tpl["id"], "scheduled_start": start, "scheduled_end": end,
                            "assignee_ids": rec.get("default_assignee_ids") or [], "recurrence_id": rec["id"], "occurrence_date": day})
        n += 1
    return n


@router.get("/work-recurrences")
async def list_recurrences(ctx: Ctx = Depends(R)):
    return await ctx.list("work_recurrences", sort=[("created_at", 1)])


@router.post("/work-recurrences")
async def create_recurrence(body: RecurrenceIn, ctx: Ctx = Depends(W)):
    await ctx.get("work_templates", body.template_id)
    rec = await ctx.insert("work_recurrences", body.model_dump())
    rec["generated"] = await generate(ctx, rec)
    return rec


@router.put("/work-recurrences/{rid}")
async def update_recurrence(rid: str, body: RecurrenceIn, ctx: Ctx = Depends(W)):
    rec = await ctx.update("work_recurrences", rid, body.model_dump())
    # Les occurrences futures non modifiées à la main sont recréées selon la nouvelle règle
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    for w in await ctx.list("work_orders", {"recurrence_id": rid, "detached": False, "status": "planifie", "scheduled_start": {"$gt": now}}):
        await ctx.delete("work_orders", w["id"])
    rec["generated"] = await generate(ctx, rec)
    return rec


@router.delete("/work-recurrences/{rid}")
async def delete_recurrence(rid: str, ctx: Ctx = Depends(W)):
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    for w in await ctx.list("work_orders", {"recurrence_id": rid, "detached": False, "status": "planifie", "scheduled_start": {"$gt": now}}):
        await ctx.delete("work_orders", w["id"])
    await db.work_recurrences.delete_one(ctx.q({"id": rid}))
    return {"ok": True}


async def tick() -> None:
    """Tâche planifiée quotidienne (une passe par société) : prolonge les récurrences sur l'horizon."""
    orgs = await db.orgs.find({}, {"_id": 0, "id": 1}).to_list(10000)
    for o in orgs:
        ctx = Ctx({"org_id": o["id"], "role": "gerant", "name": "Récurrence"})
        for rec in await ctx.list("work_recurrences", {"active": True}):
            await generate(ctx, rec)
