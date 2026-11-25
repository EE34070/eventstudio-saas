"""Module métier Wedding planner (orgs.modules contient « wedding_planner »).

Espace de l'organisatrice : /api/wedding/*  (droits « événements », rubrique events de la grille d'accès)
Espace des mariés         : /api/portal/wedding/*  (portail client existant : rôle client, contact rattaché au mariage)

Une seule saisie : les partenaires sont des contacts, chaque événement daté du week-end (Welcome dinner, Jour J,
Brunch, « Autre ») est un événement de l'application, avec le couple en contacts clients : devis, DJ, logistique,
portail (documents, musique, messages) s'y rattachent comme pour tout événement.
"""
import json
import re
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field, field_validator

import portal_core as po
import wedding_core as wc
from core import Ctx, audit, current_member, db, need, new_id
from routes_comms import base_url
from wedding_seed import (AVAILABLE_SECTIONS, COUPLE_SECTIONS, DEFAULT_OPEN_SECTIONS, DEFAULT_RIGHTS, FICHE_FIELDS, MODULE_LINKS,
                          NOTIFICATION_TYPES)

router = APIRouter(prefix="/api")
_R, _W, _C = need("events:read"), need("events:write"), need("portal:client")
LANG = {"fr": "fr-FR", "en": "en-US"}
DESIGN = {"app_name": None, "primary_color": "#1F3D2B", "background": "#F2F1EB", "surface": "#FAF9F5", "ink": "#4b5c4c", "muted": "#6b7a63",
          "line": "#cdd6c6", "soft": "#a9c0ac", "alert": "#9a3b2e", "font_display": "Cormorant Garamond", "font_body": "Montserrat"}
INDEXES = {"wp_weddings": [[("org_id", 1), ("id", 1)], [("org_id", 1), ("contact_ids", 1)]], "wp_questions": [[("org_id", 1), ("order", 1)]],
           "wp_responses": [[("org_id", 1), ("wedding_id", 1), ("submitted_at", -1)]], "wp_notifications": [[("org_id", 1), ("read", 1), ("created_at", -1)]],
           "wp_food": [[("org_id", 1), ("wedding_id", 1)]]}


async def _org(ctx: Ctx) -> dict:
    return await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}) or {}


async def _module(ctx: Ctx) -> dict:
    org = await _org(ctx)
    if wc.MODULE not in (org.get("modules") or []):
        raise HTTPException(403, "Module Wedding planner non activé pour cette société")
    return org


async def R(ctx: Ctx = Depends(_R)) -> Ctx:
    await _module(ctx)
    return ctx


async def W_(ctx: Ctx = Depends(_W)) -> Ctx:
    await _module(ctx)
    return ctx


def _j(d):
    return json.loads(json.dumps(d, default=str))


# --- Schémas ------------------------------------------------------------------------------------

class Partner(BaseModel):
    first_name: str = Field("", max_length=80)
    last_name: str = Field("", max_length=80)
    email: Optional[EmailStr] = None
    phone: str = Field("", max_length=40)
    job: str = Field("", max_length=120)
    address: str = Field("", max_length=300)


class Guests(BaseModel):
    adults: Optional[int] = Field(None, ge=0)
    kids: Optional[int] = Field(None, ge=0)


class Ceremony(BaseModel):
    type: Optional[Literal["Laïque", "Religieuse"]] = None
    confession: str = Field("", max_length=120)
    place: str = Field("", max_length=200)
    time: str = Field("", max_length=5)
    officiant: str = Field("", max_length=200)
    language: str = Field("", max_length=80)
    people: Optional[int] = Field(None, ge=0)


class Info(BaseModel):
    partners: List[Partner] = Field(default_factory=lambda: [Partner(), Partner()], min_length=2, max_length=2)
    same_address: bool = False
    date: Optional[str] = None
    venue: str = Field("", max_length=200)
    venue_address: str = Field("", max_length=300)
    budget: Optional[float] = Field(None, ge=0)
    guests: Guests = Guests()
    ceremony: Ceremony = Ceremony()

    @field_validator("date")
    @classmethod
    def _d(cls, v):
        if v in (None, ""):
            return None
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("date AAAA-MM-JJ")
        return v

    def clean(self) -> dict:
        if self.same_address:
            self.partners[1].address = self.partners[0].address
        if self.ceremony.type != "Religieuse":
            self.ceremony.confession = ""
        return self.model_dump(mode="json")


class WEvent(BaseModel):
    id: str = Field(max_length=40)
    key: str = Field(max_length=40)
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    fixed: bool = False
    date: Optional[str] = None
    place: str = Field("", max_length=200)
    estimate: Optional[int] = Field(None, ge=0)


class Rights(BaseModel):
    budget: bool = True
    vendor_prices: bool = True
    dday_planning: bool = False
    documents: bool = True
    edit_info: bool = True


class CreateIn(BaseModel):
    partner1_email: EmailStr
    partner2_email: Optional[EmailStr] = None
    partner1_first_name: str = Field("", max_length=80)
    partner2_first_name: str = Field("", max_length=80)
    lang: Literal["fr", "en"] = "fr"
    welcome_dinner: bool = True
    brunch: bool = True
    date: Optional[str] = None
    send_invitations: bool = True


