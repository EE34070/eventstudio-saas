import tenant_router as tenants
from functools import partial
from typing import Literal  # noqa: F811
import hmac
import io
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import List
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Flowable, Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core import Ctx, audit, db, need, new_id, now_iso
from i18n import clean_lang, doc_lang, fmt_date, money, pick, tr
from routes_files import file_bytes, quote_products
from routes_main import contact_name

from core import ensure_link  # noqa: E402,F401
router = APIRouter(prefix="/api")
PARIS = ZoneInfo("Europe/Paris")
QUOTE_STATUSES = ["brouillon", "envoye", "vu", "negociation", "accepte", "refuse", "expire"]
OPEN_STATUSES = ("brouillon", "envoye", "vu", "negociation")
LOAD_STATUSES = ["confirme", "en_preparation"]


def today() -> str:
    return datetime.now(PARIS).strftime("%Y-%m-%d")


def plus_days(day: str, n: int) -> str:
    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=n)).strftime("%Y-%m-%d")


def r2(x: float) -> float:
    return round(float(x) + 1e-9, 2)


def totals(lines: list) -> dict:
    by: dict = {}
    for l in lines:
        by[l["vat"]] = by.get(l["vat"], 0) + l["qty"] * l["unit_price"]
    breakdown = [{"rate": k, "ht": r2(v), "vat": r2(v * k / 100)} for k, v in sorted(by.items())]
    ht, vat = r2(sum(b["ht"] for b in breakdown)), r2(sum(b["vat"] for b in breakdown))
    return {"vat_breakdown": breakdown, "total_ht": ht, "total_vat": vat, "total_ttc": r2(ht + vat)}


def hist(ctx: Ctx, action: str, detail: str = "") -> dict:
    return {"at": now_iso(), "by": ctx.member.get("name"), "action": action, "detail": detail}


async def event_log(ctx: Ctx, event_id: str, action: str, detail: str) -> None:
    await db.events.update_one(ctx.q({"id": event_id}), {"$push": {"history": {"$each": [hist(ctx, action, detail)], "$slice": -300}}})


async def next_number(ctx: Ctx, kind: str, prefix: str) -> str:
    year = today()[:4]
    r = await db.counters.find_one_and_update({"org_id": ctx.org_id, "key": f"{kind}-{year}"}, {"$inc": {"seq": 1}},
                                              upsert=True, return_document=ReturnDocument.AFTER)
    return f"{prefix}-{year}-{r['seq']:04d}"


def quote_writer(ctx: Ctx) -> None:
    if not (ctx.can("finance:write") or ctx.can("events:write")):
        raise HTTPException(403, "Action non autorisée pour votre rôle")


@router.post("/{coll}/{did}/share/revoke")
async def revoke_share(coll: Literal["quotes", "invoices"], did: str, ctx: Ctx = Depends(need("finance:read"))):
    """Renvoyer un nouveau lien : l'ancien ne répond plus."""
    if ctx.role not in ("admin", "gerant"):
        raise HTTPException(403, "Réservé à l'administrateur et au gérant")
    d = await ctx.get(coll, did)
    token = await ensure_link(coll, d, renew=True)
    await audit(ctx.org_id, ctx.member, "share_link_revoked", d.get("number", ""))
    return {"token": token}


# ---------- Quotes ----------
class LineIn(BaseModel):
    label: str = Field(min_length=1, max_length=300)
    description: str = Field("", max_length=600)
    qty: float = Field(gt=0)
    unit_price: float
    vat: float = Field(ge=0, le=100)
    equipment_id: str = Field("", max_length=64)
    pack_id: str = Field("", max_length=64)
    kind: str = Field("service", max_length=12)
    unit: str = Field("", max_length=20)
    uom: str = Field("", max_length=12)


class QuoteIn(BaseModel):
    lines: List[LineIn] = Field(min_length=1)
    deposit_percent: float = Field(ge=0, lt=100)
    language: str = Field("", max_length=10)
    valid_until: str = ""
    notes: str = Field("", max_length=2000)


class QuoteStatusIn(BaseModel):
    status: str


@router.get("/quotes")
async def list_quotes(ctx: Ctx = Depends(need("finance:read")), event_id: str = ""):
    rows = await ctx.list("quotes", {"event_id": event_id} if event_id else {}, sort=[("created_at", -1)], limit=50000)
    crm = {i for o in await ctx.list("opportunities", {"quote_ids": {"$exists": True, "$ne": []}}, limit=50000) for i in o.get("quote_ids") or []}
    for q in rows:
        q["created_from"] = q.get("created_from") or ("crm" if q["id"] in crm else "devis" if q.get("origin") == "direct" else "evenement")
    return rows


