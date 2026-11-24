import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, errMsg } from "@/lib/api";
import { Alert, F, In, Note, Pick, T, dl, eur, inp, run, upload, useLoad } from "@/components/social/kit";

const TYPES = [["cdi", "CDI"], ["cdd", "CDD"], ["cddu", "CDDU (intermittent)"], ["alternance", "Apprentissage"], ["stage", "Stage"], ["extra", "Extra"]];
const tl = (t) => TYPES.find((x) => x[0] === t)?.[1] || t || "—";
const STATUS = { actif: "Actif", sorti: "Sorti", en_attente: "En attente d'embauche" };
const DOCS = [["contrat", "Contrat"], ["avenant", "Avenant"], ["dpae", "DPAE"], ["identite", "Pièce d'identité"], ["sejour", "Titre de séjour"], ["bulletin", "Bulletin"], ["attestation", "Attestation"], ["certificat", "Certificat de travail"], ["solde", "Solde de tout compte"], ["dispense", "Dispense mutuelle"], ["entretien", "Compte rendu d'entretien"], ["autre", "Autre"]];
const openFile = (fid) => api.get(`/files/${fid}/link`).then((r) => window.open(r.data.url?.startsWith("http") ? r.data.url : process.env.REACT_APP_BACKEND_URL + r.data.url, "_blank", "noopener")).catch((e) => toast.error(errMsg(e)));

