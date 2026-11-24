"""Nomenclatures (kits paramétriques) et calculateur modulaire (scène, piste). Le kit « Scène » par défaut vit dans le code."""
import ast
import math
import operator as op
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

import routes_stock as rs
from core import Ctx, db, need, new_id, now_iso
from routes_units import num

router = APIRouter(prefix="/api")
R, W = need("catalog:read"), need("catalog:write")
STEP = 0.5
OPS = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.Mod: op.mod, ast.USub: op.neg, ast.Not: op.not_, ast.Eq: op.eq, ast.NotEq: op.ne,
       ast.Lt: op.lt, ast.LtE: op.le, ast.Gt: op.gt, ast.GtE: op.ge}
FUNCS = {"ceil": lambda x: math.ceil(x - 1e-9), "floor": lambda x: math.floor(x + 1e-9), "round": round, "min": min, "max": max, "if_": lambda c, a, b=0: a if c else b}


class FormulaError(ValueError):
    pass


def evaluate(expr: str, variables: dict):
    """Moteur d'expressions sécurisé (jamais d'eval) : + - * / ( ), comparaisons, et/ou, ceil floor round min max if()."""
    names = {**variables, "oui": True, "non": False, "vrai": True, "faux": False}

    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float, bool, str)):
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in names:
                raise FormulaError(f"Variable inconnue : {n.id}")
            return names[n.id]
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            return OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in OPS:
            return OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.BoolOp):
            vals = [ev(v) for v in n.values]
            return all(vals) if isinstance(n.op, ast.And) else any(vals)
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and type(n.ops[0]) in OPS:
            return OPS[type(n.ops[0])](ev(n.left), ev(n.comparators[0]))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS and not n.keywords:
            return FUNCS[n.func.id](*[ev(a) for a in n.args])
        raise FormulaError("Expression non autorisée")
    try:
        src = re.sub(r"\bif\s*\(", "if_(", str(expr).strip()).replace("&&", " and ").replace("||", " or ")
        return ev(ast.parse(src, mode="eval").body)
    except FormulaError:
        raise
    except ZeroDivisionError:
        raise FormulaError("Division par zéro")
    except Exception:
        raise FormulaError("Formule invalide")


DEFAULT_PARAMS = {"hauteur": 60, "systeme": "", "pieds_par_praticable": 4, "clamps_par_metre": 1, "moquette": False, "couleur_moquette": "noir", "rabat": 0.1, "jupe": False,
                  "cotes_jupe": ["face", "gauche", "droite"], "escalier": False, "nb_escaliers": 1, "garde_corps": False, "longueur_garde_corps": 0, "terrain_irregulier": False, "ratio": 2}
SCENE = {"id": "scene", "name": "Scène modulaire", "calculator": "modular", "tile_role": "praticable", "use_legs": True, "lines": [
    {"role": "clamp", "label": "Clamps de liaison", "qty": "ceil(longueur_jonctions * clamps_par_metre)", "cond": ""},
    {"role": "egalisateur", "label": "Égalisateurs", "qty": "if(terrain_irregulier, nb_pieds, ceil(nb_pieds * 0.1))", "cond": ""},
    {"role": "moquette", "label": "Moquette", "qty": "ml_moquette", "cond": "moquette"},
    {"role": "scotch", "label": "Scotch double face", "qty": "ceil((perimetre + joints_moquette) * 1.1 / 25)", "cond": "moquette"},
    {"role": "gaffer", "label": "Gaffer", "qty": "ceil(surface / 50)", "cond": "moquette"},
    {"role": "jupe", "label": "Jupe de scène", "qty": "ceil(longueur_jupe)", "cond": "jupe"},
    {"role": "escalier", "label": "Escalier", "qty": "nb_escaliers", "cond": "escalier or hauteur >= 40"},
    {"role": "garde_corps", "label": "Garde-corps", "qty": "ceil(longueur_garde_corps / 2)", "cond": "garde_corps"},
    {"role": "kit_outils", "label": "Kit outils scène", "qty": "1", "cond": ""}]}


async def kits(org_id: str) -> list:
    mine = {k["id"]: k async for k in db.kits.find({"org_id": org_id, "deleted_at": None}, {"_id": 0, "org_id": 0})}
    return [{**mine.pop("scene"), "custom": True} if "scene" in mine else {**SCENE, "custom": False}] + [{**k, "custom": True} for k in mine.values()]


