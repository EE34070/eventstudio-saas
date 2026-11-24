"""Finance : estimation de l'IS, acomptes, solde, TVA prévisionnelle, CFE, calendrier fiscal et provision. Estimations seulement : aucune écriture comptable, rien n'est déclaré ni payé par l'app."""
from datetime import date, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import Ctx, db, now_iso
from routes_statements import NOTE, R, W, TaxSettings, ensure_rates

router = APIRouter(prefix="/api")
r2 = lambda x: round(float(x or 0) + 1e-9, 2)  # noqa: E731
fr = lambda d: f"{d[8:10]}/{d[5:7]}/{d[:4]}"  # noqa: E731
OPENQ = ["envoye", "vu", "negociation"]
PER = {"monthly": 1, "quarterly": 3, "yearly": 12}


def add_months(d: date, n: int, day: int = 0) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    for dd in (day or d.day, 30, 29, 28):
        try:
            return date(y, m, dd)
        except ValueError:
            continue


def fiscal_year(closing: str, today: str) -> tuple:
    def end_of(y):
        try:
            return date(y, int(closing[:2]), int(closing[3:]))
        except ValueError:
            return date(y, int(closing[:2]), 28)
    e = end_of(int(today[:4]))
    if e.isoformat() < today:
        e = end_of(e.year + 1)
    return (end_of(e.year - 1) + timedelta(days=1)).isoformat(), e.isoformat()


def compute_is(taxable: float, eligible: bool, p: dict, credits: float = 0) -> dict:
    base = max(0.0, taxable)
    low = min(base, p["plafond_taux_reduit"]) if eligible else 0.0
    red, nor = r2(low * p["taux_reduit_pct"] / 100), r2((base - low) * p["taux_normal_pct"] / 100)
    total = max(0.0, r2(red + nor - credits))
    return {"base_reduit": r2(low), "is_reduit": red, "base_normal": r2(base - low), "is_normal": nor, "credits": r2(credits), "is_total": total, "effective_rate": round(total / base * 100, 1) if base else 0.0}


def acompte_dates(end: date) -> list:
    md = (end.month, end.day)
    m = 12 if md >= (11, 20) or md <= (2, 19) else 3 if md <= (5, 19) else 6 if md <= (8, 19) else 9
    last = date(end.year - 1 if m == 12 and end.month <= 2 else end.year, m, 15)
    return [add_months(last, -3 * i, 15).isoformat() for i in (3, 2, 1, 0)]


async def rate(org_id: str, tax: str, day: str) -> dict:
    await ensure_rates(org_id)
    rows = await db.tax_rate_tables.find({"org_id": org_id, "tax": tax, "valid_from": {"$lte": day}}, {"_id": 0}).sort("valid_from", -1).to_list(20)
    return next((r["params"] for r in rows if not r.get("valid_to") or r["valid_to"] >= day), rows[0]["params"] if rows else {})


