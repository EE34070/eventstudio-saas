import math
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import routes_stock as rs
from core import Ctx, db, need, new_id, now_iso
from providers_core import distance_km
from routes_billing import LOAD_STATUSES, plus_days, today

from core import check_expiry, ensure_link, link_doc, link_limit  # noqa: E402,F401
from routes_units import Qty, ensure_whole  # noqa: E402

router = APIRouter(prefix="/api")
R, W = need("events:read"), need("events:write")
STATUSES = ["a_planifier", "planifiee", "chargee", "en_route", "livree", "retiree", "cloturee"]
TYPES = {"livraison": "Livraison / installation", "retrait": "Retrait / démontage", "transfert": "Transfert", "navette": "Navette"}
FEEDBACK = {"trois_quarts_vide": 0.25, "moitie": 0.5, "presque_plein": 0.9, "plein": 1.0, "pas_tenu": 1.15}
LIVE = LOAD_STATUSES + ["realise"]


# ---------- Capacités (matrice véhicule × matériel) ----------
async def caps(org_id: str) -> dict:
    return {(c["vehicle_id"], c["key"]): c["max_qty"] async for c in db.vehicle_capacities.find({"org_id": org_id}, {"_id": 0})}


def cap_for(c: dict, vid: str, eq: dict) -> float | None:
    return c.get((vid, eq.get("id"))) or c.get((vid, f"fam:{eq.get('category', '')}"))


@router.get("/logistics/capacities")
async def get_caps(ctx: Ctx = Depends(R)):
    eqs = await ctx.list("equipment", sort=[("category", 1), ("ref", 1)])
    return {"vehicles": [v for v in await ctx.list("vehicles", sort=[("name", 1)]) if v.get("active", True)],
            "products": [{"id": e["id"], "ref": e["ref"], "name": e["name"], "category": e.get("category", "")} for e in eqs],
            "families": sorted({e.get("category", "") for e in eqs if e.get("category")}),
            "cells": [{"vehicle_id": k[0], "key": k[1], "max_qty": v} for k, v in (await caps(ctx.org_id)).items()],
            "proposals": await ctx.list("load_observations", {"status": "proposed"}, sort=[("created_at", -1)], limit=50)}


class CapIn(BaseModel):
    vehicle_id: str
    key: str = Field(min_length=1, max_length=80)
    max_qty: Optional[float] = Field(None, ge=0)
    proposal_id: str = ""


@router.put("/logistics/capacities")
async def put_cap(body: CapIn, ctx: Ctx = Depends(need("catalog:write"))):
    await ctx.get("vehicles", body.vehicle_id)
    f = ctx.q({"vehicle_id": body.vehicle_id, "key": body.key})
    if not body.max_qty:
        await db.vehicle_capacities.update_one(f, {"$set": {"max_qty": 0, "source": "vide", "updated_at": now_iso()}}, upsert=True)
    else:
        await db.vehicle_capacities.update_one(f, {"$set": {"max_qty": body.max_qty, "source": "apprentissage" if body.proposal_id else "manuel", "updated_at": now_iso()}}, upsert=True)
    if body.proposal_id:
        await db.load_observations.update_one(ctx.q({"id": body.proposal_id}), {"$set": {"status": "applied"}})
    return {"ok": True}


# ---------- Trajets ----------
async def travel(org: dict, a: dict | None, b: dict | None) -> dict:
    if not a or not b or None in (a.get("lat"), a.get("lng"), b.get("lat"), b.get("lng")):
        return {"minutes": None, "km": None, "source": "Coordonnées GPS manquantes : trajet non calculé"}
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if key:
        try:
            async with httpx.AsyncClient(timeout=10) as cl:
                r = (await cl.get("https://maps.googleapis.com/maps/api/distancematrix/json", params={"origins": f"{a['lat']},{a['lng']}", "destinations": f"{b['lat']},{b['lng']}", "key": key})).json()
            el = r["rows"][0]["elements"][0]
            return {"minutes": round(el["duration"]["value"] / 60), "km": round(el["distance"]["value"] / 1000, 1), "source": "Google Maps"}
        except Exception:
            pass
    km = round((distance_km(a["lat"], a["lng"], b["lat"], b["lng"]) or 0) * 1.2, 1)
    speed = org.get("logistics_speed_kmh") or 50
    return {"minutes": round(km / speed * 60), "km": km, "source": f"Estimation : vol d'oiseau + 20 %, {speed} km/h (pas de clé Google Maps)"}


