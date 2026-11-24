"""Fournisseurs multiples par produit : supplier_product_map + historique des prix. Réservé au droit finance:costs."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import Ctx, db, need, new_id, now_iso

router = APIRouter(prefix="/api")
FIELDS = ("supplier_ref", "supplier_label", "purchase_uom", "conversion_factor", "unit_price_ht", "price_date", "lead_time_days", "min_order_qty", "usual_shipping_ht", "url", "notes")


def costs(ctx: Ctx = Depends(need("catalog:read"))) -> Ctx:
    if not ctx.can("finance:costs"):
        raise HTTPException(403, "Réservé aux profils qui voient les prix d'achat")
    return ctx


def costs_w(ctx: Ctx = Depends(need("catalog:write"))) -> Ctx:
    return costs(ctx)


def name_of(c: dict) -> str:
    return c.get("company") or " ".join(filter(None, [c.get("first_name"), c.get("last_name")])) or "—"


def stock_price(m: dict) -> Optional[float]:
    return round(m["unit_price_ht"] / (m.get("conversion_factor") or 1), 4) if m.get("unit_price_ht") else None


async def rows_for(org_id: str, f: dict) -> list:
    ms = await db.supplier_product_map.find({"org_id": org_id, "deleted_at": None, **f}, {"_id": 0}).to_list(5000)
    cs = {c["id"]: c async for c in db.contacts.find({"org_id": org_id, "id": {"$in": [m["supplier_id"] for m in ms]}}, {"_id": 0, "id": 1, "company": 1, "first_name": 1, "last_name": 1, "language": 1, "email": 1})}
    ps = {p["id"]: p async for p in db.equipment.find({"org_id": org_id, "id": {"$in": [m["product_id"] for m in ms]}}, {"_id": 0, "id": 1, "ref": 1, "name": 1, "stock_uom": 1})}
    out = []
    for m in ms:
        if m["supplier_id"] in cs and m["product_id"] in ps:
            p = ps[m["product_id"]]
            out.append({**m, "supplier_name": name_of(cs[m["supplier_id"]]), "product_ref": p.get("ref", ""), "product_name": p["name"], "stock_uom": p.get("stock_uom") or "piece", "stock_price_ht": stock_price(m)})
    priced = [r["stock_price_ht"] for r in out if r["stock_price_ht"]]
    for r in out:
        r["cheapest"] = bool(priced) and len(out) > 1 and r["stock_price_ht"] == min(priced)
    return sorted(out, key=lambda r: (r["stock_price_ht"] is None, r["stock_price_ht"] or 0))


async def offers(org_id: str, product_id: str) -> list:
    rows = await rows_for(org_id, {"product_id": product_id})
    return sorted(rows, key=lambda r: not r.get("is_preferred"))


async def _sync_default(org_id: str, pid: str) -> None:
    m = await db.supplier_product_map.find_one({"org_id": org_id, "product_id": pid, "deleted_at": None, "is_preferred": True}, {"_id": 0, "supplier_id": 1})
    await db.equipment.update_one({"org_id": org_id, "id": pid}, {"$set": {"default_supplier_id": (m or {}).get("supplier_id", "")}})


async def learn(org_id: str, supplier_id: str, product_id: str, price: float, date: str, source: str, invoice_id: str = "", ref: str = "", label: str = "") -> dict:
    """Crée ou met à jour la ligne fournisseur/produit sans doublon, garde l'historique, signale une hausse > 10 %."""
    key = {"org_id": org_id, "supplier_id": supplier_id, "product_id": product_id, "deleted_at": None}
    m = await db.supplier_product_map.find_one(key, {"_id": 0})
    old = (m or {}).get("unit_price_ht") or 0
    if not m:
        first = not await db.supplier_product_map.find_one({"org_id": org_id, "product_id": product_id, "deleted_at": None})
        m = {"id": new_id(), **key, "supplier_ref": ref, "supplier_label": label, "purchase_uom": "", "conversion_factor": 1, "lead_time_days": None, "min_order_qty": None, "usual_shipping_ht": None,
             "url": "", "notes": "", "is_preferred": first, "source": source, "created_at": now_iso()}
        await db.supplier_product_map.insert_one({**m})
        if first:
            await _sync_default(org_id, product_id)
    await db.supplier_product_map.update_one({"org_id": org_id, "id": m["id"]}, {"$set": {"unit_price_ht": price, "price_date": date, "updated_at": now_iso()}})
    await db.supplier_price_history.insert_one({"id": new_id(), "org_id": org_id, "map_id": m["id"], "price": price, "date": date, "purchase_invoice_id": invoice_id or None, "source": source, "at": now_iso()})
    return {"map_id": m["id"], "old_price": old, "new_price": price, "rise_alert": bool(old) and price > old * 1.1}


