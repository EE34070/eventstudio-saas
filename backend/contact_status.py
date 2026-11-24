"""Statuts de contact par type (client, wedding planner, prestataire, lieu, fournisseur). Listes par défaut en code, modifiables par société."""
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import Ctx, db, need, now_iso

router = APIRouter(prefix="/api")
TONES = ["gris", "vert", "ambre", "rouge", "bleu", "rose", "violet"]
WP = "wedding_planner"


def _s(id: str, label: str, color: str, excluded: bool = False) -> dict:
    return {"id": id, "label": label, "color": color, "excluded": excluded}


DEFAULTS = {
    "client": [_s("prospect", "Prospect", "ambre"), _s("client", "Client", "vert"), _s("ancien_client", "Ancien client", "gris"), _s("perdu", "Perdu", "rouge")],
    WP: [_s("nouvelle_relation", "Nouvelle relation", "bleu"), _s("partenaire_active", "Partenaire active", "vert"), _s("occasionnelle", "Occasionnelle", "ambre"), _s("inactive", "Inactive", "gris")],
    "prestataire": [_s("a_tester", "À tester", "bleu"), _s("partenaire_actif", "Partenaire actif", "vert"), _s("occasionnel", "Occasionnel", "ambre"), _s("inactif", "Inactif", "gris"),
                    _s("ne_plus", "Ne plus travailler avec", "rouge", True)],
    "lieu": [_s("lieu_partenaire", "Lieu partenaire", "vert"), _s("deja_travaille", "Déjà travaillé", "bleu"), _s("jamais_travaille", "Jamais travaillé", "gris")],
    "fournisseur": [_s("actif", "Actif", "vert"), _s("occasionnel", "Occasionnel", "ambre"), _s("inactif", "Inactif", "gris")],
}
FALLBACK = {"client": "prospect", WP: "partenaire_active", "prestataire": "partenaire_actif", "lieu": "deja_travaille", "fournisseur": "actif"}
TYPE_LABELS = {"client": "Client", WP: "Wedding planner", "prestataire": "Prestataire", "lieu": "Lieu", "fournisseur": "Fournisseur"}


async def lists(org_id: str) -> dict:
    mine = {d["contact_type"]: d["items"] async for d in db.contact_statuses.find({"org_id": org_id, "deleted_at": None}, {"_id": 0})}
    return {t: mine.get(t) or DEFAULTS[t] for t in DEFAULTS}


def keys(c: dict, wp: bool) -> list:
    out = [WP if t == "prestataire" and wp else t for t in c.get("types") or []]
    return [k for k in out if k in DEFAULTS]


def effective(c: dict, wp: bool, ls: dict) -> dict:
    out, st = {}, c.get("statuses") or {}
    for k in keys(c, wp):
        ids = [x["id"] for x in ls[k]]
        legacy = c.get("status") if k == "client" else None
        out[k] = st[k] if st.get(k) in ids else legacy if legacy in ids else FALLBACK[k] if FALLBACK[k] in ids else ids[0]
    return out


async def profiles(org_id: str) -> dict:
    return {p["contact_id"]: p async for p in db.provider_profiles.find({"org_id": org_id}, {"_id": 0, "id": 1, "contact_id": 1, "categories": 1})}


async def labels(org_id: str) -> dict:
    return {c["key"]: c["label"] async for c in db.provider_categories.find({"org_id": org_id}, {"_id": 0, "key": 1, "label": 1})}


async def enrich(org_id: str, rows: list, profs: Optional[dict] = None, labs: Optional[dict] = None) -> list:
    profs, labs, ls = profs if profs is not None else await profiles(org_id), labs if labs is not None else await labels(org_id), await lists(org_id)
    for r in rows:
        p = profs.get(r["id"]) if "prestataire" in (r.get("types") or []) else None
        cats = (p or {}).get("categories") or []
        r["provider_id"] = (p or {}).get("id")
        r["categories"] = [{"key": k, "label": labs.get(k, k)} for k in cats]
        r["is_wedding_planner"] = WP in cats
        r["statuses"] = effective(r, r["is_wedding_planner"], ls)
        r["status_badges"] = [{"type": k, "type_label": TYPE_LABELS[k], **next(x for x in ls[k] if x["id"] == v)} for k, v in r["statuses"].items()]
    return rows


async def banned(org_id: str) -> set:
    ids = [x["id"] for x in (await lists(org_id))["prestataire"] if x.get("excluded")]
    return {c["id"] async for c in db.contacts.find({"org_id": org_id, "statuses.prestataire": {"$in": ids}}, {"_id": 0, "id": 1})}


async def clean(ctx: Ctx, d: dict, cur: Optional[dict] = None) -> list:
    """Valide d['statuses'] selon les types du contact ; renvoie les lignes d'historique à ajouter."""
    wp = bool(cur and await db.provider_profiles.find_one(ctx.q({"contact_id": cur["id"], "categories": WP})))
    ls = await lists(ctx.org_id)
    sent = {**((cur or {}).get("statuses") or {}), **(d.get("statuses") or {})}
    if "client" not in (d.get("statuses") or {}) and d.get("status"):
        sent["client"] = d["status"]
    for k in keys(d, wp):
        if sent.get(k) and sent[k] not in [x["id"] for x in ls[k]]:
            raise HTTPException(400, f"Statut « {sent[k]} » inconnu pour le type {TYPE_LABELS[k]}")
    d["statuses"] = effective({**d, "statuses": sent}, wp, ls)
    d["status"] = d["statuses"].get("client", "")
    old = effective(cur, wp, ls) if cur else {}
    return [{"type": k, "from": old.get(k, ""), "to": v, "at": now_iso(), "by": ctx.member.get("name")} for k, v in d["statuses"].items() if cur and old.get(k) != v]


@router.get("/contact-statuses")
async def get_statuses(ctx: Ctx = Depends(need("contacts:read"))):
    custom = {d["contact_type"] async for d in db.contact_statuses.find({"org_id": ctx.org_id, "deleted_at": None}, {"_id": 0, "contact_type": 1})}
    return {"lists": await lists(ctx.org_id), "labels": TYPE_LABELS, "defaults": FALLBACK, "tones": TONES, "custom": sorted(custom)}


class StatusItem(BaseModel):
    id: str = Field("", max_length=40)
    label: str = Field(min_length=1, max_length=60)
    color: str = "gris"
    excluded: bool = False


class StatusList(BaseModel):
    items: List[StatusItem] = Field(min_length=1, max_length=20)


@router.put("/contact-statuses/{ctype}")
async def put_statuses(ctype: str, body: StatusList, ctx: Ctx = Depends(need("org:write"))):
    if ctype not in DEFAULTS:
        raise HTTPException(404, "Type inconnu")
    items, seen = [], set()
    for x in body.items:
        sid = x.id or re.sub(r"[^a-z0-9]+", "_", x.label.strip().lower()).strip("_") or "statut"
        while sid in seen:
            sid += "_2"
        seen.add(sid)
        items.append({"id": sid, "label": x.label.strip(), "color": x.color if x.color in TONES else "gris", "excluded": x.excluded and ctype == "prestataire"})
    await db.contact_statuses.update_one(ctx.q({"contact_type": ctype}), {"$set": {"items": items, "deleted_at": None, "updated_at": now_iso()}}, upsert=True)
    return await get_statuses(ctx)


@router.delete("/contact-statuses/{ctype}")
async def reset_statuses(ctype: str, ctx: Ctx = Depends(need("org:write"))):
    await db.contact_statuses.update_one(ctx.q({"contact_type": ctype}), {"$set": {"deleted_at": now_iso()}})
    return await get_statuses(ctx)
