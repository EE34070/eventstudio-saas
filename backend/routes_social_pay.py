"""Pôle Social (2/2) : pré-paie, import des bulletins, gérants TNS, échéances sociales, prévisionnel, budget, scénarios, tableau de bord.
Aucune écriture comptable : pointages et estimations seulement."""
import copy
import csv
import io
from datetime import date, timedelta
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

import routes_finance_reports as rp
import social_core as sc
from core import Ctx, audit, db, new_id, now_iso
from routes_social import D, DO, R, W, YM, ai_pdf, keep_file, num, period_doc, read_small, staffed, table, who

router = APIRouter(prefix="/api")
col, r2 = rp.col, sc.r2
PRE_COLS = ["Nom", "Contrat", "Entrée", "Sortie", "Base", "Heures", "Heures sup.", "Nuit", "Dimanche", "Férié", "Primes et cachets", "Indemnités", "Frais", "Acomptes", "Congés payés (j)", "Autres absences"]
NUMS = ("gross", "employee_contrib", "employer_contrib", "net_pay", "net_taxable", "pas", "hours", "employer_cost_total", "variables_paid")


# ---------- Pré-paie ----------
async def build_prepay(ctx: Ctx, period: str) -> list:
    d, rows = await sc.load(ctx.org_id), []
    first, last = period + "-01", sc.month_end(period)
    for tid in staffed(d):
        c = sc.contract_at(d, tid, period) or sc.contract_at(d, tid, period, True)
        if not c:
            continue
        h, vs = sc.month_hours(d, tid, period), [v for v in d["variables"] if v["team_id"] == tid and v["period"] == period]
        S = lambda *k: r2(sum(v["amount"] for v in vs if v["kind"] in k))  # noqa: E731
        ab = [a for a in d["absences"] if a["team_id"] == tid and a["status"] == "approved" and a["start"] <= last and a["end"] >= first]
        sid = (d["files"].get(tid) or {}).get("staff_id")
        if c["type"] == "cddu":
            ms = [m for m in d["missions"] if sid and m["provider_id"] == sid and m["date"][:7] == period]
            ts = {t["mission_id"]: t for t in d["timesheets"] if t.get("provider_id") == sid}
            base = sum((ts[m["id"]].get("amount_base", 0) + ts[m["id"]].get("amount_overtime", 0)) if m["id"] in ts else m.get("total_ht") or 0 for m in ms) or (c["base_pay"] * (c.get("quantity") or 1) if c["start"][:7] == period else 0)
        else:
            base = sc.gross_at(d, c, period) + h["overtime_amount"]
        gross = r2(base + S(*sc.GROSS_KINDS))
        rows.append({"team_id": tid, "name": d["team"][tid]["name"], "type": c["type"], "entry": c["start"] if c["start"][:7] == period else "", "exit": c.get("end", "") if (c.get("end") or "")[:7] == period else "", "base": r2(base),
                     "amendment": sc.eff(c) if c.get("version", 1) > 1 and sc.eff(c)[:7] == period else "", "hours": h["total"], "overtime": h["overtime_hours"], "night": h["night"], "sunday": h["sunday"], "holiday": h["holiday"],
                     "bonuses": S(*sc.GROSS_KINDS), "allowances": S("indemnite_repas", "indemnite_deplacement", "grand_deplacement"), "expenses": S("frais"), "advances": S("acompte"),
                     "cp_days": r2(sum(a["days"] for a in ab if a["type"] == "cp")), "absences": ", ".join(f"{sc.ABS_TYPES[a['type']]} {a['start']}→{a['end']}" + (" (subrogation)" if a.get("subrogation") else "") for a in ab if a["type"] != "cp"),
                     "expected_gross": gross, "expected_cost": r2(gross * sc.coef_of(d, tid, c["type"])[0])})
    return sorted(rows, key=lambda r: r["name"])


def pre_cells(r: dict) -> list:
    return [r["name"], sc.TYPES.get(r["type"], r["type"]) + (f" (avenant du {r['amendment']})" if r["amendment"] else ""), r["entry"], r["exit"], r["base"], r["hours"], r["overtime"], r["night"], r["sunday"], r["holiday"], r["bonuses"], r["allowances"], r["expenses"], r["advances"], r["cp_days"], r["absences"]]


def pre_csv(rows: list) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(PRE_COLS)
    w.writerows(pre_cells(r) for r in rows)
    return ("\ufeff" + buf.getvalue()).encode()


def pre_pdf(org: str, period: str, rows: list) -> bytes:
    return rp.to_pdf(f"{org} — Pré-paie {period}", {"tables": [{"key": "p", "title": f"{len(rows)} salarié(s)", "columns": [col(c) for c in PRE_COLS], "rows": [pre_cells(r) for r in rows]}]}, intro=["Éléments variables transmis au cabinet pour l'établissement des bulletins."])


@router.post("/social/periods/{period}/close")
async def close_period(period: str, ctx: Ctx = Depends(W)):
    if len(period) != 7 or (await period_doc(ctx, period))["status"] != "open":
        raise HTTPException(409, "Période déjà clôturée")
    rows, p = await build_prepay(ctx, period), await sc.params_at(ctx.org_id, sc.today())
    org = (await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "name": 1}) or {}).get("name", "")
    draft = {"to": p["firm_email"], "subject": f"{org} — éléments de paie {period}", "status": "draft", "attachments": [f"pre-paie-{period}.csv", f"pre-paie-{period}.pdf"],
             "body": f"Bonjour,\n\nVeuillez trouver ci-joint les éléments variables de paie de {period} pour {len(rows)} salarié(s) : entrées et sorties, heures, primes, absences, acomptes et frais.\n\nBien cordialement,\n{ctx.member.get('name', '')}"}
    await db.pay_periods.update_one(ctx.q({"period": period}), {"$set": {"status": "closed", "variables_closed_at": now_iso(), "closed_by": ctx.member.get("name", ""), "prepay": rows, "draft": draft}, "$setOnInsert": {"id": new_id(), "created_at": now_iso()}}, upsert=True)
    await audit(ctx.org_id, ctx.member, "social_period_closed", period, f"{len(rows)} salarié(s), brouillon d'e-mail préparé (non envoyé)")
    return await payroll(period, ctx)


