import csv
import io
import os
from datetime import datetime, timedelta
from typing import Dict, List, Literal, Optional
from xml.sax.saxutils import escape

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import portal_core as po
import providers_core as pc
from core import Ctx, audit, current_member, db, need, new_id, now_iso
from i18n import doc_lang
from routes_comms import base_url
from routes_files import store_bytes
from routes_portal import VISIBLE, _mission, _mission_row, _profile, nf
from security import sha256, sign_file

router = APIRouter(prefix="/api")
P, PV, ADMIN = need("providers:manage"), need("portal:provider"), need("users:manage")
DATE, TIME = r"^\d{4}-\d{2}-\d{2}$", r"^([01]\d|2[0-3]):[0-5]\d$"
ACTIVE = ("invited", "applied", "shortlisted", "waitlist")
OK_PROFILE = (None, "active", "test")


def _fernet() -> Fernet:
    key = os.environ.get("STAFF_ENCRYPTION_KEY")
    if not key:
        raise HTTPException(503, "Chiffrement non configuré (STAFF_ENCRYPTION_KEY)")
    return Fernet(key.encode())


def _mins(t: str) -> int:
    return int(t[:2]) * 60 + int(t[3:])


def _hours(start: str, end: str, pause: int = 0) -> float:
    return round(max(0, (_mins(end) - _mins(start)) % 1440 - pause) / 60, 2)


def completion(p: dict, c: dict) -> int:
    checks = [c.get("phone"), p.get("categories"), p.get("base_city"), p.get("bio"), p.get("languages"), p.get("base_rate"), p.get("employment_status"),
              p.get("siret") if p.get("employment_status") != "intermittent" else p.get("conges_spectacles_number")]
    return round(100 * sum(1 for x in checks if x) / len(checks))


async def _notify(org: dict, contact_id: str, fr: tuple, en: tuple, base: str) -> None:
    c = await db.contacts.find_one({"org_id": org["id"], "id": contact_id}, {"_id": 0}) or {}
    if c.get("email"):
        s, m = en if doc_lang(c.get("language")) == "en" else fr
        await po.send_tpl(org, "alert", c.get("language"), c["email"], {"prenom": c.get("first_name") or "", "sujet": s, "message": m, "lien": base}, base)


async def _org(ctx: Ctx) -> dict:
    return await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}) or {}


async def _name(org_id: str, p: dict) -> str:
    c = await db.contacts.find_one({"org_id": org_id, "id": p.get("contact_id")}, {"_id": 0}) or {}
    return p.get("stage_name") or " ".join(filter(None, [c.get("first_name"), c.get("last_name")])) or c.get("company") or "—"


# ---------- Inscription autonome ----------
class JoinIn(BaseModel):
    org_id: str = Field(max_length=40)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=6, max_length=40)
    categories: List[str] = Field(min_length=1, max_length=10)
    years_experience: Dict[str, int] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list, max_length=20)
    languages: List[str] = Field(default_factory=list, max_length=10)
    driving_licence: bool = False
    has_vehicle: bool = False
    equipment_brought: str = Field("", max_length=500)
    base_city: str = Field("", max_length=120)
    radius_km: float = Field(0, ge=0, le=2000)
    departments: List[str] = Field(default_factory=list, max_length=30)
    employment_status: Literal["freelance", "intermittent", "other"]
    base_rate: float = Field(0, ge=0, le=100000)
    vat_mode: Literal["subject", "not_applicable_293B"] = "not_applicable_293B"
    siret: str = Field("", max_length=20)
    conges_spectacles_number: str = Field("", max_length=30)
    bio: str = Field("", max_length=1500)
    website: str = Field("", max_length=300)
    language: Literal["fr-FR", "en-US", "en-GB"] = "fr-FR"
    accept: Literal[True]


@router.get("/public/join/{org_id}")
async def join_info(org_id: str):
    org = await db.orgs.find_one({"id": org_id}, {"_id": 0, "name": 1})
    if not org:
        raise HTTPException(404, "Introuvable")
    return {"org": org["name"], "categories": [{"key": k, "label": v} for k, v in (await pc.labels(org_id)).items()]}


@router.post("/join")
async def join(body: JoinIn, member: dict = Depends(current_member)):
    if member.get("org_id"):
        raise HTTPException(400, "Votre compte est déjà rattaché")
    org = await db.orgs.find_one({"id": body.org_id}, {"_id": 0})
    if not org:
        raise HTTPException(404, "Introuvable")
    q, email = {"org_id": org["id"]}, (member.get("email") or "").lower()
    dup = await db.contacts.find_one({**q, "$or": [{"email": email}, {"phone": body.phone}]}, {"_id": 0, "id": 1})
    c = {"id": new_id(), **q, "created_at": now_iso(), "first_name": body.first_name.strip(), "last_name": body.last_name.strip(), "email": email, "phone": body.phone, "language": body.language, "kind": "prestataire", "company": ""}
    await db.contacts.insert_one({**c})
    d = body.model_dump(exclude={"org_id", "first_name", "last_name", "phone", "accept"})
    p = {"id": new_id(), **q, "created_at": now_iso(), "contact_id": c["id"], "stage_name": "", "whatsapp": False, "instagram": "", "video_url": "", "base_zip": "", "base_lat": None, "base_lng": None,
         "travels_everywhere": False, "included_hours": 0, "extra_hour_rate": 0, "travel_fee_mode": "included", "travel_fee_amount": 0, "travel_km_included": 0, "meal_lodging": False, "meal_lodging_fee": 0,
         "legal_status": "micro" if body.employment_status == "freelance" else "intermittent", "vat_rate": 20, "equipment_needed": [], "equipment_needed_note": "", "tech_rider": "", "rating": 0, "notes": "", **d,
         "status": "pending", "validation_status": "pending", "signup_source": "self", "duplicate_of": (dup or {}).get("id"), "withdrawals": 0}
    p["completion_pct"] = completion(p, c)
    await db.provider_profiles.insert_one({**p})
    await db.users.update_one({"user_id": member["user_id"]}, {"$set": {"org_id": org["id"], "role": "provider", "contact_id": c["id"], "status": "pending", "name": f"{c['first_name']} {c['last_name']}",
                                                                      "terms_accepted_at": now_iso(), "terms_version": po.TERMS_VERSION, "terms_language": body.language}})
    await audit(org["id"], {**member, "role": "provider"}, "network_application", email)
    return {"ok": True}


