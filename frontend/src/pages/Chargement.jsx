import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Truck, ChevronLeft, ChevronRight, Check, AlertTriangle, MapPin, Clock, Weight, Plus, Pencil, PackageCheck, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PageHeader, Loading, EmptyState, Meta, Field } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { dayKey, fmtDate } from "@/lib/constants";
import { useMe } from "@/context/MeContext";
import { EventRequirements } from "@/components/catalogue/Material";

const shiftDay = (d, n) => { const x = new Date(d + "T00:00"); x.setDate(x.getDate() + n); return dayKey(x); };
const EMPTY = { name: "", plate: "", capacity_kg: 0, volume_m3: 0, active: true };

function VehiclesDialog({ open, onOpenChange, vehicles, onSaved }) {
  const [f, setF] = useState(null);
  useEffect(() => { if (open) setF(null); }, [open]);
  const submit = async (e) => {
    e.preventDefault();
    const body = { name: f.name, plate: f.plate, capacity_kg: Number(f.capacity_kg) || 0, volume_m3: Number(f.volume_m3) || 0, active: f.active };
    try { f.id ? await api.put(`/vehicles/${f.id}`, body) : await api.post("/vehicles", body); toast.success("Véhicule enregistré"); setF(null); onSaved(); } catch (err) { toast.error(errMsg(err)); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-lg overflow-y-auto">
        <DialogHeader><DialogTitle className="text-xl font-bold">Véhicules</DialogTitle></DialogHeader>
        <div className="divide-y divide-border" data-testid="vehicles-list">
          {vehicles.map((v) => (
            <div key={v.id} className="flex items-center gap-3 py-2.5 text-sm" data-testid={`vehicle-row-${v.id}`}>
              <Truck className="h-5 w-5 shrink-0" />
              <div className="min-w-0 flex-1"><div className={`font-semibold ${v.active ? "" : "text-muted-foreground line-through"}`}>{v.name}</div><div className="text-xs text-muted-foreground">{v.plate || "—"} · {v.capacity_kg} kg · {v.volume_m3} m³</div></div>
              <Button size="icon" variant="ghost" onClick={() => setF(v)} data-testid={`vehicle-edit-${v.id}`}><Pencil /></Button>
            </div>
          ))}
        </div>
        {f ? (
          <form onSubmit={submit} className="grid grid-cols-2 gap-3" data-testid="vehicle-form">
            <Field label="Nom"><Input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} data-testid="vehicle-name-input" /></Field>
            <Field label="Immatriculation"><Input value={f.plate} onChange={(e) => setF({ ...f, plate: e.target.value })} data-testid="vehicle-plate-input" /></Field>
            <Field label="Charge utile (kg)"><Input type="number" min="0" value={f.capacity_kg} onChange={(e) => setF({ ...f, capacity_kg: e.target.value })} data-testid="vehicle-capacity-input" /></Field>
            <Field label="Volume (m³)"><Input type="number" min="0" step="any" value={f.volume_m3} onChange={(e) => setF({ ...f, volume_m3: e.target.value })} /></Field>
            <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} />Véhicule en service</label>
            <div className="col-span-2 flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setF(null)}>Annuler</Button><Button data-testid="vehicle-form-submit">Enregistrer</Button></div>
          </form>
        ) : <Button onClick={() => setF(EMPTY)} data-testid="vehicle-add-button"><Plus />Véhicule</Button>}
      </DialogContent>
    </Dialog>
  );
}

