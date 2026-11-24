import { useState } from "react";
import { toast } from "sonner";
import { ArrowDown, ArrowUp, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, errMsg } from "@/lib/api";

const SERVICE = ["Service", "Prestation artistique"];
const num = (v) => Number(String(v).replace(",", ".")) || 0;
const preview = (cs) => [["Prestations incluses", cs.filter((c) => c.service)], ["Matériel inclus", cs.filter((c) => !c.service)]].filter(([, x]) => x.length).map(([t, x]) => `${t} : ${x.map((c) => `${c.qty} × ${c.client_label || c.name}`).join(" · ")}`).join(" / ");

export const packOf = (m, eqs) => {
  if (m.product_type !== "Pack" || !m.components?.length) return {};
  const by = Object.fromEntries(eqs.map((e) => [e.id, e]));
  const sum = m.components.reduce((s, c) => s + c.qty * (by[c.equipment_id]?.price_day || 0), 0);
  const cost = Math.round(m.components.reduce((s, c) => s + c.qty * (by[c.equipment_id]?.cost || by[c.equipment_id]?.cost_ht || 0), 0) * 100) / 100;
  return { show_components: true, pack_version: m.version || 1, ...(cost > 0 ? { unit_cost: cost } : {}), ...(m.pricing_mode === "sum" ? { unit_price: Math.round(sum * (m.pricing_coef || 1) * 100) / 100 } : {}),
    pack_components: m.components.map((c) => ({ equipment_id: c.equipment_id, qty: c.qty, base_qty: c.qty, visible_client: c.visible_client !== false, show_exact_reference: !!c.show_exact_reference, client_label: c.client_label || "", client_label_en: c.client_label_en || "", name: by[c.equipment_id]?.name || "", name_en: by[c.equipment_id]?.name_en || "", service: SERVICE.includes(by[c.equipment_id]?.product_type) })) };
};

export function PackLine({ b, upd }) {
  const set = (i, patch) => upd(b.id, { pack_components: b.pack_components.map((c, j) => (j === i ? { ...c, ...patch } : c)) });
  return (
    <div className="col-span-12 rounded-xl bg-secondary/40 p-2 text-xs" data-testid={`pack-line-${b.id}`}>
      <label className="mb-1 flex items-center gap-2 font-semibold"><input type="checkbox" checked={b.show_components !== false} onChange={(e) => upd(b.id, { show_components: e.target.checked })} data-testid={`pack-show-${b.id}`} />Détail de la composition affiché au client (sans prix)</label>
      <div className="flex flex-wrap gap-x-4 gap-y-1">{b.pack_components.map((c, i) => (
        <span key={c.equipment_id + i} className={`flex items-center gap-1 ${c.visible_client ? "" : "opacity-50"}`}><Input className="h-7 w-14 px-1" type="number" min="0" step="any" value={c.qty} onChange={(e) => set(i, { qty: num(e.target.value) })} aria-label={`Quantité ${c.name}`} data-testid={`pack-qty-${b.id}-${i}`} />× {c.client_label || c.name}
          {c.qty !== c.base_qty && <span className="rounded-full bg-amber-500/20 px-1.5 font-semibold text-amber-700" data-testid={`pack-adjusted-${b.id}-${i}`}>ajusté</span>}{!c.visible_client && <span>(interne)</span>}</span>))}</div>
    </div>);
}