class Course(BaseModel):
    name: str = Field("", max_length=120)
    chosen: str = Field("", max_length=300)
    options: List[str] = Field([], max_length=30)


class Included(BaseModel):
    name: str = Field("", max_length=120)
    detail: str = Field("", max_length=300)


class External(BaseModel):
    name: str = Field("", max_length=120)
    supplier: str = Field("", max_length=120)
    per_guest: float = Field(0, ge=0, le=20)
    unit: Literal["bottle", "keg", "l"] = "bottle"


class FoodIn(BaseModel):
    vendor: str = Field("", max_length=160)
    formula: str = Field("", max_length=300)
    price: str = Field("", max_length=120)
    courses: List[Course] = Field([], max_length=30)
    included: List[Included] = Field([], max_length=30)
    external: List[External] = Field([], max_length=30)
    notes: str = Field("", max_length=10000)


# --- Mariage : contacts et événements de l'application ------------------------------------------

def _shift(d: str | None, n: int) -> str | None:
    from datetime import date, timedelta
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat() if d else None


def default_events(d: str | None, wd: bool, br: bool) -> list:
    return [{"id": new_id()[:12], "key": "wd", "name": "Welcome dinner", "enabled": wd, "fixed": False, "date": _shift(d, -1), "place": "", "estimate": None},
            {"id": new_id()[:12], "key": "dj", "name": "Jour J", "enabled": True, "fixed": True, "date": d, "place": "", "estimate": None},
            {"id": new_id()[:12], "key": "br", "name": "Brunch", "enabled": br, "fixed": False, "date": _shift(d, 1), "place": "", "estimate": None}]


async def sync_contacts(ctx: Ctx, w: dict) -> list:
    ids = list(w.get("contact_ids") or [None, None])
    for i, p in enumerate(w["info"]["partners"]):
        data = {"first_name": p.get("first_name") or "", "last_name": p.get("last_name") or "", "email": (p.get("email") or "").lower(),
                "phone": p.get("phone") or "", "address": p.get("address") or "", "language": LANG[w.get("lang", "fr")]}
        cid = ids[i] if i < len(ids) else None
        if cid and await db.contacts.find_one(ctx.q({"id": cid}), {"_id": 0, "id": 1}):
            await ctx.update("contacts", cid, data)
        elif p.get("email") or p.get("first_name"):
            cid = (await ctx.insert("contacts", {**data, "kind": "particulier", "status": "client", "types": ["client"], "statuses": {}, "company": "",
                                                 "city": "", "source": "Wedding planner", "tags": ["mariage"], "notes": "", "interactions": []}))["id"]
        else:
            cid = None
        ids[i] = cid
    return ids[:2]


async def sync_events(ctx: Ctx, w: dict) -> list:
    """Chaque événement activé et daté existe dans Événements, avec le couple en clients (portail, devis, DJ…)."""
    from routes_ops import EventIn, EventPatch, create_event, patch_event
    n, clients = wc.names(w["info"]), [c for c in w.get("contact_ids") or [] if c]
    out = []
    for e in w.get("events", []):
        eid = e.get("event_id")
        alive = eid and await db.events.find_one(ctx.q({"id": eid}), {"_id": 0, "id": 1})
        if not e.get("enabled") or not e.get("date"):
            if alive:
                await ctx.delete("events", eid)
            out.append({**e, "event_id": None})
            continue
        title, start, end = f"{n} · {e['name']}", f"{e['date']}T{'16:00' if e['key'] == 'dj' else '19:00'}", f"{e['date']}T23:59"
        guests = e.get("estimate") or 0
        if alive:
            await patch_event(eid, EventPatch(title=title, start=start, end=end, guests=guests, client_contact_ids=clients or None), ctx)
        else:
            eid = (await create_event(EventIn(title=title, type="Mariage", start=start, end=end, guests=guests, client_contact_ids=clients or None,
                                              language=LANG[w.get("lang", "fr")], notes=f"Créé par le module Wedding planner ({e['name']})"), ctx))["id"]
            await db.events.update_one(ctx.q({"id": eid}), {"$set": {"wedding_id": w["id"], "wedding_event_key": e["key"]}})
        out.append({**e, "event_id": eid})
    return out


async def _w(ctx: Ctx, wid: str) -> dict:
    w = await wc.get(ctx, wc.W, wid)
    if not w or w.get("status") == "deleted":
        raise HTTPException(404, "Mariage introuvable")
    return w


