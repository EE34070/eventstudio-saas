import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { FileText, Plus, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PageHeader, Loading } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { fmtDate, fmtEur2 } from "@/lib/constants";
import { openFile } from "@/lib/files";
import { useMe } from "@/context/MeContext";
import { download } from "@/components/finance/Report";
import { EditOccurrence } from "@/components/contracts/EditOccurrence";

const ko = (e) => toast.error(errMsg(e));
const sel = "h-9 rounded-lg border border-border bg-background px-2 text-sm";
const PERIOD = { monthly: "mensuel", quarterly: "trimestriel", yearly: "annuel" };
const STATUS = { actif: "Actif", essai: "Essai", a_resilier: "À résilier", resilie: "Résilié", en_cours_de_deblocage: "En cours de déblocage", en_remboursement: "En remboursement", solde: "Soldé", rembourse_par_anticipation: "Remboursé par anticipation", renegocie: "Renégocié" };
const KINDS = { contract: "Contrat signé", terms: "Conditions générales", amendment: "Avenant", schedule: "Tableau d'amortissement", letter: "Courrier" };
const SUB = { name: "", supplier_name: "", supplier_contact_id: "", category: "", amount: "", vat_rate: 20, period: "monthly", billing_day: "", start_date: "", business_day_rule: "next", commitment_months: 0, tacit_renewal: true, notice_days: 0, payment_method: "", account_id: "", owner: "", licenses: 0, account_ref: "", contract_ref: "", status: "actif", notes: "", renewal_date: "", active: true };
const LOAN = { name: "", bank: "", contract_ref: "", type: "amortissable", capital: "", rate_pct: "", months: 60, period: "monthly", first_due_date: "", billing_day: "", business_day_rule: "next", deferral_months: 0, deferral_type: "partial", insurance_monthly: 0, fees: 0, rent: 0, first_rent: 0, option_value: 0, option_date: "", account_id: "", personal_guarantee: false, guarantees: "", notes: "", status: "", installments: null };
const SUB_F = [["name", "Service *"], ["supplier_name", "Fournisseur"], ["category", "Catégorie"], ["amount", "Montant HT par échéance *", "number"], ["vat_rate", "TVA %", "number"], ["period", "Périodicité", PERIOD], ["start_date", "Date de début", "date"], ["billing_day", "Jour de prélèvement", "number"],
  ["business_day_rule", "Report au jour ouvré", { next: "suivant", previous: "précédent", none: "aucun" }], ["commitment_months", "Engagement (mois, 0 = sans)", "number"], ["notice_days", "Préavis (jours)", "number"], ["tacit_renewal", "Reconduction tacite", "check"], ["personal_non_deductible", "Personnel / non déductible (réintégré dans le résultat fiscal)", "check"], ["payment_method", "Mode de paiement"], ["account_id", "Compte débité", "account"],
  ["owner", "Responsable"], ["licenses", "Licences", "number"], ["account_ref", "N° de compte client"], ["contract_ref", "N° de contrat"], ["status", "Statut", { actif: "Actif", essai: "Essai", a_resilier: "À résilier", resilie: "Résilié" }], ["notes", "Notes"]];
const LOAN_F = [["name", "Objet du prêt *"], ["bank", "Banque"], ["contract_ref", "N° de contrat"], ["type", "Type", { amortissable: "Amortissable", in_fine: "In fine", lease: "Crédit-bail / LOA" }], ["capital", "Capital", "number"], ["rate_pct", "Taux %", "number"], ["months", "Durée (mois)", "number"], ["period", "Périodicité", PERIOD],
  ["first_due_date", "1re échéance *", "date"], ["billing_day", "Jour de prélèvement", "number"], ["business_day_rule", "Report au jour ouvré", { next: "suivant", previous: "précédent", none: "aucun" }], ["deferral_months", "Différé (mois)", "number"], ["deferral_type", "Type de différé", { partial: "partiel", total: "total" }],
  ["insurance_monthly", "Assurance / mois", "number"], ["fees", "Frais de dossier et garantie", "number"], ["rent", "Loyer (crédit-bail)", "number"], ["first_rent", "1er loyer majoré", "number"], ["option_value", "Valeur de levée d'option", "number"], ["option_date", "Date de levée d'option", "date"], ["account_id", "Compte débité", "account"],
  ["personal_guarantee", "Caution personnelle du gérant", "check"], ["guarantees", "Garanties"], ["notes", "Notes"]];
