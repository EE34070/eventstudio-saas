"""Corbeille : mécanisme unique de suppression (deleted_at / deleted_by), restauration, purge à 30 jours."""
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import IN_ENV, Ctx, audit, db, need, now_iso

router = APIRouter(prefix="/api")
ANY = need()
DAYS = 30
# kind: (collection, module de la grille, droit, libellé)
KINDS = {"member": ("team", "users", "users:delete", "Membre"), "manager": ("social_managers", "social", "social:manage", "Gérant"), "provider": ("provider_profiles", "providers", "providers:manage", "DJ / prestataire"),
         "contact": ("contacts", "contacts", "contacts:write", "Contact"), "venue": ("venues", "venues", "venues:write", "Lieu"), "product": ("equipment", "catalog", "catalog:write", "Produit / matériel"),
         "pack": ("packs", "catalog", "catalog:write", "Pack"), "kit": ("kits", "catalog", "catalog:write", "Nomenclature"), "vehicle": ("vehicles", "vehicles", "catalog:write", "Véhicule"),
         "warehouse": ("warehouses", "stock", "catalog:write", "Entrepôt"), "event": ("events", "events", "events:delete", "Événement"), "quote": ("quotes", "quotes", "finance:write", "Devis"),
         "invoice": ("invoices", "invoices", "finance:write", "Facture"), "task": ("tasks", "tasks", "events:read", "Tâche"), "expense": ("expense_reports", "expenses", "events:read", "Note de frais"),
         "subscription": ("subscriptions", "purchases", "finance:write", "Abonnement"), "purchase": ("purchase_invoices", "purchases", "finance:write", "Achat"),
         "profile": ("access_profiles", "users", "users:manage", "Profil d'accès"), "media": ("media_assets", "communication", "comms:manage", "Média"), "post": ("comm_posts", "communication", "comms:manage", "Publication")}
MODULES = {k[1] for k in KINDS.values()}
DEPS = ("logistics_missions", "dj_bookings")
GONE = " (supprimé)"
today = lambda: datetime.now().strftime("%Y-%m-%d")  # noqa: E731


def allowed(ctx: Ctx, kind: str) -> bool:
    _, mod, perm, _ = KINDS[kind]
    return ctx.can(perm) and (kind == "member" or not ctx.grid or bool((ctx.grid.get(mod) or {}).get("delete")))


def label(d: dict) -> str:
    return str(d.get("name") or d.get("title") or d.get("number") or d.get("label") or d.get("filename") or " ".join(filter(None, [d.get("first_name"), d.get("last_name")])) or d.get("company") or d.get("code") or d.get("id", ""))[:120]


async def fetch(ctx: Ctx, kind: str, id: str, gone: bool = False) -> dict:
    if kind not in KINDS:
        raise HTTPException(400, "Type d'élément inconnu")
    if not allowed(ctx, kind):
        raise HTTPException(403, f"Votre profil ne permet pas de supprimer : {KINDS[kind][3]}")
    d = await db[KINDS[kind][0]].find_one(ctx.q({"id": id, "deleted_at": {"$ne": None} if gone else None}), {"_id": 0})
    if not d:
        raise HTTPException(404, "Introuvable")
    return d