async def out(ctx: Ctx, w: dict) -> dict:
    conf = await wc.confirmed_counts(ctx, w)
    evs = []
    for e in w.get("events", []):
        g, src = wc.guests_for(e, conf)
        evs.append({**e, "confirmed": conf.get(e["id"]), "guests": g, "guests_source": src})
    return _j({"id": w["id"], "names": wc.names(w["info"]), "info": w["info"], "events": evs, "lang": w.get("lang", "fr"),
               "rights": {**DEFAULT_RIGHTS, **(w.get("rights") or {})}, "open_sections": w.get("open_sections", DEFAULT_OPEN_SECTIONS),
               "notes": w.get("notes", ""), "status": w.get("status", "active"), "days_left": wc.days_left(w["info"].get("date")), "progress": wc.progress(w),
               "questionnaire": w.get("questionnaire") or {"status": "pending"}, "discrepancies": [d for d in w.get("discrepancies", []) if d["status"] == "open"],
               "contact_ids": w.get("contact_ids", [])})


# --- Tableau de bord, création --------------------------------------------------------------------

@router.get("/wedding/design")
async def design(ctx: Ctx = Depends(R)):
    org = await _org(ctx)
    return {**DESIGN, "app_name": org.get("name"), **(org.get("wp_branding") or {})}


@router.get("/wedding/weddings")
async def list_weddings(archived: bool = False, ctx: Ctx = Depends(R)):
    rows = await wc.find(ctx, wc.W, {"status": "archived" if archived else "active"})
    cards = []
    for w in rows:
        conf, i = await wc.confirmed_counts(ctx, w), w["info"]
        dj = next((e for e in w.get("events", []) if e["key"] == "dj"), {})
        cards.append({"id": w["id"], "names": wc.names(i), "date": i.get("date"), "days_left": wc.days_left(i.get("date")), "venue": i.get("venue"),
                      "guests": conf.get(dj.get("id")) or wc.total_guests(i) or dj.get("estimate"), "budget": i.get("budget"), "progress": wc.progress(w),
                      "questionnaire": (w.get("questionnaire") or {}).get("status", "pending"),
                      "open_discrepancies": sum(1 for d in w.get("discrepancies", []) if d["status"] == "open"),
                      "vendors": None, "documents": None, "next_payment": None, "next_task": None})  # modules suivants
    cards.sort(key=lambda c: (c["date"] is None, c["date"] or ""))
    return cards


async def _invite(request: Request, ctx: Ctx, w: dict, i: int) -> dict | None:
    cid = (w.get("contact_ids") or [None, None])[i]
    if not cid or not w["info"]["partners"][i].get("email"):
        return None
    org, contact = await _org(ctx), await ctx.get("contacts", cid)
    first = next((e for e in w.get("events", []) if e["key"] == "dj"), {})
    return await po.invite(org, contact, "client", ctx.member, base_url(request), f"{wc.names(w['info'])} · {first.get('name', 'Mariage')}")


@router.post("/wedding/weddings", status_code=201)
async def create(body: CreateIn, request: Request, ctx: Ctx = Depends(W_)):
    info = Info(date=body.date)
    info.partners[0] = Partner(email=body.partner1_email, first_name=body.partner1_first_name)
    info.partners[1] = Partner(email=body.partner2_email, first_name=body.partner2_first_name)
    w = {"id": new_id(), "info": info.clean(), "lang": body.lang, "events": default_events(body.date, body.welcome_dinner, body.brunch),
         "rights": dict(DEFAULT_RIGHTS), "open_sections": list(DEFAULT_OPEN_SECTIONS), "notes": "", "status": "active", "discrepancies": [],
         "questionnaire": {"status": "pending"}}
    w["contact_ids"] = await sync_contacts(ctx, w)
    w["events"] = await sync_events(ctx, w)
    await wc.put(ctx, wc.W, w["id"], w)
    links = []
    if body.send_invitations:
        for i in (0, 1):
            try:
                r = await _invite(request, ctx, w, i)
                if r and r.get("link"):
                    links.append({"email": r["email"], "link": r["link"]})
            except HTTPException as exc:
                links.append({"email": w["info"]["partners"][i].get("email"), "error": exc.detail})
    await audit(ctx.org_id, ctx.member, "wedding_created", wc.names(w["info"]))
    return {**(await out(ctx, w)), "invitations": links}


@router.get("/wedding/weddings/{wid}")
async def get_wedding(wid: str, ctx: Ctx = Depends(R)):
    return await out(ctx, await _w(ctx, wid))


async def _save_info(ctx: Ctx, w: dict, info: dict) -> dict:
    w["info"] = info
    for e in w["events"]:
        if e["key"] == "dj":
            e["date"] = info["date"]
    w["contact_ids"] = await sync_contacts(ctx, w)
    w["events"] = await sync_events(ctx, w)
    await wc.put(ctx, wc.W, w["id"], {"info": info, "events": w["events"], "contact_ids": w["contact_ids"]})
    return w


@router.put("/wedding/weddings/{wid}/info")
async def put_info(wid: str, body: Info, ctx: Ctx = Depends(W_)):
    return await out(ctx, await _save_info(ctx, await _w(ctx, wid), body.clean()))


