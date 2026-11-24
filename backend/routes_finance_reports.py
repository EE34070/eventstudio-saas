"""Finance : tableau de bord prévisionnel, activité, marges. Chaque onglet renvoie {kpis, tables, alerts}, repris tel quel par l'écran et les exports."""
import io
import math
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

import routes_finance as fin
from core import Ctx, db

router = APIRouter(prefix="/api")
R = fin.R
DONE = ("realise", "facture", "cloture")
SENT = ("envoye", "vu", "accepte", "refuse")
r2 = fin.r2
col = lambda l, t="text": {"l": l, "t": t}  # noqa: E731
kpi = lambda key, label, value, t="eur", hint="": {"key": key, "label": label, "value": value, "t": t, "hint": hint}  # noqa: E731


def group(rows: list, key: str) -> dict:
    out: dict = {}
    for r in rows:
        out.setdefault(r[key], []).append(r)
    return out


async def load(ctx: Ctx) -> dict:
    cfg = await fin.settings(ctx.org_id)
    eqs = {e["id"]: e for e in await ctx.list("equipment", limit=10000)}
    qs, invs, cms = [group(await ctx.list(c, limit=20000), "event_id") for c in ("quotes", "invoices", "commitments")]
    opps = {o["event_id"]: o for o in await ctx.list("opportunities", limit=10000) if o.get("event_id")}
    names = {c["id"]: c.get("company") or " ".join(filter(None, [c.get("first_name"), c.get("last_name")])) for c in await ctx.list("contacts", limit=20000)}
    venues = {v["id"]: v.get("name", "") for v in await ctx.list("venues", limit=5000)}
    st = await db.crm_stages.find_one(ctx.q({"key": "devis_envoye"}), {"_id": 0, "default_probability": 1})
    chans, today, rows = {c["id"]: c["name"] for c in cfg["channels"]}, date.today().isoformat(), []
    for ev in await ctx.list("events", limit=10000):
        f = fin.event_finance(ev, qs.get(ev["id"], []), invs.get(ev["id"], []), cms.get(ev["id"], []), cfg, eqs, opps.get(ev["id"]), (st or {}).get("default_probability", 50))
        d = (ev.get("start") or "")[:10]
        q = next((x for x in qs.get(ev["id"], []) if f["quote"] and x["id"] == f["quote"]["id"]), None)
        rows.append({**f, "date": d, "month": d[:7], "title": ev.get("title", ""), "code": ev.get("code", ""), "type": ev.get("type") or "—", "language": ev.get("language") or "fr-FR",
                     "planner": names.get(ev.get("planner_contact_id"), "—"), "venue": venues.get(ev.get("venue_id"), "—"), "channel": chans.get(fin.channel_of(ev, opps.get(ev["id"]), cfg["channels"]), "—"),
                     "done": ev.get("status") in DONE or d < today, "ca": f["revenue"]["quoted_ht"], "lines": (q or {}).get("lines") or []})
    return {"cfg": cfg, "rows": rows, "quotes": [q for v in qs.values() for q in v], "opps": list(opps.values()), "eqs": eqs, "today": today,
            "subs": await ctx.list("subscriptions", {"active": {"$ne": False}})}


def amt(r: dict, act: str = "") -> float:
    return r["by_activity"].get(act, 0) if act else r["ca"]


def margin_rate(rows: list):
    done = [r for r in rows if r["done"] and r["signed"] and r["ca"]]
    ca = sum(r["revenue"]["invoiced_ht"] if r["margin_real"] is not None else r["ca"] for r in done)
    return round(sum(r["margin_real"] if r["margin_real"] is not None else r["margin_planned"] for r in done) / ca * 100, 1) if ca else None


def fixed_monthly(d: dict) -> float:
    per = {"monthly": 1, "quarterly": 1 / 3, "yearly": 1 / 12}
    return d["cfg"]["fixed_costs_monthly"] if d["cfg"]["fixed_costs_monthly"] is not None else r2(sum(s.get("amount", 0) * per.get(s.get("period"), 1) for s in d["subs"]))


