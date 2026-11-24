"""Prévisionnel financier sur 3 ans : versions, hypothèses, compte de résultat, trésorerie, plan de financement, bilan indicatif, export banquier."""
import copy
import math
from datetime import date, timedelta
from typing import Any, Dict, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import routes_finance as fin
import routes_finance_reports as rp
from core import Ctx, audit, db, now_iso

router = APIRouter(prefix="/api")
R, W = fin.R, fin.W
N = 36
BLANK = {"activities": [], "staff": [], "raise_pct": 0, "fixed": [], "indexation_pct": 0, "investments": [], "loans": [], "contributions": [], "dividends": [],
         "tax": {"is_reduced_rate": 15, "is_reduced_cap": 42500, "is_rate": 25, "cfe_yearly": 0},
         "delays": {"deposit_pct": 30, "signature_to_event_months": 3, "balance_delay_months": 0, "supplier_delay_months": 1, "charges_vat_pct": 20}, "opening_cash": 0}
SECTIONS = {"pnl": "Compte de résultat 3 ans", "pnl_monthly": "Compte de résultat mensuel (année 1)", "cash": "Plan de trésorerie 12 mois", "financing": "Plan de financement", "balance": "Bilan simplifié",
            "invest": "Investissements et financements", "hypotheses": "Hypothèses"}
col, kpi, r2 = rp.col, rp.kpi, fin.r2


