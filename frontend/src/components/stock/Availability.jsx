import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { AlertTriangle, Truck, MapPin, Send, RefreshCw, Boxes } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Field, Section } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { fmtDate } from "@/lib/constants";

const ko = (e) => toast.error(errMsg(e));
export const TONE = { green: "border-emerald-500/40 bg-emerald-500/10", orange: "border-amber-500/50 bg-amber-500/10", red: "border-red-500/50 bg-red-500/10" };
export const DOT = { green: "bg-emerald-500", orange: "bg-amber-500", red: "bg-red-600" };
const Q_ST = { brouillon: "brouillon", envoye: "envoyé, non signé" };
const Ful = ({ f }) => f === "on_site"
  ? <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 dark:text-emerald-300"><MapPin className="mr-1 inline h-3 w-3" />Sur place</span>
  : <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-semibold text-amber-700 dark:text-amber-300"><Truck className="mr-1 inline h-3 w-3" />À livrer</span>;

export function ReminderDialog({ quoteId, onClose, onSent }) {
  const [d, setD] = useState(null);
  const [f, setF] = useState({ subject: "", body: "", deadline: "", set_deadline: true });
  useEffect(() => { setD(null); if (quoteId) api.get(`/quotes/${quoteId}/urgent-reminder`).then((r) => { setD(r.data); setF({ subject: r.data.subject, body: r.data.body, deadline: r.data.deadline, set_deadline: true }); }).catch((e) => { ko(e); onClose(); }); }, [quoteId, onClose]);
  if (!quoteId || !d) return null;
  const send = () => api.post(`/quotes/${quoteId}/urgent-reminder`, f).then((r) => { toast.success(`Relance urgente envoyée à ${r.data.sent_to}`); onSent?.(); onClose(); }).catch(ko);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-xl overflow-y-auto" data-testid="reminder-dialog">
        <DialogHeader><DialogTitle className="text-xl font-bold">Relance urgente</DialogTitle></DialogHeader>
        <p className="text-sm text-muted-foreground">Destinataire : <b data-testid="reminder-to">{d.to || "aucune adresse e-mail"}</b> · langue {d.language} · e-mail (WhatsApp non configuré). Le message ne cite jamais l'autre client.</p>
        {d.recent && <p className="rounded-xl border border-amber-500/50 bg-amber-500/10 p-3 text-sm" data-testid="reminder-recent">Une relance urgente a déjà été envoyée il y a moins de 48 h : un nouvel envoi est bloqué.</p>}
        {d.status !== "envoye" && <p className="rounded-xl border border-border p-3 text-sm">Ce devis n'est pas encore envoyé : envoyez-le d'abord au client.</p>}
        <Field label="Objet"><Input value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} data-testid="reminder-subject" /></Field>
        <Field label={`Message (précédé de « ${d.greeting} », suivi du lien de signature)`}><Textarea rows={8} value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} data-testid="reminder-body" /></Field>
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Date limite"><Input type="date" value={f.deadline} onChange={(e) => setF({ ...f, deadline: e.target.value })} data-testid="reminder-deadline" /></Field>
          <label className="flex items-center gap-2 pb-2 text-sm"><Switch checked={f.set_deadline} onCheckedChange={(v) => setF({ ...f, set_deadline: v })} data-testid="reminder-set-deadline" />Fixer cette date comme expiration de l'option</label>
        </div>
        <DialogFooter><Button disabled={d.recent || d.status !== "envoye" || !d.to} onClick={send} data-testid="reminder-send"><Send />Envoyer la relance</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function AvailabilityPanel({ data, onReload }) {
  const [remind, setRemind] = useState(null);
  const close = useCallback(() => setRemind(null), []);
  if (!data) return null;
  if (data.no_date) return <p className="text-sm text-muted-foreground" data-testid="availability-no-date">Saisissez une date pour voir la disponibilité et les devis concurrents.</p>;
  if (!data.rows.length) return <p className="text-sm text-muted-foreground">Aucun produit du catalogue sur ce devis.</p>;
  const dl = data.delivery;
  return (
    <div className="space-y-3" data-testid="availability-panel">
      {data.rows.map((r) => (
        <div key={r.product_id} className={`rounded-xl border p-3 text-sm ${TONE[r.color]}`} data-testid={`availability-row-${r.product_id}`} data-color={r.color}>
          <div className="flex flex-wrap items-center gap-2"><span className={`h-2.5 w-2.5 rounded-full ${DOT[r.color]}`} /><b>{r.qty} × {r.name}</b>
            <span className="text-xs text-muted-foreground">stock {r.total} · ferme {r.firm} · en option {r.option_qty} · disponible {r.available_now} · si toutes les options passent {r.available_if_options}</span></div>
          <div className="mt-1 text-xs text-muted-foreground">{r.warehouses.map((w) => `${w.name} : ${w.on_hand - w.reserved} libre(s) sur ${w.on_hand}`).join(" · ") || "Aucun entrepôt utilisable pour ce lieu"}</div>
          {r.message && <div className="mt-1.5 font-semibold" data-testid={`availability-message-${r.product_id}`}><AlertTriangle className="mr-1 inline h-4 w-4" />{r.message}</div>}
          <div className="mt-2 flex flex-wrap gap-2">{r.allocation.map((a) => <span key={a.warehouse_id} className="flex items-center gap-1.5 text-xs" data-testid={`availability-alloc-${r.product_id}-${a.fulfilment}`}>{a.qty} × {a.name} <Ful f={a.fulfilment} /></span>)}</div>
          {r.options.map((o) => (
            <div key={o.quote_id} className="mt-2 flex flex-wrap items-center gap-2 rounded-lg bg-background/70 p-2 text-xs" data-testid={`availability-option-${o.number}`}>
              <span className="min-w-0 flex-1"><b>{o.qty}</b> sur <Link className="font-semibold underline" to={`/evenements/${o.event_id}`}>{o.number}</Link> ({Q_ST[o.status]}{o.client ? `, ${o.client}` : ""}{o.organizer ? `, organisateur ${o.organizer}` : ""}) · le {fmtDate(o.start.slice(0, 10))}
                {o.sent_at ? ` · envoyé le ${fmtDate(o.sent_at.slice(0, 10))}` : ""}{o.expires ? ` · option jusqu'au ${fmtDate(o.expires)}` : ""}{o.probability != null ? ` · ${o.probability} %` : ""}{o.owner ? ` · ${o.owner}` : ""}</span>
              {r.color !== "green" && <Button type="button" size="sm" variant="outline" onClick={() => setRemind(o.quote_id)} data-testid={`urgent-reminder-${o.number}`}><Send />Relance urgente</Button>}
            </div>
          ))}
        </div>
      ))}
      <div className="rounded-xl border border-border p-3 text-sm" data-testid="availability-delivery">
        {dl.all_on_site ? <>Tout le matériel est déjà sur place : aucun transport. Proposez une ligne « Mise en place sur site » plutôt que des frais de livraison.</>
          : <>Part à livrer : <b>{dl.to_deliver_qty}</b> article(s), {dl.weight_kg} kg, {dl.volume_m3} m³{dl.on_site_qty ? ` · ${dl.on_site_qty} déjà sur place` : ""}. Les frais de livraison restent saisis à la main, sur cette part.</>}
      </div>
      <p className="text-xs text-muted-foreground">{data.rule} {data.count_options ? "Les options sont déduites de la disponibilité." : "Les options sont affichées mais non déduites de la disponibilité."}</p>
      <ReminderDialog quoteId={remind} onClose={close} onSent={onReload} />
    </div>
  );
}