def _minus(day: str, hm: str, minutes: int) -> str:
    return (datetime.strptime(f"{day}T{hm or '08:00'}", "%Y-%m-%dT%H:%M") - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M")


# ---------- Missions ----------
def need_items(ev: dict, w: dict) -> dict:
    out: dict = {}
    for r in rs.alloc_of(ev, w):
        if r["fulfilment"] == "to_deliver":
            out[r["equipment_id"]] = out.get(r["equipment_id"], 0) + r["qty"]
    return out


def sync_items(m: dict, want: dict) -> list:
    notes, items = [], m["items"]
    for pid in {i["product_id"] for i in items} | set(want):
        cur, target = sum(i["qty"] for i in items if i["product_id"] == pid), want.get(pid, 0)
        if target > cur:
            _add(items, pid, target - cur, "", "manual")
            notes.append(f"+{target - cur} à placer")
        elif target < cur:
            left = cur - target
            for i in sorted([i for i in items if i["product_id"] == pid], key=lambda i: i["mv_id"] != ""):
                take = min(left, i["qty"])
                i["qty"], left = i["qty"] - take, left - take
            notes.append(f"-{cur - target} retiré(s)")
    m["items"] = [i for i in items if i["qty"] > 0]
    return notes


def _add(items: list, pid: str, qty: int, mv: str, placement: str) -> None:
    cur = next((i for i in items if i["product_id"] == pid and i["mv_id"] == mv), None)
    if cur:
        cur["qty"] += qty
        cur["placement"] = placement if placement == "random" else cur["placement"]
    else:
        items.append({"id": new_id(), "product_id": pid, "qty": qty, "mv_id": mv, "placement": placement, "verified": placement != "random", "loaded_qty": 0})


async def enrich(ctx: Ctx, ms: list, ev: dict | None = None) -> list:
    if not ms:
        return []
    c, w = await caps(ctx.org_id), await rs.world(ctx.org_id)
    veh = {v["id"]: v for v in await ctx.list("vehicles")}
    team = {t["id"]: t for t in await ctx.list("team")}
    venues = {v["id"]: v for v in await ctx.list("venues")}
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "logistics_speed_kmh": 1}) or {}
    days = await ctx.list("logistics_missions", {"date": {"$in": list({m["date"] for m in ms})}, "status": {"$ne": "cloturee"}})
    for m in ms:
        venue = venues.get(m.get("destination_venue_id")) or {}
        lg, alerts = venue.get("logistics") or {}, []
        for i in m["items"]:
            eq = w["eqs"].get(i["product_id"]) or {}
            i["name"], i["ref"], i["category"] = eq.get("name", "?"), eq.get("ref", ""), eq.get("category", "")
        for mv in m["vehicles"]:
            v = veh.get(mv["vehicle_id"]) or {}
            mv["name"], mv["plate"], fill, unm = v.get("name", "?") + (f" — rotation {mv['trip_index']}" if mv.get("trip_index", 1) > 1 else ""), v.get("plate", ""), 0.0, 0
            for i in [i for i in m["items"] if i["mv_id"] == mv["id"]]:
                cp = cap_for(c, mv["vehicle_id"], w["eqs"].get(i["product_id"]) or {})
                i["share_pct"] = round(i["qty"] / cp * 100, 1) if cp else None
                fill, unm = fill + (i["qty"] / cp if cp else 0), unm + (0 if cp else i["qty"])
            mv["fill_pct"], mv["unmeasured"] = round(fill * 100, 1), unm
            mv["drivers"] = [team[d]["name"] for d in mv.get("driver_ids", []) if d in team]
            if fill > 1.0001:
                alerts.append(f"{mv['name']} rempli à {mv['fill_pct']} % : déplacez du matériel, ajoutez un véhicule ou une 2ᵉ rotation (navette)")
            if lg.get("max_length_m") and (v.get("length_m") or 0) > lg["max_length_m"]:
                alerts.append(f"{mv['name']} trop long pour le lieu ({v['length_m']} m, maximum {lg['max_length_m']} m)")
            if lg.get("max_height_m") and (v.get("height_m") or 0) > lg["max_height_m"]:
                alerts.append(f"{mv['name']} trop haut pour le lieu ({v['height_m']} m, maximum {lg['max_height_m']} m)")
            if lg.get("tailgate_required") and not v.get("tailgate"):
                alerts.append(f"Hayon nécessaire sur ce lieu : {mv['name']} n'en a pas")
            if any(u["start"] <= m["date"] <= u["end"] for u in v.get("unavailabilities") or []):
                alerts.append(f"{mv['name']} est indisponible ce jour-là")
            lic = v.get("licence_required") or ""
            alerts += [f"{team[d]['name']} n'a pas le permis {lic} requis pour {mv['name']}" for d in mv.get("driver_ids", []) if d in team and lic and lic not in (team[d].get("licences") or [])]
            for o in days:
                if o["id"] != m["id"] and o["date"] == m["date"]:
                    if any(x["vehicle_id"] == mv["vehicle_id"] for x in o["vehicles"]):
                        alerts.append(f"{v.get('name', '?')} est déjà sur une autre mission ce jour-là")
                    alerts += [f"{team[d]['name']} est déjà sur une autre mission ce jour-là" for d in mv.get("driver_ids", []) if d in team and any(d in x.get("driver_ids", []) for x in o["vehicles"])]
        un = [i for i in m["items"] if not i["mv_id"]]
        if un and m["status"] != "a_planifier":
            alerts.append(f"{sum(i['qty'] for i in un)} article(s) encore « à placer »")
        if any(i["placement"] == "random" and not i.get("verified") for i in m["items"]):
            alerts.append("Placement aléatoire — à vérifier")
        m["alerts"], m["type_label"], m["venue_name"], m["venue"] = list(dict.fromkeys(alerts)), TYPES[m["type"]], venue.get("name", ""), {k: venue.get(k, "") for k in ("address", "zip", "city", "access_instructions")}
        m["contacts"] = [{k: x.get(k, "") for k in ("name", "role", "phone", "email")} for x in venue.get("onsite_contacts") or []]
        t = await travel(org, w["by"].get(m.get("origin_id")) or w["default"], venue)
        m["travel"] = t
        if t["minutes"] is not None and m.get("window_start"):
            m["depart_at"] = _minus(m["date"], m["window_start"], t["minutes"] + 15)
            m["load_start_at"] = _minus(m["date"], m["window_start"], t["minutes"] + 15 + (m.get("load_duration_min") or 45))
    return ms


async def _mission(ctx: Ctx, mid: str) -> dict:
    return await ctx.get("logistics_missions", mid)


async def _save(ctx: Ctx, m: dict, hist: str = "") -> dict:
    await db.logistics_missions.update_one(ctx.q({"id": m["id"]}), {"$set": {"items": [{k: i[k] for k in ("id", "product_id", "qty", "mv_id", "placement", "verified", "loaded_qty")} for i in m["items"]],
                                                                          "vehicles": [{k: v.get(k) for k in ("id", "vehicle_id", "trip_index", "driver_ids", "fill_feedback", "loaded_at")} for v in m["vehicles"]], "updated_at": now_iso()},
                                                                 **({"$push": {"history": {"at": now_iso(), "by": ctx.member.get("name"), "detail": hist}}} if hist else {})})
    return (await enrich(ctx, [await _mission(ctx, m["id"])]))[0]


