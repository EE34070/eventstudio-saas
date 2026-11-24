"""Routes internes (espace de l'organisatrice) : /api/wedding-planner/*.

Toutes passent par guard("wedding_planner", ...) et TenantRepository.
"""
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.config import get_settings as app_settings
from app.core.rbac import Role
from app.core.tenancy import TenantContext, guard
from app.platform.invitations import create_invitation, invitation_statuses
from app.platform.mailer import send_email

from . import forms as F
from . import recap as R
from . import service as S
from .models import (
    AssignResponse,
    EventsIn,
    FoodIn,
    Lang,
    NotesIn,
    OpenSectionsIn,
    QuestionPatch,
    RecapPatch,
    ResolveDiscrepancy,
    Rights,
    SettingsIn,
    WeddingCreate,
    WeddingInfo,
)
from .seed import (
    AVAILABLE_SECTIONS,
    COUPLE_SECTIONS,
    DEFAULT_OPEN_SECTIONS,
    DEFAULT_RIGHTS,
    FICHE_FIELDS,
    MODULE_LINKS,
    NOTIFICATION_TYPES,
)

router = APIRouter(prefix="/wedding-planner", tags=["wedding_planner"])
read = guard(S.MODULE, "read")
write = guard(S.MODULE, "write")


def _jsonable(d):
    return json.loads(json.dumps(d, default=str))


async def _wedding(ctx: TenantContext, wid: str) -> dict:
    w = await S.repo(ctx, S.WEDDINGS).get(wid)
    if not w:
        raise HTTPException(404, "Mariage introuvable")
    return w


async def wedding_out(ctx: TenantContext, w: dict) -> dict:
    confirmed = await S.confirmed_counts(ctx, w)
    events = []
    for e in w.get("events", []):
        g, src = S.guests_for(e, confirmed)
        events.append({**e, "confirmed": confirmed.get(e["id"]), "guests": g, "guests_source": src})
    return _jsonable({
        "id": w["_id"], "names": S.couple_names(w["info"]), "info": w["info"], "events": events,
        "lang": w.get("lang", "fr"), "rights": w.get("rights", DEFAULT_RIGHTS),
        "open_sections": w.get("open_sections", DEFAULT_OPEN_SECTIONS), "notes": w.get("notes", ""),
        "status": w.get("status", "active"), "days_left": S.days_left(w["info"].get("date")),
        "progress": S.progress(w), "questionnaire": w.get("questionnaire") or {"status": "pending"},
        "discrepancies": [d for d in w.get("discrepancies", []) if d["status"] == "open"],
        "contact_ids": w.get("contact_ids", []),
    })


def _card(w: dict, confirmed: dict) -> dict:
    info = w["info"]
    dj = next((e for e in w.get("events", []) if e["key"] == "dj"), None)
    guests = (confirmed.get(dj["id"]) if dj else None) or WeddingInfo(**info).guests.total or (dj or {}).get("estimate")
    return {
        "id": w["_id"], "names": S.couple_names(info), "date": info.get("date"), "days_left": S.days_left(info.get("date")),
        "venue": info.get("venue"), "guests": guests, "budget": info.get("budget"), "progress": S.progress(w),
        "questionnaire": (w.get("questionnaire") or {}).get("status", "pending"),
        "open_discrepancies": sum(1 for d in w.get("discrepancies", []) if d["status"] == "open"),
        # Alimentés par les modules suivants (prestataires, documents, paiements, tâches)
        "vendors": None, "documents": None, "next_payment": None, "next_task": None,
    }


# --- Tableau de bord ----------------------------------------------------------------

@router.get("/weddings")
async def list_weddings(archived: bool = False, ctx: TenantContext = Depends(read)):
    flt = {"status": "archived"} if archived else {"status": {"$ne": "archived"}}
    docs = await S.repo(ctx, S.WEDDINGS).find(flt, sort=[("info.date", 1)], limit=500)
    cards = [_card(w, await S.confirmed_counts(ctx, w)) for w in docs]
    cards.sort(key=lambda c: (c["date"] is None, c["date"] or ""))
    return _jsonable(cards)


