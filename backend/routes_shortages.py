"""Manques de matériel : liste par événement, solutions, « À acheter », demandes aux partenaires. Jamais visible côté client."""
import secrets
from html import escape
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

import routes_stock as rs
from core import Ctx, db, need, new_id, now_iso
from routes_ops import holds, period
from security import APP_ENV, link_token, sha256

router = APIRouter(prefix="/api")
R, W = need("events:read"), need("events:write")
OPEN = {"$ne": "resolu"}
SOLUTIONS = {"transfert": "Transfert depuis un autre entrepôt", "partenaire": "Demande partenaire / location externe", "achat": "Achat", "substitution": "Substitution", "reduction": "Quantité réduite"}


def _by_wh(w: dict, evs: list, pid: str, venue: str, sp: tuple, exclude: str) -> list:
    res, mt, lv = rs.reserved(w, evs, pid, sp, exclude), rs.maint(w, pid), w["levels"].get(pid, {})
    return [{"warehouse_id": x["id"], "name": x["name"], "qty": max(0, lv.get(x["id"], 0) - mt.get(x["id"], 0) - res.get(x["id"], 0))} for x in rs.usable(w, venue)]


def rows_of(ev: dict, w: dict, evs: list, missing: list, lines: list) -> dict:
    out, (start, end) = {}, period(ev)
    for m in missing:
        pid, auto = m["equipment_id"], bool(m.get("auto"))
        src = [x for x in lines if x["auto_added"] and x["linked_product_id"] == pid] if auto else []
        out[f"{pid}:{'auto' if auto else 'line'}"] = {
            "secondary_uom": (w["eqs"].get(pid) or {}).get("secondary_uom") or "", "missing_secondary": round(m["missing"] * ((w["eqs"].get(pid) or {}).get("qty_per_piece") or 0), 3),
            "stock_uom": (w["eqs"].get(pid) or {}).get("stock_uom") or "piece",
            "product_id": pid, "auto": auto, "ref": m.get("ref", ""), "name": m.get("name", ""), "requested": m["requested"], "available": m["available"], "missing": m["missing"],
            "by_warehouse": _by_wh(w, evs, pid, rs.target(ev), rs.buffered((start, end), w["eqs"].get(pid) or {}), ev["id"]), "date_from": start, "date_to": end,
            "origin": " ; ".join(f"{x['label']} pour {x['source_qty']} × {x['source_name']}" for x in src) or "Composant de nomenclature (scène)" if auto else "Ligne de matériel / devis"}
    return out


def summary_of(rows: list) -> str:
    n = len(rows)
    return f"{n} manque{'s' if n > 1 else ''} : " + ", ".join(f"{r['missing']:g} × {r['name']}" + (f" ({r['missing_secondary']:g} {r['secondary_uom']})" if r.get("secondary_uom") and r.get("missing_secondary") else "") for r in rows) if n else ""


async def sync(org_id: str, ev: dict, w: dict, evs: list, missing: list, lines: list) -> None:
    cur = rows_of(ev, w, evs, missing, lines) if holds(ev) else {}
    old = {d["key"]: d async for d in db.shortages.find({"org_id": org_id, "event_id": ev["id"]}, {"_id": 0})}
    for k, d in cur.items():
        o = old.get(k)
        if not o:
            await db.shortages.insert_one({"id": new_id(), "org_id": org_id, "event_id": ev["id"], "key": k, **d, "status": "a_traiter", "solution": None, "resolved_auto": False, "created_at": now_iso(), "updated_at": now_iso()})
            continue
        upd = {**d, "updated_at": now_iso()}
        if o["status"] == "resolu" and o.get("resolved_auto"):
            upd.update({"status": "solution" if o.get("solution") else "a_traiter", "resolved_auto": False})
        await db.shortages.update_one({"org_id": org_id, "id": o["id"]}, {"$set": upd})
    for k, o in old.items():
        if k not in cur and o["status"] != "resolu":
            await db.shortages.update_one({"org_id": org_id, "id": o["id"]}, {"$set": {"status": "resolu", "resolved_auto": True, "missing": 0, "available": o["requested"], "updated_at": now_iso()}})


