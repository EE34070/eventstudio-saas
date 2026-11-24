import tenant_router as tenants
from functools import partial
import base64
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError
from starlette.concurrency import run_in_threadpool

import messaging_core as mc
from core import Ctx, db, need, new_id, now_iso
from routes_billing import cron_guard
from routes_comms import EMAIL_RE, HOST_RE, _recent
from routes_main import contact_name
from routes_ops import EventIn, create_event

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)
READ, WRITE = need("messages:read"), need("messages:write")


def base_url(request: Request) -> str:
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip().lower()
    if not HOST_RE.match(host):
        raise HTTPException(400, "Hôte invalide")
    return f"https://{host}"


async def _account(org_id: str) -> dict | None:
    return await db.channel_accounts.find_one({"org_id": org_id, "channel": "gmail"}, {"_id": 0})


async def _live_account(ctx: Ctx, conv: dict | None = None) -> dict:
    acc = await _account(ctx.org_id)
    if not acc or acc["status"] != "connected":
        raise HTTPException(409, "La boîte Gmail n'est pas connectée : reconnectez-la dans les réglages de la messagerie")
    if conv and conv["account_id"] != acc["id"]:
        raise HTTPException(409, "Cette conversation appartient à une boîte qui n'est plus connectée")
    return acc


async def _gmail(acc: dict, method: str, path: str, **kw) -> dict:
    try:
        return await mc.gmail(acc, method, path, **kw)
    except mc.GmailAuthError:
        raise HTTPException(409, "Autorisation Google expirée : reconnectez la boîte Gmail")
    except httpx.HTTPError as exc:
        logger.error("Gmail %s %s failed: %s", method, path, getattr(getattr(exc, "response", None), "text", exc))
        raise HTTPException(502, f"Gmail a refusé la demande : {mc.explain(exc)}")


# ---------- Connexion de la boîte ----------
@router.get("/messaging/status")
async def status(request: Request, ctx: Ctx = Depends(READ)):
    acc = await _account(ctx.org_id)
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "messaging": 1})
    live = ctx.q({"deleted_at": None})
    return {"configured": {"google": mc.google_ready(), "pubsub": bool(os.environ.get("GMAIL_PUBSUB_TOPIC") and os.environ.get("PUBSUB_PUSH_SA_EMAIL")), "ai": mc.ai_ready()},
            "account": {k: acc.get(k) for k in ("id", "email", "status", "last_error", "last_sync_at", "import", "watch_expiration", "watch_error")} if acc else None,
            "progress": await mc.progress(acc) if acc else None, "settings": mc.settings_of(org), "categories": mc.CATEGORIES, "trash_days": mc.TRASH_DAYS, "import_days": ((acc or {}).get("import") or {}).get("days") or mc.IMPORT_DAYS,
            "full_import": bool(((acc or {}).get("import") or {}).get("days")), "gmail_categories": mc.GCAT_FR,
            "labels": await db.mail_labels.find(ctx.q({"account_id": acc["id"], "deleted_at": None}), {"_id": 0, "org_id": 0}).sort("name", 1).to_list(1000) if acc else [],
            "spam": await db.conversations.count_documents({**live, "is_spam": True}),
            "unread": await db.conversations.count_documents({**live, "box": "inbox", "unread": True}),
            "trash": await db.conversations.count_documents(ctx.q({"deleted_at": {"$ne": None}})),
            "purgeable": await db.conversations.count_documents(mc.expired(ctx.org_id)),
            "redirect_uri": os.environ.get("GOOGLE_REDIRECT_URI") or f"{base_url(request)}/api/auth/google/callback"}


def _return_to(request: Request, origin: str) -> str:
    origin = origin.rstrip("/")
    allowed = [o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
    if origin in allowed or ("*" in allowed and origin == base_url(request)):
        return origin
    raise HTTPException(400, "Origine non autorisée")


@router.get("/messaging/gmail/connect")
async def gmail_connect(request: Request, return_to: str, ctx: Ctx = Depends(need("org:write"))):
    if not mc.google_ready():
        raise HTTPException(503, "La connexion Gmail n'est pas configurée (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET manquants)")
    redirect = os.environ.get("GOOGLE_REDIRECT_URI") or f"{base_url(request)}/api/auth/google/callback"
    state = secrets.token_urlsafe(32)
    await db.oauth_states.insert_one({"_id": state, "org_id": ctx.org_id, "by": ctx.member.get("name"), "return_to": _return_to(request, return_to),
                                      "redirect_uri": redirect, "at": now_iso()})
    return {"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"], "redirect_uri": redirect, "response_type": "code", "scope": mc.SCOPES,
        "access_type": "offline", "prompt": "consent", "include_granted_scopes": "false", "state": state}), "redirect_uri": redirect}


