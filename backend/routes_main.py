import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Literal, Optional

import requests
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from core import (DEFAULT_ROLE, IN_ENV, MODULE_IDS, PERMS, RANK, ROLE_LABELS, ROLES, Ctx, current_member,
                  db, effective_role, need, new_id, now_iso)

from core import ENV, PORTAL_ROLES, STAFF_2FA, _clerk_user, now_iso, twofa_exempt  # noqa: E402,F811

router = APIRouter(prefix="/api")
ORG_SENSITIVE = ("iban", "siret", "vat_number", "payment_terms", "legal_mentions")


def org_view(org: dict | None, perms: set) -> dict | None:
    if org and not ({"finance:read", "org:write"} & perms):
        return {k: v for k, v in org.items() if k not in ORG_SENSITIVE}
    return org


# ---------- Me / onboarding ----------
@router.get("/me")
async def me(request: Request, member: dict = Depends(current_member)):
    org = await db.orgs.find_one({"id": member["org_id"]}, {"_id": 0}) if member.get("org_id") else None
    if member["role"] in PORTAL_ROLES:
        return {"user": {"name": member.get("name"), "email": member.get("email"), "role": member["role"], "team_id": None},
                "org": {"name": (org or {}).get("name", "")}, "perms": sorted(PERMS[member["role"]]), "roles": []}
    if member.get("status") in ("suspended", "disabled", "deleted"):
        raise HTTPException(403, "Votre accès est désactivé. Contactez votre administrateur.")
    needs_2fa = False
    from core import audit, needs_2fa as twofa_needed, perms_of, preview_target, profile_of
    prof = await profile_of(member)
    if org and twofa_needed(member, prof, await twofa_exempt(member.get("org_id"))):
        two = bool((await run_in_threadpool(_clerk_user, member["user_id"])).get("two_factor_enabled"))
        await db.users.update_one({"user_id": member["user_id"]}, {"$set": {"two_factor": two}})
        needs_2fa = not two
    pv = await preview_target(request, member, prof) if org else None
    if pv:
        await audit(member["org_id"], member, "view_as_member", pv[0].get("email", ""), (pv[1] or {}).get("name", ""))
        member, prof = pv
        member["role"] = effective_role(member.get("role"))
    perms = perms_of(member, prof)
    return {"needs_2fa": needs_2fa, "preview": member.get("name") or member.get("email") if pv else None,
            "grid": None if not prof or prof.get("locked") else __import__("access_grid").fill(prof.get("permissions"), perms), "user": {"name": member.get("name"), "email": member.get("email"), "role": member["role"],
                     "team_id": member.get("team_id")},
            "org": org_view(org, perms), "perms": sorted(perms) if org else [],
            "plan": __import__("plans").summary(org) if org else None,
            "roles": [{"id": r, "label": ROLE_LABELS[r]} for r in ROLES]}


class OnboardingIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=120)
    city: str = ""


@router.post("/onboarding")
async def onboarding(body: OnboardingIn, member: dict = Depends(current_member)):
    if member.get("org_id"):
        raise HTTPException(400, "Votre compte est déjà rattaché à une entreprise")
    org = {"id": new_id(), "name": body.company_name, "slug": new_id(), "city": body.city,
           "modules": ["loueur_materiel"], "default_vat": 20, "deposit_percent": 30,
           "quote_prefix": "DEV", "invoice_prefix": "FAC", "created_at": now_iso(),
           "subscription": __import__("plans").new_trial("pro")}
    await db.orgs.insert_one(org)
    import server
    import tenant_router as tenants
    await tenants.provision(org["id"], server.INDEXES)  # base dédiée t_<org_id> et ses index
    tenants.pin_org(org["id"])
    team_id = new_id()
    await db.team.insert_one({"id": team_id, "org_id": org["id"], "name": member.get("name"), "email": member.get("email"),
                              "phone": "", "job": "Direction", "access_role": "admin", "skills": [], "color": "#B4643C",
                              "user_id": member["user_id"], "active": True, "created_at": now_iso()})
    await db.users.update_one({"user_id": member["user_id"]},
                              {"$set": {"org_id": org["id"], "role": "admin", "team_id": team_id}})
    return {"ok": True}


