import base64
import io
import re
from typing import List
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from PIL import Image as PILImage
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core import Ctx, db, need, new_id, now_iso
from i18n import fmt_date, tr
from routes_billing import LOAD_STATUSES, PARIS, _day, _fonts, fr_date, today
from routes_files import file_bytes, read_upload, store_bytes
from routes_main import contact_name

router = APIRouter(prefix="/api")
INK, GREY, LINE = colors.HexColor("#171717"), colors.HexColor("#525252"), colors.HexColor("#E5E5E5")
W = A4[0] - 36 * mm


def _styles() -> dict:
    F, FB = _fonts()
    st = ParagraphStyle("b", fontName=F, fontSize=9.5, leading=13, textColor=INK)
    return {"st": st, "sm": ParagraphStyle("s", parent=st, fontSize=8, leading=11, textColor=GREY), "bold": ParagraphStyle("bo", parent=st, fontName=FB),
            "big": ParagraphStyle("h", parent=st, fontName=FB, fontSize=18, leading=22), "h2": ParagraphStyle("h2", parent=st, fontName=FB, fontSize=12, leading=16)}


def P(t, s) -> Paragraph:
    return Paragraph(escape(str(t or "")).replace("\n", "<br/>"), s)


def _build(story: list, title: str, org: dict) -> bytes:
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                      title=title, author=org.get("name", "")).build(story)
    return buf.getvalue()


def _table(rows: list, widths: list) -> Table:
    return Table(rows, colWidths=widths, repeatRows=1, style=TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK), ("LINEBELOW", (0, 1), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (0, -1), 0)]))


def _img(data: bytes, maxw: float, maxh: float):
    try:
        im = PILImage.open(io.BytesIO(data))
        im.thumbnail((1400, 1400))
        out = io.BytesIO()
        im.convert("RGB").save(out, "JPEG", quality=80)
        k = min(maxw / im.width, maxh / im.height)
        return Image(io.BytesIO(out.getvalue()), width=im.width * k, height=im.height * k)
    except Exception:
        return None


def _address(v: dict) -> str:
    return ", ".join(x for x in (v.get("address"), " ".join(filter(None, [v.get("zip"), v.get("city")]))) if x)


# ---------- Livraison du jour ----------
def _snap(ev: dict, eqs: dict, venue: dict, contact: dict | None) -> dict:
    secs = {s["id"]: s["name"] for s in venue.get("sections", [])}
    return {"language": ev.get("language") or "fr-FR", "event_code": ev["code"], "event_title": ev["title"], "departure": ev["setup_start"], "vehicle_id": ev.get("vehicle_id") or "",
            "venue": {k: venue.get(k) for k in ("name", "address", "zip", "city", "lat", "lng")},
            "client_name": contact_name(contact) if contact else "", "client_phone": (contact or {}).get("phone", ""),
            "lines": [{"ref": (eqs.get(l["equipment_id"]) or {}).get("ref", "?"), "name": ((ev.get("language") or "fr").startswith("en") and (eqs.get(l["equipment_id"]) or {}).get("name_en")) or (eqs.get(l["equipment_id"]) or {}).get("name", "Matériel supprimé"),
                       "qty": l["qty"], "section": secs.get(l.get("section_id"), "")} for l in ev.get("equipment", [])]}


