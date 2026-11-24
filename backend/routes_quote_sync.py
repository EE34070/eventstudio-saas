"""Devis → événement : recalcul complet (montants, matériel, CRM), import de devis externes et rapprochement catalogue."""
import re
import secrets
from difflib import SequenceMatcher
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import routes_quote_blocks as qb
from core import Ctx, db, need, new_id, now_iso
from routes_billing import hist, next_number, plus_days, quote_writer, today, totals
from routes_supplier_quotes import norm

router = APIRouter(prefix="/api")
FIN = need("finance:read")
ORDER = ["accepte", "negociation", "vu", "envoye", "brouillon"]
SERVICE = re.compile(r"\b(dj|technicien|regisseur|transport|livraison|retrait|installation|montage|demontage|forfait|prestation|frais|main d ?oeuvre|deplacement|remise|animation|saxophoniste|musicien|chauffeur|hebergement)\b")


def is_import(q: dict) -> bool:
    return q.get("created_from") == "import"


def unmatched_of(q: dict) -> int:
    if not is_import(q) or q.get("import_flat"):
        return 0
    return sum(1 for b in q.get("blocks") or [] if b["type"] == "line" and not b.get("equipment_id") and not b.get("pack_id") and not b.get("match"))


def pick(qs: list) -> Optional[dict]:
    for s in ORDER:
        c = [q for q in qs if q["status"] == s]
        if c:
            return max(c, key=lambda q: q.get("created_at", ""))
    return None