@router.get("/auth/google/callback")
async def google_callback(bg: BackgroundTasks, state: str = "", code: str = "", error: str = ""):
    st = await db.oauth_states.find_one_and_delete({"_id": state}) if state else None
    if not st or not _recent(st["at"], 600):
        raise HTTPException(400, "Lien de connexion expiré : recommencez depuis la messagerie")
    tenants.pin_org(st["org_id"])
    back = st["return_to"] + "/messagerie?gmail="
    if error or not code:
        return RedirectResponse(back + "refus")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(mc.TOKEN_URL, data={"code": code, "client_id": os.environ["GOOGLE_CLIENT_ID"], "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                                             "redirect_uri": st["redirect_uri"], "grant_type": "authorization_code"})
        if r.is_error:
            logger.error("Google token exchange failed: %s %s", r.status_code, r.text[:300])
            return RedirectResponse(back + "erreur")
        tok = r.json()
        if not tok.get("refresh_token") or "gmail.modify" not in tok.get("scope", ""):
            return RedirectResponse(back + "droits")
        prof = await c.get(mc.GMAIL + "/profile", headers={"Authorization": f"Bearer {tok['access_token']}"})
    if prof.is_error:
        logger.error("Gmail profile failed: %s %s", prof.status_code, prof.text[:300])
        return RedirectResponse(back + "erreur")
    email = prof.json()["emailAddress"].lower()
    if await tenants.org_of("channel_accounts", {"email": email, "status": "connected"}, exclude=st["org_id"]):
        return RedirectResponse(back + "deja")
    old = await _account(st["org_id"])
    aid = old["id"] if old and old.get("email") == email else new_id()
    await db.channel_accounts.update_one({"org_id": st["org_id"], "channel": "gmail"}, {"$set": {
        "id": aid, "email": email, "refresh_token": mc.seal(tok["refresh_token"]), "status": "connected", "last_error": None, "watch_error": None,
        "watch_expiration": 0, "connected_by": st["by"], "connected_at": now_iso(), "import": {"status": "running", "listed": False}},
        "$setOnInsert": {"created_at": now_iso()}}, upsert=True)
    bg.add_task(mc.sync_account, aid, True)
    return RedirectResponse(back + "ok")


@router.delete("/messaging/account")
async def disconnect(ctx: Ctx = Depends(need("org:write"))):
    acc = await _account(ctx.org_id)
    if not acc:
        raise HTTPException(404, "Aucune boîte connectée")
    if acc["status"] == "connected":
        try:
            await mc.gmail(acc, "POST", "/stop")
        except Exception as exc:
            logger.warning("Gmail stop failed: %s", exc)
    await db.channel_accounts.update_one(ctx.q({"id": acc["id"]}), {"$set": {"status": "disconnected", "watch_expiration": 0}, "$unset": {"refresh_token": ""}})
    return {"ok": True}


@router.post("/messaging/sync")
async def manual_sync(bg: BackgroundTasks, ctx: Ctx = Depends(READ)):
    acc = await _live_account(ctx)
    bg.add_task(mc.sync_account, acc["id"])
    return {"ok": True}


class SettingsIn(BaseModel):
    auto_classify: bool = True
    signature: str = Field("", max_length=2000)
    retention_months: int = Field(0, ge=0, le=120)


@router.put("/messaging/settings")
async def save_settings(body: SettingsIn, ctx: Ctx = Depends(need("org:write"))):
    await db.orgs.update_one({"id": ctx.org_id}, {"$set": {"messaging": body.model_dump()}})
    return body.model_dump()


# ---------- Conversations ----------
async def _decorate(ctx: Ctx, rows: list) -> list:
    cs = {c["id"]: c for c in await ctx.list("contacts", {"id": {"$in": [r["contact_id"] for r in rows if r.get("contact_id")]}})}
    es = {e["id"]: e for e in await ctx.list("events", {"id": {"$in": [r["event_id"] for r in rows if r.get("event_id")]}, **ctx.event_scope()})}
    for r in rows:
        c, e = cs.get(r.get("contact_id")), es.get(r.get("event_id"))
        r["contact_name"] = contact_name(c) if c else None
        r["event_title"] = e["title"] if e else None
        if r.get("deleted_at"):
            r["purge_at"] = (datetime.fromisoformat(r["deleted_at"]) + timedelta(days=mc.TRASH_DAYS)).isoformat()
    return rows


@router.get("/messaging/conversations")
async def list_conversations(ctx: Ctx = Depends(READ), box: str = "inbox", q: str = "", category: str = "", unread: bool = False,
                             contact_id: str = "", event_id: str = "", skip: int = 0, limit: int = 50, gcat: str = "", label_id: str = "", unlinked: bool = False):
    f: dict = {"deleted_at": {"$ne": None}} if box == "trash" else {"deleted_at": None, "last_message_at": {"$exists": True}}
    ands = []
    if box in ("inbox", "archived", "spam"):
        f["box"] = box
    elif box == "sent":
        ands.append({"$or": [{"has_sent": True}, {"box": "sent"}]})
    elif box != "trash":
        f["is_spam"] = {"$ne": True}
        if box == "unread":
            f["unread"] = True
        if box == "starred":
            f["is_starred"] = True
    if gcat in mc.GCAT_FR:
        f["gmail_category"] = {"$in": ["primary", None]} if gcat == "primary" else gcat
    if unlinked:
        f["contact_id"] = None
    words = []
    for w in q.split():
        k, _, v = w.partition(":")
        if k == "from" and v:
            rx = {"$regex": re.escape(v), "$options": "i"}
            ands.append({"$or": [{"counterpart.email": rx}, {"counterpart.name": rx}]})
        elif k == "label" and v:
            ids = [x["gmail_id"] async for x in db.mail_labels.find(ctx.q({"deleted_at": None, "name": {"$regex": re.escape(v).replace("_", "[_ ]"), "$options": "i"}}), {"_id": 0, "gmail_id": 1})]
            f["label_ids"] = {"$in": ids}
        elif w == "has:attachment":
            f["has_attachments"] = True
        else:
            words.append(w)
    q = " ".join(words)
    if label_id:
        f["label_ids"] = label_id
    if ands:
        f["$and"] = ands
    if category:
        f["category"] = category
    if unread:
        f["unread"] = True
    if contact_id:
        f["contact_id"] = contact_id
    if event_id:
        f["event_id"] = event_id
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        f.setdefault("$and", []).append({"$or": [{"subject": rx}, {"snippet": rx}, {"counterpart.name": rx}, {"counterpart.email": rx}]})
    rows = await db.conversations.find(ctx.q(f), {"_id": 0}).sort("last_message_at", -1).skip(max(skip, 0)).limit(min(max(limit, 1), 100)).to_list(100)
    return await _decorate(ctx, rows)


@router.get("/messaging/conversations/{cid}")
async def get_conversation(cid: str, ctx: Ctx = Depends(READ)):
    conv = (await _decorate(ctx, [await ctx.get("conversations", cid)]))[0]
    scope = ctx.q({"conversation_id": cid})
    msgs = await db.messages.find({**scope, "deleted_at": None}, {"_id": 0, "org_id": 0}).sort("sent_at", 1).to_list(300)
    for m in msgs:
        m["unread"] = "UNREAD" in m.get("label_ids", [])
    conv["messages"] = msgs
    conv["notes"] = await db.internal_notes.find(scope, {"_id": 0, "org_id": 0}).sort("created_at", 1).to_list(300)
    c = await db.contacts.find_one(ctx.q({"id": conv.get("contact_id")}), {"_id": 0}) if conv.get("contact_id") else None
    conv["contact"] = {"id": c["id"], "display_name": contact_name(c), "email": c.get("email"), "phone": c.get("phone"), "status": c.get("status")} if c else None
    ev_f = {"id": 1, "code": 1, "title": 1, "start": 1, "status": 1, "_id": 0}
    conv["event"] = await db.events.find_one(ctx.q({"id": conv.get("event_id"), **ctx.event_scope()}), ev_f) if conv.get("event_id") else None
    conv["contact_events"] = await db.events.find(ctx.q({"$and": [{"$or": [{"client_id": c["id"]}, {"client_contact_ids": c["id"]}, {"planner_contact_id": c["id"]}]}], **ctx.event_scope()}), ev_f).sort("start", -1).to_list(30) if c else []
    acc = await _account(ctx.org_id)
    conv["can_reply"] = bool(acc and acc["status"] == "connected" and acc["id"] == conv["account_id"] and not conv.get("deleted_at"))
    return conv


async def _set_labels(ctx: Ctx, conv: dict, add: list, remove: list) -> None:
    acc = await _account(ctx.org_id)
    if acc and acc["status"] == "connected" and acc["id"] == conv["account_id"]:
        await _gmail(acc, "POST", f"/threads/{conv['thread_id']}/modify", json={"addLabelIds": add, "removeLabelIds": remove})
    f = ctx.q({"conversation_id": conv["id"], "deleted_at": None})
    if add:
        await db.messages.update_many(f, {"$addToSet": {"label_ids": {"$each": add}}})
    if remove:
        await db.messages.update_many(f, {"$pull": {"label_ids": {"$in": remove}}})
    await mc.refresh_conv(conv["id"])


class ConvPatch(BaseModel):
    unread: Optional[bool] = None
    archived: Optional[bool] = None
    starred: Optional[bool] = None
    spam: Optional[bool] = None
    contact_id: Optional[str] = None
    event_id: Optional[str] = None
    category: Optional[str] = None


@router.patch("/messaging/conversations/{cid}")
async def patch_conversation(cid: str, body: ConvPatch, ctx: Ctx = Depends(WRITE)):
    conv = await ctx.get("conversations", cid)
    upd = {}
    if body.contact_id is not None:
        upd["contact_id"] = (await ctx.get("contacts", body.contact_id))["id"] if body.contact_id else None
    if body.event_id is not None:
        upd["event_id"] = (await ctx.get("events", body.event_id, ctx.event_scope()))["id"] if body.event_id else None
    if body.category is not None:
        if body.category not in mc.CATEGORIES:
            raise HTTPException(400, "Catégorie inconnue")
        upd.update(category=body.category, category_manual=True)
    if upd:
        await db.conversations.update_one(ctx.q({"id": cid}), {"$set": upd})
    if body.unread is not None:
        await _set_labels(ctx, conv, ["UNREAD"] if body.unread else [], [] if body.unread else ["UNREAD"])
    if body.archived is not None:
        await _set_labels(ctx, conv, [] if body.archived else ["INBOX"], ["INBOX"] if body.archived else [])
    if body.starred is not None:
        await _set_labels(ctx, conv, ["STARRED"] if body.starred else [], [] if body.starred else ["STARRED"])
    if body.spam is not None:
        await _set_labels(ctx, conv, ["SPAM"] if body.spam else ["INBOX"], ["INBOX"] if body.spam else ["SPAM"])
    return await get_conversation(cid, ctx)


async def _gmail_trash(ctx: Ctx, conv: dict, verb: str) -> None:
    acc = await _account(ctx.org_id)
    if acc and acc["status"] == "connected" and acc["id"] == conv["account_id"]:
        await _gmail(acc, "POST", f"/threads/{conv['thread_id']}/{verb}")


ACTIONS = {"read": ([], ["UNREAD"]), "unread": (["UNREAD"], []), "archive": ([], ["INBOX"]), "inbox": (["INBOX"], []), "star": (["STARRED"], []), "unstar": ([], ["STARRED"]),
           "spam": (["SPAM"], ["INBOX"]), "notspam": (["INBOX"], ["SPAM"])}


class BulkIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)
    action: str = ""
    add_label_ids: list[str] = Field([], max_length=20)
    remove_label_ids: list[str] = Field([], max_length=20)
    archive: bool = False


@router.post("/messaging/conversations/bulk")
async def bulk(body: BulkIn, ctx: Ctx = Depends(WRITE)):
    if body.action and body.action not in {*ACTIONS, "trash"}:
        raise HTTPException(400, "Action inconnue")
    wanted = set(body.add_label_ids) | set(body.remove_label_ids)
    if wanted and await db.mail_labels.count_documents(ctx.q({"deleted_at": None, "gmail_id": {"$in": list(wanted)}})) != len(wanted):
        raise HTTPException(400, "Libellé inconnu")
    convs = await ctx.list("conversations", {"id": {"$in": body.ids}, "deleted_at": None})
    for conv in convs:
        if body.action == "trash":
            await _gmail_trash(ctx, conv, "trash")
            await db.conversations.update_one(ctx.q({"id": conv["id"]}), {"$set": {"deleted_at": now_iso(), "deleted_reason": "user", "deleted_by": ctx.member.get("name")}})
            continue
        add, rem = ACTIONS.get(body.action, ([], []))
        add, rem = [*add, *body.add_label_ids], [*rem, *body.remove_label_ids, *(["INBOX"] if body.archive else [])]
        if add or rem:
            await _set_labels(ctx, conv, add, rem)
    return {"updated": len(convs)}


# ---------- Libellés Gmail ----------
class LabelIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


async def _labels(ctx: Ctx, acc: dict) -> list:
    try:
        return [{k: v for k, v in x.items() if k != "org_id"} for x in await mc.sync_labels(acc)]
    except mc.GmailAuthError:
        raise HTTPException(409, "Autorisation Google expirée : reconnectez la boîte Gmail")
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Gmail a refusé la demande : {mc.explain(exc)}")


def _label_name(body: LabelIn) -> str:
    name = "/".join(p.strip() for p in body.name.split("/") if p.strip())
    if not name or name.upper() in {"INBOX", "SENT", "SPAM", "TRASH", "UNREAD", "STARRED", "DRAFT", "IMPORTANT"}:
        raise HTTPException(400, "Nom de libellé invalide ou réservé par Gmail")
    return name


async def _label_call(acc: dict, method: str, path: str, **kw) -> dict:
    try:
        return await mc.gmail(acc, method, path, **kw)
    except mc.GmailAuthError:
        raise HTTPException(409, "Autorisation Google expirée : reconnectez la boîte Gmail")
    except mc.GmailError as exc:
        raise HTTPException(409 if exc.status == 409 else 404 if exc.status == 404 else 502, "Un libellé porte déjà ce nom" if exc.status == 409 else "Libellé introuvable dans Gmail" if exc.status == 404 else f"Gmail a refusé la demande : {mc.explain(exc)}")
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Gmail a refusé la demande : {mc.explain(exc)}")


@router.get("/messaging/labels")
async def list_labels(ctx: Ctx = Depends(READ)):
    return await _labels(ctx, await _live_account(ctx))


@router.post("/messaging/labels")
async def create_label(body: LabelIn, ctx: Ctx = Depends(WRITE)):
    acc = await _live_account(ctx)
    await _label_call(acc, "POST", "/labels", json={"name": _label_name(body), "labelListVisibility": "labelShow", "messageListVisibility": "show"})
    return await _labels(ctx, acc)


@router.put("/messaging/labels/{lid}")
async def rename_label(lid: str, body: LabelIn, ctx: Ctx = Depends(WRITE)):
    acc = await _live_account(ctx)
    lab = await ctx.get("mail_labels", lid, {"deleted_at": None})
    await _label_call(acc, "PATCH", f"/labels/{lab['gmail_id']}", json={"name": _label_name(body)})
    return await _labels(ctx, acc)


@router.delete("/messaging/labels/{lid}")
async def delete_label(lid: str, ctx: Ctx = Depends(need("org:write"))):
    acc = await _live_account(ctx)
    lab = await ctx.get("mail_labels", lid, {"deleted_at": None})
    await _label_call(acc, "DELETE", f"/labels/{lab['gmail_id']}")
    await db.messages.update_many(ctx.q({"label_ids": lab["gmail_id"]}), {"$pull": {"label_ids": lab["gmail_id"]}})
    return await _labels(ctx, acc)


@router.post("/messaging/import-full")
async def import_full(bg: BackgroundTasks, ctx: Ctx = Depends(need("org:write"))):
    acc = await _live_account(ctx)
    if (acc.get("import") or {}).get("status") == "running":
        raise HTTPException(409, "Un import est déjà en cours")
    await db.channel_accounts.update_one(ctx.q({"id": acc["id"]}), {"$set": {"import": {"status": "running", "listed": False, "days": mc.FULL_DAYS, "started_at": now_iso(), "started_by": ctx.member.get("name")}}})
    bg.add_task(mc.sync_account, acc["id"])
    return {"ok": True, "days": mc.FULL_DAYS}


@router.delete("/messaging/conversations/{cid}")
async def trash_conversation(cid: str, ctx: Ctx = Depends(WRITE)):
    conv = await ctx.get("conversations", cid)
    if not conv.get("deleted_at"):
        await _gmail_trash(ctx, conv, "trash")
        await db.conversations.update_one(ctx.q({"id": cid}), {"$set": {"deleted_at": now_iso(), "deleted_reason": "user", "deleted_by": ctx.member.get("name")}})
    return {"ok": True, "trash_days": mc.TRASH_DAYS}


@router.post("/messaging/conversations/{cid}/restore")
async def restore_conversation(cid: str, ctx: Ctx = Depends(WRITE)):
    conv = await ctx.get("conversations", cid)
    await _gmail_trash(ctx, conv, "untrash")
    await db.messages.update_many(ctx.q({"conversation_id": cid}), {"$set": {"deleted_at": None}, "$pull": {"label_ids": "TRASH"}})
    await db.conversations.update_one(ctx.q({"id": cid}), {"$set": {"deleted_at": None, "deleted_reason": None}})
    await mc.refresh_conv(cid)
    return {"ok": True}


@router.post("/messaging/trash/purge")
async def purge(ctx: Ctx = Depends(need("org:write"))):
    return {"deleted": await mc.purge_trash(ctx.org_id)}


# ---------- Envoi ----------
class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    to: str = ""


@router.post("/messaging/conversations/{cid}/reply")
async def reply(cid: str, body: ReplyIn, ctx: Ctx = Depends(WRITE)):
    conv = await ctx.get("conversations", cid)
    if conv.get("deleted_at"):
        raise HTTPException(400, "Restaurez la conversation avant de répondre")
    acc = await _live_account(ctx, conv)
    last = await db.messages.find(ctx.q({"conversation_id": cid, "deleted_at": None}), {"_id": 0}).sort("sent_at", -1).to_list(30)
    if not last:
        raise HTTPException(400, "Conversation vide")
    inbound = next((m for m in last if m["direction"] == "in"), None)
    to = body.to.strip() or (inbound and (inbound.get("reply_to") or inbound["from"]["email"])) or (last[0]["to"] or [""])[0]
    if not EMAIL_RE.match(to or ""):
        raise HTTPException(400, "Adresse du destinataire invalide")
    subject = conv["subject"] if conv["subject"].lower().startswith("re:") else f"Re: {conv['subject']}"
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    try:
        await mc.send_mail(acc, org, to, subject, body.text, reply={**last[0], "thread_id": conv["thread_id"]})
    except mc.GmailAuthError:
        raise HTTPException(409, "Autorisation Google expirée : reconnectez la boîte Gmail")
    except httpx.HTTPError as exc:
        logger.error("Gmail send failed: %s", getattr(getattr(exc, "response", None), "text", exc))
        raise HTTPException(502, "Gmail a refusé l'envoi, réessayez")
    return await get_conversation(cid, ctx)


class SendIn(BaseModel):
    to: str
    subject: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=50_000)
    contact_id: str = ""
    event_id: str = ""


