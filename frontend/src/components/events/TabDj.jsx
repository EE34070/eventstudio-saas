import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Mail, Phone } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, errMsg } from "@/lib/api";
import { ConflictDialog, isHard, useSelection } from "@/components/dj/Conflicts";

const ko = (e) => toast.error(errMsg(e));
const ST = { option_requested: "Option demandée", option_accepted: "Option acceptée", option_refused: "Option refusée", option_conditions: "Sous conditions", confirmed: "Confirmé", acknowledged: "Confirmé (accusé reçu)", done: "Réalisée", invoiced: "Facturée", paid: "Payée", option_lifted: "Option levée", cancelled: "Annulé", availability_requested: "Dispo demandée", available: "Disponible", not_available: "Pas disponible", extended: "Option prolongée", release_message: "Message de libération", release: "Libéré", conflict_forced: "Conflit accepté" };
const TONE = { confirmed: "bg-emerald-500/15 text-emerald-700", acknowledged: "bg-emerald-500/15 text-emerald-700", option_requested: "bg-amber-500/20 text-amber-700", option_accepted: "bg-amber-500/20 text-amber-700", option_conditions: "bg-amber-500/20 text-amber-700" };
const OPEN = ["option_requested", "option_accepted", "option_conditions"];
const DONE = ["confirmed", "acknowledged"];
const ASK = ["availability_requested", "available", "not_available"];