@router.post("/social/periods/{period}/reopen")
async def reopen(period: str, ctx: Ctx = Depends(W)):
    await db.pay_periods.update_one(ctx.q({"period": period}), {"$set": {"status": "open", "draft": None}})
    return await payroll(period, ctx)


@router.get("/social/periods/{period}/prepay")
async def prepay_file(period: str, format: Literal["csv", "pdf"] = "csv", ctx: Ctx = Depends(R)):
    pd = await period_doc(ctx, period)
    rows = pd.get("prepay") if pd["status"] != "open" else await build_prepay(ctx, period)
    if format == "csv":
        return Response(pre_csv(rows or []), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="pre-paie-{period}.csv"'})
    org = (await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "name": 1}) or {}).get("name", "")
    return Response(pre_pdf(org, period, rows or []), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="pre-paie-{period}.pdf"'})


class DraftIn(BaseModel):
    to: str = Field(max_length=160)
    subject: str = Field(max_length=200)
    body: str = Field(max_length=5000)


@router.put("/social/periods/{period}/draft")
async def put_draft(period: str, body: DraftIn, ctx: Ctx = Depends(W)):
    pd = await period_doc(ctx, period)
    if not pd.get("draft") or pd["draft"]["status"] != "draft":
        raise HTTPException(409, "Aucun brouillon à modifier")
    await db.pay_periods.update_one(ctx.q({"period": period}), {"$set": {"draft": {**pd["draft"], **body.model_dump()}}})
    return await payroll(period, ctx)


@router.post("/social/periods/{period}/send-draft")
async def send_draft(period: str, ctx: Ctx = Depends(W)):
    """Envoi uniquement sur action explicite d'un gérant, jamais automatique."""
    from html import escape
    from emailer import send_email
    import providers_core as pc
    pd = await period_doc(ctx, period)
    dr = pd.get("draft") or {}
    if dr.get("status") != "draft":
        raise HTTPException(409, "Aucun brouillon à envoyer")
    if not pc.MAIL_RE.match(dr.get("to") or "") or dr["to"].endswith("@example.com"):
        raise HTTPException(400, "Adresse du cabinet absente, invalide ou de test : aucun e-mail envoyé")
    org = (await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "name": 1}) or {}).get("name", "")
    sent = await send_email(to=dr["to"], subject=dr["subject"], html="".join(f"<p>{escape(l)}</p>" for l in dr["body"].split("\n") if l.strip()), attachments=[(dr["attachments"][0], pre_csv(pd["prepay"])), (dr["attachments"][1], pre_pdf(org, period, pd["prepay"]))])
    if not sent:
        raise HTTPException(502, "L'e-mail n'a pas pu être envoyé : le brouillon est conservé")
    await db.pay_periods.update_one(ctx.q({"period": period}), {"$set": {"draft.status": "sent", "draft.sent_at": now_iso(), "status": "sent"}})
    await audit(ctx.org_id, ctx.member, "social_prepay_sent", period, dr["to"])
    return await payroll(period, ctx)


class DsnIn(BaseModel):
    done: bool


@router.put("/social/periods/{period}/dsn")
async def dsn(period: str, body: DsnIn, ctx: Ctx = Depends(W)):
    await db.pay_periods.update_one(ctx.q({"period": period}), {"$set": {"dsn_done_at": now_iso() if body.done else None}, "$setOnInsert": {"id": new_id(), "status": "open", "created_at": now_iso()}}, upsert=True)
    return await payroll(period, ctx)


# ---------- Bulletins ----------
def controls(pd: dict, lines: list, pct: float) -> list:
    pre, out = {r["team_id"]: r for r in pd.get("prepay") or []}, []
    got = {l["team_id"] for l in lines if l.get("team_id")}
    out += [{"level": "high", "text": f"{r['name']} : présent dans la pré-paie, bulletin manquant"} for t, r in pre.items() if t not in got] if lines else []
    for l in lines:
        r = pre.get(l.get("team_id"))
        if not l.get("team_id"):
            out.append({"level": "high", "text": f"{l.get('name', '?')} : bulletin non rattaché à un salarié"})
        elif pd.get("prepay") is not None and not r:
            out.append({"level": "high", "text": f"{l['name']} : bulletin sans ligne de pré-paie"})
        if r and l.get("variables_paid") is not None and abs(l["variables_paid"] - r["bonuses"]) > 0.5:
            out.append({"level": "warn", "text": f"{l['name']} : variables envoyées {r['bonuses']:g} € ≠ variables payées {l['variables_paid']:g} €"})
        if r and r["expected_cost"] and l.get("employer_cost_total"):
            gap = (l["employer_cost_total"] - r["expected_cost"]) / r["expected_cost"] * 100
            if abs(gap) > pct:
                k = l["employer_cost_total"] / l["gross"] if l.get("gross") else 0
                out.append({"level": "warn", "text": f"{l['name']} : coût réel {l['employer_cost_total']:g} € vs prévu {r['expected_cost']:g} € ({gap:+.1f} %) — brut {l.get('gross', 0):g} € vs {r['expected_gross']:g} € prévu, coefficient réel {k:.3f}"})
    return out


@router.get("/social/payroll")
async def payroll(period: str = "", ctx: Ctx = Depends(R)):
    period = period if len(period) == 7 else sc.ym_add(sc.today()[:7], -1)
    pd, p = await period_doc(ctx, period), await sc.params_at(ctx.org_id, sc.today())
    lines = await db.payroll_lines.find(ctx.q({"period": period, "status": {"$in": ["draft", "validated"]}}), {"_id": 0}).sort("name", 1).to_list(500)
    emps = [{"team_id": t["id"], "name": t["name"]} for t in await ctx.list("team", sort=[("name", 1)])]
    return {"period": period, "status": pd["status"], "closed_by": pd.get("closed_by"), "closed_at": pd.get("variables_closed_at"), "prepay": pd.get("prepay") if pd["status"] != "open" else await build_prepay(ctx, period), "prepay_cols": PRE_COLS,
            "draft": pd.get("draft"), "dsn_done_at": pd.get("dsn_done_at"), "lines": lines, "controls": controls(pd, lines, p["variance_alert_pct"]), "employees": emps, "can_manage": ctx.can("social:manage"),
            "totals": {k: r2(sum(l.get(k) or 0 for l in lines if l["status"] == "validated")) for k in ("gross", "net_pay", "employer_cost_total")},
            "pennylane": {"connected": False, "note": "Contrôle avec les comptes 64x de Pennylane : disponible quand l'API sera branchée (lecture seule)."}}