@router.post("/events/{eid}/quotes")
async def create_quote(eid: str, ctx: Ctx = Depends(need("finance:read"))):
    quote_writer(ctx)
    ev = await ctx.get("events", eid)
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    eqs = {e["id"]: e for e in await ctx.list("equipment")}
    vat = org.get("default_vat", 20)
    days = ev.get("rental_days", 1)
    c = await db.contacts.find_one(ctx.q({"id": ev.get("client_id")}), {"_id": 0}) if ev.get("client_id") else None
    lang = clean_lang(ev.get("language") or (c or {}).get("language"))
    lines = [{"label": p["title"], "description": "", "qty": 1, "unit_price": p.get("price", 0), "vat": vat, "equipment_id": ""}
             for p in ev.get("prestations", [])]
    for l in ev.get("equipment", []):
        eq = eqs.get(l["equipment_id"]) or {}
        sec = l.get("entered_uom") == "secondary" and l.get("entered_qty") and eq.get("secondary_uom")
        total = (l.get("price_day") or 0) * days * l["qty"]
        lines.append({"label": f"{eq.get('ref', '')} {pick(eq, 'name', lang) or 'Matériel'}".strip(), "description": tr("rental_days", lang, n=days),
                      "qty": l["entered_qty"] if sec else l["qty"], "unit_price": r2(total / l["entered_qty"]) if sec else r2((l.get("price_day") or 0) * days), "vat": vat,
                      "equipment_id": l["equipment_id"], "unit": eq["secondary_uom"] if sec else "", "uom": "secondary" if sec else ""})
    client = {"name": contact_name(c), "address": c.get("address", ""), "city": c.get("city", ""), "email": c.get("email", "")} if c else {"name": ""}
    day = today()
    doc = await ctx.insert("quotes", {
        "number": await next_number(ctx, "quote", org.get("quote_prefix") or "DEV"), "event_id": eid, "event_code": ev["code"],
        "event_title": ev["title"], "event_date": ev["start"][:10], "client_id": ev.get("client_id", ""), "client": client,
        "status": "brouillon", "date": day, "valid_until": plus_days(day, 30), "lines": lines, "created_from": "evenement",
        "deposit_percent": org.get("deposit_percent", 30), "notes": "", "language": lang, **totals(lines),
        "history": [hist(ctx, "Création", "Devis créé depuis l'événement")]})
    await event_log(ctx, eid, "Devis", f"Devis {doc['number']} créé")
    return doc


@router.get("/quotes/{qid}")
async def get_quote(qid: str, ctx: Ctx = Depends(need("finance:read"))):
    return await ctx.get("quotes", qid)


@router.post("/quotes/{qid}/share")
async def share_quote(qid: str, ctx: Ctx = Depends(need("finance:read"))):
    q = await ctx.get("quotes", qid)
    return {"token": await ensure_link("quotes", q)}


async def _editable_quote(ctx: Ctx, qid: str) -> dict:
    q = await ctx.get("quotes", qid)
    if q.get("active") is False:
        raise HTTPException(400, "Ancienne version du devis : consultable uniquement")
    if await db.invoices.find_one(ctx.q({"quote_id": qid})):
        raise HTTPException(400, "Ce devis a déjà été facturé : il ne peut plus être modifié")
    if (q.get("signature") or {}).get("status") in ("ongoing", "done"):
        raise HTTPException(400, "Ce devis est en cours de signature ou déjà signé : annulez la signature en cours, ou créez une nouvelle version (V2) pour le modifier")
    return q


@router.put("/quotes/{qid}")
async def update_quote(qid: str, body: QuoteIn, ctx: Ctx = Depends(need("finance:read"))):
    quote_writer(ctx)
    q = await _editable_quote(ctx, qid)
    if q["status"] not in OPEN_STATUSES:
        raise HTTPException(400, "Seul un devis en brouillon ou envoyé peut être modifié")
    data = body.model_dump()
    data["language"] = clean_lang(data["language"] or q.get("language"))
    await db.quotes.update_one(ctx.q({"id": qid}), {"$set": {**data, **totals(data["lines"]), "blocks": None, "updated_at": now_iso()},
                                                     "$push": {"history": hist(ctx, "Modification", "Lignes / conditions")}})
    return await ctx.get("quotes", qid)


@router.post("/quotes/{qid}/status")
async def quote_status(qid: str, body: QuoteStatusIn, ctx: Ctx = Depends(need("finance:read"))):
    quote_writer(ctx)
    if body.status not in QUOTE_STATUSES:
        raise HTTPException(400, "Statut inconnu")
    q = await _editable_quote(ctx, qid)
    if body.status == "accepte" and await db.quotes.find_one(ctx.q({"$or": [{"id": q.get("root_id") or q["id"]}, {"root_id": q.get("root_id") or q["id"]}], "status": "accepte", "id": {"$ne": qid}})):
        raise HTTPException(409, "Une autre version de ce devis est déjà acceptée")
    if q["status"] != body.status:
        await db.quotes.update_one(ctx.q({"id": qid}), {"$set": {"status": body.status, "updated_at": now_iso()},
                                                         "$push": {"history": hist(ctx, "Statut", f"{q['status']} → {body.status}")}})
        await event_log(ctx, q["event_id"], "Devis", f"Devis {q['number']} : {body.status}")
        from routes_quotes import on_accept, on_sent
        if body.status == "accepte":
            await on_accept(ctx.org_id, qid, ctx.member.get("name"))
        elif body.status == "envoye":
            await on_sent(ctx.org_id, q["event_id"])
        import routes_quote_sync
        await routes_quote_sync.recalc_event(ctx.org_id, q["event_id"], ctx.member.get("name"))
        if body.status in ("refuse", "expire"):
            import routes_dj_coverage
            await routes_dj_coverage.on_quote_closed(ctx.org_id, q)
    return await ctx.get("quotes", qid)


# ---------- Invoices ----------
class InvoiceFromQuote(BaseModel):
    kind: str


class PaymentIn(BaseModel):
    amount: float = Field(gt=0)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    method: str = "virement"
    reference: str = Field("", max_length=120)