@router.get("/staff/overview")
async def overview(ctx: Ctx = Depends(P)):
    pend = await ctx.list("provider_profiles", {"validation_status": {"$in": ["pending", "more_info"]}}, sort=[("created_at", -1)])
    out = []
    for p in pend:
        c = await db.contacts.find_one(ctx.q({"id": p["contact_id"]}), {"_id": 0}) or {}
        out.append({**{k: p.get(k) for k in ("id", "categories", "years_experience", "base_city", "radius_km", "employment_status", "base_rate", "bio", "languages", "validation_status", "duplicate_of", "completion_pct", "created_at")},
                    "name": await _name(ctx.org_id, p), "email": c.get("email"), "phone": c.get("phone")})
    tomorrow = (datetime.strptime(po.today(), "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    dpae = await ctx.list("missions", {"employment_status": "intermittent", "status": "confirmed", "dpae_done_at": None, "date": {"$gte": po.today(), "$lte": tomorrow}})
    from routes_admin import cddu_rows
    team_dpae = [{"id": r["id"], "team_id": r["team_id"], "event_id": r["event_id"], "provider_name": r["provider_name"], "date": r["date"]} for r in await cddu_rows(ctx, po.today(), tomorrow, ["confirme", "en_preparation"]) if not r["dpae_done"]]
    return {"org_id": ctx.org_id, "applications": out, "labels": await pc.labels(ctx.org_id), "settings": {"withdraw_days": 7, "km_rate": 0.4, "overtime_after": 8, **((await _org(ctx)).get("staff_settings") or {})},
            "dpae_alerts": [{"id": m["id"], "provider_name": m["provider_name"], "date": m["date"]} for m in dpae] + team_dpae}


class DecideIn(BaseModel):
    decision: Literal["active", "test", "refused", "more_info"]
    message: str = Field("", max_length=1000)


@router.post("/providers/{pid}/validate")
async def validate_profile(pid: str, body: DecideIn, request: Request, ctx: Ctx = Depends(P)):
    p = await ctx.get("provider_profiles", pid)
    ok = body.decision in ("active", "test")
    await ctx.update("provider_profiles", pid, {"validation_status": body.decision, "status": "active" if ok else "archived" if body.decision == "refused" else "pending"})
    await db.users.update_many(ctx.q({"contact_id": p["contact_id"], "role": "provider"}), {"$set": {"status": "active" if ok else "suspended" if body.decision == "refused" else "pending"}})
    msgs = {"active": ("Votre profil est validé", "Bienvenue dans l'équipe ! Vous pouvez maintenant consulter les missions disponibles.", "Your profile is approved", "Welcome to the team! You can now browse available jobs."),
            "refused": ("Votre candidature", "Merci pour votre candidature. Nous ne pouvons malheureusement pas y donner suite pour le moment.", "Your application", "Thank you for applying. Unfortunately we cannot take it further at this time."),
            "more_info": ("Complément demandé", body.message or "Merci de compléter votre profil.", "More information needed", body.message or "Please complete your profile.")}
    fr1, fr2, en1, en2 = msgs["active" if ok else body.decision]
    await _notify(await _org(ctx), p["contact_id"], (fr1, fr2), (en1, en2), base_url(request))
    await audit(ctx.org_id, ctx.member, f"network_{body.decision}", await _name(ctx.org_id, p))
    return {"ok": True}


# ---------- Équipes ----------
class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    provider_ids: List[str] = Field(default_factory=list, max_length=300)


@router.get("/staff-teams")
async def teams(ctx: Ctx = Depends(P)):
    return await ctx.list("staff_teams", {"archived_at": None}, sort=[("name", 1)])


@router.post("/staff-teams")
async def add_team(body: TeamIn, ctx: Ctx = Depends(P)):
    return await ctx.insert("staff_teams", {**body.model_dump(), "archived_at": None})


@router.put("/staff-teams/{tid}")
async def put_team(tid: str, body: TeamIn, ctx: Ctx = Depends(P)):
    return await ctx.update("staff_teams", tid, body.model_dump())


# ---------- Postes ----------
class PositionIn(BaseModel):
    category_key: str = Field(min_length=1, max_length=40)
    quantity: int = Field(1, ge=1, le=100)
    date: str = Field(pattern=DATE)
    start_time: str = Field(pattern=TIME)
    end_time: str = Field(pattern=TIME)
    break_min: int = Field(0, ge=0, le=600)
    dress: str = Field("", max_length=200)
    brief: str = Field("", max_length=2000)
    skills: List[str] = Field(default_factory=list, max_length=20)
    rate_type: Literal["hourly", "flat", "cachet"] = "flat"
    rate: float = Field(0, ge=0, le=100000)
    rate_basis: Literal["ht", "ttc", "brut"] = "ht"
    accepted_statuses: List[Literal["freelance", "intermittent", "other"]] = Field(default_factory=lambda: ["freelance", "intermittent"])
    visibility: Literal["private", "team", "network"] = "private"
    team_id: str = Field("", max_length=40)


async def _pos_view(ctx: Ctx, pos: dict, lab: dict) -> dict:
    apps = await ctx.list("position_applications", {"position_id": pos["id"]}, sort=[("created_at", 1)])
    for a in apps:
        prof = await db.provider_profiles.find_one(ctx.q({"id": a["provider_id"]}), {"_id": 0, "rating": 1, "withdrawals": 1, "employment_status": 1}) or {}
        a.update(rating=prof.get("rating") or 0, withdrawals=prof.get("withdrawals") or 0, employment_status=prof.get("employment_status") or "freelance",
                 busy=bool(await db.missions.count_documents(ctx.q({"provider_id": a["provider_id"], "date": pos["date"], "status": {"$in": VISIBLE}, "position_id": {"$ne": pos["id"]}}))))
    n = sum(1 for a in apps if a["status"] == "confirmed")
    return {**pos, "category": lab.get(pos["category_key"], pos["category_key"]), "confirmed": n, "applications": apps, "label": "Pourvu" if n >= pos["quantity"] else f"{n} / {pos['quantity']} confirmés"}


@router.get("/events/{eid}/positions")
async def positions(eid: str, ctx: Ctx = Depends(P)):
    await ctx.get("events", eid)
    lab = await pc.labels(ctx.org_id)
    rows = [await _pos_view(ctx, p, lab) for p in await ctx.list("positions", {"event_id": eid, "archived_at": None}, sort=[("date", 1), ("start_time", 1)])]
    conf, need_ = sum(r["confirmed"] for r in rows), sum(r["quantity"] for r in rows)
    return {"positions": rows, "summary": f"{conf} confirmés · {max(0, need_ - conf)} postes à pourvoir", "labels": lab, "teams": await ctx.list("staff_teams", {"archived_at": None}),
            "providers": [{"id": p["id"], "name": await _name(ctx.org_id, p), "categories": p.get("categories") or []} for p in await ctx.list("provider_profiles", {"status": "active"}, limit=500) if p.get("contact_id") not in await __import__("contact_status").banned(ctx.org_id)]}


@router.post("/events/{eid}/positions")
async def add_position(eid: str, body: PositionIn, ctx: Ctx = Depends(P)):
    ev = await ctx.get("events", eid)
    v = await db.venues.find_one(ctx.q({"id": ev.get("venue_id") or "__none__"}), {"_id": 0, "city": 1}) or {}
    return await ctx.insert("positions", {**body.model_dump(), "event_id": eid, "venue_city": v.get("city", ""), "status": "open", "archived_at": None})


@router.put("/positions/{pid}")
async def put_position(pid: str, body: PositionIn, ctx: Ctx = Depends(P)):
    return await ctx.update("positions", pid, body.model_dump())


@router.post("/positions/{pid}/duplicate")
async def dup_position(pid: str, ctx: Ctx = Depends(P)):
    p = await ctx.get("positions", pid)
    return await ctx.insert("positions", {k: v for k, v in p.items() if k not in ("id", "org_id", "created_at", "updated_at")} | {"status": "open"})


class InviteIn(BaseModel):
    provider_ids: List[str] = Field(default_factory=list, max_length=200)
    team_id: str = Field("", max_length=40)


@router.post("/positions/{pid}/invite")
async def invite(pid: str, body: InviteIn, request: Request, ctx: Ctx = Depends(P)):
    pos, org, n = await ctx.get("positions", pid), await _org(ctx), 0
    ids = set(body.provider_ids) | set((await ctx.get("staff_teams", body.team_id))["provider_ids"] if body.team_id else [])
    for prov in ids:
        p = await db.provider_profiles.find_one(ctx.q({"id": prov, "status": "active"}), {"_id": 0})
        if not p or await db.position_applications.find_one(ctx.q({"position_id": pid, "provider_id": prov})):
            continue
        await ctx.insert("position_applications", {"position_id": pid, "event_id": pos["event_id"], "provider_id": prov, "provider_name": await _name(ctx.org_id, p), "status": "invited", "origin": "invite", "message": "", "counter_rate": None, "reply": ""})
        await _notify(org, p["contact_id"], ("Nouvelle invitation", f"Vous êtes invité(e) sur une mission le {pc.fr_date(pos['date'])}. Répondez depuis votre espace."), ("New invitation", f"You are invited to a job on {pos['date']}. Reply from your space."), base_url(request))
        n += 1
    return {"invited": n}


@router.post("/applications/{aid}/{action}")
async def decide_application(aid: str, action: Literal["confirm", "refuse", "shortlist", "waitlist"], request: Request, ctx: Ctx = Depends(P)):
    a = await ctx.get("position_applications", aid)
    pos, org, base = await ctx.get("positions", a["position_id"]), await _org(ctx), base_url(request)
    if action != "confirm":
        return await ctx.update("position_applications", aid, {"status": {"refuse": "refused", "shortlist": "shortlisted", "waitlist": "waitlist"}[action]})
    if a["status"] not in ACTIVE:
        raise HTTPException(409, "Cette candidature n'est plus active")
    n = await db.position_applications.count_documents(ctx.q({"position_id": pos["id"], "status": "confirmed"}))
    if n >= pos["quantity"]:
        raise HTTPException(409, "Poste déjà pourvu")
    p = await ctx.get("provider_profiles", a["provider_id"])
    rate = a.get("counter_rate") or pos["rate"]
    ht = round(rate * _hours(pos["start_time"], pos["end_time"], pos["break_min"]), 2) if pos["rate_type"] == "hourly" else rate
    es = p.get("employment_status") or "freelance"
    vat = p.get("vat_rate", 20) if p.get("vat_mode") == "subject" and es == "freelance" else 0
    m = await ctx.insert("missions", {"request_id": "", "recipient_id": "", "position_id": pos["id"], "provider_id": p["id"], "provider_name": a["provider_name"], "event_id": pos["event_id"], "category_key": pos["category_key"],
                                      "date": pos["date"], "start_time": pos["start_time"], "end_time": pos["end_time"], "break_min": pos["break_min"], "venue_city": pos.get("venue_city", ""), "brief": pos["brief"], "dress": pos["dress"],
                                      "rate_type": pos["rate_type"], "agreed_rate": rate, "agreed_travel_fee": 0, "vat_mode": "subject" if vat else "not_applicable_293B", "vat_rate": vat, "total_ht": ht, "total_ttc": round(ht * (1 + vat / 100), 2),
                                      "equipment_needed": [], "equipment_note": "", "missing_equipment": [], "status": "confirmed", "employment_status": es, "dpae_done_at": None, "rating": None, "rating_comment": ""})
    await ctx.insert("provider_unavailabilities", {"provider_id": p["id"], "date": pos["date"], "start_time": pos["start_time"], "end_time": pos["end_time"], "source": "mission", "mission_id": m["id"], "note": ""})
    await ctx.update("position_applications", aid, {"status": "confirmed", "mission_id": m["id"]})
    await _notify(org, p["contact_id"], ("Mission confirmée", f"Votre mission du {pc.fr_date(pos['date'])} est confirmée."), ("Job confirmed", f"Your job on {pos['date']} is confirmed."), base)
    if n + 1 >= pos["quantity"]:
        await ctx.update("positions", pos["id"], {"status": "filled"})
        for o in await ctx.list("position_applications", {"position_id": pos["id"], "status": {"$in": ["invited", "applied", "shortlisted"]}}):
            await ctx.update("position_applications", o["id"], {"status": "filled_elsewhere"})
            op = await db.provider_profiles.find_one(ctx.q({"id": o["provider_id"]}), {"_id": 0, "contact_id": 1}) or {}
            await _notify(org, op.get("contact_id"), ("Poste pourvu", f"Le poste du {pc.fr_date(pos['date'])} a été pourvu. Merci pour votre réponse."), ("Position filled", f"The position on {pos['date']} has been filled. Thank you."), base)
    return {"mission_id": m["id"]}


@router.post("/missions/{mid}/dpae")
async def dpae(mid: str, ctx: Ctx = Depends(P)):
    await ctx.update("missions", mid, {"dpae_done_at": now_iso()})
    return {"ok": True}


# ---------- Portail staff ----------
async def _valid(ctx: Ctx, request: Request) -> dict:
    p = await _profile(ctx, request)
    if p.get("status") != "active" or p.get("validation_status") not in OK_PROFILE:
        await nf(ctx, request)
    return p


def _pos_public(pos: dict, lab: dict) -> dict:
    return {**{k: pos.get(k) for k in ("id", "date", "start_time", "end_time", "break_min", "dress", "brief", "skills", "rate_type", "rate", "rate_basis", "venue_city")}, "category": lab.get(pos["category_key"], pos["category_key"])}


@router.get("/portal/provider/home")
async def staff_home(request: Request, ctx: Ctx = Depends(PV)):
    p = await _profile(ctx, request)
    c = await db.contacts.find_one(ctx.q({"id": p["contact_id"]}), {"_id": 0}) or {}
    lab, day = await pc.labels(ctx.org_id), po.today()
    ms = await db.missions.find(ctx.q({"provider_id": p["id"], "status": {"$in": VISIBLE}, "date": {"$gte": day}}), {"_id": 0}).sort("date", 1).to_list(50)
    week = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")
    return {"first_name": c.get("first_name", ""), "validation_status": p.get("validation_status") or "active", "completion_pct": completion(p, c), "next": _mission_row(ms[0], lab) if ms else None,
            "week": [_mission_row(m, lab) for m in ms if m["date"] <= week], "invitations": await db.position_applications.count_documents(ctx.q({"provider_id": p["id"], "status": "invited"}))}


@router.get("/portal/provider/positions")
async def open_positions(request: Request, ctx: Ctx = Depends(PV)):
    p = await _valid(ctx, request)
    lab = await pc.labels(ctx.org_id)
    mine = {a["position_id"]: a for a in await db.position_applications.find(ctx.q({"provider_id": p["id"]}), {"_id": 0}).to_list(500)}
    teams = [t["id"] for t in await db.staff_teams.find(ctx.q({"provider_ids": p["id"], "archived_at": None}), {"_id": 0, "id": 1}).to_list(100)]
    out = {"open": [], "invitations": [], "applications": []}
    async for pos in db.positions.find(ctx.q({"date": {"$gte": po.today()}, "archived_at": None}), {"_id": 0}).sort("date", 1):
        a = mine.get(pos["id"])
        row = {**_pos_public(pos, lab), "application_id": (a or {}).get("id"), "status": (a or {}).get("status")}
        if a:
            out["invitations" if a["status"] == "invited" else "applications"].append(row)
        elif pos["status"] == "open" and pos["category_key"] in (p.get("categories") or []) and (p.get("employment_status") or "freelance") in pos["accepted_statuses"] \
                and (pos["visibility"] == "network" or (pos["visibility"] == "team" and pos.get("team_id") in teams)):
            out["open"].append(row)
    return out


class ApplyIn(BaseModel):
    message: str = Field("", max_length=1000)
    counter_rate: Optional[float] = Field(None, ge=0, le=100000)


@router.post("/portal/provider/positions/{pid}/apply")
async def apply(pid: str, body: ApplyIn, request: Request, ctx: Ctx = Depends(PV)):
    p = await _valid(ctx, request)
    ok = next((x for x in (await open_positions(request, ctx))["open"] if x["id"] == pid), None)
    if not ok:
        await nf(ctx, request)
    pos = await ctx.get("positions", pid)
    return {"id": (await ctx.insert("position_applications", {"position_id": pid, "event_id": pos["event_id"], "provider_id": p["id"], "provider_name": await _name(ctx.org_id, p), "status": "applied", "origin": "application", **body.model_dump(), "reply": ""}))["id"]}


class ReplyIn(BaseModel):
    reply: Literal["accept", "refuse", "conditional"]
    message: str = Field("", max_length=1000)
    counter_rate: Optional[float] = Field(None, ge=0, le=100000)


@router.post("/portal/provider/applications/{aid}/reply")
async def reply(aid: str, body: ReplyIn, request: Request, ctx: Ctx = Depends(PV)):
    p = await _valid(ctx, request)
    r = await db.position_applications.update_one(ctx.q({"id": aid, "provider_id": p["id"], "status": "invited"}),
                                                  {"$set": {"status": "refused" if body.reply == "refuse" else "applied", "reply": body.reply, "message": body.message, "counter_rate": body.counter_rate, "replied_at": now_iso()}})
    if not r.matched_count:
        await nf(ctx, request)
    return {"ok": True}


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/portal/provider/missions/{mid}/withdraw")
async def withdraw(mid: str, body: ReasonIn, request: Request, ctx: Ctx = Depends(PV)):
    m, p = await _mission(ctx, request, mid)
    days = int(((await _org(ctx)).get("staff_settings") or {}).get("withdraw_days", 7))
    if m["status"] != "confirmed" or (datetime.strptime(m["date"], "%Y-%m-%d") - datetime.strptime(po.today(), "%Y-%m-%d")).days < days:
        raise HTTPException(409, f"Désistement possible jusqu'à J-{days} : contactez-nous")
    await db.missions.update_one(ctx.q({"id": mid}), {"$set": {"status": "cancelled", "withdrawal_reason": body.reason, "withdrawn_at": now_iso()}})
    await db.provider_unavailabilities.update_many(ctx.q({"mission_id": mid}), {"$set": {"cancelled_at": now_iso()}})
    await db.provider_profiles.update_one(ctx.q({"id": p["id"]}), {"$inc": {"withdrawals": 1}})
    if m.get("position_id"):
        await db.position_applications.update_one(ctx.q({"mission_id": mid}), {"$set": {"status": "withdrawn"}})
        await db.positions.update_one(ctx.q({"id": m["position_id"]}), {"$set": {"status": "open"}})
    await audit(ctx.org_id, ctx.member, "mission_withdrawn", m["provider_name"], body.reason)
    return {"ok": True}


# ---------- Heures ----------
class TimesheetIn(BaseModel):
    start_time: str = Field(pattern=TIME)
    end_time: str = Field(pattern=TIME)
    break_min: int = Field(0, ge=0, le=600)
    night_hours: float = Field(0, ge=0, le=24)
    km: float = Field(0, ge=0, le=5000)
    expenses: float = Field(0, ge=0, le=10000)
    comment: str = Field("", max_length=1000)
    reason: str = Field("", max_length=500)


def _calc(d: dict, m: dict, s: dict) -> dict:
    h = _hours(d["start_time"], d["end_time"], d["break_min"])
    hourly, after = m.get("rate_type") == "hourly", float(s.get("overtime_after", 8))
    base = m["agreed_rate"] * h if hourly else m["agreed_rate"]
    extra = max(0, h - after) * m["agreed_rate"] * 0.25 if hourly else 0
    fees = d["km"] * float(s.get("km_rate", 0.4)) + d["expenses"] + (m.get("agreed_travel_fee") or 0)
    return {"hours": h, "normal_hours": min(h, after), "overtime_hours": round(max(0, h - after), 2), "amount_base": round(base, 2), "amount_overtime": round(extra, 2), "amount_expenses": round(fees, 2), "total_ht": round(base + extra + fees, 2)}


async def _save_ts(ctx: Ctx, m: dict, body: TimesheetIn, status: str, extra: dict) -> dict:
    d = body.model_dump(exclude={"reason"})
    doc = {**d, **_calc(d, m, (await _org(ctx)).get("staff_settings") or {}), "status": status, "updated_at": now_iso(), **extra}
    await db.timesheets.update_one(ctx.q({"mission_id": m["id"]}), {"$set": doc, "$setOnInsert": {"id": new_id(), "provider_id": m["provider_id"], "provider_name": m["provider_name"], "event_id": m.get("event_id"), "date": m["date"],
                                                                                              "employment_status": m.get("employment_status") or "freelance", "created_at": now_iso()}}, upsert=True)
    return await db.timesheets.find_one(ctx.q({"mission_id": m["id"]}), {"_id": 0, "org_id": 0})


@router.put("/portal/provider/missions/{mid}/timesheet")
async def declare(mid: str, body: TimesheetIn, request: Request, ctx: Ctx = Depends(PV)):
    m, _ = await _mission(ctx, request, mid)
    cur = await db.timesheets.find_one(ctx.q({"mission_id": mid}), {"_id": 0, "status": 1})
    if cur and cur["status"] not in ("declared", "refused"):
        raise HTTPException(409, "Heures déjà validées")
    return await _save_ts(ctx, m, body, "declared", {"declared_at": now_iso()})


@router.get("/portal/provider/space")
async def space(request: Request, ctx: Ctx = Depends(PV)):
    p = await _profile(ctx, request)
    lab, out = await pc.labels(ctx.org_id), []
    ts = {t["mission_id"]: t for t in await db.timesheets.find(ctx.q({"provider_id": p["id"]}), {"_id": 0, "org_id": 0}).to_list(1000)}
    inv = {i["mission_id"]: i for i in await db.provider_invoices.find(ctx.q({"provider_id": p["id"]}), {"_id": 0, "org_id": 0}).to_list(1000)}
    async for m in db.missions.find(ctx.q({"provider_id": p["id"], "status": {"$in": VISIBLE}}), {"_id": 0}).sort("date", -1).limit(200):
        i = inv.get(m["id"])
        out.append({**_mission_row(m, lab), "break_min": m.get("break_min", 0), "past": m["date"] <= po.today(), "timesheet": ts.get(m["id"]),
                    "invoice": {"number": i["number"], "status": i["status"], "total_ttc": i["total_ttc"], "url": sign_file(ctx.org_id, i["file"])} if i else None})
    return {"employment_status": p.get("employment_status") or "freelance", "missions": out, "ical": bool(p.get("ical_hash")), "has_bank": bool(p.get("iban_encrypted"))}


class BankIn(BaseModel):
    iban: str = Field("", max_length=40)
    ssn: str = Field("", max_length=20)


@router.put("/portal/provider/bank")
async def bank(body: BankIn, request: Request, ctx: Ctx = Depends(PV)):
    p, f = await _profile(ctx, request), _fernet()
    ch = {f"{k}_encrypted": f.encrypt(v.replace(" ", "").encode()).decode() for k, v in body.model_dump().items() if v.strip()}
    if ch:
        await db.provider_profiles.update_one(ctx.q({"id": p["id"]}), {"$set": ch})
    return {"ok": True}


@router.get("/providers/{pid}/bank")
async def read_bank(pid: str, ctx: Ctx = Depends(ADMIN)):
    p, f = await ctx.get("provider_profiles", pid), _fernet()
    await audit(ctx.org_id, ctx.member, "bank_details_read", await _name(ctx.org_id, p))
    return {k: f.decrypt(p[f"{k}_encrypted"].encode()).decode() if p.get(f"{k}_encrypted") else "" for k in ("iban", "ssn")}


@router.get("/timesheets")
async def timesheets(status: str = "", ctx: Ctx = Depends(P)):
    return await ctx.list("timesheets", {"status": status} if status else {}, sort=[("date", -1)], limit=500)


class IdsIn(BaseModel):
    ids: List[str] = Field(min_length=1, max_length=200)


@router.post("/timesheets/validate")
async def validate_ts(body: IdsIn, ctx: Ctx = Depends(P)):
    r = await db.timesheets.update_many(ctx.q({"id": {"$in": body.ids}, "status": "declared"}), {"$set": {"status": "validated", "validated_at": now_iso(), "validated_by": ctx.member.get("name")}})
    await db.missions.update_many(ctx.q({"id": {"$in": [t["mission_id"] async for t in db.timesheets.find(ctx.q({"id": {"$in": body.ids}}), {"mission_id": 1})]}, "status": "confirmed"}), {"$set": {"status": "done"}})
    return {"validated": r.modified_count}


@router.post("/timesheets/{tid}/{action}")
async def review_ts(tid: str, action: Literal["correct", "refuse"], body: TimesheetIn, ctx: Ctx = Depends(P)):
    t = await ctx.get("timesheets", tid)
    if not body.reason.strip():
        raise HTTPException(400, "Motif obligatoire")
    if t["status"] not in ("declared", "validated"):
        raise HTTPException(409, "Heures déjà transmises")
    m = await ctx.get("missions", t["mission_id"])
    return await _save_ts(ctx, m, body, "validated" if action == "correct" else "refused", {"review_reason": body.reason, "validated_by": ctx.member.get("name")})


# ---------- Factures et paie ----------
def _invoice_pdf(org: dict, p: dict, c: dict, m: dict, t: dict, number: str, vat: float) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table
    ss, e = getSampleStyleSheet(), lambda s: escape(str(s or ""))  # noqa: E731
    ht = t["total_ht"]
    rows = [["Désignation", "Montant HT"], [f"Prestation du {pc.fr_date(m['date'])} ({t['hours']} h)", pc.money(t["amount_base"])]]
    rows += [[lbl, pc.money(v)] for lbl, v in (("Heures majorées", t["amount_overtime"]), ("Frais et déplacement", t["amount_expenses"])) if v]
    rows += [["Total HT", pc.money(ht)], [f"TVA {vat:g} %" if vat else "TVA", pc.money(ht * vat / 100)], ["Total TTC", pc.money(ht * (1 + vat / 100))]]
    out = [Paragraph(f"Facture n° {e(number)}", ss["Title"]), Paragraph(f"Date : {pc.fr_date(po.today())} — Date de prestation : {pc.fr_date(m['date'])}", ss["Normal"]), Spacer(1, 10),
           Paragraph(f"<b>{e(c.get('first_name'))} {e(c.get('last_name'))}</b><br/>SIRET : {e(p.get('siret') or 'à compléter')}<br/>{e(p.get('base_city'))}", ss["Normal"]), Spacer(1, 8),
           Paragraph(f"<b>Client :</b> {e(org.get('name'))}<br/>{e(org.get('address'))} {e(org.get('zip'))} {e(org.get('city'))}", ss["Normal"]), Spacer(1, 14), Table(rows, colWidths=[360, 120]), Spacer(1, 14)]
    if not vat:
        out.append(Paragraph("TVA non applicable, art. 293 B du CGI", ss["Normal"]))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, title=f"Facture {number}").build(out)
    return buf.getvalue()


@router.post("/portal/provider/missions/{mid}/make-invoice")
async def make_invoice(mid: str, request: Request, ctx: Ctx = Depends(PV)):
    m, p = await _mission(ctx, request, mid)
    t = await db.timesheets.find_one(ctx.q({"mission_id": mid}), {"_id": 0})
    if (p.get("employment_status") or "freelance") == "intermittent":
        raise HTTPException(403, "Un salarié intermittent ne facture pas : vos heures sont transmises en paie")
    if not t or t["status"] != "validated":
        raise HTTPException(409, "Vos heures doivent d'abord être validées")
    if await db.provider_invoices.find_one(ctx.q({"mission_id": mid})):
        raise HTTPException(409, "Facture déjà émise")
    seq = await db.provider_invoices.count_documents(ctx.q({"provider_id": p["id"]})) + 1
    number, vat = f"{po.today()[:4]}-{seq:03d}", float(p.get("vat_rate") or 0) if p.get("vat_mode") == "subject" else 0
    c, org = await db.contacts.find_one(ctx.q({"id": p["contact_id"]}), {"_id": 0}) or {}, await _org(ctx)
    ref = await store_bytes(ctx.org_id, await run_in_threadpool(_invoice_pdf, org, p, c, m, t, number, vat), "application/pdf", f"facture-{number}.pdf", ctx.member["user_id"])
    ttc = round(t["total_ht"] * (1 + vat / 100), 2)
    await ctx.insert("provider_invoices", {"provider_id": p["id"], "provider_name": m["provider_name"], "mission_id": mid, "timesheet_id": t["id"], "event_id": m.get("event_id"), "number": number, "date": po.today(), "service_date": m["date"],
                                           "total_ht": t["total_ht"], "vat_rate": vat, "total_ttc": ttc, "file": ref, "status": "sent", "paid_at": None, "gap": round(t["total_ht"] - m["total_ht"], 2)})
    await db.timesheets.update_one(ctx.q({"id": t["id"]}), {"$set": {"status": "invoiced"}})
    await db.missions.update_one(ctx.q({"id": mid}), {"$set": {"status": "invoiced", "provider_invoice_file": ref, "payment_status": "pending"}})
    return {"number": number, "total_ttc": ttc}


@router.get("/provider-invoices")
async def invoices(format: str = "", ctx: Ctx = Depends(P)):
    rows = await ctx.list("provider_invoices", sort=[("date", -1)], limit=1000)
    if format != "csv":
        return rows
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["N°", "Prestataire", "Date", "Prestation", "HT", "TVA %", "TTC", "Écart mission", "Statut", "Payée le"])
    for r in rows:
        w.writerow([r["number"], r["provider_name"], r["date"], r["service_date"], r["total_ht"], r["vat_rate"], r["total_ttc"], r["gap"], r["status"], r.get("paid_at") or ""])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="factures-prestataires.csv"'})