const clean = (f, fields) => ({ ...f, ...Object.fromEntries(fields.filter(([, , t]) => t === "number").map(([k]) => [k, f[k] === "" || f[k] == null ? (k === "billing_day" ? null : 0) : Number(f[k])])), active: f.status !== "resilie" });

function Form({ kind, value, accounts, ai, onClose, onSaved }) {
  const [f, setF] = useState(value);
  const [doubt, setDoubt] = useState([]);
  const [busy, setBusy] = useState(false);
  const file = useRef(null);
  const fields = kind === "loan" ? LOAN_F : SUB_F;
  const base = kind === "loan" ? "/loans" : "/subscriptions";
  const read = async (e) => { const x = e.target.files[0]; e.target.value = ""; if (!x) return; setBusy(true); const fd = new FormData(); fd.append("file", x);
    try { const r = await api.post(`/contracts/extract?kind=${kind === "loan" ? "loan" : "subscription"}`, fd); const ex = r.data.extracted || {}; setDoubt(ex.uncertain || []); setF((c) => ({ ...c, ...Object.fromEntries(Object.entries(ex).filter(([k, v]) => k !== "uncertain" && v !== "" && v !== 0 && v != null)), _file: x })); toast[r.data.extracted ? "success" : "message"](r.data.message || "Fiche pré-remplie : vérifiez les champs en orange"); } catch (err) { ko(err); } setBusy(false); };
  const save = async () => { try { const { _file, id, ...b } = clean(f, fields); const r = id ? await api.put(`${base}/${id}`, b) : await api.post(base, b);
    if (_file) { const fd = new FormData(); fd.append("file", _file); fd.append("owner_type", kind); fd.append("owner_id", r.data.id); fd.append("kind", kind === "loan" && f.installments ? "schedule" : "contract"); await api.post("/contract-documents", fd); }
    toast.success("Enregistré"); onSaved(r.data); } catch (e) { ko(e); } };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}><DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto" data-testid={`${kind}-form`}>
      <DialogHeader><DialogTitle>{f.id ? "Modifier" : "Nouveau"} {kind === "loan" ? "prêt / financement" : "abonnement"}</DialogTitle><DialogDescription>Les champs lus par l'IA sont à vérifier avant d'enregistrer.</DialogDescription></DialogHeader>
      {!f.id && <div className="flex items-center gap-3 rounded-xl border border-dashed border-border p-3"><input ref={file} type="file" hidden accept="application/pdf,image/*" onChange={read} data-testid={`${kind}-contract-input`} />
        <Button size="sm" variant="outline" disabled={busy} onClick={() => file.current.click()} data-testid={`${kind}-from-contract`}><Upload />{busy ? "Lecture…" : kind === "loan" ? "Créer depuis l'offre ou le tableau d'amortissement" : "Créer depuis un contrat"}</Button>
        <span className="text-xs text-muted-foreground">{ai ? "PDF ou image : la fiche est pré-remplie, le fichier est archivé." : "Lecture IA indisponible : le fichier sera seulement archivé."}{f.installments ? ` ${f.installments.length} échéances importées.` : ""}</span></div>}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">{fields.map(([k, l, t]) => (
        <label key={k} className={`text-xs ${doubt.includes(k) ? "font-semibold text-amber-600" : "text-muted-foreground"}`}>{l}{doubt.includes(k) ? " (à vérifier)" : ""}
          {t === "check" ? <input type="checkbox" className="ml-2" checked={!!f[k]} onChange={(e) => setF({ ...f, [k]: e.target.checked })} data-testid={`${kind}-${k}`} />
            : t === "account" ? <select className={`${sel} mt-1 w-full`} value={f[k] || ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} data-testid={`${kind}-${k}`}><option value="">—</option>{accounts.map((a) => <option key={a.id} value={a.id}>{a.name}{a.bank ? ` (${a.bank})` : ""}</option>)}</select>
            : typeof t === "object" ? <select className={`${sel} mt-1 w-full`} value={f[k] || ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} data-testid={`${kind}-${k}`}>{Object.entries(t).map(([v, x]) => <option key={v} value={v}>{x}</option>)}</select>
            : <Input className={`mt-1 h-9 ${doubt.includes(k) ? "border-amber-500" : ""}`} type={t || "text"} step="any" value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} data-testid={`${kind}-${k}`} />}</label>))}</div>
      <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Annuler</Button><Button disabled={!String(f.name).trim() || (kind === "loan" ? !f.first_due_date : f.amount === "")} onClick={save} data-testid={`${kind}-save`}>Enregistrer</Button></div>
    </DialogContent></Dialog>);
}