async def save_line(ctx: Ctx, period: str, data: dict) -> dict:
    data = {k: (r2(v) if k in NUMS and v is not None else v) for k, v in data.items()}
    if not data.get("employer_cost_total"):
        data["employer_cost_total"] = r2((data.get("gross") or 0) + (data.get("employer_contrib") or 0))
    t = await db.team.find_one(ctx.q({"id": data.get("team_id") or "__"}), {"_id": 0, "name": 1, "contract_type": 1})
    data.update(team_id=data.get("team_id") if t else None, name=(t or {}).get("name") or data.get("name", ""), contract_type=(t or {}).get("contract_type", ""), status="draft")
    if t:
        await db.payroll_lines.update_many(ctx.q({"period": period, "team_id": data["team_id"], "status": "draft"}), {"$set": {"status": "replaced", "updated_at": now_iso()}})
        if await db.payroll_lines.find_one(ctx.q({"period": period, "team_id": data["team_id"], "status": "validated"})):
            raise HTTPException(409, f"{data['name']} a déjà un bulletin validé pour {period}")
    return await ctx.insert("payroll_lines", {**data, "period": period})


HEAD = (("name", ("nom", "salari", "email")), ("employee_contrib", ("salariale",)), ("employer_contrib", ("patronale",)), ("net_taxable", ("imposable",)), ("net_pay", ("net",)), ("pas", ("source", "pas")), ("hours", ("heure",)),
        ("employer_cost_total", ("coût", "cout")), ("variables_paid", ("variable", "prime")), ("gross", ("brut",)))


@router.post("/social/payroll/import")
async def import_journal(period: str = Form(..., pattern=YM), file: UploadFile = File(...), ctx: Ctx = Depends(W)):
    """Journal de paie CSV / Excel : toujours des brouillons à valider."""
    rows = [r for r in table(await read_small(file), file.filename or "") if any(str(c).strip() for c in r)]
    if len(rows) < 2:
        raise HTTPException(400, "Fichier vide")
    idx = {}
    for i, h in enumerate(rows[0]):
        k = next((k for k, words in HEAD if k not in idx and any(w in str(h).lower() for w in words)), None)
        if k:
            idx[k] = i
    if "name" not in idx or "gross" not in idx:
        raise HTTPException(400, "Colonnes attendues : Nom (ou e-mail), Brut, Cotisations salariales, Cotisations patronales, Net à payer, Net imposable, PAS, Heures, Coût employeur")
    d, n = await sc.load(ctx.org_id), 0
    for r in rows[1:]:
        name = str(r[idx["name"]]).strip()
        await save_line(ctx, period, {"name": name, "team_id": who(d, name, name), **{k: num(r[i]) for k, i in idx.items() if k != "name" and i < len(r)}, "source": "journal", "confidence": {}})
        n += 1
    return {**await payroll(period, ctx), "imported": n}


@router.post("/social/payroll/import-pdf")
async def import_payslip(period: str = Form(..., pattern=YM), team_id: str = Form(""), file: UploadFile = File(...), ctx: Ctx = Depends(W)):
    """Bulletin PDF lu par IA : brouillon, champs douteux signalés, validation manuelle obligatoire."""
    fid, data, ctype = await keep_file(ctx, file)
    if ctype != "application/pdf":
        raise HTTPException(400, "Un PDF est attendu")
    out = await ai_pdf(data, "Tu lis un bulletin de paie français. Montants en euros, positifs. N'invente rien : montant absent = 0 avec c = 1 ; en cas de doute, c faible.",
                       'Format : {"name": "Prénom Nom", "period": "AAAA-MM", "values": {"gross": {"v": 0, "c": 0.9}, "employee_contrib": {}, "employer_contrib": {}, "net_pay": {}, "net_taxable": {}, "pas": {}, "hours": {}, "employer_cost_total": {}}, '
                       '"by_body": {"URSSAF": 0, "Audiens": 0}} — gross = salaire brut ; employee_contrib / employer_contrib = totaux des cotisations salariales / patronales ; net_pay = net à payer ; pas = prélèvement à la source ; employer_cost_total = coût global employeur.')
    vals = {k: num((x or {}).get("v")) for k, x in ((out or {}).get("values") or {}).items() if k in NUMS and isinstance(x, dict)}
    conf = {k: max(0.0, min(1.0, num((x or {}).get("c")))) for k, x in ((out or {}).get("values") or {}).items() if k in NUMS and isinstance(x, dict)}
    d = await sc.load(ctx.org_id)
    l = await save_line(ctx, period, {"name": str((out or {}).get("name") or file.filename or "")[:120], "team_id": team_id or who(d, "", str((out or {}).get("name") or "")), **vals, "confidence": conf, "file_id": fid, "source": "pdf",
                                      "by_body": {str(k)[:40]: num(v) for k, v in ((out or {}).get("by_body") or {}).items()}, "warning": "" if out else "Lecture IA indisponible : saisissez les montants à la main, le PDF reste affiché à côté."})
    return {**await payroll(period, ctx), "line_id": l["id"]}


class LineIn(BaseModel):
    team_id: str
    gross: float = Field(ge=0, le=1e7)
    employee_contrib: float = Field(0, ge=0, le=1e7)
    employer_contrib: float = Field(0, ge=0, le=1e7)
    net_pay: float = Field(ge=0, le=1e7)
    net_taxable: float = Field(0, ge=0, le=1e7)
    pas: float = Field(0, ge=0, le=1e7)
    hours: float = Field(0, ge=0, le=400)
    employer_cost_total: float = Field(0, ge=0, le=1e7)
    variables_paid: Optional[float] = Field(None, ge=0, le=1e7)


