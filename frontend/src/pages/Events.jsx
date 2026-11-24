import { DjDot } from "@/components/dj/DjPlanning";
import { TrashBtn, Pick, BulkDelete } from "@/components/Trash";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Plus, LayoutGrid, List, AlertTriangle, MapPin, Search, Package } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader, StatusBadge, ModuleBadge, Loading, EmptyState } from "@/components/common";
import EventFormDialog from "@/components/events/EventFormDialog";
import { api, errMsg } from "@/lib/api";
import { STATUSES, MODULES, fmtEur, fmtDate } from "@/lib/constants";
import { useMe } from "@/context/MeContext";

function KanbanCard({ e, draggable }) {
  return (
    <Link to={`/evenements/${e.id}`} draggable={draggable} onDragStart={(ev) => ev.dataTransfer.setData("text/plain", e.id)}
      data-testid={`kanban-card-${e.id}`} className="block rounded-xl border border-border bg-card p-3.5 hover-lift">
      <div className="flex items-start justify-between gap-2">
        <span className="font-mono text-[10.5px] text-muted-foreground">{e.code}</span>
        {e.conflicts_count > 0 && <span className="flex items-center gap-1 rounded bg-red-50 px-1.5 text-[10.5px] font-semibold text-red-700"><AlertTriangle className="h-3 w-3" />Conflit</span>}
        {e.shortages_count > 0 && <span className="rounded bg-red-600 px-1.5 text-[10.5px] font-semibold text-white" data-testid={`event-shortages-kanban-${e.id}`}>{e.shortages_count} manque{e.shortages_count > 1 ? "s" : ""}</span>}
      </div>
      <div className="mt-1 text-[13.5px] font-semibold leading-snug">{e.title}<DjDot id={e.id} /></div>
      <div className="mt-1 text-xs text-muted-foreground">{e.client_name}</div>
      <div className="mt-2.5 flex items-center gap-1.5 text-xs text-muted-foreground"><MapPin className="h-3 w-3" />{e.date_tbc ? "Date à confirmer" : fmtDate(e.start, { day: "numeric", month: "short", year: "2-digit" })} · {e.venue_city || "—"}</div>
      <div className="mt-2.5 flex flex-wrap gap-1">{e.modules.map((m) => <ModuleBadge key={m} module={m} />)}</div>
      <div className="mt-3 flex items-center justify-between border-t border-border pt-2.5">
        <div className="flex -space-x-1.5">
          {e.team.slice(0, 4).map((t) => <span key={t.member_id} title={t.name} className="flex h-6 w-6 items-center justify-center rounded-full border-2 border-white text-[9.5px] font-bold text-white" style={{ background: t.color }}>{t.name.split(" ").map((x) => x[0]).join("").slice(0, 2)}</span>)}
          {!e.team.length && <span className="text-[11px] text-muted-foreground">Aucune équipe</span>}
        </div>
        {e.amount_ht != null ? <span className="text-[13px] font-semibold">{fmtEur(e.amount_ht)}</span> : <span className="flex items-center gap-1 text-xs text-muted-foreground"><Package className="h-3 w-3" />{e.equipment_count}</span>}
      </div>
    </Link>
  );
}

function Kanban({ events, onMove, canWrite }) {
  const [over, setOver] = useState(null);
  return (
    <div className="flex gap-4 overflow-x-auto pb-4 scroll-thin" data-testid="events-kanban">
      {STATUSES.map((s) => {
        const items = events.filter((e) => e.status === s.id);
        return (
          <div key={s.id} data-testid={`kanban-column-${s.id}`}
            onDragOver={(ev) => { if (canWrite) { ev.preventDefault(); setOver(s.id); } }} onDragLeave={() => setOver(null)}
            onDrop={(ev) => { ev.preventDefault(); setOver(null); onMove(ev.dataTransfer.getData("text/plain"), s.id); }}
            className={`w-[272px] shrink-0 rounded-2xl p-2.5 transition-colors ${over === s.id ? "bg-accent ring-2 ring-primary/30" : "bg-secondary/60"}`}>
            <div className="mb-2.5 flex items-center justify-between px-1.5 pt-1"><StatusBadge status={s.id} /><span className="text-xs font-semibold text-muted-foreground">{items.length}</span></div>
            <div className="space-y-2.5 min-h-[80px]">{items.map((e) => <KanbanCard key={e.id} e={e} draggable={canWrite} />)}</div>
          </div>
        );
      })}
    </div>
  );
}