@router.put("/wedding/weddings/{wid}/events")
async def put_events(wid: str, body: dict, ctx: Ctx = Depends(W_)):
    w = await _w(ctx, wid)
    evs = [WEvent(**e) for e in (body.get("events") or [])][:12]
    if [e.key for e in evs].count("dj") != 1 or len({e.id for e in evs}) != len(evs):
        raise HTTPException(422, "Le Jour J est obligatoire et unique")
    old, new = {e["id"]: e for e in w.get("events", [])}, []
    for e in evs:
        if e.key not in ("wd", "dj", "br") and not e.key.startswith("x"):
            raise HTTPException(422, f"Type d'événement inconnu : {e.key}")
        d = {**e.model_dump(), "event_id": (old.get(e.id) or {}).get("event_id")}
        if e.key == "dj":
            d.update(enabled=True, fixed=True)
        new.append(d)
    for gone in set(old) - {e.id for e in evs}:
        if old[gone].get("event_id") and await db.events.find_one(ctx.q({"id": old[gone]["event_id"]}), {"_id": 0, "id": 1}):
            await ctx.delete("events", old[gone]["event_id"])
    w["events"] = new
    w["info"]["date"] = next(e for e in new if e["key"] == "dj")["date"]
    w["events"] = await sync_events(ctx, w)
    await wc.put(ctx, wc.W, wid, {"events": w["events"], "info": w["info"]})
    return await out(ctx, w)


@router.put("/wedding/weddings/{wid}/rights")
async def put_rights(wid: str, body: Rights, ctx: Ctx = Depends(W_)):
    await _w(ctx, wid)
    await wc.put(ctx, wc.W, wid, {"rights": body.model_dump()})
    return body


class LangIn(BaseModel):
    lang: Literal["fr", "en"]


@router.put("/wedding/weddings/{wid}/lang")
async def put_lang(wid: str, body: LangIn, ctx: Ctx = Depends(W_)):
    w = await _w(ctx, wid)
    w["lang"] = body.lang
    await sync_contacts(ctx, w)
    await wc.put(ctx, wc.W, wid, {"lang": body.lang})
    return {"lang": body.lang}


class SectionsIn(BaseModel):
    open_sections: List[str] = Field(max_length=20)


@router.put("/wedding/weddings/{wid}/open-sections")
async def put_sections(wid: str, body: SectionsIn, ctx: Ctx = Depends(W_)):
    await _w(ctx, wid)
    if set(body.open_sections) - AVAILABLE_SECTIONS:
        raise HTTPException(422, f"Rubriques pas encore disponibles : {sorted(set(body.open_sections) - AVAILABLE_SECTIONS)}")
    secs = [s for s in COUPLE_SECTIONS if s in set(body.open_sections) | {"home", "info", "quest"}]
    await wc.put(ctx, wc.W, wid, {"open_sections": secs})
    return {"open_sections": secs}


class NotesIn(BaseModel):
    notes: str = Field("", max_length=20000)


@router.put("/wedding/weddings/{wid}/notes")
async def put_notes(wid: str, body: NotesIn, ctx: Ctx = Depends(W_)):
    await _w(ctx, wid)
    await wc.put(ctx, wc.W, wid, {"notes": body.notes})
    return {"notes": body.notes}


class StatusIn(BaseModel):
    status: Literal["active", "archived"]


@router.put("/wedding/weddings/{wid}/status")
async def put_status(wid: str, body: StatusIn, ctx: Ctx = Depends(W_)):
    await _w(ctx, wid)
    await wc.put(ctx, wc.W, wid, {"status": body.status})
    return {"status": body.status}


# --- Compte et droits -----------------------------------------------------------------------------

@router.get("/wedding/weddings/{wid}/account")
async def account(wid: str, ctx: Ctx = Depends(R)):
    w = await _w(ctx, wid)
    partners = []
    for i, p in enumerate(w["info"]["partners"]):
        cid = (w.get("contact_ids") or [None, None])[i]
        u = await db.users.find_one({"org_id": ctx.org_id, "contact_id": cid, "role": "client"}, {"_id": 0}) if cid else None
        st = "not_invited" if not u else "accepted" if u.get("status") == "active" else "pending" if u.get("status") == "invited" else u.get("status")
        partners.append({"index": i, "first_name": p.get("first_name"), "email": p.get("email"), "status": st})
    return _j({"partners": partners, "lang": w.get("lang", "fr"), "rights": {**DEFAULT_RIGHTS, **(w.get("rights") or {})},
               "open_sections": w.get("open_sections", DEFAULT_OPEN_SECTIONS), "available_sections": sorted(AVAILABLE_SECTIONS)})


@router.post("/wedding/weddings/{wid}/invite/{i}")
async def invite(wid: str, i: int, request: Request, ctx: Ctx = Depends(W_)):
    if i not in (0, 1):
        raise HTTPException(404, "Partenaire introuvable")
    w = await _w(ctx, wid)
    if not w["info"]["partners"][i].get("email"):
        raise HTTPException(422, "Renseignez d'abord l'e-mail de ce partenaire")
    w["contact_ids"] = await sync_contacts(ctx, w)
    await wc.put(ctx, wc.W, wid, {"contact_ids": w["contact_ids"]})
    r = await _invite(request, ctx, w, i) or {}
    return {"sent": r.get("sent", False), "link": r.get("link")}


# --- Questionnaire ----------------------------------------------------------------------------------

