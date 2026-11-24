import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { QRCodeSVG } from "qrcode.react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader, Section } from "@/components/common";
import { api, errMsg, downloadPdf } from "@/lib/api";
import { openFile } from "@/lib/files";
import { fmtDate, fmtEur } from "@/lib/constants";

const ko = (e) => toast.error(errMsg(e));
const TS = { declared: "Déclarées", validated: "Validées", refused: "Refusées", invoiced: "Facturées", payroll: "Transmises en paie", paid: "Payées" };
const APP = { invited: "Invité", applied: "Candidat", shortlisted: "Présélectionné", waitlist: "Liste d'attente", confirmed: "Confirmé", refused: "Refusé", withdrawn: "Désisté", filled_elsewhere: "Poste pourvu" };
const ES = { freelance: "Indépendant", intermittent: "Intermittent", other: "Autre" };
const sel = "h-9 rounded-lg border border-border bg-background px-2 text-sm";

function useGet(path) {
  const [d, setD] = useState(null);
  const load = useCallback(() => api.get(path).then((r) => setD(r.data)).catch(ko), [path]);
  useEffect(() => { load(); }, [load]);
  return [d, load];
}

function Network() {
  const [d, load] = useGet("/staff/overview");
  if (!d) return null;
  const url = `${window.location.origin}/rejoindre?o=${d.org_id}`;
  const decide = (a, decision) => { const message = decision === "more_info" ? window.prompt("Quel complément demander ?") : ""; if (decision !== "more_info" || message) api.post(`/providers/${a.id}/validate`, { decision, message: message || "" }).then(load).catch(ko); };
  return (
    <div className="space-y-4" data-testid="staff-network">
      {d.dpae_alerts.map((m) => <div key={m.id} className="flex items-center gap-3 rounded-xl bg-red-500/10 p-3 text-sm font-semibold text-red-600" data-testid={`dpae-alert-${m.id}`}>DPAE à faire : {m.provider_name}, mission du {fmtDate(m.date)}<Button size="sm" variant="outline" onClick={() => (m.team_id ? api.post(`/team/${m.team_id}/dpae`, { event_id: m.event_id }) : api.post(`/missions/${m.id}/dpae`)).then(load).catch(ko)}>DPAE faite</Button></div>)}
      <div className="card-soft flex flex-wrap items-center gap-4 p-4"><QRCodeSVG value={url} size={84} /><div className="min-w-0 flex-1 text-sm"><b>Lien d'inscription « Rejoindre l'équipe »</b><div className="break-all font-mono text-xs" data-testid="join-url">{url}</div></div></div>
      {!d.applications.length && <p className="text-sm text-muted-foreground">Aucune candidature en attente.</p>}
      {d.applications.map((a) => <div key={a.id} className="card-soft p-4 text-sm" data-testid={`network-app-${a.id}`}><div className="flex flex-wrap items-center gap-2"><b className="flex-1">{a.name}</b><span>{ES[a.employment_status]}</span><span className="text-xs text-muted-foreground">profil {a.completion_pct} %</span></div>
        <div className="text-muted-foreground">{a.email} · {a.phone} · {a.categories.map((c) => d.labels[c] || c).join(", ")} · {a.base_city} ({a.radius_km} km) · {fmtEur(a.base_rate)}</div>{a.bio && <p className="mt-1">{a.bio}</p>}
        {a.duplicate_of && <div className="mt-1 text-xs font-semibold text-amber-700">Un contact existe déjà avec cet e-mail ou ce téléphone : vérifiez le doublon avant de valider.</div>}
        <div className="mt-2 flex flex-wrap gap-2">{[["active", "Valider (actif)"], ["test", "Valider (en test)"], ["more_info", "Demander un complément"], ["refused", "Refuser"]].map(([k, l]) => <Button key={k} size="sm" variant={k === "active" ? "default" : "outline"} onClick={() => decide(a, k)} data-testid={`network-${k}-${a.id}`}>{l}</Button>)}</div></div>)}
    </div>
  );
}

