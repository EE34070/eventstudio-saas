import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AlertTriangle, Wrench, UserX, Truck, Repeat, ArrowUp, ArrowDown, GripVertical, Settings2 } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { api } from "@/lib/api";
import { useMe } from "@/context/MeContext";
import { TensionWidget } from "@/components/stock/Availability";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { PageHeader, StatusBadge, Section, Loading } from "@/components/common";
import { STATUSES, fmtEur, fmtDate } from "@/lib/constants";

const ICONS = { conflit: AlertTriangle, maintenance: Wrench, technicien: UserX, vehicule: Truck, abonnement: Repeat };
const LOGI = { non_planifie: ["Non planifié", "bg-secondary text-muted-foreground"], planifie: ["Planifié", "bg-blue-500/15 text-blue-700 dark:text-blue-300"], charge: ["Chargé", "bg-amber-500/15 text-amber-700 dark:text-amber-300"], livre: ["Livré", "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"], retire: ["Retiré", "bg-foreground text-background"] };
const WIDGETS = [["today", "Aujourd'hui"], ["events14", "Événements des 14 prochains jours"], ["alerts", "Alertes"], ["finance", "Devis, factures et achats"], ["tasks", "Mes tâches"], ["tension", "Stock sous tension"], ["ca", "Chiffre d'affaires (HT)"], ["chart", "Chiffre d'affaires mensuel (HT)"], ["pipeline", "Pipeline par statut"]];
const TITLE = Object.fromEntries(WIDGETS);
const WIDE = ["events14", "chart"];

const Logi = ({ s }) => <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${LOGI[s][1]}`} data-testid={`logi-${s}`}>{LOGI[s][0]}</span>;
const Empty = ({ children }) => <div className="text-sm text-muted-foreground">{children}</div>;
const Stat = ({ label, value, sub, to, tone = "", testid }) => (
  <Link to={to} className="block rounded-xl border border-border p-3.5 transition-colors hover:bg-secondary/50" data-testid={testid}>
    <div className="eyebrow">{label}</div><div className={`mt-1.5 font-display text-2xl ${tone}`}>{value}</div>{sub && <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>}
  </Link>
);

function Today({ t }) {
  const groups = [["Chargements", t.loadings, "/chargement"], ["Livraisons", t.deliveries, "/livraison"], ["Retraits", t.returns, "/evenements"]];
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {groups.map(([l, rows, to]) => (
        <div key={l} className="rounded-xl border border-border p-3.5" data-testid={`today-${to.slice(1)}-${l}`}>
          <Link to={to} className="flex items-baseline justify-between"><span className="eyebrow">{l}</span><span className="font-display text-2xl">{rows.length}</span></Link>
          {rows.map((e) => <Link key={e.id} to={`/evenements/${e.id}`} className="mt-1.5 block truncate text-[13px] hover:text-primary">{e.setup_start.slice(11, 16)} · {e.title}</Link>)}
        </div>
      ))}
    </div>
  );
}

function Events14({ rows }) {
  if (!rows.length) return <Empty>Aucun événement dans les 14 prochains jours.</Empty>;
  return (
    <div className="divide-y divide-border">
      {rows.map((e) => (
        <Link key={e.id} to={`/evenements/${e.id}`} className="group flex flex-wrap items-center gap-3 py-2.5" data-testid={`event14-${e.id}`}>
          <span className="w-20 shrink-0 text-xs text-muted-foreground">{fmtDate(e.start, { weekday: "short", day: "numeric", month: "short" })}</span>
          <span className="min-w-0 flex-1 truncate text-sm font-medium group-hover:text-primary">{e.title}</span>
          {e.alert && <span className="h-2.5 w-2.5 rounded-full bg-red-600" title="Véhicule non affecté" data-testid={`event14-alert-${e.id}`} />}
          {e.vehicle_name && <span className="hidden text-xs text-muted-foreground sm:inline">{e.vehicle_name}</span>}
          <Logi s={e.logistics} /><StatusBadge status={e.status} />
        </Link>
      ))}
    </div>
  );
}

function Alerts({ alerts }) {
  const nav = useNavigate();
  if (!alerts.length) return <Empty>Aucune alerte, tout est sous contrôle.</Empty>;
  return (
    <div className="space-y-2.5">
      {alerts.map((a, i) => {
        const I = ICONS[a.type] || AlertTriangle;
        return (
          <button key={i} data-testid={`alert-${a.type}-${i}`} onClick={() => nav(a.to || (a.event_id ? `/evenements/${a.event_id}` : "/catalogue?tab=maintenance"))}
            className={`flex w-full gap-3 rounded-xl border p-3.5 text-left transition-colors ${a.severity === "danger" ? "border-red-500/30 bg-red-500/10 hover:bg-red-500/15" : "border-amber-500/30 bg-amber-500/10 hover:bg-amber-500/15"}`}>
            <I className={`mt-0.5 h-4 w-4 shrink-0 ${a.severity === "danger" ? "text-red-600 dark:text-red-400" : "text-amber-600 dark:text-amber-400"}`} />
            <div className="min-w-0"><div className="text-[13px] font-semibold">{a.title}</div><div className="text-xs text-muted-foreground">{a.detail}</div></div>
          </button>
        );
      })}
    </div>
  );
}

const Finance = ({ f }) => (
  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
    <Stat testid="kpi-quotes-pending" to="/devis-factures?tab=devis" label="Devis en attente" value={f.quotes_count} sub={`${fmtEur(f.quotes_total)} TTC`} />
    <Stat testid="kpi-unpaid" to="/relances" label="Factures impayées" value={fmtEur(f.unpaid_total)} tone={f.late_count ? "text-red-600" : ""} sub={f.late_count ? `${f.late_count} en retard, jusqu'à ${f.late_days} j` : `${f.unpaid_count} facture(s)`} />
    <Stat testid="kpi-purchases" to="/factures-achat" label="Factures d'achat à payer" value={fmtEur(f.purchases_total)} tone={f.purchases_overdue ? "text-red-600" : ""} sub={`${f.purchases_count} facture(s)${f.purchases_overdue ? `, ${f.purchases_overdue} échue(s)` : ""}`} />
  </div>
);