async def sync_deliveries(org_id: str, day: str, scope: dict) -> list:
    evs = await db.events.find({**scope, "org_id": org_id, "status": {"$in": LOAD_STATUSES},
                                "setup_start": {"$regex": f"^{re.escape(day)}"}}, {"_id": 0}).to_list(500)
    if not evs:
        return []
    eqs = {e["id"]: e for e in await db.equipment.find({"org_id": org_id}, {"_id": 0}).to_list(5000)}
    venues = {v["id"]: v for v in await db.venues.find({"org_id": org_id}, {"_id": 0}).to_list(5000)}
    contacts = {c["id"]: c for c in await db.contacts.find({"org_id": org_id, "id": {"$in": [e.get("client_id") for e in evs]}}, {"_id": 0}).to_list(500)}
    out = []
    for ev in evs:
        key = {"org_id": org_id, "day": day, "event_id": ev["id"]}
        snap = _snap(ev, eqs, venues.get(ev.get("venue_id")) or {}, contacts.get(ev.get("client_id")))
        cur = await db.deliveries.find_one(key, {"_id": 0})
        if cur is None:
            cur = {**key, **snap, "id": new_id(), "status": "a_livrer", "order": 0, "photos": [], "created_at": now_iso()}
            try:
                await db.deliveries.insert_one(dict(cur))
            except DuplicateKeyError:
                cur = await db.deliveries.find_one(key, {"_id": 0})
        elif cur["status"] != "livre" and any(cur.get(k) != v for k, v in snap.items()):
            await db.deliveries.update_one(key, {"$set": snap})
            cur.update(snap)
        out.append(cur)
    return sorted(out, key=lambda d: (d.get("order") or 999, d["departure"]))


@router.get("/deliveries")
async def get_deliveries(ctx: Ctx = Depends(need("events:read")), day: str = ""):
    d = _day(day) if day else today()
    return {"day": d, "deliveries": await sync_deliveries(ctx.org_id, d, ctx.event_scope()), "vehicles": await ctx.list("vehicles", sort=[("name", 1)])}


class OrderIn(BaseModel):
    ids: List[str] = Field(max_length=100)


@router.put("/deliveries/order")
async def order_deliveries(body: OrderIn, ctx: Ctx = Depends(need("events:write"))):
    for i, did in enumerate(body.ids):
        await db.deliveries.update_one(ctx.q({"id": did}), {"$set": {"order": i + 1}})
    return {"ok": True}


async def _delivery(ctx: Ctx, did: str) -> dict:
    d = await ctx.get("deliveries", did)
    await ctx.get("events", d["event_id"], ctx.event_scope())
    return d


@router.post("/deliveries/{did}/photos")
async def add_photo(did: str, file: UploadFile = File(...), ctx: Ctx = Depends(need("events:read"))):
    d = await _delivery(ctx, did)
    data, ctype = await read_upload(file)
    if not ctype.startswith("image/"):
        raise HTTPException(400, "Seules les photos sont acceptées")
    if d["status"] == "livre" or len(d["photos"]) >= 12:
        raise HTTPException(400, "Le bon est déjà signé" if d["status"] == "livre" else "12 photos maximum par livraison")
    ref = await store_bytes(ctx.org_id, data, ctype, f"livraison-{d['event_code']}", ctx.member.get("name"))
    r = await db.deliveries.find_one_and_update(ctx.q({"id": did, "status": {"$ne": "livre"}}), {"$push": {"photos": ref}},
                                                projection={"_id": 0}, return_document=ReturnDocument.AFTER)
    if r is None:
        raise HTTPException(400, "Le bon est déjà signé")
    return r


class SignIn(BaseModel):
    signer_name: str = Field(min_length=2, max_length=120)
    signature: str = Field(max_length=700_000)
    notes: str = Field("", max_length=1000)


def _signature_png(data_url: str) -> bytes:
    try:
        raw = base64.b64decode(data_url.split("base64,", 1)[1], validate=True)
        im = PILImage.open(io.BytesIO(raw)).convert("RGBA")
        flat = PILImage.new("RGB", im.size, "white")
        flat.paste(im, mask=im.split()[3])
    except Exception:
        raise HTTPException(400, "Signature illisible")
    if flat.convert("L").getextrema()[0] > 200:
        raise HTTPException(400, "La signature est vide")
    out = io.BytesIO()
    flat.save(out, "PNG")
    return out.getvalue()