async def generate(org_id: str, ev: dict, by: str = "Système") -> list:
    if ev.get("no_logistics"):
        return []
    w = await rs.world(org_id)
    want, notes = need_items(ev, w), []
    dw, pw = ev.get("delivery_window") or {}, ev.get("pickup_window") or {}
    cur = {m["type"]: m async for m in db.logistics_missions.find({"org_id": org_id, "event_id": ev["id"], "type": {"$in": ["livraison", "retrait"]}}, {"_id": 0})}
    if not want and not cur:
        return []
    venue = await db.venues.find_one({"org_id": org_id, "id": rs.target(ev)}, {"_id": 0}) or {}
    lg = venue.get("logistics") or {}
    for t, day, ws, we in (("livraison", (ev.get("setup_start") or ev["start"])[:10], dw.get("from") or lg.get("delivery_start") or (ev.get("setup_start") or ev["start"])[11:16], dw.get("to") or lg.get("delivery_end") or ""),
                           ("retrait", (ev.get("return_end") or ev["end"])[:10], pw.get("from") or lg.get("pickup_start") or (ev.get("return_end") or ev["end"])[11:16], pw.get("to") or lg.get("pickup_end") or "")):
        m = cur.get(t)
        if not m:
            m = {"id": new_id(), "org_id": org_id, "created_at": now_iso(), "event_id": ev["id"], "event_title": ev["title"], "event_code": ev["code"], "type": t, "date": day, "window_start": ws, "window_end": we,
                 "origin_type": "warehouse", "origin_id": w["default"]["id"], "destination_venue_id": rs.target(ev), "load_duration_min": 45, "status": "a_planifier", "vehicles": [], "items": [], "notes": "", "mute_reminders": False,
                 "history": [{"at": now_iso(), "by": by, "detail": "Mission créée"}]}
            sync_items(m, want)
            await db.logistics_missions.insert_one(dict(m))
            notes.append(f"{TYPES[t]} créée")
        elif m["status"] in ("a_planifier", "planifiee"):
            ch = sync_items(m, want)
            upd = {"items": m["items"], "destination_venue_id": rs.target(ev), **({"date": day} if m["date"] != day else {}), **({"window_start": ws, "window_end": we} if dw or pw else {})}
            if ch or m["date"] != day or ((dw or pw) and m.get("window_start") != ws) or m.get("destination_venue_id") != rs.target(ev):
                await db.logistics_missions.update_one({"org_id": org_id, "id": m["id"]}, {"$set": upd, "$push": {"history": {"at": now_iso(), "by": by, "detail": "Mise à jour depuis l'événement : " + (", ".join(ch) or "date / lieu")}}})
                notes.append(f"{TYPES[t]} : " + (", ".join(ch) or "date / lieu mis à jour"))
    return notes


@router.get("/events/{eid}/logistics")
async def event_logistics(eid: str, ctx: Ctx = Depends(R)):
    ev = await ctx.get("events", eid, ctx.event_scope())
    ms = await enrich(ctx, await ctx.list("logistics_missions", {"event_id": eid}, sort=[("date", 1)]))
    return {"missions": ms, "to_deliver": sum(need_items(ev, await rs.world(ctx.org_id)).values()), "vehicles": [v for v in await ctx.list("vehicles", sort=[("name", 1)]) if v.get("active", True)],
            "team": [{"id": t["id"], "name": t["name"], "licences": t.get("licences") or [], "is_driver": bool(t.get("is_driver"))} for t in await ctx.list("team", {"active": {"$ne": False}}, sort=[("name", 1)])], "statuses": STATUSES}


@router.post("/events/{eid}/logistics/generate")
async def generate_route(eid: str, ctx: Ctx = Depends(W)):
    notes = await generate(ctx.org_id, await ctx.get("events", eid), ctx.member.get("name"))
    return {**await event_logistics(eid, ctx), "message": " ; ".join(notes) or "Plan logistique à jour (aucun matériel « à livrer » à ajouter)"}


class MissionIn(BaseModel):
    type: Literal["transfert", "navette", "livraison", "retrait"]
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    window_start: str = ""
    notes: str = Field("", max_length=1000)


@router.post("/events/{eid}/logistics/missions")
async def add_mission(eid: str, body: MissionIn, ctx: Ctx = Depends(W)):
    ev, w = await ctx.get("events", eid), await rs.world(ctx.org_id)
    await ctx.insert("logistics_missions", {**body.model_dump(), "event_id": eid, "event_title": ev["title"], "event_code": ev["code"], "window_end": "", "origin_type": "warehouse", "origin_id": w["default"]["id"],
                                           "destination_venue_id": rs.target(ev), "load_duration_min": 45, "status": "a_planifier", "vehicles": [], "items": [], "mute_reminders": False, "history": []})
    return await event_logistics(eid, ctx)


class MissionPatch(BaseModel):
    date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    load_duration_min: Optional[int] = Field(None, ge=0, le=600)
    notes: Optional[str] = Field(None, max_length=1000)
    mute_reminders: Optional[bool] = None
    status: Optional[str] = None
    confirm: bool = False
    signed_by: Optional[str] = Field(None, max_length=120)


@router.patch("/logistics/missions/{mid}")
async def patch_mission(mid: str, body: MissionPatch, request: Request, ctx: Ctx = Depends(R)):
    m, d = await _mission(ctx, mid), body.model_dump(exclude_none=True, exclude={"confirm"})
    if set(d) - {"status", "signed_by"} and not ctx.can("events:write"):
        raise HTTPException(403, "Action non autorisée pour votre rôle")
    if "status" in d:
        if d["status"] not in STATUSES:
            raise HTTPException(400, "Statut inconnu")
        left = sum(i["qty"] for i in m["items"] if not i["mv_id"])
        if d["status"] == "planifiee" and left and not body.confirm:
            raise HTTPException(409, {"code": "unplaced", "message": f"{left} article(s) sont encore « à placer » : confirmez pour planifier quand même"})
    going = d.get("status") == "en_route" and m["status"] != "en_route"
    if going:
        d.update(await eta_fields(ctx.org_id, m))
    await db.logistics_missions.update_one(ctx.q({"id": mid}), {"$set": {**d, "updated_at": now_iso()}, "$push": {"history": {"at": now_iso(), "by": ctx.member.get("name"), "detail": f"Statut : {d['status']}" if "status" in d else "Modification"}}})
    if going:
        from routes_comms import base_url
        await run_rules(ctx.org_id, trigger="en_route", only=mid, base=base_url(request))
    return (await enrich(ctx, [await _mission(ctx, mid)]))[0]


class MvIn(BaseModel):
    vehicle_id: str
    driver_ids: List[str] = []


@router.post("/logistics/missions/{mid}/vehicles")
async def add_vehicle(mid: str, body: MvIn, ctx: Ctx = Depends(W)):
    m = await _mission(ctx, mid)
    await ctx.get("vehicles", body.vehicle_id)
    trip = len([v for v in m["vehicles"] if v["vehicle_id"] == body.vehicle_id]) + 1
    m["vehicles"].append({"id": new_id(), "vehicle_id": body.vehicle_id, "trip_index": trip, "driver_ids": body.driver_ids, "fill_feedback": "", "loaded_at": None})
    return await _save(ctx, m, "Véhicule ajouté")


