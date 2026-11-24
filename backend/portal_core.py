import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import requests
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

import messaging_core as mc
import providers_core as pc
from core import ENV, _admin_emails, audit, db, new_id, now_iso
from i18n import doc_lang

logger = logging.getLogger(__name__)
INVITE_DAYS = 7
TERMS_VERSION = "2026-11"
MODULES = [("home", "Mon événement", "My event", "Home", False), ("music", "Ma musique", "My music", "Music", True), ("documents", "Documents", "Documents", "FileText", False),
           ("billing", "Devis & factures", "Quotes & invoices", "Receipt", False), ("timeline", "Déroulé", "Schedule", "Clock", True),
           ("messages", "Messages", "Messages", "MessageCircle", True), ("guests", "Mes invités", "My guests", "Users", False)]
BUILT = ["home", "music", "documents", "billing", "timeline", "messages"]
ON = {"client_visible": True, "lock_offset_days": 0}
DEFAULTS = {"*": {"documents": ON, "billing": ON, "timeline": ON, "messages": ON},
            "Mariage": {"documents": ON, "billing": ON, "timeline": ON, "messages": ON, "music": {"client_visible": True, "lock_offset_days": 10}}}
FOOT_FR = "\n\n—\n{societe} · Politique de confidentialité : {confidentialite}"
FOOT_EN = "\n\n—\n{societe} · Privacy policy: {confidentialite}"
TEMPLATES = {
    "invitation": {"fr": ("Votre espace {societe} est prêt", "Bonjour {prenom},\n\nVotre espace personnel pour « {evenement} » est prêt. Connectez-vous en un clic, sans mot de passe :\n{lien}\n\nCe lien est valable 7 jours. Ensuite, demandez simplement un nouveau lien depuis l'écran de connexion avec votre adresse e-mail."),
                   "en": ("Your {societe} space is ready", "Hello {prenom},\n\nYour personal space for “{evenement}” is ready. Sign in with one click, no password needed:\n{lien}\n\nThis link is valid for 7 days. After that, simply request a new link from the sign-in screen with your e-mail address.")},
    "module_open": {"fr": ("Nouveau dans votre espace : {module}", "Bonjour {prenom},\n\nLa rubrique « {module} » est maintenant ouverte dans votre espace pour « {evenement} » :\n{lien}"),
                    "en": ("New in your space: {module}", "Hello {prenom},\n\nThe “{module}” section is now open in your space for “{evenement}”:\n{lien}")},
    "music_reminder": {"fr": ("Votre musique : plus que {jours} jours", "Bonjour {prenom},\n\nIl vous reste {jours} jours pour finaliser vos choix musicaux pour « {evenement} » :\n{lien}"),
                       "en": ("Your music: {jours} days left", "Hello {prenom},\n\nYou have {jours} days left to finalise your music choices for “{evenement}”:\n{lien}")},
    "new_message": {"fr": ("Nouveau message de {societe}", "Bonjour {prenom},\n\nVous avez reçu un nouveau message au sujet de « {evenement} » :\n\n{message}\n\nRépondre : {lien}"),
                    "en": ("New message from {societe}", "Hello {prenom},\n\nYou have a new message about “{evenement}”:\n\n{message}\n\nReply: {lien}")},
    "new_document": {"fr": ("Nouveau document : {document}", "Bonjour {prenom},\n\nLe document « {document} » est disponible dans votre espace pour « {evenement} » :\n{lien}"),
                     "en": ("New document: {document}", "Hello {prenom},\n\nThe document “{document}” is available in your space for “{evenement}”:\n{lien}")},
    "alert": {"fr": ("{societe} : {sujet}", "Bonjour {prenom},\n\n{message}\n\n{lien}"), "en": ("{societe}: {sujet}", "Hello {prenom},\n\n{message}\n\n{lien}")},
    "access_end": {"fr": ("Votre espace ferme dans 15 jours", "Bonjour {prenom},\n\nVotre espace pour « {evenement} » sera fermé dans 15 jours. Pensez à télécharger vos documents :\n{lien}"),
                   "en": ("Your space closes in 15 days", "Hello {prenom},\n\nYour space for “{evenement}” will close in 15 days. Remember to download your documents:\n{lien}")},
}
VARIABLES = ["prenom", "societe", "evenement", "lien", "module", "document", "message", "sujet", "jours", "confidentialite"]


