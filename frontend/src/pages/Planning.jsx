import { DjDot } from "@/components/dj/DjPlanning";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader, StatusBadge, Loading } from "@/components/common";
import { showError } from "@/pages/EventDetail";
import { api } from "@/lib/api";
import { dayKey, daysBetween, fmtDate } from "@/lib/constants";
import { useMe } from "@/context/MeContext";
import { Filters, Resources } from "@/components/planning/Resources";
import WorksTeam from "@/components/planning/WorksTeam";

const WD = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const monday = (d) => { const x = new Date(d.getFullYear(), d.getMonth(), d.getDate()); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x; };
const coversDay = (e, k) => {
  const s = e.start.slice(0, 10);
  let end = e.end.slice(0, 10);
  if (end > s && e.end.slice(11, 16) < "06:00") end = dayKey(addDays(new Date(end + "T00:00"), -1));
  return s <= k && k <= end;
};

function Chip({ e, day, draggable, compact }) {
  const nav = useNavigate();
  return (
    <div draggable={draggable} onDragStart={(ev) => ev.dataTransfer.setData("text/plain", JSON.stringify({ id: e.id, day }))}
      onClick={() => nav(`/evenements/${e.id}`)} data-testid={`planning-chip-${e.id}-${day}`}
      className={`st-${e.status} cursor-pointer truncate rounded-md px-2 py-1 text-[11.5px] font-medium transition-transform hover:scale-[1.02] ${draggable ? "active:cursor-grabbing" : ""}`}>
      {!compact && <span className="mr-1 opacity-70">{e.start.slice(0, 10) === day ? e.start.slice(11, 16) : "↳"}</span>}{e.title}<DjDot id={e.id} />{e.shortages_count > 0 && <span className="ml-1 rounded-full bg-red-600 px-1.5 text-[10px] font-bold text-white" title={`${e.shortages_count} manque(s) de matériel à traiter`} data-testid={`planning-shortages-${e.id}`}>{e.shortages_count}</span>}
    </div>
  );
}

function DayCell({ k, events, canDrag, onDrop, muted, minH = "min-h-[112px]", max = 3, children }) {
  const [over, setOver] = useState(false);
  const items = events.filter((e) => coversDay(e, k));
  const today = k === dayKey(new Date());
  return (
    <div onDragOver={(ev) => { if (canDrag) { ev.preventDefault(); setOver(true); } }} onDragLeave={() => setOver(false)}
      onDrop={(ev) => { ev.preventDefault(); setOver(false); const d = JSON.parse(ev.dataTransfer.getData("text/plain") || "{}"); if (d.id) onDrop(d.id, daysBetween(d.day, k)); }}
      className={`${minH} border-b border-r border-border p-1.5 transition-colors ${over ? "bg-accent" : muted ? "bg-secondary/40" : "bg-card"}`} data-testid={`planning-day-${k}`}>
      <div className={`mb-1 text-right text-[11px] ${today ? "font-bold text-primary" : "text-muted-foreground"}`}>{Number(k.slice(8))}</div>
      <div className="space-y-1">
        {items.slice(0, max).map((e) => <Chip key={e.id} e={e} day={k} draggable={canDrag} />)}
        {items.length > max && <div className="px-1 text-[11px] text-muted-foreground">+{items.length - max} autre(s)</div>}
      </div>
      {children}
    </div>
  );
}

