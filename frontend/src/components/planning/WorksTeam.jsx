import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { AlertTriangle, FileDown, GripVertical } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Loading } from "@/components/common";
import { api, errMsg, downloadPdf } from "@/lib/api";
import { dayKey, fmtDate } from "@/lib/constants";

// Planning › Équipe : personnes × jours, travaux internes + événements, backlog à glisser-déposer.
const WD = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const PRIO = { basse: "bg-slate-400", normale: "bg-sky-600", haute: "bg-amber-500", urgente: "bg-red-600" };
const hm = (m) => (m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60}` : ""}` : `${m} min`);
const ko = (e) => toast.error(errMsg(e));

function Gauge({ m }) {
  if (m.intermittent || !m.capacity) return <div className="text-[10.5px] text-muted-foreground">{m.hours} h{m.intermittent ? " · intermittent" : ""}</div>;
  const pct = m.load_pct ?? 0;
  const tone = pct > 100 ? "bg-red-600" : pct > 85 ? "bg-amber-500" : "bg-emerald-600";
  return (
    <div title={`${m.hours} h planifiées sur ${m.capacity} h disponibles`} data-testid={`gauge-${m.id}`}>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary"><div className={`h-full ${tone}`} style={{ width: `${Math.min(pct, 100)}%` }} /></div>
      <div className="mt-0.5 text-[10.5px] text-muted-foreground">{m.hours} / {m.capacity} h · {pct} %</div>
    </div>
  );
}

