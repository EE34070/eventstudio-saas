import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Field } from "@/components/common";
import { api, errMsg } from "@/lib/api";

const TYPES = ["Location", "Consommable", "Service", "Prestation artistique", "Pack"];
const uniq = (rows, k) => [...new Set(rows.map((x) => x[k]).filter(Boolean))].sort();

export function NewProduct({ value, eqs, onClose, onCreated }) {
  const [f, setF] = useState({ name: value.name, category: "", subcategory: "", product_type: "Location", price_day: value.price ?? "", qty_total: 0 });
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const save = async () => {
    setBusy(true);
    try { const { data } = await api.post("/equipment/quick", { ...f, price_day: Number(f.price_day) || 0, qty_total: Number(f.qty_total) || 0 }); toast.success(`Produit créé : ${data.ref}`); onCreated(data); } catch (e) { toast.error(errMsg(e)); }
    setBusy(false);
  };
  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-md" data-testid="new-product-panel">
        <SheetHeader><SheetTitle>Créer le produit</SheetTitle><SheetDescription>Il est ajouté au catalogue avec le badge « À compléter », puis au devis (quantité {value.qty}). La référence est attribuée automatiquement.</SheetDescription></SheetHeader>
        <div className="mt-5 space-y-4">
          <Field label="Désignation *"><Input value={f.name} onChange={set("name")} data-testid="new-product-name" /></Field>
          <Field label="Catégorie *"><Input list="np-cats" value={f.category} onChange={set("category")} placeholder="Sonorisation, Éclairage…" data-testid="new-product-category" /><datalist id="np-cats">{uniq(eqs, "category").map((c) => <option key={c} value={c} />)}</datalist></Field>
          <Field label="Sous-catégorie"><Input list="np-subs" value={f.subcategory} onChange={set("subcategory")} data-testid="new-product-subcategory" /><datalist id="np-subs">{uniq(eqs.filter((x) => !f.category || x.category === f.category), "subcategory").map((c) => <option key={c} value={c} />)}</datalist></Field>
          <Field label="Type"><select className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm" value={f.product_type} onChange={set("product_type")} data-testid="new-product-type">{TYPES.map((c) => <option key={c}>{c}</option>)}</select></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Prix HT / jour"><Input type="number" min="0" step="any" value={f.price_day} onChange={set("price_day")} data-testid="new-product-price" /></Field>
            <Field label="Quantité en stock"><Input type="number" min="0" step="1" value={f.qty_total} onChange={set("qty_total")} data-testid="new-product-qty" /></Field>
          </div>
          <div className="flex justify-end gap-2 pt-2"><Button type="button" variant="ghost" onClick={onClose}>Annuler</Button><Button type="button" disabled={busy || !f.name.trim() || !f.category.trim()} onClick={save} data-testid="new-product-save">Créer et ajouter au devis</Button></div>
        </div>
      </SheetContent>
    </Sheet>);
}
