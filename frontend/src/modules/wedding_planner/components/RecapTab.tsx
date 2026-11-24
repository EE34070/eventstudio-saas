import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { download } from "@/core/api/client";
import { useWpMutation, wp, type RecapRubric, type Wedding } from "../api";
import { Loading, toast } from "../ui";

function Rubric({ w, r }: { w: Wedding; r: RecapRubric }) {
  const [text, setText] = useState(r.text);
  useEffect(() => setText(r.text), [r.text]);
  const edit = useWpMutation((t: string) => wp.editRecap(w.id, r.key, t), () => toast("Passage enregistré, il sera conservé si vous régénérez"));
  const prop = useWpMutation((accept: boolean) => wp.proposal(w.id, r.key, accept));
  return (
    <div className="sec">
      <div className="row spread">
        <h3>{r.title}</h3>
        {r.edited && <span className="pill">Modifié à la main</span>}
      </div>
      <textarea aria-label={r.title} value={text} onChange={(e) => setText(e.target.value)}
                onBlur={() => text !== r.text && edit.mutate(text)} placeholder="Rien à signaler pour le moment." />
      {r.proposal && (
        <div className="proposal">
          <div className="kicker">Nouvelle version proposée depuis les dernières réponses</div>
          {r.proposal}
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn small" onClick={() => prop.mutate(true)}>Remplacer ma version</button>
            <button className="btn ghost small" onClick={() => prop.mutate(false)}>Garder ma version</button>
          </div>
        </div>
      )}
    </div>
  );
}

export function RecapTab({ w }: { w: Wedding }) {
  const { data, isLoading } = useQuery({ queryKey: ["wp", "recap", w.id], queryFn: () => wp.recap(w.id) });
  const gen = useWpMutation(() => wp.generate(w.id), () => toast("Récapitulatif régénéré (les passages modifiés à la main sont conservés)"));
  if (isLoading || !data) return <Loading />;
  return (
    <div>
      <div className="row">
        {data.generated_at && <span className="pill ok">Généré depuis le questionnaire</span>}
        <button className="btn ghost" disabled={gen.isPending} onClick={() => gen.mutate(undefined, { onError: (e) => toast(e.message) })}>
          {gen.isPending ? "Génération…" : data.generated_at ? "Régénérer" : "Générer le récapitulatif"}
        </button>
        {data.generated_at && <button className="btn ghost" onClick={() => download(`/wedding-planner/weddings/${w.id}/recap.pdf`, "recapitulatif.pdf").then(() => toast("PDF téléchargé"))}>Télécharger le PDF</button>}
      </div>
      <div className="note">Synthèse modifiable. Vous retrouvez l'essentiel sans relire tout le questionnaire. Vos corrections sont gardées si vous régénérez. Les mariés ne voient jamais ce récapitulatif.</div>
      {!data.generated_at && <div className="empty"><h3>Pas encore de récapitulatif</h3><p>Générez-le dès que le couple a rempli son questionnaire.</p></div>}
      {data.rubrics.map((r) => <Rubric key={r.key} w={w} r={r} />)}
    </div>
  );
}