@router.post("/messaging/send")
async def send_new(body: SendIn, ctx: Ctx = Depends(WRITE)):
    if not EMAIL_RE.match(body.to.strip()):
        raise HTTPException(400, "Adresse du destinataire invalide")
    link = {}
    if body.contact_id:
        link["contact_id"] = (await ctx.get("contacts", body.contact_id))["id"]
    if body.event_id:
        link["event_id"] = (await ctx.get("events", body.event_id, ctx.event_scope()))["id"]
    acc = await _live_account(ctx)
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    try:
        cid = await mc.send_mail(acc, org, body.to.strip(), body.subject, body.text)
    except mc.GmailAuthError:
        raise HTTPException(409, "Autorisation Google expirée : reconnectez la boîte Gmail")
    except httpx.HTTPError as exc:
        logger.error("Gmail send failed: %s", getattr(getattr(exc, "response", None), "text", exc))
        raise HTTPException(502, "Gmail a refusé l'envoi, réessayez")
    if link:
        await db.conversations.update_one(ctx.q({"id": cid}), {"$set": link})
    return {"id": cid}


@router.get("/messaging/messages/{mid}/attachments/{index}")
async def attachment(mid: str, index: int, ctx: Ctx = Depends(READ)):
    msg = await ctx.get("messages", mid)
    if not 0 <= index < len(msg.get("attachments", [])):
        raise HTTPException(404, "Pièce jointe introuvable")
    att = msg["attachments"][index]
    acc = await _live_account(ctx, {"account_id": msg["account_id"]})
    full = await _gmail(acc, "GET", f"/messages/{msg['gmail_id']}", params={"format": "full"})
    stack, part = [full.get("payload") or {}], None
    while stack:
        p = stack.pop()
        if p.get("filename") and p.get("partId", "") == att["part_id"]:
            part = p
            break
        stack += p.get("parts") or []
    body = (part or {}).get("body") or {}
    if not part:
        raise HTTPException(404, "Pièce jointe introuvable dans Gmail")
    data = body.get("data") or (await _gmail(acc, "GET", f"/messages/{msg['gmail_id']}/attachments/{body['attachmentId']}"))["data"]
    return Response(mc._b64(data), media_type="application/octet-stream",
                    headers={"Content-Disposition": "attachment", "X-Content-Type-Options": "nosniff"})