# ---------- Organisation & modules ----------
class OrgIn(BaseModel):
    name: str
    legal_name: str = ""
    siret: str = ""
    vat_number: str = ""
    address: str = ""
    zip: str = ""
    city: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    logo_url: str = ""
    legal_mentions: str = ""
    terms_annex: bool = True
    legal_form_capital: str = Field("", max_length=120)
    rcs: str = Field("", max_length=80)
    ape: str = Field("", max_length=12)
    licence: str = Field("", max_length=60)
    mediator: str = Field("", max_length=120)
    bic: str = Field("", max_length=11)
    quote_validity_days: int = Field(30, ge=1, le=365)
    balance_days: int = Field(15, ge=0, le=365)
    iban: str = ""
    payment_terms: str = ""
    quote_prefix: str = "DEV"
    invoice_prefix: str = "FAC"
    default_vat: float = 20
    deposit_percent: float = 30
    terms: str = Field("", max_length=20000)
    signature_fields: List[str] = Field(default=["Nom et qualité du signataire", "Adresse de facturation", "Mention « Bon pour accord »"], max_length=6)
    terms_en: str = Field("", max_length=20000)
    payment_terms_en: str = Field("", max_length=5000)
    legal_mentions_en: str = Field("", max_length=5000)
    signature_fields_en: List[str] = Field(default=[], max_length=6)


@router.get("/org")
async def get_org(ctx: Ctx = Depends(need())):
    return org_view(await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}), ctx.perms)


@router.post("/org/terms-file")
async def put_terms_file(lang: Literal["fr", "en"] = "fr", file: UploadFile = File(...), ctx: Ctx = Depends(need("org:write"))):
    from routes_files import read_upload, store_bytes
    data, ctype = await read_upload(file)
    if ctype != "application/pdf":
        raise HTTPException(400, "Un PDF est attendu")
    ref = await store_bytes(ctx.org_id, data, ctype, file.filename or "", ctx.member.get("name"))
    await db.orgs.update_one({"id": ctx.org_id}, {"$set": {f"terms_file_{lang}": {"id": ref[5:], "filename": (file.filename or "")[:200]}}})
    return await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})


@router.delete("/org/terms-file")
async def del_terms_file(lang: Literal["fr", "en"] = "fr", ctx: Ctx = Depends(need("org:write"))):
    await db.orgs.update_one({"id": ctx.org_id}, {"$unset": {f"terms_file_{lang}": ""}})
    return await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})


@router.put("/org")
async def put_org(body: OrgIn, ctx: Ctx = Depends(need("org:write"))):
    await db.orgs.update_one({"id": ctx.org_id}, {"$set": body.model_dump()})
    return await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})


class ModulesIn(BaseModel):
    modules: List[str]


@router.put("/org/modules")
async def put_modules(body: ModulesIn, ctx: Ctx = Depends(need("org:write"))):
    mods = [m for m in MODULE_IDS if m in body.modules]
    import plans
    plans.check_business_modules(await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}) or {}, mods)
    await db.orgs.update_one({"id": ctx.org_id}, {"$set": {"modules": mods}})
    return {"modules": mods}


MODULE_DEFS = [("dj", "DJ / Animateur"), ("son_lumiere", "Son & Lumière"), ("photobooth", "Photobooth"), ("photographe", "Photographe"),
               ("wedding_planner", "Wedding planner"), ("agence", "Agence événementielle"), ("loueur_materiel", "Loueur de matériel")]
MODULE_DEFAULTS = {"Mariage": ["dj", "son_lumiere"]}


async def seed_module_defs() -> None:
    for i, (k, label) in enumerate(MODULE_DEFS):
        await db.module_defs.update_one({"key": k}, {"$setOnInsert": {"key": k, "label": label, "order": i, "active": True}}, upsert=True)


async def module_catalog(org_id: str) -> list:
    org = await db.orgs.find_one({"id": org_id}, {"_id": 0}) or {}
    rows = await db.module_defs.find({"active": True}, {"_id": 0}).sort("order", 1).to_list(100)
    return [{"key": r["key"], "label": r["label"]} for r in rows if r["key"] in org.get("modules", [])]