async def recalc_event(org_id: str, eid: str, by: str = "Système") -> dict:
    key = {"org_id": org_id}
    ev = await db.events.find_one({**key, "id": eid}, {"_id": 0}) if eid else None
    if not ev:
        return {}
    qs = await db.quotes.find({**key, "event_id": eid, "active": {"$ne": False}}, {"_id": 0}).to_list(500)
    import routes_stock
    acc = sorted([x for x in qs if x["status"] == "accepte"], key=lambda x: x.get("created_at", ""))
    shown = acc or ([pick(qs)] if pick(qs) else [])
    eqs = {e["id"]: e async for e in db.equipment.find(key, {"_id": 0})}
    own = [l for l in ev.get("equipment", []) if not l.get("from_quote")]
    applied = [x for x in acc if x.get("origin") != "direct" and (is_import(x) or not own)]
    apply, want, q = bool(applied), {}, None
    equipment = own + [l for l in ev.get("equipment", []) if l.get("from_quote") and l.get("state_out")]
    prestations = [p for p in ev.get("prestations", []) if not p.get("from_quote")]
    from routes_quotes import guess_module
    from routes_units import to_pieces
    days = max(1, ev.get("rental_days", 1))
    for q in applied:
        by_id = {b["id"]: b for b in q.get("blocks") or []}
        for l in q.get("lines") or []:
            if l.get("kind") == "title":
                continue
            parts = routes_stock.pack_parts(l, eqs)
            if parts is not None:
                for i, n in parts.items():
                    want.setdefault(i, {"qty": 0, "amount": 0})["qty"] += n
                prestations.append({"id": secrets.token_hex(8), "module": guess_module(l["label"]) or "", "title": l["label"], "price": round(l["qty"] * l["unit_price"], 2), "cost": 0, "fields": {}, "from_quote": q["id"]})
            elif l.get("equipment_id") in eqs:
                mob = l["qty"] - (l.get("reused") or 0)
                n = (to_pieces(eqs[l["equipment_id"]], mob, l.get("uom") or "") or 1) if mob > 0 else 0
                w = want.setdefault(l["equipment_id"], {"qty": 0, "amount": 0})
                w["qty"], w["amount"] = w["qty"] + n, w["amount"] + l["qty"] * l["unit_price"]
            elif l.get("pack_id"):
                pack = await db.packs.find_one({**key, "id": l["pack_id"]}, {"_id": 0}) or {}
                for it in pack.get("items", []):
                    if it["equipment_id"] in eqs:
                        want.setdefault(it["equipment_id"], {"qty": 0, "amount": 0})["qty"] += it["qty"] * l["qty"]
                prestations.append({"id": secrets.token_hex(8), "module": "loueur_materiel", "title": l["label"], "price": round(l["qty"] * l["unit_price"], 2), "cost": 0, "fields": {}, "from_quote": q["id"]})
            elif (by_id.get(l.get("block_id")) or {}).get("match") != "ignore":
                prestations.append({"id": secrets.token_hex(8), "module": guess_module(l["label"]) or "", "title": l["label"], "price": round(l["qty"] * l["unit_price"], 2), "cost": 0, "fields": {}, "from_quote": q["id"]})
    q = shown[0] if shown else None
    if apply:
        have = {l["equipment_id"] for l in equipment}
        equipment += [{"equipment_id": i, "qty": int(w["qty"]) if float(w["qty"]).is_integer() else w["qty"], "entered_qty": None, "entered_uom": "", "price_day": round(w["amount"] / w["qty"] / days, 4) if w["qty"] else 0,
                       "state_out": "", "state_in": "", "qty_returned": 0, "section_id": "", "from_quote": q["id"]} for i, w in want.items() if i not in have and w["qty"] > 0]
    ev.update(equipment=equipment, prestations=prestations, quote_ht=round(sum(x["total_ht"] for x in shown), 2) if q else None, quote_ttc=round(sum(x["total_ttc"] for x in shown), 2) if q else None)
    if q and q["status"] == "accepte" and ev["status"] in ("demande", "devis_envoye"):
        ev["status"] = "confirme"
    try:
        from routes_ops import normalize
        ev = normalize(ev, eqs)
    except HTTPException:
        pass
    un, flat = sum(unmatched_of(x) for x in shown), any(x.get("import_flat") for x in shown)
    keys = ("equipment", "prestations", "status", "rental_days", "amount_equipment", "amount_services", "amount_ht", "amount_ttc", "costs_total", "quote_ht", "quote_ttc")
    await db.events.update_one({**key, "id": eid}, {"$set": {**{k: ev.get(k) for k in keys}, "quote_id": q["id"] if q else "", "quote_unmatched": un, "quote_flat": flat, "updated_at": now_iso()}})
    await routes_stock.reallocate(org_id, eid)
    if apply and equipment:
        import routes_logistics
        await routes_logistics.generate(org_id, ev, by)
    if q:
        async for o in db.opportunities.find({**key, "$or": [{"event_id": eid}, {"quote_ids": q["id"]}]}, {"_id": 0}):
            upd = {"amount": ev.get("quote_ht") or q["total_ht"], "amount_tax_mode": "ht", "quote_ids": list(dict.fromkeys((o.get("quote_ids") or []) + [q["id"]])), "event_id": o.get("event_id") or eid}
            upd["weighted_amount"] = round(upd["amount"] * (o.get("probability") or 0) / 100, 2)
            await db.opportunities.update_one({**key, "id": o["id"]}, {"$set": upd})
    return {"event_id": eid, "quote": q["number"] if q else None, "quote_ht": ev.get("quote_ht"), "equipment": len(equipment), "unmatched": un, "flat": flat}


# ---------- Rapprochement des lignes avec le catalogue ----------
async def _memo(org_id: str) -> dict:
    return {m["key"]: m async for m in db.quote_label_map.find({"org_id": org_id}, {"_id": 0})}


def _guess(label: str, ref: str, eqs: list, memo: dict) -> tuple:
    """(equipment_id | '', match, sûr ?, suggestion)"""
    k = norm(label)
    m = memo.get(k)
    if m:
        return m.get("equipment_id", ""), m.get("match", ""), True, None
    e = next((e for e in eqs if ref and norm(e.get("ref")) == norm(ref)), None) or next((e for e in eqs if norm(e["name"]) == k), None)
    if e:
        return e["id"], "", True, None
    if SERVICE.search(k):
        return "", "service", True, None
    best = max(eqs, key=lambda e: SequenceMatcher(None, k, norm(e["name"])).ratio(), default=None)
    ok = best and SequenceMatcher(None, k, norm(best["name"])).ratio() >= 0.72
    return "", "", False, {"equipment_id": best["id"], "name": best["name"]} if ok else None


