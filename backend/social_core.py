"""Pôle Social : paramètres datés, coût employeur, masse salariale prévisionnelle, congés, heures. Estimations seulement : aucune paie calculée, aucune écriture comptable."""
import calendar
import copy
from datetime import date, timedelta

from core import db, new_id, now_iso

NOTE = "Estimation indicative, à valider avec l'expert-comptable."
r2 = lambda x: round(float(x or 0) + 1e-9, 2)  # noqa: E731
SALARIED = ("cdi", "cdd", "alternance", "stage", "extra")
TYPES = {"cdi": "CDI", "cdd": "CDD", "cddu": "CDDU", "alternance": "Apprentissage", "stage": "Stage", "extra": "Extra"}
GROSS_KINDS = ("prime_evenement", "prime_exceptionnelle", "prime_objectif", "cachet", "avantage_nature")
VAR_KINDS = {"prime_evenement": "Prime d'événement", "prime_exceptionnelle": "Prime exceptionnelle", "prime_objectif": "Prime sur objectif", "cachet": "Cachet", "indemnite_repas": "Indemnité de repas",
             "indemnite_deplacement": "Indemnité de déplacement", "grand_deplacement": "Grand déplacement", "frais": "Frais professionnels remboursés", "avantage_nature": "Avantage en nature", "acompte": "Acompte versé"}
ABS_TYPES = {"cp": "Congés payés", "rtt": "RTT / repos compensateur", "maladie": "Maladie", "accident_travail": "Accident du travail", "maternite": "Maternité / paternité", "familial": "Événement familial",
             "sans_solde": "Congé sans solde", "injustifiee": "Absence injustifiée"}
DEFAULTS = {
    "coef": {"cdi": 1.45, "cdd": 1.5, "cddu": 1.65, "alternance": 1.15, "stage": 1.0, "extra": 1.5}, "net_ratio": 0.78, "weekly_hours": 35,
    "overtime": [{"hours": 8, "pct": 25}, {"hours": None, "pct": 50}], "night_pct": 25, "sunday_pct": 50, "holiday_pct": 100, "contingent": 220,
    "daily_max": 10, "weekly_max": 48, "rest_hours": 11, "leave_days_per_month": 2.5, "leave_mode": "ouvrables", "leave_ref_start": "06-01",
    "minimums": [], "cdd_max_months": 18, "cdd_max_renewals": 2, "pay_day": 0, "dues_day": 15, "variables_avg": "3", "tns_rate": 45, "tns_regul_month": 10,
    "flat_tax_pct": 30, "subrogation": False, "firm_email": "", "variance_alert_pct": 5,
    "bodies": [{"key": "urssaf", "name": "URSSAF", "share_pct": 62, "periodicity": "monthly", "day": 15, "account": ""}, {"key": "audiens", "name": "Audiens (retraite, prévoyance)", "share_pct": 22, "periodicity": "monthly", "day": 15, "account": ""},
               {"key": "conges_spectacles", "name": "Congés Spectacles", "share_pct": 6, "periodicity": "monthly", "day": 15, "account": ""}, {"key": "france_travail", "name": "France Travail (spectacle)", "share_pct": 4, "periodicity": "monthly", "day": 15, "account": ""},
               {"key": "afdas", "name": "Afdas", "share_pct": 2, "periodicity": "yearly", "day": 28, "account": ""}, {"key": "medecine", "name": "Médecine du travail", "share_pct": 1, "periodicity": "yearly", "day": 31, "account": ""},
               {"key": "mutuelle", "name": "Mutuelle", "share_pct": 3, "periodicity": "monthly", "day": 10, "account": ""}, {"key": "dgfip_pas", "name": "DGFiP (prélèvement à la source)", "share_pct": 0, "periodicity": "monthly", "day": 15, "account": ""}]}


def today() -> str:
    return date.today().isoformat()


def ym_add(ym: str, n: int) -> str:
    k = int(ym[:4]) * 12 + int(ym[5:7]) - 1 + n
    return f"{k // 12}-{k % 12 + 1:02d}"


def month_end(ym: str) -> str:
    return f"{ym}-{calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1]:02d}"


def day_in(ym: str, day: int) -> str:
    last = int(month_end(ym)[8:])
    return f"{ym}-{min(day, last) if day else last:02d}"