function Detail({ row, write, onClose, onChanged }) {
  const [d, setD] = useState(null);
  const [docs, setDocs] = useState([]);
  const [sim, setSim] = useState(null);
  const [amt, setAmt] = useState("");
  const [kind, setKind] = useState("contract");
  const file = useRef(null);
  const loan = row.kind === "loan";
  const load = useCallback(() => { api.get(loan ? `/loans/${row.id}` : `/subscriptions/${row.id}/occurrences`).then((r) => setD(r.data)).catch(ko); api.get("/contract-documents", { params: { owner_id: row.id } }).then((r) => setDocs(r.data)).catch(ko); }, [row.id, loan]);
  useEffect(() => { load(); }, [load]);
  const today = new Date().toISOString().slice(0, 10);
  const [edit, setEdit] = useState(null);
  const up = (e) => { const x = e.target.files[0]; e.target.value = ""; if (!x) return; const fd = new FormData(); fd.append("file", x); fd.append("owner_type", row.kind); fd.append("owner_id", row.id); fd.append("kind", kind); api.post("/contract-documents", fd).then((r) => { setDocs(r.data); onChanged(); }).catch(ko); };
  const rows = d ? (loan ? d.schedule : d.occurrences) : [];
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}><DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto" data-testid="contract-detail">
      <DialogHeader><DialogTitle>{row.name}</DialogTitle><DialogDescription>{row.party} · {STATUS[row.status] || row.status}{row.personal_guarantee ? " · caution personnelle du gérant" : ""}</DialogDescription></DialogHeader>
      {d?.gap_alert && <div className="rounded-lg bg-amber-500/10 p-2 text-sm text-amber-700" data-testid="loan-gap-alert">{d.gap_alert}</div>}
      <div data-testid="contract-documents"><div className="eyebrow mb-1">Documents</div>
        {docs.map((x) => <div key={x.id} className="flex items-center gap-2 py-1 text-sm"><FileText className="h-4 w-4" /><button className="underline" onClick={() => openFile(`file:${x.file_id}`)}>{KINDS[x.kind]} — {x.filename}</button><span className="text-xs text-muted-foreground">{fmtDate(x.date)}</span>{write && <button aria-label="Supprimer" onClick={() => api.delete(`/contract-documents/${x.id}`).then((r) => { setDocs(r.data); onChanged(); }).catch(ko)}><Trash2 className="h-3.5 w-3.5" /></button>}</div>)}
        {write && <div className="mt-1 flex gap-2"><select className={sel} value={kind} onChange={(e) => setKind(e.target.value)} data-testid="doc-kind">{Object.entries(KINDS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select><input ref={file} type="file" hidden onChange={up} data-testid="doc-input" /><Button size="sm" variant="outline" onClick={() => file.current.click()} data-testid="doc-add"><Upload />Ajouter</Button></div>}</div>
      {loan && d && row.category.startsWith("Prêt") && <div className="rounded-xl border border-border p-3 text-sm" data-testid="loan-simulator"><div className="eyebrow mb-1">Remboursement anticipé</div>
        <div className="flex flex-wrap items-center gap-2"><Input className="h-9 w-36" type="number" placeholder="Montant" value={amt} onChange={(e) => setAmt(e.target.value)} data-testid="sim-amount" />
          {[["duration", "Réduire la durée"], ["payment", "Réduire la mensualité"]].map(([m, l]) => <Button key={m} size="sm" variant="outline" disabled={!amt} onClick={() => api.get(`/loans/${row.id}/simulate`, { params: { amount: amt, mode: m } }).then((r) => setSim(r.data)).catch(ko)} data-testid={`sim-${m}`}>{l}</Button>)}</div>
        {sim && <div className="mt-2" data-testid="sim-result">Capital restant {fmtEur2(sim.new_principal)} · {sim.new_installments} échéances de {fmtEur2(sim.new_payment)} · intérêts économisés {fmtEur2(sim.interest_saved)} · indemnité estimée {fmtEur2(sim.penalty)}<div className="text-xs text-muted-foreground">{sim.note}</div></div>}</div>}
      <div className="eyebrow">{loan ? "Tableau d'amortissement" : "Prélèvements (18 mois)"}</div>
      <table className="w-full text-sm" data-testid="contract-schedule"><thead><tr className="border-b border-border text-left text-xs text-muted-foreground"><th>Date contractuelle</th><th>Prélèvement attendu</th><th className="text-right">Montant</th>{loan && <><th className="text-right">Capital</th><th className="text-right">Intérêts</th><th className="text-right">Assurance</th><th className="text-right">Restant dû</th></>}<th>Statut</th><th /></tr></thead>
        <tbody>{rows.map((o) => { const key = loan ? o.n : o.contractual_date; const amount = loan ? o.total : o.expected_amount; return (
          <tr key={key} className="border-b border-border last:border-0" data-testid={`occ-${key}`}><td>{fmtDate(o.contractual_date)}</td><td>{fmtDate(o.expected_debit_date)}</td><td className="text-right">{fmtEur2(amount)}{o.is_manual_override ? <span title={o.override_reason}> ✎</span> : ""}</td>
            {loan && <><td className="text-right">{fmtEur2(o.principal)}</td><td className="text-right">{fmtEur2(o.interest)}</td><td className="text-right">{fmtEur2(o.insurance)}</td><td className="text-right">{fmtEur2(o.remaining_principal)}</td></>}
            <td className="text-xs">{{ facturee: "Facturée", passee: "Passée", payee: "Payée", a_venir: "À venir" }[o.status]}</td>
            <td className="whitespace-nowrap text-xs">{write && (o.expected_debit_date >= today && !o.bank_transaction_id ? <button className="underline" onClick={() => setEdit(o)} data-testid={`occ-edit-${key}`}>modifier</button> : <span className="text-muted-foreground" title="Échéance déjà prélevée ou rapprochée : son montant n'est plus modifiable" data-testid={`occ-locked-${key}`}>verrouillée</span>)}</td></tr>); })}</tbody></table>
      {edit && <EditOccurrence loan={loan} id={row.id} row={edit} onClose={() => setEdit(null)} onSaved={(data) => { setD(data); setEdit(null); onChanged(); }} />}
    </DialogContent></Dialog>);
}

