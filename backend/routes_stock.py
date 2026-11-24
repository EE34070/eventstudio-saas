import csv
import io
import os
from datetime import datetime, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from core import Ctx, db, need, new_id, now_iso
from routes_billing import hist, plus_days, quote_writer, today
from routes_ops import holds, period

from routes_units import Qty, check_whole, num, to_pieces  # noqa: E402

router = APIRouter(prefix="/api")
R, WR, FIN = need("catalog:read"), need("catalog:write"), need("finance:read")
FMT = "%Y-%m-%dT%H:%M"
RULE = "Le premier devis signé (ou acompte payé) obtient le matériel ; les autres devis passent en rouge et leur responsable est alerté."
MOVES = {"entree": "Entrée", "sortie_evenement": "Sortie événement", "retour_evenement": "Retour événement", "transfert": "Transfert", "casse": "Casse / perte", "ajustement": "Ajustement"}


class WarehouseIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal["principal", "site_client", "partenaire", "vehicule", "autre"] = "autre"
    address: str = Field("", max_length=200)
    postal_code: str = Field("", max_length=12)
    city: str = Field("", max_length=80)
    country: str = Field("France", max_length=60)
    lat: Optional[float] = None
    lng: Optional[float] = None
    venue_id: str = ""
    manager_contact_id: str = ""
    access_hours: str = Field("", max_length=300)
    access_instructions: str = Field("", max_length=1000)
    is_default: bool = False
    priority: int = Field(10, ge=0, le=999)
    restricted_to_venue: Optional[bool] = None
    active: bool = True


# ---------- Modèle : entrepôts, niveaux, mouvements ----------
async def move(org_id: str, kind: str, pid: str, qty: int, frm: str = "", to: str = "", event_id: str = "", note: str = "", by: str = "Système", status: str = "done") -> dict:
    m = {"id": new_id(), "org_id": org_id, "created_at": now_iso(), "type": kind, "product_id": pid, "qty": qty, "from_warehouse_id": frm, "to_warehouse_id": to, "event_id": event_id,
         "logistics_mission_id": "", "status": status, "user": by, "note": note}
    await db.stock_movements.insert_one(dict(m))
    return m


async def world(org_id: str) -> dict:
    whs = await db.warehouses.find({"org_id": org_id}, {"_id": 0}).sort([("priority", 1), ("name", 1)]).to_list(500)
    if not whs:
        w = {"id": new_id(), "org_id": org_id, "created_at": now_iso(), **WarehouseIn(name="Entrepôt principal", type="principal", is_default=True, restricted_to_venue=False, priority=0).model_dump()}
        try:
            await db.warehouses.insert_one(dict(w))
        except DuplicateKeyError:
            pass
        whs = await db.warehouses.find({"org_id": org_id}, {"_id": 0}).to_list(500)
    default = next((w for w in whs if w.get("is_default")), whs[0])
    eqs = {e["id"]: e async for e in db.equipment.find({"org_id": org_id}, {"_id": 0, "maintenance_log": 0, "requirements": 0})}
    levels: dict = {}
    async for l in db.stock_levels.find({"org_id": org_id}, {"_id": 0}):
        levels.setdefault(l["product_id"], {})[l["warehouse_id"]] = l["qty_on_hand"]
    for pid, e in eqs.items():
        if pid not in levels:
            try:
                await db.stock_levels.insert_one({"org_id": org_id, "product_id": pid, "warehouse_id": default["id"], "qty_on_hand": e.get("qty_total", 0), "updated_at": now_iso()})
                if e.get("qty_total"):
                    await move(org_id, "entree", pid, e["qty_total"], to=default["id"], note="Reprise du stock existant")
            except DuplicateKeyError:
                pass
            levels[pid] = {default["id"]: e.get("qty_total", 0)}
    return {"whs": whs, "by": {w["id"]: w for w in whs}, "eqs": eqs, "levels": levels, "default": default}


async def migrate() -> None:
    async for org in db.orgs.find({}, {"_id": 0, "id": 1}):
        await world(org["id"])


async def sync_total(org_id: str, pid: str) -> None:
    key = {"org_id": org_id, "product_id": pid}
    total = sum([l["qty_on_hand"] async for l in db.stock_levels.find(key, {"_id": 0})])
    total += sum([m["qty"] async for m in db.stock_movements.find({**key, "status": "in_transit"}, {"_id": 0})])
    await db.equipment.update_one({"org_id": org_id, "id": pid}, {"$set": {"qty_total": num(total)}})


async def bump(org_id: str, pid: str, wid: str, delta: int) -> None:
    key = {"org_id": org_id, "product_id": pid, "warehouse_id": wid}
    if delta < 0:
        r = await db.stock_levels.update_one({**key, "qty_on_hand": {"$gte": -delta}}, {"$inc": {"qty_on_hand": delta}, "$set": {"updated_at": now_iso()}})
        if not r.matched_count:
            raise HTTPException(400, "Stock insuffisant dans cet entrepôt pour ce mouvement")
    elif delta:
        await db.stock_levels.update_one(key, {"$inc": {"qty_on_hand": delta}, "$set": {"updated_at": now_iso()}}, upsert=True)
    await sync_total(org_id, pid)
    if delta > 0:
        for eid in await db.shortages.distinct("event_id", {"org_id": org_id, "product_id": pid, "status": {"$ne": "resolu"}}):
            await reallocate(org_id, eid)


async def on_total_change(ctx: Ctx, pid: str, old: int, new: int) -> None:
    if old == new:
        return
    w = await world(ctx.org_id)
    try:
        await bump(ctx.org_id, pid, w["default"]["id"], new - old)
    except HTTPException:
        raise HTTPException(400, "Quantité inférieure au stock de l'entrepôt par défaut : ajustez le stock par entrepôt (Entrepôts & stocks)")
    await move(ctx.org_id, "ajustement", pid, new - old, to=w["default"]["id"], note="Quantité totale modifiée dans le catalogue", by=ctx.member.get("name"))


async def consume(org_id: str, pid: str, delta: int, wid: str = "", event_id: str = "") -> None:
    w = await world(org_id)
    wid = wid if wid in w["by"] else w["default"]["id"]
    have = w["levels"].get(pid, {}).get(wid, 0)
    d = -min(delta, have) if delta > 0 else -delta
    if d:
        await bump(org_id, pid, wid, d)
        await move(org_id, "sortie_evenement" if d < 0 else "ajustement", pid, d, frm=wid, event_id=event_id, note="Consommable utilisé")


# ---------- Disponibilité et allocation ----------
def _shift(s: str, n: int) -> str:
    return (datetime.strptime(s[:16], FMT) + timedelta(days=n)).strftime(FMT) if n else s[:16]


def buffered(base: tuple, eq: dict) -> tuple:
    return _shift(base[0], -int(eq.get("prep_days_before") or 0)), _shift(base[1], int(eq.get("return_days_after") or 0))


def overlap(a: tuple, b: tuple) -> bool:
    return a[0] < b[1] and a[1] > b[0]