def bon_pdf(d: dict, org: dict, signer: str, notes: str, signed_at: str, sig: bytes, photos: list) -> bytes:
    s = _styles()
    v = d["venue"]
    lg = d.get("language")
    story = [P(org.get("name", ""), s["big"]), P(f"{tr('bl_title', lg)} BL-{d['event_code']} · {fmt_date(d['day'], lg)}", s["h2"]), Spacer(1, 6 * mm),
             Table([[[P(tr("event", lg), s["sm"]), P(d["event_title"], s["bold"]), P(d["event_code"], s["sm"])],
                     [P(tr("bl_to", lg), s["sm"]), P(v.get("name") or "—", s["bold"]), P(_address(v), s["sm"]), P(d.get("client_name", ""), s["sm"])]]],
                   colWidths=[W / 2, W / 2], style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (0, 0), 0.6, LINE),
                                                              ("BOX", (1, 0), (1, 0), 0.6, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                                              ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)])),
             Spacer(1, 6 * mm),
             _table([[P(tr("bl_ref", lg), s["sm"]), P(tr("designation", lg), s["sm"]), P(tr("bl_area", lg), s["sm"]), P(tr("qty", lg), s["sm"])]] +
                    [[P(l["ref"], s["st"]), P(l["name"], s["bold"]), P(l["section"], s["st"]), P(l["qty"], s["st"])] for l in d["lines"]],
                    [W * 0.18, W * 0.46, W * 0.24, W * 0.12]), Spacer(1, 6 * mm)]
    if notes:
        story += [P(tr("bl_notes", lg), s["bold"]), P(notes, s["st"]), Spacer(1, 4 * mm)]
    when = signed_at[:16].replace("T", " à ")
    story.append(KeepTogether([P(tr("bl_received", lg, signer=signer, date=fmt_date(signed_at, lg), time=when[-5:]), s["st"]), Spacer(1, 2 * mm),
                               _img(sig, 70 * mm, 32 * mm) or Spacer(1, 1)]))
    cells = [i for i in (_img(p, W / 2 - 4 * mm, 80 * mm) for p in photos) if i]
    if cells:
        story += [PageBreak(), P(tr("bl_photos", lg), s["h2"]), Spacer(1, 4 * mm)]
        cells += [""] * (len(cells) % 2)
        story.append(Table([cells[i:i + 2] for i in range(0, len(cells), 2)], colWidths=[W / 2, W / 2],
                           style=TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 0)])))
    return _build(story, f"Bon de livraison {d['event_code']}", org)


@router.post("/deliveries/{did}/sign")
async def sign_delivery(did: str, body: SignIn, ctx: Ctx = Depends(need("events:read"))):
    d = await _delivery(ctx, did)
    if d["status"] == "livre":
        raise HTTPException(409, "Ce bon de livraison est déjà signé")
    sig = _signature_png(body.signature)
    from datetime import datetime
    signed_at = datetime.now(PARIS).strftime("%Y-%m-%dT%H:%M")
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    photos = [g[0] for g in [await file_bytes(ctx.org_id, p) for p in d["photos"]] if g]
    pdf = bon_pdf(d, org, body.signer_name.strip(), body.notes.strip(), signed_at, sig, photos)
    upd = {"status": "livre", "signer_name": body.signer_name.strip(), "notes": body.notes.strip(), "signed_at": signed_at,
           "delivered_by": ctx.member.get("name"),
           "signature_file": await store_bytes(ctx.org_id, sig, "image/png", f"signature-{d['event_code']}.png", ctx.member.get("name")),
           "bon_file": await store_bytes(ctx.org_id, pdf, "application/pdf", f"BL-{d['event_code']}.pdf", ctx.member.get("name"))}
    r = await db.deliveries.find_one_and_update(ctx.q({"id": did, "status": {"$ne": "livre"}}), {"$set": upd},
                                                projection={"_id": 0}, return_document=ReturnDocument.AFTER)
    if r is None:
        raise HTTPException(409, "Ce bon de livraison est déjà signé")
    detail = f"Livraison signée par {upd['signer_name']}" + (f" — réserves : {upd['notes']}" if upd["notes"] else "")
    await db.events.update_one(ctx.q({"id": d["event_id"]}), {"$push": {"history": {"$each": [
        {"at": now_iso(), "by": ctx.member.get("name"), "action": "Livraison", "detail": detail}], "$slice": -300}}})
    return r


