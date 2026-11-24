"""Travaux internes — lot 2 : planning d'équipe.

Vue Équipe (personnes × jours) qui réunit travaux internes et événements, placement d'un travail par
glisser-déposer avec contrôles (absence, chevauchement, compétences, effectif, amplitude journalière,
repos, date limite, montage de l'événement lié), jauge de charge et PDF de la semaine.

Les contrôles ne bloquent pas : ils sont renvoyés en 409 et l'utilisateur peut forcer, comme pour
l'affectation des événements. Seules les dépendances d'étapes (séchage…) restent bloquantes (422).
"""
from datetime import date, datetime, timedelta
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import social_core as sc
from core import Ctx, audit, db, need, now_iso
from routes_works import OPEN, _check_dependencies, _clean, _dt, _end_from, _own, _schedule

router = APIRouter(prefix="/api")
R, W = need("events:read"), need("catalog:write")
FMT = "%Y-%m-%dT%H:%M"
HOURLY = ("cdi", "cdd", "alternance", "stage", "autre")   # contrats avec une durée hebdomadaire


# --------------------------------------------------------------------------------------
# Données de la semaine
# --------------------------------------------------------------------------------------
def _span(e: dict) -> tuple[str, str]:
    return (e.get("setup_start") or e["start"])[:16], (e.get("return_end") or e["end"])[:16]


def _hours_in_day(s: str, e: str, day: str) -> float:
    a, b = max(_dt(s), datetime.fromisoformat(day + "T00:00")), min(_dt(e), datetime.fromisoformat(day + "T00:00") + timedelta(days=1))
    return max(0.0, (b - a).total_seconds() / 3600)


def _absent(m: dict, day: str) -> str:
    u = next((u for u in m.get("unavailabilities") or [] if u["start"] <= day <= u["end"]), None)
    return (u.get("reason") or "Absence") if u else ""


async def _context(ctx: Ctx, frm: str, to: str) -> dict:
    """Personnes, événements et travaux qui touchent [frm, to] (dates AAAA-MM-JJ, bornes incluses)."""
    lo, hi = frm + "T00:00", to + "T23:59"
    team = [m for m in await ctx.list("team", {}, limit=1000) if m.get("active", True)]
    events = [e for e in await ctx.list("events", {"status": {"$nin": ["cloture", "demande", "annule", "perdu"]}}, limit=5000)
              if e.get("start") and _span(e)[0] <= hi and lo <= _span(e)[1]]
    works = await db.work_orders.find(ctx.q({"status": {"$in": list(OPEN) + ["fait"]}, "scheduled_start": {"$ne": "", "$lte": hi}, "scheduled_end": {"$gte": lo},
                                             "deleted_at": None}), {"_id": 0}).to_list(5000)
    try:
        d = await sc.load(ctx.org_id)
    except Exception:  # pôle Social absent ou incomplet : valeurs par défaut
        d = {"contracts": [], "params": dict(sc.DEFAULTS)}
    return {"team": team, "events": events, "works": works, "social": d, "params": d["params"]}


def _capacity(c: dict, m: dict) -> float | None:
    """Heures disponibles un jour ouvré ; None pour les intermittents et externes (pas de durée contractuelle)."""
    ctype = m.get("contract_type") or "cdi"
    if ctype not in HOURLY:
        return None
    cur = sc.current_contract(c["social"], m["id"]) if c["social"].get("contracts") else None
    return round(((cur or {}).get("weekly_hours") or c["params"]["weekly_hours"]) / 5, 2)


def _items(c: dict, mid: str, exclude: str = "") -> list[dict]:
    out = [{"kind": "event", "id": e["id"], "title": e["title"], "code": e.get("code", ""), "start": _span(e)[0], "end": _span(e)[1], "status": e["status"]}
           for e in c["events"] if any(t.get("member_id") == mid for t in e.get("team") or [])]
    out += [{"kind": "work", "id": w["id"], "title": w["title"], "type": w.get("type", ""), "priority": w.get("priority", "normale"), "status": w["status"],
             "start": w["scheduled_start"][:16], "end": w["scheduled_end"][:16], "event_id": w.get("event_id", ""), "parent_id": w.get("parent_id", ""),
             "lead": w.get("lead_id") == mid} for w in c["works"] if w["id"] != exclude and (mid in (w.get("assignee_ids") or []) or w.get("lead_id") == mid)]
    return sorted(out, key=lambda i: i["start"])