# ---------- Notes internes ----------
class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


@router.post("/messaging/conversations/{cid}/notes")
async def add_note(cid: str, body: NoteIn, ctx: Ctx = Depends(WRITE)):
    await ctx.get("conversations", cid)
    doc = await ctx.insert("internal_notes", {"conversation_id": cid, "text": body.text.strip(), "by": ctx.member.get("name")})
    doc.pop("org_id")
    return doc


@router.delete("/messaging/notes/{nid}")
async def delete_note(nid: str, ctx: Ctx = Depends(WRITE)):
    await ctx.delete("internal_notes", nid)
    return {"ok": True}


# ---------- Contact, événement, IA ----------
async def _contact_from(ctx: Ctx, conv: dict) -> str:
    if not ctx.can("contacts:write"):
        raise HTTPException(403, "Action non autorisée pour votre rôle")
    cp = conv.get("counterpart") or {}
    if not EMAIL_RE.match(cp.get("email") or ""):
        raise HTTPException(400, "Aucune adresse e-mail exploitable dans cette conversation")
    first, _, last = (cp.get("name") or cp["email"].split("@")[0]).strip().partition(" ")
    c = await ctx.insert("contacts", {"kind": "particulier", "status": "prospect", "first_name": first, "last_name": last, "company": "", "email": cp["email"],
                                      "phone": "", "address": "", "city": "", "source": "Messagerie", "tags": [], "notes": "", "types": ["client"], "interactions": []})
    await db.conversations.update_many(ctx.q({"contact_id": None, "counterpart.email": cp["email"]}), {"$set": {"contact_id": c["id"]}})
    return c["id"]