async def auto_match(org_id: str, blocks: list) -> tuple:
    eqs = [e async for e in db.equipment.find({"org_id": org_id, "archived": {"$ne": True}}, {"_id": 0, "id": 1, "name": 1, "ref": 1})]
    memo, done, todo = await _memo(org_id), 0, 0
    for b in blocks:
        if b["type"] != "line" or b.get("equipment_id") or b.get("pack_id") or b.get("match"):
            continue
        eid, match, sure, _ = _guess(b["label"], b.get("import_ref", ""), eqs, memo)
        if sure:
            b.update(equipment_id=eid, match=match, **({"kind": "catalog"} if eid else {}))
            done += 1
        else:
            todo += 1
    return done, todo


@router.get("/quotes/{qid}/matching")
async def get_matching(qid: str, ctx: Ctx = Depends(FIN)):
    q = await ctx.get("quotes", qid)
    eqs = [{"id": e["id"], "name": e["name"], "ref": e.get("ref", "")} for e in await ctx.list("equipment", {"archived": {"$ne": True}}, sort=[("name", 1)], limit=20000)]
    memo, by = await _memo(ctx.org_id), {e["id"]: e for e in eqs}
    rows = []
    for b in q.get("blocks") or []:
        if b["type"] != "line" or b.get("pack_id"):
            continue
        sug = None if b.get("equipment_id") or b.get("match") else _guess(b["label"], "", eqs, memo)[3]
        rows.append({"block_id": b["id"], "label": b["label"], "qty": b["qty"], "equipment_id": b.get("equipment_id", ""), "equipment_name": (by.get(b.get("equipment_id")) or {}).get("name", ""),
                     "action": "existing" if b.get("equipment_id") else b.get("match") or "", "suggestion": sug})
    return {"number": q["number"], "rows": rows, "equipment": eqs, "can_create": ctx.can("catalog:write"), "unmatched": unmatched_of(q), "flat": bool(q.get("import_flat"))}


class MatchRow(BaseModel):
    block_id: str
    action: Literal["", "existing", "new", "service", "ignore"]
    equipment_id: str = ""
    category: str = Field("", max_length=80)


class MatchIn(BaseModel):
    rows: List[MatchRow] = Field(max_length=600)


@router.put("/quotes/{qid}/matching")
async def put_matching(qid: str, body: MatchIn, ctx: Ctx = Depends(FIN)):
    quote_writer(ctx)
    q = await ctx.get("quotes", qid)
    by = {b["id"]: b for b in q.get("blocks") or [] if b["type"] == "line"}
    for r in body.rows:
        b = by.get(r.block_id)
        if not b:
            continue
        if r.action == "new":
            if not ctx.can("catalog:write"):
                raise HTTPException(403, "Votre profil ne permet pas de créer un article du catalogue")
            from routes_ops import QuickProductIn, quick_product
            r.equipment_id = (await quick_product(QuickProductIn(name=b["label"], category=r.category or "À classer", price_day=b.get("unit_price") or 0), ctx))["id"]
        if r.action in ("existing", "new"):
            await ctx.get("equipment", r.equipment_id)
            b.update(equipment_id=r.equipment_id, match="", kind="catalog")
        else:
            b.update(equipment_id="", match=r.action, kind="service")
        if r.action:
            await db.quote_label_map.update_one({"org_id": ctx.org_id, "key": norm(b["label"])}, {"$set": {"equipment_id": b["equipment_id"], "match": b["match"], "label": b["label"], "updated_at": now_iso()}}, upsert=True)
    blocks = q["blocks"]
    await db.quotes.update_one(ctx.q({"id": qid}), {"$set": {"blocks": blocks, "lines": qb.flatten(blocks, q.get("global_discount_percent", 0)), "updated_at": now_iso()},
                                                     "$push": {"history": hist(ctx, "Matériel", "Correspondances catalogue mises à jour")}})
    await recalc_event(ctx.org_id, q.get("event_id", ""), ctx.member.get("name"))
    return await get_matching(qid, ctx)


@router.post("/events/{eid}/recalc-quotes")
async def recalc(eid: str, ctx: Ctx = Depends(FIN)):
    quote_writer(ctx)
    await ctx.get("events", eid)
    return await recalc_event(ctx.org_id, eid, ctx.member.get("name"))


# ---------- Import d'un devis fait hors de l'application ----------
class ImportLine(BaseModel):
    ref: str = Field("", max_length=80)
    label: str = Field(min_length=1, max_length=300)
    qty: float = Field(1, gt=0, le=100000)
    unit_price: float = Field(0, ge=0, le=10000000)
    vat: float = Field(20, ge=0, le=100)