@router.put("/logistics/missions/{mid}/vehicles/{mvid}")
async def set_drivers(mid: str, mvid: str, body: MvIn, ctx: Ctx = Depends(W)):
    m = await _mission(ctx, mid)
    for v in m["vehicles"]:
        if v["id"] == mvid:
            v["driver_ids"] = body.driver_ids
    return await _save(ctx, m, "Chauffeurs modifiés")


@router.delete("/logistics/missions/{mid}/vehicles/{mvid}")
async def remove_vehicle(mid: str, mvid: str, ctx: Ctx = Depends(W)):
    m = await _mission(ctx, mid)
    for i in [i for i in m["items"] if i["mv_id"] == mvid]:
        i["mv_id"] = ""
        _add(m["items"], i["product_id"], i["qty"], "", "manual")
        i["qty"] = 0
    m["items"] = [i for i in m["items"] if i["qty"] > 0]
    m["vehicles"] = [v for v in m["vehicles"] if v["id"] != mvid]
    return await _save(ctx, m, "Véhicule retiré : matériel renvoyé dans « à placer »")


class PlaceIn(BaseModel):
    product_id: str
    qty: Qty = Field(gt=0)
    from_mv: str = ""
    to_mv: str = ""
    verify: bool = False


def _move(m: dict, pid: str, qty: int, frm: str, to: str, placement: str = "manual") -> None:
    src = next((i for i in m["items"] if i["product_id"] == pid and i["mv_id"] == frm), None)
    if not src or src["qty"] < qty or (to and all(v["id"] != to for v in m["vehicles"])):
        raise HTTPException(400, "Déplacement impossible : quantité ou véhicule invalide")
    src["qty"] -= qty
    _add(m["items"], pid, qty, to, placement)
    m["items"] = [i for i in m["items"] if i["qty"] > 0]


@router.post("/logistics/missions/{mid}/place")
async def place(mid: str, body: PlaceIn, ctx: Ctx = Depends(W)):
    m = await _mission(ctx, mid)
    if body.verify:
        for i in m["items"]:
            if i["product_id"] == body.product_id and i["mv_id"] == body.from_mv:
                i["verified"], i["placement"] = True, "manual"
    elif body.from_mv != body.to_mv:
        await ensure_whole(ctx.org_id, body.product_id, body.qty)
        _move(m, body.product_id, body.qty, body.from_mv, body.to_mv)
    return await _save(ctx, m)


class AutoIn(BaseModel):
    mode: Literal["auto", "random", "clear"]


@router.post("/logistics/missions/{mid}/auto")
async def auto(mid: str, body: AutoIn, ctx: Ctx = Depends(W)):
    m = await _mission(ctx, mid)
    if body.mode == "clear":
        for i in list(m["items"]):
            if i["mv_id"]:
                _move(m, i["product_id"], i["qty"], i["mv_id"], "")
        return await _save(ctx, m, "Tout vidé")
    if not m["vehicles"]:
        raise HTTPException(400, "Ajoutez d'abord un véhicule")
    c, w = await caps(ctx.org_id), await rs.world(ctx.org_id)
    veh = {v["id"]: v for v in await ctx.list("vehicles")}
    order = sorted(m["vehicles"], key=lambda v: -((veh.get(v["vehicle_id"]) or {}).get("capacity_kg") or 0))

    def fill(mv: dict) -> float:
        return sum(i["qty"] / cp for i in m["items"] if i["mv_id"] == mv["id"] and (cp := cap_for(c, mv["vehicle_id"], w["eqs"].get(i["product_id"]) or {})))
    for i in [dict(i) for i in m["items"] if not i["mv_id"]]:
        left, eq = i["qty"], w["eqs"].get(i["product_id"]) or {}
        known = any(cap_for(c, v["vehicle_id"], eq) for v in order)
        if known and body.mode == "auto":
            for mv in order:
                cp = cap_for(c, mv["vehicle_id"], eq)
                take = min(left, math.floor((1 - fill(mv)) * cp + 1e-6)) if cp else 0
                if take > 0:
                    _move(m, i["product_id"], take, "", mv["id"], "auto")
                    left -= take
        elif not known or body.mode == "random":
            _move(m, i["product_id"], left, "", min(order, key=fill)["id"], "random")
    return await _save(ctx, m, "Répartition automatique" if body.mode == "auto" else "Reste réparti au hasard")


class FitIn(BaseModel):
    mv_id: str
    product_id: str
    qty: Qty = Field(gt=0)


@router.post("/logistics/missions/{mid}/wont-fit")
async def wont_fit(mid: str, body: FitIn, ctx: Ctx = Depends(R)):
    m = await _mission(ctx, mid)
    await ensure_whole(ctx.org_id, body.product_id, body.qty)
    _move(m, body.product_id, body.qty, body.mv_id, "")
    name = ((await rs.world(ctx.org_id))["eqs"].get(body.product_id) or {}).get("name", "matériel")
    await rs.task(ctx.org_id, f"Ne rentre pas : {body.qty} × {name} ({m.get('event_title', '')})", f"wontfit:{mid}:{body.product_id}:{now_iso()[:16]}", desc="Signalé au chargement : matériel renvoyé dans « à placer ».")
    return await _save(ctx, m, f"Ne rentre pas : {body.qty} × {name}")


class LoadedIn(BaseModel):
    feedback: Literal["", "trois_quarts_vide", "moitie", "presque_plein", "plein", "pas_tenu"] = ""