const Ca = ({ f }) => (
  <div className="grid grid-cols-2 gap-3">
    <Stat testid="kpi-ca-month" to="/evenements" label="CA du mois" value={fmtEur(f.ca_month)} sub={`+ ${fmtEur(f.ca_month_quotes)} en devis`} />
    <Stat testid="kpi-ca-year" to="/evenements" label="CA de l'année" value={fmtEur(f.ca_year)} sub={`+ ${fmtEur(f.ca_year_quotes)} en devis`} />
  </div>
);

function Tasks({ rows }) {
  if (!rows.length) return <Empty>Aucune tâche pour aujourd'hui.</Empty>;
  return <div className="divide-y divide-border">{rows.map((t) => <Link key={t.id} to="/todo" className="flex items-center gap-3 py-2 text-sm" data-testid={`dash-task-${t.id}`}><span className="min-w-0 flex-1 truncate">{t.title}</span><span className={`text-xs font-semibold ${t.overdue ? "text-red-600" : "text-muted-foreground"}`}>{t.overdue ? `En retard · ${fmtDate(t.due_at.slice(0, 10), { day: "numeric", month: "short" })}` : t.due_at.slice(11, 16) || "Aujourd'hui"}</span></Link>)}</div>;
}

const Chart = ({ months }) => (
  <div className="h-64">
    <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 256 }}>
      <BarChart data={months.map((m) => ({ ...m, label: new Date(m.month + "-01").toLocaleDateString("fr-FR", { month: "short" }) }))}>
        <CartesianGrid vertical={false} stroke="hsl(var(--border))" />
        <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={11} />
        <YAxis tickLine={false} axisLine={false} fontSize={11} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
        <Tooltip formatter={(v) => fmtEur(v)} cursor={{ fill: "hsl(var(--secondary))" }} contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 12 }} />
        <Bar dataKey="ca" name="Confirmé" stackId="a" fill="#0347FB" />
        <Bar dataKey="pipeline" name="Devis envoyés" stackId="a" fill="#03A9FC" fillOpacity={0.45} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  </div>
);

const Pipeline = ({ counts }) => (
  <div className="space-y-1.5">{STATUSES.map((s) => <Link to={`/evenements?status=${s.id}`} key={s.id} className="flex items-center justify-between rounded-lg px-2 py-1.5 hover:bg-secondary"><StatusBadge status={s.id} /><span className="font-display text-lg">{counts[s.id]}</span></Link>)}</div>
);