class ImportIn(BaseModel):
    ref: str = Field(min_length=1, max_length=60)
    event_id: str = ""
    status: Literal["brouillon", "envoye", "vu", "negociation", "accepte", "refuse", "expire"] = "envoye"
    date: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    total_ht: float = Field(ge=0, le=100000000)
    vat_rate: float = Field(20, ge=0, le=100)
    deposit_percent: float = Field(30, ge=0, lt=100)
    lines: List[ImportLine] = Field(default_factory=list, max_length=500)


@router.post("/quotes/import")
async def import_quote(body: ImportIn, ctx: Ctx = Depends(FIN)):
    quote_writer(ctx)
    old = await db.quotes.find_one(ctx.q({"import_ref": body.ref}), {"_id": 0})
    if old:
        return {**old, "already_imported": True}
    ev = await ctx.get("events", body.event_id) if body.event_id else None
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}) or {}
    c = await db.contacts.find_one(ctx.q({"id": ev.get("client_id")}), {"_id": 0}) if ev and ev.get("client_id") else None
    sec = new_id()
    flat = not body.lines
    src = body.lines or [ImportLine(label=f"Prestation selon devis importé n° {body.ref}", unit_price=body.total_ht, vat=body.vat_rate)]
    blocks = [qb.Block(id=sec, type="section", title=f"Devis importé n° {body.ref}").model_dump()] + \
        [{**qb.Block(id=new_id(), parent_id=sec, type="line", label=l.label, qty=l.qty, unit_price=l.unit_price, vat=l.vat).model_dump(), "import_ref": l.ref} for l in src]
    done, todo = (0, 0) if flat else await auto_match(ctx.org_id, blocks)
    lines = qb.flatten(blocks)
    tot, day = totals(lines), body.date or today()
    from routes_main import contact_name
    doc = await ctx.insert("quotes", {
        "number": await next_number(ctx, "quote", org.get("quote_prefix") or "DEV"), "created_from": "import", "import_ref": body.ref, "import_flat": flat, "import_total_ht": body.total_ht, "import_gap": round(tot["total_ht"] - body.total_ht, 2),
        "event_id": ev["id"] if ev else "", "event_code": ev["code"] if ev else "", "event_title": ev["title"] if ev else "", "event_date": ev["start"][:10] if ev and not ev.get("date_tbc") else "",
        "client_id": (ev or {}).get("client_id", ""), "client": {"name": contact_name(c), "address": c.get("address", ""), "city": c.get("city", ""), "email": c.get("email", "")} if c else {"name": ""},
        "status": body.status, "date": day, "valid_until": plus_days(day, 30), "blocks": blocks, "lines": lines, "deposit_percent": body.deposit_percent, "notes": f"Réf. import {body.ref}", "language": (ev or {}).get("language") or "fr-FR",
        "global_discount_percent": 0, "price_display": "detailed", "numbering": False, "client_modified": False, **tot, "history": [hist(ctx, "Création", f"Devis importé (réf. {body.ref}) : {done} ligne(s) rapprochée(s), {todo} à rapprocher")]})
    if ev:
        if body.status == "accepte":
            from routes_quotes import on_accept
            await on_accept(ctx.org_id, doc["id"], ctx.member.get("name"))
        await recalc_event(ctx.org_id, ev["id"], ctx.member.get("name"))
    return {**doc, "matched": done, "to_match": todo}


