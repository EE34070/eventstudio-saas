import tenant_router as tenants
from functools import partial
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from core import Ctx, db, need, now_iso
from emailer import mail_html, send_email
from i18n import fmt_date, money, pick, tr, yousign_locale
from routes_billing import cron_guard, eur, fr_date, hist, invoice_pdf_bytes, quote_pdf_bytes, quote_writer, today
from routes_files import file_bytes, store_bytes

from core import check_expiry, ensure_link, link_doc, link_limit  # noqa: E402,F401
from core import audit  # noqa: E402
router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
HOST_RE = re.compile(r"^[a-z0-9.-]+$")
DEFAULT_SIGN_FIELDS = ["Nom et qualité du signataire", "Adresse de facturation", "Mention « Bon pour accord »"]
STEPS = (7, 15, 30)
SIG_STATUS = {"done": "done", "declined": "declined", "rejected": "declined", "expired": "expired", "canceled": "canceled", "deleted": "canceled"}


def base_url(request: Request) -> str:
    # Liens envoyés par e-mail : toujours l'adresse publique de l'application, jamais l'hôte du backend.
    if os.environ.get("APP_URL"):
        return os.environ["APP_URL"].rstrip("/")
    host = (request.headers.get("host") or "").lower()
    if not HOST_RE.match(host):
        raise HTTPException(400, "Hôte invalide")
    # Derrière la passerelle, Host est le nom interne (inaccessible de l'extérieur) : on prend l'adresse vue par le navigateur, si c'est la même application.
    for raw in (request.headers.get("origin"), request.headers.get("referer")):
        seen = (raw or "").split("://", 1)[-1].split("/", 1)[0].lower()
        if seen and HOST_RE.match(seen) and seen.split(".")[0] == host.split(".")[0]:
            return f"https://{seen}"
    return f"https://{host}"


async def ensure_token(coll: str, doc: dict) -> str:
    return await ensure_link(coll, doc)


async def client_of(doc: dict) -> dict:
    c = await db.contacts.find_one({"org_id": doc["org_id"], "id": doc.get("client_id")}, {"_id": 0}) if doc.get("client_id") else None
    c = c or {}
    email = (c.get("email") or (doc.get("client") or {}).get("email") or "").strip()
    return {"language": doc.get("language") or c.get("language") or "fr-FR", "email": email if EMAIL_RE.match(email) else "", "first_name": (c.get("first_name") or "").strip(),
            "last_name": (c.get("last_name") or "").strip(), "name": (doc.get("client") or {}).get("name") or ""}


def reply_to(org: dict) -> str | None:
    e = (org.get("email") or "").strip()
    return e if EMAIL_RE.match(e) else None