@router.post("/provider-invoices/{iid}/paid")
async def invoice_paid(iid: str, ctx: Ctx = Depends(P)):
    i = await ctx.update("provider_invoices", iid, {"status": "paid", "paid_at": po.today()})
    await db.timesheets.update_one(ctx.q({"id": i["timesheet_id"]}), {"$set": {"status": "paid"}})
    await db.missions.update_one(ctx.q({"id": i["mission_id"]}), {"$set": {"status": "paid", "payment_status": "paid"}})
    return i


@router.get("/payroll-export")
async def payroll(start: str = "", end: str = "", ctx: Ctx = Depends(P)):
    f = {"employment_status": "intermittent", "status": {"$in": ["validated", "payroll"]}, "date": {"$gte": start or "0", "$lte": end or "9"}}
    rows = await ctx.list("timesheets", f, sort=[("date", 1)], limit=2000)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Salarié", "Date", "Début", "Fin", "Pause (min)", "Heures", "Heures normales", "Heures majorées", "Heures de nuit", "Cachet / brut", "Frais", "Convention"])
    for t in rows:
        w.writerow([t["provider_name"], t["date"], t["start_time"], t["end_time"], t["break_min"], t["hours"], t["normal_hours"], t["overtime_hours"], t["night_hours"], t["amount_base"] + t["amount_overtime"], t["amount_expenses"], "IDCC 3090"])
    from routes_admin import cddu_rows
    for r in await cddu_rows(ctx, start or "0", end or "9", ["realise", "facture", "cloture"]):
        w.writerow([r["provider_name"], r["date"], r["start_time"], r["end_time"], 0, r["hours"], r["hours"], 0, 0, r["day_rate"], 0, "IDCC 3090 (heures du planning, non pointées)"])
    await db.timesheets.update_many(ctx.q({**f, "status": "validated"}), {"$set": {"status": "payroll", "payroll_at": now_iso()}})
    await audit(ctx.org_id, ctx.member, "export", "paie", f"{start} → {end} · {len(rows)} lignes")
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="export-paie.csv"'})


