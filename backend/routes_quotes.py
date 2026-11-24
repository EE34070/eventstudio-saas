import re
import secrets
from datetime import datetime, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import Ctx, audit, db, need, now_iso
from i18n import clean_lang
from routes_billing import LineIn, hist, next_number, plus_days, quote_writer, today, totals
from routes_main import ContactIn, _contact, contact_name, module_catalog
from routes_ops import EventIn, NewVenue, compute_conflicts, create_event, normalize

router = APIRouter(prefix="/api")
TBC_START = "2099-12-31T18:00"
GUESS = [("dj", r"\bdj\b|animat|musique"), ("son_lumiere", r"sono|son\b|lumi|éclairage|eclairage"), ("photobooth", r"photobooth|borne"), ("photographe", r"photograph")]


def guess_module(label: str) -> str:
    return next((k for k, rx in GUESS if re.search(rx, label.lower())), "")


class NewClient(BaseModel):
    first_name: str = Field("", max_length=80)
    last_name: str = Field("", max_length=80)
    company: str = Field("", max_length=120)
    email: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    language: str = "fr-FR"


class DirectIn(BaseModel):
    event_id: str = ""
    client_ids: List[str] = Field([], max_length=6)
    new_client: Optional[NewClient] = None
    organizer_contact_id: str = ""
    type: str = "Autre"
    date: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    venue_id: str = ""
    new_venue: Optional[NewVenue] = None
    guests: int = Field(0, ge=0)
    language: str = ""
    lines: List[LineIn] = Field(min_length=1)
    deposit_percent: float = Field(30, ge=0, lt=100)
    valid_until: str = ""
    notes: str = Field("", max_length=2000)