function EventTable({ events, reload }) {
  const nav = useNavigate();
  const [pick, setPick] = useState([]);
  return (
    <div className="card-soft overflow-x-auto" data-testid="events-table">
      <div className="p-2 empty:hidden"><BulkDelete kind="event" picked={pick} onDone={() => { setPick([]); reload(); }} /></div><Table>
        <TableHeader><TableRow><TableHead>Code</TableHead><TableHead>Événement</TableHead><TableHead>Date</TableHead><TableHead>Lieu</TableHead><TableHead>Organisateur</TableHead><TableHead>Modules</TableHead><TableHead>Statut</TableHead><TableHead className="text-right">Montant HT</TableHead><TableHead /></TableRow></TableHeader>
        <TableBody>
          {events.map((e) => (
            <TableRow key={e.id} className="cursor-pointer" onClick={() => nav(`/evenements/${e.id}`)} data-testid={`event-row-${e.id}`}>
              <TableCell className="font-mono text-xs"><Pick id={e.id} pick={pick} setPick={setPick} />{e.code}</TableCell>
              <TableCell><div className="font-medium flex items-center gap-1.5">{e.title}<DjDot id={e.id} />{e.conflicts_count > 0 && <AlertTriangle className="h-3.5 w-3.5 text-red-600" />}{e.shortages_count > 0 && <span className="rounded-full bg-red-600 px-1.5 text-[10px] font-bold text-white" title="Manques de matériel à traiter" data-testid={`event-shortages-${e.id}`}>{e.shortages_count}</span>}</div><div className="text-xs text-muted-foreground">{e.client_name}</div></TableCell>
              <TableCell className="whitespace-nowrap">{e.date_tbc ? "Date à confirmer" : fmtDate(e.start)}</TableCell>
              <TableCell>{e.venue_name}<div className="text-xs text-muted-foreground">{e.venue_city}</div></TableCell>
              <TableCell data-testid={`event-planner-${e.id}`}>{e.planner_name || "—"}</TableCell>
              <TableCell><div className="flex flex-wrap gap-1">{e.modules.map((m) => <ModuleBadge key={m} module={m} />)}</div></TableCell>
              <TableCell><StatusBadge status={e.status} /></TableCell>
              <TableCell className="text-right font-medium">{e.amount_ht != null ? fmtEur(e.amount_ht) : "—"}</TableCell><TableCell><TrashBtn kind="event" id={e.id} name={e.title} onDone={reload} /></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export default function Events() {
  const { can } = useMe();
  const [params, setParams] = useSearchParams();
  const [events, setEvents] = useState(null);
  const [view, setView] = useState(() => localStorage.getItem("events-view") || (window.innerWidth < 768 ? "list" : "kanban"));
  const [q, setQ] = useState("");
  const [module, setModule] = useState("all");
  const [open, setOpen] = useState(false);
  const [planner, setPlanner] = useState("all");
  const [planners, setPlanners] = useState([]);
  useEffect(() => { if (can("contacts:read")) api.get("/organizers").then((r) => setPlanners(r.data)).catch(() => {}); }, [can]);
  const nav = useNavigate();
  const status = params.get("status") || "all";

  const load = useCallback(() => {
    api.get("/events", { params: { q: q || undefined, module: module === "all" ? undefined : module, planner: planner === "all" ? undefined : planner, status: view === "list" && status !== "all" ? status : undefined } }).then((r) => setEvents(r.data));
  }, [q, module, status, view, planner]);
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t); }, [load]);
  useEffect(() => { localStorage.setItem("events-view", view); }, [view]);

  const move = async (id, st) => {
    const ev = events.find((e) => e.id === id);
    if (!ev || ev.status === st) return;
    try {
      await api.post(`/events/${id}/status`, { status: st });
      toast.success(`${ev.code} → statut mis à jour`);
      load();
    } catch (err) {
      toast.error(errMsg(err));
    }
  };

  return (
    <div>
      <PageHeader title="Événements" subtitle={`${events?.length ?? 0} événement(s) — de la demande à la clôture.`} />
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input data-testid="events-search-input" className="pl-9 bg-card" placeholder="Rechercher…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <Select value={module} onValueChange={setModule}><SelectTrigger className="w-48 bg-card" data-testid="events-module-filter"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">Tous les modules</SelectItem>{MODULES.map((m) => <SelectItem key={m.id} value={m.id}>{m.label}</SelectItem>)}</SelectContent></Select>
        {planners.length > 0 && <Select value={planner} onValueChange={setPlanner}><SelectTrigger className="w-52 bg-card" data-testid="events-planner-filter"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">Tous les organisateurs</SelectItem>{planners.map((p) => <SelectItem key={p.contact_id} value={p.contact_id}>{p.display_name}</SelectItem>)}</SelectContent></Select>}
        {view === "list" && (
          <Select value={status} onValueChange={(v) => setParams(v === "all" ? {} : { status: v })}><SelectTrigger className="w-44 bg-card" data-testid="events-status-filter"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="all">Tous les statuts</SelectItem>{STATUSES.map((s) => <SelectItem key={s.id} value={s.id}>{s.label}</SelectItem>)}</SelectContent></Select>
        )}
        <div className="ml-auto flex rounded-xl border border-border bg-card p-1">
          <button data-testid="view-kanban-button" onClick={() => setView("kanban")} className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium ${view === "kanban" ? "bg-foreground text-background" : "text-muted-foreground"}`}><LayoutGrid className="h-3.5 w-3.5" />Kanban</button>
          <button data-testid="view-list-button" onClick={() => setView("list")} className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium ${view === "list" ? "bg-foreground text-background" : "text-muted-foreground"}`}><List className="h-3.5 w-3.5" />Liste</button>
        </div>
      </div>
      {!events ? <Loading /> : !events.length ? <EmptyState title="Aucun événement" text="Ajustez vos filtres ou créez un nouvel événement." /> :
        view === "kanban" ? <Kanban events={events} onMove={move} canWrite={can("events:write")} /> : <EventTable events={events} reload={load} />}
      <EventFormDialog open={open} onOpenChange={setOpen} onSaved={(r) => nav(`/evenements/${r.id}`)} />
    </div>
  );
}
