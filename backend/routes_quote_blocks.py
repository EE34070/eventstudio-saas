import math
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

import routes_stock as rs
from core import Ctx, db, need, new_id, now_iso
from i18n import fmt_date
from routes_billing import OPEN_STATUSES, _editable_quote, hist, quote_writer, totals

from core import check_expiry, ensure_link, link_doc, link_limit  # noqa: E402,F401
router = APIRouter(prefix="/api")
FIN = need("finance:read")
MODES = ("detailed", "section_totals", "total_only", "none")


class Block(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    parent_id: str = ""
    type: Literal["section", "subsection", "line", "text", "page_break"]
    title: str = Field("", max_length=200)
    description: str = Field("", max_length=4000)
    space_id: str = ""
    show_subtotal: bool = True
    optional: bool = False
    selected: bool = False
    price_display_override: Literal["", "detailed", "section_totals", "total_only", "none"] = ""
    discount_percent: float = Field(0, ge=0, le=100)
    label: str = Field("", max_length=300)
    qty: float = Field(1, gt=0)
    unit_price: float = 0
    vat: float = Field(20, ge=0, le=100)
    equipment_id: str = ""
    pack_id: str = ""
    kind: str = Field("service", max_length=12)
    unit: str = Field("", max_length=20)
    uom: str = Field("", max_length=12)
    dates: Optional[dict] = None
    unit_cost: float = 0
    margin_pending: bool = False
    supplier_id: str = ""
    supplier_quote_id: str = ""
    supplier_line_id: str = ""
    catalog_item_id: str = ""
    detail: Optional[list] = None
    source_type: str = Field("", max_length=20)
    source_id: str = Field("", max_length=64)
    price_locked: bool = False
    pack_components: Optional[List[dict]] = Field(None, max_length=60)
    pack_version: int = 0
    show_components: bool = True
    match: str = Field("", max_length=10)
    usage_start: str = Field("", pattern=r"^(\d{2}:\d{2})?$")
    usage_end: str = Field("", pattern=r"^(\d{2}:\d{2})?$")
    reuse_from: str = Field("", max_length=64)
    reuse_qty: float = Field(0, ge=0)
    reuse_status: str = Field("", max_length=12)
    reuse_force_reason: str = Field("", max_length=200)
    reuse_effective: float = 0
    reuse_alert: str = Field("", max_length=300)
    import_ref: str = Field("", max_length=80)


COST_KEYS = ("unit_cost", "margin_pending", "supplier_id", "supplier_quote_id", "supplier_line_id", "catalog_item_id", "detail")


class Slot(BaseModel):
    enabled: bool = True
    date: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    start: str = Field("", pattern=r"^(\d{2}:\d{2})?$")
    end: str = Field("", pattern=r"^(\d{2}:\d{2})?$")


class Operation(BaseModel):
    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


class Dates(BaseModel):
    delivery: Slot
    operation: Operation
    pickup: Slot
    delivery_same_day: bool = False
    pickup_after_operation: bool = False


class StructureIn(BaseModel):
    blocks: List[Block] = Field(min_length=1, max_length=600)
    dates: Optional[Dates] = None
    price_display: Literal["detailed", "section_totals", "total_only", "none"] = "detailed"
    numbering: bool = False
    global_discount_percent: float = Field(0, ge=0, le=100)
    deposit_percent: float = Field(0, ge=0, lt=100)
    valid_until: str = ""
    notes: str = Field("", max_length=2000)


def default_blocks(q: dict) -> list:
    sid = new_id()
    out = [{**Block(id=sid, type="section", title="Prestations").model_dump()}]
    for l in q.get("lines", []):
        if l.get("kind") == "title":
            out.append(Block(id=new_id(), parent_id=sid, type="text", description=l.get("label", "")).model_dump())
            continue
        out.append(Block(id=new_id(), parent_id=sid, type="line", label=l["label"][:300], description=l.get("description", ""), qty=l["qty"], unit_price=l["unit_price"], vat=l["vat"],
                         equipment_id=l.get("equipment_id", ""), pack_id=l.get("pack_id", ""), kind=l.get("kind") or "service", unit=l.get("unit", ""), uom=l.get("uom", "")).model_dump())
    return out


def blocks_of(q: dict) -> list:
    return q.get("blocks") or default_blocks(q)


async def migrate() -> None:
    async for q in db.quotes.find({"blocks": {"$in": [None, []]}}, {"_id": 0}):
        await db.quotes.update_one({"org_id": q["org_id"], "id": q["id"], "blocks": {"$in": [None, []]}}, {"$set": {"blocks": default_blocks(q), "price_display": q.get("price_display") or "detailed"}})


def _chain(by: dict, b: dict) -> list:
    out, cur = [], by.get(b.get("parent_id"))
    while cur and len(out) < 3:
        out.append(cur)
        cur = by.get(cur.get("parent_id"))
    return out


def _eff(b: dict, chain: list, gd: float) -> float:
    p = b["unit_price"] * (1 - b.get("discount_percent", 0) / 100) * (1 - gd / 100)
    for c in chain:
        p *= 1 - c.get("discount_percent", 0) / 100
    return round(p, 4)


def flatten(blocks: list, gd: float = 0) -> list:
    by, out = {b["id"]: b for b in blocks}, []
    for b in blocks:
        chain = _chain(by, b)
        if b["type"] != "line" or not chain or any(c.get("optional") and not c.get("selected") for c in chain):
            continue
        out.append({"label": b["label"], "description": b.get("description", ""), "qty": b["qty"], "unit_price": _eff(b, chain, gd), "vat": b["vat"], "equipment_id": b.get("equipment_id", ""), "pack_id": b.get("pack_id", ""),
                    "kind": b.get("kind") or "service", "unit": b.get("unit", ""), "uom": b.get("uom", ""), "section_id": chain[-1]["id"], "space_id": b.get("space_id") or next((c["space_id"] for c in chain if c.get("space_id")), ""), "block_id": b["id"], **({"reused": b["reuse_effective"]} if b.get("reuse_effective") else {}), **({"pack_components": b["pack_components"]} if b.get("pack_components") is not None else {})})
    return out


def _with_comps(b: dict, en: bool, lang: str = "") -> str:
    cs = [c for c in (b.get("pack_components") or []) if c.get("visible_client", True)] if b.get("show_components", True) else []
    lab = lambda c: f"{c['qty']:g} × " + (c.get("loc") or (c.get("client_label_en") if en else "") or c.get("client_label") or (c.get("name_en") if en else "") or c.get("name", ""))  # noqa: E731
    from routes_pack_i18n import GROUPS
    g = GROUPS.get((lang or ("en" if en else "fr"))[:2]) or GROUPS["en"]
    parts = [(g[0], [c for c in cs if c.get("service")]), (g[1], [c for c in cs if not c.get("service")])]
    return " / ".join(filter(None, [b.get("description", "")] + [t + " · ".join(lab(c) for c in x) for t, x in parts if x]))


def rows_of(q: dict, spaces: dict, force: str = "") -> list:
    blocks, gd, en = blocks_of(q), q.get("global_discount_percent", 0), (q.get("language") or "fr").startswith("en")
    by, rows, n = {b["id"]: b for b in blocks}, [], [0, 0]

    def sub(pid: str) -> float:
        return sum(sub(c["id"]) if c["type"] == "subsection" else c["qty"] * _eff(c, _chain(by, c), gd) for c in blocks if c.get("parent_id") == pid and c["type"] in ("line", "subsection"))

    def walk(pid: str, level: int, mode: str) -> None:
        for b in [x for x in blocks if x.get("parent_id", "") == pid]:
            if b["type"] in ("section", "subsection"):
                m = force or b.get("price_display_override") or mode
                n[level - 1] += 1
                if level == 1:
                    n[1] = 0
                num = (f"{n[0]}. " if level == 1 else f"{n[0]}.{n[1]} ") if q.get("numbering") else ""
                sp = spaces.get(b.get("space_id"), "")
                rows.append({"kind": "title", "level": level, "id": b["id"], "label": num + b["title"] + (f" — {sp}" if sp and sp not in b["title"] else "") + ((" (option)" if not en else " (optional)") if b.get("optional") else ""),
                             "description": b.get("description", ""), "optional": bool(b.get("optional")), "selected": bool(b.get("selected")), "space": sp})
                if b.get("description"):
                    rows.append({"kind": "text", "label": b["description"]})
                walk(b["id"], level + 1, m)
                if m == "section_totals" or (m == "detailed" and b.get("show_subtotal") and level == 1 and len([x for x in blocks if x["type"] == "section"]) > 1):
                    rows.append({"kind": "subtotal", "label": ("Subtotal " if en else "Sous-total ") + b["title"], "amount": round(sub(b["id"]), 2), "section_id": b["id"]})
            elif b["type"] == "text":
                rows.append({"kind": "text", "label": b.get("description") or b.get("title", "")})
            elif b["type"] == "line":
                r = {"kind": "line", "label": b["label"], "description": _with_comps(b, en, q.get("language") or ""), "qty": b["qty"], "unit": b.get("unit", ""), "equipment_id": b.get("equipment_id", "")}
                rows.append({**r, "unit_price": _eff(b, _chain(by, b), gd), "vat": b["vat"]} if mode == "detailed" else {**r, "hide_price": True})
    walk("", 1, force or q.get("price_display") or "detailed")
    return rows


def norm_dates(d: dict) -> dict:
    if d["delivery_same_day"]:
        d["delivery"]["date"] = d["operation"]["start"][:10]
    if d["pickup_after_operation"]:
        d["pickup"]["date"] = d["operation"]["end"][:10]
    op = d["operation"]
    if op["end"] <= op["start"]:
        raise HTTPException(400, "La fin de l'exploitation doit être après son début")
    dl, pk = d["delivery"], d["pickup"]
    if dl["enabled"] and (not dl["date"] or f"{dl['date']}T{dl['start'] or '00:00'}" > op["start"]):
        raise HTTPException(400, "La livraison doit avoir lieu avant le début de l'exploitation")
    if pk["enabled"] and (not pk["date"] or f"{pk['date']}T{pk['end'] or '23:59'}" < op["end"]):
        raise HTTPException(400, "Le retrait doit avoir lieu après la fin de l'exploitation")
    return d


def dates_from_event(ev: dict) -> dict:
    s, e = ev.get("setup_start") or ev["start"], ev.get("return_end") or ev["end"]
    dw, pw = ev.get("delivery_window") or {}, ev.get("pickup_window") or {}
    return {"delivery": {"enabled": not ev.get("no_delivery", False), "date": s[:10], "start": dw.get("from") or s[11:16], "end": dw.get("to", "")}, "operation": {"start": ev["start"][:16], "end": ev["end"][:16]},
            "pickup": {"enabled": not ev.get("no_pickup", False), "date": e[:10], "start": pw.get("from", ""), "end": pw.get("to") or e[11:16]}, "delivery_same_day": False, "pickup_after_operation": False}


def op_days(d: dict) -> int:
    h = (datetime.fromisoformat(d["operation"]["end"]) - datetime.fromisoformat(d["operation"]["start"])).total_seconds() / 3600
    return max(1, math.ceil(h / 24))


def dates_lines(d: dict | None, lg: str) -> list:
    if not d:
        return []
    en, op, out = (lg or "fr").startswith("en"), d["operation"], []
    slot = lambda s: " – ".join(x for x in (s["start"], s["end"]) if x)  # noqa: E731
    same = d["delivery"]["enabled"] and d["delivery"]["date"] == op["start"][:10] == op["end"][:10]
    if d["delivery"]["enabled"]:
        out.append(f"{'Delivery / set-up' if en else 'Livraison / installation'} : {fmt_date(d['delivery']['date'], lg)} {slot(d['delivery'])}".strip())
    out.append(f"{'Event' if en else 'Exploitation'} : {fmt_date(op['start'], lg)} {op['start'][11:]} → {fmt_date(op['end'], lg)} {op['end'][11:]}")
    if d["pickup"]["enabled"]:
        out.append(f"{'Pick-up / dismantling' if en else 'Retrait / démontage'} : {fmt_date(d['pickup']['date'], lg)} {slot(d['pickup'])}".strip())
    if same:
        out.append("Delivery and event on the same day" if en else "Livraison et exploitation le même jour")
    return out


async def _spaces(org_id: str, event_id: str) -> tuple:
    ev = await db.events.find_one({"org_id": org_id, "id": event_id}, {"_id": 0, "history": 0}) or {}
    v = await db.venues.find_one({"org_id": org_id, "id": ev.get("venue_id")}, {"_id": 0}) if ev.get("venue_id") else None
    return ev, v, {s["id"]: s["name"] for s in (v or {}).get("sections", [])}


async def pdf_doc(doc: dict) -> dict:
    if "kind" in doc or not doc.get("blocks"):
        return doc
    _, _, sp = await _spaces(doc["org_id"], doc.get("event_id", ""))
    import routes_pack_i18n
    doc = await routes_pack_i18n.localize(doc)
    return {**doc, "lines": rows_of(doc, sp), "dates_lines": dates_lines(doc.get("dates"), doc.get("language"))}


async def public_extra(q: dict) -> dict:
    if not q.get("blocks"):
        return {}
    _, _, sp = await _spaces(q["org_id"], q.get("event_id", ""))
    mode = q.get("price_display") or "detailed"
    mode = "total_only" if mode == "none" else mode
    import routes_pack_i18n
    q = await routes_pack_i18n.localize(q)
    return {"rows": rows_of({**q, "price_display": mode}, sp), "price_display": mode, "dates_lines": dates_lines(q.get("dates"), q.get("language")), "client_modified": bool(q.get("client_modified")),
            "can_choose": q["status"] in OPEN_STATUSES and (q.get("signature") or {}).get("status") not in ("ongoing", "done"), **({} if mode == "detailed" else {"lines": []})}


@router.get("/quotes/{qid}/structure")
async def get_structure(qid: str, ctx: Ctx = Depends(FIN)):
    q = await ctx.get("quotes", qid)
    ev, v, sp = await _spaces(ctx.org_id, q.get("event_id", ""))
    d = q.get("dates") or (dates_from_event(ev) if ev else None)
    import routes_supplier_quotes as sq
    cc = sq.can_cost(ctx)
    return {"blocks": blocks_of(q) if cc else [{k: v for k, v in b.items() if k not in COST_KEYS} for b in blocks_of(q)], "can_cost": cc, "margin_rules": await sq.rules_of(ctx.org_id) if cc else None,
            "supplier_quotes": await db.supplier_quotes.find(ctx.q({"quote_id": qid, "status": {"$ne": "remplace"}}), {"_id": 0, "lines": 0}).to_list(50) if cc else [], "dates": d, "operation_days": op_days(d) if d else 1, "event_dates": dates_from_event(ev) if ev else None, "price_display": q.get("price_display") or "detailed", "numbering": bool(q.get("numbering")),
            "global_discount_percent": q.get("global_discount_percent", 0), "deposit_percent": q.get("deposit_percent", 0), "valid_until": q.get("valid_until", ""), "notes": q.get("notes", ""), "venue_id": (v or {}).get("id", ""),
            "spaces": [{"id": k, "name": n} for k, n in sp.items()], "templates": await ctx.list("quote_section_templates", sort=[("name", 1)]), "client_modified": bool(q.get("client_modified")), "number": q["number"], "has_trips": bool(q.get("trips") or q.get("labor") or q.get("expenses")), "logistics_section": (await __import__("routes_quote_logistics").pricing_of(ctx.org_id))["logistics_section"], "event_id": q.get("event_id", ""), "event_label": f"{ev['code']} · {ev['title']}" if ev else ""}


@router.put("/quotes/{qid}/structure")
async def put_structure(qid: str, body: StructureIn, ctx: Ctx = Depends(FIN)):
    quote_writer(ctx)
    q = await _editable_quote(ctx, qid)
    if q["status"] not in OPEN_STATUSES:
        raise HTTPException(400, "Seul un devis en brouillon ou envoyé peut être modifié")
    blocks = [b.model_dump() for b in body.blocks]
    import routes_reuse
    per = {x["id"]: x.get("transfer_minutes") or 0 for x in ((await _spaces(ctx.org_id, q.get("event_id", "")))[1] or {}).get("sections", [])}
    await routes_reuse.apply(ctx.org_id, blocks, per)
    await routes_reuse.sync_steps(ctx.org_id, q, blocks, per)
    by = {b["id"]: b for b in blocks}
    if len(by) != len(blocks):
        raise HTTPException(400, "Identifiants de blocs en double")
    for b in blocks:
        p = by.get(b["parent_id"])
        ok = (b["type"] == "section" and not b["parent_id"]) or (b["type"] == "subsection" and p and p["type"] == "section") or (b["type"] in ("line", "text", "page_break") and p and p["type"] in ("section", "subsection"))
        if not ok or (b["type"] == "line" and not b["label"].strip()) or (b["type"] in ("section", "subsection") and not b["title"].strip()):
            raise HTTPException(400, "Structure invalide : chaque ligne doit avoir une désignation et appartenir à une section titrée")
    import routes_supplier_quotes as sq
    old = {b["id"]: b for b in q.get("blocks") or []}
    for b in blocks:
        if not sq.can_cost(ctx):
            b.update({k: old.get(b["id"], {}).get(k, Block.model_fields[k].default) for k in COST_KEYS})
        b["margin_pending"] = b["type"] == "line" and b["unit_cost"] > 0 and b["unit_price"] <= b["unit_cost"] + 0.001
    if not any(b["type"] == "line" for b in blocks):
        raise HTTPException(400, "Le devis doit contenir au moins une ligne")
    lines = flatten(blocks, body.global_discount_percent)
    upd = {"blocks": blocks, "lines": lines, **totals(lines), **body.model_dump(exclude={"blocks", "dates"}), "client_modified": False, "updated_at": now_iso()}
    warnings, ev = [], await db.events.find_one(ctx.q({"id": q.get("event_id")}), {"_id": 0, "history": 0})
    if body.dates and ev:
        d = norm_dates(body.dates.model_dump())
        upd["dates"], op, dl, pk = d, d["operation"], d["delivery"], d["pickup"]
        evu = {"start": op["start"], "end": op["end"], "setup_start": f"{dl['date']}T{dl['start'] or '08:00'}" if dl["enabled"] else op["start"], "return_end": f"{pk['date']}T{pk['end'] or '18:00'}" if pk["enabled"] else op["end"],
               "delivery_window": {"from": dl["start"], "to": dl["end"]} if dl["enabled"] else None, "pickup_window": {"from": pk["start"], "to": pk["end"]} if pk["enabled"] else None,
               "no_delivery": not dl["enabled"], "no_pickup": not pk["enabled"], "no_logistics": not dl["enabled"] and not pk["enabled"]}
        evu["return_end"] = max(evu["return_end"], op["end"])
        gap = (await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "quote_gap_days": 1}) or {}).get("quote_gap_days") or 5
        if dl["enabled"] and (datetime.fromisoformat(op["start"]) - datetime.fromisoformat(evu["setup_start"])).days > gap:
            warnings.append(f"La livraison a lieu plus de {gap} jours avant l'exploitation")
        if any(ev.get(k) != v for k, v in evu.items()):
            await rs.check(ctx.org_id, {**ev, **evu})
            await db.events.update_one(ctx.q({"id": ev["id"]}), {"$set": {**evu, "updated_at": now_iso()}, "$push": {"history": hist(ctx, "Dates", f"Dates reprises du devis {q['number']}")}})
            await rs.reallocate(ctx.org_id, ev["id"])
            if await db.logistics_missions.find_one(ctx.q({"event_id": ev["id"]})):
                import routes_logistics
                await routes_logistics.generate(ctx.org_id, {**ev, **evu}, ctx.member.get("name"))
    await db.quotes.update_one(ctx.q({"id": qid}), {"$set": upd, "$push": {"history": hist(ctx, "Modification", "Sections / lignes / dates")}})
    import routes_quote_sync
    await routes_quote_sync.recalc_event(ctx.org_id, q.get("event_id", ""), ctx.member.get("name"))
    return {**await get_structure(qid, ctx), "warnings": warnings, "total_ttc": upd["total_ttc"], "total_ht": upd["total_ht"]}


class SpaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.post("/venues/{vid}/spaces")
async def add_space(vid: str, body: SpaceIn, ctx: Ctx = Depends(FIN)):
    quote_writer(ctx)
    await ctx.get("venues", vid)
    s = {"id": new_id(), "name": body.name.strip(), "notes": ""}
    await db.venues.update_one(ctx.q({"id": vid}), {"$push": {"sections": s}})
    return s


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    blocks: List[Block] = Field(min_length=1, max_length=100)


@router.post("/quote-section-templates")
async def save_template(body: TemplateIn, ctx: Ctx = Depends(FIN)):
    quote_writer(ctx)
    return await ctx.insert("quote_section_templates", {"name": body.name, "blocks": [{**b.model_dump(), "space_id": ""} for b in body.blocks]})


class OptionIn(BaseModel):
    section_id: str
    selected: bool


@router.post("/public/quotes/{token}/options")
async def public_option(token: str, body: OptionIn):
    q = await link_doc("quotes", token)
    if not q or not q.get("blocks"):
        raise HTTPException(404, "Devis introuvable")
    if q["status"] not in OPEN_STATUSES or (q.get("signature") or {}).get("status") in ("ongoing", "done"):
        raise HTTPException(409, "Ce devis ne peut plus être modifié")
    b = next((b for b in q["blocks"] if b["id"] == body.section_id and b.get("optional") and b["type"] in ("section", "subsection")), None)
    if not b:
        raise HTTPException(404, "Option introuvable")
    b["selected"] = body.selected
    lines = flatten(q["blocks"], q.get("global_discount_percent", 0))
    await db.quotes.update_one({"org_id": q["org_id"], "id": q["id"]}, {"$set": {"blocks": q["blocks"], "lines": lines, **totals(lines), "client_modified": True, "updated_at": now_iso()},
                                                                         "$push": {"history": {"at": now_iso(), "by": "Client", "action": "Modifié par le client", "detail": f"Option « {b['title']} » {'ajoutée' if body.selected else 'retirée'}"}}})
    await rs.task(q["org_id"], f"Devis {q['number']} modifié par le client : à valider", f"quote-client:{q['id']}:{now_iso()[:13]}", desc=f"Option « {b['title']} » {'ajoutée' if body.selected else 'retirée'} depuis la page publique.")
    from routes_files import public_quote
    return await public_quote(token)


