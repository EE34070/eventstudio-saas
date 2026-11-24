import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, errMsg } from "@/lib/api";
import { TaxEstimate } from "@/components/finance/TaxEstimate";

const ko = (e) => toast.error(errMsg(e));
const sel = "mt-1 h-9 w-full rounded-lg border border-border bg-background px-2 text-sm";
const CHECKS = [["capital_libere", "Capital entièrement libéré"], ["detention_75", "Détenue à 75 % au moins par des personnes physiques (ou par une société elle-même éligible)"], ["ca_sous_seuil", "Chiffre d'affaires HT sous le seuil (apprécié au niveau du groupe le cas échéant)"]];

export function TaxTab() {
  const [d, setD] = useState(null);
  const [f, setF] = useState(null);
  const [rates, setRates] = useState([]);
  const fill = (x) => { setD(x); setF(x.settings); setRates(x.rates); };
  useEffect(() => { api.get("/finance/tax-settings").then((r) => fill(r.data)).catch(ko); }, []);
  if (!f) return null;
  const ro = !d.can_manage;
  const pick = (k, l, opts) => <label className="text-xs text-muted-foreground">{l}<select className={sel} disabled={ro} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} data-testid={`tax-${k}`}>{opts.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></label>;
  const saveRate = (r) => api.put("/finance/tax-rates", r).then((x) => { fill(x.data); toast.success("Barème enregistré"); }).catch(ko);
  return (
    <div className="space-y-4" data-testid="tax-tab">
      <TaxEstimate key={JSON.stringify(d.settings) + rates.length} />
      <div className="rounded-2xl border border-border p-4"><b>Paramètres fiscaux de la société</b> <span className="text-xs text-muted-foreground">{d.note}</span>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          {pick("regime", "Régime d'imposition", [["is", "Impôt sur les sociétés"], ["ir", "Impôt sur le revenu"]])}
          {pick("tva_regime", "Régime de TVA", [["reel_mensuel", "Réel normal mensuel"], ["reel_trimestriel", "Réel normal trimestriel"], ["simplifie", "Simplifié"], ["franchise", "Franchise en base"]])}
          {pick("tva_exigibilite", "Exigibilité de la TVA", [["encaissements", "Sur les encaissements (prestations de services)"], ["debits", "Sur les débits (option)"]])}
          <label className="text-xs text-muted-foreground">Date de clôture (JJ/MM)<Input className="mt-1" disabled={ro} value={f.closing.split("-").reverse().join("/")} onChange={(e) => { const m = e.target.value.match(/^(\d{0,2})\/?(\d{0,2})$/); if (m) setF({ ...f, closing: `${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}` }); }} data-testid="tax-closing" /></label>
          {pick("liasse", "Régime de la liasse", [["2033", "Simplifié (2033)"], ["2050", "Réel normal (2050)"]])}
          <label className="text-xs text-muted-foreground">Commune de la CFE<Input className="mt-1" disabled={ro} value={f.cfe_commune} onChange={(e) => setF({ ...f, cfe_commune: e.target.value })} data-testid="tax-cfe" /></label></div>
        <div className="mt-3 text-sm"><b>Éligibilité au taux réduit d'IS</b>{CHECKS.map(([k, l]) => <label key={k} className="flex items-center gap-2"><input type="checkbox" disabled={ro} checked={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.checked })} data-testid={`tax-${k}`} />{l}</label>)}
          <p className={`mt-1 font-semibold ${CHECKS.every(([k]) => f[k]) ? "text-emerald-700" : "text-muted-foreground"}`} data-testid="tax-eligible">{CHECKS.every(([k]) => f[k]) ? "Société éligible au taux réduit" : "Taux réduit non applicable tant que les trois conditions ne sont pas cochées"}</p>
          <label className="mt-2 flex items-center gap-2"><input type="checkbox" disabled={ro} checked={f.integration_fiscale} onChange={(e) => setF({ ...f, integration_fiscale: e.target.checked })} data-testid="tax-integration" />Intégration fiscale</label>
          {f.integration_fiscale && <Input className="mt-1 max-w-sm" placeholder="Tête de groupe" disabled={ro} value={f.tete_groupe} onChange={(e) => setF({ ...f, tete_groupe: e.target.value })} />}</div>
        {!ro && <Button className="mt-3" size="sm" onClick={() => api.put("/finance/tax-settings", f).then((r) => { fill(r.data); toast.success("Paramètres fiscaux enregistrés"); }).catch(ko)} data-testid="tax-save">Enregistrer</Button>}</div>
      <div className="rounded-2xl border border-border p-4" data-testid="tax-rates"><b>Barèmes</b> <span className="text-xs text-muted-foreground">Table datée et modifiable : aucun taux n'est figé dans l'application. {d.note}</span>
        {rates.map((r, i) => <div key={r.id} className="mt-3 border-t border-border pt-2 text-sm" data-testid={`tax-rate-${r.tax}`}><div className="flex flex-wrap items-center gap-2"><b>{r.label || r.tax}</b>
          <label className="text-xs text-muted-foreground">à partir du <input type="date" disabled={ro} className="rounded border border-border bg-background px-1" value={r.valid_from} onChange={(e) => setRates(rates.map((x, j) => (j === i ? { ...x, valid_from: e.target.value } : x)))} /></label>
          <label className="text-xs text-muted-foreground">jusqu'au <input type="date" disabled={ro} className="rounded border border-border bg-background px-1" value={r.valid_to} onChange={(e) => setRates(rates.map((x, j) => (j === i ? { ...x, valid_to: e.target.value } : x)))} /></label><span className="flex-1" />
          {!ro && <><Button size="sm" variant="ghost" onClick={() => saveRate({ ...r, id: "", valid_from: new Date().toISOString().slice(0, 10) })} data-testid={`tax-rate-dup-${r.tax}`}>Nouvelle période</Button><Button size="sm" variant="outline" onClick={() => saveRate(r)} data-testid={`tax-rate-save-${r.tax}`}>Enregistrer</Button></>}</div>
          <div className="mt-1 grid gap-2 sm:grid-cols-3">{Object.entries(r.params).map(([k, v]) => <label key={k} className="text-xs text-muted-foreground">{k.replaceAll("_", " ")}<Input type="number" disabled={ro} className="mt-1 h-8" value={v} onChange={(e) => setRates(rates.map((x, j) => (j === i ? { ...x, params: { ...x.params, [k]: Number(e.target.value) } } : x)))} data-testid={`tax-param-${k}`} /></label>)}</div></div>)}</div>
    </div>);
}
