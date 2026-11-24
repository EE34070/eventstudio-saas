import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { api, errMsg } from "@/lib/api";
import { ConflictDialog, DjGrid, Pill, isHard, useSelection } from "@/components/dj/Conflicts";

const ko = (e) => toast.error(errMsg(e));
const TONE = { none: "bg-red-500/15 text-red-700", option: "bg-amber-500/20 text-amber-700", confirmed: "bg-emerald-500/15 text-emerald-700" };
const LABEL = { none: "Aucun DJ", option: "Option posée", confirmed: "DJ confirmé" };
const STATE = { available: "disponible", available_default: "disponible (par défaut)", maybe: "peut-être", unknown: "non renseigné", option: "option en cours", confirmed: "déjà confirmé ce jour", unavailable: "indisponible" };
const fr = (d) => d.split("-").reverse().join("/");

function AssignPanel({ day, ev, onClose, onDone }) {
  const [rows, setRows] = useState(null);
  const [fee, setFee] = useState("");
  useEffect(() => { api.get("/dj/search", { params: { date: day.date, all: true } }).then((r) => setRows(r.data)).catch(ko); }, [day.date]);
  const taken = Object.fromEntries(day.events.flatMap((e) => e.djs.map((d) => [d.provider_id, e.title])));
  const done = (msg) => () => { toast.success(msg); onDone(); onClose(); };
  const [sel] = useSelection(ev.event_id);
  const [clash, setClash] = useState(null);
  const [freeOnly, setFreeOnly] = useState(false);
  const run = (p, kind, force = {}) => (kind === "direct" ? api.post(`/events/${ev.event_id}/dj/assign`, { provider_id: p.provider_id, fee: Number(fee) || 0, ...force }).then(done(`${p.name} affecté (aucun e-mail envoyé)`))
    : api.post(`/events/${ev.event_id}/dj/options`, { provider_ids: [p.provider_id], proposed_fee: Number(fee) || 0, start_time: ev.start || "18:00", end_time: ev.end || "02:00", ...force }).then(done(`Option posée sur ${p.name}`))).catch(ko);
  const go = (p, kind) => (isHard(sel?.by[p.provider_id]) ? setClash({ p, kind }) : run(p, kind));
  const direct = (p) => go(p, "direct");
  const option = (p) => go(p, "option");
  const list = (rows || []).filter((p) => !freeOnly || !isHard(sel?.by[p.provider_id])).sort((x, y) => isHard(sel?.by[x.provider_id]) - isHard(sel?.by[y.provider_id]));
  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}><SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg" data-testid="dj-assign-panel">
      <SheetHeader><SheetTitle>Affecter un DJ</SheetTitle><SheetDescription>{ev.code} · {ev.title} — {fr(day.date)}{ev.city ? `, ${ev.city}` : ""}</SheetDescription></SheetHeader>
      <label className="mt-4 flex items-center gap-2 text-sm">Cachet proposé (€)<Input className="h-9 w-28" type="number" min="0" value={fee} onChange={(e) => setFee(e.target.value)} data-testid="dj-assign-fee" /></label>
      {freeOnly && <button type="button" className="mt-2 text-xs underline" onClick={() => setFreeOnly(false)}>Afficher aussi les DJ en conflit</button>}
      {clash && sel && <ConflictDialog sel={sel} row={sel.by[clash.p.provider_id]} onCancel={() => setClash(null)} onOther={() => { setClash(null); setFreeOnly(true); }} onForce={(reason) => { run(clash.p, clash.kind, { conflict_override: true, conflict_reason: reason }); setClash(null); }} />}
      <div className="mt-3 divide-y divide-border">{list.map((p, i) => (
        <div key={p.provider_id} className={`flex flex-wrap items-center gap-2 py-2.5 text-sm ${isHard(sel?.by[p.provider_id]) ? "opacity-60" : ""}`} data-testid={`dj-assign-row-${i}`}>
          <span className="min-w-0 flex-1"><b>{p.name}</b> <Pill row={sel?.by[p.provider_id]} /><span className="block text-xs text-muted-foreground">{STATE[p.state] || p.state}{taken[p.provider_id] ? ` · Déjà affecté à ${taken[p.provider_id]}` : ""}</span></span>
          <Button size="sm" variant="outline" onClick={() => option(p)} data-testid={`dj-option-${i}`}>Poser une option</Button><Button size="sm" onClick={() => direct(p)} data-testid={`dj-direct-${i}`}>Affecter directement</Button>
        </div>))}{rows && !rows.length && <p className="py-4 text-sm text-muted-foreground">Aucun DJ partenaire : ajoutez-en un.</p>}</div>
      <p className="mt-3 text-xs text-muted-foreground">« Poser une option » prévient le DJ par e-mail. « Affecter directement » (accord déjà pris) n'envoie rien.</p>
    </SheetContent></Sheet>);
}