def today() -> str:
    return datetime.now(pc.PARIS).strftime("%Y-%m-%d")


def _clerk(method: str, path: str, **kw):
    r = requests.request(method, "https://api.clerk.com/v1" + path, timeout=15, **kw,
                         headers={"Authorization": f"Bearer {os.environ['CLERK_SECRET_KEY']}", "Content-Type": "application/json", "User-Agent": "eventstudio"})
    if r.status_code >= 400:
        raise HTTPException(502, "Le service de connexion a refusé l'opération : " + r.text[:160])
    return r.json() if r.content else {}


async def clerk(method: str, path: str, **kw):
    return await run_in_threadpool(lambda: _clerk(method, path, **kw))


async def revoke_sessions(user_id: str) -> int:
    await db.users.update_one({"user_id": user_id}, {"$set": {"sessions_revoked_at": int(datetime.now(timezone.utc).timestamp())}})
    try:
        page = await clerk("GET", "/sessions", params={"user_id": user_id, "status": "active", "limit": 100})
        rows = page if isinstance(page, list) else page.get("data", [])
        for s in rows:
            await clerk("POST", f"/sessions/{s['id']}/revoke")
        return len(rows)
    except HTTPException as exc:
        logger.error("Révocation Clerk incomplète pour %s : %s", user_id, exc.detail)
        return 0


async def template(org_id: str, key: str, lg: str) -> tuple:
    row = await db.email_templates.find_one({"org_id": org_id, "key": key, "language": lg}, {"_id": 0})
    return (row["subject"], row["body_html"]) if row else TEMPLATES[key][lg]


async def send_tpl(org: dict, key: str, language: str | None, to: str, v: dict, base: str = "") -> bool:
    lg = doc_lang(language)
    subject, body = await template(org["id"], key, lg)
    v = {"societe": org.get("name", ""), "confidentialite": f"{base}/legal/{org['id']}/privacy", "lien": base, **v}
    if ENV != "live" and to.lower() not in _admin_emails():
        return False
    acc = await db.channel_accounts.find_one({"org_id": org["id"], "channel": "gmail", "status": "connected"}, {"_id": 0})
    if not acc:
        return False
    try:
        await mc.send_mail(acc, org, to, pc.render(subject, v), pc.render(body + (FOOT_FR if lg == "fr" else FOOT_EN), v))
        return True
    except Exception as exc:
        logger.error("E-mail %s non envoyé à %s : %s", key, to, exc)
        return False


async def invite(org: dict, contact: dict, role: str, actor: dict | None, base: str, event_title: str = "") -> dict:
    email = (contact.get("email") or "").strip().lower()
    if not pc.MAIL_RE.match(email):
        raise HTTPException(400, "Ce contact n'a pas d'adresse e-mail valide")
    u = await db.users.find_one({"org_id": org["id"], "contact_id": contact["id"], "role": role}, {"_id": 0})
    if not u:
        found = await clerk("GET", "/users", params={"email_address": email})
        if found:
            cu = found[0]
        else:
            body = {"email_address": [email], "first_name": contact.get("first_name") or None, "last_name": contact.get("last_name") or None}
            try:
                cu = await clerk("POST", "/users", json={**body, "skip_password_requirement": True})
            except HTTPException:
                cu = await clerk("POST", "/users", json={**body, "password": secrets.token_urlsafe(32), "skip_password_checks": True})
        if await db.users.find_one({"user_id": cu["id"]}):
            raise HTTPException(409, "Cette adresse e-mail est déjà rattachée à un autre compte de l'application")
        u = {"user_id": cu["id"], "email": email, "name": " ".join(filter(None, [contact.get("first_name"), contact.get("last_name")])) or contact.get("company") or email,
             "org_id": org["id"], "role": role, "team_id": None, "contact_id": contact["id"], "status": "invited", "env": ENV, "created_at": now_iso()}
        await db.users.insert_one({**u})
    tok = await clerk("POST", "/sign_in_tokens", json={"user_id": u["user_id"], "expires_in_seconds": INVITE_DAYS * 86400})
    link = f"{base}/sign-in?__clerk_ticket={tok['token']}"
    ch = {"invited_at": now_iso(), "invite_expires_at": (datetime.now(timezone.utc) + timedelta(days=INVITE_DAYS)).isoformat()}
    if u.get("status") == "suspended":
        raise HTTPException(409, "Accès suspendu : réactivez-le avant de renvoyer l'invitation")
    if u.get("status") == "deleted":
        ch["status"] = "invited"
    await db.users.update_one({"user_id": u["user_id"]}, {"$set": ch})
    sent = await send_tpl(org, "invitation", contact.get("language"), email, {"prenom": contact.get("first_name") or "", "evenement": event_title or org.get("name", ""), "lien": link}, base)
    await audit(org["id"], actor, "invitation", email, f"{role} — {'e-mail envoyé' if sent else 'e-mail non envoyé, lien à transmettre'}")
    return {"user_id": u["user_id"], "email": email, "sent": sent, "link": None if sent else link}