export default function Dashboard() {
  const { me } = useMe();
  const [d, setD] = useState(null);
  const [x, setX] = useState(null);
  const [dj, setDj] = useState({ alerts: [], without_dj: 0 });
  const [layout, setLayout] = useState(null);
  const [edit, setEdit] = useState(false);
  const [drag, setDrag] = useState(null);
  useEffect(() => {
    api.get("/dashboard").then((r) => setD(r.data));
    api.get("/dashboard/extra").then((r) => setX(r.data));
    api.get("/dj/coverage").then((r) => setDj(r.data)).catch(() => {});
    api.get("/menu").then((r) => { const saved = (r.data.prefs.dashboard_widgets || []).filter((w) => TITLE[w.id]); setLayout([...saved, ...WIDGETS.filter(([id]) => !saved.some((w) => w.id === id)).map(([id]) => ({ id, on: true }))]); });
  }, []);
  if (!d || !x || !layout) return <Loading />;
  const tech = me.user.role === "technicien";
  const body = {
    today: <Today t={x.today} />, events14: <Events14 rows={x.events14} />, alerts: tech ? null : <Alerts alerts={[...dj.alerts, ...x.alerts, ...d.alerts]} />,
    finance: x.finance && <Finance f={x.finance} />, tasks: <Tasks rows={x.tasks} />, ca: x.finance && <Ca f={x.finance} />,
    tension: x.finance && <TensionWidget />,
    chart: d.months && <Chart months={d.months} />, pipeline: <Pipeline counts={d.status_counts} />,
  };
  const save = (next) => { setLayout(next); api.put("/menu/prefs", { dashboard_widgets: next }).catch(() => {}); };
  const move = (from, to) => { if (to < 0 || to >= layout.length || from === to) return; const next = [...layout]; next.splice(to, 0, next.splice(from, 1)[0]); save(next); };
  const shown = layout.map((w, i) => ({ ...w, i })).filter((w) => body[w.id] && (edit || w.on));
  return (
    <div>
      <PageHeader title="Tableau de bord" subtitle={`Bonjour ${me.user.name?.split(" ")[0]} — ${x.events14.length} événement(s) dans les 14 jours, ${tech ? x.tasks.length + " tâche(s)" : x.alerts.length + d.alerts.length + " alerte(s)"}.`}
        actions={<Button variant={edit ? "default" : "outline"} size="sm" onClick={() => setEdit(!edit)} data-testid="dashboard-customize"><Settings2 />{edit ? "Terminer" : "Personnaliser"}</Button>} />
      {edit && <p className="mb-4 text-sm text-muted-foreground">Glissez un bloc ou utilisez les flèches pour le déplacer ; l'interrupteur l'affiche ou le masque. Votre disposition est mémorisée.</p>}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2" data-testid="dashboard-grid">
        {shown.map((w) => (
          <div key={w.id} draggable={edit} onDragStart={() => setDrag(w.i)} onDragOver={(e) => edit && e.preventDefault()} onDrop={() => { if (drag != null) move(drag, w.i); setDrag(null); }}
            className={`${WIDE.includes(w.id) ? "xl:col-span-2" : ""} ${edit ? "cursor-grab rounded-2xl ring-1 ring-dashed ring-primary/40" : ""} ${w.on ? "" : "opacity-50"}`} data-testid={`widget-${w.id}`}>
            <Section title={w.id === "alerts" ? `Alertes (${x.alerts.length + d.alerts.length + dj.alerts.length})${dj.without_dj ? ` · Prestations DJ sans DJ : ${dj.without_dj}` : ""}` : TITLE[w.id]} className="h-full"
              actions={edit && <div className="flex items-center gap-1"><GripVertical className="h-4 w-4 text-muted-foreground" />
                <button className="icon-btn" onClick={() => move(w.i, w.i - 1)} aria-label="Monter" data-testid={`widget-up-${w.id}`}><ArrowUp className="h-4 w-4" /></button>
                <button className="icon-btn" onClick={() => move(w.i, w.i + 1)} aria-label="Descendre" data-testid={`widget-down-${w.id}`}><ArrowDown className="h-4 w-4" /></button>
                <Switch checked={w.on} onCheckedChange={(on) => save(layout.map((l) => (l.id === w.id ? { ...l, on } : l)))} data-testid={`widget-switch-${w.id}`} /></div>}>
              {body[w.id]}
            </Section>
          </div>
        ))}
      </div>
    </div>
  );
}
