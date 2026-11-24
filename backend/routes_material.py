import math
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import Ctx, db, need, new_id, now_iso

router = APIRouter(prefix="/api")
R = need("catalog:read")
W = need("catalog:write")
DOC_TYPES = ["fiche_technique", "notice", "fiche_commerciale", "certificat", "autre"]
REQ_TYPES = ["consommable", "accessoire_obligatoire", "accessoire_optionnel", "alimentation", "logistique", "humain", "note"]


class DocIn(BaseModel):
    file_ref: str = Field(pattern=r"^file:[\w-]+$")
    type: str = "fiche_technique"
    title: str = Field(min_length=1, max_length=200)
    visibility: Literal["interne", "client"] = "interne"
    is_primary: bool = False
    product_ids: List[str] = Field(min_length=1, max_length=200)


class DocPatch(BaseModel):
    file_ref: Optional[str] = Field(None, pattern=r"^file:[\w-]+$")
    type: Optional[str] = None
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    visibility: Optional[Literal["interne", "client"]] = None
    is_primary: Optional[bool] = None
    product_ids: Optional[List[str]] = Field(None, max_length=200)


async def _one_primary(ctx: Ctx, d: dict) -> None:
    if d.get("is_primary"):
        await db.product_documents.update_many(ctx.q({"id": {"$ne": d["id"]}, "product_ids": {"$in": d["product_ids"]}, "is_primary": True}), {"$set": {"is_primary": False}})


@router.get("/product-documents")
async def list_docs(ctx: Ctx = Depends(R), product_id: str = ""):
    return await ctx.list("product_documents", {"deleted_at": None, **({"product_ids": product_id} if product_id else {})}, sort=[("created_at", -1)])


@router.post("/product-documents")
async def add_doc(body: DocIn, ctx: Ctx = Depends(W)):
    d = await ctx.insert("product_documents", {**body.model_dump(), "type": body.type if body.type in DOC_TYPES else "autre", "version": 1, "history": [], "uploaded_by": ctx.member.get("name"), "deleted_at": None})
    await _one_primary(ctx, d)
    return d


@router.patch("/product-documents/{did}")
async def patch_doc(did: str, body: DocPatch, ctx: Ctx = Depends(W)):
    d = await ctx.get("product_documents", did)
    ch = body.model_dump(exclude_none=True)
    if "type" in ch and ch["type"] not in DOC_TYPES:
        ch["type"] = "autre"
    if "product_ids" in ch and not ch["product_ids"]:
        raise HTTPException(400, "Un document doit rester lié à au moins un produit")
    if ch.get("file_ref") and ch["file_ref"] != d["file_ref"]:
        ch["history"] = d["history"] + [{"version": d["version"], "file_ref": d["file_ref"], "replaced_at": now_iso(), "by": ctx.member.get("name")}]
        ch["version"] = d["version"] + 1
    d = await ctx.update("product_documents", did, ch)
    await _one_primary(ctx, d)
    return d


@router.delete("/product-documents/{did}")
async def delete_doc(did: str, ctx: Ctx = Depends(need("users:manage"))):
    await ctx.update("product_documents", did, {"deleted_at": now_iso()})
    return {"ok": True}


async def shareable_docs(org_id: str, doc_ids: list) -> list:
    return await db.product_documents.find({"org_id": org_id, "deleted_at": None, "visibility": "client", "id": {"$in": doc_ids or []}}, {"_id": 0}).to_list(200)


async def public_docs(q: dict, token: str) -> list:
    return [{"id": d["id"], "title": d["title"], "type": d["type"], "url": f"/api/public/quotes/{token}/documents/{d['id']}"} for d in await shareable_docs(q["org_id"], q.get("shared_doc_ids"))]


@router.get("/public/quotes/{token}/documents/{did}")
async def public_doc(token: str, did: str):
    from routes_files import _serve, _shared_quote, file_bytes
    q = await _shared_quote(token)
    d = next((x for x in await shareable_docs(q["org_id"], q.get("shared_doc_ids")) if x["id"] == did), None)
    if not d:
        raise HTTPException(404, "Introuvable")
    return _serve(await file_bytes(q["org_id"], d["file_ref"]))