function Line({ lo, l, locked, call }) {
  const [open, setOpen] = useState(false);
  const [m, setM] = useState({ qty: l.missing_qty || 1, note: l.note || "" });
  const done = l.loaded_qty === l.qty;
  const path = `/loading/${lo.id}/lines/${l.equipment_id}`;
  const toggle = () => call(() => api.patch(path, { loaded_qty: done ? 0 : l.qty - l.missing_qty, missing_qty: done ? 0 : l.missing_qty, note: l.note }));
  const report = async (qty) => { if (await call(() => api.patch(path, { loaded_qty: Math.min(l.loaded_qty, l.qty - qty), missing_qty: qty, note: m.note }), qty ? "Manquant signalé" : "Signalement retiré")) setOpen(false); };
  const ok = l.loaded_qty + l.missing_qty === l.qty && l.loaded_qty > 0;
  return (
    <div className="py-3" data-testid={`load-line-${l.ref}`}>
      <div className="flex items-center gap-3">
        <button disabled={locked} onClick={toggle} data-testid={`load-check-${l.ref}`} aria-label={`Charger ${l.name}`}
          className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full border transition-colors ${done || ok ? "border-foreground bg-foreground text-background" : "border-border hover:border-foreground/50"}`}>
          {(done || ok) && <Check className="h-5 w-5" />}
        </button>
        <div className="min-w-0 flex-1">
          <div className={`truncate text-[15px] font-semibold ${done ? "text-muted-foreground line-through" : ""}`}>{l.qty} × {l.name}</div>
          <div className="truncate text-[13px] text-[#737373]">{l.ref} · {l.category}{l.checked_by ? ` · ${l.checked_by}` : ""}</div>
          {l.missing_qty > 0 && <div className="mt-1 flex items-center gap-1.5 text-[13px] font-semibold text-red-600 dark:text-red-400" data-testid={`load-missing-${l.ref}`}><AlertTriangle className="h-4 w-4" />{l.missing_qty} manquant(s){l.note ? ` — ${l.note}` : ""}</div>}
        </div>
        {!locked && <Button size="sm" variant="ghost" onClick={() => setOpen(!open)} data-testid={`load-report-${l.ref}`}><AlertTriangle />Manquant</Button>}
      </div>
      {open && !locked && (
        <div className="mt-3 flex flex-wrap items-end gap-2 sm:pl-14" data-testid={`load-report-form-${l.ref}`}>
          <Field label="Quantité manquante"><Input type="number" min="0" step="any" max={l.qty} className="w-28" value={m.qty} onChange={(e) => setM({ ...m, qty: e.target.value })} data-testid={`load-missing-qty-${l.ref}`} /></Field>
          <Field label="Précision" className="min-w-40 flex-1"><Input placeholder="Introuvable, en panne…" value={m.note} onChange={(e) => setM({ ...m, note: e.target.value })} data-testid={`load-missing-note-${l.ref}`} /></Field>
          <Button size="sm" onClick={() => report(Math.max(1, Math.min(l.qty, Number(m.qty) || 1)))} data-testid={`load-missing-submit-${l.ref}`}>Signaler</Button>
          {l.missing_qty > 0 && <Button size="sm" variant="ghost" onClick={() => report(0)} data-testid={`load-missing-clear-${l.ref}`}>Retirer</Button>}
        </div>
      )}
    </div>
  );
}

function LoadingCard({ lo, vehicles, call, write }) {
  const locked = lo.status === "charge";
  const loaded = lo.lines.reduce((n, l) => n + l.loaded_qty, 0);
  const total = lo.lines.reduce((n, l) => n + l.qty, 0);
  const missing = lo.lines.reduce((n, l) => n + l.missing_qty, 0);
  const weight = Math.round(lo.lines.reduce((n, l) => n + l.qty * (l.weight_kg || 0), 0));
  const complete = lo.lines.every((l) => l.loaded_qty + l.missing_qty === l.qty);
  return (
    <div className="card-soft p-6" data-testid={`loading-card-${lo.event_code}`}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <Link to={`/evenements/${lo.event_id}`} className="block truncate text-lg font-semibold hover:underline">{lo.event_title}</Link>
          <div className="truncate text-sm text-muted-foreground">{lo.event_code} · {lo.venue_name}{lo.venue_city ? `, ${lo.venue_city}` : ""}</div>
        </div>
        {locked && <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-600 dark:text-emerald-400" data-testid={`loading-validated-${lo.event_code}`}><PackageCheck className="h-4 w-4" />Chargé</span>}
      </div>
      <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1">
        <Meta icon={Clock}>Départ {lo.departure.slice(11, 16)}</Meta>
        <Meta icon={PackageCheck} testid={`loading-progress-${lo.event_code}`}>{loaded} / {total} chargé(s)</Meta>
        <Meta icon={Weight}>{weight} kg</Meta>
        {missing > 0 && <Meta icon={AlertTriangle}>{missing} manquant(s)</Meta>}
        <Meta icon={MapPin}>{lo.venue_city || "—"}</Meta>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-secondary"><div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${total ? (loaded / total) * 100 : 0}%` }} /></div>
      <div className="mt-3 divide-y divide-border">
        {!lo.lines.length && <div className="py-3 text-sm text-muted-foreground">Aucun matériel sur cet événement.</div>}
        {lo.lines.map((l) => <Line key={l.equipment_id} lo={lo} l={l} locked={locked} call={call} />)}
      </div>
      {lo.transfers?.length > 0 && <div className="mt-3 rounded-xl border border-amber-500/50 bg-amber-500/10 p-3 text-sm" data-testid={`loading-transfers-${lo.event_code}`}><b>Matériel réemployé sur place — ne pas charger en double</b>{lo.transfers.map((t) => <div key={t.time + t.title} className="text-xs">{t.time} · {t.title} — {t.description}</div>)}</div>}
      <EventRequirements eventId={lo.event_id} checklist />
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {write && !locked && (
          <Select value={lo.vehicle_id || "none"} onValueChange={(v) => call(() => api.put(`/loading/${lo.id}/vehicle`, { vehicle_id: v === "none" ? "" : v }), "Véhicule affecté")}>
            <SelectTrigger className="h-10 w-56 rounded-full" data-testid={`loading-vehicle-select-${lo.event_code}`}><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="none">Sans véhicule</SelectItem>{vehicles.filter((v) => v.active || v.id === lo.vehicle_id).map((v) => <SelectItem key={v.id} value={v.id}>{v.name}</SelectItem>)}</SelectContent>
          </Select>
        )}
        {!locked && <Button className="ml-auto" disabled={!complete || !lo.lines.length} onClick={() => call(() => api.post(`/loading/${lo.id}/status`, { status: "charge" }), "Chargement validé")} data-testid={`loading-validate-${lo.event_code}`}><Check />Valider le chargement</Button>}
        {locked && write && <Button className="ml-auto" variant="ghost" onClick={() => call(() => api.post(`/loading/${lo.id}/status`, { status: "en_cours" }), "Chargement rouvert")} data-testid={`loading-reopen-${lo.event_code}`}><RotateCcw />Rouvrir</Button>}
      </div>
    </div>
  );
}