class Line(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    amount: float = Field(ge=0, le=1e9)
    kind: Literal["produit", "charge", "reintegration", "deduction"]


class Inputs(BaseModel):
    pending_weight_pct: float = Field(0, ge=0, le=100)
    lines: List[Line] = Field(default_factory=list, max_length=40)
    credits: float = Field(0, ge=0, le=1e9)
    use_deficits: bool = True
    deficits: Optional[float] = Field(None, ge=0, le=1e10)
    is_n1: Optional[float] = Field(None, ge=0, le=1e10)
    cfe_amount: float = Field(0, ge=0, le=1e8)


async def build(org_id: str, today: str) -> dict:
    o = {"org_id": org_id}
    st = TaxSettings(**{k: v for k, v in (await db.tax_settings.find_one(o, {"_id": 0}) or {}).items() if k in TaxSettings.model_fields})
    inp = Inputs(**{k: v for k, v in (await db.tax_inputs.find_one(o, {"_id": 0}) or {}).items() if k in Inputs.model_fields})
    start, end = fiscal_year(st.closing, today)
    last = await db.fiscal_years.find_one({**o, "status": "locked"}, {"_id": 0, "balances": 0}, sort=[("end", -1)]) or {}
    in_fy = {"$gte": start, "$lte": end}
    # --- résultat comptable estimé (données de l'app + lignes saisies) ---
    quotes = await db.quotes.find({**o, "active": {"$ne": False}, "status": {"$in": ["accepte"] + OPENQ}}, {"_id": 0, "id": 1, "number": 1, "status": 1, "event_date": 1, "total_ht": 1, "total_vat": 1, "total_ttc": 1}).to_list(5000)
    signed = r2(sum(q.get("total_ht") or 0 for q in quotes if q["status"] == "accepte" and start <= (q.get("event_date") or "") <= end))
    pending = r2(sum(q.get("total_ht") or 0 for q in quotes if q["status"] in OPENQ and start <= (q.get("event_date") or "") <= end) * inp.pending_weight_pct / 100)
    subs = [s async for s in db.subscriptions.find({**o, "active": {"$ne": False}}, {"_id": 0})]
    sub_m = lambda s: (s.get("amount") or 0) / PER.get(s.get("period"), 1)  # noqa: E731
    sub_total, personal = r2(sum(sub_m(s) * 12 for s in subs)), [{"label": f"{s['name']} (personnel / non déductible)", "amount": r2(sub_m(s) * 12)} for s in subs if s.get("personal_non_deductible")]
    purchases = [p async for p in db.purchase_invoices.find({**o, "date": {"$gte": add_months(date.fromisoformat(today), -2).isoformat()}}, {"_id": 0, "date": 1, "amount_ht": 1, "vat": 1})]
    bought = r2(sum([p.get("amount_ht") or 0 async for p in db.purchase_invoices.find({**o, "date": in_fy}, {"_id": 0, "amount_ht": 1})]))
    interest = 0.0
    async for l in db.loans.find({**o, "deleted_at": None}, {"_id": 0, "installments": 1}):
        interest += sum((i.get("interest") or 0) + (i.get("insurance") or 0) for i in l.get("installments") or [] if start <= (i.get("contractual_date") or "") <= end)
    man = lambda k: [{"label": l.label, "amount": r2(l.amount)} for l in inp.lines if l.kind == k]  # noqa: E731
    tot = lambda rows: r2(sum(x["amount"] for x in rows))  # noqa: E731
    products = [{"label": "Devis signés (événements de l'exercice)", "amount": signed}] + ([{"label": f"Devis en cours pondérés à {inp.pending_weight_pct:g} %", "amount": pending}] if pending else []) + man("produit")
    charges = [{"label": "Abonnements et charges récurrentes (12 mois)", "amount": sub_total}, {"label": "Factures d'achat de l'exercice", "amount": bought}, {"label": "Intérêts et assurances d'emprunt", "amount": r2(interest)}] + man("charge")
    import social_core as sc
    sf = sc.forecast(await sc.load(org_id), start[:7], 12)
    charges += [{"label": l, "amount": a} for l, a in (("Charges de personnel (Pôle Social : salaires et charges)", sf["staff_total"]), ("Gérants : rémunération et cotisations TNS (Pôle Social)", sf["managers_total"])) if a]
    accounting = r2(tot(products) - tot(charges))
    reint, deduc = personal + man("reintegration"), man("deduction")
    before = r2(accounting + tot(reint) - tot(deduc))
    isp, acp = await rate(org_id, "is", end), await rate(org_id, "is_acomptes", end)
    stock = inp.deficits if inp.deficits is not None else (last.get("deficits_reportables") or 0)
    cap = isp.get("deficit_plafond", 1e6) + max(0.0, before - isp.get("deficit_plafond", 1e6)) * isp.get("deficit_pct_au_dela", 50) / 100
    used = r2(min(stock, max(0.0, before), cap)) if inp.use_deficits else 0.0
    taxable = r2(before - used)
    eligible = st.regime == "is" and st.capital_libere and st.detention_75 and st.ca_sous_seuil
    calc = compute_is(taxable, eligible, isp, inp.credits) if st.regime == "is" else {"is_total": 0.0, "effective_rate": 0.0, "is_reduit": 0.0, "is_normal": 0.0, "base_reduit": 0.0, "base_normal": 0.0, "credits": 0.0}
    is_n1 = inp.is_n1 if inp.is_n1 is not None else (last.get("headings") or {}).get("is") or 0
    # --- échéances ---
    paid = {d["key"]: d async for d in db.tax_dues.find(o, {"_id": 0})}
    dues = []

    def due(key, tax, label, day, amount, detail=""):
        p = paid.get(key) or {}
        amt = r2(p["final_amount"]) if p.get("final_amount") is not None else r2(amount)
        left = (date.fromisoformat(day) - date.fromisoformat(today)).days
        dues.append({"key": key, "tax": tax, "label": label, "due_date": day, "amount": amt, "estimated": r2(amount), "final": p.get("final_amount") is not None, "detail": detail,
                     "status": "paid" if p.get("paid") else "late" if left < 0 and amt > 0 else "due", "alert": "" if p.get("paid") or amt <= 0 or left < 0 else "J-3" if left <= 3 else "J-15" if left <= 15 else ""})
        return dues[-1]
    exempt = is_n1 < acp.get("seuil_dispense", 3000)
    acs = [due(f"is-acompte-{i + 1}-{end}", "IS", f"Acompte d'IS n° {i + 1}", d, 0 if exempt or st.regime != "is" else is_n1 / 4, f"25 % de l'IS de référence ({is_n1:,.0f} €)".replace(",", " ")) for i, d in enumerate(acompte_dates(date.fromisoformat(end)))]
    ac_total, ac_paid = r2(sum(a["amount"] for a in acs)), r2(sum(a["amount"] for a in acs if a["status"] == "paid"))
    solde = r2(calc["is_total"] - ac_total)
    due(f"is-solde-{end}", "IS", "Solde d'IS (relevé 2572)" if solde >= 0 else "Excédent d'IS à se faire rembourser", add_months(date.fromisoformat(end), 4, 15).isoformat(), max(0.0, solde), f"IS estimé {calc['is_total']:,.0f} € − acomptes {ac_total:,.0f} €".replace(",", " "))
    todo = [a for a in acs if a["status"] != "paid" and a["amount"] > 0]
    mod = {"possible": False}
    if todo and calc["is_total"] < ac_total:
        left, sug = max(0.0, r2(calc["is_total"] - ac_paid)), []
        for a in todo:
            x = min(a["amount"], left)
            left = r2(left - x)
            sug.append({"key": a["key"], "label": a["label"], "due_date": a["due_date"], "current": a["amount"], "suggested": r2(x)})
        mod = {"possible": True, "saving": r2(sum(s["current"] - s["suggested"] for s in sug)), "suggested": sug,
               "warning": f"Si l'IS définitif dépasse finalement l'estimation de plus de {acp.get('tolerance_modulation_pct', 10):g} %, une majoration de {acp.get('majoration_pct', 5):g} % et des intérêts de retard s'appliquent sur l'insuffisance d'acompte. {NOTE}"}
    # --- TVA prévisionnelle ---
    tva, t0 = [], date.fromisoformat(today).replace(day=1)
    if st.tva_regime != "franchise":
        col, ded = {}, {}
        put = lambda d, day, v: d.__setitem__(day[:7], d.get(day[:7], 0) + v)  # noqa: E731
        invoiced = {}
        async for inv in db.invoices.find(o, {"_id": 0, "quote_id": 1, "date": 1, "due_date": 1, "total_vat": 1, "total_ttc": 1, "payments": 1, "balance_due": 1, "status": 1}):
            if str(inv.get("status", "")).startswith("annul") or not inv.get("total_ttc"):
                continue
            ratio = (inv.get("total_vat") or 0) / inv["total_ttc"]
            invoiced[inv.get("quote_id")] = invoiced.get(inv.get("quote_id"), 0) + inv["total_ttc"]
            if st.tva_exigibilite == "debits":
                put(col, inv.get("date") or today, inv.get("total_vat") or 0)
                continue
            for p in inv.get("payments") or []:
                put(col, p.get("date") or (p.get("at") or today)[:10], (p.get("amount") or 0) * ratio)
            if (inv.get("balance_due") or 0) > 0:
                put(col, max(inv.get("due_date") or today, today), inv["balance_due"] * ratio)
        for q in quotes:
            rest = (q.get("total_ttc") or 0) - invoiced.get(q["id"], 0)
            if q["status"] == "accepte" and rest > 0.01 and q.get("total_ttc"):
                put(col, max(q.get("event_date") or today, today), rest * (q.get("total_vat") or 0) / q["total_ttc"])
        for p in purchases:
            put(ded, p.get("date") or today, p.get("vat") or 0)
        for i in range(0, 13):
            put(ded, add_months(t0, i, 1).isoformat(), sum(sub_m(s) * (s.get("vat_rate", 20) or 0) / 100 for s in subs))
        step, credit, day_decl = 1 if st.tva_regime == "reel_mensuel" else 3, 0.0, int((await rate(org_id, "tva", today)).get("jour_declaration", 20))
        first = add_months(t0, -1, 1)
        first = first.replace(month=(first.month - 1) // step * step + 1)
        for i in range(0, 14, step):
            ps = add_months(first, i, 1)
            months = [add_months(ps, k, 1).isoformat()[:7] for k in range(step)]
            c, dd = r2(sum(col.get(m, 0) for m in months)), r2(sum(ded.get(m, 0) for m in months))
            net = r2(c - dd - credit)
            pe = add_months(ps, step, 1) - timedelta(days=1)
            row = {"period": months[0] if step == 1 else f"{months[0]} → {months[-1]}", "collected": c, "deductible": dd, "credit_in": r2(credit), "to_pay": max(0.0, net), "credit_out": max(0.0, -net), "past": pe.isoformat() < t0.isoformat()}
            credit = row["credit_out"]
            row["due_date"] = due(f"tva-{pe.isoformat()}", "TVA", f"TVA {row['period']}", add_months(pe, 1, day_decl).isoformat(), row["to_pay"], f"collectée {c:,.0f} € − déductible {dd:,.0f} €".replace(",", " "))["due_date"]
            tva.append(row)
    # --- CFE ---
    if inp.cfe_amount:
        seuil = (await rate(org_id, "cfe", today)).get("seuil_acompte", 3000)
        for y in (int(today[:4]), int(today[:4]) + 1):
            ac = inp.cfe_amount / 2 if inp.cfe_amount >= seuil else 0
            if ac:
                due(f"cfe-acompte-{y}", "CFE", f"Acompte de CFE {y}", f"{y}-06-15", ac, "50 % de la CFE précédente")
            due(f"cfe-solde-{y}", "CFE", f"Solde de CFE {y}", f"{y}-12-15", inp.cfe_amount - ac, f"d'après le dernier avis ({inp.cfe_amount:,.0f} €)".replace(",", " "))
    lo, hi = (date.fromisoformat(today) - timedelta(days=45)).isoformat(), (date.fromisoformat(today) + timedelta(days=365)).isoformat()
    cal = sorted([d for d in dues if lo <= d["due_date"] <= hi and (d["amount"] > 0 or d["status"] == "paid" or d["tax"] == "IS")], key=lambda d: d["due_date"])
    ahead = [d for d in cal if d["status"] != "paid" and d["due_date"] >= today]
    by_tax = {t: r2(sum(d["amount"] for d in ahead if d["tax"] == t)) for t in ("TVA", "IS", "CFE")}
    d90 = (date.fromisoformat(today) + timedelta(days=90)).isoformat()
    cvae = await rate(org_id, "cvae", today)
    ca_n1 = ((last.get("headings") or {}).get("production_vendue") or 0) + ((last.get("headings") or {}).get("ventes_marchandises") or 0)
    await db.tax_estimates.update_one({**o, "month": today[:7]}, {"$set": {"computed_at": now_iso(), "accounting_result": accounting, "taxable_result": taxable, "is_total": calc["is_total"], "effective_rate": calc["effective_rate"]}}, upsert=True)
    hist = await db.tax_estimates.find(o, {"_id": 0, "org_id": 0}).sort("month", -1).to_list(12)
    return {"today": today, "fiscal_year": {"start": start, "end": end}, "regime": st.regime, "eligible": eligible, "inputs": inp.model_dump(), "note": NOTE,
            "estimate": {"products": products, "charges": charges, "accounting_result": accounting, "reintegrations": reint, "deductions": deduc, "deficits_available": r2(stock), "deficits_used": used, "taxable_result": taxable, **calc,
                         "rates": {"reduit": isp.get("taux_reduit_pct"), "normal": isp.get("taux_normal_pct"), "plafond": isp.get("plafond_taux_reduit")}},
            "reference": {"is_n1": r2(is_n1), "source": "saisi" if inp.is_n1 is not None else f"exercice clos le {fr(last['end'])}" if last else "aucun exercice importé", "exempt": exempt, "seuil_dispense": acp.get("seuil_dispense", 3000)},
            "acomptes": acs, "acomptes_total": ac_total, "acomptes_paid": ac_paid, "solde": solde, "modulation": mod, "tva": tva, "tva_note": {"simplifie": "Régime simplifié : les deux acomptes de juillet et décembre ne sont pas calculés ; estimation trimestrielle indicative."}.get(st.tva_regime, ""),
            "calendar": cal, "provision": {"monthly": r2(sum(by_tax.values()) / 12), "next_90_days": r2(sum(d["amount"] for d in ahead if d["due_date"] <= d90)), "by_tax": by_tax, "total_12_months": r2(sum(by_tax.values()))},
            "cvae": {"concerned": ca_n1 > cvae.get("seuil_paiement_ca", 500000), "must_declare": ca_n1 > cvae.get("seuil_declaration_ca", 152500), "ca_n1": r2(ca_n1)}, "history": list(reversed(hist)),
            "limits": ["Résultat estimé à partir des données de l'application et de vos lignes saisies : le réel Pennylane n'est pas encore branché (salaires, amortissements et autres charges sont à saisir).",
                       "Les factures d'achat liées à un abonnement peuvent être comptées deux fois : vérifiez les charges.", "Acomptes calculés sur le dernier IS connu ; la régularisation du premier acompte sur N-2 n'est pas gérée."]}


@router.get("/finance/tax")
async def get_tax_view(ctx: Ctx = Depends(R)):
    return {**await build(ctx.org_id, now_iso()[:10]), "can_manage": ctx.can("pilot:manage")}


@router.put("/finance/tax/inputs")
async def put_inputs(body: Inputs, ctx: Ctx = Depends(W)):
    await db.tax_inputs.update_one({"org_id": ctx.org_id}, {"$set": {**body.model_dump(), "updated_at": now_iso(), "updated_by": ctx.member.get("name", "")}}, upsert=True)
    return await get_tax_view(ctx)


class DueIn(BaseModel):
    paid: bool = False
    final_amount: Optional[float] = Field(None, ge=0, le=1e9)


@router.put("/finance/tax/dues/{key}")
async def put_due(key: str, body: DueIn, ctx: Ctx = Depends(W)):
    """Pointage manuel : aucun paiement n'est émis par l'application."""
    if key not in {d["key"] for d in (await build(ctx.org_id, now_iso()[:10]))["calendar"]} and not key.startswith(("is-", "tva-", "cfe-")):
        raise HTTPException(404, "Échéance introuvable")
    await db.tax_dues.update_one({"org_id": ctx.org_id, "key": key[:60]}, {"$set": {**body.model_dump(), "updated_at": now_iso(), "by": ctx.member.get("name", "")}}, upsert=True)
    return await get_tax_view(ctx)