export function PackComposition({ item, equipment, onClose, onSaved }) {
  const by = Object.fromEntries(equipment.map((e) => [e.id, e]));
  const [cs, setCs] = useState((item.components || []).map((c) => ({ ...c })));
  const [mode, setMode] = useState(item.pricing_mode || "fixed");
  const [coef, setCoef] = useState(item.pricing_coef || 1);
  const [q, setQ] = useState("");
  const set = (i, patch) => setCs(cs.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const move = (i, d) => { const n = [...cs]; [n[i], n[i + d]] = [n[i + d], n[i]]; setCs(n); };
  const found = q.length >= 2 ? equipment.filter((e) => e.id !== item.id && `${e.name} ${e.ref}`.toLowerCase().includes(q.toLowerCase())).slice(0, 8) : [];
  const save = () => api.put(`/equipment/${item.id}/pack`, { components: cs.map((c) => ({ equipment_id: c.equipment_id, qty: num(c.qty) || 1, visible_client: c.visible_client !== false, client_label: c.client_label || "", client_label_en: c.client_label_en || "", note: c.note || "", show_exact_reference: !!c.show_exact_reference })), pricing_mode: mode, pricing_coef: num(coef) || 1 })
    .then(() => { toast.success("Composition enregistrée"); onSaved(); onClose(); }).catch((e) => toast.error(errMsg(e)));
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}><DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto" data-testid="pack-composition-dialog">
      <DialogHeader><DialogTitle>Composition — {item.name}</DialogTitle><DialogDescription>Le pack n'a pas de stock propre : la disponibilité et les réservations portent sur ses composants matériels. Les services ne réservent pas de stock.</DialogDescription></DialogHeader>
      <div className="relative"><Input placeholder="Ajouter un composant : rechercher dans le catalogue…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="pack-search" />
        {found.length > 0 && <div className="absolute z-40 mt-1 w-full rounded-xl border border-border bg-card shadow-lg">{found.map((e, i) => <button key={e.id} type="button" className="block w-full px-3 py-1.5 text-left text-sm hover:bg-secondary" onClick={() => { setCs([...cs, { equipment_id: e.id, qty: 1, visible_client: true, client_label: "", client_label_en: "", note: "" }]); setQ(""); }} data-testid={`pack-search-item-${i}`}>{e.name} <span className="text-xs text-muted-foreground">{e.ref} · {e.product_type}</span></button>)}</div>}</div>
      <div className="divide-y divide-border">{cs.map((c, i) => (
        <div key={c.equipment_id + i} className="flex flex-wrap items-center gap-2 py-2 text-sm" data-testid={`pack-comp-${i}`}>
          <Input className="h-9 w-16" type="number" min="0" step="any" value={c.qty} onChange={(e) => set(i, { qty: e.target.value })} data-testid={`pack-comp-qty-${i}`} /><span className="min-w-0 flex-1">× {by[c.equipment_id]?.name || "article supprimé"} <span className="text-xs text-muted-foreground">{by[c.equipment_id]?.product_type}</span></span>
          <Input className="h-9 w-40" placeholder="Libellé client (FR)" value={c.client_label || ""} onChange={(e) => set(i, { client_label: e.target.value })} data-testid={`pack-comp-label-${i}`} /><Input className="h-9 w-36" placeholder="Libellé client (EN)" value={c.client_label_en || ""} onChange={(e) => set(i, { client_label_en: e.target.value })} />
          <Input className="h-9 w-36" placeholder="Note interne" value={c.note || ""} onChange={(e) => set(i, { note: e.target.value })} />
          <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={c.visible_client !== false} onChange={(e) => set(i, { visible_client: e.target.checked })} data-testid={`pack-comp-visible-${i}`} />visible client</label>
          <label className="flex items-center gap-1 text-xs" title="Si coché, la référence exacte devient contractuelle : la remplacer demandera votre validation « équivalent ou supérieur », ou une nouvelle signature."><input type="checkbox" checked={!!c.show_exact_reference} onChange={(e) => set(i, { show_exact_reference: e.target.checked })} data-testid={`pack-comp-exact-${i}`} />réf. exacte</label>
          <button type="button" aria-label="Monter" disabled={!i} onClick={() => move(i, -1)}><ArrowUp className="h-4 w-4" /></button><button type="button" aria-label="Descendre" disabled={i === cs.length - 1} onClick={() => move(i, 1)}><ArrowDown className="h-4 w-4" /></button>
          <button type="button" aria-label="Retirer" onClick={() => setCs(cs.filter((_, j) => j !== i))} data-testid={`pack-comp-remove-${i}`}><Trash2 className="h-4 w-4" /></button>
        </div>))}{!cs.length && <p className="py-4 text-sm text-muted-foreground">Aucun composant.</p>}</div>
      <div className="flex flex-wrap items-center gap-3 text-sm"><span className="font-semibold">Prix du pack</span><select className="h-9 rounded-lg border border-border bg-background px-2 text-sm" value={mode} onChange={(e) => setMode(e.target.value)} data-testid="pack-pricing-mode"><option value="fixed">Prix fixe (celui de la fiche article)</option><option value="sum">Somme des composants × coefficient</option></select>
        {mode === "sum" && <Input className="h-9 w-20" type="number" min="0" step="any" value={coef} onChange={(e) => setCoef(e.target.value)} data-testid="pack-pricing-coef" />}</div>
      <div className="rounded-xl border border-border p-3 text-sm" data-testid="pack-client-preview"><div className="mb-1 text-xs font-semibold text-muted-foreground">Ce que voit le client</div><b>{item.name}</b><div className="text-muted-foreground">{preview(cs.filter((c) => c.visible_client !== false).map((c) => ({ ...c, name: by[c.equipment_id]?.name, service: SERVICE.includes(by[c.equipment_id]?.product_type) }))) || "Aucun détail affiché."}</div></div>
      <DialogFooter><Button variant="ghost" onClick={onClose}>Annuler</Button><Button onClick={save} data-testid="pack-composition-save">Enregistrer la composition</Button></DialogFooter>
    </DialogContent></Dialog>);
}