function MissionLoad({ m, reload }) {
  const ko = (err) => toast.error(errMsg(err));
  const unplaced = m.items.filter((i) => !i.mv_id).reduce((n, i) => n + i.qty, 0);
  return (
    <div className="card-soft p-6" data-testid={`mission-load-${m.event_code}-${m.type}`}>
      <Link to={`/evenements/${m.event_id}`} className="block truncate text-lg font-semibold hover:underline">{m.event_title}</Link>
      <div className="text-sm text-muted-foreground">{m.type_label} · {m.venue_name}{m.load_start_at ? ` · chargement ${m.load_start_at.slice(11)}, départ ${m.depart_at.slice(11)}` : m.window_start ? ` · arrivée ${m.window_start}` : ""}</div>
      {m.alerts.map((a) => <p key={a} className="mt-2 flex items-center gap-1.5 text-[13px] font-semibold text-amber-600"><AlertTriangle className="h-4 w-4" />{a}</p>)}
      {unplaced > 0 && <p className="mt-2 text-[13px] font-semibold text-red-600" data-testid={`mission-load-unplaced-${m.event_code}`}>{unplaced} article(s) à placer : répartissez-les dans l'onglet Matériel de l'événement.</p>}
      {m.vehicles.map((v) => (
        <div key={v.id} className="mt-4" data-testid={`mission-load-vehicle-${v.name}`}>
          <div className="flex items-center gap-2 text-sm font-semibold"><Truck className="h-4 w-4" />{v.name}<span className="font-normal text-muted-foreground">{v.fill_pct} %{v.drivers.length ? ` · ${v.drivers.join(", ")}` : ""}</span></div>
          <div className="divide-y divide-border">{m.items.filter((i) => i.mv_id === v.id).map((i) => { const done = i.loaded_qty >= i.qty; return (
            <button key={i.id} disabled={!!v.loaded_at} onClick={() => api.patch(`/logistics/missions/${m.id}/items/${i.id}`, { loaded_qty: done ? 0 : i.qty }).then(reload).catch(ko)} className="flex w-full items-center gap-3 py-2.5 text-left" data-testid={`mission-check-${i.ref}`}>
              <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full border ${done ? "border-foreground bg-foreground text-background" : "border-border"}`}>{done && <Check className="h-4 w-4" />}</span>
              <span className={`text-[15px] font-semibold ${done ? "text-muted-foreground line-through" : ""}`}>{i.qty} × {i.name}</span></button>); })}</div>
          {v.loaded_at ? <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-600" data-testid={`mission-load-done-${v.name}`}><PackageCheck className="h-4 w-4" />Véhicule chargé</span>
            : <Button size="sm" className="mt-2" onClick={() => api.post(`/logistics/missions/${m.id}/vehicles/${v.id}/loaded`, { feedback: "" }).then(reload).catch(ko)} data-testid={`mission-load-validate-${v.name}`}><Check />Véhicule chargé</Button>}
        </div>))}
      {!m.vehicles.length && <p className="mt-3 text-sm text-muted-foreground">Aucun véhicule affecté à cette mission.</p>}
    </div>
  );
}

export default function Chargement() {
  const [ms, setMs] = useState([]);
  const { can } = useMe();
  const [day, setDay] = useState(dayKey(new Date()));
  const [data, setData] = useState(null);
  const [fleet, setFleet] = useState(false);
  const load = useCallback(() => { api.get("/logistics/day", { params: { day } }).then((r) => setMs(r.data.missions.filter((m) => m.type !== "retrait"))).catch(() => setMs([])); return api.get("/loading", { params: { day } }).then((r) => setData(r.data)).catch((err) => toast.error(errMsg(err))); }, [day]);
  useEffect(() => { setData(null); load(); }, [load]);
  const call = async (fn, msg) => { try { await fn(); if (msg) toast.success(msg); await load(); return true; } catch (err) { toast.error(errMsg(err)); return false; } };
  const withMission = new Set(ms.map((m) => m.event_id));
  if (data && !data.all) data.all = data.loadings;
  if (data) data.loadings = data.all.filter((l) => !withMission.has(l.event_id) || l.status === "charge");
  const groups = data ? [...data.vehicles.filter((v) => data.loadings.some((l) => l.vehicle_id === v.id)), { id: "", name: "Sans véhicule" }]
    .map((v) => ({ v, items: data.loadings.filter((l) => (l.vehicle_id || "") === v.id) })).filter((g) => g.items.length) : [];
  return (
    <div>
      <PageHeader title="Chargement" subtitle={data ? `${data.loadings.length} chargement(s) le ${fmtDate(day, { weekday: "long", day: "numeric", month: "long" })} — check-list par véhicule.` : "Check-list par véhicule."}
        actions={can("catalog:write") && <Button onClick={() => setFleet(true)} data-testid="vehicles-button"><Truck />Véhicules</Button>} />
      <div className="mb-6 flex flex-wrap items-center gap-2">
        <Button size="icon" onClick={() => setDay(shiftDay(day, -1))} data-testid="loading-prev-day" aria-label="Jour précédent"><ChevronLeft /></Button>
        <Button onClick={() => setDay(dayKey(new Date()))} data-testid="loading-today">Aujourd'hui</Button>
        <Button size="icon" onClick={() => setDay(shiftDay(day, 1))} data-testid="loading-next-day" aria-label="Jour suivant"><ChevronRight /></Button>
        <Input type="date" className="h-10 w-44 rounded-full px-4" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} data-testid="loading-day-input" />
      </div>
      {ms.length > 0 && <div className="mb-8 grid grid-cols-1 gap-4 lg:grid-cols-2" data-testid="mission-load-list">{ms.map((m) => <MissionLoad key={m.id} m={m} reload={load} />)}</div>}
      {!data ? <Loading /> : !groups.length ? (ms.length ? null :  <EmptyState icon={Truck} title="Aucun chargement ce jour" text="Les événements confirmés ou en préparation apparaissent ici le jour de leur montage." />) : (
        <div className="space-y-8" data-testid="loading-groups">
          {groups.map(({ v, items }) => {
            const kg = Math.round(items.reduce((n, lo) => n + lo.lines.reduce((s, l) => s + l.qty * (l.weight_kg || 0), 0), 0));
            const over = v.capacity_kg > 0 && kg > v.capacity_kg;
            return (
              <section key={v.id || "none"} data-testid={`vehicle-group-${v.id || "none"}`}>
                <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1">
                  <h2 className="flex items-center gap-2 text-lg font-semibold"><Truck className="h-5 w-5" />{v.name}</h2>
                  {v.plate && <span className="text-[13px] text-[#737373]">{v.plate}</span>}
                  {v.id && <span className={`text-[13px] ${over ? "font-semibold text-red-600 dark:text-red-400" : "text-[#737373]"}`} data-testid={`vehicle-weight-${v.id}`}>{kg} / {v.capacity_kg} kg{over ? " — surcharge" : ""}</span>}
                </div>
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">{items.map((lo) => <LoadingCard key={lo.id} lo={lo} vehicles={data.vehicles} call={call} write={can("events:write")} />)}</div>
              </section>
            );
          })}
        </div>
      )}
      <VehiclesDialog open={fleet} onOpenChange={setFleet} vehicles={data?.vehicles || []} onSaved={load} />
    </div>
  );
}