class ShareIn(BaseModel):
    doc_ids: List[str] = Field(max_length=100)


async def _quote_eq_ids(ctx: Ctx, q: dict) -> list:
    from routes_stock import quote_items
    packs = {p["id"]: p for p in await ctx.list("packs")}
    return list(quote_items(q.get("lines") or [], packs))


@router.get("/quotes/{qid}/product-documents")
async def quote_docs(qid: str, ctx: Ctx = Depends(need("finance:read"))):
    q = await ctx.get("quotes", qid)
    rows = await ctx.list("product_documents", {"deleted_at": None, "visibility": "client", "product_ids": {"$in": await _quote_eq_ids(ctx, q)}}, sort=[("title", 1)])
    return [{"id": d["id"], "title": d["title"], "type": d["type"], "file_ref": d["file_ref"], "selected": d["id"] in (q.get("shared_doc_ids") or [])} for d in rows]


@router.put("/quotes/{qid}/product-documents")
async def put_quote_docs(qid: str, body: ShareIn, ctx: Ctx = Depends(need("finance:read"))):
    from routes_billing import quote_writer
    quote_writer(ctx)
    q = await ctx.get("quotes", qid)
    ok = {d["id"] for d in await ctx.list("product_documents", {"deleted_at": None, "visibility": "client", "product_ids": {"$in": await _quote_eq_ids(ctx, q)}})}
    ids = [i for i in dict.fromkeys(body.doc_ids) if i in ok]
    await db.quotes.update_one(ctx.q({"id": qid}), {"$set": {"shared_doc_ids": ids}})
    return {"doc_ids": ids}


class Requirement(BaseModel):
    id: str = ""
    type: str = "consommable"
    label: str = Field(min_length=1, max_length=200)
    label_en: str = Field("", max_length=200)
    linked_product_id: str = ""
    quantity: float = Field(1, ge=0)
    unit: str = Field("", max_length=20)
    calc_mode: Literal["per_unit", "per_unit_day", "per_event", "per_day", "per_hour", "per_secondary"] = "per_unit"
    spare_qty: float = Field(0, ge=0)
    spare_pct: float = Field(0, ge=0)
    mandatory: bool = True
    power_w: float = 0
    voltage: str = ""
    plug_type: str = ""
    sockets: int = 0
    weight_kg: float = 0
    volume_m3: float = 0
    handlers: int = 0
    setup_min: int = 0
    teardown_min: int = 0
    note: str = Field("", max_length=500)


class ReqsIn(BaseModel):
    requirements: List[Requirement] = Field(max_length=60)


@router.put("/equipment/{eid}/requirements")
async def put_reqs(eid: str, body: ReqsIn, ctx: Ctx = Depends(W)):
    rows = [{**r.model_dump(), "id": r.id or new_id(), "type": r.type if r.type in REQ_TYPES else "note", "linked_product_id": "" if r.linked_product_id == eid else r.linked_product_id, "order": i} for i, r in enumerate(body.requirements)]
    out = (await ctx.update("equipment", eid, {"requirements": rows}))["requirements"]
    import routes_stock as rs
    for e in await db.events.find(ctx.q({"equipment.equipment_id": eid, "status": {"$ne": "cloture"}, "return_end": {"$gte": now_iso()[:10]}}), {"_id": 0, "id": 1}).to_list(100):
        await rs.reallocate(ctx.org_id, e["id"])
    return out


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    lines: List[Requirement] = Field(max_length=60)


@router.get("/requirement-templates")
async def list_templates(ctx: Ctx = Depends(R)):
    return await ctx.list("requirement_templates", {"deleted_at": None}, sort=[("name", 1)])


@router.post("/requirement-templates")
async def add_template(body: TemplateIn, ctx: Ctx = Depends(W)):
    return await ctx.insert("requirement_templates", {"name": body.name, "lines": [{**l.model_dump(), "id": ""} for l in body.lines]})


