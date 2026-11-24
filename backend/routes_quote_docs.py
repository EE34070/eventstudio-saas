"""Devis tour 2 : pages d'en-tête / clôture, gabarits de marque, versions destinataires, signature OTP, versionnage."""
import hashlib
import hmac
import io
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

import routes_quote_blocks as qb
import routes_stock as rs
from core import Ctx, db, need, new_id, now_iso
from emailer import mail_html, send_email
from i18n import fmt_date, money
from routes_billing import OPEN_STATUSES, _editable_quote, _fonts, hist, quote_pdf_bytes, quote_writer, r2, today, totals
from routes_files import _serve, file_bytes, store_bytes
from routes_main import contact_name

from core import check_expiry, ensure_link, link_doc, link_limit  # noqa: E402,F401
router = APIRouter(prefix="/api")
FIN = need("finance:read")
ORGW = need("org:write")
FIELDS = ["client.nom", "organisateur.nom", "evenement.titre", "evenement.date", "lieu.nom", "devis.numero", "devis.date_validite", "devis.total_ttc", "responsable.nom", "responsable.telephone", "societe.nom"]
SIGNABLE = ("envoye", "vu", "negociation")


class PBlock(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    type: Literal["title", "text", "image", "columns", "quote", "schedule"]
    text: str = Field("", max_length=8000)
    right: str = Field("", max_length=8000)
    image: str = Field("", max_length=300)
    mode: Literal["banner", "full"] = "banner"


class PageIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["header", "closing"]
    brand_id: str = ""
    blocks_fr: List[PBlock] = Field([], max_length=40)
    blocks_en: List[PBlock] = Field([], max_length=40)
    default_on: bool = False
    order: int = 0


class BrandIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    logo: str = Field("", max_length=300)
    color: str = Field("#171717", pattern=r"^#[0-9a-fA-F]{6}$")
    font: Literal["sans", "serif"] = "sans"
    legal_name: str = Field("", max_length=200)
    siret: str = Field("", max_length=40)
    vat_number: str = Field("", max_length=40)
    legal_mentions: str = Field("", max_length=4000)
    legal_mentions_en: str = Field("", max_length=4000)
    terms: str = Field("", max_length=40000)
    terms_en: str = Field("", max_length=40000)
    is_default: bool = False


def _b(type_: str, text: str = "", **kw) -> dict:
    return PBlock(id=new_id(), type=type_, text=text, **kw).model_dump()


async def migrate() -> None:
    await db.quotes.update_many({"version": {"$exists": False}}, [{"$set": {"version": 1, "root_id": "$id", "active": True}}])


async def ensure_defaults(org_id: str) -> None:
    org = await db.orgs.find_one({"id": org_id}, {"_id": 0}) or {}
    if not await db.brand_templates.find_one({"org_id": org_id}):
        await db.brand_templates.insert_one({"id": new_id(), "org_id": org_id, "created_at": now_iso(), **BrandIn(name=org.get("name") or "Marque principale", is_default=True).model_dump()})
    if not await db.document_pages.find_one({"org_id": org_id}):
        cover = "**{client.nom}**\n{evenement.date} · {lieu.nom}\n"
        await db.document_pages.insert_many([
            {"id": new_id(), "org_id": org_id, "created_at": now_iso(), **PageIn(name="Page de garde", kind="header", order=0, default_on=True).model_dump(),
             "blocks_fr": [_b("title", "{evenement.titre}"), _b("text", cover + "Devis {devis.numero} — valable jusqu'au {devis.date_validite}")],
             "blocks_en": [_b("title", "{evenement.titre}"), _b("text", cover + "Quote {devis.numero} — valid until {devis.date_validite}")]},
            {"id": new_id(), "org_id": org_id, "created_at": now_iso(), **PageIn(name="Conditions de paiement", kind="closing", order=0, default_on=True).model_dump(),
             "blocks_fr": [_b("title", "Conditions de paiement"), _b("schedule"), _b("text", "Votre contact : {responsable.nom} — {responsable.telephone}")],
             "blocks_en": [_b("title", "Payment terms"), _b("schedule"), _b("text", "Your contact: {responsable.nom} — {responsable.telephone}")]}])


# ---------- Gabarits de marque et bibliothèque de pages ----------
@router.get("/brand-templates")
async def list_brands(ctx: Ctx = Depends(FIN)):
    await ensure_defaults(ctx.org_id)
    return await ctx.list("brand_templates", sort=[("name", 1)])


async def _save_brand(ctx: Ctx, body: BrandIn, bid: str = "") -> dict:
    if body.is_default:
        await db.brand_templates.update_many(ctx.q({}), {"$set": {"is_default": False}})
    return await ctx.update("brand_templates", bid, body.model_dump()) if bid else await ctx.insert("brand_templates", body.model_dump())


@router.post("/brand-templates")
async def create_brand(body: BrandIn, ctx: Ctx = Depends(ORGW)):
    return await _save_brand(ctx, body)


@router.put("/brand-templates/{bid}")
async def update_brand(bid: str, body: BrandIn, ctx: Ctx = Depends(ORGW)):
    return await _save_brand(ctx, body, bid)


@router.delete("/brand-templates/{bid}")
async def delete_brand(bid: str, ctx: Ctx = Depends(ORGW)):
    if (await ctx.get("brand_templates", bid)).get("is_default"):
        raise HTTPException(400, "Le gabarit par défaut ne peut pas être supprimé")
    await ctx.delete("brand_templates", bid)
    return {"ok": True}


@router.get("/document-pages")
async def list_pages(ctx: Ctx = Depends(FIN)):
    await ensure_defaults(ctx.org_id)
    return {"pages": await ctx.list("document_pages", sort=[("kind", -1), ("order", 1), ("name", 1)]), "fields": FIELDS}


@router.post("/document-pages")
async def create_page(body: PageIn, ctx: Ctx = Depends(ORGW)):
    return await ctx.insert("document_pages", body.model_dump())


@router.put("/document-pages/{pid}")
async def update_page(pid: str, body: PageIn, ctx: Ctx = Depends(ORGW)):
    return await ctx.update("document_pages", pid, body.model_dump())


@router.delete("/document-pages/{pid}")
async def delete_page(pid: str, ctx: Ctx = Depends(ORGW)):
    await ctx.delete("document_pages", pid)
    return {"ok": True}


# ---------- Pages d'un devis ----------
async def field_values(q: dict, lg: str) -> dict:
    ev, v, _ = await qb._spaces(q["org_id"], q.get("event_id", ""))
    org = await db.orgs.find_one({"id": q["org_id"]}, {"_id": 0}) or {}
    pl = await db.contacts.find_one({"org_id": q["org_id"], "id": ev.get("planner_contact_id")}, {"_id": 0}) if ev.get("planner_contact_id") else None
    return {"client.nom": (q.get("client") or {}).get("name", ""), "organisateur.nom": contact_name(pl) if pl else "", "evenement.titre": await __import__("routes_titles").quote_title(q, ev), "evenement.date": fmt_date(q.get("event_date", ""), lg),
            "lieu.nom": (v or {}).get("name", ""), "devis.numero": q["number"], "devis.date_validite": fmt_date(q.get("valid_until", ""), lg), "devis.total_ttc": money(q.get("total_ttc", 0), lg),
            "responsable.nom": ((q.get("history") or [{}])[0].get("by") or ""), "responsable.telephone": org.get("phone", ""), "societe.nom": org.get("name", "")}


def fill(text: str, vals: dict) -> str:
    return re.sub(r"\{([a-z_.]+)\}", lambda m: str(vals.get(m.group(1), m.group(0))), text or "")


async def _brand(q: dict) -> dict:
    key = {"org_id": q["org_id"]}
    return (await db.brand_templates.find_one({**key, "id": q.get("brand_template_id")}, {"_id": 0}) if q.get("brand_template_id") else None) or await db.brand_templates.find_one({**key, "is_default": True}, {"_id": 0}) or {}


def _selection(q: dict, kind: str, tpls: dict, brand: dict) -> list:
    sel = q.get(f"{kind}_pages")
    return sel or []  # pages d'en-tête et de clôture désactivées par défaut : seulement si choisies sur le devis


async def resolved(q: dict, no_prices: bool = False) -> dict:
    lg = q.get("language") or "fr-FR"
    en = lg.startswith("en")
    tpls = {t["id"]: t async for t in db.document_pages.find({"org_id": q["org_id"]}, {"_id": 0})}
    brand, vals = await _brand(q), await field_values(q, lg)
    dep = q.get("deposit_percent") or 0
    sched = ([[f"{'Deposit on order' if en else 'Acompte à la commande'} ({dep:g} %)", money(r2(q["total_ttc"] * dep / 100), lg)]] if dep else []) + \
        [["Balance" if en else "Solde", money(r2(q["total_ttc"] * (100 - dep) / 100), lg)], ["Total incl. VAT" if en else "Total TTC", money(q["total_ttc"], lg)]]
    out = {"brand": brand}
    for kind in ("header", "closing"):
        pages, seen = [], set()
        for s in _selection(q, kind, tpls, brand):
            t = tpls.get(s["template_id"])
            if not s.get("enabled") or not (t or s.get("override")) or (t or {}).get("name", s["template_id"]) in seen:
                continue
            seen.add((t or {}).get("name", s["template_id"]))
            blocks = s.get("override") or (en and t.get("blocks_en")) or t["blocks_fr"]
            pages.append({"name": (t or {}).get("name", ""), "blocks": [{**b, "text": fill(b["text"], vals), "right": fill(b["right"], vals), **({"rows": sched} if b["type"] == "schedule" else {})}
                                                                     for b in blocks if not (no_prices and b["type"] == "schedule")]})
        out[kind] = pages
    return out


async def _flow(pages: list, brand: dict, org_id: str, pre: bool) -> list:
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image, PageBreak, Paragraph, Spacer, Table, TableStyle
    F, FB = ("Times-Roman", "Times-Bold") if brand.get("font") == "serif" else _fonts()
    it = "Times-Italic" if brand.get("font") == "serif" else "Helvetica-Oblique"
    st = ParagraphStyle("pg", fontName=F, fontSize=10.5, leading=15.5)
    h = ParagraphStyle("pgh", fontName=FB, fontSize=24, leading=29, textColor=colors.HexColor(brand.get("color") or "#171717"), spaceAfter=10)
    W = 174 * mm

    def rich(t: str, s=st):
        t = "\n".join(("• " + l[2:]) if l.startswith("- ") else l for l in escape(t or "").split("\n"))
        t = re.sub(r"\*\*(.+?)\*\*", rf'<font name="{FB}">\1</font>', t)
        return Paragraph(re.sub(r"\*(.+?)\*", rf'<font name="{it}">\1</font>', t).replace("\n", "<br/>"), s)

    async def img(ref: str, mw: float, mh: float):
        got = await file_bytes(org_id, ref)
        if not got or not got[1].startswith("image/"):
            return None
        try:
            iw, ih = ImageReader(io.BytesIO(got[0])).getSize()
            k = min(mw / iw, mh / ih)
            return Image(io.BytesIO(got[0]), width=iw * k, height=ih * k)
        except Exception:
            return None
    story = []
    for i, p in enumerate(pages):
        if not pre:
            story.append(Spacer(1, 6 * mm))
        if pre and i == 0 and brand.get("logo"):
            logo = await img(brand["logo"], 45 * mm, 25 * mm)
            if logo:
                logo.hAlign = "LEFT"
                story += [logo, Spacer(1, 8 * mm)]
        for b in p["blocks"]:
            if b["type"] == "title":
                story.append(rich(b["text"], h))
            elif b["type"] == "text":
                story += [rich(b["text"]), Spacer(1, 4 * mm)]
            elif b["type"] == "image":
                im = await img(b.get("image", ""), W, (215 if b.get("mode") == "full" else 70) * mm)
                story += [im, Spacer(1, 5 * mm)] if im else []
            elif b["type"] == "columns":
                story += [Table([[rich(b["text"]), rich(b["right"])]], colWidths=[W / 2, W / 2], style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, 0), 0)])), Spacer(1, 4 * mm)]
            elif b["type"] == "quote":
                story += [rich(f"« {b['text']} »", ParagraphStyle("pq", parent=st, fontName=it, fontSize=12, leading=17, leftIndent=10)), rich(f"— {b['right']}" if b["right"] else ""), Spacer(1, 4 * mm)]
            elif b["type"] == "schedule":
                story += [Table([[rich(r[0]), rich(r[1])] for r in b.get("rows", [])], colWidths=[W * 0.6, W * 0.4], style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E5E5")), ("LEFTPADDING", (0, 0), (0, -1), 0)])), Spacer(1, 4 * mm)]
        if pre:
            story.append(PageBreak())
    return story


async def decorate(doc: dict, org: dict) -> tuple:
    if "kind" in doc or not await db.document_pages.find_one({"org_id": doc["org_id"]}, {"_id": 1}):
        return doc, org
    res = await resolved(doc, doc.get("price_display") == "none")
    b = res["brand"]
    org = {**org, **{k: b[k] for k in ("legal_name", "siret", "vat_number", "legal_mentions", "legal_mentions_en", "terms", "terms_en") if b.get(k)}, **({"name": b["name"]} if b.get("name") else {})}
    doc = {**doc, "_closing_schedule": any(x["type"] == "schedule" for p in res["closing"] for x in p["blocks"])}
    return {**doc, "_pre": await _flow(res["header"], b, doc["org_id"], True), "_post": await _flow(res["closing"], b, doc["org_id"], False)}, org


class PageSel(BaseModel):
    template_id: str
    enabled: bool = True
    override: Optional[List[PBlock]] = Field(None, max_length=40)


class QuotePagesIn(BaseModel):
    brand_template_id: str = ""
    header: List[PageSel] = Field([], max_length=30)
    closing: List[PageSel] = Field([], max_length=30)


@router.get("/quotes/{qid}/pages")
async def get_quote_pages(qid: str, ctx: Ctx = Depends(FIN)):
    await ensure_defaults(ctx.org_id)
    q = await ctx.get("quotes", qid)
    tpls = {t["id"]: t for t in await ctx.list("document_pages", sort=[("order", 1), ("name", 1)])}
    brand, en, out = await _brand(q), (q.get("language") or "fr").startswith("en"), {}
    for kind in ("header", "closing"):
        sel = [s for s in _selection(q, kind, tpls, brand) if s["template_id"] in tpls]
        sel += [{"template_id": t["id"], "enabled": False, "override": None} for t in tpls.values() if t["kind"] == kind and t["id"] not in {s["template_id"] for s in sel}]
        out[kind] = [{**s, "name": tpls[s["template_id"]]["name"], "blocks": (en and tpls[s["template_id"]].get("blocks_en")) or tpls[s["template_id"]]["blocks_fr"]} for s in sel]
    return {**out, "brand_template_id": q.get("brand_template_id") or brand.get("id", ""), "brands": await ctx.list("brand_templates", sort=[("name", 1)]), "fields": FIELDS, "language": q.get("language") or "fr-FR"}


@router.put("/quotes/{qid}/pages")
async def put_quote_pages(qid: str, body: QuotePagesIn, ctx: Ctx = Depends(FIN)):
    quote_writer(ctx)
    q = await _editable_quote(ctx, qid)
    if q["status"] not in OPEN_STATUSES:
        raise HTTPException(400, "Seul un devis non signé peut être modifié")
    d = body.model_dump()
    await db.quotes.update_one(ctx.q({"id": qid}), {"$set": {"brand_template_id": d["brand_template_id"], "header_pages": d["header"], "closing_pages": d["closing"], "updated_at": now_iso()},
                                                     "$push": {"history": hist(ctx, "Modification", "Pages d'en-tête / de clôture")}})
    return await get_quote_pages(qid, ctx)


# ---------- Versions destinataires ----------
class ViewIn(BaseModel):
    kind: Literal["organizer", "venue", "provider"]
    label: str = Field("", max_length=120)
    provider_id: str = ""
    section_ids: List[str] = Field([], max_length=100)
    price_display: Literal["same", "detailed", "section_totals", "total_only", "none"] = "same"


@router.get("/quotes/{qid}/views")
async def list_views(qid: str, ctx: Ctx = Depends(FIN)):
    q = await ctx.get("quotes", qid)
    from routes_comms import ensure_token
    views = await ctx.list("quote_views", {"quote_id": qid}, sort=[("created_at", 1)])
    for v in views:
        v["token"] = await ensure_link("quote_views", v)
    return {"client_token": await ensure_token("quotes", q), "views": views, "can_renew": ctx.role in ("admin", "gerant"),
            "sections": [{"id": b["id"], "title": b["title"]} for b in qb.blocks_of(q) if b["type"] == "section"]}


@router.post("/quotes/{qid}/views")
async def create_view(qid: str, body: ViewIn, ctx: Ctx = Depends(FIN)):
    quote_writer(ctx)
    await ctx.get("quotes", qid)
    d = body.model_dump()
    if d["kind"] in ("venue", "provider"):
        d["price_display"] = "none"
    v = await ctx.insert("quote_views", {**d, "quote_id": qid})
    return {**v, "token": await ensure_link("quote_views", v)}


@router.delete("/quote-views/{vid}")
async def delete_view(vid: str, ctx: Ctx = Depends(FIN)):
    quote_writer(ctx)
    await ctx.delete("quote_views", vid)
    return {"ok": True}


async def _view(token: str) -> tuple:
    v = await link_doc("quote_views", token)
    q = await db.quotes.find_one({"org_id": v["org_id"], "id": v["quote_id"]}, {"_id": 0}) if v else None
    if not q:
        raise HTTPException(404, "Document introuvable")
    check_expiry(link_limit("quotes", q))
    return q, v


def _pub(pages: list, base: str) -> list:
    return [{"name": p["name"], "blocks": [{**b, "image": f"{base}/page-files/{b['image'][5:]}" if b.get("image", "").startswith("file:") else b.get("image", "")} for b in p["blocks"]]} for p in pages]


def _pub_brand(b: dict, base: str) -> dict:
    return {"name": b.get("name", ""), "color": b.get("color", "#171717"), "font": b.get("font", "sans"), "logo": f"{base}/page-files/{b['logo'][5:]}" if b.get("logo", "").startswith("file:") else b.get("logo", "")}


async def _view_data(q: dict, v: dict) -> tuple:
    mode = "none" if v["kind"] in ("venue", "provider") else (q.get("price_display") or "detailed") if v["price_display"] == "same" else v["price_display"]
    blocks = qb.blocks_of(q)
    if v.get("section_ids"):
        by = {b["id"]: b for b in blocks}

        def root(b: dict) -> str:
            while b.get("parent_id") and b["parent_id"] in by:
                b = by[b["parent_id"]]
            return b["id"]
        blocks = [b for b in blocks if root(b) in v["section_ids"]]
    lines = qb.flatten(blocks, q.get("global_discount_percent", 0))
    qq = {**q, "blocks": blocks, "lines": lines, **totals(lines), "price_display": mode}
    ev, venue, sp = await qb._spaces(q["org_id"], q.get("event_id", ""))
    rows = qb.rows_of(qq, sp, "" if v["price_display"] == "same" and v["kind"] == "organizer" else mode)
    used = {b.get("space_id") for b in blocks}
    spaces = [{k: s.get(k, "") for k in ("name", "description", "power", "notes", "indoor", "vehicle_access")} for s in (venue or {}).get("sections", []) if s["id"] in used]
    return qq, mode, rows, spaces, venue


@router.get("/public/quote-views/{token}")
async def public_view(token: str):
    q, v = await _view(token)
    qq, mode, rows, spaces, venue = await _view_data(q, v)
    org = await db.orgs.find_one({"id": q["org_id"]}, {"_id": 0}) or {}
    res, base, none = await resolved(qq, mode == "none"), f"/api/public/quote-views/{token}", mode == "none"
    return {**{k: qq.get(k) for k in ("number", "status", "date", "valid_until", "event_title", "event_date")}, "event_title": await __import__("routes_titles").quote_title(q), "valid_until": __import__("routes_titles").validity(q, org), "language": q.get("language") or "fr-FR", "client_name": (q.get("client") or {}).get("name", ""),
            "org": {k: org.get(k, "") for k in ("name", "address", "zip", "city", "phone", "email")}, "products": [], "lines": [], "rows": rows, "price_display": mode, "no_prices": none,
            "vat_breakdown": [] if none else qq["vat_breakdown"], "total_ht": None if none else qq["total_ht"], "total_vat": None if none else qq["total_vat"], "total_ttc": None if none else qq["total_ttc"],
            "deposit_percent": 0 if none else q.get("deposit_percent", 0), "notes": "", "dates_lines": qb.dates_lines(q.get("dates"), q.get("language")), "client_modified": False, "can_choose": False,
            "view": {"kind": v["kind"], "label": v.get("label", "")}, "spaces": spaces, "venue_name": (venue or {}).get("name", ""), "pages": {"header": _pub(res["header"], base), "closing": _pub(res["closing"], base)},
            "brand": _pub_brand(res["brand"], base), "version": q.get("version", 1), "active": q.get("active", True), "sign": {"can": False}}


@router.get("/public/quote-views/{token}/pdf")
async def public_view_pdf(token: str):
    q, v = await _view(token)
    qq, mode, rows, spaces, venue = await _view_data(q, v)
    org = await db.orgs.find_one({"id": q["org_id"]}, {"_id": 0}) or {}
    if mode != "none":
        data = await quote_pdf_bytes(qq, org)
    else:
        from reportlab.lib.units import mm
        from reportlab.platypus import Spacer

        from routes_delivery import P, W, _build, _styles, _table
        s = _styles()
        en = (q.get("language") or "fr").startswith("en")
        story = [P(org.get("name", ""), s["sm"]), P(f"{q['number']} — {v.get('label') or ('Technical version' if en else 'Version technique')}", s["big"]), P(f"{q.get('event_title', '')} · {(venue or {}).get('name', '')}", s["sm"]), Spacer(1, 4 * mm)]
        story += [P(t, s["st"]) for t in qb.dates_lines(q.get("dates"), q.get("language"))] + [Spacer(1, 4 * mm)]
        story.append(_table([[P("Désignation" if not en else "Item", s["sm"]), P("Qté" if not en else "Qty", s["sm"])]] + [[P(r["label"], s["bold"] if r["kind"] == "title" else s["st"]), P(f"{r['qty']:g}" if r["kind"] == "line" else "", s["st"])]
                                                                                                                       for r in rows if r["kind"] != "subtotal"], [W * 0.82, W * 0.18]))
        for x in spaces:
            story += [Spacer(1, 5 * mm), P(x["name"], s["bold"])] + [P(f"{lab} : {x[k]}", s["st"]) for k, lab in (("power", "Electricity" if en else "Électricité"), ("notes", "Notes"), ("description", "Description")) if x.get(k)]
        data = _build(story, f"{q['number']} technique", org)
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{q["number"]}-{v["kind"]}.pdf"'})


async def _page_file(q: dict, fid: str) -> Response:
    res = await resolved(q)
    refs = {b.get("image") for k in ("header", "closing") for p in res[k] for b in p["blocks"]} | {res["brand"].get("logo")}
    if f"file:{fid}" not in refs:
        raise HTTPException(404, "Introuvable")
    return _serve(await file_bytes(q["org_id"], f"file:{fid}"))


@router.get("/public/quote-views/{token}/page-files/{fid}")
async def view_page_file(token: str, fid: str):
    return await _page_file((await _view(token))[0], fid)


@router.get("/public/quotes/{token}/page-files/{fid}")
async def quote_page_file(token: str, fid: str):
    return await _page_file(await _client_quote(token), fid)


# ---------- Page publique client : pages, vu, signature OTP, refus ----------
async def _client_quote(token: str) -> dict:
    q = await link_doc("quotes", token)
    if not q:
        raise HTTPException(404, "Devis introuvable")
    return q


def _can_sign(q: dict) -> bool:
    sig = q.get("signature") or {}
    return q.get("active", True) and q["status"] in SIGNABLE and q.get("price_display") != "none" and not q.get("client_modified") and sig.get("status") != "done" and not (sig.get("provider") == "yousign" and sig.get("status") == "ongoing")


async def public_extra(q: dict, token: str) -> dict:
    res, base, sig = await resolved(q), f"/api/public/quotes/{token}", q.get("signature") or {}
    return {"pages": {"header": _pub(res["header"], base), "closing": _pub(res["closing"], base)}, "brand": _pub_brand(res["brand"], base), "version": q.get("version", 1), "active": q.get("active", True),
            "sign": {"can": bool(_can_sign(q)), "status": sig.get("status", ""), "provider": sig.get("provider") or ("yousign" if os.environ.get("YOUSIGN_API_KEY") else "otp"), "signed_at": sig.get("signed_at", ""),
                     "signer_name": sig.get("signer_name", ""), "hash": sig.get("hash", "") if sig.get("status") == "done" else ""}}


@router.post("/public/quotes/{token}/viewed")
async def public_viewed(token: str):
    q = await _client_quote(token)
    if q["status"] == "envoye":
        await db.quotes.update_one({"org_id": q["org_id"], "id": q["id"], "status": "envoye"}, {"$set": {"status": "vu", "viewed_at": now_iso()}, "$push": {"history": {"at": now_iso(), "by": "Client", "action": "Vu", "detail": "Devis consulté en ligne"}}})
    return {"ok": True}


async def freeze(q: dict, org: dict) -> dict:
    pdf = await quote_pdf_bytes(q, org)
    return {"hash": hashlib.sha256(pdf).hexdigest(), "frozen_file": await store_bytes(q["org_id"], pdf, "application/pdf", f"{q['number']}-v{q.get('version', 1)}.pdf", "Signature")}


async def otp_start(q: dict, org: dict, c: dict, base: str) -> dict:
    from routes_comms import ensure_token, reply_to
    url, lg = f"{base}/devis/{await ensure_token('quotes', q)}", c["language"]
    en = lg.startswith("en")
    fr = await freeze(q, org)
    html = mail_html(org["name"], f"Hello {c['name']}," if en else f"Bonjour {c['name']},", [
        (f"Your quote {q['number']} ({money(q['total_ttc'], lg)} incl. VAT) is ready to be signed online." if en else f"Votre devis {q['number']} ({money(q['total_ttc'], lg)} TTC) est prêt à être signé en ligne."),
        ("Open it, tick “Approved”, and confirm with the code sent to this address." if en else "Ouvrez-le, cochez « Bon pour accord », puis validez avec le code envoyé à cette adresse.")], ("Review and sign" if en else "Consulter et signer", url), lg)
    await send_email(to=c["email"], subject=(f"Quote {q['number']} to sign — {org['name']}" if en else f"Devis {q['number']} à signer — {org['name']}"), html=html, reply_to=reply_to(org))
    return {"provider": "otp", "level": "simple", "status": "ongoing", "sent_at": now_iso(), "sent_to": c["email"], "url": url, **fr}


def _otp_hash(salt: str, code: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


@router.post("/public/quotes/{token}/sign/request")
async def sign_request(token: str, request: Request):
    from routes_comms import _recent, base_url, client_of, reply_to
    q = await _client_quote(token)
    if not _can_sign(q) or os.environ.get("YOUSIGN_API_KEY"):
        raise HTTPException(409, "Ce devis ne peut pas être signé en ligne pour le moment")
    c, sig = await client_of(q), q.get("signature") or {}
    if not c["email"]:
        raise HTTPException(400, "Aucune adresse e-mail n'est enregistrée pour le signataire")
    if _recent(sig.get("otp_sent_at"), 60):
        raise HTTPException(429, "Un code vient d'être envoyé, patientez une minute")
    org = await db.orgs.find_one({"id": q["org_id"]}, {"_id": 0})
    if sig.get("status") != "ongoing" or sig.get("provider") != "otp":
        sig = {"provider": "otp", "level": "simple", "status": "ongoing", "sent_at": now_iso(), "sent_to": c["email"], "url": f"{base_url(request)}/devis/{token}", **(await freeze(q, org))}
    code, salt, en = f"{secrets.randbelow(10 ** 6):06d}", secrets.token_hex(8), c["language"].startswith("en")
    html = mail_html(org["name"], f"Hello {c['name']}," if en else f"Bonjour {c['name']},", [
        (f"To confirm your approval of quote {q['number']}, enter this number on the quote page: {code}" if en else f"Pour valider votre accord sur le devis {q['number']}, saisissez ce numéro sur la page du devis : {code}"),
        ("It is valid for 15 minutes. If you did not request it, ignore this message." if en else "Il est valable 15 minutes. Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.")], None, c["language"])
    await send_email(to=c["email"], subject=(f"Quote {q['number']}: your confirmation number" if en else f"Devis {q['number']} : votre numéro de validation"), html=html, reply_to=reply_to(org))
    sig.update(otp_hash=_otp_hash(salt, code), otp_salt=salt, otp_tries=0, otp_sent_at=now_iso(), otp_expires=(datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat())
    await db.quotes.update_one({"org_id": q["org_id"], "id": q["id"]}, {"$set": {"signature": sig}})
    name, _, dom = c["email"].partition("@")
    return {"ok": True, "to": f"{name[:2]}***@{dom}"}


class SignIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")
    name: str = Field(min_length=2, max_length=120)
    title: str = Field("", max_length=120)
    accept: bool


def _proof_pdf(frozen: bytes, lines: list) -> bytes:
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas
    F, FB = _fonts()
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=A4)
    c.setFont(FB, 16)
    c.drawString(50, A4[1] - 70, lines[0])
    c.setFont(F, 10)
    for i, l in enumerate(lines[1:]):
        c.drawString(50, A4[1] - 105 - 18 * i, l)
    c.save()
    w = PdfWriter()
    w.append(PdfReader(io.BytesIO(frozen)))
    w.append(PdfReader(io.BytesIO(buf.getvalue())))
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


@router.post("/public/quotes/{token}/sign/confirm")
async def sign_confirm(token: str, body: SignIn, request: Request):
    q = await _client_quote(token)
    sig, key = q.get("signature") or {}, {"org_id": q["org_id"], "id": q["id"]}
    if not _can_sign(q) or sig.get("status") != "ongoing" or sig.get("provider") != "otp" or not sig.get("otp_hash"):
        raise HTTPException(409, "Aucune signature en attente : demandez un nouveau code")
    if not body.accept:
        raise HTTPException(400, "Cochez « Bon pour accord » pour signer")
    if sig.get("otp_tries", 0) >= 5:
        raise HTTPException(429, "Trop d'essais : demandez un nouveau code")
    if datetime.now(timezone.utc) > datetime.fromisoformat(sig["otp_expires"]):
        raise HTTPException(410, "Code expiré : demandez un nouveau code")
    if not hmac.compare_digest(sig["otp_hash"], _otp_hash(sig["otp_salt"], body.code)):
        await db.quotes.update_one(key, {"$inc": {"signature.otp_tries": 1}})
        raise HTTPException(400, "Code incorrect")
    got = await file_bytes(q["org_id"], sig.get("frozen_file", ""))
    if not got or hashlib.sha256(got[0]).hexdigest() != sig["hash"]:
        raise HTTPException(409, "Le document a changé : demandez un nouveau code")
    proof = {"level": "simple", "method": "Bon pour accord + code OTP par e-mail", "email": sig["sent_to"], "signer_name": body.name.strip(), "signer_title": body.title.strip(), "signed_at": now_iso(),
             "ip": (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip(), "user_agent": (request.headers.get("user-agent") or "")[:200], "hash": sig["hash"],
             "quote": q["number"], "version": q.get("version", 1)}
    en = (q.get("language") or "fr").startswith("en")
    signed = _proof_pdf(got[0], ["Proof of signature (simple electronic signature)" if en else "Preuve de signature (signature électronique simple)", f"{'Quote' if en else 'Devis'} {q['number']} — V{proof['version']}",
                                 f"{'Signed by' if en else 'Signé par'} : {proof['signer_name']}" + (f" — {proof['signer_title']}" if proof["signer_title"] else ""), ("Mention: Approved" if en else "Mention : Bon pour accord"),
                                 f"E-mail : {proof['email']} (code OTP)", f"Date (UTC) : {proof['signed_at']}", f"IP : {proof['ip']}", f"SHA-256 : {proof['hash']}"])
    upd = {"signature.signed_file": await store_bytes(q["org_id"], signed, "application/pdf", f"{q['number']}-signe.pdf", "Client"), "signature.proof": proof, "signature.signed_at": proof["signed_at"], "signature.signer_name": proof["signer_name"]}
    await db.quotes.update_one(key, {"$set": upd, "$unset": {"signature.otp_hash": "", "signature.otp_salt": "", "signature.otp_expires": ""}})
    from routes_comms import apply_signature
    await apply_signature(q["id"], "done", "Client")
    from routes_files import public_quote
    return await public_quote(token)


class RefuseIn(BaseModel):
    reason: str = Field("", max_length=1000)


@router.post("/public/quotes/{token}/refuse")
async def public_refuse(token: str, body: RefuseIn):
    q = await _client_quote(token)
    sig = q.get("signature") or {}
    if not q.get("active", True) or q["status"] not in SIGNABLE or sig.get("status") == "done":
        raise HTTPException(409, "Ce devis ne peut plus être refusé en ligne")
    upd = {"status": "refuse", "refused_at": now_iso(), "refused_reason": body.reason.strip(), **({"signature.status": "declined"} if sig.get("status") == "ongoing" else {})}
    await db.quotes.update_one({"org_id": q["org_id"], "id": q["id"]}, {"$set": upd, "$push": {"history": {"at": now_iso(), "by": "Client", "action": "Refus", "detail": body.reason.strip() or "Sans motif"}}})
    import routes_crm
    async for o in db.opportunities.find({"org_id": q["org_id"], "quote_ids": q["id"], "stage_key": {"$nin": ["gagnee", "perdue", "negociation"]}}, {"_id": 0}):
        await db.opportunities.update_one({"org_id": q["org_id"], "id": o["id"]}, {"$set": {"stage_key": "negociation"}})
        await routes_crm.log(q["org_id"], o["id"], "stage_change", f"Négociation / relance — devis {q['number']} refusé par le client" + (f" : {body.reason.strip()}" if body.reason.strip() else ""))
    await rs.task(q["org_id"], f"Devis {q['number']} refusé par le client : à relancer", f"quote-refused:{q['id']}", desc=body.reason.strip())
    from routes_files import public_quote
    return await public_quote(token)


@router.get("/quotes/{qid}/signature/proof")
async def signature_proof(qid: str, ctx: Ctx = Depends(FIN)):
    sig = (await ctx.get("quotes", qid)).get("signature") or {}
    if not sig.get("proof"):
        raise HTTPException(404, "Aucune preuve de signature pour ce devis")
    return sig["proof"]


async def tick() -> None:
    from routes_comms import reply_to
    async for q in db.quotes.find({"signature.status": "ongoing", "signature.provider": "otp", "status": {"$in": list(SIGNABLE)}}, {"_id": 0}):
        sig, key = q["signature"], {"org_id": q["org_id"], "id": q["id"]}
        if q.get("valid_until") and q["valid_until"] < today():
            from routes_comms import apply_signature
            await apply_signature(q["id"], "expired", "Système")
            continue
        org = await db.orgs.find_one({"id": q["org_id"]}, {"_id": 0}) or {}
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(sig["sent_at"])).days
        due = [d for d in (org.get("sign_reminder_days") or [3, 7]) if d <= age and d not in (sig.get("reminders") or [])]
        if not due or not sig.get("url"):
            continue
        en = (q.get("language") or "fr").startswith("en")
        try:
            await send_email(to=sig["sent_to"], subject=(f"Reminder: quote {q['number']} to sign" if en else f"Rappel : devis {q['number']} à signer"), reply_to=reply_to(org),
                             html=mail_html(org.get("name", ""), "Hello," if en else "Bonjour,", [f"Your quote {q['number']} is still waiting for your signature." if en else f"Votre devis {q['number']} attend toujours votre signature."],
                                            ("Review and sign" if en else "Consulter et signer", sig["url"]), q.get("language") or "fr-FR"))
        except Exception:
            continue
        await db.quotes.update_one(key, {"$push": {"signature.reminders": {"$each": due}, "history": {"at": now_iso(), "by": "Système", "action": "Rappel", "detail": f"Rappel de signature J+{max(due)}"}}})


# ---------- Versionnage ----------
DROP = ("id", "_id", "created_at", "updated_at", "signature", "sent_at", "sent_to", "share_token", "applied_at", "stock_alerts", "history", "client_modified", "option_expires_at", "option_released_at",
        "last_urgent_reminder_at", "viewed_at", "refused_at", "refused_reason", "superseded_by", "status_before")


@router.post("/quotes/{qid}/new-version")
async def new_version(qid: str, ctx: Ctx = Depends(FIN)):
    quote_writer(ctx)
    q = await ctx.get("quotes", qid)
    if not q.get("active", True):
        raise HTTPException(400, "Créez la nouvelle version à partir de la version active")
    if (q.get("signature") or {}).get("status") == "ongoing":
        raise HTTPException(409, "Une signature est en cours : annulez-la avant de créer une nouvelle version")
    v = q.get("version", 1) + 1
    doc = await ctx.insert("quotes", {**{k: x for k, x in q.items() if k not in DROP}, "status": "brouillon", "version": v, "root_id": q.get("root_id") or q["id"], "parent_version_id": q["id"], "active": True,
                                      "date": today(), "history": [hist(ctx, "Création", f"Version V{v} créée à partir de V{v - 1}")]})
    await db.quotes.update_one(ctx.q({"id": qid}), {"$set": {"active": False, "version": q.get("version", 1), "root_id": q.get("root_id") or q["id"], "superseded_by": doc["id"], "status_before": q["status"], "status": "remplace", "updated_at": now_iso()},
                                                     "$push": {"history": hist(ctx, "Version", f"Remplacée par V{v}")}})
    await db.opportunities.update_many(ctx.q({"quote_ids": qid}), {"$addToSet": {"quote_ids": doc["id"]}})
    return doc


@router.get("/quotes/{qid}/versions")
async def versions(qid: str, ctx: Ctx = Depends(FIN)):
    q = await ctx.get("quotes", qid)
    rows = await ctx.list("quotes", {"$or": [{"id": qid}, {"root_id": q.get("root_id") or qid}]}, sort=[("version", 1)])
    return [{"id": r["id"], "version": r.get("version", 1), "status": r["status"], "status_before": r.get("status_before", ""), "active": r.get("active", True), "date": r.get("date", ""), "total_ht": r["total_ht"],
             "total_ttc": r["total_ttc"], "signed": (r.get("signature") or {}).get("status") == "done", "share_token": await ensure_link("quotes", r)} for r in rows]


@router.get("/quotes/{qid}/compare")
async def compare(qid: str, other: str, ctx: Ctx = Depends(FIN)):
    a, b = await ctx.get("quotes", other), await ctx.get("quotes", qid)
    if (a.get("root_id") or a["id"]) != (b.get("root_id") or b["id"]):
        raise HTTPException(400, "Ces devis ne sont pas deux versions du même devis")
    if a.get("version", 1) > b.get("version", 1):
        a, b = b, a
    la, lb = ({x["id"]: x for x in qb.blocks_of(q) if x["type"] == "line"} for q in (a, b))
    keys, short = ("label", "qty", "unit_price", "discount_percent", "vat"), lambda x: {k: x.get(k) for k in ("label", "qty", "unit_price", "discount_percent", "vat")}  # noqa: E731
    head = lambda q: {"id": q["id"], "version": q.get("version", 1), "total_ht": q["total_ht"], "total_ttc": q["total_ttc"]}  # noqa: E731
    return {"from": head(a), "to": head(b), "added": [short(x) for i, x in lb.items() if i not in la], "removed": [short(x) for i, x in la.items() if i not in lb],
            "changed": [{"before": short(la[i]), "after": short(x)} for i, x in lb.items() if i in la and any(la[i].get(k) != x.get(k) for k in keys)], "diff_ttc": r2(b["total_ttc"] - a["total_ttc"])}