async def direct_quote(ctx: Ctx, body: DirectIn) -> dict:
    quote_writer(ctx)
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    if body.event_id:
        ev = await ctx.get("events", body.event_id)
    else:
        if not ctx.can("events:write"):
            raise HTTPException(403, "Action non autorisée pour votre rôle")
        ids = list(body.client_ids)
        n = body.new_client
        if n and (n.first_name or n.last_name or n.company):
            if not ctx.can("contacts:write"):
                raise HTTPException(403, "Action non autorisée pour votre rôle")
            data = _contact(ContactIn(**n.model_dump(), kind="entreprise" if n.company and not n.last_name else "particulier", types=["client"], source="Devis"))
            ids.insert(0, (await ctx.insert("contacts", {**data, "interactions": []}))["id"])
        first = await ctx.get("contacts", ids[0]) if ids else None
        city = body.new_venue.city if body.new_venue else ((await ctx.get("venues", body.venue_id)).get("city", "") if body.venue_id else "")
        title = " ".join(filter(None, [body.type, contact_name(first) if first else ""])) + (f" — {city}" if city else "")
        keys = [m["key"] for m in await module_catalog(ctx.org_id)]
        mods = {guess_module(l.label) for l in body.lines} | ({"loueur_materiel"} if any(l.equipment_id or l.pack_id for l in body.lines) else set())
        mods = [k for k in keys if k in mods] or keys[:1]
        start = f"{body.date}T18:00" if body.date else TBC_START
        end = (datetime.strptime(start[:10], "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%dT02:00")
        r = await create_event(EventIn(title=title, type=body.type, client_id=ids[0] if ids else "", client_contact_ids=ids, signatory_contact_id=ids[0] if ids else "",
                                       planner_contact_id=body.organizer_contact_id or None, venue_id=body.venue_id, new_venue=body.new_venue, start=start, end=end,
                                       guests=body.guests, modules=mods, language=body.language or None, date_tbc=not body.date), ctx)
        ev = await ctx.get("events", r["id"])
    c = await db.contacts.find_one(ctx.q({"id": ev.get("client_id")}), {"_id": 0}) if ev.get("client_id") else None
    lines = [l.model_dump() for l in body.lines]
    day = today()
    doc = await ctx.insert("quotes", {
        "number": await next_number(ctx, "quote", org.get("quote_prefix") or "DEV"), "origin": "direct", "event_id": ev["id"], "event_code": ev["code"], "event_title": ev["title"],
        "event_date": "" if ev.get("date_tbc") else ev["start"][:10], "client_id": ev.get("client_id", ""),
        "client": {"name": contact_name(c), "address": c.get("address", ""), "city": c.get("city", ""), "email": c.get("email", "")} if c else {"name": ""},
        "status": "brouillon", "date": day, "valid_until": body.valid_until or plus_days(day, 30), "lines": lines,
        "deposit_percent": body.deposit_percent, "notes": body.notes, "language": clean_lang(body.language or ev.get("language") or (c or {}).get("language")), **totals(lines),
        "history": [hist(ctx, "Création", "Devis créé directement")]})
    await db.events.update_one(ctx.q({"id": ev["id"]}), {"$push": {"history": hist(ctx, "Devis", f"Devis {doc['number']} créé")}})
    return doc


@router.post("/quotes/direct")
async def create_direct(body: DirectIn, ctx: Ctx = Depends(need("finance:read"))):
    return await direct_quote(ctx, body)


async def on_sent(org_id: str, event_id: str) -> None:
    await db.events.update_one({"org_id": org_id, "id": event_id, "status": "demande"}, {"$set": {"status": "devis_envoye", "updated_at": now_iso()}})


async def on_accept(org_id: str, qid: str, by: str) -> list:
    key = {"org_id": org_id}
    q = await db.quotes.find_one({**key, "id": qid}, {"_id": 0})
    import routes_pack_i18n
    await routes_pack_i18n.snapshot(org_id, q)
    import routes_supplier_quotes
    await routes_supplier_quotes.on_quote_accepted(org_id, q)
    import routes_dj
    await routes_dj.on_quote_accepted(org_id, q)
    ev = await db.events.find_one({**key, "id": q["event_id"]}, {"_id": 0})
    import routes_quote_logistics
    await routes_quote_logistics.on_quote_accepted(org_id, q, ev)
    if not ev:
        return []
    eqs = {e["id"]: e async for e in db.equipment.find(key, {"_id": 0})}
    if q.get("origin") == "direct" and not q.get("applied_at"):
        days = max(1, ev.get("rental_days", 1))
        have = {l["equipment_id"] for l in ev.get("equipment", [])}

        def add(eid: str, qty: float, price: float, uom: str = "") -> None:
            if eid in eqs and eid not in have:
                have.add(eid)
                from routes_units import to_pieces
                sec = uom == "secondary" and eqs[eid].get("qty_per_piece")
                n = to_pieces(eqs[eid], qty, uom) or 1
                ev.setdefault("equipment", []).append({"equipment_id": eid, "qty": n, "entered_qty": qty if sec else None, "entered_uom": "secondary" if sec else "",
                                                       "price_day": round(price * (qty if sec else n) / n / days, 2), "state_out": "", "state_in": "", "qty_returned": 0, "section_id": ""})
        for l in q["lines"]:
            if l.get("kind") == "title":
                continue
            import routes_stock as _rs
            parts = _rs.pack_parts(l, eqs)
            if parts is not None:
                for i, n in parts.items():
                    add(i, n, 0)
                ev.setdefault("prestations", []).append({"id": secrets.token_hex(8), "module": guess_module(l["label"]) or "", "title": l["label"], "price": round(l["qty"] * l["unit_price"], 2), "cost": 0, "fields": {}})
                continue
            if l.get("equipment_id"):
                add(l["equipment_id"], l["qty"], l["unit_price"], l.get("uom") or "")
                continue
            if l.get("pack_id"):
                pack = await db.packs.find_one({**key, "id": l["pack_id"]}, {"_id": 0}) or {}
                for it in pack.get("items", []):
                    add(it["equipment_id"], it["qty"] * l["qty"], 0)
            ev.setdefault("prestations", []).append({"id": secrets.token_hex(8), "module": guess_module(l["label"]) or ("loueur_materiel" if l.get("pack_id") else ""), "title": l["label"],
                                                     "price": round(l["qty"] * l["unit_price"], 2), "cost": 0, "fields": {}})
    if ev["status"] in ("demande", "devis_envoye"):
        ev["status"] = "confirme"
    ev = normalize(ev, eqs)
    evs = await db.events.find({**key, "status": {"$ne": "cloture"}}, {"_id": 0}).to_list(5000)
    conflicts = compute_conflicts(ev, [ev if e["id"] == ev["id"] else e for e in evs], eqs)
    await db.events.update_one({**key, "id": ev["id"]}, {"$set": {k: ev[k] for k in ("equipment", "prestations", "status", "rental_days", "amount_equipment", "amount_services", "amount_ht", "amount_ttc", "costs_total")},
                                                        "$push": {"history": {"at": now_iso(), "by": by, "action": "Devis", "detail": f"Devis {q['number']} accepté : matériel réservé, événement confirmé"}}})
    await db.quotes.update_one({**key, "id": qid}, {"$set": {"applied_at": now_iso(), "stock_alerts": conflicts}})
    import routes_stock
    await routes_stock.reallocate(org_id, ev["id"])
    import routes_shortages
    await routes_shortages.notify_confirmed(org_id, ev)
    await routes_stock.after_firm(org_id, qid)
    return conflicts


# ---------- Devis depuis la fiche événement : liste, rattachement, détachement ----------
def _signed(q: dict) -> bool:
    return q["status"] == "accepte" or (q.get("signature") or {}).get("status") == "done"


def _ev_date(ev: dict) -> str:
    return "" if ev.get("date_tbc") else ev["start"][:10]


def _diffs(q: dict, ev: dict) -> list:
    out = ["client"] if q.get("client_id") and ev.get("client_id") and q["client_id"] != ev["client_id"] else []
    op = (q.get("dates") or {}).get("operation")
    if (op and (op["start"][:16], op["end"][:16]) != (ev["start"][:16], ev["end"][:16])) or (not op and q.get("event_date") and _ev_date(ev) and q["event_date"] != _ev_date(ev)):
        out.append("dates")
    return out


@router.get("/events/{eid}/quotes")
async def event_quotes(eid: str, ctx: Ctx = Depends(need("events:read"))):
    await ctx.get("events", eid, ctx.event_scope())
    money = ctx.can("finance:read")
    rows = await ctx.list("quotes", {"event_id": eid, "active": {"$ne": False}}, sort=[("created_at", -1)])
    return [{"id": q["id"], "number": q["number"], "version": q.get("version", 1), "status": q["status"], "date": q.get("date", ""), "signed": _signed(q),
             "imported": q.get("created_from") == "import", "unmatched": __import__("routes_quote_sync").unmatched_of(q), "flat": bool(q.get("import_flat")),
             **({"total_ht": q["total_ht"], "total_ttc": q["total_ttc"], "import_gap": q.get("import_gap") or 0} if money else {})} for q in rows]


@router.get("/events/{eid}/quote-candidates")
async def quote_candidates(eid: str, q: str = "", all: bool = False, ctx: Ctx = Depends(need("finance:read"))):
    ev = await ctx.get("events", eid)
    rows = await ctx.list("quotes", {"event_id": {"$ne": eid}, "active": {"$ne": False}}, sort=[("created_at", -1)], limit=5000)
    if not all:
        rows = [r for r in rows if not r.get("event_id") or (ev.get("client_id") and r.get("client_id") == ev["client_id"])]
    out = [{"id": r["id"], "number": r["number"], "version": r.get("version", 1), "status": r["status"], "date": r.get("date", ""), "client": (r.get("client") or {}).get("name", ""), "total_ttc": r["total_ttc"],
            "event_id": r.get("event_id", ""), "event_label": " · ".join(filter(None, [r.get("event_code"), r.get("event_title")])) if r.get("event_id") else "", "signed": _signed(r), "diffs": _diffs(r, ev)} for r in rows]
    t = q.strip().lower().replace(",", ".")
    return [r for r in out if not t or t in f"{r['number']} {r['client']} {r['total_ttc']:.2f} {r['date']} {r['date'][8:10]}/{r['date'][5:7]}/{r['date'][:4]}".lower()][:200]


class AttachIn(BaseModel):
    quote_ids: List[str] = Field(min_length=1, max_length=50)
    confirm_move: bool = False
    align: Literal["quote", "event"] = "quote"


async def _family(ctx: Ctx, q: dict) -> dict:
    if await db.invoices.find_one(ctx.q({"quote_id": q["id"]})):
        raise HTTPException(400, f"Le devis {q['number']} est déjà facturé : son rattachement ne peut plus changer")
    return ctx.q({"$or": [{"id": q["id"]}, {"root_id": q.get("root_id") or q["id"]}]})


@router.post("/events/{eid}/quotes/attach")
async def attach_quotes(eid: str, body: AttachIn, ctx: Ctx = Depends(need("finance:read"))):
    quote_writer(ctx)
    ev = await ctx.get("events", eid)
    qs = [q for q in [await ctx.get("quotes", i) for i in dict.fromkeys(body.quote_ids)] if q.get("event_id") != eid]
    if any(q.get("active") is False for q in qs):
        raise HTTPException(400, "Rattachez la version active du devis")
    fams = [await _family(ctx, q) for q in qs]
    moved = [q for q in qs if q.get("event_id")]
    if moved and not body.confirm_move:
        raise HTTPException(409, "Déjà lié à un autre événement : " + ", ".join(f"{q['number']} (lié à {q.get('event_title') or q.get('event_code')})" for q in moved) + ". Confirmez le déplacement.")
    c = await db.contacts.find_one(ctx.q({"id": ev.get("client_id")}), {"_id": 0}) if ev.get("client_id") else None
    import routes_stock
    for q, fam in zip(qs, fams):
        old = q.get("event_id", "")
        await db.quotes.update_many(fam, {"$set": {"event_id": eid, "event_code": ev["code"], "updated_at": now_iso()}})
        detail = f"Devis {q['number']} " + (f"déplacé depuis {q.get('event_code') or 'un autre événement'}" if old else "rattaché") + f" à {ev['code']}"
        op = {"$push": {"history": hist(ctx, "Rattachement", detail)}}
        if not _signed(q):
            op["$set"] = {"event_title": ev["title"], "event_date": _ev_date(ev)}
            if body.align == "event":
                op["$unset"] = {"dates": ""}
                op["$set"]["language"] = clean_lang(ev.get("language") or (c or {}).get("language") or q.get("language"))
                if c:
                    op["$set"].update(client_id=c["id"], client={"name": contact_name(c), "address": c.get("address", ""), "city": c.get("city", ""), "email": c.get("email", "")})
        await db.quotes.update_one(ctx.q({"id": q["id"]}), op)
        for e in filter(None, [eid, old]):
            await db.events.update_one(ctx.q({"id": e}), {"$push": {"history": hist(ctx, "Devis", detail)}})
        await audit(ctx.org_id, ctx.member, "quote_moved" if old else "quote_attached", q["number"], detail)
        await db.opportunities.update_many(ctx.q({"quote_ids": q["id"], "event_id": {"$in": [None, "", old]}}), {"$set": {"event_id": eid}})
        await db.opportunities.update_many(ctx.q({"event_id": eid}), {"$addToSet": {"quote_ids": q["id"]}})
        if old:
            await routes_stock.reallocate(ctx.org_id, old)
        if q["status"] == "accepte":
            await db.quotes.update_one(ctx.q({"id": q["id"]}), {"$unset": {"applied_at": ""}})
            await on_accept(ctx.org_id, q["id"], ctx.member.get("name"))
    import routes_quote_sync
    for e in {eid, *[q.get("event_id") for q in moved]}:
        await routes_quote_sync.recalc_event(ctx.org_id, e, ctx.member.get("name"))
    return await event_quotes(eid, ctx)


@router.post("/quotes/{qid}/detach")
async def detach_quote(qid: str, ctx: Ctx = Depends(need("finance:read"))):
    quote_writer(ctx)
    q = await ctx.get("quotes", qid)
    old = q.get("event_id", "")
    if not old:
        raise HTTPException(400, "Ce devis n'est rattaché à aucun événement")
    await db.quotes.update_many(await _family(ctx, q), {"$set": {"event_id": "", "event_code": "", "updated_at": now_iso()}})
    detail = f"Devis {q['number']} détaché de {q.get('event_code') or 'son événement'}"
    await db.quotes.update_one(ctx.q({"id": qid}), {"$push": {"history": hist(ctx, "Rattachement", detail)}})
    await db.events.update_one(ctx.q({"id": old}), {"$push": {"history": hist(ctx, "Devis", detail)}})
    await audit(ctx.org_id, ctx.member, "quote_detached", q["number"], detail)
    import routes_stock
    import routes_quote_sync
    await routes_quote_sync.recalc_event(ctx.org_id, old, ctx.member.get("name"))
    return {"ok": True}


# ---------- Dupliquer un devis / modèles de devis ----------
import routes_quote_blocks as qb  # noqa: E402
from core import new_id  # noqa: E402

BODY = ("global_discount_percent", "deposit_percent", "price_display", "numbering", "notes", "language", "brand_template_id", "header_pages", "closing_pages")


class DupIn(BaseModel):
    destination: Literal["same", "event", "none"] = "same"
    event_id: str = ""
    client: Literal["source", "event"] = "source"
    dates: Literal["source", "event", "custom"] = "source"
    custom_dates: Optional[qb.Dates] = None
    prices: Literal["source", "catalog"] = "source"


def _client_of(c: dict) -> dict:
    return {"name": contact_name(c), "address": c.get("address", ""), "city": c.get("city", ""), "email": c.get("email", "")}


async def build_quote(ctx: Ctx, src: dict, ev: dict | None, body: DupIn, note: str, extra: dict | None = None) -> dict:
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0})
    src_ev = await db.events.find_one(ctx.q({"id": src.get("event_id")}), {"_id": 0, "history": 0}) if src.get("event_id") else None
    src_blocks = qb.blocks_of(src)
    ids = {b["id"]: new_id() for b in src_blocks}
    blocks = [{**b, "id": ids[b["id"]], "parent_id": ids.get(b.get("parent_id"), "")} for b in src_blocks]
    src_sp = (await qb._spaces(ctx.org_id, src_ev["id"]))[2] if src_ev else {}
    dst_sp = (await qb._spaces(ctx.org_id, ev["id"]))[2] if ev else {}
    by_name, lost, warnings = {n.strip().lower(): i for i, n in dst_sp.items()}, 0, []
    for b in blocks:
        if b.get("space_id"):
            keep = b["space_id"] if b["space_id"] in dst_sp else by_name.get((src_sp.get(b["space_id"]) or "").strip().lower(), "")
            lost += not keep
            b["space_id"] = keep
    if lost:
        warnings.append(f"{lost} emplacement(s) vidé(s) : le lieu de destination n'a pas les mêmes espaces")
    if body.prices == "catalog":
        eqs = {e["id"]: e for e in await ctx.list("equipment", limit=10000)}
        packs = {p["id"]: p for p in await ctx.list("packs")}
        for b in blocks:
            if b["type"] == "line" and b.get("equipment_id") in eqs:
                b["unit_price"] = eqs[b["equipment_id"]].get("price_day") or 0
            elif b["type"] == "line" and b.get("pack_id") in packs:
                b["unit_price"] = packs[b["pack_id"]].get("price") or 0
    if body.dates == "custom":
        if not body.custom_dates:
            raise HTTPException(400, "Saisissez les dates du duplicata")
        dates = qb.norm_dates(body.custom_dates.model_dump())
    else:
        dates = (src.get("dates") or (qb.dates_from_event(src_ev) if src_ev and not src_ev.get("date_tbc") else None)) if body.dates == "source" else None
    c = await db.contacts.find_one(ctx.q({"id": ev.get("client_id")}), {"_id": 0}) if ev and body.client == "event" and ev.get("client_id") else None
    lines, day = qb.flatten(blocks, src.get("global_discount_percent", 0)), today()
    doc = await ctx.insert("quotes", {
        "number": await next_number(ctx, "quote", org.get("quote_prefix") or "DEV"), "origin": "direct", "event_id": ev["id"] if ev else "", "event_code": ev["code"] if ev else "", "event_title": ev["title"] if ev else "",
        "event_date": dates["operation"]["start"][:10] if dates else (_ev_date(ev) if ev else ""), "client_id": c["id"] if c else src.get("client_id", ""), "client": _client_of(c) if c else src.get("client") or {"name": ""},
        "status": "brouillon", "date": day, "valid_until": plus_days(day, 30), "blocks": blocks, "lines": lines, **totals(lines), **{k: src[k] for k in BODY if k in src}, **({"dates": dates} if dates else {}),
        **(extra or {}), "history": [hist(ctx, "Création", note)]})
    if ev:
        await db.events.update_one(ctx.q({"id": ev["id"]}), {"$push": {"history": hist(ctx, "Devis", f"Devis {doc['number']} créé ({note})")}})
    await audit(ctx.org_id, ctx.member, "quote_duplicated", doc["number"], note)
    return {**doc, "warnings": warnings}