@router.put("/social/payroll/lines/{lid}")
async def put_line(lid: str, body: LineIn, ctx: Ctx = Depends(W)):
    l = await ctx.get("payroll_lines", lid, {"status": "draft"})
    t = await ctx.get("team", body.team_id)
    d = body.model_dump()
    d["employer_cost_total"] = d["employer_cost_total"] or r2(d["gross"] + d["employer_contrib"])
    await ctx.update("payroll_lines", lid, {**d, "name": t["name"], "contract_type": t.get("contract_type", ""), "confidence": {}})
    return await payroll(l["period"], ctx)


@router.post("/social/payroll/lines/{lid}/validate")
async def validate_line(lid: str, ctx: Ctx = Depends(W)):
    l = await ctx.get("payroll_lines", lid, {"status": "draft"})
    if not l.get("team_id") or not l.get("gross"):
        raise HTTPException(400, "Rattachez le bulletin à un salarié et vérifiez le brut avant de valider")
    if await db.payroll_lines.find_one(ctx.q({"period": l["period"], "team_id": l["team_id"], "status": "validated"})):
        raise HTTPException(409, "Un bulletin est déjà validé pour ce salarié sur cette période")
    pre = next((r for r in (await period_doc(ctx, l["period"])).get("prepay") or [] if r["team_id"] == l["team_id"]), None)
    var = round((l["employer_cost_total"] - pre["expected_cost"]) / pre["expected_cost"] * 100, 1) if pre and pre["expected_cost"] else None
    await ctx.update("payroll_lines", lid, {"status": "validated", "validated_by": ctx.member.get("name", ""), "validated_at": now_iso(), "variance_vs_forecast": var})
    if l.get("file_id"):
        await db.employee_files.update_one(ctx.q({"team_id": l["team_id"]}), {"$push": {"documents": {"kind": "bulletin", "label": f"Bulletin {l['period']}", "file_id": l["file_id"], "period": l["period"]}}, "$setOnInsert": {"id": new_id(), "created_at": now_iso()}}, upsert=True)
    await db.social_notifications.insert_one({"id": new_id(), "org_id": ctx.org_id, "team_id": l["team_id"], "text": f"Votre bulletin de {l['period']} est disponible.", "read": False, "created_at": now_iso()})
    d = await sc.load(ctx.org_id)
    return {**await payroll(l["period"], ctx), "coef": dict(zip(("value", "source"), sc.coef_of(d, l["team_id"], l.get("contract_type") or "cdi")))}


@router.delete("/social/payroll/lines/{lid}")
async def del_line(lid: str, ctx: Ctx = Depends(W)):
    l = await ctx.get("payroll_lines", lid, {"status": {"$in": ["draft", "validated"]}})
    await ctx.update("payroll_lines", lid, {"status": "deleted", "deleted_by": ctx.member.get("name", "")})
    return await payroll(l["period"], ctx)


# ---------- Gérants (TNS) ----------
class MPay(BaseModel):
    amount: float = Field(ge=0, le=1e6)
    periodicity: Literal["monthly", "quarterly", "yearly"] = "monthly"
    start: str = Field(pattern=D)
    end: str = Field("", pattern=DO)
    decision_file_id: str = Field("", max_length=60)


class MContract(BaseModel):
    label: str = Field(max_length=120)
    kind: Literal["madelin", "per", "prevoyance"] = "madelin"
    monthly: float = Field(ge=0, le=1e5)


class MCall(BaseModel):
    id: str = ""
    kind: Literal["provisionnel", "regularisation"] = "provisionnel"
    year: int = Field(ge=2015, le=2100)
    due_date: str = Field(pattern=D)
    amount: float = Field(ge=-1e6, le=1e6)
    file_id: str = Field("", max_length=60)


class ManagerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    status: str = Field("Gérant majoritaire (TNS)", max_length=80)
    pay: List[MPay] = Field(default_factory=list, max_length=30)
    contracts: List[MContract] = Field(default_factory=list, max_length=20)
    calls: List[MCall] = Field(default_factory=list, max_length=200)


def mgr_view(d: dict, m: dict) -> dict:
    y = int(sc.today()[:4])
    pay, est = sc.manager_year(d, m, y), 0.0
    est = r2(pay * d["params"]["tns_rate"] / 100)
    called = r2(sum(c["amount"] for c in m.get("calls") or [] if c["kind"] == "provisionnel" and c["year"] == y))
    gap = r2(est - called)
    tip = ("Provisionnels supérieurs à l'estimation : une modulation à la baisse est possible sur le site de l'URSSAF." if called and gap < -0.1 * est else
           f"Provisionnels inférieurs à l'estimation : prévoyez une régularisation d'environ {gap:,.0f} €.".replace(",", " ") if gap > 0.1 * max(est, 1) else "Provisionnels cohérents avec l'estimation.")
    return {**m, "year": y, "pay_year": r2(pay), "contrib_estimated": est, "contrib_called": called, "regul_estimated": gap, "regul_month": f"{y + 1}-{int(d['params']['tns_regul_month']):02d}", "modulation": tip,
            "contracts_year": r2(sum(c["monthly"] for c in m.get("contracts") or []) * 12), "no_payslip": "TNS : ni bulletin, ni DSN, ni assurance chômage."}


@router.get("/social/managers")
async def managers(ctx: Ctx = Depends(R)):
    d = await sc.load(ctx.org_id)
    return {"rows": [mgr_view(d, m) for m in sorted(d["managers"], key=lambda m: m["name"])], "note": sc.NOTE, "tns_rate": d["params"]["tns_rate"], "can_manage": ctx.can("social:manage")}


@router.post("/social/managers")
async def add_manager(body: ManagerIn, ctx: Ctx = Depends(W)):
    data = body.model_dump()
    data["calls"] = [{**c, "id": c["id"] or new_id()} for c in data["calls"]]
    await ctx.insert("social_managers", {**data, "deleted_at": None})
    return await managers(ctx)


@router.put("/social/managers/{mid}")
async def put_manager(mid: str, body: ManagerIn, ctx: Ctx = Depends(W)):
    data = body.model_dump()
    data["calls"] = [{**c, "id": c["id"] or new_id()} for c in data["calls"]]
    await ctx.update("social_managers", mid, data)
    await audit(ctx.org_id, ctx.member, "social_manager", body.name, "fiche gérant modifiée")
    return await managers(ctx)