function TeamRows({ days, events, team }) {
  return (
    <div className="card-soft mt-6 overflow-x-auto" data-testid="planning-team-rows">
      <div className="min-w-[900px]">
        <div className="grid grid-cols-[180px_repeat(7,1fr)] border-b border-border bg-secondary/50 text-xs font-semibold">
          <div className="p-2.5">Affectations équipe</div>{days.map((d) => <div key={dayKey(d)} className="p-2.5">{WD[(d.getDay() + 6) % 7]} {d.getDate()}</div>)}
        </div>
        {team.map((m) => (
          <div key={m.id} className="grid grid-cols-[180px_repeat(7,1fr)] border-b border-border text-xs last:border-0">
            <div className="flex items-center gap-2 p-2.5"><span className="h-2.5 w-2.5 rounded-full" style={{ background: m.color }} /><span className="truncate">{m.name}</span></div>
            {days.map((d) => {
              const k = dayKey(d);
              const evs = events.filter((e) => coversDay(e, k) && e.team.some((t) => t.member_id === m.id));
              const off = m.unavailabilities?.some((u) => u.start <= k && k <= u.end);
              return <div key={k} className={`p-1.5 ${off ? "bg-secondary" : ""}`}>{evs.map((e) => <div key={e.id} className="mb-1 truncate rounded px-1.5 py-0.5 text-white" style={{ background: m.color }} title={e.title}>{e.code.slice(-3)} {e.title}</div>)}{off && !evs.length && <span className="text-muted-foreground">Absent</span>}</div>;
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

function DayView({ k, events }) {
  const nav = useNavigate();
  const items = events.filter((e) => coversDay(e, k));
  if (!items.length) return <div className="card-soft p-10 text-center text-sm text-muted-foreground">Aucun événement ce jour.</div>;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {items.map((e) => (
        <button key={e.id} onClick={() => nav(`/evenements/${e.id}`)} className="card-soft p-5 text-left hover-lift" data-testid={`day-event-${e.id}`}>
          <div className="flex items-center justify-between"><span className="font-mono text-xs text-muted-foreground">{e.code}</span><StatusBadge status={e.status} /></div>
          <div className="mt-1 font-display text-xl">{e.title}</div>
          <div className="mt-1 text-sm text-muted-foreground">{e.start.slice(11, 16)} → {e.end.slice(11, 16)} · {e.venue_name}, {e.venue_city}</div>
          <div className="mt-3 flex flex-wrap gap-1.5">{e.team.map((t) => <span key={t.member_id} className="rounded-full px-2 py-0.5 text-[11px] text-white" style={{ background: t.color }}>{t.name}{t.role ? ` · ${t.role}` : ""}</span>)}{!e.team.length && <span className="text-xs text-amber-700">Aucun technicien affecté</span>}</div>
        </button>
      ))}
    </div>
  );
}

export default function Planning() {
  const { can, me } = useMe();
  const works = (!me?.plan || me.plan.sections.includes("works")) && (!me?.grid || !!me.grid.works?.view);
  const [view, setView] = useState(new URLSearchParams(window.location.search).get("vue") === "equipe" ? "team" : window.innerWidth < 768 ? "day" : "month");
  const [cursor, setCursor] = useState(new Date());
  const [events, setEvents] = useState(null);
  const [team, setTeam] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [flt, setFlt] = useState({ type: "", vehicle: "", person: "", venue: "" });
  const canDrag = can("events:write");

  const days = useMemo(() => {
    if (view === "month") { const s = monday(new Date(cursor.getFullYear(), cursor.getMonth(), 1)); return Array.from({ length: 42 }, (_, i) => addDays(s, i)); }
    if (view === "week" || view === "resources" || view === "team") { const s = monday(cursor); return Array.from({ length: 7 }, (_, i) => addDays(s, i)); }
    return [new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate())];
  }, [view, cursor]);

  const load = useCallback(() => {
    api.get("/events", { params: { date_from: dayKey(days[0]) + "T00:00", date_to: dayKey(days[days.length - 1]) + "T23:59" } }).then((r) => setEvents(r.data));
  }, [days]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.get("/vehicles").then((r) => setVehicles(r.data)).catch(() => {}); }, []);
  useEffect(() => { api.get("/team").then((r) => setTeam(r.data.filter((t) => t.active))); }, []);

  const shift = async (id, n) => {
    if (!n) return;
    try { await api.post(`/events/${id}/shift`, { days: n }); toast.success(`Événement décalé de ${n > 0 ? "+" : ""}${n} jour(s)`); load(); } catch (err) { showError(err); }
  };
  const assign = async (body, force) => {
    try { await api.post("/planning/assign", { ...body, force }); return true; } catch (err) {
      const d = err?.response?.data?.detail;
      if (d?.code === "resource_conflict" && !force) return window.confirm(`Conflit : ${d.message}.\n\nAffecter quand même ?`) ? assign(body, true) : false;
      showError(err); return false;
    }
  };
  const dropRes = async (p, kind, rid, k) => {
    let ok = true;
    if (p.kind === kind && p.rid !== rid) ok = await assign(kind === "vehicle" ? { event_id: p.id, vehicle_id: rid } : { event_id: p.id, add_member_id: rid, remove_member_id: p.rid });
    const n = daysBetween(p.day, k);
    if (ok && n) { try { await api.post(`/events/${p.id}/shift`, { days: n }); } catch (err) { showError(err); } }
    if (ok) toast.success("Planning mis à jour");
    load();
  };
  const shown = (events || []).filter((e) => (!flt.type || e.type === flt.type) && (!flt.vehicle || e.vehicle_id === flt.vehicle) && (!flt.person || e.team.some((t) => t.member_id === flt.person)) && (!flt.venue || e.venue_name === flt.venue));
  const venues = [...new Set((events || []).map((e) => e.venue_name).filter(Boolean))].sort();
  const step = (dir) => setCursor(view === "month" ? new Date(cursor.getFullYear(), cursor.getMonth() + dir, 1) : addDays(cursor, dir * (view === "day" ? 1 : 7)));
  const title = view === "month" ? cursor.toLocaleDateString("fr-FR", { month: "long", year: "numeric" })
    : view !== "day" ? `Semaine du ${fmtDate(dayKey(days[0]), { day: "numeric", month: "long" })}` : fmtDate(dayKey(days[0]), { weekday: "long", day: "numeric", month: "long", year: "numeric" });

  return (
    <div>
      <PageHeader eyebrow="Opérations" title="Planning" subtitle={canDrag ? "Glissez un événement sur un autre jour pour le décaler (le contrôle de disponibilité du matériel s'applique)." : "Vos événements et affectations."} />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon" onClick={() => step(-1)} data-testid="planning-prev"><ChevronLeft className="h-4 w-4" /></Button>
          <Button variant="outline" onClick={() => setCursor(new Date())} data-testid="planning-today">Aujourd'hui</Button>
          <Button variant="outline" size="icon" onClick={() => step(1)} data-testid="planning-next"><ChevronRight className="h-4 w-4" /></Button>
        </div>
        <h2 className="font-display text-xl first-letter:uppercase" data-testid="planning-title">{title}</h2>
        <div className="ml-auto flex rounded-xl border border-border bg-card p-1">
          {[["day", "Jour"], ["week", "Semaine"], ["month", "Mois"], ["resources", "Ressources"], ...(works ? [["team", "Équipe"]] : [])].map(([k, l]) => (
            <button key={k} onClick={() => setView(k)} data-testid={`planning-view-${k}`} className={`rounded-lg px-3 py-1.5 text-xs font-medium ${view === k ? "bg-foreground text-background" : "text-muted-foreground"}`}>{l}</button>
          ))}
        </div>
      </div>
      {view !== "team" && <Filters value={flt} onChange={setFlt} vehicles={vehicles} team={team} venues={venues} />}
      {view === "team" ? <WorksTeam days={days} canEdit={can("catalog:write")} /> : !events ? <Loading /> : view === "day" ? <DayView k={dayKey(days[0])} events={shown} /> : view === "resources" ? <Resources days={days} events={shown} vehicles={vehicles} team={team} coversDay={coversDay} canDrag={canDrag} onDrop={dropRes} /> : (
        <>
          <div className="card-soft overflow-x-auto">
            <div className="min-w-[760px]">
              <div className="grid grid-cols-7 border-b border-border bg-secondary/50">{WD.map((d) => <div key={d} className="p-2.5 text-xs font-semibold">{d}</div>)}</div>
              <div className="grid grid-cols-7 border-l border-border">
                {days.map((d) => <DayCell key={dayKey(d)} k={dayKey(d)} events={shown} canDrag={canDrag} onDrop={shift}
                  muted={view === "month" && d.getMonth() !== cursor.getMonth()} minH={view === "week" ? "min-h-[260px]" : "min-h-[112px]"} max={view === "week" ? 8 : 3} />)}
              </div>
            </div>
          </div>
          {view === "week" && <TeamRows days={days} events={shown} team={team} />}
        </>
      )}
    </div>
  );
}
