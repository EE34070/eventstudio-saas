"""Espace des mariés : /api/portal/wedding/*.

Réservé au rôle externe « client » rattaché au mariage (membership.scope.wedding_id).
Schémas de sortie dédiés : jamais de notes internes, de récapitulatif de l'organisatrice,
ni de budget ou de tarifs si les droits du couple ne le permettent pas.
"""
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.rbac import Role
from app.core.tenancy import TenantContext, tenant_context

from . import forms as F
from . import service as S
from .models import WeddingInfo
from .router import _jsonable, food_out
from .seed import COUPLE_SECTIONS, DEFAULT_OPEN_SECTIONS, DEFAULT_RIGHTS

router = APIRouter(prefix="/portal/wedding", tags=["wedding_planner:portal"])


@dataclass
class CoupleCtx:
    ctx: TenantContext
    wedding: dict


async def couple(request: Request, ctx: TenantContext = Depends(tenant_context)) -> CoupleCtx:
    if ctx.role != Role.CLIENT or not ctx.entitlements.has_module(S.MODULE):
        raise HTTPException(403, "Espace réservé aux mariés")
    wid = (ctx.membership.get("scope") or {}).get("wedding_id")
    w = await S.repo(ctx, S.WEDDINGS).get(wid) if wid else None
    if not w or ctx.membership.get("contact_id") not in (w.get("contact_ids") or []) or w.get("status") == "archived":
        raise HTTPException(404, "Espace introuvable")
    if request.method not in {"GET", "HEAD"} and ctx.entitlements.read_only:
        raise HTTPException(402, "Espace temporairement en lecture seule")
    return CoupleCtx(ctx=ctx, wedding=w)


def _rights(w: dict) -> dict:
    return {**DEFAULT_RIGHTS, **(w.get("rights") or {})}


def _public_info(w: dict) -> dict:
    info = _jsonable(w["info"])
    if not _rights(w)["budget"]:
        info["budget"] = None
    return info


@router.get("")
async def home(c: CoupleCtx = Depends(couple)):
    w, ctx = c.wedding, c.ctx
    info = w["info"]
    p = WeddingInfo(**info).partners
    info_complete = all(x.first_name and x.last_name and x.email and x.phone for x in p) and bool(info.get("date"))
    branding = ctx.org.get("branding", {})
    return _jsonable({
        "id": w["_id"], "names": S.couple_names(info), "lang": w.get("lang", "fr"), "date": info.get("date"),
        "venue": info.get("venue"), "days_left": S.days_left(info.get("date")),
        "sections": COUPLE_SECTIONS, "open_sections": w.get("open_sections", DEFAULT_OPEN_SECTIONS),
        "steps": {"info": "complete" if info_complete else "todo",
                  "quest": (w.get("questionnaire") or {}).get("status", "pending"),
                  "quest_submitted_at": (w.get("questionnaire") or {}).get("submitted_at")},
        "events": [{"key": e["key"], "name": e["name"], "date": e.get("date")} for e in w.get("events", []) if e.get("enabled")],
        "can_edit_info": _rights(w)["edit_info"] and not ctx.entitlements.read_only,
        "organizer": {"name": branding.get("app_name") or ctx.org.get("name"), "logo_url": branding.get("logo_url")},
    })


@router.get("/info")
async def get_info(c: CoupleCtx = Depends(couple)):
    return {"info": _public_info(c.wedding), "can_edit": _rights(c.wedding)["edit_info"],
            "budget_visible": _rights(c.wedding)["budget"]}


_LABELS = {"partners": "coordonnées", "date": "date", "venue": "lieu", "venue_address": "adresse du lieu",
           "budget": "budget", "ceremony": "cérémonie", "same_address": "adresse"}


@router.put("/info")
async def put_info(body: WeddingInfo, c: CoupleCtx = Depends(couple)):
    w, ctx = c.wedding, c.ctx
    if not _rights(w)["edit_info"]:
        raise HTTPException(403, "La modification de la fiche n'est pas ouverte pour le moment")
    new = body.normalized().model_dump(mode="json")
    old = w["info"]
    new["guests"] = old.get("guests", {})          # calculé : jamais saisi par les mariés
    if not _rights(w)["budget"]:
        new["budget"] = old.get("budget")
    changed = [k for k in new if _jsonable(new[k]) != _jsonable(old.get(k))]
    if not changed:
        return {"info": _public_info(w)}
    w["info"] = new
    for e in w["events"]:
        if e["key"] == "dj":
            e["date"] = new["date"]
    w["contact_ids"] = await S.ensure_contacts(ctx, w)
    w["events"] = await S.sync_core_events(ctx, w)
    await S.repo(ctx, S.WEDDINGS).update(w["_id"], {"info": new, "events": w["events"], "contact_ids": w["contact_ids"]})
    what = ", ".join(sorted({_LABELS.get(k, k) for k in changed}))
    await S.notify(ctx, "info_changed", f"{S.couple_names(new)} ont modifié leur fiche : {what}.", wedding_id=w["_id"])
    return {"info": _public_info(w)}


@router.get("/questionnaire")
async def questionnaire(c: CoupleCtx = Depends(couple)):
    ctx, w = c.ctx, c.wedding
    s = await S.get_settings(ctx)
    questions = await S.repo(ctx, S.QUESTIONS).find({"fiche_field": {"$ne": None}}, limit=200)
    responder = s.get("responder_uri") or s.get("form_url")
    q = w.get("questionnaire") or {}
    return _jsonable({
        "status": q.get("status", "pending"), "submitted_at": q.get("submitted_at"),
        "embed_url": F.prefilled_url(responder, questions, w["info"]), "open_url": responder,
        "known_fields": F.known_fields(w["info"]),
    })


@router.get("/food/{key}")
async def food(key: str, c: CoupleCtx = Depends(couple)):
    ctx, w = c.ctx, c.wedding
    if "food" not in w.get("open_sections", DEFAULT_OPEN_SECTIONS):
        raise HTTPException(404, "Rubrique pas encore ouverte")
    ev = next((e for e in w.get("events", []) if e["key"] == key), None)
    if not ev:
        raise HTTPException(404, "Événement introuvable")
    if not ev.get("enabled"):
        return {"event": {"key": key, "name": ev["name"]}, "enabled": False}
    guests, src = S.guests_for(ev, await S.confirmed_counts(ctx, w))
    f = food_out(await S.repo(ctx, S.FOOD).get(f"{w['_id']}:{key}"), guests)
    if f:
        f.pop("notes", None)  # notes internes : jamais visibles des mariés
        if not _rights(w)["vendor_prices"]:
            f["price"] = None
    return _jsonable({"event": {"key": key, "name": ev["name"], "date": ev.get("date")}, "enabled": True,
                      "guests": guests, "guests_source": src, "food": f, "diets": [], "kids": None})


async def on_invitation_accepted(ctx: TenantContext, invitation: dict) -> None:
    wid = (invitation.get("scope") or {}).get("wedding_id")
    w = await S.repo(ctx, S.WEDDINGS).get(wid) if wid else None
    if not w:
        return
    i = (invitation.get("scope") or {}).get("partner", 0)
    who = w["info"]["partners"][i].get("first_name") or invitation["email"]
    await S.notify(ctx, "invitation_accepted", f"{who} ({S.couple_names(w['info'])}) a rejoint son espace.", wedding_id=wid)
