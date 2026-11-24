import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, errMsg } from "@/lib/api";

const ACTIONS = { "": "À rapprocher", existing: "Existant", new: "Nouveau (créer l'article)", service: "Service / frais", ignore: "Ignorer" };

export function MatchDialog({ quoteId, onClose, onDone }) {
  const [d, setD] = useState(null);
  useEffect(() => { api.get(`/quotes/${quoteId}/matching`).then((r) => setD({ ...r.data, rows: r.data.rows.map((x) => (x.action || !x.suggestion ? x : { ...x, action: "existing", equipment_id: x.suggestion.equipment_id, proposed: true })) })).catch((e) => toast.error(errMsg(e))); }, [quoteId]);
  if (!d) return null;
  const up = (id, patch) => setD({ ...d, rows: d.rows.map((x) => (x.block_id === id ? { ...x, ...patch, proposed: false } : x)) });
  const bad = d.rows.some((x) => x.action === "existing" && !x.equipment_id);
  const save = () => api.put(`/quotes/${quoteId}/matching`, { rows: d.rows.map((x) => ({ block_id: x.block_id, action: x.action, equipment_id: x.action === "existing" ? x.equipment_id : "", category: x.category || "" })) })
    .then((r) => { toast.success(r.data.unmatched ? `Enregistré : ${r.data.unmatched} ligne(s) restent à rapprocher` : "Correspondances enregistrées : matériel de l'événement mis à jour"); onDone(); onClose(); }).catch((e) => toast.error(errMsg(e)));
  const sel = "h-9 rounded-lg border border-border bg-background px-2 text-xs";
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}><DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto" data-testid="match-dialog">
      <DialogHeader><DialogTitle>Matériel du devis {d.number}</DialogTitle><DialogDescription>Reliez chaque ligne à un article du catalogue pour générer les besoins matériel de l'événement. Les correspondances validées sont mémorisées pour les prochains imports.</DialogDescription></DialogHeader>
      <div className="divide-y divide-border">{d.rows.map((x, i) => (
        <div key={x.block_id} className="flex flex-wrap items-center gap-2 py-2 text-sm" data-testid={`match-row-${i}`}>
          <span className="min-w-0 flex-1"><b>{x.qty} ×</b> {x.label}{x.proposed && <span className="ml-2 text-xs text-amber-600">proposition à vérifier</span>}</span>
          <select className={sel} value={x.action} onChange={(e) => up(x.block_id, { action: e.target.value })} data-testid={`match-action-${i}`}>{Object.entries(ACTIONS).filter(([k]) => k !== "new" || d.can_create).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          {x.action === "existing" && <select className={`${sel} max-w-56`} value={x.equipment_id} onChange={(e) => up(x.block_id, { equipment_id: e.target.value })} data-testid={`match-equipment-${i}`}><option value="">Choisir un article…</option>{d.equipment.map((e) => <option key={e.id} value={e.id}>{e.name}{e.ref ? ` (${e.ref})` : ""}</option>)}</select>}
          {x.action === "new" && <Input className="h-9 w-40" placeholder="Catégorie" value={x.category || ""} onChange={(e) => up(x.block_id, { category: e.target.value })} data-testid={`match-category-${i}`} />}
        </div>))}</div>
      <DialogFooter><Button variant="ghost" onClick={onClose}>Annuler</Button><Button disabled={bad} onClick={save} data-testid="match-save">Enregistrer les correspondances</Button></DialogFooter>
    </DialogContent></Dialog>);
}
