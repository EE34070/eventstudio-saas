from datetime import datetime, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

import portal_core as po
import providers_core as pc
import tenant_router as tenants
from core import Ctx, audit, db, need, new_id, now_iso
from i18n import clean_lang
from routes_comms import base_url, ensure_token
from routes_files import _serve, file_bytes, read_upload, store_bytes
from routes_main import contact_name, onsite_for
from routes_material import shareable_docs
from security import check_file, sign_file

router = APIRouter(prefix="/api")
A, C, PV = need("portal:any"), need("portal:client"), need("portal:provider")
VISIBLE = ["confirmed", "done", "invoiced", "paid"]
DATE = r"^\d{4}-\d{2}-\d{2}$"


async def nf(ctx: Ctx, request: Request):
    await audit(ctx.org_id, ctx.viewer, "access_denied", request.url.path)
    raise HTTPException(404, "Introuvable")


async def _org(ctx: Ctx) -> dict:
    return await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}) or {}


async def _contact(ctx: Ctx) -> dict:
    return await db.contacts.find_one(ctx.q({"id": ctx.contact_id or "__none__"}), {"_id": 0}) or {}


def _mine(ctx: Ctx) -> dict:
    cid = ctx.contact_id or "__none__"
    return ctx.q({"$or": [{"client_contact_ids": cid}, {"organizer_portal_access": True, "planner_contact_id": cid}]})


# ---------- Commun ----------
@router.get("/portal/me")
async def portal_me(ctx: Ctx = Depends(A)):
    org, c = await _org(ctx), await _contact(ctx)
    if ctx.preview:
        await audit(ctx.org_id, ctx.viewer, "view_as", ctx.member.get("email", ""), ctx.role)
    return {"role": ctx.role, "preview": ctx.preview, "name": ctx.member.get("name"), "first_name": c.get("first_name", ""), "last_name": c.get("last_name", ""), "email": ctx.member.get("email"),
            "phone": c.get("phone", ""), "language": c.get("language") or "fr-FR", "notifications": ctx.member.get("notifications") or {"email": True},
            "terms_required": not ctx.preview and ctx.member.get("terms_version") != po.TERMS_VERSION, "terms_version": po.TERMS_VERSION,
            "org": {"id": org.get("id"), "name": org.get("name", ""), "phone": org.get("phone", ""), "email": org.get("email", "")}}


class TermsIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field("", max_length=80)
    language: str = "fr-FR"
    accept: Literal[True]


@router.post("/portal/terms")
async def accept_terms(body: TermsIn, ctx: Ctx = Depends(A)):
    await db.contacts.update_one(ctx.q({"id": ctx.contact_id}), {"$set": {"first_name": body.first_name.strip(), "last_name": body.last_name.strip()}})
    await db.users.update_one({"user_id": ctx.member["user_id"]}, {"$set": {"terms_accepted_at": now_iso(), "terms_version": po.TERMS_VERSION, "terms_language": clean_lang(body.language),
                                                                          "name": f"{body.first_name} {body.last_name}".strip()}})
    await audit(ctx.org_id, ctx.member, "terms_accepted", po.TERMS_VERSION, clean_lang(body.language))
    return {"ok": True}


class AccountIn(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=80)
    last_name: Optional[str] = Field(None, max_length=80)
    phone: Optional[str] = Field(None, max_length=40)
    language: Optional[Literal["fr-FR", "en-US", "en-GB"]] = None
    notify_email: Optional[bool] = None


@router.patch("/portal/account")
async def patch_account(body: AccountIn, ctx: Ctx = Depends(A)):
    ch = body.model_dump(exclude_none=True, exclude={"notify_email"})
    if ch:
        await db.contacts.update_one(ctx.q({"id": ctx.contact_id}), {"$set": ch})
    if body.notify_email is not None:
        await db.users.update_one({"user_id": ctx.member["user_id"]}, {"$set": {"notifications": {"email": body.notify_email}}})
    return {"ok": True}


@router.post("/portal/account/logout-all")
async def logout_all(ctx: Ctx = Depends(A)):
    n = await po.revoke_sessions(ctx.member["user_id"])
    await audit(ctx.org_id, ctx.member, "sessions_revoked", ctx.member.get("email", ""), "par l'utilisateur")
    return {"revoked": n}