async def settings_rows(org_id: str) -> list:
    rows = await db.social_settings.find({"org_id": org_id}, {"_id": 0}).sort("valid_from", -1).to_list(100)
    if not rows:
        rows = [{"id": new_id(), "org_id": org_id, "valid_from": "2020-01-01", "params": copy.deepcopy(DEFAULTS), "created_at": now_iso()}]
        await db.social_settings.insert_one(dict(rows[0]))
    return rows


async def params_at(org_id: str, day: str) -> dict:
    rows = await settings_rows(org_id)
    row = next((r for r in rows if r["valid_from"] <= day), rows[-1])
    return {**copy.deepcopy(DEFAULTS), **(row.get("params") or {})}


async def load(org_id: str) -> dict:
    o = {"org_id": org_id}
    L = lambda c, f=None: db[c].find({**o, **(f or {})}, {"_id": 0}).to_list(5000)  # noqa: E731
    return {"org_id": org_id, "team": {t["id"]: t for t in await L("team")}, "files": {f["team_id"]: f for f in await L("employee_files")},
            "contracts": await L("employment_contracts", {"deleted_at": None}), "revisions": await L("pay_revisions"), "variables": await L("pay_variables"),
            "lines": await L("payroll_lines", {"status": "validated"}), "missions": await L("missions", {"employment_status": "intermittent", "status": {"$nin": ["cancelled", "withdrawn", "refused"]}}),
            "timesheets": await L("timesheets", {"status": {"$in": ["validated", "payroll", "invoiced", "paid"]}}), "entries": await L("time_entries"),
            "managers": await L("social_managers", {"deleted_at": None}), "absences": await L("absences"), "params": await params_at(org_id, today())}


def eff(c: dict) -> str:
    return c.get("effective_from") or c["start"]


def contract_at(d: dict, tid: str, ym: str, cddu: bool = False):
    first, last = ym + "-01", month_end(ym)
    ok = [c for c in d["contracts"] if c["team_id"] == tid and (c["type"] == "cddu") == cddu and eff(c) <= last and (not c.get("end") or c["end"] >= first)]
    return max(ok, key=lambda c: (eff(c), c.get("version", 1))) if ok else None


def current_contract(d: dict, tid: str):
    cs = [c for c in d["contracts"] if c["team_id"] == tid]
    live = [c for c in cs if eff(c) <= today()]
    return max(live or cs, key=lambda c: (eff(c), c.get("version", 1))) if cs else None


def monthly_base(c: dict, p: dict, base: float | None = None) -> float:
    b = c.get("base_pay", 0) if base is None else base
    if c.get("pay_basis") == "hourly":
        return b * (c.get("weekly_hours") or p["weekly_hours"]) * 52 / 12
    return b if c.get("pay_basis") == "monthly" else 0.0


def gross_at(d: dict, c: dict, ym: str) -> float:
    base = c.get("base_pay", 0)
    for r in sorted((r for r in d["revisions"] if r["team_id"] == c["team_id"] and r.get("status") != "cancelled"), key=lambda r: r["effective_date"]):
        if eff(c) <= r["effective_date"] and r["effective_date"][:7] <= ym:
            base = r["new_base"]
    first, last = date.fromisoformat(ym + "-01"), date.fromisoformat(month_end(ym))
    a = max(first, date.fromisoformat(c["start"]))
    b = min(last, date.fromisoformat(c["end"])) if c.get("end") else last
    ratio = max(0, (b - a).days + 1) / last.day
    return (monthly_base(c, d["params"], base) + sum(i.get("amount") or 0 for i in c.get("fixed_items") or [])) * ratio


def coef_of(d: dict, tid: str, ctype: str) -> tuple:
    ls = sorted((l for l in d["lines"] if l.get("team_id") == tid and (l.get("gross") or 0) > 0 and l.get("employer_cost_total")), key=lambda l: l["period"])[-3:]
    if ls:
        return round(sum(l["employer_cost_total"] for l in ls) / sum(l["gross"] for l in ls), 3), "réel"
    return float(d["params"]["coef"].get(ctype, 1.5)), "paramètre"


def var_avg(d: dict, tid: str, n: int | None = None) -> float:
    n = int(d["params"].get("variables_avg") or 0) if n is None else n
    if not n:
        return 0.0
    cur = today()[:7]
    return sum(v.get("amount") or 0 for v in d["variables"] if v["team_id"] == tid and v["kind"] in GROSS_KINDS and ym_add(cur, -n) <= v["period"] < cur) / n