@router.delete("/requirement-templates/{tid}")
async def delete_template(tid: str, ctx: Ctx = Depends(W)):
    await ctx.update("requirement_templates", tid, {"deleted_at": now_iso()})
    return {"ok": True}


LINKED = ("consommable", "accessoire_obligatoire", "accessoire_optionnel")
SUMS = ("power_w", "sockets", "weight_kg", "volume_m3", "setup_min", "teardown_min")


def _hours(ev: dict) -> float:
    if not ev.get("start") or not ev.get("end"):
        return 1
    return max(1, (datetime.strptime(ev["end"][:16], "%Y-%m-%dT%H:%M") - datetime.strptime(ev["start"][:16], "%Y-%m-%dT%H:%M")).total_seconds() / 3600)


def build(ev: dict, eqs: dict) -> tuple:
    saved = ev.get("requirement_lines") or {}
    days, hours = max(1, ev.get("rental_days") or 1), _hours(ev)
    lines, tot = [], {**{k: 0 for k in SUMS}, "handlers": 0}
    for l in ev.get("equipment", []):
        eq = eqs.get(l["equipment_id"]) or {}
        n, at, rq = l["qty"], eq.get("attributes") or {}, eq.get("requirements") or []
        if isinstance(at.get("puissance_w"), (int, float)) and not any(r.get("power_w") for r in rq):
            tot["power_w"] = round(tot["power_w"] + at["puissance_w"] * n, 3)
        if isinstance(at.get("poids_kg"), (int, float)) and not any(r.get("weight_kg") for r in rq):
            tot["weight_kg"] = round(tot["weight_kg"] + at["poids_kg"] * n, 3)
        for r in rq:
            mult = {"per_unit": n, "per_unit_day": n * days, "per_event": 1, "per_day": days, "per_hour": hours, "per_secondary": n * (eq.get("qty_per_piece") or 1)}[r["calc_mode"]]
            base = r["quantity"] * mult
            qty = math.ceil(base + r.get("spare_qty", 0) + base * r.get("spare_pct", 0) / 100 - 1e-9)
            units = n if r["calc_mode"] in ("per_unit", "per_unit_day") else 1
            for k in SUMS:
                tot[k] = round(tot[k] + (r.get(k) or 0) * units, 3)
            tot["handlers"] = max(tot["handlers"], r.get("handlers") or 0)
            key = f"{l['equipment_id']}:{r['id']}"
            s = saved.get(key, {})
            adj = s.get("adjusted_qty")
            accepted = s.get("accepted", r["type"] != "accessoire_optionnel")
            lines.append({"key": key, "source_product_id": l["equipment_id"], "source_name": eq.get("name", ""), "source_ref": eq.get("ref", ""), "source_qty": n, "requirement_id": r["id"],
                          "type": r["type"], "label": r["label"], "label_en": r.get("label_en", ""), "unit": r.get("unit", ""), "mandatory": r.get("mandatory", True), "note": r.get("note", ""),
                          "linked_product_id": r.get("linked_product_id", ""), "computed_qty": qty, "adjusted_qty": adj, "qty": adj if adj is not None else qty,
                          "status": "adjusted" if adj is not None else "auto", "accepted": accepted, "auto_added": bool(r.get("linked_product_id")) and accepted and r["type"] in LINKED,
                          "power_w": r.get("power_w") or 0, "sockets": r.get("sockets") or 0, "voltage": r.get("voltage", ""),
                          "checked_out": s.get("checked_out", False), "checked_in": s.get("checked_in", False), "used_qty": s.get("used_qty", 0)})
    return lines, tot


def auto_of(lines: list) -> dict:
    out: dict = {}
    for x in lines:
        if x["auto_added"] and x["qty"] > 0:
            out[x["linked_product_id"]] = out.get(x["linked_product_id"], 0) + int(x["qty"])
    return out