export function TabDj({ ev }) {
  const [d, setD] = useState(null);
  const [swap, setSwap] = useState(null);
  const [past, setPast] = useState(false);
  const [sel] = useSelection(ev.id);
  const [clash, setClash] = useState(null);
  const MARK = { free: "✓ libre", tentative: "ⓘ sous réserve", probable: "⚠ conflit probable", blocking: "⛔ conflit", unavailable: "⛔ indisponible" };
  const doSwap = (b, force = {}) => act(api.post(`/dj/replace/${b.id}`, { provider_id: swap.provider_id, reason: swap.reason, ...force }), "DJ remplacé (aucun e-mail envoyé depuis l'aperçu)");
  const [msg, setMsg] = useState(null);
  const draftMsg = (b, mode) => api.get(`/dj/bookings/${b.id}/release-draft`).then((r) => setMsg({ id: b.id, mode, ...r.data })).catch(ko);
  const sendMsg = () => act(msg.mode === "lift" ? api.post(`/dj/bookings/${msg.id}/lift`, { subject: msg.subject, body: msg.body }) : api.post(`/dj/bookings/${msg.id}/release-message`, { subject: msg.subject, body: msg.body }), "Message enregistré (envoyé uniquement en production)").then(() => setMsg(null));
  const load = useCallback(() => api.get(`/events/${ev.id}/dj`).then((r) => setD(r.data)).catch(() => setD(false)), [ev.id]);
  useEffect(() => { load(); }, [load]);
  if (!d) return null;
  const act = (p, m) => p.then(() => { toast.success(m); setSwap(null); load(); }).catch(ko);
  const openSwap = (b) => api.get("/dj/search", { params: { date: d.date, all: true } }).then((r) => setSwap({ id: b.id, rows: r.data.filter((x) => x.provider_id !== b.provider_id), provider_id: "", reason: "" })).catch(ko);
  const cancel = (b) => { const reason = window.prompt("Motif de l'annulation (le DJ est libéré à cette date)"); if (reason) act(api.post(`/dj/bookings/${b.id}/cancel`, { reason }), "Prestation DJ annulée"); };
  const live = d.bookings.filter((b) => [...OPEN, ...DONE, ...ASK].includes(b.status));
  const old = d.bookings.filter((b) => !live.includes(b) && !b.release_pending);
  const pend = d.bookings.filter((b) => b.release_pending);
  const card = (b) => { const c = d.contacts?.[b.provider_id] || {}; return (
    <div key={b.id} className="rounded-2xl border border-border p-4 text-sm" data-testid={`dj-card-${b.id}`}>
      <div className="flex flex-wrap items-center gap-2"><b className="text-base" data-testid={`dj-card-name-${b.id}`}>{b.provider_name}</b><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${TONE[b.status] || "bg-secondary text-muted-foreground"}`} data-testid={`dj-card-status-${b.id}`}>{ST[b.status] || b.status}</span><span className="flex-1" />
        {[...OPEN, ...DONE].includes(b.status) && <Button size="sm" variant="outline" onClick={() => openSwap(b)} data-testid={`dj-card-change-${b.id}`}>Changer de DJ</Button>}
        {DONE.includes(b.status) && <Button size="sm" variant="destructive" onClick={() => cancel(b)} data-testid={`dj-card-cancel-${b.id}`}>Annuler</Button>}
        {OPEN.includes(b.status) && <Button size="sm" variant="outline" onClick={() => draftMsg(b, "lift")} data-testid={`dj-card-lift-${b.id}`}>Lever l'option</Button>}
        {b.release_pending && <Button size="sm" onClick={() => draftMsg(b, "release")} data-testid={`dj-card-release-${b.id}`}>Message de libération</Button>}
        {b.status === "availability_requested" && [[true, "Il a répondu oui"], [false, "Il a répondu non"]].map(([v, l]) => <Button key={l} size="sm" variant="outline" onClick={() => act(api.put(`/dj/requests/${b.id}`, { available: v }), "Réponse enregistrée")}>{l}</Button>)}</div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-muted-foreground">
        <span data-testid={`dj-card-hours-${b.id}`}>{b.date.split("-").reverse().join("/")} · {b.start_time}–{b.end_time}</span>
        <span data-testid={`dj-card-fee-${b.id}`}>Cachet : {b.proposed_fee ? `${b.proposed_fee} € ${(b.fee_tax_mode || "").toUpperCase()}` : "non renseigné"}{b.travel_fee ? ` + ${b.travel_fee} € déplacement` : ""}</span>
        {c.phone && <a className="flex items-center gap-1 underline" href={`tel:${c.phone}`} data-testid={`dj-card-phone-${b.id}`}><Phone className="h-3.5 w-3.5" />{c.phone}</a>}
        {c.email && <a className="flex items-center gap-1 underline" href={`mailto:${c.email}`} data-testid={`dj-card-email-${b.id}`}><Mail className="h-3.5 w-3.5" />{c.email}</a>}
        {!c.phone && !c.email && <span>Coordonnées non renseignées</span>}</div>
      {b.conflict_override && <p className="mt-1 text-xs font-semibold text-amber-600" data-testid={`dj-card-conflict-${b.id}`}>Conflit accepté — {b.conflict_reason}</p>}
      {b.dj_comment && <p className="mt-1 text-xs">« {b.dj_comment} »</p>}
      {b.cancel_reason && <p className="mt-1 text-xs text-muted-foreground">Motif : {b.cancel_reason}</p>}
      {b.release_pending && <p className="mt-1 text-xs font-semibold text-amber-600">Devis refusé ou expiré : ce DJ n'a pas encore été prévenu qu'il est libre.</p>}
      {msg?.id === b.id && <div className="mt-3 space-y-2 rounded-xl bg-secondary/50 p-3" data-testid="dj-release-form"><b>{msg.mode === "lift" ? "Lever l'option et prévenir" : "Prévenir"} {msg.to || "(pas d'e-mail renseigné)"}</b>
        <Input value={msg.subject} onChange={(e) => setMsg({ ...msg, subject: e.target.value })} data-testid="dj-release-subject" /><textarea className="w-full rounded-xl border border-border bg-background p-2" rows={6} value={msg.body} onChange={(e) => setMsg({ ...msg, body: e.target.value })} data-testid="dj-release-body" />
        <div className="flex gap-2"><Button size="sm" disabled={!msg.subject.trim() || !msg.body.trim()} onClick={sendMsg} data-testid="dj-release-send">{msg.mode === "lift" ? "Lever l'option et envoyer" : "Envoyer"}</Button><Button size="sm" variant="ghost" onClick={() => setMsg(null)}>Fermer</Button></div></div>}
      {swap?.id === b.id && <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-secondary/50 p-3" data-testid="dj-swap-form">
        <select className="h-9 rounded-lg border border-border bg-background px-2 text-sm" value={swap.provider_id} onChange={(e) => setSwap({ ...swap, provider_id: e.target.value })} data-testid="dj-swap-select"><option value="">Remplacer par…</option>{swap.rows.map((r) => <option key={r.provider_id} value={r.provider_id}>{r.name} — {MARK[sel?.by[r.provider_id]?.level] || r.state}</option>)}</select>
        <Input className="h-9 w-64" placeholder="Motif (facultatif)" value={swap.reason} onChange={(e) => setSwap({ ...swap, reason: e.target.value })} data-testid="dj-swap-reason" />
        <Button size="sm" disabled={!swap.provider_id} onClick={() => (isHard(sel?.by[swap.provider_id]) ? setClash(b) : doSwap(b))} data-testid="dj-swap-save">Remplacer</Button><Button size="sm" variant="ghost" onClick={() => setSwap(null)}>Fermer</Button></div>}
    </div>); };
  return (
    <div className="space-y-3" data-testid="event-dj-tab">
      {clash && sel && <ConflictDialog sel={sel} row={sel.by[swap.provider_id]} onCancel={() => setClash(null)} onOther={() => { setClash(null); setSwap({ ...swap, provider_id: "", rows: swap.rows.filter((r) => !isHard(sel.by[r.provider_id])) }); }} onForce={(reason) => { doSwap(clash, { conflict_override: true, conflict_reason: reason }); setClash(null); }} />}
      {!live.length && <p className="rounded-2xl border border-dashed border-border p-4 text-sm text-muted-foreground" data-testid="dj-tab-empty">Aucun DJ sur cet événement pour l'instant. <Link className="underline" to="/dj?tab=planning">Affecter un DJ depuis le Planning DJ</Link>, ou utilisez « Trouver le DJ » ci-dessous.</p>}
      <label className="flex items-center gap-2 text-sm" data-testid="dj-show-client-label"><input type="checkbox" checked={d.show_client} onChange={(e) => act(api.put(`/events/${ev.id}/dj/show-client`, { show: e.target.checked }), e.target.checked ? "Le client verra le nom du DJ une fois confirmé" : "Nom du DJ masqué au client")} data-testid="dj-show-client" />Afficher le DJ au client <span className="text-xs text-muted-foreground">(son nom apparaît dans l'espace client seulement après confirmation)</span></label>
      {live.map(card)}{pend.map(card)}
      {old.length > 0 && <div><button type="button" className="text-sm underline" onClick={() => setPast(!past)} data-testid="dj-tab-past-toggle">Anciennes affectations ({old.length})</button>{past && <div className="mt-2 space-y-3 opacity-70">{old.map(card)}</div>}</div>}
      {d.log.length > 0 && <div className="rounded-2xl border border-border p-4 text-sm" data-testid="dj-tab-history"><b>Historique</b><div className="mt-2 space-y-1 text-xs text-muted-foreground">{d.log.map((l) => <div key={l.id}>{l.at.slice(0, 16).replace("T", " ")} · <b>{d.bookings.find((b) => b.id === l.booking_id)?.provider_name || ""}</b> · {ST[l.action] || l.action}{l.by ? ` · ${l.by}` : ""}{l.detail ? ` — ${l.detail}` : ""}</div>)}</div></div>}
    </div>);
}
