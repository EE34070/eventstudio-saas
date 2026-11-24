import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, errMsg } from "@/lib/api";

const ko = (e) => toast.error(errMsg(e));
const eur = (x) => `${Math.round(x ?? 0).toLocaleString("fr-FR")} €`;
const fr = (d) => (d || "").split("-").reverse().join("/");
const KIND = { produit: "Produit prévu", charge: "Charge prévue", reintegration: "Réintégration fiscale", deduction: "Déduction fiscale" };
const ST = { paid: ["Payé", "bg-emerald-500/15 text-emerald-700"], late: ["Échu, non pointé", "bg-red-500/15 text-red-700"], due: ["À venir", "bg-secondary"] };
const box = "rounded-2xl border border-border p-4";

export function TaxEstimate() {
  const [d, setD] = useState(null);
  const [f, setF] = useState(null);
  const fill = (x) => { setD(x); setF(x.inputs); };
  useEffect(() => { api.get("/finance/tax").then((r) => fill(r.data)).catch(ko); }, []);
  if (!d) return null;
  const e = d.estimate, ro = !d.can_manage;
  const save = () => api.put("/finance/tax/inputs", { ...f, lines: f.lines.filter((l) => l.label.trim()) }).then((r) => { fill(r.data); toast.success("Estimation recalculée"); }).catch(ko);
  const mark = (x, body) => api.put(`/finance/tax/dues/${x.key}`, body).then((r) => fill(r.data)).catch(ko);
  const num = (k, label, tid) => <label className="text-xs text-muted-foreground">{label}<Input type="number" min="0" disabled={ro} className="mt-1 h-8" value={f[k] ?? ""} onChange={(ev) => setF({ ...f, [k]: ev.target.value === "" ? null : Number(ev.target.value) })} data-testid={tid} /></label>;
  const rows = (list, sign = "") => list.map((x) => <div key={x.label} className="flex justify-between gap-3"><span>{x.label}</span><span className="whitespace-nowrap">{sign}{eur(x.amount)}</span></div>);
  const total = (label, v, tid) => <div className="flex justify-between gap-3 border-t border-border pt-1 font-semibold" data-testid={tid}><span>{label}</span><span>{eur(v)}</span></div>;
  return (
    <div className="space-y-4" data-testid="tax-estimate">
      <div className="grid gap-3 sm:grid-cols-4">{[["IS estimé de l'exercice", eur(e.is_total), "tax-kpi-is"], ["Taux effectif", `${e.effective_rate.toLocaleString("fr-FR")} %`, "tax-kpi-rate"], ["Provision fiscale conseillée / mois", eur(d.provision.monthly), "tax-kpi-provision"], ["Impôts à payer sous 90 jours", eur(d.provision.next_90_days), "tax-kpi-90"]].map(([l, v, t]) => <div key={t} className={box} data-testid={t}><div className="text-xs text-muted-foreground">{l}</div><div className="text-2xl font-bold">{v}</div></div>)}</div>
      <p className="text-xs text-muted-foreground" data-testid="tax-limits">Exercice du {fr(d.fiscal_year.start)} au {fr(d.fiscal_year.end)}. {d.note} {d.limits.join(" ")}</p>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className={`${box} space-y-1 text-sm`} data-testid="tax-is-detail"><b>Du résultat estimé à l'IS</b>
          {rows(e.products)}{rows(e.charges, "− ")}{total("Résultat comptable estimé", e.accounting_result, "tax-accounting")}
          {rows(e.reintegrations, "+ ")}{rows(e.deductions, "− ")}{e.deficits_used > 0 && rows([{ label: `Déficits reportables imputés (disponibles : ${eur(e.deficits_available)})`, amount: e.deficits_used }], "− ")}
          {total("Résultat fiscal estimé", e.taxable_result, "tax-taxable")}
          {d.regime !== "is" ? <p className="text-muted-foreground">Société à l'impôt sur le revenu : pas d'IS calculé.</p> : <>
            {d.eligible ? rows([{ label: `${eur(e.base_reduit)} à ${e.rates.reduit} %`, amount: e.is_reduit }]) : <p className="text-xs text-amber-700">Taux réduit non appliqué : conditions d'éligibilité non cochées dans les paramètres.</p>}
            {rows([{ label: `${eur(e.base_normal)} à ${e.rates.normal} %`, amount: e.is_normal }])}{e.credits > 0 && rows([{ label: "Crédits et réductions d'impôt", amount: e.credits }], "− ")}{total("IS estimé", e.is_total, "tax-is-total")}
            <p className="text-xs text-muted-foreground">IS de l'exercice précédent : {eur(d.reference.is_n1)} ({d.reference.source}) · acomptes pointés payés : {eur(d.acomptes_paid)}</p></>}
          {d.history.length > 1 && <p className="text-xs text-muted-foreground" data-testid="tax-history">Historique de l'estimation : {d.history.map((h) => `${h.month.slice(5)}/${h.month.slice(0, 4)} ${eur(h.is_total)}`).join(" · ")}</p>}</div>
        <div className={`${box} space-y-2 text-sm`} data-testid="tax-inputs"><b>Vos hypothèses</b>
          <div className="grid grid-cols-2 gap-2">{num("pending_weight_pct", "Devis en cours comptés à (%)", "tax-in-weight")}{num("credits", "Crédits d'impôt (€)", "tax-in-credits")}{num("is_n1", "IS de l'exercice précédent (vide = exercice importé)", "tax-in-isn1")}{num("deficits", "Déficits reportables (vide = liasse importée)", "tax-in-deficits")}{num("cfe_amount", "CFE : montant du dernier avis (€)", "tax-in-cfe")}
            <label className="flex items-end gap-2 text-xs"><input type="checkbox" disabled={ro} checked={f.use_deficits} onChange={(ev) => setF({ ...f, use_deficits: ev.target.checked })} />Imputer les déficits reportables</label></div>
          <div className="text-xs text-muted-foreground">Lignes à ajouter (salaires, amortissements, amendes, quote-part véhicules…)</div>
          {f.lines.map((l, i) => <div key={i} className="flex gap-2" data-testid={`tax-line-${i}`}><select disabled={ro} className="h-8 rounded-lg border border-border bg-background px-1 text-xs" value={l.kind} onChange={(ev) => setF({ ...f, lines: f.lines.map((x, j) => (j === i ? { ...x, kind: ev.target.value } : x)) })}>{Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
            <Input disabled={ro} className="h-8 min-w-0 flex-1" placeholder="Libellé" value={l.label} onChange={(ev) => setF({ ...f, lines: f.lines.map((x, j) => (j === i ? { ...x, label: ev.target.value } : x)) })} data-testid={`tax-line-label-${i}`} />
            <Input disabled={ro} type="number" min="0" className="h-8 w-28" value={l.amount} onChange={(ev) => setF({ ...f, lines: f.lines.map((x, j) => (j === i ? { ...x, amount: Number(ev.target.value) } : x)) })} data-testid={`tax-line-amount-${i}`} />
            {!ro && <button aria-label="Supprimer" onClick={() => setF({ ...f, lines: f.lines.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></button>}</div>)}
          {!ro && <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setF({ ...f, lines: [...f.lines, { kind: "charge", label: "", amount: 0 }] })} data-testid="tax-line-add">Ajouter une ligne</Button><Button size="sm" onClick={save} data-testid="tax-inputs-save">Recalculer</Button></div>}</div>
      </div>
      {d.reference.exempt && d.regime === "is" && <p className={`${box} text-sm`} data-testid="tax-exempt">Dispense d'acomptes : l'IS de référence ({eur(d.reference.is_n1)}) est inférieur au seuil de {eur(d.reference.seuil_dispense)}. L'IS sera payé en une fois au solde.</p>}
      {d.modulation.possible && <div className="rounded-2xl border border-amber-500/60 bg-amber-500/10 p-4 text-sm" data-testid="tax-modulation"><b>Modulation possible des acomptes : {eur(d.modulation.saving)} de trésorerie conservée</b>
        {d.modulation.suggested.map((s) => <div key={s.key}>{s.label} du {fr(s.due_date)} : {eur(s.current)} → {eur(s.suggested)}</div>)}<p className="mt-1 text-xs">{d.modulation.warning}</p></div>}
      <div className={`${box} overflow-x-auto`} data-testid="tax-calendar"><b>Calendrier fiscal</b> <span className="text-xs text-muted-foreground">Pointage manuel : l'application ne déclare et ne paie rien.</span>
        <table className="mt-2 w-full text-sm"><thead><tr className="border-b border-border text-left text-xs text-muted-foreground"><th className="py-1">Date</th><th>Impôt</th><th>Échéance</th><th className="text-right">Montant</th><th>Statut</th><th /></tr></thead>
          <tbody>{d.calendar.map((x) => <tr key={x.key} className="border-b border-border/50" data-testid={`tax-due-${x.key}`}><td className="whitespace-nowrap py-1">{fr(x.due_date)}{x.alert && <span className="ml-1 rounded-full bg-amber-500 px-1.5 text-xs text-white">{x.alert}</span>}</td><td>{x.tax}</td><td>{x.label}<div className="text-xs text-muted-foreground">{x.detail}</div></td>
            <td className="whitespace-nowrap text-right">{eur(x.amount)}<div className="text-xs text-muted-foreground">{x.final ? "définitif" : "estimé"}</div></td><td><span className={`rounded-full px-2 py-0.5 text-xs ${ST[x.status][1]}`}>{ST[x.status][0]}</span></td>
            <td className="whitespace-nowrap text-right">{!ro && <><button className="text-xs underline" onClick={() => mark(x, { paid: x.status !== "paid", final_amount: x.final ? x.amount : null })} data-testid={`tax-due-paid-${x.key}`}>{x.status === "paid" ? "annuler" : "pointer payé"}</button>
              <button className="ml-2 text-xs underline" onClick={() => { const v = window.prompt("Montant définitif (vide = revenir à l'estimation)", x.final ? x.amount : ""); if (v !== null) mark(x, { paid: x.status === "paid", final_amount: v.trim() === "" ? null : Number(v.replace(",", ".")) }); }}>montant</button></>}</td></tr>)}</tbody></table></div>
      {d.tva.length > 0 && <div className={`${box} overflow-x-auto`} data-testid="tax-tva"><b>TVA prévisionnelle</b> <span className="text-xs text-muted-foreground">{d.tva_note || "D'après les factures, paiements, devis signés, factures d'achat et abonnements de l'application."}</span>
        <table className="mt-2 w-full text-sm"><thead><tr className="border-b border-border text-xs text-muted-foreground"><th className="py-1 text-left">Période</th><th className="text-right">Collectée</th><th className="text-right">Déductible</th><th className="text-right">Crédit reporté</th><th className="text-right">À payer</th><th className="text-right">Échéance</th></tr></thead>
          <tbody>{d.tva.map((t) => <tr key={t.period} className={`border-b border-border/50 ${t.past ? "text-muted-foreground" : ""}`}><td className="py-1">{t.period}</td><td className="text-right">{eur(t.collected)}</td><td className="text-right">{eur(t.deductible)}</td><td className="text-right">{eur(t.credit_in)}</td><td className="text-right font-semibold">{t.to_pay ? eur(t.to_pay) : `crédit ${eur(t.credit_out)}`}</td><td className="text-right">{fr(t.due_date)}</td></tr>)}</tbody></table></div>}
      <p className="text-sm text-muted-foreground" data-testid="tax-cvae">CVAE : {d.cvae.concerned ? "société concernée" : d.cvae.must_declare ? "déclaration à déposer, pas de paiement" : "société non concernée"} (chiffre d'affaires du dernier exercice importé : {eur(d.cvae.ca_n1)}). Provision sur 12 mois : TVA {eur(d.provision.by_tax.TVA)} · IS {eur(d.provision.by_tax.IS)} · CFE {eur(d.provision.by_tax.CFE)}.</p>
    </div>);
}
