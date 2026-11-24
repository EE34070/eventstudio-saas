import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

import portal_core as po
from core import IN_ENV, PORTAL_ROLES, ROLE_LABELS, Ctx, audit, db, effective_role, need, new_id, now_iso
from routes_comms import base_url
from routes_main import contact_name
from routes_portal import EDITABLE, TextIn

router = APIRouter(prefix="/api")
U, E, PM = need("users:manage"), need("events:write"), need("providers:manage")
DATE = r"^(\d{4}-\d{2}-\d{2})?$"


def _status(u: dict | None) -> str:
    return "none" if not u else u.get("status") or "active"


async def _org(ctx: Ctx) -> dict:
    return await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}) or {}


@router.get("/events/{eid}/portal")
async def event_portal(eid: str, ctx: Ctx = Depends(need("events:read"))):
    ev, org = await ctx.get("events", eid, ctx.event_scope()), await _org(ctx)
    ids = list(ev.get("client_contact_ids") or []) + ([ev["planner_contact_id"]] if ev.get("planner_contact_id") else [])
    contacts = {c["id"]: c for c in await ctx.list("contacts", {"id": {"$in": ids}})}
    users = {u["contact_id"]: u for u in await ctx.list("users", {"contact_id": {"$in": ids}, "role": "client"})}
    row = lambda cid, organizer: {"contact_id": cid, "name": contact_name(contacts.get(cid) or {}), "email": (contacts.get(cid) or {}).get("email", ""), "language": (contacts.get(cid) or {}).get("language") or "fr-FR",
                                  "organizer": organizer, "status": _status(users.get(cid)), "user_id": (users.get(cid) or {}).get("user_id"), "last_login_at": (users.get(cid) or {}).get("last_login_at")}  # noqa: E731
    rows, defs = await po.event_modules(org, ev), await po.modules(ctx.org_id)
    t = await db.timelines.find_one(ctx.q({"event_id": eid}), {"_id": 0}) or {}
    missions = await ctx.list("missions", {"event_id": eid}, sort=[("date", 1)])
    return {"state": po.portal_state(ev, org), "portal_status": ev.get("portal_status") or "", "organizer_portal_access": bool(ev.get("organizer_portal_access")),
            "clients": [row(c, False) for c in ev.get("client_contact_ids") or []], "organizer": row(ev["planner_contact_id"], True) if ev.get("planner_contact_id") else None,
            "modules": [{**rows[m["key"]], "label": m["label"], "active": m["active"], "built": m["key"] in po.BUILT} for m in defs if m["key"] in rows and m["client_facing"]],
            "timeline": {"items": t.get("items") or [], "comments": t.get("comments") or []},
            "documents": await ctx.list("client_documents", {"event_id": eid, "deleted_at": None}, sort=[("shared_at", -1)]),
            "messages": await db.portal_messages.find(ctx.q({"event_id": eid}), {"_id": 0, "org_id": 0}).sort("at", 1).to_list(1000),
            "missions": [{k: m.get(k) for k in ("id", "provider_name", "date", "status", "share_full_timeline", "share_team", "presence_confirmed_at", "provider_invoice_file", "payment_status")} for m in missions]}


class InviteIn(BaseModel):
    contact_ids: List[str] = Field(default_factory=list, max_length=20)


@router.post("/events/{eid}/portal/invite")
async def invite_clients(eid: str, body: InviteIn, request: Request, ctx: Ctx = Depends(E)):
    ev, org = await ctx.get("events", eid), await _org(ctx)
    allowed = list(ev.get("client_contact_ids") or []) + ([ev["planner_contact_id"]] if ev.get("organizer_portal_access") and ev.get("planner_contact_id") else [])
    out = []
    for cid in [c for c in (body.contact_ids or ev.get("client_contact_ids") or []) if c in allowed]:
        c = await ctx.get("contacts", cid)
        try:
            out.append({"contact_id": cid, **await po.invite(org, c, "client", ctx.member, base_url(request), ev["title"])})
        except HTTPException as exc:
            out.append({"contact_id": cid, "error": exc.detail})
    return out


class PortalPatch(BaseModel):
    organizer_portal_access: Optional[bool] = None
    portal_status: Optional[Literal["", "read_only", "disabled"]] = None


