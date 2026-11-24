import asyncio
import csv
import io
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

import messaging_core as mc
import providers_core as pc
from core import Ctx, db, need, now_iso
from core import audit  # noqa: E402
from routes_main import contact_name, onsite_for
from routes_messaging import _return_to

from core import check_expiry, ensure_link, link_doc, link_limit  # noqa: E402,F401
router = APIRouter(prefix="/api")
P = need("providers:manage")
DATE, TIME = r"^\d{4}-\d{2}-\d{2}$", r"^([01]\d|2[0-3]):[0-5]\d$"
CONTACT_KEYS = ("first_name", "last_name", "company", "email", "phone")
DOC_TYPES = ["contrat", "kbis", "urssaf", "rc_pro", "autre"]
Vat = Literal["subject", "not_applicable_293B"]


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


# ---------- Métiers ----------
class CategoryIn(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    order: Optional[int] = None
    active: bool = True
    is_organizer: Optional[bool] = None


@router.get("/provider-categories")
async def list_categories(ctx: Ctx = Depends(P)):
    await pc.ensure_categories(ctx.org_id)
    return await ctx.list("provider_categories", sort=[("order", 1)])


@router.post("/provider-categories")
async def add_category(body: CategoryIn, ctx: Ctx = Depends(P)):
    rows = await list_categories(ctx)
    key = slug(body.label)
    if not key or any(r["key"] == key for r in rows):
        raise HTTPException(409, "Ce métier existe déjà")
    return await ctx.insert("provider_categories", {"key": key, "label": body.label.strip(), "order": body.order or len(rows) + 1, "active": body.active, "is_organizer": bool(body.is_organizer)})


@router.put("/provider-categories/{cid}")
async def update_category(cid: str, body: CategoryIn, ctx: Ctx = Depends(P)):
    upd = {"label": body.label.strip(), "active": body.active}
    if body.order is not None:
        upd["order"] = body.order
    if body.is_organizer is not None:
        upd["is_organizer"] = body.is_organizer
    return await ctx.update("provider_categories", cid, upd)


# ---------- Prestataires ----------
class ProviderIn(BaseModel):
    contact_id: str = ""
    first_name: str = Field("", max_length=80)
    last_name: str = Field("", max_length=80)
    company: str = Field("", max_length=120)
    email: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    stage_name: str = Field("", max_length=120)
    language: str = Field("fr-FR", max_length=10)
    whatsapp: bool = False
    website: str = Field("", max_length=300)
    instagram: str = Field("", max_length=300)
    video_url: str = Field("", max_length=300)
    categories: List[str] = Field(min_length=1)
    tags: List[str] = []
    base_city: str = Field("", max_length=120)
    base_zip: str = Field("", max_length=10)
    base_lat: Optional[float] = None
    base_lng: Optional[float] = None
    radius_km: float = Field(0, ge=0, le=2000)
    departments: List[str] = []
    travels_everywhere: bool = False
    base_rate: float = Field(0, ge=0, le=1_000_000)
    included_hours: float = Field(0, ge=0, le=48)
    extra_hour_rate: float = Field(0, ge=0, le=100_000)
    travel_fee_mode: Literal["included", "flat", "per_km", "quote"] = "included"
    travel_fee_amount: float = Field(0, ge=0, le=100_000)
    travel_km_included: float = Field(0, ge=0, le=5000)
    meal_lodging: bool = False
    meal_lodging_fee: float = Field(0, ge=0, le=100_000)
    legal_status: Literal["micro", "company", "guso"] = "micro"
    vat_mode: Vat = "not_applicable_293B"
    vat_rate: float = Field(20, ge=0, le=100)
    equipment_brought: str = Field("", max_length=1000)
    equipment_needed: List[str] = []
    equipment_needed_note: str = Field("", max_length=1000)
    tech_rider: str = ""
    languages: List[str] = ["Français"]
    rating: int = Field(0, ge=0, le=5)
    status: Literal["active", "test", "blocked"] = "active"
    notes: str = Field("", max_length=5000)


DEFAULTS = {k: v for k, v in ProviderIn(categories=["autres"]).model_dump().items() if k not in CONTACT_KEYS + ("contact_id",)}


def _clean(xs: list, n: int = 30) -> list:
    return list(dict.fromkeys(x.strip()[:60] for x in xs if x and x.strip()))[:n]


async def _profile_data(ctx: Ctx, body: ProviderIn) -> dict:
    d = {k: v for k, v in body.model_dump().items() if k not in CONTACT_KEYS + ("contact_id",)}
    keys = {c["key"] for c in await list_categories(ctx)}
    d["categories"] = [c for c in dict.fromkeys(d["categories"]) if c in keys]
    if not d["categories"]:
        raise HTTPException(400, "Choisissez au moins un métier")
    d["tags"], d["languages"] = _clean(d["tags"]), _clean(d["languages"], 10)
    d["departments"] = [x for x in _clean([x.upper().zfill(2) for x in d["departments"]], 110) if re.fullmatch(r"\d{2,3}|2[AB]", x)]
    d["equipment_needed"] = [e for e in d["equipment_needed"] if e in pc.EQUIPMENT]
    if d["tech_rider"] and not await db.files.find_one(ctx.q({"id": d["tech_rider"][5:], "is_deleted": False})):
        raise HTTPException(400, "Fiche technique introuvable")
    if d["base_city"] and d["base_lat"] is None:
        g = await pc.geocode(f"{d['base_zip']} {d['base_city']}".strip(), True)
        if g:
            d.update(base_lat=g["lat"], base_lng=g["lng"], base_zip=d["base_zip"] or g["zip"])
    return d


def _contact_fields(body: ProviderIn) -> dict:
    c = {k: getattr(body, k).strip() for k in CONTACT_KEYS}
    c["email"] = c["email"].lower()
    c["language"] = body.language if body.language in pc.LANGS else "fr-FR"
    if c["email"] and not pc.MAIL_RE.match(c["email"]):
        raise HTTPException(400, "Adresse e-mail invalide")
    if not (c["first_name"] or c["last_name"] or c["company"] or body.stage_name.strip()):
        raise HTTPException(400, "Renseignez un nom, un nom de scène ou une société")
    return c


async def _stats(ctx: Ctx) -> dict:
    out: dict = {}
    for r in await ctx.list("request_recipients", {"sent_at": {"$ne": None}}, limit=20000):
        s = out.setdefault(r["provider_id"], [0, 0, 0.0])
        s[0] += 1
        if r.get("replied_at"):
            s[1] += 1
            s[2] += max(0, (datetime.fromisoformat(r["replied_at"]) - datetime.fromisoformat(r["sent_at"])).total_seconds() / 60)
    return out


def _view(p: dict, c: dict, stats: dict) -> dict:
    s = stats.get(p["id"])
    return {**p, **{k: c.get(k, "") for k in CONTACT_KEYS}, "language": c.get("language") or "fr-FR", "display_name": p.get("stage_name") or contact_name(c), "contact_name": contact_name(c),
            "requests_sent": s[0] if s else 0, "response_rate": round(100 * s[1] / s[0]) if s else None, "avg_response_time_min": round(s[2] / s[1]) if s and s[1] else None}


async def _all(ctx: Ctx) -> list:
    contacts = {c["id"]: c for c in await ctx.list("contacts", {"types": "prestataire"})}
    profs = await ctx.list("provider_profiles")
    have = {p["contact_id"] for p in profs}
    for cid, c in contacts.items():
        if cid not in have:
            try:
                profs.append(await ctx.insert("provider_profiles", {**DEFAULTS, "withdrawals": 0, "contact_id": cid, "base_city": c.get("city", ""), "tags": _clean(c.get("tags", []))}))
            except DuplicateKeyError:
                pass
    stats = await _stats(ctx)
    return [_view(p, contacts[p["contact_id"]], stats) for p in profs if p["contact_id"] in contacts]


async def _one(ctx: Ctx, pid: str) -> dict:
    p = await ctx.get("provider_profiles", pid)
    return _view(p, await ctx.get("contacts", p["contact_id"]), await _stats(ctx))


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")[-9:]


@router.get("/providers")
async def list_providers(ctx: Ctx = Depends(P)):
    rows = await _all(ctx)
    today = datetime.now(pc.PARIS).strftime("%Y-%m-%d")
    soon = (datetime.now(pc.PARIS) + timedelta(days=30)).strftime("%Y-%m-%d")
    exp = {}
    for d in await ctx.list("provider_documents", {"type": "urssaf", "expires_at": {"$gt": ""}}):
        exp[d["provider_id"]] = max(exp.get(d["provider_id"], ""), d["expires_at"])
    for r in rows:
        e = exp.get(r["id"])
        r["urssaf_alert"] = None if not e or e > soon else ("expired" if e < today else "soon")
    return sorted(rows, key=lambda r: r["display_name"].lower())


@router.get("/providers/duplicates")
async def duplicates(email: str = "", phone: str = "", name: str = "", ctx: Ctx = Depends(P)):
    email, tel, name = email.strip().lower(), _digits(phone), name.strip().lower()
    profs = {p["contact_id"]: p for p in await ctx.list("provider_profiles")}
    out = []
    for c in await ctx.list("contacts"):
        p = profs.get(c["id"])
        names = {contact_name(c).lower(), (p or {}).get("stage_name", "").lower()} - {"", "—"}
        if (email and c.get("email", "").lower() == email) or (len(tel) == 9 and _digits(c.get("phone")) == tel) or (len(name) > 2 and name in names):
            out.append({"contact_id": c["id"], "display_name": contact_name(c), "email": c.get("email", ""), "provider_id": p["id"] if p else None})
    return out[:5]


EXPORT = [("display_name", "Nom"), ("first_name", "Prénom"), ("last_name", "Nom de famille"), ("company", "Société"), ("email", "E-mail"), ("phone", "Téléphone"),
          ("categories", "Métiers"), ("tags", "Tags"), ("base_city", "Ville de base"), ("base_zip", "Code postal"), ("radius_km", "Rayon km"), ("departments", "Départements"),
          ("base_rate", "Tarif de base"), ("included_hours", "Heures incluses"), ("extra_hour_rate", "Heure supplémentaire"), ("travel_fee_mode", "Déplacement"),
          ("travel_fee_amount", "Montant déplacement"), ("travel_km_included", "Km inclus"), ("vat_mode", "TVA"), ("vat_rate", "Taux TVA"), ("legal_status", "Statut juridique"),
          ("equipment_brought", "Matériel apporté"), ("equipment_needed", "Matériel à fournir"), ("languages", "Langues"), ("rating", "Note"), ("status", "Statut"), ("notes", "Notes")]


@router.get("/providers/export")
async def export_providers(ctx: Ctx = Depends(P)):
    lab = await pc.labels(ctx.org_id)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([h for _, h in EXPORT])
    for r in await list_providers(ctx):
        r["categories"] = [lab.get(c, c) for c in r["categories"]]
        cells = [", ".join(map(str, r[k])) if isinstance(r[k], list) else str(r[k]).replace(".", ",") if isinstance(r[k], float) else str(r[k] if r[k] is not None else "") for k, _ in EXPORT]
        w.writerow(["'" + c if c[:1] and c[:1] in "=+-@" else c for c in cells])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=prestataires.csv"})


async def _create(ctx: Ctx, body: ProviderIn) -> dict:
    data = await _profile_data(ctx, body)
    if body.contact_id:
        c = await ctx.get("contacts", body.contact_id)
        if await db.provider_profiles.find_one(ctx.q({"contact_id": c["id"]})):
            raise HTTPException(409, "Ce contact a déjà une fiche prestataire")
        await db.contacts.update_one(ctx.q({"id": c["id"]}), {"$addToSet": {"types": "prestataire"}})
    else:
        f = _contact_fields(body)
        if f["email"] and await db.contacts.find_one(ctx.q({"email": {"$regex": f"^{re.escape(f['email'])}$", "$options": "i"}})):
            raise HTTPException(409, "Un contact utilise déjà cet e-mail : rattachez la fiche à ce contact")
        c = await ctx.insert("contacts", {**f, "kind": "entreprise" if f["company"] and not (f["first_name"] or f["last_name"]) else "particulier", "status": "", "statuses": {"wedding_planner": "nouvelle_relation"} if "wedding_planner" in data["categories"] else {"prestataire": "partenaire_actif"},
                                          "address": "", "city": data["base_city"], "source": "Prestataires", "tags": [], "notes": "", "types": ["prestataire"], "interactions": []})
    try:
        p = await ctx.insert("provider_profiles", {**data, "contact_id": c["id"], "withdrawals": 0})
    except DuplicateKeyError:
        raise HTTPException(409, "Ce contact a déjà une fiche prestataire")
    return p


@router.post("/providers")
async def create_provider(body: ProviderIn, ctx: Ctx = Depends(P)):
    return await _one(ctx, (await _create(ctx, body))["id"])


@router.put("/providers/{pid}")
async def update_provider(pid: str, body: ProviderIn, ctx: Ctx = Depends(P)):
    p = await ctx.get("provider_profiles", pid)
    f = _contact_fields(body)
    if f["email"] and await db.contacts.find_one(ctx.q({"id": {"$ne": p["contact_id"]}, "email": {"$regex": f"^{re.escape(f['email'])}$", "$options": "i"}})):
        raise HTTPException(409, "Un autre contact utilise déjà cet e-mail")
    data = await _profile_data(ctx, body)
    await db.contacts.update_one(ctx.q({"id": p["contact_id"]}), {"$set": {**f, "updated_at": now_iso()}, "$addToSet": {"types": "prestataire"}})
    await ctx.update("provider_profiles", pid, data)
    return await _one(ctx, pid)


@router.get("/providers/{pid}")
async def get_provider(pid: str, ctx: Ctx = Depends(P)):
    p = await _one(ctx, pid)
    lab = await pc.labels(ctx.org_id)
    reqs = {r["id"]: r for r in await ctx.list("service_requests")}
    p["documents"] = await ctx.list("provider_documents", {"provider_id": pid}, sort=[("created_at", -1)])
    p["unavailabilities"] = [{k: v for k, v in u.items() if k != "private_title"} for u in await ctx.list("provider_unavailabilities", {"provider_id": pid, "cancelled_at": None}, sort=[("date", -1)], limit=200)]
    p.pop("iban_encrypted", None), p.pop("ssn_encrypted", None), p.pop("ical_hash", None)
    p["history"] = [{"request_id": r["request_id"], "category": lab.get(reqs[r["request_id"]]["category_key"], ""), "date": reqs[r["request_id"]]["date"],
                     "city": reqs[r["request_id"]].get("venue_city", ""), "status": _rstatus(r), "sent_at": r.get("sent_at"), "replied_at": r.get("replied_at"),
                     "total_ht": r.get("total_ht"), "total_ttc": r.get("total_ttc"), "vat_mode": r.get("vat_mode")}
                    for r in await ctx.list("request_recipients", {"provider_id": pid}, sort=[("created_at", -1)]) if r["request_id"] in reqs]
    p["missions"] = await ctx.list("missions", {"provider_id": pid}, sort=[("date", -1)])
    return p


class DocIn(BaseModel):
    type: str
    file: str
    expires_at: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")


@router.post("/providers/{pid}/documents")
async def add_document(pid: str, body: DocIn, ctx: Ctx = Depends(P)):
    p = await _one(ctx, pid)
    rec = await db.files.find_one(ctx.q({"id": body.file[5:], "is_deleted": False}), {"_id": 0}) if body.file.startswith("file:") else None
    if body.type not in DOC_TYPES or not rec:
        raise HTTPException(400, "Document invalide")
    return await ctx.insert("provider_documents", {"provider_id": pid, "provider_name": p["display_name"], "type": body.type, "file": body.file,
                                                   "filename": rec.get("filename", ""), "expires_at": body.expires_at})


@router.delete("/provider-documents/{did}")
async def delete_document(did: str, ctx: Ctx = Depends(P)):
    await ctx.delete("provider_documents", did)
    return {"ok": True}


class UnavailIn(BaseModel):
    date: str = Field(pattern=DATE)
    start_time: str = Field("", pattern=r"^(([01]\d|2[0-3]):[0-5]\d)?$")
    end_time: str = Field("", pattern=r"^(([01]\d|2[0-3]):[0-5]\d)?$")
    note: str = Field("", max_length=300)


@router.post("/providers/{pid}/unavailabilities")
async def add_unavailability(pid: str, body: UnavailIn, ctx: Ctx = Depends(P)):
    await ctx.get("provider_profiles", pid)
    return await ctx.insert("provider_unavailabilities", {**body.model_dump(), "provider_id": pid, "source": "manual"})


@router.delete("/provider-unavailabilities/{uid}")
async def delete_unavailability(uid: str, ctx: Ctx = Depends(P)):
    if (await ctx.get("provider_unavailabilities", uid))["source"] == "mission":
        raise HTTPException(400, "Cette date correspond à une mission confirmée")
    await ctx.delete("provider_unavailabilities", uid)
    return {"ok": True}


class CatsIn(BaseModel):
    categories: List[str] = Field(min_length=1, max_length=20)


@router.put("/contacts/{cid}/categories")
async def set_categories(cid: str, body: CatsIn, ctx: Ctx = Depends(need("contacts:write"))):
    c = await ctx.get("contacts", cid)
    await pc.ensure_categories(ctx.org_id)
    ok = {x["key"] for x in await ctx.list("provider_categories")}
    cats = [k for k in dict.fromkeys(body.categories) if k in ok]
    if not cats:
        raise HTTPException(400, "Choisissez au moins un métier")
    if not await db.provider_profiles.find_one(ctx.q({"contact_id": cid})):
        await ctx.insert("provider_profiles", {**DEFAULTS, "withdrawals": 0, "contact_id": cid, "base_city": c.get("city", ""), "tags": []})
    await db.provider_profiles.update_one(ctx.q({"contact_id": cid}), {"$set": {"categories": cats, "updated_at": now_iso()}})
    await db.contacts.update_one(ctx.q({"id": cid}), {"$addToSet": {"types": "prestataire"}})
    return {"categories": cats}


# ---------- Wedding planners : événements apportés ----------
@router.get("/organizers")
async def wedding_planners(ctx: Ctx = Depends(need("contacts:read"))):
    await pc.ensure_categories(ctx.org_id)
    kinds = {c["key"]: c["label"] for c in await ctx.list("provider_categories", {"is_organizer": True}, sort=[("order", 1)])}
    profs = await ctx.list("provider_profiles", {"categories": {"$in": list(kinds)}, "status": {"$ne": "blocked"}})
    cs = {c["id"]: c for c in await ctx.list("contacts", {"id": {"$in": [p["contact_id"] for p in profs]}})}
    rows = [{"contact_id": p["contact_id"], "provider_id": p["id"], "display_name": p.get("stage_name") or contact_name(cs[p["contact_id"]]),
             "company": cs[p["contact_id"]].get("company", ""), "city": p.get("base_city") or cs[p["contact_id"]].get("city", ""),
             "types": [k for k in kinds if k in p["categories"]], "type_label": ", ".join(v for k, v in kinds.items() if k in p["categories"])} for p in profs if p["contact_id"] in cs]
    return sorted(rows, key=lambda r: r["display_name"].lower())


async def _planner_rows(ctx: Ctx, contact_ids: list) -> list:
    evs = await ctx.list("events", {"planner_contact_id": {"$in": contact_ids}}, sort=[("start", -1)], limit=5000)
    ids = [e["id"] for e in evs]
    signed, invoiced = {}, {}
    for q in await ctx.list("quotes", {"event_id": {"$in": ids}, "status": "accepte"}, sort=[("created_at", 1)], limit=5000):
        signed[q["event_id"]] = q.get("total_ht", 0)
    for i in await ctx.list("invoices", {"event_id": {"$in": ids}}, limit=5000):
        invoiced[i["event_id"]] = round(invoiced.get(i["event_id"], 0) + i.get("total_ht", 0), 2)
    contacts = {c["id"]: c for c in await ctx.list("contacts", {"id": {"$in": [e.get("client_id") for e in evs]}})}
    venues = {v["id"]: v for v in await ctx.list("venues")}
    today = datetime.now(pc.PARIS).strftime("%Y-%m-%d")
    import contact_people as cp
    ppl = await cp.people(ctx.org_id, contact_ids)
    rows = []
    for e in evs:
        total = e.get("amount_ht") or 0
        base = signed.get(e["id"], total)
        mode, val = e.get("planner_commission_mode", "none"), e.get("planner_commission_value") or 0
        v = venues.get(e.get("venue_id")) or {}
        c = contacts.get(e.get("client_id"))
        rows.append({"id": e["id"], "code": e["code"], "title": e["title"], "date": e["start"][:10], "upcoming": e["start"][:10] >= today, "planner_contact_id": e["planner_contact_id"], "interlocutor": (cp.pick([p for p in ppl if p["contact_id"] == e["planner_contact_id"]], e.get("planner_person_id")) or {}).get("name", ""),
                     "client": contact_name(c) if c else "", "venue": " · ".join(filter(None, [v.get("name"), v.get("city")])), "type": e.get("type", ""), "status": e["status"],
                     "event_ht": total, "signed_ht": signed.get(e["id"]), "ca_ht": base, "invoiced_ht": invoiced.get(e["id"], 0),
                     "commission": round(base * val / 100, 2) if mode == "percent" else val if mode == "fixed" else 0, "commission_status": e.get("planner_commission_status", "due"),
                     "lead_days": max(0, (datetime.strptime(e["start"][:10], "%Y-%m-%d") - datetime.strptime(e["created_at"][:10], "%Y-%m-%d")).days)})
    return rows


def _indicators(rows: list) -> dict:
    n = len(rows)
    tot = lambda k, f=lambda r: True: round(sum(r[k] for r in rows if f(r)), 2)  # noqa: E731
    places: dict = {}
    for r in rows:
        if r["venue"]:
            places[r["venue"]] = places.get(r["venue"], 0) + 1
    return {"count": n, "upcoming": len([r for r in rows if r["upcoming"]]), "past": len([r for r in rows if not r["upcoming"]]), "ca_ht": tot("ca_ht"), "event_ht": tot("event_ht"),
            "invoiced_ht": tot("invoiced_ht"), "average_basket": round(tot("ca_ht") / n, 2) if n else 0, "commission_due": tot("commission", lambda r: r["commission_status"] == "due"),
            "commission_paid": tot("commission", lambda r: r["commission_status"] == "paid"), "lead_days": round(sum(r["lead_days"] for r in rows) / n) if n else None,
            "top_venues": sorted(places.items(), key=lambda x: -x[1])[:3]}


@router.get("/organizers/ranking")
async def planner_ranking(year: str = "", type: str = "", ctx: Ctx = Depends(P)):
    year = year if re.fullmatch(r"\d{4}", year) else datetime.now(pc.PARIS).strftime("%Y")
    planners = [p for p in await wedding_planners(ctx) if not type or type in p["types"]]
    rows = [r for r in await _planner_rows(ctx, [p["contact_id"] for p in planners]) if r["date"][:4] == year]
    out = []
    for p in planners:
        mine = [r for r in rows if r["planner_contact_id"] == p["contact_id"]]
        if mine:
            out.append({**p, **_indicators(mine)})
    return {"year": year, "rows": sorted(out, key=lambda r: (-r["ca_ht"], -r["count"]))}


@router.get("/providers/{pid}/events")
async def planner_events(pid: str, year: str = "", ctx: Ctx = Depends(P)):
    p = await ctx.get("provider_profiles", pid)
    rows = await _planner_rows(ctx, [p["contact_id"]])
    years = sorted({r["date"][:4] for r in rows}, reverse=True)
    shown = [r for r in rows if not year or r["date"][:4] == year]
    return {"rows": shown, "years": years, "indicators": _indicators(shown), "by_year": [{"year": y, **_indicators([r for r in rows if r["date"][:4] == y])} for y in years]}


@router.get("/providers/{pid}/events/export")
async def planner_events_export(pid: str, year: str = "", ctx: Ctx = Depends(P)):
    data = await planner_events(pid, year, ctx)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Date", "Code", "Événement", "Client", "Lieu", "Catégorie", "Statut", "Total HT événement", "HT devis signé", "HT facturé", "Commission", "Statut commission"])
    fr = lambda v: "" if v is None else f"{v:.2f}".replace(".", ",")  # noqa: E731
    for r in data["rows"]:
        cells = [r["date"], r["code"], r["title"], r["client"], r["venue"], r["type"], r["status"], fr(r["event_ht"]), fr(r["signed_ht"]), fr(r["invoiced_ht"]), fr(r["commission"]),
                 "Versée" if r["commission_status"] == "paid" else "À verser"]
        w.writerow(["'" + c if c[:1] and c[:1] in "=+-@" else c for c in cells])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=evenements-apportes.csv"})


# ---------- Import ----------
def _num(v) -> float:
    try:
        return max(0.0, float(re.sub(r"[^\d,.]", "", str(v or "")).replace(",", ".") or 0))
    except ValueError:
        return 0.0


def _split(v) -> list:
    return [x.strip() for x in re.split(r"[,;|/]", str(v or "")) if x.strip()]


class ImportIn(BaseModel):
    rows: List[dict] = Field(min_length=1, max_length=500)


@router.post("/providers/import")
async def import_providers(body: ImportIn, ctx: Ctx = Depends(P)):
    cats = await list_categories(ctx)
    by_label = {slug(c["label"]): c["key"] for c in cats} | {c["key"]: c["key"] for c in cats}
    profs = {p["contact_id"] for p in await ctx.list("provider_profiles")}
    contacts = {c["email"].lower(): c["id"] for c in await ctx.list("contacts") if c.get("email")}
    sem, created, skipped = asyncio.Semaphore(5), 0, []

    cache: dict = {}

    async def geo(q: str) -> None:
        async with sem:
            cache[q] = await pc.geocode(q, True)

    todo = []
    for i, r in enumerate(body.rows, start=2):
        r = {k: str(v or "").strip()[:1000] for k, v in r.items()}
        first, last = r.get("first_name", ""), r.get("last_name", "")
        if r.get("name") and not (first or last):
            first, _, last = r["name"].partition(" ")
        email = r.get("email", "").lower()
        if not (first or last or r.get("company") or r.get("stage_name")):
            skipped.append({"row": i, "reason": "nom manquant"})
            continue
        if email and not pc.MAIL_RE.match(email):
            skipped.append({"row": i, "reason": "e-mail invalide"})
            continue
        if email and contacts.get(email) in profs:
            skipped.append({"row": i, "reason": "déjà présent (même e-mail)"})
            continue
        keys, tags = [], _split(r.get("tags"))
        for label in _split(r.get("categories")) or ["autres"]:
            k = by_label.get(slug(label))
            keys.append(k or "autres")
            if not k:
                tags.append(label)
        travel, vat = slug(r.get("travel_fee_mode", "")), slug(r.get("vat", ""))
        d = {"first_name": first[:80], "last_name": last[:80], "company": r.get("company", "")[:120], "email": email, "phone": r.get("phone", "")[:40],
             "stage_name": r.get("stage_name", "")[:120], "categories": list(dict.fromkeys(keys)), "tags": tags, "base_city": r.get("base_city", "")[:120],
             "base_zip": r.get("base_zip", "")[:10], "radius_km": min(_num(r.get("radius_km")), 2000), "departments": _split(r.get("departments")),
             "travels_everywhere": slug(r.get("travels_everywhere", "")) in ("oui", "yes", "1", "true", "x"),
             "base_rate": _num(r.get("base_rate")), "included_hours": min(_num(r.get("included_hours")), 48), "extra_hour_rate": _num(r.get("extra_hour_rate")),
             "travel_fee_mode": "per_km" if "km" in travel else "flat" if "forfait" in travel or "flat" in travel else "quote" if "devis" in travel or "quote" in travel else "included",
             "travel_fee_amount": _num(r.get("travel_fee_amount")), "travel_km_included": _num(r.get("travel_km_included")),
             "vat_mode": "subject" if vat and not any(x in vat for x in ("non", "293", "net", "not")) else "not_applicable_293B",
             "legal_status": "company" if "soc" in slug(r.get("legal_status", "")) or "company" in slug(r.get("legal_status", "")) else "guso" if "guso" in slug(r.get("legal_status", "")) or "interm" in slug(r.get("legal_status", "")) else "micro",
             "equipment_brought": r.get("equipment_brought", ""), "languages": _split(r.get("languages")) or ["Français"], "notes": r.get("notes", ""),
             "contact_id": contacts.get(email, "") if email else ""}
        if email:
            profs.add(contacts.get(email) or f"new:{email}")
            contacts.setdefault(email, f"new:{email}")
            if d["contact_id"].startswith("new:"):
                skipped.append({"row": i, "reason": "doublon dans le fichier (même e-mail)"})
                continue
        todo.append((i, d))
    for i, d in todo:
        try:
            d = ProviderIn(**d)
        except Exception:
            skipped.append({"row": i, "reason": "valeurs invalides"})
            continue
        try:
            await _create(ctx, d.model_copy(update={"base_lat": 0.0 if d.base_city else None}))
            created += 1
        except HTTPException as exc:
            skipped.append({"row": i, "reason": str(exc.detail)})
    fresh = await ctx.list("provider_profiles", {"base_lat": 0.0, "base_lng": None})
    await asyncio.gather(*[geo(q) for q in {f"{p['base_zip']} {p['base_city']}".strip() for p in fresh}])
    for p in fresh:
        g = cache.get(f"{p['base_zip']} {p['base_city']}".strip()) or {}
        await db.provider_profiles.update_one(ctx.q({"id": p["id"]}), {"$set": {"base_lat": g.get("lat"), "base_lng": g.get("lng"), "base_zip": p["base_zip"] or g.get("zip", "")}})
    return {"created": created, "skipped": sorted(skipped, key=lambda s: s["row"])}


# ---------- Modèles de message ----------
class TemplateIn(BaseModel):
    type: Literal["request", "reminder", "confirmation", "filled", "roadmap"]
    category_key: str = ""
    language: Literal["fr", "en"] = "fr"
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)


