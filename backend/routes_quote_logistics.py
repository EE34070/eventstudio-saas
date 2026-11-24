"""Devis : réglages de tarification et trajets (livraison / retrait). Les trajets génèrent des lignes de devis synchronisées ; coût et distance restent internes."""
import os
from typing import Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

import routes_logistics as lg
import routes_quote_blocks as qb
import routes_stock as rs
import routes_supplier_quotes as sq
from core import Ctx, db, need, new_id, now_iso
from routes_billing import _editable_quote, quote_writer

router = APIRouter(prefix="/api")
FIN = need("finance:read")
r2 = lambda x: round(x or 0, 2)  # noqa: E731


class Zone(BaseModel):
    max_km: float = Field(gt=0, le=2000)
    price: float = Field(ge=0)


class Surcharges(BaseModel):
    night_start: str = Field("22:00", pattern=r"^\d{2}:\d{2}$")
    night_end: str = Field("06:00", pattern=r"^\d{2}:\d{2}$")
    night_pct: float = Field(25, ge=0, le=300)
    sunday_pct: float = Field(50, ge=0, le=300)
    holiday_pct: float = Field(100, ge=0, le=300)
    cumulative: bool = False


class PricingIn(BaseModel):
    transport_mode: Literal["zone", "computed", "manual"] = "zone"
    zone_grid: Dict[Literal["utilitaire", "camion"], List[Zone]] = {"utilitaire": [Zone(max_km=30, price=90), Zone(max_km=60, price=150), Zone(max_km=100, price=220), Zone(max_km=150, price=320)],
                                                                    "camion": [Zone(max_km=30, price=126), Zone(max_km=60, price=210), Zone(max_km=100, price=308), Zone(max_km=150, price=448)]}
    vehicle_flat_fee: float = Field(60, ge=0)
    client_rate_per_km: Dict[Literal["utilitaire", "camion"], float] = {"utilitaire": 0.9, "camion": 1.3}
    shift_lengths: List[float] = Field([4, 8, 12], max_length=6)
    surcharges: Surcharges = Surcharges()
    employer_charge_coef: Dict[str, float] = {"cddu": 1.65, "cdd": 1.5, "cdi": 1.45, "alternance": 1.15}
    overnight_distance_km: float = Field(150, ge=0)
    overnight_end_hour: str = Field("01:00", pattern=r"^\d{2}:\d{2}$")
    overnight_return_minutes: int = Field(90, ge=0)
    lodging_default: float = Field(95, ge=0)
    meal_default: float = Field(20, ge=0)
    labor_grid: Dict[str, dict] = {"technicien_son": {"label": "Technicien son", "cost_hour": 28, "price_hour": 45}, "technicien_lumiere": {"label": "Technicien lumière", "cost_hour": 28, "price_hour": 45},
                                   "regisseur": {"label": "Régisseur", "cost_hour": 35, "price_hour": 55}, "manutentionnaire": {"label": "Manutentionnaire", "cost_hour": 22, "price_hour": 35},
                                   "chauffeur": {"label": "Chauffeur", "cost_hour": 22, "price_hour": 35}, "autre": {"label": "Intervenant", "cost_hour": 25, "price_hour": 40}}
    logistics_section: str = Field("Logistique & installation", min_length=1, max_length=80)


async def pricing_of(org_id: str) -> dict:
    org = await db.orgs.find_one({"id": org_id}, {"_id": 0, "pricing": 1}) or {}
    import social_core as sc
    out = {**PricingIn().model_dump(), **(org.get("pricing") or {})}
    coef = (await sc.params_at(org_id, sc.today()))["coef"]
    out["employer_charge_coef"] = {k: float(coef.get(k, v)) for k, v in out["employer_charge_coef"].items()}
    return out


@router.get("/pricing-settings")
async def get_pricing(ctx: Ctx = Depends(FIN)):
    return await pricing_of(ctx.org_id)


@router.put("/pricing-settings")
async def put_pricing(body: PricingIn, ctx: Ctx = Depends(need("org:write"))):
    d = body.model_dump()
    for g in d["zone_grid"].values():
        g.sort(key=lambda z: z["max_km"])
    await db.orgs.update_one({"id": ctx.org_id}, {"$set": {"pricing": d}})
    return d


# ---------- Trajets ----------
class TripVehicle(BaseModel):
    vehicle_id: str = ""
    rental_label: str = Field("", max_length=80)
    rental_cost_ht: float = Field(0, ge=0)
    rental_volume_m3: float = Field(0, ge=0)
    rental_capacity_kg: float = Field(0, ge=0)


