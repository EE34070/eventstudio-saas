import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, Plus, Trash2, Truck, Wand2, Shuffle, Eraser } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Section } from "@/components/common";
import { api, errMsg } from "@/lib/api";

const ko = (e) => toast.error(errMsg(e));
const sel = "h-9 rounded-lg border border-border bg-background px-2 text-xs";
export const M_STATUS = { a_planifier: "À planifier", planifiee: "Planifiée", chargee: "Chargée", en_route: "En route", livree: "Livrée", retiree: "Retirée", cloturee: "Clôturée" };
const FEEDBACK = [["", "Sans appréciation"], ["trois_quarts_vide", "Vide aux ¾"], ["moitie", "À moitié"], ["presque_plein", "Presque plein"], ["plein", "Plein"], ["pas_tenu", "Ça n'a pas tenu"]];

function Item({ i, m, write, act }) {
  const [qty, setQty] = useState(i.qty);
  useEffect(() => setQty(i.qty), [i.qty]);
  const targets = [{ id: "", name: "À placer" }, ...m.vehicles].filter((v) => v.id !== i.mv_id);
  return (
    <div draggable={write} onDragStart={(e) => e.dataTransfer.setData("text/plain", JSON.stringify({ product_id: i.product_id, from_mv: i.mv_id, qty: Number(qty) || i.qty }))}
      className="mb-1.5 rounded-lg border border-border bg-card p-2 text-xs" data-testid={`load-item-${i.mv_id ? "placed" : "unplaced"}-${i.product_id}`}>
      <div className="flex items-center justify-between gap-2"><b>{i.qty} × {i.name}</b>{i.mv_id ? <span className="text-muted-foreground">{i.share_pct != null ? `${i.share_pct} %` : "non mesuré"}</span> : null}</div>
      {i.placement === "random" && !i.verified && <button className="mt-1 rounded-full bg-amber-500/15 px-2 py-0.5 font-semibold text-amber-700 dark:text-amber-300" onClick={() => write && act("place", { product_id: i.product_id, qty: i.qty, from_mv: i.mv_id, to_mv: i.mv_id, verify: true })} data-testid={`load-random-${i.product_id}`}>placement aléatoire — à vérifier</button>}
      {write && <div className="mt-1.5 flex flex-wrap items-center gap-1">
        <input type="number" min="0" step="any" max={i.qty} value={qty} onChange={(e) => setQty(e.target.value)} className="h-7 w-16 rounded border border-border bg-background px-1" aria-label="Quantité" data-testid={`load-qty-${i.mv_id ? "placed" : "unplaced"}-${i.product_id}`} />
        {targets.map((t) => <button key={t.id} className="rounded-full border border-border px-2 py-0.5 hover:bg-secondary" onClick={() => act("place", { product_id: i.product_id, qty: Number(qty) || i.qty, from_mv: i.mv_id, to_mv: t.id })} data-testid={`load-move-${i.product_id}-${t.id || "unplaced"}`}>→ {t.name}</button>)}
        {i.mv_id && <button className="rounded-full border border-red-500/40 px-2 py-0.5 text-red-600" onClick={() => act("wont-fit", { mv_id: i.mv_id, product_id: i.product_id, qty: Number(qty) || i.qty })} data-testid={`load-wontfit-${i.product_id}`}>Ne rentre pas</button>}
      </div>}
    </div>
  );
}