# ---------- Reprise de l'existant (relançable, sans doublon) ----------
async def repair(org_id: str, apply: bool) -> dict:
    rep = {"devis_importes": 0, "lignes_forfaitaires": 0, "lignes_rapprochees": 0, "lignes_a_rapprocher": 0, "ecarts_de_montant": [], "sans_evenement": [], "evenements_recalcules": 0, "evenements": []}
    events = set()
    async for q in db.quotes.find({"org_id": org_id, "active": {"$ne": False}, "$or": [{"created_from": "import"}, {"notes": {"$regex": r"^R[ée]f\. (Odoo|import)"}}]}, {"_id": 0}):
        rep["devis_importes"] += 1
        blocks, upd = qb.blocks_of(q), {"created_from": "import"}
        m = re.match(r"^R[ée]f\. (?:Odoo|import) (\S+)", q.get("notes") or "")
        if m and not q.get("import_ref"):
            upd["import_ref"] = m.group(1)
        if not any(b["type"] == "line" for b in blocks) and (q.get("total_ht") or q.get("import_total_ht")):
            sec, ht = new_id(), q.get("import_total_ht") or q["total_ht"]
            blocks = [qb.Block(id=sec, type="section", title=f"Devis importé n° {q['number']}").model_dump(), qb.Block(id=new_id(), parent_id=sec, type="line", label=f"Prestation selon devis importé n° {q['number']}", unit_price=ht).model_dump()]
            upd["import_flat"] = True
            rep["lignes_forfaitaires"] += 1
        elif not q.get("import_flat"):
            done, todo = await auto_match(org_id, blocks)
            rep["lignes_rapprochees"] += done
            rep["lignes_a_rapprocher"] += todo
        lines = qb.flatten(blocks, q.get("global_discount_percent", 0))
        tot = totals(lines) if lines else {}
        if lines and abs(tot["total_ht"] - (q.get("total_ht") or 0)) > 0.01:
            rep["ecarts_de_montant"].append({"devis": q["number"], "lignes": tot["total_ht"], "total": q.get("total_ht")})
        if not q.get("event_id"):
            rep["sans_evenement"].append(q["number"])
        else:
            events.add(q["event_id"])
        if apply:
            await db.quotes.update_one({"org_id": org_id, "id": q["id"]}, {"$set": {**upd, "blocks": blocks, "lines": lines, **(tot if not q.get("total_ht") else {})}})
    for eid in events:
        ev = await db.events.find_one({"org_id": org_id, "id": eid}, {"_id": 0, "code": 1, "amount_ht": 1})
        if not ev:
            continue
        after = (await recalc_event(org_id, eid, "Reprise devis importés")).get("quote_ht") if apply else None
        rep["evenements"].append({"code": ev["code"], "avant": ev.get("amount_ht"), "apres": after})
        rep["evenements_recalcules"] += 1 if apply else 0
    return rep


# ---------- Liste des devis : onglets de statut, filtres, tri et export (côté serveur) ----------
import csv  # noqa: E402
import io  # noqa: E402
from datetime import date, timedelta  # noqa: E402

from fastapi import Request, Response  # noqa: E402

GROUPS = {"to_process": ["brouillon", "envoye", "vu", "negociation"], "accepted": ["accepte"], "closed": ["refuse", "expire"], "all": None}
SORTS = {"number": "number", "client": "client", "event": "event_title", "event_date": "event_date", "venue": "venue", "brand": "brand", "total_ht": "total_ht", "total_ttc": "total_ttc", "status": "status", "sent_at": "sent_at",
         "valid_until": "valid_until", "last_activity": "last_activity", "owner": "owner", "accepted_at": "accepted_at"}
_indexed = False