async def counts(org_id: str) -> dict:
    return {r["_id"]: r["n"] async for r in db.shortages.aggregate([{"$match": {"org_id": org_id, "status": OPEN}}, {"$group": {"_id": "$event_id", "n": {"$sum": 1}}}])}


async def bell(ctx: Ctx) -> list:
    if ctx.event_scope():
        return []
    cnt = await counts(ctx.org_id)
    evs = await ctx.list("events", {"id": {"$in": list(cnt)}, "status": {"$ne": "cloture"}})
    return [{"type": "manque", "severity": "danger", "event_id": e["id"], "title": "Manques de matériel à traiter", "detail": f"{e['code']} · {e['title']} : {cnt[e['id']]} manque(s) à traiter."} for e in evs]


async def notify_confirmed(org_id: str, ev: dict) -> None:
    """Après signature du client : tâche urgente interne (+ e-mail interne en production uniquement)."""
    rows = await db.shortages.find({"org_id": org_id, "event_id": ev["id"], "status": OPEN}, {"_id": 0}).to_list(200)
    ref = f"shortage:{ev['id']}"
    if not rows or await db.tasks.find_one({"org_id": org_id, "source_ref": ref, "status": {"$ne": "done"}, "deleted_at": None}):
        return
    title = f"Événement {ev['code']} · {ev['title']} confirmé — {len(rows)} manque{'s' if len(rows) > 1 else ''} à traiter"
    await db.tasks.insert_one({"id": new_id(), "org_id": org_id, "created_at": now_iso(), "title": title, "description": summary_of(rows), "due_at": rs.today(), "due_date": rs.today(), "priority": "urgent",
                               "assignee_ids": [], "event_id": ev["id"], "status": "todo", "done": False, "done_at": None, "checklist": [], "attachments": [], "source": "auto", "source_ref": ref,
                               "created_by": "Système", "created_by_id": ""})
    if APP_ENV == "production":
        from emailer import send_email
        async for u in db.users.find({"org_id": org_id, "role": {"$in": ["admin", "gerant"]}, "status": {"$nin": ["suspended", "deleted", "disabled"]}}, {"_id": 0, "email": 1}):
            if u.get("email"):
                await send_email(to=u["email"], subject=title, html=f"<p>{escape(title)}</p><p>{escape(summary_of(rows))}</p>")


async def _event(ctx: Ctx, eid: str) -> dict:
    return await ctx.get("events", eid, ctx.event_scope())


async def _lines(ctx: Ctx, eid: str) -> list:
    return await ctx.list("shortages", {"event_id": eid}, sort=[("status", 1), ("name", 1)])


@router.get("/events/{eid}/shortages/preview")
async def preview(eid: str, ctx: Ctx = Depends(R)):
    from routes_material import auto_of, build
    ev = await _event(ctx, eid)
    reqs = {e["id"]: e for e in await ctx.list("equipment", {"id": {"$in": [l["equipment_id"] for l in ev.get("equipment", [])]}})}
    lines = build(ev, reqs)[0]
    sim = {**ev, "status": "confirme", "allocations": [], "auto_equipment": [{"equipment_id": p, "qty": n} for p, n in sorted(auto_of(lines).items())]}
    w, evs = await rs.world(ctx.org_id), await rs._evs(ctx.org_id)
    rows = list(rows_of(sim, w, evs, rs.plan_event(w, evs, sim)[1], lines).values())
    return {"lines": rows, "summary": summary_of(rows)}