@router.get("/events/{eid}/documents")
async def event_documents(eid: str, ctx: Ctx = Depends(need("events:read"))):
    await ctx.get("events", eid, ctx.event_scope())
    docs = [{"kind": "Bon de livraison signé", "label": f"BL-{d['event_code']} · {fr_date(d['day'])} · signé par {d['signer_name']}", "ref": d["bon_file"]}
            for d in await ctx.list("deliveries", {"event_id": eid, "status": "livre"}, sort=[("day", 1)])]
    docs += [{"kind": "Bon signé (mission)", "label": f"BL-{m.get('event_code', '')} · {fr_date(m['date'])} · signé par {m['signer_name']}", "ref": m["bon_file"]}
             for m in await ctx.list("logistics_missions", {"event_id": eid, "bon_file": {"$exists": True}}, sort=[("date", 1)])]
    if ctx.can("finance:read"):
        docs += [{"kind": "Devis signé", "label": q["number"], "ref": q["signature"]["signed_file"]}
                 for q in await ctx.list("quotes", {"event_id": eid, "signature.signed_file": {"$exists": True}})]
    return docs


# ---------- Plan d'implantation ----------
@router.get("/events/{eid}/implantation/pdf")
async def implantation_pdf(eid: str, ctx: Ctx = Depends(need("events:read"))):
    ev = await ctx.get("events", eid, ctx.event_scope())
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    venue = await db.venues.find_one(ctx.q({"id": ev.get("venue_id")}), {"_id": 0}) or {}
    eqs = {e["id"]: e for e in await ctx.list("equipment")}
    s = _styles()
    story = [P("Plan d'implantation", s["big"]), P(f"{ev['code']} · {ev['title']}", s["h2"]),
             P(f"{venue.get('name', 'Lieu à définir')} — {_address(venue)}", s["st"]),
             P(f"Montage : {fr_date(ev['setup_start'])} à {ev['setup_start'][11:16]} · Événement : {fr_date(ev['start'])} à {ev['start'][11:16]}", s["sm"]),
             Spacer(1, 6 * mm)]
    groups = [(sec["name"], sec.get("notes", ""), sec["id"]) for sec in venue.get("sections", [])] + [("Non affecté", "", "")]
    known = {g[2] for g in groups}
    for name, notes, sid in groups:
        lines = [l for l in ev.get("equipment", []) if (l.get("section_id") or "") == sid or (not sid and l.get("section_id") not in known)]
        if not lines:
            continue
        rows = [[P("Référence", s["sm"]), P("Désignation", s["sm"]), P("Qté", s["sm"]), P("Posé", s["sm"])]]
        rows += [[P((eqs.get(l["equipment_id"]) or {}).get("ref", "?"), s["st"]), P((eqs.get(l["equipment_id"]) or {}).get("name", "Matériel supprimé"), s["bold"]),
                  P(l["qty"], s["st"]), ""] for l in lines]
        t = _table(rows, [W * 0.2, W * 0.56, W * 0.12, W * 0.12])
        t.setStyle(TableStyle([("BOX", (3, 1), (3, -1), 0.6, GREY), ("INNERGRID", (3, 1), (3, -1), 0.6, GREY)]))
        story.append(KeepTogether([P(f"{name} — {sum(l['qty'] for l in lines)} élément(s)", s["h2"])] + ([P(notes, s["sm"])] if notes else []) +
                                  [Spacer(1, 2 * mm), t, Spacer(1, 7 * mm)]))
    if not ev.get("equipment"):
        story.append(P("Aucun matériel sur cet événement.", s["st"]))
    for ref in [p for p in venue.get("plans", []) if p.startswith("file:")][:3]:
        got = await file_bytes(ctx.org_id, ref)
        img = _img(got[0], W, 230 * mm) if got and got[1].startswith("image/") else None
        if img:
            story += [PageBreak(), P(f"Plan — {venue.get('name', '')}", s["h2"]), Spacer(1, 4 * mm), img]
    return Response(_build(story, f"Plan d'implantation {ev['code']}", org), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="implantation-{ev["code"]}.pdf"'})