@router.get("/modules")
async def list_modules(ctx: Ctx = Depends(need())):
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}) or {}
    mods = await module_catalog(ctx.org_id)
    keys = {m["key"] for m in mods}
    d = org.get("module_defaults")
    d = MODULE_DEFAULTS if d is None else d
    return {"modules": mods, "defaults": {t: [k for k in ks if k in keys] for t, ks in d.items()}}


class ModuleDefaultsIn(BaseModel):
    defaults: Dict[str, List[str]] = Field(max_length=40)


@router.put("/org/module-defaults")
async def put_module_defaults(body: ModuleDefaultsIn, ctx: Ctx = Depends(need("org:write"))):
    keys = {m["key"] for m in await module_catalog(ctx.org_id)}
    d = {t[:60]: [k for k in ks if k in keys] for t, ks in body.defaults.items() if t.strip()}
    await db.orgs.update_one({"id": ctx.org_id}, {"$set": {"module_defaults": d}})
    return {"defaults": d}


# ---------- Users (access) ----------
@router.get("/users")
async def list_users(ctx: Ctx = Depends(need("users:manage"))):
    people = await db.users.find({"org_id": ctx.org_id, "role": {"$nin": PORTAL_ROLES}, **IN_ENV}, {"_id": 0}).to_list(1000)
    return {"roles": [{"id": r, "label": ROLE_LABELS[r]} for r in ROLES if RANK[r] <= RANK[ctx.role]],
            "users": [{**p, "role": effective_role(p.get("role"))} for p in people]}


class RoleIn(BaseModel):
    role: str


@router.patch("/users/{user_id}/role")
async def set_role(user_id: str, body: RoleIn, ctx: Ctx = Depends(need("users:manage"))):
    if body.role not in ROLES or RANK[body.role] > RANK[ctx.role]:
        raise HTTPException(403, "Vous ne pouvez pas attribuer ce rôle")
    target = await db.users.find_one({"user_id": user_id, "org_id": ctx.org_id, **IN_ENV}, {"_id": 0})
    if target is None:
        raise HTTPException(404, "Introuvable")
    if target.get("role") in PORTAL_ROLES or RANK[effective_role(target.get("role"))] > RANK[ctx.role]:
        raise HTTPException(403, "Vous ne pouvez pas modifier ce compte")
    if (effective_role(target.get("role")) == "admin" and body.role != "admin"
            and await db.users.count_documents({"org_id": ctx.org_id, "role": "admin", **IN_ENV}) <= 1):
        raise HTTPException(409, "Il faut conserver au moins un administrateur")
    await db.users.update_one({"user_id": user_id}, {"$set": {"role": body.role}})
    if target.get("team_id"):
        await db.team.update_one({"id": target["team_id"], "org_id": ctx.org_id}, {"$set": {"access_role": body.role}})
    return {"user_id": user_id, "role": body.role}


# ---------- Team ----------
class Unavailability(BaseModel):
    start: str
    end: str
    reason: str = ""


class TeamIn(BaseModel):
    name: str = Field(min_length=1)
    email: str = ""
    phone: str = ""
    job: str = ""
    access_role: str = DEFAULT_ROLE
    skills: List[str] = []
    color: str = "#B4643C"
    day_rate: float = 0
    active: bool = True
    unavailabilities: List[Unavailability] = []
    contract_type: Literal["cdi", "cdd", "cddu", "alternance", "stage", "independant", "externe", "autre"] = "cdi"
    start_date: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    end_date: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    licences: List[Literal["B", "BE", "C1", "C", "CE"]] = []
    licence_valid_until: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    is_driver: bool = False
    send_invite: bool = False