async def _send_invite(request: Request, ctx: TenantContext, w: dict, i: int) -> dict | None:
    p = w["info"]["partners"][i]
    cid = (w.get("contact_ids") or [None, None])[i]
    if not p.get("email") or not cid:
        return None
    inv, token = await create_invitation(request, ctx, email=p["email"], role=Role.CLIENT, module=S.MODULE,
                                         contact_id=cid, scope={"wedding_id": w["_id"], "partner": i},
                                         lang=w.get("lang", "fr"))
    if token:
        org = ctx.org.get("branding", {}).get("app_name") or ctx.org.get("name", "")
        link = f"{app_settings().APP_URL}/invitation/{token}"
        if w.get("lang") == "en":
            subject, html = (f"{org}: your wedding space is ready",
                             f"<p>Hello{(' ' + p['first_name']) if p.get('first_name') else ''},</p>"
                             f"<p>Your private wedding space with {org} is ready. You will find your information, "
                             f"your questionnaire and, step by step, everything about your wedding.</p>"
                             f'<p><a href="{link}">Open my space</a></p>')
        else:
            subject, html = (f"{org} : votre espace mariage est prêt",
                             f"<p>Bonjour{(' ' + p['first_name']) if p.get('first_name') else ''},</p>"
                             f"<p>Votre espace privé avec {org} est prêt. Vous y retrouverez vos informations, "
                             f"votre questionnaire et, au fil de l'organisation, tout ce qui concerne votre mariage.</p>"
                             f'<p><a href="{link}">Ouvrir mon espace</a></p>')
        await send_email(p["email"], subject, html)
    return inv


@router.post("/weddings", status_code=201)
async def create_wedding(body: WeddingCreate, request: Request, ctx: TenantContext = Depends(write)):
    info = WeddingInfo(date=body.date)
    info.partners[0].email = body.partner1_email
    info.partners[0].first_name = body.partner1_first_name
    info.partners[1].email = body.partner2_email
    info.partners[1].first_name = body.partner2_first_name
    w = {
        "_id": uuid4().hex, "info": info.model_dump(mode="json"), "lang": body.lang,
        "events": S.default_events(body.date, body.welcome_dinner, body.brunch),
        "rights": dict(DEFAULT_RIGHTS), "open_sections": list(DEFAULT_OPEN_SECTIONS), "notes": "",
        "status": "active", "discrepancies": [], "questionnaire": {"status": "pending"},
    }
    w["contact_ids"] = await S.ensure_contacts(ctx, w)
    w["events"] = await S.sync_core_events(ctx, w)
    doc = await S.repo(ctx, S.WEDDINGS).insert(w)
    if body.send_invitations:
        for i in (0, 1):
            await _send_invite(request, ctx, doc, i)
    return await wedding_out(ctx, doc)


@router.get("/weddings/{wid}")
async def get_wedding(wid: str, ctx: TenantContext = Depends(read)):
    return await wedding_out(ctx, await _wedding(ctx, wid))


@router.put("/weddings/{wid}/info")
async def update_info(wid: str, body: WeddingInfo, ctx: TenantContext = Depends(write)):
    w = await _wedding(ctx, wid)
    w["info"] = body.normalized().model_dump(mode="json")
    w["contact_ids"] = await S.ensure_contacts(ctx, w)
    # La date du Jour J suit la date du mariage
    for e in w["events"]:
        if e["key"] == "dj":
            e["date"] = w["info"]["date"]
            e["place"] = e.get("place") or w["info"]["venue"]
    w["events"] = await S.sync_core_events(ctx, w)
    await S.repo(ctx, S.WEDDINGS).update(wid, {"info": w["info"], "contact_ids": w["contact_ids"], "events": w["events"]})
    return await wedding_out(ctx, await _wedding(ctx, wid))