@router.post("/messaging/conversations/{cid}/contact")
async def create_contact_from(cid: str, ctx: Ctx = Depends(WRITE)):
    conv = await ctx.get("conversations", cid)
    if conv.get("contact_id"):
        raise HTTPException(409, "Cette conversation est déjà rattachée à un contact")
    await _contact_from(ctx, conv)
    return await get_conversation(cid, ctx)


def _need_ai() -> None:
    if not mc.ai_ready():
        mc.ai_fail()


@router.post("/messaging/conversations/{cid}/classify")
async def classify(cid: str, ctx: Ctx = Depends(WRITE)):
    _need_ai()
    await ctx.get("conversations", cid)
    await mc.classify_conv(cid, True)
    return await get_conversation(cid, ctx)


@router.post("/messaging/conversations/{cid}/suggest")
async def suggest(cid: str, ctx: Ctx = Depends(WRITE)):
    _need_ai()
    conv = await get_conversation(cid, ctx)
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    context = f"Contact : {(conv['contact'] or {}).get('display_name') or 'inconnu'}."
    if conv["event"]:
        context += f" Événement lié : {conv['event']['title']} le {conv['event']['start'][:10]} (statut {conv['event']['status']})."
    try:
        return {"text": await mc.suggest_reply(conv, org, context)}
    except Exception as exc:
        mc.ai_fail(exc)


