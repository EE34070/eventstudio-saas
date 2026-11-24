"""Import du catalogue Odoo : logique commune au script (backend/scripts/import_catalogue_odoo.py) et à la page admin. Upsert par `ref`."""
import math
import uuid
from datetime import datetime, timezone

TYPES = ("Location", "Consommable", "Service", "Prestation artistique", "Pack")
NO_STOCK = ("Service", "Prestation artistique", "Pack")
ALLOWED_SLUGS = ("exclusivity-events",)
NOTE = "Inventaire initial (import Odoo)"
NEW_FIELDS = ["subcategory", "product_type", "provenance", "sublet_partner", "cost_ht", "secondary_uom", "qty_per_piece", "specs", "to_check", "import_source", "price_day vide = prix à définir"]
DEFAULTS = {"photo": "", "description": "", "name_en": "", "description_en": "", "replacement_value": 0, "weight_kg": 0, "volume_m3": 0, "state": "bon", "notes": "",
            "prep_days_before": 0, "return_days_after": 0, "qty_maintenance": 0, "maintenance_log": []}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


def normalize(r: dict) -> tuple:
    """Retourne (champs produit, stock entier, motif de refus)."""
    if not isinstance(r, dict):
        return None, 0, "ligne illisible"
    ref, name, typ = str(r.get("ref") or "").strip(), str(r.get("name") or "").strip(), str(r.get("type") or "").strip()
    if not ref or not name:
        return None, 0, "référence ou nom manquant"
    if typ not in TYPES:
        return None, 0, f"type inconnu « {typ} »"
    for k in ("price_ht", "cost_ht", "stock_main", "qty_per_piece"):
        if r.get(k) is not None and not _num(r[k]):
            return None, 0, f"{k} invalide « {r[k]} »"
    cat, sub = str(r.get("category") or "").strip() or "À classer", str(r.get("subcategory") or "").strip()
    if cat == "Câblage" and sub == "Connectique (pièces détachées)":
        cat = "Consommables"
    check, raw = str(r.get("to_check") or "").strip(), r.get("stock_main") or 0
    su, extra = str(r.get("unite_stock") or "").strip(), {}
    if su:
        extra["stock_uom"] = "piece" if su in ("pièce", "piece") else su
    if r.get("unite_devis"):
        extra["quote_uom"] = "secondary" if str(r["unite_devis"]).strip() in ("secondary", "secondaire", str(r.get("secondary_uom") or "-")) else "stock"
    if r.get("arrondi") in ("ceil", "nearest", "exact"):
        extra["rounding"] = r["arrondi"]
    carac = {k[6:]: v for k, v in r.items() if k.startswith("carac:") and v not in ("", None)}
    if carac:
        extra["attributes"] = carac
    measured = extra.get("stock_uom", "piece") not in ("piece", "lot") or extra.get("rounding") == "exact"
    stock = 0 if typ in NO_STOCK else round(raw, 3) if measured else int(math.floor(raw))
    if typ not in NO_STOCK and raw != stock:
        check = "; ".join(x for x in (check, f"stock Odoo {raw:g} arrondi à {stock}") if x)
    return {"ref": ref, "name": name[:300], "category": cat, "subcategory": sub, "product_type": typ, "price_day": r.get("price_ht"), "cost_ht": r.get("cost_ht"),
            "provenance": str(r.get("provenance") or "").strip() or "À qualifier", "sublet_partner": str(r.get("partner") or "").strip(), "secondary_uom": str(r.get("secondary_uom") or "").strip(),
            "qty_per_piece": r.get("qty_per_piece"), "specs": str(r.get("specs") or "").strip(), "to_check": check, "import_source": "odoo", **extra}, stock, ""


async def run(db, org_id: str, rows: list, apply: bool, by: str = "Import Odoo") -> dict:
    rep = {"applied": apply, "total": len(rows), "created": 0, "updated": 0, "unchanged": 0, "refused": [], "stock_levels": 0, "stock_units": 0, "price_missing": 0, "to_check": 0,
           "rounded": [], "existing_not_imported": [], "by_type": {}, "by_category": {}, "subcategories": 0, "new_fields": NEW_FIELDS}
    existing = {e["ref"]: e async for e in db.equipment.find({"org_id": org_id}, {"_id": 0, "maintenance_log": 0})}
    wh = None
    if apply:
        import routes_stock
        wh = (await routes_stock.world(org_id))["default"]
    seen, subs = set(), set()
    for i, r in enumerate(rows, 1):
        doc, stock, why = normalize(r)
        if not why and doc["ref"] in seen:
            why = "référence en double dans le fichier"
        if why:
            rep["refused"].append({"line": i, "ref": str((r or {}).get("ref", "") if isinstance(r, dict) else ""), "reason": why})
            continue
        seen.add(doc["ref"])
        subs.add((doc["category"], doc["subcategory"]))
        cur = existing.get(doc["ref"])
        state = "created" if not cur else "unchanged" if all(cur.get(k) == v for k, v in doc.items()) else "updated"
        rep[state] += 1
        for key, k in (("by_type", doc["product_type"]), ("by_category", doc["category"])):
            rep[key].setdefault(k, {"created": 0, "updated": 0, "unchanged": 0})[state] += 1
        rep["price_missing"] += doc["price_day"] is None
        rep["to_check"] += bool(doc["to_check"])
        if "arrondi" in doc["to_check"]:
            rep["rounded"].append(f"{doc['ref']} : {r['stock_main']:g} → {stock}")
        if cur and cur.get("import_source") != "odoo":
            rep["existing_not_imported"].append(doc["ref"])
        if state == "created":
            rep["stock_levels"] += stock > 0
            rep["stock_units"] += stock
        if not apply:
            continue
        if cur:
            if state == "updated":
                await db.equipment.update_one({"org_id": org_id, "id": cur["id"]}, {"$set": {**doc, "updated_at": _now()}})
            continue
        pid = str(uuid.uuid4())
        await db.equipment.insert_one({**DEFAULTS, "maintenance_log": [], **doc, "id": pid, "org_id": org_id, "created_at": _now(), "qty_total": stock})
        await db.stock_levels.insert_one({"org_id": org_id, "product_id": pid, "warehouse_id": wh["id"], "qty_on_hand": stock, "updated_at": _now()})
        if stock:
            await db.stock_movements.insert_one({"id": str(uuid.uuid4()), "org_id": org_id, "created_at": _now(), "type": "entree", "product_id": pid, "qty": stock, "from_warehouse_id": "",
                                                 "to_warehouse_id": wh["id"], "event_id": "", "logistics_mission_id": "", "status": "done", "user": by, "note": NOTE})
    rep["subcategories"] = len(subs)
    rep["warehouse"] = (wh or await db.warehouses.find_one({"org_id": org_id, "is_default": True}, {"_id": 0, "name": 1}) or {}).get("name") or "Entrepôt principal (sera créé)"
    return rep