@router.post("/logistics/missions/{mid}/vehicles/{mvid}/loaded")
async def loaded(mid: str, mvid: str, body: LoadedIn, ctx: Ctx = Depends(R)):
    m = (await enrich(ctx, [await _mission(ctx, mid)]))[0]
    mv = next((v for v in m["vehicles"] if v["id"] == mvid), None)
    if not mv:
        raise HTTPException(404, "Introuvable")
    mv["fill_feedback"], mv["loaded_at"], props = body.feedback, now_iso(), []
    for i in m["items"]:
        if i["mv_id"] == mvid:
            i["loaded_qty"] = i["qty"]
    target, f = FEEDBACK.get(body.feedback), mv["fill_pct"] / 100
    if target and f > 0 and abs(f - target) > 0.05:
        c, w = await caps(ctx.org_id), await rs.world(ctx.org_id)
        for i in [i for i in m["items"] if i["mv_id"] == mvid]:
            cp = cap_for(c, mv["vehicle_id"], w["eqs"].get(i["product_id"]) or {})
            if cp:
                props.append(await ctx.insert("load_observations", {"mission_id": mid, "vehicle_id": mv["vehicle_id"], "vehicle_name": mv["name"], "key": i["product_id"], "product": i["name"], "current": cp,
                                                                    "proposed": max(1, round(cp * f / target)), "feedback": body.feedback, "computed_pct": mv["fill_pct"], "status": "proposed"}))
    if all(v.get("loaded_at") for v in m["vehicles"]) and m["status"] in ("a_planifier", "planifiee"):
        await db.logistics_missions.update_one(ctx.q({"id": mid}), {"$set": {"status": "chargee"}})
    return {"mission": await _save(ctx, m, f"Véhicule chargé ({body.feedback or 'sans appréciation'})"), "proposals": props}


# ---------- Jour, tournées, rotations, flotte ----------
@router.get("/logistics/day")
async def day_view(day: str = "", ctx: Ctx = Depends(R)):
    day = day or today()
    ids = [e["id"] for e in await ctx.list("events", ctx.event_scope())] if ctx.event_scope() else None
    ms = await enrich(ctx, await ctx.list("logistics_missions", {"date": day, **({"event_id": {"$in": ids}} if ids is not None else {})}, sort=[("window_start", 1)]))
    tours: dict = {}
    for m in ms:
        for mv in m["vehicles"] or [{"name": "Sans véhicule", "vehicle_id": ""}]:
            tours.setdefault(mv["name"], []).append({"mission_id": m["id"], "type_label": m["type_label"], "event_title": m.get("event_title", ""), "window_start": m.get("window_start", ""), "venue_name": m["venue_name"], "depart_at": m.get("depart_at", "")})
    soon, fleet = plus_days(today(), 30), []
    for v in await ctx.list("vehicles"):
        fleet += [{"vehicle": v["name"], "label": l, "date": v[k], "late": v[k] < today()} for k, l in (("ct_due", "Contrôle technique"), ("insurance_due", "Assurance"), ("service_due", "Entretien")) if v.get(k) and v[k] <= soon]
    return {"day": day, "missions": ms, "tours": [{"vehicle": k, "stops": sorted(v, key=lambda s: s["window_start"] or "99")} for k, v in tours.items()], "tour_note": "Ordre des arrêts par créneau d'arrivée (optimisation Google Directions non branchée).", "fleet_alerts": fleet}


@router.get("/logistics/rotations")
async def rotations(ctx: Ctx = Depends(R)):
    ms = await ctx.list("logistics_missions", {"date": {"$gte": today()}, "status": {"$in": ["a_planifier", "planifiee"]}}, sort=[("date", 1)])
    eqs, out = (await rs.world(ctx.org_id))["eqs"], []
    for a in [m for m in ms if m["type"] == "retrait"]:
        for b in [m for m in ms if m["type"] == "livraison" and m["event_id"] != a["event_id"] and a["date"] <= m["date"] <= plus_days(a["date"], 1) and (m["date"], m.get("window_start") or "") > (a["date"], a.get("window_start") or "")]:
            for pid in {i["product_id"] for i in a["items"]} & {i["product_id"] for i in b["items"]}:
                q = min(sum(i["qty"] for i in a["items"] if i["product_id"] == pid), sum(i["qty"] for i in b["items"] if i["product_id"] == pid))
                out.append({"from_mission_id": a["id"], "to_mission_id": b["id"], "product_id": pid, "qty": q, "text": f"{q} × {(eqs.get(pid) or {}).get('name', '?')} de « {a.get('event_title')} » (retrait le {a['date'][8:]}/{a['date'][5:7]} à {a.get('window_start') or '?'}) peuvent servir à « {b.get('event_title')} » (livraison le {b['date'][8:]}/{b['date'][5:7]} à {b.get('window_start') or '?'})"})
    return out


class RotationIn(BaseModel):
    from_mission_id: str
    to_mission_id: str
    product_id: str
    qty: Qty = Field(gt=0)


@router.post("/logistics/rotations")
async def accept_rotation(body: RotationIn, ctx: Ctx = Depends(W)):
    a, b = await _mission(ctx, body.from_mission_id), await _mission(ctx, body.to_mission_id)
    m = await ctx.insert("logistics_missions", {"event_id": b["event_id"], "event_title": b.get("event_title"), "event_code": b.get("event_code"), "type": "transfert", "date": a["date"], "window_start": a.get("window_start", ""), "window_end": "",
                                                "origin_type": "event", "origin_id": a["event_id"], "destination_venue_id": b.get("destination_venue_id"), "load_duration_min": 30, "status": "a_planifier", "vehicles": [],
                                                "items": [{"id": new_id(), "product_id": body.product_id, "qty": body.qty, "mv_id": "", "placement": "manual", "verified": True, "loaded_qty": 0}],
                                                "notes": f"Rotation directe depuis « {a.get('event_title')} » sans repasser par l'entrepôt.", "mute_reminders": True, "history": [{"at": now_iso(), "by": ctx.member.get("name"), "detail": "Rotation acceptée"}]})
    for x in (a, b):
        src = next((i for i in x["items"] if i["product_id"] == body.product_id and not i["mv_id"]), None)
        if src:
            src["qty"] = max(0, src["qty"] - body.qty)
            x["items"] = [i for i in x["items"] if i["qty"] > 0]
            await db.logistics_missions.update_one(ctx.q({"id": x["id"]}), {"$set": {"items": x["items"]}})
    return m


# ---------- Fiche logistique d'un lieu ----------
class VenueLogistics(BaseModel):
    delivery_address: str = Field("", max_length=300)
    access_hours: str = Field("", max_length=500)
    delivery_start: str = ""
    delivery_end: str = ""
    pickup_start: str = ""
    pickup_end: str = ""
    max_length_m: float = Field(0, ge=0)
    max_height_m: float = Field(0, ge=0)
    max_tonnage_t: float = Field(0, ge=0)
    tailgate_required: bool = False
    dock_distance_m: float = Field(0, ge=0)
    stairs: str = Field("", max_length=200)
    parking: str = Field("", max_length=300)
    gate_code: str = Field("", max_length=60)
    instructions: str = Field("", max_length=2000)
    preferred_channel: Literal["email", "whatsapp", "both"] = "email"
    reminders_off: bool = False