# ---------- Agenda, iCal ----------
class BusyIn(BaseModel):
    date: str = Field(pattern=DATE)
    title: str = Field("", max_length=120)


@router.get("/portal/provider/agenda")
async def agenda(request: Request, ctx: Ctx = Depends(PV)):
    p = await _profile(ctx, request)
    lab, day, items = await pc.labels(ctx.org_id), po.today(), []
    async for m in db.missions.find(ctx.q({"provider_id": p["id"], "status": {"$in": VISIBLE}, "date": {"$gte": day}}), {"_id": 0}):
        items.append({"kind": "mission", "date": m["date"], "start_time": m["start_time"], "end_time": m["end_time"], "label": f"{lab.get(m['category_key'], m['category_key'])} · {m.get('venue_city', '')}", "id": m["id"]})
    async for a in db.position_applications.find(ctx.q({"provider_id": p["id"], "status": "invited"}), {"_id": 0}):
        pos = await db.positions.find_one(ctx.q({"id": a["position_id"], "date": {"$gte": day}}), {"_id": 0})
        if pos:
            items.append({"kind": "invitation", "date": pos["date"], "start_time": pos["start_time"], "end_time": pos["end_time"], "label": lab.get(pos["category_key"], pos["category_key"]), "id": a["id"]})
    async for u in db.provider_unavailabilities.find(ctx.q({"provider_id": p["id"], "date": {"$gte": day}, "source": {"$ne": "mission"}, "cancelled_at": None}), {"_id": 0}):
        items.append({"kind": "busy", "date": u["date"], "start_time": "", "end_time": "", "label": u.get("private_title") or u.get("note") or "", "id": u["id"], "mine": u.get("source") in ("provider", "external")})
    return {"today": day, "items": sorted(items, key=lambda i: (i["date"], i["start_time"])), "ical": bool(p.get("ical_hash"))}