def target(ev: dict) -> str:
    return (ev.get("delivery_venue_id") if not ev.get("delivery_same_as_venue", True) else "") or ev.get("venue_id") or ""


def _ful(w: dict, venue: str) -> str:
    return "on_site" if venue and w.get("venue_id") == venue else "to_deliver"


def alloc_of(ev: dict, w: dict) -> list:
    if ev.get("allocations") is not None:
        return ev["allocations"]
    d = w["default"]
    return [{"equipment_id": l["equipment_id"], "warehouse_id": d["id"], "qty": l["qty"], "fulfilment": _ful(d, target(ev)), "mode": "auto"} for l in ev.get("equipment", [])]


def maint(w: dict, pid: str) -> dict:
    left, out, lv = (w["eqs"].get(pid) or {}).get("qty_maintenance", 0), {}, w["levels"].get(pid, {})
    for wh in sorted(w["whs"], key=lambda x: not x.get("is_default")):
        take = min(left, lv.get(wh["id"], 0))
        if take:
            out[wh["id"]], left = take, left - take
    return out


def reserved(w: dict, evs: list, pid: str, sp: tuple, exclude: str = "") -> dict:
    out, eq = {}, w["eqs"].get(pid) or {}
    for o in evs:
        if o["id"] == exclude or not holds(o) or not overlap(buffered(period(o), eq), sp):
            continue
        for r in alloc_of(o, w):
            if r["equipment_id"] == pid:
                out[r["warehouse_id"]] = out.get(r["warehouse_id"], 0) + r["qty"]
    return out


def usable(w: dict, venue: str) -> list:
    act = [x for x in w["whs"] if x.get("active", True)]
    first = [x for x in act if venue and x.get("venue_id") == venue]
    rest = [x for x in act if x not in first and not x.get("restricted_to_venue")]
    return first + sorted(rest, key=lambda x: (x.get("priority", 10), not x.get("is_default")))


def allocate(w: dict, evs: list, pid: str, qty: int, venue: str, sp: tuple, exclude: str = "", extra: dict | None = None) -> tuple:
    res, mt, lv, rows, left = reserved(w, evs, pid, sp, exclude), maint(w, pid), w["levels"].get(pid, {}), [], qty
    for wh in usable(w, venue):
        av = lv.get(wh["id"], 0) - mt.get(wh["id"], 0) - res.get(wh["id"], 0) - (extra or {}).get(wh["id"], 0)
        take = min(left, max(0, av))
        if take:
            rows.append({"equipment_id": pid, "warehouse_id": wh["id"], "qty": num(take), "fulfilment": _ful(wh, venue), "mode": "auto"})
            left = num(left - take)
    return rows, left


def plan_event(w: dict, evs: list, ev: dict) -> tuple:
    rows, missing, venue, stored = [], [], target(ev), ev.get("allocations") or []
    for l in ev.get("equipment", []):
        pid, eq = l["equipment_id"], w["eqs"].get(l["equipment_id"]) or {}
        mine = [r for r in stored if r["equipment_id"] == pid and r.get("mode") == "manual" and r["warehouse_id"] in w["by"]]
        if mine and sum(r["qty"] for r in mine) <= l["qty"]:
            got, left = [{**r, "fulfilment": _ful(w["by"][r["warehouse_id"]], venue)} for r in mine], l["qty"] - sum(r["qty"] for r in mine)
        else:
            got, left = allocate(w, evs, pid, l["qty"], venue, buffered(period(ev), eq), ev["id"])
        rows += got
        if left:
            missing.append({"equipment_id": pid, "ref": eq.get("ref", ""), "name": eq.get("name", ""), "requested": l["qty"], "available": l["qty"] - left, "missing": left, "events": []})
    for a in ev.get("auto_equipment") or []:
        pid = a["equipment_id"]
        if pid not in w["eqs"]:
            continue
        taken: dict = {}
        for r in rows:
            if r["equipment_id"] == pid:
                taken[r["warehouse_id"]] = taken.get(r["warehouse_id"], 0) + r["qty"]
        got, left = allocate(w, evs, pid, a["qty"], venue, buffered(period(ev), w["eqs"][pid]), ev["id"], taken)
        rows += [{**r, "auto": True} for r in got]
        if left:
            missing.append({"equipment_id": pid, "ref": w["eqs"][pid].get("ref", ""), "name": w["eqs"][pid].get("name", ""), "requested": a["qty"], "available": a["qty"] - left, "missing": left, "events": [], "auto": True})
    return rows, missing


async def _evs(org_id: str) -> list:
    return await db.events.find({"org_id": org_id, "status": {"$ne": "cloture"}}, {"_id": 0, "history": 0}).to_list(5000)


async def check(org_id: str, ev: dict) -> None:
    """Règle « ne jamais bloquer » : un stock insuffisant produit une liste de manques (routes_shortages), plus d'erreur."""
    return


async def reallocate(org_id: str, eid: str, reset: bool = False) -> dict:
    ev = await db.events.find_one({"org_id": org_id, "id": eid}, {"_id": 0, "history": 0})
    if not ev:
        return {}
    old = ev.get("allocations")
    from routes_material import auto_of, build
    reqs = {e["id"]: e async for e in db.equipment.find({"org_id": org_id, "id": {"$in": [l["equipment_id"] for l in ev.get("equipment", [])]}}, {"_id": 0, "id": 1, "name": 1, "ref": 1, "requirements": 1})}
    req_lines = build(ev, reqs)[0]
    ev["auto_equipment"] = [{"equipment_id": p, "qty": n} for p, n in sorted(__import__("routes_kits").merge_auto(ev, auto_of(req_lines)).items())]
    await db.events.update_one({"org_id": org_id, "id": eid}, {"$set": {"auto_equipment": ev["auto_equipment"]}})
    w, evs = await world(org_id), await _evs(org_id)
    rows, missing = plan_event(w, evs, {**ev, "allocations": [] if reset else old})
    on, deliver = sum(r["qty"] for r in rows if r["fulfilment"] == "on_site"), sum(r["qty"] for r in rows if r["fulfilment"] == "to_deliver")
    note = ev.get("allocation_note", "")
    if old is not None and rows != old:
        note = f"Allocation recalculée le {datetime.now().strftime('%d/%m/%Y à %H:%M')} : {on} sur place, {deliver} à livrer" + (f", manque {sum(m['missing'] for m in missing)}" if missing else "") + "."
    await db.events.update_one({"org_id": org_id, "id": eid}, {"$set": {"allocations": rows, "allocation_note": note}})
    import routes_shortages
    await routes_shortages.sync(org_id, ev, w, evs, missing, req_lines)
    return {"rows": rows, "missing": missing, "note": note}


# ---------- Options (devis non validés) ----------
NO_STOCK = ("Service", "Prestation artistique", "Pack")