def compute(v: dict, sens: dict | None = None) -> dict:
    a, y0, s = {**copy.deepcopy(BLANK), **(v.get("assumptions") or {})}, v["start_year"], sens or {}
    tax, dl = {**BLANK["tax"], **(a.get("tax") or {})}, {**BLANK["delays"], **(a.get("delays") or {})}
    ek, bk, vp = 1 + s.get("events_pct", 0) / 100, 1 + s.get("basket_pct", 0) / 100, s.get("var_pts", 0)
    idx = lambda ym: (int(ym[:4]) - y0) * 12 + int(ym[5:7]) - 1 if ym else None  # noqa: E731
    Z = lambda: [0.0] * N  # noqa: E731
    Y = lambda arr: [sum(arr[i * 12:(i + 1) * 12]) for i in range(3)]  # noqa: E731
    on = lambda rows: [r for r in rows or [] if r.get("enabled", True)]  # noqa: E731
    ca, var, vat_col, events, by_act = Z(), Z(), Z(), Z(), {}
    for act in on(a["activities"]):
        season = act.get("seasonality") if len(act.get("seasonality") or []) == 12 and sum(act["seasonality"]) else [1] * 12
        g2, g3, launch, row = 1 + (act.get("growth_y2_pct") or 0) / 100, 1 + (act.get("growth_y3_pct") or 0) / 100, idx(act.get("start")) or 0, Z()
        for m in range(max(0, launch), N):
            n = (act.get("events_per_year") or 0) * ek * (1, g2, g2 * g3)[m // 12] * season[m % 12] / sum(season)
            c = n * (act.get("basket_ht") or 0) * bk
            row[m], events[m], ca[m] = c, events[m] + n, ca[m] + c
            var[m] += c * max(0, (act.get("variable_cost_pct") or 0) + vp) / 100
            vat_col[m] += c * (act.get("vat_pct", 20) or 0) / 100
        by_act[act.get("name") or "Activité"] = row

    def recurring(rows, pct):
        out = Z()
        for f in on(rows):
            end = idx(f.get("end"))
            for m in range(max(0, idx(f.get("start")) or 0), N if end is None else min(N, end + 1)):
                out[m] += (f.get("monthly") or 0) * (1 + (pct or 0) / 100) ** (m // 12)
        return out
    fixed, staff, cfe = recurring(a["fixed"], a.get("indexation_pct")), recurring(a["staff"], a.get("raise_pct")), [(tax["cfe_yearly"] or 0) / 12] * N
    so, mgr = v.get("_social"), Z()
    if so:
        staff, mgr = so["staff"], so["managers"]
    amort, inv, inv_vat = Z(), Z(), Z()
    for i in on(a["investments"]):
        k, n = idx(i.get("date")), max(1, int((i.get("amort_years") or 5) * 12))
        if k is not None and 0 <= k < N:
            inv[k] += i.get("amount_ht") or 0
            inv_vat[k] += (i.get("amount_ht") or 0) * (i.get("vat_pct", 20) or 0) / 100
            for m in range(k, min(N, k + n)):
                amort[m] += (i.get("amount_ht") or 0) / n
    interest, principal, loan_in, debt0, payments = Z(), Z(), Z(), 0.0, []
    for l in on(a["loans"]):
        k, r, n, d, bal = idx(l.get("date")), (l.get("rate_pct") or 0) / 1200, max(1, int(l.get("months") or 12)), int(l.get("deferral_months") or 0), l.get("amount") or 0
        if k is None:
            continue
        pay, pre = (bal * r / (1 - (1 + r) ** -n) if r else bal / n), bal
        payments.append([l.get("label", "Prêt"), l.get("amount") or 0, l.get("rate_pct") or 0, n, r2(pay)])
        if 0 <= k < N:
            loan_in[k] += bal
        for j in range(1, d + n + 1):
            m, it = k + j, bal * r
            pr = 0 if j <= d else pay - it
            bal -= pr
            if m < 0:
                pre = bal
            elif m < N:
                interest[m] += it
                principal[m] += pr
        debt0 += pre if k < 0 else 0
    equity_in, cc_in, div = Z(), Z(), Z()
    for c in on(a["contributions"]):
        k = idx(c.get("date"))
        if k is not None and 0 <= k < N:
            (cc_in if c.get("kind") == "compte_courant" else equity_in)[k] += c.get("amount") or 0
    for c in on(a["dividends"]):
        k = idx(c.get("date"))
        if k is not None and 0 <= k < N:
            div[k] += c.get("amount") or 0
    margin = [ca[m] - var[m] for m in range(N)]
    ebe = [margin[m] - fixed[m] - cfe[m] - staff[m] - mgr[m] for m in range(N)]
    rex = [ebe[m] - amort[m] for m in range(N)]
    rc = [rex[m] - interest[m] for m in range(N)]
    is_ = Z()
    for y, base in enumerate(Y(rc)):
        is_[y * 12 + 11] = 0 if base <= 0 else min(base, tax["is_reduced_cap"]) * tax["is_reduced_rate"] / 100 + max(0, base - tax["is_reduced_cap"]) * tax["is_rate"] / 100
    net = [rc[m] - is_[m] for m in range(N)]
    cv, flows = dl["charges_vat_pct"] / 100, Z()
    labels = ["Encaissements clients TTC", "Coûts directs TTC", "Charges de structure TTC", "Personnel", "Impôts et taxes", "TVA nette", "IS", "Investissements TTC", "Emprunts reçus", "Remboursements d'emprunts", "Apports et comptes courants", "Dividendes"]
    cf = {k: Z() for k in labels}
    for m in range(N):
        ttc = ca[m] + vat_col[m]
        dep = ttc * dl["deposit_pct"] / 100
        cf[labels[0]][max(0, m - int(dl["signature_to_event_months"]))] += dep
        for k, val, lab in ((m + int(dl["balance_delay_months"]), ttc - dep, labels[0]), (m + int(dl["supplier_delay_months"]), -var[m] * (1 + cv), labels[1]),
                            (m + 1, -(vat_col[m] - (var[m] + fixed[m]) * cv - inv_vat[m]), labels[5]), (m + 4, -is_[m], labels[6])):
            if k < N:
                cf[lab][k] += val
        for lab, val in ((labels[2], -fixed[m] * (1 + cv)), (labels[3], -(so["cash"][m] if so else staff[m])), (labels[4], -cfe[m]), (labels[7], -(inv[m] + inv_vat[m])), (labels[8], loan_in[m]), (labels[9], -(interest[m] + principal[m])),
                         (labels[10], equity_in[m] + cc_in[m]), (labels[11], -div[m])):
            cf[lab][m] += val
    bal, cash = a.get("opening_cash") or 0, []
    for m in range(N):
        flows[m] = sum(cf[k][m] for k in labels)
        bal += flows[m]
        cash.append(bal)
    low = min(range(N), key=lambda m: cash[m])
    months = [f"{y0 + m // 12}-{m % 12 + 1:02d}" for m in range(N)]
    years = [str(y0 + i) for i in range(3)]
    pnl_lines = [(f"CA — {k}", v) for k, v in by_act.items()] + [("Chiffre d'affaires HT", ca), ("Coûts directs", var), ("Marge brute", margin), ("Charges externes", fixed), ("Impôts et taxes", cfe), ("Personnel", staff), *([("Gérants (rémunération et cotisations)", mgr)] if so else []),
                                                                ("EBE", ebe), ("Dotations aux amortissements", amort), ("Résultat d'exploitation", rex), ("Charges financières", interest), ("Résultat courant", rc), ("IS", is_), ("Résultat net", net)]
    bold = [i for i, (l, _) in enumerate(pnl_lines) if l in ("Chiffre d'affaires HT", "Marge brute", "EBE", "Résultat d'exploitation", "Résultat courant", "Résultat net")]
    caf = [n_ + am for n_, am in zip(Y(net), Y(amort))]
    opening = [a.get("opening_cash") or 0, cash[11], cash[23]]
    dcash = [cash[i * 12 + 11] - opening[i] for i in range(3)]
    res = [caf, Y(equity_in), Y(cc_in), Y(loan_in)]
    needs = [Y(inv), Y(principal), Y(div)]
    bfr = [sum(r[i] for r in res) - sum(n_[i] for n_ in needs) - dcash[i] for i in range(3)]
    cum = lambda arr, i: sum(arr[:(i + 1) * 12])  # noqa: E731
    immo = [cum(inv, i) - cum(amort, i) for i in range(3)]
    debts = [debt0 + cum(loan_in, i) - cum(principal, i) + cum(cc_in, i) for i in range(3)]
    assets = [immo[i] + sum(bfr[:i + 1]) + cash[i * 12 + 11] for i in range(3)]
    ca1, var1 = Y(ca)[0], Y(var)[0]
    rate = (ca1 - var1) / ca1 if ca1 else 0
    struct = Y(fixed)[0] + Y(staff)[0] + Y(mgr)[0] + Y(cfe)[0] + Y(amort)[0] + Y(interest)[0]
    be, ev1, cm = (struct / rate if rate > 0 else None), sum(events[:12]), 0.0
    be_month = None
    for m in range(12):
        cm += margin[m]
        if be_month is None and struct and cm >= struct:
            be_month = months[m]
    R_ = lambda rows: [[l] + [r2(x) for x in v] for l, v in rows]  # noqa: E731
    T = lambda key, title, cols, rows, **kw: {"key": key, "title": title, "columns": [col(cols[0])] + [col(c, "eur") for c in cols[1:]], "rows": rows, **kw}  # noqa: E731
    xl = lambda n: [["Total (formule)"] + [f"=SUM({chr(66 + i)}2:{chr(66 + i)}{n + 1})" for i in range(12)]]  # noqa: E731
    return {"kpis": [kpi("ca", f"CA HT {years[0]}", r2(ca1)), kpi("gross", "Marge brute", r2(ca1 - var1)), kpi("ebe", "EBE", r2(Y(ebe)[0]), hint="résultat avant amortissements, frais financiers et IS"), kpi("net", "Résultat net", r2(Y(net)[0])),
                     kpi("low", "Trésorerie minimale", r2(cash[low]), hint=months[low]), kpi("need", "Besoin de financement", r2(max(0, -cash[low]))), kpi("caf", "CAF", r2(caf[0])),
                     kpi("breakeven", "Seuil de rentabilité (CA)", r2(be) if be else None, hint=f"atteint en {be_month}" if be_month else "non atteint sur l'année 1"),
                     kpi("breakeven_events", "Soit en événements", math.ceil(be / (ca1 / ev1)) if be and ev1 else None, "int"), kpi("rate", "Taux de marge brute", round(rate * 100, 1), "pct"),
                     kpi("payroll", "Poids de la masse salariale", round(Y(staff)[0] / ca1 * 100, 1) if ca1 else None, "pct"), kpi("debt_caf", "Dettes financières / CAF", round(debts[0] / caf[0], 2) if caf[0] > 0 else None, "num")],
            "tables": [T("pnl", SECTIONS["pnl"], ["Poste"] + years, R_([(l, Y(v)) for l, v in pnl_lines]), bold=bold),
                       T("pnl_monthly", SECTIONS["pnl_monthly"], ["Poste"] + months[:12], R_([(l, v[:12]) for l, v in pnl_lines]), bold=bold),
                       T("cash", SECTIONS["cash"], ["Flux"] + months[:12], R_([(k, cf[k][:12]) for k in labels] + [("Variation du mois", flows[:12]), ("Trésorerie fin de mois", cash[:12])]), bold=[len(labels) + 1], formulas=xl(len(labels))),
                       T("financing", SECTIONS["financing"], ["Poste"] + years, R_([("Investissements HT", needs[0]), ("Variation du BFR (dont TVA)", bfr), ("Remboursements d'emprunts", needs[1]), ("Dividendes", needs[2]),
                                                                                  ("Total besoins", [needs[0][i] + bfr[i] + needs[1][i] + needs[2][i] for i in range(3)]), ("CAF", caf), ("Apports et subventions", res[1]), ("Comptes courants d'associés", res[2]),
                                                                                  ("Emprunts", res[3]), ("Total ressources", [sum(r[i] for r in res) for i in range(3)]), ("Variation de trésorerie", dcash), ("Trésorerie de fin d'exercice", [cash[i * 12 + 11] for i in range(3)])]), bold=[4, 9, 11]),
                       T("balance", SECTIONS["balance"] + " (indicatif)", ["Poste"] + years, R_([("Immobilisations nettes", immo), ("BFR net", [sum(bfr[:i + 1]) for i in range(3)]), ("Trésorerie", [cash[i * 12 + 11] for i in range(3)]), ("Total actif", assets),
                                                                                              ("Capitaux propres", [assets[i] - debts[i] for i in range(3)]), ("Dettes financières", debts), ("Total passif", assets)]), bold=[3, 6]),
                       {"key": "invest", "title": SECTIONS["invest"], "columns": [col("Prêt"), col("Montant", "eur"), col("Taux", "pct"), col("Durée (mois)", "int"), col("Mensualité", "num")], "rows": payments}],
            "alerts": [f"Trésorerie négative en {months[low]} : besoin de financement de {-cash[low]:,.0f} €".replace(",", " ")] if cash[low] < 0 else [], "monthly_ca": [r2(x) for x in ca[:12]]}


async def prefill(ctx: Ctx, year: int) -> dict:
    d, a = await rp.load(ctx), copy.deepcopy(BLANK)
    since, rate = (date.today() - timedelta(days=365)).isoformat(), rp.margin_rate(d["rows"])
    past = [r for r in d["rows"] if r["signed"] and since <= r["date"] <= d["today"]]
    for act in d["cfg"]["activities"]:
        rs = [r for r in past if r["by_activity"].get(act["id"])]
        if rs:
            season = [sum(1 for r in rs if int(r["month"][5:7]) == m) for m in range(1, 13)]
            a["activities"].append({"name": act["name"], "events_per_year": len(rs), "basket_ht": r2(sum(r["by_activity"][act["id"]] for r in rs) / len(rs)), "variable_cost_pct": round(100 - rate, 1) if rate is not None else 40,
                                    "seasonality": season, "growth_y2_pct": 0, "growth_y3_pct": 0, "vat_pct": 20, "source": "12 derniers mois"})
    per = {"monthly": 1, "quarterly": 1 / 3, "yearly": 1 / 12}
    a["fixed"] = [{"label": s["name"], "monthly": r2(s.get("amount", 0) * per.get(s.get("period"), 1)), "start": "", "end": "", "source": "abonnement"} for s in d["subs"]]
    import routes_contracts as rc
    a["loans"] = [{"label": l["name"], "amount": l.get("capital") or 0, "date": l["first_due_date"][:7], "rate_pct": l.get("rate_pct") or 0, "months": l["months"], "deferral_months": l.get("deferral_months") or 0, "source": "prêt existant"}
                  for l in await ctx.list("loans", {"deleted_at": None}) if l["type"] != "lease"]
    a["investments"] = [{"label": n["label"], "amount_ht": 0, "date": f"{year}-01", "amort_years": 5, "vat_pct": 20, "enabled": False, "source": "à acheter"} for n in await ctx.list("purchase_needs", {"status": {"$nin": ["commande", "recu", "annule"]}}, limit=50)]
    return a


async def with_social(ctx: Ctx, v: dict) -> dict:
    """Charges de personnel alimentées par le Pôle Social (salariés et gérants séparés) ; une version figée garde sa photo."""
    if (v.get("assumptions") or {}).get("staff_source") == "manual":
        return v
    if v["status"] == "frozen":
        return {**v, "_social": v["social_snapshot"]} if v.get("social_snapshot") else v
    import social_core as sc
    f = sc.forecast(await sc.load(ctx.org_id), f"{v['start_year']}-01", N)
    if not (f["staff_total"] or f["managers_total"]):
        return v
    return {**v, "_social": {"staff": [r["cost"] + r["cddu"] for r in f["rows"]], "managers": [r["mgr_pay"] + r["mgr_charge"] for r in f["rows"]], "cash": [f["cash"][m] for m in f["months"]]}}


async def signed_share(ctx: Ctx, v: dict, res: dict) -> dict:
    d = await rp.load(ctx)
    y = str(v["start_year"])
    signed = sum(r["ca"] for r in d["rows"] if r["signed"] and r["date"].startswith(y))
    ca = res["kpis"][0]["value"]
    real = [r2(sum(r["ca"] for r in d["rows"] if r["signed"] and r["month"] == f"{y}-{m:02d}")) for m in range(1, 13)]
    return {"signed_ht": r2(signed), "pct": round(signed / ca * 100, 1) if ca else None, "real_monthly": real, "today": d["today"]}


def follow(v: dict, res: dict, sh: dict) -> dict:
    y, plan, rows, landing = v["start_year"], res["monthly_ca"], [], 0
    for m in range(12):
        past = f"{y}-{m + 1:02d}" < sh["today"][:7]
        landing += sh["real_monthly"][m] if past else max(plan[m], sh["real_monthly"][m])
        rows.append([f"{y}-{m + 1:02d}", plan[m], sh["real_monthly"][m] if past else None, r2(sh["real_monthly"][m] - plan[m]) if past else None])
    return {"key": "follow", "title": f"Suivi {y} : CA signé réel vs version figée — atterrissage {landing:,.0f} €".replace(",", " "), "columns": [col("Mois"), col("Prévu", "eur"), col("Réel signé", "eur"), col("Écart", "eur")], "rows": rows}


class NewIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    start_year: int = Field(ge=2020, le=2100)
    mode: Literal["blank", "data", "duplicate"] = "blank"
    source_id: str = ""


class SaveIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    notes: str = Field("", max_length=2000)
    presentation_text: str = Field("", max_length=6000)
    assumptions: Dict[str, Any]


def run(v: dict, sens: dict | None = None) -> dict:
    try:
        return compute(v, sens)
    except (TypeError, ValueError, KeyError, IndexError, ZeroDivisionError, OverflowError):
        raise HTTPException(400, "Hypothèses invalides : vérifiez les nombres et les dates (format AAAA-MM)")


@router.get("/finance/forecasts")
async def list_versions(ctx: Ctx = Depends(R)):
    rows = await db.forecast_versions.find(ctx.q({"deleted_at": None}), {"_id": 0, "assumptions": 0}).sort("created_at", -1).to_list(200)
    return {"versions": rows, "can_manage": ctx.can("pilot:manage"), "sections": SECTIONS}


@router.get("/finance/forecasts/compare")
async def compare(ids: str, ctx: Ctx = Depends(R)):
    vs = [await ctx.get("forecast_versions", i, {"deleted_at": None}) for i in ids.split(",")[:4] if i]
    rs = [run(await with_social(ctx, v)) for v in vs]
    return {"kpis": [], "alerts": [], "tables": [{"key": "compare", "title": "Comparaison des versions (année 1)", "columns": [col("Indicateur")] + [col(v["name"], "eur") for v in vs],
                                                 "rows": [[k["label"]] + [next(x["value"] for x in r["kpis"] if x["key"] == k["key"]) for r in rs] for k in rs[0]["kpis"] if k["key"] in ("ca", "gross", "ebe", "net", "low", "need", "caf")] if rs else []}]}


@router.post("/finance/forecasts")
async def create(body: NewIn, ctx: Ctx = Depends(W)):
    src = await ctx.get("forecast_versions", body.source_id, {"deleted_at": None}) if body.mode == "duplicate" else None
    a = src["assumptions"] if src else await prefill(ctx, body.start_year) if body.mode == "data" else copy.deepcopy(BLANK)
    return await ctx.insert("forecast_versions", {"name": body.name, "start_year": body.start_year, "horizon_months": N, "granularity": "monthly", "status": "draft", "frozen_at": None, "frozen_by": None,
                                                  "parent_version_id": (src or {}).get("id"), "notes": "", "presentation_text": "", "assumptions": a, "deleted_at": None})


async def _full(ctx: Ctx, v: dict, sens: dict | None = None) -> dict:
    vs = await with_social(ctx, v)
    res = run(vs, sens)
    res["personnel_source"] = "Pôle Social" if vs.get("_social") else "saisie manuelle"
    v = {k: x for k, x in v.items() if k != "social_snapshot"}
    sh = await signed_share(ctx, v, res)
    if v["status"] == "frozen":
        res["tables"].append(follow(v, res, sh))
    return {"version": v, "results": res, "signed_share": sh, "can_manage": ctx.can("pilot:manage")}


@router.get("/finance/forecasts/{vid}")
async def get_version(vid: str, events_pct: float = Query(0, ge=-90, le=200), basket_pct: float = Query(0, ge=-90, le=200), var_pts: float = Query(0, ge=-50, le=50), ctx: Ctx = Depends(R)):
    return await _full(ctx, await ctx.get("forecast_versions", vid, {"deleted_at": None}), {"events_pct": events_pct, "basket_pct": basket_pct, "var_pts": var_pts})


async def _draft(ctx: Ctx, vid: str) -> dict:
    v = await ctx.get("forecast_versions", vid, {"deleted_at": None})
    if v["status"] == "frozen":
        raise HTTPException(409, "Cette version est figée : dupliquez-la pour la modifier")
    return v


@router.put("/finance/forecasts/{vid}")
async def save(vid: str, body: SaveIn, ctx: Ctx = Depends(W)):
    v = await _draft(ctx, vid)
    run(await with_social(ctx, {**v, "assumptions": body.assumptions}))
    return await _full(ctx, await ctx.update("forecast_versions", vid, body.model_dump()))


@router.post("/finance/forecasts/{vid}/freeze")
async def freeze(vid: str, ctx: Ctx = Depends(W)):
    v = await _draft(ctx, vid)
    vs = await with_social(ctx, v)
    res = run(vs)
    v = await ctx.update("forecast_versions", vid, {"social_snapshot": vs.get("_social"), "status": "frozen", "frozen_at": now_iso(), "frozen_by": ctx.member.get("name")})
    kinds = {"Chiffre d'affaires HT": "ca", "Coûts directs": "variable", "Charges externes": "fixed", "Personnel": "staff"}
    for row in next(t for t in res["tables"] if t["key"] == "pnl_monthly")["rows"]:
        for m, amount in enumerate(row[1:], 1):
            if row[0] in kinds:
                await db.budgets.update_one(ctx.q({"year": v["start_year"], "month": m, "line_kind": kinds[row[0]]}), {"$set": {"amount": amount, "source_forecast_version_id": vid, "updated_at": now_iso()}}, upsert=True)
    await audit(ctx.org_id, ctx.member, "forecast_frozen", v["name"], f"Budget {v['start_year']} généré")
    return await _full(ctx, v)


@router.delete("/finance/forecasts/{vid}")
async def remove(vid: str, ctx: Ctx = Depends(W)):
    await _draft(ctx, vid)
    await ctx.update("forecast_versions", vid, {"deleted_at": now_iso()})
    return {"ok": True}


@router.get("/finance/forecasts/{vid}/export")
async def export(vid: str, format: str = "pdf", sections: str = "", ctx: Ctx = Depends(R)):
    v = await ctx.get("forecast_versions", vid, {"deleted_at": None})
    res, want = run(await with_social(ctx, v)), set(filter(None, sections.split(","))) or set(SECTIONS)
    a = v["assumptions"]
    hyp = [[x.get("name"), x.get("events_per_year"), x.get("basket_ht"), x.get("variable_cost_pct")] for x in a.get("activities") or [] if x.get("enabled", True)]
    tables = [t for t in res["tables"] if t["key"] in want]
    if "hypotheses" in want:
        tables.insert(0, {"key": "hypotheses", "title": "Hypothèses d'activité", "columns": [col("Activité"), col("Événements / an", "num"), col("Panier moyen HT", "eur"), col("Coûts variables", "pct")], "rows": hyp})
    org = await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0, "name": 1}) or {}
    return rp.send(f"dossier-banquier-{v['start_year']}", format, f"{org.get('name', '')} — Prévisionnel financier {v['start_year']}-{v['start_year'] + 2}", {**res, "tables": tables},
                   intro=[f"Version : {v['name']}" + (f" (figée le {v['frozen_at'][:10]})" if v.get("frozen_at") else " (brouillon)"), *(v.get("presentation_text") or "").split("\n"), v.get("notes") or ""],
                   footer="Document prévisionnel non audité, établi à partir d'hypothèses de gestion.") if format in ("pdf", "xlsx") else None