async def sync_event(ctx: Ctx, event_id: str) -> None:
    invs = await ctx.list("invoices", {"event_id": event_id})
    live = [i for i in invs if i["status"] != "annulee"]
    await db.events.update_one(ctx.q({"id": event_id}), {"$set": {
        "deposit_paid": r2(sum(i["paid_amount"] for i in invs if i["kind"] == "acompte")),
        "invoice_paid": any(i["kind"] == "solde" for i in live) and all(i["status"] == "payee" for i in live),
        "updated_at": now_iso()}})


@router.get("/invoices")
async def list_invoices(ctx: Ctx = Depends(need("finance:read")), event_id: str = ""):
    return await ctx.list("invoices", {"event_id": event_id} if event_id else {}, sort=[("created_at", -1)])


@router.post("/quotes/{qid}/invoice")
async def quote_to_invoice(qid: str, body: InvoiceFromQuote, ctx: Ctx = Depends(need("finance:write"))):
    if body.kind not in ("acompte", "solde"):
        raise HTTPException(400, "Type de facture inconnu")
    q = await ctx.get("quotes", qid)
    if q["status"] == "refuse":
        raise HTTPException(400, "Un devis refusé ne peut pas être facturé")
    existing = await ctx.list("invoices", {"quote_id": qid})
    kinds = {i["kind"] for i in existing}
    if "solde" in kinds:
        raise HTTPException(409, "La facture de solde existe déjà pour ce devis")
    if body.kind in kinds:
        raise HTTPException(409, "La facture d'acompte existe déjà pour ce devis")
    pct = q.get("deposit_percent", 0)
    lang = q.get("language")
    if body.kind == "acompte":
        if pct <= 0:
            raise HTTPException(400, "Aucun acompte n'est prévu sur ce devis")
        lines = [{"label": tr("deposit_line", lang, pct=f"{pct:g}", n=q["number"]), "description": tr("deposit_base", lang, ht=money(b["ht"], lang), rate=f"{b['rate']:g}"),
                  "qty": 1, "unit_price": r2(b["ht"] * pct / 100), "vat": b["rate"]} for b in q["vat_breakdown"] if b["ht"]]
    else:
        lines = [dict(l) for l in q["lines"]]
        for inv in existing:
            lines += [{"label": tr("deposit_done", lang, n=inv["number"]), "description": "", "qty": 1,
                       "unit_price": -l["unit_price"], "vat": l["vat"]} for l in inv["lines"]]
    t = totals(lines)
    if t["total_ttc"] <= 0:
        raise HTTPException(400, "Le montant à facturer est nul")
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    day = today()
    try:
        doc = await ctx.insert("invoices", {
            "number": "", "kind": body.kind, "quote_id": qid, "quote_number": q["number"], "event_id": q["event_id"],
            "event_code": q["event_code"], "event_title": q["event_title"], "event_date": q.get("event_date", ""),
            "client_id": q.get("client_id", ""), "client": q["client"], "language": clean_lang(lang), "status": "emise", "date": day,
            "due_date": plus_days(day, 15), "lines": lines, **t, "payments": [], "paid_amount": 0, "balance_due": t["total_ttc"],
            "notes": q.get("notes", ""), "history": [hist(ctx, "Émission", f"Facture issue du devis {q['number']}")]})
    except DuplicateKeyError:
        raise HTTPException(409, "Cette facture existe déjà pour ce devis")
    number = await next_number(ctx, "invoice", org.get("invoice_prefix") or "FAC")
    await db.invoices.update_one(ctx.q({"id": doc["id"]}), {"$set": {"number": number}})
    if q["status"] != "accepte":
        await db.quotes.update_one(ctx.q({"id": qid}), {"$set": {"status": "accepte"},
                                                         "$push": {"history": hist(ctx, "Statut", f"Accepté (facture {number})")}})
        from routes_quotes import on_accept
        await on_accept(ctx.org_id, qid, ctx.member.get("name"))
    await event_log(ctx, q["event_id"], "Facture", f"Facture {'d’acompte' if body.kind == 'acompte' else 'de solde'} {number} émise")
    await sync_event(ctx, q["event_id"])
    return await ctx.get("invoices", doc["id"])


@router.post("/invoices/{iid}/credit-note")
async def credit_note(iid: str, ctx: Ctx = Depends(need("finance:write"))):
    """Une facture émise ne se supprime pas : l'avoir l'annule et garde la numérotation continue."""
    inv = await ctx.get("invoices", iid)
    if inv["kind"].startswith("avoir") or inv["status"] == "annulee":
        raise HTTPException(409, "Cette facture est déjà annulée par un avoir")
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    lines = [{**l, "unit_price": -l["unit_price"]} for l in inv["lines"]]
    try:
        doc = await ctx.insert("invoices", {**{k: inv.get(k, "") for k in ("quote_id", "quote_number", "event_id", "event_code", "event_title", "event_date", "client_id", "client", "language")},
                                            "number": "", "kind": "avoir_" + inv["kind"], "credit_of": iid, "status": "annulee", "date": today(), "due_date": today(), "lines": lines, **totals(lines),
                                            "payments": [], "paid_amount": 0, "balance_due": 0, "notes": f"Avoir annulant la facture {inv['number']}", "history": [hist(ctx, "Émission", f"Avoir sur {inv['number']}")]})
    except DuplicateKeyError:
        raise HTTPException(409, "Un avoir existe déjà pour cette facture")
    number = await next_number(ctx, "credit", "AV")
    await db.invoices.update_one(ctx.q({"id": doc["id"]}), {"$set": {"number": number}})
    await db.invoices.update_one(ctx.q({"id": iid}), {"$set": {"status": "annulee", "balance_due": 0, "credit_note_number": number, "updated_at": now_iso()}, "$push": {"history": hist(ctx, "Annulation", f"Avoir {number}")}})
    await event_log(ctx, inv["event_id"], "Facture", f"Avoir {number} émis : facture {inv['number']} annulée")
    await sync_event(ctx, inv["event_id"])
    return await ctx.get("invoices", doc["id"])