@router.get("/message-templates")
async def list_templates(ctx: Ctx = Depends(P)):
    saved = await ctx.list("message_templates")
    out = [{"type": k, "category_key": "", "channel": "email", "language": lg, "subject": s, "body": b, "custom": False} for lg, src in (("fr", pc.TEMPLATES), ("en", pc.TEMPLATES_EN)) for k, (s, b) in src.items()
           if not any(t["type"] == k and not t["category_key"] and t["language"] == lg for t in saved)]
    return out + [{**t, "custom": True} for t in saved]


@router.put("/message-templates")
async def save_template(body: TemplateIn, ctx: Ctx = Depends(P)):
    if body.type in ("request", "reminder") and "{lien_reponse}" not in body.body:
        raise HTTPException(400, "Le message doit contenir {lien_reponse}")
    if body.category_key and body.category_key not in await pc.labels(ctx.org_id):
        raise HTTPException(400, "Métier inconnu")
    key = ctx.q({"type": body.type, "category_key": body.category_key, "channel": "email", "language": body.language})
    cur = await db.message_templates.find_one(key, {"_id": 0})
    data = {"subject": body.subject, "body": body.body}
    return await ctx.update("message_templates", cur["id"], data) if cur else await ctx.insert("message_templates", {**key, **data})


# ---------- Demandes ----------
class RequestIn(BaseModel):
    event_id: str = ""
    category_key: str
    quantity: int = Field(1, ge=1, le=50)
    date: str = Field(pattern=DATE)
    start_time: str = Field(pattern=TIME)
    end_time: str = Field(pattern=TIME)
    venue_name: str = Field("", max_length=200)
    venue_address: str = Field(min_length=1, max_length=300)
    venue_zip: str = Field("", max_length=10)
    venue_city: str = Field("", max_length=120)
    venue_lat: Optional[float] = None
    venue_lng: Optional[float] = None
    onsite_contact: str = Field("", max_length=200)
    access_instructions: str = Field("", max_length=2000)
    event_type: str = Field("", max_length=80)
    guest_count: int = Field(0, ge=0, le=100000)
    brief: str = Field("", max_length=5000)
    onsite_equipment: List[str] = []
    onsite_equipment_note: str = Field("", max_length=500)
    budget_min: float = Field(0, ge=0, le=10_000_000)
    budget_max: float = Field(0, ge=0, le=10_000_000)
    budget_tax_mode: Literal["HT", "TTC"] = "HT"
    hide_budget: bool = False
    reply_deadline: str = ""