def dashboard(d: dict, act: str, costs: bool) -> dict:
    rows, today = d["rows"], d["today"]
    m, y = today[:7], today[:4]
    prev = lambda k: f"{int(k[:4]) - 1}{k[4:]}"  # noqa: E731
    signed = [r for r in rows if r["signed"]]
    ca = lambda p: r2(sum(amt(r, act) for r in signed if r["month"].startswith(p)))  # noqa: E731
    backlog: dict = {}
    for r in signed:
        if r["date"] >= today:
            backlog[r["month"]] = r2(backlog.get(r["month"], 0) + amt(r, act))
    pipe = [r for r in rows if not r["signed"] and r["quote"] and r["date"] >= today]
    rate = d["cfg"]["variable_margin_rate"] if d["cfg"]["variable_margin_rate"] is not None else margin_rate(rows) if costs else None
    fixed = fixed_monthly(d)
    be = r2(fixed / rate * 100) if rate and rate > 0 else None
    basket = sum(r["ca"] for r in signed) / len(signed) if signed else 0
    alerts = []
    if costs:
        alerts += [f"{r['code']} {r['title']} : marge {r['margin_planned_pct']} % sous le seuil de {r['threshold']} %" for r in rows if r["done"] and r["signed"] and r["alert"]][:20]
        alerts += [f"{r['code']} {r['title']} : écart prévu / réel de plus de 10 % sur les charges" for r in rows if r["charges"]["planned"] and r["charges"]["invoiced"] > r["charges"]["planned"] * 1.1][:20]
    return {"kpis": [kpi("ca_month", "CA signé du mois", ca(m), hint=f"N-1 : {ca(prev(m)):,.0f} €".replace(",", " ")), kpi("ca_year", "CA signé de l'exercice", ca(y), hint=f"N-1 : {ca(prev(y)):,.0f} €".replace(",", " ")),
                     kpi("backlog", "Carnet de commandes", r2(sum(backlog.values())), hint="devis signés, événements à venir"),
                     kpi("pipeline", "Pipeline pondéré", r2(sum(amt(r, act) * r["probability"] / 100 for r in pipe)), hint=f"{len(pipe)} devis en cours"),
                     kpi("avg_margin", "Marge moyenne réalisée", margin_rate(rows) if costs else None, "pct"), kpi("breakeven", "Point mort mensuel", be, hint=f"charges fixes {fixed:,.0f} € / taux {rate or '—'} %".replace(",", " ")),
                     kpi("breakeven_events", "Soit en événements", math.ceil(be / basket) if be and basket else None, "int", f"panier moyen {basket:,.0f} €".replace(",", " ")),
                     kpi("coverage", "Taux de couverture du mois", round(ca(m) / be * 100, 1) if be else None, "pct")],
            "tables": [{"key": "backlog", "title": "Carnet de commandes par mois de réalisation", "columns": [col("Mois"), col("HT signé", "eur")], "rows": [[k, v] for k, v in sorted(backlog.items())]},
                       {"key": "pipeline", "title": "Devis en cours", "columns": [col("Événement"), col("Date"), col("HT", "eur"), col("Probabilité", "pct"), col("Pondéré", "eur")],
                        "rows": [[f"{r['code']} {r['title']}", r["date"], amt(r, act), r["probability"], r2(amt(r, act) * r["probability"] / 100)] for r in sorted(pipe, key=lambda r: r["date"])]}],
            "alerts": alerts, "real": "Trésorerie, facturé et encaissé comptables"}


