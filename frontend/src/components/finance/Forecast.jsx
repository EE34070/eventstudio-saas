import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, errMsg } from "@/lib/api";
import { ReportView, download, show } from "@/components/finance/Report";

const ko = (e) => toast.error(errMsg(e));
const sel = "h-9 rounded-lg border border-border bg-card px-2 text-sm";
const LISTS = [
  ["activities", "1. Activité et coûts directs", [["name", "Activité", "text"], ["events_per_year", "Événements / an"], ["basket_ht", "Panier moyen HT"], ["variable_cost_pct", "Coûts variables %"], ["growth_y2_pct", "Évol. an 2 %"], ["growth_y3_pct", "Évol. an 3 %"], ["vat_pct", "TVA %"], ["start", "Lancement (AAAA-MM)", "text"], ["seasonality", "Saisonnalité (12 poids)", "list"]], { name: "", events_per_year: 0, basket_ht: 0, variable_cost_pct: 40, growth_y2_pct: 0, growth_y3_pct: 0, vat_pct: 20, start: "", seasonality: [] }],
  ["staff", "3. Personnel (coût chargé mensuel)", [["label", "Poste", "text"], ["monthly", "Coût chargé / mois"], ["start", "Début (AAAA-MM)", "text"], ["end", "Fin (AAAA-MM)", "text"]], { label: "", monthly: 0, start: "", end: "" }],
  ["fixed", "4. Charges de structure", [["label", "Charge", "text"], ["monthly", "Montant HT / mois"], ["start", "Début (AAAA-MM)", "text"], ["end", "Fin (AAAA-MM)", "text"]], { label: "", monthly: 0, start: "", end: "" }],
  ["investments", "5. Investissements", [["label", "Investissement", "text"], ["amount_ht", "Montant HT"], ["date", "Date (AAAA-MM)", "text"], ["amort_years", "Amortissement (ans)"], ["vat_pct", "TVA %"]], { label: "", amount_ht: 0, date: "", amort_years: 5, vat_pct: 20 }],
  ["loans", "6. Prêts", [["label", "Prêt", "text"], ["amount", "Montant"], ["date", "Date (AAAA-MM)", "text"], ["rate_pct", "Taux %"], ["months", "Durée (mois)"], ["deferral_months", "Différé (mois)"]], { label: "", amount: 0, date: "", rate_pct: 4, months: 48, deferral_months: 0 }],
  ["contributions", "6 bis. Apports, comptes courants, subventions", [["label", "Libellé", "text"], ["amount", "Montant"], ["date", "Date (AAAA-MM)", "text"], ["kind", "Type (apport / compte_courant / subvention)", "text"]], { label: "", amount: 0, date: "", kind: "apport" }],
  ["dividends", "7 bis. Dividendes", [["amount", "Montant"], ["date", "Date (AAAA-MM)", "text"]], { amount: 0, date: "" }]];
const SCALARS = [["raise_pct", "Hausse annuelle des salaires %"], ["indexation_pct", "Indexation des charges %"], ["opening_cash", "Trésorerie de départ"], ["tax.is_reduced_rate", "IS taux réduit %"], ["tax.is_reduced_cap", "Plafond du taux réduit"], ["tax.is_rate", "IS taux normal %"], ["tax.cfe_yearly", "CFE / an"],
  ["delays.deposit_pct", "Acompte à la signature %"], ["delays.signature_to_event_months", "Signature → événement (mois)"], ["delays.balance_delay_months", "Délai du solde (mois)"], ["delays.supplier_delay_months", "Délai fournisseurs (mois)"], ["delays.charges_vat_pct", "TVA sur charges %"]];
const num = (v) => (v === "" || v == null ? 0 : Number(String(v).replace(",", ".")) || 0);
const getp = (o, p) => p.split(".").reduce((x, k) => x?.[k], o);
const setp = (o, p, v) => { const ks = p.split("."); if (ks.length === 1) return { ...o, [p]: v }; return { ...o, [ks[0]]: { ...o[ks[0]], [ks[1]]: v } }; };