async def _member_invite(ctx: Ctx, t: dict, base: str) -> dict:
    """Crée (ou renouvelle) le lien d'invitation d'un membre et tente l'envoi ; ne lève jamais : le résultat est écrit sur la fiche."""
    import portal_core as po
    from core import _admin_emails, audit
    from emailer import mail_html, send_email
    base = (os.environ.get("APP_URL") or base).rstrip("/")
    email, key = (t.get("email") or "").strip().lower(), ctx.q({"id": t["id"]})
    upd, link = {"invited_at": now_iso(), "invited_by": ctx.member.get("name", "")}, ""
    try:
        if not po.pc.MAIL_RE.match(email):
            raise HTTPException(400, "Adresse e-mail absente ou invalide sur la fiche")
        found = await po.clerk("GET", "/users", params={"email_address": email})
        if found:
            cu = found[0]
            if await db.users.find_one({"user_id": cu["id"]}):
                raise HTTPException(409, "Cette adresse e-mail est déjà rattachée à un autre compte de l'application")
        else:
            first, _, last = t["name"].partition(" ")
            body = {"email_address": [email], "first_name": first or None, "last_name": last or None}
            try:
                cu = await po.clerk("POST", "/users", json={**body, "skip_password_requirement": True})
            except HTTPException:
                cu = await po.clerk("POST", "/users", json={**body, "password": secrets.token_urlsafe(32), "skip_password_checks": True})
        if t.get("invite_token_id"):
            try:
                await po.clerk("POST", f"/sign_in_tokens/{t['invite_token_id']}/revoke")
            except HTTPException:
                pass
        tok = await po.clerk("POST", "/sign_in_tokens", json={"user_id": cu["id"], "expires_in_seconds": po.INVITE_DAYS * 86400})
        link = f"{base}/sign-in?__clerk_ticket={tok['token']}"
        upd.update(invite_token_id=tok["id"], invite_link=link, invite_expires_at=(datetime.now(timezone.utc) + timedelta(days=po.INVITE_DAYS)).isoformat())
        if "+clerk_test@" in email or email.endswith("@example.com"):
            raise HTTPException(400, "Adresse de test : aucun e-mail n'est envoyé. Copiez le lien et transmettez-le.")
        org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}) or {}
        await send_email(to=email, subject=f"{org.get('name', '')} : créez votre accès", html=mail_html(org.get("name", ""), f"Bonjour {t['name'].split(' ')[0]},", [
            f"{ctx.member.get('name') or 'Votre responsable'} vous invite à rejoindre l'espace de travail {org.get('name', '')}.",
            "Ce lien personnel est valable 7 jours et ne fonctionne qu'une fois. Vous choisirez ensuite votre mot de passe."], ("Créer mon accès", link), "fr-FR"))
        upd.update(invite_status="sent", invite_error="")
    except HTTPException as exc:
        d = exc.detail if isinstance(exc.detail, str) else "Envoi impossible"
        upd.update(invite_status="error", invite_error=("Nombre maximal de comptes atteint chez Clerk (100 en mode développement)" if "quota" in d.lower() else d)[:300])
    await db.team.update_one(key, {"$set": upd, **({"$addToSet": {"invite_token_history": upd["invite_token_id"]}} if upd.get("invite_token_id") else {})})
    await audit(ctx.org_id, ctx.member, "member_invitation", email or t["name"], "e-mail envoyé" if upd["invite_status"] == "sent" else f"échec : {upd['invite_error']}" + (" (lien créé)" if link else ""))
    return _access(await ctx.get("team", t["id"]), {})


def _access(r: dict, users: dict) -> dict:
    u = users.get(r.get("user_id"))
    r["access"] = {"status": ("suspended" if (u or {}).get("status") == "suspended" else "active") if r.get("user_id") else r.get("invite_status") or "none",
                   "invited_at": r.get("invited_at", ""), "error": r.get("invite_error", ""), "has_link": bool(r.get("invite_link")) and not r.get("user_id")}
    for k in ("invite_link", "invite_token_id", "invite_token_history"):
        r.pop(k, None)
    return r


def _check_grant(ctx: Ctx, role: str):
    if role not in ROLES or RANK[role] > RANK[ctx.role]:
        raise HTTPException(403, "Vous ne pouvez pas attribuer ce rôle")


@router.get("/team")
async def list_team(ctx: Ctx = Depends(need("team:read"))):
    rows = await ctx.list("team", sort=[("name", 1)])
    users = {u["user_id"]: u async for u in db.users.find(ctx.q({"user_id": {"$in": [r["user_id"] for r in rows if r.get("user_id")]}}), {"_id": 0})}
    for r in rows:
        _access(r, users)
        r["employment_status"] = "intermittent" if r.get("contract_type") == "cddu" else "salarie"
        if not ctx.can("finance:read"):
            r.pop("day_rate", None)
    return rows