def pack_parts(l: dict, eqs: dict | None) -> dict | None:
    """Composants matériels d'une ligne pack (copie du devis, sinon catalogue) ; None si la ligne n'est pas un pack."""
    e = (eqs or {}).get(l.get("equipment_id")) or {}
    comps = l.get("pack_components") if l.get("pack_components") is not None else (e.get("components") or []) if e.get("product_type") == "Pack" else None
    if comps is None:
        return None
    out: dict = {}
    for c in comps:
        x = (eqs or {}).get(c["equipment_id"]) or {}
        subs = [(s["equipment_id"], s["qty"] * c["qty"]) for s in x.get("components") or []] if x.get("product_type") == "Pack" else [(c["equipment_id"], c["qty"])]
        for i, n in subs:
            if eqs is None or (i in eqs and (eqs[i].get("product_type") or "Location") not in NO_STOCK):
                out[i] = out.get(i, 0) + n * l["qty"]
    return out


def quote_items(lines: list, packs: dict, eqs: dict | None = None) -> dict:
    out: dict = {}
    for l in lines:
        parts = pack_parts(l, eqs)
        if parts is not None:
            for i, n in parts.items():
                out[i] = out.get(i, 0) + n
            continue
        if l.get("equipment_id"):
            out[l["equipment_id"]] = out.get(l["equipment_id"], 0) + to_pieces((eqs or {}).get(l["equipment_id"]) or {}, l["qty"] - (l.get("reused") or 0), l.get("uom") or "") if l["qty"] > (l.get("reused") or 0) else 0
        for it in (packs.get(l.get("pack_id")) or {}).get("items", []):
            out[it["equipment_id"]] = out.get(it["equipment_id"], 0) + int(it["qty"] * l["qty"])
    return out


def eff_exp(q: dict, days: int) -> str:
    if q.get("option_expires_at"):
        return q["option_expires_at"]
    return plus_days((q.get("sent_at") or q.get("updated_at") or q.get("date") or today())[:10], days) if q["status"] in ("envoye", "vu", "negociation") else ""


async def task(org_id: str, title: str, ref: str, owner: str = "", desc: str = "") -> None:
    if await db.tasks.find_one({"org_id": org_id, "source_ref": ref, "status": {"$ne": "done"}, "deleted_at": None}):
        return
    await db.tasks.insert_one({"id": new_id(), "org_id": org_id, "created_at": now_iso(), "title": title, "description": desc, "due_at": today(), "due_date": today(), "priority": "urgent",
                               "assignee_ids": [owner] if owner else [], "event_id": "", "status": "todo", "done": False, "done_at": None, "checklist": [], "attachments": [], "source": "auto",
                               "source_ref": ref, "created_by": "Système", "created_by_id": ""})


async def _opp(org_id: str, qid: str) -> dict:
    return await db.opportunities.find_one({"org_id": org_id, "quote_ids": qid}, {"_id": 0}) or {}


async def _crm(org_id: str, qid: str, text: str) -> dict:
    o = await _opp(org_id, qid)
    if o:
        from routes_crm import log
        await log(org_id, o["id"], "note", text)
    return o


async def expire_options(org_id: str) -> int:
    org = await db.orgs.find_one({"id": org_id}, {"_id": 0, "option_days": 1}) or {}
    n, day = 0, today()
    async for q in db.quotes.find({"org_id": org_id, "status": {"$in": ["brouillon", "envoye", "vu", "negociation"]}, "option_released_at": None}, {"_id": 0}):
        exp = eff_exp(q, org.get("option_days") or 7)
        if exp and exp < day and not (q.get("signature") or {}).get("status") == "done":
            await db.quotes.update_one({"org_id": org_id, "id": q["id"]}, {"$set": {"option_released_at": now_iso()},
                                                                            "$push": {"history": {"at": now_iso(), "by": "Système", "action": "Option", "detail": f"Option expirée le {exp} : matériel libéré"}}})
            o = await _crm(org_id, q["id"], f"Option du devis {q['number']} expirée le {exp} : matériel libéré.")
            await task(org_id, f"Relancer ou clôturer le devis {q['number']}", f"option:{q['id']}", o.get("owner_id", ""), f"L'option a expiré le {exp} sans signature ; le matériel n'est plus réservé à titre provisoire.")
            n += 1
    return n


async def tick() -> None:
    async for org in db.orgs.find({}, {"_id": 0, "id": 1}):
        await expire_options(org["id"])


async def prepare(org_id: str) -> dict:
    await expire_options(org_id)
    w, evs = await world(org_id), await _evs(org_id)
    org = await db.orgs.find_one({"id": org_id}, {"_id": 0, "stock_count_options": 1, "option_days": 1}) or {}
    by = {e["id"]: e for e in evs}
    packs = {p["id"]: p async for p in db.packs.find({"org_id": org_id}, {"_id": 0})}
    opps: dict = {}
    async for o in db.opportunities.find({"org_id": org_id, "quote_ids.0": {"$exists": True}}, {"_id": 0}):
        opps.update({qid: o for qid in o["quote_ids"]})
    users = {u["user_id"]: u.get("name") or u.get("email") async for u in db.users.find({"org_id": org_id}, {"_id": 0})}
    opts = []
    async for q in db.quotes.find({"org_id": org_id, "status": {"$in": ["brouillon", "envoye", "vu", "negociation"]}, "option_released_at": None}, {"_id": 0}).sort("created_at", 1):
        ev = by.get(q.get("event_id"))
        items = quote_items(q["lines"], packs, w["eqs"]) if ev and not holds(ev) and not ev.get("date_tbc") else {}
        if items:
            opts.append({"q": q, "ev": ev, "items": items})
    from routes_main import contact_name
    pl = {c["id"]: contact_name(c) async for c in db.contacts.find({"org_id": org_id, "id": {"$in": [o["ev"].get("planner_contact_id") for o in opts if o["ev"].get("planner_contact_id")]}}, {"_id": 0})}
    return {"w": w, "evs": evs, "by": by, "opts": opts, "count": bool(org.get("stock_count_options")), "days": org.get("option_days") or 7, "opps": opps, "users": users, "packs": packs, "planners": pl}