@router.put("/weddings/{wid}/events")
async def update_events(wid: str, body: EventsIn, ctx: TenantContext = Depends(write)):
    w = await _wedding(ctx, wid)
    old = {e["id"]: e for e in w.get("events", [])}
    keys = [e.key for e in body.events]
    if keys.count("dj") != 1 or len(set(e.id for e in body.events)) != len(body.events):
        raise HTTPException(422, "Le Jour J est obligatoire et unique")
    events = []
    for e in body.events:
        d = e.model_dump()
        if e.key == "dj":
            d.update(enabled=True, fixed=True, name=d["name"] or "Jour J")
        elif e.key not in ("wd", "br") and not e.key.startswith("x"):
            raise HTTPException(422, f"Type d'événement inconnu : {e.key}")
        d["event_id"] = (old.get(e.id) or {}).get("event_id")
        events.append(d)
    for gone in set(old) - {e.id for e in body.events}:
        if old[gone].get("event_id"):
            await S.repo(ctx, "events").update(old[gone]["event_id"], {"status": "canceled"})
    w["events"] = events
    dj = next(e for e in events if e["key"] == "dj")
    if dj["date"] != w["info"].get("date"):
        w["info"]["date"] = dj["date"]
    w["events"] = await S.sync_core_events(ctx, w)
    await S.repo(ctx, S.WEDDINGS).update(wid, {"events": w["events"], "info": w["info"]})
    return await wedding_out(ctx, await _wedding(ctx, wid))


@router.put("/weddings/{wid}/rights")
async def update_rights(wid: str, body: Rights, ctx: TenantContext = Depends(write)):
    await _wedding(ctx, wid)
    await S.repo(ctx, S.WEDDINGS).update(wid, {"rights": body.model_dump()})
    return body


class LangIn(BaseModel):
    lang: Lang


@router.put("/weddings/{wid}/lang")
async def update_lang(wid: str, body: LangIn, ctx: TenantContext = Depends(write)):
    w = await _wedding(ctx, wid)
    w["lang"] = body.lang
    await S.ensure_contacts(ctx, w)
    await S.repo(ctx, S.WEDDINGS).update(wid, {"lang": body.lang})
    return {"lang": body.lang}


@router.put("/weddings/{wid}/open-sections")
async def update_open_sections(wid: str, body: OpenSectionsIn, ctx: TenantContext = Depends(write)):
    await _wedding(ctx, wid)
    sections = [s for s in COUPLE_SECTIONS if s in set(body.open_sections) | {"home", "info", "quest"}]
    unknown = set(body.open_sections) - AVAILABLE_SECTIONS
    if unknown:
        raise HTTPException(422, f"Rubriques pas encore disponibles : {sorted(unknown)}")
    await S.repo(ctx, S.WEDDINGS).update(wid, {"open_sections": sections})
    return {"open_sections": sections}


@router.put("/weddings/{wid}/notes")
async def update_notes(wid: str, body: NotesIn, ctx: TenantContext = Depends(write)):
    await _wedding(ctx, wid)
    await S.repo(ctx, S.WEDDINGS).update(wid, {"notes": body.notes})
    return {"notes": body.notes}


class StatusIn(BaseModel):
    status: str


@router.put("/weddings/{wid}/status")
async def update_status(wid: str, body: StatusIn, ctx: TenantContext = Depends(write)):
    if body.status not in {"active", "archived"}:
        raise HTTPException(422, "Statut inconnu")
    await _wedding(ctx, wid)
    await S.repo(ctx, S.WEDDINGS).update(wid, {"status": body.status})
    return {"status": body.status}


@router.delete("/weddings/{wid}", status_code=204)
async def delete_wedding(wid: str, ctx: TenantContext = Depends(write)):
    await _wedding(ctx, wid)
    await S.repo(ctx, S.WEDDINGS).soft_delete(wid)  # corbeille, purge après 30 jours


# --- Compte et droits -----------------------------------------------------------------

