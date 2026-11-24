"""Unités de mesure et caractéristiques par produit. Les modèles par défaut vivent dans le code ; une société n'écrit que ce qu'elle modifie."""
import math
import re
from typing import Annotated, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AfterValidator, BaseModel, Field

from core import Ctx, db, need, new_id, now_iso

router = APIRouter(prefix="/api")
R, W = need("catalog:read"), need("catalog:write")
WHOLE = ("piece", "lot")
STOCK_UOMS = ["piece", "m", "m²", "m³", "kg", "L", "lot"]
UOMS = [{"code": c, "label": "pièce" if c == "piece" else c, "kind": k} for c, k in (
    ("piece", "count"), ("lot", "count"), ("m", "length"), ("m²", "area"), ("m³", "volume"), ("kg", "weight"), ("L", "volume"), ("places", "seats"), ("appareils", "count"), ("W", "power"))]


def num(v: float):
    v = round(float(v), 3)
    return int(v) if v == int(v) else v


Qty = Annotated[float, AfterValidator(num)]


def is_exact(eq: dict) -> bool:
    return eq.get("rounding") == "exact" or (eq.get("stock_uom") or "piece") not in WHOLE


def to_pieces(eq: dict, qty: float, uom: str = ""):
    qpp = eq.get("qty_per_piece") or 0
    if uom == "secondary" and qpp:
        raw = qty / qpp
        if is_exact(eq):
            return num(raw)
        return max(1, round(raw) if eq.get("rounding") == "nearest" else math.ceil(raw - 1e-9))
    return num(qty) if is_exact(eq) else int(qty)


def check_whole(eq: dict, qty: float) -> None:
    if not is_exact(eq) and qty != int(qty):
        raise HTTPException(400, f"{eq.get('name', 'Ce produit')} se gère en pièces entières")


def _f(code, label, type_="number", unit="", options=None):
    return {"code": code, "label": label, "type": type_, "unit": unit, "options": options or []}


DEFAULTS = [
    {"id": "guirlandes", "name": "Guirlandes & ciels lumineux", "scopes": ["Guirlandes & ciels lumineux"], "fields": [
        _f("longueur_m", "Longueur", unit="m"), _f("nb_ampoules", "Nombre d'ampoules"), _f("entraxe_cm", "Entraxe", unit="cm"), _f("culot", "Culot", "select", options=["E27", "E14", "B22", "LED intégrée"]),
        _f("puissance_w", "Puissance totale", unit="W"), _f("couleur_lumiere", "Couleur de lumière", "select", options=["Blanc chaud", "Blanc froid", "RGB"]), _f("ip", "IP", "text"),
        _f("raccordable", "Raccordable bout à bout", "bool"), _f("max_serie", "Nombre max en série")]},
    {"id": "structure", "name": "Structure", "scopes": ["Structures", "Structure & levage"], "fields": [
        _f("longueur_m", "Longueur", unit="m"), _f("section", "Section", "select", options=["290", "220", "Monotube"]), _f("charge_max_kg", "Charge max", unit="kg"), _f("couleur", "Couleur", "text")]},
    {"id": "scene", "name": "Scène & piste", "scopes": ["Scène & piste", "Praticables & scènes", "Pistes de danse", "Habillage de scène", "Tapis & moquettes"], "fields": [
        _f("longueur_m", "Longueur", unit="m"), _f("largeur_m", "Largeur", unit="m"), _f("hauteur_cm", "Hauteur réglable", "text", "cm"), _f("surface_m2", "Surface (calculée)", unit="m²"), _f("charge_kg_m2", "Charge", unit="kg/m²"), _f("role", "Rôle dans une nomenclature (praticable, pied, pied_telescopique, moquette, scotch, gaffer, clamp, egalisateur, jupe, escalier, garde_corps)", "text"),
        _f("systeme", "Système / gamme", "text"), _f("hauteur_fixe_cm", "Hauteur fixe", unit="cm"), _f("hauteur_min_cm", "Hauteur min (télescopique)", unit="cm"), _f("hauteur_max_cm", "Hauteur max (télescopique)", unit="cm"),
        _f("largeur_rouleau_m", "Largeur de rouleau", unit="m"), _f("longueur_rouleau_m", "Longueur de rouleau", unit="m"), _f("couleur", "Couleur", "text")]},
    {"id": "tables", "name": "Tables & salons", "scopes": ["Tables", "Salons & lounge", "Tables basses", "Mange-debout"], "fields": [
        _f("dimensions", "Dimensions (L × l × H)", "text"), _f("places_assises", "Places assises", unit="places"), _f("matiere", "Matière", "text"), _f("couleur", "Couleur", "text")]},
    {"id": "cablage", "name": "Câblage & électricité", "scopes": ["Câblage", "Électricité"], "fields": [
        _f("longueur_m", "Longueur", unit="m"), _f("connecteurs", "Connecteurs", "text"), _f("intensite_a", "Intensité", unit="A"), _f("phase", "Mono / tétra", "select", options=["Mono", "Tétra"])]},
    {"id": "son_lumiere", "name": "Enceintes / lumière", "scopes": ["Enceintes", "Caissons de basse", "Projecteurs LED", "Lyres", "Son", "Lumière"], "fields": [
        _f("puissance_w", "Puissance", unit="W"), _f("poids_kg", "Poids", unit="kg"), _f("alimentation", "Alimentation", "text"), _f("ip", "IP", "text")]},
]


async def templates(org_id: str) -> list:
    mine = {t["id"]: t async for t in db.attribute_templates.find({"org_id": org_id, "deleted_at": None}, {"_id": 0, "org_id": 0})}
    out = [{**mine.pop(d["id"]), "custom": True} if d["id"] in mine else {**d, "custom": False} for d in DEFAULTS]
    return out + [{**t, "custom": True} for t in mine.values()]


