import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, errMsg } from "@/lib/api";

const CLS = [["utilitaire", "Utilitaire (moins de 16 m³)"], ["camion", "Camion (16 m³ et plus)"]];
const n = (v) => Number(String(v).replace(",", ".")) || 0;

export function PricingSettings({ write }) {
  const [f, setF] = useState(null);
  useEffect(() => { api.get("/pricing-settings").then((r) => setF(r.data)).catch((e) => toast.error(errMsg(e))); }, []);
  if (!f) return null;
  const num = (label, value, onChange, tid, w = "w-24") => <label className="flex items-center justify-between gap-2 text-sm">{label}<Input disabled={!write} className={`h-9 ${w}`} type="number" min="0" step="any" value={value} onChange={(e) => onChange(e.target.value)} data-testid={tid} /></label>;
  const zone = (c, i, patch) => setF({ ...f, zone_grid: { ...f.zone_grid, [c]: f.zone_grid[c].map((z, j) => (j === i ? { ...z, ...patch } : z)) } });
  const save = () => api.put("/pricing-settings", { ...f, vehicle_flat_fee: n(f.vehicle_flat_fee), overnight_distance_km: n(f.overnight_distance_km), overnight_return_minutes: Math.round(n(f.overnight_return_minutes)), lodging_default: n(f.lodging_default), meal_default: n(f.meal_default),
    zone_grid: Object.fromEntries(CLS.map(([c]) => [c, f.zone_grid[c].map((z) => ({ max_km: n(z.max_km), price: n(z.price) })).filter((z) => z.max_km > 0)])), client_rate_per_km: Object.fromEntries(CLS.map(([c]) => [c, n(f.client_rate_per_km[c])])),
    shift_lengths: String(f.shift_lengths).split(/[\s,;/]+/).map(n).filter(Boolean), employer_charge_coef: Object.fromEntries(Object.entries(f.employer_charge_coef).map(([k, v]) => [k, n(v)])),
    surcharges: { ...f.surcharges, night_pct: n(f.surcharges.night_pct), sunday_pct: n(f.surcharges.sunday_pct), holiday_pct: n(f.surcharges.holiday_pct) } }).then((r) => { setF(r.data); toast.success("Tarification enregistrée"); }).catch((e) => toast.error(errMsg(e)));
  const card = "rounded-2xl border border-border p-4";
  return (
    <div className="space-y-4" data-testid="pricing-settings">
      <div className={card}><div className="mb-2 font-semibold">Transport</div>
        <label className="flex items-center gap-2 text-sm">Mode de tarification par défaut<select disabled={!write} className="h-9 rounded-lg border border-border bg-background px-2 text-sm" value={f.transport_mode} onChange={(e) => setF({ ...f, transport_mode: e.target.value })} data-testid="pricing-transport-mode"><option value="zone">Forfait par zone</option><option value="computed">Calcul (mise à disposition + km)</option><option value="manual">Manuel</option></select></label>
        <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">{CLS.map(([c, l]) => (
          <div key={c} data-testid={`pricing-grid-${c}`}><div className="mb-1 text-xs font-semibold text-muted-foreground">{l} — forfait par trajet, selon la distance aller</div>
            {f.zone_grid[c].map((z, i) => <div key={i} className="mb-1 flex items-center gap-2 text-sm">jusqu'à<Input disabled={!write} className="h-9 w-20" type="number" value={z.max_km} onChange={(e) => zone(c, i, { max_km: e.target.value })} data-testid={`pricing-zone-km-${c}-${i}`} />km :<Input disabled={!write} className="h-9 w-24" type="number" value={z.price} onChange={(e) => zone(c, i, { price: e.target.value })} data-testid={`pricing-zone-price-${c}-${i}`} />€ HT
              {write && <button type="button" aria-label="Supprimer la zone" onClick={() => setF({ ...f, zone_grid: { ...f.zone_grid, [c]: f.zone_grid[c].filter((_, j) => j !== i) } })}><Trash2 className="h-3.5 w-3.5" /></button>}</div>)}
            {write && <button type="button" className="text-xs underline" onClick={() => setF({ ...f, zone_grid: { ...f.zone_grid, [c]: [...f.zone_grid[c], { max_km: "", price: "" }] } })} data-testid={`pricing-zone-add-${c}`}><Plus className="mr-1 inline h-3 w-3" />Zone</button>}
            <div className="mt-2">{num("Au-delà et en mode calcul : € HT / km", f.client_rate_per_km[c], (v) => setF({ ...f, client_rate_per_km: { ...f.client_rate_per_km, [c]: v } }), `pricing-rate-${c}`)}</div></div>))}</div>
        <div className="mt-3 max-w-md">{num("Mise à disposition du véhicule (mode calcul), € HT", f.vehicle_flat_fee, (v) => setF({ ...f, vehicle_flat_fee: v }), "pricing-flat-fee")}</div></div>
      <div className={card}><div className="mb-2 font-semibold">Main-d'œuvre <span className="text-xs font-normal text-muted-foreground">(utilisé par l'onglet Équipe, étape suivante)</span></div>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          <label className="flex items-center justify-between gap-2 text-sm">Durées de vacation (heures)<Input disabled={!write} className="h-9 w-32" value={Array.isArray(f.shift_lengths) ? f.shift_lengths.join(" / ") : f.shift_lengths} onChange={(e) => setF({ ...f, shift_lengths: e.target.value })} data-testid="pricing-shifts" /></label>
          {[["night_pct", `Majoration nuit (${f.surcharges.night_start}–${f.surcharges.night_end}) %`], ["sunday_pct", "Majoration dimanche %"], ["holiday_pct", "Majoration jour férié %"]].map(([k, l]) => <div key={k}>{num(l, f.surcharges[k], (v) => setF({ ...f, surcharges: { ...f.surcharges, [k]: v } }), `pricing-${k}`)}</div>)}
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!write} checked={f.surcharges.cumulative} onChange={(e) => setF({ ...f, surcharges: { ...f.surcharges, cumulative: e.target.checked } })} data-testid="pricing-cumulative" />Majorations cumulées (sinon la plus forte s'applique)</label>
          {Object.entries(f.employer_charge_coef).map(([k, v]) => <div key={k}>{num(`Coefficient de charges ${k.toUpperCase()}`, v, (x) => setF({ ...f, employer_charge_coef: { ...f.employer_charge_coef, [k]: x } }), `pricing-coef-${k}`)}</div>)}</div>
        <p className="mt-2 text-xs text-muted-foreground">Coefficients indicatifs : à valider avec votre comptable.</p></div>
      <div className={card}><div className="mb-2 font-semibold">Frais de mission <span className="text-xs font-normal text-muted-foreground">(étape suivante)</span></div>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {num("Nuitée proposée si distance aller > (km)", f.overnight_distance_km, (v) => setF({ ...f, overnight_distance_km: v }), "pricing-overnight-km")}
          <label className="flex items-center justify-between gap-2 text-sm">… ou fin après<Input disabled={!write} className="h-9 w-24" type="time" value={f.overnight_end_hour} onChange={(e) => setF({ ...f, overnight_end_hour: e.target.value })} data-testid="pricing-overnight-hour" /></label>
          {num("… avec un retour de plus de (min)", f.overnight_return_minutes, (v) => setF({ ...f, overnight_return_minutes: v }), "pricing-overnight-min")}
          {num("Nuitée par défaut, € HT", f.lodging_default, (v) => setF({ ...f, lodging_default: v }), "pricing-lodging")}
          {num("Repas par défaut, € HT", f.meal_default, (v) => setF({ ...f, meal_default: v }), "pricing-meal")}
          <label className="flex items-center justify-between gap-2 text-sm">Nom de la section du devis<Input disabled={!write} className="h-9 w-56" value={f.logistics_section} onChange={(e) => setF({ ...f, logistics_section: e.target.value })} data-testid="pricing-section-name" /></label></div></div>
      {write && <Button onClick={save} data-testid="pricing-save">Enregistrer la tarification</Button>}
    </div>);
}
