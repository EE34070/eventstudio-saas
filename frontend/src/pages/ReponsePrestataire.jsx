import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import axios from "axios";
import { Loading } from "@/components/common";
import { fmtDate, fmtEur2 } from "@/lib/constants";

const BASE = `${process.env.REACT_APP_BACKEND_URL}/api/public/provider-requests`;
const CHOICES = [["available", "Disponible", "bg-emerald-600 text-white"], ["conditional", "Disponible sous conditions", "bg-amber-500 text-white"], ["unavailable", "Pas disponible", "bg-neutral-700 text-white"]];
const inp = "h-12 w-full rounded-xl border border-border bg-background px-3 text-base";
const L = ({ label, children }) => <label className="mt-4 block"><span className="mb-1.5 block text-sm font-medium">{label}</span>{children}</label>;
const Shell = ({ org, children }) => (
  <div className="mx-auto min-h-screen max-w-lg px-4 py-8" data-testid="provider-reply-page">
    <div className="mb-6 flex items-center gap-2.5"><span className="brand-mark">{(org || "E")[0]}</span><span className="font-brand text-xl">{org || "Exclusivity Events"}</span></div>
    {children}
  </div>
);

export default function ReponsePrestataire() {
  const { token } = useParams();
  const [params] = useSearchParams();
  const [d, setD] = useState(null);
  const [f, setF] = useState(null);
  const [err, setErr] = useState("");
  const [done, setDone] = useState("");
  const [busy, setBusy] = useState(false);
  const stop = params.get("stop") === "1";
  useEffect(() => {
    if (stop) return;
    axios.get(`${BASE}/${token}`).then((r) => { setD(r.data); setF({ ...r.data.reply, reply: r.data.reply.reply === "none" ? "" : r.data.reply.reply, update_defaults: false }); })
      .catch((e) => setErr(e.response?.status === 410 ? "Ce lien a expiré : la date limite de réponse est dépassée." : "Ce lien est introuvable ou n'est plus valide."));
  }, [token, stop]);

  if (stop) return (
    <Shell><div className="card-soft p-6" data-testid="unsubscribe-panel">
      {done ? <p data-testid="unsubscribe-done">C'est noté : vous ne recevrez plus de demandes de notre part.</p> : (<>
        <p className="text-base">Souhaitez-vous ne plus recevoir de demandes de notre part ?</p>
        {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
        <button className="mt-5 h-12 w-full rounded-full bg-neutral-800 text-base font-semibold text-white" disabled={busy} data-testid="unsubscribe-confirm"
          onClick={() => { setBusy(true); axios.post(`${BASE}/${token}/unsubscribe`).then(() => setDone("ok")).catch(() => setErr("Lien introuvable.")).finally(() => setBusy(false)); }}>Ne plus me solliciter</button>
      </>)}</div></Shell>
  );
  if (err) return <Shell><p className="card-soft p-6 text-base" data-testid="reply-error">{err}</p></Shell>;
  if (!d) return <Loading />;
  const en = !(d.language || "fr").startsWith("fr");
  const tt = (fr, e) => (en ? e : fr);
  const loc = en ? d.language : "fr-FR";
  const CH_EN = { available: "Available", conditional: "Available with conditions", unavailable: "Not available" };

  const num = (v) => Number(String(v).replace(",", ".")) || 0;
  const subject = f.vat_mode === "subject";
  const ht = num(f.proposed_rate) + num(f.proposed_travel_fee);
  const ttc = subject ? ht * (1 + num(f.vat_rate) / 100) : ht;
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const toggle = (k) => setF({ ...f, equipment_needed: f.equipment_needed.includes(k) ? f.equipment_needed.filter((x) => x !== k) : [...f.equipment_needed, k] });
  const submit = async () => {
    setBusy(true); setErr("");
    try {
      await axios.post(`${BASE}/${token}`, { ...f, proposed_rate: num(f.proposed_rate), proposed_travel_fee: num(f.proposed_travel_fee), vat_rate: num(f.vat_rate) });
      setDone(f.reply);
    } catch (e) { const x = e.response?.data?.detail; setErr(typeof x === "string" ? x : "Vérifiez les montants saisis."); }
    setBusy(false);
  };
  const closed = { retained: tt("Vous êtes retenu(e) pour cette prestation. Tous les détails vous ont été envoyés par e-mail.", "You have been booked for this job. All details were sent to you by e-mail."), filled: tt("Cette date est désormais pourvue. Merci pour votre réponse.", "This date has now been filled. Thank you for your reply."), cancelled: tt("Cette demande a été annulée.", "This request has been cancelled.") }[d.state];

  return (
    <Shell org={d.org_name}>
      <h1 className="text-2xl font-extrabold tracking-tight" data-testid="reply-title">{tt(`Bonjour ${d.first_name}, êtes-vous disponible ?`, `Hello ${d.first_name}, are you available?`)}</h1>
      <div className="card-soft mt-5 space-y-1.5 p-5 text-base" data-testid="reply-recap">
        <div className="text-lg font-semibold">{d.category}{d.event_type ? ` · ${d.event_type}` : ""}</div>
        <div>{new Date(`${d.date}T00:00`).toLocaleDateString(loc, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}, {tt("de", "from")} {d.start_time} {tt("à", "to")} {d.end_time}</div>
        <div>{d.city}{d.distance_km != null ? tt(` (environ ${Math.round(d.distance_km)} km de chez vous)`, ` (about ${Math.round(d.distance_km)} km from you)`) : ""}{d.guest_count ? ` · ${d.guest_count} ${tt("invités", "guests")}` : ""}</div>
        {d.brief && <p className="whitespace-pre-wrap pt-2 text-sm text-muted-foreground">{d.brief}</p>}
        <div className="pt-2 text-sm"><b>{tt("Matériel sur place :", "Equipment on site:")}</b> {[...d.onsite_equipment.map((k) => d.equipment_labels[k]), d.onsite_equipment_note].filter(Boolean).join(", ") || tt("non précisé", "not specified")}</div>
        {d.budget && <div className="text-sm"><b>{tt("Budget :", "Budget:")}</b> {d.budget}</div>}
        <div className="text-sm text-muted-foreground">{tt("Réponse attendue avant le", "Please reply before")} {new Date(d.deadline).toLocaleString(loc, { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" })}</div>
      </div>
      {closed ? <p className="card-soft mt-5 p-5 text-base font-medium" data-testid="reply-closed">{closed}</p> : done ? (
        <div className="card-soft mt-5 p-5" data-testid="reply-done"><p className="text-lg font-semibold">{tt("Merci, votre réponse est enregistrée.", "Thank you, your reply has been saved.")}</p>
          <p className="mt-1 text-sm text-muted-foreground">{done === "unavailable" ? tt("Nous avons noté votre indisponibilité.", "We have noted that you are not available.") : tt("Nous revenons vers vous rapidement.", "We will get back to you shortly.")} {tt("Vous pouvez la modifier tant que la date n'est pas pourvue.", "You can change it until the date is filled.")}</p>
          <button className="mt-4 text-sm underline" onClick={() => setDone("")} data-testid="reply-edit">{tt("Modifier ma réponse", "Change my reply")}</button></div>
      ) : (<>
        <div className="mt-5 space-y-2.5">{CHOICES.map(([k, l, cls]) => (
          <button key={k} type="button" onClick={() => setF({ ...f, reply: k })} aria-pressed={f.reply === k} data-testid={`reply-choice-${k}`}
            className={`h-14 w-full rounded-2xl text-lg font-semibold transition-opacity ${cls} ${f.reply && f.reply !== k ? "opacity-40" : ""}`}>{en ? CH_EN[k] : l}</button>))}</div>
        {f.reply && f.reply !== "unavailable" && (
          <div className="card-soft mt-5 p-5" data-testid="reply-form">
            <p className="text-sm text-muted-foreground">{tt("Pré-rempli d'après votre fiche : vérifiez et validez.", "Pre-filled from your profile: please check and confirm.")}</p>
            <L label={`${tt("Votre prix", "Your price")} (€ ${subject ? tt("HT", "excl. VAT") : "net"})`}><input className={inp} inputMode="decimal" value={f.proposed_rate} onChange={set("proposed_rate")} data-testid="reply-rate" /></L>
            <L label={`${tt("Déplacement", "Travel")} (€)${d.travel_fee_mode === "per_km" && d.distance_km != null ? tt(" — calculé au km, aller-retour", " — per km, round trip") : ""}`}><input className={inp} inputMode="decimal" value={f.proposed_travel_fee} onChange={set("proposed_travel_fee")} data-testid="reply-travel" /></L>
            <L label={tt("TVA", "VAT")}><select className={inp} value={f.vat_mode} onChange={set("vat_mode")} data-testid="reply-vat-mode"><option value="subject">{tt("Assujetti à la TVA (prix HT)", "VAT registered (price excl. VAT)")}</option><option value="not_applicable_293B">{tt("Non assujetti — TVA non applicable, art. 293 B du CGI", "Not VAT registered — VAT not applicable, art. 293 B CGI")}</option></select></L>
            {subject && <L label={tt("Taux de TVA (%)", "VAT rate (%)")}><input className={inp} inputMode="decimal" value={f.vat_rate} onChange={set("vat_rate")} data-testid="reply-vat-rate" /></L>}
            <div className="mt-4 rounded-xl bg-secondary p-4 text-base font-semibold" data-testid="reply-total">{subject ? tt(`Total : ${fmtEur2(ht)} HT, soit ${fmtEur2(ttc)} TTC`, `Total: ${fmtEur2(ht)} excl. VAT, i.e. ${fmtEur2(ttc)} incl. VAT`) : tt(`Total : ${fmtEur2(ht)} net — TVA non applicable, art. 293 B du CGI`, `Total: ${fmtEur2(ht)} net — VAT not applicable, art. 293 B CGI`)}</div>
            <L label={tt("Ce qu'il faut vous fournir sur place", "What you need on site")}><div className="flex flex-wrap gap-2">{Object.entries(d.equipment_labels).map(([k, l]) => (
              <button key={k} type="button" onClick={() => toggle(k)} aria-pressed={f.equipment_needed.includes(k)} data-testid={`reply-equipment-${k}`}
                className={`h-10 rounded-full border px-4 text-sm font-medium ${f.equipment_needed.includes(k) ? "border-primary bg-primary text-white" : "border-border"}`}>{l}</button>))}</div></L>
            <L label={tt("Précisions matériel", "Equipment details")}><input className={inp} value={f.equipment_note} onChange={set("equipment_note")} data-testid="reply-equipment-note" /></L>
            <L label={tt("Autres horaires possibles (facultatif)", "Other possible times (optional)")}><div className="grid grid-cols-2 gap-2"><input type="time" className={inp} value={f.alt_start} onChange={set("alt_start")} aria-label="Début proposé" data-testid="reply-alt-start" /><input type="time" className={inp} value={f.alt_end} onChange={set("alt_end")} aria-label="Fin proposée" data-testid="reply-alt-end" /></div></L>
            <label className="mt-4 flex items-start gap-3 text-sm"><input type="checkbox" className="mt-1 h-5 w-5" checked={f.update_defaults} onChange={(e) => setF({ ...f, update_defaults: e.target.checked })} data-testid="reply-update-defaults" />{tt("Mettre à jour mes conditions par défaut (TVA et besoin matériel)", "Update my default terms (VAT and equipment needs)")}</label>
          </div>)}
        {f.reply && (<>
          <L label={f.reply === "conditional" ? tt("Vos conditions", "Your conditions") : tt("Commentaire (facultatif)", "Comment (optional)")}><textarea className={`${inp} h-24 py-2`} value={f.reply_comment} onChange={set("reply_comment")} data-testid="reply-comment" /></L>
          {err && <p className="mt-3 text-sm text-red-600" data-testid="reply-submit-error">{err}</p>}
          <button className="mt-5 h-14 w-full rounded-full bg-primary text-lg font-semibold text-white disabled:opacity-50" disabled={busy} onClick={submit} data-testid="reply-submit">{busy ? tt("Envoi…", "Sending…") : tt("Envoyer ma réponse", "Send my reply")}</button>
        </>)}
      </>)}
      <p className="mt-8 text-xs text-muted-foreground">{tt("Vos coordonnées sont utilisées uniquement pour vous proposer des missions.", "Your contact details are used only to offer you bookings.")} <a className="underline" href={`/reponse/${token}?stop=1`} data-testid="reply-unsubscribe-link">{tt("Ne plus être sollicité", "Stop receiving requests")}</a></p>
    </Shell>
  );
}
