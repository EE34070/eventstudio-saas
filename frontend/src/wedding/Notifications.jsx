import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { send, useWm, useWq } from "./core";

const ago = (iso) => {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 60) return `Il y a ${Math.max(1, m)} min`;
  if (m < 1440) return `Il y a ${Math.round(m / 60)} h`;
  return new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "long" });
};

export function Notifications() {
  const [open, setOpen] = useState(false);
  const nav = useNavigate();
  const { data } = useWq(["notifs"], "/wedding/notifications", { refetchInterval: 60000 });
  const readAll = useWm(() => send("post", "/wedding/notifications/read-all"));
  return (
    <div style={{ position: "relative" }}>
      <button className="btn ghost" aria-expanded={open} onClick={() => { setOpen(!open); if (!open && data?.unread) readAll.mutate(); }}>Notifications ({data?.unread ?? 0})</button>
      {open && (
        <div className="notif" role="dialog" aria-label="Notifications">
          <div className="kicker">Notifications</div>
          {!data?.items.length && <div className="n">Aucune notification pour le moment.</div>}
          {data?.items.map((n) => (
            <div key={n.id} className={`n${n.read ? "" : " unread"}`} style={{ cursor: n.wedding_id ? "pointer" : "default" }} onClick={() => { if (n.wedding_id) { setOpen(false); nav(`/mariages/${n.wedding_id}`); } }}>
              <div>{n.text}</div><div className="kicker">{ago(n.at)}</div>
            </div>
          ))}
          <div className="kicker" style={{ marginTop: 8 }}>Paramétrables dans Paramètres : dans l'espace et par e-mail.</div>
        </div>
      )}
    </div>
  );
}