@router.post("/messaging/conversations/{cid}/event-draft")
async def draft_event(cid: str, ctx: Ctx = Depends(WRITE)):
    conv = await ctx.get("conversations", cid)
    d = {"title": f"Demande — {conv['subject']}"[:120], "type": "Autre", "start": "", "end": "", "guests": 0, "ai": False}
    if mc.ai_ready():
        try:
            a = await mc.event_draft(conv)
            d.update(title=a.title[:120] or d["title"], type=a.type, guests=max(a.guests, 0), ai=True)
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.date):
                day = datetime.strptime(a.date, "%Y-%m-%d")
                d.update(start=f"{a.date}T18:00", end=f"{(day + timedelta(days=1)).strftime('%Y-%m-%d')}T02:00")
        except Exception as exc:
            d["ai_error"] = mc.ai_fail(exc, False)
    return d


class EventFromIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: str = "Autre"
    start: str
    end: str
    guests: int = 0


@router.post("/messaging/conversations/{cid}/event")
async def event_from(cid: str, body: EventFromIn, ctx: Ctx = Depends(WRITE)):
    if not ctx.can("events:write"):
        raise HTTPException(403, "Action non autorisée pour votre rôle")
    conv = await ctx.get("conversations", cid)
    contact_id = conv.get("contact_id") or await _contact_from(ctx, conv)
    msg = await db.messages.find(ctx.q({"conversation_id": cid, "deleted_at": None, "direction": "in"}), {"_id": 0, "text": 1, "from": 1, "sent_at": 1}).sort("sent_at", -1).to_list(1)
    notes = f"Demande reçue par e-mail le {msg[0]['sent_at'][:10]} de {msg[0]['from']['email']} :\n\n{msg[0]['text'][:5000]}" if msg else ""
    ev = await create_event(EventIn(title=body.title, type=body.type, client_id=contact_id, start=body.start, end=body.end, guests=body.guests, notes=notes), ctx)
    await db.conversations.update_one(ctx.q({"id": cid}), {"$set": {"event_id": ev["id"]}})
    return ev