function Teams() {
  const [teams, load] = useGet("/staff-teams");
  const [prov] = useGet("/providers");
  const [name, setName] = useState("");
  if (!teams || !prov) return null;
  const toggle = (t, id) => api.put(`/staff-teams/${t.id}`, { name: t.name, provider_ids: t.provider_ids.includes(id) ? t.provider_ids.filter((x) => x !== id) : [...t.provider_ids, id] }).then(load).catch(ko);
  return (
    <div className="space-y-4" data-testid="staff-teams">
      <div className="flex gap-2"><Input className="max-w-xs" placeholder="Nom de l'équipe (ex. Techniciens Gard)" value={name} onChange={(e) => setName(e.target.value)} data-testid="team-name" /><Button disabled={!name.trim()} onClick={() => api.post("/staff-teams", { name, provider_ids: [] }).then(() => { setName(""); load(); }).catch(ko)} data-testid="team-add">Créer l'équipe</Button></div>
      {teams.map((t) => <div key={t.id} className="card-soft p-4" data-testid={`team-${t.id}`}><b>{t.name}</b> <span className="text-xs text-muted-foreground">{t.provider_ids.length} membre(s)</span><div className="mt-2 flex flex-wrap gap-1.5">{prov.map((p) => <button key={p.id} onClick={() => toggle(t, p.id)} className={`rounded-full px-3 py-1 text-xs ${t.provider_ids.includes(p.id) ? "bg-primary text-white" : "bg-secondary"}`}>{p.display_name}</button>)}</div></div>)}
    </div>
  );
}