def manager_month(d: dict, m: dict, ym: str) -> tuple:
    """(rémunération, cotisations estimées en charge, cotisations décaissées) du mois."""
    pay, mo, rate = 0.0, int(ym[5:7]), d["params"]["tns_rate"] / 100
    for x in m.get("pay") or []:
        if (x.get("start") or "0")[:7] <= ym and (not x.get("end") or x["end"][:7] >= ym):
            pay += x["amount"] if x.get("periodicity", "monthly") == "monthly" else x["amount"] if (x["periodicity"] == "quarterly" and mo % 3 == 0) or (x["periodicity"] == "yearly" and mo == 12) else 0
    extra = sum(c.get("monthly") or 0 for c in m.get("contracts") or [])
    calls = m.get("calls") or []
    cash = extra + sum(c.get("amount") or 0 for c in calls if (c.get("due_date") or "")[:7] == ym)
    if mo == int(d["params"]["tns_regul_month"]):
        y = str(int(ym[:4]) - 1)
        if not any(c.get("kind") == "regularisation" and str(c.get("year")) == y for c in calls):
            cash += manager_regul(d, m, int(y))
    return pay, pay * rate + extra, cash


def manager_year(d: dict, m: dict, y: int) -> float:
    return sum(manager_month({**d, "params": {**d["params"], "tns_regul_month": 0}}, m, f"{y}-{k:02d}")[0] for k in range(1, 13))


def manager_regul(d: dict, m: dict, y: int) -> float:
    called = sum(c.get("amount") or 0 for c in m.get("calls") or [] if c.get("kind", "provisionnel") == "provisionnel" and str(c.get("year") or (c.get("due_date") or "")[:4]) == str(y))
    return r2(manager_year(d, m, y) * d["params"]["tns_rate"] / 100 - called)