def row(c: dict, pid: str, qty: int, venue: str, base: tuple, xq: str = "", xe: str = "") -> dict | None:
    w, eq = c["w"], c["w"]["eqs"].get(pid)
    if not eq:
        return None
    sp, mt, lv = buffered(base, eq), maint(w, pid), w["levels"].get(pid, {})
    res = reserved(w, c["evs"], pid, sp, xe)
    whs = [{"warehouse_id": x["id"], "name": x["name"], "on_site": _ful(x, venue) == "on_site", "on_hand": lv.get(x["id"], 0) - mt.get(x["id"], 0), "reserved": res.get(x["id"], 0)} for x in usable(w, venue) if lv.get(x["id"], 0)]
    total, firm, options = sum(x["on_hand"] for x in whs), sum(x["reserved"] for x in whs), []
    for o in c["opts"]:
        q, ev = o["q"], o["ev"]
        if q["id"] == xq or ev["id"] == xe or pid not in o["items"] or not overlap(buffered(period(ev), eq), sp):
            continue
        opp = c["opps"].get(q["id"]) or {}
        options.append({"quote_id": q["id"], "number": q["number"], "event_id": ev["id"], "client": (q.get("client") or {}).get("name", ""), "organizer": c["planners"].get(ev.get("planner_contact_id"), ""),
                        "start": period(ev)[0], "end": period(ev)[1], "qty": o["items"][pid], "status": q["status"], "sent_at": q.get("sent_at") or "", "expires": eff_exp(q, c["days"]),
                        "probability": opp.get("probability"), "owner": c["users"].get(opp.get("owner_id")) or ((q.get("history") or [{}])[0].get("by") or ""), "last_urgent_reminder_at": q.get("last_urgent_reminder_at") or ""})
    oq = sum(x["qty"] for x in options)
    if_all = total - firm - oq
    now_av = if_all if c["count"] else total - firm
    color = "red" if qty > now_av else "orange" if qty > if_all else "green"
    extra, left = {}, oq if c["count"] else 0
    for x in whs:
        extra[x["warehouse_id"]] = min(left, max(0, x["on_hand"] - x["reserved"]))
        left -= extra[x["warehouse_id"]]
    alloc, missing = allocate(w, c["evs"], pid, qty, venue, sp, xe, extra)
    msg = f"Manque {qty - max(0, now_av)} : sous-location / prestataire, produit de remplacement ou quantité réduite." if color == "red" else ""
    if color == "orange":
        msg = f"Si {options[0]['number'] if len(options) == 1 else 'les options concurrentes'} {'est signé' if len(options) == 1 else 'sont signées'}, il manquera {qty - max(0, if_all)} {eq['name']}."
    return {"product_id": pid, "ref": eq.get("ref", ""), "name": eq["name"], "qty": qty, "total": total, "firm": firm, "option_qty": oq, "options": options, "available_now": total - firm, "available_if_options": if_all,
            "color": color, "message": msg, "warehouses": whs, "missing": missing, "weight_kg": eq.get("weight_kg") or 0, "volume_m3": eq.get("volume_m3") or 0,
            "allocation": [{**a, "name": w["by"][a["warehouse_id"]]["name"]} for a in alloc]}


def _pack(c: dict, rows: list) -> dict:
    rows = [r for r in rows if r]
    dl = [(a, r) for r in rows for a in r["allocation"] if a["fulfilment"] == "to_deliver"]
    on = sum(a["qty"] for r in rows for a in r["allocation"] if a["fulfilment"] == "on_site")
    return {"rows": rows, "no_date": False, "count_options": c["count"], "rule": RULE,
            "delivery": {"to_deliver_qty": sum(a["qty"] for a, _ in dl), "on_site_qty": on, "weight_kg": round(sum(a["qty"] * r["weight_kg"] for a, r in dl), 1), "volume_m3": round(sum(a["qty"] * r["volume_m3"] for a, r in dl), 2),
                         "all_on_site": bool(on) and not dl and not any(r["missing"] for r in rows)}}


class AvLine(BaseModel):
    equipment_id: str = ""
    pack_id: str = ""
    qty: float = Field(1, gt=0)
    uom: str = Field("", max_length=12)


class AvIn(BaseModel):
    event_id: str = ""
    date: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    venue_id: str = ""
    lines: List[AvLine] = Field(max_length=200)


@router.post("/stock/availability")
async def availability(body: AvIn, ctx: Ctx = Depends(FIN)):
    c = await prepare(ctx.org_id)
    ev = await ctx.get("events", body.event_id) if body.event_id else None
    if (ev and ev.get("date_tbc")) or not (ev or body.date):
        return {"rows": [], "no_date": True}
    base = period(ev) if ev else (f"{body.date}T18:00", _shift(f"{body.date}T02:00", 1))
    venue = target(ev) if ev else body.venue_id
    items = quote_items([l.model_dump() for l in body.lines], c["packs"], c["w"]["eqs"])
    return _pack(c, [row(c, pid, q, venue, base, xe=ev["id"] if ev else "") for pid, q in items.items()])


async def _quote_rows(c: dict, q: dict) -> list:
    ev = c["by"].get(q.get("event_id"))
    if not ev or ev.get("date_tbc"):
        return []
    return [row(c, pid, n, target(ev), period(ev), q["id"], ev["id"]) for pid, n in quote_items(q["lines"], c["packs"], c["w"]["eqs"]).items()]


@router.get("/quotes/{qid}/availability")
async def quote_availability(qid: str, ctx: Ctx = Depends(FIN)):
    q, c = await ctx.get("quotes", qid), await prepare(ctx.org_id)
    q = await ctx.get("quotes", qid)
    return {**_pack(c, await _quote_rows(c, q)), "option_expires_at": eff_exp(q, c["days"]), "option_released_at": q.get("option_released_at"), "show_on_site": bool(q.get("show_on_site")), "status": q["status"]}


@router.get("/stock/options")
async def options_view(ctx: Ctx = Depends(FIN)):
    c, out, comp = await prepare(ctx.org_id), [], {}
    for o in c["opts"]:
        q, ev = o["q"], o["ev"]
        for r in await _quote_rows(c, q):
            if not r:
                continue
            if r["options"]:
                comp.setdefault(q["id"], set()).update(x["number"] for x in r["options"])
            out.append({"product_id": r["product_id"], "product": r["name"], "date": period(ev)[0][:10], "quote_id": q["id"], "number": q["number"], "event_id": ev["id"], "client": (q.get("client") or {}).get("name", ""),
                        "status": q["status"], "qty": r["qty"], "color": r["color"], "message": r["message"], "option_qty": r["option_qty"], "available_now": r["available_now"], "expires": eff_exp(q, c["days"]),
                        "competitors": [x["number"] for x in r["options"]]})
    out.sort(key=lambda x: ({"red": 0, "orange": 1, "green": 2}[x["color"]], x["date"]))
    return {"rows": out, "competition": {k: sorted(v) for k, v in comp.items()}, "tension": [x for x in out if x["color"] != "green"], "rule": RULE, "count_options": c["count"]}


async def after_firm(org_id: str, qid: str) -> None:
    signed = await db.quotes.find_one({"org_id": org_id, "id": qid}, {"_id": 0})
    c = await prepare(org_id)
    mine = set(quote_items(signed["lines"], c["packs"]))
    for o in c["opts"]:
        red = [r for r in await _quote_rows(c, o["q"]) if r and r["color"] == "red" and r["product_id"] in mine]
        if red:
            n = o["q"]["number"]
            opp = await _crm(org_id, o["q"]["id"], f"Stock : le devis {signed['number']} a été signé ; il manque du matériel pour le devis {n} ({', '.join(r['name'] for r in red)}).")
            await task(org_id, f"Stock insuffisant pour le devis {n}", f"stock:{o['q']['id']}", opp.get("owner_id", ""), f"Un autre devis ({signed['number']}) a été signé sur le même matériel aux mêmes dates. " + " ".join(r["message"] for r in red))


class OptionIn(BaseModel):
    option_expires_at: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    show_on_site: Optional[bool] = None


