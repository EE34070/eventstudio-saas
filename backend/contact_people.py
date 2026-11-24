"""Personnes d'une structure (contact prestataire / fournisseur / lieu, et contacts sur place des lieux) : une seule table contact_people."""
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import Ctx, db, need, new_id, now_iso

router = APIRouter(prefix="/api")
R, W = need("contacts:read"), need("contacts:write")
ROLES = ["Gérant·e", "Associé·e", "Assistant·e", "Coordinateur·rice", "Commercial·e", "Comptabilité", "Régisseur·se", "Technicien·ne", "Autre"]
LIVE = {"deleted_at": None}


def pname(p: dict) -> str:
    return " ".join(filter(None, [p.get("first_name"), p.get("last_name")])) or "—"


def digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")[-9:]


async def roles(org_id: str) -> list:
    d = await db.contact_roles.find_one({"org_id": org_id, "deleted_at": None}, {"_id": 0})
    return (d or {}).get("labels") or ROLES


async def people(org_id: str, owner_ids: list, owner_type: str = "contact") -> list:
    rows = await db.contact_people.find({"org_id": org_id, "owner_type": owner_type, "contact_id": {"$in": owner_ids}, **LIVE}, {"_id": 0, "org_id": 0}).to_list(5000)
    for p in rows:
        p["name"] = pname(p)
    return sorted(rows, key=lambda p: (not p.get("is_primary"), not p.get("active", True), p["name"].lower()))


def pick(rows: list, pid: Optional[str]) -> Optional[dict]:
    return next((p for p in rows if p["id"] == pid), None) or next((p for p in rows if p.get("is_primary") and p.get("active", True)), None)


async def for_event(org_id: str, contact_id: str, ev: dict) -> dict:
    rows = await people(org_id, [contact_id])
    person = pick(rows, ev.get("planner_person_id"))
    cc_ids = set(ev.get("planner_cc_person_ids") or [])
    cc = [p for p in rows if p is not person and (p["id"] in cc_ids or (p.get("cc_by_default") and p.get("active", True)))]
    return {"people": [p for p in rows if p.get("active", True) or p is person], "person": person, "cc": cc}


async def check(ctx: Ctx, contact_id: Optional[str], ids: list, base: dict, new_pid: Optional[str]) -> None:
    ids = [i for i in ids if i]
    if ids and await db.contact_people.count_documents(ctx.q({"id": {"$in": ids}, "contact_id": contact_id, "owner_type": "contact", **LIVE})) != len(set(ids)):
        raise HTTPException(400, "Cette personne n'appartient pas à la structure choisie")
    if base.get("id") and new_pid != base.get("planner_person_id"):
        await db.event_person_history.insert_one({"id": new_id(), "org_id": ctx.org_id, "event_id": base["id"], "from": base.get("planner_person_id"), "to": new_pid, "at": now_iso(), "by": ctx.member.get("name")})


async def search_owner_ids(org_id: str, q: str) -> list:
    rx = {"$regex": re.escape(q), "$options": "i"}
    return [p["contact_id"] async for p in db.contact_people.find({"org_id": org_id, "owner_type": "contact", **LIVE, "$or": [{"first_name": rx}, {"last_name": rx}, {"email": rx}]}, {"_id": 0, "contact_id": 1})]