function AddDj({ onClose, onDone }) {
  const [f, setF] = useState({ name: "", email: "", phone: "", city: "", base_rate: "", languages: "fr", notes: "" });
  const save = () => api.post("/dj/quick", { ...f, base_rate: Number(f.base_rate) || 0, languages: f.languages.split(/[\s,;]+/).filter(Boolean) }).then((r) => { toast.success(`${r.data.name} ajouté : il est proposé dans « Affecter »`); onDone(); onClose(); }).catch(ko);
  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}><SheetContent side="right" className="w-full sm:max-w-md" data-testid="dj-add-panel">
      <SheetHeader><SheetTitle>Ajouter un DJ</SheetTitle><SheetDescription>Fiche interne : le DJ est affectable tout de suite. Aucun e-mail ne lui est envoyé.</SheetDescription></SheetHeader>
      <div className="mt-4 space-y-3">{[["name", "Nom / nom de scène *"], ["email", "E-mail"], ["phone", "Téléphone"], ["city", "Ville / zone"], ["base_rate", "Cachet de base (€)"], ["languages", "Langues d'animation (fr, en…)"], ["notes", "Notes"]].map(([k, l]) => <label key={k} className="block text-xs text-muted-foreground">{l}<Input className="mt-1 h-9" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} data-testid={`dj-add-${k}`} /></label>)}
        <Button disabled={!f.name.trim()} onClick={save} data-testid="dj-add-save">Ajouter le DJ</Button></div>
    </SheetContent></Sheet>);
}