@router.get("/weddings/{wid}/account")
async def account(wid: str, request: Request, ctx: TenantContext = Depends(read)):
    w = await _wedding(ctx, wid)
    ids = [c for c in w.get("contact_ids", []) if c]
    statuses = await invitation_statuses(request, ctx.org_id, S.MODULE, ids)
    partners = []
    for i, p in enumerate(w["info"]["partners"]):
        cid = (w.get("contact_ids") or [None, None])[i]
        st = statuses.get(cid or "", {})
        partners.append({"index": i, "first_name": p.get("first_name"), "email": p.get("email"),
                         "status": st.get("status", "not_invited"), "sent_count": st.get("sent_count", 0)})
    return _jsonable({"partners": partners, "lang": w.get("lang", "fr"), "rights": w.get("rights", DEFAULT_RIGHTS),
                      "open_sections": w.get("open_sections", DEFAULT_OPEN_SECTIONS),
                      "available_sections": sorted(AVAILABLE_SECTIONS)})


@router.post("/weddings/{wid}/invite/{index}")
async def invite(wid: str, index: int, request: Request, ctx: TenantContext = Depends(write)):
    if index not in (0, 1):
        raise HTTPException(404, "Partenaire introuvable")
    w = await _wedding(ctx, wid)
    if not w["info"]["partners"][index].get("email"):
        raise HTTPException(422, "Renseignez d'abord l'e-mail de ce partenaire")
    w["contact_ids"] = await S.ensure_contacts(ctx, w)
    await S.repo(ctx, S.WEDDINGS).update(wid, {"contact_ids": w["contact_ids"]})
    inv = await _send_invite(request, ctx, w, index)
    return {"status": (inv or {}).get("status", "not_invited")}


# --- Questionnaire -----------------------------------------------------------------------

@router.get("/weddings/{wid}/questionnaire")
async def wedding_questionnaire(wid: str, ctx: TenantContext = Depends(read)):
    w = await _wedding(ctx, wid)
    answers = await F.merged_answers(ctx, wid)
    enabled = {e["key"] for e in w.get("events", []) if e.get("enabled")}
    settings = await S.get_settings(ctx)
    rubrics = {r["key"]: r["title"] for r in settings["rubrics"]}
    modified = {d["question_id"] for d in w.get("discrepancies", []) if d["status"] == "kept_fiche"}
    sections: list[dict] = []
    for q in await S.repo(ctx, S.QUESTIONS).find({}, sort=[("order", 1)], limit=500):
        if q.get("event_key") and q["event_key"] not in enabled:
            continue
        a = answers.get(q["_id"])
        if q.get("status") == "deleted" and not a:
            continue
        if not sections or sections[-1]["title"] != q["section"]:
            sections.append({"title": q["section"], "questions": []})
        sections[-1]["questions"].append({
            "id": q["_id"], "title": q["title"], "kind": q["kind"], "answer": F.answer_text(a),
            "files": (a or {}).get("files", []), "rows": (a or {}).get("rows", {}),
            "deleted": q.get("status") == "deleted", "to_classify": q.get("status") == "to_classify",
            "rubric": rubrics.get(q.get("rubric") or "", None), "modified_in_fiche": q["_id"] in modified,
        })
    for s in sections:
        s["answered"] = sum(1 for q in s["questions"] if q["answer"])
    return _jsonable({"status": (w.get("questionnaire") or {}).get("status", "pending"),
                      "submitted_at": (w.get("questionnaire") or {}).get("submitted_at"),
                      "connected": bool(settings.get("form_id")), "last_sync": settings.get("last_sync"),
                      "sections": sections,
                      "discrepancies": [d for d in w.get("discrepancies", []) if d["status"] == "open"]})


@router.post("/weddings/{wid}/discrepancies/{did}/resolve")
async def resolve(wid: str, did: str, body: ResolveDiscrepancy, ctx: TenantContext = Depends(write)):
    w = await _wedding(ctx, wid)
    try:
        info, discrepancies = F.resolve_discrepancy(w, did, body.keep)
    except KeyError:
        raise HTTPException(404, "Différence introuvable ou déjà traitée")
    info = WeddingInfo(**info).normalized().model_dump(mode="json")
    await S.repo(ctx, S.WEDDINGS).update(wid, {"info": info, "discrepancies": discrepancies})
    return await wedding_out(ctx, await _wedding(ctx, wid))