@router.put("/venues/{vid}/logistics")
async def put_venue_logistics(vid: str, body: VenueLogistics, ctx: Ctx = Depends(need("venues:write"))):
    return (await ctx.update("venues", vid, {"logistics": body.model_dump()})).get("logistics")


# ---------- Relances aux lieux ----------
DEFAULT_RULES = [("j7", "J-7 : annonce de la livraison", "livraison", 7, "email"), ("j1", "J-1 : rappel de la livraison", "livraison", 1, "whatsapp"), ("en_route", "En route", "en_route", 0, "whatsapp"), ("veille_retrait", "Veille du retrait", "retrait", 1, "whatsapp")]
TPL = {"fr": {"j7": ("Livraison prévue le {date} — {evenement}", "Nous livrerons le matériel de l'événement « {evenement} » à {lieu} le {date}, créneau {creneau}.\nMerci de nous confirmer les conditions d'accès.\nContact : {contact_EE}."),
              "j1": ("Rappel : livraison demain — {evenement}", "Notre équipe arrivera demain {date} vers {creneau} à {lieu}.\nVéhicule(s) : {vehicules} ({immatriculations}). Chauffeur : {chauffeur}."),
              "en_route": ("Notre équipe est en route — {evenement}", "Notre équipe est en route vers {lieu}.\nVéhicule(s) : {vehicules} ({immatriculations}). Chauffeur : {chauffeur}."),
              "veille_retrait": ("Retrait du matériel demain — {evenement}", "Nous viendrons retirer le matériel demain {date} vers {creneau} à {lieu}.\nVéhicule(s) : {vehicules}.")},
       "en": {"j7": ("Delivery scheduled on {date} — {evenement}", "We will deliver the equipment for “{evenement}” to {lieu} on {date}, time slot {creneau}.\nPlease confirm the access conditions.\nContact: {contact_EE}."),
              "j1": ("Reminder: delivery tomorrow — {evenement}", "Our team will arrive tomorrow {date} around {creneau} at {lieu}.\nVehicle(s): {vehicules} ({immatriculations}). Driver: {chauffeur}."),
              "en_route": ("Our team is on its way — {evenement}", "Our team is on its way to {lieu}.\nVehicle(s): {vehicules} ({immatriculations}). Driver: {chauffeur}."),
              "veille_retrait": ("Equipment pick-up tomorrow — {evenement}", "We will pick up the equipment tomorrow {date} around {creneau} at {lieu}.\nVehicle(s): {vehicules}.")}}


async def rules_of(org_id: str) -> list:
    saved = {r["key"]: r for r in (await db.orgs.find_one({"id": org_id}, {"_id": 0, "reminder_rules": 1}) or {}).get("reminder_rules") or []}
    return [{"key": k, "label": l, "trigger": t, "days": d, "channel": c, "mode": "draft", "active": True, **{x: saved[k][x] for x in ("channel", "mode", "active", "days") if k in saved and x in saved[k]}} for k, l, t, d, c in DEFAULT_RULES]


async def _deliver(org_id: str, log: dict) -> dict:
    from emailer import mail_html, send_email
    org = await db.orgs.find_one({"id": org_id}, {"_id": 0, "name": 1}) or {}
    upd = {"fallback": "WhatsApp non configuré : envoi par e-mail de repli" if log["channel"] != "email" else ""}
    try:
        upd["message_id"] = await send_email(to=log["to"], subject=log["subject"], html=mail_html(org.get("name", ""), log["greeting"], [p for p in log["body"].split("\n") if p.strip()], None, log["language"])) or ""
        upd.update(status="sent", sent_at=now_iso(), error="")
    except Exception as e:
        upd.update(status="failed", error=str(getattr(e, "detail", e))[:200])
    await db.reminder_logs.update_one({"org_id": org_id, "id": log["id"]}, {"$set": upd})
    return {**log, **upd}


async def run_rules(org_id: str, trigger: str = "", only: str = "", base: str = "") -> int:
    rules, day, n = [r for r in await rules_of(org_id) if r["active"]], today(), 0
    org = await db.orgs.find_one({"id": org_id}, {"_id": 0, "name": 1, "email": 1, "phone": 1}) or {}
    f = {"org_id": org_id, "mute_reminders": {"$ne": True}, "status": {"$nin": ["cloturee"]}, **({"id": only} if only else {"date": {"$gte": day, "$lte": plus_days(day, 30)}})}
    async for m in db.logistics_missions.find(f, {"_id": 0}):
        ev = await db.events.find_one({"org_id": org_id, "id": m["event_id"]}, {"_id": 0, "status": 1, "title": 1}) or {}
        venue = await db.venues.find_one({"org_id": org_id, "id": m.get("destination_venue_id")}, {"_id": 0}) or {}
        lg = venue.get("logistics") or {}
        if ev.get("status") not in LIVE or lg.get("reminders_off"):
            continue
        to = next((c for c in sorted(venue.get("onsite_contacts") or [], key=lambda c: not c.get("is_primary")) if c.get("email")), None)
        for r in rules:
            hit = (trigger == "en_route" and r["trigger"] == "en_route") or (not trigger and r["trigger"] == m["type"] and plus_days(day, r["days"]) == m["date"])
            if not hit or not to or await db.reminder_logs.find_one({"org_id": org_id, "mission_id": m["id"], "rule": r["key"]}):
                continue
            veh = [v async for v in db.vehicles.find({"org_id": org_id, "id": {"$in": [x["vehicle_id"] for x in m["vehicles"]]}}, {"_id": 0})]
            drivers = [t async for t in db.team.find({"org_id": org_id, "id": {"$in": [d for x in m["vehicles"] for d in x.get("driver_ids", [])]}}, {"_id": 0})]
            lang = to.get("language") or "fr-FR"
            k = "en" if lang.startswith("en") else "fr"
            vals = defaultdict(lambda: "—", lieu=venue.get("name", ""), evenement=ev.get("title", ""), date=f"{m['date'][8:]}/{m['date'][5:7]}/{m['date'][:4]}", creneau=" – ".join(filter(None, [m.get("window_start"), m.get("window_end")])) or "—",
                               vehicules=", ".join(v["name"] for v in veh) or "—", immatriculations=", ".join(v.get("plate") or "—" for v in veh) or "—", chauffeur=", ".join(t["name"] for t in drivers) or "—",
                               contact_EE=" · ".join(filter(None, [org.get("name"), org.get("phone"), org.get("email")])))
            url = await track_url(org_id, m, base) if r["key"] in ("j1", "en_route") else ""
            link = (("\nTrack the delivery: " if k == "en" else "\nSuivi de la livraison : ") + url) if url else ""
            log = {"id": new_id(), "org_id": org_id, "created_at": now_iso(), "mission_id": m["id"], "event_id": m["event_id"], "rule": r["key"], "rule_label": r["label"], "to": to["email"], "to_name": to.get("name", ""), "channel": r["channel"],
                   "language": lang, "greeting": ("Hello" if k == "en" else "Bonjour") + (f" {to['name']}," if to.get("name") else ","), "subject": TPL[k][r["key"]][0].format_map(vals), "body": TPL[k][r["key"]][1].format_map(vals) + link, "status": "draft", "fallback": "", "error": ""}
            await db.reminder_logs.insert_one(dict(log))
            n += 1
            if r["mode"] == "auto":
                await _deliver(org_id, log)
    return n


