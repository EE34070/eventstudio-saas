import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useSession } from "@/core/session/SessionProvider";
import { fmtDate, useWedding, useWpMutation, wp, type Info } from "../api";
import { InfoForm } from "../components/InfoForm";
import { EventsTab } from "../components/EventsTab";
import { QuestionnaireTab } from "../components/QuestionnaireTab";
import { FoodAdmin } from "../components/FoodAdmin";
import { RecapTab } from "../components/RecapTab";
import { AccountTab } from "../components/AccountTab";
import { Wp } from "../Wp";
import { Loading, toast } from "../ui";

const TABS = [["info", "Informations"], ["events", "Événements"], ["quest", "Questionnaire"], ["food", "Repas et boissons"],
  ["recap", "Récapitulatif"], ["access", "Compte et droits"]] as const;

export default function WeddingFile() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("onglet") ?? "info";
  const { canWrite } = useSession();
  const { data: w, isLoading, error } = useWedding(id);
  const save = useWpMutation((info: Info) => wp.info(id, info), () => toast("Enregistré. Le récapitulatif et le planning se mettent à jour."));

  return (
    <Wp>
      <button className="back" onClick={() => nav("/mariages")}>← Tous les mariages</button>
      {isLoading && <Loading />}
      {error && <p>Mariage introuvable.</p>}
      {w && (
        <>
          <div className="kicker">{w.info.date ? `${fmtDate(w.info.date)} · ${w.days_left} jours` : "Date à définir"}</div>
          <h1>{w.names}</h1>
          <div className="row" style={{ margin: "16px 0" }} role="tablist">
            {TABS.map(([k, l]) => (
              <button key={k} role="tab" aria-selected={tab === k} className={`btn${tab === k ? "" : " ghost"}`}
                      onClick={() => setSp({ onglet: k }, { replace: true })}>
                {l}{k === "quest" && w.discrepancies.length > 0 ? ` (${w.discrepancies.length})` : ""}
              </button>
            ))}
          </div>
          {tab === "info" && (
            <>
              <div className="note">Les mariés complètent cette fiche de leur côté. Vous pouvez aussi la modifier. Une seule saisie : elle alimente le récapitulatif, le planning et les autres onglets.</div>
              <InfoForm info={w.info} lang="fr" admin canEdit={canWrite("wedding_planner")} saving={save.isPending}
                        onSave={(info) => save.mutate(info, { onError: (e) => toast(e.message) })} />
            </>
          )}
          {tab === "events" && <EventsTab w={w} />}
          {tab === "quest" && <QuestionnaireTab w={w} />}
          {tab === "food" && <FoodAdmin w={w} />}
          {tab === "recap" && <RecapTab w={w} />}
          {tab === "access" && <AccountTab w={w} />}
        </>
      )}
    </Wp>
  );
}