@router.post("/team")
async def create_team(body: TeamIn, request: Request, ctx: Ctx = Depends(need("team:write"))):
    _check_grant(ctx, body.access_role)
    data = body.model_dump()
    send = data.pop("send_invite")
    data["email"] = data["email"].strip().lower()
    if data["email"] and await db.team.find_one(ctx.q({"email": data["email"]})):
        raise HTTPException(409, "Un membre utilise déjà cet e-mail")
    t = await ctx.insert("team", {**data, "user_id": None})
    if send and data["email"]:
        from routes_comms import base_url
        return await _member_invite(ctx, t, base_url(request))
    return _access(t, {})


@router.post("/team/{tid}/invite")
async def invite_member(tid: str, request: Request, ctx: Ctx = Depends(need("team:write"))):
    t = await ctx.get("team", tid)
    if t.get("user_id"):
        raise HTTPException(409, "Ce membre a déjà un compte actif")
    _check_grant(ctx, t.get("access_role") or DEFAULT_ROLE)
    import plans
    staff = await db.users.count_documents({"org_id": ctx.org_id, "role": {"$in": ROLES}, "status": {"$nin": ["suspended", "deleted", "disabled"]}})
    plans.check_seats(await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}) or {}, staff)
    from routes_comms import base_url
    return await _member_invite(ctx, t, base_url(request))


@router.get("/team/{tid}/invite-link")
async def member_invite_link(tid: str, ctx: Ctx = Depends(need("team:write"))):
    t = await ctx.get("team", tid)
    if t.get("user_id") or not t.get("invite_link"):
        raise HTTPException(404, "Aucun lien d'invitation en attente : envoyez d'abord l'invitation")
    return {"link": t["invite_link"], "expires_at": t.get("invite_expires_at", "")}


@router.put("/team/{tid}")
async def update_team(tid: str, body: TeamIn, ctx: Ctx = Depends(need("team:write"))):
    cur = await ctx.get("team", tid)
    data = body.model_dump()
    data.pop("send_invite")
    data["email"] = data["email"].strip().lower()
    if cur.get("user_id"):
        data.pop("access_role")
        data["email"] = cur.get("email", "")
    else:
        _check_grant(ctx, body.access_role)
    if data["end_date"] != (cur.get("end_date") or ""):
        data.update(end_reminded=False, contract_ended=False)
    t = await ctx.update("team", tid, data)
    if data["end_date"]:
        import routes_access
        await routes_access.tick(ctx.org_id)
    return t


@router.delete("/team/{tid}")
async def delete_team(tid: str, ctx: Ctx = Depends(need("team:write"))):
    cur = await ctx.get("team", tid)
    if cur.get("user_id"):
        raise HTTPException(400, "Ce membre a un compte actif : désactivez-le plutôt")
    await ctx.delete("team", tid)
    return {"ok": True}


@router.get("/team/{tid}/missions")
async def team_missions(tid: str, ctx: Ctx = Depends(need("team:read"))):
    if ctx.assigned_only and tid != ctx.team_id:
        raise HTTPException(404, "Introuvable")
    evs = await ctx.list("events", {"team.member_id": tid}, sort=[("start", 1)])
    return [{"id": e["id"], "code": e["code"], "title": e["title"], "start": e["start"], "end": e["end"],
             "status": e["status"], "role": next((t.get("role") for t in e.get("team", []) if t["member_id"] == tid), "")}
            for e in evs]


# ---------- Contacts ----------
class ContactIn(BaseModel):
    kind: str = "particulier"
    status: str = "prospect"
    first_name: str = ""
    last_name: str = ""
    company: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    city: str = ""
    source: str = ""
    tags: List[str] = []
    notes: str = ""
    types: List[str] = ["client"]
    statuses: Dict[str, str] = {}
    language: str = "fr-FR"
    instagram_handle: str = Field("", max_length=80)