@router.patch("/events/{eid}/portal")
async def patch_portal(eid: str, body: PortalPatch, ctx: Ctx = Depends(E)):
    ch = body.model_dump(exclude_none=True)
    await ctx.update("events", eid, ch)
    await audit(ctx.org_id, ctx.member, "portal_settings", eid, str(ch))
    return {"ok": True}


class EventModuleIn(BaseModel):
    client_visible: bool
    client_editable: bool = True
    visible_from: str = Field("", pattern=DATE)
    lock_date: str = Field("", pattern=DATE)


@router.put("/events/{eid}/portal/modules/{key}")
async def set_event_module(eid: str, key: str, body: EventModuleIn, request: Request, ctx: Ctx = Depends(E)):
    ev, org = await ctx.get("events", eid), await _org(ctx)
    old = (await po.event_modules(org, ev)).get(key)
    if not old:
        raise HTTPException(404, "Introuvable")
    await db.event_portal_modules.update_one(ctx.q({"event_id": eid, "module_key": key}), {"$set": {**body.model_dump(), "updated_at": now_iso()}})
    await audit(ctx.org_id, ctx.member, "module_toggle", f"{ev['title']} · {key}", "visible" if body.client_visible else "masqué")
    m = next((x for x in await po.modules(ctx.org_id) if x["key"] == key), {})
    if body.client_visible and not old.get("client_visible") and m.get("notify", True) and m.get("active"):
        await po.notify_clients(org, ev, "module_open", {"module": m.get("label", key)}, base_url(request))
    return {"ok": True}


class TimelineItem(BaseModel):
    id: str = ""
    time: str = Field("", pattern=r"^(([01]\d|2[0-3]):[0-5]\d)?$")
    label: str = Field(min_length=1, max_length=200)
    label_en: str = Field("", max_length=200)
    description: str = Field("", max_length=1000)
    description_en: str = Field("", max_length=1000)


class TimelineIn(BaseModel):
    items: List[TimelineItem] = Field(max_length=100)


@router.put("/events/{eid}/timeline")
async def put_timeline(eid: str, body: TimelineIn, ctx: Ctx = Depends(E)):
    await ctx.get("events", eid)
    items = [{**i.model_dump(), "id": i.id or new_id(), "order": n} for n, i in enumerate(body.items)]
    await db.timelines.update_one(ctx.q({"event_id": eid}), {"$set": {"items": items, "updated_at": now_iso()}, "$setOnInsert": {"id": new_id(), "comments": [], "created_at": now_iso()}}, upsert=True)
    return items


class ClientDocIn(BaseModel):
    file_ref: str = Field(pattern=r"^file:[\w-]+$")
    title: str = Field(min_length=1, max_length=200)
    title_en: str = Field("", max_length=200)
    type: Literal["contrat", "devis_signe", "plan", "autre"] = "autre"
    visible_to_client: bool = True


@router.post("/events/{eid}/client-documents")
async def add_client_doc(eid: str, body: ClientDocIn, request: Request, ctx: Ctx = Depends(E)):
    ev = await ctx.get("events", eid)
    if not await db.files.find_one(ctx.q({"id": body.file_ref[5:], "is_deleted": False})):
        raise HTTPException(400, "Fichier invalide")
    d = await ctx.insert("client_documents", {**body.model_dump(), "event_id": eid, "shared_at": now_iso(), "shared_by": ctx.member.get("name")})
    if body.visible_to_client:
        await po.notify_clients(await _org(ctx), ev, "new_document", {"document": body.title}, base_url(request))
    return d


class VisibleIn(BaseModel):
    visible_to_client: bool


@router.patch("/client-documents/{did}")
async def patch_client_doc(did: str, body: VisibleIn, ctx: Ctx = Depends(E)):
    return await ctx.update("client_documents", did, body.model_dump())


@router.delete("/client-documents/{did}")
async def del_client_doc(did: str, ctx: Ctx = Depends(E)):
    await ctx.update("client_documents", did, {"visible_to_client": False, "deleted_at": now_iso()})
    return {"ok": True}


class StaffMsg(TextIn):
    thread: str = Field("client", max_length=60)