@router.get("/portal/account/export")
async def export_me(ctx: Ctx = Depends(A)):
    c = await _contact(ctx)
    data = {"contact": {k: c.get(k) for k in ("first_name", "last_name", "company", "email", "phone", "address", "city", "language")},
            "account": {k: ctx.member.get(k) for k in ("email", "role", "created_at", "terms_accepted_at", "terms_version", "terms_language", "last_login_at")},
            "messages": await db.portal_messages.find(ctx.q({"from_user_id": ctx.member["user_id"]}), {"_id": 0, "org_id": 0}).to_list(2000)}
    if ctx.role == "client":
        data["events"] = [{"title": e["title"], "start": e.get("start"), "type": e.get("type")} async for e in db.events.find(_mine(ctx), {"_id": 0})]
    await audit(ctx.org_id, ctx.viewer, "export", ctx.member.get("email", ""), "export RGPD")
    return data


@router.post("/portal/account/delete-request")
async def delete_request(ctx: Ctx = Depends(A)):
    if not await db.gdpr_requests.find_one(ctx.q({"user_id": ctx.member["user_id"], "status": "pending"})):
        await ctx.insert("gdpr_requests", {"user_id": ctx.member["user_id"], "contact_id": ctx.contact_id, "email": ctx.member.get("email"), "name": ctx.member.get("name"), "status": "pending"})
        await audit(ctx.org_id, ctx.member, "deletion_requested", ctx.member.get("email", ""))
    return {"ok": True}


@router.post("/portal/files")
async def portal_upload(file: UploadFile = File(...), ctx: Ctx = Depends(A)):
    data, ctype = await read_upload(file)
    if ctype != "application/pdf":
        raise HTTPException(400, "Seuls les PDF sont acceptés")
    return {"ref": await store_bytes(ctx.org_id, data, ctype, "document.pdf", ctx.member["user_id"])}


async def _own_file(ctx: Ctx, ref: str) -> None:
    if not await db.files.find_one(ctx.q({"id": ref[5:], "created_by": ctx.member["user_id"], "is_deleted": False})):
        raise HTTPException(400, "Fichier invalide")


@router.get("/portal/dl/{org_id}/{fid}")
async def signed_download(org_id: str, fid: str, exp: int = 0, sig: str = ""):
    if not check_file(org_id, fid, exp, sig):
        raise HTTPException(403, "Lien expiré")
    tenants.pin_org(org_id)  # signature vérifiée : on peut lire la base de cette société
    return _serve(await file_bytes(org_id, f"file:{fid}"))


@router.get("/public/legal/{org_id}/{page}")
async def legal(org_id: str, page: Literal["privacy", "legal"]):
    org = await db.orgs.find_one({"id": org_id}, {"_id": 0, "name": 1, "portal_legal": 1})
    if not org:
        raise HTTPException(404, "Introuvable")
    pl = org.get("portal_legal") or {}
    return {"org": org.get("name", ""), "fr": pl.get(page) or "", "en": pl.get(f"{page}_en") or ""}


# ---------- Espace client ----------
async def c_event(ctx: Ctx, request: Request, eid: str, module: str = "home", write: bool = False) -> tuple:
    ev = await db.events.find_one({**_mine(ctx), "id": eid}, {"_id": 0})
    org = await _org(ctx)
    state = po.portal_state(ev, org) if ev else "disabled"
    mods = await po.visible_modules(org, ev) if ev and state != "disabled" else {}
    if module not in mods:
        await nf(ctx, request)
    if write and (state != "active" or not mods[module]["editable"] or ctx.contact_id not in (ev.get("client_contact_ids") or [])):
        raise HTTPException(403, "Lecture seule")
    return ev, org, mods, state


@router.get("/portal/client/events")
async def client_events(ctx: Ctx = Depends(C)):
    org = await _org(ctx)
    evs = await db.events.find(_mine(ctx), {"_id": 0, "id": 1, "title": 1, "start": 1, "end": 1, "type": 1, "portal_status": 1}).sort("start", 1).to_list(50)
    return [{"id": e["id"], "title": __import__("routes_titles").ev_title(e, e.get("language") or "fr-FR"), "start": e.get("start"), "type": e.get("type")} for e in evs if po.portal_state(e, org) != "disabled"]