def match(tpls: list, eq: dict) -> Optional[dict]:
    for key in (eq.get("subcategory"), eq.get("category")):
        t = next((t for t in tpls if key and key in t["scopes"]), None)
        if t:
            return t
    return None


@router.get("/uoms")
async def list_uoms(ctx: Ctx = Depends(R)):
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "uoms": 1}) or {}
    return {"uoms": UOMS + [u for u in org.get("uoms") or [] if u["code"] not in {x["code"] for x in UOMS}], "stock_uoms": STOCK_UOMS}


class UomIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    kind: str = Field("count", max_length=20)


@router.post("/uoms")
async def add_uom(body: UomIn, ctx: Ctx = Depends(W)):
    code = body.code.strip()
    await db.orgs.update_one({"id": ctx.org_id, "uoms.code": {"$ne": code}}, {"$push": {"uoms": {"code": code, "label": code, "kind": body.kind}}})
    return await list_uoms(ctx)


@router.get("/attribute-templates")
async def list_templates(ctx: Ctx = Depends(R)):
    return await templates(ctx.org_id)


class FieldIn(BaseModel):
    code: str = Field("", max_length=40)
    label: str = Field(min_length=1, max_length=80)
    type: Literal["number", "text", "select", "bool"] = "text"
    unit: str = Field("", max_length=20)
    options: List[str] = Field([], max_length=40)


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scopes: List[str] = Field(max_length=40)
    fields: List[FieldIn] = Field(max_length=60)


def _code(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower().translate(str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc"))).strip("_")[:40] or new_id()[:8]


@router.put("/attribute-templates/{tid}")
async def save_template(tid: str, body: TemplateIn, ctx: Ctx = Depends(W)):
    if tid == "new":
        tid = new_id()
    fields = [{**f.model_dump(), "code": f.code or _code(f.label)} for f in body.fields]
    if len({f["code"] for f in fields}) != len(fields):
        raise HTTPException(400, "Deux champs portent le même code")
    await db.attribute_templates.update_one(ctx.q({"id": tid}), {"$set": {"name": body.name, "scopes": [s.strip() for s in body.scopes if s.strip()], "fields": fields, "deleted_at": None, "updated_at": now_iso()},
                                                                 "$setOnInsert": {"created_at": now_iso()}}, upsert=True)
    return await templates(ctx.org_id)


@router.delete("/attribute-templates/{tid}")
async def reset_template(tid: str, ctx: Ctx = Depends(W)):
    await db.attribute_templates.update_one(ctx.q({"id": tid}), {"$set": {"deleted_at": now_iso()}})
    return await templates(ctx.org_id)


class UnitsIn(BaseModel):
    stock_uom: str = Field("piece", max_length=20)
    secondary_uom: str = Field("", max_length=20)
    qty_per_piece: Optional[float] = Field(None, gt=0, le=1000000)
    quote_uom: Literal["stock", "secondary"] = "stock"
    rounding: Literal["ceil", "nearest", "exact"] = "ceil"
    price_day: Optional[float] = Field(None, ge=0)
    price_per_secondary: Optional[float] = Field(None, ge=0)


@router.put("/equipment/{eid}/units")
async def put_units(eid: str, body: UnitsIn, ctx: Ctx = Depends(W)):
    eq = await ctx.get("equipment", eid)
    if body.stock_uom not in STOCK_UOMS:
        raise HTTPException(400, "Unité de stock inconnue")
    if body.secondary_uom and not body.qty_per_piece:
        raise HTTPException(400, "Indiquez la quantité par pièce pour l'unité secondaire")
    d = body.model_dump()
    if "price_day" not in body.model_fields_set:
        d.pop("price_day")
    if not body.secondary_uom:
        d.update({"qty_per_piece": None, "quote_uom": "stock", "price_per_secondary": None})
    if not is_exact(d) and eq.get("qty_total", 0) != int(eq.get("qty_total", 0)):
        raise HTTPException(400, "Le stock actuel est décimal : gardez une unité de stock mesurée ou l'arrondi « exact »")
    return await ctx.update("equipment", eid, d)


class ExtraAttr(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    value: str = Field("", max_length=200)
    unit: str = Field("", max_length=20)


class AttrsIn(BaseModel):
    attributes: dict = {}
    extra_attributes: List[ExtraAttr] = Field([], max_length=40)


@router.put("/equipment/{eid}/attributes")
async def put_attributes(eid: str, body: AttrsIn, ctx: Ctx = Depends(W)):
    eq = await ctx.get("equipment", eid)
    t = match(await templates(ctx.org_id), eq) or {"fields": []}
    types, out = {f["code"]: f["type"] for f in t["fields"]}, {}
    for k, v in body.attributes.items():
        if k not in types or v in ("", None):
            continue
        if types[k] == "number":
            try:
                v = num(float(str(v).replace(",", ".")))
            except ValueError:
                raise HTTPException(400, f"Valeur numérique attendue pour « {k} »")
        out[k] = bool(v) if types[k] == "bool" else v if types[k] == "number" else str(v)[:200]
    if "surface_m2" in types and out.get("longueur_m") and out.get("largeur_m"):
        out["surface_m2"] = num(out["longueur_m"] * out["largeur_m"])
    return await ctx.update("equipment", eid, {"attributes": out, "extra_attributes": [e.model_dump() for e in body.extra_attributes]})


async def ensure_whole(org_id: str, pid: str, qty: float) -> None:
    check_whole(await db.equipment.find_one({"org_id": org_id, "id": pid}, {"_id": 0, "name": 1, "stock_uom": 1, "rounding": 1}) or {}, qty)
