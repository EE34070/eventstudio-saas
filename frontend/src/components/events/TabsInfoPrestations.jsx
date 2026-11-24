import { useEffect, useState } from "react";
import { Plus, Trash2, Pencil, Truck, Zap, Volume2, Clock, Package } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Section, Info, Field, ModuleBadge, EmptyState } from "@/components/common";
import { api } from "@/lib/api";
import { MODULES, fmtEur, fmtDT } from "@/lib/constants";
import { useMe } from "@/context/MeContext";
import { OnsiteCard } from "@/components/events/OnsiteContacts";
import { PeopleCards } from "@/components/events/PeopleFields";

export function InfosTab({ ev }) {
  const v = ev.venue;
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <PeopleCards ev={ev} />
      <Section title="Dates & logistique" testid="infos-dates">
        <div className="grid grid-cols-2 gap-4">
          <Info label="Sortie dépôt / montage" value={fmtDT(ev.setup_start)} />
          <Info label="Retour dépôt" value={fmtDT(ev.return_end)} />
          <Info label="Début" value={fmtDT(ev.start)} />
          <Info label="Fin" value={fmtDT(ev.end)} />
          <Info label="Invités" value={ev.guests} />
          <Info label="Jours facturés" value={ev.rental_days} />
          {ev.budget > 0 && <Info label={`Budget global ${ev.budget_tax_mode === "ht" ? "HT" : "TTC"}`} value={fmtEur(ev.budget)} />}
          {ev.delivery_venue && <Info label="Lieu de livraison" value={`${ev.delivery_venue.name} · ${ev.delivery_venue.city}`} />}
          {ev.modules?.length > 0 && <div className="col-span-2" data-testid="infos-modules"><div className="eyebrow mb-1">Modules</div><div className="flex flex-wrap gap-1.5">{ev.modules.map((m) => <span key={m.module_key} className="rounded-full border border-border px-2.5 py-0.5 text-xs">{m.label}{m.budget_amount > 0 ? ` · ${fmtEur(m.budget_amount)}` : ""}</span>)}</div></div>}
        </div>
        {ev.notes && <p className="mt-4 whitespace-pre-line rounded-lg bg-secondary p-3 text-sm">{ev.notes}</p>}
      </Section>
      <Section title="Lieu de réception" testid="infos-venue">
        {v ? (
          <div className="space-y-3 text-sm">
            <div className="font-medium">{v.name}</div>
            <div className="text-muted-foreground">{v.address}, {v.zip} {v.city}</div>
            <div className="flex gap-2"><Truck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />{v.truck_access || "—"}</div>
            <div className="flex gap-2"><Zap className="mt-0.5 h-4 w-4 shrink-0 text-primary" />{v.electricity || "—"}</div>
            <div className="flex gap-2"><Volume2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />{v.sound_limiter || "—"}</div>
            <div className="flex gap-2"><Clock className="mt-0.5 h-4 w-4 shrink-0 text-primary" />{v.setup_hours} · {v.teardown_hours}</div>
            {v.lat && <a className="inline-block text-xs font-medium text-primary underline" target="_blank" rel="noreferrer" href={`https://www.google.com/maps/dir/?api=1&destination=${v.lat},${v.lng}`}>Itinéraire</a>}
            <OnsiteCard ev={ev} />
          </div>
        ) : <div className="text-sm text-muted-foreground">Lieu à définir.</div>}
      </Section>
    </div>
  );
}

