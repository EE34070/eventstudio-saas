import { useEffect, useState } from "react";
import { CalendarClock, MapPin } from "lucide-react";
import { StatusBadge } from "@/components/common";
import { api } from "@/lib/api";
import { fmtDT } from "@/lib/constants";

export function Overlaps({ start, end, venueId, exclude }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    if (!start || !end || end <= start) { setRows(null); return undefined; }
    const t = setTimeout(() => api.get("/events/overlaps", { params: { start, end, venue_id: venueId || undefined, exclude: exclude || undefined } }).then((r) => setRows(r.data)).catch(() => setRows(null)), 250);
    return () => clearTimeout(t);
  }, [start, end, venueId, exclude]);
  if (!rows) return null;
  return (
    <div className="rounded-2xl border border-border p-4 sm:col-span-2" data-testid="event-overlaps">
      <div className="flex items-center gap-2 text-sm font-semibold"><CalendarClock className="h-[18px] w-[18px]" />{rows.length ? `${rows.length} événement(s) sur la même période` : "Aucun autre événement sur cette période"}</div>
      {rows.map((e) => (
        <div key={e.id} className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]" data-testid={`overlap-${e.code}`}>
          <span className="font-semibold">{e.title}</span><StatusBadge status={e.status} />
          <span className="text-[#737373]">{fmtDT(e.start)} → {fmtDT(e.end)}</span>
          <span className={`inline-flex items-center gap-1 ${e.same_venue ? "font-semibold text-red-600 dark:text-red-400" : "text-[#737373]"}`}><MapPin className="h-4 w-4" />{e.venue_name || "—"}{e.same_venue ? " (même lieu)" : ""}</span>
          <span className="text-[#737373]">{e.equipment_count} matériel(s)</span>
        </div>
      ))}
    </div>
  );
}

export function RentalPeriod({ ev, save, write }) {
  const [p, setP] = useState({ s: "", e: "" });
  useEffect(() => { setP({ s: ev.rental_start || "", e: ev.rental_end || "" }); }, [ev]);
  const dirty = p.s !== (ev.rental_start || "") || p.e !== (ev.rental_end || "");
  const cls = "h-9 rounded-md border border-input bg-transparent px-3 text-sm";
  return (
    <div className="mb-4 flex flex-wrap items-end gap-3 rounded-2xl border border-border p-4" data-testid="rental-period">
      <label className="flex flex-col gap-1.5 text-xs font-medium text-muted-foreground">Location du<input type="datetime-local" disabled={!write} className={cls} value={p.s} onChange={(x) => setP({ ...p, s: x.target.value })} data-testid="rental-start-input" /></label>
      <label className="flex flex-col gap-1.5 text-xs font-medium text-muted-foreground">au<input type="datetime-local" disabled={!write} className={cls} value={p.e} onChange={(x) => setP({ ...p, e: x.target.value })} data-testid="rental-end-input" /></label>
      <div className="text-xs text-muted-foreground">{ev.rental_start ? `${ev.rental_days} jour(s) facturé(s) — le matériel est bloqué sur cette plage.` : "Vide : la période suit les dates de l'événement (sortie dépôt → retour)."}</div>
      {write && dirty && <button className="ml-auto text-sm font-semibold underline" onClick={() => save({ rental_start: p.s, rental_end: p.e }, "Période de location enregistrée")} data-testid="rental-period-save">Enregistrer la période</button>}
    </div>
  );
}
