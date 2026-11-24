import logging
import os
import re
from datetime import datetime, timedelta
from typing import List, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import messaging_core as mc
from core import Ctx, db, need, now_iso
from i18n import clean_lang
from routes_main import ContactIn, VenueIn, _contact, _venue, contact_name, module_catalog
from routes_ops import EventIn, _sync_modules, create_event, hist

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)
W = need("events:write")
SOURCES = ["sms", "instagram", "whatsapp", "email", "telephone", "autre"]
EVENT_TYPES = ["Mariage", "Soirée d'entreprise", "Séminaire", "Gala", "Anniversaire", "Soirée privée", "Festival", "Autre"]
ORG_TYPES = ["wedding_planner", "agence_evenementielle", "agence_communication", "autre"]
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
DEFAULT_PROMPT = (
    "Tu es l'assistant d'Exclusivity Events (DJ, sonorisation, éclairage, photobooth, location de mobilier événementiel, sud de la France et Québec). "
    "Tu reçois le texte brut d'une demande client copiée depuis un SMS, Instagram, WhatsApp ou un email. Extrais uniquement les informations présentes ou "
    "déductibles sans ambiguïté. Interprète les dates relatives par rapport à la date de réception ; si l'année n'est pas précisée, prends la prochaine "
    "occurrence future. Si une date est vague (« fin juin », « été 2027 »), mets la meilleure estimation, date_is_approximate: true et recopie l'expression "
    "dans date_raw. N'invente jamais un nom, un téléphone, un lieu ou un budget. Ignore politesses, emojis et messages qui ne viennent pas du client. "
    "Si l'expéditeur est un organisateur (wedding planner, agence) qui écrit pour un client, remplis organizer et laisse client vide si le client n'est pas nommé. "
    "Déduis les modules du vocabulaire (« DJ », « musique », « sono » → dj / son_lumiere ; « borne photo » → photobooth ; « tables, chaises, mange-debout, salon » "
    "→ loueur_materiel). Détecte la langue du message. Liste dans questions_to_ask les infos clés manquantes pour un devis. Réponds uniquement en JSON valide selon le schéma.")


class XClient(BaseModel):
    first_name: str
    last_name: str
    phone: str
    email: str
    instagram_handle: str
    company: str
    language: str


class XOrganizer(BaseModel):
    name: str
    company: str
    type: str
    phone: str
    email: str


class XItem(BaseModel):
    item: str
    quantity: int


class XEvent(BaseModel):
    category: str
    date: str
    date_is_approximate: bool
    date_raw: str
    start_time: str
    end_time: str
    guests: int
    venue_name: str
    venue_address: str
    venue_city: str
    venue_postal_code: str
    modules: List[str]
    equipment_requested: List[XItem]
    budget_amount: float
    budget_tax_mode: str
    title_suggestion: str


class XConfidence(BaseModel):
    date: float
    venue: float
    category: float
    client_name: float
    guests: float
    budget: float


class Extraction(BaseModel):
    source_detected: str
    client: XClient
    organizer: XOrganizer
    event: XEvent
    notes: str
    questions_to_ask: List[str]
    followup_message: str
    confidence: XConfidence


def empty_extraction() -> dict:
    return Extraction(source_detected="", client=XClient(first_name="", last_name="", phone="", email="", instagram_handle="", company="", language="fr-FR"),
                      organizer=XOrganizer(name="", company="", type="", phone="", email=""),
                      event=XEvent(category="", date="", date_is_approximate=False, date_raw="", start_time="", end_time="", guests=0, venue_name="", venue_address="",
                                   venue_city="", venue_postal_code="", modules=[], equipment_requested=[], budget_amount=0, budget_tax_mode="TTC", title_suggestion=""),
                      notes="", questions_to_ask=[], followup_message="", confidence=XConfidence(date=0, venue=0, category=0, client_name=0, guests=0, budget=0)).model_dump()


def e164(phone: str) -> str:
    d = re.sub(r"\D", "", phone or "")
    if not d:
        return ""
    if (phone or "").strip().startswith("+"):
        return "+" + d
    if d.startswith("00"):
        return "+" + d[2:]
    if len(d) == 10 and d.startswith("0"):
        return "+33" + d[1:]
    return "+" + d if d.startswith("33") and len(d) == 11 else d