function PlaceDialog({ place, team, onClose, onDone }) {
  const [f, setF] = useState(null);
  const [conflicts, setConflicts] = useState(null);
  useEffect(() => { setConflicts(null); setF(place ? { start: place.start, end: place.end || "", people: place.people } : null); }, [place]);
  if (!place || !f) return null;
  const send = (force) => api.post(`/work-orders/${place.work.id}/place`, { scheduled_start: f.start, scheduled_end: f.end, assignee_ids: f.people, force })
    .then((r) => { toast.success(r.data.forced ? "Planifié malgré les alertes" : "Travail planifié"); onDone(); onClose(); })
    .catch((e) => { const c = e?.response?.data?.detail?.conflicts; if (e?.response?.status === 409 && c) setConflicts(c); else ko(e); });
  const unplace = () => api.post(`/work-orders/${place.work.id}/unplace`).then(() => { toast.success("Remis dans « À planifier »"); onDone(); onClose(); }).catch(ko);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>{place.work.title}</DialogTitle></DialogHeader>
        <div className="grid grid-cols-2 gap-3" data-testid="place-form">
          <label className="text-xs text-muted-foreground">Début<Input type="datetime-local" value={f.start} onChange={(e) => { setConflicts(null); setF({ ...f, start: e.target.value }); }} data-testid="place-start" /></label>
          <label className="text-xs text-muted-foreground">Fin (vide = calculée)<Input type="datetime-local" value={f.end} onChange={(e) => { setConflicts(null); setF({ ...f, end: e.target.value }); }} /></label>
          <div className="col-span-2">
            <div className="mb-1.5 text-xs text-muted-foreground">Personnes{place.work.required_people > 1 ? ` (${place.work.required_people} requises)` : ""}</div>
            <div className="flex flex-wrap gap-1.5">{team.map((p) => { const on = f.people.includes(p.id); return (
              <button type="button" key={p.id} aria-pressed={on} onClick={() => { setConflicts(null); setF({ ...f, people: on ? f.people.filter((x) => x !== p.id) : [...f.people, p.id] }); }}
                className={`rounded-full border px-3 py-1 text-xs ${on ? "border-primary bg-primary text-primary-foreground" : "border-border"}`}>{p.name}</button>); })}</div>
          </div>
          {conflicts && (
            <div className="col-span-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm" data-testid="place-conflicts">
              <div className="mb-1 flex items-center gap-1.5 font-semibold"><AlertTriangle className="h-4 w-4 text-amber-600" />À vérifier avant de planifier</div>
              <ul className="list-disc space-y-0.5 pl-5">{conflicts.map((c) => <li key={c}>{c}</li>)}</ul>
            </div>)}
        </div>
        <DialogFooter>
          {place.work.scheduled_start && <Button variant="ghost" onClick={unplace} data-testid="place-unplace">Retirer du planning</Button>}
          {conflicts ? <Button variant="destructive" onClick={() => send(true)} data-testid="place-force">Planifier quand même</Button>
            : <Button onClick={() => send(false)} disabled={!f.start} data-testid="place-save">Planifier</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function WorksTeam({ days, canEdit }) {
  const nav = useNavigate();
  const [b, setB] = useState(null);
  const [backlog, setBacklog] = useState([]);
  const [place, setPlace] = useState(null);
  const [over, setOver] = useState("");
  const start = dayKey(days[0]);
  const load = useCallback(() => {
    api.get("/work-planning", { params: { start, days: days.length } }).then((r) => setB(r.data)).catch(ko);
    if (canEdit) api.get("/work-orders", { params: { backlog: true } }).then((r) => setBacklog(r.data.orders)).catch(() => {});
  }, [start, days.length, canEdit]);
  useEffect(() => { load(); }, [load]);
  if (!b) return <Loading />;

  const drop = async (ev, member, cell) => {
    ev.preventDefault(); setOver("");
    const d = JSON.parse(ev.dataTransfer.getData("text/plain") || "{}");
    if (!d.id) return;
    const w = d.from ? (await api.get(`/work-orders/${d.id}`).catch(ko))?.data : backlog.find((x) => x.id === d.id);
    if (!w) return;
    const last = cell.items.filter((i) => i.end.slice(0, 10) === cell.date && i.id !== w.id).map((i) => i.end.slice(11, 16)).sort().pop();
    const time = d.from && w.scheduled_start ? w.scheduled_start.slice(11, 16) : last && last < "18:00" ? last : "08:00";
    const people = [...(w.assignee_ids || []).filter((x) => x !== d.from), member.id].filter((x, i, a) => a.indexOf(x) === i);
    setPlace({ work: w, start: `${cell.date}T${time}`, people });
  };
  const open = async (i) => {
    if (i.kind === "event") return nav(`/evenements/${i.id}`);
    if (!canEdit) return;
    const w = (await api.get(`/work-orders/${i.id}`).catch(ko))?.data;
    if (w) setPlace({ work: w, start: w.scheduled_start, end: w.scheduled_end, people: w.assignee_ids || [] });
  };
  const today = dayKey(new Date());
  return (
    <div className="flex gap-4" data-testid="works-team">
      {canEdit && (
        <aside className="card-soft w-64 shrink-0 self-start p-3" data-testid="works-backlog">
          <div className="mb-2 flex items-center justify-between text-sm font-semibold">À planifier <span className="text-xs font-normal text-muted-foreground">{backlog.length}</span></div>
          <p className="mb-2 text-[11px] text-muted-foreground">Glissez un travail sur une personne et un jour.</p>
          <div className="max-h-[70vh] space-y-1.5 overflow-y-auto">
            {backlog.map((w) => (
              <div key={w.id} draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", JSON.stringify({ id: w.id }))}
                className="flex cursor-grab gap-1.5 rounded-lg border border-border bg-card p-2 text-xs active:cursor-grabbing" data-testid={`backlog-${w.id}`}>
                <GripVertical className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 font-medium"><span className={`h-2 w-2 shrink-0 rounded-full ${PRIO[w.priority]}`} /><span className="truncate">{w.title}</span></div>
                  <div className="mt-0.5 text-muted-foreground">{hm(w.estimated_minutes)} · {w.required_people} pers.{w.deadline && <span className={w.late ? " font-semibold text-red-600" : ""}> · avant le {fmtDate(w.deadline, { day: "numeric", month: "short" })}</span>}</div>
                </div>
              </div>))}
            {!backlog.length && <p className="text-xs text-muted-foreground">Rien à planifier.</p>}
          </div>
        </aside>)}
      <div className="card-soft min-w-0 flex-1 overflow-x-auto">
        <div className="min-w-[900px]">
          <div className="grid border-b border-border bg-secondary/50 text-xs font-semibold" style={{ gridTemplateColumns: `180px repeat(${b.days.length}, 1fr)` }}>
            <div className="flex items-center justify-between p-2.5">Équipe
              <button onClick={() => downloadPdf(`/work-planning/pdf?start=${start}&days=${days.length}`, `planning-equipe-${start}.pdf`).catch(ko)} title="PDF de la semaine" data-testid="works-team-pdf"><FileDown className="h-4 w-4" /></button></div>
            {b.days.map((k) => { const d = new Date(k + "T00:00"); return <div key={k} className={`p-2.5 ${k === today ? "text-primary" : ""}`}>{WD[(d.getDay() + 6) % 7]} {d.getDate()}</div>; })}
          </div>
          {b.members.map((m) => (
            <div key={m.id} className="grid border-b border-border text-xs last:border-0" style={{ gridTemplateColumns: `180px repeat(${b.days.length}, 1fr)` }} data-testid={`team-row-${m.id}`}>
              <div className="space-y-1 p-2.5"><div className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ background: m.color }} /><span className="truncate font-medium">{m.name}</span></div><Gauge m={m} /></div>
              {m.cells.map((c) => {
                const key = `${m.id}:${c.date}`;
                return (
                  <div key={c.date} onDragOver={(e) => { if (canEdit) { e.preventDefault(); setOver(key); } }} onDragLeave={() => setOver("")} onDrop={(e) => drop(e, m, c)}
                    className={`min-h-[64px] border-l border-border p-1 transition-colors ${over === key ? "bg-accent" : c.absent ? "bg-secondary" : ""}`} data-testid={`cell-${m.id}-${c.date}`}>
                    {c.absent && <div className="mb-1 truncate text-[10.5px] text-muted-foreground">{c.absent}</div>}
                    {c.items.map((i) => (
                      <div key={i.id} draggable={canEdit && i.kind === "work"} onDragStart={(e) => e.dataTransfer.setData("text/plain", JSON.stringify({ id: i.id, from: m.id }))}
                        onClick={() => open(i)} title={`${i.start.slice(11)}–${i.end.slice(11)} ${i.title}`}
                        className={`mb-1 cursor-pointer truncate rounded px-1.5 py-0.5 text-[11px] ${i.kind === "event" ? "st-" + i.status : "text-white " + (PRIO[i.priority] || PRIO.normale)} ${i.status === "fait" ? "opacity-50 line-through" : ""}`}
                        data-testid={`team-item-${i.id}-${c.date}`}>
                        {i.start.slice(0, 10) === c.date ? i.start.slice(11) : "↳"} {i.kind === "event" ? "◆ " : ""}{i.title}
                      </div>))}
                    {c.hours > 0 && <div className={`text-right text-[10px] ${c.over ? "font-bold text-red-600" : "text-muted-foreground"}`} title={c.over ? `Plus de ${b.daily_max} h dans la journée` : ""}>{c.hours} h</div>}
                  </div>);
              })}
            </div>))}
          {!b.members.length && <div className="p-6 text-center text-sm text-muted-foreground">Aucune personne active dans l'équipe.</div>}
        </div>
      </div>
      <PlaceDialog place={place} team={b.members} onClose={() => setPlace(null)} onDone={load} />
    </div>
  );
}