@router.patch("/quotes/{qid}/option")
async def patch_option(qid: str, body: OptionIn, ctx: Ctx = Depends(FIN)):
    quote_writer(ctx)
    await ctx.get("quotes", qid)
    upd = body.model_dump(exclude_none=True)
    if "option_expires_at" in upd and upd["option_expires_at"] >= today():
        upd["option_released_at"] = None
    if upd:
        await db.quotes.update_one(ctx.q({"id": qid}), {"$set": upd, "$push": {"history": hist(ctx, "Option", f"Expiration de l'option : {upd['option_expires_at']}" if "option_expires_at" in upd else "Mention « déjà sur place »")}})
    if "option_expires_at" in upd and upd["option_expires_at"] < today():
        await expire_options(ctx.org_id)
    return await ctx.get("quotes", qid)


async def on_site_note(doc: dict) -> dict:
    c = await prepare(doc["org_id"])
    on = {r["product_id"]: sum(a["qty"] for a in r["allocation"] if a["fulfilment"] == "on_site") for r in await _quote_rows(c, doc) if r}
    en = (doc.get("language") or "fr").startswith("en")
    lines = []
    for l in doc["lines"]:
        n = on.get(l.get("equipment_id"), 0)
        txt = (f"including {n} already on site" if en else f"dont {n} déjà sur place") if n else ""
        lines.append({**l, "description": " — ".join(filter(None, [l.get("description", ""), txt]))})
    return {**doc, "lines": lines}


# ---------- Relance d'urgence ----------
TPL = {"fr": ("Votre devis {numero_devis} : merci de confirmer avant le {date_limite}",
              "Nous avons une autre demande pour du matériel réservé à titre provisoire sur votre date ({date_evenement}{lieu}).\n\nPour vous garantir la disponibilité, merci de confirmer votre devis {numero_devis} avant le {date_limite}.\n\nPassé ce délai, nous ne pourrons plus garantir la réservation.", "Voir et signer le devis"),
       "en": ("Your quote {numero_devis}: please confirm before {date_limite}",
              "We have received another request for equipment provisionally reserved for your date ({date_evenement}{lieu}).\n\nTo guarantee availability, please confirm your quote {numero_devis} before {date_limite}.\n\nAfter this date, we will no longer be able to guarantee the reservation.", "View and sign the quote")}


async def _send(fn, **kw):
    return await fn(**kw)


async def _reminder(ctx: Ctx, qid: str, request: Request) -> dict:
    from i18n import fmt_date, tr
    from routes_comms import _recent, base_url, client_of, ensure_token
    q = await ctx.get("quotes", qid)
    ev = await db.events.find_one(ctx.q({"id": q.get("event_id")}), {"_id": 0, "history": 0}) or {}
    to = await client_of(q)
    cid = q.get("client_id", "")
    if ev.get("main_contact_role") == "planner" and ev.get("planner_contact_id"):
        p = await db.contacts.find_one(ctx.q({"id": ev["planner_contact_id"]}), {"_id": 0}) or {}
        if p.get("email"):
            to, cid = {"email": p["email"].strip(), "first_name": p.get("first_name", ""), "name": p.get("company") or p.get("last_name", ""), "language": p.get("language") or "fr-FR"}, p["id"]
    lg = to["language"]
    k = "en" if lg.startswith("en") else "fr"
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    exp = eff_exp(q, org.get("option_days") or 7)
    deadline = exp if exp >= today() else plus_days(today(), 3)
    venue = await db.venues.find_one(ctx.q({"id": target(ev)}), {"_id": 0, "name": 1}) if target(ev) else None

    def fill(s: str, d: str) -> str:
        return s.format(numero_devis=q["number"], date_limite=fmt_date(d, lg), date_evenement=fmt_date(q.get("event_date") or "", lg) or "—", lieu=f", {venue['name']}" if venue else "")
    url = f"{(os.environ.get('APP_URL') or base_url(request)).rstrip('/')}/devis/{await ensure_token('quotes', q)}"
    return {"q": q, "org": org, "to": to, "contact_id": cid, "language": lg, "deadline": deadline, "url": url, "button": TPL[k][2], "greeting": tr("hello", lg, name=to.get("first_name") or to.get("name") or ""),
            "subject": fill(TPL[k][0], deadline), "body": fill(TPL[k][1], deadline), "fill": fill, "k": k, "recent": _recent(q.get("last_urgent_reminder_at"), 172800)}


@router.get("/quotes/{qid}/urgent-reminder")
async def reminder_preview(qid: str, request: Request, ctx: Ctx = Depends(FIN)):
    r = await _reminder(ctx, qid, request)
    return {"to": r["to"]["email"], "language": r["language"], "deadline": r["deadline"], "subject": r["subject"], "body": r["body"], "greeting": r["greeting"], "url": r["url"], "status": r["q"]["status"],
            "last_urgent_reminder_at": r["q"].get("last_urgent_reminder_at") or "", "recent": r["recent"], "channel": "email", "whatsapp": False}


class ReminderIn(BaseModel):
    subject: str = Field("", max_length=200)
    body: str = Field("", max_length=3000)
    deadline: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    set_deadline: bool = True


@router.post("/quotes/{qid}/urgent-reminder")
async def reminder_send(qid: str, body: ReminderIn, request: Request, ctx: Ctx = Depends(FIN)):
    from emailer import mail_html, send_email
    from routes_comms import reply_to
    quote_writer(ctx)
    r = await _reminder(ctx, qid, request)
    q, to = r["q"], r["to"]
    if q["status"] not in ("envoye", "vu", "negociation"):
        raise HTTPException(400, "La relance urgente concerne un devis envoyé et non signé : envoyez d'abord le devis")
    if not to["email"]:
        raise HTTPException(400, "Le destinataire n'a pas d'adresse e-mail valide")
    if r["recent"]:
        raise HTTPException(409, {"code": "reminder_recent", "message": "Une relance urgente a déjà été envoyée pour ce devis il y a moins de 48 h"})
    deadline = body.deadline or r["deadline"]
    if deadline < today():
        raise HTTPException(400, "La date limite est dépassée")
    text = body.body.strip() or r["fill"](TPL[r["k"]][1], deadline)
    subject = body.subject.strip() or r["fill"](TPL[r["k"]][0], deadline)
    try:
        mid = await _send(send_email, to=to["email"], subject=subject, html=mail_html(r["org"]["name"], r["greeting"], [p for p in text.split("\n") if p.strip()], (r["button"], r["url"]), r["language"]), reply_to=reply_to(r["org"]))
    except HTTPException as e:
        raise HTTPException(502, {"code": "reminder_failed", "message": f"La relance n'a pas pu être envoyée : {str(e.detail).rstrip('.')}. Rien n'a été enregistré, vous pouvez réessayer."})
    except Exception:
        raise HTTPException(502, {"code": "reminder_failed", "message": "La relance n'a pas pu être envoyée : service d'e-mail injoignable. Rien n'a été enregistré, vous pouvez réessayer."})
    now, by = now_iso(), ctx.member.get("name")
    upd = {"last_urgent_reminder_at": now, **({"option_expires_at": deadline, "option_released_at": None} if body.set_deadline else {})}
    await db.quotes.update_one(ctx.q({"id": qid}), {"$set": upd, "$push": {"history": hist(ctx, "Relance urgente", f"Envoyée à {to['email']} — date limite {deadline}")}})
    await ctx.insert("urgent_reminders", {"quote_id": qid, "sent_to_contact_id": r["contact_id"], "sent_to": to["email"], "channel": "email", "language": r["language"], "deadline": deadline, "sent_by": by, "sent_at": now, "message_id": mid or ""})
    await db.events.update_one(ctx.q({"id": q.get("event_id")}), {"$push": {"history": {"at": now, "by": by, "action": "Devis", "detail": f"Relance urgente du devis {q['number']} envoyée à {to['email']}"}}})
    opp = await _crm(ctx.org_id, qid, f"Relance urgente du devis {q['number']} envoyée à {to['email']} par {by} (date limite {deadline}).")
    if opp.get("owner_id") and opp["owner_id"] != ctx.member.get("user_id"):
        await task(ctx.org_id, f"Relance urgente envoyée sur le devis {q['number']}", f"reminder:{qid}:{now[:10]}", opp["owner_id"], f"Envoyée par {by} à {to['email']}, date limite {deadline}.")
    return {"ok": True, "sent_to": to["email"], "deadline": deadline, "language": r["language"]}