async def _billing(ctx: Ctx, eid: str) -> dict:
    quotes = await db.quotes.find(ctx.q({"event_id": eid, "status": {"$nin": ["brouillon", "remplace"]}}), {"_id": 0}).sort("date", -1).to_list(50)
    invoices = await db.invoices.find(ctx.q({"event_id": eid}), {"_id": 0}).sort("date", 1).to_list(50)
    return {"quotes": [{"id": q["id"], "number": q["number"], "status": q["status"], "date": q.get("date"), "valid_until": q.get("valid_until"), "total_ttc": q.get("total_ttc", 0),
                        "signature": (q.get("signature") or {}).get("status") or "", "url": f"/devis/{await ensure_token('quotes', q)}", "pdf": f"/api/public/quotes/{q['share_token']}/pdf" if q.get("share_token") else ""} for q in quotes],
            "invoices": [{"id": i["id"], "number": i["number"], "kind": i.get("kind"), "status": i["status"], "date": i.get("date"), "due_date": i.get("due_date"), "total_ttc": i.get("total_ttc", 0),
                          "paid_amount": i.get("paid_amount", 0), "balance_due": i.get("balance_due", 0), "pdf": f"/api/public/invoices/{await ensure_token('invoices', i)}/pdf"} for i in invoices]}


@router.get("/portal/client/events/{eid}")
async def client_event(eid: str, request: Request, ctx: Ctx = Depends(C)):
    ev, org, mods, state = await c_event(ctx, request, eid)
    v = await db.venues.find_one(ctx.q({"id": ev.get("venue_id") or "__none__"}), {"_id": 0}) or {}
    deadlines, progress = [], []
    if mods.get("music", {}).get("lock_date"):
        deadlines.append({"kind": "music", "date": mods["music"]["lock_date"]})
    if "billing" in mods:
        b = await _billing(ctx, eid)
        deadlines += [{"kind": "balance", "date": i["due_date"], "amount": i["balance_due"]} for i in b["invoices"] if i["balance_due"] > 0]
        progress = [{"key": "quote_signed", "done": any(q["status"] == "accepte" for q in b["quotes"])},
                    {"key": "deposit_paid", "done": any(i["kind"] == "acompte" and i["status"] == "payee" for i in b["invoices"])},
                    {"key": "balance_paid", "done": any(i["kind"] == "solde" and i["status"] == "payee" for i in b["invoices"])}]
    return {"id": ev["id"], "title": ev["title"], "type": ev.get("type"), "start": ev.get("start"), "end": ev.get("end"), "date_tbc": bool(ev.get("date_tbc")), "guests": ev.get("guests", 0),
            "language": ev.get("language") or "fr-FR", "state": state, "read_only": state != "active" or ctx.contact_id not in (ev.get("client_contact_ids") or []),
            "venue": {k: v.get(k) for k in ("name", "address", "zip", "city", "lat", "lng", "access_instructions")} if v else None,
            "contact": {"name": org.get("name", ""), "phone": org.get("phone", ""), "email": org.get("email", "")}, "modules": list(mods.values()), "deadlines": deadlines, "progress": progress}


async def _client_docs(ctx: Ctx, ev: dict) -> list:
    out = [{"id": f"c:{d['id']}", "title": d["title"], "title_en": d.get("title_en", ""), "type": d.get("type", "autre"), "date": d.get("shared_at"), "ref": d["file_ref"]}
           for d in await db.client_documents.find(ctx.q({"event_id": ev["id"], "visible_to_client": True}), {"_id": 0}).sort("shared_at", -1).to_list(200)]
    out += [{"id": f"p:{d['id']}", "title": d["title"], "title_en": "", "type": "fiche", "date": d.get("created_at"), "ref": d["file_ref"]}
            for d in await shareable_docs(ctx.org_id, [i for q in await db.quotes.find(ctx.q({"event_id": ev["id"], "status": {"$nin": ["brouillon", "remplace"]}}), {"_id": 0, "shared_doc_ids": 1}).to_list(50) for i in q.get("shared_doc_ids") or []])]
    return out