@router.get("/events/{eid}/shortages")
async def event_shortages(eid: str, ctx: Ctx = Depends(R)):
    from routes_material import compute
    ev = await _event(ctx, eid)
    if ev["status"] != "cloture":
        await rs.reallocate(ctx.org_id, eid)
    rows = await _lines(ctx, eid)
    alerts = [a for a in (await compute(ctx, ev))["alerts"] if not a.startswith("Stock insuffisant")] if holds(ev) else []
    if holds(ev) and not ev.get("team") and not any("echnicien" in a for a in alerts):
        alerts.append("Aucun technicien affecté à l'événement")
    if ctx.can("finance:costs"):
        import routes_suppliers as sup
        for r in rows:
            r["offers"] = await sup.offers(ctx.org_id, r["product_id"])
    return {"lines": rows, "alerts": alerts, "open": sum(1 for r in rows if r["status"] != "resolu"), "summary": summary_of([r for r in rows if r["status"] != "resolu"]), "solutions": SOLUTIONS,
            "requests": await _requests(ctx, eid)}


class SolutionIn(BaseModel):
    status: Optional[Literal["a_traiter", "solution", "resolu"]] = None
    solution_type: Optional[Literal["transfert", "partenaire", "achat", "substitution", "reduction"]] = None
    warehouse_id: str = ""
    substitute_id: str = ""
    qty: Optional[float] = Field(None, ge=0, le=100000)
    note: str = Field("", max_length=500)


@router.patch("/shortages/{sid}")
async def patch_shortage(sid: str, body: SolutionIn, ctx: Ctx = Depends(W)):
    s = await ctx.get("shortages", sid)
    ev = await _event(ctx, s["event_id"])
    upd, warning = {}, ""
    if body.solution_type:
        sol = {"type": body.solution_type, "label": SOLUTIONS[body.solution_type], "qty": body.qty if body.qty is not None else s["missing"], "note": body.note, "by": ctx.member.get("name"), "at": now_iso(),
               "purchase_id": (s.get("solution") or {}).get("purchase_id", "")}
        if body.solution_type == "transfert":
            sol["warehouse_id"] = body.warehouse_id
            sol["warehouse_name"] = (await ctx.get("warehouses", body.warehouse_id))["name"]
        if body.solution_type == "substitution":
            sub = await ctx.get("equipment", body.substitute_id)
            sol.update({"substitute_id": sub["id"], "substitute_name": f"{sub.get('ref', '')} {sub['name']}".strip()})
        if body.solution_type == "achat" and not sol["purchase_id"]:
            p = await ctx.insert("purchase_needs", {"product_id": s["product_id"], "label": f"{s.get('ref', '')} {s['name']}".strip(), "qty": sol["qty"], "needed_by": s["date_from"][:10], "event_id": ev["id"],
                                                    "shortage_id": sid, "status": "a_acheter", "note": f"Manque sur l'événement {ev['code']} · {ev['title']}", "deleted_at": None, "created_by": ctx.member.get("name")})
            sol["purchase_id"] = p["id"]
        if body.solution_type == "reduction" and not s["auto"]:
            nums = [q["number"] async for q in db.quotes.find(ctx.q({"event_id": ev["id"], "status": {"$nin": ["remplace", "refuse"]}, "lines.equipment_id": s["product_id"]}), {"_id": 0, "number": 1})]
            if nums:
                warning = f"Attention : cette réduction touche le devis client ({', '.join(nums)}). Le devis n'est pas modifié automatiquement."
        upd.update({"solution": sol, "status": body.status or "solution"})
    elif body.status:
        upd["status"] = body.status
    if upd:
        s = await ctx.update("shortages", sid, {**upd, "resolved_auto": False})
    return {"line": s, "warning": warning}