class NewSupplier(BaseModel):
    name: str = Field("", max_length=120)
    company: str = Field("", max_length=160)
    email: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    website: str = Field("", max_length=300)
    language: str = "fr-FR"


class MapIn(BaseModel):
    supplier_id: str = ""
    product_id: str = ""
    new_supplier: Optional[NewSupplier] = None
    supplier_ref: str = Field("", max_length=120)
    supplier_label: str = Field("", max_length=300)
    purchase_uom: str = Field("", max_length=80)
    conversion_factor: float = Field(1, gt=0, le=1000000)
    unit_price_ht: Optional[float] = Field(None, ge=0, le=10000000)
    price_date: str = Field("", max_length=10)
    lead_time_days: Optional[int] = Field(None, ge=0, le=730)
    min_order_qty: Optional[float] = Field(None, ge=0)
    usual_shipping_ht: Optional[float] = Field(None, ge=0)
    url: str = Field("", max_length=500)
    notes: str = Field("", max_length=1000)
    is_preferred: bool = False


async def _prefer(ctx: Ctx, m: dict) -> None:
    await db.supplier_product_map.update_many(ctx.q({"product_id": m["product_id"], "id": {"$ne": m["id"]}}), {"$set": {"is_preferred": False}})
    await db.supplier_product_map.update_one(ctx.q({"id": m["id"]}), {"$set": {"is_preferred": True}})
    await _sync_default(ctx.org_id, m["product_id"])


async def _add(ctx: Ctx, pid: str, body: MapIn) -> dict:
    await ctx.get("equipment", pid)
    sid = body.supplier_id
    if not sid:
        n = body.new_supplier
        if not n or not (n.name.strip() or n.company.strip()):
            raise HTTPException(400, "Choisissez ou créez un fournisseur")
        c = await ctx.insert("contacts", {"kind": "entreprise", "status": "", "statuses": {"fournisseur": "actif"}, "first_name": "", "last_name": n.name.strip() if n.company.strip() else "", "company": n.company.strip() or n.name.strip(),
                                          "email": n.email.strip().lower(), "phone": n.phone.strip(), "website": n.website.strip(), "language": n.language, "address": "", "city": "", "source": "Catalogue", "tags": [], "notes": "",
                                          "types": ["fournisseur"], "interactions": []})
        sid = c["id"]
    else:
        await ctx.get("contacts", sid)
        await db.contacts.update_one(ctx.q({"id": sid}), {"$addToSet": {"types": "fournisseur"}})
    if await db.supplier_product_map.find_one(ctx.q({"product_id": pid, "supplier_id": sid, "deleted_at": None})):
        raise HTTPException(409, "Ce fournisseur est déjà lié à ce produit")
    first = not await db.supplier_product_map.find_one(ctx.q({"product_id": pid, "deleted_at": None}))
    d = body.model_dump(include=set(FIELDS))
    d["price_date"] = d["price_date"] or (now_iso()[:10] if d["unit_price_ht"] else "")
    m = await ctx.insert("supplier_product_map", {**d, "supplier_id": sid, "product_id": pid, "is_preferred": False, "source": "manual", "deleted_at": None})
    if d["unit_price_ht"]:
        await db.supplier_price_history.insert_one({"id": new_id(), "org_id": ctx.org_id, "map_id": m["id"], "price": d["unit_price_ht"], "date": d["price_date"], "purchase_invoice_id": None, "source": "manual", "at": now_iso()})
    if body.is_preferred or first:
        await _prefer(ctx, m)
    return m


@router.get("/equipment/{pid}/suppliers")
async def product_suppliers(pid: str, ctx: Ctx = Depends(costs)):
    await ctx.get("equipment", pid)
    return await rows_for(ctx.org_id, {"product_id": pid})


@router.post("/equipment/{pid}/suppliers")
async def add_supplier(pid: str, body: MapIn, ctx: Ctx = Depends(costs_w)):
    await _add(ctx, pid, body)
    return await rows_for(ctx.org_id, {"product_id": pid})


@router.get("/supplier-products")
async def index(supplier_id: str = "", ctx: Ctx = Depends(need("catalog:read"))):
    if not ctx.can("finance:costs"):
        return {"rows": [], "allowed": False}
    return {"rows": await rows_for(ctx.org_id, {"supplier_id": supplier_id} if supplier_id else {}), "allowed": True}