@router.get("/portal/client/events/{eid}/documents")
async def client_documents(eid: str, request: Request, ctx: Ctx = Depends(C)):
    ev, *_ = await c_event(ctx, request, eid, "documents")
    return [{k: v for k, v in d.items() if k != "ref"} for d in await _client_docs(ctx, ev)]


@router.get("/portal/client/events/{eid}/documents/{did}/link")
async def client_document_link(eid: str, did: str, request: Request, ctx: Ctx = Depends(C)):
    ev, *_ = await c_event(ctx, request, eid, "documents")
    d = next((x for x in await _client_docs(ctx, ev) if x["id"] == did), None)
    if not d:
        await nf(ctx, request)
    await audit(ctx.org_id, ctx.viewer, "download", d["title"], ev["title"])
    return {"url": sign_file(ctx.org_id, d["ref"])}


@router.get("/portal/client/events/{eid}/billing")
async def client_billing(eid: str, request: Request, ctx: Ctx = Depends(C)):
    await c_event(ctx, request, eid, "billing")
    return await _billing(ctx, eid)


async def _timeline(ctx: Ctx, eid: str) -> dict:
    t = await db.timelines.find_one(ctx.q({"event_id": eid}), {"_id": 0}) or {}
    return {"items": sorted(t.get("items") or [], key=lambda i: (i.get("order", 0), i.get("time", ""))), "comments": t.get("comments") or []}


class TextIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@router.get("/portal/client/events/{eid}/timeline")
async def client_timeline(eid: str, request: Request, ctx: Ctx = Depends(C)):
    await c_event(ctx, request, eid, "timeline")
    return await _timeline(ctx, eid)


@router.post("/portal/client/events/{eid}/timeline/comments")
async def client_timeline_comment(eid: str, body: TextIn, request: Request, ctx: Ctx = Depends(C)):
    await c_event(ctx, request, eid, "timeline", write=True)
    await db.timelines.update_one(ctx.q({"event_id": eid}), {"$push": {"comments": {"id": new_id(), "by": ctx.member.get("name"), "role": "client", "at": now_iso(), "body": body.body.strip()}},
                                                             "$setOnInsert": {"id": new_id(), "items": [], "created_at": now_iso()}}, upsert=True)
    return await _timeline(ctx, eid)


async def _thread(ctx: Ctx, eid: str, thread: str) -> list:
    return await db.portal_messages.find(ctx.q({"event_id": eid, "thread": thread}), {"_id": 0, "org_id": 0, "from_user_id": 0}).sort("at", 1).to_list(1000)


async def _post(ctx: Ctx, eid: str, thread: str, body: str, title: str) -> None:
    await ctx.insert("portal_messages", {"event_id": eid, "thread": thread, "from_role": ctx.role, "from_name": ctx.member.get("name"), "from_user_id": ctx.member["user_id"], "body": body.strip(), "at": now_iso()})
    org = await _org(ctx)
    acc = await db.channel_accounts.find_one(ctx.q({"channel": "gmail", "status": "connected"}), {"_id": 0})
    if acc:
        import messaging_core as mc
        try:
            await mc.send_mail(acc, org, acc["email"], f"[Portail] {title} — {ctx.member.get('name')}", body.strip())
        except Exception as exc:
            po.logger.error("Message portail non relayé : %s", exc)


@router.get("/portal/client/events/{eid}/messages")
async def client_messages(eid: str, request: Request, ctx: Ctx = Depends(C)):
    await c_event(ctx, request, eid, "messages")
    return await _thread(ctx, eid, "client")


@router.post("/portal/client/events/{eid}/messages")
async def client_message(eid: str, body: TextIn, request: Request, ctx: Ctx = Depends(C)):
    ev, *_ = await c_event(ctx, request, eid, "messages", write=True)
    await _post(ctx, eid, "client", body.body, ev["title"])
    return await _thread(ctx, eid, "client")