async def auto_provider(org: dict, contact_id: str, actor: dict | None, base: str) -> None:
    c = await db.contacts.find_one({"org_id": org["id"], "id": contact_id}, {"_id": 0})
    if not c:
        return
    u = await db.users.find_one({"org_id": org["id"], "contact_id": contact_id, "role": "provider"}, {"_id": 0})
    try:
        if u:
            en = doc_lang(c.get("language")) == "en"
            await send_tpl(org, "alert", c.get("language"), u["email"], {"prenom": c.get("first_name") or "", "sujet": "New job" if en else "Nouvelle mission",
                                                                        "message": "A new job has been added to your portal." if en else "Une nouvelle mission a été ajoutée à votre portail.", "lien": base}, base)
        else:
            await invite(org, c, "provider", actor, base)
    except HTTPException as exc:
        logger.error("Compte prestataire non créé pour %s : %s", contact_id, exc.detail)


async def modules(org_id: str) -> list:
    if not await db.portal_modules.count_documents({"org_id": org_id}):
        for i, (k, fr, en, icon, prov) in enumerate(MODULES):
            await db.portal_modules.update_one({"org_id": org_id, "key": k}, {"$setOnInsert": {"id": new_id(), "label": fr, "label_en": en, "description": "", "description_en": "", "icon": icon,
                                               "staff_enabled": True, "client_facing": True, "provider_facing": prov, "order": i, "active": True, "notify": True}}, upsert=True)
    return await db.portal_modules.find({"org_id": org_id}, {"_id": 0}).sort("order", 1).to_list(50)


async def event_modules(org: dict, ev: dict) -> dict:
    rows = await db.event_portal_modules.find({"org_id": org["id"], "event_id": ev["id"]}, {"_id": 0}).to_list(50)
    have = {r["module_key"] for r in rows}
    d = org.get("portal_defaults") or DEFAULTS
    d = d.get(ev.get("type")) or d.get("*") or {}
    for m in await modules(org["id"]):
        if m["key"] in have or m["key"] == "home":
            continue
        x = d.get(m["key"]) or {}
        off = int(x.get("lock_offset_days") or 0)
        lock = (datetime.strptime(ev["start"][:10], "%Y-%m-%d") - timedelta(days=off)).strftime("%Y-%m-%d") if off and ev.get("start") else ""
        row = {"id": new_id(), "org_id": org["id"], "event_id": ev["id"], "module_key": m["key"], "client_visible": bool(x.get("client_visible")), "client_editable": True,
               "visible_from": "", "lock_date": lock, "status": "open", "created_at": now_iso()}
        await db.event_portal_modules.update_one({"org_id": org["id"], "event_id": ev["id"], "module_key": m["key"]}, {"$setOnInsert": row}, upsert=True)
        rows.append(row)
    return {r["module_key"]: r for r in rows}


async def visible_modules(org: dict, ev: dict) -> dict:
    rows, day, out = await event_modules(org, ev), today(), {}
    for m in await modules(org["id"]):
        r = rows.get(m["key"]) or {}
        if m["key"] != "home" and not (m["active"] and m["client_facing"] and r.get("client_visible") and (r.get("visible_from") or "") <= day):
            continue
        locked = bool(r.get("lock_date")) and r["lock_date"] < day
        out[m["key"]] = {"key": m["key"], "label": m["label"], "label_en": m["label_en"] or m["label"], "icon": m["icon"], "built": m["key"] in BUILT,
                         "editable": m["key"] != "home" and bool(r.get("client_editable")) and not locked, "lock_date": r.get("lock_date") or ""}
    return out