async def impact(ctx: Ctx, kind: str, d: dict) -> dict:
    """Ce qui est rattaché : lignes affichées dans la confirmation, choix demandés, blocage légal éventuel."""
    q, n, lines, out = ctx.q, db, [], {"lines": [], "blocked": "", "needs": {}}
    C = lambda c, f: n[c].count_documents(q(f))  # noqa: E731
    i = d["id"]
    if kind == "invoice" and d.get("number") and d.get("status") not in ("brouillon", "draft"):
        out["blocked"] = "Un avoir ne se supprime pas" if d.get("kind", "").startswith("avoir") else "Facture déjà annulée par un avoir : elle reste dans l'historique" if d.get("status") == "annulee" else "Facture émise : annulez-la par un avoir"
        out["credit"] = d.get("status") != "annulee"
    if kind == "profile":
        if d.get("locked"):
            out["blocked"] = "Le profil Administrateur ne peut pas être supprimé"
        elif await n.users.count_documents({"org_id": ctx.org_id, "access_profile_id": i, "status": {"$ne": "deleted"}}):
            out["blocked"] = "Des membres sont rattachés à ce profil : changez d'abord leur profil"
    if kind == "vehicle":
        k = await C("logistics_missions", {"date": {"$gte": today()}, "$or": [{"vehicles": i}, {"vehicles.vehicle_id": i}, {"vehicle_id": i}]})
        lines += [f"Ce véhicule est affecté à {k} rotation(s) à venir : il en sera retiré"] if k else []
    if kind == "warehouse":
        k = await C("stock_levels", {"warehouse_id": i, "qty_on_hand": {"$gt": 0}})
        others = [{"id": w["id"], "name": w["name"]} for w in await ctx.list("warehouses", {"id": {"$ne": i}, "active": {"$ne": False}})]
        if k:
            lines.append(f"Cet entrepôt contient du stock ({k} référence(s))")
            out["needs"]["stock"] = others
        if d.get("is_default"):
            lines.append("C'est l'entrepôt principal : choisissez celui qui le remplace")
            out["needs"]["new_default"] = others
        k = await C("logistics_missions", {"date": {"$gte": today()}, "origin_id": i})
        lines += [f"{k} rotation(s) à venir partent de cet entrepôt"] if k else []
    if kind == "provider":
        k, m = await C("dj_bookings", {"provider_id": i, "date": {"$gte": today()}}), await C("missions", {"provider_id": i, "date": {"$gte": today()}})
        lines += [f"{k} prestation(s) DJ à venir : il en sera retiré (alerte « aucun DJ affecté »)"] if k else []
        lines += [f"{m} mission(s) Staff à venir"] if m else []
        lines.append("Les prestations passées gardent son nom, avec la mention « (supprimé) »")
    if kind == "member":
        uid = d.get("user_id")
        if uid:
            t, e = await C("tasks", {"assignee_ids": uid, "status": {"$ne": "done"}}), await C("events", {"team.member_id": i, "end": {"$gte": today()}})
            o = await C("opportunities", {"owner_id": uid})
            lines.append(f"{t} tâche(s) ouverte(s), {e} événement(s) à venir, {o} opportunité(s) : à transférer")
            out["needs"]["handover"] = [{"id": u["user_id"], "name": u.get("name", "")} async for u in n.users.find({"org_id": ctx.org_id, "user_id": {"$ne": uid}, "team_id": {"$ne": None}, "status": {"$nin": ["suspended", "disabled", "deleted"]}, **IN_ENV})]
            lines.append("Son compte de connexion est bloqué tout de suite et supprimé à la purge (30 jours)")
        else:
            lines.append("Son lien d'invitation sera invalidé")
    if kind == "event":
        for c, lab in (("quotes", "devis"), ("logistics_missions", "rotation(s) logistique(s)"), ("dj_bookings", "réservation(s) DJ"), ("tasks", "tâche(s)")):
            k = await C(c, {"event_id": i})
            lines += [f"{k} {lab} rattaché(s)"] if k else []
    if kind in ("contact", "venue"):
        f = {"$or": [{"client_id": i}, {"client_contact_ids": i}]} if kind == "contact" else {"venue_id": i}
        k = await C("events", {**f, "end": {"$gte": today()}})
        lines += [f"Rattaché à {k} événement(s) à venir (le nom y reste affiché)"] if k else []
    if kind in ("product", "pack", "kit"):
        k = await C("quotes", {"lines.equipment_id": i, "status": {"$in": ["brouillon", "envoye"]}})
        lines += [f"Présent dans {k} devis en cours (les lignes gardent leur libellé)"] if k else []
    out["lines"] = lines
    return out


async def _clerk(method: str, path: str, **kw):
    import portal_core as po
    try:
        return await po.clerk(method, path, **kw)
    except HTTPException:
        return None