@router.delete("/social/managers/{mid}")
async def del_manager(mid: str, ctx: Ctx = Depends(W)):
    await ctx.delete("social_managers", mid)
    return await managers(ctx)


@router.post("/social/managers/{mid}/calls/import-pdf")
async def import_call(mid: str, file: UploadFile = File(...), ctx: Ctx = Depends(W)):
    """Appel ou régularisation URSSAF indépendants lu par IA : proposition à vérifier, rien n'est enregistré sans validation."""
    await ctx.get("social_managers", mid)
    fid, data, ctype = await keep_file(ctx, file)
    out = await ai_pdf(data, "Tu lis un appel de cotisations ou une régularisation URSSAF des travailleurs indépendants. N'invente rien.",
                       'Format : {"calls": [{"kind": "provisionnel|regularisation", "year": 2026, "due_date": "AAAA-MM-JJ", "amount": 0}]}') if ctype == "application/pdf" else None
    calls = [{"kind": c.get("kind") if c.get("kind") in ("provisionnel", "regularisation") else "provisionnel", "year": int(num(c.get("year")) or sc.today()[:4]), "due_date": str(c.get("due_date") or "")[:10], "amount": num(c.get("amount")), "file_id": fid}
             for c in (out or {}).get("calls") or [] if isinstance(c, dict)][:24]
    return {"file_id": fid, "calls": calls, "message": "" if out else "Lecture IA indisponible : saisissez les échéances à la main, le document est conservé."}


@router.get("/social/managers/simulate")
async def simulate_mgr(budget: float, ctx: Ctx = Depends(R)):
    """Même enveloppe pour la société : tout en rémunération, ou tout en dividendes (après IS)."""
    import routes_tax as rt
    p = await sc.params_at(ctx.org_id, sc.today())
    k, flat = p["tns_rate"] / 100, float(p.get("flat_tax_pct", 30)) / 100
    pay = budget / (1 + k)
    isv = rt.compute_is(budget, True, await rt.rate(ctx.org_id, "is", sc.today()))["is_total"]
    return {"budget": r2(budget), "remuneration": {"paid": r2(pay), "contributions": r2(budget - pay), "is_saved": 0, "net_before_income_tax": r2(pay)},
            "dividends": {"is": r2(isv), "distributable": r2(budget - isv), "flat_tax": r2((budget - isv) * flat), "net": r2((budget - isv) * (1 - flat))},
            "note": "Comparaison indicative. Pour un gérant majoritaire, la part des dividendes dépassant 10 % du capital et des comptes courants supporte des cotisations sociales ; la rémunération ouvre des droits (retraite, prévoyance), pas les dividendes. " + sc.NOTE}


# ---------- Échéances sociales ----------
async def dues_list(org_id: str, d: Optional[dict] = None) -> list:
    d = d or await sc.load(org_id)
    cur, p, out = sc.today()[:7], d["params"], []
    f = sc.forecast(d, sc.ym_add(cur, -3), 15)
    paid = {x["key"]: x async for x in db.social_dues.find({"org_id": org_id}, {"_id": 0})}
    size = {"monthly": 1, "quarterly": 3, "yearly": 12}

    def due(key, body, label, day, amount, account=""):
        x = paid.get(key) or {}
        late = day < sc.today() and not x.get("paid_at")
        gap = r2(x["paid_amount"] - amount) if x.get("paid_at") and x.get("paid_amount") is not None else None
        out.append({"key": key, "body": body, "label": label, "due_date": day, "amount": r2(amount), "account": account, "paid_at": x.get("paid_at"), "paid_amount": x.get("paid_amount"), "gap": gap,
                    "alert": "Prélèvement non pointé après l'échéance" if late and amount > 0 else f"Montant payé différent du prévu ({gap:+.2f} €)" if gap is not None and abs(gap) > 1 else ""})
    for b in p["bodies"]:
        n = size.get(b.get("periodicity"), 1)
        groups = {}
        for r in f["rows"]:
            k = (int(r["month"][:4]) * 12 + int(r["month"][5:7]) - 1) // n
            groups.setdefault(k, []).append(r)
        for k, rs in groups.items():
            last = f"{(k * n + n - 1) // 12}-{(k * n + n - 1) % 12 + 1:02d}"
            amt = sum(r["pas"] if b["key"] == "dgfip_pas" else r["contrib"] * (b.get("share_pct") or 0) / 100 for r in rs)
            if amt > 0:
                due(f"{b['key']}-{last}", b["name"], f"{b['name']} — {rs[0]['month']}" + (f" → {last}" if n > 1 else "") + (" (réel)" if all(r["real"] for r in rs) else " (prévu)"), sc.day_in(sc.ym_add(last, 1), int(b.get("day") or p["dues_day"])), amt, b.get("account", ""))
    for m in d["managers"]:
        for c in m.get("calls") or []:
            due(f"tns-{c['id']}", "URSSAF indépendants", f"{m['name']} — {c['kind']} {c['year']}", c["due_date"], c["amount"])
    return sorted(out, key=lambda x: x["due_date"])


@router.get("/social/dues")
async def dues(ctx: Ctx = Depends(R)):
    rows = await dues_list(ctx.org_id)
    return {"rows": rows, "can_manage": ctx.can("social:manage"), "bank": {"connected": False, "note": "Rapprochement bancaire automatique : disponible avec Pennylane. En attendant, pointez chaque paiement à la main."},
            "note": "Répartition par organisme estimée d'après les parts paramétrées. " + sc.NOTE}


class PaidIn(BaseModel):
    paid_at: str = Field("", pattern=DO)
    paid_amount: Optional[float] = Field(None, ge=0, le=1e7)


@router.put("/social/dues/{key}")
async def put_due(key: str, body: PaidIn, ctx: Ctx = Depends(W)):
    """Pointage manuel : aucun paiement n'est émis par l'application."""
    if key not in {x["key"] for x in await dues_list(ctx.org_id)}:
        raise HTTPException(404, "Échéance introuvable")
    await db.social_dues.update_one(ctx.q({"key": key}), {"$set": {**body.model_dump(), "updated_at": now_iso(), "by": ctx.member.get("name", "")}}, upsert=True)
    return await dues(ctx)