def forecast(d: dict, start: str, n: int) -> dict:
    """Masse salariale mois par mois : le réel (bulletins validés) remplace le prévu ; flux de trésorerie datés."""
    p, months, rows, people, flows = d["params"], [ym_add(start, i) for i in range(-1, n)], [], {}, []
    by_staff = {f.get("staff_id"): tid for tid, f in d["files"].items() if f.get("staff_id")}
    for ym in months:
        row = {"month": ym, "gross": 0.0, "cost": 0.0, "net": 0.0, "contrib": 0.0, "pas": 0.0, "cddu": 0.0, "mgr_pay": 0.0, "mgr_charge": 0.0, "mgr_cash": 0.0, "real": False}
        real = {l["team_id"]: l for l in d["lines"] if l["period"] == ym and l.get("team_id")}

        def add(tid, name, ctype, gross, cost, net, pas, src, cddu=False):
            row["gross"] += gross
            row["cddu" if cddu else "cost"] += cost
            row["net"] += net
            row["pas"] += pas
            row["contrib"] += cost - net - pas
            pp = people.setdefault(tid, {"team_id": tid, "name": name, "type": ctype, "gross": {}, "cost": {}, "source": {}})
            pp["gross"][ym], pp["cost"][ym], pp["source"][ym] = r2(pp["gross"].get(ym, 0) + gross), r2(pp["cost"].get(ym, 0) + cost), src
        for tid, l in real.items():
            row["real"] = True
            t = d["team"].get(tid) or {}
            add(tid, t.get("name") or l.get("name", ""), l.get("contract_type") or t.get("contract_type", ""), l.get("gross") or 0, l.get("employer_cost_total") or 0, l.get("net_pay") or 0, l.get("pas") or 0, "réel", l.get("contract_type") == "cddu")
        for tid, t in d["team"].items():
            c = contract_at(d, tid, ym)
            if tid in real or not c:
                continue
            g = gross_at(d, c, ym)
            g += var_avg(d, tid) if g and ym >= today()[:7] else sum(v.get("amount") or 0 for v in d["variables"] if v["team_id"] == tid and v["period"] == ym and v["kind"] in GROSS_KINDS)
            k = coef_of(d, tid, c["type"])[0]
            add(tid, t.get("name", ""), c["type"], g, g * k, g * p["net_ratio"], 0, "prévu")
        for m in d["missions"]:
            tid = by_staff.get(m.get("provider_id"))
            if (m.get("date") or "")[:7] == ym and not (tid and tid in real):
                g = (m.get("total_ht") or 0) * (m.get("cost_ratio", 1))
                add(tid or "staff:" + m["provider_id"], m.get("provider_name", ""), "cddu", g, g * (coef_of(d, tid, "cddu")[0] if tid else p["coef"]["cddu"]), g * p["net_ratio"], 0, "prévu", True)
        for c in d["contracts"]:
            if c["type"] == "cddu" and c["start"][:7] == ym and c["team_id"] not in real and not (set(c.get("mission_ids") or []) & {m["id"] for m in d["missions"]}):
                g = c.get("base_pay", 0) * (c.get("quantity") or 1)
                add(c["team_id"], (d["team"].get(c["team_id"]) or {}).get("name", ""), "cddu", g, g * coef_of(d, c["team_id"], "cddu")[0], g * p["net_ratio"], 0, "prévu", True)
        for m in d["managers"]:
            pay, charge, cash = manager_month(d, m, ym)
            row["mgr_pay"], row["mgr_charge"], row["mgr_cash"] = row["mgr_pay"] + pay, row["mgr_charge"] + charge, row["mgr_cash"] + cash
            if pay:
                flows.append({"date": day_in(ym, p["pay_day"]), "kind": "gerants", "label": f"Rémunération {m['name']}", "amount": r2(pay)})
            if cash:
                flows.append({"date": day_in(ym, 5), "kind": "tns", "label": f"URSSAF indépendants {m['name']}", "amount": r2(cash)})
        if row["net"]:
            flows.append({"date": day_in(ym, p["pay_day"]), "kind": "nets", "label": f"Salaires nets {ym}" + (" (réel)" if row["real"] else ""), "amount": r2(row["net"])})
        if row["contrib"] > 0:
            flows.append({"date": day_in(ym_add(ym, 1), p["dues_day"]), "kind": "cotisations", "label": f"Cotisations sociales de {ym}", "amount": r2(row["contrib"])})
        if row["pas"]:
            flows.append({"date": day_in(ym_add(ym, 1), p["dues_day"]), "kind": "pas", "label": f"Prélèvement à la source de {ym}", "amount": r2(row["pas"])})
        rows.append({k: r2(v) if isinstance(v, float) else v for k, v in row.items()})
    keep = months[1:]
    cash = {ym: r2(sum(f["amount"] for f in flows if f["date"][:7] == ym)) for ym in keep}
    return {"months": keep, "rows": rows[1:], "people": sorted(people.values(), key=lambda x: x["name"]), "flows": sorted((f for f in flows if f["date"][:7] in keep), key=lambda f: f["date"]), "cash": cash,
            "staff_total": r2(sum(r["cost"] + r["cddu"] for r in rows[1:])), "managers_total": r2(sum(r["mgr_pay"] + r["mgr_charge"] for r in rows[1:]))}


# ---------- Congés ----------
def work_days(a: str, b: str, mode: str, half: float = 0) -> float:
    x, y, n = date.fromisoformat(a), date.fromisoformat(b), 0
    while x <= y:
        n += 1 if x.weekday() < (6 if mode == "ouvrables" else 5) else 0
        x += timedelta(days=1)
    return max(0.0, n - half)


def ref_period(p: dict, day: str) -> tuple:
    mm, dd = int(p["leave_ref_start"][:2]), int(p["leave_ref_start"][3:])
    t = date.fromisoformat(day)
    s = date(t.year, mm, dd)
    if s > t:
        s = date(t.year - 1, mm, dd)
    return s, date(s.year + 1, mm, dd) - timedelta(days=1)