@router.post("/events/{eid}/portal/messages")
async def staff_message(eid: str, body: StaffMsg, request: Request, ctx: Ctx = Depends(E)):
    ev = await ctx.get("events", eid)
    await ctx.insert("portal_messages", {"event_id": eid, "thread": body.thread, "from_role": "staff", "from_name": ctx.member.get("name"), "from_user_id": ctx.member["user_id"], "body": body.body.strip(), "at": now_iso()})
    if body.thread == "client":
        await po.notify_clients(await _org(ctx), ev, "new_message", {"message": body.body.strip()}, base_url(request))
    return {"ok": True}


# ---------- Utilisateurs ----------
@router.get("/portal-users")
async def portal_users(ctx: Ctx = Depends(U)):
    people = await db.users.find({"org_id": ctx.org_id, **IN_ENV}, {"_id": 0}).to_list(2000)
    langs = {c["id"]: c.get("language") or "fr-FR" for c in await ctx.list("contacts", {"id": {"$in": [p["contact_id"] for p in people if p.get("contact_id")]}})}
    since = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    denied = await db.audit_logs.count_documents(ctx.q({"action": "access_denied", "at": {"$gte": since}}))
    people = [p for p in people if p.get("status") != "deleted"]
    return {"denied_alert": denied if denied > 20 else 0,
            "users": [{"user_id": p["user_id"], "name": p.get("name"), "email": p.get("email"), "role": effective_role(p.get("role")), "role_label": ROLE_LABELS[effective_role(p.get("role"))],
                       "status": p.get("status") or "active", "last_login_at": p.get("last_login_at"), "two_factor": p.get("two_factor"), "language": langs.get(p.get("contact_id"), "fr-FR"),
                       "portal": p.get("role") in PORTAL_ROLES} for p in people]}


@router.post("/portal-users/{uid}/{action}")
async def portal_user_action(uid: str, action: Literal["resend", "suspend", "reactivate", "revoke", "delete"], request: Request, ctx: Ctx = Depends(U)):
    u = await db.users.find_one(ctx.q({"user_id": uid, "role": {"$in": PORTAL_ROLES}}), {"_id": 0})
    if not u:
        raise HTTPException(404, "Introuvable")
    out = {"ok": True}
    if action == "resend":
        out = await po.invite(await _org(ctx), await ctx.get("contacts", u["contact_id"]), u["role"], ctx.member, base_url(request))
    elif action == "suspend":
        await db.users.update_one({"user_id": uid}, {"$set": {"status": "suspended"}})
        await po.revoke_sessions(uid)
    elif action == "reactivate":
        await db.users.update_one({"user_id": uid}, {"$set": {"status": "active" if u.get("last_login_at") else "invited"}})
    elif action == "revoke":
        out = {"revoked": await po.revoke_sessions(uid)}
    else:
        await po.revoke_sessions(uid)
        await db.users.update_one({"user_id": uid, "org_id": ctx.org_id}, {"$set": {"status": "deleted", "deleted_at": now_iso()}})
    if action != "resend":
        await audit(ctx.org_id, ctx.member, f"access_{action}", u.get("email", ""), u["role"])
    return out


@router.post("/providers/{pid}/invite")
async def invite_provider(pid: str, request: Request, ctx: Ctx = Depends(PM)):
    p = await ctx.get("provider_profiles", pid)
    return await po.invite(await _org(ctx), await ctx.get("contacts", p["contact_id"]), "provider", ctx.member, base_url(request))


# ---------- Modules, réglages, modèles ----------
class ModuleRow(BaseModel):
    key: str
    label: str = Field(min_length=1, max_length=60)
    label_en: str = Field("", max_length=60)
    description: str = Field("", max_length=300)
    description_en: str = Field("", max_length=300)
    active: bool = True
    notify: bool = True


class ModulesIn(BaseModel):
    modules: List[ModuleRow] = Field(max_length=30)
    defaults: Dict[str, Dict[str, Dict[str, object]]] = Field(default_factory=dict)


@router.get("/portal-modules")
async def get_portal_modules(ctx: Ctx = Depends(U)):
    return {"modules": await po.modules(ctx.org_id), "defaults": (await _org(ctx)).get("portal_defaults") or po.DEFAULTS, "built": po.BUILT}


