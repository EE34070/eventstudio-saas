import re
from datetime import date, datetime, timedelta
from typing import Literal, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from core import Ctx, db, need, new_id, now_iso
from routes_billing import loading_alerts
from routes_main import OnsiteContact, VenueIn, _venue, contact_name, module_catalog, onsite_for

from routes_units import Qty, check_whole, num, to_pieces  # noqa: E402

router = APIRouter(prefix="/api")

STATUSES = ["demande", "devis_envoye", "confirme", "en_preparation", "realise", "facture", "cloture"]
STATUS_LABEL = {"demande": "Demande", "devis_envoye": "Devis envoyé", "confirme": "Confirmé",
                "en_preparation": "En préparation", "realise": "Réalisé", "facture": "Facturé", "cloture": "Clôturé"}
HOLD = ["confirme", "en_preparation", "realise"]
CONFIRMED = ["confirme", "en_preparation", "realise", "facture", "cloture"]
VAT = 0.20


# ---------- Equipment ----------
class EquipmentIn(BaseModel):
    ref: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = "Sonorisation"
    photo: str = ""
    description: str = Field("", max_length=2000)
    name_en: str = Field("", max_length=300)
    description_en: str = Field("", max_length=2000)
    qty_total: Qty = Field(ge=0)
    price_day: Optional[float] = Field(0, ge=0)
    movable_during_event: bool = True
    subcategory: str = Field("", max_length=120)
    product_type: str = Field("Location", max_length=40)
    provenance: str = Field("", max_length=60)
    replacement_value: float = Field(0, ge=0)
    weight_kg: float = 0
    volume_m3: float = 0
    state: str = "bon"
    notes: str = ""
    prep_days_before: int = Field(0, ge=0, le=30)
    return_days_after: int = Field(0, ge=0, le=30)


class MaintenanceIn(BaseModel):
    action: str = "start"
    qty: int = Field(1, ge=1)
    note: str = ""


def _now_local() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


async def load_world(ctx: Ctx):
    evs = await ctx.list("events", {"status": {"$ne": "cloture"}}, limit=5000)
    eqs = {e["id"]: e for e in await ctx.list("equipment")}
    return evs, eqs


def holds(ev: dict) -> bool:
    return ev["status"] in HOLD and not ev.get("material_returned")


def period(ev: dict) -> tuple:
    return ev.get("rental_start") or ev.get("setup_start") or ev["start"], ev.get("rental_end") or ev.get("return_end") or ev["end"]


def usage(evs: list, s: str, e: str, exclude: str | None = None):
    used, by = {}, {}
    for o in evs:
        ps, pe = period(o)
        if o["id"] == exclude or not holds(o) or not (ps < e and pe > s):
            continue
        for l in o.get("equipment", []) + (o.get("auto_equipment") or []):
            used[l["equipment_id"]] = used.get(l["equipment_id"], 0) + l["qty"]
            by.setdefault(l["equipment_id"], []).append({"id": o["id"], "code": o["code"], "title": o["title"], "qty": l["qty"],
                                                          "start": ps, "end": pe})
    return used, by


def compute_conflicts(ev: dict, evs: list, eqs: dict) -> list:
    if not ev.get("equipment"):
        return []
    used, by = usage(evs, *period(ev), ev["id"])
    out = []
    for l in ev["equipment"]:
        eq = eqs.get(l["equipment_id"])
        if not eq:
            continue
        avail = eq["qty_total"] - eq.get("qty_maintenance", 0) - used.get(eq["id"], 0)
        if l["qty"] > avail:
            out.append({"equipment_id": eq["id"], "ref": eq["ref"], "name": eq["name"], "requested": l["qty"],
                        "available": max(0, avail), "missing": l["qty"] - max(0, avail), "events": by.get(eq["id"], [])})
    return out


@router.get("/equipment")
async def list_equipment(ctx: Ctx = Depends(need("catalog:read")), start: str = "", end: str = ""):
    s = start or _now_local()
    e = end or (datetime.strptime(s[:16], "%Y-%m-%dT%H:%M") + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    if e <= s:
        raise HTTPException(400, "La fin de période doit être après le début")
    evs, eqs = await load_world(ctx)
    used, by = usage(evs, s, e)
    rows = sorted(eqs.values(), key=lambda x: (x.get("category", ""), x["ref"]))
    for r in rows:
        r["qty_maintenance"] = r.get("qty_maintenance", 0)
        r["reserved"] = used.get(r["id"], 0)
        r["reserved"] = num(r["reserved"])
        r["available"] = num(r["qty_total"] - r["qty_maintenance"] - r["reserved"])
        r["bookings"] = by.get(r["id"], [])
        if not ctx.can("finance:read"):
            r.pop("replacement_value", None)
    return {"start": s, "end": e, "items": rows}


@router.get("/equipment/{eid}/bookings")
async def equipment_bookings(eid: str, ctx: Ctx = Depends(need("catalog:read"))):
    eq = await ctx.get("equipment", eid)
    evs = await ctx.list("events", {"equipment.equipment_id": eid, "status": {"$ne": "cloture"}}, sort=[("setup_start", 1)])
    eq["bookings"] = [{"id": e["id"], "code": e["code"], "title": e["title"], "status": e["status"], "start": period(e)[0],
                       "end": period(e)[1], "qty": sum(l["qty"] for l in e["equipment"] if l["equipment_id"] == eid),
                       "holds": holds(e)} for e in evs]
    return eq


@router.post("/equipment")
async def create_equipment(body: EquipmentIn, ctx: Ctx = Depends(need("catalog:write"))):
    if await db.equipment.find_one(ctx.q({"ref": body.ref})):
        raise HTTPException(409, "Cette référence existe déjà")
    check_whole({}, body.qty_total)
    return await ctx.insert("equipment", {**body.model_dump(), "qty_maintenance": 0, "maintenance_log": []})


@router.put("/equipment/{eid}")
async def update_equipment(eid: str, body: EquipmentIn, ctx: Ctx = Depends(need("catalog:write"))):
    cur = await ctx.get("equipment", eid)
    if body.qty_total < cur.get("qty_maintenance", 0):
        raise HTTPException(400, "Quantité inférieure au matériel en maintenance")
    check_whole(cur, body.qty_total)
    from routes_stock import on_total_change
    await on_total_change(ctx, eid, cur.get("qty_total", 0), body.qty_total)
    return await ctx.update("equipment", eid, {**body.model_dump(exclude_unset=True), "to_complete": False})


class CatalogueImportIn(BaseModel):
    rows: list = Field(max_length=5000)
    apply: bool = False


@router.post("/catalogue-import")
async def catalogue_import_route(body: CatalogueImportIn, ctx: Ctx = Depends(need("catalog:write"))):
    import catalogue_import as ci
    from core import audit
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "slug": 1}) or {}
    if ctx.role != "admin" or ctx.preview:
        raise HTTPException(403, "Réservé aux administrateurs")
    if org.get("slug") not in (*ci.ALLOWED_SLUGS, "qa-sandbox"):
        raise HTTPException(403, "L'import du catalogue n'est pas ouvert pour cette société")
    rep = await ci.run(db, ctx.org_id, body.rows, body.apply, ctx.member.get("name") or "Import Odoo")
    if body.apply:
        await audit(ctx.org_id, ctx.member, "catalogue_import", "equipment", f"créés {rep['created']}, mis à jour {rep['updated']}, inchangés {rep['unchanged']}, refusés {len(rep['refused'])}")
    return rep


