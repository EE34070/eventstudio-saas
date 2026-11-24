import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { Loading } from "@/components/common";

const BASE = `${process.env.REACT_APP_BACKEND_URL}/api/public/dj-availability`;
const SAID = { available: "Vous avez répondu : disponible. Merci !", not_available: "Vous avez répondu : pas disponible. Merci !", closed: "Cette demande n'attend plus de réponse." };

export default function DispoDj() {
  const { token } = useParams();
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { axios.get(`${BASE}/${token}`).then((r) => setD(r.data)).catch((e) => setErr(e.response?.status === 410 ? "Ce lien a expiré." : "Ce lien est introuvable ou n'est plus valide.")); }, [token]);
  const send = (available) => { setBusy(true); axios.post(`${BASE}/${token}`, { available }).then((r) => setD({ ...d, status: r.data.status })).catch((e) => setErr(e.response?.data?.detail || "Réponse impossible.")).finally(() => setBusy(false)); };
  if (!d && !err) return <Loading />;
  return (
    <div className="mx-auto min-h-screen max-w-lg px-4 py-8" data-testid="dj-availability-page">
      <div className="mb-6 flex items-center gap-2.5"><span className="brand-mark">{(d?.org || "E")[0]}</span><span className="font-brand text-xl">{d?.org || "Exclusivity Events"}</span></div>
      {err ? <p className="card-soft p-6 text-base" data-testid="dj-availability-error">{err}</p> : (
        <div className="card-soft p-6">
          <p className="text-base">Bonjour {d.name},</p>
          <p className="mt-2 text-base">Êtes-vous disponible le <b data-testid="dj-availability-date">{d.date.split("-").reverse().join("/")}</b>, de {d.start_time} à {d.end_time}{d.city ? `, à ${d.city}` : ""}{d.event_type ? ` (${d.event_type})` : ""} ?</p>
          <p className="mt-1 text-sm text-muted-foreground">Simple question de disponibilité : rien n'est confirmé à ce stade.</p>
          {d.status !== "availability_requested" && <p className="mt-4 rounded-xl bg-secondary p-3 text-sm font-semibold" data-testid="dj-availability-state">{SAID[d.status]}</p>}
          {d.status !== "closed" && <div className="mt-5 grid grid-cols-2 gap-3">
            <button className="h-12 rounded-full bg-emerald-600 text-base font-semibold text-white" disabled={busy} onClick={() => send(true)} data-testid="dj-availability-yes">Oui, disponible</button>
            <button className="h-12 rounded-full bg-neutral-700 text-base font-semibold text-white" disabled={busy} onClick={() => send(false)} data-testid="dj-availability-no">Non</button></div>}
        </div>)}
    </div>);
}