# ---------- Portail prestataire ----------
async def _profile(ctx: Ctx, request: Request) -> dict:
    p = await db.provider_profiles.find_one(ctx.q({"contact_id": ctx.contact_id or "__none__"}), {"_id": 0})
    if not p:
        await nf(ctx, request)
    return p


async def _mission(ctx: Ctx, request: Request, mid: str) -> tuple:
    p = await _profile(ctx, request)
    since = (datetime.strptime(po.today(), "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    m = await db.missions.find_one(ctx.q({"id": mid, "provider_id": p["id"], "status": {"$in": VISIBLE}, "date": {"$gte": since}}), {"_id": 0})
    if not m:
        await nf(ctx, request)
    return m, p


def _mission_row(m: dict, lab: dict) -> dict:
    return {**{k: m.get(k) for k in ("id", "date", "start_time", "end_time", "venue_city", "status", "agreed_rate", "agreed_travel_fee", "vat_mode", "vat_rate", "total_ht", "total_ttc",
                                    "presence_confirmed_at", "payment_status")}, "category": lab.get(m["category_key"], m["category_key"]), "has_invoice": bool(m.get("provider_invoice_file"))}


@router.get("/portal/provider/missions")
async def provider_missions(request: Request, ctx: Ctx = Depends(PV)):
    p = await _profile(ctx, request)
    lab = await pc.labels(ctx.org_id)
    since = (datetime.strptime(po.today(), "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    rows = await db.missions.find(ctx.q({"provider_id": p["id"], "status": {"$in": VISIBLE}, "date": {"$gte": since}}), {"_id": 0}).sort("date", 1).to_list(500)
    return {"today": po.today(), "missions": [_mission_row(m, lab) for m in rows]}


@router.get("/portal/provider/missions/{mid}")
async def provider_mission(mid: str, request: Request, ctx: Ctx = Depends(PV)):
    m, p = await _mission(ctx, request, mid)
    lab = await pc.labels(ctx.org_id)
    org = await _org(ctx)
    req = await db.service_requests.find_one(ctx.q({"id": m.get("request_id")}), {"_id": 0}) or {}
    ev = await db.events.find_one(ctx.q({"id": m.get("event_id") or "__none__"}), {"_id": 0}) or {}
    venue = await db.venues.find_one(ctx.q({"id": ev.get("venue_id") or "__none__"}), {"_id": 0}) if ev else None
    if not req:
        v = venue or {}
        req = {"venue_name": v.get("name", ""), "venue_address": v.get("address", ""), "venue_zip": v.get("zip", ""), "venue_city": v.get("city") or m.get("venue_city", ""), "venue_lat": v.get("lat"), "venue_lng": v.get("lng"),
               "access_instructions": v.get("access_instructions", ""), "brief": "\n".join(filter(None, [m.get("brief"), m.get("dress")]))}
    days = int((org.get("portal_settings") or {}).get("onsite_days") or 7)
    since = m.get("onsite_contact_visible_from") or (datetime.strptime(m["date"], "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    onsite = [{k: c.get(k, "") for k in ("name", "role", "phone")} for c in onsite_for(venue, ev.get("onsite_contact_ids"))] if po.today() >= since else []
    items = (await _timeline(ctx, ev["id"]))["items"] if ev else []
    if not m.get("share_full_timeline"):
        items = [i for i in items if m["start_time"] <= (i.get("time") or "") <= m["end_time"]]
    team = []
    if m.get("share_team") and ev:
        async for o in db.missions.find(ctx.q({"event_id": ev["id"], "status": {"$in": VISIBLE}, "id": {"$ne": mid}}), {"_id": 0}):
            op = await db.provider_profiles.find_one(ctx.q({"id": o["provider_id"]}), {"_id": 0, "contact_id": 1}) or {}
            oc = await db.contacts.find_one(ctx.q({"id": op.get("contact_id")}), {"_id": 0, "first_name": 1, "phone": 1}) or {}
            team.append({"first_name": oc.get("first_name", ""), "category": lab.get(o["category_key"], o["category_key"]), "phone": oc.get("phone", "")})
    return {**_mission_row(m, lab), "event_type": req.get("event_type") or ev.get("type", ""), "guest_count": req.get("guest_count") or 0,
            "venue": {"name": req.get("venue_name", ""), "address": req.get("venue_address", ""), "zip": req.get("venue_zip", ""), "city": req.get("venue_city", ""), "lat": req.get("venue_lat"),
                      "lng": req.get("venue_lng"), "access_instructions": req.get("access_instructions", "")}, "brief": req.get("brief", ""), "onsite_contacts": onsite, "onsite_from": since,
            "timeline": items, "team": team, "equipment_needed": [pc.EQUIPMENT.get(k, k) for k in m.get("equipment_needed") or []], "equipment_note": m.get("equipment_note", ""),
            "missing_equipment": [pc.EQUIPMENT.get(k, k) for k in m.get("missing_equipment") or []], "contact": {"name": org.get("name", ""), "phone": org.get("phone", ""), "email": org.get("email", "")},
            "messages": await _thread(ctx, m.get("event_id") or mid, f"mission:{mid}"), "has_music": m["category_key"] == "dj" and bool(ev)}


@router.post("/portal/provider/missions/{mid}/confirm")
async def confirm_presence(mid: str, request: Request, ctx: Ctx = Depends(PV)):
    await _mission(ctx, request, mid)
    await db.missions.update_one(ctx.q({"id": mid}), {"$set": {"presence_confirmed_at": now_iso()}})
    return {"ok": True}


class FileIn(BaseModel):
    file: str = Field(pattern=r"^file:[\w-]+$")
    type: Literal["kbis", "urssaf", "rc_pro", "autre"] = "autre"
    expires_at: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")


@router.post("/portal/provider/missions/{mid}/invoice")
async def provider_invoice(mid: str, body: FileIn, request: Request, ctx: Ctx = Depends(PV)):
    m, _ = await _mission(ctx, request, mid)
    await _own_file(ctx, body.file)
    await db.missions.update_one(ctx.q({"id": mid}), {"$set": {"provider_invoice_file": body.file, "provider_invoice_at": now_iso(), "status": "paid" if m["status"] == "paid" else "invoiced",
                                                               "payment_status": m.get("payment_status") or "pending"}})
    await audit(ctx.org_id, ctx.member, "provider_invoice", m["provider_name"], m["date"])
    return {"ok": True}


@router.post("/portal/provider/missions/{mid}/messages")
async def provider_message(mid: str, body: TextIn, request: Request, ctx: Ctx = Depends(PV)):
    m, _ = await _mission(ctx, request, mid)
    await _post(ctx, m.get("event_id") or mid, f"mission:{mid}", body.body, f"Mission du {m['date']}")
    return await _thread(ctx, m.get("event_id") or mid, f"mission:{mid}")


@router.get("/portal/provider/requests")
async def provider_requests(request: Request, ctx: Ctx = Depends(PV)):
    p = await _profile(ctx, request)
    lab, out = await pc.labels(ctx.org_id), []
    async for r in db.request_recipients.find(ctx.q({"provider_id": p["id"]}), {"_id": 0}).sort("created_at", -1).limit(100):
        req = await db.service_requests.find_one(ctx.q({"id": r["request_id"]}), {"_id": 0})
        if req and req["status"] != "draft":
            out.append({"id": r["id"], "date": req["date"], "start_time": req["start_time"], "end_time": req["end_time"], "city": req.get("venue_city", ""), "category": lab.get(req["category_key"], req["category_key"]),
                        "reply": r.get("reply"), "retained": r.get("retained"), "open": req["status"] in pc.OPEN and req["reply_deadline"] > now_iso(), "deadline": req["reply_deadline"], "url": f"/reponse/{r['token']}"})
    return out


class UnavailIn(BaseModel):
    date: str = Field(pattern=DATE)
    note: str = Field("", max_length=300)


@router.get("/portal/provider/unavailabilities")
async def my_unavailabilities(request: Request, ctx: Ctx = Depends(PV)):
    p = await _profile(ctx, request)
    return await db.provider_unavailabilities.find(ctx.q({"provider_id": p["id"], "date": {"$gte": po.today()}}), {"_id": 0, "org_id": 0}).sort("date", 1).to_list(500)


@router.post("/portal/provider/unavailabilities")
async def add_unavailability(body: UnavailIn, request: Request, ctx: Ctx = Depends(PV)):
    p = await _profile(ctx, request)
    return await ctx.insert("provider_unavailabilities", {"provider_id": p["id"], "date": body.date, "start_time": "", "end_time": "", "note": body.note, "source": "provider"})


@router.delete("/portal/provider/unavailabilities/{uid}")
async def del_unavailability(uid: str, request: Request, ctx: Ctx = Depends(PV)):
    p = await _profile(ctx, request)
    r = await db.provider_unavailabilities.delete_one(ctx.q({"id": uid, "provider_id": p["id"], "source": "provider"}))
    if not r.deleted_count:
        await nf(ctx, request)
    return {"ok": True}


EDITABLE = ["base_rate", "extra_hour_rate", "included_hours", "travel_fee_mode", "travel_fee_amount", "travel_km_included", "vat_mode", "vat_rate", "radius_km", "base_city", "base_zip", "equipment_needed_note"]


@router.get("/portal/provider/profile")
async def my_profile(request: Request, ctx: Ctx = Depends(PV)):
    p = await _profile(ctx, request)
    return {"profile": {k: p.get(k) for k in EDITABLE + ["stage_name", "categories"]},
            "changes": await db.provider_profile_changes.find(ctx.q({"provider_id": p["id"]}), {"_id": 0, "org_id": 0}).sort("created_at", -1).to_list(30)}


class ChangeIn(BaseModel):
    base_rate: Optional[float] = Field(None, ge=0, le=1_000_000)
    extra_hour_rate: Optional[float] = Field(None, ge=0, le=100_000)
    travel_fee_amount: Optional[float] = Field(None, ge=0, le=100_000)
    vat_mode: Optional[Literal["subject", "not_applicable_293B"]] = None
    vat_rate: Optional[float] = Field(None, ge=0, le=30)
    radius_km: Optional[float] = Field(None, ge=0, le=5000)
    base_city: Optional[str] = Field(None, max_length=120)
    equipment_needed_note: Optional[str] = Field(None, max_length=500)


@router.post("/portal/provider/profile/changes")
async def request_change(body: ChangeIn, request: Request, ctx: Ctx = Depends(PV)):
    p = await _profile(ctx, request)
    ch = {k: v for k, v in body.model_dump(exclude_none=True).items() if p.get(k) != v}
    if not ch:
        raise HTTPException(400, "Aucune modification")
    return await ctx.insert("provider_profile_changes", {"provider_id": p["id"], "provider_name": p.get("stage_name") or contact_name(await _contact(ctx)), "changes": ch,
                                                         "previous": {k: p.get(k) for k in ch}, "status": "pending", "reviewed_by": None})


@router.get("/portal/provider/documents")
async def my_documents(request: Request, ctx: Ctx = Depends(PV)):
    p = await _profile(ctx, request)
    return await db.provider_documents.find(ctx.q({"provider_id": p["id"]}), {"_id": 0, "org_id": 0, "file": 0}).sort("created_at", -1).to_list(100)


@router.post("/portal/provider/documents")
async def add_my_document(body: FileIn, request: Request, ctx: Ctx = Depends(PV)):
    p = await _profile(ctx, request)
    await _own_file(ctx, body.file)
    d = await ctx.insert("provider_documents", {"provider_id": p["id"], "provider_name": p.get("stage_name") or ctx.member.get("name"), "type": body.type, "file": body.file,
                                                "filename": f"{body.type}.pdf", "expires_at": body.expires_at, "reminded_at": None, "source": "provider"})
    return {"id": d["id"]}


@router.get("/portal/provider/documents/{did}/link")
async def my_document_link(did: str, request: Request, ctx: Ctx = Depends(PV)):
    p = await _profile(ctx, request)
    d = await db.provider_documents.find_one(ctx.q({"id": did, "provider_id": p["id"]}), {"_id": 0})
    if not d:
        await nf(ctx, request)
    return {"url": sign_file(ctx.org_id, d["file"])}


__all__: List[str] = ["router", "base_url", "Response"]