async def _req_data(ctx: Ctx, body: RequestIn) -> dict:
    d = body.model_dump()
    if d["category_key"] not in await pc.labels(ctx.org_id):
        raise HTTPException(400, "Métier inconnu")
    d["event_id"] = (await ctx.get("events", d["event_id"]))["id"] if d["event_id"] else None
    d["onsite_equipment"] = [e for e in d["onsite_equipment"] if e in pc.EQUIPMENT]
    try:
        dl = datetime.fromisoformat(d["reply_deadline"]) if d["reply_deadline"] else datetime.now(timezone.utc) + timedelta(hours=48)
    except ValueError:
        raise HTTPException(400, "Date limite invalide")
    d["reply_deadline"] = (dl if dl.tzinfo else dl.replace(tzinfo=pc.PARIS)).astimezone(timezone.utc).isoformat()
    if d["venue_lat"] is None or d["venue_lng"] is None:
        g = await pc.geocode(" ".join(filter(None, [d["venue_address"], d["venue_zip"], d["venue_city"]])))
        if g:
            d.update(venue_lat=g["lat"], venue_lng=g["lng"], venue_zip=d["venue_zip"] or g["zip"], venue_city=d["venue_city"] or g["city"])
    return d


def _rstatus(r: dict) -> str:
    if r.get("retained"):
        return "retained"
    if r["reply"] != "none":
        return r["reply"]
    if r.get("send_error"):
        return "error"
    return "queued" if not r.get("sent_at") else "opened" if r.get("opened_at") else "sent"