# ---------- Prévisionnel, budget ----------
@router.get("/social/forecast")
async def forecast(months: int = 12, start: str = "", ctx: Ctx = Depends(R)):
    d = await sc.load(ctx.org_id)
    f = sc.forecast(d, start if len(start) == 7 else sc.today()[:7], 36 if months > 12 else 12)
    return {**f, "note": "Le réel (bulletins validés) remplace le prévu. Nets payés " + ("le dernier jour du mois" if not d["params"]["pay_day"] else f"le {d['params']['pay_day']}") + f", cotisations le {d['params']['dues_day']} du mois suivant. " + sc.NOTE,
            "leave_provision": r2(sum(sc.leave_provision(d, t) for t in staffed(d))), "feeds": ["Prévisionnel 3 ans et dossier banquier (ligne « Personnel » et ligne « Gérants »)", "Plan de trésorerie", "Résultat estimé de l'onglet Impôts & fiscalité", "Marge des événements (CDDU et primes)"]}


class BudgetIn(BaseModel):
    monthly: List[float] = Field(min_length=12, max_length=12)


@router.get("/social/budget/{year}")
async def budget(year: int, ctx: Ctx = Depends(R)):
    d = await sc.load(ctx.org_id)
    b = (await db.headcount_budgets.find_one(ctx.q({"year": year}), {"_id": 0}) or {}).get("monthly") or [0] * 12
    f, rows = sc.forecast(d, f"{year}-01", 12), []
    for i, r in enumerate(f["rows"]):
        ym, why = r["month"], []
        ot = sum(sc.month_hours(d, t, ym)["overtime_amount"] for t in staffed(d)) if r["real"] else 0
        pr = sum(v["amount"] for v in d["variables"] if v["period"] == ym and v["kind"] in sc.GROSS_KINDS)
        ab = sum(a["days"] for a in d["absences"] if a["status"] == "approved" and a["type"] != "cp" and a["start"][:7] == ym)
        hi = [d["team"][c["team_id"]]["name"] for c in d["contracts"] if c["start"][:7] == ym and c.get("version", 1) == 1 and c["team_id"] in d["team"]]
        why += [f"heures sup. {ot:,.0f} €".replace(",", " ")] if ot else []
        why += [f"primes {pr:,.0f} €".replace(",", " ")] if pr else []
        why += [f"{ab:g} j d'absence"] if ab else []
        why += ["embauche : " + ", ".join(hi)] if hi else []
        total = r["cost"] + r["cddu"]
        rows.append({"month": ym, "budget": r2(b[i]), "actual": r2(total), "real": r["real"], "gap": r2(total - b[i]), "explain": " · ".join(why)})
    return {"year": year, "rows": rows, "total_budget": r2(sum(b)), "total_actual": r2(sum(r["actual"] for r in rows)), "can_manage": ctx.can("social:manage")}


@router.put("/social/budget/{year}")
async def put_budget(year: int, body: BudgetIn, ctx: Ctx = Depends(W)):
    await db.headcount_budgets.update_one(ctx.q({"year": year}), {"$set": {"monthly": body.monthly, "updated_at": now_iso()}, "$setOnInsert": {"id": new_id()}}, upsert=True)
    return await budget(year, ctx)


# ---------- Scénarios : comparés, jamais appliqués automatiquement ----------
class ScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["hire", "cdd_to_cdi", "raise_pct", "departure", "replace_cddu", "manager_raise"]
    date: str = Field(pattern=D)
    team_id: str = ""
    contract_type: Literal["cdi", "cdd"] = "cdi"
    gross: float = Field(0, ge=0, le=1e6)
    pct: float = Field(0, ge=-50, le=200)
    missions_per_year: float = Field(0, ge=0, le=1000)
    cost_per_mission: float = Field(0, ge=0, le=1e5)
    job: str = Field("", max_length=120)


def apply_scenario(d: dict, a: dict) -> dict:
    d = copy.deepcopy(d)
    k, day = a["kind"], a["date"]
    if k in ("hire", "replace_cddu"):
        d["team"]["__sc"] = {"id": "__sc", "name": "Scénario : " + (a.get("job") or "embauche")}
        d["contracts"].append({"id": "__sc", "team_id": "__sc", "type": a["contract_type"], "start": day, "end": "", "pay_basis": "monthly", "base_pay": a["gross"], "version": 1, "effective_from": day})
    for c in d["contracts"]:
        mine = not a["team_id"] or c["team_id"] == a["team_id"]
        if k == "cdd_to_cdi" and c["team_id"] == a["team_id"] and c["type"] == "cdd":
            c.update(type="cdi", end="")
        if k == "departure" and c["team_id"] == a["team_id"] and (not c.get("end") or c["end"] > day):
            c["end"] = day
        if k == "raise_pct" and mine and c["type"] != "cddu" and c is sc.current_contract(d, c["team_id"]):
            d["revisions"].append({"team_id": c["team_id"], "effective_date": day, "new_base": c["base_pay"] * (1 + a["pct"] / 100), "status": "planned"})
    if k == "manager_raise":
        for m in d["managers"]:
            new = []
            for x in m.get("pay") or []:
                if not x.get("end") or x["end"] >= day:
                    new.append({**x, "start": max(day, x["start"]), "amount": x["amount"] * (1 + a["pct"] / 100)})
                    x["end"] = (date.fromisoformat(max(day, x["start"])).replace(day=1) - timedelta(days=1)).isoformat()
            m["pay"] = [x for x in m["pay"] if x["end"] >= x["start"]] + new
    return d


