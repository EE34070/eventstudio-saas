import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loading, Section, send, toast, useWm, useWq, Wp } from "./core";

function Connection({ s }) {
  const [url, setUrl] = useState(s.form_url || (s.form_id ? `https://docs.google.com/forms/d/${s.form_id}/edit` : ""));
  const save = useWm((form_url) => send("put", "/wedding/settings", { form_url }), () => toast("Formulaire enregistré"));
  const sync = useWm(() => send("post", "/wedding/questionnaire/sync"), (r) => toast(r.status === "ok" ? `Synchronisé : ${r.responses_created ?? 0} nouvelle(s) réponse(s), ${r.new_questions ?? 0} question(s) à classer` : `Synchronisation impossible : ${r.error ?? r.status}`));
  return (
    <Section title="Google Form du questionnaire">
      <p>Le formulaire existant reste la référence : aucune question n'est recréée. Les réponses arrivent toutes seules toutes les 15 minutes, ou tout de suite avec « Synchroniser ».</p>
      <label className="l">Lien du formulaire (édition ou réponse)</label>
      <div className="row"><input style={{ flex: 1 }} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://docs.google.com/forms/d/…" />
        <button className="btn ghost" onClick={() => save.mutate(url)}>Enregistrer</button>
        <button className="btn" disabled={!s.form_id || sync.isPending} onClick={() => sync.mutate()}>{sync.isPending ? "Synchronisation…" : "Synchroniser"}</button></div>
      <div className="row" style={{ marginTop: 10 }}>{s.form_title && <span className="pill ok">{s.form_title}</span>}{s.last_sync && <span className="kicker">Dernière synchronisation : {new Date(s.last_sync).toLocaleString("fr-FR")}</span>}{s.sync_error && <span className="pill warn">Erreur : {s.sync_error}</span>}</div>
      <div className="note">{s.google_configured
        ? <>Partagez le formulaire (« Ajouter des collaborateurs » dans Google Forms) avec l'adresse <b>{s.service_account}</b>. Activez « Collecter les adresses e-mail » : c'est ainsi que chaque réponse est rattachée au bon couple.</>
        : <>Connexion Google pas encore configurée sur le serveur : l'administrateur doit renseigner GOOGLE_SERVICE_ACCOUNT_JSON.</>}</div>
    </Section>
  );
}

function QuestionRow({ q, v }) {
  const patch = useWm((b) => send("patch", `/wedding/questions/${q.id}`, b), () => toast("Rangement mémorisé pour tous les couples"));
  return (
    <tr style={q.status === "deleted" ? { opacity: 0.55 } : undefined}>
      <td className="num">{q.number ?? "·"}</td>
      <td><div className="kicker">{q.section}</div>{q.title}{q.status === "deleted" && <> <span className="pill warn">Supprimée</span></>}</td>
      <td><select value={q.rubric ?? ""} aria-label="Rubrique" onChange={(e) => patch.mutate({ rubric: e.target.value || null })}><option value="">À classer</option>{v.rubrics.map((r) => <option key={r.key} value={r.key}>{r.title}</option>)}</select></td>
      <td><select value={q.fiche_field ?? ""} aria-label="Champ de la fiche" onChange={(e) => patch.mutate({ fiche_field: e.target.value || null })}><option value="">Aucun</option>{Object.entries(v.fiche_fields).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></td>
      <td><select value={q.module ?? ""} aria-label="Module alimenté" onChange={(e) => patch.mutate({ module: e.target.value || null })}><option value="">Aucun</option>{Object.entries(v.modules).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></td>
    </tr>
  );
}

function Questions() {
  const { data: v } = useWq(["questions"], "/wedding/questions");
  const [filter, setFilter] = useState("");
  const classify = useWm(({ id, rubric }) => send("patch", `/wedding/questions/${id}`, { rubric }), () => toast("Question classée"));
  if (!v) return <Loading />;
  const todo = v.questions.filter((q) => q.status === "to_classify");
  const title = (k) => v.rubrics.find((r) => r.key === k)?.title ?? k;
  const shown = v.questions.filter((q) => !filter || `${q.title} ${q.section}`.toLowerCase().includes(filter.toLowerCase()));
  return (<>
    <Section title={`À classer (${todo.length})`}>
      {!todo.length ? <p className="muted">Aucune nouvelle question. Quand vous ajoutez une question au formulaire, elle apparaît ici avec une rubrique suggérée.</p> : todo.map((q) => (
        <div key={q.id} className="qa"><div className="q">{q.section}</div><div>{q.title}</div>
          <div className="row" style={{ marginTop: 6 }}>{q.suggestion && <button className="btn small" onClick={() => classify.mutate({ id: q.id, rubric: q.suggestion })}>Valider : {title(q.suggestion)}</button>}
            <select aria-label="Autre rubrique" value="" style={{ width: "auto" }} onChange={(e) => e.target.value && classify.mutate({ id: q.id, rubric: e.target.value })}><option value="">Choisir une autre rubrique</option>{v.rubrics.map((r) => <option key={r.key} value={r.key}>{r.title}</option>)}</select></div></div>))}
    </Section>
    <Section title="Réglages du questionnaire">
      <p className="muted">Chaque question est reconnue par son identifiant Google : vous pouvez la renommer ou la déplacer dans le formulaire sans rien casser ici.</p>
      <input placeholder="Rechercher une question" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ margin: "8px 0" }} />
      {!v.questions.length ? <div className="empty">Synchronisez le formulaire pour charger ses questions.</div> : (
        <div className="tablewrap"><table><thead><tr><th>N°</th><th>Question</th><th>Rubrique du récapitulatif</th><th>Préremplit la fiche</th><th>Alimente</th></tr></thead><tbody>{shown.map((q) => <QuestionRow key={q.id} q={q} v={v} />)}</tbody></table></div>)}
    </Section>
  </>);
}

function Unassigned() {
  const { data = [] } = useWq(["unassigned"], "/wedding/responses/unassigned");
  const { data: weddings = [] } = useWq(["weddings"], "/wedding/weddings");
  const assign = useWm(({ rid, wid }) => send("put", `/wedding/responses/${rid}/assign`, { wedding_id: wid }), () => toast("Réponse rattachée au couple"));
  if (!data.length) return null;
  return (
    <Section title={`Réponses à attribuer (${data.length})`}><p className="muted">Ces réponses viennent d'une adresse qui ne correspond à aucun partenaire. Rattachez-les au bon mariage.</p>
      {data.map((r) => <div key={r.id} className="qa row spread"><span>{r.email ?? "Adresse non collectée"} · {r.answers} réponses · {new Date(r.submitted_at).toLocaleDateString("fr-FR")}</span>
        <select style={{ width: "auto" }} value="" aria-label="Mariage" onChange={(e) => e.target.value && assign.mutate({ rid: r.id, wid: e.target.value })}><option value="">Rattacher à…</option>{weddings.map((w) => <option key={w.id} value={w.id}>{w.names}</option>)}</select></div>)}
    </Section>
  );
}

function Notif({ s }) {
  const [email, setEmail] = useState(s.notify_email ?? "");
  useEffect(() => setEmail(s.notify_email ?? ""), [s.notify_email]);
  const save = useWm((b) => send("put", "/wedding/settings", b), () => toast("Préférences enregistrées"));
  const set = (k, ch, v) => save.mutate({ notification_prefs: { ...s.notification_prefs, [k]: { ...s.notification_prefs[k], [ch]: v } } });
  return (
    <Section title="Notifications">
      <label className="l">Adresse e-mail qui reçoit les notifications</label>
      <div className="row"><input style={{ flex: 1 }} type="email" value={email} onChange={(e) => setEmail(e.target.value)} /><button className="btn ghost" onClick={() => save.mutate({ notify_email: email || null })}>Enregistrer</button></div>
      <p className="muted">Les e-mails partent par la messagerie Gmail connectée de la société.</p>
      <div className="tablewrap" style={{ marginTop: 14 }}><table><thead><tr><th>Événement</th><th>Dans l'espace</th><th>Par e-mail</th></tr></thead>
        <tbody>{Object.entries(s.notification_types).map(([k, l]) => <tr key={k}><td>{l}</td><td><input type="checkbox" aria-label={`${l} dans l'espace`} checked={!!s.notification_prefs[k]?.app} onChange={(e) => set(k, "app", e.target.checked)} /></td><td><input type="checkbox" aria-label={`${l} par e-mail`} checked={!!s.notification_prefs[k]?.email} onChange={(e) => set(k, "email", e.target.checked)} /></td></tr>)}</tbody></table></div>
    </Section>
  );
}

function Rubrics({ s }) {
  const [rubrics, setRubrics] = useState(s.rubrics);
  useEffect(() => setRubrics(s.rubrics), [s.rubrics]);
  const save = useWm((r) => send("put", "/wedding/settings", { rubrics: r }), () => toast("Rubriques enregistrées"));
  return (
    <Section title="Rubriques du récapitulatif">
      {rubrics.map((r, i) => <div key={r.key} className="row" style={{ marginTop: 6 }}><input style={{ flex: 1 }} value={r.title} aria-label="Titre de la rubrique" onChange={(e) => setRubrics(rubrics.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))} /><button className="btn ghost small" onClick={() => setRubrics(rubrics.filter((_, j) => j !== i))}>Retirer</button></div>)}
      <div className="row" style={{ marginTop: 12 }}><button className="btn ghost" onClick={() => setRubrics([...rubrics, { key: `r${Date.now().toString(36)}`, title: "Nouvelle rubrique" }])}>Ajouter une rubrique</button><button className="btn" onClick={() => save.mutate(rubrics)}>Enregistrer</button></div>
    </Section>
  );
}

export default function Settings() {
  const nav = useNavigate();
  const { data: s } = useWq(["settings"], "/wedding/settings");
  return (
    <Wp>
      <button className="back" onClick={() => nav("/mariages")}>← Tous les mariages</button>
      <div className="kicker">Paramètres</div><h1>Questionnaire et notifications</h1>
      {!s ? <Loading /> : <><Connection s={s} /><Unassigned /><Questions /><Rubrics s={s} /><Notif s={s} /></>}
    </Wp>
  );
}