@router.get("/wedding/weddings/{wid}/questionnaire")
async def questionnaire(wid: str, ctx: Ctx = Depends(R)):
    w, s = await _w(ctx, wid), await wc.settings(ctx)
    answers, on = await wc.merged_answers(ctx, wid), {e["key"] for e in w.get("events", []) if e.get("enabled")}
    titles = {r["key"]: r["title"] for r in s["rubrics"]}
    kept_fiche = {d["question_id"] for d in w.get("discrepancies", []) if d["status"] == "kept_fiche"}
    sections: list = []
    for q in await wc.find(ctx, wc.Q, sort=[("order", 1)]):
        a = answers.get(q["id"])
        if (q.get("event_key") and q["event_key"] not in on) or (q.get("status") == "deleted" and not a):
            continue
        if not sections or sections[-1]["title"] != q["section"]:
            sections.append({"title": q["section"], "questions": [], "answered": 0})
        txt = wc.answer_text(a)
        sections[-1]["answered"] += bool(txt)
        sections[-1]["questions"].append({"id": q["id"], "title": q["title"], "answer": txt, "files": (a or {}).get("files", []),
                                          "deleted": q.get("status") == "deleted", "to_classify": q.get("status") == "to_classify",
                                          "rubric": titles.get(q.get("rubric") or ""), "modified_in_fiche": q["id"] in kept_fiche})
    q = w.get("questionnaire") or {}
    return _j({"status": q.get("status", "pending"), "submitted_at": q.get("submitted_at"), "connected": bool(s.get("form_id")), "last_sync": s.get("last_sync"),
               "sections": sections, "discrepancies": [d for d in w.get("discrepancies", []) if d["status"] == "open"]})


class ResolveIn(BaseModel):
    keep: Literal["fiche", "form"]


@router.post("/wedding/weddings/{wid}/discrepancies/{did}/resolve")
async def resolve(wid: str, did: str, body: ResolveIn, ctx: Ctx = Depends(W_)):
    w = await _w(ctx, wid)
    d = next((x for x in w.get("discrepancies", []) if x["id"] == did and x["status"] == "open"), None)
    if not d:
        raise HTTPException(404, "Différence introuvable ou déjà traitée")
    if body.keep == "form":
        wc.set_path(w["info"], d["field"], d["form_value"])
    d["status"] = f"kept_{body.keep}"
    await wc.put(ctx, wc.W, wid, {"discrepancies": w["discrepancies"]})
    await _save_info(ctx, w, Info(**w["info"]).clean())
    return await out(ctx, await _w(ctx, wid))


@router.post("/wedding/questionnaire/sync")
async def sync(ctx: Ctx = Depends(W_)):
    return _j(await wc.sync(ctx))


@router.get("/wedding/questions")
async def questions(ctx: Ctx = Depends(R)):
    s = await wc.settings(ctx)
    qs = await wc.find(ctx, wc.Q, sort=[("order", 1)])
    return {"questions": [{k: q.get(k) for k in ("id", "number", "order", "section", "title", "kind", "rubric", "fiche_field", "module", "status", "suggestion")} for q in qs],
            "rubrics": s["rubrics"], "fiche_fields": FICHE_FIELDS, "modules": MODULE_LINKS}


class QuestionPatch(BaseModel):
    rubric: Optional[str] = None
    fiche_field: Optional[str] = None
    module: Optional[str] = None


@router.patch("/wedding/questions/{qid}")
async def patch_question(qid: str, body: QuestionPatch, ctx: Ctx = Depends(W_)):
    q = await wc.get(ctx, wc.Q, qid)
    if not q:
        raise HTTPException(404, "Question introuvable")
    ch = body.model_dump(exclude_unset=True)
    s = await wc.settings(ctx)
    if ch.get("rubric") and ch["rubric"] not in {r["key"] for r in s["rubrics"]}:
        raise HTTPException(422, "Rubrique inconnue")
    if ch.get("fiche_field") and ch["fiche_field"] not in FICHE_FIELDS:
        raise HTTPException(422, "Champ de fiche inconnu")
    if ch.get("module") and ch["module"] not in MODULE_LINKS:
        raise HTTPException(422, "Module inconnu")
    if ch.get("rubric") and q.get("status") == "to_classify":
        ch["status"] = "active"  # classée en un clic, choix mémorisé pour tous les couples
    await wc.put(ctx, wc.Q, qid, ch)
    return _j(await wc.get(ctx, wc.Q, qid))


@router.get("/wedding/responses/unassigned")
async def unassigned(ctx: Ctx = Depends(R)):
    rows = await wc.find(ctx, wc.R, {"wedding_id": None}, sort=[("submitted_at", -1)], limit=200)
    return [{"id": d["id"], "email": d.get("respondent_email"), "submitted_at": d.get("submitted_at"),
             "answers": sum(1 for a in (d.get("answers") or {}).values() if a.get("values") or a.get("files"))} for d in rows]


class AssignIn(BaseModel):
    wedding_id: Optional[str] = None