def proposals(surface: float, ratio: float) -> list:
    cands = [(i * STEP, j * STEP) for i in range(2, 81) for j in range(2, i + 1)]
    cands.sort(key=lambda c: abs(c[0] * c[1] - surface) / surface + 0.1 * abs(c[0] / c[1] - ratio))
    return [{"ouverture": w, "profondeur": d, "surface": w * d} for w, d in cands[:3]]


def tile(w: float, d: float, formats: list, stock: dict) -> tuple:
    cw, cd = round(w / STEP), round(d / STEP)
    owner, pieces, left = [[0] * cw for _ in range(cd)], [], dict(stock)
    fm = sorted(formats, key=lambda f: -f["a"] * f["b"])
    for missing in (False, True):
        for f in fm:
            for y in range(cd):
                for x in range(cw):
                    if owner[y][x] or (not missing and left.get(f["id"], 0) < 1):
                        continue
                    for a, b in ((f["a"], f["b"]), (f["b"], f["a"])):
                        if x + a <= cw and y + b <= cd and not any(owner[y + j][x + i] for j in range(b) for i in range(a)):
                            n = len(pieces) + 1
                            for j in range(b):
                                for i in range(a):
                                    owner[y + j][x + i] = n
                            pieces.append({"n": n, "x": x * STEP, "y": y * STEP, "w": a * STEP, "d": b * STEP, "product_id": f["id"], "format": f["name"], "missing": missing})
                            left[f["id"]] = left.get(f["id"], 0) - 1
                            break
    joints = sum(STEP for y in range(cd) for x in range(cw) for dx, dy in ((1, 0), (0, 1)) if x + dx < cw and y + dy < cd and owner[y][x] != owner[y + dy][x + dx])
    return pieces, joints


def carpet(w: float, d: float, widths: list, rabat: float) -> Optional[dict]:
    best = None
    for c in widths:
        for sens, pose, perp in (("profondeur", d, w), ("ouverture", w, d)):
            les = math.ceil(perp / c["width"] - 1e-9)
            ml = round(les * (pose + 2 * rabat), 3)
            x = {"product_id": c["id"], "largeur": c["width"], "sens": sens, "les": les, "longueur_le": round(pose + 2 * rabat, 3), "ml": ml, "m2": round(ml * c["width"], 3),
                 "chute": round(ml * c["width"] - w * d, 3), "joints": round((les - 1) * pose, 3)}
            if not best or x["chute"] < best["chute"]:
                best = x
    return best


async def availability(org_id: str, ev: Optional[dict], pids: list) -> dict:
    w = await rs.world(org_id)
    if not ev or not ev.get("start"):
        return {p: (w["eqs"].get(p) or {}).get("qty_total", 0) for p in pids}
    evs = [e for e in await rs._evs(org_id) if e["id"] != ev["id"]]
    return {p: sum(r["qty"] for r in rs.allocate(w, evs, p, 10 ** 6, rs.target(ev), rs.buffered(rs.period(ev), w["eqs"][p]), ev["id"])[0]) for p in pids if p in w["eqs"]}


