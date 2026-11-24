import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, errMsg } from "@/lib/api";

export const TONE = { gris: "bg-secondary text-secondary-foreground", vert: "bg-emerald-500/15 text-emerald-700", ambre: "bg-amber-500/15 text-amber-700", rouge: "bg-red-500/15 text-red-700",
  bleu: "bg-sky-500/15 text-sky-700", rose: "bg-pink-500/15 text-pink-700", violet: "bg-violet-500/15 text-violet-700" };
export const Pill = ({ color = "gris", children, testid, title }) => <span title={title} data-testid={testid} className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${TONE[color] || TONE.gris}`}>{children}</span>;
export const WpBadge = ({ testid }) => <Pill color="rose" testid={testid}>Wedding planner</Pill>;
export const statusKeys = (types, wp) => (types || []).map((t) => (t === "prestataire" && wp ? "wedding_planner" : t)).filter((t) => t !== "autre");

export function StatusesDialog({ open, onOpenChange, meta, onSaved }) {
  const [type, setType] = useState("client");
  const [items, setItems] = useState([]);
  useEffect(() => { if (open && meta) setItems(meta.lists[type].map((x) => ({ ...x }))); }, [open, meta, type]);
  if (!meta) return null;
  const up = (i, k, v) => setItems(items.map((x, j) => (j === i ? { ...x, [k]: v } : x)));
  const move = (i, d) => { const a = [...items]; if (!a[i + d]) return; [a[i], a[i + d]] = [a[i + d], a[i]]; setItems(a); };
  const done = (r) => { onSaved(r.data); toast.success("Statuts enregistrés"); };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto" data-testid="statuses-dialog">
      <DialogHeader><DialogTitle>Statuts des contacts</DialogTitle><DialogDescription>Une liste par type de contact. L'ordre des lignes est l'ordre d'affichage.</DialogDescription></DialogHeader>
      <div className="flex flex-wrap gap-1.5">{Object.entries(meta.labels).map(([k, l]) => <button key={k} onClick={() => setType(k)} data-testid={`statuses-type-${k}`} className={`h-8 rounded-full border px-3 text-xs font-medium ${type === k ? "border-primary bg-primary text-white" : "border-border"}`}>{l}{meta.custom.includes(k) ? " ·" : ""}</button>)}</div>
      <div className="space-y-2">{items.map((x, i) => (
        <div key={i} className="flex items-center gap-2" data-testid={`statuses-row-${i}`}>
          <Input className="h-9 flex-1" value={x.label} onChange={(e) => up(i, "label", e.target.value)} data-testid={`statuses-label-${i}`} />
          <select className="h-9 rounded-lg border border-border bg-background px-2 text-sm" value={x.color} onChange={(e) => up(i, "color", e.target.value)} data-testid={`statuses-color-${i}`}>{meta.tones.map((t) => <option key={t}>{t}</option>)}</select>
          {type === "prestataire" && <label className="flex items-center gap-1 whitespace-nowrap text-xs" title="Masqué des autocomplétions, du matching DJ et des disponibilités"><input type="checkbox" checked={!!x.excluded} onChange={(e) => up(i, "excluded", e.target.checked)} />Ne plus proposer</label>}
          <button className="text-xs" onClick={() => move(i, -1)} aria-label="Monter">↑</button><button className="text-xs" onClick={() => move(i, 1)} aria-label="Descendre">↓</button>
          <button aria-label="Supprimer" onClick={() => setItems(items.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></button>
        </div>))}</div>
      <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setItems([...items, { id: "", label: "", color: "gris", excluded: false }])} data-testid="statuses-add"><Plus />Statut</Button><span className="flex-1" />
        {meta.custom.includes(type) && <Button size="sm" variant="ghost" onClick={() => api.delete(`/contact-statuses/${type}`).then(done).catch((e) => toast.error(errMsg(e)))} data-testid="statuses-reset">Revenir à la liste par défaut</Button>}
        <Button size="sm" disabled={!items.length || items.some((x) => !x.label.trim())} onClick={() => api.put(`/contact-statuses/${type}`, { items }).then(done).catch((e) => toast.error(errMsg(e)))} data-testid="statuses-save">Enregistrer</Button></div>
    </DialogContent></Dialog>
  );
}