@router.put("/wedding/responses/{rid}/assign")
async def assign(rid: str, body: AssignIn, ctx: Ctx = Depends(W_)):
    if not await wc.get(ctx, wc.R, rid):
        raise HTTPException(404, "Réponse introuvable")
    if body.wedding_id:
        await _w(ctx, body.wedding_id)
    await wc.put(ctx, wc.R, rid, {"wedding_id": body.wedding_id})
    if body.wedding_id:
        await wc.on_response(ctx, body.wedding_id, False)
    return {"ok": True}


# --- Récapitulatif ------------------------------------------------------------------------------------

@router.get("/wedding/weddings/{wid}/recap")
async def recap(wid: str, ctx: Ctx = Depends(R)):
    await _w(ctx, wid)
    return _j(await wc.get(ctx, wc.REC, wid) or {"rubrics": [], "generated_at": None})


@router.post("/wedding/weddings/{wid}/recap/generate")
async def generate(wid: str, ctx: Ctx = Depends(W_)):
    return _j(await wc.generate_recap(ctx, await _w(ctx, wid)))


class RecapIn(BaseModel):
    text: str = Field(max_length=20000)


@router.patch("/wedding/weddings/{wid}/recap/{key}")
async def edit_recap(wid: str, key: str, body: RecapIn, ctx: Ctx = Depends(W_)):
    doc = await wc.get(ctx, wc.REC, wid)
    if not doc:
        raise HTTPException(404, "Récapitulatif pas encore généré")
    rubrics = [{**x, "text": body.text, "edited": body.text != x.get("generated")} if x["key"] == key else x for x in doc["rubrics"]]
    await wc.put(ctx, wc.REC, wid, {"rubrics": rubrics})
    return _j(await wc.get(ctx, wc.REC, wid))


@router.post("/wedding/weddings/{wid}/recap/{key}/proposal")
async def proposal(wid: str, key: str, accept: bool = True, ctx: Ctx = Depends(W_)):
    doc = await wc.get(ctx, wc.REC, wid)
    if not doc:
        raise HTTPException(404, "Récapitulatif pas encore généré")
    rubrics = []
    for x in doc["rubrics"]:
        if x["key"] == key and x.get("proposal") is not None:
            x = {**x, "text": x["proposal"], "generated": x["proposal"], "edited": False, "proposal": None} if accept else {**x, "generated": x["proposal"], "proposal": None}
        rubrics.append(x)
    await wc.put(ctx, wc.REC, wid, {"rubrics": rubrics})
    return _j(await wc.get(ctx, wc.REC, wid))


