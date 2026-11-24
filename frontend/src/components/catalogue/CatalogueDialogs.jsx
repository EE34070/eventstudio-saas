import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Field, StatusBadge } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { TranslateButton } from "@/lib/i18n";
import { CATEGORIES, MODULES, fmtDT } from "@/lib/constants";
import { FileImg, UploadButton } from "@/lib/files";

const EQ_EMPTY = { ref: "", name: "", category: "Sonorisation", subcategory: "", product_type: "Location", provenance: "", photo: "", description: "", name_en: "", description_en: "", qty_total: 1, price_day: 0, replacement_value: 0, weight_kg: 0, volume_m3: 0, state: "bon", notes: "", prep_days_before: 0, return_days_after: 0 };

export function EquipmentDialog({ open, onOpenChange, item, onSaved, cats }) {
  const [f, setF] = useState(EQ_EMPTY);
  useEffect(() => { if (open) setF(item ? Object.fromEntries(Object.keys(EQ_EMPTY).map((k) => [k, k === "price_day" ? item[k] ?? "" : item[k] ?? EQ_EMPTY[k]])) : EQ_EMPTY); }, [open, item]);
  const set = (k) => (e) => setF({ ...f, [k]: e?.target ? e.target.value : e });
  const submit = async (e) => {
    e.preventDefault();
    const body = { ...f, qty_total: Number(f.qty_total), price_day: f.price_day === "" || f.price_day == null ? null : Number(f.price_day), replacement_value: Number(f.replacement_value), weight_kg: Number(f.weight_kg), volume_m3: Number(f.volume_m3), prep_days_before: Number(f.prep_days_before) || 0, return_days_after: Number(f.return_days_after) || 0 };
    try { item ? await api.put(`/equipment/${item.id}`, body) : await api.post("/equipment", body); toast.success("Matériel enregistré"); onSaved(); onOpenChange(false); } catch (err) { toast.error(errMsg(err)); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">{item ? "Modifier le matériel" : "Nouveau matériel"}</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="grid grid-cols-2 gap-4" data-testid="equipment-form">
          <Field label="Référence"><Input required value={f.ref} onChange={set("ref")} data-testid="equipment-ref-input" /></Field>
          <Field label="Catégorie"><Input required list="eq-cats" value={f.category} onChange={set("category")} data-testid="equipment-category-select" /><datalist id="eq-cats">{[...new Set([...CATEGORIES, ...(cats || []).map((c) => c[0])])].map((c) => <option key={c} value={c} />)}</datalist></Field>
          <Field label="Sous-catégorie"><Input list="eq-subs" value={f.subcategory} onChange={set("subcategory")} data-testid="equipment-subcategory-input" /><datalist id="eq-subs">{[...new Set((cats || []).filter((c) => c[0] === f.category && c[1]).map((c) => c[1]))].map((c) => <option key={c} value={c} />)}</datalist></Field>
          <Field label="Type"><select className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm" value={f.product_type} onChange={set("product_type")} data-testid="equipment-type-select">{["Location", "Consommable", "Service", "Prestation artistique", "Pack"].map((c) => <option key={c}>{c}</option>)}</select></Field>
          <Field label="Provenance"><Input list="eq-prov" value={f.provenance} onChange={set("provenance")} data-testid="equipment-provenance-input" /><datalist id="eq-prov">{["En stock (parc propre)", "Sous-location partenaire", "Mixte (stock + partenaire)", "Prestataire externe", "Achat à la demande", "Pack (composé)", "Interne", "À qualifier"].map((c) => <option key={c} value={c} />)}</datalist></Field>
          <Field label="Nom" className="col-span-2"><Input required value={f.name} onChange={set("name")} data-testid="equipment-name-input" /></Field>
          <Field label={item ? "Quantité totale (écart appliqué à l'entrepôt par défaut)" : "Quantité totale (Entrepôt par défaut)"}><Input type="number" min="0" required value={f.qty_total} onChange={set("qty_total")} data-testid="equipment-qty-input" /></Field>
          <Field label="Prix location / jour HT (€) — vide = à définir"><Input type="number" min="0" step="0.01" value={f.price_day ?? ""} onChange={set("price_day")} data-testid="equipment-price-input" /></Field>
          <Field label="Valeur de remplacement (€)"><Input type="number" min="0" value={f.replacement_value} onChange={set("replacement_value")} /></Field>
          <Field label="Poids unitaire (kg)"><Input type="number" min="0" step="0.1" value={f.weight_kg} onChange={set("weight_kg")} /></Field>
          <Field label="Volume (m³)"><Input type="number" min="0" step="0.01" value={f.volume_m3} onChange={set("volume_m3")} /></Field>
          <Field label="Temps tampon avant (jours)"><Input type="number" min="0" max="30" value={f.prep_days_before} onChange={set("prep_days_before")} data-testid="equipment-prep-days" /></Field>
          <Field label="Temps tampon après (jours)"><Input type="number" min="0" max="30" value={f.return_days_after} onChange={set("return_days_after")} data-testid="equipment-return-days" /></Field>
          <Field label="Photo du produit"><div className="flex items-center gap-3">{f.photo && <FileImg src={f.photo} className="h-12 w-12 rounded-lg object-cover" />}<UploadButton multiple={false} accept="image/*" label="Photo" testid="equipment-photo-upload" onUploaded={(r) => setF({ ...f, photo: r[0] })} />{f.photo && <Button type="button" size="sm" variant="ghost" onClick={() => setF({ ...f, photo: "" })}>Retirer</Button>}</div></Field>
          <Field label="Description (fiche produit du devis)" className="col-span-2"><Textarea rows={3} value={f.description} onChange={set("description")} data-testid="equipment-description-input" placeholder="Chaise bistro en bois naturel, assise cannée…" /></Field>
          <Field label="Nom anglais (documents en anglais)"><Input value={f.name_en} onChange={set("name_en")} data-testid="equipment-name-en-input" /></Field>
          <div className="flex items-end pb-1"><TranslateButton testid="equipment-translate-button" context="Nom et description d'un produit de location événementielle." texts={{ name_en: f.name, description_en: f.description }} onDone={(r) => setF((cur) => ({ ...cur, ...r }))} /></div>
          <Field label="Description anglaise" className="col-span-2"><Textarea rows={2} value={f.description_en} onChange={set("description_en")} data-testid="equipment-description-en-input" /></Field>
          <Field label="Notes" className="col-span-2"><Textarea rows={2} value={f.notes} onChange={set("notes")} /></Field>
          <DialogFooter className="col-span-2"><Button data-testid="equipment-form-submit">Enregistrer</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function MaintenanceDialog({ item, onOpenChange, onSaved }) {
  const [f, setF] = useState({ action: "start", qty: 1, note: "" });
  useEffect(() => { if (item) setF({ action: item.qty_maintenance ? "end" : "start", qty: 1, note: "" }); }, [item]);
  const submit = async () => {
    try { await api.post(`/equipment/${item.id}/maintenance`, { ...f, qty: Number(f.qty) }); toast.success("Maintenance mise à jour"); onSaved(); onOpenChange(false); } catch (err) { toast.error(errMsg(err)); }
  };
  return (
    <Dialog open={!!item} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>Maintenance · {item?.name}</DialogTitle></DialogHeader>
        <p className="text-sm text-muted-foreground">En maintenance : {item?.qty_maintenance} / {item?.qty_total}. Les unités en maintenance ne sont plus réservables.</p>
        <div className="grid grid-cols-2 gap-3" data-testid="maintenance-form">
          <Field label="Action"><Select value={f.action} onValueChange={(v) => setF({ ...f, action: v })}><SelectTrigger data-testid="maintenance-action-select"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="start">Mettre en maintenance</SelectItem><SelectItem value="end">Remettre en service</SelectItem></SelectContent></Select></Field>
          <Field label="Quantité"><Input type="number" min="1" value={f.qty} onChange={(e) => setF({ ...f, qty: e.target.value })} data-testid="maintenance-qty-input" /></Field>
          <Field label="Note" className="col-span-2"><Input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} placeholder="Révision, réparation…" data-testid="maintenance-note-input" /></Field>
        </div>
        <DialogFooter><Button onClick={submit} data-testid="maintenance-submit">Valider</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function BookingsSheet({ id, onOpenChange }) {
  const [d, setD] = useState(null);
  useEffect(() => { setD(null); if (id) api.get(`/equipment/${id}/bookings`).then((r) => setD(r.data)); }, [id]);
  return (
    <Sheet open={!!id} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader><SheetTitle className="font-display text-2xl font-medium">{d?.name || "…"}</SheetTitle></SheetHeader>
        {d && (
          <div className="mt-4 space-y-4" data-testid="bookings-sheet">
            <div className="text-sm text-muted-foreground">{d.ref} · {d.category} · stock {d.qty_total} (dont {d.qty_maintenance || 0} en maintenance)</div>
            <div className="eyebrow">Réservations (sortie → retour)</div>
            {!d.bookings.length && <div className="text-sm text-muted-foreground">Aucune réservation en cours.</div>}
            {d.bookings.map((b) => (
              <Link key={b.id} to={`/evenements/${b.id}`} className="block rounded-xl border border-border p-3 hover:bg-secondary/50">
                <div className="flex items-center justify-between"><span className="text-sm font-medium">{b.title}</span><StatusBadge status={b.status} /></div>
                <div className="mt-1 text-xs text-muted-foreground">{fmtDT(b.start)} → {fmtDT(b.end)} · {b.qty} unité(s) {b.holds ? "" : "(non bloquant)"}</div>
              </Link>
            ))}
            {d.maintenance_log?.length > 0 && <><div className="eyebrow pt-2">Journal de maintenance</div>
              {[...d.maintenance_log].reverse().map((m) => <div key={m.id} className="text-xs"><b>{m.action === "start" ? "Entrée" : "Sortie"} ×{m.qty}</b> — {m.note} · {m.by} · {new Date(m.at).toLocaleDateString("fr-FR")}</div>)}</>}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

const PK_EMPTY = { name: "", module: "loueur_materiel", description: "", price: 0, items: [], services: [], options: [], active: true };

export function PackDialog({ open, onOpenChange, pack, equipment, onSaved }) {
  const [f, setF] = useState(PK_EMPTY);
  useEffect(() => { if (open) setF(pack ? { ...PK_EMPTY, ...pack } : PK_EMPTY); }, [open, pack]);
  const list = (k) => (e) => setF({ ...f, [k]: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) });
  const submit = async () => {
    const body = { name: f.name, module: f.module, description: f.description, price: Number(f.price), items: f.items.filter((i) => i.equipment_id).map((i) => ({ equipment_id: i.equipment_id, qty: Number(i.qty) })), services: f.services, options: f.options, active: f.active };
    try { pack ? await api.put(`/packs/${pack.id}`, body) : await api.post("/packs", body); toast.success("Pack enregistré"); onSaved(); onOpenChange(false); } catch (err) { toast.error(errMsg(err)); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">{pack ? "Modifier le pack" : "Nouveau pack"}</DialogTitle></DialogHeader>
        <div className="grid grid-cols-2 gap-4" data-testid="pack-form">
          <Field label="Nom" className="col-span-2"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} data-testid="pack-name-input" /></Field>
          <Field label="Module"><Select value={f.module} onValueChange={(v) => setF({ ...f, module: v })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{MODULES.map((m) => <SelectItem key={m.id} value={m.id}>{m.label}</SelectItem>)}</SelectContent></Select></Field>
          <Field label="Prix de vente HT (€)"><Input type="number" min="0" value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} data-testid="pack-price-input" /></Field>
          <Field label="Description" className="col-span-2"><Textarea rows={2} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <Field label="Services inclus (séparés par des virgules)" className="col-span-2"><Input defaultValue={f.services.join(", ")} key={`s-${open}`} onBlur={list("services")} /></Field>
          <Field label="Options (séparées par des virgules)" className="col-span-2"><Input defaultValue={f.options.join(", ")} key={`o-${open}`} onBlur={list("options")} /></Field>
          <div className="col-span-2">
            <div className="mb-2 flex items-center justify-between"><span className="text-xs font-medium text-muted-foreground">Matériel composant le pack</span>
              <Button size="sm" variant="outline" onClick={() => setF({ ...f, items: [...f.items, { equipment_id: "", qty: 1 }] })} data-testid="pack-add-item"><Plus className="mr-1 h-3.5 w-3.5" />Ligne</Button></div>
            {f.items.map((it, i) => (
              <div key={i} className="mb-2 flex gap-2">
                <Select value={it.equipment_id || undefined} onValueChange={(v) => setF({ ...f, items: f.items.map((x, j) => (j === i ? { ...x, equipment_id: v } : x)) })}>
                  <SelectTrigger className="flex-1"><SelectValue placeholder="Choisir" /></SelectTrigger>
                  <SelectContent className="max-h-72">{equipment.map((e) => <SelectItem key={e.id} value={e.id}>{e.ref} · {e.name}</SelectItem>)}</SelectContent></Select>
                <Input type="number" min="1" className="w-20" value={it.qty} onChange={(e) => setF({ ...f, items: f.items.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)) })} />
                <Button size="icon" variant="ghost" onClick={() => setF({ ...f, items: f.items.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></Button>
              </div>
            ))}
          </div>
          <label className="col-span-2 flex items-center gap-2 text-sm"><Switch checked={f.active} onCheckedChange={(v) => setF({ ...f, active: v })} />Commercialisé</label>
        </div>
        <DialogFooter><Button onClick={submit} disabled={!f.name} data-testid="pack-form-submit">Enregistrer</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