@router.get("/events/{eid}/shortages/pdf")
async def shortages_pdf(eid: str, ctx: Ctx = Depends(R)):
    import io
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    ev = await _event(ctx, eid)
    n, b = ParagraphStyle("n", fontName="Helvetica", fontSize=9, leading=11), ParagraphStyle("b", fontName="Helvetica-Bold", fontSize=9, leading=11)
    st = {"a_traiter": "À traiter", "solution": "Solution choisie", "resolu": "Résolu"}
    rows = [[Paragraph(x, b) for x in ("Produit", "Demandé", "Disponible", "Manquant", "Dates", "Origine", "Statut / solution")]]
    for r in await _lines(ctx, eid):
        sol = r.get("solution") or {}
        rows.append([Paragraph(escape(f"{r.get('ref', '')} {r['name']}".strip()), n), f"{r['requested']:g}", Paragraph(escape(f"{r['available']:g} (" + ", ".join(f"{x['name']} {x['qty']:g}" for x in r["by_warehouse"]) + ")"), n),
                     f"{r['missing']:g}", Paragraph(f"{r['date_from'][:10]} → {r['date_to'][:10]}", n), Paragraph(escape(r["origin"]), n),
                     Paragraph(escape(st[r["status"]] + (f" — {sol.get('label', '')} {sol.get('note', '')}" if sol else "")), n)])
    t = Table(rows, colWidths=[55 * mm, 18 * mm, 50 * mm, 18 * mm, 36 * mm, 50 * mm, 45 * mm], repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)]))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm, title="Liste des manques").build(
        [Paragraph("Liste des manques (document interne)", ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=15, leading=19)), Paragraph(escape(f"{ev['code']} · {ev['title']} · {ev['start'][:10]}"), n), Spacer(1, 5 * mm), t])
    return Response(buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="manques-{ev["code"]}.pdf"'})


@router.get("/logistics/shortages")
async def global_shortages(date_from: str = "", date_to: str = "", status: str = "open", ctx: Ctx = Depends(R)):
    for eid in list(await counts(ctx.org_id))[:30]:
        await rs.reallocate(ctx.org_id, eid)
    f: dict = {} if status == "all" else {"status": OPEN}
    if date_from:
        f["date_to"] = {"$gte": date_from}
    if date_to:
        f["date_from"] = {"$lte": date_to + "T23:59"}
    rows = await ctx.list("shortages", f, sort=[("date_from", 1), ("name", 1)])
    evs = {e["id"]: e for e in await ctx.list("events", {**ctx.event_scope(), "id": {"$in": list({r["event_id"] for r in rows})}})}
    rows = [{**r, "event_code": evs[r["event_id"]]["code"], "event_title": evs[r["event_id"]]["title"]} for r in rows if r["event_id"] in evs]
    by: dict = {}
    for r in rows:
        e = by.setdefault(r["event_id"], {"id": r["event_id"], "code": r["event_code"], "title": r["event_title"], "start": evs[r["event_id"]]["start"], "count": 0})
        e["count"] += r["status"] != "resolu"
    return {"lines": rows, "events": sorted(by.values(), key=lambda e: e["start"])}


# ---------- Achats › À acheter ----------
P = need("finance:read")


class NeedIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    qty: float = Field(1, gt=0, le=100000)
    needed_by: str = Field("", max_length=10)
    event_id: str = ""
    note: str = Field("", max_length=500)


class NeedPatch(BaseModel):
    status: Optional[Literal["a_acheter", "commande", "recu"]] = None
    qty: Optional[float] = Field(None, gt=0, le=100000)
    needed_by: Optional[str] = Field(None, max_length=10)
    note: Optional[str] = Field(None, max_length=500)


@router.get("/purchase-needs")
async def list_needs(ctx: Ctx = Depends(P)):
    rows = await ctx.list("purchase_needs", {"deleted_at": None}, sort=[("needed_by", 1)])
    evs = {e["id"]: e for e in await ctx.list("events", {"id": {"$in": [r["event_id"] for r in rows if r.get("event_id")]}})}
    import routes_suppliers as sup
    return [{**r, "event_code": (evs.get(r.get("event_id")) or {}).get("code", ""), "event_title": (evs.get(r.get("event_id")) or {}).get("title", ""),
             "offers": await sup.offers(ctx.org_id, r["product_id"]) if r.get("product_id") and ctx.can("finance:costs") else []} for r in rows]


@router.post("/purchase-needs")
async def add_need(body: NeedIn, ctx: Ctx = Depends(need("finance:write"))):
    if body.event_id:
        await ctx.get("events", body.event_id)
    return await ctx.insert("purchase_needs", {**body.model_dump(), "product_id": "", "shortage_id": "", "status": "a_acheter", "deleted_at": None, "created_by": ctx.member.get("name")})


@router.patch("/purchase-needs/{nid}")
async def patch_need(nid: str, body: NeedPatch, ctx: Ctx = Depends(need("finance:write"))):
    await ctx.get("purchase_needs", nid)
    return await ctx.update("purchase_needs", nid, body.model_dump(exclude_none=True))


@router.delete("/purchase-needs/{nid}")
async def delete_need(nid: str, ctx: Ctx = Depends(need("finance:write"))):
    await ctx.update("purchase_needs", nid, {"deleted_at": now_iso()})
    return {"ok": True}


# ---------- Demandes de matériel aux partenaires ----------
class PartnerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field("", max_length=200)


class RequestIn(BaseModel):
    partners: List[PartnerIn] = Field(min_length=1, max_length=10)
    shortage_ids: List[str] = Field(min_length=1, max_length=100)
    deadline: str = Field("", max_length=10)
    note: str = Field("", max_length=1000)


async def _requests(ctx: Ctx, eid: str) -> list:
    return [{**{k: v for k, v in r.items() if k not in ("share_nonce", "token_hash")}, "link": f"/partenaire/{link_token('partner_requests', r)}"}
            for r in await ctx.list("partner_requests", {"event_id": eid}, sort=[("created_at", 1)])]


@router.post("/events/{eid}/partner-requests")
async def create_requests(eid: str, body: RequestIn, ctx: Ctx = Depends(W)):
    ev = await _event(ctx, eid)
    rows = await ctx.list("shortages", {"event_id": eid, "id": {"$in": body.shortage_ids}, "status": OPEN})
    if not rows:
        raise HTTPException(400, "Sélectionnez au moins un manque à traiter")
    venue = await db.venues.find_one(ctx.q({"id": rs.target(ev)}), {"_id": 0, "name": 1, "city": 1}) or {}
    items = [{"shortage_id": r["id"], "product_id": r["product_id"], "name": r["name"], "qty": r["missing"]} for r in rows]
    for p in body.partners:
        doc = await ctx.insert("partner_requests", {"event_id": eid, "partner_name": p.name, "partner_email": p.email, "items": items, "date_from": rows[0]["date_from"], "date_to": rows[0]["date_to"],
                                                    "place": " ".join(x for x in (venue.get("name"), venue.get("city")) if x), "deadline": body.deadline, "note": body.note, "status": "envoyee",
                                                    "share_nonce": secrets.token_hex(16), "reply": None, "email_sent": False, "created_by": ctx.member.get("name")})
        token = link_token("partner_requests", doc)
        sent = False
        if APP_ENV == "production" and p.email:
            from emailer import send_email
            org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "name": 1}) or {}
            base = (__import__("os").environ.get("APP_URL") or "").rstrip("/")
            sent = bool(await send_email(to=p.email, subject=f"Demande de disponibilité de matériel — {org.get('name', '')}",
                                         html=f"<p>Bonjour {escape(p.name)},</p><p>Pouvez-vous nous indiquer vos disponibilités et tarifs ?</p><p><a href=\"{base}/partenaire/{token}\">Répondre à la demande</a></p>"))
        await db.partner_requests.update_one(ctx.q({"id": doc["id"]}), {"$set": {"token_hash": sha256(token), "email_sent": sent}})
    names = ", ".join(p.name for p in body.partners)
    for r in rows:
        await ctx.update("shortages", r["id"], {"status": "solution", "resolved_auto": False, "solution": {"type": "partenaire", "label": SOLUTIONS["partenaire"], "qty": r["missing"], "note": f"Demande adressée à {names}",
                                                                                                          "by": ctx.member.get("name"), "at": now_iso(), "purchase_id": (r.get("solution") or {}).get("purchase_id", "")}})
    return await _requests(ctx, eid)