# ---------- Entrepôts ----------
async def _wh_data(ctx: Ctx, body: WarehouseIn, cur: dict | None) -> dict:
    d = body.model_dump()
    if d["venue_id"]:
        await ctx.get("venues", d["venue_id"])
    if d["restricted_to_venue"] is None:
        d["restricted_to_venue"] = d["type"] == "site_client"
    if cur and cur.get("is_default"):
        if not d["active"]:
            raise HTTPException(400, "L'entrepôt par défaut ne peut pas être archivé : choisissez-en un autre d'abord")
        d["is_default"] = True
    if d["is_default"]:
        d["restricted_to_venue"] = False
        await db.warehouses.update_many(ctx.q({"id": {"$ne": (cur or {}).get("id", "")}}), {"$set": {"is_default": False}})
    return d


@router.get("/warehouses")
async def list_warehouses(ctx: Ctx = Depends(R)):
    w = await world(ctx.org_id)
    venues = {v["id"]: v["name"] for v in await ctx.list("venues")}
    out = []
    for x in w["whs"]:
        qs = [lv.get(x["id"], 0) for lv in w["levels"].values()]
        out.append({**x, "venue_name": venues.get(x.get("venue_id"), ""), "products": len([q for q in qs if q]), "units": sum(qs)})
    return out


@router.post("/warehouses")
async def create_warehouse(body: WarehouseIn, ctx: Ctx = Depends(WR)):
    await world(ctx.org_id)
    return await ctx.insert("warehouses", await _wh_data(ctx, body, None))


@router.put("/warehouses/{wid}")
async def update_warehouse(wid: str, body: WarehouseIn, ctx: Ctx = Depends(WR)):
    return await ctx.update("warehouses", wid, await _wh_data(ctx, body, await ctx.get("warehouses", wid)))


def _csv(header: list, rows: list, name: str) -> Response:
    buf = io.StringIO()
    wr = csv.writer(buf, delimiter=";")
    wr.writerow(header)
    wr.writerows(rows)
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/warehouses/{wid}/stock")
async def warehouse_stock(wid: str, format: str = "", ctx: Ctx = Depends(R)):
    wh, w = await ctx.get("warehouses", wid), await world(ctx.org_id)
    rows = sorted([{"product_id": pid, "ref": e.get("ref", ""), "name": e["name"], "category": e.get("category", ""), "stock_uom": e.get("stock_uom") or "piece", "secondary_uom": e.get("secondary_uom") or "", "qty_per_piece": e.get("qty_per_piece") or 0, "qty_on_hand": w["levels"].get(pid, {}).get(wid, 0), "maintenance": maint(w, pid).get(wid, 0)}
                   for pid, e in w["eqs"].items()], key=lambda r: (r["category"], r["ref"]))
    if format == "csv":
        return _csv(["Référence", "Produit", "Catégorie", "En stock", "Maintenance / HS"], [[r["ref"], r["name"], r["category"], r["qty_on_hand"], r["maintenance"]] for r in rows if r["qty_on_hand"]], f"inventaire-{wh['name']}.csv".replace(" ", "-"))
    return {"warehouse": wh, "rows": rows}


@router.get("/equipment/{eid}/stock")
async def product_stock(eid: str, start: str = "", end: str = "", warehouse_id: str = "", ctx: Ctx = Depends(R)):
    w, evs = await world(ctx.org_id), await _evs(ctx.org_id)
    eq = w["eqs"].get(eid)
    if not eq:
        raise HTTPException(404, "Introuvable")
    s = (start or datetime.now().strftime(FMT))[:16]
    e = (end or _shift(s, 1))[:16]
    mt, lv = maint(w, eid), w["levels"].get(eid, {})

    def rows(sp: tuple) -> list:
        res = reserved(w, evs, eid, sp)
        return [{"warehouse_id": x["id"], "name": x["name"], "on_hand": lv.get(x["id"], 0), "maintenance": mt.get(x["id"], 0), "reserved": res.get(x["id"], 0),
                 "available": lv.get(x["id"], 0) - mt.get(x["id"], 0) - res.get(x["id"], 0)} for x in w["whs"] if x.get("active", True) or lv.get(x["id"], 0)]
    cur = rows(buffered((s, e), eq))
    cal = []
    for i in range(30):
        d = _shift(f"{s[:10]}T00:00", i)[:10]
        cal.append({"day": d, "available": sum(r["available"] for r in rows((f"{d}T00:00", f"{d}T23:59")) if not warehouse_id or r["warehouse_id"] == warehouse_id)})
    transit = sum([m["qty"] async for m in db.stock_movements.find(ctx.q({"product_id": eid, "status": "in_transit"}), {"_id": 0})])
    return {"product": {"id": eid, "ref": eq.get("ref", ""), "name": eq["name"], "prep_days_before": eq.get("prep_days_before") or 0, "return_days_after": eq.get("return_days_after") or 0}, "start": s, "end": e,
            "warehouses": cur, "in_transit": transit, "total": {k: sum(r[k] for r in cur) for k in ("on_hand", "maintenance", "reserved", "available")}, "calendar": cal}


# ---------- Mouvements, transferts, inventaire, import ----------
@router.get("/stock/movements")
async def list_movements(product_id: str = "", warehouse_id: str = "", ctx: Ctx = Depends(R)):
    f: dict = {"product_id": product_id} if product_id else {}
    if warehouse_id:
        f["$or"] = [{"from_warehouse_id": warehouse_id}, {"to_warehouse_id": warehouse_id}]
    w = await world(ctx.org_id)
    rows = await ctx.list("stock_movements", f, sort=[("created_at", -1)], limit=500)
    for m in rows:
        m["product"] = (w["eqs"].get(m["product_id"]) or {}).get("name", "?")
        m["from_name"], m["to_name"] = (w["by"].get(m["from_warehouse_id"]) or {}).get("name", ""), (w["by"].get(m["to_warehouse_id"]) or {}).get("name", "")
        m["type_label"] = MOVES.get(m["type"], m["type"])
    return rows