function Sheet({ tid, onClose, can }) {
  const [d, load] = useLoad(`/social/employees/${tid}`);
  const [f, setF] = useState(null);
  const [sec, setSec] = useState(null);
  const [doc, setDoc] = useState("contrat");
  if (!d) return null;
  const v = f || { status: d.status, ...d.file, ssn: null, iban: null };
  const save = () => run(api.put(`/social/employees/${tid}`, { ...v, trainings: v.trainings || [], habilitations: v.habilitations || [], documents: v.documents || [], leave_carry: Number(v.leave_carry) || 0, split_days: Number(v.split_days) || 0 }), "Fiche enregistrée", () => { setF(null); load(); });
  const list = (k, label, withExp) => (
    <div className="col-span-2"><div className="eyebrow mb-1">{label}</div>
      {(v[k] || []).map((x, i) => <div key={i} className="mb-1 flex gap-2"><input className={inp} placeholder="Intitulé" value={x.label} onChange={(e) => setF({ ...v, [k]: v[k].map((y, j) => (j === i ? { ...y, label: e.target.value } : y)) })} /><input className={inp} type="date" title={withExp ? "Expiration" : "Date"} value={withExp ? x.expires : x.date} onChange={(e) => setF({ ...v, [k]: v[k].map((y, j) => (j === i ? { ...y, [withExp ? "expires" : "date"]: e.target.value } : y)) })} /><button onClick={() => setF({ ...v, [k]: v[k].filter((_, j) => j !== i) })}>×</button></div>)}
      {can && <button className="text-sm underline" onClick={() => setF({ ...v, [k]: [...(v[k] || []), { label: "", date: "", expires: "", status: "" }] })} data-testid={`emp-add-${k}`}>+ Ajouter</button>}</div>);
  return (
    <Dialog open onOpenChange={onClose}><DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto" data-testid="employee-sheet">
      <DialogHeader><DialogTitle>{d.name}</DialogTitle><DialogDescription>{tl(d.contract_type)} · {d.job || "emploi non renseigné"} · coefficient employeur {d.coef} ({d.coef_source})</DialogDescription></DialogHeader>
      {d.alerts.map((a, i) => <Alert key={i} a={a} />)}
      {d.changes.map((c) => <div key={c.id} className="rounded-lg bg-blue-500/10 p-3 text-sm" data-testid="emp-change">Demande du salarié : {[c.phone && `téléphone ${c.phone}`, c.address && `adresse ${c.address}`, c.has_iban && `nouveau RIB (…${c.iban_last4})`].filter(Boolean).join(" · ")}
        {can && <span className="ml-2"><button className="underline" onClick={() => run(api.post(`/social/changes/${c.id}/decide`, { approve: true }), "Validé", load)} data-testid="emp-change-ok">Valider</button> · <button className="underline" onClick={() => run(api.post(`/social/changes/${c.id}/decide`, { approve: false }), "Refusé", load)}>Refuser</button></span>}</div>)}
      <div className="grid grid-cols-2 gap-3">
        <F label="Statut"><Pick f={v} setF={setF} k="status" opts={Object.entries(STATUS)} tid="emp-status" /></F>
        <F label="Date de naissance"><In f={v} setF={setF} k="birth_date" type="date" tid="emp-birth" /></F>
        <F label="Adresse" className="col-span-2"><In f={v} setF={setF} k="address" /></F>
        <F label="Contact d'urgence" className="col-span-2"><In f={v} setF={setF} k="emergency_contact" /></F>
        <F label={`N° de sécurité sociale (chiffré)${d.ssn_last4 ? ` — enregistré …${d.ssn_last4}` : ""}`}><input className={inp} placeholder="Saisir pour remplacer" value={v.ssn ?? ""} onChange={(e) => setF({ ...v, ssn: e.target.value })} data-testid="emp-ssn" /></F>
        <F label={`IBAN (chiffré)${d.iban_last4 ? ` — enregistré …${d.iban_last4}` : ""}`}><input className={inp} placeholder="Saisir pour remplacer" value={v.iban ?? ""} onChange={(e) => setF({ ...v, iban: e.target.value })} data-testid="emp-iban" /></F>
        {(d.ssn_last4 || d.iban_last4) && <div className="col-span-2 text-sm">{sec ? <span data-testid="emp-secrets">SS : {sec.ssn || "—"} · IBAN : {sec.iban || "—"}</span> : <button className="underline" onClick={() => api.get(`/social/employees/${tid}/secrets`).then((r) => setSec(r.data)).catch((e) => toast.error(errMsg(e)))} data-testid="emp-show-secrets">Afficher le n° SS et l'IBAN (consultation tracée)</button>}</div>}
        <F label="Mutuelle / prévoyance"><Pick f={v} setF={setF} k="mutual_status" blank="Non renseigné" opts={[["adhesion", "Adhésion"], ["dispense", "Dispense justifiée"]]} /></F>
        <F label="Fin de la dispense"><In f={v} setF={setF} k="mutual_waiver_end" type="date" /></F>
        <F label="Dernière visite médicale"><In f={v} setF={setF} k="medical_last" type="date" /></F>
        <F label="Prochaine visite médicale"><In f={v} setF={setF} k="medical_next" type="date" tid="emp-medical-next" /></F>
        <F label="Dernier entretien professionnel"><In f={v} setF={setF} k="prof_review_last" type="date" /></F>
        <F label="Prochain entretien (2 ans ; bilan à 6 ans)"><In f={v} setF={setF} k="prof_review_next" type="date" /></F>
        <F label="Expiration du titre de séjour (date seule)"><In f={v} setF={setF} k="residence_permit_end" type="date" /></F>
        <F label="N° Congés Spectacles (CDDU)"><In f={v} setF={setF} k="conges_spectacles_number" /></F>
        <F label="Report de congés (jours)"><In f={v} setF={setF} k="leave_carry" type="number" /></F>
        <F label="Jours de fractionnement"><In f={v} setF={setF} k="split_days" type="number" /></F>
        {list("trainings", "Formations (Afdas)", false)}{list("habilitations", "Habilitations (électrique, hauteur, CACES…)", true)}
        <div className="col-span-2"><div className="eyebrow mb-1">Documents</div>
          {(v.documents || []).map((x, i) => <div key={i} className="flex items-center gap-2 text-sm"><button className="underline" onClick={() => openFile(x.file_id)}>{x.label || x.kind}</button>{can && <button onClick={() => setF({ ...v, documents: v.documents.filter((_, j) => j !== i) })}>×</button>}</div>)}
          {can && <div className="mt-1 flex gap-2"><select className={inp} value={doc} onChange={(e) => setDoc(e.target.value)}>{DOCS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select><input type="file" accept="application/pdf,image/*" data-testid="emp-doc-file" onChange={(e) => e.target.files[0] && upload("/social/files", e.target.files[0]).then((r) => setF({ ...v, documents: [...(v.documents || []), { kind: doc, label: `${DOCS.find((x) => x[0] === doc)[1]} — ${r.data.filename}`, file_id: r.data.file_id, period: "" }] })).catch((x) => toast.error(errMsg(x)))} /></div>}</div>
      </div>
      {d.leave ? <p className="text-sm" data-testid="emp-leave">Congés : {d.leave.remaining} j restants (N-1 : {d.leave.n1_remaining}, N : {d.leave.n_remaining}) · provision estimée {eur(d.leave_provision)}</p> : <p className="text-sm text-muted-foreground">CDDU : congés gérés par la caisse Congés Spectacles.</p>}
      <div className="eyebrow">Bulletins archivés</div>
      <T testid="emp-payslips" cols={[["Mois", "period"], ["Brut", (r) => eur(r.gross)], ["Net", (r) => eur(r.net_pay)], ["Coût employeur", (r) => eur(r.employer_cost_total)], ["PDF", (r) => (r.file_id ? <button className="underline" onClick={() => openFile(r.file_id)}>Ouvrir</button> : "—")]]} rows={d.payslips} empty="Aucun bulletin importé." />
      {can && <div className="flex justify-end"><Button onClick={save} data-testid="emp-save">Enregistrer</Button></div>}
    </DialogContent></Dialog>);
}

export function PersonnelTab() {
  const [d, load] = useLoad("/social/employees");
  const [open, setOpen] = useState(null);
  const [f, setF] = useState(null);
  if (!d) return null;
  return (
    <div data-testid="social-personnel">
      <div className="mb-3 flex flex-wrap gap-2">
        {d.can_manage && <Button size="sm" onClick={() => setF({ name: "", email: "", job: "", contract_type: "cdi", staff_id: "" })} data-testid="emp-new">Nouveau salarié</Button>}
        <Button size="sm" variant="outline" onClick={() => dl("/social/register?format=pdf", "registre-du-personnel.pdf")} data-testid="register-pdf">Registre du personnel (PDF)</Button>
      </div>
      <T testid="emp-table" cols={[["Nom", (r) => <button className="font-medium underline" onClick={() => setOpen(r.team_id)} data-testid={`emp-open-${r.team_id}`}>{r.name}</button>], ["Contrat", (r) => (r.has_contract ? tl(r.contract_type) : <span className="text-amber-700">{tl(r.contract_type)} — contrat à saisir</span>)], ["Emploi", "job"], ["Entrée", "start"], ["Fin", "end"], ["Statut", (r) => STATUS[r.status] || r.status], ["Staff", (r) => (r.staff_id ? "Relié" : "—")],
        ["Alertes", (r) => (r.alerts.length ? <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-semibold text-amber-800" title={r.alerts.map((a) => a.label).join("\n")}>{r.alerts.length}</span> : "—")]]} rows={d.rows} />
      <Note>Une seule fiche par personne : c'est la fiche Salariés de la page Équipe, complétée ici. N° SS et RIB chiffrés, visibles des seuls Admin, Gérant et Comptable.</Note>
      {open && <Sheet tid={open} can={d.can_manage} onClose={() => { setOpen(null); load(); }} />}
      {f && <Dialog open onOpenChange={() => setF(null)}><DialogContent data-testid="emp-new-dialog"><DialogHeader><DialogTitle>Nouveau salarié</DialogTitle><DialogDescription>Depuis une fiche Staff (intermittent) ou en saisie libre.</DialogDescription></DialogHeader>
        <F label="Depuis une fiche Staff"><Pick f={f} setF={setF} k="staff_id" blank="— Saisie libre —" opts={d.staff.map((s) => [s.id, s.name])} tid="emp-new-staff" /></F>
        <F label="Nom"><In f={f} setF={setF} k="name" tid="emp-new-name" /></F><F label="E-mail"><In f={f} setF={setF} k="email" type="email" /></F><F label="Emploi"><In f={f} setF={setF} k="job" /></F>
        {!f.staff_id && <F label="Type de contrat"><Pick f={f} setF={setF} k="contract_type" opts={TYPES.filter((t) => t[0] !== "extra")} /></F>}
        <Button onClick={() => run(api.post("/social/employees", f), "Fiche créée", (r) => { setF(null); load(); setOpen(r.team_id); })} data-testid="emp-new-save">Créer</Button></DialogContent></Dialog>}
    </div>);
}

const C0 = { team_id: "", type: "cdi", annex: "", cdd_reason: "", start: "", end: "", min_duration: "", renewals: 0, trial_end: "", trial_renewed: false, job: "", classification: "", full_time: true, weekly_hours: 35, workplace: "", pay_basis: "monthly", base_pay: 0, quantity: 1, fixed_items: [], clauses: "", mission_ids: [], signed_at: "", signed_file_id: "", dpae_done_at: "", dpae_ref: "", end_docs: {} };

export function ContratsTab() {
  const [d, load] = useLoad("/social/contracts");
  const [f, setF] = useState(null);
  const [am, setAm] = useState(null);
  const [ms, setMs] = useState(null);
  if (!d) return null;
  const save = () => run(f.id ? api.put(`/social/contracts/${f.id}`, { ...C0, ...f }) : api.post("/social/contracts", f), "Contrat enregistré", () => { setF(null); load(); });
  const fixed = f?.fixed_items || [];
  return (
    <div data-testid="social-contrats">
      <div className="mb-3 space-y-1">{d.alerts.map((a, i) => <Alert key={i} a={a} />)}</div>
      {d.can_manage && <div className="mb-3 flex gap-2"><Button size="sm" onClick={() => setF({ ...C0 })} data-testid="contract-new">Nouveau contrat</Button><Button size="sm" variant="outline" onClick={() => setMs({ mission_ids: [], mode: "per_mission", annex: "8" })} data-testid="contract-from-missions">CDDU depuis des missions Staff</Button></div>}
      <T testid="contract-table" cols={[["Salarié", "name"], ["Type", (r) => tl(r.type) + (r.annex ? ` · annexe ${r.annex}` : "")], ["Version", (r) => (r.version > 1 ? `Avenant ${r.version - 1}` : "Initial") + (r.current ? " · en vigueur" : "")], ["Effet", (r) => r.effective_from || r.start], ["Fin", "end"], ["Essai", "trial_end"],
        ["Base", (r) => `${r.base_pay} € / ${{ monthly: "mois", hourly: "h", cachet: "cachet" }[r.pay_basis]}`], ["DPAE", (r) => r.dpae_done_at || <span className="text-red-600">à faire</span>], ["Signé", (r) => r.signed_at || <span className="text-amber-700">non</span>],
        ["", (r) => <span className="flex gap-2 whitespace-nowrap"><button className="underline" onClick={() => dl(`/social/contracts/${r.id}/pdf`, "contrat.pdf")} data-testid={`contract-pdf-${r.id}`}>PDF</button>{d.can_manage && <><button className="underline" onClick={() => setF({ ...C0, ...r })}>Modifier</button>{r.type !== "cddu" && r.current && <button className="underline" onClick={() => setAm({ id: r.id, effective_from: "", reason: "", base_pay: r.base_pay })} data-testid={`contract-amend-${r.id}`}>Avenant</button>}</>}</span>]]} rows={d.rows} />
      <Note>Signature électronique : Yousign non configuré pour l'instant. Téléchargez le PDF, faites-le signer puis déposez l'exemplaire signé dans le contrat (« Modifier »).</Note>
      {f && <Dialog open onOpenChange={() => setF(null)}><DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto" data-testid="contract-dialog"><DialogHeader><DialogTitle>{f.id ? "Modifier le contrat" : "Nouveau contrat"}</DialogTitle><DialogDescription>CCN du spectacle vivant privé (IDCC 3090).</DialogDescription></DialogHeader>
        <div className="grid grid-cols-3 gap-3">
          <F label="Salarié"><Pick f={f} setF={setF} k="team_id" blank="— Choisir —" opts={d.employees.map((e) => [e.team_id, e.name])} tid="contract-employee" /></F>
          <F label="Type"><Pick f={f} setF={setF} k="type" opts={TYPES} tid="contract-type" /></F>
          {f.type === "cddu" ? <F label="Annexe"><Pick f={f} setF={setF} k="annex" blank="—" opts={[["8", "8 — technicien"], ["10", "10 — artiste"]]} /></F> : <F label="Emploi"><In f={f} setF={setF} k="job" /></F>}
          <F label="Début"><In f={f} setF={setF} k="start" type="date" tid="contract-start" /></F><F label="Fin (terme précis)"><In f={f} setF={setF} k="end" type="date" tid="contract-end" /></F><F label="ou durée minimale"><In f={f} setF={setF} k="min_duration" /></F>
          {f.type === "cdd" && <><F label="Motif du CDD" className="col-span-2"><In f={f} setF={setF} k="cdd_reason" tid="contract-reason" /></F><F label="Renouvellements"><In f={f} setF={setF} k="renewals" type="number" /></F></>}
          <F label="Fin de période d'essai"><In f={f} setF={setF} k="trial_end" type="date" /></F><F label="Classification CCN (filière, catégorie, échelon)" className="col-span-2"><In f={f} setF={setF} k="classification" /></F>
          <F label="Heures / semaine"><In f={f} setF={setF} k="weekly_hours" type="number" /></F><F label="Lieu de travail" className="col-span-2"><In f={f} setF={setF} k="workplace" /></F>
          <F label="Base de rémunération"><Pick f={f} setF={setF} k="pay_basis" opts={[["monthly", "Mensuel"], ["hourly", "Horaire"], ["cachet", "Cachet"]]} /></F><F label="Salaire de base brut (€)"><In f={f} setF={setF} k="base_pay" type="number" tid="contract-base" /></F>{f.type === "cddu" && <F label="Nombre d'heures / de cachets"><In f={f} setF={setF} k="quantity" type="number" /></F>}
          <div className="col-span-3"><div className="eyebrow mb-1">Éléments fixes (primes contractuelles, avantages en nature, véhicule)</div>{fixed.map((x, i) => <div key={i} className="mb-1 flex gap-2"><input className={inp} value={x.label} placeholder="Intitulé" onChange={(e) => setF({ ...f, fixed_items: fixed.map((y, j) => (j === i ? { ...y, label: e.target.value } : y)) })} /><input className={inp} type="number" value={x.amount} onChange={(e) => setF({ ...f, fixed_items: fixed.map((y, j) => (j === i ? { ...y, amount: Number(e.target.value) } : y)) })} /><button onClick={() => setF({ ...f, fixed_items: fixed.filter((_, j) => j !== i) })}>×</button></div>)}<button className="text-sm underline" onClick={() => setF({ ...f, fixed_items: [...fixed, { label: "", amount: 0 }] })}>+ Élément</button></div>
          <F label="Clauses (mobilité, exclusivité…)" className="col-span-3"><textarea className="min-h-16 rounded-lg border border-border bg-card p-2 text-sm" value={f.clauses} onChange={(e) => setF({ ...f, clauses: e.target.value })} /></F>
          <F label="DPAE faite le"><In f={f} setF={setF} k="dpae_done_at" type="date" tid="contract-dpae" /></F><F label="N° d'accusé DPAE"><In f={f} setF={setF} k="dpae_ref" /></F><F label="Contrat signé le"><In f={f} setF={setF} k="signed_at" type="date" /></F>
          <F label={`Exemplaire signé${f.signed_file_id ? " (déposé)" : ""}`} className="col-span-3"><input type="file" accept="application/pdf" onChange={(e) => e.target.files[0] && upload("/social/files", e.target.files[0]).then((r) => setF({ ...f, signed_file_id: r.data.file_id })).catch((x) => toast.error(errMsg(x)))} /></F>
          {f.end && <div className="col-span-3 flex flex-wrap gap-4 text-sm">{[["attestation_ft", "Attestation France Travail"], ["certificat", "Certificat de travail"], ["solde", "Solde de tout compte"], ["indemnite", "Indemnité de fin de contrat versée (si due)"]].map(([k, l]) => <label key={k} className="flex items-center gap-1"><input type="checkbox" checked={!!f.end_docs?.[k]} onChange={(e) => setF({ ...f, end_docs: { ...f.end_docs, [k]: e.target.checked } })} />{l}</label>)}</div>}
        </div><div className="flex justify-end"><Button onClick={save} data-testid="contract-save">Enregistrer</Button></div></DialogContent></Dialog>}
      {am && <Dialog open onOpenChange={() => setAm(null)}><DialogContent data-testid="amend-dialog"><DialogHeader><DialogTitle>Avenant</DialogTitle><DialogDescription>Crée une nouvelle version datée ; l'historique reste consultable et le prévisionnel applique chaque version à sa date d'effet.</DialogDescription></DialogHeader>
        <F label="Date d'effet"><In f={am} setF={setAm} k="effective_from" type="date" tid="amend-date" /></F><F label="Nouveau salaire de base (€)"><In f={am} setF={setAm} k="base_pay" type="number" tid="amend-base" /></F><F label="Heures / semaine (vide = inchangé)"><In f={am} setF={setAm} k="weekly_hours" type="number" /></F><F label="Nouvel emploi (vide = inchangé)"><In f={am} setF={setAm} k="job" /></F>
        <F label="Passage en"><Pick f={am} setF={setAm} k="type" blank="Type inchangé" opts={[["cdi", "CDI"]]} /></F><F label="Motif"><In f={am} setF={setAm} k="reason" /></F>
        <Button onClick={() => run(api.post(`/social/contracts/${am.id}/amend`, Object.fromEntries(Object.entries(am).filter(([k, v]) => k !== "id" && v !== "" && v !== undefined))), "Avenant créé", () => { setAm(null); load(); })} data-testid="amend-save">Créer l'avenant</Button></DialogContent></Dialog>}
      {ms && <Dialog open onOpenChange={() => setMs(null)}><DialogContent data-testid="missions-dialog"><DialogHeader><DialogTitle>CDDU depuis des missions Staff</DialogTitle><DialogDescription>Missions confirmées d'un même intermittent, sans contrat.</DialogDescription></DialogHeader>
        <div className="max-h-60 space-y-1 overflow-y-auto text-sm">{d.missions.length === 0 && "Aucune mission confirmée sans contrat."}{d.missions.map((m) => <label key={m.id} className="flex gap-2"><input type="checkbox" checked={ms.mission_ids.includes(m.id)} onChange={(e) => setMs({ ...ms, mission_ids: e.target.checked ? [...ms.mission_ids, m.id] : ms.mission_ids.filter((x) => x !== m.id) })} />{m.label}</label>)}</div>
        <F label="Contrat"><Pick f={ms} setF={setMs} k="mode" opts={[["per_mission", "Un contrat par mission"], ["multi", "Un contrat multi-dates"]]} /></F><F label="Annexe"><Pick f={ms} setF={setMs} k="annex" opts={[["8", "8 — technicien"], ["10", "10 — artiste"]]} /></F>
        <Button disabled={!ms.mission_ids.length} onClick={() => run(api.post("/social/contracts/from-missions", ms), "Contrat(s) créé(s)", () => { setMs(null); load(); })} data-testid="missions-save">Générer</Button></DialogContent></Dialog>}
    </div>);
}

export function RemunerationsTab() {
  const [d, load] = useLoad("/social/pay");
  const [sim, setSim] = useState({ amount: 2000, kind: "gross", type: "cdi" });
  const [res, setRes] = useState(null);
  const [rv, setRv] = useState(null);
  const [hist, setHist] = useState(null);
  if (!d) return null;
  return (
    <div data-testid="social-remunerations">
      <T testid="pay-table" cols={[["Salarié", (r) => <button className="underline" onClick={() => setHist(r)}>{r.name}</button>], ["Contrat", (r) => tl(r.type)], ["Base", (r) => `${r.base_pay} €${r.pay_basis === "hourly" ? " / h" : r.pay_basis === "cachet" ? " / cachet" : ""}`], ["Fixes", (r) => eur(r.fixed)], ["Variables moy. 3 mois", (r) => eur(r.var_3m)], ["12 mois", (r) => eur(r.var_12m)],
        ["Coefficient", (r) => <span data-testid={`pay-coef-${r.team_id}`}>{r.coef} <span className={`rounded px-1 text-[11px] ${r.coef_source === "réel" ? "bg-emerald-500/15 text-emerald-700" : "bg-secondary"}`}>{r.coef_source}</span></span>], ["Coût employeur / mois", (r) => eur(r.cost_month)], ["/ an", (r) => eur(r.cost_year)], ["Coût horaire chargé", (r) => `${r.hourly_cost} €`], ["Dernier réel", (r) => (r.real_cost ? `${eur(r.real_cost)} (${r.real_period})` : "—")],
        ["", (r) => d.can_manage && r.type !== "cddu" && <button className="underline" onClick={() => setRv({ team_id: r.team_id, effective_date: "", new_base: r.base_pay, reason: "" })} data-testid={`pay-revise-${r.team_id}`}>Réviser</button>]]} rows={d.rows} />
      <p className="mt-2 text-sm">Coût employeur mensuel estimé : <b data-testid="pay-total">{eur(d.total_month)}</b></p>
      <div className="card-soft mt-4 p-4" data-testid="pay-simulator"><div className="eyebrow mb-2">Simulation indicative brut ↔ net ↔ coût employeur</div>
        <div className="flex flex-wrap items-end gap-2"><F label="Montant (€)"><In f={sim} setF={setSim} k="amount" type="number" tid="sim-amount" /></F><F label="Ce montant est"><Pick f={sim} setF={setSim} k="kind" opts={[["gross", "un brut"], ["net", "un net"], ["cost", "un coût employeur"]]} /></F><F label="Contrat"><Pick f={sim} setF={setSim} k="type" opts={TYPES} /></F>
          <Button size="sm" onClick={() => api.get("/social/simulate", { params: sim }).then((r) => setRes(r.data)).catch((e) => toast.error(errMsg(e)))} data-testid="sim-run">Simuler</Button>
          {res && <span className="text-sm" data-testid="sim-result">Brut {eur(res.gross)} · Net ≈ {eur(res.net)} · Coût employeur ≈ {eur(res.cost)} (coef. {res.coef})</span>}</div></div>
      <Note>{d.note} Le coefficient part du paramètre par type de contrat puis se recale sur les 3 derniers bulletins réels importés.</Note>
      {rv && <Dialog open onOpenChange={() => setRv(null)}><DialogContent data-testid="revision-dialog"><DialogHeader><DialogTitle>Révision salariale</DialogTitle><DialogDescription>Planifiée à une date future ; son effet sur le prévisionnel s'affiche à l'enregistrement.</DialogDescription></DialogHeader>
        <F label="Date d'effet"><In f={rv} setF={setRv} k="effective_date" type="date" tid="revision-date" /></F><F label="Nouveau salaire de base (€)"><In f={rv} setF={setRv} k="new_base" type="number" tid="revision-base" /></F><F label="Motif"><In f={rv} setF={setRv} k="reason" /></F>
        <Button onClick={() => api.post("/social/revisions", rv).then((r) => { toast.success(`Révision planifiée : ${eur(r.data.forecast_effect_12m)} de plus sur 12 mois`, { duration: 9000 }); setRv(null); load(); }).catch((e) => toast.error(errMsg(e)))} data-testid="revision-save">Planifier</Button></DialogContent></Dialog>}
      {hist && <Dialog open onOpenChange={() => setHist(null)}><DialogContent><DialogHeader><DialogTitle>Historique — {hist.name}</DialogTitle><DialogDescription>Hausses et versions de contrat.</DialogDescription></DialogHeader>
        <T testid="pay-history" cols={[["Date", "date"], ["Base", (r) => `${r.base} €`], ["Origine", "label"], ["", (r) => r.id && d.can_manage && <button className="underline" onClick={() => run(api.delete(`/social/revisions/${r.id}`), "Révision supprimée", () => { setHist(null); load(); })}>Supprimer</button>]]} rows={hist.history} /></DialogContent></Dialog>}
    </div>);
}