@router.post("/questionnaire/sync")
async def sync_questionnaire(ctx: TenantContext = Depends(write)):
    return _jsonable(await F.sync(ctx))


@router.get("/questions")
async def list_questions(ctx: TenantContext = Depends(read)):
    settings = await S.get_settings(ctx)
    qs = await S.repo(ctx, S.QUESTIONS).find({}, sort=[("order", 1)], limit=500)
    return _jsonable({
        "questions": [{"id": q["_id"], "number": q.get("number"), "order": q.get("order"), "section": q["section"],
                       "title": q["title"], "kind": q["kind"], "rubric": q.get("rubric"), "fiche_field": q.get("fiche_field"),
                       "module": q.get("module"), "status": q.get("status"), "suggestion": q.get("suggestion")}
                      for q in qs],
        "rubrics": settings["rubrics"], "fiche_fields": FICHE_FIELDS, "modules": MODULE_LINKS,
    })


@router.patch("/questions/{item_id}")
async def patch_question(item_id: str, body: QuestionPatch, ctx: TenantContext = Depends(write)):
    r = S.repo(ctx, S.QUESTIONS)
    q = await r.get(item_id)
    if not q:
        raise HTTPException(404, "Question introuvable")
    changes = body.model_dump(exclude_unset=True)
    settings = await S.get_settings(ctx)
    if changes.get("rubric") and changes["rubric"] not in {x["key"] for x in settings["rubrics"]}:
        raise HTTPException(422, "Rubrique inconnue")
    if changes.get("fiche_field") and changes["fiche_field"] not in FICHE_FIELDS:
        raise HTTPException(422, "Champ de fiche inconnu")
    if changes.get("module") and changes["module"] not in MODULE_LINKS:
        raise HTTPException(422, "Module inconnu")
    # Classer une question la sort de « À classer » ; le choix vaut pour tous les couples
    if changes.get("rubric") and q.get("status") == "to_classify":
        changes["status"] = "active"
    await r.update(item_id, changes)
    return _jsonable(await r.get(item_id))


@router.get("/responses/unassigned")
async def unassigned(ctx: TenantContext = Depends(read)):
    docs = await S.repo(ctx, S.RESPONSES).find({"wedding_id": None}, sort=[("submitted_at", -1)], limit=200)
    return _jsonable([{"id": d["_id"], "email": d.get("respondent_email"), "submitted_at": d.get("submitted_at"),
                       "answers": sum(1 for a in d.get("answers", {}).values() if a.get("values") or a.get("files"))}
                      for d in docs])


@router.put("/responses/{rid}/assign")
async def assign(rid: str, body: AssignResponse, ctx: TenantContext = Depends(write)):
    r = S.repo(ctx, S.RESPONSES)
    if not await r.get(rid):
        raise HTTPException(404, "Réponse introuvable")
    if body.wedding_id:
        await _wedding(ctx, body.wedding_id)
    await r.update(rid, {"wedding_id": body.wedding_id})
    if body.wedding_id:
        await F.on_response(ctx, body.wedding_id, is_update=False)
    return {"ok": True}


# --- Récapitulatif -----------------------------------------------------------------------

@router.get("/weddings/{wid}/recap")
async def get_recap(wid: str, ctx: TenantContext = Depends(read)):
    await _wedding(ctx, wid)
    doc = await S.repo(ctx, S.RECAPS).get(wid)
    return _jsonable(doc or {"rubrics": [], "generated_at": None})


@router.post("/weddings/{wid}/recap/generate")
async def generate_recap(wid: str, ctx: TenantContext = Depends(write)):
    return _jsonable(await R.generate(ctx, await _wedding(ctx, wid)))


async def _recap_doc(ctx: TenantContext, wid: str) -> dict:
    doc = await S.repo(ctx, S.RECAPS).get(wid)
    if not doc:
        raise HTTPException(404, "Récapitulatif pas encore généré")
    return doc