@router.delete("/equipment/{eid}")
async def delete_equipment(eid: str, ctx: Ctx = Depends(need("catalog:write"))):
    if await db.events.find_one(ctx.q({"equipment.equipment_id": eid, "status": {"$ne": "cloture"}})):
        raise HTTPException(400, "Matériel utilisé sur des événements en cours")
    await ctx.delete("equipment", eid)
    return {"ok": True}


@router.post("/equipment/{eid}/maintenance")
async def maintenance(eid: str, body: MaintenanceIn, ctx: Ctx = Depends(need("catalog:write"))):
    eq = await ctx.get("equipment", eid)
    cur = eq.get("qty_maintenance", 0)
    new = cur + body.qty if body.action == "start" else cur - body.qty
    if new < 0 or new > eq["qty_total"]:
        raise HTTPException(400, "Quantité invalide")
    entry = {"id": new_id(), "at": now_iso(), "action": body.action, "qty": body.qty, "note": body.note, "by": ctx.member.get("name")}
    await db.equipment.update_one(ctx.q({"id": eid}), {"$set": {"qty_maintenance": new, "state": "maintenance" if new else "bon"},
                                                         "$push": {"maintenance_log": entry}})
    return await ctx.get("equipment", eid)


# ---------- Catalogue packs ----------
class PackItem(BaseModel):
    equipment_id: str
    qty: int = Field(1, ge=1)


class PackIn(BaseModel):
    name: str = Field(min_length=1)
    module: str = "loueur_materiel"
    description: str = ""
    price: float = Field(0, ge=0)
    items: List[PackItem] = []
    services: List[str] = []
    options: List[str] = []
    active: bool = True


@router.get("/packs")
async def list_packs(ctx: Ctx = Depends(need("catalog:read"))):
    return await ctx.list("packs", sort=[("name", 1)])


@router.post("/packs")
async def create_pack(body: PackIn, ctx: Ctx = Depends(need("catalog:write"))):
    return await ctx.insert("packs", body.model_dump())


@router.put("/packs/{pid}")
async def update_pack(pid: str, body: PackIn, ctx: Ctx = Depends(need("catalog:write"))):
    return await ctx.update("packs", pid, body.model_dump())


@router.delete("/packs/{pid}")
async def delete_pack(pid: str, ctx: Ctx = Depends(need("catalog:write"))):
    await ctx.delete("packs", pid)
    return {"ok": True}


# ---------- Events ----------
class PrestationIn(BaseModel):
    id: str = ""
    module: str
    title: str
    price: float = 0
    cost: float = 0
    fields: dict = {}


class EquipLine(BaseModel):
    equipment_id: str
    qty: Qty = Field(1, gt=0)
    entered_qty: Optional[float] = Field(None, gt=0)
    entered_uom: Literal["", "stock", "secondary"] = ""
    price_day: Optional[float] = None
    state_out: str = ""
    state_in: str = ""
    qty_returned: int = 0
    section_id: str = ""


class TeamLine(BaseModel):
    member_id: str
    role: str = ""
    start: str = ""
    end: str = ""
    confirmed: bool = False


class PlanLine(BaseModel):
    date: str = ""
    time: str
    label: str


class RentalIn(BaseModel):
    deposit_amount: float = 0
    deposit_status: str = "non_demandee"
    out_at: str = ""
    return_at: str = ""
    out_checked_by: str = ""
    return_checked_by: str = ""
    notes: str = ""