@router.post("/partner-requests/{rid}/accept")
async def accept_request(rid: str, ctx: Ctx = Depends(W)):
    r = await ctx.get("partner_requests", rid)
    await _event(ctx, r["event_id"])
    if r["status"] != "repondue":
        raise HTTPException(409, "Ce partenaire n'a pas encore répondu")
    ids = [i["shortage_id"] for i in r["items"]]
    await ctx.update("partner_requests", rid, {"status": "acceptee", "accepted_at": now_iso(), "accepted_by": ctx.member.get("name")})
    await db.partner_requests.update_many(ctx.q({"event_id": r["event_id"], "id": {"$ne": rid}, "status": {"$in": ["envoyee", "repondue"]}, "items.shortage_id": {"$in": ids}}), {"$set": {"status": "non_retenue"}})
    got = {i["shortage_id"]: i["available_qty"] for i in (r.get("reply") or {}).get("items", [])}
    for s in await ctx.list("shortages", {"id": {"$in": ids}}):
        full = got.get(s["id"], 0) >= s["missing"]
        if not got.get(s["id"]):
            continue
        await ctx.update("shortages", s["id"], {"status": "resolu" if full else "solution", "resolved_auto": False, "solution": {**(s.get("solution") or {}), "type": "partenaire", "label": SOLUTIONS["partenaire"], "request_id": rid,
                                                                                                       "qty": got[s["id"]], "note": f"Couvert (partenaire {r['partner_name']})" if full else f"Couvert en partie par {r['partner_name']} : {got[s['id']]:g} sur {s['missing']:g}", "by": ctx.member.get("name"), "at": now_iso()}})
    return await _requests(ctx, r["event_id"])


