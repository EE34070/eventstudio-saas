import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMe } from "@/context/MeContext";
import { Field, fmtDate, Loading, Modal, money, send, toast, useWm, useWq, Wp } from "./core";
import { Notifications } from "./Notifications";

function NewWedding({ onClose, onCreated }) {
  const [f, setF] = useState({ partner1_email: "", partner1_first_name: "", partner2_email: "", partner2_first_name: "", date: "", lang: "fr", welcome_dinner: true, brunch: true, send_invitations: true });
  const [links, setLinks] = useState(null);
  const m = useWm((b) => send("post", "/wedding/weddings", { ...b, partner2_email: b.partner2_email || null, date: b.date || null }), (w) => {
    const l = (w.invitations || []).filter((x) => x.link || x.error);
    if (l.length) { setLinks({ id: w.id, rows: l }); return; }
    toast(f.send_invitations ? "Dossier créé et invitations envoyées" : "Dossier créé");
    onClose(); onCreated(w.id);
  });
  const check = (label, k) => <label className="row" style={{ fontSize: 14, marginTop: 6 }}><input type="checkbox" checked={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.checked })} />{label}</label>;
  if (links) return (
    <Modal onClose={() => { onClose(); onCreated(links.id); }}>
      <h3>Dossier créé</h3>
      <p>L'e-mail d'invitation n'a pas pu partir automatiquement (messagerie Gmail non connectée, ou hors production). Transmettez ces liens personnels au couple :</p>
      {links.rows.map((r) => <div key={r.email} className="qa"><div className="q">{r.email}</div>{r.link ? <input readOnly value={r.link} onFocus={(e) => e.target.select()} /> : <div style={{ color: "var(--al)" }}>{r.error}</div>}</div>)}
      <div className="row" style={{ marginTop: 16 }}><button className="btn" onClick={() => { onClose(); onCreated(links.id); }}>Ouvrir le dossier</button></div>
    </Modal>
  );
  return (
    <Modal onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); m.mutate(f); }}>
        <h3>Nouveau mariage</h3>
        <div className="two"><Field label="Partenaire 1, prénom" value={f.partner1_first_name} onChange={(v) => setF({ ...f, partner1_first_name: v })} /><Field label="Partenaire 1, e-mail" type="email" value={f.partner1_email} placeholder="prenom@exemple.com" onChange={(v) => setF({ ...f, partner1_email: v })} /></div>
        <div className="two"><Field label="Partenaire 2, prénom" value={f.partner2_first_name} onChange={(v) => setF({ ...f, partner2_first_name: v })} /><Field label="Partenaire 2, e-mail" type="email" value={f.partner2_email} placeholder="prenom@exemple.com" onChange={(v) => setF({ ...f, partner2_email: v })} /></div>
        <Field label="Date du mariage (si connue)" type="date" value={f.date} onChange={(v) => setF({ ...f, date: v })} />
        <label className="l">Événements du mariage</label>
        <label className="row" style={{ fontSize: 14 }}><input type="checkbox" checked disabled />Jour J (toujours)</label>
        {check("Welcome dinner", "welcome_dinner")}{check("Brunch", "brunch")}
        <label className="l">Langue de l'espace des mariés
          <select value={f.lang} onChange={(e) => setF({ ...f, lang: e.target.value })} style={{ marginTop: 4, textTransform: "none", letterSpacing: 0 }}><option value="fr">Français</option><option value="en">Anglais</option></select>
        </label>
        <div className="note">Tout l'espace du couple s'affiche dans la langue choisie : menus, textes, formulaires et e-mails. Vous pourrez la changer dans « Compte et droits ». Les partenaires deviennent des contacts, et chaque événement daté apparaît dans Événements.</div>
        {check("Envoyer les invitations maintenant", "send_invitations")}
        <div className="row" style={{ marginTop: 16 }}><button className="btn" type="submit" disabled={m.isPending || !f.partner1_email}>Créer le compte</button><button className="btn ghost" type="button" onClick={onClose}>Annuler</button></div>
      </form>
    </Modal>
  );
}

export default function Dashboard() {
  const nav = useNavigate();
  const { can } = useMe();
  const [creating, setCreating] = useState(false);
  const { data = [], isLoading } = useWq(["weddings"], "/wedding/weddings");
  const open = (id) => nav(`/mariages/${id}`);
  const soon = (v) => v ?? "À venir";
  return (
    <Wp>
      <div className="row spread"><div className="kicker">Tableau de bord</div><div className="row"><Notifications /><button className="btn ghost" onClick={() => nav("/mariages/reglages")}>Paramètres</button></div></div>
      <h1>Vos mariages en cours</h1>
      <p>Une vue d'ensemble de tous les mariages. Cliquez sur une carte pour ouvrir le dossier du couple.</p>
      {isLoading ? <Loading /> : (
        <div className="grid">
          {data.map((w) => (
            <div key={w.id} className="card click" role="button" tabIndex={0} onClick={() => open(w.id)} onKeyDown={(e) => e.key === "Enter" && open(w.id)} data-testid={`wedding-card-${w.id}`}>
              <h3>{w.names}</h3>
              <div className="kicker">{w.date ? `${fmtDate(w.date)} · ${w.days_left} jours` : "Date à définir"}</div>
              <div>{w.venue || "Lieu à confirmer"}</div>
              <div className="bar" aria-label={`Avancement ${w.progress} %`}><i style={{ width: `${w.progress}%` }} /></div>
              <div className="kicker">Avancement {w.progress} %</div>
              <div>{w.guests != null ? `${w.guests} invités` : "Invités à préciser"}{w.budget != null && ` · Budget ${money(w.budget)}`}</div>
              <div className="row">{w.questionnaire === "submitted" ? <span className="pill ok">Questionnaire rempli</span> : <span className="pill">Questionnaire en attente</span>}{w.open_discrepancies > 0 && <span className="pill warn">{w.open_discrepancies} différence(s)</span>}</div>
              <div>Prestataires validés : {soon(w.vendors)}</div>
              <div>Documents : {soon(w.documents)}</div>
              <div><span className="strong">Prochain paiement : </span>{soon(w.next_payment)}</div>
              <div><span className="strong">Prochaine tâche : </span>{soon(w.next_task)}</div>
            </div>
          ))}
          {can("events:write") && <button className="card click add" onClick={() => setCreating(true)} data-testid="wedding-new"><h3>Nouveau mariage</h3><div>Créer le dossier et le compte du couple</div></button>}
        </div>
      )}
      {creating && <NewWedding onClose={() => setCreating(false)} onCreated={open} />}
    </Wp>
  );
}