# ---------- Webhook Pub/Sub et tâches planifiées ----------
def _verify_push(token: str) -> None:
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token
    claims = id_token.verify_oauth2_token(token, g_requests.Request(), audience=os.environ.get("PUBSUB_AUDIENCE") or None)
    if claims.get("email") != os.environ["PUBSUB_PUSH_SA_EMAIL"] or not claims.get("email_verified"):
        raise ValueError("unexpected service account")


@router.post("/webhooks/gmail")
async def gmail_webhook(request: Request, bg: BackgroundTasks):
    if not os.environ.get("PUBSUB_PUSH_SA_EMAIL"):
        raise HTTPException(503, "Webhook non configuré")
    auth = request.headers.get("authorization", "")
    try:
        await run_in_threadpool(_verify_push, auth[7:] if auth.lower().startswith("bearer ") else "")
    except Exception:
        raise HTTPException(401, "Invalid Pub/Sub token")
    try:
        message = (await request.json())["message"]
        data = json.loads(base64.b64decode(message["data"]))
        email = data["emailAddress"].lower()
    except Exception:
        raise HTTPException(400, "Invalid body")
    try:
        await db.webhook_events.insert_one({"_id": f"gmail:{message.get('messageId') or message.get('message_id')}", "at": now_iso()})
    except DuplicateKeyError:
        return {"ok": True, "duplicate": True}
    bg.add_task(tenants.run_in_org_of, "channel_accounts", {"email": email}, mc.sync_email, email)
    return {"ok": True}


@router.post("/cron/messaging-sync")
async def cron_sync(request: Request, bg: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    if not await cron_guard(request, "messaging-sync"):
        return {"ok": True, "duplicate": True}
    bg.add_task(tenants.for_each_org, mc.sync_all, label="messaging-sync")
    return {"ok": True}


@router.post("/cron/messaging-daily")
async def cron_daily(request: Request, bg: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    if not await cron_guard(request, "messaging-daily"):
        return {"ok": True, "duplicate": True}
    bg.add_task(tenants.for_each_org, mc.daily_trash, label="messaging-daily")
    return {"ok": True}
