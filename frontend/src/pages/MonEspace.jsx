import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { F, In, Pick, T, dl, eur, today } from "@/components/social/kit";

const ST = { requested: "En attente", approved: "Validée", refused: "Refusée", cancelled: "Annulée" };

export function MySocial({ base = "/my-social", portal = false }) {
  const [d, setD] = useState(null);
  const load = useCallback(() => api.get(base).then((r) => setD(r.data)).catch(() => setD(false)), [base]);
  useEffect(() => { load(); }, [load]);
  const [f, setF] = useState({ type: "cp", start: today(), end: today(), half_days: 0 });
  const [c, setC] = useState({ phone: "", address: "", iban: "" });
  if (d === null) return null;
  if (d === false) return portal ? null : <p className="text-sm text-muted-foreground" data-testid="my-social-none">Aucune fiche salarié n'est reliée à votre compte. Demandez à un gérant de relier votre adresse e-mail à votre fiche dans Équipe.</p>;
  const file = (fid, name) => dl(`${base}/files/${fid}`, name);
  const ask = () => api.post(`${base}/absences`, f).then((r) => { toast.success(`Demande envoyée : ${r.data.absence.days} jour(s). Solde après demande : ${r.data.balance_after ?? "—"} j`, { duration: 9000 }); load(); }).catch((e) => toast.error(errMsg(e)));
  return (
    <div className="space-y-5" data-testid="my-social">
      {d.notifications.slice(0, 3).map((n) => <div key={n.id} className="rounded-lg bg-blue-500/10 px-3 py-2 text-sm" data-testid="my-notification">{n.text}</div>)}
      <section><div className="eyebrow mb-1">Mes contrats et avenants</div>
        <T testid="my-contracts" cols={[["Type", (r) => r.type.toUpperCase() + (r.version > 1 ? ` — avenant ${r.version - 1}` : "")], ["Effet", (r) => r.effective_from || r.start], ["Fin", "end"], ["Emploi", "job"], ["", (r) => <button className="underline" onClick={() => dl(`${base}/contracts/${r.id}/pdf`, "contrat.pdf")} data-testid={`my-contract-${r.id}`}>PDF</button>]]} rows={d.contracts} empty="Aucun contrat." /></section>
      <section><div className="eyebrow mb-1">Mes bulletins</div>
        <T testid="my-payslips" cols={[["Mois", "period"], ["Brut", (r) => eur(r.gross)], ["Net à payer", (r) => eur(r.net_pay)], ["", (r) => (r.file_id ? <button className="underline" onClick={() => file(r.file_id, `bulletin-${r.period}.pdf`)}>Télécharger</button> : "—")]]} rows={d.payslips} empty="Aucun bulletin publié." /></section>
      <section><div className="eyebrow mb-1">Mes documents</div>{(d.file.documents || []).length ? d.file.documents.map((x, i) => <div key={i}><button className="text-sm underline" onClick={() => file(x.file_id, x.label || "document")}>{x.label || x.kind}</button></div>) : <p className="text-sm text-muted-foreground">Aucun document.</p>}</section>
      <section><div className="eyebrow mb-1">Mes congés</div>
        {d.leave ? <p className="text-sm" data-testid="my-leave">Solde : <b>{d.leave.remaining} j</b> (N-1 : {d.leave.n1_remaining} · N : {d.leave.n_remaining}) · en attente : {d.leave.pending} j · jours {d.leave.mode}</p> : <p className="text-sm text-muted-foreground" data-testid="my-leave-cddu">{d.cddu_note || "Pas de compteur de congés."}</p>}
        {d.leave && !portal && <div className="mt-2 flex flex-wrap items-end gap-2"><F label="Type"><Pick f={f} setF={setF} k="type" opts={Object.entries(d.types)} tid="my-leave-type" /></F><F label="Du"><In f={f} setF={setF} k="start" type="date" tid="my-leave-start" /></F><F label="Au"><In f={f} setF={setF} k="end" type="date" tid="my-leave-end" /></F><F label="Demi-journées en moins"><In f={f} setF={setF} k="half_days" type="number" /></F><Button size="sm" onClick={ask} data-testid="my-leave-ask">Demander</Button></div>}
        <div className="mt-2"><T testid="my-absences" cols={[["Type", (r) => d.types[r.type] || "Absence"], ["Du", "start"], ["Au", "end"], ["Jours", "days"], ["Statut", (r) => ST[r.status]], ["", (r) => r.status === "requested" && !portal && <button className="underline" onClick={() => api.delete(`${base}/absences/${r.id}`).then(load).catch((e) => toast.error(errMsg(e)))} data-testid={`my-cancel-${r.id}`}>Annuler</button>]]} rows={d.absences} empty="Aucune demande." /></div></section>
      <section><div className="eyebrow mb-1">Mes heures</div>{d.hours.map((h) => <p key={h.period} className="text-sm">{h.period} : <b>{h.total} h</b> (dont {h.overtime_hours} h supplémentaires, {h.night} h de nuit)</p>)}{!portal && <Link className="text-sm underline" to="/notes-de-frais">Mes notes de frais</Link>}</section>
      {!portal && <section><div className="eyebrow mb-1">Mettre à jour mes coordonnées ou mon RIB (validation par un gérant)</div>
        {d.changes[0]?.status === "pending" && <p className="text-sm text-amber-700" data-testid="my-change-pending">Une demande est en attente de validation.</p>}
        <div className="flex flex-wrap items-end gap-2"><F label="Téléphone"><In f={c} setF={setC} k="phone" /></F><F label="Adresse"><In f={c} setF={setC} k="address" /></F><F label={`Nouvel IBAN${d.iban_last4 ? ` (actuel …${d.iban_last4})` : ""}`}><In f={c} setF={setC} k="iban" tid="my-iban" /></F>
          <Button size="sm" variant="outline" onClick={() => api.put(`${base}/profile-change`, c).then((r) => { toast.success(r.data.message); setC({ phone: "", address: "", iban: "" }); load(); }).catch((e) => toast.error(errMsg(e)))} data-testid="my-change-send">Envoyer la demande</Button></div></section>}
    </div>);
}

export default function MonEspace() {
  return <div data-testid="mon-espace-page"><PageHeader title="Mon espace salarié" subtitle="Vos contrats, bulletins, congés et heures. Vous seul voyez ces informations, avec la direction." /><MySocial /></div>;
}
