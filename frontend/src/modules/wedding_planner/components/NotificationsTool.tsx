import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { wp, useWpMutation } from "../api";
import "../wp.css";

const ago = (iso: string) => {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 60) return `Il y a ${Math.max(1, m)} min`;
  if (m < 1440) return `Il y a ${Math.round(m / 60)} h`;
  return new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "long" });
};

/** Cloche des notifications, dans l'en-tête. Les préférences se règlent dans Paramètres. */
export default function NotificationsTool() {
  const [open, setOpen] = useState(false);
  const nav = useNavigate();
  const { data } = useQuery({ queryKey: ["wp", "notifs"], queryFn: wp.notifications, refetchInterval: 60_000 });
  const readAll = useWpMutation(() => wp.readAll());
  return (
    <div className="wp" style={{ position: "relative" }}>
      <button className="btn ghost" aria-expanded={open} onClick={() => { setOpen(!open); if (!open && data?.unread) readAll.mutate(undefined); }}>
        Notifications ({data?.unread ?? 0})
      </button>
      {open && (
        <div className="notif" role="dialog" aria-label="Notifications">
          <div className="kicker">Notifications</div>
          {!data?.items.length && <div className="n">Aucune notification pour le moment.</div>}
          {data?.items.map((n) => (
            <div key={n.id} className={`n${n.read ? "" : " unread"}`} role={n.wedding_id ? "button" : undefined} tabIndex={n.wedding_id ? 0 : undefined}
                 style={{ cursor: n.wedding_id ? "pointer" : "default" }}
                 onClick={() => { if (n.wedding_id) { setOpen(false); nav(`/mariages/${n.wedding_id}`); } }}>
              <div>{n.text}</div>
              <div className="kicker">{ago(n.at)}</div>
            </div>
          ))}
          <div className="kicker" style={{ marginTop: 8 }}>Paramétrables : vous choisissez lesquelles recevoir, dans l'espace et par e-mail.</div>
        </div>
      )}
    </div>
  );
}
