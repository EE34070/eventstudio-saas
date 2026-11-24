import { useState } from "react";
import { wp, useWpMutation, type Wedding } from "../api";
import { Field, Modal, toast } from "../ui";

export function NewWeddingModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const [f, setF] = useState({ partner1_email: "", partner1_first_name: "", partner2_email: "", partner2_first_name: "",
    date: "", lang: "fr", welcome_dinner: true, brunch: true, send_invitations: true });
  const [err, setErr] = useState("");
  const m = useWpMutation((b: typeof f) => wp.create({ ...b, partner2_email: b.partner2_email || null, date: b.date || null }),
    (w: Wedding) => { toast(f.send_invitations ? "Dossier créé et invitations envoyées" : "Dossier créé"); onClose(); onCreated(w.id); });
  const check = (label: string, k: "welcome_dinner" | "brunch" | "send_invitations") => (
    <label className="row" style={{ fontSize: 14, marginTop: 6 }}>
      <input type="checkbox" checked={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.checked })} />{label}
    </label>
  );
  return (
    <Modal onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); setErr(""); m.mutate(f, { onError: (x) => setErr(x.message) }); }}>
        <h3>Nouveau mariage</h3>
        <div className="two">
          <Field label="Partenaire 1, prénom" value={f.partner1_first_name} onChange={(v) => setF({ ...f, partner1_first_name: v })} />
          <Field label="Partenaire 1, e-mail" type="email" value={f.partner1_email} placeholder="prenom@exemple.com"
                 onChange={(v) => setF({ ...f, partner1_email: v })} />
        </div>
        <div className="two">
          <Field label="Partenaire 2, prénom" value={f.partner2_first_name} onChange={(v) => setF({ ...f, partner2_first_name: v })} />
          <Field label="Partenaire 2, e-mail" type="email" value={f.partner2_email} placeholder="prenom@exemple.com"
                 onChange={(v) => setF({ ...f, partner2_email: v })} />
        </div>
        <Field label="Date du mariage (si connue)" type="date" value={f.date} onChange={(v) => setF({ ...f, date: v })} />
        <label className="l">Événements du mariage</label>
        <label className="row" style={{ fontSize: 14 }}><input type="checkbox" checked disabled />Jour J (toujours)</label>
        {check("Welcome dinner", "welcome_dinner")}
        {check("Brunch", "brunch")}
        <label className="l">Langue de l'espace des mariés
          <select value={f.lang} onChange={(e) => setF({ ...f, lang: e.target.value })} style={{ marginTop: 4, textTransform: "none", letterSpacing: 0 }}>
            <option value="fr">Français</option>
            <option value="en">Anglais</option>
          </select>
        </label>
        <div className="note">Tout l'espace du couple s'affiche dans la langue choisie : menus, textes, formulaires et e-mails. Vous pouvez la changer plus tard dans « Compte et droits ».</div>
        {check("Envoyer les invitations maintenant", "send_invitations")}
        {err && <p style={{ color: "var(--al)" }}>{err}</p>}
        <div className="row" style={{ marginTop: 16 }}>
          <button className="btn" type="submit" disabled={m.isPending || !f.partner1_email}>Créer le compte</button>
          <button className="btn ghost" type="button" onClick={onClose}>Annuler</button>
        </div>
      </form>
    </Modal>
  );
}