async def run_scenario(ctx: Ctx, a: dict) -> dict:
    import routes_forecast as fc
    import routes_tax as rt
    d = await sc.load(ctx.org_id)
    tx = await rt.build(ctx.org_id, sc.today())
    start = tx["fiscal_year"]["start"][:7] if a["date"] <= tx["fiscal_year"]["end"] else a["date"][:7]
    base, after = sc.forecast(d, start, 12), sc.forecast(apply_scenario(d, a), start, 12)
    tot = lambda f: f["staff_total"] + f["managers_total"]  # noqa: E731
    saved = r2(a["missions_per_year"] * a["cost_per_mission"] * d["params"]["coef"]["cddu"]) if a["kind"] == "replace_cddu" else 0
    delta = r2(tot(after) - tot(base) - saved)
    isp = await rt.rate(ctx.org_id, "is", tx["fiscal_year"]["end"])
    is0, is1 = tx["estimate"]["is_total"], rt.compute_is(tx["estimate"]["taxable_result"] - delta, tx["eligible"], isp, tx["inputs"]["credits"])["is_total"] if tx["regime"] == "is" else 0
    v = await db.forecast_versions.find_one(ctx.q({"deleted_at": None}), {"_id": 0}, sort=[("created_at", -1)])
    cash0, be0, rate = [0.0] * 12, None, None
    if v:
        res = fc.run(await fc.with_social(ctx, v))
        cash0 = next(r[1:] for r in next(t for t in res["tables"] if t["key"] == "cash")["rows"] if r[0] == "Trésorerie fin de mois")
        be0, rate = next(x["value"] for x in res["kpis"] if x["key"] == "breakeven"), next(x["value"] for x in res["kpis"] if x["key"] == "rate")
    cum, cash1 = 0.0, []
    for i, m in enumerate(base["months"]):
        cum += after["cash"][m] - base["cash"][m] - saved / 12
        cash1.append(r2(cash0[i] - cum))
    return {"period": f"{base['months'][0]} → {base['months'][-1]}", "cost_year_without": r2(tot(base)), "cost_year_with": r2(tot(base) + delta), "delta_cost": delta, "cddu_saved": saved, "result_effect": r2(-delta),
            "is_without": r2(is0), "is_with": r2(is1), "is_effect": r2(is1 - is0), "cash_low_without": r2(min(cash0)), "cash_low_with": min(cash1), "cash_source": f"prévisionnel « {v['name']} »" if v else "aucun prévisionnel : variation de trésorerie seule",
            "breakeven_without": be0, "breakeven_with": r2(be0 + delta / (rate / 100)) if be0 and rate else None, "note": sc.NOTE}


@router.get("/social/scenarios")
async def scenarios(ctx: Ctx = Depends(R)):
    rows = await ctx.list("social_scenarios", sort=[("created_at", -1)])
    return {"rows": rows, "can_manage": ctx.can("social:manage"), "employees": [{"team_id": t["id"], "name": t["name"]} for t in await ctx.list("team", sort=[("name", 1)])]}


@router.post("/social/scenarios")
async def add_scenario(body: ScenarioIn, ctx: Ctx = Depends(W)):
    a = body.model_dump()
    if body.team_id:
        await ctx.get("team", body.team_id)
    elif body.kind in ("cdd_to_cdi", "departure"):
        raise HTTPException(400, "Choisissez le salarié concerné")
    await ctx.insert("social_scenarios", {"name": body.name, "assumptions": a, "results": await run_scenario(ctx, a), "created_by": ctx.member.get("name", ""), "applied_at": None})
    return await scenarios(ctx)


@router.post("/social/scenarios/{sid}/apply")
async def apply(sid: str, ctx: Ctx = Depends(W)):
    """Application explicite : seuls l'embauche et l'augmentation créent des données (fiche en attente + contrat, ou révisions planifiées)."""
    import routes_social as rs
    s = await ctx.get("social_scenarios", sid, {"applied_at": None})
    a, d = s["assumptions"], await sc.load(ctx.org_id)
    if a["kind"] == "hire":
        tid = await rs.new_member(ctx, a.get("job") or s["name"], "", a.get("job", ""), a["contract_type"])
        if a["contract_type"] == "cdi":
            await rs.add_contract(rs.ContractIn(team_id=tid, type="cdi", start=a["date"], job=a.get("job", ""), base_pay=a["gross"]), ctx)
    elif a["kind"] == "raise_pct":
        for tid in ([a["team_id"]] if a["team_id"] else staffed(d)):
            c = sc.current_contract(d, tid)
            if c and c["type"] != "cddu":
                await ctx.insert("pay_revisions", {"team_id": tid, "effective_date": a["date"], "old_base": c["base_pay"], "new_base": r2(c["base_pay"] * (1 + a["pct"] / 100)), "reason": s["name"], "status": "planned"})
    else:
        raise HTTPException(400, "Ce scénario s'applique à la main (contrat, avenant ou fiche gérant) : il reste une simulation")
    await ctx.update("social_scenarios", sid, {"applied_at": now_iso(), "applied_by": ctx.member.get("name", "")})
    await audit(ctx.org_id, ctx.member, "social_scenario_applied", s["name"])
    return await scenarios(ctx)


@router.delete("/social/scenarios/{sid}")
async def del_scenario(sid: str, ctx: Ctx = Depends(W)):
    await ctx.delete("social_scenarios", sid)
    return await scenarios(ctx)


# ---------- Tableau de bord, badges, coûts par événement ----------
async def badge_items(ctx: Ctx, d: dict) -> list:
    t0, cur, out = sc.today(), sc.today()[:7], []
    prev = sc.ym_add(cur, -1)
    has = lambda ym: any(sc.contract_at(d, t, ym) or sc.contract_at(d, t, ym, True) for t in d["team"])  # noqa: E731
    if t0[8:] > "25" and has(cur) and (await period_doc(ctx, cur))["status"] == "open":
        out.append({"kind": "variables", "label": f"Variables de {cur} non clôturées", "level": "warn"})
    if t0[8:] > "10" and has(prev) and not any(l["period"] == prev for l in d["lines"]):
        out.append({"kind": "payslips", "label": f"Bulletins de {prev} non importés", "level": "warn"})
    out += [a for a in sc.alerts(d) if a["kind"] in ("cdd_end", "trial_end", "dpae", "medical_next", "prof_review_next")]
    n = sum(1 for a in d["absences"] if a["status"] == "requested")
    out += [{"kind": "leave", "label": f"{n} demande(s) de congé en attente", "level": "warn"}] if n else []
    lim = (date.fromisoformat(t0) + timedelta(days=7)).isoformat()
    out += [{"kind": "due", "label": f"Échéance {x['label']} : {x['amount']:,.0f} €".replace(",", " "), "date": x["due_date"], "level": "warn"} for x in await dues_list(ctx.org_id, d) if not x["paid_at"] and t0 <= x["due_date"] <= lim]
    return out