export function MissionBoard({ m, vehicles, team, write, onChange }) {
  const [add, setAdd] = useState("");
  const done = (r) => onChange(r.data.mission || r.data);
  const act = (path, body) => api.post(`/logistics/missions/${m.id}/${path}`, body).then((r) => { done(r); r.data.proposals?.forEach((p) => toast.info(`Proposition : ${p.vehicle_name} → ${p.proposed} × ${p.product} (actuel ${p.current}), à valider dans Logistique > Capacités`)); }).catch(ko);
  const drop = (to) => (e) => { e.preventDefault(); const p = JSON.parse(e.dataTransfer.getData("text/plain") || "{}"); if (p.product_id && p.from_mv !== to) act("place", { ...p, to_mv: to }); };
  const status = (s, confirm = false) => api.patch(`/logistics/missions/${m.id}`, { status: s, confirm }).then(done).catch((e) => { const d = e?.response?.data?.detail; if (d?.code === "unplaced" && window.confirm(`${d.message}.`)) status(s, true); else if (d?.code !== "unplaced") ko(e); });
  const unplaced = m.items.filter((i) => !i.mv_id);
  return (
    <div className="rounded-2xl border border-border p-4" data-testid={`mission-${m.type}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Truck className="h-4 w-4" /><b>{m.type_label}</b><span className="text-sm text-muted-foreground">{m.date.slice(8)}/{m.date.slice(5, 7)} · arrivée {m.window_start || "?"}{m.window_end ? `–${m.window_end}` : ""} · {m.venue_name || "lieu à définir"}</span>
        <select className={`${sel} ml-auto`} value={m.status} onChange={(e) => status(e.target.value)} data-testid={`mission-status-${m.type}`}>{Object.entries(M_STATUS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
      </div>
      <p className="mt-1 text-xs text-muted-foreground" data-testid={`mission-travel-${m.type}`}>{m.depart_at ? `Début de chargement ${m.load_start_at.slice(11)} · départ ${m.depart_at.slice(11)} · trajet ${m.travel.minutes} min (${m.travel.km} km). ` : ""}{m.travel.source}</p>
      {m.alerts.map((a) => <p key={a} className="mt-2 rounded-lg border border-amber-500/50 bg-amber-500/10 p-2 text-xs font-semibold" data-testid="mission-alert"><AlertTriangle className="mr-1 inline h-3.5 w-3.5" />{a}</p>)}
      {write && <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => act("auto", { mode: "auto" })} data-testid={`mission-auto-${m.type}`}><Wand2 />Répartir automatiquement</Button>
        <Button size="sm" variant="outline" onClick={() => act("auto", { mode: "random" })} data-testid={`mission-random-${m.type}`}><Shuffle />Répartir le reste au hasard</Button>
        <Button size="sm" variant="ghost" onClick={() => act("auto", { mode: "clear" })} data-testid={`mission-clear-${m.type}`}><Eraser />Tout vider</Button>
        <select className={sel} value={add} onChange={(e) => setAdd(e.target.value)} data-testid={`mission-vehicle-select-${m.type}`}><option value="">+ Ajouter un véhicule</option>{vehicles.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</select>
        {add && <Button size="sm" onClick={() => { act("vehicles", { vehicle_id: add, driver_ids: [] }); setAdd(""); }} data-testid={`mission-vehicle-add-${m.type}`}><Plus />Ajouter</Button>}
      </div>}
      <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-3">
        <div onDragOver={(e) => e.preventDefault()} onDrop={drop("")} className="rounded-xl bg-secondary/50 p-3" data-testid={`mission-unplaced-${m.type}`}>
          <div className="mb-2 text-sm font-semibold">Matériel à placer ({unplaced.reduce((n, i) => n + i.qty, 0)})</div>
          {unplaced.map((i) => <Item key={i.id} i={i} m={m} write={write} act={act} />)}{!unplaced.length && <p className="text-xs text-muted-foreground">Tout est placé.</p>}
        </div>
        {m.vehicles.map((v) => (
          <div key={v.id} onDragOver={(e) => e.preventDefault()} onDrop={drop(v.id)} className="rounded-xl border border-border p-3" data-testid={`mission-vehicle-${v.name}`}>
            <div className="flex items-center justify-between gap-2 text-sm font-semibold"><span>{v.name}</span>{write && <button onClick={() => api.delete(`/logistics/missions/${m.id}/vehicles/${v.id}`).then(done).catch(ko)} aria-label="Retirer le véhicule"><Trash2 className="h-3.5 w-3.5" /></button>}</div>
            <div className="my-2 h-2 overflow-hidden rounded-full bg-secondary"><div className={v.fill_pct > 100 ? "h-full bg-red-600" : "h-full bg-primary"} style={{ width: `${Math.min(100, v.fill_pct)}%` }} /></div>
            <div className={`mb-2 text-xs ${v.fill_pct > 100 ? "font-semibold text-red-600" : "text-muted-foreground"}`} data-testid={`mission-fill-${v.name}`}>{v.fill_pct} %{v.unmeasured ? ` · + ${v.unmeasured} article(s) non mesuré(s)` : ""}</div>
            {m.items.filter((i) => i.mv_id === v.id).map((i) => <Item key={i.id} i={i} m={m} write={write} act={act} />)}
            {write && <select multiple className="mt-1 h-16 w-full rounded-lg border border-border bg-background p-1 text-xs" value={v.driver_ids || []} onChange={(e) => api.put(`/logistics/missions/${m.id}/vehicles/${v.id}`, { vehicle_id: v.vehicle_id, driver_ids: [...e.target.selectedOptions].map((o) => o.value) }).then(done).catch(ko)} aria-label="Chauffeurs" data-testid={`mission-drivers-${v.name}`}>{team.map((t) => <option key={t.id} value={t.id}>{t.name}{t.licences.length ? ` (${t.licences.join(", ")})` : ""}</option>)}</select>}
            {v.loaded_at ? <p className="mt-2 text-xs font-semibold text-emerald-700" data-testid={`mission-loaded-${v.name}`}>Véhicule chargé</p> : <div className="mt-2 flex gap-1"><select id={`fb-${v.id}`} className={sel} defaultValue="" data-testid={`mission-feedback-${v.name}`}>{FEEDBACK.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
              <Button size="sm" onClick={() => act(`vehicles/${v.id}/loaded`, { feedback: document.getElementById(`fb-${v.id}`).value })} data-testid={`mission-load-${v.name}`}>Véhicule chargé</Button></div>}
          </div>))}
      </div>
    </div>
  );
}

export function EventLogistics({ ev, write }) {
  const [d, setD] = useState(null);
  const version = JSON.stringify([(ev.equipment || []).map((l) => [l.equipment_id, l.qty]), ev.venue_id, ev.start]);
  const load = useCallback(() => api.get(`/events/${ev.id}/logistics`).then((r) => setD(r.data)).catch(() => {}), [ev.id]);
  useEffect(() => { load(); }, [load, version]);
  if (!d || (!d.missions.length && !d.to_deliver)) return null;
  return (
    <Section title="Logistique" testid="logistics-section" actions={write && <Button size="sm" variant="outline" onClick={() => api.post(`/events/${ev.id}/logistics/generate`).then((r) => { setD(r.data); toast.success(r.data.message); }).catch(ko)} data-testid="logistics-generate">{d.missions.length ? "Mettre à jour le plan" : "Générer le plan logistique"}</Button>}>
      {!d.missions.length ? <p className="text-sm text-muted-foreground">{d.to_deliver} article(s) à livrer : générez le plan pour créer les missions de livraison et de retrait.</p>
        : <div className="space-y-4">{d.missions.map((m) => <MissionBoard key={m.id} m={m} vehicles={d.vehicles} team={d.team} write={write} onChange={(nm) => setD({ ...d, missions: d.missions.map((x) => (x.id === nm.id ? nm : x)) })} />)}</div>}
    </Section>
  );
}
