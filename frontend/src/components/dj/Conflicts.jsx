import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";

const LV = { free: ["✓", "libre", "text-emerald-600"], tentative: ["ⓘ", "sous réserve", "text-muted-foreground"], probable: ["⚠", "conflit probable", "text-amber-600"], blocking: ["⛔", "conflit", "text-red-600"], unavailable: ["⛔", "indisponible", "text-red-600"] };
const ST = { option_requested: "Option demandée", option_accepted: "Option acceptée", option_conditions: "Sous conditions", confirmed: "Confirmé", acknowledged: "Confirmé", availability_requested: "Dispo demandée", available: "Disponible" };
const fr = (d) => (d || "").split("-").reverse().join("/");
export const isHard = (r) => ["blocking", "unavailable"].includes(r?.level);

export function useSelection(eventId) {
  const [sel, setSel] = useState(null);
  const load = useCallback(() => { if (eventId) api.get("/dj/selection", { params: { event_id: eventId } }).then((r) => setSel({ ...r.data, by: Object.fromEntries(r.data.djs.map((x) => [x.provider_id, x])) })).catch(() => setSel(null)); }, [eventId]);
  useEffect(() => { load(); }, [load]);
  return [sel, load];
}

export function Pill({ row }) {
  if (!row) return null;
  const [icon, label, tone] = LV[row.level] || LV.free;
  return <span className={`whitespace-nowrap text-xs font-semibold ${tone}`} title={row.conflicts.map((c) => c.detail).join("\n") || "Aucun conflit sur ce créneau"} data-testid={`dj-pill-${row.provider_id}`} data-level={row.level}>{icon} {label}</span>;
}

export function ConflictDialog({ sel, row, onCancel, onOther, onForce }) {
  const [reason, setReason] = useState("");
  const e = sel.event;
  return (
    <Dialog open onOpenChange={(o) => !o && onCancel()}><DialogContent className="max-w-2xl" data-testid="dj-conflict-dialog">
      <DialogHeader><DialogTitle>Conflit DJ : {row.name}</DialogTitle><DialogDescription>Ce DJ est déjà pris sur ce créneau. Comparez les deux prestations avant de décider.</DialogDescription></DialogHeader>
      <div className="grid gap-3 text-sm sm:grid-cols-2">
        <div className="rounded-xl border border-border p-3" data-testid="dj-conflict-new"><b>Prestation à affecter</b><div>{e.title}</div><div className="text-muted-foreground">{fr(e.date)} · {e.start_time} → {e.end_time}</div><div className="text-muted-foreground">{e.venue || "Lieu à définir"}</div></div>
        <div className="space-y-2">{row.conflicts.filter((c) => ["blocking", "unavailable"].includes(c.level)).map((c, i) => (
          <div key={i} className="rounded-xl border border-red-500/50 bg-red-500/10 p-3" data-testid={`dj-conflict-other-${i}`}><b>{c.event_title || "Indisponibilité déclarée"}</b>{c.event_title ? <><div className="text-muted-foreground">{fr(c.date)} · {c.start_time || "?"} → {c.end_time || "?"}</div><div className="text-muted-foreground">{c.venue || "Lieu à définir"} · {ST[c.status] || c.status}{c.event_code ? ` · ${c.event_code}` : ""}</div></> : <div className="text-muted-foreground">{c.detail}</div>}</div>))}</div>
      </div>
      <Input placeholder="Motif pour affecter quand même (obligatoire), ex. deux sets courts, même domaine" value={reason} onChange={(x) => setReason(x.target.value)} data-testid="dj-conflict-reason" />
      <div className="flex flex-wrap justify-end gap-2"><Button variant="ghost" onClick={onCancel} data-testid="dj-conflict-cancel">Annuler</Button><Button variant="outline" onClick={onOther} data-testid="dj-conflict-other">Choisir un autre DJ</Button><Button variant="destructive" disabled={!reason.trim()} onClick={() => onForce(reason.trim())} data-testid="dj-conflict-force">Affecter quand même</Button></div>
    </DialogContent></Dialog>);
}

export function DjGrid({ days }) {
  const names = [...new Set(days.flatMap((d) => d.events.flatMap((e) => e.djs.map((x) => x.name))))].sort();
  if (!names.length) return <p className="text-sm text-muted-foreground">Aucun DJ affecté sur la période.</p>;
  return (
    <div className="overflow-x-auto" data-testid="dj-grid"><table className="text-xs"><thead><tr><th className="sticky left-0 bg-background p-2 text-left">DJ</th>{days.map((d) => <th key={d.date} className="whitespace-nowrap p-2">{fr(d.date).slice(0, 5)}</th>)}</tr></thead>
      <tbody>{names.map((n) => <tr key={n} className="border-t border-border"><td className="sticky left-0 whitespace-nowrap bg-background p-2 font-semibold">{n}</td>{days.map((d) => { const evs = d.events.filter((e) => e.djs.some((x) => x.name === n)); const clash = evs.length > 1; const ok = clash && evs.every((e) => e.conflict_accepted);
        return <td key={d.date} className={`p-2 align-top ${clash ? (ok ? "bg-amber-500/20" : "bg-red-500/20 font-semibold text-red-700") : evs.length ? "bg-emerald-500/10" : ""}`} data-testid={clash ? `dj-grid-clash-${d.date}` : undefined}>{evs.map((e) => <div key={e.event_id} className="whitespace-nowrap">{e.start}–{e.end} {e.code}</div>)}{ok && <div>Conflit accepté</div>}</td>; })}</tr>)}</tbody></table></div>);
}