@router.get("/service-requests")
async def list_requests(ctx: Ctx = Depends(P)):
    lab = await pc.labels(ctx.org_id)
    recs = await ctx.list("request_recipients", limit=20000)
    rows = await ctx.list("service_requests", sort=[("date", -1)])
    for r in rows:
        mine = [x for x in recs if x["request_id"] == r["id"]]
        r.update(category_label=lab.get(r["category_key"], r["category_key"]), recipients=len(mine), retained=len([x for x in mine if x.get("retained")]),
                 available=len([x for x in mine if x["reply"] in ("available", "conditional")]), replied=len([x for x in mine if x["reply"] != "none"]))
    return rows


@router.get("/service-requests/prefill")
async def prefill(event_id: str, ctx: Ctx = Depends(P)):
    e = await ctx.get("events", event_id)
    v = await db.venues.find_one(ctx.q({"id": e.get("venue_id")}), {"_id": 0}) or {}
    return {"event_id": e["id"], "event_title": e["title"], "date": e["start"][:10], "start_time": e["start"][11:16], "end_time": e["end"][11:16],
            "event_type": e.get("type", ""), "guest_count": e.get("guests", 0), "venue_name": v.get("name", ""), "venue_address": v.get("address", ""),
            "venue_zip": v.get("zip", ""), "venue_city": v.get("city", ""), "venue_lat": v.get("lat"), "venue_lng": v.get("lng"),
            "onsite_contact": ", ".join(" ".join(filter(None, [c["name"], f"({c['role']})" if c["role"] else "", c["phone"]])) for c in onsite_for(v, e.get("onsite_contact_ids")))[:200], "access_instructions": v.get("access_instructions", "")}


