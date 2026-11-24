import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { dayKey, EVENT_TYPES } from "@/lib/constants";

const WD = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const sel = "h-9 rounded-full border border-border bg-background px-3 text-xs";
const grid = "grid grid-cols-[170px_repeat(7,minmax(0,1fr))]";

export function Filters({ value, onChange, vehicles, team, venues }) {
  const set = (k) => (e) => onChange({ ...value, [k]: e.target.value });
  return (
    <div className="mb-4 flex flex-wrap gap-2" data-testid="planning-filters">
      <select className={sel} value={value.type} onChange={set("type")} data-testid="planning-filter-type"><option value="">Tous les types</option>{EVENT_TYPES.map((t) => <option key={t}>{t}</option>)}</select>
      <select className={sel} value={value.vehicle} onChange={set("vehicle")} data-testid="planning-filter-vehicle"><option value="">Tous les véhicules</option>{vehicles.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</select>
      <select className={sel} value={value.person} onChange={set("person")} data-testid="planning-filter-person"><option value="">Toute l'équipe</option>{team.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select>
      <select className={sel} value={value.venue} onChange={set("venue")} data-testid="planning-filter-venue"><option value="">Tous les lieux</option>{venues.map((v) => <option key={v}>{v}</option>)}</select>
      <select className={sel} disabled title="Disponible avec le module Entrepôts & stocks" data-testid="planning-filter-warehouse"><option>Tous les entrepôts</option></select>
    </div>
  );
}

function Cell({ kind, rid, k, items, color, canDrag, onDrop, off }) {
  const [over, setOver] = useState(false);
  const nav = useNavigate();
  return (
    <div onDragOver={(e) => { if (canDrag) { e.preventDefault(); setOver(true); } }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const p = JSON.parse(e.dataTransfer.getData("text/plain") || "{}"); if (p.id) onDrop(p, kind, rid, k); }}
      className={`min-h-[52px] border-l border-border p-1 transition-colors ${over ? "bg-accent" : off ? "bg-secondary" : ""}`} data-testid={`res-cell-${kind}-${rid || "none"}-${k}`}>
      {items.map((e) => (
        <div key={e.id} draggable={canDrag} onDragStart={(ev) => ev.dataTransfer.setData("text/plain", JSON.stringify({ id: e.id, day: k, kind, rid }))} onClick={() => nav(`/evenements/${e.id}`)} title={e.title}
          className={`mb-1 cursor-pointer truncate rounded-md px-1.5 py-1 text-[11px] font-medium ${color ? "text-white" : `st-${e.status}`}`} style={color ? { background: color } : undefined} data-testid={`res-chip-${kind}-${e.id}`}>{e.start.slice(11, 16)} {e.title}</div>
      ))}
      {off && !items.length && <span className="text-[11px] text-muted-foreground">Absent</span>}
    </div>
  );
}

export function Resources({ days, events, vehicles, team, coversDay, canDrag, onDrop }) {
  const head = (label) => <div className={`${grid} border-b border-border bg-secondary/50 text-xs font-semibold`}><div className="p-2.5">{label}</div>{days.map((d) => <div key={dayKey(d)} className="border-l border-border p-2.5">{WD[(d.getDay() + 6) % 7]} {d.getDate()}</div>)}</div>;
  const row = (kind, rid, label, match, extra = {}) => (
    <div key={`${kind}-${rid}`} className={`${grid} border-b border-border text-xs last:border-0`} data-testid={`res-row-${kind}-${rid || "none"}`}>
      <div className="flex items-center gap-2 p-2.5">{extra.color && <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: extra.color }} />}<span className="truncate">{label}</span></div>
      {days.map((d) => { const k = dayKey(d); return <Cell key={k} kind={kind} rid={rid} k={k} color={extra.color} canDrag={canDrag} onDrop={onDrop} off={extra.off?.(k)} items={events.filter((e) => coversDay(e, k) && match(e))} />; })}
    </div>
  );
  return (
    <div className="card-soft overflow-x-auto" data-testid="planning-resources"><div className="min-w-[980px]">
      {head("Véhicules")}
      {vehicles.filter((v) => v.active).map((v) => row("vehicle", v.id, v.name, (e) => e.vehicle_id === v.id))}
      {row("vehicle", "", "Sans véhicule", (e) => !e.vehicle_id)}
      {head("Chauffeurs / équipe")}
      {team.map((m) => row("member", m.id, `${m.name}${m.is_driver ? " · chauffeur" : ""}`, (e) => e.team.some((t) => t.member_id === m.id), { color: m.color, off: (k) => m.unavailabilities?.some((u) => u.start <= k && k <= u.end) }))}
      {head("Entrepôts")}
      <div className="p-3 text-xs text-muted-foreground" data-testid="res-warehouses-placeholder">Les entrepôts et les missions logistiques (chargement, livraison, retrait, transfert) s'afficheront ici avec les modules Entrepôts & stocks et Logistique.</div>
    </div></div>
  );
}