let cache = { at: 0, p: null };
const options = () => { if (Date.now() - cache.at > 20000) cache = { at: Date.now(), p: api.get("/stock/options").then((r) => r.data).catch(() => ({ rows: [], competition: {}, tension: [] })) }; return cache.p; };

export function QuoteStock({ q, onChanged }) {
  const [comp, setComp] = useState([]);
  const [open, setOpen] = useState(false);
  const [d, setD] = useState(null);
  const live = ["brouillon", "envoye"].includes(q.status);
  useEffect(() => { if (live) options().then((o) => setComp(o.competition[q.id] || [])); }, [q.id, live, q.updated_at]);
  const load = useCallback(() => api.get(`/quotes/${q.id}/availability`).then((r) => setD(r.data)).catch(ko), [q.id]);
  useEffect(() => { if (open) load(); }, [open, load]);
  const patch = (body) => api.patch(`/quotes/${q.id}/option`, body).then(() => { cache.at = 0; load(); onChanged?.(); }).catch(ko);
  return (
    <>
      {comp.length > 0 && <button onClick={() => setOpen(true)} className="rounded-full bg-amber-500/15 px-2.5 py-0.5 text-[11px] font-semibold text-amber-700 dark:text-amber-300" data-testid={`quote-competition-${q.number}`}>Concurrence sur le stock : {comp.join(", ")}</button>}
      <Button size="sm" variant="outline" onClick={() => setOpen(true)} data-testid={`quote-availability-${q.number}`}><Boxes />Disponibilité</Button>
      {open && (
        <Dialog open onOpenChange={setOpen}>
          <DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto">
            <DialogHeader><DialogTitle className="text-xl font-bold">Disponibilité & devis concurrents · {q.number}</DialogTitle></DialogHeader>
            {d && live && <div className="flex flex-wrap items-end gap-4">
              <Field label="Expiration de l'option"><Input type="date" defaultValue={d.option_expires_at} onBlur={(e) => e.target.value && e.target.value !== d.option_expires_at && patch({ option_expires_at: e.target.value })} data-testid="quote-option-expiry" /></Field>
              {d.option_released_at && <span className="pb-2 text-sm font-semibold text-red-600" data-testid="quote-option-released">Option expirée : matériel libéré</span>}
              <label className="flex items-center gap-2 pb-2 text-sm"><Switch checked={d.show_on_site} onCheckedChange={(v) => patch({ show_on_site: v })} data-testid="quote-show-on-site" />Afficher « dont X déjà sur place » sur le PDF</label>
            </div>}
            <AvailabilityPanel data={d} onReload={load} />
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}

export function TensionWidget() {
  const [rows, setRows] = useState(null);
  useEffect(() => { options().then((o) => setRows(o.tension)); }, []);
  if (!rows) return null;
  if (!rows.length) return <div className="text-sm text-muted-foreground">Aucune tension : les options en cours tiennent dans le stock.</div>;
  return <div className="space-y-2" data-testid="tension-list">{rows.slice(0, 8).map((r, i) => (
    <Link key={i} to="/entrepots?vue=options" className={`block rounded-xl border p-3 text-sm ${TONE[r.color]}`} data-testid={`tension-${r.number}`}><b>{r.product}</b> · {fmtDate(r.date)} · {r.number} ({r.qty})<div className="text-xs text-muted-foreground">{r.message}</div></Link>))}</div>;
}

export function StockSettings() {
  const [f, setF] = useState(null);
  useEffect(() => { api.get("/stock/settings").then((r) => setF(r.data)); }, []);
  if (!f) return null;
  const save = (next) => { setF(next); api.put("/stock/settings", next).then(() => toast.success("Réglage enregistré")).catch(ko); };
  return (
    <div className="card-soft space-y-4 p-5" data-testid="stock-settings">
      <label className="flex items-center gap-3 text-sm"><Switch checked={f.stock_count_options} onCheckedChange={(v) => save({ ...f, stock_count_options: v })} data-testid="stock-count-options" />Déduire de la disponibilité les options (devis non signés). Elles restent toujours affichées.</label>
      <Field label="Durée d'une option après l'envoi du devis (jours)"><Input type="number" min="1" max="90" className="w-28" defaultValue={f.option_days} onBlur={(e) => Number(e.target.value) !== f.option_days && save({ ...f, option_days: Number(e.target.value) || 7 })} data-testid="stock-option-days" /></Field>
    </div>
  );
}

export function StockDialog({ item, onClose }) {
  const [d, setD] = useState(null);
  const [wh, setWh] = useState("");
  useEffect(() => { setD(null); if (item) api.get(`/equipment/${item.id}/stock`, { params: { warehouse_id: wh } }).then((r) => setD(r.data)).catch(ko); }, [item, wh]);
  if (!item) return null;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto" data-testid="product-stock-dialog">
        <DialogHeader><DialogTitle className="text-xl font-bold">Stock · {item.name}</DialogTitle></DialogHeader>
        {d && <>
          <table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted-foreground"><th className="py-2">Entrepôt</th><th>En stock</th><th>Réservé</th><th>Maint. / HS</th><th>Disponible</th></tr></thead>
            <tbody>{d.warehouses.map((w) => <tr key={w.warehouse_id} className="border-t border-border" data-testid={`product-stock-row-${w.warehouse_id}`}><td className="py-2">{w.name}</td><td>{w.on_hand}</td><td>{w.reserved}</td><td>{w.maintenance}</td><td className="font-semibold">{w.available}</td></tr>)}
              <tr className="border-t border-border font-semibold"><td className="py-2">Total{d.in_transit ? ` (+ ${d.in_transit} en transit)` : ""}</td><td data-testid="product-stock-total">{d.total.on_hand}</td><td>{d.total.reserved}</td><td>{d.total.maintenance}</td><td>{d.total.available}</td></tr></tbody></table>
          <p className="text-xs text-muted-foreground">Période : maintenant → +24 h, temps tampon J-{d.product.prep_days_before} / J+{d.product.return_days_after} inclus.</p>
          <div className="flex items-center justify-between"><div className="eyebrow">Disponibilité sur 30 jours</div>
            <select className="h-8 rounded-lg border border-border bg-background px-2 text-xs" value={wh} onChange={(e) => setWh(e.target.value)} data-testid="product-stock-warehouse"><option value="">Tous les entrepôts</option>{d.warehouses.map((w) => <option key={w.warehouse_id} value={w.warehouse_id}>{w.name}</option>)}</select></div>
          <div className="grid grid-cols-6 gap-1 sm:grid-cols-10" data-testid="product-stock-calendar">{d.calendar.map((c) => <div key={c.day} title={c.day} className={`rounded-lg p-1.5 text-center text-xs ${c.available <= 0 ? "bg-red-500/15 text-red-700" : "bg-secondary"}`}><div className="text-[10px] text-muted-foreground">{c.day.slice(8)}/{c.day.slice(5, 7)}</div><b>{c.available}</b></div>)}</div>
        </>}
      </DialogContent>
    </Dialog>
  );
}

export function EventOrigin({ ev, write, onChanged }) {
  const [d, setD] = useState(null);
  const [edit, setEdit] = useState(null);
  const [ret, setRet] = useState(null);
  const version = JSON.stringify([(ev.equipment || []).map((l) => [l.equipment_id, l.qty]), ev.venue_id, ev.start, ev.status]);
  const load = useCallback(() => api.get(`/events/${ev.id}/origin`).then((r) => setD(r.data)).catch(() => {}), [ev.id]);
  useEffect(() => { load(); }, [load, version]);
  if (!d || !d.lines.length) return null;
  const saveAlloc = () => api.put(`/events/${ev.id}/allocations`, { equipment_id: edit.equipment_id, rows: edit.rows.map((r) => ({ warehouse_id: r.warehouse_id, qty: Number(r.qty) || 0 })) }).then((r) => { setD(r.data); setEdit(null); toast.success("Répartition manuelle enregistrée"); }).catch(ko);
  const doReturn = () => api.post(`/events/${ev.id}/stock-return`, { mode: ret.mode, lines: ret.lines.map((l) => ({ equipment_id: l.equipment_id, returned: Number(l.returned) || 0, damaged: Number(l.damaged) || 0 })) }).then(() => { toast.success("Retour de stock enregistré"); setRet(null); load(); onChanged?.(); }).catch(ko);
  return (
    <Section title="Origine du matériel" testid="origin-section" actions={write && <Button size="sm" variant="outline" onClick={() => api.post(`/events/${ev.id}/allocations/recalc`).then((r) => { setD(r.data); toast.success("Allocation recalculée"); }).catch(ko)} data-testid="origin-recalc"><RefreshCw />Recalculer</Button>}>
      {d.note && <p className="mb-3 rounded-xl bg-secondary p-3 text-sm" data-testid="origin-note">{d.note}</p>}
      {d.missing.map((m) => <p key={m.name} className="mb-2 rounded-xl border border-red-500/50 bg-red-500/10 p-3 text-sm font-semibold" data-testid="origin-missing"><AlertTriangle className="mr-1 inline h-4 w-4" />Manque {m.missing} × {m.name} — {d.suggestions.join(", ")}.</p>)}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">{d.groups.map((g) => (
        <div key={g.warehouse_id} className="rounded-xl border border-border p-3.5" data-testid={`origin-group-${g.fulfilment}`}>
          <div className="mb-2 flex items-center justify-between gap-2"><b className="text-sm">{g.name}</b><Ful f={g.fulfilment} /></div>
          {g.lines.map((l) => <div key={`${l.equipment_id}${l.auto ? "a" : ""}`} className="flex justify-between text-sm" data-testid={`origin-line-${g.fulfilment}-${l.equipment_id}`}><span>{l.qty} × {l.name}{l.mode === "manual" ? " (manuelle)" : ""}{l.auto ? " (auto : besoins)" : ""}</span></div>)}
          <div className="mt-2 text-xs text-muted-foreground">{g.weight_kg} kg · {g.volume_m3} m³</div>
        </div>))}</div>
      <p className="mt-3 text-sm" data-testid="origin-summary">{d.all_on_site ? "Tout est sur place : aucun transport à prévoir." : `À transporter : ${d.to_deliver.qty} article(s), ${d.to_deliver.weight_kg} kg, ${d.to_deliver.volume_m3} m³.`}</p>
      {write && <div className="mt-3 flex flex-wrap gap-2">
        {d.lines.map((l) => <Button key={l.equipment_id} size="sm" variant="ghost" onClick={() => setEdit({ ...l, rows: d.warehouses.map((w) => ({ warehouse_id: w.id, name: w.name, qty: l.rows.find((r) => r.warehouse_id === w.id)?.qty || 0 })) })} data-testid={`origin-edit-${l.equipment_id}`}>Répartir {l.name}</Button>)}
        {d.returned_at ? <span className="self-center text-xs font-semibold text-emerald-700" data-testid="origin-returned">Retour de stock enregistré</span>
          : <Button size="sm" variant="outline" onClick={() => setRet({ mode: "origin", lines: d.lines.map((l) => ({ ...l, returned: l.qty, damaged: 0 })) })} data-testid="origin-return">Retour du matériel (stock)</Button>}
      </div>}
      {edit && <Dialog open onOpenChange={() => setEdit(null)}><DialogContent className="max-w-md"><DialogHeader><DialogTitle>Répartir {edit.qty} × {edit.name}</DialogTitle></DialogHeader>
        {edit.rows.map((r, i) => <label key={r.warehouse_id} className="flex items-center justify-between gap-3 text-sm">{r.name}<Input type="number" min="0" step="any" className="w-24" value={r.qty} onChange={(e) => setEdit({ ...edit, rows: edit.rows.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)) })} data-testid={`origin-alloc-${r.warehouse_id}`} /></label>)}
        <DialogFooter><Button onClick={saveAlloc} data-testid="origin-alloc-save">Enregistrer (manuelle)</Button></DialogFooter></DialogContent></Dialog>}
      {ret && <Dialog open onOpenChange={() => setRet(null)}><DialogContent className="max-w-lg"><DialogHeader><DialogTitle>Retour du matériel</DialogTitle></DialogHeader>
        <select className="h-10 rounded-lg border border-border bg-background px-3 text-sm" value={ret.mode} onChange={(e) => setRet({ ...ret, mode: e.target.value })} data-testid="return-mode"><option value="origin">Retour à l'entrepôt d'origine</option>{d.has_depot && <option value="leave_on_site">Laisser sur place (transfert vers le dépôt du lieu)</option>}</select>
        <p className="text-xs text-muted-foreground">« Envoyer vers un autre événement » (rotation) arrivera avec la Logistique.</p>
        {ret.lines.map((l, i) => <div key={l.equipment_id} className="grid grid-cols-3 items-center gap-2 text-sm"><span>{l.qty} × {l.name}</span>
          <Input type="number" min="0" step="any" title="Retournées" value={l.returned} onChange={(e) => setRet({ ...ret, lines: ret.lines.map((x, j) => (j === i ? { ...x, returned: e.target.value } : x)) })} data-testid={`return-qty-${l.equipment_id}`} />
          <Input type="number" min="0" step="any" title="Cassées / perdues" placeholder="Cassées" value={l.damaged} onChange={(e) => setRet({ ...ret, lines: ret.lines.map((x, j) => (j === i ? { ...x, damaged: e.target.value } : x)) })} data-testid={`return-damaged-${l.equipment_id}`} /></div>)}
        <DialogFooter><Button onClick={doReturn} data-testid="return-submit">Valider le retour</Button></DialogFooter></DialogContent></Dialog>}
    </Section>
  );
}