@router.post("/service-requests")
async def create_request(body: RequestIn, ctx: Ctx = Depends(P)):
    return await ctx.insert("service_requests", {**await _req_data(ctx, body), "status": "draft", "created_by": ctx.member.get("name"),
                                                 "created_by_email": ctx.member.get("email", ""), "cascade_enabled": False, "cascade_batch_size": 3, "cascade_delay_h": 24})


@router.put("/service-requests/{rid}")
async def update_request(rid: str, body: RequestIn, ctx: Ctx = Depends(P)):
    if (await ctx.get("service_requests", rid))["status"] in ("filled", "cancelled"):
        raise HTTPException(400, "Cette demande n'est plus modifiable")
    return await ctx.update("service_requests", rid, await _req_data(ctx, body))


async def _busy(ctx: Ctx, date: str) -> dict:
    out: dict = {}
    for u in await ctx.list("provider_unavailabilities", {"date": date, "cancelled_at": None}):
        out.setdefault(u["provider_id"], set()).add("mission" if u["source"] == "mission" else "unavailable")
    return out


@router.get("/service-requests/{rid}")
async def get_request(rid: str, ctx: Ctx = Depends(P)):
    req = await ctx.get("service_requests", rid)
    lab = await pc.labels(ctx.org_id)
    provs = {p["id"]: p for p in await _all(ctx)}
    recs = []
    for r in await ctx.list("request_recipients", {"request_id": rid}, sort=[("order", 1)]):
        p = provs.get(r["provider_id"])
        if not p:
            continue
        est = pc.estimate(p, req)
        replied = r["reply"] in ("available", "conditional")
        r.pop("token", None)
        r.update(status=_rstatus(r), display_name=p["display_name"], email=p["email"], rating=p["rating"], distance_km=est["distance_km"], estimated=not replied,
                 missing_equipment=[e for e in (r["equipment_needed"] if replied else p["equipment_needed"]) if e not in req["onsite_equipment"]])
        if not replied:
            r.update(proposed_rate=est["rate"], proposed_travel_fee=est["travel_fee"], vat_mode=p["vat_mode"], vat_rate=p["vat_rate"], total_ht=est["total_ht"], total_ttc=est["total_ttc"])
        recs.append(r)
    rank = {"retained": 0, "available": 1, "conditional": 2, "opened": 3, "sent": 3, "queued": 4, "error": 5, "unavailable": 6}
    recs.sort(key=lambda r: (rank[r["status"]], r["total_ttc"]))
    acc = await db.channel_accounts.find_one(ctx.q({"channel": "gmail", "status": "connected"}), {"_id": 0, "email": 1})
    subject, body = await pc.template(ctx.org_id, "request", req["category_key"])
    return {**req, "category_label": lab.get(req["category_key"], req["category_key"]), "duration_h": pc.duration_h(req["start_time"], req["end_time"]),
            "recipients": recs, "missions": await ctx.list("missions", {"request_id": rid}), "sender": acc["email"] if acc else None,
            "message": {"subject": req.get("message_subject") or subject, "body": req.get("message_body") or body}, "equipment_labels": pc.EQUIPMENT}