def portal_state(ev: dict, org: dict) -> str:
    if ev.get("portal_status") in ("read_only", "disabled"):
        return ev["portal_status"]
    s = org.get("portal_settings") or {}
    end = datetime.strptime((ev.get("end") or ev.get("start") or "2999-01-01")[:10], "%Y-%m-%d")
    now = datetime.strptime(today(), "%Y-%m-%d")
    if now > end + timedelta(days=int(s.get("disable_days") or 365)):
        return "disabled"
    return "read_only" if now > end + timedelta(days=int(s.get("read_only_days") or 90)) else "active"


async def notify_clients(org: dict, ev: dict, key: str, v: dict, base: str) -> None:
    for u in await db.users.find({"org_id": org["id"], "role": "client", "status": "active", "contact_id": {"$in": ev.get("client_contact_ids") or []}}, {"_id": 0}).to_list(20):
        c = await db.contacts.find_one({"org_id": org["id"], "id": u["contact_id"]}, {"_id": 0}) or {}
        if (u.get("notifications") or {}).get("email", True):
            await send_tpl(org, key, c.get("language"), u["email"], {"prenom": c.get("first_name") or "", "evenement": ev["title"], "lien": base, **v}, base)


async def tick() -> None:
    base = (os.environ.get("APP_URL") or "").rstrip("/")
    day = datetime.strptime(today(), "%Y-%m-%d")
    async for org in db.orgs.find({}, {"_id": 0}):
        off = int((org.get("portal_settings") or {}).get("disable_days") or 365) - 15
        target = (day - timedelta(days=off)).strftime("%Y-%m-%d")
        async for ev in db.events.find({"org_id": org["id"], "end": {"$regex": f"^{target}"}, "portal_end_notified": {"$ne": True}}, {"_id": 0}):
            await notify_clients(org, ev, "access_end", {}, base)
            await db.events.update_one({"org_id": org["id"], "id": ev["id"]}, {"$set": {"portal_end_notified": True}})
        for n in (30, 15, 3):
            d = (day + timedelta(days=n)).strftime("%Y-%m-%d")
            async for ev in db.events.find({"org_id": org["id"], "start": {"$regex": f"^{d}"}, "music_reminders": {"$ne": n}}, {"_id": 0}):
                plan = await db.music_plans.find_one({"org_id": org["id"], "event_id": ev["id"]}, {"_id": 0, "status": 1}) or {"status": "draft"}
                if plan["status"] == "draft" and "music" in await visible_modules(org, ev):
                    await notify_clients(org, ev, "music_reminder", {"jours": str(n)}, base)
                await db.events.update_one({"org_id": org["id"], "id": ev["id"]}, {"$addToSet": {"music_reminders": n}})
        soon = (day + timedelta(days=30)).strftime("%Y-%m-%d")
        async for d in db.provider_documents.find({"org_id": org["id"], "expires_at": {"$gt": "", "$lte": soon}, "reminded_at": None}, {"_id": 0}):
            p = await db.provider_profiles.find_one({"org_id": org["id"], "id": d["provider_id"]}, {"_id": 0}) or {}
            c = await db.contacts.find_one({"org_id": org["id"], "id": p.get("contact_id")}, {"_id": 0}) or {}
            if c.get("email"):
                en = doc_lang(c.get("language")) == "en"
                await send_tpl(org, "alert", c.get("language"), c["email"], {"prenom": c.get("first_name") or "", "sujet": "Document expiring" if en else "Document à renouveler",
                               "message": (f"Your document ({d['type']}) expires on {d['expires_at']}. Please upload the new version." if en
                                           else f"Votre document ({d['type']}) expire le {d['expires_at']}. Merci de déposer la nouvelle version."), "lien": base}, base)
            await db.provider_documents.update_one({"org_id": org["id"], "id": d["id"]}, {"$set": {"reminded_at": now_iso()}})