async def _set_payments(ctx: Ctx, inv: dict, payments: list, label: str) -> dict:
    paid = r2(sum(p["amount"] for p in payments))
    balance = r2(inv["total_ttc"] - paid)
    status = "payee" if balance <= 0 else "partielle" if paid > 0 else "emise"
    r = await db.invoices.find_one_and_update(
        ctx.q({"id": inv["id"], "paid_amount": inv["paid_amount"]}),
        {"$set": {"payments": payments, "paid_amount": paid, "balance_due": max(0, balance), "status": status, "updated_at": now_iso()},
         "$push": {"history": hist(ctx, "Paiement", label)}}, projection={"_id": 0}, return_document=ReturnDocument.AFTER)
    if r is None:
        raise HTTPException(409, "La facture vient d'être modifiée, réessayez")
    await sync_event(ctx, inv["event_id"])
    return r


@router.post("/invoices/{iid}/payments")
async def add_payment(iid: str, body: PaymentIn, ctx: Ctx = Depends(need("finance:write"))):
    inv = await ctx.get("invoices", iid)
    if body.amount > inv["balance_due"] + 0.001:
        raise HTTPException(400, f"Le paiement dépasse le reste à payer ({inv['balance_due']:.2f} €)")
    p = {"id": new_id(), **body.model_dump(), "amount": r2(body.amount), "by": ctx.member.get("name"), "at": now_iso()}
    r = await _set_payments(ctx, inv, inv["payments"] + [p], f"{p['amount']:.2f} € encaissés ({p['method']})")
    await event_log(ctx, inv["event_id"], "Paiement", f"{p['amount']:.2f} € sur {inv['number']}")
    return r


@router.delete("/invoices/{iid}/payments/{pid}")
async def remove_payment(iid: str, pid: str, ctx: Ctx = Depends(need("finance:write"))):
    inv = await ctx.get("invoices", iid)
    keep = [p for p in inv["payments"] if p["id"] != pid]
    if len(keep) == len(inv["payments"]):
        raise HTTPException(404, "Introuvable")
    return await _set_payments(ctx, inv, keep, "Paiement annulé")


# ---------- PDF ----------
def _fonts() -> tuple:
    base = "/usr/share/fonts/truetype/liberation/LiberationSans"
    if os.path.exists(base + "-Regular.ttf") and os.path.exists(base + "-Bold.ttf"):
        if "LibSans" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("LibSans", base + "-Regular.ttf"))
            pdfmetrics.registerFont(TTFont("LibSans-Bold", base + "-Bold.ttf"))
        return "LibSans", "LibSans-Bold"
    return "Helvetica", "Helvetica-Bold"


def eur(x: float) -> str:
    return f"{x:,.2f}".replace(",", " ").replace(".", ",") + " €"


def fr_date(s: str) -> str:
    return f"{s[8:10]}/{s[5:7]}/{s[:4]}" if s and len(s) >= 10 else "—"


class AcceptBox(Flowable):
    def __init__(self, out: dict, font: str, bold: str):
        super().__init__()
        self.out, self.font, self.bold = out, font, bold
        self.height = 30 + 44 * len(out["labels"]) + 100

    def wrap(self, aw, ah):
        self.width = aw
        return aw, self.height

    def draw(self):
        c = self.canv
        x0, y0 = c.absolutePosition(0, 0)
        y, fields = self.height - 14, []
        c.setFont(self.bold, 11)
        c.drawString(0, y, tr("accept_title", self.out.get("language")))
        y -= 26
        c.setFont(self.font, 9)
        c.setStrokeColorRGB(0.75, 0.75, 0.75)
        for label in self.out["labels"]:
            c.drawString(0, y, f"{label} :")
            c.line(0, y - 30, 380, y - 30)
            fields.append({"label": label, "x": int(x0) + 2, "y": int(A4[1] - (y0 + y - 5))})
            y -= 44
        c.drawString(0, y, tr("client_signature", self.out.get("language")) + " :")
        c.rect(0, y - 80, 200, 72)
        self.out.update(page=c.getPageNumber(), fields=fields,
                        signature={"x": int(x0) + 4, "y": int(A4[1] - (y0 + y - 10)), "width": 190, "height": 66})