async def _clerk_ids(d: dict) -> list:
    if d.get("user_id"):
        return [d["user_id"]]
    return [c["id"] for c in (await _clerk("GET", "/users", params={"email_address": d["email"]}) or []) if not await db.users.find_one({"user_id": c["id"]})] if d.get("email") else []


async def soft_delete(ctx: Ctx, kind: str, id: str, opt: dict) -> list:
    import portal_core as po
    d = await fetch(ctx, kind, id)
    im = await impact(ctx, kind, d)
    if im["blocked"]:
        raise HTTPException(409, im["blocked"])
    coll, alerts, mark = KINDS[kind][0], [], {"deleted_at": now_iso(), "deleted_with": id}
    if kind == "vehicle":
        f = ctx.q({"date": {"$gte": today()}, "$or": [{"vehicles": id}, {"vehicles.vehicle_id": id}, {"vehicle_id": id}]})
        hit = [m["id"] async for m in db.logistics_missions.find(f, {"id": 1})]
        await db.logistics_missions.update_many({"id": {"$in": hit}, "vehicles": id}, {"$pull": {"vehicles": id}})
        await db.logistics_missions.update_many({"id": {"$in": hit}}, {"$pull": {"vehicles": {"vehicle_id": id}}})
        await db.logistics_missions.update_many({"id": {"$in": hit}, "vehicle_id": id}, {"$set": {"vehicle_id": ""}})
        k = (await db.logistics_missions.update_many({"id": {"$in": hit}, "vehicles": {"$size": 0}}, {"$set": {"status": "a_planifier", "coverage_alert": f"Véhicule « {label(d)} » supprimé : aucun véhicule affecté"}})).modified_count
        alerts += [f"{len(hit)} rotation(s) à venir mise(s) à jour, dont {k} sans véhicule"] if hit else []
    if kind == "warehouse":
        if "new_default" in im["needs"]:
            nd = await db.warehouses.find_one(ctx.q({"id": opt.get("new_default_id") or "", "active": {"$ne": False}}))
            if not nd or nd["id"] == id:
                raise HTTPException(400, "Choisissez l'entrepôt qui devient principal")
            await db.warehouses.update_one(ctx.q({"id": id}), {"$set": {"is_default": False}})
            await db.warehouses.update_one(ctx.q({"id": nd["id"]}), {"$set": {"is_default": True}})
        if "stock" in im["needs"]:
            to = opt.get("transfer_to") or ""
            if to != "drop" and (to == id or not await db.warehouses.find_one(ctx.q({"id": to}))):
                raise HTTPException(400, "Choisissez l'entrepôt qui reçoit le stock, ou la suppression du stock")
            moved = 0
            async for s in db.stock_levels.find(ctx.q({"warehouse_id": id, "qty_on_hand": {"$gt": 0}}), {"_id": 0}):
                if to != "drop":
                    await db.stock_levels.update_one(ctx.q({"product_id": s["product_id"], "warehouse_id": to}), {"$inc": {"qty_on_hand": s["qty_on_hand"]}, "$set": {"updated_at": now_iso()}}, upsert=True)
                await db.stock_levels.update_one(ctx.q({"product_id": s["product_id"], "warehouse_id": id}), {"$set": {"qty_on_hand": 0, "trashed_qty": s["qty_on_hand"], "trashed_to": to}})
                moved += 1
            alerts.append(f"{moved} référence(s) de stock " + ("supprimée(s) avec l'entrepôt" if to == "drop" else "transférée(s)"))
    if kind == "provider":
        k = (await db.dj_bookings.update_many(ctx.q({"provider_id": id, "date": {"$gte": today()}}), {"$set": mark})).modified_count
        alerts += [f"Retiré de {k} prestation(s) à venir : aucun DJ affecté"] if k else []
        for c in ("dj_bookings", "missions", "timesheets"):
            async for b in db[c].find(ctx.q({"provider_id": id, "date": {"$lt": today()}, "provider_name": {"$not": re.compile(re.escape(GONE) + "$")}}), {"id": 1, "provider_name": 1}):
                await db[c].update_one({"id": b["id"]}, {"$set": {"provider_name": (b.get("provider_name") or label(d)) + GONE}})
    if kind == "event":
        for c in DEPS:
            await db[c].update_many(ctx.q({"event_id": id}), {"$set": mark})
    if kind == "member":
        uid = d.get("user_id")
        if uid:
            import routes_access as ra
            await ra._target(ctx, uid, True)
            if opt.get("to_user_id"):
                await ra.handover(uid, ra.HandoverIn(to_user_id=opt["to_user_id"]), ctx)
                alerts.append("Tâches, événements et opportunités transférés")
            await db.users.update_one({"user_id": uid, "org_id": ctx.org_id}, {"$set": {"status": "deleted", "deleted_at": now_iso()}})
            await po.revoke_sessions(uid)
        if d.get("invite_token_id"):
            await _clerk("POST", f"/sign_in_tokens/{d['invite_token_id']}/revoke")
        for cid in await _clerk_ids(d):
            await _clerk("POST", f"/users/{cid}/ban")
    await db[coll].update_one(ctx.q({"id": id}), {"$set": {"deleted_at": now_iso(), "deleted_by": ctx.member.get("name", ""), "purge_at": (datetime.now(timezone.utc) + timedelta(days=DAYS)).isoformat(), **({"invite_link": ""} if kind == "member" else {})}})
    await audit(ctx.org_id, ctx.member, "trash_deleted", f"{KINDS[kind][3]} : {label(d)}", " | ".join(im["lines"] + alerts)[:900] or "rien de rattaché")
    return alerts


