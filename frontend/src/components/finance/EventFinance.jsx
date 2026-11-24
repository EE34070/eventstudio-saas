import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Section } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { fmtEur2 } from "@/lib/constants";

const ko = (e) => toast.error(errMsg(e));
const sel = "h-9 rounded-lg border border-border bg-background px-2 text-sm";
const ST = { prevu: "Prévu", confirme: "Confirmé", facture: "Facturé", paye: "Payé", annule: "Annulé" };
const pct = (v) => (v == null ? "—" : `${String(v).replace(".", ",")} %`);
const Row = ({ l, v, strong, testid }) => <div className={`flex justify-between py-1.5 text-sm ${strong ? "border-t border-border pt-2 font-semibold" : ""}`}><span className={strong ? "" : "text-muted-foreground"}>{l}</span><span data-testid={testid}>{v}</span></div>;

export function EventFinance({ eid }) {
  const [d, setD] = useState(null);
  const [f, setF] = useState(null);
  const load = useCallback(() => api.get(`/events/${eid}/finance`).then((r) => setD(r.data)).catch(ko), [eid]);
  useEffect(() => { load(); }, [load]);
  if (!d) return null;
  const done = (r) => { setD(r.data); setF(null); };
  return (
    <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-3" data-testid="event-finance">
      <Section title="Recettes" testid="event-finance-revenue">
        <Row l={`Devisé HT${d.quote ? ` (${d.quote.number}${d.signed ? ", signé" : ""})` : ""}`} v={fmtEur2(d.revenue.quoted_ht)} testid="ef-quoted" />
        <Row l="Facturé HT" v={fmtEur2(d.revenue.invoiced_ht)} /><Row l="Encaissé TTC" v={fmtEur2(d.revenue.paid_ttc)} /><Row l="Reste dû TTC" v={fmtEur2(d.revenue.due_ttc)} strong />
        <div className="mt-3 text-xs text-muted-foreground">Par activité</div>
        {Object.entries(d.by_activity).map(([k, v]) => <Row key={k} l={d.activities[k] || k} v={fmtEur2(v)} testid={`ef-activity-${k}`} />)}
        <label className="mt-3 block text-xs text-muted-foreground">Canal
          <select className={`${sel} mt-1 w-full`} value={d.channel_id} disabled={!d.write} onChange={(e) => api.put(`/events/${eid}/finance/channel`, { channel_id: e.target.value }).then(done).catch(ko)} data-testid="ef-channel">{d.channels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
        <div className="mt-3 rounded-lg bg-secondary p-2 text-xs text-muted-foreground" data-testid="ef-pennylane">Réel comptable : Pennylane non connecté</div>
      </Section>
      {d.costs && <Section title="Charges" testid="event-finance-charges">
        {d.charges.categories.map((c) => <Row key={c.key} l={`${c.label}${c.estimated ? " (estimé)" : ""}`} v={`${fmtEur2(c.planned)} · facturé ${fmtEur2(c.invoiced)}`} testid={`ef-cat-${c.key}`} />)}
        <Row l="Total prévu" v={fmtEur2(d.charges.planned)} strong testid="ef-charges-planned" /><Row l="Facturé / payé" v={`${fmtEur2(d.charges.invoiced)} / ${fmtEur2(d.charges.paid)}`} />
        <Row l="Marge prévisionnelle" v={`${fmtEur2(d.margin_planned)} (${pct(d.margin_planned_pct)})`} strong testid="ef-margin-planned" />
        <Row l="Marge réelle" v={d.margin_real == null ? "— (rien de facturé)" : `${fmtEur2(d.margin_real)} (${pct(d.margin_real_pct)})`} testid="ef-margin-real" />
        {d.alert && <div className="mt-2 rounded-lg bg-red-500/10 p-2 text-xs font-medium text-red-700" data-testid="ef-alert">Marge sous le seuil de {d.threshold} %</div>}
      </Section>}
      {d.costs && <Section title="Engagements" testid="event-finance-commitments">
        {!d.commitments.length && <p className="text-sm text-muted-foreground">Aucun engagement.</p>}
        {d.commitments.map((c) => (
          <div key={c.id} className="border-b border-border py-2 text-sm last:border-0" data-testid={`ef-commit-${c.id}`}>
            <div className="flex justify-between gap-2"><span className="min-w-0 truncate font-medium">{c.label}</span><b data-testid={`ef-commit-amount-${c.id}`}>{fmtEur2(c.amount_ht)}</b></div>
            <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground"><span>{d.categories[c.category]}{c.due_date ? ` · paiement ${c.due_date}` : ""}{c.source === "mission" ? " · prestataire retenu" : ""}{c.actual_ht != null && c.actual_ht !== c.amount_ht ? ` · réel ${fmtEur2(c.actual_ht)} (écart ${fmtEur2(c.actual_ht - c.amount_ht)})` : ""}</span>
              <select className="h-7 rounded border border-border bg-background px-1" value={c.status} disabled={!d.write} data-testid={`ef-commit-status-${c.id}`}
                onChange={(e) => { const st = e.target.value; const real = ["facture", "paye"].includes(st) ? window.prompt("Montant réel HT facturé ?", String(c.actual_ht ?? c.amount_ht)) : null; api.put(`/events/${eid}/finance/commitments/${c.id}`, { status: st, actual_ht: real ? Number(real.replace(",", ".")) : null }).then(done).catch(ko); }}>{Object.entries(ST).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>
          </div>))}
        {d.write && (f ? <div className="mt-2 space-y-2" data-testid="ef-commit-form"><Input placeholder="Libellé" value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} data-testid="ef-commit-label" />
          <div className="flex gap-2"><select className={`${sel} flex-1`} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} data-testid="ef-commit-category">{Object.entries(d.categories).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            <Input className="w-28" type="number" min="0" placeholder="HT €" value={f.amount_ht} onChange={(e) => setF({ ...f, amount_ht: e.target.value })} data-testid="ef-commit-amount" /><Input className="w-36" type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></div>
          <div className="flex justify-end gap-2"><Button size="sm" variant="ghost" onClick={() => setF(null)}>Annuler</Button><Button size="sm" disabled={!f.label.trim() || f.amount_ht === ""} onClick={() => api.post(`/events/${eid}/finance/commitments`, { ...f, amount_ht: Number(f.amount_ht) }).then(done).catch(ko)} data-testid="ef-commit-save">Ajouter</Button></div></div>
          : <button className="mt-2 text-sm underline" onClick={() => setF({ label: "", category: "transport", amount_ht: "", due_date: "" })} data-testid="ef-commit-add">+ Engagement manuel</button>)}
      </Section>}
    </div>);
}