async def compute(ctx: Ctx, kit: dict, params: dict, ev: Optional[dict], keep: Optional[dict] = None) -> dict:
    p = {**DEFAULT_PARAMS, **{k: v for k, v in params.items() if v is not None}}
    eqs = await ctx.list("equipment", {"attributes.role": {"$exists": True}}, limit=5000)
    at = lambda e, k, dflt=None: (e.get("attributes") or {}).get(k, dflt)  # noqa: E731
    sysok = lambda e: not p["systeme"] or not at(e, "systeme") or at(e, "systeme") == p["systeme"]  # noqa: E731
    by_role: dict = {}
    for e in eqs:
        if sysok(e):
            by_role.setdefault(at(e, "role"), []).append(e)
    av = await availability(ctx.org_id, ev, [e["id"] for e in eqs])
    out = {"params": p, "alerts": [], "errors": [], "proposals": [], "lines": [], "layout": None, "vars": {}}
    tiles = [{"id": e["id"], "name": e["name"], "a": round(at(e, "longueur_m") / STEP), "b": round(at(e, "largeur_m") / STEP)} for e in by_role.get(kit.get("tile_role") or "praticable", [])
             if isinstance(at(e, "longueur_m"), (int, float)) and isinstance(at(e, "largeur_m"), (int, float)) and at(e, "longueur_m") >= STEP and at(e, "largeur_m") >= STEP]
    w, d = p.get("ouverture"), p.get("profondeur")
    if not (w and d):
        if not p.get("surface_cible"):
            raise HTTPException(400, "Indiquez une surface ou des dimensions (ouverture × profondeur)")
        out["proposals"] = proposals(float(p["surface_cible"]), float(p["ratio"] or 2))
        w, d = out["proposals"][0]["ouverture"], out["proposals"][0]["profondeur"]
    rw, rd = max(STEP, round(float(w) / STEP) * STEP), max(STEP, round(float(d) / STEP) * STEP)
    if (rw, rd) != (float(w), float(d)):
        out["alerts"].append(f"Dimensions arrondies au module le plus proche : {rw:g} × {rd:g} m")
    w, d = rw, rd
    if not tiles:
        raise HTTPException(400, f"Aucun produit de rôle « {kit.get('tile_role') or 'praticable'} » avec longueur et largeur dans le catalogue (onglet Caractéristiques)")
    pieces, joints = tile(w, d, tiles, av)
    lines: dict = {}

    def add(e: dict, qty, role: str, note: str = "") -> None:
        if qty and qty > 0:
            l = lines.setdefault(e["id"], {"product_id": e["id"], "ref": e.get("ref", ""), "name": e["name"], "role": role, "computed_qty": 0, "note": note})
            l["computed_qty"] = num(l["computed_qty"] + qty)
    ename = {e["id"]: e for e in eqs}
    for pc in pieces:
        add(ename[pc["product_id"]], 1, kit.get("tile_role") or "praticable")
    h, n_p = float(p["hauteur"] or 0), len(pieces)
    v = {**{k: x for k, x in p.items() if isinstance(x, (int, float, bool, str))}, "surface": w * d, "ouverture": w, "profondeur": d, "perimetre": 2 * (w + d), "nb_praticables": n_p,
         "longueur_jonctions": joints, "nb_jonctions": round(joints / STEP), "nb_pieds": 0, "nb_pieds_telescopiques": 0, "ml_moquette": 0, "m2_moquette_achetee": 0, "chute_moquette_m2": 0,
         "joints_moquette": 0, "les_moquette": 0, "largeur_rouleau_retenue": 0,
         "longueur_jupe": sum({"face": w, "arriere": w, "gauche": d, "droite": d}.get(c, 0) for c in p.get("cotes_jupe") or [])}
    if kit.get("use_legs", True) and h > 0:
        need_legs = v["nb_pieds"] = n_p * int(p["pieds_par_praticable"] or 4)
        fixed = next((e for e in by_role.get("pied", []) if at(e, "hauteur_fixe_cm") == h), None)
        take = min(need_legs, max(0, av.get(fixed["id"], 0))) if fixed else 0
        rest = need_legs - take
        for t in [e for e in by_role.get("pied_telescopique", []) if (at(e, "hauteur_min_cm") or 0) <= h <= (at(e, "hauteur_max_cm") or 0)]:
            q = min(rest, max(0, av.get(t["id"], 0)))
            add(t, q, "pied_telescopique", f"réglé à {h:g} cm")
            rest, v["nb_pieds_telescopiques"] = rest - q, v["nb_pieds_telescopiques"] + q
        if fixed:
            add(fixed, take + rest, "pied")
        elif rest:
            out["alerts"].append(f"Aucun pied de {h:g} cm dans le catalogue : {rest} pieds à couvrir")
    if p["moquette"]:
        c = carpet(w, d, [{"id": e["id"], "width": at(e, "largeur_rouleau_m")} for e in by_role.get("moquette", [])
                          if isinstance(at(e, "largeur_rouleau_m"), (int, float)) and str(at(e, "couleur", "")).lower() == str(p["couleur_moquette"]).lower()], float(p["rabat"]))
        if c:
            v.update({"ml_moquette": c["ml"], "m2_moquette_achetee": c["m2"], "chute_moquette_m2": c["chute"], "joints_moquette": c["joints"], "les_moquette": c["les"], "largeur_rouleau_retenue": c["largeur"]})
        else:
            out["alerts"].append(f"Aucune moquette « {p['couleur_moquette']} » avec largeur de rouleau dans le catalogue")
    else:
        c = None
    for kl in kit.get("lines") or []:
        try:
            if kl.get("cond") and not evaluate(kl["cond"], v):
                continue
            q = evaluate(kl["qty"], v)
        except FormulaError as e:
            out["errors"].append(f"{kl.get('label') or kl.get('role')} : {e}")
            continue
        cands = by_role.get(kl["role"], []) if not kl.get("product_id") else [e for e in eqs if e["id"] == kl["product_id"]]
        if kl["role"] == "moquette":
            cands = [ename[c["product_id"]]] if c else []
        cands = sorted(cands, key=lambda e: at(e, "hauteur_fixe_cm") != h)
        if cands:
            add(cands[0], q, kl["role"], kl.get("note", ""))
        elif q and kl["role"] not in ("moquette", "kit_outils"):
            out["alerts"].append(f"{kl.get('label') or kl['role']} : aucun produit de rôle « {kl['role']} » dans le catalogue ({q:g} nécessaires)")
    if h > 100 and not p["garde_corps"]:
        out["alerts"].append("Garde-corps conseillé au-delà de 100 cm")
    if h > 40 and not p["escalier"]:
        out["alerts"].append("Escalier ajouté : conseillé au-delà de 40 cm")
    for l in lines.values():
        adj = (keep or {}).get(l["product_id"])
        l.update({"adjusted_qty": adj, "qty": adj if adj is not None else l["computed_qty"], "available": av.get(l["product_id"], 0)})
        l["missing"] = num(max(0, l["qty"] - l["available"]))
    out.update({"lines": list(lines.values()), "vars": v, "layout": {"w": w, "d": d, "pieces": pieces, "carpet": c, "skirt": p.get("cotes_jupe") if p["jupe"] else []},
                "label": f"{kit['name']} {w:g} × {d:g} m" + (f" — h. {h:g} cm" if h else "") + (f" — moquette {p['couleur_moquette']}" if p["moquette"] else "") + (f" — jupe {len(p.get('cotes_jupe') or [])} côtés" if p["jupe"] else "")})
    return out