CONTACT_TYPES = ["client", "prestataire", "lieu", "fournisseur", "autre"]


def _contact(body: ContactIn) -> dict:
    d = body.model_dump()
    d["types"] = [t for t in CONTACT_TYPES if t in d["types"]] or ["client"]
    from i18n import clean_lang
    d["language"] = clean_lang(d["language"])
    return d


class InteractionIn(BaseModel):
    type: str = "note"
    note: str = Field(min_length=1)
    at: Optional[str] = None


def contact_name(c: dict) -> str:
    if c.get("kind") == "entreprise" and c.get("company"):
        return c["company"]
    return " ".join(filter(None, [c.get("first_name"), c.get("last_name")])) or c.get("company") or "—"


@router.get("/contacts")
async def list_contacts(ctx: Ctx = Depends(need("contacts:read")), q: str = "", status: str = "", type: str = "", role: str = "", provider_category: str = "", exclude_wp: bool = False):
    import contact_status as cs
    profs, labs = await cs.profiles(ctx.org_id), await cs.labels(ctx.org_id)
    f, ands = {}, []
    if type:
        f["types"] = type
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        hit = [cid for cid, p in profs.items() if any(q.lower() in labs.get(k, k).lower() for k in p.get("categories") or [])]
        ands.append({"$or": [{"first_name": rx}, {"last_name": rx}, {"company": rx}, {"email": rx}, {"city": rx}, {"types": "prestataire", "id": {"$in": hit}}, {"id": {"$in": await __import__("contact_people").search_owner_ids(ctx.org_id, q)}}]})
    wp = [cid for cid, p in profs.items() if cs.WP in (p.get("categories") or [])]
    if role == "wedding_planner":
        ands.append({"types": "prestataire", "id": {"$in": wp}})
    if exclude_wp:
        ands.append({"id": {"$nin": wp}})
    if provider_category:
        want = set(provider_category.split(","))
        ands.append({"types": "prestataire", "id": {"$in": [cid for cid, p in profs.items() if want & set(p.get("categories") or [])]}})
    if ands:
        f["$and"] = ands
    rows = await ctx.list("contacts", f, sort=[("created_at", -1)])
    counts = {}
    for e in await ctx.list("events", {}, limit=5000):
        counts[e.get("client_id")] = counts.get(e.get("client_id"), 0) + 1
    for r in rows:
        r["display_name"] = contact_name(r)
        r["events_count"] = counts.get(r["id"], 0)
    await cs.enrich(ctx.org_id, rows, profs, labs)
    if q:
        import contact_people as cp
        for p in await cp.people(ctx.org_id, [r["id"] for r in rows]):
            if q.lower() in f"{p['name']} {p.get('email', '')}".lower():
                next(r for r in rows if r["id"] == p["contact_id"]).setdefault("matched_people", []).append(f"{p['name']} — {p['role_label']}")
    return [r for r in rows if status in r["statuses"].values()] if status else rows


@router.get("/contacts/{cid}")
async def get_contact(cid: str, ctx: Ctx = Depends(need("contacts:read"))):
    import contact_status as cs
    c = await ctx.get("contacts", cid)
    c["display_name"] = contact_name(c)
    evs = await ctx.list("events", {"$or": [{"client_id": cid}, {"client_contact_ids": cid}, {"planner_contact_id": cid}]}, sort=[("start", -1)])
    c["events"] = [{"id": e["id"], "code": e["code"], "title": e["title"], "start": e["start"], "status": e["status"],
                    "amount_ht": e.get("amount_ht") if ctx.can("finance:read") else None} for e in evs]
    await cs.enrich(ctx.org_id, [c])
    today = now_iso()[:10]
    brought = [e for e in evs if e.get("planner_contact_id") == cid]
    c["planner_events"] = {"upcoming": sum(1 for e in brought if (e.get("start") or "")[:10] >= today), "past": sum(1 for e in brought if (e.get("start") or "")[:10] < today)}
    return c


@router.post("/contacts")
async def create_contact(body: ContactIn, ctx: Ctx = Depends(need("contacts:write"))):
    import contact_status as cs
    d = _contact(body)
    await cs.clean(ctx, d)
    return await ctx.insert("contacts", {**d, "interactions": []})


