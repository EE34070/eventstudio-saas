import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PageHeader, Loading } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { ForecastTab } from "@/components/finance/Forecast";
import { ReportTab } from "@/components/finance/Report";
import { StatementsTab } from "@/components/finance/Statements";
import { TaxTab } from "@/components/finance/Tax";

export const TABS = [["dashboard", "Tableau de bord"], ["activite", "Activité"], ["marges", "Marges & rentabilité"], ["tresorerie", "Trésorerie"], ["echeancier", "Échéancier & encaissements"], ["charges", "Charges & structure"], ["budget", "Budget & suivi"], ["previsionnel", "Prévisionnel"], ["etats", "États financiers"], ["impots", "Impôts & fiscalité"]];
const LATER = ["tresorerie", "echeancier", "charges", "budget"];
const sel = "h-9 rounded-lg border border-border bg-card px-2 text-sm";
const csv = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);
export const NotConnected = ({ what = "Les données réelles" }) => <div className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground" data-testid="pennylane-off">{what} : <b>Pennylane non connecté</b>.</div>;

function SettingsDialog({ open, onOpenChange, cfg, onSaved }) {
  const [f, setF] = useState(null);
  useEffect(() => { if (open && cfg) setF(JSON.parse(JSON.stringify(cfg))); }, [open, cfg]);
  if (!f) return null;
  const up = (k, i, key, v) => setF({ ...f, [k]: f[k].map((x, j) => (j === i ? { ...x, [key]: v } : x)) });
  const num = (k, l, tid) => <label className="text-xs text-muted-foreground">{l}<Input className="mt-1" type="number" min="0" value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value === "" ? null : Number(e.target.value) })} data-testid={tid} /></label>;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto" data-testid="finance-settings-dialog">
      <DialogHeader><DialogTitle>Réglages Finance</DialogTitle><DialogDescription>Activités (affectées aux lignes de devis par la catégorie du catalogue ou par mots-clés) et canaux (repris de la source CRM).</DialogDescription></DialogHeader>
      <div className="eyebrow">Activités</div>
      {f.activities.map((a, i) => <div key={i} className="grid grid-cols-12 gap-2" data-testid={`fin-activity-${i}`}><Input className="col-span-3" value={a.name} onChange={(e) => up("activities", i, "name", e.target.value)} data-testid={`fin-activity-name-${i}`} />
        <Input className="col-span-4" placeholder="Catégories catalogue (virgules)" title={`Catégories existantes : ${cfg.catalog_categories.join(", ")}`} value={a.categories.join(", ")} onChange={(e) => up("activities", i, "categories", csv(e.target.value))} />
        <Input className="col-span-4" placeholder="Mots-clés (virgules)" value={a.keywords.join(", ")} onChange={(e) => up("activities", i, "keywords", csv(e.target.value))} />
        <button aria-label="Supprimer" onClick={() => setF({ ...f, activities: f.activities.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></button></div>)}
      <button className="text-left text-sm underline" onClick={() => setF({ ...f, activities: [...f.activities, { id: "", name: "", color: "gris", categories: [], keywords: [] }] })} data-testid="fin-activity-add"><Plus className="mr-1 inline h-3.5 w-3.5" />Activité</button>
      <div className="eyebrow mt-2">Canaux</div>
      {f.channels.map((c, i) => <div key={i} className="grid grid-cols-12 gap-2" data-testid={`fin-channel-${i}`}><Input className="col-span-4" value={c.name} onChange={(e) => up("channels", i, "name", e.target.value)} data-testid={`fin-channel-name-${i}`} />
        <select className={`${sel} col-span-3`} value={c.type} onChange={(e) => up("channels", i, "type", e.target.value)}><option value="direct">Client direct</option><option value="planner">Wedding planner</option><option value="venue">Lieu</option><option value="other">Autre</option></select>
        <Input className="col-span-4" placeholder="Sources CRM (clés, virgules)" value={c.source_keys.join(", ")} onChange={(e) => up("channels", i, "source_keys", csv(e.target.value))} />
        <button aria-label="Supprimer" onClick={() => setF({ ...f, channels: f.channels.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></button></div>)}
      <button className="text-left text-sm underline" onClick={() => setF({ ...f, channels: [...f.channels, { id: "", name: "", type: "other", source_keys: [] }] })}><Plus className="mr-1 inline h-3.5 w-3.5" />Canal</button>
      <div className="mt-2 grid grid-cols-4 gap-3">{num("margin_threshold", "Seuil d'alerte marge (%)", "fin-threshold")}{num("provider_payment_days", "Délai paiement prestataires (j)", "fin-pay-days")}{num("fixed_costs_monthly", "Charges fixes / mois (vide = abonnements)", "fin-fixed")}{num("variable_margin_rate", "Taux de marge sur coûts variables % (vide = réel)", "fin-rate")}</div>
      <div className="flex justify-end"><Button disabled={f.activities.some((a) => !a.name.trim()) || f.channels.some((c) => !c.name.trim())} onClick={() => api.put("/finance/settings", f).then((r) => { onSaved(r.data); onOpenChange(false); toast.success("Réglages enregistrés"); }).catch((e) => toast.error(errMsg(e)))} data-testid="fin-settings-save">Enregistrer</Button></div>
    </DialogContent></Dialog>);
}

export default function Finance() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "dashboard";
  const [cfg, setCfg] = useState(null);
  const [open, setOpen] = useState(false);
  const [flt, setFlt] = useState({ period: "exercice", activity: "", compare: "n1" });
  useEffect(() => { api.get("/finance/settings").then((r) => setCfg(r.data)).catch((e) => toast.error(errMsg(e))); }, []);
  if (!cfg) return <Loading />;
  return (
    <div data-testid="finance-page">
      <PageHeader eyebrow="Finance" title="Finance & pilotage" subtitle="Prévisionnel, marges et rentabilité. La comptabilité reste dans Pennylane."
        actions={cfg.can_manage && <Button variant="outline" size="sm" onClick={() => setOpen(true)} data-testid="finance-settings-button">Réglages</Button>} />
      <div className="mb-3 flex flex-wrap gap-1.5" data-testid="finance-tabs">{TABS.map(([k, l], i) => <button key={k} onClick={() => setParams({ tab: k })} data-testid={`finance-tab-${k}`} className={`h-9 rounded-full border px-4 text-sm font-medium ${tab === k ? "border-primary bg-primary text-white" : "border-border hover:bg-secondary"}`}>{i + 1}. {l}</button>)}</div>
      <div className="mb-4 flex flex-wrap items-center gap-2" data-testid="finance-filters">
        <select className={sel} value={flt.period} onChange={(e) => setFlt({ ...flt, period: e.target.value })} data-testid="finance-filter-period"><option value="mois">Mois en cours</option><option value="trimestre">Trimestre</option><option value="exercice">Exercice</option><option value="12m">12 mois glissants</option>{[1, 2, 3].map((i) => <option key={i} value={String(new Date().getFullYear() + i)}>Exercice {new Date().getFullYear() + i}</option>)}<option value={String(new Date().getFullYear() - 1)}>Exercice {new Date().getFullYear() - 1}</option></select>
        <select className={sel} value={flt.activity} onChange={(e) => setFlt({ ...flt, activity: e.target.value })} data-testid="finance-filter-activity"><option value="">Toutes activités</option>{cfg.activities.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select>
        <select className={sel} value={flt.compare} onChange={(e) => setFlt({ ...flt, compare: e.target.value })} data-testid="finance-filter-compare"><option value="n1">Comparer à N-1</option><option value="budget">Comparer au budget</option></select>
      </div>
      {LATER.includes(tab) ? <div className="space-y-3" data-testid={`finance-later-${tab}`}><p className="text-sm text-muted-foreground">À venir : cet onglet arrivera avec la connexion Pennylane.</p><NotConnected /></div>
        : tab === "previsionnel" ? <ForecastTab />
        : tab === "etats" ? <StatementsTab />
        : tab === "impots" ? <TaxTab />
        : <ReportTab tab={tab} flt={flt} NotConnected={NotConnected} />}
      <SettingsDialog open={open} onOpenChange={setOpen} cfg={cfg} onSaved={setCfg} />
    </div>);
}