def render_pdf(doc: dict, org: dict, title: str, products: list | None = None, accept: dict | None = None) -> bytes:
    F, FB = _fonts()
    lg = doc.get("language")
    en = doc_lang(lg) == "en"
    eur = lambda x: money(x, lg)  # noqa: E731
    fr_date = lambda s: fmt_date(s, lg)  # noqa: E731
    ink, grey, line = colors.HexColor("#171717"), colors.HexColor("#525252"), colors.HexColor("#E5E5E5")
    st = ParagraphStyle("b", fontName=F, fontSize=9, leading=12.5, textColor=ink)
    sm = ParagraphStyle("s", parent=st, fontSize=8.5, leading=11.5, textColor=colors.HexColor("#404040"))
    bold = ParagraphStyle("bo", parent=st, fontName=FB)
    right = ParagraphStyle("r", parent=st, alignment=TA_RIGHT)
    right_sm = ParagraphStyle("rs", parent=sm, alignment=TA_RIGHT)
    big = ParagraphStyle("h", parent=st, fontName=FB, fontSize=18, leading=22)
    big_r = ParagraphStyle("hr", parent=big, alignment=TA_RIGHT)

    def P(t, s=st):
        return Paragraph(escape(str(t)).replace("\n", "<br/>"), s)

    buf = io.BytesIO()
    W = A4[0] - 36 * mm
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=20 * mm,
                            title=f"{title} {doc['number']}", author=org.get("name", ""))
    is_inv = "kind" in doc
    org_lines = [org.get("address", ""), " ".join(filter(None, [org.get("zip", ""), org.get("city", "")])), org.get("phone", ""), org.get("email", "")]
    meta = [f"{tr('date', lg)} : {fr_date(doc['date'])}"]
    meta.append(f"{tr('due', lg)} : {fr_date(doc['due_date'])}" if is_inv else f"{tr('valid_until', lg)} : {fr_date(doc.get('valid_until', ''))}")
    if is_inv:
        meta.append(f"{tr('quote_ref', lg)} : {doc['quote_number']}")
    c = doc.get("client") or {}
    story = [
        Table([[[P(org.get("name", ""), big)] + [P(x, sm) for x in org_lines if x],
                [P(title, big_r), P(f"{tr('number', lg)} {doc['number']}", ParagraphStyle("n", parent=right, fontName=FB))] + [P(m, right_sm) for m in meta]]],
              colWidths=[W * 0.55, W * 0.45], style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                                                 ("RIGHTPADDING", (0, 0), (-1, -1), 0)])),
        Spacer(1, 9 * mm),
        Table([[[P(tr("event", lg), sm), P(doc.get("event_title", ""), bold)] + ([P(doc["venue_line"], st)] if doc.get("venue_line") else []) + [P(f"{doc.get('event_code', '')} · {fr_date(doc.get('event_date', ''))}", sm)],
                [P("CLIENT", sm), P(c.get("name") or "—", bold)] + [P(x, sm) for x in (c.get("address"), c.get("city"), c.get("email")) if x]]],
              colWidths=[W * 0.5, W * 0.5], style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (0, 0), 0.6, line),
                                                               ("BOX", (1, 0), (1, 0), 0.6, line), ("TOPPADDING", (0, 0), (-1, -1), 8),
                                                               ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 10)])),
        Spacer(1, 8 * mm),
    ]
    story = (doc.get("_pre") or []) + story
    for x in doc.get("dates_lines") or []:
        story.append(P(x, sm))
    if doc.get("dates_lines"):
        story.append(Spacer(1, 5 * mm))
    rows = [[P(h, sm) if i == 0 else P(h, right_sm) for i, h in enumerate([tr(k, lg) for k in ("designation", "qty", "unit_price", "vat", "line_total")])]]
    for l in doc["lines"]:
        if l.get("kind") == "title":
            rows.append([P(l["label"], ParagraphStyle("t", parent=bold, fontSize=10.5)), "", "", "", ""])
            continue
        if l.get("kind") in ("text", "subtotal") or l.get("hide_price"):
            first = [P(l["label"], sm if l.get("kind") == "text" else bold)] + ([P(l["description"], sm)] if l.get("description") and l.get("kind") != "text" else [])
            rows.append([first, P(f"{l['qty']:g} {l.get('unit') or ''}".strip(), right) if l.get("hide_price") else "", "", "", P(eur(l["amount"]), right) if l.get("kind") == "subtotal" else ""])
            continue
        cell = [P(l["label"], bold)] + ([P(l["description"], sm)] if l.get("description") else [])
        rows.append([cell, P(f"{l['qty']:g} {l.get('unit') or ''}".strip(), right), P(eur(l["unit_price"]), right), P(f"{l['vat']:g} %", right), P(eur(l["qty"] * l["unit_price"]), right)])
    story.append(Table(rows, colWidths=[W * 0.46, W * 0.09, W * 0.17, W * 0.1, W * 0.18], repeatRows=1, style=TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 0.8, ink), ("LINEBELOW", (0, 1), (-1, -1), 0.5, line),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 0)])))
    story.append(Spacer(1, 6 * mm))
    tot = [[P(tr("total_ht", lg)), P(eur(doc["total_ht"]), right)]]
    tot += [[P(tr("vat_on", lg, rate=f"{b['rate']:g}", base=eur(b["ht"])), sm), P(eur(b["vat"]), right)] for b in doc["vat_breakdown"]]
    tot.append([P(tr("total_ttc", lg), bold), P(eur(doc["total_ttc"]), ParagraphStyle("rb", parent=right, fontName=FB, fontSize=11))])
    ttc_row = len(tot) - 1
    if is_inv:
        tot += [[P(tr("paid", lg)), P(eur(doc["paid_amount"]), right)], [P(tr("balance", lg), bold), P(eur(doc["balance_due"]), ParagraphStyle("rb2", parent=right, fontName=FB))]]
    story.append(Table(tot, colWidths=[W * 0.3, W * 0.2], hAlign="RIGHT", style=TableStyle([
        ("LINEABOVE", (0, ttc_row), (-1, ttc_row), 0.8, ink), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (0, -1), 0), ("RIGHTPADDING", (-1, 0), (-1, -1), 0)])))
    story.append(Spacer(1, 8 * mm))
    if doc.get("notes"):
        story += [P(doc["notes"]), Spacer(1, 4 * mm)]
    story += doc.get("_post") or []
    end, dep = [], doc.get("deposit_percent") or 0
    if not is_inv and not doc.get("_closing_schedule") and doc.get("price_display") != "none":
        end.append(P(tr("payment_terms", lg), bold))
        if dep:
            end.append(P(f"{tr('deposit', lg, pct=f'{dep:g}')} : {eur(r2(doc['total_ttc'] * dep / 100))}"))
        end.append(P(f"{tr('balance_line', lg)} : {eur(r2(doc['total_ttc'] * (100 - dep) / 100))} — {tr('balance_due_days', lg, n=org.get('balance_days') or 15)}"))
    if org.get("payment_terms"):
        end += ([] if end else [P(tr("payment_terms", lg), bold)]) + [P(pick(org, "payment_terms", lg), sm)]
    if org.get("iban"):
        iban = re.sub(r"\s", "", org["iban"])
        end.append(P("IBAN : " + " ".join(iban[i:i + 4] for i in range(0, len(iban), 4)) + (f" — BIC : {org['bic']}" if org.get("bic") else ""), sm))
    end.append(Spacer(1, 3 * mm))
    custom = pick(org, "legal_mentions", lg)
    import routes_titles
    cg = routes_titles.cgv(org, lg or "fr-FR")
    annex = org.get("terms_annex") is not False and not is_inv
    notes = [tr("cgv_apply", lg) if annex and (cg["text"] or cg["file"]) else "", "" if re.fullmatch(r"\s*\[.*\]\s*", custom or "[]", re.S) else custom]
    end += [P(x, sm) for x in notes if x]
    if accept is not None:
        end.append(AcceptBox(accept, F, FB))
    elif not is_inv:
        end += [Spacer(1, 5 * mm), P(tr("sign_title", lg), bold), Spacer(1, 2 * mm),
                Table([[P(tr("sign_date", lg), sm), P(tr("sign_mention", lg), sm)]], colWidths=[W * 0.3, W * 0.7], rowHeights=[40 * mm], style=TableStyle([
                    ("BOX", (0, 0), (-1, -1), 0.6, line), ("LINEAFTER", (0, 0), (0, 0), 0.6, line), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))]
    story.append(KeepTogether(end))
    if annex and cg["text"] and not cg["file"]:
        story += [PageBreak(), P(tr("terms", lg), big), Spacer(1, 4 * mm), P(cg["text"], sm), Spacer(1, 6 * mm)]
    if products:
        story += [PageBreak(), P(tr("products", lg), big), Spacer(1, 6 * mm)]
        for p in products:
            img = ""
            if p.get("image"):
                try:
                    iw, ih = ImageReader(io.BytesIO(p["image"])).getSize()
                    k = min(60 * mm / iw, 45 * mm / ih)
                    img = Image(io.BytesIO(p["image"]), width=iw * k, height=ih * k)
                except Exception:
                    img = ""
            story.append(KeepTogether([Table([[img, [P(p["name"], bold), P(p["ref"], sm), Spacer(1, 2 * mm), P(p.get("description", ""))]]],
                                             colWidths=[W * 0.38, W * 0.62], style=TableStyle([
                                                 ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.6, line),
                                                 ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                                                 ("LEFTPADDING", (0, 0), (-1, -1), 10)])), Spacer(1, 5 * mm)]))
    siret = re.sub(r"\D", "", org.get("siret") or "")
    siret = f"{siret[:3]} {siret[3:6]} {siret[6:9]} {siret[9:]}" if len(siret) == 14 else org.get("siret") or ""
    legal = " — ".join(x for x in (org.get("legal_name") or org.get("name"), f"SIRET {siret}" if siret else "", f"{tr('vat', lg)} {org['vat_number']}" if org.get("vat_number") else "") if x)

    class Numbered(Canvas):
        def __init__(self, *a, **k):
            super().__init__(*a, **{**k, "pdfVersion": (1, 7)})
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            for s in self._pages:
                self.__dict__.update(s)
                self.setFont(F, 7)
                self.setFillColor(grey)
                self.drawCentredString(A4[0] / 2, 11 * mm, legal)
                self.drawRightString(A4[0] - 18 * mm, 11 * mm, f"{tr('page', lg)} {self._pageNumber} / {len(self._pages)}")
                super().showPage()
            super().save()

    pdf.build(story, canvasmaker=Numbered)
    return buf.getvalue()