class Trip(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    type: Literal["delivery", "pickup", "extra"] = "extra"
    active: bool = True
    title: str = Field("", max_length=120)
    date: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    slot_start: str = Field("", pattern=r"^(\d{2}:\d{2})?$")
    slot_end: str = Field("", pattern=r"^(\d{2}:\d{2})?$")
    origin_id: str = ""
    vehicles: Optional[List[TripVehicle]] = Field(None, max_length=8)
    distance_manual: bool = False
    distance_km_rt: float = Field(0, ge=0, le=10000)
    tolls_ht: float = Field(0, ge=0)
    pricing_mode: Literal["", "zone", "computed", "manual"] = ""
    price_ht: float = Field(0, ge=0)


class Labor(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    role: str = Field("autre", max_length=40)
    headcount: int = Field(1, ge=1, le=50)
    phase: Literal["delivery", "operation", "pickup", "custom"] = "operation"
    date: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    start: str = Field("", pattern=r"^(\d{2}:\d{2})?$")
    end: str = Field("", pattern=r"^(\d{2}:\d{2})?$")
    hours: float = Field(0, ge=0, le=72)
    unit: Literal["hour", "shift", "day", "flat"] = "shift"
    cost_source: Literal["employee", "provider", "average"] = "average"
    contract: str = Field("cddu", max_length=20)
    gross_hour: float = Field(0, ge=0, le=1000)
    provider_rate: float = Field(0, ge=0, le=100000)
    unit_price_ht: float = Field(0, ge=0, le=1000000)
    trip_id: str = Field("", max_length=64)


class Expense(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    type: Literal["lodging", "meal", "toll", "parking", "train", "plane", "other"] = "lodging"
    label: str = Field("", max_length=120)
    persons: int = Field(1, ge=1, le=200)
    qty: float = Field(1, ge=0, le=1000)
    unit_cost_ht: float = Field(0, ge=0, le=100000)
    unit_price_ht: float = Field(0, ge=0, le=100000)
    mode: Literal["included", "flat", "actual", "client_provided"] = "flat"
    vat_rate: float = Field(20, ge=0, le=100)
    debours: bool = False
    note: str = Field("", max_length=300)


COST_KEYS = {"labor": ("cost_source", "contract", "gross_hour", "provider_rate"), "expenses": ("unit_cost_ht",)}
PHASES = {"delivery": "installation", "operation": "exploitation", "pickup": "démontage", "custom": ""}
EXP = {"lodging": "Nuitée", "meal": "Repas", "toll": "Péages", "parking": "Parking", "train": "Train", "plane": "Avion", "other": "Frais"}


def span(it: dict, dates: dict | None):
    from datetime import datetime, timedelta
    d = dates or {}
    if it["phase"] == "operation":
        a, b = (d.get("operation") or {}).get("start", ""), (d.get("operation") or {}).get("end", "")
    else:
        x = (d.get(it["phase"]) or {}) if it["phase"] != "custom" else it
        a, b = (f"{x.get('date')}T{x.get('start')}" if x.get("date") and x.get("start") else ""), (f"{x.get('date')}T{x.get('end')}" if x.get("date") and x.get("end") else "")
    if not a:
        return None
    a = datetime.fromisoformat(a[:16])
    b = datetime.fromisoformat(b[:16]) if b else a + timedelta(hours=4)
    if b <= a:
        b += timedelta(days=1)
    return (a, a + timedelta(hours=it["hours"])) if it.get("hours") else (a, b)


def surcharge(a, b, r: dict) -> tuple:
    from datetime import timedelta
    from routes_contracts import holidays
    t, tot, n, hit = a, 0.0, 0, {"nuit": 0, "dimanche": 0, "férié": 0}
    while t < b:
        hm = t.strftime("%H:%M")
        ps = {"nuit": r["night_pct"] if (hm >= r["night_start"] or hm < r["night_end"]) else 0, "dimanche": r["sunday_pct"] if t.weekday() == 6 else 0, "férié": r["holiday_pct"] if t.date() in holidays(t.year) else 0}
        for k, v in ps.items():
            hit[k] += 0.25 if v else 0
        tot += sum(ps.values()) if r["cumulative"] else max(ps.values())
        n += 1
        t += timedelta(minutes=15)
    return 1 + (tot / n / 100 if n else 0), ", ".join(f"{v:g} h {k}" for k, v in hit.items() if v)


def labor_rows(items: list, dates: dict | None, st: dict) -> list:
    out = []
    for it in items:
        g = st["labor_grid"].get(it["role"]) or st["labor_grid"]["autre"]
        sp = span(it, dates)
        hours = (sp[1] - sp[0]).total_seconds() / 3600 if sp else (it.get("hours") or 0)
        mult, note = surcharge(sp[0], sp[1], st["surcharges"]) if sp else (1, "")
        lens = sorted(st["shift_lengths"]) or [8]
        if it["unit"] == "shift":
            ln = next((x for x in lens if x >= hours), lens[-1])
            n = max(1, -(-hours // ln)) if hours else 1
            billed, qty = n * ln, f"{n:g} vacation{'s' if n > 1 else ''} de {ln:g} h"
        elif it["unit"] == "day":
            n = max(1, -(-hours // 8))
            billed, qty = n * 8, f"{n:g} jour{'s' if n > 1 else ''}"
        else:
            billed, qty = hours, f"{hours:g} h" if it["unit"] == "hour" else "forfait"
        price = it["unit_price_ht"] if it["unit"] == "flat" else g["price_hour"] * billed * mult
        cost = it["provider_rate"] if it["cost_source"] == "provider" else (it["gross_hour"] * st["employer_charge_coef"].get(it["contract"], 1.5) if it["cost_source"] == "employee" else g["cost_hour"]) * hours * mult
        w = g["label"].lower().split()
        w[0] += "s" if it["headcount"] > 1 else ""
        label = " — ".join(x for x in (f"{it['headcount']} {' '.join(w)}", PHASES[it["phase"]], qty) if x)
        out.append({**it, "start_at": sp[0].isoformat()[:16] if sp else "", "end_at": sp[1].isoformat()[:16] if sp else "", "computed_hours": round(hours, 2), "multiplier": round(mult, 4), "surcharge_note": note,
                    "price_ht": r2(price * it["headcount"]), "cost_ht": r2(cost * it["headcount"]), "client_label": label, "role_label": g["label"]})
    return out


def suggest(rows: list, one_way_km: float, minutes: float | None, st: dict) -> list:
    minutes = minutes if minutes is not None else one_way_km / 70 * 60
    nights = lunch = dinner = 0
    for r in rows:
        if not r["start_at"]:
            continue
        a, b = r["start_at"][11:], r["end_at"][11:]
        late = r["end_at"][:10] > r["start_at"][:10] or b < a
        if one_way_km > st["overnight_distance_km"] or (late and st["overnight_end_hour"] <= b < "08:00" and minutes > st["overnight_return_minutes"]):
            nights += r["headcount"]
        lunch += r["headcount"] if a <= "12:30" and (late or b >= "13:30") else 0
        dinner += r["headcount"] if (a <= "20:00" and (late or b >= "21:00")) or (late and a > "20:00") else 0
    mk = lambda t, label, n, c: Expense(id=new_id(), type=t, label=label, persons=n, qty=1, unit_cost_ht=c, unit_price_ht=c).model_dump()  # noqa: E731
    return ([mk("lodging", "Nuitée", nights, st["lodging_default"])] if nights else []) + ([mk("meal", "Repas du midi", lunch, st["meal_default"])] if lunch else []) + ([mk("meal", "Repas du soir", dinner, st["meal_default"])] if dinner else [])


def expense_lines(items: list, cc: bool) -> tuple:
    rows, lines = [], []
    tot = lambda xs, k: r2(sum(x["persons"] * x["qty"] * x[k] for x in xs))  # noqa: E731
    for e in items:
        rows.append({**e, "price_ht": 0 if e["mode"] in ("included", "client_provided") else tot([e], "unit_price_ht"), "cost_ht": 0 if e["mode"] == "client_provided" else tot([e], "unit_cost_ht")})
    mk = lambda sid, label, price, cost, vat: {"source_type": "expense", "source_id": sid, "kind": "expense", "label": label, "qty": 1, "unit_price": price, "vat": vat, **({"unit_cost": cost} if cc else {})}  # noqa: E731
    plain = [e for e in items if not e["debours"]]
    for mode, sid, label in (("flat", "expenses_flat", "Frais de déplacement et d'hébergement de l'équipe"), ("actual", "expenses_actual", "Frais de déplacement et d'hébergement de l'équipe (estimation, refacturé au réel sur justificatifs)")):
        xs = [e for e in plain if e["mode"] == mode]
        if xs:
            lines.append(mk(sid, label, tot(xs, "unit_price_ht"), tot(xs, "unit_cost_ht"), xs[0]["vat_rate"]))
    if any(e["mode"] == "client_provided" for e in items):
        lines.append(mk("expenses_client", "Hébergement / repas fournis par le client", 0, 0, 20))
    for e in items:
        if e["debours"] and e["mode"] in ("flat", "actual"):
            lines.append(mk(e["id"], f"{e['label'] or EXP[e['type']]} (débours, sans TVA)", tot([e], "unit_price_ht"), tot([e], "unit_cost_ht"), 0))
    inc = [e for e in items if e["mode"] == "included"]
    return rows, lines, tot(inc, "unit_cost_ht")


class QLine(BaseModel):
    equipment_id: str
    qty: float = Field(gt=0)


class TripsIn(BaseModel):
    trips: Optional[List[Trip]] = Field(None, max_length=12)
    lines: Optional[List[QLine]] = Field(None, max_length=600)
    dates: Optional[dict] = None
    display: Optional[Literal["detailed", "grouped"]] = None
    labor: Optional[List[Labor]] = Field(None, max_length=40)
    expenses: Optional[List[Expense]] = Field(None, max_length=40)
    labor_display: Optional[Literal["detailed", "grouped"]] = None
    show_weight: Optional[bool] = None


async def road(org: dict, a: dict | None, b: dict | None) -> dict:
    if not a or not b or None in (a.get("lat"), a.get("lng"), b.get("lat"), b.get("lng")):
        return {"km": None, "minutes": None, "source": "Coordonnées GPS manquantes : saisissez la distance"}
    if os.environ.get("GOOGLE_MAPS_API_KEY"):
        return await lg.travel(org, a, b)
    key = f"{a['lat']:.4f},{a['lng']:.4f};{b['lat']:.4f},{b['lng']:.4f}"
    hit = await db.route_cache.find_one({"key": key}, {"_id": 0})
    if hit:
        return hit
    try:
        async with httpx.AsyncClient(timeout=6) as cl:
            r = (await cl.get(f"https://router.project-osrm.org/route/v1/driving/{a['lng']},{a['lat']};{b['lng']},{b['lat']}", params={"overview": "false"})).json()
        out = {"key": key, "km": round(r["routes"][0]["distance"] / 1000, 1), "minutes": round(r["routes"][0]["duration"] / 60), "source": "Distance routière (OSRM)", "at": now_iso()}
        await db.route_cache.update_one({"key": key}, {"$set": out}, upsert=True)
        return out
    except Exception:
        return await lg.travel(org, a, b)


def vclass(v: dict) -> str:
    return "utilitaire" if (v.get("type") or "utilitaire") == "utilitaire" and (v.get("volume_m3") or 0) < 16 else "camion"


def _veh(tv: dict, fleet: dict) -> dict:
    v = fleet.get(tv.get("vehicle_id")) or {}
    if v:
        return {**tv, "name": v["name"], "capacity_kg": v.get("capacity_kg") or 0, "volume_m3": v.get("volume_m3") or 0, "cost_km": v.get("cost_km") or 0, "cls": vclass(v), "rental": False}
    vol = tv.get("rental_volume_m3") or 0
    return {**tv, "vehicle_id": "", "name": tv.get("rental_label") or "Véhicule loué", "capacity_kg": tv.get("rental_capacity_kg") or 0, "volume_m3": vol, "cost_km": 0, "cls": "camion" if vol >= 16 else "utilitaire", "rental": True}


def _fill(load: list, vs: list, c: dict) -> tuple:
    w, vol = sum(q * (e.get("weight_kg") or 0) for e, q in load), sum(q * (e.get("volume_m3") or 0) for e, q in load)
    cap, cv = sum(v["capacity_kg"] for v in vs), sum(v["volume_m3"] for v in vs)
    by_cap = sum(q / s for e, q in load if (s := sum(lg.cap_for(c, v["vehicle_id"], e) or 0 for v in vs if v["vehicle_id"])))
    return round(w, 1), round(vol, 2), round(max(w / cap if cap else 0, vol / cv if cv else 0, by_cap) * 100, 1), bool(cap and w > cap)


def _label(t: dict, vs: list, en: bool, weight: float | None) -> str:
    names = {"delivery": ("Livraison et installation", "Delivery and set-up"), "pickup": ("Retrait et démontage", "Pick-up and dismantling"), "extra": ("Transport", "Transport")}
    if t.get("on_site"):
        return "On-site set-up" if en else "Mise en place sur site"
    parts = [t.get("title") or names[t["type"]][en]]
    if t["date"]:
        slot = " – ".join(x.replace(":00", " h").replace(":", " h ") if not en else x for x in (t["slot_start"], t["slot_end"]) if x)
        parts.append(f"{t['date'][8:10]}/{t['date'][5:7]}" + (f", {slot}" if slot else ""))
    groups: dict = {}
    for v in vs:
        k = (("van" if en else "utilitaire") if v["cls"] == "utilitaire" else ("truck" if en else "camion")) + (f" {v['volume_m3']:g} m³" if v["volume_m3"] else "")
        groups[k] = groups.get(k, 0) + 1
    if groups:
        parts.append(", ".join(f"{n} {k}" for k, n in groups.items()))
    if weight:
        parts.append(f"{weight:g} kg")
    return " — ".join(parts)


async def compute(ctx: Ctx, q: dict, body: TripsIn) -> dict:
    cc, st = sq.can_cost(ctx), await pricing_of(ctx.org_id)
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}) or {}
    ev = await db.events.find_one(ctx.q({"id": q.get("event_id")}), {"_id": 0, "history": 0}) if q.get("event_id") else None
    w, c = await rs.world(ctx.org_id), await lg.caps(ctx.org_id)
    fleet = {v["id"]: v for v in await ctx.list("vehicles", sort=[("capacity_kg", 1)]) if v.get("active", True)}
    venue_id = rs.target(ev) if ev else ""
    venue = await db.venues.find_one(ctx.q({"id": venue_id}), {"_id": 0}) if venue_id else None
    dates = body.dates or q.get("dates") or (qb.dates_from_event(ev) if ev else None)
    display = body.display or q.get("trip_display") or "detailed"
    show_weight = q.get("trip_show_weight", False) if body.show_weight is None else body.show_weight
    # Chargement : uniquement la part « À livrer »
    want: dict = {}
    for l in ([x.model_dump() for x in body.lines] if body.lines is not None else qb.flatten(qb.blocks_of(q))):
        if l.get("equipment_id") in w["eqs"]:
            want[l["equipment_id"]] = want.get(l["equipment_id"], 0) + l["qty"]
    alloc, depots = (rs.alloc_of(ev, w) if ev else []), [x["id"] for x in w["whs"] if venue_id and x.get("venue_id") == venue_id]
    load, origin_default = [], ""
    for pid, qty in want.items():
        rows = [r for r in alloc if r["equipment_id"] == pid]
        on = sum(r["qty"] for r in rows if r["fulfilment"] == "on_site") if rows else sum(w["levels"].get(pid, {}).get(d, 0) for d in depots)
        origin_default = origin_default or next((r["warehouse_id"] for r in rows if r["fulfilment"] == "to_deliver"), "")
        if qty - min(on, qty) > 0:
            load.append((w["eqs"][pid], qty - min(on, qty)))
    back = [(e, n) for e, n in load if (e.get("product_type") or "Location") != "Consommable"]
    all_on_site = bool(want) and not load
    trips = [t.model_dump() for t in body.trips] if body.trips is not None else q.get("trips")
    if trips is None:
        trips = [Trip(id=new_id(), type="delivery").model_dump(), Trip(id=new_id(), type="pickup").model_dump()]
    busy = {}
    out, lines, en = [], [], (q.get("language") or "fr").startswith("en")
    for t in trips:
        slot = (dates or {}).get(t["type"]) if t["type"] != "extra" else None
        if slot:
            t.update(date=slot.get("date", ""), slot_start=slot.get("start", ""), slot_end=slot.get("end", ""))
        enabled = t["active"] and (slot is None or slot.get("enabled", True))
        cargo = back if t["type"] == "pickup" else load
        wh = w["by"].get(t["origin_id"] or origin_default) or w["default"]
        if t["vehicles"] is None:  # proposition : le plus petit véhicule qui suffit, sinon on en ajoute
            pick, cands = [], [_veh({"vehicle_id": i}, fleet) for i, v in fleet.items() if v.get("capacity_kg")]
            one = next((v for v in cands if _fill(cargo, [v], c)[2] <= 100), None)
            for v in ([one] if one else sorted(cands, key=lambda v: -v["capacity_kg"])):
                pick.append(v)
                if _fill(cargo, pick, c)[2] <= 100:
                    break
            t["vehicles"] = [TripVehicle(vehicle_id=v["vehicle_id"]).model_dump() for v in pick] if cargo else []
        t["on_site"] = all_on_site and t["type"] == "delivery"
        vs = [] if t["on_site"] else [_veh(tv, fleet) for tv in t["vehicles"]]
        weight, vol, fill, over = _fill(cargo, vs, c)
        alerts = []
        if vs and (fill > 100 or over):
            alerts.append(f"Chargement à {fill:g} % de la capacité{' (charge utile dépassée)' if over else ''} : ajoutez un véhicule")
        if cargo and not vs and not t["on_site"]:
            alerts.append("Aucun véhicule sur ce trajet")
        for v in vs:
            f = fleet.get(v["vehicle_id"]) or {}
            if t["date"] and any(u.get("start", "") <= t["date"] <= u.get("end", "") for u in f.get("unavailabilities") or []):
                alerts.append(f"{v['name']} indisponible le {t['date'][8:10]}/{t['date'][5:7]}")
            if t["date"] and v["vehicle_id"]:
                if t["date"] not in busy:
                    busy[t["date"]] = await ctx.list("logistics_missions", {"date": t["date"], "event_id": {"$ne": q.get("event_id") or "-"}, "status": {"$ne": "annulee"}}, limit=200)
                other = next((m for m in busy[t["date"]] if any(x["vehicle_id"] == v["vehicle_id"] for x in m.get("vehicles") or [])), None)
                if other:
                    alerts.append(f"{v['name']} déjà pris ce jour-là ({other.get('event_code', '')} {other.get('event_title', '')})".strip())
        rd = {"km": None, "minutes": None, "source": "Distance saisie à la main"} if t["distance_manual"] else await road(org, wh, venue)
        if not t["distance_manual"]:
            t["distance_km_rt"] = round((rd["km"] or 0) * 2, 1)
        km_rt, one_way = t["distance_km_rt"], t["distance_km_rt"] / 2
        mode = t["pricing_mode"] or st["transport_mode"]
        calc = lambda v: st["vehicle_flat_fee"] + km_rt * st["client_rate_per_km"][v["cls"]]  # noqa: E731
        zone = lambda v: next((z["price"] for z in st["zone_grid"][v["cls"]] if one_way <= z["max_km"]), None)  # noqa: E731
        if mode == "manual" or t["on_site"]:
            price, note = t["price_ht"], "Prix saisi à la main"
        elif mode == "zone":
            beyond = any(zone(v) is None for v in vs)
            price = sum(zone(v) if zone(v) is not None else calc(v) for v in vs) + t["tolls_ht"]
            note = "Forfait par zone" + (" (hors grille : calcul au km)" if beyond else "")
        else:
            price, note = sum(calc(v) for v in vs) + t["tolls_ht"], "Mise à disposition + km + péages"
        cost = sum(km_rt * v["cost_km"] + (v.get("rental_cost_ht") or 0) for v in vs) + t["tolls_ht"]
        t["price_ht"] = r2(price)
        row = {**t, "enabled": enabled, "weight_kg": weight, "volume_m3": vol, "fill_pct": fill, "payload_alert": over, "alerts": alerts, "drive_minutes": rd["minutes"], "distance_source": rd["source"],
               "pricing_note": note, "origin_name": wh.get("name", ""), "destination_name": (venue or {}).get("name", ""), "vehicle_names": [v["name"] for v in vs], "items": len(cargo), **({"cost_ht": r2(cost), "margin_ht": r2(price - cost)} if cc else {})}
        out.append(row)
        if enabled and (vs or t["on_site"]):
            lines.append({"source_type": "trip", "source_id": t["id"], "kind": "transport", "label": _label(t, vs, en, weight if show_weight else None), "qty": 1, "unit_price": r2(price), "vat": 20, **({"unit_cost": r2(cost)} if cc else {})})
    if display == "grouped" and lines:
        tw = max((r["weight_kg"] for r in out if r["enabled"]), default=0)
        lines = [{"source_type": "trip", "source_id": "grouped", "kind": "transport", "qty": 1, "vat": 20, "unit_price": r2(sum(l["unit_price"] for l in lines)), **({"unit_cost": r2(sum(l["unit_cost"] for l in lines))} if cc else {}),
                  "label": ("Round-trip transport (delivery and pick-up)" if en else "Transport aller-retour (livraison et retrait)") + (f" — {tw:g} kg" if show_weight and tw else "")}]
    # Équipe et frais de mission
    def items(key: str, given):
        old = {x["id"]: x for x in q.get(key) or []}
        rows = [x.model_dump() for x in given] if given is not None else list(old.values())
        if not cc and given is not None:  # un profil sans les coûts ne peut pas les écraser
            rows = [{**x, **{k: old[x["id"]][k] for k in COST_KEYS[key] if x["id"] in old}} for x in rows]
        return rows
    labor_in, exp_in = items("labor", body.labor), items("expenses", body.expenses)
    lab = labor_rows(labor_in, dates, st)
    ld = body.labor_display or q.get("labor_display") or "detailed"
    ll = [{"source_type": "labor", "source_id": r["id"], "kind": "labor", "label": r["client_label"], "qty": 1, "unit_price": r["price_ht"], "vat": 20, **({"unit_cost": r["cost_ht"]} if cc else {})} for r in lab]
    if ld == "grouped" and ll:
        ph = [PHASES[k] for k in PHASES if PHASES[k] and any(r["phase"] == k for r in lab)]
        ll = [{"source_type": "labor", "source_id": "labor_grouped", "kind": "labor", "label": "Main-d'œuvre" + (f" ({', '.join(ph)})" if ph else ""), "qty": 1, "vat": 20, "unit_price": r2(sum(x["unit_price"] for x in ll)), **({"unit_cost": r2(sum(x["unit_cost"] for x in ll))} if cc else {})}]
    exp, el, included = expense_lines(exp_in, cc)
    ref = next((r for r in out if r["enabled"] and not r.get("on_site")), None)
    sug = suggest(lab, (ref or {}).get("distance_km_rt", 0) / 2, (ref or {}).get("drive_minutes"), st)
    for r in out:
        nv = max(1, len(r["vehicle_names"]))
        r.update(handling_minutes=90 * nv, duration_minutes=(r["drive_minutes"] or round(r["distance_km_rt"] / 2 / 70 * 60)) * 2 + 90 * nv, team=[x["id"] for x in lab if x["trip_id"] == r["id"]])
    hide = lambda rows, key: rows if cc else [{k: v for k, v in x.items() if k not in (*COST_KEYS[key], "cost_ht")} for x in rows]  # noqa: E731
    lines = lines + ll + el
    keep = set(Trip.model_fields)
    return {"labor": hide(lab, "labor"), "expenses": hide(exp, "expenses"), "labor_display": ld, "suggested_expenses": hide(sug, "expenses"), "stored_labor": labor_in, "stored_expenses": exp_in, **({"included_cost_ht": included} if cc else {}),
            "roles": {k: v["label"] for k, v in st["labor_grid"].items()}, "shift_lengths": st["shift_lengths"], "contracts": list(st["employer_charge_coef"]),
            "trips": out, "stored": [{k: v for k, v in t.items() if k in keep} for t in trips], "lines": lines, "display": display, "show_weight": show_weight, "all_on_site": all_on_site, "can_cost": cc, "section": st["logistics_section"],
            "default_mode": st["transport_mode"], "vehicles": [{"id": v["id"], "name": v["name"], "capacity_kg": v.get("capacity_kg") or 0, "volume_m3": v.get("volume_m3") or 0} for v in fleet.values()],
            "warehouses": [{"id": x["id"], "name": x["name"]} for x in w["whs"] if x.get("active", True)], "has_venue": bool(venue)}


@router.post("/quotes/{qid}/trips/compute")
async def compute_trips(qid: str, body: TripsIn, ctx: Ctx = Depends(FIN)):
    return _pub(await compute(ctx, await ctx.get("quotes", qid), body))


@router.put("/quotes/{qid}/trips")
async def save_trips(qid: str, body: TripsIn, ctx: Ctx = Depends(FIN)):
    quote_writer(ctx)
    q = await _editable_quote(ctx, qid)
    out = await compute(ctx, q, body)
    await db.quotes.update_one(ctx.q({"id": qid}), {"$set": {"trips": out["stored"], "trip_display": out["display"], "trip_show_weight": out["show_weight"], "labor": out["stored_labor"], "expenses": out["stored_expenses"], "labor_display": out["labor_display"], "updated_at": now_iso()}})
    return _pub(out)


def _pub(out: dict) -> dict:
    return {k: v for k, v in out.items() if k not in ("stored", "stored_labor", "stored_expenses")}


async def on_quote_accepted(org_id: str, q: dict, ev: dict | None) -> None:
    """Devis signé : missions, postes Staff, engagements de charge et tâches (une seule fois par élément)."""
    if not ev or not (q.get("trips") or q.get("labor") or q.get("expenses")):
        return
    st, dates = await pricing_of(org_id), q.get("dates") or qb.dates_from_event(ev)
    base = {"org_id": org_id, "created_at": now_iso()}
    day = ev["start"][:10]

    async def commit(sid: str, cat: str, label: str, amount: float) -> None:
        if amount and not await db.commitments.find_one({"org_id": org_id, "source": "quote_logistics", "source_id": sid}):
            await db.commitments.insert_one({**base, "id": new_id(), "event_id": ev["id"], "kind": "expense", "category": cat, "label": label, "amount_ht": r2(amount), "vat": 0, "due_date": day, "probability": 100,
                                             "source": "quote_logistics", "source_id": sid, "status": "prevu", "invoice_ref": "", "paid_at": None, "actual_ht": None, "history": []})

    async def task(ref: str, title: str, desc: str) -> None:
        if not await db.tasks.find_one({"org_id": org_id, "source_ref": ref}):
            await db.tasks.insert_one({**base, "id": new_id(), "title": title, "description": desc, "due_at": day, "due_date": day, "priority": "high", "assignee_ids": [], "event_id": ev["id"], "status": "todo", "done": False,
                                       "done_at": None, "checklist": [], "attachments": [], "source": "auto", "source_ref": ref, "created_by": "Système", "created_by_id": ""})
    trips = [t for t in q.get("trips") or [] if t.get("active", True)]
    if trips:
        await lg.generate(org_id, ev, "Devis signé")
    for t in trips:
        slot = (dates or {}).get(t["type"]) or {}
        m = await db.logistics_missions.find_one({"org_id": org_id, "event_id": ev["id"], "type": {"delivery": "livraison", "pickup": "retrait"}.get(t["type"], "-")}, {"_id": 0})
        if m and m["status"] in ("a_planifier", "planifiee") and slot.get("enabled", True):
            vs = m.get("vehicles") or [{"id": new_id(), "vehicle_id": v["vehicle_id"], "trip_index": 1, "driver_ids": [], "fill_feedback": "", "loaded_at": None} for v in t.get("vehicles") or [] if v.get("vehicle_id")]
            await db.logistics_missions.update_one({"org_id": org_id, "id": m["id"]}, {"$set": {"vehicles": vs, **({"date": slot["date"], "window_start": slot.get("start", ""), "window_end": slot.get("end", "")} if slot.get("date") else {}),
                                                                                              **({"origin_id": t["origin_id"]} if t.get("origin_id") else {})},
                                                                                     "$push": {"history": {"at": now_iso(), "by": "Devis signé", "detail": f"Créneau et véhicules repris du devis {q['number']}"}}})
        for v in t.get("vehicles") or []:
            if not v.get("vehicle_id"):
                await commit(f"{q['id']}:{t['id']}:{v.get('rental_label')}", "transport", f"Location {v.get('rental_label') or 'véhicule'} — devis {q['number']}", v.get("rental_cost_ht") or 0)
    cat = {"manutentionnaire": "manutentionnaire", "chauffeur": "manutentionnaire", "autre": "autres"}
    for r in labor_rows(q.get("labor") or [], dates, st):
        ref = f"{q['id']}:{r['id']}"
        if r["start_at"] and not await db.positions.find_one({"org_id": org_id, "source_ref": ref}):
            ext = r["cost_source"] == "provider"
            await db.positions.insert_one({**base, "id": new_id(), "event_id": ev["id"], "category_key": cat.get(r["role"], "technicien_polyvalent"), "quantity": r["headcount"], "date": r["start_at"][:10], "start_time": r["start_at"][11:],
                                           "end_time": r["end_at"][11:], "break_min": 0, "dress": "", "brief": f"{r['role_label']} — {PHASES[r['phase']] or 'mission'} (devis {q['number']})", "skills": [],
                                           "rate_type": "flat" if ext else "hourly", "rate": r["provider_rate"] if ext else r["gross_hour"], "rate_basis": "ht" if ext else "brut", "accepted_statuses": ["freelance"] if ext else ["freelance", "intermittent"],
                                           "visibility": "network" if ext else "private", "team_id": "", "venue_city": "", "status": "open", "archived_at": None, "source_ref": ref})
        if r["cost_source"] == "provider":
            await commit(ref, "prestataires", f"{r['headcount']} {r['role_label']} externe — devis {q['number']}", r["cost_ht"])
    for e in q.get("expenses") or []:
        ref, n = f"{q['id']}:{e['id']}", e["persons"] * e["qty"]
        if e["mode"] == "client_provided":
            await task(ref, f"Confirmer hébergement / repas fournis par le client — {ev['title']}", f"{e['label'] or EXP[e['type']]} : {n:g} — devis {q['number']}.")
            continue
        if e["type"] == "lodging":
            await commit(ref, "autre", f"Hôtel — {n:g} nuitée(s) — devis {q['number']}", n * e["unit_cost_ht"])
            await task(ref, f"Réserver hôtel — {ev['title']}", f"{e['persons']} personne(s) × {e['qty']:g} nuit(s), autour du {day[8:10]}/{day[5:7]} — devis {q['number']}. Rattacher ensuite la facture d'hôtel à l'événement.")