class MoveIn(BaseModel):
    type: Literal["entree", "casse", "ajustement"]
    product_id: str
    warehouse_id: str
    qty: Qty
    note: str = Field("", max_length=300)


async def _refs(ctx: Ctx, pid: str, *wids: str) -> None:
    await world(ctx.org_id)
    await ctx.get("equipment", pid)
    for wid in wids:
        await ctx.get("warehouses", wid)


@router.post("/stock/movements")
async def add_movement(body: MoveIn, ctx: Ctx = Depends(WR)):
    if body.qty == 0 or (body.qty < 0 and body.type != "ajustement"):
        raise HTTPException(400, "Quantité invalide")
    await _refs(ctx, body.product_id, body.warehouse_id)
    check_whole(await ctx.get("equipment", body.product_id), body.qty)
    delta = -body.qty if body.type == "casse" else body.qty
    await bump(ctx.org_id, body.product_id, body.warehouse_id, delta)
    return await move(ctx.org_id, body.type, body.product_id, delta, frm=body.warehouse_id if delta < 0 else "", to=body.warehouse_id if delta > 0 else "", note=body.note, by=ctx.member.get("name"))


class TransferIn(BaseModel):
    product_id: str
    qty: Qty = Field(gt=0)
    from_warehouse_id: str
    to_warehouse_id: str
    in_transit: bool = False
    note: str = Field("", max_length=300)


@router.post("/stock/transfers")
async def transfer(body: TransferIn, ctx: Ctx = Depends(WR)):
    if body.from_warehouse_id == body.to_warehouse_id:
        raise HTTPException(400, "Choisissez deux entrepôts différents")
    await _refs(ctx, body.product_id, body.from_warehouse_id, body.to_warehouse_id)
    check_whole(await ctx.get("equipment", body.product_id), body.qty)
    await bump(ctx.org_id, body.product_id, body.from_warehouse_id, -body.qty)
    m = await move(ctx.org_id, "transfert", body.product_id, body.qty, body.from_warehouse_id, body.to_warehouse_id, note=body.note, by=ctx.member.get("name"), status="in_transit" if body.in_transit else "done")
    if body.in_transit:
        await sync_total(ctx.org_id, body.product_id)
    else:
        await bump(ctx.org_id, body.product_id, body.to_warehouse_id, body.qty)
    return m


@router.post("/stock/transfers/{mid}/receive")
async def receive(mid: str, ctx: Ctx = Depends(WR)):
    m = await db.stock_movements.find_one_and_update(ctx.q({"id": mid, "status": "in_transit"}), {"$set": {"status": "done", "received_at": now_iso()}}, projection={"_id": 0})
    if not m:
        raise HTTPException(404, "Introuvable")
    await bump(ctx.org_id, m["product_id"], m["to_warehouse_id"], m["qty"])
    return {"ok": True}


class Count(BaseModel):
    product_id: str
    counted: Qty = Field(ge=0)


class InventoryIn(BaseModel):
    warehouse_id: str
    counts: List[Count] = Field(max_length=2000)


@router.post("/stock/inventory")
async def inventory(body: InventoryIn, ctx: Ctx = Depends(WR)):
    await ctx.get("warehouses", body.warehouse_id)
    w, diffs = await world(ctx.org_id), []
    for c in body.counts:
        have = w["levels"].get(c.product_id, {}).get(body.warehouse_id, 0)
        if c.product_id in w["eqs"] and c.counted != have:
            await bump(ctx.org_id, c.product_id, body.warehouse_id, c.counted - have)
            await move(ctx.org_id, "ajustement", c.product_id, c.counted - have, to=body.warehouse_id, note=f"Inventaire : compté {c.counted}, théorique {have}", by=ctx.member.get("name"))
            diffs.append({"product_id": c.product_id, "name": w["eqs"][c.product_id]["name"], "expected": have, "counted": c.counted, "diff": c.counted - have})
    return {"adjusted": len(diffs), "diffs": diffs}


class ImportIn(BaseModel):
    text: str = Field(min_length=1, max_length=200000)


@router.post("/stock/import")
async def import_csv(body: ImportIn, ctx: Ctx = Depends(WR)):
    w, done, errors = await world(ctx.org_id), 0, []
    prods = {k.strip().lower(): e for e in w["eqs"].values() for k in (e.get("ref", ""), e["name"]) if k}
    whs = {x["name"].strip().lower(): x for x in w["whs"]}
    first = body.text.strip().splitlines()[0]
    for i, r in enumerate(csv.reader(io.StringIO(body.text.strip()), delimiter=";" if ";" in first else ","), 1):
        r = [x.strip() for x in r]
        if len(r) < 3 or not r[2].lstrip("-").isdigit():
            if i > 1 or len(r) < 3:
                errors.append(f"Ligne {i} : format attendu « référence ; entrepôt ; quantité »")
            continue
        e, wh, qty = prods.get(r[0].lower()), whs.get(r[1].lower()), int(r[2])
        if not e or not wh or qty < 0:
            errors.append(f"Ligne {i} : {'produit' if not e else 'entrepôt' if not wh else 'quantité'} inconnu(e) « {r[0] if not e else r[1] if not wh else r[2]} »")
            continue
        have = (await db.stock_levels.find_one(ctx.q({"product_id": e["id"], "warehouse_id": wh["id"]}), {"_id": 0}) or {}).get("qty_on_hand", 0)
        if qty != have:
            await bump(ctx.org_id, e["id"], wh["id"], qty - have)
            await move(ctx.org_id, "entree" if qty > have else "ajustement", e["id"], qty - have, to=wh["id"], note="Import CSV", by=ctx.member.get("name"))
        done += 1
    return {"imported": done, "errors": errors}


# ---------- Réglages ----------
class SettingsIn(BaseModel):
    stock_count_options: bool = False
    option_days: int = Field(7, ge=1, le=90)


@router.get("/stock/settings")
async def get_settings(ctx: Ctx = Depends(R)):
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "stock_count_options": 1, "option_days": 1}) or {}
    return {"stock_count_options": bool(org.get("stock_count_options")), "option_days": org.get("option_days") or 7}


@router.put("/stock/settings")
async def put_settings(body: SettingsIn, ctx: Ctx = Depends(need("org:write"))):
    await db.orgs.update_one({"id": ctx.org_id}, {"$set": body.model_dump()})
    return body.model_dump()


