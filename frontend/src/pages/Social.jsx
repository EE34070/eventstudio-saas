import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/common";
import { api } from "@/lib/api";
import { Alert, F, Kpi, Note, T, eur, inp, run, today, useLoad } from "@/components/social/kit";
import { ContratsTab, PersonnelTab, RemunerationsTab } from "@/components/social/People";
import { CongesTab, PaieTab, TempsTab } from "@/components/social/Time";
import { EcheancesTab, GerantsTab, PrevisionnelTab } from "@/components/social/Money";

const TABS = [["dashboard", "Tableau de bord"], ["personnel", "Personnel"], ["contrats", "Contrats"], ["remunerations", "Rémunérations"], ["temps", "Temps & variables"], ["conges", "Congés & absences"], ["paie", "Paie du mois"], ["gerants", "Gérants"], ["echeances", "Échéances sociales"], ["previsionnel", "Prévisionnel"], ["parametres", "Paramètres"]];

function DashboardTab() {
  const [d] = useLoad("/social/dashboard");
  if (!d) return null;
  const p = d.payroll;
  return (
    <div className="space-y-4" data-testid="social-dashboard">
      {d.badges.length > 0 && <div className="space-y-1" data-testid="social-badges">{d.badges.map((a, i) => <Alert key={i} a={a} />)}</div>}
      <div className="grid gap-3 md:grid-cols-4">
        <Kpi testid="kpi-headcount" label="Effectif" value={d.headcount.total} hint={`${d.headcount.fte} ETP · ${d.headcount.by_type.map((t) => `${t.count} ${t.type}`).join(", ") || "aucun contrat"} · ${d.headcount.entries} entrée(s), ${d.headcount.exits} sortie(s) cette année`} />
        <Kpi testid="kpi-month" label="Masse salariale du mois" value={eur(p.month)} hint={p.month_real ? "réel (bulletins)" : "prévu"} />
        <Kpi testid="kpi-ytd" label="Cumul de l'année" value={eur(p.ytd)} hint={`N-1 réel : ${eur(p.ytd_n1_real)}`} />
        <Kpi testid="kpi-managers" label="Coût des gérants (cumul)" value={eur(p.managers_ytd)} />
        <Kpi testid="kpi-ratio" label="Masse salariale / CA" value={p.ratio_pct == null ? "—" : `${p.ratio_pct} %`} hint={`avec gérants : ${p.ratio_with_managers_pct == null ? "—" : `${p.ratio_with_managers_pct} %`} · CA signé ${eur(p.ca_ytd)}`} />
        <Kpi testid="kpi-overtime" label="Heures sup. du mois" value={`${d.overtime.month_hours} h`} hint={d.overtime.contingent.map((c) => `${c.name} ${c.used}/${c.max} h`).join(" · ")} />
        <Kpi testid="kpi-absent" label="Absentéisme du mois" value={`${d.absenteeism_pct} %`} />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div><div className="eyebrow mb-1">Congés à prendre avant la fin de la période</div><T testid="dash-leave" cols={[["Salarié", "name"], ["Reliquat N-1", (r) => `${r.n1_remaining} j`], ["Avant le", "to_take_before"], ["Solde total", (r) => `${r.remaining} j`]]} rows={d.leave} /></div>
        <div><div className="eyebrow mb-1">Coût chargé des intermittents par événement</div><T testid="dash-cddu" cols={[["Événement", "title"], ["Coût", (r) => eur(r.cost)]]} rows={d.cddu_by_event} /></div>
        <div><div className="eyebrow mb-1">Prochaines échéances RH</div><div className="space-y-1">{d.alerts.length ? d.alerts.map((a, i) => <Alert key={i} a={a} />) : <p className="text-sm text-muted-foreground">Rien à signaler.</p>}</div></div>
        <div><div className="eyebrow mb-1">Prochaines cotisations</div><T testid="dash-dues" cols={[["Date", "due_date"], ["Libellé", "label"], ["Montant", (r) => eur(r.amount)]]} rows={d.dues} /></div>
      </div>
      <Note>{d.note} La paie est établie par le cabinet ; la comptabilité reste dans Pennylane : aucune écriture n'est créée ici.</Note>
    </div>);
}

