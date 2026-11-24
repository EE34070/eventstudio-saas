"""Réemploi du matériel déplacé dans un même événement : interne, jamais visible du client."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends

from core import Ctx, db, need, new_id, now_iso

router = APIRouter(prefix="/api")
TRANSFER = 20


def _m(s: str) -> int:
    return int(s[:2]) * 60 + int(s[3:5])


def hours(by: dict, b: dict):
    """(début, fin, titre) en minutes de la section qui porte l'horaire d'utilisation."""
    while b:
        if b.get("usage_start") and b.get("usage_end"):
            a, e = _m(b["usage_start"]), _m(b["usage_end"])
            a += 1440 if a < 360 else 0
            while e <= a:
                e += 1440
            return a, e, b.get("title", ""), b["id"]
        b = by.get(b.get("parent_id"))
    return None


def space_of(by: dict, b: dict) -> str:
    while b:
        if b.get("space_id"):
            return b["space_id"]
        b = by.get(b.get("parent_id"))
    return ""


async def apply(org_id: str, blocks: list, per_space: dict | None = None) -> None:
    by = {b["id"]: b for b in blocks}
    ids = [b.get("equipment_id") for b in blocks if b.get("reuse_from")]
    eqs = {e["id"]: e async for e in db.equipment.find({"org_id": org_id, "id": {"$in": ids}}, {"_id": 0, "id": 1, "movable_during_event": 1})}
    org = await db.orgs.find_one({"id": org_id}, {"_id": 0, "transfer_minutes": 1}) or {}
    used: dict = {}
    for b in blocks:
        b.update(reuse_effective=0, reuse_alert="")
        if b["type"] != "line" or not b.get("reuse_from"):
            b.update(reuse_status="", reuse_from="")
            continue
        src, why, status = by.get(b["reuse_from"]), "", "validated"
        if not src or src is b or not b.get("equipment_id") or src.get("equipment_id") != b["equipment_id"] or src.get("reuse_from"):
            why = "La ligne d'origine n'existe plus, n'est pas le même article ou est elle-même réemployée"
        elif eqs.get(b["equipment_id"], {}).get("movable_during_event") is False:
            why = "Article non déplaçable en cours d'événement : réemploi impossible"
        else:
            h1, h2 = hours(by, src), hours(by, b)
            if not h1 or not h2:
                why = "Renseignez l'horaire d'utilisation des deux sections"
            elif h1[0] < h2[1] and h2[0] < h1[1]:
                if (b.get("reuse_force_reason") or "").strip():
                    status = "forced"
                else:
                    why = "Les deux sections sont utilisées en même temps : réemploi impossible"
            else:
                gap = h2[0] - h1[1] if h2[0] >= h1[1] else h1[0] - h2[1]
                need_min = (per_space or {}).get(space_of(by, b)) or org.get("transfer_minutes") or TRANSFER
                if gap < need_min:
                    b["reuse_alert"] = f"Seulement {gap} min pour déplacer le matériel (temps de bascule : {need_min} min)"
        if why:
            b.update(reuse_status="invalid", reuse_alert=why)
            continue
        n = max(0, min(b.get("reuse_qty") or b["qty"], b["qty"], src["qty"] - used.get(src["id"], 0)))
        used[src["id"]] = used.get(src["id"], 0) + n
        b.update(reuse_status=status, reuse_effective=n, reuse_qty=n)


async def sync_steps(org_id: str, q: dict, blocks: list, per_space: dict | None = None) -> None:
    """Chaque réemploi validé crée ou met à jour l'étape « Bascule » du déroulé."""
    ev = await db.events.find_one({"org_id": org_id, "id": q.get("event_id") or "-"}, {"_id": 0, "id": 1, "start": 1})
    if not ev:
        return
    by, groups = {b["id"]: b for b in blocks}, {}
    for b in blocks:
        if b.get("reuse_effective"):
            h1, h2 = hours(by, by[b["reuse_from"]]), hours(by, b)
            groups.setdefault((h1[3], h2[3]), {"h1": h1, "h2": h2, "items": [], "min": (per_space or {}).get(space_of(by, b))})["items"].append(f"{b['reuse_effective']:g} × {b['label']}")
    org = await db.orgs.find_one({"id": org_id}, {"_id": 0, "transfer_minutes": 1}) or {}
    keep = []
    for (a, c), g in groups.items():
        ref = f"reuse:{q['id']}:{a}:{c}"
        keep.append(ref)
        doc = {"title": f"Bascule {g['h1'][2]} → {g['h2'][2]}", "description": "Matériel à déplacer : " + ", ".join(g["items"]), "start": (datetime.fromisoformat(ev["start"][:10]) + timedelta(minutes=g["h1"][1])).isoformat()[:16],
               "duration_min": g["min"] or org.get("transfer_minutes") or TRANSFER}
        if not (await db.schedule_steps.update_one({"org_id": org_id, "source_ref": ref, "deleted_at": None}, {"$set": doc})).matched_count:
            await db.schedule_steps.insert_one({"id": new_id(), "org_id": org_id, "created_at": now_iso(), "event_id": ev["id"], "source": "auto", "source_ref": ref, "time_mode": "fixed", "phase": "exploitation", "relevance": "concerns_us",
                                                "visible": True, "space_label": "", "people": "", "internal_notes": "", "status": "planned", "deleted_at": None, "order": 999, **doc})
    await db.schedule_steps.update_many({"org_id": org_id, "source_ref": {"$regex": f"^reuse:{q['id']}:", "$nin": keep}, "deleted_at": None}, {"$set": {"deleted_at": now_iso()}})


