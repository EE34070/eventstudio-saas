import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, errMsg } from "@/lib/api";
import { Alert, F, In, Note, Pick, T, dl, eur, inp, run, sel, today, upload, useLoad } from "@/components/social/kit";

const Month = ({ v, set, tid }) => <input type="month" className={sel} value={v} onChange={(e) => e.target.value && set(e.target.value)} data-testid={tid} />;
const prevMonth = () => { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - 1); return d.toISOString().slice(0, 7); };

export function TempsTab() {
  const [p, setP] = useState(today().slice(0, 7));
  const [d, load] = useLoad(`/social/time?period=${p}`);
  const [e, setE] = useState(null);
  const [v, setV] = useState(null);
  if (!d) return null;
  const open = d.status === "open" && d.can_manage;
  return (
    <div data-testid="social-temps">
      <div className="mb-3 flex flex-wrap items-center gap-2"><Month v={p} set={setP} tid="time-period" />
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${d.status === "open" ? "bg-amber-500/15 text-amber-800" : "bg-emerald-500/15 text-emerald-700"}`} data-testid="time-status">{d.status === "open" ? "Variables ouvertes" : "Variables clôturées"}</span>
        {open && <><Button size="sm" variant="outline" onClick={() => setE({ team_id: "", date: `${p}-01`, normal_h: 7, night_h: 0, sunday_h: 0, holiday_h: 0 })} data-testid="time-add">Saisir des heures</Button>
          <label className="cursor-pointer text-sm underline">Importer un CSV<input type="file" accept=".csv,.xlsx" className="hidden" data-testid="time-import" onChange={(x) => x.target.files[0] && upload("/social/time-entries/import", x.target.files[0]).then((r) => { toast.success(`${r.data.imported} ligne(s) importée(s)${r.data.skipped_lines.length ? `, lignes ignorées : ${r.data.skipped_lines.join(", ")}` : ""}`); load(); }).catch((er) => toast.error(errMsg(er)))} /></label>
          <Button size="sm" variant="outline" onClick={() => setV({ team_id: "", period: p, kind: "prime_evenement", amount: 0, quantity: 1, event_id: "", label: "" })} data-testid="var-add">Ajouter une variable</Button>
          <Button size="sm" onClick={() => window.confirm(`Clôturer les variables de ${p} ? La période est verrouillée et la pré-paie est préparée (aucun e-mail n'est envoyé).`) && run(api.post(`/social/periods/${p}/close`), "Variables clôturées : pré-paie prête dans « Paie du mois »", load)} data-testid="period-close">Clôturer les variables</Button></>}
      </div>
      <T testid="time-table" empty="Aucun salarié sous contrat sur ce mois." cols={[["Salarié", "name"], ["Contractuel", (r) => `${r.contractual} h`], ["Réalisé", (r) => <b>{r.total} h</b>], ["Normales", "normal"], ["Heures sup.", (r) => r.overtime.filter((o) => o.hours).map((o) => `${o.hours} h à +${o.pct} %`).join(", ") || "—"], ["Nuit", "night"], ["Dim.", "sunday"], ["Férié", "holiday"],
        ["Contingent", (r) => <span className={r.contingent_alert ? "font-semibold text-red-600" : ""}>{r.contingent_used} / {r.contingent} h</span>], ["Source", (r) => [...new Set(r.rows.map((x) => ({ timesheet: "Feuilles de temps Staff", manual: "Saisie", import: "Import" }[x.source])))].join(", ") || "—"],
        ["Variables", (r) => r.variables.map((x) => <div key={x.id} className="whitespace-nowrap">{d.kinds[x.kind]} : {eur(x.amount)}{x.event_id ? " · événement" : ""}{open && <button className="ml-1 text-red-600" onClick={() => run(api.delete(`/social/variables/${x.id}`), "Supprimé", load)}>×</button>}</div>)],
        ["Absences", (r) => r.absences.map((a) => `${a.start}→${a.end}`).join(", ") || "—"], ["Contrôles", (r) => (r.warnings.length ? <span className="text-amber-700" title={r.warnings.join("\n")}>{r.warnings.length} alerte(s)</span> : "—")]]} rows={d.rows} />
      <Note>Les heures validées des intermittents viennent des feuilles de temps Staff, sans ressaisie. Contrôles non bloquants (durées maximales, repos). CSV : nom ou e-mail ; date ; heures ; nuit ; dimanche ; férié.</Note>
      {e && <Dialog open onOpenChange={() => setE(null)}><DialogContent data-testid="time-dialog"><DialogHeader><DialogTitle>Saisie d'heures</DialogTitle><DialogDescription>Pour les salariés hors feuilles de temps Staff.</DialogDescription></DialogHeader>
        <F label="Salarié"><Pick f={e} setF={setE} k="team_id" blank="— Choisir —" opts={d.rows.map((r) => [r.team_id, r.name])} tid="time-employee" /></F><F label="Date"><In f={e} setF={setE} k="date" type="date" /></F>
        <div className="grid grid-cols-4 gap-2"><F label="Heures"><In f={e} setF={setE} k="normal_h" type="number" tid="time-hours" /></F><F label="dont nuit"><In f={e} setF={setE} k="night_h" type="number" /></F><F label="dont dimanche"><In f={e} setF={setE} k="sunday_h" type="number" /></F><F label="dont férié"><In f={e} setF={setE} k="holiday_h" type="number" /></F></div>
        <Button onClick={() => run(api.post("/social/time-entries", e), "Heures enregistrées", () => { setE(null); load(); })} data-testid="time-save">Enregistrer</Button></DialogContent></Dialog>}
      {v && <Dialog open onOpenChange={() => setV(null)}><DialogContent data-testid="var-dialog"><DialogHeader><DialogTitle>Variable du mois</DialogTitle><DialogDescription>Une prime rattachée à un événement apparaît, chargée, dans sa rentabilité.</DialogDescription></DialogHeader>
        <F label="Salarié"><Pick f={v} setF={setV} k="team_id" blank="— Choisir —" opts={d.rows.map((r) => [r.team_id, r.name])} tid="var-employee" /></F><F label="Type"><Pick f={v} setF={setV} k="kind" opts={Object.entries(d.kinds)} tid="var-kind" /></F>
        <F label="Montant (€)"><In f={v} setF={setV} k="amount" type="number" tid="var-amount" /></F><F label="Événement (facultatif)"><Pick f={v} setF={setV} k="event_id" blank="— Aucun —" opts={d.events.map((x) => [x.id, `${x.start.slice(0, 10)} · ${x.title}`])} /></F><F label="Libellé"><In f={v} setF={setV} k="label" /></F>
        <Button onClick={() => run(api.post("/social/variables", v), "Variable enregistrée", () => { setV(null); load(); })} data-testid="var-save">Enregistrer</Button></DialogContent></Dialog>}
    </div>);
}

const ST = { requested: "En attente", approved: "Validée", refused: "Refusée", cancelled: "Annulée" };

export function CongesTab() {
  const [d, load] = useLoad("/social/absences");
  const [f, setF] = useState(null);
  if (!d) return null;
  const act = (a, action) => api.post(`/social/absences/${a.id}/${action}`, { reason: action === "refuse" ? window.prompt("Motif du refus") || "" : "" }).then((r) => { toast.success(ST[r.data.status]); if (r.data.overlaps?.length) toast.warning(`Chevauchement : ${r.data.overlaps.map((o) => `${o.label} (${o.date})`).join(", ")}`, { duration: 12000 }); load(); }).catch((e) => toast.error(errMsg(e)));
  const now = today();
  return (
    <div data-testid="social-conges">
      <div className="mb-3 flex gap-2">{d.can_manage && <Button size="sm" onClick={() => setF({ team_id: "", type: "maladie", start: now, end: now, half_days: 0, attachment_id: "" })} data-testid="absence-new">Saisir une absence</Button>}<Button size="sm" variant="outline" onClick={() => dl("/social/absences?format=csv", "absences.csv")} data-testid="absence-export">Exporter</Button></div>
      <div className="eyebrow mb-1">Compteurs de congés payés</div>
      <T testid="leave-balances" cols={[["Salarié", "name"], ["Période de référence", "period"], ["Acquis N-1", "n1_acquired"], ["Acquis N", "n_acquired"], ["Pris", "taken"], ["En attente", "pending"], ["Solde", (r) => <b>{r.remaining} j</b>], ["Provision", (r) => eur(r.provision)]]} rows={d.balances} empty="Aucun CDI / CDD avec compteur." />
      <p className="mt-2 text-sm">Provision congés payés estimée : <b data-testid="leave-provision">{eur(d.provision_total)}</b></p><Note>{d.note} {d.cddu_note}</Note>
      <div className="eyebrow mb-1 mt-5">Demandes et absences</div>
      <T testid="absence-table" cols={[["Salarié", "name"], ["Type", "type_label"], ["Du", "start"], ["Au", "end"], ["Jours", "days"], ["Statut", (r) => <span data-testid={`absence-status-${r.id}`}>{ST[r.status]}{r.subrogation ? " · subrogation" : ""}</span>],
        ["Chevauchement", (r) => (r.overlaps.length ? <span className="font-semibold text-red-600" data-testid={`absence-overlap-${r.id}`}>{r.overlaps.map((o) => `${o.label} (${o.date})`).join(", ")}</span> : "—")],
        ["", (r) => d.can_manage && <span className="flex gap-2">{r.status === "requested" && <><button className="underline" onClick={() => act(r, "approve")} data-testid={`absence-approve-${r.id}`}>Valider</button><button className="underline" onClick={() => act(r, "refuse")} data-testid={`absence-refuse-${r.id}`}>Refuser</button></>}{r.status === "approved" && r.end >= now && <button className="underline" onClick={() => act(r, "cancel")}>Annuler</button>}</span>]]} rows={d.rows} />
      <div className="eyebrow mb-1 mt-5">Calendrier de l'équipe (8 semaines)</div>
      <div className="overflow-x-auto" data-testid="absence-calendar"><table className="text-[10px]"><tbody>{d.employees.map((e) => <tr key={e.team_id}><td className="whitespace-nowrap pr-2 text-xs">{e.name}</td>{Array.from({ length: 56 }, (_, i) => { const day = new Date(Date.now() + i * 864e5).toISOString().slice(0, 10); const a = d.rows.find((x) => x.team_id === e.team_id && ["approved", "requested"].includes(x.status) && x.start <= day && x.end >= day); return <td key={i} title={`${day}${a ? ` · ${a.type_label}` : ""}`} className={`h-4 w-3 border border-background ${a ? (a.status === "approved" ? "bg-primary" : "bg-amber-400") : "bg-secondary"}`} />; })}</tr>)}</tbody></table></div>
      {f && <Dialog open onOpenChange={() => setF(null)}><DialogContent data-testid="absence-dialog"><DialogHeader><DialogTitle>Saisir une absence</DialogTitle><DialogDescription>Justificatif en pièce jointe ; le motif médical n'est jamais saisi.</DialogDescription></DialogHeader>
        <F label="Salarié"><Pick f={f} setF={setF} k="team_id" blank="— Choisir —" opts={d.employees.map((e) => [e.team_id, e.name])} tid="absence-employee" /></F><F label="Type"><Pick f={f} setF={setF} k="type" opts={Object.entries(d.types)} tid="absence-type" /></F>
        <div className="grid grid-cols-3 gap-2"><F label="Du"><In f={f} setF={setF} k="start" type="date" /></F><F label="Au"><In f={f} setF={setF} k="end" type="date" /></F><F label="Demi-journées en moins"><In f={f} setF={setF} k="half_days" type="number" /></F></div>
        <F label={`Justificatif${f.attachment_id ? " (déposé)" : ""}`}><input type="file" accept="application/pdf,image/*" onChange={(e) => e.target.files[0] && upload("/social/files", e.target.files[0]).then((r) => setF({ ...f, attachment_id: r.data.file_id })).catch((x) => toast.error(errMsg(x)))} /></F>
        <Button onClick={() => api.post("/social/absences", f).then((r) => { toast.success("Absence enregistrée"); if (r.data.overlaps?.length) toast.warning(`Chevauchement : ${r.data.overlaps.map((o) => o.label).join(", ")}`, { duration: 12000 }); setF(null); load(); }).catch((e) => toast.error(errMsg(e)))} data-testid="absence-save">Enregistrer</Button></DialogContent></Dialog>}
    </div>);
}

const NUMS = [["gross", "Brut"], ["employee_contrib", "Cotisations salariales"], ["employer_contrib", "Cotisations patronales"], ["net_pay", "Net à payer"], ["net_taxable", "Net imposable"], ["pas", "Prélèvement à la source"], ["hours", "Heures"], ["employer_cost_total", "Coût employeur total"]];

function LineDialog({ l, emps, onClose, onDone }) {
  const [f, setF] = useState({ team_id: l.team_id || "", ...Object.fromEntries(NUMS.map(([k]) => [k, l[k] ?? 0])) });
  const [url, setUrl] = useState("");
  useEffect(() => { if (l.file_id) api.get(`/files/${l.file_id}/link`).then((r) => setUrl(r.data.url?.startsWith("http") ? r.data.url : process.env.REACT_APP_BACKEND_URL + r.data.url)).catch(() => {}); }, [l.file_id]);
  const save = (validate) => api.put(`/social/payroll/lines/${l.id}`, f).then(() => (validate ? api.post(`/social/payroll/lines/${l.id}/validate`) : null)).then((r) => { toast.success(validate ? `Bulletin validé — coefficient ${r.data.coef.value} (${r.data.coef.source})` : "Enregistré"); onDone(); }).catch((e) => toast.error(errMsg(e)));
  return (
    <Dialog open onOpenChange={onClose}><DialogContent className="max-h-[92vh] max-w-5xl overflow-y-auto" data-testid="line-dialog"><DialogHeader><DialogTitle>Bulletin — {l.name}</DialogTitle><DialogDescription>Vérifiez chaque montant avant de valider. Les champs en orange sont douteux.</DialogDescription></DialogHeader>
      {l.warning && <Alert a={{ text: l.warning }} />}
      <div className={`grid gap-4 ${url ? "md:grid-cols-2" : ""}`}>
        <div className="space-y-2"><F label="Salarié"><Pick f={f} setF={setF} k="team_id" blank="— Rattacher —" opts={emps.map((e) => [e.team_id, e.name])} tid="line-employee" /></F>
          {NUMS.map(([k, lab]) => <F key={k} label={lab}><input type="number" className={`${inp} ${l.confidence?.[k] !== undefined && l.confidence[k] < 0.8 ? "border-orange-500 bg-orange-50" : ""}`} value={f[k]} onChange={(e) => setF({ ...f, [k]: Number(e.target.value) })} data-testid={`line-${k}`} /></F>)}
          <div className="flex gap-2"><Button variant="outline" onClick={() => save(false)} data-testid="line-save">Enregistrer</Button><Button onClick={() => save(true)} data-testid="line-validate">Valider le bulletin</Button></div></div>
        {url && <iframe title="Bulletin" src={url} className="h-[70vh] w-full rounded-lg border border-border" data-testid="line-pdf" />}
      </div></DialogContent></Dialog>);
}

export function PaieTab() {
  const [p, setP] = useState(prevMonth());
  const [d, load, setD] = useLoad(`/social/payroll?period=${p}`);
  const [dr, setDr] = useState(null);
  const [line, setLine] = useState(null);
  useEffect(() => { setDr(d?.draft || null); }, [d]);
  if (!d) return null;
  const m = d.can_manage;
  const imp = (path, file) => upload(path, file, { period: p }).then((r) => { setD(r.data); toast.success("Import en brouillon : vérifiez puis validez chaque bulletin"); if (r.data.line_id) setLine(r.data.lines.find((x) => x.id === r.data.line_id)); }).catch((e) => toast.error(errMsg(e)));
  return (
    <div data-testid="social-paie">
      <div className="mb-3 flex flex-wrap items-center gap-2"><Month v={p} set={setP} tid="payroll-period" /><span className="rounded-full bg-secondary px-3 py-1 text-xs font-semibold" data-testid="payroll-status">{{ open: "Variables ouvertes", closed: "Variables clôturées", sent: "Pré-paie envoyée" }[d.status]}{d.closed_by ? ` par ${d.closed_by}` : ""}</span>
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" disabled={!m} checked={!!d.dsn_done_at} onChange={(e) => run(api.put(`/social/periods/${p}/dsn`, { done: e.target.checked }), "Enregistré", setD)} data-testid="dsn-check" />DSN déposée par le cabinet</label></div>
      <div className="eyebrow mb-1">1. Pré-paie {d.status === "open" ? "(aperçu, non clôturée)" : ""}</div>
      <T testid="prepay-table" cols={[["Nom", "name"], ["Contrat", "type"], ["Entrée", "entry"], ["Sortie", "exit"], ["Base", (r) => eur(r.base)], ["Heures", "hours"], ["H. sup.", "overtime"], ["Primes / cachets", (r) => eur(r.bonuses)], ["Indemnités", (r) => eur(r.allowances)], ["Frais", (r) => eur(r.expenses)], ["Acomptes", (r) => eur(r.advances)], ["CP (j)", "cp_days"], ["Absences", "absences"], ["Coût prévu", (r) => eur(r.expected_cost)]]} rows={d.prepay} />
      <div className="mt-2 flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={() => dl(`/social/periods/${p}/prepay?format=csv`, `pre-paie-${p}.csv`)} data-testid="prepay-csv">CSV</Button><Button size="sm" variant="outline" onClick={() => dl(`/social/periods/${p}/prepay?format=pdf`, `pre-paie-${p}.pdf`)} data-testid="prepay-pdf">Récapitulatif PDF</Button>
        {m && d.status === "open" && <Button size="sm" onClick={() => run(api.post(`/social/periods/${p}/close`), "Variables clôturées, brouillon préparé", setD)} data-testid="payroll-close">Clôturer les variables</Button>}{m && d.status === "closed" && <Button size="sm" variant="ghost" onClick={() => run(api.post(`/social/periods/${p}/reopen`), "Période rouverte", setD)} data-testid="payroll-reopen">Rouvrir</Button>}</div>
      {dr && <div className="card-soft mt-3 space-y-2 p-4" data-testid="prepay-draft"><div className="eyebrow">Brouillon d'e-mail au cabinet — {dr.status === "sent" ? `envoyé le ${dr.sent_at?.slice(0, 10)}` : "non envoyé, à valider"}</div>
        <F label="Destinataire (adresse du cabinet, réglable dans Paramètres)"><In f={dr} setF={setDr} k="to" tid="draft-to" disabled={dr.status === "sent"} /></F><F label="Objet"><In f={dr} setF={setDr} k="subject" disabled={dr.status === "sent"} /></F>
        <F label="Message"><textarea className="min-h-28 rounded-lg border border-border bg-card p-2 text-sm" value={dr.body} disabled={dr.status === "sent"} onChange={(e) => setDr({ ...dr, body: e.target.value })} data-testid="draft-body" /></F>
        <div className="text-xs text-muted-foreground">Pièces jointes : {dr.attachments.join(", ")}</div>
        {m && dr.status === "draft" && <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => run(api.put(`/social/periods/${p}/draft`, { to: dr.to, subject: dr.subject, body: dr.body }), "Brouillon enregistré", setD)} data-testid="draft-save">Enregistrer le brouillon</Button>
          <Button size="sm" onClick={() => window.confirm(`Envoyer la pré-paie à ${dr.to} ?`) && api.put(`/social/periods/${p}/draft`, { to: dr.to, subject: dr.subject, body: dr.body }).then(() => api.post(`/social/periods/${p}/send-draft`)).then((r) => { setD(r.data); toast.success("Pré-paie envoyée"); }).catch((e) => toast.error(errMsg(e)))} data-testid="draft-send">Envoyer au cabinet</Button></div>}</div>}
      <div className="eyebrow mb-1 mt-6">2. Bulletins importés</div>
      {m && <div className="mb-2 flex flex-wrap gap-4 text-sm"><label className="cursor-pointer underline">Importer le journal de paie (CSV / Excel)<input type="file" accept=".csv,.xlsx" className="hidden" data-testid="payroll-import-csv" onChange={(e) => e.target.files[0] && imp("/social/payroll/import", e.target.files[0])} /></label>
        <label className="cursor-pointer underline">Importer un bulletin PDF (lecture par IA)<input type="file" accept="application/pdf" className="hidden" data-testid="payroll-import-pdf" onChange={(e) => e.target.files[0] && imp("/social/payroll/import-pdf", e.target.files[0])} /></label></div>}
      <T testid="payroll-lines" empty="Aucun bulletin importé pour ce mois." cols={[["Salarié", (r) => r.name || "?"], ["Brut", (r) => eur(r.gross)], ["Cot. salariales", (r) => eur(r.employee_contrib)], ["Cot. patronales", (r) => eur(r.employer_contrib)], ["Net à payer", (r) => eur(r.net_pay)], ["PAS", (r) => eur(r.pas)], ["Coût employeur", (r) => eur(r.employer_cost_total)], ["Écart / prévu", (r) => (r.variance_vs_forecast != null ? `${r.variance_vs_forecast} %` : "—")],
        ["Statut", (r) => <span className={r.status === "validated" ? "text-emerald-700" : "text-amber-700"} data-testid={`line-status-${r.id}`}>{r.status === "validated" ? "Validé" : "À valider"}</span>], ["", (r) => m && <span className="flex gap-2">{r.status === "draft" && <button className="underline" onClick={() => setLine(r)} data-testid={`line-open-${r.id}`}>Vérifier</button>}<button className="text-red-600 underline" onClick={() => window.confirm("Retirer ce bulletin ?") && run(api.delete(`/social/payroll/lines/${r.id}`), "Retiré", setD)}>Retirer</button></span>]]} rows={d.lines} />
      <div className="eyebrow mb-1 mt-6">3. Contrôles</div>
      <div className="space-y-1" data-testid="payroll-controls">{d.controls.length ? d.controls.map((c, i) => <Alert key={i} a={c} />) : <p className="text-sm text-muted-foreground">{d.lines.length ? "Aucun écart détecté." : "Les contrôles s'affichent après l'import des bulletins."}</p>}</div>
      <Note>{d.pennylane.note} La paie n'est pas calculée dans l'application : le cabinet établit les bulletins.</Note>
      {line && <LineDialog l={line} emps={d.employees} onClose={() => setLine(null)} onDone={() => { setLine(null); load(); }} />}
    </div>);
}