@router.get("/wedding/weddings/{wid}/recap/pdf")
async def recap_pdf(wid: str, ctx: Ctx = Depends(R)):
    w, doc = await _w(ctx, wid), await wc.get(ctx, wc.REC, wid)
    if not doc:
        raise HTTPException(404, "Récapitulatif pas encore généré")
    i = w["info"]
    body = wc.pdf(await _org(ctx), wc.names(i), "Récapitulatif · " + " · ".join(x for x in (i.get("date") or "", i.get("venue") or "") if x),
                  [(x["title"], x.get("text", "")) for x in doc["rubrics"]])
    return Response(body, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="recapitulatif.pdf"'})


# --- Repas et boissons ---------------------------------------------------------------------------------

def _food(f: dict | None, guests: int | None) -> dict | None:
    if not f:
        return None
    ext = [{**x, "quantity": None if guests is None else -(-int(guests * x["per_guest"] * 1000) // 1000)} for x in f.get("external", [])]
    return {**{k: f.get(k) for k in ("vendor", "formula", "price", "courses", "included", "notes")}, "external": ext}


async def _food_view(ctx: Ctx, w: dict, key: str) -> dict:
    ev = next((e for e in w.get("events", []) if e["key"] == key), None)
    if not ev:
        raise HTTPException(404, "Événement introuvable")
    g, src = wc.guests_for(ev, await wc.confirmed_counts(ctx, w))
    f = await wc.get(ctx, wc.FOOD, f"{w['id']}:{key}")
    return {"event": ev, "enabled": ev.get("enabled"), "guests": g, "guests_source": src, "food": _food(f if f and f.get("vendor") else None, g),
            "diets": [], "kids": None}  # contraintes alimentaires : depuis la Guest List (phase 2)


@router.get("/wedding/weddings/{wid}/food/{key}")
async def get_food(wid: str, key: str, ctx: Ctx = Depends(R)):
    return _j(await _food_view(ctx, await _w(ctx, wid), key))


@router.put("/wedding/weddings/{wid}/food/{key}")
async def put_food(wid: str, key: str, body: FoodIn, ctx: Ctx = Depends(W_)):
    w = await _w(ctx, wid)
    await _food_view(ctx, w, key)
    await wc.put(ctx, wc.FOOD, f"{wid}:{key}", {**body.model_dump(), "wedding_id": wid, "event_key": key})
    return _j(await _food_view(ctx, w, key))


@router.get("/wedding/weddings/{wid}/food/{key}/pdf")
async def food_pdf(wid: str, key: str, ctx: Ctx = Depends(R)):
    w = await _w(ctx, wid)
    v = await _food_view(ctx, w, key)
    f = v["food"]
    if not f:
        raise HTTPException(404, "Aucun traiteur rattaché à cet événement")
    u = {"bottle": "bouteilles", "keg": "fûts", "l": "litres"}
    secs = [("Prestation", f"{f['vendor']}\nFormule : {f['formula']}\nInvités : {v['guests'] if v['guests'] is not None else 'à confirmer'}"),
            ("Menu", "\n".join(f"{c['name']} : {c['chosen']}" for c in f["courses"])),
            ("Boissons incluses", "\n".join(f"{d['name']} : {d['detail']}" for d in f["included"])),
            ("Boissons d'un autre fournisseur", "\n".join(f"{d['name']} ({d['supplier']}) : {d['quantity'] if d['quantity'] is not None else '?'} {u[d['unit']]}" for d in f["external"])),
            ("Contraintes alimentaires", "Calculées depuis la Guest List dès qu'elle sera disponible.")]
    body = wc.pdf(await _org(ctx), f"{wc.names(w['info'])} · {v['event']['name']}", f"Fiche traiteur · {v['event'].get('date') or ''}", secs)
    return Response(body, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="traiteur-{key}.pdf"'})


# --- Notifications et réglages ----------------------------------------------------------------------------

@router.get("/wedding/notifications")
async def notifications(ctx: Ctx = Depends(R)):
    rows = await wc.find(ctx, wc.NOTIF, sort=[("created_at", -1)], limit=50)
    return {"unread": await db[wc.NOTIF].count_documents(ctx.q({"read": False})),
            "items": [{"id": d["id"], "kind": d["kind"], "text": d["text"], "wedding_id": d.get("wedding_id"), "read": d["read"], "at": d["created_at"]} for d in rows]}


@router.post("/wedding/notifications/read-all")
async def read_all(ctx: Ctx = Depends(R)):
    await db[wc.NOTIF].update_many(ctx.q({"read": False}), {"$set": {"read": True}})
    return {"ok": True}


@router.get("/wedding/settings")
async def get_settings(ctx: Ctx = Depends(R)):
    s = await wc.settings(ctx)
    return _j({**{k: s.get(k) for k in ("form_id", "form_url", "notify_email", "notification_prefs", "rubrics", "last_sync", "sync_error", "form_title")},
               "notification_types": NOTIFICATION_TYPES, "google_configured": bool(wc.service_account_email()), "service_account": wc.service_account_email()})


class SettingsIn(BaseModel):
    form_url: Optional[str] = Field(None, max_length=500)
    notify_email: Optional[EmailStr] = None
    notification_prefs: Optional[dict] = None
    rubrics: Optional[List[dict]] = Field(None, max_length=40)


@router.put("/wedding/settings")
async def put_settings(body: SettingsIn, ctx: Ctx = Depends(W_)):
    ch = body.model_dump(exclude_unset=True, mode="json")
    if "form_url" in ch:
        m = re.search(r"/forms/d/(?:e/)?([A-Za-z0-9_-]{20,})", ch["form_url"] or "")
        ch["form_id"] = m.group(1) if m else None
    if "rubrics" in ch:
        keys = [r.get("key") for r in ch["rubrics"]]
        if len(set(keys)) != len(keys) or not all(keys) or not all(str(r.get("title") or "").strip() for r in ch["rubrics"]):
            raise HTTPException(422, "Chaque rubrique a une clé unique et un titre")
        ch["rubrics"] = [{"key": str(r["key"])[:40], "title": str(r["title"])[:120]} for r in ch["rubrics"]]
    if "notification_prefs" in ch:
        ch["notification_prefs"] = {k: {"app": bool(v.get("app")), "email": bool(v.get("email"))} for k, v in ch["notification_prefs"].items() if k in NOTIFICATION_TYPES}
    await wc.settings(ctx)
    await wc.put(ctx, wc.SET, "settings", ch)
    return await get_settings(ctx)


# --- Espace des mariés (portail client) ---------------------------------------------------------------------

PREVIEW_HEADER = "x-view-as-wedding"


async def couple(request: Request, member: dict = Depends(current_member)) -> tuple:
    """Mariés connectés, ou « Voir comme les mariés » : l'équipe (events:read) voit l'espace d'un mariage en lecture seule,
    sans compte ni identifiants du couple. Les droits du couple s'appliquent à l'identique ; chaque ouverture est journalisée."""
    wid = request.headers.get(PREVIEW_HEADER)
    if wid:
        ctx = await _R(request, member)
        if request.method != "GET":
            raise HTTPException(403, "Aperçu : lecture seule")
        org = await _org(ctx)
        if wc.MODULE not in (org.get("modules") or []):
            raise HTTPException(403, "Module Wedding planner non activé")
        w = await db[wc.W].find_one(ctx.q({"id": wid, "status": {"$ne": "deleted"}}), {"_id": 0})
        if not w:
            raise HTTPException(404, "Introuvable")
        ctx.preview = True
        if request.url.path.rstrip("/").endswith("/portal/wedding"):
            await audit(ctx.org_id, member, "wedding_preview", w["id"], f"Aperçu de l'espace des mariés : {wc.names(w['info'])}")
        return ctx, w, org
    ctx = await _C(request, member)
    org = await _org(ctx)
    if wc.MODULE not in (org.get("modules") or []) or not ctx.contact_id:
        raise HTTPException(404, "Introuvable")
    w = await db[wc.W].find_one(ctx.q({"contact_ids": ctx.contact_id, "status": "active"}), {"_id": 0})
    if not w:
        raise HTTPException(404, "Introuvable")
    return ctx, w, org


def _rights(w: dict) -> dict:
    return {**DEFAULT_RIGHTS, **(w.get("rights") or {})}


def _public_info(w: dict) -> dict:
    i = _j(w["info"])
    if not _rights(w)["budget"]:
        i["budget"] = None
    return i


@router.get("/portal/wedding")
async def portal_home(c=Depends(couple)):
    ctx, w, org = c
    i = w["info"]
    complete = all(p.get("first_name") and p.get("last_name") and p.get("email") and p.get("phone") for p in i["partners"]) and bool(i.get("date"))
    q = w.get("questionnaire") or {}
    return _j({"id": w["id"], "names": wc.names(i), "lang": w.get("lang", "fr"), "date": i.get("date"), "venue": i.get("venue"), "days_left": wc.days_left(i.get("date")),
               "sections": COUPLE_SECTIONS, "open_sections": w.get("open_sections", DEFAULT_OPEN_SECTIONS),
               "steps": {"info": "complete" if complete else "todo", "quest": q.get("status", "pending"), "quest_submitted_at": q.get("submitted_at")},
               "events": [{"key": e["key"], "name": e["name"], "date": e.get("date")} for e in w.get("events", []) if e.get("enabled")],
               "can_edit_info": _rights(w)["edit_info"] and not ctx.preview, "preview": ctx.preview, "design": {**DESIGN, "app_name": org.get("name"), **(org.get("wp_branding") or {})}})


@router.get("/portal/wedding/info")
async def portal_info(c=Depends(couple)):
    ctx, w, _ = c
    return {"info": _public_info(w), "can_edit": _rights(w)["edit_info"] and not ctx.preview, "budget_visible": _rights(w)["budget"]}


@router.put("/portal/wedding/info")
async def portal_put_info(body: Info, c=Depends(couple)):
    ctx, w, _ = c
    if ctx.preview:
        raise HTTPException(403, "Aperçu : lecture seule")
    if not _rights(w)["edit_info"]:
        raise HTTPException(403, "La modification de la fiche n'est pas ouverte pour le moment")
    new, old = body.clean(), w["info"]
    new["guests"] = old.get("guests") or {}  # calculé : jamais saisi par les mariés
    if not _rights(w)["budget"]:
        new["budget"] = old.get("budget")
    changed = sorted({k for k in new if _j(new[k]) != _j(old.get(k))})
    if changed:
        # Fiche modifiée par les mariés : les contacts et événements liés sont mis à jour au nom du module
        system = Ctx({"org_id": ctx.org_id, "role": "admin", "user_id": ctx.member["user_id"], "name": f"Espace mariés ({ctx.member.get('name', '')})"})
        await _save_info(system, w, new)
        labels = {"partners": "coordonnées", "date": "date", "venue": "lieu", "venue_address": "adresse du lieu", "budget": "budget", "ceremony": "cérémonie", "same_address": "adresse"}
        await wc.notify(ctx, "info_changed", f"{wc.names(new)} ont modifié leur fiche : {', '.join(labels.get(k, k) for k in changed)}.", w["id"])
    return {"info": _public_info(w)}


@router.get("/portal/wedding/questionnaire")
async def portal_questionnaire(c=Depends(couple)):
    ctx, w, _ = c
    s = await wc.settings(ctx)
    qs = await wc.find(ctx, wc.Q, {"fiche_field": {"$ne": None}}, limit=200)
    resp = s.get("responder_uri") or s.get("form_url")
    q = w.get("questionnaire") or {}
    return _j({"status": q.get("status", "pending"), "submitted_at": q.get("submitted_at"), "embed_url": wc.prefilled_url(resp, qs, w["info"]),
               "open_url": resp, "known_fields": wc.known_fields(w["info"]), "preview": ctx.preview})


@router.get("/portal/wedding/food/{key}")
async def portal_food(key: str, c=Depends(couple)):
    ctx, w, _ = c
    if "food" not in w.get("open_sections", DEFAULT_OPEN_SECTIONS):
        raise HTTPException(404, "Rubrique pas encore ouverte")
    v = await _food_view(ctx, w, key)
    if not v["enabled"]:
        return {"event": {"key": key, "name": v["event"]["name"]}, "enabled": False}
    if v["food"]:
        v["food"].pop("notes", None)  # notes internes : jamais visibles des mariés
        if not _rights(w)["vendor_prices"]:
            v["food"]["price"] = None
    v["event"] = {"key": key, "name": v["event"]["name"], "date": v["event"].get("date")}
    return _j(v)