@router.post("/portal/provider/busy")
async def add_busy(body: BusyIn, request: Request, ctx: Ctx = Depends(PV)):
    p = await _profile(ctx, request)
    return {"id": (await ctx.insert("provider_unavailabilities", {"provider_id": p["id"], "date": body.date, "start_time": "", "end_time": "", "note": "", "private_title": body.title, "source": "external"}))["id"]}


@router.post("/portal/provider/ical/{action}")
async def ical_token(action: Literal["create", "revoke"], request: Request, ctx: Ctx = Depends(PV)):
    p = await _profile(ctx, request)
    tok = new_id().replace("-", "") + os.urandom(8).hex() if action == "create" else ""
    await db.provider_profiles.update_one(ctx.q({"id": p["id"]}), {"$set": {"ical_hash": sha256(tok) if tok else ""}})
    return {"url": f"/api/public/ical/{tok}.ics" if tok else ""}


@router.get("/public/ical/{token}.ics")
async def ical(token: str):
    p = await db.provider_profiles.find_one({"ical_hash": sha256(token)}, {"_id": 0}) if len(token) >= 40 else None
    if not p:
        raise HTTPException(404, "Introuvable")
    lab, ev = await pc.labels(p["org_id"]), []
    async for m in db.missions.find({"org_id": p["org_id"], "provider_id": p["id"], "status": {"$in": VISIBLE}}, {"_id": 0}):
        d = m["date"].replace("-", "")
        ev.append(f"BEGIN:VEVENT\r\nUID:{m['id']}\r\nDTSTART;TZID=Europe/Paris:{d}T{m['start_time'].replace(':', '')}00\r\nDTEND;TZID=Europe/Paris:{d}T{m['end_time'].replace(':', '')}00\r\nSUMMARY:Mission {lab.get(m['category_key'], '')} {m.get('venue_city', '')}\r\nEND:VEVENT")
    return Response("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Exclusivity Events//Staff//FR\r\n" + "\r\n".join(ev) + "\r\nEND:VCALENDAR\r\n", media_type="text/calendar")