@router.put("/portal-modules")
async def put_portal_modules(body: ModulesIn, ctx: Ctx = Depends(U)):
    await po.modules(ctx.org_id)
    for i, m in enumerate(body.modules):
        await db.portal_modules.update_one(ctx.q({"key": m.key}), {"$set": {**m.model_dump(exclude={"key"}), "active": m.active or m.key == "home", "order": i}})
    if body.defaults:
        clean = {t: {k: {"client_visible": bool(v.get("client_visible")), "lock_offset_days": int(v.get("lock_offset_days") or 0)} for k, v in ks.items()} for t, ks in body.defaults.items()}
        await db.orgs.update_one({"id": ctx.org_id}, {"$set": {"portal_defaults": clean}})
    await audit(ctx.org_id, ctx.member, "modules_updated")
    return await po.modules(ctx.org_id)


class SettingsIn(BaseModel):
    read_only_days: int = Field(90, ge=0, le=3650)
    disable_days: int = Field(365, ge=30, le=3650)
    onsite_days: int = Field(7, ge=0, le=365)
    privacy: str = Field("", max_length=40000)
    privacy_en: str = Field("", max_length=40000)
    legal: str = Field("", max_length=40000)
    legal_en: str = Field("", max_length=40000)


@router.get("/portal-settings")
async def get_settings(ctx: Ctx = Depends(U)):
    org = await _org(ctx)
    return {**SettingsIn().model_dump(), **(org.get("portal_settings") or {}), **(org.get("portal_legal") or {}), "terms_version": po.TERMS_VERSION, "org_id": ctx.org_id}


@router.put("/portal-settings")
async def put_settings(body: SettingsIn, ctx: Ctx = Depends(U)):
    d = body.model_dump()
    await db.orgs.update_one({"id": ctx.org_id}, {"$set": {"portal_settings": {k: d[k] for k in ("read_only_days", "disable_days", "onsite_days")},
                                                         "portal_legal": {k: d[k] for k in ("privacy", "privacy_en", "legal", "legal_en")}}})
    return {"ok": True}


class TemplateIn(BaseModel):
    key: str
    language: Literal["fr", "en"]
    subject: str = Field(min_length=1, max_length=200)
    body_html: str = Field(min_length=1, max_length=8000)


@router.get("/email-templates")
async def list_email_templates(ctx: Ctx = Depends(U)):
    saved = {(r["key"], r["language"]): r for r in await ctx.list("email_templates")}
    return {"variables": po.VARIABLES, "templates": [{"key": k, "language": lg, "subject": (saved.get((k, lg)) or {}).get("subject") or v[lg][0], "body_html": (saved.get((k, lg)) or {}).get("body_html") or v[lg][1],
                                                     "custom": (k, lg) in saved} for k, v in po.TEMPLATES.items() for lg in ("fr", "en")]}


@router.put("/email-templates")
async def save_email_template(body: TemplateIn, ctx: Ctx = Depends(U)):
    if body.key not in po.TEMPLATES:
        raise HTTPException(404, "Introuvable")
    await db.email_templates.update_one(ctx.q({"key": body.key, "language": body.language}), {"$set": {"subject": body.subject, "body_html": body.body_html, "variables": po.VARIABLES, "updated_at": now_iso()},
                                                                                             "$setOnInsert": {"id": new_id(), "created_at": now_iso()}}, upsert=True)
    return {"ok": True}


# ---------- Journal, validations, RGPD ----------
@router.get("/audit-logs")
async def audit_logs(ctx: Ctx = Depends(U), action: str = "", q: str = "", format: str = ""):
    f: dict = {}
    if action:
        f["action"] = action
    if q:
        import re
        f["$or"] = [{k: {"$regex": re.escape(q[:60]), "$options": "i"}} for k in ("actor_name", "target", "detail")]
    rows = await db.audit_logs.find(ctx.q(f), {"_id": 0, "org_id": 0, "at_dt": 0}).sort("at", -1).to_list(5000 if format == "csv" else 300)
    if format != "csv":
        return {"rows": rows, "actions": sorted(await db.audit_logs.distinct("action", ctx.q()))}
    await audit(ctx.org_id, ctx.member, "export", "journal d'audit")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Date", "Acteur", "Rôle", "Action", "Cible", "Détail"])
    for r in rows:
        w.writerow([r["at"], r["actor_name"], r["actor_role"], r["action"], r["target"], r["detail"]])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="journal.csv"'})


@router.get("/portal-requests")
async def portal_requests(ctx: Ctx = Depends(U)):
    return {"changes": await ctx.list("provider_profile_changes", sort=[("created_at", -1)], limit=100), "gdpr": await ctx.list("gdpr_requests", sort=[("created_at", -1)], limit=100)}