async def _search(request: Request, ctx: Ctx) -> dict:
    global _indexed
    if not _indexed:
        await db.quotes.create_index([("org_id", 1), ("status", 1), ("event_date", 1)])
        _indexed = True
    p = request.query_params
    money = "sale_prices" not in (getattr(request.state, "hide", None) or set())
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "quote_followup_days": 1}) or {}
    evs = {e["id"]: e async for e in db.events.find(ctx.q({}), {"_id": 0, "id": 1, "venue_id": 1, "chef_projet_id": 1})}
    venues = {v["id"]: v["name"] async for v in db.venues.find(ctx.q({}), {"_id": 0, "id": 1, "name": 1})}
    team = {t["id"]: t["name"] async for t in db.team.find(ctx.q({}), {"_id": 0, "id": 1, "name": 1})}
    djm = {m["event_id"] async for m in db.event_modules.find(ctx.q({"module_key": "dj", "status": "actif"}), {"event_id": 1})}
    me = {ctx.member.get("id"), ctx.member.get("user_id"), ctx.member.get("team_id")} - {None, ""}
    today_, soon, late = date.today().isoformat(), (date.today() + timedelta(days=7)).isoformat(), (date.today() - timedelta(days=org.get("quote_followup_days") or 5)).isoformat()
    rows = []
    async for q in db.quotes.find(ctx.q({"active": {"$ne": False}}), {"_id": 0, "blocks": 0, "lines": 0}):
        ev, h = evs.get(q.get("event_id")) or {}, q.get("history") or []
        rows.append({"id": q["id"], "number": q["number"], "status": q["status"], "client": (q.get("client") or {}).get("name", ""), "client_id": q.get("client_id", ""), "event_id": q.get("event_id", ""), "event_code": q.get("event_code", ""),
                     "event_title": q.get("event_title", ""), "event_date": q.get("event_date", ""), "venue_id": ev.get("venue_id", ""), "venue": venues.get(ev.get("venue_id"), ""), "total_ht": q.get("total_ht") or 0, "total_ttc": q.get("total_ttc") or 0,
                     "sent_at": (q.get("sent_at") or "")[:10], "valid_until": q.get("valid_until", ""), "created_at": q.get("created_at", "")[:10], "last_activity": (h[-1].get("at") if h else q.get("updated_at") or q.get("created_at") or "")[:16],
                     "brand": q.get("brand") or ("Le Frenchie" if q.get("event_id") in djm else "Exclusivity Events"), "owner_id": ev.get("chef_projet_id", ""), "owner": team.get(ev.get("chef_projet_id"), ""), "created_from": q.get("created_from") or ("devis" if q.get("origin") == "direct" else "evenement"),
                     "accepted_at": next((x.get("at", "")[:16] for x in reversed(h) if q["status"] == "accepte" and x.get("action") in ("Statut", "Signature")), ""), "expiring": q["status"] in GROUPS["to_process"] and bool(q.get("valid_until")) and q["valid_until"] <= soon,
                     "to_follow_up": q["status"] in ("envoye", "vu") and ((q.get("sent_at") or q.get("updated_at") or q.get("created_at") or "")[:10] <= late)})
    t, quick, st = norm(p.get("q", "")), set(p.getlist("quick")), [s for s in p.getlist("status") if s in ORDER + ["refuse", "expire"]]
    field = {"event": "event_date", "created": "created_at", "sent": "sent_at"}.get(p.get("period", "event"), "event_date")
    lo, hi = (float(p[k]) if money and p.get(k) else None for k in ("min_ht", "max_ht"))
    keep = lambda r: ((not t or t in norm(f"{r['number']} {r['client']} {r['event_title']} {r['event_code']} {r['venue']}"))  # noqa: E731
                      and all(not p.get(k) or r[k] == p[k] for k in ("event_id", "client_id", "venue_id", "owner_id", "created_from"))
                      and (not p.get("date_from") or (r[field] and r[field] >= p["date_from"])) and (not p.get("date_to") or (r[field] and r[field] <= p["date_to"]))
                      and (lo is None or r["total_ht"] >= lo) and (hi is None or r["total_ht"] <= hi)
                      and ("follow_up" not in quick or r["to_follow_up"]) and ("expiring" not in quick or r["expiring"]) and ("mine" not in quick or r["owner_id"] in me))
    rows = [r for r in rows if keep(r)]
    counts = {g: sum(1 for r in rows if s is None or r["status"] in s) for g, s in GROUPS.items()}
    group = p.get("group") if p.get("group") in GROUPS else "to_process"
    wanted = st or GROUPS[group]
    rows = [r for r in rows if wanted is None or r["status"] in wanted]
    if p.get("ids"):
        rows = [r for r in rows if r["id"] in set(p["ids"].split(","))]
    sort = SORTS.get(p.get("sort", ""), "")
    if sort in ("total_ht", "total_ttc") and not money:
        sort = ""
    desc = p.get("dir") == "desc" if sort else group == "accepted"
    sort = sort or ("accepted_at" if group == "accepted" else "event_date")
    rows.sort(key=lambda r: (r[sort] in ("", None), r[sort] if isinstance(r[sort], (int, float)) else str(r[sort]).lower()), reverse=desc)
    if desc:
        rows.sort(key=lambda r: r[sort] in ("", None))
    return {"rows": rows, "counts": counts, "group": "custom" if st else group, "money": money, "footer": {"count": len(rows), **({"total_ht": round(sum(r["total_ht"] for r in rows), 2)} if money else {})},
            "follow_up_days": org.get("quote_followup_days") or 5, "owners": [{"id": k, "name": v} for k, v in team.items()], "venues": [{"id": k, "name": v} for k, v in sorted(venues.items(), key=lambda x: x[1])]}