def _checks(c: dict, w: dict, start: str, end: str, people: list[str]) -> list[str]:
    """Contrôles d'un placement. Renvoie des messages lisibles ; liste vide = rien à signaler."""
    p, team, out = c["params"], {m["id"]: m for m in c["team"]}, []
    days = sorted({(_dt(start) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((_dt(end) - _dt(start)).days + 1)})
    if len(people) < (w.get("required_people") or 1):
        out.append(f"Effectif insuffisant : {len(people)} personne(s) pour {w.get('required_people') or 1} requise(s)")
    skills = {s.lower() for pid in people for s in (team.get(pid) or {}).get("skills") or []}
    miss = [s for s in w.get("required_skills") or [] if s.lower() not in skills]
    if miss:
        out.append("Compétence(s) manquante(s) dans l'équipe : " + ", ".join(miss))
    for pid in people:
        m = team.get(pid)
        if not m:
            raise HTTPException(422, "Personne inconnue dans l'équipe")
        n = m["name"]
        for day in days:
            if r := _absent(m, day):
                out.append(f"{n} est indisponible le {day} ({r})")
        items = _items(c, pid, exclude=w["id"])
        for i in items:
            if i["start"] < end and start < i["end"]:
                out.append(f"{n} est déjà sur « {i['title']} » ({i['start'][11:]}–{i['end'][11:]})")
        for day in days:
            h = sum(_hours_in_day(i["start"], i["end"], day) for i in items) + _hours_in_day(start, end, day)
            if h > p["daily_max"]:
                out.append(f"{n} : {h:g} h le {day} (maximum {p['daily_max']:g} h)")
        # Repos quotidien : des créneaux séparés de moins de N h forment une même « journée » ;
        # son amplitude ne peut dépasser 24 h − N h (ex. 13 h pour 11 h de repos).
        rest, block = timedelta(hours=p["rest_hours"]), None
        for i in sorted(items + [{"start": start, "end": end}], key=lambda x: x["start"]):
            s_, e_ = _dt(i["start"]), _dt(i["end"])
            if block and s_ - block[1] < rest:
                block = (block[0], max(block[1], e_), block[2] or i["start"] == start)
            else:
                block = (s_, e_, i["start"] == start)
            if block[2] and block[1] - block[0] > timedelta(hours=24) - rest:
                out.append(f"{n} : repos de moins de {p['rest_hours']:g} h (amplitude de {(block[1] - block[0]).total_seconds() / 3600:g} h)")
                break
    if w.get("deadline") and end[:10] > w["deadline"][:10]:
        out.append(f"Se termine après la date limite du {w['deadline'][:10]}")
    ev = next((e for e in c["events"] if e["id"] == w.get("event_id")), None)
    if ev and end > _span(ev)[0]:
        out.append(f"Se termine après le début du montage de « {ev['title']} »")
    return out


# --------------------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------------------
def _range(start: str, days: int) -> tuple[str, str]:
    try:
        d0 = date.fromisoformat(start) if start else date.today()
    except ValueError:
        raise HTTPException(422, "Date de début invalide")
    days = max(1, min(days, 31))
    return d0.isoformat(), (d0 + timedelta(days=days - 1)).isoformat()


async def _board(ctx: Ctx, request: Request, start: str, days: int) -> dict:
    frm, to = _range(start, days)
    c = await _context(ctx, frm, to)
    keys = [(date.fromisoformat(frm) + timedelta(days=i)).isoformat() for i in range((date.fromisoformat(to) - date.fromisoformat(frm)).days + 1)]
    team = c["team"]
    if _own(ctx):
        team = [m for m in team if m["id"] == ctx.team_id]
    rows, p = [], c["params"]
    for m in sorted(team, key=lambda m: m["name"].lower()):
        cap, items = _capacity(c, m), _items(c, m["id"])
        cells, total, capacity = [], 0.0, 0.0
        for k in keys:
            its = [i for i in items if i["start"][:10] <= k <= i["end"][:10] and _hours_in_day(i["start"], i["end"], k) > 0]
            h = round(sum(_hours_in_day(i["start"], i["end"], k) for i in its), 2)
            off = _absent(m, k)
            weekday = date.fromisoformat(k).weekday() < 5
            dcap = 0 if off else (cap if cap is not None else p["daily_max"]) if weekday or cap is None else 0
            total, capacity = total + h, capacity + (dcap or 0)
            cells.append({"date": k, "items": its, "hours": h, "absent": off, "capacity": dcap, "over": h > p["daily_max"]})
        rows.append({"id": m["id"], "name": m["name"], "color": m.get("color") or "#888", "skills": m.get("skills") or [], "contract_type": m.get("contract_type") or "",
                     "cells": cells, "hours": round(total, 2), "capacity": round(capacity, 2), "load_pct": round(100 * total / capacity) if capacity else None,
                     "intermittent": cap is None})
    return {"from": frm, "to": to, "days": keys, "members": rows, "daily_max": p["daily_max"], "rest_hours": p["rest_hours"]}


@router.get("/work-planning")
async def board(request: Request, start: str = "", days: int = 7, ctx: Ctx = Depends(R)):
    return await _board(ctx, request, start, days)


class PlaceIn(BaseModel):
    scheduled_start: str
    scheduled_end: str = ""
    assignee_ids: list[str] | None = None   # None = garder l'équipe actuelle
    add_assignee_id: str = ""               # dépôt sur la ligne d'une personne : on l'ajoute
    force: bool = False


@router.post("/work-orders/{wid}/place")
async def place(wid: str, body: PlaceIn, request: Request, ctx: Ctx = Depends(W)):
    w = await db.work_orders.find_one(ctx.q({"id": wid, "deleted_at": None}), {"_id": 0})
    if not w:
        raise HTTPException(404, "Travail introuvable")
    if w["status"] in ("fait", "annule"):
        raise HTTPException(422, "Ce travail est terminé ou annulé")
    people = list(w.get("assignee_ids") or []) if body.assignee_ids is None else list(dict.fromkeys(body.assignee_ids))
    if body.add_assignee_id and body.add_assignee_id not in people:
        people.append(body.add_assignee_id)
    start = _dt(body.scheduled_start).strftime(FMT)
    end = _dt(body.scheduled_end).strftime(FMT) if body.scheduled_end else _end_from(start, w.get("estimated_minutes") or 60, max(len(people), w.get("required_people") or 1))
    if _dt(end) <= _dt(start):
        raise HTTPException(422, "La fin doit être après le début")
    upd = {"scheduled_start": start, "scheduled_end": end, "assignee_ids": people}
    if w.get("lead_id") and w["lead_id"] not in people:
        upd["lead_id"] = ""
    await _check_dependencies(ctx, wid, {**w, **upd})
    c = await _context(ctx, start[:10], end[:10])
    issues = _checks(c, w, start, end, people)
    if issues and not body.force:
        raise HTTPException(409, {"code": "planning_conflict", "message": " ; ".join(issues), "conflicts": issues})
    _schedule(upd, w)
    upd["updated_at"] = now_iso()
    if issues:
        upd["forced_conflicts"] = issues
    await db.work_orders.update_one(ctx.q({"id": wid}), {"$set": upd})
    await audit(ctx.org_id, ctx.member, "work_order_placed", w["title"], f"{start} → {end}" + (" (forcé)" if issues else ""))
    return _clean(ctx, request, {**w, **upd, "forced": bool(issues)})


@router.post("/work-orders/{wid}/unplace")
async def unplace(wid: str, ctx: Ctx = Depends(W)):
    w = await db.work_orders.find_one(ctx.q({"id": wid, "deleted_at": None}), {"_id": 0})
    if not w:
        raise HTTPException(404, "Travail introuvable")
    await db.work_orders.update_one(ctx.q({"id": wid}), {"$set": {"scheduled_start": "", "scheduled_end": "", "status": "a_planifier", "updated_at": now_iso()}})
    return {"ok": True}


@router.get("/work-planning/pdf")
async def board_pdf(request: Request, start: str = "", days: int = 7, ctx: Ctx = Depends(R)):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    b = await _board(ctx, request, start, days)
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "name": 1}) or {}
    st = getSampleStyleSheet()
    small = st["BodyText"].clone("s", fontSize=7, leading=8.5)
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;")  # noqa: E731
    wd = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
    head = ["Personne"] + [f"{wd[date.fromisoformat(k).weekday()]} {k[8:]}/{k[5:7]}" for k in b["days"]]
    data = [head]
    for m in b["members"]:
        load = f"{m['hours']:g} h" + (f" / {m['capacity']:g} h" if m["capacity"] and not m["intermittent"] else "")
        row = [Paragraph(f"<b>{esc(m['name'])}</b><br/>{load}", small)]
        for cell in m["cells"]:
            lines = [f"{i['start'][11:] if i['start'][:10] == cell['date'] else '↳'}–{i['end'][11:] if i['end'][:10] == cell['date'] else '…'} "
                     f"{'◆ ' if i['kind'] == 'event' else ''}{esc(i['title'])}" for i in cell["items"]]
            if cell["absent"]:
                lines.insert(0, f"<i>{esc(cell['absent'])}</i>")
            row.append(Paragraph("<br/>".join(lines), small))
        data.append(row)
    width = landscape(A4)[0] - 20 * mm
    t = Table(data, colWidths=[32 * mm] + [(width - 32 * mm) / len(b["days"])] * len(b["days"]), repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
                           ("FONTSIZE", (0, 0), (-1, 0), 8), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm, topMargin=10 * mm, bottomMargin=10 * mm,
                            title=f"Planning équipe {b['from']}")
    doc.build([Paragraph(f"{esc(org.get('name', ''))} — planning de l'équipe du {b['from']} au {b['to']}", st["Heading2"]),
               Paragraph("◆ = événement ; autres lignes = travaux internes.", small), Spacer(1, 4), t])
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="planning-equipe-{b["from"]}.pdf"'})