@router.post("/quotes/{qid}/duplicate")
async def duplicate_quote(qid: str, body: DupIn, ctx: Ctx = Depends(need("finance:read"))):
    quote_writer(ctx)
    src = await ctx.get("quotes", qid)
    eid = src.get("event_id", "") if body.destination == "same" else body.event_id if body.destination == "event" else ""
    if body.destination == "event" and not eid:
        raise HTTPException(400, "Choisissez l'événement de destination")
    ev = await ctx.get("events", eid) if eid else None
    return await build_quote(ctx, src, ev, body, f"Dupliqué de {src['number']}", {"duplicated_from": {"id": src["id"], "number": src["number"]}})


class TemplateIn(BaseModel):
    quote_id: str
    name: str = Field(min_length=1, max_length=120)


class UseIn(BaseModel):
    event_id: str = ""
    prices: Literal["source", "catalog"] = "source"


@router.get("/quote-templates")
async def list_quote_templates(ctx: Ctx = Depends(need("finance:read"))):
    return [{"id": t["id"], "name": t["name"], "total_ttc": t.get("total_ttc", 0), "created_at": t["created_at"]} for t in await ctx.list("quote_templates", sort=[("name", 1)])]


@router.post("/quote-templates")
async def save_quote_template(body: TemplateIn, ctx: Ctx = Depends(need("finance:read"))):
    quote_writer(ctx)
    q = await ctx.get("quotes", body.quote_id)
    t = await ctx.insert("quote_templates", {"name": body.name.strip(), "blocks": qb.blocks_of(q), "total_ttc": q["total_ttc"], "source_number": q["number"], **{k: q[k] for k in BODY if k in q}})
    return {"id": t["id"], "name": t["name"]}


@router.delete("/quote-templates/{tid}")
async def delete_quote_template(tid: str, ctx: Ctx = Depends(need("finance:read"))):
    quote_writer(ctx)
    await ctx.delete("quote_templates", tid)
    return {"ok": True}


@router.post("/quote-templates/{tid}/use")
async def use_quote_template(tid: str, body: UseIn, ctx: Ctx = Depends(need("finance:read"))):
    quote_writer(ctx)
    t = await ctx.get("quote_templates", tid)
    ev = await ctx.get("events", body.event_id) if body.event_id else None
    return await build_quote(ctx, t, ev, DupIn(client="event", dates="event", prices=body.prices), f"Créé à partir du modèle « {t['name']} »", {"template_id": tid})