async def restore(ctx: Ctx, kind: str, id: str) -> None:
    d = await fetch(ctx, kind, id, True)
    un = {"$set": {"deleted_at": None}, "$unset": {"deleted_by": "", "purge_at": "", "deleted_with": ""}}
    if kind == "warehouse":
        async for s in db.stock_levels.find(ctx.q({"warehouse_id": id, "trashed_qty": {"$gt": 0}}), {"_id": 0}):
            if s.get("trashed_to") not in ("drop", None):
                await db.stock_levels.update_one(ctx.q({"product_id": s["product_id"], "warehouse_id": s["trashed_to"]}), {"$inc": {"qty_on_hand": -s["trashed_qty"]}})
            await db.stock_levels.update_one(ctx.q({"product_id": s["product_id"], "warehouse_id": id}), {"$set": {"qty_on_hand": s["trashed_qty"], "trashed_qty": 0}})
    if kind == "provider":
        for c in ("dj_bookings", "missions", "timesheets"):
            async for b in db[c].find(ctx.q({"provider_id": id, "provider_name": re.compile(re.escape(GONE) + "$")}), {"id": 1, "provider_name": 1}):
                await db[c].update_one({"id": b["id"]}, {"$set": {"provider_name": b["provider_name"][:-len(GONE)]}})
    if kind == "member":
        if d.get("user_id"):
            await db.users.update_one({"user_id": d["user_id"], "org_id": ctx.org_id}, {"$set": {"status": "active"}, "$unset": {"deleted_at": ""}})
        for cid in await _clerk_ids(d):
            await _clerk("POST", f"/users/{cid}/unban")
    for c in DEPS:
        await db[c].update_many(ctx.q({"deleted_with": id, "deleted_at": {"$ne": None}}), un)
    await db[KINDS[kind][0]].update_one(ctx.q({"id": id, "deleted_at": {"$ne": None}}), un)
    await audit(ctx.org_id, ctx.member, "trash_restored", f"{KINDS[kind][3]} : {label(d)}")