async def compute(ctx: Ctx, ev: dict) -> dict:
    eqs = {e["id"]: e for e in await ctx.list("equipment", limit=10000)}
    lines, tot = build(ev, eqs)
    alerts, need_by = [], auto_of(lines)
    if need_by and ev.get("id") and ev.get("setup_start"):
        import routes_stock as rs
        w, own = await rs.world(ctx.org_id), {l["equipment_id"]: l["qty"] for l in ev.get("equipment", [])}
        evs = [e for e in await rs._evs(ctx.org_id) if e["id"] != ev["id"]]
        for pid, q in need_by.items():
            eq = w["eqs"].get(pid)
            if not eq:
                continue
            _, left = rs.allocate(w, evs, pid, q + own.get(pid, 0), rs.target(ev), rs.buffered(rs.period(ev), eq), ev["id"])
            if left:
                alerts.append(f"Stock insuffisant : {eq.get('name', '?')} — {q} nécessaire(s), {max(0, q - left)} disponible(s) aux dates de l'événement")
    venue = await db.venues.find_one(ctx.q({"id": ev.get("venue_id")}), {"_id": 0, "power_capacity_w": 1}) if ev.get("venue_id") else None
    cap = (venue or {}).get("power_capacity_w") or 0
    if cap and tot["power_w"] > cap:
        alerts.append(f"Puissance totale {tot['power_w']:g} W supérieure à la capacité du lieu ({cap:g} W)")
    if any(x["type"] == "humain" for x in lines) and not ev.get("team"):
        alerts.append("Technicien requis non affecté")
    return {"lines": lines, "totals": tot, "alerts": alerts, "days": max(1, ev.get("rental_days") or 1)}


@router.get("/events/{eid}/requirements")
async def event_reqs(eid: str, ctx: Ctx = Depends(need("events:read"))):
    return await compute(ctx, await ctx.get("events", eid, ctx.event_scope()))


@router.get("/quotes/{qid}/requirements")
async def quote_reqs(qid: str, ctx: Ctx = Depends(need("finance:read"))):
    from routes_stock import quote_items
    q = await ctx.get("quotes", qid)
    ev = await db.events.find_one(ctx.q({"id": q.get("event_id")}), {"_id": 0, "history": 0}) if q.get("event_id") else None
    packs = {p["id"]: p for p in await ctx.list("packs")}
    eqs = {e["id"]: e for e in await ctx.list("equipment", {"id": {"$in": [l["equipment_id"] for l in q.get("lines") or [] if l.get("equipment_id")]}})}
    items = [{"equipment_id": k, "qty": v} for k, v in quote_items(q.get("lines") or [], packs, eqs).items()]
    return await compute(ctx, {**(ev or {}), "equipment": items, "requirement_lines": {}})


def checklist_pdf(ev: dict, org: dict, eqs: dict, lines: list, packs: list | None = None) -> bytes:
    import io
    from xml.sax.saxutils import escape
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    n, b, h = ParagraphStyle("n", fontName="Helvetica", fontSize=9.5, leading=12), ParagraphStyle("b", fontName="Helvetica-Bold", fontSize=10, leading=13), ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=16, leading=20)
    sub = ParagraphStyle("s", parent=n, leftIndent=12)
    rows, bold = [[Paragraph("Matériel", b), Paragraph("Qté", b), Paragraph("Départ", b), Paragraph("Retour", b), Paragraph("Utilisé", b)]], []
    for label, qty, comps in packs or []:
        bold.append(len(rows))
        rows.append([Paragraph(escape(f"Pack : {label}"), b), Paragraph(f"{qty:g}", b), "", "", ""])
        rows += [[Paragraph(escape((eqs.get(c["equipment_id"]) or {}).get("name") or c.get("name", "")), sub), Paragraph(f"{c['qty'] * qty:g}", n), "", "", "—" if c.get("service") else ""] for c in comps]
    for l in ev.get("equipment", []):
        eq = eqs.get(l["equipment_id"]) or {}
        bold.append(len(rows))
        rows.append([Paragraph(escape(f"{eq.get('ref', '')} {eq.get('name', 'Matériel')}".strip()), b), Paragraph(str(l["qty"]), b), "", "", ""])
        for x in lines:
            if x["source_product_id"] == l["equipment_id"] and x["accepted"] and x["type"] in LINKED + ("note",):
                rows.append([Paragraph(escape(x["label"] + (f" — {x['note']}" if x["note"] else "")), sub), Paragraph("" if x["type"] == "note" else f"{x['qty']:g} {escape(x['unit'])}", n), "", "", "" if x["type"] == "consommable" else "—"])
    t = Table(rows, colWidths=[96 * mm, 24 * mm, 18 * mm, 18 * mm, 18 * mm], repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)] + [("BACKGROUND", (0, i), (-1, i), colors.whitesmoke) for i in bold]))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm, title="Check-list de préparation", author=org.get("name", "")).build(
        [Paragraph("Check-list de préparation", h), Paragraph(escape(f"{ev.get('code', '')} · {ev.get('title', '')} · {(ev.get('start') or '')[:10]}"), n), Spacer(1, 6 * mm), t])
    return buf.getvalue()