class PersonIn(BaseModel):
    first_name: str = Field("", max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    role_label: str = Field(min_length=1, max_length=80)
    phone: str = Field("", max_length=40)
    email: str = Field("", max_length=160)
    whatsapp: bool = False
    language: str = Field("", max_length=10)
    preferred_channel: str = Field("email", pattern="^(email|whatsapp|phone)$")
    is_primary: bool = False
    cc_by_default: bool = False
    active: bool = True
    notes: str = Field("", max_length=500)


async def _data(ctx: Ctx, body: PersonIn, owner_id: str, me: str = "") -> dict:
    d = body.model_dump()
    d["email"] = d["email"].strip().lower()
    async for o in db.contact_people.find(ctx.q({"id": {"$ne": me}, **LIVE, "active": {"$ne": False}}), {"_id": 0, "email": 1, "phone": 1, "first_name": 1, "last_name": 1}):
        if (d["email"] and o.get("email") == d["email"]) or (digits(d["phone"]) and len(digits(d["phone"])) >= 9 and digits(o.get("phone")) == digits(d["phone"])):
            raise HTTPException(409, f"Cette adresse ou ce numéro appartient déjà à {pname(o)}")
    d["role_id"] = re.sub(r"[^a-z0-9]+", "_", d["role_label"].lower()).strip("_")
    return d


async def _prime(ctx: Ctx, owner_id: str, pid: str) -> None:
    await db.contact_people.update_many(ctx.q({"contact_id": owner_id, "owner_type": "contact", "id": {"$ne": pid}}), {"$set": {"is_primary": False}})


@router.get("/contacts/{cid}/people")
async def list_people(cid: str, ctx: Ctx = Depends(R)):
    await ctx.get("contacts", cid)
    return {"people": await people(ctx.org_id, [cid]), "roles": await roles(ctx.org_id)}


@router.post("/contacts/{cid}/people")
async def add_person(cid: str, body: PersonIn, ctx: Ctx = Depends(W)):
    c = await ctx.get("contacts", cid)
    d = await _data(ctx, body, cid)
    first = not await db.contact_people.find_one(ctx.q({"contact_id": cid, "owner_type": "contact", **LIVE}))
    p = await ctx.insert("contact_people", {**d, "language": d["language"] or c.get("language") or "fr-FR", "is_primary": d["is_primary"] or first, "contact_id": cid, "owner_type": "contact", "left_at": None, "deleted_at": None})
    if p["is_primary"]:
        await _prime(ctx, cid, p["id"])
    return await list_people(cid, ctx)


@router.put("/contact-people/{pid}")
async def update_person(pid: str, body: PersonIn, ctx: Ctx = Depends(W)):
    cur = await ctx.get("contact_people", pid, {"owner_type": "contact", **LIVE})
    d = await _data(ctx, body, cur["contact_id"], pid)
    d["left_at"] = None if d["active"] else cur.get("left_at") or now_iso()
    d["is_primary"] = d["is_primary"] and d["active"]
    await ctx.update("contact_people", pid, d)
    if d["is_primary"]:
        await _prime(ctx, cur["contact_id"], pid)
    return await list_people(cur["contact_id"], ctx)


@router.delete("/contact-people/{pid}")
async def delete_person(pid: str, ctx: Ctx = Depends(W)):
    cur = await ctx.get("contact_people", pid, {"owner_type": "contact", **LIVE})
    await ctx.update("contact_people", pid, {"deleted_at": now_iso(), "is_primary": False})
    return await list_people(cur["contact_id"], ctx)


class RolesIn(BaseModel):
    labels: List[str] = Field(min_length=1, max_length=40)


@router.get("/contact-roles")
async def get_roles(ctx: Ctx = Depends(R)):
    return {"labels": await roles(ctx.org_id)}


@router.put("/contact-roles")
async def put_roles(body: RolesIn, ctx: Ctx = Depends(need("org:write"))):
    labels = list(dict.fromkeys(x.strip()[:80] for x in body.labels if x.strip()))
    await db.contact_roles.update_one({"org_id": ctx.org_id}, {"$set": {"labels": labels, "deleted_at": None, "updated_at": now_iso()}}, upsert=True)
    return {"labels": labels}


async def sync_venue(org_id: str, venue: dict) -> None:
    """Les contacts sur place d'un lieu sont recopiés dans la table commune (la fiche lieu reste la source d'affichage)."""
    ids = []
    for c in venue.get("onsite_contacts") or []:
        first, _, last = (c.get("name") or "").partition(" ")
        ids.append(c["id"])
        await db.contact_people.update_one({"org_id": org_id, "id": c["id"]}, {"$set": {"owner_type": "venue", "contact_id": venue["id"], "first_name": first if last else "", "last_name": last or first, "role_label": c.get("role", ""),
                                           "phone": c.get("phone", ""), "email": (c.get("email") or "").lower(), "language": c.get("language") or "fr-FR", "is_primary": bool(c.get("is_primary")), "notes": c.get("notes", ""),
                                           "active": True, "deleted_at": None, "updated_at": now_iso()}, "$setOnInsert": {"created_at": now_iso(), "whatsapp": False, "preferred_channel": "email", "cc_by_default": False, "left_at": None}}, upsert=True)
    await db.contact_people.update_many({"org_id": org_id, "owner_type": "venue", "contact_id": venue["id"], "id": {"$nin": ids}, **LIVE}, {"$set": {"active": False, "left_at": now_iso()}})