def _recent(iso: str | None, seconds: int) -> bool:
    return bool(iso) and (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() < seconds


async def _log_event(org_id: str, event_id: str, by: str, action: str, detail: str) -> None:
    await db.events.update_one({"org_id": org_id, "id": event_id}, {"$push": {"history": {
        "$each": [{"at": now_iso(), "by": by, "action": action, "detail": detail}], "$slice": -300}}})


# ---------- Envoi du devis ----------
@router.post("/quotes/{qid}/send")
async def send_quote(qid: str, request: Request, force: bool = False, ctx: Ctx = Depends(need("finance:read"))):
    quote_writer(ctx)
    q = await ctx.get("quotes", qid)
    await audit(ctx.org_id, ctx.member, "quote_sent", q.get("number", ""))
    pending = sum(1 for b in q.get("blocks") or [] if b.get("margin_pending"))
    if pending and not force:
        raise HTTPException(409, {"code": "margin_pending", "message": f"{pending} ligne(s) « Marge à définir » (vendues au prix coûtant) : définissez la marge ou confirmez l'envoi."})
    if q["status"] in ("refuse", "remplace"):
        raise HTTPException(400, "Un devis refusé ou remplacé ne peut pas être envoyé")
    if q.get("price_display") == "none":
        raise HTTPException(400, "Affichage « Sans prix » : un devis envoyé au client doit montrer au minimum le total HT, la TVA et le total TTC. Choisissez un autre affichage des prix.")
    if _recent(q.get("sent_at"), 60):
        raise HTTPException(429, "Ce devis vient d'être envoyé, patientez une minute")
    c = await client_of(q)
    if not c["email"]:
        raise HTTPException(400, "Le client n'a pas d'adresse e-mail valide dans sa fiche contact")
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    url = f"{base_url(request)}/devis/{await ensure_token('quotes', q)}"
    lg = c["language"]
    html = mail_html(org["name"], tr("hello", lg, name=c["name"]), [
        tr("mail_quote_1", lg, n=q["number"], title=await __import__("routes_titles").quote_title({**q, "language": lg}), ttc=money(q["total_ttc"], lg)),
        tr("mail_quote_2", lg, date=fmt_date(__import__("routes_titles").validity(q, org), lg)), tr("mail_quote_3", lg)], (tr("mail_quote_btn", lg), url), lg)
    await send_email(to=c["email"], subject=tr("mail_quote_subject", lg, n=q["number"], org=org["name"]), html=html, reply_to=reply_to(org))
    from routes_quotes import on_sent
    await on_sent(ctx.org_id, q["event_id"])
    upd = {"sent_at": now_iso(), "sent_to": c["email"]}
    if q["status"] == "brouillon":
        upd["status"] = "envoye"
    await db.quotes.update_one(ctx.q({"id": qid}), {"$set": upd, "$push": {"history": hist(ctx, "Envoi", f"Envoyé par e-mail à {c['email']}")}})
    await _log_event(ctx.org_id, q["event_id"], ctx.member.get("name"), "Devis", f"Devis {q['number']} envoyé à {c['email']}")
    return await ctx.get("quotes", qid)


@router.get("/public/quotes/{token}/pdf")
async def public_quote_pdf(token: str):
    q = await link_doc("quotes", token)
    if not q:
        raise HTTPException(404, "Introuvable")
    org = await db.orgs.find_one({"id": q["org_id"]}, {"_id": 0})
    return Response(await quote_pdf_bytes(q, org), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{q["number"]}.pdf"'})


@router.get("/public/invoices/{token}/pdf")
async def public_invoice_pdf(token: str):
    i = await link_doc("invoices", token)
    if not i:
        raise HTTPException(404, "Introuvable")
    org = await db.orgs.find_one({"id": i["org_id"]}, {"_id": 0})
    return Response(invoice_pdf_bytes(i, org), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{i["number"]}.pdf"'})


# ---------- Signature électronique (Yousign) ----------
async def ys(method: str, path: str, **kw) -> httpx.Response:
    key = os.environ.get("YOUSIGN_API_KEY")
    if not key:
        raise HTTPException(503, "La signature électronique n'est pas encore configurée (clé Yousign manquante)")
    async with httpx.AsyncClient(base_url=os.environ["YOUSIGN_BASE_URL"].rstrip("/"), timeout=45) as c:
        r = await c.request(method, path, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}, **kw)
    if r.is_error:
        logger.error("Yousign %s %s -> %s %s", method, path, r.status_code, r.text[:500])
        raise HTTPException(502, f"Yousign a refusé la demande ({r.status_code}) : {r.text[:300]}")
    return r


class SignatureProvider:
    name = ""

    async def start(self, q: dict, org: dict, c: dict, base: str) -> dict:
        raise NotImplementedError

    async def cancel(self, sig: dict) -> None:
        return None


class YousignProvider(SignatureProvider):
    name = "yousign"

    async def start(self, q: dict, org: dict, c: dict, base: str) -> dict:
        if not (c["first_name"] and c["last_name"]):
            raise HTTPException(400, "Prénom, nom et e-mail du signataire sont requis dans la fiche contact du client")
        en = not c["language"].startswith("fr")
        pos = {"language": c["language"], "labels": [f for f in ((en and org.get("signature_fields_en")) or org.get("signature_fields", DEFAULT_SIGN_FIELDS)) if f.strip()][:6]}
        pdf = await quote_pdf_bytes(q, org, pos)
        sr = (await ys("POST", "/signature_requests", json={"name": f"Devis {q['number']} — {q['event_title']}"[:120], "delivery_mode": "email",
                                                            "timezone": "Europe/Paris", "external_id": q["id"]})).json()
        doc = (await ys("POST", f"/signature_requests/{sr['id']}/documents", files={"file": (f"{q['number']}.pdf", pdf, "application/pdf")},
                        data={"nature": "signable_document"})).json()
        fields = [{"type": "signature", "document_id": doc["id"], "page": pos["page"], **pos["signature"]}]
        fields += [{"type": "text", "document_id": doc["id"], "page": pos["page"], "x": f["x"], "y": f["y"], "max_length": 60,
                    "question": f["label"][:250], "optional": False, "name": f"champ_{i + 1}"} for i, f in enumerate(pos["fields"])]
        signer = (await ys("POST", f"/signature_requests/{sr['id']}/signers", json={
            "info": {"first_name": c["first_name"], "last_name": c["last_name"], "email": c["email"], "locale": yousign_locale(c["language"])},
            "signature_level": "electronic_signature", "signature_authentication_mode": "otp_email", "fields": fields})).json()
        await ys("POST", f"/signature_requests/{sr['id']}/activate")
        return {"provider": "yousign", "request_id": sr["id"], "document_id": doc["id"], "signer_id": signer["id"], "status": "ongoing", "sent_at": now_iso(), "sent_to": c["email"],
                "hash": hashlib.sha256(pdf).hexdigest()}

    async def cancel(self, sig: dict) -> None:
        await ys("POST", f"/signature_requests/{sig['request_id']}/cancel", json={"reason": "errors_in_document"})


class OtpProvider(SignatureProvider):
    name = "otp"

    async def start(self, q: dict, org: dict, c: dict, base: str) -> dict:
        from routes_quote_docs import otp_start
        return await otp_start(q, org, c, base)


def signature_provider(name: str = "") -> SignatureProvider:
    return YousignProvider() if (name or ("yousign" if os.environ.get("YOUSIGN_API_KEY") else "otp")) == "yousign" else OtpProvider()


@router.post("/quotes/{qid}/signature")
async def start_signature(qid: str, request: Request, ctx: Ctx = Depends(need("finance:read"))):
    quote_writer(ctx)
    q = await ctx.get("quotes", qid)
    if q["status"] in ("refuse", "remplace") or q.get("active") is False:
        raise HTTPException(400, "Un devis refusé ou remplacé ne peut pas être signé")
    if q.get("price_display") == "none":
        raise HTTPException(400, "Affichage « Sans prix » : l'envoi en signature est bloqué. Un devis signé doit montrer le total HT, la TVA et le total TTC.")
    if (q.get("signature") or {}).get("status") in ("ongoing", "done"):
        raise HTTPException(409, "Une signature est déjà en cours ou terminée pour ce devis")
    c = await client_of(q)
    if not c["email"]:
        raise HTTPException(400, "L'e-mail du signataire est requis dans la fiche contact du client")
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    sig = await signature_provider().start(q, org, c, base_url(request))
    from routes_quotes import on_sent
    await on_sent(ctx.org_id, q["event_id"])
    upd = {"signature": sig, "client_modified": False}
    if q["status"] == "brouillon":
        upd["status"] = "envoye"
    await db.quotes.update_one(ctx.q({"id": qid}), {"$set": upd, "$push": {"history": hist(ctx, "Signature", f"Demande de signature envoyée à {c['email']}")}})
    await _log_event(ctx.org_id, q["event_id"], ctx.member.get("name"), "Devis", f"Devis {q['number']} envoyé en signature à {c['email']}")
    return await ctx.get("quotes", qid)


async def apply_signature(quote_id: str, status: str, by: str = "Yousign") -> None:
    q = await db.quotes.find_one({"id": quote_id}, {"_id": 0})
    sig = (q or {}).get("signature") or {}
    if not q or sig.get("status") == status:
        return
    upd = {"signature.status": status, "signature.updated_at": now_iso()}
    label = {"done": "Devis signé par le client", "declined": "Signature refusée par le client", "expired": "Demande de signature expirée",
             "canceled": "Demande de signature annulée"}.get(status, status)
    if status in ("done", "declined", "expired"):
        upd["status"] = {"done": "accepte", "declined": "refuse", "expired": "expire"}[status]
    await db.quotes.update_one({"id": quote_id}, {"$set": upd, "$push": {"history": {"at": now_iso(), "by": by, "action": "Signature", "detail": label}}})
    await _log_event(q["org_id"], q["event_id"], by, "Devis", f"{q['number']} : {label}")
    if status != "done":
        return
    from routes_quotes import on_accept
    await on_accept(q["org_id"], quote_id, by)
    import routes_stock
    if q.get("deposit_percent"):
        await routes_stock.task(q["org_id"], f"Devis {q['number']} signé : créer la facture d'acompte", f"quote-signed:{quote_id}", desc="Le devis est signé et verrouillé. Créez la facture d'acompte depuis Devis & factures.")
    if sig.get("provider", "yousign") != "yousign":
        return
    try:
        path = f"/signature_requests/{sig['request_id']}/documents/{sig['document_id']}"
        pdf = (await ys("GET", f"{path}/download")).content
        more = {"signature.signed_file": await store_bytes(q["org_id"], pdf, "application/pdf", f"{q['number']}-signe.pdf", "Yousign")}
        rows = (await ys("GET", f"{path}/fields")).json()
        rows = rows.get("data", []) if isinstance(rows, dict) else rows
        more["signature.answers"] = [{"question": f.get("question", ""), "answer": f.get("answer") or ""} for f in rows if f.get("type") == "text"]
        await db.quotes.update_one({"id": quote_id}, {"$set": more})
    except Exception as exc:
        logger.error("Yousign signed document fetch failed for %s: %s", q["number"], exc)


@router.post("/quotes/{qid}/signature/refresh")
async def refresh_signature(qid: str, ctx: Ctx = Depends(need("finance:read"))):
    quote_writer(ctx)
    q = await ctx.get("quotes", qid)
    sig = q.get("signature") or {}
    if sig.get("provider") == "otp":
        return q
    if not sig.get("request_id"):
        raise HTTPException(400, "Aucune demande de signature pour ce devis")
    remote = (await ys("GET", f"/signature_requests/{sig['request_id']}")).json().get("status", "")
    await apply_signature(qid, SIG_STATUS.get(remote, "ongoing"))
    if SIG_STATUS.get(remote) == "done" and not sig.get("signed_file"):
        await db.quotes.update_one(ctx.q({"id": qid, "signature.signed_file": {"$exists": False}}), {"$set": {"signature.status": "ongoing"}})
        await apply_signature(qid, "done")
    return await ctx.get("quotes", qid)


@router.post("/quotes/{qid}/signature/cancel")
async def cancel_signature(qid: str, ctx: Ctx = Depends(need("finance:read"))):
    quote_writer(ctx)
    q = await ctx.get("quotes", qid)
    sig = q.get("signature") or {}
    if sig.get("status") != "ongoing":
        raise HTTPException(400, "Aucune signature en cours à annuler")
    await signature_provider(sig.get("provider", "yousign")).cancel(sig)
    await apply_signature(qid, "canceled", ctx.member.get("name"))
    return await ctx.get("quotes", qid)


@router.get("/quotes/{qid}/signed-pdf")
async def signed_pdf(qid: str, ctx: Ctx = Depends(need("finance:read"))):
    q = await ctx.get("quotes", qid)
    got = await file_bytes(ctx.org_id, (q.get("signature") or {}).get("signed_file") or "")
    if not got:
        raise HTTPException(404, "Le devis signé n'est pas encore disponible")
    return Response(got[0], media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{q["number"]}-signe.pdf"'})


@router.post("/webhooks/yousign")
async def yousign_webhook(request: Request, bg: BackgroundTasks):
    secret = os.environ.get("YOUSIGN_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(503, "Webhook non configuré")
    raw = await request.body()
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest((request.headers.get("x-yousign-signature-256") or "").strip(), expected):
        raise HTTPException(401, "Invalid webhook signature")
    event = json.loads(raw)
    if not event.get("event_id"):
        raise HTTPException(400, "Missing event_id")
    try:
        await db.webhook_events.insert_one({"_id": f"yousign:{event['event_id']}", "at": now_iso()})
    except DuplicateKeyError:
        return {"ok": True, "duplicate": True}
    status = SIG_STATUS.get((event.get("event_name") or "").rsplit(".", 1)[-1])
    sr_id = ((event.get("data") or {}).get("signature_request") or {}).get("id")
    org_id = await tenants.org_of("quotes", {"signature.request_id": sr_id}) if sr_id else None
    if not org_id:
        return {"ok": True, "ignored": True}
    tenants.pin_org(org_id)
    if (event.get("event_name") or "") == "signer.link_opened":
        await db.quotes.update_one({"signature.request_id": ((event.get("data") or {}).get("signature_request") or {}).get("id"), "status": "envoye"}, {"$set": {"status": "vu", "viewed_at": now_iso()}})
    sr_id = ((event.get("data") or {}).get("signature_request") or {}).get("id")
    q = await db.quotes.find_one({"signature.request_id": sr_id}, {"_id": 0, "id": 1}) if status and sr_id else None
    if q:
        bg.add_task(apply_signature, q["id"], status)
    return {"ok": True}


# ---------- Relances impayés ----------
def _late(inv: dict, day: str) -> int:
    return (datetime.strptime(day, "%Y-%m-%d") - datetime.strptime(inv["due_date"], "%Y-%m-%d")).days


def reminder_copy(inv: dict, level: int, late: int, lg: str = "fr-FR") -> tuple:
    n, d, bal = inv["number"], fmt_date(inv["due_date"], lg), money(inv["balance_due"], lg)
    k = f"rem{min(3, max(1, level))}"
    return tr(f"{k}_s", lg, n=n), [tr(f"{k}_a", lg, n=n, d=d, bal=bal, late=late), tr(f"{k}_b", lg)]


def _old_copy(inv: dict, level: int, late: int) -> tuple:
    n, d, bal = inv["number"], fr_date(inv["due_date"]), eur(inv["balance_due"])
    if level <= 1:
        return f"Rappel : facture {n} en attente de règlement", [
            f"Sauf erreur de notre part, la facture {n}, arrivée à échéance le {d}, n'a pas encore été réglée. Le solde restant dû s'élève à {bal}.",
            "Si votre règlement a été effectué entre-temps, merci de ne pas tenir compte de ce message."]
    if level == 2:
        return f"Deuxième relance : facture {n} impayée", [
            f"Malgré notre précédent rappel, la facture {n} (échéance du {d}) reste impayée à ce jour, soit {late} jours de retard. Le solde dû s'élève à {bal}.",
            "Nous vous remercions de procéder au règlement sous 8 jours, selon les modalités indiquées sur la facture."]
    return f"Dernière relance avant mise en demeure : facture {n}", [
        f"La facture {n} (échéance du {d}) demeure impayée après {late} jours de retard, pour un solde de {bal}.",
        "Sans règlement sous 8 jours, nous serons contraints d'engager une procédure de recouvrement ; les pénalités de retard prévues par nos conditions restent dues."]


async def _overdue(org_id: str) -> list:
    return await db.invoices.find({"org_id": org_id, "status": {"$ne": "payee"}, "due_date": {"$lt": today()}}, {"_id": 0}).sort("due_date", 1).to_list(1000)


async def _send_reminder(inv: dict, org: dict, base: str, level: int, by: str, auto: bool) -> str:
    c = await client_of(inv)
    if not c["email"]:
        raise HTTPException(400, "Le client n'a pas d'adresse e-mail valide dans sa fiche contact")
    lg = c["language"]
    subject, ps = reminder_copy(inv, level, _late(inv, today()), lg)
    url = f"{base}/api/public/invoices/{await ensure_token('invoices', inv)}/pdf"
    await send_email(to=c["email"], subject=subject, html=mail_html(org["name"], tr("hello", lg, name=c["name"]), ps, (tr("mail_invoice_btn", lg), url), lg),
                     reply_to=reply_to(org))
    entry = {"at": now_iso(), "level": level, "by": by, "auto": auto, "to": c["email"]}
    await db.invoices.update_one({"org_id": inv["org_id"], "id": inv["id"]}, {"$push": {"reminders": entry, "history": {
        "at": entry["at"], "by": by, "action": "Relance", "detail": f"Relance n° {level} envoyée à {c['email']}"}}})
    return c["email"]


@router.get("/reminders")
async def list_reminders(request: Request, ctx: Ctx = Depends(need("finance:read"))):
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    base, day, rows = base_url(request), today(), []
    for inv in await _overdue(ctx.org_id):
        c = await client_of(inv)
        late, sent = _late(inv, day), inv.get("reminders", [])
        level = min(3, len(sent) + 1)
        subject, ps = reminder_copy(inv, level, late, c["language"])
        url = f"{base}/api/public/invoices/{await ensure_token('invoices', inv)}/pdf"
        rows.append({**{k: inv[k] for k in ("id", "number", "kind", "event_id", "event_title", "due_date", "balance_due", "total_ttc")},
                     "client_name": c["name"], "client_email": c["email"], "days_late": late, "reminders": sent, "next_level": level,
                     "language": c["language"], "subject": subject, "message": "\n\n".join([tr("hello", c["language"], name=c["name"]), *ps, f"{tr('invoice', c['language'])} : {url}", org["name"]])})
    return {"auto": bool(org.get("auto_reminders")), "steps": STEPS, "rows": rows,
            "total_due": round(sum(r["balance_due"] for r in rows), 2)}


class AutoIn(BaseModel):
    auto: bool


@router.put("/reminders/settings")
async def reminder_settings(body: AutoIn, ctx: Ctx = Depends(need("finance:write"))):
    await db.orgs.update_one({"id": ctx.org_id}, {"$set": {"auto_reminders": body.auto}})
    return {"auto": body.auto}


@router.post("/invoices/{iid}/remind")
async def remind(iid: str, request: Request, ctx: Ctx = Depends(need("finance:write"))):
    inv = await ctx.get("invoices", iid)
    if inv["status"] == "payee" or inv["due_date"] >= today():
        raise HTTPException(400, "Cette facture n'est pas en retard de paiement")
    sent = inv.get("reminders", [])
    if sent and _recent(sent[-1]["at"], 3600):
        raise HTTPException(429, "Une relance vient déjà d'être envoyée pour cette facture")
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    to = await _send_reminder(inv, org, base_url(request), min(3, len(sent) + 1), ctx.member.get("name"), False)
    await _log_event(ctx.org_id, inv["event_id"], ctx.member.get("name"), "Relance", f"Relance de la facture {inv['number']} envoyée à {to}")
    return await ctx.get("invoices", iid)


async def run_auto_reminders(base: str) -> None:
    day = today()
    async for org in db.orgs.find({"auto_reminders": True}, {"_id": 0}):
        for inv in await _overdue(org["id"]):
            late = _late(inv, day)
            level = sum(1 for s in STEPS if late >= s)
            prev = inv.get("auto_level", 0)
            if level <= prev:
                continue
            key = {"org_id": org["id"], "id": inv["id"], "auto_level": inv.get("auto_level")}
            if (await db.invoices.update_one(key, {"$set": {"auto_level": level}})).modified_count == 0:
                continue
            try:
                await _send_reminder(inv, org, base, level, "Relance automatique", True)
            except Exception as exc:
                detail = getattr(exc, "detail", exc)
                logger.warning("Auto reminder %s failed: %s", inv["number"], detail)
                await db.invoices.update_one({"org_id": org["id"], "id": inv["id"]}, {"$set": {"auto_level": prev, "auto_error": str(detail)[:200]}})


@router.post("/cron/reminders")
async def cron_reminders(request: Request, bg: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    if not await cron_guard(request, "reminders"):
        return {"ok": True, "duplicate": True}
    bg.add_task(tenants.for_each_org, partial(run_auto_reminders, base_url(request)), label="reminders")
    return {"ok": True}