@router.put("/contacts/{cid}")
async def update_contact(cid: str, body: ContactIn, ctx: Ctx = Depends(need("contacts:write"))):
    import contact_status as cs
    d = _contact(body)
    hist = await cs.clean(ctx, d, await ctx.get("contacts", cid))
    r = await ctx.update("contacts", cid, d)
    if hist:
        await db.contacts.update_one(ctx.q({"id": cid}), {"$push": {"status_history": {"$each": hist}}})
    return r


@router.delete("/contacts/{cid}")
async def delete_contact(cid: str, ctx: Ctx = Depends(need("contacts:write"))):
    if await db.events.find_one(ctx.q({"$or": [{"client_id": cid}, {"client_contact_ids": cid}, {"planner_contact_id": cid}]})):
        raise HTTPException(400, "Ce contact est lié à des événements")
    await ctx.delete("contacts", cid)
    await db.conversations.update_many(ctx.q({"contact_id": cid, "deleted_at": None}), {"$set": {"deleted_at": now_iso(), "deleted_reason": "contact"}})
    return {"ok": True}


@router.post("/contacts/{cid}/interactions")
async def add_interaction(cid: str, body: InteractionIn, ctx: Ctx = Depends(need("contacts:write"))):
    await ctx.get("contacts", cid)
    it = {"id": new_id(), "type": body.type, "note": body.note, "at": body.at or now_iso(), "by": ctx.member.get("name")}
    await db.contacts.update_one(ctx.q({"id": cid}), {"$push": {"interactions": it}})
    return it


# ---------- Venues ----------
class VenueSection(BaseModel):
    id: str = ""
    name: str = Field(min_length=1, max_length=80)
    notes: str = Field("", max_length=500)
    description: str = Field("", max_length=500)
    indoor: bool = True
    vehicle_access: bool = False
    power: str = Field("", max_length=120)
    transfer_minutes: int = Field(0, ge=0, le=240)


def normalize_onsite(data: dict) -> dict:
    cs = data.get("onsite_contacts")
    if cs is None:
        cs = [{"id": "", "name": data.get("contact_name") or "Contact sur place", "role": "", "phone": data.get("contact_phone", ""), "email": data.get("contact_email", ""),
               "notes": "", "is_primary": True, "language": "fr-FR"}] if data.get("contact_name") or data.get("contact_phone") or data.get("contact_email") else []
    cs = cs[:12]
    main = next((c for c in cs if c.get("is_primary")), cs[0] if cs else None)
    for c in cs:
        c["id"] = c.get("id") or new_id()
        c["is_primary"] = c is main
    data.update(onsite_contacts=cs, contact_name=main["name"] if main else "", contact_phone=main["phone"] if main else "", contact_email=main["email"] if main else "")
    return data


def onsite_for(venue: dict | None, ids: list | None) -> list:
    cs = (venue or {}).get("onsite_contacts") or []
    return [c for c in cs if c["id"] in (ids or [])] or [c for c in cs if c.get("is_primary")]


class OnsiteContact(BaseModel):
    id: str = ""
    name: str = Field(min_length=1, max_length=120)
    role: str = Field("", max_length=80)
    phone: str = Field("", max_length=40)
    email: str = Field("", max_length=160)
    notes: str = Field("", max_length=500)
    is_primary: bool = False
    language: str = Field("fr-FR", max_length=10)


def _venue(body) -> dict:
    data = normalize_onsite(body.model_dump())
    for s in data["sections"]:
        s["id"] = s["id"] or new_id()
    return data


class VenueIn(BaseModel):
    name: str = Field(min_length=1)
    instagram_handle: str = Field("", max_length=80)
    type: str = "Domaine"
    address: str = ""
    zip: str = ""
    city: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    capacity: int = 0
    power_capacity_w: float = Field(0, ge=0)
    contact_name: str = ""
    contact_phone: str = ""
    contact_email: str = ""
    onsite_contacts: Optional[List[OnsiteContact]] = None
    truck_access: str = ""
    electricity: str = ""
    sound_limiter: str = ""
    setup_hours: str = ""
    teardown_hours: str = ""
    access_instructions: str = Field("", max_length=1000)
    photos: List[str] = []
    plans: List[str] = []
    sections: List[VenueSection] = []
    notes: str = ""