def breakdown(rows: list, key: str, title: str, margins: bool = False) -> dict:
    out = []
    for k, rs in sorted(group(rows, key).items(), key=lambda x: -sum(r["ca"] for r in x[1])):
        ca, mg = sum(r["ca"] for r in rs), sum(r["margin_planned"] or 0 for r in rs)
        out.append([k, r2(ca), len(rs)] + ([r2(mg), round(mg / ca * 100, 1) if ca else None] if margins else [r2(ca / len(rs))]))
    return {"key": f"by_{key}", "title": title, "columns": [col(title.replace("Par ", "").capitalize()), col("CA HT", "eur"), col("Événements", "int")] + ([col("Marge", "eur"), col("Marge %", "pct")] if margins else [col("Panier moyen", "eur")]), "rows": out}


def by_activity(d: dict, rows: list, margins: bool = False) -> dict:
    names, out = {a["id"]: a["name"] for a in d["cfg"]["activities"]}, []
    for a, n in names.items():
        rs = [r for r in rows if r["by_activity"].get(a)]
        ca = sum(r["by_activity"][a] for r in rs)
        mg = sum((r["margin_planned"] or 0) * r["by_activity"][a] / r["ca"] for r in rs if r["ca"])
        if rs:
            out.append([n, r2(ca), len(rs)] + ([r2(mg), round(mg / ca * 100, 1) if ca else None] if margins else [r2(ca / len(rs))]))
    return {"key": "by_activity", "title": "Par activité", "columns": [col("Activité"), col("CA HT", "eur"), col("Événements", "int")] + ([col("Marge (au prorata)", "eur"), col("Marge %", "pct")] if margins else [col("Panier moyen", "eur")]), "rows": out}


DIMS = [("channel", "Par canal"), ("planner", "Par wedding planner"), ("venue", "Par lieu"), ("type", "Par type d'événement")]


def activity(d: dict, start: str, end: str, act: str) -> dict:
    signed = [r for r in d["rows"] if r["signed"] and (not act or r["by_activity"].get(act))]
    rows, y = [r for r in signed if start <= r["date"] <= end], int(end[:4])
    ca = lambda p: r2(sum(amt(r, act) for r in signed if r["month"] == p))  # noqa: E731
    sent = [q for q in d["quotes"] if q.get("status") in SENT and start <= (q.get("date") or q.get("created_at", ""))[:10] <= end]
    won = [q for q in sent if q["status"] == "accepte"]
    ev_ch = {r["event_id"]: r["channel"] for r in d["rows"]}
    conv = [[ch, len(qs), len([q for q in qs if q["status"] == "accepte"]), round(len([q for q in qs if q["status"] == "accepte"]) / len(qs) * 100, 1)] for ch, qs in group([{**q, "ch": ev_ch.get(q.get("event_id"), "—")} for q in sent], "ch").items()]
    days = [(date.fromisoformat(((q.get("signature") or {}).get("signed_at") or q.get("updated_at") or q["created_at"])[:10]) - date.fromisoformat(q["created_at"][:10])).days for q in won if q.get("created_at")]
    lost: dict = {}
    for o in d["opps"]:
        if o.get("lost_reason"):
            lost[o["lost_reason"]] = lost.get(o["lost_reason"], 0) + 1
    tot = sum(r["ca"] for r in rows)
    return {"kpis": [kpi("ca", "CA signé sur la période", r2(sum(amt(r, act) for r in rows))), kpi("events", "Événements", len(rows), "int"), kpi("basket", "Panier moyen", r2(tot / len(rows)) if rows else None),
                     kpi("foreign", "Part des clients étrangers", round(sum(r["ca"] for r in rows if not r["language"].startswith("fr")) / tot * 100, 1) if tot else None, "pct"),
                     kpi("conv_count", "Transformation des devis (nombre)", round(len(won) / len(sent) * 100, 1) if sent else None, "pct", f"{len(won)} signés sur {len(sent)} envoyés"),
                     kpi("conv_amount", "Transformation (montant)", round(sum(q.get("total_ht") or 0 for q in won) / (sum(q.get("total_ht") or 0 for q in sent) or 1) * 100, 1) if sent else None, "pct"),
                     kpi("delay", "Délai moyen création → signature", round(sum(days) / len(days), 1) if days else None, "int", "jours")],
            "tables": [{"key": "monthly", "title": f"CA mensuel {y} vs {y - 1}", "columns": [col("Mois"), col(str(y), "eur"), col(str(y - 1), "eur")], "rows": [[f"{i:02d}", ca(f"{y}-{i:02d}"), ca(f"{y - 1}-{i:02d}")] for i in range(1, 13)]},
                       by_activity(d, rows)] + [breakdown(rows, k, t) for k, t in DIMS] +
                      [{"key": "conversion", "title": "Transformation par canal", "columns": [col("Canal"), col("Envoyés", "int"), col("Signés", "int"), col("Taux", "pct")], "rows": conv},
                       {"key": "lost", "title": "Motifs de perte", "columns": [col("Motif"), col("Nombre", "int")], "rows": sorted(lost.items(), key=lambda x: -x[1])}], "alerts": []}


