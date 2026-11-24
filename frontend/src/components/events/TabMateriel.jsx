import { useEffect, useMemo, useState } from "react";
import { Plus, Trash2, AlertTriangle, CheckCircle2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Section, Field, EmptyState } from "@/components/common";
import { cleanLine } from "@/components/events/TabsInfoPrestations";
import { api } from "@/lib/api";
import { fmtEur, ITEM_STATES, DEPOSIT_STATUSES } from "@/lib/constants";
import { useMe } from "@/context/MeContext";
import { RentalPeriod } from "@/components/events/Overlaps";
import { EventRequirements } from "@/components/catalogue/Material";
import { EventOrigin } from "@/components/stock/Availability";
import { EventLogistics } from "@/components/logistics/EventLogistics";
import { EventShortages } from "@/components/logistics/Shortages";
import { EventKits } from "@/components/catalogue/Kits";
import { dual, toPieces, uomLabel } from "@/components/catalogue/Units";
import { Mobilized } from "@/components/events/Mobilized";

const HOLD = ["devis_envoye", "confirme", "en_preparation", "realise"];

function Rental({ ev, save, write }) {
  const [r, setR] = useState(ev.rental || {});
  const [lines, setLines] = useState([]);
  useEffect(() => { setR(ev.rental || {}); setLines((ev.equipment || []).map((l) => ({ ...l }))); }, [ev]);
  const upd = (i, k, v) => setLines(lines.map((l, j) => (j === i ? { ...l, [k]: v } : l)));
  const saveAll = () => save({ rental: { ...r, deposit_amount: Number(r.deposit_amount) || 0 }, equipment: lines.map(cleanLine) }, "Fiche location enregistrée");
  const markReturned = (val) => save({ material_returned: val, equipment: lines.map((l) => cleanLine(val ? { ...l, qty_returned: l.qty_returned || l.qty, state_in: l.state_in || "OK" } : l)) }, val ? "Retour du matériel validé" : "Retour annulé");
  return (
    <Section title="Location : caution & contrôle départ / retour" testid="rental-section"
      actions={ev.material_returned ? <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-700" data-testid="material-returned-flag"><CheckCircle2 className="h-4 w-4" />Matériel retourné</span> : null}>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {r.deposit_amount !== undefined && <Field label="Caution (€)"><Input type="number" min="0" disabled={!write} data-testid="deposit-amount-input" value={r.deposit_amount ?? 0} onChange={(e) => setR({ ...r, deposit_amount: e.target.value })} /></Field>}
        <Field label="Statut de la caution">
          <Select disabled={!write} value={r.deposit_status || "non_demandee"} onValueChange={(v) => setR({ ...r, deposit_status: v })}><SelectTrigger data-testid="deposit-status-select"><SelectValue /></SelectTrigger>
            <SelectContent>{DEPOSIT_STATUSES.map((d) => <SelectItem key={d.id} value={d.id}>{d.label}</SelectItem>)}</SelectContent></Select>
        </Field>
        <Field label="Sortie effective"><Input type="datetime-local" disabled={!write} data-testid="rental-out-input" value={r.out_at || ""} onChange={(e) => setR({ ...r, out_at: e.target.value })} /></Field>
        <Field label="Retour effectif"><Input type="datetime-local" disabled={!write} data-testid="rental-return-input" value={r.return_at || ""} onChange={(e) => setR({ ...r, return_at: e.target.value })} /></Field>
      </div>
      {lines.length > 0 && (
        <div className="mt-5 overflow-x-auto">
          <Table>
            <TableHeader><TableRow><TableHead>Matériel</TableHead><TableHead>Qté</TableHead><TableHead>État au départ</TableHead><TableHead>État au retour</TableHead><TableHead>Qté retournée</TableHead></TableRow></TableHeader>
            <TableBody>
              {lines.map((l, i) => (
                <TableRow key={l.equipment_id}>
                  <TableCell><span className="font-mono text-xs text-muted-foreground">{l.ref}</span> {l.name}</TableCell>
                  <TableCell>{l.qty}</TableCell>
                  {["state_out", "state_in"].map((k) => (
                    <TableCell key={k}>
                      <Select disabled={!write} value={l[k] || "none"} onValueChange={(v) => upd(i, k, v === "none" ? "" : v)}><SelectTrigger className="h-8 w-32" data-testid={`${k}-${l.equipment_id}`}><SelectValue /></SelectTrigger>
                        <SelectContent><SelectItem value="none">—</SelectItem>{ITEM_STATES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent></Select>
                    </TableCell>
                  ))}
                  <TableCell><Input type="number" min="0" max={l.qty} disabled={!write} className="h-8 w-20" value={l.qty_returned || 0} onChange={(e) => upd(i, "qty_returned", e.target.value)} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {write && (
        <div className="mt-5 flex flex-wrap gap-2">
          <Button variant="outline" onClick={saveAll} data-testid="save-rental-button">Enregistrer la fiche</Button>
          {ev.material_returned
            ? <Button variant="ghost" onClick={() => markReturned(false)} data-testid="undo-return-button"><RotateCcw className="mr-1.5 h-4 w-4" />Annuler le retour</Button>
            : <Button onClick={() => markReturned(true)} disabled={!lines.length} data-testid="mark-returned-button"><CheckCircle2 className="mr-1.5 h-4 w-4" />Valider le retour du matériel</Button>}
        </div>
      )}
    </Section>
  );
}

export default function MaterielTab({ ev, save, reload }) {
  const { can, modules } = useMe();
  const write = can("events:write");
  const [stock, setStock] = useState([]);
  const [lines, setLines] = useState([]);
  const [pick, setPick] = useState("");
  const [qty, setQty] = useState(1);

  useEffect(() => { setLines((ev.equipment || []).map((l) => ({ ...l }))); }, [ev]);
  const pStart = ev.rental_start || ev.setup_start;
  const pEnd = ev.rental_end || ev.return_end;
  const zones = ev.venue?.sections || [];
  useEffect(() => { api.get("/equipment", { params: { start: pStart, end: pEnd } }).then((r) => setStock(r.data.items)); }, [pStart, pEnd, ev.equipment]);

  const selfHolds = HOLD.includes(ev.status) && !ev.material_returned;
  const availFor = useMemo(() => {
    const own = Object.fromEntries((ev.equipment || []).map((l) => [l.equipment_id, l.qty]));
    return (id) => { const s = stock.find((x) => x.id === id); return s ? s.available + (selfHolds ? own[id] || 0 : 0) : 0; };
  }, [stock, ev.equipment, selfHolds]);
  const conflicts = Object.fromEntries((ev.conflicts || []).map((c) => [c.equipment_id, c]));
  const dirty = JSON.stringify(lines.map(cleanLine)) !== JSON.stringify((ev.equipment || []).map(cleanLine));

  const add = () => {
    const s = stock.find((x) => x.id === pick);
    if (!s) return;
    const ex = lines.find((l) => l.equipment_id === pick);
    if (ex) setLines(lines.map((l) => (l.equipment_id === pick ? { ...l, qty: Number(l.qty) + Number(qty) } : l)));
    else setLines([...lines, { equipment_id: s.id, ref: s.ref, name: s.name, category: s.category, qty: Number(qty), price_day: s.price_day, weight_kg: s.weight_kg }]);
    setPick(""); setQty(1);
  };
  const weight = lines.reduce((n, l) => n + (l.weight_kg || 0) * l.qty, 0);

  return (
    <div className="space-y-6">
      <Section title="Matériel réservé" testid="materiel-section"
        actions={<div className="text-xs text-muted-foreground">Période : {pStart.replace("T", " ")} → {pEnd.replace("T", " ")} · {Math.round(weight)} kg</div>}>
        <RentalPeriod ev={ev} save={save} write={write} />
        {write && (
          <div className="mb-4 flex flex-wrap items-end gap-2 rounded-xl bg-secondary/60 p-3">
            <Field label="Ajouter du matériel" className="min-w-[260px] flex-1">
              <Select value={pick} onValueChange={setPick}><SelectTrigger className="bg-card" data-testid="add-equipment-select"><SelectValue placeholder="Choisir une référence" /></SelectTrigger>
                <SelectContent className="max-h-72">{stock.map((s) => <SelectItem key={s.id} value={s.id}>{s.ref} · {s.name} — dispo {availFor(s.id)}</SelectItem>)}</SelectContent></Select>
            </Field>
            <Field label="Quantité"><Input type="number" min="0" step="any" className="w-24 bg-card" data-testid="add-equipment-qty" value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
            <Button variant="outline" className="bg-card" onClick={add} disabled={!pick} data-testid="add-equipment-button"><Plus className="mr-1 h-4 w-4" />Ajouter</Button>
          </div>
        )}
        {!lines.length ? <EmptyState title="Aucun matériel" text="Ajoutez des références ou un pack depuis l'onglet Prestations." /> : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow><TableHead>Référence</TableHead><TableHead>Désignation</TableHead><TableHead>Qté</TableHead>{zones.length > 0 && <TableHead>Espace</TableHead>}<TableHead>Disponible</TableHead>{can("finance:read") && <><TableHead>Prix/jour</TableHead><TableHead className="text-right">Total ({ev.rental_days} j)</TableHead></>}<TableHead /></TableRow></TableHeader>
              <TableBody>
                {lines.map((l, i) => {
                  const c = conflicts[l.equipment_id];
                  const av = availFor(l.equipment_id);
                  const short = Number(l.qty) > av;
                  return (
                    <TableRow key={l.equipment_id} className={c || short ? "bg-red-500/10" : ""} data-testid={`equipment-line-${l.equipment_id}`}>
                      <TableCell className="font-mono text-xs">{l.ref}</TableCell>
                      <TableCell>{l.name}<div className="text-xs text-muted-foreground">{l.category}</div></TableCell>
                      <TableCell>{(() => { const eq = stock.find((x) => x.id === l.equipment_id) || {}; const sec = l.entered_uom === "secondary" && eq.secondary_uom; const set = (patch) => setLines(lines.map((x, j) => (j === i ? { ...x, ...patch } : x)));
                        return (<><div className="flex gap-1"><Input type="number" min="0" step="any" disabled={!write} className="h-8 w-20" data-testid={`equipment-qty-${l.equipment_id}`} value={sec ? l.entered_qty ?? "" : l.qty} onChange={(e) => set(sec ? { entered_qty: e.target.value, qty: toPieces(eq, e.target.value) } : { qty: e.target.value })} />
                          {eq.secondary_uom && eq.qty_per_piece ? <select disabled={!write} className="h-8 rounded-md border border-input bg-transparent px-1 text-xs" value={sec ? "secondary" : ""} onChange={(e) => set(e.target.value ? { entered_uom: "secondary", entered_qty: l.qty * eq.qty_per_piece } : { entered_uom: "", entered_qty: null })} data-testid={`equipment-uom-${l.equipment_id}`}><option value="">{uomLabel(eq.stock_uom, 1)}</option><option value="secondary">{eq.secondary_uom}</option></select> : eq.stock_uom && eq.stock_uom !== "piece" ? <span className="self-center text-xs text-muted-foreground">{eq.stock_uom}</span> : null}</div>
                          {sec && <div className="mt-0.5 text-xs text-muted-foreground" data-testid={`equipment-conv-${l.equipment_id}`}>{l.entered_qty} {eq.secondary_uom} demandés · {dual(eq, l.qty).replace(" · ", " (")}) sorties</div>}</>); })()}</TableCell>
                      {zones.length > 0 && <TableCell><select disabled={!write} className="h-8 rounded-md border border-input bg-transparent px-2 text-xs" value={l.section_id || ""} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, section_id: e.target.value } : x)))} data-testid={`equipment-section-${l.equipment_id}`}><option value="">—</option>{zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}</select></TableCell>}
                      <TableCell>{short ? <span className="flex items-center gap-1 text-xs font-semibold text-red-700"><AlertTriangle className="h-3.5 w-3.5" />{av} dispo</span> : <span className="text-xs text-emerald-700">{av} dispo</span>}</TableCell>
                      {can("finance:read") && <><TableCell>{fmtEur(l.price_day)}</TableCell><TableCell className="text-right font-medium">{fmtEur((l.price_day || 0) * l.qty * ev.rental_days)}</TableCell></>}
                      <TableCell>{write && <Button size="icon" variant="ghost" onClick={() => setLines(lines.filter((_, j) => j !== i))} data-testid={`remove-equipment-${l.equipment_id}`}><Trash2 className="h-4 w-4" /></Button>}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
        {write && dirty && (
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setLines((ev.equipment || []).map((l) => ({ ...l })))}>Annuler</Button>
            <Button onClick={() => save({ equipment: lines.map(cleanLine) }, "Matériel enregistré")} data-testid="save-equipment-button">Enregistrer le matériel</Button>
          </div>
        )}
        <EventRequirements eventId={ev.id} write={write} version={JSON.stringify([(ev.equipment || []).map((l) => [l.equipment_id, l.qty]), ev.start, ev.end, ev.rental_days])} />
      </Section>
      <Mobilized eid={ev.id} />
      <EventOrigin ev={ev} write={write} />
      <EventKits ev={ev} write={write} onChanged={reload} />
      <EventShortages ev={{ ...ev, kit_v: JSON.stringify((ev.kit_instances || []).map((k) => k.updated_at)) }} write={write} />
      <EventLogistics ev={ev} write={write} />
      {modules.includes("loueur_materiel") && <Rental ev={ev} save={save} write={write} />}
    </div>
  );
}