def merge_auto(ev: dict, auto: dict) -> dict:
    for k in ev.get("kit_instances") or []:
        for l in k["lines"]:
            auto[l["product_id"]] = num(auto.get(l["product_id"], 0) + l["qty"])
    return auto


async def _kit(ctx: Ctx, kid: str) -> dict:
    k = next((k for k in await kits(ctx.org_id) if k["id"] == kid), None)
    if not k:
        raise HTTPException(404, "Nomenclature introuvable")
    return k


@router.get("/kits")
async def list_kits(ctx: Ctx = Depends(R)):
    return {"kits": await kits(ctx.org_id), "default_params": DEFAULT_PARAMS}


class KitLine(BaseModel):
    role: str = Field("", max_length=40)
    product_id: str = ""
    label: str = Field("", max_length=120)
    qty: str = Field(min_length=1, max_length=300)
    cond: str = Field("", max_length=300)
    note: str = Field("", max_length=200)


class KitIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    tile_role: str = Field("praticable", max_length=40)
    use_legs: bool = True
    lines: List[KitLine] = Field(max_length=80)


@router.put("/kits/{kid}")
async def save_kit(kid: str, body: KitIn, ctx: Ctx = Depends(W)):
    kid = new_id() if kid == "new" else kid
    await db.kits.update_one(ctx.q({"id": kid}), {"$set": {**body.model_dump(), "calculator": "modular", "deleted_at": None, "updated_at": now_iso()}, "$setOnInsert": {"created_at": now_iso()}}, upsert=True)
    return {"id": kid, "kits": await kits(ctx.org_id)}


@router.delete("/kits/{kid}")
async def reset_kit(kid: str, ctx: Ctx = Depends(W)):
    await ctx.delete("kits", kid)
    return {"kits": await kits(ctx.org_id)}


class TestIn(BaseModel):
    formula: str = Field(max_length=300)
    variables: dict = {}


@router.post("/kits/test-formula")
async def test_formula(body: TestIn, ctx: Ctx = Depends(R)):
    try:
        return {"ok": True, "result": evaluate(body.formula, body.variables)}
    except FormulaError as e:
        return {"ok": False, "error": str(e)}


class ComputeIn(BaseModel):
    kit_id: str = "scene"
    params: dict = {}


@router.post("/events/{eid}/kits/compute")
async def compute_route(eid: str, body: ComputeIn, ctx: Ctx = Depends(need("events:read"))):
    return await compute(ctx, await _kit(ctx, body.kit_id), body.params, await ctx.get("events", eid, ctx.event_scope()))