def leave_balance(d: dict, tid: str, day: str | None = None) -> dict | None:
    day, p = day or today(), d["params"]
    cs = [c for c in d["contracts"] if c["team_id"] == tid and c["type"] != "cddu"]
    if not cs:
        return None
    hired, out = min(c["start"] for c in cs), max((c.get("end") or "9999-12-31") for c in cs)
    s, e = ref_period(p, day)
    ps, pe = date(s.year - 1, s.month, s.day), s - timedelta(days=1)

    def acquired(a: date, b: date) -> float:
        a, b = max(a, date.fromisoformat(hired)), min(b, date.fromisoformat(day), date.fromisoformat(out[:10]) if out < "9999" else b)
        return 0.0 if b < a else min(p["leave_days_per_month"] * 12, round(p["leave_days_per_month"] * ((b.year - a.year) * 12 + b.month - a.month + (1 if (b + timedelta(days=1)).month != b.month or b.day - a.day >= 27 else 0)), 2))
    f = d["files"].get(tid) or {}
    n1, n = acquired(ps, pe) + (f.get("leave_carry") or 0) + (f.get("split_days") or 0), acquired(s, e)
    mine = [a for a in d["absences"] if a["team_id"] == tid and a["type"] == "cp" and a["start"] >= ps.isoformat()]
    taken, pending = sum(a["days"] for a in mine if a["status"] == "approved"), sum(a["days"] for a in mine if a["status"] == "requested")
    return {"period": f"{s.isoformat()} → {e.isoformat()}", "n1_acquired": r2(n1), "n_acquired": r2(n), "taken": r2(taken), "pending": r2(pending), "n1_remaining": r2(max(0, n1 - taken)),
            "n_remaining": r2(n - max(0, taken - n1)), "remaining": r2(n1 + n - taken), "mode": p["leave_mode"], "split_days": f.get("split_days") or 0}


def leave_provision(d: dict, tid: str) -> float:
    b, c = leave_balance(d, tid), contract_at(d, tid, today()[:7])
    if not b or not c:
        return 0.0
    return r2(b["remaining"] * gross_at(d, {**c, "start": "2000-01-01", "end": ""}, today()[:7]) / (26 if d["params"]["leave_mode"] == "ouvrables" else 21.67) * coef_of(d, tid, c["type"])[0])


# ---------- Heures ----------
def month_hours(d: dict, tid: str, ym: str) -> dict:
    p, sid, days = d["params"], (d["files"].get(tid) or {}).get("staff_id"), {}
    rows = [{"date": e["date"], "h": (e.get("normal_h") or 0), "night": e.get("night_h") or 0, "sunday": e.get("sunday_h") or 0, "holiday": e.get("holiday_h") or 0, "source": e.get("source", "manual"), "id": e["id"]} for e in d["entries"] if e["team_id"] == tid and e["date"][:7] == ym]
    rows += [{"date": t["date"], "h": t.get("hours") or 0, "night": t.get("night_hours") or 0, "sunday": (t.get("hours") or 0) if date.fromisoformat(t["date"]).weekday() == 6 else 0, "holiday": 0, "source": "timesheet", "id": t["id"], "event_id": t.get("event_id")}
             for t in d["timesheets"] if sid and t.get("provider_id") == sid and t["date"][:7] == ym]
    weeks, warn = {}, []
    for r in rows:
        days[r["date"]] = days.get(r["date"], 0) + r["h"]
        wk = date.fromisoformat(r["date"]).isocalendar()[:2]
        weeks[wk] = weeks.get(wk, 0) + r["h"]
    warn += [f"{k} : {v:g} h dans la journée (maximum {p['daily_max']:g} h)" for k, v in sorted(days.items()) if v > p["daily_max"]]
    warn += [f"Semaine {k[1]} : {v:g} h (maximum {p['weekly_max']:g} h)" for k, v in sorted(weeks.items()) if v > p["weekly_max"]]
    c = contract_at(d, tid, ym)
    wh, ot = (c or {}).get("weekly_hours") or p["weekly_hours"], [{"pct": t["pct"], "hours": 0.0} for t in p["overtime"]]
    for v in weeks.values():
        extra = max(0.0, v - wh)
        for i, t in enumerate(p["overtime"]):
            x = extra if t.get("hours") is None else min(extra, t["hours"])
            ot[i]["hours"], extra = ot[i]["hours"] + x, extra - x
    total, hourly = sum(r["h"] for r in rows), (monthly_base(c, p) / (wh * 52 / 12) if c and wh else 0)
    amount = sum(o["hours"] * hourly * (1 + o["pct"] / 100) for o in ot) + hourly * (sum(r["night"] for r in rows) * p["night_pct"] + sum(r["sunday"] for r in rows) * p["sunday_pct"] + sum(r["holiday"] for r in rows) * p["holiday_pct"]) / 100
    return {"rows": sorted(rows, key=lambda r: r["date"]), "total": r2(total), "overtime": [{**o, "hours": r2(o["hours"])} for o in ot], "overtime_hours": r2(sum(o["hours"] for o in ot)), "normal": r2(total - sum(o["hours"] for o in ot)),
            "night": r2(sum(r["night"] for r in rows)), "sunday": r2(sum(r["sunday"] for r in rows)), "holiday": r2(sum(r["holiday"] for r in rows)), "contractual": r2(wh * 52 / 12) if c else 0, "warnings": warn, "overtime_amount": r2(amount)}