@router.post("/supplier-products")
async def add_product(body: MapIn, ctx: Ctx = Depends(costs_w)):
    await _add(ctx, body.product_id, body)
    return {"rows": await rows_for(ctx.org_id, {"supplier_id": body.supplier_id})}


@router.put("/supplier-products/{mid}")
async def update_map(mid: str, body: MapIn, ctx: Ctx = Depends(costs_w)):
    m = await ctx.get("supplier_product_map", mid, {"deleted_at": None})
    d = body.model_dump(include=set(FIELDS))
    if d["unit_price_ht"] and d["unit_price_ht"] != m.get("unit_price_ht"):
        d["price_date"] = d["price_date"] if d["price_date"] and d["price_date"] != m.get("price_date") else now_iso()[:10]
        await db.supplier_price_history.insert_one({"id": new_id(), "org_id": ctx.org_id, "map_id": mid, "price": d["unit_price_ht"], "date": d["price_date"], "purchase_invoice_id": None, "source": "manual", "at": now_iso()})
    await ctx.update("supplier_product_map", mid, d)
    if body.is_preferred:
        await _prefer(ctx, m)
    return await rows_for(ctx.org_id, {"product_id": m["product_id"]})


@router.delete("/supplier-products/{mid}")
async def delete_map(mid: str, ctx: Ctx = Depends(costs_w)):
    m = await ctx.get("supplier_product_map", mid, {"deleted_at": None})
    await ctx.update("supplier_product_map", mid, {"deleted_at": now_iso(), "is_preferred": False})
    nxt = (await rows_for(ctx.org_id, {"product_id": m["product_id"]}))[:1]
    if m.get("is_preferred") and nxt:
        await _prefer(ctx, nxt[0])
    else:
        await _sync_default(ctx.org_id, m["product_id"])
    return await rows_for(ctx.org_id, {"product_id": m["product_id"]})


@router.get("/supplier-products/{mid}/history")
async def history(mid: str, ctx: Ctx = Depends(costs)):
    await ctx.get("supplier_product_map", mid)
    return await db.supplier_price_history.find(ctx.q({"map_id": mid}), {"_id": 0, "org_id": 0}).sort("at", -1).to_list(200)


@router.get("/supplier-products/{mid}/price-request")
async def price_request(mid: str, qty: float = 1, ctx: Ctx = Depends(costs)):
    """Brouillon seulement : rien n'est envoyé."""
    m = await ctx.get("supplier_product_map", mid, {"deleted_at": None})
    c, p = await ctx.get("contacts", m["supplier_id"]), await ctx.get("equipment", m["product_id"])
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "name": 1}) or {}
    label, ref = m.get("supplier_label") or p["name"], m.get("supplier_ref") or "—"
    unit = m.get("purchase_uom") or p.get("stock_uom") or "pièce"
    if (c.get("language") or "fr-FR").startswith("fr"):
        subject = f"Demande de prix — {label}"
        text = f"Bonjour,\n\nPourriez-vous nous communiquer votre meilleur prix et votre délai de livraison pour :\n\n- Produit : {label}\n- Votre référence : {ref}\n- Quantité : {qty:g} {unit}\n\nMerci d'avance,\n{ctx.member.get('name', '')}\n{org.get('name', '')}"
    else:
        subject = f"Price request — {label}"
        text = f"Hello,\n\nCould you please send us your best price and delivery time for:\n\n- Product: {label}\n- Your reference: {ref}\n- Quantity: {qty:g} {unit}\n\nThank you,\n{ctx.member.get('name', '')}\n{org.get('name', '')}"
    return {"to": c.get("email", ""), "subject": subject, "text": text, "language": c.get("language") or "fr-FR"}


class InvoiceLine(BaseModel):
    product_id: str
    qty: float = Field(1, gt=0)
    unit_price_ht: float = Field(ge=0)
    supplier_ref: str = Field("", max_length=120)
    label: str = Field("", max_length=300)


async def apply_invoice(ctx: Ctx, inv: dict, lines: List[dict]) -> list:
    out = []
    if not inv.get("supplier_contact_id"):
        return out
    for l in lines:
        if await db.equipment.find_one(ctx.q({"id": l["product_id"]})) and l["unit_price_ht"] > 0:
            out.append({**await learn(ctx.org_id, inv["supplier_contact_id"], l["product_id"], l["unit_price_ht"], inv["date"], "invoice", inv["id"], l.get("supplier_ref", ""), l.get("label", "")), "product_id": l["product_id"]})
    return out
