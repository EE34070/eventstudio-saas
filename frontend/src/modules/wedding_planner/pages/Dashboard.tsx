import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useSession } from "@/core/session/SessionProvider";
import { fmtDate, money, wp } from "../api";
import { NewWeddingModal } from "../components/NewWeddingModal";
import { Wp } from "../Wp";
import { Loading } from "../ui";

export default function Dashboard() {
  const nav = useNavigate();
  const { canWrite } = useSession();
  const [creating, setCreating] = useState(false);
  const { data = [], isLoading } = useQuery({ queryKey: ["wp", "weddings"], queryFn: wp.weddings });
  const open = (id: string) => nav(`/mariages/${id}`);
  const soon = (v: string | null) => v ?? "À venir";

  return (
    <Wp>
      <div className="kicker">Tableau de bord</div>
      <h1>Vos mariages en cours</h1>
      <p>Une vue d'ensemble de tous les mariages. Cliquez sur une carte pour ouvrir le dossier du couple.</p>
      {isLoading ? <Loading /> : (
        <div className="grid">
          {data.map((w) => (
            <div key={w.id} className="card click" role="button" tabIndex={0} onClick={() => open(w.id)}
                 onKeyDown={(e) => e.key === "Enter" && open(w.id)}>
              <h3>{w.names}</h3>
              <div className="kicker">{w.date ? `${fmtDate(w.date)} · ${w.days_left} jours` : "Date à définir"}</div>
              <div>{w.venue || "Lieu à confirmer"}</div>
              <div className="bar" aria-label={`Avancement ${w.progress} %`}><i style={{ width: `${w.progress}%` }} /></div>
              <div className="kicker">Avancement {w.progress} %</div>
              <div>{w.guests != null ? `${w.guests} invités` : "Invités à préciser"}{w.budget != null && ` · Budget ${money(w.budget)}`}</div>
              <div className="row">
                {w.questionnaire === "submitted" ? <span className="pill ok">Questionnaire rempli</span> : <span className="pill">Questionnaire en attente</span>}
                {w.open_discrepancies > 0 && <span className="pill warn">{w.open_discrepancies} différence(s)</span>}
              </div>
              <div>Prestataires validés : {soon(w.vendors)}</div>
              <div>Documents : {soon(w.documents)}</div>
              <div><span className="strong">Prochain paiement : </span>{soon(w.next_payment)}</div>
              <div><span className="strong">Prochaine tâche : </span>{soon(w.next_task)}</div>
            </div>
          ))}
          {canWrite("wedding_planner") && (
            <button className="card click add" onClick={() => setCreating(true)}>
              <h3>Nouveau mariage</h3>
              <div>Créer le dossier et le compte du couple</div>
            </button>
          )}
        </div>
      )}
      {creating && <NewWeddingModal onClose={() => setCreating(false)} onCreated={(id) => open(id)} />}
    </Wp>
  );
}