@router.get("/quotes/{qid}/installation/pdf")
async def installation_pdf(qid: str, ctx: Ctx = Depends(need("events:read"))):
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Spacer

    from routes_delivery import P, W, _build, _styles, _table
    q = await ctx.get("quotes", qid)
    ev, v, sp = await _spaces(ctx.org_id, q.get("event_id", ""))
    await ctx.get("events", q.get("event_id", ""), ctx.event_scope())
    notes = {s["id"]: s for s in (v or {}).get("sections", [])}
    groups: dict = {}
    for l in flatten(blocks_of(q)):
        g = groups.setdefault(l["space_id"], {})
        g[l["label"]] = g.get(l["label"], 0) + l["qty"]
    s, story, org = _styles(), [], await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    for i, (sid, items) in enumerate(groups.items()):
        x = notes.get(sid) or {}
        story += ([PageBreak()] if i else []) + [P(org.get("name", ""), s["sm"]), P(sp.get(sid) or "Sans emplacement", s["big"]), P(f"{q.get('event_title', '')} · {(v or {}).get('name', '')} · devis {q['number']}", s["sm"]), Spacer(1, 4 * mm)]
        story += [P(t, s["st"]) for t in dates_lines(q.get("dates") or (dates_from_event(ev) if ev else None), "fr")]
        story += [P(f"Électricité : {x['power']}", s["st"])] if x.get("power") else []
        story += [P(f"Notes d'installation : {x['notes']}", s["st"])] if x.get("notes") else []
        story += [Spacer(1, 4 * mm), _table([[P("Matériel", s["sm"]), P("Qté", s["sm"])]] + [[P(k, s["bold"]), P(f"{n:g}", s["st"])] for k, n in items.items()], [W * 0.82, W * 0.18])]
    return Response(_build(story or [P("Aucun matériel", s["st"])], f"Fiche d'installation {q['number']}", org), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="installation-{q["number"]}.pdf"'})