@router.get("/quote-list")
async def quote_list(request: Request, page: int = 1, size: int = 50, ctx: Ctx = Depends(FIN)):
    out = await _search(request, ctx)
    size = max(1, min(size, 200))
    return {**out, "rows": out["rows"][(max(1, page) - 1) * size:max(1, page) * size], "page": max(1, page), "size": size}


@router.get("/quote-list/csv")
async def quote_csv(request: Request, ctx: Ctx = Depends(FIN)):
    out = await _search(request, ctx)
    cols = [("number", "N°"), ("client", "Client"), ("event_title", "Événement"), ("event_date", "Date de l'événement"), ("venue", "Lieu"), ("brand", "Marque"), *([("total_ht", "Montant HT"), ("total_ttc", "Montant TTC")] if out["money"] else []),
            ("status", "Statut"), ("sent_at", "Date d'envoi"), ("valid_until", "Expiration"), ("last_activity", "Dernière activité"), ("owner", "Responsable")]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([l for _, l in cols])
    for r in out["rows"]:
        w.writerow([str(r[k]).replace(".", ",") if isinstance(r[k], float) else r[k] for k, _ in cols])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="devis.csv"'})


# ---------- Packs à composition fixe (article du catalogue de type Pack) ----------
class Comp(BaseModel):
    equipment_id: str
    qty: float = Field(1, gt=0, le=10000)
    visible_client: bool = True
    client_label: str = Field("", max_length=160)
    client_label_en: str = Field("", max_length=160)
    note: str = Field("", max_length=300)
    show_exact_reference: bool = False


class PackCompIn(BaseModel):
    comment: str = Field("", max_length=300)
    components: List[Comp] = Field(max_length=60)
    pricing_mode: Literal["fixed", "sum"] = "fixed"
    pricing_coef: float = Field(1, gt=0, le=10)


@router.put("/equipment/{eid}/pack")
async def put_pack(eid: str, body: PackCompIn, ctx: Ctx = Depends(need("catalog:write"))):
    cur = await ctx.get("equipment", eid)
    for c in body.components:
        x = await ctx.get("equipment", c.equipment_id)
        if c.equipment_id == eid or (x.get("product_type") == "Pack" and any((await ctx.get("equipment", s["equipment_id"])).get("product_type") == "Pack" for s in x.get("components") or [])):
            raise HTTPException(400, "Un pack peut contenir un autre pack, sur un seul niveau")
    new = body.model_dump(exclude={"comment"})
    out = await ctx.update("equipment", eid, {**new, "product_type": "Pack"})
    if new["components"] != (cur.get("components") or []):
        import routes_pack_i18n
        out["version"] = await routes_pack_i18n.bump(ctx, out, body.comment, not cur.get("components"))
    return out


class RemindIn(BaseModel):
    ids: List[str] = Field(min_length=1, max_length=50)
    send: bool = False


@router.post("/quote-list/remind")
async def remind(body: RemindIn, request: Request, ctx: Ctx = Depends(FIN)):
    """Relance groupée : aperçu de chaque e-mail ; l'envoi (send=true) passe par l'envoi de devis habituel."""
    quote_writer(ctx)
    import routes_comms as rc
    org, out = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}) or {}, []
    for qid in body.ids:
        q = await ctx.get("quotes", qid)
        c = await rc.client_of(q)
        lg = c["language"]
        row = {"id": qid, "number": q["number"], "to": c["email"], "subject": rc.tr("mail_quote_subject", lg, n=q["number"], org=org.get("name", "")),
               "body": [rc.tr("hello", lg, name=c["name"]), rc.tr("mail_quote_1", lg, n=q["number"], title=q["event_title"], ttc=rc.money(q["total_ttc"], lg)), rc.tr("mail_quote_2", lg, date=rc.fmt_date(q.get("valid_until", ""), lg)), rc.tr("mail_quote_3", lg)],
               "ok": bool(c["email"]) and q["status"] in ("envoye", "vu"), "why": "" if c["email"] else "Pas d'adresse e-mail"}
        if not row["why"] and not row["ok"]:
            row["why"] = "Seuls les devis envoyés ou vus se relancent"
        if body.send and row["ok"]:
            try:
                await rc.send_quote(qid, request, True, ctx)
                row["sent"] = True
            except HTTPException as e:
                row["why"] = str(e.detail)
        out.append(row)
    return out