async def purge_doc(org_id: str, kind: str, d: dict, actor: dict | None, why: str) -> None:
    """Suppression définitive : action explicite depuis la Corbeille, ou échéance des 30 jours."""
    from routes_files import remove_stored
    o = {"org_id": org_id}
    for fid in set(re.findall(r"file:([0-9a-f-]{36})", json.dumps(d, default=str))) | ({d["file_id"]} if d.get("file_id") else set()):
        f = await db.files.find_one({**o, "id": fid}, {"_id": 0})
        if f:
            await remove_stored(f["storage_path"])
            await db.files.delete_one({**o, "id": fid})
    if kind == "member":
        for cid in await _clerk_ids(d):
            await _clerk("DELETE", f"/users/{cid}")
        if d.get("user_id"):
            await db.users.delete_one({**o, "user_id": d["user_id"], "status": "deleted"})
    if kind == "warehouse":
        await db.stock_levels.delete_many({**o, "warehouse_id": d["id"]})
    for c in DEPS:
        await db[c].delete_many({**o, "deleted_with": d["id"], "deleted_at": {"$ne": None}})
    await db[KINDS[kind][0]].delete_one({**o, "id": d["id"], "deleted_at": {"$ne": None}})
    await audit(org_id, actor, "trash_purged", f"{KINDS[kind][3]} : {label(d)}", why)


async def purge_expired(org_id: str | None = None) -> int:
    n, now = 0, now_iso()
    for kind, (coll, *_) in KINDS.items():
        async for d in db[coll].find({"deleted_at": {"$ne": None}, "purge_at": {"$lte": now}, **({"org_id": org_id} if org_id else {})}, {"_id": 0}):
            await purge_doc(d["org_id"], kind, d, None, f"purge automatique après {DAYS} jours")
            n += 1
    return n


class Item(BaseModel):
    kind: str
    id: str


class Batch(BaseModel):
    items: List[Item] = Field(min_length=1, max_length=200)
    options: Dict[str, str] = {}


@router.get("/trash/impact")
async def get_impact(kind: str, id: str, ctx: Ctx = Depends(ANY)):
    d = await fetch(ctx, kind, id)
    return {"kind": kind, "id": id, "label": label(d), "type": KINDS[kind][3], **await impact(ctx, kind, d)}


@router.get("/trash/rights")
async def rights(ctx: Ctx = Depends(ANY)):
    return {k: allowed(ctx, k) for k in KINDS}


@router.post("/trash/delete")
async def delete(body: Batch, ctx: Ctx = Depends(ANY)):
    done, alerts, errors = 0, [], []
    for it in body.items:
        try:
            alerts += await soft_delete(ctx, it.kind, it.id, body.options)
            done += 1
        except HTTPException as e:
            if len(body.items) == 1:
                raise
            errors.append(str(e.detail))
    return {"deleted": done, "alerts": alerts, "errors": errors}


@router.get("/trash")
async def list_trash(ctx: Ctx = Depends(ANY)):
    await purge_expired(ctx.org_id)
    rows = []
    for kind, (coll, *_r) in KINDS.items():
        if allowed(ctx, kind):
            rows += [{"kind": kind, "type": _r[2], "id": d["id"], "label": label(d), "deleted_at": d["deleted_at"], "deleted_by": d.get("deleted_by", ""), "purge_at": d.get("purge_at", "")}
                     async for d in db[coll].find(ctx.q({"deleted_at": {"$ne": None}, "id": {"$exists": True}}), {"_id": 0})]
    return {"rows": sorted(rows, key=lambda r: r["deleted_at"], reverse=True), "days": DAYS}


@router.post("/trash/restore")
async def do_restore(body: Batch, ctx: Ctx = Depends(ANY)):
    for it in body.items:
        await restore(ctx, it.kind, it.id)
    return {"restored": len(body.items)}


@router.post("/trash/purge")
async def do_purge(body: Batch, ctx: Ctx = Depends(ANY)):
    for it in body.items:
        await purge_doc(ctx.org_id, it.kind, await fetch(ctx, it.kind, it.id, True), ctx.member, "suppression définitive depuis la Corbeille")
    return {"purged": len(body.items)}


@router.post("/trash/empty")
async def empty(ctx: Ctx = Depends(ANY)):
    rows = (await list_trash(ctx))["rows"]
    for r in rows:
        await purge_doc(ctx.org_id, r["kind"], await fetch(ctx, r["kind"], r["id"], True), ctx.member, "corbeille vidée")
    return {"purged": len(rows)}