@router.patch("/weddings/{wid}/recap/{key}")
async def edit_recap(wid: str, key: str, body: RecapPatch, ctx: TenantContext = Depends(write)):
    doc = await _recap_doc(ctx, wid)
    rubrics = [({**x, "text": body.text, "edited": body.text != x.get("generated")} if x["key"] == key else x)
               for x in doc["rubrics"]]
    await S.repo(ctx, S.RECAPS).update(wid, {"rubrics": rubrics})
    return _jsonable(await S.repo(ctx, S.RECAPS).get(wid))


@router.post("/weddings/{wid}/recap/{key}/proposal")
async def proposal(wid: str, key: str, accept: bool = True, ctx: TenantContext = Depends(write)):
    doc = await _recap_doc(ctx, wid)
    out = []
    for x in doc["rubrics"]:
        if x["key"] == key and x.get("proposal") is not None:
            x = ({**x, "text": x["proposal"], "generated": x["proposal"], "edited": False, "proposal": None} if accept
                 else {**x, "generated": x["proposal"], "proposal": None})
        out.append(x)
    await S.repo(ctx, S.RECAPS).update(wid, {"rubrics": out})
    return _jsonable(await S.repo(ctx, S.RECAPS).get(wid))


@router.get("/weddings/{wid}/recap.pdf")
async def recap_pdf(wid: str, ctx: TenantContext = Depends(read)):
    w = await _wedding(ctx, wid)
    doc = await _recap_doc(ctx, wid)
    info = w["info"]
    sub = " · ".join(x for x in [info.get("date") or "", info.get("venue") or ""] if x)
    pdf = R.pdf_document(ctx, S.couple_names(info), f"Récapitulatif · {sub}",
                         [(x["title"], x.get("text", "")) for x in doc["rubrics"]])
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="recapitulatif-{wid[:8]}.pdf"'})


# --- Repas et boissons -------------------------------------------------------------------

def _food_id(wid: str, key: str) -> str:
    return f"{wid}:{key}"


async def _event(ctx: TenantContext, w: dict, key: str) -> dict:
    ev = next((e for e in w.get("events", []) if e["key"] == key), None)
    if not ev:
        raise HTTPException(404, "Événement introuvable")
    return ev