async def quote_pdf_bytes(doc: dict, org: dict, accept: dict | None = None) -> bytes:
    from routes_quote_blocks import pdf_doc
    doc = await pdf_doc(doc)
    import routes_titles
    doc = await routes_titles.client_doc(doc, org)
    from routes_quote_docs import decorate
    doc, org = await decorate(doc, org)
    if doc.get("show_on_site"):
        from routes_stock import on_site_note
        doc = await on_site_note(doc)
    products = await quote_products(doc)
    for p in products:
        got = await file_bytes(doc["org_id"], p["photo"])
        p["image"] = got[0] if got and got[1].startswith("image/") else None
    out = render_pdf(doc, org, tr("quote", doc.get("language")), products, accept)
    import routes_titles
    cg = routes_titles.cgv(org, doc.get("language") or "fr-FR")
    got = await file_bytes(doc["org_id"], f"file:{cg['file']}") if cg["file"] and org.get("terms_annex") is not False else None
    if got:
        import io
        from pypdf import PdfWriter
        w = PdfWriter()
        w.append(io.BytesIO(out))
        w.append(io.BytesIO(got[0]))
        buf = io.BytesIO()
        w.write(buf)
        out = buf.getvalue()
    return out


def invoice_pdf_bytes(doc: dict, org: dict) -> bytes:
    return render_pdf(doc, org, tr("credit_note" if doc["kind"].startswith("avoir") else "deposit_invoice" if doc["kind"] == "acompte" else "invoice", doc.get("language")))


