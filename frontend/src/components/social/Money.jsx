import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, errMsg } from "@/lib/api";
import { Alert, F, In, Kpi, Note, Pick, T, eur, inp, run, today, upload, useLoad } from "@/components/social/kit";

const rowsEd = (f, setF, k, fields, blank, tid) => (
  <div><div className="space-y-1">{(f[k] || []).map((x, i) => <div key={i} className="flex gap-1">{fields.map(([key, ph, type, opts]) => (opts
    ? <select key={key} className={inp} value={x[key]} onChange={(e) => setF({ ...f, [k]: f[k].map((y, j) => (j === i ? { ...y, [key]: e.target.value } : y)) })}>{opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
    : <input key={key} className={inp} type={type || "text"} placeholder={ph} title={ph} value={x[key] ?? ""} onChange={(e) => setF({ ...f, [k]: f[k].map((y, j) => (j === i ? { ...y, [key]: type === "number" ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value } : y)) })} />))}
    <button onClick={() => setF({ ...f, [k]: f[k].filter((_, j) => j !== i) })}>×</button></div>)}</div>
    <button className="mt-1 text-sm underline" onClick={() => setF({ ...f, [k]: [...(f[k] || []), { ...blank }] })} data-testid={tid}>+ Ajouter</button></div>);

export function GerantsTab() {
  const [d, load] = useLoad("/social/managers");
  const [f, setF] = useState(null);
  const [sim, setSim] = useState({ budget: 50000 });
  const [res, setRes] = useState(null);
  if (!d) return null;
  const save = () => run(f.id ? api.put(`/social/managers/${f.id}`, f) : api.post("/social/managers", f), "Fiche gérant enregistrée", () => { setF(null); load(); });
  return (
    <div data-testid="social-gerants">
      {d.can_manage && <Button size="sm" className="mb-3" onClick={() => setF({ name: "", status: "Gérant majoritaire (TNS)", pay: [], contracts: [], calls: [] })} data-testid="manager-new">Ajouter un gérant</Button>}
      <T testid="manager-table" empty="Aucun gérant saisi. Ajoutez les fiches des co-gérants." cols={[["Gérant", (r) => <><b>{r.name}</b><div className="text-xs text-muted-foreground">{r.status} — {r.no_payslip}</div></>], [`Rémunération ${d.rows[0]?.year || ""}`, (r) => eur(r.pay_year)], ["Madelin / PER / prévoyance", (r) => eur(r.contracts_year)], [`Cotisations estimées (${d.tns_rate} %)`, (r) => eur(r.contrib_estimated)], ["Provisionnels appelés", (r) => eur(r.contrib_called)],
        ["Régularisation estimée", (r) => <span data-testid={`manager-regul-${r.id}`}>{eur(r.regul_estimated)} en {r.regul_month}</span>], ["Modulation", "modulation"], ["", (r) => d.can_manage && <button className="underline" onClick={() => setF(JSON.parse(JSON.stringify(r)))} data-testid={`manager-edit-${r.id}`}>Modifier</button>]]} rows={d.rows} />
      <div className="card-soft mt-4 p-4" data-testid="manager-simulator"><div className="eyebrow mb-2">Simulateur rémunération vs dividendes (même enveloppe pour la société)</div>
        <div className="flex flex-wrap items-end gap-2"><F label="Enveloppe (€)"><In f={sim} setF={setSim} k="budget" type="number" tid="mgr-sim-budget" /></F><Button size="sm" onClick={() => api.get("/social/managers/simulate", { params: sim }).then((r) => setRes(r.data)).catch((e) => toast.error(errMsg(e)))} data-testid="mgr-sim-run">Comparer</Button></div>
        {res && <div className="mt-2 grid gap-2 text-sm md:grid-cols-2" data-testid="mgr-sim-result"><div>En rémunération : {eur(res.remuneration.paid)} versés + {eur(res.remuneration.contributions)} de cotisations TNS → <b>{eur(res.remuneration.net_before_income_tax)}</b> avant impôt sur le revenu</div><div>En dividendes : IS {eur(res.dividends.is)}, distribuable {eur(res.dividends.distributable)}, prélèvement forfaitaire {eur(res.dividends.flat_tax)} → <b>{eur(res.dividends.net)}</b> nets</div><p className="text-xs italic text-muted-foreground md:col-span-2">{res.note}</p></div>}</div>
      <Note>{d.note} Aucune écriture comptable n'est créée.</Note>
      {f && <Dialog open onOpenChange={() => setF(null)}><DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto" data-testid="manager-dialog"><DialogHeader><DialogTitle>{f.id ? f.name : "Nouveau gérant"}</DialogTitle><DialogDescription>Gérant majoritaire TNS : ni bulletin, ni DSN, ni chômage.</DialogDescription></DialogHeader>
        <div className="grid grid-cols-2 gap-2"><F label="Nom"><In f={f} setF={setF} k="name" tid="manager-name" /></F><F label="Statut"><In f={f} setF={setF} k="status" /></F></div>
        <div className="eyebrow">Rémunération décidée (montant, périodicité, du, au)</div>{rowsEd(f, setF, "pay", [["amount", "Montant €", "number"], ["periodicity", "", "", [["monthly", "par mois"], ["quarterly", "par trimestre"], ["yearly", "par an"]]], ["start", "Du", "date"], ["end", "Au", "date"]], { amount: 0, periodicity: "monthly", start: today(), end: "", decision_file_id: "" }, "manager-add-pay")}
        <div className="eyebrow">Contrats pris en charge par la société</div>{rowsEd(f, setF, "contracts", [["label", "Intitulé"], ["kind", "", "", [["madelin", "Madelin"], ["per", "PER"], ["prevoyance", "Prévoyance"]]], ["monthly", "€ / mois", "number"]], { label: "", kind: "madelin", monthly: 0 }, "manager-add-contract")}
        <div className="eyebrow">Appels URSSAF indépendants (type, année, échéance, montant)</div>{rowsEd(f, setF, "calls", [["kind", "", "", [["provisionnel", "Provisionnel"], ["regularisation", "Régularisation"]]], ["year", "Année", "number"], ["due_date", "Échéance", "date"], ["amount", "Montant €", "number"]], { id: "", kind: "provisionnel", year: new Date().getFullYear(), due_date: today(), amount: 0, file_id: "" }, "manager-add-call")}
        {f.id && <label className="cursor-pointer text-sm underline">Lire un appel ou une régularisation PDF par IA<input type="file" accept="application/pdf" className="hidden" data-testid="manager-import-pdf" onChange={(e) => e.target.files[0] && upload(`/social/managers/${f.id}/calls/import-pdf`, e.target.files[0]).then((r) => { if (r.data.message) toast.warning(r.data.message); else toast.success(`${r.data.calls.length} échéance(s) proposée(s) : vérifiez-les avant d'enregistrer`); setF({ ...f, calls: [...f.calls, ...r.data.calls.map((c) => ({ id: "", ...c }))] }); }).catch((x) => toast.error(errMsg(x)))} /></label>}
        <div className="flex justify-between">{f.id ? <button className="text-sm text-red-600 underline" onClick={() => window.confirm("Placer ce gérant dans la Corbeille (30 jours) ?") && run(api.delete(`/social/managers/${f.id}`), "Retiré", () => { setF(null); load(); })}>Retirer</button> : <span />}<Button onClick={save} data-testid="manager-save">Enregistrer</Button></div></DialogContent></Dialog>}
    </div>);
}

export function EcheancesTab() {
  const [d, , setD] = useLoad("/social/dues");
  const [p, setP] = useState(null);
  if (!d) return null;
  return (
    <div data-testid="social-echeances">
      <Alert a={{ text: d.bank.note }} />
      <div className="mt-3"><T testid="dues-table" empty="Aucune échéance : saisissez des contrats ou des gérants." cols={[["Échéance", "due_date"], ["Organisme", "body"], ["Libellé", "label"], ["Montant prévu", (r) => eur(r.amount)], ["Payé", (r) => (r.paid_at ? `${r.paid_at} · ${eur(r.paid_amount ?? r.amount)}` : "—")], ["Alerte", (r) => (r.alert ? <span className="font-semibold text-red-600">{r.alert}</span> : "—")],
        ["", (r) => d.can_manage && <button className="underline" onClick={() => setP({ key: r.key, paid_at: r.paid_at || today(), paid_amount: r.paid_amount ?? r.amount })} data-testid={`due-point-${r.key}`}>{r.paid_at ? "Modifier" : "Pointer"}</button>]]} rows={d.rows} /></div>
      <Note>{d.note} Aucun paiement n'est émis par l'application.</Note>
      {p && <Dialog open onOpenChange={() => setP(null)}><DialogContent data-testid="due-dialog"><DialogHeader><DialogTitle>Pointer le paiement</DialogTitle><DialogDescription>Pointage manuel ; un écart avec le montant prévu est signalé.</DialogDescription></DialogHeader>
        <F label="Payé le (vide = non payé)"><In f={p} setF={setP} k="paid_at" type="date" tid="due-date" /></F><F label="Montant payé (€)"><In f={p} setF={setP} k="paid_amount" type="number" tid="due-amount" /></F>
        <Button onClick={() => run(api.put(`/social/dues/${p.key}`, { paid_at: p.paid_at, paid_amount: p.paid_at ? Number(p.paid_amount) : null }), "Pointé", (r) => { setD(r); setP(null); })} data-testid="due-save">Enregistrer</Button></DialogContent></Dialog>}
    </div>);
}

const KINDS = [["hire", "Embauche"], ["cdd_to_cdi", "Passage d'un CDD en CDI"], ["raise_pct", "Augmentation de X %"], ["departure", "Départ d'un salarié"], ["replace_cddu", "Remplacer des intermittents par un CDI"], ["manager_raise", "Hausse de la rémunération des gérants"]];

export function PrevisionnelTab() {
  const [n, setN] = useState(12);
  const [d] = useLoad(`/social/forecast?months=${n}`);
  const y = new Date().getFullYear();
  const [b, , setB] = useLoad(`/social/budget/${y}`);
  const [sc, , setSc] = useLoad("/social/scenarios");
  const [f, setF] = useState(null);
  if (!d || !b || !sc) return null;
  const shown = n > 12 ? d.rows.filter((_, i) => i % 3 === 0 || true).slice(0, 36) : d.rows;
  return (
    <div data-testid="social-previsionnel">
      <div className="mb-3 grid gap-3 md:grid-cols-4"><Kpi label={`Salariés et intermittents (${n} mois)`} value={eur(d.staff_total)} testid="fc-staff" /><Kpi label="Gérants (ligne distincte)" value={eur(d.managers_total)} testid="fc-managers" /><Kpi label="Provision congés payés" value={eur(d.leave_provision)} hint="dette sociale latente, information" /><div className="flex items-center gap-2"><Button size="sm" variant={n === 12 ? "default" : "outline"} onClick={() => setN(12)} data-testid="fc-12">12 mois</Button><Button size="sm" variant={n === 36 ? "default" : "outline"} onClick={() => setN(36)} data-testid="fc-36">3 ans</Button></div></div>
      <T testid="fc-table" cols={[["Mois", (r) => <>{r.month} {r.real && <span className="rounded bg-emerald-500/15 px-1 text-[11px] text-emerald-700">réel</span>}</>], ["Brut", (r) => eur(r.gross)], ["Coût CDI / CDD", (r) => eur(r.cost)], ["Coût CDDU", (r) => eur(r.cddu)], ["Nets à payer", (r) => eur(r.net)], ["Cotisations (payées M+1)", (r) => eur(r.contrib)], ["PAS", (r) => eur(r.pas)], ["Gérants : rémunération", (r) => eur(r.mgr_pay)], ["Gérants : cotisations TNS", (r) => eur(r.mgr_charge)], ["Décaissé dans le mois", (r) => <b>{eur(d.cash[r.month])}</b>]]} rows={shown} />
      <div className="eyebrow mb-1 mt-5">Détail par personne (coût employeur)</div>
      <div className="overflow-x-auto rounded-xl border border-border" data-testid="fc-people"><table className="w-full text-xs"><thead className="bg-secondary"><tr><th className="px-2 py-1 text-left">Personne</th>{d.months.slice(0, 12).map((m) => <th key={m} className="px-2 py-1 text-right">{m.slice(2)}</th>)}</tr></thead><tbody>{d.people.map((p) => <tr key={p.team_id} className="border-t border-border"><td className="whitespace-nowrap px-2 py-1">{p.name} <span className="text-muted-foreground">{p.type}</span></td>{d.months.slice(0, 12).map((m) => <td key={m} className={`px-2 py-1 text-right ${p.source[m] === "réel" ? "font-semibold text-emerald-700" : ""}`} data-testid={`fc-${p.team_id}-${m}`}>{p.cost[m] ? Math.round(p.cost[m]).toLocaleString("fr-FR") : ""}</td>)}</tr>)}</tbody></table></div>
      <div className="eyebrow mb-1 mt-5">Échéancier de trésorerie (90 prochains flux)</div>
      <T testid="fc-flows" cols={[["Date", "date"], ["Flux", "label"], ["Montant", (r) => eur(r.amount)]]} rows={d.flows.slice(0, 90)} />
      <Note>{d.note} Alimente automatiquement : {d.feeds.join(" ; ")}.</Note>
      <div className="eyebrow mb-1 mt-6">Budget de masse salariale {y} vs réel</div>
      <T testid="budget-table" cols={[["Mois", "month"], ["Budget", (r, i) => (b.can_manage ? <input type="number" className={`${inp} w-28`} defaultValue={r.budget} data-testid={`budget-${i}`} onBlur={(e) => Number(e.target.value) !== r.budget && run(api.put(`/social/budget/${y}`, { monthly: b.rows.map((x, j) => (j === i ? Number(e.target.value) : x.budget)) }), "Budget enregistré", setB)} /> : eur(r.budget))], ["Réel / prévu", (r) => <>{eur(r.actual)} {r.real ? "(réel)" : "(prévu)"}</>], ["Écart", (r) => <span className={r.gap > 0 ? "text-red-600" : "text-emerald-700"}>{eur(r.gap)}</span>], ["Explication", "explain"]]} rows={b.rows} />
      <div className="mb-2 mt-6 flex items-center justify-between"><div className="eyebrow">Scénarios (comparés côte à côte, jamais appliqués automatiquement)</div>{sc.can_manage && <Button size="sm" onClick={() => setF({ name: "", kind: "hire", date: today(), team_id: "", contract_type: "cdi", gross: 2300, pct: 5, missions_per_year: 0, cost_per_mission: 0, job: "" })} data-testid="scenario-new">Nouveau scénario</Button>}</div>
      {sc.rows.length === 0 ? <p className="text-sm text-muted-foreground">Aucun scénario.</p> : <div className="overflow-x-auto rounded-xl border border-border" data-testid="scenario-table"><table className="w-full text-sm"><thead className="bg-secondary text-xs"><tr><th className="px-3 py-2 text-left">Indicateur</th>{sc.rows.map((s) => <th key={s.id} className="px-3 py-2 text-right">{s.name}{s.applied_at && <div className="font-normal text-emerald-700">appliqué</div>}</th>)}</tr></thead><tbody>
        {[["Coût annuel sans", "cost_year_without"], ["Coût annuel avec", "cost_year_with"], ["Surcoût annuel", "delta_cost"], ["Effet sur le résultat", "result_effect"], ["IS estimé sans", "is_without"], ["IS estimé avec", "is_with"], ["Point bas de trésorerie sans", "cash_low_without"], ["Point bas de trésorerie avec", "cash_low_with"], ["Seuil de rentabilité sans", "breakeven_without"], ["Seuil de rentabilité avec", "breakeven_with"]].map(([l, k]) => <tr key={k} className="border-t border-border"><td className="px-3 py-1.5">{l}</td>{sc.rows.map((s) => <td key={s.id} className="px-3 py-1.5 text-right" data-testid={`scenario-${k}-${s.id}`}>{eur(s.results[k])}</td>)}</tr>)}
        <tr className="border-t border-border text-xs text-muted-foreground"><td className="px-3 py-1.5">Période · trésorerie</td>{sc.rows.map((s) => <td key={s.id} className="px-3 py-1.5 text-right">{s.results.period}<br />{s.results.cash_source}</td>)}</tr>
        {sc.can_manage && <tr className="border-t border-border"><td />{sc.rows.map((s) => <td key={s.id} className="px-3 py-1.5 text-right">{!s.applied_at && ["hire", "raise_pct"].includes(s.assumptions.kind) && <button className="mr-2 underline" onClick={() => window.confirm("Appliquer ce scénario ? Cela crée la fiche et le contrat (embauche) ou les révisions planifiées (augmentation).") && run(api.post(`/social/scenarios/${s.id}/apply`), "Scénario appliqué", setSc)} data-testid={`scenario-apply-${s.id}`}>Appliquer</button>}<button className="text-red-600 underline" onClick={() => run(api.delete(`/social/scenarios/${s.id}`), "Supprimé", setSc)}>Supprimer</button></td>)}</tr>}</tbody></table></div>}
      {f && <Dialog open onOpenChange={() => setF(null)}><DialogContent data-testid="scenario-dialog"><DialogHeader><DialogTitle>Nouveau scénario</DialogTitle><DialogDescription>Une simulation : rien n'est modifié tant que vous ne l'appliquez pas.</DialogDescription></DialogHeader>
        <F label="Nom"><In f={f} setF={setF} k="name" tid="scenario-name" /></F><F label="Type"><Pick f={f} setF={setF} k="kind" opts={KINDS} tid="scenario-kind" /></F><F label="Date d'effet"><In f={f} setF={setF} k="date" type="date" tid="scenario-date" /></F>
        {["hire", "replace_cddu"].includes(f.kind) && <><F label="Emploi"><In f={f} setF={setF} k="job" /></F><F label="Salaire brut mensuel (€)"><In f={f} setF={setF} k="gross" type="number" tid="scenario-gross" /></F></>}
        {f.kind === "hire" && <F label="Contrat"><Pick f={f} setF={setF} k="contract_type" opts={[["cdi", "CDI"], ["cdd", "CDD"]]} /></F>}
        {f.kind === "replace_cddu" && <div className="grid grid-cols-2 gap-2"><F label="Missions d'intermittents remplacées / an"><In f={f} setF={setF} k="missions_per_year" type="number" /></F><F label="Brut moyen par mission (€)"><In f={f} setF={setF} k="cost_per_mission" type="number" /></F></div>}
        {["cdd_to_cdi", "departure", "raise_pct"].includes(f.kind) && <F label={f.kind === "raise_pct" ? "Salarié (vide = tous)" : "Salarié"}><Pick f={f} setF={setF} k="team_id" blank="—" opts={sc.employees.map((e) => [e.team_id, e.name])} /></F>}
        {["raise_pct", "manager_raise"].includes(f.kind) && <F label="Pourcentage"><In f={f} setF={setF} k="pct" type="number" /></F>}
        <Button onClick={() => run(api.post("/social/scenarios", f), "Scénario calculé", (r) => { setSc(r); setF(null); })} data-testid="scenario-save">Calculer</Button></DialogContent></Dialog>}
    </div>);
}
