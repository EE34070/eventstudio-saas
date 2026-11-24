import { useEffect, useState } from "react";
import { useWpMutation, wp, type WEvent, type Wedding } from "../api";
import { num, toast } from "../ui";

export function EventsTab({ w }: { w: Wedding }) {
  const [events, setEvents] = useState<WEvent[]>(w.events);
  useEffect(() => setEvents(w.events), [w.events]);
  const save = useWpMutation((e: WEvent[]) => wp.events(w.id, e), () => toast("Événements enregistrés"));
  const set = (i: number, patch: Partial<WEvent>) => setEvents((xs) => xs.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const named = (e: WEvent) => e.key.startsWith("x");

  return (
    <div>
      <div className="note">Choisissez les événements de ce mariage. La plateforme s'adapte : les sections du questionnaire, la Guest List, Repas et boissons, Design et ambiance, les musiques et le planning ne montrent que les événements activés.</div>
      {events.map((ev, i) => (
        <div key={ev.id} className="sec" style={ev.enabled ? undefined : { opacity: 0.55 }}>
          <div className="row spread">
            <label className="row">
              <input type="checkbox" checked={ev.enabled} disabled={ev.fixed} aria-label={`Activer ${ev.name}`}
                     onChange={(e) => set(i, { enabled: e.target.checked })} />
              <span className="strong">{ev.fixed ? "Toujours actif" : ev.enabled ? "Activé" : "Désactivé"}</span>
            </label>
            {named(ev) && <button className="btn ghost small" onClick={() => setEvents(events.filter((_, j) => j !== i))}>Supprimer</button>}
          </div>
          <label className="l">Nom</label>
          <input value={ev.name} disabled={!named(ev)} onChange={(e) => set(i, { name: e.target.value })} aria-label="Nom de l'événement" />
          <div className="two">
            <div><label className="l">Date</label><input type="date" value={ev.date ?? ""} onChange={(e) => set(i, { date: e.target.value || null })} /></div>
            <div><label className="l">Invités, estimation</label><input inputMode="numeric" value={ev.estimate ?? ""} onChange={(e) => set(i, { estimate: num(e.target.value) })} /></div>
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            {ev.confirmed
              ? <span className="pill ok">Confirmés dans la Guest List : {ev.confirmed}</span>
              : <span className="pill">Guest List : aucun invité encore ajouté</span>}
            <span className="kicker">{ev.confirmed ? "Ce nombre se met à jour tout seul" : "On garde l'estimation en attendant"}</span>
          </div>
          <label className="l">Lieu</label>
          <input value={ev.place} onChange={(e) => set(i, { place: e.target.value })} />
        </div>
      ))}
      <div className="row" style={{ marginTop: 16 }}>
        <button className="btn ghost" onClick={() => {
          const id = Math.random().toString(36).slice(2, 10);
          setEvents([...events, { id, key: `x${id}`, name: "Autre événement", enabled: true, fixed: false, date: null, place: "", estimate: null }]);
        }}>Ajouter un événement « Autre »</button>
        <button className="btn" disabled={save.isPending} onClick={() => save.mutate(events, { onError: (e) => toast(e.message) })}>Enregistrer</button>
      </div>
    </div>
  );
}