async def _pdf(ctx: Ctx, coll: str, did: str) -> Response:
    doc = await ctx.get(coll, did)
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    data = await quote_pdf_bytes(doc, org) if coll == "quotes" else invoice_pdf_bytes(doc, org)
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{doc["number"]}.pdf"'})


@router.get("/quotes/{qid}/pdf")
async def quote_pdf(qid: str, ctx: Ctx = Depends(need("finance:read"))):
    return await _pdf(ctx, "quotes", qid)


@router.get("/invoices/{iid}/pdf")
async def invoice_pdf(iid: str, ctx: Ctx = Depends(need("finance:read"))):
    return await _pdf(ctx, "invoices", iid)


# ---------- Vehicles ----------
class VehicleIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    plate: str = Field("", max_length=20)
    capacity_kg: float = Field(0, ge=0)
    volume_m3: float = Field(0, ge=0)
    active: bool = True
    type: str = Field("utilitaire", max_length=30)
    licence_required: str = Field("B", max_length=3)
    tailgate: bool = False
    length_m: float = Field(0, ge=0)
    height_m: float = Field(0, ge=0)
    seats: int = Field(3, ge=0)
    cost_km: float = Field(0, ge=0)
    ownership: str = Field("propre", max_length=20)
    ct_due: str = ""
    insurance_due: str = ""
    service_due: str = ""
    unavailabilities: List[dict] = []
    rental_start: str = ""
    rental_end: str = ""
    rental_cost: float = Field(0, ge=0)


@router.get("/vehicles")
async def list_vehicles(ctx: Ctx = Depends(need("events:read"))):
    return await ctx.list("vehicles", sort=[("name", 1)])


@router.post("/vehicles")
async def create_vehicle(body: VehicleIn, ctx: Ctx = Depends(need("catalog:write"))):
    return await ctx.insert("vehicles", body.model_dump())


@router.put("/vehicles/{vid}")
async def update_vehicle(vid: str, body: VehicleIn, ctx: Ctx = Depends(need("catalog:write"))):
    return await ctx.update("vehicles", vid, body.model_dump())


# ---------- Chargement du jour ----------
def _lines(ev: dict, eqs: dict, old: list | None = None) -> list:
    prev = {l["equipment_id"]: l for l in (old or [])}
    out = []
    for l in ev.get("equipment", []):
        eq, p = eqs.get(l["equipment_id"]) or {}, prev.get(l["equipment_id"], {})
        loaded = min(p.get("loaded_qty", 0), l["qty"])
        out.append({"equipment_id": l["equipment_id"], "ref": eq.get("ref", "?"), "name": eq.get("name", "Matériel supprimé"),
                    "category": eq.get("category", ""), "weight_kg": eq.get("weight_kg", 0), "qty": l["qty"], "loaded_qty": loaded,
                    "missing_qty": min(p.get("missing_qty", 0), l["qty"] - loaded), "note": p.get("note", ""),
                    "checked_by": p.get("checked_by", "")})
    return out


async def sync_loadings(org_id: str, day: str, scope: dict | None = None) -> list:
    evs = await db.events.find({**(scope or {}), "org_id": org_id, "status": {"$in": LOAD_STATUSES},
                                "setup_start": {"$regex": f"^{re.escape(day)}"}}, {"_id": 0}).sort("setup_start", 1).to_list(500)
    if not evs:
        return []
    eqs = {e["id"]: e for e in await db.equipment.find({"org_id": org_id}, {"_id": 0}).to_list(5000)}
    venues = {v["id"]: v for v in await db.venues.find({"org_id": org_id}, {"_id": 0}).to_list(5000)}
    out = []
    for ev in evs:
        key = {"org_id": org_id, "day": day, "event_id": ev["id"]}
        head = {"event_code": ev["code"], "event_title": ev["title"], "departure": ev["setup_start"], "vehicle_id": ev.get("vehicle_id") or ""}
        cur = await db.loadings.find_one(key, {"_id": 0})
        if cur is None:
            cur = {**key, **head, "id": new_id(), "status": "a_charger", "lines": _lines(ev, eqs), "generated_at": now_iso()}
            try:
                await db.loadings.insert_one(dict(cur))
            except DuplicateKeyError:
                cur = await db.loadings.find_one(key, {"_id": 0})
        elif cur["status"] != "charge":
            new = {**head, "lines": _lines(ev, eqs, cur["lines"])}
            if any(cur.get(k) != v for k, v in new.items()):
                await db.loadings.update_one(key, {"$set": new})
                cur.update(new)
        v = venues.get(ev.get("venue_id")) or {}
        import routes_reuse
        out.append({**cur, "venue_name": v.get("name", ""), "venue_city": v.get("city", ""), "transfers": await routes_reuse.transfers_of(org_id, ev["id"])})
    return out