async def badge_count(ctx: Ctx) -> int:
    return len(await badge_items(ctx, await sc.load(ctx.org_id)))


@router.get("/social/dashboard")
async def dashboard(ctx: Ctx = Depends(R)):
    d = await sc.load(ctx.org_id)
    cur, y, p = sc.today()[:7], sc.today()[:4], d["params"]
    active = [(t, c) for t in staffed(d) if (c := sc.contract_at(d, t, cur) or sc.contract_at(d, t, cur, True))]
    by = {}
    for _, c in active:
        x = by.setdefault(c["type"], {"type": sc.TYPES[c["type"]], "count": 0, "fte": 0.0})
        x["count"], x["fte"] = x["count"] + 1, r2(x["fte"] + (0 if c["type"] == "cddu" else (c.get("weekly_hours") or p["weekly_hours"]) / p["weekly_hours"]))
    f = sc.forecast(d, f"{y}-01", 12)
    ytd = [r for r in f["rows"] if r["month"] <= cur]
    row = next(r for r in f["rows"] if r["month"] == cur)
    ca = sum([q.get("total_ht") or 0 async for q in db.quotes.find(ctx.q({"status": "accepte", "active": {"$ne": False}, "event_date": {"$gte": f"{y}-01-01", "$lte": cur + "-31"}}), {"_id": 0, "total_ht": 1})])
    staff_ytd, mgr_ytd = sum(r["cost"] + r["cddu"] for r in ytd), sum(r["mgr_pay"] + r["mgr_charge"] for r in ytd)
    n1 = sum(l.get("employer_cost_total") or 0 for l in d["lines"] if f"{int(y) - 1}-01" <= l["period"] <= f"{int(y) - 1}{cur[4:]}")
    pct = lambda a: round(a / ca * 100, 1) if ca else None  # noqa: E731
    absd = sum(a["days"] for a in d["absences"] if a["status"] == "approved" and a["type"] not in ("cp", "rtt") and a["start"][:7] == cur)
    by_ev, sid_of = {}, {}
    for m in d["missions"]:
        if m.get("event_id") and m["date"][:4] == y:
            by_ev[m["event_id"]] = by_ev.get(m["event_id"], 0) + (m.get("total_ht") or 0) * p["coef"]["cddu"]
    titles = {e["id"]: e.get("title", "") async for e in db.events.find(ctx.q({"id": {"$in": list(by_ev)}}), {"_id": 0, "id": 1, "title": 1})}
    ent = [c for c in d["contracts"] if c.get("version", 1) == 1 and c["start"][:4] == y]
    return {"headcount": {"total": len(active), "fte": r2(sum(x["fte"] for x in by.values())), "by_type": list(by.values()), "entries": len(ent), "exits": len({c["team_id"] for c in d["contracts"] if (c.get("end") or "")[:4] == y and c["end"] < sc.today()})},
            "payroll": {"month": r2(row["cost"] + row["cddu"]), "month_real": row["real"], "ytd": r2(staff_ytd), "ytd_n1_real": r2(n1), "managers_ytd": r2(mgr_ytd), "ca_ytd": r2(ca), "ratio_pct": pct(staff_ytd), "ratio_with_managers_pct": pct(staff_ytd + mgr_ytd)},
            "overtime": {"month_hours": r2(sum(sc.month_hours(d, t, cur)["overtime_hours"] for t, _ in active)), "contingent": [{"name": d["team"][t]["name"], "used": u, "max": p["contingent"]} for t, c in active if c["type"] != "cddu" and (u := sc.contingent_used(d, t, y))]},
            "leave": [{"name": d["team"][t]["name"], "to_take_before": b["period"][-10:], "n1_remaining": b["n1_remaining"], "remaining": b["remaining"]} for t, _ in active if (b := sc.leave_balance(d, t))],
            "absenteeism_pct": round(absd / (len(active) * 21.67) * 100, 1) if active else 0, "cddu_by_event": sorted(({"event_id": k, "title": titles.get(k, ""), "cost": r2(v)} for k, v in by_ev.items()), key=lambda x: -x["cost"])[:15],
            "alerts": sc.alerts(d), "badges": await badge_items(ctx, d), "dues": [x for x in await dues_list(ctx.org_id, d) if not x["paid_at"] and x["due_date"] >= sc.today()][:8], "note": sc.NOTE, "can_manage": ctx.can("social:manage")}


async def event_costs(org_id: str, eid: str) -> list:
    """Charges sociales des intermittents (au-delà du brut déjà engagé par la mission) et primes chargées rattachées à l'événement : lignes calculées, jamais stockées."""
    d, out = await sc.load(org_id), []
    by_staff = {f.get("staff_id"): tid for tid, f in d["files"].items() if f.get("staff_id")}
    ts = {t["mission_id"]: t for t in d["timesheets"]}
    mk = lambda label, planned, real: {"id": "social", "kind": "expense", "category": "staff", "label": label, "amount_ht": r2(planned), "actual_ht": r2(real) if real is not None else None, "status": "facture" if real is not None else "confirme", "source": "social", "vat": 0, "due_date": "", "history": []}  # noqa: E731
    for m in d["missions"]:
        if m.get("event_id") == eid:
            k = (sc.coef_of(d, by_staff[m["provider_id"]], "cddu")[0] if m["provider_id"] in by_staff else d["params"]["coef"]["cddu"]) - 1
            t = ts.get(m["id"])
            out.append(mk(f"Charges sociales — {m.get('provider_name', '')} (CDDU)", (m.get("total_ht") or 0) * k, (t.get("amount_base", 0) + t.get("amount_overtime", 0)) * k if t else None))
    for v in d["variables"]:
        if v.get("event_id") == eid and v["kind"] in sc.GROSS_KINDS:
            c = sc.current_contract(d, v["team_id"])
            cost = v["amount"] * sc.coef_of(d, v["team_id"], (c or {}).get("type") or "cdi")[0]
            closed = await db.pay_periods.find_one({"org_id": org_id, "period": v["period"], "status": {"$ne": "open"}})
            out.append(mk(f"{sc.VAR_KINDS[v['kind']]} — {(d['team'].get(v['team_id']) or {}).get('name', '')} (chargée)", cost, cost if closed else None))
    return out