function Pending({ write, onDone, onCreate }) {
  const [rows, setRows] = useState([]);
  const load = useCallback(() => api.get("/subscription-invoices/pending").then((r) => setRows(r.data)).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);
  if (!rows.length) return null;
  const post = (id, body) => api.post(`/subscription-invoices/${id}/link`, body).then(() => { load(); onDone(); toast.success("Facture traitée"); }).catch(ko);
  return (<div className="card-soft mb-4 p-4" data-testid="pending-invoices"><div className="eyebrow mb-2">Factures d'abonnement à confirmer ({rows.length})</div>
    {rows.map((i) => <div key={i.id} className="flex flex-wrap items-center gap-2 border-b border-border py-2 text-sm last:border-0" data-testid={`pending-${i.id}`}><b>{i.supplier_name}</b><span>{i.number} · {fmtDate(i.date)} · {fmtEur2(i.amount_ht)} HT</span><span className="flex-1" />
      {write && i.candidates.map((c) => <Button key={c.id} size="sm" variant="outline" onClick={() => post(i.id, { links: [{ subscription_id: c.id, amount: i.amount_ht }] })} data-testid={`pending-link-${i.id}-${c.id}`}>Lier à {c.name}{c.delta ? ` (${c.delta > 0 ? "+" : ""}${fmtEur2(c.delta)}, ${c.delta_pct > 0 ? "+" : ""}${String(c.delta_pct).replace(".", ",")} %)` : ""}</Button>)}
      {write && !i.candidates.length && <Button size="sm" variant="outline" onClick={() => onCreate({ ...SUB, ...i.suggested, created_from_invoice_id: i.id })} data-testid={`pending-create-${i.id}`}>Créer l'abonnement</Button>}
      {write && <><button className="text-xs underline" onClick={() => post(i.id, { ignore: true })} data-testid={`pending-ignore-${i.id}`}>Pas un abonnement</button><button className="text-xs underline" onClick={() => post(i.id, { ignore: true, never: true })}>ne plus proposer</button></>}</div>)}</div>);
}

function Calendar() {
  const [d, setD] = useState(null);
  useEffect(() => { api.get("/debits").then((r) => setD(r.data)).catch(ko); }, []);
  if (!d) return null;
  return (<div className="grid grid-cols-1 gap-4 lg:grid-cols-3" data-testid="debits-calendar">
    <div className="card-soft p-4 lg:col-span-2"><div className="eyebrow mb-2">Prochains prélèvements (3 mois) — {fmtEur2(d.total)}</div>{d.by_day.map((day) => <div key={day.key} className="border-b border-border py-1.5 text-sm last:border-0" data-testid={`debit-day-${day.key}`}><div className="flex justify-between font-medium"><span>{fmtDate(day.key)}</span><span>{fmtEur2(day.total)}</span></div>
      {d.rows.filter((r) => r.date === day.key).map((r, i) => <div key={i} className="flex justify-between text-xs text-muted-foreground"><span>{r.kind === "loan" ? "Prêt" : "Abonnement"} · {r.name} · {r.account}</span><span>{fmtEur2(r.amount)}</span></div>)}</div>)}</div>
    <div className="card-soft p-4"><div className="eyebrow mb-2">Par compte bancaire</div>{d.by_account.map((a) => <div key={a.key} className="flex justify-between py-1 text-sm"><span>{a.key}</span><b>{fmtEur2(a.total)}</b></div>)}</div></div>);
}

export default function Contracts() {
  const { can } = useMe();
  const [d, setD] = useState(null);
  const [view, setView] = useState("subscriptions");
  const [form, setForm] = useState(null);
  const [open, setOpen] = useState(null);
  const [q, setQ] = useState("");
  const [st, setSt] = useState("");
  const [sort, setSort] = useState("name");
  const load = useCallback(() => api.get("/contracts/list").then((r) => setD(r.data)).catch(ko), []);
  useEffect(() => { load(); }, [load]);
  if (!d) return <Loading />;
  const write = d.write && can("finance:write");
  const loans = view === "loans";
  const rows = (d[view] || []).filter((r) => (!q || `${r.name} ${r.party} ${r.category} ${r.account}`.toLowerCase().includes(q.toLowerCase())) && (!st || r.status === st)).sort((a, b) => (typeof a[sort] === "number" ? (b[sort] || 0) - (a[sort] || 0) : String(a[sort] || "9").localeCompare(String(b[sort] || "9"))));
  const accounts = () => { const txt = window.prompt("Comptes bancaires, un par ligne sous la forme « Nom ; Banque »", d.accounts.map((a) => `${a.name} ; ${a.bank}`).join("\n")); if (txt == null) return;
    api.put("/bank-accounts", { accounts: txt.split("\n").map((l) => { const [name, bank] = l.split(";").map((x) => x.trim()); const old = d.accounts.find((a) => a.name === name); return { id: old?.id || "", name: name || "", bank: bank || "" }; }) }).then(load).catch(ko); };
  return (
    <div data-testid="subscriptions-page">
      <PageHeader eyebrow="Achats" title="Abonnements, prêts & financements" subtitle="Échéances, engagements et prélèvements attendus. Le rapprochement bancaire viendra avec Pennylane."
        actions={write && <><Button variant="outline" size="sm" onClick={accounts} data-testid="bank-accounts-button">Comptes bancaires</Button><Button onClick={() => setForm(loans ? { kind: "loan", value: LOAN } : { kind: "subscription", value: SUB })} data-testid={loans ? "new-loan-button" : "new-subscription-button"}><Plus />{loans ? "Prêt" : "Abonnement"}</Button></>} />
      <div className="mb-4 flex flex-wrap items-center gap-2" data-testid="contracts-switch">{[["subscriptions", "Abonnements"], ["loans", "Prêts & financements"], ["calendar", "Calendrier des prélèvements"]].map(([k, l]) => <button key={k} onClick={() => { setView(k); setSt(""); }} data-testid={`contracts-view-${k}`} className={`h-9 rounded-full border px-4 text-sm font-medium ${view === k ? "border-primary bg-primary text-white" : "border-border hover:bg-secondary"}`}>{l}</button>)}
        {view !== "calendar" && <><Input className="h-9 w-56 bg-card" placeholder="Filtrer (nom, banque, catégorie, compte)" value={q} onChange={(e) => setQ(e.target.value)} data-testid="contracts-filter" />
          <select className={sel} value={st} onChange={(e) => setSt(e.target.value)} data-testid="contracts-status-filter"><option value="">Tous statuts</option>{[...new Set(d[view].map((r) => r.status))].map((s) => <option key={s} value={s}>{STATUS[s] || s}</option>)}</select>
          <select className={sel} value={sort} onChange={(e) => setSort(e.target.value)} data-testid="contracts-sort"><option value="name">Tri : nom</option><option value="end_date">fin la plus proche</option><option value="next_date">prochaine échéance</option><option value="monthly">mensualité</option><option value="remaining_amount">restant à payer</option></select>
          <span className="flex-1" /><Button size="sm" variant="outline" onClick={() => download("/contracts/export", { kind: view, format: "xlsx" }, `${view}.xlsx`)} data-testid="contracts-export-xlsx">Excel</Button><Button size="sm" variant="outline" onClick={() => download("/contracts/export", { kind: view, format: "pdf" }, `${view}.pdf`)} data-testid="contracts-export-pdf">PDF</Button></>}</div>
      {view === "calendar" ? <Calendar /> : <>
        {!loans && <Pending write={write} onDone={load} onCreate={(v) => setForm({ kind: "subscription", value: v })} />}
        <div className="card-soft divide-y divide-border" data-testid="contracts-list">{!rows.length && <p className="p-5 text-sm text-muted-foreground">Aucun contrat.</p>}
          {rows.map((r) => (
            <div key={r.id} className={`px-5 py-3 text-sm ${r.status === "resilie" || r.status === "solde" ? "opacity-60" : ""}`} data-testid={`${loans ? "loan" : "subscription"}-row-${r.id}`}>
              <div className="flex flex-wrap items-center gap-3"><button className="min-w-0 flex-1 text-left" onClick={() => setOpen(r)} data-testid={`contract-open-${r.id}`}><div className="font-semibold">{r.name}</div><div className="text-xs text-muted-foreground">{[r.party, r.category, r.account, STATUS[r.status] || r.status].filter(Boolean).join(" · ")}</div></button>
                {r.has_contract ? <FileText className="h-4 w-4 text-emerald-600" data-testid={`contract-ok-${r.id}`} /> : <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-700" data-testid={`contract-missing-${r.id}`}>contrat manquant</span>}
                {r.alert && <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-xs text-red-700" data-testid={`contract-alert-${r.id}`}>{r.alert}</span>}
                <div className="text-right" title={r.split ? `Capital ${fmtEur2(r.split.principal)} · intérêts ${fmtEur2(r.split.interest)} · assurance ${fmtEur2(r.split.insurance)}` : undefined}><b data-testid={`contract-installment-${r.id}`}>{fmtEur2(r.installment)}</b><div className="text-xs text-muted-foreground">{PERIOD[r.period]}</div></div>
                {write && <button className="text-xs underline" onClick={() => api.get(loans ? `/loans/${r.id}` : `/subscriptions/${r.id}/occurrences`).then((x) => setForm({ kind: loans ? "loan" : "subscription", value: { ...(loans ? LOAN : SUB), ...(loans ? x.data.loan : x.data.subscription) } })).catch(ko)} data-testid={`contract-edit-${r.id}`}>Modifier</button>}
                {write && <button aria-label="Supprimer" onClick={() => window.confirm("Placer ce contrat dans la Corbeille (30 jours) ?") && api.delete(`${loans ? "/loans" : "/subscriptions"}/${r.id}`).then(load).catch(ko)}><Trash2 className="h-4 w-4" /></button>}</div>
              <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground"><span>Prochaine : {r.next_date ? `${fmtDate(r.next_date)} (${fmtEur2(r.next_amount)})` : "—"}</span><span>Fin : {r.end_date ? fmtDate(r.end_date) : "sans engagement"}</span><span data-testid={`contract-time-left-${r.id}`}>Reste : {r.time_left}</span>
                {r.total_count != null && <span data-testid={`contract-remaining-${r.id}`}>{r.remaining_count} / {r.total_count} échéances</span>}{r.remaining_amount != null && <span data-testid={`contract-remaining-amount-${r.id}`}>Restant à payer : {fmtEur2(r.remaining_amount)}</span>}
                {r.remaining_principal != null && <span>Capital restant dû : {fmtEur2(r.remaining_principal)}</span>}{r.deadline && <span>{loans ? "Levée d'option" : "Résiliation avant le"} {fmtDate(r.deadline)}</span>}
                {r.progress != null && <span className="flex items-center gap-1"><span className="inline-block h-1.5 w-24 overflow-hidden rounded-full bg-secondary"><span className="block h-full bg-primary" style={{ width: `${r.progress}%` }} /></span><span data-testid={`contract-progress-${r.id}`}>{r.progress} %</span></span>}</div>
            </div>))}</div>
        <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-5" data-testid="contracts-footer">{[["monthly_subscriptions", "Abonnements / mois", "subs-monthly"], ["monthly_loans", "Prêts / mois"], ["monthly_total", "Ensemble / mois"], ["remaining_total", "Restant à payer"], ["remaining_principal_total", "Capital restant dû"]].map(([k, l, tid]) => <div key={k} className="card-soft p-3"><div className="text-xs text-muted-foreground">{l}</div><div className="font-display text-xl" data-testid={tid || `footer-${k}`}>{fmtEur2(d.footer[k])}</div></div>)}</div></>}
      {form && <Form kind={form.kind} value={form.value} accounts={d.accounts} ai={d.ai} onClose={() => setForm(null)} onSaved={(saved) => { const inv = form.value.created_from_invoice_id; setForm(null); (inv ? api.post(`/subscription-invoices/${inv}/link`, { links: [{ subscription_id: saved.id }] }) : Promise.resolve()).then(load).catch(ko); }} />}
      {open && <Detail row={open} write={write} onClose={() => setOpen(null)} onChanged={load} />}
    </div>);
}