@router.get("/service-requests/{rid}/candidates")
async def candidates(rid: str, inactive: bool = False, ctx: Ctx = Depends(P)):
    import contact_status as cs
    out_of = set() if inactive else await cs.banned(ctx.org_id)
    req = await ctx.get("service_requests", rid)
    busy = await _busy(ctx, req["date"])
    done = {r["provider_id"] for r in await ctx.list("request_recipients", {"request_id": rid})}
    last = {}
    for m in await ctx.list("missions", sort=[("date", 1)]):
        last[m["provider_id"]] = m["date"]
    out = []
    for p in await _all(ctx):
        if p["status"] == "blocked" or p["contact_id"] in out_of:
            continue
        est = pc.estimate(p, req)
        flags = busy.get(p["id"], set())
        out.append({**{k: p[k] for k in ("id", "display_name", "email", "categories", "tags", "languages", "base_city", "status", "rating", "response_rate", "vat_mode",
                                         "vat_rate", "legal_status", "travel_fee_mode", "equipment_needed")},
                    **est, "match": req["category_key"] in p["categories"] and est["in_zone"], "has_category": req["category_key"] in p["categories"],
                    "unavailable": "unavailable" in flags, "on_mission": "mission" in flags, "already_sent": p["id"] in done, "last_collaboration": last.get(p["id"])})
    out.sort(key=lambda c: (c["unavailable"] or c["on_mission"], -c["rating"], c["total_ttc"], c["distance_km"] if c["distance_km"] is not None else 1e9))
    return out


class PreviewIn(BaseModel):
    provider_id: str
    subject: str = Field(max_length=300)
    body: str = Field(max_length=20000)


@router.post("/service-requests/{rid}/preview")
async def preview(rid: str, body: PreviewIn, ctx: Ctx = Depends(P)):
    req = await ctx.get("service_requests", rid)
    p = await ctx.get("provider_profiles", body.provider_id)
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    v = pc.variables(org, {**req, "app_url": "https://…"}, p, await ctx.get("contacts", p["contact_id"]), {"token": "lien-personnel"}, await pc.labels(ctx.org_id))
    return {"subject": pc.render(body.subject, v), "body": pc.render(body.body, v) + pc.RGPD.format(org=org.get("name", ""), stop="https://…/reponse/lien-personnel?stop=1")}


class SendIn(BaseModel):
    provider_ids: List[str] = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    app_url: str
    cascade_enabled: bool = False
    cascade_batch_size: int = Field(3, ge=1, le=50)
    cascade_delay_h: float = Field(24, gt=0, le=720)


@router.post("/service-requests/{rid}/send")
async def send_request(rid: str, body: SendIn, request: Request, bg: BackgroundTasks, ctx: Ctx = Depends(P)):
    req = await ctx.get("service_requests", rid)
    if req["status"] in ("filled", "cancelled"):
        raise HTTPException(400, "Cette demande est close")
    if "{lien_reponse}" not in body.body:
        raise HTTPException(400, "Le message doit contenir {lien_reponse}")
    if req["reply_deadline"] <= now_iso():
        raise HTTPException(400, "La date limite de réponse est dépassée : modifiez-la avant d'envoyer")
    if not await db.channel_accounts.find_one(ctx.q({"channel": "gmail", "status": "connected"})):
        raise HTTPException(409, "La boîte Gmail n'est pas connectée : connectez-la dans la messagerie")
    app_url = _return_to(request, body.app_url)
    provs = {p["id"]: p for p in await _all(ctx)}
    order = {r["provider_id"] for r in await ctx.list("request_recipients", {"request_id": rid})}
    for pid in dict.fromkeys(body.provider_ids):
        p = provs.get(pid)
        if p and pid not in order and p["status"] != "blocked":
            await ctx.insert("request_recipients", {"request_id": rid, "provider_id": pid, "provider_name": p["display_name"], 
                                                    "channels": ["email"], "order": len(order), "sent_at": None, "opened_at": None, "reminded_at": None, "replied_at": None,
                                                    "send_error": None, "claim": None, "reply": "none", "retained": False})
            order.add(pid)
    req = await ctx.update("service_requests", rid, {"message_subject": body.subject, "message_body": body.body, "app_url": app_url, "cascade_enabled": body.cascade_enabled,
                                                     "cascade_batch_size": body.cascade_batch_size, "cascade_delay_h": body.cascade_delay_h,
                                                     "status": "sent" if req["status"] == "draft" else req["status"]})
    bg.add_task(pc.send_batch, await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}), req, body.cascade_batch_size if body.cascade_enabled else None)
    return await get_request(rid, ctx)


@router.post("/service-requests/{rid}/cancel")
async def cancel_request(rid: str, ctx: Ctx = Depends(P)):
    if (await ctx.get("service_requests", rid))["status"] == "filled":
        raise HTTPException(400, "Cette demande est déjà pourvue")
    return await ctx.update("service_requests", rid, {"status": "cancelled"})