@router.get("/logistics/reminders")
async def reminders(ctx: Ctx = Depends(R)):
    return {"rules": await rules_of(ctx.org_id), "logs": await ctx.list("reminder_logs", sort=[("created_at", -1)], limit=200), "whatsapp": False, "variables": ["{lieu}", "{evenement}", "{date}", "{creneau}", "{vehicules}", "{immatriculations}", "{chauffeur}", "{contact_EE}"]}


class RuleIn(BaseModel):
    key: str
    channel: Literal["email", "whatsapp", "both"] = "email"
    mode: Literal["draft", "auto"] = "draft"
    active: bool = True
    days: int = Field(1, ge=0, le=60)


class RulesIn(BaseModel):
    rules: List[RuleIn]


@router.put("/logistics/reminders/rules")
async def put_rules(body: RulesIn, ctx: Ctx = Depends(need("org:write"))):
    await db.orgs.update_one({"id": ctx.org_id}, {"$set": {"reminder_rules": [r.model_dump() for r in body.rules]}})
    return await rules_of(ctx.org_id)


@router.post("/logistics/reminders/run")
async def run_now(request: Request, ctx: Ctx = Depends(W)):
    from routes_comms import base_url
    return {"created": await run_rules(ctx.org_id, base=base_url(request))}


class LogPatch(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=3000)


@router.post("/logistics/reminders/{lid}/send")
async def send_reminder(lid: str, body: LogPatch, ctx: Ctx = Depends(W)):
    log = await ctx.get("reminder_logs", lid)
    if log["status"] == "sent":
        raise HTTPException(409, "Cette relance a déjà été envoyée")
    out = await _deliver(ctx.org_id, {**log, **body.model_dump()})
    await db.reminder_logs.update_one(ctx.q({"id": lid}), {"$set": {**body.model_dump(), "sent_by": ctx.member.get("name")}})
    if out["status"] == "failed":
        raise HTTPException(502, {"code": "reminder_failed", "message": f"La relance n'a pas pu être envoyée : {out['error']}. Elle reste en brouillon, vous pouvez réessayer."})
    return out


@router.delete("/logistics/reminders/{lid}")
async def cancel_reminder(lid: str, ctx: Ctx = Depends(W)):
    await ctx.update("reminder_logs", lid, {"status": "cancelled"})
    return {"ok": True}


# ---------- Automatismes ----------
async def tick() -> None:
    day = today()
    async for org in db.orgs.find({}, {"_id": 0, "id": 1}):
        oid = org["id"]
        async for ev in db.events.find({"org_id": oid, "status": {"$in": LOAD_STATUSES}, "equipment.0": {"$exists": True}, "setup_start": {"$gte": day, "$lte": plus_days(day, 10) + "T23:59"}}, {"_id": 0, "history": 0}):
            if not await db.logistics_missions.find_one({"org_id": oid, "event_id": ev["id"]}) and await generate(oid, ev):
                await rs.task(oid, f"Planifier la logistique de {ev['title']}", f"logistics:{ev['id']}")
        async for m in db.logistics_missions.find({"org_id": oid, "date": {"$gte": day, "$lte": plus_days(day, 3)}, "status": {"$in": ["a_planifier", "planifiee"]}}, {"_id": 0}):
            pb = [t for t, bad in (("véhicule manquant", not m["vehicles"]), ("chauffeur manquant", any(not v.get("driver_ids") for v in m["vehicles"])), ("matériel « à placer »", any(not i["mv_id"] for i in m["items"])),
                                   ("placement aléatoire non vérifié", any(i["placement"] == "random" and not i.get("verified") for i in m["items"]))) if bad]
            if pb and m["items"]:
                await rs.task(oid, f"Logistique J-3 : {m.get('event_title', '')} ({TYPES[m['type']]})", f"logj3:{m['id']}", desc="À régler : " + ", ".join(pb) + ".")
        await run_rules(oid)


# ---------- Check-list, photos, signature, suivi public ----------
import secrets  # noqa: E402

from fastapi import File, Request, UploadFile  # noqa: E402

PUBLIC_STATUS = {"a_planifier": "En préparation", "planifiee": "Planifiée", "chargee": "Véhicule chargé", "en_route": "En route", "livree": "Livrée", "retiree": "Matériel retiré", "cloturee": "Terminée"}


async def track_url(org_id: str, m: dict, base: str = "") -> str:
    base = (os.environ.get("APP_URL") or base or "").rstrip("/")
    if not base:
        return ""
    return f"{base}/suivi/{await ensure_link('logistics_missions', m)}"


async def eta_fields(org_id: str, m: dict) -> dict:
    from routes_delivery import PARIS
    w = await rs.world(org_id)
    venue = await db.venues.find_one({"org_id": org_id, "id": m.get("destination_venue_id")}, {"_id": 0})
    org = await db.orgs.find_one({"id": org_id}, {"_id": 0, "logistics_speed_kmh": 1}) or {}
    t, now = await travel(org, w["by"].get(m.get("origin_id")) or w["default"], venue), datetime.now(PARIS)
    return {"en_route_at": now.strftime("%Y-%m-%dT%H:%M"), "eta": (now + timedelta(minutes=t["minutes"])).strftime("%Y-%m-%dT%H:%M") if t["minutes"] is not None else "", "eta_source": t["source"]}