class NewVenue(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(min_length=1, max_length=200)
    zip: str = Field(min_length=1, max_length=10)
    city: str = Field(min_length=1, max_length=80)
    lat: Optional[float] = None
    lng: Optional[float] = None
    contact_name: str = Field("", max_length=120)
    onsite_contacts: Optional[List[OnsiteContact]] = None
    contact_phone: str = Field("", max_length=40)
    contact_email: str = Field("", max_length=160)
    access_instructions: str = Field("", max_length=1000)


class EventIn(BaseModel):
    title: str = Field(min_length=1)
    type: str = "Mariage"
    client_id: str = ""
    venue_id: str = ""
    language: Optional[str] = Field(None, max_length=10)
    date_tbc: bool = False
    client_contact_ids: Optional[List[str]] = None
    signatory_contact_id: Optional[str] = None
    planner_contact_id: Optional[str] = None
    planner_person_id: Optional[str] = None
    planner_cc_person_ids: Optional[List[str]] = None
    main_contact_role: Optional[str] = None
    planner_commission_mode: Optional[str] = None
    planner_commission_value: Optional[float] = None
    planner_commission_status: Optional[str] = None
    onsite_contact_ids: Optional[List[str]] = Field(None, max_length=12)
    start: str
    end: str
    setup_start: str = ""
    return_end: str = ""
    guests: int = 0
    budget: float = 0
    chef_projet_id: str = ""
    notes: str = ""
    delivery_venue_id: str = ""
    delivery_same_as_venue: bool = True
    budget_tax_mode: str = "ttc"
    modules: Optional[List[str]] = None
    module_budgets: Optional[Dict[str, float]] = None
    new_venue: Optional[NewVenue] = None
    new_delivery_venue: Optional[NewVenue] = None


class EventPatch(BaseModel):
    delivery_venue_id: Optional[str] = None
    delivery_same_as_venue: Optional[bool] = None
    budget_tax_mode: Optional[str] = None
    modules: Optional[List[str]] = None
    module_budgets: Optional[Dict[str, float]] = None
    new_venue: Optional[NewVenue] = None
    new_delivery_venue: Optional[NewVenue] = None
    title: Optional[str] = None
    type: Optional[str] = None
    language: Optional[str] = Field(None, max_length=10)
    client_id: Optional[str] = None
    client_contact_ids: Optional[List[str]] = None
    signatory_contact_id: Optional[str] = None
    planner_contact_id: Optional[str] = None
    planner_person_id: Optional[str] = None
    planner_cc_person_ids: Optional[List[str]] = None
    main_contact_role: Optional[str] = None
    planner_commission_mode: Optional[str] = None
    planner_commission_value: Optional[float] = None
    planner_commission_status: Optional[str] = None
    onsite_contact_ids: Optional[List[str]] = Field(None, max_length=12)
    venue_id: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    setup_start: Optional[str] = None
    return_end: Optional[str] = None
    guests: Optional[int] = None
    budget: Optional[float] = None
    chef_projet_id: Optional[str] = None
    notes: Optional[str] = None
    prestations: Optional[List[PrestationIn]] = None
    equipment: Optional[List[EquipLine]] = None
    team: Optional[List[TeamLine]] = None
    planning: Optional[List[PlanLine]] = None
    rental: Optional[RentalIn] = None
    material_returned: Optional[bool] = None
    deposit_paid: Optional[float] = None
    invoice_paid: Optional[bool] = None
    extra_costs: Optional[float] = None
    rental_start: Optional[str] = None
    rental_end: Optional[str] = None


FINANCE_FIELDS = {"deposit_paid", "invoice_paid", "extra_costs"}
SECTION_LABELS = {"prestations": "Prestations", "equipment": "Matériel", "team": "Équipe", "planning": "Planning",
                  "rental": "Location / caution", "material_returned": "Retour matériel", "deposit_paid": "Acompte",
                  "invoice_paid": "Facture soldée", "extra_costs": "Coûts", "rental_start": "Période de location", "rental_end": "Période de location"}


def _d(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def normalize(ev: dict, eqs: dict) -> dict:
    for k in ("start", "end"):
        try:
            datetime.strptime(ev[k][:16], "%Y-%m-%dT%H:%M")
        except (ValueError, TypeError):
            raise HTTPException(400, "Format de date invalide (AAAA-MM-JJTHH:MM)")
    ev["setup_start"] = ev.get("setup_start") or ev["start"]
    ev["return_end"] = ev.get("return_end") or ev["end"]
    if not (ev["setup_start"] <= ev["start"] < ev["end"] <= ev["return_end"]):
        raise HTTPException(400, "Dates incohérentes : montage ≤ début < fin ≤ retour")
    rs, re_ = ev.get("rental_start") or "", ev.get("rental_end") or ""
    if rs or re_:
        try:
            for x in (rs, re_):
                datetime.strptime(x[:16], "%Y-%m-%dT%H:%M")
        except (ValueError, TypeError):
            raise HTTPException(400, "Période de location : indiquez un début et une fin valides")
        if rs >= re_:
            raise HTTPException(400, "La fin de location doit être après le début")
    days = max(1, (_d(re_) - _d(rs)).days) if rs else max(1, (_d(ev["end"]) - _d(ev["start"])).days)
    for l in ev.get("equipment", []):
        eq = eqs.get(l["equipment_id"]) or {}
        if l.get("entered_uom") == "secondary" and eq.get("qty_per_piece") and l.get("entered_qty"):
            l["qty"] = to_pieces(eq, l["entered_qty"], "secondary")
        else:
            l["entered_uom"], l["entered_qty"] = "", None
        check_whole(eq, l["qty"])
        if l.get("price_day") is None:
            l["price_day"] = eqs.get(l["equipment_id"], {}).get("price_day", 0)
    eq_total = sum(l["qty"] * (l["price_day"] or 0) * days for l in ev.get("equipment", []))
    pr_total = sum(p.get("price", 0) for p in ev.get("prestations", []))
    ev["rental_days"] = days
    ev["amount_equipment"] = round(eq_total, 2)
    ev["amount_services"] = round(pr_total, 2)
    ev["amount_ht"] = round(eq_total + pr_total, 2)
    ev["amount_ttc"] = round(ev["amount_ht"] * (1 + VAT), 2)
    ev["costs_total"] = round(sum(p.get("cost", 0) for p in ev.get("prestations", [])) + (ev.get("extra_costs") or 0), 2)
    if ev.get("quote_ht") is not None:
        ev["amount_ht"], ev["amount_ttc"] = ev["quote_ht"], ev.get("quote_ttc") or 0
    return ev


def guard(ev: dict, evs: list, eqs: dict):
    """Règle « ne jamais bloquer » : les manques sont listés dans la logistique de l'événement (routes_shortages)."""
    return


COMMISSION = ("planner_commission_mode", "planner_commission_value", "planner_commission_status")
PEOPLE_DEFAULTS = {"planner_contact_id": None, "main_contact_role": "client", "planner_commission_mode": "none", "planner_commission_value": 0, "planner_commission_status": "due"}


async def organizer_keys(org_id: str) -> list:
    return [c["key"] async for c in db.provider_categories.find({"org_id": org_id, "is_organizer": True}, {"_id": 0, "key": 1})]


async def _people(ctx: Ctx, data: dict, base: dict, creating: bool) -> None:
    for k in COMMISSION + ("main_contact_role", "client_contact_ids", "signatory_contact_id"):
        if data.get(k) is None or (k in COMMISSION and not ctx.can("finance:read")):
            data.pop(k, None)
    if creating or {"client_id", "client_contact_ids", "signatory_contact_id"} & set(data):
        ids = data["client_contact_ids"] if "client_contact_ids" in data else [data.get("signatory_contact_id") or data.get("client_id") or ""] if {"client_id", "signatory_contact_id"} & set(data) else base.get("client_contact_ids", [])
        ids = list(dict.fromkeys(i for i in ids if i))[:6]
        for i in ids:
            await ctx.get("contacts", i)
        sig = next((x for x in (data.get("signatory_contact_id"), base.get("signatory_contact_id")) if x in ids), ids[0] if ids else "")
        data.update(client_contact_ids=ids, signatory_contact_id=sig, client_id=sig)
    if "planner_contact_id" in data:
        data["planner_contact_id"] = data["planner_contact_id"] or None
        if data["planner_contact_id"] and not await db.provider_profiles.find_one(ctx.q({"contact_id": data["planner_contact_id"], "categories": {"$in": await organizer_keys(ctx.org_id)}})):
            raise HTTPException(400, "Ce contact n'est pas un prestataire organisateur")
    planner = data.get("planner_contact_id", base.get("planner_contact_id"))
    if creating or {"planner_contact_id", "main_contact_role"} & set(data):
        role = data.get("main_contact_role")
        if role not in ("client", "planner"):
            role = "planner" if planner != base.get("planner_contact_id") else base.get("main_contact_role", "client")
        data["main_contact_role"] = role if planner else "client"
    if data.get("planner_commission_mode", "none") not in ("none", "percent", "fixed") or data.get("planner_commission_status", "due") not in ("due", "paid"):
        raise HTTPException(400, "Commission invalide")
    mode, value = data.get("planner_commission_mode", base.get("planner_commission_mode", "none")), data.get("planner_commission_value", base.get("planner_commission_value", 0))
    if value < 0 or (mode == "percent" and value > 100):
        raise HTTPException(400, "Commission invalide")
    if "planner_person_id" in data or "planner_cc_person_ids" in data:
        import contact_people as cp
        data["planner_person_id"] = data.get("planner_person_id") or None
        await cp.check(ctx, planner, [data["planner_person_id"]] + (data.get("planner_cc_person_ids") or []), base, data["planner_person_id"])
    if not planner and "planner_contact_id" in data:
        data.update(planner_commission_mode="none", planner_commission_value=0)
    if creating:
        for k, v in PEOPLE_DEFAULTS.items():
            data.setdefault(k, v)


def sanitize(ev: dict, ctx: Ctx) -> dict:
    if not ctx.can("finance:read"):
        for k in ("amount_ht", "amount_ttc", "amount_equipment", "amount_services", "budget", "deposit_paid",
                  "invoice_paid", "extra_costs", "costs_total", *COMMISSION):
            ev.pop(k, None)
        for p in ev.get("prestations", []):
            p.pop("price", None)
            p.pop("cost", None)
        for l in ev.get("equipment", []):
            l.pop("price_day", None)
        if ev.get("rental"):
            ev["rental"].pop("deposit_amount", None)
        for m in ev.get("modules", []):
            if isinstance(m, dict):
                m.pop("budget_amount", None)
    return ev


def hist(ctx: Ctx, action: str, detail: str = "") -> dict:
    return {"at": now_iso(), "by": ctx.member.get("name"), "action": action, "detail": detail}


async def _names(ctx: Ctx):
    contacts = {c["id"]: c for c in await ctx.list("contacts")} if ctx.can("contacts:read") else {}
    venues = {v["id"]: v for v in await ctx.list("venues")}
    team = {t["id"]: t for t in await ctx.list("team")}
    return contacts, venues, team


def summary(ev: dict, contacts, venues, team, conflicts) -> dict:
    v = venues.get(ev.get("venue_id")) or {}
    c = contacts.get(ev.get("client_id"))
    out = {k: ev.get(k) for k in ("id", "code", "title", "type", "status", "start", "end", "setup_start", "return_end",
                                  "guests", "amount_ht", "amount_ttc", "deposit_paid", "invoice_paid", "material_returned",
                                  "client_id", "venue_id", "vehicle_id", "chef_projet_id", "planner_contact_id", "created_at", "date_tbc", "language")}
    out["planner_name"] = contact_name(contacts[ev["planner_contact_id"]]) if ev.get("planner_contact_id") in contacts else ""
    out.update({"client_name": contact_name(c) if c else "", "venue_name": v.get("name", ""), "venue_city": v.get("city", ""),
                "chef_projet_name": (team.get(ev.get("chef_projet_id")) or {}).get("name", ""),
                "modules": sorted({p["module"] for p in ev.get("prestations", [])}),
                "equipment_count": sum(l["qty"] for l in ev.get("equipment", [])),
                "team": [{"member_id": t["member_id"], "name": (team.get(t["member_id"]) or {}).get("name", "?"),
                          "color": (team.get(t["member_id"]) or {}).get("color", "#999"), "role": t.get("role", "")}
                         for t in ev.get("team", [])],
                "conflicts_count": len(conflicts)})
    return out


@router.get("/events")
async def list_events(ctx: Ctx = Depends(need("events:read")), status: str = "", q: str = "",
                      date_from: str = "", date_to: str = "", module: str = "", planner: str = ""):
    f = dict(ctx.event_scope())
    if planner:
        f["planner_contact_id"] = planner
    if status:
        f["status"] = status
    if module:
        f["prestations.module"] = module
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        f["$or"] = [{"title": rx}, {"code": rx}, {"type": rx}]
    if date_from or date_to:
        f["date_tbc"] = {"$ne": True}
    if date_from:
        f["return_end"] = {"$gte": date_from}
    if date_to:
        f["setup_start"] = {"$lte": date_to}
    rows = await ctx.list("events", f, sort=[("start", 1)])
    evs, eqs = await load_world(ctx)
    contacts, venues, team = await _names(ctx)
    cnt = await __import__("routes_shortages").counts(ctx.org_id)
    return [{**x, "shortages_count": cnt.get(x["id"], 0)} for x in [sanitize(summary(e, contacts, venues, team, compute_conflicts(e, evs, eqs) if e["status"] != "cloture" else []), ctx)
            for e in rows]]


async def _detail(ctx: Ctx, eid: str) -> dict:
    ev = await ctx.get("events", eid, ctx.event_scope())
    evs, eqs = await load_world(ctx)
    contacts, venues, team = await _names(ctx)
    ev["conflicts"] = compute_conflicts(ev, evs, eqs) if ev["status"] != "cloture" else []
    ev["shortages_count"] = (await __import__("routes_shortages").counts(ctx.org_id)).get(eid, 0)
    ev["client"] = contacts.get(ev.get("client_id"))
    if ev["client"]:
        ev["client"]["display_name"] = contact_name(ev["client"])
    ev["clients"] = [{**contacts[i], "display_name": contact_name(contacts[i]), "is_signatory": i == ev.get("client_id")}
                     for i in (ev.get("client_contact_ids") or [ev.get("client_id")]) if i in contacts]
    pl = contacts.get(ev.get("planner_contact_id"))
    prof = await db.provider_profiles.find_one(ctx.q({"contact_id": pl["id"]}), {"_id": 0, "id": 1, "categories": 1}) if pl else None
    types = [c["label"] async for c in db.provider_categories.find(ctx.q({"is_organizer": True, "key": {"$in": (prof or {}).get("categories", [])}}), {"_id": 0}).sort("order", 1)]
    ev["planner"] = {**pl, "display_name": contact_name(pl), "provider_id": (prof or {}).get("id"), "types": types} if pl else None
    if pl:
        import contact_people as cp
        ev["planner"].update(await cp.for_event(ctx.org_id, pl["id"], ev))
    ev["onsite_selected"] = [c["id"] for c in onsite_for(venues.get(ev.get("venue_id")), ev.get("onsite_contact_ids"))]
    ev["main_contact_role"] = ev.get("main_contact_role") if pl else "client"
    ev["venue"] = venues.get(ev.get("venue_id"))
    ev["chef_projet_name"] = (team.get(ev.get("chef_projet_id")) or {}).get("name", "")
    for l in ev.get("equipment", []):
        eq = eqs.get(l["equipment_id"]) or {}
        l.update({"ref": eq.get("ref", "?"), "name": eq.get("name", "Matériel supprimé"), "category": eq.get("category", ""),
                  "weight_kg": eq.get("weight_kg", 0)})
    for t in ev.get("team", []):
        m = team.get(t["member_id"]) or {}
        t.update({"name": m.get("name", "?"), "job": m.get("job", ""), "color": m.get("color", "#999")})
    ev["history"] = list(reversed(ev.get("history", [])))
    ev["can_close"] = bool(ev.get("material_returned") and ev.get("invoice_paid"))
    ev["invoices_count"] = await db.invoices.count_documents(ctx.q({"event_id": eid}))
    defs = await db.module_defs.find({}, {"_id": 0}).sort("order", 1).to_list(100)
    rows = {m["module_key"]: m for m in await ctx.list("event_modules", {"event_id": eid, "status": "actif"})}
    keys = set(rows) or {p.get("module") for p in ev.get("prestations", [])}
    ev["modules"] = [{"module_key": d["key"], "label": d["label"], "budget_amount": rows.get(d["key"], {}).get("budget_amount", 0),
                      "status": "actif"} for d in defs if d["key"] in keys]
    ev["delivery_venue"] = None if ev.get("delivery_same_as_venue", True) else venues.get(ev.get("delivery_venue_id"))
    return sanitize(ev, ctx)


@router.get("/events/overlaps")
async def event_overlaps(start: str, end: str, exclude: str = "", venue_id: str = "", ctx: Ctx = Depends(need("events:write"))):
    if len(start) < 16 or end <= start:
        return []
    rows = await ctx.list("events", {"status": {"$ne": "cloture"}, "setup_start": {"$lt": end}, "return_end": {"$gt": start}},
                          sort=[("start", 1)], limit=50)
    venues = {v["id"]: v for v in await ctx.list("venues")}
    return [{"id": e["id"], "code": e["code"], "title": e["title"], "status": e["status"], "start": e["start"], "end": e["end"],
             "venue_name": (venues.get(e.get("venue_id")) or {}).get("name", ""),
             "same_venue": bool(venue_id) and e.get("venue_id") == venue_id,
             "equipment_count": sum(l["qty"] for l in e.get("equipment", []))} for e in rows if e["id"] != exclude]


@router.get("/events/{eid}")
async def get_event(eid: str, ctx: Ctx = Depends(need("events:read"))):
    return await _detail(ctx, eid)


async def _next_code(ctx: Ctx, start: str) -> str:
    year = start[:4]
    r = await db.counters.find_one_and_update({"org_id": ctx.org_id, "key": f"event-{year}"}, {"$inc": {"seq": 1}},
                                              upsert=True, return_document=ReturnDocument.AFTER)
    return f"EVT-{year}-{r['seq']:03d}"


async def _check_refs(ctx: Ctx, data: dict):
    for key, coll in (("client_id", "contacts"), ("venue_id", "venues"), ("delivery_venue_id", "venues"), ("chef_projet_id", "team")):
        if data.get(key):
            await ctx.get(coll, data[key])


async def _prepare(ctx: Ctx, data: dict, base: dict, creating: bool) -> tuple:
    mods, budgets = data.pop("modules", None), data.pop("module_budgets", None)
    nv = {k: data.pop(k, None) for k in ("new_venue", "new_delivery_venue")}
    if any(nv.values()) and not ctx.can("venues:write"):
        raise HTTPException(403, "Action non autorisée pour votre rôle")
    if data.get("budget_tax_mode") not in (None, "ht", "ttc"):
        raise HTTPException(400, "Mode de budget inconnu (HT ou TTC)")
    if budgets is not None and (not ctx.can("finance:read") or mods is None):
        budgets = None
    if budgets and any(v < 0 for v in budgets.values()):
        raise HTTPException(400, "Un budget ne peut pas être négatif")
    if mods is not None:
        mods = list(dict.fromkeys(mods))
        if creating and not mods:
            raise HTTPException(400, "Sélectionnez au moins un module")
        allowed = {m["key"] for m in await module_catalog(ctx.org_id)} | {m["module_key"] for m in await ctx.list("event_modules", {"event_id": base.get("id", "-")})}
        if set(mods) - allowed:
            raise HTTPException(400, "Module inconnu ou non activé pour votre société")
        if "loueur_materiel" in mods:
            m = {**base, **data}
            same = m.get("delivery_same_as_venue", True)
            cand = nv["new_venue" if same else "new_delivery_venue"]
            vid = m.get("venue_id") if same else m.get("delivery_venue_id")
            if not cand and vid and not ((same and nv["new_venue"]) or (not same and nv["new_delivery_venue"])):
                cand = await db.venues.find_one(ctx.q({"id": vid}), {"_id": 0})
            if not cand or not all((cand.get(k) or "").strip() for k in ("address", "zip", "city")):
                raise HTTPException(400, "Location de matériel : un lieu de livraison complet (adresse, code postal, ville) est obligatoire")
    return mods, budgets, nv


async def _make_venues(ctx: Ctx, data: dict, nv: dict) -> None:
    for src, dst in (("new_venue", "venue_id"), ("new_delivery_venue", "delivery_venue_id")):
        v = nv.get(src)
        if not v or (src == "new_delivery_venue" and data.get("delivery_same_as_venue")):
            continue
        dup = await db.venues.find_one(ctx.q({"name": {"$regex": f"^{re.escape(v['name'].strip())}$", "$options": "i"}, "zip": v["zip"].strip()}), {"_id": 0})
        clean = {k: x.strip() if isinstance(x, str) else x for k, x in v.items()}
        data[dst] = (dup or await ctx.insert("venues", _venue(VenueIn(**clean))))["id"]
    if data.get("delivery_same_as_venue"):
        data["delivery_venue_id"] = ""


async def _sync_modules(ctx: Ctx, eid: str, keys: list, budgets: dict | None) -> None:
    cur = {m["module_key"]: m for m in await ctx.list("event_modules", {"event_id": eid})}
    for k in keys:
        upd = {"status": "actif", **({"budget_amount": round(float(budgets.get(k, 0)), 2)} if budgets is not None else {})}
        if k in cur:
            await db.event_modules.update_one(ctx.q({"id": cur[k]["id"]}), {"$set": upd})
        else:
            await ctx.insert("event_modules", {"event_id": eid, "module_key": k, "budget_amount": 0, **upd})
    for k in set(cur) - set(keys):
        await db.event_modules.update_one(ctx.q({"id": cur[k]["id"]}), {"$set": {"status": "retire"}})


@router.post("/events")
async def create_event(body: EventIn, ctx: Ctx = Depends(need("events:write"))):
    data = body.model_dump()
    mods, budgets, nv = await _prepare(ctx, data, {}, True)
    await _people(ctx, data, {}, True)
    sig = await db.contacts.find_one(ctx.q({"id": data.get("client_id")}), {"_id": 0, "language": 1}) if data.get("client_id") else None
    data["language"] = data.get("language") or (sig or {}).get("language") or "fr-FR"
    await _check_refs(ctx, data)
    evs, eqs = await load_world(ctx)
    normalize({**data, "equipment": [], "prestations": []}, eqs)
    await _make_venues(ctx, data, nv)
    ev = normalize({**data, "status": "demande", "prestations": [], "equipment": [], "team": [], "planning": [],
                    "rental": RentalIn().model_dump(), "material_returned": False, "deposit_paid": 0,
                    "invoice_paid": False, "extra_costs": 0}, eqs)
    ev["code"] = await _next_code(ctx, now_iso() if ev.get("date_tbc") else ev["start"])
    ev["history"] = [hist(ctx, "Création", f"Événement créé ({ev['code']})")]
    doc = await ctx.insert("events", ev)
    if mods is not None:
        await _sync_modules(ctx, doc["id"], mods, budgets)
    return {"id": doc["id"], "code": doc["code"]}


@router.patch("/events/{eid}")
async def patch_event(eid: str, body: EventPatch, ctx: Ctx = Depends(need("events:read"))):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(400, "Aucune modification")
    fin = set(changes) & FINANCE_FIELDS
    other = set(changes) - FINANCE_FIELDS
    if (fin and not ctx.can("finance:write")) or (other and not ctx.can("events:write")):
        raise HTTPException(403, "Action non autorisée pour votre rôle")
    ev = await ctx.get("events", eid, ctx.event_scope())
    if {"deposit_paid", "invoice_paid"} & set(changes) and await db.invoices.find_one(ctx.q({"event_id": eid})):
        raise HTTPException(400, "Acompte et solde sont calculés depuis les factures de cet événement")
    if ev.get("date_tbc") and changes.get("start") and changes["start"] != ev["start"]:
        changes["date_tbc"] = False
        await db.quotes.update_many(ctx.q({"event_id": eid, "event_date": ""}), {"$set": {"event_date": changes["start"][:10]}})
    mods, budgets, nv = await _prepare(ctx, changes, ev, False)
    await _people(ctx, changes, ev, False)
    await _check_refs(ctx, changes)
    for k in ("prestations",):
        if k in changes:
            for p in changes[k]:
                p["id"] = p.get("id") or new_id()
    if "team" in changes:
        team_ids = {t["id"] for t in await ctx.list("team")}
        if any(t["member_id"] not in team_ids for t in changes["team"]):
            raise HTTPException(404, "Membre introuvable")
    if "equipment" in changes:
        eq_ids = {e["id"] for e in await ctx.list("equipment")}
        if any(l["equipment_id"] not in eq_ids for l in changes["equipment"]):
            raise HTTPException(404, "Matériel introuvable")
        ids = [l["equipment_id"] for l in changes["equipment"]]
        if len(ids) != len(set(ids)):
            raise HTTPException(400, "Une référence ne peut apparaître qu'une fois")
    evs, eqs = await load_world(ctx)
    merged = normalize({**ev, **changes}, eqs)
    guard(merged, evs, eqs)
    import routes_stock
    touch = bool({"equipment", "venue_id", "delivery_venue_id", "delivery_same_as_venue", "start", "end", "setup_start", "return_end", "rental_start", "rental_end"} & set(changes))
    if touch:
        await routes_stock.check(ctx.org_id, merged)
    if any(nv.values()) or "delivery_same_as_venue" in changes:
        await _make_venues(ctx, changes, nv)
        merged.update(changes)
    if mods is not None:
        await _sync_modules(ctx, eid, mods, budgets)
    labels = [SECTION_LABELS.get(k, "Informations") for k in changes if merged.get(k) != ev.get(k)]
    if not labels:
        return await _detail(ctx, eid)
    h = hist(ctx, "Modification", ", ".join(sorted(set(labels))))
    fields = {k: merged[k] for k in list(changes) + ["setup_start", "return_end", "rental_days", "amount_equipment",
                                                     "amount_services", "amount_ht", "amount_ttc", "costs_total"]}
    if "equipment" in changes:
        fields["equipment"] = merged["equipment"]
    fields["updated_at"] = now_iso()
    await db.events.update_one(ctx.q({"id": eid}), {"$set": fields, "$push": {"history": {"$each": [h], "$slice": -300}}})
    if touch:
        await routes_stock.reallocate(ctx.org_id, eid)
        import routes_logistics
        if await db.logistics_missions.find_one(ctx.q({"event_id": eid})):
            await routes_logistics.generate(ctx.org_id, await ctx.get("events", eid), ctx.member.get("name"))
    out = await _detail(ctx, eid)
    if {"start", "end"} & set(changes):
        import routes_dj_conflicts
        out["dj_conflicts"] = await routes_dj_conflicts.on_event_moved(ctx.org_id, merged)
    return out


class StatusIn(BaseModel):
    status: str


@router.post("/events/{eid}/status")
async def set_status(eid: str, body: StatusIn, ctx: Ctx = Depends(need("events:read"))):
    if body.status not in STATUSES:
        raise HTTPException(400, "Statut inconnu")
    if not (ctx.can("events:write") or (ctx.can("finance:write") and body.status in ("facture", "cloture"))):
        raise HTTPException(403, "Action non autorisée pour votre rôle")
    ev = await ctx.get("events", eid, ctx.event_scope())
    if body.status == ev["status"]:
        return await _detail(ctx, eid)
    if body.status == "cloture":
        missing = []
        if not ev.get("material_returned"):
            missing.append("le matériel n'est pas retourné")
        if not ev.get("invoice_paid"):
            missing.append("la facture n'est pas soldée")
        if missing:
            raise HTTPException(400, "Clôture impossible : " + " et ".join(missing))
    evs, eqs = await load_world(ctx)
    guard({**ev, "status": body.status}, evs, eqs)
    import routes_stock
    if body.status in HOLD and ev["status"] not in HOLD:
        await routes_stock.check(ctx.org_id, {**ev, "status": body.status})
    h = hist(ctx, "Statut", f"{STATUS_LABEL[ev['status']]} → {STATUS_LABEL[body.status]}")
    await db.events.update_one(ctx.q({"id": eid}), {"$set": {"status": body.status, "updated_at": now_iso()},
                                                     "$push": {"history": h}})
    await routes_stock.reallocate(ctx.org_id, eid)
    return await _detail(ctx, eid)


class ShiftIn(BaseModel):
    days: int = Field(ge=-730, le=730)


def _shift(s: str, days: int) -> str:
    if not s:
        return s
    fmt = "%Y-%m-%dT%H:%M" if len(s) > 10 else "%Y-%m-%d"
    return (datetime.strptime(s[:16], fmt) + timedelta(days=days)).strftime(fmt)


@router.post("/events/{eid}/shift")
async def shift_event(eid: str, body: ShiftIn, ctx: Ctx = Depends(need("events:write"))):
    ev = await ctx.get("events", eid)
    if body.days == 0:
        return await _detail(ctx, eid)
    upd = {k: _shift(ev[k], body.days) for k in ("start", "end", "setup_start", "return_end")}
    upd.update({k: _shift(ev[k], body.days) for k in ("rental_start", "rental_end") if ev.get(k)})
    planning = [{**p, "date": _shift(p.get("date", ""), body.days)} for p in ev.get("planning", [])]
    team = [{**t, "start": _shift(t.get("start", ""), body.days), "end": _shift(t.get("end", ""), body.days)} for t in ev.get("team", [])]
    evs, eqs = await load_world(ctx)
    guard({**ev, **upd}, evs, eqs)
    import routes_stock
    await routes_stock.check(ctx.org_id, {**ev, **upd})
    h = hist(ctx, "Planning", f"Décalé de {body.days:+d} jour(s) : {ev['start'][:10]} → {upd['start'][:10]}")
    await db.events.update_one(ctx.q({"id": eid}), {"$set": {**upd, "planning": planning, "team": team, "updated_at": now_iso()},
                                                     "$push": {"history": h}})
    await routes_stock.reallocate(ctx.org_id, eid)
    return await _detail(ctx, eid)


@router.delete("/events/{eid}")
async def delete_event(eid: str, ctx: Ctx = Depends(need("events:delete"))):
    import trash
    await trash.soft_delete(ctx, "event", eid, {})
    await db.shortages.update_many(ctx.q({"event_id": eid, "status": {"$ne": "resolu"}}), {"$set": {"status": "resolu", "resolved_auto": True, "updated_at": now_iso()}})
    return {"ok": True}


# ---------- Dashboard / alerts / search ----------
def build_alerts(evs: list, eqs: dict, now: str) -> list:
    alerts = []
    soon = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M")
    for e in evs:
        if e["return_end"] < now:
            continue
        for c in compute_conflicts(e, evs, eqs):
            alerts.append({"type": "conflit", "severity": "danger" if holds(e) else "warning", "event_id": e["id"],
                           "title": f"Conflit matériel : {c['name']}",
                           "detail": f"{e['code']} · {e['title']} demande {c['requested']}, disponible {c['available']} (manque {c['missing']})."})
        if e["status"] in ("confirme", "en_preparation") and e["start"] <= soon and not e.get("team"):
            alerts.append({"type": "technicien", "severity": "warning", "event_id": e["id"],
                           "title": "Aucun technicien affecté",
                           "detail": f"{e['code']} · {e['title']} le {e['start'][8:10]}/{e['start'][5:7]} n'a pas d'équipe."})
    for eq in eqs.values():
        if eq.get("qty_maintenance"):
            last = (eq.get("maintenance_log") or [{}])[-1].get("note", "")
            alerts.append({"type": "maintenance", "severity": "warning", "equipment_id": eq["id"],
                           "title": f"En maintenance : {eq['name']}",
                           "detail": f"{eq['qty_maintenance']} / {eq['qty_total']} indisponible(s). {last}".strip()})
    order = {"danger": 0, "warning": 1}
    return sorted(alerts, key=lambda a: order[a["severity"]])


@router.get("/dashboard")
async def dashboard(ctx: Ctx = Depends(need("events:read"))):
    now = _now_local()
    scope = ctx.event_scope()
    rows = await ctx.list("events", scope, sort=[("start", 1)], limit=5000)
    evs, eqs = await load_world(ctx)
    contacts, venues, team = await _names(ctx)
    month = now[:7]
    in90 = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%dT%H:%M")
    upcoming = [summary(e, contacts, venues, team, compute_conflicts(e, evs, eqs))
                for e in rows if e["end"] >= now and e["status"] != "cloture"][:8]
    res = {"upcoming": [sanitize(u, ctx) for u in upcoming],
           "alerts": await loading_alerts(ctx) + build_alerts(evs, eqs, now) if not scope else []}
    if ctx.can("finance:read"):
        conf = [e for e in rows if e["status"] in CONFIRMED]
        devis = [e for e in rows if e["status"] == "devis_envoye"]
        unpaid = [e for e in rows if e["status"] == "facture" and not e.get("invoice_paid")]
        months = []
        base = datetime.now().replace(day=1)
        for i in range(-5, 7):
            y, m = base.year + (base.month - 1 + i) // 12, (base.month - 1 + i) % 12 + 1
            key = f"{y}-{m:02d}"
            months.append({"month": key, "ca": round(sum(e["amount_ht"] for e in conf if e["start"][:7] == key), 2),
                           "pipeline": round(sum(e["amount_ht"] for e in devis if e["start"][:7] == key), 2)})
        res["kpis"] = {
            "ca_month": round(sum(e["amount_ht"] for e in conf if e["start"][:7] == month), 2),
            "ca_month_count": len([e for e in conf if e["start"][:7] == month]),
            "ca_forecast": round(sum(e["amount_ht"] for e in conf if now <= e["start"] <= in90), 2),
            "ca_forecast_count": len([e for e in conf if now <= e["start"] <= in90]),
            "quotes_pending": len(devis), "quotes_pending_amount": round(sum(e["amount_ttc"] for e in devis), 2),
            "unpaid_count": len(unpaid),
            "unpaid_amount": round(sum(e["amount_ttc"] - (e.get("deposit_paid") or 0) for e in unpaid), 2),
        }
        res["months"] = months
    res["status_counts"] = {s: len([e for e in rows if e["status"] == s]) for s in STATUSES}
    return res


@router.get("/notifications")
async def notifications(ctx: Ctx = Depends(need("events:read"))):
    evs, eqs = await load_world(ctx)
    from routes_crm import alerts as crm_alerts
    alerts = await loading_alerts(ctx) + build_alerts(evs, eqs, _now_local()) + await crm_alerts(ctx) if not ctx.event_scope() else []
    if ctx.can("providers:manage"):
        from providers_core import alerts as provider_alerts
        alerts = await provider_alerts(ctx.org_id) + alerts
    alerts = await __import__("routes_shortages").bell(ctx) + alerts
    rows = await ctx.list("events", ctx.event_scope(), limit=5000)
    activity = []
    for e in rows:
        for h in e.get("history", [])[-5:]:
            activity.append({**h, "event_id": e["id"], "code": e["code"], "title": e["title"]})
    activity.sort(key=lambda x: x["at"], reverse=True)
    return {"alerts": alerts, "activity": activity[:12]}


@router.get("/search")
async def search(q: str = Query(min_length=2), ctx: Ctx = Depends(need("events:read"))):
    rx = {"$regex": re.escape(q), "$options": "i"}
    out = {"events": [], "contacts": [], "venues": [], "equipment": []}
    for e in await ctx.list("events", {**ctx.event_scope(), "$or": [{"title": rx}, {"code": rx}]}, limit=6):
        out["events"].append({"id": e["id"], "label": e["title"], "sub": f"{e['code']} · {e['start'][:10]}"})
    if ctx.can("contacts:read") and ctx.sees("contacts"):
        for c in await ctx.list("contacts", {"$or": [{"first_name": rx}, {"last_name": rx}, {"company": rx}, {"email": rx}]}, limit=6):
            out["contacts"].append({"id": c["id"], "label": contact_name(c), "sub": c.get("city", "")})
    for v in await ctx.list("venues", {"$or": [{"name": rx}, {"city": rx}]}, limit=6) if ctx.sees("venues") else []:
        out["venues"].append({"id": v["id"], "label": v["name"], "sub": v.get("city", "")})
    for m in await ctx.list("equipment", {"$or": [{"name": rx}, {"ref": rx}]}, limit=6) if ctx.sees("catalog") else []:
        out["equipment"].append({"id": m["id"], "label": m["name"], "sub": m["ref"]})
    if ctx.can("finance:read"):
        for coll in [c for c in ("quotes", "invoices") if ctx.sees(c)]:
            out[coll] = [{"id": d["id"], "event_id": d.get("event_id"), "label": d["number"], "sub": d.get("event_title") or (d.get("client") or {}).get("name", "")}
                         for d in await ctx.list(coll, {"$or": [{"number": rx}, {"event_title": rx}, {"client.name": rx}]}, limit=6)]
    return out


# ---------- Ajout rapide du devis : recherche catalogue ----------
def _norm(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


def _score(tokens: list, e: dict) -> int:
    from difflib import SequenceMatcher
    name, ref = _norm(e.get("name")), _norm(e.get("ref"))
    q = " ".join(tokens)
    if ref == q:
        return 100
    hay = f"{name} {ref} {_norm(e.get('category'))} {_norm(e.get('brand'))} {_norm(' '.join(e.get('keywords') or []))} {_norm(e.get('description'))}"
    words, total = hay.replace("-", " ").split(), 0
    for t in tokens:
        if any(w.startswith(t) for w in words):
            total += 60
        elif t in hay:
            total += 40
        elif len(t) >= 4 and any(SequenceMatcher(None, t, w[:len(t) + 1]).ratio() >= 0.75 for w in words):
            total += 20
        else:
            return 0
    return total // len(tokens) + (20 if name.startswith(q) else 0)


@router.get("/catalog/search")
async def catalog_search(q: str = "", limit: int = 8, event_id: str = "", ctx: Ctx = Depends(need("catalog:read"))):
    from core import hidden_of
    tokens = _norm(q).split()
    if len("".join(tokens)) < 2:
        return {"q": q, "items": []}
    show = "sale_prices" not in hidden_of(ctx.profile)
    rows = [(s, e) for e in await ctx.list("equipment", {"archived": {"$ne": True}}, limit=5000) if (s := _score(tokens, e))]
    rows.sort(key=lambda x: (-x[0], x[1].get("name", "")))
    used, at_dates = {}, False
    ev = await db.events.find_one(ctx.q({"id": event_id}), {"_id": 0}) if event_id else None
    if ev and ev.get("start") and ev.get("end"):
        evs = [e for e in await ctx.list("events", {"status": {"$ne": "cloture"}}, limit=5000) if e["id"] != event_id]
        used, at_dates = usage(evs, ev.get("setup_start") or ev["start"], ev.get("return_end") or ev["end"])[0], True
    free = []
    if ctx.can("finance:read"):
        pipe = [{"$match": ctx.q({})}, {"$unwind": "$lines"}, {"$match": {"lines.equipment_id": {"$in": ["", None]}, "lines.pack_id": {"$in": ["", None]}, "lines.kind": {"$ne": "title"}}},
                {"$group": {"_id": "$lines.label", "uses": {"$sum": 1}, "price": {"$last": "$lines.unit_price"}}}, {"$limit": 5000}]
        known = {_norm(e.get("name")) for _, e in rows}
        hits = [g async for g in db.quotes.aggregate(pipe) if g["_id"] and all(t in _norm(g["_id"]) for t in tokens) and _norm(g["_id"]) not in known]
        free = [{"label": g["_id"], "uses": g["uses"], **({"price": g.get("price") or 0} if show else {})} for g in sorted(hits, key=lambda g: -g["uses"])[:4]]
    return {"q": q, "items": [{"id": e["id"], "name": e["name"], "ref": e.get("ref", ""), "category": e.get("category", ""), "unit": e.get("uom") or "",
                               "available": num((e.get("qty_total") or 0) - (e.get("qty_maintenance") or 0) - used.get(e["id"], 0)), "at_event_dates": at_dates, **({"price": e.get("price_day") or 0} if show else {})} for _, e in rows[:min(max(limit, 1), 20)]], "free": free}


class QuickProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    category: str = Field(min_length=1, max_length=80)
    subcategory: str = Field("", max_length=120)
    product_type: str = Field("Location", max_length=40)
    price_day: float = Field(0, ge=0)
    qty_total: Qty = Field(0, ge=0)


@router.post("/equipment/quick")
async def quick_product(body: QuickProductIn, ctx: Ctx = Depends(need("catalog:write"))):
    import re
    code = lambda x, fb: re.sub(r"[^A-Z0-9]", "", _norm(x).upper())[:3] or fb  # noqa: E731
    prefix = f"{code(body.category, 'DIV')}-{code(body.subcategory, 'GEN')}-"
    n = await db.equipment.count_documents(ctx.q({"ref": {"$regex": f"^{prefix}"}})) + 1
    while await db.equipment.find_one(ctx.q({"ref": f"{prefix}{n:03d}"})):
        n += 1
    check_whole({}, body.qty_total)
    return await ctx.insert("equipment", {**EquipmentIn(ref=f"{prefix}{n:03d}", **body.model_dump()).model_dump(), "qty_maintenance": 0, "maintenance_log": [], "to_complete": True})