@router.post("/service-requests/{rid}/recipients/{cid}/remind")
async def remind(rid: str, cid: str, ctx: Ctx = Depends(P)):
    req = await ctx.get("service_requests", rid)
    rec = await ctx.get("request_recipients", cid, {"request_id": rid})
    if req["status"] not in pc.OPEN or rec["reply"] != "none" or req["reply_deadline"] <= now_iso():
        raise HTTPException(400, "Relance impossible pour ce destinataire")
    field = "reminded_at" if rec.get("sent_at") else "sent_at"
    await db.request_recipients.update_one(ctx.q({"id": cid}), {"$set": {field: None, "send_error": None, "claim": None}})
    ok = await pc.send_recipient(await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}), req, {**rec, field: None}, "reminder" if rec.get("sent_at") else "request")
    if not ok:
        raise HTTPException(502, (await ctx.get("request_recipients", cid)).get("send_error") or "Envoi impossible")
    return {"ok": True}


async def _after_retain(org: dict, req: dict, rec: dict, mission: dict, others: list) -> None:
    key = {"org_id": org["id"], "id": mission["id"]}
    try:
        await pc.deliver(org, req, rec, "confirmation", mission)
        await db.missions.update_one(key, {"$set": {"confirmation_sent_at": now_iso()}})
    except Exception as exc:
        await db.missions.update_one(key, {"$set": {"confirmation_error": str(exc)[:200]}})
    for o in others:
        try:
            await pc.deliver(org, req, o, "filled")
            await db.request_recipients.update_one({"org_id": org["id"], "id": o["id"]}, {"$set": {"filled_notified_at": now_iso()}})
        except Exception as exc:
            pc.logger.error("Message « date pourvue » en échec pour %s : %s", o["id"], exc)


@router.post("/service-requests/{rid}/recipients/{cid}/retain")
async def retain(rid: str, cid: str, request: Request, bg: BackgroundTasks, no_account: bool = False, ctx: Ctx = Depends(P)):
    req = await ctx.get("service_requests", rid)
    if req["status"] not in pc.OPEN:
        raise HTTPException(400, "Cette demande n'est pas ouverte")
    claim = await db.request_recipients.find_one_and_update(ctx.q({"id": cid, "request_id": rid, "retained": False, "reply": {"$ne": "unavailable"}}),
                                                            {"$set": {"retained": True}}, projection={"_id": 0})
    if not claim:
        raise HTTPException(409, "Ce prestataire est déjà retenu ou s'est déclaré indisponible")
    p = await _one(ctx, claim["provider_id"])
    if claim["reply"] == "none":
        est = pc.estimate(p, req)
        claim.update(proposed_rate=est["rate"], proposed_travel_fee=est["travel_fee"], vat_mode=p["vat_mode"], vat_rate=p["vat_rate"], total_ht=est["total_ht"],
                     total_ttc=est["total_ttc"], equipment_needed=p["equipment_needed"], equipment_note=p["equipment_needed_note"])
    missing = [e for e in claim["equipment_needed"] if e not in req["onsite_equipment"]]
    mission = await ctx.insert("missions", {"request_id": rid, "recipient_id": cid, "provider_id": p["id"], "provider_name": p["display_name"], "event_id": req.get("event_id"),
                                            "category_key": req["category_key"], "date": req["date"], "start_time": req["start_time"], "end_time": req["end_time"],
                                            "venue_city": req.get("venue_city", ""), "agreed_rate": claim["proposed_rate"], "agreed_travel_fee": claim["proposed_travel_fee"],
                                            "vat_mode": claim["vat_mode"], "vat_rate": claim["vat_rate"], "total_ht": claim["total_ht"], "total_ttc": claim["total_ttc"],
                                            "equipment_needed": claim["equipment_needed"], "equipment_note": claim.get("equipment_note", ""), "missing_equipment": missing,
                                            "status": "confirmed", "confirmation_sent_at": None, "roadmap_sent_at": None, "rating": None, "rating_comment": ""})
    await ctx.insert("provider_unavailabilities", {"provider_id": p["id"], "date": req["date"], "start_time": req["start_time"], "end_time": req["end_time"],
                                                   "source": "mission", "mission_id": mission["id"], "note": ""})
    import routes_finance as fin
    await fin.on_mission(ctx.org_id, mission)
    recs = await ctx.list("request_recipients", {"request_id": rid})
    others = []
    if len([r for r in recs if r["retained"]]) >= req["quantity"]:
        req = await ctx.update("service_requests", rid, {"status": "filled"})
        others = [r for r in recs if not r["retained"] and r["reply"] in ("available", "conditional")]
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    bg.add_task(_after_retain, org, req, claim, mission, others)
    if not no_account:
        import portal_core as po
        from routes_comms import base_url
        bg.add_task(po.auto_provider, org, p["contact_id"], ctx.member, base_url(request))
    return {"mission": mission, "filled": req["status"] == "filled", "missing_equipment": missing, "notified_others": len(others)}


# ---------- Missions ----------
@router.get("/missions")
async def list_missions(ctx: Ctx = Depends(P)):
    lab = await pc.labels(ctx.org_id)
    today = datetime.now(pc.PARIS).strftime("%Y-%m-%d")
    rows = await ctx.list("missions", sort=[("date", -1)])
    for m in rows:
        m.update(category_label=lab.get(m["category_key"], m["category_key"]), to_rate=m["date"] < today and not m.get("rating"))
    return rows


