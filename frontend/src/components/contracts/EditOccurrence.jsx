import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, errMsg } from "@/lib/api";
import { fmtDate, fmtEur2 } from "@/lib/constants";

const PARTS = [["principal", "Capital"], ["interest", "Intérêts"], ["insurance", "Assurance"], ["fees", "Frais"]];
const n = (v) => Number(String(v).replace(",", ".")) || 0;

export function EditOccurrence({ loan, id, row, onClose, onSaved }) {
  const url = loan ? `/loans/${id}/installments/${row.n}` : `/subscriptions/${id}/occurrences/${row.contractual_date}`;
  const cur = loan ? row.total : row.expected_amount;
  const [mode, setMode] = useState("total");
  const [f, setF] = useState({ amount: cur, principal: row.principal ?? 0, interest: row.interest ?? 0, insurance: row.insurance ?? 0, fees: row.fees ?? 0 });
  const [following, setFollowing] = useState(false);
  const [reason, setReason] = useState("");
  const total = mode === "detail" ? PARTS.reduce((s, [k]) => s + n(f[k]), 0) : n(f.amount);
  const done = (p) => p.then((r) => { toast.success("Échéance mise à jour"); onSaved(r.data); }).catch((e) => toast.error(errMsg(e)));
  const save = () => done(api.put(url, { reason, following, ...(mode === "detail" ? Object.fromEntries(PARTS.map(([k]) => [k, n(f[k])])) : { amount: n(f.amount) }) }));
  const pill = (on) => `h-8 rounded-full border px-3 text-xs font-medium ${on ? "border-primary bg-primary text-white" : "border-border hover:bg-secondary"}`;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}><DialogContent className="max-w-lg" data-testid="occurrence-edit-dialog">
      <DialogHeader><DialogTitle>Modifier l'échéance du {fmtDate(row.contractual_date)}</DialogTitle><DialogDescription>Montant actuel : {fmtEur2(cur)}. L'échéancier, le calendrier des prélèvements et la trésorerie sont recalculés aussitôt.</DialogDescription></DialogHeader>
      {loan && <div className="flex gap-2">{[["total", "Montant total"], ["detail", "Détail (capital, intérêts…)"]].map(([k, l]) => <button key={k} type="button" className={pill(mode === k)} onClick={() => setMode(k)} data-testid={`occ-mode-${k}`}>{l}</button>)}</div>}
      {mode === "detail" ? <div className="grid grid-cols-2 gap-3">{PARTS.map(([k, l]) => <label key={k} className="text-xs text-muted-foreground">{l}<Input className="mt-1 h-9" type="number" min="0" step="any" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} data-testid={`occ-${k}`} /></label>)}
        <div className="col-span-2 text-sm">Total de l'échéance : <b data-testid="occ-total">{fmtEur2(total)}</b>. Le capital restant dû est recalculé ; l'écart est reporté sur la dernière échéance.</div></div>
        : <label className="text-xs text-muted-foreground">Nouveau montant<Input className="mt-1 h-9" type="number" min="0" step="any" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} data-testid="occ-amount" /></label>}
      <div className="flex flex-wrap gap-2">{[[false, "Cette échéance seulement"], [true, "Cette échéance et les suivantes"]].map(([v, l]) => <button key={l} type="button" className={pill(following === v)} onClick={() => setFollowing(v)} data-testid={`occ-scope-${v ? "following" : "one"}`}>{l}</button>)}</div>
      <label className="text-xs text-muted-foreground">Motif (obligatoire)<Input className="mt-1 h-9" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Ex. révision tarifaire, avenant du 12/03" data-testid="occ-reason" /></label>
      {row.history?.length > 0 && <div className="rounded-xl border border-border p-3 text-xs" data-testid="occ-history"><div className="mb-1 font-semibold">Historique</div>
        {row.history.map((h, i) => <div key={i} className="py-0.5 text-muted-foreground">{fmtDate(h.at)} · {h.by || "—"} · {h.reason}{h.from ? ` (avant : ${fmtEur2(h.from.total ?? h.from.amount)})` : ""}{h.following ? " · et suivantes" : ""}</div>)}</div>}
      <div className="flex flex-wrap justify-end gap-2">
        {row.is_manual_override && row.history?.length > 0 && <Button variant="outline" onClick={() => done(api.delete(url))} data-testid="occ-reset">Revenir à la valeur calculée</Button>}
        <Button variant="ghost" onClick={onClose}>Annuler</Button><Button disabled={reason.trim().length < 2} onClick={save} data-testid="occ-save">Enregistrer</Button></div>
    </DialogContent></Dialog>);
}