# ---------- Planning et statistiques ----------
@router.get("/staff/planning")
async def planning(start: str = "", end: str = "", ctx: Ctx = Depends(P)):
    start = start or po.today()
    end = end or (datetime.strptime(start, "%Y-%m-%d") + timedelta(days=13)).strftime("%Y-%m-%d")
    by: dict = {}
    for m in await ctx.list("missions", {"status": {"$in": VISIBLE}, "date": {"$gte": start, "$lte": end}}, sort=[("date", 1), ("start_time", 1)], limit=2000):
        by.setdefault(m["provider_id"], []).append(m)
    from routes_admin import cddu_rows
    for r in await cddu_rows(ctx, start, end, ["confirme", "en_preparation", "realise"]):
        by.setdefault(r["provider_id"], []).append(r)
    rows = []
    for ms in by.values():
        ms.sort(key=lambda m: (m["date"], m["start_time"]))
        alerts = []
        for a, b in zip(ms, ms[1:]):
            sa, ea, sb = _mins(a["start_time"]), _mins(a["end_time"]), _mins(b["start_time"])
            ea += 1440 if ea <= sa else 0
            gap = (datetime.strptime(b["date"], "%Y-%m-%d") - datetime.strptime(a["date"], "%Y-%m-%d")).days * 1440 + sb - ea
            if gap < 0:
                alerts.append(f"Chevauchement le {pc.fr_date(b['date'])}")
            elif gap < 660 and a.get("employment_status") == "intermittent":
                alerts.append(f"Repos inférieur à 11 h avant le {pc.fr_date(b['date'])}")
        alerts += [f"Durée supérieure à 12 h le {pc.fr_date(m['date'])}" for m in ms if m.get("employment_status") == "intermittent" and _hours(m["start_time"], m["end_time"]) > 12]
        rows.append({"provider_name": ms[0]["provider_name"], "alerts": alerts, "missions": [{k: m.get(k) for k in ("id", "date", "start_time", "end_time", "venue_city", "employment_status", "event_id")} for m in ms]})
    return {"start": start, "end": end, "rows": sorted(rows, key=lambda r: r["provider_name"])}