function PrestationDialog({ open, onOpenChange, initial, modules, onSubmit }) {
  const [p, setP] = useState(initial);
  useEffect(() => { if (open) setP(initial); }, [open, initial]);
  if (!p) return null;
  const def = MODULES.find((m) => m.id === p.module);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">{initial?.id ? "Modifier la prestation" : "Nouvelle prestation"}</DialogTitle></DialogHeader>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2" data-testid="prestation-form">
          <Field label="Module métier">
            <Select value={p.module} onValueChange={(v) => setP({ ...p, module: v, fields: {} })}><SelectTrigger data-testid="prestation-module-select"><SelectValue /></SelectTrigger>
              <SelectContent>{MODULES.filter((m) => modules.includes(m.id) || m.id === p.module).map((m) => <SelectItem key={m.id} value={m.id}>{m.label}</SelectItem>)}</SelectContent></Select>
          </Field>
          <Field label="Intitulé"><Input data-testid="prestation-title-input" value={p.title} onChange={(e) => setP({ ...p, title: e.target.value })} /></Field>
          <Field label="Prix de vente HT (€)"><Input type="number" min="0" data-testid="prestation-price-input" value={p.price} onChange={(e) => setP({ ...p, price: e.target.value })} /></Field>
          <Field label="Coût estimé (€)"><Input type="number" min="0" data-testid="prestation-cost-input" value={p.cost} onChange={(e) => setP({ ...p, cost: e.target.value })} /></Field>
          {def?.fields.map((f) => (
            <Field key={f.key} label={f.label} className={f.type === "textarea" ? "sm:col-span-2" : ""}>
              {f.type === "textarea"
                ? <Textarea rows={2} data-testid={`prestation-field-${f.key}`} value={p.fields?.[f.key] || ""} onChange={(e) => setP({ ...p, fields: { ...p.fields, [f.key]: e.target.value } })} />
                : <Input data-testid={`prestation-field-${f.key}`} value={p.fields?.[f.key] || ""} onChange={(e) => setP({ ...p, fields: { ...p.fields, [f.key]: e.target.value } })} />}
            </Field>
          ))}
        </div>
        <DialogFooter><Button data-testid="prestation-submit" disabled={!p.title} onClick={() => onSubmit({ ...p, price: Number(p.price) || 0, cost: Number(p.cost) || 0 })}>Enregistrer</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const clean = (p) => ({ id: p.id, module: p.module, title: p.title, price: p.price, cost: p.cost, fields: p.fields || {} });
export const cleanLine = (l) => ({ equipment_id: l.equipment_id, qty: Number(l.qty), entered_qty: l.entered_uom === "secondary" ? Number(l.entered_qty) || null : null, entered_uom: l.entered_uom === "secondary" ? "secondary" : "", price_day: l.price_day, state_out: l.state_out || "", state_in: l.state_in || "", qty_returned: Number(l.qty_returned) || 0, section_id: l.section_id || "" });

export function PrestationsTab({ ev, save }) {
  const { can, modules } = useMe();
  const [dlg, setDlg] = useState(null);
  const [packs, setPacks] = useState([]);
  const [pack, setPack] = useState("");
  useEffect(() => { api.get("/packs").then((r) => setPacks(r.data)); }, []);
  const write = can("events:write");
  const list = ev.prestations || [];

  const submit = async (p) => {
    const next = p.id ? list.map((x) => (x.id === p.id ? p : x)) : [...list, p];
    if (await save({ prestations: next.map(clean) })) setDlg(null);
  };
  const remove = (pid) => save({ prestations: list.filter((x) => x.id !== pid).map(clean) }, "Prestation retirée");
  const addPack = async () => {
    const pk = packs.find((x) => x.id === pack);
    if (!pk) return;
    const lines = (ev.equipment || []).map(cleanLine);
    pk.items.forEach((it) => {
      const l = lines.find((x) => x.equipment_id === it.equipment_id);
      if (l) l.qty += it.qty; else lines.push({ equipment_id: it.equipment_id, qty: it.qty, price_day: null, state_out: "", state_in: "", qty_returned: 0 });
    });
    const prest = { id: "", module: pk.module, title: pk.name, price: pk.price, cost: 0, fields: { notes: [pk.description, ...pk.services].filter(Boolean).join(" · ") } };
    if (await save({ prestations: [...list.map(clean), prest], equipment: lines }, `Pack « ${pk.name} » ajouté`)) setPack("");
  };

  return (
    <Section title="Prestations" testid="prestations-section"
      actions={write && (
        <div className="flex flex-wrap gap-2">
          <Select value={pack} onValueChange={setPack}><SelectTrigger className="w-56" data-testid="pack-select"><SelectValue placeholder="Ajouter un pack du catalogue" /></SelectTrigger>
            <SelectContent>{packs.filter((p) => p.active).map((p) => <SelectItem key={p.id} value={p.id}>{p.name} · {fmtEur(p.price)}</SelectItem>)}</SelectContent></Select>
          {pack && <Button variant="outline" onClick={addPack} data-testid="add-pack-button"><Package className="mr-1.5 h-4 w-4" />Ajouter</Button>}
          <Button data-testid="add-prestation-button" onClick={() => setDlg({ id: "", module: modules[0] || "loueur_materiel", title: "", price: 0, cost: 0, fields: {} })}><Plus className="mr-1.5 h-4 w-4" />Prestation</Button>
        </div>
      )}>
      {!list.length ? <EmptyState title="Aucune prestation" text="Ajoutez une prestation par module métier ou un pack du catalogue (le matériel du pack est réservé automatiquement)." /> : (
        <div className="divide-y divide-border">
          {list.map((p) => {
            const def = MODULES.find((m) => m.id === p.module);
            const filled = def?.fields.filter((f) => p.fields?.[f.key]) || [];
            return (
              <div key={p.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-start" data-testid={`prestation-${p.id}`}>
                <div className="flex-1">
                  <div className="flex items-center gap-2"><ModuleBadge module={p.module} /><span className="font-medium">{p.title}</span></div>
                  {filled.length > 0 && (
                    <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
                      {filled.map((f) => <div key={f.key}><dt className="inline text-muted-foreground">{f.label} : </dt><dd className="inline">{p.fields[f.key]}</dd></div>)}
                    </dl>
                  )}
                </div>
                {p.price != null && <div className="text-right"><div className="font-semibold">{fmtEur(p.price)}</div><div className="text-xs text-muted-foreground">coût {fmtEur(p.cost)}</div></div>}
                {write && <div className="flex gap-1"><Button size="icon" variant="ghost" onClick={() => setDlg(p)} data-testid={`edit-prestation-${p.id}`}><Pencil className="h-4 w-4" /></Button><Button size="icon" variant="ghost" onClick={() => remove(p.id)} data-testid={`delete-prestation-${p.id}`}><Trash2 className="h-4 w-4" /></Button></div>}
              </div>
            );
          })}
        </div>
      )}
      <PrestationDialog open={!!dlg} onOpenChange={(o) => !o && setDlg(null)} initial={dlg} modules={modules} onSubmit={submit} />
    </Section>
  );
}