def food_out(food: dict | None, guests: int | None) -> dict | None:
    if not food:
        return None
    ext = [{**x, "quantity": None if guests is None else -(-guests * x["per_guest"] // 1)} for x in food.get("external", [])]
    for x in ext:
        if x["quantity"] is not None:
            x["quantity"] = int(x["quantity"])
    return {**{k: food.get(k) for k in ("vendor", "formula", "price", "courses", "included", "notes")}, "external": ext}


@router.get("/weddings/{wid}/food/{key}")
async def get_food(wid: str, key: str, ctx: TenantContext = Depends(read)):
    w = await _wedding(ctx, wid)
    ev = await _event(ctx, w, key)
    guests, src = S.guests_for(ev, await S.confirmed_counts(ctx, w))
    food = await S.repo(ctx, S.FOOD).get(_food_id(wid, key))
    return _jsonable({"event": ev, "guests": guests, "guests_source": src, "food": food_out(food, guests),
                      "diets": [], "kids": None})  # contraintes : calculées depuis la Guest List (phase 2)


@router.put("/weddings/{wid}/food/{key}")
async def put_food(wid: str, key: str, body: FoodIn, ctx: TenantContext = Depends(write)):
    w = await _wedding(ctx, wid)
    await _event(ctx, w, key)
    r = S.repo(ctx, S.FOOD)
    fid = _food_id(wid, key)
    data = {**body.model_dump(), "wedding_id": wid, "event_key": key}
    if not body.vendor:
        if await r.get(fid):
            await r.soft_delete(fid)
    elif await r.get(fid):
        await r.update(fid, data)
    else:
        await r.insert({"_id": fid, **data})
    return await get_food(wid, key, ctx)


@router.get("/weddings/{wid}/food/{key}/pdf")
async def food_pdf(wid: str, key: str, ctx: TenantContext = Depends(read)):
    w = await _wedding(ctx, wid)
    ev = await _event(ctx, w, key)
    guests, _ = S.guests_for(ev, await S.confirmed_counts(ctx, w))
    food = food_out(await S.repo(ctx, S.FOOD).get(_food_id(wid, key)), guests)
    if not food:
        raise HTTPException(404, "Aucun traiteur rattaché à cet événement")
    units = {"bottle": "bouteilles", "keg": "fûts", "l": "litres"}
    sections = [
        ("Prestation", f"{food['vendor']}\nFormule : {food['formula']}\nInvités : {guests if guests is not None else 'à confirmer'}"),
        ("Menu", "\n".join(f"{c['name']} : {c['chosen']}" for c in food["courses"])),
        ("Boissons incluses", "\n".join(f"{d['name']} : {d['detail']}" for d in food["included"])),
        ("Boissons d'un autre fournisseur", "\n".join(
            f"{d['name']} ({d['supplier']}) : {d['quantity'] if d['quantity'] is not None else '?'} {units[d['unit']]}"
            for d in food["external"])),
        ("Contraintes alimentaires", "Calculées depuis la Guest List dès qu'elle sera disponible."),
    ]
    pdf = R.pdf_document(ctx, f"{S.couple_names(w['info'])} · {ev['name']}", f"Fiche traiteur · {ev.get('date') or ''}", sections)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="traiteur-{key}-{wid[:8]}.pdf"'})


# --- Notifications et réglages ---------------------------------------------------------

@router.get("/notifications")
async def notifications(ctx: TenantContext = Depends(read)):
    r = S.repo(ctx, S.NOTIFS)
    docs = await r.find({}, sort=[("created_at", -1)], limit=50)
    return _jsonable({"unread": await r.count({"read": False}),
                      "items": [{"id": d["_id"], "kind": d["kind"], "text": d["text"], "wedding_id": d.get("wedding_id"),
                                 "read": d["read"], "at": d["created_at"]} for d in docs]})


@router.post("/notifications/read-all")
async def read_all(ctx: TenantContext = Depends(write)):
    r = S.repo(ctx, S.NOTIFS)
    for d in await r.find({"read": False}, limit=500):
        await r.update(d["_id"], {"read": True})
    return {"ok": True}


@router.get("/settings")
async def get_module_settings(ctx: TenantContext = Depends(read)):
    s = await S.get_settings(ctx)
    return _jsonable({**{k: s.get(k) for k in ("form_id", "form_url", "notify_email", "notification_prefs", "rubrics",
                                                "last_sync", "sync_error", "form_title", "responder_uri")},
                      "notification_types": NOTIFICATION_TYPES,
                      "google_configured": bool(app_settings().GOOGLE_SERVICE_ACCOUNT_JSON),
                      "service_account": _sa_email()})


def _sa_email() -> str | None:
    raw = app_settings().GOOGLE_SERVICE_ACCOUNT_JSON
    try:
        return json.loads(raw).get("client_email") if raw else None
    except ValueError:
        return None


@router.put("/settings")
async def put_module_settings(body: SettingsIn, ctx: TenantContext = Depends(write)):
    changes = body.model_dump(exclude_unset=True, mode="json")
    if "form_url" in changes and changes["form_url"] and not changes.get("form_id"):
        import re
        m = re.search(r"/forms/d/(?:e/)?([A-Za-z0-9_-]{20,})", changes["form_url"])
        if m:
            changes["form_id"] = m.group(1)
    if "rubrics" in changes:
        keys = [r.get("key") for r in changes["rubrics"]]
        if len(set(keys)) != len(keys) or not all(keys) or not all(r.get("title") for r in changes["rubrics"]):
            raise HTTPException(422, "Chaque rubrique a une clé unique et un titre")
    if "notification_prefs" in changes:
        changes["notification_prefs"] = {k: v for k, v in changes["notification_prefs"].items() if k in NOTIFICATION_TYPES}
    await S.update_settings(ctx, changes)
    return await get_module_settings(ctx)