async def margins(ctx: Ctx, d: dict, start: str, end: str, act: str) -> dict:
    import routes_suppliers as sup
    rows = [r for r in d["rows"] if r["signed"] and start <= r["date"] <= end and (not act or r["by_activity"].get(act))]
    ev = lambda r: [{"to": f"/evenements/{r['event_id']}?tab=finances", "label": f"{r['code']} {r['title']}"}, r["date"], r["ca"], r["charges"]["planned"], r["margin_planned"], r["margin_planned_pct"], r["margin_real"],  # noqa: E731
                    r2(r["margin_real"] - r["margin_planned"]) if r["margin_real"] is not None else None]
    evc = [col("Événement", "link"), col("Date"), col("CA HT", "eur"), col("Coûts directs", "eur"), col("Marge prévue", "eur"), col("%", "pct"), col("Marge réelle", "eur"), col("Écart", "eur")]
    ranked = sorted([r for r in rows if r["margin_planned_pct"] is not None], key=lambda r: -r["margin_planned_pct"])
    prod: dict = {}
    for r in rows:
        for l in r["lines"]:
            if l.get("equipment_id") in d["eqs"]:
                p = prod.setdefault(l["equipment_id"], [0, 0, 0])
                p[0] += (l.get("qty") or 0) * (l.get("unit_price") or 0)
                p[1] += l.get("qty") or 0
                p[2] += 1
    maps = {m["product_id"]: m for m in await sup.rows_for(ctx.org_id, {"is_preferred": True})}
    prows = []
    for pid, (ca, qty, n) in sorted(prod.items(), key=lambda x: -x[1][0]):
        e, buy = d["eqs"][pid], (maps.get(pid) or {}).get("stock_price_ht")
        prows.append([f"{e.get('ref', '')} {e['name']}".strip(), r2(ca), qty, n, buy, round(ca / (buy * (e.get("qty_total") or 1)), 2) if buy else None])
    alerts = [f"{p[0]} : prix moyen loué inférieur au prix d'achat unitaire" for p in prows if p[4] and p[2] and p[1] / p[2] < 0][:10]
    return {"kpis": [kpi("ca", "CA signé", r2(sum(r["ca"] for r in rows))), kpi("costs", "Coûts directs prévus", r2(sum(r["charges"]["planned"] for r in rows))),
                     kpi("margin", "Marge prévisionnelle", r2(sum(r["margin_planned"] for r in rows))), kpi("rate", "Taux de marge réalisé", margin_rate(rows), "pct")],
            "tables": [{"key": "events", "title": "Par événement", "columns": evc, "rows": [ev(r) for r in sorted(rows, key=lambda r: r["date"])]}, by_activity(d, rows, True)] + [breakdown(rows, k, t, True) for k, t in DIMS] +
                      [{"key": "products", "title": "Par produit (devis signés)", "columns": [col("Produit"), col("CA HT", "eur"), col("Quantité louée", "num"), col("Devis", "int"), col("Prix d'achat unitaire", "eur"), col("CA / valeur du parc", "num")], "rows": prows},
                       {"key": "top", "title": "Top 10 événements", "columns": evc, "rows": [ev(r) for r in ranked[:10]]}, {"key": "flop", "title": "Flop 10 événements", "columns": evc, "rows": [ev(r) for r in ranked[::-1][:10]]}],
            "alerts": alerts, "note": "Fiches de coût de revient détaillées, taux d'utilisation et ROI : lot suivant."}