@router.get("/staff/stats")
async def stats(start: str = "", end: str = "", ctx: Ctx = Depends(P)):
    f = {"date": {"$gte": start or "0", "$lte": end or "9"}}
    ms = await ctx.list("missions", {**f, "status": {"$in": VISIBLE}}, limit=5000)
    ts = {t["mission_id"]: t for t in await ctx.list("timesheets", {**f, "status": {"$in": ["validated", "invoiced", "payroll", "paid"]}}, limit=5000)}
    pos = await ctx.list("positions", {**f, "archived_at": None}, limit=5000)
    titles = {e["id"]: e["title"] for e in await ctx.list("events", {"id": {"$in": list({m.get("event_id") for m in ms if m.get("event_id")})}})}
    ev, pr = {}, {}
    for m in ms:
        t = ts.get(m["id"])
        e = ev.setdefault(m.get("event_id") or "", {"title": titles.get(m.get("event_id"), "Sans événement"), "planned": 0, "real": 0})
        e["planned"] += m["total_ht"]
        e["real"] += t["total_ht"] if t else 0
        p = pr.setdefault(m["provider_id"], {"name": m["provider_name"], "missions": 0, "hours": 0, "paid": 0})
        p["missions"] += 1
        p["hours"] += t["hours"] if t else 0
        p["paid"] += t["total_ht"] if t and t["status"] == "paid" else 0
    return {"events": list(ev.values()), "providers": sorted(pr.values(), key=lambda x: -x["missions"]), "missions": len(ms), "cost": round(sum(m["total_ht"] for m in ms), 2),
            "freelance": sum(1 for m in ms if m.get("employment_status") != "intermittent"), "intermittent": sum(1 for m in ms if m.get("employment_status") == "intermittent"),
            "fill_rate": round(100 * sum(1 for p in pos if p["status"] == "filled") / len(pos)) if pos else None, "withdrawals": await db.missions.count_documents(ctx.q({**f, "withdrawn_at": {"$ne": None}}))}