def contingent_used(d: dict, tid: str, year: str) -> float:
    return r2(sum(month_hours(d, tid, f"{year}-{m:02d}")["overtime_hours"] for m in range(1, 13)))


# ---------- Alertes ----------
def alerts(d: dict) -> list:
    t0, out, p = today(), [], d["params"]
    soon = lambda day, n: bool(day) and day <= (date.fromisoformat(t0) + timedelta(days=n)).isoformat()  # noqa: E731

    def add(kind, tid, label, day="", level="warn"):
        out.append({"kind": kind, "team_id": tid, "name": (d["team"].get(tid) or {}).get("name", ""), "label": label, "date": day, "level": level})
    for tid in d["team"]:
        c, f = current_contract(d, tid), d["files"].get(tid) or {}
        if f.get("status") == "sorti":
            if c and c.get("end") and not all((c.get("end_docs") or {}).get(k) for k in ("attestation_ft", "certificat", "solde")):
                add("end_docs", tid, "Documents de fin de contrat à remettre (attestation France Travail, certificat de travail, solde de tout compte)", c["end"])
            continue
        if c:
            if c["type"] == "cdd" and c.get("end") and t0 <= c["end"] and soon(c["end"], 15):
                add("cdd_end", tid, "Fin de CDD : renouveler, passer en CDI ou laisser finir (indemnité de fin de contrat à prévoir)", c["end"], "high")
            if c.get("trial_end") and t0 <= c["trial_end"] and soon(c["trial_end"], 15):
                add("trial_end", tid, "Fin de période d'essai", c["trial_end"])
            if not c.get("dpae_done_at") and soon(c["start"], 1) and c["type"] != "stage" and (not c.get("end") or c["end"] >= t0):
                add("dpae", tid, "DPAE manquante avant la prise de poste", c["start"], "high")
            if not c.get("signed_at") and c["start"] <= (date.fromisoformat(t0) - timedelta(days=2)).isoformat() and (not c.get("end") or c["end"] >= t0):
                add("contract_unsigned", tid, "Contrat non remis signé dans le délai légal", c["start"])
            if c["type"] == "cdd" and c.get("end"):
                root = min(x["start"] for x in d["contracts"] if x["team_id"] == tid and x["type"] == "cdd")
                if (date.fromisoformat(c["end"]) - date.fromisoformat(root)).days > p["cdd_max_months"] * 30.5 or (c.get("renewals") or 0) > p["cdd_max_renewals"]:
                    add("cdd_limit", tid, f"CDD au-delà de la durée maximale ({p['cdd_max_months']} mois) ou du nombre de renouvellements ({p['cdd_max_renewals']})", c["end"], "high")
            mini = next((m.get("monthly") for m in p.get("minimums") or [] if m.get("classification") and m["classification"] == c.get("classification")), None)
            if mini and c.get("pay_basis") == "monthly" and c.get("base_pay", 0) < mini * (c.get("weekly_hours") or p["weekly_hours"]) / p["weekly_hours"]:
                add("minimum", tid, f"Salaire de base inférieur au minimum conventionnel ({mini:g} €)", "", "high")
        for key, label, n in (("medical_next", "Visite médicale à prévoir", 30), ("prof_review_next", "Entretien professionnel à prévoir", 30), ("mutual_waiver_end", "Fin de dispense de mutuelle", 30), ("residence_permit_end", "Titre de séjour à renouveler", 60)):
            if soon(f.get(key), n):
                add(key, tid, label, f[key], "high" if f[key] < t0 else "warn")
        for h in f.get("habilitations") or []:
            if soon(h.get("expires"), 30):
                add("habilitation", tid, f"Habilitation « {h.get('label', '')} » à renouveler", h["expires"])
    return sorted(out, key=lambda a: (a["level"] != "high", a["date"] or "9"))