@router.get("/venues")
async def list_venues(ctx: Ctx = Depends(need("venues:read"))):
    rows = await ctx.list("venues", sort=[("name", 1)])
    counts = {}
    for e in await ctx.list("events", ctx.event_scope(), limit=5000):
        counts[e.get("venue_id")] = counts.get(e.get("venue_id"), 0) + 1
    for r in rows:
        r["events_count"] = counts.get(r["id"], 0)
    return rows


@router.get("/venues/{vid}")
async def get_venue(vid: str, ctx: Ctx = Depends(need("venues:read"))):
    v = await ctx.get("venues", vid)
    evs = await ctx.list("events", {"venue_id": vid, **ctx.event_scope()}, sort=[("start", -1)])
    v["events"] = [{"id": e["id"], "code": e["code"], "title": e["title"], "start": e["start"], "status": e["status"]} for e in evs]
    return v


@router.post("/venues")
async def create_venue(body: VenueIn, ctx: Ctx = Depends(need("venues:write"))):
    v = await ctx.insert("venues", _venue(body))
    import contact_people as cp
    await cp.sync_venue(ctx.org_id, v)
    return v


@router.put("/venues/{vid}")
async def update_venue(vid: str, body: VenueIn, ctx: Ctx = Depends(need("venues:write"))):
    v = await ctx.update("venues", vid, _venue(body))
    import contact_people as cp
    await cp.sync_venue(ctx.org_id, v)
    return v


@router.delete("/venues/{vid}")
async def delete_venue(vid: str, ctx: Ctx = Depends(need("venues:write"))):
    if await db.events.find_one(ctx.q({"venue_id": vid})):
        raise HTTPException(400, "Ce lieu est lié à des événements")
    await ctx.delete("venues", vid)
    return {"ok": True}


def _nominatim(q: str) -> list:
    r = requests.get("https://nominatim.openstreetmap.org/search", timeout=10,
                     params={"q": q, "format": "json", "limit": 5, "countrycodes": "fr"},
                     headers={"User-Agent": "exclusivity-events-erp/1.0"})
    r.raise_for_status()
    return [{"lat": float(x["lat"]), "lng": float(x["lon"]), "label": x["display_name"]} for x in r.json()]


@router.get("/geocode")
async def geocode(q: str = Query(min_length=3), ctx: Ctx = Depends(need("venues:write"))):
    try:
        return await run_in_threadpool(_nominatim, q)
    except requests.RequestException:
        raise HTTPException(502, "Service de géolocalisation indisponible")


class RenewIn(BaseModel):
    ticket: str = Field(max_length=4000)


@router.post("/public/invitations/renew")
async def renew_invitation(body: RenewIn, request: Request):
    """Lien d'invitation expiré ou déjà utilisé : renvoie un nouveau lien à l'adresse du membre (jamais affiché ici)."""
    import base64
    import json
    try:
        part = body.ticket.split(".")[1]
        sid = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("sid") or ""
    except Exception:
        sid = ""
    t = await db.team.find_one({"$or": [{"invite_token_id": sid}, {"invite_token_history": sid}], "user_id": None}, {"_id": 0}) if sid.startswith("sit_") else None
    if not t:
        raise HTTPException(404, "Ce lien n'est plus reconnu. Demandez une nouvelle invitation à votre responsable.")
    if (t.get("invited_at") or "") > (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat():
        raise HTTPException(429, "Un lien vient d'être envoyé : consultez votre boîte e-mail, ou réessayez dans 5 minutes.")
    from routes_comms import base_url
    r = await _member_invite(Ctx({"org_id": t["org_id"], "role": t.get("access_role") or DEFAULT_ROLE, "name": t.get("invited_by") or "", "user_id": ""}), t, base_url(request))
    if r["access"]["status"] != "sent":
        raise HTTPException(502, "Le nouveau lien n'a pas pu être envoyé. Demandez une nouvelle invitation à votre responsable.")
    return {"ok": True}