# ---------- Événement : origine du matériel et retours ----------
@router.get("/events/{eid}/origin")
async def origin(eid: str, ctx: Ctx = Depends(need("events:read"))):
    ev = await ctx.get("events", eid, ctx.event_scope())
    if ev.get("equipment") and ev.get("allocations") is None:
        await reallocate(ctx.org_id, eid)
        ev = await ctx.get("events", eid)
    w, venue, groups = await world(ctx.org_id), target(ev), {}
    rows = alloc_of(ev, w)
    for r in rows:
        eq, wh = w["eqs"].get(r["equipment_id"]) or {}, w["by"].get(r["warehouse_id"]) or {}
        g = groups.setdefault(r["warehouse_id"], {"warehouse_id": r["warehouse_id"], "name": wh.get("name", "?"), "fulfilment": r["fulfilment"], "lines": [], "weight_kg": 0, "volume_m3": 0})
        g["lines"].append({"equipment_id": r["equipment_id"], "ref": eq.get("ref", ""), "name": eq.get("name", "?"), "qty": r["qty"], "mode": r.get("mode", "auto"), "auto": bool(r.get("auto"))})
        g["weight_kg"] = round(g["weight_kg"] + r["qty"] * (eq.get("weight_kg") or 0), 1)
        g["volume_m3"] = round(g["volume_m3"] + r["qty"] * (eq.get("volume_m3") or 0), 2)
    lines, missing = [], []
    for l in ev.get("equipment", []):
        mine = [r for r in rows if r["equipment_id"] == l["equipment_id"] and not r.get("auto")]
        name = (w["eqs"].get(l["equipment_id"]) or {}).get("name", "?")
        lines.append({"equipment_id": l["equipment_id"], "name": name, "qty": l["qty"], "rows": [{"warehouse_id": r["warehouse_id"], "qty": r["qty"]} for r in mine], "mode": "manual" if any(r.get("mode") == "manual" for r in mine) else "auto"})
        if l["qty"] > sum(r["qty"] for r in mine):
            missing.append({"name": name, "missing": l["qty"] - sum(r["qty"] for r in mine)})
    dl = [g for g in groups.values() if g["fulfilment"] == "to_deliver"]
    return {"groups": sorted(groups.values(), key=lambda g: g["fulfilment"]), "lines": lines, "missing": missing, "note": ev.get("allocation_note", ""), "returned_at": ev.get("stock_returned_at"),
            "to_deliver": {"qty": sum(x["qty"] for g in dl for x in g["lines"]), "weight_kg": round(sum(g["weight_kg"] for g in dl), 1), "volume_m3": round(sum(g["volume_m3"] for g in dl), 2)},
            "all_on_site": bool(rows) and not dl and not missing, "warehouses": [{"id": x["id"], "name": x["name"]} for x in w["whs"] if x.get("active", True)],
            "has_depot": any(x.get("venue_id") == venue for x in w["whs"]) if venue else False, "suggestions": ["Sous-location / prestataire", "Produit de remplacement", "Réduire la quantité"] if missing else []}


class AllocRow(BaseModel):
    warehouse_id: str
    qty: Qty = Field(ge=0)


class AllocIn(BaseModel):
    equipment_id: str
    rows: List[AllocRow] = Field(max_length=30)


@router.put("/events/{eid}/allocations")
async def manual_alloc(eid: str, body: AllocIn, ctx: Ctx = Depends(need("events:write"))):
    ev, w = await ctx.get("events", eid), await world(ctx.org_id)
    line = next((l for l in ev.get("equipment", []) if l["equipment_id"] == body.equipment_id), None)
    if not line or any(r.warehouse_id not in w["by"] for r in body.rows) or sum(r.qty for r in body.rows) > line["qty"]:
        raise HTTPException(400, "Répartition invalide : le total ne peut pas dépasser la quantité de la ligne")
    venue = target(ev)
    rows = [r for r in alloc_of(ev, w) if r["equipment_id"] != body.equipment_id or r.get("auto")] + [{"equipment_id": body.equipment_id, "warehouse_id": r.warehouse_id, "qty": r.qty, "fulfilment": _ful(w["by"][r.warehouse_id], venue), "mode": "manual"} for r in body.rows if r.qty]
    await db.events.update_one(ctx.q({"id": eid}), {"$set": {"allocations": rows, "allocation_note": "Répartition manuelle enregistrée (non recalculée automatiquement)."}})
    return await origin(eid, ctx)


@router.post("/events/{eid}/allocations/recalc")
async def recalc(eid: str, ctx: Ctx = Depends(need("events:write"))):
    await ctx.get("events", eid)
    await reallocate(ctx.org_id, eid, reset=True)
    return await origin(eid, ctx)


class ReturnLine(BaseModel):
    equipment_id: str
    returned: Qty = Field(0, ge=0)
    damaged: Qty = Field(0, ge=0)


class ReturnIn(BaseModel):
    mode: Literal["origin", "leave_on_site"] = "origin"
    lines: List[ReturnLine] = Field(max_length=300)


@router.post("/events/{eid}/stock-return")
async def stock_return(eid: str, body: ReturnIn, ctx: Ctx = Depends(need("events:write"))):
    ev, w = await ctx.get("events", eid), await world(ctx.org_id)
    if ev.get("stock_returned_at"):
        raise HTTPException(409, "Le retour de stock a déjà été enregistré pour cet événement")
    depot = next((x for x in w["whs"] if x.get("active", True) and x.get("venue_id") and x["venue_id"] == target(ev)), None)
    if body.mode == "leave_on_site" and not depot:
        raise HTTPException(400, "Aucun dépôt n'est lié à ce lieu : créez-le dans Entrepôts & stocks")
    by, rows = ctx.member.get("name"), alloc_of(ev, w)
    for l in body.lines:
        back, broken = l.returned, l.damaged
        for r in [r for r in rows if r["equipment_id"] == l.equipment_id]:
            d = min(broken, r["qty"])
            if d:
                await bump(ctx.org_id, l.equipment_id, r["warehouse_id"], -d)
                await move(ctx.org_id, "casse", l.equipment_id, -d, frm=r["warehouse_id"], event_id=eid, note="Casse / perte au retour", by=by)
                broken -= d
            n = min(back, r["qty"] - d)
            if n:
                back -= n
                await move(ctx.org_id, "retour_evenement", l.equipment_id, n, to=depot["id"] if body.mode == "leave_on_site" else r["warehouse_id"], event_id=eid, by=by)
                if body.mode == "leave_on_site" and r["warehouse_id"] != depot["id"]:
                    await bump(ctx.org_id, l.equipment_id, r["warehouse_id"], -n)
                    await bump(ctx.org_id, l.equipment_id, depot["id"], n)
                    await move(ctx.org_id, "transfert", l.equipment_id, n, r["warehouse_id"], depot["id"], event_id=eid, note="Laissé sur place après l'événement", by=by)
    await db.events.update_one(ctx.q({"id": eid}), {"$set": {"stock_returned_at": now_iso(), "stock_return_mode": body.mode}, "$push": {"history": hist(ctx, "Stock", "Retour enregistré" + (" : matériel laissé sur place" if body.mode == "leave_on_site" else ""))}})
    return {"ok": True}