def tail(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")[-9:]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


async def extract(org: dict, raw: str, source: str, received_at: str, modules: list) -> tuple:
    day = datetime.strptime(received_at[:10], "%Y-%m-%d")
    system = ((org.get("inbound_parse_system_prompt") or DEFAULT_PROMPT) +
              f"\n\nDate de réception : {DAYS[day.weekday()]} {received_at[:10]}. Source indiquée : {source or 'inconnue'} (source_detected parmi {', '.join(SOURCES)}). "
              f"category parmi : {', '.join(EVENT_TYPES)} (chaîne vide si inconnu). modules parmi : {', '.join(m['key'] + ' (' + m['label'] + ')' for m in modules)}. "
              f"organizer.type parmi : {', '.join(ORG_TYPES)}. client.language parmi fr-FR, en-US, en-GB, es-ES, it-IT, de-DE. Dates AAAA-MM-JJ, heures HH:MM, chaîne vide si inconnu ; "
              "nombres à 0 si inconnus. venue_city : nom officiel complet de la commune si elle est identifiable. confidence entre 0 et 1. "
              "followup_message : message de relance court et poli, dans la langue du message, tutoiement ou vouvoiement selon le ton reçu, qui demande les informations de questions_to_ask "
              "(chaîne vide s'il ne manque rien). questions_to_ask en français." + mc.GUARD)
    for attempt in range(2):
        try:
            r = await mc.claude().messages.parse(model=org.get("inbound_parse_model") or os.environ.get("LLM_MODEL") or os.environ.get("INBOUND_PARSE_MODEL") or "claude-haiku-5-5", max_tokens=4000,
                                                 output_format=Extraction, system=system, messages=[{"role": "user", "content": raw[:12000]}])
            x = r.parsed_output.model_dump()
            keys = {m["key"] for m in modules}
            x["event"]["modules"] = [k for k in x["event"]["modules"] if k in keys]
            x["event"]["category"] = next((t for t in EVENT_TYPES if t.lower() == x["event"]["category"].strip().lower()), "")
            x["client"]["phone"], x["organizer"]["phone"] = e164(x["client"]["phone"]), e164(x["organizer"]["phone"])
            x["client"]["language"] = clean_lang(x["client"]["language"])
            x["client"]["instagram_handle"] = x["client"]["instagram_handle"].lstrip("@")
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", x["event"]["date"]):
                x["event"]["date"] = ""
            return x, True
        except Exception as exc:
            logger.error("Inbound parse attempt %s failed: %s", attempt + 1, exc)
            extract.reason = mc.ai_reason(exc)
    return empty_extraction(), False


async def matches(ctx: Ctx, x: dict) -> dict:
    out = {"client": None, "organizer": None, "venue": None, "same_day": []}
    contacts = await ctx.list("contacts", limit=5000)
    c = x["client"]
    name = norm(f"{c['first_name']} {c['last_name']}")

    def find(pool, phone, email, insta, nm, company=""):
        for strong, test in ((True, lambda k: phone and tail(k.get("phone")) == tail(phone)), (True, lambda k: email and norm(k.get("email")) == norm(email)),
                             (True, lambda k: insta and norm(k.get("instagram_handle")) == norm(insta)),
                             (False, lambda k: (len(nm) > 3 and norm(f"{k.get('first_name', '')} {k.get('last_name', '')}") == nm) or (company and norm(k.get("company")) == norm(company)))):
            hit = next((k for k in pool if test(k)), None)
            if hit:
                return hit, strong
        return None, False
    hit, strong = find([k for k in contacts if "client" in k.get("types", [])], c["phone"], c["email"], c["instagram_handle"], name)
    if hit:
        n = await db.events.count_documents(ctx.q({"$or": [{"client_id": hit["id"]}, {"client_contact_ids": hit["id"]}]}))
        out["client"] = {"id": hit["id"], "display_name": contact_name(hit), "phone": hit.get("phone", ""), "email": hit.get("email", ""), "events_count": n, "strong": strong}
    o = x["organizer"]
    if o["name"] or o["company"]:
        hit, strong = find([k for k in contacts if "prestataire" in k.get("types", [])], o["phone"], o["email"], "", norm(o["name"]), o["company"])
        if hit:
            out["organizer"] = {"id": hit["id"], "display_name": contact_name(hit), "company": hit.get("company", ""), "strong": strong}
    e = x["event"]
    if e["venue_name"]:
        vs = await ctx.list("venues", {"name": {"$regex": re.escape(e["venue_name"].strip()), "$options": "i"}})
        v = next((v for v in vs if e["venue_postal_code"] and v.get("zip") == e["venue_postal_code"]), None) or next(
            (v for v in vs if not e["venue_city"] or norm(e["venue_city"])[:6] in norm(v.get("city"))), None)
        if v:
            out["venue"] = {k: v.get(k, "") for k in ("id", "name", "city", "zip")}
    if e["date"]:
        out["same_day"] = await same_day(ctx, e["date"])
    return out


async def same_day(ctx: Ctx, day: str) -> list:
    return [{"id": ev["id"], "title": ev["title"], "status": ev["status"]} for ev in await ctx.list("events", {"start": {"$regex": f"^{re.escape(day)}"}})]


class ParseIn(BaseModel):
    raw_text: str = Field(min_length=1, max_length=20000)
    source: str = ""
    received_at: str = ""
    manual: bool = False


@router.post("/inbound-requests/parse")
async def parse(body: ParseIn, ctx: Ctx = Depends(W)):
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    received = body.received_at if re.match(r"^\d{4}-\d{2}-\d{2}", body.received_at) else datetime.now(ZoneInfo("Europe/Paris")).strftime("%Y-%m-%dT%H:%M")
    if body.manual:
        x, ok = empty_extraction(), False
    else:
        if not mc.ai_ready():
            logger.error("Saisie rapide IA : %s", mc.ai_reason())
            raise HTTPException(503, "Assistant IA indisponible : " + mc.ai_reason())
        x, ok = await extract(org, body.raw_text, body.source, received, await module_catalog(ctx.org_id))
        if not ok:
            raise HTTPException(503, "Assistant IA indisponible : " + getattr(extract, "reason", "erreur du fournisseur"))
    source = body.source if body.source in SOURCES else x.get("source_detected") if x.get("source_detected") in SOURCES else "autre"
    doc = await ctx.insert("inbound_requests", {"raw_text": body.raw_text, "source": source, "received_at": received, "extracted_json": x, "status": "draft",
                                                "contact_id": None, "event_id": None, "created_by": ctx.member.get("name")})
    return {**doc, "parsed": ok, "matches": await matches(ctx, x)}


@router.get("/inbound-requests/availability")
async def availability(day: str, ctx: Ctx = Depends(W)):
    return await same_day(ctx, day)


@router.get("/inbound-requests/settings")
async def get_settings(ctx: Ctx = Depends(need("org:write"))):
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    return {"inbound_parse_system_prompt": org.get("inbound_parse_system_prompt") or DEFAULT_PROMPT, "inbound_parse_model": org.get("inbound_parse_model") or ""}


class SettingsIn(BaseModel):
    inbound_parse_system_prompt: str = Field(max_length=8000)
    inbound_parse_model: str = Field("", max_length=80)


@router.put("/inbound-requests/settings")
async def put_settings(body: SettingsIn, ctx: Ctx = Depends(need("org:write"))):
    await db.orgs.update_one({"id": ctx.org_id}, {"$set": body.model_dump()})
    return body


@router.get("/inbound-requests")
async def list_requests(ctx: Ctx = Depends(need("events:read"))):
    rows = await ctx.list("inbound_requests", {"status": {"$in": ["draft", "converted"]}}, sort=[("received_at", -1)], limit=300)
    evs = {e["id"]: e for e in await ctx.list("events", {"id": {"$in": [r["event_id"] for r in rows if r.get("event_id")]}})}
    out = []
    for r in rows:
        ev = evs.get(r.get("event_id"))
        if r["status"] == "converted" and (not ev or ev["status"] != "demande"):
            continue
        x = r["extracted_json"]
        out.append({"id": r["id"], "status": r["status"], "source": r["source"], "received_at": r["received_at"], "event_id": r.get("event_id"),
                    "title": (ev or {}).get("title") or x["event"]["title_suggestion"] or r["raw_text"][:60], "event_date": (ev or {}).get("start", x["event"]["date"])[:10],
                    "missing": len([q for q in x.get("questions_to_ask", []) if q not in r.get("asked", [])])})
    return out


@router.get("/inbound-requests/{rid}")
async def get_request(rid: str, ctx: Ctx = Depends(W)):
    r = await ctx.get("inbound_requests", rid)
    return {**r, "parsed": True, "matches": await matches(ctx, r["extracted_json"])}


class PersonIn(BaseModel):
    contact_id: str = ""
    first_name: str = Field("", max_length=80)
    last_name: str = Field("", max_length=80)
    name: str = Field("", max_length=160)
    company: str = Field("", max_length=120)
    phone: str = Field("", max_length=40)
    email: str = Field("", max_length=200)
    instagram_handle: str = Field("", max_length=80)
    language: str = "fr-FR"
    type: str = "wedding_planner"
    fill_missing: bool = True


class EventDraftIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: str = "Autre"
    date: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    start_time: str = ""
    end_time: str = ""
    guests: int = Field(0, ge=0, le=100000)
    venue_id: str = ""
    venue_name: str = Field("", max_length=120)
    venue_address: str = Field("", max_length=200)
    venue_zip: str = Field("", max_length=10)
    venue_city: str = Field("", max_length=80)
    modules: List[str] = Field(min_length=1)
    budget: float = Field(0, ge=0)
    budget_tax_mode: Literal["ht", "ttc"] = "ttc"
    notes: str = Field("", max_length=5000)


class ConvertIn(BaseModel):
    target: Literal["event", "opportunity"] = "opportunity"
    client: Optional[PersonIn] = None
    organizer: Optional[PersonIn] = None
    event: EventDraftIn
    asked: List[str] = []


class DraftIn(BaseModel):
    extracted_json: Optional[dict] = None
    status: Optional[Literal["draft", "discarded"]] = None


@router.patch("/inbound-requests/{rid}")
async def save_draft(rid: str, body: DraftIn, ctx: Ctx = Depends(W)):
    r = await ctx.get("inbound_requests", rid)
    if r["status"] not in ("draft", "discarded"):
        raise HTTPException(400, "Cette demande a déjà été traitée")
    return await ctx.update("inbound_requests", rid, body.model_dump(exclude_none=True))


async def _client(ctx: Ctx, p: PersonIn | None) -> str:
    if not p or not (p.contact_id or p.first_name or p.last_name or p.company):
        return ""
    fields = {"first_name": p.first_name.strip(), "last_name": p.last_name.strip(), "company": p.company.strip(), "phone": e164(p.phone), "email": p.email.strip().lower(),
              "instagram_handle": p.instagram_handle.strip().lstrip("@")}
    if p.contact_id:
        cur = await ctx.get("contacts", p.contact_id)
        upd = {k: v for k, v in fields.items() if v and not cur.get(k)} if p.fill_missing else {}
        if upd or "client" not in cur.get("types", []):
            await db.contacts.update_one(ctx.q({"id": cur["id"]}), {"$set": {**upd, "updated_at": now_iso()}, "$addToSet": {"types": "client"}})
        return cur["id"]
    if not ctx.can("contacts:write"):
        raise HTTPException(403, "Action non autorisée pour votre rôle")
    data = _contact(ContactIn(**fields, types=["client"], language=p.language, source="Saisie rapide"))
    return (await ctx.insert("contacts", {**data, "interactions": []}))["id"]


async def _organizer(ctx: Ctx, p: PersonIn | None) -> str | None:
    if not p or not (p.contact_id or p.name or p.company):
        return None
    if p.contact_id:
        return (await ctx.get("contacts", p.contact_id))["id"]
    if not ctx.can("providers:manage"):
        raise HTTPException(403, "Seul un admin ou un gérant peut créer un organisateur")
    from routes_providers import ProviderIn, _create
    import providers_core as pc
    await pc.ensure_categories(ctx.org_id)
    first, _, last = p.name.strip().partition(" ")
    prof = await _create(ctx, ProviderIn(first_name=first, last_name=last, company=p.company, email=p.email, phone=e164(p.phone), language=p.language,
                                         categories=[p.type if p.type in ORG_TYPES[:3] else "wedding_planner"]))
    return prof["contact_id"]


async def _venue_id(ctx: Ctx, e: EventDraftIn) -> str:
    if e.venue_id:
        return (await ctx.get("venues", e.venue_id))["id"]
    if not e.venue_name.strip():
        return ""
    dup = await db.venues.find_one(ctx.q({"name": {"$regex": f"^{re.escape(e.venue_name.strip())}$", "$options": "i"}, "zip": e.venue_zip.strip()}), {"_id": 0})
    if dup:
        return dup["id"]
    if not ctx.can("venues:write"):
        raise HTTPException(403, "Action non autorisée pour votre rôle")
    return (await ctx.insert("venues", _venue(VenueIn(name=e.venue_name.strip(), address=e.venue_address.strip(), zip=e.venue_zip.strip(), city=e.venue_city.strip()))))["id"]


async def to_event(ctx: Ctx, req: dict, body: ConvertIn, client_id: str, organizer_id: str | None, venue_id: str) -> dict:
    e = body.event
    if not e.date:
        raise HTTPException(400, "Indiquez la date de l'événement")
    start = f"{e.date}T{e.start_time or '18:00'}"
    end_day = e.date if e.end_time and e.end_time > (e.start_time or "18:00") else (datetime.strptime(e.date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    data = EventIn(title=e.title, type=e.type, client_id=client_id, client_contact_ids=[client_id] if client_id else [], signatory_contact_id=client_id, planner_contact_id=organizer_id,
                   venue_id=venue_id, start=start, end=f"{end_day}T{e.end_time or '02:00'}", guests=e.guests, budget=e.budget, budget_tax_mode=e.budget_tax_mode, notes=e.notes, modules=e.modules)
    if not client_id and organizer_id:
        lang = (await ctx.get("contacts", organizer_id)).get("language")
        data.language = lang
    r = await create_event(data, ctx)
    return {"kind": "event", "id": r["id"], "code": r["code"], "url": f"/evenements/{r['id']}"}


async def to_opportunity(ctx: Ctx, req: dict, body: ConvertIn, client_id: str, organizer_id: str | None, venue_id: str) -> dict:
    from routes_crm import OppIn, create_opp
    if not ctx.can("crm:manage"):
        raise HTTPException(403, "Action non autorisée pour votre rôle")
    if not client_id:
        raise HTTPException(400, "Un client est obligatoire pour créer une opportunité : renseignez au moins son nom")
    e = body.event
    src = {"sms": "sms", "instagram": "instagram", "whatsapp": "whatsapp", "email": "email"}.get(req["source"], "organisateur" if organizer_id else "autre")
    o = await create_opp(ctx, OppIn(client_contact_id=client_id, organizer_contact_id=organizer_id or "", venue_id=venue_id, city=e.venue_city, event_date=e.date, event_type=e.type,
                                    guest_count=e.guests, services=e.modules, source_key=src, amount=e.budget, amount_tax_mode=e.budget_tax_mode, notes=f"{e.notes}\n\n[{req['source']}] {req['raw_text']}"[:5000], force=True))
    return {"kind": "opportunity", "id": o["id"], "url": f"/crm?id={o['id']}"}


TARGETS = {"event": to_event, "opportunity": to_opportunity}


async def log_raw(ctx: Ctx, event_id: str, req: dict, action: str) -> None:
    entry = {"id": req["id"], "source": req["source"], "received_at": req["received_at"], "raw_text": req["raw_text"], "by": ctx.member.get("name"), "at": now_iso()}
    await db.events.update_one(ctx.q({"id": event_id}), {"$push": {"inbound_messages": entry, "history": {"$each": [hist(ctx, action, f"[{req['source']} · {req['received_at'][:10]}] {req['raw_text'][:1500]}")], "$slice": -300}}})


@router.post("/inbound-requests/{rid}/convert")
async def convert(rid: str, body: ConvertIn, ctx: Ctx = Depends(W)):
    req = await ctx.get("inbound_requests", rid)
    if req["status"] != "draft":
        raise HTTPException(409, "Cette demande a déjà été traitée")
    client_id = await _client(ctx, body.client)
    organizer_id = await _organizer(ctx, body.organizer)
    venue_id = await _venue_id(ctx, body.event)
    out = await TARGETS[body.target](ctx, req, body, client_id, organizer_id, venue_id)
    missing = len([q for q in req["extracted_json"].get("questions_to_ask", []) if q not in body.asked])
    await ctx.update("inbound_requests", rid, {"status": "converted", "contact_id": client_id or None, "event_id": out["id"] if out["kind"] == "event" else None,
                                               "target": out, "asked": body.asked})
    if out["kind"] == "event":
        await log_raw(ctx, out["id"], req, "Demande reçue")
    return {**out, "missing": missing}


async def diffs(ctx: Ctx, req: dict, ev: dict) -> list:
    e, out = req["extracted_json"]["event"], []
    if e["guests"] and e["guests"] != ev.get("guests"):
        out.append({"key": "guests", "label": "Invités", "old": ev.get("guests") or "—", "new": e["guests"], "value": e["guests"]})
    if e["date"] and e["date"] != ev["start"][:10]:
        out.append({"key": "date", "label": "Date", "old": ev["start"][:10], "new": e["date"], "value": e["date"]})
    if e["budget_amount"] and ctx.can("finance:read") and e["budget_amount"] != ev.get("budget"):
        out.append({"key": "budget", "label": "Budget", "old": ev.get("budget") or "—", "new": e["budget_amount"], "value": e["budget_amount"]})
    cur = {m["module_key"] for m in await ctx.list("event_modules", {"event_id": ev["id"], "status": "actif"})}
    labels = {m["key"]: m["label"] for m in await module_catalog(ctx.org_id)}
    for k in e["modules"]:
        if k not in cur:
            out.append({"key": f"module:{k}", "label": "Module", "old": "—", "new": labels.get(k, k), "value": k})
    for i, it in enumerate(e["equipment_requested"]):
        txt = f"{it['quantity'] or ''} {it['item']}".strip()
        out.append({"key": f"equipment:{i}", "label": "Matériel demandé", "old": "—", "new": txt, "value": txt})
    if e["venue_name"]:
        v = await db.venues.find_one(ctx.q({"id": ev.get("venue_id")}), {"_id": 0}) if ev.get("venue_id") else None
        if not v or norm(e["venue_name"]) not in norm(v["name"]):
            out.append({"key": "venue_note", "label": "Lieu", "old": (v or {}).get("name", "—"), "new": e["venue_name"], "value": e["venue_name"]})
    return out


@router.get("/inbound-requests/{rid}/diff/{eid}")
async def diff(rid: str, eid: str, ctx: Ctx = Depends(W)):
    return await diffs(ctx, await ctx.get("inbound_requests", rid), await ctx.get("events", eid))


class MergeIn(BaseModel):
    keys: List[str] = Field(max_length=60)


@router.post("/inbound-requests/{rid}/merge/{eid}")
async def merge(rid: str, eid: str, body: MergeIn, ctx: Ctx = Depends(W)):
    req = await ctx.get("inbound_requests", rid)
    if req["status"] != "draft":
        raise HTTPException(409, "Cette demande a déjà été traitée")
    ev = await ctx.get("events", eid)
    upd, notes, mods = {}, [], []
    for d in await diffs(ctx, req, ev):
        if d["key"] not in body.keys:
            continue
        if d["key"] in ("guests", "budget"):
            upd[d["key"]] = d["value"]
        elif d["key"] == "date":
            delta = datetime.strptime(d["value"], "%Y-%m-%d") - datetime.strptime(ev["start"][:10], "%Y-%m-%d")
            for k in ("start", "end", "setup_start", "return_end"):
                upd[k] = (datetime.strptime(ev[k][:16], "%Y-%m-%dT%H:%M") + delta).strftime("%Y-%m-%dT%H:%M")
        elif d["key"].startswith("module:"):
            mods.append(d["value"])
        else:
            notes.append(f"{d['label']} : {d['value']}")
    if notes:
        upd["notes"] = "\n".join(filter(None, [ev.get("notes", ""), f"[{req['source']} {req['received_at'][:10]}] " + " ; ".join(notes)]))
    if upd:
        await ctx.update("events", eid, upd)
    if mods:
        cur = [m["module_key"] for m in await ctx.list("event_modules", {"event_id": eid, "status": "actif"})]
        await _sync_modules(ctx, eid, cur + mods, None)
    await log_raw(ctx, eid, req, "Complément de demande")
    await ctx.update("inbound_requests", rid, {"status": "merged", "event_id": eid, "contact_id": ev.get("client_id") or None})
    return {"id": eid, "url": f"/evenements/{eid}", "applied": len(body.keys)}