async def _store(ctx: Ctx, ev: dict, inst: dict, res: dict) -> dict:
    inst = {**inst, "params": res["params"], "label": res["label"], "vars": res["vars"], "layout": res["layout"], "alerts": res["alerts"] + res["errors"], "updated_at": now_iso(),
            "lines": [{k: l[k] for k in ("product_id", "ref", "name", "role", "computed_qty", "adjusted_qty", "qty", "note")} for l in res["lines"]]}
    rows = [k for k in ev.get("kit_instances") or [] if k["id"] != inst["id"]] + [inst]
    await db.events.update_one(ctx.q({"id": ev["id"]}), {"$set": {"kit_instances": rows}})
    await rs.reallocate(ctx.org_id, ev["id"])
    return inst


@router.post("/events/{eid}/kits")
async def add_instance(eid: str, body: ComputeIn, ctx: Ctx = Depends(need("events:write"))):
    ev = await ctx.get("events", eid, ctx.event_scope())
    return await _store(ctx, ev, {"id": new_id(), "kit_id": body.kit_id, "created_by": ctx.member.get("name")}, await compute(ctx, await _kit(ctx, body.kit_id), body.params, ev))


class InstPatch(BaseModel):
    params: Optional[dict] = None
    product_id: str = ""
    adjusted_qty: Optional[float] = Field(None, ge=-1, le=100000)


@router.patch("/events/{eid}/kits/{iid}")
async def patch_instance(eid: str, iid: str, body: InstPatch, ctx: Ctx = Depends(need("events:write"))):
    ev = await ctx.get("events", eid, ctx.event_scope())
    inst = next((k for k in ev.get("kit_instances") or [] if k["id"] == iid), None)
    if not inst:
        raise HTTPException(404, "Introuvable")
    keep = {l["product_id"]: l["adjusted_qty"] for l in inst["lines"] if l.get("adjusted_qty") is not None}
    if body.product_id:
        keep.pop(body.product_id, None)
        if body.adjusted_qty is not None and body.adjusted_qty >= 0:
            keep[body.product_id] = num(body.adjusted_qty)
    return await _store(ctx, ev, inst, await compute(ctx, await _kit(ctx, inst["kit_id"]), {**inst["params"], **(body.params or {})}, ev, keep))


@router.delete("/events/{eid}/kits/{iid}")
async def delete_instance(eid: str, iid: str, ctx: Ctx = Depends(need("events:write"))):
    ev = await ctx.get("events", eid, ctx.event_scope())
    await db.events.update_one(ctx.q({"id": eid}), {"$set": {"kit_instances": [k for k in ev.get("kit_instances") or [] if k["id"] != iid]}})
    await rs.reallocate(ctx.org_id, eid)
    return {"ok": True}


@router.get("/events/{eid}/kits/{iid}/plan")
async def plan_pdf(eid: str, iid: str, ctx: Ctx = Depends(need("events:read"))):
    import io
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen.canvas import Canvas
    ev = await ctx.get("events", eid, ctx.event_scope())
    inst = next((k for k in ev.get("kit_instances") or [] if k["id"] == iid), None)
    if not inst:
        raise HTTPException(404, "Introuvable")
    lay, buf = inst["layout"], io.BytesIO()
    pw, ph = landscape(A4)
    c, s = Canvas(buf, pagesize=(pw, ph)), min((pw - 80) / lay["w"], (ph - 140) / lay["d"])
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, ph - 40, inst["label"][:110])
    c.setFont("Helvetica", 9)
    c.drawString(40, ph - 56, f"{ev.get('code', '')} · {ev.get('title', '')} — vue de dessus, public en bas"[:140])
    palette, fm = [colors.HexColor(x) for x in ("#dbeafe", "#dcfce7", "#fef3c7", "#fce7f3", "#e0e7ff")], {}
    for p in lay["pieces"]:
        col = fm.setdefault(p["format"], palette[len(fm) % len(palette)])
        c.setFillColor(colors.HexColor("#fecaca") if p["missing"] else col)
        x, y = 40 + p["x"] * s, ph - 80 - (p["y"] + p["d"]) * s
        c.rect(x, y, p["w"] * s, p["d"] * s, fill=1, stroke=1)
        c.setFillColor(colors.black)
        c.drawCentredString(x + p["w"] * s / 2, y + p["d"] * s / 2 - 3, str(p["n"]))
    c.drawString(40, 40, " · ".join(f"{l['qty']:g} × {l['name']}" for l in inst["lines"])[:230])
    c.save()
    return Response(buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="plan-scene.pdf"'})