@router.post("/profile-changes/{cid}/{decision}")
async def review_change(cid: str, decision: Literal["approve", "reject"], ctx: Ctx = Depends(PM)):
    ch = await ctx.get("provider_profile_changes", cid, {"status": "pending"})
    if decision == "approve":
        await db.provider_profiles.update_one(ctx.q({"id": ch["provider_id"]}), {"$set": {k: v for k, v in ch["changes"].items() if k in EDITABLE}})
    await ctx.update("provider_profile_changes", cid, {"status": "approved" if decision == "approve" else "rejected", "reviewed_by": ctx.member.get("name")})
    await audit(ctx.org_id, ctx.member, f"profile_change_{decision}", ch.get("provider_name", ""))
    return {"ok": True}


@router.post("/gdpr-requests/{rid}/anonymize")
async def anonymize(rid: str, ctx: Ctx = Depends(U)):
    r = await ctx.get("gdpr_requests", rid, {"status": "pending"})
    await po.revoke_sessions(r["user_id"])
    await db.contacts.update_one(ctx.q({"id": r["contact_id"]}), {"$set": {"first_name": "Anonymisé", "last_name": "", "company": "", "email": "", "phone": "", "address": "", "city": "",
                                                                         "instagram_handle": "", "notes": "", "interactions": [], "anonymized_at": now_iso()}})
    await db.portal_messages.update_many(ctx.q({"from_user_id": r["user_id"]}), {"$set": {"from_name": "Anonymisé", "body": "(supprimé)"}})
    await db.users.update_one({"user_id": r["user_id"], "org_id": ctx.org_id}, {"$set": {"status": "deleted", "deleted_at": now_iso(), "email": "", "name": "Anonymisé"}})
    try:
        await po.clerk("DELETE", f"/users/{r['user_id']}")
    except HTTPException:
        pass
    await ctx.update("gdpr_requests", rid, {"status": "done", "email": "", "name": "Anonymisé", "done_by": ctx.member.get("name")})
    await audit(ctx.org_id, ctx.member, "anonymized", rid, "pièces comptables conservées")
    return {"ok": True}


# ---------- RGPD : export et effacement d'un contact ----------
@router.get("/contacts/{cid}/gdpr-export")
async def contact_gdpr_export(cid: str, ctx: Ctx = Depends(U)):
    c = await ctx.get("contacts", cid)
    evs = await ctx.list("events", {"$or": [{"client_id": cid}, {"client_contact_ids": cid}, {"planner_contact_id": cid}]})
    ids = [e["id"] for e in evs]
    docs = {k: [{f: d.get(f) for f in ("number", "date", "status", "total_ttc")} for d in await ctx.list(k, {"event_id": {"$in": ids}})] for k in ("quotes", "invoices")}
    await audit(ctx.org_id, ctx.member, "gdpr_export", cid)
    return {"contact": c, "events": [{f: e.get(f) for f in ("code", "title", "start", "end", "status")} for e in evs], **docs,
            "portal_messages": await db.portal_messages.find(ctx.q({"event_id": {"$in": ids}, "from_contact_id": cid}), {"_id": 0, "org_id": 0}).to_list(2000)}


@router.post("/contacts/{cid}/gdpr-anonymize")
async def contact_gdpr_anonymize(cid: str, ctx: Ctx = Depends(U)):
    await ctx.get("contacts", cid)
    for u in await ctx.list("users", {"contact_id": cid}):
        await po.revoke_sessions(u["user_id"])
        await db.users.update_one({"user_id": u["user_id"], "org_id": ctx.org_id}, {"$set": {"status": "deleted", "deleted_at": now_iso(), "email": "", "name": "Anonymisé"}})
        await db.portal_messages.update_many(ctx.q({"from_user_id": u["user_id"]}), {"$set": {"from_name": "Anonymisé", "body": "(supprimé)"}})
    await ctx.update("contacts", cid, {"first_name": "Anonymisé", "last_name": "", "company": "", "email": "", "phone": "", "address": "", "city": "", "instagram_handle": "", "notes": "",
                                       "interactions": [], "siret": "", "vat_number": "", "anonymized_at": now_iso()})
    await audit(ctx.org_id, ctx.member, "anonymized", cid, "contact ; pièces comptables conservées")
    return {"ok": True}