def _day(day: str) -> str:
    try:
        return datetime.strptime(day, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Date invalide (AAAA-MM-JJ)")


@router.get("/loading")
async def get_loading(ctx: Ctx = Depends(need("events:read")), day: str = ""):
    d = _day(day) if day else today()
    return {"day": d, "today": today(), "loadings": await sync_loadings(ctx.org_id, d, ctx.event_scope()),
            "vehicles": await ctx.list("vehicles", sort=[("name", 1)])}


async def _loading(ctx: Ctx, lid: str) -> dict:
    lo = await ctx.get("loadings", lid)
    await ctx.get("events", lo["event_id"], ctx.event_scope())
    return lo


class LoadLineIn(BaseModel):
    loaded_qty: float = Field(ge=0)
    missing_qty: float = Field(0, ge=0)
    note: str = Field("", max_length=300)


@router.patch("/loading/{lid}/lines/{equipment_id}")
async def check_line(lid: str, equipment_id: str, body: LoadLineIn, ctx: Ctx = Depends(need("events:read"))):
    lo = await _loading(ctx, lid)
    if lo["status"] == "charge":
        raise HTTPException(400, "Ce chargement est déjà validé")
    line = next((l for l in lo["lines"] if l["equipment_id"] == equipment_id), None)
    if line is None:
        raise HTTPException(404, "Introuvable")
    if body.loaded_qty + body.missing_qty > line["qty"]:
        raise HTTPException(400, f"Quantité supérieure à la quantité prévue ({line['qty']})")
    await db.loadings.update_one(ctx.q({"id": lid}), {"$set": {
        "lines.$[l].loaded_qty": body.loaded_qty, "lines.$[l].missing_qty": body.missing_qty,
        "lines.$[l].note": body.note if body.missing_qty else "", "lines.$[l].checked_by": ctx.member.get("name"),
        "status": "en_cours", "updated_at": now_iso()}}, array_filters=[{"l.equipment_id": equipment_id}])
    if body.missing_qty and body.missing_qty != line["missing_qty"]:
        await event_log(ctx, lo["event_id"], "Chargement", f"Manquant signalé : {body.missing_qty} × {line['name']}. {body.note}".strip())
    return await ctx.get("loadings", lid)


class LoadVehicleIn(BaseModel):
    vehicle_id: str = ""


@router.put("/loading/{lid}/vehicle")
async def set_vehicle(lid: str, body: LoadVehicleIn, ctx: Ctx = Depends(need("events:write"))):
    lo = await _loading(ctx, lid)
    if body.vehicle_id:
        await ctx.get("vehicles", body.vehicle_id)
    await db.events.update_one(ctx.q({"id": lo["event_id"]}), {"$set": {"vehicle_id": body.vehicle_id}})
    await db.loadings.update_one(ctx.q({"id": lid}), {"$set": {"vehicle_id": body.vehicle_id}})
    return await ctx.get("loadings", lid)


class LoadStatusIn(BaseModel):
    status: str


@router.post("/loading/{lid}/status")
async def loading_status(lid: str, body: LoadStatusIn, ctx: Ctx = Depends(need("events:read"))):
    lo = await _loading(ctx, lid)
    if body.status == "charge":
        if any(l["loaded_qty"] + l["missing_qty"] < l["qty"] for l in lo["lines"]):
            raise HTTPException(400, "Chaque ligne doit être chargée ou signalée manquante avant validation")
    elif body.status == "en_cours":
        if not ctx.can("events:write"):
            raise HTTPException(403, "Action non autorisée pour votre rôle")
    else:
        raise HTTPException(400, "Statut inconnu")
    if lo["status"] != body.status:
        await db.loadings.update_one(ctx.q({"id": lid}), {"$set": {"status": body.status, "validated_by": ctx.member.get("name"), "updated_at": now_iso()}})
        await event_log(ctx, lo["event_id"], "Chargement", "Chargement validé" if body.status == "charge" else "Chargement rouvert")
    return await ctx.get("loadings", lid)


async def loading_alerts(ctx: Ctx) -> list:
    rows = await ctx.list("loadings", {"day": {"$gte": today()}, "lines.missing_qty": {"$gt": 0}})
    return [{"type": "manquant", "severity": "danger", "event_id": r["event_id"], "title": f"Manquant au chargement : {l['name']}",
             "detail": f"{r['event_code']} · {r['event_title']} — {l['missing_qty']} sur {l['qty']} manquant(s). {l['note']}".strip()}
            for r in rows for l in r["lines"] if l["missing_qty"]]


async def generate_all(day: str) -> None:
    async for org in db.orgs.find({}, {"_id": 0, "id": 1}):
        await sync_loadings(org["id"], day)


async def cron_guard(request: Request, name: str) -> bool:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer ") or not hmac.compare_digest(auth[7:].encode(), os.environ["WEBHOOK_CRON_SECRET"].encode()):
        raise HTTPException(401, "Unauthorized")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid body")
    run_id = request.headers.get("x-webhook-id") or (body.get("run_id") if isinstance(body, dict) else None)
    if not isinstance(body, dict) or not run_id:
        raise HTTPException(400, "Invalid body")
    try:
        await db.cron_runs.insert_one({"_id": f"{name}:{run_id}", "at": now_iso()})
    except DuplicateKeyError:
        return False
    return True


@router.post("/cron/loading")
async def cron_loading(request: Request, bg: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    if not await cron_guard(request, "loading"):
        return {"ok": True, "duplicate": True}
    bg.add_task(tenants.for_each_org, partial(generate_all, today()), label="loading")
    return {"ok": True}