const SCALARS = [["net_ratio", "Ratio net / brut (simulation)"], ["weekly_hours", "Durée hebdomadaire de référence (h)"], ["night_pct", "Majoration de nuit (%)"], ["sunday_pct", "Majoration du dimanche (%)"], ["holiday_pct", "Majoration jour férié (%)"], ["contingent", "Contingent annuel d'heures sup. (h)"], ["daily_max", "Durée maximale journalière (h)"], ["weekly_max", "Durée maximale hebdomadaire (h)"], ["rest_hours", "Repos quotidien (h)"],
  ["leave_days_per_month", "Congés acquis par mois (jours)"], ["cdd_max_months", "Durée maximale d'un CDD (mois)"], ["cdd_max_renewals", "Renouvellements maximum d'un CDD"], ["pay_day", "Jour de paie (0 = dernier jour du mois)"], ["dues_day", "Jour d'échéance des cotisations (M+1)"], ["tns_rate", "Taux de cotisations TNS estimé (% de la rémunération)"], ["tns_regul_month", "Mois de la régularisation TNS (1-12)"], ["flat_tax_pct", "Prélèvement forfaitaire sur dividendes (%)"], ["variance_alert_pct", "Seuil d'alerte écart prévu / réel (%)"]];

function ParametresTab() {
  const [d, , setD] = useLoad("/social/settings");
  const [f, setF] = useState(null);
  const [from, setFrom] = useState(today());
  useEffect(() => { if (d) setF(JSON.parse(JSON.stringify(d.current))); }, [d]);
  if (!d || !f) return null;
  const n = (v) => (v === "" ? "" : Number(v));
  const arr = (k, i, key, v) => setF({ ...f, [k]: f[k].map((x, j) => (j === i ? { ...x, [key]: v } : x)) });
  return (
    <div className="space-y-4" data-testid="social-parametres">
      <Alert a={{ text: "Aucun taux légal n'est figé dans l'application : toutes ces valeurs sont à valider avec l'expert-comptable. Chaque enregistrement crée une version datée." }} />
      <div className="text-sm">Versions : {d.versions.map((v) => `${v.valid_from}${v.updated_by ? ` (${v.updated_by})` : ""}`).join(" · ")}</div>
      <div><div className="eyebrow mb-1">Coefficients employeur par type de contrat (coût = brut × coefficient ; aussi utilisés pour la main-d'œuvre des devis)</div><div className="grid grid-cols-3 gap-2 md:grid-cols-6">{Object.keys(f.coef).map((k) => <F key={k} label={d.types[k] || k}><input type="number" step="0.01" className={inp} value={f.coef[k]} onChange={(e) => setF({ ...f, coef: { ...f.coef, [k]: n(e.target.value) } })} data-testid={`param-coef-${k}`} /></F>)}</div></div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3">{SCALARS.map(([k, l]) => <F key={k} label={l}><input type="number" step="0.01" className={inp} value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: n(e.target.value) })} data-testid={`param-${k}`} /></F>)}
        <F label="Décompte des congés"><select className={inp} value={f.leave_mode} onChange={(e) => setF({ ...f, leave_mode: e.target.value })}><option value="ouvrables">Jours ouvrables</option><option value="ouvres">Jours ouvrés</option></select></F>
        <F label="Début de la période de référence (MM-JJ)"><input className={inp} value={f.leave_ref_start} onChange={(e) => setF({ ...f, leave_ref_start: e.target.value })} data-testid="param-leave-ref" /></F>
        <F label="Moyenne des variables dans le prévisionnel"><select className={inp} value={f.variables_avg} onChange={(e) => setF({ ...f, variables_avg: e.target.value })}><option value="0">Aucune</option><option value="3">3 mois</option><option value="12">12 mois</option></select></F>
        <F label="Subrogation en cas d'arrêt maladie"><select className={inp} value={f.subrogation ? "1" : ""} onChange={(e) => setF({ ...f, subrogation: !!e.target.value })}><option value="">Non</option><option value="1">Oui</option></select></F>
        <F label="E-mail du cabinet (pré-paie)" ><input className={inp} type="email" value={f.firm_email} onChange={(e) => setF({ ...f, firm_email: e.target.value })} data-testid="param-firm-email" /></F></div>
      <div><div className="eyebrow mb-1">Tranches d'heures supplémentaires (heures par semaine dans la tranche ; vide = au-delà)</div>{f.overtime.map((t, i) => <div key={i} className="mb-1 flex gap-2"><input type="number" className={inp} placeholder="Heures" value={t.hours ?? ""} onChange={(e) => arr("overtime", i, "hours", e.target.value === "" ? null : Number(e.target.value))} /><input type="number" className={inp} placeholder="Majoration %" value={t.pct} onChange={(e) => arr("overtime", i, "pct", n(e.target.value))} /><button onClick={() => setF({ ...f, overtime: f.overtime.filter((_, j) => j !== i) })}>×</button></div>)}<button className="text-sm underline" onClick={() => setF({ ...f, overtime: [...f.overtime, { hours: null, pct: 50 }] })}>+ Tranche</button></div>
      <div><div className="eyebrow mb-1">Minimums conventionnels CCN 3090 (classification exacte du contrat, minimum mensuel temps plein)</div>{f.minimums.map((t, i) => <div key={i} className="mb-1 flex gap-2"><input className={inp} placeholder="Classification" value={t.classification} onChange={(e) => arr("minimums", i, "classification", e.target.value)} /><input type="number" className={inp} placeholder="€ / mois" value={t.monthly} onChange={(e) => arr("minimums", i, "monthly", n(e.target.value))} /><button onClick={() => setF({ ...f, minimums: f.minimums.filter((_, j) => j !== i) })}>×</button></div>)}<button className="text-sm underline" onClick={() => setF({ ...f, minimums: [...f.minimums, { classification: "", monthly: 0 }] })} data-testid="param-add-minimum">+ Minimum</button></div>
      <div><div className="eyebrow mb-1">Organismes sociaux (part estimée des cotisations, périodicité, jour d'exigibilité, compte bancaire)</div>{f.bodies.map((b, i) => <div key={i} className="mb-1 grid grid-cols-12 gap-2"><input className={`${inp} col-span-4`} value={b.name} onChange={(e) => arr("bodies", i, "name", e.target.value)} /><input type="number" className={`${inp} col-span-2`} title="Part %" value={b.share_pct} onChange={(e) => arr("bodies", i, "share_pct", n(e.target.value))} /><select className={`${inp} col-span-2`} value={b.periodicity} onChange={(e) => arr("bodies", i, "periodicity", e.target.value)}><option value="monthly">Mensuel</option><option value="quarterly">Trimestriel</option><option value="yearly">Annuel</option></select><input type="number" className={`${inp} col-span-1`} title="Jour" value={b.day} onChange={(e) => arr("bodies", i, "day", n(e.target.value))} /><input className={`${inp} col-span-3`} placeholder="Compte bancaire" value={b.account} onChange={(e) => arr("bodies", i, "account", e.target.value)} /></div>)}</div>
      {d.can_manage && <div className="flex items-end gap-2"><F label="Applicable à partir du"><input type="date" className={inp} value={from} onChange={(e) => setFrom(e.target.value)} data-testid="param-from" /></F><Button onClick={() => run(api.put("/social/settings", { valid_from: from, params: f }), "Paramètres enregistrés", setD)} data-testid="param-save">Enregistrer cette version</Button></div>}
      <Note>{d.note}</Note>
    </div>);
}

const VIEW = { dashboard: DashboardTab, personnel: PersonnelTab, contrats: ContratsTab, remunerations: RemunerationsTab, temps: TempsTab, conges: CongesTab, paie: PaieTab, gerants: GerantsTab, echeances: EcheancesTab, previsionnel: PrevisionnelTab, parametres: ParametresTab };

export default function Social() {
  const [sp, setSp] = useSearchParams();
  const tab = VIEW[sp.get("tab")] ? sp.get("tab") : "dashboard";
  const View = VIEW[tab];
  return (
    <div data-testid="social-page">
      <PageHeader title="Pôle Social" subtitle="Personnel, contrats, temps, congés et paie du mois. Les bulletins sont établis par le cabinet ; la comptabilité reste dans Pennylane." />
      <div className="mb-5 flex flex-wrap gap-1.5" data-testid="social-tabs">{TABS.map(([k, l]) => <button key={k} onClick={() => setSp({ tab: k })} data-testid={`social-tab-${k}`} className={`h-9 rounded-full border px-4 text-sm font-medium ${tab === k ? "border-primary bg-primary text-white" : "border-border hover:bg-secondary"}`}>{l}</button>)}</div>
      <View />
    </div>);
}
