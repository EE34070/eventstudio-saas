import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Field, Loading, PageHeader } from "@/components/common";
import { api, errMsg, downloadPdf } from "@/lib/api";
import { EVENT_TYPES, fmtDate, fmtEur } from "@/lib/constants";

const sel = "h-10 w-full rounded-lg border border-border bg-background px-3 text-sm";
const LOST = { prix: "Prix", date_indisponible: "Date indisponible", concurrent: "Concurrent", sans_reponse: "Sans réponse", projet_annule: "Projet annulé", autre: "Autre" };
const money = (o) => `${fmtEur(o.amount)} ${o.amount_tax_mode.toUpperCase()}`;

function OppDialog({ open, onOpenChange, cfg, onSaved }) {
  const [f, setF] = useState({ client_contact_id: "", event_type: "Mariage", event_date: "", city: "", guest_count: 0, services: [], source_key: "autre", amount: 0, amount_tax_mode: "ttc", next_action: "Répondre à la demande", next_action_date: "", notes: "" });
  const [contacts, setContacts] = useState([]);
  useEffect(() => { if (open) api.get("/contacts?type=client").then((r) => setContacts(r.data)); }, [open]);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const save = async (force) => {
    try { const r = await api.post("/crm/opportunities", { ...f, guest_count: Number(f.guest_count) || 0, amount: Number(f.amount) || 0, force }); toast.success("Opportunité créée"); onSaved(r.data); onOpenChange(false); }
    catch (e) { const d = e.response?.data?.detail; if (d?.opportunity_id) { if (window.confirm("Une opportunité existe déjà pour ce client à cette date : l'ouvrir ? (Annuler = créer quand même)")) { onSaved({ id: d.opportunity_id }); onOpenChange(false); } else save(true); } else toast.error(errMsg(e)); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto" data-testid="opp-dialog">
      <DialogHeader><DialogTitle className="text-xl font-bold">Nouvelle opportunité</DialogTitle></DialogHeader>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Client *" className="col-span-2"><select className={sel} value={f.client_contact_id} onChange={set("client_contact_id")} data-testid="opp-client"><option value="">— Choisir —</option>{contacts.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}</select></Field>
        <Field label="Type"><select className={sel} value={f.event_type} onChange={set("event_type")} data-testid="opp-type">{EVENT_TYPES.map((t) => <option key={t}>{t}</option>)}</select></Field>
        <Field label="Date de l'événement (vide = non fixée)"><Input type="date" value={f.event_date} onChange={set("event_date")} data-testid="opp-date" /></Field>
        <Field label="Ville"><Input value={f.city} onChange={set("city")} data-testid="opp-city" /></Field>
        <Field label="Invités"><Input type="number" value={f.guest_count} onChange={set("guest_count")} /></Field>
        <Field label="Source"><select className={sel} value={f.source_key} onChange={set("source_key")} data-testid="opp-source">{cfg.sources.filter((s) => s.active).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</select></Field>
        <Field label="Montant estimé (€)"><div className="flex gap-2"><Input type="number" value={f.amount} onChange={set("amount")} data-testid="opp-amount" /><select className={`${sel} w-24`} value={f.amount_tax_mode} onChange={set("amount_tax_mode")}><option value="ttc">TTC</option><option value="ht">HT</option></select></div></Field>
        <div className="col-span-2 flex flex-wrap gap-2">{cfg.modules.map((m) => { const on = f.services.includes(m.key); return <button key={m.key} type="button" aria-pressed={on} onClick={() => setF({ ...f, services: on ? f.services.filter((k) => k !== m.key) : [...f.services, m.key] })} className={`h-8 rounded-full border px-3 text-xs font-medium ${on ? "border-primary bg-primary text-white" : "border-border"}`}>{m.label}</button>; })}</div>
        <Field label="Prochaine action *"><Input value={f.next_action} onChange={set("next_action")} data-testid="opp-next-action" /></Field>
        <Field label="Échéance (défaut : aujourd'hui)"><Input type="date" value={f.next_action_date} onChange={set("next_action_date")} /></Field>
        <Field label="Notes" className="col-span-2"><Textarea rows={2} value={f.notes} onChange={set("notes")} /></Field>
      </div>
      <DialogFooter><Button disabled={!f.client_contact_id} onClick={() => save(false)} data-testid="opp-save">Créer</Button></DialogFooter>
    </DialogContent></Dialog>
  );
}

function OppSheet({ id, cfg, onClose, onChanged }) {
  const [o, setO] = useState(null);
  const [note, setNote] = useState({ type: "note", body: "" });
  const [fu, setFu] = useState(null);
  const [ai, setAi] = useState("");
  const [lost, setLost] = useState(null);
  const load = useCallback(() => { if (id) api.get(`/crm/opportunities/${id}`).then((r) => setO(r.data)).catch((e) => toast.error(errMsg(e))); }, [id]);
  useEffect(() => { setO(null); setFu(null); setAi(""); setLost(null); load(); }, [load]);
  const run = async (fn, msg) => { try { await fn(); if (msg) toast.success(msg); load(); onChanged(); } catch (e) { toast.error(errMsg(e)); } };
  const stage = (k) => (cfg.stages.find((s) => s.key === k)?.is_lost ? setLost({ lost_reason: "prix", lost_comment: "" }) : run(() => api.patch(`/crm/opportunities/${id}`, { stage_key: k })));
  return (
    <Sheet open={!!id} onOpenChange={(v) => !v && onClose()}><SheetContent className="w-full overflow-y-auto sm:max-w-xl">
      <SheetHeader><SheetTitle className="text-xl font-bold">{o?.title || "…"}</SheetTitle></SheetHeader>
      {o && <div className="mt-4 space-y-5 text-sm" data-testid="opp-sheet">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Étape"><select className={sel} value={o.stage_key} onChange={(e) => stage(e.target.value)} data-testid="opp-stage-select">{cfg.stages.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</select></Field>
          <div><div className="eyebrow">Montant · probabilité</div><div className="font-semibold" data-testid="opp-amount-line">{money(o)} · {o.probability} % · pondéré {fmtEur(o.weighted_amount)}</div></div>
        </div>
        {lost && <div className="rounded-xl border border-border p-3" data-testid="opp-lost-form"><select className={sel} value={lost.lost_reason} onChange={(e) => setLost({ ...lost, lost_reason: e.target.value })} data-testid="opp-lost-reason">{Object.entries(LOST).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          <Input className="mt-2" placeholder="Commentaire" value={lost.lost_comment} onChange={(e) => setLost({ ...lost, lost_comment: e.target.value })} /><Button size="sm" className="mt-2" onClick={() => run(() => api.patch(`/crm/opportunities/${id}`, { stage_key: "perdue", ...lost }), "Opportunité perdue").then(() => setLost(null))} data-testid="opp-lost-confirm">Confirmer la perte</Button></div>}
        {o.open && <div className="rounded-xl bg-secondary p-3" data-testid="opp-next"><b className={o.overdue ? "text-red-600" : ""}>{o.next_action}</b> — {fmtDate(o.next_action_date)}
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => run(() => api.post(`/crm/opportunities/${id}/postpone`, { days: 0, done: true }), "Action faite")} data-testid="opp-done">Fait</Button>
            {[[1, "+1 j"], [3, "+3 j"], [7, "+1 sem."]].map(([d, l]) => <Button key={d} size="sm" variant="outline" onClick={() => run(() => api.post(`/crm/opportunities/${id}/postpone`, { days: d }), "Reporté")} data-testid={`opp-postpone-${d}`}>{l}</Button>)}
            <Button size="sm" variant="outline" onClick={() => api.get(`/crm/opportunities/${id}/followup`).then((r) => setFu(r.data))} data-testid="opp-followup">Relancer</Button>
          </div></div>}
        {fu && <div className="rounded-xl border border-border p-3" data-testid="opp-followup-form"><div className="text-xs text-muted-foreground">À : {fu.to || "pas d'e-mail"} · langue {fu.language}</div>
          <Input className="mt-2" value={fu.subject} onChange={(e) => setFu({ ...fu, subject: e.target.value })} /><Textarea className="mt-2" rows={7} value={fu.body} onChange={(e) => setFu({ ...fu, body: e.target.value })} />
          <div className="mt-2 flex gap-2"><Button size="sm" disabled={!fu.to} onClick={() => run(() => api.post(`/crm/opportunities/${id}/followup`, fu), "Relance envoyée").then(() => setFu(null))} data-testid="opp-followup-send">Envoyer par Gmail</Button>
            <Button size="sm" variant="outline" onClick={() => navigator.clipboard.writeText(fu.body).then(() => toast.success("Message copié"))}>Copier le message</Button></div></div>}
        <div><div className="eyebrow mb-1">Contacts</div>{o.contacts.map((c) => <div key={c.id}>{c.role} : <b>{c.display_name}</b> {[c.phone, c.email].filter(Boolean).join(" · ")}</div>)}{o.venue_name && <div>Lieu : {o.venue_name}</div>}
          <div className="text-muted-foreground">{[o.event_type, o.event_date ? fmtDate(o.event_date) : "date non fixée", o.city, o.guest_count ? `${o.guest_count} invités` : ""].filter(Boolean).join(" · ")}{o.date_taken && <b className="ml-2 text-amber-600">Date déjà prise</b>}</div></div>
        <div data-testid="opp-quotes"><div className="eyebrow mb-1">Devis</div>{o.quotes.map((q) => <div key={q.id}>{q.number} · {q.status} · {fmtEur(q.total_ttc)} TTC</div>)}
          <div className="mt-1 flex flex-wrap gap-3"><Link className="font-semibold underline" to={`/devis-factures?new=1&client=${o.client_contact_id}&opp=${o.id}`} data-testid="opp-new-quote">+ Créer un devis</Link>
            {o.stage_key !== "gagnee" ? <button className="font-semibold underline" onClick={() => run(() => api.post(`/crm/opportunities/${id}/win`, {}), "Gagnée : événement créé et lié")} data-testid="opp-win">Marquer gagnée et créer l'événement</button> : o.event_id && <Link className="font-semibold underline" to={`/evenements/${o.event_id}`} data-testid="opp-event-link">Voir l'événement</Link>}</div></div>
        <div><Button size="sm" variant="outline" onClick={() => api.post(`/crm/opportunities/${id}/summary`).then((r) => setAi(r.data.summary)).catch((e) => toast.error(errMsg(e)))} data-testid="opp-ai-summary">Résumer avec l'IA</Button>{ai && <p className="mt-2 whitespace-pre-wrap rounded-xl bg-secondary p-3">{ai}</p>}</div>
        <div><div className="eyebrow mb-1">Tâches</div>{o.tasks.map((t) => <label key={t.id} className="flex items-center gap-2 py-0.5"><input type="checkbox" checked={t.done} onChange={() => run(() => api.patch(`/crm/tasks/${t.id}`, { title: t.title, due_date: t.due_date, done: !t.done }))} />{t.title} — {fmtDate(t.due_date)}</label>)}</div>
        <div><div className="eyebrow mb-1">Historique</div>
          <div className="mb-2 flex gap-2"><select className={`${sel} w-32`} value={note.type} onChange={(e) => setNote({ ...note, type: e.target.value })}><option value="note">Note</option><option value="call">Appel</option><option value="meeting">Rendez-vous</option><option value="whatsapp">WhatsApp</option></select>
            <Input value={note.body} onChange={(e) => setNote({ ...note, body: e.target.value })} placeholder="Résumé…" data-testid="opp-note-input" /><Button disabled={!note.body} onClick={() => run(() => api.post(`/crm/opportunities/${id}/activities`, note)).then(() => setNote({ type: "note", body: "" }))} data-testid="opp-note-add">Ajouter</Button></div>
          <div data-testid="opp-timeline">{o.timeline.map((t, i) => <div key={i} className="border-b border-border py-2 last:border-0"><div>{t.body}</div><div className="text-xs text-muted-foreground">{t.type} · {t.by} · {fmtDate(t.at)}</div></div>)}</div></div>
      </div>}
    </SheetContent></Sheet>
  );
}

export default function Crm() {
  const [sp, setSp] = useSearchParams();
  const [cfg, setCfg] = useState(null);
  const [rows, setRows] = useState(null);
  const [dash, setDash] = useState(null);
  const [view, setView] = useState("kanban");
  const [q, setQ] = useState("");
  const [dlg, setDlg] = useState(false);
  const load = useCallback(() => { api.get("/crm/opportunities").then((r) => setRows(r.data)); api.get("/crm/dashboard").then((r) => setDash(r.data)); }, []);
  useEffect(() => { api.get("/crm/config").then((r) => setCfg(r.data)); load(); }, [load]);
  useEffect(() => { const h = (e) => { if (e.key.toLowerCase() === "n" && !/INPUT|TEXTAREA|SELECT/.test(e.target.tagName) && !e.ctrlKey && !e.metaKey) setDlg(true); }; window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h); }, []);
  if (!cfg || !rows) return <Loading />;
  const shown = rows.filter((o) => !q || `${o.title} ${o.client_name} ${o.organizer_name} ${o.city}`.toLowerCase().includes(q.toLowerCase()));
  const drop = async (id, key) => {
    const o = rows.find((x) => x.id === id);
    if (!o || o.stage_key === key) return;
    if (cfg.stages.find((s) => s.key === key)?.is_lost) return setSp({ id });
    setRows(rows.map((x) => (x.id === id ? { ...x, stage_key: key } : x)));
    try { await api.patch(`/crm/opportunities/${id}`, { stage_key: key }); } catch (e) { toast.error(errMsg(e)); }
    load();
  };
  const Card = ({ o }) => (
    <div draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", o.id)} onClick={() => setSp({ id: o.id })} className="cursor-pointer rounded-xl border border-border bg-card p-3 text-sm hover:shadow-md" data-testid={`opp-card-${o.id}`}>
      <div className="font-semibold">{o.title}</div><div className="text-xs text-muted-foreground">{[o.client_name, o.organizer_name].filter(Boolean).join(" · ")}</div>
      <div className="mt-1 flex justify-between text-xs"><span>{o.event_date ? fmtDate(o.event_date) : "date non fixée"}</span><b>{money(o)}</b></div>
      {o.open && <div className={`mt-1 text-xs ${o.overdue ? "font-semibold text-red-600" : "text-muted-foreground"}`}>{o.overdue && "En retard · "}{o.next_action} — {fmtDate(o.next_action_date)}</div>}
      {o.date_taken && <div className="mt-1 text-xs font-semibold text-amber-600">Date déjà prise</div>}
    </div>
  );
  const today = new Date().toISOString().slice(0, 10);
  return (
    <div>
      <PageHeader title="CRM" subtitle="Pipeline commercial : de la première demande à la signature." actions={<><Button variant="outline" onClick={() => downloadPdf("/crm/opportunities/export.csv", "opportunites.csv")} data-testid="crm-export">Export CSV</Button><Button onClick={() => setDlg(true)} data-testid="crm-new"><Plus />Nouvelle opportunité</Button></>} />
      {dash && <details open className="card-soft mb-5 p-4 text-sm" data-testid="crm-dashboard"><summary className="cursor-pointer font-semibold">Tableau de bord</summary>
        <div className="mt-3 grid grid-cols-2 gap-4 lg:grid-cols-5">
          <div><div className="eyebrow">Pipeline ouvert</div><b>{dash.open.count}</b> · {fmtEur(dash.open.total)} · pondéré {fmtEur(dash.open.weighted)}</div>
          <div><div className="eyebrow">Gagné / perdu</div><b>{dash.won.count}</b> ({fmtEur(dash.won.total)}) / {dash.lost.count} · transformation {dash.conversion_rate ?? "—"} %</div>
          <div><div className="eyebrow">Par source</div>{dash.by_source.map((s) => <div key={s.key}>{s.key} : {s.rate} %</div>)}</div>
          <div><div className="eyebrow">Délais</div>1re réponse : {dash.avg_first_response_h ?? "—"} h<br />Demande → signature : {dash.avg_days_to_win ?? "—"} j</div>
          <div><div className="eyebrow">Pertes · prévision</div>{Object.entries(dash.lost_reasons).map(([k, n]) => <div key={k}>{LOST[k]} : {n}</div>)}{Object.entries(dash.forecast).map(([m, v]) => <div key={m}>{m} : {fmtEur(v)}</div>)}</div>
        </div></details>}
      <div className="mb-4 flex flex-wrap items-center gap-3"><Input className="max-w-xs" placeholder="Rechercher…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="crm-search" />
        <div className="flex rounded-full border border-border p-1">{[["kanban", "Kanban"], ["liste", "Liste"], ["todo", "À faire aujourd'hui"], ["calendrier", "Calendrier"]].map(([k, l]) => <button key={k} onClick={() => setView(k)} data-testid={`crm-view-${k}`} className={`rounded-full px-4 py-1.5 text-xs font-semibold ${view === k ? "bg-foreground text-background" : "text-muted-foreground"}`}>{l}</button>)}</div></div>
      {view === "kanban" && <div className="flex gap-3 overflow-x-auto pb-4" data-testid="crm-kanban">{cfg.stages.filter((s) => s.active).map((s) => { const col = shown.filter((o) => o.stage_key === s.key); return (
        <div key={s.key} onDragOver={(e) => e.preventDefault()} onDrop={(e) => drop(e.dataTransfer.getData("text/plain"), s.key)} className="w-64 shrink-0 rounded-2xl bg-secondary p-2" data-testid={`crm-col-${s.key}`}>
          <div className="px-1 pb-2 text-xs font-semibold">{s.label} <span className="font-normal text-muted-foreground">· {col.length} · {fmtEur(col.reduce((n, o) => n + o.amount, 0))}</span></div>
          <div className="space-y-2">{col.map((o) => <Card key={o.id} o={o} />)}</div></div>); })}</div>}
      {view !== "kanban" && <div className="card-soft divide-y divide-border" data-testid={`crm-${view}`}>
        {(view === "todo" ? shown.filter((o) => o.open && o.next_action_date <= today) : view === "calendrier" ? shown.filter((o) => o.open && o.event_date).sort((a, b) => a.event_date.localeCompare(b.event_date)) : shown).map((o) => (
          <button key={o.id} onClick={() => setSp({ id: o.id })} className="flex w-full flex-wrap items-center gap-3 p-3 text-left text-sm hover:bg-secondary" data-testid={`opp-row-${o.id}`}>
            {view === "calendrier" && <b className="w-28">{fmtDate(o.event_date)}</b>}<span className="min-w-0 flex-1 truncate font-medium">{o.title}</span><span className="text-xs text-muted-foreground">{cfg.stages.find((s) => s.key === o.stage_key)?.label} · {o.source_key}</span>
            <span className={`text-xs ${o.overdue ? "font-semibold text-red-600" : ""}`}>{o.open ? `${o.next_action} — ${fmtDate(o.next_action_date)}` : ""}</span>{o.date_taken && <span className="text-xs font-semibold text-amber-600">Date déjà prise</span>}<b>{money(o)}</b></button>))}
      </div>}
      <OppDialog open={dlg} onOpenChange={setDlg} cfg={cfg} onSaved={(o) => { load(); setSp({ id: o.id }); }} />
      <OppSheet id={sp.get("id")} cfg={cfg} onClose={() => setSp({})} onChanged={load} />
    </div>
  );
}