@router.get("/events/{eid}/requirements/checklist")
async def checklist(eid: str, annex: bool = False, ctx: Ctx = Depends(need("events:read"))):
    from fastapi import Response
    ev = await ctx.get("events", eid, ctx.event_scope())
    eqs = {e["id"]: e for e in await ctx.list("equipment", limit=10000)}
    packs = [(l["label"], l["qty"], l["pack_components"]) async for q in db.quotes.find(ctx.q({"event_id": eid, "status": "accepte", "active": {"$ne": False}}), {"_id": 0, "lines": 1}) for l in q.get("lines") or [] if l.get("pack_components")]
    pdf = checklist_pdf(ev, await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}) or {}, eqs, build(ev, eqs)[0], packs)
    if annex:
        import pymupdf
        from routes_files import file_bytes
        out = pymupdf.open(stream=pdf, filetype="pdf")
        for d in await ctx.list("product_documents", {"deleted_at": None, "type": "fiche_technique", "product_ids": {"$in": [l["equipment_id"] for l in ev.get("equipment", [])]}}, sort=[("title", 1)], limit=40):
            got = await file_bytes(ctx.org_id, d["file_ref"])
            if got:
                try:
                    out.insert_pdf(pymupdf.open(stream=got[0], filetype="pdf"))
                except Exception:
                    pass
        pdf = out.tobytes()
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="check-list-{ev.get("code", "evenement")}.pdf"'})


class LinePatch(BaseModel):
    key: str = Field(max_length=120)
    adjusted_qty: Optional[int] = Field(None, ge=-1)
    accepted: Optional[bool] = None
    checked_out: Optional[bool] = None
    checked_in: Optional[bool] = None
    used_qty: Optional[int] = Field(None, ge=0)


@router.patch("/events/{eid}/requirements")
async def patch_line(eid: str, body: LinePatch, ctx: Ctx = Depends(need("events:read"))):
    ev = await ctx.get("events", eid, ctx.event_scope())
    cur = next((x for x in (await compute(ctx, ev))["lines"] if x["key"] == body.key), None)
    if not cur:
        raise HTTPException(404, "Introuvable")
    ch = body.model_dump(exclude_none=True, exclude={"key"})
    if ({"adjusted_qty", "accepted"} & set(ch)) and not ctx.can("events:write"):
        raise HTTPException(403, "Action non autorisée pour votre rôle")
    if ch.get("adjusted_qty") == -1:
        ch["adjusted_qty"] = None
    if "used_qty" in ch and cur["linked_product_id"] and cur["type"] == "consommable":
        delta = ch["used_qty"] - cur["used_qty"]
        from routes_stock import consume
        wid = next((r["warehouse_id"] for r in ev.get("allocations") or [] if r.get("auto") and r["equipment_id"] == cur["linked_product_id"]), "")
        await consume(ctx.org_id, cur["linked_product_id"], delta, wid, eid)
    line = {**(ev.get("requirement_lines") or {}).get(body.key, {}), **ch}
    await db.events.update_one(ctx.q({"id": eid}), {"$set": {f"requirement_lines.{body.key.replace('.', '_')}": line}})
    if {"adjusted_qty", "accepted"} & set(ch):
        from routes_stock import reallocate
        await reallocate(ctx.org_id, eid)
    return await compute(ctx, await ctx.get("events", eid))