export function DjPlanning() {
  const [d, setD] = useState(null);
  const [only, setOnly] = useState(false);
  const [range, setRange] = useState({ frm: "", to: "" });
  const [pick, setPick] = useState(null);
  const [add, setAdd] = useState(false);
  const [pending, setPending] = useState(false);
  const [grid, setGrid] = useState(false);
  const load = useCallback(() => api.get("/dj/coverage", { params: { ...range, pending } }).then((r) => setD(r.data)).catch(ko), [range, pending]);
  useEffect(() => { load(); }, [load]);
  if (!d) return null;
  const days = d.days.filter((x) => !only || x.red);
  return (
    <div className="space-y-4" data-testid="dj-planning">
      <div className="flex flex-wrap items-center gap-3 text-sm"><b className={d.without_dj ? "text-red-600" : ""} data-testid="dj-without-count">Prestations DJ sans DJ : {d.without_dj}</b>
        <label className="flex items-center gap-1"><input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} data-testid="dj-filter-none" />Sans DJ uniquement</label>
        <label className="flex items-center gap-1"><input type="checkbox" checked={pending} onChange={(e) => setPending(e.target.checked)} data-testid="dj-filter-pending" />Inclure les devis en cours</label>
        <label className="flex items-center gap-1">Du<Input className="h-9 w-40" type="date" value={range.frm} onChange={(e) => setRange({ ...range, frm: e.target.value })} data-testid="dj-filter-from" /></label><label className="flex items-center gap-1">au<Input className="h-9 w-40" type="date" value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })} data-testid="dj-filter-to" /></label>
        <label className="flex items-center gap-1"><input type="checkbox" checked={grid} onChange={(e) => setGrid(e.target.checked)} data-testid="dj-view-grid" />Vue par DJ</label>
        <span className="flex-1" /><Button size="sm" onClick={() => setAdd(true)} data-testid="dj-add-open">Ajouter un DJ</Button></div>
      {!days.length && <p className="text-sm text-muted-foreground">Aucune prestation DJ sur la période.</p>}
      {grid && <DjGrid days={days} />}
      {!grid && days.map((day) => (
        <div key={day.date} className={`rounded-2xl border p-4 ${day.red ? "border-red-500/50" : "border-border"}`} data-testid={`dj-day-${day.date}`}>
          <div className={`font-semibold ${day.red ? "text-red-600" : ""}`} data-testid={`dj-day-label-${day.date}`}>{day.label}</div>
          {day.conflicts.map((c) => <div key={c} className="mt-1 text-sm font-semibold text-red-600" data-testid={`dj-conflict-${day.date}`}>Conflit DJ : {c}</div>)}
          <div className="mt-2 divide-y divide-border">{day.events.map((e) => (
            <div key={e.event_id} className={`flex flex-wrap items-center gap-2 py-2 text-sm ${e.confirmed ? "" : "opacity-60"}`} data-testid={`dj-event-${e.code}`}>
              <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${e.confirmed || e.djs.length ? TONE[e.coverage] : "bg-secondary text-muted-foreground"}`} data-testid={`dj-coverage-${e.code}`}>{e.confirmed || e.djs.length ? LABEL[e.coverage] : "Devis en cours"}</span>
              <Link className="min-w-0 flex-1" to={`/evenements/${e.event_id}?tab=devis`}><span className="underline">{e.code} · {e.title}</span><span className="block text-xs text-muted-foreground">{[e.city, `${e.start}–${e.end}`, e.language, e.formula].filter(Boolean).join(" · ")}</span></Link>
              <span className="text-xs">{e.djs.map((x) => `${x.name} (${{ confirmed: "confirmé", acknowledged: "accusé de réception" }[x.status] || "option"})`).join(", ")}</span>
              {e.conflict_accepted && <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-xs font-semibold text-amber-700" data-testid={`dj-conflict-accepted-${e.code}`}>Conflit accepté</span>}
              {e.priority !== "normal" && e.coverage === "none" && <span className="text-xs font-semibold text-red-600">{e.priority === "critical" ? "critique" : "priorité haute"} · J-{e.days_left}</span>}
              {e.coverage !== "confirmed" && <Button size="sm" variant="outline" onClick={() => setPick({ day, ev: e })} data-testid={`dj-assign-${e.code}`}>Affecter</Button>}
            </div>))}</div>
        </div>))}
      {pick && <AssignPanel day={pick.day} ev={pick.ev} onClose={() => setPick(null)} onDone={load} />}
      {add && <AddDj onClose={() => setAdd(false)} onDone={load} />}
    </div>);
}

export function DjBanner({ eid }) {
  const [e, setE] = useState(null);
  useEffect(() => { api.get("/dj/coverage", { params: { event_id: eid, frm: "2000-01-01" } }).then((r) => setE(r.data.days[0]?.events[0] || null)).catch(() => {}); }, [eid]);
  if (!e || e.coverage !== "none" || !e.confirmed) return null;
  return <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-red-500/50 bg-red-500/10 p-3 text-sm font-semibold text-red-700" data-testid="event-dj-banner">DJ non affecté pour cette prestation<Link className="underline" to="/dj?tab=planning">Affecter un DJ</Link></div>;
}

let covCache = null;
const covOf = () => { covCache = covCache || api.get("/dj/coverage", { params: { frm: "2000-01-01", pending: true } }).then((r) => Object.fromEntries(r.data.days.flatMap((d) => d.events.map((e) => [e.event_id, e])))).catch(() => ({})); return covCache; };
const stateOf = (e) => (e.djs.length ? e.coverage : e.confirmed ? "none" : e.requests?.length ? "ask" : "");
const TONE2 = { ...TONE, ask: "bg-secondary text-muted-foreground" };
const names = (e) => (e.djs.length ? e.djs : e.requests || []).map((x) => x.name).join(", ");
export function DjDot({ id }) {
  const [e, setE] = useState(null);
  useEffect(() => { let on = true; covOf().then((m) => on && setE(m[id])); return () => { on = false; }; }, [id]);
  const st = e && stateOf(e);
  if (!st) return null;
  return <span title={`DJ : ${LABEL[st] || "disponibilité demandée"}`} className={`ml-1 inline-block rounded-full px-1.5 text-[10px] font-bold ${TONE2[st]}`} data-testid={`dj-dot-${id}`}>DJ{names(e) ? ` ${names(e)}` : ""}</span>;
}

export function DjBadge({ eid, onOpen }) {
  const [e, setE] = useState(null);
  useEffect(() => { covCache = null; api.get("/dj/coverage", { params: { event_id: eid, frm: "2000-01-01", pending: true } }).then((r) => setE(r.data.days[0]?.events[0] || null)).catch(() => {}); }, [eid]);
  const st = e && stateOf(e);
  if (!st) return null;
  const txt = st === "none" ? "Aucun DJ" : st === "ask" ? `${names(e)} — dispo demandée` : `${e.djs.map((x) => `${x.name} — ${["confirmed", "acknowledged"].includes(x.status) ? "Confirmé" : "Option"}`).join(" · ")}${e.required > 1 ? ` (${e.djs.filter((x) => ["confirmed", "acknowledged"].includes(x.status)).length} / ${e.required} DJ affectés)` : ""}${e.conflict_accepted ? " · Conflit accepté" : ""}`;
  return <button type="button" onClick={onOpen} className={`mr-3 rounded-full px-3 py-1 text-xs font-semibold ${TONE2[st]}`} data-testid="event-dj-badge">DJ : {txt}</button>;
}

export function DjQuoteBox({ quoteId }) {
  const [d, setD] = useState(null);
  const [pick, setPick] = useState(null);
  const [sel] = useSelection(d?.event_id);
  const load = useCallback(() => api.get(`/quotes/${quoteId}/dj-status`).then((r) => setD(r.data)).catch(() => {}), [quoteId]);
  useEffect(() => { load(); }, [load]);
  if (!d?.has_dj) return null;
  const R = { availability_requested: "en attente", available: "disponible", not_available: "indisponible" };
  const head = d.options.length ? `Option posée : ${d.options.map((x) => x.name).join(", ")}` : d.free ? `DJ à trouver — ${d.free} DJ disponible(s) le ${fr(d.date)}` : `Aucun DJ disponible le ${fr(d.date)}`;
  return (
    <div className={`rounded-xl border p-3 text-sm ${d.free || d.options.length ? "border-sky-500/40 bg-sky-500/10" : "border-amber-500/50 bg-amber-500/10"}`} data-testid="quote-dj-box">
      <div className="font-semibold" data-testid="quote-dj-head">{head} <span className="text-xs font-normal text-muted-foreground">(interne, jamais montré au client)</span></div>
      <div className="text-xs text-muted-foreground">Ce jour-là : {d.confirmed_count} prestation(s) DJ confirmée(s), {d.pending_count} devis DJ en cours, {d.free} DJ libre(s).</div>
      {d.requests.map((r) => <div key={r.booking_id} className="mt-1 flex flex-wrap items-center gap-2 text-xs" data-testid={`quote-dj-request-${r.name}`}>Disponibilité demandée à <b>{r.name}</b> — {R[r.status]}
        {r.status === "availability_requested" && <>{[[true, "il a répondu oui"], [false, "il a répondu non"]].map(([v, l]) => <button key={l} type="button" className="underline" onClick={() => api.put(`/dj/requests/${r.booking_id}`, { available: v }).then(load).catch(ko)}>{l}</button>)}<button type="button" className="underline" onClick={() => api.get(`/dj/requests/${r.booking_id}/link`).then((x) => navigator.clipboard.writeText(window.location.origin + x.data.path)).then(() => toast.success("Lien de réponse copié : envoyez-le au DJ")).catch(ko)} data-testid={`quote-dj-link-${r.name}`}>copier son lien de réponse</button></>}</div>)}
      {pick ? <div className="mt-2" data-testid="quote-dj-ask-list">{d.djs.map((p) => <label key={p.provider_id} className="mr-3 inline-flex items-center gap-1 text-xs"><input type="checkbox" checked={pick.includes(p.provider_id)} onChange={(e) => setPick(e.target.checked ? [...pick, p.provider_id] : pick.filter((x) => x !== p.provider_id))} />{p.name} <Pill row={sel?.by[p.provider_id]} />{p.reserved && !sel ? " (sous réserve)" : ""}</label>)}
        <Button type="button" size="sm" disabled={!pick.length} onClick={() => api.post(`/quotes/${quoteId}/dj/ask`, { provider_ids: pick }).then((r) => { setD(r.data); setPick(null); toast.success("Disponibilité demandée"); }).catch(ko)} data-testid="quote-dj-ask-send">Demander</Button></div>
        : <div className="mt-2 flex gap-3 text-xs"><button type="button" className="underline" onClick={() => setPick([])} data-testid="quote-dj-ask">Voir les DJ disponibles / demander la disponibilité</button><Link className="underline" to="/dj?tab=planning">Poser une option (Planning DJ)</Link></div>}
    </div>);
}