async def _public(token: str) -> dict:
    r = await db.partner_requests.find_one({"token_hash": sha256(token)}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Lien introuvable")
    return r


@router.get("/public/partner-requests/{token}")
async def public_request(token: str):
    r = await _public(token)
    org = await db.orgs.find_one({"id": r["org_id"]}, {"_id": 0, "name": 1}) or {}
    return {"org": org.get("name", ""), "partner_name": r["partner_name"], "items": [{"shortage_id": i["shortage_id"], "name": i["name"], "qty": i["qty"]} for i in r["items"]], "date_from": r["date_from"],
            "date_to": r["date_to"], "place": r.get("place", ""), "deadline": r.get("deadline", ""), "note": r.get("note", ""), "status": r["status"], "answered": bool(r.get("reply"))}


class ReplyItem(BaseModel):
    shortage_id: str
    available_qty: float = Field(0, ge=0, le=100000)
    unit_cost: float = Field(0, ge=0, le=1000000)


class ReplyIn(BaseModel):
    items: List[ReplyItem] = Field(max_length=100)
    conditions: str = Field("", max_length=1000)
    comment: str = Field("", max_length=1000)


@router.post("/public/partner-requests/{token}/reply")
async def public_reply(token: str, body: ReplyIn):
    r = await _public(token)
    if r["status"] not in ("envoyee", "repondue"):
        raise HTTPException(409, "Cette demande est close")
    ok = {i["shortage_id"]: i for i in r["items"]}
    items = [{"shortage_id": i.shortage_id, "name": ok[i.shortage_id]["name"], "requested": ok[i.shortage_id]["qty"], "available_qty": i.available_qty, "unit_cost": i.unit_cost} for i in body.items if i.shortage_id in ok]
    reply = {"items": items, "conditions": body.conditions, "comment": body.comment, "at": now_iso(), "covered_qty": sum(i["available_qty"] for i in items), "cost_total": round(sum(i["available_qty"] * i["unit_cost"] for i in items), 2)}
    await db.partner_requests.update_one({"org_id": r["org_id"], "id": r["id"]}, {"$set": {"reply": reply, "status": "repondue"}})
    return {"ok": True}