@router.get("/logistics/missions/{mid}/tracking-link")
async def tracking_link(mid: str, request: Request, ctx: Ctx = Depends(R)):
    from routes_comms import base_url
    return {"url": await track_url(ctx.org_id, await _mission(ctx, mid), base_url(request))}


@router.get("/public/tracking/{token}")
async def public_tracking(token: str):
    m = await link_doc("logistics_missions", token)
    if not m:
        raise HTTPException(404, "Lien de suivi introuvable")
    oid = m["org_id"]
    org = await db.orgs.find_one({"id": oid}, {"_id": 0, "name": 1}) or {}
    venue = await db.venues.find_one({"org_id": oid, "id": m.get("destination_venue_id")}, {"_id": 0, "name": 1}) or {}
    veh = {v["id"]: v async for v in db.vehicles.find({"org_id": oid, "id": {"$in": [x["vehicle_id"] for x in m["vehicles"]]}}, {"_id": 0})}
    team = [t async for t in db.team.find({"org_id": oid, "id": {"$in": [d for x in m["vehicles"] for d in x.get("driver_ids", [])]}}, {"_id": 0})]
    eqs = {e["id"]: e["name"] async for e in db.equipment.find({"org_id": oid, "id": {"$in": [i["product_id"] for i in m["items"]]}}, {"_id": 0, "id": 1, "name": 1})}
    items: dict = {}
    for i in m["items"]:
        items[i["product_id"]] = items.get(i["product_id"], 0) + i["qty"]
    return {"org": org.get("name", ""), "event": m.get("event_title", ""), "type_label": TYPES[m["type"]], "venue": venue.get("name", ""), "date": m["date"], "window_start": m.get("window_start", ""), "window_end": m.get("window_end", ""),
            "status": m["status"], "status_label": PUBLIC_STATUS[m["status"]], "eta": m.get("eta", "") if m["status"] == "en_route" else "", "en_route_at": m.get("en_route_at", ""),
            "vehicles": [{"name": (veh.get(x["vehicle_id"]) or {}).get("name", ""), "plate": (veh.get(x["vehicle_id"]) or {}).get("plate", "")} for x in m["vehicles"]],
            "drivers": [{"first_name": (t.get("name") or "").split(" ")[0], "phone": t.get("phone", "")} for t in team],
            "items": [{"qty": q, "name": eqs.get(pid, "Matériel")} for pid, q in items.items()], "signed_at": m.get("signed_at", "")}


class ItemCheck(BaseModel):
    loaded_qty: Qty = Field(ge=0)


@router.patch("/logistics/missions/{mid}/items/{iid}")
async def check_item(mid: str, iid: str, body: ItemCheck, ctx: Ctx = Depends(R)):
    m = await _mission(ctx, mid)
    for i in m["items"]:
        if i["id"] == iid:
            i["loaded_qty"] = min(body.loaded_qty, i["qty"])
    return await _save(ctx, m)


@router.post("/logistics/missions/{mid}/photos")
async def mission_photo(mid: str, file: UploadFile = File(...), ctx: Ctx = Depends(R)):
    from routes_files import read_upload, store_bytes
    m = await _mission(ctx, mid)
    data, ctype = await read_upload(file)
    if not ctype.startswith("image/") or m.get("signed_at") or len(m.get("photos") or []) >= 12:
        raise HTTPException(400, "Seules les photos sont acceptées (12 maximum, avant signature)")
    ref = await store_bytes(ctx.org_id, data, ctype, f"mission-{m.get('event_code', '')}", ctx.member.get("name"))
    await db.logistics_missions.update_one(ctx.q({"id": mid}), {"$push": {"photos": ref}})
    return (await enrich(ctx, [await _mission(ctx, mid)]))[0]


@router.post("/logistics/missions/{mid}/sign")
async def mission_sign(mid: str, request: Request, ctx: Ctx = Depends(R)):
    from routes_delivery import PARIS, SignIn, _signature_png, bon_pdf
    from routes_files import file_bytes, store_bytes
    body = SignIn(**await request.json())
    m = (await enrich(ctx, [await _mission(ctx, mid)]))[0]
    if m.get("signed_at"):
        raise HTTPException(409, "Ce bon est déjà signé")
    sig, signed_at, by = _signature_png(body.signature), datetime.now(PARIS).strftime("%Y-%m-%dT%H:%M"), ctx.member.get("name")
    ev = await db.events.find_one(ctx.q({"id": m["event_id"]}), {"_id": 0, "language": 1}) or {}
    lines: dict = {}
    for i in m["items"]:
        lines.setdefault(i["product_id"], {"ref": i["ref"], "name": i["name"], "section": m["type_label"], "qty": 0})["qty"] += i["qty"]
    d = {"language": ev.get("language") or "fr-FR", "event_code": m.get("event_code", ""), "event_title": m.get("event_title", ""), "day": m["date"], "client_name": "", "venue": {"name": m["venue_name"], **m["venue"]}, "lines": list(lines.values())}
    photos = [g[0] for g in [await file_bytes(ctx.org_id, p) for p in m.get("photos") or []] if g]
    pdf = bon_pdf(d, await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}), body.signer_name.strip(), body.notes.strip(), signed_at, sig, photos)
    upd = {"status": "retiree" if m["type"] == "retrait" else "livree", "signer_name": body.signer_name.strip(), "sign_notes": body.notes.strip(), "signed_at": signed_at, "delivered_by": by,
           "bon_file": await store_bytes(ctx.org_id, pdf, "application/pdf", f"BL-{m.get('event_code', '')}-{m['type']}.pdf", by)}
    r = await db.logistics_missions.update_one(ctx.q({"id": mid, "signed_at": {"$in": [None, ""]}}), {"$set": upd, "$push": {"history": {"at": now_iso(), "by": by, "detail": f"Bon signé par {upd['signer_name']}"}}})
    if not r.matched_count:
        raise HTTPException(409, "Ce bon est déjà signé")
    await db.events.update_one(ctx.q({"id": m["event_id"]}), {"$push": {"history": {"at": now_iso(), "by": by, "action": "Livraison", "detail": f"{m['type_label']} signée par {upd['signer_name']}" + (f" — réserves : {upd['sign_notes']}" if upd["sign_notes"] else "")}}})
    return (await enrich(ctx, [await _mission(ctx, mid)]))[0]