@router.get("/quotes/{qid}/mobilized")
async def mobilized(qid: str, ctx: Ctx = Depends(need("finance:read"))):
    q = await ctx.get("quotes", qid)
    rows: dict = {}
    for l in q.get("lines") or []:
        if l.get("equipment_id"):
            r = rows.setdefault(l["equipment_id"], {"equipment_id": l["equipment_id"], "label": l["label"], "quoted": 0, "reused": 0})
            r["quoted"], r["reused"] = r["quoted"] + l["qty"], r["reused"] + (l.get("reused") or 0)
    return [{**r, "mobilized": r["quoted"] - r["reused"]} for r in rows.values()]


async def transfers_of(org_id: str, eid: str) -> list:
    return [{"time": s["start"][11:16], "title": s["title"], "description": s.get("description", "")}
            async for s in db.schedule_steps.find({"org_id": org_id, "event_id": eid, "source_ref": {"$regex": "^reuse:"}, "deleted_at": None}, {"_id": 0}).sort("start", 1)]


@router.get("/events/{eid}/mobilized")
async def event_mobilized(eid: str, ctx: Ctx = Depends(need("events:read"))):
    """Quantités seulement, aucun prix : devisé, réemployé, réellement mobilisé."""
    await ctx.get("events", eid, ctx.event_scope())
    qs = await db.quotes.find(ctx.q({"event_id": eid, "active": {"$ne": False}, "status": {"$in": ["accepte", "brouillon", "envoye", "vu", "negociation"]}}), {"_id": 0, "status": 1, "lines": 1}).to_list(50)
    acc = [q for q in qs if q["status"] == "accepte"]
    rows: dict = {}
    for q in acc or qs:
        for l in q.get("lines") or []:
            if l.get("equipment_id"):
                r = rows.setdefault(l["equipment_id"], {"equipment_id": l["equipment_id"], "label": l["label"], "quoted": 0, "reused": 0})
                r["quoted"], r["reused"] = r["quoted"] + l["qty"], r["reused"] + (l.get("reused") or 0)
    return {"basis": "accepte" if acc else "en_cours" if qs else "", "rows": [{**r, "mobilized": r["quoted"] - r["reused"]} for r in rows.values()], "transfers": await transfers_of(ctx.org_id, eid)}
