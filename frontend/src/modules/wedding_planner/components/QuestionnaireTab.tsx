import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useWpMutation, wp, type Wedding } from "../api";
import { Loading, toast } from "../ui";

const LABELS: Record<string, string> = { budget: "Budget global", "guests.adults": "Adultes", "guests.kids": "Enfants",
  "ceremony.type": "Type de cérémonie", "ceremony.place": "Lieu de la cérémonie", "ceremony.time": "Horaire de la cérémonie",
  "ceremony.confession": "Confession", "partners.0.job": "Profession, partenaire 1", "partners.1.job": "Profession, partenaire 2" };

export function QuestionnaireTab({ w }: { w: Wedding }) {
  const { data, isLoading } = useQuery({ queryKey: ["wp", "quest", w.id], queryFn: () => wp.questionnaire(w.id) });
  const resolve = useWpMutation(({ id, keep }: { id: string; keep: "fiche" | "form" }) => wp.resolve(w.id, id, keep),
    () => toast("Fiche mise à jour"));
  if (isLoading || !data) return <Loading />;
  const answered = data.sections.reduce((n, s) => n + s.answered, 0);

  return (
    <div>
      <div className="row">
        {data.status === "submitted"
          ? <span className="pill ok">Rempli{data.submitted_at ? ` le ${new Date(data.submitted_at).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}` : ""}</span>
          : <span className="pill">En attente</span>}
        <span className={`pill${data.connected ? "" : " warn"}`}>{data.connected ? "Google Form connecté" : "Google Form non connecté"}</span>
        {!data.connected && <Link to="/mariages/reglages">Connecter le formulaire</Link>}
      </div>
      <div className="note">Les réponses du Google Form existant arrivent ici automatiquement, rangées par section. Aucune question à recréer.</div>

      {data.discrepancies.length > 0 && (
        <div className="sec">
          <h3>Différences détectées</h3>
          <p className="muted">La fiche est la référence : rien n'a été écrasé. Choisissez la valeur à garder.</p>
          {data.discrepancies.map((d) => (
            <div key={d.id} className="qa">
              <div className="q">{LABELS[d.field] ?? d.field} · {d.question}</div>
              <div className="row">
                <span>Fiche : <b className="strong">{String(d.fiche_value)}</b></span>
                <span>Formulaire : <b className="strong">{String(d.form_value)}</b></span>
                <button className="btn ghost small" onClick={() => resolve.mutate({ id: d.id, keep: "fiche" })}>Garder la fiche</button>
                <button className="btn small" onClick={() => resolve.mutate({ id: d.id, keep: "form" })}>Prendre le formulaire</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {answered === 0 && <div className="empty"><h3>Aucune réponse pour le moment</h3><p>Dès que le couple remplit le formulaire, ses réponses s'affichent ici.</p></div>}
      {data.sections.filter((s) => s.answered > 0 || s.questions.some((q) => q.deleted)).map((s, i) => (
        <details key={s.title} className="sec" open={i < 2}>
          <summary><h3>{s.title} <span className="kicker">({s.answered} réponses)</span></h3></summary>
          {s.questions.filter((q) => q.answer).map((q) => (
            <div key={q.id} className="qa">
              <div className="q">{q.title}</div>
              <div style={{ whiteSpace: "pre-wrap" }}>{q.answer}</div>
              {q.files.length > 0 && <div className="row files">{q.files.map((f) => <a key={f.url} href={f.url} target="_blank" rel="noreferrer">{f.name}</a>)}</div>}
              <div className="row" style={{ marginTop: 4 }}>
                {q.deleted && <span className="pill warn">Question supprimée</span>}
                {q.to_classify && <span className="pill warn">À classer</span>}
                {q.modified_in_fiche && <span className="pill">Modifié dans la fiche</span>}
              </div>
            </div>
          ))}
        </details>
      ))}
    </div>
  );
}