function Hours() {
  const [rows, load] = useGet("/timesheets");
  const [pick, setPick] = useState([]);
  if (!rows) return null;
  const review = (t, action) => { const reason = window.prompt(action === "refuse" ? "Motif du refus (visible par la personne)" : "Motif de la correction, puis saisissez les heures"); if (!reason) return; const end = action === "correct" ? window.prompt("Heure de fin corrigée (HH:MM)", t.end_time) : t.end_time; if (end) api.post(`/timesheets/${t.id}/${action}`, { start_time: t.start_time, end_time: end, break_min: t.break_min, night_hours: t.night_hours, km: t.km, expenses: t.expenses, comment: t.comment, reason }).then(load).catch(ko); };
  return (
    <div data-testid="staff-hours">
      <Button className="mb-3" disabled={!pick.length} onClick={() => api.post("/timesheets/validate", { ids: pick }).then(() => { setPick([]); load(); }).catch(ko)} data-testid="hours-validate">Valider la sélection ({pick.length})</Button>
      <div className="card-soft divide-y divide-border text-sm">{rows.map((t) => <div key={t.id} className="flex flex-wrap items-center gap-3 p-3" data-testid={`hours-row-${t.id}`}>{t.status === "declared" && <input type="checkbox" checked={pick.includes(t.id)} onChange={(e) => setPick(e.target.checked ? [...pick, t.id] : pick.filter((x) => x !== t.id))} data-testid={`hours-pick-${t.id}`} />}
        <div className="min-w-0 flex-1"><b>{t.provider_name}</b> · {fmtDate(t.date)} · {ES[t.employment_status]}<div className="text-xs text-muted-foreground">{t.start_time}–{t.end_time}, pause {t.break_min} min · {t.hours} h (dont {t.overtime_hours} h majorées) · frais {fmtEur(t.amount_expenses)}{t.comment ? ` · ${t.comment}` : ""}{t.review_reason ? ` · motif : ${t.review_reason}` : ""}</div></div>
        <b>{fmtEur(t.total_ht)}</b><span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-semibold">{TS[t.status]}</span>{["declared", "validated"].includes(t.status) && <><Button size="sm" variant="ghost" onClick={() => review(t, "correct")}>Corriger</Button><Button size="sm" variant="ghost" onClick={() => review(t, "refuse")}>Refuser</Button></>}</div>)}</div>
    </div>
  );
}

function Money() {
  const [rows, load] = useGet("/provider-invoices");
  const [p, setP] = useState({ start: "", end: "" });
  if (!rows) return null;
  return (
    <div className="space-y-4" data-testid="staff-money">
      <Section title="Factures reçues des indépendants" actions={<Button size="sm" variant="outline" onClick={() => downloadPdf("/provider-invoices?format=csv", "factures-prestataires.csv")}>Export CSV</Button>}>
        {!rows.length && <p className="text-sm text-muted-foreground">Aucune facture.</p>}
        {rows.map((i) => <div key={i.id} className="flex flex-wrap items-center gap-3 border-b border-border py-2 text-sm last:border-0" data-testid={`pinvoice-${i.id}`}><b>{i.number}</b><span className="flex-1">{i.provider_name} · prestation du {fmtDate(i.service_date)}</span>{Math.abs(i.gap) > 0.01 && <span className="text-xs font-semibold text-amber-700">Écart avec la mission : {fmtEur(i.gap)}</span>}<b>{fmtEur(i.total_ttc)}</b>
          <button className="underline" onClick={() => openFile(i.file)}>PDF</button>{i.status === "paid" ? <span className="text-xs text-emerald-700">Payée le {fmtDate(i.paid_at)}</span> : <Button size="sm" onClick={() => api.post(`/provider-invoices/${i.id}/paid`).then(load).catch(ko)} data-testid={`pinvoice-paid-${i.id}`}>Marquer payée</Button>}</div>)}
      </Section>
      <Section title="Export de paie (intermittents, CDDU)"><p className="mb-2 text-xs text-muted-foreground">Aide à la préparation uniquement : aucune déclaration n'est faite automatiquement. Les heures validées exportées passent à « Transmises en paie ».</p>
        <div className="flex flex-wrap gap-2"><Input type="date" className="w-44" value={p.start} onChange={(e) => setP({ ...p, start: e.target.value })} /><Input type="date" className="w-44" value={p.end} onChange={(e) => setP({ ...p, end: e.target.value })} /><Button onClick={() => downloadPdf(`/payroll-export?start=${p.start}&end=${p.end}`, "export-paie.csv")} data-testid="payroll-export">Exporter (CSV)</Button></div></Section>
    </div>
  );
}

function Plan() {
  const [d] = useGet("/staff/planning");
  const [s] = useGet("/staff/stats");
  if (!d || !s) return null;
  return (
    <div className="space-y-4" data-testid="staff-planning">
      <Section title={`Planning du ${fmtDate(d.start)} au ${fmtDate(d.end)}`}>{!d.rows.length && <p className="text-sm text-muted-foreground">Aucune mission sur la période.</p>}
        {d.rows.map((r) => <div key={r.provider_name} className="border-b border-border py-2 text-sm last:border-0"><b>{r.provider_name}</b> {r.missions.map((m) => <span key={m.id} className="ml-2 rounded bg-secondary px-2 py-0.5 text-xs">{fmtDate(m.date)} {m.start_time}–{m.end_time}</span>)}{r.alerts.map((a) => <div key={a} className="text-xs font-semibold text-red-600" data-testid="planning-alert">{a}</div>)}</div>)}</Section>
      <Section title="Statistiques"><div className="mb-3 flex flex-wrap gap-6 text-sm"><span>Missions : <b>{s.missions}</b></span><span>Coût prévu : <b>{fmtEur(s.cost)}</b></span><span>Indépendants : <b>{s.freelance}</b></span><span>Intermittents : <b>{s.intermittent}</b></span><span>Taux de pourvoi : <b>{s.fill_rate == null ? "—" : `${s.fill_rate} %`}</b></span><span>Désistements : <b>{s.withdrawals}</b></span></div>
        {s.events.map((e) => <div key={e.title} className="flex justify-between border-b border-border py-1 text-sm last:border-0"><span>{e.title}</span><span>prévu {fmtEur(e.planned)} · réel {fmtEur(e.real)}</span></div>)}
        {s.providers.map((x) => <div key={x.name} className="flex justify-between py-1 text-xs text-muted-foreground"><span>{x.name}</span><span>{x.missions} mission(s) · {x.hours} h · payé {fmtEur(x.paid)}</span></div>)}</Section>
    </div>
  );
}

export function StaffTab({ ev }) {
  const [d, load] = useGet(`/events/${ev.id}/positions`);
  const blank = { category_key: "", quantity: 1, date: (ev.start || "").slice(0, 10), start_time: "18:00", end_time: "23:00", break_min: 0, dress: "", brief: "", rate_type: "flat", rate: 0, rate_basis: "ht", visibility: "private", team_id: "" };
  const [f, setF] = useState(blank);
  const [inv, setInv] = useState({});
  if (!d) return null;
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const run = (p, msg) => p.then(() => { if (msg) toast.success(msg); load(); }).catch(ko);
  return (
    <div className="space-y-4" data-testid="staff-tab">
      <Section title="Postes" actions={<span className="text-sm font-semibold" data-testid="positions-summary">{d.summary}</span>}>
        <div className="mb-4 grid grid-cols-2 gap-2 lg:grid-cols-6"><select className={sel} value={f.category_key} onChange={set("category_key")} data-testid="position-category"><option value="">Métier *</option>{Object.entries(d.labels).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select><Input type="number" min="1" title="Nombre" value={f.quantity} onChange={set("quantity")} data-testid="position-quantity" /><Input type="date" value={f.date} onChange={set("date")} /><Input type="time" value={f.start_time} onChange={set("start_time")} /><Input type="time" value={f.end_time} onChange={set("end_time")} /><Input type="number" title="Pause (min)" placeholder="Pause" value={f.break_min} onChange={set("break_min")} />
          <select className={sel} value={f.rate_type} onChange={set("rate_type")}><option value="flat">Forfait</option><option value="hourly">Horaire</option><option value="cachet">Cachet</option></select><Input type="number" placeholder="Tarif" value={f.rate} onChange={set("rate")} data-testid="position-rate" /><select className={sel} value={f.rate_basis} onChange={set("rate_basis")}><option value="ht">HT</option><option value="ttc">TTC</option><option value="brut">Brut</option></select>
          <select className={sel} value={f.visibility} onChange={set("visibility")} data-testid="position-visibility"><option value="private">Privé (invitation)</option><option value="team">Équipe</option><option value="network">Réseau</option></select>{f.visibility === "team" && <select className={sel} value={f.team_id} onChange={set("team_id")} data-testid="position-team"><option value="">Équipe…</option>{d.teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>}
          <Input placeholder="Tenue" value={f.dress} onChange={set("dress")} /><Input className="col-span-2" placeholder="Brief" value={f.brief} onChange={set("brief")} />
          <Button disabled={!f.category_key || !f.date} onClick={() => run(api.post(`/events/${ev.id}/positions`, { ...f, quantity: Number(f.quantity) || 1, break_min: Number(f.break_min) || 0, rate: Number(f.rate) || 0 }).then(() => setF(blank)), "Poste créé")} data-testid="position-add">Ajouter le poste</Button></div>
        {d.positions.map((p) => <div key={p.id} className="mb-3 rounded-2xl border border-border p-3 text-sm" data-testid={`position-${p.id}`}><div className="flex flex-wrap items-center gap-2"><b className="flex-1">{p.quantity} × {p.category} · {fmtDate(p.date)} {p.start_time}–{p.end_time}</b><span className="text-xs text-muted-foreground">{{ private: "Privé", team: "Équipe", network: "Réseau" }[p.visibility]}</span><span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-semibold" data-testid={`position-count-${p.id}`}>{p.label}</span><Button size="sm" variant="ghost" onClick={() => run(api.post(`/positions/${p.id}/duplicate`), "Poste dupliqué")}>Dupliquer</Button></div>
          <div className="mt-2 flex flex-wrap gap-2"><select className={sel} value={inv[p.id] || ""} onChange={(e) => setInv({ ...inv, [p.id]: e.target.value })} data-testid={`position-invite-select-${p.id}`}><option value="">Inviter…</option>{d.teams.map((t) => <option key={t.id} value={`t:${t.id}`}>Équipe {t.name}</option>)}{d.providers.filter((x) => x.categories.includes(p.category_key)).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
            <Button size="sm" variant="outline" disabled={!inv[p.id]} onClick={() => run(api.post(`/positions/${p.id}/invite`, inv[p.id].startsWith("t:") ? { team_id: inv[p.id].slice(2) } : { provider_ids: [inv[p.id]] }).then((r) => toast.success(`${r.data.invited} invitation(s)`)))} data-testid={`position-invite-${p.id}`}>Inviter</Button></div>
          {p.applications.map((a) => <div key={a.id} className="mt-2 flex flex-wrap items-center gap-2 border-t border-border pt-2" data-testid={`application-${a.id}`}><span className="min-w-0 flex-1"><b>{a.provider_name}</b> · {ES[a.employment_status]} · note {a.rating || "—"} · {a.withdrawals} désistement(s){a.counter_rate ? ` · propose ${fmtEur(a.counter_rate)}` : ""}{a.message ? ` · « ${a.message} »` : ""}</span>{a.busy && <span className="text-xs font-semibold text-amber-700">Déjà en mission ce jour</span>}<span className="text-xs font-semibold">{APP[a.status]}</span>
            {["invited", "applied", "shortlisted", "waitlist"].includes(a.status) && [["confirm", "Confirmer"], ["shortlist", "Présélectionner"], ["waitlist", "Liste d'attente"], ["refuse", "Refuser"]].map(([k, l]) => <Button key={k} size="sm" variant={k === "confirm" ? "default" : "ghost"} onClick={() => run(api.post(`/applications/${a.id}/${k}`))} data-testid={`application-${k}-${a.id}`}>{l}</Button>)}</div>)}</div>)}
      </Section>
    </div>
  );
}

export default function StaffAdmin() {
  return (
    <div>
      <PageHeader eyebrow="Équipe" title="Staff & missions" subtitle="Candidatures au réseau, équipes, heures, factures, paie et planning. Les postes se créent dans l'onglet « Staff » de chaque événement." />
      <Tabs defaultValue="network"><TabsList className="mb-5 h-auto flex-wrap">{[["network", "Candidatures au réseau"], ["teams", "Équipes"], ["hours", "Heures"], ["money", "Factures & paie"], ["plan", "Planning & statistiques"]].map(([k, l]) => <TabsTrigger key={k} value={k} data-testid={`staff-tab-${k}`}>{l}</TabsTrigger>)}</TabsList>
        <TabsContent value="network"><Network /></TabsContent><TabsContent value="teams"><Teams /></TabsContent><TabsContent value="hours"><Hours /></TabsContent><TabsContent value="money"><Money /></TabsContent><TabsContent value="plan"><Plan /></TabsContent></Tabs>
    </div>
  );
}