class MissionPatch(BaseModel):
    status: Optional[Literal["confirmed", "done", "invoiced", "paid", "cancelled"]] = None
    share_full_timeline: Optional[bool] = None
    share_team: Optional[bool] = None
    onsite_contact_visible_from: Optional[str] = Field(None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    payment_status: Optional[Literal["pending", "scheduled", "paid"]] = None
    rating: Optional[int] = Field(None, ge=1, le=5)
    rating_comment: Optional[str] = Field(None, max_length=1000)


@router.patch("/missions/{mid}")
async def patch_mission(mid: str, body: MissionPatch, ctx: Ctx = Depends(P)):
    m = await ctx.update("missions", mid, body.model_dump(exclude_none=True))
    if body.status == "cancelled":
        await db.provider_unavailabilities.delete_many(ctx.q({"mission_id": mid}))
        await audit(ctx.org_id, ctx.member, "mission_cancelled", m["provider_name"], "Accès du prestataire à cette mission retiré")
    if body.rating:
        rated = [x["rating"] for x in await ctx.list("missions", {"provider_id": m["provider_id"], "rating": {"$ne": None}})]
        await db.provider_profiles.update_one(ctx.q({"id": m["provider_id"]}), {"$set": {"rating": round(sum(rated) / len(rated))}})
    return m


# ---------- Page publique de réponse (sans compte) ----------
async def _by_token(token: str) -> tuple:
    rec = await link_doc("request_recipients", token)
    req = await db.service_requests.find_one({"org_id": rec["org_id"], "id": rec["request_id"]}, {"_id": 0}) if rec else None
    prof = await db.provider_profiles.find_one({"org_id": rec["org_id"], "id": rec["provider_id"]}, {"_id": 0}) if req else None
    if not prof or req["status"] == "draft":
        raise HTTPException(404, "Lien introuvable")
    check_expiry(link_limit("service_requests", req))
    if req["reply_deadline"] <= now_iso() and not rec["retained"]:
        raise HTTPException(410, "Ce lien a expiré : la date limite de réponse est dépassée")
    return rec, req, prof


def _state(req: dict, rec: dict) -> str:
    return "retained" if rec["retained"] else "cancelled" if req["status"] == "cancelled" else "filled" if req["status"] == "filled" else "open"


@router.get("/public/provider-requests/{token}")
async def public_request(token: str):
    rec, req, prof = await _by_token(token)
    if not rec.get("opened_at"):
        await db.request_recipients.update_one({"org_id": rec["org_id"], "id": rec["id"]}, {"$set": {"opened_at": now_iso()}})
    org = await db.orgs.find_one({"id": rec["org_id"]}, {"_id": 0, "name": 1}) or {}
    contact = await db.contacts.find_one({"org_id": rec["org_id"], "id": prof["contact_id"]}, {"_id": 0, "first_name": 1}) or {}
    est = pc.estimate(prof, req)
    replied = rec["reply"] in ("available", "conditional")
    full = await db.contacts.find_one({"org_id": rec["org_id"], "id": prof["contact_id"]}, {"_id": 0, "language": 1}) or {}
    return {"language": full.get("language") or "fr-FR", "org_name": org.get("name", ""), "first_name": contact.get("first_name") or prof.get("stage_name", ""), "state": _state(req, rec),
            "category": (await pc.labels(rec["org_id"])).get(req["category_key"], ""), "date": req["date"], "start_time": req["start_time"], "end_time": req["end_time"],
            "city": f"{req.get('venue_zip', '')} {req.get('venue_city', '')}".strip(), "event_type": req.get("event_type", ""), "guest_count": req.get("guest_count", 0),
            "brief": req.get("brief", ""), "onsite_equipment": req["onsite_equipment"], "onsite_equipment_note": req.get("onsite_equipment_note", ""),
            "budget": None if req.get("hide_budget") or not (req["budget_min"] or req["budget_max"]) else pc.budget_text(req), "deadline": req["reply_deadline"],
            "equipment_labels": pc.EQUIPMENT, "distance_km": est["distance_km"], "travel_fee_mode": prof["travel_fee_mode"],
            "reply": {"reply": rec["reply"], "proposed_rate": rec["proposed_rate"] if replied else est["rate"],
                      "proposed_travel_fee": rec["proposed_travel_fee"] if replied else est["travel_fee"], "vat_mode": rec["vat_mode"] if replied else prof["vat_mode"],
                      "vat_rate": rec["vat_rate"] if replied else prof["vat_rate"], "equipment_needed": rec["equipment_needed"] if replied else prof["equipment_needed"],
                      "equipment_note": rec.get("equipment_note", "") if replied else prof["equipment_needed_note"], "reply_comment": rec.get("reply_comment", ""),
                      "alt_start": rec.get("alt_start", ""), "alt_end": rec.get("alt_end", "")}}


class ReplyIn(BaseModel):
    reply: Literal["available", "unavailable", "conditional"]
    proposed_rate: float = Field(0, ge=0, le=1_000_000)
    proposed_travel_fee: float = Field(0, ge=0, le=100_000)
    vat_mode: Vat = "not_applicable_293B"
    vat_rate: float = Field(20, ge=0, le=100)
    equipment_needed: List[str] = []
    equipment_note: str = Field("", max_length=1000)
    reply_comment: str = Field("", max_length=2000)
    alt_start: str = Field("", pattern=r"^(([01]\d|2[0-3]):[0-5]\d)?$")
    alt_end: str = Field("", pattern=r"^(([01]\d|2[0-3]):[0-5]\d)?$")
    update_defaults: bool = False


async def _notify_admin(org_id: str, req: dict, rec: dict, text: str) -> None:
    acc = await db.channel_accounts.find_one({"org_id": org_id, "channel": "gmail", "status": "connected"}, {"_id": 0})
    if not acc:
        return
    to = acc["email"]
    try:
        await mc.send_mail(acc, await db.orgs.find_one({"id": org_id}, {"_id": 0}), to, f"Prestataire disponible — {rec.get('provider_name', '')} le {pc.fr_date(req['date'])}",
                           f"{text}\n\nSuivi de la demande : {req.get('app_url', '')}/prestataires/demandes/{req['id']}")
    except Exception as exc:
        pc.logger.error("Notification admin en échec : %s", exc)


@router.post("/public/provider-requests/{token}")
async def public_reply(token: str, body: ReplyIn, bg: BackgroundTasks):
    rec, req, prof = await _by_token(token)
    if _state(req, rec) != "open":
        raise HTTPException(409, "Cette demande n'est plus ouverte : votre réponse ne peut plus être modifiée")
    scope = {"org_id": rec["org_id"]}
    upd = {"reply": body.reply, "replied_at": now_iso(), "reply_comment": body.reply_comment}
    await db.provider_unavailabilities.update_many({**scope, "recipient_id": rec["id"], "source": "request_reply", "cancelled_at": None}, {"$set": {"cancelled_at": now_iso()}})
    if body.reply == "unavailable":
        await db.provider_unavailabilities.insert_one({**scope, "id": secrets.token_hex(16), "provider_id": prof["id"], "date": req["date"], "start_time": req["start_time"],
                                                       "end_time": req["end_time"], "source": "request_reply", "recipient_id": rec["id"], "note": body.reply_comment[:300], "cancelled_at": None, "created_at": now_iso()})
    else:
        ht, ttc = pc.totals(body.proposed_rate, body.proposed_travel_fee, body.vat_mode, body.vat_rate)
        needed = [e for e in body.equipment_needed if e in pc.EQUIPMENT]
        upd.update(proposed_rate=body.proposed_rate, proposed_travel_fee=body.proposed_travel_fee, vat_mode=body.vat_mode, vat_rate=body.vat_rate, total_ht=ht, total_ttc=ttc,
                   equipment_needed=needed, equipment_note=body.equipment_note, alt_start=body.alt_start, alt_end=body.alt_end, update_defaults=body.update_defaults)
        if body.update_defaults:
            await db.provider_profiles.update_one({**scope, "id": prof["id"]}, {"$set": {"vat_mode": body.vat_mode, "vat_rate": body.vat_rate, "equipment_needed": needed,
                                                                                         "equipment_needed_note": body.equipment_note, "updated_at": now_iso()}})
        bg.add_task(_notify_admin, rec["org_id"], req, rec, f"{rec.get('provider_name', 'Un prestataire')} est disponible{' sous conditions' if body.reply == 'conditional' else ''} : "
                    f"{pc.price_text(body.vat_mode, body.vat_rate, ht, ttc)}." + (f"\n\nCommentaire : {body.reply_comment}" if body.reply_comment else ""))
    await db.request_recipients.update_one({**scope, "id": rec["id"]}, {"$set": upd})
    await db.service_requests.update_one({**scope, "id": req["id"], "status": "sent"}, {"$set": {"status": "in_progress"}})
    return {"ok": True}


@router.post("/public/provider-requests/{token}/unsubscribe")
async def public_unsubscribe(token: str):
    rec = await link_doc("request_recipients", token)
    if not rec:
        raise HTTPException(404, "Lien introuvable")
    await db.provider_profiles.update_one({"org_id": rec["org_id"], "id": rec["provider_id"]}, {"$set": {"status": "blocked", "unsubscribed_at": now_iso()}})
    prof = await db.provider_profiles.find_one({"org_id": rec["org_id"], "id": rec["provider_id"]}, {"_id": 0, "contact_id": 1}) or {}
    await db.users.update_many({"org_id": rec["org_id"], "contact_id": prof.get("contact_id", "__none__"), "role": "provider"}, {"$set": {"status": "suspended"}})
    return {"ok": True}