async def build(ctx: Ctx, tab: str, start: str, end: str, act: str) -> dict:
    y = date.today().year
    start, end = start or f"{y}-01-01", end or f"{y}-12-31"
    d = await load(ctx)
    if tab == "dashboard":
        return dashboard(d, act, ctx.can("finance:costs"))
    if tab == "activite":
        return activity(d, start, end, act)
    if tab == "marges":
        if not ctx.can("finance:costs"):
            raise HTTPException(403, "Réservé aux profils qui voient les coûts et les marges")
        return await margins(ctx, d, start, end, act)
    raise HTTPException(404, "Onglet inconnu")


@router.get("/finance/report/{tab}")
async def report(tab: str, start: str = "", end: str = "", activity: str = "", ctx: Ctx = Depends(R)):
    return await build(ctx, tab, start, end, activity)


def cell(v):
    return v["label"] if isinstance(v, dict) else v


def to_xlsx(title: str, data: dict) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Synthèse"
    ws.append([title])
    for k in data.get("kpis", []):
        ws.append([k["label"], k["value"], k.get("hint", "")])
    for t in data["tables"]:
        s = wb.create_sheet(t["title"][:31].replace("/", "-"))
        s.append([c["l"] for c in t["columns"]])
        for r in t["rows"]:
            s.append([cell(v) for v in r])
        for f in t.get("formulas", []):
            s.append(f)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def fmt(v, t):
    if v is None:
        return "—"
    v = cell(v)
    if isinstance(v, str) or t in ("text", "link"):
        return str(v)
    return f"{v:,.0f} €".replace(",", " ") if t == "eur" else f"{v:g} %" if t == "pct" else f"{v:g}"


def to_pdf(title: str, data: dict, intro: list = (), footer: str = "") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    st, out = getSampleStyleSheet(), io.BytesIO()
    flow = [Paragraph(title, st["Title"])] + [Paragraph(x, st["BodyText"]) for x in intro] + [Spacer(1, 10)]
    if data.get("kpis"):
        flow += [Table([[k["label"], fmt(k["value"], k["t"])] for k in data["kpis"]], colWidths=[260, 160]), Spacer(1, 12)]
    for t in data["tables"]:
        if not t["rows"]:
            continue
        rows = [[c["l"] for c in t["columns"]]] + [[fmt(v, c["t"]) for v, c in zip(r, t["columns"])] for r in t["rows"]]
        tb = Table(rows, repeatRows=1)
        tb.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
        flow += [Paragraph(t["title"], st["Heading3"]), tb, Spacer(1, 10)]
    if footer:
        flow.append(Paragraph(footer, st["Italic"]))
    SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24).build(flow)
    return out.getvalue()


def send(name: str, fmt_: str, title: str, data: dict, **kw) -> Response:
    if fmt_ == "xlsx":
        return Response(to_xlsx(title, data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    return Response(to_pdf(title, data, **kw), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})


@router.get("/finance/export/{tab}")
async def export(tab: str, format: str = "xlsx", start: str = "", end: str = "", activity: str = "", ctx: Ctx = Depends(R)):
    titles = {"dashboard": "Tableau de bord", "activite": "Activité", "marges": "Marges & rentabilité"}
    return send(f"finance-{tab}", format, f"Finance — {titles.get(tab, tab)}", await build(ctx, tab, start, end, activity), footer="Données prévisionnelles issues de l'application. Réel comptable : Pennylane non connecté.")