function Editor({ a, setA, locked }) {
  const up = (k, i, f, v) => setA({ ...a, [k]: a[k].map((r, j) => (j === i ? { ...r, [f]: v } : r)) });
  return (<div className="space-y-4" data-testid="forecast-editor">
    {LISTS.map(([k, title, fields, blank]) => (
      <div key={k} className="card-soft overflow-x-auto p-4" data-testid={`fc-block-${k}`}><div className="eyebrow mb-2">{title}</div>
        <table className="w-full text-sm"><thead><tr><th />{fields.map(([f, l]) => <th key={f} className="px-1 pb-1 text-left text-xs font-medium text-muted-foreground">{l}</th>)}<th /></tr></thead>
          <tbody>{(a[k] || []).map((r, i) => <tr key={i} className={r.enabled === false ? "opacity-50" : ""}>
            <td><input type="checkbox" title="Inclure dans la version" checked={r.enabled !== false} disabled={locked} onChange={(e) => up(k, i, "enabled", e.target.checked)} data-testid={`fc-${k}-enabled-${i}`} /></td>
            {fields.map(([f, , t]) => <td key={f} className="px-1 py-0.5"><Input className="h-8 min-w-[84px]" disabled={locked} title={r.source ? `Source : ${r.source}` : undefined} value={t === "list" ? (r[f] || []).join(" ") : r[f] ?? ""}
              onChange={(e) => up(k, i, f, t === "list" ? e.target.value.split(/[\s,;]+/).filter(Boolean).map(num) : t === "text" ? e.target.value : e.target.value)} onBlur={(e) => !t && up(k, i, f, num(e.target.value))} data-testid={`fc-${k}-${f}-${i}`} /></td>)}
            <td>{!locked && <button aria-label="Supprimer" onClick={() => setA({ ...a, [k]: a[k].filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></button>}</td></tr>)}</tbody></table>
        {!locked && <button className="mt-1 text-sm underline" onClick={() => setA({ ...a, [k]: [...(a[k] || []), { ...blank }] })} data-testid={`fc-${k}-add`}><Plus className="mr-1 inline h-3.5 w-3.5" />Ligne</button>}
      </div>))}
    <div className="card-soft grid grid-cols-2 gap-3 p-4 lg:grid-cols-4" data-testid="fc-block-scalars"><div className="eyebrow col-span-full">7 et 8. Fiscalité, délais de paiement, indexations</div>
      {SCALARS.map(([p, l]) => <label key={p} className="text-xs text-muted-foreground">{l}<Input className="mt-1 h-8" disabled={locked} value={getp(a, p) ?? ""} onChange={(e) => setA(setp(a, p, e.target.value))} onBlur={(e) => setA(setp(a, p, num(e.target.value)))} data-testid={`fc-${p}`} /></label>)}</div>
  </div>);
}

export function ForecastTab() {
  const [list, setList] = useState(null);
  const [id, setId] = useState("");
  const [d, setD] = useState(null);
  const [f, setF] = useState(null);
  const [sens, setSens] = useState({ events_pct: 0, basket_pct: 0, var_pts: 0 });
  const [nw, setNw] = useState(null);
  const [cmp, setCmp] = useState(null);
  const [secs, setSecs] = useState(null);
  const loadList = useCallback(() => api.get("/finance/forecasts").then((r) => { setList(r.data); setSecs((s) => s || Object.keys(r.data.sections)); return r.data; }).catch(ko), []);
  useEffect(() => { loadList().then((l) => l?.versions[0] && setId((x) => x || l.versions[0].id)); }, [loadList]);
  const got = (r) => { setD(r.data); setF({ name: r.data.version.name, notes: r.data.version.notes, presentation_text: r.data.version.presentation_text, assumptions: r.data.version.assumptions }); };
  useEffect(() => { if (id) api.get(`/finance/forecasts/${id}`, { params: sens }).then((r) => (d?.version.id === id ? setD({ ...d, results: r.data.results }) : got(r))).catch(ko); }, [id, sens]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!list) return null;
  const locked = d?.version.status === "frozen" || !list.can_manage;
  const create = () => api.post("/finance/forecasts", nw).then((r) => { setNw(null); setD(null); loadList(); setId(r.data.id); toast.success("Version créée"); }).catch(ko);
  const save = () => api.put(`/finance/forecasts/${id}`, f).then((r) => { got(r); setSens({ events_pct: 0, basket_pct: 0, var_pts: 0 }); loadList(); toast.success("Enregistré et recalculé"); }).catch(ko);
  const slider = (k, l, min, max, unit) => <label className="flex items-center gap-2 text-xs">{l}<input type="range" min={min} max={max} value={sens[k]} onChange={(e) => setSens({ ...sens, [k]: Number(e.target.value) })} data-testid={`fc-sens-${k}`} /><b className="w-12">{sens[k] > 0 ? "+" : ""}{sens[k]}{unit}</b></label>;
  return (<div className="space-y-4" data-testid="forecast-tab">
    <div className="flex flex-wrap items-center gap-2">
      <select className={sel} value={id} onChange={(e) => { setD(null); setId(e.target.value); }} data-testid="fc-version-select"><option value="">Choisir une version…</option>{list.versions.map((v) => <option key={v.id} value={v.id}>{v.name} — {v.start_year}{v.status === "frozen" ? " (figée)" : ""}</option>)}</select>
      {list.can_manage && <Button size="sm" variant="outline" onClick={() => setNw({ name: "", start_year: new Date().getFullYear() + 1, mode: "data", source_id: id })} data-testid="fc-new"><Plus />Nouvelle version</Button>}
      {list.versions.length > 1 && <Button size="sm" variant="ghost" onClick={() => api.get("/finance/forecasts/compare", { params: { ids: list.versions.slice(0, 4).map((v) => v.id).join(",") } }).then((r) => setCmp(r.data)).catch(ko)} data-testid="fc-compare">Comparer les versions</Button>}
    </div>
    {nw && <div className="card-soft flex flex-wrap items-end gap-2 p-4" data-testid="fc-new-form"><Input className="w-56" placeholder="Nom (ex. 2027 réaliste)" value={nw.name} onChange={(e) => setNw({ ...nw, name: e.target.value })} data-testid="fc-new-name" />
      <Input className="w-24" type="number" value={nw.start_year} onChange={(e) => setNw({ ...nw, start_year: Number(e.target.value) })} data-testid="fc-new-year" />
      <select className={sel} value={nw.mode} onChange={(e) => setNw({ ...nw, mode: e.target.value })} data-testid="fc-new-mode"><option value="data">Partir de mes données</option><option value="blank">De zéro</option>{id && <option value="duplicate">Dupliquer la version ouverte</option>}</select>
      <Button size="sm" disabled={!nw.name.trim()} onClick={create} data-testid="fc-new-create">Créer</Button><Button size="sm" variant="ghost" onClick={() => setNw(null)}>Annuler</Button></div>}
    {cmp && <div data-testid="fc-compare-view"><ReportView data={cmp} testid="fc-compare-report" /><button className="text-sm underline" onClick={() => setCmp(null)}>Fermer la comparaison</button></div>}
    {d && f && <>
      <div className="flex flex-wrap items-center gap-2"><Input className="w-64" disabled={locked} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} data-testid="fc-name" />
        {d.version.status === "frozen" ? <span className="rounded-full bg-sky-500/15 px-3 py-1 text-xs font-medium text-sky-700" data-testid="fc-frozen-badge">Figée le {d.version.frozen_at?.slice(0, 10)} par {d.version.frozen_by} — sert de budget {d.version.start_year}</span>
          : list.can_manage && <><Button size="sm" onClick={save} data-testid="fc-save">Enregistrer et recalculer</Button>
            <Button size="sm" variant="outline" onClick={() => window.confirm("Figer cette version ? Elle ne sera plus modifiable et générera le budget de l'année.") && api.post(`/finance/forecasts/${id}/freeze`).then((r) => { got(r); loadList(); toast.success("Version figée, budget généré"); }).catch(ko)} data-testid="fc-freeze">Figer</Button>
            <Button size="sm" variant="ghost" onClick={() => window.confirm("Supprimer ce brouillon ?") && api.delete(`/finance/forecasts/${id}`).then(() => { setD(null); setId(""); loadList(); }).catch(ko)} data-testid="fc-delete">Supprimer</Button></>}
        <span className="flex-1" />
        <Button size="sm" variant="outline" onClick={() => download(`/finance/forecasts/${id}/export`, { format: "pdf", sections: secs.join(",") }, `dossier-banquier-${d.version.start_year}.pdf`)} data-testid="fc-export-pdf">Dossier banquier PDF</Button>
        <Button size="sm" variant="outline" onClick={() => download(`/finance/forecasts/${id}/export`, { format: "xlsx", sections: secs.join(",") }, `dossier-banquier-${d.version.start_year}.xlsx`)} data-testid="fc-export-xlsx">Excel</Button></div>
      <div className="flex flex-wrap gap-3 text-xs" data-testid="fc-sections"><span className="text-muted-foreground">Sections du dossier :</span>{Object.entries(list.sections).map(([k, l]) => <label key={k} className="flex items-center gap-1"><input type="checkbox" checked={secs.includes(k)} onChange={(e) => setSecs(e.target.checked ? [...secs, k] : secs.filter((x) => x !== k))} />{l}</label>)}</div>
      <div className="rounded-xl bg-secondary p-3 text-sm" data-testid="fc-signed-share">{d.signed_share.pct == null ? "Aucun CA prévu pour l'instant." : <><b>{show(d.signed_share.pct, "pct")}</b> du CA {d.version.start_year} déjà signé ({show(d.signed_share.signed_ht, "eur")}).</>}</div>
      <div className="flex flex-wrap items-center gap-2 rounded-xl bg-secondary p-3 text-sm" data-testid="fc-personnel-source">Charges de personnel : <b>{d.results.personnel_source}</b>{!locked && <select className={sel} value={f.assumptions?.staff_source || "social"} onChange={(e) => setF({ ...f, assumptions: { ...f.assumptions, staff_source: e.target.value } })} data-testid="fc-staff-source"><option value="social">Alimentées par le Pôle Social (salariés et gérants séparés)</option><option value="manual">Saisie manuelle (bloc 3)</option></select>}</div>
      <div className="card-soft flex flex-wrap items-center gap-4 p-3" data-testid="fc-sensitivity"><span className="eyebrow">Sensibilité</span>{slider("events_pct", "Événements", -20, 20, " %")}{slider("basket_pct", "Panier moyen", -10, 10, " %")}{slider("var_pts", "Coûts variables", -5, 5, " pts")}</div>
      <ReportView data={d.results} testid="fc-results" />
      <textarea className="w-full rounded-xl border border-border bg-card p-3 text-sm" rows={3} disabled={locked} placeholder="Présentation de l'entreprise et du projet (reprise dans le dossier banquier)" value={f.presentation_text} onChange={(e) => setF({ ...f, presentation_text: e.target.value })} data-testid="fc-presentation" />
      <Editor a={f.assumptions} setA={(a) => setF({ ...f, assumptions: a })} locked={locked} />
    </>}
  </div>);
}
